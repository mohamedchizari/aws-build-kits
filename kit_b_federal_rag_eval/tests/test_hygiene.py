"""Rules from the spine that can be checked mechanically."""
from __future__ import annotations

import re

from conftest import KIT_DIR

# Folders the scripts or you create while using the kit. They are git-ignored and not part of it.
GENERATED = (".pytest_cache", "__pycache__", "build", "results", ".venv", "venv", ".git")
TEXT_FILES = sorted(
    p for p in KIT_DIR.rglob("*")
    if p.is_file() and p.suffix in (".py", ".md", ".txt", ".env", ".json", ".csv", "") and
    not any(part in GENERATED for part in p.relative_to(KIT_DIR).parts)
    and p.name not in (".state.json", "config.env"))

README_HEADINGS = [
    "What this is",
    "Problems first",
    "Before you start",
    "Run it",
    "Tear it down and prove it",
    "What to record",
    "What you can truthfully say afterwards, and what you cannot",
    "What was and was not tested",
    "Sources",
]


def read(path):
    return path.read_text(encoding="utf-8-sig")


def test_required_files_exist():
    for name in ("README.md", "requirements.txt", "config.example.env", "RESULTS_TEMPLATE.md", ".gitignore",
                 "00_check.py", "90_teardown.py", "99_verify_clean.py", "tests/fixtures/inventory_5rows.csv"):
        assert (KIT_DIR / name).is_file(), name


def test_readme_has_exactly_the_nine_headings_in_order():
    headings = re.findall(r"^## (.+)$", read(KIT_DIR / "README.md"), flags=re.MULTILINE)
    assert headings == [f"{number}. {title}" for number, title in enumerate(README_HEADINGS, start=1)]


def test_readme_says_unofficial_and_that_no_aws_call_was_run():
    text = read(KIT_DIR / "README.md").lower()
    assert "unofficial" in text and "not endorsed by" in text
    assert "no aws call was run" in text or "no aws api call was run" in text


def test_no_em_dashes_anywhere():
    for path in TEXT_FILES:
        if path.name == "inventory_5rows.csv":        # public source data, copied as published
            continue
        assert "\u2014" not in read(path), f"em dash in {path.name}"


def test_no_credentials_account_ids_or_email_addresses():
    allowed_ids = {"000000000000", "123456789012", "111122223333"}   # documentation placeholders
    for path in TEXT_FILES:
        text = read(path)
        assert not re.search(r"AKIA[0-9A-Z]{16}", text), f"access key id in {path.name}"
        for value in re.findall(r"aws_secret_access_key\s*=\s*(\S+)", text, re.IGNORECASE):
            assert value.startswith('"testing"'), f"secret-looking value in {path.name}"   # Stubber dummy only
        if path.name != "inventory_5rows.csv":
            for found in re.findall(r"(?<![0-9A-Za-z])\d{12}(?![0-9A-Za-z])", text):
                assert found in allowed_ids, f"12-digit number {found} in {path.name}"
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", text), f"email address in {path.name}"


def test_fixture_has_five_rows_and_blank_contact_emails():
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(read(KIT_DIR / "tests" / "fixtures" / "inventory_5rows.csv"))))
    assert len(rows) == 5 and all(r["contact_email"] == "" for r in rows)


def test_gitignore_keeps_generated_files_out():
    lines = read(KIT_DIR / ".gitignore").splitlines()
    for entry in ("build/", "results/", ".state.json", "config.env", ".venv/"):
        assert entry in lines


def test_no_corpus_or_downloaded_data_sits_outside_the_ignored_folders():
    assert [p for p in TEXT_FILES if p.stat().st_size > 200_000] == []
    assert [p for p in TEXT_FILES if re.fullmatch(r"uc-\d+\.txt(\.metadata\.json)?", p.name)] == []
    csvs = [p.relative_to(KIT_DIR).as_posix() for p in TEXT_FILES if p.suffix == ".csv"]
    assert csvs == ["tests/fixtures/inventory_5rows.csv"]


def test_requirements_are_pinned():
    lines = [line for line in read(KIT_DIR / "requirements.txt").splitlines() if line and not line.startswith("#")]
    assert lines and all(re.fullmatch(r"[a-z0-9-]+==\d+\.\d+\.\d+", line) for line in lines)
    assert any(line.startswith("boto3==") for line in lines)


def test_installed_sdk_is_the_pinned_one():
    import boto3
    pinned = [line.split("==")[1] for line in read(KIT_DIR / "requirements.txt").splitlines()
              if line.startswith("boto3==")][0]
    assert boto3.__version__ == pinned


def test_unverified_items_in_code_are_repeated_in_the_readme():
    count = 0
    for path in list(KIT_DIR.glob("*.py")) + list((KIT_DIR / "kitlib").glob("*.py")):
        count += len(re.findall(r"# UNVERIFIED:|UNVERIFIED:", read(path)))
    assert count >= 4
    assert read(KIT_DIR / "README.md").count("UNVERIFIED") >= count


def test_every_script_has_a_dry_run_flag_and_billing_scripts_have_the_gate():
    for path in sorted(KIT_DIR.glob("[0-9][0-9]_*.py")):
        source = read(path)
        assert "make_parser(" in source and "args.dry_run" in source, path.name
    for name in ("30_deploy_kb.py", "40_create_guardrail.py", "50_run_eval.py"):
        assert "require_bills_flag(" in read(KIT_DIR / name), name


def test_only_kitlib_aws_talks_to_aws():
    for path in list(KIT_DIR.glob("*.py")) + list((KIT_DIR / "kitlib").glob("*.py")):
        if path.name == "aws.py":
            continue
        source = read(path)
        assert "import boto3" not in source and "boto3.client" not in source, path.name
        assert ".call(" not in source or path.name in ("resources.py",), path.name
