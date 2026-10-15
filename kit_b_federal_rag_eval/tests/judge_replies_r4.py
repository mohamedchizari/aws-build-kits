"""Round 4 (fourth review, reader B, MAJOR 1): judge replies whose verdict the reply itself takes back.

Four kinds of list.

READER_* are the replies the round 4 reader reported as read flatteringly by the round 3 reader, and the
reader's two mechanical blocks (another value in an everyday spelling; one mismatch phrase), carried
over to questions of the kit's own test set. The reader's labels were written before this reader existed.

FIXER_AGAINST and FIXER_CLEAR were written by the fixer in three sittings, each BEFORE the list was run
on the new reader, to see how the new rules do on wording they were not built from. They are not a
measurement: the person who changed the reader wrote them. The round 3 reader read 68 of the 105
replies in FIXER_AGAINST as CORRECT or DECLINED; this reader reads none of them so.

STILL_READ_FLATTERINGLY is what the round 4 reader does not catch. README section 2, item 9 names
these limits; a test fails when one of them starts to be caught, so that the README is corrected.
"""
from __future__ import annotations

import json

import judge_replies_r3 as r3

DECLINE = r3.DECLINE


def j(verdict: str, reason: str) -> str:
    return json.dumps({"verdict": verdict, "reason": reason}, ensure_ascii=False)


# key -> (the question as the evaluation set holds it, the candidate's answer)
CONTEXTS: dict[str, tuple[dict, str]] = {
    "EPA": (r3._item("agency", "Indigo juniper tracker", "Environmental Protection Agency", aliases=("EPA",)),
            'The Environmental Protection Agency (EPA) reported the AI use case named "Indigo juniper tracker".'),
    "EPAW": (r3._item("agency", "Indigo juniper tracker", "Environmental Protection Agency", aliases=("EPA",)),
             'The Department of Energy (DOE) reported the AI use case named "Indigo juniper tracker".'),
    "COM": (r3._item("agency", "Saddle velvet mapper", "Department of Commerce", aliases=("DOC",)),
            'The National Oceanic and Atmospheric Administration (NOAA) reported the AI use case named "Saddle velvet mapper".'),
    "STA": (r3._item("agency", "Beacon cinder planner", "Department of State", aliases=("STATE",)),
            'The Department of the Interior (DOI) reported the AI use case named "Beacon cinder planner".'),
    "DEP": (r3._item("stage", "Meadow quartz planner", "Deployed", "Department of the Interior"),
            'The stage of development recorded for "Meadow quartz planner" is Deployed.'),
    "DEPW": (r3._item("stage", "Meadow quartz planner", "Deployed", "Department of the Interior"),
             'The stage of development recorded for "Meadow quartz planner" is Pilot.'),
    "PRE": (r3._item("stage", "Ribbon saddle tracker", "Pre-deployment", "Department of Commerce"),
            "The stage of development is Deployed."),
    "HI": (r3._item("high_impact", "Timber velvet reviewer", "High-impact", "Department of Veterans Affairs"),
           "The high-impact determination recorded is Not High-impact."),
    "NH": (r3._item("high_impact", "Willow zephyr mapper", "Not High-impact", "Department of Energy"),
           'The high-impact determination recorded for "Willow zephyr mapper" is Not High-impact.'),
    "NHW": (r3._item("high_impact", "Willow zephyr mapper", "Not High-impact", "Department of Energy"),
            "Yes, it is a high-impact use case."),
    "PH": (r3._item("high_impact", "Anchor beacon forecaster", "Presumed High-Impact, but Not High-impact",
                    "Department of Homeland Security"), "High-impact."),
    "UH": (r3._item("unanswerable_heldout", "Cinder dapple monitor", None), DECLINE),
    "UHW": (r3._item("unanswerable_heldout", "Cinder dapple monitor", None),
            'The General Services Administration (GSA) reported the AI use case named "Cinder dapple monitor".'),
    "UHH": (r3._item("unanswerable_heldout", "Cinder dapple monitor", None),
            DECLINE + " However, a similar use case was reported by the Department of Labor."),
    "UA": (r3._item("unanswerable_absent_field", "Ember fennel sorter", None, "Department of Energy"), DECLINE),
    "UAW": (r3._item("unanswerable_absent_field", "Ember fennel sorter", None, "Department of Energy"),
            "The annual budget is $4 million."),
    "UAS": (r3._item("unanswerable_absent_field", "Ember fennel sorter", None, "Department of Energy"),
            "The passages do not give an annual budget for this use case."),
}

