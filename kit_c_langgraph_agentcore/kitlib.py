"""Shared plumbing for the numbered scripts in this kit.

What lives here:
- Config: Region, prefix, model id and resource names, from the environment
  and an optional config.env file next to this file;
- Aws: one place every AWS call goes through. In --dry-run it prints the call
  and makes none. In both modes it first checks the parameters against the
  service model that ships inside the installed AWS SDK, so a wrong parameter
  name fails on your machine and not in your account;
- State: .state.json, the record of what was created and where (Region, name
  prefix, account id). It is written atomically. A file that cannot be read is
  NEVER moved, renamed, deleted or overwritten by any script in this kit: the
  script stops and says what to do (review round 2, 2026-10-07);
- check_place: the comparison every state-reading script makes before it acts;
- prices, each with the page it was read on and the date;
- the --dry-run and --i-understand-this-bills flags.

Exit codes used across the kit:
  0  done
  1  something failed, or something is left, or a result is not verified; also every stop
     after a create call was sent, whatever stopped it
  2  refused before anything was done: bad arguments, bad configuration, no credentials,
     or the billing flag is missing
  3  a --dry-run of 90_teardown.py, optional_gateway/90_teardown_gateway.py or
     99_verify_clean.py (a dry run deletes nothing and proves nothing, so it is not 0)
  4  STOPPED: .state.json records another Region, prefix or account than the one in use,
     or cannot be read, or names resources without saying where they are
  5  INCOMPLETE. 99_verify_clean.py: there is a place this run could not check.
     90_teardown.py with --region and --prefix beside a state file it cannot use: every
     delete worked, but nothing says where else the kit was deployed

Nothing here was run against AWS. See README.md section 8.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Callable

KIT_DIR = pathlib.Path(__file__).resolve().parent
STATE_PATH = KIT_DIR / ".state.json"
BUILD_DIR = KIT_DIR / ".build"
PACKAGE_ZIP = BUILD_DIR / "deployment_package.zip"

READ_DATE = "2026-10-07"  # the day every source in this kit was read
DRY_ACCOUNT = "000000000000"  # placeholder shown in --dry-run output, not a real account

TAGS = {"project": "aws-kits", "kit": "kit-c"}

DEFAULT_REGION = "us-east-1"
DEFAULT_PREFIX = "kitdemo"
DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"

EXIT_DRY_RUN_PROVES_NOTHING = 3
EXIT_STATE_MISMATCH = 4
EXIT_INCOMPLETE = 5

# AWS, on usage logs and metrics for AgentCore Runtime (read 2026-10-07):
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html
USAGE_DELAY_MINUTES = 60
USAGE_DELAY = dt.timedelta(minutes=USAGE_DELAY_MINUTES)
USAGE_DELAY_QUOTE = ('"Resource usage data may be delayed by up to 60 minutes and precision might '
                     'differ across metrics."')

# --------------------------------------------------------------------------
# prices, as read on the AgentCore pricing page on READ_DATE
# --------------------------------------------------------------------------
PRICING_URL = "https://aws.amazon.com/bedrock/agentcore/pricing/"
PRICING_REGION_NOTE = ("the page's pricing table has one Runtime price and no Region column; it "
                       "does not say which Regions the price covers")
RUNTIME_RATES = {
    # platform version -> (USD per vCPU-hour, USD per GB-hour)
    "V1": (0.0895, 0.00945),
    "V2": (0.1276, 0.0169),
}
GATEWAY_USD_PER_1000_CALLS = 0.005
GATEWAY_USD_PER_1000_SEARCHES = 0.025
GATEWAY_USD_PER_100_TOOLS_INDEXED_MONTH = 0.02

# The most one session may use. Quotas page, read 2026-10-07: "Maximum hardware allocation per
# session | 2vCPU/8GB".  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html
SESSION_MAX_VCPU = 2
SESSION_MAX_GB = 8
# Service defaults when a runtime sets no lifecycle configuration, read 2026-10-07:
# "idleRuntimeSessionTimeout: 900 seconds (15 minutes)", "maxLifetime: 28800 seconds (8 hours)".
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html
SERVICE_DEFAULT_IDLE_S = 900
SERVICE_DEFAULT_LIFETIME_S = 28800
# Memory assumed for a session that only sits idle. This is an assumption, not a measurement:
# the pricing page's own example starts a session at 1 GB, and 128 MB is the billing minimum.
IDLE_GB_ASSUMED = 0.5

PRICE_LINES_RUNTIME = [
    "AgentCore Runtime, platform V1 (the default): $0.0895 per vCPU-hour, $0.00945 per GB-hour.",
    "AgentCore Runtime, platform V2 (consumption): $0.1276 per vCPU-hour, $0.0169 per GB-hour.",
    "Billed per second on actual CPU and memory, 1 second minimum, 128 MB memory minimum.",
    'The page also says: "Billing includes system overhead in addition to your application\'s',
    'resource usage"; "direct code deployment bills for the size of the code artifacts you',
    'deployed at S3 Standard rates" (its example: 100 MB is $0.0023 a month); and "Network data',
    'transfer charges apply at standard EC2 rates". So a deployed runtime with no session is',
    "not free: the stored zip bills a fraction of a cent a month until teardown.",
    "A session bills until it is stopped or its idle timeout ends it.",
    f"Source: {PRICING_URL} read {READ_DATE}; {PRICING_REGION_NOTE}.",
]

# Bedrock on-demand token prices in USD per 1,000,000 tokens (input, output), for the two
# models this kit names. Read 2026-10-07 from the price file behind
# https://aws.amazon.com/bedrock/pricing/ (table "Geo Cross-region inference and in-region",
# Standard tier, columns "Price per 1M input tokens" and "Price per 1M output tokens"):
# https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrock/USD/current/bedrock.json
# (file published 2026-10-06). The same figures apply in the three Regions listed.
#
# Read again on 2026-10-07 for review round 2, from the AWS Price List file, which names
# each row: https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json
# (publicationDate 2026-10-06T14:47:26Z; the us-east-2 and us-west-2 files carry the same
# figures). It prices per 1K tokens:
#   Nova2.0Lite-input-tokens                      $0.00033   -> $0.33 per 1M   ("geo")
#   Nova2.0Lite-output-tokens                     $0.00275   -> $2.75 per 1M
#   Nova2.0Lite-input-tokens-cross-region-global  $0.0003    -> $0.30 per 1M   ("global")
#   Nova2.0Lite-output-tokens-cross-region-global $0.0025    -> $2.50 per 1M
#   NovaMicro-input-tokens                        $0.000035  -> $0.035 per 1M  ("geo")
#   NovaMicro-output-tokens                       $0.00014   -> $0.14 per 1M
# The file has no "cross-region-global" row for Nova Micro, so this kit holds no price for a
# global.amazon.nova-micro-v1:0 id. "geo" is what a plain model id or a us. inference profile
# pays in the three Regions listed; "global" is what a global. inference profile pays. The
# first version of this kit charged a global. id the geo price, 10% too much.
BEDROCK_PRICING_URL = "https://aws.amazon.com/bedrock/pricing/"
BEDROCK_PRICE_LIST_URL = ("https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/"
                          "current/us-east-1/index.json")
MODEL_PRICE_REGIONS = ("us-east-1", "us-east-2", "us-west-2")
MODEL_USD_PER_1M_TOKENS = {
    "amazon.nova-micro-v1:0": {"geo": (0.035, 0.14)},
    "amazon.nova-2-lite-v1:0": {"geo": (0.33, 2.75), "global": (0.30, 2.50)},
}
PRICE_LINES_MODEL = [
    "Bedrock model tokens, a separate charge. Prices are per 1,000,000 (1M) tokens:",
    "  Amazon Nova Micro (the default): $0.035 per 1M input tokens, $0.14 per 1M output tokens.",
    "  Amazon Nova 2 Lite:              $0.33 per 1M input tokens, $2.75 per 1M output tokens;",
    "                                   through a global. inference profile $0.30 and $2.50.",
    "Standard tier, in us-east-1, us-east-2 and us-west-2, for a plain model id or a us. profile.",
    f"Source: the price file behind {BEDROCK_PRICING_URL} and the AWS Price List file",
    f"(both published 2026-10-06), read {READ_DATE}.",
    "For any other model, profile or Region, look the price up on that page before you run.",
]
PRICE_LINES_LOGS = [
    "CloudWatch logs, spans and metrics: charged at Amazon CloudWatch rates (per the AgentCore",
    f"pricing page, read {READ_DATE}). The CloudWatch rates themselves are NOT QUOTED here.",
]
PRICE_LINES_S3 = [
    "S3: the zip (about 54 MB) sits in your bucket while the kit is deployed, and AgentCore bills",
    "the deployed code artifact at S3 Standard rates as well. S3's own rate table is NOT QUOTED",
    "here; by the AgentCore page's example (100 MB is $0.0023 a month) this is well under one",
    "cent a month.",
]
PRICE_LINES_GATEWAY = [
    "AgentCore Gateway: $0.005 per 1,000 API invocations (ListTools, InvokeTool, Ping),",
    "$0.025 per 1,000 search calls, $0.02 per 100 tools indexed per month.",
    f"Source: {PRICING_URL} read {READ_DATE}; {PRICING_REGION_NOTE}.",
]


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
def load_env_file(path: pathlib.Path | None = None) -> None:
    """Read KEY=VALUE lines from config.env into os.environ. Real env vars win."""
    path = path or (KIT_DIR / "config.env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ConfigError(ValueError):
    pass


@dataclasses.dataclass
class Config:
    region: str = DEFAULT_REGION
    prefix: str = DEFAULT_PREFIX
    model_id: str = DEFAULT_MODEL_ID
    platform_version: str = ""  # "" means leave it out, which AWS documents as V1
    idle_timeout_s: int = 120
    max_lifetime_s: int = 900
    enable_otel: bool = True
    python_runtime: str = "PYTHON_3_13"
    role_s3_read: bool = False  # add s3:GetObject on the zip to the execution role (README section 2)

    @classmethod
    def from_env(cls) -> "Config":
        load_env_file()
        env = os.environ
        cfg = cls(
            region=env.get("AWS_REGION", "").strip() or DEFAULT_REGION,
            prefix=env.get("KIT_PREFIX", "").strip() or DEFAULT_PREFIX,
            model_id=env.get("MODEL_ID", "").strip() or DEFAULT_MODEL_ID,
            platform_version=env.get("PLATFORM_VERSION", "").strip().upper(),
            idle_timeout_s=int(env.get("IDLE_TIMEOUT_SECONDS", "120") or 120),
            max_lifetime_s=int(env.get("MAX_LIFETIME_SECONDS", "900") or 900),
            enable_otel=env.get("ENABLE_OTEL", "true").strip().lower() not in {"0", "false", "no"},
            python_runtime=env.get("PYTHON_RUNTIME", "").strip() or "PYTHON_3_13",
            role_s3_read=env.get("EXECUTION_ROLE_S3_READ", "").strip().lower() in {"1", "true", "yes"},
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", self.prefix) or self.prefix.endswith("-"):
            raise ConfigError(
                "KIT_PREFIX must be 2 to 16 characters: lower-case letters, digits and hyphens, "
                "starting with a letter"
            )
        if not re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", self.region):
            raise ConfigError(f"AWS_REGION does not look like a Region name: {self.region!r}")
        if self.platform_version not in {"", "V1", "V2"}:
            raise ConfigError("PLATFORM_VERSION must be empty, V1 or V2")
        # The CreateAgentRuntime request model (botocore 1.43.108) allows 60 to 1,209,600, but
        # the larger values are for runtimes on a capacity provider. This kit creates a microVM
        # runtime, for which the documented range is "60-28800 (microVMs)":
        # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html (read 2026-10-07)
        for name, value in (("IDLE_TIMEOUT_SECONDS", self.idle_timeout_s),
                            ("MAX_LIFETIME_SECONDS", self.max_lifetime_s)):
            if not 60 <= value <= SERVICE_DEFAULT_LIFETIME_S:
                raise ConfigError(f"{name} must be between 60 and {SERVICE_DEFAULT_LIFETIME_S}")
        if self.idle_timeout_s > self.max_lifetime_s:
            raise ConfigError("IDLE_TIMEOUT_SECONDS must not exceed MAX_LIFETIME_SECONDS")
        if self.python_runtime not in {"PYTHON_3_11", "PYTHON_3_12", "PYTHON_3_13"}:
            raise ConfigError("PYTHON_RUNTIME must be PYTHON_3_11, PYTHON_3_12 or PYTHON_3_13")

    # ---- names. Every resource this kit creates starts with the prefix. ----
    @property
    def runtime_name(self) -> str:
        # AgentCore runtime names allow letters, digits and underscores only.
        return f"{self.prefix.replace('-', '_')}_kitc_fr_agent"

    @property
    def role_name(self) -> str:
        return f"{self.prefix}-kitc-runtime-role"

    @property
    def role_policy_name(self) -> str:
        return f"{self.prefix}-kitc-runtime-policy"

    def bucket_name(self, account_id: str) -> str:
        return f"{self.prefix}-kitc-code-{account_id}-{self.region}"

    @property
    def code_key(self) -> str:
        return f"{self.runtime_name}/deployment_package.zip"

    @property
    def usage_log_group(self) -> str:
        return f"/aws/vendedlogs/bedrock-agentcore/{self.prefix}-kitc-usage"

    @property
    def app_log_group(self) -> str:
        return f"/aws/vendedlogs/bedrock-agentcore/{self.prefix}-kitc-app"

    @property
    def runtime_log_group_prefix(self) -> str:
        # Runtime logs go to /aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>
        # and the agent id starts with the runtime name.
        return f"/aws/bedrock-agentcore/runtimes/{self.runtime_name}-"

    def delivery_names(self, kind: str) -> tuple[str, str]:
        return (f"{self.prefix}-kitc-{kind}-src", f"{self.prefix}-kitc-{kind}-dst")

    @property
    def gateway_name(self) -> str:
        return f"{self.prefix}-kitc-gateway"

    @property
    def gateway_role_name(self) -> str:
        return f"{self.prefix}-kitc-gateway-role"

    @property
    def python_version(self) -> str:
        return self.python_runtime.replace("PYTHON_", "").replace("_", ".")

    def rates(self, reported_platform_version: str | None = None,
              requested_platform_version: str | None = None) -> tuple[str, float, float]:
        """Rates for the platform version in use: what the service reported at deploy time,
        else what the deploy asked for, else the current setting, else V1 (the documented
        default). A stored "not reported" or "default" is not a version and is skipped."""
        for candidate in (reported_platform_version, requested_platform_version,
                          self.platform_version, "V1"):
            version = str(candidate or "").upper()
            if version in RUNTIME_RATES:
                cpu, mem = RUNTIME_RATES[version]
                return version, cpu, mem
        raise AssertionError("unreachable: V1 is always in RUNTIME_RATES")

    def rates_basis(self, reported_platform_version: str | None = None,
                    requested_platform_version: str | None = None) -> str:
        """Where the platform version behind rates() came from, in words for a rates line.
        Only a version the service reported is known; anything else is an assumption, and
        the usage cross-check compares hours, not dollars, so it cannot catch a wrong one."""
        if str(reported_platform_version or "").upper() in RUNTIME_RATES:
            return "the version the service reported"
        version = self.rates(reported_platform_version, requested_platform_version)[0]
        other = "V2" if version == "V1" else "V1"
        if str(requested_platform_version or "").upper() in RUNTIME_RATES:
            how = "ASSUMED from what the deploy asked for; the service reported no version"
        elif self.platform_version in RUNTIME_RATES:
            how = "ASSUMED from the PLATFORM_VERSION setting in use now; the service reported no version"
        else:
            how = ("ASSUMED: AWS documents V1 when none is asked for; the service reported no version")
        return f"{how}. If the runtime is really on {other}, these rates are wrong"


# --------------------------------------------------------------------------
# state file
# --------------------------------------------------------------------------
class StateUnusable(RuntimeError):
    """Raised when something tries to write over a state file that could not be read."""


class State:
    """.state.json: what this kit created, and where.

    A file that is empty, cut short or not JSON is DAMAGED. It is left exactly where it is:
    no script in this kit moves, renames, deletes or overwrites it (the first version set it
    aside and carried on, which threw away the only record of the Region the deploy was in).
    .damaged says why it could not be read, .data stays empty, and save() refuses. Every
    script then stops through check_place() or explain_unusable_state().
    Written atomically: a temporary file in the same folder, flushed, then renamed over the
    old one, so a kill at any moment leaves either the old file or the new one, never half.
    """

    def __init__(self, path: pathlib.Path | None = None, dry_run: bool = False,
                 out: Callable[[str], None] = print):
        self.path = path or STATE_PATH
        self.dry_run = dry_run
        self.data: dict = {}
        self.damaged: str | None = None
        self.existed = self.path.exists()
        if not self.existed:
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("the file does not hold a JSON object")
            self.data = loaded
        except (OSError, ValueError) as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            self.damaged = f"{type(exc).__name__}: {str(exc)[:120]}"

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, **values: Any) -> None:
        self.data.update(values)
        self.save()

    def remove(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)
        self.save()

    def save(self) -> None:
        if self.dry_run:
            return
        if self.damaged:
            raise StateUnusable(f"{self.path.name} could not be read ({self.damaged}); it is never "
                                "overwritten")
        self.data["updated_at"] = utc_now_iso()
        text = json.dumps(self.data, indent=2, sort_keys=True, default=str) + "\n"
        temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)  # atomic on POSIX and on Windows
        finally:
            if temporary.exists():  # only when the rename did not happen
                temporary.unlink()


# --------------------------------------------------------------------------
# where the deploy was made: Region, prefix, account
# --------------------------------------------------------------------------
PLACE_KEYS = ("region", "prefix", "account_id")
_ARN_KEYS = ("runtime_arn", "gateway_arn", "workload_identity_arn")
# Keys that mean "something was created". A file that has one of these must also say where.
RESOURCE_KEYS = ("runtime_id", "runtime_arn", "gateway_id", "gateway_arn", "bucket", "role_name",
                 "gateway_role_name", "workload_identity_arn", "deliveries", "log_groups", "sessions")


def recorded_place(state: State) -> dict | None:
    """The Region, prefix and account id of the deploy recorded in .state.json, or None when
    nothing is deployed according to the file (empty, or history only)."""
    data = state.data
    if not any(data.get(key) for key in PLACE_KEYS):
        return None
    account = data.get("account_id")
    if not account:  # a file written before the account id was recorded: read it from an ARN
        for key in _ARN_KEYS:
            parts = str(data.get(key) or "").split(":")
            if len(parts) > 4 and parts[4].isdigit():
                account = parts[4]
                break
    return {"region": data.get("region"), "prefix": data.get("prefix"), "account_id": account}


def unusable_reason(state: State) -> str | None:
    """Why this state file cannot be relied on to say where the kit is deployed, or None.

    Two cases, treated the same everywhere: the file could not be read at all; or it names
    resources (a runtime id, a bucket, ...) but not the Region, the prefix and the account
    they are in. Acting on either from whatever Region the shell happens to export is how a
    live deploy in another Region lost its bucket and role in the second review.
    """
    if state.damaged:
        return f"{state.path.name} could not be read ({state.damaged})"
    named = [key for key in RESOURCE_KEYS if state.data.get(key)]
    if not named:
        return None
    place = recorded_place(state) or {}
    missing = [label for key, label in (("region", "the Region"), ("prefix", "the name prefix"),
                                        ("account_id", "the account"))
               if not place.get(key)]
    if missing:
        return (f"{state.path.name} names resources ({', '.join(named[:4])}) but does not record "
                f"{', '.join(missing)} they are in")
    return None


def stale_damaged_files(state: State) -> list[str]:
    """Names of state files that the first version of this kit set aside as damaged
    (.state.json.damaged-...). One of them may be the only record of a live deploy."""
    try:
        return sorted(p.name for p in state.path.parent.glob(state.path.name + ".damaged-*"))
    except OSError:
        return []


def explain_unusable_state(reason: str, out: Callable[[str], None], script: str) -> None:
    """The STOPPED message for a state file that cannot be used. Nothing is done to the file."""
    out(f"STOPPED: {reason}. This script did nothing.")
    out("  The file was left exactly as it is. No script in this kit moves, renames, deletes or "
        "rewrites a state file it cannot use.")
    out("  Open it in a text editor: it may still show the Region and the name prefix of the deploy.")
    out("  To tear down by name in a place you name yourself, without relying on the file:")
    out("      python 90_teardown.py --region <Region> --prefix <prefix>")
    out("  That deletes what carries this kit's names in that one Region and leaves the file where it is.")
    out("  99_verify_clean.py stays INCOMPLETE while the file is in this state. When you have torn "
        "down and checked every Region you used, move the file out of the kit folder yourself.")
    if script not in {"90_teardown.py", "99_verify_clean.py"}:
        out(f"  {script} cannot run until then.")


def record_place(state: State, cfg: "Config", account: str) -> None:
    """Write the place of this deploy before the first resource is created."""
    state.set(region=cfg.region, prefix=cfg.prefix, account_id=account)


def describe_place(region: str | None, prefix: str | None, account: str | None) -> str:
    return f"account {mask_account(account)}, Region {region}, prefix {prefix}"


def check_place(state: State, cfg: "Config", account: str | None, out: Callable[[str], None],
                script: str, dry_run: bool = False) -> bool:
    """Compare the recorded deploy with the settings and the identity in use. False means STOP.

    Rule shared by all three kits: a script that reads .state.json must not act on a Region,
    a prefix or an account other than the one the file records. In --dry-run no AWS call is
    made, so the account cannot be known and only Region and prefix are compared.
    A file that cannot be read, or that names resources without saying where they are, also
    means STOP (see unusable_reason): it is never set aside and never guessed around.
    """
    reason = unusable_reason(state)
    if reason:
        explain_unusable_state(reason, out, script)
        return False
    place = recorded_place(state)
    if place is None:
        return True
    problems: list[str] = []
    if place["region"] and place["region"] != cfg.region:
        problems.append(f"Region: .state.json records {place['region']}, the setting in use is {cfg.region}")
    if place["prefix"] and place["prefix"] != cfg.prefix:
        problems.append(f"name prefix: .state.json records {place['prefix']}, the setting in use is {cfg.prefix}")
    if not dry_run and account and place["account_id"] and place["account_id"] != account:
        same_tail = place["account_id"][-4:] == str(account)[-4:]
        problems.append(
            f"account: .state.json records {mask_account(place['account_id'])}, you are signed in to "
            f"{mask_account(account)}" + (" (a different account that ends in the same four digits)"
                                          if same_tail else ""))
    if not problems:
        if dry_run and place["account_id"]:
            out("DRY-RUN  the account was not compared with .state.json: a dry run makes no AWS call")
        return True
    out("STOPPED: .state.json was written by a deploy somewhere else, so this script did nothing.")
    for problem in problems:
        out(f"  {problem}")
    out("  Settings come from the environment first and config.env second: an exported AWS_REGION "
        "overrides config.env.")
    out("  Check with:  echo $AWS_REGION $KIT_PREFIX ; aws sts get-caller-identity")
    out("  Nothing was created, changed or deleted, and .state.json was not touched.")
    out("  To act on the recorded deploy, sign in to that account and run:")
    out(f"      AWS_REGION={place['region'] or cfg.region} KIT_PREFIX={place['prefix'] or cfg.prefix} "
        f"python {script}")
    return False


def history_places(state: State) -> list[dict]:
    """Every place named by a finished deploy in .state.json's history, oldest first, no repeats."""
    places: list[dict] = []
    for entry in state.get("history", []) or []:
        if not isinstance(entry, dict):
            continue
        place = {key: entry.get(key) for key in PLACE_KEYS}
        if any(place.values()) and place not in places:
            places.append(place)
    return places


