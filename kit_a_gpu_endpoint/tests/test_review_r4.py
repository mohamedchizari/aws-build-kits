"""Tests added after the fourth independent review of 2026-10-07 (round 4). One section per finding.

Two readers: one followed the money (every script run as a process against a stateful fake account; its
findings are named BLOCKER, MAJOR, MINOR here as in its report), one ran the kits against a local emulator
(its findings are named "emulator N"). Each test below fails on the code as reviewed, except the ones whose
name ends in "_control", which pin behaviour that must not change. REVIEW_NOTES_r4.md has the table.

Everything here is offline: the plain fake account in conftest.py (World), botocore's Stubber, or plain
fakes for the streaming body.
"""

from __future__ import annotations

import _thread
import csv
import datetime as dt
import json
import re
import signal
import sys
import threading

import pytest

import kitlib
import streamstats
from conftest import ACCOUNT, KIT_DIR, OTHER_REGION, REGION, FakeAwsError, FakeClock, Lines, World, deploy_into, load_script, world_aws
from test_kitlib import deployed_state
from test_review_r2 import deploy_with_logs, last_line, ns, result_line, teardown, verify
from test_scripts import FakeRuntimeAws, loadtest_args, token_stream

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
CALLER = f"arn:aws:iam::{ACCOUNT}:user/somebody"
DENIED = f"User: {CALLER} is not authorized to perform: sagemaker:DeleteEndpoint on resource: arn:aws:sagemaker:{REGION}:{ACCOUNT}:endpoint/x"


class UnauthorizedSSOTokenError(Exception):
    """Same class name as botocore's error for an expired IAM Identity Center sign-in."""


def sso_expired():
    return UnauthorizedSSOTokenError("The SSO session associated with this profile has expired or is otherwise invalid.")


def deploy(state_path, cfg, aws, **overrides):
    out, clock = Lines(), FakeClock()
    args = ns(state_path, i_understand_this_bills=True, **overrides)
    return load_script("10_deploy").run(args, cfg, aws, out, sleep=clock.sleep, clock=clock), out


def guarded_run(capsys, script, call):
    """Run `call` the way the last line of the script `script` does, and return (exit code, stdout, stderr)."""
    argv, sys.argv = sys.argv, [script]
    try:
        code = kitlib.guarded(call)
    finally:
        sys.argv = argv
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def lines_of(text):
    return [line for line in text.splitlines() if line.strip()]


# ======================================================================================================
# BLOCKER 1 and MINOR 14: a stop AFTER the script created or deleted something said "could not run", exit 2
# ======================================================================================================

def test_r4_b1_sign_in_expires_while_deploy_waits_the_last_line_says_billing_and_exit_is_1(cfg, state_path, capsys):
    """Reviewed code: last line "STOP: no usable AWS credentials ... Sign in first", exit 2, with the endpoint
    Creating. The table in common/README.md gives kit A code 2 as "stopped before acting"."""
    world = World()
    aws = world_aws(world, fail={"describe_endpoint": sso_expired()})
    code, out, err = guarded_run(capsys, "10_deploy.py", lambda: deploy(state_path, cfg, aws)[0])
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"], "the endpoint was created before the stop"
    assert code == 1, "exit code 2 means: stopped before anything was created or deleted"
    last = lines_of(err)[-1]
    assert "CreateModel, CreateEndpointConfig, CreateEndpoint" in last
    assert "billing by the hour" in last and "python 90_teardown.py" in last and "python 99_verify_clean.py" in last
    assert "no usable AWS credentials" in err and "--dry-run" not in err, "the dry-run hint is for a run that did nothing"


def test_r4_b1_sign_in_expires_while_teardown_waits_exit_is_1_and_the_delete_is_named(cfg, state_path, capsys):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = world_aws(world, fail={"describe_endpoint": sso_expired()})
    code, out, err = guarded_run(capsys, "90_teardown.py", lambda: teardown(state_path, cfg, aws)[0])
    assert code == 1, "teardown's own docstring: 2 means stopped before deleting anything"
    last = lines_of(err)[-1]
    assert "THIS RUN HAD SENT TO AWS: DeleteEndpoint" in last and "billing" in last and "99_verify_clean.py" in last
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint"), "not confirmed gone, so still on record"


