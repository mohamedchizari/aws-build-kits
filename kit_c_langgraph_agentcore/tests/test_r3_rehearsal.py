"""Round 3, 2026-10-07: what changed after the answer check was run on text written by real
language models (Claude Haiku and Claude Sonnet as stand-ins; 30 questions, 60 answers; a blind
reader labelled each answer).

What the rehearsal showed, and what these tests pin:
  1. The commonest real error is not an invented number. It is a search TOTAL given as a count
     of documents on a topic ("EPA published 31 proposed rules about air quality implementation
     plans"), or a returned document presented as the thing asked for. The first now gets a
     warning in the wordings a rule can see; the second is still not checked, and the last
     tests here pin that so nobody reads the check as more than it is.
  2. Ten of the 33 answers the reader called clean were warned or replaced. The rules behind
     nine of them are changed here: dates of a search as sent, dates the question gives in
     words, counts that equal a tool figure, a number the user asked about whose lookup
     failed, docket ids from the docket_ids field, and "names none of the documents" on an
     answer to "how many". The sentences marked REAL below are quoted from those 60 answers.

Offline: scripted model, canned Federal Register responses.
"""
from __future__ import annotations

import datetime as dt

import pytest
from conftest import FakeResponse, load_fixture
from langchain_core.messages import AIMessage

from agent import fr_tools
from agent import graph as g
from agent.fake_model import ScriptedChatModel, tool_call

TODAY = dt.date(2026, 10, 7)
REAL = "2026-19964"
REAL_2 = "2026-19071"
BASE = load_fixture("search_ai_rules.json")["body"]
DETAIL = load_fixture("document_detail.json")["body"]


class Session:
    """Stands in for requests.Session. searches are answered in order and the last repeats."""

    def __init__(self, searches=None, docs=None):
        self.searches = list(searches or [])
        self.docs = dict(docs or {})

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/documents.json"):
            item = self.searches.pop(0) if len(self.searches) > 1 else self.searches[0]
        else:
            item = self.docs.get(url.rsplit("/", 1)[1][: -len(".json")], (404, None))
        return FakeResponse(*item)


def S(term="lithium batteries", **kwargs):
    return tool_call("search_federal_register", {"term": term, **kwargs})


def L(number):
    return tool_call("get_federal_register_document", {"document_number": number})


def A(text):
    return AIMessage(content=text)


def doc(number, title, abstract, agency="Energy Department", date="2026-09-30"):
    return {"abstract": abstract, "document_number": number, "title": title, "type": "Rule",
            "publication_date": date, "agencies": [{"name": agency, "raw_name": agency.upper()}],
            "html_url": f"https://www.federalregister.gov/documents/{date.replace('-', '/')}/{number}/slug"}


def body(*docs, count=None):
    return {"count": len(docs) if count is None else count, "results": list(docs)}


def detail(base, **more):
    out = dict(base, action="Final rule.", effective_on=None, comments_close_on=None, dates=None,
               pdf_url=None, citation=None, docket_ids=[], cfr_references=[], page_length=None)
    out.update(more)
    return out


HM = doc("2026-21011", "Hazardous Materials: Harmonization With International Standards",
         "PHMSA is aligning its rules for lithium batteries. It supersedes the rule published on May 31, 2022, "
         "and the guidance of June 2025.", "Pipeline and Hazardous Materials Safety Administration", "2026-10-06")
GV = doc("2026-20944", "Special Conditions: Gulfstream GVIII Airplanes; Lithium Battery Installations",
         "Special conditions for rechargeable lithium batteries.", "Federal Aviation Administration", "2026-10-05")
PS = doc("2026-20871", "Mailing Standards for Lithium Batteries", "Publication 52 is revised.", "Postal Service",
         "2026-10-02")
FL = doc("2026-20802", "Fisheries of the Northeastern United States; Summer Flounder Quota Transfer",
         "NMFS announces a quota transfer.", "National Oceanic and Atmospheric Administration", "2026-10-01")
EB = doc("2026-20760", "Safety Standard for Lithium-Ion Batteries Used in E-Bikes",
         "A safety standard for lithium-ion batteries.", "Consumer Product Safety Commission", "2026-09-30")
FIVE = [HM, GV, PS, FL, EB]
NUMS = "2026-21011, 2026-20944, 2026-20871, 2026-20802 and 2026-20760"
SEC = doc("2026-20990", "Adoption of Updated Filer Manual", "Amendments to the Filer Manual.",
          "Securities and Exchange Commission", "2026-10-06")
SEC_DETAIL = detail(SEC, citation="91 FR 63900", page_length=3, effective_on="2026-10-06",
                    docket_ids=["Release Nos. 33-11500", "34-106500", "IC-36400"],
                    cfr_references=[{"title": 17, "part": "232"}])
HM_DETAIL = detail(HM, citation="91 FR 63811", page_length=41, effective_on="2026-11-06",
                   docket_ids=["Docket No. PHMSA-2025-0107 (HM-215R)"])
LOOKUPS = {"2026-20990": (200, SEC_DETAIL), "2026-21011": (200, HM_DETAIL)}
Q30 = "What final rules on lithium batteries were published in the last 30 days?"


def cut(count=57):
    """A search that returned 5 documents of `count` matches."""
    return Session([(200, body(*FIVE, count=count))])


