"""Request shapes and response parsing, checked offline.

No test here talks to AWS. Requests are validated against the API model that
ships inside botocore (the same definitions the real SDK uses), and the three
calls the evaluation numbers depend on are also run through botocore's Stubber,
which checks both the request sent and the response shape returned.
"""
from __future__ import annotations

import inspect
import re

import boto3
import pytest
from botocore.exceptions import ParamValidationError
from botocore.stub import Stubber

from kitlib import aws as api
from kitlib import config


def dry():
    aws = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None)
    return aws


def ops(aws):
    return [f"{service}.{operation}" for service, operation, _ in aws.calls]


# --- the validator itself has teeth ---------------------------------------------------------------

def test_validator_rejects_a_wrong_enum_value():
    with pytest.raises(ValueError, match="knowledgeBaseConfiguration.type='FULLY_MANAGED'"):
        api.validate_request("bedrock-agent", "create_knowledge_base", {
            "name": "x", "roleArn": "arn:aws:iam::000000000000:role/x",
            "knowledgeBaseConfiguration": {"type": "FULLY_MANAGED"}})
    with pytest.raises(ValueError, match="qualifiers"):
        api.validate_request("bedrock-runtime", "apply_guardrail", {
            "guardrailIdentifier": "g", "guardrailVersion": "1", "source": "OUTPUT",
            "content": [{"text": {"text": "x", "qualifiers": ["grounding-source"]}}]})
    with pytest.raises(ValueError, match="distanceMetric"):
        api.validate_request("s3vectors", "create_index", {
            "vectorBucketName": "vb-name", "indexName": "ix-name", "dataType": "float32",
            "dimension": 1024, "distanceMetric": "COSINE"})


def test_validator_rejects_an_unknown_parameter_and_a_missing_required_one():
    with pytest.raises(ParamValidationError):
        api.validate_request("bedrock-runtime", "apply_guardrail", {
            "guardrailIdentifier": "g", "guardrailVersion": "1", "source": "OUTPUT",
            "content": [], "sources": "not a real parameter"})
    with pytest.raises(ParamValidationError):
        api.validate_request("bedrock-agent-runtime", "retrieve", {"retrievalQuery": {"text": "q"}})


def test_validator_rejects_an_unknown_operation():
    with pytest.raises(ValueError):
        api.validate_request("bedrock-agent", "create_managed_knowledge_base", {})


def test_dry_run_can_never_create_a_client():
    with pytest.raises(RuntimeError, match="never create an AWS client"):
        dry().client("s3")


# --- every wrapper builds a request the SDK model accepts ---------------------------------------------

def test_managed_knowledge_base_request():
    aws = dry()
    api.create_managed_knowledge_base(aws, "kitdemo-fedrag-kb", "arn:aws:iam::000000000000:role/r", {"project": "aws-kits"})
    _, _, params = aws.calls[0]
    assert params["knowledgeBaseConfiguration"] == {
        "type": "MANAGED", "managedKnowledgeBaseConfiguration": {"embeddingModelType": "MANAGED"}}
    assert "storageConfiguration" not in params and params["tags"] == {"project": "aws-kits"}


def test_s3_vectors_knowledge_base_request():
    aws = dry()
    api.create_s3vectors_knowledge_base(
        aws, "kb", "arn:aws:iam::000000000000:role/r",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0", 1024,
        "arn:aws:s3vectors:us-east-1:000000000000:bucket/vb",
        "arn:aws:s3vectors:us-east-1:000000000000:bucket/vb/index/ix", {"project": "aws-kits"})
    params = aws.calls[0][2]
    assert params["knowledgeBaseConfiguration"]["type"] == "VECTOR"
    assert params["storageConfiguration"]["type"] == "S3_VECTORS"
    assert set(params["storageConfiguration"]["s3VectorsConfiguration"]) == {"vectorBucketArn", "indexArn"}


def test_no_request_ever_names_opensearch():
    aws = dry()
    api.create_managed_knowledge_base(aws, "kb", "arn:aws:iam::000000000000:role/r", {})
    api.create_s3vectors_knowledge_base(
        aws, "kb", "arn:aws:iam::000000000000:role/r",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0", 1024,
        "arn:aws:s3vectors:us-east-1:000000000000:bucket/vb",
        "arn:aws:s3vectors:us-east-1:000000000000:bucket/vb/index/ix", {})
    assert "OPENSEARCH" not in repr(aws.calls).upper()
    source = inspect.getsource(api)
    assert "create_collection" not in source and "opensearchServerlessConfiguration" not in source


