"""Offline tests for whats_running.py. No network, no credentials, no AWS call."""
from __future__ import annotations

import datetime as dt
import json

import botocore.exceptions as bex
import pytest

import whats_running as wr
from helpers import (
    Err, FakeAccount, OlderBoto3Client, RaisingClient, StubbedAccount, client_error, empty_plan, forbidden_factory,
    log_group_steps, real_client,
)

T0 = dt.datetime(2026, 10, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
ARN = "arn:aws:sagemaker:us-east-1:111122223333"


def endpoint(name: str, status: str = "InService") -> dict:
    return {"EndpointName": name, "EndpointArn": f"{ARN}:endpoint/{name}", "CreationTime": T0, "LastModifiedTime": T0, "EndpointStatus": status}


def run(argv, account, capsys):
    code = wr.main(argv, client_factory=account)
    return code, capsys.readouterr().out


def result_for(results, check_id):
    return next(r for r in results if r.check_id == check_id)


def audit(account, regions=("us-east-1",), prefixes=("kitdemo",), skip=()):
    """What main() does, without the command line: name the account, then run every check."""
    _identity, identity_result = wr.check_identity(account, regions[0])
    return [identity_result] + wr.run_audit(list(regions), list(prefixes), account, tuple(skip))


def text_for(results, regions=("us-east-1",), prefixes=("kitdemo",), ignore_storage_only=False):
    scope = wr.build_scope(regions, prefixes, True, wr.KITS_DIR)
    return wr.render_text(results, scope, wr.Identity("111122223333"), ignore_storage_only)


# ---------------------------------------------------------------- exit codes
def test_empty_account_exits_0_and_makes_every_call(capsys):
    account = StubbedAccount(empty_plan())
    code, out = run([], account, capsys)
    assert code == 0
    assert "COULD NOT CHECK" not in out
    assert out.count("none found") == len(wr.CHECKS)
    assert "nothing that bills while idle was found" in out
    account.assert_all_calls_made()


def test_running_endpoint_exits_2(capsys):
    plan = empty_plan()
    plan["sm_endpoints"] = ("sagemaker", [("list_endpoints", {"Endpoints": [endpoint("kitdemo-ep")]}, {"MaxResults": 100})])
    code, out = run([], StubbedAccount(plan), capsys)
    assert code == 2
    assert "BILLS WHILE IDLE: YES | SageMaker endpoint: kitdemo-ep [kit prefix]" in out
    assert "created: 2026-10-01T12:00:00Z | state: InService" in out
    assert "RESULT: NOT CLEAN (exit 2)" in out
    assert "docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-delete-resources.html (read 2026-10-07)" in out


def test_items_that_do_not_bill_idle_keep_exit_0(capsys):
    plan = empty_plan()
    plan["sm_models"] = ("sagemaker", [("list_models", {"Models": [{"ModelName": "m1", "ModelArn": f"{ARN}:model/m1", "CreationTime": T0}]}, {"MaxResults": 100})])
    plan["br_guardrails"] = (
        "bedrock",
        [("list_guardrails", {"guardrails": [{"id": "g1", "arn": "arn:aws:bedrock:us-east-1:111122223333:guardrail/g1", "status": "READY", "name": "kitdemo-guard", "version": "DRAFT", "createdAt": T0, "updatedAt": T0}]}, {"maxResults": 100})],
    )
    code, out = run([], StubbedAccount(plan), capsys)
    assert code == 0
    assert "BILLS WHILE IDLE: NO | SageMaker model: m1" in out
    assert "BILLS WHILE IDLE: NO | Bedrock guardrail: kitdemo-guard" in out


def test_storage_only_exits_2_unless_ignored(capsys):
    plan = empty_plan()
    plan["ecr"] = (
        "ecr",
        [("describe_repositories", {"repositories": [{"repositoryName": "kitdemo-agent", "createdAt": T0}, {"repositoryName": "someone-elses-repo", "createdAt": T0}]}, {"maxResults": 100})],
    )
    code, out = run([], StubbedAccount(plan), capsys)
    assert code == 2
    assert "BILLS WHILE IDLE: STORAGE ONLY | ECR repository: kitdemo-agent" in out
    assert "someone-elses-repo" not in out  # only names that carry the kit prefix
    assert "storage is still being billed" in out

    code, out = run(["--ignore-storage-only"], StubbedAccount(plan), capsys)
    assert code == 0
    # Round 2: the flag's limit opens the RESULT line, in capitals (see tests/test_review_r2.py, U04).
    assert "RESULT: LIMITED CHECK: STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only): 1 OF THEM REMAIN" in out


def test_unknown_billing_is_treated_as_not_clean(capsys):
    plan = empty_plan()
    plan["sm_notebooks"] = (
        "sagemaker",
        [("list_notebook_instances", {"NotebookInstances": [{"NotebookInstanceName": "nb", "NotebookInstanceArn": f"{ARN}:notebook-instance/nb", "NotebookInstanceStatus": "Stopped", "CreationTime": T0}]}, {"MaxResults": 100})],
    )
    code, out = run(["--ignore-storage-only"], StubbedAccount(plan), capsys)
    assert code == 2
    assert "BILLS WHILE IDLE: UNKNOWN | SageMaker notebook instance: nb" in out
    assert "UNVERIFIED" in out


def test_bad_command_line_exits_64_not_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        wr.main(["--no-such-flag"], client_factory=forbidden_factory)
    assert excinfo.value.code == 64


def test_decide_exit_is_not_clean_when_nothing_completed():
    skipped = [wr.CheckResult("x", "sagemaker", "t", "us-east-1", wr.STATUS_SKIPPED)]
    assert wr.decide_exit(skipped) == 2
    assert wr.decide_exit([]) == 2


# ------------------------------------------- "could not check" is never clean
def test_access_denied_is_could_not_check_never_none_found(capsys):
    plan = empty_plan()
    plan["ac_gateways"] = ("bedrock-agentcore-control", [("list_gateways", Err("AccessDeniedException", "not authorized to perform bedrock-agentcore:ListGateways", 403), {"maxResults": 100})])
    account = StubbedAccount(plan)
    results = audit(account)
    gw = result_for(results, "ac_gateways")
    assert gw.status == wr.STATUS_COULD_NOT_CHECK
    assert "AccessDeniedException" in gw.reason and "ListGateways" in gw.reason
    assert wr.decide_exit(results) == 2
    out = text_for(results)
    line = next(l for l in out.splitlines() if "AgentCore gateways" in l)
    assert "COULD NOT CHECK" in line and "none found" not in line
    assert "nothing that bills while idle was found" not in out
    assert "some checks could not run, so this is NOT a clean result" in out
    # the other checks still ran
    assert result_for(results, "ac_memories").status == wr.STATUS_OK
    account.assert_all_calls_made()


def test_could_not_check_stays_exit_2_even_with_ignore_storage_only(capsys):
    plan = empty_plan()
    plan["log_groups"] = ("logs", [("describe_log_groups", Err("AccessDeniedException", "denied", 400), {"logGroupNamePrefix": "/aws/sagemaker/Endpoints/", "limit": 50})])
    code, out = run(["--ignore-storage-only"], StubbedAccount(plan), capsys)
    assert code == 2
    assert "COULD NOT CHECK" in out


def test_service_missing_from_installed_boto3_is_could_not_check():
    account = StubbedAccount(empty_plan(), skip_checks=("s3vectors",))
    account.overrides["s3vectors"] = bex.UnknownServiceError(service_name="s3vectors", known_service_names="s3, sts")
    results = audit(account)
    r = result_for(results, "s3vectors")
    assert r.status == wr.STATUS_COULD_NOT_CHECK
    assert "not in the installed boto3" in r.reason
    assert wr.decide_exit(results) == 2


def test_operation_missing_from_installed_boto3_is_could_not_check():
    account = StubbedAccount(empty_plan(), skip_checks=("ac_runtimes", "ac_gateways", "ac_memories"))
    account.overrides["bedrock-agentcore-control"] = OlderBoto3Client(
        real_client("bedrock-agentcore-control"), {"ListAgentRuntimes", "ListGateways", "ListMemories"}
    )
    results = audit(account)
    for check_id in ("ac_runtimes", "ac_gateways", "ac_memories"):
        r = result_for(results, check_id)
        assert r.status == wr.STATUS_COULD_NOT_CHECK
        assert "is not in the installed boto3" in r.reason
    assert wr.decide_exit(results) == 2


def test_service_not_in_region_is_could_not_check():
    account = StubbedAccount(empty_plan(), skip_checks=("s3vectors",))
    account.overrides["s3vectors"] = RaisingClient(
        real_client("s3vectors"), "list_vector_buckets", bex.EndpointConnectionError(endpoint_url="https://s3vectors.example-region.api.aws")
    )
    results = audit(account)
    r = result_for(results, "s3vectors")
    assert r.status == wr.STATUS_COULD_NOT_CHECK
    assert "no endpoint could be reached" in r.reason
    assert wr.decide_exit(results) == 2


def test_no_credentials_is_could_not_check_for_every_check():
    class NoCreds(StubbedAccount):
        def __call__(self, service, region):
            real = real_client(service)
            return _AlwaysRaise(real, bex.NoCredentialsError())

    results = audit(NoCreds({}))
    assert len(results) == len(wr.CHECKS) + 1  # every check, and the caller identity
    assert all(r.status == wr.STATUS_COULD_NOT_CHECK for r in results)
    assert all("no usable AWS credentials" in r.reason for r in results)
    assert wr.decide_exit(results) == 2


class _AlwaysRaise:
    def __init__(self, real, exc):
        self._exc = exc
        self.meta = real.meta

    def __getattr__(self, name):
        def raiser(**kwargs):
            raise self._exc
        return raiser


def test_unexpected_response_shape_is_could_not_check():
    class Weird:
        def __init__(self, real):
            self.meta = real.meta

        def list_vector_buckets(self, **kwargs):
            return {"somethingElse": []}  # required key 'vectorBuckets' is missing

    account = StubbedAccount(empty_plan(), skip_checks=("s3vectors",))
    account.overrides["s3vectors"] = Weird(real_client("s3vectors"))
    results = audit(account)
    r = result_for(results, "s3vectors")
    assert r.status == wr.STATUS_COULD_NOT_CHECK
    assert "vectorBuckets" in r.reason


def test_a_crashing_check_is_could_not_check_not_a_traceback():
    def boom(ctx):
        raise KeyError("EndpointName")
        yield  # pragma: no cover

    check = wr.Check("boom", "sagemaker", "Boom", ("none",), boom)
    result = wr.run_check(check, wr.Context("us-east-1", "kitdemo", forbidden_factory))
    assert result.status == wr.STATUS_COULD_NOT_CHECK
    assert "unexpected response shape" in result.reason


def test_skipped_family_is_reported_as_skipped_and_is_never_exit_0(capsys):
    account = StubbedAccount(empty_plan(), skip_checks=("ac_runtimes", "ac_gateways", "ac_memories"))
    code, out = run(["--skip", "agentcore"], account, capsys)
    assert code == 2
    assert out.count("SKIPPED, not checked") == 3
    assert "nothing that bills while idle was found" not in out
    assert "3 check(s) were skipped and say nothing" in out
    assert ("bedrock-agentcore-control", "us-east-1") not in account.requested
    account.assert_all_calls_made()


# ----------------------------------------------------------------- pagination
def test_pagination_follows_next_token_on_list_endpoints(capsys):
    plan = empty_plan()
    plan["sm_endpoints"] = (
        "sagemaker",
        [
            ("list_endpoints", {"Endpoints": [endpoint("ep-page-1")], "NextToken": "tok-1"}, {"MaxResults": 100}),
            ("list_endpoints", {"Endpoints": [endpoint("ep-page-2")], "NextToken": "tok-2"}, {"MaxResults": 100, "NextToken": "tok-1"}),
            ("list_endpoints", {"Endpoints": [endpoint("ep-page-3")]}, {"MaxResults": 100, "NextToken": "tok-2"}),
        ],
    )
    account = StubbedAccount(plan)
    results = audit(account)
    names = [i.name for i in result_for(results, "sm_endpoints").items]
    assert names == ["ep-page-1", "ep-page-2", "ep-page-3"]
    account.assert_all_calls_made()


def test_failure_on_a_later_page_keeps_what_was_seen_and_is_could_not_check():
    plan = empty_plan()
    plan["sm_endpoints"] = (
        "sagemaker",
        [
            ("list_endpoints", {"Endpoints": [endpoint("ep-page-1")], "NextToken": "tok-1"}, {"MaxResults": 100}),
            ("list_endpoints", Err("ThrottlingException", "Rate exceeded"), {"MaxResults": 100, "NextToken": "tok-1"}),
        ],
    )
    results = audit(StubbedAccount(plan))
    r = result_for(results, "sm_endpoints")
    assert r.status == wr.STATUS_COULD_NOT_CHECK
    assert [i.name for i in r.items] == ["ep-page-1"]
    out = text_for(results)
    assert "listing is incomplete; 1 item(s) seen before it failed" in out


def test_repeated_pagination_token_does_not_loop_for_ever():
    class Looping:
        def __init__(self, real):
            self.meta = real.meta
            self.calls = 0

        def list_memories(self, **kwargs):
            self.calls += 1
            return {"memories": [], "nextToken": "same"}

    looping = Looping(real_client("bedrock-agentcore-control"))
    with pytest.raises(wr.CouldNotCheck, match="pagination token repeated"):
        list(wr._paginate(looping, "ListMemories", "memories", maxResults=100))
    assert looping.calls == 2


# ------------------------------------------------------ nested and loud cases
def test_opensearch_classic_collection_gets_loud_warning_with_minimum_charge(capsys):
    plan = empty_plan()
    plan["aoss_collections"] = (
        "opensearchserverless",
        [
            ("list_collections", {"collectionSummaries": [{"id": "abc123", "name": "kitdemo-kb", "status": "ACTIVE"}], "nextToken": "n1"}, {"maxResults": 100}),
            ("list_collections", {"collectionSummaries": [{"id": "def456", "name": "kitdemo-next", "status": "ACTIVE", "collectionGroupName": "nextgen-kitdemo-next"}]}, {"maxResults": 100, "nextToken": "n1"}),
            (
                "list_collection_groups",
                {"collectionGroupSummaries": [{"id": "grp001", "name": "nextgen-kitdemo-next", "generation": "NEXTGEN", "numberOfCollections": 1, "createdDate": 1790000000000, "capacityLimits": {"minIndexingCapacityInOCU": 0.0, "minSearchCapacityInOCU": 0.0}}]},
                {"maxResults": 100},
            ),
            (
                "batch_get_collection",
                {"collectionDetails": [
                    {"id": "abc123", "name": "kitdemo-kb", "status": "ACTIVE", "type": "VECTORSEARCH", "standbyReplicas": "ENABLED", "createdDate": 1790000000000},
                    {"id": "def456", "name": "kitdemo-next", "status": "ACTIVE", "type": "VECTORSEARCH", "createdDate": 1790000000000, "collectionGroupName": "nextgen-kitdemo-next"},
                ]},
                {"ids": ["abc123", "def456"]},
            ),
        ],
    )
    plan["aoss_collection_groups"] = ("opensearchserverless", [])  # served from the cache, no second call
    account = StubbedAccount(plan)
    code, out = run([], account, capsys)
    assert code == 2
    assert "!!! WARNING: OpenSearch Serverless collection(s) that bill with zero queries" in out
    assert "You will be billed at least for a minimum of 2 OCUs" in out
    assert "$0.48 per hour" in out and "$11.52 per day" in out
    assert "aws.amazon.com/opensearch-service/pricing/ (read 2026-10-07)" in out
    assert "BILLS WHILE IDLE: YES | OpenSearch Serverless collection: kitdemo-kb (abc123)" in out
    assert "BILLS WHILE IDLE: STORAGE ONLY | OpenSearch Serverless collection: kitdemo-next (def456)" in out
    assert "BILLS WHILE IDLE: NO | OpenSearch Serverless collection group: nextgen-kitdemo-next (grp001)" in out
    assert "created: 2026-09-21T" in out  # epoch milliseconds were converted
    account.assert_all_calls_made()


def test_opensearch_generation_unreadable_is_treated_as_classic():
    plan = empty_plan()
    plan["aoss_collections"] = (
        "opensearchserverless",
        [
            ("list_collections", {"collectionSummaries": [{"id": "abc123", "name": "kbx", "status": "ACTIVE", "collectionGroupName": "grp"}]}, {"maxResults": 100}),
            ("list_collection_groups", Err("AccessDeniedException", "denied"), {"maxResults": 100}),
            ("batch_get_collection", {"collectionDetails": [{"id": "abc123", "name": "kbx", "standbyReplicas": "DISABLED", "createdDate": 1790000000000}]}, {"ids": ["abc123"]}),
        ],
    )
    plan["aoss_collection_groups"] = ("opensearchserverless", [])
    results = audit(StubbedAccount(plan))
    coll = result_for(results, "aoss_collections")
    assert coll.status == wr.STATUS_OK
    assert coll.items[0].bills_idle == wr.BILLS_YES
    assert "treated as Classic" in coll.items[0].why and "$0.24 per hour" in coll.items[0].why
    groups = result_for(results, "aoss_collection_groups")
    assert groups.status == wr.STATUS_COULD_NOT_CHECK  # the failed group listing is reported, not hidden


def test_knowledge_base_reports_vector_store_and_data_sources():
    plan = empty_plan()
    plan["br_knowledge_bases"] = (
        "bedrock-agent",
        [
            ("list_knowledge_bases", {"knowledgeBaseSummaries": [{"knowledgeBaseId": "KB12345678", "name": "kitdemo-kb", "status": "ACTIVE", "updatedAt": T0}]}, {"maxResults": 100}),
            (
                "get_knowledge_base",
                {"knowledgeBase": {
                    "knowledgeBaseId": "KB12345678", "name": "kitdemo-kb", "knowledgeBaseArn": "arn:aws:bedrock:us-east-1:111122223333:knowledge-base/KB12345678",
                    "roleArn": "arn:aws:iam::111122223333:role/kitdemo-kb-role", "status": "ACTIVE", "createdAt": T0, "updatedAt": T0,
                    "knowledgeBaseConfiguration": {"type": "VECTOR"}, "storageConfiguration": {"type": "OPENSEARCH_SERVERLESS"},
                }},
                {"knowledgeBaseId": "KB12345678"},
            ),
            ("list_data_sources", {"dataSourceSummaries": [{"knowledgeBaseId": "KB12345678", "dataSourceId": "DS12345678", "name": "corpus", "status": "AVAILABLE", "updatedAt": T0}]}, {"knowledgeBaseId": "KB12345678", "maxResults": 100}),
        ],
    )
    account = StubbedAccount(plan)
    results = audit(account)
    items = result_for(results, "br_knowledge_bases").items
    assert [i.kind for i in items] == ["Bedrock knowledge base", "Bedrock knowledge base data source"]
    assert "OPENSEARCH_SERVERLESS" in items[0].state and "BILLS SEPARATELY" in items[0].why
    assert items[0].created == "2026-10-01T12:00:00Z"
    assert items[1].created.startswith("not returned by this API")
    account.assert_all_calls_made()


def test_s3_vectors_lists_indexes_per_bucket():
    plan = empty_plan()
    plan["s3vectors"] = (
        "s3vectors",
        [
            ("list_vector_buckets", {"vectorBuckets": [{"vectorBucketName": "kitdemo-vectors", "vectorBucketArn": "arn:aws:s3vectors:us-east-1:111122223333:bucket/kitdemo-vectors", "creationTime": T0}]}, {"maxResults": 500}),
            ("list_indexes", {"indexes": [{"vectorBucketName": "kitdemo-vectors", "indexName": "main", "indexArn": "arn:aws:s3vectors:us-east-1:111122223333:bucket/kitdemo-vectors/index/main", "creationTime": T0}]}, {"vectorBucketName": "kitdemo-vectors", "maxResults": 500}),
        ],
    )
    results = audit(StubbedAccount(plan))
    items = result_for(results, "s3vectors").items
    assert [(i.kind, i.name, i.bills_idle) for i in items] == [
        ("S3 Vectors vector bucket", "kitdemo-vectors", wr.BILLS_STORAGE),
        ("S3 Vectors index", "kitdemo-vectors/main", wr.BILLS_STORAGE),
    ]


# ------------------------------------------------------- read-only and dry run
def test_dry_run_makes_no_client_and_no_call(capsys):
    code = wr.main(["--dry-run", "--regions", "us-east-1,us-west-2", "--all-regions"], client_factory=forbidden_factory)
    out = capsys.readouterr().out
    assert code == wr.EXIT_DRY_RUN == 3  # never 0: a dry run checks nothing
    assert "Exit code 3, not 0" in out
    assert "DRY RUN: no AWS call was made" in out
    assert "=== Region us-west-2" in out
    for _, operation, _ in wr.READ_OPERATIONS:
        assert operation in out


def test_call_refuses_anything_outside_the_read_only_list():
    sagemaker = real_client("sagemaker")
    with pytest.raises(wr.CouldNotCheck, match="refused"):
        wr._call(sagemaker, "DeleteEndpoint", EndpointName="x")
    with pytest.raises(wr.CouldNotCheck, match="refused"):
        wr._call(sagemaker, "CreateEndpoint", EndpointName="x", EndpointConfigName="y")


def test_every_listed_operation_is_a_read_verb():
    for _, operation, _ in wr.READ_OPERATIONS:
        assert operation.startswith(("List", "Describe", "Get", "BatchGet")), operation


def test_two_regions_are_audited_separately(capsys):
    calls = []

    class PerRegion:
        def __init__(self):
            self.accounts = {}

        def __call__(self, service, region):
            calls.append((service, region))
            self.accounts.setdefault(region, StubbedAccount(empty_plan(region=region)))
            return self.accounts[region](service, region)

    code, out = run(["--regions", "us-east-1,us-west-2"], PerRegion(), capsys)
    assert code == 0
    assert "=== Region us-east-1 ===" in out and "=== Region us-west-2 ===" in out
    assert {r for _, r in calls} == {"us-east-1", "us-west-2"}


def test_json_output_is_valid_and_carries_exit_code(capsys):
    plan = empty_plan()
    plan["sm_endpoints"] = ("sagemaker", [("list_endpoints", {"Endpoints": [endpoint("ep")]}, {"MaxResults": 100})])
    code, out = run(["--json"], StubbedAccount(plan), capsys)
    doc = json.loads(out)
    assert code == 2 and doc["exit_code"] == 2 and doc["read_only"] is True
    assert doc["summary"]["yes"] == 1
    first = next(c for c in doc["checks"] if c["check_id"] == "sm_endpoints")
    assert first["items"][0]["bills_idle"] == "yes" and first["items"][0]["source"]


def test_prefix_comes_from_flag_and_filters_log_groups(capsys):
    plan = empty_plan(prefix_forms=("acme", "kitdemo"))
    group = {"logGroupName": "/aws/lambda/acme-fn", "creationTime": 1790000000000, "storedBytes": 2048}
    plan["log_groups"] = ("logs", log_group_steps(("acme", "kitdemo"), found={4: [group]}))  # query 4 is the pattern "acme"
    account = StubbedAccount(plan)
    code, out = run(["--prefix", "acme"], account, capsys)
    assert code == 2
    assert "CloudWatch log group: /aws/lambda/acme-fn [kit prefix]" in out
    assert "2048 bytes stored, retention not set" in out
    account.assert_all_calls_made()


def test_log_group_without_stored_bytes_says_so_instead_of_claiming_zero(capsys):
    plan = empty_plan()
    group = {"logGroupName": "/custom/kitdemo_agent", "creationTime": 1790000000000}
    plan["log_groups"] = ("logs", log_group_steps(found={4: [group]}))  # found by the name pattern, which returns no sizes
    code, out = run([], StubbedAccount(plan), capsys)
    assert code == 2
    assert "stored bytes and retention were not returned; the API leaves them out when listing by name pattern" in out
    assert "0 bytes" not in out


def test_empty_collection_group_does_not_bill_but_one_with_a_minimum_does():
    plan = empty_plan()
    plan["aoss_collection_groups"] = (
        "opensearchserverless",
        [(
            "list_collection_groups",
            {"collectionGroupSummaries": [
                {"id": "grp001", "name": "empty-group", "generation": "NEXTGEN", "numberOfCollections": 0, "capacityLimits": {"minIndexingCapacityInOCU": 2.0, "minSearchCapacityInOCU": 2.0}},
                {"id": "grp002", "name": "busy-group", "generation": "NEXTGEN", "numberOfCollections": 1, "capacityLimits": {"minIndexingCapacityInOCU": 2.0, "minSearchCapacityInOCU": 0.0}},
            ]},
            {"maxResults": 100},
        )],
    )
    results = audit(StubbedAccount(plan))
    by_name = {i.name: i.bills_idle for i in result_for(results, "aoss_collection_groups").items}
    assert by_name == {"empty-group (grp001)": wr.BILLS_NO, "busy-group (grp002)": wr.BILLS_YES}
    assert wr.decide_exit(results) == 2


def test_opensearch_rate_note_names_the_region_or_says_it_is_a_floor():
    assert "in us-east-1" in wr.aoss_rate_note("us-east-1")
    assert "LOWEST rate" in wr.aoss_rate_note("eu-west-1")


# ------------------------------------------------ round 1 review: MINOR 5, training jobs
def job(name, status, warm=None):
    summary = {"TrainingJobName": name, "TrainingJobArn": f"{ARN}:training-job/{name}", "CreationTime": T0, "TrainingJobStatus": status}
    if warm:
        summary["WarmPoolStatus"] = {"Status": warm}
    return summary


def test_minor5_stopping_jobs_and_retained_warm_pools_are_seen(capsys):
    plan = empty_plan()
    jobs = [
        job("running", "InProgress"), job("stopping", "Stopping"), job("done", "Completed"), job("failed", "Failed"),
        job("done-warm", "Completed", "Available"), job("done-warm-inuse", "Completed", "InUse"),
        job("done-pool-ended", "Completed", "Terminated"), job("done-pool-reused", "Stopped", "Reused"),
    ]
    plan["sm_training_jobs"] = ("sagemaker", [("list_training_jobs", {"TrainingJobSummaries": jobs}, {"MaxResults": 100})])
    account = StubbedAccount(plan)
    results = audit(account)
    items = {i.name: i for i in result_for(results, "sm_training_jobs").items}
    assert sorted(items) == ["done-warm", "done-warm-inuse", "running", "stopping"]
    assert all(i.bills_idle == wr.BILLS_YES for i in items.values())
    assert items["stopping"].kind == "SageMaker training job in progress"
    assert items["done-warm"].kind == "SageMaker training job with a retained warm pool"
    assert "SageMaker AI managed warm pools are a billable resource." in items["done-warm"].why
    account.assert_all_calls_made()  # one unfiltered listing: no StatusEquals, so no status is missed


def test_minor5_a_training_job_status_this_audit_does_not_know_is_unknown_not_ignored():
    account = FakeAccount({("sagemaker", "list_training_jobs"): {"TrainingJobSummaries": [{"TrainingJobName": "odd", "TrainingJobStatus": "SomethingNew"}, {"TrainingJobName": "nostatus"}]}})
    results = audit(account)
    assert {i.name: i.bills_idle for i in result_for(results, "sm_training_jobs").items} == {"odd": wr.BILLS_UNKNOWN, "nostatus": wr.BILLS_UNKNOWN}
    assert wr.decide_exit(results) == 2


# ------------------------------- new calls, with shapes validated by botocore's Stubber
def test_s3_bucket_calls_match_the_service_model(capsys):
    plan = empty_plan()
    kit_bucket = "kitdemo-fedrag-corpus-111122223333-us-east-1"
    plan["s3_buckets"] = (
        "s3",
        [
            ("list_buckets", {"Buckets": [{"Name": "plain", "CreationDate": T0, "BucketRegion": "us-east-1"}], "ContinuationToken": "next"}, {"BucketRegion": "us-east-1", "MaxBuckets": 1000}),
            (
                "list_buckets",
                {"Buckets": [{"Name": kit_bucket, "CreationDate": T0, "BucketRegion": "us-east-1"}, {"Name": "tagged", "CreationDate": T0, "BucketRegion": "us-east-1"}]},
                {"BucketRegion": "us-east-1", "MaxBuckets": 1000, "ContinuationToken": "next"},
            ),
            ("get_bucket_tagging", Err("NoSuchTagSet", "The TagSet does not exist", 404), {"Bucket": "plain"}),
            ("list_object_versions", {"Versions": [{"Key": "corpus/doc-0001.txt", "VersionId": "null", "IsLatest": True, "Size": 10}]}, {"Bucket": kit_bucket, "MaxKeys": 1}),
            ("get_bucket_tagging", {"TagSet": [{"Key": "project", "Value": "aws-kits"}]}, {"Bucket": "tagged"}),
            ("list_object_versions", {"DeleteMarkers": [{"Key": "old", "VersionId": "v1", "IsLatest": True}]}, {"Bucket": "tagged", "MaxKeys": 1}),
        ],
    )
    account = StubbedAccount(plan)
    code, out = run([], account, capsys)
    assert code == 2
    assert "S3 bucket: kitdemo-fedrag-corpus-[account ending 3333]-us-east-1 [kit prefix]" in out
    assert "created: 2026-10-01T12:00:00Z | state: not empty" in out
    assert "S3 bucket: tagged" in out and "it carries the tag project=aws-kits" in out
    assert "S3 bucket: plain" not in out
    assert "111122223333" not in out
    account.assert_all_calls_made()


def test_agentcore_runtime_calls_match_the_service_model(capsys):
    plan = empty_plan()
    arn = "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/kitdemo_kitc_fr_agent-AbCdEf1234"
    summary = {"agentRuntimeArn": arn, "agentRuntimeId": "kitdemo_kitc_fr_agent-AbCdEf1234", "agentRuntimeVersion": "1", "agentRuntimeName": "kitdemo_kitc_fr_agent", "description": "kit C", "lastUpdatedAt": T0, "status": "READY"}
    detail = {
        "agentRuntimeArn": arn, "agentRuntimeName": "kitdemo_kitc_fr_agent", "agentRuntimeId": "kitdemo_kitc_fr_agent-AbCdEf1234", "agentRuntimeVersion": "1",
        "createdAt": T0, "lastUpdatedAt": T0, "roleArn": "arn:aws:iam::111122223333:role/kitdemo-kitc-runtime-role", "status": "READY",
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 120, "maxLifetime": 900},
        "agentRuntimeArtifact": {"codeConfiguration": {"code": {"s3": {"bucket": "kitdemo-kitc-code-111122223333-us-east-1", "prefix": "kitdemo_kitc_fr_agent/deployment_package.zip"}}, "runtime": "PYTHON_3_13", "entryPoint": ["agentcore_app.py"]}},
    }
    plan["ac_runtimes"] = (
        "bedrock-agentcore-control",
        [
            ("list_agent_runtimes", {"agentRuntimes": [summary]}, {"maxResults": 100}),
            ("get_agent_runtime", detail, {"agentRuntimeId": "kitdemo_kitc_fr_agent-AbCdEf1234"}),
        ],
    )
    account = StubbedAccount(plan)
    code, out = run([], account, capsys)
    assert code == 2
    assert "BILLS WHILE IDLE: STORAGE ONLY | AgentCore runtime: kitdemo_kitc_fr_agent (kitdemo_kitc_fr_agent-AbCdEf1234, version 1) [kit prefix]" in out
    assert "created: 2026-10-01T12:00:00Z | state: READY, microVMs, direct code deployment, session idle timeout 120 s, session max lifetime 900 s" in out
    assert "111122223333" not in out
    account.assert_all_calls_made()


