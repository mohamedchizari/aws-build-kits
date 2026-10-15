"""Re-record the Federal Register fixtures. NETWORK. Not run by pytest. No AWS.

    python tests/record_fixtures.py --dry-run     # print the four requests, send none
    python tests/record_fixtures.py --record      # send them and rewrite tests/fixtures/
    python tests/record_fixtures.py --help

Nothing is sent without --record. Run with no argument, or with one it does
not know, it prints what it would do and stops with exit code 2. (Before the
review of 2026-10-07 any argument other than --dry-run, including --help, sent
the four requests and rewrote the fixtures.)

With --record it makes four GET requests to federalregister.gov through the
real tool functions and writes what came back, with the exact request that
produced it, into tests/fixtures/. The offline tests replay these files and
also check that the tools still build the same request. Several tests name the
documents in the current recording, so after a re-record expect to update them.

Bodies are small because the tools ask the API for a short list of fields and
at most three results. Nothing else is trimmed, so each file is what the API
returned for that request on the day it was recorded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import fr_tools  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class RecordingSession:
    """Wraps requests.Session and remembers the last exchange."""

    def __init__(self):
        import requests

        self._session = requests.Session()
        self.last = None

    def get(self, url, params=None, headers=None, timeout=None):
        resp = self._session.get(url, params=params, headers=headers, timeout=timeout)
        try:
            body = resp.json()
        except ValueError:
            body = None
        self.last = {
            "request": {"url": url, "params": [list(p) for p in (params or [])]},
            "status": resp.status_code,
            "body": body,
        }
        return resp


def _save(name: str, session: RecordingSession, today: str) -> None:
    record = {"recorded_on": today, "source": "federalregister.gov/api/v1", **session.last}
    path = FIXTURES / name
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}  status={record['status']}  bytes={path.stat().st_size}")


def plan(date_from: str, date_to: str) -> list[str]:
    base = fr_tools.BASE_URL
    return [
        f"GET {base}/documents.json  term=\"artificial intelligence\" type=RULE {date_from}..{date_to} per_page=3",
        f"GET {base}/documents.json  term=zzqxv-kit-c-no-such-term (expects no results)",
        f"GET {base}/documents/<first result>.json",
        f"GET {base}/documents/0000-00000.json (expects 404)",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print the four requests this would send and send none")
    mode.add_argument("--record", action="store_true",
                      help="required to send anything: make the four requests and rewrite the fixtures")
    args = parser.parse_args(argv)

    today = dt.date.today()
    date_to = today.isoformat()
    date_from = (today - dt.timedelta(days=30)).isoformat()
    if not args.record:
        for line in plan(date_from, date_to):
            print(f"DRY-RUN  would {line}")
        if args.dry_run:
            print("DRY-RUN complete: nothing was sent and no fixture was written.")
            return 0
        print("Nothing was sent and no fixture was written. Add --record to send these four "
              "requests and rewrite tests/fixtures/.")
        return 2
    FIXTURES.mkdir(parents=True, exist_ok=True)
    s = RecordingSession()

    found = fr_tools.search_documents(
        '"artificial intelligence"', doc_type="RULE", date_from=date_from, date_to=date_to,
        limit=3, session=s,
    )
    _save("search_ai_rules.json", s, date_to)

    fr_tools.search_documents(
        "zzqxv-kit-c-no-such-term", doc_type="RULE", date_from=date_from, date_to=date_to,
        limit=3, session=s,
    )
    _save("search_no_results.json", s, date_to)

    if found.get("results"):
        number = found["results"][0]["document_number"]
        fr_tools.get_document(number, session=s)
        _save("document_detail.json", s, date_to)
    else:
        print("the search returned nothing today, so document_detail.json was not re-recorded")

    fr_tools.get_document("0000-00000", session=s)
    _save("document_not_found.json", s, date_to)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
