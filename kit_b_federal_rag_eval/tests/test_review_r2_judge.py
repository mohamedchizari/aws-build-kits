"""Round 2 review, the judge parser: tests written to fail on the code as it stood after round 1.

B5   the parser trusted the verdict field against its own reason and against text it dropped
     (7 of the reader's 88 replies came back CORRECT or DECLINED without support).
M2   it lost 14 of 39 clear CORRECT replies in shapes the README did not name.

The rule since round 2: CORRECT or DECLINED comes back only when the reply states exactly one
verdict, nothing in the reason or in any other text of the reply contradicts it, and nothing
was left unread. A DECLINED verdict with a reason needs a reason that says the candidate
declined. INCORRECT can never flatter the system, so it is read more freely.
"""
from __future__ import annotations

import pytest

import judge_replies_r2
from kitlib import scoring

U = scoring.UNPARSEABLE

# --- B5: the reader's seven flattering replies ---------------------------------------------------------------

FLATTERING_IN_ROUND_2 = [
    '{"verdict": "CORRECT", "reason": "The candidate is not correct: it names DOE, the reference is EPA."}',
    '{"verdict": "CORRECT", "reason": "INCORRECT - the candidate names a different agency."}',
    '{"verdict": "CORRECT", "reason": "The candidate declines to answer."}',
    '{"verdict": "CORRECT", "reason": "ok"} Actually, on a second look the candidate names the wrong agency.',
    '{"verdict": "CORRECT", "reason": "ok"}\n{"note": "should be INCORRECT, the agency differs"}',
    '{"verdict": "DECLINED", "reason": "The candidate answered Department of Energy"}',
    'Not {"verdict": "CORRECT", "rea',
]


@pytest.mark.parametrize("reply", FLATTERING_IN_ROUND_2)
def test_a_verdict_its_own_reply_contradicts_is_unparseable(reply):
    assert scoring.parse_judge(reply) == U


# --- M2: the clear shapes the reader listed are read ---------------------------------------------------------

CLEAR_SHAPES = [
    ("Verdict: CORRECT\nReason: the candidate names the same agency.", "CORRECT"),      # a "Verdict:" line
    ("CORRECT - the candidate states the reference answer.", "CORRECT"),                # the word, a dash, a reason
    ('{"verdict": "CORRECT.", "reason": "matches"}', "CORRECT"),                        # a trailing period
    ('{"verdict": "CORRECT", "reason": "matches",}', "CORRECT"),                        # a trailing comma
    ("{'verdict': 'CORRECT', 'reason': 'matches'}", "CORRECT"),                         # single quotes
    ('{"Verdict": "CORRECT", "Reason": "matches"}', "CORRECT"),                         # a capitalised key
    ('The candidate answer is correct.\n{"verdict": "CORRECT", "reason": "matches"}', "CORRECT"),
    ('<thinking>The candidate is correct.</thinking>\n{"verdict": "CORRECT", "reason": "same"}', "CORRECT"),
    ("The verdict is CORRECT.", "CORRECT"),
    ('{"result": {"verdict": "CORRECT", "reason": "matches"}}', "CORRECT"),             # one level of nesting
    ('{"verdict": "CORRECT", "reason": "matches"}}', "CORRECT"),                        # a stray closing brace
    ('{{"verdict": "CORRECT", "reason": "matches"}}', "CORRECT"),
    ('JSON: {"verdict": "INCORRECT", "reason": "x"} (not CORRECT because the stage differs)', "INCORRECT"),
    ("Verdict: DECLINED\nReason: the candidate says it cannot answer.", "DECLINED"),
    ("DECLINED - the candidate declines.", "DECLINED"),
    ("verdict = incorrect", "INCORRECT"),
]


@pytest.mark.parametrize("reply,verdict", CLEAR_SHAPES)
def test_a_clear_reply_in_a_shape_the_reader_listed_is_read(reply, verdict):
    assert scoring.parse_judge(reply) == verdict


# --- the contradiction check, verdict by verdict ---------------------------------------------------------------

@pytest.mark.parametrize("reason", [
    "not the same agency", "the candidate isn't right", "wrong agency", "incorrect", "the candidate declined",
    "the candidate refuses", "it cannot answer", "the stage differs", "a different stage", "another agency",
    "no match", "mismatch", "partly right", "partially", "right except for the bureau", "right, but late",
    "however the bureau is off", "actually it is Pilot", "it fails to say", "the agency is missing",
    "false", "is it?", "it would be right", "right if abbreviations count", "unsure", "the opposite",
    "it contradicts the reference", "No, it contradicts the reference",
])
def test_correct_is_not_returned_when_the_reason_holds_a_contradicting_word(reason):
    for reply in ('{"verdict": "CORRECT", "reason": "%s"}' % reason,
                  '{"verdict": "CORRECT"}\n%s' % reason,
                  '%s\n{"verdict": "CORRECT", "reason": "same"}' % reason,
                  "Verdict: CORRECT\nReason: %s" % reason,
                  "CORRECT - %s" % reason,
                  '{"verdict": "CORRECT", "reason": "%s' % reason):          # cut off inside the reason
        assert scoring.parse_judge(reply) == U, reply


@pytest.mark.parametrize("reason", [
    "matches", "same agency", "The candidate states the reference answer.", "same fact, wording may differ",
    "Same agency, different wording.", "Same fact; the wording differs.", "", "ok",
    "The candidate states the reference answer and no fact that contradicts it.",
    "States the reference; no contradicting fact.", "It does not contradict the reference.",
    "The abbreviation is acceptable.", "probably the same",
])
def test_correct_is_returned_when_the_reason_supports_it(reason):
    for reply in ('{"verdict": "CORRECT", "reason": "%s"}' % reason,
                  "Verdict: CORRECT\nReason: %s" % reason):
        assert scoring.parse_judge(reply) == "CORRECT", reply


