"""Round 1 review, findings in the evaluation run: tests written to fail on the code as reviewed.

MAJOR 1   the results never said that the service-managed re-ranker was on.
MAJOR 2   a rebuilt corpus could be evaluated against a knowledge base built from another one.
MAJOR 3   --resume mixed rows produced under different settings.
MAJOR 4   the same-family judge was not disclosed where the table is.
MINOR 1   a hit rate of 0/100 with no warning when no document id could be read.
MINOR 6   Retrieve was priced from the settings, not from what was deployed.
MINOR 10  the retrieved passage text was not saved.
MINOR 13  usage of failed attempts was dropped after a resume.
"""
from __future__ import annotations

import csv
import importlib.util
import json

import pytest

import fakeaws
from conftest import KIT_DIR
from kitlib import aws as api
from kitlib import config, scoring
from kitlib.evalloop import Passage
from test_evalloop import ITEMS, LABEL_SETS, SCRIPT, FakeBackend

FINGERPRINT = "f" * 64
BILLS = "--i-understand-this-bills"


class Backend(FakeBackend):
    """The scripted fake backend, with switches for the failure modes these tests need."""
    judge_fail_on: set = set()
    drop_document_ids = False
    created: list = []

    def __init__(self, *args, **kwargs):
        super().__init__()
        Backend.created.append((args, kwargs))

    def retrieve(self, question):
        passages = super().retrieve(question)
        if Backend.drop_document_ids:
            return [Passage(text=p.text, doc_id=None, score=p.score, uri=None) for p in passages]
        return [Passage(text=p.text, doc_id=p.doc_id, score=p.score,
                        uri=f"s3://kitdemo-fedrag-corpus-{fakeaws.ACCOUNT_A}-us-east-1/corpus/{p.doc_id}.txt")
                for p in passages]

    def judge(self, system, user):
        if self.current in Backend.judge_fail_on:
            self.log.append(("judge", self.current))
            raise RuntimeError("ModelErrorException: the model returned an error")
        return super().judge(system, user)


def write_build(tmp_path, eval_fingerprint=FINGERPRINT, manifest_fingerprint=FINGERPRINT):
    build = tmp_path / "build"
    (build / "eval").mkdir(parents=True, exist_ok=True)
    (build / "eval" / "eval_set.jsonl").write_text("".join(json.dumps(i) + "\n" for i in ITEMS), encoding="utf-8")
    (build / "eval" / "eval_set_meta.json").write_text(json.dumps(
        {"label_sets": LABEL_SETS, "seed": 7, "corpus_fingerprint": eval_fingerprint}), encoding="utf-8")
    (build / "corpus_manifest.json").write_text(json.dumps(
        {"mean_document_chars": 900, "documents": 400, "commit": "06c7ebeef5b3", "seed": 7,
         "corpus_fingerprint": manifest_fingerprint}), encoding="utf-8")


def write_state(**changes):
    saved = {"account_id": fakeaws.ACCOUNT_A, "region": "us-east-1", "prefix": "kitdemo",
             "knowledge_base_id": "KB12345678", "kb_type": "managed", "bucket": "kitdemo-fedrag-corpus-x",
             "corpus_fingerprint": FINGERPRINT, "guardrail_id": "gr1", "guardrail_version": "1",
             "grounding_threshold": 0.7, "relevance_threshold": 0.7}
    saved.update(changes)
    config.save_state({key: value for key, value in saved.items() if value is not None})


