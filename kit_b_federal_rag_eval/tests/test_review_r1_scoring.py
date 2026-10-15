"""Round 1 review, scoring findings: tests written to fail on the code as reviewed.

BLOCKER 1  exact match read the field name "High-impact determination" as the value "High-impact".
BLOCKER 2  the judge parser read "not correct" as CORRECT.
MINOR 3    a refusal was detected by substring.
MINOR 4    the rubric for unanswerable questions invited the verdict CORRECT.
MINOR 7    a negation more than three words before a value was missed.

The answers below are templates: each one is filled in for every expected value
of its field, so a template passes only if it is scored the same way for all of them.
"""
from __future__ import annotations

import pytest

from kitlib import evalloop, scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, NO_ANSWER, STAGE_LABELS, TEMPLATES, simple_label_set

# The agencies whose abbreviations are also ordinary words or common short forms, plus a few plain ones.
AGENCIES = [
    ("Department of Energy", "DOE"), ("Department of Education", "ED"), ("Department of State", "STATE"),
    ("Department of Commerce", "DOC"), ("Department of Veterans Affairs", "VA"),
    ("Department of Transportation", "DOT"), ("Securities and Exchange Commission", "SEC"),
    ("National Aeronautics and Space Administration", "NASA"), ("Department of the Interior", "DOI"),
    ("Federal Energy Regulatory Commission", "FERC"), ("National Transportation Safety Board", "NTSB"),
]
LABEL_SETS = {
    "agency": [{"label": name, "aliases": [{"text": abbr, "case_sensitive": True}]} for name, abbr in AGENCIES],
    "stage": simple_label_set(STAGE_LABELS),
    "high_impact": simple_label_set(HIGH_IMPACT_LABELS),
}
NAME = "Grid load forecasting assistant"
REPORTER = "Department of Justice"       # the agency named in stage and high-impact questions


def make_item(kind: str, expected: str) -> dict:
    question = TEMPLATES[kind].format(name=NAME, agency_name=REPORTER)
    aliases = [{"text": dict(AGENCIES)[expected], "case_sensitive": True}] if kind == "agency" else []
    return {"id": "q-001", "type": kind, "answerable": True, "question": question, "use_case_name": NAME,
            "expected_answer": expected, "label_set": kind, "accepted_aliases": aliases, "source_doc_id": "uc-0001"}


def cases(kind: str):
    """(item, mapping of placeholders) for every expected value of a field."""
    values = [name for name, _ in AGENCIES] if kind == "agency" else [e["label"] for e in LABEL_SETS[kind]]
    out = []
    for position, value in enumerate(values):
        other = values[(position + 1) % len(values)]
        item = make_item(kind, value)
        out.append((item, {"v": value, "other": other, "name": NAME, "ag": REPORTER, "q": item["question"],
                           "abbr": dict(AGENCIES).get(value, ""), "decline": scoring.DECLINE_SENTENCE}))
    return out


def score_all(kind: str, template: str) -> list[dict]:
    return [scoring.score_exact(item, template.format(**fill), LABEL_SETS) for item, fill in cases(kind)]


# --- BLOCKER 1: sentences that state the expected value must be scored correct ------------------------

