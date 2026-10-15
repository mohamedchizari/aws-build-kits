"""The AgentCore Runtime entrypoint: the same graph, wrapped for hosting.

AgentCore Runtime's HTTP contract is POST /invocations and GET /ping on port
8080. BedrockAgentCoreApp from the bedrock-agentcore package serves both and
routes /invocations to the function marked @app.entrypoint.
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html  (read 2026-10-07)
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html  (read 2026-10-07)
Pattern learned from AWS's current LangGraph sample (not copied):
  awslabs/agentcore-samples, 01-features/02-host-your-agent/01-runtime/
  01-hosting-agents/01-http-protocol/02-langgraph-bedrock/agent.py  (commit 3f2d283, read 2026-10-07)

Run locally (the documented local test):
    python agentcore_app.py
    curl -X POST http://localhost:8080/invocations \
         -H "Content-Type: application/json" -d '{"prompt": "..."}'
12_serve_local.py does the same and can use a fake model, so it needs no AWS.

Request body:  {"prompt": "<question>"}
Response body: {"result": "<everything the reader is shown, as one text>",
                "block": "<the part code built from the tool results>",
                "warning": "<the WARNING lines, or an empty string>", "warnings": [...],
                "notes": [<NOTE lines: information, not a failed check>],
                "prose": "<the model's own text, or an empty string when it was withheld>",
                "grounding": "ok" | "warned" | "replaced" | "stopped",
                "unverified_document_numbers": [...], "unverified_numbers": [...],
                "unverified_dates": [...], "unverified_urls": [...], "unverified_quotes": [...],
                "count_problems": [...], "total_problems": [...], "window_problems": [...],
                "tool_errors": [...], "citations": [...],
                "tool_calls": [...], ...}

"result" is never the model's raw text. It is built by the finalize node in
agent/graph.py: first "block", which code builds from the tool results of this
run (each search as sent with the API's total, then each document returned);
then "warning", when a check on the model's text failed; then "notes",
information lines that are not a failed check; then "prose", the model's own
text under a label that says it is the model's summary. A caller that shows
"result" to a person shows them in that order. A caller that lays the parts
out itself must show "warning" before "prose" and must not show "prose"
without "block". When no tool result supports anything, "result" is
fixed text, "prose" is empty, and the model's text is not sent back at all,
only its length ("withheld_answer_chars"), so it cannot be shown by mistake and
is not stored in the application logs. To read it, run the same question
locally: python 10_run_local.py "<question>" --show-withheld

The agent keeps no conversation memory: every request is answered on its own.
A session on AgentCore Runtime is still its own microVM, which is what the
latency and cost measurements in this kit are about.

Nothing here opens a connection or reads the clock at import time. The graph
and the Bedrock client are built on the first request and then reused. AWS's
guidance for platform version V2 is that import-time state is frozen into a
snapshot shared by every session, so connections, ids and dates must be made
per request.
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html  (read 2026-10-07)
"""
from __future__ import annotations

import os
import threading

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent.graph import DEFAULT_RECURSION_LIMIT, build_graph, run_question, validate_question

# LangChain and LangGraph spans. AWS lists opentelemetry-instrumentation-langchain (0.55.0 or
# newer) as a supported way to instrument LangGraph, and the LangGraph template of AWS's own
# AgentCore CLI makes this same call at import time.
#   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks.html  (read 2026-10-07)
#   aws/agentcore-cli, src/assets/python/http/langchain_langgraph/base/main.py  (commit dd6304e, read 2026-10-07)
# The package is only in the hosted zip (requirements-runtime.txt), so this is skipped locally.
# What this instrumentor writes into spans. Read in the package source on 2026-10-07
# (opentelemetry-instrumentation-langchain 0.62.4, utils.py, should_send_prompts): it records
# prompts and model output in span attributes unless TRACELOOP_TRACE_CONTENT is "false", and it
# reads the variable on every call. The model's output includes text that the finalize node
# withholds, so the variable is set to "false" by 30_deploy.py on the hosted runtime and again
# here in case the runtime's variables were edited by hand. Set it to "true" yourself only if
# you want prompts and model text stored in CloudWatch.
# UNVERIFIED: what the spans hold on AgentCore with this set. No span was produced here, and the
# other instrumentations that aws-opentelemetry-distro switches on were not read.
os.environ.setdefault("TRACELOOP_TRACE_CONTENT", "false")
try:
    from opentelemetry.instrumentation.langchain import LangchainInstrumentor

    LangchainInstrumentor().instrument()
