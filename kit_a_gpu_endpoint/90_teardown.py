#!/usr/bin/env python3
"""90_teardown.py: delete the endpoint, the endpoint configuration and the model, then check that they are gone.

Deleting the endpoint is what stops the hourly charge. AWS states that deleting an endpoint does not
delete its endpoint configuration or its model, so this script deletes all three, in that order, and
waits for the endpoint to be really gone before touching the other two.

Where it acts: the Region in AWS_REGION, the account of your current credentials, the prefix in KIT_PREFIX.
An exported AWS_REGION overrides config.env; --region and --prefix on the command line override both.
Before it deletes anything it compares those three with what .state.json records for the deploy. On any
difference it STOPS (exit 2): nothing is deleted and the state file is not rewritten, because "already
absent" in the wrong Region or account proves nothing.

It deletes what .state.json records AND anything in that Region that is recognisably this kit's: a name
starting "<KIT_PREFIX>-kita-" or both tags project=aws-kits and kit=kit-a-gpu-endpoint. By default it also
deletes the CloudWatch log group of every endpoint it deletes, and any log group left under
/aws/sagemaker/Endpoints/ whose name follows this kit's naming rule; pass --keep-logs to keep the logs
(they then cost a little storage until you delete them, and the last line says LOGS KEPT).

A resource is struck from .state.json only after a fresh listing, in the recorded Region and account,
no longer shows it. Anything still listed stays recorded and the exit code is 1.

No state file: the script acts in the place this shell (or --region and --prefix) names and nowhere else.
It cannot know whether a deploy went to another Region, and its last line says so in plain words.
Damaged state file (not readable as a state file): the script stops, exit 2, and says how to go on. It goes
on only when you name the place yourself with BOTH --region and --prefix. It then deletes what it finds
there, leaves the damaged file exactly as it is, and exits 1, because it cannot confirm that the place you
named is where the deploy went. No script deletes, renames or rewrites a damaged state file.

It prints, for RESULTS_TEMPLATE.md: the UTC time the endpoint was confirmed gone, the hours and estimated
dollars of the run it closed on a line of its own ("This run:"), the total over every finished run in the
state file with the number of runs and their dates, and the UTC time it finished.

If the listing it makes before the deletes fails (a denied or throttled List call), it still deletes the
endpoint first, the one .state.json records or the one with this kit's fixed name, because that delete is
what stops the charge. Then it reports the listing error and exits 1.

Exit codes:
  0  nothing of this kit remains in the place it acted on (read the last line: it says when no state
     file was found, when the file recorded no live deploy, and when logs were kept)
  1  something remains, the tag check was incomplete, the state file is damaged so the place could
     not be confirmed, or the script stopped after it had sent a delete call (the last line names the calls)
  2  stopped before deleting anything (state mismatch, damaged state file without --region and --prefix,
     no credentials)
  3  --dry-run: the calls were printed, nothing was deleted and nothing was looked at. For this script
     exit code 0 means "nothing remains", so a dry run never exits 0. Same code as 99_verify_clean.py --dry-run.

It needs no confirmation flag: deleting is the safe direction. Always follow it with: python 99_verify_clean.py
Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any, Callable

import kitlib
from kitlib import Aws, Config


def merged_names(state: dict[str, Any] | None, found: dict[str, Any], kind: str, bucket: str) -> list[str]:
    names = [r["name"] for r in kitlib.state_resources(state, kind)]
    for entry in found[bucket]:
        if entry["name"] not in names:
            names.append(entry["name"])
    return names


def strike_confirmed_gone(state: dict[str, Any], after: dict[str, Any], outcomes: dict[str, str],
                          ended: dt.datetime) -> bool:
    """Take out of the state file every recorded resource that the listing made after the deletes no longer shows.

    Call it only when the Region, prefix and account were compared with the state file first: the listing
    is then proof of absence in the place the deploy was recorded. A resource that is still listed keeps
    its record. Returns True when the state changed.
    """
    recorded = list(state.get("resources", []))
    still_listed = {entry["name"] for bucket in ("endpoints", "endpoint_configs", "models") for entry in after[bucket]}
    kept = [r for r in recorded if r.get("name") in still_listed]
    changed = len(kept) != len(recorded)
    if state.get("deploy") and not any(r.get("type") == "endpoint" for r in kept):
        # The endpoint is confirmed gone, so the run is over. If it was already gone when this script looked
        # (deleted in the console, for example), the real end time is unknown and the hours are an upper bound.
        already_gone = any(outcomes.get(f"endpoint:{r['name']}") == "absent"
                           for r in recorded if r.get("type") == "endpoint")
        kitlib.close_run(state, ended, end_time_known=not already_gone)
        changed = True
    state["resources"] = kept
    return changed


EXIT_DRY_RUN = 3  # the same code as a dry run of 99_verify_clean.py; kitlib.EXIT_DRY_RUN says why


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    state_name = args.state_path.name
    place_named = bool(getattr(args, "region", None) and getattr(args, "prefix", None))
    damaged: kitlib.StateFileError | None = None
    try:
        state = kitlib.load_state(args.state_path)
    except kitlib.StateFileError as problem:
        if not place_named:
            raise  # exit 2; the message says how to go on (both flags, the audit, the file stays)
        state, damaged = None, problem
    no_state_file = state is None and damaged is None

    account = kitlib.caller_account(aws)
    where = kitlib.scope_text(cfg.region, account, cfg.prefix)
    out(f"Teardown in {where}{'' if account else ' (account not read in a dry run)'}.")
    if damaged is not None:
        out(f"WARNING: {state_name} exists but cannot be used: {damaged.reason}. Going on because you named the "
            "place with --region and --prefix. The file is left exactly as it is: this script does not delete, "
            "rename or rewrite it.")
        mentioned = damaged.hints.get("regions", [])
        if mentioned and cfg.region not in mentioned:
            out(f"WARNING: what is left of {state_name} mentions Region {', '.join(mentioned)}, not {cfg.region}. "
                "If the deploy went there, run this script again with that Region.")
    elif no_state_file:
        out(f"NOTE: no state file was found ({state_name} does not exist). This script acts only in the place "
            "named above. It cannot know whether a deploy went to another Region.")
    # Stop before any delete if the state file records the deploy somewhere else.
    kitlib.require_state_matches(state, cfg, account, state_name)
    if aws.dry_run:
        out("DRY RUN: the calls are printed, not made. Nothing is deleted.")

    had_live_record = kitlib.has_live_record(state)
    try:
        found = kitlib.find_remaining(aws, cfg, check_logs=True, max_tag_lookups=args.max_tag_lookups)
    except Exception as listing_error:  # noqa: BLE001 - raised again below, after the delete that stops the bill
        if aws.dry_run or type(listing_error).__name__ in kitlib.CREDENTIAL_ERRORS:
            raise
        # The listing is how this script finds what else is the kit's. It is not needed to stop the charge:
        # the endpoint is on record, or has this kit's fixed name. So a denied or throttled List call must
        # not keep the endpoint alive.
        first = [r["name"] for r in kitlib.state_resources(state, "endpoint")] or [cfg.endpoint_name]
        why = kitlib.error_code(listing_error) or type(listing_error).__name__
        out(f"The listing that comes before the deletes failed ({why}). "
            f"Deleting the endpoint first, because that is what stops the hourly charge: {', '.join(first)}.")
        first_outcomes: dict[str, str] = {}
        gone = kitlib.delete_stack(aws, first, [], [], out, sleep, clock, outcomes=first_outcomes)
        unchanged = "the state file was not changed" if state is not None else f"there is no state file ({state_name})"
        if not gone:
            out("THE ENDPOINT IS STILL PRESENT and may still be billing.")
        elif all(first_outcomes.get(f"endpoint:{name}") == "absent" for name in first):
            # Round 5, F4: nothing was deleted, so this run stopped no charge; and the listing that failed is the
            # one that would have looked for anything else.
            out(f"Endpoint {', '.join(first)} was not found in {where} (already absent): this run deleted nothing "
                f"there. NOTHING ELSE WAS DELETED OR CHECKED, and {unchanged}. If an endpoint of this kit exists in "
                "another Region or account, it is still billing.")
        else:
            out(f"Endpoint {', '.join(first)} confirmed gone at {kitlib.iso(kitlib.utc_now())} (UTC, this machine's "
                f"clock): its hourly charge has stopped. NOTHING ELSE WAS DELETED OR CHECKED, and {unchanged}.")
        out("The rest of the teardown did not run because of the error below. Deal with it, then run this script again.")
        raise
    endpoints = merged_names(state, found, "endpoint", "endpoints")
    configs = merged_names(state, found, "endpoint_config", "endpoint_configs")
    models = merged_names(state, found, "model", "models")
    if aws.dry_run and not endpoints:
        endpoints, configs, models = [cfg.endpoint_name], ["<endpoint configuration name>"], ["<model name>"]
    out(f"To delete: {len(endpoints)} endpoint(s), {len(configs)} endpoint configuration(s), {len(models)} model(s).")

    outcomes: dict[str, str] = {}
    all_gone = kitlib.delete_stack(aws, endpoints, configs, models, out, sleep, clock, outcomes=outcomes)
    ended = kitlib.utc_now()
    if all_gone and endpoints and not aws.dry_run:
        out(f"Endpoint(s) confirmed gone at {kitlib.iso(ended)} (UTC, this machine's clock).")

    # The log group of every endpoint this run handled (whatever its prefix: an endpoint found by tag has its
    # log group under its own name), plus every log group the listing matched by name.
    log_groups = [entry["name"] for entry in found["log_groups"]]
    for name in endpoints:
        if kitlib.LOG_GROUP_ROOT + name not in log_groups:
            log_groups.append(kitlib.LOG_GROUP_ROOT + name)
    if args.keep_logs:
        out(f"Keeping {len(log_groups)} possible log group(s) (--keep-logs). 99_verify_clean.py will report them "
            "unless you pass --allow-logs there.")
    elif all_gone:
        for name in log_groups:
            try:
                # DeleteLogGroup: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteLogGroup.html (read 2026-10-07)
                aws.call("logs", "delete_log_group", logGroupName=name)
                out(f"  log group {name}: {'(dry run)' if aws.dry_run else 'deleted.'}")
            except Exception as exc:  # noqa: BLE001 - classified just below
                if not kitlib.is_not_found(exc):
                    raise
                out(f"  log group {name}: already absent.")

    if aws.dry_run:
        out(f"DRY RUN finished: {aws.calls_printed} AWS call(s) printed, 0 made. Nothing was deleted. "
            "Whatever exists still exists and an endpoint is still billing.")
        out(f"Exit code {EXIT_DRY_RUN}: for this script exit code 0 means nothing of this kit remains, and a dry run "
            "deleted nothing and looked at nothing, so a dry run of teardown never exits 0. It is the same code as a "
            "dry run of 99_verify_clean.py.")
        return EXIT_DRY_RUN

    if not all_gone:
        out("")
        out(f"{state_name} was not changed{'' if state else ' (there is no usable state file)'}"
            f"{': it still records the endpoint.' if state else '.'}")
        # The headline is the last line, as README section 5 says of every ending (round 5, F8).
        out("TEARDOWN INCOMPLETE: an endpoint is still present and may still be billing. Wait five minutes, run this "
            "script again, and if it still fails delete the endpoint from the Endpoints list in the SageMaker AI console.")
        return 1

    out("")
    out(f"Checking what remains in {where} (the same check as 99_verify_clean.py):")
    after = kitlib.find_remaining(aws, cfg, check_logs=True, max_tag_lookups=args.max_tag_lookups)
    count_logs = not args.keep_logs
    for line in kitlib.describe_remaining(after, count_logs=count_logs):
        out("  " + line)
    remaining = kitlib.remaining_count(after, count_logs=count_logs)
    kept_logs = [entry["name"] for entry in after["log_groups"]] if args.keep_logs else []

    closed_now = False
    if state and kitlib.has_live_record(state):
        runs_before = len(state.get("history", []))
        if strike_confirmed_gone(state, after, outcomes, ended):
            kitlib.save_state(state, args.state_path)
        closed_now = len(state.get("history", [])) > runs_before
        if state.get("resources"):
            out(f"  {state_name} still records {len(state['resources'])} resource(s) that are still listed.")

    report = kitlib.run_report_lines(state, state_name, closed_now)
    if report:
        out("")
        for line in report:
            out(line)
    elif endpoints:
        out("")
        why = ("cannot be read" if damaged is not None else "does not exist" if no_state_file
               else "holds no deploy record for it (no CreateEndpoint time)")
        out(f"Hours and dollars for the endpoint just deleted: unknown. They are worked out from {state_name}, "
            f"which {why}. Use your bill in Billing and Cost Management.")

    finished = kitlib.iso(kitlib.utc_now())
    lost_state = (f" NO USABLE STATE FILE WAS FOUND ({state_name} does not exist), so this script does not know where "
                  "a deploy went: only that Region, account and prefix were looked at, and this is NOT proof for any "
                  "other Region. If you deployed somewhere else, run it there: python 90_teardown.py --region "
                  "<Region> --prefix <prefix>.") if no_state_file else ""
    if remaining or after["incomplete"]:
        out("")
        out(f"NOT CLEAN: {remaining} resource(s) remain in {where}"
            f"{' and the tag check was incomplete' if after['incomplete'] else ''}. "
            f"Run this script again, then python 99_verify_clean.py.{lost_state}"
            + (f" {state_name} is damaged and was left as it is." if damaged is not None else ""))
        return 1
    logs_kept = ""
    if kept_logs:
        logs_kept = (f" LOGS KEPT at your request (--keep-logs): {len(kept_logs)} CloudWatch log group(s) remain there "
                     f"and cost a little storage until you delete them: {', '.join(kept_logs)}.")
    nothing = ("no endpoint, endpoint configuration or model of this kit was found" if kept_logs
               else "nothing of this kit was found")
    out("")
    if damaged is not None:
        out(f"TEARDOWN NOT CONFIRMED at {finished} (UTC): {nothing} in {where}, the place you named, when this "
            f"script looked again.{logs_kept} But {state_name} is damaged ({damaged.reason}), so this script cannot confirm "
            "that this is where the deploy went, and this is NOT proof for any other Region. Exit code 1. "
            f"Next: python 99_verify_clean.py --region {cfg.region} --prefix {cfg.prefix}   It stays INCOMPLETE until "
            f"you move {state_name} out of this folder by hand; no script will do that for you.")
        return 1
    if no_state_file:
        scope_note = lost_state
    elif had_live_record:
        scope_note = (f" Only that Region, account and prefix were acted on (the place {state_name} records); this is "
                      "NOT proof for any other Region or account.")
    else:
        # The file exists but recorded nothing live, so nothing was compared with the shell: the script acted
        # where the shell (or --region and --prefix) points. Its history may name other places.
        elsewhere = sorted({str(scope["region"]) for scope in kitlib.named_scopes(state)
                            if scope["region"] and scope["region"] != cfg.region})
        scope_note = (f" {state_name} RECORDED NO LIVE DEPLOY when this script started, so it had no place to compare: "
                      "only the Region, account and prefix this shell points at were acted on"
                      + (f", and the file's history names {', '.join(elsewhere)}, which was NOT looked at" if elsewhere else "")
                      + ". This is NOT proof for any other Region or account.")
    out(f"Teardown done at {finished} (UTC): {nothing} in {where}.{logs_kept}{scope_note}"
        " Now prove it independently: python 99_verify_clean.py")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "")
    kitlib.add_place_arguments(parser)
    parser.add_argument("--keep-logs", action="store_true", help="Do not delete the endpoint's CloudWatch log group.")
    parser.add_argument("--max-tag-lookups", type=int, default=300,
                        help="Upper limit on ListTags calls used to find resources by tag (default 300).")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.config_for_place(kitlib.load_config(), args.region, args.prefix)
    return run(args, cfg, Aws(cfg.region, args.dry_run))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
