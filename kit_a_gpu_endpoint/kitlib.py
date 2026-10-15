"""Shared helpers for kit A (one small open-weights model on one SageMaker AI GPU endpoint).

Nothing in this file has been run against AWS. It was written without an AWS
account. The offline tests in tests/ exercise it with botocore's Stubber, which
validates every request against the botocore 1.43.108 service model.

Every AWS API call in this kit goes through Aws.call(), so --dry-run can print
the call and make none.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

KIT_DIR = Path(__file__).resolve().parent
KIT_NAME = "kit_a_gpu_endpoint"
STATE_FILE = KIT_DIR / ".state.json"
RESULTS_DIR = KIT_DIR / "results"
DATE_READ = "2026-10-07"

PROJECT_TAG_KEY = "project"
PROJECT_TAG_VALUE = "aws-kits"
KIT_TAG_KEY = "kit"
KIT_TAG_VALUE = "kit-a-gpu-endpoint"
NAME_INFIX = "kita"
VARIANT_NAME = "AllTraffic"
# SageMaker writes an endpoint's container logs to the log group "/aws/sagemaker/Endpoints/[EndpointName]":
# https://docs.aws.amazon.com/sagemaker/latest/dg/logging-cloudwatch.html (read 2026-10-07).
LOG_GROUP_ROOT = "/aws/sagemaker/Endpoints/"
# Exit code of a --dry-run of 90_teardown.py and of 99_verify_clean.py. For those two scripts exit code 0
# means "nothing of this kit remains", and a dry run looked at nothing and deleted nothing, so it never exits 0.
EXIT_DRY_RUN = 3

# ---------------------------------------------------------------------------
# Facts read from primary sources on 2026-10-07. Do not edit from memory.
# ---------------------------------------------------------------------------

PRICE_REGION = "us-east-1"
PRICE_SOURCE = (
    "AWS Price List file for AmazonSageMaker, us-east-1 "
    "(https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonSageMaker/current/us-east-1/index.json), "
    "publicationDate 2026-10-06T23:47:07Z, row effective date 2026-10-01, read 2026-10-07"
)
QUOTA_SOURCE = (
    "AWS General Reference, Amazon SageMaker AI endpoints and quotas "
    "(https://docs.aws.amazon.com/general/latest/gr/sagemaker.html), read 2026-10-07"
)

# usd_per_hour: price list rows "USE1-Host:<type>", unit Hrs.
# quota_code and default_quota: the row "<type> for endpoint usage" on the quotas page.
# gpu and gpu_mem_gib: https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html (g6/g5 rows), read 2026-10-07.
INSTANCES: dict[str, dict[str, Any]] = {
    "ml.g6.xlarge": {
        "usd_per_hour": 1.1267, "quota_code": "L-D470D954", "default_quota": 0,
        "gpu": "1 x NVIDIA L4", "gpu_mem_gib": 22, "vcpu": 4, "ram_gib": 16,
    },
    "ml.g6.2xlarge": {
        "usd_per_hour": 1.222, "quota_code": "L-98BDE811", "default_quota": 0,
        "gpu": "1 x NVIDIA L4", "gpu_mem_gib": 22, "vcpu": 8, "ram_gib": 32,
    },
    "ml.g5.xlarge": {
        "usd_per_hour": 1.408, "quota_code": "L-1928E07B", "default_quota": 0,
        "gpu": "1 x NVIDIA A10G", "gpu_mem_gib": 22, "vcpu": 4, "ram_gib": 16,
    },
    "ml.g5.2xlarge": {
        "usd_per_hour": 1.515, "quota_code": "L-9614C779", "default_quota": 0,
        "gpu": "1 x NVIDIA A10G", "gpu_mem_gib": 22, "vcpu": 8, "ram_gib": 32,
    },
}

# Same price list file, same date. Small next to the instance-hour, listed so nothing is hidden.
OTHER_HOSTING_CHARGES = [
    "$0.14 per GB-Mo of Endpoint ML storage (USE1-Host:VolumeUsage.gp2)",
    "$0.016 per GB for Endpoint Data IN (USE1-Hst:Data-Bytes-In)",
    "$0.016 per GB for Endpoint Data OUT (USE1-Hst:Data-Bytes-Out)",
]

# Model facts for the default model, read 2026-10-07 from
# https://huggingface.co/api/models/Qwen/Qwen3-4B and https://huggingface.co/Qwen/Qwen3-4B/resolve/main/config.json
MODEL_FACTS: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-4B": {
        "licence": "apache-2.0",
        "gated": False,
        "parameters": 4_022_468_096,
        "bytes_per_parameter": 2,  # BF16
        "num_hidden_layers": 36,
        "hidden_size": 2560,
        "num_key_value_heads": 8,
        "head_dim": 128,
        "max_position_embeddings": 40960,
    }
}

SETTABLE_ENV_KEYS = (
    "SM_VLLM_MAX_NUM_SEQS",
    "SM_VLLM_MAX_MODEL_LEN",
    "SM_VLLM_GPU_MEMORY_UTILIZATION",
)

DEFAULTS: dict[str, str] = {
    "AWS_REGION": "us-east-1",
    "KIT_PREFIX": "kitdemo",
    "SAGEMAKER_EXECUTION_ROLE_NAME": "kitdemo-kita-sagemaker-execution",
    "INSTANCE_TYPE": "ml.g6.2xlarge",
    "HF_MODEL_ID": "Qwen/Qwen3-4B",
    "DLC_REGISTRY_ACCOUNT": "763104351884",
    "VLLM_IMAGE_TAG": "0.30.0-gpu-py312-cu130-ubuntu24.04-sagemaker",
    "INFERENCE_AMI_VERSION": "al2023-ami-sagemaker-inference-gpu-4-1",
    "MAX_MODEL_LEN": "8192",
    "MAX_NUM_SEQS": "4",
    "GPU_MEMORY_UTILIZATION": "",
    "STARTUP_HEALTH_CHECK_TIMEOUT_SECONDS": "900",
    "MAX_HOURS": "3",
    "CHAT_TEMPLATE_KWARGS_JSON": '{"enable_thinking": false}',
}

_PREFIX_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,18}[a-z0-9])?$")
_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d{1,2}$")
# A log group name (after LOG_GROUP_ROOT) that this kit's naming rule produces under ANY prefix.
_KIT_LOG_TAIL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,18}[a-z0-9])?-" + NAME_INFIX + r"-")


class KitError(Exception):
    """A problem the owner must fix. Scripts print it and exit non-zero."""


class StateFileError(KitError):
    """The state file exists but cannot be used: unreadable, not JSON, or not a state object.

    No script deletes, renames or overwrites such a file. Every script but two stops on it. 90_teardown.py
    goes on only when the owner names the place with --region and --prefix; 99_verify_clean.py goes on,
    read-only, and reports INCOMPLETE for as long as the file is there.
    """

    def __init__(self, path: Path, reason: str):
        self.path, self.reason = path, reason
        self.hints = salvage_hints(path)
        super().__init__(f"{path.name} exists but cannot be used: {reason}. {damaged_state_advice(path.name, self.hints)}")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_env_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines. Blank lines and lines starting with # are ignored."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" and not value.startswith("{"):
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Config:
    region: str
    prefix: str
    role_name: str
    instance_type: str
    hf_model_id: str
    dlc_registry_account: str
    image_tag: str
    inference_ami_version: str
    max_model_len: int
    max_num_seqs: int
    gpu_memory_utilization: str
    health_timeout_s: int
    max_hours: float
    chat_template_kwargs: dict[str, Any] | None = field(default=None)

    @property
    def image_uri(self) -> str:
        # URI pattern "<account>.dkr.ecr.<region>.amazonaws.com/<repository>:<tag>":
        # https://aws.github.io/deep-learning-containers/reference/available_images/ (read 2026-10-07).
        # The registry account is AWS's public Deep Learning Containers registry, not the owner's account.
        return f"{self.dlc_registry_account}.dkr.ecr.{self.region}.amazonaws.com/vllm:{self.image_tag}"

    @property
    def name_stem(self) -> str:
        return f"{self.prefix}-{NAME_INFIX}-"

    @property
    def endpoint_name(self) -> str:
        # Fixed name on purpose: a second deploy collides instead of quietly billing twice.
        return f"{self.name_stem}endpoint"

    def model_name(self, revision: str) -> str:
        return f"{self.name_stem}model-{revision}"

    def endpoint_config_name(self, revision: str) -> str:
        return f"{self.name_stem}config-{revision}"

    @property
    def log_group_name(self) -> str:
        # https://docs.aws.amazon.com/sagemaker/latest/dg/logging-cloudwatch.html (read 2026-10-07):
        # log group "/aws/sagemaker/Endpoints/[EndpointName]".
        return f"/aws/sagemaker/Endpoints/{self.endpoint_name}"

    def tags(self) -> list[dict[str, str]]:
        return [
            {"Key": PROJECT_TAG_KEY, "Value": PROJECT_TAG_VALUE},
            {"Key": KIT_TAG_KEY, "Value": KIT_TAG_VALUE},
        ]

    def container_env(self) -> dict[str, str]:
        """Environment for the AWS vLLM Deep Learning Container.

        Source: https://aws.github.io/deep-learning-containers/vllm/configuration/ and
        .../vllm/deployment/sagemaker/ (repository aws/deep-learning-containers, docs/vllm/, commit e72722a,
        read 2026-10-07): "Any SM_VLLM_* environment variable is converted to a --<name> vLLM server argument".
        """
        env = {
            "SM_VLLM_MODEL": self.hf_model_id,
            "SM_VLLM_MAX_MODEL_LEN": str(self.max_model_len),
            "SM_VLLM_MAX_NUM_SEQS": str(self.max_num_seqs),
            "SM_VLLM_TENSOR_PARALLEL_SIZE": "1",
        }
        if self.gpu_memory_utilization:
            env["SM_VLLM_GPU_MEMORY_UTILIZATION"] = self.gpu_memory_utilization
        return env


def load_config(environ: dict[str, str] | None = None, env_file: Path | None = None) -> Config:
    """Environment variables win over config.env, which wins over the defaults."""
    environ = dict(os.environ if environ is None else environ)
    file_values = load_env_file(env_file if env_file is not None else KIT_DIR / "config.env")
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in file_values.items() if k in DEFAULTS})
    merged.update({k: v for k, v in environ.items() if k in DEFAULTS})

    prefix = merged["KIT_PREFIX"]
    if not _PREFIX_RE.match(prefix):
        raise KitError(
            f"KIT_PREFIX {prefix!r} is not usable. Use 1 to 20 lower-case letters, digits or hyphens, "
            "starting and ending with a letter or digit."
        )
    show_prefix(prefix)
    try:
        max_model_len = int(merged["MAX_MODEL_LEN"])
        max_num_seqs = int(merged["MAX_NUM_SEQS"])
        health_timeout = int(merged["STARTUP_HEALTH_CHECK_TIMEOUT_SECONDS"])
        max_hours = float(merged["MAX_HOURS"])
    except ValueError as exc:
        raise KitError(f"A numeric setting is not a number: {exc}") from exc
    if not 60 <= health_timeout <= 3600:
        # Valid range from https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ProductionVariant.html (read 2026-10-07).
        raise KitError("STARTUP_HEALTH_CHECK_TIMEOUT_SECONDS must be between 60 and 3600.")
    if max_hours <= 0 or max_hours > 12:
        raise KitError("MAX_HOURS must be greater than 0 and at most 12. This kit is for one sitting.")
    if max_model_len < 256 or max_num_seqs < 1:
        raise KitError("MAX_MODEL_LEN must be at least 256 and MAX_NUM_SEQS at least 1.")
    gpu_util = merged["GPU_MEMORY_UTILIZATION"].strip()
    if gpu_util:
        try:
            value = float(gpu_util)
        except ValueError as exc:
            raise KitError("GPU_MEMORY_UTILIZATION must be empty or a number such as 0.90.") from exc
        if not 0 < value <= 1:
            raise KitError("GPU_MEMORY_UTILIZATION must be greater than 0 and at most 1.")
    kwargs_raw = merged["CHAT_TEMPLATE_KWARGS_JSON"].strip()
    chat_template_kwargs = None
    if kwargs_raw:
        try:
            chat_template_kwargs = json.loads(kwargs_raw)
        except ValueError as exc:
            raise KitError(f"CHAT_TEMPLATE_KWARGS_JSON is not valid JSON: {exc}") from exc
        if not isinstance(chat_template_kwargs, dict):
            raise KitError("CHAT_TEMPLATE_KWARGS_JSON must be a JSON object or empty.")
    return Config(
        region=merged["AWS_REGION"],
        prefix=prefix,
        role_name=merged["SAGEMAKER_EXECUTION_ROLE_NAME"],
        instance_type=merged["INSTANCE_TYPE"],
        hf_model_id=merged["HF_MODEL_ID"],
        dlc_registry_account=merged["DLC_REGISTRY_ACCOUNT"],
        image_tag=merged["VLLM_IMAGE_TAG"],
        inference_ami_version=merged["INFERENCE_AMI_VERSION"].strip(),
        max_model_len=max_model_len,
        max_num_seqs=max_num_seqs,
        gpu_memory_utilization=gpu_util,
        health_timeout_s=health_timeout,
        max_hours=max_hours,
        chat_template_kwargs=chat_template_kwargs,
    )


def add_place_arguments(parser: argparse.ArgumentParser) -> None:
    """--region and --prefix for 90_teardown.py and 99_verify_clean.py: the place, named on the command line."""
    parser.add_argument("--region", default=None, metavar="REGION",
                        help="Act in this Region instead of AWS_REGION or config.env. With --prefix, it is also the "
                             "only way to tear down when .state.json is damaged.")
    parser.add_argument("--prefix", default=None, metavar="PREFIX",
                        help="Use this name prefix instead of KIT_PREFIX or config.env.")


def config_for_place(cfg: Config, region: str | None, prefix: str | None) -> Config:
    """cfg with the Region and prefix given on the command line, when they were given."""
    if region is not None and not _REGION_RE.match(region):
        raise KitError(f"--region {region!r} does not look like an AWS Region name such as us-east-1.")
    if prefix is not None and not _PREFIX_RE.match(prefix):
        raise KitError(f"--prefix {prefix!r} is not usable as KIT_PREFIX. Use 1 to 20 lower-case letters, digits or "
                       "hyphens, starting and ending with a letter or digit.")
    if prefix is not None:
        show_prefix(prefix, only=False)
    return dataclasses.replace(cfg, region=region or cfg.region, prefix=prefix or cfg.prefix)


# ---------------------------------------------------------------------------
# AWS access, with dry-run
# ---------------------------------------------------------------------------

# AWS's public Deep Learning Containers registry account (DEFAULTS). Not the owner's, and it is part of the
# image address every deploy prints, so the output filter leaves it readable.
PUBLIC_REGISTRY_ACCOUNT = "763104351884"
_ACCOUNT_ID_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
# arn:aws:iam::<account>:user/<name>   arn:aws:sts::<account>:assumed-role/<role>/<session name>
_CALLER_NAME_RE = re.compile(r"(:(?:user|federated-user)/|:assumed-role/[^/\s\"']+/)[^\s\"',;)]+")
# The KIT_PREFIX in use (load_config, config_for_place). Twelve digits inside it are part of a name the owner
# chose, a timestamp for example, and are printed as they are, so that a printed name or command still works.
# A prefix of digits only is not kept: it cannot be told apart from an account id. Round 5, finding F9.
_PREFIXES_SHOWN: list[str] = []
# Account ids read from GetCallerIdentity in this process: masked everywhere, inside a prefix too.
_ACCOUNTS_READ: set[str] = set()


def show_prefix(prefix: str, only: bool = True) -> None:
    """Let redact() print 12 digits that stand inside this prefix. only=True forgets prefixes set before."""
    if only:
        _PREFIXES_SHOWN.clear()
    if prefix and not prefix.isdigit():
        _PREFIXES_SHOWN.append(prefix)


def redact(text: Any) -> str:
    """Text that is safe to show: no full account id and no user or session name of a caller ARN.

    A 12-digit number is cut to its last four digits, except AWS's public registry account and digits that
    stand inside the KIT_PREFIX in use (show_prefix) and are not the account of these credentials. AWS error
    text is not under this kit's control: an AccessDenied message names the caller, for example
    "User: arn:aws:iam::<account id>:user/<name> is not authorized".
    """
    cleaned = _CALLER_NAME_RE.sub(lambda m: m.group(1) + "[name hidden]", str(text))
    shown = [(m.start(), m.end()) for prefix in _PREFIXES_SHOWN for m in re.finditer(re.escape(prefix), cleaned)]

    def mask(match: re.Match[str]) -> str:
        digits = match.group(0)
        if digits == PUBLIC_REGISTRY_ACCOUNT:
            return digits
        if digits not in _ACCOUNTS_READ and any(start <= match.start() and match.end() <= end for start, end in shown):
            return digits
        return f"[account ending {digits[-4:]}]"

    return _ACCOUNT_ID_RE.sub(mask, cleaned)


class _RedactingStream:
    """stdout or stderr with redact() applied to everything written. guarded() installs it for a script run."""

    def __init__(self, stream: Any):
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(redact(text))
        return len(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


# Create and delete calls this process has sent that AWS carried out or may have carried out, in order.
# Aws.call() fills it; guarded() empties it at the start of a script and reads it when the script stops.
_CHANGES_SENT: list[str] = []
# The sign-in and configuration errors that guarded() names.
CREDENTIAL_ERRORS = ("NoCredentialsError", "PartialCredentialsError", "ProfileNotFound", "NoRegionError",
                     "TokenRetrievalError", "SSOTokenLoadError", "UnauthorizedSSOTokenError")
# Errors botocore raises only before the first try leaves this machine: no credentials at all (the client's
# credentials are fixed when it is built), an unknown profile or no Region (both raised while the client is
# built), and a request it refused to build. The other sign-in errors are NOT here: botocore 1.43.108 signs
# every retry again (endpoint.py: "Create a new request when retried (including a new signature)"), and a
# refresh that fails then is raised to the caller (credentials.py, _protected_refresh), after an earlier try
# may have been carried out. Round 5, finding F1.
NOT_SENT_ERRORS = ("NoCredentialsError", "ProfileNotFound", "NoRegionError", "ParamValidationError")


def sent_changes() -> list[str]:
    return _CHANGES_SENT


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class Aws:
    """One place where AWS calls happen.

    dry_run=True: call() prints the call and returns None. No boto3 client is created,
    so no credential lookup and no network traffic can happen.
    """

    def __init__(self, region: str, dry_run: bool, out: Callable[[str], None] = print,
                 clients: dict[str, Any] | None = None, client_config: dict[str, Any] | None = None):
        self.region = region
        self.dry_run = dry_run
        self.out = out
        self._clients: dict[str, Any] = dict(clients or {})
        self._client_config = client_config or {}
        self.calls_made = 0
        self.calls_printed = 0
        self._sent = sent_changes()

    def for_region(self, region: str) -> "Aws":
        """The same kind of access (dry run or not, same output) in another Region, same credentials.

        Used only by 99_verify_clean.py, which also looks in every Region the state file names.
        """
        if region == self.region:
            return self
        return Aws(region, self.dry_run, out=self.out, client_config=self._client_config)

    def client(self, service: str) -> Any:
        if self.dry_run:
            raise KitError("Internal error: a client was requested during --dry-run.")
        if service not in self._clients:
            import boto3  # imported late so --help and --dry-run work without boto3 credentials
            from botocore.config import Config as BotoConfig

            options = {"retries": {"mode": "standard", "total_max_attempts": 3},
                       "user_agent_extra": "aws-kits/kit-a"}
            options.update(self._client_config.get(service, {}))
            self._clients[service] = boto3.client(service, region_name=self.region, config=BotoConfig(**options))
        return self._clients[service]

    def call(self, service: str, operation: str, **params: Any) -> Any:
        if self.dry_run:
            self.calls_printed += 1
            rendered = json.dumps(_jsonable(params), indent=2, sort_keys=True)
            self.out(f"DRY-RUN would call {service}.{operation} with:\n{rendered}")
            return None
        self.calls_made += 1
        method = getattr(self.client(service), operation)
        if not operation.startswith(("create_", "delete_")):
            return method(**params)
        # A create or a delete: guarded() must know, when the script stops later, that this run has already
        # changed something (or may have). Only a refusal on the first try, or an error raised before
        # anything was sent, leaves no mark. Ctrl-C during the call counts as no clear answer.
        name = "".join(part.capitalize() for part in operation.split("_"))
        try:
            result = method(**params)
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - recorded, then raised unchanged
            if not definitely_rejected(exc) and type(exc).__name__ not in NOT_SENT_ERRORS:
                self._sent.append(f"{name} (no clear answer)")
            raise
        self._sent.append(name)
        return result


def _error_dict(exc: Exception) -> dict[str, Any]:
    """The "Error" part of a boto3 ClientError response, or {} for anything else.

    Other libraries also put a .response on their exceptions (the OpenAI SDK attaches an HTTP response
    object), so the attribute is only trusted when it is a dict.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return {}
    error = response.get("Error")
    return error if isinstance(error, dict) else {}