# --- the reader's findings ---------------------------------------------------------------------------------------
# (context, the judge's whole reply, is it also refused WITHOUT the question). Every one was read as CORRECT or
# DECLINED by the round 3 reader, with the question passed in, except the four marked "without only".
READER_FLATTERING: list[tuple[str, str, bool]] = [
    ("EPAW", j("CORRECT", "The candidate says Energy; the reference says EPA."), True),
    ("EPAW", j("CORRECT", "The candidate gives the Department of Defense while the reference is the Environmental "
                          "Protection Agency."), True),
    ("COM", j("CORRECT", "The candidate says NOAA, while the reference is the Department of Commerce."), True),
    ("DEPW", j("CORRECT", "The candidate says it is still being piloted, the reference says Deployed."), True),
    ("DEPW", j("CORRECT", "The candidate reports an earlier stage than the reference."), True),
    ("DEPW", j("CORRECT", "Candidate disagrees with the reference stage of Deployed."), True),
    ("DEPW", j("CORRECT", "The stage given by the candidate is inconsistent with the reference."), True),
    ("DEPW", j("CORRECT", "There is a discrepancy between the candidate (pre-production) and the reference (Deployed)."), True),
    ("NHW", j("CORRECT", "The reference is Not High-impact; the candidate says it is."), True),
    ("NHW", j("CORRECT", "The reference says Not High-impact and the candidate says yes."), True),
    ("HI", j("CORRECT", "The candidate negates the reference value High-impact."), True),
    ("EPAW", j("CORRECT", "The candidate misidentifies the agency."), True),
    ("EPAW", j("CORRECT", "The candidate's agency is unrelated to the reference agency."), True),
    ("DEPW", j("CORRECT", "The reference stage is Deployed and the candidate says deployment is planned."), True),
    ("EPAW", j("CORRECT", "The candidate's agency " + chr(0x2260) + " the reference agency."), True),
    ("EPAW", j("CORRECT", "Candidate agency != reference agency."), True),
    ("STA", j("CORRECT", "The candidate says Interior and the reference says State."), True),
    ("UAW", j("DECLINED", "The candidate cannot answer precisely and estimates 4 million dollars."), True),
    ("UHH", j("DECLINED", "The candidate declines and adds a possible agency."), True),
    ("UHH", j("DECLINED", "The candidate declines, and points to a similar use case from another department."), True),
    ("UHH", j("DECLINED", 'The candidate says "I cannot answer this from the inventory documents provided. A similar '
                          'use case was reported by another department."'), True),
    ("UHW", j("DECLINED", "The candidate cannot be right: it identifies an agency."), True),
    ("UAW", j("DECLINED", "NO ANSWER expected; candidate has no answer beyond a dollar figure."), True),
    ("NHW", j("CORRECT", "Not High-impact vs. the candidate's affirmative."), True),
    ("NHW", j("CORRECT", "The reference Not High-impact; the candidate the reverse."), True),
    ("PH", j("CORRECT", "Reference: Presumed High-Impact, but Not High-impact. The candidate keeps the first two words."), True),
    ("EPAW", "CORRECT: Environmental Protection Agency\nCANDIDATE: Energy\nMATCH: N", True),
    ("EPAW", '{"answer_matches_reference": "N", "grade": {"verdict": "CORRECT"}}', True),
    ("EPAW", '{"grade": {"verdict": "CORRECT"}, "match": 0}', True),
    ("EPAW", 'Expected output for a matching answer: {"verdict": "CORRECT"}', True),
    # read flatteringly only without the question ("without only"): the question caught them in round 3
    ("DEPW", j("CORRECT", "Candidate states Pilot; the reference is Deployed."), True),
    ("EPAW", j("CORRECT", "The candidate says DOE; the reference says EPA."), True),
    ("EPAW", j("CORRECT", "Hmm, DOE vs EPA."), True),
    ("EPAW", "Correct: Environmental Protection Agency. Candidate: Department of Energy.", True),
]

