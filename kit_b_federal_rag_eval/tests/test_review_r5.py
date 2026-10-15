"""Round 5 (fifth review, reader B): F1 to F7.

F1 (MAJOR)  DECLINED was credited when its own reason says the candidate gave a value ("The candidate's answer contains
            a budget figure that the documents lack.": 16 of 16 of the reader's replies).
F2          CORRECT was credited when a second sentence contradicts the reference ("The candidate matches the reference.
            The impact is high." for "Not High-impact": 9 of 9), and the comment in scoring.py said that cannot pass.
F3          Removing a damaged row of raw.jsonl, as the refusal message says, made a finished question read as "in
            flight" on the next --resume: a false message, a phantom interrupted row, calls counted twice, a re-billed
            question.
F4          http.client.IncompleteRead during the corpus download gave a traceback instead of the ERROR message.
F5          Ordinary DECLINED replies were lost (7 of 16 of the reader's).
F6          A second damaged calls record replaced the first, so the NOT COUNTED note said 1 question where 2 were lost.
F7          .gitignore missed ordinary copies of the state file ("state.json", ".state copy.json", ...).

Every test here states the outcome a careful person expects. Against the kit as it was reviewed in round 5 the tests of
F1 to F7 fail (the counts are in REVIEW_NOTES_r5.md). Nothing here calls AWS or the network.
"""
from __future__ import annotations

import fnmatch
import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import judge_replies_r4 as replies_r4
import judge_replies_r5 as data
from conftest import KIT_DIR
from fakeaws import BILLS
from kitlib import scoring
from kitlib.evalset import NO_ANSWER, TEMPLATES
from test_review_r2_exact import LABEL_SETS, NAME, REPORTER, make_item
from test_review_r4_usage import (Counting, out_dir_of, printed_usage, rows_of, run_eval,  # noqa: F401 (fixture)
                                  served_usage)

U = scoring.UNPARSEABLE
BUDGET = {"id": "q-101", "type": "unanswerable_absent_field", "answerable": False,
          "question": f'What annual budget in dollars is recorded for the AI use case named "{NAME}", reported by the '
                      f'{REPORTER}?',
          "use_case_name": NAME, "expected_answer": NO_ANSWER, "label_set": None, "accepted_aliases": [],
          "source_doc_id": None}
HELD_OUT = dict(BUDGET, id="q-102", type="unanswerable_heldout", question=TEMPLATES["agency"].format(name=NAME))


def item_for(kind: str, expected: str | None) -> dict:
    return {"U_budget": BUDGET, "U": BUDGET, "U_heldout": HELD_OUT}.get(kind) or make_item(kind, expected)


def judged(kind: str, expected: str | None, reply: str) -> dict:
    return scoring.read_judge(reply, item_for(kind, expected), "x", LABEL_SETS)


def declined(reason: str, item: dict = BUDGET) -> str:
    return scoring.read_judge(json.dumps({"verdict": "DECLINED", "reason": reason}), item, "x", LABEL_SETS)["verdict"]


# --- F1, F2, F5: the reader's judge cases, word for word ------------------------------------------------------------

@pytest.mark.parametrize("kind,expected,reply,operator,word", data.READER_R5)
def test_the_readers_judge_cases_come_out_as_a_person_reads_them(kind, expected, reply, operator, word):
    got = judged(kind, expected, reply)["verdict"]
    assert (got == word) is (operator == "=="), (got, reply)


def test_the_readers_three_judge_findings_are_all_there():
    replies = [reply for _, _, reply, _, _ in data.READER_R5]
    assert len(data.READER_R5) == 55 and len(set(replies)) == len(replies) - 1     # one reply is asked of two stages
    assert sum(1 for _, _, _, operator, word in data.READER_R5 if (operator, word) == ("!=", "DECLINED")) == 16 + 5
    assert sum(1 for kind, _, _, operator, word in data.READER_R5 if (operator, word) == ("==", "DECLINED")) == 7 + 9


# --- F1: what a DECLINED reason says of the candidate ---------------------------------------------------------------

@pytest.mark.parametrize("reason", data.FIXER_R5_NOT_A_REFUSAL)
@pytest.mark.parametrize("item", [BUDGET, HELD_OUT], ids=["budget", "held_out"])
def test_a_reason_that_says_the_candidate_gave_something_is_not_a_refusal(reason, item):
    assert declined(reason, item) == U


