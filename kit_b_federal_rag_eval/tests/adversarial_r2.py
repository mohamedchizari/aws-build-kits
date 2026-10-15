"""Round 2: adversarial answers written by the fixer, hand-labelled BEFORE the new scorer existed.

These are different from the independent reader's 250. They were written to attack an
allow-list scorer: wrong answers built from harmless-looking words, questions without a
question mark, symbols that negate, look-alike agency names, values hidden in a use case
name, key-value and JSON shapes, and refusals with something attached.

Label 1 = a careful human grader would accept the answer as stating the expected value for
the use case asked about, and no other value (a hedged statement of the right value is
labelled 1, as in the reader's set). Label 0 = anything else. For an unanswerable item,
label 1 = the answer declines and gives no answer.

The items are made up (no row of the inventory is used); the agency names are real.
"""
from __future__ import annotations

D = "I cannot answer this from the inventory documents provided."

AGENCY_Q = 'Which federal agency reported the AI use case named "{name}" in the 2025 federal AI use case inventory?'
STAGE_Q = 'What stage of development is recorded for the AI use case named "{name}", reported by the {agency}?'
HIGH_Q = 'What high-impact determination is recorded for the AI use case named "{name}", reported by the {agency}?'
BUDGET_Q = ('What annual budget in dollars is recorded for the AI use case named "{name}", '
            "reported by the {agency}?")

ITEMS = {
    "A1": ("agency", "Department of Energy", "Grid load forecasting assistant", None),
    "A2": ("agency", "Department of State", "Visa backlog triage helper", None),
    "A3": ("agency", "Department of Veterans Affairs", "Claims letter summarizer", None),
    "A4": ("agency", "Department of Housing and Urban Development", "Voucher fraud screening model", None),
    "A5": ("agency", "Securities and Exchange Commission", "Filing anomaly detector", None),
    "S1": ("stage", "Deployed", "Grid load forecasting assistant", "Department of Energy"),
    "S2": ("stage", "Pre-deployment", "Wildfire smoke plume tracker", "Department of the Interior"),
    "S3": ("stage", "Retired", "Pilot roster planning tool", "Department of Transportation"),
    "S4": ("stage", "Pilot", "Benefit letter drafting aid", "Social Security Administration"),
    "H1": ("high_impact", "High-impact", "Benefit eligibility screening model", "Department of Labor"),
    "H2": ("high_impact", "Not High-impact", "Meeting notes summarizer", "General Services Administration"),
    "H3": ("high_impact", "Presumed High-Impact, but Not High-impact", "Parcel image sorting model",
           "Department of Homeland Security"),
    "U1": ("unanswerable_heldout", None, "Seabed cable fault predictor", None),
    "U2": ("unanswerable_absent_field", None, "Grid load forecasting assistant", "Department of Energy"),
}


def make_item(key: str) -> dict:
    kind, expected, name, agency = ITEMS[key]
    answerable = expected is not None
    if kind in ("agency", "unanswerable_heldout"):
        question = AGENCY_Q.format(name=name)
    elif kind == "stage":
        question = STAGE_Q.format(name=name, agency=agency)
    elif kind == "high_impact":
        question = HIGH_Q.format(name=name, agency=agency)
    else:
        question = BUDGET_Q.format(name=name, agency=agency)
    return {"id": key, "type": kind, "answerable": answerable, "question": question, "use_case_name": name,
            "expected_answer": expected if answerable else "NO_ANSWER_IN_CORPUS",
            "label_set": kind if answerable else None, "accepted_aliases": [], "source_doc_id": "uc-0001"}


ANSWERS: list[tuple[str, str, int, str]] = []


def a(key: str, text: str, label: int, tag: str) -> None:
    ANSWERS.append((key, text, label, tag))


# ---------------- agency: Department of Energy ----------------
a("A1", "Department of Energy.", 1, "terse")
a("A1", "The Department of Energy", 1, "terse")
a("A1", "It was the Department of Energy.", 1, "plain")
a("A1", "The reporting agency is the Department of Energy (DOE).", 1, "plain")
a("A1", 'The federal agency that reported the AI use case named "Grid load forecasting assistant" in the '
        "2025 federal AI use case inventory is the Department of Energy.", 1, "question-restated")
