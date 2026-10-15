"""Corpus builder: CSV rows -> text documents and metadata sidecars."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import FIXTURE_CSV, KIT_DIR, rows_to_csv_bytes, synthetic_rows
from kitlib import config, corpus


def test_fixture_parses_to_five_rows_with_stable_ids(fixture_rows):
    assert len(fixture_rows) == 5
    assert [r.row_number for r in fixture_rows] == [1, 2, 3, 4, 5]
    assert [r.doc_id for r in fixture_rows] == ["uc-0001", "uc-0002", "uc-0003", "uc-0004", "uc-0005"]
    assert fixture_rows[0].get("use_case_name") == "Relocatable Multi-Sensor System"


def test_parse_rejects_csv_without_expected_columns():
    with pytest.raises(ValueError, match="missing expected columns"):
        corpus.parse_csv("\ufeffa,b\n1,2\n".encode("utf-8"))


def test_document_puts_checkable_facts_first_and_copies_them_exactly(fixture_rows):
    row = fixture_rows[0]
    text = corpus.render_document(row, config.OMB_COMMIT)
    lines = text.splitlines()
    assert lines[1] == "Document ID: uc-0001"
    assert lines[2] == "Use case name: Relocatable Multi-Sensor System"
    assert lines[3] == "Agency: Department of Homeland Security (DHS)"
    assert lines[5] == "Stage of development: Pre-deployment"
    assert lines[6] == "High-impact determination: Presumed High-Impact, but Not High-impact"
    assert lines[-1].endswith("commit 06c7ebeef5b3, CSV row 1")


def test_document_marks_missing_fields_and_never_contains_an_email(fixture_rows):
    sparse = corpus.render_document(fixture_rows[3], config.OMB_COMMIT)  # the row with few fields
    assert "Topic area: Not reported" in sparse
    assert "Problem to be solved: Not reported" in sparse
    for row in fixture_rows:
        assert "@" not in corpus.render_document(row, config.OMB_COMMIT)


def test_free_text_is_cut_and_marked():
    row = corpus.Row(7, {"use_case_name": "A name", "agency_name": "An agency", "agency": "AA",
                         "problem_solved": "x" * 1000, "benefits": "y" * 10, "system_outputs": ""})
    text = corpus.render_document(row, "abc")
    problem_line = [line for line in text.splitlines() if line.startswith("Problem to be solved:")][0]
    assert problem_line == "Problem to be solved: " + "x" * 400 + " [truncated]"
    assert "Expected benefits: yyyyyyyyyy\n" in text
    assert len(text) < 1500


def test_whitespace_inside_cells_is_collapsed():
    row = corpus.Row(1, {"use_case_name": "Line one\r\nline  two", "agency_name": "X", "agency": "X"})
    assert row.get("use_case_name") == "Line one line two"


def test_sidecar_typed_format_matches_the_documented_shape(fixture_rows):
    body = json.loads(corpus.render_sidecar(fixture_rows[0], "typed"))
    attrs = body["metadataAttributes"]
    assert attrs["agency"] == {"value": {"type": "STRING", "stringValue": "DHS"}}
    assert attrs["development_stage"]["value"]["stringValue"] == "Pre-deployment"
    assert set(attrs) == {"doc_id", "agency", "agency_name", "development_stage", "is_high_impact",
                          "topic_area", "classification"}


def test_sidecar_simple_format(fixture_rows):
    body = json.loads(corpus.render_sidecar(fixture_rows[2], "simple"))
    assert body == {"metadataAttributes": {
        "doc_id": "uc-0003", "agency": "FTC", "agency_name": "Federal Trade Commission",
        "development_stage": "Deployed", "is_high_impact": "Not High-impact",
        "topic_area": "Law Enforcement", "classification": "Classical ML"}}
    with pytest.raises(ValueError):
        corpus.render_sidecar(fixture_rows[2], "yaml")


def test_sidecars_respect_the_size_limits(fixture_rows):
    for row in fixture_rows:
        for fmt in ("typed", "simple"):
            text = corpus.render_sidecar(row, fmt)
            assert len(text.encode("utf-8")) < corpus.SIDECAR_MAX_BYTES
        attrs = corpus.metadata_attributes(row)
        assert len(attrs) <= corpus.S3_VECTORS_METADATA_MAX_KEYS
        assert sum(len(k) + len(v.encode("utf-8")) for k, v in attrs.items()) < corpus.S3_VECTORS_METADATA_MAX_BYTES


def test_limit_check_raises_when_metadata_is_too_big():
    with pytest.raises(ValueError, match="1 KB"):
        corpus.check_sidecar_limits({"k": "v" * 2000}, "{}")
    with pytest.raises(ValueError, match="35 metadata keys"):
        corpus.check_sidecar_limits({f"k{i}": "v" for i in range(36)}, "{}")
    with pytest.raises(ValueError, match="10 KB"):
        corpus.check_sidecar_limits({"k": "v"}, "x" * 20000)


def test_sampling_is_deterministic_and_seeded():
    rows = synthetic_rows(120)
    first = [r.row_number for r in corpus.select_rows(rows, 30, seed=1)]
    again = [r.row_number for r in corpus.select_rows(rows, 30, seed=1)]
    other = [r.row_number for r in corpus.select_rows(rows, 30, seed=2)]
    assert first == again
    assert first != other
    assert len(first) == 30 and first == sorted(first) and len(set(first)) == 30


def test_sample_size_zero_means_all_eligible_rows_and_blank_names_are_dropped():
    rows = synthetic_rows(20)
    rows.append(corpus.Row(21, {"use_case_name": "  ", "agency_name": "Agency", "agency": "A"}))
    chosen = corpus.select_rows(rows, 0, seed=5)
    assert len(chosen) == 20
    assert len(corpus.select_rows(rows, 999, seed=5)) == 20


def test_build_corpus_writes_one_document_and_one_sidecar_per_row(fixture_rows):
    files, manifest = corpus.build_corpus(fixture_rows, 0, 1, config.OMB_COMMIT)
    assert sorted(files) == sorted(
        [f"uc-000{i}.txt" for i in range(1, 6)] + [f"uc-000{i}.txt.metadata.json" for i in range(1, 6)])
    assert manifest["documents"] == 5 and manifest["csv_rows"] == 5 and manifest["eligible_rows"] == 5
    assert manifest["total_document_chars"] == sum(len(files[f"uc-000{i}.txt"]) for i in range(1, 6))
    assert [d["doc_id"] for d in manifest["docs"]] == [f"uc-000{i}" for i in range(1, 6)]


def test_doc_id_from_uri():
    assert corpus.doc_id_from_uri("s3://bucket/corpus/uc-0042.txt") == "uc-0042"
    assert corpus.doc_id_from_uri("s3://bucket/corpus/uc-0042.txt.metadata.json") is None
    assert corpus.doc_id_from_uri("s3://bucket/other.pdf") is None
    assert corpus.doc_id_from_uri("") is None


def test_pinned_source_constants_are_consistent():
    assert len(config.OMB_COMMIT) == 40 and len(config.OMB_CSV_SHA256) == 64
    assert config.OMB_COMMIT in config.OMB_CSV_URL
    assert config.OMB_CSV_URL.startswith("https://raw.githubusercontent.com/ombegov/")


def _run(script: str, *args: str, env_extra: dict | None = None):
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(KIT_DIR / script), *args], capture_output=True, text=True,
                          cwd=KIT_DIR, env=env, timeout=120)


def test_script_10_refuses_a_csv_with_the_wrong_hash_and_writes_nothing(tmp_path):
    result = _run("10_build_corpus.py", "--csv", str(FIXTURE_CSV))
    assert result.returncode == 1
    assert "does not match the pinned" in result.stderr
    assert not (tmp_path / "build").exists()


def test_scripts_10_and_20_end_to_end_on_a_local_csv(tmp_path):
    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_bytes(rows_to_csv_bytes(synthetic_rows(300)))
    built = _run("10_build_corpus.py", "--csv", str(csv_path), "--skip-sha-check", "--sample-size", "200")
    assert built.returncode == 0, built.stderr
    corpus_dir = tmp_path / "build" / "corpus"
    assert len(list(corpus_dir.glob("uc-*.txt"))) == 200
    assert len(list(corpus_dir.glob("uc-*.txt.metadata.json"))) == 200
    manifest = json.loads((tmp_path / "build" / "corpus_manifest.json").read_text())
    assert manifest["documents"] == 200 and manifest["csv_sha256_matches_pin"] is False

    args = ["--n-agency", "12", "--n-stage", "8", "--n-high-impact", "6",
            "--n-unanswerable-heldout", "4", "--n-unanswerable-absent-field", "3"]
    evaluated = _run("20_build_eval_set.py", *args)
    assert evaluated.returncode == 0, evaluated.stderr
    lines = (tmp_path / "build" / "eval" / "eval_set.jsonl").read_text().splitlines()
    assert len(lines) == 33
    meta = json.loads((tmp_path / "build" / "eval" / "eval_set_meta.json").read_text())
    assert meta["answerable"] == 26 and meta["unanswerable"] == 7 and meta["shortfalls"] == {}

    # A second sample size removes the stale documents of the first run.
    rebuilt = _run("10_build_corpus.py", "--csv", str(csv_path), "--skip-sha-check", "--sample-size", "50")
    assert rebuilt.returncode == 0
    assert len(list(corpus_dir.glob("uc-*.txt"))) == 50


def test_script_20_fails_without_a_corpus(tmp_path):
    result = _run("20_build_eval_set.py")
    assert result.returncode == 1 and "Run 10_build_corpus.py first" in result.stderr
