"""Review findings B2, B3 and B4: 60_read_usage.py.

B2  Token prices are per 1,000,000 tokens, the unit the Bedrock pricing page uses.
B3  Usage data can be up to 60 minutes late; a partial read must not look like a result.
B4  The cross-check must fail closed: a session cost is CROSS-CHECKED only when usage logs
    and CloudWatch metrics both exist and agree within the stated tolerance. Both the
    per-session sum and the per-session maximum are always printed.

The "true" session used throughout is the reviewer's: 60 seconds alive, 6 seconds of one
vCPU, 0.5 GB for the whole time. Two such sessions cost $0.000456 at V1 rates.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import ACCOUNT, RUNTIME_ARN, RUNTIME_ID, FakeClientError, load_script, make_fake_aws

S1, S2 = "kitdemo-kitc-" + "a" * 32, "kitdemo-kitc-" + "b" * 32
TRUE_V = 6 / 3600
TRUE_G = 0.5 * 60 / 3600
TRUE_COST = 2 * (TRUE_V * 0.0895 + TRUE_G * 0.00945)
METRICS_OK = {"CPUUsed-vCPUHours": 2 * TRUE_V, "MemoryUsed-GBHours": 2 * TRUE_G}
T0 = 1791367200000  # any millisecond timestamp; only the order matters


def increments(sid, n=60):
    """One record per second, each an increment."""
    return [{"timestamp": T0 + i * 1000, "message": json.dumps({
        "session.id": sid, "elapsed_time_seconds": 1,
        "agent.runtime.vcpu.hours.used": (1 / 3600 if i < 6 else 0),
        "agent.runtime.memory.gb_hours.used": 0.5 / 3600})} for i in range(n)]


def running(sid, n=60):
    """One record per second, each a running total."""
    return [{"timestamp": T0 + i * 1000, "message": json.dumps({
        "session.id": sid, "elapsed_time_seconds": i + 1,
        "agent.runtime.vcpu.hours.used": min(i + 1, 6) / 3600,
        "agent.runtime.memory.gb_hours.used": 0.5 * (i + 1) / 3600})} for i in range(n)]


def state_for(kit, **extra):
    state = kit.State(kit.STATE_PATH)
    data = {"region": "us-east-1", "prefix": "kitdemo", "account_id": ACCOUNT,
            "runtime_id": RUNTIME_ID, "runtime_arn": RUNTIME_ARN, "model_id": "us.amazon.nova-micro-v1:0",
            "reported_platform_version": "not reported", "requested_platform_version": "default",
            "deliveries": [{"kind": "usage", "log_type": "USAGE_LOGS"}],
            "sessions": [{"session_id": s, "started_at": "2026-10-07T10:00:00Z",
                          "ended_at": "2026-10-07T10:01:00Z", "stopped": True,
                          "calls": [{"input_tokens": 3000, "output_tokens": 500},
                                    {"input_tokens": 3000, "output_tokens": 500}]} for s in (S1, S2)]}
    data.update(extra)
    state.set(**data)
    return state


def run(kit, monkeypatch, events_for, metrics, argv=(), minutes_after=90, **state_extra):
    script = load_script("60_read_usage.py")
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 10, 1, tzinfo=dt.timezone.utc)
                        + dt.timedelta(minutes=minutes_after))
    lines: list[str] = []

    def filter_log_events(**params):
        if "kitc-usage" not in params["logGroupName"]:
            return FakeClientError("ResourceNotFoundException")
        return {"events": events_for(params["filterPattern"].strip('"'))}

    def get_metric_statistics(**params):
        if not metrics:
            return {"Datapoints": []}
        return {"Datapoints": [{"Sum": metrics[params["MetricName"]]}]}

    aws = make_fake_aws(kit, {
        "get_caller_identity": {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/x", "UserId": "A"},
        "filter_log_events": filter_log_events, "get_metric_statistics": get_metric_statistics}, lines)
    state = state_for(kit, **state_extra)
    rc = script.main(list(argv), aws=aws, out=lines.append, state=state)
    return rc, "\n".join(lines), lines, state


def result_line(lines):
    found = [line for line in lines if line.startswith("RESULT:")]
    assert len(found) == 1, lines
    return found[0]


# ====================================================================== B4: the cross-check
def test_increments_that_agree_with_the_metrics_are_cross_checked(kit, monkeypatch):
    rc, text, lines, state = run(kit, monkeypatch, increments, METRICS_OK)
    assert rc == 0, text
    assert result_line(lines).startswith("RESULT: CROSS-CHECKED")
    assert f"${TRUE_COST:.6f}" in result_line(lines) and "increments" in result_line(lines)
    assert "tolerance 10%" in result_line(lines)
    assert state.get("usage_cross_checked_at") and state.get("usage_reading") == "sum"


def test_running_totals_are_not_summed_into_a_figure_48_times_too_large(kit, monkeypatch):
    rc, text, lines, state = run(kit, monkeypatch, running, METRICS_OK)
    assert rc == 0, text
    assert result_line(lines).startswith("RESULT: CROSS-CHECKED")
    assert f"${TRUE_COST:.6f}" in result_line(lines) and "running totals" in result_line(lines)
    assert state.get("usage_reading") == "max"


def test_the_reviewers_case_running_totals_and_no_metrics_fails_closed(kit, monkeypatch):
    """Before the fix this printed $0.021958 for a true $0.000456 with no warning."""
    rc, text, lines, state = run(kit, monkeypatch, running, None)
    assert rc == 1
    line = result_line(lines)
    assert line.startswith("RESULT: NOT CROSS-CHECKED") and "do not quote" in line
    assert "no datapoints" in line
    assert "$0.021958" not in line  # the inflated sum is never offered as the figure
    assert not state.get("usage_cross_checked_at")


def test_both_the_sum_and_the_maximum_are_always_printed(kit, monkeypatch):
    for events, metrics in ((increments, METRICS_OK), (running, None)):
        rc, text, lines, _ = run(kit, monkeypatch, events, metrics)
        assert "Sum of per-session sums" in text and "Sum of per-session maxima" in text
        header = next(line for line in lines if line.startswith("session"))
        for column in ("vCPU-h sum", "vCPU-h max", "GB-h sum", "GB-h max", "USD sum", "USD max",
                       "records", "wall s", "covered s"):
            assert column in header
    # running totals: the per-session maximum is the true session, the sum is not
    assert f"{TRUE_V:.8f}" in text and "0.021958" in text


def test_logs_and_metrics_that_disagree_are_not_cross_checked(kit, monkeypatch):
    double = {name: value * 2 for name, value in METRICS_OK.items()}
    rc, text, lines, _ = run(kit, monkeypatch, increments, double)
    assert rc == 1
    assert result_line(lines).startswith("RESULT: NOT CROSS-CHECKED")
    assert "neither reading" in result_line(lines) and "10%" in result_line(lines)


def test_agreement_inside_the_tolerance_passes_and_just_outside_fails(kit, monkeypatch):
    inside = {name: value * 1.08 for name, value in METRICS_OK.items()}
    outside = {name: value * 1.15 for name, value in METRICS_OK.items()}  # passed at the old 20%
    assert run(kit, monkeypatch, increments, inside)[0] == 0
    assert run(kit, monkeypatch, increments, outside)[0] == 1


def test_a_layout_that_contradicts_the_metric_agreement_is_not_cross_checked(kit, monkeypatch):
    """Records that look like increments, while the metric total matches the maxima instead."""
    one_max = {"CPUUsed-vCPUHours": 2 * (1 / 3600), "MemoryUsed-GBHours": 2 * (0.5 / 3600)}
    rc, text, lines, _ = run(kit, monkeypatch, increments, one_max)
    assert rc == 1 and "record layout" in result_line(lines)


def test_without_a_usage_log_delivery_nothing_is_cross_checked(kit, monkeypatch):
    rc, text, lines, _ = run(kit, monkeypatch, increments, METRICS_OK, deliveries=[])
    assert rc == 1 and result_line(lines).startswith("RESULT: NOT CROSS-CHECKED")
    assert "No USAGE_LOGS delivery is recorded" in text


# ====================================================================== B3: late and partial data
def test_a_session_with_no_records_yet_is_flagged_and_blocks_the_result(kit, monkeypatch):
    half = {name: value / 2 for name, value in METRICS_OK.items()}
    rc, text, lines, _ = run(kit, monkeypatch, lambda sid: increments(sid) if sid == S1 else [], half)
    assert rc == 1
    assert "NO RECORDS YET" in text
    assert "1 of 2 session(s) have no usage records yet" in result_line(lines)


def test_half_the_records_with_no_metrics_is_flagged_partial(kit, monkeypatch):
    """The reviewer's case 5: $0.000228 was printed as the answer for a true $0.000456."""
    rc, text, lines, _ = run(kit, monkeypatch, lambda sid: increments(sid, 30), None)
    assert rc == 1
    assert text.count("PARTIAL: records cover 30 of 60 s") == 2
    assert result_line(lines).startswith("RESULT: NOT CROSS-CHECKED")


