#!/usr/bin/env python3
"""55_observe.py: read-only look at what the endpoint is doing. Run it after 50 and again after 60 and 70.

Shows three things:
  1. Endpoint status from DescribeEndpoint.
  2. CloudWatch metrics for the last N minutes: GPU memory, GPU utilisation, host memory, invocations, latency.
  3. Container log lines that matter for memory and batching (KV cache size, maximum concurrency, preemption,
     errors). Use --all-logs to see every line.

What to look for: GPUMemoryUtilization sits near 90 percent even when idle, because vLLM reserves its
KV cache when it starts. The model does not "use" that memory in the sense of needing it. Compare the
container's own "Maximum concurrency for N tokens per request" line with your arithmetic in README section 2.

If .state.json records a deploy in another Region, account or prefix than this shell points at, the
script stops and says so. An exported AWS_REGION overrides config.env.

Creates nothing. Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Any, Callable

import kitlib
from kitlib import Aws, Config

# Namespaces and metric names: https://docs.aws.amazon.com/sagemaker/latest/dg/monitoring-cloudwatch.html (read 2026-10-07).
INSTANCE_METRICS = [  # namespace "/aws/sagemaker/Endpoints", unit Percent, GPU values are multiplied by GPU count
    "GPUMemoryUtilization", "GPUUtilization", "MemoryUtilization", "CPUUtilization",
]
INVOCATION_METRICS = [  # namespace "AWS/SageMaker"
    ("Invocations", "Sum", "count"),
    ("ModelLatency", "Average", "microseconds"),
    ("OverheadLatency", "Average", "microseconds"),
    ("InvocationModelErrors", "Sum", "count"),
]

# "Maximum concurrency for %s tokens per request" and "Available KV cache memory: %s GiB" are log format
# strings in vLLM v0.30.0 (vllm/v1/core/kv_cache_utils.py, vllm/v1/worker/gpu_worker.py, read 2026-10-07).
# The other patterns are broad on purpose.
INTERESTING = re.compile(
    r"Maximum concurrency|KV cache|kv-cache-memory|preempt|out of memory|OutOfMemory|CUDA|error|Traceback|"
    r"vLLM server arguments|non-default args|Application startup complete|max_model_len|Loading weights took|"
    r"Model loading took",
    re.IGNORECASE,
)


def summarise_datapoints(datapoints: list[dict[str, Any]], statistic: str) -> str:
    if not datapoints:
        return "no data yet (metrics appear at 1-minute granularity, a few minutes behind)"
    ordered = sorted(datapoints, key=lambda point: point["Timestamp"])
    values = [float(point[statistic]) for point in ordered if statistic in point]
    if not values:
        return "no data for this statistic"
    if statistic == "Sum":
        return f"total {sum(values):.0f} over {len(values)} minute(s), latest minute {values[-1]:.0f}"
    return f"latest {values[-1]:.1f}, min {min(values):.1f}, max {max(values):.1f} over {len(values)} minute(s)"


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print) -> int:
    endpoint_name = args.endpoint_name or cfg.endpoint_name
    now = kitlib.utc_now()
    start = now - dt.timedelta(minutes=args.minutes)
    state = kitlib.load_state(args.state_path)
    account = kitlib.caller_account(aws)
    kitlib.require_state_matches(state, cfg, account, args.state_path.name)

    # DescribeEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeEndpoint.html (read 2026-10-07)
    try:
        description = aws.call("sagemaker", "describe_endpoint", EndpointName=endpoint_name)
    except Exception as exc:  # noqa: BLE001 - classified just below
        if not kitlib.is_not_found(exc):
            raise
        description = {}
        out(f"Endpoint {endpoint_name} does not exist in {kitlib.scope_text(cfg.region, account, cfg.prefix)}. "
            "Logs may still exist; continuing.")
    if description:
        out(f"Endpoint {endpoint_name}: status {description.get('EndpointStatus')}")
        if description.get("FailureReason"):
            out(f"FailureReason: {description['FailureReason']}")

    if not args.logs_only:
        out("")
        out(f"CloudWatch metrics, last {args.minutes} minutes:")
        dimensions = [{"Name": "EndpointName", "Value": endpoint_name}, {"Name": "VariantName", "Value": kitlib.VARIANT_NAME}]
        for metric in INSTANCE_METRICS:
            # GetMetricStatistics: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html (read 2026-10-07)
            response = aws.call("cloudwatch", "get_metric_statistics", Namespace="/aws/sagemaker/Endpoints",
                                MetricName=metric, Dimensions=dimensions, StartTime=start, EndTime=now,
                                Period=60, Statistics=["Average"])
            if response is not None:
                out(f"  {metric:<22} percent:      {summarise_datapoints(response.get('Datapoints', []), 'Average')}")
        for metric, statistic, unit in INVOCATION_METRICS:
            # GetMetricStatistics: same page as above.
            response = aws.call("cloudwatch", "get_metric_statistics", Namespace="AWS/SageMaker",
                                MetricName=metric, Dimensions=dimensions, StartTime=start, EndTime=now,
                                Period=60, Statistics=[statistic])
            if response is not None:
                out(f"  {metric:<22} {unit + ':':<13} {summarise_datapoints(response.get('Datapoints', []), statistic)}")

    if not args.metrics_only:
        out("")
        log_minutes = args.log_minutes if args.log_minutes is not None else max(args.minutes, 120)
        log_start = now - dt.timedelta(minutes=log_minutes)
        out(f"Container log lines from {cfg.log_group_name}, last {log_minutes} minutes"
            f"{'' if args.all_logs else ' (filtered; --all-logs shows everything)'}:")
        shown = scanned = pages = 0
        token: str | None = None
        while pages < args.max_log_pages:
            params: dict[str, Any] = {"logGroupName": cfg.log_group_name if not args.endpoint_name
                                      else f"/aws/sagemaker/Endpoints/{endpoint_name}",
                                      "startTime": int(log_start.timestamp() * 1000), "limit": 1000}
            if token:
                params["nextToken"] = token
            try:
                # FilterLogEvents: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_FilterLogEvents.html (read 2026-10-07)
                page = aws.call("logs", "filter_log_events", **params)
            except Exception as exc:  # noqa: BLE001 - classified just below
                if kitlib.error_code(exc) != "ResourceNotFoundException":
                    raise
                out("  No log group yet. It is created when the container first writes a line.")
                break
            if page is None:
                break
            pages += 1
            for event in page.get("events", []):
                scanned += 1
                message = str(event.get("message", "")).rstrip()
                if args.all_logs or INTERESTING.search(message):
                    shown += 1
                    out("  " + message[:400])
            token = page.get("nextToken")
            if not token:
                break
        if not aws.dry_run:
            out(f"  ({shown} line(s) shown of {scanned} scanned in {pages} page(s))")

    out("")
    if aws.dry_run:
        out(f"DRY RUN finished: {aws.calls_printed} AWS call(s) printed, 0 made.")
        return 0
    for line in kitlib.billing_lines(state, kitlib.utc_now()):
        out(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "")
    parser.add_argument("--minutes", type=int, default=30, help="Metric window (default 30).")
    parser.add_argument("--log-minutes", type=int, default=None, help="Log window (default: the larger of --minutes and 120).")
    parser.add_argument("--logs-only", action="store_true")
    parser.add_argument("--metrics-only", action="store_true")
    parser.add_argument("--all-logs", action="store_true", help="Print every log line, not only the filtered ones.")
    parser.add_argument("--max-log-pages", type=int, default=5, help="At most this many pages of 1000 log events (default 5).")
    parser.add_argument("--endpoint-name", default=None, help="Default: <KIT_PREFIX>-kita-endpoint.")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.load_config()
    return run(args, cfg, Aws(cfg.region, args.dry_run))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
