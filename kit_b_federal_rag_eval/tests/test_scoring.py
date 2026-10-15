"""Scoring logic. These functions produce the numbers that get quoted, so the edge cases are spelled out."""
from __future__ import annotations

import math

import pytest

from kitlib import scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, NO_ANSWER, STAGE_LABELS, simple_label_set

AGENCY_SET = [
    {"label": "Department of Energy", "aliases": [{"text": "DOE", "case_sensitive": True}]},
    {"label": "Department of Education", "aliases": [{"text": "ED", "case_sensitive": True}]},
    {"label": "Department of State", "aliases": [{"text": "STATE", "case_sensitive": True}]},
    {"label": "National Aeronautics and Space Administration", "aliases": [{"text": "NASA", "case_sensitive": True}]},
]
LABEL_SETS = {"agency": AGENCY_SET, "stage": simple_label_set(STAGE_LABELS),
              "high_impact": simple_label_set(HIGH_IMPACT_LABELS)}


def item(kind="agency", expected="Department of Energy", answerable=True, name="Grid load forecaster"):
    return {"id": "q-001", "type": kind, "answerable": answerable, "question": f'About "{name}"?',
            "use_case_name": name, "expected_answer": expected if answerable else NO_ANSWER,
            "label_set": kind if answerable else None, "accepted_aliases": [], "source_doc_id": "uc-0001"}


def exact(kind, expected, answer, **kw):
    return scoring.score_exact(item(kind, expected, **kw), answer, LABEL_SETS)


# --- normalisation ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Pre-deployment", "pre deployment"),
    ("Pre\u2011deployment", "pre deployment"),          # non-breaking hyphen
    ("Pre \u2013 deployment", "pre deployment"),        # en dash
    ("  HIGH-Impact. ", "high impact"),
    ("Presumed High-Impact, but Not High-impact", "presumed high impact but not high impact"),
    ("\uff24\uff2f\uff25", "doe"),                      # full-width letters fold under NFKC
    (None, ""),
])
def test_normalise(raw, expected):
    assert scoring.normalise(raw) == expected


# --- decline detection --------------------------------------------------------

def test_decline_is_detected_only_for_the_fixed_sentence():
    assert scoring.is_decline(scoring.DECLINE_SENTENCE)
    assert scoring.is_decline("  " + scoring.DECLINE_SENTENCE[:-1] + "\n")       # the final period is optional
    # Round 2 review: nothing is folded or stripped any more, not even the case of the first letter.
    assert not scoring.is_decline("i cannot answer this from the inventory documents provided")
    # Round 1 review, MINOR 3: the sentence with anything added is no longer a refusal.
    assert not scoring.is_decline("Sorry. I cannot answer this from the inventory documents provided.")
    assert scoring.mentions_decline("Sorry. I cannot answer this from the inventory documents provided.")
    assert not scoring.is_decline("I don't know.")
    assert not scoring.is_decline("The Department of Energy.")
    assert not scoring.is_decline("")


# --- closed-set exact match: agency ----------------------------------------------

def test_agency_full_name_matches():
    result = exact("agency", "Department of Energy", "It was reported by the Department of Energy.")
    assert result == {"exact": True, "declined": False, "unclear": False, "note": "match",
                      "asserted": ["Department of Energy"], "found": ["Department of Energy"], "unread": ""}


def test_agency_abbreviation_matches_only_as_an_upper_case_whole_word():
    nasa = "National Aeronautics and Space Administration"
    assert exact("agency", nasa, "NASA reported it.")["exact"]
    assert not exact("agency", nasa, "Nasa reported it.")["exact"]
    # Round 2 review: "DOE", "ED" and "STATE" are also ordinary words, so they count only next to the full name.
    assert not exact("agency", "Department of Energy", "DOE reported it.")["exact"]
    assert exact("agency", "Department of Energy", "The Department of Energy (DOE).")["exact"]
    assert not exact("agency", "Department of Energy", "The doe ran across the field.")["exact"]
    assert not exact("agency", "Department of Education", "It was reported.")["exact"]      # 'ed' in 'reported'
    assert not exact("agency", "Department of State", "The state of the project is unknown.")["exact"]


