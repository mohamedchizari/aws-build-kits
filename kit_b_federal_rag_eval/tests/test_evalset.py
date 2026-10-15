"""Evaluation set builder: deterministic, answers copied from the CSV, no model involved."""
from __future__ import annotations

import inspect

from conftest import AGENCIES, HIGH_IMPACT, STAGES, synthetic_rows
from kitlib import corpus, evalset

SMALL = {"agency": 12, "stage": 8, "high_impact": 6, "unanswerable_heldout": 4, "unanswerable_absent_field": 3}


def build(rows=None, corpus_rows=None, seed=11, counts=None):
    rows = rows if rows is not None else synthetic_rows(300)
    corpus_rows = corpus_rows if corpus_rows is not None else set(range(1, 201))
    return rows, *evalset.build_eval_set(rows, corpus_rows, seed, counts or SMALL)


def test_same_seed_same_set_and_other_seed_other_set():
    _, a, meta_a = build(seed=11)
    _, b, meta_b = build(seed=11)
    _, c, _ = build(seed=12)
    assert a == b and meta_a == meta_b
    assert [i["source_row"] for i in a] != [i["source_row"] for i in c]


def test_counts_by_type_are_what_was_asked_for():
    _, items, meta = build()
    assert meta["built"] == SMALL
    assert meta["answerable"] == 26 and meta["unanswerable"] == 7 and meta["total"] == 33
    assert meta["shortfalls"] == {}
    assert [i["id"] for i in items] == [f"q-{n:03d}" for n in range(1, 34)]


def test_every_expected_answer_is_the_csv_cell_of_its_source_row():
    rows, items, _ = build()
    by_number = {r.row_number: r for r in rows}
    field_for = {"agency": "agency_name", "stage": "development_stage", "high_impact": "is_high_impact"}
    for item in items:
        row = by_number[item["source_row"]]
        assert item["use_case_name"] == row.get("use_case_name")
        assert f'"{row.get("use_case_name")}"' in item["question"]
        if item["answerable"]:
            assert item["expected_answer"] == row.get(field_for[item["type"]])
            assert item["source_doc_id"] == row.doc_id
            assert field_for[item["type"]] in item["csv_fields"]
        else:
            assert item["expected_answer"] == evalset.NO_ANSWER
            assert item["source_doc_id"] is None


def test_agency_questions_carry_the_abbreviation_as_a_case_sensitive_alias():
    rows, items, _ = build()
    by_number = {r.row_number: r for r in rows}
    for item in [i for i in items if i["type"] == "agency"]:
        assert item["accepted_aliases"] == [
            {"text": by_number[item["source_row"]].get("agency"), "case_sensitive": True}]


def test_answerable_sources_are_in_the_corpus_and_heldout_sources_are_not():
    _, items, _ = build()
    corpus_rows = set(range(1, 201))
    for item in items:
        if item["type"] == "unanswerable_heldout":
            assert item["source_row"] not in corpus_rows
        else:
            assert item["source_row"] in corpus_rows


def test_no_row_is_used_twice():
    _, items, _ = build()
    rows_used = [i["source_row"] for i in items]
    assert len(rows_used) == len(set(rows_used))


def test_labels_are_balanced_across_values():
    _, items, meta = build(counts={**SMALL, "stage": 8, "high_impact": 6})
    assert meta["expected_answer_counts"]["stage"] == {s: 2 for s in STAGES}
    assert meta["expected_answer_counts"]["high_impact"] == {h: 2 for h in HIGH_IMPACT}
    agencies = meta["expected_answer_counts"]["agency"]
    assert len(agencies) == len(AGENCIES) and set(agencies.values()) == {2}


def test_duplicate_names_are_never_used():
    rows = synthetic_rows(300)
    for n in (5, 6, 7):  # three rows share one name
        rows[n - 1].fields["use_case_name"] = "Shared duplicated use case name"
    _, items, _ = build(rows=rows)
    assert "Shared duplicated use case name" not in {i["use_case_name"] for i in items}


def test_short_or_oddly_punctuated_names_are_never_used():
    rows = synthetic_rows(300)
    counts = evalset.name_counts(rows)
    def with_name(name):
        return corpus.Row(999, {"use_case_name": name, "agency_name": "X", "agency": "X"})
    counts.update([evalset.norm_name(n) for n in ("Chatbot", 'Tool "Alpha" for review of claims',
                                                    "Deep?learning integration for operations",
                                                    "A perfectly ordinary use case name")])
    assert not evalset.good_name(with_name("Chatbot"), counts)
    assert not evalset.good_name(with_name('Tool "Alpha" for review of claims'), counts)
    assert not evalset.good_name(with_name("Deep?learning integration for operations"), counts)
    assert evalset.good_name(with_name("A perfectly ordinary use case name"), counts)


def test_names_containing_a_value_of_the_field_are_not_used_for_that_question_type():
    stage_set = evalset.simple_label_set(evalset.STAGE_LABELS)
    assert evalset.name_contains_value("Claims triage Pilot for regional offices", stage_set)
    assert evalset.name_contains_value("Tracker for pre-deployment testing", stage_set)
    assert not evalset.name_contains_value("Claims triage assistant for regional offices", stage_set)
    agency_set = [{"label": "Department of Energy", "aliases": [{"text": "DOE", "case_sensitive": True}]}]
    assert evalset.name_contains_value("DOE grid forecasting model", agency_set)
    assert evalset.name_contains_value("Forecasts for the Department of Energy grid", agency_set)
    assert not evalset.name_contains_value("Does grid forecasting well", agency_set)  # 'Does' is not 'DOE'

    rows = synthetic_rows(300)
    for n in range(1, 201):
        if rows[n - 1].get("development_stage") == "Pilot":
            rows[n - 1].fields["use_case_name"] += " pilot"
    _, items, meta = build(rows=rows)
    assert "Pilot" not in meta["expected_answer_counts"]["stage"]
    for item in items:
        if item["type"] == "stage":
            assert "pilot" not in item["use_case_name"].lower()


