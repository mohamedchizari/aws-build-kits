#!/usr/bin/env python3
"""99_verify_clean.py: prove that nothing of this kit is left. Read-only.

Lists every SageMaker endpoint, endpoint configuration and model and reports the ones that are this kit's
by either test:
  name   starts with "<KIT_PREFIX>-kita-"
  tags   carries both project=aws-kits and kit=kit-a-gpu-endpoint
It also reports the kit's CloudWatch log groups under /aws/sagemaker/Endpoints/: the log group of every
endpoint it found, and any log group whose name follows this kit's naming rule under any prefix. Pass
--allow-logs if you kept them on purpose; the RESULT line then says LOGS KEPT.

Where it looks: the account of your current credentials, the Region in AWS_REGION and the prefix in
KIT_PREFIX (an exported AWS_REGION overrides config.env; --region and --prefix override both). It reads
.state.json for one purpose only: to learn where else to look. Every Region and prefix the state file or
its history names is checked too, in the same account. It never takes the state file's word that something
is gone, so a stale state file cannot hide a resource. An account named there that is not the one you are
signed in to cannot be checked from here, and the verdict is then INCOMPLETE. So is it when the file
records a live deploy with no account id, or with no Region.

The limit, in plain words: with no state file this script cannot know where a deploy went. It checks the
one place this shell names, and its RESULT line then says NO USABLE STATE FILE WAS FOUND and that the
result is NOT proof for any other Region. A state file that exists but cannot be read as one (damaged)
keeps the verdict at INCOMPLETE for as long as the file is in this folder; the Regions still legible in it
are checked as hints. No script deletes, renames or rewrites a damaged state file: you move it away by
hand, after tearing down with 90_teardown.py --region ... --prefix ...

The RESULT line names what was checked: account (last four digits), Region(s) and prefix(es).

Exit codes:
  0  CLEAN: every place named was checked and nothing remains there. Read the line: it says CLEAN ONLY
     WHERE CHECKED when no state file was found, and LOGS KEPT when --allow-logs left log groups
  1  NOT CLEAN (the list is printed), or INCOMPLETE (a place the state file names was not checked, the
     state file is damaged or records a live deploy with no account id or no Region, or the tag lookup
     limit was reached)
  2  the script could not run (for example, no credentials)
  3  --dry-run: the calls were printed and nothing was checked. A dry run of the proof never exits 0.

Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

import kitlib
from kitlib import Aws, Config

EXIT_DRY_RUN = 3


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print) -> int:
    state_name = args.state_path.name
    account = kitlib.caller_account(aws)
    damaged: kitlib.StateFileError | None = None
    try:
        state = kitlib.load_state(args.state_path)
    except kitlib.StateFileError as problem:
        state, damaged = None, problem
    no_state_file = state is None and damaged is None

    # Where to look: here, plus every Region and prefix the state file or its history names.
    regions, prefixes = [cfg.region], [cfg.prefix]
    unchecked: list[dict[str, str | None]] = []
    for scope in kitlib.named_scopes(state):
        if account is not None and scope["account_id"] not in (None, account):
            unchecked.append(scope)  # another account: these credentials cannot look there
            continue
        if scope["region"] and scope["region"] not in regions:
            regions.append(scope["region"])
        if scope["prefix"] and scope["prefix"] not in prefixes:
            prefixes.append(scope["prefix"])
    hinted: list[str] = []
    if damaged is not None:
        # Looking is harmless, so every Region and prefix still legible in the damaged file is checked too.
        for region in damaged.hints.get("regions", []):
            if region not in regions:
                regions.append(region)
                hinted.append(f"Region {region}")
        for prefix in damaged.hints.get("prefixes", []):
            if prefix not in prefixes:
                prefixes.append(prefix)
                hinted.append(f"prefix {prefix}")

    checked = (f"account ending {kitlib.account_tail(account)}, Region {', '.join(regions)}, "
               f"prefix {', '.join(prefixes)}")
    out(f"Verify clean: {checked}, checked at {kitlib.iso(kitlib.utc_now())} (UTC).")
    if no_state_file:
        out(f"NOTE: no state file was found ({state_name} does not exist). Only the place named above is checked. "
            "This script cannot know whether a deploy went to another Region.")
    if damaged is not None:
        out(f"WARNING: {state_name} exists but cannot be used: {damaged.reason}. It is left exactly as it is."
            + (f" Still legible in it and added to this check as hints: {', '.join(hinted)}." if hinted else ""))
    if state is not None and (len(regions) > 1 or len(prefixes) > 1):
        out(f"This shell points at Region {cfg.region}, prefix {cfg.prefix}. The rest is checked because "
            f"{state_name} or its history names it.")
    live = kitlib.recorded_scope(state) if kitlib.has_live_record(state) else None
    if live and (live["region"] != cfg.region or live["prefix"] != cfg.prefix):
        out(f"NOTE: {state_name} records a live deploy in Region {live['region'] or '(none recorded)'}, prefix "
            f"{live['prefix'] or '(none recorded)'}. "
            f"This shell points at Region {cfg.region}, prefix {cfg.prefix}. An exported AWS_REGION or KIT_PREFIX "
            "overrides config.env. The other scripts stop on this mismatch; this one checks both places.")
    live_without_account = bool(live) and live["account_id"] is None
    live_without_region = bool(live) and live["region"] is None

    count_logs = not args.allow_logs
    remaining = 0
    incomplete = False
    endpoints_left = 0
    kept_logs: list[str] = []
    for region in regions:
        found = kitlib.find_remaining(aws.for_region(region), cfg, check_logs=True,
                                      max_tag_lookups=args.max_tag_lookups, extra_prefixes=prefixes[1:])
        if aws.dry_run:
            continue
        out(f"Region {region}:")
        for line in kitlib.describe_remaining(found, count_logs=count_logs):
            out("  " + line)
        remaining += kitlib.remaining_count(found, count_logs=count_logs)
        endpoints_left += len(found["endpoints"])
        incomplete = incomplete or found["incomplete"]
        if not count_logs:
            kept_logs += [f"{entry['name']} in {region}" if len(regions) > 1 else entry["name"]
                          for entry in found["log_groups"]]

    if aws.dry_run:
        out(f"DRY RUN finished: {aws.calls_printed} AWS call(s) printed, 0 made. NOTHING WAS CHECKED. "
            "This is not proof of anything.")
        out(f"Exit code {EXIT_DRY_RUN}: a dry run of the proof script never exits 0, so it cannot be mistaken "
            "for a clean result.")
        return EXIT_DRY_RUN

    if (state and state.get("resources") and not remaining and not unchecked and not live_without_account
            and not live_without_region):
        out(f"Note: {state_name} still lists {len(state['resources'])} resource(s) that AWS no longer has "
            "in the place it records. The file is stale; AWS is the authority. Running 90_teardown.py once more "
            "tidies it.")

    reasons: list[str] = []
    for scope in unchecked:
        reasons.append(
            f"{state_name} or its history names {kitlib.scope_text(scope['region'], scope['account_id'], scope['prefix'])}. "
            f"You are signed in to the account ending {kitlib.account_tail(account)}, so that account was NOT checked. "
            "Sign in to it (AWS_PROFILE) and run this script again there.")
    if live_without_account:
        reasons.append(
            f"{state_name} records a live deploy but no account id, so this script cannot tell whether the account "
            f"ending {kitlib.account_tail(account)}, the one you are signed in to, is the one you deployed in. Finding "
            "nothing here says nothing about that deploy. If this is the account you deployed in, add "
            f'"account_id": "<its 12 digits>" at the top level of {state_name} and run python 90_teardown.py. '
            "If it is not, sign in to the right one (AWS_PROFILE) and run this script again.")
    if live_without_region:
        reasons.append(
            f"{state_name} records a live deploy but no Region (and no ARN that names one), so this script cannot tell "
            f"where that deploy is. Only Region {', '.join(regions)} was checked, because this shell points there; finding "
            "nothing there says nothing about that deploy. Find the Region (RESULTS_TEMPLATE.md if you filled it in, the "
            "Endpoints list in the SageMaker AI console, or python ../common/whats_running.py --all-regions), add "
            f'"region": "<that Region>" at the top level of {state_name} and run python 90_teardown.py.')
    if damaged is not None:
        reasons.append(
            f"{state_name} exists but cannot be used ({damaged.reason}), so this script does not know which Regions, "
            "accounts or prefixes it named. The result stays INCOMPLETE for as long as that file is in this folder. "
            "To end it: (1) tear down with the place named: python 90_teardown.py --region <the Region you deployed "
            "in> --prefix <your KIT_PREFIX>   (2) run this script with the same --region and --prefix until it lists "
            f"nothing   (3) move {state_name} out of this folder by hand (no script deletes or rewrites it) and run "
            "this script once more. Its RESULT line will then say that no usable state file was found.")
    if incomplete:
        reasons.append("Not every resource could be checked for tags (the tag lookup limit was reached). "
                       "Raise --max-tag-lookups and run again.")

    not_proof = ("so this script does not know where a deploy went: only the account, Region and prefix named here "
                 "were checked, and this is NOT proof for any other Region.")
    state_note = ""
    if no_state_file:
        state_note = f" NO USABLE STATE FILE WAS FOUND ({state_name} does not exist), {not_proof}"
    elif damaged is not None:
        state_note = f" NO USABLE STATE FILE ({state_name} is damaged), {not_proof}"

    out("")
    if remaining:
        out(f"RESULT: NOT CLEAN. Checked {checked}: {remaining} resource(s) remain.{state_note} Exit code 1.")
        how = ("python 90_teardown.py --region <the Region listed above> --prefix <the prefix in the names listed>"
               if damaged is not None else
               "python 90_teardown.py in the place listed above (--region <that Region> --prefix <that prefix>, "
               "or AWS_REGION and KIT_PREFIX)")
        if endpoints_left:
            out(f"An endpoint remains, so the hourly charge is still running. Run {how}.")
        else:
            out("No endpoint remains in the places checked, so the hourly charge has stopped there. "
                f"To remove the rest, run {how}.")
        for reason in reasons:
            out("ALSO INCOMPLETE: " + reason)
        return 1
    if reasons:
        out(f"RESULT: INCOMPLETE. Checked {checked}: nothing of this kit was found there, but the check does not "
            f"cover everything.{state_note} Exit code 1.")
        for reason in reasons:
            out("INCOMPLETE: " + reason)
        return 1

    counts = "0 endpoints, 0 endpoint configurations, 0 models" + (", 0 log groups" if not kept_logs else "")
    logs_note = ""
    if kept_logs:
        logs_note = (f" LOGS KEPT: {len(kept_logs)} CloudWatch log group(s) of this kit remain and were not counted "
                     f"because you passed --allow-logs ({', '.join(kept_logs)}); they cost a little storage until you "
                     "delete them.")
    if no_state_file:
        head = "RESULT: CLEAN ONLY WHERE CHECKED" + (", EXCEPT FOR THE LOGS YOU KEPT." if kept_logs else ".")
        out(f"{head} NO USABLE STATE FILE WAS FOUND ({state_name} does not exist), so this script does not know "
            f"where a deploy went. Only {checked} were checked: {counts} belonging to this kit there.{logs_note} "
            "This is NOT proof for any other Region or account. If you ever deployed from this folder, check the "
            "Region you deployed in (python 99_verify_clean.py --region <Region>) and run the shared audit "
            "(python ../common/whats_running.py). Exit code 0.")
    else:
        head = "RESULT: CLEAN EXCEPT FOR THE LOGS YOU KEPT." if kept_logs else "RESULT: CLEAN."
        out(f"{head} Checked {checked}: {counts} belonging to this kit.{logs_note} Only those places were checked "
            f"(this shell, plus what {state_name} and its history name); this is NOT proof for any other Region or "
            "account. Exit code 0.")
    out("Record this line and its time in RESULTS_TEMPLATE.md. Check the bill tomorrow as well.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "")
    kitlib.add_place_arguments(parser)
    parser.add_argument("--allow-logs", action="store_true",
                        help="Do not count CloudWatch log groups as remaining. The RESULT line then says LOGS KEPT.")
    parser.add_argument("--max-tag-lookups", type=int, default=300,
                        help="Upper limit on ListTags calls per Region (default 300). If reached, the result is INCOMPLETE.")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.config_for_place(kitlib.load_config(), args.region, args.prefix)
    return run(args, cfg, Aws(cfg.region, args.dry_run))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