def ask(script, session, question=Q30):
    graph = g.build_graph(ScriptedChatModel(responses=list(script)), g.build_tools(session=session, today=TODAY))
    return g.run_question(graph, question, today=TODAY)


def S30():
    return S(doc_type="RULE", limit=5, last_n_days=30)


# ================================================================== the tool: what a total is, and a word count
def test_a_search_result_says_in_fixed_words_what_its_total_counts():
    out = fr_tools.search_documents("lithium batteries", session=cut())
    assert out["count"] == 57 and out["returned"] == 5
    assert out["count_means"] == fr_tools.COUNT_MEANS
    assert "match the search words" in out["count_means"] and "not the number of documents about the topic" in out["count_means"]
    assert "not checked for relevance" in out["count_means"]
    assert out["search_words_note"] == fr_tools.SEARCH_WORDS_NOTE and "counted by code, not judged" in out["search_words_note"]
    for word in fr_tools.SEARCH_STOP_WORDS:   # the note names every word that is left out
        assert f" {word}," in out["search_words_note"] or f" {word})" in out["search_words_note"]


def test_an_empty_search_says_it_is_about_the_words_not_the_topic():
    out = fr_tools.search_documents("lithium batteries", session=Session([(200, {"count": 0})]))
    assert out["count"] == 0 and "search_words_note" not in out and out["count_means"] == fr_tools.COUNT_MEANS
    assert out["note"].startswith("No Federal Register documents matched this search.")
    assert "a document on the topic that uses other words would not match" in out["note"]


@pytest.mark.parametrize("term, expected", [
    ("air quality implementation plans", ["air", "quality", "implementation", "plans"]),
    ('"guidance for industry"', ["guidance", "industry"]),                  # quotation marks and "for" go
    ("Lithium-Ion battery  battery", ["lithium", "ion", "battery"]),        # split at the hyphen, each word once
    ("the of and", []),
])
def test_the_words_of_a_search_term_that_are_counted(term, expected):
    assert fr_tools.search_content_words(term) == expected


@pytest.mark.parametrize("term, text, cut_short, expected", [
    ("air quality implementation plans", "Initial Air Quality Designations", False,
     "2 of 4 (not found: implementation, plans)"),
    ("safety zone", "Security Zone; Patapsco River, Baltimore, MD", False, "1 of 2 (not found: safety)"),
    ("safety zones", "Safety Zone; Illinois River", False, "2 of 2"),                       # a final s is ignored
    ("cybersecurity", "Transparency in Coverage", False, "0 of 1 (not found: cybersecurity)"),
    ("zone", "Rezoned areas and zoning", False, "0 of 1 (not found: zone)"),                # whole words only
    ("endangered species", "Species at risk " + fr_tools.TRUNCATION_MARK, True,
     "1 of 2 in the part shown (not found: endangered)"),
    ("truncated", "A title " + fr_tools.TRUNCATION_MARK, True, "0 of 1 in the part shown (not found: truncated)"),
    ("medicare", None, False, "no abstract was returned"),
    ("medicare", "   ", False, "no abstract was returned"),
    ("of the", "Anything", False, "the search term has no words to count"),
])
def test_the_word_count_is_arithmetic_on_words_and_says_so(term, text, cut_short, expected):
    assert fr_tools.search_word_report(term, text, cut_short, "abstract") == expected


def test_every_search_result_carries_the_word_count_for_its_title_and_its_abstract():
    out = fr_tools.search_documents("lithium batteries", session=cut())
    by_number = {d["document_number"]: d for d in out["results"]}
    assert by_number["2026-20871"]["search_words_in_title"] == "2 of 2"
    assert by_number["2026-20802"]["search_words_in_title"] == "0 of 2 (not found: lithium, batteries)"
    assert by_number["2026-20802"]["search_words_in_abstract"] == "0 of 2 (not found: lithium, batteries)"
    assert by_number["2026-20760"]["search_words_in_title"] == "2 of 2"      # Lithium-Ion Batteries
    long_abstract = dict(FL, abstract="word " * fr_tools.ABSTRACT_CHARS_SEARCH)
    cut_one = fr_tools.search_documents("lithium batteries", session=Session([(200, body(long_abstract))]))["results"][0]
    assert cut_one["search_words_in_abstract"] == "0 of 2 in the part shown (not found: lithium, batteries)"


def test_the_word_count_fields_are_never_a_source_for_the_models_text():
    """They are written by code from the model's own search term. A number the model put into
    its term must not become "a number the tool returned" by way of them."""
    out = ask([S("docket 77123 lithium"), A("2026-21011 is in docket 77123.")], Session([(200, body(HM))]))
    assert out["unverified_numbers"] == ["77123"] and out["grounding"] == "warned"


# ================================================================== the block
def test_the_block_says_under_each_search_what_the_total_counts():
    out = ask([S30(), A(f"The search matched 57 final rules; the 5 newest are {NUMS}.")], cut())
    lines = out["block"].splitlines()
    total = next(i for i, line in enumerate(lines) if "The API reported 57 matching document(s) in total and returned 5." in line)
    assert lines[total + 1].strip() == g.MATCHES_NOT_TOPIC
    assert "match the search words, not documents about the topic" in g.MATCHES_NOT_TOPIC
    assert "not checked for relevance" in g.MATCHES_NOT_TOPIC


