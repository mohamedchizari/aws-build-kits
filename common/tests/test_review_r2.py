"""Tests written from the round 2 independent review (2026-10-07).

The reviewer ran 143 teardown and audit sequences against a stateful fake account.
Each finding that concerns common/ has tests here that failed on the code as
reviewed and pass now. Test names start with the finding:

    test_r2_u02d_      sequence U02d under BLOCKER 1: a damaged state file that a kit set aside
    test_r2_minor14_   MINOR 14 and sequence U01b: how visible the lost-state limit is
    test_r2_allregions_  the --all-regions switch that the lost-state limit calls for
    test_r2_minor10_   MINOR 10: --after-teardown exits 0 with [FOUND] rows
    test_r2_budget_    the budget that budget_alarm.py creates was covered by no row
    test_r2_u03_       sequence U03: --only, whose RESULT line must be impossible to misread
    test_r2_u04_       sequences U04 and U04b: --ignore-storage-only, the same

Offline: no network, no credentials, no AWS call.
"""
from __future__ import annotations

import json

import pytest
from botocore.stub import Stubber

import budget_alarm as ba
import whats_running as wr
from helpers import (
    TEST_ACCOUNT, Err, FakeAccount, MixedFactory, OlderBoto3Client, client_error, failure_kinds, forbidden_factory,
    log_groups_like_aws, real_client,
)

OTHER_ACCOUNT = "444455556666"  # a second AWS documentation placeholder account id
KIT_A, KIT_B, KIT_C = "kit_a_gpu_endpoint", "kit_b_federal_rag_eval", "kit_c_langgraph_agentcore"
EXAMPLE = "AWS_REGION=us-east-1\nKIT_PREFIX=kitdemo\n"

# The sentence for one kit. When several kits have no state file each is named ("kit_x: no state file")
# and the consequence is said once, for "those kits".
NO_STATE = "{kit}: no state file, so this audit cannot know where that kit was last deployed; only the Regions listed here were checked"
NO_REGION = "{kit}: its state file names no Region, so this audit cannot know where that kit was last deployed; only the Regions listed here were checked"
SEVERAL = "so this audit cannot know where those kits were last deployed; only the Regions listed here were checked"
NOTHING = "nothing that bills while idle was found"


def make_kit(root, name, config=None, example=EXAMPLE, state=None, extra=None):
    """Create a sibling kit folder the way a kit leaves it on disk. extra: {file name: text}."""
    kit = root / name
    kit.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (kit / "config.env").write_text(config, encoding="utf-8")
    if example is not None:
        (kit / "config.example.env").write_text(example, encoding="utf-8")
    if state is not None:
        (kit / ".state.json").write_text(state if isinstance(state, str) else json.dumps(state), encoding="utf-8")
    for file_name, text in (extra or {}).items():
        (kit / file_name).write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return kit


def run(argv, account, capsys, kits=None, monkeypatch=None):
    if kits is not None:
        monkeypatch.setattr(wr, "KITS_DIR", kits, raising=False)
    code = wr.main(list(argv), client_factory=account)
    return code, capsys.readouterr().out


def result_line(out):
    return next(line for line in out.splitlines() if line.startswith("RESULT"))


def found_rows(out):
    """How many rows of the --after-teardown screen are marked [FOUND]."""
    return sum(1 for line in out.splitlines() if line.startswith("  [FOUND]"))


def good_state(region="us-east-1", prefix="kitdemo"):
    return {"account_id": TEST_ACCOUNT, "region": region, "prefix": prefix, "history": []}


RUNTIME_SUMMARY = {"agentRuntimeName": "kitdemo_kitc_fr_agent", "agentRuntimeId": "kitdemo_kitc_fr_agent-ab00000001", "agentRuntimeVersion": "1", "status": "READY"}
ENDPOINT = {"Endpoints": [{"EndpointName": "kitdemo-kita-endpoint", "EndpointStatus": "InService"}]}


# ==========================================================  U02d (BLOCKER 1)
# What kit C left on disk in the reviewer's sequence U02d: a fresh, valid .state.json whose history
# names only us-east-1, and the damaged file it had set aside, which still names us-west-2.
SET_ASIDE = ".state.json.damaged-20261007T122912Z-3548"
DAMAGED_KIT_C_STATE = (
    '{\n  "account_id": "%(a)s",\n  "bucket": "kitdemo-kitc-code-%(a)s-us-west-2",\n'
    '  "code_key": "kitdemo_kitc_fr_agent/deployment_package.zip",\n  "deployed_at": "2026-10-07T12:29:11Z",\n'
    '  "idle_timeout_s": 120,\n  "prefix": "kitdemo",\n  "region": "us-west-2",\n  "role_name": "kitdemo-kitc-runtime-role",\n'
    '  "runtime_arn": "arn:aws:bedrock-agentcore:us-west-2:%(a)s:runt'
) % {"a": TEST_ACCOUNT}
STATE_AFTER_KIT_C_TEARDOWN = {
    "damaged_state_set_aside": [SET_ASIDE],
    "history": [{"account_id": TEST_ACCOUNT, "deployed_at": None, "gateway_id": None, "prefix": "kitdemo", "region": "us-east-1", "runtime_id": None, "torn_down_at": "2026-10-07T12:29:12Z"}],
    "past_sessions": [],
}


def test_r2_u02d_a_state_file_a_kit_set_aside_as_damaged_is_still_read(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_C, state=STATE_AFTER_KIT_C_TEARDOWN, extra={SET_ASIDE: DAMAGED_KIT_C_STATE})
    # the reviewer's world: the runtime and its log group are alive in us-west-2, nothing in us-east-1
    account = FakeAccount({
        ("bedrock-agentcore-control", "list_agent_runtimes", "us-west-2"): {"agentRuntimes": [RUNTIME_SUMMARY]},
        ("logs", "describe_log_groups", "us-west-2"): log_groups_like_aws(["/aws/bedrock-agentcore/runtimes/kitdemo_kitc_fr_agent-ab00000001-DEFAULT"]),
    })
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert "us-west-2" in account.regions_called("bedrock-agentcore-control")  # the salvaged Region is audited
    assert code == 2
    assert "AgentCore runtime: kitdemo_kitc_fr_agent" in out
    line = result_line(out)
    assert "NOT CLEAN" in line and f"{KIT_C}/{SET_ASIDE}" in line and "us-west-2" in line
    assert NOTHING not in out
    assert TEST_ACCOUNT not in out


