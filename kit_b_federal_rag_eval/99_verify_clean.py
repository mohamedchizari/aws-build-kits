#!/usr/bin/env python3
"""Step 99. Look for anything that is left. Read-only towards AWS.

It checks ONE place per run: the account your credentials belong to (asked
from STS), the Region in AWS_REGION and the prefix in KIT_PREFIX. The RESULT
line names that place. In it, it lists:
  * every S3 bucket, IAM role, Bedrock knowledge base (with its data sources),
    guardrail and S3 vector bucket (with its indexes) whose name contains
    "-fedrag-", whatever prefix is in front, plus anything .state.json records by id;
  * every resource in the Region tagged project=aws-kits. All of them count as
    left, also the ones another kit created: the tag is shared by the three kits;
  * every OpenSearch Serverless collection in the account and Region, with a loud
    warning, because one left running bills around the clock.

.state.json is read to find out whether this was the right place to look. If it
(or its history of finished teardowns) names an account, Region or prefix that
this run did not check, the result is INCOMPLETE, never CLEAN. When a place in
the history is found clean, that is written into .state.json (the only thing
this script writes).

With no state file, or one that records nothing, a CLEAN result can only speak
for the place that was checked: the RESULT line then says that no record told
the script where the kit was deployed, and that it is no proof for any other
Region. A state file that cannot be read is never deleted or written to; the
checks still run, and the result is INCOMPLETE at best while the file is there.

Exit code 0 = CLEAN: nothing found here, every check ran, nowhere else to check.
Exit code 1 = NOT CLEAN: something is left here.
Exit code 3 = nothing of the kits is left, but OpenSearch Serverless collections exist.
Exit code 4 = INCOMPLETE: a check could not run, or .state.json names a place
              that was not checked, or .state.json cannot be read.
Exit code 5 = --dry-run: the calls were printed, nothing was checked.
"""
from __future__ import annotations

import sys

from kitlib import aws as api
from kitlib import config, resources
from kitlib import state as state_mod
from kitlib.cli import banner, make_parser, opensearch_warning
from kitlib.redact import protect_output

KIT_B_ARN_MARKERS = resources.KIT_B_ARN_MARKERS
EXIT_CLEAN, EXIT_NOT_CLEAN, EXIT_COLLECTIONS, EXIT_INCOMPLETE, EXIT_DRY_RUN = 0, 1, 3, 4, 5


def tag_reason(arn: str) -> str:
    if resources.KIT_MARKER in arn:
        return "kit B by name"
    if any(marker in arn for marker in KIT_B_ARN_MARKERS):
        return "a kind kit B creates"
    return "another kind: probably another kit's, the tag is shared"


