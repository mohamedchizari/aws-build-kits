"""Test helpers: stubbed boto3 clients. No network, no credentials."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import boto3
from botocore.stub import Stubber


class Err:
    """A stubbed AWS error response."""

    def __init__(self, code: str, message: str = "stubbed error", status: int = 400):
        self.code, self.message, self.status = code, message, status


def real_client(service: str, region: str = "us-east-1") -> Any:
    # Dummy keys; the Stubber answers before anything is signed or sent.
    return boto3.client(service, region_name=region, aws_access_key_id="testing", aws_secret_access_key="testing")


# The calls the audit makes in an empty account, per check, in run order.
# check_id -> (boto3 client name, [(method, response, expected_params), ...])
# "caller_identity" is the one call main() makes before the per-Region checks.
LOG_GROUP_QUERIES = [
    {"logGroupNamePrefix": "/aws/sagemaker/Endpoints/", "limit": 50},
    {"logGroupNamePrefix": "/aws/bedrock-agentcore/", "limit": 50},
    {"logGroupNamePrefix": "/aws/vendedlogs/bedrock-agentcore/", "limit": 50},
    {"logGroupNamePrefix": "aws/spans", "limit": 50},
]


def log_group_steps(prefix_forms: tuple[str, ...] = ("kitdemo",), found: dict[int, list[dict[str, Any]]] | None = None):
    """The DescribeLogGroups calls for one Region: the four fixed name prefixes, then one pattern per prefix form."""
    queries = LOG_GROUP_QUERIES + [{"logGroupNamePattern": form, "limit": 50} for form in prefix_forms]
    return [("describe_log_groups", {"logGroups": (found or {}).get(n, [])}, query) for n, query in enumerate(queries)]


def empty_plan(identity: bool = True, region: str = "us-east-1", prefix_forms: tuple[str, ...] = ("kitdemo",)) -> dict[str, tuple[str, list[tuple[str, Any, Any]]]]:
    plan: dict[str, tuple[str, list[tuple[str, Any, Any]]]] = {}
    if identity:
        plan["caller_identity"] = ("sts", [("get_caller_identity", {"Account": "111122223333", "UserId": "AIDAEXAMPLE", "Arn": "arn:aws:iam::111122223333:user/example"}, {})])
    plan.update({
        "sm_endpoints": ("sagemaker", [("list_endpoints", {"Endpoints": []}, {"MaxResults": 100})]),
        "sm_endpoint_configs": ("sagemaker", [("list_endpoint_configs", {"EndpointConfigs": []}, {"MaxResults": 100})]),
        "sm_models": ("sagemaker", [("list_models", {"Models": []}, {"MaxResults": 100})]),
        "sm_inference_components": ("sagemaker", [("list_inference_components", {"InferenceComponents": []}, {"MaxResults": 100})]),
        "sm_training_jobs": ("sagemaker", [("list_training_jobs", {"TrainingJobSummaries": []}, {"MaxResults": 100})]),
        "sm_notebooks": ("sagemaker", [("list_notebook_instances", {"NotebookInstances": []}, {"MaxResults": 100})]),
        "sm_apps": ("sagemaker", [("list_apps", {"Apps": []}, {"MaxResults": 100})]),
        "sm_spaces": ("sagemaker", [("list_spaces", {"Spaces": []}, {"MaxResults": 100})]),
        "br_knowledge_bases": ("bedrock-agent", [("list_knowledge_bases", {"knowledgeBaseSummaries": []}, {"maxResults": 100})]),
        "br_guardrails": ("bedrock", [("list_guardrails", {"guardrails": []}, {"maxResults": 100})]),
        "br_provisioned": ("bedrock", [("list_provisioned_model_throughputs", {"provisionedModelSummaries": []}, {"maxResults": 100})]),
        "br_custom_models": ("bedrock", [("list_custom_models", {"modelSummaries": []}, {"maxResults": 100})]),
        "br_imported_models": ("bedrock", [("list_imported_models", {"modelSummaries": []}, {"maxResults": 100})]),
        "br_custom_model_deployments": ("bedrock", [("list_custom_model_deployments", {"modelDeploymentSummaries": []}, {"maxResults": 100})]),
        "aoss_collections": ("opensearchserverless", [("list_collections", {"collectionSummaries": []}, {"maxResults": 100})]),
        "aoss_collection_groups": ("opensearchserverless", [("list_collection_groups", {"collectionGroupSummaries": []}, {"maxResults": 100})]),
        "s3vectors": ("s3vectors", [("list_vector_buckets", {"vectorBuckets": []}, {"maxResults": 500})]),
        "s3_buckets": ("s3", [("list_buckets", {"Buckets": []}, {"BucketRegion": region, "MaxBuckets": 1000})]),
        "ac_runtimes": ("bedrock-agentcore-control", [("list_agent_runtimes", {"agentRuntimes": []}, {"maxResults": 100})]),
        "ac_gateways": ("bedrock-agentcore-control", [("list_gateways", {"items": []}, {"maxResults": 100})]),
        "ac_memories": ("bedrock-agentcore-control", [("list_memories", {"memories": []}, {"maxResults": 100})]),
        "ecr": ("ecr", [("describe_repositories", {"repositories": []}, {"maxResults": 100})]),
        "log_groups": ("logs", log_group_steps(prefix_forms)),
    })
    return plan


class StubbedAccount:
    """A client factory whose clients answer from a plan, in order, via botocore's Stubber."""

    def __init__(self, plan: dict[str, tuple[str, list[tuple[str, Any, Any]]]], skip_checks: tuple[str, ...] = ()):
        self.clients: dict[str, Any] = {}
        self.stubbers: dict[str, Stubber] = {}
        self.requested: list[tuple[str, str]] = []
        self.overrides: dict[str, Any] = {}
        for check_id, (service, steps) in plan.items():
            if check_id in skip_checks:
                continue
            stubber = self._stubber(service)
            for method, payload, expected in steps:
                if isinstance(payload, Err):
                    stubber.add_client_error(
                        method,
                        service_error_code=payload.code,
                        service_message=payload.message,
                        http_status_code=payload.status,
                        expected_params=expected,
                    )
                else:
                    stubber.add_response(method, payload, expected)
        for stubber in self.stubbers.values():
            stubber.activate()

    def _stubber(self, service: str) -> Stubber:
        if service not in self.clients:
            self.clients[service] = real_client(service)
            self.stubbers[service] = Stubber(self.clients[service])
        return self.stubbers[service]

    def __call__(self, service: str, region: str) -> Any:
        self.requested.append((service, region))
        if service in self.overrides:
            override = self.overrides[service]
            if isinstance(override, BaseException):
                raise override
            return override
        if service not in self.clients:
            self._stubber(service).activate()
        return self.clients[service]

    def assert_all_calls_made(self) -> None:
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