def test_data_source_requests_for_both_types():
    aws = dry()
    api.create_managed_s3_data_source(aws, "KB12345678", "src", "bucket-name", "000000000000", "corpus/")
    api.create_vector_s3_data_source(aws, "KB12345678", "src", "bucket-name", "000000000000", "corpus/")
    managed, vector = aws.calls[0][2], aws.calls[1][2]
    connector = managed["dataSourceConfiguration"]["managedKnowledgeBaseConnectorConfiguration"]
    assert managed["dataSourceConfiguration"]["type"] == "MANAGED_KNOWLEDGE_BASE_CONNECTOR"
    assert connector["connectorParameters"]["type"] == "S3" and connector["connectorParameters"]["version"] == "1"
    assert connector["connectorParameters"]["connectionConfiguration"] == {
        "bucketName": "bucket-name", "bucketOwnerAccountId": "000000000000"}
    assert connector["connectorParameters"]["filterConfiguration"] == {"inclusionPrefixes": ["corpus/"]}
    assert managed["dataDeletionPolicy"] == "DELETE"
    assert vector["dataSourceConfiguration"] == {"type": "S3", "s3Configuration": {
        "bucketArn": "arn:aws:s3:::bucket-name", "bucketOwnerAccountId": "000000000000",
        "inclusionPrefixes": ["corpus/"]}}


def test_retrieval_configuration_differs_by_knowledge_base_type():
    # Round 1 review, MAJOR 1: the re-ranker setting is sent, not left to the service default.
    assert api.retrieval_configuration("managed", 5) == {"managedSearchConfiguration": {
        "numberOfResults": 5, "rerankingModelType": "MANAGED"}}
    assert api.retrieval_configuration("s3vectors", 7) == {"vectorSearchConfiguration": {"numberOfResults": 7}}
    flt = {"equals": {"key": "agency", "value": "DOE"}}
    assert api.retrieval_configuration("managed", 5, flt)["managedSearchConfiguration"]["filter"] == flt
    aws = dry()
    api.retrieve(aws, "KB12345678", "managed", "q", 5, flt)
    api.retrieve(aws, "KB12345678", "s3vectors", "q", 5, flt)
    assert ops(aws) == ["bedrock-agent-runtime.retrieve"] * 2


def test_guardrail_requests():
    aws = dry()
    api.create_grounding_guardrail(aws, "kitdemo-fedrag-grounding", 0.7, 0.6, [{"key": "project", "value": "aws-kits"}])
    api.create_guardrail_version(aws, "abc123")
    api.get_guardrail(aws, "abc123", "1")
    api.delete_guardrail(aws, "abc123")
    api.apply_grounding_guardrail(aws, "abc123", "1", "sources", "question?", "answer")
    create = aws.calls[0][2]
    assert create["contextualGroundingPolicyConfig"] == {"filtersConfig": [
        {"type": "GROUNDING", "threshold": 0.7, "action": "BLOCK"},
        {"type": "RELEVANCE", "threshold": 0.6, "action": "BLOCK"}]}
    assert set(create) == {"name", "description", "contextualGroundingPolicyConfig",
                           "blockedInputMessaging", "blockedOutputsMessaging", "tags"}
    apply = aws.calls[-1][2]
    assert apply["source"] == "OUTPUT"
    assert apply["outputScope"] == "FULL"      # round 1 review, MINOR 5: scores for answers that pass, too
    assert [block["text"]["qualifiers"] for block in apply["content"]] == [
        ["grounding_source"], ["query"], ["guard_content"]]
    assert [block["text"]["text"] for block in apply["content"]] == ["sources", "question?", "answer"]