@protect_output
def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__)
    args = parser.parse_args(argv)
    aws = api.Aws(settings.region, dry_run=args.dry_run)
    file_status = config.state_file_status()
    damaged = file_status == "damaged"
    if damaged:
        # The checks below still run (they are read-only), but nothing is written and the result
        # cannot be CLEAN: the file may name a place this run does not look at.
        print(config.damaged_state_message(), file=sys.stderr)
        state: dict = {}
    else:
        state = config.load_state()

    banner(f"Kit B clean check in {settings.region}, prefix '{settings.prefix}'")

    account = None
    identity_error = None
    try:
        # DOC: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = api.get_caller_identity(aws)["Account"]
    except Exception as exc:  # noqa: BLE001
        identity_error = f"caller identity (STS): {type(exc).__name__}: {exc}"[:300]
    if args.dry_run:
        account = None
    checked = state_mod.place(account, settings.region, settings.prefix)
    where = state_mod.describe(checked).replace("account unknown", "account unknown (STS did not answer)")
    print(f"Checking {where}.")

    report = resources.verify(aws, settings, state)
    if identity_error:
        report["errors"].insert(0, identity_error)

    print(f"\n-- Kit B resources (name contains '{resources.KIT_MARKER}', or recorded in .state.json)")
    kit = report["kit_resources"]
    for kind in ("knowledge_bases", "data_sources", "guardrails", "vector_buckets", "vector_indexes",
                 "roles", "buckets"):
        entries = kit[kind]
        print(f"  {kind:<16}: {len(entries)}")
        for entry in entries:
            name = entry if isinstance(entry, str) else (entry.get("name") or "")
            note = "" if name.startswith(settings.prefix + "-fedrag") or resources.KIT_MARKER not in name \
                else "   (created under another KIT_PREFIX)"
            print(f"      LEFT: {entry}{note}")

    others = {k: v for k, v in report["other_prefix_resources"].items() if v}
    print(f"\n-- For information only: buckets, roles, knowledge bases, guardrails and vector buckets named "
          f"'{settings.prefix}-...' that are not kit B's (they do not count here unless they are tagged)")
    if others:
        for kind, entries in others.items():
            for entry in entries:
                print(f"  {kind}: {entry}")
    else:
        print("  none")

    print(f"\n-- Resources tagged {config.TAG_KEY}={config.TAG_VALUE} in {settings.region} (every one counts as left)")
    tagged = report["tagged_resources"]
    if tagged:
        for arn in tagged:
            print(f"  LEFT (tagged, {tag_reason(arn)}): {arn}")
        # UNVERIFIED: how long a resource that was just deleted can still be returned by the tagging API.
        # The API page says it "Returns all the tagged or previously tagged resources"; with a tag filter,
        # as here, an entry is expected to be a resource that carries the tag now.
        print(f"  The tag {config.TAG_KEY}={config.TAG_VALUE} is shared by the three kits. If an entry is something "
              "you have just deleted, wait a minute and run this again.")
    else:
        print("  none")

    print("\n-- OpenSearch Serverless collections (any, not only this kit's)")
    collections = report["opensearch_serverless_collections"]
    warning = opensearch_warning(collections)
    print("\n".join(warning) if warning else "  none found in this Region")

    banner("Result")
    if args.dry_run:
        print("DRY-RUN: the list calls above were checked against the SDK's API model. None was sent, so "
              "nothing was checked and this is NOT a clean result.")
        print(f"RESULT: NOTHING WAS CHECKED (--dry-run). Exit code {EXIT_DRY_RUN}, so a script that tests for "
              "exit code 0 cannot take a dry run for a clean account.")
        return EXIT_DRY_RUN

    for error in report["errors"]:
        print(f"COULD NOT CHECK: {error}")
    leftovers = report["kit_resource_count"] + len(tagged)
    clean_here = not leftovers and not report["errors"]
    no_proof = "this is not proof for any other Region, account or prefix"
    if damaged:
        hint = config.salvage_from_damaged_state()
        print("NOT CHECKED: whatever place the damaged state file recorded"
              + (f". What can still be read in it points to Region {hint['region']}, prefix '{hint['prefix']}': "
                 f"run this script with AWS_REGION={hint['region']} KIT_PREFIX={hint['prefix']}" if hint else "")
              + ".")

    if clean_here and state.get("history"):
        stamped = state_mod.mark_checked_clean(state, checked)
        if stamped != state:
            config.save_state(stamped)
            state = stamped
    elsewhere = state_mod.places_not_checked(state, checked)
    if state_mod.has_record(state) and not elsewhere:
        print("NOTE: .state.json still records resources in this place. If the lists above are empty they were "
              "deleted some other way; run 90_teardown.py once to confirm that and clear the record.")
    for other in elsewhere:
        print(f"NOT CHECKED: {state_mod.describe(other)} ({other['why']}). To check it, run this script "
              f"again with {state_mod.how_to_get_there(other)}.")

    if leftovers:
        print(f"RESULT: NOT CLEAN in {where}: {report['kit_resource_count']} kit B resource(s) by name or record, "
              f"{len(tagged)} tagged resource(s), {len(report['errors'])} check(s) that could not run, "
              f"{len(elsewhere)} recorded place(s) not checked"
              + (", and the state file cannot be read" if damaged else "") + ".")
        if damaged:
            print("Run 90_teardown.py with --region and --prefix as described at the top of this output, or "
                  "delete the listed items in the console. Exit code 1.")
        else:
            print("Run 90_teardown.py again with the settings the names above point to, or delete the listed "
                  "items in the console. Exit code 1.")
        return EXIT_NOT_CLEAN
    if report["errors"] or elsewhere or damaged:
        reasons = []
        if damaged:
            reasons.append("the state file cannot be read, so the place it recorded is not known (move the "
                           "file out of this folder yourself once every place you used was torn down and checked)")
        if report["errors"]:
            reasons.append(f"{len(report['errors'])} check(s) could not run")
        if elsewhere:
            reasons.append(f"{len(elsewhere)} place(s) named in .state.json were not checked "
                           f"({'; '.join(state_mod.describe(other) for other in elsewhere)})")
        print(f"RESULT: INCOMPLETE. Nothing was found in {where}, but {' and '.join(reasons)}. "
              f"This is not a pass. Exit code {EXIT_INCOMPLETE}.")
        return EXIT_INCOMPLETE
    # What the record says about the place that was checked. Without a usable record a clean result
    # speaks for this place only, and the RESULT line has to say so in plain words.
    if state_mod.names_place(state, checked):
        record = "This is the place .state.json names, and every other place it names was checked."
    elif file_status == "absent":
        record = (f"NO STATE FILE was found, so nothing told this script where the kit was deployed: {no_proof}.")
    elif not state_mod.has_record(state) and not state.get("history"):
        record = ("The state file records no deploy and no finished teardown, so nothing told this script where "
                  f"the kit was deployed: {no_proof}.")
    else:
        record = (f".state.json does not name this place (the places it names were checked earlier): {no_proof}.")
    if collections:
        print(f"RESULT: no kit resource in {where}, but the OpenSearch Serverless collections above may be "
              f"billing. Exit code {EXIT_COLLECTIONS}. {record}")
        return EXIT_COLLECTIONS
    print(f"RESULT: CLEAN in {where}: no '-fedrag-' resource, nothing that .state.json records, nothing tagged "
          f"{config.TAG_KEY}={config.TAG_VALUE}, and no OpenSearch Serverless collection. {record}")
    print("Only this account, this Region and this prefix were checked. Storage and request charges already "
          "incurred still appear on the bill. Check Billing tomorrow.")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
