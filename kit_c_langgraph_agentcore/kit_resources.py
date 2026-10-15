"""Find and delete everything this kit can create. Used by 90_teardown.py,
99_verify_clean.py and optional_gateway/90_teardown_gateway.py.

discover() does not trust .state.json. It lists by name prefix in every
service the kit touches and, separately, by the tags project=aws-kits and
kit=kit-c, so a lost state file does not hide a resource.

The callers decide WHERE: each compares the Region, prefix and account that
.state.json records with the ones in use (kitlib.check_place) before anything
here runs. confirm_recorded_absent() then asks AWS by id for the runtime and
gateway the file names, so a record is cleared only on a positive "not found"
(when that call fails another way, the record is kept: review round 5, F1).

Two kinds of resource are not tied to one Region, and deleting them from the
wrong Region broke a live deploy in the second review (round 2, BLOCKER 1):
  S3 buckets   ListBuckets shows the buckets of every Region. Teardown deletes
               only the bucket named exactly for this account and this Region
               (<prefix>-kitc-code-<account>-<region>). Any other bucket with
               the kit's name is reported with its Region and left alone.
  IAM roles    one role name serves every Region. A role is deleted only when
               no bucket of this kit exists for another Region and no runtime
               or gateway of this kit is found in any other Region this code
               can name (the Regions in the role's own trust policy and in
               .state.json's history). Otherwise it is reported and kept.

What the kit can create, and how each is found:
  AgentCore runtime          list_agent_runtimes, name starts with <prefix>_kitc_
  AgentCore gateway, targets list_gateways, name starts with <prefix>-kitc-   (optional step)
  workload identities        list_workload_identities, name starts with either of the above
  IAM roles                  list_roles, name starts with <prefix>-kitc-
  S3 bucket and objects      list_buckets, name starts with <prefix>-kitc-
  log groups                 describe_log_groups, two name prefixes
  log deliveries, sources,   describe_deliveries / _sources / _destinations,
    destinations             name starts with <prefix>-kitc-
  anything tagged            resourcegroupstaggingapi get_resources
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Callable

import kitlib

CONTROL = "bedrock-agentcore-control"


def _pages(aws: kitlib.Aws, service: str, operation: str, items_key: str,
           token_in: str = "nextToken", token_out: str = "nextToken", **params: Any) -> list:
    items: list = []
    token = None
    while True:
        call_params = dict(params)
        if token:
            call_params[token_in] = token
        page = aws.call(service, operation, dry_result={items_key: []}, **call_params)
        items += page.get(items_key, []) or []
        token = page.get(token_out)
        if not token:
            return items


def discover(aws: kitlib.Aws, cfg: kitlib.Config, out: Callable[[str], None] = print) -> dict:
    """Read-only. Returns every resource that matches this kit's prefix or tags."""
    name_prefix = f"{cfg.prefix}-kitc-"
    runtime_prefix = f"{cfg.prefix.replace('-', '_')}_kitc_"
    found: dict[str, list] = {}

    # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html (read 2026-10-07)
    runtimes = _pages(aws, CONTROL, "list_agent_runtimes", "agentRuntimes", maxResults=100)
    found["runtimes"] = [
        {"id": r["agentRuntimeId"], "arn": r["agentRuntimeArn"], "name": r["agentRuntimeName"],
         "status": r.get("status")}
        for r in runtimes if r.get("agentRuntimeName", "").startswith(runtime_prefix)
    ]

    # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGateways.html (read 2026-10-07)
    gateways = _pages(aws, CONTROL, "list_gateways", "items", maxResults=100)
    found["gateways"] = []
    for g in gateways:
        if not g.get("name", "").startswith(name_prefix):
            continue
        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGatewayTargets.html (read 2026-10-07)
        targets = _pages(aws, CONTROL, "list_gateway_targets", "items",
                         gatewayIdentifier=g["gatewayId"], maxResults=100)
        found["gateways"].append({"id": g["gatewayId"], "name": g["name"], "status": g.get("status"),
                                  "targets": [{"id": t["targetId"], "name": t.get("name")}
                                              for t in targets]})

    # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListWorkloadIdentities.html (read 2026-10-07)
    identities = _pages(aws, CONTROL, "list_workload_identities", "workloadIdentities", maxResults=20)
    found["workload_identities"] = [
        {"name": w["name"], "arn": w.get("workloadIdentityArn")}
        for w in identities
        if w.get("name", "").startswith(runtime_prefix) or w.get("name", "").startswith(name_prefix)
    ]

    # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListRoles.html (read 2026-10-07)
    roles = _pages(aws, "iam", "list_roles", "Roles", token_in="Marker", token_out="Marker",
                   MaxItems=1000)
    found["roles"] = [{"name": r["RoleName"], "arn": r.get("Arn")}
                      for r in roles if r.get("RoleName", "").startswith(name_prefix)]

    # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListBuckets.html (read 2026-10-07)
    buckets = _pages(aws, "s3", "list_buckets", "Buckets", token_in="ContinuationToken",
                     token_out="ContinuationToken", Prefix=name_prefix, MaxBuckets=1000)
    # "BucketRegion" is in the response when the request carries a parameter, as this one does
    # (same page, read 2026-10-07). Where it is missing the Region is read from the name.
    found["buckets"] = [{"name": b["Name"], "region": b.get("BucketRegion") or _region_in_name(b["Name"])}
                        for b in buckets if b.get("Name", "").startswith(name_prefix)]

    found["log_groups"] = log_groups(aws, cfg)

    # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeDeliveries.html (read 2026-10-07)
    deliveries = _pages(aws, "logs", "describe_deliveries", "deliveries", limit=50)
    found["deliveries"] = [{"id": d["id"], "source": d.get("deliverySourceName")}
                           for d in deliveries
                           if (d.get("deliverySourceName") or "").startswith(name_prefix)]
    # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeDeliverySources.html (read 2026-10-07)
    sources = _pages(aws, "logs", "describe_delivery_sources", "deliverySources", limit=50)
    found["delivery_sources"] = [{"name": s["name"]} for s in sources
                                 if s.get("name", "").startswith(name_prefix)]
    # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeDeliveryDestinations.html (read 2026-10-07)
    destinations = _pages(aws, "logs", "describe_delivery_destinations", "deliveryDestinations",
                          limit=50)
    found["delivery_destinations"] = [{"name": d["name"]} for d in destinations
                                      if d.get("name", "").startswith(name_prefix)]

    # By tag, as a second net.
    # doc: https://docs.aws.amazon.com/resourcegroupstagging/latest/APIReference/API_GetResources.html (read 2026-10-07)
    # UNVERIFIED: which AgentCore resource types the Resource Groups Tagging API returns. The
    # by-name listings above do not depend on it.
    try:
        tagged = _pages(aws, "resourcegroupstaggingapi", "get_resources", "ResourceTagMappingList",
                        token_in="PaginationToken", token_out="PaginationToken",
                        TagFilters=[{"Key": k, "Values": [v]} for k, v in kitlib.TAGS.items()],
                        ResourcesPerPage=100)
        found["tagged"] = [{"arn": t["ResourceARN"]} for t in tagged]
        found["lookup_errors"] = []
    except Exception as exc:  # the tag lookup is a second net; do not let it hide the first
        reason = aws.error_code(exc) or type(exc).__name__
        out(f"[tags] the tag lookup failed ({reason}); the by-name results below still stand")
        found["tagged"] = []
        found["lookup_errors"] = [f"tag lookup failed: {reason}"]
    return found


