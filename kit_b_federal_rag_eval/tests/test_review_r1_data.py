"""Round 1 review, findings in the corpus and the evaluation set: tests written to fail on the code as reviewed.

MINOR 9   one free-text cell of the CSV holds an e-mail address that a non-default sample put in a document.
MINOR 14  near-duplicate use cases: a correct answer without a retrieval hit, and a held-out
          question whose "invented" agency could be the true one.
MAJOR 2   (the builder's half) the corpus fingerprint that the deploy and the evaluation compare.
"""
from __future__ import annotations

import json
import re

import pytest

from conftest import rows_to_csv_bytes, synthetic_rows
from kitlib import config, corpus, evalset
from test_corpus import _run

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w.])(?:\+?1[\s.\-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.\-])\d{3}[\s.\-]\d{4}(?!\w)")
AT = "@"            # addresses are built at run time so that no file of the kit contains one
ADDRESSES = ["program.inbox" + AT + "agency.example.gov", "First.Last" + AT + "example.org",
             "help_desk+ai" + AT + "sub.example.com"]
PHONES = ["(202) 555-0123", "202-555-0145", "202.555.0167", "202 555 0189", "+1 202 555 0111", "1-800-555-0199"]
FREE_TEXT_FIELDS = ("problem_solved", "benefits", "system_outputs", "agency_bureau", "topic_area",
                    "classification", "use_case_name")


def rows_with_contact_details(n: int = 120) -> list[corpus.Row]:
    rows = synthetic_rows(n)
    for position, row in enumerate(rows):
        field = FREE_TEXT_FIELDS[position % len(FREE_TEXT_FIELDS)]
        detail = (ADDRESSES + PHONES)[position % (len(ADDRESSES) + len(PHONES))]
        row.fields[field] = f"{row.fields.get(field, '')} Write to {detail} for details."
        if position % 5 == 0:                          # some rows carry one right at the start of a cell
            row.fields["benefits"] = f"{PHONES[position % len(PHONES)]} is the hotline; {ADDRESSES[0]}"
    return rows


# --- MINOR 9 ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sample_size,seed", [(0, 1), (1, 1), (7, 2), (40, 3), (119, 4), (120, 5), (500, 6)])
@pytest.mark.parametrize("metadata_format", ["typed", "simple"])
def test_no_address_or_phone_number_reaches_any_document_under_any_sample(sample_size, seed, metadata_format):
    rows = rows_with_contact_details()
    files, manifest = corpus.build_corpus(rows, sample_size, seed, config.OMB_COMMIT, metadata_format)
    assert manifest["documents"] == (120 if sample_size in (0, 120, 500) else sample_size)
    for name, text in files.items():
        assert not EMAIL.search(text), f"e-mail address in {name}"
        assert not PHONE.search(text), f"phone-shaped string in {name}"
        assert AT not in text or "@" not in re.sub(r"\[[^\]]*\]", "", text), name
    joined = "\n".join(files.values())
    if sample_size == 0:
        assert corpus.EMAIL_REMOVED in joined and corpus.PHONE_REMOVED in joined


def test_scrub_replaces_addresses_and_phone_shaped_strings_and_nothing_else():
    for address in ADDRESSES:
        assert corpus.scrub(f"mail {address} now") == f"mail {corpus.EMAIL_REMOVED} now"
    for phone in PHONES:
        assert corpus.scrub(f"call {phone} now") == f"call {corpus.PHONE_REMOVED} now"
    for harmless in ("Landsat product at 30 m (LGCEP30)", "NARA@WORK Kendra Search", "fiscal years 2021-2022-2023",
                     "[2024 INV#WO0000000108776]", "95% accuracy on 10,000 records", "version 3.11.4",
                     "CSV row 1396", "ISO date 2026-10-07", "top 100 of 2500", "S2666546824000971"):
        assert corpus.scrub(harmless) == harmless
        assert not corpus.has_contact_details(harmless)
    assert corpus.has_contact_details("x " + ADDRESSES[0]) and corpus.has_contact_details(PHONES[0])


def test_every_cell_read_is_scrubbed_so_documents_sidecars_and_questions_agree():
    row = corpus.Row(7, {"use_case_name": "Hotline 202-555-0145 triage assistant", "agency_name": "An agency",
                         "agency": "AA", "agency_bureau": "Office of " + ADDRESSES[1],
                         "problem_solved": "Mail goes to " + ADDRESSES[0] + "."})
    assert row.get("use_case_name") == f"Hotline {corpus.PHONE_REMOVED} triage assistant"
    document = corpus.render_document(row, "abc")
    assert f"Use case name: Hotline {corpus.PHONE_REMOVED} triage assistant" in document
    assert f"Problem to be solved: Mail goes to {corpus.EMAIL_REMOVED}." in document
    assert not corpus.has_contact_details(document)
    assert not corpus.has_contact_details(corpus.render_sidecar(row))