a("A1", "Is it the Department of Energy", 0, "question-without-mark")
a("A1", "Was it reported by the Department of Energy", 0, "question-without-mark")
a("A1", "The Department of Energy, is it", 0, "tag-question-without-mark")
a("A1", "Department of Energy ✗", 0, "symbol-negation")
a("A1", "~~Department of Energy~~", 0, "struck-through")
a("A1", "Agency != Department of Energy", 0, "symbol-negation")
a("A1", "≠ Department of Energy", 0, "symbol-negation")
a("A1", "!Department of Energy", 0, "symbol-negation")
a("A1", "Department of Energy: false", 0, "key-value-false")
a("A1", '{"agency": "Department of Energy", "confirmed": false}', 0, "json-extra-key")
a("A1", '{"agency": "Department of Energy"}', 1, "json")
a("A1", '{"not_the_agency": "Department of Energy"}', 0, "json-key-negates")
a("A1", '{"agency": ["Department of Energy", "Department of State"]}', 0, "json-two-values")
a("A1", "The Texas Department of Energy.", 0, "look-alike-entity")
a("A1", "A state Department of Energy.", 0, "look-alike-entity")
a("A1", "The Department of Energy and Climate Change.", 0, "look-alike-entity")
a("A1", "The Energy Department of the State of Ohio.", 0, "look-alike-entity")
a("A1", "The former Department of Energy.", 0, "tense-shift")
a("A1", "The agency is no longer the Department of Energy.", 0, "negated")
a("A1", "Anything but the Department of Energy.", 0, "negated")
a("A1", "The opposite of the Department of Energy.", 0, "nonsense-negation")
a("A1", "Nicht das Department of Energy.", 0, "foreign-negation")
a("A1", "Pas le Department of Energy.", 0, "foreign-negation")
a("A1", "Department of Energy 不是", 0, "foreign-negation")
a("A1", "Department of Energy (sic)", 0, "doubt-marker")
a("A1", "Department of Energy [citation needed]", 0, "doubt-marker")
a("A1", "Allegedly the Department of Energy.", 0, "hedge-not-listed-in-r1")
a("A1", "Supposedly the Department of Energy.", 0, "hedge-not-listed-in-r1")
a("A1", "The Department of Energy, I suppose.", 1, "hedged")
a("A1", "Department of Energy, per the record for another use case.", 0, "other-use-case")
a("A1", "The record for a use case in the passages is from the Department of Energy.", 0, "vague-other-use-case")
a("A1", "The passage is a Department of Energy record.", 0, "about-the-passage-not-the-use-case")
a("A1", "Each use case in the passages was reported by the Department of Energy.", 1, "universal")
a("A1", "Every agency except the Department of Energy.", 0, "negated")
a("A1", "The Department of Energy did.", 1, "elliptical")
a("A1", "DOE.", 1, "abbreviation-that-is-a-word")
a("A1", "Doe", 0, "abbreviation-wrong-case")
a("A1", "The use case was reported by John DOE.", 0, "abbreviation-collision")
a("A1", "D.O.E.", 1, "abbreviation-dotted")
a("A1", "Dept of Energy", 1, "short-name")
a("A1", "The Energy Dept.", 1, "short-name")
a("A1", "Department Of Energy", 1, "case")
a("A1", "Department of Enery", 0, "misspelt")
a("A1", "Department of Energy Department of Energy Department of State", 0, "repeated-plus-other")
a("A1", "Department of Education. Correction: Department of Energy.", 0, "self-correction-two-values")
a("A1", "The Department of Energy reported a different use case.", 0, "other-use-case")
a("A1", "If any agency, the Department of Energy.", 0, "conditional")
a("A1", "The Department of Energy or so.", 0, "vague")
a("A1", "The Department of Energy?", 0, "question-mark")
a("A1", "¿The Department of Energy", 0, "question-mark-inverted")
a("A1", "The agency that did not report it is the Department of Energy.", 0, "negated")
a("A1", "Grid load forecasting assistant", 0, "name-only")
a("A1", 'The AI use case named "Grid load forecasting assistant" was reported by the agency.', 0, "no-value")
a("A1", "The agency is the agency that reported it.", 0, "no-value")
a("A1", "U.S. Department of Energy", 1, "us-prefix")
a("A1", "United States Department of Energy", 1, "us-prefix")
a("A1", "The Department of Energy\u2019s Office of Science.", 1, "with-bureau")
a("A1", "Department of Energy - " + D, 0, "value-plus-refusal")

