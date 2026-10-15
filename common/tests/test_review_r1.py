"""Tests written from the round 1 independent review (2026-10-07).

Each BLOCKER and MAJOR has at least one test here that failed on the code as
reviewed and passes now. The test names start with the finding id. Offline:
no network, no credentials, no AWS call.
"""
from __future__ import annotations

import json
import re

import botocore.session
import pytest

import whats_running as wr
from helpers import TEST_ACCOUNT, EMPTY_RESPONSES, FakeAccount, client_error, log_groups_like_aws

OTHER_ACCOUNT = "444455556666"  # a second AWS documentation placeholder account id


def make_kit(root, name, config=None, example=None, state=None):
    """Create a sibling kit folder the way a kit leaves it on disk."""
    kit = root / name
    kit.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (kit / "config.env").write_text(config, encoding="utf-8")
    if example is not None:
        (kit / "config.example.env").write_text(example, encoding="utf-8")
    if state is not None:
        (kit / ".state.json").write_text(state if isinstance(state, str) else json.dumps(state), encoding="utf-8")
    return kit


def run(argv, account, capsys, kits=None, monkeypatch=None):
    if kits is not None:
        monkeypatch.setattr(wr, "KITS_DIR", kits, raising=False)
    code = wr.main(list(argv), client_factory=account)
    return code, capsys.readouterr().out


def result_line(out):
    return next(line for line in out.splitlines() if line.startswith("RESULT"))


# =====================================================================  B1
def test_b1_region_from_a_kit_config_env_is_audited_even_when_the_command_names_another(tmp_path, monkeypatch, capsys):
    # The reviewer's scenario D: the kit ran in us-west-2, the kit README says --region us-east-1.
    make_kit(tmp_path, "kit_a_gpu_endpoint", config="AWS_REGION=us-west-2\nKIT_PREFIX=kitdemo\n")
    endpoint = {"Endpoints": [{"EndpointName": "kitdemo-kita-endpoint", "EndpointStatus": "InService"}]}
    account = FakeAccount({("sagemaker", "list_endpoints", "us-west-2"): endpoint})
    code, out = run(["--region", "us-east-1"], account, capsys, tmp_path, monkeypatch)
    assert {"us-east-1", "us-west-2"} <= account.regions_called("sagemaker")
    assert code == 2
    assert "SageMaker endpoint: kitdemo-kita-endpoint" in out
    assert "us-west-2" in result_line(out) and "us-east-1" in result_line(out)


def test_b1_prefix_from_a_kit_config_env_finds_that_kits_log_groups(tmp_path, monkeypatch, capsys):
    # The reviewer's scenario C: KIT_PREFIX=acme is set only in the kit's config.env.
    make_kit(tmp_path, "kit_c_langgraph_agentcore", config="KIT_PREFIX=acme\n")
    groups = ["/aws/lambda/acme-something", "/unrelated/group"]
    account = FakeAccount({("logs", "describe_log_groups"): log_groups_like_aws(groups)})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "CloudWatch log group: /aws/lambda/acme-something" in out
    assert "/unrelated/group" not in out
    assert "acme" in result_line(out)


