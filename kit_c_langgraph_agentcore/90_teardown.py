#!/usr/bin/env python3
"""90_teardown.py: delete everything this kit created, including the optional gateway.

Before anything else it compares .state.json with the settings in use. If the
file records a deploy in another Region, under another name prefix or in
another account, it STOPS (exit code 4), deletes nothing and leaves the file
alone. An exported AWS_REGION overrides config.env, so check your shell first.

A .state.json that cannot be read, or that names resources without saying where
they are, also means STOP (exit code 4). The file is never moved, renamed,
deleted or rewritten. To tear down anyway, name the place yourself:
    python 90_teardown.py --region us-west-2 --prefix kitdemo
That run works by name only, in that one Region, and leaves the file as it is.
It cannot end with exit code 0: the file that would say where else the kit was
deployed could not be used, so its last line is TEARDOWN INCOMPLETE, exit code 5.

It does not rely on .state.json to find things. It lists by this kit's name
prefix in every service the kit touches (see kit_resources.py), then deletes in
an order that works: open sessions, log deliveries, gateway targets and
gateways, the runtime, any workload identity left behind, log groups, the code
bucket, and last the IAM roles. A runtime or gateway that the state file names
is also asked for by id, and its record is cleared only when AWS answers that it
does not exist. If the runtime cannot be deleted yet, the bucket and role it
needs are left in place and the state file is kept.

Two things are not tied to one Region, so two rules apply to them:
  - only the bucket named exactly <prefix>-kitc-code-<account>-<this Region> is
    emptied and deleted. A bucket with the kit's name for another Region is
    printed with its Region and left alone: a deploy may be live there.
  - the IAM roles are deleted only when no such bucket exists and no runtime or
    gateway of this kit is found in any other Region this script can name (the
    Regions in the role's trust policy and in .state.json's history).
Whenever the listing by name or by tag shows a resource of this kit that this
run did not delete, the last line says so and the exit code is not 0.

Read your usage first: deleting the log groups deletes the usage records, and
usage data can arrive up to 60 minutes late.
    python 60_read_usage.py

What this script does NOT touch, because the kit did not create it:
  - CloudWatch Transaction Search, if you switched it on, and the aws/spans log group
  - CloudWatch metrics already published (they expire on CloudWatch's own schedule)
  - your Bedrock model access

Deleting stops charges, so this script needs no billing flag.

Exit codes: 0 everything this kit named here was deleted and nothing of the kit
was seen elsewhere; 1 something failed (a session that could not be stopped
counts), or something of the kit remains, or there was no record of a deploy and
the tag listing could not be read; 3 a --dry-run (nothing was deleted, so it is
not 0); 4 STOPPED on the state file; 5 INCOMPLETE: every delete worked, but the
state file could not be used and the place was named with --region and --prefix.

Usage:
    python 90_teardown.py --dry-run
    python 90_teardown.py
    python 90_teardown.py --clean-local      # also remove the local .build folder
    python 90_teardown.py --region us-west-2 --prefix kitdemo    # name the place yourself
Then prove it:
    python 99_verify_clean.py
"""
from __future__ import annotations

import dataclasses
import shutil

