"""Round 3 (rehearsal on real model text): judge replies with the question they were written for.

Two lists.

REAL_NOT_HIGH_IMPACT is the reply that real stand-in judges (Claude Haiku and Claude Sonnet, given the
kit's own judge prompt) wrote for all ten "Not High-impact" questions of the rehearsal on 2026-10-07.
The round 2 parser returned UNPARSEABLE for every one of them, because of the word "Not" inside the
value. The use case names here are made up; the reply and the shape of the answers are the real ones.

REPLIES was written by the fixer and hand-labelled BEFORE the round 3 parser existed. No label was
changed afterwards. Unlike the round 2 lists, every reply comes with its question, because the round 3
parser is given the question's reference answer and the candidate's answer.

Label = what a careful person who knows the question, the reference and the candidate's answer reads as
the judge's verdict: "C" CORRECT, "I" INCORRECT, "D" DECLINED, "U" no single clear verdict (this includes
a verdict that the reply's own reason speaks against).
"flattering": the parser returns CORRECT or DECLINED and the label is not that.
"lost": the parser returns UNPARSEABLE and the label is C, I or D.
"""
from __future__ import annotations

DECLINE = "I cannot answer this from the inventory documents provided."


def _item(kind: str, name: str, expected: str | None, agency: str = "", aliases: tuple = ()) -> dict:
    answerable = expected is not None
    if kind == "agency" or kind == "unanswerable_heldout":
        question = f'Which federal agency reported the AI use case named "{name}" in the 2025 federal AI use case inventory?'
    elif kind == "stage":
        question = f'What stage of development is recorded for the AI use case named "{name}", reported by the {agency}?'
    elif kind == "high_impact":
        question = f'What high-impact determination is recorded for the AI use case named "{name}", reported by the {agency}?'
    else:
        question = f'What annual budget in dollars is recorded for the AI use case named "{name}", reported by the {agency}?'
    return {"id": "q-r3", "type": kind, "answerable": answerable, "question": question, "use_case_name": name,
            "expected_answer": expected if answerable else "NO_ANSWER_IN_CORPUS",
            "accepted_aliases": [{"text": text, "case_sensitive": True} for text in aliases],
            "label_set": kind if answerable else None, "source_doc_id": "uc-0001" if answerable else None}


# key -> (the question as the evaluation set holds it, the candidate's answer)
CONTEXTS: dict[str, tuple[dict, str]] = {
    "AG": (_item("agency", "Harbor lantern sorter", "Department of Energy", aliases=("DOE",)),
           'The Department of Energy (DOE) reported the AI use case named "Harbor lantern sorter".'),
    "AGD": (_item("agency", "Harbor lantern sorter", "Department of Energy", aliases=("DOE",)), DECLINE),
    "WR": (_item("agency", "Indigo juniper tracker", "Environmental Protection Agency", aliases=("EPA",)),
           'The Department of Energy (DOE) reported the AI use case named "Indigo juniper tracker".'),
    "ST": (_item("stage", "Meadow quartz planner", "Pilot", "Department of Justice"),
           'The stage of development recorded for "Meadow quartz planner" is Pilot.'),
    "ST2": (_item("stage", "Ribbon saddle tracker", "Pre-deployment", "Department of Commerce"),
            "The stage of development is Pre-deployment."),
    "TR": (_item("stage", "No-Code Error Triage Pilot", "Deployed", "Department of State"),
           'The stage of development recorded for "No-Code Error Triage Pilot" is Deployed.'),
    "QA": (_item("stage", "Quartz ribbon monitor", "Retired", "Department of Labor"),
           "The stage of development is Retired; no other stage is recorded in the passages."),
    "HI": (_item("high_impact", "Timber velvet reviewer", "High-impact", "Department of Veterans Affairs"),
           'The high-impact determination recorded for "Timber velvet reviewer" is High-impact.'),
    "NH": (_item("high_impact", "Willow zephyr mapper", "Not High-impact", "Department of Energy"),
           'The high-impact determination recorded for "Willow zephyr mapper" is Not High-impact.'),
    "PH": (_item("high_impact", "Anchor beacon forecaster", "Presumed High-Impact, but Not High-impact",
                 "Department of Homeland Security"),
           'The high-impact determination recorded for "Anchor beacon forecaster" is '
           '"Presumed High-Impact, but Not High-impact".'),
    "UH": (_item("unanswerable_heldout", "Cinder dapple monitor", None), DECLINE),
    "UA": (_item("unanswerable_absent_field", "Ember fennel sorter", None, "Department of Energy"), DECLINE),
    "UX": (_item("unanswerable_heldout", "Garnet hollow planner", None),
           'The Department of Justice reported the AI use case named "Garnet hollow planner".'),
}

