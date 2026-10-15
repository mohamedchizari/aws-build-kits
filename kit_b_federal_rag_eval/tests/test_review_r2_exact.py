"""Round 2 review, exact match: tests written to fail on the code as it stood after round 1.

B2      exact match gave credit to wrong answers of kinds the README did not name (38 of the
        reader's 250 hand-labelled answers), while three sentences called it strict.
M1      it lost credit on kinds the README did not list (agency short names and others).
MINOR   the refusal check stripped every character that is not a-z or 0-9.

The rule since round 2 is an allow-list. An answer earns credit only if, once the question's
own words (the use case name, the agency it names, the question itself when repeated), the
field-name phrases and exactly one accepted spelling of the expected value are taken out,
every word left is on a short written-out list. Anything else is "unclear": not correct in
the exact column, and counted in a row of its own.

The answers in FALSE_CREDIT_IN_ROUND_2 are the reader's, word for word, except that use case
names from the inventory were replaced by made-up ones (the kit ships no inventory rows
beyond its five-row fixture).
"""
from __future__ import annotations

import json
import re

import pytest

import adversarial_r2
from conftest import KIT_DIR
from kitlib import scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, NO_ANSWER, STAGE_LABELS, TEMPLATES, simple_label_set

AGENCIES = json.loads((KIT_DIR / "tests" / "fixtures" / "agencies_41.json").read_text(encoding="utf-8"))["agencies"]
ABBREVIATION = dict(AGENCIES)
LABEL_SETS = {
    "agency": [{"label": name, "aliases": [{"text": abbr, "case_sensitive": True}]} for name, abbr in AGENCIES],
    "stage": simple_label_set(STAGE_LABELS),
    "high_impact": simple_label_set(HIGH_IMPACT_LABELS),
}
NAME = "Grid load forecasting assistant"
REPORTER = "Department of Justice"
D = scoring.DECLINE_SENTENCE


def make_item(kind: str, expected: str, name: str = NAME, reporter: str = REPORTER) -> dict:
    return {"id": "q-001", "type": kind, "answerable": True,
            "question": TEMPLATES[kind].format(name=name, agency_name=reporter), "use_case_name": name,
            "expected_answer": expected, "label_set": kind, "accepted_aliases": [], "source_doc_id": "uc-0001"}


def unanswerable() -> dict:
    return {"id": "q-101", "type": "unanswerable_heldout", "answerable": False,
            "question": TEMPLATES["agency"].format(name=NAME), "use_case_name": NAME,
            "expected_answer": NO_ANSWER, "label_set": None, "accepted_aliases": [], "source_doc_id": None}


def score(kind: str, expected: str, answer: str, **kw) -> dict:
    return scoring.score_exact(make_item(kind, expected, **kw), answer, LABEL_SETS)


# --- B2: the reader's 36 answerable false credits, each pinned to "not correct" --------------------------------

EPA, DOE, STATE, VA = ("Environmental Protection Agency", "Department of Energy", "Department of State",
                       "Department of Veterans Affairs")
