"""Every AWS API call this kit makes lives in this file.

Each call carries the URL of the AWS page that describes it and the date the
page was read. NONE of these calls was run against AWS when the kit was
written: there was no AWS account. What was done instead:

  * the request shape of every call is checked offline against the API model
    shipped inside botocore 1.43.108 (tests/test_aws_shapes.py, again on every
    --dry-run, and by the fake account in tests/fakeaws.py);
  * the response parsers are tested with hand-built responses.

`# UNVERIFIED:` marks anything that could not be confirmed on a current AWS
page. The same items are listed in README section 8.
"""
from __future__ import annotations

import json
import time

from .evalloop import Passage
from . import corpus

DOCS_READ = "2026-10-07"
DRY_ACCOUNT = "000000000000"  # placeholder used only in --dry-run output; not a real account


# ----------------------------------------------------------------------------
# The caller: one place that either calls AWS or, in dry-run, prints the call.
# ----------------------------------------------------------------------------

class Aws:
    def __init__(self, region: str, dry_run: bool = False, canned: dict | None = None,
                 clients: dict | None = None, echo=print):
        self.region = region
        self.dry_run = dry_run
        self.calls: list[tuple[str, str, dict]] = []
        self._canned = dict(DRY_RESPONSES)
        self._canned.update(canned or {})
        self._clients = dict(clients or {})
        self._echo = echo
        self.quiet_dry_run = False

    def client(self, service: str):
        if self.dry_run:
            raise RuntimeError("dry-run must never create an AWS client")
        if service not in self._clients:
            import boto3
            from botocore.config import Config

            # DOC: https://docs.aws.amazon.com/boto3/latest/guide/retries.html (read 2026-10-07)
            # "standard" mode retries throttling errors with backoff; 8 attempts in total.
            config = Config(retries={"total_max_attempts": 8, "mode": "standard"},
                            user_agent_extra="aws-kits-kit-b")
            self._clients[service] = boto3.client(service, region_name=self.region, config=config)
        return self._clients[service]

    def call(self, service: str, operation: str, **params):
        self.calls.append((service, operation, params))
        if self.dry_run:
            validate_request(service, operation, params)
            if not self.quiet_dry_run:
                self._echo(f"DRY-RUN {service}.{operation} {_short(params)}")
            canned = self._canned.get((service, operation))
            return canned(params) if callable(canned) else (canned or {})
        return getattr(self.client(service), operation)(**params)


def _short(params: dict, limit: int = 420) -> str:
    def shrink(value):
        if isinstance(value, (bytes, bytearray)):
            return f"<{len(value)} bytes>"
        if isinstance(value, str) and len(value) > 160:
            return value[:157] + "..."
        if isinstance(value, dict):
            return {k: shrink(v) for k, v in value.items()}
        if isinstance(value, list):
            return [shrink(v) for v in value[:6]] + (["..."] if len(value) > 6 else [])
        return value
    text = json.dumps(shrink(params), sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit - 3] + "..."


_MODEL_CACHE: dict = {}


def validate_request(service: str, operation: str, params: dict) -> None:
    """Check a request against the API model inside botocore. Offline; no client, no network."""
    import botocore.session
    from botocore import xform_name
    from botocore.validate import validate_parameters

    if service not in _MODEL_CACHE:
        model = botocore.session.get_session().get_service_model(service)
        _MODEL_CACHE[service] = (model, {xform_name(name): name for name in model.operation_names})
    model, names = _MODEL_CACHE[service]
    if operation not in names:
        raise ValueError(f"{service} has no operation {operation!r} in this botocore version")
    shape = model.operation_model(names[operation]).input_shape
    if shape is not None:
        validate_parameters(params, shape)   # names, required fields, types, lengths and ranges
        problems = _enum_problems(params, shape, operation)
        if problems:
            raise ValueError("value not in the API model's allowed list: " + "; ".join(problems))
    elif params:
        raise ValueError(f"{service}.{operation} takes no parameters")


def _enum_problems(value, shape, path: str) -> list[str]:
    """botocore does not check enum values, so do it here."""
    problems: list[str] = []
    kind = shape.type_name
    if kind == "structure" and isinstance(value, dict):
        for key, member in shape.members.items():
            if key in value:
                problems += _enum_problems(value[key], member, f"{path}.{key}")
    elif kind == "list" and isinstance(value, list):
        for index, element in enumerate(value):
            problems += _enum_problems(element, shape.member, f"{path}[{index}]")
    elif kind == "map" and isinstance(value, dict):
        for key, element in value.items():
            problems += _enum_problems(element, shape.value, f"{path}.{key}")
    elif kind == "string" and getattr(shape, "enum", None) and isinstance(value, str):
        if value not in shape.enum:
            problems.append(f"{path}={value!r} (allowed: {shape.enum})")
    return problems


def error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "") if hasattr(exc, "response") else ""


def paginate(aws: Aws, service: str, operation: str, result_key: str, token_in: str,
             token_out: str | None = None, max_pages: int = 200, **params) -> list:
    """Collect one list across pages. Works for the token styles used below."""
    token_out = token_out or token_in
    items: list = []
    token = None
    for _ in range(max_pages):
        request = dict(params)
        if token:
            request[token_in] = token
        response = aws.call(service, operation, **request)
        items.extend(response.get(result_key) or [])
        token = response.get(token_out)
        if not token:
            break
    return items


