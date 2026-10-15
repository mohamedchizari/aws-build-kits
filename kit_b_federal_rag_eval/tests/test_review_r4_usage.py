"""Round 4 (fourth review, reader B), MAJOR 2: the usage and cost line left out calls that were answered.

The reader's runs T02, T04, T08b and T14: a run is stopped with Ctrl-C while a question is in flight, or the
process is killed while the row of a question is being written, and the run is finished with the --resume
command the script prints. summary.md then said "120 Retrieve calls ... $0.2403" where the stand-in had
answered 121 Retrieve calls (and, for a row that was cut off, one more generation, guardrail and judge call).
Nothing said so. README section 2 item 5 promised that the figure "includes the calls that succeeded in the
attempts that failed".

The rule since round 4: after every call that is answered, the counts of the question in flight are written to
last_question_calls.json in the results folder (numbers and ids only). --resume turns that record into an
attempt of its own when the row of that question never reached raw.jsonl, so the answered calls are counted,
and the usage line says what it still cannot count.
"""
from __future__ import annotations

import importlib.util
import json
import re

import pytest

import fakeaws
from conftest import KIT_DIR
from kitlib import evalloop, jsonl, scoring
from test_evalloop import ITEMS, LABEL_SETS, FakeBackend
from test_review_r1_eval import BILLS, write_build, write_state

RECORD = "last_question_calls.json"


class Counting(FakeBackend):
    """The scripted backend. Every call that RETURNS is appended to `served`: that is what AWS would bill."""
    served: list = []
    faults: dict = {}                    # (operation, question id) -> list of exceptions, first call first

    def __init__(self, *args, **kwargs):
        super().__init__()

    def _fault(self, operation: str) -> None:
        queue = Counting.faults.get((operation, self.current))
        if queue:
            raise queue.pop(0)

    def _number(self) -> int:
        return int(self.current.split("-")[1])

    def retrieve(self, question):
        self.current = "q-%03d" % int(question.split()[1])
        self._fault("retrieve")
        passages = super().retrieve(question)
        Counting.served.append(("retrieve", self.current, {}))
        return passages

    def generate(self, system, user):
        self._fault("generate")
        usage = {"input_tokens": 1000 + self._number(), "output_tokens": 10 + self._number()}
        Counting.served.append(("generate", self.current, usage))
        return dict(super().generate(system, user), **usage)

    def apply_guardrail(self, sources, question, answer):
        self._fault("guardrail")
        usage = {"units": 2 + self._number()}
        Counting.served.append(("guardrail", self.current, usage))
        return dict(super().apply_guardrail(sources, question, answer), **usage)

    def judge(self, system, user):
        self._fault("judge")
        usage = {"input_tokens": 300 + self._number(), "output_tokens": 15}
        Counting.served.append(("judge", self.current, usage))
        return dict(super().judge(system, user), **usage)


def served_usage() -> dict:
    out = {"retrieve_calls": 0, "gen_input_tokens": 0, "gen_output_tokens": 0, "judge_input_tokens": 0,
           "judge_output_tokens": 0, "guardrail_text_units": 0, "guardrail_calls": 0}
    for operation, _, usage in Counting.served:
        if operation == "retrieve":
            out["retrieve_calls"] += 1
        elif operation == "generate":
            out["gen_input_tokens"] += usage["input_tokens"]
            out["gen_output_tokens"] += usage["output_tokens"]
        elif operation == "judge":
            out["judge_input_tokens"] += usage["input_tokens"]
            out["judge_output_tokens"] += usage["output_tokens"]
        else:
            out["guardrail_text_units"] += usage["units"]
            out["guardrail_calls"] += 1
    return out


USAGE_LINE = re.compile(r"Measured usage: ([\d,]+) Retrieve calls; generation ([\d,]+) input and ([\d,]+) output tokens; "
                        r"judge ([\d,]+) input and ([\d,]+) output tokens; guardrail ([\d,]+) text units in ([\d,]+) calls")


def printed_usage(out_dir) -> dict:
    found = USAGE_LINE.search((out_dir / "summary.md").read_text(encoding="utf-8"))
    numbers = [int(group.replace(",", "")) for group in found.groups()]
    return dict(zip(("retrieve_calls", "gen_input_tokens", "gen_output_tokens", "judge_input_tokens",
                     "judge_output_tokens", "guardrail_text_units", "guardrail_calls"), numbers))


