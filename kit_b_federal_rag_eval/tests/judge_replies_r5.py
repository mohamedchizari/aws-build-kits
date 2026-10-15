"""Round 5 (fifth review, reader B): judge replies for F1, F2 and F5.

READER_R5 are the judge cases of the reader's attack suite (attack/cases.json and cases2.json of the review folder,
hashed by the reader before any case ran), copied word for word with the outcome the reader expects: the F1, F2 and F5
cases and the reader's controls. kind "U_budget" is an unanswerable budget question, "U_heldout" a held-out agency
question, as in the reader's runner.

FIXER_R5_* were written by the fixer. FIXER_R5_NOT_A_REFUSAL and FIXER_R5_REFUSALS were written BEFORE they were run on
either reader; on their first run the round 5 draft refused 29 of the 30 and read 22 of the 25 refusals, and the draft
was then changed (the round 4 reader: 5 of 30 and 15 of 25). FIXER_R5_SECOND_SET was written after that change and
before its own first run: 40 of 46 read as a person reads them on that run, 43 of 46 now (round 4: 27 of 46).
FIXER_R5_HUNTED were written while attacking the round 5 draft, after it existed; 6 of them were read as DECLINED by a
draft and made it stricter. One more is still read so: README section 2, item 9, and STILL_READ_FLATTERINGLY. They are not a measurement: the person who changed the reader wrote them.
"""
from __future__ import annotations

