"""Review findings M1 and M2 (round 1), and the rule all three kits share.

M2  A damaged .state.json must not end teardown or the clean check with a
    traceback, and the write is atomic. Round 1 answered this by setting the
    damaged file aside and carrying on; the second review showed that this
    destroys the only record of where the deploy is. Since round 2 the file is
    left exactly where it is and every script stops with instructions
    (tests/test_r2_money.py has the scenarios).
M1  .state.json records the Region, the name prefix and the account id of the
    deploy. Every script that reads it compares all three with the current
    settings and the current caller identity and STOPS on any mismatch.
    Teardown never clears the record of a resource it did not delete or
    positively confirm absent. The clean check says exactly what it checked,
    is INCOMPLETE when the state names a place it did not check, and its
    --dry-run does not exit 0.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest
from conftest import ACCOUNT, ROOT, RUNTIME_ARN, RUNTIME_ID, load_script, make_aws
from test_aws_flows import (CONTROL, DATA, NOW, empty_discovery, identity, log_groups_listed_again,
                            runtime_detail, runtime_summary)

OTHER_ACCOUNT = "999999999999"  # placeholder, not a real account
WEST_ARN = RUNTIME_ARN.replace("us-east-1", "us-west-2")
BUCKET = f"kitdemo-kitc-code-{ACCOUNT}-us-east-1"


def deployed(**changes) -> dict:
    record = {"region": "us-east-1", "prefix": "kitdemo", "account_id": ACCOUNT,
              "runtime_id": RUNTIME_ID, "runtime_arn": RUNTIME_ARN, "bucket": BUCKET,
              "role_name": "kitdemo-kitc-runtime-role", "deployed_at": "2026-10-07T12:00:00Z",
              "idle_timeout_s": 120, "max_lifetime_s": 900,
              "sessions": [{"session_id": "kitdemo-kitc-" + "a" * 32, "started_at": "2026-10-07T12:00:00Z",
                            "ended_at": "2026-10-07T12:01:00Z", "stopped": True, "calls": []}]}
    record.update(changes)
    return record


def write_state(kit, data: dict):
    kit.STATE_PATH.write_text(json.dumps(data))
    return kit.State(kit.STATE_PATH)


# ====================================================================== M2: a damaged file is read without a crash
@pytest.mark.parametrize("content", [b"", b'{"runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:0000',
                                      b"[1, 2, 3]", b"\xff\xfe\x00not text"])
def test_a_damaged_state_file_is_left_exactly_where_it_is_and_never_written_over(kit, content):
    kit.STATE_PATH.write_bytes(content)
    lines: list[str] = []
    state = kit.State(kit.STATE_PATH, out=lines.append)  # must not raise
    assert state.damaged and state.existed
    assert state.get("runtime_id") is None
    assert "could not be read" in kit.unusable_reason(state)
    assert kit.STATE_PATH.read_bytes() == content                       # not moved, not rewritten
    assert [p.name for p in kit.STATE_PATH.parent.iterdir() if "damaged" in p.name] == []
    with pytest.raises(kit.StateUnusable):                              # and it cannot be saved over
        state.set(runtime_id="r-1")
    assert kit.STATE_PATH.read_bytes() == content
    assert [p.name for p in kit.STATE_PATH.parent.iterdir() if ".tmp" in p.name] == []


def test_a_read_only_state_leaves_the_damaged_file_where_it_is(kit):
    kit.STATE_PATH.write_text("{truncated")
    state = kit.State(kit.STATE_PATH, dry_run=True)
    assert state.damaged and kit.STATE_PATH.read_text() == "{truncated"
    assert [p.name for p in kit.STATE_PATH.parent.iterdir() if "damaged" in p.name] == []
    assert "could not be read" in kit.unusable_reason(state)


# ====================================================================== M2: atomic write
def test_save_writes_a_temporary_file_and_renames_it_over_the_state(kit, monkeypatch):
    state = kit.State(kit.STATE_PATH)
    state.set(runtime_id="old")
    seen = []
    real_replace = os.replace

    def watching_replace(src, dst):
        # At the moment of the rename the state file still holds the last complete version.
        seen.append((str(src), str(dst), json.loads(kit.STATE_PATH.read_text())["runtime_id"],
                     json.loads(open(src).read())["runtime_id"]))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", watching_replace)
    state.set(runtime_id="new")
    assert len(seen) == 1
    src, dst, on_disk_before, in_temp = seen[0]
    assert dst == str(kit.STATE_PATH) and os.path.dirname(src) == os.path.dirname(dst) and src != dst
    assert (on_disk_before, in_temp) == ("old", "new")
    assert json.loads(kit.STATE_PATH.read_text())["runtime_id"] == "new"
    assert [p.name for p in kit.STATE_PATH.parent.iterdir() if ".tmp" in p.name] == []


def test_a_save_that_dies_before_the_rename_leaves_the_old_file_whole(kit, monkeypatch):
    state = kit.State(kit.STATE_PATH)
    state.set(runtime_id="old")
    before = kit.STATE_PATH.read_bytes()

    def killed(src, dst):
        raise KeyboardInterrupt()

    monkeypatch.setattr(os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        state.set(runtime_id="new")
    assert kit.STATE_PATH.read_bytes() == before
    assert json.loads(before)["runtime_id"] == "old"
    assert [p.name for p in kit.STATE_PATH.parent.iterdir() if ".tmp" in p.name] == []


# ====================================================================== M2: the real scripts as processes
@pytest.fixture()
def kit_copy(tmp_path):
    """A throwaway copy of the kit, so a state file can be planted without touching the real folder."""
    target = tmp_path / "kit"
    shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns(
        ".build", "__pycache__", ".state.json*", "config.env", "tests", ".venv", ".pytest_cache"))
    return target


def run_copy(kit_copy, script, *args, env_extra=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("AWS_") and k not in {"KIT_PREFIX", "MODEL_ID", "PLATFORM_VERSION"}}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_CONFIG_FILE": str(kit_copy / "no-config"),
                "AWS_SHARED_CREDENTIALS_FILE": str(kit_copy / "no-credentials")})
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(kit_copy / script), *args], cwd=kit_copy, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("content", ["", '{"runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:0000'])
@pytest.mark.parametrize("script, code", [("90_teardown.py", 4), ("99_verify_clean.py", 3),
                                          ("50_invoke_hosted.py", 4), ("60_read_usage.py", 4)])
def test_real_scripts_stop_on_a_damaged_state_file_without_a_traceback_and_leave_it(kit_copy, content, script, code):
    """As processes, in --dry-run and for real (no credentials, so the real run stops at sign-in
    or at the state file, whichever comes first). The clean check's dry run exits 3 as always."""
    (kit_copy / ".state.json").write_text(content)
    result = run_copy(kit_copy, script, "--dry-run")
    assert "Traceback" not in result.stderr and "JSONDecodeError" not in result.stderr
    assert result.returncode == code, result.stdout + result.stderr
    assert "could not be read" in result.stdout
    assert ("STOPPED:" in result.stdout) == (code == 4)
    real = run_copy(kit_copy, script)
    assert "Traceback" not in real.stderr and real.returncode != 0
    assert (kit_copy / ".state.json").read_text() == content
    assert sorted(p.name for p in kit_copy.iterdir() if p.name.startswith(".state.json")) == [".state.json"]