# ---------------- agency: abbreviations that are words or state codes ----------------
a("A2", "Department of State", 1, "terse")
a("A2", "The State Department", 1, "short-name")
a("A2", "State", 1, "short-name-one-word")
a("A2", "STATE", 1, "abbreviation-that-is-a-word")
a("A2", "The State Department of Transportation.", 0, "look-alike-entity")
a("A2", "A state department.", 0, "ordinary-words")
a("A2", "The state department of health reported it.", 0, "ordinary-words")
a("A2", "THE STATE DEPARTMENT OF MOTOR VEHICLES", 0, "look-alike-entity-upper-case")
a("A2", "It is in a pre-deployment state.", 0, "ordinary-word")
a("A2", "The agency is in the record. STATE: unknown.", 0, "abbreviation-collision")
a("A2", "Department of State (STATE)", 1, "document-line-form")
a("A2", "Agency: Department of State (STATE)", 1, "document-line")
a("A2", "The Department of State of Palestine.", 0, "look-alike-entity")
a("A3", "Department of Veterans Affairs", 1, "terse")
a("A3", "The VA.", 1, "abbreviation-that-is-a-state-code")
a("A3", "Richmond, VA", 0, "state-code")
a("A3", "VA", 1, "abbreviation-that-is-a-state-code")
a("A3", "Veterans Affairs Canada", 0, "look-alike-entity")
a("A3", "The Veterans Affairs Department", 1, "short-name")
a("A3", "Veterans' Affairs", 1, "short-name-apostrophe")
a("A3", "The Department of Veteran Affairs", 1, "common-misspelling")
a("A3", "The agency is the VA; the use case is a pilot.", 1, "right-plus-unrelated-fact")
a("A4", "HUD", 1, "abbreviation")
a("A4", "The answer is HUD.", 1, "abbreviation")
a("A4", "hud", 1, "abbreviation-wrong-case")
a("A4", "The pilot reads it on a HUD.", 0, "abbreviation-collision")
a("A4", "Housing and Urban Development", 1, "short-name")
a("A4", "The Housing and Urban Development Corporation of India.", 0, "look-alike-entity")
a("A4", "Department of Housing", 0, "truncated-name")
a("A4", "Department of Housing and Urban Development (HUD), not the Department of the Interior.", 1,
  "right-plus-negated-other")
a("A5", "Securities and Exchange Commission (SEC)", 1, "document-line-form")
a("A5", "SEC", 1, "abbreviation-that-is-a-word")
a("A5", "Wait a SEC", 0, "abbreviation-collision")
a("A5", "The Securities and Exchange Commission of Pakistan.", 0, "look-alike-entity")
a("A5", "The Securities and Exchange Commission is the agency in the passage; the agency for this use case "
        "is the Federal Trade Commission.", 0, "two-values")

