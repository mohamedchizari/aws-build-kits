#!/usr/bin/env python3
"""whats_running.py: a READ-ONLY audit of what could still be billing.

It lists the resources from the three kits' service families that can bill
while idle or that a teardown commonly misses. It never creates, changes or
deletes anything: every call goes through _call(), which refuses any
operation that is not in the READ_OPERATIONS table below. It never deletes,
renames or rewrites a kit's files either.

Where it looks. By default it works out what to audit from the kit folders
beside this one: every Region and every name prefix found in
../kit_*/config.env, in the defaults of ../kit_*/config.example.env and in
every file in a kit folder whose name starts with .state.json (the state
file, a half-written .state.json.tmp, a .state.json.damaged-* file that an
earlier kit C set aside, a copy made by hand), plus AWS_REGION and KIT_PREFIX
from the environment and the kits' built-in defaults (us-east-1, kitdemo).
--region and --prefix ADD to that. --all-regions adds every Region that AWS
reports as enabled for the account (one extra call, account:ListRegions).
Only --only replaces it.

What it cannot know. A kit folder with no state file tells the audit nothing
about where that kit was last deployed. The RESULT line then says so in
plain words, names the kit, and offers --all-regions. A state file that is
unreadable or damaged is read as far as a pattern search allows, makes the
result NOT CLEAN, and is named in the RESULT line.

The RESULT line names every Region and prefix audited and the account (last
four digits only, from sts:GetCallerIdentity). With --only or
--ignore-storage-only it starts with LIMITED CHECK and the limit in capitals.

Exit codes
    0   every check ran in every audited Region, nothing was skipped, the
        account could be named, no kit state file was unreadable, damaged or
        named another account, the Regions could be listed if --all-regions
        asked for them, nothing that bills while idle was found, and (with
        --after-teardown KIT) no row of that kit is marked FOUND
    2   NOT CLEAN: something bills while idle, OR a check could not be
        completed, OR a check was skipped with --skip, OR the scope of the
        audit is in doubt, OR --after-teardown KIT found something of that
        kit, whatever it costs while idle (a check that did not run is never
        reported as clean)
    3   --dry-run: the calls were printed and nothing was checked. A dry run
        of the audit never exits 0, so it cannot be taken for a clean result
        (the three kits' 99_verify_clean.py scripts do the same)
    64  the command line was wrong
    1   the script itself crashed (a bug; treat as "not clean")

The budget that budget_alarm.py creates is listed under INFORMATIONAL. It is
free and is not a leftover, so that row never changes the result or the exit
code, whether the budget exists, is missing, or could not be read.

NOT RUN: this file was written without an AWS account. No call in it has
been made against AWS. The request and response shapes were checked against
the service models shipped in boto3 1.43.108 and exercised offline with
botocore's Stubber and with plain fakes (see tests/).

All doc and pricing pages named in comments were read on 2026-10-07.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

try:  # boto3 is imported lazily enough that --help and --dry-run work without it
    import boto3
    import botocore
    import botocore.exceptions as bex
    from botocore.config import Config
except ImportError:  # pragma: no cover - exercised only on a machine without boto3
    boto3 = None
    botocore = None
    bex = None
    Config = None

DOCS_READ = "2026-10-07"
DEFAULT_REGION = "us-east-1"
DEFAULT_PREFIX = "kitdemo"
PROJECT_TAG_KEY = "project"
PROJECT_TAG_VALUE = "aws-kits"

# The folder that holds common/ and the kit_* folders. Tests point this elsewhere.
KITS_DIR = Path(__file__).resolve().parent.parent

# budget_alarm.py, in this folder, records the budget it created here. The audit reads the name
# from it for the informational budget row. Tests point this elsewhere.
BUDGET_STATE_FILE = Path(__file__).resolve().with_name(".state.json")
BUDGET_CREATED_BY_TAG = ("created-by", "aws-kits-budget-alarm")  # the tag budget_alarm.py sets
MAX_BUDGET_TAG_LOOKUPS = 20  # the budget row is information only; it does not read tags without end

STATE_FILE_NAME = ".state.json"  # every kit keeps its record under this name, in its own folder

EXIT_CLEAN = 0
EXIT_NOT_CLEAN = 2
EXIT_DRY_RUN = 3  # nothing was checked, so this must not look like a pass
EXIT_USAGE = 64

BILLS_YES = "yes"
BILLS_STORAGE = "storage only"
BILLS_NO = "no"
BILLS_UNKNOWN = "unknown"

STATUS_OK = "ok"
STATUS_COULD_NOT_CHECK = "could not check"
STATUS_SKIPPED = "skipped"

# Why a result is not clean. These strings are also the JSON "verdict_reasons".
REASON_BILLS = "bills while idle"
REASON_STORAGE = "storage only"
REASON_COULD_NOT_CHECK = "could not check"
REASON_SCOPE = "scope problem"
REASON_SKIPPED = "skipped"
REASON_NOTHING_RAN = "no check completed"
REASON_KIT_FOUND = "kit leftover found"  # --after-teardown KIT: a row of that kit is FOUND, whatever it costs

VERDICT_CLEAN = "clean"
VERDICT_NOT_CLEAN = "not clean"
VERDICT_COULD_NOT_CHECK = "could not check"
VERDICT_SKIPPED = "skipped"

MAX_PAGES = 500
MAX_LOCAL_FILE_BYTES = 5_000_000  # a kit's config or state file is a few kilobytes

# ---------------------------------------------------------------------------
# Sources for every "bills while idle" statement. Read on DOCS_READ.
# The quoted words are what the page said that day. Re-read before relying
# on them: pricing pages change.
# ---------------------------------------------------------------------------
SRC_SM_PRICING = "https://aws.amazon.com/sagemaker/ai/pricing/"
SRC_SM_DELETE = "https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-delete-resources.html"
SRC_SM_ZERO = "https://docs.aws.amazon.com/sagemaker/latest/dg/endpoint-auto-scaling-zero-instances.html"
SRC_SM_WARM_POOLS = "https://docs.aws.amazon.com/sagemaker/latest/dg/train-warm-pools.html"
SRC_BR_PRICING = "https://aws.amazon.com/bedrock/pricing/"
SRC_KB_DELETE = "https://docs.aws.amazon.com/bedrock/latest/userguide/kb-delete.html"
SRC_AOSS_PRICING = "https://aws.amazon.com/opensearch-service/pricing/"
SRC_AOSS_CAPACITY = "https://docs.aws.amazon.com/opensearch-service/latest/developerguide/collection-groups-capacity-limits.html"
SRC_S3_PRICING = "https://aws.amazon.com/s3/pricing/"
SRC_AC_PRICING = "https://aws.amazon.com/bedrock/agentcore/pricing/"
SRC_AC_LIFECYCLE = "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html"
SRC_AC_SESSIONS = "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html"
SRC_ECR_PRICING = "https://aws.amazon.com/ecr/pricing/"
SRC_CW_PRICING = "https://aws.amazon.com/cloudwatch/pricing/"
SRC_BUDGETS_PRICING = "https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/"
SRC_REGIONS_GUIDE = "https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-regions.html"

# From SRC_BUDGETS_PRICING (the same sentence budget_alarm.py prints before it creates the budget):
BUDGET_FREE_QUOTE = "You can monitor and receive notifications on your budgets free of charge."
# From SRC_REGIONS_GUIDE, raw text of the page (curl of its .md form) read on DOCS_READ:
REGION_DISABLED_QUOTE = (
    "Disabling an opt-in Region does not delete the resources in that Region and charges for resources (if any) "
    "in that disabled opt-in Region continue to accrue at the standard rate."
)

# OpenSearch Serverless figures, from SRC_AOSS_PRICING read on DOCS_READ.
# The two sentences are quoted from the page. The hourly rate comes from the
# price data file that page loads for its Region selector (rows "OpenSearch
# Compute Unit (OCU) - Indexing" and "- Search and Query"), as saved on
# DOCS_READ: $0.24 per OCU per hour in US East (N. Virginia), US East (Ohio)
# and US West (Oregon). The other 27 Regions on that file were all higher
# (up to $0.381), so $0.24 is used as a floor anywhere else.
AOSS_MIN_OCU_QUOTE = (
    "You will be billed at least for a minimum of 2 OCUs (1 OCU [0.5 x 2] indexing "
    "includes primary and standby, and 1 OCU [0.5 x 2] search includes one replica "
    "for HA) for the first collection in an account."
)
AOSS_DEVTEST_QUOTE = (
    "This deployment mode further cuts the cost in half, with 0.5 OCU for indexing "
    "and 0.5 OCU for search."
)
AOSS_OCU_HOUR_USD = 0.24  # the floor: lowest rate on the price file read on DOCS_READ
AOSS_OCU_HOUR_USD_BY_REGION = {"us-east-1": 0.24, "us-east-2": 0.24, "us-west-2": 0.24}
AOSS_MIN_OCU_STANDBY = 2.0
AOSS_MIN_OCU_DEVTEST = 1.0

# AgentCore Runtime sentences. Each was copied from the raw text of the page
# (curl, not a page-fetch tool) on DOCS_READ.
# From SRC_AC_PRICING:
AC_SESSION_QUOTE = (
    "With consumption pricing, you only pay for actual resource consumption during your session, which spans "
    "from microVM ready, initialization, active processing, idle periods, until session termination"
)
AC_CODE_STORAGE_QUOTE = (
    "Code storage costs: container deployment requires ECR storage (billed separately); direct code deployment "
    "bills for the size of the code artifacts you deployed at S3 Standard rates."
)
AC_INSTANCES_QUOTE = (
    "Charged per instance-hour from provisioning (boot) until the instance is stopped or terminated, with an "
    "approximately 1-minute minimum."
)
# From SRC_AC_LIFECYCLE:
AC_IDLE_DEFAULT_QUOTE = "Default: 900 seconds (15 minutes)"
AC_MAX_DEFAULT_QUOTE = "Default: 28800 seconds (8 hours)"
AC_LIMITS_QUOTE = (
    "Runtimes that use microVMs accept up to 28800 seconds (8 hours). Runtimes that use a capacity provider "
    "(Instances) accept up to 1209600 seconds (14 days)."
)
# From SRC_AC_SESSIONS:
AC_STOPPED_QUOTE = (
    "This can occur due to inactivity (default 15 minutes), reaching max compute lifetime (default 8 hours), an "
    "explicit stop by invoking the StopRuntimeSession API, or if the compute is deemed unhealthy based on health checks."
)
AC_SESSIONS_CANNOT_BE_LISTED = (
    "OPEN SESSIONS CANNOT BE LISTED. The installed boto3 has no call that lists the sessions of a runtime "
    "(bedrock-agentcore ListSessions belongs to AgentCore Memory and needs a memory id), so this audit cannot "
    "see an open session."
)

# ---------------------------------------------------------------------------
# The only operations this script may call. tests/test_operations.py checks
# every entry against the installed boto3 service model.
# (boto3 client name, API operation name, doc URL read on DOCS_READ)
# ---------------------------------------------------------------------------
READ_OPERATIONS: tuple[tuple[str, str, str], ...] = (
    ("sts", "GetCallerIdentity", "https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html"),
    ("sagemaker", "ListEndpoints", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpoints.html"),
    ("sagemaker", "ListEndpointConfigs", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpointConfigs.html"),
    ("sagemaker", "ListModels", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListModels.html"),
    ("sagemaker", "ListInferenceComponents", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListInferenceComponents.html"),
    ("sagemaker", "ListTrainingJobs", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListTrainingJobs.html"),
    ("sagemaker", "ListNotebookInstances", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListNotebookInstances.html"),
    ("sagemaker", "ListApps", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListApps.html"),
    ("sagemaker", "ListSpaces", "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListSpaces.html"),
    ("bedrock-agent", "ListKnowledgeBases", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_ListKnowledgeBases.html"),
    ("bedrock-agent", "GetKnowledgeBase", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_GetKnowledgeBase.html"),
    ("bedrock-agent", "ListDataSources", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_ListDataSources.html"),
    ("bedrock", "ListGuardrails", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListGuardrails.html"),
    ("bedrock", "ListProvisionedModelThroughputs", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListProvisionedModelThroughputs.html"),
    ("bedrock", "ListCustomModels", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListCustomModels.html"),
    ("bedrock", "ListImportedModels", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListImportedModels.html"),
    ("bedrock", "ListCustomModelDeployments", "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListCustomModelDeployments.html"),
    ("opensearchserverless", "ListCollections", "https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_ListCollections.html"),
    ("opensearchserverless", "BatchGetCollection", "https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_BatchGetCollection.html"),
    ("opensearchserverless", "ListCollectionGroups", "https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_ListCollectionGroups.html"),
    ("s3vectors", "ListVectorBuckets", "https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListVectorBuckets.html"),
    ("s3vectors", "ListIndexes", "https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListIndexes.html"),
    ("s3", "ListBuckets", "https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListBuckets.html"),
    ("s3", "GetBucketTagging", "https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetBucketTagging.html"),
    ("s3", "ListObjectVersions", "https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html"),
    ("bedrock-agentcore-control", "ListAgentRuntimes", "https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html"),
    ("bedrock-agentcore-control", "GetAgentRuntime", "https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetAgentRuntime.html"),
    ("bedrock-agentcore-control", "ListGateways", "https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGateways.html"),
    ("bedrock-agentcore-control", "ListMemories", "https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListMemories.html"),
    ("ecr", "DescribeRepositories", "https://docs.aws.amazon.com/AmazonECR/latest/APIReference/API_DescribeRepositories.html"),
    ("logs", "DescribeLogGroups", "https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html"),
    # Only with --all-regions: which Regions are enabled for the account.
    ("account", "ListRegions", "https://docs.aws.amazon.com/accounts/latest/APIReference/API_ListRegions.html"),
    # Only for the informational budget row. Neither call can change the verdict or the exit code.
    ("budgets", "DescribeBudgets", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeBudgets.html"),
    ("budgets", "ListTagsForResource", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_ListTagsForResource.html"),
)
_ALLOWED = {(svc, op) for svc, op, _ in READ_OPERATIONS}
_READ_VERBS = ("List", "Describe", "Get", "BatchGet")


# ---------------------------------------------------------------------------
# Account ids never reach the screen in full
# ---------------------------------------------------------------------------
_ACCOUNT_ID_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")


def redact(text: Any) -> str:
    """Replace every 12-digit number (an AWS account id) by its last four digits."""
    return _ACCOUNT_ID_RE.sub(lambda m: f"[account ending {m.group(0)[-4:]}]", str(text))


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Item:
    kind: str
    name: str
    created: str
    state: str
    bills_idle: str
    why: str
    source: str
    carries_prefix: bool = False

    def __post_init__(self) -> None:
        # Kit bucket names carry the account id. Show the last four digits only.
        self.name = redact(self.name)

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class CheckResult:
    check_id: str
    family: str
    title: str
    region: str
    status: str
    reason: str = ""
    items: list[Item] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["items"] = [i.as_dict() for i in self.items]
        return d


class CouldNotCheck(Exception):
    """A check could not be completed. The message is shown to the owner."""

    def __init__(self, message: str = ""):
        super().__init__(redact(message))


class CallFailed(CouldNotCheck):
    def __init__(self, service: str, operation: str, cause: BaseException):
        self.service = service
        self.operation = operation
        self.cause = cause
        self.code = error_code(cause)
        super().__init__(f"{service}.{operation}: {describe_error(cause)}")


class UsageError(Exception):
    pass


def error_code(exc: BaseException) -> str:
    """The AWS error code of a ClientError, or ''."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str((response.get("Error") or {}).get("Code", ""))
    return ""


def describe_error(exc: BaseException) -> str:
    """Turn any failure into a short, honest reason. Never returns ''. Account ids are cut to four digits."""
    return redact(_describe_error(exc))


def _describe_error(exc: BaseException) -> str:
    if isinstance(exc, CouldNotCheck):
        return str(exc)
    if bex is not None:
        if isinstance(exc, bex.ClientError):
            err = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            code = err.get("Code", "ClientError")
            msg = " ".join(str(err.get("Message", "")).split())[:240]
            return f"{code}: {msg}" if msg else str(code)
        if isinstance(exc, bex.UnknownServiceError):
            return f"service is not in the installed boto3 ({_boto3_version()})"
        if isinstance(exc, (bex.NoCredentialsError, bex.PartialCredentialsError)):
            return "no usable AWS credentials were found"
        if isinstance(exc, bex.NoRegionError):
            return "no AWS Region was given"
        if isinstance(exc, bex.EndpointConnectionError):
            return "no endpoint could be reached (the service may not exist in this Region, or there is no network)"
        if isinstance(exc, bex.BotoCoreError):
            return f"{type(exc).__name__}: {' '.join(str(exc).split())[:240]}"
    text = " ".join(str(exc).split())[:240]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _boto3_version() -> str:
    return getattr(boto3, "__version__", "not installed")


def fmt_time(value: Any, *, epoch_ms: bool = False) -> str:
    """ISO 8601 UTC, or a plain statement that the API did not return it."""
    if value is None:
        return "not returned by this API"
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000.0 if epoch_ms else float(value)
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def src(url: str) -> str:
    return f"{url} (read {DOCS_READ})"


