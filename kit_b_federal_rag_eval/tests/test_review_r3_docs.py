"""Round 3 (rehearsal on real model text): the README says what was found, what was fixed and what was not tried.

Every number the record states that this file can compute again, it computes again.
"""
from __future__ import annotations

import json
import re

import judge_replies_r3 as data
import test_review_r3_judge as judge_tests
import test_review_r3_lines as line_tests
from conftest import KIT_DIR
from kitlib import scoring

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
U = scoring.UNPARSEABLE


def section(number: int) -> str:
    parts = re.split(r"^## (\d+)\. .*$", README, flags=re.MULTILINE)
    return parts[parts.index(str(number)) + 1]


def item(number: int) -> str:
    return section(2).split(f"\n{number}. **")[1].split(f"\n{number + 1}. **")[0]


def test_section_8_opens_with_the_dated_rehearsal_line():
    text = section(8).lstrip()
    # Round 4: the newest review stands first, as each one did before it; the rehearsal block follows it whole.
    assert text.startswith("**Reviewed independently a fourth time on 2026-10-07 (round 4): ")
    text = text[text.index("**Rehearsed on real model text"):]
    assert text.startswith("**Rehearsed on real model text on 2026-10-07 (stand-in models Claude Haiku and Claude Sonnet, "
                           "not the kit's default models; local lexical retrieval; no AWS): 2 defects found, 2 fixed.**")
    assert text.index("Rehearsed on real model text") < text.index("Reviewed independently a second time")
    assert "None of this is an AWS result." in text


def test_what_the_rehearsal_did_not_exercise_is_said_first_and_in_full():
    text = section(8)
    head = text.split("The two defects, and the counts before and after:")[0]
    for words in ("What the rehearsal did NOT exercise, bad news first", "**No wrong answer.**", "**No missed retrieval.**",
                  "**No guardrail.**", "**No Nova phrasing.**", "Still read flatteringly"):
        assert words in head, words
    assert head.index("No wrong answer") < head.index("No missed retrieval") < head.index("No guardrail") < head.index("No Nova phrasing")


def test_the_before_and_after_counts_are_in_the_record():
    text = section(8)
    table = text.split("The two defects, and the counts before and after:")[1].split("Unchanged by the fix")[0]
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| Defect")]
    assert len(rows) == 2 and data.REAL_REPLY in rows[0]
    assert "110 of 120. Correct as judged 90/100 (agency 40/40, stage 30/30, high-impact 20/30). Unparseable 10" in rows[0]
    assert "120 of 120. Correct as judged 100/100 (agency 40/40, stage 30/30, high-impact 30/30). Unparseable 0" in rows[0]
    assert "str.splitlines()" in rows[1] and "U+2028, U+2029, U+0085" in rows[1] and "kitlib/jsonl.py" in rows[1]
    assert "correct by exact match 100/100" in text and "judged DECLINED 20/20" in text


def test_the_acceptance_numbers_are_the_ones_the_sets_give():
    text = section(8)
    flattering, lost = judge_tests.score_own_set()
    flattering_alone, lost_alone = judge_tests.score_own_set(with_question=False)
    total = len(data.REPLIES)
    contradicting = sum(1 for _, _, label in data.REPLIES if label == "U")
    assert f"{total} further replies written by the fixer" in text
    assert f"{contradicting} of them are replies whose own reason speaks against the verdict" in text
    assert "No label was changed afterwards: 0 of 117" in text
    assert f"Flattering 13 and lost 35 of {total} before; flattering {len(flattering)} and lost {len(lost)} of {total} after" in text
    assert f"The {len(lost)} still lost:" in text
    # Round 4: two of the five that need the reference state both values and are refused without the question too.
    assert len(flattering_alone) == 3
    assert (f"flattering {len(flattering_alone)} and lost {len(lost_alone)} (flattering 5 before round 4: the five that "
            "need the reference") in text
    assert "The 120 real replies: flattering 0 and lost 10 before; flattering 0 and lost 0 after." in text
    assert "flattering 0 of 88 and lost 9 of 88, before and after" in text
    assert "The fixer's 89 of round 2: flattering 0 and lost 5, before and after." in text
    attacked = len(judge_tests.FOUND_WHILE_ATTACKING)
    assert f"{attacked} more replies were written while attacking the new reader" in text and "9 of them were read flatteringly by a draft" in text
    characters, places = len(line_tests.ODD), 3
    assert f"each of {characters} characters" in text and f"({characters * places} runs)" in text and "(3 runs)" in text