# (kind, expected answer, the judge's whole reply, "==" or "!=", verdict)
READER_R5: list[tuple[str, str | None, str, str, str]] = [
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate\'s answer contains a budget figure that the documents lack."}', '!=', 'DECLINED'),  # F1-01
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate answer includes a budget figure not in the documents."}', '!=', 'DECLINED'),  # F1-02
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate\'s response holds a budget figure the inventory does not contain."}', '!=', 'DECLINED'),  # F1-03
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate indicates a budget amount; the record is silent on budget."}', '!=', 'DECLINED'),  # F1-04
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate explains the budget figure, which is not in the documents."}', '!=', 'DECLINED'),  # F1-05
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate acknowledged the budget figure; the documents do not contain it."}', '!=', 'DECLINED'),  # F1-06
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate\'s answer is a budget figure; there is no budget data in the record."}', '!=', 'DECLINED'),  # F1-07
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate reported a figure for the budget; the passages do not contain a budget."}', '!=', 'DECLINED'),  # F1-08
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate reports the budget amount that the documents do not contain."}', '!=', 'DECLINED'),  # F1-09
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate determined the budget amount; the documents do not contain it."}', '!=', 'DECLINED'),  # F1-10
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate found the budget figure. The record lacks a budget figure."}', '!=', 'DECLINED'),  # F1-11
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate reported the budget amount, which is not recorded."}', '!=', 'DECLINED'),  # F1-12
    ('U_heldout', None, '{"verdict": "DECLINED", "reason": "The candidate\'s answer contains an agency the documents do not contain."}', '!=', 'DECLINED'),  # F1-13
    ('U_heldout', None, '{"verdict": "DECLINED", "reason": "The candidate\'s answer is an agency that is not in the documents."}', '!=', 'DECLINED'),  # F1-14
    ('U_heldout', None, '{"verdict": "DECLINED", "reason": "The candidate determined the agency; the record lacks it."}', '!=', 'DECLINED'),  # F1-15
    ('U_budget', None, "DECLINED. The candidate's answer includes a budget figure that is not in the documents.", '!=', 'DECLINED'),  # F1-16
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "The candidate matches the reference. The impact is high."}', '!=', 'CORRECT'),  # F2-01
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "The candidate matches the reference. Yes, the impact is high."}', '!=', 'CORRECT'),  # F2-02
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "The candidate states the reference answer. Its impact is high."}', '!=', 'CORRECT'),  # F2-03
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "Matches the reference; impact is high."}', '!=', 'CORRECT'),  # F2-04
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "The candidate matches the reference. It was determined to be high in impact."}', '!=', 'CORRECT'),  # F2-05
    ('high_impact', 'Not High-impact', 'CORRECT. The candidate matches the reference. The impact is high.', '!=', 'CORRECT'),  # F2-06
    ('high_impact', 'Not High-impact', 'Verdict: CORRECT\nReason: The candidate matches the reference; the impact is high.', '!=', 'CORRECT'),  # F2-07
    ('stage', 'Deployed', '{"verdict": "CORRECT", "reason": "The candidate matches the reference. The use case is in development."}', '!=', 'CORRECT'),  # F2-08
    ('stage', 'Retired', '{"verdict": "CORRECT", "reason": "The candidate matches the reference. The use case is in development."}', '!=', 'CORRECT'),  # F2-09
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate says it cannot answer."}', '==', 'DECLINED'),  # C_declined_ok-01
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate declines because the documents lack budget data."}', '==', 'DECLINED'),  # C_declined_ok-02
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate correctly says it cannot answer; the documents do not contain the budget."}', '==', 'DECLINED'),  # C_declined_ok-03
    ('U_heldout', None, '{"verdict": "DECLINED", "reason": "The candidate declines to answer."}', '==', 'DECLINED'),  # C_declined_ok-04
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate\'s reply gives the budget figure from the documents, which lack it."}', '!=', 'DECLINED'),  # C_declined_refused-01
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "Candidate provides a figure; information is not available in the documents."}', '!=', 'DECLINED'),  # C_declined_refused-02
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate notes the budget amount though the record lacks it."}', '!=', 'DECLINED'),  # C_declined_refused-03
    ('U_heldout', None, '{"verdict": "DECLINED", "reason": "The candidate answered Department of Energy"}', '!=', 'DECLINED'),  # C_declined_refused-04
    ('U_heldout', None, '{"verdict": "DECLINED", "reason": "The candidate declines, then states Department of Energy."}', '!=', 'DECLINED'),  # C_declined_refused-05
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "Candidate correctly states Not High-impact, matching reference."}', '==', 'CORRECT'),  # C_correct_ok-01
    ('agency', 'Department of Energy', '{"verdict": "CORRECT", "reason": "The candidate states Department of Energy, matching the reference."}', '==', 'CORRECT'),  # C_correct_ok-02
    ('stage', 'Pilot', '{"verdict": "CORRECT", "reason": "Candidate correctly states Pilot, matching reference."}', '==', 'CORRECT'),  # C_correct_ok-03
    ('high_impact', 'High-impact', '{"verdict": "CORRECT", "reason": "The candidate states Not High-impact, the same as the reference."}', '!=', 'CORRECT'),  # C_correct_refused-01
    ('stage', 'Pilot', '{"verdict": "CORRECT", "reason": "The candidate matches the reference. It has been deployed."}', '!=', 'CORRECT'),  # C_correct_refused-02
    ('agency', 'Department of Energy', '{"verdict": "CORRECT", "reason": "The candidate is not correct"}', '!=', 'CORRECT'),  # C_correct_refused-03
    ('high_impact', 'Not High-impact', '{"verdict": "CORRECT", "reason": "The candidate\'s answer matches the reference. The use case is high impact."}', '!=', 'CORRECT'),  # C_correct_refused-04
    ('agency', 'Department of Energy', '{"verdict": "CORRECT", "reason": "The candidate says DOE; the reference says EPA."}', '!=', 'CORRECT'),  # C_correct_refused-05
    ('agency', 'Environmental Protection Agency', '{"verdict": "CORRECT", "reason": "The candidate says Energy; the reference says EPA."}', '!=', 'CORRECT'),  # C_correct_refused-06
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate states it cannot answer from the provided documents, which is appropriate since the reference indicates no answer."}', '==', 'DECLINED'),  # F5-01
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate declined to answer, which is correct since there is no answer."}', '==', 'DECLINED'),  # F5-02
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "Candidate explicitly declines, stating it cannot answer from the inventory documents."}', '==', 'DECLINED'),  # F5-03
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate uses the refusal sentence."}', '==', 'DECLINED'),  # F5-04
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate indicates that it cannot answer based on the documents."}', '==', 'DECLINED'),  # F5-05
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate\'s response is the refusal sentence, as expected."}', '==', 'DECLINED'),  # F5-06
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate explicitly states it cannot answer the question."}', '==', 'DECLINED'),  # F5-07
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate correctly declines to answer."}', '==', 'DECLINED'),  # C_declined_ok2-01
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate says the information is not available in the documents."}', '==', 'DECLINED'),  # C_declined_ok2-02
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate refuses to answer since the documents do not include the budget."}', '==', 'DECLINED'),  # C_declined_ok2-03
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate properly abstains from answering."}', '==', 'DECLINED'),  # C_declined_ok2-04
    ('U_budget', None, '{"verdict": "DECLINED", "reason": "The candidate does not provide an answer and states it cannot answer from the documents."}', '==', 'DECLINED'),  # C_declined_ok2-05
]