def test_the_block_counts_the_search_words_for_each_document_and_labels_the_count():
    out = ask([S30(), A(f"The search matched 57 final rules; the 5 newest are {NUMS}.")], cut())
    block = out["block"]
    assert block.count(g.SEARCH_WORDS_LEGEND) == 1
    assert "counts made by code, not judgements of relevance" in g.SEARCH_WORDS_LEGEND
    assert "A document can hold every search word and be about something else." in g.SEARCH_WORDS_LEGEND
    assert "leaving out " + ", ".join(fr_tools.SEARCH_STOP_WORDS) in g.SEARCH_WORDS_LEGEND
    lines = block.splitlines()
    flounder = next(i for i, line in enumerate(lines) if line.strip().startswith("4. 2026-20802 |"))
    assert ("Search words (search 1): in title: 0 of 2 (not found: lithium, batteries); "
            "in abstract: 0 of 2 (not found: lithium, batteries)") in lines[flounder + 3]
    mailing = next(i for i, line in enumerate(lines) if line.strip().startswith("3. 2026-20871 |"))
    assert ("Search words (search 1): in title: 2 of 2; in abstract: 0 of 2 (not found: lithium, batteries)"
            in lines[mailing + 3])                      # on topic by its title, 0 of 2 in its abstract
    assert block.count("Search words (search 1):") == 5


def test_a_document_that_two_searches_returned_is_counted_against_each_and_a_lookup_adds_no_line():
    session = Session([(200, body(HM, EB)), (200, body(EB))], {"2026-20990": (200, SEC_DETAIL)})
    out = ask([S("hazardous materials"), S("safety standard"), L("2026-20990"),
               A("2026-21011, 2026-20760 and 2026-20990.")], session, "x?")
    lines = out["block"].splitlines()
    ebike = next(i for i, line in enumerate(lines) if line.strip().startswith("2. 2026-20760 |"))
    assert "Search words (search 1): in title: 0 of 2" in lines[ebike + 3]
    assert "Search words (search 2): in title: 2 of 2" in lines[ebike + 4]
    sec = next(i for i, line in enumerate(lines) if line.strip().startswith("3. 2026-20990 |"))
    assert not any("Search words" in line for line in lines[sec:sec + 5])
    only_lookup = ask([L("2026-20990"), A("2026-20990.")], Session(docs=LOOKUPS), "x?")
    assert "Search words" not in only_lookup["block"] and g.MATCHES_NOT_TOPIC not in only_lookup["block"]


def test_the_no_results_text_says_a_zero_is_about_the_words():
    out = ask([S30(), A("Nothing was published on lithium batteries.")], Session([(200, {"count": 0})]))
    assert out["grounding"] == "replaced" and out["notes"] == []
    assert out["answer"].endswith("The API reported 0 matching documents.\n     " + g.ZERO_MATCHES_NOT_TOPIC)
    assert "Nothing was published" not in out["answer"]


# ================================================================== the prompt
def test_the_prompt_tells_the_model_what_a_total_is_and_what_may_be_called_the_newest():
    prompt = g.SYSTEM_PROMPT.format(today="2026-10-07")
    flat = " ".join(prompt.split())
    for needed in (
        '10. "count" is the number of documents that MATCH THE SEARCH WORDS.',
        'Always word a total as a count of matches: "N documents matched the search for X".',
        'not "the agency published N rules on X"',
        "11. Read the title and the abstract of every returned document before you list it.",
        "do not list it as an answer",
        '12. Write "the newest", "the most recent", "the latest" or "the" document on a subject only about a document '
        "whose own fields (type, title, abstract, action) show that it is the kind of document the question asked for.",
        "say what the search returned and that none of it clearly fits the question",
        '13. A comparison ("more than", "fewer than") or a "most" needs a figure that a tool returned for each side.',
        "do not say that nothing was published on the subject",
        "search_words_in_title and search_words_in_abstract only count words",
    ):
        assert needed in flat, needed
    assert "{" not in prompt and "}" not in prompt        # the only placeholder is the date
    assert "last_n_days=N" in prompt and "quotation marks" in prompt
    # the examples in the prompt carry no figure a small model could copy into an answer
    assert g.find_numbers(prompt.split("Rules:")[1])[0] == set()


def test_the_search_tools_description_says_what_count_is():
    tool = next(t for t in g.build_tools(session=cut()) if t.name == "search_federal_register")
    assert "number of documents that match the search words, not the number about a subject" in " ".join(tool.description.split())


def test_the_label_says_relevance_is_not_checked():
    assert "whether a document it lists is about what you asked" in g.SUMMARY_LABEL


# ================================================================== a search total given as a count of documents
TOTAL_MUST_WARN = [
    # REAL, Q07 Haiku, the answer the reader called misleading and the check passed
    ("EPA published 57 proposed rules about air quality implementation plans in the last 30 days. Showing the 5 newest:\n\n"
     f"{NUMS}", "57 proposed rules"),
    # REAL, Q10 Haiku
    (f"The FDA published 57 notices announcing guidance for industry in the last 30 days. Showing the 5 newest: {NUMS}",
     "57 notices"),
    # REAL, Q25 Haiku
    (f"Between September 7 and October 7, 2026, 57 Medicare-related notices were published (5 shown): {NUMS}",
     "57 medicare-related notices"),
    # REAL, Q04 Haiku (the reader called it minor, for this sentence)
    (f"The FAA published 57 airworthiness directive final rules in the last 30 days. Showing the 5 newest: {NUMS}",
     "57 airworthiness directive final rules"),
    (f"Fifty-seven final rules on lithium batteries were published. The 5 newest are {NUMS}.", "fifty-seven final rules"),
    (f"I ran a search. 57 final rules on lithium batteries were published. The 5 newest are {NUMS}.", "57 final rules"),
    ("57 final rules on lithium batteries were published:\n- 2026-21011 (matched the search)\n- 2026-20944\n"
     "- 2026-20871\n- 2026-20802\n- 2026-20760", "57 final rules"),
    (f"The agencies published 57\nfinal rules on lithium batteries. The 5 newest are {NUMS}.", "57 final rules"),
]