@pytest.fixture
def run_eval(monkeypatch, tmp_path):
    fakeaws.install(monkeypatch, fakeaws.World())
    spec = importlib.util.spec_from_file_location("run_eval_script_r1", KIT_DIR / "50_run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_build(tmp_path)
    write_state()
    Backend.judge_fail_on, Backend.drop_document_ids, Backend.created = set(), False, []
    monkeypatch.setattr(module.api, "BedrockBackend", Backend)
    return module


def run_dir(tmp_path):
    runs = sorted((tmp_path / "results").iterdir())
    assert len(runs) == 1
    return runs[0]


def summary_text(tmp_path) -> str:
    return (run_dir(tmp_path) / "summary.md").read_text(encoding="utf-8")


# --- MAJOR 1 and MAJOR 4: what the table is, said where the table is --------------------------------------

def test_the_summary_says_which_search_and_which_reranker_produced_the_hit_rate(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    text = summary_text(tmp_path)
    assert "- Retrieval: managed knowledge base: hybrid search" in text
    assert "re-ranking by the service-managed model" in text and "rerankingModelType=MANAGED" in text
    config_file = json.loads((run_dir(tmp_path) / "run_config.json").read_text(encoding="utf-8"))
    assert "rerankingModelType=MANAGED" in config_file["retrieval"]


def test_the_summary_says_when_no_reranker_was_configured(run_eval, tmp_path):
    write_state(kb_type="s3vectors")
    assert run_eval.main([BILLS]) == 0
    assert "no re-ranking model was configured" in summary_text(tmp_path)


def test_the_summary_discloses_a_judge_from_the_generators_family(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS]) == 0
    text = summary_text(tmp_path)
    assert "- Judge and generator: SAME FAMILY: the judge (amazon.nova-pro-v1:0) and the generator " \
           "(amazon.nova-lite-v1:0) are both Amazon Nova models." in text
    assert "SAME FAMILY" in capsys.readouterr().out


def test_a_judge_from_another_family_is_reported_as_such(run_eval, tmp_path, monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert run_eval.main([BILLS]) == 0
    text = summary_text(tmp_path)
    assert "- Judge and generator: different families: the judge (us.anthropic.claude-haiku-4-5-20251001-v1:0) " \
           "is from the Anthropic Claude family, the generator (amazon.nova-lite-v1:0) is from the Amazon Nova " \
           "family" in text
    assert "SAME FAMILY" not in text


# --- MAJOR 2: the corpus on disk, the evaluation set and the deployed corpus must be the same one ---------------

def test_a_corpus_rebuilt_after_the_deploy_is_refused(run_eval, tmp_path, capsys):
    write_build(tmp_path, eval_fingerprint="a" * 64, manifest_fingerprint="a" * 64)
    assert run_eval.main([BILLS]) == 1
    err = capsys.readouterr().err
    assert "not the corpus that was deployed" in err and "30_deploy_kb.py" in err
    assert Backend.created == [] and not (tmp_path / "results").exists()


def test_an_evaluation_set_built_from_another_corpus_is_refused(run_eval, tmp_path, capsys):
    write_build(tmp_path, eval_fingerprint="a" * 64)
    assert run_eval.main([BILLS]) == 1
    assert "20_build_eval_set.py" in capsys.readouterr().err
    assert Backend.created == []


def test_a_deploy_record_without_a_corpus_fingerprint_is_refused(run_eval, tmp_path, capsys):
    write_state(corpus_fingerprint=None)
    assert run_eval.main([BILLS]) == 1
    assert "30_deploy_kb.py" in capsys.readouterr().err and Backend.created == []


# --- MAJOR 3: resume only under the settings the run was started with ----------------------------------------

def test_a_run_writes_its_settings_down(run_eval, tmp_path):
    assert run_eval.main([BILLS, "--limit", "3"]) == 0
    saved = json.loads((run_dir(tmp_path) / "run_config.json").read_text(encoding="utf-8"))
    assert saved["limit"] == 3 and saved["top_k"] == 5 and saved["knowledge_base_id"] == "KB12345678"
    assert saved["gen_model_id"] == "amazon.nova-lite-v1:0" and saved["judge_model_id"] == "amazon.nova-pro-v1:0"
    assert saved["guardrail"] == {"applied": True, "id": "gr1", "version": "1",
                                  "grounding_threshold": 0.7, "relevance_threshold": 0.7}
    assert saved["corpus_fingerprint"] == FINGERPRINT and len(saved["eval_set_sha256"]) == 64
    assert len(saved["prompts_sha256"]) == 64 and saved["scoring_version"] == scoring.SCORING_VERSION


@pytest.mark.parametrize("label,argv,env,state_change", [
    ("judge model", ["--limit", "5"], {"JUDGE_MODEL_ID": "amazon.nova-micro-v1:0"}, {}),
    ("generation model", ["--limit", "5"], {"GEN_MODEL_ID": "amazon.nova-micro-v1:0"}, {}),
    ("top k", ["--limit", "5"], {"TOP_K": "20"}, {}),
    ("guardrail", ["--limit", "5", "--no-guardrail"], {}, {}),
    ("limit", [], {}, {}),
    ("guardrail version", ["--limit", "5"], {}, {"guardrail_version": "2"}),
    ("knowledge base", ["--limit", "5"], {}, {"knowledge_base_id": "KB99999999"}),
])
def test_resume_under_other_settings_is_refused(run_eval, tmp_path, monkeypatch, capsys, label, argv, env,
                                                state_change):
    assert run_eval.main([BILLS, "--limit", "5"]) == 0
    out_dir = run_dir(tmp_path)
    before = {p.name: p.read_bytes() for p in out_dir.iterdir()}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if state_change:
        write_state(**state_change)
    Backend.created = []
    capsys.readouterr()

    assert run_eval.main([BILLS, "--resume", str(out_dir), *argv]) == 1
    err = capsys.readouterr().err
    assert "Refusing to resume" in err and label in err
    assert Backend.created == []                                         # nothing was called
    assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == before  # and nothing was rewritten


def test_resume_under_the_same_settings_is_allowed(run_eval, tmp_path):
    Backend.judge_fail_on = {"q-003"}
    assert run_eval.main([BILLS]) == 1
    Backend.judge_fail_on = set()
    assert run_eval.main([BILLS, "--resume", str(run_dir(tmp_path))]) == 0
    assert "INCOMPLETE" not in summary_text(tmp_path)


def test_resume_of_a_folder_without_a_settings_file_is_refused(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS]) == 0
    (run_dir(tmp_path) / "run_config.json").unlink()
    assert run_eval.main([BILLS, "--resume", str(run_dir(tmp_path))]) == 1
    assert "run_config.json" in capsys.readouterr().err


# --- MINOR 13: usage of an attempt that failed half way is still usage ------------------------------------------

def test_usage_of_a_failed_attempt_is_kept_after_resume(run_eval, tmp_path):
    Backend.judge_fail_on = {"q-003"}          # Retrieve, Converse and ApplyGuardrail succeed, the judge fails
    assert run_eval.main([BILLS]) == 1
    first = json.loads((run_dir(tmp_path) / "summary.json").read_text(encoding="utf-8"))["usage"]
    assert first["retrieve_calls"] == 6 and first["gen_input_tokens"] == 6000

    Backend.judge_fail_on = set()
    assert run_eval.main([BILLS, "--resume", str(run_dir(tmp_path))]) == 0
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text(encoding="utf-8"))
    usage = summary["usage"]
    assert summary["questions_scored"] == 6 and summary["complete"] is True
    assert usage["retrieve_calls"] == 7 and usage["gen_input_tokens"] == 7000        # 6 questions, 7 attempts
    assert usage["guardrail_calls"] == 7 and usage["judge_input_tokens"] == 1800
    assert usage["earlier_failed_attempts_included"] == 1
    cost = summary["estimated_cost_from_measured_usage"]["parts_usd"]
    assert abs(cost["retrieve_calls"] - 0.007) < 1e-12
    assert "includes 1 earlier attempt(s) that failed" in summary_text(tmp_path)
    raw = [json.loads(line) for line in (run_dir(tmp_path) / "raw.jsonl").read_text().splitlines()]
    assert [r["id"] for r in raw].count("q-003") == 2 and len(raw) == 7             # every attempt is kept