# ---------------- stage ----------------
a("S1", "Deployed.", 1, "terse")
a("S1", "It is Deployed.", 1, "plain")
a("S1", "The stage of development recorded is Deployed.", 1, "plain")
a("S1", "Is it Deployed", 0, "question-without-mark")
a("S1", "Deployed, is it", 0, "tag-question-without-mark")
a("S1", "Has it been deployed", 0, "question-without-mark")
a("S1", "Deployed: no", 0, "key-value-no")
a("S1", "Deployed = false", 0, "key-value-false")
a("S1", "Deployed ❌", 0, "symbol-negation")
a("S1", "~~Deployed~~", 0, "struck-through")
a("S1", "Deployed (0% of sites)", 0, "contradicting-detail")
a("S1", "Un-deployed", 0, "prefix-negation")
a("S1", "Undeployed", 0, "prefix-negation")
a("S1", "Non-Deployed", 0, "prefix-negation")
a("S1", "Semi-deployed", 0, "prefix-qualifier")
a("S1", "Pre-Deployed", 0, "prefix-changes-value")
a("S1", "Deployed-ish", 0, "suffix-hedge")
a("S1", "To be Deployed.", 0, "future")
a("S1", "It is to be Deployed.", 0, "future")
a("S1", "It is about to be Deployed.", 0, "future")
a("S1", "It is being deployed.", 0, "in-progress")
a("S1", "It was Deployed.", 0, "past-tense")
a("S1", "It had been Deployed.", 0, "past-perfect")
a("S1", "It used to be Deployed.", 0, "tense-shift")
a("S1", "Once Deployed.", 0, "tense-shift")
a("S1", "Deployed until 2024.", 0, "tense-shift")
a("S1", "Deployed soon.", 0, "future")
a("S1", "Almost Deployed.", 0, "approximation")
a("S1", "Partially Deployed.", 0, "qualifier")
a("S1", "Deployed in name only.", 0, "qualifier")
a("S1", "Deployed, supposedly.", 0, "hedge-not-listed-in-r1")
a("S1", "The stage after Deployed.", 0, "comparison")
a("S1", "One stage before Deployed.", 0, "comparison")
a("S1", "The stage is anything other than Deployed.", 0, "negated")
a("S1", "It is far from Deployed.", 0, "negated-idiom")
a("S1", "Hardly Deployed.", 0, "negated-adverb")
a("S1", "Deployed is what the record for a use case in the passages says.", 0, "vague-other-use-case")
a("S1", "The stage of development for the use case in passage [2] is Deployed.", 0, "about-a-passage")
a("S1", "According to passage [1], it is Deployed.", 1, "citation")
a("S1", "Deployed [1]", 1, "citation")
a("S1", "The stage is Deployed (document uc-0412).", 1, "citation")
a("S1", "Deployed, as recorded for the Department of Energy.", 1, "plain")
a("S1", "The Department of Energy record gives Deployed.", 1, "plain")
a("S1", "The Department of Energy deployed it.", 0, "verb-in-passing")
a("S1", "It is deployed on the agency network, stage unknown.", 0, "verb-in-passing")
a("S1", "D e p l o y e d", 1, "spaced-letters")
a("S1", "Deployed!", 1, "exclamation")
a("S1", "Deployed, Deployed, Deployed.", 1, "repeated")
a("S1", "deployed (the stage of development)", 1, "plain")
a("S1", "Stage: Deployed. Agency: Department of Energy.", 1, "extra-true-field")
a("S1", "D\u0435ployed", 1, "homoglyph-cyrillic-e")
a("S1", "Deployed\u200b", 1, "zero-width-space")
a("S1", "The stage of development is \u201cDeployed\u201d.", 1, "curly-quotes")
a("S1", "Deployed. " + D, 0, "value-plus-refusal")
a("S1", "The current stage is Deployed.", 1, "plain-with-current")
a("S1", "It is currently Deployed.", 1, "plain-with-currently")
a("S1", "Stage of development: Deployed (previously Pilot)", 1, "right-plus-temporal-other")
a("S1", "It is the Deployed stage of the Pilot.", 0, "two-values")
a("S1", "The stage is Deployed for the pilot sites only.", 0, "qualifier-plus-other-value")