@pytest.mark.parametrize("text, phrase", TOTAL_MUST_WARN, ids=[c[1] + str(i) for i, c in enumerate(TOTAL_MUST_WARN)])
def test_a_total_given_as_a_count_of_documents_gets_a_warning(text, phrase):
    out = ask([S30(), A(text)], cut())
    assert out["grounding"] == "warned" and "search_total_as_count" in out["grounding_reasons"], out["warnings"]
    assert len(out["total_problems"]) == 1 and out["total_problems"][0].startswith(f'"{phrase}": 57 is the total')
    warning = next(w for w in out["warnings"] if "search total as a count of documents" in w)
    assert "search 1 (term: lithium batteries), which returned 5 of them" in warning
    assert "It is not a count of documents about a subject" in warning
    assert out["answer"].index(warning) < out["answer"].index(g.SUMMARY_LABEL)


TOTAL_WORDED_AS_A_TOTAL = [
    f"The search matched 57 final rules in the last 30 days; the 5 newest are {NUMS}.",
    # REAL wording, Sonnet: "The API reports 31 EPA proposed rules matching air quality implementation plans ..."
    f"The API reports 57 final rules matching lithium batteries. Only the 5 newest were returned: {NUMS}.",
    # REAL wording, Q13 Haiku, which the reader called clean: a match of a full-text search does mention the words
    f"57 final rules mentioning lithium batteries were published in the last 30 days. Showing the 5 newest: {NUMS}",
    f"57 final rules contain the words lithium batteries; the 5 newest are {NUMS}.",
    f"There are 57 results. The 5 newest are {NUMS}.",
    f"The search returned 5 of 57 hits: {NUMS}.",
    f"I found 57 matches and list the first 5: {NUMS}.",
]


@pytest.mark.parametrize("text", TOTAL_WORDED_AS_A_TOTAL)
def test_a_total_worded_as_a_count_of_matches_gets_no_warning(text):
    out = ask([S30(), A(text)], cut())
    assert out["warnings"] == [] and out["total_problems"] == [] and out["grounding"] == "ok", out["warnings"]


def test_the_rule_on_totals_is_for_a_search_that_returned_fewer_documents_than_matched():
    """When every match was returned, the count is the count of the documents in the block, which
    the reader can see. REAL, Q01 Haiku, which the reader called clean."""
    text = f"Two final rules were published in the last 30 days: {REAL} and {REAL_2}."
    out = ask([S("artificial intelligence", doc_type="RULE", last_n_days=30), A(text)], Session([(200, BASE)]))
    assert out["warnings"] == [] and out["total_problems"] == []


def test_stated_limit_the_rule_on_totals_sees_only_a_phrase_that_reads_as_a_count_of_documents():
    """REAL, Q22 Haiku, misleading, still passes: the totals are not written as "9 final rules",
    and the sentence has the word "returned"."""
    text = (f"In the last 30 days, final rules on lithium batteries number 57 total (5 returned). {NUMS}.")
    out = ask([S30(), A(text)], cut())
    assert out["warnings"] == [] and out["grounding"] == "ok"
    # REAL, Q09 Haiku, minor: two totals compared with no word that says they are totals. Not a
    # phrase the count rule reads, but with no document named it is caught by another rule.
    two = Session([(200, body(*FIVE, count=57)), (200, body(EB, count=9))])
    out = ask([S30(), S(doc_type="PRORULE", last_n_days=30), A("Yes, more (57 vs 9) final rules than proposed rules.")], two)
    assert out["total_problems"] == [] and "no_document_cited" in out["grounding_reasons"]


# ================================================================== dates: the question's, and the searches' as sent
ISO = "For 2026-09-01 to 2026-09-30 one final rule matched the search: 2026-20760, published 2026-09-30."


@pytest.mark.parametrize("wording", [
    "between September 1 and September 30, 2026",     # REAL, the question of Q25
    "from Sept. 1 to Sept. 30, 2026",
    "between 9/1/2026 and 9/30/2026",
    "between 1 September 2026 and 30 September 2026",
    "on September 1-30, 2026",
    "from the 1st of September 2026 to the 30th of September 2026",
    "between 2026/09/01 and 2026/09/30",
    "between September 1st and 30th, 2026",
])
def test_a_date_the_question_gives_is_accepted_in_any_common_written_form(wording):
    question = f"What final rules on lithium batteries were published {wording}?"
    out = ask([S(doc_type="RULE"), A(ISO)], Session([(200, body(EB))]), question)   # the search carries no dates
    assert out["unverified_dates"] == [] and out["warnings"] == [], out["warnings"]