# ---------------------------------------------------------------------------
# The single choke point for AWS calls
# ---------------------------------------------------------------------------
def _call(client: Any, operation: str, **params: Any) -> dict[str, Any]:
    """Make one read-only call, or raise CouldNotCheck. Nothing else calls AWS."""
    try:
        model = client.meta.service_model
        service = model.service_name
        known_ops = set(model.operation_names)
        mapping = client.meta.method_to_api_mapping
    except AttributeError as exc:
        raise CouldNotCheck(f"client has no service model ({exc})") from exc
    if (service, operation) not in _ALLOWED or not operation.startswith(_READ_VERBS):
        raise CouldNotCheck(f"refused: {service}.{operation} is not in this script's read-only list")
    if operation not in known_ops:
        raise CouldNotCheck(
            f"operation {operation} is not in the installed boto3 ({_boto3_version()}) model for {service}"
        )
    method_name = next((py for py, api in mapping.items() if api == operation), None)
    if method_name is None or not hasattr(client, method_name):
        raise CouldNotCheck(f"installed boto3 has no client method for {service}.{operation}")
    try:
        response = getattr(client, method_name)(**params)
    except Exception as exc:  # noqa: BLE001 - every failure must become "could not check"
        raise CallFailed(service, operation, exc) from exc
    if not isinstance(response, dict):
        raise CouldNotCheck(f"{service}.{operation}: unexpected response type {type(response).__name__}")
    return response


def _paginate(
    client: Any,
    operation: str,
    result_key: str,
    token_param: str = "nextToken",
    token_key: str = "nextToken",
    **params: Any,
) -> Iterator[dict[str, Any]]:
    """Follow the pagination token until it runs out. Yields one record at a time.

    A response that does not carry its list at all is "could not check", never
    "none found", whether or not the service model marks the key as required.
    """
    seen: set[str] = set()
    token: str | None = None
    for _ in range(MAX_PAGES):
        kwargs = dict(params)
        if token:
            kwargs[token_param] = token
        response = _call(client, operation, **kwargs)
        records = response.get(result_key)
        if records is None:
            raise CouldNotCheck(f"{operation}: response had no '{result_key}' list, so nothing can be said about it")
        if not isinstance(records, list):
            raise CouldNotCheck(f"{operation}: '{result_key}' was not a list")
        yield from records
        token = response.get(token_key)
        if not token:
            return
        if token in seen:
            raise CouldNotCheck(f"{operation}: pagination token repeated; listing is incomplete")
        seen.add(token)
    raise CouldNotCheck(f"{operation}: more than {MAX_PAGES} pages; listing is incomplete")


# ---------------------------------------------------------------------------
# Scope: which Regions, prefixes and account the audit covers, and why
# ---------------------------------------------------------------------------
_REGION_PATTERN = r"[a-z]{2}(?:-[a-z]+)+-\d{1,2}"
_REGION_RE = re.compile(rf"^{_REGION_PATTERN}$")
_KIT_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{0,19}$")
# An ARN is arn:partition:service:region:account:resource. Two patterns, so that an ARN cut off after
# its Region still gives the Region, and an ARN with no Region (IAM) still gives the account.
_ARN_REGION_RE = re.compile(rf"arn:aws[a-z-]*:[a-z0-9-]+:({_REGION_PATTERN}):")
_ARN_ACCOUNT_RE = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:(\d{12}):")
# Kit B and kit C put the account id and the Region into their bucket names.
_ACCOUNT_REGION_IN_NAME_RE = re.compile(rf"-(\d{{12}})-({_REGION_PATTERN})(?![a-z0-9])")
# Every kit name is <prefix>-kita-..., <prefix>-fedrag-... or <prefix>-kitc-...
_PREFIX_IN_NAME_RE = re.compile(r"(?<![a-z0-9-])([a-z][a-z0-9-]{0,19}?)-(?:kita|fedrag|kitc)-")
# An AWS host name carries its Region: kit A records the container image address
# <registry account>.dkr.ecr.<region>.amazonaws.com/... The registry account in front of it is AWS's,
# not the owner's, so only the Region is taken.
_HOST_REGION_RE = re.compile(rf"\.({_REGION_PATTERN})\.(?:amazonaws\.com|api\.aws|on\.aws)")
# For a file that does not parse: "key": "value" pairs in either quote style, and bare quoted values.
_JSON_PAIR_RE = re.compile(r"""["']([A-Za-z0-9_.-]{1,40})["']\s*[:=]\s*(?:["']([^"'\\]{0,200})["']|(\d{4,12})\b)""")
_QUOTED_REGION_RE = re.compile(rf"""["']({_REGION_PATTERN})["']""")
# For a config.env line that the plain KEY=VALUE reading skips (commented out, a colon, spaces, "set").
_CONFIG_REGION_RE = re.compile(rf"\b(?:AWS_REGION|AWS_DEFAULT_REGION)\b[^A-Za-z0-9\n]{{1,6}}({_REGION_PATTERN})(?![a-z0-9-])")
# The prefix must be ASSIGNED on that line: KIT_PREFIX, then = or :, then the value, then the end of the line or
# a comment. A sentence that only mentions the name ("an AWS_REGION or KIT_PREFIX exported in your shell", which
# every kit A config.env carries, copied from config.example.env) names no prefix.
_CONFIG_PREFIX_RE = re.compile(
    r"""\bKIT_PREFIX\b[ \t]{0,3}[=:][ \t]{0,3}["']?([a-z][a-z0-9-]{0,19})["']?[ \t]*(?=$|[#;])""", re.MULTILINE)

_REGION_KEYS = {"region", "aws_region", "awsregion", "region_name", "regionname", "aws_default_region"}
_PREFIX_KEYS = {"prefix", "kit_prefix", "kitprefix", "name_prefix", "resource_prefix"}
_ACCOUNT_KEYS = {
    "account", "account_id", "accountid", "aws_account", "aws_account_id", "awsaccountid", "caller_account",
    "caller_account_id", "owner_account", "owner_account_id",
    "account_last4", "account_last_4", "account_last_four", "account_id_last4", "account_id_last_4",
    "account_id_last_four", "account_suffix", "account_tail",
}
_PLACEHOLDER_ACCOUNTS = {"0" * 12}  # twelve zeros: kit C prints this in --dry-run; it is not an account


def _norm_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


_KNOWN_REGIONS: set[str] | None = None


def known_regions() -> set[str]:
    """Region names in the endpoint data of the installed botocore (a local file; no call). Empty without boto3."""
    global _KNOWN_REGIONS
    if _KNOWN_REGIONS is None:
        names: set[str] = set()
        try:
            import botocore.session

            session = botocore.session.get_session()
            for partition in session.get_available_partitions():
                names.update(session.get_available_regions("sts", partition_name=partition))
        except Exception:  # noqa: BLE001 - no boto3, or endpoint data in a shape this does not know
            names = set()
        _KNOWN_REGIONS = names
    return _KNOWN_REGIONS


@dataclasses.dataclass
class Scope:
    """What is audited and where each value came from."""

    regions: dict[str, list[str]] = dataclasses.field(default_factory=dict)   # Region -> sources
    prefixes: dict[str, list[str]] = dataclasses.field(default_factory=dict)  # prefix -> sources
    state_accounts: list[tuple[str, str]] = dataclasses.field(default_factory=list)  # (source, 12 or 4 digits)
    problems: list[str] = dataclasses.field(default_factory=list)  # each one makes the verdict not clean
    notes: list[str] = dataclasses.field(default_factory=list)
    kits_read: list[str] = dataclasses.field(default_factory=list)
    only: bool = False
    # Round 2: what the RESULT line has to say about the kits' state files.
    state_files_read: list[str] = dataclasses.field(default_factory=list)       # every state file found, by kit/name
    damaged_state: list[str] = dataclasses.field(default_factory=list)          # unreadable or damaged ones; one problem each
    kits_without_state: list[str] = dataclasses.field(default_factory=list)     # kit folders with no state file at all
    kits_state_without_region: list[str] = dataclasses.field(default_factory=list)  # a state file, but no Region in it
    no_kit_folders: bool = False
    # --all-regions
    all_regions_requested: bool = False
    all_regions_listed: bool = False
    all_regions_failure: str = ""
    enabled_regions: list[str] = dataclasses.field(default_factory=list)
    not_enabled_regions: list[str] = dataclasses.field(default_factory=list)

    def add_region(self, value: Any, source: str) -> bool:
        text = str(value).strip()
        if not _REGION_RE.match(text):
            return False
        _add(self.regions, text, source)
        return True

    def add_prefix(self, value: Any, source: str, strict: bool = True) -> bool:
        text = str(value).strip()
        if strict and (not _KIT_PREFIX_RE.match(text) or text.endswith("-")):
            return False
        if not text or any(ch.isspace() for ch in text):
            return False
        _add(self.prefixes, text, source)
        return True

    def add_account(self, value: Any, source: str) -> bool:
        text = str(value).strip()
        if text in _PLACEHOLDER_ACCOUNTS or not re.fullmatch(r"\d{12}|\d{4}", text):
            return False
        if (source, text) not in self.state_accounts:
            self.state_accounts.append((source, text))
        return True

    def add_damaged(self, source: str, problem: str) -> None:
        """A state file that is unreadable or damaged: one scope problem, and named in the RESULT line."""
        if source not in self.damaged_state:
            self.damaged_state.append(source)
            self.problems.append(problem)

    @property
    def region_list(self) -> list[str]:
        return list(self.regions)

    @property
    def prefix_list(self) -> list[str]:
        return list(self.prefixes)


def _add(table: dict[str, list[str]], value: str, source: str) -> None:
    sources = table.setdefault(value, [])
    if source not in sources:
        sources.append(source)


def _read_local_file(path: Path) -> str | None:
    """Text of a small local file, or None when it does not exist. Raises OSError when it cannot be read."""
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        data = handle.read(MAX_LOCAL_FILE_BYTES + 1)
    if len(data) > MAX_LOCAL_FILE_BYTES:
        raise OSError(f"larger than {MAX_LOCAL_FILE_BYTES} bytes")
    return data.decode("utf-8", errors="replace").lstrip("\ufeff")


def _os_error_text(exc: OSError) -> str:
    """Why a local file could not be read, without the path (a path can carry a user name)."""
    return f"{type(exc).__name__}: {exc.strerror}" if exc.strerror else f"{type(exc).__name__}: {exc}"


def parse_env_text(text: str) -> dict[str, str]:
    """KEY=VALUE lines the way the kits read them, a little more forgiving."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if " #" in value:  # a trailing comment
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value.strip('"').strip("'").strip()
    return values


def _scan_text(text: str, scope: Scope, source: str) -> None:
    """Regions, accounts and prefixes that sit inside a string: ARNs, bucket names, resource names, host names."""
    for match in _ARN_REGION_RE.finditer(text):
        scope.add_region(match.group(1), source)
    for match in _ARN_ACCOUNT_RE.finditer(text):
        scope.add_account(match.group(1), source)
    for match in _ACCOUNT_REGION_IN_NAME_RE.finditer(text):
        scope.add_account(match.group(1), source)
        scope.add_region(match.group(2), source)
    for match in _HOST_REGION_RE.finditer(text):
        scope.add_region(match.group(1), source)
    for match in _PREFIX_IN_NAME_RE.finditer(text):
        scope.add_prefix(match.group(1), source)


def _scan_pair(key: Any, value: Any, scope: Scope, source: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return
    name = _norm_key(key)
    if name in _REGION_KEYS:
        scope.add_region(value, source)
    elif name in _PREFIX_KEYS:
        scope.add_prefix(value, source)
    elif name in _ACCOUNT_KEYS:
        scope.add_account(value, source)


def _scan_json(node: Any, scope: Scope, source: str, depth: int = 0) -> None:
    """Walk any JSON value. Unknown keys and odd types are skipped, never an error."""
    if depth > 40:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            _scan_pair(key, value, scope, source)
            _scan_json(value, scope, source, depth + 1)
    elif isinstance(node, list):
        for value in node:
            _scan_json(value, scope, source, depth + 1)
    elif isinstance(node, str):
        _scan_text(node, scope, source)


def _salvage_text(text: str, scope: Scope, source: str) -> bool:
    """Take what a pattern search can still find in a file that does not parse. True when anything was found."""
    before = (len(scope.regions), len(scope.prefixes), len(scope.state_accounts), sum(len(v) for v in scope.regions.values()))
    for match in _JSON_PAIR_RE.finditer(text):
        _scan_pair(match.group(1), match.group(2) if match.group(2) is not None else match.group(3), scope, source)
    _scan_text(text, scope, source)
    # A Region written as a value under a key this audit does not know. Only names the installed botocore
    # knows are taken here, so that a prefix such as "my-kit-1" is not audited as if it were a Region.
    known = known_regions()
    for match in _QUOTED_REGION_RE.finditer(text):
        if match.group(1) in known:
            scope.add_region(match.group(1), source)
    return (len(scope.regions), len(scope.prefixes), len(scope.state_accounts), sum(len(v) for v in scope.regions.values())) != before


def is_set_aside_name(name: str) -> bool:
    """A state file that an earlier version of kit C renamed to .state.json.damaged-<time>-<pid>."""
    return "damaged" in name[len(STATE_FILE_NAME):].lower()


def read_kit_state(path: Path, scope: Scope, source: str) -> bool:
    """Add what one state file says about Region, prefix and account. Never raises.

    Returns True when a file (or anything else) exists at that path. A file that cannot be read,
    is empty, does not parse, or carries "damaged" in its name is recorded with scope.add_damaged():
    it makes the verdict not clean and the RESULT line names it.
    """
    try:
        if not path.exists() and not path.is_symlink():
            return False  # no such file
        if not path.is_file():
            scope.add_damaged(source, f"{source} is not a regular file, so the Region, prefix and account that kit used are not known")
            return True
        text = _read_local_file(path)
    except OSError as exc:
        scope.add_damaged(source, f"{source} could not be read ({_os_error_text(exc)}), so the Region, prefix and account that kit used are not known")
        return True
    if text is None:
        return False
    if source not in scope.state_files_read:
        scope.state_files_read.append(source)
    if not text.strip():
        scope.add_damaged(
            source,
            f"{source} could not be read: it is empty (a write that was cut short?), so the Region, prefix and "
            "account that kit used are not known",
        )
        return True
    try:
        data = json.loads(text)
    except ValueError as exc:
        # Cut short or damaged. Take what a pattern search can still find, and say the rest is unknown.
        salvaged = _salvage_text(text, scope, source)
        scope.add_damaged(
            source,
            f"{source} could not be read as JSON ({type(exc).__name__}; cut short or damaged). "
            + ("Values found in it by pattern search were added, but " if salvaged else "Nothing could be taken from it, so ")
            + "what that kit created, and where, is not fully known",
        )
        return True
    if isinstance(data, (dict, list)):
        _scan_json(data, scope, source)
    else:
        scope.notes.append(f"{source} holds no object (it is {type(data).__name__}); nothing was taken from it")
    if path.name != STATE_FILE_NAME and not is_set_aside_name(path.name):
        scope.notes.append(f"{source} is not the kit's own state file (a write that did not finish, or a copy); it reads as JSON and was read as well")
    if is_set_aside_name(path.name):
        scope.add_damaged(
            source,
            f"{source} is a state file that a kit script set aside as damaged. What could be read from it was added, "
            "but what that kit created, and where, is not fully known",
        )
    return True


def kit_state_files(kit: Path) -> list[Path]:
    """.state.json first, then every other entry whose name starts with .state.json, in name order.

    That covers what the kits write today (.state.json, .state.json.tmp, .state.json.tmp-<pid>), what an
    earlier kit C left behind (.state.json.damaged-<time>-<pid>), and a copy made by hand (.state.json.bak).
    """
    others = sorted(p for p in kit.iterdir() if p.name.startswith(STATE_FILE_NAME) and p.name != STATE_FILE_NAME)
    return [kit / STATE_FILE_NAME] + others


def read_kit_config(path: Path, scope: Scope, source: str, is_example: bool) -> None:
    """Add AWS_REGION and KIT_PREFIX from a kit's config.env or config.example.env. Never raises."""
    try:
        text = _read_local_file(path)
    except OSError as exc:
        message = f"{source} could not be read ({_os_error_text(exc)})"
        if is_example:
            scope.notes.append(message)
        else:
            scope.problems.append(message + ", so the Region and prefix that kit used are not known")
        return
    if text is None:
        return
    values = parse_env_text(text)
    for key, adder in (("AWS_REGION", scope.add_region), ("KIT_PREFIX", scope.add_prefix)):
        value = values.get(key, "")
        if value and not adder(value, source):
            scope.notes.append(f"{source}: {key} has a value that is not usable and was ignored")
    if not is_example:
        # The owner's own file: also take a Region or prefix from a line the plain reading skips, such as
        # one that was commented out after a deploy. The example file is not searched this way, because
        # its comments are documentation, not a record of where anything ran.
        for match in _CONFIG_REGION_RE.finditer(text):
            scope.add_region(match.group(1), source)
        for match in _CONFIG_PREFIX_RE.finditer(text):
            scope.add_prefix(match.group(1), source)