STATES_THE_VALUE = {
    "agency": [
        "{v}",
        # "{abbr}" alone was in this list until the round 2 review. Seven of these abbreviations are also
        # ordinary words or a state code and now count only next to the full name: see
        # test_review_r2_exact.py, test_an_abbreviation_that_is_a_word_or_a_state_code_counts_only_...
        'The {v} ({abbr}) reported the AI use case named "{name}".',
        'The AI use case named "{name}" was reported by the {v}.',
        "According to the passages, it was reported by the {v} ({abbr}).",
        "Agency: {v} ({abbr})",
        "{q} The {v}.",                                              # the question restated, then the answer
    ],
    "stage": [
        "{v}",
        'The stage of development recorded for the AI use case named "{name}", reported by the {ag}, is {v}.',
        'The stage of development is "{v}".',
        "Stage of development: {v}",
        "It is recorded as {v}.",
        "It is in the {v} stage.",
        "{q} {v}.",
    ],
    "high_impact": [
        "{v}",
        'The high-impact determination recorded for the AI use case named "{name}", reported by the {ag}, is {v}.',
        'The high-impact determination is "{v}".',                   # the reviewer's failing template
        "High-impact determination: {v}",                            # the document line itself
        "It is recorded as {v}.",
        'The determination recorded is "{v}".',
        "The high-impact determination for this use case is {v}.",
        "Its high-impact status is {v}.",
        "High-impact status: {v}",
        "{q} {v}.",
        "{q}\nThe high-impact determination is {v}.",
    ],
}


@pytest.mark.parametrize("kind,template", [(k, t) for k, ts in STATES_THE_VALUE.items() for t in ts])
def test_a_sentence_that_states_the_expected_value_is_scored_correct(kind, template):
    results = score_all(kind, template)
    wrong = [(fill["v"], r["note"]) for (_, fill), r in zip(cases(kind), results) if not r["exact"]]
    assert wrong == [], f"scored wrong although the value is stated: {wrong}"


# --- BLOCKER 1: sentences that do not state it must never be scored correct ------------------------------

DOES_NOT_STATE_THE_VALUE = {
    "agency": [
        "The passages do not say which agency reported it.",
        "It was reported by the Bureau of Made Up Things.",
        'The use case named "{name}" is not reported by any agency in the passages.',
        "{q}",                                                        # the question restated and nothing else
        "The agency is not recorded in the passages.",
        "It was not reported by the {v}.",                            # negated
        "It was not reported by {abbr}.",                             # negated abbreviation
        "The reporting agency isn't the {v}.",
        "It was probably reported by the {v}.",                       # hedged
        "It may be the {v}.",
        "I think it was {abbr}.",
        "Either the {v} or the {other}.",                             # two values
        "{v} and {other}",
        "The {other}.",                                               # another value
        "{decline}",                                                  # a refusal
        "{v}. {decline}",                                             # a value and a refusal together
        # Round 2 review: stated, but with a negation next to it. Unclear, so not credited (lost credit).
        "It was reported by the {v}, not by any other agency.",
    ],
    "stage": [
        "The stage of development is not reported.",
        "The stage of development recorded is Not reported.",
        "The passages do not state the stage of development.",
        "{q}",
        "It is not {v}.",
        "It hasn't been fully {v}.",                                  # the reviewer's example
        "It is not currently in the {v} stage.",                      # the reviewer's example
        "It has never, as far as the passage shows, reached anything but an unknown stage.",
        "The {v} stage is not confirmed by the passages.",            # negation after the value
        "It is probably {v}.",
        "It might be {v}.",
        "It is likely {v}.",
        "It appears to be {v}, but I am unsure.",
        "It is {v} or {other}.",
        "{v}, formerly {other}.",
        "It is {other}.",
        "{decline}",
        "{v}. {decline}",
    ],
    "high_impact": [
        "The high-impact determination is not recorded in the passages.",      # the reviewer's failing template
        'The high-impact determination recorded is "Not reported".',
        "The passages do not state a high-impact determination.",
        "The high-impact determination for this use case is unknown.",
        "{q}",
        "High-impact determination: Not reported",
        "The high-impact status is unknown.",
        "The high-impact status is missing from the record.",
        "No high-impact determination is recorded.",
        "I could not find a high-impact determination.",
        "The record is silent on the high-impact determination.",
        "There is a high-impact determination field, and it is blank.",
        "The high-impact flag has no value here.",
        "It is not classified as {v}.",
        "It is probably {v}.",
        "It may be {v}.",
        "{v} or {other}",
        "Either {v} or {other}.",
        "It is {other}.",
        "{decline}",
        "{v}. {decline}",
    ],
}