def test_r2_u02d_a_set_aside_file_keeps_the_audit_not_clean_even_when_nothing_is_found(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_C, state=STATE_AFTER_KIT_C_TEARDOWN, extra={SET_ASIDE: DAMAGED_KIT_C_STATE})
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    line = result_line(out)
    assert "NOT CLEAN" in line and "unreadable or damaged state file" in line and f"{KIT_C}/{SET_ASIDE}" in line
    assert NOTHING not in out
    # and the same with the one-screen view for that kit
    code, out = run(["--after-teardown", "c"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2 and f"{KIT_C}/{SET_ASIDE}" in result_line(out)


@pytest.mark.parametrize("name", [SET_ASIDE, ".state.json.tmp", ".state.json.tmp-4242", ".state.json.bak", ".state.json.old.1", ".state.json~"])
def test_r2_u02d_every_state_file_name_in_a_kit_folder_is_read(name, tmp_path, monkeypatch, capsys):
    # kit A and kit B write .state.json.tmp, kit C writes .state.json.tmp-<pid>, the older kit C left
    # .state.json.damaged-<time>-<pid>; a copy made by hand can have any ending.
    make_kit(tmp_path, KIT_C, state=good_state(), extra={name: DAMAGED_KIT_C_STATE})
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert "us-west-2" in account.regions_called("sagemaker"), name
    assert code == 2
    assert f"{KIT_C}/{name}" in result_line(out)


def test_r2_u02d_a_readable_extra_copy_adds_its_region_and_is_not_a_problem(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_A, state=good_state(), extra={".state.json.bak": good_state(region="eu-west-1", prefix="older")})
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert {"us-east-1", "eu-west-1"} <= account.regions_called("sagemaker")
    assert code == 0, out
    assert "older" in result_line(out) and "damaged" not in result_line(out)


def test_r2_u02d_a_file_named_damaged_counts_as_damaged_even_if_it_parses(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_C, state=good_state(), extra={SET_ASIDE: good_state(region="ap-southeast-2")})
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert "ap-southeast-2" in account.regions_called("logs")
    assert code == 2 and f"{KIT_C}/{SET_ASIDE}" in result_line(out)


@pytest.mark.parametrize("text", ["", "   \n", '{"region": "us-west-2", "resources": [{"arn": "arn:aws:sagemaker:eu-west-1:', "\x00\x01 not json"])
def test_r2_u02d_a_damaged_main_state_file_is_named_in_the_result_line(text, tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_A, state=text)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    line = result_line(out)
    assert "unreadable or damaged state file" in line and f"{KIT_A}/.state.json" in line


def test_r2_u02d_a_state_file_that_cannot_be_opened_is_named_in_the_result_line(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_B, state=good_state())
    real = wr._read_local_file

    def denied(path):
        if path.name == ".state.json":
            raise PermissionError(13, "Permission denied", str(path))
        return real(path)

    monkeypatch.setattr(wr, "_read_local_file", denied)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert f"{KIT_B}/.state.json" in result_line(out) and "unreadable or damaged state file" in result_line(out)
    assert str(tmp_path) not in out


def test_r2_u02d_a_folder_where_the_state_file_should_be_is_not_read_as_no_state(tmp_path, monkeypatch, capsys):
    kit = make_kit(tmp_path, KIT_A)
    (kit / ".state.json").mkdir()
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert f"{KIT_A}/.state.json" in result_line(out)
    assert f"{KIT_A}: no state file" not in out


@pytest.mark.parametrize(
    "text, regions, in_line",
    [
        # the container image address kit A records carries the Region of the deploy
        ('{"deploy": {"image_uri": "%s.dkr.ecr.eu-west-2.amazonaws.com/vllm:0.30.0", "ins' % OTHER_ACCOUNT, {"eu-west-2"}, []),
        # a Region as a bare value under a key this audit does not know
        ('{"deploy": {"where": ["ap-south-1", "ca-central-1"], "x": {', {"ap-south-1", "ca-central-1"}, []),
        # a kit bucket name: prefix, account and Region
        ('{"bucket": "acme-fedrag-corpus-%s-eu-central-1", "kb' % OTHER_ACCOUNT, {"eu-central-1"}, ["acme"]),
        # an ARN cut off after its Region
        ('{"resources": [{"arn": "arn:aws:sagemaker:sa-east-1:', {"sa-east-1"}, []),
        # a key spelled another way, and Python-style quotes
        ("{'AwsRegion': 'us-west-1', 'KitPrefix': 'zulu', 'history': [", {"us-west-1"}, ["zulu"]),
        # a resource name: the prefix in front of the kit's fixed infix
        ('{"endpoint": "bravo-kita-endpoint", "region": "us-east-2", "history": [{', {"us-east-2"}, ["bravo"]),
    ],
)
def test_r2_u02d_regions_prefixes_and_accounts_are_salvaged_by_pattern(text, regions, in_line, tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_B, extra={SET_ASIDE: text})
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert regions <= account.regions_called("sagemaker"), out
    assert code == 2
    line = result_line(out)
    for expected in list(regions) + in_line:
        assert expected in line, expected
    if "dkr.ecr" in text:  # the registry account in an image address is AWS's, not the kit's account
        assert "ending 6666" not in out
    assert OTHER_ACCOUNT not in out and TEST_ACCOUNT not in out


def test_r2_u02d_a_salvaged_bucket_name_in_another_account_is_reported(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_B, state='{"bucket": "kitdemo-fedrag-corpus-%s-us-east-1", "kb' % OTHER_ACCOUNT)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "names the account ending 6666" in out and "account ending 3333" in out


def test_r2_u02d_salvage_does_not_take_a_prefix_or_a_date_for_a_region(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_A, state='{"prefix": "my-kit-1", "revision": "ab-cd-2", "note": "to-do-3", "hist')
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert account.regions_called("sagemaker") == {"us-east-1"}
    assert "my-kit-1" in result_line(out)  # it is a prefix


def test_r2_u02d_config_env_lines_that_do_not_parse_or_are_commented_out_still_give_their_region(tmp_path, monkeypatch, capsys):
    config = "# AWS_REGION=us-west-2   (the Region I used last week)\nAWS_REGION: ap-southeast-2\nset KIT_PREFIX = 'acme'\nAWS_DEFAULT_REGION=eu-north-1\n"
    make_kit(tmp_path, KIT_A, config=config, state=good_state())
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert {"us-west-2", "ap-southeast-2", "eu-north-1", "us-east-1"} <= account.regions_called("sagemaker")
    assert "acme" in result_line(out)
    assert code == 0, out  # a config file is not a state file: odd lines in it are not a reason for NOT CLEAN


def test_r2_u02d_the_scope_listing_names_every_state_file_it_read(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, KIT_C, state=STATE_AFTER_KIT_C_TEARDOWN, extra={SET_ASIDE: DAMAGED_KIT_C_STATE})
    monkeypatch.setattr(wr, "KITS_DIR", tmp_path, raising=False)
    code = wr.main(["--dry-run"], client_factory=forbidden_factory)
    out = capsys.readouterr().out
    assert code == 3
    assert f"Region us-west-2: {KIT_C}/{SET_ASIDE}" in out
    assert "SCOPE PROBLEMS" in out and SET_ASIDE in out.split("SCOPE PROBLEMS")[1]


# ================================================  MINOR 14 and U01b: the lost-state limit
def three_kits(root, **states):
    for letter, name in (("a", KIT_A), ("b", KIT_B), ("c", KIT_C)):
        make_kit(root, name, state=states.get(letter))


def test_r2_minor14_each_kit_folder_without_a_state_file_is_named_in_the_result_line(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0  # an account with nothing in it and kits that were never deployed is still exit 0
    for kit in (KIT_A, KIT_B, KIT_C):
        assert f"{kit}: no state file" in line
    assert line.count(SEVERAL) == 1
    assert "--all-regions" in line
    assert line.index("no state file") < line.index(NOTHING)  # the limit is read before the good news


def test_r2_minor14_a_kit_with_a_state_file_gets_no_such_sentence(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, b=good_state(region="us-west-2"))
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0
    assert f"{KIT_A}: no state file; {KIT_C}: no state file; {SEVERAL}" in line
    assert f"{KIT_B}: no state file" not in line and f"{KIT_B}: its state file" not in line


def test_r2_minor14_all_three_kits_with_state_files_get_a_plain_result_line(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0
    assert line.startswith(f"RESULT: {NOTHING}, and every check ran (exit 0).")
    assert "no state file" not in line and "LIMITED CHECK" not in line


@pytest.mark.parametrize("state", ["{}", "null", '{"deploy": null, "history": [], "resources": []}'])
def test_r2_minor14_a_state_file_that_names_no_region_is_said_too(state, tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=state, b=good_state(), c=good_state())
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 0
    assert NO_REGION.format(kit=KIT_A) in result_line(out)


def test_r2_minor14_no_kit_folder_at_all_is_said_in_the_result_line(tmp_path, monkeypatch, capsys):
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0
    assert "no kit folder was found beside this script, so this audit cannot know where any kit was deployed; only the Regions listed here were checked" in line
    assert line.index("no kit folder") < line.index(NOTHING)


def test_r2_u01b_state_lost_and_a_region_that_was_only_exported_is_a_limit_the_result_line_states(tmp_path, monkeypatch, capsys):
    # The reviewer's U01b: kit A was deployed with AWS_REGION=us-west-2 exported, .state.json was then
    # deleted, and the audit runs in a new shell. Nothing on this machine names us-west-2.
    three_kits(tmp_path)
    account = FakeAccount({("sagemaker", "list_endpoints", "us-west-2"): ENDPOINT})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert account.regions_called("sagemaker") == {"us-east-1"}
    assert code == 0  # the limit itself: the audit cannot know
    assert f"{KIT_A}: no state file" in line and SEVERAL in line and "Regions us-east-1;" in line
    assert "run again with --all-regions" in line
    assert line.index("no state file") < line.index(NOTHING)
    # the same on the one-screen view
    code, out = run(["--after-teardown", "a"], account, capsys, tmp_path, monkeypatch)
    assert code == 0 and f"{KIT_A}: no state file" in result_line(out) and SEVERAL in result_line(out)

    # with the other two kits recorded, the one that lost its state gets the sentence for one kit, word for word
    three_kits(tmp_path, b=good_state(), c=good_state())
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 0 and NO_STATE.format(kit=KIT_A) in result_line(out)


def test_r2_u01b_all_regions_finds_the_endpoint_the_default_run_could_not_know_about(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path)
    account = FakeAccount({
        ("sagemaker", "list_endpoints", "us-west-2"): ENDPOINT,
        ("account", "list_regions"): {"Regions": [
            {"RegionName": "us-east-1", "RegionOptStatus": "ENABLED_BY_DEFAULT"},
            {"RegionName": "us-west-2", "RegionOptStatus": "ENABLED_BY_DEFAULT"},
            {"RegionName": "me-south-1", "RegionOptStatus": "DISABLED"},
        ]},
    })
    code, out = run(["--all-regions"], account, capsys, tmp_path, monkeypatch)
    assert account.regions_called("sagemaker") == {"us-east-1", "us-west-2"}
    assert code == 2
    assert "BILLS WHILE IDLE: YES | SageMaker endpoint: kitdemo-kita-endpoint" in out
    line = result_line(out)
    assert "NOT CLEAN" in line and "us-west-2" in line


def test_r2_minor14_json_names_the_kits_without_a_state_file_and_carries_the_result_line(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, c=good_state())
    code, out = run(["--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert code == 0 and doc["exit_code"] == 0
    assert doc["audited"]["kits_without_state_file"] == [KIT_A, KIT_B]
    assert doc["audited"]["state_files_read"] == [f"{KIT_C}/.state.json"]
    assert doc["damaged_state_files"] == []
    assert f"{KIT_A}: no state file; {KIT_B}: no state file; {SEVERAL}" in doc["result_line"] and doc["result_line"].startswith("RESULT: ")


def test_r2_minor14_only_does_not_read_the_kit_folders_so_it_cannot_speak_about_their_state(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path)
    code, out = run(["--only", "--region", "us-east-1", "--prefix", "kitdemo"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert "no state file" not in out and result_line(out).startswith("RESULT: LIMITED CHECK: ")


# ==========================================================  --all-regions
def regions_response(*pairs, token=None):
    response = {"Regions": [{"RegionName": name, "RegionOptStatus": status} for name, status in pairs]}
    if token:
        response["NextToken"] = token
    return response


def test_r2_allregions_the_call_matches_the_service_model_and_follows_the_token(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    client = real_client("account")
    stubber = Stubber(client)
    stubber.add_response("list_regions", regions_response(("us-east-1", "ENABLED_BY_DEFAULT"), ("eu-south-1", "ENABLED"), token="page-2"), {"MaxResults": 50})
    stubber.add_response("list_regions", regions_response(("ap-east-1", "DISABLED"), ("us-west-2", "ENABLED_BY_DEFAULT")), {"MaxResults": 50, "NextToken": "page-2"})
    stubber.activate()
    fake = FakeAccount()
    code, out = run(["--all-regions"], MixedFactory(fake, {"account": client}), capsys, tmp_path, monkeypatch)
    stubber.assert_no_pending_responses()
    assert fake.regions_called("sagemaker") == {"us-east-1", "eu-south-1", "us-west-2"}
    assert code == 0, out
    line = result_line(out)
    assert "Regions us-east-1, eu-south-1, us-west-2;" in line
    assert "--all-regions" in line and "3" in line
    assert "run again with --all-regions" not in line
    assert "ap-east-1" in out and "NOT audited" in out  # the Region that is not enabled is named, with why it still matters
    assert "charges for resources (if any) in that disabled opt-in Region continue to accrue" in out


def test_r2_allregions_regions_that_are_being_enabled_or_disabled_are_audited_too(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("account", "list_regions"): regions_response(
        ("us-east-1", "ENABLED_BY_DEFAULT"), ("af-south-1", "ENABLING"), ("me-south-1", "DISABLING"), ("ap-east-1", "DISABLED"),
    )})
    code, out = run(["--all-regions"], account, capsys, tmp_path, monkeypatch)
    assert account.regions_called("logs") == {"us-east-1", "af-south-1", "me-south-1"}


@pytest.mark.parametrize("kind", sorted(failure_kinds()))
def test_r2_allregions_when_regions_cannot_be_listed_the_audit_says_so_and_never_exits_0(kind, tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    account = FakeAccount({("account", "list_regions"): failure_kinds()[kind]()})
    code, out = run(["--all-regions"], account, capsys, tmp_path, monkeypatch)
    assert code == 2, kind
    line = result_line(out)
    assert "NOT CLEAN" in line and "could not list Regions" in line, kind
    assert NOTHING not in out and "Traceback" not in out
    assert account.regions_called("sagemaker") == {"us-east-1"}  # what was known is still audited


def test_r2_allregions_access_denied_names_the_permission_that_is_missing(tmp_path, monkeypatch, capsys):
    denied = client_error("AccessDeniedException", f"User: arn:aws:iam::{TEST_ACCOUNT}:user/x is not authorized to perform: account:ListRegions")
    code, out = run(["--all-regions"], FakeAccount({("account", "list_regions"): denied}), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "could not list Regions" in result_line(out) and "AccessDeniedException" in out and "account:ListRegions" in out
    assert TEST_ACCOUNT not in out


def test_r2_allregions_an_installed_boto3_without_the_call_cannot_list_regions(tmp_path, monkeypatch, capsys):
    fake = FakeAccount()
    old = OlderBoto3Client(real_client("account"), {"ListRegions"})
    code, out = run(["--all-regions"], MixedFactory(fake, {"account": old}), capsys, tmp_path, monkeypatch)
    assert code == 2 and "could not list Regions" in result_line(out)


@pytest.mark.parametrize(
    "response",
    [{}, {"Regions": None}, {"Regions": []}, {"Regions": [{"RegionName": "ap-east-1", "RegionOptStatus": "DISABLED"}]},
     {"Regions": [{"RegionOptStatus": "ENABLED"}]}, {"Regions": ["us-east-1"]}],
)
def test_r2_allregions_a_listing_with_no_enabled_region_in_it_is_not_a_listing(response, tmp_path, monkeypatch, capsys):
    code, out = run(["--all-regions"], FakeAccount({("account", "list_regions"): response}), capsys, tmp_path, monkeypatch)
    assert code == 2 and "could not list Regions" in result_line(out), out


def test_r2_allregions_a_region_without_a_status_is_audited_and_an_odd_name_is_set_aside(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("account", "list_regions"): {"Regions": [
        {"RegionName": "us-east-1", "RegionOptStatus": "ENABLED_BY_DEFAULT"}, {"RegionName": "eu-west-3"},
        {"RegionName": "not a region", "RegionOptStatus": "ENABLED"},
    ]}})
    code, out = run(["--all-regions"], account, capsys, tmp_path, monkeypatch)
    assert account.regions_called("sagemaker") == {"us-east-1", "eu-west-3"}
    assert code == 2 and "could not list Regions" in result_line(out)  # one entry could not be used, so the list is in doubt


def test_r2_allregions_cannot_be_combined_with_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wr, "KITS_DIR", tmp_path, raising=False)
    assert wr.main(["--only", "--region", "us-east-1", "--prefix", "kitdemo", "--all-regions"], client_factory=forbidden_factory) == 64


def test_r2_allregions_dry_run_names_the_extra_call_and_makes_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wr, "KITS_DIR", tmp_path, raising=False)
    code = wr.main(["--all-regions", "--dry-run"], client_factory=forbidden_factory)
    out = capsys.readouterr().out
    assert code == 3
    assert "account.ListRegions(MaxResults=50)" in out and "every Region" in out


def test_r2_allregions_without_the_flag_the_call_is_not_made(tmp_path, monkeypatch, capsys):
    account = FakeAccount()
    run([], account, capsys, tmp_path, monkeypatch)
    assert account.called("account", "list_regions") == []


def test_r2_allregions_json_says_what_was_listed(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("account", "list_regions"): regions_response(("us-east-1", "ENABLED_BY_DEFAULT"), ("us-west-2", "ENABLED_BY_DEFAULT"), ("ap-east-1", "DISABLED"))})
    code, out = run(["--all-regions", "--json"], account, capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert doc["all_regions"]["requested"] is True and doc["all_regions"]["listed"] is True
    assert doc["all_regions"]["enabled"] == ["us-east-1", "us-west-2"] and doc["all_regions"]["not_enabled"] == ["ap-east-1"]
    code, out = run(["--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert json.loads(out)["all_regions"]["requested"] is False


def test_r2_allregions_a_run_over_several_regions_ends_with_one_line_per_region(tmp_path, monkeypatch, capsys):
    account = FakeAccount({
        ("account", "list_regions"): regions_response(("us-east-1", "ENABLED_BY_DEFAULT"), ("us-west-2", "ENABLED_BY_DEFAULT"), ("eu-north-1", "ENABLED_BY_DEFAULT")),
        ("sagemaker", "list_endpoints", "us-west-2"): ENDPOINT,
        ("s3vectors", "list_vector_buckets", "eu-north-1"): failure_kinds()["no-endpoint"](),
    })
    code, out = run(["--all-regions"], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    block = out.split("PER REGION")[1].split("SUMMARY")[0]
    assert "us-east-1: every check ran, nothing found" in block
    assert "us-west-2: 1 item(s) found" in block
    assert "eu-north-1: 1 check(s) could not run" in block


# ==========================================================  MINOR 10
def test_r2_minor10_after_teardown_with_only_free_leftovers_of_that_kit_is_not_exit_0(tmp_path, monkeypatch, capsys):
    # The reviewer's U08: the endpoint and its log group are gone, the configuration and the model remain.
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    account = FakeAccount({
        ("sagemaker", "list_endpoint_configs"): {"EndpointConfigs": [{"EndpointConfigName": "kitdemo-kita-config-20261007-124247"}]},
        ("sagemaker", "list_models"): {"Models": [{"ModelName": "kitdemo-kita-model-20261007-124247"}]},
    })
    code, out = run(["--after-teardown", "a"], account, capsys, tmp_path, monkeypatch)
    assert found_rows(out) == 2
    assert code == 2
    line = result_line(out)
    assert "NOT CLEAN (exit 2)" in line
    assert "2 of kit A's resource type(s) were FOUND" in line
    assert "kit A's own clean check" in line and "would say NOT CLEAN" in line and "99_verify_clean.py" in line
    assert NOTHING not in out
    # without --after-teardown nothing changes: these two carry no idle charge, and the full listing shows them
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 0 and "BILLS WHILE IDLE: NO | SageMaker model: kitdemo-kita-model-20261007-124247" in out


def test_r2_minor10_kit_b_knowledge_base_data_source_and_guardrail_left_is_not_exit_0(tmp_path, monkeypatch, capsys):
    # The reviewer's U08b.
    account = FakeAccount({
        ("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": [{"knowledgeBaseId": "KB0001", "name": "kitdemo-fedrag-kb", "status": "ACTIVE"}]},
        ("bedrock-agent", "get_knowledge_base"): {"knowledgeBase": {"knowledgeBaseId": "KB0001", "knowledgeBaseConfiguration": {"type": "VECTOR"}, "storageConfiguration": {"type": "S3_VECTORS"}}},
        ("bedrock-agent", "list_data_sources"): {"dataSourceSummaries": [{"dataSourceId": "DS1", "name": "kitdemo-fedrag-s3-source", "status": "AVAILABLE"}]},
        ("bedrock", "list_guardrails"): {"guardrails": [{"id": "gr0004", "name": "kitdemo-fedrag-grounding", "version": "DRAFT", "status": "READY"}]},
    })
    code, out = run(["--after-teardown", "b"], account, capsys, tmp_path, monkeypatch)
    assert found_rows(out) == 3 and code == 2
    assert "3 of kit B's resource type(s) were FOUND" in result_line(out) and "would say NOT CLEAN" in result_line(out)
    # the same leftovers seen from kit A's screen are not kit A's: exit 0 there
    code, out = run(["--after-teardown", "a"], account, capsys, tmp_path, monkeypatch)
    assert code == 0 and "[FOUND]" not in out


def test_r2_minor10_ignore_storage_only_does_not_hide_a_found_row_from_the_exit_code(tmp_path, monkeypatch, capsys):
    # The reviewer's U04, third command: --ignore-storage-only --after-teardown b with kit B's bucket left.
    account = FakeAccount({("s3", "list_buckets"): {"Buckets": [{"Name": f"kitdemo-fedrag-corpus-{TEST_ACCOUNT}-us-east-1"}]}})
    code, out = run(["--ignore-storage-only", "--after-teardown", "b"], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    line = result_line(out)
    assert line.startswith("RESULT: LIMITED CHECK: ") and "NOT CLEAN (exit 2)" in line and "1 of kit B's resource type(s) were FOUND" in line


def test_r2_minor10_json_carries_the_reason_and_the_count(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("sagemaker", "list_models"): {"Models": [{"ModelName": "kitdemo-kita-model-1"}]}})
    code, out = run(["--after-teardown", "a", "--json"], account, capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert code == 2 and doc["exit_code"] == 2 and doc["verdict"] == "not clean"
    assert "kit leftover found" in doc["verdict_reasons"]
    assert doc["after_teardown"]["rows_found"] == 1


def test_r2_minor10_a_clean_screen_is_still_exit_0(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    for kit, unseen in (("a", 1), ("b", 2), ("c", 5)):
        code, out = run(["--after-teardown", kit], FakeAccount(), capsys, tmp_path, monkeypatch)
        line = result_line(out)
        assert code == 0 and "[FOUND]" not in out and NOTHING in line
        # The reviewer's U08c: roles, log deliveries and a workload identity can be left where this audit
        # cannot look. Exit 0 here must not be taken for the kit's own clean check.
        assert line.startswith(f"RESULT: {unseen} of kit {kit.upper()}'s resource types cannot be checked by this audit")
        assert "does not replace that kit's own clean check (python 99_verify_clean.py" in line
        assert line.index("cannot be checked") < line.index(NOTHING)


def test_r2_minor10_every_checked_row_says_whether_the_kits_own_check_counts_it():
    for kit, resources in wr.KIT_COVERAGE.items():
        for resource in resources:
            assert isinstance(resource.own_check, bool)
    # the one row a kit's own check does not count: the Transaction Search log group, which kit C does not
    # create and its 99_verify_clean.py prints as information only
    not_counted = [r.label for r in wr.KIT_COVERAGE["c"] if r.check_id and not r.own_check]
    assert len(not_counted) == 1 and "aws/spans" in not_counted[0]


def test_r2_minor10_a_found_row_the_kits_own_check_does_not_count_is_not_claimed_for_it(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("logs", "describe_log_groups"): log_groups_like_aws(["aws/spans"])})
    code, out = run(["--after-teardown", "c"], account, capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 2 and found_rows(out) == 1
    assert "1 of kit C's resource type(s) were FOUND" in line
    assert "would say NOT CLEAN" not in line and "does not count as a leftover" in line


# ==========================================================  the budget row
def budget(name, limit="25"):
    return {"BudgetName": name, "BudgetType": "COST", "TimeUnit": "MONTHLY", "BudgetLimit": {"Amount": limit, "Unit": "USD"}}


def record_budget(monkeypatch, tmp_path, name="kitdemo-monthly-cost"):
    path = tmp_path / "common-state.json"
    path.write_text(json.dumps({"budget": {"name": name, "created_by": "aws-kits-budget-alarm", "limit_usd": "25"}}), encoding="utf-8")
    monkeypatch.setattr(wr, "BUDGET_STATE_FILE", path, raising=False)


def info_block(out):
    return out.split("INFORMATIONAL")[1].split("SUMMARY")[0]


def test_r2_budget_the_budget_this_folder_created_is_listed_as_information_and_exit_stays_0(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    record_budget(monkeypatch, tmp_path)
    account = FakeAccount({("budgets", "describe_budgets"): {"Budgets": [budget("kitdemo-monthly-cost"), budget("someone-elses", "100")]}})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 0, out
    block = info_block(out)
    assert "never changes the RESULT or the exit code" in out
    assert "kitdemo-monthly-cost: COST, MONTHLY, limit 25 USD" in block
    assert "kitdemo-monthly-cost: COST, MONTHLY, limit 25 USD. Created by budget_alarm.py (recorded in common/.state.json)" in block
    assert "budget_alarm.py --delete --i-understand-this-changes-my-account" in block
    assert "someone-elses: COST, MONTHLY, limit 100 USD" in block
    assert "free of charge" in block
    assert result_line(out).startswith(f"RESULT: {NOTHING}")
    assert "no idle charge:               0" in out  # it is not counted as a leftover of any kind
    assert account.called("budgets", "describe_budgets") == [{"AccountId": TEST_ACCOUNT, "MaxResults": 100}]
    assert TEST_ACCOUNT not in out


def test_r2_budget_without_a_record_the_tag_this_folder_sets_identifies_the_budget(tmp_path, monkeypatch, capsys):
    def tags(**kwargs):
        mine = kwargs["ResourceARN"].endswith(":budget/renamed-by-me")
        return {"ResourceTags": [{"Key": "created-by", "Value": "aws-kits-budget-alarm"}] if mine else [{"Key": "team", "Value": "x"}]}

    account = FakeAccount({
        ("budgets", "describe_budgets"): {"Budgets": [budget("renamed-by-me"), budget("other")]},
        ("budgets", "list_tags_for_resource"): tags,
    })
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    block = info_block(out)
    assert code == 0
    assert "renamed-by-me: COST, MONTHLY, limit 25 USD. Created by budget_alarm.py (it carries the tag created-by=aws-kits-budget-alarm)" in block
    assert "other: COST, MONTHLY, limit 25 USD. Not created by budget_alarm.py" in block
    arns = [kw["ResourceARN"] for kw in account.called("budgets", "list_tags_for_resource")]
    assert arns == [f"arn:aws:budgets::{TEST_ACCOUNT}:budget/renamed-by-me", f"arn:aws:budgets::{TEST_ACCOUNT}:budget/other"]
    assert TEST_ACCOUNT not in out


def test_r2_budget_calls_match_the_service_model(tmp_path, monkeypatch, capsys):
    client = real_client("budgets")
    stubber = Stubber(client)
    stubber.add_response("describe_budgets", {"Budgets": [budget("kitdemo-monthly-cost")], "NextToken": "p2"}, {"AccountId": TEST_ACCOUNT, "MaxResults": 100})
    stubber.add_response("describe_budgets", {"Budgets": [budget("b2")]}, {"AccountId": TEST_ACCOUNT, "MaxResults": 100, "NextToken": "p2"})
    stubber.add_response("list_tags_for_resource", {"ResourceTags": [{"Key": "created-by", "Value": "aws-kits-budget-alarm"}]}, {"ResourceARN": f"arn:aws:budgets::{TEST_ACCOUNT}:budget/kitdemo-monthly-cost"})
    stubber.add_client_error("list_tags_for_resource", service_error_code="AccessDeniedException", service_message="no", expected_params={"ResourceARN": f"arn:aws:budgets::{TEST_ACCOUNT}:budget/b2"})
    stubber.activate()
    code, out = run([], MixedFactory(FakeAccount(), {"budgets": client}), capsys, tmp_path, monkeypatch)
    stubber.assert_no_pending_responses()
    block = info_block(out)
    assert code == 0
    assert "kitdemo-monthly-cost" in block and "Created by budget_alarm.py" in block
    assert "b2: COST, MONTHLY, limit 25 USD. Its tags could not be read" in block


def test_r2_budget_no_budget_at_all_is_said_and_is_not_a_reason_for_not_clean(tmp_path, monkeypatch, capsys):
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 0
    assert "[budget] AWS Budgets in this account: none" in info_block(out) and "budget_alarm.py" in info_block(out)


@pytest.mark.parametrize("kind", sorted(failure_kinds()))
def test_r2_budget_a_budget_call_that_fails_never_changes_the_exit_code(kind, tmp_path, monkeypatch, capsys):
    for dirty in (False, True):
        handlers = {("budgets", "describe_budgets"): failure_kinds()[kind]()}
        if dirty:
            handlers[("sagemaker", "list_endpoints")] = ENDPOINT
        code, out = run([], FakeAccount(handlers), capsys, tmp_path, monkeypatch)
        assert code == (2 if dirty else 0), kind
        assert "[budget] AWS Budgets in this account: COULD NOT READ" in out, kind
        assert "COULD NOT CHECK" not in out and "Traceback" not in out, kind
        assert "checks that could not run:    0" in out


def test_r2_budget_a_failing_tag_call_of_any_kind_leaves_the_row_and_the_exit_code(tmp_path, monkeypatch, capsys):
    for kind, make in failure_kinds().items():
        account = FakeAccount({("budgets", "describe_budgets"): {"Budgets": [budget("b1")]}, ("budgets", "list_tags_for_resource"): make()})
        code, out = run([], account, capsys, tmp_path, monkeypatch)
        assert code == 0, kind
        assert "b1: COST, MONTHLY, limit 25 USD. Its tags could not be read" in out, kind


def test_r2_budget_when_the_account_is_unknown_the_budget_row_is_not_read(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("sts", "get_caller_identity"): client_error("ExpiredToken", "expired")})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2 and account.called("budgets", "describe_budgets") == []
    assert "[budget] AWS Budgets in this account: COULD NOT READ" in out


def test_r2_budget_the_row_is_on_the_after_teardown_screen_in_json_and_in_the_dry_run(tmp_path, monkeypatch, capsys):
    record_budget(monkeypatch, tmp_path)
    account = FakeAccount({("budgets", "describe_budgets"): {"Budgets": [budget("kitdemo-monthly-cost")]}})
    code, out = run(["--after-teardown", "b"], account, capsys, tmp_path, monkeypatch)
    assert code == 0 and "kitdemo-monthly-cost: COST, MONTHLY, limit 25 USD" in info_block(out)
    code, out = run(["--json"], account, capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert code == 0
    assert doc["informational"]["budgets"]["status"] == "ok"
    assert doc["informational"]["budgets"]["affects_exit_code"] is False
    assert doc["informational"]["budgets"]["budgets"] == [{"name": "kitdemo-monthly-cost", "type": "COST", "time_unit": "MONTHLY", "limit": "25 USD", "created_by_budget_alarm": "yes (recorded in common/.state.json)"}]
    assert doc["summary"]["no"] == 0
    code = wr.main(["--dry-run"], client_factory=forbidden_factory)
    out = capsys.readouterr().out
    assert "[budget] budgets.DescribeBudgets(AccountId=<your account id>, MaxResults=100)" in out


def test_r2_budget_a_damaged_budget_record_does_not_break_the_audit(tmp_path, monkeypatch, capsys):
    path = tmp_path / "common-state.json"
    path.write_text('{"budget": {"name": ', encoding="utf-8")
    monkeypatch.setattr(wr, "BUDGET_STATE_FILE", path, raising=False)
    account = FakeAccount({("budgets", "describe_budgets"): {"Budgets": [budget("kitdemo-monthly-cost")]}})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 0 and "kitdemo-monthly-cost" in info_block(out)


def test_r2_budget_show_marks_the_budget_it_created_and_points_to_the_audit_row(tmp_path):
    from test_budget_alarm import ACCOUNT, StubbedBudgets, identity

    state = tmp_path / ".state.json"
    state.write_text(json.dumps({"budget": {"name": "kitdemo-monthly-cost"}}), encoding="utf-8")
    factory = StubbedBudgets(
        [identity()],
        [
            ("describe_budgets", {"Budgets": [budget("kitdemo-monthly-cost"), budget("another-budget", "100")]}, {"AccountId": ACCOUNT, "MaxResults": 100}),
            ("describe_notifications_for_budget", {"Notifications": []}, {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost", "MaxResults": 100}),
            ("describe_notifications_for_budget", {"Notifications": []}, {"AccountId": ACCOUNT, "BudgetName": "another-budget", "MaxResults": 100}),
        ],
    )
    lines: list[str] = []
    code = ba.main(["--show"], client_factory=factory, out=lines.append, state_path=state)
    out = "\n".join(lines)
    assert code == 0
    mine = out.split("kitdemo-monthly-cost:")[1].split("another-budget:")[0]
    assert "this is the budget budget_alarm.py created" in mine
    assert "this is the budget budget_alarm.py created" not in out.split("another-budget:")[1]
    assert "whats_running.py" in out and "INFORMATIONAL" in out and "never changes its result" in out
    factory.assert_all_calls_made()


def test_r2_budget_show_copes_with_a_budget_record_of_the_wrong_shape(tmp_path):
    from test_budget_alarm import ACCOUNT, StubbedBudgets, identity

    state = tmp_path / ".state.json"
    state.write_text(json.dumps({"budget": "kitdemo-monthly-cost"}), encoding="utf-8")  # a text where an object should be
    factory = StubbedBudgets(
        [identity()],
        [
            ("describe_budgets", {"Budgets": [budget("kitdemo-monthly-cost")]}, {"AccountId": ACCOUNT, "MaxResults": 100}),
            ("describe_notifications_for_budget", {"Notifications": []}, {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost", "MaxResults": 100}),
        ],
    )
    lines: list[str] = []
    assert ba.main(["--show"], client_factory=factory, out=lines.append, state_path=state) == 0
    assert "this is the budget budget_alarm.py created" not in "\n".join(lines)


def test_r2_budget_show_points_to_the_audit_row_even_when_there_is_no_budget(tmp_path):
    from test_budget_alarm import ACCOUNT, StubbedBudgets, identity

    factory = StubbedBudgets([identity()], [("describe_budgets", {"Budgets": []}, {"AccountId": ACCOUNT, "MaxResults": 100})])
    lines: list[str] = []
    assert ba.main(["--show"], client_factory=factory, out=lines.append, state_path=tmp_path / ".state.json") == 0
    assert "whats_running.py" in "\n".join(lines)


# ==========================================================  U03: --only
def test_r2_u03_only_starts_the_result_line_with_the_limit_in_capitals(tmp_path, monkeypatch, capsys):
    # The reviewer's U03: kit A is alive in us-west-2 and the owner asks for us-east-1 only.
    three_kits(tmp_path, a=good_state(region="us-west-2"))
    account = FakeAccount({("sagemaker", "list_endpoints", "us-west-2"): ENDPOINT})
    code, out = run(["--only", "--region", "us-east-1", "--prefix", "kitdemo"], account, capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0  # what the flag asks for; the line must make it impossible to take for a clean account
    assert line.startswith("RESULT: LIMITED CHECK: THE KIT FOLDERS WERE NOT READ (--only)")
    assert line.index("LIMITED CHECK") < line.index("nothing")
    assert "ONLY THE REGIONS AND PREFIXES YOU NAMED WERE AUDITED" in line
    assert "Regions us-east-1;" in line


def test_r2_u03_only_starts_a_not_clean_result_the_same_way(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("sagemaker", "list_endpoints", "us-west-2"): ENDPOINT})
    code, out = run(["--only", "--region", "us-west-2", "--prefix", "kitdemo"], account, capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 2
    assert line.startswith("RESULT: LIMITED CHECK: THE KIT FOLDERS WERE NOT READ (--only)") and "NOT CLEAN (exit 2)" in line
    code, out = run(["--only", "--region", "us-west-2", "--prefix", "kitdemo", "--after-teardown", "a"], account, capsys, tmp_path, monkeypatch)
    assert code == 2 and result_line(out).startswith("RESULT: LIMITED CHECK: ")


def test_r2_u03_json_carries_the_limit(tmp_path, monkeypatch, capsys):
    code, out = run(["--only", "--region", "us-east-1", "--prefix", "kitdemo", "--ignore-storage-only", "--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert len(doc["limited_check"]) == 2 and doc["result_line"].startswith("RESULT: LIMITED CHECK: ")
    code, out = run(["--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert json.loads(out)["limited_check"] == []


def test_r2_u03_a_run_without_either_flag_is_not_called_limited(tmp_path, monkeypatch, capsys):
    code, out = run(["--region", "us-west-2"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert "LIMITED CHECK" not in out


# ==========================================================  U04, U04b: --ignore-storage-only
def storage_account():
    return FakeAccount({
        ("s3", "list_buckets"): {"Buckets": [{"Name": f"kitdemo-fedrag-corpus-{TEST_ACCOUNT}-us-east-1"}, {"Name": f"kitdemo-kitc-code-{TEST_ACCOUNT}-us-east-1"}]},
        ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [RUNTIME_SUMMARY]},
    })


def test_r2_u04_ignore_storage_only_starts_the_result_line_with_the_limit_in_capitals(tmp_path, monkeypatch, capsys):
    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    code, out = run(["--ignore-storage-only"], storage_account(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0  # what the flag asks for
    assert line.startswith("RESULT: LIMITED CHECK: STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only)")
    assert "3 OF THEM REMAIN" in line
    assert line.index("LIMITED CHECK") < line.index("nothing")
    # U04b: the runtime that remains can have an open session, which bills compute and cannot be listed
    assert "1 AGENTCORE RUNTIME(S) REMAIN AND THEIR OPEN SESSIONS CANNOT BE LISTED" in line
    assert line.index("OPEN SESSIONS CANNOT BE LISTED") < line.index("nothing")


def test_r2_u04_the_flag_is_named_first_even_when_it_ignored_nothing_or_the_result_is_not_clean(tmp_path, monkeypatch, capsys):
    code, out = run(["--ignore-storage-only"], FakeAccount(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0 and line.startswith("RESULT: LIMITED CHECK: STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only)")
    assert "NONE WAS FOUND THIS TIME" in line
    code, out = run(["--ignore-storage-only"], FakeAccount({("sagemaker", "list_endpoints"): ENDPOINT}), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 2 and line.startswith("RESULT: LIMITED CHECK: ") and "NOT CLEAN (exit 2)" in line


def test_r2_u04_both_flags_are_both_named_before_anything_else(tmp_path, monkeypatch, capsys):
    code, out = run(["--only", "--region", "us-east-1", "--prefix", "kitdemo", "--ignore-storage-only"], storage_account(), capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0
    assert line.startswith("RESULT: LIMITED CHECK: ")
    first = line.index("nothing")
    assert line.index("(--only)") < first and line.index("(--ignore-storage-only)") < first


def test_r2_u04_without_the_flag_storage_is_not_clean_and_the_line_is_not_called_limited(tmp_path, monkeypatch, capsys):
    code, out = run([], storage_account(), capsys, tmp_path, monkeypatch)
    assert code == 2 and "LIMITED CHECK" not in out


def test_r2_allregions_readme_states_the_calls_one_region_costs(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    three_kits(tmp_path, a=good_state(), b=good_state(), c=good_state())
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    per_region = [call for call in account.calls if call[0] not in ("sts", "budgets", "account")]
    once = sorted(f"{call[0]}.{call[1]}" for call in account.calls if call[0] in ("sts", "budgets", "account"))
    assert code == 0 and once == ["budgets.describe_budgets", "sts.get_caller_identity"]
    readme = (Path(wr.__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    assert f"{len(per_region)} read-only calls per Region in an account with nothing in it, so {len(per_region) * 17} calls for the 17 Regions" in readme


# ==========================================================  the README states what is true
def test_r2_readme_carries_the_dated_round_2_line_and_the_minute_the_kits_were_read():
    import re
    from pathlib import Path

    readme = (Path(wr.__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    match = re.search(r"Reviewed independently a second time on 2026-10-07 \(round 2\): (\d+) findings for this folder, (\d+) fixed, (\d+) left open \(listed below\)", readme)
    assert match, "the dated round 2 line is missing"
    findings, fixed, left_open = (int(n) for n in match.groups())
    assert findings == fixed + left_open
    assert re.search(r"read on 2026-10-07 at \d{2}:\d{2} UTC", readme), "the README must say the minute the kit code was read"
    for flag in ("--all-regions", "LIMITED CHECK", "no state file"):
        assert flag in readme