def test_half_the_records_is_not_a_result_even_when_equally_late_metrics_agree(kit, monkeypatch):
    half = {name: value / 2 for name, value in METRICS_OK.items()}
    for events in (lambda sid: increments(sid, 30), lambda sid: running(sid, 30)):
        rc, text, lines, _ = run(kit, monkeypatch, events, half)
        assert rc == 1, text
        assert "less than 90% of their wall-clock time" in result_line(lines)


def test_the_sixty_minute_delay_is_stated_with_awss_words_and_teardown_is_held_back(kit, monkeypatch):
    rc, text, lines, _ = run(kit, monkeypatch, running, None, minutes_after=3)
    assert "may be delayed by up to 60 minutes" in text
    assert "3 minute(s) after the last session ended (2026-10-07T10:01:00Z)" in text
    assert "That is EARLY: a read can be final only from 2026-10-07T11:01:00Z (UTC) on" in text
    assert "Do not run 90_teardown.py until it prints RESULT: CROSS-CHECKED" in text


def test_an_early_read_that_agrees_is_not_cross_checked_and_says_when_to_read_again(kit, monkeypatch):
    """Round 1 called this CROSS-CHECKED with a caution. Round 2 (B1): two sources that share one
    delay agree with each other, so lateness is a reason. tests/test_r2_usage.py has the rest."""
    rc, text, lines, state = run(kit, monkeypatch, increments, METRICS_OK, minutes_after=5)
    assert rc == 1 and result_line(lines).startswith("RESULT: NOT CROSS-CHECKED")
    assert "this was read 5 minute(s) after the last session ended" in result_line(lines)
    assert "read again at or after 2026-10-07T11:01:00Z (UTC)" in result_line(lines)
    assert not state.get("usage_cross_checked_at")