@pytest.mark.parametrize("kind,template", [(k, t) for k, ts in DOES_NOT_STATE_THE_VALUE.items() for t in ts])
def test_a_sentence_that_does_not_state_the_expected_value_is_never_scored_correct(kind, template):
    results = score_all(kind, template)
    credited = [fill["v"] for (_, fill), r in zip(cases(kind), results) if r["exact"]]
    assert credited == [], f"scored correct although the value is not stated: {credited}"


def test_the_field_name_itself_is_not_a_value():
    item = make_item("high_impact", "High-impact")
    for echo in ("The high-impact determination", "high-impact determination:", "High-impact determinations",
                 "the high impact determination field", "What high-impact determination is recorded?"):
        result = scoring.score_exact(item, echo, LABEL_SETS)
        assert (result["exact"], result["asserted"]) == (False, []), echo
    stated = scoring.score_exact(item, "High-impact determination: High-impact", LABEL_SETS)
    assert stated["exact"] and stated["asserted"] == ["High-impact"]


def test_notes_say_why_an_answer_was_not_credited():
    def note(kind, expected, answer):
        return scoring.score_exact(make_item(kind, expected), answer, LABEL_SETS)["note"]

    # The notes changed with the round 2 review: every answer the allow-list cannot read is "unclear_...".
    assert note("stage", "Deployed", "It hasn't been fully deployed.") == "unclear_words_outside_the_filler_list"
    assert note("stage", "Pilot", "It is not currently in the Pilot stage.") == "unclear_words_outside_the_filler_list"
    assert note("stage", "Pilot", "It is probably Pilot.") == "unclear_words_outside_the_filler_list"
    assert note("stage", "Pilot", "Pilot or Deployed") == "unclear_more_than_one_value"
    assert note("stage", "Pilot", "It is Deployed.") == "different_value"
    assert note("stage", "Pilot", "The passages do not say.") == "unclear_no_value_found"
    assert note("stage", "Pilot", "Pilot. " + scoring.DECLINE_SENTENCE) == "unclear_mixed_with_the_refusal_sentence"
    assert note("agency", "Department of Energy", "It was not reported by DOE.") == "unclear_no_value_found"
    assert note("agency", "Department of the Interior", "It was not reported by DOI.") == \
        "unclear_words_outside_the_filler_list"


def test_a_negation_anywhere_makes_the_answer_unclear_even_when_it_negates_another_value():
    """Until the round 2 review these five answers were credited: the negation sat in another clause.

    The same reading credited "It is not, as far as I can tell, Deployed". An allow-list cannot tell
    the two apart, so both are unclear now. That is lost credit, stated in README section 2, item 8.
    """
    def exact(kind, expected, answer):
        return scoring.score_exact(make_item(kind, expected), answer, LABEL_SETS)

    for kind, expected, answer in (
            ("stage", "Pilot", "It is not deployed; it is in the Pilot stage."),
            ("stage", "Pilot", "It is not Deployed, it is Pilot."),
            ("stage", "Deployed", "The stage is Deployed, not Pilot."),
            ("stage", "Deployed", "It is not Pilot but Deployed."),
            ("agency", "Department of Energy",
             "The Department of Energy, not the Department of Education, reported it.")):
        result = exact(kind, expected, answer)
        assert (result["exact"], result["unclear"]) == (False, True), answer
    assert exact("high_impact", "Not High-impact", "The use case is not High-impact.")["exact"]   # that IS the value


# --- MINOR 3: a refusal is the fixed sentence and nothing else ------------------------------------------------

def unanswerable():
    return {"id": "q-101", "type": "unanswerable_heldout", "answerable": False, "question": "Q?",
            "use_case_name": NAME, "expected_answer": NO_ANSWER, "label_set": None, "accepted_aliases": [],
            "source_doc_id": None}