def test_caller_identity_call_matches_the_service_model_and_is_made_once_for_two_regions(capsys):
    calls = []

    class PerRegion:
        def __init__(self):
            self.accounts = {}

        def __call__(self, service, region):
            calls.append((service, region))
            # the identity call goes to the first audited Region: here the one named on the command line
            self.accounts.setdefault(region, StubbedAccount(empty_plan(identity=(region == "us-west-2"), region=region)))
            return self.accounts[region](service, region)

    factory = PerRegion()
    code, out = run(["--region", "us-west-2"], factory, capsys)
    assert code == 0
    assert [c for c in calls if c[0] == "sts"] == [("sts", "us-west-2")]
    assert {region for _service, region in calls} == {"us-west-2", "us-east-1"}
    assert "[account] Caller identity (which account is being audited): account ending 3333" in out
    for account in factory.accounts.values():
        account.assert_all_calls_made()


# ------------------------------------------------- what reaches the screen, and what does not
def test_account_ids_in_aws_error_text_are_cut_to_four_digits(capsys):
    message = "User: arn:aws:iam::111122223333:user/jane is not authorized to perform: ecr:DescribeRepositories on resource: arn:aws:ecr:us-east-1:111122223333:repository/*"
    account = FakeAccount({("ecr", "describe_repositories"): client_error("AccessDeniedException", message)})
    code, out = run([], account, capsys)
    assert code == 2 and "AccessDeniedException" in out
    assert "111122223333" not in out and "[account ending 3333]" in out
    code, out = run(["--json"], account, capsys)
    assert "111122223333" not in out


