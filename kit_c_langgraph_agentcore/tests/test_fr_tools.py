"""The two Federal Register tools, offline, against recorded real responses."""
from __future__ import annotations

import json

import pytest
from conftest import CannedSession, FakeResponse, RaisingSession, ReplaySession, load_fixture

from agent import fr_tools
from agent.fr_tools import ToolInputError


def _recorded_search_args(fixture: str) -> dict:
    """The arguments the recorder used, read back from the recorded request."""
    params = load_fixture(fixture)["request"]["params"]
    get = lambda key: next(v for k, v in params if k == key)  # noqa: E731
    return {
        "term": get("conditions[term]"),
        "doc_type": get("conditions[type][]"),
        "date_from": get("conditions[publication_date][gte]"),
        "date_to": get("conditions[publication_date][lte]"),
        "limit": int(get("per_page")),
    }


# ---------------------------------------------------------------- search
def test_search_replays_recorded_request_and_shapes_results():
    session = ReplaySession("search_ai_rules.json")
    out = fr_tools.search_documents(**_recorded_search_args("search_ai_rules.json"), session=session)
    body = load_fixture("search_ai_rules.json")["body"]
    assert "error" not in out
    assert out["count"] == body["count"]
    assert out["returned"] == len(body["results"]) >= 1
    first, raw = out["results"][0], body["results"][0]
    assert first["document_number"] == raw["document_number"]
    assert first["html_url"] == raw["html_url"]
    assert first["html_url"].startswith("https://www.federalregister.gov/documents/")
    assert first["agencies"] == [a["name"] for a in raw["agencies"]]
    # this recorded abstract (787 characters) fits under the cap since round 2, so nothing is cut
    full = " ".join(raw["abstract"].split())
    assert 400 < len(full) <= fr_tools.ABSTRACT_CHARS_SEARCH
    assert set(first) == {
        "document_number", "title", "type", "publication_date", "agencies", "html_url", "abstract",
        "search_words_in_title", "search_words_in_abstract",   # round 3: counted by code
    }
    assert first["abstract"] == full
    # round 3: the result says what its total is, in fixed words
    assert out["count_means"] == fr_tools.COUNT_MEANS and "not the number of documents about the topic" in out["count_means"]
    assert out["search_words_note"] == fr_tools.SEARCH_WORDS_NOTE


def test_search_cuts_an_abstract_longer_than_the_cap_and_says_so():
    record = load_fixture("search_ai_rules.json")
    long_body = json.loads(json.dumps(record["body"]))
    long_body["results"][0]["abstract"] = "word " * fr_tools.ABSTRACT_CHARS_SEARCH
    session = CannedSession({"/documents.json": (200, long_body)})
    out = fr_tools.search_documents("artificial intelligence", session=session)
    first = out["results"][0]
    assert set(first["truncated"]) == {"abstract"}
    assert first["abstract"].endswith(" " + fr_tools.TRUNCATION_MARK)
    assert len(first["abstract"]) <= fr_tools.ABSTRACT_CHARS_SEARCH
    assert first["truncated"]["abstract"]["characters_in_full_text"] == fr_tools.ABSTRACT_CHARS_SEARCH * 5 - 1


def test_search_sends_user_agent_and_timeouts():
    session = ReplaySession("search_ai_rules.json")
    fr_tools.search_documents(**_recorded_search_args("search_ai_rules.json"), session=session)
    call = session.calls[0]
    assert call["url"] == "https://www.federalregister.gov/api/v1/documents.json"
    assert "aws-kits-kit-c" in call["headers"]["User-Agent"]
    assert call["timeout"] == (fr_tools.CONNECT_TIMEOUT_S, fr_tools.READ_TIMEOUT_S)
    assert len(session.calls) == 1


def test_search_no_results_says_so():
    session = ReplaySession("search_no_results.json")
    out = fr_tools.search_documents(**_recorded_search_args("search_no_results.json"), session=session)
    assert out["count"] == 0 and out["returned"] == 0 and out["results"] == []
    assert "No Federal Register documents matched" in out["note"]