# --- MINOR 6: Retrieve is priced for the knowledge base that was deployed ------------------------------------------

def test_retrieve_is_priced_from_the_deployed_type_not_from_the_settings(run_eval, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KB_TYPE", "s3vectors")          # the settings say one thing, the deploy record another
    assert run_eval.main([BILLS]) == 0
    out = capsys.readouterr().out
    assert "$1.00 per 1,000 calls on a Managed Knowledge Base" in out
    assert "NOTE: KB_TYPE is 's3vectors' but .state.json records a 'managed' knowledge base" in out
    cost = json.loads((run_dir(tmp_path) / "summary.json").read_text())["estimated_cost_from_measured_usage"]
    assert abs(cost["parts_usd"]["retrieve_calls"] - 0.006) < 1e-12
    assert "- Knowledge base type: managed" in summary_text(tmp_path)


# --- MINOR 1: no silent zero hit rate -------------------------------------------------------------------------------

def test_unreadable_document_ids_are_not_reported_as_a_hit_rate_of_zero(run_eval, tmp_path, capsys):
    Backend.drop_document_ids = True
    assert run_eval.main([BILLS]) == 0
    text = summary_text(tmp_path)
    assert "WARNING: no document id could be read from any of the 8 retrieved passages" in text
    assert "| Retrieval hit rate, source document in top 5 | NOT MEASURED" in text
    assert "0/4 (0.0%" not in text.split("| Answerable: correct by exact match")[0]
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text())
    assert summary["retrieval"]["hit_rate_measured"] is False
    assert summary["retrieval"]["passages_without_document_id"] == 8
    assert "WARNING: no document id could be read" in capsys.readouterr().out


