"""README.md and RECORD_OF_REVIEWS.md held to what the kit does. Review finding M5 and the shared rules.

A wrong sentence in the README is a defect like any other, and several of the
review's findings were sentences. These tests fail when one of them comes back,
or when the counts in section 8 stop matching the test suite.

Documentation pass of 2026-10-07, after review round 4. The README was shortened to at most
600 lines, and what it said until then stands, word for word, in RECORD_OF_REVIEWS.md under
headings by round. Every test below that pinned a sentence of the README now reads the
sentence where it lives: `section(n)` for the README, `record(title)` for one part of the
record. Where a test guarded a statement that the round 4 findings showed to be wrong, it now
guards the corrected statement, and says so where it stands. No test was deleted.
"""
from __future__ import annotations

import hashlib
import re

import conftest
import pytest
from conftest import ROOT

README = (ROOT / "README.md").read_text(encoding="utf-8")
RECORD = (ROOT / "RECORD_OF_REVIEWS.md").read_text(encoding="utf-8")
FINDINGS = ROOT.parent / "_review_reports" / "round4" / "FINDINGS_round4.md"
HEADINGS = [
    "1. What this is", "2. Problems first", "3. Before you start", "4. Run it",
    "5. Tear it down and prove it", "6. What to record",
    "7. What you can truthfully say afterwards, and what you cannot",
    "8. What was and was not tested", "9. Sources",
]
RECORD_PARTS = [
    "Statements corrected in round 4", "The four rounds in one paragraph", "Round 4", "Round 3", "Round 2",
    "Round 1", "Before the reviews", "Reference text that left the README when it was shortened",
]
CORRECTED, R4, R3, R2, R1, REFERENCE = (RECORD_PARTS[0], "Round 4", "Round 3", "Round 2", "Round 1", RECORD_PARTS[-1])


def section(number: int) -> str:
    start = README.index(f"## {HEADINGS[number - 1]}")
    end = README.index(f"## {HEADINGS[number]}") if number < len(HEADINGS) else len(README)
    return README[start:end]


def flat(text: str) -> str:
    return " ".join(text.split())


def record(title: str) -> str:
    """One part of RECORD_OF_REVIEWS.md, from its `## ` heading to the next one, as one line of text."""
    marks = [(m.group(1), m.start()) for m in re.finditer(r"^## (.+)$", RECORD, flags=re.M)]
    assert [name for name, _ in marks] == RECORD_PARTS, [name for name, _ in marks]
    starts = dict(marks)
    end = min([pos for _, pos in marks if pos > starts[title]], default=len(RECORD))
    return flat(RECORD[starts[title]:end])


def findings() -> str | None:
    """The coordinating account of round 4, when the kit stands beside the review reports."""
    return flat(FINDINGS.read_text(encoding="utf-8")) if FINDINGS.is_file() else None


def test_the_nine_headings_in_order():
    assert re.findall(r"^## (.+)$", README, flags=re.M) == HEADINGS


def test_no_em_dashes_anywhere_in_the_kit():
    for path in list(ROOT.glob("*.md")) + list(ROOT.glob("*.py")) + list(ROOT.glob("*.env")) \
            + list((ROOT / "agent").glob("*.py")) + list((ROOT / "optional_gateway").glob("*")):
        if path.is_file() and path.suffix in {".md", ".py", ".env", ".json"}:
            assert "\u2014" not in path.read_text(encoding="utf-8"), path.name


def test_section_7_says_what_the_owner_did_not_what_the_kit_did():
    """Review M5. Each phrase below credited the owner with the author's work, or claimed
    more than the run can show."""
    said = flat(section(7))
    for overstated in (
        "You built a LangGraph tool-calling agent",
        "You wrote and attached the execution role",
        "You measured cold and warm call latency",
        "and have a check that proves it",
        "You know the Runtime contract first-hand",
    ):
        assert overstated not in said
    for honest in (
        "deployed and operated an agent that the kit supplied",
        "created the execution role from AWS's documented policy",
        "timed first and later calls end to end",
        "found nothing under your prefix in the Regions",
    ):
        assert honest in said, honest
    assert "not a measured cold start" in said


def test_section_7_says_exactly_what_the_answer_check_covers():
    said = flat(section(7))
    assert "That the agent's answers are correct" in said
    assert ("document numbers, Federal Register citations, other numbers of two or more digits, dates, "
            "URLs, counts of documents and phrases in quotation marks") in said
    assert "single digits and anything else with no digits in it were not checked" in said
    # round 4: what the number rule does not read is said here and on the label itself
    assert "nor were numbers in words, two-digit ordinals and two digits that follow letters" in said
    assert "That the agent cannot invent a document or a claim. It can, in words." in said
    # the round 1 sentence is no longer true: dates are compared now
    assert "does not cover titles, agencies, dates or summaries" not in flat(README)
    assert "does not cover titles, agencies, dates or summaries" not in flat(RECORD)


def test_round_2_sentences_stronger_than_the_code_are_gone():
    """Round 2, grounding review, section (a): each of these read stronger than the code."""
    said = flat(README) + " " + flat(RECORD)
    for overstated in (
        "never passes the model's text on unchecked",
        "in any dash, spacing",
        "checks the answer against the tool results without a model",
        "within 20%",
        "at least 80%",
        "is set aside, not fatal",
        "deletes everything, found by name prefix",
    ):
        assert overstated not in said, overstated


def test_section_2_gives_the_bad_news_about_the_answer_check_before_the_good():
    """README section 2 as it is now: what was never run, then what the check does not read, then
    what was measured with its limits first, then money. The sentences this test pinned until the
    documentation pass are pinned in the record by the test below."""
    said = flat(section(2))
    never_run = said.index("Nothing in this kit has been run against AWS, and the kit has never called a model.")
    not_meaning = said.index("The answer check compares identifiers and figures. It does not read meaning.")
    passes = said.index("So these pass with no warning")
    measured = said.index("What was measured on real model text, limits first.")
    unseen = said.index("The check on 88 answers it had not seen")
    assert never_run < not_meaning < passes < measured < unseen < said.index("What can cost money.")
    for limit in ("a returned document presented as the thing you asked for", "a wrong agency",
                  "a real number attached to the wrong document", "an invented rule with no number",
                  "It does not mean \"false\", and no warning does not mean \"true\"",
                  "Open each URL in the block before you rely on an answer."):
        assert limit in said, limit
    # limits before figures, and the bad news about the 88 answers before their table
    assert said.index("not the kit's default") < said.index("| the preparing agent | as before round 3 |")
    assert said.index("has not been measured: the 88 answers below held none") < said.index("| the preparing agent |")
    assert said.index("none of the 88 was misleading, so this set says nothing about what the check catches") \
        < said.index("| clean (70) | 59 | 6 | 5 |")
    for part in ("FROM THE FEDERAL REGISTER API", "MODEL'S SUMMARY", "`WARNING:`", "`NOTE:`"):
        assert part in said, part
    assert "No real model was ever called" not in said


def test_the_record_keeps_what_section_2_said_of_the_check_with_the_bad_news_before_the_good():
    """Moved with its sentences: until the documentation pass this was the test of README section 2.
    The passages stand in the record's reference part in the order they had."""
    said = record(REFERENCE)
    bad = said.index("All of these pass with no warning")
    good = said.index("What the kit does.")
    compared = said.index("What is compared in the model's text")
    assert bad < good < compared
    for limit in ("a claim with no digits in it", "attached to the wrong document",
                  "a single digit standing alone", "it can steer the model",
                  "It does not mean \"false\", and no warning does not mean \"true\""):
        assert limit in said, limit
    # round 3: stand-in models have written answers since; the kit itself has called none
    assert "No real model was ever called" not in flat(RECORD)
    assert "The kit itself has still never called a model." in record(R3)
    assert "the kit has never called a model" in flat(section(2))
    # the three parts, and where the stored text goes
    for part in ("FROM THE FEDERAL REGISTER API", "MODEL'S SUMMARY", "[TRUNCATED]", "TRACELOOP_TRACE_CONTENT"):
        assert part in said, part