def test_a_day_and_month_without_a_year_in_the_question_take_the_questions_year_or_this_year():
    session = lambda: Session([(200, body(EB))])   # noqa: E731
    since = "Since 2026-09-01 one final rule matched the search: 2026-20760, published 2026-09-30."
    assert ask([S(), A(since)], session(), "What was published since Sept. 1?")["warnings"] == []
    other_year = ask([S(), A(ISO)], session(), "What was published between September 1 and September 30, 2025?")
    assert other_year["unverified_dates"] == ["2026-09-01"]
    # the head of a document number is not a year the question names
    assert g.find_years("Is 2026-17895 in force? I asked on Sept. 1, 2025.") == {2025}


@pytest.mark.parametrize("text, listed", [
    ("One final rule matched the search: 2026-20760, published 2026-09-02.", ["2026-09-02"]),       # inside the range
    ("One final rule matched the search: 2026-20760. Comments close on October 1, 2026.", ["2026-10-01"]),
    ("One final rule matched the search: 2026-20760, proposed on August 31, 2026.", ["2026-08-31"]),
])
def test_any_other_date_is_still_warned(text, listed):
    question = "What final rules on lithium batteries were published between September 1 and September 30, 2026?"
    out = ask([S(), A(text)], Session([(200, body(EB))]), question)
    assert out["unverified_dates"] == listed and "unverified_dates" in out["grounding_reasons"]
    assert "not as the first or last day of a search that was sent" in out["warnings"][0]


def test_the_two_ends_of_a_search_as_sent_are_in_the_block_and_nothing_between_them_is():
    """REAL: Q09 and Q21 (Sonnet) named the dates of their own second search and were warned."""
    sent = S(date_from="2026-08-08", date_to="2026-09-06")
    fine = ask([sent, A("Between 2026-08-08 and 2026-09-06 one document matched the search: 2026-20760.")],
               Session([(200, body(EB))]))
    assert fine["warnings"] == [] and "published 2026-08-08 to 2026-09-06 (dates chosen by the model)" in fine["block"]
    for text, date in (("2026-20760 matched the search. It takes effect on 2026-09-07.", "2026-09-07"),
                       ("2026-20760 matched the search. It was proposed on 2026-08-07.", "2026-08-07"),
                       ("2026-20760 matched the search and was published on 2026-08-20.", "2026-08-20")):
        assert ask([sent, A(text)], Session([(200, body(EB))]))["unverified_dates"] == [date]
    computed = ask([S30(), A("The window started on 2026-09-06. 2026-20760 matched the search.")], Session([(200, body(EB))]))
    assert computed["unverified_dates"] == ["2026-09-06"]            # the tool's window began on 2026-09-07


@pytest.mark.parametrize("text, expected", [
    ("September 1-30, 2026", {(2026, 9, 1), (2026, 9, 30)}),
    ("Sept. 1 to 30, 2026", {(2026, 9, 1), (2026, 9, 30)}),
    ("September 1st and 30th, 2026", {(2026, 9, 1), (2026, 9, 30)}),
    ("2026/09/30", {(2026, 9, 30)}), ("2026.09.30", {(2026, 9, 30)}),
    ("September 1-31, 2026", set()),                                                   # no 31st of September
    ("https://www.federalregister.gov/documents/2026/09/30/2026-19964/slug", set()),   # a URL path is not a date
])
def test_more_written_forms_of_a_date_are_read(text, expected):
    assert g.find_dates(text)["full"] == expected


def test_the_year_of_a_full_date_in_a_tool_result_is_a_number_the_tool_returned():
    """REAL, Q17 Sonnet: "the 2022 manufactured housing standards rule", from an abstract that
    says "published in the Federal Register on May 31, 2022", was warned as a number in no tool
    result."""
    session = lambda: Session([(200, body(HM))])   # noqa: E731
    assert ask([S("harmonization"), A("2026-21011 supersedes the 2022 rule.")], session())["warnings"] == []
    assert ask([S("harmonization"), A("2026-21011 supersedes the 2021 rule.")], session())["unverified_numbers"] == ["2021"]
    # the year of a month and year alone stays out: with it, an essay from memory passed
    assert ask([S("harmonization"), A("2026-21011 follows the 2025 rule.")], session())["unverified_numbers"] == ["2025"]


# ================================================================== counts
def test_a_count_that_equals_what_a_search_returned_or_its_total_is_not_a_mismatch():
    """REAL, Q06 Sonnet ("10 newest matches") and Q21 Sonnet ("7 proposed rules", the API's
    total): both were warned because the text named fewer documents than the count."""
    text = ("The API reports 57 notices matching lithium batteries. The tool gave me only the 5 newest matches, "
            "and all 5 were published between 2026-09-30 and 2026-10-06.")
    out = ask([S30(), A(text)], cut())
    assert out["count_problems"] == [] and out["warnings"] == [] and out["grounding"] == "ok"
    two = Session([(200, body(HM, GV, count=7)), (200, body(PS, FL, EB, count=10))])
    text = ("By the API's counts, 7 proposed rules matching PFAS were published this year, against 10 for last year. "
            "Clearly related: 2026-21011.")
    out = ask([S("PFAS"), S("PFAS"), A(text)], two, "x?")
    assert out["count_problems"] == [] and out["warnings"] == []