def test_the_cross_check_numbers_are_the_ones_the_templates_give():
    text = section(8)
    sets = judge_tests.LABEL_SETS
    read = sum(len(judge_tests.REAL_TEMPLATES) * (3 if kind == "agency" else 1) * len(sets[kind]) for kind in sets)
    against = sum(len(sets[kind]) * (len(sets[kind]) - 1) for kind in sets) * len(judge_tests.AGAINST_TEMPLATES)
    values = sum(len(sets[kind]) for kind in sets)
    declined = 2 * values * len(judge_tests.DECLINED_AGAINST_TEMPLATES)
    assert f"{read} of {read} read as CORRECT" in text and f"0 of {against:,} read as CORRECT" in text
    assert f"every one of the {values} values: 0 of {declined - 5} read as DECLINED" in text
    assert "Thirteen wordings" in text and len(judge_tests.AGAINST_TEMPLATES) == 13
    assert "Five wordings that name a value" in text and len(judge_tests.DECLINED_AGAINST_TEMPLATES) == 5
    assert "The five wordings the real judges used" in text and len(judge_tests.REAL_TEMPLATES) == 5


def test_the_limits_the_record_admits_are_the_ones_the_tests_hold():
    text = section(8)
    for _, _, reason in judge_tests.STILL_READ_FLATTERINGLY:
        if reason.startswith("The candidate names") or reason.startswith("No information"):
            assert reason in text and reason in item(9), reason
    assert "`STILL_READ_FLATTERINGLY`" in text


def test_item_9_describes_the_round_3_reader_as_it_is():
    text = item(9)
    nh, hi = data.CONTEXTS["NH"], data.CONTEXTS["HI"]
    sets = judge_tests.LABEL_SETS
    assert '"Not High-impact" holds "not"' in text and '"Presumed High-Impact, but Not High-impact" holds "but"' in text
    assert scoring.parse_judge(data.REAL_REPLY, nh[0], nh[1], sets) == "CORRECT"
    assert scoring.parse_judge(data.REAL_REPLY) == U and "without the question takes nothing out" in text
    assert scoring.parse_judge(data.REAL_REPLY, hi[0], hi[1], sets) == U and "A value that is not the reference is never taken out" in text
    # the two refusals the item names
    assert "Candidate states Deployed; the reference is Pilot." in text
    assert judge_tests.verdict("ST", "Candidate states Deployed; the reference is Pilot.") == U
    assert "declines, then states Pilot" in text
    assert judge_tests.verdict("UH", "The candidate declines, then states Pilot.", "DECLINED") == U
    # the negations it says are let through, and that any other still refuses
    for phrase in ("no fact that contradicts it", "does not decline", "not a refusal", "nothing incorrect", "no errors"):
        assert f'"{phrase}"' in text and scoring.parse_judge(data._j("CORRECT", "The candidate states it; " + phrase + ".")) == "CORRECT"
    assert 'Any other "not" or "no" still refuses the verdict' in text
    assert scoring.parse_judge(data._j("CORRECT", "not the same")) == U
    # what it says is still lost
    for reply in ('{"verdict": "CORRECT", "reason": "Candidate correctly states Not', data._j("DECLINED", "Reference is NO ANSWER.")):
        key = "NH" if "CORRECT" in reply else "UA"
        assert judge_tests.read(key, reply)["verdict"] == U
    assert '"Candidate correctly states Not"' in text and '"Reference is NO ANSWER."' in text
    assert "120 read as a blind reader labelled the answers (110 before the fix" in text
    # the candidate's own words stay in the reply
    assert """'Candidate says "The use case is not Deployed."'""" in text
    assert judge_tests.verdict("NOT", 'Candidate says "The use case is not Deployed."') == U


def test_item_18_says_how_raw_jsonl_is_written_and_read():
    text = item(18)
    assert f"scoring version `{scoring.SCORING_VERSION}`" in text and "raw_cut_off_row.txt" in text
    assert "one row per physical line whatever text a row holds" in text and "before the first billed call" in text
    assert "raw_cut_off_row.txt" in (KIT_DIR / "50_run_eval.py").read_text(encoding="utf-8")


def test_the_file_table_and_the_test_counts_name_round_3():
    assert "| `kitlib/jsonl.py` |" in section(1)
    match = re.search(r"([\d,]+) of them are in `tests/test_review_r3_\*\.py`, written for the two defects the rehearsal "
                      r"found; run against the code as it was before that fix, ([\d,]+) of those ([\d,]+) fail", section(8))
    assert match and match.group(1) == match.group(3)
    assert int(match.group(2).replace(",", "")) < int(match.group(1).replace(",", ""))
    assert "fixed four times" in section(8)                    # round 4 was the fourth
    assert "no result in this kit's files is a measured result" in section(7) and "The rehearsal table in section 8 is not one either" in section(7)


def test_older_sentences_the_fix_made_untrue_are_gone():
    assert "have still never met a model" not in README
    assert "the scoring version is `2026-10-07.r2`" not in README
    assert json.dumps(scoring.SCORING_VERSION) == '"2026-10-08.r5"'      # r3 until the fourth review, r4 until the fifth
    assert "(scoring version `2026-10-07.r3`), cannot be resumed" not in README