FALSE_CREDIT_IN_ROUND_2 = [
    # same-clause negation or doubt outside the old word lists
    ("agency", EPA, "The Department of Defense reported it, rather than the Environmental Protection Agency."),
    ("agency", EPA, "Instead of the Environmental Protection Agency, the record names the Department of Defense."),
    ("agency", EPA, "The use case was reported by an agency other than the Environmental Protection Agency."),
    ("agency", EPA, "It is false that the Environmental Protection Agency reported it."),
    ("agency", EPA, "Unlike the Environmental Protection Agency, the agency that reported this tool is a defense agency."),
    ("agency", EPA, "There is insufficient information to confirm that the Environmental Protection Agency reported it."),
    ("agency", DOE, "This use case has yet to be reported by the Department of Energy."),
    ("stage", "Deployed", "It has yet to be deployed."),
    ("stage", "Deployed", "Hard to say whether it is Deployed."),
    ("stage", "Deployed", "Formerly Deployed, the use case is now listed under another status."),
    ("high_impact", "High-impact", "The agency has yet to decide whether it is high-impact."),
    # question form
    ("agency", EPA, "Is it the Environmental Protection Agency? The passages do not say."),
    ("stage", "Deployed", "Is it Deployed? No."),
    ("stage", "Deployed", "Deployed? The passages do not say."),
    ("high_impact", "High-impact", "Is it high-impact? No."),
    ("high_impact", "High-impact", "High-impact? No."),
    # future tense
    ("stage", "Deployed", "It will be deployed in 2026."),
    ("stage", "Deployed", "It is planned to be deployed next year; the current stage is Initiation."),
    ("stage", "Retired", "The use case will be retired next year; it is currently in use."),
    # an upper-case abbreviation that is also a word or a state code
    ("agency", STATE, "PLEASE STATE THE QUESTION AGAIN. NO AGENCY FOUND."),
    ("agency", VA, "It was reported by the Defense Health Agency in Falls Church, VA."),
    # the two kinds the README already named: a negation in another clause, a value word in passing
    ("stage", "Deployed", "It is not, as far as I can tell, Deployed."),
    ("stage", "Deployed", "It is not (yet) Deployed."),
    ("stage", "Deployed", "The tool was deployed by the agency, but its stage is not recorded."),
    ("stage", "Deployed", "The stage is Operation and Maintenance; the model is deployed on a USGS server."),
    ("stage", "Deployed", "I can only find that the agency deployed maps for the Western US; no stage is given."),
    ("stage", "Pilot", "The stage is not recorded; the description mentions a pilot at two medical centers."),
    ("stage", "Pilot", 'The stage of development is "Initiated". A pilot site has been selected.'),
    ("agency", DOE, "The Department of Defense reported it; the Department of Energy is only named as a partner."),
    ("agency", DOE, "The passages list use cases from the Department of Energy, but not this one."),
    ("high_impact", "High-impact", "It is categorized as high-impact by default, but the agency determined it is not."),
    # the value given for another use case
    ("agency", EPA, 'The passages do not mention the Grid load forecasting assistant. The closest record, '
                    '"Comment letter drafting aid", was reported by the Environmental Protection Agency.'),
    ("agency", EPA, "The passages list several use cases:\n1. Comment letter drafting aid - Environmental "
                    "Protection Agency\n2. Records lookup helper - Environmental Protection Agency"),
    ("agency", DOE, "I cannot determine which agency reported it. Passage [1] is a Department of Energy record "
                    "for a different use case."),
    ("stage", "Deployed", 'The passages do not include this use case. A similar use case, "Irrigation '
                          'estimate mapper", is Deployed.'),
    ("high_impact", "High-impact", "The record does not give one. Other use cases in the passages are high-impact."),
]


def test_the_list_holds_the_36_answerable_false_credits_the_reader_found():
    assert len(FALSE_CREDIT_IN_ROUND_2) == 36


@pytest.mark.parametrize("kind,expected,answer", FALSE_CREDIT_IN_ROUND_2)
def test_a_wrong_answer_the_reader_found_credited_is_no_longer_credited(kind, expected, answer):
    result = score(kind, expected, answer)
    assert result["exact"] is False, result
    assert result["unclear"] is True and result["note"].startswith("unclear"), result


# --- MINOR: a refusal is the fixed sentence, with no character stripped ----------------------------------------

@pytest.mark.parametrize("answer", [
    D + " 能源部",                 # the reader's two refusal-column false credits
    D + " $",
    D + " \u200bDOE", D + " 🙂", D + " -", D + "..", D[:-1] + "!", "- " + D, '"' + D + '"',
    D.lower(), D.upper(), D.replace(" ", "\u00a0"),
])
def test_the_refusal_sentence_with_anything_added_or_changed_is_not_a_refusal(answer):
    assert scoring.is_decline(answer) is False
    result = scoring.score_exact(unanswerable(), answer, LABEL_SETS)
    assert (result["exact"], result["declined"]) == (False, False)


@pytest.mark.parametrize("answer", [D, D[:-1], "  " + D + "\n", "\t" + D[:-1] + "  "])
def test_only_whitespace_around_it_and_one_trailing_period_are_trimmed(answer):
    assert scoring.is_decline(answer) is True
    assert scoring.score_exact(unanswerable(), answer, LABEL_SETS)["exact"] is True


# --- the filler list: written out in one place, short, and free of the words that change a meaning ---------------