def test_b1_hyphenated_prefix_still_finds_the_underscore_named_runtime_log_group(tmp_path, monkeypatch, capsys):
    # The reviewer's scenario B: kit C names the runtime my_kit_kitc_fr_agent for KIT_PREFIX=my-kit.
    group = "/custom/my_kit_kitc_fr_agent-AbCdEf1234-DEFAULT"
    account = FakeAccount({("logs", "describe_log_groups"): log_groups_like_aws([group])})
    code, out = run(["--prefix", "my-kit"], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert f"CloudWatch log group: {group}" in out


@pytest.mark.parametrize(
    "group",
    [
        "/aws/sagemaker/Endpoints/acme-kita-endpoint",
        "/aws/bedrock-agentcore/runtimes/my_kit_kitc_fr_agent-AbCdEf1234-DEFAULT",
        "/aws/vendedlogs/bedrock-agentcore/acme-kitc-usage",
        "aws/spans",
    ],
)
def test_b1_service_log_groups_are_found_whatever_the_prefix(group, tmp_path, monkeypatch, capsys):
    # No kit folder, no --prefix: the audit knows only the default prefix "kitdemo".
    account = FakeAccount({("logs", "describe_log_groups"): log_groups_like_aws([group, "/someone/elses"])})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert f"CloudWatch log group: {group}" in out
    assert "/someone/elses" not in out


def test_b1_state_file_and_its_history_add_regions_and_prefixes(tmp_path, monkeypatch, capsys):
    state = {
        "kit": "kit-a-gpu-endpoint", "region": "us-west-2", "prefix": "second", "account_id": TEST_ACCOUNT,
        "resources": [{"type": "endpoint", "name": "third-kita-endpoint", "arn": f"arn:aws:sagemaker:ap-southeast-2:{TEST_ACCOUNT}:endpoint/third-kita-endpoint"}],
        "history": [{"region": "eu-west-1", "prefix": "first", "hours": 1.5}],
    }
    make_kit(tmp_path, "kit_a_gpu_endpoint", state=state)
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert {"us-west-2", "eu-west-1", "ap-southeast-2", "us-east-1"} <= account.regions_called("sagemaker")
    line = result_line(out)
    for expected in ("us-west-2", "eu-west-1", "ap-southeast-2", "first", "second", "third", "kitdemo"):
        assert expected in line, expected
    assert code == 0


def test_b1_config_example_env_defaults_are_read(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, "kit_b_federal_rag_eval", example="# comment\nAWS_REGION=eu-central-1\nKIT_PREFIX=fromexample\n")
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert "eu-central-1" in account.regions_called("bedrock")
    assert "fromexample" in result_line(out) and "eu-central-1" in result_line(out)


@pytest.mark.parametrize(
    "state_text, clean",
    [
        (None, True),                                             # missing
        ("{}", True),                                             # written, nothing in it
        ('{"unexpected": {"nested": [1, 2, {"deep": null}]}, "region": 7, "prefix": ["x"]}', True),  # keys and types not expected
        ("null", True),
        ("", False),                                              # empty file: a write that was cut short
        ('{"region": "us-west-2", "prefix": "cutoff", "resources": [{"arn": "arn:aws:sagemaker:eu-west-1:', False),  # cut short
        ("\x00\x01 not json at all", False),
    ],
)
def test_b1_state_files_are_read_defensively(state_text, clean, tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, "kit_a_gpu_endpoint", config="AWS_REGION=us-east-1\n", state=state_text)
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)  # must not raise
    assert "Traceback" not in out
    if clean:
        assert code == 0, out
    else:
        assert code == 2, out
        assert "kit_a_gpu_endpoint/.state.json" in out and "could not be read" in out
        assert "nothing that bills while idle was found" not in out
    if state_text and "cutoff" in state_text:  # what could be salvaged from the broken file is still audited
        assert {"us-west-2", "eu-west-1"} <= account.regions_called("sagemaker")
        assert "cutoff" in result_line(out)


def test_b1_command_line_adds_to_what_was_discovered_and_only_replaces_it(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, "kit_a_gpu_endpoint", config="AWS_REGION=us-west-2\nKIT_PREFIX=fromkit\n")
    account = FakeAccount()
    code, out = run(["--region", "eu-west-1", "--prefix", "typed"], account, capsys, tmp_path, monkeypatch)
    assert {"us-west-2", "eu-west-1"} <= account.regions_called("sagemaker")
    assert "fromkit" in result_line(out) and "typed" in result_line(out)

    account = FakeAccount()
    code, out = run(["--only", "--region", "eu-west-1", "--prefix", "typed"], account, capsys, tmp_path, monkeypatch)
    assert account.regions_called("sagemaker") == {"eu-west-1"}
    line = result_line(out)
    assert "eu-west-1" in line and "typed" in line and "us-west-2" not in line and "fromkit" not in line
    assert "--only" in out  # the output says the kit folders were not read


def test_b1_only_without_an_explicit_region_and_prefix_is_a_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wr, "KITS_DIR", tmp_path, raising=False)
    assert wr.main(["--only"], client_factory=FakeAccount()) == 64
    assert wr.main(["--only", "--region", "us-east-1"], client_factory=FakeAccount()) == 64


