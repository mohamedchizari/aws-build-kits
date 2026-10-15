"""Round 1 review: the README and the results template must say what the code does.

MAJOR 1 and 4, MINOR 7, 8, 10, 11 and 12 were (also) wrong or missing sentences. These
tests tie the sentences to the code so they cannot drift apart again without a test failing.
"""
from __future__ import annotations

import re

import pytest

from conftest import KIT_DIR
from kitlib import aws as api
from kitlib import redact, scoring
from kitlib.evalset import HIGH_IMPACT_LABELS, STAGE_LABELS, simple_label_set

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
TEMPLATE = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")
LABEL_SETS = {"stage": simple_label_set(STAGE_LABELS), "high_impact": simple_label_set(HIGH_IMPACT_LABELS)}


def section(number: int) -> str:
    parts = re.split(r"^## \d+\. .*$", README, flags=re.MULTILINE)
    return parts[number]


def exact(kind, expected, answer):
    item = {"answerable": True, "label_set": kind, "expected_answer": expected, "use_case_name": "Some tool"}
    return scoring.score_exact(item, answer, LABEL_SETS)


# --- MAJOR 1: re-ranking -----------------------------------------------------------------------------------

def test_the_readme_no_longer_says_the_kit_uses_no_reranking():
    assert "re-ranking models, or OpenSearch. The kit uses none of them" not in README
    assert 'Do not say "no re-ranking" either' in section(7)
    assert "hybrid search with the service-managed re-ranking model switched on" in section(7)
    assert "rerankingModelType: MANAGED" in section(1)
    assert api.MANAGED_RERANKING_MODEL_TYPE == "MANAGED"
    assert "rerankingModelType=MANAGED" in api.describe_retrieval("managed")
    assert "rerankingModelType=MANAGED" in TEMPLATE


# --- MAJOR 4: the judge's family, wherever the table is described --------------------------------------------

def test_the_same_family_judge_is_stated_wherever_the_table_is_described():
    for number in (1, 2, 6, 7):
        assert "Amazon Nova" in section(number), f"section {number}"
    assert "The judge was an Amazon Nova model grading an Amazon Nova generator" in section(7)
    assert "an Amazon Nova judge grading an Amazon Nova generator" in TEMPLATE
    assert '"Z by a judge model"' not in README and "Z by a judge model, with 95% intervals" not in README


# --- MINOR 7 and BLOCKER 1: the README's description of exact match is what the code does ------------------------
# Rewritten in round 2. The round 1 test pinned the three sentences that exact match scored wrong and
# the three wrong answers it credited; the allow-list that replaced those rules credits none of the three.
# The full check of section 2, item 8 against the code is in test_review_r2_docs.py.

def test_the_wrong_answers_item_8_used_to_admit_crediting_are_no_longer_credited():
    for fooled in ("It is not, as far as I can tell, Deployed",
                   "The tool was deployed by the agency, but its stage is not recorded"):
        result = exact("stage", "Deployed", fooled + ".")
        assert (result["exact"], result["unclear"]) == (False, True), fooled
    in_passing = "The passages list use cases from the Department of Energy, but not this one"
    agencies = {"agency": [{"label": "Department of Energy", "aliases": [{"text": "DOE", "case_sensitive": True}]}]}
    assert scoring.score_exact(
        {"answerable": True, "label_set": "agency", "expected_answer": "Department of Energy",
         "use_case_name": "Some tool"}, in_passing + ".", agencies)["exact"] is False
    # the three correct answers it lost in round 1 are still lost, and the README still says so in substance
    for sentence, kind, expected in (("It is Deployed and has not been retired", "stage", "Deployed"),
                                     ("As of May 2025 it is Deployed", "stage", "Deployed")):
        assert exact(kind, expected, sentence + ".")["exact"] is False, sentence
    assert "As of May 2025 it is Deployed." in section(2)
    # one of them is credited now: the value followed by "use case"
    assert exact("high_impact", "High-impact", "It is a high-impact use case.")["exact"] is True
    assert scoring.DECLINE_SENTENCE in section(2)
    assert "a value after a negation does not count" not in README       # the old, looser claim


