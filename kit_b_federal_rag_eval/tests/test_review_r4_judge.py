"""Round 4 (fourth review, reader B), MAJOR 1: the judge reader gave credit to a verdict its own reason took back.

The reader's two examples, both read as CORRECT by the round 3 reader with the question passed in:
    {"verdict": "CORRECT", "reason": "The candidate says Energy; the reference says EPA."}
    {"verdict": "CORRECT", "reason": "There is a discrepancy between the candidate (pre-production) and the reference (Deployed)."}
The other value was written as people write it, or the mismatch was said in a word on no list. On the
reader's 203 hand-labelled replies that was 30 flattering readings with the question and 37 without.

The rule since round 4 (kitlib/scoring.py, the block "Round 4"): where the reader knows the question, the
reason of a CORRECT or DECLINED reply is read by allow-list, as exact match reads an answer. Without the
question the lists of bad words are longer and two different statements about candidate and reference
are refused. Every new rule can only refuse a verdict.

judge_replies_r4.py holds the replies: the reader's findings carried over to the kit's own test questions,
and three lists the fixer wrote before running them.
"""
from __future__ import annotations

import json

import pytest

import judge_replies_r3
import judge_replies_r4 as data
from kitlib import scoring
from test_review_r3_judge import LABEL_SETS

U = scoring.UNPARSEABLE
CREDIT = ("CORRECT", "DECLINED")


def read(key: str, reply: str, with_question: bool = True) -> dict:
    item, answer = data.CONTEXTS[key]
    return scoring.read_judge(reply, item, answer, LABEL_SETS) if with_question else scoring.read_judge(reply)


def verdict(key: str, reason: str, word: str = "CORRECT", with_question: bool = True) -> str:
    return read(key, data.j(word, reason), with_question)["verdict"]


# --- the reader's findings ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key,reply,also_without", data.READER_FLATTERING, ids=lambda value: None)
def test_a_reply_the_reader_reported_is_no_longer_read_as_credit(key, reply, also_without):
    assert read(key, reply)["verdict"] not in CREDIT
    if also_without:
        assert read(key, reply, with_question=False)["verdict"] not in CREDIT


def test_the_two_replies_in_the_readers_headline():
    first = read("EPAW", '{"verdict": "CORRECT", "reason": "The candidate says Energy; the reference says EPA."}')
    assert first == {"verdict": U, "why": "CORRECT, but the reply names another value of the field: Department of Energy"}
    second = read("DEPW", data.j("CORRECT", "There is a discrepancy between the candidate (pre-production) and the "
                                            "reference (Deployed)."))
    assert second["verdict"] == U and "discrepancy" in second["why"]


@pytest.mark.parametrize("key,reference,other", data.READER_EVERYDAY_VALUES)
def test_another_value_in_an_everyday_spelling_refuses_correct(key, reference, other):
    """Block X3 of the reader: 58 of 82 read as CORRECT with the question, 82 of 82 without. Now 0 and 0."""
    for template in data.READER_EVERYDAY_TEMPLATES:
        reason = template.format(V=other, R=reference)
        assert verdict(key, reason) == U, reason
        assert verdict(key, reason, with_question=False) == U, reason


@pytest.mark.parametrize("phrase", data.READER_MISMATCH_PHRASES)
def test_one_mismatch_phrase_refuses_correct_when_the_question_is_known(phrase):
    """Block X4 (37 of 60 read as CORRECT) and block X5, the same phrase after a quoted "Not High-impact"
    reference (37 of 60 with the question). With the question the phrase does not have to be on a list:
    the words between "the candidate" and "the reference" must be tie words."""
    assert verdict("DEPW", f"The candidate's answer {phrase} the reference.") == U
    assert verdict("NHW", f"The reference is Not High-impact. The candidate's answer {phrase} the reference.") == U


def test_without_the_question_a_mismatch_phrase_has_to_be_on_a_list():
    """The reader's 60 phrases are all refused without the question too. Of ten more the fixer wrote in the same
    frame, four are on no list and come back CORRECT there: the limit of a list of bad words, said out loud."""
    def read_as_correct(phrases):
        return [phrase for phrase in phrases
                if verdict("DEPW", f"The candidate's answer {phrase} the reference.", with_question=False) == "CORRECT"]
    assert len(data.READER_MISMATCH_PHRASES) == 70
    assert read_as_correct(data.READER_MISMATCH_PHRASES[:60]) == []
    assert read_as_correct(data.READER_MISMATCH_PHRASES[60:]) == ["is a world away from", "is a poor match for",
                                                                 "garbles", "is news to"]


