"""Round 4 (fourth review): the README, REVIEW_NOTES_r4.md and the results template say what the code does.

Every example the README gives for a round 4 rule is run here, and every count it states for a list or for
one of the kit's own sets is counted here, so that a later change to a rule fails a test until the sentence
is corrected with it.
"""
from __future__ import annotations

import re

import judge_replies_r4 as replies
import test_review_r2_exact as exact_tests
import test_review_r4_judge as judge_tests
from conftest import KIT_DIR
from kitlib import evalloop, pricing, scoring, state

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
NOTES = (KIT_DIR / "REVIEW_NOTES_r4.md").read_text(encoding="utf-8")
# Round 5 changed the size of one list and caught two of the known limits; the record of that is REVIEW_NOTES_r5.md.
NOTES_R5 = (KIT_DIR / "REVIEW_NOTES_r5.md").read_text(encoding="utf-8")
TEMPLATE = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
U = scoring.UNPARSEABLE
EPA = "Environmental Protection Agency"


def section(number: int) -> str:
    return re.split(r"^## \d+\. .*$", README, flags=re.MULTILINE)[number]


def item(number: int) -> str:
    return section(2).split(f"\n{number}. **")[1].split(f"\n{number + 1}. **")[0]


def run_eval_source() -> str:
    return (KIT_DIR / "50_run_eval.py").read_text(encoding="utf-8")


# --- the dated line and the record of the findings ---------------------------------------------------------------

def test_section_8_opens_with_the_dated_round_4_line_and_its_numbers_add_up():
    text = section(8).lstrip()
    match = re.match(r"\*\*Reviewed independently a fourth time on 2026-10-07 \(round 4\): (\d+) findings for this kit "
                     r"\((\d+) major, (\d+) minor\), (\d+) fixed, (\d+) fixed in part with the rest stated as a limit "
                     r"\(listed in `REVIEW_NOTES_r4\.md`\)\.\*\*", text)
    assert match
    findings, major, minor, fixed, in_part = map(int, match.groups())
    assert (findings, major + minor, fixed + in_part) == (16, 16, 16)
    assert text.index("round 4") < text.index("Rehearsed on real model text") < text.index("(round 2)") < text.index("(round 1)")
    assert "none of the fixes has been run against AWS" in text.split("\n")[0]
    # bad news first: what is still wrong stands before what was done
    assert text.index("What is still wrong or unproven after round 4, bad news first:") < text.index("What was done about each finding")


def test_the_notes_list_every_finding_with_an_outcome():
    table = NOTES.split("## 3. Every finding and what happened to it")[1].split("## 4.")[0]
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| Finding")]
    assert len(rows) == 16
    for row in rows:
        assert "FIXED" in row or "STATED AS A LIMIT" in row, row[:60]
    in_part = [row for row in rows if "STATED AS A LIMIT" in row]
    assert len(in_part) == 5 and all("FIXED" in row for row in in_part)
    majors = [row for row in rows if "MAJOR" in row.split("|")[1]]
    assert len(majors) == 2
    assert "Nothing here was run against AWS." in NOTES.split("\n")[2]
    assert NOTES.index("## 1. What is still wrong, worst first") < NOTES.index("## 2.") < NOTES.index("## 3.")


def test_the_readme_points_to_the_notes_and_the_notes_are_part_of_the_kit():
    assert (KIT_DIR / "REVIEW_NOTES_r4.md").is_file()
    assert README.count("`REVIEW_NOTES_r4.md`") >= 3
    assert chr(0x2014) not in NOTES


