"""START_HERE.md held to README.md and to the scripts.

START_HERE.md is the one-page order of work. It repeats commands that README.md gives in
sections 3 to 5, and it says what the last line of each script should be. These tests fail when
it grows past 80 lines, when a command in it is no longer the README's, character for
character, or when a line it quotes is no longer in the script that prints it. Offline: they
only read files of the kit.
"""
from __future__ import annotations

import re

from conftest import KIT_DIR as KIT

PATH = KIT / "START_HERE.md"
README = (KIT / "README.md").read_text(encoding="utf-8")
SECTIONS = [
    "What this is", "What it costs, and the one thing that stops the bill", "Before you start", "Problems first",
    "The commands, in order", "Tear down and prove it", "If something goes wrong", "What to write down",
    "Where the rest is",
]
# A script of the kit, the words START_HERE.md quotes from what that script prints, and (when the
# script builds the line from a constant) the words as they stand in the script's source.
QUOTED_FROM_SCRIPTS = [
    ('00_check.py', "DRY-RUN: the API calls above were printed and checked against the SDK's API model. None was sent."),
    ('00_check.py', 'No problem found. This does not prove model access unless you ran --invoke-test.'),
    ('00_check.py', 'PROBLEM:'),
    ('10_build_corpus.py', 'Next: python 20_build_eval_set.py'),
    ('20_build_eval_set.py', 'Read a dozen of the questions yourself before spending money on them.'),
    ('30_deploy_kb.py', "DRY-RUN: every call above was checked against the SDK's API model. None was sent."),
    ('30_deploy_kb.py', 'Write these numbers into RESULTS_TEMPLATE.md. Next: python 40_create_guardrail.py'),
    ('40_create_guardrail.py', 'Next: python 50_run_eval.py --limit 5 --i-understand-this-bills'),
    ('50_run_eval.py', 'Copy the table into RESULTS_TEMPLATE.md. When you are finished: python 90_teardown.py'),
    ('50_run_eval.py', 'INCOMPLETE:'),
    ('90_teardown.py', 'RESULT: NOTHING WAS DELETED (--dry-run)'),
    ('90_teardown.py', 'RESULT: every recorded resource was deleted or confirmed absent in'),
    ('90_teardown.py', 'That is not proof. Now run: python 99_verify_clean.py'),
    ('90_teardown.py', 'NOT CONFIRMED', 'RESULT: NOT CONFIRMED.'),
    ('99_verify_clean.py', 'RESULT: CLEAN in'),
    ('99_verify_clean.py', 'This is the place .state.json names'),
    ('99_verify_clean.py', 'NO STATE FILE'),
    ('../common/whats_running.py', 'nothing that bills while idle was found, and every check ran (exit'),
]
# The commands of README sections 4 and 5 that START_HERE.md must give, in the README's order.
MUST_HAVE = [
    'python 00_check.py --dry-run',
    'python 00_check.py',
    'python 00_check.py --invoke-test --i-understand-this-bills    # one tiny request per model; the real proof of access',
    'python 10_build_corpus.py',
    'python 20_build_eval_set.py',
    'python 30_deploy_kb.py --dry-run',
    'python 30_deploy_kb.py --i-understand-this-bills',
    'python 40_create_guardrail.py --i-understand-this-bills',
    'python 50_run_eval.py --limit 5 --i-understand-this-bills',
    'python 50_run_eval.py --i-understand-this-bills',
    'python 90_teardown.py --dry-run     # shows every delete call; exit code 5, never 0',
    'python 90_teardown.py               # asks once, then deletes each resource separately',
    'python 99_verify_clean.py           # exit code 0 means clean in the place named on its RESULT line',
    'python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>',
]


def start() -> str:
    assert PATH.is_file(), "START_HERE.md is missing from the kit folder"
    return PATH.read_text(encoding="utf-8")


def section(title: str) -> str:
    text = start()
    begin = text.index(f"## {title}\n")
    later = [text.index(f"## {other}\n") for other in SECTIONS if text.index(f"## {other}\n") > begin]
    return text[begin:min(later)] if later else text[begin:]


def code_block_lines(text: str) -> list[str]:
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            inside = not inside
        elif inside and line.strip():
            lines.append(line)
    assert not inside, "a code fence in START_HERE.md is not closed"
    return lines