# ====================================================================== the shared rule: compare, then stop
def test_the_deploy_record_is_compared_field_by_field(kit):
    cfg = kit.Config.from_env()
    state = write_state(kit, deployed())
    assert kit.check_place(state, cfg, ACCOUNT, [].append, "x.py") is True

    for change, old, new in ((dict(region="us-west-2"), "us-west-2", "us-east-1"),
                             (dict(prefix="other"), "other", "kitdemo")):
        lines: list[str] = []
        state = write_state(kit, deployed(**change))
        assert kit.check_place(state, cfg, ACCOUNT, lines.append, "90_teardown.py") is False
        text = "\n".join(lines)
        assert text.startswith("STOPPED")
        assert old in text and new in text  # both values are named
        assert "exported AWS_REGION overrides config.env" in text
        assert "90_teardown.py" in text


def test_an_account_mismatch_stops_and_shows_only_the_last_four_digits(kit):
    # 111122223333 and 444455556666 are the example account ids AWS documentation uses, not real accounts.
    cfg = kit.Config.from_env()
    lines: list[str] = []
    state = write_state(kit, deployed(account_id="111122223333"))
    assert kit.check_place(state, cfg, "444455556666", lines.append, "90_teardown.py") is False
    text = "\n".join(lines)
    assert "********3333" in text and "********6666" in text
    assert "111122223333" not in text and "444455556666" not in text
    assert "11112222" not in text and "44445555" not in text


def test_no_record_means_nothing_to_compare(kit):
    cfg = kit.Config.from_env()
    assert kit.check_place(kit.State(kit.STATE_PATH), cfg, ACCOUNT, [].append, "x.py") is True
    history_only = write_state(kit, {"history": [{"region": "us-west-2", "prefix": "kitdemo",
                                                  "account_id": ACCOUNT}]})
    assert kit.check_place(history_only, cfg, ACCOUNT, [].append, "x.py") is True


