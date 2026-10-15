#!/usr/bin/env python3
"""60_read_usage.py: read back what the sessions used, and work out what they cost.

Makes no change in AWS. Three sources, all documented on
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html  (read 2026-10-07)

  A. USAGE_LOGS records in the log group that 40_enable_observability.py set up.
     Fields: session.id, elapsed_time_seconds, agent.runtime.vcpu.hours.used,
     agent.runtime.memory.gb_hours.used. This gives figures per session.
  B. CloudWatch metrics CPUUsed-vCPUHours and MemoryUsed-GBHours, namespace
     AWS/Bedrock-AgentCore, dimensions Service=AgentCore.Runtime and
     Resource=<runtime ARN>. This gives the total for the runtime over the
     same window and is the cross-check for A.
  C. Optional: the runtime's own log group, and span counts per session.

Read this before you trust a figure.

  The data is late. AWS: "Resource usage data may be delayed by up to 60 minutes
  and precision might differ across metrics." A read taken a few minutes after
  the sessions can hold half the records and still look like a result.

  AWS does not say whether a usage record is an increment (add them up) or a
  running total (take the largest). The page gives the field names and
  "1-second granularity", nothing more. So this script prints BOTH readings for
  every session: the sum of its records and the largest single record. It looks
  at elapsed_time_seconds to guess which reading is right, and then checks the
  guess against source B.

  A session cost is labelled CROSS-CHECKED only when all of this holds:
    - the read is taken at least 60 minutes after the last session ended, which
      is the longest delay AWS states. Before that the two sources can both be
      equally incomplete and agree with each other, so an early read is a
      reason for NOT CROSS-CHECKED, not a footnote (review round 2, B1);
    - there are usage records for every session, they say how much time they
      cover (elapsed_time_seconds), and that is at least 90% of each session's
      wall-clock time. Records with no elapsed time count as partial;
    - the CloudWatch metrics have data;
    - one reading of the logs agrees with the metric total within 10%
      (vCPU-hours and GB-hours each), and the record layout does not point to
      the other reading.
  In every other case the last line says NOT CROSS-CHECKED and the exit code is
  1. Do not quote a session cost from such a run, and do not tear down yet:
  90_teardown.py deletes the log group that holds the records. The exception:
  when no USAGE_LOGS delivery is recorded, or a session has no end time, no later
  read can be cross-checked, and the script says so and that teardown can go ahead.
  The 90% and the 10% are this kit's choices, not AWS's. --tolerance-percent
  changes the second and is echoed in the RESULT line.

  --accept-early-read lets a read taken before the 60 minutes are up end
  CROSS-CHECKED when everything else holds. The RESULT line then says
  "read early at the owner's request, NOT final", and 90_teardown.py still warns.

Cost = vCPU-hours x the vCPU rate + GB-hours x the GB rate, at the rate for the
platform version the service reported at deploy time. If it reported none, the
version is ASSUMED (what the deploy asked for, else V1) and every rates line
says so: the cross-check compares hours, not dollars, so it cannot catch a
wrong version.

Model tokens are a separate charge. Token counts come from what the agent
returned in 50_invoke_hosted.py. Prices are PER 1,000,000 TOKENS, the unit the
Bedrock pricing page uses. For the two models this kit names the price read on
2026-10-07 is built in (a global. inference profile has its own, lower price);
for any other model pass
    --input-usd-per-1m <price>  --output-usd-per-1m <price>

Exit codes: 0 CROSS-CHECKED; 1 NOT CROSS-CHECKED or a failed call; 4 the state
file records another Region, prefix or account, or cannot be used.

Usage:
    python 60_read_usage.py
    python 60_read_usage.py --show-logs
    python 60_read_usage.py --accept-early-read
    python 60_read_usage.py --dry-run
"""
from __future__ import annotations

import datetime as dt
import json

import kitlib

VCPU_KEY = "agent.runtime.vcpu.hours.used"
MEM_KEY = "agent.runtime.memory.gb_hours.used"
ELAPSED_KEY = "elapsed_time_seconds"
SESSION_KEY = "session.id"
METRIC_NAMESPACE = "AWS/Bedrock-AgentCore"

