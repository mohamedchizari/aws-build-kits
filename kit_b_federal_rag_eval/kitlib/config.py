"""Configuration, resource names and the state file.

Settings come from, in order of priority: real environment variables, then
`config.env` in the kit folder (copy `config.example.env`), then the defaults
below. No secrets belong in any of these files.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent

# --- The corpus is pinned to one commit of the OMB repository -----------------
OMB_REPO = "ombegov/2025-Federal-Agency-AI-Use-Case-Inventory"
OMB_COMMIT = "06c7ebeef5b376524211042bd9673b2a7fefd3e3"  # commit dated 2026-05-14, read 2026-10-07
OMB_CSV_PATH = "Data/2025_individually_reported_AI_use_cases.csv"
OMB_CSV_SHA256 = "a62721202ca4b110ce3c53ffdb688d05ad27a35971a7afda4f1179b2493e31d0"
OMB_CSV_ROWS = 3611
OMB_CSV_URL = f"https://raw.githubusercontent.com/{OMB_REPO}/{OMB_COMMIT}/{OMB_CSV_PATH}"

TAG_KEY = "project"
TAG_VALUE = "aws-kits"

# Regions where the Managed Knowledge Base is listed as supported.
# DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-regions.html (read 2026-10-07)
MANAGED_KB_REGIONS = (
    "us-east-1", "us-west-2", "eu-west-1", "eu-west-2", "eu-central-1",
    "ap-northeast-1", "ap-southeast-2", "us-gov-west-1",
)

DEFAULTS = {
    "AWS_REGION": "us-east-1",
    "KIT_PREFIX": "kitdemo",
    # "managed" = Bedrock Managed Knowledge Base (no vector store in your account).
    # "s3vectors" = customer-managed knowledge base on Amazon S3 Vectors (fallback).
    "KB_TYPE": "managed",
    # Model ids. DOC: model cards under
    # https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html (read 2026-10-07)
    "GEN_MODEL_ID": "amazon.nova-lite-v1:0",
    "JUDGE_MODEL_ID": "amazon.nova-pro-v1:0",
    "EMBED_MODEL_ID": "amazon.titan-embed-text-v2:0",  # used only when KB_TYPE=s3vectors
    "EMBED_DIMENSIONS": "1024",
    "TOP_K": "5",
    "GROUNDING_THRESHOLD": "0.7",
    "RELEVANCE_THRESHOLD": "0.7",
    "CORPUS_SAMPLE_SIZE": "400",
    "SEED": "20261007",
}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name: str, env: dict[str, str] | None = None) -> str:
    """Return one setting: environment, then config.env, then the default."""
    env = os.environ if env is None else env
    if env.get(name):
        return env[name]
    file_values = _read_env_file(config_file())
    if file_values.get(name):
        return file_values[name]
    return DEFAULTS.get(name, "")


def config_file() -> Path:
    # KIT_CONFIG_FILE exists so the tests never read your own config.env.
    return Path(os.environ.get("KIT_CONFIG_FILE") or (KIT_DIR / "config.env"))


def build_dir() -> Path:
    return Path(os.environ.get("KIT_BUILD_DIR") or (KIT_DIR / "build"))


def results_dir() -> Path:
    return Path(os.environ.get("KIT_RESULTS_DIR") or (KIT_DIR / "results"))


def state_path() -> Path:
    return Path(os.environ.get("KIT_STATE_FILE") or (KIT_DIR / ".state.json"))


def shown_path(path: Path) -> str:
    """A path for the screen: inside the kit folder its name there, inside the home folder with "~" in front.

    A full local path can carry a user name (round 4). The owner still finds the file from either form.
    """
    try:
        return str(Path(path).resolve().relative_to(KIT_DIR))
    except ValueError:
        pass
    try:
        return "~/" + Path(path).resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, RuntimeError):
        return str(path)


@dataclass(frozen=True)
class Settings:
    region: str
    prefix: str
    kb_type: str
    gen_model_id: str
    judge_model_id: str
    embed_model_id: str
    embed_dimensions: int
    top_k: int
    grounding_threshold: float
    relevance_threshold: float
    corpus_sample_size: int
    seed: int

    @staticmethod
    def load(env: dict[str, str] | None = None) -> "Settings":
        s = Settings(
            region=setting("AWS_REGION", env),
            prefix=setting("KIT_PREFIX", env),
            kb_type=setting("KB_TYPE", env).lower(),
            gen_model_id=setting("GEN_MODEL_ID", env),
            judge_model_id=setting("JUDGE_MODEL_ID", env),
            embed_model_id=setting("EMBED_MODEL_ID", env),
            embed_dimensions=int(setting("EMBED_DIMENSIONS", env)),
            top_k=int(setting("TOP_K", env)),
            grounding_threshold=float(setting("GROUNDING_THRESHOLD", env)),
            relevance_threshold=float(setting("RELEVANCE_THRESHOLD", env)),
            corpus_sample_size=int(setting("CORPUS_SAMPLE_SIZE", env)),
            seed=int(setting("SEED", env)),
        )
        s.validate()
        return s

    def validate(self) -> None:
        import re

        if self.kb_type not in ("managed", "s3vectors"):
            raise SystemExit(f"KB_TYPE must be 'managed' or 's3vectors', got {self.kb_type!r}")
        # Lower-case letters, digits and hyphens only, so one prefix is legal in
        # every name this kit builds (S3 bucket, vector bucket, IAM role, KB, guardrail).
        if not re.fullmatch(r"[a-z](?:-?[a-z0-9]){2,15}", self.prefix):
            raise SystemExit(
                "KIT_PREFIX must be 3 to 16 characters: lower-case letters, digits, single hyphens; "
                f"start with a letter and not end with a hyphen. Got {self.prefix!r}"
            )
        if not 1 <= self.top_k <= 100:
            raise SystemExit("TOP_K must be between 1 and 100")
        for label, value in (("GROUNDING_THRESHOLD", self.grounding_threshold),
                             ("RELEVANCE_THRESHOLD", self.relevance_threshold)):
            # DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html
            # (read 2026-10-07): valid threshold range is 0 to 0.99.
            if not 0 <= value <= 0.99:
                raise SystemExit(f"{label} must be between 0 and 0.99")


@dataclass(frozen=True)
class Names:
    """Every resource name this kit creates, derived from prefix, account and Region.

    Because the names are deterministic, teardown and verification can find the
    resources again even if .state.json is lost.
    """
    prefix: str
    account_id: str
    region: str

    @property
    def stem(self) -> str:
        return f"{self.prefix}-fedrag"

    @property
    def bucket(self) -> str:  # S3 bucket names are global, so account and Region are in the name
        return f"{self.stem}-corpus-{self.account_id}-{self.region}"

    @property
    def corpus_prefix(self) -> str:
        return "corpus/"

    @property
    def role(self) -> str:
        return f"{self.stem}-kb-role-{self.region}"

    @property
    def role_policy(self) -> str:
        return f"{self.stem}-kb-access"

    @property
    def knowledge_base(self) -> str:
        return f"{self.stem}-kb"

    @property
    def data_source(self) -> str:
        return f"{self.stem}-s3-source"

    @property
    def guardrail(self) -> str:
        return f"{self.stem}-grounding"

    @property
    def vector_bucket(self) -> str:
        return f"{self.stem}-vectors"

    @property
    def vector_index(self) -> str:
        return f"{self.stem}-index"


def tags_map() -> dict[str, str]:
    return {TAG_KEY: TAG_VALUE}


def tags_list_lower() -> list[dict[str, str]]:
    return [{"key": TAG_KEY, "value": TAG_VALUE}]


def tags_list_upper() -> list[dict[str, str]]:
    return [{"Key": TAG_KEY, "Value": TAG_VALUE}]


# --- state file ---------------------------------------------------------------

class StopHere(Exception):
    """Raised to stop a script before it changes anything. The message is for the user."""


class StateFileDamaged(StopHere):
    """.state.json exists but cannot be read. No script deletes or overwrites such a file."""


def _read_state_file() -> tuple[str, dict, str]:
    """(status, state, problem). status: "absent", "damaged", "empty" or "ok".

    "empty" is a readable file that records no resource, no place and no finished teardown.
    A file that is not a JSON object (cut short, emptied, not text) is "damaged".
    """
    path = state_path()
    if not path.is_file():
        return "absent", {}, ""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return "damaged", {}, f"{type(exc).__name__}"
    try:
        state = json.loads(text)
    except ValueError as exc:
        return "damaged", {}, ("it is empty" if not text.strip() else f"it is not valid JSON ({exc})")
    if not isinstance(state, dict):
        return "damaged", {}, "it does not hold a record (a JSON object)"
    return ("ok" if state else "empty"), state, ""


def state_file_status() -> str:
    """"absent", "damaged", "empty" or "ok". Never raises."""
    return _read_state_file()[0]


def salvage_from_damaged_state() -> dict:
    """Region and prefix that can still be read in a damaged state file, as hints for the person.

    The bucket name is the first thing a deploy writes and holds both
    ("<prefix>-fedrag-corpus-<account>-<region>"). Nothing found: an empty dictionary.
    """
    import re

    try:
        text = state_path().read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return {}
    found: dict[str, str] = {}
    bucket = re.search(r"([a-z][a-z0-9-]{2,15})-fedrag-corpus-\d{12}-([a-z]{2}(?:-[a-z]+)+-\d)", text)
    if bucket:
        found.update(prefix=bucket.group(1), region=bucket.group(2), source="the bucket name in it")
    region = re.search(r'"region"\s*:\s*"([a-z]{2}(?:-[a-z]+)+-\d)"', text)
    prefix = re.search(r'"prefix"\s*:\s*"([a-z][a-z0-9-]{2,15})"', text)
    if region and prefix:
        found.update(prefix=prefix.group(1), region=region.group(1), source="the region and prefix lines in it")
    return found


def damaged_state_message(problem: str = "") -> str:
    """What to do about a state file that cannot be read. Every script prints this and stops."""
    problem = problem or _read_state_file()[2]
    hint = salvage_from_damaged_state()
    lines = [
        f"STOP: the state file {shown_path(state_path())} exists but cannot be read ({problem}).",
        "It may be the only record of where this kit was deployed. No script deletes or overwrites it,",
        "and nothing was changed in AWS or on disk. What to do:",
        "  1. Open the file in a text editor. Whatever is left of it may still show the Region and the prefix",
        "     (the bucket name is '<prefix>-fedrag-corpus-<account>-<Region>').",
    ]
    if hint:
        lines.append(f"     This script can still read in it: Region {hint['region']}, prefix '{hint['prefix']}' "
                     f"(from {hint['source']}).")
    command = (f"python 90_teardown.py --region {hint['region']} --prefix {hint['prefix']}" if hint
               else "python 90_teardown.py --region <Region> --prefix <prefix>")
    lines += [
        "  2. Tear down by naming the place yourself, once for every Region and prefix you deployed to:",
        f"       {command}",
        "     With both options given, the teardown acts on the kit's fixed names in that place, in the account",
        "     your credentials belong to, and leaves this file where it is.",
        "  3. Run python 99_verify_clean.py with AWS_REGION and KIT_PREFIX set to the same place. While this file",
        "     is in the folder the clean check reports what it finds but never says CLEAN.",
        "  4. When step 3 finds nothing in every place you used, move the file out of this folder yourself",
        "     (for example into your home folder) and run 99_verify_clean.py once more.",
    ]
    return "\n".join(lines)


def load_state() -> dict:
    """The record, or {} when there is no file. Raises StateFileDamaged when the file cannot be read."""
    status, state, problem = _read_state_file()
    if status == "damaged":
        raise StateFileDamaged(damaged_state_message(problem))
    return state


def save_state(state: dict) -> None:
    """Write the state file in one step, so a crash cannot leave half a record behind.

    A file that is there but cannot be read is never replaced: StateFileDamaged is raised instead.
    """
    status, _, problem = _read_state_file()
    if status == "damaged":
        raise StateFileDamaged(damaged_state_message(problem))
    path = state_path()
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def update_state(**changes) -> dict:
    """Merge changes into the state file at once, so a crash still leaves a trail."""
    state = load_state()
    for key, value in changes.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value
    save_state(state)
    return state