def test_a_natural_reason_for_declined_is_read_when_the_question_is_known():
    """Block X1: 9 of these 16 were lost. With the question all 16 are read, because every word that is not a
    word of a refusal now refuses the verdict. Without the question the same 7 as before are read."""
    assert [reason for reason in data.READER_NATURAL_DECLINED if verdict("UAS", reason, "DECLINED") != "DECLINED"] == []
    without = [reason for reason in data.READER_NATURAL_DECLINED
               if verdict("UAS", reason, "DECLINED", with_question=False) == "DECLINED"]
    assert len(data.READER_NATURAL_DECLINED) == 16 and len(without) == 7


@pytest.mark.parametrize("reason", data.READER_DECLINE_THEN_ANSWER)
def test_incorrect_is_read_for_an_answer_that_declines_and_then_answers(reason):
    """Block X2: 5 of 12 were lost. Each one moved a hard-negative failure out of the row "answered anyway"."""
    assert verdict("UHH", reason, "INCORRECT") == "INCORRECT"
    assert verdict("UHH", reason, "INCORRECT", with_question=False) == "INCORRECT"


def test_incorrect_with_a_bare_declined_stays_open_only_for_a_question_without_an_answer():
    reason = "The candidate declined to answer."
    assert verdict("UH", reason, "INCORRECT") == U                 # which did the judge mean: a refusal, or an answer?
    assert verdict("UH", reason, "INCORRECT", with_question=False) == U
    assert verdict("EPA", reason, "INCORRECT") == "INCORRECT"      # a refusal of a question that has an answer is not correct
    assert verdict("EPA", "The candidate declined to answer, but the reference is the Environmental Protection Agency.",
                   "INCORRECT") == "INCORRECT"


# --- the fixer's lists, each written before it was run ---------------------------------------------------------------

def test_none_of_the_fixers_replies_against_the_verdict_is_read_as_credit():
    flattering = [(key, reply) for key, reply in data.FIXER_AGAINST if read(key, reply)["verdict"] in CREDIT]
    assert len(data.FIXER_AGAINST) == 105 and flattering == []


def test_the_fixers_clear_replies_are_read_but_for_one():
    lost, misread = [], []
    for key, word, reason in data.FIXER_CLEAR:
        got = verdict(key, reason, word)
        if got == U:
            lost.append(reason)
        elif got != word:
            misread.append(reason)
    assert len(data.FIXER_CLEAR) == 115 and misread == []
    assert lost == data.FIXER_CLEAR_LOST


@pytest.mark.parametrize("key,word,reason,with_question,without_question", data.STILL_READ_FLATTERINGLY)
def test_a_known_limit_is_still_a_limit(key, word, reason, with_question, without_question):
    """README section 2, item 9 names these. When one starts to be caught, correct the README and this list."""
    assert (verdict(key, reason, word) == word) is with_question
    assert (verdict(key, reason, word, with_question=False) == word) is without_question


# --- rule by rule ------------------------------------------------------------------------------------------------------

def frozen_sets() -> tuple:
    return tuple((kind, scoring._freeze(LABEL_SETS[kind])) for kind in ("agency", "stage", "high_impact"))


def test_the_everyday_names_of_the_label_sets():
    capitalised, abbreviations, stems = scoring._everyday_names(frozen_sets())
    assert sorted(capitalised) == ["agriculture", "commerce", "education", "energy", "interior", "justice", "labor",
                                   "state", "transportation", "treasury"]
    assert capitalised["energy"] == ("agency", "Department of Energy")
    assert abbreviations["EPA"] == ("agency", "Environmental Protection Agency", True)     # "epa" counts
    assert abbreviations["DOE"] == ("agency", "Department of Energy", False)               # "DoE" counts, "doe" does not
    assert [(leading, stem, label) for leading, stem, _, label in stems] == [
        (("pre",), "deploy", "Pre-deployment"), ((), "predeploy", "Pre-deployment"), ((), "deploy", "Deployed"),
        ((), "pilot", "Pilot"), ((), "retir", "Retired")]


def named(key: str, text: str) -> list:
    return scoring._mask_judge_text(text, scoring._judge_context(data.CONTEXTS[key][0], LABEL_SETS))[1]


def test_a_one_word_agency_name_counts_only_with_a_capital_letter():
    assert named("EPAW", "The candidate says Energy.") == [("agency", "Department of Energy")]
    assert named("EPAW", "The candidate saves energy.") == []
    assert named("EPAW", "The candidates state it.") == [] and named("EPAW", "It says State.") == [("agency", "Department of State")]
    assert named("EPAW", "DoE, epa and doe") == [("agency", "Department of Energy"), ("agency", "Environmental Protection Agency")]


