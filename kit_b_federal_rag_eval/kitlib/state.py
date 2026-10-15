"""The state file: what was deployed, where, and under which account.

`.state.json` is local and git-ignored. It holds three things:

  * the place of the deploy: AWS account id, Region and name prefix;
  * the names and ids of the resources created there;
  * a history: one entry for every place whose resources were all deleted, with
    the time the clean check last found that place clean.

The rule every script follows (the same rule in all three kits and the shared
audit): compare the recorded account, Region and prefix with the current
settings and the current caller identity, and stop on any difference. A script
that carried on would act in one place while the record describes another, and
that is how a teardown reports success having deleted nothing.

Nothing here calls AWS.
"""
from __future__ import annotations

import datetime

from . import config
from .redact import account_label

PLACE_KEYS = ("account_id", "region", "prefix")

# The resources this kit creates, and the other keys that describe each of them.
RESOURCE_KEYS = {
    "bucket": ("objects_uploaded", "corpus_fingerprint", "corpus_documents", "stale_objects_removed"),
    "role_name": ("role_arn",),
    "vector_bucket": ("vector_bucket_arn",),
    "vector_index": ("vector_index_arn",),
    "knowledge_base_id": ("knowledge_base_arn", "knowledge_base_name", "knowledge_base_created_at", "ingestion"),
    "data_source_id": ("data_source_name",),
    "guardrail_id": ("guardrail_arn", "guardrail_name", "guardrail_version",
                     "grounding_threshold", "relevance_threshold"),
}
LABELS = {
    "bucket": "S3 bucket", "role_name": "IAM role", "vector_bucket": "S3 vector bucket",
    "vector_index": "S3 vector index", "knowledge_base_id": "knowledge base",
    "data_source_id": "data source", "guardrail_id": "guardrail",
}


# Defined in kitlib.config so that the functions that read the state file can raise it too.
StopHere = config.StopHere
StateFileDamaged = config.StateFileDamaged