def test_the_readme_describes_the_judge_parser_as_it_is():
    item_9 = section(2).split("9. **The judge")[1].split("10. **")[0]
    for reply in ("not correct", "PARTIALLY CORRECT"):
        assert reply in item_9 and scoring.parse_judge(reply) == scoring.UNPARSEABLE
    assert "judge verdict unclear" in item_9


# --- MINOR 8: nothing documented is called unverified, and every UNVERIFIED item is where the README says ---

def test_documented_facts_are_no_longer_listed_as_unverified():
    assert 'cannot be used with managed knowledge bases' in README
    assert "The user guide pages read do not say either way" not in README
    assert "fixed-size chunking with 300 tokens and 20% overlap" in README
    assert "the sync skips its delete phase" in README
    unverified = section(8).split("**UNVERIFIED:")[1]
    assert 'what "deletion protection" on a managed data source guards against' not in unverified
    assert "whether `RetrieveAndGenerate` works with a managed knowledge base" not in unverified


def test_every_unverified_item_in_the_readme_names_a_file_that_carries_the_mark():
    assert "Each is also marked `UNVERIFIED:` in the code" not in README
    bullets = re.findall(r"^- UNVERIFIED: .*$", section(8), flags=re.MULTILINE)
    assert len(bullets) >= 12
    readme_only = 0
    for bullet in bullets:
        tail = bullet.rstrip()
        if tail.endswith("(README only)."):
            readme_only += 1
            continue
        named = re.findall(r"`((?:kitlib/)?[0-9a-z_]+\.py)`", tail)
        assert named, f"no file named in: {bullet[:90]}"
        for name in named:
            assert "UNVERIFIED:" in (KIT_DIR / name).read_text(encoding="utf-8"), f"{name} has no UNVERIFIED mark"
    assert readme_only == 3


def test_every_file_with_an_unverified_mark_is_named_in_the_readme_list():
    unverified = section(8).split("**UNVERIFIED:")[1]
    for path in sorted(list(KIT_DIR.glob("*.py")) + list((KIT_DIR / "kitlib").glob("*.py"))):
        if "UNVERIFIED:" in path.read_text(encoding="utf-8"):
            name = path.relative_to(KIT_DIR).as_posix()
            assert f"`{name}`" in unverified, name


# --- MINOR 10: where the passage text is ----------------------------------------------------------------------

def test_the_readme_says_the_passage_text_is_in_raw_jsonl_not_in_the_csv():
    assert "read all five rows: the passages retrieved" not in README
    assert "The text of the retrieved passages is not in the CSV" in section(4)
    assert "`retrieved_passages`" in section(4)


# --- MINOR 11: the paired comparison -----------------------------------------------------------------------------

def test_the_readme_does_not_compare_the_two_columns_by_overlapping_intervals():
    assert "Do not call a difference real if the intervals overlap" not in README
    assert "when the 95% intervals overlap" not in README
    assert "they are the same 100 answers" in section(2)
    assert "The two columns are the same answers" in section(7)
    summary = scoring.render_summary_markdown(scoring.summarise([], top_k=5))
    assert "The two columns are the same answers" in summary and "not a comparison of two samples" in summary


# --- MINOR 12 and the shared rule: the clean check as documented ------------------------------------------------

def test_the_readme_documents_the_clean_checks_exit_codes_and_the_shared_audit_command():
    five = section(5)
    for code in ("| 0 |", "| 1 |", "| 3 |", "| 4 |", "| 5 |"):
        assert code in five
    assert "INCOMPLETE" in five and "RESULT line" in five
    assert "uses no state file" not in README
    assert ("`python ../common/whats_running.py --region <the AWS_REGION in your config.env> "
            "--prefix <your KIT_PREFIX>`") in five
    assert "whats_running.py --region us-east-1" not in README          # no hardcoded Region
    source = (KIT_DIR / "99_verify_clean.py").read_text(encoding="utf-8")
    assert "EXIT_CLEAN, EXIT_NOT_CLEAN, EXIT_COLLECTIONS, EXIT_INCOMPLETE, EXIT_DRY_RUN = 0, 1, 3, 4, 5" in source


