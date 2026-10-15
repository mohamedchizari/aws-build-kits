"""The optional gateway step, offline: the OpenAPI file, the create flow against
botocore Stubber, the MCP request bodies, SigV4 signing, and teardown."""
from __future__ import annotations

import datetime as dt
import json

from conftest import ACCOUNT, ROOT, load_script, make_aws
from test_aws_flows import ANY, CONTROL, empty_discovery, identity

NOW = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc)
GATEWAY_ID = "kitdemo-kitc-gateway-abcdefghij"
GATEWAY_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:gateway/{GATEWAY_ID}"
GATEWAY_URL = f"https://{GATEWAY_ID}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
GATEWAY_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/kitdemo-kitc-gateway-role"


def test_openapi_file_stays_inside_what_gateway_documents_as_supported():
    spec = json.loads((ROOT / "optional_gateway" / "federal_register_openapi.json").read_text())
    assert spec["openapi"].startswith("3.0")          # 3.0 and 3.1 are supported, Swagger 2.0 is not
    assert spec["servers"] == [{"url": "https://www.federalregister.gov/api/v1"}]
    assert list(spec["paths"]) == ["/agencies/{slug}"]
    operation = spec["paths"]["/agencies/{slug}"]["get"]
    assert operation["operationId"] == "getAgency"    # operationId is required and becomes the tool name
    assert [(p["name"], p["in"], p["required"]) for p in operation["parameters"]] == [("slug", "path", True)]
    text = json.dumps(spec)
    for unsupported in ("oneOf", "anyOf", "allOf", "securitySchemes", "[", ):
        if unsupported == "[":
            assert all("[" not in p["name"] for p in operation["parameters"])
        else:
            assert unsupported not in text
    assert len(text) < 5000


def gateway_detail(status):
    return {"gatewayArn": GATEWAY_ARN, "gatewayId": GATEWAY_ID, "gatewayUrl": GATEWAY_URL,
            "createdAt": NOW, "updatedAt": NOW, "status": status, "name": "kitdemo-kitc-gateway",
            "authorizerType": "AWS_IAM"}