a("S2", "Pre-deployment", 1, "terse")
a("S2", "Pre deployment.", 1, "no-dash")
a("S2", "It is in the Pre-deployment stage of development.", 1, "plain")
a("S2", "Pre-\ndeployment", 1, "line-break-inside-value")
a("S2", "Not Pre-deployment.", 0, "negated")
a("S2", "Post Pre-deployment.", 0, "prefix-changes-value")
a("S2", "Pre-deployment is over.", 0, "tense-shift")
a("S2", "Before deployment", 0, "paraphrase-no-value")
a("S2", "It is pre-deployment; it has not been Deployed.", 1, "right-plus-negated-other")
a("S2", "The use case is not recorded as Pre-deployment.", 0, "negated")

a("S3", "Retired", 1, "terse")
a("S3", "The Pilot roster planning tool is Retired.", 1, "name-holds-another-value")
a("S3", "Pilot roster planning tool", 0, "name-only-holds-another-value")
a("S3", "The Pilot roster planning tool is a Pilot.", 0, "wrong-value-after-name")
a("S3", "The Pilot is Retired.", 1, "shortened-name")
a("S3", "The stage recorded for the Pilot roster planning tool, reported by the Department of "
        "Transportation, is Retired.", 1, "question-restated")
a("S3", "Retiring", 0, "in-progress")
a("S3", "Soon to be Retired.", 0, "future")
a("S3", "It is to be Retired.", 0, "future")
a("S3", "Retired? Yes.", 1, "question-then-yes")

a("S4", "Pilot", 1, "terse")
a("S4", "This is a Pilot.", 1, "plain")
a("S4", "It is a pilot use case.", 1, "plain")
a("S4", "The pilot flew the aircraft; the stage is not given.", 0, "ordinary-word")
a("S4", "A pilot is planned.", 0, "future")
a("S4", "It is recorded as a Pilot in the inventory.", 1, "plain")
a("S4", "The Social Security Administration recorded it as Pilot.", 1, "plain")

# ---------------- high-impact ----------------
a("H1", "High-impact", 1, "terse")
a("H1", "The determination is High-impact.", 1, "plain")
a("H1", "Its high-impact determination is High-impact.", 1, "plain")
a("H1", "The high-impact determination", 0, "field-name-only")
a("H1", "It has a high-impact determination.", 0, "field-name-only")
a("H1", "High-impact determination: recorded", 0, "field-name-only")
a("H1", "High-impact: no", 0, "key-value-no")
a("H1", "High-impact: N", 0, "key-value-no")
a("H1", "High-impact = 0", 0, "key-value-zero")
a("H1", "High-impact (false)", 0, "key-value-false")
a("H1", "Is it High-impact", 0, "question-without-mark")
a("H1", "The use case is High-impact, is it", 0, "tag-question-without-mark")
a("H1", "Low, rather than High-impact.", 0, "comparison")
a("H1", "Less than High-impact.", 0, "comparison")
a("H1", "Formerly High-impact.", 0, "tense-shift")
a("H1", "It will be determined to be High-impact.", 0, "future")
a("H1", "It is yet to be determined to be High-impact.", 0, "yet-to-be")
a("H1", "It was determined to be High-impact.", 1, "plain-past")
a("H1", "It is determined to be High-impact.", 1, "plain")
a("H1", "Yes: High-impact.", 1, "yes-plus-value")
a("H1", "High-impact, yes.", 1, "value-plus-yes")
a("H1", "Yes and no: High-impact.", 0, "yes-and-no")
a("H1", "High-impact for another use case.", 0, "other-use-case")
a("H1", "The Department of Labor has a High-impact use case.", 0, "vague-other-use-case")
a("H1", "A use case is High-impact.", 0, "vague-other-use-case")
a("H1", "It is a High-impact use case.", 1, "plain")
a("H1", "High-impact, according to the Department of Labor record.", 1, "plain")
a("H1", "Quasi High-impact", 0, "qualifier")
a("H1", "High-impact-adjacent", 0, "qualifier")
a("H1", "HIGH-IMPACT", 1, "case")
a("H1", "Highimpact", 1, "spelling")
a("H1", "High - impact", 1, "spacing")
a("H1", "Hi-impact", 0, "not-the-value")
a("H1", "High-impact. " + D, 0, "value-plus-refusal")
a("H1", '{"high_impact_determination": "High-impact"}', 1, "json")
a("H1", '{"high_impact_determination": "High-impact", "note": "see Not High-impact"}', 0, "json-two-values")
a("H1", '{"high_impact_determination": null, "guess": "High-impact"}', 0, "json-null-plus-guess")