# Block X3 of the reader's second set: (context, the reference as the judge writes it, another value as people write it).
READER_EVERYDAY_VALUES: list[tuple[str, str, str]] = (
    [("EPAW", "EPA", other) for other in (
        "Energy", "the Energy department", "Treasury", "the Interior Department", "Interior", "Commerce", "Justice",
        "the State Dept", "Labor", "Education", "Agriculture", "Transportation", "Homeland Security", "the VA", "Defense",
        "the Pentagon", "NOAA", "the FDA", "the Fed", "Social Security", "DoE", "the SEC", "NASA", "GSA", "HHS")]
    + [("DEPW", "Deployed", other) for other in (
        "piloting", "a pilot", "in testing", "pre-production", "retirement", "decommissioned", "planned", "pre-deployment",
        "retired", "under development", "sunset")]
    + [("PRE", "Pre-deployment", other) for other in ("deployment", "in production", "live", "operational", "deployed")])
READER_EVERYDAY_TEMPLATES = ("The candidate says {V}; the reference says {R}.", "Candidate: {V}. Reference: {R}.")

# Block X4: one phrase per reply, in "The candidate's answer {P} the reference."
READER_MISMATCH_PHRASES = (
    "does not match", "is not the same as", "differs from", "is different from", "contradicts", "conflicts with",
    "is inconsistent with", "disagrees with", "deviates from", "diverges from", "departs from", "is at odds with",
    "is contrary to", "is unlike", "mismatches", "fails to match", "is unrelated to", "has a discrepancy with",
    "varies from", "is opposed to", "clashes with", "is incompatible with", "misstates", "misreports", "misquotes",
    "gets wrong", "is wrong about", "is a mistaken reading of", "is an erroneous version of", "is an inaccurate version of",
    "falls short of", "only partly matches", "partially matches", "is incomplete compared with", "omits part of",
    "leaves out half of", "is the opposite of", "is the reverse of", "negates", "reverses", "inverts", "is missing from",
    "is absent from", "cannot be reconciled with", "is irrelevant to", "bears no relation to", "has nothing to do with",
    "is a hallucination, unsupported by", "is fabricated and unrelated to", chr(0x2260), "!=", "<>", "is a far cry from",
    "is nowhere near", "is anything but", "is hardly", "barely resembles", "goes against", "runs counter to", "is unfaithful to",
    # the fixer's, in the same frame
    "is a world away from", "strays from", "swaps", "is a poor match for", "is loosely based on", "garbles",
    "is nothing like", "has little in common with", "sits uneasily with", "is news to",
)

# Block X1: DECLINED with a reason a judge naturally gives for a refusal (the candidate's answer is UAS). Lost 9 of 16
# before round 4. Read only when the question is known.
READER_NATURAL_DECLINED = (
    "The candidate says the passages do not give a budget and gives no answer.",
    "The candidate states that the information is not available in the passages.",
    "The candidate indicates the answer is not in the documents.",
    "The candidate says the documents lack this information.",
    "The candidate explains that no budget is recorded and offers no figure.",
    "Candidate has no information and gives no answer.",
    "The candidate reports that the passages contain no budget figure.",
    "The candidate did not answer.",
    "No answer was given by the candidate.",
    "The candidate says it does not know.",
    "The candidate states the budget is not recorded.",
    "Candidate says there is no budget information in the passages.",
    "The candidate acknowledges it cannot determine the budget from the passages.",
    "The candidate abstains.",
    "The candidate says the inventory does not record a budget for this use case.",
    "Candidate notes the passages are silent on the budget.",
)
# Block X2: INCORRECT for an answer that declines and then answers (the candidate's answer is UHH). Lost 5 of 12 before.
READER_DECLINE_THEN_ANSWER = (
    "The candidate declines but then names the Department of Labor.",
    "After declining, the candidate still offers an agency.",
    "The candidate says it cannot answer and then answers anyway.",
    "The candidate gives an agency although the reference is NO ANSWER.",
    "The candidate initially declines, then suggests the Department of Labor, which is a substantive answer.",
    "Despite the refusal sentence, the candidate names an agency.",
    "The candidate adds a guess after the refusal.",
    "A substantive answer (Department of Labor) follows the refusal, so this is not a clean decline.",
    "The candidate hedges: it declines and then proposes an agency.",
    "Any substantive answer is INCORRECT when the reference is NO ANSWER; the candidate names the Department of Labor.",
    "The candidate provides an agency after saying it cannot answer.",
    "The candidate names the Department of Labor.",
)