@pytest.fixture
def run_eval(monkeypatch, tmp_path):
    fakeaws.install(monkeypatch, fakeaws.World())
    spec = importlib.util.spec_from_file_location("run_eval_script_r4_usage", KIT_DIR / "50_run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_build(tmp_path)
    write_state()
    Counting.served, Counting.faults = [], {}
    monkeypatch.setattr(module.api, "BedrockBackend", Counting)
    return module


def out_dir_of(tmp_path):
    runs = sorted(path for path in (tmp_path / "results").iterdir() if path.is_dir())
    assert len(runs) == 1
    return runs[0]


def cut_last_row(raw, keep) -> None:
    """Cut raw.jsonl inside its last row, as a process killed during the write leaves it."""
    body, last = raw.read_bytes()[:-1].rsplit(b"\n", 1)
    raw.write_bytes(body + b"\n" + keep(last))


def rows_of(out_dir) -> list[dict]:
    return jsonl.loads_lines((out_dir / "raw.jsonl").read_bytes(), "raw.jsonl")


# --- the reader's runs -------------------------------------------------------------------------------------------------

def test_ctrl_c_during_a_call_then_resume_counts_the_calls_that_were_answered(run_eval, tmp_path, capsys):
    """T02: Ctrl-C during the generation call of q-003. Its Retrieve call had been answered."""
    Counting.faults = {("generate", "q-003"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    assert not (out_dir / "summary.md").exists() and len(rows_of(out_dir)) == 2
    record = json.loads((out_dir / RECORD).read_text(encoding="utf-8"))
    assert record["id"] == "q-003" and record["rows_before"] == 2 and record["retrieved_doc_ids"] == ["uc-0008"]
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert "q-003 was in flight when the run was stopped: 1 call had been answered (Retrieve)" in capsys.readouterr().out
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 7
    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "This includes 1 earlier attempt(s) that failed or were interrupted part of the way" in text
    rows = rows_of(out_dir)
    attempts = [row for row in rows if row["id"] == "q-003"]
    assert len(rows) == 7 and len(attempts) == 2
    assert attempts[0]["interrupted"] is True and attempts[0]["error"].startswith("Interrupted: ")
    assert attempts[0]["gen_input_tokens"] == 0 and attempts[1]["error"] is None
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["usage"]["interrupted_attempts_included"] == 1 and summary["complete"] is True
    assert summary["questions_total"] == summary["questions_scored"] == 6


@pytest.mark.parametrize("keep", [lambda row: row[:len(row) // 2], lambda row: row[:1], lambda row: row[:-1]],
                         ids=["mid_row", "one_byte", "all_but_the_last_byte"])
def test_a_row_cut_off_while_it_was_written_is_run_again_and_its_calls_are_counted(run_eval, tmp_path, capsys, keep):
    """T04a to T04c: the process is killed while the row of q-003 is written. All four calls had been answered."""
    Counting.faults = {("retrieve", "q-004"): [KeyboardInterrupt()]}          # stops before any call of q-004
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    cut_last_row(out_dir / "raw.jsonl", keep)
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "q-003 was in flight when the run was stopped: 4 calls had been answered" in out
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 7
    assert (out_dir / "raw_cut_off_row.txt").exists()
    cost = float(re.search(r"computed from that usage: \$([\d.]+)", (out_dir / "summary.md").read_text()).group(1).rstrip("."))
    usage = served_usage()
    own = (usage["gen_input_tokens"] * 0.06 / 1e6 + usage["gen_output_tokens"] * 0.24 / 1e6
           + usage["judge_input_tokens"] * 0.80 / 1e6 + usage["judge_output_tokens"] * 3.20 / 1e6
           + usage["guardrail_text_units"] * 0.10 / 1000 + usage["retrieve_calls"] * 1.00 / 1000)
    assert abs(cost - own) < 0.00005


def test_a_whole_last_row_is_not_counted_twice(run_eval, tmp_path, capsys):
    """T04d and T03: the last row is whole (with or without its line feed). The record of q-003 is older than it."""
    Counting.faults = {("retrieve", "q-004"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    raw = out_dir / "raw.jsonl"
    raw.write_bytes(raw.read_bytes()[:-1])                                    # the line feed is gone, the row is whole
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert "in flight" not in capsys.readouterr().out
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 6
    assert len(rows_of(out_dir)) == 6


def test_a_finished_run_whose_last_row_is_cut_afterwards(run_eval, tmp_path):
    """T08b: every question finished, then the last row is cut short, then --resume."""
    assert run_eval.main([BILLS]) == 0
    out_dir = out_dir_of(tmp_path)
    assert printed_usage(out_dir) == served_usage()
    cut_last_row(out_dir / "raw.jsonl", lambda row: row[:-7])
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 7
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0             # and a resume of the finished run adds nothing
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 7


def test_stopped_twice_each_time_with_the_last_row_cut_and_one_failed_question(run_eval, tmp_path):
    """T14."""
    Counting.faults = {("retrieve", "q-003"): [KeyboardInterrupt()], ("retrieve", "q-006"): [KeyboardInterrupt()],
                       ("judge", "q-001"): [RuntimeError("ModelErrorException")]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    cut_last_row(out_dir / "raw.jsonl", lambda row: row[:100])
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 130             # runs q-001 again, q-002 .. q-005, stops at q-006
    cut_last_row(out_dir / "raw.jsonl", lambda row: row[:-1])
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 9
    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "This includes 3 earlier attempt(s) that failed or were interrupted part of the way" in text
    assert (out_dir / "raw_cut_off_row.txt").read_bytes().count(b"\n") == 2


def test_an_undisturbed_run_and_a_run_with_failed_questions_count_as_before(run_eval, tmp_path):
    Counting.faults = {("judge", "q-002"): [RuntimeError("ThrottlingException")]}
    assert run_eval.main([BILLS]) == 1
    out_dir = out_dir_of(tmp_path)
    assert printed_usage(out_dir) == served_usage()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert printed_usage(out_dir) == served_usage() and served_usage()["retrieve_calls"] == 7
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["usage"]["earlier_failed_attempts_included"] == 1
    assert summary["usage"]["interrupted_attempts_included"] == 0


# --- the record itself ---------------------------------------------------------------------------------------------------

def test_the_record_holds_numbers_and_ids_and_no_text(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    record = json.loads((out_dir_of(tmp_path) / RECORD).read_text(encoding="utf-8"))
    # "question_rows_before" since round 5 (F3): how many rows of its own question raw.jsonl held when it started
    assert sorted(record) == sorted(["id", "rows_before", "question_rows_before", "calls_answered", "retrieved_doc_ids",
                                     "guardrail_action", "guardrail_units", "gen_input_tokens", "gen_output_tokens",
                                     "judge_input_tokens", "judge_output_tokens"])
    assert record["id"] == "q-006" and record["rows_before"] == 5 and record["question_rows_before"] == 0
    assert record["calls_answered"] == ["Retrieve", "generation", "guardrail", "judge"]
    assert not list(out_dir_of(tmp_path).glob("*.tmp"))


def test_the_loop_reports_after_every_call_that_was_answered():
    seen = []
    names = []
    row = evalloop.evaluate_item(ITEMS[0], FakeBackend(), LABEL_SETS,
                                 on_call=lambda partial, calls: (seen.append(dict(partial)), names.append(calls)))
    assert len(seen) == 4 and row["error"] is None
    assert names == [["Retrieve"], ["Retrieve", "generation"], ["Retrieve", "generation", "guardrail"],
                     ["Retrieve", "generation", "guardrail", "judge"]]
    assert [partial["retrieved_doc_ids"] is not None for partial in seen] == [True] * 4
    assert [partial["gen_input_tokens"] for partial in seen] == [0, 1000, 1000, 1000]
    assert [partial["guardrail_action"] for partial in seen] == [None, None, "NONE", "NONE"]
    assert [partial["judge_input_tokens"] > 0 for partial in seen] == [False, False, False, True]
    seen.clear()
    evalloop.evaluate_item(ITEMS[0], FakeBackend(), LABEL_SETS, use_guardrail=False,
                           on_call=lambda partial, calls: seen.append(calls))
    assert seen[-1] == ["Retrieve", "generation", "judge"]


def test_a_record_that_cannot_be_read_does_not_stop_the_resume_and_the_summary_says_so(run_eval, tmp_path, capsys):
    Counting.faults = {("generate", "q-003"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    (out_dir / RECORD).write_text('{"id": "q-003", "rows_bef', encoding="utf-8")
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert "could not be read" in capsys.readouterr().out
    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "NOT COUNTED: the record of the calls of 1 interrupted question(s) could not be read" in text
    assert "up to 4 answered calls each" in text
    assert printed_usage(out_dir)["retrieve_calls"] == 6 and served_usage()["retrieve_calls"] == 7


def test_a_record_that_cannot_be_written_does_not_fail_the_question(run_eval, tmp_path, capsys, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("No space left on device")
    monkeypatch.setattr(run_eval, "write_calls_record", refuse)
    assert run_eval.main([BILLS]) == 0
    out = capsys.readouterr().out
    assert out.count("could not write last_question_calls.json") == 1
    assert printed_usage(out_dir_of(tmp_path)) == served_usage()


def test_the_usage_line_says_what_it_does_not_count(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    text = (out_dir_of(tmp_path) / "summary.md").read_text(encoding="utf-8")
    assert ("Not counted here: a call that failed or was cut off before its answer arrived (by an error, by Ctrl-C "
            "or by a kill), and a call the SDK sent a second time is counted once; whether AWS bills those is not "
            "known to this kit.") in text
    assert "This includes" not in text


def test_summarise_counts_an_interrupted_attempt_only_in_the_usage():
    rows = evalloop.run(ITEMS, FakeBackend(), LABEL_SETS)
    earlier = dict(evalloop.blank_row(ITEMS[2]), retrieved_doc_ids=["uc-0003"], gen_input_tokens=7, interrupted=True,
                   error="Interrupted: the run was stopped before this question finished")
    plain = scoring.summarise(rows, 5)
    with_one = scoring.summarise(rows, 5, [earlier])
    assert with_one["usage"]["retrieve_calls"] == plain["usage"]["retrieve_calls"] + 1
    assert with_one["usage"]["gen_input_tokens"] == plain["usage"]["gen_input_tokens"] + 7
    assert (with_one["usage"]["earlier_failed_attempts_included"], with_one["usage"]["interrupted_attempts_included"]) == (1, 1)
    for key in ("guardrail_off", "guardrail_on", "retrieval", "guardrail_blocks", "by_type", "questions_scored"):
        assert with_one[key] == plain[key]