except Exception:  # not installed, or instrumentation is unavailable: run without spans
    pass

app = BedrockAgentCoreApp()

_graph = None
_graph_lock = threading.Lock()
_model_label = None


def _use_fake_model() -> bool:
    return os.environ.get("KIT_FAKE_MODEL", "").strip().lower() in {"1", "true", "yes"}


def _get_graph(question: str):
    """Build the graph once per process. The fake model is rebuilt per request."""
    global _graph, _model_label
    if _use_fake_model():
        from agent.fake_model import demo_script

        return build_graph(demo_script(question)), "fake (KIT_FAKE_MODEL is set)"
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                from agent.model import make_bedrock_model, resolve_model_id

                _graph = build_graph(make_bedrock_model())
                _model_label = resolve_model_id()
    return _graph, _model_label


@app.entrypoint
def invoke(payload, context):
    """Called for every POST /invocations."""
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "invalid_input", "detail": 'send {"prompt": "<your question>"}'}
    try:
        prompt = validate_question(prompt)
    except ValueError as exc:
        return {"error": "invalid_input", "detail": str(exc)}
    try:
        graph, model_label = _get_graph(prompt)
        result = run_question(
            graph,
            prompt,
            recursion_limit=int(os.environ.get("KIT_RECURSION_LIMIT", DEFAULT_RECURSION_LIMIT)),
        )
    except ValueError as exc:
        # Not the caller's fault: the prompt passed validation above. A model response that
        # does not fit its schema raises ValueError too, and that used to be reported to the
        # caller as "invalid_input" (review round 4, m8).
        return {"error": "run_failed", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}
    return {
        "result": result["answer"],
        "block": result["block"],
        "warning": "\n".join(result["warnings"]),
        "warnings": result["warnings"],
        "notes": result["notes"],
        "prose": result["model_summary"] or "",
        "prose_label": result["summary_label"] or "",
        "grounding": result["grounding"],
        "grounding_reasons": result["grounding_reasons"],
        "answer_replaced": result["answer_replaced"],
        "withheld_answer_chars": len(result["withheld_answer"] or ""),
        "citations": result["citations"],
        "documents_returned": result["documents_returned"],
        "searches": result["searches"],
        "tool_calls": result["tool_calls"],
        "no_results": result["no_results"],
        "unverified_document_numbers": result["unverified_document_numbers"],
        "mentioned_only_references": result["mentioned_only_references"],
        "asked_not_returned": result["asked_not_returned"],
        "unverified_numbers": result["unverified_numbers"],
        "unverified_dates": result["unverified_dates"],
        "unverified_urls": result["unverified_urls"],
        "unverified_quotes": result["unverified_quotes"],
        "count_problems": result["count_problems"],
        "total_problems": result["total_problems"],
        "window_problems": result["window_problems"],
        "tool_errors": result["tool_errors"],
        "stopped": result["stopped"],
        "usage": result["usage"],
        "model_id": model_label,
        "session_id": getattr(context, "session_id", None),
    }


def bind_host() -> str:
    """The address the server listens on.

    The Runtime contract says "Host: 0.0.0.0", port 8080:
      https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html  (read 2026-10-07)
    The SDK's app.run() picks 127.0.0.1 unless /.dockerenv exists or DOCKER_CONTAINER is set
    (bedrock-agentcore 1.24.1, runtime/app.py, run), and nothing in a direct-code runtime is
    documented to set either. So the host is not left to that guess: 30_deploy.py sets
    KIT_BIND_HOST=0.0.0.0 on the hosted runtime and this passes it to app.run(). On your own
    machine the variable is absent and the server stays on 127.0.0.1.
    # UNVERIFIED: that a direct-code runtime reaches the server on 0.0.0.0:8080 (not run
    # against AWS), and that a bare app.run() would not have worked as well: AWS's own
    # direct-code samples call app.run() with no arguments.
    """
    return os.environ.get("KIT_BIND_HOST", "").strip() or "127.0.0.1"


if __name__ == "__main__":
    app.run(host=bind_host())
