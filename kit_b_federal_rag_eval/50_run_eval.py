#!/usr/bin/env python3
"""Step 50. Run the evaluation set and write the results table.

For every question: Retrieve from the knowledge base, generate one answer with
the Converse API, apply the contextual grounding guardrail to that answer
(ApplyGuardrail), ask a judge model to grade it against the expected answer,
and run the exact-match check. "Guardrail off" is the answer as generated;
"guardrail on" is the same answer after the guardrail verdict.

Writes results/<run>/per_question.csv, raw.jsonl, summary.json, summary.md,
run_config.json and last_question_calls.json (the counts of the question that was
last in flight; --resume uses it to count the calls of a question that was
interrupted). Prints a cost estimate before it starts. Try --limit 5 first.

Before any billed call it checks three things and stops if one fails:
  * .state.json describes the account, Region and prefix in use now;
  * the corpus in build/ is the corpus that was deployed, and the evaluation
    set was built from it (one fingerprint, written at each step);
  * with --resume, the settings are the ones the run was started with.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from kitlib import aws as api
from kitlib import config, evalloop, jsonl, pricing, scoring
from kitlib import state as state_mod
from kitlib.cli import banner, judge_family_line, make_parser, require_bills_flag, stop
from kitlib.redact import protect_output

RUN_CONFIG_LABELS = {
    "eval_set_sha256": "evaluation set (build/eval/eval_set.jsonl)",
    "eval_set_meta_sha256": "label sets and build record (build/eval/eval_set_meta.json)",
    "questions": "number of questions",
    "limit": "--limit",
    "corpus_fingerprint": "corpus fingerprint",
    "region": "Region",
    "knowledge_base_id": "knowledge base id",
    "kb_type": "knowledge base type",
    "retrieval": "retrieval settings",
    "top_k": "top k",
    "gen_model_id": "generation model",
    "judge_model_id": "judge model",
    "guardrail": "guardrail",
    "prompts_sha256": "prompts and rubric",
    "scoring_version": "scoring rules version",
}


def load_eval_set(build: Path) -> tuple[list[dict], dict, str]:
    data = (build / "eval" / "eval_set.jsonl").read_bytes()
    items = jsonl.loads_lines(data, "build/eval/eval_set.jsonl")       # split on the line feed only
    meta = json.loads((build / "eval" / "eval_set_meta.json").read_text(encoding="utf-8"))
    return items, meta, hashlib.sha256(data).hexdigest()


def meta_fingerprint(build: Path) -> str:
    """SHA-256 of build/eval/eval_set_meta.json as it is on disk. The label sets, which decide how every
    answer is scored, are in that file and in no other fingerprint (round 4)."""
    path = build / "eval" / "eval_set_meta.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def prompts_fingerprint() -> str:
    text = "\x00".join((evalloop.GEN_SYSTEM_PROMPT, evalloop.JUDGE_SYSTEM_PROMPT, evalloop.JUDGE_RUBRIC,
                        evalloop.NO_ANSWER_REFERENCE))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_differences(saved: dict, current: dict) -> list[str]:
    """Human-readable lines for every setting that differs between a saved run and now."""
    lines = []
    for key in sorted(set(saved) | set(current)):
        if saved.get(key) == current.get(key):
            continue
        label = RUN_CONFIG_LABELS.get(key, key)
        if key == "guardrail":
            old, new = saved.get(key) or {}, current.get(key) or {}
            for inner in sorted(set(old) | set(new)):
                if old.get(inner) != new.get(inner):
                    lines.append(f"guardrail {inner.replace('_', ' ')}: the run was started with "
                                 f"{old.get(inner)!r}, now {new.get(inner)!r}")
        else:
            lines.append(f"{label}: the run was started with {saved.get(key)!r}, now {current.get(key)!r}")
    return lines


def read_rows(raw_path: Path) -> tuple[list[dict], bool]:
    """Every row of raw.jsonl in the order written, and whether a row cut short at the end was left out.

    The file is split on the line feed and on nothing else (kitlib/jsonl.py): the text of a model
    or of a passage may hold a line separator, and str.splitlines() would cut the row there. A
    last line without a line feed that is not JSON is a row the process was stopped in the middle
    of; it is left out, so its question is run again. Any other line that cannot be read, or a
    row without an "id", raises jsonl.BadLine with the line number.
    """
    data = raw_path.read_bytes()
    rows = jsonl.loads_lines(data, str(raw_path), drop_cut_off_tail=True)
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or "id" not in row:
            raise jsonl.BadLine(str(raw_path), number, False, 'a row without an "id"')
    return rows, jsonl.ends_in_a_cut_off_line(data)


def split_attempts(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(latest row per question, earlier attempts), both in the order the rows were written."""
    last = {row["id"]: position for position, row in enumerate(rows)}
    latest = [row for position, row in enumerate(rows) if last[row["id"]] == position]
    earlier = [row for position, row in enumerate(rows) if last[row["id"]] != position]
    return latest, earlier


