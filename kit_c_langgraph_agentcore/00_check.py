#!/usr/bin/env python3
"""00_check.py: read-only preflight. Creates nothing, changes nothing.

Checks, in order:
  1. local tools: Python version, the packages in requirements.txt, uv
  2. who you are signed in as (account shown masked) and the Region
  3. the model: that the id resolves, that the model is ACTIVE, and that your
     account is allowed to invoke it
  4. AgentCore: that the control API answers in this Region, how many runtimes
     exist, and whether one with this kit's name is already there
  5. whether CloudWatch Transaction Search is on (needed only for traces)
It also reads .state.json: if the file records a deploy in another Region,
under another prefix or in another account than the one in use, it stops with
exit code 4 before doing anything else (an exported AWS_REGION overrides
config.env).

Usage:
    python 00_check.py
    python 00_check.py --dry-run
"""
from __future__ import annotations

import importlib.metadata
import shutil
import sys

import kitlib

REQUIRED_PACKAGES = ["boto3", "langgraph", "langchain-aws", "langchain-core", "bedrock-agentcore", "requests"]
# Documented default quota, read 2026-10-07:
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html
DOCUMENTED_AGENTS_PER_ACCOUNT = 1000
# Source Regions of the US geographic inference profile for the default model, read 2026-10-07:
# https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-micro.html
US_PROFILE_SOURCE_REGIONS = {"us-east-1", "us-east-2", "us-west-2"}