MEANING_CHANGERS = """not no non never nor neither none cannot without unable unknown isn't wasn't hasn't
    may might maybe perhaps possibly probably likely presumably apparently seems appears guess think believe
    will would shall should could can to be been being was were had formerly previously once until soon yet
    still now currently planned rather than instead other another unlike except but however although though
    if unless whether or and either both also only just almost nearly partly partially hardly barely
    false wrong different similar same of from by with""".split()


def all_filler_phrases(kind: str) -> set[str]:
    return set(scoring.FILLER_PHRASES["common"]) | set(scoring.FILLER_PHRASES[kind])


def test_the_filler_list_is_short_and_is_one_object():
    assert set(scoring.FILLER_PHRASES) == {"common", "agency", "stage", "high_impact"}
    total = sum(len(phrases) for phrases in scoring.FILLER_PHRASES.values())
    assert total <= 70, total
    for phrases in scoring.FILLER_PHRASES.values():
        assert len(phrases) == len(set(phrases))
        for phrase in phrases:
            assert phrase == " ".join(phrase.split()) == phrase.lower()


@pytest.mark.parametrize("kind", ["agency", "stage", "high_impact"])
def test_no_single_filler_word_is_a_negation_a_hedge_a_tense_shift_or_a_comparison(kind):
    singles = {phrase for phrase in all_filler_phrases(kind) if " " not in phrase}
    allowed_exceptions = {"agency": {"was"}}.get(kind, set())      # "was reported by": the report is in the past
    assert (singles & set(MEANING_CHANGERS)) - allowed_exceptions == set()


def test_every_filler_phrase_on_its_own_is_harmless():
    """Each phrase, put before and after the expected value, still reads as that value and nothing else."""
    for kind, expected in (("agency", DOE), ("stage", "Deployed"), ("high_impact", "High-impact")):
        for phrase in sorted(all_filler_phrases(kind)):
            for answer in (f"{phrase} {expected}", f"{expected} {phrase}"):
                result = score(kind, expected, answer)
                if result["exact"]:
                    continue
                # A filler phrase may fail for three reasons only: it opens a question ("is Deployed"), it is
                # a field name that swallows the words of the value ("High-impact determination"), or it
                # makes the value read as a verb with an object ("Deployed the", "Deployed it").
                if any(name in scoring.normalise(answer) for name in scoring.FIELD_NAME_PHRASES[kind]):
                    assert result["note"] == "unclear_no_value_found", (answer, result)
                elif answer.startswith(expected) and phrase.split()[0] in scoring.OBJECTS_AFTER_A_VERB:
                    assert result["note"] == "unclear_value_used_as_a_verb", (answer, result)
                else:
                    assert result["note"] == "unclear_reads_as_a_question", (answer, result)


@pytest.mark.parametrize("word", MEANING_CHANGERS)
def test_one_meaning_changing_word_next_to_the_value_makes_the_answer_unclear(word):
    for kind, expected in (("agency", DOE), ("stage", "Deployed"), ("high_impact", "High-impact")):
        if (kind, word) == ("agency", "was"):
            continue
        for answer in (f"{word} {expected}", f"It is {word} {expected}.", f"{expected} {word}"):
            result = score(kind, expected, answer)
            if kind == "high_impact" and word == "not":
                assert result["exact"] is False                 # "not High-impact" is another value of the field
                continue
            assert (result["exact"], result["unclear"]) == (False, True), (answer, result)


@pytest.mark.parametrize("mark", list("?!/\\<>=~+&%$#@^|{}[]") + ["≠", "✗", "❌", "→", "¿"])
def test_a_character_outside_the_allowed_punctuation_makes_the_answer_unclear(mark):
    # Round 4: "Deployed!" is read like "Deployed." (tests/test_review_r4_exact.py). An exclamation mark anywhere
    # but directly at the end of a word is still outside the list.
    forms = (f"Deployed {mark}", f"{mark} Deployed", f"{mark}Deployed") + (() if mark == "!" else (f"Deployed{mark}",))
    for answer in forms:
        result = score("stage", "Deployed", answer)
        assert (result["exact"], result["unclear"]) == (False, True), (answer, result)


def test_the_allowed_punctuation_is_written_out():
    assert set(scoring.ALLOWED_PUNCTUATION) >= set(".,;:\"'()*_`-")
    assert not set(scoring.ALLOWED_PUNCTUATION) & set("?!/\\<>=~+&%$#@^|{}[]")


