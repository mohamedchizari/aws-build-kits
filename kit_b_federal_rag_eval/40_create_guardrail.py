#!/usr/bin/env python3
"""Step 40. Create a Bedrock Guardrail that has only a contextual grounding check.

The guardrail scores a generated answer on two things and blocks it when a
score is under its threshold:
  GROUNDING  is the answer supported by the retrieved passages?
  RELEVANCE  does the answer address the question?
Thresholds come from GROUNDING_THRESHOLD and RELEVANCE_THRESHOLD (default 0.7).
A numbered version is created so the evaluation runs against a fixed guardrail.

The guardrail is recorded in .state.json together with the account, Region and
prefix. If the file already records a deploy somewhere else, this script stops.
"""
from __future__ import annotations

import sys

from kitlib import aws as api
from kitlib import config, pricing, resources
from kitlib import state as state_mod
from kitlib.cli import banner, make_parser, require_bills_flag, stop
from kitlib.redact import protect_output


@protect_output
def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__, bills=True)
    args = parser.parse_args(argv)

    banner(f"Kit B guardrail in {settings.region}")
    print(f"Thresholds: grounding {settings.grounding_threshold}, relevance {settings.relevance_threshold}")
    require_bills_flag(args, [
        "Creating a guardrail is not itself charged. Applying it is: contextual grounding check "
        f"${pricing.GUARDRAIL_GROUNDING_PER_1K_UNITS:.2f} per 1,000 text units; one text unit is up to "
        f"{pricing.GUARDRAIL_TEXT_UNIT_CHARS} characters, counted over source + query + answer together "
        f"(AWS Price List AmazonBedrock us-east-1 and aws.amazon.com/bedrock/pricing/, read {pricing.READ_DATE}).",
        "This script applies nothing. 50_run_eval.py does, once per question.",
    ])

    aws = api.Aws(settings.region, dry_run=args.dry_run)
    try:
        result = resources.create_guardrail(aws, settings)
    except state_mod.StopHere as error:
        return stop(error)
    except KeyboardInterrupt:
        print("\nInterrupted. If the guardrail was created, .state.json records it by its name, with the account, "
              "Region and prefix. Run this script again to finish, or python 90_teardown.py to remove it.",
              file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("If the guardrail was created, .state.json records it by its name. Run this script again to finish, "
              "or python 90_teardown.py to remove it.", file=sys.stderr)
        return 1

    banner("Done")
    if args.dry_run:
        print("DRY-RUN: every call above was checked against the SDK's API model. None was sent.")
        return 0
    print(f"Guardrail id     : {result.get('guardrail_id')}")
    print(f"Guardrail version: {result.get('guardrail_version')}")
    print("Next: python 50_run_eval.py --limit 5 --i-understand-this-bills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