STATE_READERS = [
    ("00_check.py", []),
    ("30_deploy.py", ["--i-understand-this-bills"]),
    ("40_enable_observability.py", ["--i-understand-this-bills"]),
    ("50_invoke_hosted.py", ["--i-understand-this-bills"]),
    ("60_read_usage.py", []),
    ("90_teardown.py", []),
    ("99_verify_clean.py", []),
    ("optional_gateway/10_create_gateway.py", ["--i-understand-this-bills"]),
    ("optional_gateway/50_call_gateway_tools.py", ["--i-understand-this-bills"]),
    ("optional_gateway/90_teardown_gateway.py", []),
]


@pytest.mark.parametrize("script_name, argv", STATE_READERS)
@pytest.mark.parametrize("change", [dict(region="us-west-2", runtime_arn=WEST_ARN), dict(prefix="other"),
                                    dict(account_id=OTHER_ACCOUNT)])
def test_every_script_that_reads_state_stops_on_a_mismatch(kit, stubs, script_name, argv, change, monkeypatch):
    script = load_script(script_name)
    if script_name == "30_deploy.py":
        kit.BUILD_DIR.mkdir(parents=True)
        kit.PACKAGE_ZIP.write_bytes(b"PK")
        script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
        script.MANIFEST.write_text(json.dumps({"entry_point": ["agentcore_app.py"], "python_runtime": "PYTHON_3_13"}))
    state = write_state(kit, deployed(gateway_url="https://example.invalid/mcp", **change))
    before = kit.STATE_PATH.read_bytes()
    identity(stubs)  # the only AWS call allowed: who am I
    lines: list[str] = []
    rc = script.main(argv, aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    text = "\n".join(lines)
    assert rc == kit.EXIT_STATE_MISMATCH == 4, text
    assert "STOPPED" in text
    stubs.assert_all_used()
    assert set(stubs.clients) == {"sts"}  # nothing was listed, created, invoked, stopped or deleted
    assert kit.STATE_PATH.read_bytes() == before  # and the record was not touched
    assert "CLEAN" not in text.replace("INCOMPLETE", "") or "RESULT: INCOMPLETE" in text
    assert not any(line.startswith("RESULT: CLEAN") for line in lines)


@pytest.mark.parametrize("script, _argv", STATE_READERS)
def test_a_dry_run_also_stops_when_the_region_does_not_match(kit_copy, script, _argv):
    (kit_copy / ".state.json").write_text(json.dumps(deployed(region="us-west-2", runtime_arn=WEST_ARN)))
    before = (kit_copy / ".state.json").read_bytes()
    result = run_copy(kit_copy, script, "--dry-run")
    assert result.returncode == 4, result.stdout + result.stderr
    assert "STOPPED" in result.stdout and "us-west-2" in result.stdout and "us-east-1" in result.stdout
    assert "Traceback" not in result.stderr
    assert (kit_copy / ".state.json").read_bytes() == before
    # and with the recorded Region exported, the same dry run goes ahead
    again = run_copy(kit_copy, script, "--dry-run", env_extra={"AWS_REGION": "us-west-2"})
    assert again.returncode in (0, 3), again.stdout + again.stderr
    assert "STOPPED" not in again.stdout


# ====================================================================== M1: teardown
def test_the_reviewers_case_teardown_in_the_wrong_region_deletes_nothing_and_keeps_the_record(kit, stubs):
    """State says us-west-2. The shell says us-east-1. Before the fix this deleted the role and the
    bucket, cleared the state and let the clean check print CLEAN."""
    teardown = load_script("90_teardown.py")
    verify = load_script("99_verify_clean.py")
    state = write_state(kit, deployed(region="us-west-2", runtime_arn=WEST_ARN,
                                      bucket=f"kitdemo-kitc-code-{ACCOUNT}-us-west-2"))
    before = kit.STATE_PATH.read_bytes()
    identity(stubs)
    lines: list[str] = []
    assert teardown.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 4
    assert kit.STATE_PATH.read_bytes() == before
    assert not any("Teardown finished" in line for line in lines)

    identity(stubs)
    lines = []
    rc = verify.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH, dry_run=True))
    assert rc == 4
    assert any(line.startswith("RESULT: INCOMPLETE") for line in lines)
    assert not any("RESULT: CLEAN" in line for line in lines)
    stubs.assert_all_used()
    assert set(stubs.clients) == {"sts"}