def test_r4_b1_sign_in_missing_before_anything_was_sent_is_still_exit_2_control(cfg, state_path, capsys):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = world_aws(world, fail={"get_caller_identity": sso_expired()})
    code, out, err = guarded_run(capsys, "90_teardown.py", lambda: teardown(state_path, cfg, aws)[0])
    assert code == 2 and "no usable AWS credentials" in err and "--dry-run" in err
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"]


def test_r4_b1_a_stop_before_anything_was_sent_says_so_and_says_what_still_bills(cfg, state_path, capsys):
    """The money reader, on the load test and the other scripts: "an expired sign-in does not" end with the
    billing reminder. Reviewed code: one STOP line and nothing about the endpoint on record."""
    world = World()
    deploy_with_logs(world, cfg, state_path)
    aws = world_aws(world, fail={"get_caller_identity": sso_expired()})
    code, out, err = guarded_run(capsys, "90_teardown.py", lambda: teardown(state_path, cfg, aws)[0])
    assert code == 2
    assert "created and deleted nothing" in lines_of(err)[-1] and "keeps billing" in lines_of(err)[-1]


def test_r4_n14_change_one_setting_exits_1_when_the_old_endpoint_does_not_go(cfg, state_path, capsys, monkeypatch):
    """Reviewed code: DeleteEndpoint accepted, the endpoint never goes, "STOP: The old endpoint is still there",
    exit 2."""
    world = World()
    deploy_into(world, cfg, state_path)
    monkeypatch.setattr(kitlib, "wait_endpoint_gone", lambda *args, **kwargs: False)
    clock, out = FakeClock(), Lines()
    args = ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True)
    run = lambda: load_script("70_change_one_setting").run(args, cfg, world_aws(world), out, sleep=clock.sleep, clock=clock)  # noqa: E731
    code, _, err = guarded_run(capsys, "70_change_one_setting.py", run)
    assert code == 1
    assert "still there" in err and "may still be billing" in err
    assert "THIS RUN HAD SENT TO AWS: DeleteEndpoint" in lines_of(err)[-1]
    assert not any(op.endswith("create_model") for op in world.operations("create")), "nothing new was created"


def test_r4_b1_a_kit_error_before_anything_was_sent_is_still_exit_2_control(capsys):
    def refuse():
        raise kitlib.KitError("Refusing to create a billed endpoint without --i-understand-this-bills.")

    code, _, err = guarded_run(capsys, "10_deploy.py", refuse)
    assert code == 2 and lines_of(err) == ["STOP: Refusing to create a billed endpoint without --i-understand-this-bills."]


def test_r4_b1_a_refused_first_call_leaves_no_mark_and_a_lost_answer_does(cfg):
    world = World()
    sent = kitlib.sent_changes()
    sent.clear()
    refused = world_aws(world, fail={"create_model": FakeAwsError("AccessDeniedException", "no", 403)})
    with pytest.raises(FakeAwsError):
        refused.call("sagemaker", "create_model", ModelName="m")
    assert sent == [], "AWS refused the one request that was sent: nothing was created"
    lost = world_aws(world, fail={"create_model": TimeoutError("read timed out")})
    with pytest.raises(TimeoutError):
        lost.call("sagemaker", "create_model", ModelName="m")
    assert sent == ["CreateModel (no clear answer)"]
    world_aws(world).call("sagemaker", "create_endpoint_config", EndpointConfigName="c")
    world_aws(world).call("sagemaker", "list_models")
    assert sent == ["CreateModel (no clear answer)", "CreateEndpointConfig"], "a read is not a change"
    signed_out = world_aws(world, fail={"delete_model": sso_expired()})
    with pytest.raises(UnauthorizedSSOTokenError):
        signed_out.call("sagemaker", "delete_model", ModelName="m")
    # Changed in round 5 (F1): this line pinned "a sign-in error is raised before the request leaves this
    # machine". botocore signs every retry again, so it can also come after a try went out.
    assert sent[2:] == ["DeleteModel (no clear answer)"], "a sign-in error may come from signing a retry"
    sent.clear()


# ======================================================================================================
# MAJOR 1 (emulator 1): a lost CreateEndpoint answer, retried by the SDK, erased the record of the endpoint
# ======================================================================================================

ALREADY = FakeAwsError("ValidationException", f'Cannot create already existing endpoint "arn:aws:sagemaker:{REGION}:{ACCOUNT}:endpoint/x".', 400)