def session_cost_bounds(idle_s: int, lifetime_s: int, version: str = "V1") -> dict:
    """What one session can cost if it is never stopped. Arithmetic only, from the list rates.

    idle:    the session is forgotten and does nothing: IDLE_GB_ASSUMED of memory, no CPU,
             for the idle timeout.
    ceiling: the session is busy at the per-session maximum (2 vCPU and 8 GB) for the whole
             maximum lifetime. Nothing can cost more than this per session.
    """
    cpu_rate, mem_rate = RUNTIME_RATES[version]
    return {
        "idle": idle_s / 3600 * IDLE_GB_ASSUMED * mem_rate,
        "ceiling": lifetime_s / 3600 * (SESSION_MAX_VCPU * cpu_rate + SESSION_MAX_GB * mem_rate),
    }


def unstopped_session_lines(idle_s: int, lifetime_s: int) -> list[str]:
    lines = [f"If a session is never stopped (this runtime: idle timeout {idle_s} s, maximum "
             f"lifetime {lifetime_s} s):"]
    for version in ("V1", "V2"):
        bounds = session_cost_bounds(idle_s, lifetime_s, version)
        lines.append(f"  {version}: about ${bounds['idle']:.4f} if it only sits idle at "
                     f"{IDLE_GB_ASSUMED} GB until the idle timeout; at most ${bounds['ceiling']:.3f} "
                     f"if it stays busy at {SESSION_MAX_VCPU} vCPU and {SESSION_MAX_GB} GB for the "
                     "whole lifetime.")
    return lines


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


