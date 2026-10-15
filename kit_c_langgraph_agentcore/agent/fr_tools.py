"""Two plain functions over the public Federal Register API.

No key is needed. Documentation for the API:
https://www.federalregister.gov/developers/documentation/api/v1

Design rules for both functions:
- inputs are validated before any network call (ToolInputError on bad input);
- every request has a connect and a read timeout and a descriptive User-Agent;
- results are capped and long text is cut, so a tool result stays small. Nothing
  is cut silently: a cut text field ends in TRUNCATION_MARK and is named under
  the key "truncated" with the characters shown and the characters there were,
  and a cut list carries its full length next to it;
- network and HTTP failures come back as a dict with an "error" key, they do
  not raise, so the model can read the failure and say so;
- a response that does not have the fields the API documents is a failure too
  (review round 2, findings F5 and F6): HTTP 200 with an unexpected body is
  never read as "nothing found" and never as a returned document;
- a search result says what its total is (rehearsal on real model text, round 3,
  2026-10-07): "count" is the number of documents that match the search words,
  not the number about a topic, and each result carries a count made by code of
  how many of the search words stand in its title and in its abstract
  (search_word_report). That count is arithmetic on words. It is not a judgement
  of relevance, and nothing in this file makes one.

These functions know nothing about LangChain or AWS. agent/graph.py wraps them.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from typing import Any, Iterable

BASE_URL = "https://www.federalregister.gov/api/v1"
USER_AGENT = "aws-kits-kit-c/0.1 (personal learning project; python-requests)"
CONNECT_TIMEOUT_S = 5
READ_TIMEOUT_S = 15

DEFAULT_LIMIT = 5
MAX_LIMIT = 10
MAX_TERM_CHARS = 200
MAX_AGENCIES = 5
MAX_LAST_N_DAYS = 3660
# In 200 live records read on 2026-10-07 (100 rules, 100 notices) the median abstract was 465
# characters and the longest 2,023. The first two versions of this tool kept 400 characters of
# an abstract in a search result, which cut 112 of the 200; a cut field is no source for the
# answer check, so an honest summary of most abstracts drew a warning. At 1,500 characters 3 of
# the 200 are cut. The cost is input tokens: about 160 more characters per document on average.
ABSTRACT_CHARS_SEARCH = 1500
ABSTRACT_CHARS_DETAIL = 1500
# Longest title in 200 live records read on 2026-10-07 was 490 characters (5 were over 300).
TITLE_CHARS = 600
ACTION_CHARS = 200
DATES_CHARS = 400
# The short fields. Real values are far below these. Measured on 2026-10-07 in the four
# recorded fixtures and the 30 stored tool results of the rehearsal: the longest URL had 164
# characters, the longest agency name 54, the longest type 21, citation 11 and docket id 34.
SHORT_CHARS = 80
URL_CHARS = 600
AGENCY_CHARS = 200
# The recorded document in tests/fixtures has six CFR parts; the first version of this tool
# returned five and said nothing. Lists are now returned whole up to these caps, and a cut
# list carries its full length (cfr_references_total, docket_ids_total).
MAX_CFR_REFERENCES = 50
MAX_DOCKET_IDS = 20
TRUNCATION_MARK = "[TRUNCATED]"
# Seen live on 2026-10-07: two broad searches both reported a count of exactly 10000, which
# looks like a ceiling in the API, not a total. UNVERIFIED: the API documentation does not
# state a ceiling. A count equal to this figure is passed on with a note that says so.
API_COUNT_CEILING_SEEN = 10000

# Words of a search term that are left out when its words are counted in a title or an
# abstract (search_word_report). A fixed list; the README repeats it.
SEARCH_STOP_WORDS = ("a", "about", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on",
                     "or", "the", "to", "with")
# Fixed words that go into every search result, for the model to read. Seen in the rehearsal on
# real model text (round 3): a model wrote "EPA published 31 proposed rules about air quality
# implementation plans" from a total of 31 keyword matches, several of them on other subjects.
COUNT_MEANS = (
    "count is the number of documents that match the search words. It is not the number of "
    "documents about the topic: a document can match on words anywhere in its text. The results "
    "were not checked for relevance.")
SEARCH_WORDS_NOTE = (
    "search_words_in_title and search_words_in_abstract are counted by code, not judged: how many "
    "words of the term (leaving out " + ", ".join(SEARCH_STOP_WORDS) + ") stand in that text as "
    "whole words, ignoring upper and lower case and a final s. Read the title and the abstract of "
    "a document before you present it as an answer.")

# The API's own document type codes.
DOC_TYPES = {
    "RULE": "Rule",
    "PRORULE": "Proposed Rule",
    "NOTICE": "Notice",
    "PRESDOCU": "Presidential Document",
}
_TYPE_ALIASES = {
    "rule": "RULE",
    "final rule": "RULE",
    "final rules": "RULE",
    "rules": "RULE",
    "proposed rule": "PRORULE",
    "proposed rules": "PRORULE",
    "prorule": "PRORULE",
    "notice": "NOTICE",
    "notices": "NOTICE",
    "presidential document": "PRESDOCU",
    "presidential documents": "PRESDOCU",
    "presdocu": "PRESDOCU",
}

_AGENCY_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DOC_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{1,39}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SEARCH_FIELDS = (
    "document_number",
    "title",
    "type",
    "publication_date",
    "html_url",
    "agencies",
    "abstract",
)
DETAIL_FIELDS = (
    "document_number",
    "title",
    "type",
    "action",
    "publication_date",
    "effective_on",
    "comments_close_on",
    "dates",
    "html_url",
    "pdf_url",
    "citation",
    "agencies",
    "docket_ids",
    "cfr_references",
    "page_length",
    "abstract",
)


class ToolInputError(ValueError):
    """Raised when a tool argument fails validation. No network call was made."""


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def _clean_term(term: Any) -> str:
    if not isinstance(term, str):
        raise ToolInputError("term must be a string")
    term = " ".join(term.split())
    if not term:
        raise ToolInputError("term must not be empty")
    if len(term) > MAX_TERM_CHARS:
        raise ToolInputError(f"term must be at most {MAX_TERM_CHARS} characters")
    return term


def _clean_agencies(agencies: Any) -> list[str]:
    if agencies is None or agencies == "":
        return []
    if isinstance(agencies, str):
        agencies = [agencies]
    if not isinstance(agencies, Iterable):
        raise ToolInputError("agencies must be a list of agency slugs")
    out: list[str] = []
    for a in agencies:
        if not isinstance(a, str) or not _AGENCY_SLUG_RE.match(a.strip()):
            raise ToolInputError(
                "each agency must be a Federal Register agency slug in lower case "
                "with hyphens, for example 'commerce-department'"
            )
        if a.strip() not in out:
            out.append(a.strip())
    if len(out) > MAX_AGENCIES:
        raise ToolInputError(f"at most {MAX_AGENCIES} agencies per search")
    return out


def _clean_type(doc_type: Any) -> str | None:
    if doc_type is None or doc_type == "":
        return None
    if not isinstance(doc_type, str):
        raise ToolInputError("doc_type must be a string")
    key = doc_type.strip()
    if key.upper() in DOC_TYPES:
        return key.upper()
    alias = _TYPE_ALIASES.get(key.lower())
    if alias:
        return alias
    raise ToolInputError(
        "doc_type must be one of RULE, PRORULE, NOTICE, PRESDOCU "
        "(RULE means a final rule, PRORULE a proposed rule)"
    )


def _clean_date(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise ToolInputError(f"{name} must be a date in YYYY-MM-DD form")
    value = value.strip()
    try:
        _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ToolInputError(f"{name} is not a real calendar date: {value}") from exc
    return value


def _clean_limit(limit: Any) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ToolInputError("limit must be a whole number")
    if limit < 1:
        raise ToolInputError("limit must be at least 1")
    return min(limit, MAX_LIMIT)


def _clean_last_n_days(last_n_days: Any) -> int | None:
    if last_n_days is None or last_n_days == "":
        return None
    if isinstance(last_n_days, bool) or not isinstance(last_n_days, int):
        raise ToolInputError("last_n_days must be a whole number of days")
    if not 1 <= last_n_days <= MAX_LAST_N_DAYS:
        raise ToolInputError(f"last_n_days must be between 1 and {MAX_LAST_N_DAYS}")
    return last_n_days


def resolve_dates(date_from: Any, date_to: Any, last_n_days: Any,
                  today: _dt.date | None = None) -> tuple[str | None, str | None, str | None]:
    """Return (date_from, date_to, note).

    With last_n_days the range is computed here, in code, from today's date:
    today minus N days up to today, both ends included, the same arithmetic the
    fixture recorder uses. The model is not trusted to do date arithmetic, and
    any date_from or date_to it also sent is ignored and said to be ignored.
    The clock is read on each call, never at import time. It is the local date
    of the machine that runs the tool (UTC on AgentCore Runtime), which can be
    one day ahead of the date in Washington late in the evening.
    """
    n = _clean_last_n_days(last_n_days)
    d_from = _clean_date(date_from, "date_from")
    d_to = _clean_date(date_to, "date_to")
    if n is None:
        if d_from and d_to and d_from > d_to:
            raise ToolInputError("date_from must not be after date_to")
        return d_from, d_to, None
    today = today or _dt.date.today()
    note = f"dates computed in code: the last {n} day(s) up to {today.isoformat()}"
    if d_from or d_to:
        note += "; the date_from and date_to that were also sent were ignored"
    return (today - _dt.timedelta(days=n)).isoformat(), today.isoformat(), note


def _clean_document_number(document_number: Any) -> str:
    if not isinstance(document_number, str):
        raise ToolInputError("document_number must be a string such as '2026-19964'")
    value = document_number.strip()
    if not _DOC_NUMBER_RE.match(value):
        raise ToolInputError(
            "document_number may contain only letters, digits and hyphens, "
            "for example '2026-19964'"
        )
    return value


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def _default_session():
    import requests  # imported here so validation can be tested without it

    return requests.Session()


def _get_json(url: str, params: list[tuple[str, str]], session: Any) -> tuple[int, Any]:
    """One GET. Returns (status_code, parsed_json_or_None). Raises only requests errors."""
    session = session or _default_session()
    resp = session.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S),
    )
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


def _one_line(text: str) -> str:
    """A text on one line: control characters (an ESC, a NUL) become spaces and every run of
    whitespace, line breaks of every kind included, becomes one space."""
    return " ".join("".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in text).split())


def _truncate(text: Any, limit: int) -> str | None:
    """Collapse whitespace and cut to `limit` characters with a plain "..." (error details and
    names only)."""
    if not isinstance(text, str):
        return None
    text = _one_line(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _cut(text: Any, limit: int, name: str, truncated: dict) -> str | None:
    """Collapse whitespace; when the text is longer than `limit`, cut it at a space, end it
    with TRUNCATION_MARK and record the field under `name` in `truncated`.

    The cut is made at a space so that no word or number is left as a stump. agent/graph.py
    never treats a number from a truncated field as returned by a tool, whole or not.
    """
    if not isinstance(text, str):
        return None
    text = _one_line(text)
    if len(text) <= limit:
        return text
    room = max(limit - len(TRUNCATION_MARK) - 1, 0)  # the mark counts towards the limit
    head = text[:room]
    if not text[room].isspace():  # the cut fell inside a word: drop the stump
        head = head[: head.rfind(" ")] if " " in head else ""
    head = head.rstrip()
    truncated[name] = {"characters_shown": len(head), "characters_in_full_text": len(text)}
    return (head + " " + TRUNCATION_MARK).strip()


def _short(value: Any, limit: int, name: str, truncated: dict) -> Any:
    """A short field (type, a date, a URL, a citation) as it is returned: a string goes on one
    line, without control characters, and is cut and marked when it is longer than any real
    value of that field. Anything that is not a string is returned as it came. Until review
    round 4 these fields were copied as the API sent them, so a line break in one of them put a
    new line into the block that code builds, and 100,000 characters were printed whole (m6)."""
    return _cut(value, limit, name, truncated) if isinstance(value, str) else value


def _agency_names(agencies: Any) -> list[str]:
    names: list[str] = []
    for a in agencies if isinstance(agencies, (list, tuple)) else []:
        if isinstance(a, dict):
            name = a.get("name") or a.get("raw_name")
            if isinstance(name, str):
                name = _truncate(name, AGENCY_CHARS)
            if name and name not in names:
                names.append(name)
    return names


def _upstream_error(detail: str, **extra: Any) -> dict:
    out = {"error": "upstream_error", "detail": detail}
    out.update(extra)
    return out


def _http_error_detail(status: int, body: Any) -> str:
    """'HTTP 400 from the Federal Register API', plus the reason the API gave when it gave one.

    Seen live on 2026-10-07: an unknown agency slug returns HTTP 400 with the body
    {"errors": {"agencies": "invalid value"}}. Without that text the model sees only a number.
    """
    detail = f"HTTP {status} from the Federal Register API"
    if status == 200 and not isinstance(body, dict):
        # review round 4, m11: the detail used to stop at "HTTP 200", which reads like success
        return (detail + ", but the body could not be read as a JSON object. This is a failure, "
                "not an empty result")
    reason = body.get("errors") if isinstance(body, dict) else None
    if reason:
        if not isinstance(reason, str):
            reason = json.dumps(reason, ensure_ascii=False, sort_keys=True)
        detail += f"; the API said: {_truncate(reason, 300)}"
    return detail


# --------------------------------------------------------------------------
# search words in a title or an abstract: a count, not a judgement
# --------------------------------------------------------------------------
_WORD = re.compile(r"[^\W_]+")


def _word_stem(word: str) -> str:
    """Lower case, and without one final s when the word has more than three letters."""
    word = word.lower()
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def search_content_words(term: Any) -> list[str]:
    """The words of a search term that are counted: the term split at everything that is not a
    letter or a digit, lower case, without SEARCH_STOP_WORDS, each word once, in order."""
    words: list[str] = []
    for word in _WORD.findall(term if isinstance(term, str) else ""):
        word = word.lower()
        if word not in SEARCH_STOP_WORDS and word not in words:
            words.append(word)
    return words


def search_words_missing(words: list[str], text: Any) -> list[str]:
    """Those of `words` that do not stand in `text` as a whole word (compared by _word_stem)."""
    if not isinstance(text, str):
        return list(words)
    present = {_word_stem(word) for word in _WORD.findall(text.replace(TRUNCATION_MARK, " "))}
    return [word for word in words if _word_stem(word) not in present]


def search_word_report(term: Any, text: Any, cut: bool = False, what: str = "text") -> str:
    """One line: how many of the term's words stand in `text`, and which do not.

    "2 of 4 (not found: implementation, plans)", "4 of 4", "0 of 1 (not found: cybersecurity)",
    "no abstract was returned". With cut=True the line says the count covers the part shown.
    The rule is the whole of it: whole words, any letter case, a final s ignored. A document
    whose title holds every search word can still be about something else, and one that holds
    none can be what was asked for.
    """
    words = search_content_words(term)
    if not words:
        return "the search term has no words to count"
    if not isinstance(text, str) or not text.replace(TRUNCATION_MARK, " ").strip():
        return f"no {what} was returned"
    missing = search_words_missing(words, text)
    line = f"{len(words) - len(missing)} of {len(words)}"
    if cut:
        line += " in the part shown"
    if missing:
        line += f" (not found: {', '.join(missing)})"
    return line


# --------------------------------------------------------------------------
# tool 1: search
# --------------------------------------------------------------------------
def build_search_params(
    term: str,
    agencies: list[str] | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    *,
    last_n_days: int | None = None,
    today: _dt.date | None = None,
) -> list[tuple[str, str]]:
    """Validate the arguments and return the exact query parameters to send."""
    term = _clean_term(term)
    agency_list = _clean_agencies(agencies)
    type_code = _clean_type(doc_type)
    d_from, d_to, _ = resolve_dates(date_from, date_to, last_n_days, today)
    n = _clean_limit(limit)

    params: list[tuple[str, str]] = [
        ("per_page", str(n)),
        ("order", "newest"),
        ("conditions[term]", term),
    ]
    for slug in agency_list:
        params.append(("conditions[agencies][]", slug))
    if type_code:
        params.append(("conditions[type][]", type_code))
    if d_from:
        params.append(("conditions[publication_date][gte]", d_from))
    if d_to:
        params.append(("conditions[publication_date][lte]", d_to))
    for f in SEARCH_FIELDS:
        params.append(("fields[]", f))
    return params


def search_documents(
    term: str,
    agencies: list[str] | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    *,
    last_n_days: int | None = None,
    today: _dt.date | None = None,
    session: Any = None,
) -> dict:
    """Search Federal Register documents. Returns a small dict, never raw API output.

    Keys on success: query (the request as sent, with the dates that were used),
    count (total matches as the API reported it; count_note when that figure looks
    like the API's ceiling), count_means (fixed words: a count of matches, not of
    documents about a topic), returned, results (list of dicts; a result whose title
    or abstract was cut says so under "truncated"; each carries search_words_in_title
    and search_words_in_abstract from search_word_report), search_words_note (fixed
    words: how those two are counted), and note when nothing matched or when more
    matched than were returned.
    last_n_days: the date range is computed in code from today's date; see resolve_dates.
    """
    today = today or _dt.date.today()  # read once, so the echo and the request agree
    d_from, d_to, date_note = resolve_dates(date_from, date_to, last_n_days, today)
    params = build_search_params(term, agencies, doc_type, date_from, date_to, limit,
                                 last_n_days=last_n_days, today=today)
    query = {
        "term": _clean_term(term),
        "agencies": _clean_agencies(agencies),
        "doc_type": _clean_type(doc_type),
        "date_from": d_from,
        "date_to": d_to,
        "limit": _clean_limit(limit),
    }
    if date_note:
        query["last_n_days"] = last_n_days
        query["date_note"] = date_note
    try:
        status, body = _get_json(f"{BASE_URL}/documents.json", params, session)
    except Exception as exc:  # requests.RequestException and friends
        return _upstream_error(f"{type(exc).__name__}: {exc}", query=query)
    if status != 200 or not isinstance(body, dict):
        return _upstream_error(_http_error_detail(status, body), query=query)
    problem = _search_shape_problem(body)
    if problem:
        return _upstream_error(
            "HTTP 200 from the Federal Register API, but the response does not have the "
            f"expected fields: {problem}. This is a failure, not an empty result.", query=query)

    count = body["count"]
    results = []
    for doc in (body.get("results") or [])[: query["limit"]]:
        truncated: dict = {}
        entry = {
            "document_number": doc["document_number"].strip(),
            "title": _cut(doc.get("title"), TITLE_CHARS, "title", truncated),
            "type": _short(doc.get("type"), SHORT_CHARS, "type", truncated),
            "publication_date": _short(doc.get("publication_date"), SHORT_CHARS, "publication_date", truncated),
            "agencies": _agency_names(doc.get("agencies")),
            "html_url": _short(doc.get("html_url"), URL_CHARS, "html_url", truncated),
            "abstract": _cut(doc.get("abstract"), ABSTRACT_CHARS_SEARCH, "abstract", truncated),
        }
        entry["search_words_in_title"] = search_word_report(
            query["term"], entry["title"], "title" in truncated, "title")
        entry["search_words_in_abstract"] = search_word_report(
            query["term"], entry["abstract"], "abstract" in truncated, "abstract")
        if truncated:
            entry["truncated"] = truncated
        results.append(entry)
    out: dict = {"query": query, "count": count, "count_means": COUNT_MEANS, "returned": len(results),
                 "results": results}
    if results:
        out["search_words_note"] = SEARCH_WORDS_NOTE
    if count == API_COUNT_CEILING_SEEN:
        out["count_note"] = (
            f"{count} is the figure the API reported. It equals the largest count this API has "
            "been seen to report, so the true number of matches may be higher.")
    if not results:
        out["note"] = ("No Federal Register documents matched this search. That is about these search "
                       "words: a document on the topic that uses other words would not match.")
    elif count > len(results):
        out["note"] = (
            f"Showing the {len(results)} newest of {count} matches (the API's figure). "
            "Narrow the dates or the term to see others."
        )
    return out


def _search_shape_problem(body: dict) -> str | None:
    """Why this HTTP 200 body is not a search response, or None when it is one.

    The API's shape, as recorded in tests/fixtures: an integer "count"; when the count is 0
    there is no "results" key at all; otherwise "results" is a list of objects that each
    carry a "document_number" string.
    """
    count = body.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return 'there is no whole-number "count"'
    results = body.get("results")
    if count == 0:
        if results:
            return 'the "count" is 0 but "results" is not empty'
        return None
    if not isinstance(results, list):
        return f'the "count" is {count} but there is no "results" list'
    if not results:
        return f'the "count" is {count} but the "results" list is empty'
    if count < len(results):
        return f'the "count" is {count} but the "results" list holds {len(results)} documents'
    for doc in results:
        if not isinstance(doc, dict):
            return 'an entry of "results" is not an object'
        number = doc.get("document_number")
        if not isinstance(number, str) or not _DOC_NUMBER_RE.match(number.strip()):
            return 'an entry of "results" has no usable "document_number"'
    return None


# --------------------------------------------------------------------------
# tool 2: one document
# --------------------------------------------------------------------------
def get_document(document_number: str, *, session: Any = None) -> dict:
    """Fetch one Federal Register document by its document number."""
    number = _clean_document_number(document_number)
    params = [("fields[]", f) for f in DETAIL_FIELDS]
    try:
        status, body = _get_json(f"{BASE_URL}/documents/{number}.json", params, session)
    except Exception as exc:
        return _upstream_error(f"{type(exc).__name__}: {exc}", document_number=number)
    if status == 404:
        return {
            "error": "not_found",
            "document_number": number,
            "detail": "The Federal Register API has no document with this number.",
        }
    if status != 200 or not isinstance(body, dict):
        return _upstream_error(_http_error_detail(status, body), document_number=number)
    returned_number = body.get("document_number")
    if not isinstance(returned_number, str) or not returned_number.strip():
        # Never fall back to the number that was asked for: that would turn the model's own
        # input into "a document the Federal Register returned" (review round 2, F5).
        return _upstream_error(
            "HTTP 200 from the Federal Register API, but the response has no "
            '"document_number", so it is not a document. This is a failure, not a result.',
            document_number=number)
    returned_number = returned_number.strip()
    if returned_number.upper() != number.upper():
        return _upstream_error(
            f"the Federal Register API answered a request for {number} with document "
            f"{_truncate(returned_number, 40)}. Treated as a failure.", document_number=number)
    all_cfr = [ref for ref in (body.get("cfr_references") or []) if isinstance(ref, dict)]
    cfr = [{"title": ref.get("title"), "part": ref.get("part")} for ref in all_cfr[:MAX_CFR_REFERENCES]]
    all_dockets = [_truncate(d, AGENCY_CHARS) for d in (body.get("docket_ids") or []) if isinstance(d, str)]
    truncated: dict = {}
    out = {
        "document_number": returned_number,
        "title": _cut(body.get("title"), TITLE_CHARS, "title", truncated),
        "type": _short(body.get("type"), SHORT_CHARS, "type", truncated),
        "action": _cut(body.get("action"), ACTION_CHARS, "action", truncated),
        "publication_date": _short(body.get("publication_date"), SHORT_CHARS, "publication_date", truncated),
        "effective_on": _short(body.get("effective_on"), SHORT_CHARS, "effective_on", truncated),
        "comments_close_on": _short(body.get("comments_close_on"), SHORT_CHARS, "comments_close_on", truncated),
        "dates": _cut(body.get("dates"), DATES_CHARS, "dates", truncated),
        "agencies": _agency_names(body.get("agencies")),
        "citation": _short(body.get("citation"), SHORT_CHARS, "citation", truncated),
        "docket_ids": all_dockets[:MAX_DOCKET_IDS],
        "docket_ids_total": len(all_dockets),
        "cfr_references": cfr,
        "cfr_references_total": len(all_cfr),
        "page_length": body.get("page_length"),
        "html_url": _short(body.get("html_url"), URL_CHARS, "html_url", truncated),
        "pdf_url": _short(body.get("pdf_url"), URL_CHARS, "pdf_url", truncated),
        "abstract": _cut(body.get("abstract"), ABSTRACT_CHARS_DETAIL, "abstract", truncated),
    }
    notes = []
    if len(all_cfr) > len(cfr):
        notes.append(f"cfr_references shows the first {len(cfr)} of {len(all_cfr)} CFR parts")
    if len(all_dockets) > MAX_DOCKET_IDS:
        notes.append(f"docket_ids shows the first {MAX_DOCKET_IDS} of {len(all_dockets)} docket ids")
    if notes:
        out["note"] = "; ".join(notes) + "."
    if truncated:
        out["truncated"] = truncated
    return out