def error_code(exc: Exception) -> str:
    return str(_error_dict(exc).get("Code", ""))


def error_message(exc: Exception) -> str:
    """AWS's own error text, through redact(): an AccessDenied message names the caller's ARN."""
    return redact(str(_error_dict(exc).get("Message", "")) or str(exc))


def retry_attempts(exc: Exception) -> int:
    """How many times botocore sent the request AGAIN before this error came back (0 = it was sent once).

    botocore writes the number into ResponseMetadata.RetryAttempts of every answer, errors included
    (botocore 1.43.108, endpoint.py). Missing or not a number counts as 0.
    """
    response = getattr(exc, "response", None)
    attempts = (response.get("ResponseMetadata") or {}).get("RetryAttempts") if isinstance(response, dict) else None
    return attempts if isinstance(attempts, int) and attempts > 0 else 0


def definitely_rejected(exc: Exception) -> bool:
    """True when AWS answered the ONE request that was sent with a 4xx error, so the thing asked for was not done.

    A timeout, a dropped connection or a 5xx answer leaves the outcome unknown and returns False. So does a 4xx
    that came back after botocore had sent the request more than once: this kit's clients retry (Aws.client),
    and an earlier try whose answer was lost may have been carried out.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict) or not error_code(exc):
        return False
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return isinstance(status, int) and 400 <= status < 500 and retry_attempts(exc) == 0


def says_already_exists(exc: Exception) -> bool:
    """True when AWS answers a create call with "that name is taken".

    # UNVERIFIED: the wording. SageMaker is believed to answer a second CreateEndpoint with the same name
    # with ValidationException "Cannot create already existing endpoint ..."; no AWS doc page read on
    # 2026-10-07 gives the text. So the deploy step does not rely on it alone: before it takes an endpoint
    # out of the state file after ANY refusal, it asks ListEndpoints (create_stack).
    """
    code, message = error_code(exc), error_message(exc).lower()
    return bool(code) and ("already exist" in message or code in ("ResourceInUse", "ResourceInUseException",
                                                                  "ConflictException"))


def is_not_found(exc: Exception) -> bool:
    """True when SageMaker or CloudWatch Logs says the named resource does not exist.

    SageMaker answers a describe or delete on a missing endpoint, endpoint configuration or model
    with ValidationException and a message that starts "Could not find". botocore's own
    endpoint_deleted waiter (botocore 1.43.108, sagemaker waiters-2.json) also treats
    ValidationException as "deleted".
    # UNVERIFIED: the exact message text ("Could not find ...") is not written on an AWS doc page
    # read on 2026-10-07. If AWS words it differently, the delete and wait steps do not guess: they ask
    # the matching List call and treat the resource as gone only when it is no longer listed
    # (listed_by_name). Any other error stops the script with the raw message.
    """
    code = error_code(exc)
    message = error_message(exc).lower()
    if code == "ResourceNotFoundException" or code == "ResourceNotFound":
        return True
    if code == "ValidationException" and ("could not find" in message or "does not exist" in message):
        return True
    return False


# ---------------------------------------------------------------------------
# Time, money, state
# ---------------------------------------------------------------------------

def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def revision_from(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def price_for(instance_type: str, region: str, override: float | None = None) -> tuple[float, str]:
    """Return (USD per hour, where the number came from). Raises KitError when no price was read."""
    if override is not None:
        if override <= 0:
            raise KitError("--price-per-hour must be greater than 0.")
        return override, "typed by you with --price-per-hour; this kit did not read it"
    if region != PRICE_REGION:
        raise KitError(
            f"This kit only read prices for {PRICE_REGION}. For {region}, read the SageMaker AI price yourself "
            "(https://aws.amazon.com/sagemaker/ai/pricing/) and pass it with --price-per-hour."
        )
    if instance_type not in INSTANCES:
        raise KitError(
            f"No price was read for {instance_type}. Known: {', '.join(sorted(INSTANCES))}. "
            "Read the price yourself and pass it with --price-per-hour."
        )
    return float(INSTANCES[instance_type]["usd_per_hour"]), PRICE_SOURCE


def quota_code_for(instance_type: str) -> str | None:
    entry = INSTANCES.get(instance_type)
    return entry["quota_code"] if entry else None


def account_tail(account: str | None) -> str:
    """Last four digits only. No script prints more of an account id than this."""
    digits = str(account or "")
    return digits[-4:] if len(digits) >= 4 else "????"


def scope_text(region: str | None, account: str | None, prefix: str | None) -> str:
    return (f"Region {region or '(not recorded)'}, account ending {account_tail(account)}, "
            f"prefix {prefix or '(not recorded)'}")


def caller_account(aws: Aws) -> str | None:
    """The 12-digit id of the account the current credentials belong to. None in a dry run.

    The id is compared with the one in the state file and written there (a local, git-ignored file).
    It is never printed in full.
    """
    # GetCallerIdentity: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
    # "No permissions are required to perform this operation."
    identity = aws.call("sts", "get_caller_identity")
    if identity is None:  # dry run
        return None
    account = str(identity.get("Account", ""))
    _ACCOUNTS_READ.add(account)
    if not re.fullmatch(r"\d{12}", account):
        raise KitError("GetCallerIdentity did not return a 12-digit account id, so this kit cannot tell which "
                       "account you are signed in to. Check: aws sts get-caller-identity")
    return account


def empty_state(cfg: Config, account_id: str | None = None) -> dict[str, Any]:
    """A new state file. It records WHERE the deploy lives: Region, name prefix and account id."""
    return {"kit": KIT_NAME, "region": cfg.region, "prefix": cfg.prefix, "account_id": account_id,
            "resources": [], "deploy": None, "history": []}


_ARN_RE = re.compile(r"^arn:[^:]*:[^:]*:([a-z0-9-]*):(\d{12}):")


def has_live_record(state: dict[str, Any] | None) -> bool:
    """True when the state file says something of this kit exists right now."""
    return bool(state and (state.get("resources") or state.get("deploy")))


def recorded_scope(state: dict[str, Any]) -> dict[str, str | None]:
    """Region, prefix and account id the state file records for the current deploy.

    A value missing at the top level (a file written by an older copy of this kit) is read from the
    recorded resource ARNs when one is there. A value that cannot be found is None.
    """
    region, prefix, account = state.get("region"), state.get("prefix"), state.get("account_id")
    for resource in state.get("resources", []):
        match = _ARN_RE.match(str(resource.get("arn") or ""))
        if match:
            region = region or match.group(1) or None
            account = account or match.group(2)
    return {"region": region or None, "prefix": prefix or None, "account_id": account or None}


def require_state_matches(state: dict[str, Any] | None, cfg: Config, account_id: str | None,
                          state_name: str = ".state.json") -> None:
    """Stop when the state file records a deploy somewhere other than where this shell points.

    Compared: Region, name prefix and account id. account_id is None when no identity call was made (a
    dry run, or the first check in 70_change_one_setting.py before the billing flag), and then only
    Region and prefix are compared. With no live record there is nothing to compare. Raises KitError;
    the caller has made no change and no delete at that point.
    """
    if not has_live_record(state):
        return
    recorded = recorded_scope(state)
    differs: list[str] = []
    if recorded["region"] != cfg.region:
        differs.append(f"Region: the file records {recorded['region'] or 'none'}, this shell uses {cfg.region}")
    if recorded["prefix"] != cfg.prefix:
        differs.append(f"prefix: the file records {recorded['prefix'] or 'none'}, this shell uses {cfg.prefix}")
    if account_id is not None:
        if recorded["account_id"] is None:
            differs.append("account: the file records no account id, so this kit cannot tell whether the account "
                           f"ending {account_tail(account_id)} is the one you deployed in. If it is, add "
                           f'"account_id": "<its 12 digits>" at the top level of {state_name} and run this again')
        elif recorded["account_id"] != account_id:
            same_tail = account_tail(recorded["account_id"]) == account_tail(account_id)
            differs.append(f"account: the file records the account ending {account_tail(recorded['account_id'])}, "
                           f"you are signed in to the account ending {account_tail(account_id)}"
                           + (" (the last four digits match, the full ids do not)" if same_tail else ""))
    if not differs:
        # The top-level values agree. A recorded ARN says most directly where a resource lives, so each one
        # must agree as well (it can only differ in a file that was edited or merged by hand).
        for resource in state.get("resources", []):
            match = _ARN_RE.match(str(resource.get("arn") or ""))
            if match and (match.group(1) != cfg.region or (account_id is not None and match.group(2) != account_id)):
                differs.append(f"resource {resource.get('name')}: its recorded ARN is in Region {match.group(1)}, "
                               f"account ending {account_tail(match.group(2))}")
    if not differs:
        return
    raise KitError(
        f"{state_name} records a deploy in {scope_text(recorded['region'], recorded['account_id'], recorded['prefix'])}. "
        f"This shell points at {scope_text(cfg.region, account_id, cfg.prefix)}"
        f"{'' if account_id is not None else ' (account not compared: no identity call was made, as in a dry run)'}. "
        f"Mismatch: {'; '.join(differs)}. "
        "An exported AWS_REGION or KIT_PREFIX overrides config.env (check: echo $AWS_REGION $KIT_PREFIX), and the "
        "account comes from your credentials (check: echo $AWS_PROFILE; aws sts get-caller-identity). "
        "Nothing was changed, nothing was deleted and the state file was not rewritten. "
        "Put the recorded values back and run this script again.")


def stamp_state(state: dict[str, Any], cfg: Config, account_id: str | None) -> None:
    """Point a state file with no live record at the place the next deploy goes.

    Finished runs in the history keep the Region, prefix and account they ran in; an entry written
    by an older copy of this kit, which has none of its own, is given the old top-level values first.
    """
    for finished in state.get("history", []):
        finished.setdefault("region", state.get("region"))
        finished.setdefault("prefix", state.get("prefix"))
        finished.setdefault("account_id", state.get("account_id"))
    state["region"], state["prefix"], state["account_id"] = cfg.region, cfg.prefix, account_id


def named_scopes(state: dict[str, Any] | None) -> list[dict[str, str | None]]:
    """Every (Region, prefix, account) the state file or its history names, without duplicates.

    99_verify_clean.py uses it: a place named here and not checked makes its verdict INCOMPLETE.
    """
    if not state:
        return []
    found: list[dict[str, str | None]] = []

    def add(region: Any, prefix: Any, account: Any) -> None:
        scope = {"region": region or None, "prefix": prefix or None, "account_id": account or None}
        if any(scope.values()) and scope not in found:
            found.append(scope)

    top = recorded_scope(state)
    add(top["region"], top["prefix"], top["account_id"])
    deploy = state.get("deploy") or {}
    if deploy:
        add(deploy.get("region") or top["region"], deploy.get("prefix") or top["prefix"],
            deploy.get("account_id") or top["account_id"])
    for finished in state.get("history", []):
        add(finished.get("region") or top["region"], finished.get("prefix") or top["prefix"],
            finished.get("account_id") or top["account_id"])
    for resource in state.get("resources", []):
        match = _ARN_RE.match(str(resource.get("arn") or ""))
        if match:
            add(match.group(1) or top["region"], top["prefix"], match.group(2))
    return found


def salvage_hints(path: Path) -> dict[str, list[str]]:
    """Region names, prefixes and account endings still legible in a damaged state file. Hints, not proof.

    A file cut short usually still holds the Region in the container image URI, in an ARN or in a
    "region" key. Never raises; an unreadable or empty file gives empty lists.
    """
    hints: dict[str, list[str]] = {"regions": [], "prefixes": [], "account_tails": []}
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return hints

    def add(key: str, value: str) -> None:
        if value and value not in hints[key]:
            hints[key].append(value)

    for match in re.finditer(r'"region"\s*:\s*"([a-z0-9-]+)"', text):
        add("regions", match.group(1))
    for match in re.finditer(r"arn:aws[a-z-]*:[a-z0-9-]+:([a-z0-9-]+):(\d{12}):", text):
        add("regions", match.group(1))
        add("account_tails", match.group(2)[-4:])
    for match in re.finditer(r"\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com", text):
        add("regions", match.group(1))
    for match in re.finditer(r'"prefix"\s*:\s*"([a-z0-9-]+)"', text):
        add("prefixes", match.group(1))
    for match in re.finditer(r'"account_id"\s*:\s*"(\d{12})"', text):
        add("account_tails", match.group(1)[-4:])
    hints["regions"] = [r for r in hints["regions"] if _REGION_RE.match(r)]
    hints["prefixes"] = [p for p in hints["prefixes"] if _PREFIX_RE.match(p)]
    return hints


def damaged_state_advice(state_name: str, hints: dict[str, list[str]]) -> str:
    """What the owner does about a state file that cannot be used. One wording, used by every script."""
    hint = ""
    if hints.get("regions") or hints.get("prefixes"):
        parts = []
        if hints.get("regions"):
            parts.append(f"Region {', '.join(hints['regions'])}")
        if hints.get("prefixes"):
            parts.append(f"prefix {', '.join(hints['prefixes'])}")
        if hints.get("account_tails"):
            parts.append(f"account ending {', '.join(hints['account_tails'])}")
        hint = f"     A hint, not proof: what is left of the file still mentions {'; '.join(parts)}.\n"
    return (
        "No script deletes, renames or overwrites that file, and nothing was changed or deleted in AWS just now.\n"
        "  If an endpoint exists it is still billing. Do this:\n"
        "  1. Tear down, naming the place yourself (both flags are needed; an exported AWS_REGION does not count):\n"
        "       python 90_teardown.py --region <the Region you deployed in> --prefix <your KIT_PREFIX>\n"
        f"{hint}"
        "     Region not known? It is in RESULTS_TEMPLATE.md if you filled that in at deploy time, and\n"
        "     python ../common/whats_running.py looks across the kits.\n"
        "  2. Check: python 99_verify_clean.py --region <same> --prefix <same>\n"
        "     It stays INCOMPLETE while the damaged file is in this folder.\n"
        f"  3. When it lists nothing, move {state_name} out of this folder by hand and run step 2 once more.\n"
        "  README section 5, \"If the state file is lost or damaged\".")


def _state_shape_problem(state: Any) -> str:
    """Why a parsed JSON value is not a state file of this kit, or '' when it is one."""
    if not isinstance(state, dict):
        return "it is valid JSON but not a state object"
    resources = state.get("resources")
    if not isinstance(resources, list) or not all(isinstance(r, dict) for r in resources):
        return "it has no usable list of resources"
    if state.get("deploy") is not None and not isinstance(state["deploy"], dict):
        return "its deploy record is not an object"
    history = state.get("history", [])
    if not isinstance(history, list) or not all(isinstance(h, dict) for h in history):
        return "its history is not a list of finished runs"
    return ""


def load_state(path: Path = STATE_FILE) -> dict[str, Any] | None:
    """The state file as a dict, None when there is no file, StateFileError when it cannot be used."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise StateFileError(path, f"it could not be read ({type(exc).__name__}: {exc})") from exc
    try:
        state = json.loads(text)
    except ValueError as exc:
        raise StateFileError(path, f"it is not valid JSON ({exc})") from exc
    problem = _state_shape_problem(state)
    if problem:
        raise StateFileError(path, problem)
    return state