def test_every_other_wrapper_builds_a_valid_request():
    aws = dry()
    api.get_caller_identity(aws)
    api.list_bedrock_quotas(aws)
    api.get_tagged_resources(aws, "project", "aws-kits")
    api.list_buckets(aws, "kitdemo")
    api.create_bucket(aws, "kitdemo-fedrag-corpus-000000000000-us-east-1")
    api.put_bucket_tagging(aws, "b-name", config.tags_list_upper())
    api.put_object(aws, "b-name", "corpus/uc-0001.txt", b"text", "text/plain; charset=utf-8")
    api.empty_bucket(aws, "b-name")
    api.delete_bucket(aws, "b-name")
    api.list_roles(aws)
    api.create_role(aws, "role-name", api.kb_trust_policy("000000000000", "us-east-1"), config.tags_list_upper())
    api.put_role_policy(aws, "role-name", "policy", api.kb_permissions_policy("000000000000", "us-east-1", "b", "managed"))
    api.list_role_policies(aws, "role-name")
    api.delete_role_policy(aws, "role-name", "policy")
    api.delete_role(aws, "role-name")
    api.list_vector_buckets(aws, "kitdemo")
    api.create_vector_bucket(aws, "kitdemo-fedrag-vectors", config.tags_map())
    api.list_vector_indexes(aws, "kitdemo-fedrag-vectors")
    api.create_vector_index(aws, "kitdemo-fedrag-vectors", "kitdemo-fedrag-index", 1024, config.tags_map())
    api.delete_vector_index(aws, "kitdemo-fedrag-vectors", "kitdemo-fedrag-index")
    api.delete_vector_bucket(aws, "kitdemo-fedrag-vectors")
    api.list_knowledge_bases(aws)
    api.get_knowledge_base(aws, "KB12345678")
    api.list_data_sources(aws, "KB12345678")
    api.start_ingestion_job(aws, "KB12345678", "DS12345678")
    api.get_ingestion_job(aws, "KB12345678", "DS12345678", "JOB1234567")
    api.delete_data_source(aws, "KB12345678", "DS12345678")
    api.delete_knowledge_base(aws, "KB12345678")
    api.get_foundation_model(aws, "amazon.nova-lite-v1:0")
    api.get_foundation_model_availability(aws, "amazon.nova-lite-v1:0")
    api.get_inference_profile(aws, "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    api.converse(aws, "amazon.nova-lite-v1:0", "system", "user", 200)
    api.list_guardrails(aws)
    api.list_opensearch_serverless_collections(aws)
    called = set(ops(aws))
    assert {"s3.create_bucket", "iam.create_role", "s3vectors.create_index", "bedrock-runtime.converse",
            "opensearchserverless.list_collections", "service-quotas.list_service_quotas",
            "resourcegroupstaggingapi.get_resources"} <= called


def test_bucket_outside_us_east_1_gets_a_location_constraint():
    east, west = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None), api.Aws("us-west-2", dry_run=True, echo=lambda *_: None)
    api.create_bucket(east, "name-one")
    api.create_bucket(west, "name-two")
    assert east.calls[0][2] == {"Bucket": "name-one"}
    assert west.calls[0][2] == {"Bucket": "name-two",
                                "CreateBucketConfiguration": {"LocationConstraint": "us-west-2"}}


def test_vector_index_marks_the_bedrock_keys_non_filterable():
    aws = dry()
    api.create_vector_index(aws, "vb-name", "ix-name", 1024, {})
    params = aws.calls[0][2]
    assert params["metadataConfiguration"] == {"nonFilterableMetadataKeys": ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]}
    assert (params["dataType"], params["dimension"], params["distanceMetric"]) == ("float32", 1024, "cosine")


# --- IAM policy documents ---------------------------------------------------------------------------------

def test_trust_policy_is_scoped_to_this_account_and_region():
    policy = api.kb_trust_policy("000000000000", "us-east-1")
    statement = policy["Statement"][0]
    assert statement["Principal"] == {"Service": "bedrock.amazonaws.com"}
    assert statement["Condition"]["StringEquals"] == {"aws:SourceAccount": "000000000000"}
    assert statement["Condition"]["ArnLike"]["AWS:SourceArn"] == "arn:aws:bedrock:us-east-1:000000000000:knowledge-base/*"