REAL_REPLY = '{"verdict": "CORRECT", "reason": "Candidate correctly states Not High-impact, matching reference."}'
_REAL_NAMES = ("Harbor timber sorter", "Lantern willow monitor (LWM)", "Meadow effects and quartz dynamics",
               "Accelerating Ribbon Science: Saddle and Velvet at Extreme Scales", "Zephyr Anchor Intelligence (ZAI)",
               "Beacon AI Agent", "AI-Form and Cinder Assistant", "DAPPLE AI Chatbot Pilot",
               "Automated Analysis of Ember Fennel Center (EFC) Annual Reports using Large Language Models",
               "Garnet Hollow Signature Program Models")
REAL_NOT_HIGH_IMPACT: list[tuple[dict, str, str]] = [
    (_item("high_impact", name, "Not High-impact", "Department of Energy"),
     f'The high-impact determination recorded for "{name}" is Not High-impact.', REAL_REPLY)
    for name in _REAL_NAMES]


def _j(verdict: str, reason: str) -> str:
    return '{"verdict": "%s", "reason": "%s"}' % (verdict, reason.replace('"', '\\"'))


# (context key, the judge's whole reply, hand label)
REPLIES: list[tuple[str, str, str]] = [
    # --- 1. reasons a real judge writes, quoting each value of each label set --------------------------------
    ("NH", _j("CORRECT", "Candidate states Not High-impact, matching the reference with no contradicting facts."), "C"),
    ("NH", _j("CORRECT", 'The candidate says the determination is "Not High-impact", which is the reference answer.'), "C"),
    ("NH", _j("CORRECT", "Candidate says the use case is not high-impact, the same as the reference."), "C"),
    ("NH", _j("CORRECT", "Candidate accurately states the reference high-impact determination."), "C"),
    ("NH", _j("CORRECT", "The candidate states the reference answer (Not High-impact) and states no fact that "
                         "contradicts it."), "C"),
    ("PH", _j("CORRECT", "Candidate states Presumed High-Impact, but Not High-impact, matching the reference."), "C"),
    ("PH", _j("CORRECT", 'The candidate gives "Presumed High-Impact, but Not High-impact", exactly the reference value.'), "C"),
    ("PH", _j("CORRECT", "Same fact as the reference: Presumed High-Impact, but Not High-impact. Wording differs."), "C"),
    ("HI", _j("CORRECT", "Candidate states High-impact, matching the reference."), "C"),
    ("HI", _j("CORRECT", "Candidate accurately states the reference high-impact determination."), "C"),
    ("HI", _j("CORRECT", "The candidate states the reference answer (High-impact) and states no fact that contradicts it."), "C"),
    ("ST", _j("CORRECT", "Candidate correctly states Pilot, matching reference answer."), "C"),
    ("ST2", _j("CORRECT", "Candidate states Pre-deployment, matching the reference with no contradicting facts."), "C"),
    ("TR", _j("CORRECT", "Candidate states Deployed for No-Code Error Triage Pilot, matching the reference."), "C"),
    ("TR", _j("CORRECT", 'The candidate states Deployed for "No-Code Error Triage Pilot", with no errors.'), "C"),
    ("QA", _j("CORRECT", "Candidate correctly states the reference answer Retired with no contradictions."), "C"),
    ("AG", _j("CORRECT", "Candidate names Department of Energy (DOE), matching the reference with no contradiction."), "C"),
    ("AG", _j("CORRECT", "Candidate correctly states the reference answer DOE with no contradictions."), "C"),
    ("AG", _j("CORRECT", "The candidate answer matches the reference answer: Department of Energy."), "C"),
    ("AG", _j("CORRECT", 'Question: Which federal agency reported the AI use case named "Harbor lantern sorter" in the '
                         "2025 federal AI use case inventory? The candidate states the Department of Energy, the reference."), "C"),
    ("UH", _j("DECLINED", "Reference is NO ANSWER and the candidate declines without giving any answer."), "D"),
    ("UA", _j("DECLINED", "Reference is NO ANSWER. Candidate appropriately declines to answer."), "D"),
    ("UA", _j("DECLINED", "Candidate appropriately declines to answer when reference indicates no answer."), "D"),
    ("UH", _j("DECLINED", "The candidate says it cannot answer and has no information, and gives no answer."), "D"),
    ("UA", _j("DECLINED", "Candidate states it cannot answer from the documents provided."), "D"),
    ("UA", _j("DECLINED", "Candidate declines to give the annual budget for the Department of Energy use case."), "D"),
    ("UA", _j("DECLINED", "The candidate declines to answer; no budget is given."), "D"),
    ("UH", _j("DECLINED", "Declines. Does not name an agency."), "D"),
    ("UA", _j("DECLINED", 'Candidate says "I cannot answer this from the inventory documents provided." and gives no value.'), "D"),
    ("UH", _j("DECLINED", 'Candidate says "I cannot answer this from the inventory documents provided."'), "D"),
    ("UA", _j("DECLINED", "Reference is NO ANSWER. The documents do not contain the answer to this question. "
                          "The candidate declines."), "D"),
    ("UA", _j("DECLINED", "Reference is NO ANSWER."), "D"),
    ("NH", _j("DECLINED", "The candidate says it cannot answer; the reference is Not High-impact."), "D"),
    ("ST", _j("DECLINED", "Candidate declines although the reference is Pilot."), "D"),
    ("UX", _j("INCORRECT", "Reference is NO ANSWER; any substantive answer is INCORRECT. Candidate names Department of Justice."), "I"),
    ("WR", _j("INCORRECT", "Different agency: candidate says Department of Energy, reference is Environmental "
                           "Protection Agency."), "I"),
    ("NH", _j("INCORRECT", "Candidate states High-impact; the reference is Not High-impact."), "I"),
    ("HI", _j("INCORRECT", "Candidate states Not High-impact but the reference is High-impact."), "I"),
    # --- 2. the five phrases, where they support the verdict ----------------------------------------------------
    ("AG", _j("CORRECT", "The candidate states the Department of Energy and does not contradict the reference."), "C"),
    ("ST", _j("CORRECT", "States Pilot; no contradicting facts."), "C"),
    ("ST", _j("CORRECT", "Candidate states Pilot. It does not contradict the reference, and no contradicting facts are added."), "C"),
    ("NH", _j("CORRECT", "Not a refusal: the candidate states Not High-impact, as the reference does."), "C"),
    ("ST", _j("CORRECT", "The candidate does not decline; it states Pilot, which is the reference."), "C"),
    ("HI", _j("CORRECT", "States High-impact. Nothing incorrect is added."), "C"),
    ("AG", _j("CORRECT", "Same agency as the reference, nothing incorrect."), "C"),
    ("HI", _j("CORRECT", "Not incorrect: the candidate states High-impact."), "C"),
    ("PH", _j("CORRECT", "The candidate does not decline and does not contradict the reference value Presumed "
                         "High-Impact, but Not High-impact."), "C"),
    ("NH", _j("CORRECT", "The candidate does not contradict the reference Not High-impact; it does not decline; "
                         "nothing incorrect."), "C"),
    ("NH", _j("CORRECT", "Correct: 'Not High-impact' is the reference and the candidate's answer; it is not a refusal "
                         "and nothing in it is incorrect."), "C"),
    ("UH", _j("DECLINED", "The candidate declines; nothing incorrect is stated."), "D"),
    ("UH", _j("DECLINED", "The candidate says it cannot answer and adds no contradicting facts."), "D"),
    ("UX", _j("INCORRECT", "Reference is NO ANSWER and the candidate does not decline: it names the Department of Justice."), "I"),
    ("UX", _j("INCORRECT", "Not a refusal. The candidate gives an agency although the reference is NO ANSWER."), "I"),
    ("UX", _j("INCORRECT", "The candidate answers instead of declining."), "I"),
    ("UX", _j("INCORRECT", "The candidate should have declined; it names an agency instead."), "I"),
    ("UX", _j("INCORRECT", "Reference is NO ANSWER but candidate gives an answer rather than declining."), "I"),
    ("WR", _j("INCORRECT", "The candidate does not state the reference agency."), "I"),
    ("WR", _j("INCORRECT", "Candidate says Department of Energy; this does not match the reference Environmental "
                           "Protection Agency."), "I"),
    ("ST", _j("INCORRECT", "The candidate states Deployed, which does not match Pilot; this is not a refusal."), "I"),
    # --- 3. replies that contradict their own verdict, in the same vocabularies -----------------------------------
    ("NH", _j("CORRECT", "The candidate does not state Not High-impact."), "U"),
    ("NH", _j("CORRECT", "Candidate states High-impact, not Not High-impact."), "U"),
    ("NH", _j("CORRECT", "Not High-impact is not what the candidate states."), "U"),
    ("NH", _j("CORRECT", "The candidate's value differs from Not High-impact."), "U"),
    ("NH", _j("CORRECT", "Candidate states Presumed High-Impact, but Not High-impact."), "U"),
    ("NH", _j("CORRECT", "Candidate states Not High-impact. Not correct."), "U"),
    ("NH", _j("CORRECT", "Not."), "U"),
    ("NH", _j("CORRECT", "Nothing correct here: the candidate does not give Not High-impact."), "U"),
    ("HI", _j("CORRECT", "Candidate states Not High-impact."), "U"),
    ("HI", _j("CORRECT", "The candidate says the use case is not high-impact."), "U"),
    ("HI", _j("CORRECT", "Something incorrect is added to High-impact."), "U"),
    ("HI", _j("CORRECT", "Nothing incorrect, except that the agency is wrong."), "U"),
    ("PH", _j("CORRECT", "Candidate states Not High-impact."), "U"),
    ("PH", _j("CORRECT", "Candidate states High-impact."), "U"),
    ("PH", _j("CORRECT", "Candidate states Presumed High-Impact, but not the rest of the reference value."), "U"),
    ("ST", _j("CORRECT", "Candidate states Deployed; the reference is Pilot."), "U"),
    ("ST", _j("CORRECT", "The candidate contradicts the reference."), "U"),
    ("ST", _j("CORRECT", "The answer does not match the reference Pilot."), "U"),
    ("ST", _j("CORRECT", "It does not contradict the reference, but it does not state it either."), "U"),
    ("ST", _j("CORRECT", "States Pilot and adds a contradicting fact."), "U"),
    ("ST", _j("CORRECT", "No contradicting facts, however the stage is Deployed."), "U"),
    ("TR", _j("CORRECT", "Candidate states Pilot."), "U"),
    ("TR", _j("CORRECT", "There is an error in the candidate's stage."), "U"),
    ("AG", _j("CORRECT", "The candidate says DOJ; the reference says DOE."), "U"),
    ("AG", _j("CORRECT", "The candidate names the Department of Justice."), "U"),
    ("AG", _j("CORRECT", "This is a refusal, not an answer."), "U"),
    ("AG", _j("CORRECT", "The candidate declines."), "U"),
    ("AG", _j("CORRECT", "No. It contradicts the reference."), "U"),
    ("AG", _j("CORRECT", "The candidate does not decline, but names the wrong agency."), "U"),
    ("AG", _j("CORRECT", "Nothing correct is stated."), "U"),
    ("AGD", _j("CORRECT", 'Candidate says "I cannot answer this from the inventory documents provided."'), "U"),
    ("UH", _j("CORRECT", "Reference is NO ANSWER and the candidate correctly declines."), "U"),
    ("UH", _j("DECLINED", "This is not a refusal."), "U"),
    ("UH", _j("DECLINED", "The candidate does not decline."), "U"),
    ("UH", _j("DECLINED", "The candidate does not decline; it names the Department of Justice."), "U"),
    ("UH", _j("DECLINED", "The candidate refuses to decline and answers."), "U"),
    ("UH", _j("DECLINED", "The candidate never declines."), "U"),
    ("UH", _j("DECLINED", "No refusal here; the candidate provides an agency."), "U"),
    ("UH", _j("DECLINED", "Candidate declines, then states Not High-impact."), "U"),
    ("UA", _j("DECLINED", "Reference is NO ANSWER; the candidate states Pilot."), "U"),
    ("UA", _j("DECLINED", "The candidate does not say it cannot answer."), "U"),
    ("UX", _j("DECLINED", "The candidate states Department of Justice."), "U"),
    ("HI", _j("DECLINED", "The candidate's answer is High-impact, not a refusal."), "U"),
    ("AG", _j("INCORRECT", "The candidate is correct: it states the Department of Energy."), "U"),
    ("UH", _j("INCORRECT", "The candidate declines to answer."), "U"),
    # --- 4. the other shapes a verdict comes in, with a value in the reason ----------------------------------------
    ("NH", "CORRECT - the candidate states Not High-impact, the reference value.", "C"),
    ("NH", "Verdict: CORRECT\nReason: Candidate states Not High-impact, matching the reference.", "C"),
    ("NH", '```json\n{"verdict": "CORRECT", "reason": "States Not High-impact as in the reference."}\n```', "C"),
    ("NH", 'The candidate says Not High-impact and so does the reference.\n{"verdict": "CORRECT", "reason": "same value"}', "C"),
    ("NH", '{"verdict": "CORRECT", "reason": "Candidate correctly states Not High-impact, matching the refer', "C"),
    ("NH", '{"verdict": "CORRECT", "reason": "Candidate correctly states Not', "C"),
    ("PH", '{"verdict": "CORRECT", "reason": "Candidate states Presumed High-Impact, but Not', "C"),
    ("HI", "CORRECT - the candidate states Not High-impact.", "U"),
    ("HI", "Verdict: CORRECT\nReason: Candidate states Not High-impact.", "U"),
    ("HI", 'The candidate says Not High-impact.\n{"verdict": "CORRECT", "reason": "same value"}', "U"),
    # --- 5. the candidate's own words, quoted or retold ---------------------------------------------------------------
    ("QA", _j("CORRECT", 'Candidate says "The stage of development is Retired; no other stage is recorded in the '
                         'passages", which matches the reference Retired.'), "C"),
    ("QA", _j("CORRECT", "Candidate states Retired and says no other stage is recorded."), "C"),
    ("ST", _j("CORRECT", "Candidate's stage, Pilot, is the same as the reference; wording differs only."), "C"),
]
