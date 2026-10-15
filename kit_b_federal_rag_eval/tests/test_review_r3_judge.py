"""Round 3 (rehearsal on real model text), defect 1: the judge reader lost every "Not High-impact" verdict.

On 2026-10-07 real stand-in judges wrote 120 replies from the kit's own judge prompt. For all ten
questions whose reference is "Not High-impact" the reply was the well-formed object
    {"verdict": "CORRECT", "reason": "Candidate correctly states Not High-impact, matching reference."}
and the round 2 reader returned UNPARSEABLE for every one, with the note "CORRECT, but the reply also
says: not". The word "Not" is part of the VALUE. The table read "correct as judged 90/100" where the
judge had said 100.

The rule since round 3: the evaluation loop tells the reader which question the reply is for. What the
judge only quotes (the reference value, the use case name, the question, NO ANSWER) is taken out before the
word lists are applied. The candidate's own words are never taken out. And because taking words out can only
help a verdict, a reply that names ANOTHER value than the reference is refused. Without the question the
reader takes nothing out and reads the reply as it did in round 2.

judge_replies_r3.py holds the replies. Its 117 hand labels were written before the round 3 reader
existed; the digest below is the one taken at that moment, so a changed label fails a test here.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json

import pytest

import fakeaws
import judge_replies_r2
import judge_replies_r3 as data
from conftest import KIT_DIR
from kitlib import evalloop, scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, STAGE_LABELS, simple_label_set
from test_evalloop import ITEMS, SCRIPT, FakeBackend
from test_review_r1_eval import BILLS, write_build, write_state

U = scoring.UNPARSEABLE
NAMES = {"C": "CORRECT", "I": "INCORRECT", "D": "DECLINED", "U": U}
AGENCIES = json.loads((KIT_DIR / "tests" / "fixtures" / "agencies_41.json").read_text(encoding="utf-8"))["agencies"]
LABEL_SETS = {
    "agency": [{"label": name, "aliases": [{"text": abbr, "case_sensitive": True}]} for name, abbr in AGENCIES],
    "stage": simple_label_set(STAGE_LABELS),
    "high_impact": simple_label_set(HIGH_IMPACT_LABELS),
}
# SHA-256 of the (context, reply, label) triples as they were written, before the reader was changed.
LABELS_AS_FIRST_WRITTEN = "bbd90a254248b795f2459b96622311e8c447ae468fb73b43dbc89bc31390f9f6"


# One more question, added with the attack list below (it is in no hand-labelled reply): the candidate's
# answer denies the reference, so a judge that quotes it and says CORRECT contradicts itself.
data.CONTEXTS.setdefault("NOT", (dict(data.CONTEXTS["TR"][0], use_case_name="Fennel garnet sorter",
                                      question='What stage of development is recorded for the AI use case named '
                                               '"Fennel garnet sorter", reported by the Department of State?'),
                                 "The use case is not Deployed."))


def read(key: str, reply: str) -> dict:
    item, answer = data.CONTEXTS[key]
    return scoring.read_judge(reply, item, answer, LABEL_SETS)


def verdict(key: str, reason: str, word: str = "CORRECT") -> str:
    return read(key, data._j(word, reason))["verdict"]


# --- the ten real replies -------------------------------------------------------------------------------------

@pytest.mark.parametrize("item,answer,reply", data.REAL_NOT_HIGH_IMPACT, ids=lambda value: None)
def test_the_real_not_high_impact_reply_is_read_as_correct(item, answer, reply):
    assert reply == data.REAL_REPLY and item["expected_answer"] == "Not High-impact"
    reading = scoring.read_judge(reply, item, answer, LABEL_SETS)
    assert reading == {"verdict": "CORRECT", "why": ""}
    assert scoring.judged_correct(item, reading["verdict"]) is True


def test_there_are_ten_of_them_and_without_the_question_the_reply_is_still_refused():
    assert len(data.REAL_NOT_HIGH_IMPACT) == 10
    # The conservative side: a reader that is not told the question cannot know that "Not" is a value.
    assert scoring.read_judge(data.REAL_REPLY) == {"verdict": U, "why": "CORRECT, but the reply also says: not"}
    item, answer, reply = data.REAL_NOT_HIGH_IMPACT[0]
    assert scoring.parse_judge(reply, item, answer) == U                   # no label sets: nothing is taken out
    assert scoring.parse_judge(reply, None, answer, LABEL_SETS) == U       # no question: nothing is taken out


def test_the_same_reply_for_another_reference_is_refused():
    """The reply says the candidate states Not High-impact. For a question whose reference is another
    value that is a judge contradicting the reference, and before round 3 only the word "not" caught it."""
    for key in ("HI", "PH"):
        reading = read(key, data.REAL_REPLY)
        assert reading["verdict"] == U
        assert reading["why"] == "CORRECT, but the reply names another value of the field: Not High-impact"


def test_the_evaluation_loop_gives_the_reader_the_question():
    item, answer, reply = data.REAL_NOT_HIGH_IMPACT[3]

    class Backend:
        def retrieve(self, question):
            return [evalloop.Passage(text="High-impact determination: Not High-impact", doc_id="uc-0001", score=0.9)]

        def generate(self, system, user):
            return {"text": answer}

        def apply_guardrail(self, sources, question, candidate):
            return {"action": "NONE"}

        def judge(self, system, user):
            assert "Reference answer: Not High-impact" in user
            return {"text": reply}

    row = evalloop.evaluate_item(item, Backend(), LABEL_SETS)
    assert row["error"] is None
    assert (row["exact"], row["judge_verdict"], row["judge_note"], row["judged_correct"]) == (True, "CORRECT", "", True)


class RealReplyBackend(FakeBackend):
    """The scripted backend of test_evalloop.py; question 3 (reference "Not High-impact") is answered
    right and judged with the real reply."""
    def __init__(self, *args, **kwargs):
        script = dict(SCRIPT)
        script["q-003"] = dict(SCRIPT["q-003"], answer="The determination is Not High-impact.", judge=data.REAL_REPLY,
                               action="NONE", docs=["uc-0003"])
        super().__init__(script=script)


def test_the_run_counts_the_real_reply_as_judged_correct(monkeypatch, tmp_path):
    fakeaws.install(monkeypatch, fakeaws.World())
    spec = importlib.util.spec_from_file_location("run_eval_script_r3_judge", KIT_DIR / "50_run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_build(tmp_path)
    write_state()
    monkeypatch.setattr(module.api, "BedrockBackend", RealReplyBackend)
    assert ITEMS[2]["expected_answer"] == "Not High-impact"
    assert module.main([BILLS]) == 0
    out_dir = sorted((tmp_path / "results").iterdir())[0]
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["judge_unparseable"] == 0
    assert summary["by_type"]["high_impact"]["judged_off"]["count"] == 1
    assert summary["guardrail_off"]["answerable_judged_correct"]["count"] == 3     # q-004 declines; the other three
    rows = {row["id"]: row for row in module.read_attempts(out_dir / "raw.jsonl")[0]}
    assert (rows["q-003"]["judge_verdict"], rows["q-003"]["judged_correct"], rows["q-003"]["exact"]) == ("CORRECT", True, True)


# --- the fixer's own 117 replies, labelled before the reader was changed -------------------------------------------

def score_own_set(with_question: bool = True):
    flattering, lost = [], []
    for key, reply, label in data.REPLIES:
        got = read(key, reply)["verdict"] if with_question else scoring.parse_judge(reply)
        if got in ("CORRECT", "DECLINED") and got != NAMES[label]:
            flattering.append((key, reply))
        elif got == U and label != "U":
            lost.append((key, reply))
        else:
            assert got == NAMES[label], (key, reply, label, got)           # never a third kind of mistake
    return flattering, lost


def test_no_label_was_changed_after_the_reader_was_written():
    frozen = json.dumps([[key, reply, label] for key, reply, label in data.REPLIES], sort_keys=True).encode()
    assert hashlib.sha256(frozen).hexdigest() == LABELS_AS_FIRST_WRITTEN
    counts = {label: sum(1 for _, _, l in data.REPLIES if l == label) for label in "CDIU"}
    assert len(data.REPLIES) == 117 and counts == {"C": 41, "D": 16, "I": 12, "U": 48}
    assert all(key in data.CONTEXTS for key, _, _ in data.REPLIES)
    kinds = {data.CONTEXTS[key][0]["type"] for key, _, _ in data.REPLIES}
    assert kinds == {"agency", "stage", "high_impact", "unanswerable_heldout", "unanswerable_absent_field"}


def test_the_set_quotes_every_value_of_every_label_set_and_the_phrases_asked_for():
    reasons = " ".join(reply for _, reply, _ in data.REPLIES)
    for value in STAGE_LABELS + HIGH_IMPACT_LABELS + ["Department of Energy", "DOE", "NO ANSWER"]:
        assert value in reasons, value
    for phrase in ("does not contradict", "no contradicting facts", "ot a refusal", "candidate does not decline",
                   "othing incorrect"):
        supported = [label for _, reply, label in data.REPLIES if phrase in reply.lower() and label != "U"]
        contradicted = [label for _, reply, label in data.REPLIES if phrase in reply.lower() and label == "U"]
        assert supported and contradicted, phrase                          # each phrase on both sides


def test_none_of_the_fixers_replies_is_read_flatteringly():
    flattering, lost = score_own_set()
    assert flattering == []
    # The seven that are lost, said out loud (README section 8). Each is counted as unparseable, never as correct.
    assert sorted(reply for _, reply in lost) == sorted([
        data._j("CORRECT", 'Candidate says "The stage of development is Retired; no other stage is recorded in the '
                           'passages", which matches the reference Retired.'),
        data._j("DECLINED", "Reference is NO ANSWER."),
        data._j("DECLINED", "Candidate declines although the reference is Pilot."),
        '{"verdict": "CORRECT", "reason": "Candidate correctly states Not',
        '{"verdict": "CORRECT", "reason": "Candidate states Presumed High-Impact, but Not',
        data._j("CORRECT", "Candidate states Retired and says no other stage is recorded."),
        data._j("CORRECT", "Candidate's stage, Pilot, is the same as the reference; wording differs only."),
    ])


def test_without_the_question_the_only_flattering_readings_are_the_ones_that_need_the_reference():
    """Read without the question, three replies come back CORRECT although a person who knows the reference
    would refuse them: each states ONE value that is not the reference and says nothing else against the
    verdict. That is the limit README section 2, item 9 names; the question closes it. In round 3 there
    were five: "Candidate states Deployed; the reference is Pilot." and "The candidate says DOJ; the
    reference says DOE." give two different things, which round 4 refuses without the question too."""
    flattering, _ = score_own_set(with_question=False)
    assert sorted(reply for _, reply in flattering) == sorted([
        data._j("CORRECT", "Candidate states High-impact."),
        data._j("CORRECT", "Candidate states Pilot."),
        data._j("CORRECT", "The candidate names the Department of Justice."),
    ])
    assert score_own_set()[0] == []


