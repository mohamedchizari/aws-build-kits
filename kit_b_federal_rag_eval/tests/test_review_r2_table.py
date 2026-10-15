"""Round 2 review, what the table and the lines around it say: tests written to fail on the code after round 1.

B3     --no-guardrail printed a filled "Guardrail on" column.
B4     the judge-family line said "different families" for a same-family judge given as an ARN,
       in upper case, or as a sibling model name.
M4     the owner was asked for three numbers no script printed.
MINOR  --limit N did not say "first N of 120"; the by-type table used "Exact" and "Judged" for
       refusals on the unanswerable rows; the block rows did not name the relevance filter;
       20_build_eval_set.py printed 6 candidates where the README said 5 rows.
New    the exact-match column now has an "unclear" row.
"""
from __future__ import annotations

import importlib.util
import json
import re

import pytest

import fakeaws
from conftest import KIT_DIR
from kitlib import cli, config, evalloop, scoring
from test_evalloop import ITEMS, LABEL_SETS, SCRIPT, FakeBackend

FINGERPRINT = "a" * 64
BILLS = "--i-understand-this-bills"
PLACE = {"account_id": fakeaws.ACCOUNT_A, "region": "us-east-1", "prefix": "kitdemo"}


@pytest.fixture
def run_eval(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("run_eval_script_r2", KIT_DIR / "50_run_eval.py")
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
    fakeaws.install(monkeypatch, fakeaws.World())
    config.save_state({**PLACE, "knowledge_base_id": "KB12345678", "kb_type": "managed", "guardrail_id": "gr1",
                       "guardrail_version": "1", "grounding_threshold": 0.7, "relevance_threshold": 0.7,
                       "corpus_fingerprint": FINGERPRINT})
    monkeypatch.setattr(module.api, "BedrockBackend", lambda *a, **k: FakeBackend())
    return module


def summary_md(tmp_path) -> str:
    runs = sorted((tmp_path / "results").iterdir())
    return (runs[-1] / "summary.md").read_text(encoding="utf-8")


def table_rows(text: str) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.startswith("|") and not line.startswith("|---")]


# --- B3 ------------------------------------------------------------------------------------------------------

def test_no_guardrail_prints_not_applied_in_every_guardrail_on_cell(run_eval, tmp_path):
    assert run_eval.main([BILLS, "--no-guardrail"]) == 0
    text = summary_md(tmp_path)
    assert "- Guardrail: NOT APPLIED (--no-guardrail)" in text
    main = [row for row in table_rows(text) if len(row) == 3 and row[0] != "Measure"]
    assert len(main) >= 18
    for row in main:
        assert row[2] == "not applied", row
    assert all("not applied" in row[1] for row in main if "blocks" in row[0])
    for row in table_rows(text):
        if len(row) > 3 and row[0] in {item["type"] for item in ITEMS}:
            assert row[-1] == "not applied", row                # the Blocked column
    assert not re.search(r"\| \d+/\d+ \([^|]*\) \|\s*$", "\n".join(
        line for line in text.splitlines() if line.startswith("| Answerable") or line.startswith("| Unanswerable")),
        flags=re.MULTILINE)
    assert "The guardrail was NOT APPLIED in this run" in text
    assert "The two columns are the same answers" not in text