def test_r4_m1_already_exists_keeps_the_endpoint_and_the_deploy_record(cfg, state_path):
    """Reviewed code: state "deploy": null and no endpoint in resources, while the endpoint runs. The load
    test and 50_invoke then ran with no BILLING lines and no teardown deadline."""
    world = World()
    aws = world_aws(world, fail={"create_endpoint_after": ALREADY})  # AWS made the endpoint, then said "exists"
    with pytest.raises(kitlib.KitError, match="EXISTS") as stop:
        deploy(state_path, cfg, aws)
    message = str(stop.value)
    assert "IT IS BILLING BY THE HOUR" in message and "python 90_teardown.py" in message
    assert ACCOUNT not in message, "the ARN in AWS's text is cut to the last four digits"
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"]
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model", "endpoint_config", "endpoint"]
    assert state["deploy"]["create_answer"] == "already exists" and state["deploy"]["endpoint_create_confirmed"] is False
    banner = "\n".join(kitlib.billing_lines(state, kitlib.utc_now()))
    assert "BILLING:" in banner and "already exists" in banner and "You said you would tear down by" in banner


def test_r4_m1_later_scripts_show_billing_and_teardown_prints_the_hours_with_their_limit(cfg, state_path, tmp_path):
    world = World()
    with pytest.raises(kitlib.KitError):
        deploy(state_path, cfg, world_aws(world, fail={"create_endpoint_after": ALREADY}))
    out = Lines()
    runtime = FakeRuntimeAws(stream_factory=token_stream(3))
    args = loadtest_args(state_path, tmp_path / "results", concurrency="1", requests_per_level=2)
    assert load_script("60_loadtest").run(args, cfg, runtime, out) == 0
    assert "BILLING:" in out.text, "the reviewed code printed no BILLING lines here: the deploy record was gone"
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0 and not world.place(ACCOUNT, REGION)["endpoints"]
    this_run = next(line for line in out if line.startswith("This run:"))
    assert "already exists" in this_run and "real hours and charge are higher" in this_run
    assert "Hours and dollars for the endpoint just deleted: unknown" not in out.text


def test_r4_m1_a_refusal_in_other_words_does_not_remove_a_listed_endpoint(cfg, state_path):
    """The wording of "already exists" is not on an AWS page. So the record is not taken out on wording:
    ListEndpoints is asked, and an endpoint that is listed stays on record."""
    odd = FakeAwsError("ValidationException", "Endpoint name is taken.", 400)
    world = World()
    with pytest.raises(kitlib.KitError, match="EXISTS"):
        deploy(state_path, cfg, world_aws(world, fail={"create_endpoint_after": odd}))
    assert f"{REGION}:list_endpoints" in world.operations("list_endpoints")
    state = kitlib.load_state(state_path)
    assert kitlib.state_resources(state, "endpoint") and state["deploy"] is not None


def test_r4_m1_a_refusal_with_the_listing_denied_keeps_the_record_as_unconfirmed(cfg, state_path):
    world = World()
    fail = {"create_endpoint": FakeAwsError("ResourceLimitExceeded", "limit is 0", 400),
            "list_endpoints": FakeAwsError("AccessDeniedException", "no", 403)}
    with pytest.raises(kitlib.KitError, match="MAY exist and MAY be billing"):
        deploy(state_path, cfg, world_aws(world, fail=fail))
    state = kitlib.load_state(state_path)
    assert kitlib.state_resources(state, "endpoint") and state["deploy"]["endpoint_create_confirmed"] is False


def test_r4_m1_a_refusal_that_came_back_after_a_retry_is_not_a_clear_no(cfg, state_path):
    retried = FakeAwsError("ThrottlingException", "Rate exceeded", 400)
    retried.response["ResponseMetadata"]["RetryAttempts"] = 2
    assert kitlib.retry_attempts(retried) == 2 and not kitlib.definitely_rejected(retried)
    assert kitlib.definitely_rejected(FakeAwsError("ThrottlingException", "Rate exceeded", 400))
    assert kitlib.says_already_exists(ALREADY) and not kitlib.says_already_exists(retried)
    assert not kitlib.says_already_exists(TimeoutError("already exists"))
    world = World()
    with pytest.raises(kitlib.KitError, match="sent the request 3 times") as stop:
        deploy(state_path, cfg, world_aws(world, fail={"create_endpoint": retried}))
    assert "MAY exist and MAY be billing" in str(stop.value)
    state = kitlib.load_state(state_path)
    assert kitlib.state_resources(state, "endpoint") and state["deploy"] is not None