def test_the_round_2_replies_are_read_as_before():
    """The round 2 lists carry no question. Their counts are the ones the README has stated since round 2."""
    flattering = [reply for reply, label in judge_replies_r2.REPLIES
                  if scoring.parse_judge(reply) in ("CORRECT", "DECLINED") and scoring.parse_judge(reply) != NAMES[label]]
    lost = [reply for reply, label in judge_replies_r2.REPLIES if scoring.parse_judge(reply) == U and label != "U"]
    assert flattering == [] and len(lost) == 5 and len(judge_replies_r2.REPLIES) == 89


# --- replies written AFTER the reader existed, while attacking it ---------------------------------------------------
# They are not a measurement: the person who wrote the reader wrote them. Nine of the 36 were read
# flatteringly by a draft of the round 3 reader and made it stricter (marked "draft"); the others were refused
# from the first draft on. All 36 must stay refused.

FOUND_WHILE_ATTACKING = [
    ("NH", "CORRECT", "Not, High-impact"),                                   # a comma the value does not have; draft
    ("NH", "CORRECT", "Not. High-impact."),
    ("NH", "CORRECT", "not Not High-impact"),
    ("NH", "CORRECT", "Not High-impact? The candidate says High-impact."),
    ("NH", "CORRECT", "Candidate states Not High-impact, which is not the reference."),
    ("NH", "CORRECT", "The candidate gives NO ANSWER."),                     # NO ANSWER is a value only where it is the reference
    ("HI", "CORRECT", "High-impact, not."),
    ("PH", "CORRECT", "Presumed High-Impact"),
    ("ST", "CORRECT", "Not High-impact."),                                   # a value of another field is not taken out
    ("ST", "CORRECT", "Candidate states the use case was retired from pilot."),
    ("ST", "CORRECT", "The candidate states Pilot. No other facts are correct."),
    ("ST", "CORRECT", "States Pilot and nothing else matches."),
    ("ST", "CORRECT", "no error-free statement"),    # draft
    ("ST", "CORRECT", "The candidate should have declined."),
    ("ST", "CORRECT", "The candidate does not decline to guess."),
    ("AG", "CORRECT", 'The candidate is "not" correct.'),                    # a quoted word is not a quoted answer
    ("AG", "CORRECT", 'Candidate says "is not the Department of Energy"'),   # not a span of the answer
    ("AG", "CORRECT", "Candidate names ED."),
    ("AG", "CORRECT", "Harbor lantern sorter was reported by another agency."),
    ("QA", "CORRECT", 'Candidate says "no other stage is recorded in the passages" and states Pilot.'),
    ("NOT", "CORRECT", 'Candidate says "The use case is not Deployed."'),    # the answer's own words, quoted; draft
    ("AGD", "CORRECT", 'Candidate says "cannot answer this from the inventory documents".'),
    ("UH", "DECLINED", "The candidate declines to refuse."),    # draft
    ("UH", "DECLINED", "The candidate does not give up and answers."),
    ("UH", "DECLINED", "The candidate fails to decline."),
    ("UH", "DECLINED", "The candidate should have declined."),
    ("UH", "DECLINED", "The candidate answered instead of declining."),
    ("UH", "DECLINED", "Declines. Says EPA."),
    ("UH", "DECLINED", "The candidate declines and states that the agency is NASA."),
    ("UH", "DECLINED", "The candidate declines and provides an agency."),
    ("UA", "DECLINED", "The candidate declines and says 4 million dollars."),    # draft
    ("UA", "DECLINED", "The candidate does not answer correctly."),    # draft
    ("UA", "DECLINED", "The candidate cannot be said to decline."),    # draft
    ("UA", "DECLINED", "The candidate is unable to decline."),    # draft
    ("UA", "DECLINED", "Declines. Says Department of Energy."),    # draft
    ("UX", "DECLINED", 'Candidate says "The Department of Justice reported the AI use case named" and declines.'),
]