def commands_in_the_readme() -> set[str]:
    """Every form in which the README writes a command out: a whole line, with its indentation
    and a list number such as ' 3. ' set aside, or the whole text between two backticks."""
    known = set(re.findall(r"`([^`\n]+)`", README))
    for line in README.splitlines():
        known.add(line.strip())
        known.add(re.sub(r"^\d+\.\s+", "", line.strip()))
    return known


def test_start_here_exists_is_at_most_80_lines_and_has_no_em_or_en_dash():
    text = start()
    assert len(text.splitlines()) <= 80, len(text.splitlines())
    assert chr(0x2014) not in text and chr(0x2013) not in text
    # the README sends a first-time reader here from its first lines
    assert "`START_HERE.md`" in "\n".join(README.splitlines()[:6])


def test_start_here_has_its_nine_sections_in_order():
    text = start()
    assert re.findall(r"^## (.+)$", text, flags=re.M) == SECTIONS
    assert len([line for line in section("What this is").splitlines()[1:] if line.strip()]) == 3
    cost = section(SECTIONS[1])
    assert "$" in cost and "`python 90_teardown.py`" in cost and "The one thing that stops the bill is" in cost
    before = section("Before you start")
    assert "root user" in before and "README section 3" in before and "uota" in before and "```" in before
    problems = [line for line in section("Problems first").splitlines()[1:] if line.strip()]
    assert 1 <= len(problems) <= 6
    for number, line in enumerate(problems, start=1):
        assert line.startswith(f"{number}. ") and line.endswith("."), line
        assert not re.search(r"[.!?][\"`)]? [A-Z]", line[3:]), f"more than one sentence: {line}"
    wrong = section("If something goes wrong")
    assert "The file never to touch: `.state.json`" in wrong and "The script to run" in wrong
    assert "`python 90_teardown.py`" in wrong and "README section" in wrong
    assert "`RESULTS_TEMPLATE.md`" in section("What to write down")
    rest = section("Where the rest is")
    assert rest.splitlines()[1].startswith("README section 2")
    for number in range(2, 9):
        assert re.search(rf"\b{number}\b", rest), f"section {number} is not named"
    proof = section("Tear down and prove it")
    assert "Exit code 0 is not enough" in proof and "RESULT" in proof and "whats_running.py" in proof
    # no history and no review counts on this page
    assert not re.search(r"\bround \d|\breview|\bfinding", text, flags=re.I)


def test_every_code_block_line_of_start_here_is_in_the_readme_character_for_character():
    lines = code_block_lines(start())
    assert len(lines) >= 17, "START_HERE.md should give the commands in code blocks"
    known = commands_in_the_readme()
    drifted = [line for line in lines if line not in known or line not in README]
    assert not drifted, "in START_HERE.md but not, character for character, in README.md:\n" + "\n".join(drifted)
    # the commands of sections 4 and 5 are all there, in the README's order
    text = start()
    for command in MUST_HAVE:
        assert command in lines or f"`{command}`" in text, command
    in_blocks = [command for command in MUST_HAVE if command in lines]
    assert [lines.index(c) for c in in_blocks] == sorted(lines.index(c) for c in in_blocks)


def test_every_command_start_here_gives_inside_a_sentence_is_in_the_readme_too():
    known = commands_in_the_readme()
    spans = [span for span in re.findall(r"`([^`\n]+)`", start())
             if span.startswith(("python ", "aws ", "pip ", "cp ", "echo "))]
    assert spans
    assert [span for span in spans if span not in known] == []


def test_the_last_lines_start_here_quotes_are_printed_by_the_scripts_it_names():
    text = start()
    for script, words, *in_source in QUOTED_FROM_SCRIPTS:
        path = KIT / script
        if script.startswith("../") and not path.is_file():
            continue  # the shared folder is not beside this kit: nothing to compare with
        assert words in text, f"START_HERE.md no longer quotes {words!r}"
        wanted = in_source[0] if in_source else words
        assert wanted in path.read_text(encoding="utf-8"), f"{script} no longer prints {wanted!r}"


def test_every_dollar_figure_of_start_here_is_in_the_readme():
    figures = re.findall(r"\$\d[\d,]*(?:\.\d+)?", start())
    assert figures
    assert [figure for figure in figures if figure not in README] == []