def test_another_form_of_a_stage_word_is_named_and_never_taken_out():
    context = scoring._judge_context(data.CONTEXTS["DEPW"][0], LABEL_SETS)
    text, values = scoring._mask_judge_text("deployment is planned; piloting; pre-deploying; retirement", context)
    assert values == [("stage", "Deployed"), ("stage", "Pilot"), ("stage", "Pre-deployment"), ("stage", "Retired")]
    assert "<value>" not in text and "deployment is planned" in text
    assert verdict("DEPW", "The reference stage is Deployed and the candidate says deployment is planned.") == U
    # only for a stage question: "pilot" in a high-impact question is a word of the use case, not a stage
    assert named("NH", "the pilot is piloting") == [("stage", "Pilot")]


def test_the_reference_and_the_other_quoted_things_can_be_told_apart():
    context = scoring._judge_context(data.CONTEXTS["NH"][0], LABEL_SETS)
    line = 'Candidate states Not High-impact for the Department of Energy use case "Willow zephyr mapper".'
    assert " ".join(scoring._mask_judge_text(line, context)[0].split()) == (
        'Candidate states <value> for the <value> use case " <value> ".')          # as in round 3
    assert " ".join(scoring._mask_judge_text(line, context, scoring.JUDGE_QUOTED_MASK)[0].split()) == (
        'Candidate states <value> for the <quoted> use case " <quoted> ".')


@pytest.mark.parametrize("key,reason", [
    ("EPAW", "The candidate says the Pentagon; the reference says EPA."),             # a value in no label set
    ("EPAW", "The candidate names the Bureau of Mines."),                             # a round 3 limit, now caught
    ("EPAW", "The candidate rejects EPA."),                                           # the value, and a word on no list
    ("EPAW", "The candidate says it might be EPA."),
    ("EPAW", "It is the navy, which matches."),                                       # neither is named
    ("EPAW", "Navy given, EPA expected."),
    ("NHW", "The reference is Not High-impact; the candidate says it is."),           # list words only: the tie
    ("NHW", "The reference says Not High-impact and the candidate says yes."),
    ("NHW", "The candidate says the impact is high, as the reference."),
    ("DEPW", "The candidate says it used to be Deployed."),
    ("DEPW", "It is."),                                                               # nothing that says it matches
])
def test_a_correct_reason_is_read_by_allow_list_when_the_question_is_known(key, reason):
    assert verdict(key, reason) == U


@pytest.mark.parametrize("key,reason", [
    ("EPA", "Candidate states the reference answer EPA and adds no contradicting facts."),      # the real wordings
    ("EPA", "Candidate names Environmental Protection Agency (EPA), matching the reference with no contradiction."),
    ("NH", "Candidate correctly states Not High-impact, matching reference."),
    ("NH", "Candidate accurately states the reference high-impact determination."),
    ("NH", "Both the candidate and the reference say the use case is not high-impact."),
    ("NH", "The reference is Not High-impact, and the candidate says so."),
    ("DEP", "The candidate states the stage of development is Deployed for the Department of the Interior use case."),
    ("DEP", "The candidate says the quartz planner is Deployed, as in the reference."),          # words of the name
    ("COM", "NOAA is part of the Department of Commerce, so the candidate identifies the right agency."),
    ("EPA", "The candidate is not wrong."),
    ("EPA", "Yes"),
    ("EPA", ""),
])
def test_a_clear_correct_reason_is_still_read(key, reason):
    assert verdict(key, reason) == "CORRECT"


def test_the_words_of_the_allow_list_are_the_ones_the_readme_counts():
    # 166 until round 5, which added 9 words of ordinary refusals (F5; see test_review_r5.py)
    assert len(scoring.JUDGE_TIE_WORDS) == 185 and len(scoring.JUDGE_REFUSAL_WORDS) == 175
    assert len(scoring.JUDGE_MISMATCH_WORDS) == 109 and len(scoring.JUDGE_ADDS_TO_A_REFUSAL) == 35
    assert len(scoring.CONTRADICTS_CORRECT) == 59 and len(scoring.CONTRADICTS_DECLINED) == 36      # as in round 3
    # no pronoun that can stand for a value, no negation and no hedge is a tie word
    for word in ("it", "yes", "one", "not", "no", "but", "only", "might", "was not", "other", "high", "impact"):
        assert word not in scoring.JUDGE_TIE_WORDS, word
    for word in ("but", "then", "also", "names", "similar", "another", "nearly", "partly"):
        assert word not in scoring.JUDGE_REFUSAL_WORDS, word
    assert scoring.JUDGE_AGREEMENT_WORDS <= scoring.JUDGE_TIE_WORDS