a("H2", "Not High-impact", 1, "terse")
a("H2", "It is Not High-impact.", 1, "plain")
a("H2", "Not. High-impact.", 0, "value-split-by-a-full-stop")
a("H2", "Not\nHigh-impact", 1, "line-break-inside-value")
a("H2", "High-impact: Not", 1, "reordered")
a("H2", "Not Not High-impact", 0, "double-negation")
a("H2", "It is not Not High-impact.", 0, "double-negation")
a("H2", "Not High-impact? Not so.", 0, "question-then-denial")
a("H2", "Not yet High-impact.", 0, "inserted-word-changes-meaning")
a("H2", "Not only High-impact.", 0, "inserted-word-changes-meaning")
a("H2", "Not Presumed High-impact.", 0, "not-a-value")
a("H2", "The use case is not high-impact.", 1, "plain")
a("H2", "High-impact", 0, "wrong-value")
a("H2", "The determination recorded is Not High-impact, not High-impact.", 1, "right-plus-negated-other")

a("H3", "Presumed High-Impact, but Not High-impact", 1, "terse")
a("H3", "Presumed High-Impact but Not High-impact.", 1, "no-comma")
a("H3", "Presumed High-Impact. But Not High-impact?", 0, "split-with-question")
a("H3", "Presumed High-Impact, and not Not High-impact", 0, "not-the-value")
a("H3", "Presumed High-Impact, but High-impact", 0, "not-the-value")
a("H3", "Presumed Not High-impact", 0, "not-the-value")
a("H3", "The determination is Presumed High-Impact, but Not High-impact.", 1, "plain")
a("H3", "It is not Presumed High-Impact, but Not High-impact.", 0, "negated")

# ---------------- unanswerable ----------------
a("U1", D, 1, "refusal")
a("U1", D + " ", 1, "refusal-trailing-space")
a("U1", "\n" + D + "\n", 1, "refusal-line-breaks")
a("U1", D + ".", 1, "refusal-two-periods")
a("U1", D[:-1] + "!", 1, "refusal-exclamation")
a("U1", D.upper(), 1, "refusal-upper-case")
a("U1", D.replace(" ", "\u00a0"), 1, "refusal-no-break-spaces")
a("U1", "A: " + D, 1, "refusal-with-label")
a("U1", D + " DOE", 0, "refusal-plus-answer")
a("U1", D + " \u200bDOE", 0, "refusal-plus-answer-zero-width")
a("U1", D + " 🙂", 1, "refusal-plus-emoji")
a("U1", D + " (Department of Energy)", 0, "refusal-plus-answer")
a("U1", D + "\n\nDepartment of Energy", 0, "refusal-plus-answer")
a("U1", D + " ١٢٣", 0, "refusal-plus-non-ascii-digits")
a("U1", D + " Énergie", 0, "refusal-plus-non-ascii-word")
a("U1", "Department of Energy. " + D, 0, "answer-plus-refusal")
a("U1", D.replace("cannot", "can"), 0, "one-word-changed")
a("U1", "I cannot answer this from the inventory documents provided, but it is the Department of Energy.", 0,
  "refusal-comma-answer")
a("U1", "The passages do not name an agency for this use case.", 1, "refusal-other-words")
a("U1", "Unknown", 1, "refusal-other-words")
a("U1", "The Department of Energy", 0, "invented")
a("U2", D, 1, "refusal")
a("U2", D + " $0", 0, "refusal-plus-number")
a("U2", D + " 0", 0, "refusal-plus-number")
a("U2", D + " -", 1, "refusal-plus-dash")
a("U2", "$3,000,000", 0, "invented")
a("U2", "No budget is recorded.", 1, "refusal-other-words")
