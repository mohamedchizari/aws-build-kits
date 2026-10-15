"""50_run_eval.py end to end against a fake backend: files written, resume, cost from measured usage."""
from __future__ import annotations

import csv
import importlib.util
import json

import pytest

import fakeaws
from conftest import KIT_DIR
from kitlib import config, evalloop
from test_evalloop import ITEMS, LABEL_SETS, FakeBackend

FINGERPRINT = "0" * 64
PLACE = {"account_id": fakeaws.ACCOUNT_A, "region": "us-east-1", "prefix": "kitdemo"}


@pytest.fixture
def run_eval(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("run_eval_script", KIT_DIR / "50_run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    build = tmp_path / "build"
    (build / "eval").mkdir(parents=True)
    (build / "eval" / "eval_set.jsonl").write_text("".join(json.dumps(i) + "\n" for i in ITEMS), encoding="utf-8")
    (build / "eval" / "eval_set_meta.json").write_text(json.dumps(
        {"label_sets": LABEL_SETS, "seed": 7, "corpus_fingerprint": FINGERPRINT}), encoding="utf-8")
    (build / "corpus_manifest.json").write_text(json.dumps(
        {"mean_document_chars": 900, "documents": 400, "commit": "06c7ebeef5b3", "seed": 7,
         "corpus_fingerprint": FINGERPRINT}), encoding="utf-8")
    # The run asks STS which account it is in and compares it with the state file, so the
    # state names a place and the fake account answers the identity call.
    fakeaws.install(monkeypatch, fakeaws.World())
    config.save_state({**PLACE, "knowledge_base_id": "KB12345678", "kb_type": "managed", "guardrail_id": "gr1",
                       "guardrail_version": "1", "grounding_threshold": 0.7, "relevance_threshold": 0.7,
                       "corpus_fingerprint": FINGERPRINT})
    backends = []

    def fake_backend(*args, **kwargs):
        backend = FakeBackend(fail_on=fake_backend.fail_on)
        backends.append(backend)
        return backend
    fake_backend.fail_on = set()
    monkeypatch.setattr(module.api, "BedrockBackend", fake_backend)
    module.fake_backend, module.backends = fake_backend, backends
    return module


def only_run_dir(tmp_path):
    runs = list((tmp_path / "results").iterdir())
    assert len(runs) == 1
    return runs[0]


def test_refuses_without_the_flag_and_writes_nothing(run_eval, tmp_path):
    with pytest.raises(SystemExit) as stop:
        run_eval.main([])
    assert stop.value.code == 2 and not (tmp_path / "results").exists() and run_eval.backends == []


def test_full_run_writes_the_five_files_with_consistent_numbers(run_eval, tmp_path, capsys):
    assert run_eval.main(["--i-understand-this-bills"]) == 0
    out_dir = only_run_dir(tmp_path)
    # the five result files, and since round 4 the record of the calls of the question last in flight
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "last_question_calls.json", "per_question.csv", "raw.jsonl", "run_config.json", "summary.json", "summary.md"]

    with (out_dir / "per_question.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["id"] for r in rows] == [i["id"] for i in ITEMS]
    assert list(rows[0]) == evalloop.CSV_COLUMNS
    assert rows[1]["blocked"] == "True" and rows[1]["exact"] == "True" and rows[1]["exact_on"] == "False"

    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["complete"] is True and summary["answerable_n"] == 4 and summary["unanswerable_n"] == 2
    assert summary["guardrail_blocks"]["total"] == 3
    cost = summary["estimated_cost_from_measured_usage"]
    expected = (6000 * 0.06 + 60 * 0.24) / 1e6 + (1800 * 0.80 + 90 * 3.20) / 1e6 + 12 * 0.10 / 1000 + 6 * 1.00 / 1000
    assert cost["complete"] is True and abs(cost["total_usd"] - expected) < 1e-12

    text = (out_dir / "summary.md").read_text()
    assert "| Measure | Guardrail off | Guardrail on |" in text
    assert "- Guardrail: gr1 version 1, grounding threshold 0.7, relevance threshold 0.7" in text
    assert "Cost of this run at list price, computed from that usage: $0.0093" in text
    assert "ESTIMATED TOTAL for this run" in capsys.readouterr().out


def test_limit_runs_only_the_first_questions(run_eval, tmp_path):
    assert run_eval.main(["--i-understand-this-bills", "--limit", "2"]) == 0
    raw = (only_run_dir(tmp_path) / "raw.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in raw] == ["q-001", "q-002"]


def test_failed_question_makes_the_run_incomplete_and_resume_finishes_it(run_eval, tmp_path, capsys):
    run_eval.fake_backend.fail_on = {"q-003"}
    assert run_eval.main(["--i-understand-this-bills"]) == 1
    out_dir = only_run_dir(tmp_path)
    assert json.loads((out_dir / "summary.json").read_text())["complete"] is False
    assert (out_dir / "summary.md").read_text().startswith("**INCOMPLETE RUN")

    run_eval.fake_backend.fail_on = set()
    assert run_eval.main(["--i-understand-this-bills", "--resume", str(out_dir)]) == 0
    assert [entry for entry in run_eval.backends[-1].log if entry[0] == "retrieve"] == [("retrieve", "q-003")]
    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["complete"] is True and summary["questions_scored"] == 6
    # raw.jsonl is append-only since the round 1 review: the failed attempt at q-003 stays in it.
    raw_ids = [json.loads(line)["id"] for line in (out_dir / "raw.jsonl").read_text().splitlines()]
    assert sorted(set(raw_ids)) == [i["id"] for i in ITEMS] and len(raw_ids) == 7 and raw_ids.count("q-003") == 2
    assert "resuming, 5 already done" in capsys.readouterr().out


def test_no_guardrail_flag_is_stated_in_the_summary(run_eval, tmp_path):
    assert run_eval.main(["--i-understand-this-bills", "--no-guardrail"]) == 0
    text = (only_run_dir(tmp_path) / "summary.md").read_text()
    assert "- Guardrail: NOT APPLIED (--no-guardrail)" in text
    # Round 2 review, B3: no number is printed in the "guardrail on" column when no guardrail was applied.
    assert "| Guardrail blocks (grounding or relevance filter), total | not applied | not applied |" in text


def test_missing_guardrail_in_state_is_an_error_before_any_call(run_eval, tmp_path):
    config.save_state({**PLACE, "knowledge_base_id": "KB12345678", "kb_type": "managed",
                       "corpus_fingerprint": FINGERPRINT})
    assert run_eval.main(["--i-understand-this-bills"]) == 1
    assert run_eval.backends == [] and not (tmp_path / "results").exists()