def check_local(out) -> list[str]:
    problems: list[str] = []
    version = sys.version_info
    out(f"[local] Python {version.major}.{version.minor}.{version.micro}")
    if version < (3, 11):
        problems.append("Python 3.11 or newer is required")
    for name in REQUIRED_PACKAGES:
        try:
            out(f"[local] {name} {importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"package {name} is not installed (pip install -r requirements.txt)")
    uv = shutil.which("uv")
    out(f"[local] uv: {uv or 'NOT FOUND'}")
    if not uv:
        problems.append("uv is not installed; 20_package.py needs it to fetch arm64 wheels")
    return problems


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=False)
    args = parser.parse_args(argv)
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=True, out=out)  # read only
    problems: list[str] = []
    warnings: list[str] = []

    out(f"Kit C preflight. Region {cfg.region}, prefix {cfg.prefix}, model {cfg.model_id}")
    out("This script only reads. It creates nothing.")
    problems += check_local(out)

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        ident = aws.call("sts", "get_caller_identity",
                         dry_result={"Account": kitlib.DRY_ACCOUNT,
                                     "Arn": f"arn:aws:iam::{kitlib.DRY_ACCOUNT}:user/dry-run"})
        out(f"[identity] account {kitlib.mask_account(ident['Account'])}, "
            f"principal type {ident['Arn'].split(':')[5].split('/')[0]}")
        if not kitlib.check_place(state, cfg, ident["Account"], out, "00_check.py",
                                  dry_run=args.dry_run):
            return kitlib.EXIT_STATE_MISMATCH

        if kitlib.is_inference_profile_id(cfg.model_id) and cfg.model_id.startswith("us.") \
                and cfg.region not in US_PROFILE_SOURCE_REGIONS:
            warnings.append(
                f"{cfg.model_id} is a US geographic inference profile; its documented source "
                f"Regions are {sorted(US_PROFILE_SOURCE_REGIONS)} and AWS_REGION is {cfg.region}"
            )

        base = kitlib.base_model_id(cfg.model_id)
        if kitlib.is_inference_profile_id(cfg.model_id):
            # doc: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetInferenceProfile.html (read 2026-10-07)
            profile = aws.call("bedrock", "get_inference_profile",
                               inferenceProfileIdentifier=cfg.model_id,
                               dry_result={"status": "ACTIVE", "type": "SYSTEM_DEFINED", "models": []})
            routes = [m.get("modelArn", "").split(":")[3] for m in profile.get("models", [])]
            out(f"[model] inference profile {cfg.model_id}: {profile.get('status')}, "
                f"routes to {sorted(set(routes)) or 'n/a'}")

        # doc: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetFoundationModel.html (read 2026-10-07)
        fm = aws.call("bedrock", "get_foundation_model", modelIdentifier=base,
                      dry_result={"modelDetails": {"modelLifecycle": {"status": "ACTIVE"},
                                                   "inferenceTypesSupported": ["ON_DEMAND"]}})
        details = fm.get("modelDetails", {})
        lifecycle = details.get("modelLifecycle", {}).get("status")
        out(f"[model] {base}: lifecycle {lifecycle}, inference types "
            f"{details.get('inferenceTypesSupported')}")
        if lifecycle != "ACTIVE":
            problems.append(f"model {base} lifecycle is {lifecycle}, not ACTIVE")

        # doc: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetFoundationModelAvailability.html (read 2026-10-07)
        avail = aws.call("bedrock", "get_foundation_model_availability", modelId=base,
                         dry_result={"authorizationStatus": "AUTHORIZED",
                                     "entitlementAvailability": "AVAILABLE",
                                     "regionAvailability": "AVAILABLE",
                                     "agreementAvailability": {"status": "AVAILABLE"}})
        agreement = avail.get("agreementAvailability", {}).get("status")
        out(f"[model] access: authorization {avail.get('authorizationStatus')}, "
            f"entitlement {avail.get('entitlementAvailability')}, "
            f"region {avail.get('regionAvailability')}, agreement {agreement}")
        if avail.get("authorizationStatus") != "AUTHORIZED":
            problems.append("your principal is not authorized for this model (IAM or Marketplace permissions)")
        if avail.get("regionAvailability") != "AVAILABLE":
            problems.append(f"model {base} is not available in {cfg.region}")
        if avail.get("entitlementAvailability") != "AVAILABLE" or agreement != "AVAILABLE":
            warnings.append(
                "the model is not yet enabled for this account. Bedrock enables most models on "
                "first use; Anthropic models first need the use-case form (README section 2, "
                "Things that can go wrong)"
            )

        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimes.html (read 2026-10-07)
        runtimes: list[dict] = []
        token = None
        while True:
            page_args = {"maxResults": 100}
            if token:
                page_args["nextToken"] = token
            page = aws.call("bedrock-agentcore-control", "list_agent_runtimes",
                            dry_result={"agentRuntimes": []}, **page_args)
            runtimes += page.get("agentRuntimes", [])
            token = page.get("nextToken")
            if not token:
                break
        mine = [r for r in runtimes if r.get("agentRuntimeName") == cfg.runtime_name]
        out(f"[agentcore] control API answered in {cfg.region}: {len(runtimes)} runtime(s) in the "
            f"account, documented default quota {DOCUMENTED_AGENTS_PER_ACCOUNT}")
        if mine:
            warnings.append(
                f"a runtime named {cfg.runtime_name} already exists (status {mine[0].get('status')}). "
                "30_deploy.py will not reuse it: it refuses while .state.json records a runtime, "
                "and otherwise AWS rejects the duplicate name. Run 90_teardown.py first"
            )
        if len(runtimes) >= DOCUMENTED_AGENTS_PER_ACCOUNT:
            problems.append("the account is at the documented default quota for agent runtimes")

        # doc: https://docs.aws.amazon.com/xray/latest/api/API_GetTraceSegmentDestination.html (read 2026-10-07)
        dest = aws.call("xray", "get_trace_segment_destination",
                        dry_result={"Destination": "XRay", "Status": "ACTIVE"})
        on = dest.get("Destination") == "CloudWatchLogs"
        out(f"[traces] CloudWatch Transaction Search: {'ON' if on else 'OFF'} "
            f"(destination {dest.get('Destination')}, status {dest.get('Status')})")
        if not on:
            warnings.append(
                "Transaction Search is off, so traces will not be viewable. Session cost and logs "
                "do not need it. Turning it on is an account-wide choice (README section 3)"
            )
    except Exception as exc:  # credentials, permissions, throttling
        code = kitlib.explain_aws_error(exc, out)
        out("PREFLIGHT INCOMPLETE: an AWS call failed, see the line above.")
        return code

    out("")
    for line in (kitlib.PRICE_LINES_RUNTIME + kitlib.PRICE_LINES_MODEL + kitlib.PRICE_LINES_LOGS
                 + kitlib.unstopped_session_lines(cfg.idle_timeout_s, cfg.max_lifetime_s)):
        out(f"[price] {line}")
    out("")
    for w in warnings:
        out(f"WARNING: {w}")
    for p in problems:
        out(f"PROBLEM: {p}")
    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made, so the values above are placeholders.")
        return 0
    if problems:
        out(f"PREFLIGHT FAILED: {len(problems)} problem(s).")
        return 1
    out(f"PREFLIGHT OK with {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