def log_groups(aws: kitlib.Aws, cfg: kitlib.Config) -> list[dict]:
    """The log groups that carry this kit's names, listed now. 90_teardown.py lists them a
    second time after the runtime is gone: AgentCore creates the runtime's own group by
    itself, and one that appeared after the first listing used to be left behind while the
    script exited 0 (review round 4, m10)."""
    groups: list[dict] = []
    for prefix in (cfg.runtime_log_group_prefix,
                   f"/aws/vendedlogs/bedrock-agentcore/{cfg.prefix}-kitc-"):
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html (read 2026-10-07)
        listed = _pages(aws, "logs", "describe_log_groups", "logGroups", logGroupNamePrefix=prefix)
        groups += [{"name": g["logGroupName"], "stored_bytes": g.get("storedBytes")} for g in listed]
    return groups


_REGION_AT_END = re.compile(r"-([a-z]{2}(?:-[a-z]+)+-\d)$")


def _region_in_name(bucket_name: str) -> str | None:
    """The Region at the end of <prefix>-kitc-code-<account>-<region>, or None."""
    match = _REGION_AT_END.search(bucket_name)
    return match.group(1) if match else None


def other_buckets(found: dict, cfg: kitlib.Config, account: str) -> list[dict]:
    """Buckets that carry the kit's name but are not this account-and-Region's own bucket."""
    own = cfg.bucket_name(account)
    return [b for b in found.get("buckets", []) if b["name"] != own]


def hints(found: dict, cfg: kitlib.Config, account: str | None = None) -> list[str]:
    """One line per leftover that this Region-and-prefix run cannot remove, saying where it
    is and which command would remove it."""
    lines: list[str] = []
    seen_regions: set[str] = set()
    for bucket in found.get("buckets", []):
        region = bucket.get("region")
        if region and region != cfg.region and region not in seen_regions:
            seen_regions.add(region)
            shown = bucket["name"].replace(account, kitlib.mask_account(account)) if account else bucket["name"]
            lines.append(f"bucket {shown} is in Region {region}: this kit may be deployed there. "
                         f"Run: AWS_REGION={region} KIT_PREFIX={cfg.prefix} python 90_teardown.py")
    seen_prefixes: set[str] = set()
    for item in found.get("tagged", []):
        prefix = _prefix_in_arn(item.get("arn", ""))
        if prefix and prefix != cfg.prefix and prefix.replace("_", "-") != cfg.prefix \
                and prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            lines.append(f"a resource tagged for this kit is named with the prefix {prefix!r}, not "
                         f"{cfg.prefix!r}. Run: AWS_REGION={cfg.region} KIT_PREFIX={prefix.replace('_', '-')} "
                         "python 90_teardown.py")
    return lines


