"""Round 5 reader B, second batch of scenario cases (same rules as test_attack_r5b.py)."""
from __future__ import annotations

import fnmatch
import json

from conftest import KIT_DIR
from fakeaws import BILLS
from test_review_r4_usage import Counting, out_dir_of, run_eval  # noqa: F401 (fixture)

RECORD = "last_question_calls.json"


def test_S7_two_unreadable_records_are_reported_as_two(run_eval, tmp_path):
    Counting.faults = {("generate", "q-003"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    (out_dir / RECORD).write_text('{"id": "q-003", "rows_bef', encoding="utf-8")       # damaged
    Counting.faults = {("generate", "q-005"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 130
    (out_dir / RECORD).write_text('{"id": "q-005", "rows_bef', encoding="utf-8")       # damaged again
    Counting.faults = {}
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    # two questions' answered calls could not be counted: the usage line should say two
    assert summary["usage"]["interrupted_without_a_record"] == 2, summary["usage"]["interrupted_without_a_record"]
    assert "the calls of 2 interrupted question(s) could not be read" in text


def test_S8_gitignore_covers_ordinary_copies_of_the_state_file():
    patterns = (KIT_DIR / ".gitignore").read_text(encoding="utf-8").split()
    for name in ("state.json", ".state copy.json", "state-backup.json"):
        assert any(fnmatch.fnmatch(name, pattern) for pattern in patterns), name


def test_S8b_control_gitignore_covers_the_named_copies():
    patterns = (KIT_DIR / ".gitignore").read_text(encoding="utf-8").split()
    for name in (".state.json", ".state.json.bak", "old.state.json", "state.json.bak"):
        assert any(fnmatch.fnmatch(name, pattern) for pattern in patterns), name