def test_r3_a_count_that_equals_the_block_is_a_note_when_fewer_documents_are_named():
    """Was a WARNING (count_mismatch) until round 3. The comparison with the number of documents
    the text names gave the two false warnings above, so it is information now. The price: an
    invented second document with no number and no quotation marks, under a count that is right,
    passes with a NOTE where it used to be warned."""
    text = f"Two final rules: {REAL}, and an Energy Department rule on grid storage."
    out = ask([S("artificial intelligence"), A(text)], Session([(200, BASE)]))
    assert out["grounding"] == "ok" and out["warnings"] == [] and out["count_problems"] == []
    assert len(out["notes"]) == 1 and out["notes"][0].startswith("NOTE: a count in the model's summary")
    # the wording of the note was changed after the second pass (test_r3_second_pass.py)
    assert ('"two final rules": equals a figure in the block; the summary names 1 of the 2 returned document(s) '
            "by number") in out["notes"][0]
    assert "This is information, not a finding" in out["notes"][0]
    answer = out["answer"]
    assert answer.index(out["block"]) < answer.index(out["notes"][0]) < answer.index(g.SUMMARY_LABEL)


@pytest.mark.parametrize("text, reason_text", [
    (f"Four final rules matched: {REAL} and {REAL_2}.", '"four final rules": the tools returned 2 document(s)'),
    (f"Seven final rules were published. The two most relevant are {REAL} and {REAL_2}.", '"seven final rules"'),
])
def test_a_count_that_equals_nothing_a_tool_returned_is_still_warned(text, reason_text):
    out = ask([S("artificial intelligence"), A(text)], Session([(200, BASE)]))
    assert "count_mismatch" in out["grounding_reasons"] and reason_text in out["warnings"][0]


def test_a_smaller_count_is_the_models_own_grouping_and_stands_when_it_names_that_many():
    grouped = ("The search returned 5 of 57 matching documents. Three rules have lithium batteries in their titles: "
               "2026-20944, 2026-20871 and 2026-20760.")
    assert ask([S30(), A(grouped)], cut())["warnings"] == []
    # Changed after the second pass. This was a WARNING ("the block has 5 document(s), and the
    # summary names 1 of them"). On 60 new real answers the same comparison warned five that a
    # reader called clean ("I left out the other 4 returned documents"), so it is a NOTE now.
    # The price: a count the text does not back by naming documents passes with a NOTE.
    unnamed = ask([S30(), A("Three final rules are about lithium batteries. 2026-20944 is one of them.")], cut())
    assert unnamed["grounding"] == "ok" and unnamed["warnings"] == [] and unnamed["count_problems"] == []
    assert ('"three final rules": equals no total the API reported, no number a search returned and not the number '
            "of documents in the block (5); the summary names 1 document(s) by number") in unnamed["notes"][0]


def test_the_number_returned_presented_as_all_there_are_is_still_warned():
    out = ask([S30(), A(f"Only five final rules were published: {NUMS}.")], cut())
    assert "count_mismatch" in out["grounding_reasons"]
    assert "that is how many documents were returned, but the API reported 57 in total" in out["warnings"][0]


# ================================================================== a number the user asked about
def test_a_number_from_the_question_whose_lookup_failed_is_not_called_invented():
    """REAL, Q27, both writers: "Document 2026-99999 was not found in the Federal Register API"
    drew "they may be invented: 2026-99999"."""
    question = "Give me the effective dates of Federal Register documents 2026-21011 and 2026-99999."
    text = "2026-21011 is effective 2026-11-06. Document 2026-99999 was not found in the Federal Register API."
    out = ask([L("2026-21011"), L("2026-99999"), A(text)], Session(docs=LOOKUPS), question)
    assert out["grounding"] == "warned" and out["grounding_reasons"] == ["asked_not_returned", "tool_failed"]
    assert not any("may be invented" in w for w in out["warnings"])
    assert out["warnings"][0].startswith("WARNING: your question names 2026-99999, and the lookup of that number failed in this run")
    assert "not_found: The Federal Register API has no document with this number" in out["warnings"][0]
    # it is still not a returned document
    assert out["unverified_document_numbers"] == ["2026-99999"] and out["asked_not_returned"] == ["2026-99999"]
    assert [d["document_number"] for d in out["citations"]] == ["2026-21011"]
    assert "2026-99999" not in out["block"].split("Tool calls that failed")[0]


def test_a_number_from_the_question_that_no_tool_returned_and_no_lookup_tried_is_warned_in_its_own_words():
    out = ask([S(), A("Yes. 2026-18889 is the Energy Department's battery rule. 2026-21011 also matched.")],
              Session([(200, body(HM, GV))]), "Is 2026-18889 a DOE final rule about batteries?")
    assert out["grounding_reasons"] == ["asked_not_returned"] and out["asked_not_returned"] == ["2026-18889"]
    assert "your question names 2026-18889. No tool returned a document with that number" in out["warnings"][0]
    assert "nothing the summary says about it was checked" in out["warnings"][0]
    cited = ask([S("harmonization"), A("91 FR 60210 is the PHMSA rule, 2026-21011.")], Session([(200, body(HM))]),
                "What is published at 91 FR 60210?")
    assert cited["asked_not_returned"] == ["91 FR 60210"]