def _prefix_in_arn(arn: str) -> str | None:
    """The name prefix inside the ARN of a kit resource, or None when it cannot be read."""
    last = arn.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    for pattern in (r"^(.+?)_kitc_", r"^(.+?)-kitc-"):
        match = re.match(pattern, last)
        if match:
            return match.group(1)
    match = re.search(r"bedrock-agentcore/(.+?)-kitc-", arn)
    return match.group(1) if match else None


def count(found: dict) -> int:
    """Number of resources found. lookup_errors are not resources."""
    return sum(len(v) for k, v in found.items() if k != "lookup_errors")


def describe(found: dict, out: Callable[[str], None] = print, mask: str | None = None) -> None:
    labels = [
        ("runtimes", "AgentCore runtimes"), ("gateways", "AgentCore gateways"),
        ("workload_identities", "AgentCore workload identities"), ("roles", "IAM roles"),
        ("buckets", "S3 buckets"), ("log_groups", "CloudWatch log groups"),
        ("deliveries", "log deliveries"), ("delivery_sources", "log delivery sources"),
        ("delivery_destinations", "log delivery destinations"),
        ("tagged", "resources tagged project=aws-kits, kit=kit-c"),
    ]
    for key, label in labels:
        items = found.get(key, [])
        out(f"  {label}: {len(items)}")
        for item in items:
            text = item.get("name") or item.get("id") or item.get("arn") or str(item)
            if mask:
                text = text.replace(mask, kitlib.mask_account(mask))
            extra = f" ({item['status']})" if item.get("status") else ""
            if key == "buckets" and item.get("region"):
                extra += f" (Region {item['region']})"
            if item.get("targets"):
                extra += f", {len(item['targets'])} target(s)"
            out(f"    - {text}{extra}")


# --------------------------------------------------------------------------
# deletion
# --------------------------------------------------------------------------
def _try(aws: kitlib.Aws, out, label: str, service: str, operation: str, **params: Any) -> bool:
    try:
        aws.call(service, operation, **params)
        out(f"[delete] {label}")
        return True
    except Exception as exc:
        if kitlib.is_not_found(exc):
            out(f"[delete] {label}: already gone")
            return True
        out(f"[delete] {label}: FAILED ({kitlib.error_text(exc)})")
        return False


def stop_sessions(aws: kitlib.Aws, sessions: list[dict], runtime_arn: str | None, out) -> list[dict]:
    """Stop every session still recorded as open, and return the ones whose stop call failed.
    A session that already ended answers "not found", which counts as stopped.

    # UNVERIFIED: that deleting a runtime ends its open sessions at once. Until review round
    # 4 this function returned nothing and teardown said "finished without errors" after a
    # stop call had failed. The caller now tries the stop again once the runtime is gone and
    # says what an unstopped session can cost."""
    failed: list[dict] = []
    for s in sessions or []:
        if s.get("stopped") or not runtime_arn:
            continue
        # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_StopRuntimeSession.html (read 2026-10-07)
        if not _try(aws, out, f"stop session ...{s['session_id'][-8:]}", "bedrock-agentcore",
                    "stop_runtime_session", agentRuntimeArn=runtime_arn, runtimeSessionId=s["session_id"]):
            failed.append(s)
    return failed


def delete_deliveries(aws: kitlib.Aws, found: dict, out, deleted: set | None = None) -> bool:
    deleted = deleted if deleted is not None else set()
    ok = True
    for d in found.get("deliveries", []):
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteDelivery.html (read 2026-10-07)
        if _try(aws, out, f"log delivery {d['id']}", "logs", "delete_delivery", id=d["id"]):
            deleted.add(d["id"])
        else:
            ok = False
    for s in found.get("delivery_sources", []):
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteDeliverySource.html (read 2026-10-07)
        if _try(aws, out, f"log delivery source {s['name']}", "logs", "delete_delivery_source",
                name=s["name"]):
            deleted.add(s["name"])
        else:
            ok = False
    for d in found.get("delivery_destinations", []):
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteDeliveryDestination.html (read 2026-10-07)
        if _try(aws, out, f"log delivery destination {d['name']}", "logs",
                "delete_delivery_destination", name=d["name"]):
            deleted.add(d["name"])
        else:
            ok = False
    return ok


def _listed_ids(aws: kitlib.Aws, operation: str, items_key: str, id_key: str) -> set[str]:
    return {item[id_key] for item in _pages(aws, CONTROL, operation, items_key, maxResults=100)}