# DECLINED would be credit for each of these; a person reads that the candidate gave something.
FIXER_R5_NOT_A_REFUSAL: list[str] = [
    'The candidate gives a budget figure the documents lack.',
    "The candidate's answer holds the agency; the record does not contain it.",
    'The candidate states the budget amount, which the documents lack.',
    'A budget figure is reported by the candidate, which the documents lack.',
    "The candidate's figure is not in the documents.",
    'The answer includes a budget amount that is not recorded.',
    'It includes a budget figure that is not in the documents.',
    'The candidate answered with a budget figure; the record lacks one.',
    'The candidate indicates the budget; the documents do not contain it.',
    'The candidate reports a figure. No budget is recorded in the documents.',
    "The candidate's response contains the agency the record does not contain.",
    'The candidate found an agency that is not in the documents.',
    'The candidate explains the budget figure: it is not in the documents.',
    'The candidate has an answer: a budget figure the documents lack.',
    'Its answer is a budget figure the record lacks.',
    'The response: a budget figure that is not recorded.',
    "The candidate's answer, a budget figure, is not in the documents.",
    "The budget figure in the candidate's answer is not in the documents.",
    "In the candidate's answer there is a budget figure; it is not in the documents.",
    'The candidate states that a budget figure is in the documents.',
    'The candidate correctly reports the budget figure that the documents lack.',
    'The candidate says that the documents do not contain the budget figure it found.',
    'The candidate declines; it has a budget figure the documents lack.',
    "The candidate's reply is an agency name; the inventory does not record it.",
    'The candidate holds that the budget is known; the documents lack it.',
    'The candidate determined an amount for the budget, not in the documents.',
    'The agency given by the candidate is not in the documents.',
    'The candidate notes a budget figure, and the record is silent on budget.',
    'A figure from the candidate is not in the documents.',
    "The candidate's answer has a budget amount the record lacks.",
]

# Ordinary refusals: each must be read as DECLINED.
FIXER_R5_REFUSALS: list[str] = [
    'The candidate declines to answer because the information is not in the documents.',
    'The candidate correctly states that it cannot answer from the inventory documents provided.',
    'Candidate response: I cannot answer this from the inventory documents provided.',
    'The candidate uses the exact refusal sentence, which is appropriate.',
    'The candidate refuses to answer, which is the expected behavior since the reference is NO ANSWER.',
    'The candidate appropriately declines to provide an answer.',
    'The candidate does not provide an answer, stating that the documents do not contain the information.',
    "The candidate's response is a refusal, which is correct.",
    'The candidate explicitly states it cannot answer from the documents provided.',
    'The candidate abstains from answering, as the documents lack the budget.',
    'The candidate states that it cannot answer, and the reference is NO ANSWER.',
    "The candidate's answer is the refusal sentence.",
    'The candidate says it cannot answer based on the inventory documents.',
    'The candidate declined. This is the expected behavior.',
    'The candidate indicates the information is not available, which is appropriate.',
    'Candidate declines; no answer is given.',
    'The candidate gives no answer, which is correct because there is no answer in the documents.',
    'The candidate correctly refuses since no budget figure is recorded.',
    'The candidate states that the documents do not contain the budget and declines to answer.',
    'The candidate acknowledges that the passages do not contain the agency.',
    'The candidate refused to answer, as expected.',
    'The response declines to answer.',
    "The candidate's response correctly indicates that it cannot answer.",
    'The candidate declined to answer the question, which is appropriate given the lack of information.',
    'The candidate responded with the refusal sentence.',
]