def test_agency_wrong_or_two_agencies_is_not_a_match():
    wrong = exact("agency", "Department of Energy", "The Department of Education reported it.")
    assert (wrong["exact"], wrong["note"]) == (False, "different_value")
    two = exact("agency", "Department of Energy", "Either the Department of Energy or NASA.")
    assert (two["exact"], two["unclear"], two["note"]) == (False, True, "unclear_more_than_one_value")
    assert two["found"] == ["Department of Energy", "National Aeronautics and Space Administration"]
    assert two["asserted"] == []


def test_agency_named_inside_the_use_case_name_is_ignored():
    result = exact("agency", "Department of Energy",
                   'The use case "NASA and partners data hub" was reported by the Department of Energy.',
                   name="NASA and partners data hub")
    assert result["exact"] and result["asserted"] == ["Department of Energy"]


def test_empty_answer_and_no_value_are_not_matches():
    assert exact("agency", "Department of Energy", "")["note"] == "empty_answer"
    assert exact("agency", "Department of Energy", "A federal agency reported it.")["note"] == "unclear_no_value_found"


# --- closed-set exact match: stage ---------------------------------------------------

@pytest.mark.parametrize("answer", [
    "Pre-deployment", "The stage of development is Pre-deployment.", "pre deployment",
    "It is recorded as PRE-DEPLOYMENT.", "Stage: Pre\u2013deployment"])
def test_stage_matches_in_several_spellings(answer):
    assert exact("stage", "Pre-deployment", answer)["exact"]


def test_stage_other_value_or_two_values_is_not_a_match():
    assert exact("stage", "Pilot", "It is Deployed.")["note"] == "different_value"
    both = exact("stage", "Pilot", "It is a Pilot that has been deployed in a limited capacity.")
    assert (both["exact"], both["note"]) == (False, "unclear_more_than_one_value")


def test_stage_value_after_a_negation_is_not_counted_as_stated():
    result = exact("stage", "Deployed", "It has not been deployed.")
    assert (result["exact"], result["note"], result["asserted"]) == (
        False, "unclear_words_outside_the_filler_list", [])
    assert result["unread"] == "has not been"
    # Round 2 review: a second value is unclear even when it is the one that is negated. This used to
    # be credited; the cost of not crediting "It is not, as far as I can tell, Deployed" is this answer.
    mixed = exact("stage", "Pilot", "It is not deployed; it is in the Pilot stage.")
    assert (mixed["exact"], mixed["note"], mixed["asserted"]) == (False, "unclear_more_than_one_value", [])
    assert not exact("stage", "Deployed", "It was never fully deployed.")["exact"]


# --- closed-set exact match: high-impact (the labels contain each other) ------------------

def test_high_impact_labels_do_not_bleed_into_each_other():
    assert exact("high_impact", "High-impact", "The determination is High-impact.")["exact"]
    assert exact("high_impact", "Not High-impact", "The determination is Not High-impact.")["exact"]
    assert exact("high_impact", "Presumed High-Impact, but Not High-impact",
                 "It is recorded as Presumed High-Impact, but Not High-impact.")["exact"]

    not_hi = exact("high_impact", "High-impact", "The determination is Not High-impact.")
    assert (not_hi["exact"], not_hi["asserted"]) == (False, ["Not High-impact"])
    hi = exact("high_impact", "Not High-impact", "The determination is High-impact.")
    assert (hi["exact"], hi["asserted"]) == (False, ["High-impact"])
    presumed = exact("high_impact", "Not High-impact", "Presumed High-Impact, but Not High-impact.")
    assert (presumed["exact"], presumed["asserted"]) == (False, ["Presumed High-Impact, but Not High-impact"])
    plain = exact("high_impact", "Presumed High-Impact, but Not High-impact", "Not High-impact.")
    assert not plain["exact"]


def test_high_impact_paraphrased_negation_never_counts_as_high_impact():
    # "not classified as high-impact" must not be scored as the value "High-impact".
    result = exact("high_impact", "High-impact", "It is not classified as high-impact.")
    assert (result["exact"], result["note"]) == (False, "unclear_words_outside_the_filler_list")
    # It is the cautious direction: the same sentence is also not credited as "Not High-impact".
    other = exact("high_impact", "Not High-impact", "It is not classified as high-impact.")
    assert other["exact"] is False


def test_high_impact_without_hyphen_matches():
    assert exact("high_impact", "Not High-impact", "not high impact")["exact"]


# --- answerable vs unanswerable ---------------------------------------------------------