def test_a_number_the_question_does_not_name_is_still_called_unverified():
    out = ask([S(), L("2026-18889"), A("2026-18889 is the battery rule. 2026-21011 also matched.")],
              Session([(200, body(HM, GV))]), "What was published about batteries?")
    assert "unverified_references" in out["grounding_reasons"] and "they may be invented: 2026-18889" in out["warnings"][0]


# ================================================================== docket ids
def test_docket_ids_copied_from_the_docket_ids_field_get_a_note_not_a_warning():
    """REAL, Q29, both writers: "The docket IDs are Release Nos. 33-11438, 34-106345, 39-2565, and
    IC-36326" drew "mentioned inside a returned document, not returned as one"."""
    text = "The most recent SEC final rule is 2026-20990. The docket IDs are Release Nos. 33-11500, 34-106500, and IC-36400."
    out = ask([L("2026-20990"), A(text)], Session(docs=LOOKUPS), "List the docket ids of 2026-20990.")
    assert out["grounding"] == "ok" and out["warnings"] == [] and out["mentioned_only_references"] == []
    assert out["docket_references"] == ["33-11500", "34-106500"]
    assert out["notes"][0].startswith("NOTE: 33-11500, 34-106500 have the form of a document number")
    assert "docket ids the tool returned, not documents returned in this run" in out["notes"][0]


@pytest.mark.parametrize("text, questions_document", [
    # a docket id called a document
    ("2026-20990 is the filer manual rule. See also document 34-106500, which sets the filing fee.", "2026-20990"),
    # a docket id given without the document whose field holds it
    ("2026-21011 was issued under Release No. 33-11500.", "2026-21011"),
])
def test_a_docket_id_is_never_a_document_and_counts_only_next_to_the_document_that_holds_it(text, questions_document):
    out = ask([L("2026-20990"), L("2026-21011"), A(text)], Session(docs=LOOKUPS), f"Tell me about {questions_document}.")
    assert out["grounding"] == "warned" and out["grounding_reasons"] == ["docket_id_not_a_document"]
    assert "a docket id in the docket_ids field of returned document 2026-20990" in out["warnings"][0]
    assert out["docket_misused"] and out["docket_references"] == []


def test_a_release_number_in_no_field_and_a_number_inside_an_abstract_are_warned_as_before():
    out = ask([L("2026-20990"), A("2026-20990 has the docket id Release No. 33-99999.")], Session(docs=LOOKUPS), "x?")
    assert out["unverified_document_numbers"] == ["33-99999"] and "unverified_references" in out["grounding_reasons"]
    quoted = doc("2026-20655", "Safety Zone; Potomac River", "Corrects the notice at 91 FR 60210 (FR Doc. 2026-19555).")
    out = ask([S("safety zone"), A("2026-20655 corrects 2026-19555, the original rule.")], Session([(200, body(quoted))]), "x?")
    assert out["mentioned_only_references"] == ["2026-19555"]
    assert "the free text of a returned document (a title or an abstract)" in out["warnings"][0]


# ================================================================== an answer that names no document
def test_an_answer_to_how_many_that_gives_the_total_as_a_total_gets_a_note_not_a_warning():
    """REAL, Q06 and Q09 (Sonnet): answers to "how many" that the reader called clean."""
    out = ask([S30(), A("The API reports 57 final rules matching lithium batteries in the last 30 days. I did not list them.")],
              cut(), "How many final rules on lithium batteries were published in the last 30 days?")
    assert out["grounding"] == "ok" and out["warnings"] == [] and "no_document_cited" not in out["grounding_reasons"]
    assert len(out["notes"]) == 1 and out["notes"][0].startswith("NOTE: the model's summary names none of the 5 document(s)")
    assert "as a count of what a search matched or returned, 57" in out["notes"][0]


@pytest.mark.parametrize("text", [
    "Several agencies have been active on lithium batteries lately.",
    "The Energy Department published a rule on grid storage.",
    "More final rules: 57 versus 9.",             # a figure, but no word that says what it counts
])
def test_an_answer_that_names_no_document_and_words_no_count_is_still_warned(text):
    out = ask([S30(), A(text)], cut())
    assert "no_document_cited" in out["grounding_reasons"]
    assert "names none of the 5 document(s) in the block above" in out["warnings"][-1]


def test_stated_limit_a_worded_total_lets_an_invented_claim_without_digits_pass_with_a_note():
    """Was warned before round 3 by "names none of the documents". Code cannot tell "I did not list
    them" from "the most important one bans X"; the NOTE says nothing else could be tied to a
    document."""
    out = ask([S30(), A("The search matched 57 final rules. The most important one bans lithium batteries in checked baggage.")],
              cut())
    assert out["grounding"] == "ok" and out["warnings"] == []
    assert "Nothing else in it could be tied to a document." in out["notes"][0]


# ================================================================== notes: where they go
def test_notes_stand_between_the_warnings_and_the_models_text_and_are_not_warnings():
    text = ("The docket IDs of 2026-20990 are Release Nos. 33-11500 and 34-106500. It was published on January 3, 2031.")
    out = ask([L("2026-20990"), A(text)], Session(docs=LOOKUPS), "x?")
    answer = out["answer"]
    assert out["grounding"] == "warned" and len(out["warnings"]) == 1 and len(out["notes"]) == 1
    assert answer.index(out["block"]) < answer.index(out["warnings"][0]) < answer.index(out["notes"][0]) \
        < answer.index(g.SUMMARY_LABEL) < answer.index(text)
    assert out["notes"][0].startswith(g.NOTE_PREFIX) and not out["notes"][0].startswith(g.WARNING_PREFIX)
    assert "NOTE:" not in g.repeated_warning(out["warnings"])
    assert g.compose_answer("B", [], "P", ["NOTE: n"]) == "B\n\nNOTE: n\n\n" + g.SUMMARY_LABEL + "\nP"
    assert g.compose_answer("B", [], "P") == "B\n\n" + g.SUMMARY_LABEL + "\nP"