def test_redact_leaves_other_numbers_alone():
    assert wr.redact("stored 1790000000000 ms, 1234567890123 bytes, 12345678901 x") == "stored 1790000000000 ms, 1234567890123 bytes, 12345678901 x"
    assert wr.redact("bucket-111122223333-us-east-1") == "bucket-[account ending 3333]-us-east-1"


def test_dry_run_prints_the_scope_it_found_and_makes_no_call(tmp_path, monkeypatch, capsys):
    kit = tmp_path / "kit_a_gpu_endpoint"
    kit.mkdir()
    (kit / "config.env").write_text('export AWS_REGION="us-west-2"  # where I ran it\nKIT_PREFIX=acme\n', encoding="utf-8")
    monkeypatch.setattr(wr, "KITS_DIR", tmp_path)
    code = wr.main(["--dry-run"], client_factory=forbidden_factory)
    out = capsys.readouterr().out
    assert code == 3
    assert "Region us-west-2: kit_a_gpu_endpoint/config.env" in out
    assert "prefix acme: kit_a_gpu_endpoint/config.env" in out
    assert "Region us-east-1: built-in default" in out and "prefix kitdemo: built-in default" in out
    assert "=== Region us-west-2: read-only calls that would be made ===" in out
    assert "sts.GetCallerIdentity()" in out