def test_declining_an_answerable_question_is_wrong_and_flagged():
    result = exact("stage", "Pilot", scoring.DECLINE_SENTENCE)
    assert result == {"exact": False, "declined": True, "unclear": False, "note": "declined_an_answerable_question",
                      "asserted": [], "found": [], "unread": ""}


def test_unanswerable_question_is_right_only_when_declined():
    declined = scoring.score_exact(item(answerable=False), scoring.DECLINE_SENTENCE, LABEL_SETS)
    assert declined["exact"] and declined["declined"]
    invented = scoring.score_exact(item(answerable=False), "The Department of Energy.", LABEL_SETS)
    assert not invented["exact"] and invented["note"] == "answered_an_unanswerable_question"
    soft = scoring.score_exact(item(answerable=False), "I do not know.", LABEL_SETS)
    assert not soft["exact"]   # only the fixed sentence counts for the exact column


# --- retrieval hit ------------------------------------------------------------------------

def test_retrieval_hit_and_rank():
    assert scoring.retrieval_hit("uc-0003", ["uc-0001", "uc-0003", "uc-0003"]) == {"hit": True, "rank": 2}
    assert scoring.retrieval_hit("uc-0003", ["uc-0003"]) == {"hit": True, "rank": 1}
    assert scoring.retrieval_hit("uc-0003", ["uc-0001", None]) == {"hit": False, "rank": None}
    assert scoring.retrieval_hit("uc-0003", []) == {"hit": False, "rank": None}
    assert scoring.retrieval_hit(None, ["uc-0001"]) == {"hit": None, "rank": None}


# --- judge parsing ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,verdict", [
    ('{"verdict": "CORRECT", "reason": "same agency"}', "CORRECT"),
    ('{"verdict": "incorrect", "reason": "x"}', "INCORRECT"),
    ('Here is my grade:\n```json\n{"verdict": "DECLINED", "reason": "no answer given"}\n```', "DECLINED"),
    ('{"verdict": "INCORRECT", "reason": "the answer is not CORRECT"}', "INCORRECT"),
    ("DECLINED", "DECLINED"),
    # Round 1 review, BLOCKER 2: this used to be pinned as CORRECT. A sentence is not a verdict.
    ("The answer is correct.", "UNPARSEABLE"),
    ("CORRECT or INCORRECT, hard to say", "UNPARSEABLE"),
    ('{"verdict": "MAYBE"}', "UNPARSEABLE"),
    ('{"verdict": ', "UNPARSEABLE"),
    ("", "UNPARSEABLE"),
    (None, "UNPARSEABLE"),
])
def test_parse_judge(text, verdict):
    assert scoring.parse_judge(text) == verdict


def test_incorrect_is_not_read_as_correct():
    assert scoring.parse_judge("INCORRECT") == "INCORRECT"
    # Round 1 review, BLOCKER 2: free text is no longer searched for a verdict word.
    assert scoring.parse_judge("That is incorrect.") == "UNPARSEABLE"
    assert scoring.parse_judge("That is not correct.") == "UNPARSEABLE"


def test_judged_correct_depends_on_answerability():
    answerable, unanswerable = item(), item(answerable=False)
    assert scoring.judged_correct(answerable, "CORRECT")
    assert not scoring.judged_correct(answerable, "DECLINED")
    assert not scoring.judged_correct(answerable, "UNPARSEABLE")
    assert scoring.judged_correct(unanswerable, "DECLINED")
    assert not scoring.judged_correct(unanswerable, "CORRECT")
    assert not scoring.judged_correct(unanswerable, "INCORRECT")
    assert not scoring.judged_correct(unanswerable, "UNPARSEABLE")


# --- guardrail-on outcome -----------------------------------------------------------------------

def row(answerable=True, exact=False, judged=False, declined=False, blocked=False, kind="agency",
        hit=True, rank=1, error=None, verdict=None, units=6):
    base = {"id": "q", "type": kind if answerable else "unanswerable_heldout", "answerable": answerable,
            "exact": exact, "judged_correct": judged, "declined": declined, "blocked": blocked,
            "hit": hit if answerable else None, "hit_rank": rank if (answerable and hit) else None,
            "judge_verdict": verdict or ("CORRECT" if judged and answerable else
                                         "DECLINED" if judged else "INCORRECT"),
            "guardrail_action": "GUARDRAIL_INTERVENED" if blocked else "NONE", "guardrail_units": units,
            "retrieved_doc_ids": ["uc-0001"], "gen_input_tokens": 1000, "gen_output_tokens": 20,
            "judge_input_tokens": 300, "judge_output_tokens": 30, "error": error}
    base.update(scoring.with_guardrail(base))
    return base