def discover_scope(kits_dir: Path, env: dict[str, str] | None = None) -> Scope:
    """Read the sibling kit folders. Local files only: no AWS call, and nothing is written."""
    env = os.environ if env is None else env
    scope = Scope()
    try:
        kit_dirs = sorted(p for p in Path(kits_dir).iterdir() if p.is_dir() and p.name.startswith("kit_"))
    except OSError as exc:
        kit_dirs = []
        scope.notes.append(f"the folder that should hold the kit_* folders could not be listed ({type(exc).__name__})")
    if not kit_dirs:
        scope.no_kit_folders = True
        scope.notes.append("no kit_* folder was found beside this script, so only the environment, the command line and the built-in defaults were used")
    for kit in kit_dirs:
        scope.kits_read.append(kit.name)
        try:
            read_kit_config(kit / "config.env", scope, f"{kit.name}/config.env", is_example=False)
            read_kit_config(kit / "config.example.env", scope, f"{kit.name}/config.example.env", is_example=True)
            found = [read_kit_state(path, scope, f"{kit.name}/{path.name}") for path in kit_state_files(kit)]
        except Exception as exc:  # noqa: BLE001 - reading a kit folder must never crash the audit
            scope.problems.append(f"{kit.name} could not be read ({type(exc).__name__}), so what that kit used is not known")
            continue
        state_prefix = f"{kit.name}/{STATE_FILE_NAME}"
        if not any(found):
            scope.kits_without_state.append(kit.name)
        elif not any(source.startswith(state_prefix) for sources in scope.regions.values() for source in sources):
            if not any(source.startswith(state_prefix) for source in scope.damaged_state):
                scope.kits_state_without_region.append(kit.name)  # a damaged file is already said, in stronger words
    if env.get("AWS_REGION") and not scope.add_region(env["AWS_REGION"], "environment AWS_REGION"):
        scope.notes.append("environment AWS_REGION does not look like a Region and was ignored")
    if env.get("KIT_PREFIX") and not scope.add_prefix(env["KIT_PREFIX"], "environment KIT_PREFIX", strict=False):
        scope.notes.append("environment KIT_PREFIX is not usable and was ignored")
    return scope


def _split_values(values: Iterable[str]) -> list[str]:
    return [part.strip() for value in values for part in str(value).split(",") if part.strip()]


def build_scope(
    cli_regions: Iterable[str],
    cli_prefixes: Iterable[str],
    only: bool,
    kits_dir: Path,
    env: dict[str, str] | None = None,
) -> Scope:
    """Discovered values, plus the command line. --only: the command line and nothing else."""
    regions, prefixes = _split_values(cli_regions), _split_values(cli_prefixes)
    for region in regions:
        if not _REGION_RE.match(region):
            raise UsageError(f"--region value {region!r} does not look like an AWS Region name (for example us-east-1)")
    for prefix in prefixes:
        if any(ch.isspace() for ch in prefix):
            raise UsageError("a --prefix value must not contain spaces")
    if only:
        if not regions or not prefixes:
            raise UsageError("--only audits nothing but what you name: give at least one --region and one --prefix with it")
        scope = Scope(only=True)
        scope.notes.append("--only was given: the kit folders were NOT read, so nothing checks that these are the Regions, prefixes and account the kits used")
    else:
        scope = discover_scope(kits_dir, env)
    for region in regions:
        scope.add_region(region, "command line")
    for prefix in prefixes:
        scope.add_prefix(prefix, "command line", strict=False)
    if not only:
        # Every kit falls back to these when its config.env does not say otherwise.
        scope.add_region(DEFAULT_REGION, "built-in default")
        scope.add_prefix(DEFAULT_PREFIX, "built-in default")
    return scope


@dataclasses.dataclass
class Identity:
    account: str | None = None  # kept in memory only; printed as its last four digits
    partition: str = "aws"      # from the caller's ARN; needed to spell a budget's ARN

    @property
    def last4(self) -> str | None:
        return self.account[-4:] if self.account else None

    def label(self) -> str:
        return f"account ending {self.last4}" if self.account else "account unknown"


def check_identity(client_factory: Callable[[str, str], Any], regions: Iterable[str] | str) -> tuple[Identity, CheckResult]:
    """Which account these credentials are for. A failure here is a check that could not run.

    The call is tried in each audited Region in turn until one answers, so that one mistyped
    Region in a config file does not hide the account.
    """
    result = CheckResult("caller_identity", "account", "Caller identity (which account is being audited)", "account", STATUS_OK)
    identity = Identity()
    first_failure = ""
    for region in ([regions] if isinstance(regions, str) else list(regions)):
        try:
            try:
                sts = client_factory("sts", region)
            except Exception as exc:  # noqa: BLE001
                raise CouldNotCheck(f"sts: {describe_error(exc)}") from exc
            # https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
            # "No permissions are required to perform this operation."
            answer = _call(sts, "GetCallerIdentity")
            account = str(answer.get("Account", ""))
            if not re.fullmatch(r"\d{12}", account):
                raise CouldNotCheck("sts.GetCallerIdentity did not return a 12-digit account id")
            identity.account = account
            parts = str(answer.get("Arn", "")).split(":")
            if len(parts) > 1 and parts[0] == "arn" and re.fullmatch(r"aws[a-z-]*", parts[1]):
                identity.partition = parts[1]
            return identity, result
        except Exception as exc:  # noqa: BLE001
            first_failure = first_failure or describe_error(exc)
    result.status = STATUS_COULD_NOT_CHECK
    result.reason = first_failure or "no Region to ask"
    return identity, result


REGION_SOURCE_ALL = "enabled for this account (account:ListRegions, --all-regions)"


def list_account_regions(client_factory: Callable[[str, str], Any], region: str) -> tuple[list[str], list[str], int]:
    """(Regions to audit, Regions that are not enabled, entries that could not be used). Raises CouldNotCheck.

    One call per 50 Regions to the AWS Account Management API, which has a single endpoint whatever
    Region the client is built for. Needs the IAM action account:ListRegions.
    """
    try:
        c = client_factory("account", region)
    except Exception as exc:  # noqa: BLE001
        raise CouldNotCheck(f"account: {describe_error(exc)}") from exc
    audited: list[str] = []
    not_enabled: list[str] = []
    unusable = 0
    # https://docs.aws.amazon.com/accounts/latest/APIReference/API_ListRegions.html (read 2026-10-07)
    # "Lists all the Regions for a given account and their respective opt-in statuses." No status filter is
    # sent, so that the Regions that are NOT enabled come back too and can be named. RegionOptStatus is one of
    # ENABLED | ENABLING | DISABLING | DISABLED | ENABLED_BY_DEFAULT. MaxResults: "Maximum value of 50."
    for entry in _paginate(c, "ListRegions", "Regions", "NextToken", "NextToken", MaxResults=50):
        name = str(entry.get("RegionName", "")).strip() if isinstance(entry, dict) else ""
        if not _REGION_RE.match(name):
            unusable += 1
            continue
        # Only a Region that is plainly DISABLED is left out. One that is being enabled or disabled, or
        # whose status is missing or new to this script, is audited: its checks answer or fail in the open.
        if entry.get("RegionOptStatus") == "DISABLED":
            not_enabled.append(name)
        elif name not in audited:
            audited.append(name)
    return audited, not_enabled, unusable


def apply_all_regions(scope: Scope, client_factory: Callable[[str, str], Any]) -> None:
    """--all-regions: add every Region the account has enabled. A failure is a scope problem, never silence."""
    scope.all_regions_requested = True
    failure = ""
    try:
        audited, not_enabled, unusable = list_account_regions(client_factory, scope.region_list[0])
    except Exception as exc:  # noqa: BLE001 - whatever went wrong, the Regions were not listed
        failure = describe_error(exc)
    else:
        for name in audited:
            scope.add_region(name, REGION_SOURCE_ALL)
        scope.enabled_regions, scope.not_enabled_regions = audited, not_enabled
        if not audited:
            failure = "account.ListRegions returned no Region that is enabled"
        elif unusable:
            failure = f"{unusable} entry(ies) in the account.ListRegions answer could not be read as a Region, so the list is in doubt"
    if failure:
        scope.all_regions_failure = failure
        scope.problems.append(
            f"could not list Regions ({failure}). --all-regions was asked for, but only the Regions listed above were "
            "audited. The call needs the IAM action account:ListRegions (README section 6)"
        )
    else:
        scope.all_regions_listed = True  # the Regions that are not enabled are named by region_note_lines()


def compare_accounts(scope: Scope, identity: Identity) -> None:
    """A kit state file that names another account means the audit looked at the wrong account."""
    if not identity.account:
        return  # the identity check itself already makes the result not clean
    for source, recorded in scope.state_accounts:
        same = recorded == identity.account if len(recorded) == 12 else recorded == identity.last4
        if same:
            _append_once(scope.notes, f"{source} names the account ending {recorded[-4:]}, the same account as these credentials")
        else:
            same_tail = " (a different account that ends in the same four digits)" if recorded[-4:] == identity.last4 else ""
            _append_once(
                scope.problems,
                f"{source} names the account ending {recorded[-4:]}, but these credentials are for the account ending "
                f"{identity.last4}{same_tail}. What that kit created there is in an account this audit did NOT look at; "
                "run the audit again with credentials for that account",
            )


def _append_once(items: list[str], text: str) -> None:
    if text not in items:
        items.append(text)


# ---------------------------------------------------------------------------
# The budget row: information only. It is not a check, it is not in CHECKS,
# and nothing in it can change the verdict or the exit code.
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class BudgetInfo:
    status: str = STATUS_OK   # STATUS_OK, or STATUS_COULD_NOT_CHECK when the budgets could not be read
    reason: str = ""
    budgets: list[dict[str, str]] = dataclasses.field(default_factory=list)
    list_absent: bool = False  # the answer carried no 'Budgets' list at all
    recorded_elsewhere: str = ""  # last four digits, when common/.state.json records a budget for ANOTHER account

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "reason": self.reason, "budgets": list(self.budgets), "affects_exit_code": False,
            "list_absent_from_response": self.list_absent,
            "record_is_for_account_ending": self.recorded_elsewhere,
            "meaning": "information only: a budget with email alerts is free and is not a leftover of any kit",
        }


BUDGET_YES_RECORD = "yes (recorded in common/.state.json)"
BUDGET_YES_TAG = f"yes (it carries the tag {BUDGET_CREATED_BY_TAG[0]}={BUDGET_CREATED_BY_TAG[1]})"
BUDGET_NO = "no"


def recorded_budget(path: Path | None = None) -> tuple[str | None, str | None]:
    """(budget name, last four digits of its account) as budget_alarm.py wrote them into common/.state.json.

    Either is None when it is not there; a record written before round 4 has no account digits. Never raises.
    """
    try:
        data = json.loads((path or BUDGET_STATE_FILE).read_text(encoding="utf-8"))
        record = data.get("budget") if isinstance(data, dict) else None
        if not isinstance(record, dict) or not record.get("name"):
            return None, None
        tail = record.get("account_tail")
        return str(record["name"]), (str(tail) if tail else None)
    except (OSError, ValueError, AttributeError):
        return None, None


def recorded_budget_name(path: Path | None = None) -> str | None:
    """The budget name budget_alarm.py wrote into common/.state.json, or None. Never raises."""
    return recorded_budget(path)[0]


def check_budgets(client_factory: Callable[[str, str], Any], region: str, identity: Identity) -> BudgetInfo:
    """Which AWS Budgets exist, and which one budget_alarm.py created. Never raises."""
    info = BudgetInfo()
    if not identity.account:
        info.status = STATUS_COULD_NOT_CHECK
        info.reason = "the account could not be named (see the caller identity check), and the Budgets API needs the account id"
        return info
    try:
        try:
            c = client_factory("budgets", region)
        except Exception as exc:  # noqa: BLE001
            raise CouldNotCheck(f"budgets: {describe_error(exc)}") from exc
        recorded, recorded_tail = recorded_budget()
        if recorded and recorded_tail and recorded_tail != identity.account[-4:]:
            # The record is for another account. A budget of the same name here is not vouched for by it.
            info.recorded_elsewhere = recorded_tail
            recorded = None
        found: list[dict[str, Any]] = []
        token: str | None = None
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"AccountId": identity.account, "MaxResults": 100}
            if token:
                params["NextToken"] = token
            # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeBudgets.html (read 2026-10-07)
            page = _call(c, "DescribeBudgets", **params)
            records = page.get("Budgets")
            if records is None:
                # UNVERIFIED: whether the live API leaves 'Budgets' out when the account has none. budget_alarm.py
                # --show reads a missing list as "no budgets"; this row does the same and says that it did.
                info.list_absent = True
                records = []
            if not isinstance(records, list):
                raise CouldNotCheck("DescribeBudgets: 'Budgets' was not a list")
            found.extend(b for b in records if isinstance(b, dict))
            token = page.get("NextToken")
            if not token:
                break
            if token in seen:
                raise CouldNotCheck("DescribeBudgets: pagination token repeated; listing is incomplete")
            seen.add(token)
        lookups = 0
        for b in found:
            name = str(b.get("BudgetName", "?"))
            limit = b.get("BudgetLimit") or {}
            if recorded and name == recorded:
                created = BUDGET_YES_RECORD
            elif lookups >= MAX_BUDGET_TAG_LOOKUPS:
                created = f"not looked up (tags are read for the first {MAX_BUDGET_TAG_LOOKUPS} budgets only)"
            else:
                lookups += 1
                try:
                    # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_ListTagsForResource.html (read 2026-10-07)
                    # The ARN form in that page's example: arn:aws:budgets::<account id>:budget/<budget name>.
                    tags = _call(c, "ListTagsForResource", ResourceARN=f"arn:{identity.partition}:budgets::{identity.account}:budget/{name}").get("ResourceTags")
                    mine = isinstance(tags, list) and any(
                        isinstance(t, dict) and (t.get("Key"), t.get("Value")) == BUDGET_CREATED_BY_TAG for t in tags
                    )
                    created = BUDGET_YES_TAG if mine else BUDGET_NO
                except Exception as exc:  # noqa: BLE001 - information only
                    created = f"unknown (tags could not be read: {describe_error(exc)})"
            info.budgets.append({
                "name": redact(name), "type": str(b.get("BudgetType", "?")), "time_unit": str(b.get("TimeUnit", "?")),
                "limit": f"{limit.get('Amount', '?')} {limit.get('Unit', '')}".strip(), "created_by_budget_alarm": created,
            })
    except Exception as exc:  # noqa: BLE001 - information only: whatever happens, the audit goes on
        info.status = STATUS_COULD_NOT_CHECK
        info.reason = describe_error(exc)
        info.budgets = []
    return info


def budget_lines(info: BudgetInfo | None) -> list[str]:
    """The INFORMATIONAL block of the text output."""
    if info is None:
        return []
    lines = ["INFORMATIONAL (free, and not a leftover of any kit; this never changes the RESULT or the exit code)"]
    head = "[budget] AWS Budgets in this account"
    if info.status != STATUS_OK:
        lines.append(f"{head}: COULD NOT READ (information only; the RESULT does not depend on it): {info.reason}")
        return lines
    elsewhere = (f"    NOTE: common/.state.json records a budget that budget_alarm.py created in the account ending "
                 f"{info.recorded_elsewhere}. This audit is signed in to another account, so that budget is not in this list.")
    if not info.budgets:
        absent = " (the answer carried no 'Budgets' list, which is read as none; UNVERIFIED that AWS leaves it out when there is none)" if info.list_absent else ""
        lines.append(f"{head}: none{absent}. Nothing will email you about spend. To set one up: python budget_alarm.py --help")
        if info.recorded_elsewhere:
            lines.append(elsewhere)
        return lines
    lines.append(f"{head}: {len(info.budgets)} found")
    if info.recorded_elsewhere:
        lines.append(elsewhere)
    for b in info.budgets:
        created = b["created_by_budget_alarm"]
        if created.startswith("yes"):
            name_flag = "" if created == BUDGET_YES_RECORD else f"--name {b['name']} "
            tail = f"Created by budget_alarm.py ({created[5:-1]}). Remove it with: python budget_alarm.py --delete {name_flag}--i-understand-this-changes-my-account"
        elif created == BUDGET_NO:
            tail = "Not created by budget_alarm.py as far as this audit can tell (no record in common/.state.json, no created-by tag); this audit did not look at whether it has budget actions."
        elif created.startswith("not looked up"):
            tail = f"Whether budget_alarm.py created it was {created}."
        else:
            tail = f"Its tags could not be read, so this audit cannot say whether budget_alarm.py created it ({created[9:-1]})."
        lines.append(f"    {b['name']}: {b['type']}, {b['time_unit']}, limit {b['limit']}. {tail}")
    lines.append(
        f"    Why this is not a leftover: budget_alarm.py creates one budget with email alerts and no budget actions, and "
        f"'{BUDGET_FREE_QUOTE}' Source: {src(SRC_BUDGETS_PRICING)}. A budget stops nothing; see: python budget_alarm.py --show"
    )
    return lines


# ---------------------------------------------------------------------------
# Context handed to each check
# ---------------------------------------------------------------------------
def prefix_variants(prefixes: Iterable[str]) -> list[str]:
    """Each prefix, and its underscore form: kit C names its runtime <prefix with _>_kitc_fr_agent."""
    out: list[str] = []
    for prefix in prefixes:
        for form in (prefix, prefix.replace("-", "_")):
            if form and form not in out:
                out.append(form)
    return out


class Context:
    def __init__(self, region: str, prefixes: Iterable[str] | str, client_factory: Callable[[str, str], Any]):
        self.region = region
        self.prefixes = tuple(dict.fromkeys([prefixes] if isinstance(prefixes, str) else list(prefixes)))
        self.variants = tuple(prefix_variants(self.prefixes))
        self._factory = client_factory
        self._clients: dict[str, Any] = {}
        self.cache: dict[str, Any] = {}

    def client(self, service: str) -> Any:
        if service not in self._clients:
            try:
                self._clients[service] = self._factory(service, self.region)
            except Exception as exc:  # noqa: BLE001
                raise CouldNotCheck(f"{service}: {describe_error(exc)}") from exc
        return self._clients[service]

    def has_prefix(self, name: str | None) -> bool:
        return bool(name) and any(variant in str(name) for variant in self.variants)


