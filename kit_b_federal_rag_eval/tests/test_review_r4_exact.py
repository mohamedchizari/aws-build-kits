"""Round 4 (fourth review, reader B), exact match: MINOR 4, 5, 9 and 11. Tests written to fail on the code as reviewed.

MINOR 4   one value written twice was "more than one value": "EPA (Environmental Protection Agency)", the name in
          bold before its abbreviation, a headline line followed by the sentence. Each lost 40 to 100 of the 100
          real right answers of the rehearsal.
MINOR 5   three answers built only from list words got credit: a question after a semicolon, and another use case
          whose name is made of list words ('named "AI Use Case Inventory"').
MINOR 9   a comma or a dash between "not" and "High-impact" was read as the value "Not High-impact".
MINOR 11  plain wording that lost every one of the 100 real right answers: "Based on the passages, ...", "Sure. ...",
          "... as of the 2025 inventory.", "... This is stated in passage 1.", an exclamation mark.

What the fixer measured with the reader's own sets is in README section 8. Here: each shape, and with it the
same answer holding ANOTHER value of the field, which must never earn credit.
"""
from __future__ import annotations

import random

import pytest

from kitlib import scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, STAGE_LABELS
from test_review_r2_exact import ABBREVIATION, AGENCIES, LABEL_SETS, NAME, REPORTER, make_item, score

EPA, DOE, VA, TREASURY = ("Environmental Protection Agency", "Department of Energy", "Department of Veterans Affairs",
                          "Department of the Treasury")


def answers_for(kind: str, value: str) -> list[str]:
    """The reader's shapes around one value, as a model would write them for the test question."""
    abbreviation = ABBREVIATION.get(value, "")
    if kind == "agency":
        sentence = f'The {value} ({abbreviation}) reported the AI use case named "{NAME}".'
        extra = [f"{abbreviation} ({value})", f"**{value}** ({abbreviation})", f"The agency is **{value}** ({abbreviation}).",
                 f'{abbreviation} ({value}) reported the AI use case named "{NAME}".']
    elif kind == "stage":
        sentence = f'The stage of development recorded for "{NAME}" is {value}.'
        extra = [f'The use case "{NAME}" has a stage of development of {value}.', f"The AI use case is classified as {value}."]
    else:
        sentence = f'The high-impact determination recorded for "{NAME}" is {value}.'
        extra = [f'The use case "{NAME}", reported by the {REPORTER}, has a high-impact determination of {value}.',
                 f"{value}. The determination is {value}."]
    return extra + [
        value + ".\n\n" + sentence,                                   # a headline line, then the sentence
        f"{value}, {value}.",
        "Based on the passages, " + sentence[0].lower() + sentence[1:],
        "Based on the inventory, " + sentence[0].lower() + sentence[1:],
        "Sure. " + sentence,
        sentence + " This is stated in passage 1.",
        sentence[:-1] + " as of the 2025 inventory.",
        sentence[:-1] + ", as stated in the passage.",
        sentence[:-1] + ", per the passages.",
        f"{value}, according to passage 2.",
        sentence[:-1] + "!",
        f"{value}!",
    ]


CASES = [("agency", EPA), ("agency", DOE), ("agency", VA), ("agency", TREASURY), ("stage", "Deployed"),
         ("stage", "Pre-deployment"), ("high_impact", "High-impact"), ("high_impact", "Not High-impact"),
         ("high_impact", "Presumed High-Impact, but Not High-impact")]


@pytest.mark.parametrize("kind,value", CASES)
def test_the_plain_shapes_the_reader_listed_earn_credit(kind, value):
    for answer in answers_for(kind, value):
        result = score(kind, value, answer)
        assert (result["exact"], result["note"]) == (True, "match"), (answer, result)
        assert result["asserted"] == [value]


@pytest.mark.parametrize("kind,value", CASES)
def test_the_same_shapes_around_another_value_never_earn_credit(kind, value):
    labels = [name for name, _ in AGENCIES] if kind == "agency" else STAGE_LABELS if kind == "stage" else HIGH_IMPACT_LABELS
    for other in labels:
        if other == value:
            continue
        for answer in answers_for(kind, other):
            result = score(kind, value, answer)
            assert result["exact"] is False, (answer, result)
            assert other in result["found"] or result["unclear"], (answer, result)