def test_block_turns_a_correct_answer_into_a_wrong_one():
    assert scoring.with_guardrail({"answerable": True, "exact": True, "judged_correct": True,
                                   "declined": False, "blocked": True}) == {
        "exact_on": False, "judged_correct_on": False, "declined_on": True}


def test_block_turns_an_invented_answer_to_an_unanswerable_question_into_a_refusal():
    assert scoring.with_guardrail({"answerable": False, "exact": False, "judged_correct": False,
                                   "declined": False, "blocked": True}) == {
        "exact_on": True, "judged_correct_on": True, "declined_on": True}


def test_no_block_changes_nothing():
    for answerable in (True, False):
        for flag in (True, False):
            base = {"answerable": answerable, "exact": flag, "judged_correct": flag,
                    "declined": False, "blocked": False}
            assert scoring.with_guardrail(base) == {"exact_on": flag, "judged_correct_on": flag,
                                                    "declined_on": False}


@pytest.mark.parametrize("kwargs,category", [
    (dict(declined=True), "on_refusal_sentences"),
    (dict(answerable=False, declined=True, judged=True), "on_refusal_sentences"),
    (dict(judged=True, exact=True), "on_answerable_judged_correct"),
    (dict(judged=False), "on_answerable_judged_incorrect"),
    (dict(answerable=False, judged=False), "on_unanswerable_answered_anyway"),
    (dict(answerable=False, judged=True), "on_unanswerable_soft_refusals"),
])
def test_block_categories_are_exclusive(kwargs, category):
    assert scoring.block_category(row(blocked=True, **kwargs)) == category


# --- Wilson interval -----------------------------------------------------------------------------

def test_wilson_interval_known_values():
    low, high = scoring.wilson_interval(50, 100)
    assert math.isclose(low, 0.4038, abs_tol=5e-4) and math.isclose(high, 0.5962, abs_tol=5e-4)
    low, high = scoring.wilson_interval(0, 20)
    assert low == 0.0 and math.isclose(high, 0.1611, abs_tol=5e-4)
    low, high = scoring.wilson_interval(20, 20)
    assert math.isclose(low, 0.8389, abs_tol=5e-4) and math.isclose(high, 1.0, abs_tol=1e-9)
    assert scoring.wilson_interval(0, 0) is None


def test_rate_with_zero_denominator_is_none_not_zero():
    assert scoring.rate(0, 0) == {"count": 0, "n": 0, "rate": None, "ci95_low": None, "ci95_high": None}
    assert scoring.rate(3, 4)["rate"] == 0.75


# --- aggregation: a hand-counted example ------------------------------------------------------------

def hand_counted_rows():
    return [
        # 6 answerable
        row(exact=True, judged=True, rank=1),                                   # right, not blocked
        row(exact=True, judged=True, rank=3),                                   # right, not blocked
        row(exact=True, judged=True, rank=1, blocked=True),                     # right, but blocked
        row(exact=False, judged=True, rank=2, kind="stage"),                    # judge says right, exact says no
        row(exact=False, judged=False, hit=False, kind="stage", blocked=True),  # wrong, blocked
        row(exact=False, judged=False, declined=True, hit=False, kind="stage", verdict="DECLINED"),  # refused
        # 4 unanswerable
        row(answerable=False, exact=True, judged=True, declined=True),          # refused as it should
        row(answerable=False, exact=True, judged=True, declined=True, blocked=True),  # refusal sentence blocked
        row(answerable=False),                                                  # invented, not blocked
        row(answerable=False, blocked=True),                                    # invented, blocked
    ]


