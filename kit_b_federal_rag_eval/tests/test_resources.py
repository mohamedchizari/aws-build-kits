"""Deploy, teardown and verify flows, walked in dry-run with canned AWS answers.

Every request made in these flows is validated against the botocore API model
by kitlib.aws.Aws.call. No AWS client is created and no network is used.
"""
from __future__ import annotations

import pytest

from kitlib import aws as api
from kitlib import config, resources

QUIET = lambda *args, **kwargs: None  # noqa: E731


def settings(**overrides):
    env = {"AWS_REGION": "us-east-1", "KIT_PREFIX": "kitdemo"}
    env.update(overrides)
    return config.Settings.load(env)


def dry(canned=None):
    return api.Aws("us-east-1", dry_run=True, canned=canned, echo=QUIET)


def ops(aws):
    return [f"{service}.{operation}" for service, operation, _ in aws.calls]


def make_corpus(tmp_path, n=3):
    corpus_dir = tmp_path / "build" / "corpus"
    corpus_dir.mkdir(parents=True)
    for i in range(1, n + 1):
        (corpus_dir / f"uc-000{i}.txt").write_text(f"document {i}\n", encoding="utf-8")
        (corpus_dir / f"uc-000{i}.txt.metadata.json").write_text('{"metadataAttributes": {}}\n', encoding="utf-8")
    (corpus_dir / "notes.tmp").write_text("must not be uploaded", encoding="utf-8")
    return corpus_dir


NAMES = config.Names("kitdemo", api.DRY_ACCOUNT, "us-east-1")


# --- names ------------------------------------------------------------------------------------

def test_names_are_deterministic_and_within_service_limits():
    longest = config.Names("a234567890123456", "000000000000", "ap-southeast-2")
    assert len(longest.bucket) <= 63 and len(longest.role) <= 64 and len(longest.guardrail) <= 50
    assert len(longest.vector_bucket) <= 63 and len(longest.vector_index) <= 63
    assert NAMES.bucket == "kitdemo-fedrag-corpus-000000000000-us-east-1"
    assert NAMES.knowledge_base == "kitdemo-fedrag-kb" and NAMES.guardrail == "kitdemo-fedrag-grounding"
    for name in (NAMES.bucket, NAMES.role, NAMES.knowledge_base, NAMES.data_source, NAMES.guardrail,
                 NAMES.vector_bucket, NAMES.vector_index):
        assert name.startswith("kitdemo-fedrag")


@pytest.mark.parametrize("bad", ["Kit", "kit_demo", "k", "kit--demo", "kitdemo-", "1kit", "a" * 17])
def test_bad_prefixes_are_refused(bad):
    with pytest.raises(SystemExit):
        settings(KIT_PREFIX=bad)


def test_bad_settings_are_refused():
    with pytest.raises(SystemExit):
        settings(KB_TYPE="opensearch")
    with pytest.raises(SystemExit):
        settings(GROUNDING_THRESHOLD="1.0")
    with pytest.raises(SystemExit):
        settings(TOP_K="0")


# --- deploy ---------------------------------------------------------------------------------------

def test_deploy_managed_makes_the_calls_in_order_and_no_vector_store(tmp_path):
    aws = dry()
    state = resources.deploy(aws, settings(), make_corpus(tmp_path), echo=QUIET, sleep=QUIET)
    made = ops(aws)
    assert made[0] == "sts.get_caller_identity"
    order = ["s3.create_bucket", "s3.put_bucket_tagging", "s3.put_object", "iam.create_role",
             "iam.put_role_policy", "bedrock-agent.create_knowledge_base", "bedrock-agent.get_knowledge_base",
             "bedrock-agent.create_data_source", "bedrock-agent.start_ingestion_job",
             "bedrock-agent.get_ingestion_job"]
    positions = [made.index(op) for op in order]
    assert positions == sorted(positions)
    assert made.count("s3.put_object") == 6                      # 3 documents + 3 sidecars, not notes.tmp
    assert not [op for op in made if op.startswith("s3vectors.create") or "opensearch" in op]
    keys = [c[2]["Key"] for c in aws.calls if c[1] == "put_object"]
    assert keys[0] == "corpus/uc-0001.txt" and "corpus/uc-0001.txt.metadata.json" in keys
    assert state["knowledge_base_id"] == "DRYRUNKB01" and state["data_source_id"] == "DRYRUNDS01"
    assert state["bucket"] == NAMES.bucket and state["kb_type"] == "managed"
    assert not config.state_path().exists()                      # dry-run writes no state file


