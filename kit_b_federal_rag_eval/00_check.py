#!/usr/bin/env python3
"""Step 00. Read-only preflight. Creates nothing.

Checks: who you are signed in as, the Region, whether the models you configured
are reachable, a few Bedrock quotas, whether the corpus and evaluation set are
built, and whether the account holds any OpenSearch Serverless collection (the
known billing trap for knowledge bases).

If .state.json records a deploy, its account, Region and prefix are compared
with your current settings and credentials first. On a difference this script
stops with exit code 1 and says which value differs.

Only the last four digits of the account id are printed.

--invoke-test additionally sends one tiny Converse request to each model. That
is the only real proof of model access, and it bills a fraction of a cent, so it
needs --i-understand-this-bills.
"""
from __future__ import annotations

import sys

from kitlib import aws as api
from kitlib import config, pricing
from kitlib import state as state_mod
from kitlib.cli import BILLS_FLAG, banner, judge_family_line, make_parser, opensearch_warning, stop
from kitlib.redact import account_label, protect_output, redact


def check_model(aws: api.Aws, label: str, model_id: str) -> tuple[bool, list[str]]:
    lines = [f"{label}: {model_id}"]
    ok = True
    is_profile = model_id.split(".", 1)[0] in ("us", "eu", "apac", "global", "us-gov", "jp", "au", "ca")
    try:
        if is_profile:
            profile = api.get_inference_profile(aws, model_id)
            lines.append(f"  inference profile status: {profile.get('status')}")
            lines.append("  (a profile id cannot be checked with the availability call; use --invoke-test)")
        else:
            details = api.get_foundation_model(aws, model_id)
            lifecycle = (details.get("modelLifecycle") or {}).get("status")
            lines.append(f"  lifecycle: {lifecycle}; inference types: {details.get('inferenceTypesSupported')}")
            availability = api.get_foundation_model_availability(aws, model_id)
            lines.append("  authorization: {a}; entitlement: {e}; Region: {r}; agreement: {g}".format(
                a=availability.get("authorizationStatus"), e=availability.get("entitlementAvailability"),
                r=availability.get("regionAvailability"),
                g=(availability.get("agreementAvailability") or {}).get("status")))
            if not aws.dry_run:
                if availability.get("regionAvailability") == "NOT_AVAILABLE":
                    ok = False
                    lines.append("  PROBLEM: not available in this Region")
                if availability.get("authorizationStatus") == "NOT_AUTHORIZED":
                    ok = False
                    lines.append("  PROBLEM: your identity is not authorized for this model")
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(f"  PROBLEM: {type(exc).__name__}: {exc}")
    return ok, lines