def default_client_factory(service: str, region: str) -> Any:
    if boto3 is None:
        raise CouldNotCheck("boto3 is not installed (pip install -r requirements.txt)")
    # Building a client makes no network call.
    return boto3.client(
        service,
        region_name=region,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=30,
            user_agent_extra="aws-kits-common-audit",
        ),
    )


# ---------------------------------------------------------------------------
# Checks: SageMaker AI
# ---------------------------------------------------------------------------
def check_sm_endpoints(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpoints.html (read 2026-10-07)
    for e in _paginate(c, "ListEndpoints", "Endpoints", "NextToken", "NextToken", MaxResults=100):
        yield Item(
            kind="SageMaker endpoint",
            name=e["EndpointName"],
            created=fmt_time(e.get("CreationTime")),
            state=str(e.get("EndpointStatus", "unknown")),
            bills_idle=BILLS_YES,
            why=(
                "Instance-backed endpoints bill per instance-hour until deleted: 'Delete endpoints to stop "
                "incurring charges.' This listing cannot tell a serverless endpoint (no idle charge) from an "
                "instance-backed one, so every endpoint is treated as billing."
            ),
            source=f"{src(SRC_SM_DELETE)}; {src(SRC_SM_PRICING)}",
            carries_prefix=ctx.has_prefix(e["EndpointName"]),
        )


def check_sm_endpoint_configs(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpointConfigs.html (read 2026-10-07)
    for e in _paginate(c, "ListEndpointConfigs", "EndpointConfigs", "NextToken", "NextToken", MaxResults=100):
        yield Item(
            kind="SageMaker endpoint configuration",
            name=e["EndpointConfigName"],
            created=fmt_time(e.get("CreationTime")),
            state="exists",
            bills_idle=BILLS_NO,
            why=(
                "No price line for an endpoint configuration on the SageMaker AI pricing page (absence of a "
                "price, not an explicit statement). Left behind because 'Deleting an endpoint will not delete "
                "the endpoint configuration or the SageMaker AI model.'"
            ),
            source=f"{src(SRC_SM_PRICING)}; {src(SRC_SM_DELETE)}",
            carries_prefix=ctx.has_prefix(e["EndpointConfigName"]),
        )


def check_sm_models(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListModels.html (read 2026-10-07)
    for m in _paginate(c, "ListModels", "Models", "NextToken", "NextToken", MaxResults=100):
        yield Item(
            kind="SageMaker model",
            name=m["ModelName"],
            created=fmt_time(m.get("CreationTime")),
            state="exists",
            bills_idle=BILLS_NO,
            why=(
                "No price line for a model object on the SageMaker AI pricing page (absence of a price, not an "
                "explicit statement). Its artifacts in S3 and its image in ECR are billed as storage there."
            ),
            source=src(SRC_SM_PRICING),
            carries_prefix=ctx.has_prefix(m["ModelName"]),
        )


def check_sm_inference_components(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListInferenceComponents.html (read 2026-10-07)
    for ic in _paginate(c, "ListInferenceComponents", "InferenceComponents", "NextToken", "NextToken", MaxResults=100):
        yield Item(
            kind="SageMaker inference component",
            name=ic["InferenceComponentName"],
            created=fmt_time(ic.get("CreationTime")),
            state=f"{ic.get('InferenceComponentStatus', 'unknown')} on endpoint {ic.get('EndpointName', '?')}",
            bills_idle=BILLS_YES,
            why=(
                "Billed through the instances of its endpoint. An endpoint only reaches zero instances when "
                "its inference components are scaled to zero copies and MinInstanceCount is 0; this listing "
                "does not show the copy count, so it is treated as billing."
            ),
            source=src(SRC_SM_ZERO),
            carries_prefix=ctx.has_prefix(ic["InferenceComponentName"]),
        )


_TRAINING_RUNNING = {"InProgress", "Stopping"}
_TRAINING_ENDED = {"Completed", "Failed", "Stopped", "Deleting"}
_WARM_POOL_HELD = {"Available", "InUse"}


def check_sm_training_jobs(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListTrainingJobs.html (read 2026-10-07)
    # No StatusEquals filter on purpose. The page says: "When StatusEquals and MaxResults are set at the same
    # time, the MaxResults number of training jobs are first retrieved ignoring the StatusEquals parameter and
    # then they are filtered", so a filter saves no call, and one filter value would miss jobs that are
    # Stopping and finished jobs that still hold a warm pool. Every job is read once and sorted out here.
    for j in _paginate(c, "ListTrainingJobs", "TrainingJobSummaries", "NextToken", "NextToken", MaxResults=100):
        status = str(j.get("TrainingJobStatus", "status not returned"))
        warm = (j.get("WarmPoolStatus") or {}).get("Status")
        if status in _TRAINING_RUNNING:
            kind, bills, why, source = (
                "SageMaker training job in progress", BILLS_YES,
                "A training job that is running or still stopping bills for its instances: 'You are charged for "
                "usage of the instance type you choose.'",
                src(SRC_SM_PRICING),
            )
        elif warm in _WARM_POOL_HELD:
            kind, bills, why, source = (
                "SageMaker training job with a retained warm pool", BILLS_YES,
                "The job has ended but its instances are kept warm: 'SageMaker AI managed warm pools are a "
                "billable resource.'",
                src(SRC_SM_WARM_POOLS),
            )
        elif status in _TRAINING_ENDED:
            continue
        else:
            kind, bills, why, source = (
                "SageMaker training job in a state this audit does not know", BILLS_UNKNOWN,
                "The status is not one this audit can map to a billing statement. Treated as possibly billing.",
                src(SRC_SM_PRICING),
            )
        yield Item(
            kind=kind,
            name=j.get("TrainingJobName", "unnamed training job"),
            created=fmt_time(j.get("CreationTime")),
            state=f"{status}/{j.get('SecondaryStatus', '?')}, warm pool {warm or 'none'}",
            bills_idle=bills,
            why=why,
            source=source,
            carries_prefix=ctx.has_prefix(j.get("TrainingJobName")),
        )


_NOTEBOOK_RUNNING = {"Pending", "InService", "Updating", "Stopping", "PendingMaintenance", "InMaintenance"}


def check_sm_notebooks(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListNotebookInstances.html (read 2026-10-07)
    for n in _paginate(c, "ListNotebookInstances", "NotebookInstances", "NextToken", "NextToken", MaxResults=100):
        status = str(n.get("NotebookInstanceStatus", "unknown"))
        if status in _NOTEBOOK_RUNNING:
            bills, why = BILLS_YES, (
                "A running notebook instance bills by the hour: 'You are charged for the instance type you "
                "choose, based on the duration of use.'"
            )
        else:
            # UNVERIFIED: no AWS page read on 2026-10-07 said whether the storage volume of a
            # stopped notebook instance is billed. Treated as unknown so it is never called clean.
            bills, why = BILLS_UNKNOWN, (
                "UNVERIFIED: the pricing page read today does not say whether the storage volume of a "
                "stopped notebook instance is billed. Delete the instance to be sure."
            )
        yield Item(
            kind="SageMaker notebook instance",
            name=n["NotebookInstanceName"],
            created=fmt_time(n.get("CreationTime")),
            state=f"{status} ({n.get('InstanceType', 'type not returned')})",
            bills_idle=bills,
            why=why,
            source=src(SRC_SM_PRICING),
            carries_prefix=ctx.has_prefix(n["NotebookInstanceName"]),
        )


def check_sm_apps(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListApps.html (read 2026-10-07)
    for a in _paginate(c, "ListApps", "Apps", "NextToken", "NextToken", MaxResults=100):
        status = str(a.get("Status", "unknown"))
        if status == "Deleted":
            continue  # ListApps keeps returning deleted apps for a while; they are not running
        name = "/".join(
            str(p) for p in (a.get("DomainId"), a.get("SpaceName") or a.get("UserProfileName"), a.get("AppType"), a.get("AppName")) if p
        )
        running = status in {"InService", "Pending"}
        yield Item(
            kind="SageMaker Studio app",
            name=name or "unnamed app",
            created=fmt_time(a.get("CreationTime")),
            state=status,
            bills_idle=BILLS_YES if running else BILLS_UNKNOWN,
            why=(
                "A running Studio app bills for its instance: 'The compute is only charged for the instance "
                "used when the JupyterLab space is running.'"
                if running
                else "App is not running but is not deleted; state could not be mapped to a billing statement."
            ),
            source=src(SRC_SM_PRICING),
            carries_prefix=ctx.has_prefix(name),
        )


def check_sm_spaces(ctx: Context) -> Iterator[Item]:
    c = ctx.client("sagemaker")
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListSpaces.html (read 2026-10-07)
    for s in _paginate(c, "ListSpaces", "Spaces", "NextToken", "NextToken", MaxResults=100):
        name = "/".join(str(p) for p in (s.get("DomainId"), s.get("SpaceName")) if p)
        yield Item(
            kind="SageMaker Studio space",
            name=name or "unnamed space",
            created=fmt_time(s.get("CreationTime")),
            state=str(s.get("Status", "unknown")),
            bills_idle=BILLS_STORAGE,
            why="'Storage charges for a JupyterLab space accrued until it is deleted.' Stopping the app is not enough.",
            source=src(SRC_SM_PRICING),
            carries_prefix=ctx.has_prefix(name),
        )


# ---------------------------------------------------------------------------
# Checks: Amazon Bedrock
# ---------------------------------------------------------------------------
# Vector stores that another check in this audit lists by itself.
_STORES_LISTED_ELSEWHERE = {
    "S3_VECTORS": "the S3 Vectors check",
    "OPENSEARCH_SERVERLESS": "the OpenSearch Serverless check",
}


def check_br_knowledge_bases(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock-agent")
    # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_ListKnowledgeBases.html (read 2026-10-07)
    kbs = list(_paginate(c, "ListKnowledgeBases", "knowledgeBaseSummaries", maxResults=100))
    for kb in kbs:
        kb_id = kb["knowledgeBaseId"]
        # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_GetKnowledgeBase.html (read 2026-10-07)
        detail = _call(c, "GetKnowledgeBase", knowledgeBaseId=kb_id).get("knowledgeBase")
        if not isinstance(detail, dict) or not detail:
            raise CouldNotCheck(
                f"GetKnowledgeBase: the response for {kb.get('name', '?')} ({kb_id}) had no 'knowledgeBase' detail, "
                "so its type and vector store are not known"
            )
        kb_type = str((detail.get("knowledgeBaseConfiguration") or {}).get("type", "type not returned"))
        store = str((detail.get("storageConfiguration") or {}).get("type", "none returned"))
        if kb_type == "MANAGED":
            bills, why = BILLS_STORAGE, (
                "Managed knowledge base: 'Index Storage ... $5.00 per GB of raw data / month' while it exists "
                "(Region for that figure was not shown in the text read)."
            )
        elif kb_type == "VECTOR" and store in _STORES_LISTED_ELSEWHERE:
            bills, why = BILLS_NO, (
                "No standing charge for a self-managed knowledge base is listed on the Bedrock pricing page "
                "(absence of a price, not an explicit statement). ITS VECTOR STORE BILLS SEPARATELY and is "
                "NOT deleted with the knowledge base: 'Delete the vector store itself for your knowledge "
                f"base.' Vector store type: {store}, which {_STORES_LISTED_ELSEWHERE[store]} lists."
            )
        else:
            bills, why = BILLS_UNKNOWN, (
                f"Knowledge base type {kb_type}, store {store}. This audit does NOT list that kind of store "
                "(for example an Aurora or RDS database, Neptune Analytics, an OpenSearch managed cluster, a "
                "Kendra index, a Redshift query engine, or a third-party store), and such a store can bill "
                "around the clock where it lives. 'Delete the vector store itself for your knowledge base.' "
                "Treated as possibly billing until you have checked that store yourself."
            )
        yield Item(
            kind="Bedrock knowledge base",
            name=f"{kb.get('name', '?')} ({kb_id})",
            created=fmt_time(detail.get("createdAt")),
            state=f"{kb.get('status', 'unknown')}, type {kb_type}, vector store {store}",
            bills_idle=bills,
            why=why,
            source=f"{src(SRC_BR_PRICING)}; {src(SRC_KB_DELETE)}",
            carries_prefix=ctx.has_prefix(kb.get("name")),
        )
        # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_ListDataSources.html (read 2026-10-07)
        for ds in _paginate(c, "ListDataSources", "dataSourceSummaries", knowledgeBaseId=kb_id, maxResults=100):
            yield Item(
                kind="Bedrock knowledge base data source",
                name=f"{ds.get('name', '?')} ({ds.get('dataSourceId', '?')}) in {kb_id}",
                created=f"not returned by this API (updated {fmt_time(ds.get('updatedAt'))})",
                state=str(ds.get("status", "unknown")),
                bills_idle=BILLS_NO,
                why=(
                    "No standing charge for a data source is listed on the Bedrock pricing page (absence of a "
                    "price, not an explicit statement). The documents it points at are billed where they are stored."
                ),
                source=src(SRC_BR_PRICING),
                carries_prefix=ctx.has_prefix(ds.get("name")),
            )


def check_br_guardrails(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock")
    # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListGuardrails.html (read 2026-10-07)
    for g in _paginate(c, "ListGuardrails", "guardrails", maxResults=100):
        yield Item(
            kind="Bedrock guardrail",
            name=f"{g.get('name', '?')} ({g.get('id', '?')}, version {g.get('version', '?')})",
            created=fmt_time(g.get("createdAt")),
            state=str(g.get("status", "unknown")),
            bills_idle=BILLS_NO,
            why=(
                "Guardrails are priced per unit processed (for example '$0.15 per 1,000 text units'; no Region "
                "was shown beside that figure in the page text read); no standing charge is listed."
            ),
            source=src(SRC_BR_PRICING),
            carries_prefix=ctx.has_prefix(g.get("name")),
        )


def check_br_provisioned(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock")
    # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListProvisionedModelThroughputs.html (read 2026-10-07)
    for p in _paginate(c, "ListProvisionedModelThroughputs", "provisionedModelSummaries", maxResults=100):
        yield Item(
            kind="Bedrock Provisioned Throughput",
            name=p["provisionedModelName"],
            created=fmt_time(p.get("creationTime")),
            state=f"{p.get('status', 'unknown')}, {p.get('modelUnits', '?')} model unit(s), commitment {p.get('commitmentDuration', 'none returned')}",
            bills_idle=BILLS_YES,
            why="Provisioned Throughput is priced 'per hour per model unit' whether or not it is invoked. This is the most expensive thing on this list.",
            source=src(SRC_BR_PRICING),
            carries_prefix=ctx.has_prefix(p["provisionedModelName"]),
        )


def check_br_custom_models(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock")
    # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListCustomModels.html (read 2026-10-07)
    for m in _paginate(c, "ListCustomModels", "modelSummaries", maxResults=100):
        yield Item(
            kind="Bedrock custom model",
            name=m["modelName"],
            created=fmt_time(m.get("creationTime")),
            state=f"{m.get('modelStatus', 'status not returned')}, {m.get('customizationType', 'type not returned')}",
            bills_idle=BILLS_STORAGE,
            why="Monthly storage: the pricing page lists a 'Price to store each custom model per month'.",
            source=src(SRC_BR_PRICING),
            carries_prefix=ctx.has_prefix(m["modelName"]),
        )


def check_br_imported_models(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock")
    # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListImportedModels.html (read 2026-10-07)
    for m in _paginate(c, "ListImportedModels", "modelSummaries", maxResults=100):
        yield Item(
            kind="Bedrock imported model (Custom Model Import)",
            name=m["modelName"],
            created=fmt_time(m.get("creationTime")),
            state="exists",
            bills_idle=BILLS_STORAGE,
            why=(
                "'Monthly storage cost per Custom Model Unit' applies while the model exists. Compute stops by "
                "itself: 'If there are no invocations for a 5-minute period, Bedrock will scale down to zero'."
            ),
            source=src(SRC_BR_PRICING),
            carries_prefix=ctx.has_prefix(m["modelName"]),
        )


def check_br_custom_model_deployments(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock")
    # https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListCustomModelDeployments.html (read 2026-10-07)
    for d in _paginate(c, "ListCustomModelDeployments", "modelDeploymentSummaries", maxResults=100):
        yield Item(
            kind="Bedrock custom model deployment",
            name=d["customModelDeploymentName"],
            created=fmt_time(d.get("createdAt")),
            state=str(d.get("status", "unknown")),
            bills_idle=BILLS_UNKNOWN,
            # UNVERIFIED: no price line for a custom model on-demand deployment was found on the
            # Bedrock pricing page read on 2026-10-07, so idle billing is unknown.
            why="UNVERIFIED: no price line for a custom model deployment was found on the pricing page read today. Treated as possibly billing.",
            source=src(SRC_BR_PRICING),
            carries_prefix=ctx.has_prefix(d["customModelDeploymentName"]),
        )


# ---------------------------------------------------------------------------
# Checks: Amazon OpenSearch Serverless
# ---------------------------------------------------------------------------
def _aoss_groups(ctx: Context) -> dict[str, dict[str, Any]]:
    """Collection groups by name. Cached per Region; a failure is cached and re-raised."""
    if "aoss_groups" not in ctx.cache:
        c = ctx.client("opensearchserverless")
        try:
            # https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_ListCollectionGroups.html (read 2026-10-07)
            groups = {
                g.get("name", ""): g
                for g in _paginate(c, "ListCollectionGroups", "collectionGroupSummaries", maxResults=100)
            }
            ctx.cache["aoss_groups"] = groups
        except CouldNotCheck as exc:
            ctx.cache["aoss_groups"] = exc
    cached = ctx.cache["aoss_groups"]
    if isinstance(cached, Exception):
        raise cached
    return cached


def _group_minimums(group: dict[str, Any]) -> tuple[float | None, float | None]:
    limits = group.get("capacityLimits") or {}
    return limits.get("minIndexingCapacityInOCU"), limits.get("minSearchCapacityInOCU")


def aoss_min_hourly_usd(standby_replicas: str | None) -> float:
    ocus = AOSS_MIN_OCU_DEVTEST if standby_replicas == "DISABLED" else AOSS_MIN_OCU_STANDBY
    return round(ocus * AOSS_OCU_HOUR_USD, 2)


def aoss_rate_note(region: str) -> str:
    if region in AOSS_OCU_HOUR_USD_BY_REGION:
        return f"${AOSS_OCU_HOUR_USD_BY_REGION[region]:.2f} per OCU per hour in {region} (price data behind the pricing page)"
    return (
        f"${AOSS_OCU_HOUR_USD:.2f} per OCU per hour, the LOWEST rate on the price data read; the rate for "
        f"{region} is not embedded here and was higher on that file"
    )


def check_aoss_collections(ctx: Context) -> Iterator[Item]:
    c = ctx.client("opensearchserverless")
    # https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_ListCollections.html (read 2026-10-07)
    summaries = list(_paginate(c, "ListCollections", "collectionSummaries", maxResults=100))
    if not summaries:
        return

    groups: dict[str, dict[str, Any]] = {}
    group_problem = ""
    try:
        groups = _aoss_groups(ctx)
    except CouldNotCheck as exc:
        group_problem = str(exc)

    details: dict[str, dict[str, Any]] = {}
    detail_problem: CouldNotCheck | None = None
    ids = [s["id"] for s in summaries if s.get("id")]
    for start in range(0, len(ids), 100):
        try:
            # https://docs.aws.amazon.com/opensearch-service/latest/ServerlessAPIReference/API_BatchGetCollection.html (read 2026-10-07)
            batch = _call(c, "BatchGetCollection", ids=ids[start : start + 100]).get("collectionDetails")
        except CouldNotCheck as exc:
            detail_problem = exc
            break
        if not isinstance(batch, list):
            detail_problem = CouldNotCheck("BatchGetCollection: response had no 'collectionDetails' list; standby replicas and type are not known")
            break
        for d in batch:
            details[d.get("id", "")] = d

    for s in summaries:
        d = details.get(s.get("id", ""), {})
        standby = d.get("standbyReplicas")
        group_name = s.get("collectionGroupName") or d.get("collectionGroupName")
        group = groups.get(group_name or "")
        generation = (group or {}).get("generation")
        min_hourly = aoss_min_hourly_usd(standby)

        if generation == "NEXTGEN":
            min_idx, min_search = _group_minimums(group or {})
            if min_idx == 0 and min_search == 0:
                bills, why = BILLS_STORAGE, (
                    "NextGen collection in a group whose minimum capacity is 0: 'There is no minimum OCU "
                    "requirement - Indexing and Search OCUs scale to zero after 10 minutes of inactivity.' "
                    "Stored data is still billed per GB-month."
                )
            elif min_idx is None or min_search is None:
                bills, why = BILLS_UNKNOWN, (
                    "NextGen collection, but its group's minimum capacity was not returned, so scale to zero "
                    "could not be confirmed. Treated as possibly billing."
                )
            else:
                bills, why = BILLS_YES, (
                    f"NextGen collection in a group with a minimum above zero (indexing {min_idx} OCU, search "
                    f"{min_search} OCU): 'OpenSearch Serverless still maintains the specified minimum number "
                    "of OCUs, and billing reflects that minimum.'"
                )
        else:
            if generation == "CLASSIC":
                label = "Classic collection."
            elif group_problem:
                label = f"Generation could not be read ({group_problem}); treated as Classic."
            else:
                # UNVERIFIED: that a collection with no collection group is always Classic. The
                # docs read on 2026-10-07 say NextGen "uses collection groups" but do not state
                # the converse. Treating it as Classic is the expensive, safe assumption.
                label = "No NextGen collection group found for it; treated as Classic (UNVERIFIED assumption, the safe one)."
            bills, why = BILLS_YES, (
                f"{label} BILLS AROUND THE CLOCK WITH ZERO QUERIES: '{AOSS_MIN_OCU_QUOTE}' "
                f"Standby replicas: {standby or 'not returned'}. At {aoss_rate_note(ctx.region)} this is at "
                f"least ${min_hourly:.2f} per hour (${min_hourly * 24:.2f} per day) for the first collection of its type."
            )
        yield Item(
            kind="OpenSearch Serverless collection",
            name=f"{s.get('name', '?')} ({s.get('id', '?')})",
            created=fmt_time(d.get("createdDate"), epoch_ms=True),
            state=f"{s.get('status', 'unknown')}, type {d.get('type', 'not returned')}, generation {generation or 'not determined'}, group {group_name or 'none'}",
            bills_idle=bills,
            why=why,
            source=f"{src(SRC_AOSS_PRICING)}; {src(SRC_AOSS_CAPACITY)}",
            carries_prefix=ctx.has_prefix(s.get("name")),
        )
    if detail_problem is not None:
        raise detail_problem


def check_aoss_collection_groups(ctx: Context) -> Iterator[Item]:
    for name, g in sorted(_aoss_groups(ctx).items()):
        min_idx, min_search = _group_minimums(g)
        generation = g.get("generation", "not returned")
        if g.get("numberOfCollections") == 0:
            bills, why = BILLS_NO, "'Empty collection groups do not consume OCUs or enforce capacity limits.'"
        elif (min_idx or 0) > 0 or (min_search or 0) > 0:
            bills, why = BILLS_YES, (
                f"Group minimum is above zero (indexing {min_idx} OCU, search {min_search} OCU): 'OpenSearch "
                "Serverless still maintains the specified minimum number of OCUs, and billing reflects that "
                "minimum.'"
            )
        elif min_idx is None or min_search is None:
            bills, why = BILLS_UNKNOWN, "Minimum capacity was not returned for this group; idle billing could not be ruled out."
        else:
            bills, why = BILLS_NO, "Group minimum capacity is 0 for indexing and search: 'A minimum of 0 enables scale to zero.'"
        yield Item(
            kind="OpenSearch Serverless collection group",
            name=f"{name} ({g.get('id', '?')})",
            created=fmt_time(g.get("createdDate"), epoch_ms=True),
            state=f"generation {generation}, {g.get('numberOfCollections', '?')} collection(s)",
            bills_idle=bills,
            why=why,
            source=src(SRC_AOSS_CAPACITY),
            carries_prefix=ctx.has_prefix(name),
        )


# ---------------------------------------------------------------------------
# Checks: Amazon S3 Vectors
# ---------------------------------------------------------------------------
def check_s3vectors(ctx: Context) -> Iterator[Item]:
    c = ctx.client("s3vectors")
    # https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListVectorBuckets.html (read 2026-10-07)
    buckets = list(_paginate(c, "ListVectorBuckets", "vectorBuckets", maxResults=500))
    for b in buckets:
        bucket_name = b["vectorBucketName"]
        yield Item(
            kind="S3 Vectors vector bucket",
            name=bucket_name,
            created=fmt_time(b.get("creationTime")),
            state="exists",
            bills_idle=BILLS_STORAGE,
            why=(
                "Storage only: the pricing page's row is 'S3 Vector Storage /Month - monthly logical storage of "
                "vector data, key, and metadata'. There is no compute to leave running."
            ),
            source=src(SRC_S3_PRICING),
            carries_prefix=ctx.has_prefix(bucket_name),
        )
        # https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_ListIndexes.html (read 2026-10-07)
        for ix in _paginate(c, "ListIndexes", "indexes", vectorBucketName=bucket_name, maxResults=500):
            yield Item(
                kind="S3 Vectors index",
                name=f"{bucket_name}/{ix.get('indexName', '?')}",
                created=fmt_time(ix.get("creationTime")),
                state="exists",
                bills_idle=BILLS_STORAGE,
                why="The vectors in the index are what the storage charge is based on.",
                source=src(SRC_S3_PRICING),
                carries_prefix=ctx.has_prefix(bucket_name) or ctx.has_prefix(ix.get("indexName")),
            )


# ---------------------------------------------------------------------------
# Checks: Amazon S3 general purpose buckets that look like a kit's
# ---------------------------------------------------------------------------
# Kit B: <prefix>-fedrag-corpus-<account>-<region>. Kit C: <prefix>-kitc-code-<account>-<region>.
# The infix is matched, not the prefix, so a changed or lost KIT_PREFIX does not hide a bucket.
_KIT_BUCKET_RE = re.compile(r"-(kita|fedrag|kitc)-")
_KIT_BUCKET_LABEL = {"kita": "kit A", "fedrag": "kit B", "kitc": "kit C"}


def kit_bucket_reason(name: str, ctx: Context) -> str:
    """Why a bucket name looks like a kit's, or ''."""
    match = _KIT_BUCKET_RE.search(name)
    if match:
        return f"its name has the {_KIT_BUCKET_LABEL[match.group(1)]} pattern '-{match.group(1)}-'"
    for prefix in ctx.prefixes:
        if name.startswith(f"{prefix}-"):
            return f"its name starts with the kit prefix '{prefix}-'"
    return ""


def _bucket_contents(c: Any, name: str) -> str:
    """'empty', 'not empty', or a plain statement that it could not be told. One read-only call, one key."""
    try:
        # https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html (read 2026-10-07)
        # "Returns metadata about all versions of the objects in a bucket." Asked for one key only. Versions
        # and delete markers are flattened lists in the S3 XML, so an empty bucket returns neither key.
        page = _call(c, "ListObjectVersions", Bucket=name, MaxKeys=1)
    except CouldNotCheck as exc:
        return f"could not tell whether it is empty ({exc})"
    if page.get("Versions") or page.get("DeleteMarkers"):
        return "not empty (at least one object, object version or delete marker)"
    return "empty (no object, object version or delete marker was returned)"


def check_s3_buckets(ctx: Context) -> Iterator[Item]:
    c = ctx.client("s3")
    # https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListBuckets.html (read 2026-10-07)
    # "Requests made to a Regional endpoint that is different from the bucket-region parameter are not
    # supported", so the Region asked for is always the Region of the client.
    buckets = list(_paginate(c, "ListBuckets", "Buckets", "ContinuationToken", "ContinuationToken", BucketRegion=ctx.region, MaxBuckets=1000))
    unread: list[str] = []
    for b in buckets:
        name = str(b.get("Name", ""))
        if not name or b.get("BucketRegion") not in (None, ctx.region):
            continue
        found_by = kit_bucket_reason(name, ctx)
        if not found_by:
            try:
                # https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetBucketTagging.html (read 2026-10-07)
                tags = _call(c, "GetBucketTagging", Bucket=name).get("TagSet")
            except CallFailed as exc:
                if exc.code != "NoSuchTagSet":  # NoSuchTagSet is how S3 says "this bucket has no tags"
                    unread.append(f"{name} ({exc.code or 'error'})")
                    continue
                tags = []
            if not isinstance(tags, list):
                unread.append(f"{name} (no TagSet in the response)")
                continue
            if any(t.get("Key") == PROJECT_TAG_KEY and t.get("Value") == PROJECT_TAG_VALUE for t in tags if isinstance(t, dict)):
                found_by = f"it carries the tag {PROJECT_TAG_KEY}={PROJECT_TAG_VALUE}"
        if not found_by:
            continue
        yield Item(
            kind="S3 bucket",
            name=name,
            created=fmt_time(b.get("CreationDate")),
            state=f"{_bucket_contents(c, name)}; listed because {found_by}",
            bills_idle=BILLS_STORAGE,
            why=(
                "S3 bills for what is stored: 'S3 Standard - General purpose storage for any type of data, "
                "typically used for frequently accessed data', priced per GB per month (the dollar rate is "
                "filled in per Region by the pricing page and is not quoted here). An empty bucket has nothing "
                "to bill, but it is a leftover that the kit's teardown should have deleted."
            ),
            source=src(SRC_S3_PRICING),
            carries_prefix=ctx.has_prefix(name),
        )
    if unread:
        shown = ", ".join(unread[:5]) + (f" and {len(unread) - 5} more" if len(unread) > 5 else "")
        raise CouldNotCheck(
            f"GetBucketTagging failed for {len(unread)} bucket(s): {shown}. A bucket tagged "
            f"{PROJECT_TAG_KEY}={PROJECT_TAG_VALUE} under another name could be among them"
        )


# ---------------------------------------------------------------------------
# Checks: Amazon Bedrock AgentCore
# ---------------------------------------------------------------------------
def check_ac_runtimes(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock-agentcore-control")
    # https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html (read 2026-10-07)
    for r in _paginate(c, "ListAgentRuntimes", "agentRuntimes", maxResults=100):
        runtime_id = r.get("agentRuntimeId")
        if not runtime_id:
            raise CouldNotCheck("ListAgentRuntimes: a runtime came back without an agentRuntimeId, so its detail cannot be read")
        # https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetAgentRuntime.html (read 2026-10-07)
        detail = _call(c, "GetAgentRuntime", agentRuntimeId=runtime_id)
        lifecycle = detail.get("lifecycleConfiguration")
        if not isinstance(lifecycle, dict):
            raise CouldNotCheck(
                f"GetAgentRuntime: the response for {r.get('agentRuntimeName', '?')} had no 'lifecycleConfiguration', "
                "so its compute type and session time limits are not known"
            )
        idle = lifecycle.get("idleRuntimeSessionTimeout")
        max_life = lifecycle.get("maxLifetime")
        limits = (
            f"This runtime's own settings: a session's compute is ended after it has been idle for "
            f"{idle if idle is not None else 'a time that was not returned (service default 900)'} seconds, and "
            f"{max_life if max_life is not None else 'a time that was not returned (service default 28800)'} seconds "
            "after it started at the latest."
        )
        artifact = detail.get("agentRuntimeArtifact") or {}
        if detail.get("capacityProviderConfiguration"):
            compute = "Instances (a capacity provider is configured)"
            bills, why = BILLS_YES, (
                f"This runtime uses the Instances compute type, which bills by the hour: '{AC_INSTANCES_QUOTE}' "
                "This audit does not list capacity providers or their instances; look at them yourself."
            )
        elif "codeConfiguration" in artifact:
            compute = "microVMs, direct code deployment"
            bills, why = BILLS_STORAGE, (
                f"A deployed runtime is not free while it sits there: '{AC_CODE_STORAGE_QUOTE}' "
                "The compute itself is billed per session, not per deployed runtime."
            )
        else:
            compute = "microVMs, container deployment" if "containerConfiguration" in artifact else "microVMs, artifact type not returned"
            bills, why = BILLS_STORAGE, (
                f"Its image is stored and billed elsewhere: '{AC_CODE_STORAGE_QUOTE}' "
                "The compute itself is billed per session, not per deployed runtime. This audit lists an ECR "
                "repository only when its name carries a kit prefix."
            )
        yield Item(
            kind="AgentCore runtime",
            name=f"{r.get('agentRuntimeName', '?')} ({runtime_id}, version {r.get('agentRuntimeVersion', '?')})",
            created=fmt_time(detail.get("createdAt")),
            state=(
                f"{detail.get('status') or r.get('status', 'unknown')}, {compute}, session idle timeout "
                f"{idle if idle is not None else 'not returned'} s, session max lifetime {max_life if max_life is not None else 'not returned'} s"
            ),
            bills_idle=bills,
            why=f"{why} {AC_SESSIONS_CANNOT_BE_LISTED} A session bills through its idle time: '{AC_SESSION_QUOTE}'. {limits}",
            source=f"{src(SRC_AC_PRICING)}; {src(SRC_AC_LIFECYCLE)}",
            carries_prefix=ctx.has_prefix(r.get("agentRuntimeName")),
        )


def check_ac_gateways(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock-agentcore-control")
    # https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGateways.html (read 2026-10-07)
    for g in _paginate(c, "ListGateways", "items", maxResults=100):
        yield Item(
            kind="AgentCore gateway",
            name=f"{g.get('name', '?')} ({g.get('gatewayId', '?')})",
            created=fmt_time(g.get("createdAt")),
            state=str(g.get("status", "unknown")),
            bills_idle=BILLS_STORAGE,
            why=(
                "Calls are per use ('$0.005 per 1,000 invocations'), but tools indexed for semantic search "
                "carry a standing monthly charge: '$0.02 per 100 tools indexed per month'. No Region is shown "
                "beside these figures on the page."
            ),
            source=src(SRC_AC_PRICING),
            carries_prefix=ctx.has_prefix(g.get("name")),
        )


def check_ac_memories(ctx: Context) -> Iterator[Item]:
    c = ctx.client("bedrock-agentcore-control")
    # https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListMemories.html (read 2026-10-07)
    for m in _paginate(c, "ListMemories", "memories", maxResults=100):
        yield Item(
            kind="AgentCore memory",
            name=str(m.get("id") or m.get("arn") or "unnamed memory"),
            created=fmt_time(m.get("createdAt")),
            state=str(m.get("status", "unknown")),
            bills_idle=BILLS_STORAGE,
            why=(
                "Stored memory is billed while it exists: short-term '$0.10 per GB-month', long-term "
                "'$0.75 per 1,000 records/month' (built-in). No Region is shown beside these figures on the page."
            ),
            source=src(SRC_AC_PRICING),
            carries_prefix=ctx.has_prefix(m.get("id")),
        )


# ---------------------------------------------------------------------------
# Checks: ECR (names that carry a kit prefix) and CloudWatch Logs
# ---------------------------------------------------------------------------
def check_ecr(ctx: Context) -> Iterator[Item]:
    c = ctx.client("ecr")
    # https://docs.aws.amazon.com/AmazonECR/latest/APIReference/API_DescribeRepositories.html (read 2026-10-07)
    # The API has no name filter other than exact names, so all repositories are listed and filtered here.
    for r in _paginate(c, "DescribeRepositories", "repositories", maxResults=100):
        name = r.get("repositoryName", "")
        if not ctx.has_prefix(name):
            continue
        yield Item(
            kind="ECR repository",
            name=name,
            created=fmt_time(r.get("createdAt")),
            state="exists",
            bills_idle=BILLS_STORAGE,
            why="Stored images are billed per GB-month for as long as they exist; an agent or model image left behind keeps costing a little.",
            source=src(SRC_ECR_PRICING),
            carries_prefix=True,
        )


# Log groups the kits' services make. They are looked up by these fixed name prefixes, whatever the kit
# prefix is, so a changed or lost KIT_PREFIX does not hide them.
FIXED_LOG_GROUP_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/aws/sagemaker/Endpoints/", "SageMaker endpoint logs (kit A)"),
    ("/aws/bedrock-agentcore/", "AgentCore runtime logs (kit C)"),
    ("/aws/vendedlogs/bedrock-agentcore/", "AgentCore usage and application logs (kit C)"),
    ("aws/spans", "CloudWatch Transaction Search spans (only if you turned it on; kit C README step 5)"),
)


def log_group_queries(ctx: Context) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = [{"logGroupNamePrefix": prefix} for prefix, _ in FIXED_LOG_GROUP_PREFIXES]
    # "based on a case-sensitive substring search": the hyphen and the underscore form are both asked for.
    queries += [{"logGroupNamePattern": variant} for variant in ctx.variants]
    return queries


def check_log_groups(ctx: Context) -> Iterator[Item]:
    c = ctx.client("logs")
    seen: set[str] = set()
    for query in log_group_queries(ctx):
        # https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html (read 2026-10-07)
        # "logGroupNamePattern and logGroupNamePrefix are mutually exclusive", so each query carries one of them.
        # "If you specify logGroupNamePattern in your request, then only arn, creationTime, and logGroupName are
        # included in the response", so stored bytes and retention are shown only when the API returns them.
        for g in _paginate(c, "DescribeLogGroups", "logGroups", **query, limit=50):
            name = g.get("logGroupName", "unnamed log group")
            if name in seen:
                continue
            seen.add(name)
            if "storedBytes" in g:
                retention = g.get("retentionInDays")
                state = f"{g['storedBytes']} bytes stored, retention {str(retention) + ' days' if retention else 'not set'}"
            else:
                state = "exists (stored bytes and retention were not returned; the API leaves them out when listing by name pattern)"
            yield Item(
                kind="CloudWatch log group",
                name=name,
                created=fmt_time(g.get("creationTime"), epoch_ms=True),
                state=state,
                bills_idle=BILLS_STORAGE,
                why="Stored log data is billed per GB-month for as long as it is kept; deleting an endpoint or runtime does not delete its log group.",
                source=src(SRC_CW_PRICING),
                carries_prefix=ctx.has_prefix(name),
            )


# ---------------------------------------------------------------------------
# Registry and runner
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Check:
    check_id: str
    family: str
    title: str
    planned_calls: tuple[str, ...]
    run: Callable[[Context], Iterator[Item]]


CHECKS: tuple[Check, ...] = (
    Check("sm_endpoints", "sagemaker", "SageMaker endpoints", ("sagemaker.ListEndpoints(MaxResults=100)",), check_sm_endpoints),
    Check("sm_endpoint_configs", "sagemaker", "SageMaker endpoint configurations", ("sagemaker.ListEndpointConfigs(MaxResults=100)",), check_sm_endpoint_configs),
    Check("sm_models", "sagemaker", "SageMaker models", ("sagemaker.ListModels(MaxResults=100)",), check_sm_models),
    Check("sm_inference_components", "sagemaker", "SageMaker inference components", ("sagemaker.ListInferenceComponents(MaxResults=100)",), check_sm_inference_components),
    Check("sm_training_jobs", "sagemaker", "SageMaker training jobs running, stopping or holding a warm pool", ("sagemaker.ListTrainingJobs(MaxResults=100)  [every job is read; sorted out here]",), check_sm_training_jobs),
    Check("sm_notebooks", "sagemaker", "SageMaker notebook instances", ("sagemaker.ListNotebookInstances(MaxResults=100)",), check_sm_notebooks),
    Check("sm_apps", "sagemaker", "SageMaker Studio apps", ("sagemaker.ListApps(MaxResults=100)",), check_sm_apps),
    Check("sm_spaces", "sagemaker", "SageMaker Studio spaces", ("sagemaker.ListSpaces(MaxResults=100)",), check_sm_spaces),
    Check(
        "br_knowledge_bases", "bedrock", "Bedrock knowledge bases and data sources",
        (
            "bedrock-agent.ListKnowledgeBases(maxResults=100)",
            "bedrock-agent.GetKnowledgeBase(knowledgeBaseId=<each>)",
            "bedrock-agent.ListDataSources(knowledgeBaseId=<each>, maxResults=100)",
        ),
        check_br_knowledge_bases,
    ),
    Check("br_guardrails", "bedrock", "Bedrock guardrails", ("bedrock.ListGuardrails(maxResults=100)",), check_br_guardrails),
    Check("br_provisioned", "bedrock", "Bedrock Provisioned Throughput", ("bedrock.ListProvisionedModelThroughputs(maxResults=100)",), check_br_provisioned),
    Check("br_custom_models", "bedrock", "Bedrock custom models", ("bedrock.ListCustomModels(maxResults=100)",), check_br_custom_models),
    Check("br_imported_models", "bedrock", "Bedrock imported models", ("bedrock.ListImportedModels(maxResults=100)",), check_br_imported_models),
    Check("br_custom_model_deployments", "bedrock", "Bedrock custom model deployments", ("bedrock.ListCustomModelDeployments(maxResults=100)",), check_br_custom_model_deployments),
    Check(
        "aoss_collections", "opensearch", "OpenSearch Serverless collections",
        (
            "opensearchserverless.ListCollections(maxResults=100)",
            "opensearchserverless.ListCollectionGroups(maxResults=100)  [only if a collection exists]",
            "opensearchserverless.BatchGetCollection(ids=<up to 100 per call>)  [only if a collection exists]",
        ),
        check_aoss_collections,
    ),
    Check("aoss_collection_groups", "opensearch", "OpenSearch Serverless collection groups", ("opensearchserverless.ListCollectionGroups(maxResults=100)",), check_aoss_collection_groups),
    Check(
        "s3vectors", "s3vectors", "S3 Vectors vector buckets and indexes",
        ("s3vectors.ListVectorBuckets(maxResults=500)", "s3vectors.ListIndexes(vectorBucketName=<each>, maxResults=500)"),
        check_s3vectors,
    ),
    Check(
        "s3_buckets", "s3", "S3 buckets that look like a kit's (name pattern, kit prefix, or tag project=aws-kits)",
        (
            "s3.ListBuckets(BucketRegion=<this Region>, MaxBuckets=1000)",
            "s3.GetBucketTagging(Bucket=<each bucket whose name is not a kit's>)",
            "s3.ListObjectVersions(Bucket=<each kit bucket found>, MaxKeys=1)  [empty or not; nothing is read]",
        ),
        check_s3_buckets,
    ),
    Check(
        "ac_runtimes", "agentcore", "AgentCore runtimes",
        ("bedrock-agentcore-control.ListAgentRuntimes(maxResults=100)", "bedrock-agentcore-control.GetAgentRuntime(agentRuntimeId=<each>)"),
        check_ac_runtimes,
    ),
    Check("ac_gateways", "agentcore", "AgentCore gateways", ("bedrock-agentcore-control.ListGateways(maxResults=100)",), check_ac_gateways),
    Check("ac_memories", "agentcore", "AgentCore memory resources", ("bedrock-agentcore-control.ListMemories(maxResults=100)",), check_ac_memories),
    Check("ecr", "ecr", "ECR repositories whose name carries a kit prefix", ("ecr.DescribeRepositories(maxResults=100)  [filtered by prefix here]",), check_ecr),
    Check(
        "log_groups", "logs", "CloudWatch log groups of the kits' services, and any whose name carries a kit prefix",
        (
            "logs.DescribeLogGroups(logGroupNamePrefix=<each of: " + ", ".join(p for p, _ in FIXED_LOG_GROUP_PREFIXES) + ">, limit=50)",
            "logs.DescribeLogGroups(logGroupNamePattern=<each kit prefix, and its underscore form>, limit=50)",
        ),
        check_log_groups,
    ),
)
FAMILIES: tuple[str, ...] = tuple(dict.fromkeys(c.family for c in CHECKS))


def run_check(check: Check, ctx: Context) -> CheckResult:
    """Run one check. Whatever happens, the result is ok or 'could not check', never silent."""
    result = CheckResult(check.check_id, check.family, check.title, ctx.region, STATUS_OK)
    try:
        for item in check.run(ctx):
            result.items.append(item)
    except Exception as exc:  # noqa: BLE001 - nothing may escape as "none found"
        result.status = STATUS_COULD_NOT_CHECK
        result.reason = describe_error(exc)
        if isinstance(exc, (KeyError, TypeError, AttributeError)):
            result.reason = f"unexpected response shape ({result.reason})"
    return result


def run_audit(
    regions: list[str],
    prefixes: Iterable[str] | str,
    client_factory: Callable[[str, str], Any] = default_client_factory,
    skip: tuple[str, ...] = (),
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for region in regions:
        ctx = Context(region, prefixes, client_factory)
        for check in CHECKS:
            if check.family in skip:
                results.append(
                    CheckResult(check.check_id, check.family, check.title, region, STATUS_SKIPPED, "skipped at your request (--skip)")
                )
                continue
            results.append(run_check(check, ctx))
    return results


def summarise(results: list[CheckResult]) -> dict[str, int]:
    counts = {BILLS_YES: 0, BILLS_STORAGE: 0, BILLS_UNKNOWN: 0, BILLS_NO: 0, STATUS_COULD_NOT_CHECK: 0, STATUS_SKIPPED: 0, "checks_completed": 0}
    for r in results:
        if r.status == STATUS_COULD_NOT_CHECK:
            counts[STATUS_COULD_NOT_CHECK] += 1
        elif r.status == STATUS_SKIPPED:
            counts[STATUS_SKIPPED] += 1
        else:
            counts["checks_completed"] += 1
        for item in r.items:
            counts[item.bills_idle] = counts.get(item.bills_idle, 0) + 1
    return counts


def verdict(
    results: list[CheckResult],
    ignore_storage_only: bool = False,
    problems: Iterable[str] = (),
    kit_rows_found: int = 0,
) -> tuple[int, str, list[str]]:
    """(exit code, one-word verdict, every reason the result is not clean).

    Exit 0 needs all of: every check completed, none skipped, no scope problem,
    nothing that bills, no storage (unless storage was ignored on request), and,
    with --after-teardown KIT, no row of that kit marked FOUND, whatever it costs.
    """
    counts = summarise(results)
    reasons: list[str] = []
    if kit_rows_found:
        reasons.append(REASON_KIT_FOUND)
    if counts[BILLS_YES] or counts[BILLS_UNKNOWN]:
        reasons.append(REASON_BILLS)
    if counts[BILLS_STORAGE] and not ignore_storage_only:
        reasons.append(REASON_STORAGE)
    if counts[STATUS_COULD_NOT_CHECK]:
        reasons.append(REASON_COULD_NOT_CHECK)
    if list(problems):
        reasons.append(REASON_SCOPE)
    if counts[STATUS_SKIPPED]:
        reasons.append(REASON_SKIPPED)
    if counts["checks_completed"] == 0:
        reasons.append(REASON_NOTHING_RAN)  # nothing was actually checked: that is not "clean"
    if not reasons:
        return EXIT_CLEAN, VERDICT_CLEAN, reasons
    if REASON_BILLS in reasons or REASON_STORAGE in reasons or REASON_KIT_FOUND in reasons:
        label = VERDICT_NOT_CLEAN
    elif REASON_COULD_NOT_CHECK in reasons or REASON_SCOPE in reasons:
        label = VERDICT_COULD_NOT_CHECK
    elif REASON_SKIPPED in reasons:
        label = VERDICT_SKIPPED
    else:
        label = VERDICT_COULD_NOT_CHECK
    return EXIT_NOT_CLEAN, label, reasons


def decide_exit(
    results: list[CheckResult], ignore_storage_only: bool = False, problems: Iterable[str] = (), kit_rows_found: int = 0,
) -> int:
    return verdict(results, ignore_storage_only, problems, kit_rows_found)[0]


# ---------------------------------------------------------------------------
# What each kit can create, for --after-teardown
# Source: the round 1 review's coverage table, re-checked on 2026-10-07 against
# the create and put calls in each kit's code, and again in round 2 at 13:35 UTC
# against every create, put and start call (kit A kitlib.py; kit B kitlib/aws.py,
# kitlib/resources.py and 40_create_guardrail.py; kit C 30_deploy.py,
# 40_enable_observability.py, 50_invoke_hosted.py and
# optional_gateway/10_create_gateway.py). No resource type was added or removed.
# own_check on each row says whether the kit's own 99_verify_clean.py counts that
# kind of thing as a leftover; it was read from those scripts at the same minute.
# ---------------------------------------------------------------------------
COVERAGE_NONE = "checked: none found"
COVERAGE_FOUND = "found"
COVERAGE_COULD_NOT = "could not check"
COVERAGE_NOT_CHECKABLE = "not checkable by this audit"

IAM_CONSOLE = "IAM console (https://console.aws.amazon.com/iam/), navigation pane, Roles"


@dataclasses.dataclass(frozen=True)
class KitResource:
    label: str
    check_id: str = ""            # '' means this audit has no check for it
    kinds: tuple[str, ...] = ()   # item kinds that count
    pattern: str = ""             # regular expression searched in the item name; prefix-independent
    where: str = ""               # where to look when the audit cannot
    note: str = ""
    own_check: bool = True        # the kit's own 99_verify_clean.py counts this kind of thing as a leftover (read in its code)


KIT_FOLDERS = {"a": "kit_a_gpu_endpoint", "b": "kit_b_federal_rag_eval", "c": "kit_c_langgraph_agentcore"}

KIT_COVERAGE: dict[str, tuple[KitResource, ...]] = {
    "a": (
        KitResource("SageMaker endpoint <prefix>-kita-endpoint", "sm_endpoints", ("SageMaker endpoint",), r"-kita-endpoint"),
        KitResource("SageMaker endpoint configuration <prefix>-kita-config-<revision>", "sm_endpoint_configs", ("SageMaker endpoint configuration",), r"-kita-config-"),
        KitResource("SageMaker model <prefix>-kita-model-<revision>", "sm_models", ("SageMaker model",), r"-kita-model-"),
        KitResource(
            "CloudWatch log group /aws/sagemaker/Endpoints/<prefix>-kita-endpoint", "log_groups", ("CloudWatch log group",),
            r"^/aws/sagemaker/Endpoints/.*-kita-", note="made by SageMaker for the endpoint; deleting the endpoint does not delete it",
        ),
        KitResource(
            "IAM execution role (you make it by hand in README section 3; the kit only reads it)",
            where=IAM_CONSOLE + "; the role name is SAGEMAKER_EXECUTION_ROLE_NAME in your config.env",
            note="this audit makes no IAM call",
        ),
    ),
    "b": (
        KitResource("S3 bucket <prefix>-fedrag-corpus-<account>-<region> and the corpus objects in it", "s3_buckets", ("S3 bucket",), r"-fedrag-corpus-"),
        KitResource("Bedrock knowledge base <prefix>-fedrag-kb", "br_knowledge_bases", ("Bedrock knowledge base",), r"-fedrag-kb\b"),
        KitResource("Knowledge base data source <prefix>-fedrag-s3-source", "br_knowledge_bases", ("Bedrock knowledge base data source",), r"-fedrag-s3-source"),
        KitResource("Bedrock guardrail <prefix>-fedrag-grounding and its version", "br_guardrails", ("Bedrock guardrail",), r"-fedrag-grounding"),
        KitResource(
            "S3 Vectors bucket <prefix>-fedrag-vectors and index <prefix>-fedrag-index (only with KB_TYPE=s3vectors)",
            "s3vectors", ("S3 Vectors vector bucket", "S3 Vectors index"), r"-fedrag-vectors",
        ),
        KitResource(
            "IAM role <prefix>-fedrag-kb-role-<region> and its inline policy <prefix>-fedrag-kb-access",
            where=IAM_CONSOLE, note="this audit makes no IAM call",
        ),
        KitResource(
            "Knowledge base ingestion job (started by 30_deploy_kb.py)",
            where="Amazon Bedrock console (https://console.aws.amazon.com/bedrock/), Knowledge Bases, your knowledge base, choose the data source to view its Sync history",
            note="runs for a while and ends by itself; it is gone with the knowledge base",
        ),
    ),
    "c": (
        KitResource("S3 bucket <prefix>-kitc-code-<account>-<region> and the code zip in it", "s3_buckets", ("S3 bucket",), r"-kitc-code-"),
        KitResource("AgentCore runtime <prefix with _>_kitc_fr_agent, its version and DEFAULT endpoint", "ac_runtimes", ("AgentCore runtime",), r"_kitc_fr_agent"),
        KitResource(
            "Open runtime sessions (50_invoke_hosted.py starts them)",
            where=(
                "nowhere complete: no AWS API in the installed boto3 lists a runtime's sessions. Kit C's own .state.json "
                "records each session id and 90_teardown.py stops them; the CloudWatch GenAI Observability page "
                "(https://console.aws.amazon.com/cloudwatch/home#gen-ai-observability) shows session data only when "
                "observability was on"
            ),
            note=(
                "a session bills through idle time until it ends; its compute is ended by the runtime's idle timeout "
                "(service default 900 seconds, kit C default 120) or maximum lifetime (service default 28800 seconds, "
                "kit C default 900)"
            ),
        ),
        KitResource(
            "CloudWatch log groups /aws/vendedlogs/bedrock-agentcore/<prefix>-kitc-usage and -app", "log_groups", ("CloudWatch log group",),
            r"^/aws/vendedlogs/bedrock-agentcore/.*-kitc-",
        ),
        KitResource(
            "CloudWatch log group /aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT (made by AgentCore)", "log_groups", ("CloudWatch log group",),
            r"^/aws/bedrock-agentcore/runtimes/.*_kitc_fr_agent",
        ),
        KitResource(
            "CloudWatch log group aws/spans (only if you turned on Transaction Search; the kit does not create it)", "log_groups",
            ("CloudWatch log group",), r"^aws/spans", own_check=False,
            note="kit C never creates or deletes this log group; its own clean check prints it as information and does not count it as a leftover",
        ),
        KitResource("AgentCore gateway <prefix>-kitc-gateway (optional_gateway/ only)", "ac_gateways", ("AgentCore gateway",), r"-kitc-gateway"),
        KitResource(
            "Gateway target (optional_gateway/ only)",
            where="AgentCore console, Gateways page (https://console.aws.amazon.com/bedrock-agentcore/toolsAndGateways), select the gateway",
            note="this audit sees it only through its gateway, in the row above",
        ),
        KitResource(
            "IAM roles <prefix>-kitc-runtime-role (inline policy <prefix>-kitc-runtime-policy) and <prefix>-kitc-gateway-role",
            where=IAM_CONSOLE, note="this audit makes no IAM call",
        ),
        KitResource(
            "Log delivery sources, destinations and deliveries <prefix>-kitc-<kind>-src and -dst (40_enable_observability.py)",
            where=(
                "AgentCore console, Agent Runtime page (https://console.aws.amazon.com/bedrock-agentcore/agents), select the "
                "runtime, Log delivery pane; a delivery left behind after the runtime is gone shows only through the "
                "CloudWatch Logs API (aws logs describe-deliveries)"
            ),
            note="this audit makes no delivery call; a delivery has no standing charge, log data is billed when it flows",
        ),
        KitResource(
            "Workload identity (AgentCore makes it with the runtime)",
            where="AgentCore console (https://console.aws.amazon.com/bedrock-agentcore/), Identity pages; UNVERIFIED which page lists workload identities",
            note="this audit has no check for it; no price line for it was found",
        ),
    ),
}


def coverage_rows(kit: str, results: list[CheckResult]) -> list[dict[str, Any]]:
    """One row per resource type the kit can create, with what this audit saw."""
    rows: list[dict[str, Any]] = []
    for resource in KIT_COVERAGE[kit]:
        row: dict[str, Any] = {
            "resource": resource.label, "status": COVERAGE_NOT_CHECKABLE, "check_id": resource.check_id or None,
            "items": [], "problems": [], "where_to_look": resource.where, "note": resource.note,
            "counted_by_the_kits_own_check": resource.own_check if resource.check_id else None,
        }
        if resource.check_id:
            pattern = re.compile(resource.pattern)
            relevant = [r for r in results if r.check_id == resource.check_id]
            for r in relevant:
                mine = [i for i in r.items if i.kind in resource.kinds and pattern.search(i.name)]
                row["items"] += [{"region": r.region, "name": i.name, "bills_idle": i.bills_idle, "state": i.state} for i in mine]
                if r.status == STATUS_COULD_NOT_CHECK:
                    row["problems"].append(f"{r.region}: {r.reason}")
                elif r.status == STATUS_SKIPPED:
                    row["problems"].append(f"{r.region}: skipped at your request (--skip)")
            if not relevant:
                row["problems"].append("the check did not run")
            if row["items"]:
                row["status"] = COVERAGE_FOUND
            elif row["problems"]:
                row["status"] = COVERAGE_COULD_NOT
            else:
                row["status"] = COVERAGE_NONE
        rows.append(row)
    return rows


def kit_rows_found(kit: str | None, results: list[CheckResult]) -> tuple[int, int]:
    """(rows of this kit marked FOUND, how many of those the kit's own clean check also counts)."""
    if not kit:
        return 0, 0
    found = [row for row in coverage_rows(kit, results) if row["status"] == COVERAGE_FOUND]
    return len(found), sum(1 for row in found if row["counted_by_the_kits_own_check"])


def items_outside_kit(kit: str, results: list[CheckResult]) -> dict[str, int]:
    """Items the audit listed that match no row of this kit, counted by verdict."""
    rows = [(r.check_id, r.kinds, re.compile(r.pattern)) for r in KIT_COVERAGE[kit] if r.check_id]
    counts = {BILLS_YES: 0, BILLS_UNKNOWN: 0, BILLS_STORAGE: 0, BILLS_NO: 0}
    for result in results:
        for item in result.items:
            if not any(result.check_id == check_id and item.kind in kinds and pattern.search(item.name) for check_id, kinds, pattern in rows):
                counts[item.bills_idle] = counts.get(item.bills_idle, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def audited_line(scope: Scope, identity: Identity) -> str:
    tail = " (--only: the kit folders were not read)" if scope.only else ""
    return f"Audited: {identity.label()}; Regions {', '.join(scope.region_list)}; prefixes {', '.join(scope.prefix_list)}{tail}."


def scope_lines(scope: Scope, identity: Identity | None) -> list[str]:
    lines = ["SCOPE (what is audited, and where each value came from)"]
    if identity is not None:
        lines.append(f"    account: {identity.label()}" + (" (from sts:GetCallerIdentity; last four digits only)" if identity.account else " (sts:GetCallerIdentity failed, see below)"))
    for region, sources in scope.regions.items():
        lines.append(f"    Region {region}: {', '.join(sources)}")
    for prefix, sources in scope.prefixes.items():
        lines.append(f"    prefix {prefix}: {', '.join(sources)}")
    if scope.kits_read:
        lines.append(
            f"    kit folders read: {', '.join(scope.kits_read)} (config.env, config.example.env, and every file whose "
            f"name starts with {STATE_FILE_NAME})"
        )
        lines.append(f"    state files found: {', '.join(scope.state_files_read) if scope.state_files_read else 'none'}")
    for sentence in state_sentences(scope):
        lines.append(f"    NO RECORD OF WHERE: {sentence}.")
    for note in scope.notes:
        lines.append(f"    note: {note}.")
    if scope.problems:
        lines.append("SCOPE PROBLEMS (each one makes the result NOT CLEAN)")
        for problem in scope.problems:
            lines.append(f"    - {problem}.")
        if scope.damaged_state:
            lines.append(
                "    A damaged state file keeps this audit at NOT CLEAN for as long as it sits in the kit folder. The kit's own "
                "README says what to do with it. This audit never deletes, renames or changes it."
            )
        lines.append("    To audit named Regions and prefixes without reading the kit folders, use --only --region R --prefix P.")
    return lines


def session_note_lines(results: list[CheckResult]) -> list[str]:
    runtimes = [(r.region, i) for r in results for i in r.items if i.kind == "AgentCore runtime"]
    if not runtimes:
        return []
    return [
        f"NOTE on AgentCore sessions: {len(runtimes)} runtime(s) exist. {AC_SESSIONS_CANNOT_BE_LISTED}",
        f"    What a session costs: '{AC_SESSION_QUOTE}'. Source: {src(SRC_AC_PRICING)}.",
        f"    When its compute ends by itself: '{AC_STOPPED_QUOTE}' Source: {src(SRC_AC_SESSIONS)}.",
        f"    Time limits: idleRuntimeSessionTimeout '{AC_IDLE_DEFAULT_QUOTE}', maxLifetime '{AC_MAX_DEFAULT_QUOTE}'. "
        f"'{AC_LIMITS_QUOTE}' Source: {src(SRC_AC_LIFECYCLE)}. Each runtime's own two values are in its entry above.",
        "    So: a session opened before this audit can still be billing for as long as those limits allow. Kit C records "
        "its session ids in its .state.json and its 90_teardown.py stops them.",
    ]


def region_note_lines(scope: Scope) -> list[str]:
    """With --all-regions: the Regions that were left out, and why that still matters."""
    if not scope.all_regions_listed or not scope.not_enabled_regions:
        return []
    return [
        f"NOTE on Regions that are not enabled: {len(scope.not_enabled_regions)} Region(s) have the status DISABLED for this "
        f"account and were NOT audited: {', '.join(scope.not_enabled_regions)}.",
        "    That is right for a Region you never enabled. If you enabled one, used it and disabled it again, what is left "
        f"there still bills: '{REGION_DISABLED_QUOTE}' Source: {src(SRC_REGIONS_GUIDE)}.",
    ]


def per_region_lines(results: list[CheckResult]) -> list[str]:
    """One line per Region, for a run over more than one Region."""
    regions = list(dict.fromkeys(r.region for r in results if r.family != "account"))
    if len(regions) < 2:
        return []
    lines = ["PER REGION"]
    for region in regions:
        mine = [r for r in results if r.region == region and r.family != "account"]
        counts = summarise(mine)
        found = counts[BILLS_YES] + counts[BILLS_UNKNOWN] + counts[BILLS_STORAGE] + counts[BILLS_NO]
        parts = []
        if found:
            parts.append(
                f"{found} item(s) found (bills yes {counts[BILLS_YES]}, unknown {counts[BILLS_UNKNOWN]}, storage only "
                f"{counts[BILLS_STORAGE]}, no idle charge {counts[BILLS_NO]})"
            )
        if counts[STATUS_COULD_NOT_CHECK]:
            failed = ", ".join(dict.fromkeys(r.family for r in mine if r.status == STATUS_COULD_NOT_CHECK))
            parts.append(f"{counts[STATUS_COULD_NOT_CHECK]} check(s) could not run ({failed})")
        if counts[STATUS_SKIPPED]:
            parts.append(f"{counts[STATUS_SKIPPED]} check(s) skipped")
        lines.append(f"    {region}: {'; '.join(parts) if parts else 'every check ran, nothing found'}")
    return lines


NO_STATE_WORDS = "no state file"
NO_REGION_WORDS = "its state file names no Region"
ONLY_THESE_REGIONS = "only the Regions listed here were checked"
NO_KITS_TEXT = f"no kit folder was found beside this script, so this audit cannot know where any kit was deployed; {ONLY_THESE_REGIONS}"
ALL_REGIONS_OFFER = "To check every Region that is enabled for this account, run again with --all-regions."


def state_sentences(scope: Scope) -> list[str]:
    """In plain words: for which kits this audit has no record of where the kit was deployed.

    One kit:  "kit_x: no state file, so this audit cannot know where that kit was last deployed; only
    the Regions listed here were checked". Several kits: each is named with its reason, and the
    consequence is said once for all of them.
    """
    if scope.only:
        return []  # the kit folders were not read at all; the LIMITED CHECK words say so
    sentences = [NO_KITS_TEXT] if scope.no_kit_folders else []
    named = [f"{kit}: {NO_STATE_WORDS}" for kit in scope.kits_without_state]
    named += [f"{kit}: {NO_REGION_WORDS}" for kit in scope.kits_state_without_region]
    if len(named) == 1:
        sentences.append(f"{named[0]}, so this audit cannot know where that kit was last deployed; {ONLY_THESE_REGIONS}")
    elif named:
        sentences.append(f"{'; '.join(named)}; so this audit cannot know where those kits were last deployed; {ONLY_THESE_REGIONS}")
    return sentences


def limited_check_phrases(results: list[CheckResult], scope: Scope, ignore_storage_only: bool) -> list[str]:
    """The limits the owner asked for with a flag, in capitals. They open the RESULT line."""
    phrases: list[str] = []
    if scope.only:
        phrases.append(
            "THE KIT FOLDERS WERE NOT READ (--only), SO ONLY THE REGIONS AND PREFIXES YOU NAMED WERE AUDITED AND NOTHING "
            "CHECKS THAT THEY ARE THE ONES THE KITS USED"
        )
    if ignore_storage_only:
        stored = summarise(results)[BILLS_STORAGE]
        runtimes = sum(1 for r in results for i in r.items if i.kind == "AgentCore runtime")
        text = "STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only): " + (
            f"{stored} OF THEM REMAIN AND ARE STILL BILLED FOR WHAT THEY STORE" if stored else "NONE WAS FOUND THIS TIME"
        )
        if runtimes:
            text += f"; {runtimes} AGENTCORE RUNTIME(S) REMAIN AND THEIR OPEN SESSIONS CANNOT BE LISTED (see the NOTE above)"
        phrases.append(text)
    return phrases


def scope_reason_phrases(scope: Scope) -> list[str]:
    phrases: list[str] = []
    if scope.damaged_state:
        phrases.append(f"unreadable or damaged state file(s): {', '.join(scope.damaged_state)}")
    if scope.all_regions_failure:
        phrases.append(f"could not list Regions ({scope.all_regions_failure}), so --all-regions did not happen and only the Regions listed here were checked")
    if len(scope.problems) > len(scope.damaged_state) + (1 if scope.all_regions_failure else 0) or not phrases:
        phrases.append("the scope of the audit is in doubt (see SCOPE PROBLEMS)")
    return phrases


def result_line(
    results: list[CheckResult],
    scope: Scope,
    identity: Identity,
    ignore_storage_only: bool,
    after_teardown: str | None = None,
) -> str:
    """The one line to read. Order: a limit asked for by flag, in capitals; then the verdict; then where it looked.

    When the verdict is good, what this audit could not know (a kit folder with no state file) comes
    before the good news, so that nobody stops reading at "nothing".
    """
    found, found_own = kit_rows_found(after_teardown, results)
    exit_code, _label, reasons = verdict(results, ignore_storage_only, scope.problems, found)
    counts = summarise(results)
    audited = audited_line(scope, identity)
    limited = limited_check_phrases(results, scope, ignore_storage_only)
    head = "RESULT: " + (f"LIMITED CHECK: {'; '.join(limited)}. " if limited else "")
    sentences = state_sentences(scope)
    state = "".join(f"{sentence}. " for sentence in sentences)
    tail = ""
    if scope.all_regions_listed:
        tail = f" --all-regions: the Regions above include every Region that AWS reports as enabled for this account ({len(scope.enabled_regions)})."
        if scope.not_enabled_regions:
            tail += f" {len(scope.not_enabled_regions)} Region(s) that are not enabled were not audited (see the NOTE above)."
    elif sentences and not scope.all_regions_requested:
        tail = f" {ALL_REGIONS_OFFER}"
    if exit_code == EXIT_CLEAN:
        if after_teardown:
            unseen = sum(1 for resource in KIT_COVERAGE[after_teardown] if not resource.check_id)
            state += (
                f"{unseen} of kit {after_teardown.upper()}'s resource types cannot be checked by this audit (the rows marked "
                f"'{COVERAGE_NOT_CHECKABLE}' above), so this screen does not replace that kit's own clean check (python "
                f"99_verify_clean.py in {KIT_FOLDERS[after_teardown]}). "
            )
        intro = "In what was checked, " if (limited or state) else ""
        return f"{head}{state}{intro}nothing that bills while idle was found, and every check ran (exit {EXIT_CLEAN}). {audited}{tail}"
    phrases = {
        REASON_BILLS: ["something bills while idle"],
        REASON_STORAGE: ["storage is still being billed"],
        REASON_COULD_NOT_CHECK: ["some checks could not run, so this is NOT a clean result"],
        REASON_SCOPE: scope_reason_phrases(scope),
        REASON_SKIPPED: [f"{counts[STATUS_SKIPPED]} check(s) were skipped and say nothing"],
        REASON_NOTHING_RAN: ["no check completed"],
    }
    if after_teardown:
        letter, folder = after_teardown.upper(), KIT_FOLDERS[after_teardown]
        text = f"{found} of kit {letter}'s resource type(s) were FOUND (the rows marked [FOUND] above)"
        if found_own:
            text += f", so kit {letter}'s own clean check (python 99_verify_clean.py in {folder}, for the same Region and prefix) would say NOT CLEAN"
        if found - found_own:
            text += f"; {found - found_own} of them is a kind of thing that kit {letter}'s own clean check does not count as a leftover"
        phrases[REASON_KIT_FOUND] = [text]
    said = "; ".join(phrase for reason in reasons for phrase in phrases[reason])
    return f"{head}NOT CLEAN (exit {EXIT_NOT_CLEAN}): {said}. {state}{audited}{tail}"


def summary_lines(results: list[CheckResult]) -> list[str]:
    counts = summarise(results)
    return [
        "SUMMARY",
        f"    bills while idle, yes:        {counts[BILLS_YES]}",
        f"    bills while idle, unknown:    {counts[BILLS_UNKNOWN]}  (treated as yes)",
        f"    storage only:                 {counts[BILLS_STORAGE]}",
        f"    no idle charge:               {counts[BILLS_NO]}",
        f"    checks that could not run:    {counts[STATUS_COULD_NOT_CHECK]}  (never counted as clean)",
        f"    checks skipped by you:        {counts[STATUS_SKIPPED]}  (never counted as clean)",
        f"    checks completed:             {counts['checks_completed']}",
    ]


CLOSING_LINE = "This audit covers the listed service families in the listed Regions only. It is not proof that the account is empty."


def closing_lines(results: list[CheckResult], scope: Scope, budget_info: BudgetInfo | None) -> list[str]:
    """What every screen ends with, before the SUMMARY: the notes and the informational budget row."""
    lines: list[str] = []
    for block in (session_note_lines(results), region_note_lines(scope), per_region_lines(results), budget_lines(budget_info)):
        if block:
            lines.append("")
            lines.extend(block)
    return lines


def render_text(
    results: list[CheckResult],
    scope: Scope,
    identity: Identity,
    ignore_storage_only: bool = False,
    budget_info: BudgetInfo | None = None,
) -> str:
    lines: list[str] = []
    out = lines.append
    out("whats_running.py: read-only audit. Nothing was created, changed or deleted.")
    lines.extend(scope_lines(scope, identity))
    out("Kit prefixes mark names with [kit prefix] and select ECR repositories and extra log groups and buckets. Everything else is listed whatever its name.")
    region = None
    classic_hits: list[Item] = []
    for r in results:
        if r.family == "account":
            out("")
            if r.status == STATUS_COULD_NOT_CHECK:
                out(f"[{r.family}] {r.title}: COULD NOT CHECK: {r.reason}")
            else:
                out(f"[{r.family}] {r.title}: {identity.label()}")
            continue
        if r.region != region:
            region = r.region
            out("")
            out(f"=== Region {region} ===")
        if r.status == STATUS_SKIPPED:
            out(f"[{r.family}] {r.title}: SKIPPED, not checked ({r.reason})")
            continue
        if r.status == STATUS_COULD_NOT_CHECK:
            out(f"[{r.family}] {r.title}: COULD NOT CHECK: {r.reason}")
            if r.items:
                out(f"    (listing is incomplete; {len(r.items)} item(s) seen before it failed)")
        elif not r.items:
            out(f"[{r.family}] {r.title}: none found")
        else:
            out(f"[{r.family}] {r.title}: {len(r.items)} found")
        for item in r.items:
            mark = " [kit prefix]" if item.carries_prefix else ""
            out(f"    BILLS WHILE IDLE: {item.bills_idle.upper()} | {item.kind}: {item.name}{mark}")
            out(f"        created: {item.created} | state: {item.state}")
            out(f"        why: {item.why}")
            out(f"        source: {item.source}")
            if item.kind == "OpenSearch Serverless collection" and item.bills_idle == BILLS_YES:
                classic_hits.append(item)

    if classic_hits:
        out("")
        lines.extend(aoss_warning_lines(classic_hits))
    lines.extend(closing_lines(results, scope, budget_info))
    out("")
    lines.extend(summary_lines(results))
    out(result_line(results, scope, identity, ignore_storage_only))
    out(CLOSING_LINE)
    return "\n".join(lines)


def aoss_warning_lines(classic_hits: list[Item]) -> list[str]:
    lines = ["!" * 78, "!!! WARNING: OpenSearch Serverless collection(s) that bill with zero queries:"]
    lines += [f"!!!   {item.name}" for item in classic_hits]
    lines.append(f"!!! '{AOSS_MIN_OCU_QUOTE}'")
    lines.append(
        f"!!! At ${AOSS_OCU_HOUR_USD:.2f} per OCU per hour (US East (N. Virginia), US East (Ohio), US West (Oregon); "
        f"higher elsewhere) the minimum is ${aoss_min_hourly_usd('ENABLED'):.2f} per hour, "
        f"${aoss_min_hourly_usd('ENABLED') * 24:.2f} per day, or ${aoss_min_hourly_usd('DISABLED'):.2f} per hour "
        "without standby replicas."
    )
    lines.append(f"!!! Source: {src(SRC_AOSS_PRICING)}. Deleting a knowledge base does NOT delete its collection.")
    lines.append("!" * 78)
    return lines


def render_after_teardown(
    kit: str,
    results: list[CheckResult],
    scope: Scope,
    identity: Identity,
    ignore_storage_only: bool = False,
    budget_info: BudgetInfo | None = None,
) -> str:
    """One screen: every resource type the kit can create, and what this audit saw of each."""
    rows = coverage_rows(kit, results)
    lines = [
        "whats_running.py --after-teardown: read-only. Nothing was created, changed or deleted.",
        f"KIT {kit.upper()} ({KIT_FOLDERS[kit]}): every resource type this kit can create, and what this audit saw of it.",
        audited_line(scope, identity),
    ]
    lines += [f"NO RECORD OF WHERE: {sentence}." for sentence in state_sentences(scope)]
    if scope.problems:
        lines.append("SCOPE PROBLEMS (each one makes the result NOT CLEAN)")
        lines += [f"    - {problem}." for problem in scope.problems]
    identity_result = next((r for r in results if r.family == "account"), None)
    if identity_result is not None and identity_result.status == STATUS_COULD_NOT_CHECK:
        lines.append(f"ACCOUNT COULD NOT BE NAMED: {identity_result.reason}")
    lines.append("")
    width = max(len(COVERAGE_NOT_CHECKABLE), len(COVERAGE_NONE)) + 2
    for row in rows:
        status = row["status"].upper() if row["status"] in (COVERAGE_FOUND, COVERAGE_COULD_NOT) else row["status"]
        lines.append(f"  {('[' + status + ']').ljust(width)} {row['resource']}")
        for item in row["items"]:
            lines.append(f"      {item['region']}: {item['name']} | bills while idle: {item['bills_idle']} | {item['state']}")
        for problem in row["problems"]:
            lines.append(f"      could not check in {problem}")
        if row["status"] == COVERAGE_NOT_CHECKABLE:
            lines.append(f"      look in: {row['where_to_look']}")
        if row["note"]:
            lines.append(f"      note: {row['note']}")
    tally = {status: sum(1 for row in rows if row["status"] == status) for status in (COVERAGE_NONE, COVERAGE_FOUND, COVERAGE_COULD_NOT, COVERAGE_NOT_CHECKABLE)}
    lines.append("")
    lines.append(
        f"COVERAGE for kit {kit.upper()}: {len(rows)} resource types. {COVERAGE_NONE}: {tally[COVERAGE_NONE]}; "
        f"{COVERAGE_FOUND}: {tally[COVERAGE_FOUND]}; {COVERAGE_COULD_NOT}: {tally[COVERAGE_COULD_NOT]}; "
        f"{COVERAGE_NOT_CHECKABLE}: {tally[COVERAGE_NOT_CHECKABLE]}."
    )
    if tally[COVERAGE_FOUND]:
        lines.append(
            f"A row marked [FOUND] makes this screen NOT CLEAN (exit {EXIT_NOT_CLEAN}) whatever the thing costs while idle: it is "
            f"something kit {kit.upper()} made and its teardown should have removed."
        )
    not_run = [r for r in results if r.status == STATUS_COULD_NOT_CHECK and r.family != "account"]
    skipped_families = list(dict.fromkeys(r.family for r in results if r.status == STATUS_SKIPPED))
    if not_run or skipped_families:
        lines.append("NOT CHECKED anywhere in this audit, this kit's rows or not (each makes the result NOT CLEAN):")
        lines += [f"    {r.region} [{r.family}] {r.title}: COULD NOT CHECK: {r.reason}" for r in not_run]
        if skipped_families:
            lines.append(f"    skipped at your request (--skip), in every Region: {', '.join(skipped_families)}")
    outside = items_outside_kit(kit, results)
    lines.append(
        f"Everything else the audit listed in these Regions (not this kit's by name): {sum(outside.values())} item(s): "
        f"bills yes {outside[BILLS_YES]}, unknown {outside[BILLS_UNKNOWN]}, storage only {outside[BILLS_STORAGE]}, no idle charge {outside[BILLS_NO]}. "
        "The SUMMARY and RESULT below are for the WHOLE audit, all kits and all names. Run without --after-teardown for the full listing."
    )
    classic_hits = [i for r in results for i in r.items if i.kind == "OpenSearch Serverless collection" and i.bills_idle == BILLS_YES]
    if classic_hits:
        lines.extend(aoss_warning_lines(classic_hits))
    lines.extend(closing_lines(results, scope, budget_info))
    lines.append("")
    lines.extend(summary_lines(results))
    lines.append(result_line(results, scope, identity, ignore_storage_only, after_teardown=kit))
    lines.append(CLOSING_LINE)
    return "\n".join(lines)


def render_json(
    results: list[CheckResult],
    scope: Scope,
    identity: Identity,
    ignore_storage_only: bool = False,
    after_teardown: str | None = None,
    budget_info: BudgetInfo | None = None,
) -> str:
    found, found_own = kit_rows_found(after_teardown, results)
    exit_code, label, reasons = verdict(results, ignore_storage_only, scope.problems, found)
    skipped = [{"check_id": r.check_id, "region": r.region} for r in results if r.status == STATUS_SKIPPED]
    doc: dict[str, Any] = {
        "tool": "whats_running.py",
        "read_only": True,
        "docs_read": DOCS_READ,
        "boto3": _boto3_version(),
        "audited": {
            "account_last4": identity.last4,
            "regions": scope.region_list,
            "prefixes": scope.prefix_list,
            "region_sources": scope.regions,
            "prefix_sources": scope.prefixes,
            "kit_folders_read": scope.kits_read,
            "state_files_read": scope.state_files_read,
            "kits_without_state_file": scope.kits_without_state,
            "kits_whose_state_file_names_no_region": scope.kits_state_without_region,
            "no_kit_folder_found": scope.no_kit_folders,
            "only": scope.only,
        },
        "all_regions": {
            "requested": scope.all_regions_requested,
            "listed": scope.all_regions_listed,
            "failure": scope.all_regions_failure,
            "enabled": scope.enabled_regions,
            "not_enabled": scope.not_enabled_regions,
        },
        "limited_check": limited_check_phrases(results, scope, ignore_storage_only),
        "damaged_state_files": list(scope.damaged_state),
        "scope_problems": list(scope.problems),
        "scope_notes": list(scope.notes),
        "summary": summarise(results),
        "exit_code": exit_code,
        "verdict": label,
        "verdict_reasons": reasons,
        "result_line": result_line(results, scope, identity, ignore_storage_only, after_teardown),
        "skipped": {"count": len(skipped), "checks": skipped, "meaning": "a skipped check says nothing and makes exit 0 impossible"},
        "ignore_storage_only": ignore_storage_only,
        "agentcore_sessions_note": " ".join(session_note_lines(results)),
        "informational": {"budgets": (budget_info or BudgetInfo(STATUS_COULD_NOT_CHECK, "not read")).as_dict()},
        "checks": [r.as_dict() for r in results],
    }
    if after_teardown:
        doc["after_teardown"] = {
            "kit": after_teardown,
            "folder": KIT_FOLDERS[after_teardown],
            "rows": coverage_rows(after_teardown, results),
            "rows_found": found,
            "rows_found_that_the_kits_own_check_counts": found_own,
            "items_not_this_kits_by_name": items_outside_kit(after_teardown, results),
        }
    return json.dumps(doc, indent=2, sort_keys=True)


def render_plan(scope: Scope, skip: tuple[str, ...], after_teardown: str | None = None, all_regions: bool = False) -> str:
    lines = [
        "DRY RUN: no AWS call was made. This says nothing about what is running.",
        f"Exit code {EXIT_DRY_RUN}, not 0: a dry run checks nothing, so it must not look like a clean result to a script that reads exit codes.",
    ]
    lines.extend(scope_lines(scope, None))
    lines.append("=== once: read-only calls that would be made ===")
    lines.append("[account] sts.GetCallerIdentity()  [to name the account by its last four digits and compare it with the kits' state files]")
    if all_regions:
        lines.append(
            "[account] account.ListRegions(MaxResults=50)  [--all-regions: every Region whose status is not DISABLED is then "
            "audited with the calls below, in addition to the Regions listed above; needs the IAM action account:ListRegions]"
        )
    lines.append("[budget] budgets.DescribeBudgets(AccountId=<your account id>, MaxResults=100)  [information only; never changes the result]")
    lines.append(
        "[budget] budgets.ListTagsForResource(ResourceARN=<each budget that common/.state.json does not record, at most "
        f"{MAX_BUDGET_TAG_LOOKUPS}>)  [information only]"
    )
    for region in scope.region_list:
        lines.append(f"=== Region {region}: read-only calls that would be made ===")
        for check in CHECKS:
            if check.family in skip:
                lines.append(f"[{check.family}] {check.title}: SKIPPED (--skip); a real run with a skipped check cannot exit 0")
                continue
            for call in check.planned_calls:
                lines.append(f"[{check.family}] {call}")
    if all_regions:
        lines.append("=== every other Region that account.ListRegions reports as enabled: the same calls as for the Regions above ===")
    if after_teardown:
        lines.append(f"=== --after-teardown {after_teardown}: resource types of {KIT_FOLDERS[after_teardown]} and how each would be covered ===")
        titles = {c.check_id: c.title for c in CHECKS}
        for resource in KIT_COVERAGE[after_teardown]:
            if resource.check_id:
                lines.append(f"  [would be checked] {resource.label}  (by: {titles[resource.check_id]})")
            else:
                lines.append(f"  [{COVERAGE_NOT_CHECKABLE}] {resource.label}")
                lines.append(f"      look in: {resource.where}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # keep exit code 2 free for "not clean"
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="whats_running.py",
        description=(
            "Read-only audit of what could still be billing in the kits' service families. Exit 0 clean, 2 not clean, "
            "3 dry run (nothing checked). "
            "By default the Regions and name prefixes to audit are read from the kit folders beside this one "
            "(config.env, config.example.env, and every file whose name starts with .state.json); the command line adds "
            "to them. A kit folder with no state file is named in the RESULT line, because the audit then cannot know "
            "where that kit was last deployed: use --all-regions."
        ),
    )
    p.add_argument("--region", action="append", default=[], metavar="REGION", help="also audit this Region (repeatable, or comma-separated). ADDS to the Regions found in the kit folders, the environment (AWS_REGION) and the default us-east-1")
    p.add_argument("--regions", action="append", default=[], metavar="R1,R2", help="same as --region with a comma-separated list. This is not an all-Regions scan.")
    p.add_argument("--prefix", action="append", default=[], metavar="PREFIX", help="also treat this as a kit name prefix (repeatable, or comma-separated). ADDS to the prefixes found in the kit folders, the environment (KIT_PREFIX) and the default kitdemo")
    p.add_argument("--only", action="store_true", help="audit ONLY the --region and --prefix values given here; the kit folders are not read (needs at least one of each). The RESULT line then starts with LIMITED CHECK")
    p.add_argument("--all-regions", action="store_true", help="also audit every Region that AWS reports as enabled for this account (one extra call, account:ListRegions, then the full set of checks in each Region: slow). Use it when a kit folder has no state file. If the Regions cannot be listed the result is NOT CLEAN")
    p.add_argument("--kits-dir", default=None, metavar="DIR", help="folder that holds the kit_* folders (default: the folder above this script)")
    p.add_argument("--after-teardown", choices=sorted(KIT_COVERAGE), type=str.lower, metavar="KIT", help="a, b or c: run the whole audit, then print one screen listing every resource type that kit can create and whether it was checked, found, could not be checked, or cannot be checked by this audit. Any row of that kit marked FOUND makes the exit code 2, whatever the thing costs while idle")
    p.add_argument("--skip", action="append", default=[], choices=FAMILIES, help="skip one service family (repeatable). A skipped check is printed as SKIPPED and makes exit 0 impossible.")
    p.add_argument("--ignore-storage-only", action="store_true", help="do not let storage-only items set exit code 2 (they are still listed). The RESULT line then starts with LIMITED CHECK")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("--dry-run", action="store_true", help="print the scope and the API calls that would be made, and make none (exit code 3: nothing was checked)")
    return p


def main(argv: list[str] | None = None, client_factory: Callable[[str, str], Any] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if any(not str(value).strip() for value in args.prefix):
        print("whats_running.py: error: a --prefix value must not be empty", file=sys.stderr)
        return EXIT_USAGE
    if args.only and args.all_regions:
        print("whats_running.py: error: --only audits nothing but what you name, and --all-regions adds every enabled Region: use one or the other", file=sys.stderr)
        return EXIT_USAGE
    try:
        scope = build_scope(args.region + args.regions, args.prefix, args.only, Path(args.kits_dir) if args.kits_dir else KITS_DIR)
    except UsageError as exc:
        print(f"whats_running.py: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    skip = tuple(dict.fromkeys(args.skip))

    if args.dry_run:
        print(render_plan(scope, skip, args.after_teardown, args.all_regions))
        return EXIT_DRY_RUN

    factory = client_factory or default_client_factory
    identity, identity_result = check_identity(factory, scope.region_list)
    first_region = scope.region_list[0]  # the two account-wide services below have one endpoint whatever the Region
    if args.all_regions:
        apply_all_regions(scope, factory)
    compare_accounts(scope, identity)
    results = [identity_result] + run_audit(scope.region_list, scope.prefix_list, factory, skip)
    budget_info = check_budgets(factory, first_region, identity)  # information only; not part of the verdict
    exit_code = decide_exit(results, args.ignore_storage_only, scope.problems, kit_rows_found(args.after_teardown, results)[0])
    if args.json:
        print(render_json(results, scope, identity, args.ignore_storage_only, args.after_teardown, budget_info))
    elif args.after_teardown:
        print(render_after_teardown(args.after_teardown, results, scope, identity, args.ignore_storage_only, budget_info))
    else:
        print(render_text(results, scope, identity, args.ignore_storage_only, budget_info))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