def read_attempts(raw_path: Path) -> tuple[list[dict], list[dict]]:
    """raw.jsonl keeps every attempt. Returns (latest row per question, earlier attempts)."""
    return split_attempts(read_rows(raw_path)[0])


# ---- the calls of the question in flight (round 4) ---------------------------------------------------------
# A row is written when its question is finished. Until then the calls that were already answered, and
# billed, were on no record: Ctrl-C during the generation call lost the Retrieve call, a process killed
# while the row was written lost all four. So after every answered call the counts of the question in
# flight are written to this file (numbers and ids only, no text). It is replaced by the next question's
# first answered call and is left in place when the run ends. --resume reads it: when raw.jsonl holds no
# more whole rows than it did when that question started, the row never arrived, and the record is
# written to raw.jsonl as an attempt of its own, so its calls are in the usage and the question is run again.
# Round 5: "no more whole rows" was the only test, so a row the person removed by hand (as the refusal for a
# damaged row tells him to) made a finished question look unfinished. The record now also holds how many rows
# of ITS question raw.jsonl held when the attempt started; the row arrived when there are more of them now,
# whatever happened to the rows of other questions. And each record that cannot be read is kept under a name
# of its own, so that two of them are counted as two.
CALLS_RECORD = "last_question_calls.json"
CALLS_RECORD_UNREADABLE = "last_question_calls.unreadable.json"
_UNREADABLE_GLOB = "last_question_calls.unreadable*.json"
INTERRUPTED = ("Interrupted: the run was stopped before this question finished. The calls counted in this row had "
               "been answered; the question was run again.")


def write_calls_record(out_dir: Path, row: dict, rows_before: int, answered: list[str],
                       question_rows_before: int = 0) -> None:
    """Replace the record in one step, so that a kill in the middle leaves the old file or the new one.

    rows_before: the whole rows of raw.jsonl when the question started; question_rows_before: how many of
    them are rows of this question (earlier attempts of it).
    """
    record = {"id": row["id"], "rows_before": rows_before, "question_rows_before": question_rows_before,
              "calls_answered": answered,
              "retrieved_doc_ids": row.get("retrieved_doc_ids"), "guardrail_action": row.get("guardrail_action"),
              "guardrail_units": row.get("guardrail_units", 0),
              "gen_input_tokens": row.get("gen_input_tokens", 0), "gen_output_tokens": row.get("gen_output_tokens", 0),
              "judge_input_tokens": row.get("judge_input_tokens", 0),
              "judge_output_tokens": row.get("judge_output_tokens", 0)}
    temporary = out_dir / (CALLS_RECORD + ".tmp")
    temporary.write_text(json.dumps(record) + "\n", encoding="utf-8")
    os.replace(temporary, out_dir / CALLS_RECORD)


def unreadable_records(out_dir: Path) -> list[Path]:
    """Every record that could not be read, in the order they were set aside."""
    def number(path: Path) -> int:
        tail = path.name[len("last_question_calls.unreadable"):-len(".json")]
        return int(tail[1:]) if tail[1:].isdigit() else 1
    return sorted(out_dir.glob(_UNREADABLE_GLOB), key=number)


def _free_unreadable_name(out_dir: Path) -> Path:
    """last_question_calls.unreadable.json, then ...unreadable-2.json, -3 ...: the first name not in use."""
    path, number = out_dir / CALLS_RECORD_UNREADABLE, 1
    while path.exists():
        number += 1
        path = out_dir / f"last_question_calls.unreadable-{number}.json"
    return path