# ====================================================================== B2: price per 1M tokens
def test_token_price_is_per_one_million_tokens(kit, monkeypatch):
    """12,000 in and 2,000 out at $0.035 and $0.14 per 1M is $0.000700, not $0.70."""
    rc, text, lines, _ = run(kit, monkeypatch, increments, METRICS_OK,
                             argv=("--input-usd-per-1m", "0.035", "--output-usd-per-1m", "0.14"))
    assert "Model tokens reported by the agent: 12000 in, 2000 out." in text
    token_line = next(line for line in lines if line.startswith("Token cost:"))
    assert "= $0.000700" in token_line and "per 1M tokens" in token_line
    assert "$0.700000" not in text


def test_the_old_per_1k_flags_are_refused(kit, monkeypatch):
    with pytest.raises(SystemExit) as stop:
        run(kit, monkeypatch, increments, METRICS_OK,
            argv=("--input-usd-per-1k", "0.035", "--output-usd-per-1k", "0.14"))
    assert stop.value.code == 2


def test_the_default_models_price_is_built_in_with_its_source(kit, monkeypatch):
    rc, text, lines, _ = run(kit, monkeypatch, increments, METRICS_OK)
    token_line = next(line for line in lines if line.startswith("Token cost:"))
    assert "x $0.035" in token_line and "x $0.14" in token_line and "= $0.000700" in token_line
    assert "2026-10-07" in token_line and "https://aws.amazon.com/bedrock/pricing/" in token_line


def test_no_token_cost_is_invented_for_a_model_the_kit_has_no_price_for(kit, monkeypatch):
    rc, text, lines, _ = run(kit, monkeypatch, increments, METRICS_OK, model_id="us.example.other-v1:0")
    token_line = next(line for line in lines if line.startswith("Token cost:"))
    assert "not computed" in token_line and "PER 1M TOKENS" in token_line