def wait_until(check, describe: str, timeout_s: int = 900, interval_s: int = 10,
               sleep=time.sleep, echo=print):
    """Poll check() until it returns a truthy value. Raises TimeoutError after timeout_s."""
    waited = 0
    while True:
        result = check()
        if result:
            return result
        if waited >= timeout_s:
            raise TimeoutError(f"timed out after {timeout_s}s waiting for {describe}")
        echo(f"  ... waiting for {describe} ({waited}s)")
        sleep(interval_s)
        waited += interval_s


# ----------------------------------------------------------------------------
# Identity, quotas, tags
# ----------------------------------------------------------------------------

def get_caller_identity(aws: Aws) -> dict:
    # DOC: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
    return aws.call("sts", "get_caller_identity")


def list_bedrock_quotas(aws: Aws) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_ListServiceQuotas.html (read 2026-10-07)
    # UNVERIFIED: that the Service Quotas service code for Amazon Bedrock is "bedrock".
    return paginate(aws, "service-quotas", "list_service_quotas", "Quotas", "NextToken",
                    ServiceCode="bedrock", MaxResults=100)


def get_tagged_resources(aws: Aws, tag_key: str, tag_value: str) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/resourcegroupstagging/latest/APIReference/API_GetResources.html (read 2026-10-07)
    # Only tagged or previously tagged resources in this Region are returned.
    return paginate(aws, "resourcegroupstaggingapi", "get_resources", "ResourceTagMappingList",
                    "PaginationToken", TagFilters=[{"Key": tag_key, "Values": [tag_value]}],
                    ResourcesPerPage=100)


# ----------------------------------------------------------------------------
# Amazon S3 (the document bucket)
# ----------------------------------------------------------------------------

def list_buckets(aws: Aws, prefix: str = "") -> list[dict]:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListBuckets.html (read 2026-10-07)
    # "Limits the response to bucket names that begin with the specified bucket name prefix."
    # With no prefix every bucket of the account is listed, in every Region.
    params: dict = {"MaxBuckets": 1000}
    if prefix:
        params["Prefix"] = prefix
    return paginate(aws, "s3", "list_buckets", "Buckets", "ContinuationToken", **params)


def create_bucket(aws: Aws, bucket: str) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateBucket.html (read 2026-10-07)
    # us-east-1 is the default and takes no LocationConstraint; other Regions need one.
    # New buckets have ACLs disabled (BucketOwnerEnforced) by default per the same page.
    params: dict = {"Bucket": bucket}
    if aws.region != "us-east-1":
        params["CreateBucketConfiguration"] = {"LocationConstraint": aws.region}
    return aws.call("s3", "create_bucket", **params)


def put_bucket_tagging(aws: Aws, bucket: str, tags: list[dict]) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketTagging.html (read 2026-10-07)
    return aws.call("s3", "put_bucket_tagging", Bucket=bucket, Tagging={"TagSet": tags})


def put_object(aws: Aws, bucket: str, key: str, body: bytes, content_type: str) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html (read 2026-10-07)
    return aws.call("s3", "put_object", Bucket=bucket, Key=key, Body=body, ContentType=content_type)


def list_object_keys(aws: Aws, bucket: str, key_prefix: str) -> list[str]:
    """Every current object key under key_prefix."""
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html (read 2026-10-07)
    # Up to 1,000 keys per page; NextContinuationToken is sent back as ContinuationToken.
    contents = paginate(aws, "s3", "list_objects_v2", "Contents", "ContinuationToken", "NextContinuationToken",
                        Bucket=bucket, Prefix=key_prefix, MaxKeys=1000)
    return [entry["Key"] for entry in contents]


def delete_object_keys(aws: Aws, bucket: str, keys: list[str]) -> int:
    """Delete the current version of each key. Used to take stale documents out of the corpus prefix."""
    for start in range(0, len(keys), 1000):
        # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html (read 2026-10-07)
        # At most 1,000 keys per request.
        result = aws.call("s3", "delete_objects", Bucket=bucket,
                          Delete={"Objects": [{"Key": key} for key in keys[start:start + 1000]], "Quiet": True})
        errors = result.get("Errors") or []
        if errors:
            raise RuntimeError(f"could not delete {len(errors)} object(s), first: {errors[0]}")
    return len(keys)


EMPTY_BUCKET_MAX_ROUNDS = 4


