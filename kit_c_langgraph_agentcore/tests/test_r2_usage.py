"""Second independent review, 2026-10-07 (round 2), the numbers: BLOCKER B1 and the minors on
60_read_usage.py, 50_invoke_hosted.py and the prices. Every test here failed on the code as
it was reviewed, except the ones marked "unchanged", which pin what must stay true.

B1  60_read_usage.py printed CROSS-CHECKED and exited 0 on partial data, because two
    sources that share one delay agree with each other, and the coverage test was skipped
    when elapsed_time_seconds was absent or counted up from the session start. It then
    wrote usage_cross_checked_at, which silenced the teardown warning.

The "true" session used throughout is the reviewer's: 60 seconds alive, 6 seconds of one
vCPU, 0.5 GB for the whole time. Two such sessions cost $0.000456 at V1 rates.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import ACCOUNT, RUNTIME_ARN, RUNTIME_ID, FakeClientError, load_script, make_fake_aws

S1, S2 = "kitdemo-kitc-" + "a" * 32, "kitdemo-kitc-" + "b" * 32
V = 6 / 3600
G = 0.5 * 60 / 3600
TRUE_COST = 2 * (V * 0.0895 + G * 0.00945)
T0 = 1791367200000


def inc(sid, n=60, elapsed=lambda i: 1):
    """n one-second increment records. elapsed(i) is the record's elapsed_time_seconds, or None."""
    out = []
    for i in range(n):
        record = {"session.id": sid, "agent.runtime.vcpu.hours.used": (1 / 3600 if i < 6 else 0),
                  "agent.runtime.memory.gb_hours.used": 0.5 / 3600}
        if elapsed(i) is not None:
            record["elapsed_time_seconds"] = elapsed(i)
        out.append({"timestamp": T0 + i * 1000, "message": json.dumps(record)})
    return out


def tot(sid, n=60):
    return [{"timestamp": T0 + i * 1000, "message": json.dumps({
        "session.id": sid, "elapsed_time_seconds": i + 1,
        "agent.runtime.vcpu.hours.used": min(i + 1, 6) / 3600,
        "agent.runtime.memory.gb_hours.used": 0.5 * (i + 1) / 3600})} for i in range(n)]


def metrics(share=1.0, cpu_share=None):
    return {"CPUUsed-vCPUHours": 2 * V * (share if cpu_share is None else cpu_share),
            "MemoryUsed-GBHours": 2 * G * share}