def test_permissions_policy_is_least_privilege_for_each_type():
    managed = api.kb_permissions_policy("000000000000", "us-east-1", "the-bucket", "managed")
    actions = [a for s in managed["Statement"] for a in s["Action"]]
    assert actions == ["s3:ListBucket", "s3:GetObject", "bedrock:ListFoundationModels", "bedrock:ListCustomModels"]
    assert managed["Statement"][1]["Resource"] == ["arn:aws:s3:::the-bucket/*"]
    assert "*" not in [s["Resource"] for s in managed["Statement"][:2]]

    vectors = api.kb_permissions_policy("000000000000", "us-east-1", "the-bucket", "s3vectors",
                                        "amazon.titan-embed-text-v2:0", "arn:aws:s3vectors:us-east-1:000000000000:bucket/v/index/i")
    by_sid = {s["Sid"]: s for s in vectors["Statement"]}
    assert by_sid["BedrockInvokeEmbeddingModelStatement"]["Resource"] == [
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"]
    assert by_sid["S3VectorBucketReadAndWritePermission"]["Action"] == [
        "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors", "s3vectors:GetIndex"]


# --- response parsers -----------------------------------------------------------------------------------------

def test_parse_retrieve_response_takes_the_document_id_from_the_s3_uri_or_the_metadata():
    passages = api.parse_retrieve_response({"retrievalResults": [
        {"content": {"text": "one"}, "score": 0.9,
         "location": {"type": "S3", "s3Location": {"uri": "s3://b/corpus/uc-0042.txt"}}},
        {"content": {"text": "two"}, "metadata": {"doc_id": "uc-0007"}},
        {"content": {"text": "three"}, "location": {"type": "S3", "s3Location": {"uri": "s3://b/other.pdf"}}},
        {"content": {}},
    ]})
    assert [(p.doc_id, p.text) for p in passages] == [("uc-0042", "one"), ("uc-0007", "two"), (None, "three"), (None, "")]
    assert passages[0].score == 0.9 and passages[0].uri == "s3://b/corpus/uc-0042.txt"
    assert api.parse_retrieve_response({}) == []


def test_parse_converse_response():
    parsed = api.parse_converse_response({
        "output": {"message": {"role": "assistant", "content": [{"text": " The Department "}, {"text": "of Energy. "}]}},
        "stopReason": "end_turn", "usage": {"inputTokens": 1234, "outputTokens": 9, "totalTokens": 1243}})
    assert parsed == {"text": "The Department of Energy.", "input_tokens": 1234, "output_tokens": 9, "stop_reason": "end_turn"}
    assert api.parse_converse_response({})["text"] == ""


def test_parse_guardrail_response_reads_action_scores_and_billed_units():
    parsed = api.parse_guardrail_response({
        "action": "GUARDRAIL_INTERVENED",
        "assessments": [{"contextualGroundingPolicy": {"filters": [
            {"type": "GROUNDING", "threshold": 0.7, "score": 0.31, "action": "BLOCKED"},
            {"type": "RELEVANCE", "threshold": 0.7, "score": 0.88, "action": "NONE"}]}}],
        "usage": {"contextualGroundingPolicyUnits": 6}, "outputs": [{"text": "blocked"}]})
    assert parsed == {"action": "GUARDRAIL_INTERVENED", "grounding_score": 0.31, "relevance_score": 0.88, "units": 6}
    assert api.parse_guardrail_response({"action": "NONE"}) == {
        "action": "NONE", "grounding_score": None, "relevance_score": None, "units": 0}


# --- the three evaluation calls through botocore's Stubber (request AND response shapes) ---------------------------

def stubbed(service):
    client = boto3.client(service, region_name="us-east-1", aws_access_key_id="testing",
                          aws_secret_access_key="testing")
    return client, Stubber(client)


def test_backend_against_stubbed_bedrock_clients():
    runtime, runtime_stub = stubbed("bedrock-runtime")
    agent, agent_stub = stubbed("bedrock-agent-runtime")

    agent_stub.add_response("retrieve", {
        "retrievalResults": [{"content": {"text": "Agency: Department of Energy (DOE)", "type": "TEXT"},
                              "location": {"type": "S3", "s3Location": {"uri": "s3://b/corpus/uc-0012.txt"}},
                              "metadata": {"doc_id": "uc-0012"}, "score": 0.71}]},
        expected_params={"knowledgeBaseId": "KB12345678", "retrievalQuery": {"text": "Which agency?"},
                         "retrievalConfiguration": {"managedSearchConfiguration": {
                             "numberOfResults": 5, "rerankingModelType": "MANAGED"}}})
    converse_reply = {
        "output": {"message": {"role": "assistant", "content": [{"text": "The Department of Energy."}]}},
        "stopReason": "end_turn", "usage": {"inputTokens": 400, "outputTokens": 7, "totalTokens": 407},
        "metrics": {"latencyMs": 321}}
    runtime_stub.add_response("converse", converse_reply, expected_params={
        "modelId": "amazon.nova-lite-v1:0", "system": [{"text": "SYS"}],
        "messages": [{"role": "user", "content": [{"text": "USER"}]}],
        "inferenceConfig": {"maxTokens": 200, "temperature": 0.0}})
    runtime_stub.add_response("apply_guardrail", {
        "action": "GUARDRAIL_INTERVENED", "outputs": [{"text": "blocked"}],
        "usage": {"topicPolicyUnits": 0, "contentPolicyUnits": 0, "wordPolicyUnits": 0,
                  "sensitiveInformationPolicyUnits": 0, "sensitiveInformationPolicyFreeUnits": 0,
                  "contextualGroundingPolicyUnits": 3},
        "assessments": [{"contextualGroundingPolicy": {"filters": [
            {"type": "GROUNDING", "threshold": 0.7, "score": 0.2, "action": "BLOCKED"},
            {"type": "RELEVANCE", "threshold": 0.7, "score": 0.9, "action": "NONE"}]}}]},
        expected_params={"guardrailIdentifier": "gr1", "guardrailVersion": "1", "source": "OUTPUT",
                         "outputScope": "FULL", "content": [
            {"text": {"text": "SRC", "qualifiers": ["grounding_source"]}},
            {"text": {"text": "Q", "qualifiers": ["query"]}},
            {"text": {"text": "A", "qualifiers": ["guard_content"]}}]})
    runtime_stub.add_response("converse", dict(converse_reply, output={"message": {
        "role": "assistant", "content": [{"text": '{"verdict": "CORRECT"}'}]}}), expected_params={
        "modelId": "amazon.nova-pro-v1:0", "system": [{"text": "JSYS"}],
        "messages": [{"role": "user", "content": [{"text": "JUSER"}]}],
        "inferenceConfig": {"maxTokens": 120, "temperature": 0.0}})

    aws = api.Aws("us-east-1", clients={"bedrock-runtime": runtime, "bedrock-agent-runtime": agent})
    backend = api.BedrockBackend(aws, "KB12345678", "managed", 5, "amazon.nova-lite-v1:0",
                                 "amazon.nova-pro-v1:0", "gr1", "1")
    with runtime_stub, agent_stub:
        passages = backend.retrieve("Which agency?")
        generated = backend.generate("SYS", "USER")
        verdict = backend.apply_guardrail("SRC", "Q", "A")
        judged = backend.judge("JSYS", "JUSER")
        runtime_stub.assert_no_pending_responses()
        agent_stub.assert_no_pending_responses()
    assert [p.doc_id for p in passages] == ["uc-0012"]
    assert generated == {"text": "The Department of Energy.", "input_tokens": 400, "output_tokens": 7, "stop_reason": "end_turn"}
    assert verdict == {"action": "GUARDRAIL_INTERVENED", "grounding_score": 0.2, "relevance_score": 0.9, "units": 3}
    assert judged["text"] == '{"verdict": "CORRECT"}'


def test_managed_knowledge_base_create_through_the_stubber():
    client, stub = stubbed("bedrock-agent")
    stub.add_response("create_knowledge_base", {"knowledgeBase": {
        "knowledgeBaseId": "KB12345678", "name": "kitdemo-fedrag-kb",
        "knowledgeBaseArn": "arn:aws:bedrock:us-east-1:000000000000:knowledge-base/KB12345678",
        "roleArn": "arn:aws:iam::000000000000:role/r", "status": "CREATING",
        "knowledgeBaseConfiguration": {"type": "MANAGED"},
        "createdAt": "2026-10-07T00:00:00Z", "updatedAt": "2026-10-07T00:00:00Z"}},
        expected_params={"name": "kitdemo-fedrag-kb", "roleArn": "arn:aws:iam::000000000000:role/r",
                         "description": "aws-kits kit B: OMB 2025 federal AI use case inventory (unofficial demo)",
                         "knowledgeBaseConfiguration": {"type": "MANAGED", "managedKnowledgeBaseConfiguration": {
                             "embeddingModelType": "MANAGED"}},
                         "tags": {"project": "aws-kits"}})
    aws = api.Aws("us-east-1", clients={"bedrock-agent": client})
    with stub:
        kb = api.create_managed_knowledge_base(aws, "kitdemo-fedrag-kb", "arn:aws:iam::000000000000:role/r",
                                               {"project": "aws-kits"})
    assert kb["knowledgeBaseId"] == "KB12345678"


# --- helpers ------------------------------------------------------------------------------------------------------------

def test_wait_until_returns_when_ready_and_times_out_otherwise():
    states = iter([None, None, {"status": "ACTIVE"}])
    slept = []
    result = api.wait_until(lambda: next(states), "it", timeout_s=100, interval_s=10, sleep=slept.append,
                            echo=lambda *_: None)
    assert result == {"status": "ACTIVE"} and slept == [10, 10]
    with pytest.raises(TimeoutError, match="timed out after 30s waiting for the thing"):
        api.wait_until(lambda: None, "the thing", timeout_s=30, interval_s=10, sleep=lambda _: None,
                       echo=lambda *_: None)


def test_paginate_follows_tokens():
    pages = {None: {"items": [1, 2], "nextToken": "a"}, "a": {"items": [3], "nextToken": "b"}, "b": {"items": [4]}}
    aws = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None,
                  canned={("bedrock", "list_guardrails"): lambda p: pages[p.get("nextToken")]})
    assert api.paginate(aws, "bedrock", "list_guardrails", "items", "nextToken") == [1, 2, 3, 4]
    assert [c[2] for c in aws.calls] == [{}, {"nextToken": "a"}, {"nextToken": "b"}]


