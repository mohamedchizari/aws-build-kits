"""Review round 4, 2026-10-07: teardown, the clean check, what a failed script says, and the
usage reading. Three readers; their own finding numbers are kept.

Reader of what a user sees (kit C):
  M5   teardown exited 0 while its own tag listing showed a bucket of this kit under another
       prefix: "demo-kitc-code-..." was looked for anywhere inside "kitdemo-kitc-code-...";
  M6   99_verify_clean.py printed RESULT: CLEAN beside a state file naming a runtime that still
       existed, because it only listed and never asked for the runtime by id;
  m8   a failure inside the run was reported to the caller of the hosted agent as "invalid_input";
  m9   60_read_usage.py: mixed record layouts and a session with no end time ended
       CROSS-CHECKED; the token line gave no hint when calls reported no tokens;
  m10  a log group that appears while the runtime is deleted was left, with exit code 0.
Reader of money safety:
  MAJOR 3   a full account id on the screen, from AWS's own error text and from a dry run that
            prints the runtime ARN it read from .state.json;
  MINOR 1   teardown said "finished without errors" after the call that stops a session failed;
  MINOR 2   teardown beside a state file it cannot use, with --region and --prefix, exited 0;
  MINOR 5   the RESULT: CLEAN line carried no "not proof for any other Region" words;
  MINOR 15  a name was written to .state.json only after the call that created the thing;
  and 30_deploy.py exited 2 ("refused") when credentials ran out after the runtime was created.
Reader with the emulator: a failed hosted call printed the error code twice and dropped AWS's
message; one test meant to be offline sent a name lookup.

Offline. The teardown and clean-check tests drive the real scripts against the World of
test_r2_money.py, a small account that remembers what exists.
"""
from __future__ import annotations

import json
import socket

import pytest
from conftest import ACCOUNT, RUNTIME_ARN, RUNTIME_ID, FakeClientError, NetworkBlocked, load_script, make_fake_aws
from test_r2_money import EAST, WEST, World, result_of, teardown, verify, write_state
from test_r2_usage import G, S1, S2, T0, V, inc, metrics, run, tot

OTHER_ACCOUNT_ARN = "arn:aws:iam::111122223333:user/example"   # an example id from AWS's documentation
DENIED_MESSAGE = (f"User: {OTHER_ACCOUNT_ARN} is not authorized to perform: bedrock-agentcore:DeleteAgentRuntime "
                  "on resource: arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/x")


@pytest.fixture()
def world(kit):
    return World(kit)


class Killed(BaseException):
    """The process dies right after a call: nothing after the call runs."""