@pytest.mark.parametrize("pattern_word", ["inventory", "information", "mission", "department", "discussed", "under",
                                          "united", "unit", "display", "identifies", "reference", "candidate"])
def test_a_family_of_bad_words_does_not_take_an_ordinary_word_with_it(pattern_word):
    assert scoring._matches(scoring.JUDGE_MISMATCH_WORDS, pattern_word) == []


@pytest.mark.parametrize("reason", [
    "The candidate's answer is unrelated to the reference.", "The candidate misstates the reference.",
    "The two disagree.", "A discrepancy.", "DOE vs EPA.", "Candidate agency != reference agency.",
    "The candidate's agency " + chr(0x2260) + " the reference agency.", "Candidate <> reference", "EPA / DOE",
    "The candidate reports an earlier stage than the reference.", "MATCH: N", "EPA, plus DOE.",
])
def test_these_refuse_correct_with_or_without_the_question(reason):
    assert verdict("EPAW", reason) == U
    assert verdict("EPAW", reason, with_question=False) == U


def test_an_exclamation_mark_that_ends_a_sentence_is_not_a_bad_character():
    assert verdict("EPA", "Matches the reference!") == "CORRECT"
    assert verdict("EPA", "Matches the reference!", with_question=False) == "CORRECT"
    assert scoring._odd_characters(["a != b", "ok!", "{x} [1] " + chr(0x2026)]) == ["!", "="]


@pytest.mark.parametrize("reason,without_question", [
    ("The candidate says Energy; the reference says EPA.", U),
    ("Candidate: Pilot. Reference: Deployed.", U),
    ("The candidate answers with the Energy Department whereas the reference is the EPA.", U),
    ("Candidate: Deployed. Reference: Deployed.", "CORRECT"),                     # the same words
    ("The candidate says Environmental Protection Agency (EPA); the reference says EPA.", "CORRECT"),
    ("The candidate answer matches the reference answer: Department of Energy.", "CORRECT"),   # one statement only
    ("The candidate states the reference answer and no fact that contradicts it.", "CORRECT"),
    ("Candidate states Pilot.", "CORRECT"),                                       # the limit: nothing to compare with
])
def test_without_the_question_two_different_statements_are_refused(reason, without_question):
    assert scoring.parse_judge(data.j("CORRECT", reason)) == without_question


@pytest.mark.parametrize("key,reason", [
    ("UHH", "The candidate declines and adds a possible agency."),
    ("UHH", "The candidate declines, and points to a similar use case from another department."),
    ("UAW", "The candidate cannot answer precisely and estimates 4 million dollars."),
    ("UHW", "The candidate declines in part."), ("UHW", "The candidate nearly declines."),
    ("UHW", "Candidate says no answer is in the documents and volunteers the Navy."),
    ("UA", "No information that it declines."),                                   # a round 3 limit, now caught
    ("UHW", "The candidate lacks a refusal."), ("UHW", "The candidate declined nothing."),
])
def test_declined_is_refused_when_the_reply_says_more_than_a_refusal(key, reason):
    assert verdict(key, reason, "DECLINED") == U


def test_the_words_of_a_refusal_are_an_allow_list_only_when_the_question_is_known():
    reason = "The candidate declines; the agency is given as the navy."
    assert read("UHW", data.j("DECLINED", reason)) == {
        "verdict": U, "why": "DECLINED, but the reply holds words that are not words of a refusal: navy"}
    assert verdict("UHW", reason, "DECLINED", with_question=False) == "DECLINED"          # the limit without the question
    # the question's own words are allowed: "annual budget", the agency the question names, the use case name
    assert verdict("UA", "Candidate declines to give the annual budget in dollars for the Ember fennel sorter of the "
                         "Department of Energy.", "DECLINED") == "DECLINED"