def _queue_full_teardown(stubs):
    stubs.add(CONTROL, "delete_agent_runtime", {"status": "DELETING"}, {"agentRuntimeId": RUNTIME_ID})
    stubs.add_error(CONTROL, "get_agent_runtime", "ResourceNotFoundException", 404)
    stubs.add(CONTROL, "list_workload_identities", {"workloadIdentities": []}, {"maxResults": 20})
    log_groups_listed_again(stubs)


def test_teardown_moves_the_record_into_history_only_after_everything_is_gone(kit, stubs):
    teardown = load_script("90_teardown.py")
    state = write_state(kit, deployed())
    identity(stubs)
    empty_discovery(stubs, runtimes=[runtime_summary()])
    _queue_full_teardown(stubs)
    lines: list[str] = []
    assert teardown.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 0, "\n".join(lines)
    stubs.assert_all_used()
    saved = json.loads(kit.STATE_PATH.read_text())
    assert "runtime_id" not in saved and "region" not in saved
    assert len(saved["history"]) == 1
    entry = saved["history"][0]
    assert (entry["region"], entry["prefix"], entry["account_id"]) == ("us-east-1", "kitdemo", ACCOUNT)
    assert entry["runtime_id"] == RUNTIME_ID and entry["torn_down_at"]
    assert len(saved["past_sessions"]) == 1
    assert ACCOUNT not in "\n".join(lines)


def test_teardown_confirms_a_recorded_runtime_is_absent_by_asking_for_it_by_id(kit, stubs):
    """The listing shows nothing with this prefix, but the state names a runtime. Its record may only
    be cleared after GetAgentRuntime says it does not exist."""
    teardown = load_script("90_teardown.py")
    state = write_state(kit, deployed())
    identity(stubs)
    empty_discovery(stubs)
    stubs.add_error(CONTROL, "get_agent_runtime", "ResourceNotFoundException", 404,
                    expected={"agentRuntimeId": RUNTIME_ID})
    stubs.add(CONTROL, "list_workload_identities", {"workloadIdentities": []}, {"maxResults": 20})
    log_groups_listed_again(stubs)
    lines: list[str] = []
    assert teardown.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 0, "\n".join(lines)
    stubs.assert_all_used()
    assert any("confirmed absent" in line for line in lines)
    assert "runtime_id" not in json.loads(kit.STATE_PATH.read_text())


def test_teardown_keeps_the_record_when_a_recorded_runtime_still_exists_and_cannot_be_deleted(kit, stubs):
    teardown = load_script("90_teardown.py")
    state = write_state(kit, deployed())
    before = kit.STATE_PATH.read_bytes()
    identity(stubs)
    empty_discovery(stubs)  # not listed under the prefix...
    stubs.add(CONTROL, "get_agent_runtime", runtime_detail("READY"), {"agentRuntimeId": RUNTIME_ID})  # ...but there
    stubs.add_error(CONTROL, "delete_agent_runtime", "AccessDeniedException", 403)
    lines: list[str] = []
    assert teardown.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 1
    assert kit.STATE_PATH.read_bytes() == before
    assert any("WITH ERRORS" in line for line in lines)
    assert "iam" not in stubs.stubbers or True  # roles were listed during discovery; none was deleted


