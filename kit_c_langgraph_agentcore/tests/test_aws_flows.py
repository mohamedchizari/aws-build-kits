"""Every AWS-calling script, run for real against botocore Stubber. Offline.

What this proves: each script sends requests whose parameter names, types and
required fields match the service models in the installed AWS SDK, sends them
in a workable order, and handles the documented response shapes.
What it does not prove: that AWS accepts the requests or behaves as documented.
No AWS call is made by any test.
"""
from __future__ import annotations

import datetime as dt
import io
import json

import pytest
from botocore.response import StreamingBody
from conftest import ACCOUNT, RUNTIME_ARN, RUNTIME_ID, load_script, make_aws

NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc)
CONTROL = "bedrock-agentcore-control"
DATA = "bedrock-agentcore"
BUCKET = f"kitdemo-kitc-code-{ACCOUNT}-us-east-1"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-runtime-role"
ANY = __import__("botocore.stub", fromlist=["ANY"]).ANY


def identity(stubs):
    stubs.add("sts", "get_caller_identity",
              {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/someone", "UserId": "AIDAEXAMPLE"}, {})


def runtime_summary(name="kitdemo_kitc_fr_agent", status="READY"):
    return {"agentRuntimeArn": RUNTIME_ARN, "agentRuntimeId": RUNTIME_ID, "agentRuntimeVersion": "1",
            "agentRuntimeName": name, "description": "d", "lastUpdatedAt": NOW, "status": status}


def runtime_detail(status="READY", **extra):
    body = {"agentRuntimeArn": RUNTIME_ARN, "agentRuntimeName": "kitdemo_kitc_fr_agent",
            "agentRuntimeId": RUNTIME_ID, "agentRuntimeVersion": "1", "createdAt": NOW,
            "lastUpdatedAt": NOW, "roleArn": ROLE_ARN, "status": status,
            "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 120, "maxLifetime": 900}}
    body.update(extra)
    return body


def log_groups_listed_again(stubs, runtime_groups=(), vended_groups=()):
    """The two calls 90_teardown.py makes once the runtime is gone: it lists the log groups a
    second time, because AgentCore creates the runtime's own group by itself (round 4, m10)."""
    stubs.add("logs", "describe_log_groups", {"logGroups": list(runtime_groups)},
              {"logGroupNamePrefix": "/aws/bedrock-agentcore/runtimes/kitdemo_kitc_fr_agent-"})
    stubs.add("logs", "describe_log_groups", {"logGroups": list(vended_groups)},
              {"logGroupNamePrefix": "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-"})


def streaming(payload: dict) -> StreamingBody:
    raw = json.dumps(payload).encode("utf-8")
    return StreamingBody(io.BytesIO(raw), len(raw))


def empty_discovery(stubs, *, runtimes=(), gateways=(), identities=(), roles=(), buckets=(),
                    runtime_groups=(), vended_groups=(), deliveries=(), sources=(),
                    destinations=(), tagged=()):
    """Queue the eleven read calls kit_resources.discover() makes, in order."""
    stubs.add(CONTROL, "list_agent_runtimes", {"agentRuntimes": list(runtimes)}, {"maxResults": 100})
    stubs.add(CONTROL, "list_gateways", {"items": list(gateways)}, {"maxResults": 100})
    for g in gateways:
        stubs.add(CONTROL, "list_gateway_targets",
                  {"items": [{"targetId": "tgt0000001", "name": "federal-register", "status": "READY",
                              "createdAt": NOW, "updatedAt": NOW}]},
                  {"gatewayIdentifier": g["gatewayId"], "maxResults": 100})
    stubs.add(CONTROL, "list_workload_identities", {"workloadIdentities": list(identities)},
              {"maxResults": 20})
    stubs.add("iam", "list_roles", {"Roles": list(roles)}, {"MaxItems": 1000})
    stubs.add("s3", "list_buckets", {"Buckets": list(buckets)},
              {"Prefix": "kitdemo-kitc-", "MaxBuckets": 1000})
    stubs.add("logs", "describe_log_groups", {"logGroups": list(runtime_groups)},
              {"logGroupNamePrefix": "/aws/bedrock-agentcore/runtimes/kitdemo_kitc_fr_agent-"})
    stubs.add("logs", "describe_log_groups", {"logGroups": list(vended_groups)},
              {"logGroupNamePrefix": "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-"})
    stubs.add("logs", "describe_deliveries", {"deliveries": list(deliveries)}, {"limit": 50})
    stubs.add("logs", "describe_delivery_sources", {"deliverySources": list(sources)}, {"limit": 50})
    stubs.add("logs", "describe_delivery_destinations", {"deliveryDestinations": list(destinations)},
              {"limit": 50})
    stubs.add("resourcegroupstaggingapi", "get_resources",
              {"ResourceTagMappingList": list(tagged)},
              {"TagFilters": [{"Key": "project", "Values": ["aws-kits"]},
                              {"Key": "kit", "Values": ["kit-c"]}], "ResourcesPerPage": 100})


# ====================================================================== 00_check
def _check_stubs(stubs, *, authorization="AUTHORIZED", destination="XRay", runtimes=(),
                 entitlement="AVAILABLE"):
    identity(stubs)
    stubs.add("bedrock", "get_inference_profile",
              {"inferenceProfileName": "US Nova Micro", "inferenceProfileId": "us.amazon.nova-micro-v1:0",
               "inferenceProfileArn": f"arn:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/us.amazon.nova-micro-v1:0",
               "status": "ACTIVE", "type": "SYSTEM_DEFINED",
               "models": [{"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0"},
                          {"modelArn": "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-micro-v1:0"}]},
              {"inferenceProfileIdentifier": "us.amazon.nova-micro-v1:0"})
    stubs.add("bedrock", "get_foundation_model",
              {"modelDetails": {"modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0",
                                "modelId": "amazon.nova-micro-v1:0", "modelLifecycle": {"status": "ACTIVE"},
                                "inferenceTypesSupported": ["ON_DEMAND"]}},
              {"modelIdentifier": "amazon.nova-micro-v1:0"})
    stubs.add("bedrock", "get_foundation_model_availability",
              {"modelId": "amazon.nova-micro-v1:0", "authorizationStatus": authorization,
               "entitlementAvailability": entitlement, "regionAvailability": "AVAILABLE",
               "agreementAvailability": {"status": entitlement}},
              {"modelId": "amazon.nova-micro-v1:0"})
    stubs.add(CONTROL, "list_agent_runtimes", {"agentRuntimes": list(runtimes)}, {"maxResults": 100})
    stubs.add("xray", "get_trace_segment_destination", {"Destination": destination, "Status": "ACTIVE"}, {})


def _uv_found(monkeypatch, script, found=True):
    """Found by the run on the Mac, 7 Oct 2026: that machine has no `uv`, so the preflight ended
    "PREFLIGHT FAILED: 1 problem(s)" and two tests that expect a pass failed with the kit unchanged. What the
    preflight finds on PATH is now set by the test, in both directions."""
    monkeypatch.setattr(script.shutil, "which", lambda name: "/usr/local/bin/uv" if found and name == "uv" else None)


def test_check_stops_when_uv_is_not_installed(kit, stubs, monkeypatch):
    script = load_script("00_check.py")
    _uv_found(monkeypatch, script, found=False)
    _check_stubs(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    text = "\n".join(lines)
    assert "[local] uv: NOT FOUND" in text
    assert "uv is not installed; 20_package.py needs it to fetch arm64 wheels" in text
    assert lines[-1] == "PREFLIGHT FAILED: 1 problem(s)."
    stubs.assert_all_used()  # the account checks still ran: one sitting shows every problem


def test_check_happy_path(kit, stubs, monkeypatch):
    script = load_script("00_check.py")
    _uv_found(monkeypatch, script)
    _check_stubs(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 0
    text = "\n".join(lines)
    assert "account ********0000" in text and ACCOUNT not in text
    assert "routes to ['us-east-1', 'us-west-2']" in text
    assert "authorization AUTHORIZED" in text
    assert "Transaction Search: OFF" in text
    assert "PREFLIGHT OK with 1 warning(s)." in text
    stubs.assert_all_used()


def test_check_fails_when_the_model_is_not_authorized(kit, stubs):
    script = load_script("00_check.py")
    _check_stubs(stubs, authorization="NOT_AUTHORIZED", destination="CloudWatchLogs",
                 runtimes=[runtime_summary()])
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    text = "\n".join(lines)
    assert "PROBLEM: your principal is not authorized for this model" in text
    assert "a runtime named kitdemo_kitc_fr_agent already exists" in text
    assert "Transaction Search: ON" in text
    # review minor 12: the deploy script does not reuse a runtime, and the message must not say so
    assert "30_deploy.py will not reuse it" in text and "will reuse it" not in text


def test_check_points_to_the_readme_section_that_has_the_anthropic_form(kit, stubs, monkeypatch):
    script = load_script("00_check.py")
    _uv_found(monkeypatch, script)
    _check_stubs(stubs, entitlement="NOT_AVAILABLE")
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 0
    text = "\n".join(lines)
    assert "README section 2" in text and "README section 3)" not in text.split("use-case form")[1][:60]
    # the price lines printed by the preflight carry the corrected units and the bound
    assert "per 1M input tokens" in text and "If a session is never stopped" in text


def test_check_reports_missing_credentials_cleanly(kit, stubs):
    script = load_script("00_check.py")
    stubs.add_error("sts", "get_caller_identity", "ExpiredToken", 403)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    assert any("ExpiredToken" in line for line in lines)
    assert lines[-1].startswith("PREFLIGHT INCOMPLETE")


# ====================================================================== 30_deploy
@pytest.fixture()
def built_package(kit):
    kit.BUILD_DIR.mkdir(parents=True)
    kit.PACKAGE_ZIP.write_bytes(b"PK-not-a-real-zip")
    (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps({
        "entry_point": ["opentelemetry-instrument", "agentcore_app.py"],
        "python_runtime": "PYTHON_3_13", "sha256": "abc", "zipped_bytes": 17, "otel": True}))


def _deploy_script(kit):
    script = load_script("30_deploy.py")
    script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    return script


def test_deploy_refuses_without_the_billing_flag(kit, stubs, built_package):
    script = _deploy_script(kit)
    lines: list[str] = []
    state = kit.State(kit.STATE_PATH)
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 2
    text = "\n".join(lines)
    assert "$0.0895 per vCPU-hour" in text and "https://aws.amazon.com/bedrock/agentcore/pricing/" in text
    assert "Stopped. Nothing was created." in text
    assert stubs.clients == {} and not kit.STATE_PATH.exists()


def test_deploy_happy_path_sends_the_documented_request(kit, stubs, built_package):
    script = _deploy_script(kit)
    identity(stubs)
    stubs.add("s3", "create_bucket", {}, {"Bucket": BUCKET})
    stubs.add("s3", "put_bucket_tagging", {}, {
        "Bucket": BUCKET, "ExpectedBucketOwner": ACCOUNT,
        "Tagging": {"TagSet": [{"Key": "project", "Value": "aws-kits"}, {"Key": "kit", "Value": "kit-c"}]}})
    stubs.add("s3", "put_object", {}, {
        "Bucket": BUCKET, "Key": "kitdemo_kitc_fr_agent/deployment_package.zip",
        "Body": b"PK-not-a-real-zip", "ExpectedBucketOwner": ACCOUNT,
        "Tagging": "project=aws-kits&kit=kit-c"})
    stubs.add("iam", "create_role",
              {"Role": {"Path": "/", "RoleName": "kitdemo-kitc-runtime-role", "RoleId": "AROAEXAMPLEEXAMPLE1",
                        "Arn": ROLE_ARN, "CreateDate": NOW}},
              {"RoleName": "kitdemo-kitc-runtime-role", "AssumeRolePolicyDocument": ANY,
               "Description": ANY,
               "Tags": [{"Key": "project", "Value": "aws-kits"}, {"Key": "kit", "Value": "kit-c"}]})
    stubs.add("iam", "put_role_policy", {}, {"RoleName": "kitdemo-kitc-runtime-role",
                                             "PolicyName": "kitdemo-kitc-runtime-policy",
                                             "PolicyDocument": ANY})
    stubs.add(CONTROL, "create_agent_runtime",
              {"agentRuntimeArn": RUNTIME_ARN, "agentRuntimeId": RUNTIME_ID, "agentRuntimeVersion": "1",
               "createdAt": NOW, "status": "CREATING",
               "workloadIdentityDetails": {"workloadIdentityArn": "arn:aws:bedrock-agentcore:us-east-1:"
                                           f"{ACCOUNT}:workload-identity-directory/default/workload-identity/x"}},
              {"agentRuntimeName": "kitdemo_kitc_fr_agent",
               "description": ANY,
               "agentRuntimeArtifact": {"codeConfiguration": {
                   "code": {"s3": {"bucket": BUCKET,
                                   "prefix": "kitdemo_kitc_fr_agent/deployment_package.zip"}},
                   "runtime": "PYTHON_3_13",
                   "entryPoint": ["opentelemetry-instrument", "agentcore_app.py"]}},
               "roleArn": ROLE_ARN,
               "networkConfiguration": {"networkMode": "PUBLIC"},
               "protocolConfiguration": {"serverProtocol": "HTTP"},
               "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 120, "maxLifetime": 900},
               "environmentVariables": {"MODEL_ID": "us.amazon.nova-micro-v1:0",
                                        "KIT_BEDROCK_REGION": "us-east-1",
                                        "KIT_BIND_HOST": "0.0.0.0",
                                        # round 2: keep model text out of the LangChain spans
                                        "TRACELOOP_TRACE_CONTENT": "false"},
               "tags": {"project": "aws-kits", "kit": "kit-c"}})
    stubs.add(CONTROL, "get_agent_runtime", runtime_detail("CREATING"), {"agentRuntimeId": RUNTIME_ID})
    stubs.add(CONTROL, "get_agent_runtime", runtime_detail("READY"), {"agentRuntimeId": RUNTIME_ID})
    endpoint = {"name": "DEFAULT", "agentRuntimeEndpointArn": RUNTIME_ARN + "/runtime-endpoint/DEFAULT",
                "agentRuntimeArn": RUNTIME_ARN, "status": "READY", "id": "DEFAULT-abcdefghij",
                "createdAt": NOW, "lastUpdatedAt": NOW}
    stubs.add(CONTROL, "list_agent_runtime_endpoints", {"runtimeEndpoints": [endpoint]},
              {"agentRuntimeId": RUNTIME_ID})

    lines: list[str] = []
    state = kit.State(kit.STATE_PATH)
    rc = script.main(["--i-understand-this-bills"], aws=make_aws(kit, stubs, lines),
                     out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    saved = json.loads(kit.STATE_PATH.read_text())
    assert saved["runtime_id"] == RUNTIME_ID and saved["runtime_arn"] == RUNTIME_ARN
    assert saved["bucket"] == BUCKET and saved["role_name"] == "kitdemo-kitc-runtime-role"
    assert saved["reported_platform_version"] == "not reported"
    assert saved["requested_platform_version"] == "default"
    # the place of the deploy is recorded, and what the service says it applied
    assert (saved["region"], saved["prefix"], saved["account_id"]) == ("us-east-1", "kitdemo", ACCOUNT)
    assert (saved["idle_timeout_s"], saved["max_lifetime_s"]) == (120, 900)
    text = "\n".join(lines)
    assert ACCOUNT not in text  # the account id is masked in everything printed
    assert "********0000" in text
    # the times RESULTS_TEMPLATE.md asks for are printed, with a UTC stamp (numbers review, M4)
    assert "[timing] create call to runtime READY: " in text
    assert "[timing] create call to DEFAULT endpoint READY: " in text
    assert text.count("(UTC)") >= 2 and f"Deployed at {saved['deployed_at']} (UTC" in text
    # and the rates line says the platform version was assumed, because the service reported none
    assert "Rates that apply (V1, ASSUMED: AWS documents V1 when none is asked for" in text


def test_deploy_passes_platform_version_only_when_asked(kit, monkeypatch):
    script = _deploy_script(kit)
    monkeypatch.setenv("PLATFORM_VERSION", "V2")
    lines: list[str] = []
    aws = kit.Aws("us-east-1", dry_run=True, out=lines.append)
    assert script.main(["--dry-run"], aws=aws, out=lines.append, state=kit.State(dry_run=True)) == 0
    create = next(p for s, o, p in aws.planned if o == "create_agent_runtime")
    assert create["platformVersion"] == "V2"
    monkeypatch.delenv("PLATFORM_VERSION")
    aws2 = kit.Aws("us-east-1", dry_run=True, out=lines.append)
    script.main(["--dry-run"], aws=aws2, out=lines.append, state=kit.State(dry_run=True))
    create2 = next(p for s, o, p in aws2.planned if o == "create_agent_runtime")
    assert "platformVersion" not in create2
    assert not kit.STATE_PATH.exists()


def test_deploy_records_what_exists_when_create_fails(kit, stubs, built_package):
    script = _deploy_script(kit)
    identity(stubs)
    stubs.add_error("s3", "create_bucket", "BucketAlreadyOwnedByYou", 409)
    stubs.add("s3", "put_bucket_tagging", {})
    stubs.add("s3", "put_object", {})
    stubs.add_error("iam", "create_role", "EntityAlreadyExists", 409)
    stubs.add("iam", "get_role", {"Role": {"Path": "/", "RoleName": "kitdemo-kitc-runtime-role",
                                           "RoleId": "AROAEXAMPLEEXAMPLE1", "Arn": ROLE_ARN,
                                           "CreateDate": NOW}},
              {"RoleName": "kitdemo-kitc-runtime-role"})
    stubs.add("iam", "put_role_policy", {})
    stubs.add_error(CONTROL, "create_agent_runtime", "ValidationException", 400)
    lines: list[str] = []
    state = kit.State(kit.STATE_PATH)
    rc = script.main(["--i-understand-this-bills"], aws=make_aws(kit, stubs, lines),
                     out=lines.append, state=state)
    assert rc == 1
    saved = json.loads(kit.STATE_PATH.read_text())
    assert saved["bucket"] == BUCKET and saved["role_name"] == "kitdemo-kitc-runtime-role"
    assert "runtime_id" not in saved
    assert (saved["region"], saved["prefix"], saved["account_id"]) == ("us-east-1", "kitdemo", ACCOUNT)
    assert any("90_teardown.py" in line for line in lines)


def test_execution_policy_matches_the_documented_statements(kit):
    script = _deploy_script(kit)
    policy = script.execution_policy(ACCOUNT, "us-east-1", "kitdemo_kitc_fr_agent")
    actions = set()
    for statement in policy["Statement"]:
        value = statement["Action"]
        actions.update([value] if isinstance(value, str) else value)
    assert actions == {
        "logs:DescribeLogStreams", "logs:CreateLogGroup", "logs:PutResourcePolicy",
        "logs:DescribeLogGroups", "logs:CreateLogStream", "logs:PutLogEvents",
        "xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules",
        "xray:GetSamplingTargets", "cloudwatch:PutMetricData",
        "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
    }
    invoke = next(st for st in policy["Statement"] if st.get("Sid") == "BedrockModelInvocation")
    assert invoke["Resource"] == [
       f"arn:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/us.amazon.nova-micro-v1:0",
       "arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0",
    ]
    assert all("foundation-model/*" not in resource and f"{ACCOUNT}:*" not in resource
              for resource in invoke["Resource"])
    log_group = (f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:"
                 "/aws/bedrock-agentcore/runtimes/kitdemo_kitc_fr_agent-*")
    create_logs = next(st for st in policy["Statement"] if "logs:CreateLogGroup" in st["Action"])
    assert create_logs["Resource"] == [log_group]
    trust = script.trust_policy(ACCOUNT, "us-east-1")["Statement"][0]
    assert trust["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert trust["Condition"]["StringEquals"] == {"aws:SourceAccount": ACCOUNT}


def test_execution_policy_scopes_inference_profile_to_profile_and_model(kit):
    script = _deploy_script(kit)
    model_id = "us.amazon.nova-micro-v1:0"
    policy = script.execution_policy(ACCOUNT, "us-east-1", "kitdemo_kitc_fr_agent",
                                    model_id=model_id)
    invoke = next(st for st in policy["Statement"] if st.get("Sid") == "BedrockModelInvocation")
    assert invoke["Resource"] == [
       f"arn:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/{model_id}",
       "arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0",
    ]
    assert "arn:aws:bedrock:*::foundation-model/*" not in invoke["Resource"]


def test_execution_policy_can_add_read_access_to_exactly_the_zip(kit):
    """Review minor 17: two AWS pages disagree on whether the role needs S3 access to the package.
    The default follows the permissions page (no S3). The opt-in adds one narrow statement."""
    script = _deploy_script(kit)
    zip_arn = f"arn:aws:s3:::{BUCKET}/kitdemo_kitc_fr_agent/deployment_package.zip"
    policy = script.execution_policy(ACCOUNT, "us-east-1", "kitdemo_kitc_fr_agent", zip_arn)
    s3 = [st for st in policy["Statement"] if "s3:GetObject" in st["Action"]]
    assert s3 == [{"Sid": "ReadTheDeploymentPackage", "Effect": "Allow",
                   "Action": ["s3:GetObject"], "Resource": [zip_arn]}]
    assert len(json.dumps(policy)) < 10240  # the IAM limit for an inline role policy


def test_deploy_passes_the_s3_statement_only_when_the_setting_is_on(kit, monkeypatch):
    script = _deploy_script(kit)
    model_id = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    monkeypatch.setenv("MODEL_ID", model_id)
    for setting, expected in (("", False), ("true", True)):
        monkeypatch.setenv("EXECUTION_ROLE_S3_READ", setting)
        lines: list[str] = []
        aws = kit.Aws("us-east-1", dry_run=True, out=lines.append)
        assert script.main(["--dry-run"], aws=aws, out=lines.append, state=kit.State(dry_run=True)) == 0
        policy = next(p for s, o, p in aws.planned if o == "put_role_policy")["PolicyDocument"]
        assert ("s3:GetObject" in policy) is expected
        invocation = next(st for st in json.loads(policy)["Statement"]
                          if st.get("Sid") == "BedrockModelInvocation")
        assert invocation["Resource"] == [
            f"arn:aws:bedrock:us-east-1::foundation-model/{model_id}"]


def test_deploy_prints_what_an_unstopped_session_can_cost(kit, stubs, built_package):
    script = _deploy_script(kit)
    lines: list[str] = []
    script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=kit.State(kit.STATE_PATH))
    text = "\n".join(lines)
    assert "idle timeout 120 s, maximum lifetime 900 s" in text
    assert "V1: about $0.0002 if it only sits idle" in text and "at most $0.064" in text
    assert "V2: about $0.0003 if it only sits idle" in text and "at most $0.098" in text


# ====================================================================== 40_enable_observability
def _delivery_stubs(stubs, kind, log_type, dest_type):
    stubs.add("logs", "put_delivery_source", {"deliverySource": {"name": f"kitdemo-kitc-{kind}-src"}},
              {"name": f"kitdemo-kitc-{kind}-src", "resourceArn": RUNTIME_ARN, "logType": log_type,
               "tags": {"project": "aws-kits", "kit": "kit-c"}})
    expected = {"name": f"kitdemo-kitc-{kind}-dst", "deliveryDestinationType": dest_type,
                "tags": {"project": "aws-kits", "kit": "kit-c"}}
    if dest_type == "CWL":
        expected["deliveryDestinationConfiguration"] = {
            "destinationResourceArn": f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:"
                                      f"/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-{kind}"}
    dest_arn = f"arn:aws:logs:us-east-1:{ACCOUNT}:delivery-destination:kitdemo-kitc-{kind}-dst"
    stubs.add("logs", "put_delivery_destination",
              {"deliveryDestination": {"name": f"kitdemo-kitc-{kind}-dst", "arn": dest_arn}}, expected)
    stubs.add("logs", "create_delivery", {"delivery": {"id": f"id{kind}"}},
              {"deliverySourceName": f"kitdemo-kitc-{kind}-src", "deliveryDestinationArn": dest_arn,
               "tags": {"project": "aws-kits", "kit": "kit-c"}})


@pytest.mark.parametrize("destination, expected_kinds", [
    ("XRay", ["usage", "app"]),
    ("CloudWatchLogs", ["usage", "app", "traces"]),
])
def test_observability_creates_deliveries(kit, stubs, destination, expected_kinds):
    script = load_script("40_enable_observability.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    identity(stubs)
    for kind, log_type in (("usage", "USAGE_LOGS"), ("app", "APPLICATION_LOGS")):
        group = f"/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-{kind}"
        stubs.add("logs", "create_log_group", {},
                  {"logGroupName": group, "tags": {"project": "aws-kits", "kit": "kit-c"}})
        stubs.add("logs", "put_retention_policy", {}, {"logGroupName": group, "retentionInDays": 7})
        _delivery_stubs(stubs, kind, log_type, "CWL")
    stubs.add("xray", "get_trace_segment_destination", {"Destination": destination, "Status": "ACTIVE"}, {})
    if "traces" in expected_kinds:
        _delivery_stubs(stubs, "traces", "TRACES", "XRAY")
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills", "--include-app-logs"],
                     aws=make_aws(kit, stubs, lines),
                     out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    saved = json.loads(kit.STATE_PATH.read_text())
    assert [d["kind"] for d in saved["deliveries"]] == expected_kinds
    assert len(saved["log_groups"]) == 2


def test_observability_needs_a_deployed_runtime(kit, stubs):
    script = load_script("40_enable_observability.py")
    identity(stubs)
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills"], aws=make_aws(kit, stubs, lines),
                     out=lines.append, state=kit.State(kit.STATE_PATH))
    assert rc == 1 and set(stubs.clients) == {"sts"}


def test_observability_skips_payload_logs_by_default(kit):
    script = load_script("40_enable_observability.py")
    lines: list[str] = []
    aws = kit.Aws("us-east-1", dry_run=True, out=lines.append)
    rc = script.main(["--dry-run"], aws=aws, out=lines.append, state=kit.State(dry_run=True))
    assert rc == 0, "\n".join(lines)
    assert any(operation == "put_delivery_source" and parameters.get("logType") == "USAGE_LOGS"
               for service, operation, parameters in aws.planned if service == "logs")
    assert not any(parameters.get("logType") == "APPLICATION_LOGS"
                   for service, operation, parameters in aws.planned if service == "logs")
    assert any("--include-app-logs" in line for line in lines)


def test_observability_rerun_after_a_partial_failure_creates_only_what_is_missing(kit, stubs):
    """Review minor 11: a first run that died after the usage delivery used to make the
    second run say "Nothing to do"."""
    script = load_script("40_enable_observability.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)

    # first run: usage delivery is made, then the application log group cannot be created
    identity(stubs)
    usage_group = "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-usage"
    stubs.add("logs", "create_log_group", {})
    stubs.add("logs", "put_retention_policy", {})
    _delivery_stubs(stubs, "usage", "USAGE_LOGS", "CWL")
    stubs.add_error("logs", "create_log_group", "ThrottlingException", 400)
    lines: list[str] = []
    assert script.main(["--i-understand-this-bills", "--include-app-logs"],
                       aws=make_aws(kit, stubs, lines),
                       out=lines.append, state=state) == 1
    assert [d["kind"] for d in json.loads(kit.STATE_PATH.read_text())["deliveries"]] == ["usage"]
    assert any("run this script again" in line for line in lines)

    # second run: the usage delivery is skipped, the other two are made
    identity(stubs)
    stubs.add("logs", "create_log_group", {})
    stubs.add("logs", "put_retention_policy", {})
    _delivery_stubs(stubs, "app", "APPLICATION_LOGS", "CWL")
    stubs.add("xray", "get_trace_segment_destination", {"Destination": "CloudWatchLogs", "Status": "ACTIVE"}, {})
    _delivery_stubs(stubs, "traces", "TRACES", "XRAY")
    lines = []
    assert script.main(["--i-understand-this-bills", "--include-app-logs"],
                       aws=make_aws(kit, stubs, lines),
                       out=lines.append, state=kit.State(kit.STATE_PATH)) == 0, "\n".join(lines)
    stubs.assert_all_used()
    saved = json.loads(kit.STATE_PATH.read_text())
    assert [d["kind"] for d in saved["deliveries"]] == ["usage", "app", "traces"]
    assert usage_group in saved["log_groups"]
    assert any("USAGE_LOGS delivery is already recorded, skipping" in line for line in lines)
    assert not any("Nothing to do" in line for line in lines)

    # third run: everything is there, nothing is created
    identity(stubs)
    lines = []
    assert script.main(["--i-understand-this-bills", "--include-app-logs"],
                       aws=make_aws(kit, stubs, lines),
                       out=lines.append, state=kit.State(kit.STATE_PATH)) == 0
    stubs.assert_all_used()
    assert any("0 delivery(ies) created now, 3 recorded in all" in line for line in lines)


def test_observability_records_a_delivery_that_an_interrupted_run_already_made(kit, stubs):
    script = load_script("40_enable_observability.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    identity(stubs)
    stubs.add("logs", "create_log_group", {})
    stubs.add("logs", "put_retention_policy", {})
    stubs.add("logs", "put_delivery_source", {"deliverySource": {"name": "kitdemo-kitc-usage-src"}})
    stubs.add("logs", "put_delivery_destination", {"deliveryDestination": {
        "name": "kitdemo-kitc-usage-dst",
        "arn": f"arn:aws:logs:us-east-1:{ACCOUNT}:delivery-destination:kitdemo-kitc-usage-dst"}})
    stubs.add_error("logs", "create_delivery", "ConflictException", 409)
    stubs.add("logs", "describe_deliveries",
              {"deliveries": [{"id": "idother", "deliverySourceName": "not-ours"},
                              {"id": "idusage", "deliverySourceName": "kitdemo-kitc-usage-src"}]},
              {"limit": 50})
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills", "--no-app-logs", "--no-traces"],
                     aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    assert json.loads(kit.STATE_PATH.read_text())["deliveries"][0]["delivery_id"] == "idusage"


# ====================================================================== 50_invoke_hosted
def _agent_answer(n):
    return {"result": f"answer {n} citing 2026-19964", "tool_calls": [{"name": "search_federal_register", "args": {}}],
            "citations": [{"document_number": "2026-19964"}], "usage": {"input_tokens": 900, "output_tokens": 120},
            "unverified_document_numbers": [], "tool_errors": [], "warnings": [], "grounding": "ok",
            "grounding_reasons": [], "answer_replaced": False, "stopped": None}


def test_invoke_opens_sessions_times_calls_and_always_stops(kit, stubs):
    script = load_script("50_invoke_hosted.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    identity(stubs)
    for _ in range(2):  # two sessions, two calls each
        for n in (1, 2):
            stubs.add(DATA, "invoke_agent_runtime",
                      {"statusCode": 200, "contentType": "application/json",
                       "response": streaming(_agent_answer(n))},
                      {"agentRuntimeArn": RUNTIME_ARN, "runtimeSessionId": ANY, "payload": ANY,
                       "contentType": "application/json", "accept": "application/json"})
        stubs.add(DATA, "stop_runtime_session", {"statusCode": 200},
                  {"agentRuntimeArn": RUNTIME_ARN, "runtimeSessionId": ANY})
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills", "--sessions", "2"],
                     aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    sessions = json.loads(kit.STATE_PATH.read_text())["sessions"]
    assert len(sessions) == 2 and all(s["stopped"] for s in sessions)
    assert len({s["session_id"] for s in sessions}) == 2
    assert all(len(s["session_id"]) >= 33 and s["session_id"].startswith("kitdemo-kitc-") for s in sessions)
    call = sessions[0]["calls"][0]
    assert call["tool_calls"] == 1 and call["citations"] == 1 and call["input_tokens"] == 900
    assert call["latency_ms"] >= 0 and call["error"] is None and call["flagged"] is False
    text = "\n".join(lines)
    assert "first call in a new session: n=2" in text
    assert "same question again, same session: n=2" in text


def test_invoke_stops_the_session_even_when_a_call_fails(kit, stubs):
    script = load_script("50_invoke_hosted.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    identity(stubs)
    stubs.add_error(DATA, "invoke_agent_runtime", "ThrottlingException", 429)
    stubs.add(DATA, "stop_runtime_session", {"statusCode": 200})
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills", "--sessions", "1", "--calls-per-session", "1",
                      "--question", "only one"],
                     aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    assert rc == 1
    stubs.assert_all_used()
    session = json.loads(kit.STATE_PATH.read_text())["sessions"][0]
    assert session["stopped"] is True and "ThrottlingException" in session["calls"][0]["error"]
    assert any("Failed or flagged calls: 1" in line for line in lines)


def test_invoke_refuses_without_the_billing_flag(kit, stubs):
    script = load_script("50_invoke_hosted.py")
    lines: list[str] = []
    rc = script.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                     state=kit.State(kit.STATE_PATH))
    assert rc == 2 and stubs.clients == {}


def test_session_ids_are_long_enough_and_unique(kit):
    script = load_script("50_invoke_hosted.py")
    ids = {script.new_session_id("ab") for _ in range(50)}
    assert len(ids) == 50 and all(len(i) >= 33 for i in ids)


# ====================================================================== 60_read_usage
def _state_with_sessions(kit, deliveries=("USAGE_LOGS",)):
    state = kit.State(kit.STATE_PATH)
    sessions = []
    for n in (1, 2):
        sessions.append({"session_id": f"kitdemo-kitc-{str(n) * 32}", "started_at": "2026-10-07T12:00:00Z",
                         "ended_at": "2026-10-07T12:02:00Z", "stopped": True,
                         "calls": [{"input_tokens": 1000, "output_tokens": 200}]})
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID, sessions=sessions,
              reported_platform_version="not reported",
              deliveries=[{"log_type": t} for t in deliveries])
    return state, sessions


def test_read_usage_sends_the_documented_requests(kit, stubs, monkeypatch):
    """The request shapes, against the SDK's own definitions. The arithmetic and the
    cross-check have their own file, test_usage_cost.py."""
    script = load_script("60_read_usage.py")
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 14, 0, tzinfo=dt.timezone.utc))
    state, sessions = _state_with_sessions(kit)
    identity(stubs)
    flat = {"session.id": sessions[0]["session_id"], "elapsed_time_seconds": 60,
            "agent.runtime.vcpu.hours.used": 0.001, "agent.runtime.memory.gb_hours.used": 0.002}
    nested = {"resource_arn": RUNTIME_ARN,
              "attributes": {"session.id": sessions[1]["session_id"], "elapsed_time_seconds": 120,
                             "agent.runtime.vcpu.hours.used": 0.003,
                             "agent.runtime.memory.gb_hours.used": 0.004}}
    stubs.add("logs", "filter_log_events",
              {"events": [{"message": json.dumps(flat), "timestamp": 1}, {"message": json.dumps(flat), "timestamp": 2},
                          {"message": "not json"}]},
              {"logGroupName": "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-usage",
               "startTime": ANY, "endTime": ANY, "filterPattern": f'"{sessions[0]["session_id"]}"'})
    stubs.add("logs", "filter_log_events", {"events": [{"message": json.dumps(nested)}]})
    for name, total in (("CPUUsed-vCPUHours", 0.005), ("MemoryUsed-GBHours", 0.008)):
        stubs.add("cloudwatch", "get_metric_statistics",
                  {"Datapoints": [{"Timestamp": NOW, "Sum": total / 2}, {"Timestamp": NOW, "Sum": total / 2}]},
                  {"Namespace": "AWS/Bedrock-AgentCore", "MetricName": name,
                   "Dimensions": [{"Name": "Service", "Value": "AgentCore.Runtime"},
                                  {"Name": "Resource", "Value": RUNTIME_ARN}],
                   "StartTime": ANY, "EndTime": ANY, "Period": 300, "Statistics": ["Sum"]})
    lines: list[str] = []
    rc = script.main(["--input-usd-per-1m", "0.5", "--output-usd-per-1m", "1.5"],
                     aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    text = "\n".join(lines)
    assert rc == 0, text
    stubs.assert_all_used()
    # logs: vCPU 0.002 + 0.003 = 0.005, GB 0.004 + 0.004 = 0.008, at V1 rates
    expected = 0.005 * 0.0895 + 0.008 * 0.00945
    assert f"0.00500000 vCPU-hours, 0.00800000 GB-hours = ${expected:.6f}" in text
    assert "1 usage record(s) could not be read" in text
    assert "Model tokens reported by the agent: 2000 in, 400 out." in text
    assert "= $0.001600" in text  # 2000 / 1e6 x 0.5 + 400 / 1e6 x 1.5
    assert lines[-1].startswith("RESULT: CROSS-CHECKED")


def test_read_usage_without_usage_logs_reads_metrics_and_is_not_cross_checked(kit, stubs, monkeypatch):
    script = load_script("60_read_usage.py")
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 13, 0, tzinfo=dt.timezone.utc))
    state, _ = _state_with_sessions(kit, deliveries=())
    identity(stubs)
    stubs.add("cloudwatch", "get_metric_statistics", {"Datapoints": []})
    stubs.add("cloudwatch", "get_metric_statistics", {"Datapoints": []})
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 1
    stubs.assert_all_used()
    assert any("No USAGE_LOGS delivery is recorded" in line for line in lines)
    assert "logs" not in stubs.clients
    assert lines[-1].startswith("RESULT: NOT CROSS-CHECKED")


def test_read_usage_needs_sessions(kit, stubs):
    script = load_script("60_read_usage.py")
    identity(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                       state=kit.State(kit.STATE_PATH)) == 1
    assert set(stubs.clients) == {"sts"}


def test_usage_parser_and_cost():
    script = load_script("60_read_usage.py")
    events = [
        {"message": json.dumps({"session.id": "s1", "agent.runtime.vcpu.hours.used": 0.5,
                                "agent.runtime.memory.gb_hours.used": 1.0})},
        {"message": json.dumps({"a": {"b": {"session.id": "s1", "agent.runtime.vcpu.hours.used": 0.25}}})},
        {"message": json.dumps({"session.id": "s2"})},  # no usage fields
        {"message": ""},
    ]
    parsed = script.parse_usage_events(events)
    assert parsed["unparsed"] == 2
    s1 = parsed["sessions"]["s1"]
    assert (s1["records"], s1["vcpu_hours_sum"], s1["gb_hours_sum"]) == (2, 0.75, 1.0)
    assert (s1["vcpu_hours_max"], s1["gb_hours_max"]) == (0.5, 1.0)
    assert script.cost(1.0, 2.0, 0.0895, 0.00945) == pytest.approx(0.0895 + 0.0189)
    # AWS's own worked example on the pricing page (V2 rates, read 2026-10-07): 60 s of 1 vCPU,
    # and 300 s x 1 GB + 150 s x 2 GB + 150 s x 2.5 GB of memory, "Total cost per session:
    # $0.006703". The exact product is $0.00670375; the page's figure is its parts cut to six places.
    vcpu_hours = 60 / 3600
    gb_hours = (300 * 1 + 150 * 2 + 150 * 2.5) / 3600
    assert script.cost(vcpu_hours, gb_hours, 0.1276, 0.0169) == pytest.approx(0.006703, abs=1e-6)


# ====================================================================== 90_teardown and 99_verify_clean
def _full_account(stubs):
    role = {"Path": "/", "RoleName": "kitdemo-kitc-runtime-role", "RoleId": "AROAEXAMPLEEXAMPLE1",
            "Arn": ROLE_ARN, "CreateDate": NOW}
    other_role = dict(role, RoleName="someone-elses-role", Arn=f"arn:aws:iam::{ACCOUNT}:role/someone-elses-role")
    empty_discovery(
        stubs,
        runtimes=[runtime_summary(), runtime_summary(name="another_teams_agent")],
        identities=[{"name": RUNTIME_ID, "workloadIdentityArn": "arn:aws:bedrock-agentcore:us-east-1:"
                     f"{ACCOUNT}:workload-identity-directory/default/workload-identity/{RUNTIME_ID}"}],
        roles=[role, other_role],
        buckets=[{"Name": BUCKET}],
        runtime_groups=[{"logGroupName": f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT"}],
        vended_groups=[{"logGroupName": "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-usage"}],
        deliveries=[{"id": "idusage", "deliverySourceName": "kitdemo-kitc-usage-src"},
                    {"id": "idother", "deliverySourceName": "not-ours"}],
        sources=[{"name": "kitdemo-kitc-usage-src"}],
        destinations=[{"name": "kitdemo-kitc-usage-dst"}],
        tagged=[{"ResourceARN": RUNTIME_ARN}],
    )


def test_teardown_deletes_everything_it_finds_and_only_that(kit, stubs):
    script = load_script("90_teardown.py")
    state = kit.State(kit.STATE_PATH)
    open_session = "kitdemo-kitc-" + "9" * 32
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID, bucket=BUCKET,
              sessions=[{"session_id": open_session, "stopped": False, "calls": []},
                        {"session_id": "kitdemo-kitc-" + "8" * 32, "stopped": True, "calls": []}])
    identity(stubs)
    _full_account(stubs)
    stubs.add(DATA, "stop_runtime_session", {"statusCode": 200},
              {"agentRuntimeArn": RUNTIME_ARN, "runtimeSessionId": open_session})
    stubs.add("logs", "delete_delivery", {}, {"id": "idusage"})
    stubs.add("logs", "delete_delivery_source", {}, {"name": "kitdemo-kitc-usage-src"})
    stubs.add("logs", "delete_delivery_destination", {}, {"name": "kitdemo-kitc-usage-dst"})
    stubs.add(CONTROL, "delete_agent_runtime", {"status": "DELETING"}, {"agentRuntimeId": RUNTIME_ID})
    stubs.add(CONTROL, "get_agent_runtime", runtime_detail("DELETING"), {"agentRuntimeId": RUNTIME_ID})
    stubs.add_error(CONTROL, "get_agent_runtime", "ResourceNotFoundException", 404)
    stubs.add(CONTROL, "list_workload_identities",
              {"workloadIdentities": [{"name": RUNTIME_ID, "workloadIdentityArn": "arn:x"},
                                      {"name": "another_teams_agent-zzzzzzzzzz", "workloadIdentityArn": "arn:y"}]},
              {"maxResults": 20})
    stubs.add(CONTROL, "delete_workload_identity", {}, {"name": RUNTIME_ID})
    log_groups_listed_again(stubs)
    stubs.add("logs", "delete_log_group", {},
              {"logGroupName": f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT"})
    stubs.add("logs", "delete_log_group", {},
              {"logGroupName": "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-usage"})
    key = "kitdemo_kitc_fr_agent/deployment_package.zip"
    stubs.add("s3", "list_object_versions",
              {"Versions": [{"Key": key, "VersionId": "null"}], "IsTruncated": False},
              {"Bucket": BUCKET, "MaxKeys": 1000})
    stubs.add("s3", "delete_objects", {}, {"Bucket": BUCKET, "Delete": {"Objects": [{"Key": key}], "Quiet": True}})
    stubs.add("s3", "list_object_versions", {"IsTruncated": False}, {"Bucket": BUCKET, "MaxKeys": 1000})
    stubs.add("s3", "delete_bucket", {}, {"Bucket": BUCKET})
    # before the role goes: its trust policy is read, to see which Region it serves
    stubs.add("iam", "get_role", {"Role": dict(
        Path="/", RoleName="kitdemo-kitc-runtime-role", RoleId="AROAEXAMPLEEXAMPLE1", Arn=ROLE_ARN,
        CreateDate=NOW, AssumeRolePolicyDocument=json.dumps({"Statement": [{"Condition": {"ArnLike": {
            "aws:SourceArn": f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:*"}}}]}))},
        {"RoleName": "kitdemo-kitc-runtime-role"})
    stubs.add("iam", "list_role_policies", {"PolicyNames": ["kitdemo-kitc-runtime-policy"]},
              {"RoleName": "kitdemo-kitc-runtime-role"})
    stubs.add("iam", "list_attached_role_policies", {"AttachedPolicies": []},
              {"RoleName": "kitdemo-kitc-runtime-role"})
    stubs.add("iam", "delete_role_policy", {},
              {"RoleName": "kitdemo-kitc-runtime-role", "PolicyName": "kitdemo-kitc-runtime-policy"})
    stubs.add("iam", "delete_role", {}, {"RoleName": "kitdemo-kitc-runtime-role"})

    lines: list[str] = []
    rc = script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()  # nothing extra was queued, so nothing of anyone else's was deleted
    saved = json.loads(kit.STATE_PATH.read_text())
    assert "runtime_id" not in saved and saved["history"][0]["torn_down_at"]
    assert saved["history"][0]["runtime_id"] == RUNTIME_ID
    assert len(saved["past_sessions"]) == 2
    text = "\n".join(lines)
    assert "someone-elses-role" not in text and "another_teams_agent" not in text
    assert ACCOUNT not in text


def test_teardown_keeps_state_and_fails_when_a_delete_fails(kit, stubs):
    script = load_script("90_teardown.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              runtime_arn=RUNTIME_ARN, runtime_id=RUNTIME_ID)
    identity(stubs)
    empty_discovery(stubs, buckets=[{"Name": BUCKET}])
    stubs.add_error(CONTROL, "get_agent_runtime", "ResourceNotFoundException", 404)
    stubs.add(CONTROL, "list_workload_identities", {"workloadIdentities": []})
    stubs.add("s3", "list_objects_v2", {"Contents": []})
    stubs.add_error("s3", "delete_bucket", "AccessDenied", 403)
    lines: list[str] = []
    rc = script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    assert rc == 1
    assert json.loads(kit.STATE_PATH.read_text())["runtime_id"] == RUNTIME_ID
    assert any("WITH ERRORS" in line for line in lines)


def test_teardown_with_nothing_to_delete_is_clean(kit, stubs):
    script = load_script("90_teardown.py")
    identity(stubs)
    empty_discovery(stubs)
    stubs.add(CONTROL, "list_workload_identities", {"workloadIdentities": []})
    log_groups_listed_again(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append,
                       state=kit.State(kit.STATE_PATH)) == 0
    stubs.assert_all_used()


def _verify_tail(stubs, destination="XRay", spans=()):
    stubs.add("xray", "get_trace_segment_destination", {"Destination": destination, "Status": "ACTIVE"}, {})
    stubs.add("logs", "describe_log_groups", {"logGroups": list(spans)}, {"logGroupNamePrefix": "aws/spans"})


def test_verify_clean_passes_on_an_empty_account(kit, stubs):
    script = load_script("99_verify_clean.py")
    identity(stubs)
    empty_discovery(stubs)
    _verify_tail(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 0
    stubs.assert_all_used()
    assert lines[-1].startswith("RESULT: CLEAN: nothing with the kit's prefix or tags was found.")
    # no state file: said in plain words, with what that limits (round 2, minor 14)
    assert "No state file was found on this machine" in lines[-1]
    assert "It is not proof for any other Region, prefix or account." in lines[-1]
    assert not kit.STATE_PATH.exists()


def test_verify_clean_fails_and_lists_every_leftover(kit, stubs):
    script = load_script("99_verify_clean.py")
    identity(stubs)
    _full_account(stubs)
    _verify_tail(stubs, destination="CloudWatchLogs", spans=[{"logGroupName": "aws/spans", "storedBytes": 10}])
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    text = "\n".join(lines)
    assert "RESULT: NOT CLEAN: 10 item(s) left" in text
    for needle in (RUNTIME_ID, "kitdemo-kitc-runtime-role", "kitdemo-kitc-usage-src",
                   "kitdemo-kitc-usage-dst", "idusage", "Transaction Search: ON", "aws/spans log group: exists"):
        assert needle in text
    assert "someone-elses-role" not in text and "idother" not in text


def test_verify_clean_finds_a_resource_known_only_by_its_tag(kit, stubs):
    """A lost state file and a renamed resource: the tag lookup alone must fail the check."""
    script = load_script("99_verify_clean.py")
    identity(stubs)
    empty_discovery(stubs, tagged=[{"ResourceARN": "arn:aws:bedrock-agentcore:us-east-1:"
                                    f"{ACCOUNT}:runtime/renamed_agent-abcdefghij"}])
    _verify_tail(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    assert any(line.startswith("RESULT: NOT CLEAN: 1 item(s)") for line in lines)


def test_verify_clean_does_not_claim_clean_when_a_call_fails(kit, stubs):
    script = load_script("99_verify_clean.py")
    identity(stubs)
    stubs.add_error(CONTROL, "list_agent_runtimes", "AccessDeniedException", 403)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    assert lines[-1].startswith("RESULT: NOT VERIFIED")
    assert not any(line.startswith("RESULT: CLEAN") for line in lines)


def test_verify_clean_does_not_claim_clean_when_the_tag_lookup_fails(kit, stubs):
    script = load_script("99_verify_clean.py")
    identity(stubs)
    stubs.add(CONTROL, "list_agent_runtimes", {"agentRuntimes": []})
    stubs.add(CONTROL, "list_gateways", {"items": []})
    stubs.add(CONTROL, "list_workload_identities", {"workloadIdentities": []})
    stubs.add("iam", "list_roles", {"Roles": []})
    stubs.add("s3", "list_buckets", {"Buckets": []})
    stubs.add("logs", "describe_log_groups", {"logGroups": []})
    stubs.add("logs", "describe_log_groups", {"logGroups": []})
    stubs.add("logs", "describe_deliveries", {"deliveries": []})
    stubs.add("logs", "describe_delivery_sources", {"deliverySources": []})
    stubs.add("logs", "describe_delivery_destinations", {"deliveryDestinations": []})
    stubs.add_error("resourcegroupstaggingapi", "get_resources", "AccessDeniedException", 403)
    _verify_tail(stubs)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append) == 1
    assert any("the tag lookup failed (AccessDeniedException)" in line for line in lines)
    assert lines[-1].startswith("RESULT: NOT VERIFIED: nothing was found by name, but")
    assert not any(line.startswith("RESULT: CLEAN") for line in lines)