def test_b1_result_line_names_every_region_and_prefix_and_the_account_by_last_four_only(tmp_path, monkeypatch, capsys):
    account = FakeAccount()
    code, out = run(["--region", "us-east-1,us-west-2", "--prefix", "acme"], account, capsys, tmp_path, monkeypatch)
    line = result_line(out)
    assert code == 0
    assert "account ending 3333" in line
    assert "us-east-1" in line and "us-west-2" in line and "acme" in line and "kitdemo" in line
    assert TEST_ACCOUNT not in out  # the full account id never reaches the screen

    code, out = run(["--region", "us-east-1,us-west-2", "--prefix", "acme", "--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert doc["audited"]["account_last4"] == "3333"
    assert set(doc["audited"]["regions"]) == {"us-east-1", "us-west-2"}
    assert set(doc["audited"]["prefixes"]) == {"acme", "kitdemo"}
    assert TEST_ACCOUNT not in out


@pytest.mark.parametrize(
    "state",
    [
        {"region": "us-east-1", "prefix": "kitdemo", "account_id": OTHER_ACCOUNT},
        {"region": "us-east-1", "account": OTHER_ACCOUNT},
        {"account_last4": OTHER_ACCOUNT[-4:]},
        {"runtime_arn": f"arn:aws:bedrock-agentcore:us-east-1:{OTHER_ACCOUNT}:runtime/kitdemo_kitc_fr_agent-abc"},
        {"bucket": f"kitdemo-kitc-code-{OTHER_ACCOUNT}-us-east-1"},
        {"history": [{"account_id": OTHER_ACCOUNT}]},
    ],
)
def test_b1_a_kit_state_that_names_another_account_is_not_clean(state, tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, "kit_c_langgraph_agentcore", state=state)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    line = result_line(out)
    assert "NOT CLEAN" in line
    assert "account ending 6666" in out and "account ending 3333" in out
    assert OTHER_ACCOUNT not in out and TEST_ACCOUNT not in out


def test_b1_a_kit_state_that_names_the_callers_account_stays_clean(tmp_path, monkeypatch, capsys):
    state = {"account_id": TEST_ACCOUNT, "bucket": f"kitdemo-kitc-code-{TEST_ACCOUNT}-us-east-1", "account_last4": TEST_ACCOUNT[-4:]}
    make_kit(tmp_path, "kit_c_langgraph_agentcore", state=state)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 0, out


def test_b1_another_account_with_the_same_last_four_digits_is_still_another_account(tmp_path, monkeypatch, capsys):
    lookalike = "9999" + TEST_ACCOUNT[4:]
    make_kit(tmp_path, "kit_b_federal_rag_eval", state={"account_id": lookalike, "region": "us-east-1", "prefix": "kitdemo"})
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "a different account that ends in the same four digits" in out
    assert lookalike not in out


def test_b1_the_keys_the_three_kits_write_today_are_all_read(tmp_path, monkeypatch, capsys):
    # region, prefix and account_id at the top level and in each history entry (kit A, B and C on 2026-10-07).
    for name, region, prefix in (("kit_a_gpu_endpoint", "us-west-2", "alpha"), ("kit_b_federal_rag_eval", "eu-west-1", "bravo"), ("kit_c_langgraph_agentcore", "us-east-2", "charlie")):
        make_kit(tmp_path, name, state={
            "region": region, "prefix": prefix, "account_id": TEST_ACCOUNT,
            "history": [{"region": "ap-northeast-1", "prefix": f"old-{prefix}", "account_id": TEST_ACCOUNT, "verified_clean_at": "2026-10-07T00:00:00Z"}],
        })
    account = FakeAccount()
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 0
    assert account.regions_called("logs") == {"us-west-2", "eu-west-1", "us-east-2", "ap-northeast-1", "us-east-1"}
    for prefix in ("alpha", "bravo", "charlie", "old-alpha", "old-bravo", "old-charlie", "kitdemo"):
        assert prefix in result_line(out)
    assert TEST_ACCOUNT not in out


def test_b1_when_the_account_cannot_be_named_the_verdict_is_not_clean(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("sts", "get_caller_identity"): client_error("ExpiredToken", "The security token included in the request is expired")})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "account unknown" in result_line(out)
    assert "COULD NOT CHECK" in out


# =====================================================================  B2
RUNTIME_SUMMARY = {"agentRuntimeName": "kitdemo_kitc_fr_agent", "agentRuntimeId": "kitdemo_kitc_fr_agent-abc", "agentRuntimeVersion": "1", "status": "READY"}


def runtime_detail(**changes):
    detail = {
        "agentRuntimeId": "kitdemo_kitc_fr_agent-abc", "agentRuntimeName": "kitdemo_kitc_fr_agent", "status": "READY",
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 120, "maxLifetime": 900},
        "agentRuntimeArtifact": {"codeConfiguration": {"runtime": "PYTHON_3_13", "entryPoint": ["agentcore_app.py"]}},
    }
    detail.update(changes)
    return detail