def test_empty_bucket_deletes_versions_and_delete_markers_across_pages():
    pages = iter([
        {"IsTruncated": True, "NextKeyMarker": "k2", "NextVersionIdMarker": "v2",
         "Versions": [{"Key": "a", "VersionId": "null"}, {"Key": "b", "VersionId": "111"}],
         "DeleteMarkers": [{"Key": "c", "VersionId": "222"}]},
        {"IsTruncated": False, "Versions": [{"Key": "d", "VersionId": "null"}]},
    ])
    aws = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None,
                  canned={("s3", "list_object_versions"): lambda p: next(pages)})
    assert api.empty_bucket(aws, "bucket-name") == 4
    deletes = [c[2]["Delete"]["Objects"] for c in aws.calls if c[1] == "delete_objects"]
    assert deletes == [[{"Key": "a"}, {"Key": "b", "VersionId": "111"}, {"Key": "c", "VersionId": "222"}], [{"Key": "d"}]]
    second_list = [c[2] for c in aws.calls if c[1] == "list_object_versions"][1]
    assert second_list == {"Bucket": "bucket-name", "MaxKeys": 1000, "KeyMarker": "k2", "VersionIdMarker": "v2"}


def test_empty_bucket_stops_on_a_delete_error():
    aws = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None, canned={
        ("s3", "list_object_versions"): {"IsTruncated": False, "Versions": [{"Key": "a", "VersionId": "null"}]},
        ("s3", "delete_objects"): {"Errors": [{"Key": "a", "Code": "AccessDenied"}]}})
    with pytest.raises(RuntimeError, match="could not delete 1 object"):
        api.empty_bucket(aws, "bucket-name")


