#!/usr/bin/env python3
"""40_enable_observability.py: send the runtime's usage logs, application logs and
(optionally) traces to CloudWatch, so a real session cost can be read back.

AgentCore Runtime publishes three log types for a runtime, which you switch on
with CloudWatch Logs "deliveries":
  USAGE_LOGS        per-session vCPU-hours and GB-hours at 1-second granularity
  APPLICATION_LOGS  one record per invocation, with request and response payloads
  TRACES            spans, delivered to X-Ray / CloudWatch Transaction Search
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html  (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html       (read 2026-10-07)

Creates: two log groups, up to three delivery sources, up to three delivery
destinations and up to three deliveries, all named <prefix>-kitc-*.

TRACES is set up only when CloudWatch Transaction Search is already on in the
account. This script never turns Transaction Search on: that is an account-wide
setting and the choice is yours (README section 3).

Safe to run again. Each of the three deliveries is recorded in .state.json as
soon as it exists; a second run creates only the ones that are missing, so a
run that failed half way can simply be repeated.

Usage:
    python 40_enable_observability.py --dry-run
    python 40_enable_observability.py --i-understand-this-bills
    python 40_enable_observability.py --i-understand-this-bills --include-app-logs
"""
from __future__ import annotations

import kitlib


def _find_delivery_id(aws: kitlib.Aws, source_name: str) -> str | None:
    token = None
    while True:
        params = {"limit": 50}
        if token:
            params["nextToken"] = token
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeDeliveries.html (read 2026-10-07)
        page = aws.call("logs", "describe_deliveries", dry_result={"deliveries": []}, **params)
        for delivery in page.get("deliveries", []):
            if delivery.get("deliverySourceName") == source_name:
                return delivery.get("id")
        token = page.get("nextToken")
        if not token:
            return None


def _delivery(aws: kitlib.Aws, cfg: kitlib.Config, kind: str, log_type: str, runtime_arn: str,
              destination_type: str, log_group_arn: str | None, out) -> dict:
    source_name, dest_name = cfg.delivery_names(kind)
    # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutDeliverySource.html (read 2026-10-07)
    # logType values for "Amazon Bedrock AgentCore Runtime" are APPLICATION_LOGS, USAGE_LOGS and
    # TRACES (PutDeliverySource page, read 2026-10-07).
    # UNVERIFIED: that the delivery source for a runtime takes the runtime ARN. AWS's example
    # function is written for any AgentCore resource and does not show a runtime ARN.
    aws.call("logs", "put_delivery_source", name=source_name, resourceArn=runtime_arn,
             logType=log_type, tags=dict(kitlib.TAGS),
             dry_result={"deliverySource": {"name": source_name}})
    dest_args = {"name": dest_name, "deliveryDestinationType": destination_type,
                 "tags": dict(kitlib.TAGS)}
    if log_group_arn:
        dest_args["deliveryDestinationConfiguration"] = {"destinationResourceArn": log_group_arn}
    # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutDeliveryDestination.html (read 2026-10-07)
    dest = aws.call("logs", "put_delivery_destination",
                    dry_result={"deliveryDestination": {
                        "name": dest_name,
                        "arn": f"arn:aws:logs:{cfg.region}:{kitlib.DRY_ACCOUNT}:delivery-destination:{dest_name}"}},
                    **dest_args)
    dest_arn = dest["deliveryDestination"]["arn"]
    try:
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_CreateDelivery.html (read 2026-10-07)
        made = aws.call("logs", "create_delivery", deliverySourceName=source_name,
                        deliveryDestinationArn=dest_arn, tags=dict(kitlib.TAGS),
                        dry_result={"delivery": {"id": "dryrun"}})
        delivery_id = made["delivery"]["id"]
    except Exception as exc:
        # An earlier run got this far and was cut off before it could record the delivery.
        if aws.error_code(exc) != "ConflictException":
            raise
        delivery_id = _find_delivery_id(aws, source_name)
        if not delivery_id:
            raise
        out(f"[logs] {log_type}: the delivery already exists, recording it")
    out(f"[logs] {log_type} -> {destination_type}: delivery {delivery_id}")
    return {"kind": kind, "log_type": log_type, "source": source_name, "destination": dest_name,
            "delivery_id": delivery_id}