def test_the_test_counts_agree_between_the_readme_and_the_notes():
    in_readme = re.search(r"([\d,]+) of them are in `tests/test_review_r4_\*\.py`, written for the round 4 findings; run against "
                          r"the kit as it was reviewed in round 4, ([\d,]+) of those ([\d,]+) fail and 18 more cannot be loaded", section(8))
    assert in_readme and in_readme.group(1) == in_readme.group(3)
    assert int(in_readme.group(2).replace(",", "")) < int(in_readme.group(1).replace(",", ""))
    in_notes = re.search(r"([\d,]+) tests in all; run against the kit as it was reviewed, ([\d,]+) of them fail and 18 more cannot "
                         r"be loaded, because the file they read did not exist\. The whole suite is ([\d,]+) tests", NOTES)
    assert in_notes and in_notes.group(1, 2) == in_readme.group(1, 2)
    total = re.search(r"`python -m pytest -q`: ([\d,]+) tests passed, 0 failed", section(8)).group(1)
    # Changed in the documentation pass after round 4. Until then the README's total had to equal the total in
    # the round 4 notes. START_HERE.md came with tests of its own, and the notes are the record of round 4 and
    # were not rewritten, so the README's total is now the notes' total plus the tests added since, which the
    # README counts in the same bullet and which are counted here from the file itself.
    later = re.search(r"(\d+) of them are in `tests/test_start_here\.py`, added with `START_HERE\.md` after round 4", section(8))
    assert later, "section 8 should say how many tests came with START_HERE.md"
    in_file = len(re.findall(r"^def test_", (KIT_DIR / "tests" / "test_start_here.py").read_text(encoding="utf-8"), flags=re.M))
    assert int(later.group(1)) == in_file
    # Round 5 added tests/test_review_r5.py and the fifth reader's two scenario files; section 8 counts them, and
    # tests/test_review_r5.py checks that count against what pytest collects.
    round_5 = re.search(r"([\d,]+) of them are in `tests/test_review_r5\.py` and the fifth reader's two scenario files",
                        section(8))
    assert round_5, "section 8 should say how many tests round 5 added"
    assert (int(in_notes.group(3).replace(",", "")) + in_file + int(round_5.group(1).replace(",", ""))
            == int(total.replace(",", "")))
    assert f"| `tests/` | {total} offline tests" in section(1)
    assert "fixed four times" in section(8)


# --- item 5: the usage and cost line ------------------------------------------------------------------------------

def test_item_5_says_what_the_usage_line_counts_and_what_it_does_not():
    text = item(5)
    for words in ("a call that failed or was cut off before its answer arrived", "counted once",
                  "Whether AWS bills those is not known to this kit", "`last_question_calls.json`", '"interrupted" row',
                  "missing without a warning", "NOT COUNTED"):
        assert words in text, words
    assert text.index("What that figure leaves out, bad news first") < text.index("Everything else is counted")
    source = run_eval_source()
    for words in ("This counts every call that was answered, in every attempt.", "Not counted here: a call that failed or was "
                  "cut off before its answer arrived", "NOT COUNTED: the record of the calls of", 'CALLS_RECORD = "last_question_calls.json"'):
        assert words in source, words
    assert "After a `--resume` that figure includes the calls that succeeded in the attempts that failed." not in README
    assert "`last_question_calls.json`" in section(1)


def test_item_5_gives_the_estimate_without_the_guardrail():
    without = pricing.estimate_eval_run(120, 5, 922, "amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0", "managed", use_guardrail=False)
    assert without["parts_usd"]["guardrail_grounding"] == 0 and f"{without['total_usd']:.2f}" == "0.18"
    assert "(with `--no-guardrail` without the grounding line: about $0.18)" in item(5)
    assert "NOT APPLIED (--no-guardrail)" in run_eval_source()


# --- item 8: exact match ---------------------------------------------------------------------------------------------

def score(kind: str, expected: str, answer: str) -> dict:
    return exact_tests.score(kind, expected, answer)


def test_item_8_lists_the_second_list_and_its_count():
    text = item(8)
    phrases = scoring.LEAD_IN_PHRASES["common"]
    assert f"a second list of {len(phrases)} phrases (`LEAD_IN_PHRASES`)" in text and len(phrases) == 37
    openers = sorted({phrase.rsplit(" the ", 1)[0] for phrase in phrases if " the " in phrase and not phrase.startswith("as of")})
    assert openers == ["as stated in", "based on", "per", "stated in"]
    for phrase in openers + ["as of the", "sure", "has a", "classified as", "listed under"]:
        assert f'"{phrase}"' in text, phrase
    assert len([phrase for phrase in phrases if phrase.startswith(tuple(openers))]) == 4 * 8 and "one of the eight sources" in text
    assert f"one short list of {sum(len(v) for v in scoring.FILLER_PHRASES.values())} phrases" in text      # as rounds 2 and 3 left it
    assert "two short lists" in section(1)