class RaisingClient:
    """Wraps a real client; one method raises the given exception instead of calling out."""

    def __init__(self, real: Any, method: str, exc: BaseException):
        self._real, self._method, self._exc = real, method, exc
        self.meta = real.meta

    def __getattr__(self, name: str) -> Any:
        if name == self._method:
            def raiser(**kwargs: Any) -> Any:
                raise self._exc
            return raiser
        return getattr(self._real, name)


class OlderBoto3Client:
    """Wraps a real client but pretends the service model lacks some operations."""

    def __init__(self, real: Any, missing: set[str]):
        self._real = real
        model = real.meta.service_model
        self.meta = SimpleNamespace(
            service_model=SimpleNamespace(
                service_name=model.service_name,
                operation_names=[o for o in model.operation_names if o not in missing],
                operation_model=model.operation_model,
            ),
            method_to_api_mapping=real.meta.method_to_api_mapping,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class MixedFactory:
    """Plain fakes for everything, except the services given here, which answer from a real stubbed client."""

    def __init__(self, fake: Any, clients: dict[str, Any]):
        self.fake, self.clients = fake, clients
        self.requested: list[tuple[str, str]] = []

    def __call__(self, service: str, region: str) -> Any:
        self.requested.append((service, region))
        return self.clients[service] if service in self.clients else self.fake(service, region)


def forbidden_factory(service: str, region: str) -> Any:
    raise AssertionError(f"a client for {service} was requested, but this path must make no AWS call")


# ---------------------------------------------------------------------------
# Plain fakes (no Stubber), so that responses AWS's model would never allow
# (a missing list key, an empty structure) can still be fed to the audit.
# The idea is the round 1 reviewer's harness; the code is this folder's own.
# ---------------------------------------------------------------------------
import copy

TEST_ACCOUNT = "111122223333"  # the AWS documentation placeholder account id

EMPTY_RESPONSES: dict[tuple[str, str], dict[str, Any]] = {
    ("sts", "get_caller_identity"): {"Account": TEST_ACCOUNT, "UserId": "AIDAEXAMPLE", "Arn": f"arn:aws:iam::{TEST_ACCOUNT}:user/example"},
    ("sagemaker", "list_endpoints"): {"Endpoints": []},
    ("sagemaker", "list_endpoint_configs"): {"EndpointConfigs": []},
    ("sagemaker", "list_models"): {"Models": []},
    ("sagemaker", "list_inference_components"): {"InferenceComponents": []},
    ("sagemaker", "list_training_jobs"): {"TrainingJobSummaries": []},
    ("sagemaker", "list_notebook_instances"): {"NotebookInstances": []},
    ("sagemaker", "list_apps"): {"Apps": []},
    ("sagemaker", "list_spaces"): {"Spaces": []},
    ("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": []},
    ("bedrock-agent", "get_knowledge_base"): {"knowledgeBase": {"knowledgeBaseId": "KB1", "knowledgeBaseConfiguration": {"type": "MANAGED"}}},
    ("bedrock-agent", "list_data_sources"): {"dataSourceSummaries": []},
    ("bedrock", "list_guardrails"): {"guardrails": []},
    ("bedrock", "list_provisioned_model_throughputs"): {"provisionedModelSummaries": []},
    ("bedrock", "list_custom_models"): {"modelSummaries": []},
    ("bedrock", "list_imported_models"): {"modelSummaries": []},
    ("bedrock", "list_custom_model_deployments"): {"modelDeploymentSummaries": []},
    ("opensearchserverless", "list_collections"): {"collectionSummaries": []},
    ("opensearchserverless", "batch_get_collection"): {"collectionDetails": []},
    ("opensearchserverless", "list_collection_groups"): {"collectionGroupSummaries": []},
    ("s3vectors", "list_vector_buckets"): {"vectorBuckets": []},
    ("s3vectors", "list_indexes"): {"indexes": []},
    ("s3", "list_buckets"): {"Buckets": []},
    ("s3", "get_bucket_tagging"): {"TagSet": []},
    ("s3", "list_object_versions"): {},
    ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": []},
    ("bedrock-agentcore-control", "get_agent_runtime"): {
        "agentRuntimeId": "rt-1", "agentRuntimeName": "rt", "status": "READY",
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 900, "maxLifetime": 28800},
        "agentRuntimeArtifact": {"codeConfiguration": {"runtime": "PYTHON_3_13"}},
    },
    ("bedrock-agentcore-control", "list_gateways"): {"items": []},
    ("bedrock-agentcore-control", "list_memories"): {"memories": []},
    ("ecr", "describe_repositories"): {"repositories": []},
    ("logs", "describe_log_groups"): {"logGroups": []},
}