def interrupted_attempt(out_dir: Path, rows: list[dict], items_by_id: dict) -> tuple[dict | None, str]:
    """(the row to add for a question whose row never reached raw.jsonl, a note for the screen).

    rows: the whole rows of raw.jsonl as they are now. (None, "") when there is no record or its question did
    get its row. (None, note) when the record cannot be read: it is then moved aside under a name of its own,
    and the summary says that its calls are not counted.
    """
    path = out_dir / CALLS_RECORD
    if not path.is_file():
        return None, ""
    whole_rows = len(rows)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        qid, rows_before = record["id"], int(record["rows_before"])
        own_before = record.get("question_rows_before")
        own_before = None if own_before is None else int(own_before)
        answered = [str(name) for name in record["calls_answered"]]
        numbers = {key: int(record.get(key) or 0) for key in ("guardrail_units", "gen_input_tokens", "gen_output_tokens",
                                                                 "judge_input_tokens", "judge_output_tokens")}
        doc_ids, action = record.get("retrieved_doc_ids"), record.get("guardrail_action")
        if qid not in items_by_id or not (doc_ids is None or isinstance(doc_ids, list)):
            raise ValueError("a record for a question that is not in the evaluation set")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        aside = _free_unreadable_name(out_dir)
        os.replace(path, aside)
        return None, (f"NOTE: {CALLS_RECORD} could not be read ({type(exc).__name__}). It holds the calls of the question "
                      f"that was in flight when the run was stopped. It was moved to {aside.name}; up to 4 "
                      "answered calls are not in the usage, and the summary says so.")
    if own_before is not None:
        # Round 5: the row of that attempt arrived when raw.jsonl holds more rows of its question than when the
        # attempt started. A row of another question that was removed by hand changes nothing here.
        arrived = sum(1 for row in rows if row.get("id") == qid) > own_before
    else:
        arrived = rows_before != whole_rows        # a record written before round 5
    if arrived or not answered:
        return None, ""                            # that question's row is in raw.jsonl, or no call was answered
    row = dict(evalloop.blank_row(items_by_id[qid]), retrieved_doc_ids=doc_ids, guardrail_action=action,
               interrupted=True, calls_answered=answered, error=INTERRUPTED, **numbers)
    row.update(scoring.with_guardrail(row))
    count = len(answered)
    return row, (f"NOTE: {qid} was in flight when the run was stopped: {count} call{'s' if count != 1 else ''} had been "
                 f"answered ({', '.join(answered)}). They are counted in the usage, and the question is run again.")


def actual_cost(summary: dict, settings: config.Settings, kb_type: str) -> dict:
    usage = summary["usage"]
    gen = pricing.token_cost(usage["gen_input_tokens"], usage["gen_output_tokens"],
                             pricing.model_price(settings.gen_model_id, "GEN"))
    judge = pricing.token_cost(usage["judge_input_tokens"], usage["judge_output_tokens"],
                               pricing.model_price(settings.judge_model_id, "JUDGE"))
    parts = {
        "generation": gen,
        "judge": judge,
        "guardrail_grounding": pricing.guardrail_cost(usage["guardrail_text_units"]),
        "retrieve_calls": pricing.retrieve_cost(usage["retrieve_calls"], kb_type),
    }
    known = [v for v in parts.values() if v is not None]
    return {"parts_usd": parts, "total_usd": sum(known), "complete": len(known) == len(parts)}


