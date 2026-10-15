"""The evaluation loop end to end with a fake backend: no AWS, fixed answers, hand-checked numbers."""
from __future__ import annotations

from kitlib import evalloop, scoring
from kitlib.evalloop import Passage
from kitlib.evalset import HIGH_IMPACT_LABELS, NO_ANSWER, STAGE_LABELS, simple_label_set

LABEL_SETS = {
    "agency": [{"label": "Department of Energy", "aliases": [{"text": "DOE", "case_sensitive": True}]},
               {"label": "Department of Justice", "aliases": [{"text": "DOJ", "case_sensitive": True}]}],
    "stage": simple_label_set(STAGE_LABELS),
    "high_impact": simple_label_set(HIGH_IMPACT_LABELS),
}


def make_item(n, kind, expected, source, answerable=True):
    return {"id": f"q-{n:03d}", "type": kind, "answerable": answerable,
            "question": f'Question {n} about "Use case {n}"?', "use_case_name": f"Use case {n}",
            "expected_answer": expected if answerable else NO_ANSWER, "accepted_aliases": [],
            "label_set": kind if answerable else None, "source_doc_id": source if answerable else None}


ITEMS = [
    make_item(1, "agency", "Department of Energy", "uc-0001"),
    make_item(2, "stage", "Pilot", "uc-0002"),
    make_item(3, "high_impact", "Not High-impact", "uc-0003"),
    make_item(4, "agency", "Department of Justice", "uc-0004"),
    make_item(5, "unanswerable_heldout", None, None, answerable=False),
    make_item(6, "unanswerable_absent_field", None, None, answerable=False),
]

# What the fake system does for each question:
#   q1 right, source ranked 1, guardrail passes
#   q2 right, source ranked 2, guardrail BLOCKS (a false block)
#   q3 wrong value, source not retrieved, guardrail BLOCKS (a useful block)
#   q4 refuses although answerable, guardrail passes
#   q5 refuses as it should, guardrail passes
#   q6 invents an answer, guardrail BLOCKS (a useful block)
SCRIPT = {
    "q-001": dict(docs=["uc-0001", "uc-0009"], answer="The Department of Energy.", judge='{"verdict": "CORRECT"}',
                  action="NONE", g=0.95, r=0.9),
    "q-002": dict(docs=["uc-0007", "uc-0002"], answer="The stage of development is Pilot.",
                  judge='{"verdict": "CORRECT"}', action="GUARDRAIL_INTERVENED", g=0.4, r=0.9),
    "q-003": dict(docs=["uc-0008"], answer="The determination is High-impact.", judge='{"verdict": "INCORRECT"}',
                  action="GUARDRAIL_INTERVENED", g=0.2, r=0.8),
    "q-004": dict(docs=["uc-0004"], answer=scoring.DECLINE_SENTENCE, judge='{"verdict": "DECLINED"}',
                  action="NONE", g=0.9, r=0.9),
    "q-005": dict(docs=["uc-0010"], answer=scoring.DECLINE_SENTENCE, judge='{"verdict": "DECLINED"}',
                  action="NONE", g=0.9, r=0.9),
    "q-006": dict(docs=["uc-0011"], answer="The annual budget is 4 million dollars.",
                  judge='{"verdict": "INCORRECT"}', action="GUARDRAIL_INTERVENED", g=0.1, r=0.7),
}


class FakeBackend:
    def __init__(self, script=SCRIPT, fail_on=()):
        self.script, self.fail_on = script, set(fail_on)
        self.current = None
        self.log = []

    def retrieve(self, question):
        self.current = "q-%03d" % int(question.split()[1])
        self.log.append(("retrieve", self.current))
        if self.current in self.fail_on:
            raise RuntimeError("ThrottlingException: rate exceeded")
        return [Passage(text=f"text of {d}", doc_id=d, score=0.5) for d in self.script[self.current]["docs"]]

    def generate(self, system, user):
        self.log.append(("generate", self.current))
        assert system == evalloop.GEN_SYSTEM_PROMPT and "Passages:" in user and "Question:" in user
        return {"text": self.script[self.current]["answer"], "input_tokens": 1000, "output_tokens": 10}

    def apply_guardrail(self, sources, question, answer):
        self.log.append(("guardrail", self.current))
        assert "text of uc-" in sources and answer
        step = self.script[self.current]
        return {"action": step["action"], "grounding_score": step["g"], "relevance_score": step["r"], "units": 2}

    def judge(self, system, user):
        self.log.append(("judge", self.current))
        assert "Reference answer:" in user and "Candidate answer:" in user
        return {"text": self.script[self.current]["judge"], "input_tokens": 300, "output_tokens": 15}