# --- the accepted templates: a gold sentence in each scores correct, a wrong value never does ------------------

ACCEPTED_TEMPLATES = {
    "agency": [
        "{v}",
        "{v}.",
        "The {v}",
        "{v} ({abbr})",
        "Agency: {v} ({abbr})",                                           # the document line itself
        'The AI use case named "{name}" was reported by the {v}.',
        'The {v} ({abbr}) reported the AI use case named "{name}".',
        "It was reported by the {v}.",
        "According to the passages, it was reported by the {v} ({abbr}).",
        "The agency is the {v}.",
        "The U.S. {v} reported it.",
        "{q} The {v}.",                                                   # the question repeated, then the answer
        'The federal agency that reported the AI use case named "{name}" in the 2025 federal AI use case '
        "inventory is the {v}.",
        '{{"agency": "{v}"}}',
    ],
    "stage": [
        "{v}",
        "{v}.",
        "It is {v}.",
        'The stage of development recorded for the AI use case named "{name}", reported by the {ag}, is {v}.',
        'The stage of development is "{v}".',
        "Stage of development: {v}",                                      # the document line itself
        "It is recorded as {v}.",
        "It is in the {v} stage.",
        "The use case is in the {v} stage of development.",
        "**{v}**",
        "{q} {v}.",
        "The stage is {v}, according to the record.",
        "According to passage [1] (document uc-0001), the stage of development is {v}.",
        '{{"stage_of_development": "{v}"}}',
    ],
    "high_impact": [
        "{v}",
        "{v}.",
        'The high-impact determination recorded for the AI use case named "{name}", reported by the {ag}, is {v}.',
        'The high-impact determination is "{v}".',
        "High-impact determination: {v}",                                 # the document line itself
        "It is recorded as {v}.",
        'The determination recorded is "{v}".',
        "The high-impact determination for this use case is {v}.",
        "Its high-impact status is {v}.",
        "High-impact status: {v}",
        "{q} {v}.",
        "{q}\nThe high-impact determination is {v}.",
        "The use case is determined to be {v}.",
        '{{"high_impact_determination": "{v}"}}',
    ],
}


def template_cases(kind: str):
    values = [name for name, _ in AGENCIES] if kind == "agency" else [e["label"] for e in LABEL_SETS[kind]]
    out = []
    for position, value in enumerate(values):
        item = make_item(kind, value)
        out.append((item, {"v": value, "other": values[(position + 1) % len(values)], "name": NAME,
                           "ag": REPORTER, "q": item["question"], "abbr": ABBREVIATION.get(value, "")}))
    return out


@pytest.mark.parametrize("kind,template", [(k, t) for k, ts in ACCEPTED_TEMPLATES.items() for t in ts])
def test_a_gold_sentence_in_an_accepted_template_scores_correct_for_every_value(kind, template):
    wrong = []
    for item, fill in template_cases(kind):
        result = scoring.score_exact(item, template.format(**fill), LABEL_SETS)
        if not (result["exact"] and result["note"] == "match" and result["asserted"] == [fill["v"]]):
            wrong.append((fill["v"], result["note"], result.get("unread")))
    assert wrong == []


@pytest.mark.parametrize("kind,template", [(k, t) for k, ts in ACCEPTED_TEMPLATES.items() for t in ts])
def test_the_same_sentence_with_another_value_never_scores_correct(kind, template):
    for item, fill in template_cases(kind):
        other = dict(fill, v=fill["other"], abbr=ABBREVIATION.get(fill["other"], ""))
        result = scoring.score_exact(item, template.format(**other), LABEL_SETS)
        assert result["exact"] is False, (fill["v"], template)
        assert result["note"] == "different_value" and result["unclear"] is False, (fill["v"], result)


# --- M1: agency short names, and the abbreviations that cannot stand alone -------------------------------------

@pytest.mark.parametrize("expected,answer", [
    ("Department of the Treasury", "The Treasury Department."),
    ("Department of State", "The State Department."),
    ("Department of Veterans Affairs", "Veterans Affairs"),
    ("Department of Energy", "Dept. of Energy"),
    ("Department of Energy", "The U.S. Energy Department."),
    ("Department of Health and Human Services", "Health and Human Services"),
    ("Department of Homeland Security", "Homeland Security"),
    ("Department of the Interior", "Dept. of the Interior"),
    ("Department of the Interior", "The Interior Department"),
])
def test_an_agency_short_name_the_reader_listed_is_accepted(expected, answer):
    result = score("agency", expected, answer)
    assert result["exact"] and result["asserted"] == [expected], result


