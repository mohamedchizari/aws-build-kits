"""A small stateful fake of the AWS account, for walking deploy, teardown and the clean check offline.

Nothing here talks to AWS. Each fake client validates the request it is given
against the botocore API model (the same check `--dry-run` uses) and then reads
or changes a dictionary. Resources are kept per account and per Region, so a
test can sign in as another account or point the kit at another Region and see
what the scripts do. The idea is taken from the round 1 review's evidence
scripts; this file was written for the kit's own tests.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import itertools
import os

from conftest import KIT_DIR
from kitlib import aws as api

ACCOUNT_A = "111122223333"   # documentation placeholder account ids
ACCOUNT_B = "123456789012"
BILLS = "--i-understand-this-bills"


class World:
    def __init__(self, account: str = ACCOUNT_A):
        self.account = account
        self.buckets: dict = {}      # (account, name) -> {"objects": [...], "tags": {}, "versioning": None, "region": str}
        self.roles: dict = {}        # (account, name) -> {"policies": {}}
        self.kbs: dict = {}          # (account, region, id) -> {"name": str, "type": str}
        self.data_sources: dict = {}  # (account, region, kb id, ds id) -> {"name": str}
        self.guardrails: dict = {}   # (account, region, id) -> {"name": str, "versions": int}
        self.vector_buckets: dict = {}   # (account, region, name) -> {"indexes": {}}
        self.collections: dict = {}  # (account, region, id) -> name
        self.extra_tagged: list = []  # (account, region, arn): tagged resources of other kits
        self.fail: dict = {}         # (service, operation) -> callable returning an exception
        self.log: list = []          # (account, region, service, operation, params)
        self._ids = itertools.count(1)

    def next_id(self) -> int:
        return next(self._ids)

    def calls(self, service: str | None = None, operation: str | None = None) -> list:
        return [entry for entry in self.log
                if (service is None or entry[2] == service) and (operation is None or entry[3] == operation)]

    def left(self) -> dict:
        """Everything that still exists, in every account and Region."""
        return {
            "buckets": sorted(name for (_, name) in self.buckets),
            "roles": sorted(name for (_, name) in self.roles),
            "knowledge_bases": sorted((region, kb_id) for (_, region, kb_id) in self.kbs),
            "data_sources": len(self.data_sources),
            "guardrails": sorted((region, g_id) for (_, region, g_id) in self.guardrails),
            "vector_buckets": sorted((region, name) for (_, region, name) in self.vector_buckets),
        }

    def nothing_left(self) -> bool:
        left = self.left()
        return not any(left[key] for key in left)

    def bucket_keys(self) -> set:
        """Keys a plain listing shows: those whose newest version is an object, not a delete marker."""
        return {key for bucket in self.buckets.values() for key in current_keys(bucket)}


def current_keys(bucket: dict) -> set:
    newest = {}
    for entry in bucket["objects"]:            # entries are kept oldest first
        newest[entry["Key"]] = entry
    return {key for key, entry in newest.items() if not entry["marker"]}


class FakeClient:
    def __init__(self, world: World, service: str, region: str):
        self.w, self.service, self.region = world, service, region

    def __getattr__(self, operation):
        def call(**params):
            api.validate_request(self.service, operation, params)
            self.w.log.append((self.w.account, self.region, self.service, operation, params))
            if (self.service, operation) in self.w.fail:
                raise self.w.fail[(self.service, operation)]()
            return getattr(self, f"_{self.service.replace('-', '_')}__{operation}")(**params)
        return call

    @property
    def a(self) -> str:
        return self.w.account

    # --- sts ---
    def _sts__get_caller_identity(self):
        return {"Account": self.a, "UserId": "FAKE", "Arn": f"arn:aws:iam::{self.a}:user/kit-tester"}

    # --- s3 (bucket names are global; the fake keeps them per account) ---
    def _s3__list_buckets(self, Prefix="", **_):
        return {"Buckets": [{"Name": name} for (account, name) in self.w.buckets
                            if account == self.a and name.startswith(Prefix)]}

    def _s3__create_bucket(self, Bucket, **_):
        self.w.buckets[(self.a, Bucket)] = {"objects": [], "tags": {}, "versioning": None, "region": self.region}
        return {}

    def _s3__put_bucket_tagging(self, Bucket, Tagging):
        self.w.buckets[(self.a, Bucket)]["tags"] = {t["Key"]: t["Value"] for t in Tagging["TagSet"]}
        return {}

    def _s3__put_object(self, Bucket, Key, Body, ContentType=None):
        bucket = self.w.buckets[(self.a, Bucket)]
        if bucket["versioning"] == "Enabled":
            bucket["objects"].append({"Key": Key, "VersionId": f"v{self.w.next_id()}", "marker": False, "Body": Body})
        else:
            bucket["objects"] = [o for o in bucket["objects"] if not (o["Key"] == Key and o["VersionId"] == "null")]
            bucket["objects"].append({"Key": Key, "VersionId": "null", "marker": False, "Body": Body})
        return {}

    def _s3__list_objects_v2(self, Bucket, Prefix="", **_):
        bucket = self.w.buckets[(self.a, Bucket)]
        keys = sorted(key for key in current_keys(bucket) if key.startswith(Prefix))
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False, "KeyCount": len(keys)}

    def _s3__list_object_versions(self, Bucket, **_):
        bucket = self.w.buckets[(self.a, Bucket)]
        return {"Versions": [{"Key": o["Key"], "VersionId": o["VersionId"]} for o in bucket["objects"] if not o["marker"]],
                "DeleteMarkers": [{"Key": o["Key"], "VersionId": o["VersionId"]}
                                  for o in bucket["objects"] if o["marker"]],
                "IsTruncated": False}

    def _s3__delete_objects(self, Bucket, Delete):
        bucket = self.w.buckets[(self.a, Bucket)]
        for target in Delete["Objects"]:
            key = target["Key"]
            if "VersionId" in target:      # a named version (or marker) is removed for good
                bucket["objects"] = [o for o in bucket["objects"]
                                     if not (o["Key"] == key and o["VersionId"] == target["VersionId"])]
            elif bucket["versioning"] == "Enabled":     # S3 adds a delete marker and removes nothing
                bucket["objects"].append({"Key": key, "VersionId": f"v{self.w.next_id()}", "marker": True})
            elif bucket["versioning"] == "Suspended":   # the null version is replaced by a null delete marker
                bucket["objects"] = [o for o in bucket["objects"] if not (o["Key"] == key and o["VersionId"] == "null")]
                bucket["objects"].append({"Key": key, "VersionId": "null", "marker": True})
            else:
                bucket["objects"] = [o for o in bucket["objects"] if o["Key"] != key]
        return {}

    def _s3__delete_bucket(self, Bucket):
        if self.w.buckets[(self.a, Bucket)]["objects"]:
            raise RuntimeError("BucketNotEmpty: the bucket you tried to delete is not empty")
        del self.w.buckets[(self.a, Bucket)]
        return {}

    # --- iam (global) ---
    def _iam__list_roles(self, **_):
        return {"Roles": [{"RoleName": name, "Arn": f"arn:aws:iam::{account}:role/{name}"}
                          for (account, name) in self.w.roles if account == self.a], "IsTruncated": False}

    def _iam__create_role(self, RoleName, **_):
        self.w.roles[(self.a, RoleName)] = {"policies": {}}
        return {"Role": {"RoleName": RoleName, "Arn": f"arn:aws:iam::{self.a}:role/{RoleName}"}}

    def _iam__put_role_policy(self, RoleName, PolicyName, PolicyDocument):
        self.w.roles[(self.a, RoleName)]["policies"][PolicyName] = PolicyDocument
        return {}

    def _iam__list_role_policies(self, RoleName):
        return {"PolicyNames": list(self.w.roles[(self.a, RoleName)]["policies"])}

    def _iam__delete_role_policy(self, RoleName, PolicyName):
        del self.w.roles[(self.a, RoleName)]["policies"][PolicyName]
        return {}

    def _iam__delete_role(self, RoleName):
        if self.w.roles[(self.a, RoleName)]["policies"]:
            raise RuntimeError("DeleteConflict: cannot delete entity, must delete policies first")
        del self.w.roles[(self.a, RoleName)]
        return {}

    # --- bedrock-agent ---
    def _kb_arn(self, kb_id):
        return f"arn:aws:bedrock:{self.region}:{self.a}:knowledge-base/{kb_id}"

    def _bedrock_agent__list_knowledge_bases(self, **_):
        return {"knowledgeBaseSummaries": [
            {"knowledgeBaseId": kb_id, "name": kb["name"], "status": "ACTIVE"}
            for (account, region, kb_id), kb in self.w.kbs.items() if (account, region) == (self.a, self.region)]}

    def _bedrock_agent__create_knowledge_base(self, name, knowledgeBaseConfiguration, **_):
        kb_id = f"KB{self.w.next_id():08d}"
        self.w.kbs[(self.a, self.region, kb_id)] = {"name": name, "type": knowledgeBaseConfiguration["type"]}
        return {"knowledgeBase": {"knowledgeBaseId": kb_id, "name": name, "status": "ACTIVE",
                                  "knowledgeBaseArn": self._kb_arn(kb_id),
                                  "knowledgeBaseConfiguration": knowledgeBaseConfiguration}}

    def _bedrock_agent__get_knowledge_base(self, knowledgeBaseId):
        kb = self.w.kbs[(self.a, self.region, knowledgeBaseId)]
        return {"knowledgeBase": {"knowledgeBaseId": knowledgeBaseId, "name": kb["name"], "status": "ACTIVE",
                                  "knowledgeBaseConfiguration": {"type": kb["type"]}}}

    def _bedrock_agent__list_data_sources(self, knowledgeBaseId, **_):
        if (self.a, self.region, knowledgeBaseId) not in self.w.kbs:
            raise RuntimeError("ResourceNotFoundException: knowledge base not found")
        return {"dataSourceSummaries": [
            {"knowledgeBaseId": kb_id, "dataSourceId": ds_id, "name": ds["name"], "status": "AVAILABLE"}
            for (account, region, kb_id, ds_id), ds in self.w.data_sources.items()
            if (account, region, kb_id) == (self.a, self.region, knowledgeBaseId)]}

    def _bedrock_agent__create_data_source(self, knowledgeBaseId, name, **_):
        ds_id = f"DS{self.w.next_id():08d}"
        self.w.data_sources[(self.a, self.region, knowledgeBaseId, ds_id)] = {"name": name}
        return {"dataSource": {"dataSourceId": ds_id, "name": name, "status": "AVAILABLE"}}

    def _bedrock_agent__start_ingestion_job(self, **_):
        return {"ingestionJob": {"ingestionJobId": "JOB0000001", "status": "STARTING"}}

    def _bedrock_agent__get_ingestion_job(self, **_):
        documents = sum(1 for key in self.w.bucket_keys() if key.endswith(".txt"))
        return {"ingestionJob": {"ingestionJobId": "JOB0000001", "status": "COMPLETE", "statistics": {
            "numberOfDocumentsScanned": documents, "numberOfNewDocumentsIndexed": documents,
            "numberOfDocumentsFailed": 0, "numberOfDocumentsDeleted": 0}}}

    def _bedrock_agent__delete_data_source(self, knowledgeBaseId, dataSourceId):
        del self.w.data_sources[(self.a, self.region, knowledgeBaseId, dataSourceId)]
        return {}

    def _bedrock_agent__delete_knowledge_base(self, knowledgeBaseId):
        del self.w.kbs[(self.a, self.region, knowledgeBaseId)]
        return {}

    def _bedrock_agent_runtime__retrieve(self, **_):
        return {"retrievalResults": []}

    # --- bedrock (guardrails) ---
    def _guardrail_arn(self, guardrail_id):
        return f"arn:aws:bedrock:{self.region}:{self.a}:guardrail/{guardrail_id}"

    def _bedrock__list_guardrails(self, **_):
        return {"guardrails": [
            {"id": g_id, "name": g["name"], "status": "READY", "version": "DRAFT", "arn": self._guardrail_arn(g_id)}
            for (account, region, g_id), g in self.w.guardrails.items() if (account, region) == (self.a, self.region)]}

    def _bedrock__create_guardrail(self, name, contextualGroundingPolicyConfig=None, **_):
        g_id = f"gr{self.w.next_id():08d}"
        self.w.guardrails[(self.a, self.region, g_id)] = {
            "name": name, "versions": 0,
            "filters": [{"type": f["type"], "threshold": f["threshold"], "action": "BLOCK"}
                        for f in (contextualGroundingPolicyConfig or {}).get("filtersConfig", [])]}
        return {"guardrailId": g_id, "guardrailArn": self._guardrail_arn(g_id), "version": "DRAFT"}

    def _bedrock__create_guardrail_version(self, guardrailIdentifier, **_):
        guardrail = self.w.guardrails[(self.a, self.region, guardrailIdentifier)]
        guardrail["versions"] += 1
        return {"guardrailId": guardrailIdentifier, "version": str(guardrail["versions"])}

    def _bedrock__get_guardrail(self, guardrailIdentifier, **_):
        guardrail = self.w.guardrails[(self.a, self.region, guardrailIdentifier)]
        return {"status": "READY", "contextualGroundingPolicy": {"filters": guardrail.get("filters", [])}}

    def _bedrock__delete_guardrail(self, guardrailIdentifier):
        del self.w.guardrails[(self.a, self.region, guardrailIdentifier)]
        return {}

    def _bedrock__get_foundation_model(self, modelIdentifier):
        return {"modelDetails": {"modelId": modelIdentifier, "modelLifecycle": {"status": "ACTIVE"},
                                 "inferenceTypesSupported": ["ON_DEMAND"]}}

    def _bedrock__get_foundation_model_availability(self, modelId):
        return {"modelId": modelId, "authorizationStatus": "AUTHORIZED", "entitlementAvailability": "AVAILABLE",
                "regionAvailability": "AVAILABLE", "agreementAvailability": {"status": "AVAILABLE"}}

    def _bedrock__get_inference_profile(self, inferenceProfileIdentifier):
        return {"inferenceProfileId": inferenceProfileIdentifier, "status": "ACTIVE", "models": []}

    # --- s3vectors ---
    def _s3vectors__list_vector_buckets(self, prefix="", **_):
        return {"vectorBuckets": [
            {"vectorBucketName": name, "vectorBucketArn": f"arn:aws:s3vectors:{region}:{account}:bucket/{name}"}
            for (account, region, name) in self.w.vector_buckets
            if (account, region) == (self.a, self.region) and name.startswith(prefix)]}

    def _s3vectors__create_vector_bucket(self, vectorBucketName, **_):
        self.w.vector_buckets[(self.a, self.region, vectorBucketName)] = {"indexes": {}}
        return {"vectorBucketArn": f"arn:aws:s3vectors:{self.region}:{self.a}:bucket/{vectorBucketName}"}

    def _s3vectors__list_indexes(self, vectorBucketName, **_):
        indexes = self.w.vector_buckets[(self.a, self.region, vectorBucketName)]["indexes"]
        return {"indexes": [{"vectorBucketName": vectorBucketName, "indexName": name,
                             "indexArn": f"arn:aws:s3vectors:{self.region}:{self.a}:bucket/{vectorBucketName}/index/{name}"}
                            for name in indexes]}

    def _s3vectors__create_index(self, vectorBucketName, indexName, **params):
        self.w.vector_buckets[(self.a, self.region, vectorBucketName)]["indexes"][indexName] = params
        return {"indexArn": f"arn:aws:s3vectors:{self.region}:{self.a}:bucket/{vectorBucketName}/index/{indexName}"}

    def _s3vectors__delete_index(self, vectorBucketName, indexName):
        del self.w.vector_buckets[(self.a, self.region, vectorBucketName)]["indexes"][indexName]
        return {}

    def _s3vectors__delete_vector_bucket(self, vectorBucketName):
        if self.w.vector_buckets[(self.a, self.region, vectorBucketName)]["indexes"]:
            raise RuntimeError("ConflictException: the vector bucket still has indexes")
        del self.w.vector_buckets[(self.a, self.region, vectorBucketName)]
        return {}

    # --- OpenSearch Serverless, tags, quotas ---
    def _opensearchserverless__list_collections(self, **_):
        return {"collectionSummaries": [
            {"id": c_id, "name": name, "status": "ACTIVE"}
            for (account, region, c_id), name in self.w.collections.items() if (account, region) == (self.a, self.region)]}

    def _opensearchserverless__batch_get_collection(self, ids):
        return {"collectionDetails": [{"id": c_id, "type": "VECTORSEARCH"} for c_id in ids]}

    def _resourcegroupstaggingapi__get_resources(self, **_):
        here = (self.a, self.region)
        arns = [self._kb_arn(kb_id) for (account, region, kb_id) in self.w.kbs if (account, region) == here]
        arns += [self._guardrail_arn(g_id) for (account, region, g_id) in self.w.guardrails if (account, region) == here]
        arns += [f"arn:aws:s3vectors:{region}:{account}:bucket/{name}"
                 for (account, region, name) in self.w.vector_buckets if (account, region) == here]
        arns += [f"arn:aws:s3:::{name}" for (account, name), bucket in self.w.buckets.items()
                 if account == self.a and bucket["tags"] and bucket["region"] == self.region]
        if self.region == "us-east-1":       # IAM is global; its resources are reported in us-east-1
            arns += [f"arn:aws:iam::{account}:role/{name}" for (account, name) in self.w.roles if account == self.a]
        arns += [arn for (account, region, arn) in self.w.extra_tagged if (account, region) == here]
        return {"ResourceTagMappingList": [{"ResourceARN": arn} for arn in arns]}

    def _service_quotas__list_service_quotas(self, **_):
        return {"Quotas": []}


def install(monkeypatch, world: World) -> World:
    """Make every non-dry-run kitlib.aws.Aws object talk to `world`.

    Nothing in the fake takes time to become ready, so the only wait left is the pause for a
    new IAM role, which is set to zero.
    """
    from kitlib import resources

    def client(self, service):
        if self.dry_run:
            raise RuntimeError("dry-run must never create an AWS client")
        return FakeClient(world, service, self.region)

    monkeypatch.setattr(api.Aws, "client", client)
    monkeypatch.setattr(resources, "IAM_PROPAGATION_S", 0)
    return world


def load_script(name: str):
    spec = importlib.util.spec_from_file_location("kit_script_" + name[:2], KIT_DIR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(name: str, *args: str, env: dict | None = None) -> tuple[int, str]:
    """Run a numbered script in this process. Returns (exit code, everything it printed)."""
    saved = dict(os.environ)
    os.environ.update(env or {})
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                code = load_script(name).main(list(args))
            except SystemExit as stop:
                code = stop.code
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return (0 if code is None else code), buffer.getvalue()


def make_corpus(build_dir, doc_ids=("uc-0001", "uc-0002", "uc-0003")) -> None:
    """A tiny local corpus so 30_deploy_kb.py has something to upload."""
    corpus_dir = build_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(corpus_dir.glob("uc-*")):
        stale.unlink()
    for doc_id in doc_ids:
        (corpus_dir / f"{doc_id}.txt").write_text(f"document {doc_id}\n", encoding="utf-8")
        (corpus_dir / f"{doc_id}.txt.metadata.json").write_text('{"metadataAttributes": {}}\n', encoding="utf-8")
