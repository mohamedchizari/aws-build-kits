#!/usr/bin/env python3
"""30_deploy.py: host the graph on Amazon Bedrock AgentCore Runtime.

Uses "direct code deployment" through boto3, the route AWS's own current
LangGraph sample takes: a zip in S3, one IAM role, one CreateAgentRuntime call.
No Docker, no ECR repository, no CodeBuild project.

Before creating anything it writes the Region, the name prefix and the account
id of this deploy into .state.json (a local, git-ignored file). Every later
script compares those three with the settings in use and stops on a mismatch.

Creates, in this order, and records each in .state.json as soon as it exists:
  1. an S3 bucket   <prefix>-kitc-code-<account>-<region>   and one object, the zip
  2. an IAM role    <prefix>-kitc-runtime-role              with one inline policy
  3. a runtime      <prefix>_kitc_fr_agent                  (AgentCore makes version 1 and
                                                            the DEFAULT endpoint itself)
AgentCore also makes, without being asked: a workload identity for the runtime
and, on first use, the log group /aws/bedrock-agentcore/runtimes/<id>-DEFAULT.
90_teardown.py removes all of it; 99_verify_clean.py checks that nothing is left.

Usage:
    python 30_deploy.py --dry-run
    python 30_deploy.py --i-understand-this-bills
"""
from __future__ import annotations

import json

import kitlib

MANIFEST = kitlib.BUILD_DIR / "package_manifest.json"


def trust_policy(account: str, region: str) -> dict:
    # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html (read 2026-10-07)
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AssumeRolePolicy",
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account},
                "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:*"},
            },
        }],
    }


def execution_policy(account: str, region: str, runtime_name: str,
                     code_object_arn: str | None = None) -> dict:
    """The execution role policy AWS documents for direct code deployment.

    doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html (read 2026-10-07)
    Same statements as the page ("Amazon Bedrock AgentCore direct deploy execution role"),
    with this account, Region and runtime name filled in. That policy has no S3 statement.

    Two AWS pages disagree here. The direct code deployment page says "The execution role
    must include basic Amazon Bedrock AgentCore runtime permissions, S3 access permissions
    for your deployment package, and CloudWatch Logs permissions for observability":
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html (read 2026-10-07)
    UNVERIFIED: which page is right. The default follows the permissions page. If
    CreateAgentRuntime fails on reading the artifact, set EXECUTION_ROLE_S3_READ=true in
    config.env and deploy again: code_object_arn is then passed and one statement is added
    that lets the role read exactly the uploaded zip and nothing else.
    """
    logs = f"arn:aws:logs:{region}:{account}:log-group"
    extra = []
    if code_object_arn:
        extra.append({"Sid": "ReadTheDeploymentPackage", "Effect": "Allow",
                      "Action": ["s3:GetObject"], "Resource": [code_object_arn]})
    return {
        "Version": "2012-10-17",
        "Statement": extra + [
            {"Effect": "Allow",
             "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
             "Resource": [f"{logs}:/aws/bedrock-agentcore/runtimes/*"]},
            {"Effect": "Allow",
             "Action": ["logs:PutResourcePolicy"],
             "Resource": [f"{logs}:/aws/bedrock-agentcore/runtimes/{runtime_name}-*"]},
            {"Effect": "Allow",
             "Action": ["logs:DescribeLogGroups"],
             "Resource": [f"{logs}:*"]},
            {"Effect": "Allow",
             "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": [f"{logs}:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]},
            {"Effect": "Allow",
             "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords",
                        "xray:GetSamplingRules", "xray:GetSamplingTargets"],
             "Resource": ["*"]},
            {"Effect": "Allow",
             "Action": "cloudwatch:PutMetricData",
             "Resource": "*",
             "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}},
            {"Sid": "BedrockModelInvocation",
             "Effect": "Allow",
             "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
             "Resource": ["arn:aws:bedrock:*::foundation-model/*",
                          f"arn:aws:bedrock:{region}:{account}:*"]},
        ],
    }


def load_manifest(dry_run: bool) -> dict:
    if MANIFEST.exists() and kitlib.PACKAGE_ZIP.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    if dry_run:
        return {"entry_point": ["opentelemetry-instrument", "agentcore_app.py"],
                "python_runtime": "PYTHON_3_13", "zipped_bytes": 0, "sha256": "not-built", "otel": True}
    raise FileNotFoundError("run 20_package.py first: .build/deployment_package.zip is missing")


def ensure_bucket(aws: kitlib.Aws, cfg: kitlib.Config, bucket: str, account: str, out) -> None:
    create = {"Bucket": bucket}
    if cfg.region != "us-east-1":
        create["CreateBucketConfiguration"] = {"LocationConstraint": cfg.region}
    try:
        # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateBucket.html (read 2026-10-07)
        aws.call("s3", "create_bucket", **create)
        out(f"[s3] created bucket {bucket.replace(account, kitlib.mask_account(account))}")
    except Exception as exc:
        if aws.error_code(exc) != "BucketAlreadyOwnedByYou":
            raise
        out("[s3] bucket already exists in this account, reusing it")
    # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketTagging.html (read 2026-10-07)
    aws.call("s3", "put_bucket_tagging", Bucket=bucket, ExpectedBucketOwner=account,
             Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in kitlib.TAGS.items()]})