@pytest.mark.parametrize("expected,answer", [
    ("Department of Energy", "Energy"), ("Department of the Treasury", "Treasury"),
    ("Department of State", "State"), ("Department of Education", "Education"),
])
def test_a_one_word_short_name_is_an_ordinary_word_and_is_not_accepted(expected, answer):
    result = score("agency", expected, answer)
    assert (result["exact"], result["unclear"]) == (False, True)


def test_the_short_names_collide_with_no_other_agency_name_in_the_whole_csv():
    """Every agency of the CSV at the pinned commit, not only the 31 a question asks about."""
    names, dropped = scoring.agency_short_names(LABEL_SETS["agency"])
    assert len(LABEL_SETS["agency"]) == 41 and dropped == []
    words = {label: tuple(scoring.normalise(label).split()) for label, _ in AGENCIES}
    seen: dict = {}
    count = 0
    for label, short_names in names.items():
        for short in short_names:
            count += 1
            tokens = tuple(scoring.normalise(short).split())
            assert len(tokens) >= 2, short                                   # never one ordinary word
            assert tokens not in seen, (short, seen.get(tokens))             # no two agencies share one
            seen[tokens] = label
            for other, other_words in words.items():
                if other == label:
                    continue
                windows = {other_words[i:i + len(tokens)] for i in range(len(other_words))}
                assert tokens not in windows, f"{short!r} of {label} is inside {other}"
    assert count == 14 * 2 + 4          # 14 departments: "X Department", "Dept of X"; 4 with a name of 2+ words
    assert sorted(label for label, short_names in names.items() if short_names) == sorted(
        label for label, _ in AGENCIES if label.startswith("Department of "))


def test_a_colliding_short_name_is_dropped_for_both_agencies():
    twins = [{"label": "Department of Veterans Affairs", "aliases": []},
             {"label": "Office of Veterans Affairs Review", "aliases": []}]
    names, dropped = scoring.agency_short_names(twins)
    assert "Veterans Affairs" not in names["Department of Veterans Affairs"]
    assert any(entry["short_name"] == "Veterans Affairs" for entry in dropped)


def test_which_abbreviations_can_stand_alone_is_decided_for_all_41():
    alone = {abbr for _, abbr in AGENCIES if scoring.abbreviation_stands_alone(abbr)}
    not_alone = {abbr for _, abbr in AGENCIES} - alone
    assert not_alone == {"VA", "ED", "STATE", "DOC", "DOT", "DOE", "SEC"}
    assert len(alone) == 34
    for code in scoring.US_STATE_CODES:
        assert not scoring.abbreviation_stands_alone(code), code
    assert {"VA", "IN", "OR", "ME", "OK", "HI", "DC", "PR"} <= set(scoring.US_STATE_CODES)
    assert len(scoring.US_STATE_CODES) >= 51


@pytest.mark.parametrize("abbr", ["VA", "ED", "STATE", "DOC", "DOT", "DOE", "SEC"])
def test_an_abbreviation_that_is_a_word_or_a_state_code_counts_only_next_to_its_full_name(abbr):
    expected = {abbreviation: name for name, abbreviation in AGENCIES}[abbr]
    alone = score("agency", expected, abbr)
    assert (alone["exact"], alone["unclear"]) == (False, True)
    assert score("agency", expected, f"The {abbr}.")["exact"] is False
    assert score("agency", expected, f"{expected} ({abbr})")["exact"] is True
    assert score("agency", expected, f"Agency: {expected} ({abbr})")["exact"] is True


@pytest.mark.parametrize("abbr", ["EPA", "HHS", "NASA", "HUD", "USDA", "TREAS", "DOL"])
def test_an_abbreviation_that_is_not_a_word_stands_alone_in_upper_case_only(abbr):
    expected = {abbreviation: name for name, abbreviation in AGENCIES}[abbr]
    assert score("agency", expected, abbr)["exact"] is True
    assert score("agency", expected, f"It was reported by {abbr}.")["exact"] is True
    assert score("agency", expected, abbr.lower())["exact"] is False
    assert score("agency", expected, abbr.title())["exact"] is False