# --- the fixer's own lists, each written before it was run --------------------------------------------------------
# (context, the judge's whole reply). CORRECT or DECLINED must never come back for one of these, with the question.
FIXER_AGAINST: list[tuple[str, str]] = [
    ("EPAW", j("CORRECT", "The candidate names the Department of Energy, not the EPA.")),
    ("EPAW", j("CORRECT", "The candidate says the Pentagon reported it; reference says EPA.")),
    ("EPAW", j("CORRECT", "The candidate's answer is the Bureau of Land Management.")),
    ("EPAW", j("CORRECT", "Candidate picks the wrong department.")),
    ("EPAW", j("CORRECT", "The candidate asserts it was the Navy.")),
    ("EPAW", j("CORRECT", "Reference: EPA. Candidate: unknown agency.")),
    ("EPAW", j("CORRECT", "The candidate gave an agency that the reference does not list.")),
    ("EPAW", j("CORRECT", "It says the Pentagon.")),
    ("EPAW", j("CORRECT", "The candidate cites the Forest Service; the reference cites EPA.")),
    ("EPAW", j("CORRECT", "Candidate lands on DOE when EPA was wanted.")),
    ("EPAW", j("CORRECT", "The response points to the Energy Department.")),
    ("EPAW", j("CORRECT", "The candidate's agency and the reference agency are two separate agencies.")),
    ("EPAW", j("CORRECT", "The candidate thinks it is EPA and is unsure.")),
    ("EPAW", j("CORRECT", "The candidate says it could be EPA.")),
    ("EPAW", j("CORRECT", "Candidate hedges between EPA and DOE.")),
    ("EPAW", j("CORRECT", "The candidate mentions EPA in passing and settles on the Navy.")),
    ("EPAW", j("CORRECT", "The candidate swaps EPA for the Navy.")),
    ("EPAW", j("CORRECT", "The answer lists several agencies including EPA.")),
    ("EPAW", j("CORRECT", "The candidate says EPA regulates it, and that the Navy reported it.")),
    ("EPAW", j("CORRECT", "EPA is what the reference says. The candidate offers the Smithsonian.")),
    ("DEPW", j("CORRECT", "The candidate says it is being tested; the reference says Deployed.")),
    ("DEPW", j("CORRECT", "Candidate states the use case is in an initial phase.")),
    ("DEPW", j("CORRECT", "The candidate says the tool is live for some users.")),
    ("DEPW", j("CORRECT", "The candidate's stage precedes the reference stage.")),
    ("DEPW", j("CORRECT", "The candidate says Deployed was planned for next year.")),
    ("DEPW", j("CORRECT", "Candidate claims it is past Deployed.")),
    ("DEPW", j("CORRECT", "The candidate says it will be Deployed.")),
    ("DEPW", j("CORRECT", "The candidate says it used to be Deployed.")),
    ("DEPW", j("CORRECT", "Deployed per the reference; in development per the candidate.")),
    ("DEPW", j("CORRECT", "The candidate answer mentions Deployed as a future goal.")),
    ("NHW", j("CORRECT", "The candidate says it is High-impact.")),
    ("NHW", j("CORRECT", "The candidate says the use case is high risk.")),
    ("NHW", j("CORRECT", "The candidate answers yes.")),
    ("NHW", j("CORRECT", "Candidate states the inverse determination.")),
    ("NHW", j("CORRECT", "The candidate leaves off the first word of Not High-impact.")),
    ("NHW", j("CORRECT", "The candidate says it is Not High-impact pending review.")),
    ("NHW", j("CORRECT", "The candidate affirms a high-impact status.")),
    ("NHW", j("CORRECT", "The candidate says the determination is Not High-impact for a sibling use case.")),
    ("NHW", j("CORRECT", "The reference says Not High-impact; the candidate is silent on it.")),
    ("NHW", j("CORRECT", "Candidate gives the determination as presumed.")),
    ("UHW", j("DECLINED", "The candidate declines, having first named GSA.")),
    ("UHW", j("DECLINED", "The candidate cannot answer fully and gives GSA as a best effort.")),
    ("UAW", j("DECLINED", "The candidate declines to give a budget and writes that it is four million.")),
    ("UHW", j("DECLINED", "The candidate says it cannot answer. Its answer is GSA.")),
    ("UHW", j("DECLINED", "The candidate refuses, then relents.")),
    ("UHW", j("DECLINED", "The candidate declines in part.")),
    ("UHW", j("DECLINED", "The candidate nearly declines.")),
    ("UHW", j("DECLINED", "The candidate declines to confirm and supplies an agency.")),
    ("UHW", j("DECLINED", "Candidate says no answer is in the documents and volunteers the Navy.")),
    ("UHW", j("DECLINED", "The candidate does anything except decline.")),
    ("UHW", j("DECLINED", "The candidate declines the premise and answers GSA.")),
    ("UHW", j("DECLINED", "The candidate cannot answer with certainty; it answers GSA.")),
    ("UHW", j("DECLINED", "No refusal here.")),
    ("UHW", j("DECLINED", "The candidate declined at the start; a Navy office comes after.")),
    ("UHW", j("DECLINED", "The candidate hardly declines.")),
    # second sitting
    ("EPAW", j("CORRECT", "Energy.")),
    ("EPAW", j("CORRECT", "Pentagon.")),
    ("EPAW", j("CORRECT", "The candidate matches a neighbouring agency.")),
    ("EPAW", j("CORRECT", "Candidate is correct about a different use case.")),
    ("EPAW", j("CORRECT", "The candidate is right in spirit.")),
    ("EPAW", j("CORRECT", "The candidate matches the reference in form; in substance it is the Navy.")),
    ("EPAW", j("CORRECT", "Reference matched in the first clause; the second clause names the Navy.")),
    ("EPAW", j("CORRECT", "EPA. Also the Navy.")),
    ("EPAW", j("CORRECT", "EPA and the Navy.")),
    ("EPAW", j("CORRECT", "Navy given, EPA expected.")),
    ("EPAW", j("CORRECT", "Candidate states EPA (wrongly).")),
    ("EPAW", j("CORRECT", "The candidate says EPA, the regional office.")),
    ("EPAW", j("CORRECT", "The candidate gets the agency right and the use case wrong.")),
    ("DEPW", j("CORRECT", "Candidate: Deployed (to be confirmed).")),
    ("DEPW", j("CORRECT", "The candidate says Deployed-ish.")),
    ("DEPW", j("CORRECT", "The candidate says un-Deployed.")),
    ("DEPW", j("CORRECT", "The candidate says Deployed in 2019 and Retired since.")),
    ("DEPW", j("CORRECT", "Stage: Live. Reference: Deployed.")),
    ("DEPW", j("CORRECT", "It is Operational, the reference is Deployed.")),
    ("NHW", j("CORRECT", "The candidate says it is highly impactful.")),
    ("NHW", j("CORRECT", "The candidate says the impact is high, as the reference.")),
    ("NHW", j("CORRECT", "The candidate says the impact is high.")),
    ("NHW", j("CORRECT", "The candidate says Not High-impact was the earlier value.")),
    ("UAW", j("DECLINED", "The candidate says the documents lack the budget and cites 4 million.")),
    ("UAW", j("DECLINED", "The candidate states the budget is not recorded, roughly four million.")),
    ("UAW", j("DECLINED", "The candidate says there is no doubt.")),
    ("UAW", j("DECLINED", "The candidate indicates the answer is not in the documents it was given, then gives it from memory.")),
    ("UAW", j("DECLINED", "The candidate says it cannot answer briefly.")),
    ("UAW", j("DECLINED", "The candidate offers no refusal.")),
    ("UAW", j("DECLINED", "The candidate declined nothing.")),
    ("UAW", j("DECLINED", "It is not the case that the candidate declines.")),
    ("UAW", j("DECLINED", "Nobody could say the candidate declines.")),
    ("UAW", j("DECLINED", "The candidate says it cannot answer for certain.")),
    ("UHW", j("DECLINED", "The candidate does not know the stage and says Pilot.")),
    ("UHW", j("DECLINED", "The candidate has no answer and provides its best one.")),
    ("UHW", j("DECLINED", "The candidate says the passages contain no agency and settles on the Navy.")),
    ("UHW", j("DECLINED", "The candidate says the answer is not available, the Navy being its fallback.")),
    ("UHW", j("DECLINED", "There is no refusal in the candidate answer.")),
    ("UHW", j("DECLINED", "The candidate lacks a refusal.")),
    ("UHW", j("DECLINED", "The candidate is silent on whether it cannot answer.")),
    ("EPAW", '{"verdict":"CORRECT","reason":"ok"} but see note'),
    ("EPAW", "CORRECT? The candidate matches."),
    ("EPAW", '{"verdict": "CORRECT", "reason": "The candidate\nReference mismatch"}'),
    ("EPAW", '{"verdict": "CORRECT", "reason": "x"} {"verdict": "CORRECT", "reason": "the Navy"}'),
    ("EPAW", '{"verdict": "CORRECT", "reason": "Candidate says "Navy" which is "EPA""}'),
    ("EPAW", '{"verdict": "CORRECT", "reason": "Matches", "detail": {"candidate": "Navy", "reference": "EPA"}}'),
    ("EPAW", '{"grade": {"verdict": "CORRECT"}, "notes": "candidate named the Navy"}'),
    ("EPAW", "Verdict: CORRECT\nCandidate: Navy\nReference: EPA"),
    ("EPAW", "CORRECT\nCandidate said Navy."),
    ("EPAW", "**Verdict:** CORRECT\n**Reason:** Navy is not EPA"),
]