class DeleteFailed(RuntimeError):
    """AWS answered for a runtime or gateway by id: it exists, and its delete failed
    (DELETE_FAILED for a runtime, FAILED for a gateway)."""


def _is_gone(aws: kitlib.Aws, out, kind: str, identifier: str, listing_decides: bool = True) -> bool:
    """True when the runtime or gateway does not exist; False while it does. Raises when
    neither the get call nor the list call can say, and DeleteFailed when the get call
    answers that the delete failed.

    The get call answering "not found" is the normal proof. When it fails with any other
    error, the list call decides (review round 2, MAJOR 7): an id that the list does not
    contain is gone, an id that it does contain still exists. That is used only while
    waiting for a resource that the listing showed and this run deleted. For a resource
    that .state.json records and the listing did NOT show, listing_decides is False: the
    listing is the very thing that cannot be trusted there, so any error other than "not
    found" is raised and the record is kept (review round 5, F1: GetAgentRuntime refused,
    the listing silent, and both the teardown and the clean check said clean while the
    runtime still existed).
    # UNVERIFIED: the error code AgentCore gives for a runtime or gateway that does not
    # exist. ResourceNotFoundException is what the API pages document; this does not depend
    # on it being the only one.
    """
    get_op, id_param, list_op, list_key, id_key = {
        "runtime": ("get_agent_runtime", "agentRuntimeId", "list_agent_runtimes", "agentRuntimes",
                    "agentRuntimeId"),
        "gateway": ("get_gateway", "gatewayIdentifier", "list_gateways", "items", "gatewayId"),
    }[kind]
    try:
        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetAgentRuntime.html (read 2026-10-07)
        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetGateway.html (read 2026-10-07)
        info = aws.call(CONTROL, get_op, dry_result={"status": "DELETING"}, **{id_param: identifier})
    except Exception as exc:
        if kitlib.is_not_found(exc):
            return True
        if not listing_decides:
            raise
        code = aws.error_code(exc) or type(exc).__name__
        try:
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html (read 2026-10-07)
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGateways.html (read 2026-10-07)
            listed = _listed_ids(aws, list_op, list_key, id_key)
        except Exception:
            raise exc from None
        if identifier in listed:
            out(f"[confirm] {get_op} failed for {kind} {identifier} ({code}); the list call still "
                "shows it")
            raise
        out(f"[confirm] {get_op} failed for {kind} {identifier} ({code}); the list call does not "
            "contain it, so it does not exist")
        return True
    if kind == "runtime" and info.get("status") == "DELETE_FAILED":
        raise DeleteFailed(f"runtime delete failed: {info.get('failureReason')}")
    if kind == "gateway" and info.get("status") == "FAILED":
        raise DeleteFailed(f"gateway delete failed: {info.get('statusReasons')}")
    return False


def delete_gateways(aws: kitlib.Aws, found: dict, out, wait_s: float = 300,
                    deleted: set | None = None) -> bool:
    """Delete each gateway's targets, then the gateway, then wait until AWS says the gateway
    does not exist. A gateway that is still listed as DELETING when the wait ends is not
    gone, and this returns False for it (review round 2, MINOR 8)."""
    deleted = deleted if deleted is not None else set()
    ok = True
    for g in found.get("gateways", []):
        for t in g.get("targets", []):
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_DeleteGatewayTarget.html (read 2026-10-07)
            ok &= _try(aws, out, f"gateway target {t.get('name') or t['id']}", CONTROL,
                       "delete_gateway_target", gatewayIdentifier=g["id"], targetId=t["id"])

        def targets_gone(gateway_id=g["id"]):
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGatewayTargets.html (read 2026-10-07)
            page = aws.call(CONTROL, "list_gateway_targets", gatewayIdentifier=gateway_id,
                            dry_result={"items": []})
            return not page.get("items")

        try:
            kitlib.wait_until(targets_gone, timeout_s=wait_s, interval_s=5,
                              what="the gateway has no targets", dry_run=aws.dry_run, out=out)
        except Exception as exc:
            if not kitlib.is_not_found(exc):
                out(f"[delete] waiting for gateway targets: {kitlib.redact(exc)}")
        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_DeleteGateway.html (read 2026-10-07)
        if not _try(aws, out, f"gateway {g['name']}", CONTROL, "delete_gateway",
                    gatewayIdentifier=g["id"]):
            ok = False
            continue
        try:
            kitlib.wait_until(lambda gateway_id=g["id"]: _is_gone(aws, out, "gateway", gateway_id),
                              timeout_s=wait_s, interval_s=5, what=f"gateway {g['id']} is gone",
                              dry_run=aws.dry_run, out=out)
            deleted.add(g["id"])
        except Exception as exc:
            ok = False
            out(f"[delete] gateway {g['id']} is not confirmed gone: {kitlib.redact(exc)}")
    return ok