def test_the_readme_says_an_exported_region_overrides_the_config_file():
    assert "An `AWS_REGION` exported in your shell overrides `config.env`" in section(2)
    assert "echo $AWS_REGION" in section(3)
    assert "overrides this line" in (KIT_DIR / "config.example.env").read_text(encoding="utf-8")


def test_section_8_carries_the_dated_review_line():
    match = re.search(r"Reviewed independently on 2026-10-07 \(round 1\): (\d+) findings, (\d+) fixed, "
                      r"(\d+) left open \(listed below\)", section(8))
    assert match
    findings, fixed, left_open = map(int, match.groups())
    assert findings == 21 and fixed + left_open == findings


def test_the_test_count_in_the_readme_is_a_number():
    assert re.search(r"`python -m pytest -q`: [\d,]{3,5} tests passed, 0 failed", section(8))
    assert re.search(r"\| `tests/` \| [\d,]{3,5} offline tests", section(1))


# --- the account id never leaves the machine in full -----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("arn:aws:iam::123456789012:role/kitdemo-fedrag-kb-role-us-east-1",
     "arn:aws:iam::********9012:role/kitdemo-fedrag-kb-role-us-east-1"),
    ("s3://kitdemo-fedrag-corpus-123456789012-us-east-1/corpus/uc-0001.txt",
     "s3://kitdemo-fedrag-corpus-********9012-us-east-1/corpus/uc-0001.txt"),
    ("Account: 123456789012", "Account: ********9012"),
    ("run-20261007T101010Z, 183,000 tokens, commit 06c7ebeef5b3, CSV row 1396", None),
    ("sha a62721202ca4b110ce3c53ffdb688d05ad27a35971a7afda4f1179b2493e31d0", None),
    ("1234567890123 is thirteen digits and 12345678901 is eleven", None),
])
def test_redact_masks_twelve_digit_numbers_and_nothing_else(text, expected):
    assert redact.redact(text) == (text if expected is None else expected)


def test_account_label_shows_four_digits_or_unknown():
    assert redact.account_label("123456789012") == "********9012"
    assert redact.account_label(None) == "unknown" and redact.account_label("") == "unknown"


def test_protect_output_filters_stdout_and_stderr_and_puts_them_back(capsys):
    import sys

    @redact.protect_output
    def main():
        print("bucket kitdemo-fedrag-corpus-123456789012-us-east-1")
        print("error for arn:aws:iam::123456789012:user/x", file=sys.stderr)
        raise SystemExit(3)

    before = sys.stdout, sys.stderr
    with pytest.raises(SystemExit):
        main()
    assert (sys.stdout, sys.stderr) == before
    captured = capsys.readouterr()
    assert "123456789012" not in captured.out + captured.err
    assert "********9012" in captured.out and "********9012" in captured.err


def test_the_two_s3_calls_added_for_stale_objects_build_valid_requests():
    aws = api.Aws("us-east-1", dry_run=True, echo=lambda *_: None, canned={
        ("s3", "list_objects_v2"): {"Contents": [{"Key": "corpus/uc-0001.txt"}], "IsTruncated": False}})
    assert api.list_object_keys(aws, "bucket-name", "corpus/") == ["corpus/uc-0001.txt"]
    assert api.delete_object_keys(aws, "bucket-name", [f"corpus/uc-{n:04d}.txt" for n in range(1, 1202)]) == 1201
    calls = [(operation, params) for _, operation, params in aws.calls]
    assert calls[0] == ("list_objects_v2", {"Bucket": "bucket-name", "Prefix": "corpus/", "MaxKeys": 1000})
    assert [len(params["Delete"]["Objects"]) for operation, params in calls if operation == "delete_objects"] == [
        1000, 201]
    assert api.list_buckets(aws) == [] and "Prefix" not in aws.calls[-1][2]       # every bucket, no prefix
    assert api.list_vector_buckets(aws) == [] and "prefix" not in aws.calls[-1][2]