@pytest.mark.parametrize("answer", [
    scoring.DECLINE_SENTENCE,
    "I cannot answer this from the inventory documents provided",
    "  I cannot answer this from the inventory documents provided.  ",
])
def test_the_fixed_sentence_alone_is_a_refusal(answer):
    assert scoring.is_decline(answer)
    assert scoring.score_exact(unanswerable(), answer, LABEL_SETS) == {
        "exact": True, "declined": True, "unclear": False, "note": "declined_as_it_should", "asserted": [],
        "found": [], "unread": ""}


@pytest.mark.parametrize("answer", [
    "The agency is the Department of Energy. I cannot answer this from the inventory documents provided "
    "with certainty.",                                                                   # the reviewer's example
    "Department of Energy (I cannot answer this from the inventory alone, but that is my best guess).",
    "Sorry. I cannot answer this from the inventory documents provided.",
    "I cannot answer this from the inventory documents provided. It is probably the Department of Energy.",
    "I cannot answer this from the documents provided.",
    "The passages do not contain the answer.",
    "",
    "   ",
    # Round 2 review: the check is equality, so another case or quotation marks are "something else" too.
    "i cannot answer this from the inventory documents provided",
    '"I cannot answer this from the inventory documents provided."',
])
def test_anything_else_is_not_a_refusal_in_the_exact_column(answer):
    assert not scoring.is_decline(answer)
    result = scoring.score_exact(unanswerable(), answer, LABEL_SETS)
    assert (result["exact"], result["declined"]) == (False, False)


def test_a_refusal_with_an_answer_attached_is_flagged_as_such():
    note = scoring.score_exact(unanswerable(), "The Department of Energy. " + scoring.DECLINE_SENTENCE,
                               LABEL_SETS)["note"]
    assert note == "decline_sentence_with_other_text"


# --- BLOCKER 2: the judge parser. Anything unclear is UNPARSEABLE, never CORRECT -------------------------

RUBRIC_LINE_AS_REVIEWED = '{"verdict": "CORRECT" | "INCORRECT" | "DECLINED", "reason": "<at most 20 words>"}'

CLEAR = [
    ('{"verdict": "CORRECT", "reason": "same agency"}', "CORRECT"),
    ('{"verdict": "INCORRECT", "reason": "different agency"}', "INCORRECT"),
    ('{"verdict": "DECLINED", "reason": "says it cannot answer"}', "DECLINED"),
    ('{"verdict": "incorrect", "reason": "x"}', "INCORRECT"),
    ('{"verdict": " Correct "}', "CORRECT"),
    ('```json\n{"verdict": "INCORRECT", "reason": "x"}\n```', "INCORRECT"),
    ('Here is my grade:\n```json\n{"verdict": "DECLINED", "reason": "no answer given"}\n```', "DECLINED"),
    ('{"verdict": "INCORRECT", "reason": "the answer is not CORRECT"}', "INCORRECT"),
    ('{"verdict": "INCORRECT", "reason": "the correct answer is Deployed"}', "INCORRECT"),
    ('{"reason": "The candidate gives {Deployed} which matches", "verdict": "CORRECT"}', "CORRECT"),
    ('{"verdict":"INCORRECT","reason":"Candidate says \\"} CORRECT\\""}', "INCORRECT"),
    ('{"verdict": "CORRECT"}\n{"verdict": "CORRECT"}', "CORRECT"),             # said twice, the same
    ("CORRECT", "CORRECT"), ("INCORRECT", "INCORRECT"), ("DECLINED", "DECLINED"),
    ("  declined.\n", "DECLINED"), ('"Correct"', "CORRECT"), ("**INCORRECT**", "INCORRECT"),
    ("Verdict: CORRECT", "CORRECT"), ("verdict: incorrect.", "INCORRECT"),
    # cut off after a complete verdict field (the reply hit the token limit inside the reason)
    ('{"verdict": "INCORRECT", "reason": "the correct answer is Deployed', "INCORRECT"),
    ('{"verdict": "CORRECT", "reason": "the candidate states the refer', "CORRECT"),
    ('```json\n{"verdict": "DECLINED", "reason": "the candidate says it cannot ans', "DECLINED"),
    ('{"verdict": "CORRECT"', "CORRECT"),
    # Round 2 review, M2: a trailing period in the verdict value is read (it was unparseable).
    ('{"verdict": "CORRECT."}', "CORRECT"),
]