def test_the_round_3_rehearsal_line_is_present_and_adds_up():
    """The dated line, rewritten after the second rehearsal pass: both passes, each with what
    the check did before and after. It stands in the record under "Round 3" now."""
    said = record(R3)
    match = re.search(
        r"Rehearsed on real model text on 2026-10-07 \(round 3\), in two passes: (\d+) answers to (\d+) questions, "
        r"(\d+) in each pass, written by two stand-in models \(Claude Haiku and Claude Sonnet, not the kit's default "
        r"model\) from the kit's own final-turn prompts, with the tool calls chosen by an agent and not by the model; "
        r"blind readers labelled the first pass (\d+) clean, (\d+) minor, (\d+) misleading and the second (\d+) "
        r"clean, (\d+) minor, (\d+) misleading\. First pass: before round 3 the check passed (\d+) of the (\d+) "
        r"misleading answers and warned or replaced (\d+) of the (\d+) clean ones; on this code it passes (\d+) of "
        r"the (\d+) and warns or replaces (\d+) of the (\d+)\. Second pass: the check as corrected after the first "
        r"pass passed (\d+) of the (\d+) misleading answers and warned or replaced (\d+) of the (\d+) clean ones; "
        r"on this code it passes (\d+) of the (\d+) and warns or replaces (\d+) of the (\d+)\.", said)
    assert match, "the dated round 3 rehearsal line is missing from the record"
    (answers, questions, per_pass, clean1, minor1, mis1, clean2, minor2, mis2,
     p1_before, p1_of, f1_before, f1_of, p1_now, p1_of_now, f1_now, f1_of_now,
     p2_before, p2_of, f2_before, f2_of, p2_now, p2_of_now, f2_now, f2_of_now) = map(int, match.groups())
    assert answers == 2 * per_pass == 4 * questions == 120
    assert clean1 + minor1 + mis1 == clean2 + minor2 + mis2 == per_pass
    assert (clean1, minor1, mis1, clean2, minor2, mis2) == (33, 14, 13, 39, 9, 12)
    assert p1_of == p1_of_now == mis1 and f1_of == f1_of_now == clean1
    assert p2_of == p2_of_now == mis2 and f2_of == f2_of_now == clean2
    assert (p1_before, f1_before, p1_now, f1_now) == (9, 10, 6, 3)
    assert (p2_before, f2_before, p2_now, f2_now) == (9, 13, 9, 3)
    assert "is one the check sees only in part" in said
    assert "What was not measured." in said and "The kit's default model was not used at all." in said
    assert "What round 3 opened." in said


def test_sections_2_and_7_give_the_rehearsal_with_its_numbers_and_its_limits():
    """Moved with its sentences to the record. Two sentences of old section 7 were corrected in
    round 4 (C4 and C5 in the record): the test now pins the corrected ones in the README, and
    the old ones where the record keeps them."""
    three, reference = record(R3), record(REFERENCE)
    for row in ("| clean (33) | 23 / 9 / 1 | 30 / 2 / 1 | 30 / 2 / 1 |", "| minor (14) | 12 / 2 / 0 | 11 / 3 / 0 | 11 / 3 / 0 |",
                "| misleading (13) | 9 / 3 / 1 | 6 / 6 / 1 | 6 / 6 / 1 |",
                "| clean (39) | 26 / 12 / 1 | 36 / 2 / 1 |", "| minor (9) | 8 / 1 / 0 | 9 / 0 / 0 |",
                "| misleading (12) | 9 / 2 / 1 | 9 / 2 / 1 |",
                "| Claude Haiku | 10 / 7 / 13 | 11 / 7 / 12 |", "| Claude Sonnet | 23 / 7 / 0 | 28 / 2 / 0 |"):
        assert row in three, row
    for needed in (
        "They are not the kit's default model (Amazon Nova Micro).",
        "chosen by the agent that prepared the rehearsal, not by the model",
        "6 of the 13 misleading answers of the first pass and 9 of the 12 of the second still reach the reader "
        "with no warning",
        "a search total or an off-topic document presented as the answer, is one the check sees only in part",
        "What round 3 gave up to remove false warnings.",
    ):
        assert needed in three, needed
    for needed in ("No rule here checks it", "After a search the block alone is usually that long."):
        assert needed in reference, needed
    assert reference.index("a returned document presented as the thing you asked for") < reference.index("What the kit does.")
    # section 7: the corrected sentences in the README, the old ones under "Statements corrected in round 4"
    seven, corrected = flat(section(7)), record(CORRECTED)
    assert "the check as it is now passes 15 of those 25 with no warning" in seven
    assert "No rule in the kit checks these." in seven
    assert "check as it is now passed 15 of those 25 with no warning." in corrected
    assert "were the commonest serious errors in both rehearsal passes and no rule in the kit checks them." in corrected
    assert "commonest serious errors" not in seven
    # sentences the rehearsal contradicted are gone, from the README and from the record
    said = flat(README) + " " + flat(RECORD)
    for gone in ("no real model's answers were ever put through the check",
                 "has only ever seen text written by people", "No model was ever called, so the prompt",
                 # the second pass has been run, and the new prompt has been read by a model
                 "has not been run", "and not run. The kit's default", "and the prompt as it is now by none",
                 "what the four prompt rules added in round 3 change in a model's writing has not been measured"):
        assert gone not in said, gone


def test_the_second_pass_is_recorded_with_its_bad_news_first_and_its_limits():
    """Second rehearsal pass, 2026-10-07: what a reader of sections 2, 7 and 8 had to be able to
    find, and can now find in the record, word for word, under "Round 3". The order pinned here
    is the order inside that part (worst results before the tables); the README's own order is
    pinned by test_section_2_gives_the_bad_news_... above. Four of the sentences were shown by
    round 4 to rest on the rehearsal's design or were overtaken by it. They stay in the record as
    history and under "Statements corrected in round 4"; the README no longer makes them
    (test_statements_the_round_4_findings_contradict_... below)."""
    three, corrected = record(R3), record(CORRECTED)
    worst = three.index("The three results that matter most, worst first:")
    tables = three.index("What the check made of the 60 answers of the first pass")
    assert worst < tables
    for needed in (
        # the model, the prompt, the check
        "gave a misleading answer to 13 of 30 questions",
        "the same model gave a misleading answer to 12 of 30",
        "The larger model gave none in 60 answers.",
        "Rewriting the prompt did not fix the smaller model.",
        "The check let 6 of those 13 and 9 of those 12 reach the reader with no warning.",
        "put a wrong warning on 10 of the 39 a reader called clean",
        "It had been tuned on one set of answers and misfired on the next.",
        # the limits of the rehearsal
        "120 answers in all",
        "They read each prompt as plain text, not through Bedrock.",
        "so the labels of the two passes are not strictly comparable",
        "no answers that this code has not seen have been put through it",
        "Neither stand-in is the kit's default model",
        # what was and was not invented
        "no document number, citation, URL, date or docket id was invented",
        'dropped the "C1-" prefix of a correction\'s number, and the check warned on it both times',
        # what it means for the owner
        "The block built by code is the supported part of every answer.",
        "the choice of model mattered more than the prompt or the check",
        "Expect wrong warnings on your own run, and count them (section 6).",
    ):
        assert needed in three, needed
    for withdrawn in ("Rewriting the prompt did not fix the smaller model.",
                      "no answers that this code has not seen have been put through it",
                      "the choice of model mattered more than the prompt or the check",
                      "warning on 10 of 39 clean answers the first time it met text it had not been corrected on"):
        assert withdrawn in corrected, withdrawn
    seven = flat(section(7))
    for needed in ("That an answer the check passed is right.",
                   "It says nothing about relevance, about \"the newest\", or about completeness.",
                   # was "wrong warning on 10 of 39 clean answers ...": the figure for unseen text is round 4's now
                   "On 88 stand-in answers the check had not seen it warned 8"):
        assert needed in seven, needed
    for needed in ("What the second pass was.", "What the second pass found.", "What the second correction changed.",
                   "What the second correction did to the 120 answers.",
                   "no wrong warning on the 33 clean answers it was tuned on, ten on the next 39",
                   "passes with a note"):
        assert needed in three, needed