def test_deploy_s3vectors_creates_the_vector_store_before_the_knowledge_base(tmp_path):
    aws = dry()
    state = resources.deploy(aws, settings(KB_TYPE="s3vectors"), make_corpus(tmp_path), echo=QUIET, sleep=QUIET)
    made = ops(aws)
    assert made.index("s3vectors.create_vector_bucket") < made.index("s3vectors.create_index") \
        < made.index("iam.put_role_policy") < made.index("bedrock-agent.create_knowledge_base")
    kb = [c[2] for c in aws.calls if c[1] == "create_knowledge_base"][0]
    assert kb["storageConfiguration"]["s3VectorsConfiguration"]["indexArn"] == state["vector_index_arn"]
    policy = [c[2]["PolicyDocument"] for c in aws.calls if c[1] == "put_role_policy"][0]
    assert "s3vectors:QueryVectors" in policy and state["vector_index_arn"] in policy
    assert not [op for op in made if "opensearch" in op]


def test_deploy_reuses_what_already_exists(tmp_path):
    aws = dry(resources.dry_run_present_fixture(NAMES, "managed"))
    state = resources.deploy(aws, settings(), make_corpus(tmp_path), echo=QUIET, sleep=QUIET)
    made = ops(aws)
    for op in ("s3.create_bucket", "iam.create_role", "bedrock-agent.create_knowledge_base",
               "bedrock-agent.create_data_source"):
        assert op not in made
    assert "bedrock-agent.start_ingestion_job" in made           # a re-run syncs the data source again
    assert state["knowledge_base_id"] == "DRYRUNKB01"


def test_deploy_stops_if_existing_resources_cannot_be_listed(tmp_path):
    def denied(params):
        raise RuntimeError("AccessDeniedException")
    aws = dry({("bedrock-agent", "list_knowledge_bases"): denied})
    with pytest.raises(RuntimeError, match="not safe to create"):
        resources.deploy(aws, settings(), make_corpus(tmp_path), echo=QUIET, sleep=QUIET)
    assert "s3.create_bucket" not in ops(aws)


def test_managed_deploy_does_not_depend_on_s3_vectors_or_guardrail_listings(tmp_path):
    def denied(params):
        raise RuntimeError("AccessDeniedException")
    aws = dry({("s3vectors", "list_vector_buckets"): denied, ("bedrock", "list_guardrails"): denied})
    state = resources.deploy(aws, settings(), make_corpus(tmp_path), echo=QUIET, sleep=QUIET)
    assert state["knowledge_base_id"] == "DRYRUNKB01"
    assert not [op for op in ops(aws) if op.startswith("s3vectors.") or op == "bedrock.list_guardrails"]


def test_deploy_waits_for_the_data_source_before_starting_ingestion(tmp_path):
    aws = dry()
    resources.deploy(aws, settings(), make_corpus(tmp_path), echo=QUIET, sleep=QUIET)
    made = ops(aws)
    create = made.index("bedrock-agent.create_data_source")
    start = made.index("bedrock-agent.start_ingestion_job")
    assert "bedrock-agent.list_data_sources" in made[create:start]


def test_smoke_retrieve_uses_a_metadata_filter():
    aws = dry()
    resources.smoke_retrieve(aws, settings(), "KB12345678", echo=QUIET)
    configs = [c[2]["retrievalConfiguration"]["managedSearchConfiguration"] for c in aws.calls]
    assert "filter" not in configs[0]
    assert configs[1]["filter"] == {"equals": {"key": "development_stage", "value": "Deployed"}}


def test_corpus_files_lists_documents_then_sidecars_only(tmp_path):
    files = resources.corpus_files(make_corpus(tmp_path, 2))
    assert [p.name for p in files] == ["uc-0001.txt", "uc-0002.txt",
                                       "uc-0001.txt.metadata.json", "uc-0002.txt.metadata.json"]


# --- guardrail -------------------------------------------------------------------------------------