@pytest.mark.parametrize("key,word,reason", FOUND_WHILE_ATTACKING)
def test_a_reply_found_while_attacking_the_new_reader_is_refused(key, word, reason):
    assert verdict(key, reason, word) == U


def test_the_attack_list_is_as_long_as_the_readme_says():
    source = (KIT_DIR / "tests" / "test_review_r3_judge.py").read_text(encoding="utf-8")
    block = source.split("FOUND_WHILE_ATTACKING = [")[1].split("]\n")[0]
    assert len(FOUND_WHILE_ATTACKING) == 36 and block.count("draft\n") == 9


# --- what the round 3 reader still read flatteringly: found while attacking it and not fixed THEN -------------------
# A person would refuse each of these. The round 3 reader did not, with or without the question. Round 4
# refuses all four when the question is known (the allow-list of tests/test_review_r4_judge.py). Without the
# question the first three still come back; the limits that remain are in tests/judge_replies_r4.py.

STILL_READ_FLATTERINGLY = [
    # the candidate's answer was the refusal sentence; the judge quotes a part of it that holds no refusal word
    ("AGD", "CORRECT", 'Candidate says "answer this from the inventory documents provided".'),
    # a wrong value that is in none of the three label sets
    ("AG", "CORRECT", "The candidate names the Bureau of Mines."),
    ("UX", "DECLINED", "The candidate declines; it reported the AI use case as Justice."),
    # a denial of the refusal in words that are on no list
    ("UA", "DECLINED", "No information that it declines."),
]