# Written as the id of the guardrail, of the knowledge base and (round 4) of the data source before
# the call that creates it, when the real id is not known yet. A crash right after that call then
# still leaves a record of the place and of the resource's fixed name, and teardown finds it by
# that name.
PENDING = "not-known-yet"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_between(earlier: str | None, later: str | None) -> float | None:
    """Hours from one now()-style stamp to another. None when either is missing or unreadable."""
    try:
        start = datetime.datetime.strptime(earlier or "", "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.datetime.strptime(later or "", "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return (end - start).total_seconds() / 3600.0


def names_place(state: dict, where: dict) -> bool:
    """Does the state file, in its record or its history, name this account, Region and prefix?"""
    if has_record(state) and same_place(recorded_place(state), where):
        return True
    return any(same_place(entry, where) for entry in state.get("history", []))


def recorded_resources(state: dict) -> dict:
    """{key: value} for every resource the state file still says exists."""
    return {key: state[key] for key in RESOURCE_KEYS if state.get(key)}


def has_record(state: dict) -> bool:
    return bool(recorded_resources(state))


def place(account_id: str | None, region: str, prefix: str) -> dict:
    return {"account_id": account_id, "region": region, "prefix": prefix}


def recorded_place(state: dict) -> dict:
    return {key: state.get(key) for key in PLACE_KEYS}


def describe(where: dict) -> str:
    """'account ********3333, Region us-east-1, prefix 'kitdemo''. Never the full account id."""
    return (f"account {account_label(where.get('account_id'))}, Region {where.get('region') or 'unknown'}, "
            f"prefix '{where.get('prefix') or 'unknown'}'")


def how_to_get_there(where: dict) -> str:
    return (f"AWS_REGION={where.get('region')} KIT_PREFIX={where.get('prefix')}, signed in to account "
            f"{account_label(where.get('account_id'))}")


def differences(state: dict, settings: config.Settings, account_id: str | None) -> list[str]:
    """Why the recorded deploy is not where this run would act. Empty when it is the same place.

    account_id None means the caller identity is not known (a dry run): the account is then
    not compared, and the caller should say so.
    """
    if not has_record(state):
        return []
    recorded = recorded_place(state)
    lines = []
    missing = [key for key in PLACE_KEYS if not recorded[key]]
    if missing:
        lines.append(f".state.json lists resources but does not record their {', '.join(missing)}, so this "
                     "script cannot tell whether it is looking at the right place. Add the missing value(s) "
                     "to the file by hand if you know them.")
    if recorded["region"] and recorded["region"] != settings.region:
        lines.append(f".state.json records a deploy in Region {recorded['region']}, but the Region in use now "
                     f"is {settings.region}. An AWS_REGION exported in your shell overrides config.env: "
                     "check `echo $AWS_REGION`.")
    if recorded["prefix"] and recorded["prefix"] != settings.prefix:
        lines.append(f".state.json records the name prefix '{recorded['prefix']}', but KIT_PREFIX is now "
                     f"'{settings.prefix}'. A KIT_PREFIX exported in your shell overrides config.env.")
    if account_id and recorded["account_id"] and str(recorded["account_id"]) != str(account_id):
        lines.append(f".state.json records account {account_label(recorded['account_id'])}, but the credentials "
                     f"in use now belong to account {account_label(account_id)}. Check your AWS profile.")
    return lines


def require_same_place(state: dict, settings: config.Settings, account_id: str | None, doing: str) -> None:
    """Raise StopHere unless the recorded deploy is in the account, Region and prefix in use now."""
    lines = differences(state, settings, account_id)
    if not lines:
        return
    recorded = recorded_place(state)
    resources = ", ".join(LABELS[key] for key in recorded_resources(state))
    text = [f"STOP: {doing} was not started, and nothing was changed."]
    text += [f"  - {line}" for line in lines]
    text += [
        f"The record still lists: {resources}.",
        f"To act on the recorded deploy, run with {how_to_get_there(recorded)}.",
        "To start somewhere else instead, first remove the recorded deploy there: python 90_teardown.py",
        "(.state.json was left exactly as it was.)",
    ]
    raise StopHere("\n".join(text))


def start_record(state: dict, settings: config.Settings, account_id: str) -> dict:
    """The place keys to write when a deploy begins. Call require_same_place first."""
    return {"account_id": account_id, "region": settings.region, "prefix": settings.prefix}


def forget(state: dict, confirmed_gone: list[str]) -> dict:
    """Return a copy of the state without the resources that were deleted or seen to be absent.

    When no resource is left, the place moves to the history so the clean check knows
    it still has to look there.
    """
    new = dict(state)
    for key in confirmed_gone:
        new.pop(key, None)
        for extra in RESOURCE_KEYS[key]:
            new.pop(extra, None)
    if has_record(state) and not has_record(new):
        entry = dict(recorded_place(state), torn_down_at=now())
        history = [h for h in new.get("history", [])
                   if not (same_place(h, entry) and not h.get("verified_clean_at"))]
        new["history"] = history + [entry]
        for key in PLACE_KEYS + ("kb_type",):
            new.pop(key, None)
    return new


def same_place(a: dict, b: dict) -> bool:
    return all(str(a.get(key)) == str(b.get(key)) for key in PLACE_KEYS)


def places_not_checked(state: dict, checked: dict) -> list[dict]:
    """Every place the state file or its history names that the clean check did not just look at.

    A history entry counts as checked once a clean check found it clean after its teardown.
    """
    out = []
    if has_record(state) and not same_place(recorded_place(state), checked):
        out.append(dict(recorded_place(state), why="resources are still recorded there"))
    for entry in state.get("history", []):
        if entry.get("verified_clean_at") or same_place(entry, checked):
            continue
        if not any(same_place(entry, seen) for seen in out):
            out.append(dict({key: entry.get(key) for key in PLACE_KEYS},
                            why=f"torn down {entry.get('torn_down_at', 'earlier')}, not yet checked"))
    return out


def mark_checked_clean(state: dict, checked: dict) -> dict:
    """Stamp the history entries of the place that was just found clean."""
    new = dict(state)
    stamp = now()
    new["history"] = [dict(entry, verified_clean_at=stamp)
                      if same_place(entry, checked) and not entry.get("verified_clean_at") else entry
                      for entry in state.get("history", [])]
    return new
