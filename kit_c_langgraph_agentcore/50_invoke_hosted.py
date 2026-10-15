#!/usr/bin/env python3
"""50_invoke_hosted.py: call the hosted agent in several sessions and time each call.

Each session is its own microVM on AgentCore Runtime. This script opens a new
session, asks one question, then asks THE SAME question again in the same
session, so the first and the later call do the same work and can be compared.

What the numbers are, and are not. Each figure is the wall-clock time of one
whole call, measured on this machine: your network, AgentCore, whatever the
session needs to start, every model turn, and the Federal Register requests the
tools make. The gap between a first call and a later call is therefore an
estimate of session start-up plus ordinary run-to-run variation. It is not a
measured cold start, and with a handful of sessions it is a few numbers, not a
distribution. One-off work in this process (loading the AWS service definition
and building the client) is done before the first timed call. The first call of
the first session still pays for one new TLS connection.

No automatic retry: the invoke call is sent exactly once. A retry would run
the agent twice and be timed as one call.

Every call's answer has already been built and checked inside the runtime
(agent/graph.py): a block that code builds from the tool results, then any
WARNING, then the model's own text. This script prints the WARNING lines first,
before any preview of the answer, then what the runtime could not verify in the
model's text, and counts as FLAGGED every call that was warned, had its model
text replaced, or was stopped. A flagged call is listed with its reasons, left
out of the latency summary, and makes the script exit non-zero. That includes a
call whose search simply found nothing: its model text is replaced, and whether
that text was honest cannot be told from here. A response with no check report
at all (a zip built from an older copy of the kit) is flagged too.

After a call fails outright (an exception, no response), nobody can say whether
the session's microVM had started. The later calls of that session are
therefore labelled as such and left out of both latency lines.

Every session this script opens is stopped with StopRuntimeSession when its
calls are done, even after an error or Ctrl-C. That matters for the bill: an
idle session keeps its memory, and is billed for it, until it is stopped or the
idle timeout ends it. If a stop fails the script says so, exits non-zero, and
90_teardown.py tries again.
  https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html  (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html            (read 2026-10-07)

Results (session ids, times, latencies, token counts, check reports) are
appended to .state.json for 60_read_usage.py.

Usage:
    python 50_invoke_hosted.py --dry-run
    python 50_invoke_hosted.py --i-understand-this-bills
    python 50_invoke_hosted.py --i-understand-this-bills --sessions 8 --question "..."
"""
from __future__ import annotations

import json
import statistics
import time
import uuid

import kitlib

# One question, asked again in the same session. The agent keeps no conversation memory,
# so the second call does the same work as the first.
DEFAULT_QUESTION = (
    "What final rules mentioning artificial intelligence were published in the last 30 days, "
    "and by which agencies?"
)


def new_session_id(prefix: str) -> str:
    """runtimeSessionId must be at least 33 characters. uuid4 is drawn per call, never at import."""
    session_id = f"{prefix}-kitc-{uuid.uuid4().hex}"
    assert len(session_id) >= 33
    return session_id


def read_body(response: dict) -> dict:
    raw = response.get("response")
    if hasattr(raw, "read"):
        raw = raw.read()
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        return {"result": raw}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def check_report(body: dict) -> tuple[bool, list[str]]:
    """(flagged, reasons) from the check report the runtime returned with the answer.

    Flagged means: the model's text was warned about, replaced or never finished. Only a
    call whose report says "ok" and carries no warning, no tool error and nothing
    unverified is clean.
    """
    if "grounding" not in body:
        return True, ["the response carries no grounding report (was the zip built from an older "
                      "copy of the kit?), so the answer is unchecked"]
    reasons: list[str] = []
    for key, label in (("unverified_document_numbers", "document numbers or citations no tool returned"),
                       ("unverified_numbers", "numbers that are in no tool result"),
                       ("unverified_dates", "dates that are in no tool result"),
                       ("unverified_urls", "URLs no tool returned"),
                       ("unverified_quotes", "phrases in quotation marks that are in no tool result"),
                       ("count_problems", "counts the tool results do not support"),
                       ("total_problems", "search totals given as counts of documents"),
                       ("window_problems", "periods the searches do not show")):
        values = body.get(key) or []
        if values:
            reasons.append(f"{label}: {', '.join(map(str, values))}")
    for error in body.get("tool_errors") or []:
        reasons.append(f"tool error: {error}")
    grounding_reasons = body.get("grounding_reasons") or []
    if "no_tool_called" in grounding_reasons:
        reasons.append("no tool was called; the model's text was withheld")
    if "no_document_cited" in grounding_reasons:
        reasons.append("the model's text names none of the documents the tools returned")
    if "imitates_kit_block" in grounding_reasons:
        reasons.append("the model's text holds a line shaped like the heading of the kit's own block")
    if "no_summary" in grounding_reasons:
        reasons.append("the model wrote no text")
    if "no_results" in grounding_reasons:
        reasons.append("every search returned nothing; the model's text was replaced by fixed text")
    if "nothing_returned" in grounding_reasons or "check_did_not_run" in grounding_reasons:
        reasons.append("no tool returned a document; the model's text was withheld")
    if "tool_failed" in grounding_reasons and not body.get("tool_errors"):
        reasons.append("a tool call failed")
    if body.get("stopped"):
        reasons.append(f"the agent was stopped early ({body.get('stopped')})")
    grounding = body.get("grounding")
    if not reasons and (grounding != "ok" or body.get("answer_replaced") or body.get("warnings")
                        or body.get("warning")):
        reasons.append(f"the runtime's check result was {grounding!r}"
                       + ("; the model's text was replaced" if body.get("answer_replaced") else ""))
    return bool(reasons), reasons