@pytest.mark.parametrize("key,word,reason", STILL_READ_FLATTERINGLY)
def test_a_round_3_limit_is_caught_since_round_4_when_the_question_is_known(key, word, reason):
    assert verdict(key, reason, word) == U
    still_without = reason != "No information that it declines."
    assert (scoring.parse_judge(data._j(word, reason)) == word) is still_without


def test_the_value_that_holds_a_but_can_be_read_two_ways():
    """ "Presumed High-Impact, but Not High-impact" holds ", but". A person can read this reason as the
    candidate stating the whole value, or as "Presumed High-Impact" against a reference "Not High-impact".
    The reference of this question IS the long value, so the reader takes the first reading."""
    assert verdict("PH", "Candidate states Presumed High-Impact, but Not High-impact is the reference.") == "CORRECT"
    assert verdict("NH", "Candidate states Presumed High-Impact, but Not High-impact is the reference.") == U


# --- what is taken out, and what is not -------------------------------------------------------------------------

def masked(key: str, text: str, context: dict | None = None):
    """(the text with the quoted values taken out, white space collapsed; the values named)."""
    item, _ = data.CONTEXTS[key]
    context = context or scoring._judge_context(item, LABEL_SETS)
    text, named = scoring._mask_judge_text(text, context)
    return " ".join(text.split()), named