UNCLEAR = [
    # negated or qualified verdict words
    "The candidate answer is not correct.", "NOT CORRECT", "not CORRECT", "Not correct.", "Verdict: not correct",
    "This is not a correct answer.", "Not incorrect.", "PARTIALLY CORRECT", "Mostly correct.",
    "The answer is correct.", "That is incorrect.", "The answer is incorrect, the correct answer is X",
    "The reference is NO ANSWER; the candidate did not decline, so this is not DECLINED.",
    "I cannot grade this.", "I'm sorry, but I can't help with that. It would be incorrect for me to do so.",
    # a JSON verdict that is not one of the three words
    '{"verdict": "NOT CORRECT", "reason": "different agency"}', '{"verdict": "PARTIALLY CORRECT", "reason": "x"}',
    '{"verdict":"Not Correct"}', '{"verdict": "MAYBE"}', '{"verdict": ""}',
    # Round 2 review, B5: DECLINED with a reason is read only if the reason says the candidate declined.
    # Cut off at "cann", this one does not say so yet.
    '```json\n{"verdict": "DECLINED", "reason": "the candidate says it cann',
    '{"verdict": ["CORRECT"]}', '{"verdict": null}', '{"verdict": true}', '{"verdict": {"value": "CORRECT"}}',
    '{"verdict": "WRONG"} not correct', '{"verdict": "UNSURE"} it could be correct',
    '{"grade": "CORRECT"}',
    # the rubric echoed back
    RUBRIC_LINE_AS_REVIEWED,
    "Reply with exactly: " + RUBRIC_LINE_AS_REVIEWED,
    evalloop.JUDGE_RUBRIC,
    "- CORRECT: the candidate states the reference answer.\n- DECLINED: the candidate says it cannot answer.\n"
    "- INCORRECT: anything else.",
    evalloop.JUDGE_RUBRIC + '\n{"verdict": "CORRECT", "reason": "x"}',
    # cut off before the verdict is complete
    '{"verdict": ', '{"verdict": "COR', '{"verdict": "CORRECT', '{"verdict": "CORRECT" |', '{"reason": "the candidate is correct',
    '{"reason": "it says \\"verdict\\": \\"CORRECT\\" but', '{',
    # two verdicts
    '{"verdict": "DECLINED", "reason": "says it cannot answer"} {"verdict": "CORRECT"}',
    '{"verdict": "CORRECT", "verdict": "INCORRECT"}',
    '{"verdict": "INCORRECT", "verdict": "CORRECT"}',
    '{"verdict": "CORRECT"} Actually, on reflection it is incorrect.',
    'It is correct. {"verdict": "INCORRECT"}',
    "CORRECT or INCORRECT, hard to say", "CORRECT INCORRECT", "CORRECT\nINCORRECT",
    '{"verdict": "CORRECT", "reason": "x"} and then {"verdict": "INCORR',
    # nothing
    "", "   ", "\n", None, "{}", "[]", "null", "N/A",
]


@pytest.mark.parametrize("text,verdict", CLEAR)
def test_a_clear_judge_reply_is_read(text, verdict):
    assert scoring.parse_judge(text) == verdict


@pytest.mark.parametrize("text", UNCLEAR)
def test_an_unclear_judge_reply_is_unparseable_and_never_correct(text):
    assert scoring.parse_judge(text) == scoring.UNPARSEABLE


