#!/usr/bin/env python3
"""Step 90. Delete everything this kit created, each thing separately.

Deleting a knowledge base does NOT delete its vector store or the S3 bucket
(https://docs.aws.amazon.com/bedrock/latest/userguide/kb-delete.html, read
2026-10-07), so this script deletes, in order: the data source, the knowledge
base, the guardrail, the S3 vector index and vector bucket (if you used
KB_TYPE=s3vectors), the IAM role, and the S3 document bucket with its objects.
If the knowledge bases cannot be listed, the role and the bucket are left alone.

Where it acts. .state.json records the AWS account, the Region and the name
prefix of the deploy. This script compares all three with your current settings
and with the account your credentials belong to, and STOPS without deleting
anything if one differs (an AWS_REGION exported in your shell overrides
config.env). With no state file it acts on the fixed names in the place your
settings point to, and its RESULT line says that there was no state file.
--region and --prefix name the place on the command line (they take the place
of AWS_REGION and KIT_PREFIX for this run).

A state file that cannot be read. This script never deletes or overwrites it.
It stops and says what to do. Given BOTH --region and --prefix it goes on in
that place and leaves the file where it is; the exit code is then 1 even when
every delete succeeded, because the record of where the kit was deployed could
not be read.

What it forgets. A resource is taken out of .state.json only after a fresh
listing, made after the deletes, shows it is gone. Anything it could not delete
or could not list stays recorded. When nothing is left, the place moves to the
"history" in .state.json so that 99_verify_clean.py knows to check it. The
state file itself is never deleted by this script.

What it checks at the end. It lists again: every bucket, role, knowledge base,
guardrail and vector bucket whose name contains "-fedrag-" (whatever the prefix,
whatever Region a bucket or role name carries) and everything tagged
project=aws-kits of a kind this kit creates. If one is still there, the exit
code is 1 and the output says which settings to run this script with.

Exit code 0 = every delete succeeded and the listing afterwards shows no kit B resource.
Exit code 1 = stopped, or something is still recorded or still listed, or the
              state file is damaged. Things may be billing.
Exit code 5 = --dry-run: the calls were printed and nothing was deleted.
"""
from __future__ import annotations

import dataclasses
import sys

from kitlib import aws as api
from kitlib import config, resources
from kitlib import state as state_mod
from kitlib.cli import banner, make_parser, stop
from kitlib.redact import protect_output

EXIT_DRY_RUN = 5


