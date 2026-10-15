#!/usr/bin/env python3
"""70_change_one_setting.py: change exactly one memory or batching setting, then measure again. THIS BILLS.

Usage:  python 70_change_one_setting.py --set SM_VLLM_MAX_NUM_SEQS=16 --i-understand-this-bills

Settings you may change (one per run), all passed to vLLM by the AWS container as --<name>:
  SM_VLLM_MAX_NUM_SEQS             how many requests vLLM will decode in one batch (the batching setting)
  SM_VLLM_MAX_MODEL_LEN            longest prompt plus answer, in tokens (a memory setting: KV cache per sequence)
  SM_VLLM_GPU_MEMORY_UTILIZATION   share of GPU memory vLLM may take (a memory setting: size of the KV cache pool)

How: the endpoint is deleted, then a new model, endpoint configuration and endpoint are created with
the one changed value. The endpoint is down for several minutes. This is not how you would change a
production endpoint (that is UpdateEndpoint, which starts a second fleet next to the first). It is done
this way here because a quota of 1 instance leaves no room for a second fleet.

"Exactly one" is enforced: the instance type, model, container image and host AMI must be the ones the
endpoint was deployed with (they are read from .state.json and compared with your settings), and every
other container setting is carried over unchanged. If you edited config.env since the deploy, the
script stops and lists the differences.

If .state.json records a deploy in another Region, account or prefix than this shell points at, the
script stops and says so. An exported AWS_REGION overrides config.env.

The teardown time you set at deploy stays the same. It is not extended.
Exit code 2 means it stopped before it deleted or created anything. Once DeleteEndpoint has been sent,
every stop is exit code 1, or 130 for Ctrl-C, and the last line names the calls that were sent (kitlib.guarded).
It prints, for RESULTS_TEMPLATE.md: the hours of the endpoint it replaced, and the minutes of downtime
from the DeleteEndpoint call to InService of the new endpoint, with both UTC times.
Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable

import kitlib
from kitlib import Aws, Config


def parse_setting(text: str) -> tuple[str, str]:
    key, separator, value = text.partition("=")
    key, value = key.strip(), value.strip()
    if not separator or not value:
        raise kitlib.KitError("--set needs NAME=VALUE, for example SM_VLLM_MAX_NUM_SEQS=16.")
    if key not in kitlib.SETTABLE_ENV_KEYS:
        raise kitlib.KitError(f"{key} is not one of the settings this script changes: {', '.join(kitlib.SETTABLE_ENV_KEYS)}.")
    try:
        if key == "SM_VLLM_GPU_MEMORY_UTILIZATION":
            number = float(value)
            if not 0 < number <= 1:
                raise ValueError("must be greater than 0 and at most 1")
        else:
            number = int(value)
            if number < 1:
                raise ValueError("must be at least 1")
            if key == "SM_VLLM_MAX_MODEL_LEN" and number < 256:
                raise ValueError("must be at least 256")
    except ValueError as exc:
        raise kitlib.KitError(f"{key}={value} is not usable: {exc}.") from exc
    return key, value


def changed_since_deploy(cfg: Config, deploy: dict[str, Any]) -> list[str]:
    """Settings that decide what is created and what it costs, where config now differs from the deploy."""
    pairs = [
        ("INSTANCE_TYPE", deploy.get("instance_type"), cfg.instance_type),
        ("HF_MODEL_ID", deploy.get("hf_model_id"), cfg.hf_model_id),
        ("container image (VLLM_IMAGE_TAG, DLC_REGISTRY_ACCOUNT)", deploy.get("image_uri"), cfg.image_uri),
        ("INFERENCE_AMI_VERSION", deploy.get("inference_ami_version"), cfg.inference_ami_version),
    ]
    return [f"{name}: deployed with {then or '(empty)'}, config now says {now or '(empty)'}"
            for name, then, now in pairs if (then or "") != (now or "")]


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    key, value = parse_setting(args.set)
    state = kitlib.load_state(args.state_path)
    # Region and prefix are compared here, which needs no AWS call. The account is compared further down,
    # after the billing flag was checked, so that a run without the flag asks AWS nothing at all.
    kitlib.require_state_matches(state, cfg, None, args.state_path.name)
    deploy = (state or {}).get("deploy")
    if aws.dry_run and not deploy:
        out("DRY RUN without a state file: using the settings from config as the current ones.")
        state = kitlib.empty_state(cfg)
        current_env = cfg.container_env()
        price, price_source = kitlib.price_for(cfg.instance_type, cfg.region, args.price_per_hour)
        source = price_source
        deadline = kitlib.utc_now()
        old = {"endpoint": [cfg.endpoint_name], "endpoint_config": ["<current endpoint configuration>"],
               "model": ["<current model>"]}
    else:
        if not deploy or not kitlib.state_resources(state, "endpoint"):
            raise kitlib.KitError("No deployed endpoint is recorded in .state.json. Deploy first: python 10_deploy.py")
        differences = changed_since_deploy(cfg, deploy)
        if differences:
            raise kitlib.KitError(
                "This script changes exactly one container setting and keeps everything else as deployed, but "
                "your settings no longer match the deploy: " + "; ".join(differences) + ". The new endpoint would "
                "be a different one at a different price. Put those settings back (config.env or the exported "
                "variables), or tear down and deploy again with 10_deploy.py.")
        current_env = dict(deploy["env"])
        # The instance type is the deployed one (checked just above), so the price is the one accepted at
        # deploy. Its source page and date were written into the state file with it.
        price = float(deploy["usd_per_hour"])
        price_source = deploy.get("price_source") or ""
        source = (f"{price_source} (the price you accepted at deploy, from {args.state_path.name})" if price_source
                  else f"no source was recorded; it is the price you accepted at deploy, from {args.state_path.name}")
        deadline = kitlib.parse_iso(deploy["deadline_utc"])
        old = {kind: [r["name"] for r in kitlib.state_resources(state, kind)]
               for kind in ("endpoint", "endpoint_config", "model")}

    before = current_env.get(key, "(not set, container default)")
    if current_env.get(key) == value:
        raise kitlib.KitError(f"{key} is already {value}. Nothing to change.")
    new_env = dict(current_env)
    new_env[key] = value

    # The price and its source are printed before anything else happens, also when the script then refuses.
    out(f"Changing one setting: {key}  {before}  ->  {value}")
    out(f"PRICE: the new endpoint costs ${price:.4f} per hour, the same as the one it replaces. Source: {source}")
    out("The old endpoint is deleted first, so you pay for one endpoint at a time. Expect several minutes of downtime.")
    out("")

    now = kitlib.utc_now()
    if not aws.dry_run:
        if kitlib.past_deadline(state, now) and not args.ignore_deadline:
            for line in kitlib.billing_lines(state, now):
                out(line)
            raise kitlib.KitError("You are past the teardown time you set. Tear down instead of redeploying, "
                                  "or pass --ignore-deadline if you have decided to keep paying.")
        if not args.i_understand_this_bills:
            raise kitlib.KitError("Refusing to recreate a billed endpoint without --i-understand-this-bills. "
                                  "Use --dry-run to see the calls without making them.")

    kitlib.require_state_matches(state, cfg, kitlib.caller_account(aws), args.state_path.name)

    # GetRole: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html (read 2026-10-07)
    role = aws.call("iam", "get_role", RoleName=cfg.role_name)
    role_arn = role["Role"]["Arn"] if role else f"arn:aws:iam::<ACCOUNT_ID>:role/{cfg.role_name}"

    out("Step 1 of 2: delete the current endpoint, endpoint configuration and model.")
    down_since = kitlib.utc_now()  # the endpoint stops answering from the DeleteEndpoint call that follows
    outcomes: dict[str, str] = {}
    replaced: dict[str, Any] | None = None
    gone = kitlib.delete_stack(aws, old["endpoint"], old["endpoint_config"], old["model"], out, sleep, clock,
                               outcomes=outcomes)
    if not gone:
        raise kitlib.KitError("The old endpoint is still there after the wait, so nothing new was created. DeleteEndpoint "
                              "was sent, and the endpoint may still be billing. "
                              "Run python 99_verify_clean.py, then python 90_teardown.py.")
    if not aws.dry_run:
        # The Region, account and prefix were compared with the state file above, so "deleted" and "already
        # absent" both mean: confirmed gone where the deploy was recorded. Only then is the record closed.
        already_gone = any(outcomes.get(f"endpoint:{name}") == "absent" for name in old["endpoint"])
        kitlib.close_run(state, kitlib.utc_now(), end_time_known=not already_gone)
        state.setdefault("changes", []).append({"setting": key, "from": before, "to": value, "at_utc": kitlib.iso(now)})
        kitlib.save_state(state, args.state_path)
        out(f"The endpoint it replaced: it existed {kitlib.run_line(state['history'][-1])}. "
            "90_teardown.py will list this run again next to the one that starts now.")
        # What this sitting has already cost before the new endpoint: the run just closed, plus whatever the
        # endpoint just deleted had carried over from an earlier change. The BILLING lines show it from now on.
        closed, before_that = state["history"][-1], (deploy or {}).get("replaced_in_this_sitting") or {}
        replaced = {"runs": int(before_that.get("runs", 0)) + 1,
                    "hours": round(float(before_that.get("hours", 0.0)) + float(closed.get("hours", 0.0)), 4),
                    "estimated_usd": round(float(before_that.get("estimated_usd", 0.0))
                                           + float(closed.get("estimated_usd", 0.0)), 4),
                    "upper_bound": bool(before_that.get("upper_bound") or closed.get("hours_is_upper_bound")),
                    # Round 5, F5: a run closed with the clock behind has no hours, and "already exists" stays said.
                    "unknown": bool(before_that.get("unknown") or closed.get("clock_went_back")),
                    "already_exists": bool(before_that.get("already_exists")
                                           or closed.get("create_answer") == "already exists")}

    out("Step 2 of 2: create the new model, endpoint configuration and endpoint.")
    kitlib.create_stack(aws, cfg, new_env, role_arn, state, args.state_path, price, deadline, kitlib.utc_now(), out,
                        price_source=price_source, replaced=replaced)
    if aws.dry_run:
        kitlib.wait_in_service(aws, cfg.endpoint_name, out, sleep, clock)
        out(f"DRY RUN finished: {aws.calls_printed} AWS call(s) printed, 0 made.")
        return 0

    out("THE NEW ENDPOINT NOW EXISTS. Treat it as billing from this moment.")
    out(f"Waiting for InService, polling every 30 s, for up to {args.wait_timeout_minutes:g} minutes.")
    status, description = kitlib.wait_in_service(aws, cfg.endpoint_name, out, sleep, clock,
                                                 timeout_s=args.wait_timeout_minutes * 60.0)
    seen = kitlib.utc_now()
    downtime = max(0.0, (seen - down_since).total_seconds() / 60.0)
    if status == "InService":
        state["deploy"]["in_service_utc"] = kitlib.iso(seen)
        kitlib.save_state(state, args.state_path)
        out(f"InService with {key}={value}.")
        out(f"Downtime: {downtime:.1f} minutes, from the DeleteEndpoint call at {kitlib.iso(down_since)} to InService "
            f"seen at {kitlib.iso(seen)} (UTC, this machine's clock, polled every 30 s). "
            "Write that number into RESULTS_TEMPLATE.md.")
        out("Next: python 55_observe.py   then   python 60_loadtest.py --label changed")
        for line in kitlib.billing_lines(state, kitlib.utc_now()):
            out(line)
        return 0
    out(f"The new endpoint did not reach InService. Final status: {status}.")
    out(f"Downtime so far: {downtime:.1f} minutes since the DeleteEndpoint call at {kitlib.iso(down_since)} (UTC), "
        "and it has not ended: nothing is serving.")
    if (description or {}).get("FailureReason"):
        out(f"FailureReason from SageMaker: {description['FailureReason']}")
    out("A setting that does not fit in GPU memory fails exactly like this. That is a result worth writing down.")
    out("Now: python 55_observe.py --logs-only   then   python 90_teardown.py   then   python 99_verify_clean.py")
    for line in kitlib.billing_lines(state, kitlib.utc_now()):  # the endpoint exists and is on record: it bills
        out(line)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "", bills=True)
    parser.add_argument("--set", required=True, metavar="NAME=VALUE", help="The one setting to change.")
    parser.add_argument("--price-per-hour", type=float, default=None, help="Only used by --dry-run without a state file.")
    parser.add_argument("--wait-timeout-minutes", type=float, default=45.0)
    parser.add_argument("--ignore-deadline", action="store_true", help="Run even though your teardown time has passed.")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.load_config()
    return run(args, cfg, Aws(cfg.region, args.dry_run))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