def test_each_question_makes_exactly_four_calls_in_order():
    backend = FakeBackend()
    evalloop.run(ITEMS[:1], backend, LABEL_SETS)
    assert backend.log == [("retrieve", "q-001"), ("generate", "q-001"), ("guardrail", "q-001"), ("judge", "q-001")]


def test_rows_carry_the_expected_outcomes():
    rows = {r["id"]: r for r in evalloop.run(ITEMS, FakeBackend(), LABEL_SETS)}
    r1, r2, r3, r4, r5, r6 = (rows[f"q-00{i}"] for i in range(1, 7))

    assert (r1["hit"], r1["hit_rank"], r1["exact"], r1["judged_correct"], r1["blocked"]) == (True, 1, True, True, False)
    assert (r1["exact_on"], r1["judged_correct_on"]) == (True, True)

    assert (r2["hit_rank"], r2["exact"], r2["judged_correct"], r2["blocked"]) == (2, True, True, True)
    assert (r2["exact_on"], r2["judged_correct_on"], r2["declined_on"]) == (False, False, True)
    assert (r2["grounding_score"], r2["relevance_score"], r2["guardrail_units"]) == (0.4, 0.9, 2)

    assert (r3["hit"], r3["exact"], r3["exact_note"], r3["judged_correct"]) == (False, False, "different_value", False)
    assert (r4["declined"], r4["exact"], r4["judge_verdict"], r4["judged_correct"]) == (True, False, "DECLINED", False)
    assert (r5["hit"], r5["declined"], r5["exact"], r5["judged_correct"]) == (None, True, True, True)
    assert (r6["exact"], r6["judged_correct"], r6["blocked"]) == (False, False, True)
    assert (r6["exact_on"], r6["judged_correct_on"]) == (True, True)


def test_summary_of_the_scripted_run():
    rows = evalloop.run(ITEMS, FakeBackend(), LABEL_SETS)
    s = scoring.summarise(rows, top_k=5)
    assert (s["answerable_n"], s["unanswerable_n"], s["complete"]) == (4, 2, True)
    assert s["retrieval"]["hit_at_k"]["count"] == 3 and s["retrieval"]["hit_at_1"]["count"] == 2
    off, on = s["guardrail_off"], s["guardrail_on"]
    assert (off["answerable_exact_correct"]["count"], on["answerable_exact_correct"]["count"]) == (2, 1)
    assert (off["answerable_judged_correct"]["count"], on["answerable_judged_correct"]["count"]) == (2, 1)
    assert (off["answerable_refused"]["count"], on["answerable_refused"]["count"]) == (1, 3)
    assert (off["unanswerable_refused"]["count"], on["unanswerable_refused"]["count"]) == (1, 2)
    assert (off["unanswerable_answered_anyway"]["count"], on["unanswerable_answered_anyway"]["count"]) == (1, 0)
    assert s["guardrail_blocks"] == {
        "total": 3, "on_refusal_sentences": 0, "on_answerable_judged_correct": 1,
        "on_answerable_judged_incorrect": 1, "on_unanswerable_answered_anyway": 1,
        "on_unanswerable_soft_refusals": 0, "on_unanswerable_judge_unclear": 0}
    assert s["usage"] == {"retrieve_calls": 6, "gen_input_tokens": 6000, "gen_output_tokens": 60,
                          "judge_input_tokens": 1800, "judge_output_tokens": 90,
                          "guardrail_text_units": 12, "guardrail_calls": 6, "earlier_failed_attempts_included": 0,
                          "interrupted_attempts_included": 0}