def test_r4_m1_already_exists_on_the_model_keeps_its_record(cfg, state_path):
    world = World()
    taken = FakeAwsError("ValidationException", "Cannot create already existing model.", 400)
    with pytest.raises(kitlib.KitError, match="MAY exist"):
        deploy(state_path, cfg, world_aws(world, fail={"create_model": taken}))
    assert [r["type"] for r in kitlib.load_state(state_path)["resources"]] == ["model"]


def test_r4_m1_a_plain_refusal_with_nothing_listed_still_removes_the_record_control(cfg, state_path):
    world = World()
    with pytest.raises(FakeAwsError):
        deploy(state_path, cfg, world_aws(world, fail={"create_endpoint": FakeAwsError("ResourceLimitExceeded", "limit is 0", 400)}))
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model", "endpoint_config"] and state["deploy"] is None


def test_r4_m1_readme_step_names_the_message_the_owner_will_see():
    step = README.split("2. **Deploy. Billing starts here.**")[1].split("3. **Call it three ways.**")[0]
    assert "EXISTS" in step and "already exists" in step and "python 90_teardown.py" in step


# ======================================================================================================
# MAJOR 2: Ctrl-C in the load test did not stop the load and threw every measurement away
# ======================================================================================================

@pytest.fixture
def ctrl_c_arrives():
    """Found by the run on the Mac, 7 Oct 2026. A process started in the background with `&` from a script (a
    shell that is not interactive) is started with the interrupt signal ignored; `nohup` alone does not do that
    (round 5, F7: it ignores only the hang-up signal). Python then installs no handler for it and
    `_thread.interrupt_main()` does nothing. Both tests below failed that way with the kit unchanged (the load
    ran to its end and exited 0). They are about what the kit does WHEN Ctrl-C arrives, so they make it arrive."""
    before = signal.getsignal(signal.SIGINT)
    if before is signal.default_int_handler:
        yield
        return
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        yield
    finally:
        if before is not None:
            signal.signal(signal.SIGINT, before)


def interruptible_runtime(after, calls):
    """A runtime fake that raises KeyboardInterrupt in the main thread (what Ctrl-C does) once `after` streamed
    requests have been sent. Every request takes a moment, so some are still on their way at that point."""
    aws = FakeRuntimeAws()
    gate = threading.Lock()

    def stream():
        with gate:
            calls.append(1)
            if len(calls) == after:
                _thread.interrupt_main()
        events = token_stream(3)()
        threading.Event().wait(0.15)
        return events

    aws.stream_factory = stream
    return aws


def test_r4_m2_ctrl_c_stops_the_load_writes_what_was_measured_and_exits_130(cfg, state_path, tmp_path, ctrl_c_arrives):
    """Reviewed code: every remaining request was still sent (48 more in the reader's run), the exit came after
    all of them, and no CSV file was written."""
    module = load_script("60_loadtest")
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now(), hours=3.0), state_path)
    calls, out = [], Lines()
    # 1 warm-up; level 2: 2 warm-ups and 12 recorded; level 4: 4 warm-ups, then Ctrl-C at its 2nd recorded request,
    # while the first four are on their way (each request takes 0.15 s)
    before_level_4 = 1 + 2 + 12 + 4
    aws = interruptible_runtime(after=before_level_4 + 2, calls=calls)
    results_dir = tmp_path / "results"
    args = loadtest_args(state_path, results_dir, concurrency="2,4", requests_per_level=12)
    try:
        code = module.run(args, cfg, aws, out)
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C went straight through the load test: nothing measured was written")
    assert code == 130
    sent_in_level_4 = len(calls) - before_level_4
    assert 2 <= sent_in_level_4 <= 4, f"only the requests already on their way: sent {sent_in_level_4} of 12 after Ctrl-C"
    files = sorted(p.name for p in results_dir.iterdir())
    assert len(files) == 2 and all("_INTERRUPTED_" in name for name in files)
    with (results_dir / files[0]).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["concurrency"] for row in rows].count("2") == 12, "the level that finished is complete"
    cut = [row for row in rows if row["concurrency"] == "4"]
    assert len(cut) == sent_in_level_4 and all(row["ok"] == "True" for row in cut), "what was on its way was waited for"
    with (results_dir / files[1]).open(encoding="utf-8") as handle:
        summary = list(csv.DictReader(handle))
    assert [row["concurrency"] for row in summary] == ["2"], "a cut level has no row in the summary file"
    assert "BILLING:" in out.text
    last = last_line(out)
    assert last.startswith("INTERRUPTED by Ctrl-C in level 4") and "still billing" in last and "python 90_teardown.py" in last
    assert "1 of 2 level(s) finished" in last