def test_create_guardrail_makes_a_numbered_version():
    aws = dry()
    result = resources.create_guardrail(aws, settings(GROUNDING_THRESHOLD="0.8"), echo=QUIET, sleep=QUIET)
    assert ops(aws) == ["sts.get_caller_identity", "bedrock.list_guardrails", "bedrock.create_guardrail",
                        "bedrock.get_guardrail", "bedrock.create_guardrail_version", "bedrock.get_guardrail"]
    assert result["guardrail_version"] == "1" and result["grounding_threshold"] == 0.8
    create = [c[2] for c in aws.calls if c[1] == "create_guardrail"][0]
    assert create["name"] == NAMES.guardrail
    assert create["contextualGroundingPolicyConfig"]["filtersConfig"][0]["threshold"] == 0.8


# --- teardown -----------------------------------------------------------------------------------------

def test_teardown_managed_deletes_each_thing_separately_and_in_a_safe_order():
    aws = dry(resources.dry_run_present_fixture(NAMES, "managed"))
    failures = resources.teardown(aws, settings(), {}, echo=QUIET, sleep=QUIET)
    assert failures == []
    made = ops(aws)
    order = ["bedrock-agent.delete_data_source", "bedrock-agent.delete_knowledge_base",
             "bedrock.delete_guardrail", "iam.delete_role_policy", "iam.delete_role",
             "s3.delete_objects", "s3.delete_bucket"]
    positions = [made.index(op) for op in order]
    assert positions == sorted(positions)
    assert [c[2] for c in aws.calls if c[1] == "delete_bucket"] == [{"Bucket": NAMES.bucket}]
    assert [c[2] for c in aws.calls if c[1] == "delete_role"] == [{"RoleName": NAMES.role}]


def test_teardown_s3vectors_deletes_index_then_vector_bucket_after_the_knowledge_base():
    aws = dry(resources.dry_run_present_fixture(NAMES, "s3vectors"))
    assert resources.teardown(aws, settings(KB_TYPE="s3vectors"), {}, echo=QUIET, sleep=QUIET) == []
    made = ops(aws)
    assert made.index("bedrock-agent.delete_knowledge_base") < made.index("s3vectors.delete_index") \
        < made.index("s3vectors.delete_vector_bucket") < made.index("iam.delete_role")


def test_teardown_works_without_a_state_file_and_finds_a_renamed_kb_by_state_id():
    fixture = resources.dry_run_present_fixture(NAMES, "managed")
    fixture[("bedrock-agent", "list_knowledge_bases")] = {"knowledgeBaseSummaries": [
        {"knowledgeBaseId": "STATEKB001", "name": "kitdemo-fedrag-kb-renamed", "status": "ACTIVE"}]}
    aws = dry(fixture)
    resources.teardown(aws, settings(), {"knowledge_base_id": "STATEKB001"}, echo=QUIET, sleep=QUIET)
    assert [c[2] for c in aws.calls if c[1] == "delete_knowledge_base"] == [{"knowledgeBaseId": "STATEKB001"}]


def test_teardown_leaves_other_resources_with_the_same_prefix_alone():
    fixture = resources.dry_run_present_fixture(NAMES, "managed")
    fixture[("s3", "list_buckets")] = {"Buckets": [{"Name": NAMES.bucket}, {"Name": "kitdemo-fedrag-other-bucket"}]}
    fixture[("iam", "list_roles")] = {"IsTruncated": False, "Roles": [
        {"RoleName": NAMES.role, "Arn": "arn:aws:iam::000000000000:role/x"},
        {"RoleName": "kitdemo-fedrag-something-else", "Arn": "arn:aws:iam::000000000000:role/y"}]}
    aws = dry(fixture)
    resources.teardown(aws, settings(), {}, echo=QUIET, sleep=QUIET)
    assert [c[2]["Bucket"] for c in aws.calls if c[1] == "delete_bucket"] == [NAMES.bucket]
    assert [c[2]["RoleName"] for c in aws.calls if c[1] == "delete_role"] == [NAMES.role]


def test_teardown_keeps_the_role_and_bucket_when_the_knowledge_base_cannot_be_deleted():
    fixture = resources.dry_run_present_fixture(NAMES, "managed")

    def refuse(params):
        raise RuntimeError("ConflictException: knowledge base is in use")
    fixture[("bedrock-agent", "delete_knowledge_base")] = refuse
    aws = dry(fixture)
    failures = resources.teardown(aws, settings(), {}, echo=QUIET, sleep=QUIET)
    made = ops(aws)
    assert "iam.delete_role" not in made and "s3.delete_bucket" not in made
    assert "bedrock.delete_guardrail" in made                    # the guardrail does not depend on it
    assert any("knowledge base is in use" in f for f in failures)
    assert any("skipped the vector store, role and bucket" in f for f in failures)


