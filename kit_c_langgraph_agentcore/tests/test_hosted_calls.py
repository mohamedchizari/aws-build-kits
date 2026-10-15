"""Review finding M4 (what the latency numbers are) and minor 9 (a stop that fails).

M4  (a) one-off client work is done before the first timed call;
    (b) the first and the later call of a session ask the same question;
    (c) the output says what the numbers are: end to end, small n, not a measured cold start;
    (d) the invoke call is sent exactly once, never retried.
"""
from __future__ import annotations

import json

from conftest import ACCOUNT, RUNTIME_ARN, RUNTIME_ID, FakeClientError, load_script, make_fake_aws

IDENTITY = {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/x", "UserId": "A"}
GOOD = {"result": "One rule: 2026-19964.", "tool_calls": [{}], "citations": [{"document_number": "2026-19964"}],
        "unverified_document_numbers": [], "tool_errors": [], "warnings": [], "grounding": "ok",
        "grounding_reasons": [], "answer_replaced": False, "usage": {"input_tokens": 10, "output_tokens": 5},
        "stopped": None}


def setup(kit, handlers=None, **state_extra):
    script = load_script("50_invoke_hosted.py")
    state = kit.State(kit.STATE_PATH)
    data = dict(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_arn=RUNTIME_ARN,
                runtime_id=RUNTIME_ID, idle_timeout_s=120, max_lifetime_s=900)
    data.update(state_extra)
    state.set(**data)
    lines: list[str] = []
    answers = {"get_caller_identity": IDENTITY,
               "invoke_agent_runtime": lambda **p: {"statusCode": 200, "response": json.dumps(GOOD).encode()},
               "stop_runtime_session": {"statusCode": 200}}
    answers.update(handlers or {})
    aws = make_fake_aws(kit, answers, lines)
    return script, state, aws, lines


def test_every_call_of_a_session_asks_the_same_question(kit):
    script, state, aws, lines = setup(kit)
    rc = script.main(["--i-understand-this-bills", "--sessions", "2", "--calls-per-session", "3"],
                     aws=aws, out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    payloads = [p["payload"] for _, op, p in aws.calls if op == "invoke_agent_runtime"]
    assert len(payloads) == 6 and len(set(payloads)) == 1
    assert json.loads(payloads[0]) == {"prompt": script.DEFAULT_QUESTION}


def test_more_than_one_question_is_refused_so_calls_stay_comparable(kit):
    script, state, aws, lines = setup(kit)
    rc = script.main(["--i-understand-this-bills", "--question", "a", "--question", "b"],
                     aws=aws, out=lines.append, state=state)
    assert rc == 2 and aws.calls == []
    assert any("--question may be given once" in line for line in lines)


def test_the_invoke_call_is_sent_exactly_once_and_the_stop_may_retry(kit):
    script, state, aws, lines = setup(kit)
    script.main(["--i-understand-this-bills", "--sessions", "1"], aws=aws, out=lines.append, state=state)
    flags = {op: {p["_single_attempt"] for _, o, p in aws.calls if o == op}
             for op in ("invoke_agent_runtime", "stop_runtime_session")}
    assert flags == {"invoke_agent_runtime": {True}, "stop_runtime_session": {False}}


def test_the_client_is_made_ready_before_the_first_timed_call(kit, monkeypatch):
    script, state, aws, lines = setup(kit)
    order: list[str] = []
    real_warm, real_call = aws.warm, aws.call
    monkeypatch.setattr(aws, "warm", lambda *a, **k: order.append(f"warm:{a[1]}") or real_warm(*a, **k))
    monkeypatch.setattr(aws, "call", lambda *a, **k: order.append(a[1]) or real_call(*a, **k))
    script.main(["--i-understand-this-bills", "--sessions", "1"], aws=aws, out=lines.append, state=state)
    first_invoke = order.index("invoke_agent_runtime")
    assert order.index("get_caller_identity") < first_invoke  # credentials resolved before timing
    assert order.index("warm:invoke_agent_runtime") < first_invoke
    assert order.index("warm:stop_runtime_session") < first_invoke


def test_the_summary_says_what_the_numbers_are(kit):
    script, state, aws, lines = setup(kit)
    script.main(["--i-understand-this-bills", "--sessions", "3"], aws=aws, out=lines.append, state=state)
    text = "\n".join(lines)
    assert "Latency, end to end from this machine" in text
    assert "first call in a new session: n=3  values " in text
    assert "same question again, same session: n=3  values " in text
    assert "It is not a measured cold start, and n is small" in text
    assert "includes cold start" not in text
    assert "(first call, new session)" in text and "(same question, same session)" in text


def test_a_stop_that_fails_makes_the_script_exit_non_zero(kit):
    """Review minor 9. The timeout printed is the one recorded at deploy, not the current config."""
    script, state, aws, lines = setup(kit, {"stop_runtime_session": FakeClientError("AccessDeniedException")},
                                      idle_timeout_s=300, max_lifetime_s=1800)
    rc = script.main(["--i-understand-this-bills", "--sessions", "2"], aws=aws, out=lines.append, state=state)
    assert rc == 1
    text = "\n".join(lines)
    # the code and what AWS said (round 4: the code alone was printed, and the message dropped)
    assert text.count("COULD NOT STOP THE SESSION (AccessDeniedException: x)") == 2
    assert "after 300 idle seconds, the idle timeout recorded when the runtime was deployed" in text
    assert "120 idle seconds" not in text  # the current config default is not what the runtime has
    assert "Sessions that could not be stopped: 2" in text
    sessions = json.loads(kit.STATE_PATH.read_text())["sessions"]
    assert [s["stopped"] for s in sessions] == [False, False]  # so 90_teardown.py tries again


def test_a_stop_failure_without_a_recorded_timeout_names_the_service_default(kit):
    script, state, aws, lines = setup(kit, {"stop_runtime_session": FakeClientError("ThrottlingException")},
                                      idle_timeout_s=None, max_lifetime_s=None)
    rc = script.main(["--i-understand-this-bills", "--sessions", "1"], aws=aws, out=lines.append, state=state)
    assert rc == 1
    assert "the service default is 900 seconds" in "\n".join(lines)


def test_a_call_stopped_at_the_step_limit_is_counted_as_failed(kit):
    stopped = dict(GOOD, result="Stopped: the agent did not finish within 12 graph steps.",
                   grounding="stopped", grounding_reasons=["recursion_limit"], stopped="recursion_limit",
                   citations=[])
    script, state, aws, lines = setup(kit, {
        "invoke_agent_runtime": lambda **p: {"statusCode": 200, "response": json.dumps(stopped).encode()}})
    rc = script.main(["--i-understand-this-bills", "--sessions", "1", "--calls-per-session", "1"],
                     aws=aws, out=lines.append, state=state)
    assert rc == 1 and any("stopped early (recursion_limit)" in line for line in lines)