def test_one_value_in_two_places_is_one_value_and_two_values_are_still_two():
    assert score("agency", EPA, "EPA (Environmental Protection Agency)")["note"] == "match"
    assert score("stage", "Deployed", "Deployed.\n\nThe stage of development is Deployed.")["found"] == ["Deployed"]
    for answer in ("Deployed. It was Pilot.", "Deployed, Pilot.", "Deployed (Deployed, not Retired)", "Pilot.\n\nDeployed."):
        assert score("stage", "Deployed", answer)["exact"] is False, answer
    assert score("stage", "Deployed", "Deployed, Pilot.")["note"] == "unclear_more_than_one_value"
    twice_wrong = score("stage", "Deployed", "Pilot.\n\nThe stage of development is Pilot.")
    assert (twice_wrong["exact"], twice_wrong["note"], twice_wrong["asserted"]) == (False, "different_value", ["Pilot"])
    # "not High-impact" is the value Not High-impact; with "High-impact" next to it that is two values
    assert score("high_impact", "Not High-impact", "Not High-impact, High-impact")["note"] == "unclear_more_than_one_value"
    # the same value twice does not make a question or a negation readable
    assert score("stage", "Deployed", "Is it Deployed. Deployed")["note"] == "unclear_reads_as_a_question"
    assert score("stage", "Deployed", "Deployed. Not Deployed.")["note"] == "unclear_words_outside_the_filler_list"


def test_one_value_in_more_than_three_places_is_a_model_repeating_itself():
    """Twice is a headline and its sentence; "Deployed, Deployed, Deployed." is in the kit's own hand-labelled set
    as an answer a person accepts. More often is not an answer written down once: the right sentence 400 times
    (the round 4 reader's own table harness, run T08) stays unclear, as it was before round 4."""
    sentence = "The stage of development is Deployed."
    for times in (2, 3):
        assert score("stage", "Deployed", " ".join([sentence] * times))["note"] == "match"
    for times in (4, 5, 400):
        got = score("stage", "Deployed", " ".join([sentence] * times))
        assert (got["exact"], got["note"], got["found"]) == (False, "unclear_one_value_written_more_than_three_times",
                                                             ["Deployed"])
    # the one answer of the reader's 60,000 random ones that got credit with "was" in it while this rule was missing
    got = score("high_impact", "High-impact", "High-impact; High-impact` determination; High-impact was_determined to be "
                + chr(0x2014) + " High-impact; ")
    assert (got["exact"], got["note"], got["unread"]) == (False, "unclear_words_outside_the_filler_list", "was _")
    # the same for another value: four times is unclear, as it was before round 4 (up to three times: "another value")
    assert score("stage", "Deployed", "Pilot. Pilot. Pilot.")["note"] == "different_value"
    assert score("stage", "Deployed", "Pilot. Pilot. Pilot. Pilot.")["note"] == "unclear_one_value_written_more_than_three_times"


def test_two_words_run_together_with_an_underscore_are_not_a_phrase_of_the_list():
    """ "was determined to be" is on the list for a high-impact question, "was" alone is not. The words of a phrase
    stand apart: "was_determined" is one string, and the underscore is shown as the thing that could not be read."""
    assert score("high_impact", "High-impact", "It was determined to be High-impact.")["note"] == "match"
    assert score("high_impact", "High-impact", "It _was determined to be_ High-impact.")["note"] == "match"
    got = score("high_impact", "High-impact", "It was_determined to be High-impact.")
    assert (got["exact"], got["note"], got["unread"]) == (False, "unclear_words_outside_the_filler_list", "was _")
    assert score("stage", "Deployed", "according_to the inventory it is Deployed")["exact"] is False
    assert score("stage", "Deployed", "According to _the inventory_ it is _Deployed_.")["note"] == "match"


def test_the_abbreviation_in_front_of_its_own_name_only():
    assert score("agency", VA, "VA (Department of Veterans Affairs)")["exact"] is True
    assert score("agency", VA, "VA")["exact"] is False                           # alone it is a state code, as before
    assert score("agency", VA, "DOE (Department of Veterans Affairs)")["exact"] is False
    assert score("agency", DOE, "VA (Department of Energy)")["exact"] is False
    assert score("agency", TREASURY, "Department of Treasury")["exact"] is True
    assert score("agency", "Department of the Interior", "The Department of Interior (DOI)")["exact"] is True
    assert score("agency", DOE, "Department of Treasury")["note"] == "different_value"