def test_the_step_done_by_hand_is_in_section_6_and_in_the_results_template():
    six = flat(section(6))
    assert "Ten answers read by hand against the block. No script does this." in six
    for kind in ("that a document is about what you asked", '"the newest", "the latest" or "the most recent"',
                 "that nothing else exists"):
        assert kind in six, kind
    template = flat((ROOT / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8"))
    assert "## Ten answers read by hand against the block" in template
    for row in ("| Answers read (10 if you can), and the model that wrote them | |",
                "| Of those, answers that carried a WARNING line | |",
                "| Answers with a WARNING line that was wrong: the block supports what the warning questions | |"):
        assert row in template, row


def test_the_word_lists_the_readme_gives_are_the_ones_the_code_uses():
    from agent import fr_tools, graph

    two = record(REFERENCE)  # the lists stand in the record now; the README gives the short form
    assert "other than " + ", ".join(fr_tools.SEARCH_STOP_WORDS) + ";" in two
    # agent/fr_tools.py says of this list that "the README repeats it": it does, in the file table of section 1
    assert "(the words of the search term other than " + ", ".join(fr_tools.SEARCH_STOP_WORDS) + ")" in section(1)
    for word in ("match", "search", "results", "hits", "returned", "API", "mention", "contain"):
        assert graph._MATCH_WORDS.search(word.upper()), word
    assert "none of the words match, search, results, hits, returned, API, mention or contain" in two
    # the subset and sample wording of the rule on the number returned (second pass)
    listed = ('newest, most recent, latest, first, top, shown, returned, listed, "was given", these, those, among, '
              'other, remaining, rest, "left out", "of the 5", "of them", "here are", following')
    assert listed in two
    for word in listed.replace('"', "").split(", "):
        assert graph._SUBSET_WORDS.search(word.upper()), word
    for word in ("matched", "search", "published", "total"):
        assert not graph._SUBSET_WORDS.search(word.upper()), word
    assert graph._ONLY_WORDS.search("ONLY") and graph._ONLY_WORDS.search("EXACTLY")
    for part in ("`Search words`", "`NOTE:`", "`WARNING:`"):
        assert part in two, part


def test_the_label_the_readme_quotes_is_the_label_the_code_prints():
    from agent import graph

    assert graph.BLOCK_HEADER.startswith("FROM THE FEDERAL REGISTER API")
    assert graph.SUMMARY_LABEL.startswith("MODEL'S SUMMARY")
    for said in (flat(section(2)), record(REFERENCE)):
        assert "`FROM THE FEDERAL REGISTER API`" in said and "`MODEL'S SUMMARY`" in said
    # the two limits are stated in the record now (old section 2), and are still held to the code
    said = record(REFERENCE)
    assert f"longer than {graph.SCREEN_LINES} lines" in said
    assert f"Above {graph.BLOCK_MAX_DOCUMENTS} documents" in said


def test_what_section_2_says_is_and_is_not_compared_is_what_the_label_says():
    """New with the documentation pass. Section 2 gives the two lists of the label that the code
    prints above the model's text; each item is held to that label, so the README cannot claim a
    comparison the label does not."""
    from agent import graph

    said = flat(section(2))
    compared, not_checked = graph.SUMMARY_LABEL.split("NOT checked:")
    assert "Compared with the tool results:" in compared
    listed = said[said.index("Compared with the tool results:"):said.index("So these pass with no warning")]
    listed_compared, listed_not = listed.split("Not checked:")
    for item in ("document numbers", "Federal Register citations", "other numbers of two or more digits", "dates",
                 "URLs", "counts of documents", "phrases of two or more words in quotation marks"):
        assert item in listed_compared and item in compared, item
    for item in ("wording", "titles and descriptions unless quoted", "which agency did what",
                 "whether a document it lists is about what you asked", "single digits", "numbers written as words",
                 "anything else with no digits in it"):
        assert item in listed_not and item in not_checked, item
    assert "a two-digit ordinal" in listed_not and "ordinal" in not_checked
    assert 'two digits after letters ("FY27")' in listed_not and "FY27" in not_checked
    # nothing is listed as compared that the label lists as not checked
    assert "wording" not in listed_compared and "agency" not in listed_compared


def test_round_4_is_recorded_with_its_bad_news_and_its_limits():
    """Review round 4, 2026-10-07: what a reader of sections 2, 5, 7 and 8 had to be able to find.
    Section 5 is still in the README. The sentences of sections 2 and 8 are in the record under
    "Round 4" and in its reference part; the one of section 7 was corrected in round 4 (C7)."""
    from agent import graph

    four, reference, five = record(R4), record(REFERENCE), flat(section(5))
    for needed in (
        "passed 50 of the 212 with no warning", "warned 12 of the 68", "This code passes 25 (numbers in words",
        "19 counts in wordings the count rules do not read",
        "that pair is again for texts the rules were corrected on", "`REVIEW_NOTES_r4.md` has every finding of round 4",
    ):
        assert needed in four, needed
    for needed in (
        # limits that stay, said before what is compared
        'a two-digit ordinal ("the 83rd")', 'two digits that follow letters ("FY27", "COVID-19")',
        'a site named without a path ("regulations.gov")',
        'a heading such as "the following 10 final rules:" still passes',
        # what changed in what is compared
        "joined by a hyphen, a dot, a slash or a colon", 'Two numbers joined by one hyphen ("parts 70-71") are compared one by one',
        'written without "https://" and has a path', "only within three words of the count",
        'a phrase with "..." is compared piece by piece', "There are five.",
    ):
        assert needed in reference, needed
    assert reference.index('a two-digit ordinal ("the 83rd")') < reference.index("What is compared in the model's text")
    assert graph.MODEL_LINE_MARK.strip() in reference
    for needed in ("`TEARDOWN INCOMPLETE` and its exit code is 5, not 0", "a line starting `NOT STOPPED` says what it can cost",
                   "A runtime or gateway that the file records as live is also asked for by id",
                   "Every such line says it is not proof for any other Region, prefix or account"):
        assert needed in five, needed
    assert "on 12 of 68 honest texts a reader wrote for round 4" in record(CORRECTED)
    assert "Reviewed independently a third time on 2026-10-07 (round 4): 1 blocker, 7 majors and 13 minors" in four
    notes = (ROOT / "REVIEW_NOTES_r4.md").read_text(encoding="utf-8")
    assert notes.index("## What is still wrong, first") < notes.index("## Counts, before and after")
    for finding in ("B1", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9",
                    "m10", "m11", "m12", "m13", "MAJOR 3", "MINOR 1", "MINOR 2", "MINOR 5", "MINOR 15"):
        assert f"- {finding}," in notes, finding
    assert notes.count("FIXED") >= 20 and "STATED AS A LIMIT" in notes and "NOT CHANGED" in notes


def test_the_shared_audit_command_is_written_out_in_full():
    assert ("python ../common/whats_running.py --region <the AWS_REGION in your config.env> "
            "--prefix <your KIT_PREFIX>") in README


def test_the_round_2_review_line_is_present_and_adds_up():
    said = record(R2)
    match = re.search(r"Reviewed independently a second time on 2026-10-07 \(round 2\): (\d+) findings for "
                      r"this kit, (\d+) fixed, (\d+) left open \(listed below\)", said)
    assert match, "the dated round 2 review line is missing from the record"
    findings_, fixed, left_open = map(int, match.groups())
    assert findings_ == 27 and fixed + left_open == findings_
    if left_open:
        assert "Left open after round 2:" in said
    # the leak counts are stated as counts, before and after
    assert "91 of 189" in said and "5 of 189" in said


def test_the_review_line_is_present_and_adds_up():
    match = re.search(r"Reviewed independently on 2026-10-07 \(round 1\): (\d+) findings, "
                      r"(\d+) fixed, (\d+) left open \(listed below\)", record(R1))
    assert match, "the dated review line is missing from the record"
    findings_, fixed, left_open = map(int, match.groups())
    assert findings_ == 27 and fixed + left_open == findings_


def test_prices_units_and_delays_are_the_corrected_ones():
    """Every sentence here is still in the README except the words of --accept-early-read's result
    line, which went to the record with the passage on usage data. The wrong sentences stay out
    of both files."""
    said, whole_record = flat(README), flat(RECORD)
    for wrong in ("per-1k", "per 1,000 input", "Wait a few minutes", "lists no standing charge",
                  'one list price for "commercial AWS Regions"'):
        assert wrong not in whole_record, wrong
    assert "read early at the owner's request, NOT final" in record(REFERENCE)
    assert "--input-usd-per-1m" in said and "per-1k" not in said and "per 1,000 input" not in said
    assert "$0.035 per 1M input tokens" in said and "$0.14 per 1M output tokens" in said
    # round 2: a global. inference profile has its own price, from the AWS Price List file
    assert "$0.30 per 1M input tokens and $2.50 per 1M output tokens" in said
    assert "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json" in said
    assert "within 10%" in said and "at least 90%" in said
    assert "--accept-early-read" in said and '`CROSS-CHECKED` without the words "read early"' in said
    assert "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrock/USD/current/bedrock.json" in said
    assert "up to 60 minutes" in flat(section(4))
    assert "Wait a few minutes" not in said
    assert "RESULT: CROSS-CHECKED" in flat(section(4)) and "NOT CROSS-CHECKED" in said
    # review minors 1 and 2
    assert "lists no standing charge" not in said
    assert 'one list price for "commercial AWS Regions"' not in said
    assert "S3 Standard rates" in said and "system overhead" in said


def test_what_an_unstopped_session_costs_is_stated_for_the_kit_and_for_the_defaults():
    for said in (flat(section(2)), record(REFERENCE)):
        for figure in ("$0.064", "$0.098", "$2.04", "$3.12"):
            assert figure in said, figure
        assert "900 / 3600 x (2 x $0.0895 + 8 x $0.00945)" in said  # the arithmetic is shown, not only the result
    assert "8 x (2 x $0.0895 + 8 x $0.00945) = $2.04" in record(REFERENCE)


def test_the_state_rule_is_explained_to_the_owner():
    said = flat(README)
    assert "an exported AWS_REGION overrides config.env" in said
    assert "exit code 4" in said and "RESULT: INCOMPLETE" in said
    assert "RESULT: CLEAN" in flat(section(5))
    assert "exits 3" in flat(section(5)) or "exit code 3" in flat(section(5))


def test_section_5_says_what_teardown_will_not_do_before_what_it_does():
    said = flat(section(5))
    assert said.index("What teardown will not do, first.") < said.index("Otherwise it finds resources")
    for needed in (
        "python 90_teardown.py --region <Region> --prefix <prefix>",
        "It never moves, renames, deletes or rewrites a `.state.json` it could not read.",
        "`--dry-run` deletes nothing and exits 3, not 0.",
        "printed with its Region and left alone",
        "One IAM role name serves every Region.",
        "Teardown finished, BUT",
        "this is not proof for any other Region, prefix or account",
        ".state.json.damaged-*",
        "every version and delete marker",
    ):
        assert needed in said, needed


def test_the_verdict_tables_of_section_5_are_the_scripts_own():
    """New with the documentation pass: section 5 gives the last lines and exit codes as two tables.
    Each row is held to the script that prints the line and to the exit codes kitlib defines."""
    import kitlib

    five = section(5)
    teardown = (ROOT / "90_teardown.py").read_text(encoding="utf-8")
    for words, code in (("Teardown finished without errors", 0), ("Teardown finished, BUT", 1),
                        ("Teardown finished WITH ERRORS", 1), ("TEARDOWN INCOMPLETE", kitlib.EXIT_INCOMPLETE)):
        assert words in teardown, words
        assert re.search(rf"^\| [\"`]{re.escape(words)}[^|]*\| {code} \|", five, flags=re.M), (words, code)
    verify = (ROOT / "99_verify_clean.py").read_text(encoding="utf-8")
    for words, code in (("RESULT: CLEAN", 0), ("RESULT: NOT CLEAN", 1), ("RESULT: NOT VERIFIED", 1),
                        ("RESULT: INCOMPLETE", kitlib.EXIT_INCOMPLETE), ("RESULT: INCOMPLETE", kitlib.EXIT_STATE_MISMATCH)):
        assert words in verify, words
        assert f"| `{words}` | {code} |" in five, (words, code)
    assert (kitlib.EXIT_INCOMPLETE, kitlib.EXIT_STATE_MISMATCH, kitlib.EXIT_DRY_RUN_PROVES_NOTHING) == (5, 4, 3)
    assert "With `--dry-run` it exits 3, not 0, because a dry run proves nothing." in flat(five)
    assert "stops with exit code 4 and deletes nothing" in flat(five)


def test_before_you_start_names_the_cli_and_the_sign_in_commands():
    said = flat(section(3))
    for needed in ("AWS CLI", "aws configure sso", "aws sso login --profile", "aws sts get-caller-identity",
                   "AWS_PROFILE"):
        assert needed in said, needed


def test_section_8_counts_match_the_test_suite():
    """Changed in the documentation pass: section 8 gives the total and the number of test files and
    no longer the count of every file. The list by file, as it was after round 4, is in the record."""
    on_disk = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    four = record(R4)
    assert "970 passed, 0 failed" in four and "20 test files" in four and "`test_readme.py` 23" in four
    if sorted(conftest.COLLECTED) != on_disk:
        pytest.skip("only part of the suite was collected, so the totals cannot be compared")
    said = flat(section(8))
    total = sum(conftest.COLLECTED.values())
    assert f"{total} passed, 0 failed" in said, f"README section 8 should say {total} passed"
    assert f"{len(on_disk)} test files" in said
    assert f"{total} offline tests" in flat(section(1))


def test_every_unverified_marker_in_the_code_is_repeated_in_section_8():
    """Spine: a detail marked `# UNVERIFIED:` in code is repeated in README section 8."""
    said = flat(section(8)).lower()
    topics = {
        "20_package.py": ["bin/"],
        "30_deploy.py": ["s3 access", "traceloop_trace_content"],
        "agentcore_app.py": ["0.0.0.0", "traceloop_trace_content"],
        "40_enable_observability.py": ["runtime arn"],
        "60_read_usage.py": ["running total"],
        "kit_resources.py": ["workload identity", "error code", 'version id "null"',
                             "whether deleting a runtime ends its open sessions"],
        "agent/fr_tools.py": ["10,000"],
        "optional_gateway/10_create_gateway.py": ["no permissions policy"],
        "optional_gateway/50_call_gateway_tools.py": ["signing name"],
    }
    for name, wanted in topics.items():
        assert "UNVERIFIED:" in (ROOT / name).read_text(encoding="utf-8"), name
        for topic in wanted:
            assert topic in said, f"section 8 should repeat the UNVERIFIED item from {name} ({topic})"
    # and no file with a marker is missing from the list above
    code = list(ROOT.glob("*.py")) + list((ROOT / "agent").glob("*.py")) \
        + list((ROOT / "optional_gateway").glob("*.py"))
    marked = sorted(path.relative_to(ROOT).as_posix() for path in code
                    if "UNVERIFIED:" in path.read_text(encoding="utf-8"))
    assert marked == sorted(topics), marked
    # the 17 items, numbered, each with what the kit does or what to do; the record has each in full
    assert re.findall(r"(?m)^\| (\d+) \| ", section(8)) == [str(n) for n in range(1, 18)]
    full = record(REFERENCE)
    assert "17. That the Federal Register API caps a search total at 10,000." in full
    assert "Each is also marked `# UNVERIFIED:` where it appears in the code." in full


# ---------------------------------------------------------------------------------------------
# Documentation pass of 2026-10-07, after review round 4: the shortened README and the record.
# ---------------------------------------------------------------------------------------------

# The figures of the round 4 findings (../_review_reports/round4/FINDINGS_round4.md, sections 1 and 2).
# Who chose the tool calls, which system prompt -> clean, minor, misleading, answers
CONDITIONS = {
    ("the preparing agent", "as before round 3"): (10, 7, 13, 30),
    ("the preparing agent", "rewritten in round 3"): (11, 7, 12, 30),
    ("the model itself", "as before round 3"): (21, 8, 1, 30),
    ("the model itself", "rewritten in round 3"): (22, 7, 0, 29),   # 30 questions; 1 conversation ended at the step limit
}
# What the check did with the 88 answers it had not seen: label -> (answers, passed, warned, replaced)
UNSEEN = {"clean": (70, 59, 6, 5), "minor": (18, 16, 2, 0), "misleading": (0, 0, 0, 0)}


def test_the_readme_is_at_most_600_lines_and_sections_2_and_8_at_most_110():
    lines = lambda number: section(number).count("\n")   # heading line to the blank line that ends the section
    assert len(README.splitlines()) <= 600, len(README.splitlines())
    assert lines(2) <= 110, lines(2)
    assert lines(8) <= 110, lines(8)
    assert "`RECORD_OF_REVIEWS.md`" in section(2) and "`RECORD_OF_REVIEWS.md`" in section(8)
    assert "`REVIEW_NOTES_r4.md`" in section(8)
    # one pointer per round, and each lands on a heading of the record
    eight = flat(section(8))
    for title in ("Round 1", "Round 2", "Round 3", "Round 4"):
        assert f'"{title}"' in eight and re.search(rf"^## {title}$", RECORD, flags=re.M), title
    # the line near the top that sends a first-time reader to the one page
    assert "`START_HERE.md`" in "\n".join(README.splitlines()[:4])


def table_rows(text: str) -> dict:
    rows = {}
    for (who, prompt) in CONDITIONS:
        row = re.search(rf"^\| {re.escape(who)} \| {re.escape(prompt)} \| (\d+) \| (\d+) \| (\d+) \| (\d+)", text, flags=re.M)
        assert row, (who, prompt)
        rows[(who, prompt)] = tuple(map(int, row.groups()))
    return rows


def test_section_2_gives_the_four_conditions_of_round_4_as_the_findings_do():
    """The four-row table of the findings' section 1: who chose the tool calls, and which prompt."""
    assert table_rows(section(2)) == CONDITIONS
    assert table_rows(RECORD[RECORD.index(f"## {CORRECTED}"):RECORD.index("### C1.")]) == CONDITIONS
    for clean, minor, misleading, answers in CONDITIONS.values():
        assert clean + minor + misleading == answers
    assert "| 29 (1 conversation ended at the kit's step limit) |" in section(2)
    if FINDINGS.is_file():
        assert table_rows(FINDINGS.read_text(encoding="utf-8")) == CONDITIONS
    two = flat(section(2))
    # what the table is said to show, the correction, and the limits
    for needed in (
        "Claude Haiku, on the same 30 questions",
        "An earlier version of this README gave the first two rows as the smaller model's own error rate, and said "
        "that rewriting the system prompt did not fix it and that the choice of model mattered more than the prompt "
        "or the check. That was wrong.",
        "whose tool calls were chosen in advance by the agent that prepared it",
        "the model was handed the results of searches it had not written, often a single search whose matches were "
        "mostly off topic",
        "In the kit the model writes its own searches and can search again.",
        "through the kit's real tools against the live Federal Register API, it misled in 0 or 1 of 30 answers, not "
        "12 or 13",
        "The rewritten prompt made little difference in either condition (13 against 12; 1 against 0).",
        "The last two rows had one reader per answer.",
        "a fresh reader gave 27 of 30 rehearsal answers the label they had before, and called 5 misleading where 5 "
        "had been",
        "The writers were stand-in models (Claude Haiku and Claude Sonnet), not the kit's default.",
        "Each ran inside its own agent harness, read the prompt as a text file, called the tools from a shell, took "
        "ten questions in one context, and knew it was a test.",
        "How often your model misleads is not known until you count it (section 6).",
    ):
        assert needed in two, needed
    said = findings()
    if said:
        for needed in ("27 of 30 the same label as before, and 5 misleading both times",
                       "The rewritten prompt made little difference in either condition (13 against 12; 1 against 0).",
                       'One reader per answer in the two "model itself" rows on the earlier questions; two readers on '
                       "the new questions.",
                       "read the prompt as a text file and called the tools from a shell, took ten questions in one "
                       "context, and knew it was a test"):
            assert needed in said, needed


def test_section_2_gives_the_new_questions_and_the_unseen_answers_as_the_findings_do():
    """0 misleading of 59; the table of the findings' section 2; the 8 warnings by kind."""
    two = flat(section(2))
    new = re.search(r"On 30 new questions, with the model's own tool calls and the rewritten prompt, two readers each: "
                    r"Claude Haiku (\d+) or (\d+) clean, (\d+) or (\d+) minor, (\d+) misleading of (\d+); Claude Sonnet "
                    r"(\d+) clean, (\d+) minor, (\d+) misleading of (\d+) \(1 conversation ended at the step limit\)\. "
                    r"The readers agreed on (\d+) of (\d+) answers\.", two)
    assert new, "the sentence on the 30 new questions is missing from section 2"
    h_clean_a, h_clean_b, h_minor_a, h_minor_b, h_mis, h_of, s_clean, s_minor, s_mis, s_of, agreed, of_agreed = map(
        int, new.groups())
    assert h_clean_a + h_minor_a + h_mis == h_clean_b + h_minor_b + h_mis == h_of == 30
    assert s_clean + s_minor + s_mis == s_of == 29 and (h_mis, s_mis) == (0, 0)
    assert (agreed, of_agreed) == (58, h_of + s_of) == (58, 59)
    seen = re.search(r"\*\*The check on (\d+) answers it had not seen\*\* \(the (\d+) and the (\d+) above\)\. Bad news "
                     r"first: none of the 88 was misleading, so this set says nothing about what the check catches\.", two)
    assert seen and tuple(map(int, seen.groups())) == (88, 59, CONDITIONS[("the model itself", "rewritten in round 3")][3])
    for label, (answers, passed, warned, replaced) in UNSEEN.items():
        assert f"| {label} ({answers}) | {passed} | {warned} | {replaced} |" in section(2), label
        assert answers == passed + warned + replaced
    assert sum(row[0] for row in UNSEEN.values()) == 88
    kinds = re.search(r"Of the (\d+) warnings, (\d+) say a tool call failed, and one did; (\d+) flags a date and a time "
                      r"taken from the visible part of a field the tool had cut short; (\d+) flag", two)
    assert kinds
    warnings, failed, cut, worked_out = map(int, kinds.groups())
    assert warnings == UNSEEN["clean"][2] + UNSEEN["minor"][2] == failed + cut + worked_out == 8
    assert (failed, cut, worked_out) == (4, 1, 3)
    assert "it reads as an accusation: 3 of 88, about 1 time in 30" in two
    assert "The 5 replaced answers each followed a search that returned nothing, after which the kit always shows fixed text." in two
    said = findings()
    if said:
        for row in ("| clean (70) | 59 | 6 | 5 |", "| minor (18) | 16 | 2 | 0 |", "| misleading (0) | 0 | 0 | 0 |"):
            assert row in said, row
        for needed in ("Claude Haiku 23 or 24 clean, 7 or 6 minor, 0 misleading of 30",
                       "Claude Sonnet 25 clean, 4 minor, 0 misleading of 29", "agreed on 58 of 59 answers",
                       "No answer in the 88 was misleading, so this set says nothing about what the check catches.",
                       "4 say a tool call failed, and one did", "about 1 time in 30",
                       "The 5 replaced answers all followed a search that returned nothing, after which the kit always "
                       "shows fixed text.",
                       "2 of 90 conversations under the current prompt ended at the kit's step limit"):
            assert needed in said, needed


def test_the_words_section_2_quotes_from_the_number_warning_and_the_step_limit_are_the_codes():
    """New with the documentation pass: two quotations and one number of section 2, held to the code."""
    import inspect

    from agent import graph

    two = flat(section(2))
    source = re.sub(r'"\s*\n\s*f?"', "", inspect.getsource(graph))   # adjacent string literals read as one
    for quoted in ("number(s) that appear in no complete field of a tool result",
                   "may be invented, worked out by the model, or taken from a field the tool cut short"):
        assert f'"{quoted}"' in two, quoted
        assert quoted in source, quoted
    limit = re.search(r"2 of 90 stand-in conversations under the current prompt ended at the kit's limit of (\d+) graph "
                      r"steps with \"No answer was produced\.\"", two)
    assert limit and int(limit.group(1)) == graph.DEFAULT_RECURSION_LIMIT == 12
    assert "No answer was produced." in source


def test_the_prices_and_the_ceilings_of_section_2_are_the_ones_in_the_code():
    """New with the documentation pass: section 2 now carries the short form of the price lists, so
    each figure in it is held to kitlib, as test_kitlib.py holds the code to the arithmetic."""
    import kitlib

    two = flat(section(2))
    v1, v2 = kitlib.RUNTIME_RATES["V1"], kitlib.RUNTIME_RATES["V2"]
    assert f"Platform version V1, the default: ${v1[0]} per vCPU-hour and ${v1[1]} per GB-hour." in two
    assert f"V2, if enabled for your account and Region: ${v2[0]} and ${v2[1]}." in two
    cfg = kitlib.Config()
    assert f"The kit sets {cfg.idle_timeout_s} seconds idle and {cfg.max_lifetime_s} of life" in two
    kit = lambda version: kitlib.session_cost_bounds(cfg.idle_timeout_s, cfg.max_lifetime_s, version)["ceiling"]
    assert kitlib.SERVICE_DEFAULT_LIFETIME_S == 28800 == 8 * 3600
    default = lambda version: kitlib.session_cost_bounds(kitlib.SERVICE_DEFAULT_IDLE_S, kitlib.SERVICE_DEFAULT_LIFETIME_S,
                                                         version)["ceiling"]
    assert f"= ${kit('V1'):.3f} on V1 (${kit('V2'):.3f} on V2)" in two
    assert f"At the service defaults of {kitlib.SERVICE_DEFAULT_IDLE_S} and 28,800 seconds the same sum over 8 hours is " \
           f"${default('V1'):.2f} (${default('V2'):.2f})" in two
    micro = kitlib.model_token_price("us.amazon.nova-micro-v1:0", "us-east-1")
    lite = kitlib.model_token_price("us.amazon.nova-2-lite-v1:0", "us-west-2")
    lite_global = kitlib.model_token_price("global.amazon.nova-2-lite-v1:0", "us-east-2")
    assert f"Nova Micro ${micro[0]} per 1M input tokens and ${micro[1]} per 1M output tokens" in two
    assert f"Nova 2 Lite ${lite[0]} and ${lite[1]}" in two
    assert f"`global.` profile: ${lite_global[0]:.2f} per 1M input tokens and ${lite_global[1]:.2f} per 1M output tokens" in two
    assert kitlib.model_token_price("global.amazon.nova-micro-v1:0", "us-east-1") is None and "none held for Nova Micro" in two
    assert "In " + ", ".join(kitlib.MODEL_PRICE_REGIONS[:2]) + " and " + kitlib.MODEL_PRICE_REGIONS[2] + ":" in two
    # each price with its source, its date and its Region, as the spine asks
    assert "Prices read 2026-10-07 (sources 2, 25, 40)" in two and "one Runtime price with no Region column" in two
    for number in ("2", "12", "25", "40"):
        assert re.search(rf"^\| {number} \| ", section(9), flags=re.M), number


def test_the_counts_section_2_takes_from_the_kits_own_notes_and_record_are_the_ones_there():
    two = flat(section(2))
    # wrong "clean" results: the round 4 findings, section 3, first row (all folders, on the merged tree)
    wrong_clean = re.search(r'the three kits and the shared audit said "clean" wrongly in (\d+) of (\d+) sequences; with '
                            r"the state file intact, in (\d+) of (\d+)\.", two)
    assert wrong_clean and tuple(map(int, wrong_clean.groups())) == (34, 377, 1, 244)
    said = findings()
    if said:
        assert "wrong \"clean\" 34 of 377 (state file intact: 1 of 244, the audit's documented blind spot for open " \
               "AgentCore sessions)" in said
    # "it passes 15 of those 25": the two rehearsal passes, as the record's tables have them on the final code
    three = record(R3)
    # first pass: three columns, the last is "This code"; second pass: two columns, the last is "This code"
    first = re.search(r"\| misleading \((13)\) \| \d+ / \d+ / \d+ \| \d+ / \d+ / \d+ \| (\d+) / (\d+) / (\d+) \|", three)
    second = re.search(r"\| misleading \((12)\) \| \d+ / \d+ / \d+ \| (\d+) / (\d+) / (\d+) \|", three)
    assert first and second
    for row in (first, second):
        assert int(row.group(1)) == sum(int(row.group(n)) for n in (2, 3, 4))
    misleading = int(first.group(1)) + int(second.group(1))
    passed = int(first.group(2)) + int(second.group(2))
    assert (misleading, passed) == (25, 15)
    assert misleading == sum(CONDITIONS[("the preparing agent", prompt)][2] for prompt in ("as before round 3", "rewritten in round 3"))
    # the round 4 fixer ran the same 120 answers through the round 4 code: unchanged in every cell.
    # The documentation pass ran them again on this code (same rig, a scratch copy): 6 of 13 and 9 of 12 pass.
    assert "| misleading (13, 12) | 6 / 6 / 1 | 6 / 6 / 1 | 9 / 2 / 1 | 9 / 2 / 1 |" in (ROOT / "REVIEW_NOTES_r4.md").read_text(
        encoding="utf-8")
    assert f"The only misleading real answers the check has met are the rehearsal's {misleading}, and it passes {passed} " \
           f"of those {misleading} with no warning." in two


def test_every_pointer_from_the_code_into_section_2_still_lands():
    """00_check.py, kitlib.py and config.example.env send the owner to "README section 2" for five
    things. None of those files was changed in the documentation pass, so section 2 must still
    hold each of them."""
    two = flat(section(2))
    assert "(README section 2, " in (ROOT / "00_check.py").read_text(encoding="utf-8")
    assert "**Things that can go wrong**" in two and "Anthropic models need a one-time use-case form" in two
    config = (ROOT / "config.example.env").read_text(encoding="utf-8")
    assert config.count("README section 2") == 4
    assert "(sources 2, 25, 40)" in two                         # "README section 2 has the sources" (token prices)
    assert "V2, if enabled for your account and Region" in two  # "different rates, see README section 2"
    assert "900 / 3600 x (2 x $0.0895 + 8 x $0.00945)" in two   # "README section 2 shows the arithmetic"
    assert "`EXECUTION_ROLE_S3_READ=true` (item 11)" in two       # "needs S3 read access ... (README section 2)"
    eight = flat(section(8))
    assert "| 11 | Whether the execution role needs S3 access to the deployment package. Two AWS pages disagree" in eight
    assert "`ENABLE_OTEL=false` (item 1)" in two and "| 1 | That the hosted runtime starts `opentelemetry-instrument`" in eight
    assert "`MODEL_ID` (item 12)" in two and "| 12 | Whether Amazon Nova accepts the search tool's optional arguments" in eight
    # section 1 and section 3 no longer send the reader to a line that left section 2
    assert "Section 8, item 1, has what can go wrong with it" in flat(section(1))
    assert "see the Free Tier line above" not in README and '"Paid plan exclusive" (source 3' in flat(section(3))
    # and every source number the README cites is in its own section 9
    cited = set(re.findall(r"sources? (\d+)", README)) | {n for group in re.findall(r"sources ([\d, ]+)", README)
                                                           for n in re.findall(r"\d+", group)}
    listed = set(re.findall(r"(?m)^\| (\d+) \| ", section(9)))
    assert cited and cited <= listed, cited - listed


def test_statements_the_round_4_findings_contradict_are_gone_from_the_readme_and_corrected_in_the_record():
    """Replaces what three assertions guarded until the documentation pass. They required README
    sections 2 and 7 to say "Rewriting the prompt did not fix the smaller model.", "the choice of
    model mattered more than the prompt or the check" and (in section 7) that the model you ran
    "matters more than either". Round 4 showed those to rest on the rehearsal's design: with its
    own tool calls the same model misled in 1 of 30 answers and 0 of 29. This test guards the
    corrected statements instead."""
    readme = flat(README)
    withdrawn = (
        "Rewriting the prompt did not fix the smaller model.",
        "The rewritten prompt did not fix the smaller",
        "the choice of model mattered more than the prompt or the check",
        "Which model you ran matters more than either",
        "no answers that this code has not seen have been put through it",
        "No model chose its own tool calls.",
        "makes a weak model safe to use",
        "commonest serious errors in both rehearsal passes",
        "The answer check has seen 120 real answers from those two models and otherwise only text",
    )
    for sentence in withdrawn:
        # the README may name a withdrawn claim only to say that it was wrong
        assert readme.count(sentence) == readme.count(sentence + ". That was wrong."), sentence
    assert readme.count("the choice of model mattered more than the prompt or the check. That was wrong.") == 1
    # word for word in the record, under the heading that stands first, each with what replaced it
    corrected = record(CORRECTED)
    for sentence in withdrawn:
        assert sentence in corrected, sentence
    assert RECORD_PARTS[0] == CORRECTED
    entries = re.findall(r"^### (C\d+)\. ", RECORD, flags=re.M)
    assert entries == [f"C{n}" for n in range(1, 13)]
    part = RECORD[RECORD.index(f"## {CORRECTED}"):RECORD.index("## The four rounds in one paragraph")]
    assert len(re.findall(r"^As it stood \(README lines \d+ to \d+\):$", part, flags=re.M)) == len(entries)
    assert len(re.findall(r"^Replaced by: .+$", part, flags=re.M)) == len(entries)
    assert 'Read "Statements corrected in round 4" first' in flat(RECORD[:RECORD.index(f"## {CORRECTED}")])
    # and where the record repeats them in their old place, a note above the passage says so
    notes = re.findall(r"^> Corrected in round 4: ", RECORD, flags=re.M)
    assert len(notes) == 6
    in_notes = " ".join(line[2:] for line in RECORD.split("\n") if line.startswith("> "))
    for ident in ("C1 above", "C2 above", "C3 above", "C4 to C7 above", "C8 above", "holds C9", "C10 above",
                  "C11 above", "(C12 above)"):
        assert ident in in_notes, ident
    # the corrected statements, in section 7, under "You cannot say"
    seven = flat(section(7))
    cannot = seven[seven.index("You cannot say, on the strength of this kit:"):]
    for stated in (
        "That the prompt or the check makes a model safe to use. The kit's default model has never been called.",
        "That the choice of model matters more than the prompt or the check, or that rewriting the prompt failed to "
        "fix a smaller model. An earlier version of this README said both, from a rehearsal in which the tool calls "
        "were chosen for the model in advance.",
        "with tool calls chosen in advance a stand-in model (Claude Haiku) misled in 12 or 13 of 30 answers, with its "
        "own in 0 or 1 of 30 on the same questions, and the rewritten prompt made little difference in either condition",
        "a stand-in in its own harness, one reader per answer where it chose its own tool calls, not the model you ran",
        "Of 88 written with the models' own tool calls, readers called none misleading, so those say nothing about "
        "what the check catches.",
        "On 88 stand-in answers the check had not seen it warned 8: 4 for a tool call that did fail, 1 for a date and "
        "a time taken from the visible part of a cut field, and 3 for a number the model had worked out correctly.",
    ):
        assert stated in cannot, stated
    assert "matters more than" not in seven[:seven.index("You cannot say, on the strength of this kit:")]
    # C11 and C12, found when START_HERE.md was written from the README's own steps: no step has the owner type
    # a curl command, and the verdict of a teardown is not its last line
    can = seven[:seven.index("You cannot say, on the strength of this kit:")]
    assert "curl" not in can and "the self-test of step 3 makes both calls for you" in can
    assert "You called the local server with curl and saw the contract it serves" in corrected
    assert "python 12_serve_local.py --fake-model --self-test" in section(4)   # the step the sentence rests on
    five = flat(section(5))
    assert "It ends with a verdict line and then `Now prove it: python 99_verify_clean.py`." in five
    assert "Its last line is `TEARDOWN INCOMPLETE`" not in five and "Its last line is `TEARDOWN INCOMPLETE`" in corrected
    teardown = (ROOT / "90_teardown.py").read_text(encoding="utf-8")
    assert teardown.rindex('out("Now prove it: python 99_verify_clean.py")') > teardown.rindex("TEARDOWN INCOMPLETE")


# Section 7, sentence by sentence. Every sentence of it that carries a number, or that speaks of a
# model, a prompt, the check, a warning or a stand-in, must be listed here with what it rests on:
#   ("findings", words)  those words stand in ../_review_reports/round4/FINDINGS_round4.md
#   ("file", name, words) those words stand in that file of the kit (code, or a test that pins it)
#   ("is", fact)          a fact computed from the kit's code, which must be True
# A sentence that is edited, or a new one, fails the test until it is listed with its evidence.
def _session_id_minimum() -> int:
    import botocore.session
    model = botocore.session.get_session().get_service_model("bedrock-agentcore")
    return model.operation_model("InvokeAgentRuntime").input_shape.members["runtimeSessionId"].metadata["min"]


def _usage_rules() -> bool:
    import kitlib
    usage = (ROOT / "60_read_usage.py").read_text(encoding="utf-8")
    return kitlib.USAGE_DELAY_MINUTES == 60 and "TOLERANCE = 0.10 " in usage and "read early at the owner's request" in usage


def _label_lists_what_is_compared() -> bool:
    from agent import graph
    return all(item in graph.SUMMARY_LABEL for item in (
        "document numbers", "Federal Register citations", "other numbers of two or more digits", "dates", "URLs",
        "counts of documents", "phrases of two or more words in quotation marks"))


SECTION_7_EVIDENCE = {
    "ran against a model on Amazon Bedrock through the Converse API": [
        ("file", "agent/model.py", "from langchain_aws import ChatBedrockConverse"),
        ("file", "30_deploy.py", "create_agent_runtime")],
    "(`POST /invocations` and `GET /ping` on port 8080; the self-test of step 3 makes both calls for you)": [
        ("file", "12_serve_local.py", 'status, ping = _http("GET", f"http://{HOST}:{port}/ping")'),
        ("file", "12_serve_local.py", 'status2, body = _http("POST", f"http://{HOST}:{port}/invocations", {"prompt": prompt})'),
        ("file", "tests/test_entrypoint.py", "def test_ping_reports_healthy("),
        ("file", "tests/test_entrypoint.py", "def test_invocations_with_fake_model("),
        ("file", "12_serve_local.py", "8080"),
        ("is", lambda: _session_id_minimum() == 33),
        ("file", "50_invoke_hosted.py", "assert len(session_id) >= 33")],
    "That figure includes the network, the model and the Federal Register.": [
        ("file", "50_invoke_hosted.py", "invoke_agent_runtime")],
    "agreed with the CloudWatch metrics within 10%, read at least 60 minutes after the last session": [
        ("is", _usage_rules),
        ("file", "tests/test_r2_usage.py", "(5 of 60 minutes had passed)"),
        ("file", "tests/test_r2_usage.py", "(tolerance 10%)")],
    "ran a check that found nothing under your prefix in the Regions and the account its result line names": [
        ("file", "99_verify_clean.py", "RESULT: CLEAN: nothing with the kit's prefix or tags was found.")],
    "the model's text was compared with the tool results for document numbers": [
        ("is", _label_lists_what_is_compared)],
    "Before your run the check had met real answers from two stand-in models only": [
        ("findings", "Stand-in models (Claude Haiku, Claude Sonnet), not the kit's default (Amazon Nova Micro)."),
        ("findings", "The kits' default models have never been called.")],
    "Of 120 written from tool calls an agent had chosen for them, readers called 25 misleading": [
        ("findings", "| the preparing agent | as before round 3 | 10 | 7 | 13 | 30 |"),
        ("findings", "| the preparing agent | rewritten in round 3 | 11 | 7 | 12 | 30 |"),
        ("file", "REVIEW_NOTES_r4.md", "| misleading (13, 12) | 6 / 6 / 1 | 6 / 6 / 1 | 9 / 2 / 1 | 9 / 2 / 1 |")],
    "Of 88 written with the models' own tool calls, readers called none misleading": [
        ("findings", "No answer in the 88 was misleading, so this set says nothing about what the check catches.")],
    "That an answer the check passed is right.": [
        ("file", "tests/test_r2_answer_check.py",
         "def test_F1_stated_limit_a_claim_with_no_digits_in_it_still_passes_without_a_warning(")],
    "A pass means that the numbers and identifiers in the model's text were found in the tool results.": [
        ("file", "tests/test_grounding.py",
         "def test_R6_known_limit_a_real_number_with_an_invented_title_and_agency_is_not_caught(")],
    "of the 10 answers you read, how many made such a claim that the block does not support": [
        ("file", "RESULTS_TEMPLATE.md", "| Answers read (10 if you can), and the model that wrote them | |")],
    "That the prompt or the check makes a model safe to use.": [
        ("findings", "the kit's default (Amazon Nova Micro)")],
    "The kit's default model has never been called.": [
        ("findings", "The kits' default models have never been called.")],
    "That the choice of model matters more than the prompt or the check, or that rewriting the prompt failed": [
        ("findings", "An earlier headline was wrong, and why")],
    "An earlier version of this README said both, from a rehearsal in which the tool calls were chosen": [
        ("findings", "That result came from a rehearsal in which the tool calls were chosen in advance by the agent "
                     "that prepared it.")],
    "misled in 12 or 13 of 30 answers, with its own in 0 or 1 of 30 on the same questions": [
        ("findings", "With pre-chosen tool calls the smaller model misled in 12 or 13 of 30 answers; with its own tool "
                     "calls in 0 or 1 of 30, on the same questions."),
        ("findings", "The rewritten prompt made little difference in either condition (13 against 12; 1 against 0).")],
    "a stand-in in its own harness, one reader per answer where it chose its own tool calls": [
        ("findings", 'One reader per answer in the two "model itself" rows on the earlier questions'),
        ("findings", "Each stand-in ran inside its own agent harness")],
    "That the warnings are reliable on your model's text.": [
        ("findings", "its \"number not found\" warning fires on correct arithmetic about 1 time in 30")],
    "On 88 stand-in answers the check had not seen it warned 8: 4 for a tool call that did fail": [
        ("findings", "| clean (70) | 59 | 6 | 5 |"), ("findings", "| minor (18) | 16 | 2 | 0 |"),
        ("findings", "4 say a tool call failed, and one did"),
        ("findings", "1 flags a date and a time the model took from the visible part of a field the tool had cut short"),
        ("findings", '3 flag a number "that appears in no complete field of a tool result" which the model had worked '
                     "out correctly from the results")],
    "That your account is clean beyond what the check's result line names.": [
        ("file", "99_verify_clean.py", "RESULT: CLEAN")],
    "That your latency or cost figures hold for other agents, models, Regions or dates.": [
        ("file", "RESULTS_TEMPLATE.md", "Region")],
}


def test_every_sentence_of_section_7_with_a_number_or_a_claim_about_models_has_its_evidence():
    body = flat(section(7).split("\n", 1)[1])
    sentences = [sentence for bullet in re.split(r" - (?=[A-Z`])", body)
                 for sentence in re.split(r'(?<=[.:;]) (?=[A-Z"`])', bullet)]
    flagged = [s for s in sentences
               if re.search(r"\d", s) or re.search(r"\b(models?|prompts?|check|warnings?|stand-ins?)\b", s)]
    assert len(flagged) >= 20
    said = findings()
    used = set()
    for sentence in flagged:
        keys = [key for key in SECTION_7_EVIDENCE if key in sentence]
        assert len(keys) == 1, f"section 7 sentence without exactly one entry of evidence: {sentence!r} {keys}"
        used.add(keys[0])
        for evidence in SECTION_7_EVIDENCE[keys[0]]:
            if evidence[0] == "findings":
                assert said is None or evidence[1] in said, (sentence, evidence[1])
            elif evidence[0] == "file":
                assert evidence[2] in (ROOT / evidence[1]).read_text(encoding="utf-8"), (sentence, evidence[1:])
            else:
                assert evidence[1]() is True, sentence
    assert used == set(SECTION_7_EVIDENCE), set(SECTION_7_EVIDENCE) - used


# sha256 over the old text in the record: every non-blank line after the corrected statements that
# the record did not add (headings, code fences, notes that start "> ", "README line(s) N (to M):").
# Printed by prove_nothing_lost.py when the README was shortened.
OLD_TEXT_IN_THE_RECORD = "141512273c113aacf304bc38c0963bafe7898e1f8a3d864e7cafb9e7ec8ef128"


def test_the_old_text_in_the_record_is_as_it_was_moved():
    """The moved text must not be edited afterwards. Take out what the record added and what is
    left after the corrected statements is, line for line, what left the README."""
    lines = RECORD.split("\n")
    start = lines.index(f"## {CORRECTED}")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    body = [line for line in lines[end:]
            if line.strip() and not line.startswith(("## ", "### ", "```", "> "))
            and not re.fullmatch(r"README lines? \d+(?: to \d+)?:", line)]
    assert hashlib.sha256("\n".join(body).encode("utf-8")).hexdigest() == OLD_TEXT_IN_THE_RECORD, \
        "the old text in RECORD_OF_REVIEWS.md was edited"
    head = flat(RECORD[:RECORD.index(f"## {CORRECTED}")])
    assert "Nothing here was reworded." in head and "the lines that start `> `" in head