def delete_runtimes(aws: kitlib.Aws, found: dict, out, wait_s: float = 600,
                    deleted: set | None = None) -> bool:
    """Delete each runtime and wait until AWS says it does not exist.

    When the delete call itself is refused (a runtime that is still CREATING answers
    ConflictException) there is nothing to wait for, so this returns False at once and
    the caller leaves the runtime's bucket and role alone.
    """
    deleted = deleted if deleted is not None else set()
    ok = True
    for r in found.get("runtimes", []):
        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_DeleteAgentRuntime.html (read 2026-10-07)
        if not _try(aws, out, f"runtime {r['id']}", CONTROL, "delete_agent_runtime",
                    agentRuntimeId=r["id"]):
            ok = False
            out(f"[delete] runtime {r['id']} was not deleted (status {r.get('status')}). If it is "
                "still being created, give it a few minutes and run this script again.")
            continue
        try:
            kitlib.wait_until(lambda runtime_id=r["id"]: _is_gone(aws, out, "runtime", runtime_id),
                              timeout_s=wait_s, interval_s=10,
                              what=f"runtime {r['id']} is gone", dry_run=aws.dry_run, out=out)
            deleted.add(r["id"])
        except Exception as exc:
            ok = False
            out(f"[delete] runtime {r['id']} is not confirmed gone: {kitlib.redact(exc)}")
    return ok


def confirm_recorded_absent(aws: kitlib.Aws, found: dict, out, runtime_id: str | None = None,
                            gateway_id: str | None = None, deleted: set | None = None) -> bool:
    """For the runtime and the gateway that .state.json names: ask AWS for each by id.

    Called after the by-prefix deletes, in the recorded Region and account (the caller has
    already checked both). "Not listed under the prefix" is not proof that a recorded
    resource is gone, so its record may be cleared only when the service answers that it
    does not exist. When that call fails for another reason, the record is kept and this
    returns False (review round 5, F1: until then the list call decided, the same listing
    that had not shown it). One that does still exist is deleted here.
    """
    deleted = deleted if deleted is not None else set()
    ok = True
    if runtime_id and runtime_id not in {r["id"] for r in found.get("runtimes", [])}:
        try:
            if aws.dry_run:
                aws.call(CONTROL, "get_agent_runtime", agentRuntimeId=runtime_id,
                         dry_result={"status": "READY"})
                out(f"DRY-RUN  would delete runtime {runtime_id} if that call found it")
            elif _is_gone(aws, out, "runtime", runtime_id, listing_decides=False):
                out(f"[confirm] runtime {runtime_id} recorded in .state.json: confirmed absent")
            else:
                out(f"[confirm] runtime {runtime_id} is recorded in .state.json and still exists, "
                    "although it was not listed under the prefix")
                ok &= delete_runtimes(aws, {"runtimes": [{"id": runtime_id, "status": "?"}]}, out,
                                      deleted=deleted)
        except DeleteFailed as exc:
            out(f"[confirm] runtime {runtime_id} is recorded in .state.json and still exists: {exc}")
            ok = False
        except Exception as exc:
            out(f"[confirm] could not check runtime {runtime_id}: "
                f"{aws.error_code(exc) or type(exc).__name__}. It was not listed under the prefix, "
                "and that is not proof that it is gone, so .state.json keeps its record")
            ok = False
    if gateway_id and gateway_id not in {g["id"] for g in found.get("gateways", [])}:
        try:
            if aws.dry_run:
                aws.call(CONTROL, "get_gateway", gatewayIdentifier=gateway_id,
                         dry_result={"status": "READY"})
                out(f"DRY-RUN  would delete gateway {gateway_id} if that call found it")
            elif _is_gone(aws, out, "gateway", gateway_id, listing_decides=False):
                out(f"[confirm] gateway {gateway_id} recorded in .state.json: confirmed absent")
            else:
                out(f"[confirm] gateway {gateway_id} is recorded in .state.json and still exists, "
                    "although it was not listed under the prefix")
                # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGatewayTargets.html (read 2026-10-07)
                targets = _pages(aws, CONTROL, "list_gateway_targets", "items",
                                 gatewayIdentifier=gateway_id, maxResults=100)
                ok &= delete_gateways(aws, {"gateways": [{
                    "id": gateway_id, "name": gateway_id,
                    "targets": [{"id": t["targetId"], "name": t.get("name")} for t in targets]}]}, out,
                    deleted=deleted)
        except DeleteFailed as exc:
            out(f"[confirm] gateway {gateway_id} is recorded in .state.json and still exists: {exc}")
            ok = False
        except Exception as exc:
            out(f"[confirm] could not check gateway {gateway_id}: "
                f"{aws.error_code(exc) or type(exc).__name__}. It was not listed under the prefix, "
                "and that is not proof that it is gone, so .state.json keeps its record")
            ok = False
    return ok


