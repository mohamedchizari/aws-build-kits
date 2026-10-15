"""Shared test setup. The whole suite runs offline: no network, no AWS credentials."""
from __future__ import annotations

import csv
import io
import os
import random
import socket
import sys
from pathlib import Path

import pytest

KIT_DIR = Path(__file__).resolve().parent.parent
FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "inventory_5rows.csv"
if str(KIT_DIR) not in sys.path:
    sys.path.insert(0, str(KIT_DIR))

from kitlib import corpus  # noqa: E402


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Fail any test that opens a network connection, and keep all output in tmp_path."""
    def refuse(self, *args, **kwargs):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    for name in list(os.environ):
        if name.startswith("AWS_") or name.startswith("PRICE_") or name in (
                "KIT_PREFIX", "KB_TYPE", "GEN_MODEL_ID", "JUDGE_MODEL_ID", "EMBED_MODEL_ID", "TOP_K",
                "GROUNDING_THRESHOLD", "RELEVANCE_THRESHOLD", "CORPUS_SAMPLE_SIZE", "SEED"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("KIT_CONFIG_FILE", str(tmp_path / "no-config.env"))   # ignore the user's config.env
    monkeypatch.setenv("KIT_BUILD_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("KIT_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("KIT_RESULTS_DIR", str(tmp_path / "results"))
    yield


AGENCIES = [
    ("AAA", "Agency for Alpha Affairs"),
    ("BBB", "Bureau of Beta Business"),
    ("CCC", "Commission on Gamma Controls"),
    ("DDD", "Department of Delta Design"),
    ("EEE", "Election Epsilon Office"),
    ("FFF", "Federal Zeta Foundation"),
]
STAGES = ["Pre-deployment", "Pilot", "Deployed", "Retired"]
HIGH_IMPACT = ["High-impact", "Not High-impact", "Presumed High-Impact, but Not High-impact"]
WORDS = ["harbor", "lantern", "meadow", "quartz", "ribbon", "saddle", "timber", "velvet", "willow", "zephyr",
         "anchor", "beacon", "cinder", "dapple", "ember", "fennel", "garnet", "hollow", "indigo", "juniper"]


KINDS = ["sorter", "monitor", "planner", "tracker", "reviewer", "mapper", "forecaster"]


def synthetic_rows(n: int = 300) -> list[corpus.Row]:
    """Made-up inventory rows with the real column names. Every name is unique."""
    rows = []
    for i in range(1, n + 1):
        abbr, agency = AGENCIES[i % len(AGENCIES)]
        w = random.Random(i).sample(WORDS, 3)
        name = f"{w[0].title()} {w[1]} {w[2]} {KINDS[i % 7]} {i}"
        rows.append(corpus.Row(i, {
            "agency": abbr, "agency_name": agency, "id": f"{abbr}-{i}",
            "use_case_name": name, "agency_bureau": f"Office {i % 9}", "contact_email": "",
            "development_stage": STAGES[i % 4], "is_high_impact": HIGH_IMPACT[i % 3],
            "topic_area": "Science", "classification": "Classical ML",
            # Each description has words of its own (case12, lot84, run156), so that two rows of
            # one agency are not near-duplicates of each other by description.
            "problem_solved": f"Sorts incoming {WORDS[(i * 3) % 20]} records faster, case{i} lot{i * 7} run{i * 13}.",
            "benefits": "Less manual review.", "system_outputs": "A ranked list.",
        }))
    return rows


def rows_to_csv_bytes(rows: list[corpus.Row]) -> bytes:
    columns = ["agency", "agency_name", "id", "use_case_name", "agency_bureau", "contact_email",
               "development_stage", "is_high_impact", "topic_area", "classification",
               "problem_solved", "benefits", "system_outputs"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.fields.get(c, "") for c in columns})
    return ("\ufeff" + out.getvalue()).encode("utf-8")


@pytest.fixture
def fixture_rows() -> list[corpus.Row]:
    return corpus.parse_csv(FIXTURE_CSV.read_bytes())