@pytest.mark.parametrize("reason", [
    "The candidate answered Department of Energy", "The candidate names the Department of State.",
    "Same fact as the reference.", "matches", "The candidate says the budget is 2 million dollars.",
    "The candidate is correct.", "wrong agency", "It declines, but then guesses Pilot.",
    "The candidate declines and names DOE.", "The candidate gives Pilot.", "declines?",
])
def test_declined_is_not_returned_unless_the_reason_says_the_candidate_declined(reason):
    for reply in ('{"verdict": "DECLINED", "reason": "%s"}' % reason,
                  "Verdict: DECLINED\nReason: %s" % reason,
                  "DECLINED - %s" % reason):
        assert scoring.parse_judge(reply) == U, reply


@pytest.mark.parametrize("reason", [
    "The candidate says it cannot answer.", "Candidate declines.", "no answer given", "declines",
    "The candidate does not answer the question.", "The candidate refuses and gives no answer.",
    "It says it has no information.", "The candidate didn't provide an answer.", "",
])
def test_declined_is_returned_when_the_reason_says_so_or_is_absent(reason):
    assert scoring.parse_judge('{"verdict": "DECLINED", "reason": "%s"}' % reason) == "DECLINED"
    assert scoring.parse_judge('{"verdict": "DECLINED"}') == "DECLINED"
    assert scoring.parse_judge("DECLINED") == "DECLINED"


def test_incorrect_is_read_unless_the_reply_also_says_the_candidate_is_correct_or_declined():
    assert scoring.parse_judge('{"verdict": "INCORRECT", "reason": "The candidate is correct."}') == U
    assert scoring.parse_judge('{"verdict": "INCORRECT", "reason": "The candidate declined."}') == U
    assert scoring.parse_judge('{"verdict": "INCORRECT", "reason": "the correct answer is Deployed"}') == "INCORRECT"
    assert scoring.parse_judge('{"verdict": "INCORRECT", "reason": "The candidate is correct on the agency '
                               'but adds a wrong bureau"}') == "INCORRECT"
    assert scoring.parse_judge('{"verdict": "INCORRECT", "reason": "the answer is not CORRECT"}') == "INCORRECT"


# --- nothing is dropped unread -------------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    '{"verdict": "CORRECT", "reason": "same"}\n{"verdict_final": "INCORRECT"}',
    '{"verdict": "CORRECT", "reason": "same"}\n{"override": true}',
    '{"verdict": "CORRECT", "reason": "same"}\n{"comment": "the agency is wrong"}',
    '{"verdict": "CORRECT", "reason": "same"} and then {"verdict": "INCORR',
    '{"verdict": "CORRECT", "correct": false}',
    '{"verdict": "CORRECT", "score": 0}',
    '{"verdict": "CORRECT", "verdict2": "INCORRECT"}',
    '{"verdict": "CORRECT", "reason": {"text": "the agency is different"}}',
    '{"verdict": "CORRECT", "reason": ["not", "the", "same"]}',
    '{"result": {"verdict": "CORRECT"}, "comment": "should be INCORRECT"}',
    '[{"verdict": "CORRECT"}, {"verdict": "DECLINED"}]',
    '{"verdict": "CORRECT", "verdict": "CORRECT"}',
    '{"verdict": "CORRECT", "Verdict": "INCORRECT"}',
    '{"verdict": "CORRECT", "reason": "matches",}\n{"verdict": "INCORRECT",}',
    "{'verdict': 'CORRECT', 'reason': 'not the same'}",
    "Verdict: CORRECT\nVerdict: INCORRECT",
    "CORRECT\n\n(The candidate is wrong about the bureau.)",
])
def test_text_or_objects_next_to_the_verdict_are_read_not_dropped(reply):
    assert scoring.parse_judge(reply) == U


@pytest.mark.parametrize("reply", [
    "The candidate is correct.", "The candidate declined.", "The answer is correct.", "PARTIALLY CORRECT",
    "not correct", "NOT CORRECT", "Correct me if I am wrong.", "CORRECT INCORRECT", "CORRECT?", "CORRECTED",
    "verdict CORRECT", "Declined to give a verdict.", '{"verdict": ["CORRECT"]}', '{"verdict": true}',
    '{"verdict": "NOT CORRECT"}', '{"verdict": "CORRECT/INCORRECT"}', '{"grade": "CORRECT"}',
])
def test_everything_else_stays_unparseable(reply):
    assert scoring.parse_judge(reply) == U


def test_the_words_the_check_looks_for_are_written_out():
    for word in ("not", "wrong", "incorrect", "declin"):
        assert any(word in pattern for pattern in scoring.CONTRADICTS_CORRECT), word
    assert scoring.CONTRADICTS_DECLINED and scoring.SAYS_DECLINED


# --- the fixer's own judge replies, labelled by hand before the new parser existed -----------------------------

def test_the_fixers_own_judge_replies_are_never_read_flatteringly():
    names = {"C": "CORRECT", "I": "INCORRECT", "D": "DECLINED", "U": U}
    flattering = []
    for reply, label in judge_replies_r2.REPLIES:
        got = scoring.parse_judge(reply)
        if got in ("CORRECT", "DECLINED") and got != names[label]:
            flattering.append((reply, label, got))
    assert len(judge_replies_r2.REPLIES) >= 80
    assert flattering == []