TOLERANCE = 0.10        # logs and metrics "agree" when each total is within 10% of the other
MIN_COVERAGE = 0.90     # usage records must cover this share of a session's wall-clock time
DELAY_MINUTES = kitlib.USAGE_DELAY_MINUTES  # AWS: usage data "may be delayed by up to 60 minutes"
DELAY_QUOTE = kitlib.USAGE_DELAY_QUOTE
EARLY_WORDS = "read early at the owner's request, NOT final"


def flatten(value, prefix: str = "") -> dict:
    """{'a': {'b': 1}} -> {'a.b': 1}. Usage records may nest their fields."""
    flat: dict = {}
    if isinstance(value, dict):
        for key, inner in value.items():
            flat.update(flatten(inner, f"{prefix}.{key}" if prefix else str(key)))
    else:
        flat[prefix] = value
    return flat


def find_field(flat: dict, name: str):
    """Value of the field called `name`, wherever it sits in the record."""
    if name in flat:
        return flat[name]
    for key, value in flat.items():
        if key.endswith("." + name):
            return value
    return None


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_usage_events(events: list[dict]) -> dict:
    """Group the usage fields of the given log events by session id.

    For each session: how many records, the SUM and the MAX of each usage field, and what
    elapsed_time_seconds looked like (how many records carry it, sum, min, max, smallest
    step between two values) and whether the usage values only ever went up.

    An event that CloudWatch returns twice (the same eventId) is counted once. Records are
    read in the order of their elapsed_time_seconds when they all carry it, else in the
    order of their timestamps, so records that arrive out of order are not misread.
    """
    sessions: dict[str, dict] = {}
    unparsed = 0
    seen_ids: set = set()
    rows: dict[str, list] = {}
    for position, event in enumerate(sorted(events, key=lambda e: e.get("timestamp") or 0)):
        event_id = event.get("eventId")
        if event_id is not None:
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)
        try:
            record = json.loads(event.get("message", ""))
        except (TypeError, ValueError):
            unparsed += 1
            continue
        flat = flatten(record)
        session_id = find_field(flat, SESSION_KEY)
        vcpu, mem = find_field(flat, VCPU_KEY), find_field(flat, MEM_KEY)
        if session_id is None or (vcpu is None and mem is None):
            unparsed += 1
            continue
        rows.setdefault(str(session_id), []).append(
            (_number(find_field(flat, ELAPSED_KEY)), position, _number(vcpu) or 0.0, _number(mem) or 0.0))
    for session_id, records in rows.items():
        with_elapsed = [r for r in records if r[0] is not None]
        if len(with_elapsed) == len(records):
            records = sorted(records, key=lambda r: (r[0], r[1]))
        entry = {
            "records": len(records),
            "vcpu_hours_sum": sum(r[2] for r in records), "gb_hours_sum": sum(r[3] for r in records),
            "vcpu_hours_max": max(r[2] for r in records), "gb_hours_max": max(r[3] for r in records),
            "elapsed_records": len(with_elapsed),
            "elapsed_sum": sum(r[0] for r in with_elapsed),
            "elapsed_min": min((r[0] for r in with_elapsed), default=None),
            "elapsed_max": max((r[0] for r in with_elapsed), default=0.0),
            "elapsed_step": None, "usage_rising": True,
        }
        steps = sorted({r[0] for r in with_elapsed})
        if len(steps) > 1:
            entry["elapsed_step"] = min(b - a for a, b in zip(steps, steps[1:]))
        last = None
        for elapsed, _, v, m in records:
            if last is not None and (elapsed, v, m) != last:  # an exact repeat says nothing
                if v < last[1] or m <= last[2]:
                    entry["usage_rising"] = False
            last = (elapsed, v, m)
        sessions[session_id] = entry
    return {"sessions": sessions, "unparsed": unparsed}


def record_shape(entry: dict) -> str:
    """Guess what one usage record is, from elapsed_time_seconds and the usage values.

    "increment"      every record covers one interval. Either elapsed_time_seconds is the
                     same in all of them (the length of the interval), or it counts up from
                     the session start while the usage values go up and down. Add them up.
    "running_total"  every record is the total so far: elapsed_time_seconds differs between
                     records and memory GB-hours rises with it. Take the largest.
    "single"         one record: both readings are the same number.
    "unknown"        some record has no elapsed_time_seconds, so nothing can be told.
    UNVERIFIED: which of these AgentCore writes. This is a guess that the metric total
    must confirm before any figure is called cross-checked.
    """
    if not entry or not entry.get("records"):
        return "none"
    if entry["records"] == 1:
        return "single"
    if entry["elapsed_records"] < entry["records"]:
        return "unknown"
    if entry["elapsed_min"] == entry["elapsed_max"]:
        return "increment"
    return "running_total" if entry["usage_rising"] else "increment"