def test_r4_m2_a_request_that_never_returns_does_not_keep_the_script_alive(monkeypatch, ctrl_c_arrives):
    module = load_script("60_loadtest")
    monkeypatch.setattr(module, "INTERRUPT_GRACE_S", 0.3, raising=False)
    never = threading.Event()
    sent = []

    def send(index):
        sent.append(index)
        if len(sent) == 2:
            _thread.interrupt_main()
        never.wait(30)  # stands in for a request that hangs until the read timeout
        return None

    release = threading.Timer(3.0, never.set)  # so that this test ends on code that waits for every request
    release.start()
    try:
        with pytest.raises(getattr(module, "LevelInterrupted", RuntimeError)) as stop:
            module.run_level(send, concurrency=2, requests=50)
    except KeyboardInterrupt:
        pytest.fail(f"Ctrl-C went straight through run_level, and it had sent {len(sent)} of 50 requests by then")
    finally:
        release.cancel()
        never.set()
    assert stop.value.results == [] and stop.value.sent == 2 and stop.value.abandoned == 2


def test_r4_m2_run_level_without_an_interrupt_is_unchanged_control():
    module = load_script("60_loadtest")
    result = streamstats.RequestResult(ok=True, error="", ttft_s=0.1, total_s=1.0, output_tokens=10, tokens_source="usage",
                                       prompt_tokens=1, request_tokens_per_s=10.0, decode_tokens_per_s=11.0,
                                       text_chunks=10, finish_reason="length", saw_done=True)
    results, wall = module.run_level(lambda index: result, concurrency=3, requests=7)
    assert len(results) == 7 and wall >= 0


# ======================================================================================================
# MAJOR 3: the full account id and the caller's ARN were printed from raw AWS error text
# ======================================================================================================

def test_r4_m3_redact_cuts_account_ids_and_hides_the_caller_name():
    text = kitlib.redact(DENIED)
    assert ACCOUNT not in text and "somebody" not in text
    assert "[account ending 3333]" in text and ":user/[name hidden]" in text
    session = kitlib.redact(f"arn:aws:sts::{ACCOUNT}:assumed-role/AWSReservedSSO_Admin_0123/first.last@example.org did it")
    assert "first.last" not in session and "assumed-role/AWSReservedSSO_Admin_0123/[name hidden] did it" in session
    role = f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kita-sagemaker-execution"
    assert kitlib.redact(role).endswith(":role/kitdemo-kita-sagemaker-execution"), "the role is the kit's, not a person"
    image = "763104351884.dkr.ecr.us-east-1.amazonaws.com/vllm:tag"
    assert kitlib.redact(image) == image, "AWS's public registry account is part of the image address"
    assert kitlib.redact("1234567890123") == "1234567890123", "13 digits is not an account id"
    assert kitlib.error_message(FakeAwsError("AccessDeniedException", DENIED, 403)) == text


@pytest.mark.parametrize("script", ["90_teardown.py", "99_verify_clean.py", "10_deploy.py"])
def test_r4_m3_an_aws_error_reaches_the_screen_without_the_account_id(script, capsys):
    def denied():
        print(f"listing for {CALLER}")
        raise FakeAwsError("AccessDeniedException", DENIED, 403)

    code, out, err = guarded_run(capsys, script, denied)
    assert code == 1 and "STOP: AWS returned AccessDeniedException" in err
    assert ACCOUNT not in out + err and "somebody" not in out + err
    assert "account ending 3333" in err


def test_r4_m3_a_traceback_reaches_the_screen_without_the_account_id(capsys):
    def crash():
        raise RuntimeError(f"unexpected answer for {CALLER}")

    code, out, err = guarded_run(capsys, "55_observe.py", crash)
    assert code == 1 and "Traceback" in err and "STOP: unexpected RuntimeError" in err
    assert ACCOUNT not in err and "somebody" not in err


