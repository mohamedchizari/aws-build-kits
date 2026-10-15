#!/usr/bin/env python3
"""optional_gateway/50_call_gateway_tools.py: list the gateway's MCP tools and call one.

Sends two JSON-RPC requests to the gateway's /mcp URL, signed with your AWS
credentials (SigV4), because the gateway was created with AWS_IAM inbound
authorization:
  1. tools/list
  2. tools/call  name=federal-register___getAgency  arguments={"slug": "..."}

Request shapes and the tool name form (<target name>___<operationId>):
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-list.html  (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-call.html  (read 2026-10-07)
Inbound IAM authorization needs bedrock-agentcore:InvokeGateway on the caller:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html    (read 2026-10-07)

UNVERIFIED: the documentation pages above show a bearer token, not SigV4 code. The
SigV4 signing name "bedrock-agentcore" is taken from AWS's own sample code
(awslabs/agentcore-samples, .../01-gateway/gatewaylabproject/streamable_http_sigv4.py and
02-use-cases/.../market-trends-agent/optimization/optimize_agent.py, commit 3f2d283).
UNVERIFIED: that a new gateway accepts MCP-Protocol-Version 2025-11-25 without an
initialize call first. Use --protocol-version to try another value.

Usage (from the kit folder):
    python optional_gateway/50_call_gateway_tools.py --dry-run
    python optional_gateway/50_call_gateway_tools.py --i-understand-this-bills --slug commerce-department
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import kitlib  # noqa: E402

SIGNING_NAME = "bedrock-agentcore"
TOOL_NAME = "federal-register___getAgency"
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def build_request(method: str, params: dict | None, request_id: str) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def signed_headers(url: str, body: bytes, region: str, protocol_version: str, credentials) -> dict:
    """SigV4-sign one POST. botocore does the signing; nothing is sent here."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": protocol_version,
    }
    request = AWSRequest(method="POST", url=url, data=body, headers=headers)
    SigV4Auth(credentials, SIGNING_NAME, region).add_auth(request)
    return dict(request.headers)


def parse_mcp_response(text: str, content_type: str) -> dict:
    """The gateway may answer with JSON or with a single server-sent event."""
    if "text/event-stream" in (content_type or ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError("no data line in the event stream")
    return json.loads(text)


def post(url: str, body: dict, region: str, protocol_version: str) -> tuple[dict, float]:
    import boto3
    import requests

    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("no AWS credentials found")
    data = json.dumps(body).encode("utf-8")
    headers = signed_headers(url, data, region, protocol_version, credentials.get_frozen_credentials())
    started = time.perf_counter()
    resp = requests.post(url, data=data, headers=headers, timeout=(5, 60))
    ms = (time.perf_counter() - started) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"gateway answered HTTP {resp.status_code}: {resp.text[:300]}")
    return parse_mcp_response(resp.text, resp.headers.get("Content-Type", "")), ms


def main(argv: list[str] | None = None, out=print, state: kitlib.State | None = None,
         poster=post, aws: kitlib.Aws | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    parser.add_argument("--slug", default="commerce-department")
    parser.add_argument("--protocol-version", default="2025-11-25")
    args = parser.parse_args(argv)
    if not _SLUG_RE.match(args.slug):
        out("--slug must be lower-case letters, digits and hyphens")
        return 2
    cfg = kitlib.Config.from_env()
    state = state or kitlib.State(dry_run=True, out=out)
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    if not args.dry_run and not kitlib.confirm_billing(args, kitlib.PRICE_LINES_GATEWAY, out):
        return 2
    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    if not kitlib.check_place(state, cfg, account, out, "optional_gateway/50_call_gateway_tools.py",
                              dry_run=args.dry_run):
        return kitlib.EXIT_STATE_MISMATCH
    url = state.get("gateway_url")

    list_body = build_request("tools/list", None, "list-tools-request")
    call_body = build_request("tools/call", {"name": TOOL_NAME, "arguments": {"slug": args.slug}},
                              "invoke-tool-request")
    if args.dry_run:
        url = url or (f"https://{cfg.gateway_name}-dryrun0000.gateway.bedrock-agentcore."
                      f"{cfg.region}.amazonaws.com/mcp")
        for body in (list_body, call_body):
            out(f"DRY-RUN  would POST {url} signed with SigV4 for {SIGNING_NAME}: {json.dumps(body)}")
        out("DRY-RUN complete: nothing was sent.")
        return 0
    if not url:
        out("No gateway URL in .state.json. Run optional_gateway/10_create_gateway.py first.")
        return 1

    try:
        listed, ms = poster(url, list_body, cfg.region, args.protocol_version)
        if "error" in listed:
            out(f"tools/list returned an error: {listed['error']}")
            return 1
        tools = (listed.get("result") or {}).get("tools") or []
        out(f"tools/list: {len(tools)} tool(s) in {ms:.0f} ms")
        for tool in tools:
            out(f"  - {tool.get('name')}: {str(tool.get('description', ''))[:100]}")
        if TOOL_NAME not in {t.get("name") for t in tools}:
            out(f"The expected tool {TOOL_NAME} is not in the list. Calling it anyway.")
        called, ms = poster(url, call_body, cfg.region, args.protocol_version)
        if "error" in called:
            out(f"tools/call returned an error: {called['error']}")
            return 1
        out(f"tools/call {TOOL_NAME}: {ms:.0f} ms")
        out(json.dumps(called.get("result"), indent=2, ensure_ascii=False)[:2000])
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