# ====================================================================== M5
def test_M5_a_name_in_the_tag_listing_is_matched_whole_not_as_a_substring():
    import kit_resources

    found = {"tagged": [
        {"arn": f"arn:aws:s3:::kitdemo-kitc-code-{ACCOUNT}-us-east-1"},
        {"arn": f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-runtime-role"},
        {"arn": f"arn:aws:s3:::demo-kitc-code-{ACCOUNT}-us-east-1"},
        {"arn": f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:/aws/vendedlogs/bedrock-agentcore/demo-kitc-usage:*"},
        {"arn": f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/demo_kitc_fr_agent-abcdefghij"},
    ]}
    deleted = {f"demo-kitc-code-{ACCOUNT}-us-east-1", "demo-kitc-runtime-role",
               "/aws/vendedlogs/bedrock-agentcore/demo-kitc-usage", "demo_kitc_fr_agent-abcdefghij"}
    assert kit_resources.tagged_not_deleted(found, deleted) == [
        f"arn:aws:s3:::kitdemo-kitc-code-{ACCOUNT}-us-east-1", f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-runtime-role"]


def test_M5_teardown_under_one_prefix_is_not_clean_while_the_tag_listing_shows_another(kit, world):
    """Prefix "demo" is torn down. A bucket of a deploy under "kitdemo", the default prefix, is
    still there and the tag listing shows it. Exit code 1, and the line names the prefix."""
    write_state(kit, world.deploy(EAST, prefix="demo"))
    other = world.deploy(EAST, prefix="kitdemo")
    del world.runtimes[EAST][other["runtime_id"]]          # only its bucket and role are left
    rc, lines = teardown(kit, world, EAST, prefix="demo")
    text = "\n".join(lines)
    assert rc == 1, text
    assert "resource(s) of this kit remain that this run did not delete" in text
    assert "named with the prefix 'kitdemo', not 'demo'" in text
    assert f"bucket kitdemo-kitc-code-{ACCOUNT}-us-east-1" in world.left()
    assert not any(item.startswith(("bucket demo-", "role demo-", "runtime demo_")) for item in world.left())


# ====================================================================== M6
class ListLagsWorld(World):
    """ListAgentRuntimes does not show a runtime that GetAgentRuntime still finds."""

    def _handlers(self, region):
        handlers = super()._handlers(region)
        handlers["list_agent_runtimes"] = lambda **p: {"agentRuntimes": []}
        return handlers


def test_M6_the_clean_check_asks_for_the_recorded_runtime_by_id(kit):
    world = ListLagsWorld(kit)
    deployed = world.deploy(EAST, tagged=False)     # so the tag listing does not give it away either
    world.buckets.clear(), world.roles.clear(), world.log_groups.clear(), world.identities.clear()
    write_state(kit, deployed)
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT CLEAN: 1 item(s) left"), "\n".join(lines)
    assert any("is recorded in .state.json and still exists, although the listing by name did not show it" in line
               for line in lines)
    assert any(deployed["runtime_id"] in line and "recorded in .state.json" in line for line in lines)


class CannotAskWorld(World):
    """The listing by name shows nothing; after that GetAgentRuntime and ListAgentRuntimes are denied."""

    def _handlers(self, region):
        handlers = super()._handlers(region)
        listings = {"n": 0}

        def list_agent_runtimes(**p):
            listings["n"] += 1
            return {"agentRuntimes": []} if listings["n"] == 1 else FakeClientError("AccessDeniedException")
        handlers["list_agent_runtimes"] = list_agent_runtimes
        handlers["get_agent_runtime"] = lambda **p: FakeClientError("AccessDeniedException")
        return handlers


def test_M6_a_recorded_runtime_that_cannot_be_asked_for_is_not_verified(kit):
    world = CannotAskWorld(kit)
    deployed = world.deploy(EAST, tagged=False)
    world.buckets.clear(), world.roles.clear(), world.log_groups.clear(), world.identities.clear()
    write_state(kit, deployed)
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT VERIFIED"), "\n".join(lines)
    assert "could not be asked for by id" in result_of(lines)


def test_M6_unchanged_a_torn_down_deploy_is_still_clean(kit, world):
    write_state(kit, world.deploy(EAST))
    assert teardown(kit, world, EAST)[0] == 0
    rc, lines = verify(kit, world, EAST)
    assert rc == 0 and result_of(lines).startswith("RESULT: CLEAN")


# ====================================================================== m10
class LateLogGroupWorld(World):
    """AgentCore writes the runtime's own log group while the runtime is being deleted."""

    def _handlers(self, region):
        handlers = super()._handlers(region)
        delete = handlers["delete_agent_runtime"]

        def delete_agent_runtime(**p):
            answer = delete(**p)
            self.log_groups.setdefault(region, set()).add(
                f"/aws/bedrock-agentcore/runtimes/{p['agentRuntimeId']}-DEFAULT")
            return answer
        handlers["delete_agent_runtime"] = delete_agent_runtime
        return handlers


def test_m10_a_log_group_that_appears_while_the_runtime_is_deleted_is_deleted_too(kit):
    world = LateLogGroupWorld(kit)
    deployed = world.deploy(EAST)
    world.log_groups[EAST].clear()                  # not there when teardown lists for the first time
    write_state(kit, deployed)
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and world.left() == [], "\n".join(lines) + str(world.left())


# ====================================================================== MINOR 1
SESSION = "kitdemo-kitc-" + "7" * 32


class SessionWorld(World):
    """One open session. stop_fails says how many of the next stop calls are denied."""

    def __init__(self, kit, stop_fails):
        super().__init__(kit)
        self.stop_fails = stop_fails
        self.session_open = True
        self.stop_calls = 0

    def _handlers(self, region):
        handlers = super()._handlers(region)

        def stop_runtime_session(**p):
            self.stop_calls += 1
            if self.stop_fails:
                self.stop_fails -= 1
                return FakeClientError("AccessDeniedException", DENIED_MESSAGE)
            if not self.session_open:
                return FakeClientError("ResourceNotFoundException", "no such session")
            self.session_open = False
            return {"statusCode": 200}
        handlers["stop_runtime_session"] = stop_runtime_session
        return handlers


def _with_session(kit, world):
    record = world.deploy(EAST)
    record.update(idle_timeout_s=120, max_lifetime_s=900,
                  sessions=[{"session_id": SESSION, "started_at": "2026-10-07T12:00:00Z", "calls": [], "stopped": False}])
    write_state(kit, record)


def test_minor1_a_stop_that_fails_is_tried_again_after_the_runtime_is_gone_and_the_last_line_says_so(kit):
    world = SessionWorld(kit, stop_fails=1)
    _with_session(kit, world)
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert rc == 0 and world.stop_calls == 2 and not world.session_open, text
    assert "finished without errors" not in text
    closing = next(line for line in lines if line.startswith("Teardown finished."))
    assert "The first call to stop 1 session(s) failed" in closing
    assert "its idle timeout (120 s) or its maximum lifetime (900 s) ends it, at most $0.098" in closing
    assert "111122223333" not in text            # AWS's message names another account's ARN: masked


def test_minor1_a_session_that_cannot_be_stopped_at_all_is_an_error_with_its_cost(kit):
    world = SessionWorld(kit, stop_fails=99)
    _with_session(kit, world)
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert rc == 1 and world.stop_calls == 2, text
    assert "NOT STOPPED: the call that stops 1 recorded session(s) failed" in text
    assert "at most $0.098 a session at the list rates" in text
    assert "Teardown finished WITH ERRORS" in text and "finished without errors" not in text
    assert json.loads(kit.STATE_PATH.read_text())["sessions"][0]["session_id"] == SESSION   # the record is kept
    # run again once the stop works: the service says the session is gone, and the record is cleared
    world.stop_fails = 0
    world.session_open = False
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and "sessions" not in json.loads(kit.STATE_PATH.read_text()), "\n".join(lines)


def test_minor1_unchanged_a_stop_that_works_ends_without_errors(kit):
    world = SessionWorld(kit, stop_fails=0)
    _with_session(kit, world)
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and world.stop_calls == 1
    assert any(line.startswith("Teardown finished without errors.") for line in lines)


# ====================================================================== MINOR 2
def test_minor2_teardown_beside_a_state_file_it_cannot_use_ends_incomplete_with_exit_code_5(kit, world):
    world.deploy(EAST)
    kit.STATE_PATH.write_bytes(b'{"region": "us-east-1", "prefix": "kitdemo", "runtime_')
    rc, lines = teardown(kit, world, EAST, ["--region", EAST, "--prefix", "kitdemo"])
    text = "\n".join(lines)
    assert rc == kit.EXIT_INCOMPLETE == 5 and world.left() == [], text
    closing = next(line for line in lines if line.startswith("TEARDOWN INCOMPLETE"))
    assert "every delete worked" in closing and "cannot say where else this kit was deployed" in closing
    assert "not proof for any other Region, prefix or account" in closing and "Exit code 5, not 0" in closing


def test_minor2_the_wrong_region_named_by_hand_is_not_exit_code_0_either(kit, world):
    """The money reader's sequence C056: deployed in us-west-2, bucket and role removed by hand,
    state cut short, and the owner types the wrong Region. Nothing is found, nothing is deleted."""
    world.deploy(WEST)
    world.buckets.clear(), world.roles.clear()
    kit.STATE_PATH.write_bytes(b'{"region":')
    rc, lines = teardown(kit, world, EAST, ["--region", EAST, "--prefix", "kitdemo"])
    assert rc == 5 and any(i.startswith("runtime ") for i in world.left()), "\n".join(lines)


def test_minor2_a_failed_delete_beside_such_a_file_is_still_exit_code_1(kit, world):
    world.deploy(EAST)
    world.denied.add("delete_bucket")
    kit.STATE_PATH.write_bytes(b'{"region":')
    rc, lines = teardown(kit, world, EAST, ["--region", EAST, "--prefix", "kitdemo"])
    assert rc == 1 and any("Teardown finished WITH ERRORS" in line for line in lines)


# ====================================================================== MINOR 5
def test_minor5_every_clean_line_says_what_it_is_not_proof_of(kit, world):
    for prepare in ("no state file", "a finished run on record", "an empty state file"):
        if prepare == "a finished run on record":
            write_state(kit, world.deploy(EAST))
            assert teardown(kit, world, EAST)[0] == 0
        elif prepare == "an empty state file":
            write_state(kit, {})
        rc, lines = verify(kit, world, EAST)
        line = result_of(lines)
        assert rc == 0 and line.startswith("RESULT: CLEAN"), prepare
        assert "not proof for any" in line and "Region, prefix or account" in line, (prepare, line)


# ====================================================================== MINOR 15
IDENTITY = {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/x", "UserId": "A"}


def _deploy(kit, killed_at, built=True):
    """Run 30_deploy.py and kill it right after the named call. Returns the state file's content."""
    if built:
        kit.BUILD_DIR.mkdir(parents=True, exist_ok=True)
        kit.PACKAGE_ZIP.write_bytes(b"PK-not-a-real-zip")
        (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps({
            "entry_point": ["opentelemetry-instrument", "agentcore_app.py"], "python_runtime": "PYTHON_3_13",
            "sha256": "abc", "zipped_bytes": 17, "otel": True}))
    script = load_script("30_deploy.py")
    script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    handlers = {"get_caller_identity": IDENTITY, "create_bucket": {}, "put_bucket_tagging": {}, "put_object": {},
                "create_role": {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-runtime-role"}},
                "put_role_policy": {},
                "create_agent_runtime": {"agentRuntimeId": RUNTIME_ID, "agentRuntimeArn": RUNTIME_ARN,
                                         "agentRuntimeVersion": "1", "status": "CREATING"}}
    handlers[killed_at] = Killed()
    lines: list[str] = []
    with pytest.raises(Killed):
        script.main(["--i-understand-this-bills"], aws=make_fake_aws(kit, handlers, lines), out=lines.append,
                    state=kit.State(kit.STATE_PATH))
    return json.loads(kit.STATE_PATH.read_text())


def test_minor15_the_bucket_is_on_record_before_the_call_that_creates_it(kit):
    saved = _deploy(kit, "create_bucket")
    assert saved["bucket"] == f"kitdemo-kitc-code-{ACCOUNT}-us-east-1" and saved["region"] == "us-east-1"


def test_minor15_the_role_is_on_record_before_the_call_that_creates_it(kit):
    assert _deploy(kit, "create_role")["role_name"] == "kitdemo-kitc-runtime-role"


def test_minor15_the_runtime_is_on_record_by_name_before_the_call_that_creates_it(kit):
    saved = _deploy(kit, "create_agent_runtime")
    assert saved["runtime_name"] == "kitdemo_kitc_fr_agent" and saved["runtime_create_sent_at"]
    assert "runtime_id" not in saved        # AWS gives the id in the answer the dead process never read


def _observability(kit, killed_at):
    script = load_script("40_enable_observability.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    handlers = {"get_caller_identity": IDENTITY, "create_log_group": {}, "put_retention_policy": {},
                "put_delivery_source": {"deliverySource": {"name": "kitdemo-kitc-usage-src"}},
                "put_delivery_destination": {"deliveryDestination": {
                    "name": "kitdemo-kitc-usage-dst",
                    "arn": f"arn:aws:logs:us-east-1:{ACCOUNT}:delivery-destination:kitdemo-kitc-usage-dst"}},
                "create_delivery": {"delivery": {"id": "dlv0000000001"}}}
    handlers[killed_at] = Killed()
    lines: list[str] = []
    with pytest.raises(Killed):
        script.main(["--i-understand-this-bills", "--no-traces"], aws=make_fake_aws(kit, handlers, lines),
                    out=lines.append, state=state)
    return json.loads(kit.STATE_PATH.read_text())


@pytest.mark.parametrize("killed_at", ["create_log_group", "put_delivery_source", "put_delivery_destination",
                                       "create_delivery"])
def test_minor15_log_group_and_delivery_names_are_on_record_before_they_are_created(kit, killed_at):
    saved = _observability(kit, killed_at)
    assert saved["log_groups"] == ["/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-usage"]
    assert saved["delivery_in_progress"] == {"kind": "usage", "source": "kitdemo-kitc-usage-src",
                                             "destination": "kitdemo-kitc-usage-dst"}
    assert "deliveries" not in saved    # stated limit: the delivery's id is known only from AWS's answer


def test_minor15_a_finished_delivery_is_recorded_and_the_in_progress_note_is_gone(kit):
    script = load_script("40_enable_observability.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    handlers = {"get_caller_identity": IDENTITY, "create_log_group": {}, "put_retention_policy": {},
                "put_delivery_source": {"deliverySource": {"name": "s"}},
                "put_delivery_destination": {"deliveryDestination": {"name": "d", "arn": "arn:aws:logs:us-east-1:x"}},
                "create_delivery": {"delivery": {"id": "dlv0000000001"}}}
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills", "--no-traces", "--no-app-logs"],
                     aws=make_fake_aws(kit, handlers, lines), out=lines.append, state=state)
    saved = json.loads(kit.STATE_PATH.read_text())
    assert rc == 0 and "delivery_in_progress" not in saved, "\n".join(lines)
    assert [d["delivery_id"] for d in saved["deliveries"]] == ["dlv0000000001"]


@pytest.mark.parametrize("killed_at, key, value", [
    ("create_role", "gateway_role_name", "kitdemo-kitc-gateway-role"),
    ("create_gateway", "gateway_name", "kitdemo-kitc-gateway"),
    ("create_gateway_target", "gateway_target_name", "federal-register"),
])
def test_minor15_the_gateway_step_writes_each_name_before_its_create_call(kit, killed_at, key, value):
    script = load_script("optional_gateway/10_create_gateway.py")
    gateway_id = "kitdemo-kitc-gateway-abcdefghij"
    handlers = {"get_caller_identity": IDENTITY,
                "create_role": {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-gateway-role"}},
                "create_gateway": {"gatewayId": gateway_id, "gatewayUrl": "https://x/mcp", "status": "CREATING",
                                   "gatewayArn": f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:gateway/{gateway_id}"},
                "get_gateway": {"status": "READY"}, "create_gateway_target": {"targetId": "TGT0000001", "status": "CREATING"}}
    handlers[killed_at] = Killed()
    lines: list[str] = []
    with pytest.raises(Killed):
        script.main(["--i-understand-this-bills"], aws=make_fake_aws(kit, handlers, lines), out=lines.append,
                    state=kit.State(kit.STATE_PATH))
    assert json.loads(kit.STATE_PATH.read_text())[key] == value


# ====================================================================== exit code after acting
class NoCredentialsError(Exception):
    """Named like botocore's, which is how kitlib.explain_aws_error recognises it."""


def test_deploy_exits_1_not_2_when_credentials_run_out_after_the_runtime_was_created(kit):
    kit.BUILD_DIR.mkdir(parents=True)
    kit.PACKAGE_ZIP.write_bytes(b"PK")
    (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps({
        "entry_point": ["agentcore_app.py"], "python_runtime": "PYTHON_3_13", "sha256": "abc", "otel": False}))
    script = load_script("30_deploy.py")
    script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    handlers = {"get_caller_identity": IDENTITY, "create_bucket": {}, "put_bucket_tagging": {}, "put_object": {},
                "create_role": {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/r"}}, "put_role_policy": {},
                "create_agent_runtime": {"agentRuntimeId": RUNTIME_ID, "agentRuntimeArn": RUNTIME_ARN, "status": "CREATING"},
                "get_agent_runtime": NoCredentialsError("Unable to locate credentials")}
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills"], aws=make_fake_aws(kit, handlers, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH))
    assert rc == 1, "\n".join(lines)
    assert lines[-1].startswith("Deployment did not finish.") and "run 90_teardown.py, which looks by name" in lines[-1]
    assert json.loads(kit.STATE_PATH.read_text())["runtime_id"] == RUNTIME_ID


def test_deploy_says_what_to_do_when_aws_answers_that_the_runtime_already_exists(kit):
    """Emulator, finding 1: the answer to the create call was lost, the SDK sent it again, and
    the second answer was "already exists". The runtime's id is then not on record; its name is."""
    kit.BUILD_DIR.mkdir(parents=True)
    kit.PACKAGE_ZIP.write_bytes(b"PK")
    (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps({"entry_point": ["agentcore_app.py"]}))
    script = load_script("30_deploy.py")
    script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    handlers = {"get_caller_identity": IDENTITY, "create_bucket": {}, "put_bucket_tagging": {}, "put_object": {},
                "create_role": {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/r"}}, "put_role_policy": {},
                "create_agent_runtime": FakeClientError("ConflictException", "An agent with this name already exists")}
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills"], aws=make_fake_aws(kit, handlers, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH))
    saved = json.loads(kit.STATE_PATH.read_text())
    assert rc == 1 and saved["runtime_name"] == "kitdemo_kitc_fr_agent" and "runtime_id" not in saved
    assert any("run 90_teardown.py first, then deploy" in line for line in lines)
    assert lines[-1].startswith("Deployment did not finish.") and "a runtime's id only if AWS answered" in lines[-1]


def test_deploy_still_exits_2_when_there_were_no_credentials_to_begin_with(kit):
    kit.BUILD_DIR.mkdir(parents=True)
    kit.PACKAGE_ZIP.write_bytes(b"PK")
    (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps({"entry_point": ["agentcore_app.py"]}))
    script = load_script("30_deploy.py")
    script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills"], out=lines.append, state=kit.State(kit.STATE_PATH),
                     aws=make_fake_aws(kit, {"get_caller_identity": NoCredentialsError("Unable to locate credentials")}, lines))
    assert rc == 2 and lines[-1] == "Deployment did not start: no create call was sent."
    assert not kit.STATE_PATH.exists()


# ====================================================================== MAJOR 3
def test_major3_redact_masks_a_12_digit_number_and_nothing_else(kit):
    assert kit.redact(f"User: {OTHER_ACCOUNT_ARN} is not authorized") == "User: arn:aws:iam::********3333:user/example is not authorized"
    assert kit.redact("bucket kitdemo-kitc-code-111122223333-us-east-1") == "bucket kitdemo-kitc-code-********3333-us-east-1"
    assert kit.redact("startTime=1791367200000 and 12345678901 and 2026-19964") == "startTime=1791367200000 and 12345678901 and 2026-19964"
    assert kit.redact(f"dry run account {kit.DRY_ACCOUNT}") == f"dry run account {kit.DRY_ACCOUNT}"   # the placeholder


def test_major3_an_aws_error_is_printed_without_the_account_id(kit):
    lines: list[str] = []
    assert kit.explain_aws_error(FakeClientError("AccessDeniedException", DENIED_MESSAGE), lines.append) == 1
    assert "111122223333" not in lines[0] and "********3333" in lines[0] and "AccessDeniedException" in lines[0]


def test_major3_a_denied_delete_in_teardown_prints_no_account_id(kit, world):
    write_state(kit, world.deploy(EAST))
    handlers = world._handlers

    def denied(region):
        table = handlers(region)
        table["delete_agent_runtime"] = lambda **p: FakeClientError("AccessDeniedException", DENIED_MESSAGE)
        return table
    world._handlers = denied
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert rc == 1 and "FAILED (AccessDeniedException: User: arn:aws:iam::********3333:user/example" in text
    assert "111122223333" not in text


@pytest.mark.parametrize("script_name, argv", [("40_enable_observability.py", ["--dry-run"]),
                                               ("50_invoke_hosted.py", ["--dry-run", "--sessions", "1"])])
def test_major3_a_dry_run_with_a_deploy_on_record_prints_no_account_id(kit, script_name, argv):
    real_account = "111122223333"
    arn = f"arn:aws:bedrock-agentcore:us-east-1:{real_account}:runtime/{RUNTIME_ID}"
    kit.STATE_PATH.write_text(json.dumps({"region": "us-east-1", "prefix": "kitdemo", "account_id": real_account,
                                          "runtime_id": RUNTIME_ID, "runtime_arn": arn}))
    before = kit.STATE_PATH.read_bytes()
    lines: list[str] = []
    rc = load_script(script_name).main(argv, aws=kit.Aws("us-east-1", dry_run=True, out=lines.append), out=lines.append,
                                       state=kit.State(kit.STATE_PATH, dry_run=True, out=lines.append))
    text = "\n".join(lines)
    assert rc == 0 and real_account not in text, text
    assert f"arn:aws:bedrock-agentcore:us-east-1:********3333:runtime/{RUNTIME_ID}" in text
    assert kit.STATE_PATH.read_bytes() == before


# ====================================================================== emulator, findings 3 and 7
def test_a_failed_hosted_call_prints_the_code_and_what_aws_said(kit):
    script = load_script("50_invoke_hosted.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID,
              idle_timeout_s=120, max_lifetime_s=900)

    class RuntimeClientError(Exception):      # botocore names the class after the code
        response = {"Error": {"Code": "RuntimeClientError",
                              "Message": "The runtime did not respond: the agent process exited with code 1"}}

    lines: list[str] = []
    aws = make_fake_aws(kit, {"get_caller_identity": IDENTITY, "invoke_agent_runtime": RuntimeClientError(),
                              "stop_runtime_session": {"statusCode": 200}}, lines)
    rc = script.main(["--i-understand-this-bills", "--sessions", "1", "--calls-per-session", "1"],
                     aws=aws, out=lines.append, state=state)
    failed = next(line for line in lines if "FAILED after" in line)
    assert rc == 1 and failed.endswith("RuntimeClientError: The runtime did not respond: the agent process exited with code 1")
    assert "RuntimeClientError: RuntimeClientError" not in failed


def test_the_runtimes_own_named_error_is_printed_with_its_reason(kit):
    script = load_script("50_invoke_hosted.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    body = json.dumps({"error": "run_failed", "detail": "ValueError: 1 validation error for ConverseResponse"}).encode()
    lines: list[str] = []
    aws = make_fake_aws(kit, {"get_caller_identity": IDENTITY, "stop_runtime_session": {"statusCode": 200},
                              "invoke_agent_runtime": lambda **p: {"statusCode": 200, "response": body}}, lines)
    script.main(["--i-understand-this-bills", "--sessions", "1", "--calls-per-session", "1"], aws=aws, out=lines.append, state=state)
    assert any("FAILED after" in line and "run_failed: ValueError: 1 validation error" in line for line in lines)


def test_the_offline_guard_refuses_a_name_lookup():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("www.federalregister.gov", 443)
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("www.federalregister.gov", 443), timeout=1)


# ====================================================================== m8
def test_m8_a_failure_inside_the_run_is_not_reported_as_the_callers_bad_input(monkeypatch):
    import agentcore_app

    class Boom:
        def stream(self, *args, **kwargs):
            raise ValueError("1 validation error for ConverseResponse: output.message.content field required")

    monkeypatch.setattr(agentcore_app, "_get_graph", lambda prompt: (Boom(), "fake"))
    answer = agentcore_app.invoke({"prompt": "What is the newest FAA airworthiness directive?"}, None)
    assert answer["error"] == "run_failed" and "ConverseResponse" in answer["detail"]
    assert agentcore_app.invoke({"prompt": "x" * 5000}, None)["error"] == "invalid_input"   # this one is the caller's
    assert agentcore_app.invoke({"prompt": "   "}, None)["error"] == "invalid_input"


# ====================================================================== m9
def _sessions(second):
    first = {"session_id": S1, "started_at": "2026-10-07T10:00:00Z", "ended_at": "2026-10-07T10:01:00Z",
             "stopped": True, "calls": [{"input_tokens": 3000, "output_tokens": 500}]}
    return [first, dict({"session_id": S2, "started_at": "2026-10-07T10:00:00Z", "stopped": True,
                         "calls": [{"input_tokens": 3000, "output_tokens": 500}]}, **second)]


def test_m9_records_that_look_like_increments_in_one_session_and_totals_in_another_are_not_cross_checked(kit, monkeypatch):
    events = lambda sid: inc(sid) if sid == S1 else tot(sid)       # noqa: E731
    total_v = V + sum(min(i + 1, 6) / 3600 for i in range(60))       # what adding everything up gives
    total_g = G + sum(0.5 * (i + 1) / 3600 for i in range(60))
    rc, result, lines, state = run(kit, monkeypatch, events,
                                   {"CPUUsed-vCPUHours": total_v, "MemoryUsed-GBHours": total_g},
                                   sessions=_sessions({"ended_at": "2026-10-07T10:01:00Z"}))
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED"), result
    assert "look like increments and those of others like running totals" in result
    assert state.get("usage_cross_checked_at") is None


def test_m9_a_session_with_no_end_time_is_not_cross_checked(kit, monkeypatch):
    one = [{"timestamp": T0, "message": json.dumps({"session.id": S2, "elapsed_time_seconds": 5,
                                                    "agent.runtime.vcpu.hours.used": V / 12,
                                                    "agent.runtime.memory.gb_hours.used": G / 12})}]
    rc, result, lines, state = run(kit, monkeypatch, lambda sid: inc(sid) if sid == S1 else one,
                                   {"CPUUsed-vCPUHours": V + V / 12, "MemoryUsed-GBHours": G + G / 12},
                                   sessions=_sessions({}))
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED"), result
    assert "1 session(s) have no end time in .state.json" in result
    assert any("NO END TIME ON RECORD" in line for line in lines)


def test_m9_unchanged_two_complete_sessions_are_cross_checked(kit, monkeypatch):
    rc, result, lines, state = run(kit, monkeypatch, inc, metrics())
    assert rc == 0 and result.startswith("RESULT: CROSS-CHECKED"), result
    assert not any("LOWER BOUND" in line or "NOT A MEASURED COST" in line for line in lines)


def test_m9_the_token_line_says_when_a_call_reported_no_tokens(kit, monkeypatch):
    sessions = _sessions({"ended_at": "2026-10-07T10:01:00Z"})
    sessions[1]["calls"] = [{"input_tokens": None, "output_tokens": None, "error": "ReadTimeoutError: x"}]
    rc, result, lines, state = run(kit, monkeypatch, inc, metrics(), sessions=sessions)
    line = next(line for line in lines if line.startswith("Token cost:"))
    assert "LOWER BOUND: 1 of 2 call(s) reported no token count" in line


def test_m9_a_token_cost_of_zero_is_not_shown_as_a_measured_cost(kit, monkeypatch):
    sessions = _sessions({"ended_at": "2026-10-07T10:01:00Z"})
    for session in sessions:
        session["calls"] = [{"input_tokens": 0, "output_tokens": 0}]
    rc, result, lines, state = run(kit, monkeypatch, inc, metrics(), sessions=sessions)
    line = next(line for line in lines if line.startswith("Token cost:"))
    assert "= $0.000000" in line and "NOT A MEASURED COST: no call reported any tokens" in line