@protect_output
def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__, bills=True)
    parser.add_argument("--invoke-test", action="store_true",
                        help=f"send one tiny request to each model (bills; needs {BILLS_FLAG})")
    args = parser.parse_args(argv)
    aws = api.Aws(settings.region, dry_run=args.dry_run)
    problems: list[str] = []

    banner("Kit B preflight (read-only)")
    print(f"Region: {settings.region}   prefix: {settings.prefix}   knowledge base type: {settings.kb_type}")
    if settings.kb_type == "managed" and settings.region not in config.MANAGED_KB_REGIONS:
        problems.append(f"Region {settings.region} is not in the Managed Knowledge Base Region list read on "
                        f"{api.DOCS_READ}: {', '.join(config.MANAGED_KB_REGIONS)}")

    print("\n-- Identity")
    try:
        identity = api.get_caller_identity(aws)
        print(f"Account: {account_label(identity.get('Account'))} (last four digits only)\n"
              f"Caller : {redact(str(identity.get('Arn')))}")
        if str(identity.get("Arn", "")).endswith(":root"):
            problems.append("you are signed in as the account root user; use an IAM user or role instead")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"cannot get caller identity (are credentials configured?): {exc}")
        identity = {}

    try:
        state = config.load_state()                # a state file that cannot be read stops the preflight
        # In a dry run no call is sent, so the account is not known and only Region and prefix are compared.
        state_mod.require_same_place(state, settings, None if args.dry_run else identity.get("Account"),
                                     "The preflight")
    except state_mod.StopHere as error:
        return stop(error)
    if state_mod.has_record(state):
        print(f".state.json records a deploy in {state_mod.describe(state_mod.recorded_place(state))}: "
              "the same place as your current settings.")

    print("\n-- Models")
    models = [("Generation model", settings.gen_model_id), ("Judge model", settings.judge_model_id)]
    if settings.kb_type == "s3vectors":
        models.append(("Embedding model", settings.embed_model_id))
    for label, model_id in models:
        ok, lines = check_model(aws, label, model_id)
        print("\n".join(lines))
        if not ok:
            problems.append(f"{label} {model_id} is not usable as configured")
    if settings.gen_model_id == settings.judge_model_id:
        print("NOTE: the judge is the same model as the generator. A judge tends to favour its own answers.")
    print(f"Judge and generator: {judge_family_line(settings.gen_model_id, settings.judge_model_id)}")
    for label, model_id, role in (("generation", settings.gen_model_id, "GEN"),
                                  ("judge", settings.judge_model_id, "JUDGE")):
        if pricing.model_price(model_id, role) is None:
            print(f"NOTE: no verified price for the {label} model {model_id}. Set PRICE_{role}_INPUT_PER_1M "
                  f"and PRICE_{role}_OUTPUT_PER_1M or the cost estimates will be incomplete.")

    if args.invoke_test:
        print("\n-- Invoke test")
        if not args.dry_run and not args.bills_ok:
            print(f"Skipped: --invoke-test bills a fraction of a cent and needs {BILLS_FLAG}.")
            problems.append("--invoke-test was requested without " + BILLS_FLAG)
        else:
            for label, model_id in models[:2]:
                try:
                    reply = api.parse_converse_response(api.converse(
                        aws, model_id, "Reply with the single word OK.", "Say OK.", max_tokens=5))
                    print(f"{label}: replied {reply['text']!r} "
                          f"({reply['input_tokens']} input, {reply['output_tokens']} output tokens)")
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{label} {model_id} could not be invoked: {exc}")

    print("\n-- Bedrock quotas that mention your models or knowledge bases")
    try:
        quotas = api.list_bedrock_quotas(aws)
        # UNVERIFIED: quota names. Matching is by substring of the model name, so nothing
        # printed here does not mean no quota applies. Look in the Service Quotas console.
        needles = ["knowledge base"]
        for model_id in (settings.gen_model_id, settings.judge_model_id):
            words = model_id.split(".")[-1].split("-v")[0].replace("-", " ")
            needles.append(words)
        shown = 0
        for quota in quotas:
            name = str(quota.get("QuotaName", ""))
            if any(needle.lower() in name.lower() for needle in needles):
                print(f"  {name}: {quota.get('Value')} {quota.get('Unit') or ''} "
                      f"(adjustable: {quota.get('Adjustable')})")
                shown += 1
        if not shown:
            print("  none matched by name (that is not proof that no quota applies; "
                  "check Service Quotas > Amazon Bedrock in the console)")
    except Exception as exc:  # noqa: BLE001
        print(f"  could not list quotas: {type(exc).__name__}: {exc}")

    print("\n-- OpenSearch Serverless collections (this kit must find none of its own)")
    try:
        collections = api.list_opensearch_serverless_collections(aws)
        warning = opensearch_warning(collections)
        print("\n".join(warning) if warning else "  none found in this Region")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"could not list OpenSearch Serverless collections, so the billing trap is unchecked: {exc}")

    print("\n-- Local files")
    build = config.build_dir()
    for path, hint in ((build / "corpus_manifest.json", "run 10_build_corpus.py"),
                       (build / "eval" / "eval_set.jsonl", "run 20_build_eval_set.py")):
        print(f"  {'found  ' if path.is_file() else 'MISSING'} {path}" + ("" if path.is_file() else f"  ({hint})"))
    if state:
        print(f"  .state.json records: {', '.join(sorted(state))}")

    banner("Result")
    if args.dry_run:
        print("DRY-RUN: the API calls above were printed and checked against the SDK's API model. None was sent.")
        return 0
    if problems:
        for problem in problems:
            print(f"PROBLEM: {problem}")
        return 1
    print("No problem found. This does not prove model access unless you ran --invoke-test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