def delete_workload_identities(aws: kitlib.Aws, cfg: kitlib.Config, out,
                               deleted: set | None = None) -> bool:
    """Run after runtimes and gateways are gone: lists again and removes any that remain."""
    deleted = deleted if deleted is not None else set()
    runtime_prefix = f"{cfg.prefix.replace('-', '_')}_kitc_"
    name_prefix = f"{cfg.prefix}-kitc-"
    ok = True
    # UNVERIFIED: whether AgentCore deletes a runtime's workload identity when the runtime is
    # deleted. This lists again afterwards and deletes whatever still carries the kit's prefix.
    # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListWorkloadIdentities.html (read 2026-10-07)
    identities = _pages(aws, CONTROL, "list_workload_identities", "workloadIdentities", maxResults=20)
    for w in identities:
        name = w.get("name", "")
        if name.startswith(runtime_prefix) or name.startswith(name_prefix):
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_DeleteWorkloadIdentity.html (read 2026-10-07)
            if _try(aws, out, f"workload identity {name}", CONTROL, "delete_workload_identity",
                    name=name):
                deleted.add(name)
            else:
                ok = False
    return ok


def delete_log_groups(aws: kitlib.Aws, found: dict, out, deleted: set | None = None) -> bool:
    deleted = deleted if deleted is not None else set()
    ok = True
    for g in found.get("log_groups", []):
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteLogGroup.html (read 2026-10-07)
        if _try(aws, out, f"log group {g['name']}", "logs", "delete_log_group",
                logGroupName=g["name"]):
            deleted.add(g["name"])
        else:
            ok = False
    return ok


EMPTY_BUCKET_MAX_ROUNDS = 4


def empty_bucket(aws: kitlib.Aws, bucket: str) -> int:
    """Delete every object, every object version and every delete marker in the bucket.
    Returns how many delete entries were sent. Raises when the bucket still lists something
    after EMPTY_BUCKET_MAX_ROUNDS rounds.

    The first version listed current objects only, so a bucket with versioning switched on
    could never be deleted (review round 2, MINOR 12). This follows the approach kit B takes:
    list versions and delete markers, delete them, list again, and only stop when a listing
    comes back empty. Round 1 names a version id only when it is a real one, which is the
    documented way to delete from a bucket that was never versioned; later rounds name every
    version id exactly as listed, "null" included.
    doc: https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html (read 2026-10-07)
         "If S3 Versioning is not enabled, Amazon S3 sets the value of the version ID to null."
    doc: https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectsfromVersioningSuspendedBuckets.html (read 2026-10-07)
    # UNVERIFIED: that DeleteObjects accepts the literal version id "null" for an object
    # version. It is only sent in round 2 and later, which a bucket that was never versioned
    # does not reach.
    """
    sent = 0
    for round_number in range(1, EMPTY_BUCKET_MAX_ROUNDS + 1):
        listed = 0
        key_marker = version_marker = None
        while True:
            params: dict = {"Bucket": bucket, "MaxKeys": 1000}
            if key_marker:
                params["KeyMarker"] = key_marker
            if version_marker:
                params["VersionIdMarker"] = version_marker
            # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html (read 2026-10-07)
            page = aws.call("s3", "list_object_versions", dry_result={}, **params)
            objects = []
            for entry in (page.get("Versions") or []) + (page.get("DeleteMarkers") or []):
                target = {"Key": entry["Key"]}
                version_id = entry.get("VersionId")
                if version_id and (version_id != "null" or round_number > 1):
                    target["VersionId"] = version_id
                objects.append(target)
            listed += len(objects)
            if objects:
                # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html (read 2026-10-07)
                # At most 1,000 keys per request, which is also the page size asked for above.
                result = aws.call("s3", "delete_objects", Bucket=bucket,
                                  Delete={"Objects": objects, "Quiet": True})
                errors = result.get("Errors") or []
                if errors:
                    raise RuntimeError(f"could not delete {len(errors)} object(s), first: "
                                       f"{errors[0].get('Key')} ({errors[0].get('Code')})")
                sent += len(objects)
            if not page.get("IsTruncated"):
                break
            key_marker = page.get("NextKeyMarker")
            version_marker = page.get("NextVersionIdMarker")
        if listed == 0 or aws.dry_run:
            return sent
    raise RuntimeError(f"the bucket still lists objects, versions or delete markers after "
                       f"{EMPTY_BUCKET_MAX_ROUNDS} delete rounds. Empty it in the S3 console (the "
                       "Empty button), then run teardown again.")


def delete_own_bucket(aws: kitlib.Aws, cfg: kitlib.Config, found: dict, out, account: str,
                      deleted: set | None = None) -> bool:
    """Empty and delete the one bucket named exactly for this account and this Region.

    Every other bucket in found["buckets"] is left alone, whatever it is called: it belongs
    to a deploy in another Region, and that deploy's runtime reads its code from it.
    """
    deleted = deleted if deleted is not None else set()
    own = cfg.bucket_name(account)
    if own not in {b["name"] for b in found.get("buckets", [])}:
        return True
    shown = own.replace(account, kitlib.mask_account(account))
    try:
        entries = empty_bucket(aws, own)
        if entries:
            out(f"[delete] {entries} object version(s) and delete marker(s) in bucket {shown}")
    except Exception as exc:
        if kitlib.is_not_found(exc):
            out(f"[delete] bucket {shown}: already gone")
            deleted.add(own)
            return True
        out(f"[delete] bucket {shown}: could not empty it ({kitlib.error_text(exc)})")
        return False
    # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteBucket.html (read 2026-10-07)
    if _try(aws, out, f"bucket {shown}", "s3", "delete_bucket", Bucket=own):
        deleted.add(own)
        return True
    return False