@pytest.mark.parametrize("status", ["CREATING", "CREATE_FAILED", "UPDATING", "UPDATE_FAILED", "READY", "DELETING", "DELETE_FAILED"])
def test_b2_a_deployed_code_runtime_is_storage_only_and_never_exit_0(status, tmp_path, monkeypatch, capsys):
    account = FakeAccount({
        ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [dict(RUNTIME_SUMMARY, status=status)]},
        ("bedrock-agentcore-control", "get_agent_runtime"): runtime_detail(status=status),
    })
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "BILLS WHILE IDLE: STORAGE ONLY | AgentCore runtime: kitdemo_kitc_fr_agent" in out
    assert "BILLS WHILE IDLE: NO | AgentCore runtime" not in out
    assert "direct code deployment bills for the size of the code artifacts you deployed at S3 Standard rates" in out
    assert account.called("bedrock-agentcore-control", "get_agent_runtime") == [{"agentRuntimeId": "kitdemo_kitc_fr_agent-abc"}]


def test_b2_a_runtime_on_instances_is_rated_yes(tmp_path, monkeypatch, capsys):
    detail = runtime_detail(capacityProviderConfiguration={"capacityProviderArn": f"arn:aws:bedrock-agentcore:us-east-1:{TEST_ACCOUNT}:capacity-provider/cp-1"})
    account = FakeAccount({
        ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [RUNTIME_SUMMARY]},
        ("bedrock-agentcore-control", "get_agent_runtime"): detail,
    })
    code, out = run(["--ignore-storage-only"], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "BILLS WHILE IDLE: YES | AgentCore runtime: kitdemo_kitc_fr_agent" in out
    assert "Charged per instance-hour from provisioning (boot) until the instance is stopped or terminated" in out
    assert TEST_ACCOUNT not in out  # the capacity provider ARN is not printed with the account id


def test_b2_a_container_runtime_names_the_ecr_storage(tmp_path, monkeypatch, capsys):
    detail = runtime_detail(agentRuntimeArtifact={"containerConfiguration": {"containerUri": "example.invalid/repo:tag"}})
    account = FakeAccount({
        ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [RUNTIME_SUMMARY]},
        ("bedrock-agentcore-control", "get_agent_runtime"): detail,
    })
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "BILLS WHILE IDLE: STORAGE ONLY | AgentCore runtime" in out
    assert "container deployment requires ECR storage (billed separately)" in out


def test_b2_the_output_says_open_sessions_cannot_be_listed_and_gives_their_time_limits(tmp_path, monkeypatch, capsys):
    account = FakeAccount({
        ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [RUNTIME_SUMMARY]},
        ("bedrock-agentcore-control", "get_agent_runtime"): runtime_detail(),
    })
    code, out = run(["--ignore-storage-only"], account, capsys, tmp_path, monkeypatch)
    flat = " ".join(out.split())
    assert "OPEN SESSIONS CANNOT BE LISTED" in flat
    assert "idle periods, until session termination" in flat          # the pricing sentence
    assert "idle for 120 seconds" in flat and "900 seconds" in flat    # this runtime's own limits
    assert "900 seconds (15 minutes)" in flat and "28800 seconds (8 hours)" in flat  # service defaults
    assert "1209600 seconds (14 days)" in flat                         # Instances
    # Even when storage is ignored, a result that leaves a runtime behind carries the warning on the RESULT line.
    assert code == 0
    # Round 2 moved that warning to the front of the line, in capitals (see tests/test_review_r2.py, U04b).
    assert "OPEN SESSIONS CANNOT BE LISTED" in result_line(out)
    assert result_line(out).startswith("RESULT: LIMITED CHECK: ")


def test_b2_runtime_detail_that_cannot_be_read_is_could_not_check(tmp_path, monkeypatch, capsys):
    for broken in (client_error("AccessDeniedException", "not authorized to perform bedrock-agentcore:GetAgentRuntime"), {}):
        account = FakeAccount({
            ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [RUNTIME_SUMMARY]},
            ("bedrock-agentcore-control", "get_agent_runtime"): broken,
        })
        code, out = run(["--ignore-storage-only"], account, capsys, tmp_path, monkeypatch)
        assert code == 2
        line = next(l for l in out.splitlines() if "AgentCore runtimes" in l)
        assert "COULD NOT CHECK" in line