def target_detail(status):
    return {"gatewayArn": GATEWAY_ARN, "targetId": "tgt0000001", "createdAt": NOW, "updatedAt": NOW,
            "status": status, "name": "federal-register",
            "targetConfiguration": {"mcp": {"openApiSchema": {"inlinePayload": "{}"}}},
            "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]}


def test_create_gateway_flow(kit, stubs):
    script = load_script("optional_gateway/10_create_gateway.py")
    identity(stubs)
    stubs.add("iam", "create_role",
              {"Role": {"Path": "/", "RoleName": "kitdemo-kitc-gateway-role", "RoleId": "AROAEXAMPLEEXAMPLE2",
                        "Arn": GATEWAY_ROLE_ARN, "CreateDate": NOW}},
              {"RoleName": "kitdemo-kitc-gateway-role", "AssumeRolePolicyDocument": ANY, "Description": ANY,
               "Tags": [{"Key": "project", "Value": "aws-kits"}, {"Key": "kit", "Value": "kit-c"}]})
    stubs.add(CONTROL, "create_gateway", gateway_detail("CREATING"),
              {"name": "kitdemo-kitc-gateway", "roleArn": GATEWAY_ROLE_ARN, "protocolType": "MCP",
               "authorizerType": "AWS_IAM", "description": ANY,
               "tags": {"project": "aws-kits", "kit": "kit-c"}})
    stubs.add(CONTROL, "get_gateway", gateway_detail("CREATING"), {"gatewayIdentifier": GATEWAY_ID})
    stubs.add(CONTROL, "get_gateway", gateway_detail("READY"), {"gatewayIdentifier": GATEWAY_ID})
    stubs.add(CONTROL, "create_gateway_target", target_detail("CREATING"),
              {"gatewayIdentifier": GATEWAY_ID, "name": "federal-register", "description": ANY,
               "targetConfiguration": ANY})
    stubs.add(CONTROL, "get_gateway_target", target_detail("READY"),
              {"gatewayIdentifier": GATEWAY_ID, "targetId": "tgt0000001"})
    lines: list[str] = []
    state = kit.State(kit.STATE_PATH)
    rc = script.main(["--i-understand-this-bills"], aws=make_aws(kit, stubs, lines),
                     out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    saved = json.loads(kit.STATE_PATH.read_text())
    assert saved["gateway_id"] == GATEWAY_ID and saved["gateway_url"] == GATEWAY_URL
    assert saved["gateway_target_id"] == "tgt0000001"
    # the gateway step records where it ran, like the deploy step
    assert (saved["region"], saved["prefix"], saved["account_id"]) == ("us-east-1", "kitdemo", ACCOUNT)


def test_create_gateway_sends_the_spec_inline_with_no_credential_provider(kit):
    script = load_script("optional_gateway/10_create_gateway.py")
    lines: list[str] = []
    aws = kit.Aws("us-east-1", dry_run=True, out=lines.append)
    assert script.main(["--dry-run"], aws=aws, out=lines.append, state=kit.State(dry_run=True)) == 0
    target = next(p for s, o, p in aws.planned if o == "create_gateway_target")
    assert "credentialProviderConfigurations" not in target
    inline = json.loads(target["targetConfiguration"]["mcp"]["openApiSchema"]["inlinePayload"])
    assert inline["paths"]["/agencies/{slug}"]["get"]["operationId"] == "getAgency"
    trust = script.gateway_trust_policy(ACCOUNT, "us-east-1")["Statement"][0]
    assert trust["Condition"]["ArnLike"]["aws:SourceArn"].endswith(":gateway/*")


def test_create_gateway_refuses_without_the_billing_flag(kit, stubs):
    script = load_script("optional_gateway/10_create_gateway.py")
    lines: list[str] = []
    rc = script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=kit.State(kit.STATE_PATH))
    assert rc == 2 and stubs.clients == {}
    assert any("$0.005 per 1,000 API invocations" in line for line in lines)


def test_mcp_request_bodies_match_the_documented_shape():
    script = load_script("optional_gateway/50_call_gateway_tools.py")
    assert script.build_request("tools/list", None, "list-tools-request") == {
        "jsonrpc": "2.0", "id": "list-tools-request", "method": "tools/list"}
    call = script.build_request("tools/call", {"name": script.TOOL_NAME, "arguments": {"slug": "x"}}, "i")
    assert call["params"]["name"] == "federal-register___getAgency"  # <target>___<operationId>


def test_signing_adds_a_sigv4_header_for_bedrock_agentcore():
    from botocore.credentials import Credentials

    script = load_script("optional_gateway/50_call_gateway_tools.py")
    headers = script.signed_headers(GATEWAY_URL, b'{"jsonrpc":"2.0"}', "us-east-1", "2025-11-25",
                                    Credentials("AKIDEXAMPLE", "not-a-real-secret"))
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/us-east-1/bedrock-agentcore/aws4_request" in headers["Authorization"]
    assert headers["MCP-Protocol-Version"] == "2025-11-25"
    assert "X-Amz-Date" in headers


def test_mcp_response_parsing_handles_json_and_event_stream():
    script = load_script("optional_gateway/50_call_gateway_tools.py")
    body = {"jsonrpc": "2.0", "id": "1", "result": {"tools": []}}
    assert script.parse_mcp_response(json.dumps(body), "application/json") == body
    sse = "event: message\ndata: " + json.dumps(body) + "\n\n"
    assert script.parse_mcp_response(sse, "text/event-stream") == body


def test_call_gateway_tools_lists_then_calls(kit, stubs):
    script = load_script("optional_gateway/50_call_gateway_tools.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, gateway_url=GATEWAY_URL)
    identity(stubs)
    sent = []

    def fake_post(url, body, region, protocol_version):
        sent.append((url, body["method"]))
        if body["method"] == "tools/list":
            return {"result": {"tools": [{"name": "federal-register___getAgency", "description": "d"}]}}, 12.0
        return {"result": {"content": [{"type": "text", "text": '{"name": "Commerce Department"}'}]}}, 34.0

    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills"], out=lines.append, state=state, poster=fake_post,
                     aws=make_aws(kit, stubs, lines))
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()
    assert sent == [(GATEWAY_URL, "tools/list"), (GATEWAY_URL, "tools/call")]
    assert any("tools/list: 1 tool(s)" in line for line in lines)


def test_call_gateway_tools_refuses_without_flag_and_validates_slug(kit):
    script = load_script("optional_gateway/50_call_gateway_tools.py")
    never = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send"))  # noqa: E731
    lines: list[str] = []
    assert script.main([], out=lines.append, state=kit.State(kit.STATE_PATH), poster=never) == 2
    assert script.main(["--slug", "Bad Slug", "--i-understand-this-bills"], out=lines.append,
                       state=kit.State(kit.STATE_PATH), poster=never) == 2


def test_gateway_teardown_deletes_target_gateway_identity_and_role(kit, stubs):
    script = load_script("optional_gateway/90_teardown_gateway.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT,
              gateway_id=GATEWAY_ID, gateway_url=GATEWAY_URL, bucket="keep-this-key")
    gateway = {"gatewayId": GATEWAY_ID, "name": "kitdemo-kitc-gateway", "status": "READY",
               "createdAt": NOW, "updatedAt": NOW, "authorizerType": "AWS_IAM"}
    role = {"Path": "/", "RoleName": "kitdemo-kitc-gateway-role", "RoleId": "AROAEXAMPLEEXAMPLE2",
            "Arn": GATEWAY_ROLE_ARN, "CreateDate": NOW}
    runtime_role = dict(role, RoleName="kitdemo-kitc-runtime-role")
    identity(stubs)
    empty_discovery(stubs, gateways=[gateway], roles=[role, runtime_role])
    stubs.add(CONTROL, "delete_gateway_target", {"gatewayArn": GATEWAY_ARN, "targetId": "tgt0000001",
                                                 "status": "DELETING"},
              {"gatewayIdentifier": GATEWAY_ID, "targetId": "tgt0000001"})
    stubs.add(CONTROL, "list_gateway_targets", {"items": []}, {"gatewayIdentifier": GATEWAY_ID})
    stubs.add(CONTROL, "delete_gateway", {"gatewayId": GATEWAY_ID, "status": "DELETING"},
              {"gatewayIdentifier": GATEWAY_ID})
    # the delete call is not the proof: the script waits until AWS says the gateway does not exist
    stubs.add(CONTROL, "get_gateway", dict(gateway, gatewayArn=GATEWAY_ARN, status="DELETING", protocolType="MCP"),
              {"gatewayIdentifier": GATEWAY_ID})
    stubs.add_error(CONTROL, "get_gateway", "ResourceNotFoundException", 404)
    stubs.add(CONTROL, "list_workload_identities",
              {"workloadIdentities": [{"name": GATEWAY_ID, "workloadIdentityArn": "arn:x"}]})
    stubs.add(CONTROL, "delete_workload_identity", {}, {"name": GATEWAY_ID})
    # before the gateway role goes, its trust policy is read to see which Region it serves
    stubs.add("iam", "get_role", {"Role": dict(role, AssumeRolePolicyDocument=json.dumps({"Statement": [{
        "Condition": {"ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:gateway/*"}}}]}))},
        {"RoleName": "kitdemo-kitc-gateway-role"})
    stubs.add("iam", "list_role_policies", {"PolicyNames": []}, {"RoleName": "kitdemo-kitc-gateway-role"})
    stubs.add("iam", "list_attached_role_policies", {"AttachedPolicies": []},
              {"RoleName": "kitdemo-kitc-gateway-role"})
    stubs.add("iam", "delete_role", {}, {"RoleName": "kitdemo-kitc-gateway-role"})
    lines: list[str] = []
    rc = script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    assert rc == 0, "\n".join(lines)
    stubs.assert_all_used()  # the runtime role was found but not touched
    saved = json.loads(kit.STATE_PATH.read_text())
    assert "gateway_id" not in saved and saved["bucket"] == "keep-this-key"
    assert saved["region"] == "us-east-1"  # the place stays recorded until 90_teardown.py