def test_the_builder_refuses_to_write_a_document_that_still_holds_contact_details(monkeypatch):
    monkeypatch.setattr(corpus, "scrub", lambda text: text)          # as if a new field bypassed the scrub
    with pytest.raises(ValueError, match="e-mail address or a phone-shaped string"):
        corpus.build_corpus(rows_with_contact_details(), 0, 1, config.OMB_COMMIT)


def test_the_readme_says_which_real_rows_ship_with_the_kit():
    from conftest import KIT_DIR
    readme = (KIT_DIR / "README.md").read_text(encoding="utf-8")
    assert "does not redistribute the data" not in readme
    assert "tests/fixtures/inventory_5rows.csv" in readme
    for row_number in ("8", "108", "1687", "2079", "2647"):
        assert re.search(rf"\b{row_number}\b", readme.split("tests/fixtures/inventory_5rows.csv")[1][:400])


# --- the corpus fingerprint ------------------------------------------------------------------------------------

def test_the_manifest_and_the_eval_set_carry_the_fingerprint_of_the_files_on_disk(tmp_path):
    from kitlib import resources
    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_bytes(rows_to_csv_bytes(synthetic_rows(300)))
    assert _run("10_build_corpus.py", "--csv", str(csv_path), "--skip-sha-check", "--sample-size", "200").returncode == 0
    manifest = json.loads((tmp_path / "build" / "corpus_manifest.json").read_text())
    on_disk = resources.corpus_fingerprint(resources.corpus_files(tmp_path / "build" / "corpus"))
    assert manifest["corpus_fingerprint"] == on_disk and len(on_disk) == 64

    args = ["--n-agency", "12", "--n-stage", "8", "--n-high-impact", "6",
            "--n-unanswerable-heldout", "4", "--n-unanswerable-absent-field", "3"]
    assert _run("20_build_eval_set.py", *args).returncode == 0
    meta = json.loads((tmp_path / "build" / "eval" / "eval_set_meta.json").read_text())
    assert meta["corpus_fingerprint"] == on_disk

    # Another sample is another fingerprint, and the old evaluation set no longer matches the corpus.
    assert _run("10_build_corpus.py", "--csv", str(csv_path), "--skip-sha-check", "--sample-size", "50").returncode == 0
    rebuilt = json.loads((tmp_path / "build" / "corpus_manifest.json").read_text())
    assert rebuilt["corpus_fingerprint"] != on_disk
    assert meta["corpus_fingerprint"] != rebuilt["corpus_fingerprint"]


def test_the_fingerprint_depends_on_names_and_contents_only():
    files = {"uc-0002.txt": "b\n", "uc-0001.txt": "a\n"}
    assert corpus.fingerprint(files) == corpus.fingerprint(dict(reversed(list(files.items()))))
    assert corpus.fingerprint(files) == corpus.fingerprint({k: v.encode("utf-8") for k, v in files.items()})
    assert corpus.fingerprint(files) != corpus.fingerprint({**files, "uc-0001.txt": "a \n"})
    assert corpus.fingerprint(files) != corpus.fingerprint({"uc-0003.txt": "a\n", "uc-0002.txt": "b\n"})


# --- MINOR 14: near-duplicates ------------------------------------------------------------------------------------

SMALL = {"agency": 12, "stage": 8, "high_impact": 6, "unanswerable_heldout": 4, "unanswerable_absent_field": 3}
TWIN_A = "Forecasting and predictive analytics workbench in R"
TWIN_B = "Forecasting and predictive analytics workbench in Matlab"


def twin_rows():
    """300 rows; rows 1 and 2 are a near-duplicate pair in the corpus with every asked field equal."""
    rows = synthetic_rows(300)
    for number, name in ((1, TWIN_A), (2, TWIN_B)):
        fields = rows[number - 1].fields
        fields.update({"use_case_name": name, "agency": "AAA", "agency_name": "Agency for Alpha Affairs",
                       "development_stage": "Pilot", "is_high_impact": "High-impact"})
    return rows


def test_name_similarity_is_the_measure_the_review_used():
    assert evalset.name_similarity(TWIN_A, TWIN_B) >= evalset.NEAR_DUPLICATE_NAME_RATIO
    assert evalset.name_similarity("Generative AI - System Testing", "Generative AI - Text Generation") >= 0.75
    assert evalset.name_similarity("Public Comment Analysis", "Grid load forecaster") < 0.5
    assert evalset.name_similarity("Same Name", "same name") == 1.0


