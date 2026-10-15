"""Round 2 review: the README, the results template and the generated summary say what the code does.

B2 named three sentences that called exact match strict while it credited wrong answers. They
are gone, and what replaced them is tied to the code here, so the words and the rules cannot
drift apart again without a test failing.
"""
from __future__ import annotations

import json
import re

import adversarial_r2
import judge_replies_r2
from conftest import KIT_DIR
from kitlib import scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, STAGE_LABELS, TEMPLATES, simple_label_set

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
TEMPLATE = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
AGENCIES = json.loads((KIT_DIR / "tests" / "fixtures" / "agencies_41.json").read_text(encoding="utf-8"))["agencies"]
LABEL_SETS = {
    "agency": [{"label": name, "aliases": [{"text": abbr, "case_sensitive": True}]} for name, abbr in AGENCIES],
    "stage": simple_label_set(STAGE_LABELS), "high_impact": simple_label_set(HIGH_IMPACT_LABELS)}


def section(number: int) -> str:
    return re.split(r"^## \d+\. .*$", README, flags=re.MULTILINE)[number]


def item(number: int) -> str:
    text = section(2)
    start = text.index(f"\n{number}. **")
    following = re.search(rf"\n{number + 1}\. \*\*", text[start:])
    return text[start:start + following.start()] if following else text[start:]


def exact(kind: str, expected: str, answer: str) -> dict:
    question = TEMPLATES[kind].format(name="Some tool for testing", agency_name="Department of Justice")
    return scoring.score_exact({"answerable": True, "label_set": kind, "expected_answer": expected,
                                "use_case_name": "Some tool for testing", "question": question}, answer, LABEL_SETS)


# --- B2: the three sentences ---------------------------------------------------------------------------------

def test_the_three_sentences_the_review_named_are_gone():
    assert "strict on purpose and will undercount" not in README
    assert "by a strict exact-match check" not in README
    source = (KIT_DIR / "kitlib" / "scoring.py").read_text(encoding="utf-8")
    assert 'fail towards "not correct"' not in source
    assert "It is built not to credit a wrong one" in item(8)
    assert "gives credit only when the answer is the expected value plus words from a short fixed list" in section(7)
    assert "and could not read U of 100, which it counts as not correct" in section(7)
    assert "The judge was an Amazon Nova model grading an Amazon Nova generator" in section(7)
    assert "always give U when you quote Y" in section(7)
    assert 'That Y is "the accuracy"' in section(7)
    assert "is proved never to credit a wrong answer" in section(7)       # in the list of what you cannot say


def test_item_8_lists_every_filler_phrase_and_the_count():
    text = item(8).lower().replace("-", " ")
    total = sum(len(phrases) for phrases in scoring.FILLER_PHRASES.values())
    assert f"one short list of {total} phrases" in item(8)
    for phrases in scoring.FILLER_PHRASES.values():
        for phrase in phrases:
            shown = {"u s": "u.s."}.get(phrase, phrase)
            if phrase.startswith("according to "):
                shown = phrase[len("according to "):]
            assert f'"{shown}"' in text, phrase
    assert '"according to"' in text


def test_every_example_in_item_8_is_scored_the_way_the_readme_says():
    text = item(8)
    unclear = [("stage", "Deployed", "Deployed (not Retired)"), ("stage", "Deployed", "Is it Deployed"),
               ("stage", "Deployed", "It deployed the use case"), ("stage", "Retired", "Retired. It was previously Deployed."),
               ("stage", "Deployed", "As of May 2025 it is Deployed."),
               ("agency", "Environmental Protection Agency", "It is probably the Environmental Protection Agency."),
               ("agency", "Environmental Protection Agency",
                "Environmental Protection Agency (EPA), Office of Mission Support."),
               ("agency", "Department of Veterans Affairs", "VA"),
               ("agency", "Securities and Exchange Commission", "The SEC."),
               ("agency", "Environmental Protection Agency", "epa"),
               ("stage", "Pilot", "The use case is being piloted."),
               ("high_impact", "Not High-impact", "It isn't high-impact."),
               ("agency", "Department of Energy", "Energy"), ("agency", "Department of the Treasury", "Treasury"),
               ("high_impact", "High-impact", '{"high_impact": true}'),
               ("agency", "Department of State", "The State Department of Transportation")]
    for kind, expected, answer in unclear:
        assert answer in text, answer
        result = exact(kind, expected, answer)
        assert (result["exact"], result["unclear"]) == (False, True), answer
    for kind, expected, answer in (("stage", "Pre-deployment", "Pre deployment"),
                                   ("stage", "Pre-deployment", "Predeployment"),
                                   ("agency", "Department of State", "Department of State (STATE)"),
                                   ("agency", "Department of Veterans Affairs", "Veterans Affairs"),
                                   ("agency", "Department of Health and Human Services", "Health and Human Services")):
        assert answer in text and exact(kind, expected, answer)["exact"] is True, answer
    for words in ("is to be Deployed", "will be", "formerly", "yet to be", "rather than", "instead of", "other than",
                  "unlike"):
        assert words in text, words
    refusal_examples = ("I'm sorry, but I cannot answer this from the inventory documents provided.", "I don't know.")
    for answer in refusal_examples:
        assert answer in text and scoring.is_decline(answer) is False
    assert scoring.DECLINE_SENTENCE in text