def test_the_hosted_entrypoint_sends_the_notes_and_the_new_lists(monkeypatch):
    import importlib

    import agent.model
    from starlette.testclient import TestClient

    module = importlib.reload(importlib.import_module("agentcore_app"))
    monkeypatch.setattr(fr_tools, "_default_session", lambda: cut())
    text = "57 final rules on lithium batteries were published."
    monkeypatch.setattr(agent.model, "make_bedrock_model", lambda *a, **k: ScriptedChatModel(responses=[S30(), A(text)]))
    with TestClient(module.app) as client:
        reply = client.post("/invocations", json={"prompt": Q30}).json()
    assert reply["grounding"] == "warned" and reply["notes"] == [] and reply["asked_not_returned"] == []
    assert reply["total_problems"][0].startswith('"57 final rules": 57 is the total')
    assert "search_total_as_count" in reply["grounding_reasons"] and reply["warning"] in reply["result"]


def test_the_hosted_script_flags_a_total_given_as_a_count():
    from conftest import load_script

    script = load_script("50_invoke_hosted.py")
    flagged, reasons = script.check_report({"grounding": "warned", "grounding_reasons": ["search_total_as_count"],
                                            "total_problems": ['"57 final rules": 57 is the total ...'],
                                            "warnings": ["WARNING: ..."]})
    assert flagged and reasons[0].startswith("search totals given as counts of documents:")
    clean, none = script.check_report({"grounding": "ok", "grounding_reasons": [], "notes": ["NOTE: ..."]})
    assert not clean and none == []            # a NOTE alone does not flag a call


# ================================================================== "the newest X is <document>": a NOTE
def test_a_newest_claim_about_a_document_with_none_of_the_search_words_gets_a_note_not_a_warning():
    """REAL, Q23 Haiku ("The most recent executive order published in the Federal Register is
    document 2026-20322", a document with neither word in its title and no abstract) and Q18
    Haiku. A NOTE and not a WARNING: as a warning the same rule fired on an honest "The newest
    is <number>" after a search for a general word."""
    text = "The most recent rule on lithium batteries is document 2026-20802, published 2026-10-01."
    out = ask([S30(), A(text)], cut())
    assert out["grounding"] == "ok" and out["warnings"] == [] and len(out["notes"]) == 1
    note = out["notes"][0]
    assert note.startswith("NOTE: the model's summary calls a document the newest, the most recent or the latest: "
                           "2026-20802 (search 1, term: lithium batteries).")
    assert "a count of words, not a judgement of relevance" in note
    assert out["answer"].index(note) < out["answer"].index(g.SUMMARY_LABEL)


@pytest.mark.parametrize("text", [
    "The newest match of my search is 2026-20802.",                                    # says it is a match
    "The most recent rule on lithium batteries is document 2026-20871.",               # the title has the words
    "The most recent rule on lithium batteries is document 2026-21011.",               # the abstract has them
    f"The 5 newest are {NUMS}.",                                                       # a list, not one document
    "2026-20802 is a rule on lithium batteries.",                                      # none of the three words
])
def test_the_note_on_a_newest_claim_is_narrow(text):
    out = ask([S30(), A(text)], cut())
    assert not any("the newest, the most recent or the latest" in note for note in out["notes"])
    assert out["warnings"] == []      # and the last one is the stated limit: relevance is not checked


# ================================================================== what is still not checked
STILL_PASSES = [
    # REAL, Q20 Haiku: the abstract of the document is about fuel economy
    ("The newest NHTSA final rule on federal motor vehicle safety standards is document 2026-21011.",
     "a returned document called the newest rule on a subject its fields do not show"),
    # REAL, Q23 Haiku: the tool labels it only "Presidential Document"
    ("The most recent executive order published in the Federal Register is document 2026-20944.",
     "a document type the tool did not return"),
    # REAL, Q16 Haiku: two of the listed documents are security zones
    (f"The Coast Guard published 5 final rules establishing safety zones in the last 30 days (out of 57 total "
     f"matching the search): {NUMS}", "the number returned, with the total beside it, given as a count on a topic"),
]


@pytest.mark.parametrize("text, what", STILL_PASSES, ids=[c[1] for c in STILL_PASSES])
def test_stated_limit_a_returned_document_presented_as_the_thing_asked_for_still_passes(text, what):
    """Pinned so nobody mistakes the check for more than it is. In the rehearsal on real model
    text this was the larger half of the answers a reader called misleading and the check
    passed. What the reader gets instead: the fixed sentence under each search, and the word
    count under each document, in the block in front of the text."""
    out = ask([S30(), A(text)], cut())
    assert out["grounding"] == "ok" and out["warnings"] == []
    assert g.MATCHES_NOT_TOPIC in out["block"] and "Search words (search 1): in title: 0 of 2" in out["block"]