def _ensure_log_group(aws: kitlib.Aws, name: str, out) -> None:
    try:
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_CreateLogGroup.html (read 2026-10-07)
        aws.call("logs", "create_log_group", logGroupName=name, tags=dict(kitlib.TAGS))
        out(f"[logs] created log group {name}")
    except Exception as exc:
        if aws.error_code(exc) != "ResourceAlreadyExistsException":
            raise
        out(f"[logs] log group {name} already exists, reusing it")
    # Keep what this kit writes for one week at most, in case teardown is forgotten.
    # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutRetentionPolicy.html (read 2026-10-07)
    aws.call("logs", "put_retention_policy", logGroupName=name, retentionInDays=7)


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    app_logs = parser.add_mutually_exclusive_group()
    app_logs.add_argument("--include-app-logs", action="store_true",
                          help="opt in to APPLICATION_LOGS, which contain prompts and answers")
    app_logs.add_argument("--no-app-logs", action="store_true",
                          help="legacy option; application logs are skipped by default")
    parser.add_argument("--no-traces", action="store_true", help="skip the TRACES delivery")
    args = parser.parse_args(argv)
    out = kitlib.redacting(out)  # review round 5, F13: no line carries a full account id
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)

    if not kitlib.confirm_billing(args, kitlib.PRICE_LINES_LOGS + [
        "Expect a few kilobytes of usage records per session and one application record per call.",
    ], out):
        return 2

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    if not kitlib.check_place(state, cfg, account, out, "40_enable_observability.py",
                              dry_run=args.dry_run):
        return kitlib.EXIT_STATE_MISMATCH

    runtime_arn = state.get("runtime_arn")
    if not runtime_arn:
        if not args.dry_run:
            out("No runtime in .state.json. Run 30_deploy.py first.")
            return 1
        runtime_arn = (f"arn:aws:bedrock-agentcore:{cfg.region}:{kitlib.DRY_ACCOUNT}:"
                       f"runtime/{cfg.runtime_name}-dryrun0000")

    deliveries: list[dict] = [] if args.dry_run else list(state.get("deliveries", []) or [])
    have = {d.get("kind") for d in deliveries}
    created = 0

    def record(entry: dict) -> None:
        nonlocal created
        deliveries.append(entry)
        created += 1
        state.set(deliveries=deliveries)
        state.remove("delivery_in_progress")

    def about_to_create(kind: str, log_group: str | None = None) -> None:
        """Write the names down BEFORE the calls that create them (review round 4: a process
        that died right after a call left nothing on record). The delivery's own id comes back
        in the answer, so until then it is on record by its source and destination names."""
        nonlocal acted
        acted = True
        source, destination = cfg.delivery_names(kind)
        if log_group:
            state.set(log_groups=sorted(set(state.get("log_groups", []) + [log_group])))
        state.set(delivery_in_progress={"kind": kind, "source": source, "destination": destination})

    acted = False
    try:
        if "usage" in have:
            out("[logs] USAGE_LOGS delivery is already recorded, skipping")
        else:
            about_to_create("usage", cfg.usage_log_group)
            _ensure_log_group(aws, cfg.usage_log_group, out)
            usage_arn = f"arn:aws:logs:{cfg.region}:{account}:log-group:{cfg.usage_log_group}"
            record(_delivery(aws, cfg, "usage", "USAGE_LOGS", runtime_arn, "CWL", usage_arn, out))

        if args.include_app_logs:
            if "app" in have:
                out("[logs] APPLICATION_LOGS delivery is already recorded, skipping")
            else:
                about_to_create("app", cfg.app_log_group)
                _ensure_log_group(aws, cfg.app_log_group, out)
                app_arn = f"arn:aws:logs:{cfg.region}:{account}:log-group:{cfg.app_log_group}"
                record(_delivery(aws, cfg, "app", "APPLICATION_LOGS", runtime_arn, "CWL", app_arn, out))
        elif "app" in have:
            out("[logs] APPLICATION_LOGS are already enabled by a recorded delivery; "
                "they contain prompts and answers. Run 90_teardown.py to remove the delivery.")
        else:
            out("[logs] APPLICATION_LOGS skipped by default because they contain prompts and answers; "
                "pass --include-app-logs to opt in")

        if args.no_traces:
            pass
        elif "traces" in have:
            out("[logs] TRACES delivery is already recorded, skipping")
        else:
            # doc: https://docs.aws.amazon.com/xray/latest/api/API_GetTraceSegmentDestination.html (read 2026-10-07)
            dest = aws.call("xray", "get_trace_segment_destination",
                            dry_result={"Destination": "CloudWatchLogs", "Status": "ACTIVE"})
            if dest.get("Destination") == "CloudWatchLogs":
                # AWS's example sends TRACES to a destination of type XRAY with no log group.
                about_to_create("traces")
                record(_delivery(aws, cfg, "traces", "TRACES", runtime_arn, "XRAY", None, out))
            else:
                out("[traces] Transaction Search is OFF in this account, so the TRACES delivery was "
                    "skipped. Usage and application logs do not need it.")
    except Exception as exc:
        code = kitlib.explain_aws_error(exc, out)
        if acted and code == 2:
            code = 1  # 2 means "refused, nothing was done"; a create call had been sent
        out(f"Not finished: {len(deliveries)} delivery(ies) exist and are recorded in .state.json. "
            "Fix the cause and run this script again; it creates only what is missing. "
            "90_teardown.py removes all of it.")
        return code

    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made.")
        return 0
    out(f"Done: {created} delivery(ies) created now, {len(deliveries)} recorded in all. "
        "Next: python 50_invoke_hosted.py --dry-run")
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