def test_item_8_states_the_counts_the_code_gives():
    text = item(8)
    alone = sum(1 for _, abbr in AGENCIES if scoring.abbreviation_stands_alone(abbr))
    names, dropped = scoring.agency_short_names(LABEL_SETS["agency"])
    assert f"the other {alone} count alone" in text and "VA, ED, STATE, DOC, DOT, DOE and SEC" in text
    assert f"These {sum(len(v) for v in names.values())} short names were checked against all {len(AGENCIES)} agency names" in text
    assert dropped == []
    departments = sum(1 for name, _ in AGENCIES if name.startswith("Department of "))
    assert f'for the {departments} "Department of X" agencies' in text
    keys = sum(len(v) for v in scoring.JSON_ANSWER_KEYS.values())
    assert keys == 10 and "and seven more keys" in text
    lost_rows = re.findall(r"^   \| [^|]+ \| (\d+) \| .*\|$", text, flags=re.MULTILINE)
    assert [int(n) for n in lost_rows] == [14, 12, 7, 7, 5, 4, 3, 3, 3, 2]
    assert sum(int(n) for n in lost_rows) + 1 == 61 and "it now scores 61 answers wrong" in text
    assert "it gave credit to 38 of those 250 answers" in text


def test_item_9_describes_the_judge_parser_as_it_is():
    text = item(9)
    U = scoring.UNPARSEABLE
    for reply in ("not correct", "PARTIALLY CORRECT", "The candidate is correct.",
                  '{"verdict": "CORRECT", "reason": "The candidate is not correct"}',
                  '{"verdict": "DECLINED", "reason": "The candidate answered Department of Energy"}'):
        assert reply in text and scoring.parse_judge(reply) == U, reply
    assert scoring.parse_judge("Verdict: CORRECT") == "CORRECT" and '"Verdict: CORRECT"' in text
    assert scoring.parse_judge("The verdict is CORRECT.") == "CORRECT" and "The verdict is CORRECT." in text
    assert f"one of {len(scoring.CONTRADICTS_CORRECT)} patterns" in text
    # Round 4: the first of the two limits the item admitted to is caught now, also without the question (the reply
    # gives two different things), and the item says so. The limits that remain are in tests/judge_replies_r4.py.
    not_caught = '{"verdict": "CORRECT", "reason": "The candidate says DOE; the reference says EPA."}'
    assert "The candidate says DOE; the reference says EPA." in text and scoring.parse_judge(not_caught) == U
    innocent = '{"verdict": "CORRECT", "reason": "only the abbreviation is given"}'
    assert "only the abbreviation is given" in text and scoring.parse_judge(innocent) == U
    assert "COULD NOT TELL" in text and "judge verdict unclear" in text
    assert "0 read flatteringly (7 before), 9 lost (22 before)" in text


# --- the dated line and the round 2 record -------------------------------------------------------------------

def test_section_8_carries_the_dated_round_2_line_and_its_numbers_add_up():
    match = re.search(r"Reviewed independently a second time on 2026-10-07 \(round 2\): (\d+) findings for this kit, "
                      r"(\d+) fixed, (\d+) left open \(listed below\)", section(8))
    assert match
    findings, fixed, left_open = map(int, match.groups())
    assert findings == 18 and fixed + left_open == findings
    table = section(8).split("The 18 findings and what was done:")[1].split("Also changed without being asked")[0]
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| Finding")]
    assert len(rows) == findings
    assert section(8).index("round 2") < section(8).index("round 1")
    assert "What is still wrong or unproven after round 2, bad news first" in section(8)


def test_the_acceptance_numbers_in_section_8_are_the_ones_the_test_sets_give():
    text = section(8)
    own = len(adversarial_r2.ANSWERS)
    rejected = sum(1 for _, _, label, _ in adversarial_r2.ANSWERS if not label)
    assert f"{own} answers on made-up use cases, {rejected} of them ones a person would reject" in text
    replies = len(judge_replies_r2.REPLIES)
    names = {"C": "CORRECT", "I": "INCORRECT", "D": "DECLINED", "U": scoring.UNPARSEABLE}
    lost = sum(1 for reply, label in judge_replies_r2.REPLIES
               if scoring.parse_judge(reply) == scoring.UNPARSEABLE and label != "U")
    assert f"The fixer's own {replies} judge replies (`tests/judge_replies_r2.py`): flattering 0 of {replies}, " \
           f"lost {lost} of {replies}" in text
    assert "false credit 0 of 250 (38 before), lost credit 61 of 250 (40 before)" in text
    assert "flattering 0 of 88 (7 before), lost 9 of 88 (22 before)" in text
    assert "0 of 41" in text and "131 teardown and clean-check commands" in text
    assert all(names[label] for _, label in judge_replies_r2.REPLIES)