@protect_output
def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__)
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--region", default=None,
                        help="act in this Region instead of AWS_REGION. With --prefix, this is how a teardown "
                             "is run when .state.json cannot be read")
    parser.add_argument("--prefix", default=None, help="act on this name prefix instead of KIT_PREFIX")
    args = parser.parse_args(argv)
    if args.region or args.prefix:
        settings = dataclasses.replace(settings, region=args.region or settings.region,
                                       prefix=args.prefix or settings.prefix)
        settings.validate()

    file_status = config.state_file_status()
    damaged = file_status == "damaged"
    if damaged:
        print(config.damaged_state_message(), file=sys.stderr)
        if args.dry_run or not (args.region and args.prefix):
            print("\nNothing was deleted. To go on without the record, give both --region and --prefix.",
                  file=sys.stderr)
            return 1
        print("\nGoing on because --region and --prefix were both given. The damaged file is left where it is "
              "and is not written to.")
        state: dict = {}
    else:
        state = config.load_state()

    banner(f"Kit B teardown in {settings.region}, prefix '{settings.prefix}'")

    if args.dry_run:
        try:
            # The account cannot be compared in a dry run: no call is made, so it is not known.
            state_mod.require_same_place(state, settings, None, "The teardown dry run")
        except state_mod.StopHere as error:
            return stop(error)
        names = config.Names(settings.prefix, api.DRY_ACCOUNT, settings.region)
        kb_type = state.get("kb_type") or settings.kb_type
        print("DRY-RUN: pretending every kit resource exists, to show every delete call.")
        print("DRY-RUN: the account is not compared with .state.json here, because no call is sent. "
              "The real run compares it and stops on a difference.")
        aws = api.Aws(settings.region, dry_run=True, canned=resources.dry_run_present_fixture(names, kb_type))
        resources.teardown(aws, settings, state)
        print("DRY-RUN: every call above was checked against the SDK's API model. None was sent. "
              ".state.json was not touched.")
        print(f"RESULT: NOTHING WAS DELETED (--dry-run). Exit code {EXIT_DRY_RUN}, so a script that tests for "
              "exit code 0 cannot take a dry run for a finished teardown.")
        return EXIT_DRY_RUN

    aws = api.Aws(settings.region)
    try:
        # DOC: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = api.get_caller_identity(aws)["Account"]
    except Exception as exc:  # noqa: BLE001
        print(f"STOP: could not find out which AWS account these credentials belong to "
              f"({type(exc).__name__}: {exc}). Nothing was deleted and .state.json was not touched.",
              file=sys.stderr)
        return 1
    here = state_mod.place(account, settings.region, settings.prefix)
    try:
        state_mod.require_same_place(state, settings, account, "The teardown")
    except state_mod.StopHere as error:
        return stop(error)

    print(f"Acting in {state_mod.describe(here)}.")
    if not state_mod.has_record(state):
        print("No resources are recorded in .state.json. Looking for the kit's fixed names in this place only.")
    if not args.yes:
        try:
            answer = input(f"Delete all kit B resources named '{settings.prefix}-fedrag-*' there? [y/N] ")
        except EOFError:                  # no terminal to answer on (a pipe, a scheduler)
            print("\nNo answer could be read. Use --yes to run without the question.")
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing was deleted.")
            return 1

    try:
        failures = resources.teardown(aws, settings, state)
    except KeyboardInterrupt:
        print("\nInterrupted. .state.json was not changed, so it may still list things this run deleted. Run this "
              "script again: it deletes what is left and clears the record of what a fresh listing shows gone.",
              file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        failures = [f"{type(exc).__name__}: {exc}"]

    # Forget only what a fresh listing shows to be gone, in this account and Region.
    kept: dict[str, str] = {}
    gone: list[str] = []
    if state_mod.has_record(state):
        try:
            gone, kept = resources.confirm_gone(aws, state)
        except Exception as exc:  # noqa: BLE001
            gone, kept = [], {key: f"the check failed ({type(exc).__name__}: {exc})"
                              for key in state_mod.recorded_resources(state)}
        if gone:                      # the file is rewritten only to take out what was seen to be gone
            config.save_state(state_mod.forget(state, gone))

    # One more listing, of every prefix: what this run did not delete because its name points elsewhere.
    try:
        left = resources.leftovers(aws, settings)
    except Exception as exc:  # noqa: BLE001
        left = {"kit": [], "other_tagged": [], "stale_tagged": [], "errors": [f"{type(exc).__name__}: {exc}"]}

    finished_at = state_mod.now()
    banner("Result")
    for failure in failures:
        print(f"FAILED: {failure}")
    for key, why in kept.items():
        print(f"KEPT IN .state.json: {state_mod.LABELS[key]} {state.get(key)}: {why}")
    for error in left["errors"]:
        print(f"COULD NOT LIST what is left: {error}")
    for entry in left["kit"]:
        there = state_mod.place(account, entry["region"], entry["prefix"] or settings.prefix)
        if state_mod.same_place(there, here):
            advice = "it is in the place this run acted in: see the failures above, then run this script again"
        else:
            advice = (f"its name points to Region {entry['region']}, prefix '{entry['prefix'] or 'unknown'}': "
                      f"run this script with AWS_REGION={entry['region']} "
                      f"KIT_PREFIX={entry['prefix'] or '<its prefix>'}")
        print(f"STILL THERE, not deleted by this run: {entry['kind']} {entry['name']}; {advice}")
    for arn in left["stale_tagged"]:
        print(f"NOTE: still returned by the tagging API but no longer in the service's own listing, so counted as "
              f"deleted: {arn}. 99_verify_clean.py lists every tagged resource; if it shows this one, wait a "
              "minute and run it again.")
    for arn in left["other_tagged"]:
        print(f"NOTE: tagged project=aws-kits but not a kind kit B creates, so probably another kit's: {arn}. "
              "It was not touched. 99_verify_clean.py counts it.")

    print(f"Date and time 90_teardown.py finished (UTC, this computer's clock): {finished_at}")
    if "knowledge_base_id" in gone:
        hours = state_mod.hours_between(state.get("knowledge_base_created_at"), finished_at)
        if hours is None:
            print("Hours the knowledge base existed: not known (.state.json holds no creation time for it; "
                  "use the time of your 30_deploy_kb.py run).")
        else:
            print("Hours the knowledge base existed (its creation by 30_deploy_kb.py to its deletion confirmed "
                  f"here): {hours:.2f}")
    else:
        print("Hours the knowledge base existed: not known (no knowledge base was on record and confirmed "
              "deleted by this run).")

    where = state_mod.describe(here)
    no_proof = "this is not proof for any other Region, account or prefix"
    if failures or kept or left["kit"] or left["errors"]:
        print(f"RESULT: NOT FINISHED in {where}: {len(failures)} failure(s), {len(kept)} resource(s) kept on "
              f"record, {len(left['kit'])} kit B resource(s) still listed, {len(left['errors'])} listing(s) "
              "that failed. Fix the cause and run this script again with the settings named above. "
              "Things may still be billing.")
        return 1
    if damaged:
        print(f"RESULT: NOT CONFIRMED. Every delete call succeeded in {where} and the listing afterwards shows no "
              "kit B resource there, but the state file is damaged, so this script does not know whether that "
              f"was the only place: {no_proof}. Exit code 1.")
        print("Next: run this script for every other Region and prefix you deployed to, then python "
              "99_verify_clean.py in each. When that finds nothing, the damaged file has no further use: move it "
              "out of this folder yourself. The clean check stays INCOMPLETE while it is here.")
        return 1
    if state_mod.has_record(state):
        print(f"RESULT: every recorded resource was deleted or confirmed absent in {where}, and the listing "
              "afterwards shows no kit B resource there.")
        print("Its record was moved to the history in .state.json, which 99_verify_clean.py reads.")
    elif state_mod.names_place(state, here):
        print(f"RESULT: every delete call succeeded in {where}, and the listing afterwards shows no kit B "
              "resource there. There was no record to clear (.state.json lists this place as torn down already).")
    else:
        why = {"absent": "NO STATE FILE was found",
               "empty": "the state file records no deploy and no finished teardown"}.get(
            file_status, "the state file does not name this place")
        print(f"RESULT: every delete call succeeded in {where}, and the listing afterwards shows no kit B "
              f"resource there. {why[0].upper() + why[1:]}, so nothing told this script where the kit was "
              f"deployed: {no_proof}.")
    print("That is not proof. Now run: python 99_verify_clean.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