@pytest.mark.parametrize("expected,answer", [
    ("Department of State", "The State Department of Transportation."),
    ("Department of State", "The state department of health reported it."),
    ("Department of Energy", "The Texas Department of Energy."),
    ("Department of Energy", "A state Department of Energy."),
    ("Department of Energy", "The Energy Department of the State of Ohio."),
    ("Department of Veterans Affairs", "Veterans Affairs Canada"),
    ("Department of Health and Human Services", "The Health and Human Services Commission."),
    ("Securities and Exchange Commission", "The Securities and Exchange Commission of Pakistan."),
    ("Department of Education", "The ED triage tool was reported by the Department of Health and Human Services."),
])
def test_a_look_alike_name_is_never_credited(expected, answer):
    result = score("agency", expected, answer)
    assert result["exact"] is False, result


def test_predeployment_in_one_word_is_a_listed_spelling():
    assert score("stage", "Pre-deployment", "Predeployment")["exact"] is True
    assert "predeployment" in [s.lower() for s in scoring.accepted_spellings(LABEL_SETS, "stage")["Pre-deployment"]]


def test_the_accepted_spellings_of_every_value_can_be_listed():
    spellings = scoring.accepted_spellings(LABEL_SETS, "agency")
    # Round 4 added the abbreviation in front of the name in brackets, and "Department of X" for "Department of the X".
    assert spellings["Department of the Treasury"] == [
        "Department of the Treasury", "Department of the Treasury (TREAS)", "TREAS (Department of the Treasury)", "TREAS",
        "Treasury Department", "Dept of the Treasury", "Department of Treasury"]
    assert spellings["Department of Veterans Affairs"] == [
        "Department of Veterans Affairs", "Department of Veterans Affairs (VA)", "VA (Department of Veterans Affairs)",
        "Veterans Affairs Department", "Dept of Veterans Affairs", "Veterans Affairs"]
    assert scoring.accepted_spellings(LABEL_SETS, "high_impact") == {label: [label] for label in HIGH_IMPACT_LABELS}


# --- the kinds of answer that are now "unclear", each with the note that says why -------------------------------

@pytest.mark.parametrize("kind,expected,answer,note", [
    ("stage", "Deployed", "Is it Deployed", "unclear_reads_as_a_question"),
    ("stage", "Deployed", "Deployed, is it", "unclear_reads_as_a_question"),
    ("stage", "Deployed", "It deployed the use case.", "unclear_value_used_as_a_verb"),
    ("stage", "Retired", "It retired it.", "unclear_value_used_as_a_verb"),
    ("stage", "Deployed", "The Department of Justice deployed it.", "unclear_words_outside_the_filler_list"),
    ("agency", DOE, "Was it reported by the Department of Energy", "unclear_reads_as_a_question"),
    ("stage", "Deployed", "Deployed?", "unclear_character_outside_the_allowed_list"),
    ("stage", "Deployed", "Deployed or Pilot.", "unclear_more_than_one_value"),
    ("stage", "Deployed", "Deployed/Retired", "unclear_character_outside_the_allowed_list"),
    ("stage", "Deployed", "Deployed (not Retired).", "unclear_more_than_one_value"),
    ("stage", "Deployed", "It is probably Deployed.", "unclear_words_outside_the_filler_list"),
    ("stage", "Deployed", "It is not Deployed.", "unclear_words_outside_the_filler_list"),
    ("stage", "Deployed", "In production.", "unclear_no_value_found"),
    ("stage", "Deployed", "The passages do not say.", "unclear_no_value_found"),
    ("stage", "Deployed", "Deployed. " + D, "unclear_mixed_with_the_refusal_sentence"),
    ("stage", "Deployed", '{"stage": "Deployed", "sure": false}', "unclear_json_form_not_accepted"),
    ("stage", "Deployed", '{"stage_of_development": true}', "unclear_json_form_not_accepted"),
    ("high_impact", "Not High-impact", "Not. High-impact.", "unclear_words_outside_the_filler_list"),
    ("high_impact", "High-impact", "The high-impact determination", "unclear_no_value_found"),
])
def test_an_unclear_answer_says_why(kind, expected, answer, note):
    result = score(kind, expected, answer)
    assert (result["exact"], result["unclear"], result["note"], result["asserted"]) == (False, True, note, [])