def save_state(state: dict[str, Any], path: Path = STATE_FILE) -> None:
    """Write the state file. Refuses to replace a file that is there and cannot be read as a state file."""
    if path.exists():
        try:
            load_state(path)
        except StateFileError as exc:
            raise KitError(f"Refusing to overwrite {path.name}: {exc.reason}. A damaged state file is evidence of "
                           "where a deploy went and is never replaced by a script. "
                           + damaged_state_advice(path.name, exc.hints)) from exc
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def state_resources(state: dict[str, Any] | None, kind: str) -> list[dict[str, Any]]:
    if not state:
        return []
    return [r for r in state.get("resources", []) if r.get("type") == kind]


def hours_between(start_iso: str, end: dt.datetime) -> float:
    return max(0.0, (end - parse_iso(start_iso)).total_seconds() / 3600.0)


def billing_lines(state: dict[str, Any] | None, now: dt.datetime) -> list[str]:
    """Lines every script prints while an endpoint is recorded in the state file."""
    deploy = (state or {}).get("deploy")
    if not deploy or not state_resources(state, "endpoint"):
        return []
    hours = hours_between(deploy["create_called_utc"], now)
    price = float(deploy["usd_per_hour"])
    name = state_resources(state, "endpoint")[0]["name"]
    if now < parse_iso(deploy["create_called_utc"]):
        # The clock of this machine was set back since the deploy. 0.00 h and $0.00 would read as "nothing spent".
        lines = [
            "=" * 72,
            f"BILLING: endpoint {name} is billing at ${price:.4f}/h. HOURS AND DOLLARS SO FAR ARE UNKNOWN: this "
            f"machine's clock says {iso(now)}, which is before the CreateEndpoint call on record "
            f"({deploy['create_called_utc']}). Check the clock; use your bill for the amount.",
        ]
    else:
        lines = [
            "=" * 72,
            f"BILLING: endpoint {name} has existed for {hours:.2f} h "
            f"at ${price:.4f}/h, about ${hours * price:.2f} so far (estimate, from this machine's clock).",
        ]
    earlier = deploy.get("replaced_in_this_sitting") or {}
    if earlier.get("runs"):
        head = f"Not in that figure: the {earlier['runs']} endpoint(s) this one replaced (70_change_one_setting.py), "
        if earlier.get("unknown"):
            # One of them was closed with this machine's clock behind its CreateEndpoint call: 0.00 h is no measurement.
            line = (head + "for an UNKNOWN time: this machine's clock went backwards while one of them existed. Hours "
                    "and dollars unknown; use your bill.")
        else:
            line = (head + f"{'at most ' if earlier.get('upper_bound') else ''}{float(earlier.get('hours', 0.0)):.2f} h, "
                    f"about ${float(earlier.get('estimated_usd', 0.0)):.2f}. Add the two for this sitting.")
        if earlier.get("already_exists"):
            line += (" One of them was answered \"already exists\": if it was there before that call, its real hours and "
                     "charge are higher.")
        lines.append(line)
    if deploy.get("create_answer") == "already exists":
        lines.append("CreateEndpoint was answered \"already exists\" for this endpoint. If it was there before that call, "
                     "it has been billing for longer than the figure above. Tear down: python 90_teardown.py")
    elif deploy.get("endpoint_create_confirmed") is False:
        lines.append("CreateEndpoint never answered, so this endpoint is UNCONFIRMED. Treat it as billing until "
                     "99_verify_clean.py shows whether it exists.")
    deadline = deploy.get("deadline_utc")
    if deadline:
        remaining = (parse_iso(deadline) - now).total_seconds() / 60.0
        if remaining >= 0:
            lines.append(f"You said you would tear down by {deadline} ({remaining:.0f} minutes from now).")
        else:
            lines.append(f"PAST YOUR DEADLINE of {deadline} by {-remaining:.0f} minutes. Tear down now.")
    lines.append("To stop the charge: python 90_teardown.py   then   python 99_verify_clean.py")
    lines.append("=" * 72)
    return lines