# How the mixed-layouts reason names each layout it saw (review round 5, F11).
LAYOUT_WORDS = {
    "increment": "the records of some sessions look like increments",
    "running_total": "those of some look like running totals",
    "unknown": "those of some do not say how much time they cover, so their layout cannot be told",
}


def covered_seconds(entry: dict, shape: str) -> float | None:
    """Seconds of the session the records account for, or None when that cannot be told.
    None is never read as "complete": the caller treats it as partial (review round 2, B1).

    running_total, single   the largest elapsed_time_seconds seen
    increment, every record with the same elapsed_time_seconds (the interval length)
                            the sum of them
    increment, elapsed_time_seconds counting up from the session start
                            records x the smallest step between two values. Not the sum:
                            for a 60-second session that would be 1 + 2 + ... + 60 = 1830.
    """
    if not entry or not entry.get("records") or entry.get("elapsed_records", 0) < entry["records"]:
        return None
    if shape in {"running_total", "single"}:
        return entry["elapsed_max"]
    if shape == "increment":
        if entry["elapsed_min"] == entry["elapsed_max"]:
            return entry["elapsed_sum"]
        if entry.get("elapsed_step"):
            return min(entry["records"] * entry["elapsed_step"], entry["elapsed_max"])
    return None


def cost(vcpu_hours: float, gb_hours: float, cpu_rate: float, mem_rate: float) -> float:
    return vcpu_hours * cpu_rate + gb_hours * mem_rate


def within_tolerance(a: float, b: float, tolerance: float = TOLERANCE) -> bool:
    """True when a and b are both positive and each is within `tolerance` of the other."""
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) <= tolerance * max(a, b)


def token_cost(tokens_in: int, tokens_out: int, usd_per_1m_in: float, usd_per_1m_out: float) -> float:
    """Prices are per 1,000,000 tokens, as on https://aws.amazon.com/bedrock/pricing/ ."""
    return tokens_in / 1_000_000 * usd_per_1m_in + tokens_out / 1_000_000 * usd_per_1m_out


def _filter_events(aws: kitlib.Aws, log_group: str, start_ms: int, end_ms: int,
                   pattern: str | None, max_events: int = 20000,
                   stream_prefix: str | None = None) -> list[dict]:
    events: list[dict] = []
    token = None
    while True:
        params = {"logGroupName": log_group, "startTime": start_ms, "endTime": end_ms}
        if stream_prefix:
            params["logStreamNamePrefix"] = stream_prefix
        if pattern:
            params["filterPattern"] = pattern
        if token:
            params["nextToken"] = token
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_FilterLogEvents.html (read 2026-10-07)
        page = aws.call("logs", "filter_log_events", dry_result={"events": []}, **params)
        events += page.get("events", [])
        token = page.get("nextToken")
        if not token or len(events) >= max_events:
            return events


def _metric_sum(aws: kitlib.Aws, name: str, runtime_arn: str, start: dt.datetime,
                end: dt.datetime) -> tuple[float, int]:
    """(sum, number of datapoints). Zero datapoints means "no data yet", not "zero use"."""
    # doc: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html (read 2026-10-07)
    # Namespace, metric names and dimensions: observability-runtime-metrics.html (read 2026-10-07)
    data = aws.call(
        "cloudwatch", "get_metric_statistics",
        Namespace=METRIC_NAMESPACE, MetricName=name,
        Dimensions=[{"Name": "Service", "Value": "AgentCore.Runtime"},
                    {"Name": "Resource", "Value": runtime_arn}],
        StartTime=start, EndTime=end, Period=300, Statistics=["Sum"],
        dry_result={"Datapoints": []},
    )
    points = data.get("Datapoints", [])
    return sum(point.get("Sum", 0.0) for point in points), len(points)


