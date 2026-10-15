"""Round 4 (fourth review, reader B), the minor findings in the evaluation run: tests written to fail on the code
as reviewed.

MINOR 3   --no-guardrail printed an estimate that still charged for the guardrail (28% too high).
MINOR 7   raw.jsonl kept only the first 500 characters of a judge reply, so judge_note could name a word
          that is not in the kept text.
MINOR 8   --resume went on after the label sets in build/eval/eval_set_meta.json were changed (rows scored under
          two label sets in one table), and a run_config.json cut short ended --resume in a traceback.
MINOR 10  the stop reason of a call was dropped, so an answer or a judge reply cut at the token limit was not marked.
"""
from __future__ import annotations

import importlib.util
import json
import math
import re

import pytest

import fakeaws
from conftest import KIT_DIR
from kitlib import evalloop, pricing, scoring
from kitlib.evalloop import Passage
from test_evalloop import ITEMS, LABEL_SETS, FakeBackend
from test_review_r1_eval import BILLS, write_build, write_state


@pytest.fixture
def run_eval(monkeypatch, tmp_path):
    fakeaws.install(monkeypatch, fakeaws.World())
    spec = importlib.util.spec_from_file_location("run_eval_script_r4_eval", KIT_DIR / "50_run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_build(tmp_path)
    write_state()
    Stopping.stop_at = None
    monkeypatch.setattr(module.api, "BedrockBackend", Stopping)
    return module


class Stopping(FakeBackend):
    stop_at: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__()

    def retrieve(self, question):
        if "q-%03d" % int(question.split()[1]) == Stopping.stop_at:
            raise KeyboardInterrupt()
        return super().retrieve(question)


def out_dir_of(tmp_path):
    runs = sorted(path for path in (tmp_path / "results").iterdir() if path.is_dir())
    assert len(runs) == 1
    return runs[0]


# --- MINOR 3 --------------------------------------------------------------------------------------------------------

def test_the_estimate_leaves_the_guardrail_out_when_it_is_not_applied():
    with_it = pricing.estimate_eval_run(120, 5, 922, "amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0", "managed")
    without = pricing.estimate_eval_run(120, 5, 922, "amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0", "managed",
                                        use_guardrail=False)
    assert with_it["guardrail_text_units"] == 720 and math.isclose(with_it["parts_usd"]["guardrail_grounding"], 0.072)
    assert without["guardrail_text_units"] == 0 and without["parts_usd"]["guardrail_grounding"] == 0.0
    assert math.isclose(with_it["total_usd"] - without["total_usd"], 0.072) and without["complete"] is True


def test_no_guardrail_prints_an_estimate_without_the_guardrail(run_eval, capsys):
    with pytest.raises(SystemExit):
        run_eval.main([])                                          # no billing flag: prints the estimate and stops
    with_it = capsys.readouterr().out
    with pytest.raises(SystemExit):
        run_eval.main(["--no-guardrail"])
    without = capsys.readouterr().out

    def total(text: str) -> float:
        return float(re.search(r"ESTIMATED TOTAL for this run: \$([\d.]+)", text).group(1).rstrip("."))
    grounding = float(re.search(r"Estimate: [\d,]+ units = \$([\d.]+)", with_it).group(1).rstrip("."))
    assert grounding > 0 and math.isclose(total(with_it) - total(without), grounding, abs_tol=0.00011)
    assert "Contextual grounding check: NOT APPLIED (--no-guardrail), no ApplyGuardrail call, $0.0000." in without
    assert "units = $" not in without


# --- MINOR 7 --------------------------------------------------------------------------------------------------------

def test_the_whole_judge_reply_is_kept():
    reply = ('{"verdict": "CORRECT", "reason": "' + "The candidate states the stage. " * 16
             + 'It is not the reference."}')

    class Long(FakeBackend):
        def judge(self, system, user):
            return {"text": reply, "input_tokens": 1, "output_tokens": 1}

    row = evalloop.evaluate_item(ITEMS[1], Long(), LABEL_SETS)
    assert len(reply) > 500 and row["judge_raw"] == reply
    assert row["judge_verdict"] == scoring.UNPARSEABLE and "not" in row["judge_note"]
    assert "not the reference" in row["judge_raw"]                 # the word the note names is in the kept text


# --- MINOR 8 --------------------------------------------------------------------------------------------------------

def test_resume_refuses_when_the_label_sets_were_changed(run_eval, tmp_path, capsys):
    Stopping.stop_at = "q-004"
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    saved = json.loads((out_dir / "run_config.json").read_text(encoding="utf-8"))
    assert len(saved["eval_set_meta_sha256"]) == 64
    before = (out_dir / "raw.jsonl").read_bytes()
    meta_path = tmp_path / "build" / "eval" / "eval_set_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for entry in meta["label_sets"]["stage"]:
        if entry["label"] == "Retired":
            entry["label"] = "Decommissioned"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    Stopping.stop_at = None
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 1
    err = capsys.readouterr().err
    assert "Refusing to resume" in err and "label sets and build record (build/eval/eval_set_meta.json)" in err
    assert (out_dir / "raw.jsonl").read_bytes() == before and not (out_dir / "summary.md").exists()


def test_a_run_config_cut_short_stops_resume_with_a_message(run_eval, tmp_path, capsys):
    Stopping.stop_at = "q-004"
    assert run_eval.main([BILLS]) == 130
    out_dir = out_dir_of(tmp_path)
    config_path = out_dir / "run_config.json"
    saved = config_path.read_bytes()
    config_path.write_bytes(saved[:40])
    before = (out_dir / "raw.jsonl").read_bytes()
    Stopping.stop_at = None
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 1           # was: JSONDecodeError traceback
    err = capsys.readouterr().err
    assert "Refusing to resume" in err and "run_config.json" in err and "cannot be read" in err
    assert "Nothing was sent to Bedrock" in err and (out_dir / "raw.jsonl").read_bytes() == before
    config_path.write_bytes(saved)
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0


# --- MINOR 10 -------------------------------------------------------------------------------------------------------

class Cut(FakeBackend):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def generate(self, system, user):
        return dict(super().generate(system, user), stop_reason="max_tokens" if self.current == "q-002" else "end_turn")

    def judge(self, system, user):
        return dict(super().judge(system, user), stop_reason="max_tokens" if self.current in ("q-001", "q-005") else "end_turn")


def test_the_row_keeps_the_stop_reason_of_both_calls():
    rows = {row["id"]: row for row in evalloop.run(ITEMS, Cut(), LABEL_SETS)}
    assert (rows["q-002"]["gen_stop_reason"], rows["q-002"]["judge_stop_reason"]) == ("max_tokens", "end_turn")
    assert rows["q-001"]["judge_stop_reason"] == "max_tokens"
    plain = evalloop.evaluate_item(ITEMS[0], FakeBackend(), LABEL_SETS)
    assert plain["gen_stop_reason"] is None and plain["judge_stop_reason"] is None      # a backend that gives none
    assert "gen_stop_reason" in evalloop.CSV_COLUMNS and "judge_stop_reason" in evalloop.CSV_COLUMNS


def test_the_summary_says_how_many_texts_were_cut_at_the_token_limit(run_eval, tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval.api, "BedrockBackend", Cut)
    assert run_eval.main([BILLS]) == 0
    out_dir = out_dir_of(tmp_path)
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert (summary["answers_cut_at_token_limit"], summary["judge_replies_cut_at_token_limit"]) == (1, 2)
    text = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert ("**WARNING: 1 answer(s) and 2 judge reply(ies) ended at the token limit (stop reason max_tokens), so their "
            "text is cut off.") in text


def test_no_such_line_when_nothing_was_cut(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    assert "token limit" not in (out_dir_of(tmp_path) / "summary.md").read_text(encoding="utf-8")


def test_the_real_backend_passes_the_stop_reason_on():
    from kitlib import aws as api
    parsed = api.parse_converse_response({"output": {"message": {"content": [{"text": "Deploy"}]}},
                                          "stopReason": "max_tokens", "usage": {"inputTokens": 5, "outputTokens": 200}})
    assert parsed["stop_reason"] == "max_tokens"
    assert Passage(text="x").doc_id is None