def test_names_that_leak_their_own_agency_are_not_used_for_agency_questions():
    row = corpus.Row(1, {"use_case_name": "AAA records sorter for field staff",
                         "agency": "AAA", "agency_name": "Agency for Alpha Affairs"})
    assert evalset.leaks_agency(row)
    row2 = corpus.Row(2, {"use_case_name": "Records sorter for field staff",
                          "agency": "AAA", "agency_name": "Agency for Alpha Affairs"})
    assert not evalset.leaks_agency(row2)


def test_absent_field_questions_avoid_rows_whose_text_mentions_the_attribute():
    rows = synthetic_rows(300)
    for n in range(1, 201):  # every corpus row mentions a budget, staff and accuracy
        rows[n - 1].fields["benefits"] = "Saves budget, frees staff, 95% accuracy."
    _, items, meta = build(rows=rows)
    assert meta["built"].get("unanswerable_absent_field", 0) == 0
    assert meta["shortfalls"] == {"unanswerable_absent_field": 3}
    assert not [i for i in items if i["type"] == "unanswerable_absent_field"]


def test_heldout_questions_avoid_names_close_to_a_corpus_name():
    rows = synthetic_rows(300)
    for n in range(201, 301):  # every held-out row is a near copy of a corpus row's name
        rows[n - 1].fields["use_case_name"] = rows[n - 201].get("use_case_name") + " two"
    _, _, meta = build(rows=rows)
    assert meta["built"].get("unanswerable_heldout", 0) == 0
    assert meta["shortfalls"]["unanswerable_heldout"] == 4


def test_heldout_questions_avoid_names_quoted_inside_a_corpus_document():
    rows = synthetic_rows(300)
    wanted = {r.row_number: r.get("use_case_name") for r in rows[200:]}
    rows[0].fields["problem_solved"] = "Works together with: " + "; ".join(wanted.values())
    _, _, meta = build(rows=rows)
    assert meta["built"].get("unanswerable_heldout", 0) == 0


def test_whole_csv_as_corpus_reports_a_shortfall_instead_of_inventing_heldout_questions():
    rows = synthetic_rows(120)
    _, items, meta = build(rows=rows, corpus_rows=set(range(1, 121)))
    assert meta["shortfalls"] == {"unanswerable_heldout": 4}
    assert not [i for i in items if i["type"] == "unanswerable_heldout"]


def test_label_sets_in_meta_cover_every_agency_and_fixed_value():
    rows, _, meta = build()
    assert [e["label"] for e in meta["label_sets"]["stage"]] == evalset.STAGE_LABELS
    assert [e["label"] for e in meta["label_sets"]["high_impact"]] == evalset.HIGH_IMPACT_LABELS
    assert {e["label"] for e in meta["label_sets"]["agency"]} == {name for _, name in AGENCIES}
    assert {e["aliases"][0]["text"] for e in meta["label_sets"]["agency"]} == {abbr for abbr, _ in AGENCIES}


def test_builder_source_uses_no_model_and_no_network():
    source = inspect.getsource(evalset)
    for forbidden in ("boto3", "converse", "requests", "urllib", "openai", "anthropic"):
        assert forbidden not in source.lower()


def test_builder_and_scorer_agree_on_gold_wrong_and_declined_answers():
    """An oracle that reads the expected answer scores 100%; a wrong value and a refusal score 0%."""
    from kitlib import config, scoring

    rows, items, meta = build(counts={"agency": 18, "stage": 12, "high_impact": 9,
                                      "unanswerable_heldout": 6, "unanswerable_absent_field": 3})
    by_number = {r.row_number: r for r in rows}
    label_sets = meta["label_sets"]
    line_start = {"agency": "Agency: ", "stage": "Stage of development: ",
                  "high_impact": "High-impact determination: "}
    answerable = [i for i in items if i["answerable"]]
    assert len(answerable) == 39
    for item in answerable:
        document = corpus.render_document(by_number[item["source_row"]], config.OMB_COMMIT)
        line = [l for l in document.splitlines() if l.startswith(line_start[item["type"]])][0]
        assert item["expected_answer"] in line                       # the answer is in the document
        # Since the round 2 review exact match credits only the expected value plus words from a short
        # list. The document's own line is such an answer; so is the question restated with the value.
        assert scoring.score_exact(item, line, label_sets)["exact"] is True
        gold = f'{item["question"]} {item["expected_answer"]}.'
        assert scoring.score_exact(item, gold, label_sets)["exact"] is True
        other = [e["label"] for e in label_sets[item["label_set"]] if e["label"] != item["expected_answer"]][0]
        assert scoring.score_exact(item, f"The inventory records: {other}.", label_sets)["exact"] is False
        assert scoring.score_exact(item, scoring.DECLINE_SENTENCE, label_sets)["exact"] is False
    for item in [i for i in items if i["type"] == "agency"]:
        abbreviation = item["accepted_aliases"][0]["text"]
        assert scoring.score_exact(item, f"It was reported by {abbreviation}.", label_sets)["exact"] is True
    for item in [i for i in items if not i["answerable"]]:
        assert scoring.score_exact(item, scoring.DECLINE_SENTENCE, label_sets)["exact"] is True
        assert scoring.score_exact(item, "The Agency for Alpha Affairs.", label_sets)["exact"] is False