def write_outputs(out_dir: Path, rows: list[dict], settings: config.Settings, context: dict,
                  kb_type: str | None = None, earlier_attempts: list[dict] | None = None,
                  guardrail_applied: bool = True) -> dict:
    kb_type = kb_type or settings.kb_type
    set_aside = [path.name for path in unreadable_records(out_dir)]
    summary = scoring.summarise(rows, settings.top_k, earlier_attempts, guardrail_applied)
    summary["estimated_cost_from_measured_usage"] = actual_cost(summary, settings, kb_type)
    summary["context"] = context
    # csv_row() leaves no character in a cell that ends a line or cannot be encoded; the error
    # handler is a second net, so that this file is written whatever a cell holds.
    with (out_dir / "per_question.csv").open("w", encoding="utf-8", errors="backslashreplace", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=evalloop.CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(evalloop.csv_row(row))
    cost = summary["estimated_cost_from_measured_usage"]
    usage = summary["usage"]
    text = scoring.render_summary_markdown(summary, context)
    earlier = usage["earlier_failed_attempts_included"]
    unreadable = summary["usage"]["interrupted_without_a_record"] = len(set_aside)
    text += (
        "\nMeasured usage: "
        f"{usage['retrieve_calls']} Retrieve calls; generation {usage['gen_input_tokens']:,} input and "
        f"{usage['gen_output_tokens']:,} output tokens; judge {usage['judge_input_tokens']:,} input and "
        f"{usage['judge_output_tokens']:,} output tokens; guardrail {usage['guardrail_text_units']:,} text units "
        f"in {usage['guardrail_calls']} calls. This counts every call that was answered, in every attempt."
        + (f" This includes {earlier} earlier attempt(s) that failed or were interrupted part of the way and were "
           "run again with --resume: the calls that were answered in them were billed." if earlier else "")
        + (f" NOT COUNTED: the record of the calls of {unreadable} interrupted question(s) could not be read "
           f"({', '.join(set_aside)}); up to 4 answered calls each (one Retrieve, one generation, one guardrail, "
           "one judge call) are missing from these figures." if unreadable else "")
        + " Not counted here: a call that failed or was cut off before its answer arrived (by an error, by Ctrl-C "
          "or by a kill), and a call the SDK sent a second time is counted once; whether AWS bills those is not "
          "known to this kit.\n"
        f"Cost of this run at list price, computed from that usage: ${cost['total_usd']:.4f}"
        + ("" if cost["complete"] else " (INCOMPLETE: a model has no price in kitlib/pricing.py)")
        + f". Prices read {pricing.READ_DATE}, us-east-1. The bill is the real number.\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(text, encoding="utf-8")
    return summary


@protect_output
def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__, bills=True)
    parser.add_argument("--limit", type=int, default=0,
                        help="only the first N questions, in the order of the file (0 = all). The file starts "
                             "with the agency questions, so a small N is agency questions only: a smoke test, "
                             "not a sample. The summary says 'first N of <all>'")
    parser.add_argument("--no-guardrail", action="store_true",
                        help="skip the guardrail calls; every 'guardrail on' cell then says 'not applied'")
    parser.add_argument("--resume", type=Path, default=None,
                        help="results folder of an interrupted run; questions that finished without an error "
                             "are skipped. Needs the same settings and options the run was started with")
    args = parser.parse_args(argv)

    build = config.build_dir()
    try:
        state = config.load_state()                # a state file that cannot be read stops the run here
        # Region and prefix are compared before anything is printed or sent. The account is
        # compared further down, after the billing gate, because that needs one (free) STS call.
        state_mod.require_same_place(state, settings, None, "The evaluation")
    except state_mod.StopHere as error:
        return stop(error)
    try:
        items, meta, eval_sha = load_eval_set(build)
        manifest = json.loads((build / "corpus_manifest.json").read_text(encoding="utf-8"))
    except ValueError as exc:                      # a file in build/ that is cut short or is not JSON
        print(f"ERROR: a file in {build} cannot be read ({exc}). Run 10_build_corpus.py and "
              "20_build_eval_set.py again. Nothing was sent to Bedrock.", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        if not args.dry_run:
            print(f"ERROR: {exc.filename} not found. Run 10_build_corpus.py and 20_build_eval_set.py first.",
                  file=sys.stderr)
            return 1
        items, meta, manifest, eval_sha = [], {"label_sets": {}}, {"mean_document_chars": 1000}, ""
    all_questions = len(items)
    if args.limit > 0:
        items = items[:args.limit]
    limited = 0 < len(items) < all_questions
    # Said wherever the number of questions is said, so a run of the first few is never taken for the set.
    which = (f"first {len(items)} of {all_questions} questions (--limit {args.limit})" if limited
             else f"all {len(items)} questions")
    n = len(items) or 120
    # What was deployed decides the search type and the price of a Retrieve call, not the setting.
    kb_type = state.get("kb_type") or settings.kb_type

    banner(f"Kit B evaluation: {which}, top {settings.top_k}, in {settings.region}")
    if limited:
        print("NOTE: --limit takes the questions in the order of the file, which starts with the agency questions. "
              "This run is a smoke test, not a sample of the evaluation set.")
    print(f"Generation model: {settings.gen_model_id}\nJudge model     : {settings.judge_model_id}")
    print(f"Judge and generator: {judge_family_line(settings.gen_model_id, settings.judge_model_id)}")
    print(f"Retrieval: {api.describe_retrieval(kb_type)}")
    if kb_type != settings.kb_type:
        print(f"NOTE: KB_TYPE is '{settings.kb_type}' but .state.json records a '{kb_type}' knowledge base. "
              "The recorded type is used for the calls and for the prices.")
    estimate = pricing.estimate_eval_run(n, settings.top_k, manifest.get("mean_document_chars", 1000),
                                         settings.gen_model_id, settings.judge_model_id, kb_type,
                                         use_guardrail=not args.no_guardrail)
    gen_price = pricing.model_price(settings.gen_model_id, "GEN")
    judge_price = pricing.model_price(settings.judge_model_id, "JUDGE")

    def price_text(price):
        return (f"{pricing.fmt_usd(price[0])} input / {pricing.fmt_usd(price[1])} output per 1M tokens"
                if price else "NO VERIFIED PRICE, set PRICE_* variables")

    parts = estimate["parts_usd"]

    def usd(value):
        return f"${value:.4f}" if value is not None else "unknown"

    require_bills_flag(args, [
        f"Generation {settings.gen_model_id}: {price_text(gen_price)}. Estimate for {n} questions: "
        f"{estimate['gen_input_tokens']:,} input + {estimate['gen_output_tokens']:,} output tokens = {usd(parts['generation'])}.",
        f"Judge {settings.judge_model_id}: {price_text(judge_price)}. Estimate: "
        f"{estimate['judge_input_tokens']:,} input + {estimate['judge_output_tokens']:,} output tokens = {usd(parts['judge'])}.",
        (f"Contextual grounding check ${pricing.GUARDRAIL_GROUNDING_PER_1K_UNITS:.2f} per 1,000 text units. Estimate: "
         f"{estimate['guardrail_text_units']:,} units = {usd(parts['guardrail_grounding'])}." if not args.no_guardrail
         else "Contextual grounding check: NOT APPLIED (--no-guardrail), no ApplyGuardrail call, $0.0000."),
        f"Retrieve: {n} calls = {usd(parts['retrieve_calls'])} "
        + ("($1.00 per 1,000 calls on a Managed Knowledge Base)." if kb_type == "managed"
           else "(S3 Vectors query requests)."),
        f"ESTIMATED TOTAL for this run: ${estimate['total_usd']:.4f}"
        + ("" if estimate["complete"] else " plus the unknown items above") + ".",
        f"Token counts assume 4 characters per token (an assumption, not an AWS figure). Model prices: AWS "
        f"Price List files for us-east-1; guardrail and Retrieve prices: aws.amazon.com/bedrock/pricing/. "
        f"All read {pricing.READ_DATE}.",
    ])

    kb_id = state.get("knowledge_base_id")
    guardrail_id = state.get("guardrail_id")
    guardrail_version = state.get("guardrail_version")
    if guardrail_id == state_mod.PENDING:          # 40_create_guardrail.py was started and did not finish
        guardrail_id = guardrail_version = None
    use_guardrail = not args.no_guardrail
    if args.dry_run:
        kb_id = kb_id or "DRYRUNKB01"
        guardrail_id, guardrail_version = guardrail_id or "dryrunguardrail", guardrail_version or "1"
    if kb_id == state_mod.PENDING or state.get("data_source_id") == state_mod.PENDING:
        print("ERROR: 30_deploy_kb.py was started and did not finish: .state.json names the knowledge base or its "
              "data source but holds no id for it yet. Run 30_deploy_kb.py again (it reuses what exists), or "
              "90_teardown.py to remove it. Nothing was sent to Bedrock.", file=sys.stderr)
        return 1
    if not kb_id:
        print("ERROR: no knowledge base id in .state.json. Run 30_deploy_kb.py first.", file=sys.stderr)
        return 1
    if use_guardrail and not (guardrail_id and guardrail_version):
        print("ERROR: no guardrail in .state.json. Run 40_create_guardrail.py first, or pass --no-guardrail.",
              file=sys.stderr)
        return 1

    aws = api.Aws(settings.region, dry_run=args.dry_run)

    if args.dry_run:
        backend = api.BedrockBackend(aws, kb_id, kb_type, settings.top_k, settings.gen_model_id,
                                     settings.judge_model_id, guardrail_id, guardrail_version)
        sample = items[:1] or [{"id": "q-000", "type": "agency", "answerable": True,
                                "question": "(dry-run question)", "expected_answer": "(dry-run)",
                                "accepted_aliases": [], "label_set": "agency", "source_doc_id": "uc-0000"}]
        label_sets = meta.get("label_sets") or {}
        label_sets.setdefault("agency", [])
        print("One identity call, then the 4 calls for one question:")
        api.get_caller_identity(aws)
        evalloop.run(sample, backend, label_sets, use_guardrail)
        print(f"DRY-RUN ... the same 4 calls for each of the other {max(0, n - 1)} questions.")
        print("DRY-RUN: the account, the corpus fingerprint and the --resume settings are not checked in a "
              "dry run. The real run checks all three before the first billed call.")
        print("DRY-RUN: every call above was checked against the SDK's API model. None was sent. Nothing was written.")
        return 0

    # --- checks before the first billed call ---------------------------------------------------------
    try:
        # DOC: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
        account = api.get_caller_identity(aws)["Account"]
        state_mod.require_same_place(state, settings, account, "The evaluation")
    except state_mod.StopHere as error:
        return stop(error)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not find out which AWS account these credentials belong to "
              f"({type(exc).__name__}: {exc}). Nothing was sent to Bedrock.", file=sys.stderr)
        return 1

    deployed = state.get("corpus_fingerprint")
    on_disk = manifest.get("corpus_fingerprint")
    if not deployed or not on_disk:
        missing = ".state.json" if not deployed else "build/corpus_manifest.json"
        print(f"ERROR: {missing} carries no corpus fingerprint, so this run cannot tell whether the knowledge "
              "base holds the corpus in build/. Run 10_build_corpus.py, 20_build_eval_set.py and "
              "30_deploy_kb.py again (re-running the deploy is safe). Nothing was sent to Bedrock.",
              file=sys.stderr)
        return 1
    if deployed != on_disk:
        print(f"ERROR: the corpus in build/ (fingerprint {on_disk[:12]}) is not the corpus that was deployed "
              f"(fingerprint {deployed[:12]}). It was rebuilt after the deploy, so questions meant to have no "
              "answer may have one in the knowledge base. Run 30_deploy_kb.py again: it replaces the bucket "
              "contents and syncs. Nothing was sent to Bedrock.", file=sys.stderr)
        return 1
    if meta.get("corpus_fingerprint") != on_disk:
        print("ERROR: the evaluation set was built from another corpus than the one in build/. "
              "Run 20_build_eval_set.py again. Nothing was sent to Bedrock.", file=sys.stderr)
        return 1

    run_config = {
        "eval_set_sha256": eval_sha,
        "eval_set_meta_sha256": meta_fingerprint(build),
        "questions": len(items),
        "limit": args.limit if args.limit > 0 else 0,
        "corpus_fingerprint": deployed,
        "region": settings.region,
        "knowledge_base_id": kb_id,
        "kb_type": kb_type,
        "retrieval": api.describe_retrieval(kb_type),
        "top_k": settings.top_k,
        "gen_model_id": settings.gen_model_id,
        "judge_model_id": settings.judge_model_id,
        "guardrail": ({"applied": True, "id": guardrail_id, "version": guardrail_version,
                       "grounding_threshold": state.get("grounding_threshold"),
                       "relevance_threshold": state.get("relevance_threshold")}
                      if use_guardrail else {"applied": False}),
        "prompts_sha256": prompts_fingerprint(),
        "scoring_version": scoring.SCORING_VERSION,
    }

    if args.resume:
        out_dir = args.resume
        config_path = out_dir / "run_config.json"
        if not (out_dir / "raw.jsonl").is_file() or not config_path.is_file():
            print(f"ERROR: Refusing to resume: {out_dir} has no raw.jsonl or no run_config.json, so the settings "
                  "that run was started with are not known. Start a new run instead.", file=sys.stderr)
            return 1
        try:
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(saved_config, dict):
                raise ValueError("not a JSON object")
        except ValueError as exc:                  # cut short or edited: the settings of that run are not known
            print(f"ERROR: Refusing to resume: run_config.json in {out_dir} cannot be read ({exc}), so the settings "
                  "that run was started with are not known. Start a new run instead. Nothing was sent to Bedrock "
                  "and nothing in the results folder was changed.", file=sys.stderr)
            return 1
        differences = config_differences(saved_config, run_config)
        if differences:
            print("ERROR: Refusing to resume: the settings are not the ones this run was started with, and "
                  "rows produced under different settings must not share one table.", file=sys.stderr)
            for line in differences:
                print(f"  - {line}", file=sys.stderr)
            print("Resume with the same settings and options, or start a new run. Nothing was sent to Bedrock "
                  "and nothing in the results folder was changed.", file=sys.stderr)
            return 1
        # raw.jsonl is read HERE, before the first billed call, and not again: the summary is
        # built from these rows and the rows this run adds. So a file that cannot be read stops
        # the run now, when it costs nothing, and can never stop it after the calls are billed.
        try:
            rows_so_far, cut_short = read_rows(out_dir / "raw.jsonl")
        except jsonl.BadLine as exc:
            print(f"ERROR: Refusing to resume: {exc}. That row was damaged after it was written; this "
                  "script cannot tell what it held. Repair or remove that line by hand, or start a new run. "
                  "If you remove it, its question is run again and the calls that row held are no longer in the "
                  "usage line. Nothing was sent to Bedrock and nothing in the results folder was changed.",
                  file=sys.stderr)
            return 1
        if cut_short:
            print("NOTE: the last row of raw.jsonl was cut short (the run was stopped while it was written). "
                  "Its question is run again; the half row is moved to raw_cut_off_row.txt, so that every "
                  "line of raw.jsonl stays a whole row.")
        done = {row["id"] for row in split_attempts(rows_so_far)[0] if not row.get("error")}   # failed ones run again
        # The question that was in flight when the run was stopped (round 4). Nothing is written here yet.
        pending, pending_note = interrupted_attempt(out_dir, rows_so_far, {item["id"]: item for item in items})
        if pending_note:
            print(pending_note)
    else:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = config.results_dir() / f"run-{stamp}"
        attempt = 1
        while out_dir.exists():              # two runs started within the same second
            attempt += 1
            out_dir = config.results_dir() / f"run-{stamp}-{attempt}"
        out_dir.mkdir(parents=True, exist_ok=False)
        (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=1) + "\n", encoding="utf-8")
        done = set()
        rows_so_far, cut_short, pending = [], False, None
    print(f"Results folder: {out_dir}" + (f" (resuming, {len(done)} already done)" if done else ""))

    backend = api.BedrockBackend(aws, kb_id, kb_type, settings.top_k, settings.gen_model_id,
                                 settings.judge_model_id, guardrail_id, guardrail_version)
    raw_path = out_dir / "raw.jsonl"
    if cut_short:
        # Nothing is thrown away: the half row goes to a file of its own, then raw.jsonl is cut back
        # to the end of its last whole row.
        whole, _, half = raw_path.read_bytes().rpartition(b"\n")
        with (out_dir / "raw_cut_off_row.txt").open("ab") as aside:
            aside.write(half + b"\n")
        with raw_path.open("r+b") as handle:
            handle.truncate(len(whole) + 1 if whole else 0)
    # A file whose last row is whole but has no line feed after it (an editor took it away) gets
    # one first, so the next row starts on a line of its own.
    needs_line_feed = raw_path.is_file() and raw_path.stat().st_size > 0 and not raw_path.read_bytes().endswith(b"\n")
    raw = raw_path.open("a", encoding="utf-8", newline="\n")    # append only: every attempt is kept
    if needs_line_feed:
        raw.write("\n")
    if pending:
        # The interrupted attempt becomes a row of its own, marked with an error, so that its calls are in
        # the usage and its question is run again. Written before any new row.
        line = jsonl.dumps_line(pending)
        raw.write(line)
        raw.flush()
        rows_so_far.append(json.loads(line))
    counter = {"n": len(done)}
    record_failed = []

    def on_call(row: dict, answered: list[str]) -> None:
        try:
            write_calls_record(out_dir, row, len(rows_so_far), answered,
                               sum(1 for earlier in rows_so_far if earlier.get("id") == row["id"]))
        except OSError as exc:
            if not record_failed:
                print(f"NOTE: could not write {CALLS_RECORD} ({type(exc).__name__}: {exc}). The run goes on. If it is "
                      "stopped, the calls of the question in flight will not be counted after --resume.")
            record_failed.append(True)

    def on_row(row: dict) -> None:
        # One row, one physical line, whatever the answer, the judge's reply or a passage holds
        # (kitlib/jsonl.py). The row is kept as it reads back from that line, so the summary below
        # is built from exactly what is on disk without reading the file again.
        line = jsonl.dumps_line(row)
        raw.write(line)
        raw.flush()
        rows_so_far.append(json.loads(line))
        counter["n"] += 1
        ids = row.get("retrieved_doc_ids") or []
        unread = " (no document id readable)" if ids and not any(ids) else ""
        flag = "ERROR " + row["error"] if row["error"] else (
            f"hit={row['hit']}{unread} exact={row['exact']} judge={row['judge_verdict']} blocked={row['blocked']}")
        print(jsonl.one_line(f"  [{counter['n']}/{len(items)}] {row['id']} {row['type']}: {flag}"))

    resume_hint = (f"python 50_run_eval.py --resume {out_dir}" + (f" --limit {args.limit}" if args.limit > 0 else "")
                   + (" --no-guardrail" if args.no_guardrail else "") + " --i-understand-this-bills")
    try:
        evalloop.run(items, backend, meta["label_sets"], use_guardrail, on_row, done, on_call)
    except KeyboardInterrupt:
        raw.close()
        print(f"\nInterrupted. The calls that were answered for the question in flight are in {out_dir / CALLS_RECORD}; "
              f"--resume counts them and runs that question again.\nFinish later with: {resume_hint}")
        return 130
    raw.close()

    latest, earlier_attempts = split_attempts(rows_so_far)
    order = {item["id"]: position for position, item in enumerate(items)}
    rows = sorted((row for row in latest if row["id"] in order), key=lambda r: order[r["id"]])
    context = {
        "Run finished (UTC, this computer's clock)": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "Region": settings.region,
        "Knowledge base type": kb_type,
        "Retrieval": api.describe_retrieval(kb_type),
        "Corpus": f"{manifest.get('documents')} documents, OMB commit {str(manifest.get('commit'))[:12]}, "
                  f"seed {manifest.get('seed')}, fingerprint {deployed[:12]}",
        "Evaluation set": f"{which}, seed {meta.get('seed')}",
        "Top k": settings.top_k,
        "Generation model": settings.gen_model_id,
        "Judge model": settings.judge_model_id,
        "Judge and generator": judge_family_line(settings.gen_model_id, settings.judge_model_id),
        "Guardrail": (f"{guardrail_id} version {guardrail_version}, grounding threshold "
                      f"{state.get('grounding_threshold')}, relevance threshold {state.get('relevance_threshold')}")
        if use_guardrail else "NOT APPLIED (--no-guardrail)",
    }
    summary = write_outputs(out_dir, rows, settings, context, kb_type, earlier_attempts, use_guardrail)

    banner("Summary")
    print((out_dir / "summary.md").read_text(encoding="utf-8"))
    print(f"Files: {out_dir}/per_question.csv, raw.jsonl (every attempt, with the retrieved passage text), "
          "summary.json, summary.md, run_config.json")
    if not summary["complete"]:
        print(f"INCOMPLETE: {summary['questions_with_errors']} question(s) failed. Re-run them with: {resume_hint}")
        return 1
    print("Copy the table into RESULTS_TEMPLATE.md. When you are finished: python 90_teardown.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