def test_search_truncates_long_abstracts():
    session = ReplaySession("search_ai_rules.json")
    out = fr_tools.search_documents(**_recorded_search_args("search_ai_rules.json"), session=session)
    raw = {d["document_number"]: d for d in load_fixture("search_ai_rules.json")["body"]["results"]}
    for doc in out["results"]:
        assert doc["abstract"] is None or len(doc["abstract"]) <= fr_tools.ABSTRACT_CHARS_SEARCH
        full = " ".join((raw[doc["document_number"]].get("abstract") or "").split())
        if len(full) > fr_tools.ABSTRACT_CHARS_SEARCH:
            # a cut is never silent: the text ends with the mark, at a word boundary, and the
            # result records how much there was
            assert doc["abstract"].endswith(" " + fr_tools.TRUNCATION_MARK)
            shown = doc["abstract"][: -len(fr_tools.TRUNCATION_MARK) - 1]
            assert full.startswith(shown) and full[len(shown)] == " "
            assert doc["truncated"]["abstract"] == {"characters_shown": len(shown),
                                                    "characters_in_full_text": len(full)}
        else:
            assert "abstract" not in doc.get("truncated", {})


def test_search_notes_when_more_matches_exist_than_returned():
    class Many:
        def get(self, url, params=None, headers=None, timeout=None):
            docs = [{"document_number": f"2026-{10000 + i}", "title": "t", "agencies": []} for i in range(2)]
            return FakeResponse(200, {"count": 57, "results": docs})

    out = fr_tools.search_documents("energy", limit=2, session=Many())
    assert out["count"] == 57 and out["returned"] == 2
    assert "2 newest of 57" in out["note"]


def test_build_search_params_full():
    params = fr_tools.build_search_params(
        "  climate   risk ", ["commerce-department", "commerce-department"], "final rule",
        "2026-01-01", "2026-01-31", 50,
    )
    assert ("conditions[term]", "climate risk") in params
    assert params.count(("conditions[agencies][]", "commerce-department")) == 1
    assert ("conditions[type][]", "RULE") in params
    assert ("conditions[publication_date][gte]", "2026-01-01") in params
    assert ("conditions[publication_date][lte]", "2026-01-31") in params
    assert ("per_page", str(fr_tools.MAX_LIMIT)) in params  # capped
    assert ("order", "newest") in params
    assert [v for k, v in params if k == "fields[]"] == list(fr_tools.SEARCH_FIELDS)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"term": ""},
        {"term": "   "},
        {"term": 42},
        {"term": "x" * 201},
        {"term": "ai", "agencies": ["Commerce Department"]},
        {"term": "ai", "agencies": ["a/../b"]},
        {"term": "ai", "agencies": [f"agency-{i}" for i in range(6)]},
        {"term": "ai", "doc_type": "MEMO"},
        {"term": "ai", "date_from": "10/07/2026"},
        {"term": "ai", "date_from": "2026-02-30"},
        {"term": "ai", "date_from": "2026-03-01", "date_to": "2026-02-01"},
        {"term": "ai", "limit": 0},
        {"term": "ai", "limit": "5"},
        {"term": "ai", "limit": True},
    ],
)
def test_search_rejects_bad_input_before_any_request(kwargs):
    session = RaisingSession(AssertionError("no request should be made"))
    with pytest.raises(ToolInputError):
        fr_tools.search_documents(session=session, **kwargs)
    assert session.calls == 0


def test_search_network_failure_is_returned_not_raised():
    out = fr_tools.search_documents("ai", session=RaisingSession(TimeoutError("read timed out")))
    assert out["error"] == "upstream_error"
    assert "TimeoutError" in out["detail"]


def test_search_http_error_is_returned_not_raised():
    class Down:
        def get(self, *a, **k):
            return FakeResponse(503, None)

    out = fr_tools.search_documents("ai", session=Down())
    assert out["error"] == "upstream_error" and "503" in out["detail"]