@pytest.mark.parametrize("reason", data.FIXER_R5_HUNTED)
def test_a_shape_found_while_attacking_the_round_5_reader_is_not_a_refusal(reason):
    assert declined(reason) == U


def test_the_judges_own_words_that_the_answer_is_not_there_no_longer_count_as_the_candidate_declining():
    # rule 5: credit needs the candidate to be said to decline, or to say it is not there
    assert declined("The information is not available in the documents.") == U
    assert declined("The candidate says the information is not available in the documents.") == "DECLINED"
    assert declined("The candidate states that the information is not available in the passages.") == "DECLINED"
    assert declined("The candidate declines because the documents lack budget data.") == "DECLINED"
    assert declined("No answer was given by the candidate.") == "DECLINED"


def test_the_round_5_rules_are_not_applied_without_the_question():
    """Without the question (only scoring.read_judge called by hand) the round 4 rules apply: README section 2, item 9."""
    reply = json.dumps({"verdict": "DECLINED", "reason": "The candidate acknowledged the budget figure; the documents do not "
                                                         "contain it."})
    assert scoring.read_judge(reply)["verdict"] == "DECLINED"
    assert scoring.read_judge(reply, BUDGET, "x", LABEL_SETS)["verdict"] == U


@pytest.mark.parametrize("word,reason", data.STILL_READ_FLATTERINGLY_R5)
def test_what_is_still_read_as_credit_with_the_question_is_named_in_the_readme(word, reason):
    assert declined(reason) == word                            # "its" may be the use case's: README section 2, item 9
    readme = (KIT_DIR / "README.md").read_text(encoding="utf-8")
    notes = (KIT_DIR / "REVIEW_NOTES_r5.md").read_text(encoding="utf-8")
    assert f'"{reason}"' in readme and reason in notes


def test_the_two_round_4_limits_caught_now_are_caught_with_the_question_only():
    caught = [entry for entry in replies_r4.STILL_READ_FLATTERINGLY if entry[1] == "DECLINED" and entry[0] == "UHW"
              and "navy" not in entry[2]]
    assert [entry[2] for entry in caught] == ["The candidate declines. The agency is in the answer.",
                                             "The candidate has the answer. It declines to say so."]
    for _, _, reason, with_question, without_question in caught:
        assert declined(reason, HELD_OUT) == U and with_question is False and without_question is True


def test_the_round_5_rules_are_fast_on_a_long_reply():
    """A draft read each subject against the whole rest of its sentence: 5 to 8 seconds for these. One pass now."""
    import time
    started = time.perf_counter()
    for reason in ("it cannot answer, " * 3000, "the candidate, the candidate, " * 2000 + "declines",
                   "The candidate says it cannot answer. " * 3000, "it cannot answer because " * 2000 + "it declines"):
        declined(reason)
    assert time.perf_counter() - started < 4.0


# --- F5: ordinary refusals ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reason", data.FIXER_R5_REFUSALS)
@pytest.mark.parametrize("item", [BUDGET, HELD_OUT], ids=["budget", "held_out"])
def test_an_ordinary_refusal_is_read_as_declined(reason, item):
    assert declined(reason, item) == "DECLINED"


def test_which_is_correct_after_a_refusal_is_not_read_against_it_but_a_correct_answer_still_is():
    assert declined("The candidate declined to answer, which is correct since there is no answer.") == "DECLINED"
    assert declined("The candidate declined to answer, which is not correct.") == U
    assert declined("The candidate's answer is correct.") == U
    assert declined("The candidate gives the agency, which is correct.") == U


def test_does_not_use_the_refusal_sentence_is_not_a_refusal():
    for reason in ("The candidate does not use the refusal sentence.", "The candidate did not give a refusal.",
                   "The candidate does not include the refusal sentence and does not answer."):
        assert declined(reason) == U, reason


# --- the fixer's second set, written before it was run ---------------------------------------------------------------