def test_kits_dir_flag_and_a_missing_kits_folder_do_not_crash(tmp_path, capsys):
    code, out = run(["--kits-dir", str(tmp_path / "does-not-exist")], FakeAccount(), capsys)
    assert code == 0
    assert "no kit_* folder was found beside this script" in out


@pytest.mark.parametrize(
    "text, expected",
    [
        ("AWS_REGION=us-west-2\nKIT_PREFIX=acme\n", {"AWS_REGION": "us-west-2", "KIT_PREFIX": "acme"}),
        ("\ufeffexport AWS_REGION='eu-west-1'\n  KIT_PREFIX = \"my-kit\"  # mine\n", {"AWS_REGION": "eu-west-1", "KIT_PREFIX": "my-kit"}),
        ("# only comments\n\nnot a setting\n=novalue\n", {"": "novalue"}),
        ("", {}),
        ("AWS_REGION=\nKIT_PREFIX", {"AWS_REGION": ""}),
    ],
)
def test_config_env_lines_are_parsed_forgivingly(text, expected):
    assert wr.parse_env_text(text.lstrip("\ufeff")) == expected


def test_environment_region_and_prefix_are_added(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    monkeypatch.setenv("KIT_PREFIX", "fromenv")
    account = FakeAccount()
    code, out = run([], account, capsys)
    assert "ap-southeast-2" in account.regions_called("sagemaker")
    assert "Region ap-southeast-2: environment AWS_REGION" in out and "prefix fromenv: environment KIT_PREFIX" in out


def test_a_region_that_does_not_look_like_one_is_a_usage_error_not_a_silent_skip(capsys):
    assert wr.main(["--region", "useast1"], client_factory=forbidden_factory) == 64
    assert wr.main(["--prefix", ""], client_factory=forbidden_factory) == 64
    assert "does not look like an AWS Region name" in capsys.readouterr().err


def test_prefix_variants_add_the_underscore_form_once():
    assert wr.prefix_variants(["my-kit", "kitdemo", "my_kit"]) == ["my-kit", "my_kit", "kitdemo"]


def test_an_empty_s3_xml_response_parses_the_way_the_bucket_check_expects():
    """botocore's own parser: an empty <Buckets/> is a list, and an empty bucket has no Versions key at all."""
    import botocore.session
    from botocore.parsers import create_parser

    model = botocore.session.get_session().get_service_model("s3")
    parser = create_parser(model.metadata["protocol"])

    def parse(operation, body):
        return parser.parse({"body": body, "headers": {}, "status_code": 200}, model.operation_model(operation).output_shape)

    ns = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'
    empty_listing = parse("ListBuckets", f'<?xml version="1.0" encoding="UTF-8"?><ListAllMyBucketsResult {ns}><Owner><ID>x</ID></Owner><Buckets></Buckets></ListAllMyBucketsResult>'.encode())
    assert empty_listing["Buckets"] == []
    empty_bucket = parse("ListObjectVersions", f'<?xml version="1.0" encoding="UTF-8"?><ListVersionsResult {ns}><Name>b</Name><MaxKeys>1</MaxKeys><IsTruncated>false</IsTruncated></ListVersionsResult>'.encode())
    assert "Versions" not in empty_bucket and "DeleteMarkers" not in empty_bucket
    one_object = parse("ListObjectVersions", f'<?xml version="1.0" encoding="UTF-8"?><ListVersionsResult {ns}><Name>b</Name><Version><Key>k</Key><VersionId>null</VersionId></Version></ListVersionsResult>'.encode())
    assert one_object["Versions"][0]["Key"] == "k"


def test_common_has_a_gitignore_that_keeps_run_time_files_out_of_git():
    from pathlib import Path

    lines = (Path(wr.__file__).resolve().parent / ".gitignore").read_text(encoding="utf-8").split()
    for needed in (".state.json", "__pycache__/", ".pytest_cache/"):
        assert needed in lines, needed