import kit_resources
import kitlib


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None, aws_for_region=None) -> int:
    parser = kitlib.make_parser(__doc__, bills=False)
    parser.add_argument("--clean-local", action="store_true",
                        help="also delete the local .build folder (the zip)")
    parser.add_argument("--region", default=None,
                        help="tear down in this Region, whatever AWS_REGION says. Give it together "
                             "with --prefix. Required when .state.json cannot be used")
    parser.add_argument("--prefix", default=None,
                        help="tear down under this name prefix, whatever KIT_PREFIX says. Give it "
                             "together with --region")
    args = parser.parse_args(argv)
    out = kitlib.redacting(out)
    cfg = kitlib.Config.from_env()
    named_by_hand = args.region is not None or args.prefix is not None
    if named_by_hand:
        if not (args.region and args.prefix):
            out("Give --region and --prefix together, or neither.")
            return 2
        cfg = dataclasses.replace(cfg, region=args.region.strip(), prefix=args.prefix.strip())
        cfg.validate()
    if aws_for_region is None:
        def aws_for_region(region: str) -> kitlib.Aws:
            return kitlib.Aws(region, dry_run=args.dry_run, out=out)
    if aws is None or aws.region != cfg.region:
        aws = aws_for_region(cfg.region)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)

    unusable = kitlib.unusable_reason(state)
    if unusable and not named_by_hand:
        kitlib.explain_unusable_state(unusable, out, "90_teardown.py")
        return kitlib.EXIT_STATE_MISMATCH
    if unusable:
        out(f"NOTE: {unusable}. As asked with --region and --prefix, this run works by name only in "
            f"{kitlib.describe_place(cfg.region, cfg.prefix, account)}. The state file is left "
            "exactly as it is and is not read for ids, sessions or history.")
        recorded: dict = {}
        place = None
    else:
        if not kitlib.check_place(state, cfg, account, out, "90_teardown.py", dry_run=args.dry_run):
            return kitlib.EXIT_STATE_MISMATCH
        recorded = state.data
        place = kitlib.recorded_place(state)
    started = kitlib.utc_now()
    out(f"Tearing down kit C in {kitlib.describe_place(cfg.region, cfg.prefix, account)}, "
        f"started {started:%Y-%m-%dT%H:%M:%SZ} (UTC)")
    if place is None:
        out("No deploy is recorded in a usable .state.json, so this covers only the Region, prefix "
            "and account shown above. It is not proof for any other Region.")
    sessions = recorded.get("sessions", []) or []
    if sessions and not recorded.get("usage_cross_checked_at"):
        out(f"WARNING: usage for {len(sessions)} session(s) has not been cross-checked by "
            "60_read_usage.py. The log groups deleted below hold the usage records, and usage "
            "data can arrive up to 60 minutes after a session ends.")
    elif sessions and recorded.get("usage_read_early"):
        out(f"WARNING: usage for {len(sessions)} session(s) was read early at your request and is "
            "NOT final. The log groups deleted below hold the usage records.")

    try:
        found = kit_resources.discover(aws, cfg, out)
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)

    out("Found:")
    kit_resources.describe(found, out, mask=account)

    ok = True
    deleted: set = set()
    kept: list[str] = []          # what to print
    kept_names: set = set()       # the same resources by name, to match the tag listing against
    stop_failed: list[dict] = []  # sessions whose stop call failed and was not made good later
    stop_retried = 0              # sessions whose first stop call failed
    try:
        runtime_arn = recorded.get("runtime_arn") or next(
            (r["arn"] for r in found["runtimes"]), None)
        stop_failed = kit_resources.stop_sessions(aws, sessions, runtime_arn, out)
        stop_retried = len(stop_failed)
        ok &= kit_resources.delete_deliveries(aws, found, out, deleted)
        gone = kit_resources.delete_gateways(aws, found, out, deleted=deleted)
        gone &= kit_resources.delete_runtimes(aws, found, out, deleted=deleted)
        gone &= kit_resources.confirm_recorded_absent(
            aws, found, out, runtime_id=recorded.get("runtime_id"),
            gateway_id=recorded.get("gateway_id"), deleted=deleted)
        ok &= gone
        if gone and stop_failed:
            # The runtime is gone. Ask once more: "not found" now is the service's own answer
            # that there is no such session to bill.
            out(f"[sessions] trying again to stop {len(stop_failed)} session(s) now that the runtime is gone")
            stop_failed = kit_resources.stop_sessions(aws, stop_failed, runtime_arn, out)
        if gone:
            ok &= kit_resources.delete_workload_identities(aws, cfg, out, deleted)
            # Listed again: AgentCore makes the runtime's own log group by itself, and one that
            # appeared after the first listing would otherwise be left behind.
            known = {g["name"] for g in found["log_groups"]}
            found["log_groups"] += [g for g in kit_resources.log_groups(aws, cfg) if g["name"] not in known]
            ok &= kit_resources.delete_log_groups(aws, found, out, deleted)
            ok &= kit_resources.delete_own_bucket(aws, cfg, found, out, account, deleted)
            for bucket in kit_resources.other_buckets(found, cfg, account):
                shown = bucket["name"].replace(account, kitlib.mask_account(account))
                kept.append(f"bucket {shown} (Region {bucket.get('region') or 'unknown'})")
                kept_names.add(bucket["name"])
                out(f"[keep] bucket {shown} is not this Region's bucket (it is for Region "
                    f"{bucket.get('region') or 'unknown'}). NOT deleted: a deploy of this kit may be "
                    "live there and reads its code from it.")
            if found["roles"]:
                reasons = kit_resources.roles_in_use_elsewhere(
                    aws, cfg, found, account, out, history=recorded.get("history", []) or [],
                    aws_for_region=aws_for_region)
                if reasons:
                    for role in found["roles"]:
                        kept.append(f"IAM role {role['name']}")
                        kept_names.add(role["name"])
                    out(f"[keep] the IAM role(s) {', '.join(r['name'] for r in found['roles'])} were "
                        f"NOT deleted, because {'; '.join(reasons)}. One role name serves every "
                        "Region, and a runtime elsewhere may be using it.")
                else:
                    ok &= kit_resources.delete_roles(aws, found, out, deleted)
        else:
            out("A runtime or gateway is not confirmed gone, so its log groups, the code bucket "
                "and the IAM roles were left in place. Give it a few minutes and run this script again.")
        if not args.dry_run:
            for arn in kit_resources.tagged_not_deleted(found, deleted | kept_names):
                kept.append(f"tagged resource {arn.replace(account, kitlib.mask_account(account))}")
    except Exception as exc:
        kitlib.explain_aws_error(exc, out)
        ok = False
    if stop_failed and not args.dry_run:
        ok = False

    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made, nothing was deleted, "
            ".state.json was not changed.")
        out(f"Exit code {kitlib.EXIT_DRY_RUN_PROVES_NOTHING}, not 0: a dry run tears nothing down, "
            "and a script that only reads exit codes must not take it for a teardown.")
        return kitlib.EXIT_DRY_RUN_PROVES_NOTHING

    finished = kitlib.utc_now()
    out(f"Finished {finished:%Y-%m-%dT%H:%M:%SZ} (UTC), "
        f"{(finished - started).total_seconds() / 60:.1f} minute(s) after the start.")
    deployed_at = recorded.get("deployed_at")
    if ok and deployed_at:
        try:
            hours = (finished - kitlib.parse_iso(deployed_at)).total_seconds() / 3600
            out(f"The runtime existed for {hours:.2f} hours: from {deployed_at} (the create call, as "
                f"recorded by 30_deploy.py) to {finished:%Y-%m-%dT%H:%M:%SZ} (this teardown).")
        except ValueError:
            pass

    did_something = bool(deleted) or place is not None
    if ok and not unusable and (did_something or state.existed):
        history = list(recorded.get("history", []) or [])
        if did_something:
            history.append({
                "region": cfg.region, "prefix": cfg.prefix, "account_id": account,
                "runtime_id": recorded.get("runtime_id"), "gateway_id": recorded.get("gateway_id"),
                "deployed_at": deployed_at, "torn_down_at": kitlib.utc_now_iso(),
                "left_in_place": kept,
            })
        new_data = {"history": history,
                    "past_sessions": recorded.get("past_sessions", []) + sessions}
        for key in ("damaged_state_set_aside", "teardowns_without_a_record"):
            if recorded.get(key):
                new_data[key] = recorded[key]
        if place is None and did_something:
            new_data["teardowns_without_a_record"] = list(new_data.get("teardowns_without_a_record", [])) + [
                {"region": cfg.region, "prefix": cfg.prefix, "account_id": account,
                 "at": kitlib.utc_now_iso()}]
        state.data = new_data
        state.save()

    where = kitlib.describe_place(cfg.region, cfg.prefix, account)
    no_record = ("" if place is not None else
                 " No deploy was recorded in a usable state file, so this is not proof for any other "
                 "Region, prefix or account.")
    lookup_errors = list(found.get("lookup_errors") or [])
    # With no record of a deploy, the tag listing is the only way this run can notice the kit under
    # another name prefix. When that listing failed too, exit 0 would claim more than was seen.
    blind = bool(lookup_errors) and place is None
    idle_s = recorded.get("idle_timeout_s") or kitlib.SERVICE_DEFAULT_IDLE_S
    life_s = recorded.get("max_lifetime_s") or kitlib.SERVICE_DEFAULT_LIFETIME_S
    session_bound = max(kitlib.session_cost_bounds(idle_s, life_s, version)["ceiling"]
                        for version in kitlib.RUNTIME_RATES)
    session_limits = (f"its idle timeout ({idle_s} s) or its maximum lifetime ({life_s} s) ends it, at most "
                      f"${session_bound:.3f} a session at the list rates"
                      + ("" if recorded.get("idle_timeout_s") else
                         " (the service defaults: .state.json does not record this runtime's own limits)"))
    # Every other closing line comes before the verdict, so that the verdict is always the line
    # right above "Now prove it" (review round 5, F16: with --clean-local, or with the NOTE on a
    # refused tag lookup, another line stood there).
    if args.clean_local and kitlib.BUILD_DIR.exists():
        shutil.rmtree(kitlib.BUILD_DIR)
        out("Removed the local .build folder.")
    if lookup_errors and not blind:
        out(f"NOTE: {lookup_errors[0]}, so this run could not look for resources of this kit "
            "under another name prefix. 99_verify_clean.py says NOT VERIFIED until that lookup works.")
    if unusable:
        out(f"The state file was left as it is ({unusable}). 99_verify_clean.py stays INCOMPLETE "
            "until you move it out of the kit folder yourself.")
    if stop_failed:
        out(f"NOT STOPPED: the call that stops {len(stop_failed)} recorded session(s) failed (the [delete] "
            "lines above say why). A session that is still open bills until it is stopped or until "
            f"{session_limits}. Whether deleting a runtime ends its sessions is not verified in this kit.")
    if not ok:
        out("Teardown finished WITH ERRORS. .state.json was left as it was. "
            "Fix the cause and run this script again; it is safe to repeat.")
    elif kept:
        out("Resources of this kit that this run did NOT delete:")
        for line in kept:
            out(f"  - {line}")
        for hint in kit_resources.hints(found, cfg, account):
            out(f"  {hint}")
        out(f"Teardown finished, BUT {len(kept)} resource(s) of this kit remain that this run did not "
            f"delete (listed above). What was recorded or named for {where} was deleted or confirmed "
            f"absent, and exit code 1 says the kit is not gone.{no_record}")
    elif blind:
        out(f"Teardown finished, BUT it cannot say this kit is gone: {lookup_errors[0]}, and no deploy was "
            "recorded in a usable state file. So this run could NOT look for resources of this kit under "
            f"another name prefix. What it could see by name in {where} was deleted or confirmed absent, "
            f"and exit code 1 says this is not a finished teardown.{no_record} Grant tag:GetResources (or "
            "sign in as an administrator) and run this script again.")
    elif unusable:
        out(f"TEARDOWN INCOMPLETE: every delete worked, and what carries this kit's names in {where} was "
            "deleted or confirmed absent. But the state file could not be used, so this run cannot say "
            "where else this kit was deployed, and it is not proof for any other Region, prefix or "
            f"account. Exit code {kitlib.EXIT_INCOMPLETE}, not 0.")
    else:
        retried = (f" The first call to stop {stop_retried} session(s) failed; asked again after the runtime "
                   "was gone, the service answered that they are stopped or do not exist. If a session "
                   f"did outlive its runtime, which this kit has not verified either way, it ends when "
                   f"{session_limits}." if stop_retried else "")
        out(("Teardown finished." if stop_retried else "Teardown finished without errors.")
            + f" Everything recorded was deleted or confirmed absent in {where}."
            + (" .state.json now holds only the history." if not unusable and (did_something or state.existed)
               else "") + no_record + retried)
    out("Now prove it: python 99_verify_clean.py")
    if not ok or kept or blind:
        return 1
    return kitlib.EXIT_INCOMPLETE if unusable else 0


if __name__ == "__main__":
    kitlib.script_main(main)