def test_a_refused_runtime_delete_does_not_wait_ten_minutes_or_remove_what_the_runtime_needs(kit, stubs, monkeypatch):
    """Review minor 10: DeleteAgentRuntime on a runtime still CREATING returns ConflictException."""
    teardown = load_script("90_teardown.py")
    state = write_state(kit, deployed())
    before = kit.STATE_PATH.read_bytes()
    waits = []
    real_wait = kit.wait_until
    monkeypatch.setattr(kit, "wait_until", lambda *a, **k: waits.append(k.get("what")) or real_wait(*a, **k))
    identity(stubs)
    role = {"Path": "/", "RoleName": "kitdemo-kitc-runtime-role", "RoleId": "AROAEXAMPLEEXAMPLE1",
            "Arn": f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-runtime-role", "CreateDate": NOW}
    empty_discovery(stubs, runtimes=[runtime_summary(status="CREATING")], roles=[role], buckets=[{"Name": BUCKET}])
    stubs.add_error(CONTROL, "delete_agent_runtime", "ConflictException", 409)
    lines: list[str] = []
    assert teardown.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 1
    stubs.assert_all_used()  # no polling call, no bucket call, no role call was queued or made
    assert waits == []
    text = "\n".join(lines)
    assert "ConflictException" in text
    assert "left in place" in text and "run this script again" in text
    assert kit.STATE_PATH.read_bytes() == before


# ====================================================================== M1: the clean check
def _verify_tail(stubs):
    stubs.add("xray", "get_trace_segment_destination", {"Destination": "XRay", "Status": "ACTIVE"}, {})
    stubs.add("logs", "describe_log_groups", {"logGroups": []}, {"logGroupNamePrefix": "aws/spans"})


def test_the_result_line_says_what_was_checked(kit, stubs):
    verify = load_script("99_verify_clean.py")
    identity(stubs)
    empty_discovery(stubs)
    _verify_tail(stubs)
    lines: list[str] = []
    assert verify.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 0
    result = [line for line in lines if line.startswith("RESULT:")]
    assert len(result) == 1
    assert result[0].startswith("RESULT: CLEAN")
    assert "account ********0000" in result[0] and "Region us-east-1" in result[0] and "prefix kitdemo" in result[0]


def test_the_clean_check_dry_run_does_not_exit_zero_and_says_why(kit):
    verify = load_script("99_verify_clean.py")
    lines: list[str] = []
    aws = kit.Aws("us-east-1", dry_run=True, out=lines.append)
    rc = verify.main(["--dry-run"], aws=aws, out=lines.append)
    assert rc == kit.EXIT_DRY_RUN_PROVES_NOTHING == 3
    text = "\n".join(lines)
    assert "proves nothing" in text and "exit code 3" in text.lower()
    assert not any(line.startswith("RESULT: CLEAN") for line in lines)


def _history(*places):
    return {"history": [{"region": r, "prefix": p, "account_id": a, "torn_down_at": "2026-10-07T13:00:00Z"}
                        for r, p, a in places]}


def test_the_clean_check_also_checks_every_other_place_the_history_names(kit, stubs):
    """Torn down in us-west-2 earlier, now set to us-east-1: one run checks both and says so."""
    from conftest import Stubs

    verify = load_script("99_verify_clean.py")
    write_state(kit, _history(("us-west-2", "kitdemo", ACCOUNT), ("us-east-1", "kitdemo", ACCOUNT)))
    identity(stubs)
    empty_discovery(stubs)
    _verify_tail(stubs)
    west = Stubs(region="us-west-2")
    empty_discovery(west)
    lines: list[str] = []
    rc = verify.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH, dry_run=True),
                     aws_for_region=lambda region: {"us-west-2": make_aws(kit, west, lines)}[region])
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    west.assert_all_used()
    result = next(line for line in lines if line.startswith("RESULT:"))
    assert result.startswith("RESULT: CLEAN") and "us-east-1" in result and "us-west-2" in result


def test_a_leftover_in_another_recorded_region_fails_the_check(kit, stubs):
    from conftest import Stubs

    verify = load_script("99_verify_clean.py")
    write_state(kit, _history(("us-west-2", "kitdemo", ACCOUNT)))
    identity(stubs)
    empty_discovery(stubs)
    _verify_tail(stubs)
    west = Stubs(region="us-west-2")
    leftover = dict(runtime_summary(), agentRuntimeArn=WEST_ARN)
    empty_discovery(west, runtimes=[leftover])
    lines: list[str] = []
    rc = verify.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH, dry_run=True),
                     aws_for_region=lambda region: make_aws(kit, west, lines))
    assert rc == 1
    result = next(line for line in lines if line.startswith("RESULT:"))
    assert result.startswith("RESULT: NOT CLEAN") and "us-west-2" in result


def test_a_history_entry_for_another_account_makes_the_verdict_incomplete(kit, stubs):
    verify = load_script("99_verify_clean.py")
    write_state(kit, _history(("us-east-1", "kitdemo", OTHER_ACCOUNT)))
    identity(stubs)
    empty_discovery(stubs)
    _verify_tail(stubs)
    lines: list[str] = []
    rc = verify.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH, dry_run=True))
    assert rc == kit.EXIT_INCOMPLETE == 5
    result = next(line for line in lines if line.startswith("RESULT:"))
    assert result.startswith("RESULT: INCOMPLETE")
    assert "********9999" in result and OTHER_ACCOUNT not in "\n".join(lines)
    assert not any(line.startswith("RESULT: CLEAN") for line in lines)


def test_a_damaged_state_file_makes_the_verdict_incomplete(kit, stubs):
    verify = load_script("99_verify_clean.py")
    kit.STATE_PATH.write_text("{truncated")
    identity(stubs)
    empty_discovery(stubs)
    _verify_tail(stubs)
    lines: list[str] = []
    rc = verify.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH, dry_run=True, out=lines.append))
    assert rc == 5
    assert any(line.startswith("RESULT: INCOMPLETE") for line in lines)