# --- MINOR 5 -------------------------------------------------------------------------------------------------------

def test_a_question_after_a_semicolon_is_a_question():
    result = score("agency", EPA, "The agency was reported; is the Environmental Protection Agency named")
    assert (result["exact"], result["note"]) == (False, "unclear_reads_as_a_question")
    assert score("stage", "Deployed", "It is recorded; is it Deployed")["exact"] is False
    assert score("stage", "Deployed", "Deployed; the stage is Deployed.")["exact"] is True     # no question in it


def test_another_use_case_in_quotation_marks_is_not_the_one_asked_about():
    answer = 'The Environmental Protection Agency reported the AI use case named "AI Use Case Inventory".'
    result = score("agency", EPA, answer)
    assert (result["exact"], result["note"]) == (False, "unclear_quoted_text_that_is_not_the_use_case_name")
    curly = answer.replace('"AI', chr(0x201C) + "AI").replace('Inventory"', "Inventory" + chr(0x201D))
    assert score("agency", EPA, curly)["exact"] is False
    # the question's own name, a value and the name of the field in quotation marks are read as before
    for fine in (f'The Environmental Protection Agency reported the AI use case named "{NAME}".',
                 f'The Environmental Protection Agency (EPA) reported the AI use case named "{NAME}."',
                 'The agency is "Environmental Protection Agency".', '"Environmental Protection Agency (EPA)"'):
        assert score("agency", EPA, fine)["exact"] is True, fine
    assert score("stage", "Deployed", 'The "stage of development" is "Deployed".')["exact"] is True


def test_the_answer_built_from_list_words_that_is_still_credited():
    """The third of the reader's three: an inverted question after a COMMA. A comma cannot start a question here,
    because '..., reported by the Department of Energy, is Deployed.' is how a right answer is written. README
    section 2, item 8 names this limit; when it is caught, correct the README."""
    assert score("agency", EPA, "It was reported, is the answer the Environmental Protection Agency")["exact"] is True


# --- MINOR 9 -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answer", ["It is not, High-impact.", "It is not - High-impact.",
                                    "It is not " + chr(0x2014) + " High-impact.", "Not; High-impact", "not,High-impact"])
def test_not_and_high_impact_with_something_between_them_is_not_the_value(answer):
    result = score("high_impact", "Not High-impact", answer)
    assert result["exact"] is False and "Not High-impact" not in result["found"]


def test_between_the_words_of_a_value_only_what_the_value_has_there():
    assert score("high_impact", "Not High-impact", "Not High impact")["exact"] is True          # a space for the hyphen
    assert score("high_impact", "Not High-impact", "not high - impact")["exact"] is True
    assert score("stage", "Pre-deployment", "Pre deployment")["exact"] is True
    assert score("high_impact", "Presumed High-Impact, but Not High-impact",
                 "Presumed High-Impact but Not High-impact")["exact"] is True                   # the comma left out
    assert score("agency", DOE, "Department, of Energy")["exact"] is False                      # a comma the name does not have
    assert score("agency", DOE, "Department-of-Energy")["exact"] is False
    assert scoring._value_gaps("Presumed High-Impact, but Not High-impact") == (
        "space", "hyphen", "comma", "space", "space", "hyphen")


# --- MINOR 11 ------------------------------------------------------------------------------------------------------

def test_the_new_phrases_are_a_list_of_their_own_and_hold_no_negation_hedge_or_tense():
    assert sum(len(phrases) for phrases in scoring.FILLER_PHRASES.values()) == 53          # as rounds 2 and 3 reviewed it
    lead_in = scoring.LEAD_IN_PHRASES["common"]
    assert len(lead_in) == 37 and list(scoring.LEAD_IN_PHRASES) == ["common"]
    assert all(len(phrase.split()) >= 2 or phrase == "sure" for phrase in lead_in)        # no single noun or verb
    assert score("agency", DOE, "The passage is a Department of Energy record.")["exact"] is False
    words = {word for phrase in lead_in for word in phrase.split()}
    assert not words & set("not no never was were will would may might could probably likely currently formerly "
                           "previously instead except unless or but only if".split())
    assert "of" not in lead_in and "a" not in lead_in and "as" not in lead_in             # only inside a phrase