def test_every_verdict_word_outside_one_clean_reply_makes_it_unparseable():
    """No free-text reply that merely contains a verdict word is ever read as that verdict."""
    for word in ("correct", "CORRECT", "Correct"):
        for wrapper in ("not {}", "{} ?", "in{}", "{}ly", "is it {}", "{} - no", "un{}", "{} / INCORRECT",
                        "the {} answer is Deployed", "{} me if I am wrong", "I would not say {}"):
            assert scoring.parse_judge(wrapper.format(word)) in (scoring.UNPARSEABLE, "INCORRECT"), wrapper
            assert scoring.parse_judge(wrapper.format(word)) != "CORRECT", wrapper


# --- MINOR 4: the rubric for unanswerable questions, and what an odd verdict there is counted as ---------------

def test_the_rubric_never_tells_the_judge_that_declining_is_the_correct_behaviour():
    prompt = evalloop.build_judge_prompt(unanswerable(), scoring.DECLINE_SENTENCE)
    assert "only correct behaviour" not in prompt
    assert "Reference answer: NO ANSWER." in prompt
    reference = prompt.split("Reference answer:")[1].split("Candidate answer:")[0]
    assert "DECLINED" in reference and "INCORRECT" in reference
    assert "never CORRECT" in evalloop.JUDGE_RUBRIC
    # the reply format is no longer written in a way that parses as a verdict when echoed
    assert '"verdict": "CORRECT"' not in evalloop.JUDGE_RUBRIC
    assert scoring.parse_judge(prompt) == scoring.UNPARSEABLE


def judged_row(answerable: bool, verdict: str, blocked: bool = False, declined: bool = False) -> dict:
    row = {"id": "q", "type": "agency" if answerable else "unanswerable_heldout", "answerable": answerable,
           "exact": False, "declined": declined, "blocked": blocked, "judge_verdict": verdict,
           "hit": True if answerable else None, "hit_rank": 1 if answerable else None,
           "retrieved_doc_ids": ["uc-0001"], "error": None}
    row["judged_correct"] = scoring.judged_correct({"answerable": answerable}, verdict)
    row.update(scoring.with_guardrail(row))
    return row


def test_only_an_incorrect_verdict_counts_as_answered_anyway():
    rows = [judged_row(False, "DECLINED"), judged_row(False, "INCORRECT"), judged_row(False, "INCORRECT"),
            judged_row(False, "CORRECT"), judged_row(False, scoring.UNPARSEABLE)]
    summary = scoring.summarise(rows, top_k=5)
    off = summary["guardrail_off"]
    assert off["unanswerable_judged_declined"]["count"] == 1
    assert off["unanswerable_answered_anyway"]["count"] == 2        # not 4: CORRECT and UNPARSEABLE are unclear
    assert off["unanswerable_judge_unclear"]["count"] == 2
    assert summary["judge_unparseable"] == 1 and summary["judge_correct_on_unanswerable"] == 1
    text = scoring.render_summary_markdown(summary)
    assert "| Unanswerable: answered anyway (judged INCORRECT) | 2/5" in text
    assert "| Unanswerable: judge verdict unclear (CORRECT or unparseable) | 2/5" in text


def test_a_blocked_unclear_answer_gets_its_own_block_bucket():
    rows = [judged_row(False, "CORRECT", blocked=True), judged_row(False, scoring.UNPARSEABLE, blocked=True),
            judged_row(False, "INCORRECT", blocked=True), judged_row(False, "DECLINED", blocked=True)]
    blocks = scoring.summarise(rows, top_k=5)["guardrail_blocks"]
    assert blocks["on_unanswerable_judge_unclear"] == 2
    assert blocks["on_unanswerable_answered_anyway"] == 1 and blocks["on_unanswerable_soft_refusals"] == 1
    assert sum(value for key, value in blocks.items() if key != "total") == blocks["total"] == 4