def test_r4_m3_guarded_filters_what_main_prints_and_puts_the_real_streams_back(capsys):
    before = (sys.stdout, sys.stderr)
    seen = []

    def main():
        seen.append(sys.stdout is before[0])
        print(f"role of account {ACCOUNT}")
        return 0

    code, out, _ = guarded_run(capsys, "00_check.py", main)
    assert code == 0 and seen == [False], "while main() runs, stdout is the filtering stream"
    assert out == "role of account [account ending 3333]\n"
    assert (sys.stdout, sys.stderr) == before


def test_r4_m3_load_test_keeps_the_account_id_out_of_the_csv_and_off_the_screen(cfg, state_path, tmp_path):
    from botocore.exceptions import ClientError

    module = load_script("60_loadtest")
    aws = FakeRuntimeAws(stream_factory=token_stream(3))
    plain_call, count = aws.call, {"n": 0}

    def call(service, operation, **params):
        if service == "sagemaker-runtime":
            count["n"] += 1
            if count["n"] > 2:  # the two warm-ups pass, every recorded request is denied
                raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": DENIED}}, "InvokeEndpointWithResponseStream")
        return plain_call(service, operation, **params)

    aws.call = call
    out, results_dir = Lines(), tmp_path / "results"
    assert module.run(loadtest_args(state_path, results_dir, concurrency="1", requests_per_level=3), cfg, aws, out) == 1
    text = "".join(path.read_text(encoding="utf-8") for path in results_dir.iterdir())
    assert "AccessDeniedException" in text and ACCOUNT not in text and "somebody" not in text
    assert ACCOUNT not in out.text


def test_r4_m3_state_file_copies_are_git_ignored_and_the_readme_moves_a_damaged_one_out_of_the_tree():
    ignored = (KIT_DIR / ".gitignore").read_text(encoding="utf-8").split()
    assert ".state.json" in ignored and ".state.json*" in ignored, "a hand copy such as .state.json.bak holds the account id too"
    section5 = README.split("## 5. Tear it down and prove it")[1].split("## 6. What to record")[0]
    assert "../kit_a_state_damaged.json" not in README, "the folder above this one is covered by no .gitignore"
    assert re.search(r"mv \.state\.json ~/", section5) and "account id" in section5.split("mv .state.json ~/")[1][:400]


# ======================================================================================================
# MINOR 3: teardown called the shell's Region "the place .state.json records" when the file recorded another
# ======================================================================================================

def test_r4_n3_teardown_does_not_call_the_shell_region_the_recorded_place(state_path):
    cfg = kitlib.load_config(environ={}, env_file=KIT_DIR / "does-not-exist.env")
    world = World()
    deploy_with_logs(world, cfg, state_path)
    assert teardown(state_path, cfg, world_aws(world))[0] == 0  # a finished run in us-east-1 is now on record
    west = kitlib.load_config(environ={"AWS_REGION": OTHER_REGION}, env_file=KIT_DIR / "does-not-exist.env")
    code, out = teardown(state_path, west, world_aws(world, region=OTHER_REGION))
    last = last_line(out)
    assert code == 0 and f"in Region {OTHER_REGION}" in last
    assert "the place .state.json records" not in last
    assert "RECORDED NO LIVE DEPLOY" in last and f"history names {REGION}, which was NOT looked at" in last
    assert "NOT proof for any other Region or account" in last