def test_summarise_matches_a_hand_count():
    s = scoring.summarise(hand_counted_rows(), top_k=5)
    assert (s["questions_total"], s["questions_scored"], s["questions_with_errors"], s["complete"]) == (10, 10, 0, True)
    assert (s["answerable_n"], s["unanswerable_n"]) == (6, 4)
    assert (s["retrieval"]["hit_at_k"]["count"], s["retrieval"]["hit_at_k"]["n"]) == (4, 6)
    assert s["retrieval"]["hit_at_1"]["count"] == 2

    off, on = s["guardrail_off"], s["guardrail_on"]
    assert off["answerable_exact_correct"]["count"] == 3 and on["answerable_exact_correct"]["count"] == 2
    assert off["answerable_judged_correct"]["count"] == 4 and on["answerable_judged_correct"]["count"] == 3
    assert off["answerable_refused"]["count"] == 1 and on["answerable_refused"]["count"] == 3
    assert off["unanswerable_refused"]["count"] == 2 and on["unanswerable_refused"]["count"] == 3
    assert off["unanswerable_answered_anyway"]["count"] == 2 and on["unanswerable_answered_anyway"]["count"] == 1
    assert math.isclose(off["answerable_judged_correct"]["rate"], 4 / 6)

    blocks = s["guardrail_blocks"]
    assert blocks == {"total": 4, "on_refusal_sentences": 1, "on_answerable_judged_correct": 1,
                      "on_answerable_judged_incorrect": 1, "on_unanswerable_answered_anyway": 1,
                      "on_unanswerable_soft_refusals": 0, "on_unanswerable_judge_unclear": 0}
    assert sum(v for k, v in blocks.items() if k != "total") == blocks["total"]

    # exact and judge agree on 5 of the 6 answerable rows
    assert (s["exact_vs_judge_agreement"]["count"], s["exact_vs_judge_agreement"]["n"]) == (5, 6)

    assert s["by_type"]["agency"]["n"] == 3 and s["by_type"]["stage"]["n"] == 3
    assert s["by_type"]["agency"]["exact_off"]["count"] == 3 and s["by_type"]["agency"]["exact_on"]["count"] == 2
    assert s["by_type"]["stage"]["hit_at_k"]["count"] == 1
    assert s["by_type"]["unanswerable_heldout"]["hit_at_k"] is None

    usage = s["usage"]
    assert usage == {"retrieve_calls": 10, "gen_input_tokens": 10000, "gen_output_tokens": 200,
                     "judge_input_tokens": 3000, "judge_output_tokens": 300,
                     "guardrail_text_units": 60, "guardrail_calls": 10, "earlier_failed_attempts_included": 0,
                     "interrupted_attempts_included": 0}


def test_rows_with_errors_are_left_out_and_the_run_is_marked_incomplete():
    rows = hand_counted_rows() + [row(error="ThrottlingException: slow down")]
    s = scoring.summarise(rows, top_k=5)
    assert (s["questions_total"], s["questions_scored"], s["questions_with_errors"]) == (11, 10, 1)
    assert s["complete"] is False and s["answerable_n"] == 6
    text = scoring.render_summary_markdown(s)
    assert text.startswith("**INCOMPLETE RUN: 1 question(s) hit an error")


def test_unparseable_judge_replies_are_counted_and_never_correct():
    rows = [row(exact=True, judged=False, verdict="UNPARSEABLE")]
    s = scoring.summarise(rows, top_k=5)
    assert s["judge_unparseable"] == 1
    assert s["guardrail_off"]["answerable_judged_correct"]["count"] == 0


def test_summary_table_shows_both_columns_and_the_counts():
    text = scoring.render_summary_markdown(scoring.summarise(hand_counted_rows(), top_k=5),
                                           {"Region": "us-east-1"})
    assert "- Region: us-east-1" in text
    assert "| Measure | Guardrail off | Guardrail on |" in text
    assert "| Retrieval hit rate, source document in top 5 | 4/6 (66.7%, 95% CI 30 to 90) | same retrieval |" in text
    assert "| Answerable: correct by exact match | 3/6 (50.0%, 95% CI 19 to 81) | 2/6 (33.3%, 95% CI 10 to 70) |" in text
    assert "| Guardrail blocks (grounding or relevance filter), total | not applied | 4 |" in text
    # Round 2 review: the unanswerable types have a table of their own, whose columns count refusals.
    assert "| unanswerable_heldout | 4 | 2/4 (50.0%, 95% CI 15 to 85) |" in text
    assert "| Unanswerable question type | n | Refused with the fixed sentence, off |" in text
    assert "\u2014" not in text


def test_empty_run_does_not_crash():
    s = scoring.summarise([], top_k=5)
    assert s["answerable_n"] == 0 and s["retrieval"]["hit_at_k"]["rate"] is None
    assert "n/a" in scoring.render_summary_markdown(s)