def test_teardown_with_nothing_left_makes_no_delete_call():
    aws = dry()
    assert resources.teardown(aws, settings(), {}, echo=QUIET, sleep=QUIET) == []
    assert not [op for op in ops(aws) if ".delete_" in op]


def test_teardown_reports_a_data_source_stuck_in_delete_unsuccessful():
    fixture = resources.dry_run_present_fixture(NAMES, "managed")
    calls = {"n": 0}

    def sources(params):
        calls["n"] += 1
        status = "AVAILABLE" if calls["n"] == 1 else "DELETE_UNSUCCESSFUL"
        return {"dataSourceSummaries": [{"knowledgeBaseId": "DRYRUNKB01", "dataSourceId": "DRYRUNDS01",
                                         "name": NAMES.data_source, "status": status}]}
    fixture[("bedrock-agent", "list_data_sources")] = sources
    aws = dry(fixture)
    failures = resources.teardown(aws, settings(), {}, echo=QUIET, sleep=QUIET)
    assert any("data source deletion was unsuccessful" in f for f in failures)
    assert "bedrock-agent.delete_knowledge_base" not in ops(aws)


# --- verify ----------------------------------------------------------------------------------------------

def test_verify_clean_account():
    report = resources.verify(dry(), settings())
    assert report["kit_resource_count"] == 0 and report["errors"] == []
    assert report["tagged_resources"] == [] and report["opensearch_serverless_collections"] == []


def test_verify_finds_leftovers_by_name_without_any_state_file():
    report = resources.verify(dry(resources.dry_run_present_fixture(NAMES, "s3vectors")), settings())
    kit = report["kit_resources"]
    assert report["kit_resource_count"] == 7
    assert [kb["id"] for kb in kit["knowledge_bases"]] == ["DRYRUNKB01"]
    assert kit["buckets"] == [NAMES.bucket] and kit["roles"][0]["name"] == NAMES.role
    assert kit["vector_indexes"][0]["name"] == NAMES.vector_index and len(kit["data_sources"]) == 1


def test_verify_separates_other_kits_resources_with_the_same_prefix():
    canned = {("s3", "list_buckets"): {"Buckets": [{"Name": "kitdemo-gpu-artifacts"}]},
              ("bedrock", "list_guardrails"): {"guardrails": [{"id": "g9", "name": "kitdemo-agent-guard"}]}}
    report = resources.verify(dry(canned), settings())
    assert report["kit_resource_count"] == 0
    assert report["other_prefix_resources"]["buckets"] == ["kitdemo-gpu-artifacts"]
    assert report["other_prefix_resources"]["guardrails"][0]["id"] == "g9"


def test_verify_reports_tagged_resources_and_opensearch_collections():
    canned = {
        ("resourcegroupstaggingapi", "get_resources"): {"ResourceTagMappingList": [
            {"ResourceARN": "arn:aws:bedrock:us-east-1:000000000000:knowledge-base/OLDKB00001"}]},
        ("opensearchserverless", "list_collections"): {"collectionSummaries": [
            {"id": "abc123", "name": "bedrock-knowledge-base-q1", "status": "ACTIVE"}]},
        ("opensearchserverless", "batch_get_collection"): {"collectionDetails": [
            {"id": "abc123", "type": "VECTORSEARCH"}]}}
    report = resources.verify(dry(canned), settings())
    assert report["tagged_resources"] == ["arn:aws:bedrock:us-east-1:000000000000:knowledge-base/OLDKB00001"]
    assert report["opensearch_serverless_collections"][0]["type"] == "VECTORSEARCH"


def test_verify_never_says_clean_when_a_check_could_not_run():
    def denied(params):
        raise RuntimeError("AccessDeniedException: not allowed")
    report = resources.verify(dry({("s3vectors", "list_vector_buckets"): denied,
                                   ("opensearchserverless", "list_collections"): denied}), settings())
    assert len(report["errors"]) == 2
    assert any("S3 vector buckets" in e for e in report["errors"])
    assert any("OpenSearch Serverless" in e for e in report["errors"])


def test_verify_and_check_make_only_read_calls():
    aws = dry(resources.dry_run_present_fixture(NAMES, "s3vectors"))
    resources.verify(aws, settings())
    for _, operation, _ in aws.calls:
        assert operation.startswith(("list_", "get_", "batch_get_")), operation
