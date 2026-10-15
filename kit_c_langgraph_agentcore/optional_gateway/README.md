# Optional: one Federal Register endpoint as an MCP tool behind AgentCore Gateway

This step is extra. The core kit does not need it: the agent's two tools run
in-process. Do it only if you want first-hand experience of Gateway.

## What this is
AgentCore Gateway takes an OpenAPI description and serves its operations as MCP
tools. These three scripts create one gateway with one OpenAPI target (a single
operation, `getAgency`, which looks up a Federal Register agency by slug), list
the tools over MCP, call the tool, and delete everything.

It is deliberately one operation. The Federal Register search endpoint uses
bracketed query parameter names such as `conditions[term]`, and the Gateway
documentation lists complex parameter serializers as unsupported for OpenAPI
targets, so the search tool stays in-process.

## Problems first
- Nothing here was run against AWS. See the main README, section 8.
- Price read 2026-10-07 on https://aws.amazon.com/bedrock/agentcore/pricing/
  (one list price, no per-Region table): $0.005 per 1,000 API invocations
  (ListTools, InvokeTool, Ping), $0.025 per 1,000 search calls, $0.02 per 100
  tools indexed per month. This step makes a handful of invocations and does
  not enable search.
- The gateway uses IAM for inbound authorization (`AWS_IAM`), so only principals
  in your account with `bedrock-agentcore:InvokeGateway` can call it. The target
  calls a public API with no outbound credential, which AWS documents as
  supported for OpenAPI targets and "not recommended" in general.
- UNVERIFIED items are marked in the scripts and repeated in the main README.
- Like the main scripts, these three compare `.state.json` with the Region,
  prefix and account in use and stop (exit code 4) if they differ, or if the
  file cannot be read. Run this step in the same Region, with the same prefix
  and in the same account as the main kit.
- `90_teardown_gateway.py` deletes only the gateway step. It exits 0 with the
  runtime still deployed and billing, because the runtime is not its job;
  `99_verify_clean.py` then says `RESULT: NOT CLEAN`. Its `--dry-run` exits 3,
  not 0. It keeps the gateway role, says so and exits 1, when a gateway of
  this kit could be using that role in another Region.

## Run it
From the kit folder, after `00_check.py` passes:

    python optional_gateway/10_create_gateway.py --dry-run
    python optional_gateway/10_create_gateway.py --i-understand-this-bills
    python optional_gateway/50_call_gateway_tools.py --dry-run
    python optional_gateway/50_call_gateway_tools.py --i-understand-this-bills

## Tear it down and check it
    python optional_gateway/90_teardown_gateway.py
    python 99_verify_clean.py

After the delete call the script waits until AWS answers that the gateway does
not exist. A gateway still listed as DELETING when the wait ends is not gone:
the record is kept and the exit code is 1. Run it again.

The last line of the check starts `RESULT:` and names the account (last four
digits), Region and prefix it looked at. Only `RESULT: CLEAN` with exit code 0
counts.

`90_teardown.py` in the kit folder also removes the gateway, so running the
main teardown is enough.

## What to record
The two `[timing]` lines that `10_create_gateway.py` prints ("create call to
gateway READY" and "create call to gateway and target READY"), the tool names
returned by `tools/list`, the latency of one `tools/call`, and the teardown
check.