def test_r4_n3_teardown_of_a_live_record_still_says_the_recorded_place_control(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0 and "(the place .state.json records)" in last_line(out)


# ======================================================================================================
# MINOR 4: the clean check said CLEAN for a live record that names no Region
# ======================================================================================================

def test_r4_n4_a_live_record_without_a_region_is_incomplete_not_clean(cfg, state_path):
    world = World()
    state = deploy_into(world, cfg, state_path)
    state.pop("region")
    state["deploy"].pop("region", None)
    for resource in state["resources"]:
        resource["arn"] = None
    state_path.write_text(json.dumps(state), encoding="utf-8")
    west = kitlib.load_config(environ={"AWS_REGION": OTHER_REGION}, env_file=KIT_DIR / "does-not-exist.env")
    code, out = verify(state_path, west, world_aws(world, region=OTHER_REGION))
    line = result_line(out)
    assert code == 1 and line.startswith("RESULT: INCOMPLETE"), line
    assert "records a live deploy but no Region" in out.text and "The file is stale" not in out.text
    assert "Region None" not in out.text
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"], "the endpoint is alive in the Region the file lost"


# ======================================================================================================
# MINOR 10: a denied or throttled List call stopped teardown before the delete that stops the bill
# ======================================================================================================

@pytest.mark.parametrize("failing", ["list_endpoints", "list_tags", "describe_log_groups"])
def test_r4_n10_a_failed_listing_does_not_keep_the_endpoint_alive(cfg, state_path, capsys, failing):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    stranger = "somebody-elses-endpoint"  # so that the listing has something to ask ListTags about
    world.place(ACCOUNT, REGION)["endpoints"][stranger] = {"status": "InService"}
    aws = world_aws(world, fail={failing: FakeAwsError("AccessDeniedException", DENIED, 403)})
    lines = Lines()
    clock = FakeClock()
    run = lambda: load_script("90_teardown").run(ns(state_path), cfg, aws, lines, sleep=clock.sleep, clock=clock)  # noqa: E731
    code, _, err = guarded_run(capsys, "90_teardown.py", run)
    here = world.place(ACCOUNT, REGION)
    assert cfg.endpoint_name not in here["endpoints"], "the endpoint on record is deleted although the listing failed"
    assert stranger in here["endpoints"] and here["models"], "nothing else is touched"
    assert code == 1 and "STOP: AWS returned AccessDeniedException" in err
    assert "its hourly charge has stopped" in lines.text and "NOTHING ELSE WAS DELETED OR CHECKED" in lines.text
    assert "THIS RUN HAD SENT TO AWS: DeleteEndpoint" in lines_of(err)[-1]
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint"), "the state file is not changed on this path"
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0 and "AT MOST" in out.text, "the next full teardown closes the run with the hours as an upper bound"


# ======================================================================================================
# MINOR 11: a failed warm-up ended the load test with no BILLING lines
# ======================================================================================================

def test_r4_n11_a_failed_warm_up_still_prints_the_billing_lines(cfg, state_path, tmp_path):
    from botocore.exceptions import ClientError

    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now(), hours=3.0), state_path)
    aws = FakeRuntimeAws(fail_with=ClientError({"Error": {"Code": "ValidationError", "Message": "Endpoint is not InService"}}, "Op"))
    out = Lines()
    with pytest.raises(kitlib.KitError, match="warm-up request failed") as stop:
        load_script("60_loadtest").run(loadtest_args(state_path, tmp_path / "results"), cfg, aws, out)
    assert "BILLING:" in out.text and "To stop the charge: python 90_teardown.py" in out.text
    assert "is billing" in str(stop.value) and "created and deleted nothing" in str(stop.value)


# ======================================================================================================
# MINOR 12: after a setting change the BILLING line counted only the new endpoint
# ======================================================================================================

def change(state_path, cfg, world, setting):
    out, clock = Lines(), FakeClock()
    args = ns(state_path, set=setting, i_understand_this_bills=True, ignore_deadline=True)
    code = load_script("70_change_one_setting").run(args, cfg, world_aws(world), out, sleep=clock.sleep, clock=clock)
    return code, out


def test_r4_n12_billing_lines_say_what_the_replaced_endpoint_cost(cfg, state_path):
    """Reviewed code, two hours in: "has existed for 0.00 h ... about $0.00 so far" and nothing else."""
    world = World()
    state = deploy_into(world, cfg, state_path)
    state["deploy"]["create_called_utc"] = kitlib.iso(kitlib.utc_now() - dt.timedelta(hours=2))
    state_path.write_text(json.dumps(state), encoding="utf-8")
    code, out = change(state_path, cfg, world, "SM_VLLM_MAX_NUM_SEQS=16")
    assert code == 0
    banner = [line for line in out if "BILLING:" in line or "Not in that figure" in line]
    assert len(banner) == 2 and "has existed for 0.00 h" in banner[0]
    assert "the 1 endpoint(s) this one replaced" in banner[1] and "2.00 h, about $2.44" in banner[1]
    assert kitlib.load_state(state_path)["deploy"]["replaced_in_this_sitting"]["runs"] == 1
    code, out = change(state_path, cfg, world, "SM_VLLM_MAX_NUM_SEQS=8")
    carried = kitlib.load_state(state_path)["deploy"]["replaced_in_this_sitting"]
    assert code == 0 and carried["runs"] == 2 and carried["hours"] == pytest.approx(2.0, abs=0.01)
    assert any("the 2 endpoint(s) this one replaced" in line for line in out)