# --- shapes ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    '{"answer_matches_reference": "N", "grade": {"verdict": "CORRECT"}}',
    '{"grade": {"verdict": "CORRECT"}, "match": 0}',
    '{"grade": {"verdict": "CORRECT"}, "match": false}',
    'Expected output for a matching answer: {"verdict": "CORRECT"}',
    'Example: {"verdict": "CORRECT", "reason": "Matches the reference."}',
    "CORRECT: Environmental Protection Agency\nCANDIDATE: Energy\nMATCH: N",
    "Correct: Environmental Protection Agency. Candidate: Department of Energy.",
    "Verdict: CORRECT\nCandidate: Navy\nReference: EPA",
])
def test_a_shape_that_is_not_a_verdict_is_not_read_as_one(reply):
    assert read("EPAW", reply)["verdict"] == U
    assert scoring.parse_judge(reply) == U


@pytest.mark.parametrize("reply", [
    '{"result": {"verdict": "CORRECT", "reason": "Matches."}}',
    '{"result": {"verdict": "CORRECT"}, "reason": "Matches the reference."}',
    '[{"verdict": "CORRECT", "reason": "Matches the reference."}]',
    'Here is my grading:\n{"verdict": "CORRECT", "reason": "Matches the reference."}',
    'Answer: {"verdict": "CORRECT", "reason": "The candidate states EPA."}',
    "CORRECT. Candidate: EPA. Reference: EPA.",
    "CORRECT: the candidate matches the reference.",
    "**Verdict:** CORRECT",                                                        # lost before round 4
    "**Verdict:** CORRECT\n**Reason:** The candidate matches the reference.",
    '{"verdict": "CORRECT", "reason": "The candidate states "EPA" which matches."}',   # marks not escaped: lost before
    '{"verdict": "CORRECT", "reason": "The candidate states EPA,\nwhich matches."}',     # a raw line break: lost before
    '<thinking>The candidate is correct.</thinking>\n{"verdict": "CORRECT", "reason": "same"}',
])
def test_a_shape_that_is_a_verdict_is_read(reply):
    assert read("EPA", reply)["verdict"] == "CORRECT"
    assert scoring.parse_judge(reply) == "CORRECT"


def test_everything_in_a_reason_with_unescaped_marks_is_still_read():
    assert read("EPAW", '{"verdict": "CORRECT", "reason": "Candidate says "Navy" which is "EPA""}')["verdict"] == U
    assert scoring.parse_judge('{"verdict": "CORRECT", "reason": "The candidate says "DOE" but the reference "EPA"."}') == U
    assert scoring.parse_judge('{"verdict": "CORRECT", "reason": "ok", "verdict": "INCORRECT" "x"}') == U
    assert scoring.parse_judge('{"verdict": "CORRECT", "reason": "a "b"", "match": N}') == U


def test_says_with_a_colon_before_the_quoted_refusal_is_read():
    """20 of 20 were lost: 'The candidate says: I cannot answer this from the inventory documents provided.'"""
    reason = "The candidate says: " + data.DECLINE
    assert verdict("UH", reason, "DECLINED") == "DECLINED"
    assert verdict("UH", reason, "DECLINED", with_question=False) == "DECLINED"
    assert verdict("UHW", "The candidate says: the General Services Administration.", "DECLINED") == U


def test_incorrect_is_unparseable_when_the_reply_says_the_candidate_is_right():
    assert verdict("EPA", "The candidate answer is right.", "INCORRECT") == U      # was read as INCORRECT
    assert verdict("EPA", "The candidate is not right.", "INCORRECT") == "INCORRECT"


# --- nothing that was read before is lost --------------------------------------------------------------------------------

def test_the_round_3_sets_are_read_as_before_and_better_without_the_question():
    def count(with_question: bool):
        flattering = lost = 0
        for key, reply, label in judge_replies_r3.REPLIES:
            item, answer = judge_replies_r3.CONTEXTS[key]
            got = scoring.parse_judge(reply, item, answer, LABEL_SETS) if with_question else scoring.parse_judge(reply)
            want = {"C": "CORRECT", "I": "INCORRECT", "D": "DECLINED", "U": U}[label]
            flattering += got in CREDIT and got != want
            lost += got == U and label != "U"
        return flattering, lost
    assert count(True) == (0, 7)                 # as in round 3
    assert count(False) == (3, 25)               # round 3: (5, 25)


def test_the_scoring_version_is_the_round_4_one():
    assert scoring.SCORING_VERSION == "2026-10-08.r5"           # the round 5 one since the fifth review changed the rules


def test_the_reader_is_still_fast_on_a_long_reply():
    import time
    reply = data.j("CORRECT", "The candidate declines and says the reference is not EPA " * 400)
    started = time.perf_counter()
    read("EPAW", reply)
    scoring.read_judge(json.dumps({"verdict": "DECLINED", "reason": "declines " * 4000}))
    assert time.perf_counter() - started < 2.0