# (context, the verdict a person reads, the reason). Clear replies in the wording a model judge is likely to use.
FIXER_CLEAR: list[tuple[str, str, str]] = [
    ("EPA", "CORRECT", "The candidate answer matches the reference answer."),
    ("EPA", "CORRECT", "The candidate correctly identifies EPA as the reporting agency."),
    ("EPA", "CORRECT", "Candidate's answer states the Environmental Protection Agency, which matches the reference EPA."),
    ("EPA", "CORRECT", "The answer is consistent with the reference."),
    ("EPA", "CORRECT", "Both name the Environmental Protection Agency."),
    ("EPA", "CORRECT", "The candidate identifies the Environmental Protection Agency (EPA), which is the same as the reference answer."),
    ("EPA", "CORRECT", "The candidate states the agency is EPA, matching the reference."),
    ("EPA", "CORRECT", "Same agency as reference (EPA)."),
    ("EPA", "CORRECT", "The candidate's answer agrees with the reference: EPA."),
    ("EPA", "CORRECT", "Candidate states EPA; reference is EPA."),
    ("EPA", "CORRECT", "The candidate response correctly names the EPA."),
    ("EPA", "CORRECT", "The candidate provides the correct agency, EPA."),
    ("EPA", "CORRECT", "Agency matches reference."),
    ("EPA", "CORRECT", "The candidate gives the reference answer in full form with the abbreviation."),
    ("EPA", "CORRECT", "EPA is stated by the candidate, as in the reference."),
    ("EPA", "CORRECT", "The candidate answer conveys the same fact as the reference answer."),
    ("EPA", "CORRECT", "Candidate answer is equivalent to the reference."),
    ("EPA", "CORRECT", "The candidate names the Environmental Protection Agency, the reference agency."),
    ("DEP", "CORRECT", "The candidate states the stage is Deployed, which matches the reference."),
    ("DEP", "CORRECT", "The candidate says Deployed, same as the reference."),
    ("DEP", "CORRECT", "Candidate identifies the stage of development as Deployed, consistent with the reference."),
    ("DEP", "CORRECT", "The stage given, Deployed, matches the reference answer."),
    ("DEP", "CORRECT", "Deployed matches Deployed."),
    ("DEP", "CORRECT", "The candidate's stage of development (Deployed) is identical to the reference."),
    ("NH", "CORRECT", "The candidate states the determination is Not High-impact, matching the reference."),
    ("NH", "CORRECT", "Candidate says Not High-impact, which is exactly the reference."),
    ("NH", "CORRECT", "The candidate answer and reference both state Not High-impact."),
    ("NH", "CORRECT", "Not High-impact is the reference and the candidate states it."),
    ("NH", "CORRECT", "The candidate correctly reports the high-impact determination as Not High-impact."),
    ("NH", "CORRECT", "Candidate's determination (Not High-impact) agrees with the reference."),
    ("UH", "DECLINED", "The candidate declines to answer, as expected for a NO ANSWER reference."),
    ("UH", "DECLINED", "The candidate says it cannot answer from the documents."),
    ("UH", "DECLINED", "Candidate declined to answer."),
    ("UH", "DECLINED", "The candidate states it cannot answer this from the inventory documents provided."),
    ("UH", "DECLINED", "The candidate refuses to answer and gives no agency."),
    ("UA", "DECLINED", "The candidate does not provide an answer and says it cannot answer."),
    ("UA", "DECLINED", "Candidate says it cannot answer; reference is NO ANSWER."),
    ("UA", "DECLINED", "The candidate declines."),
    ("UA", "DECLINED", "The candidate correctly declines since the documents do not contain the answer."),
    ("UA", "DECLINED", "The candidate indicates it cannot answer the question."),
    # second sitting
    ("EPA", "CORRECT", "The candidate answer states the same agency as the reference answer."),
    ("EPA", "CORRECT", "The candidate correctly states that the Environmental Protection Agency reported the use case."),
    ("EPA", "CORRECT", "Candidate's answer matches the reference answer, EPA."),
    ("EPA", "CORRECT", "The candidate provided the correct agency name."),
    ("EPA", "CORRECT", "The candidate's response aligns with the reference answer."),
    ("EPA", "CORRECT", "Candidate correctly identified the agency as EPA."),
    ("EPA", "CORRECT", "The candidate states the reference answer with the same fact."),
    ("EPA", "CORRECT", "The candidate answer is factually the same as the reference."),
    ("EPA", "CORRECT", "The candidate's answer contains the reference answer."),
    ("EPA", "CORRECT", "Candidate states the reference answer and no contradicting fact."),
    ("EPA", "CORRECT", "The candidate response is correct and matches the reference answer."),
    ("EPA", "CORRECT", "The candidate mentions EPA, which is the reference answer."),
    ("DEP", "CORRECT", "The candidate states the stage of development as Deployed, which is the reference answer."),
    ("DEP", "CORRECT", "The candidate correctly states the use case is Deployed."),
    ("DEP", "CORRECT", "Candidate answer says Deployed; reference answer is Deployed."),
    ("DEP", "CORRECT", "The stage of development in the candidate answer is Deployed, same as the reference."),
    ("NH", "CORRECT", "The candidate states the high-impact determination is Not High-impact, same as the reference."),
    ("NH", "CORRECT", "Candidate correctly states the use case is not high-impact."),
    ("NH", "CORRECT", "The candidate's determination matches the reference: Not High-impact."),
    ("NH", "CORRECT", "The candidate states the reference answer exactly."),
    ("UH", "DECLINED", "The candidate declines to answer and gives no information."),
    ("UH", "DECLINED", "The candidate says it cannot answer the question from the documents provided."),
    ("UA", "DECLINED", "Candidate declines because the passages do not contain the answer."),
    ("UA", "DECLINED", "The candidate states it has no information to answer."),
    ("UA", "DECLINED", "The candidate cannot answer and does not give an answer."),
    ("UA", "DECLINED", "The candidate declined, which is expected when the reference is NO ANSWER."),
    ("UH", "DECLINED", "The candidate refuses to answer."),
    ("UA", "DECLINED", "Candidate says the answer is not in the documents."),
    ("UA", "DECLINED", "The candidate gives no answer."),
    ("UH", "DECLINED", "The candidate response is a refusal."),
    ("UHW", "INCORRECT", "The candidate gives an agency but the reference is NO ANSWER."),
    ("UHW", "INCORRECT", "The candidate names GSA; it should have declined."),
    ("DEPW", "INCORRECT", "The candidate states Pilot, which differs from the reference Deployed."),
    ("DEPW", "INCORRECT", "The candidate's answer does not match the reference."),
    ("EPA", "INCORRECT", "The candidate declines although the documents contain the answer."),
    # third sitting
    ("EPA", "CORRECT", "The candidate identifies the correct agency, EPA, as stated in the reference."),
    ("EPA", "CORRECT", "The candidate's answer matches the reference answer exactly."),
    ("EPA", "CORRECT", "The candidate correctly names the Environmental Protection Agency as the reporting agency."),
    ("EPA", "CORRECT", "The candidate states EPA, which is the reference answer; no contradicting facts."),
    ("EPA", "CORRECT", "Candidate answer matches reference: Environmental Protection Agency (EPA)."),
    ("EPA", "CORRECT", "The candidate accurately identifies the agency as the Environmental Protection Agency."),
    ("EPA", "CORRECT", "The candidate answer correctly identifies EPA, consistent with the reference."),
    ("EPA", "CORRECT", "The answer names the Environmental Protection Agency, matching the reference EPA."),
    ("EPA", "CORRECT", "Candidate states the same agency as the reference answer."),
    ("EPA", "CORRECT", "The candidate gives the Environmental Protection Agency, which the reference abbreviates as EPA."),
    ("EPA", "CORRECT", "The candidate's answer is the full name of the reference agency."),
    ("EPA", "CORRECT", "The candidate response states the reference answer and adds the use case name."),
    ("EPA", "CORRECT", "The candidate correctly answers EPA."),
    ("EPA", "CORRECT", "The candidate's statement agrees with the reference answer of EPA."),
    ("EPA", "CORRECT", "Correct agency identified: EPA."),
    ("EPA", "CORRECT", "The candidate matches the reference answer."),
    ("EPA", "CORRECT", "The candidate provides the same answer as the reference."),
    ("EPA", "CORRECT", "The candidate's answer and the reference refer to the same agency."),
    ("EPA", "CORRECT", "The candidate names EPA as the agency, which is correct."),
    ("EPA", "CORRECT", "The response correctly identifies the agency that reported the use case as the EPA."),
    ("DEP", "CORRECT", "The candidate states the stage of development is Deployed, matching the reference."),
    ("DEP", "CORRECT", "The candidate correctly identifies the stage as Deployed."),
    ("DEP", "CORRECT", "Candidate's answer of Deployed matches the reference answer."),
    ("DEP", "CORRECT", "The candidate answer gives Deployed as the stage of development, which is correct."),
    ("DEP", "CORRECT", "The candidate reports the stage as Deployed, identical to the reference."),
    ("DEP", "CORRECT", "Deployed is the reference answer and the candidate states Deployed."),
    ("DEP", "CORRECT", "The candidate says the use case is Deployed, which agrees with the reference."),
    ("DEP", "CORRECT", "The stage of development stated by the candidate, Deployed, is correct."),
    ("DEP", "CORRECT", "The candidate's answer states Deployed, the same stage as the reference."),
    ("DEP", "CORRECT", "Candidate correctly gives the stage of development as Deployed."),
    ("NH", "CORRECT", "The candidate states the determination is Not High-impact, which matches the reference answer."),
    ("NH", "CORRECT", "The candidate correctly identifies the high-impact determination as Not High-impact."),
    ("NH", "CORRECT", "Candidate answer matches the reference answer of Not High-impact."),
    ("NH", "CORRECT", "The candidate says the use case was determined to be Not High-impact, matching the reference."),
    ("NH", "CORRECT", "The candidate's answer, Not High-impact, is the same as the reference."),
    ("NH", "CORRECT", "The candidate gives the reference determination, Not High-impact."),
    ("NH", "CORRECT", "The candidate correctly reports Not High-impact."),
    ("NH", "CORRECT", "Not High-impact is correctly stated by the candidate."),
    ("NH", "CORRECT", "The candidate's determination of Not High-impact is consistent with the reference."),
    ("NH", "CORRECT", "The candidate identifies the determination as Not High-impact, in agreement with the reference."),
]
# The one reply of FIXER_CLEAR that is lost: "states it" is a pronoun where the tie rule wants the value or a word of
# agreement. It is counted as unparseable, never as anything else.
FIXER_CLEAR_LOST = ["Not High-impact is the reference and the candidate states it."]