# --------------------------------------------------------------------------
# the one door to AWS
# --------------------------------------------------------------------------
class DryRunResult(dict):
    """Marks a value that came from --dry-run, not from AWS."""


class Aws:
    """Every AWS call in this kit goes through call().

    client_factory lets the tests hand in botocore Stubber clients.
    """

    def __init__(self, region: str, dry_run: bool = False,
                 client_factory: Callable[[str], Any] | None = None,
                 out: Callable[[str], None] = print):
        self.region = region
        self.dry_run = dry_run
        self._client_factory = client_factory
        self._clients: dict[tuple[str, int], Any] = {}
        self._models: dict[str, Any] = {}
        self._out = out
        self.planned: list[tuple[str, str, dict]] = []

    # ---- offline parameter check against the SDK's own service model ----
    def _operation_model(self, service: str, operation: str):
        import botocore.session
        from botocore import xform_name

        if service not in self._models:
            model = botocore.session.get_session().get_service_model(service)
            self._models[service] = (model, {xform_name(n): n for n in model.operation_names})
        model, names = self._models[service]
        if operation not in names:
            raise ValueError(f"the installed AWS SDK has no operation {service}.{operation}")
        return model.operation_model(names[operation])

    def validate(self, service: str, operation: str, params: dict) -> None:
        from botocore.validate import validate_parameters

        op = self._operation_model(service, operation)
        if op.input_shape is not None:
            validate_parameters(params, op.input_shape)
        elif params:
            raise ValueError(f"{service}.{operation} takes no parameters")

    def client(self, service: str, attempts: int = 3):
        """attempts is the total number of tries, the first one included. 1 means no retry."""
        key = (service, attempts)
        if key not in self._clients:
            if self._client_factory is not None:
                self._clients[key] = self._client_factory(service)
            else:
                import boto3
                from botocore.config import Config as BotoConfig

                self._clients[key] = boto3.client(
                    service,
                    region_name=self.region,
                    config=BotoConfig(
                        # botocore: "total_max_attempts" counts the first try. The other
                        # key, "max_attempts", counts retries only (so 1 would mean 2 tries),
                        # which a test caught on 2026-10-07.
                        retries={"total_max_attempts": attempts, "mode": "standard"},
                        connect_timeout=10,
                        read_timeout=300,
                        user_agent_extra="aws-kits-kit-c",
                    ),
                )
        return self._clients[key]

    def warm(self, service: str, operation: str, attempts: int = 3) -> None:
        """Do the one-off client-side work now: load the service definition and build the
        client. A script that times a call uses this first so the timing does not include it."""
        self._operation_model(service, operation)
        if not self.dry_run:
            self.client(service, attempts)

    def call(self, service: str, operation: str, dry_result: dict | None = None,
             single_attempt: bool = False, **params: Any):
        """Make one AWS call, or in --dry-run print it and return dry_result.

        single_attempt=True sends the request exactly once, with no automatic retry. Used
        where a silent retry would be wrong: a timed call, or a call that runs the agent.
        """
        self.validate(service, operation, params)
        if self.dry_run:
            self.planned.append((service, operation, params))
            # redact(): a runtime ARN read from .state.json carries the account id
            self._out(redact(f"DRY-RUN  would call {service}.{operation}({_compact(params)})"))
            return DryRunResult(dry_result or {})
        client = self.client(service, 1 if single_attempt else 3)
        return getattr(client, operation)(**params)

    def error_code(self, exc: Exception) -> str:
        response = getattr(exc, "response", None) or {}
        return (response.get("Error") or {}).get("Code", "")


