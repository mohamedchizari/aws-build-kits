"""The evaluation loop: retrieve, generate, check grounding, judge, score.

The loop talks to a `backend` object, so the same code runs against Amazon
Bedrock (kitlib.aws.BedrockBackend) and against fakes in the offline tests.

How "guardrail off" and "guardrail on" are compared
  Each question is retrieved and answered ONCE. "Off" is that answer as
  generated. "On" is the same answer after the contextual grounding check
  (ApplyGuardrail): if the guardrail intervenes, the answer is replaced by a
  block. So the two columns differ only by the guardrail, not by sampling noise.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import scoring
from .jsonl import one_line
from .redact import redact

# Limits of the contextual grounding check.
# DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html (read 2026-10-07)
GROUNDING_SOURCE_MAX_CHARS = 100_000
GROUNDING_QUERY_MAX_CHARS = 1_000
GROUNDING_ANSWER_MAX_CHARS = 5_000

GEN_SYSTEM_PROMPT = (
    "You answer questions about the OMB 2025 Federal Agency AI Use Case Inventory. "
    "Use only the passages given in the user message. Rules:\n"
    "1. State only facts that are written in the passages.\n"
    "2. When the answer is a field value (the agency, the stage of development, the high-impact "
    "determination), quote that value exactly as it is written in the passage.\n"
    "3. Answer in one short sentence.\n"
    "4. If the passages do not contain the answer, reply with exactly this sentence and nothing else: "
    f"{scoring.DECLINE_SENTENCE}"
)

JUDGE_SYSTEM_PROMPT = (
    "You grade one answer against a reference. You do not answer the question yourself. "
    "Reply with one JSON object and nothing else."
)

# The reply format is written so that the rubric, if a model echoes it back, is not itself a
# verdict: scoring.parse_judge reads "<one of ...>" as no verdict at all.
JUDGE_RUBRIC = (
    "Grade the candidate answer.\n"
    "- CORRECT: the candidate states the reference answer (same fact, wording may differ) and states "
    "no fact that contradicts it.\n"
    "- DECLINED: the candidate says it cannot answer or has no information, and gives no answer.\n"
    "- INCORRECT: anything else. This includes a different answer, an answer with a contradicting "
    "fact added, and ANY substantive answer when the reference is NO ANSWER.\n"
    "When the reference is NO ANSWER the verdict is DECLINED if the candidate declines and INCORRECT "
    "if it gives any answer. It is never CORRECT.\n"
    'Reply with one JSON object and nothing else, in this form: '
    '{"verdict": "<one of CORRECT, INCORRECT, DECLINED>", "reason": "<at most 20 words>"}'
)

# The reference shown to the judge for a question that has no answer in the corpus. The text is in
# kitlib/scoring.py, because the reader of the judge's reply has to know it too.
NO_ANSWER_REFERENCE = scoring.NO_ANSWER_REFERENCE


@dataclass
class Passage:
    text: str
    doc_id: str | None = None
    score: float | None = None
    uri: str | None = None


def build_generation_prompt(question: str, passages: list[Passage]) -> str:
    blocks = [f"[{i}] (document {p.doc_id or 'unknown'})\n{p.text.strip()}"
              for i, p in enumerate(passages, start=1)]
    body = "\n\n".join(blocks) if blocks else "(no passages were retrieved)"
    return f"Passages:\n\n{body}\n\nQuestion: {question}"


def build_judge_prompt(item: dict, answer: str) -> str:
    if item["answerable"]:
        reference = item["expected_answer"]
        aliases = [a["text"] for a in item.get("accepted_aliases", []) if a.get("text")]
        if aliases:
            reference += f" (also acceptable: {', '.join(aliases)})"
    else:
        reference = NO_ANSWER_REFERENCE
    return (f"{JUDGE_RUBRIC}\n\nQuestion: {item['question']}\n"
            f"Reference answer: {reference}\nCandidate answer: {answer.strip() or '(empty)'}")


def grounding_source_text(passages: list[Passage]) -> str:
    text = "\n\n".join(p.text.strip() for p in passages) or "No passages were retrieved."
    return text[:GROUNDING_SOURCE_MAX_CHARS]


def blank_row(item: dict) -> dict:
    """The row of one question before any call was answered."""
    return {
        "id": item["id"], "type": item["type"], "answerable": item["answerable"],
        "question": item["question"], "expected_answer": item["expected_answer"],
        "source_doc_id": item.get("source_doc_id"),
        "retrieved_doc_ids": None, "retrieved_passages": None, "hit": None, "hit_rank": None,
        "answer": "", "declined": False, "exact": False, "exact_unclear": False, "exact_note": "",
        "exact_unread": "", "asserted": [],
        "judge_verdict": None, "judge_note": "", "judged_correct": False,
        "guardrail_action": None, "blocked": False, "grounding_score": None,
        "relevance_score": None, "guardrail_units": 0, "answer_truncated_for_guardrail": False,
        "gen_input_tokens": 0, "gen_output_tokens": 0, "gen_stop_reason": None,
        "judge_input_tokens": 0, "judge_output_tokens": 0, "judge_stop_reason": None,
        "error": None,
    }


def evaluate_item(item: dict, backend, label_sets: dict, use_guardrail: bool = True, on_call=None) -> dict:
    """Run one question end to end and return its result row.

    on_call(row, calls) is called after EVERY call that was answered, with the row as far as it is
    filled and the names of the calls answered so far ("Retrieve", "generation", "guardrail", "judge").
    50_run_eval.py uses it to keep the counts of the question in flight on disk, so that a run stopped
    between two calls does not lose the calls that were already answered (and billed).
    """
    row = blank_row(item)
    calls: list[str] = []

    def answered(name: str) -> None:
        calls.append(name)
        if on_call:
            on_call(row, list(calls))

    try:
        passages = backend.retrieve(item["question"])
        row["retrieved_doc_ids"] = [p.doc_id for p in passages]
        answered("Retrieve")
        # The passage text is kept (in raw.jsonl only) so a blocked answer can be audited later:
        # these passages, joined, are exactly the grounding source the guardrail was given.
        row["retrieved_passages"] = [
            {"doc_id": p.doc_id, "score": p.score, "uri": redact(p.uri) if p.uri else p.uri, "text": p.text}
            for p in passages]
        hit = scoring.retrieval_hit(item.get("source_doc_id"), row["retrieved_doc_ids"])
        row["hit"], row["hit_rank"] = hit["hit"], hit["rank"]

        generated = backend.generate(GEN_SYSTEM_PROMPT, build_generation_prompt(item["question"], passages))
        answer = generated["text"]
        row["answer"] = answer
        row["gen_input_tokens"] = generated.get("input_tokens", 0)
        row["gen_output_tokens"] = generated.get("output_tokens", 0)
        row["gen_stop_reason"] = generated.get("stop_reason")      # "max_tokens": the answer was cut at the limit
        answered("generation")

        exact = scoring.score_exact(item, answer, label_sets)
        row.update({"exact": exact["exact"], "declined": exact["declined"], "exact_unclear": exact["unclear"],
                    "exact_note": exact["note"], "exact_unread": exact["unread"], "asserted": exact["asserted"]})

        if use_guardrail:
            guard_answer = answer.strip() or "(empty)"
            if len(guard_answer) > GROUNDING_ANSWER_MAX_CHARS:
                guard_answer = guard_answer[:GROUNDING_ANSWER_MAX_CHARS]
                row["answer_truncated_for_guardrail"] = True
            verdict = backend.apply_guardrail(
                grounding_source_text(passages), item["question"][:GROUNDING_QUERY_MAX_CHARS], guard_answer)
            row["guardrail_action"] = verdict["action"]
            row["blocked"] = verdict["action"] == "GUARDRAIL_INTERVENED"
            row["grounding_score"] = verdict.get("grounding_score")
            row["relevance_score"] = verdict.get("relevance_score")
            row["guardrail_units"] = verdict.get("units", 0)
            answered("guardrail")

        judged = backend.judge(JUDGE_SYSTEM_PROMPT, build_judge_prompt(item, answer))
        row["judge_input_tokens"] = judged.get("input_tokens", 0)
        row["judge_output_tokens"] = judged.get("output_tokens", 0)
        row["judge_stop_reason"] = judged.get("stop_reason")
        answered("judge")
        # The reader is told which question this is, so that a value the judge only quotes
        # ("Not High-impact") is not read as the judge speaking against its own verdict.
        reading = scoring.read_judge(judged["text"], item, answer, label_sets)
        row["judge_verdict"] = reading["verdict"]
        row["judge_note"] = reading["why"]             # why a reply was unparseable; empty otherwise
        # The whole reply (round 4: it was cut at 500 characters, so judge_note could name a word that
        # was not in the kept text). The judge may write 120 tokens.
        row["judge_raw"] = judged["text"]
        row["judged_correct"] = scoring.judged_correct(item, row["judge_verdict"])
    except Exception as exc:  # noqa: BLE001 - one bad question must not lose the whole run
        row["error"] = redact(f"{type(exc).__name__}: {exc}")[:500]   # AWS errors can carry an account id
    row.update(scoring.with_guardrail(row))
    return row


def run(items: list[dict], backend, label_sets: dict, use_guardrail: bool = True,
        on_row=None, done_ids: frozenset[str] | set[str] = frozenset(), on_call=None) -> list[dict]:
    """Evaluate every item not already done. Calls on_row(row) after each one, and on_call(row so far,
    names of the calls answered) after every call that was answered."""
    rows = []
    for item in items:
        if item["id"] in done_ids:
            continue
        row = evaluate_item(item, backend, label_sets, use_guardrail, on_call)
        rows.append(row)
        if on_row:
            on_row(row)
    return rows


# per_question.csv is the table you read row by row. The retrieved passage TEXT is not in
# it (it would make the rows unreadable); it is in raw.jsonl under "retrieved_passages".
CSV_COLUMNS = [
    "id", "type", "answerable", "question", "expected_answer", "source_doc_id",
    "retrieved_doc_ids", "hit", "hit_rank",
    "answer", "declined", "exact", "exact_unclear", "exact_note", "exact_unread", "judge_verdict",
    "judge_note", "judged_correct",
    "guardrail_action", "blocked", "grounding_score", "relevance_score", "guardrail_units",
    "exact_on", "judged_correct_on", "declined_on",
    "gen_input_tokens", "gen_output_tokens", "gen_stop_reason", "judge_input_tokens", "judge_output_tokens",
    "judge_stop_reason", "error",
]


def csv_row(row: dict) -> dict:
    """One row of per_question.csv. Every text cell is one physical line: the answer's white space
    is collapsed as before, and in every cell a character that would end a line or cannot be
    stored (a line or paragraph separator, a control character, a NUL, a lone surrogate) is shown
    as an escape. The text exactly as it arrived is in raw.jsonl."""
    out = {key: row.get(key) for key in CSV_COLUMNS}
    ids = row.get("retrieved_doc_ids")
    out["retrieved_doc_ids"] = " ".join(d or "?" for d in ids) if ids is not None else ""
    out["answer"] = " ".join((row.get("answer") or "").split())
    return {key: one_line(value) if isinstance(value, str) else value for key, value in out.items()}