# (kind, expected answer, verdict word, what a person reads: the verdict word or "U", reason). kind "U": the budget question.
FIXER_R5_SECOND_SET: list[tuple[str, str | None, str, str, str]] = [
    ('high_impact', 'Not High-impact', 'CORRECT', 'CORRECT', 'The candidate states the high-impact determination is Not High-impact, matching the reference.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'CORRECT', "The candidate's high impact determination matches the reference."),
    ('high_impact', 'Not High-impact', 'CORRECT', 'CORRECT', 'The candidate correctly says the use case is not high-impact.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'CORRECT', 'Candidate answer matches reference: Not High-impact.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'CORRECT', 'The candidate gives the same high-impact status as the reference.'),
    ('stage', 'Deployed', 'CORRECT', 'CORRECT', 'The candidate states the stage of development is Deployed, matching the reference.'),
    ('stage', 'Deployed', 'CORRECT', 'CORRECT', "The candidate's development stage matches the reference."),
    ('stage', 'Deployed', 'CORRECT', 'CORRECT', 'Candidate correctly identifies the stage as Deployed.'),
    ('stage', 'Deployed', 'CORRECT', 'CORRECT', 'The candidate states the use case is deployed, which matches the reference.'),
    ('high_impact', 'High-impact', 'CORRECT', 'CORRECT', 'The candidate states High-impact, matching the reference.'),
    ('high_impact', 'High-impact', 'CORRECT', 'CORRECT', 'The candidate says the use case is high impact, same as the reference.'),
    ('agency', 'Environmental Protection Agency', 'CORRECT', 'CORRECT', 'The candidate names EPA, matching the reference.'),
    ('agency', 'Environmental Protection Agency', 'CORRECT', 'CORRECT', "The candidate's answer matches the reference agency."),
    ('high_impact', 'Not High-impact', 'CORRECT', 'U', 'The candidate matches the reference. High impact, it is.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'U', 'The candidate matches the reference; it is high in impact.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'U', 'The candidate states the reference answer. The determination is high.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'U', 'Matches the reference. Impact: high.'),
    ('stage', 'Deployed', 'CORRECT', 'U', 'The candidate matches the reference. The stage is pre-deployment.'),
    ('stage', 'Deployed', 'CORRECT', 'U', 'The candidate matches the reference. The use case is in the development stage.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'U', 'The candidate matches the reference. The use case has high impact.'),
    ('agency', 'Environmental Protection Agency', 'CORRECT', 'U', 'The candidate matches the reference. The impact is high.'),
    ('high_impact', 'Not High-impact', 'CORRECT', 'U', 'The candidate matches the reference, high impact.'),
    ('stage', 'Retired', 'CORRECT', 'U', 'The candidate matches the reference. The use case is in use.'),
    ('stage', 'Retired', 'CORRECT', 'U', 'The candidate matches the reference. It was piloted.'),
    ('U', None, 'DECLINED', 'U', "The candidate's reply names a budget figure; the documents lack it."),
    ('U', None, 'DECLINED', 'U', 'The candidate answer is that the budget is a figure the record lacks.'),
    ('U', None, 'DECLINED', 'U', 'The candidate states a figure for the budget, and the documents are silent.'),
    ('U', None, 'DECLINED', 'U', "The figure is in the candidate's answer; the documents lack it."),
    ('U', None, 'DECLINED', 'U', 'The candidate offers the budget figure, which the documents do not record.'),
    ('U', None, 'DECLINED', 'U', "There is an agency in the candidate's response that the record does not contain."),
    ('U', None, 'DECLINED', 'U', 'The candidate covers the budget amount; it is not recorded.'),
    ('U', None, 'DECLINED', 'U', "The candidate's answer gives an amount; no amount is recorded."),
    ('U', None, 'DECLINED', 'U', 'The response holds a figure. The documents do not contain a budget.'),
    ('U', None, 'DECLINED', 'U', 'The candidate cannot answer from the documents and indicates a figure.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate declines to answer since the documents do not record a budget.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate says it cannot determine the budget from the passages.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate properly states that the information is not in the documents.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate gives no figure and says the record is silent on the budget.'),
    ('U', None, 'DECLINED', 'DECLINED', "The candidate's answer is a refusal, as expected for this question."),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate refuses to give a budget figure because the documents lack one.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate correctly answers with the refusal sentence.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate explains that the documents do not include budget information.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate indicates it has no information about the budget.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate declined, which is appropriate.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate reports that no budget figure is available in the documents.'),
    ('U', None, 'DECLINED', 'DECLINED', 'The candidate does not give a budget figure and states it cannot answer.'),
]
# The three of the second set that are still lost (UNPARSEABLE, never credit). All three were lost before round 5.
FIXER_R5_SECOND_SET_LOST = [
    "The candidate's high impact determination matches the reference.",
    "The candidate gives the same high-impact status as the reference.",
    "The candidate refuses to give a budget figure because the documents lack one.",
]

# Written while attacking the round 5 draft, under DECLINED for the budget question. None may be read as DECLINED.
FIXER_R5_HUNTED: list[str] = [
    "The candidate's answer is the refusal sentence with a budget figure.",
    "The candidate's refusal includes a budget figure.",
    'Budget figure given; the record lacks it.',
    'The documents do not contain the budget figure the candidate determined.',
    'The candidate declines; the budget it reports is not in the documents.',
    'The candidate states the refusal sentence and a budget figure.',
    'The candidate does not decline to answer.',
    'The candidate uses the refusal sentence about a budget figure that is not in the documents.',
    "The candidate's reply, which holds a budget figure, does not answer from the documents.",
    'The candidate declines to answer from the documents, using the budget figure instead.',
    'The candidate cannot answer from the documents, which do not contain the budget figure it gives.',
    'The candidate has the refusal sentence and the budget amount.',
    'The candidate declines. A figure for the budget, not in the documents, is the answer.',
    'The candidate is unable to answer; its answer is a budget figure.',
    'The candidate refuses to answer from the documents and answers from the record instead.',
    'The candidate declines to answer from the documents and gives an answer from memory.',
    'The candidate cannot answer from the documents; the answer it has is a budget figure.',
    'The candidate declines because the budget figure is given in another document.',
    'The candidate abstains, as the budget figure is in its answer.',
    'The candidate says the documents do not contain the budget, so the budget it gives is not from them.',
    'The candidate refuses to answer from the record and indicates the amount is in the documents.',
    "The candidate declines to answer; information on the budget is in the candidate's answer.",
    'The candidate says the record is silent on the budget, and the answer holds a figure for it.',
    'The candidate says the inventory does not record a budget, except the figure in its answer.',
    'The candidate declines to name an agency, and the agency it has is in the documents.',
    "The candidate's response declines, and a budget figure is in it.",
    'The candidate states that it cannot answer, and the agency is the reference.',
    "The candidate notes the documents lack budget data; the candidate's budget figure is from memory.",
    'The candidate declines; the budget figure is from the answer.',
    'The candidate does not give the budget figure from the documents, but from its own knowledge.',
    'The candidate declines: budget figure.',
    'The candidate correctly says it cannot answer; however, a figure is included.',
    'Declines, with a budget figure.',
    'The candidate declines. Budget figure: yes.',
]

# What the round 5 reader still reads as credit with the question (README section 2, item 9 quotes each one). A test
# fails when one of them starts to be caught, so that the README is corrected with it.
STILL_READ_FLATTERINGLY_R5: list[tuple[str, str]] = [
    ("DECLINED", "The candidate's answer is a refusal; its budget figure is not in the documents."),   # "its": the use case's?
]
