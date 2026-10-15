"""Tests added after the fifth independent review (round 5, read on 2026-10-07, fixed on 2026-10-08).

One reader, kit A and common/, 9 MINOR findings (F1 to F9) and one question (Q1); REVIEW_NOTES_r5.md has the
table. Each test below failed on the code as reviewed, except the ones whose name ends in "_control", which pin
behaviour that must not change. The reader's own attack suite is not part of this folder; its cases are named
in the notes next to the test that covers each.

Everything here is offline: the plain fake account in conftest.py (World) and plain fakes. Two tests start
`sh` and `nohup` with a Python that only reads its own SIGINT handler (F7); they make no AWS call.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import signal
import subprocess
import sys
import threading

import pytest

import kitlib
import streamstats
from conftest import ACCOUNT, KIT_DIR, REGION, FakeAwsError, FakeClock, Lines, World, deploy_into, load_script, world_aws
from test_review_r2 import deploy_with_logs, last_line, ns
from test_review_r4 import UnauthorizedSSOTokenError, deploy, guarded_run, lines_of, sso_expired

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
START_HERE = (KIT_DIR / "START_HERE.md").read_text(encoding="utf-8")
OTHER = "us-east-2"
SENT = "BEFORE IT STOPPED, THIS RUN HAD SENT TO AWS: "


class AfterCall:
    """One fake client whose `op` is carried out by the fake account and THEN raises `exc`: an answer lost
    after AWS acted, or a sign-in that failed when botocore signed the retry again."""

    def __init__(self, inner, op: str, exc: BaseException | None = None, then=None):
        self._inner, self._op, self._exc, self._then = inner, op, exc, then

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name != self._op:
            return attr

        def wrapped(**params):
            result = attr(**params)
            if self._then is not None:
                self._then(params)
            if self._exc is not None:
                raise self._exc
            return result

        return wrapped


def wrap(aws, service, op, exc=None, then=None):
    aws._clients[service] = AfterCall(aws._clients[service], op, exc, then)
    return aws


def run_teardown(state_path, cfg, aws, capsys, lines=None):
    lines = lines if lines is not None else Lines()
    clock = FakeClock()
    code, out, err = guarded_run(capsys, "90_teardown.py",
                                 lambda: load_script("90_teardown").run(ns(state_path), cfg, aws, lines, sleep=clock.sleep,
                                                                         clock=clock))
    return code, lines, err


# ======================================================================================================
# F1: a sign-in error raised by a create or delete call was taken as "nothing was sent"
# ======================================================================================================

def test_r5_f1_sign_in_error_raised_by_create_model_counts_as_no_clear_answer(cfg, state_path, capsys):
    """Reviewed code: exit 2 ("stopped before it created anything") with a model in the account. botocore signs
    every retry again, so a sign-in that expires between two tries raises AFTER a request went out."""
    world = World()
    aws = wrap(world_aws(world), "sagemaker", "create_model", sso_expired())
    code, out, err = guarded_run(capsys, "10_deploy.py", lambda: deploy(state_path, cfg, aws)[0])
    assert world.place(ACCOUNT, REGION)["models"], "the first try was carried out"
    assert code == 1
    assert lines_of(err)[-1].startswith(SENT + "CreateModel (no clear answer). ")
    assert kitlib.state_resources(kitlib.load_state(state_path), "model"), "the model stays on record"


def test_r5_f1_sign_in_error_raised_by_create_endpoint_is_named_on_the_last_line(cfg, state_path, capsys):
    world = World()
    aws = world_aws(world, fail={"create_endpoint_after": sso_expired()})
    code, out, err = guarded_run(capsys, "10_deploy.py", lambda: deploy(state_path, cfg, aws)[0])
    assert code == 1
    assert SENT + "CreateModel, CreateEndpointConfig, CreateEndpoint (no clear answer). " in lines_of(err)[-1]
    state = kitlib.load_state(state_path)
    assert kitlib.state_resources(state, "endpoint") and state["deploy"], "the endpoint stays on record"


def test_r5_f1_sign_in_error_raised_by_delete_endpoint_is_exit_1_and_named(cfg, state_path, capsys):
    """Reviewed code: exit 2 and "This run created and deleted nothing in AWS" after the endpoint was deleted."""
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = wrap(world_aws(world), "sagemaker", "delete_endpoint", sso_expired())
    code, lines, err = run_teardown(state_path, cfg, aws, capsys)
    assert cfg.endpoint_name not in world.place(ACCOUNT, REGION)["endpoints"], "the delete was carried out"
    assert code == 1 and "created and deleted nothing" not in err
    assert lines_of(err)[-1].startswith(SENT + "DeleteEndpoint (no clear answer). ")
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint"), "not confirmed gone: still on record"


@pytest.mark.parametrize("name", ["NoCredentialsError", "NoRegionError", "ProfileNotFound", "ParamValidationError"])
def test_r5_f1_errors_botocore_raises_before_the_first_try_leave_no_mark_control(name):
    """botocore raises these before any request leaves (no credentials at all, no Region, an unknown profile, a
    request it refuses to build); none of them can come from signing a retry, so nothing was sent."""
    error = type(name, (Exception,), {})("before sending")
    sent = kitlib.sent_changes()
    sent.clear()
    aws = world_aws(World(), fail={"create_model": error})
    with pytest.raises(type(error)):
        aws.call("sagemaker", "create_model", ModelName="m")
    assert sent == []


# ======================================================================================================
# F3: Ctrl-C after a create gave exit 130 and "If an endpoint exists", naming no call
# ======================================================================================================

def test_r5_f3_ctrl_c_during_the_deploy_wait_names_the_calls_and_exits_130(cfg, state_path, capsys):
    world = World()
    aws = world_aws(world, fail={"describe_endpoint": KeyboardInterrupt()})
    code, out, err = guarded_run(capsys, "10_deploy.py", lambda: deploy(state_path, cfg, aws)[0])
    last = lines_of(err)[-1]
    assert code == 130
    assert last.startswith(SENT + "CreateModel, CreateEndpointConfig, CreateEndpoint. ") and "Exit code 130." in last
    assert "If an endpoint exists" not in err and "Interrupted (Ctrl-C)." in err
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint")


def test_r5_f3_ctrl_c_inside_create_endpoint_names_it_as_no_clear_answer(cfg, state_path, capsys):
    world = World()
    aws = world_aws(world, fail={"create_endpoint_after": KeyboardInterrupt()})
    code, out, err = guarded_run(capsys, "10_deploy.py", lambda: deploy(state_path, cfg, aws)[0])
    assert code == 130 and "CreateEndpoint (no clear answer)" in lines_of(err)[-1]
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint")


def test_r5_f3_ctrl_c_before_any_create_says_nothing_was_changed(cfg, state_path, capsys):
    world = World()
    aws = world_aws(world, fail={"get_caller_identity": KeyboardInterrupt()})
    code, out, err = guarded_run(capsys, "10_deploy.py", lambda: deploy(state_path, cfg, aws)[0])
    assert code == 130 and lines_of(err)[-1].startswith("STOPPED BEFORE ANY CHANGE: this run created and deleted nothing")
    assert not world.operations("create")


def test_r5_f3_the_documents_give_ctrl_c_its_own_code():
    step2 = README.split("2. **Deploy. Billing starts here.**")[1].split("3. **Call it three ways.**")[0]
    assert "every stop is exit code 1 and the last line names the calls" not in step2
    assert "130" in step2 and "Ctrl-C" in step2
    limit11 = README.split("11. **Exit code 1 has one more meaning.**")[1].split("12. **")[0]
    assert "130" in limit11
    deploy_doc = load_script("10_deploy").__doc__
    assert "130" in deploy_doc and "Ctrl-C" in deploy_doc
    assert "130" in kitlib.guarded.__doc__ and "Ctrl-C" in kitlib.guarded.__doc__


# ======================================================================================================
# F4: after a failed listing, teardown said "its hourly charge has stopped" when it had deleted nothing
# ======================================================================================================

def test_r5_f4_failed_listing_with_the_endpoint_absent_does_not_say_the_charge_stopped(cfg, state_path, capsys):
    world = World()
    world.place(ACCOUNT, OTHER)["endpoints"][cfg.endpoint_name] = {"status": "InService"}  # billing elsewhere
    aws = world_aws(world, fail={"list_endpoints": FakeAwsError("ThrottlingException", "Rate exceeded", 400)})
    code, lines, err = run_teardown(state_path, cfg, aws, capsys)
    assert code == 1 and cfg.endpoint_name in world.place(ACCOUNT, OTHER)["endpoints"]
    assert "charge has stopped" not in lines.text and "confirmed gone" not in lines.text
    told = next(line for line in lines if line.startswith(f"Endpoint {cfg.endpoint_name} was not found"))
    assert REGION in told and "deleted nothing" in told and "NOTHING ELSE WAS DELETED OR CHECKED" in told
    assert "state file was not changed" not in told and "no state file" in told


def test_r5_f4_failed_listing_that_deleted_the_endpoint_still_says_the_charge_stopped_control(cfg, state_path, capsys):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = world_aws(world, fail={"list_endpoints": FakeAwsError("ThrottlingException", "Rate exceeded", 400)})
    code, lines, err = run_teardown(state_path, cfg, aws, capsys)
    assert code == 1 and "its hourly charge has stopped" in lines.text and "the state file was not changed" in lines.text


# ======================================================================================================
# F5: the endpoints a setting change replaced were shown as "0.00 h, about $0.00" with the clock set back
# ======================================================================================================

def change_run(state_path, cfg, aws):
    out, clock = Lines(), FakeClock()
    args = ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True, ignore_deadline=True)
    return load_script("70_change_one_setting").run(args, cfg, aws, out, sleep=clock.sleep, clock=clock), out


def replaced_line(state_path):
    lines = kitlib.billing_lines(kitlib.load_state(state_path), kitlib.utc_now())
    return next(line for line in lines if line.startswith("Not in that figure"))


def test_r5_f5_replaced_endpoint_with_the_clock_set_back_is_unknown_not_zero(cfg, state_path):
    world = World()
    state = deploy_into(world, cfg, state_path)
    state["deploy"]["create_called_utc"] = kitlib.iso(kitlib.utc_now() + dt.timedelta(hours=2))  # clock behind
    state_path.write_text(json.dumps(state), encoding="utf-8")
    code, out = change_run(state_path, cfg, world_aws(world))
    line = replaced_line(state_path)
    assert code == 0 and "0.00 h" not in line and "$0.00" not in line
    assert "UNKNOWN" in line and "use your bill" in line


def test_r5_f5_replaced_endpoint_answered_already_exists_keeps_that_caveat(cfg, state_path):
    world = World()
    state = deploy_into(world, cfg, state_path)
    state["deploy"]["create_answer"] = "already exists"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    code, out = change_run(state_path, cfg, world_aws(world))
    assert code == 0 and "already exists" in replaced_line(state_path)


# ======================================================================================================
# F6: a request whose send() raised disappeared from the level uncounted
# ======================================================================================================

GOOD = streamstats.RequestResult(ok=True, error="", ttft_s=0.1, total_s=1.0, output_tokens=10, tokens_source="usage",
                                 prompt_tokens=1, request_tokens_per_s=10.0, decode_tokens_per_s=11.0, text_chunks=10,
                                 finish_reason="length", saw_done=True)


def test_r5_f6_a_send_that_raises_is_counted_as_a_failed_request(monkeypatch):
    module = load_script("60_loadtest")
    seen = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args))

    def send(index):
        if index == 3:
            raise RuntimeError("a bug in the measuring code")
        return GOOD

    results, wall = module.run_level(send, concurrency=2, requests=6)
    failed = [r for r in results if not r.ok]
    assert len(results) == 6 and len(failed) == 1, results
    assert "RuntimeError" in failed[0].error and "a bug in the measuring code" in failed[0].error
    assert seen == [], "no worker thread died"


# ======================================================================================================
# F7: the README blamed nohup for an ignored interrupt signal
# ======================================================================================================

PROBE = "import signal; print(signal.getsignal(signal.SIGINT) is signal.SIG_IGN)"


def test_r5_f7_readme_and_fixture_blame_the_background_start_not_nohup():
    step5 = README.split("5. **Predict, then measure the baseline.**")[1].split("6. **Change one setting.**")[0]
    assert "Started with `nohup` or with `&`" not in step5
    assert "`&`" in step5 and "`nohup`" in step5 and "hang-up" in step5
    fixture = (KIT_DIR / "tests" / "test_review_r4.py").read_text(encoding="utf-8")
    assert "`nohup` or with `&`" not in fixture


@pytest.mark.skipif(shutil.which("nohup") is None or shutil.which("sh") is None, reason="needs nohup and sh")
def test_r5_f7_what_the_readme_now_says_about_nohup_and_the_background_holds_control(tmp_path):
    reset = lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)  # noqa: E731 - start from the default, like a Terminal
    nohup = subprocess.run(["nohup", sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=30,
                           preexec_fn=reset, cwd=tmp_path)
    background = subprocess.run(["sh", "-c", f'"{sys.executable}" -c "{PROBE}" & wait'], capture_output=True,
                                text=True, timeout=30, preexec_fn=reset, cwd=tmp_path)
    assert nohup.stdout.strip() == "False", "nohup in the foreground leaves SIGINT alone"
    assert background.stdout.strip() == "True", "& in a non-interactive shell starts the process with SIGINT ignored"


# ======================================================================================================
# F8: last lines and BILLING blocks the documents promised
# ======================================================================================================

def test_r5_f8_a_failed_change_ends_with_the_billing_block(cfg, state_path):
    world = World()
    deploy_into(world, cfg, state_path)

    def to_failed(params):
        world.place(ACCOUNT, REGION)["endpoints"][params["EndpointName"]]["status"] = "Failed"

    code, out = change_run(state_path, cfg, wrap(world_aws(world), "sagemaker", "create_endpoint", then=to_failed))
    assert code == 1 and kitlib.state_resources(kitlib.load_state(state_path), "endpoint")
    now_line = max(i for i, line in enumerate(out) if line.startswith("Now: python 55_observe.py --logs-only"))
    block = out[now_line + 1:]
    assert any(line.startswith("BILLING:") for line in block) and block[-1] == "=" * 72
    assert any(line.startswith("To stop the charge: python 90_teardown.py") for line in block)


def test_r5_f8_teardown_incomplete_is_the_last_line(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = world_aws(world)

    def stays(**params):
        world.place(ACCOUNT, REGION)["endpoints"][params["EndpointName"]]["status"] = "Deleting"
        return {}

    inner = aws._clients["sagemaker"]
    aws._clients["sagemaker"] = type("Stays", (), {"__getattr__": lambda self, n: stays if n == "delete_endpoint"
                                                   else getattr(inner, n)})()
    out, clock = Lines(), FakeClock()
    code = load_script("90_teardown").run(ns(state_path), cfg, aws, out, sleep=clock.sleep, clock=clock)
    assert code == 1 and last_line(out).startswith("TEARDOWN INCOMPLETE: ")
    assert "Wait five minutes" in last_line(out), "what to do stays on the line"


def test_r5_f8_teardown_stopped_before_any_delete_has_a_named_last_line(cfg, state_path, capsys):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = world_aws(world, fail={"get_caller_identity": FakeAwsError("AccessDenied", "not allowed", 403)})
    code, lines, err = run_teardown(state_path, cfg, aws, capsys)
    last = lines_of(err)[-1]
    assert code != 0 and last.startswith("STOPPED BEFORE ANY CHANGE: ")
    assert "created and deleted nothing" in last and "keeps billing" in last
    section5 = README.split("## 5. Tear it down and prove it")[1].split("## 6. What to record")[0]
    assert "`STOPPED BEFORE ANY CHANGE`" in " ".join(section5.split())


def test_r5_f8_start_here_describes_the_billing_block_as_it_is_printed(cfg):
    from test_kitlib import deployed_state

    block = kitlib.billing_lines(deployed_state(cfg, created=kitlib.utc_now()), kitlib.utc_now())
    assert block[0] == block[-1] == "=" * 72, "the block starts and ends with a rule"
    assert block[-2].startswith("To stop the charge: python 90_teardown.py")
    text = " ".join(START_HERE.split())
    assert "whose last line is `To stop the charge" not in text
    assert "`BILLING:`" in text and "To stop the charge: python 90_teardown.py" in START_HERE


# ======================================================================================================
# F9: the output filter rewrote a valid KIT_PREFIX with 12 digits in a row
# ======================================================================================================

# The prefix of the reader's case S01, a timestamp. Built from two parts because tests/test_kit_rules.py refuses
# a literal 12-digit number in the kit's files (it could be an account id).
STAMP = "2026" + "10071230"
TIMESTAMP_PREFIX = "kit-" + STAMP


def test_r5_f9_twelve_digits_inside_the_prefix_are_printed_as_they_are(state_path, monkeypatch):
    import io

    cfg12 = kitlib.load_config(environ={"KIT_PREFIX": TIMESTAMP_PREFIX}, env_file=KIT_DIR / "does-not-exist.env")
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    code = kitlib.guarded(lambda: load_script("99_verify_clean").run(ns(state_path), cfg12, world_aws(World())),
                          "99_verify_clean.py")
    text = buffer.getvalue()
    result = next(line for line in text.splitlines() if line.startswith("RESULT:"))
    assert f"prefix {TIMESTAMP_PREFIX} " in result and "[account ending 1230]" not in text
    assert "ending 3333" in result and ACCOUNT not in text, "the account itself is still cut to four digits"


def test_r5_f9_an_account_id_is_still_masked_wherever_it_is_not_the_prefix(monkeypatch):
    from conftest import OTHER_ACCOUNT

    monkeypatch.setattr(kitlib, "_ACCOUNTS_READ", set())  # earlier tests in this process read OTHER_ACCOUNT
    kitlib.load_config(environ={"KIT_PREFIX": TIMESTAMP_PREFIX}, env_file=KIT_DIR / "does-not-exist.env")
    text = kitlib.redact(f"arn:aws:iam::{OTHER_ACCOUNT}:user/x and {TIMESTAMP_PREFIX}-kita-endpoint and {STAMP}")
    assert OTHER_ACCOUNT not in text and f"{TIMESTAMP_PREFIX}-kita-endpoint" in text
    assert text.endswith("and [account ending 1230]"), "the same digits on their own are masked"
    kitlib.load_config(environ={"KIT_PREFIX": OTHER_ACCOUNT}, env_file=KIT_DIR / "does-not-exist.env")
    assert kitlib.redact(f"prefix {OTHER_ACCOUNT}") == "prefix [account ending 6666]", "an all-digit prefix stays masked"
    kitlib.load_config(environ={"KIT_PREFIX": "a" + OTHER_ACCOUNT}, env_file=KIT_DIR / "does-not-exist.env")
    assert kitlib.redact("a" + OTHER_ACCOUNT) == "a" + OTHER_ACCOUNT, "inside a prefix with a letter: shown"
    kitlib.caller_account(world_aws(World(), account=OTHER_ACCOUNT))
    assert OTHER_ACCOUNT not in kitlib.redact("a" + OTHER_ACCOUNT), "the account of these credentials is never shown"


# ======================================================================================================
# Q1 and the record of this round
# ======================================================================================================

def test_r5_q1_the_round_4_line_says_which_fixes_leave_a_limit():
    section8 = " ".join(README.split("## 8. What was and was not tested")[1].split("## 9. Sources")[0].split())
    line = section8.split("(round 4): ")[1].split("(round 5)")[0]
    assert "MINOR 3" in line and "words only" in line and "14" in line and "MAJOR 2" in line and "13" in line


def test_r5_readme_and_notes_record_round_5():
    section8 = " ".join(README.split("## 8. What was and was not tested")[1].split("## 9. Sources")[0].split())
    assert "(round 5)" in section8 and "`REVIEW_NOTES_r5.md`" in section8
    notes = (KIT_DIR / "REVIEW_NOTES_r5.md").read_text(encoding="utf-8")
    for finding in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "Q1"):
        assert f"| {finding} " in notes, finding