def test_the_test_counts_in_the_readme_are_numbers_and_agree():
    match = re.search(r"`python -m pytest -q`: ([\d,]+) tests passed, 0 failed", section(8))
    assert match
    assert f"| `tests/` | {match.group(1)} offline tests" in section(1)
    assert re.search(r"([\d,]+) of them are in `tests/test_review_r2_\*\.py`", section(8))


# --- what the kit ships, and what the builder prints ----------------------------------------------------------

def test_the_readme_says_which_data_ships_with_the_kit():
    text = item(13)
    assert "tests/fixtures/inventory_5rows.csv" in text and "tests/fixtures/agencies_41.json" in text
    assert "the 41 distinct agency names with their abbreviations" in text
    for path in (KIT_DIR / "tests").rglob("*"):
        if path.is_file() and path.suffix in (".py", ".json"):
            content = path.read_text(encoding="utf-8")
            # Use case names the reader's set quoted from the inventory must not have come along. They are
            # put together here from two halves, so that this file does not hold them either.
            for first, second in (("CUI Marking", "Tool"), ("BudgetChat", "AI Tool"), ("SUVI Thematic", "Maps"),
                                  ("OpenET", "irrigation"), ("Evapotranspiration", "mapping")):
                assert f"{first} {second}" not in content, (path.name, first)


def test_the_near_duplicate_count_is_stated_both_ways():
    assert "turns down 6 candidates, which are 5 different CSV rows" in item(14)
    assert "turned down 6 candidates, which are 5 different CSV rows" in section(8)
    assert "that turns down 5 rows" not in README


# --- sections 5 and 6: teardown and what to record ---------------------------------------------------------------

def test_section_5_documents_the_teardown_as_it_behaves():
    five = section(5)
    teardown = (KIT_DIR / "90_teardown.py").read_text(encoding="utf-8")
    assert "EXIT_DRY_RUN = 5" in teardown and "exit code 5, never 0" in five
    for flag in ("--region", "--prefix"):
        assert flag in five and f'"{flag}"' in teardown
    for phrase in ("NOT FINISHED", "NOT CONFIRMED", "NO STATE FILE", "move the file out of the folder yourself",
                   "none deletes or overwrites the file", "never CLEAN"):
        assert phrase in five, phrase
    for phrase in ("NOT FINISHED", "NOT CONFIRMED", "NO STATE FILE"):
        assert phrase in teardown
    clean = (KIT_DIR / "99_verify_clean.py").read_text(encoding="utf-8")
    assert "NO STATE FILE was found" in clean and "This is the place .state.json names" in clean
    assert "This is the place .state.json names" in five
    assert "a guardrail created with `40_create_guardrail.py` alone" in five       # the limit that remains
    assert "item 19" in five or "section 5" in item(19)


def test_section_6_asks_only_for_numbers_a_script_prints():
    six = section(6)
    assert "none has to be timed by hand" in six
    for line, script in (("Minutes from the start of this script to ingestion COMPLETE", "30_deploy_kb.py"),
                         ("Date and time 90_teardown.py finished", "90_teardown.py"),
                         ("Hours the knowledge base existed", "90_teardown.py")):
        assert line in six and line in (KIT_DIR / script).read_text(encoding="utf-8"), line
    for column in ("exact_unclear", "exact_note", "exact_unread", "judge_note"):
        assert column in six
    from kitlib import evalloop
    for column in ("exact_unclear", "exact_note", "exact_unread", "judge_note"):
        assert column in evalloop.CSV_COLUMNS


def test_the_results_template_has_the_rows_of_the_generated_table():
    summary = scoring.render_summary_markdown(scoring.summarise([], top_k=5))
    names = [line.split("|")[1].strip() for line in summary.splitlines()
             if line.startswith("| ") and line.count("|") == 4 and not line.startswith("| Measure")]
    assert len(names) == 20
    for name in names:
        template_name = name.replace("top 5", "top k")
        assert f"| {template_name} |" in TEMPLATE, name
    for phrase in ("first N of 120", "not applied", "COULD NOT TELL", "exact_unclear", "judge_note",
                   "printed by 90_teardown.py"):
        assert phrase in TEMPLATE, phrase


def test_the_generated_summary_describes_exact_match_as_what_it_is():
    summary = scoring.render_summary_markdown(scoring.summarise([], top_k=5))
    assert "Exact match gives credit only when the answer is the expected value plus words from a short fixed list" \
        in summary
    assert "So the exact-match rate can undercount" in summary and "strict" not in summary
    assert "either filter, grounding or relevance" in summary
    assert "when its own reason or other text speaks against the verdict it states" in summary