def test_gateway_teardown_keeps_the_record_of_a_gateway_it_cannot_confirm_gone(kit, stubs):
    """Not listed under the prefix, but .state.json names it and AWS will not say it is gone."""
    script = load_script("optional_gateway/90_teardown_gateway.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, gateway_id=GATEWAY_ID)
    identity(stubs)
    empty_discovery(stubs)
    stubs.add_error(CONTROL, "get_gateway", "AccessDeniedException", 403)
    # Review round 5 (F1): the list call is no longer asked for a recorded gateway that the
    # listing did not show, so the refused list call that was queued here is gone.
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 1
    stubs.assert_all_used()
    assert json.loads(kit.STATE_PATH.read_text())["gateway_id"] == GATEWAY_ID
    assert any("could not check gateway" in line for line in lines)


def test_gateway_teardown_keeps_the_record_when_the_get_call_fails_another_way(kit, stubs):
    """Round 2, MAJOR 7, the same rule for the gateway: get fails with an unfamiliar error.
    Changed in review round 5 (F1): this test was named
    test_gateway_teardown_takes_the_list_call_as_proof_when_the_get_call_fails_another_way and
    asserted exit 0 with the record cleared, because a list call that did not contain the id
    decided. For a recorded gateway that the listing did not show, the listing does not decide:
    the record is kept, the list call is not made and the exit code is 1."""
    script = load_script("optional_gateway/90_teardown_gateway.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, gateway_id=GATEWAY_ID)
    identity(stubs)
    empty_discovery(stubs)
    stubs.add_error(CONTROL, "get_gateway", "ValidationException", 400)
    lines: list[str] = []
    assert script.main([], aws=make_aws(kit, stubs, lines), out=lines.append, state=state) == 1, lines
    stubs.assert_all_used()
    assert json.loads(kit.STATE_PATH.read_text())["gateway_id"] == GATEWAY_ID
    assert any(f"could not check gateway {GATEWAY_ID}: ValidationException" in line for line in lines)
