"""Round 5 reader B: scenario cases. Each test asserts what a careful person expects. A FAILING test is a
defect reproduced; a passing control is behaviour that must keep working. Runs under the kit's own conftest
(sockets refused, AWS variables removed). Nothing here calls AWS: fakeaws.World and the scripted backend only.
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import urllib.error

import fakeaws
from conftest import KIT_DIR
from fakeaws import BILLS, run_script
from kitlib import config
from kitlib import state as state_mod
from test_review_r4_usage import (Counting, out_dir_of, printed_usage, rows_of, run_eval,  # noqa: F401 (fixture)
                                  served_usage)


# ---- F3: --resume after the user removes a damaged line, as the refusal message tells him to -----------------------

def test_S1_removing_a_damaged_line_does_not_turn_a_finished_question_into_an_interrupted_one(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS]) == 0                         # six questions, all finished
    out_dir = out_dir_of(tmp_path)
    raw = out_dir / "raw.jsonl"
    lines = raw.read_bytes().split(b"\n")
    assert len([line for line in lines if line]) == 6
    lines[1] = b'{"id": "q-002", "answer": "half'               # one row damaged after it was written
    raw.write_bytes(b"\n".join(lines))
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 1      # refuses and says: repair or remove that line
    err = capsys.readouterr().err
    assert "Repair or remove that line by hand" in err
    del lines[1]                                                # the person removes it, as told
    raw.write_bytes(b"\n".join(lines))
    code = run_eval.main([BILLS, "--resume", str(out_dir)])
    out = capsys.readouterr().out
    rows = rows_of(out_dir)
    # what a careful person expects: q-002 runs again, nothing else changes, the run is complete
    assert "in flight" not in out, out
    assert not [row["id"] for row in rows if row.get("interrupted")], [row["id"] for row in rows if row.get("interrupted")]
    assert code == 0
    assert printed_usage(out_dir)["retrieve_calls"] == 6        # five kept rows plus q-002 again; q-006 once


def test_S1b_control_without_any_removal_a_second_resume_adds_nothing(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS]) == 0
    out_dir = out_dir_of(tmp_path)
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert "in flight" not in capsys.readouterr().out
    assert printed_usage(out_dir) == served_usage()


def test_S4_control_ctrl_c_in_flight_then_resume_counts_every_answered_call(run_eval, tmp_path, capsys):
    Counting.faults = {("guardrail", "q-004"): [KeyboardInterrupt()]}
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert "q-004 was in flight" in capsys.readouterr().out
    assert printed_usage(out_dir) == served_usage()


# ---- F4: the corpus download, a connection closed in the middle of the body ----------------------------------------

def _build_corpus_module(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("build_corpus_attack", KIT_DIR / "10_build_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("KIT_BUILD_DIR", str(tmp_path / "build"))
    return module


class _Response:
    def __init__(self, error):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        raise self.error


def test_S2_a_body_cut_short_is_one_message_not_a_traceback(monkeypatch, tmp_path, capsys):
    module = _build_corpus_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module.urllib.request, "urlopen",
                        lambda *a, **k: _Response(http.client.IncompleteRead(b"x" * 1000, 5_000_000)))
    try:
        code = module.main([])
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"traceback instead of the ERROR message: {type(exc).__name__}") from None
    captured = capsys.readouterr()
    assert code == 1 and "ERROR: could not download the inventory CSV" in captured.err


def test_S3_control_connection_refused_is_one_message(monkeypatch, tmp_path, capsys):
    module = _build_corpus_module(monkeypatch, tmp_path)

    def refused(*a, **k):
        raise urllib.error.URLError("[Errno 111] Connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", refused)
    assert module.main([]) == 1
    assert "ERROR: could not download the inventory CSV" in capsys.readouterr().err
    assert not (tmp_path / "build" / "corpus_manifest.json").exists()


def test_S3b_control_reset_during_the_body_is_one_message(monkeypatch, tmp_path, capsys):
    module = _build_corpus_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: _Response(ConnectionResetError(104, "reset")))
    assert module.main([]) == 1
    assert "ERROR: could not download the inventory CSV" in capsys.readouterr().err


# ---- controls: teardown and the clean check with a knowledge base recorded as "not known yet" ----------------------

def test_S5_control_kb_recorded_pending_then_teardown_and_clean_check(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build")
    world = fakeaws.install(monkeypatch, fakeaws.World())
    original = fakeaws.FakeClient._bedrock_agent__create_knowledge_base

    def create_then_die(self, **params):
        original(self, **params)
        raise RuntimeError("the answer was lost on the way")

    monkeypatch.setattr(fakeaws.FakeClient, "_bedrock_agent__create_knowledge_base", create_then_die)
    assert run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")[0] == 1
    saved = json.loads(config.state_path().read_text(encoding="utf-8"))
    assert saved["knowledge_base_id"] == state_mod.PENDING and world.left()["knowledge_bases"]
    code, out = run_script("99_verify_clean.py")
    assert code == 1 and "RESULT: NOT CLEAN" in out              # the knowledge base is there: never clean
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and world.nothing_left(), out
    assert "RESULT: every recorded resource was deleted or confirmed absent in" in out
    code, out = run_script("99_verify_clean.py")
    assert code == 0 and "RESULT: CLEAN in" in out and "This is the place .state.json names" in out


def test_S6_control_clean_check_in_another_region_is_incomplete_while_a_deploy_is_recorded(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build")
    world = fakeaws.install(monkeypatch, fakeaws.World())
    assert run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")[0] == 0
    code, out = run_script("99_verify_clean.py", env={"AWS_REGION": "us-west-2"})
    assert code != 0 and "RESULT: CLEAN" not in out, out
    code, out = run_script("90_teardown.py", "--yes", env={"AWS_REGION": "us-west-2"})
    assert code == 1 and "STOP:" in out and world.left()["knowledge_bases"]