# Calls the audit makes that can never decide the verdict by themselves: the budget row is
# informational, and account.ListRegions is made only with --all-regions. They are kept out of
# EMPTY_RESPONSES so that the "every call, every failure" tests of round 1 keep their meaning.
INFO_RESPONSES: dict[tuple[str, str], dict[str, Any]] = {
    ("budgets", "describe_budgets"): {"Budgets": []},
    ("budgets", "list_tags_for_resource"): {"ResourceTags": []},
    ("account", "list_regions"): {"Regions": [{"RegionName": "us-east-1", "RegionOptStatus": "ENABLED_BY_DEFAULT"}]},
}


def failure_kinds() -> dict[str, Any]:
    """Eleven ways one call can go wrong: label -> a function that makes the handler."""
    import botocore.exceptions as bex

    return {
        "access-denied": lambda: client_error("AccessDeniedException", "not authorized"),
        "throttled": lambda: client_error("ThrottlingException", "Rate exceeded"),
        "no-endpoint": lambda: bex.EndpointConnectionError(endpoint_url="https://service.invalid"),
        "timeout": lambda: bex.ConnectTimeoutError(endpoint_url="https://service.invalid"),
        "no-credentials": lambda: bex.NoCredentialsError(),
        "runtime-error": lambda: RuntimeError("boom"),
        "key-error": lambda: KeyError("k"),
        "empty-exception": lambda: Exception(),
        "returns-none": lambda: (lambda **kw: None),
        "returns-list": lambda: (lambda **kw: []),
        "returns-text": lambda: (lambda **kw: "oops"),
    }