def test_b2_the_installed_boto3_really_has_no_call_that_lists_runtime_sessions():
    session = botocore.session.get_session()
    for service in ("bedrock-agentcore", "bedrock-agentcore-control"):
        names = session.get_service_model(service).operation_names
        offenders = [n for n in names if n.startswith(("List", "Describe", "Get")) and "RuntimeSession" in n]
        assert not offenders, f"{service} now has {offenders}: the audit could list sessions; update check_ac_runtimes"
    # ListSessions exists, but it is the memory API: its request needs a memory id and an actor id.
    list_sessions = session.get_service_model("bedrock-agentcore").operation_model("ListSessions")
    assert {"memoryId", "actorId"} <= set(list_sessions.input_shape.required_members)


# =====================================================================  B3
def buckets_account(names, tags=None, contents=None, extra=None):
    tags = tags or {}
    contents = contents or {}

    def tagging(**kw):
        if kw["Bucket"] not in tags:
            return client_error("NoSuchTagSet", "The TagSet does not exist", "GetBucketTagging", 404)
        value = tags[kw["Bucket"]]
        return value if isinstance(value, BaseException) else {"TagSet": [{"Key": k, "Value": v} for k, v in value.items()]}

    def versions(**kw):
        return contents.get(kw["Bucket"], {})

    handlers = {
        ("s3", "list_buckets"): {"Buckets": [{"Name": n, "BucketRegion": "us-east-1"} for n in names]},
        ("s3", "get_bucket_tagging"): tagging,
        ("s3", "list_object_versions"): versions,
    }
    handlers.update(extra or {})
    return FakeAccount(handlers)


def test_b3_kit_buckets_are_found_by_name_pattern_whatever_the_prefix(tmp_path, monkeypatch, capsys):
    corpus = f"acme-fedrag-corpus-{TEST_ACCOUNT}-us-east-1"
    code_bucket = f"other-kitc-code-{TEST_ACCOUNT}-us-east-1"
    account = buckets_account(
        [corpus, code_bucket, "someone-elses-bucket"],
        contents={corpus: {"Versions": [{"Key": "corpus/a.txt", "VersionId": "null"}]}},
    )
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "BILLS WHILE IDLE: STORAGE ONLY | S3 bucket: acme-fedrag-corpus-[account ending 3333]-us-east-1" in out
    assert "BILLS WHILE IDLE: STORAGE ONLY | S3 bucket: other-kitc-code-[account ending 3333]-us-east-1" in out
    assert "someone-elses-bucket" not in out
    assert TEST_ACCOUNT not in out
    corpus_state = out.split("S3 bucket: acme-fedrag-corpus")[1].split("why:")[0]
    code_state = out.split("S3 bucket: other-kitc-code")[1].split("why:")[0]
    assert "not empty" in corpus_state
    assert "empty" in code_state and "not empty" not in code_state
    assert account.called("s3", "list_buckets") == [{"BucketRegion": "us-east-1", "MaxBuckets": 1000}]
    # read-only and cheap: one listing call of one key per kit bucket, nothing else
    assert sorted(kw["Bucket"] for kw in account.called("s3", "list_object_versions")) == sorted([corpus, code_bucket])
    assert all(kw["MaxKeys"] == 1 for kw in account.called("s3", "list_object_versions"))


def test_b3_a_bucket_is_found_by_the_project_tag_even_with_an_unrelated_name(tmp_path, monkeypatch, capsys):
    account = buckets_account(
        ["renamed-by-hand", "tagged-for-something-else", "untagged"],
        tags={"renamed-by-hand": {"project": "aws-kits", "kit": "kit-c"}, "tagged-for-something-else": {"project": "payroll"}},
    )
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "S3 bucket: renamed-by-hand" in out and "tag project=aws-kits" in out
    assert "tagged-for-something-else" not in out and "untagged" not in out