def test_without_the_guardrail_the_two_columns_are_identical():
    backend = FakeBackend()
    rows = evalloop.run(ITEMS, backend, LABEL_SETS, use_guardrail=False)
    assert not [entry for entry in backend.log if entry[0] == "guardrail"]
    for row in rows:
        assert row["guardrail_action"] is None and row["blocked"] is False
        assert (row["exact_on"], row["judged_correct_on"]) == (row["exact"], row["judged_correct"])
    assert scoring.summarise(rows, 5)["guardrail_blocks"]["total"] == 0


def test_an_error_on_one_question_is_recorded_and_the_run_continues():
    rows = evalloop.run(ITEMS, FakeBackend(fail_on={"q-002"}), LABEL_SETS)
    assert len(rows) == 6
    failed = [r for r in rows if r["error"]]
    assert [r["id"] for r in failed] == ["q-002"]
    assert failed[0]["error"].startswith("RuntimeError: ThrottlingException")
    assert failed[0]["exact"] is False and failed[0]["judged_correct_on"] is False
    summary = scoring.summarise(rows, 5)
    assert summary["complete"] is False and summary["answerable_n"] == 3


def test_resume_skips_questions_already_done_and_reports_each_new_row():
    backend = FakeBackend()
    seen = []
    rows = evalloop.run(ITEMS, backend, LABEL_SETS, on_row=seen.append, done_ids={"q-001", "q-002", "q-003"})
    assert [r["id"] for r in rows] == ["q-004", "q-005", "q-006"] == [r["id"] for r in seen]
    assert ("retrieve", "q-001") not in backend.log


def test_prompts_are_fixed_and_carry_the_decline_sentence_and_the_rubric():
    assert scoring.DECLINE_SENTENCE in evalloop.GEN_SYSTEM_PROMPT
    prompt = evalloop.build_generation_prompt("Q?", [Passage("alpha", "uc-0001"), Passage("beta", None)])
    assert prompt == "Passages:\n\n[1] (document uc-0001)\nalpha\n\n[2] (document unknown)\nbeta\n\nQuestion: Q?"
    assert "(no passages were retrieved)" in evalloop.build_generation_prompt("Q?", [])

    answerable = dict(ITEMS[0], accepted_aliases=[{"text": "DOE", "case_sensitive": True}])
    judge = evalloop.build_judge_prompt(answerable, "It is DOE.")
    assert "Reference answer: Department of Energy (also acceptable: DOE)" in judge
    assert judge.endswith("Candidate answer: It is DOE.")
    no_answer = evalloop.build_judge_prompt(ITEMS[4], "")
    assert "Reference answer: NO ANSWER." in no_answer and no_answer.endswith("Candidate answer: (empty)")
    for verdict in scoring.VERDICTS:
        assert verdict in evalloop.JUDGE_RUBRIC


def test_guardrail_inputs_respect_the_documented_length_limits():
    captured = {}

    class LongBackend(FakeBackend):
        def generate(self, system, user):
            return {"text": "The Department of Energy. " + "x" * 9000, "input_tokens": 1, "output_tokens": 1}

        def retrieve(self, question):
            self.current = "q-001"
            return [Passage(text="y" * 150_000, doc_id="uc-0001")]

        def apply_guardrail(self, sources, question, answer):
            captured.update(sources=len(sources), question=len(question), answer=len(answer))
            return {"action": "NONE", "units": 106}

    item = dict(ITEMS[0], question='Question 1 about "Use case 1"? ' + "z" * 3000)
    row = evalloop.evaluate_item(item, LongBackend(), LABEL_SETS)
    assert captured == {"sources": 100_000, "question": 1_000, "answer": 5_000}
    assert row["answer_truncated_for_guardrail"] is True and row["error"] is None


def test_csv_row_is_flat_and_single_line():
    row = evalloop.run(ITEMS[:1], FakeBackend({"q-001": dict(SCRIPT["q-001"], answer="Line one\nline two DOE")}),
                       LABEL_SETS)[0]
    flat = evalloop.csv_row(row)
    assert set(flat) == set(evalloop.CSV_COLUMNS)
    assert flat["retrieved_doc_ids"] == "uc-0001 uc-0009" and flat["answer"] == "Line one line two DOE"