def test_a_few_unreadable_document_ids_are_counted_and_warned_about():
    rows = [{"id": "q", "type": "agency", "answerable": True, "exact": True, "judged_correct": True,
             "declined": False, "blocked": False, "judge_verdict": "CORRECT", "hit": True, "hit_rank": 1,
             "retrieved_doc_ids": ["uc-0001", None, None], "error": None,
             "exact_on": True, "judged_correct_on": True, "declined_on": False}]
    summary = scoring.summarise(rows, top_k=5)
    assert summary["retrieval"]["hit_rate_measured"] is True
    assert scoring.retrieval_warnings(summary) == [
        "WARNING: 2 of 3 retrieved passages carried no readable document id. The hit rates below are "
        "therefore a lower bound, not a measurement."]
    assert scoring.retrieval_warnings(scoring.summarise(
        [dict(rows[0], retrieved_doc_ids=["uc-0001"])], top_k=5)) == []


def test_the_parser_finds_the_document_id_in_other_location_shapes():
    passages = api.parse_retrieve_response({"retrievalResults": [
        {"content": {"text": "a"}, "location": {"type": "CUSTOM", "customDocumentLocation": {"id": "corpus/uc-0042.txt"}}},
        {"content": {"text": "b"}, "metadata": {"x-amz-bedrock-kb-source-uri": "s3://bucket/corpus/uc-0007.txt"}},
        {"content": {"text": "c"}, "location": {"type": "WEB", "webLocation": {"url": "https://example.com/x"}}},
        {"content": {"text": "d"}, "metadata": {"doc_id": "not-ours"}},
    ]})
    assert [p.doc_id for p in passages] == ["uc-0042", "uc-0007", None, None]


# --- MINOR 10: a blocked answer can be audited later ---------------------------------------------------------------