def test_only_the_reference_and_what_the_question_gives_is_taken_out():
    text, named = masked("NH", "Candidate states Not High-impact for the Department of Energy, and High-impact or Pilot.")
    assert text == "Candidate states <value> for the <value> , and High-impact or Pilot."
    assert named == [("high_impact", "Not High-impact"), ("agency", "Department of Energy"),
                     ("high_impact", "High-impact"), ("stage", "Pilot")]
    # in any case and with a space for the hyphen, as exact match reads a value
    assert masked("NH", "the use case is not high impact")[0] == "the use case is <value>"
    # every spelling exact match accepts, and the abbreviation the judge prompt shows
    assert masked("AG", "DOE; Energy Department; Dept. of Energy; department of energy")[0].count("<value>") == 4
    assert masked("ST2", "Predeployment, pre deployment, PRE-DEPLOYMENT")[0].count("<value>") == 3
    assert masked("AG", "doe")[0] == "doe"                                # an abbreviation only as it is written


def test_the_field_name_is_not_read_as_a_value():
    for phrase in ("high-impact determination", "High-Impact Determinations", "high impact status",
                   "high-impact classification"):
        assert masked("NH", f"Candidate states the reference {phrase}.")[1] == []
        assert verdict("NH", f"Candidate accurately states the reference {phrase}.") == "CORRECT"
    assert masked("ST", "the stage of development is Pilot")[1] == [("stage", "Pilot")]


def test_the_use_case_name_is_taken_out_only_as_the_question_writes_it():
    assert masked("TR", "States Deployed for No-Code Error Triage Pilot.") == (
        "States <value> for <value> .", [("stage", "Deployed")])
    # in another case it is not the name, and the stage inside it counts as a value named
    assert masked("TR", "no-code error triage pilot")[1] == [("stage", "Pilot")]
    item = dict(data.CONTEXTS["ST"][0], use_case_name="Other", question='What stage of development is recorded for '
                'the AI use case named "Other", reported by the Department of Justice?')
    context = scoring._judge_context(item, LABEL_SETS)
    assert masked("ST", 'States Pilot for "Other".', context=context)[0] == 'States <value> for " <value> ".'
    assert masked("ST", "Other agency named.", context=context)[0] == "Other agency named."
    assert scoring.parse_judge(data._j("CORRECT", "Other agency named."), item, "It is Pilot.", LABEL_SETS) == U


def test_a_value_inside_the_use_case_name_gives_no_exemption():
    assert verdict("TR", "Candidate states Pilot.") == U
    assert verdict("TR", "Candidate states Deployed for No-Code Error Triage Pilot, matching the reference.") == "CORRECT"


def test_no_answer_is_a_value_only_for_a_question_that_has_none():
    assert masked("UA", "Reference is NO ANSWER.")[0] == "Reference is <value> ."
    assert masked("NH", "Reference is NO ANSWER.")[0] == "Reference is NO ANSWER."
    assert masked("UA", "There is no answer.")[0] == "There is no answer."            # the judge's own words
    echoed = "NO ANSWER. The documents do not contain the answer to this question. A candidate that declines gets DECLINED."
    assert "DECLINED" not in masked("UA", echoed)[0]
    assert verdict("UA", "Reference is NO ANSWER. The candidate declines.", "DECLINED") == "DECLINED"
    assert verdict("UA", "Reference is NO ANSWER.", "DECLINED") == U       # says nothing about the candidate: lost
    assert scoring.NO_ANSWER_REFERENCE.startswith(scoring.NO_ANSWER_TOKEN + ".")


def test_the_candidates_own_words_are_never_taken_out():
    """A draft took a quoted span of the answer out. Then CORRECT with the reason 'Candidate says "The use
    case is not Deployed."' came back CORRECT for a question whose reference is Deployed."""
    span = '"no other stage is recorded in the passages"'
    assert masked("QA", f"Candidate adds {span}.")[0] == f"Candidate adds {span}."
    assert verdict("QA", f"States Retired. Also says {span}.") == U        # a right answer, quoted: lost
    assert verdict("QA", "States Retired. Also says no other stage is recorded in the passages.") == U
    assert verdict("NOT", 'Candidate says "The use case is not Deployed."') == U
    assert verdict("NOT", "Candidate states Deployed.") == "CORRECT"       # the same question, a reason without the quote
    # the answer is not needed for anything: with or without it the reading is the same
    item, answer = data.CONTEXTS["NH"]
    assert scoring.read_judge(data.REAL_REPLY, item, None, LABEL_SETS) == scoring.read_judge(data.REAL_REPLY, item, answer, LABEL_SETS)