def test_the_words_that_could_not_be_read_are_reported():
    result = score("stage", "Deployed", "It will be Deployed next year.")
    assert result["unread"] == "will be next year" and result["found"] == ["Deployed"]
    clean = score("stage", "Deployed", "It is Deployed.")
    assert clean["unread"] == "" and clean["found"] == ["Deployed"] and clean["asserted"] == ["Deployed"]


def test_a_clean_wrong_value_is_wrong_not_unclear():
    result = score("stage", "Deployed", "The stage of development is Pilot.")
    assert (result["exact"], result["unclear"], result["note"], result["asserted"]) == (
        False, False, "different_value", ["Pilot"])


def test_a_refusal_of_an_answerable_question_and_an_empty_answer_are_not_unclear():
    refused = score("stage", "Deployed", D)
    assert (refused["exact"], refused["declined"], refused["unclear"]) == (False, True, False)
    empty = score("stage", "Deployed", "   ")
    assert (empty["exact"], empty["note"], empty["unclear"]) == (False, "empty_answer", True)


# --- JSON answers: only the enumerated form -------------------------------------------------------------------

@pytest.mark.parametrize("kind,expected,key", [
    (kind, expected, key)
    for kind, expected in (("agency", DOE), ("stage", "Pilot"), ("high_impact", "Not High-impact"))
    for key in sorted(scoring.JSON_ANSWER_KEYS[kind])])
def test_a_json_object_with_one_listed_key_and_the_value_as_a_string_is_accepted(kind, expected, key):
    assert score(kind, expected, json.dumps({key: expected}))["exact"] is True
    assert score(kind, expected, "```json\n" + json.dumps({key: expected}) + "\n```")["exact"] is True


@pytest.mark.parametrize("answer", [
    '{"stage": "Deployed", "stage_of_development": "Deployed"}',     # two keys
    '{"status": "Deployed"}',                                         # a key that is not listed
    '{"not_the_stage": "Deployed"}',
    '{"stage": ["Deployed"]}', '{"stage": {"value": "Deployed"}}', '{"stage": true}', '{"stage": null}',
    '{"stage": "not Deployed"}', '{"stage": "Deployed or Pilot"}',
    '{"stage": "Deployed"} but I am not sure', 'Note {"stage": "Deployed"}',
    '[{"stage": "Deployed"}]', '{"stage": "Deployed"', "{'stage': 'Deployed'}",
])
def test_any_other_json_shape_is_unclear(answer):
    result = score("stage", "Deployed", answer)
    assert (result["exact"], result["unclear"]) == (False, True), result


def test_the_json_keys_are_written_out():
    assert set(scoring.JSON_ANSWER_KEYS) == {"agency", "stage", "high_impact"}
    assert sum(len(keys) for keys in scoring.JSON_ANSWER_KEYS.values()) <= 12


# --- the fixer's own adversarial set, labelled by hand before the new scorer existed ---------------------------

def own_counts():
    false_credit, lost_credit = [], []
    for key, text, label, tag in adversarial_r2.ANSWERS:
        got = bool(scoring.score_exact(adversarial_r2.make_item(key), text, LABEL_SETS)["exact"])
        if got and not label:
            false_credit.append((key, tag, text))
        if label and not got:
            lost_credit.append((key, tag, text))
    return false_credit, lost_credit


def test_the_fixers_own_adversarial_answers_give_no_false_credit():
    assert len(adversarial_r2.ANSWERS) >= 100
    assert len({(key, text) for key, text, _, _ in adversarial_r2.ANSWERS}) == len(adversarial_r2.ANSWERS)
    false_credit, _ = own_counts()
    assert false_credit == []


def test_the_lost_credit_on_the_fixers_own_set_is_the_number_the_readme_states():
    _, lost_credit = own_counts()
    readme = (KIT_DIR / "README.md").read_text(encoding="utf-8")
    match = re.search(r"false credit 0 of (\d+) and lost credit (\d+) of \1 on the fixer's own", readme)
    assert match, "the README does not state the two counts for the fixer's own set"
    assert (int(match.group(1)), int(match.group(2))) == (len(adversarial_r2.ANSWERS), len(lost_credit))
