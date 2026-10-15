#!/usr/bin/env python3
"""10_run_local.py: run the graph on this machine against a model on Amazon Bedrock.

One question from the command line. Prints every tool call, then the answer as
the reader would see it: first the block that code builds from the tool results
(each search as sent with the API's total, each document returned), then any
WARNING, then the model's own text under its label (agent/graph.py has the
rule). After that come the token counts the model reported and the wall-clock
time. When there is a WARNING it is printed again as the very last line, so it
cannot scroll out of sight behind a long answer. Nothing is created in the
account, but each model turn is a Bedrock call billed per token, so the real
run needs --i-understand-this-bills.

Usage:
    python 10_run_local.py "What final rules mentioning artificial intelligence were published in the last 30 days, and by which agencies?" --i-understand-this-bills
    python 10_run_local.py "energy storage" --fake-model      # no AWS, no model; the tool call is real
    python 10_run_local.py "energy storage" --dry-run         # prints what would be called, calls nothing
"""
from __future__ import annotations

import json
import time

import kitlib

DEFAULT_QUESTION = (
    "What final rules mentioning artificial intelligence were published in the "
    "last 30 days, and by which agencies?"
)


def print_result(result: dict, seconds: float, model_label: str, out=print,
                 show_withheld: bool = False) -> None:
    out(f"Model: {model_label}")
    out(f"Tool calls ({len(result['tool_calls'])}):")
    for i, call in enumerate(result["tool_calls"], 1):
        out(f"  {i}. {call['name']}({json.dumps(call['args'], ensure_ascii=False)})")
    if result["tool_errors"]:
        out("Tool errors:")
        for err in result["tool_errors"]:
            out(f"  - {err}")
    out("")
    out(f"Check of the model's text against the tool results: {result['grounding']}"
        + (f" ({', '.join(result['grounding_reasons'])})" if result["grounding_reasons"] else ""))
    out("Answer:")
    out(result["answer"])
    if result["answer_replaced"]:
        withheld = result["withheld_answer"] or ""
        if show_withheld:
            out("")
            out("Withheld model text. NOT checked against any tool result. Do not rely on it:")
            out(withheld)
        else:
            out(f"(The model's own text, {len(withheld)} characters, was withheld because no tool "
                "result supports it. Add --show-withheld to print it for debugging.)")
    out("")
    out(f"Documents the model's text cites that a tool returned ({len(result['citations'])}):")
    for doc in result["citations"]:
        out(f"  - {doc['document_number']}  {doc['html_url']}")
    out(f"Documents the tools returned in this run ({len(result['documents_returned'])}):")
    for doc in result["documents_returned"]:
        out(f"  - {doc['document_number']}  {doc['html_url']}")
    for label, key in (("Document numbers or citations in the model's text that no tool returned",
                        "unverified_document_numbers"),
                       ("Numbers in the model's text that are in no tool result", "unverified_numbers"),
                       ("Dates in the model's text that are in no tool result", "unverified_dates"),
                       ("URLs in the model's text that no tool returned", "unverified_urls"),
                       ("Phrases the model's text puts in quotation marks that are in no tool result",
                        "unverified_quotes"),
                       ("Counts in the model's text that the tool results do not support", "count_problems"),
                       ("Search totals the model's text gives as counts of documents", "total_problems"),
                       ("Periods in the model's text that the searches do not show", "window_problems")):
        if result.get(key):
            out(f"{label}: {result[key]}")
    out(f"Search returned nothing: {result['no_results']}")
    out(f"Stopped early: {result['stopped'] or 'no'}")
    usage = result["usage"]
    out(f"Model turns: {usage['model_turns']}  input tokens: {usage['input_tokens']}  "
        f"output tokens: {usage['output_tokens']}")
    out(f"Wall-clock seconds: {seconds:.2f}")
    if result["warnings"]:
        from agent.graph import repeated_warning

        out(repeated_warning(result["warnings"]))
    elif result["grounding"] != "ok":
        out(f"NOTE (repeated from above): the check result was {result['grounding']}"
            + (f" ({', '.join(result['grounding_reasons'])})" if result["grounding_reasons"] else "")
            + ". The model's own text is not part of the answer above.")


def main(argv: list[str] | None = None, out=print) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--fake-model", action="store_true",
                        help="use the scripted fake model: no AWS call, no token cost")
    parser.add_argument("--recursion-limit", type=int, default=None,
                        help="graph step limit (default 12, about four tool rounds)")
    parser.add_argument("--show-withheld", action="store_true",
                        help="also print model text that the check withheld (debugging only)")
    args = parser.parse_args(argv)
    cfg = kitlib.Config.from_env()

    from agent.graph import DEFAULT_RECURSION_LIMIT, build_graph, run_question, validate_question

    try:
        question = validate_question(args.question)
    except ValueError as exc:
        out(f"Bad question: {exc}")
        return 2
    limit = args.recursion_limit or DEFAULT_RECURSION_LIMIT

    if args.dry_run:
        out("DRY-RUN  nothing is called. A real run would make:")
        out(f"DRY-RUN  would call bedrock-runtime.converse(modelId={cfg.model_id!r}, ...) in "
            f"{cfg.region}, once per model turn, at most {limit // 2} turns, through "
            "langchain_aws.ChatBedrockConverse")
        out("DRY-RUN  would call GET https://www.federalregister.gov/api/v1/documents.json "
            "(and /documents/<number>.json) once per tool call the model asks for")
        for line in kitlib.PRICE_LINES_MODEL:
            out(f"  {line}")
        return 0

    if args.fake_model:
        from agent.fake_model import demo_script

        model, label = demo_script(question), "fake model (no AWS call, no cost)"
    else:
        if not kitlib.confirm_billing(args, kitlib.PRICE_LINES_MODEL, out):
            return 2
        from agent.model import make_bedrock_model

        try:
            # AWS call made inside langchain-aws on each model turn: bedrock-runtime Converse
            # doc: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html (read 2026-10-07)
            model = make_bedrock_model(cfg.model_id, cfg.region)
        except Exception as exc:
            return kitlib.explain_aws_error(exc, out)
        label = f"{cfg.model_id} in {cfg.region}"

    graph = build_graph(model)
    started = time.perf_counter()
    try:
        result = run_question(graph, question, recursion_limit=limit)
    except Exception as exc:
        return kitlib.explain_aws_error(exc, out)
    print_result(result, time.perf_counter() - started, label, out, show_withheld=args.show_withheld)
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