def test_a_quoted_refusal_is_read():
    quote = '"I cannot answer this from the inventory documents provided."'
    assert masked("AGD", f"Candidate says {quote}")[0] == f"Candidate says {quote}"
    assert verdict("AGD", f"Candidate says {quote}") == U
    assert verdict("UH", f"Candidate says {quote}", "DECLINED") == "DECLINED"


@pytest.mark.parametrize("key,reason", [
    ("ST", "Candidate states Deployed; the reference is Pilot."),
    ("AG", "The candidate says DOJ; the reference says DOE."),
    ("AG", "The candidate says DOE; the reference says EPA."),
    ("HI", "Candidate states Not High-impact."),
    ("NH", "Candidate states High-impact."),
    ("NH", "Candidate states Presumed High-Impact, but Not High-impact."),
    ("PH", "Candidate states Not High-impact."),
    ("ST2", "States Pre-deployment, or Pilot."),
])
def test_correct_is_refused_when_the_reply_names_another_value_of_the_field(key, reason):
    reading = read(key, data._j("CORRECT", reason))
    assert reading["verdict"] == U and reading["why"].startswith("CORRECT, but the reply names another value of the field")
    for shape in ("CORRECT - " + reason, "Verdict: CORRECT\nReason: " + reason,
                  reason + '\n{"verdict": "CORRECT", "reason": "same"}',
                  '{"verdict": "CORRECT", "reason": "same"}\n{"note": "%s"}' % reason,
                  '{"verdict": "CORRECT", "reason": "%s' % reason):
        assert read(key, shape)["verdict"] == U, shape


@pytest.mark.parametrize("key,reason", [
    ("ST", "Candidate states Pilot for the Department of Justice use case."),       # the question names that agency
    ("ST", "Candidate states Pilot; the passage also records High-impact."),        # a value of another field
    ("AG", "Candidate names the Department of Energy; the use case is Deployed."),  # a value of another field
])
def test_a_value_of_another_field_or_of_the_question_does_not_refuse_correct(key, reason):
    assert verdict(key, reason) == "CORRECT"


@pytest.mark.parametrize("key,reason", [
    ("UH", "Candidate declines, then states Not High-impact."),
    ("UH", "Declines. Says EPA."),
    ("UA", "Reference is NO ANSWER; the candidate states Pilot."),
    ("UX", "The candidate states Department of Justice."),
    ("HI", "The candidate declines; the reference is Not High-impact."),            # not this question's reference
])
def test_declined_is_refused_when_the_reply_names_a_value(key, reason):
    assert read(key, data._j("DECLINED", reason))["verdict"] == U


@pytest.mark.parametrize("key,reason", [
    ("NH", "The candidate says it cannot answer; the reference is Not High-impact."),
    ("UA", "Candidate declines to give the annual budget for the Department of Energy use case."),
    ("UA", "The candidate does not give an answer."),
    ("UH", "Candidate states it cannot answer from the documents provided."),
    ("UH", "The candidate says that the documents do not contain the answer."),
    ("UH", "The candidate correctly declines."),
])
def test_declined_is_read_when_the_reply_names_only_the_reference_or_the_question(key, reason):
    assert read(key, data._j("DECLINED", reason))["verdict"] == "DECLINED"


# --- the phrases: a negation is let through only with the bad thing it denies ----------------------------------

@pytest.mark.parametrize("reason", [
    "does not contradict the reference", "no contradicting facts", "States it; no contradictions.",
    "Not a refusal.", "The candidate does not decline.", "The candidate did not refuse.", "No refusal.",
    "Nothing incorrect.", "Nothing incorrect is added.", "Not incorrect.", "Nothing in it is wrong.", "No errors.",
    "With no mistakes.", "Adds no other facts.", "No additional claims are added.", "States it and nothing else.",
])
def test_these_negations_support_correct_with_or_without_the_question(reason):
    assert scoring.parse_judge(data._j("CORRECT", reason)) == "CORRECT"
    assert verdict("ST", reason) == "CORRECT"