def test_every_round_4_example_in_item_8_is_scored_the_way_the_readme_says():
    text = item(8)
    credited = [("stage", "Deployed", "Deployed!"), ("stage", "Deployed", "It has a stage of development of Deployed."),
                ("stage", "Pre-deployment", "Pre deployment"), ("high_impact", "High-impact", "High - impact"),
                ("agency", "Department of Veterans Affairs", "VA (Department of Veterans Affairs)"),
                ("agency", "Department of the Treasury", "Department of Treasury"),
                ("stage", "Deployed", "Deployed.\n\nThe stage of development is Deployed."),
                ("stage", "Deployed", "Deployed, according to passage 1."), ("stage", "Deployed", "Per document 2, it is Deployed.")]
    for kind, expected, answer in credited:
        assert score(kind, expected, answer)["note"] == "match", answer
    for shown in ('"Deployed!"', '"a stage of development of Deployed"', '"Pre deployment"', '"High - impact"',
                  '"VA (Department of Veterans Affairs)"', '"Department of Treasury"', '"passage 1"', '"document 2"'):
        assert shown in text, shown
    refused = [("stage", "Deployed", "It is != Deployed"), ("high_impact", "Not High-impact", "It is not, High-impact."),
               ("high_impact", "High-impact", "It was_determined to be High-impact."),
               ("agency", EPA, f'The {EPA} reported the AI use case named "AI Use Case Inventory".'),
               ("agency", EPA, f"The agency was reported; is the {EPA} named"),
               ("stage", "Deployed", "Deployed. Deployed. Deployed. Deployed.")]
    for kind, expected, answer in refused:
        got = score(kind, expected, answer)
        assert got["exact"] is False and got["note"].startswith("unclear"), (answer, got)
    for shown in ('"!="', '"not, High-impact"', '"was_determined to be"', 'named "AI Use Case Inventory"', "after a semicolon",
                  "four times or more is unclear"):
        assert shown in text, shown
    assert score("stage", "Deployed", "Deployed. Deployed. Deployed.")["note"] == "match"       # "two or three times"
    assert "the same value written two or three times counts once" in text


def test_item_8_names_the_answer_that_is_still_credited():
    still = "It was reported, is the answer the Environmental Protection Agency"
    assert score("agency", EPA, still)["exact"] is True
    assert f'One is still credited: "{still}"' in item(8) and still in NOTES
    assert item(8).index("Bad news first: it has credited answers a person would reject") < item(8).index("How it reads an answer")
    assert "1 of the 111 a person would reject (3 before)" in item(8) and "73 of the 189 a person would accept as not correct (85 before)" in item(8)
    assert "it still credits 1 of the 111 a person would reject" in section(7)
    assert score("stage", "Deployed", "Deployed is a stage of development.")["exact"] is True
    assert "Deployed is a stage of development." in section(8) and "Deployed is a stage of development." in NOTES


def test_what_the_notes_call_still_lost_is_still_lost():
    for kind, expected, answer in (("stage", "Deployed", "As of May 2025 it is Deployed."),
                                   ("stage", "Deployed", "The use case is currently in the Deployed stage."),
                                   ("agency", EPA, "The EPA, or EPA, reported it."),
                                   ("stage", "Pre-deployment", "Pre-\ndeployment")):
        assert score(kind, expected, answer)["exact"] is False, answer
    for shown in ("As of May 2025 it is Deployed.", "is currently in the Deployed stage", "The EPA, or EPA, reported it."):
        assert shown in NOTES, shown
    assert '"is currently in the Deployed stage"' in section(8)
    false_credit, lost = exact_tests.own_counts()
    assert f"On the kit's own 270 hand-labelled answers: false credit {len(false_credit)}, lost {len(lost)} (48 before)." in NOTES
    assert f"false credit 0 of 270 and lost credit {len(lost)} of 270 on the fixer's own set (48 before round 4)" in section(8)
    refusal = scoring.DECLINE_SENTENCE
    for reworded in (f'"{refusal}"', refusal + " [1]", "I'm sorry, but " + refusal[0].lower() + refusal[1:], refusal + " Please ask another question."):
        assert not scoring.is_decline(reworded), reworded


# --- item 9: the judge reader ----------------------------------------------------------------------------------------

