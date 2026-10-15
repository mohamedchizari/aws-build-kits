#!/usr/bin/env python3
"""optional_gateway/90_teardown_gateway.py: delete only the gateway step's resources.

Finds by name prefix, not only from .state.json: gateways named <prefix>-kitc-*,
their targets, the role <prefix>-kitc-gateway-role and any workload identity
left with the gateway's name. The main 90_teardown.py does the same and more.

Like every script that reads .state.json, it first compares the Region, prefix
and account the file records with the ones in use, and stops on a mismatch, or
when the file cannot be used. The Region, prefix and account stay recorded
afterwards; 90_teardown.py moves them into the history once nothing of the kit
is left.

After the delete call it waits until AWS answers that the gateway does not
exist. A gateway still listed as DELETING when the wait ends is not gone: the
record is kept and the exit code is 1. The gateway role is deleted only when no
gateway of this kit could be using it in another Region (kit_resources.py).

A --dry-run exits 3, not 0: it deletes nothing.

Usage (from the kit folder):
    python optional_gateway/90_teardown_gateway.py --dry-run
    python optional_gateway/90_teardown_gateway.py
    python 99_verify_clean.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import kit_resources  # noqa: E402
import kitlib  # noqa: E402


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=False)
    args = parser.parse_args(argv)
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    if not kitlib.check_place(state, cfg, account, out, "optional_gateway/90_teardown_gateway.py",
                              dry_run=args.dry_run):
        return kitlib.EXIT_STATE_MISMATCH
    try:
        found = kit_resources.discover(aws, cfg, out)
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    gateway_only = {
        "gateways": found["gateways"],
        "roles": [r for r in found["roles"] if r["name"] == cfg.gateway_role_name],
    }
    out(f"Found {len(gateway_only['gateways'])} gateway(s) and {len(gateway_only['roles'])} "
        "gateway role(s).")
    ok = True
    kept: list[str] = []
    try:
        ok &= kit_resources.delete_gateways(aws, gateway_only, out)
        # A gateway that .state.json names is asked for by id: its record is cleared only when
        # AWS answers that it does not exist.
        ok &= kit_resources.confirm_recorded_absent(aws, gateway_only, out,
                                                    gateway_id=state.get("gateway_id"))
        if not ok:
            out("A gateway is not confirmed gone, so its workload identity and role were left in place.")
        else:
            if not found["runtimes"]:
                # With no runtime left, any identity carrying the kit's prefix belongs to the gateway.
                ok &= kit_resources.delete_workload_identities(aws, cfg, out)
            else:
                out("A runtime still exists, so workload identities are left for 90_teardown.py.")
            if gateway_only["roles"]:
                # Only buckets and Regions are looked at here, never the runtime's own role.
                reasons = kit_resources.roles_in_use_elsewhere(
                    aws, cfg, {"roles": gateway_only["roles"], "buckets": found["buckets"]}, account, out,
                    history=state.get("history", []) or [],
                    aws_for_region=lambda region: kitlib.Aws(region, dry_run=args.dry_run, out=out))
                if reasons:
                    kept = [f"IAM role {r['name']}" for r in gateway_only["roles"]]
                    out(f"[keep] the gateway role was NOT deleted, because {'; '.join(reasons)}.")
                else:
                    ok &= kit_resources.delete_roles(aws, gateway_only, out)
    except Exception as exc:
        kitlib.explain_aws_error(exc, out)
        ok = False
    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made.")
        out(f"Exit code {kitlib.EXIT_DRY_RUN_PROVES_NOTHING}, not 0: a dry run deletes nothing.")
        return kitlib.EXIT_DRY_RUN_PROVES_NOTHING
    if ok:
        state.remove("gateway_id", "gateway_url", "gateway_arn", "gateway_name",
                     "gateway_target_id", "gateway_target_name", "gateway_role_name")
    if not ok:
        out("Gateway teardown finished WITH ERRORS; run it again.")
    elif kept:
        out(f"Gateway teardown finished, BUT {', '.join(kept)} was left in place (see above).")
    else:
        out("Gateway teardown finished.")
    out("Now prove it: python 99_verify_clean.py")
    return 0 if ok and not kept else 1


if __name__ == "__main__":
    kitlib.script_main(main)