def _count_spans(aws: kitlib.Aws, group: str, start_ms: int, end_ms: int, session_id: str,
                 stream_prefix: str | None) -> int | None:
    """Events that carry the session id, or None when the log group does not exist."""
    try:
        return len(_filter_events(aws, group, start_ms, end_ms, f'"{session_id}"',
                                  max_events=2000, stream_prefix=stream_prefix))
    except Exception as exc:
        if kitlib.is_not_found(exc):
            return None
        raise


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=False)
    parser.allow_abbrev = False
    parser.add_argument("--show-logs", action="store_true",
                        help="also print the last lines of the runtime's own log group")
    parser.add_argument("--input-usd-per-1m", type=float, default=None,
                        help="your model's price per 1,000,000 (1M) input tokens, as the Bedrock "
                             "pricing page shows it")
    parser.add_argument("--output-usd-per-1m", type=float, default=None,
                        help="your model's price per 1,000,000 (1M) output tokens")
    parser.add_argument("--accept-early-read", action="store_true",
                        help=f"allow a CROSS-CHECKED result before {DELAY_MINUTES} minutes have passed "
                             "since the last session ended. The RESULT line then says it was read "
                             "early at the owner's request and is NOT final")
    parser.add_argument("--tolerance-percent", type=float, default=TOLERANCE * 100,
                        help="how far apart the usage logs and the CloudWatch metrics may be and "
                             f"still agree (default {TOLERANCE * 100:.0f}; 1 to 50). Echoed in the RESULT line")
    args = parser.parse_args(argv)
    out = kitlib.redacting(out)  # review round 5, F13: no line carries a full account id
    if not 1 <= args.tolerance_percent <= 50:
        out("--tolerance-percent must be between 1 and 50")
        return 2
    tolerance = args.tolerance_percent / 100
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    if not kitlib.check_place(state, cfg, account, out, "60_read_usage.py", dry_run=args.dry_run):
        return kitlib.EXIT_STATE_MISMATCH

    runtime_arn = state.get("runtime_arn")
    runtime_id = state.get("runtime_id")
    sessions = state.get("sessions", [])
    if args.dry_run and not (runtime_arn and sessions):
        runtime_id = f"{cfg.runtime_name}-dryrun0000"
        runtime_arn = f"arn:aws:bedrock-agentcore:{cfg.region}:{kitlib.DRY_ACCOUNT}:runtime/{runtime_id}"
        now = kitlib.utc_now_iso()
        sessions = [{"session_id": f"{cfg.prefix}-kitc-{'0' * 32}", "started_at": now,
                     "ended_at": now, "calls": []}]
    if not runtime_arn or not sessions:
        out("Nothing to read: .state.json has no runtime or no sessions. "
            "Run 30_deploy.py and 50_invoke_hosted.py first.")
        return 1

    reported_version = state.get("reported_platform_version")
    requested_version = state.get("requested_platform_version")
    version, cpu_rate, mem_rate = cfg.rates(reported_version, requested_version)
    basis = cfg.rates_basis(reported_version, requested_version)
    version_assumed = str(reported_version or "").upper() not in kitlib.RUNTIME_RATES
    now = kitlib.utc_now()
    last_end = max(kitlib.parse_iso(s.get("ended_at") or s["started_at"]) for s in sessions)
    start = min(kitlib.parse_iso(s["started_at"]) for s in sessions) - dt.timedelta(minutes=5)
    end = min(last_end + dt.timedelta(minutes=DELAY_MINUTES + 30), now + dt.timedelta(minutes=1))
    if end <= start:
        end = start + dt.timedelta(minutes=10)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    minutes_since = max((now - last_end).total_seconds() / 60, 0.0)
    final_from = last_end + dt.timedelta(minutes=DELAY_MINUTES)
    early = minutes_since < DELAY_MINUTES
    out(f"Runtime {runtime_id}, {len(sessions)} session(s), window {start:%Y-%m-%d %H:%M}Z to "
        f"{end:%H:%M}Z")
    out(f"Rates ({version}, {basis}): ${cpu_rate} per vCPU-hour, ${mem_rate} per GB-hour. "
        f"Source: {kitlib.PRICING_URL} read {kitlib.READ_DATE}.")
    out(f"This read: {now:%Y-%m-%dT%H:%M:%SZ} (UTC), {minutes_since:.0f} minute(s) after the last "
        f"session ended ({last_end:%Y-%m-%dT%H:%M:%SZ}). AWS: {DELAY_QUOTE}")
    if early:
        out(f"That is EARLY: a read can be final only from {final_from:%Y-%m-%dT%H:%M:%SZ} (UTC) on, "
            f"{DELAY_MINUTES - minutes_since:.0f} minute(s) from now."
            + (" --accept-early-read was given." if args.accept_early_read else ""))

    try:
        # ---- A. usage logs, per session ----
        usage_by_session: dict[str, dict] = {}
        unparsed = 0
        have_usage_logs = any(d.get("log_type") == "USAGE_LOGS" for d in state.get("deliveries", [])) \
            or args.dry_run
        if have_usage_logs:
            for s in sessions:
                # UNVERIFIED: the exact JSON layout of a USAGE_LOGS record. The field names are
                # documented; whether they sit at the top level or nested is not shown. The
                # parser looks for them at any depth, and the filter is the quoted session id.
                events = _filter_events(aws, cfg.usage_log_group, start_ms, end_ms,
                                        f'"{s["session_id"]}"')
                parsed = parse_usage_events(events)
                unparsed += parsed["unparsed"]
                usage_by_session.update(parsed["sessions"])
        else:
            out("No USAGE_LOGS delivery is recorded (40_enable_observability.py was not run), "
                "so there is no per-session figure and nothing can be cross-checked.")

        # ---- B. metrics, total for the runtime ----
        metric_vcpu, vcpu_points = _metric_sum(aws, "CPUUsed-vCPUHours", runtime_arn, start, end)
        metric_gb, gb_points = _metric_sum(aws, "MemoryUsed-GBHours", runtime_arn, start, end)

        # ---- C. optional extras ----
        log_tail: list[dict] = []
        runtime_group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
        if args.show_logs:
            try:
                log_tail = _filter_events(aws, runtime_group, start_ms, end_ms, None, max_events=200)[-20:]
            except Exception as exc:
                if not kitlib.is_not_found(exc):
                    raise
                out(f"The runtime log group {runtime_group} does not exist yet.")
        span_counts: dict[str, str] = {}
        if any(d.get("log_type") == "TRACES" for d in state.get("deliveries", [])):
            for s in sessions:
                # AWS: "newly created agents use the agent's log group as the default span
                # destination", in the log stream "spans" of
                # /aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>; older agents use
                # the shared aws/spans log group. Both are counted.
                # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html (read 2026-10-07)
                # UNVERIFIED: that a span record carries the runtime session id as plain text.
                # If both counts are zero, look in the CloudWatch console under GenAI
                # Observability, Bedrock AgentCore, Sessions.
                own = _count_spans(aws, runtime_group, start_ms, end_ms, s["session_id"], "spans")
                shared = _count_spans(aws, "aws/spans", start_ms, end_ms, s["session_id"], None)
                span_counts[s["session_id"]] = (f"{'-' if own is None else own}/"
                                                f"{'-' if shared is None else shared}")
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)

    # ---- per session ----
    out("")
    out('Per session, from USAGE_LOGS. Both readings are shown: "sum" is right if each record is')
    out('an increment, "max" is right if each record is a running total.')
    out(f"{'session':<12}{'calls':>6}{'wall s':>8}{'records':>9}{'covered s':>11}"
        f"{'vCPU-h sum':>14}{'vCPU-h max':>14}{'GB-h sum':>13}{'GB-h max':>13}"
        f"{'USD sum':>11}{'USD max':>11}  {'records look like':<18}{'spans own/shared':>17}  note")
    totals = {"sum": [0.0, 0.0], "max": [0.0, 0.0]}
    shapes: set[str] = set()
    tokens_in = tokens_out = 0
    calls_total = calls_without_tokens = 0
    missing: list[str] = []
    partial: list[str] = []
    uncovered: list[str] = []
    no_end: list[str] = []
    for s in sessions:
        sid = s["session_id"]
        u = usage_by_session.get(sid, {})
        shape = record_shape(u)
        if shape not in {"none", "single"}:
            shapes.add(shape)
        wall = max((kitlib.parse_iso(s.get("ended_at") or s["started_at"])
                    - kitlib.parse_iso(s["started_at"])).total_seconds(), 0.0)
        covered = covered_seconds(u, shape)
        v_sum, g_sum = u.get("vcpu_hours_sum", 0.0), u.get("gb_hours_sum", 0.0)
        v_max, g_max = u.get("vcpu_hours_max", 0.0), u.get("gb_hours_max", 0.0)
        totals["sum"][0] += v_sum
        totals["sum"][1] += g_sum
        totals["max"][0] += v_max
        totals["max"][1] += g_max
        for call in s.get("calls", []):
            calls_total += 1
            if call.get("input_tokens") is None and call.get("output_tokens") is None:
                calls_without_tokens += 1  # a call that failed reports none
            tokens_in += int(call.get("input_tokens") or 0)
            tokens_out += int(call.get("output_tokens") or 0)
        note = ""
        if have_usage_logs and not u.get("records"):
            note = "NO RECORDS YET"
            missing.append(sid)
        elif have_usage_logs and not s.get("ended_at"):
            # Review round 4, m9: with no end time the wall-clock time is unknown (it was shown
            # as 0), so the coverage of the records could not be checked, and it was not said.
            note = "NO END TIME ON RECORD: how much of this session the records cover is not known"
            no_end.append(sid)
        elif have_usage_logs and covered is None:
            note = "PARTIAL: the records do not say how much time they cover"
            uncovered.append(sid)
        elif covered is not None and wall > 0 and covered < MIN_COVERAGE * wall:
            note = f"PARTIAL: records cover {covered:.0f} of {wall:.0f} s"
            partial.append(sid)
        out(f"{'...' + sid[-8:]:<12}{len(s.get('calls', [])):>6}{wall:>8.0f}{u.get('records', 0):>9}"
            f"{('-' if covered is None else f'{covered:.0f}'):>11}"
            f"{v_sum:>14.8f}{v_max:>14.8f}{g_sum:>13.8f}{g_max:>13.8f}"
            f"{cost(v_sum, g_sum, cpu_rate, mem_rate):>11.6f}{cost(v_max, g_max, cpu_rate, mem_rate):>11.6f}"
            f"  {shape:<18}{span_counts.get(sid, '-'):>17}  {note}")

    sum_cost = cost(*totals["sum"], cpu_rate, mem_rate)
    max_cost = cost(*totals["max"], cpu_rate, mem_rate)
    metric_cost = cost(metric_vcpu, metric_gb, cpu_rate, mem_rate)
    have_metrics = vcpu_points > 0 and gb_points > 0
    out("")
    out(f"Sum of per-session sums   (if records are increments):     {totals['sum'][0]:.8f} vCPU-hours, "
        f"{totals['sum'][1]:.8f} GB-hours = ${sum_cost:.6f}")
    out(f"Sum of per-session maxima (if records are running totals): {totals['max'][0]:.8f} vCPU-hours, "
        f"{totals['max'][1]:.8f} GB-hours = ${max_cost:.6f}")
    if have_metrics:
        out(f"Runtime total (CloudWatch metrics):                        {metric_vcpu:.8f} vCPU-hours, "
            f"{metric_gb:.8f} GB-hours = ${metric_cost:.6f}")
    else:
        out("Runtime total (CloudWatch metrics):                        no datapoints yet "
            f"({vcpu_points} for vCPU-hours, {gb_points} for GB-hours)")
    if unparsed:
        out(f"{unparsed} usage record(s) could not be read with the documented field names.")

    # ---- the verdict ----
    agrees = {name: have_metrics and within_tolerance(totals[name][0], metric_vcpu, tolerance)
              and within_tolerance(totals[name][1], metric_gb, tolerance) for name in ("sum", "max")}
    layout = None
    if shapes == {"increment"}:
        layout = "sum"
    elif shapes == {"running_total"}:
        layout = "max"
    reasons: list[str] = []
    if len(shapes) > 1:
        # Review round 4, m9: one session's records looked like increments and another's like
        # running totals, the sum happened to be near the metrics, and the run ended CROSS-CHECKED.
        if shapes == {"increment", "running_total"}:
            reasons.append("the usage records of some sessions look like increments and those of others "
                           "like running totals, so neither way of adding them up can be relied on")
        else:
            # Review round 5, F11: with "unknown" among them this said "running totals" when no
            # session's records looked like that. Only the layouts that were seen are named.
            seen = "; ".join(LAYOUT_WORDS[shape] for shape in ("increment", "running_total", "unknown")
                             if shape in shapes)
            reasons.append(f"the usage records of the sessions do not all have one layout ({seen}), so "
                           "neither way of adding them up can be relied on")
    if no_end:
        reasons.append(f"{len(no_end)} session(s) have no end time in .state.json (the script that ran "
                       "them was stopped before it could write one), so how much of them the usage "
                       "records cover cannot be checked")
    if early and not args.accept_early_read:
        reasons.append(
            f"this was read {minutes_since:.0f} minute(s) after the last session ended, and AWS says "
            f"usage data may be delayed by up to {DELAY_MINUTES} minutes, so both sources may still "
            f"be incomplete; read again at or after {final_from:%Y-%m-%dT%H:%M:%SZ} (UTC)")
    if not have_usage_logs:
        reasons.append("there are no usage logs to compare with the metrics")
    if missing:
        reasons.append(f"{len(missing)} of {len(sessions)} session(s) have no usage records yet")
    if partial:
        reasons.append(f"{len(partial)} session(s) have usage records for less than "
                       f"{MIN_COVERAGE:.0%} of their wall-clock time")
    if uncovered:
        reasons.append(f"{len(uncovered)} session(s) have usage records that do not say how much "
                       "time they cover (no usable elapsed_time_seconds), so they cannot be told "
                       "from partial data")
    if not have_metrics:
        reasons.append("the CloudWatch metrics have no datapoints for this runtime yet, so there "
                       "is nothing to check the logs against")
    chosen = None
    if have_metrics and have_usage_logs and not missing:
        candidates = [name for name in ("sum", "max") if agrees[name]]
        if not candidates:
            reasons.append(
                "neither reading of the logs is within "
                f"{tolerance:.0%} of the metric total (sums ${sum_cost:.6f}, maxima ${max_cost:.6f}, "
                f"metrics ${metric_cost:.6f})")
        elif layout and layout not in candidates:
            reasons.append(
                f"the record layout points to the per-session {layout} but only the other reading "
                "agrees with the metric total")
        else:
            chosen = layout if layout in candidates else candidates[0]

    out("")
    tolerance_words = (f"tolerance {tolerance:.0%}" if tolerance == TOLERANCE
                       else f"tolerance {tolerance:.0%}, set with --tolerance-percent")
    rates_words = f"Rates: {version}, {basis}."
    if chosen and not reasons:
        figure = sum_cost if chosen == "sum" else max_cost
        usage_pair = totals[chosen]
        kind = "increments (added up)" if chosen == "sum" else "running totals (largest taken)"
        low, high = sorted((figure, metric_cost))
        apart = (high - low) / high if high else 0.0
        head = "RESULT: CROSS-CHECKED"
        if early:
            head += f", {EARLY_WORDS} ({minutes_since:.0f} of {DELAY_MINUTES} minutes had passed)"
        verdict = (f"{head}: runtime cost of these {len(sessions)} session(s) ${figure:.6f} from the "
                   f"usage logs, read as {kind}, against ${metric_cost:.6f} from the CloudWatch "
                   f"metrics. The two are {apart:.1%} apart ({tolerance_words}).")
        if apart > 0.02:
            verdict += f" Quote the range ${low:.6f} to ${high:.6f}, not the lower figure alone."
        verdict += f" {rates_words}"
        if version_assumed:
            other = "V2" if version == "V1" else "V1"
            other_cost = cost(*usage_pair, *kitlib.RUNTIME_RATES[other])
            verdict += f" At {other} rates the same usage would be ${other_cost:.6f}."
        verdict += (f" Read at {now:%Y-%m-%dT%H:%M:%SZ} (UTC), {minutes_since:.0f} minute(s) after "
                    "the last session ended.")
        if not args.dry_run:
            state.set(usage_cross_checked_at=kitlib.utc_now_iso(), usage_reading=chosen,
                      usage_runtime_usd=round(figure, 8), usage_metric_usd=round(metric_cost, 8),
                      usage_read_early=bool(early), usage_minutes_after_last_session=round(minutes_since, 1))
        code = 0
    else:
        headline = {"sum": sum_cost, "max": max_cost}.get(layout or "")
        verdict = ("RESULT: NOT CROSS-CHECKED, do not quote a session cost from this run: "
                   + "; ".join(reasons or ["the two sources could not be compared"]) + ".")
        if headline is not None:
            verdict += (f" Unchecked figure, for orientation only: ${headline:.6f} "
                        f"(the records look like {'increments' if layout == 'sum' else 'running totals'}).")
        # Review round 5, F3: two reasons do not go away however long one waits: no USAGE_LOGS
        # delivery is recorded (step 40 was skipped; whether a delivery set up later would bring
        # back the records of sessions that ran before it is not known, and this kit does not
        # count on it), and a session with no end time (nothing writes one later). Then the
        # result cannot become CROSS-CHECKED by waiting, and telling the owner to wait for it
        # would keep a deploy up for nothing.
        permanent = []
        if not have_usage_logs:
            permanent.append("no USAGE_LOGS delivery is recorded for these sessions")
        if no_end:
            permanent.append(f"{len(no_end)} session(s) have no end time on record")
        if permanent:
            verdict += (f" This cannot change however long you wait ({'; '.join(permanent)}): there is no "
                        "cross-checked session cost for these sessions, and teardown can go ahead.")
        verdict += (f" {rates_words} Read at {now:%Y-%m-%dT%H:%M:%SZ} (UTC), {minutes_since:.0f} "
                    "minute(s) after the last session ended.")
        if permanent:
            out(f"This read can never end CROSS-CHECKED, however long you wait: {'; '.join(permanent)}. "
                "Write down the figures above, as unchecked figures, then go on to 90_teardown.py when "
                "you are ready: waiting gains nothing.")
        else:
            out(f"Usage data can be up to {DELAY_MINUTES} minutes late. Run this script again at or after "
                f"{final_from:%Y-%m-%dT%H:%M:%SZ} (UTC). Do not run 90_teardown.py until it prints "
                "RESULT: CROSS-CHECKED: teardown deletes the log group that holds these records.")
        if not args.dry_run and state.get("usage_cross_checked_at"):
            # An earlier run ended CROSS-CHECKED. This one did not, so that stamp no longer
            # stands: without it 90_teardown.py warns again before it deletes the records.
            state.remove("usage_cross_checked_at", "usage_reading", "usage_runtime_usd",
                         "usage_metric_usd", "usage_read_early", "usage_minutes_after_last_session")
        code = 1

    # ---- tokens ----
    out(f"Model tokens reported by the agent: {tokens_in} in, {tokens_out} out.")
    token_caveat = ""
    if calls_without_tokens:
        token_caveat = (f" LOWER BOUND: {calls_without_tokens} of {calls_total} call(s) reported no token "
                        "count (a call that failed reports none), and their tokens are not in this figure.")
    elif calls_total and not tokens_in and not tokens_out:
        token_caveat = (" NOT A MEASURED COST: no call reported any tokens (the model or the runtime "
                        "reported none), so this says nothing about what the tokens cost.")
    price_in, price_out, price_source = args.input_usd_per_1m, args.output_usd_per_1m, "the prices you gave"
    if (price_in is None) != (price_out is None):
        out("Token cost: not computed. Give both --input-usd-per-1m and --output-usd-per-1m, or neither."
            + token_caveat)
    else:
        if price_in is None:
            model = state.get("model_id") or cfg.model_id
            known = kitlib.model_token_price(model, cfg.region)
            if known:
                price_in, price_out, which = known
                price_source = (f"the kit's table for {model} in {cfg.region}, {which}, read "
                                f"{kitlib.READ_DATE}; check {kitlib.BEDROCK_PRICING_URL}")
        if price_in is None:
            # Review round 5, F12: the caveat on the token count was printed only beside a cost.
            out("Token cost: not computed. This kit holds no price for this model id and Region. Pass "
                "--input-usd-per-1m and --output-usd-per-1m with the prices PER 1M TOKENS from "
                f"{kitlib.BEDROCK_PRICING_URL} .{token_caveat}")
        else:
            out(f"Token cost: {tokens_in} / 1,000,000 x ${price_in} + {tokens_out} / 1,000,000 x "
                f"${price_out} = ${token_cost(tokens_in, tokens_out, price_in, price_out):.6f}  "
                f"(prices per 1M tokens: {price_source}){token_caveat}")
    if log_tail:
        out("")
        out("Last lines of the runtime log group:")
        for event in log_tail:
            out("  " + str(event.get("message", "")).rstrip()[:300])
    out("")
    out("Write these numbers into RESULTS_TEMPLATE.md. The invoice is the final word: check "
        "Billing and Cost Management a day later.")
    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made, the figures above are zeros.")
        return 0
    out(verdict)
    return code


if __name__ == "__main__":
    kitlib.script_main(main)
