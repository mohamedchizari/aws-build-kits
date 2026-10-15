#!/usr/bin/env python3
"""99_verify_clean.py: check that nothing this kit created is left. Read-only.

Lists by this kit's name prefix in every service the kit touches, and
separately by the tags project=aws-kits and kit=kit-c, so a lost .state.json
does not hide a resource. See kit_resources.py for the full list.

Where it looks:
  - the Region and prefix in use now, in the account you are signed in to;
  - plus every other Region and prefix that .state.json's history names for
    this same account, in the same run.
It cannot look into another account. The last line always starts "RESULT:" and
names the account (last four digits), the Regions and the prefixes checked.

Verdicts and exit codes:
  RESULT: CLEAN         0  nothing found in any place checked, and no place left unchecked.
                           When no usable .state.json exists the line says so in plain
                           words, and says it is not proof for any other Region
  RESULT: NOT CLEAN     1  something is left; each item is printed, with the command
                           that removes it when it sits in another Region or prefix
  RESULT: NOT VERIFIED  1  a lookup failed, so this is not proof of anything
  RESULT: INCOMPLETE    5  nothing found where it looked, but .state.json names a place
                           it could not check (another account); or the file cannot be
                           read; or it names resources without saying where they are; or
                           a .state.json.damaged-* file from the first version of this
                           kit is still in the folder
  RESULT: INCOMPLETE    4  STOPPED before looking: .state.json records a live deploy in
                           another Region, prefix or account than the one in use
  a --dry-run           3  no AWS call is made, so a dry run proves nothing and must
                           not look like a pass to a script that only reads exit codes

What CLEAN does not cover: Regions or prefixes this machine's .state.json never
recorded (a deploy from another computer, or a state file that was deleted),
and anything outside this kit. ../common/whats_running.py is the wider audit.

It also reports two account-level things the kit never creates or deletes, so
you know their state: CloudWatch Transaction Search and the aws/spans log group.
Those two lines are information. A failure to read them is printed and does not
change the verdict.

Usage:
    python 99_verify_clean.py
    python 99_verify_clean.py --dry-run
"""
from __future__ import annotations

import dataclasses