def empty_bucket(aws: Aws, bucket: str) -> int:
    """Delete every object, object version and delete marker. Returns how many delete entries were sent.

    Works in rounds and lists again after each one, so it only returns when a listing shows
    the bucket empty (or raises). Round 1 names a version id only when it is a real one,
    which is the documented way to delete from a bucket that was never versioned. If
    anything is still listed after that, the bucket has (or had) versioning switched on:
    later rounds name every version id exactly as listed, including "null".
    DOC: https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html (read 2026-10-07)
         "If S3 Versioning is not enabled, Amazon S3 sets the value of the version ID to null."
    DOC: https://docs.aws.amazon.com/AmazonS3/latest/userguide/ManagingDelMarkers.html (read 2026-10-07)
         "To delete a delete marker with a NULL version ID, you must pass the NULL as the version ID
         in the DeleteObject request."
    DOC: https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectsfromVersioningSuspendedBuckets.html
         (read 2026-10-07) "the bucket owner can permanently delete a specified version by including
         the version ID in the DELETE request".
    UNVERIFIED: that DeleteObjects (the multi-object call) accepts the literal version id "null" for an
    object VERSION the way the page above describes for a delete marker with DeleteObject. It is only
    sent in round 2 and later, which a bucket that was never versioned does not reach.
    """
    deleted = 0
    for round_number in range(1, EMPTY_BUCKET_MAX_ROUNDS + 1):
        listed = 0
        key_marker = version_marker = None
        while True:
            # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html (read 2026-10-07)
            params: dict = {"Bucket": bucket, "MaxKeys": 1000}
            if key_marker:
                params["KeyMarker"] = key_marker
            if version_marker:
                params["VersionIdMarker"] = version_marker
            page = aws.call("s3", "list_object_versions", **params)
            objects = []
            for entry in (page.get("Versions") or []) + (page.get("DeleteMarkers") or []):
                target = {"Key": entry["Key"]}
                version_id = entry.get("VersionId")
                if version_id and (version_id != "null" or round_number > 1):
                    target["VersionId"] = version_id
                objects.append(target)
            listed += len(objects)
            if objects:
                # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html (read 2026-10-07)
                # At most 1,000 keys per request.
                result = aws.call("s3", "delete_objects", Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
                errors = result.get("Errors") or []
                if errors:
                    raise RuntimeError(f"could not delete {len(errors)} object(s), first: {errors[0]}")
                deleted += len(objects)
            if not page.get("IsTruncated"):
                break
            key_marker = page.get("NextKeyMarker")
            version_marker = page.get("NextVersionIdMarker")
        if listed == 0 or aws.dry_run:
            return deleted
    raise RuntimeError(f"bucket {bucket} still lists objects, versions or delete markers after "
                       f"{EMPTY_BUCKET_MAX_ROUNDS} delete rounds. Empty it in the S3 console (Empty button), "
                       "then run teardown again.")


def delete_bucket(aws: Aws, bucket: str) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteBucket.html (read 2026-10-07)
    # All objects, versions and delete markers must be gone first.
    return aws.call("s3", "delete_bucket", Bucket=bucket)


# ----------------------------------------------------------------------------
# IAM (the role the knowledge base assumes)
# ----------------------------------------------------------------------------

def list_roles(aws: Aws) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListRoles.html (read 2026-10-07)
    # Tags are not returned by this operation, so roles are matched by name.
    roles: list = []
    marker = None
    while True:
        params: dict = {"MaxItems": 1000}
        if marker:
            params["Marker"] = marker
        page = aws.call("iam", "list_roles", **params)
        roles.extend(page.get("Roles") or [])
        if not page.get("IsTruncated"):
            return roles
        marker = page.get("Marker")


def create_role(aws: Aws, role_name: str, trust_policy: dict, tags: list[dict]) -> dict:
    # DOC: https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateRole.html (read 2026-10-07)
    return aws.call("iam", "create_role", RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="Service role for the aws-kits kit B Bedrock knowledge base",
                    Tags=tags)


def put_role_policy(aws: Aws, role_name: str, policy_name: str, policy: dict) -> dict:
    # DOC: https://docs.aws.amazon.com/IAM/latest/APIReference/API_PutRolePolicy.html (read 2026-10-07)
    return aws.call("iam", "put_role_policy", RoleName=role_name, PolicyName=policy_name,
                    PolicyDocument=json.dumps(policy))


def list_role_policies(aws: Aws, role_name: str) -> list[str]:
    # DOC: https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListRolePolicies.html (read 2026-10-07)
    return aws.call("iam", "list_role_policies", RoleName=role_name).get("PolicyNames") or []


def delete_role_policy(aws: Aws, role_name: str, policy_name: str) -> dict:
    # DOC: https://docs.aws.amazon.com/IAM/latest/APIReference/API_DeleteRolePolicy.html (read 2026-10-07)
    return aws.call("iam", "delete_role_policy", RoleName=role_name, PolicyName=policy_name)


def delete_role(aws: Aws, role_name: str) -> dict:
    # DOC: https://docs.aws.amazon.com/IAM/latest/APIReference/API_DeleteRole.html (read 2026-10-07)
    # Inline policies must be deleted first.
    return aws.call("iam", "delete_role", RoleName=role_name)


def kb_trust_policy(account_id: str, region: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-permissions.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html (read 2026-10-07)
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
                "ArnLike": {"AWS:SourceArn": f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/*"},
            },
        }],
    }


def kb_permissions_policy(account_id: str, region: str, bucket: str, kb_type: str,
                          embed_model_id: str = "", vector_index_arn: str = "") -> dict:
    """Least-privilege inline policy for the knowledge base role.

    S3 statements: same two pages as kb_trust_policy.
    For KB_TYPE=managed with the managed embedding model no bedrock:InvokeModel
    statement is added, because no model in your account is invoked.
    UNVERIFIED: that the managed type needs nothing beyond the S3 statements and the
    model-list statement (the page lists statements but not which are required when
    the embedding model is service-managed; the AWS sample adds only S3 and a
    CloudWatch metrics statement in that case).
    """
    statements = [
        {"Sid": "S3ListBucketStatement", "Effect": "Allow", "Action": ["s3:ListBucket"],
         "Resource": [f"arn:aws:s3:::{bucket}"],
         "Condition": {"StringEquals": {"aws:ResourceAccount": account_id}}},
        {"Sid": "S3GetObjectStatement", "Effect": "Allow", "Action": ["s3:GetObject"],
         "Resource": [f"arn:aws:s3:::{bucket}/*"],
         "Condition": {"StringEquals": {"aws:ResourceAccount": account_id}}},
        {"Sid": "BedrockListModelsStatement", "Effect": "Allow",
         "Action": ["bedrock:ListFoundationModels", "bedrock:ListCustomModels"], "Resource": "*"},
    ]
    if kb_type == "s3vectors":
        statements.append({
            "Sid": "BedrockInvokeEmbeddingModelStatement", "Effect": "Allow",
            "Action": ["bedrock:InvokeModel"],
            "Resource": [f"arn:aws:bedrock:{region}::foundation-model/{embed_model_id}"]})
        # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html (read 2026-10-07)
        statements.append({
            "Sid": "S3VectorBucketReadAndWritePermission", "Effect": "Allow",
            "Action": ["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                       "s3vectors:QueryVectors", "s3vectors:GetIndex"],
            "Resource": vector_index_arn})
    return {"Version": "2012-10-17", "Statement": statements}


# ----------------------------------------------------------------------------
# Amazon S3 Vectors (only when KB_TYPE=s3vectors)
# ----------------------------------------------------------------------------

def list_vector_buckets(aws: Aws, prefix: str = "") -> list[dict]:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListVectorBuckets.html (read 2026-10-07)
    params: dict = {"maxResults": 500}
    if prefix:
        params["prefix"] = prefix
    return paginate(aws, "s3vectors", "list_vector_buckets", "vectorBuckets", "nextToken", **params)


def create_vector_bucket(aws: Aws, name: str, tags: dict) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_CreateVectorBucket.html (read 2026-10-07)
    return aws.call("s3vectors", "create_vector_bucket", vectorBucketName=name, tags=tags)


def list_vector_indexes(aws: Aws, vector_bucket: str) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListIndexes.html (read 2026-10-07)
    return paginate(aws, "s3vectors", "list_indexes", "indexes", "nextToken",
                    vectorBucketName=vector_bucket, maxResults=500)


def create_vector_index(aws: Aws, vector_bucket: str, index: str, dimension: int, tags: dict) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_CreateIndex.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html (read 2026-10-07)
    # The second page says to add AMAZON_BEDROCK_TEXT and AMAZON_BEDROCK_METADATA as
    # non-filterable metadata keys, and that only float32 embeddings are supported.
    return aws.call("s3vectors", "create_index", vectorBucketName=vector_bucket, indexName=index,
                    dataType="float32", dimension=dimension, distanceMetric="cosine",
                    metadataConfiguration={"nonFilterableMetadataKeys": [
                        "AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]},
                    tags=tags)


def delete_vector_index(aws: Aws, vector_bucket: str, index: str) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_DeleteIndex.html (read 2026-10-07)
    return aws.call("s3vectors", "delete_index", vectorBucketName=vector_bucket, indexName=index)


def delete_vector_bucket(aws: Aws, vector_bucket: str) -> dict:
    # DOC: https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_DeleteVectorBucket.html (read 2026-10-07)
    # "All vector indexes in the vector bucket must be deleted before the vector bucket can be deleted."
    return aws.call("s3vectors", "delete_vector_bucket", vectorBucketName=vector_bucket)


# ----------------------------------------------------------------------------
# Amazon Bedrock Knowledge Bases (control plane: bedrock-agent)
# ----------------------------------------------------------------------------

def list_knowledge_bases(aws: Aws) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_ListKnowledgeBases.html (read 2026-10-07)
    return paginate(aws, "bedrock-agent", "list_knowledge_bases", "knowledgeBaseSummaries", "nextToken",
                    maxResults=1000)


def create_managed_knowledge_base(aws: Aws, name: str, role_arn: str, tags: dict) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateKnowledgeBase.html (read 2026-10-07)
    # type MANAGED needs no storageConfiguration. embeddingModelType MANAGED uses the
    # service-managed embedding model, priced at $0 on the Bedrock pricing page.
    return aws.call(
        "bedrock-agent", "create_knowledge_base",
        name=name,
        description="aws-kits kit B: OMB 2025 federal AI use case inventory (unofficial demo)",
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "MANAGED",
            "managedKnowledgeBaseConfiguration": {"embeddingModelType": "MANAGED"},
        },
        tags=tags,
    )["knowledgeBase"]


def create_s3vectors_knowledge_base(aws: Aws, name: str, role_arn: str, embed_model_arn: str,
                                    dimensions: int, vector_bucket_arn: str, index_arn: str,
                                    tags: dict) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateKnowledgeBase.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html (read 2026-10-07)
    # The user-guide table calls the index field "vectorIndexARN"; the API model in
    # botocore 1.43.108 names it "indexArn", which is what is sent here.
    return aws.call(
        "bedrock-agent", "create_knowledge_base",
        name=name,
        description="aws-kits kit B: OMB 2025 federal AI use case inventory (unofficial demo)",
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": embed_model_arn,
                "embeddingModelConfiguration": {"bedrockEmbeddingModelConfiguration": {
                    "dimensions": dimensions, "embeddingDataType": "FLOAT32"}},
            },
        },
        storageConfiguration={
            "type": "S3_VECTORS",
            "s3VectorsConfiguration": {"vectorBucketArn": vector_bucket_arn, "indexArn": index_arn},
        },
        tags=tags,
    )["knowledgeBase"]


def get_knowledge_base(aws: Aws, kb_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_GetKnowledgeBase.html (read 2026-10-07)
    return aws.call("bedrock-agent", "get_knowledge_base", knowledgeBaseId=kb_id)["knowledgeBase"]


def list_data_sources(aws: Aws, kb_id: str) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_ListDataSources.html (read 2026-10-07)
    return paginate(aws, "bedrock-agent", "list_data_sources", "dataSourceSummaries", "nextToken",
                    knowledgeBaseId=kb_id, maxResults=1000)


def create_managed_s3_data_source(aws: Aws, kb_id: str, name: str, bucket: str, account_id: str,
                                  key_prefix: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-s3.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateDataSource.html (read 2026-10-07)
    # connectorParameters is a free-form document in the API model, so botocore cannot
    # check its inner fields. They are copied from the two user-guide pages above.
    # For managed knowledge bases only dataDeletionPolicy DELETE is supported.
    # Chunking is left at the service default, which for a managed knowledge base is documented:
    # "the service uses fixed-size chunking with 300 tokens and 20% overlap".
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html (read 2026-10-07)
    # Deletion protection (the OUTER deletionProtectionConfiguration) is documented:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-connect-ds.html (read 2026-10-07)
    #   "A safeguard against accidental bulk deletion of indexed content. ... The threshold is the maximum
    #    percentage of documents that a sync job can delete from your index. If a sync would delete more than
    #    this percentage, the sync skips its delete phase, leaving your indexed documents in place."
    # It is set to DISABLED on purpose: after a corpus rebuild the deploy step removes the old
    # documents from the bucket and the next sync must be allowed to delete them from the index,
    # however many they are.
    # UNVERIFIED: the INNER connectorParameters.deletionProtectionConfiguration.enableDeletionProtection.
    # It appears, set to false, in the kb-managed-create example and nowhere with a description.
    return aws.call(
        "bedrock-agent", "create_data_source",
        knowledgeBaseId=kb_id,
        name=name,
        description="OMB inventory documents in S3 (unofficial demo)",
        dataSourceConfiguration={
            "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR",
            "managedKnowledgeBaseConnectorConfiguration": {
                "connectorParameters": {
                    "type": "S3",
                    "version": "1",
                    "connectionConfiguration": {"bucketName": bucket, "bucketOwnerAccountId": account_id},
                    "filterConfiguration": {"inclusionPrefixes": [key_prefix]},
                    "deletionProtectionConfiguration": {"enableDeletionProtection": False},
                },
                "deletionProtectionConfiguration": {"deletionProtectionStatus": "DISABLED"},
            },
        },
        dataDeletionPolicy="DELETE",
        vectorIngestionConfiguration={"parsingConfiguration": {"parsingStrategy": "SMART_PARSING"}},
    )["dataSource"]


def create_vector_s3_data_source(aws: Aws, kb_id: str, name: str, bucket: str, account_id: str,
                                 key_prefix: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateDataSource.html (read 2026-10-07)
    # dataDeletionPolicy DELETE removes the vectors when the data source is deleted;
    # the vector index and vector bucket themselves are NOT deleted (see teardown).
    return aws.call(
        "bedrock-agent", "create_data_source",
        knowledgeBaseId=kb_id,
        name=name,
        description="OMB inventory documents in S3 (unofficial demo)",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {"bucketArn": f"arn:aws:s3:::{bucket}",
                                "bucketOwnerAccountId": account_id,
                                "inclusionPrefixes": [key_prefix]},
        },
        dataDeletionPolicy="DELETE",
    )["dataSource"]


def start_ingestion_job(aws: Aws, kb_id: str, data_source_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_StartIngestionJob.html (read 2026-10-07)
    return aws.call("bedrock-agent", "start_ingestion_job", knowledgeBaseId=kb_id,
                    dataSourceId=data_source_id)["ingestionJob"]


def get_ingestion_job(aws: Aws, kb_id: str, data_source_id: str, job_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_GetIngestionJob.html (read 2026-10-07)
    return aws.call("bedrock-agent", "get_ingestion_job", knowledgeBaseId=kb_id,
                    dataSourceId=data_source_id, ingestionJobId=job_id)["ingestionJob"]


def delete_data_source(aws: Aws, kb_id: str, data_source_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_DeleteDataSource.html (read 2026-10-07)
    return aws.call("bedrock-agent", "delete_data_source", knowledgeBaseId=kb_id, dataSourceId=data_source_id)


def delete_knowledge_base(aws: Aws, kb_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_DeleteKnowledgeBase.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-delete.html (read 2026-10-07)
    # "the vector store itself is not deleted if you delete a knowledge base or data source resource."
    return aws.call("bedrock-agent", "delete_knowledge_base", knowledgeBaseId=kb_id)


# ----------------------------------------------------------------------------
# Retrieval (data plane: bedrock-agent-runtime)
# ----------------------------------------------------------------------------

# What the kit asks for when it queries a managed knowledge base. Sent explicitly so the
# results table can say what was measured instead of relying on a default.
# DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html (read 2026-10-07)
#   "Retrieval always uses hybrid search, which combines keyword and semantic search. Semantic-only
#    search is not available for fully managed knowledge bases."
#   "Reranking is enabled by default using a service-managed reranking model. You can control
#    reranking behavior with the rerankingModelType field in managedSearchConfiguration:
#    MANAGED (default) ... CUSTOM ... NONE - Reranking is disabled."
MANAGED_RERANKING_MODEL_TYPE = "MANAGED"


def describe_retrieval(kb_type: str) -> str:
    """One line for the results table: what kind of search produced the hit rate."""
    if kb_type == "managed":
        return ("managed knowledge base: hybrid search (keyword plus semantic, the only kind this type offers) "
                f"with re-ranking by the service-managed model, sent as rerankingModelType="
                f"{MANAGED_RERANKING_MODEL_TYPE}")
    return ("S3 Vectors knowledge base: vector search with the service's default ranking; "
            "no re-ranking model was configured")


def retrieval_configuration(kb_type: str, top_k: int, metadata_filter: dict | None = None) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html (read 2026-10-07)
    # "Use managedSearchConfiguration ... instead of vectorSearchConfiguration. The
    # vectorSearchConfiguration field is used for custom knowledge bases only."
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_ManagedSearchConfiguration.html
    # (read 2026-10-07): numberOfResults 1 to 100; rerankingModelType CUSTOM | MANAGED | NONE,
    # "MANAGED to use the service default".
    if kb_type == "managed":
        inner: dict = {"numberOfResults": top_k, "rerankingModelType": MANAGED_RERANKING_MODEL_TYPE}
        key = "managedSearchConfiguration"
    else:
        inner = {"numberOfResults": top_k}
        key = "vectorSearchConfiguration"
    if metadata_filter:
        inner["filter"] = metadata_filter
    return {key: inner}


def retrieve(aws: Aws, kb_id: str, kb_type: str, query: str, top_k: int,
             metadata_filter: dict | None = None) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html (read 2026-10-07)
    return aws.call("bedrock-agent-runtime", "retrieve", knowledgeBaseId=kb_id,
                    retrievalQuery={"text": query},
                    retrievalConfiguration=retrieval_configuration(kb_type, top_k, metadata_filter))


def parse_retrieve_response(response: dict) -> list[Passage]:
    """Turn a Retrieve response into passages. The source document id comes from the
    S3 URI in `location`, or failing that from our own `doc_id` metadata attribute.

    The AWS sample rag/managed-knowledge-bases/01-getting-started/01-create-bmkb-s3.ipynb
    reads location.s3Location.uri the same way for a managed knowledge base.
    UNVERIFIED: the shape of `location` for a managed knowledge base beyond that sample. So the
    parser also looks at every other string inside `location` and `metadata` for a name of the
    form uc-NNNN.txt. A passage whose id still cannot be read gets doc_id None; the evaluation
    counts those and says so instead of reporting a hit rate of zero.
    """
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for inner in value.values():
                yield from strings(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from strings(inner)

    passages = []
    for result in response.get("retrievalResults") or []:
        location, metadata = result.get("location") or {}, result.get("metadata") or {}
        uri = (location.get("s3Location") or {}).get("uri")
        doc_id = corpus.doc_id_from_uri(uri or "")
        if not doc_id:
            meta_value = metadata.get("doc_id")
            if isinstance(meta_value, str) and corpus.is_doc_id(meta_value):
                doc_id = meta_value
        if not doc_id:
            for candidate in list(strings(location)) + list(strings(metadata)):
                doc_id = corpus.doc_id_from_uri(candidate)
                if doc_id:
                    uri = uri or candidate
                    break
        passages.append(Passage(text=(result.get("content") or {}).get("text") or "",
                                doc_id=doc_id, score=result.get("score"), uri=uri))
    return passages


# ----------------------------------------------------------------------------
# Models (control plane: bedrock; data plane: bedrock-runtime)
# ----------------------------------------------------------------------------

def get_foundation_model(aws: Aws, model_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetFoundationModel.html (read 2026-10-07)
    return aws.call("bedrock", "get_foundation_model", modelIdentifier=model_id).get("modelDetails") or {}


def get_foundation_model_availability(aws: Aws, model_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetFoundationModelAvailability.html (read 2026-10-07)
    return aws.call("bedrock", "get_foundation_model_availability", modelId=model_id)


def get_inference_profile(aws: Aws, profile_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetInferenceProfile.html (read 2026-10-07)
    return aws.call("bedrock", "get_inference_profile", inferenceProfileIdentifier=profile_id)


def converse(aws: Aws, model_id: str, system: str, user: str, max_tokens: int) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html (read 2026-10-07)
    # modelId may be a model id or an inference profile id. Temperature 0 for repeatable answers.
    return aws.call("bedrock-runtime", "converse", modelId=model_id,
                    system=[{"text": system}],
                    messages=[{"role": "user", "content": [{"text": user}]}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": 0.0})


def parse_converse_response(response: dict) -> dict:
    content = ((response.get("output") or {}).get("message") or {}).get("content") or []
    text = "".join(block.get("text", "") for block in content if isinstance(block, dict))
    usage = response.get("usage") or {}
    return {"text": text.strip(), "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0), "stop_reason": response.get("stopReason")}


# ----------------------------------------------------------------------------
# Guardrails
# ----------------------------------------------------------------------------

def list_guardrails(aws: Aws) -> list[dict]:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListGuardrails.html (read 2026-10-07)
    return paginate(aws, "bedrock", "list_guardrails", "guardrails", "nextToken", maxResults=1000)


def create_grounding_guardrail(aws: Aws, name: str, grounding_threshold: float,
                               relevance_threshold: float, tags: list[dict]) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrail.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html (read 2026-10-07)
    # Only the contextual grounding policy is configured: GROUNDING (is the answer supported by
    # the source?) and RELEVANCE (does it answer the query?). Thresholds 0 to 0.99.
    return aws.call(
        "bedrock", "create_guardrail",
        name=name,
        description="aws-kits kit B: contextual grounding check only",
        contextualGroundingPolicyConfig={"filtersConfig": [
            {"type": "GROUNDING", "threshold": grounding_threshold, "action": "BLOCK"},
            {"type": "RELEVANCE", "threshold": relevance_threshold, "action": "BLOCK"},
        ]},
        blockedInputMessaging="[kit B] The input was blocked by the guardrail.",
        blockedOutputsMessaging="[kit B] The answer was blocked by the contextual grounding check.",
        tags=tags,
    )


def create_guardrail_version(aws: Aws, guardrail_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateGuardrailVersion.html (read 2026-10-07)
    return aws.call("bedrock", "create_guardrail_version", guardrailIdentifier=guardrail_id,
                    description="version used by the kit B evaluation")


def get_guardrail(aws: Aws, guardrail_id: str, version: str | None = None) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetGuardrail.html (read 2026-10-07)
    params = {"guardrailIdentifier": guardrail_id}
    if version:
        params["guardrailVersion"] = version
    return aws.call("bedrock", "get_guardrail", **params)


def delete_guardrail(aws: Aws, guardrail_id: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_DeleteGuardrail.html (read 2026-10-07)
    # With no guardrailVersion, the guardrail and all of its versions are deleted.
    return aws.call("bedrock", "delete_guardrail", guardrailIdentifier=guardrail_id)


def apply_grounding_guardrail(aws: Aws, guardrail_id: str, version: str, sources: str,
                              question: str, answer: str) -> dict:
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html (read 2026-10-07)
    # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html (read 2026-10-07)
    # Qualifiers: grounding_source = the retrieved passages, query = the question,
    # guard_content = the generated answer to be checked. source OUTPUT = model output.
    # Same call pattern as the AWS sample aws-samples/amazon-bedrock-samples,
    # responsible_ai/bedrock-guardrails/bedrock_guardrails_apply_guardrail_api.ipynb (commit b5ad367).
    # outputScope, same API page: "Set to FULL to return the entire output, including any detected
    # and non-detected entries in the response for enhanced debugging." Valid values INTERVENTIONS | FULL.
    # UNVERIFIED: whether, without FULL, the grounding and relevance scores come back for an answer
    # that was NOT blocked. FULL is sent so the scores of passing answers are recorded as well.
    return aws.call(
        "bedrock-runtime", "apply_guardrail",
        guardrailIdentifier=guardrail_id, guardrailVersion=version, source="OUTPUT", outputScope="FULL",
        content=[
            {"text": {"text": sources, "qualifiers": ["grounding_source"]}},
            {"text": {"text": question, "qualifiers": ["query"]}},
            {"text": {"text": answer, "qualifiers": ["guard_content"]}},
        ])


def parse_guardrail_response(response: dict) -> dict:
    """Action, the two scores, and the text units AWS says it processed (what is billed)."""
    scores: dict = {}
    for assessment in response.get("assessments") or []:
        for item in (assessment.get("contextualGroundingPolicy") or {}).get("filters") or []:
            scores[item.get("type")] = item.get("score")
    usage = response.get("usage") or {}
    return {"action": response.get("action"),
            "grounding_score": scores.get("GROUNDING"),
            "relevance_score": scores.get("RELEVANCE"),
            "units": usage.get("contextualGroundingPolicyUnits", 0)}


# ----------------------------------------------------------------------------
# OpenSearch Serverless: this kit never creates a collection. It only looks.
# ----------------------------------------------------------------------------

def list_opensearch_serverless_collections(aws: Aws) -> list[dict]:
    """Every OpenSearch Serverless collection in the account and Region, with its type."""
    # DOC: https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_ListCollections.html (read 2026-10-07)
    summaries = paginate(aws, "opensearchserverless", "list_collections", "collectionSummaries",
                         "nextToken", maxResults=100)
    details: dict = {}
    ids = [s["id"] for s in summaries if s.get("id")]
    for start in range(0, len(ids), 100):
        # DOC: https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_BatchGetCollection.html (read 2026-10-07)
        batch = aws.call("opensearchserverless", "batch_get_collection", ids=ids[start:start + 100])
        for detail in batch.get("collectionDetails") or []:
            details[detail.get("id")] = detail
    return [{**summary, **details.get(summary.get("id"), {})} for summary in summaries]


# ----------------------------------------------------------------------------
# The backend the evaluation loop talks to
# ----------------------------------------------------------------------------

class BedrockBackend:
    def __init__(self, aws: Aws, kb_id: str, kb_type: str, top_k: int, gen_model_id: str,
                 judge_model_id: str, guardrail_id: str | None, guardrail_version: str | None):
        self.aws = aws
        self.kb_id, self.kb_type, self.top_k = kb_id, kb_type, top_k
        self.gen_model_id, self.judge_model_id = gen_model_id, judge_model_id
        self.guardrail_id, self.guardrail_version = guardrail_id, guardrail_version

    def retrieve(self, question: str) -> list[Passage]:
        return parse_retrieve_response(retrieve(self.aws, self.kb_id, self.kb_type, question, self.top_k))

    def generate(self, system: str, user: str) -> dict:
        return parse_converse_response(converse(self.aws, self.gen_model_id, system, user, max_tokens=200))

    def judge(self, system: str, user: str) -> dict:
        return parse_converse_response(converse(self.aws, self.judge_model_id, system, user, max_tokens=120))

    def apply_guardrail(self, sources: str, question: str, answer: str) -> dict:
        return parse_guardrail_response(apply_grounding_guardrail(
            self.aws, self.guardrail_id, self.guardrail_version, sources, question, answer))


# ----------------------------------------------------------------------------
# Canned responses for --dry-run, so each script can walk its whole path.
# ----------------------------------------------------------------------------

def _dry_arn(kind: str, name: str, region: str = "us-east-1") -> str:
    return f"arn:aws:{kind}:{region}:{DRY_ACCOUNT}:{name}"


DRY_RESPONSES: dict = {
    ("sts", "get_caller_identity"): {"Account": DRY_ACCOUNT, "UserId": "DRYRUN",
                                     "Arn": f"arn:aws:iam::{DRY_ACCOUNT}:user/dry-run"},
    ("s3", "list_buckets"): {"Buckets": []},
    ("s3", "list_object_versions"): {"Versions": [], "IsTruncated": False},
    ("iam", "list_roles"): {"Roles": [], "IsTruncated": False},
    ("iam", "create_role"): lambda p: {"Role": {
        "RoleName": p["RoleName"], "Arn": f"arn:aws:iam::{DRY_ACCOUNT}:role/{p['RoleName']}"}},
    ("iam", "list_role_policies"): {"PolicyNames": []},
    ("s3vectors", "list_vector_buckets"): {"vectorBuckets": []},
    ("s3vectors", "list_indexes"): {"indexes": []},
    ("s3vectors", "create_vector_bucket"): lambda p: {
        "vectorBucketArn": _dry_arn("s3vectors", f"bucket/{p['vectorBucketName']}")},
    ("s3vectors", "create_index"): lambda p: {
        "indexArn": _dry_arn("s3vectors", f"bucket/{p['vectorBucketName']}/index/{p['indexName']}")},
    ("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": []},
    ("bedrock-agent", "create_knowledge_base"): lambda p: {"knowledgeBase": {
        "knowledgeBaseId": "DRYRUNKB01", "name": p["name"], "status": "ACTIVE",
        "knowledgeBaseArn": _dry_arn("bedrock", "knowledge-base/DRYRUNKB01")}},
    ("bedrock-agent", "get_knowledge_base"): lambda p: {"knowledgeBase": {
        "knowledgeBaseId": p["knowledgeBaseId"], "status": "ACTIVE"}},
    ("bedrock-agent", "list_data_sources"): {"dataSourceSummaries": []},
    ("bedrock-agent", "create_data_source"): lambda p: {"dataSource": {
        "dataSourceId": "DRYRUNDS01", "name": p["name"], "status": "AVAILABLE"}},
    ("bedrock-agent", "start_ingestion_job"): {"ingestionJob": {
        "ingestionJobId": "DRYRUNJOB1", "status": "COMPLETE", "statistics": {}}},
    ("bedrock-agent", "get_ingestion_job"): {"ingestionJob": {
        "ingestionJobId": "DRYRUNJOB1", "status": "COMPLETE", "statistics": {}}},
    ("bedrock-agent-runtime", "retrieve"): {"retrievalResults": [{
        "content": {"text": "(dry-run passage)"}, "score": 0.0,
        "location": {"type": "S3", "s3Location": {"uri": "s3://dry-run/corpus/uc-0000.txt"}}}]},
    ("bedrock-runtime", "converse"): {
        "output": {"message": {"role": "assistant", "content": [{"text": "(dry-run text)"}]}},
        "stopReason": "end_turn", "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}},
    ("bedrock-runtime", "apply_guardrail"): {"action": "NONE", "assessments": [], "outputs": [],
                                             "usage": {"contextualGroundingPolicyUnits": 0}},
    ("bedrock", "list_guardrails"): {"guardrails": []},
    ("bedrock", "create_guardrail"): {"guardrailId": "dryrunguardrail", "version": "DRAFT",
                                      "guardrailArn": _dry_arn("bedrock", "guardrail/dryrunguardrail")},
    ("bedrock", "create_guardrail_version"): {"guardrailId": "dryrunguardrail", "version": "1"},
    ("bedrock", "get_guardrail"): {"guardrailId": "dryrunguardrail", "status": "READY", "version": "1"},
    ("bedrock", "get_foundation_model"): lambda p: {"modelDetails": {
        "modelId": p["modelIdentifier"], "modelLifecycle": {"status": "(dry-run)"}}},
    ("bedrock", "get_foundation_model_availability"): lambda p: {
        "modelId": p["modelId"], "authorizationStatus": "(dry-run)",
        "entitlementAvailability": "(dry-run)", "regionAvailability": "(dry-run)",
        "agreementAvailability": {"status": "(dry-run)"}},
    ("bedrock", "get_inference_profile"): lambda p: {
        "inferenceProfileId": p["inferenceProfileIdentifier"], "status": "(dry-run)", "models": []},
    ("opensearchserverless", "list_collections"): {"collectionSummaries": []},
    ("service-quotas", "list_service_quotas"): {"Quotas": []},
    ("resourcegroupstaggingapi", "get_resources"): {"ResourceTagMappingList": []},
}