def test_one_price_without_the_other_is_refused(kit, monkeypatch):
    rc, text, lines, _ = run(kit, monkeypatch, increments, METRICS_OK, argv=("--input-usd-per-1m", "0.035"))
    assert "Give both" in next(line for line in lines if line.startswith("Token cost:"))


def test_price_table_matches_what_was_read_from_the_price_file(kit):
    assert kit.MODEL_USD_PER_1M_TOKENS["amazon.nova-micro-v1:0"] == {"geo": (0.035, 0.14)}
    assert kit.MODEL_USD_PER_1M_TOKENS["amazon.nova-2-lite-v1:0"] == {"geo": (0.33, 2.75), "global": (0.30, 2.50)}
    text = " ".join(kit.PRICE_LINES_MODEL)
    assert "per 1M input tokens" in text and "2026-10-07" in text and "per 1,000 " not in text
    script = load_script("60_read_usage.py")
    assert script.token_cost(1_000_000, 1_000_000, 0.035, 0.14) == pytest.approx(0.175)


# ====================================================================== review minor 4 and 14
def test_a_v2_deploy_whose_version_was_not_echoed_is_costed_at_v2_rates(kit, monkeypatch):
    metrics = dict(METRICS_OK)
    rc, text, lines, _ = run(kit, monkeypatch, increments, metrics, requested_platform_version="V2")
    assert "Rates (V2, ASSUMED from what the deploy asked for" in text
    assert "): $0.1276 per vCPU-hour, $0.0169 per GB-hour." in text
    assert kit.Config.from_env().rates("not reported", "default") == ("V1", 0.0895, 0.00945)
    assert kit.Config.from_env().rates("V2", "default") == ("V2", 0.1276, 0.0169)


def test_spans_are_counted_in_the_runtimes_own_log_group_first(kit, monkeypatch):
    script = load_script("60_read_usage.py")
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc))
    lines: list[str] = []
    asked = []

    def filter_log_events(**params):
        asked.append((params["logGroupName"], params.get("logStreamNamePrefix")))
        if params["logGroupName"] == "aws/spans":
            return FakeClientError("ResourceNotFoundException")
        if params.get("logStreamNamePrefix") == "spans":
            return {"events": [{"message": "span"}] * 4}
        return {"events": increments(params["filterPattern"].strip('"'))}

    aws = make_fake_aws(kit, {
        "get_caller_identity": {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/x", "UserId": "A"},
        "filter_log_events": filter_log_events,
        "get_metric_statistics": lambda **p: {"Datapoints": [{"Sum": METRICS_OK[p["MetricName"]]}]}}, lines)
    state = state_for(kit, deliveries=[{"kind": "usage", "log_type": "USAGE_LOGS"},
                                       {"kind": "traces", "log_type": "TRACES"}])
    assert script.main([], aws=aws, out=lines.append, state=state) == 0, "\n".join(lines)
    own_group = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT"
    assert (own_group, "spans") in asked and ("aws/spans", None) in asked
    row = next(line for line in lines if line.startswith("..." + S1[-8:]))
    assert "4/-" in row  # 4 in the runtime's own group, the shared group does not exist


def test_parser_reads_nested_and_string_values(kit):
    script = load_script("60_read_usage.py")
    parsed = script.parse_usage_events([
        {"message": json.dumps({"attributes": {"session.id": "x", "agent.runtime.vcpu.hours.used": "0.001",
                                               "agent.runtime.memory.gb_hours.used": None}})},
        {"message": json.dumps({"session": {"id": "y"}, "elapsed_time_seconds": 5,
                                "agent": {"runtime": {"vcpu": {"hours": {"used": 1e-4}},
                                                      "memory": {"gb_hours": {"used": 2e-4}}}}})},
        {"message": "not json"}])
    assert parsed["unparsed"] == 1
    assert parsed["sessions"]["x"]["vcpu_hours_sum"] == pytest.approx(0.001)
    assert parsed["sessions"]["y"]["gb_hours_max"] == pytest.approx(2e-4)
    assert script.record_shape(parsed["sessions"]["y"]) == "single"
    assert script.record_shape(parsed["sessions"]["x"]) == "single"
    assert script.record_shape({}) == "none"