def _trust_policy_regions(document: Any) -> set[str]:
    """Regions named by aws:SourceArn in a role's trust policy (what 30_deploy.py and the
    gateway step write: arn:aws:bedrock-agentcore:<region>:<account>:...)."""
    if isinstance(document, str):
        try:
            document = json.loads(urllib.parse.unquote(document))
        except ValueError:
            return set()
    return set(re.findall(r"arn:aws[a-z-]*:bedrock-agentcore:([a-z0-9-]+):", json.dumps(document or {})))


def roles_in_use_elsewhere(aws: kitlib.Aws, cfg: kitlib.Config, found: dict, account: str, out,
                           history: list[dict] | None = None,
                           aws_for_region: Callable[[str], kitlib.Aws] | None = None) -> list[str]:
    """Reasons not to delete this prefix's IAM roles, or [] when nothing found says they are
    still needed. One role name serves every Region, so before a role goes this looks for a
    deploy of this kit that could be using it:
      - a bucket with the kit's name for another Region (no call needed: ListBuckets shows
        every Region);
      - a runtime or gateway with the kit's name in any other Region that the role's own
        trust policy names, or that .state.json's history names for this account.
    A Region that cannot be checked counts as a reason. Read-only.
    """
    reasons = []
    for bucket in other_buckets(found, cfg, account):
        shown = bucket["name"].replace(account, kitlib.mask_account(account))
        reasons.append(f"bucket {shown} exists for Region {bucket.get('region') or 'unknown'}")
    if reasons:
        return reasons
    regions: set[str] = set()
    for entry in history or []:
        if entry.get("account_id") in (None, account) and entry.get("prefix") in (None, cfg.prefix) \
                and entry.get("region"):
            regions.add(entry["region"])
    for role in found.get("roles", []):
        try:
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html (read 2026-10-07)
            info = aws.call("iam", "get_role", RoleName=role["name"], dry_result={"Role": {}})
        except Exception as exc:
            if kitlib.is_not_found(exc):
                continue
            reasons.append(f"the trust policy of role {role['name']} could not be read "
                           f"({aws.error_code(exc) or type(exc).__name__})")
            continue
        regions |= _trust_policy_regions((info.get("Role") or {}).get("AssumeRolePolicyDocument"))
    regions.discard(cfg.region)
    runtime_prefix = f"{cfg.prefix.replace('-', '_')}_kitc_"
    name_prefix = f"{cfg.prefix}-kitc-"
    for region in sorted(regions):
        if aws_for_region is None:
            reasons.append(f"Region {region} is named by the role or by .state.json's history and "
                           "could not be checked from here")
            continue
        try:
            there = aws_for_region(region)
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html (read 2026-10-07)
            runtimes = [r for r in _pages(there, CONTROL, "list_agent_runtimes", "agentRuntimes",
                                          maxResults=100)
                        if r.get("agentRuntimeName", "").startswith(runtime_prefix)]
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListGateways.html (read 2026-10-07)
            gateways = [g for g in _pages(there, CONTROL, "list_gateways", "items", maxResults=100)
                        if g.get("name", "").startswith(name_prefix)]
        except Exception as exc:
            reasons.append(f"Region {region} could not be checked for a runtime that uses the role "
                           f"({aws.error_code(exc) or type(exc).__name__})")
            continue
        if runtimes or gateways:
            reasons.append(f"{len(runtimes)} runtime(s) and {len(gateways)} gateway(s) of this kit "
                           f"exist in Region {region}")
        else:
            out(f"[roles] checked Region {region}: no runtime or gateway of this kit there")
    return reasons