import kit_resources
import kitlib


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None, aws_for_region=None) -> int:
    parser = kitlib.make_parser(__doc__, bills=False)
    args = parser.parse_args(argv)
    out = kitlib.redacting(out)
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=True, out=out)  # never written by this script
    if aws_for_region is None:
        def aws_for_region(region: str) -> kitlib.Aws:
            return kitlib.Aws(region, dry_run=args.dry_run, out=out)

    def result(line: str, code: int) -> int:
        """The last line: the verdict, when it was reached, and the exit code, in one line so
        that it can be copied into RESULTS_TEMPLATE.md whole."""
        out(f"{line} Checked at {kitlib.utc_now_iso()} (UTC). Exit code {code}.")
        return code

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        code = kitlib.explain_aws_error(exc, out)
        return result("RESULT: NOT VERIFIED: the caller identity could not be read, so nothing "
                      "was checked.", code or 1)

    unusable = kitlib.unusable_reason(state)
    if unusable:
        out(f"NOTE: {unusable}. The file was left as it is. This run looks only in "
            f"{kitlib.describe_place(cfg.region, cfg.prefix, account)} and cannot end CLEAN.")
    elif not kitlib.check_place(state, cfg, account, out, "99_verify_clean.py", dry_run=args.dry_run):
        live = kitlib.recorded_place(state)
        return result(
            "RESULT: INCOMPLETE: nothing was checked. .state.json records a deploy in "
            f"{kitlib.describe_place(live['region'], live['prefix'], live['account_id'])}, and the "
            f"settings in use are {kitlib.describe_place(cfg.region, cfg.prefix, account)}.",
            kitlib.EXIT_STATE_MISMATCH)

    # The places to look: here, plus every other place the history names for this account.
    places = [(cfg.region, cfg.prefix)]
    unreachable: list[dict] = []
    for place in ([] if unusable else kitlib.history_places(state)):
        if not args.dry_run and place.get("account_id") and place["account_id"] != account:
            unreachable.append(place)
            continue
        key = (place.get("region") or cfg.region, place.get("prefix") or cfg.prefix)
        if key not in places:
            places.append(key)

    results: list[tuple[str, str, dict, kitlib.Config]] = []
    not_asked: list[str] = []
    try:
        for region, prefix in places:
            here = (region, prefix) == (cfg.region, cfg.prefix)
            place_cfg = cfg if here else dataclasses.replace(cfg, region=region, prefix=prefix)
            place_aws = aws if region == cfg.region else aws_for_region(region)
            out(f"Checking {kitlib.describe_place(region, prefix, account)}"
                + ("" if here else "  (named in .state.json's history)"))
            found = kit_resources.discover(place_aws, place_cfg, out)
            if here and not unusable:
                # The runtime and the gateway the file names are asked for by id as well: a
                # listing that does not show them is not proof that they are gone.
                not_asked = kit_resources.recorded_still_there(
                    place_aws, found, out, runtime_id=state.get("runtime_id"),
                    gateway_id=state.get("gateway_id"))
            results.append((region, prefix, found, place_cfg))
    except Exception as exc:
        code = kitlib.explain_aws_error(exc, out)
        done = "; ".join(f"Region {r}, prefix {p}" for r, p, _, _ in results) or "nothing"
        return result(
            "RESULT: NOT VERIFIED: an AWS call failed, so this is not proof of anything. "
            f"Completely checked before the failure: {done}. Account {kitlib.mask_account(account)}.",
            code or 1)

    # Account-level, informational only. Whatever happens here does not decide the verdict
    # (review round 2, MINOR 11: a denied X-Ray call used to turn a clean account into
    # NOT VERIFIED).
    try:
        # doc: https://docs.aws.amazon.com/xray/latest/api/API_GetTraceSegmentDestination.html (read 2026-10-07)
        dest = aws.call("xray", "get_trace_segment_destination",
                        dry_result={"Destination": "XRay", "Status": "ACTIVE"})
        search_line = "ON" if dest.get("Destination") == "CloudWatchLogs" else "OFF"
    except Exception as exc:
        search_line = (f"could not be read ({aws.error_code(exc) or type(exc).__name__}); this "
                       "does not change the result below")
    try:
        # doc: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html (read 2026-10-07)
        spans = aws.call("logs", "describe_log_groups", logGroupNamePrefix="aws/spans",
                         dry_result={"logGroups": []}).get("logGroups", [])
        spans_line = ("exists" + f" ({spans[0].get('storedBytes')} bytes stored)") if spans else "absent"
    except Exception as exc:
        spans_line = (f"could not be read ({aws.error_code(exc) or type(exc).__name__}); this does "
                      "not change the result below")

    leftovers = 0
    dirty: list[str] = []
    lookup_errors: list[str] = []
    hints: list[str] = []
    for region, prefix, found, place_cfg in results:
        n = kit_resources.count(found)
        leftovers += n
        if n:
            dirty.append(f"{n} in {region} (prefix {prefix})")
            for hint in kit_resources.hints(found, place_cfg, account):
                if hint not in hints:
                    hints.append(hint)
        lookup_errors += [f"{region}: {e}" for e in found.get("lookup_errors", [])]
        if (region, prefix) == (cfg.region, cfg.prefix):
            lookup_errors += [f"{region}: {e}" for e in not_asked]
        out(f"Resources matching this kit in {region}, prefix {prefix}:")
        kit_resources.describe(found, out, mask=account)
    out("")
    out(f"Account-level settings this kit does not create or delete (Region {cfg.region}):")
    out(f"  CloudWatch Transaction Search: {search_line}")
    out(f"  aws/spans log group: {spans_line}")
    out("")

    checked = (f"Checked: account {kitlib.mask_account(account)}; "
               + "; ".join(f"Region {r}, prefix {p}" for r, p, _, _ in results) + ".")
    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made, so this proves nothing about the account.")
        out(f"Exit code {kitlib.EXIT_DRY_RUN_PROVES_NOTHING}, not 0, so that a dry run can never be "
            "taken for a clean result. Run without --dry-run for a RESULT line.")
        return kitlib.EXIT_DRY_RUN_PROVES_NOTHING
    if leftovers:
        for hint in hints:
            out(f"  Where it is: {hint}")
        how = ("See the lines above for where each one is." if hints else
               "Run 90_teardown.py with the same AWS_REGION and KIT_PREFIX, then this again.")
        return result(f"RESULT: NOT CLEAN: {leftovers} item(s) left ({', '.join(dirty)}). {how} "
                      f"{checked}", 1)
    if lookup_errors:
        fix = ("Grant tag:GetResources (or sign in as an administrator) and run this again."
               if "tag lookup" in lookup_errors[0] else "Fix the cause and run this again.")
        return result(
            f"RESULT: NOT VERIFIED: nothing was found by name, but {lookup_errors[0]}. {fix} {checked}", 1)

    stale = kitlib.stale_damaged_files(state)
    set_aside = [] if unusable else list(state.get("damaged_state_set_aside") or [])
    if unreachable or unusable or stale or set_aside:
        reasons = [f".state.json's history names {kitlib.describe_place(p.get('region'), p.get('prefix'), p.get('account_id'))}, "
                   "an account you are not signed in to" for p in unreachable]
        if unusable:
            reasons.append(f"{unusable}, so it cannot say where else this kit was deployed (check "
                           "each Region you used, then move the file out of the kit folder yourself; "
                           "this kit will not touch it)")
        if stale or set_aside:
            names = sorted(set(stale) | set(map(str, set_aside)))
            reasons.append("an earlier state file was set aside as damaged by the first version of "
                           f"this kit ({', '.join(names)}) and may be the only record of a deploy "
                           "(open it, check the Region it names, then move it out of the kit folder "
                           "yourself)")
        return result(
            f"RESULT: INCOMPLETE: nothing was found where this run looked, but {'; and '.join(reasons)}. "
            f"{checked}", kitlib.EXIT_INCOMPLETE)
    caveat = ""
    without_record = state.get("teardowns_without_a_record") or []
    if not state.existed:
        caveat = (" No state file was found on this machine, so this run had no record of where "
                  "this kit was deployed and looked only in the place shown. It is not proof for "
                  "any other Region, prefix or account.")
    elif without_record:
        caveat = (f" A teardown on {without_record[-1].get('at')} ran without a record of where this "
                  "kit was deployed, so the state file does not know every place it was ever "
                  "deployed. This is not proof for any Region, prefix or account not listed here.")
    elif kitlib.recorded_place(state) is None and not kitlib.history_places(state):
        caveat = (" The state file records no deploy and no teardown, so this run looked only in "
                  "the place shown. It is not proof for any other Region, prefix or account.")
    else:
        # Said on every CLEAN line, as kits A and B do (review round 4): the places come from
        # this machine's state file, which does not know a deploy made from another computer
        # or recorded in a file that was later replaced.
        caveat = (" The places checked are the ones this machine's state file names. This is not "
                  "proof for any other Region, prefix or account.")
    out("Also check Billing and Cost Management tomorrow: the invoice is the final word.")
    return result(f"RESULT: CLEAN: nothing with the kit's prefix or tags was found. {checked}{caveat}", 0)


if __name__ == "__main__":
    kitlib.script_main(main)