@pytest.mark.parametrize("reason", [
    "not", "Not correct.", "does not state the reference", "does not match", "no match", "not the same",
    "No. It contradicts the reference.", "No, incorrect.", "Not a refusal, not an answer either.",
    "The candidate does not decline, it guesses.", "Nothing correct.", "Nothing incorrect, except the agency.",
    "No other facts are correct.", "Nothing else is right, the agency is wrong.", "no error-free statement",
    "It is not that nothing is wrong.", "No refusal and no answer.", "not only wrong", "no error free statement",
])
def test_every_other_negation_still_refuses_correct_with_or_without_the_question(reason):
    assert scoring.parse_judge(data._j("CORRECT", reason)) == U
    assert verdict("ST", reason) == U


@pytest.mark.parametrize("reason", [
    "This is not a refusal.", "The candidate does not decline.", "The candidate never declines.", "No refusal here.",
    "The candidate did not refuse.", "The candidate answers instead of declining.", "It should have declined.",
    "The candidate fails to decline.", "The candidate declines to refuse.", "The candidate does not say it cannot answer.",
    "The candidate declines and says 4 million dollars.", "The candidate declines and states Pilot.",
    "The candidate declines and provides an answer.", "The candidate does not answer correctly.",
    "The candidate cannot decline.", "The candidate does not give a refusal.",
])
def test_declined_is_refused_when_the_reply_says_the_candidate_did_not_decline(reason):
    assert scoring.parse_judge(data._j("DECLINED", reason)) == U           # needs no question
    assert verdict("UH", reason, "DECLINED") == U
    assert scoring.parse_judge("DECLINED - " + reason) == U
    assert scoring.parse_judge("Verdict: DECLINED\nReason: " + reason) == U


@pytest.mark.parametrize("reason", [
    "Reference is NO ANSWER and the candidate does not decline: it names the Department of Justice.",
    "Not a refusal. The candidate gives an agency.", "The candidate answers instead of declining.",
    "The candidate should have declined; it names an agency instead.",
    "Candidate gives an answer rather than declining.", "The candidate fails to decline.",
])
def test_incorrect_is_read_when_the_reply_says_the_candidate_did_not_decline(reason):
    assert scoring.parse_judge(data._j("INCORRECT", reason)) == "INCORRECT"
    assert verdict("UX", reason, "INCORRECT") == "INCORRECT"


def test_incorrect_is_still_refused_when_the_reply_says_the_candidate_declined():
    for reason in ("The candidate declines to answer.", "It should have answered; it declined.",
                   "Not a refusal? The candidate declined."):
        assert scoring.parse_judge(data._j("INCORRECT", reason)) == U
        assert verdict("UH", reason, "INCORRECT") == U


# --- nothing else moved ---------------------------------------------------------------------------------------

def test_the_judge_prompt_and_its_fingerprint_did_not_change():
    """The NO ANSWER reference moved from kitlib/evalloop.py to kitlib/scoring.py. Its text, and with it the
    prompts fingerprint the rehearsal recorded (d0d1cb28c544), are the same."""
    assert evalloop.NO_ANSWER_REFERENCE is scoring.NO_ANSWER_REFERENCE
    text = "\x00".join((evalloop.GEN_SYSTEM_PROMPT, evalloop.JUDGE_SYSTEM_PROMPT, evalloop.JUDGE_RUBRIC,
                        evalloop.NO_ANSWER_REFERENCE))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest().startswith("d0d1cb28c544")
    item = data.CONTEXTS["UA"][0]
    assert f"Reference answer: {scoring.NO_ANSWER_REFERENCE}\n" in evalloop.build_judge_prompt(item, "x")


def test_the_scoring_version_is_past_round_3_and_the_pattern_count_the_readme_states_is_unchanged():
    assert scoring.SCORING_VERSION == "2026-10-08.r5"          # rounds 4 and 5 changed the rules again: test_review_r4/r5_*.py
    assert len(scoring.CONTRADICTS_CORRECT) == 59 and r"\bnot\b" in scoring.CONTRADICTS_CORRECT


def test_the_reader_does_not_change_the_question_or_the_label_sets():
    item, answer = data.CONTEXTS["PH"]
    before = json.dumps([item, LABEL_SETS], sort_keys=True)
    for _ in range(2):
        assert read("PH", data._j("CORRECT", "Candidate states Presumed High-Impact, but Not High-impact.")) == {
            "verdict": "CORRECT", "why": ""}
    assert json.dumps([item, LABEL_SETS], sort_keys=True) == before