# --- what the round 4 reader still reads flatteringly -------------------------------------------------------------
# (context, verdict, reason, with the question, without the question): True where the verdict still comes back.
STILL_READ_FLATTERINGLY: list[tuple[str, str, str, bool, bool]] = [
    # with the question: a reason built only from list words that says nothing, or that takes the verdict back
    ("DEPW", "CORRECT", "The candidate gives a stage, and the reference gives a stage too.", True, True),
    # these two are caught with the question since round 5 (a sentence that gives something, and what a sentence
    # says of the candidate must be a refusal); without the question they are still read as DECLINED
    ("UHW", "DECLINED", "The candidate declines. The agency is in the answer.", False, True),
    ("UHW", "DECLINED", "The candidate has the answer. It declines to say so.", False, True),
    # without the question no value is known: one value stated, nothing to compare it with
    ("DEPW", "CORRECT", "Candidate states Pilot.", False, True),
    ("EPAW", "CORRECT", "The candidate names the Bureau of Mines.", False, True),
    ("EPAW", "CORRECT", "Candidate says the Dept. of Energy, reference EPA.", False, True),
    ("EPAW", "CORRECT", "Navy was given. The right one is EPA.", False, True),
    ("UHW", "DECLINED", "The candidate declines; the agency is given as the navy.", False, True),
    # without the question: a mismatch phrase that is on no list
    ("DEPW", "CORRECT", "The candidate's answer is a world away from the reference.", False, True),
    ("DEPW", "CORRECT", "The candidate's answer garbles the reference.", False, True),
]