def test_opensearch_listing_merges_type_details():
    aws = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None, canned={
        ("opensearchserverless", "list_collections"): {"collectionSummaries": [
            {"id": "abc123", "name": "bedrock-knowledge-base-x", "status": "ACTIVE"}]},
        ("opensearchserverless", "batch_get_collection"): {"collectionDetails": [
            {"id": "abc123", "type": "VECTORSEARCH", "standbyReplicas": "ENABLED"}]}})
    found = api.list_opensearch_serverless_collections(aws)
    assert found == [{"id": "abc123", "name": "bedrock-knowledge-base-x", "status": "ACTIVE",
                      "type": "VECTORSEARCH", "standbyReplicas": "ENABLED"}]


# --- the spine rule: every AWS call carries a doc URL and the date it was read ----------------------------------------------

def test_every_function_that_calls_aws_cites_a_doc_page_with_the_read_date():
    skip = {"paginate", "wait_until", "validate_request", "error_code"}
    checked = 0
    for name, fn in inspect.getmembers(api, inspect.isfunction):
        if fn.__module__ != api.__name__ or name in skip or name.startswith("_"):
            continue
        source = inspect.getsource(fn)
        if "aws.call(" in source or "paginate(aws" in source:
            checked += 1
            assert re.search(r"# DOC: https://\S+ \(read 2026-10-07\)", source) or re.search(
                r"# DOC: https://\S+\n\s+# \(read 2026-10-07\)", source), f"{name} has no DOC comment"
    assert checked >= 35