def past_deadline(state: dict[str, Any] | None, now: dt.datetime) -> bool:
    deploy = (state or {}).get("deploy")
    if not deploy or not deploy.get("deadline_utc") or not state_resources(state, "endpoint"):
        return False
    return now > parse_iso(deploy["deadline_utc"])


def close_run(state: dict[str, Any], ended: dt.datetime, end_time_known: bool = True) -> None:
    """Move the current deploy into history with its end time and forget its resources.

    Call it only after the endpoint was deleted, or confirmed absent, in the Region and account the
    state file records. end_time_known=False means the endpoint was already gone when this kit
    looked (deleted in the console, for example): the hours then run to "now" and are an upper bound.
    """
    deploy = state.get("deploy")
    if deploy:
        finished = dict(deploy)
        finished.setdefault("region", state.get("region"))
        finished.setdefault("prefix", state.get("prefix"))
        finished.setdefault("account_id", state.get("account_id"))
        finished["deleted_confirmed_utc"] = iso(ended)
        finished["hours"] = round(hours_between(deploy["create_called_utc"], ended), 4)
        finished["estimated_usd"] = round(finished["hours"] * float(deploy["usd_per_hour"]), 4)
        finished["hours_is_upper_bound"] = not end_time_known
        if ended < parse_iso(deploy["create_called_utc"]):
            finished["clock_went_back"] = True  # the end is before the start: the 0 hours above are not a measurement
        state.setdefault("history", []).append(finished)
    state["deploy"] = None
    state["resources"] = []