def test_an_exclamation_mark_only_where_a_period_could_stand():
    for answer in ("Deployed!", 'The stage is "Deployed"!', "**Deployed**!", f'The stage of development recorded for "{NAME}!" is Deployed.'):
        assert score("stage", "Deployed", answer)["exact"] is True, answer
    for answer in ("Deployed !", "! Deployed", "!Deployed", "Deployed != Pilot", "Deployed!?", "Deployed!!", "Not! Deployed"):
        assert score("stage", "Deployed", answer)["exact"] is False, answer


def test_the_number_of_a_passage_is_a_citation_and_any_other_number_is_not():
    assert score("stage", "Deployed", "Deployed, according to passage 1.")["exact"] is True
    assert score("stage", "Deployed", "According to document 3, the stage is Deployed.")["exact"] is True
    assert score("stage", "Deployed", "Deployed in 2019.")["exact"] is False
    assert score("stage", "Deployed", "Deployed, 1 of 3.")["exact"] is False
    assert score("stage", "Deployed", "Deployed as of May 2025.")["exact"] is False            # a date is still unclear


@pytest.mark.parametrize("kind,value,answer", [
    ("stage", "Deployed", "Meadow quartz planner is currently in the Deployed stage."),        # "currently"
    ("agency", EPA, "The Environmental Protection Agency, or EPA, reported it."),             # "or"
    ("agency", EPA, "Environmental Protection\nAgency"),                                       # a line break inside the value
    ("agency", EPA, "It is probably the Environmental Protection Agency."),                    # a hedge
    ("agency", EPA, "Environmental Protection Agency, Office of Mission Support"),             # the bureau
    ("stage", "Deployed", "In production (Deployed)."),
    ("high_impact", "Not High-impact", "It isn't high-impact."),
])
def test_plain_wording_that_is_still_lost(kind, value, answer):
    """README section 2, item 8 lists these with the others. Each is unclear: counted, never correct."""
    result = score(kind, value, answer)
    assert (result["exact"], result["unclear"]) == (False, True)


def test_no_answer_with_a_changing_word_or_another_value_is_credited_whatever_stands_around_it():
    """By construction, as the reader's 60,000: random answers from the expected value, other values, every phrase
    of both lists, the use case name and words that change the meaning. Seeded."""
    rng = random.Random(4)
    changers = ("not no never isn't probably maybe formerly previously will would should was were instead except "
                "unless neither nor none false wrong unknown hardly almost originally once former other another "
                "different currently soon later").split()
    fill = ([phrase for phrases in scoring.FILLER_PHRASES.values() for phrase in phrases]
            + list(scoring.LEAD_IN_PHRASES["common"]))
    marks = [" ", " ", " ", ", ", ". ", "; ", ": ", " - ", " (", ") ", ' "', '" ', "\n", " * ", "! ", "!", "**", "passage 1 "]
    credited = 0
    for _ in range(6000):
        kind, value = rng.choice(CASES)
        labels = [name for name, _ in AGENCIES] if kind == "agency" else STAGE_LABELS if kind == "stage" else HIGH_IMPACT_LABELS
        parts, changed, other = [], False, False
        for _ in range(rng.randint(1, 8)):
            roll = rng.random()
            if roll < 0.32:
                parts.append(value)
            elif roll < 0.40:
                pick = rng.choice(labels)
                parts.append(pick)
                other = other or pick != value
            elif roll < 0.76:
                parts.append(rng.choice(fill))
            elif roll < 0.81:
                parts.append('"' + NAME + '"')
            else:
                word = rng.choice(changers)
                parts.append(word)
                # "was" is on the list for an agency ("was reported by") and, in front of "determined to be", for
                # a high-impact determination: there it is not counted as a changer
                changed = changed or not (word == "was" and kind in ("agency", "high_impact"))
        text = "".join(part + rng.choice(marks) for part in parts)
        result = scoring.score_exact(make_item(kind, value), text, LABEL_SETS)
        credited += result["exact"]
        if result["exact"] and (changed or other) and kind != "high_impact":
            raise AssertionError((kind, value, text, result))
        if result["exact"] and kind == "high_impact":
            # the three values share their words ("not" + "High-impact" IS a value): what was read must be the
            # expected value alone, and no changer but that "not" (and "was", see above)
            assert set(result["found"]) == {value}, (value, text, result)
            assert not (set(parts) & (set(changers) - {"not", "was"})), (value, text, result)
    assert credited > 300                                             # the check is not empty