def test_item_9_states_the_sizes_of_the_lists():
    text = item(9)
    assert (f"`JUDGE_TIE_WORDS` and `JUDGE_PRO_FORMS`, {len(scoring.JUDGE_TIE_WORDS)} and {len(scoring.JUDGE_PRO_FORMS)} words, "
            f"for CORRECT; `JUDGE_REFUSAL_WORDS`, {len(scoring.JUDGE_REFUSAL_WORDS)}, for DECLINED") in text
    assert f"`JUDGE_MISMATCH_WORDS`, {len(scoring.JUDGE_MISMATCH_WORDS)} patterns" in text
    assert f"one of {len(scoring.CONTRADICTS_CORRECT)} patterns (`CONTRADICTS_CORRECT`" in text
    for name in ("JUDGE_TIE_WORDS", "JUDGE_PRO_FORMS", "JUDGE_REFUSAL_WORDS", "JUDGE_SAYS_IT_IS_NOT_THERE",
                 "JUDGE_MISMATCH_WORDS", "JUDGE_ADDS_TO_A_REFUSAL", "JUDGE_OUTSIDE_AGAINST", "CONTRADICTS_CORRECT",
                 "CONTRADICTS_DECLINED"):
        size = len(getattr(scoring, name))
        assert any(f"`{name}` ({size}" in notes or f"`{name}`, {size} " in notes for notes in (NOTES, NOTES_R5)), name
    capitalised, _, _ = scoring._everyday_names(judge_tests.frozen_sets())
    assert len(capitalised) == 10 and "ten such names in the inventory" in NOTES


def test_item_9_puts_the_round_4_news_first_and_names_what_is_still_read_flatteringly():
    text = item(9)
    assert text.index("Round 4, bad news first.") < text.index("The reply is read as CORRECT or DECLINED")
    for words in ("30 with the question and 37 without", "58 of 82", "37 of 60", "0 read flatteringly with the question, 2 without",
                  "27 of that reader's 123 clear verdicts with the question (32 before) and 45 without (49 before)"):
        assert words in text, words
    named_with = [reason for _, _, reason, with_question, _ in replies.STILL_READ_FLATTERINGLY if with_question]
    assert len(named_with) == 1               # 3 until round 5, whose rules catch the two DECLINED ones (REVIEW_NOTES_r5.md)
    for reason in named_with:
        assert f'"{reason}"' in text and reason in NOTES, reason
    for key, word, reason, with_question, without_question in replies.STILL_READ_FLATTERINGLY:
        assert (judge_tests.verdict(key, reason, word) == word) is with_question
        assert (judge_tests.verdict(key, reason, word, with_question=False) == word) is without_question
        if not with_question and "world away" not in reason and "garbles" not in reason and "the navy" not in reason \
                and "Navy was given" not in reason:
            assert f'"{reason}"' in text, reason
    assert '"is a world away from", "garbles"' in text
    assert f"{len(replies.STILL_READ_FLATTERINGLY)} that are still read flatteringly" in NOTES


def test_item_9_says_which_round_3_limits_are_caught_now():
    text = item(9)
    assert "Three limits of the round 3 reader are caught since round 4" in text
    both = [("EPAW", "CORRECT", "The candidate says DOE; the reference says EPA."), ("UA", "DECLINED", "No information that it declines.")]
    for key, word, reason in both:
        assert f'"{reason}"' in text
        assert judge_tests.verdict(key, reason, word) == U and judge_tests.verdict(key, reason, word, with_question=False) == U
    mines = "The candidate names the Bureau of Mines."
    assert judge_tests.verdict("EPAW", mines) == U and judge_tests.verdict("EPAW", mines, with_question=False) == "CORRECT"
    assert "read on its own, without the question, that reply still comes back CORRECT" not in README


def test_the_lost_replies_item_9_added_in_round_4_are_lost():
    text = item(9)
    lost = [("EPA", replies.j("CORRECT", "Cannot fault it.")), ("EPA", replies.j("CORRECT", "The answer is error-free.")),
            ("EPA", '{"verdict": "CORRECT", "reason": "Matches the reference.", "score": 1}'),
            ("DEPW", "Verdict: INCORRECT (the candidate says Pilot)"), ("DEP", "Verdict: CORRECT " + chr(0x2705)),
            ("NH", replies.j("CORRECT", "Not High-impact is the reference and the candidate states it."))]
    for key, reply in lost:
        assert judge_tests.read(key, reply)["verdict"] == U, reply
    for shown in ('"Cannot fault it."', '"The answer is error-free."', '`"score": 1`', '"Verdict: INCORRECT (the candidate says Pilot)"',
                  '"Not High-impact is the reference and the candidate states it."'):
        assert shown in text, shown
    assert replies.FIXER_CLEAR_LOST == ["Not High-impact is the reference and the candidate states it."]
    assert f"{len(replies.FIXER_AGAINST)} replies whose reason speaks against the verdict" in NOTES
    assert f"{len(replies.FIXER_CLEAR)} clear replies (1 lost" in NOTES