# ---------------------------------------------------------------- one document
def test_get_document_replays_recorded_request():
    record = load_fixture("document_detail.json")
    number = record["body"]["document_number"]
    session = ReplaySession("document_detail.json")
    out = fr_tools.get_document(number, session=session)
    assert out["document_number"] == number
    assert out["html_url"] == record["body"]["html_url"]
    assert out["pdf_url"] == record["body"]["pdf_url"]
    assert out["agencies"] == [a["name"] for a in record["body"]["agencies"]]
    assert out["abstract"] is None or len(out["abstract"]) <= fr_tools.ABSTRACT_CHARS_DETAIL
    assert session.calls[0]["url"].endswith(f"/documents/{number}.json")
    # lists are returned whole (the first version cut both to five and said nothing)
    assert len(out["cfr_references"]) == out["cfr_references_total"] == len(record["body"]["cfr_references"]) == 6
    assert out["docket_ids"] == record["body"]["docket_ids"] and out["docket_ids_total"] == 1
    assert out["citation"] == record["body"]["citation"] and "truncated" not in out


def test_get_document_not_found_uses_recorded_404():
    session = ReplaySession("document_not_found.json")
    out = fr_tools.get_document("0000-00000", session=session)
    assert out == {
        "error": "not_found",
        "document_number": "0000-00000",
        "detail": "The Federal Register API has no document with this number.",
    }


@pytest.mark.parametrize("bad", ["", " ", "2026/19964", "../agencies", "2026-19964.json", "x" * 41, 202619964, None])
def test_get_document_rejects_bad_numbers_before_any_request(bad):
    session = RaisingSession(AssertionError("no request should be made"))
    with pytest.raises(ToolInputError):
        fr_tools.get_document(bad, session=session)
    assert session.calls == 0


def test_get_document_network_failure_is_returned_not_raised():
    out = fr_tools.get_document("2026-19964", session=RaisingSession(ConnectionError("refused")))
    assert out["error"] == "upstream_error" and out["document_number"] == "2026-19964"


def test_default_session_is_blocked_by_the_offline_guard():
    """Proves the guard works: with no session injected the tool tries the network and is refused,
    at the name lookup, before anything leaves this machine (round 4)."""
    out = fr_tools.search_documents("ai")
    assert out["error"] == "upstream_error"
    assert "NetworkBlocked" in out["detail"] or "a test tried to" in out["detail"], out["detail"]


# ------------------------------------------------------------------ review minors 7 and 8
def test_a_400_keeps_the_reason_the_api_gave():
    """Seen live on 2026-10-07: slug 'epa' returns 400 and {"errors": {"agencies": "invalid value"}}."""

    class One:
        def get(self, *args, **kwargs):
            return FakeResponse(400, {"errors": {"agencies": "invalid value"}})

    out = fr_tools.search_documents("clean air", agencies=["epa"], session=One())
    assert out["error"] == "upstream_error"
    assert out["detail"].startswith("HTTP 400 from the Federal Register API")
    assert "agencies" in out["detail"] and "invalid value" in out["detail"]


def test_last_n_days_computes_the_range_in_code():
    import datetime as dt

    today = dt.date(2026, 10, 7)
    params = dict(fr_tools.build_search_params("ai", last_n_days=30, today=today))
    assert params["conditions[publication_date][gte]"] == "2026-09-07"
    assert params["conditions[publication_date][lte]"] == "2026-10-07"
    # across a month end and a leap day
    assert fr_tools.resolve_dates(None, None, 1, dt.date(2028, 3, 1))[:2] == ("2028-02-29", "2028-03-01")


def test_last_n_days_wins_over_dates_the_model_also_sent_and_says_so():
    import datetime as dt

    d_from, d_to, note = fr_tools.resolve_dates("2020-01-01", "2020-12-31", 14, dt.date(2026, 10, 7))
    assert (d_from, d_to) == ("2026-09-23", "2026-10-07")
    assert "ignored" in note


def test_last_n_days_reads_the_clock_per_call_when_no_date_is_passed():
    import datetime as dt

    d_from, d_to, _ = fr_tools.resolve_dates(None, None, 7)
    assert d_to == dt.date.today().isoformat()
    assert d_from == (dt.date.today() - dt.timedelta(days=7)).isoformat()


@pytest.mark.parametrize("bad", [0, -3, 3661, 2.5, "30", True])
def test_last_n_days_rejects_bad_values_before_any_request(bad):
    session = RaisingSession(AssertionError("no request expected"))
    with pytest.raises(ToolInputError):
        fr_tools.search_documents("ai", last_n_days=bad, session=session)
    assert session.calls == 0
