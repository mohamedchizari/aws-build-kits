#!/usr/bin/env python3
"""10_deploy.py: create one model, one endpoint configuration and one single-GPU endpoint. THIS BILLS.

The endpoint is billed for every hour it exists, with or without traffic, until 90_teardown.py deletes it.
The script refuses to run without --i-understand-this-bills and prints the price it expects first.

What it does: reads your account id, reads the quota again, looks up the execution role, creates the
three resources (each one is written into .state.json before its create call and completed after it, so
a deploy that dies half way still leaves a record of the place), then polls until the endpoint is
InService or Failed. It prints the UTC time of the CreateEndpoint call and of InService. First start
usually takes several minutes because the instance pulls the container image and the container
downloads the model weights from Hugging Face.

.state.json records the Region, the name prefix and the account id of this deploy. The file is local and
git-ignored; no script prints more than the last four digits of the account id (everything a script prints,
AWS error text included, passes through kitlib.redact). Every later script
compares the three with the shell it runs in and stops on a mismatch. So does this one, if the file
already records something. An exported AWS_REGION overrides config.env.

Exit codes: 0 InService (or --no-wait, or --dry-run); 1 the endpoint did not reach InService, AWS returned
an error, or the script stopped after it had sent a create call (the last line then names the calls that
were sent, and the endpoint may exist and bill); 2 it stopped before it created anything; 130 Ctrl-C (its
last line, too, names any create call already sent).
If CreateEndpoint is refused and an endpoint of this name exists ("already exists", for example after the
answer to this run's own request was lost and the SDK sent it again), the endpoint and the deploy record
stay in .state.json and the script stops with exit code 1: tear down, then deploy again.

Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any, Callable

import kitlib
from kitlib import Aws, Config


def print_plan(cfg: Config, env: dict[str, str], price: float, source: str, max_hours: float,
               out: Callable[[str], None]) -> None:
    out("Plan")
    out(f"  Region:            {cfg.region}")
    out(f"  Endpoint:          {cfg.endpoint_name} (1 x {cfg.instance_type})")
    out(f"  Container image:   {cfg.image_uri}")
    out(f"  Host AMI version:  {cfg.inference_ami_version or '(not set, SageMaker default)'}")
    out(f"  Model:             {cfg.hf_model_id} (downloaded by the container from huggingface.co)")
    for key in sorted(env):
        out(f"    {key}={env[key]}")
    out(f"  Tags:              {kitlib.PROJECT_TAG_KEY}={kitlib.PROJECT_TAG_VALUE}, {kitlib.KIT_TAG_KEY}={kitlib.KIT_TAG_VALUE}")
    out("")
    out(f"PRICE: ${price:.4f} per hour while the endpoint exists, traffic or no traffic.")
    out(f"  Source: {source}")
    for line in kitlib.OTHER_HOSTING_CHARGES:
        out(f"  Also (small): {line}")
    out(f"  Your limit for this sitting: {max_hours:g} h, about ${price * max_hours:.2f}. "
        f"Forgotten for 24 h: about ${price * 24:.2f}. Forgotten for 30 days: about ${price * 720:.2f}.")
    out("  Nothing in this kit deletes the endpoint for you. You delete it: python 90_teardown.py")
    out("")


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    env = cfg.container_env()
    max_hours = args.max_hours if args.max_hours is not None else cfg.max_hours
    if max_hours <= 0 or max_hours > 12:
        raise kitlib.KitError("--max-hours must be greater than 0 and at most 12.")
    price, source = kitlib.price_for(cfg.instance_type, cfg.region, args.price_per_hour)
    print_plan(cfg, env, price, source, max_hours, out)

    if not aws.dry_run and not args.i_understand_this_bills:
        raise kitlib.KitError("Refusing to create a billed endpoint without --i-understand-this-bills. "
                              "Use --dry-run to see the calls without making them.")

    state = kitlib.load_state(args.state_path)
    account = kitlib.caller_account(aws)
    kitlib.require_state_matches(state, cfg, account, args.state_path.name)
    if kitlib.has_live_record(state):
        raise kitlib.KitError(
            f"{args.state_path.name} already records {len(state.get('resources', []))} resource(s). This kit runs one "
            "endpoint at a time. Run: python 90_teardown.py   then   python 99_verify_clean.py")
    if state is None:
        state = kitlib.empty_state(cfg, account)
        if not aws.dry_run:
            out(f"NOTE: no state file was found, so a new {args.state_path.name} starts with this deploy. If you "
                "ever deployed from this folder before, that deploy is not known to this kit: check it with "
                "python 99_verify_clean.py --region <the Region of that deploy> before you go on.")
    else:
        kitlib.stamp_state(state, cfg, account)
    out(f"Deploying into {kitlib.scope_text(cfg.region, account, cfg.prefix)}"
        f"{'' if account else ' (account not read in a dry run)'}. {args.state_path.name} records all three.")

    quota = kitlib.read_quota(aws, cfg.instance_type)
    if quota["value"] is not None and quota["value"] < 1:
        raise kitlib.KitError(
            f"Quota '{cfg.instance_type} for endpoint usage' ({quota['code']}) is {quota['value']:g}. "
            f"Request 1 first: {kitlib.quota_request_command(cfg.instance_type, cfg.region)}")

    # GetRole: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html (read 2026-10-07)
    role = aws.call("iam", "get_role", RoleName=cfg.role_name)
    role_arn = role["Role"]["Arn"] if role else f"arn:aws:iam::<ACCOUNT_ID>:role/{cfg.role_name}"

    now = kitlib.utc_now()
    deadline = now + dt.timedelta(hours=max_hours)
    kitlib.create_stack(aws, cfg, env, role_arn, state, args.state_path, price, deadline, now, out,
                        price_source=source)

    if aws.dry_run:
        kitlib.wait_in_service(aws, cfg.endpoint_name, out, sleep, clock)
        out(f"DRY RUN finished: {aws.calls_printed} AWS call(s) printed, 0 made. Nothing was created. Nothing bills.")
        return 0

    out("")
    out("THE ENDPOINT NOW EXISTS. Treat it as billing from this moment.")
    out(f"CreateEndpoint was called at {state['deploy']['create_called_utc']} (UTC). That is the date of this run.")
    out(f"Tear down by {state['deploy']['deadline_utc']} at the latest: python 90_teardown.py")
    if args.no_wait:
        out("Not waiting (--no-wait). The endpoint is billing from now on, whatever its status. Check the status "
            "with: python 55_observe.py   Stop the charge with: python 90_teardown.py")
        return 0

    out(f"Waiting for InService, polling every 30 s, for up to {args.wait_timeout_minutes:g} minutes.")
    status, description = kitlib.wait_in_service(aws, cfg.endpoint_name, out, sleep, clock,
                                                 timeout_s=args.wait_timeout_minutes * 60.0)
    if status == "InService":
        seen = kitlib.utc_now()
        state["deploy"]["in_service_utc"] = kitlib.iso(seen)
        # UNVERIFIED: DescribeEndpoint returning CreationTime. It is in the botocore 1.43.108 service model but
        # was not listed on the DescribeEndpoint API reference page read on 2026-10-07, so it is optional here.
        creation = (description or {}).get("CreationTime")
        if creation is not None and hasattr(creation, "astimezone"):
            state["deploy"]["aws_creation_time_utc"] = kitlib.iso(creation)
        kitlib.save_state(state, args.state_path)
        started = kitlib.parse_iso(state["deploy"]["create_called_utc"])
        minutes = max(0.0, (seen - started).total_seconds() / 60.0)
        out(f"InService after {minutes:.1f} minutes (CreateEndpoint call at {state['deploy']['create_called_utc']}, "
            f"InService seen at {state['deploy']['in_service_utc']}, UTC, polled every 30 s). "
            "Write that number into RESULTS_TEMPLATE.md.")
        for line in kitlib.billing_lines(state, kitlib.utc_now()):
            out(line)
        out("Next: python 50_invoke.py")
        return 0

    out("")
    out(f"The endpoint did not reach InService. Final status: {status}.")
    reason = (description or {}).get("FailureReason")
    if reason:
        out(f"FailureReason from SageMaker: {reason}")
    out("It may still be billing. Do these two things now, in this order:")
    out("  1. python 55_observe.py --logs-only     (read why, while the logs are fresh)")
    out("  2. python 90_teardown.py                (then python 99_verify_clean.py)")
    out("Common causes are listed in README section 2.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "", bills=True)
    parser.add_argument("--max-hours", type=float, default=None,
                        help="How long you intend to keep the endpoint (default MAX_HOURS from config, 3). "
                             "Recorded as a deadline that later scripts enforce. It deletes nothing by itself.")
    parser.add_argument("--price-per-hour", type=float, default=None,
                        help="A price you read yourself, for a Region or instance type this kit has no price for.")
    parser.add_argument("--no-wait", action="store_true", help="Return right after CreateEndpoint.")
    parser.add_argument("--wait-timeout-minutes", type=float, default=45.0, help="Stop polling after this long (default 45).")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.load_config()
    return run(args, cfg, Aws(cfg.region, args.dry_run))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