def run_totals(state: dict[str, Any] | None) -> tuple[float, float]:
    """(hours, estimated USD) summed over finished runs in the state file."""
    history = (state or {}).get("history", [])
    return (round(sum(float(h.get("hours", 0.0)) for h in history), 4),
            round(sum(float(h.get("estimated_usd", 0.0)) for h in history), 4))


def totals_are_upper_bound(state: dict[str, Any] | None) -> bool:
    """True when at least one finished run has an unknown end time (see close_run)."""
    return any(h.get("hours_is_upper_bound") for h in (state or {}).get("history", []))


def run_line(run: dict[str, Any]) -> str:
    """One finished run in words: its own start, end, hours and estimated charge."""
    start, end = run.get("create_called_utc", "?"), run.get("deleted_confirmed_utc", "?")
    hours, dollars = float(run.get("hours", 0.0)), float(run.get("estimated_usd", 0.0))
    if run.get("clock_went_back"):
        return (f"for an UNKNOWN time: this machine's clock went backwards (CreateEndpoint call {start}, confirmed gone "
                f"{end}, UTC, which is earlier). Hours and estimated charge unknown; use your bill")
    older = (" The CreateEndpoint call was answered \"already exists\": if the endpoint was there before that call, the "
             "real hours and charge are higher" if run.get("create_answer") == "already exists" else "")
    if run.get("hours_is_upper_bound"):
        return (f"AT MOST {hours:.2f} h (CreateEndpoint call {start}, found already gone at {end}, UTC; the real "
                f"end time is unknown, so the clock was run to the moment of that check). Estimated instance charge "
                f"at most ${dollars:.2f}{'.' + older if older else ''}")
    return (f"{hours:.2f} h by this machine's clock (CreateEndpoint call {start}, confirmed gone {end}, UTC). "
            f"Estimated instance charge ${dollars:.2f}{'.' + older if older else ''}")


def run_report_lines(state: dict[str, Any] | None, state_name: str = ".state.json",
                     closed_now: bool = True) -> list[str]:
    """What 90_teardown.py prints about hours and dollars.

    The run this teardown closed gets its own line ("This run:"). The total over every finished run in the
    state file comes after it, with the number of runs, the dates it covers and one line per run, so that a
    run from another day (or one with an unknown end) cannot pass for today's number.
    closed_now=False: this teardown closed no run, so only earlier runs are listed.
    """
    history = (state or {}).get("history", [])
    if not history:
        return []
    lines: list[str] = []
    if closed_now:
        lines.append(f"This run: the endpoint existed {run_line(history[-1])}.")
    else:
        lines.append(f"This teardown closed no run: {state_name} recorded no endpoint when it started.")
    if len(history) == 1:
        lines.append(f"It is the only finished run recorded in {state_name}."
                     if closed_now else f"The one finished run recorded in {state_name}: {run_line(history[0])}.")
    else:
        hours, dollars = run_totals(state)
        unknown = [h for h in history if h.get("hours_is_upper_bound")]
        first = min(str(h.get("create_called_utc", "?")) for h in history)
        last = max(str(h.get("deleted_confirmed_utc", "?")) for h in history)
        bound = "AT MOST " if unknown else ""
        tail = ""
        if unknown:
            starts = ", ".join(str(h.get("create_called_utc", "?")) for h in unknown)
            tail = (f" {len(unknown)} of the {len(history)} ended at an unknown time (started {starts}), which is "
                    "why the total is AT MOST.")
        lines.append(f"All {len(history)} finished runs recorded in {state_name}, first CreateEndpoint call {first}, "
                     f"last end {last} (UTC): {bound}{hours:.2f} h, estimated instance charge "
                     f"{'at most ' if unknown else ''}${dollars:.2f}.{tail} "
                     "That total can span several days; the runs are:")
        for number, run in enumerate(history, start=1):
            lines.append(f"  run {number}: {run_line(run)}.")
    lines.append("These are estimates. The number to record is the one on your bill in Billing and Cost Management. "
                 "Look the next day.")
    return lines


def read_quota(aws: Aws, instance_type: str) -> dict[str, Any]:
    """Read the applied Service Quotas value for "<instance type> for endpoint usage".

    Returns {"code", "value", "source"}; value is None in a dry run or when the type is unknown to this kit.
    """
    code = quota_code_for(instance_type)
    if code is None:
        return {"code": None, "value": None, "source": "no quota code recorded in this kit for this instance type"}
    try:
        # GetServiceQuota: https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_GetServiceQuota.html
        # (read 2026-10-07): "Retrieves the applied quota value ... For some quotas, only the default values are available."
        response = aws.call("service-quotas", "get_service_quota", ServiceCode="sagemaker", QuotaCode=code)
        source = "applied quota (GetServiceQuota)"
    except Exception as exc:  # noqa: BLE001 - classified just below
        if error_code(exc) != "NoSuchResourceException":
            raise
        # GetAWSDefaultServiceQuota: https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_GetAWSDefaultServiceQuota.html (read 2026-10-07)
        response = aws.call("service-quotas", "get_aws_default_service_quota", ServiceCode="sagemaker", QuotaCode=code)
        source = "AWS default (no applied value exists yet)"
    if response is None:  # dry run
        return {"code": code, "value": None, "source": "dry run"}
    return {"code": code, "value": float(response["Quota"]["Value"]), "source": source}