def delete_roles(aws: kitlib.Aws, found: dict, out, deleted: set | None = None) -> bool:
    deleted = deleted if deleted is not None else set()
    ok = True
    for r in found.get("roles", []):
        name = r["name"]
        try:
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListRolePolicies.html (read 2026-10-07)
            inline = _pages(aws, "iam", "list_role_policies", "PolicyNames", token_in="Marker",
                            token_out="Marker", RoleName=name)
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListAttachedRolePolicies.html (read 2026-10-07)
            attached = _pages(aws, "iam", "list_attached_role_policies", "AttachedPolicies",
                              token_in="Marker", token_out="Marker", RoleName=name)
        except Exception as exc:
            if kitlib.is_not_found(exc):
                deleted.add(name)
                continue
            out(f"[delete] role {name}: could not list its policies ({aws.error_code(exc)})")
            ok = False
            continue
        for policy_name in inline:
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_DeleteRolePolicy.html (read 2026-10-07)
            ok &= _try(aws, out, f"inline policy {policy_name}", "iam", "delete_role_policy",
                       RoleName=name, PolicyName=policy_name)
        for policy in attached:
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_DetachRolePolicy.html (read 2026-10-07)
            ok &= _try(aws, out, f"detach {policy['PolicyName']}", "iam", "detach_role_policy",
                       RoleName=name, PolicyArn=policy["PolicyArn"])
        # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_DeleteRole.html (read 2026-10-07)
        if _try(aws, out, f"role {name}", "iam", "delete_role", RoleName=name):
            deleted.add(name)
        else:
            ok = False
    return ok


def _names_in_arn(arn: str) -> set[str]:
    """Every name or id an ARN can stand for, each as a whole: the resource part, what follows
    its last ":" and its last "/", a log group's name without the trailing ":*", and for S3 the
    bucket."""
    resource = arn.split(":", 5)[5] if arn.count(":") >= 5 else arn
    names = {arn, resource, resource.rsplit(":", 1)[-1], resource.rsplit("/", 1)[-1]}
    if resource.startswith("log-group:"):
        names.add(resource[len("log-group:"):].removesuffix(":*"))
    if arn.startswith("arn:") and arn.split(":")[2] == "s3":
        names.add(resource.split("/", 1)[0])
    for kind in ("delivery-source:", "delivery-destination:", "delivery:", "role/", "runtime/", "gateway/"):
        if resource.startswith(kind):
            names.add(resource[len(kind):])
    return names


def tagged_not_deleted(found: dict, deleted: set) -> list[str]:
    """ARNs from the tag listing that name nothing this run deleted. The tag listing is
    compared with what was deleted, not asked again, because it can lag behind a delete.

    A name must match as a whole. Until review round 4 it was looked for anywhere inside the
    ARN, so after a teardown under the prefix "demo" the bucket and the role of a deploy under
    "kitdemo" were taken for deleted ("demo-kitc-code-..." stands inside "kitdemo-kitc-code-...")
    and the script exited 0 (M5)."""
    left = []
    for item in found.get("tagged", []):
        arn = item.get("arn", "")
        if not (_names_in_arn(arn) & {identifier for identifier in deleted if identifier}):
            left.append(arn)
    return left


def recorded_still_there(aws: kitlib.Aws, found: dict, out, runtime_id: str | None = None,
                         gateway_id: str | None = None) -> list[str]:
    """Read-only, for 99_verify_clean.py: ask AWS by id for the runtime and the gateway that
    .state.json names, when the listing by name prefix did not show them. One that still
    exists is added to `found`, so it is counted and printed like any other leftover. Returns
    what could not be checked.

    "Not in the list" is not proof that a recorded resource is gone: 90_teardown.py has
    always asked by id (confirm_recorded_absent), and the clean check did not, so it could
    print RESULT: CLEAN beside a state file that named a runtime which still existed (review
    round 4, M6). Whether the list can really lag behind is not known. A get call that fails
    for any reason other than "not found" makes the result NOT VERIFIED; the listing does not
    decide here (review round 5, F1)."""
    could_not_check: list[str] = []
    for kind, identifier, key in (("runtime", runtime_id, "runtimes"), ("gateway", gateway_id, "gateways")):
        if not identifier or identifier in {item["id"] for item in found.get(key, [])}:
            continue
        if aws.dry_run:
            aws.call(CONTROL, "get_agent_runtime" if kind == "runtime" else "get_gateway",
                     dry_result={"status": "READY"},
                     **{"agentRuntimeId" if kind == "runtime" else "gatewayIdentifier": identifier})
            continue
        status = "exists"
        try:
            # The listing did not show it, so the listing may not decide that it is gone
            # (review round 5, F1).
            gone = _is_gone(aws, out, kind, identifier, listing_decides=False)
        except DeleteFailed as exc:
            # Asked for by id, it answered: it exists and its delete failed. That is NOT CLEAN,
            # not "could not be asked for" (review round 5, F10).
            gone, status = False, f"{'DELETE_FAILED' if kind == 'runtime' else 'FAILED'}: {exc}"
        except Exception as exc:
            could_not_check.append(f"{kind} {identifier}, which .state.json records, could not be asked "
                                   f"for by id ({aws.error_code(exc) or type(exc).__name__})")
            continue
        if not gone:
            out(f"[confirm] {kind} {identifier} is recorded in .state.json and still exists"
                + ("" if status == "exists" else f" ({status})")
                + ", although the listing by name did not show it")
            found.setdefault(key, []).append(
                {"id": identifier, "name": f"{identifier} (recorded in .state.json; not in the listing by name)",
                 "arn": None, "status": status, "targets": []})
    return could_not_check