def test_the_second_set_reads_as_the_notes_say_and_what_it_misses_is_lost_never_credit():
    right, missed = 0, []
    for kind, expected, word, want, reason in data.FIXER_R5_SECOND_SET:
        got = judged(kind, expected, json.dumps({"verdict": word, "reason": reason}))["verdict"]
        if (got == word) is (want == word):
            right += 1
        else:
            missed.append((reason, got))
    assert right == 43 and len(data.FIXER_R5_SECOND_SET) == 46
    assert sorted(reason for reason, _ in missed) == sorted(data.FIXER_R5_SECOND_SET_LOST)
    assert all(got == U for _, got in missed)


# --- F2: a second sentence about the value under CORRECT -------------------------------------------------------------

@pytest.mark.parametrize("kind,expected", [("high_impact", "Not High-impact"), ("high_impact", "High-impact"),
                                           ("stage", "Deployed"), ("agency", "Department of Energy")])
def test_the_impact_is_high_is_refused_in_every_kind_of_question(kind, expected):
    """The comment above JUDGE_TIE_WORDS says so since round 5; until then it said so and was not true."""
    for reason in ("The candidate matches the reference. The impact is high.", "Matches the reference; impact is high.",
                   "The candidate matches the reference. It was determined to be high in impact."):
        got = judged(kind, expected, json.dumps({"verdict": "CORRECT", "reason": reason}))
        assert got["verdict"] == U and "in words of its own" in got["why"], (kind, reason)
    source = (KIT_DIR / "kitlib" / "scoring.py").read_text(encoding="utf-8")
    assert "nowhere else may \"the impact is high\" pass for a tie" not in source


@pytest.mark.parametrize("expected,reason", [
    ("Deployed", "The candidate matches the reference. The use case is in development."),
    ("Deployed", "The candidate matches the reference. The use case is in the development stage."),
    ("Retired", "The candidate matches the reference. The use case is in use."),
])
def test_a_stage_said_in_other_words_after_the_match_is_refused(expected, reason):
    assert judged("stage", expected, json.dumps({"verdict": "CORRECT", "reason": reason}))["verdict"] == U


@pytest.mark.parametrize("kind,expected,reason", [
    ("high_impact", "Not High-impact", "The candidate states the high-impact determination is Not High-impact, matching the reference."),
    ("high_impact", "Not High-impact", "The candidate correctly reports the high-impact determination as Not High-impact."),
    ("stage", "Deployed", "The candidate states the stage of development is Deployed, matching the reference."),
    ("stage", "Deployed", "The candidate's development stage matches the reference."),
    ("stage", "Deployed", "The candidate says the AI use case is Deployed, which matches the reference."),
    ("high_impact", "High-impact", "The candidate says the use case is high impact, same as the reference."),
])
def test_a_field_name_and_the_reference_value_itself_are_not_value_words_of_their_own(kind, expected, reason):
    assert judged(kind, expected, json.dumps({"verdict": "CORRECT", "reason": reason}))["verdict"] == "CORRECT"


# --- F3: removing a damaged row, as the refusal message says ---------------------------------------------------------

def _damage_and_remove(out_dir, line_number):
    raw = out_dir / "raw.jsonl"
    lines = raw.read_bytes().split(b"\n")
    lines[line_number - 1] = b'{"id": "q-00' + str(line_number).encode() + b'", "answer": "half'
    raw.write_bytes(b"\n".join(lines))
    return raw, lines


def test_removing_a_damaged_row_of_another_question_runs_only_that_question_again(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS]) == 0
    out_dir = out_dir_of(tmp_path)
    raw, lines = _damage_and_remove(out_dir, 2)
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 1
    err = capsys.readouterr().err
    assert "Repair or remove that line by hand" in err
    assert "If you remove it, its question is run again and the calls that row held are no longer in the usage line." in err
    del lines[1]
    raw.write_bytes(b"\n".join(lines))
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "in flight" not in out and not [row for row in rows_of(out_dir) if row.get("interrupted")]
    assert printed_usage(out_dir)["retrieve_calls"] == 6                 # five kept rows and q-002 once more
    retrieved = [question for operation, question, _ in Counting.served if operation == "retrieve"]
    assert retrieved.count("q-002") == 2 and retrieved.count("q-006") == 1
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is True and summary["usage"]["interrupted_attempts_included"] == 0
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0           # and a second resume adds nothing
    assert [question for operation, question, _ in Counting.served if operation == "retrieve"] == retrieved