def quota_request_command(instance_type: str, region: str) -> str:
    """The AWS CLI command the owner can run to ask for a quota of 1. This kit never files it.

    RequestServiceQuotaIncrease parameters (ServiceCode, QuotaCode, DesiredValue):
    https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_RequestServiceQuotaIncrease.html (read 2026-10-07)
    """
    code = quota_code_for(instance_type) or "<QUOTA_CODE>"
    return (f"aws service-quotas request-service-quota-increase --service-code sagemaker "
            f"--quota-code {code} --desired-value 1 --region {region}")


def base_parser(description: str, bills: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the AWS API calls this script would make and make none.")
    if bills:
        parser.add_argument("--i-understand-this-bills", action="store_true",
                            help="Required. This script creates a resource that is billed by the hour until deleted.")
    return parser


def stop_reminder(script: str, sent: list[str], exit_code: int = 1) -> str:
    """The last line a script prints when it stops on an error or on Ctrl-C (exit_code 130): what this run
    changed, and what to do next."""
    if sent:
        then = "Next, once the cause above is dealt with: " if exit_code == 1 else "Next: "
        return ("BEFORE IT STOPPED, THIS RUN HAD SENT TO AWS: " + ", ".join(sent) + ". Treat each as carried out. An "
                f"endpoint that exists is billing by the hour until it is deleted, whatever was printed above. {then}"
                "python 99_verify_clean.py (shows what exists), then python 90_teardown.py "
                f"(stops the charge). Exit code {exit_code}.")
    if script == "99_verify_clean.py":
        return ("This check did not finish, so it is NOT a clean result and proves nothing either way. Deal with the "
                "cause above and run it again. An endpoint that exists keeps billing in the meantime.")
    if script == "00_check.py":
        return "00_check.py creates, changes and deletes nothing. Deal with the cause above and run it again."
    return ("STOPPED BEFORE ANY CHANGE: this run created and deleted nothing in AWS. An endpoint that already exists "
            "keeps billing: python 99_verify_clean.py shows whether one does, python 90_teardown.py deletes it.")


def guarded(main: Callable[[], int], script: str | None = None) -> int:
    """Run a script's main(), turning expected problems into plain lines and a non-zero exit.

    Exit code 2 means the script stopped BEFORE it created or deleted anything. Once Aws.call() has sent a
    create or delete call that AWS carried out or may have carried out, every stop is exit code 1, except
    Ctrl-C, which is exit code 130; either way the last line names those calls (stop_reminder). Everything
    printed while main() runs, AWS error text and tracebacks included, passes through redact().
    """
    script = script if script is not None else Path(sys.argv[0]).name
    sent = sent_changes()
    sent.clear()
    plain_out, plain_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _RedactingStream(plain_out), _RedactingStream(plain_err)
    try:
        try:
            return main()
        except KitError as exc:
            print(f"STOP: {exc}", file=sys.stderr)
            if not sent:
                return 2
            print(stop_reminder(script, sent), file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nInterrupted (Ctrl-C).", file=sys.stderr)
            print(stop_reminder(script, sent, exit_code=130), file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - last line of defence, keeps the message readable
            name = type(exc).__name__
            if name in CREDENTIAL_ERRORS:
                print(f"STOP: no usable AWS credentials ({name}: {exc}). Sign in first (README section 3)"
                      f"{'' if sent else ', or use --dry-run to see the calls without credentials'}.", file=sys.stderr)
                print(stop_reminder(script, sent), file=sys.stderr)
                return 1 if sent else 2
            if error_code(exc):
                print(f"STOP: AWS returned {error_code(exc)}: {error_message(exc)}", file=sys.stderr)
                print(stop_reminder(script, sent), file=sys.stderr)
                return 1
            # Anything else (a timeout, a dropped connection, another library's error, a bug in this kit).
            # The traceback is printed for whoever debugs it; the last two lines are the ones to act on.
            import traceback

            traceback.print_exc()
            print(f"STOP: unexpected {name}: {exc}. That was not an answer from AWS that this kit understands.",
                  file=sys.stderr)
            print(stop_reminder(script, sent), file=sys.stderr)
            return 1
    finally:
        sys.stdout, sys.stderr = plain_out, plain_err


# ---------------------------------------------------------------------------
# Memory arithmetic (README section 2 explains the formulas and their sources)
# ---------------------------------------------------------------------------

def memory_estimate(facts: dict[str, Any], max_model_len: int, max_num_seqs: int,
                    gpu_mem_gib: float, gpu_memory_utilization: float) -> dict[str, float]:
    """Weights plus KV cache against GPU memory. All results in GiB (2**30 bytes) unless named otherwise.

    Weights:  parameters x bytes per parameter.
    KV cache per token, AWS LMI formula: 2 x bytes per value x layers x hidden size
        (https://docs.djl.ai/master/docs/serving/serving/docs/lmi/deployment_guide/instance-type-selection.html,
        read 2026-10-07). It ignores grouped-query attention, so it is an upper bound.
    KV cache per token, adjusted: 2 x bytes per value x layers x key/value heads x head dimension.
        This adjustment is this kit's own arithmetic from the model's config.json, not an AWS formula.
    """
    gib = float(2 ** 30)
    bytes_per = facts["bytes_per_parameter"]
    weights = facts["parameters"] * bytes_per / gib
    kv_token_lmi = 2 * bytes_per * facts["num_hidden_layers"] * facts["hidden_size"]
    kv_token_gqa = 2 * bytes_per * facts["num_hidden_layers"] * facts["num_key_value_heads"] * facts["head_dim"]
    budget = gpu_mem_gib * gpu_memory_utilization
    kv_pool = budget - weights
    return {
        "weights_gib": weights,
        "kv_bytes_per_token_lmi": float(kv_token_lmi),
        "kv_bytes_per_token_gqa": float(kv_token_gqa),
        "kv_per_full_sequence_lmi_gib": kv_token_lmi * max_model_len / gib,
        "kv_per_full_sequence_gqa_gib": kv_token_gqa * max_model_len / gib,
        "kv_worst_case_lmi_gib": kv_token_lmi * max_model_len * max_num_seqs / gib,
        "kv_worst_case_gqa_gib": kv_token_gqa * max_model_len * max_num_seqs / gib,
        "vllm_budget_gib": budget,
        "kv_pool_before_overhead_gib": kv_pool,
        "full_sequences_that_fit_lmi": kv_pool * gib / (kv_token_lmi * max_model_len),
        "full_sequences_that_fit_gqa": kv_pool * gib / (kv_token_gqa * max_model_len),
    }


# ---------------------------------------------------------------------------
# Create, wait, delete, find
# ---------------------------------------------------------------------------

def create_stack(aws: Aws, cfg: Config, env: dict[str, str], role_arn: str, state: dict[str, Any],
                 state_path: Path, usd_per_hour: float, deadline: dt.datetime, now: dt.datetime,
                 out: Callable[[str], None], price_source: str = "",
                 replaced: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create model, endpoint configuration and endpoint.

    deadline is the time the owner said they would tear down by. It is recorded, shown by every
    script, and enforced by 50, 60 and 70 (they refuse to run past it). It deletes nothing by itself.
    replaced is what 70_change_one_setting.py passes: runs, hours and dollars of the endpoint(s) this one
    replaces in the same sitting, so that the BILLING lines can say what their figure leaves out.

    Each of the three is written into the state file BEFORE its create call, with no ARN, and completed
    after it. So the file names the Region, prefix, account and the resource from the first call on, also
    when the process dies between the call and the next line. A record is taken out again only when AWS
    refused the one request that was sent (a 4xx on the first try) with something other than "already
    exists". If no answer arrives (a timeout, a dropped connection), or the refusal came back after the SDK
    had sent the request again, the record stays, because the resource may exist.

    The endpoint is the one that bills, so it gets one more check: before its record is taken out,
    ListEndpoints is asked, and it leaves the state file only when it is not listed. "Already exists", or a
    refusal with the endpoint listed, means an endpoint of this kit's fixed name is there and billing: the
    record and the deploy record stay (marked "already exists"), and the script stops with exit code 1.
    """
    revision = revision_from(now)
    model_name = cfg.model_name(revision)
    config_name = cfg.endpoint_config_name(revision)
    endpoint_name = cfg.endpoint_name

    def remember(kind: str, name: str) -> dict[str, Any]:
        """Write the resource into the state file BEFORE the create call, with no ARN yet."""
        entry = {"type": kind, "name": name, "arn": None, "created_utc": iso(utc_now())}
        state["resources"].append(entry)
        if not aws.dry_run:
            save_state(state, state_path)
        return entry

    def confirm(entry: dict[str, Any], arn: str | None) -> None:
        entry["arn"] = arn
        if not aws.dry_run:
            save_state(state, state_path)

    def create_failed(exc: Exception, entry: dict[str, Any], api_name: str) -> KitError | None:
        """After a create call raised: take the record back out when AWS refused (4xx), keep it otherwise.

        Returns the error to raise when the outcome is unknown, or None when the caller re-raises AWS's refusal.
        """
        if definitely_rejected(exc) and not says_already_exists(exc):
            state["resources"] = [r for r in state["resources"] if r is not entry]
            save_state(state, state_path)
            return None
        return KitError(
            f"{api_name} did not come back with a clear answer ({type(exc).__name__}: {error_message(exc)}"
            f"{sent_again(exc)}). "
            f"The {entry['type'].replace('_', ' ')} {entry['name']} MAY exist. It costs nothing by itself and it stays "
            f"in {state_path.name}, which also records the Region, prefix and account. Nothing further was created. "
            "Do this now: python 90_teardown.py   then   python 99_verify_clean.py")

    def sent_again(exc: Exception) -> str:
        again = retry_attempts(exc)
        return f"; the SDK had sent the request {again + 1} times, so an earlier try may have been carried out" if again else ""

    # The state file is written before the first create call, so a deploy that dies right after CreateModel
    # (a closed terminal, kill -9) still leaves a record of the place and of the model.
    model_entry = remember("model", model_name)
    try:
        # CreateModel: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateModel.html (read 2026-10-07)
        # PrimaryContainer.Image and .Environment: .../API_ContainerDefinition.html (read 2026-10-07)
        # No VpcConfig and no network isolation: the container downloads the weights from huggingface.co at start.
        response = aws.call(
            "sagemaker", "create_model",
            ModelName=model_name,
            ExecutionRoleArn=role_arn,
            PrimaryContainer={"Image": cfg.image_uri, "Environment": env},
            Tags=cfg.tags(),
        )
    except Exception as exc:  # noqa: BLE001 - classified in create_failed
        unknown = create_failed(exc, model_entry, "CreateModel")
        if unknown is None:
            raise
        raise unknown from exc
    confirm(model_entry, (response or {}).get("ModelArn"))

    variant: dict[str, Any] = {
        "VariantName": VARIANT_NAME,
        "ModelName": model_name,
        "InstanceType": cfg.instance_type,
        "InitialInstanceCount": 1,
        "ContainerStartupHealthCheckTimeoutInSeconds": cfg.health_timeout_s,
    }
    if cfg.inference_ami_version:
        # InferenceAmiVersion values: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ProductionVariant.html
        # (read 2026-10-07): al2023-ami-sagemaker-inference-gpu-4-1 = NVIDIA driver 580, CUDA 13.0.
        # The AWS DLC docs say GPU deployments of the CUDA 13.0 vLLM image need this field, and AWS's own
        # endpoint test plus three AWS sample notebooks pair cu130 vLLM tags with this value.
        # UNVERIFIED: that this value is right for this exact image tag. Two other AWS pages read the same day
        # differ (README section 2, "AWS sources disagree on the host AMI").
        variant["InferenceAmiVersion"] = cfg.inference_ami_version

    config_entry = remember("endpoint_config", config_name)
    try:
        # CreateEndpointConfig: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateEndpointConfig.html (read 2026-10-07)
        response = aws.call(
            "sagemaker", "create_endpoint_config",
            EndpointConfigName=config_name,
            ProductionVariants=[variant],
            Tags=cfg.tags(),
        )
    except Exception as exc:  # noqa: BLE001 - classified in create_failed
        unknown = create_failed(exc, config_entry, "CreateEndpointConfig")
        if unknown is None:
            raise
        raise unknown from exc
    confirm(config_entry, (response or {}).get("EndpointConfigArn"))

    create_called = utc_now() if not aws.dry_run else now
    state["deploy"] = {
        "revision": revision,
        "region": cfg.region,
        "prefix": cfg.prefix,
        "account_id": state.get("account_id"),
        "instance_type": cfg.instance_type,
        "usd_per_hour": usd_per_hour,
        "price_source": price_source,
        "hf_model_id": cfg.hf_model_id,
        "image_uri": cfg.image_uri,
        "inference_ami_version": cfg.inference_ami_version,
        "env": dict(env),
        "create_called_utc": iso(create_called),
        "in_service_utc": None,
        "deadline_utc": iso(deadline),
        "endpoint_create_confirmed": False,
    }
    if replaced and replaced.get("runs"):
        state["deploy"]["replaced_in_this_sitting"] = dict(replaced)
    remember("endpoint", endpoint_name)
    try:
        # CreateEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateEndpoint.html (read 2026-10-07)
        # This is the call that starts the GPU instance. Treat billing as starting here.
        response = aws.call(
            "sagemaker", "create_endpoint",
            EndpointName=endpoint_name,
            EndpointConfigName=config_name,
            Tags=cfg.tags(),
        )
    except Exception as exc:  # noqa: BLE001 - classified just below
        exists = says_already_exists(exc)
        if definitely_rejected(exc) and not exists:
            # A refusal on the first and only try. The record of the thing that bills is still not taken out on
            # the wording of an error alone: ListEndpoints is asked. If that call fails too, the record stays.
            try:
                exists = listed_by_name(aws, "endpoint", endpoint_name)
            except Exception as list_error:  # noqa: BLE001 - the listing is a cross-check, not the answer
                raise KitError(
                    f"CreateEndpoint was refused ({error_code(exc)}: {error_message(exc)}), and ListEndpoints, asked to "
                    f"confirm that no endpoint {endpoint_name} exists, failed as well ({type(list_error).__name__}: "
                    f"{error_message(list_error)}). So the endpoint stays in {state_path.name}, marked unconfirmed: it "
                    "MAY exist and MAY be billing. Do this now: python 99_verify_clean.py (it shows whether the "
                    "endpoint exists), then python 90_teardown.py.") from exc
            if not exists:
                state["resources"] = [r for r in state["resources"] if r.get("type") != "endpoint"]
                state["deploy"] = None
                save_state(state, state_path)
                raise
        if exists:
            state["deploy"]["create_answer"] = "already exists"
            save_state(state, state_path)
            raise KitError(
                f"CreateEndpoint was refused ({error_code(exc)}: {error_message(exc)}{sent_again(exc)}), and an endpoint "
                f"named {endpoint_name} EXISTS in {scope_text(cfg.region, state.get('account_id'), cfg.prefix)}. Either "
                "this run's own request created it and the answer was lost on the way back, or it was there before. "
                f"EITHER WAY IT IS BILLING BY THE HOUR. It stays in {state_path.name} with this run's deploy record, so "
                "every later script shows the BILLING lines and teardown deletes it. "
                "Do this now: python 90_teardown.py   then   python 99_verify_clean.py   then deploy again.") from exc
        raise KitError(
            f"CreateEndpoint did not come back with a clear answer ({type(exc).__name__}: {error_message(exc)}"
            f"{sent_again(exc)}). "
            f"The endpoint {endpoint_name} MAY exist and MAY be billing. It stays in {state_path.name}, marked "
            "unconfirmed. Do this now: python 99_verify_clean.py (it shows whether the endpoint exists), "
            "then python 90_teardown.py.") from exc
    state["resources"][-1]["arn"] = (response or {}).get("EndpointArn")
    state["deploy"]["endpoint_create_confirmed"] = True
    if not aws.dry_run:
        save_state(state, state_path)
    out(f"Created model {model_name}, endpoint configuration {config_name}, endpoint {endpoint_name}.")
    return state


def wait_in_service(aws: Aws, endpoint_name: str, out: Callable[[str], None], sleep: Callable[[float], None],
                    clock: Callable[[], float], timeout_s: float = 2700.0, poll_s: float = 30.0) -> tuple[str, dict[str, Any] | None]:
    """Poll DescribeEndpoint. Returns (final status, last description)."""
    started = clock()
    last: dict[str, Any] | None = None
    while True:
        # DescribeEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeEndpoint.html (read 2026-10-07)
        # EndpointStatus values on that page: OutOfService | Creating | Updating | SystemUpdating | RollingBack |
        # InService | Deleting | Failed | UpdateRollbackFailed.
        last = aws.call("sagemaker", "describe_endpoint", EndpointName=endpoint_name)
        if last is None:  # dry run
            return "DryRun", None
        status = last.get("EndpointStatus", "Unknown")
        elapsed = clock() - started
        out(f"  [{elapsed / 60.0:5.1f} min] endpoint status: {status}")
        if status in ("InService", "Failed", "OutOfService", "UpdateRollbackFailed"):
            return status, last
        if elapsed >= timeout_s:
            return "Timeout", last
        sleep(poll_s)


def wait_endpoint_gone(aws: Aws, endpoint_name: str, out: Callable[[str], None], sleep: Callable[[float], None],
                       clock: Callable[[], float], timeout_s: float = 1800.0, poll_s: float = 15.0) -> bool:
    """Poll DescribeEndpoint until SageMaker says the endpoint does not exist. True when gone."""
    started = clock()
    while True:
        try:
            # DescribeEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeEndpoint.html (read 2026-10-07)
            description = aws.call("sagemaker", "describe_endpoint", EndpointName=endpoint_name)
        except Exception as exc:  # noqa: BLE001 - classified just below
            if is_not_found(exc):
                return True
            if error_code(exc) == "ValidationException" and not listed_by_name(aws, "endpoint", endpoint_name):
                # Not the wording this kit knows for "does not exist", so it is not taken on trust:
                # ListEndpoints was asked and no longer returns the endpoint.
                out(f"  endpoint {endpoint_name}: DescribeEndpoint answered \"{error_message(exc)[:120]}\" and "
                    "ListEndpoints no longer lists it. Treating it as gone.")
                return True
            raise
        if description is None:  # dry run
            return True
        elapsed = clock() - started
        out(f"  [{elapsed / 60.0:5.1f} min] endpoint status: {description.get('EndpointStatus', 'Unknown')}")
        if elapsed >= timeout_s:
            return False
        sleep(poll_s)


def _delete_quietly(aws: Aws, service: str, operation: str, label: str, out: Callable[[str], None],
                    absent_by_listing: Callable[[], bool] | None = None, **params: Any) -> str:
    """Returns 'deleted', 'absent' or raises.

    absent_by_listing is asked only when AWS answers with a ValidationException whose wording this kit
    does not recognise as "does not exist": the resource then counts as absent only if a List call no
    longer returns it. Any other error is raised.
    """
    try:
        aws.call(service, operation, **params)
    except Exception as exc:  # noqa: BLE001 - classified just below
        if is_not_found(exc):
            out(f"  {label}: already absent.")
            return "absent"
        if error_code(exc) == "ValidationException" and absent_by_listing is not None and absent_by_listing():
            out(f"  {label}: already absent (not in the list any more; AWS said \"{error_message(exc)[:120]}\").")
            return "absent"
        raise
    out(f"  {label}: delete requested." if not aws.dry_run else f"  {label}: (dry run)")
    return "deleted"


def delete_stack(aws: Aws, endpoint_names: list[str], config_names: list[str], model_names: list[str],
                 out: Callable[[str], None], sleep: Callable[[float], None], clock: Callable[[], float],
                 outcomes: dict[str, str] | None = None) -> bool:
    """Delete endpoints, wait until they are gone, then configurations, then models.

    Order and the reason for all three:
    https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-delete-resources.html (read 2026-10-07):
    "Deleting an endpoint will not delete the endpoint configuration or the SageMaker AI model."
    https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteEndpointConfig.html (read 2026-10-07):
    "You must not delete an EndpointConfig in use by an endpoint that is live or while the UpdateEndpoint or
    CreateEndpoint operations are being performed on the endpoint."
    Returns True when every endpoint was confirmed gone.
    outcomes, when given, is filled with "<kind>:<name>" -> "deleted" (this call deleted it), "absent" (it was
    already gone when this call looked) or "present" (an endpoint that did not go away).
    """
    record = outcomes if outcomes is not None else {}
    all_gone = True
    for name in endpoint_names:
        # DeleteEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteEndpoint.html (read 2026-10-07)
        result = _delete_quietly(aws, "sagemaker", "delete_endpoint", f"endpoint {name}", out,
                                 absent_by_listing=lambda name=name: not listed_by_name(aws, "endpoint", name),
                                 EndpointName=name)
        if not wait_endpoint_gone(aws, name, out, sleep, clock):
            out(f"  endpoint {name}: STILL PRESENT after waiting. Its configuration and model were left alone.")
            all_gone = False
            result = "present"
        record[f"endpoint:{name}"] = result
    if not all_gone:
        return False
    for name in config_names:
        # DeleteEndpointConfig: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteEndpointConfig.html (read 2026-10-07)
        record[f"endpoint_config:{name}"] = _delete_quietly(
            aws, "sagemaker", "delete_endpoint_config", f"endpoint configuration {name}", out,
            absent_by_listing=lambda name=name: not listed_by_name(aws, "endpoint_config", name),
            EndpointConfigName=name)
    for name in model_names:
        # DeleteModel: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteModel.html (read 2026-10-07)
        record[f"model:{name}"] = _delete_quietly(
            aws, "sagemaker", "delete_model", f"model {name}", out,
            absent_by_listing=lambda name=name: not listed_by_name(aws, "model", name), ModelName=name)
    return True


# (operation, result key, name key, ARN key, bucket in find_remaining, kind in the state file)
_LIST_PLAN = [
    # ListEndpoints: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpoints.html (read 2026-10-07)
    ("list_endpoints", "Endpoints", "EndpointName", "EndpointArn", "endpoints", "endpoint"),
    # ListEndpointConfigs: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpointConfigs.html (read 2026-10-07)
    ("list_endpoint_configs", "EndpointConfigs", "EndpointConfigName", "EndpointConfigArn", "endpoint_configs", "endpoint_config"),
    # ListModels: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListModels.html (read 2026-10-07)
    ("list_models", "Models", "ModelName", "ModelArn", "models", "model"),
]


def _list_all(aws: Aws, operation: str, result_key: str, **extra: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        params: dict[str, Any] = {"MaxResults": 100, **extra}
        if token:
            params["NextToken"] = token
        page = aws.call("sagemaker", operation, **params)
        if page is None:  # dry run
            return items
        items.extend(page.get(result_key, []))
        token = page.get("NextToken")
        if not token:
            return items


def listed_by_name(aws: Aws, kind: str, name: str) -> bool:
    """True when a List call in this Region and account still returns a resource with exactly this name.

    kind is "endpoint", "endpoint_config" or "model". NameContains is a request parameter of all three
    List operations ("returns only endpoints whose name contains the specified string", same pages as in
    _LIST_PLAN, read 2026-10-07); the exact comparison is done here. In a dry run nothing is listed.
    """
    for operation, result_key, name_key, _arn_key, _bucket, plan_kind in _LIST_PLAN:
        if plan_kind == kind:
            return any(item.get(name_key) == name
                       for item in _list_all(aws, operation, result_key, NameContains=name))
    raise KitError(f"Internal error: unknown resource kind {kind!r}.")


def _has_kit_tags(tags: list[dict[str, str]]) -> bool:
    pairs = {(t.get("Key"), t.get("Value")) for t in tags}
    return (PROJECT_TAG_KEY, PROJECT_TAG_VALUE) in pairs and (KIT_TAG_KEY, KIT_TAG_VALUE) in pairs


def find_remaining(aws: Aws, cfg: Config, check_logs: bool = True, max_tag_lookups: int = 300,
                   extra_prefixes: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
    """List endpoints, endpoint configurations and models that belong to this kit, in aws.region.

    A resource belongs to the kit when its name starts with "<KIT_PREFIX>-kita-" OR it carries both
    tags project=aws-kits and kit=kit-a-gpu-endpoint. The second test finds resources even when the
    prefix was changed or the state file was lost. extra_prefixes adds further name prefixes to look
    for (99_verify_clean.py passes the prefixes the state file names).

    CloudWatch log groups under /aws/sagemaker/Endpoints/ belong to the kit when they are the log group
    of an endpoint found here, or when their name follows this kit's naming rule under any prefix.
    Every log group under that path is listed to find them (50 per call).
    """
    found: dict[str, Any] = {
        "endpoints": [], "endpoint_configs": [], "models": [], "log_groups": [],
        "other_endpoints": 0, "tag_lookups": 0, "incomplete": False,
    }
    stems = [cfg.name_stem] + [f"{prefix}-{NAME_INFIX}-" for prefix in extra_prefixes
                               if f"{prefix}-{NAME_INFIX}-" != cfg.name_stem]
    for operation, result_key, name_key, arn_key, bucket, _kind in _LIST_PLAN:
        for item in _list_all(aws, operation, result_key):
            name = item.get(name_key, "")
            arn = item.get(arn_key, "")
            entry = {"name": name, "arn": arn, "why": "", "status": item.get("EndpointStatus")}
            if name.startswith(tuple(stems)):
                entry["why"] = "name prefix"
                found[bucket].append(entry)
                continue
            if found["tag_lookups"] >= max_tag_lookups:
                found["incomplete"] = True
                if bucket == "endpoints":
                    found["other_endpoints"] += 1
                continue
            found["tag_lookups"] += 1
            # ListTags: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListTags.html (read 2026-10-07)
            tags = (aws.call("sagemaker", "list_tags", ResourceArn=arn) or {}).get("Tags", [])
            if _has_kit_tags(tags):
                entry["why"] = "tags"
                found[bucket].append(entry)
            elif bucket == "endpoints":
                found["other_endpoints"] += 1
    if check_logs:
        # This kit does not create the log groups, so it cannot tag them. They are matched by name: the log group
        # of an endpoint found above (by name or by tag), or a name this kit's naming rule produces under any
        # prefix ("<prefix>-kita-..."). The second test finds the log group of an endpoint that was deployed
        # under another prefix and is already gone.
        endpoint_names = {entry["name"] for entry in found["endpoints"]}
        token: str | None = None
        while True:
            params: dict[str, Any] = {"logGroupNamePrefix": LOG_GROUP_ROOT, "limit": 50}
            if token:
                params["nextToken"] = token
            # DescribeLogGroups: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html (read 2026-10-07)
            # limit is at most 50 per page; nextToken continues the list.
            page = aws.call("logs", "describe_log_groups", **params)
            for group in (page or {}).get("logGroups", []):
                name = group.get("logGroupName", "")
                if not name.startswith(LOG_GROUP_ROOT):
                    continue
                tail = name[len(LOG_GROUP_ROOT):]
                if tail.startswith(tuple(stems)):
                    why = "name prefix"
                elif tail in endpoint_names:
                    why = "the log group of an endpoint listed above"
                elif _KIT_LOG_TAIL_RE.match(tail):
                    why = "this kit's name pattern under another prefix"
                else:
                    continue
                found["log_groups"].append({"name": name, "why": why})
            token = (page or {}).get("nextToken")
            if not token:
                break
    return found


def remaining_count(found: dict[str, Any], count_logs: bool = True) -> int:
    total = len(found["endpoints"]) + len(found["endpoint_configs"]) + len(found["models"])
    if count_logs:
        total += len(found["log_groups"])
    return total


def describe_remaining(found: dict[str, Any], count_logs: bool = True) -> list[str]:
    lines = []
    labels = [("endpoints", "Endpoints (these bill by the hour)"), ("endpoint_configs", "Endpoint configurations"),
              ("models", "Models"), ("log_groups", "CloudWatch log groups" + ("" if count_logs else " (not counted)"))]
    for bucket, label in labels:
        lines.append(f"{label}: {len(found[bucket])}")
        for entry in found[bucket]:
            status = f", status {entry['status']}" if entry.get("status") else ""
            lines.append(f"    {entry['name']} (matched by {entry['why']}{status})")
    lines.append(f"Other SageMaker endpoints in this Region that are not this kit's (not counted): {found['other_endpoints']}")
    if found["incomplete"]:
        lines.append("INCOMPLETE: the tag lookup limit was reached, so some resources were not checked for tags. "
                     "Raise --max-tag-lookups and run again.")
    return lines
