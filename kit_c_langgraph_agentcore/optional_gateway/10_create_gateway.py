#!/usr/bin/env python3
"""optional_gateway/10_create_gateway.py: one gateway, one OpenAPI target.

Creates:
  1. an IAM role    <prefix>-kitc-gateway-role   (trusted by bedrock-agentcore, no permissions)
  2. a gateway      <prefix>-kitc-gateway        protocol MCP, inbound authorization AWS_IAM
  3. a target       federal-register             OpenAPI, inline, no outbound credential
AgentCore also creates a workload identity for the gateway.

Sources:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html              (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html          (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html           (read 2026-10-07)
Pattern for an OpenAPI target with no credential provider learned from (not copied):
  awslabs/agentcore-samples, 01-features/05-authenticate-and-authorize/
  08-okta-xaa-delegation-chain/deploy/02_create_gateway.py  (commit 3f2d283, read 2026-10-07)

Usage (from the kit folder):
    python optional_gateway/10_create_gateway.py --dry-run
    python optional_gateway/10_create_gateway.py --i-understand-this-bills
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import kitlib  # noqa: E402

SPEC_PATH = pathlib.Path(__file__).resolve().parent / "federal_register_openapi.json"
TARGET_NAME = "federal-register"
CONTROL = "bedrock-agentcore-control"


def gateway_trust_policy(account: str, region: str) -> dict:
    # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html (read 2026-10-07)
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "GatewayAssumeRolePolicy",
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account},
                "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:gateway/*"},
            },
        }],
    }


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    parser.add_argument("--wait-minutes", type=float, default=10.0)
    args = parser.parse_args(argv)
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)

    if not kitlib.confirm_billing(args, kitlib.PRICE_LINES_GATEWAY, out):
        return 2
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    acted = False
    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
        if not kitlib.check_place(state, cfg, account, out, "optional_gateway/10_create_gateway.py",
                                  dry_run=args.dry_run):
            return kitlib.EXIT_STATE_MISMATCH
        if state.get("gateway_id") and not args.dry_run:
            out(f"A gateway is already recorded in .state.json ({state.get('gateway_id')}).")
            return 1
        # Where this is being created, written before anything exists (the same record
        # 30_deploy.py writes; the two steps must be in the same Region, prefix and account).
        kitlib.record_place(state, cfg, account)
        # Each name is written down before the call that creates the thing (review round 4).
        state.set(gateway_role_name=cfg.gateway_role_name)
        acted = True
        try:
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateRole.html (read 2026-10-07)
            # UNVERIFIED: that a gateway service role with a trust policy and no permissions
            # policy is enough for an OpenAPI target that calls a public API with no credential.
            # The permissions page shows no policy for that case.
            role = aws.call(
                "iam", "create_role", RoleName=cfg.gateway_role_name,
                AssumeRolePolicyDocument=json.dumps(gateway_trust_policy(account, cfg.region)),
                Description="Service role for the aws-kits kit C AgentCore gateway",
                Tags=[{"Key": k, "Value": v} for k, v in kitlib.TAGS.items()],
                dry_result={"Role": {"Arn": f"arn:aws:iam::{account}:role/{cfg.gateway_role_name}"}})
            role_arn = role["Role"]["Arn"]
            out(f"[iam] created role {cfg.gateway_role_name}")
            if not args.dry_run:
                kitlib.sleep(15)
        except Exception as exc:
            if aws.error_code(exc) != "EntityAlreadyExists":
                raise
            # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html (read 2026-10-07)
            role_arn = aws.call("iam", "get_role", RoleName=cfg.gateway_role_name)["Role"]["Arn"]

        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateGateway.html (read 2026-10-07)
        create_called = kitlib.monotonic()
        state.set(gateway_name=cfg.gateway_name)  # the id comes back in the answer
        gateway = aws.call(
            CONTROL, "create_gateway", name=cfg.gateway_name, roleArn=role_arn, protocolType="MCP",
            authorizerType="AWS_IAM",
            description="aws-kits kit C: one Federal Register operation as an MCP tool",
            tags=dict(kitlib.TAGS),
            dry_result={"gatewayId": f"{cfg.gateway_name}-dryrun0000",
                        "gatewayUrl": f"https://{cfg.gateway_name}-dryrun0000.gateway."
                                      f"bedrock-agentcore.{cfg.region}.amazonaws.com/mcp",
                        "gatewayArn": f"arn:aws:bedrock-agentcore:{cfg.region}:{account}:gateway/"
                                      f"{cfg.gateway_name}-dryrun0000", "status": "CREATING"})
        gateway_id = gateway["gatewayId"]
        state.set(gateway_id=gateway_id, gateway_url=gateway.get("gatewayUrl"),
                  gateway_arn=gateway.get("gatewayArn"), gateway_name=cfg.gateway_name)
        out(f"[gateway] created {gateway_id} (status {gateway.get('status')})")

        def gateway_ready():
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetGateway.html (read 2026-10-07)
            info = aws.call(CONTROL, "get_gateway", gatewayIdentifier=gateway_id,
                            dry_result={"status": "READY"})
            if info.get("status") == "FAILED":
                raise RuntimeError(f"gateway FAILED: {info.get('statusReasons')}")
            if info.get("gatewayUrl"):
                state.set(gateway_url=info["gatewayUrl"])
            return info.get("status") == "READY"

        kitlib.wait_until(gateway_ready, timeout_s=args.wait_minutes * 60, interval_s=5,
                          what="the gateway is READY", dry_run=args.dry_run, out=out)
        if not args.dry_run:
            out("[timing] " + kitlib.elapsed_line("create call to gateway READY", create_called))

        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateGatewayTarget.html (read 2026-10-07)
        # No credentialProviderConfigurations: "No authorization" is documented as supported for
        # OpenAPI schema targets (gateway-outbound-auth.html, read 2026-10-07).
        state.set(gateway_target_name=TARGET_NAME)  # the id comes back in the answer
        target = aws.call(
            CONTROL, "create_gateway_target", gatewayIdentifier=gateway_id, name=TARGET_NAME,
            description="GET /agencies/{slug} on the public Federal Register API",
            targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": json.dumps(spec)}}},
            dry_result={"targetId": "dryrun0000", "status": "CREATING"})
        target_id = target["targetId"]
        state.set(gateway_target_id=target_id, gateway_target_name=TARGET_NAME)
        out(f"[gateway] created target {TARGET_NAME} ({target_id}, status {target.get('status')})")

        def target_ready():
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetGatewayTarget.html (read 2026-10-07)
            info = aws.call(CONTROL, "get_gateway_target", gatewayIdentifier=gateway_id,
                            targetId=target_id, dry_result={"status": "READY"})
            if info.get("status") in {"FAILED", "UPDATE_UNSUCCESSFUL", "SYNCHRONIZE_UNSUCCESSFUL"}:
                raise RuntimeError(f"target {info.get('status')}: {info.get('statusReasons')}")
            return info.get("status") == "READY"

        kitlib.wait_until(target_ready, timeout_s=args.wait_minutes * 60, interval_s=5,
                          what="the target is READY", dry_run=args.dry_run, out=out)
        if not args.dry_run:
            out("[timing] " + kitlib.elapsed_line("create call to gateway and target READY",
                                                  create_called))
    except Exception as exc:
        code = kitlib.explain_aws_error(exc, out)
        if acted and code == 2:
            code = 1  # 2 means "refused, nothing was done"; a create call had been sent
        out("Not finished. Run optional_gateway/90_teardown_gateway.py to remove what was created.")
        return code

    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made.")
        return 0
    out(f"Gateway ready: {state.get('gateway_url')}")
    out("Next: python optional_gateway/50_call_gateway_tools.py --dry-run")
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