@pytest.mark.parametrize("seed", [11, 12, 13, 14, 15])
def test_a_near_duplicate_with_the_same_value_is_never_used_for_an_answerable_question(seed):
    rows = twin_rows()
    counts = dict(SMALL, agency=300, stage=300, high_impact=300)     # ask for more than fits: every candidate is looked at
    items, meta = evalset.build_eval_set(rows, set(range(1, 201)), seed, counts)
    answerable_names = {i["use_case_name"] for i in items if i["answerable"]}
    assert TWIN_A not in answerable_names and TWIN_B not in answerable_names
    excluded = meta["near_duplicates"]["excluded_rows"]
    for kind in ("agency", "stage", "high_impact"):
        assert {1, 2} <= set(excluded[kind]), kind

    # Without the twin they are ordinary rows and do get used.
    plain = synthetic_rows(300)
    for number in (1, 2):
        plain[number - 1].fields.update({"development_stage": "Pilot", "is_high_impact": "High-impact"})
    plain_items, plain_meta = evalset.build_eval_set(plain, set(range(1, 201)), seed, counts)
    assert {1, 2} <= {i["source_row"] for i in plain_items if i["answerable"]}
    assert not any({1, 2} & set(v) for v in plain_meta["near_duplicates"]["excluded_rows"].values())


def test_a_near_duplicate_with_another_value_is_kept_and_flagged():
    rows = twin_rows()
    rows[1].fields.update({"development_stage": "Deployed", "is_high_impact": "Not High-impact",
                           "agency": "BBB", "agency_name": "Bureau of Beta Business"})
    counts = dict(SMALL, agency=300, stage=300, high_impact=300)
    items, meta = evalset.build_eval_set(rows, set(range(1, 201)), 11, counts)
    flagged = {i["source_row"]: i["near_duplicate_doc_ids"] for i in items if i["answerable"] and i["source_row"] in (1, 2)}
    assert flagged == {1: ["uc-0002"], 2: ["uc-0001"]}
    assert meta["near_duplicates"]["flagged_questions"] >= 2
    assert all(isinstance(i["near_duplicate_doc_ids"], list) for i in items)
    assert meta["near_duplicates"]["flagged_questions"] == sum(1 for i in items if i["near_duplicate_doc_ids"])


def test_a_held_out_use_case_with_a_same_agency_twin_in_the_corpus_is_not_used():
    rows = synthetic_rows(300)
    corpus_rows = set(range(1, 201))
    for number in range(201, 301):
        twin = rows[number - 201]                        # a corpus row
        fields = rows[number - 1].fields
        fields.update({"agency": twin.get("agency"), "agency_name": twin.get("agency_name")})
        if number % 2:                                   # odd rows: the same description as a same-agency corpus row
            fields.update({"problem_solved": twin.get("problem_solved"), "benefits": twin.get("benefits")})
            twin.fields["problem_solved"] = fields["problem_solved"] = (
                f"Automatically integrated assistant number {number} without an identified benefit.")
        else:                                            # even rows: a description of their own
            fields["problem_solved"] = f"Something entirely different, case {number}: glacier telemetry."
            fields["benefits"] = "Fewer field visits."
    items, meta = evalset.build_eval_set(rows, corpus_rows, 11, dict(SMALL, unanswerable_heldout=30))
    held = [i for i in items if i["type"] == "unanswerable_heldout"]
    assert held and all(i["source_row"] % 2 == 0 for i in held)
    excluded = meta["near_duplicates"]["excluded_rows"]["unanswerable_heldout"]
    assert len([row for row in excluded if row % 2 == 1]) >= 20      # the twins that were looked at were turned down


def test_the_rule_and_its_thresholds_are_written_into_the_meta_file():
    _, meta = evalset.build_eval_set(synthetic_rows(300), set(range(1, 201)), 11, SMALL)
    rule = meta["near_duplicates"]
    assert rule["name_ratio_answerable"] == 0.75
    assert rule["name_ratio_heldout_same_agency"] == 0.70 and rule["text_overlap_heldout_same_agency"] == 0.80
    assert set(rule["excluded_rows"]) == {"agency", "stage", "high_impact", "unanswerable_heldout"}


def test_the_builder_is_still_deterministic_with_the_exclusions():
    first = evalset.build_eval_set(twin_rows(), set(range(1, 201)), 11, SMALL)
    again = evalset.build_eval_set(twin_rows(), set(range(1, 201)), 11, SMALL)
    assert first == again