def test_b3_a_bucket_with_the_audited_prefix_is_found(tmp_path, monkeypatch, capsys):
    account = buckets_account(["acme-something-new", "acmeother"])
    code, out = run(["--prefix", "acme"], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "S3 bucket: acme-something-new" in out and "acmeother" not in out


def test_b3_no_buckets_of_the_kits_is_clean_and_storage_can_be_ignored(tmp_path, monkeypatch, capsys):
    code, out = run([], buckets_account(["someone-elses-bucket"]), capsys, tmp_path, monkeypatch)
    assert code == 0
    assert "S3 buckets" in out
    corpus = f"kitdemo-fedrag-corpus-{TEST_ACCOUNT}-us-east-1"
    code, out = run(["--ignore-storage-only"], buckets_account([corpus]), capsys, tmp_path, monkeypatch)
    assert code == 0 and "S3 bucket: kitdemo-fedrag-corpus" in out


def test_b3_tags_that_cannot_be_read_make_the_check_could_not_check(tmp_path, monkeypatch, capsys):
    denied = client_error("AccessDenied", "Access Denied", "GetBucketTagging", 403)
    account = buckets_account(["locked-bucket", "plain"], tags={"locked-bucket": denied})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    line = next(l for l in out.splitlines() if "S3 buckets" in l)
    assert "COULD NOT CHECK" in line and "locked-bucket" in line


def test_b3_bucket_listing_failure_or_contents_failure_is_never_silent(tmp_path, monkeypatch, capsys):
    account = FakeAccount({("s3", "list_buckets"): client_error("AccessDenied", "Access Denied", "ListBuckets", 403)})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2 and "COULD NOT CHECK" in next(l for l in out.splitlines() if "S3 buckets" in l)

    corpus = f"kitdemo-fedrag-corpus-{TEST_ACCOUNT}-us-east-1"
    account = buckets_account([corpus], contents={corpus: client_error("AccessDenied", "Access Denied", "ListObjectVersions", 403)})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "S3 bucket: kitdemo-fedrag-corpus" in out and "could not tell whether it is empty" in out


def test_b3_bucket_listing_follows_the_continuation_token(tmp_path, monkeypatch, capsys):
    pages = {
        None: {"Buckets": [], "ContinuationToken": "t1"},
        "t1": {"Buckets": [{"Name": "kitdemo-kitc-code-x"}]},
    }
    account = FakeAccount({("s3", "list_buckets"): lambda **kw: pages[kw.get("ContinuationToken")]})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2 and "S3 bucket: kitdemo-kitc-code-x" in out


# =====================================================================  M1
def kb_account(kb_detail):
    return FakeAccount({
        ("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": [{"knowledgeBaseId": "KB12345678", "name": "kitdemo-fedrag-kb", "status": "ACTIVE"}]},
        ("bedrock-agent", "get_knowledge_base"): {"knowledgeBase": kb_detail},
    })


@pytest.mark.parametrize(
    "kb_type, store, expected",
    [
        ("VECTOR", "S3_VECTORS", "NO"),                    # the store is listed by the S3 Vectors check
        ("VECTOR", "OPENSEARCH_SERVERLESS", "NO"),         # the store is listed by the OpenSearch Serverless check
        ("VECTOR", "RDS", "UNKNOWN"),
        ("VECTOR", "NEPTUNE_ANALYTICS", "UNKNOWN"),
        ("VECTOR", "OPENSEARCH_MANAGED_CLUSTER", "UNKNOWN"),
        ("VECTOR", "PINECONE", "UNKNOWN"),
        ("VECTOR", None, "UNKNOWN"),
        ("KENDRA", None, "UNKNOWN"),
        ("SQL", None, "UNKNOWN"),
        (None, None, "UNKNOWN"),
        ("MANAGED", None, "STORAGE ONLY"),
    ],
)
def test_m1_knowledge_base_is_no_only_when_its_store_is_listed_elsewhere(kb_type, store, expected, tmp_path, monkeypatch, capsys):
    detail = {"knowledgeBaseId": "KB12345678", "name": "kitdemo-fedrag-kb"}
    if kb_type:
        detail["knowledgeBaseConfiguration"] = {"type": kb_type}
    if store:
        detail["storageConfiguration"] = {"type": store}
    code, out = run([], kb_account(detail), capsys, tmp_path, monkeypatch)
    assert f"BILLS WHILE IDLE: {expected} | Bedrock knowledge base: kitdemo-fedrag-kb" in out
    assert code == (0 if expected == "NO" else 2)


# =====================================================================  M2
LIST_CALLS = sorted(
    key for key, response in EMPTY_RESPONSES.items()
    if key[1].startswith(("list_", "describe_")) and key not in {("s3", "list_object_versions")}
)
# Calls only made when a parent resource exists.
PARENTS = {
    ("bedrock-agent", "list_data_sources"): {("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": [{"knowledgeBaseId": "KB1", "name": "n", "status": "ACTIVE"}]}},
    ("s3vectors", "list_indexes"): {("s3vectors", "list_vector_buckets"): {"vectorBuckets": [{"vectorBucketName": "vb"}]}},
}


@pytest.mark.parametrize("key", LIST_CALLS, ids=[f"{s}.{m}" for s, m in LIST_CALLS])
@pytest.mark.parametrize("shape", ["missing", "none"])
def test_m2_a_list_response_without_its_list_key_is_could_not_check(key, shape, tmp_path, monkeypatch, capsys):
    list_key = next(iter(EMPTY_RESPONSES[key]))
    handlers = dict(PARENTS.get(key, {}))
    handlers[key] = {} if shape == "missing" else {list_key: None}
    # --ignore-storage-only so that the parent items above cannot be what makes the result not clean
    code, out = run(["--ignore-storage-only"], FakeAccount(handlers), capsys, tmp_path, monkeypatch)
    assert code == 2, out
    assert "COULD NOT CHECK" in out
    assert "nothing that bills while idle was found" not in out


@pytest.mark.parametrize("response", [{}, {"knowledgeBase": {}}, {"knowledgeBase": None}])
def test_m2_an_empty_get_knowledge_base_is_could_not_check_not_no(response, tmp_path, monkeypatch, capsys):
    account = kb_account({})
    account.handlers[("bedrock-agent", "get_knowledge_base")] = response
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "COULD NOT CHECK" in next(l for l in out.splitlines() if "Bedrock knowledge bases" in l)
    assert "BILLS WHILE IDLE: NO | Bedrock knowledge base:" not in out


def test_m2_batch_get_collection_without_details_is_could_not_check(tmp_path, monkeypatch, capsys):
    account = FakeAccount({
        ("opensearchserverless", "list_collections"): {"collectionSummaries": [{"id": "c1", "name": "n", "status": "ACTIVE"}]},
        ("opensearchserverless", "batch_get_collection"): {},
    })
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "COULD NOT CHECK" in next(l for l in out.splitlines() if "OpenSearch Serverless collections" in l)
    assert "BILLS WHILE IDLE: YES | OpenSearch Serverless collection: n (c1)" in out  # still shown, still the expensive reading


# =====================================================================  M3
ALL_BUT_LOGS = ["sagemaker", "bedrock", "opensearch", "s3vectors", "agentcore", "ecr"]


def test_m3_skipping_checks_makes_exit_0_impossible(tmp_path, monkeypatch, capsys):
    # The reviewer's scenario F: an InService endpoint exists, six families are skipped.
    endpoint = {"Endpoints": [{"EndpointName": "kitdemo-kita-endpoint", "EndpointStatus": "InService"}]}
    argv = [arg for family in ALL_BUT_LOGS for arg in ("--skip", family)]
    code, out = run(argv, FakeAccount({("sagemaker", "list_endpoints"): endpoint}), capsys, tmp_path, monkeypatch)
    assert code == 2
    line = result_line(out)
    assert "NOT CLEAN" in line and "skipped" in line
    assert "nothing that bills while idle was found" not in out


def test_m3_one_skipped_family_in_an_empty_account_is_still_not_exit_0(tmp_path, monkeypatch, capsys):
    code, out = run(["--skip", "ecr"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert out.count("SKIPPED, not checked") == 1
    assert "skipped" in result_line(out)


def test_m3_json_carries_a_skipped_verdict(tmp_path, monkeypatch, capsys):
    code, out = run(["--skip", "ecr", "--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert code == 2 and doc["exit_code"] == 2
    assert doc["verdict"] == "skipped"
    assert "skipped" in doc["verdict_reasons"]
    assert doc["skipped"]["count"] == 1 and doc["skipped"]["checks"][0]["check_id"] == "ecr"

    code, out = run(["--json"], FakeAccount(), capsys, tmp_path, monkeypatch)
    doc = json.loads(out)
    assert code == 0 and doc["verdict"] == "clean" and doc["verdict_reasons"] == [] and doc["skipped"]["count"] == 0


def test_m3_exit_0_needs_every_check_in_every_region_to_have_run():
    ok = wr.CheckResult("a", "sagemaker", "t", "us-east-1", wr.STATUS_OK)
    skipped = wr.CheckResult("b", "ecr", "t", "us-west-2", wr.STATUS_SKIPPED)
    assert wr.decide_exit([ok]) == 0
    assert wr.decide_exit([ok, skipped]) == 2
    assert wr.decide_exit([ok, skipped], ignore_storage_only=True) == 2
    assert wr.decide_exit([]) == 2


# ============================================  every call, every kind of failure
# The reviewer injected one failure at a time into every call (286 cases, all exit 2).
# The same idea, kept here so that it also covers the calls added since.
EVERY_CALL = sorted(EMPTY_RESPONSES)
CALL_PARENTS = dict(PARENTS)
CALL_PARENTS.update({
    ("bedrock-agent", "get_knowledge_base"): {("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": [{"knowledgeBaseId": "KB1", "name": "n", "status": "ACTIVE"}]}},
    ("opensearchserverless", "batch_get_collection"): {("opensearchserverless", "list_collections"): {"collectionSummaries": [{"id": "c1", "name": "n", "status": "ACTIVE"}]}},
    ("s3", "get_bucket_tagging"): {("s3", "list_buckets"): {"Buckets": [{"Name": "not-a-kit-name"}]}},
    ("s3", "list_object_versions"): {("s3", "list_buckets"): {"Buckets": [{"Name": "kitdemo-kitc-code-x"}]}},
    ("bedrock-agentcore-control", "get_agent_runtime"): {("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [RUNTIME_SUMMARY]}},
})


def _failures():
    from helpers import failure_kinds

    return failure_kinds()


@pytest.mark.parametrize("key", EVERY_CALL, ids=[f"{s}.{m}" for s, m in EVERY_CALL])
def test_one_failing_call_of_any_kind_never_leaves_exit_0(key, tmp_path, monkeypatch, capsys):
    for label, make in _failures().items():
        handlers = dict(CALL_PARENTS.get(key, {}))
        handlers[key] = make()
        code, out = run([], FakeAccount(handlers), capsys, tmp_path, monkeypatch)
        assert code == 2, f"{key} {label}: exit {code}"
        assert "nothing that bills while idle was found" not in out, f"{key} {label}"
        if key == ("s3", "list_object_versions"):
            # by design not a failed check: the bucket is listed, and the line says its contents are unknown
            assert "could not tell whether it is empty" in out, label
        else:
            assert "COULD NOT CHECK" in out, f"{key} {label}"
        assert "Traceback" not in out


def test_real_clients_without_credentials_or_network_report_every_check_as_could_not_check(capsys):
    # The real client factory. conftest.py removes credentials and makes any socket use fail the test.
    code = wr.main([])
    out = capsys.readouterr().out
    assert code == 2
    assert out.count("COULD NOT CHECK") == len(wr.CHECKS) + 1  # every check, and the caller identity
    assert "none found" not in out
    assert "account unknown" in result_line(out)


# ================================================  small things found while fixing B1
def test_b1_identity_is_asked_in_the_next_region_when_the_first_one_does_not_answer(tmp_path, monkeypatch, capsys):
    # A mistyped Region in a config file must not turn into "account unknown".
    make_kit(tmp_path, "kit_a_gpu_endpoint", config="AWS_REGION=us-esat-1\n")
    import botocore.exceptions as bex

    account = FakeAccount({("sts", "get_caller_identity", "us-esat-1"): bex.EndpointConnectionError(endpoint_url="https://sts.us-esat-1.amazonaws.com")})
    code, out = run([], account, capsys, tmp_path, monkeypatch)
    assert "account ending 3333" in result_line(out)
    assert [region for service, _m, region, _kw in account.calls if service == "sts"] == ["us-esat-1", "us-east-1"]


def test_b1_a_state_file_that_cannot_be_opened_is_not_clean_and_its_path_is_not_printed(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, "kit_b_federal_rag_eval", state={"region": "us-east-1"})
    real = wr._read_local_file

    def denied(path):
        if path.name == ".state.json":
            raise PermissionError(13, "Permission denied", str(path))
        return real(path)

    monkeypatch.setattr(wr, "_read_local_file", denied)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2
    assert "kit_b_federal_rag_eval/.state.json could not be read (PermissionError: Permission denied)" in out
    assert str(tmp_path) not in out


def test_b1_a_state_file_too_large_to_be_a_state_file_is_not_clean(tmp_path, monkeypatch, capsys):
    make_kit(tmp_path, "kit_b_federal_rag_eval", state={"region": "us-west-2", "padding": "x" * 5000})
    monkeypatch.setattr(wr, "MAX_LOCAL_FILE_BYTES", 1000)
    code, out = run([], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert code == 2 and "could not be read" in out and "larger than 1000 bytes" in out