def _compact(params: dict, limit: int = 600) -> str:
    def default(value: Any) -> str:
        if isinstance(value, (bytes, bytearray)):
            return f"<{len(value)} bytes>"
        return str(value)

    text = json.dumps(params, default=default, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def is_not_found(exc: Exception) -> bool:
    code = ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code", "")
    return code in {
        "ResourceNotFoundException", "NoSuchEntity", "NoSuchBucket", "NoSuchKey", "404",
        "NotFound", "NoSuchEntityException",
    }


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------
def make_parser(description: str, bills: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the AWS calls this script would make and make none",
    )
    if bills:
        parser.add_argument(
            "--i-understand-this-bills", action="store_true", dest="bills_ok",
            help="required: this script creates or uses something AWS charges for",
        )
    return parser


def confirm_billing(args: argparse.Namespace, price_lines: list[str],
                    out: Callable[[str], None] = print) -> bool:
    """Print the expected prices. Return False when the script must stop."""
    out("What this step is expected to cost:")
    for line in price_lines:
        out(f"  {line}")
    if getattr(args, "dry_run", False):
        out("--dry-run: nothing will be created and nothing will bill.")
        return True
    if not getattr(args, "bills_ok", False):
        out("")
        out("Stopped. Nothing was created. Re-run with --i-understand-this-bills to proceed,")
        out("or with --dry-run to see the calls first.")
        return False
    return True


def mask_account(account_id: str) -> str:
    """Show only the last four digits, so pasted output does not carry the account id."""
    account_id = str(account_id or "")
    return ("*" * 8 + account_id[-4:]) if len(account_id) >= 4 else "*" * 12


_TWELVE_DIGITS = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")


def redact(text: Any) -> str:
    """A line as it may be printed: every 12-digit number standing by itself is shown as eight
    stars and its last four digits. An AWS account id is 12 digits, and it reaches the screen
    in places no script chose: the text of an AccessDenied answer names the caller's ARN, and
    a runtime ARN read back from .state.json sits in the parameters a dry run prints (review
    round 4: both were printed in full). The dry-run placeholder 000000000000 is left as it is."""
    return _TWELVE_DIGITS.sub(
        lambda m: m.group(0) if m.group(0) == DRY_ACCOUNT else mask_account(m.group(0)), str(text))


def redacting(out: Callable[[str], None]) -> Callable[[str], None]:
    """Wrap a print function so that every line goes through redact(). The main() of 30, 40,
    50, 60, 90 and 99 does this to its `out` first, so no line those scripts print carries a
    full account id. Until review round 5 (F13) this said "each script", and only 90 and 99
    did it: 60_read_usage.py --show-logs printed an ARN with the account id in full. The
    other scripts (00, 10, 12, 20 and the optional gateway's) are not wrapped; 00_check.py
    masks the one account id it prints itself."""
    if getattr(out, "_redacts", False):
        return out

    def redacted(line: Any = "") -> None:
        out(redact(line))

    redacted._redacts = True  # type: ignore[attr-defined]
    return redacted


def explain_aws_error(exc: Exception, out: Callable[[str], None] = print) -> int:
    """One readable line for the common failures. Returns an exit code."""
    name = type(exc).__name__
    if name in {"NoCredentialsError", "PartialCredentialsError", "NoRegionError",
                "ProfileNotFound", "CredentialRetrievalError"}:
        out(redact(f"No usable AWS credentials or Region: {exc}"))
        out("Sign in first (see README section 3), or use --dry-run.")
        return 2
    response = getattr(exc, "response", None)
    if response:
        err = response.get("Error", {})
        out(redact(f"AWS returned an error: {err.get('Code')}: {err.get('Message')}"))
        return 1
    out(redact(f"{name}: {exc}"))
    return 1


def error_text(exc: Exception) -> str:
    """'<Code>: <Message>' for an AWS error, '<Type>: <text>' for anything else, with account
    ids masked. botocore names an error class after its code, so printing the class name and
    the code gave "RuntimeClientError: RuntimeClientError" and dropped the one part that says
    what went wrong (review round 4, emulator finding 3)."""
    err = (getattr(exc, "response", None) or {}).get("Error") or {}
    if err.get("Code"):
        message = " ".join(str(err.get("Message") or "").split())
        return redact(f"{err['Code']}: {message[:400]}" if message else str(err["Code"]))
    return redact(f"{type(exc).__name__}: {' '.join(str(exc).split())[:400]}")


def sleep(seconds: float) -> None:
    """Wrapped so tests can replace it."""
    time.sleep(seconds)


def monotonic() -> float:
    """Wrapped so tests can replace it."""
    return time.monotonic()


def elapsed_line(what: str, since: float) -> str:
    """'<what>: 3.2 minutes (192 s) after ..., at 2026-10-07T12:00:00Z (UTC)'. For the rows of
    RESULTS_TEMPLATE.md that ask for a duration: the script prints it, nobody times it by hand."""
    seconds = max(monotonic() - since, 0.0)
    return f"{what}: {seconds / 60:.1f} minutes ({seconds:.0f} s), at {utc_now_iso()} (UTC)"


def wait_until(check: Callable[[], Any], *, timeout_s: float, interval_s: float,
               what: str, dry_run: bool, out: Callable[[str], None] = print) -> Any:
    """Poll check() until it returns something truthy. In --dry-run, call it once.

    The wait ends when the time slept adds up to timeout_s, or when the clock says timeout_s
    has passed, whichever comes first, so it also ends where sleeping is switched off.
    """
    if dry_run:
        check()
        out(f"DRY-RUN  would poll every {interval_s:.0f}s for up to {timeout_s:.0f}s until {what}")
        return None
    deadline = monotonic() + timeout_s
    slept = 0.0
    while True:
        result = check()
        if result:
            return result
        if monotonic() >= deadline or slept >= timeout_s:
            raise TimeoutError(f"timed out after {timeout_s:.0f}s waiting until {what}")
        sleep(interval_s)
        slept += interval_s


def base_model_id(model_id: str) -> str:
    """us.amazon.nova-micro-v1:0 -> amazon.nova-micro-v1:0. A plain model id is unchanged."""
    head, _, rest = model_id.partition(".")
    if head in {"us", "eu", "apac", "jp", "au", "ca", "global", "us-gov"} and rest:
        return rest
    return model_id


def is_inference_profile_id(model_id: str) -> bool:
    return base_model_id(model_id) != model_id


def model_token_price(model_id: str, region: str) -> tuple[float, float, str] | None:
    """(USD per 1M input tokens, USD per 1M output tokens, which price) for a model id, or
    None when this kit holds no price for it. A global. inference profile has its own price;
    a plain id or a us. profile pays the geo price in the three Regions listed. Every other
    profile prefix, model or Region: no price, look it up."""
    head, _, rest = model_id.partition(".")
    table = MODEL_USD_PER_1M_TOKENS.get(base_model_id(model_id))
    if not table or region not in MODEL_PRICE_REGIONS:
        return None
    if head == "global" and rest:
        kind = "global"
    elif head == "us" or base_model_id(model_id) == model_id:
        kind = "geo"
    else:
        return None
    if kind not in table:
        return None
    label = ("the global cross-Region price" if kind == "global"
             else "the geo cross-Region and in-Region price")
    return table[kind][0], table[kind][1], label


def script_main(main: Callable[[list[str] | None], int]) -> None:
    try:
        code = main(None)
    except ConfigError as exc:
        print(f"Configuration problem: {exc}")
        code = 2
    except KeyboardInterrupt:
        print("Interrupted.")
        code = 130
    sys.exit(code)