def run(kit, monkeypatch, events_for, metric_values, argv=(), minutes_after=90, **state_extra):
    script = load_script("60_read_usage.py")
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 10, 1, tzinfo=dt.timezone.utc)
                        + dt.timedelta(minutes=minutes_after))
    lines: list[str] = []

    def get_metric_statistics(**params):
        if not metric_values:
            return {"Datapoints": []}
        return {"Datapoints": [{"Sum": metric_values[params["MetricName"]]}]}

    aws = make_fake_aws(kit, {
        "get_caller_identity": {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/x", "UserId": "A"},
        "filter_log_events": lambda **p: {"events": events_for(p["filterPattern"].strip('"'))},
        "get_metric_statistics": get_metric_statistics}, lines)
    state = kit.State(kit.STATE_PATH)
    data = {"region": "us-east-1", "prefix": "kitdemo", "account_id": ACCOUNT,
            "runtime_id": RUNTIME_ID, "runtime_arn": RUNTIME_ARN, "model_id": "us.amazon.nova-micro-v1:0",
            "reported_platform_version": "not reported", "requested_platform_version": "default",
            "deliveries": [{"kind": "usage", "log_type": "USAGE_LOGS"}],
            "sessions": [{"session_id": s, "started_at": "2026-10-07T10:00:00Z",
                          "ended_at": "2026-10-07T10:01:00Z", "stopped": True,
                          "calls": [{"input_tokens": 3000, "output_tokens": 500}]} for s in (S1, S2)]}
    data.update(state_extra)
    state.set(**data)
    rc = script.main(list(argv), aws=aws, out=lines.append, state=state)
    results = [line for line in lines if line.startswith("RESULT:")]
    assert len(results) == (0 if rc == 2 else 1), lines
    return rc, (results[0] if results else ""), lines, state


# ====================================================================== B1: the reviewer's four failing inputs
ONE_RECORD_NO_ELAPSED = lambda s: [{"timestamp": T0, "message": json.dumps({  # noqa: E731
    "session.id": s, "agent.runtime.vcpu.hours.used": V * 0.1, "agent.runtime.memory.gb_hours.used": G * 0.1})}]
B1_INPUTS = [
    ("one record per session, no elapsed, both sources 10% delivered", ONE_RECORD_NO_ELAPSED, metrics(0.1)),
    ("increments whose elapsed counts from session start, 50% delivered",
     lambda s: inc(s, 30, elapsed=lambda i: i + 1), metrics(0.5, 1.0)),
    ("the same, 20% delivered", lambda s: inc(s, 12, elapsed=lambda i: i + 1), metrics(0.2, 1.0)),
    ("increments with no elapsed field, 50% delivered", lambda s: inc(s, 30, elapsed=lambda i: None),
     metrics(0.5, 1.0)),
]


@pytest.mark.parametrize("name, events_for, metric_values", B1_INPUTS, ids=[c[0] for c in B1_INPUTS])
def test_B1_partial_data_read_five_minutes_after_the_sessions_is_not_cross_checked(
        kit, monkeypatch, name, events_for, metric_values):
    rc, result, lines, state = run(kit, monkeypatch, events_for, metric_values, minutes_after=5)
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED"), result
    assert state.get("usage_cross_checked_at") is None  # the teardown warning is not silenced
    assert "this was read 5 minute(s) after the last session ended" in result


@pytest.mark.parametrize("name, events_for, metric_values", B1_INPUTS, ids=[c[0] for c in B1_INPUTS])
def test_B1_the_same_partial_data_is_not_cross_checked_after_the_delay_either(
        kit, monkeypatch, name, events_for, metric_values):
    """Lateness is one reason. Records that cannot show what they cover are another, on their own."""
    rc, result, lines, state = run(kit, monkeypatch, events_for, metric_values, minutes_after=90)
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED"), result
    assert "do not say how much time they cover" in result or "of their wall-clock time" in result
    assert state.get("usage_cross_checked_at") is None


def test_B1_an_early_read_is_a_reason_even_when_the_data_are_complete_and_agree(kit, monkeypatch):
    rc, result, lines, state = run(kit, monkeypatch, inc, metrics(), minutes_after=5)
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED")
    assert "AWS says usage data may be delayed by up to 60 minutes" in result
    assert "read again at or after 2026-10-07T11:01:00Z (UTC)" in result
    assert state.get("usage_cross_checked_at") is None
    text = "\n".join(lines)
    assert "That is EARLY" in text and "Caution:" not in text


def test_B1_fifty_nine_minutes_is_early_and_sixty_is_not(kit, monkeypatch):
    assert run(kit, monkeypatch, inc, metrics(), minutes_after=59)[0] == 1
    rc, result, _, state = run(kit, monkeypatch, inc, metrics(), minutes_after=60)
    assert rc == 0 and result.startswith("RESULT: CROSS-CHECKED:") and "NOT final" not in result
    assert state.get("usage_cross_checked_at") and state.get("usage_read_early") is False


def test_B1_the_owner_can_ask_for_an_early_result_and_the_result_line_says_so(kit, monkeypatch):
    rc, result, lines, state = run(kit, monkeypatch, inc, metrics(), minutes_after=5,
                                   argv=("--accept-early-read",))
    assert rc == 0
    assert result.startswith("RESULT: CROSS-CHECKED, read early at the owner's request, NOT final")
    assert "(5 of 60 minutes had passed)" in result
    assert state.get("usage_read_early") is True
    # the flag does not excuse partial data: only the lateness
    rc, result, _, state = run(kit, monkeypatch, lambda s: inc(s, 30), metrics(0.5, 1.0), minutes_after=5,
                               argv=("--accept-early-read",))
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED")


def test_B1_teardown_still_warns_after_an_early_read(kit, monkeypatch):
    rc, result, lines, state = run(kit, monkeypatch, inc, metrics(), minutes_after=5,
                                   argv=("--accept-early-read",))
    assert state.get("usage_cross_checked_at")
    teardown = load_script("90_teardown.py")
    printed: list[str] = []
    empty = {"agentRuntimes": []}
    handlers = {
        "get_caller_identity": {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/x", "UserId": "A"},
        "list_agent_runtimes": empty, "list_gateways": {"items": []},
        "list_workload_identities": {"workloadIdentities": []}, "list_roles": {"Roles": []},
        "list_buckets": {"Buckets": []}, "describe_log_groups": {"logGroups": []},
        "describe_deliveries": {"deliveries": []}, "describe_delivery_sources": {"deliverySources": []},
        "describe_delivery_destinations": {"deliveryDestinations": []},
        "get_resources": {"ResourceTagMappingList": []}, "stop_runtime_session": {},
        "get_agent_runtime": FakeClientError("ResourceNotFoundException"),
    }
    teardown.main([], aws=make_fake_aws(kit, handlers, printed), out=printed.append, state=state)
    assert any(line.startswith("WARNING: usage for 2 session(s) was read early") for line in printed)


def test_B1_a_later_read_that_fails_takes_the_earlier_stamp_away(kit, monkeypatch):
    rc, _, _, state = run(kit, monkeypatch, inc, metrics())
    assert rc == 0 and state.get("usage_cross_checked_at")
    rc, result, _, state = run(kit, monkeypatch, inc, metrics(2.0),
                               usage_cross_checked_at="2026-10-07T11:31:00Z")
    assert rc == 1 and state.get("usage_cross_checked_at") is None


def test_B1_complete_data_after_the_delay_is_still_cross_checked(kit, monkeypatch):
    """Unchanged: the fix must not make a good read fail."""
    for events_for in (inc, tot, lambda s: tot(s) + tot(s), lambda s: list(reversed(inc(s))),
                       lambda s: inc(s, 60, elapsed=lambda i: i + 1)):
        rc, result, lines, state = run(kit, monkeypatch, events_for, metrics())
        assert rc == 0 and result.startswith("RESULT: CROSS-CHECKED:"), result
        assert f"${TRUE_COST:.6f}" in result


def test_B1_running_totals_that_arrive_out_of_order_are_read_by_their_elapsed_time(kit, monkeypatch):
    def shuffled(sid):
        import random

        events = tot(sid)
        random.Random(1).shuffle(events)
        stamps = sorted(e["timestamp"] for e in events)
        return [dict(e, timestamp=t) for e, t in zip(events, stamps)]

    rc, result, _, _ = run(kit, monkeypatch, shuffled, metrics())
    assert rc == 0 and "running totals" in result


def test_B1_coverage_for_each_record_layout(kit):
    script = load_script("60_read_usage.py")

    def covered(events):
        entry = script.parse_usage_events(events)["sessions"][S1]
        return script.record_shape(entry), script.covered_seconds(entry, script.record_shape(entry))

    assert covered(inc(S1)) == ("increment", 60)
    assert covered(inc(S1, 30)) == ("increment", 30)
    assert covered(inc(S1, 30, elapsed=lambda i: i + 1)) == ("increment", 30)   # not 1+2+...+30 = 465
    assert covered(inc(S1, 60, elapsed=lambda i: i + 1)) == ("increment", 60)
    assert covered(inc(S1, 30, elapsed=lambda i: None)) == ("unknown", None)
    assert covered(tot(S1, 30)) == ("running_total", 30)
    assert covered(tot(S1)[9:10]) == ("single", 10)
    assert covered(ONE_RECORD_NO_ELAPSED(S1)) == ("single", None)


def test_B1_an_event_returned_twice_with_the_same_id_is_counted_once(kit):
    script = load_script("60_read_usage.py")
    events = [dict(e, eventId=str(i)) for i, e in enumerate(inc(S1))]
    parsed = script.parse_usage_events(events + events)["sessions"][S1]
    assert parsed["records"] == 60


# ====================================================================== minor: the 0.84 ratio
def test_minor_logs_sixteen_percent_under_the_metrics_are_not_cross_checked(kit, monkeypatch):
    rc, result, _, _ = run(kit, monkeypatch, inc, metrics(1 / 0.84))
    assert rc == 1 and "neither reading of the logs is within 10% of the metric total" in result


def test_minor_the_result_line_gives_both_figures_and_tells_the_reader_to_quote_the_range(kit, monkeypatch):
    rc, result, _, _ = run(kit, monkeypatch, inc, metrics(1.08))
    assert rc == 0 and "The two are 7.4% apart (tolerance 10%)." in result
    assert f"Quote the range ${TRUE_COST:.6f} to ${TRUE_COST * 1.08:.6f}, not the lower figure alone." in result
    exact = run(kit, monkeypatch, inc, metrics())[1]
    assert "The two are 0.0% apart" in exact and "Quote the range" not in exact


def test_minor_a_wider_tolerance_is_the_owners_choice_and_is_echoed(kit, monkeypatch):
    rc, result, _, _ = run(kit, monkeypatch, inc, metrics(1.19), argv=("--tolerance-percent", "20"))
    assert rc == 0 and "tolerance 20%, set with --tolerance-percent" in result
    assert run(kit, monkeypatch, inc, metrics(1.19))[0] == 1
    assert run(kit, monkeypatch, inc, metrics(), argv=("--tolerance-percent", "80"))[0] == 2


# ====================================================================== minor: the rates line and the assumed version
def test_minor_the_rates_line_says_when_the_platform_version_was_assumed(kit, monkeypatch):
    rc, result, lines, _ = run(kit, monkeypatch, inc, metrics())
    rates = next(line for line in lines if line.startswith("Rates ("))
    assert rates.startswith("Rates (V1, ASSUMED: AWS documents V1 when none is asked for; the service "
                            "reported no version. If the runtime is really on V2, these rates are wrong)")
    assert "Rates: V1, ASSUMED" in result
    v2_cost = 2 * (V * 0.1276 + G * 0.0169)
    assert f"At V2 rates the same usage would be ${v2_cost:.6f}." in result

    rc, result, lines, _ = run(kit, monkeypatch, inc, metrics(), requested_platform_version="V2")
    rates = next(line for line in lines if line.startswith("Rates ("))
    assert rates.startswith("Rates (V2, ASSUMED from what the deploy asked for; the service reported no version")
    assert "At V1 rates the same usage would be" in result

    rc, result, lines, _ = run(kit, monkeypatch, inc, metrics(), reported_platform_version="V2")
    rates = next(line for line in lines if line.startswith("Rates ("))
    assert rates.startswith("Rates (V2, the version the service reported)")
    assert "ASSUMED" not in result and "the same usage would be" not in result


# ====================================================================== minor: the global inference profile price
def test_minor_a_global_inference_profile_has_its_own_lower_price(kit, monkeypatch):
    """Read 2026-10-07 from the AWS Price List file for us-east-1 (publicationDate
    2026-10-06T14:47:26Z): Nova2.0Lite-input-tokens-cross-region-global $0.0003 per 1K tokens,
    Nova2.0Lite-output-tokens-cross-region-global $0.0025 per 1K tokens."""
    assert kit.model_token_price("global.amazon.nova-2-lite-v1:0", "us-east-1")[:2] == (0.30, 2.50)
    assert kit.model_token_price("us.amazon.nova-2-lite-v1:0", "us-east-1")[:2] == (0.33, 2.75)
    assert kit.model_token_price("amazon.nova-2-lite-v1:0", "us-west-2")[:2] == (0.33, 2.75)
    assert kit.model_token_price("us.amazon.nova-micro-v1:0", "us-east-2")[:2] == (0.035, 0.14)
    # no row in the price file, or a profile or Region this kit did not read: no price
    assert kit.model_token_price("global.amazon.nova-micro-v1:0", "us-east-1") is None
    assert kit.model_token_price("eu.amazon.nova-2-lite-v1:0", "us-east-1") is None
    assert kit.model_token_price("us.amazon.nova-micro-v1:0", "eu-west-1") is None
    rc, result, lines, _ = run(kit, monkeypatch, inc, metrics(), model_id="global.amazon.nova-2-lite-v1:0")
    token_line = next(line for line in lines if line.startswith("Token cost:"))
    assert "x $0.3 + 1000 / 1,000,000 x $2.5 = $0.004300" in token_line
    assert "the global cross-Region price" in token_line


# ====================================================================== M4: times a script prints, not a stopwatch
def test_M4_the_usage_read_prints_its_utc_time_and_the_minutes_since_the_last_session(kit, monkeypatch):
    rc, result, lines, _ = run(kit, monkeypatch, inc, metrics())
    text = "\n".join(lines)
    assert ("This read: 2026-10-07T11:31:00Z (UTC), 90 minute(s) after the last session ended "
            "(2026-10-07T10:01:00Z).") in text
    assert "Read at 2026-10-07T11:31:00Z (UTC), 90 minute(s) after the last session ended." in result


def test_M4_elapsed_line_gives_minutes_seconds_and_a_utc_stamp(kit, monkeypatch):
    monkeypatch.setattr(kit, "monotonic", lambda: 292.0)
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 12, 0, 5, tzinfo=dt.timezone.utc))
    assert kit.elapsed_line("create call to runtime READY", 100.0) == (
        "create call to runtime READY: 3.2 minutes (192 s), at 2026-10-07T12:00:05Z (UTC)")


def test_M4_every_row_of_the_results_template_that_asks_for_a_time_names_a_line_a_script_prints():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    template = (root / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
    sources = "\n".join((root / name).read_text(encoding="utf-8") for name in (
        "30_deploy.py", "50_invoke_hosted.py", "60_read_usage.py", "90_teardown.py", "99_verify_clean.py",
        "optional_gateway/10_create_gateway.py", "kitlib.py"))
    rows = [line for line in template.splitlines()
            if line.startswith("|") and re.search(r"\b(Minutes|Seconds|Hours|time|UTC)\b", line)]
    assert len(rows) >= 8
    for row in rows:
        quoted = re.findall(r'"([^"]+)"', row)
        assert quoted, f"this row asks for a time but names no printed line: {row}"
        for phrase in quoted:
            assert phrase in sources, f"no script prints {phrase!r} (row: {row})"