# --- the cross-check: every value of every label set, as the reference and as the other value ---------------------

REAL_TEMPLATES = [                                      # the wordings the real judges used in the rehearsal
    "Candidate correctly states {R}, matching reference.",
    "Candidate states {R}, matching the reference with no contradicting facts.",
    "Candidate correctly states the reference answer {R} with no contradictions.",
    "Candidate names {R}, matching the reference with no contradiction.",
    "Candidate correctly states {R}.",
]
AGAINST_TEMPLATES = [                                   # CORRECT must never come back for any of these
    "Candidate states {V}.",
    "The candidate says {V}; the reference says {R}.",
    "Candidate states {V}, not {R}.",
    "{R} is the reference; the candidate gives {V}.",
    "Candidate states {R} and {V}.",
    "Candidate: {V}. Reference: {R}.",
    "The candidate does not state {R}.",
    "{R}? No.",
    "not {R}",
    "Candidate states {R} incorrectly.",
    "The candidate contradicts {R}.",
    "Wrong: {R} expected.",
    "The candidate declines; {R} is the reference.",
]
DECLINED_AGAINST_TEMPLATES = [                          # DECLINED must never come back for any of these
    "The candidate declines and states {V}.",
    "Declines. {V}.",
    "The candidate says it cannot answer. Then: {V}.",
    "Not a refusal: {V}.",
    "The candidate does not decline; it says {V}.",
]


def question_about(kind: str, reference: str) -> dict:
    return data._item(kind, "Juniper ember reviewer", reference, "Department of Labor")


@pytest.mark.parametrize("kind", ["agency", "stage", "high_impact"])
def test_every_value_as_the_reference_in_the_real_wordings_is_read(kind):
    read_as_correct = total = 0
    for entry in LABEL_SETS[kind]:
        spellings = [entry["label"]] + [alias["text"] for alias in entry["aliases"]]
        if entry["aliases"]:
            spellings.append(f'{entry["label"]} ({entry["aliases"][0]["text"]})')
        for spelling in spellings:
            for template in REAL_TEMPLATES:
                item = question_about(kind, entry["label"])
                item["accepted_aliases"] = entry["aliases"]
                got = scoring.parse_judge(data._j("CORRECT", template.format(R=spelling)), item, "", LABEL_SETS)
                total += 1
                read_as_correct += got == "CORRECT"
    assert read_as_correct == total and total == {"agency": 41 * 3 * 5, "stage": 4 * 5, "high_impact": 3 * 5}[kind]


@pytest.mark.parametrize("kind", ["agency", "stage", "high_impact"])
def test_no_reply_that_speaks_against_correct_is_read_as_correct_for_any_pair_of_values(kind):
    labels = [entry["label"] for entry in LABEL_SETS[kind]]
    total = 0
    for reference in labels:
        item = question_about(kind, reference)
        for other in labels:
            if other == reference:
                continue
            for template in AGAINST_TEMPLATES:
                reply = data._j("CORRECT", template.format(R=reference, V=other))
                total += 1
                assert scoring.parse_judge(reply, item, "", LABEL_SETS) == U, reply
    assert total == len(labels) * (len(labels) - 1) * len(AGAINST_TEMPLATES)


def test_no_reply_that_names_a_value_is_read_as_declined_for_a_question_without_an_answer():
    total, in_the_question = 0, []
    for key in ("UH", "UA"):
        item, answer = data.CONTEXTS[key]
        for kind in ("agency", "stage", "high_impact"):
            for entry in LABEL_SETS[kind]:
                for template in DECLINED_AGAINST_TEMPLATES:
                    reply = data._j("DECLINED", template.format(V=entry["label"]))
                    total += 1
                    if key == "UA" and entry["label"] == "Department of Energy":
                        in_the_question.append(scoring.parse_judge(reply, item, answer, LABEL_SETS))
                        continue
                    assert scoring.parse_judge(reply, item, answer, LABEL_SETS) == U, (key, reply)
    assert total == 2 * 48 * len(DECLINED_AGAINST_TEMPLATES)
    # The one value left out: the agency the question itself names ("..., reported by the Department of
    # Energy?" asks for a budget). Repeating it is not an answer, so it does not refuse the verdict by itself;
    # the words around it still can. "Declines. Department of Energy." is read as DECLINED.
    assert in_the_question == [U, "DECLINED", U, U, U]