def test_r4_n12_a_first_deploy_has_no_such_line_control(cfg, state_path):
    state = deployed_state(cfg, created=kitlib.utc_now() - dt.timedelta(hours=1), hours=3.0)
    assert not any("Not in that figure" in line for line in kitlib.billing_lines(state, kitlib.utc_now()))


# ======================================================================================================
# MINOR 13: with the machine clock set back the BILLING line said 0.00 h and $0.00
# ======================================================================================================

def test_r4_n13_a_clock_set_back_is_said_not_shown_as_zero(cfg):
    now = kitlib.utc_now()
    state = deployed_state(cfg, created=now + dt.timedelta(hours=1), hours=3.0)
    banner = "\n".join(kitlib.billing_lines(state, now))
    assert "0.00 h" not in banner and "$0.00" not in banner
    assert "HOURS AND DOLLARS SO FAR ARE UNKNOWN" in banner and "is billing at $1.2220/h" in banner
    kitlib.close_run(state, now)
    run = state["history"][-1]
    assert run["clock_went_back"] is True and "UNKNOWN time" in kitlib.run_line(run) and "0.00 h" not in kitlib.run_line(run)


def test_r4_n13_a_normal_clock_is_unchanged_control(cfg):
    now = kitlib.utc_now()
    state = deployed_state(cfg, created=now - dt.timedelta(hours=1, minutes=30), hours=3.0)
    assert "has existed for 1.50 h at $1.2220/h, about $1.83 so far" in "\n".join(kitlib.billing_lines(state, now))
    kitlib.close_run(state, now)
    assert "clock_went_back" not in state["history"][-1]


# ======================================================================================================
# Emulator 5: two messages that said the wrong thing
# ======================================================================================================

def test_r4_e5_the_clean_check_is_not_told_to_run_itself_and_the_preflight_is_not_told_about_billing(capsys):
    def denied():
        raise FakeAwsError("AccessDeniedException", "not authorized to perform: sagemaker:ListEndpoints", 403)

    code, _, err = guarded_run(capsys, "99_verify_clean.py", denied)
    assert code == 1 and "If an endpoint was created" not in err and "Run: python 99_verify_clean.py" not in err
    assert "NOT a clean result" in lines_of(err)[-1]
    code, _, err = guarded_run(capsys, "00_check.py", denied)
    assert code == 1 and "creates, changes and deletes nothing" in lines_of(err)[-1] and "billing" not in err


def test_r4_e5_teardown_does_not_say_the_state_file_is_missing_when_it_is_there(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    state = kitlib.load_state(state_path)
    state["deploy"] = None  # what the reviewed code left behind after "already exists"
    state["resources"] = [r for r in state["resources"] if r["type"] != "endpoint"]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    code, out = teardown(state_path, cfg, world_aws(world))
    line = next(line for line in out if line.startswith("Hours and dollars for the endpoint just deleted: unknown"))
    assert code == 0 and "holds no deploy record for it" in line and "does not exist" not in line


# ======================================================================================================
# The record of this round
# ======================================================================================================

def test_r4_readme_states_the_exit_code_rule_and_points_to_the_notes():
    section5 = README.split("## 5. Tear it down and prove it")[1].split("## 6. What to record")[0]
    assert "2 it stopped before deleting anything" in section5 and "stopped after it had sent a delete call" in section5
    section8 = README.split("## 8. What was and was not tested")[1].split("## 9. Sources")[0]
    assert re.search(r"Reviewed independently on 2026-10-07 \(round 4\): \d+ findings for this kit, \d+ fixed, "
                     r"\d+ stated as a limit, \d+ not changed \(`REVIEW_NOTES_r4\.md`\)", section8)
    notes = (KIT_DIR / "REVIEW_NOTES_r4.md").read_text(encoding="utf-8")
    for finding in ("BLOCKER 1", "MAJOR 1", "MAJOR 2", "MAJOR 3", "MINOR 3", "MINOR 4", "MINOR 10", "MINOR 11",
                    "MINOR 12", "MINOR 13", "MINOR 14", "Emulator 1", "Emulator 5"):
        assert finding in notes, finding
    assert "already exist" in section8.split("**UNVERIFIED:")[1], "the unverified wording is owned up to"