def test_the_retrieved_passage_text_is_saved_in_raw_jsonl(run_eval, tmp_path):
    assert run_eval.main([BILLS]) == 0
    raw = [json.loads(line) for line in (run_dir(tmp_path) / "raw.jsonl").read_text().splitlines()]
    blocked = [row for row in raw if row["blocked"]]
    assert blocked
    for row in raw:
        docs = SCRIPT[row["id"]]["docs"]
        assert [p["doc_id"] for p in row["retrieved_passages"]] == docs
        assert [p["text"] for p in row["retrieved_passages"]] == [f"text of {d}" for d in docs]
        assert all(p["score"] == 0.5 for p in row["retrieved_passages"])
    text = (run_dir(tmp_path) / "raw.jsonl").read_text()
    assert fakeaws.ACCOUNT_A not in text and "********3333" in text       # the bucket name carries the account id

    with (run_dir(tmp_path) / "per_question.csv").open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert "retrieved_doc_ids" in header and "retrieved_passages" not in header


# --- BLOCKER 1 and 2, end to end through the loop and the table ----------------------------------------------------

def test_a_perfect_system_that_repeats_the_field_name_scores_full_marks_and_a_hedging_judge_scores_none():
    """The reviewer's end-to-end cases 1 and 3, on the six scripted questions."""
    from kitlib import evalloop

    perfect = {
        "q-001": dict(SCRIPT["q-001"], answer='The Department of Energy (DOE) reported the AI use case named "Use case 1".'),
        "q-002": dict(SCRIPT["q-002"], answer="The stage of development recorded is Pilot.", action="NONE"),
        "q-003": dict(SCRIPT["q-003"], docs=["uc-0003"], answer='The high-impact determination recorded is "Not High-impact".',
                      judge='{"verdict": "CORRECT", "reason": "same value"}', action="NONE"),
        "q-004": dict(SCRIPT["q-004"], answer="The AI use case was reported by the Department of Justice.",
                      judge='{"verdict": "CORRECT"}'),
        "q-005": SCRIPT["q-005"],
        "q-006": dict(SCRIPT["q-006"], answer=scoring.DECLINE_SENTENCE, judge='{"verdict": "DECLINED"}', action="NONE"),
    }
    summary = scoring.summarise(evalloop.run(ITEMS, FakeBackend(perfect), LABEL_SETS), top_k=5)
    off = summary["guardrail_off"]
    assert off["answerable_exact_correct"]["count"] == 4 and off["answerable_judged_correct"]["count"] == 4
    assert off["unanswerable_refused"]["count"] == 2 and summary["exact_vs_judge_agreement"]["count"] == 4

    # The same system, but every answer is wrong and the judge says so in words the old parser read as CORRECT.
    replies = ["The candidate answer is not correct.", "NOT CORRECT", '{"verdict": "NOT CORRECT", "reason": "x"}',
               '{"verdict": "PARTIALLY CORRECT", "reason": "x"}', "Verdict: not correct", "This is not a correct answer."]
    wrong = {key: dict(step, answer="It was reported by the Bureau of Made Up Things.", judge=reply, action="NONE")
             for (key, step), reply in zip(perfect.items(), replies)}
    summary = scoring.summarise(evalloop.run(ITEMS, FakeBackend(wrong), LABEL_SETS), top_k=5)
    assert summary["guardrail_off"]["answerable_judged_correct"]["count"] == 0       # was 4 of 4 before the fix
    assert summary["guardrail_off"]["answerable_exact_correct"]["count"] == 0
    assert summary["judge_unparseable"] == 6
    assert summary["guardrail_off"]["unanswerable_answered_anyway"]["count"] == 0     # unclear, not "answered"
    assert summary["guardrail_off"]["unanswerable_judge_unclear"]["count"] == 2


def test_two_runs_started_in_the_same_second_get_two_folders(run_eval, tmp_path):
    """Not asked for by the review: the second run used to end in a traceback (FileExistsError)."""
    assert run_eval.main([BILLS]) == 0
    assert run_eval.main([BILLS]) == 0
    assert run_eval.main([BILLS]) == 0
    runs = sorted(p.name for p in (tmp_path / "results").iterdir())
    assert len(runs) == 3 and len(set(runs)) == 3