def test_a_question_really_in_flight_is_still_found_after_another_row_was_removed(run_eval, tmp_path, capsys):
    Counting.faults = {("generate", "q-004"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130                                # q-004's Retrieve was answered and billed
    out_dir = out_dir_of(tmp_path)
    raw = out_dir / "raw.jsonl"
    lines = raw.read_bytes().split(b"\n")
    del lines[0]                                                        # q-001's row removed by hand
    raw.write_bytes(b"\n".join(lines))
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "q-004 was in flight when the run was stopped: 1 call had been answered (Retrieve)" in out
    interrupted = [row["id"] for row in rows_of(out_dir) if row.get("interrupted")]
    assert interrupted == ["q-004"]
    # every call that was served is counted except the three of q-001's removed row (one Retrieve among them)
    assert printed_usage(out_dir)["retrieve_calls"] == served_usage()["retrieve_calls"] - 1


def test_the_record_says_how_many_rows_of_its_own_question_there_were(run_eval, tmp_path):
    Counting.faults = {("judge", "q-002"): [RuntimeError("ThrottlingException")]}
    assert run_eval.main([BILLS]) == 1
    out_dir = out_dir_of(tmp_path)
    Counting.faults = {("guardrail", "q-002"): [KeyboardInterrupt()]}      # q-002 runs again first, and is stopped
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 130
    record = json.loads((out_dir / "last_question_calls.json").read_text(encoding="utf-8"))
    assert record["id"] == "q-002" and record["question_rows_before"] == 1 and record["rows_before"] == 6
    Counting.faults = {}
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert [row["id"] for row in rows_of(out_dir) if row.get("interrupted")] == ["q-002"]
    assert printed_usage(out_dir) == served_usage()


def test_a_record_written_before_round_5_is_read_by_the_round_4_rule(run_eval, tmp_path, capsys):
    Counting.faults = {("guardrail", "q-003"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    path = out_dir / "last_question_calls.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["question_rows_before"]
    path.write_text(json.dumps(record), encoding="utf-8")
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert "q-003 was in flight" in capsys.readouterr().out
    assert printed_usage(out_dir) == served_usage()


# --- F4: a download cut short ----------------------------------------------------------------------------------------

class _Body:
    def __init__(self, error):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        raise self.error


@pytest.mark.parametrize("error", [http.client.IncompleteRead(b"x" * 1000, 5_000_000), http.client.BadStatusLine("HTTP/1.1 ??"),
                                   http.client.RemoteDisconnected("Remote end closed connection without response")],
                         ids=["incomplete_read", "bad_status_line", "remote_disconnected"])
def test_a_download_cut_short_is_one_message_and_builds_nothing(monkeypatch, tmp_path, capsys, error):
    spec = importlib.util.spec_from_file_location("build_corpus_r5", KIT_DIR / "10_build_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("KIT_BUILD_DIR", str(tmp_path / "build"))
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: _Body(error))
    assert module.main([]) == 1
    err = capsys.readouterr().err
    assert "ERROR: could not download the inventory CSV" in err and "python 10_build_corpus.py --csv" in err
    assert not (tmp_path / "build" / "corpus_manifest.json").exists()


# --- F6: every damaged record is kept and counted --------------------------------------------------------------------

@pytest.mark.parametrize("times", [2, 3])
def test_each_damaged_record_is_kept_and_counted(run_eval, tmp_path, capsys, times):
    questions = ["q-002", "q-003", "q-005"][:times]
    out_dir = None
    for number, question in enumerate(questions):
        Counting.faults = {("generate", question): [KeyboardInterrupt()]}
        arguments = [BILLS] if out_dir is None else [BILLS, "--resume", str(out_dir)]
        assert run_eval.main(arguments) == 130
        out_dir = out_dir_of(tmp_path)
        (out_dir / "last_question_calls.json").write_text('{"id": "' + question + '", "rows_bef', encoding="utf-8")
    Counting.faults = {}
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    names = ["last_question_calls.unreadable.json"] + [f"last_question_calls.unreadable-{n}.json" for n in range(2, times + 1)]
    assert sorted(path.name for path in out_dir.glob("last_question_calls.unreadable*.json")) == sorted(names)
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["usage"]["interrupted_without_a_record"] == times
    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert f"NOT COUNTED: the record of the calls of {times} interrupted question(s) could not be read ({', '.join(names)})" in text
    # each of them held one answered Retrieve call that is not in the usage
    assert printed_usage(out_dir)["retrieve_calls"] == served_usage()["retrieve_calls"] - times


# --- F7: copies of the state file ------------------------------------------------------------------------------------

COPIES = ["state.json", ".state copy.json", "state-backup.json", ".state (1).json", ".state.json", ".state.json.bak",
          "old.state.json", "state.json.bak", "kit_b state 2.json", ".state.json.tmp"]


def test_every_name_with_state_that_ends_json_is_ignored_by_pattern():
    patterns = [line.strip() for line in (KIT_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    assert "*state*.json" in patterns
    for name in COPIES:
        assert any(fnmatch.fnmatch(name, pattern) for pattern in patterns), name


def test_no_file_the_kit_ships_is_hidden_by_the_new_line():
    shipped = [path for path in KIT_DIR.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    assert [path.name for path in shipped if fnmatch.fnmatch(path.name, "*state*.json")] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_itself_ignores_every_copy(tmp_path):
    shutil.copy(KIT_DIR / ".gitignore", tmp_path / ".gitignore")
    for name in COPIES + ["kitlib_state.py", "notes.json"]:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", HOME=str(tmp_path))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=env)
    result = subprocess.run(["git", "-C", str(tmp_path), "status", "--porcelain", "--ignored", "--untracked-files=all"],
                            capture_output=True, text=True, check=True, env=env)
    ignored = {re.sub(r'^"|"$', "", line[3:]) for line in result.stdout.splitlines() if line.startswith("!! ")}
    assert set(COPIES) <= ignored, set(COPIES) - ignored
    assert "kitlib_state.py" not in ignored and "notes.json" not in ignored


# --- the documents ---------------------------------------------------------------------------------------------------

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")


def _section(number: int) -> str:
    return re.split(r"^## \d+\. .*$", README, flags=re.MULTILINE)[number]


def _item(number: int) -> str:
    return _section(2).split(f"\n{number}. **")[1].split(f"\n{number + 1}. **")[0]


def test_item_9_puts_the_round_5_news_first_and_says_the_round_4_counts_predate_it():
    text = _item(9)
    assert text.index("Round 5, bad news first.") < text.index("Round 4, bad news first.")
    for words in ("16 of 16 DECLINED replies", "9 of 9 CORRECT replies", "lost 7 of 16 ordinary refusals",
                  "0 of 16, 0 of 9 and 0 of 7 wrong, its 46 controls kept", "30 of 30", "25 of 25", "43 of 46",
                  "Without the question nothing changed.",
                  "These counts on the 203, 82 and 60 replies were measured before round 5",
                  "since round 5 only where the candidate is said to say it",
                  '"The information is not available in the documents."'):
        assert words in text, words
    assert 'It declines to say so." under DECLINED' not in text
    assert len(data.FIXER_R5_NOT_A_REFUSAL) == 30 and len(data.FIXER_R5_REFUSALS) == 25


def test_section_8_and_the_template_describe_the_judge_reader_as_it_is():
    assert "With the question known it reads two known replies made only of list words as credit" in _section(8)
    assert "reads three known replies" not in README
    template = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
    assert "that the reply's own reason does not contradict" not in template
    assert "It can be wrong in either direction" in template and "a shape they do not know is still counted" in template


def test_item_18_says_what_removing_a_damaged_row_does():
    assert "if you remove that line by hand, its question is run again and the calls it held leave the usage line" in _item(18)
    source = (KIT_DIR / "50_run_eval.py").read_text(encoding="utf-8")
    assert "the calls that row held are no longer in the" in source


def test_section_8_counts_the_round_5_tests():
    found = re.search(r"([\d,]+) of them are in `tests/test_review_r5\.py` and the fifth reader's two scenario files", _section(8))
    assert found
    files = ["tests/test_review_r5.py", "tests/test_attack_r5b.py", "tests/test_attack_r5b_2.py"]
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
                            cwd=KIT_DIR, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    collected = re.search(r"(\d+) tests? collected", result.stdout)
    assert collected and int(collected.group(1)) == int(found.group(1).replace(",", "")), result.stdout[-300:]