def client_error(code: str, message: str = "stubbed", operation: str = "Op", status: int = 400):
    import botocore.exceptions as bex

    return bex.ClientError({"Error": {"Code": code, "Message": message}, "ResponseMetadata": {"HTTPStatusCode": status}}, operation)


class _FakeClient:
    def __init__(self, service: str, region: str, account: "FakeAccount"):
        self._service, self._region, self._account = service, region, account
        self.meta = real_client(service).meta  # the real service model, so _call()'s checks still apply

    def __getattr__(self, name: str) -> Any:
        key = (self._service, name)
        if key not in EMPTY_RESPONSES and key not in INFO_RESPONSES:
            raise AttributeError(name)

        def method(**kwargs: Any) -> Any:
            self._account.calls.append((self._service, name, self._region, kwargs))
            handler = self._account.handlers.get((self._service, name, self._region), self._account.handlers.get(key))
            if handler is None:
                return copy.deepcopy(EMPTY_RESPONSES[key] if key in EMPTY_RESPONSES else INFO_RESPONSES[key])
            if callable(handler):
                handler = handler(**kwargs)
            if isinstance(handler, BaseException):
                raise handler
            return copy.deepcopy(handler)

        return method


class FakeAccount:
    """Client factory answering from `handlers`: {(service, method[, region]): response | exception | callable}."""

    def __init__(self, handlers: dict | None = None):
        self.handlers = dict(handlers or {})
        self.calls: list[tuple[str, str, str, dict]] = []

    def __call__(self, service: str, region: str) -> Any:
        return _FakeClient(service, region, self)

    def regions_called(self, service: str | None = None) -> set[str]:
        return {region for svc, _method, region, _kw in self.calls if service in (None, svc)}

    def called(self, service: str, method: str) -> list[dict]:
        return [kw for svc, name, _region, kw in self.calls if (svc, name) == (service, method)]


def log_groups_like_aws(names: list[str]):
    """DescribeLogGroups as documented: the pattern is a case-sensitive substring, the prefix a prefix."""

    def handler(**kwargs: Any) -> dict[str, Any]:
        if "logGroupNamePattern" in kwargs:
            hits = [n for n in names if kwargs["logGroupNamePattern"] in n]
        elif "logGroupNamePrefix" in kwargs:
            hits = [n for n in names if n.startswith(kwargs["logGroupNamePrefix"])]
        else:
            hits = list(names)
        return {"logGroups": [{"logGroupName": n, "creationTime": 1790000000000} for n in hits]}

    return handler