def ensure_role(aws: kitlib.Aws, cfg: kitlib.Config, account: str, out,
                code_object_arn: str | None = None) -> str:
    try:
        # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateRole.html (read 2026-10-07)
        role = aws.call(
            "iam", "create_role",
            RoleName=cfg.role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy(account, cfg.region)),
            Description="Execution role for the aws-kits kit C AgentCore runtime",
            Tags=[{"Key": k, "Value": v} for k, v in kitlib.TAGS.items()],
            dry_result={"Role": {"Arn": f"arn:aws:iam::{account}:role/{cfg.role_name}"}},
        )
        role_arn = role["Role"]["Arn"]
        out(f"[iam] created role {cfg.role_name}")
        created = True
    except Exception as exc:
        if aws.error_code(exc) != "EntityAlreadyExists":
            raise
        # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html (read 2026-10-07)
        role_arn = aws.call("iam", "get_role", RoleName=cfg.role_name)["Role"]["Arn"]
        out(f"[iam] role {cfg.role_name} already exists, reusing it")
        created = False
    # doc: https://docs.aws.amazon.com/IAM/latest/APIReference/API_PutRolePolicy.html (read 2026-10-07)
    aws.call("iam", "put_role_policy", RoleName=cfg.role_name, PolicyName=cfg.role_policy_name,
             PolicyDocument=json.dumps(execution_policy(account, cfg.region, cfg.runtime_name,
                                                        code_object_arn)))
    if code_object_arn:
        out("[iam] EXECUTION_ROLE_S3_READ is on: the role may also read the uploaded zip")
    if created and not aws.dry_run:
        out("[iam] waiting 15 seconds for the new role to become usable")
        kitlib.sleep(15)
    return role_arn


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    parser.add_argument("--wait-minutes", type=float, default=20.0,
                        help="how long to wait for the runtime to become READY (default 20)")
    args = parser.parse_args(argv)
    out = kitlib.redacting(out)  # review round 5, F13: no line carries a full account id
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)

    version, cpu_rate, mem_rate = cfg.rates()
    prices = kitlib.PRICE_LINES_RUNTIME + [
        f"This deployment asks for platform version {cfg.platform_version or 'default (V1)'}.",
        "Creating the runtime starts no session, so no vCPU or memory charge accrues until",
        "50_invoke_hosted.py opens one. The stored zip bills from the moment it is uploaded.",
    ] + kitlib.unstopped_session_lines(cfg.idle_timeout_s, cfg.max_lifetime_s) + kitlib.PRICE_LINES_S3
    if not kitlib.confirm_billing(args, prices, out):
        return 2

    try:
        manifest = load_manifest(args.dry_run)
    except FileNotFoundError as exc:
        out(str(exc))
        return 1

    acted = False  # True from the moment the first create call is about to be sent
    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
        if not kitlib.check_place(state, cfg, account, out, "30_deploy.py", dry_run=args.dry_run):
            return kitlib.EXIT_STATE_MISMATCH
        bucket = cfg.bucket_name(account)
        out(f"Deploying {cfg.runtime_name} to {cfg.region} in account {kitlib.mask_account(account)}")

        if state.get("runtime_id") and not args.dry_run:
            out(f"A runtime is already recorded in .state.json ({state.get('runtime_id')}).")
            out("Run 90_teardown.py first. It clears the entry once the runtime is confirmed gone.")
            return 1

        # ---- 0. where this deploy is made, written before anything exists ----
        kitlib.record_place(state, cfg, account)

        # Every name below is written to .state.json BEFORE the call that creates the thing,
        # so a process that dies right after a call has still left its name on record (review
        # round 4: the role was created, the script slept 15 seconds, and only then wrote it
        # down). A name on record is not proof that the thing exists: the call may have failed.
        # ---- 1. code bucket and the zip ----
        state.set(bucket=bucket, code_key=cfg.code_key)
        acted = True
        ensure_bucket(aws, cfg, bucket, account, out)
        body = kitlib.PACKAGE_ZIP.read_bytes() if kitlib.PACKAGE_ZIP.exists() else b""
        # doc: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html (read 2026-10-07)
        aws.call("s3", "put_object", Bucket=bucket, Key=cfg.code_key, Body=body,
                 ExpectedBucketOwner=account,
                 Tagging="&".join(f"{k}={v}" for k, v in kitlib.TAGS.items()))
        out(f"[s3] uploaded {len(body) / 1e6:.1f} MB to s3://<bucket>/{cfg.code_key}")

        # ---- 2. execution role ----
        code_object_arn = f"arn:aws:s3:::{bucket}/{cfg.code_key}" if cfg.role_s3_read else None
        state.set(role_name=cfg.role_name, role_policy_name=cfg.role_policy_name)
        role_arn = ensure_role(aws, cfg, account, out, code_object_arn)

        # ---- 3. the runtime ----
        request = {
            "agentRuntimeName": cfg.runtime_name,
            "description": "aws-kits kit C: LangGraph agent with Federal Register tools",
            "agentRuntimeArtifact": {
                "codeConfiguration": {
                    "code": {"s3": {"bucket": bucket, "prefix": cfg.code_key}},
                    "runtime": manifest.get("python_runtime", cfg.python_runtime),
                    "entryPoint": manifest["entry_point"],
                }
            },
            "roleArn": role_arn,
            "networkConfiguration": {"networkMode": "PUBLIC"},
            "protocolConfiguration": {"serverProtocol": "HTTP"},
            # Short timeouts on purpose: an idle session keeps billing memory until it is
            # stopped or this timeout ends it. The service default is 900 s idle, 8 h lifetime.
            "lifecycleConfiguration": {
                "idleRuntimeSessionTimeout": cfg.idle_timeout_s,
                "maxLifetime": cfg.max_lifetime_s,
            },
            "environmentVariables": {
                "MODEL_ID": cfg.model_id,
                "KIT_BEDROCK_REGION": cfg.region,
                # The contract page says the server must listen on host 0.0.0.0, port 8080.
                # The SDK picks 127.0.0.1 unless it detects Docker, so the address is passed
                # explicitly; agentcore_app.py reads it. Locally it stays 127.0.0.1.
                # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html (read 2026-10-07)
                "KIT_BIND_HOST": "0.0.0.0",
                # Keep prompts and model text out of the LangChain spans. The model's text
                # includes what the answer check withholds. Read in the package source
                # (opentelemetry-instrumentation-langchain 0.62.4, utils.py) on 2026-10-07:
                # content is recorded unless this variable is "false".
                # UNVERIFIED: what the spans hold on AgentCore with it set (not run on AWS).
                "TRACELOOP_TRACE_CONTENT": "false",
            },
            "tags": dict(kitlib.TAGS),
        }
        if cfg.platform_version:
            # AWS: "If you omit platformVersion when you create a runtime, the runtime uses V1."
            # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html (read 2026-10-07)
            request["platformVersion"] = cfg.platform_version
        # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateAgentRuntime.html (read 2026-10-07)
        # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html (read 2026-10-07)
        # UNVERIFIED: how the runtime runs "opentelemetry-instrument" from a zip built with
        # `uv pip install --target`. The documented example passes exactly this entryPoint.
        # AWS's own packager (aws/agentcore-cli, src/lib/packaging/helpers.ts, commit dd6304e)
        # rewrites build-machine shebangs in bin/ to "#!/usr/bin/env python3", which shows the
        # script is executed from the zip's bin/ folder; 20_package.py now does the same.
        # If the runtime still fails to start, set ENABLE_OTEL=false, re-run 20_package.py
        # and deploy again.
        create_called = kitlib.monotonic()
        # The id comes back in the answer, so only the name can be written first. Teardown and
        # the clean check find a runtime by this name.
        state.set(runtime_name=cfg.runtime_name, runtime_create_sent_at=kitlib.utc_now_iso())
        created = aws.call(
            "bedrock-agentcore-control", "create_agent_runtime",
            dry_result={"agentRuntimeId": f"{cfg.runtime_name}-dryrun0000",
                        "agentRuntimeArn": f"arn:aws:bedrock-agentcore:{cfg.region}:{account}:"
                                           f"runtime/{cfg.runtime_name}-dryrun0000",
                        "agentRuntimeVersion": "1", "status": "CREATING"},
            **request,
        )
        runtime_id = created["agentRuntimeId"]
        runtime_arn = created["agentRuntimeArn"]
        state.set(runtime_id=runtime_id, runtime_arn=runtime_arn, runtime_name=cfg.runtime_name,
                  runtime_version=created.get("agentRuntimeVersion"),
                  workload_identity_arn=(created.get("workloadIdentityDetails") or {}).get(
                      "workloadIdentityArn"),
                  requested_platform_version=cfg.platform_version or "default",
                  idle_timeout_s=cfg.idle_timeout_s, max_lifetime_s=cfg.max_lifetime_s,
                  model_id=cfg.model_id, package_sha256=manifest.get("sha256"),
                  deployed_at=kitlib.utc_now_iso())
        out(f"[agentcore] created runtime {runtime_id} (status {created.get('status')})")

        # ---- wait for READY ----
        last = {}

        def ready():
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetAgentRuntime.html (read 2026-10-07)
            info = aws.call("bedrock-agentcore-control", "get_agent_runtime",
                            agentRuntimeId=runtime_id, dry_result={"status": "READY"})
            last.update(info)
            status = info.get("status")
            if status in {"CREATE_FAILED", "UPDATE_FAILED"}:
                raise RuntimeError(f"runtime {status}: {info.get('failureReason', 'no reason given')}")
            if status != "READY":
                out(f"[agentcore] status {status}, waiting")
            return status == "READY"

        kitlib.wait_until(ready, timeout_s=args.wait_minutes * 60, interval_s=15,
                          what="the runtime is READY", dry_run=args.dry_run, out=out)
        if not args.dry_run:
            out("[timing] " + kitlib.elapsed_line("create call to runtime READY", create_called))
        reported = last.get("platformVersion")
        lifecycle = last.get("lifecycleConfiguration") or {}
        state.set(reported_platform_version=reported or "not reported",
                  # what the service says it applied, when it says so; else what was asked for
                  idle_timeout_s=lifecycle.get("idleRuntimeSessionTimeout", cfg.idle_timeout_s),
                  max_lifetime_s=lifecycle.get("maxLifetime", cfg.max_lifetime_s))
        version, cpu_rate, mem_rate = cfg.rates(reported, cfg.platform_version)
        out(f"[agentcore] runtime READY. Platform version reported by the service: "
            f"{reported or 'not reported'}"
            + ("" if reported else f" (using {version}: " + (
                "that is what this deploy asked for)" if cfg.platform_version
                else "AWS documents V1 when it is left out)")))

        # ---- the DEFAULT endpoint AgentCore created ----
        def endpoint_ready():
            # doc: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_ListAgentRuntimeEndpoints.html (read 2026-10-07)
            page = aws.call("bedrock-agentcore-control", "list_agent_runtime_endpoints",
                            agentRuntimeId=runtime_id,
                            dry_result={"runtimeEndpoints": [{"name": "DEFAULT", "status": "READY"}]})
            endpoints = {e["name"]: e["status"] for e in page.get("runtimeEndpoints", [])}
            out(f"[agentcore] endpoints: {endpoints or 'none yet'}")
            if any(s in {"CREATE_FAILED", "UPDATE_FAILED"} for s in endpoints.values()):
                raise RuntimeError(f"an endpoint failed: {endpoints}")
            return bool(endpoints) and all(s == "READY" for s in endpoints.values())

        kitlib.wait_until(endpoint_ready, timeout_s=args.wait_minutes * 60, interval_s=15,
                          what="the DEFAULT endpoint is READY", dry_run=args.dry_run, out=out)
        if not args.dry_run:
            out("[timing] " + kitlib.elapsed_line("create call to DEFAULT endpoint READY", create_called))
    except Exception as exc:
        code = kitlib.explain_aws_error(exc, out)
        if acted and code == 2:
            # 2 means "refused, nothing was done". A stop after the first create call was sent
            # is not that, whatever stopped it (review round 4: credentials that ran out while
            # this script waited for the runtime gave 2).
            code = 1
        message = str(((getattr(exc, "response", None) or {}).get("Error") or {}).get("Message") or "")
        if aws.error_code(exc) == "ConflictException" or "already exists" in message.lower():
            # Seen with the emulator in review round 4: the answer to CreateAgentRuntime was lost,
            # the SDK sent the call again, and AWS answered that the runtime already exists.
            # Deploying again then fails the same way until the first runtime is removed.
            out("AWS says something with this name already exists. If that is the runtime, an earlier "
                "create call went through (its answer may have been lost on the way). Deploying again "
                "will fail the same way: run 90_teardown.py first, then deploy.")
        if acted:
            out("Deployment did not finish. The name of everything this run may have created is in "
                ".state.json (a runtime's id only if AWS answered the create call); "
                "run 90_teardown.py, which looks by name, and then 99_verify_clean.py.")
        else:
            out("Deployment did not start: no create call was sent.")
        return code

    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made and .state.json was not written.")
        return 0
    out("")
    out(f"Deployed at {state.get('deployed_at')} (UTC, the time of the create call). 90_teardown.py "
        "prints the hours the runtime existed from this.")
    out(f"Rates that apply ({version}, {cfg.rates_basis(reported, cfg.platform_version)}): "
        f"${cpu_rate} per vCPU-hour, ${mem_rate} per GB-hour, only while a session exists.")
    out("Next: python 40_enable_observability.py --dry-run   (optional but needed for session cost)")
    out("      python 50_invoke_hosted.py --dry-run")
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