def warning_lines(body: dict) -> list[str]:
    """The WARNING lines of a response: the "warnings" list, or the "warning" text."""
    lines = [str(w) for w in (body.get("warnings") or []) if str(w).strip()]
    if not lines and isinstance(body.get("warning"), str) and body["warning"].strip():
        lines = [line for line in body["warning"].splitlines() if line.strip()]
    return lines


def _preview(text, limit: int = 300) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def main(argv: list[str] | None = None, aws: kitlib.Aws | None = None, out=print,
         state: kitlib.State | None = None) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    parser.add_argument("--sessions", type=int, default=5, help="number of sessions (default 5)")
    parser.add_argument("--calls-per-session", type=int, default=2,
                        help="calls in each session, all with the same question (default 2)")
    parser.add_argument("--question", action="append",
                        help="the question asked in every call (give it once)")
    args = parser.parse_args(argv)
    out = kitlib.redacting(out)  # review round 5, F13: no line carries a full account id
    if not 1 <= args.sessions <= 20:
        out("--sessions must be between 1 and 20")
        return 2
    if not 1 <= args.calls_per_session <= 5:
        out("--calls-per-session must be between 1 and 5")
        return 2
    if args.question and len(args.question) > 1:
        out("--question may be given once. Every call asks the same question, so that the first "
            "and the later calls of a session are comparable.")
        return 2
    cfg = kitlib.Config.from_env()
    aws = aws or kitlib.Aws(cfg.region, dry_run=args.dry_run, out=out)
    state = state or kitlib.State(dry_run=args.dry_run, out=out)
    question = (args.question or [DEFAULT_QUESTION])[0]

    idle_s = state.get("idle_timeout_s")
    life_s = state.get("max_lifetime_s")
    version, cpu_rate, mem_rate = cfg.rates(state.get("reported_platform_version"),
                                            state.get("requested_platform_version"))
    basis = cfg.rates_basis(state.get("reported_platform_version"),
                            state.get("requested_platform_version"))
    if not kitlib.confirm_billing(args, kitlib.PRICE_LINES_RUNTIME + kitlib.PRICE_LINES_MODEL + [
        f"This run: {args.sessions} session(s), {args.calls_per_session} call(s) each, the same "
        "question every time. Each call is one or more Bedrock model calls made from inside the "
        "runtime.",
    ] + kitlib.unstopped_session_lines(idle_s or cfg.idle_timeout_s, life_s or cfg.max_lifetime_s), out):
        return 2

    try:
        # doc: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        # Also the cheap first call: it resolves credentials before anything is timed.
        account = aws.call("sts", "get_caller_identity",
                           dry_result={"Account": kitlib.DRY_ACCOUNT})["Account"]
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    if not kitlib.check_place(state, cfg, account, out, "50_invoke_hosted.py", dry_run=args.dry_run):
        return kitlib.EXIT_STATE_MISMATCH

    runtime_arn = state.get("runtime_arn")
    if not runtime_arn:
        if not args.dry_run:
            out("No runtime in .state.json. Run 30_deploy.py first.")
            return 1
        runtime_arn = (f"arn:aws:bedrock-agentcore:{cfg.region}:{kitlib.DRY_ACCOUNT}:"
                       f"runtime/{cfg.runtime_name}-dryrun0000")

    # One-off client-side work, done before the first timed call (review finding M4): about
    # 0.2 s of service-definition loading and client construction measured offline.
    aws.warm("bedrock-agentcore", "invoke_agent_runtime", attempts=1)
    aws.warm("bedrock-agentcore", "stop_runtime_session")

    records = list(state.get("sessions", []))
    if not args.dry_run and state.get("usage_cross_checked_at"):
        # New sessions are about to be opened. An earlier CROSS-CHECKED read did not cover them,
        # so its stamp no longer stands and 90_teardown.py must warn again.
        state.remove("usage_cross_checked_at", "usage_reading", "usage_runtime_usd",
                     "usage_metric_usd", "usage_read_early", "usage_minutes_after_last_session")
    failed = 0
    stop_failures = 0
    not_comparable = 0
    first_call_ms: list[float] = []
    later_call_ms: list[float] = []
    payload = json.dumps({"prompt": question}).encode("utf-8")
    run_started = kitlib.utc_now()
    out(f"Started at {run_started:%Y-%m-%dT%H:%M:%SZ} (UTC).")
    out(f"Question for every call: {question}")

    for n in range(1, args.sessions + 1):
        session_id = new_session_id(cfg.prefix)
        record = {"session_id": session_id, "started_at": kitlib.utc_now_iso(), "calls": [],
                  "stopped": False}
        records.append(record)
        state.set(sessions=records)  # written before the first call, so teardown can stop it
        out(f"--- session {n}/{args.sessions}  {session_id}")
        earlier_call_failed = False
        try:
            for i in range(args.calls_per_session):
                started = time.perf_counter()
                try:
                    # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html (read 2026-10-07)
                    # No qualifier: "If not specified, Amazon Bedrock AgentCore uses the default endpoint".
                    response = aws.call(
                        "bedrock-agentcore", "invoke_agent_runtime", single_attempt=True,
                        agentRuntimeArn=runtime_arn, runtimeSessionId=session_id, payload=payload,
                        contentType="application/json", accept="application/json",
                        dry_result={"statusCode": 200, "response": json.dumps({
                            "result": "(dry run)", "grounding": "ok"}).encode()},
                    )
                    body = read_body(response)  # reading the body is part of the call
                    error = body.get("error")
                    if error and body.get("detail"):  # the runtime's own named error, with its reason
                        error = kitlib.redact(f"{error}: {' '.join(str(body['detail']).split())[:400]}")
                    status = response.get("statusCode")
                except Exception as exc:
                    body, status = {}, None
                    # the code AND what AWS said (it used to print the code twice and drop
                    # the message: "RuntimeClientError: RuntimeClientError")
                    error = kitlib.error_text(exc)
                ms = (time.perf_counter() - started) * 1000
                usage = body.get("usage") or {}
                flagged, reasons = (False, []) if error else check_report(body)
                warnings = [] if error else warning_lines(body)
                if earlier_call_failed:
                    position = "after a failed call"
                    label = ("after a failed call in this session: not known to be first or later, "
                             "left out of the latency summary")
                elif i == 0:
                    position, label = "first", "first call, new session"
                else:
                    position, label = "later", "same question, same session"
                call = {
                    "index": i, "latency_ms": round(ms, 1), "http_status": status,
                    "error": error, "tool_calls": len(body.get("tool_calls") or []),
                    "citations": len(body.get("citations") or []),
                    "documents_returned": len(body.get("documents_returned") or []),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "stopped": body.get("stopped"),
                    "grounding": body.get("grounding"),
                    "warnings": warnings,
                    "unverified_document_numbers": list(body.get("unverified_document_numbers") or []),
                    "unverified_numbers": list(body.get("unverified_numbers") or []),
                    "unverified_dates": list(body.get("unverified_dates") or []),
                    "unverified_urls": list(body.get("unverified_urls") or []),
                    "unverified_quotes": list(body.get("unverified_quotes") or []),
                    "count_problems": list(body.get("count_problems") or []),
                    "total_problems": list(body.get("total_problems") or []),
                    "window_problems": list(body.get("window_problems") or []),
                    "tool_errors": list(body.get("tool_errors") or []),
                    "answer_replaced": bool(body.get("answer_replaced")),
                    "flagged": flagged,
                    "flag_reasons": reasons,
                    "position": position,
                }
                record["calls"].append(call)
                if error:
                    failed += 1
                    earlier_call_failed = True
                    out(f"  call {i + 1} ({label}): FAILED after {ms:.0f} ms: {error}")
                    continue
                out(f"  call {i + 1} ({label}): {ms:.0f} ms end to end, {call['tool_calls']} tool "
                    f"call(s), {call['documents_returned']} document(s) returned, "
                    f"{call['citations']} cited by the model, tokens in/out "
                    f"{call['input_tokens']}/{call['output_tokens']}")
                # The WARNING lines come first, before any text of the answer is shown.
                for warning in warnings:
                    out(f"    {warning}")
                if flagged:
                    failed += 1
                    out("    FLAGGED, counted as a failed call and left out of the latency summary:")
                    for reason in reasons:
                        out(f"      - {reason}")
                elif position == "first":
                    first_call_ms.append(ms)
                elif position == "later":
                    later_call_ms.append(ms)
                if position == "after a failed call":
                    not_comparable += 1
                if "block" in body or "prose" in body:
                    out(f"    built by code from the tool results: {_preview(body.get('block')) or '(nothing)'}")
                    out("    the model's own text (its wording is not checked): "
                        f"{_preview(body.get('prose')) or '(withheld or empty)'}")
                else:
                    out(f"    {_preview(body.get('result'))}")
        finally:
            try:
                # doc: https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_StopRuntimeSession.html (read 2026-10-07)
                aws.call("bedrock-agentcore", "stop_runtime_session",
                         agentRuntimeArn=runtime_arn, runtimeSessionId=session_id,
                         dry_result={"statusCode": 200})
                record["stopped"] = True
            except Exception as exc:
                stop_failures += 1
                bounds = kitlib.session_cost_bounds(idle_s or kitlib.SERVICE_DEFAULT_IDLE_S,
                                                    life_s or kitlib.SERVICE_DEFAULT_LIFETIME_S, version)
                out(f"  COULD NOT STOP THE SESSION ({kitlib.error_text(exc)}). It ends by itself "
                    + (f"after {idle_s} idle seconds, the idle timeout recorded when the runtime "
                       "was deployed" if idle_s else
                       "after the runtime's idle timeout, which .state.json does not record (the "
                       f"service default is {kitlib.SERVICE_DEFAULT_IDLE_S} seconds)")
                    + f". Until then it bills memory: about ${bounds['idle']:.4f} if idle, at most "
                      f"${bounds['ceiling']:.3f} ({version} rates, {basis}). 90_teardown.py tries the "
                      "stop again.")
            record["ended_at"] = kitlib.utc_now_iso()
            state.set(sessions=records)

    out("")
    if args.dry_run:
        out("DRY-RUN complete: no AWS call was made.")
        return 0

    def summary(label: str, values: list[float]) -> None:
        if values:
            listed = ", ".join(f"{v:.0f}" for v in values)
            out(f"{label}: n={len(values)}  values {listed} ms  min {min(values):.0f}  "
                f"median {statistics.median(values):.0f}  max {max(values):.0f}")
        else:
            out(f"{label}: no clean call to report")

    out("Latency, end to end from this machine (network + AgentCore + model turns + Federal "
        "Register requests):")
    summary("  first call in a new session", first_call_ms)
    summary("  same question again, same session", later_call_ms)
    out("  The gap between the two lines estimates session start-up plus run-to-run variation. "
        "It is not a measured cold start, and n is small: quote the values, not a percentile.")
    out(f"Failed or flagged calls: {failed}")
    if not_comparable:
        out(f"Calls left out of both lines because an earlier call in their session failed: "
            f"{not_comparable}")
    if stop_failures:
        out(f"Sessions that could not be stopped: {stop_failures}")
    out(f"Runtime rates that apply ({version}, {basis}): ${cpu_rate} per vCPU-hour, "
        f"${mem_rate} per GB-hour.")
    finished = kitlib.utc_now()
    out(f"Finished at {finished:%Y-%m-%dT%H:%M:%SZ} (UTC), "
        f"{(finished - run_started).total_seconds() / 60:.1f} minute(s) after the start.")
    out(f'Usage arrives late. AWS: {kitlib.USAGE_DELAY_QUOTE} So the earliest read that can be')
    out(f"final is at {(finished + kitlib.USAGE_DELAY):%Y-%m-%dT%H:%M:%SZ} (UTC). Then run")
    out("    python 60_read_usage.py")
    out("Do not run 90_teardown.py until it prints RESULT: CROSS-CHECKED:")
    out("teardown deletes the log group that holds the usage records.")
    return 1 if failed or stop_failures else 0


if __name__ == "__main__":
    kitlib.script_main(main)