def test_the_examples_of_the_rules_in_the_notes_are_refused():
    for key, word, reason in (("EPAW", "CORRECT", "The candidate says the Pentagon; the reference says EPA."),
                              ("DEPW", "CORRECT", "The candidate's answer is at odds with the reference."),
                              ("EPAW", "CORRECT", "The candidate rejects EPA."),
                              ("NHW", "CORRECT", "The reference is Not High-impact; the candidate says it is."),
                              ("DEP", "CORRECT", "It is."),
                              ("UHW", "DECLINED", "The candidate declines in part."),
                              ("UHW", "DECLINED", "The candidate nearly declines."),
                              ("UHW", "DECLINED", "The candidate declines and volunteers the Navy."),
                              ("DEPW", "CORRECT", "The candidate says piloting; the reference says Deployed.")):
        assert judge_tests.verdict(key, reason, word) == U, reason
    assert judge_tests.verdict("EPAW", "The candidate says Energy; the reference says EPA.", with_question=False) == U
    assert judge_tests.read("DEP", "**Verdict:** CORRECT")["verdict"] == "CORRECT"
    assert judge_tests.verdict("UH", "The candidate states that the information is not available in the passages.", "DECLINED") == "DECLINED"
    assert '"the information is not available in the passages" and the like count as saying so' in item(9)
    assert judge_tests.verdict("UH", "The candidate states that the information is not available in the passages.", "DECLINED",
                               with_question=False) == U
    assert judge_tests.verdict("UHH", "The candidate declines but then names the Department of Labor.", "INCORRECT") == "INCORRECT"


# --- item 18, sections 4 and 6, the template --------------------------------------------------------------------------

def test_item_18_names_the_round_4_guards():
    text = item(18)
    assert f"scoring version `{scoring.SCORING_VERSION}`" in text and scoring.SCORING_VERSION == "2026-10-08.r5"   # r4 until round 5
    assert "a fingerprint of `build/eval/eval_set_meta.json`" in text and '"eval_set_meta_sha256"' in run_eval_source()
    assert "when `run_config.json` itself cannot be read" in text and "cannot be read" in run_eval_source()
    assert "with the whole judge reply (until round 4 only its first 500 characters)" in text
    assert "`2026-10-07.r4` since round 4" in section(8)


def test_the_columns_and_rows_the_readme_names_exist():
    for column in ("gen_stop_reason", "judge_stop_reason"):
        assert column in evalloop.CSV_COLUMNS and f"`{column}`" in section(4)
    assert "`max_tokens` means the text was cut at the token limit" in section(4)
    assert "what is not counted" in section(6) and "the WARNING line about texts cut at the token limit" in section(6)
    assert "| Anything the usage line of summary.md says is NOT COUNTED (copy the sentence) | |" in TEMPLATE
    assert "| Answers and judge replies that ended at the token limit (the WARNING line of summary.md, if there is one) | |" in TEMPLATE
    assert "| Earlier failed or interrupted attempts included in the usage (after --resume) | |" in TEMPLATE
    assert "a second, different value" in TEMPLATE and "so this rate can undercount too" in TEMPLATE


def test_section_5_names_the_stale_state_file_and_section_8_the_data_source_id():
    assert "a state file that was put back from an older copy is believed as it stands" in section(5)
    assert "The data source id cannot be on record before AWS answers `CreateDataSource`" in section(8)
    source = (KIT_DIR / "kitlib" / "resources.py").read_text(encoding="utf-8")
    assert "data_source_id=" in source and "PENDING" in source and isinstance(state.PENDING, str)
    assert "with the id marked as not known yet" in NOTES
    ignored = (KIT_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".state.json*", "*.state.json", "*state*.json.bak"):
        assert entry in ignored and entry in NOTES