def test_with_the_guardrail_the_on_column_is_filled_as_before(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    text = summary_md(tmp_path)
    assert "| Answerable: correct by exact match | 2/4 (50.0%, 95% CI 15 to 85) | 1/4 (25.0%, 95% CI 5 to 70) |" in text
    assert "The two columns are the same answers" in text and "NOT APPLIED" not in text


def test_summarise_records_whether_the_guardrail_was_applied():
    rows = evalloop.run(ITEMS, FakeBackend(), LABEL_SETS, use_guardrail=False)
    assert scoring.summarise(rows, 5, guardrail_applied=False)["guardrail_applied"] is False
    assert scoring.summarise(rows, 5)["guardrail_applied"] is True


# --- B4 ------------------------------------------------------------------------------------------------------

NOVA_LITE = "amazon.nova-lite-v1:0"


@pytest.mark.parametrize("judge", [
    "amazon.nova-pro-v1:0", "us.amazon.nova-pro-v1:0", "AMAZON.NOVA-PRO-V1:0", "Us.Amazon.Nova-Pro-v1:0",
    "arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.amazon.nova-pro-v1:0",
    "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
    "amazon.nova-premier-v1:0", "us.amazon.nova-2-lite-v1:0", "global.amazon.nova-2-lite-v1:0",
    "us-west-2.amazon.nova-pro-v1:0",
])
def test_a_judge_from_the_generators_family_is_called_same_family_however_its_id_is_written(judge):
    line = cli.judge_family_line(NOVA_LITE, judge)
    assert line.startswith("SAME FAMILY") and "different" not in line


@pytest.mark.parametrize("generator,judge", [
    ("meta.llama3-70b-instruct-v1:0", "us.meta.llama4-maverick-17b-instruct-v1:0"),
    ("mistral.mistral-large-2407-v1:0", "mistral.mixtral-8x7b-instruct-v0:1"),
    (NOVA_LITE, "amazon.titan-text-premier-v1:0"),
    ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
])
def test_two_models_of_one_provider_are_never_called_different_families(generator, judge):
    line = cli.judge_family_line(generator, judge)
    assert line.startswith("SAME ") and "different families" not in line


@pytest.mark.parametrize("generator,judge", [
    (NOVA_LITE, "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/abc123def456"),
    (NOVA_LITE, "arn:aws:bedrock:us-east-1:111122223333:provisioned-model/abcdef"),
    (NOVA_LITE, "my-imported-model"), (NOVA_LITE, "acme.wonder-v1:0"), (NOVA_LITE, ""),
    ("acme.wonder-v1:0", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
])
def test_an_id_that_cannot_be_read_gives_could_not_tell_never_different(generator, judge):
    line = cli.judge_family_line(generator, judge)
    assert line.startswith("COULD NOT TELL") and "different families" not in line and "SAME" not in line


def test_different_families_is_printed_only_for_two_known_and_different_providers():
    for judge in ("us.anthropic.claude-haiku-4-5-20251001-v1:0",
                  "arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
                  "US.ANTHROPIC.CLAUDE-HAIKU-4-5-20251001-V1:0"):
        line = cli.judge_family_line(NOVA_LITE, judge)
        assert line.startswith("different families") and "Anthropic Claude" in line and "Amazon Nova" in line
    assert cli.model_provider(NOVA_LITE) == "amazon" and cli.model_provider("acme.wonder-v1:0") is None
    assert len(cli.KNOWN_PROVIDERS) >= 5


# --- MINOR: --limit ------------------------------------------------------------------------------------------

def test_limit_says_first_n_of_all_in_the_summary_and_on_screen(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS, "--limit", "2"]) == 0
    text = summary_md(tmp_path)
    assert "- Evaluation set: first 2 of 6 questions (--limit 2), seed 7" in text
    assert "first 2 of 6 questions" in capsys.readouterr().out
    assert run_eval.main([BILLS]) == 0
    assert "- Evaluation set: all 6 questions, seed 7" in summary_md(tmp_path)


def test_the_limit_help_text_says_which_questions_come_first():
    source = (KIT_DIR / "50_run_eval.py").read_text(encoding="utf-8")
    assert "in the order of the file" in source and "agency questions" in source


# --- MINOR: the by-type tables -----------------------------------------------------------------------------

def test_answerable_and_unanswerable_types_get_separate_tables_with_their_own_headers(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    text = summary_md(tmp_path)
    answerable = ("| Answerable question type | n | Hit in top k | Exact correct, off | Exact unclear | "
                  "Judged correct, off | Exact correct, on | Judged correct, on | Blocked |")
    unanswerable = ("| Unanswerable question type | n | Refused with the fixed sentence, off | Judged DECLINED, off | "
                    "Refused or blocked, on | Judged DECLINED or blocked, on | Blocked |")
    assert answerable in text and unanswerable in text
    assert text.index(answerable) < text.index("| agency |") < text.index(unanswerable) < text.index(
        "| unanswerable_heldout |")
    assert "| Question type | n | Hit in top k | Exact, off |" not in text
    assert "| unanswerable_absent_field | 1 | 0/1" in text


# --- MINOR: the block rows name both filters ---------------------------------------------------------------

def test_the_block_rows_name_the_grounding_and_the_relevance_filter(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    text = summary_md(tmp_path)
    assert "| Guardrail blocks (grounding or relevance filter), total | not applied | 3 |" in text
    assert "Grounding guardrail blocks" not in text
    assert "either filter" in text and "grounding_score" in text and "relevance_score" in text
    template = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
    assert "| Guardrail blocks (grounding or relevance filter), total | not applied | |" in template
    assert "Grounding guardrail blocks" not in template


# --- New: the unclear row ------------------------------------------------------------------------------------

def test_the_table_has_a_row_for_answers_exact_match_could_not_read(run_eval, tmp_path, monkeypatch):
    script = dict(SCRIPT)
    script["q-001"] = dict(SCRIPT["q-001"], answer="It is probably the Department of Energy.")
    monkeypatch.setattr(run_eval.api, "BedrockBackend", lambda *a, **k: FakeBackend(script))
    assert run_eval.main([BILLS]) == 0
    text = summary_md(tmp_path)
    # q1 unclear, q2 correct, q3 another value, q4 refused: the four rows add up to the 4 answerable questions
    assert "| Answerable: correct by exact match | 1/4 " in text
    assert "| Answerable: unclear to exact match (counted as not correct) | 1/4 " in text
    assert "| Answerable: another value, read cleanly by exact match | 1/4 " in text
    assert "| Answerable: refused or blocked | 1/4 " in text
    runs = sorted((tmp_path / "results").iterdir())
    summary = json.loads((runs[-1] / "summary.json").read_text(encoding="utf-8"))
    off = summary["guardrail_off"]
    assert sum(off[key]["count"] for key in ("answerable_exact_correct", "answerable_exact_unclear",
                                             "answerable_exact_different_value", "answerable_refused")) == 4
    assert summary["by_type"]["agency"]["exact_unclear"] == 1
    header = (runs[-1] / "per_question.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "exact_unclear" in header and "exact_unread" in header
    first = json.loads((runs[-1] / "raw.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["exact_unclear"] is True and first["exact_unread"] == "probably"
    assert first["exact_note"] == "unclear_words_outside_the_filler_list"
    assert "credit only when" in text and "short fixed list" in text


def test_the_scoring_version_changed_so_an_older_run_cannot_be_resumed():
    # Changed in round 3 (the rehearsal on real model text), again in round 4 (the fourth review) and in round 5
    # (the judge reader changed again): the version did too. What matters here is that it is no longer the
    # version of an earlier round.
    assert scoring.SCORING_VERSION == "2026-10-08.r5"
    assert scoring.SCORING_VERSION not in ("2026-10-07", "2026-10-07.r1", "2026-10-07.r2", "2026-10-07.r3",
                                           "2026-10-07.r4")


# --- M4: the three numbers the owner is asked for are printed ---------------------------------------------------

@pytest.fixture
def world(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build")
    return fakeaws.install(monkeypatch, fakeaws.World())


def test_the_deploy_prints_the_minutes_to_ingestion_complete_and_records_when_the_knowledge_base_was_made(world):
    code, out = fakeaws.run_script("30_deploy_kb.py", BILLS)
    assert code == 0, out
    assert re.search(r"Minutes from the start of this script to ingestion COMPLETE: \d+\.\d \(this computer's clock\)",
                     out)
    saved = json.loads(config.state_path().read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", saved["knowledge_base_created_at"])


def test_a_redeploy_keeps_the_time_the_knowledge_base_was_first_made(world):
    assert fakeaws.run_script("30_deploy_kb.py", BILLS)[0] == 0
    state = json.loads(config.state_path().read_text(encoding="utf-8"))
    state["knowledge_base_created_at"] = "2026-10-01T08:00:00Z"
    config.save_state(state)
    assert fakeaws.run_script("30_deploy_kb.py", BILLS)[0] == 0
    assert json.loads(config.state_path().read_text(encoding="utf-8"))["knowledge_base_created_at"] == \
        "2026-10-01T08:00:00Z"


def test_the_teardown_prints_when_it_finished_and_how_long_the_knowledge_base_existed(world, monkeypatch):
    from kitlib import state as state_mod
    assert fakeaws.run_script("30_deploy_kb.py", BILLS)[0] == 0
    state = json.loads(config.state_path().read_text(encoding="utf-8"))
    state["knowledge_base_created_at"] = "2026-10-07T08:00:00Z"
    config.save_state(state)
    monkeypatch.setattr(state_mod, "now", lambda: "2026-10-07T11:30:00Z")
    code, out = fakeaws.run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert "Date and time 90_teardown.py finished (UTC, this computer's clock): 2026-10-07T11:30:00Z" in out
    assert ("Hours the knowledge base existed (its creation by 30_deploy_kb.py to its deletion confirmed here): "
            "3.50") in out


def test_the_teardown_does_not_invent_the_hours_when_the_creation_time_is_not_on_record(world):
    assert fakeaws.run_script("30_deploy_kb.py", BILLS)[0] == 0
    state = json.loads(config.state_path().read_text(encoding="utf-8"))
    state.pop("knowledge_base_created_at")
    config.save_state(state)
    code, out = fakeaws.run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert "Hours the knowledge base existed: not known" in out


def test_every_row_the_template_asks_for_from_a_script_is_printed_by_that_script():
    template = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
    deploy = (KIT_DIR / "30_deploy_kb.py").read_text(encoding="utf-8")
    teardown = (KIT_DIR / "90_teardown.py").read_text(encoding="utf-8")
    assert "| Minutes from the start of 30_deploy_kb.py to ingestion COMPLETE (printed by the script) | |" in template
    assert "Minutes from the start of this script to ingestion COMPLETE" in deploy
    assert "| Hours the knowledge base existed (printed by 90_teardown.py) | |" in template
    assert "Hours the knowledge base existed" in teardown
    assert "| Date and time 90_teardown.py finished (UTC, printed by the script) | |" in template
    assert "Date and time 90_teardown.py finished" in teardown


# --- MINOR: 6 candidates, 5 rows ---------------------------------------------------------------------------

def test_the_builder_says_how_many_different_rows_the_candidates_are(tmp_path):
    from conftest import rows_to_csv_bytes, synthetic_rows
    rows = synthetic_rows(300)
    twin = rows[10].fields.copy()
    twin["use_case_name"] = rows[10].fields["use_case_name"] + "s"
    from kitlib import corpus
    rows.append(corpus.Row(301, twin))
    csv_path = tmp_path / "in.csv"
    csv_path.write_bytes(rows_to_csv_bytes(rows))
    assert fakeaws.run_script("10_build_corpus.py", "--csv", str(csv_path), "--skip-sha-check",
                              "--sample-size", "0")[0] == 0
    code, out = fakeaws.run_script("20_build_eval_set.py", "--allow-shortfall")
    assert code == 0, out
    match = re.search(r"In all: (\d+) candidate\(s\) not used, which are (\d+) different CSV row\(s\)", out)
    assert match, out
    meta = json.loads((tmp_path / "build" / "eval" / "eval_set_meta.json").read_text(encoding="utf-8"))
    excluded = meta["near_duplicates"]["excluded_rows"]
    assert int(match.group(1)) == sum(len(v) for v in excluded.values())
    assert int(match.group(2)) == len({n for v in excluded.values() for n in v}) == \
        meta["near_duplicates"]["excluded_rows_distinct"]
