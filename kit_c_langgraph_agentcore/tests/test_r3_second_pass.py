"""Round 3, second pass, 2026-10-07: the count rule after it met text it was not tuned on.

The answer check had been corrected on the 60 real answers of the first rehearsal pass. Two
stand-in models (Claude Haiku and Claude Sonnet) then wrote 60 new answers to the same 30
questions under the system prompt that correction had produced, and two new blind readers
labelled them. On the new text the corrected check warned 12 of the 39 answers a reader called
clean (on the answers it had been tuned on: 2 of 33). Eight of the twelve were the count rule
misreading honest sentences that the new prompt asks a model to write; two were the number
rule not knowing a figure the block itself prints; two were true (a failed lookup).

What these tests pin. A stated count of documents is a WARNING in three cases only:
  (a) a search total given as a count of documents with no word that says it is a count of
      matches (unchanged, test_r3_rehearsal.py);
  (b) the number returned presented as all there are: the sentence has no subset or sample
      wording, no larger total stands in the same paragraph, and the question did not ask for
      that many;
  (c) more documents than every search of the run matched and than the block holds.
Every other comparison of a count is one NOTE line, which says it is information and not a
finding. The sentences marked REAL are quoted from the second pass, with the document numbers
of this file's canned documents put in.

Offline: scripted model, canned Federal Register responses.
"""
from __future__ import annotations

import datetime as dt

import pytest
from conftest import FakeResponse
from langchain_core.messages import AIMessage

from agent import graph as g
from agent.fake_model import ScriptedChatModel, tool_call

TODAY = dt.date(2026, 10, 7)


class Session:
    """Stands in for requests.Session. Searches are answered in order and the last repeats."""

    def __init__(self, searches):
        self.searches = list(searches)

    def get(self, url, params=None, headers=None, timeout=None):
        assert url.endswith("/documents.json")
        return FakeResponse(*(self.searches.pop(0) if len(self.searches) > 1 else self.searches[0]))


def S(term="tariffs", **kwargs):
    return tool_call("search_federal_register", {"term": term, **kwargs})


def A(text):
    return AIMessage(content=text)


TITLES = [
    "Robotically-Assisted Surgical Devices; Draft Guidance for Industry; Availability",
    "Request for Information on Ibogaine Clinical Trials",
    "Agency Information Collection Activities; Proposed Collection; Comment Request",
    "Agency Information Collection Activities; Submission for Review",
    "Pilot Program Announcement",
    "Endangered and Threatened Wildlife and Plants; Nine Species Not Warranted for Listing",
    "Safety Zone; Illinois River, Morris, IL",
    "Statement of Organization, Functions, and Delegations of Authority",
    "Decision and Order",
    "Fisheries of the Northeastern United States; Quota Transfer",
]


def doc(index):
    number = f"2026-{21001 + index}"
    return {"abstract": "An abstract with no figures in it.", "document_number": number, "title": TITLES[index],
            "type": "Notice", "publication_date": "2026-10-02",
            "agencies": [{"name": "Food and Drug Administration", "raw_name": "FOOD AND DRUG ADMINISTRATION"}],
            "html_url": f"https://www.federalregister.gov/documents/2026/10/02/{number}/slug"}


N = [f"2026-{21001 + i}" for i in range(10)]


def found(total, returned):
    """One search response: `returned` documents of `total` matches."""
    return (200, {"count": total, "results": [doc(i) for i in range(returned)]})


def second(total, returned):
    """A second search's response, with documents the first did not return."""
    return (200, {"count": total, "results": [doc(5 + i) for i in range(returned)]})


def ask(script, searches, question="What was published?"):
    graph = g.build_graph(ScriptedChatModel(responses=list(script)),
                          g.build_tools(session=Session(searches), today=TODAY))
    return g.run_question(graph, question, today=TODAY)


def listing(numbers):
    return "\n".join(f"- Food and Drug Administration: {TITLES[N.index(n)]}; 2026-10-02; {n}" for n in numbers)


LAST30 = dict(doc_type="NOTICE", last_n_days=30)

# ================================================================== the eight honest sentences, and two more
HONEST = [
    # REAL, Q05 Sonnet: 1094 matched, 3 returned, one listed
    ("Q05 sonnet", [S()], [found(1094, 3)], "x?",
     f"The newest match of the search is {N[0]}, but its title and abstract are about something else.\n\n"
     f"{listing(N[:1])}\n\n"
     "I left out the other 2 returned documents: both are older and their titles and abstracts are about something else."),
    # REAL, Q10 Haiku: 10 matched, 5 returned, one listed
    ("Q10 haiku", [S(**LAST30)], [found(10, 5)], "x?",
     "10 documents matched the search for \"guidance for industry\" among FDA notices in the last 30 days. Of the 5 "
     f"newest returned results, one clearly fits the question: {N[0]}. Four other returned documents matched the search "
     "words but their titles and abstracts show they are about other topics (ibogaine drug trials, orphan drugs, "
     "temporary marketing permits, and CMC development)."),
    # REAL, Q10 Sonnet. "two information collection notices" is the model's own grouping: a NOTE
    ("Q10 sonnet", [S(**LAST30)], [found(10, 5)], "x?",
     "10 documents matched the search for guidance for industry among FDA notices in the last 30 days, and the tool "
     f"returned only the 5 newest. Of those 5, one clearly announces guidance:\n\n{listing(N[:1])}\n\n"
     "This one announces draft guidance. I left out the other 4 returned documents: they matched the search, but their "
     "titles and abstracts are about something else (a request for information on ibogaine clinical trials, two "
     "information collection notices, and a pilot program announcement). The other 5 matches were not returned, so the "
     "tool results do not show whether any of them announce guidance."),
    # REAL, Q13 Sonnet: 11 matched, 5 returned, all five listed, and 11 - 5 = 6
    ("Q13 sonnet", [S(doc_type="PRESDOCU", last_n_days=60)], [found(11, 5)], "x?",
     "11 documents matched the search for tariffs among presidential documents in the last 60 days. The tool returned "
     f"only the 5 newest, listed below.\n\n{listing(N[:5])}\n\nThe other 6 matches were not returned."),
    # REAL, Q19 Haiku: the question asks for five, 171 matched, the total is not in the text
    ("Q19 haiku", [S(**LAST30)], [found(171, 5)],
     "Give me the five newest SEC notices from the last 30 days about self-regulatory organizations' proposed rule changes.",
     "Five documents matching the search for SEC notices about self-regulatory organizations' proposed rule changes "
     f"from the last 30 days are:\n\n{listing(N[:5])}"),
    # REAL, Q23 Sonnet: the total stands in the same paragraph as "All three were published"
    ("Q23 sonnet", [S("executive order", doc_type="PRESDOCU", limit=3)], [found(3131, 3)], "x?",
     "I can't name the most recent executive order from these results. The search was for presidential documents "
     "containing the words executive order (3131 documents matched; I was given the 3 newest). The records label all "
     f"three only as \"Notice\". All three were published on 2026-10-02:\n\n{listing(N[:3])}"),
    # REAL, Q25 Sonnet: 27 matched, 5 returned, two listed
    ("Q25 sonnet", [S("Medicare", doc_type="NOTICE")], [found(27, 5)], "x?",
     "27 documents matched the search for Medicare among notices in that period, and I was given the 5 newest; none of "
     f"them shows by its title and abstract that it is about Medicare. Two are from the same agency:\n\n{listing(N[:2])}\n\n"
     "I left out the other 3 returned documents (a statement of organization and two decisions) because their titles "
     "and abstracts are about something else."),
    # REAL, Q28 Sonnet: 14 matched, 10 returned, one listed (its title holds the word Nine)
    ("Q28 sonnet", [S("endangered species", doc_type="RULE", last_n_days=60, limit=10)], [found(14, 10)], "x?",
     "Among the returned results, the only agency shown to have published a final rule about endangered species in "
     f"the last 60 days is the Food and Drug Administration:\n\n{listing(N[5:6])}\n\n"
     "This is not a complete answer. 14 documents matched the search for endangered species among final rules in that "
     "period, and I was given the 10 newest. I left out the other 9 returned documents because their titles and "
     "abstracts are about other subjects (the words appear elsewhere in their text), so I have not counted their "
     "agencies. The remaining matches were not returned."),
    # REAL, Q21 Sonnet (the reader called it minor, for another sentence): two searches, 7 and 10
    # matched, 5 returned by each; the totals stand in the same paragraph
    ("Q21 sonnet", [S("PFAS", doc_type="PRORULE"), S("PFAS", doc_type="PRORULE")], [found(7, 5), second(10, 5)], "x?",
     "What the searches show: 7 documents matched the search for PFAS among proposed rules this year, and 10 matched "
     "for last year. Those are counts of matches, not counts of PFAS rules. I was given only 5 documents from each "
     "search, and several of them have titles and abstracts about other subjects, so neither total can be read as a "
     f"PFAS count.\n\n{listing(N[:1])}"),
]


@pytest.mark.parametrize("name, calls, searches, question, text", HONEST, ids=[c[0] for c in HONEST])
def test_real_second_pass_an_honest_count_sentence_gets_no_warning(name, calls, searches, question, text):
    out = ask([*calls, A(text)], searches, question)
    assert out["warnings"] == [] and out["grounding"] == "ok" and out["count_problems"] == [], out["warnings"]
    assert out["total_problems"] == []


def test_real_second_pass_the_number_of_documents_in_the_block_is_not_an_unverified_number():
    """REAL, Q22, both writers: two searches returned 5 documents each, and "none of the 10
    returned documents" (Haiku) and "I left out 8 of those 10 returned documents" (Sonnet) drew
    "1 number(s) that appear in no complete field of a tool result ... : 10". The block itself
    says "Documents returned (10)"; code counted them."""
    two = [found(9, 5), second(16, 5)]
    calls = [S("cybersecurity", doc_type="RULE", last_n_days=60), S("cybersecurity", doc_type="PRORULE", last_n_days=60)]
    haiku = ("The search found 9 documents matching \"cybersecurity\" as final rules in the last 60 days, and 16 "
             "documents matching \"cybersecurity\" as proposed rules in the same period.\n\nHowever, none of the 10 "
             "returned documents have titles or abstracts clearly showing they are about cybersecurity.")
    out = ask([*calls, A(haiku)], two)
    assert "Documents returned (10)" in out["block"]
    assert out["unverified_numbers"] == [] and out["warnings"] == [] and out["grounding"] == "ok"
    sonnet = ("In the last 60 days, 9 documents matched the search for cybersecurity among final rules and 16 matched "
              f"among proposed rules. I was given the 5 newest of each. I left out 8 of those 10 returned documents.\n\n"
              f"{listing([N[0], N[5]])}")
    out = ask([*calls, A(sonnet)], two)
    assert out["unverified_numbers"] == [] and out["warnings"] == [] and out["grounding"] == "ok"
    # a number the block does not print is still warned
    out = ask([*calls, A(haiku.replace("the 10 returned", "the 12 returned"))], two)
    assert out["unverified_numbers"] == ["12"] and "unverified_numbers" in out["grounding_reasons"]


# ================================================================== (b) the number returned given as all there are
RETURNED_AS_ALL = "that is how many documents were returned, but the API reported {total} in total"


def test_real_second_pass_the_number_returned_given_as_the_number_matched_is_still_warned():
    """REAL, Q16 Haiku, which the reader called misleading: 20 matched and 10 were returned. The
    sentence has the words "matched" and "search", and those are not subset wording: it says
    how many matched, and that is the API's total, not the number returned."""
    text = ("Ten documents matched the search for Coast Guard safety zones in the last 30 days. The newest final rules "
            f"establishing or regulating safety zones are:\n\n{listing(N[:8])}\n\n"
            f"Also returned were rules that matched the search but are about security zones, not safety zones ({N[8]} and {N[9]}).")
    out = ask([S("safety zone", doc_type="RULE", last_n_days=30, limit=10), A(text)], [found(20, 10)])
    assert out["grounding"] == "warned" and out["grounding_reasons"] == ["count_mismatch"]
    assert '"ten documents": ' + RETURNED_AS_ALL.format(total=20) in out["warnings"][0]


@pytest.mark.parametrize("text", [
    f"Only five notices were published: {', '.join(N[:5])}.",
    f"Exactly five documents were published in the period: {', '.join(N[:5])}.",
    f"There are five notices on tariffs: {', '.join(N[:5])}.",
    f"Five notices matched: {', '.join(N[:5])}.",
    # the total stands in another paragraph, so the sentence still reads as all there are
    f"Only five notices were published: {', '.join(N[:5])}.\n\nA note on method: the API reported 57 matches.",
])
def test_the_number_returned_with_no_subset_wording_and_no_total_nearby_is_still_warned(text):
    out = ask([S(), A(text)], [found(57, 5)])
    assert out["grounding_reasons"] == ["count_mismatch"], out["warnings"]
    assert RETURNED_AS_ALL.format(total=57) in out["warnings"][0]


@pytest.mark.parametrize("text", [
    f"The 5 newest notices are {', '.join(N[:5])}.",
    f"I was given 5 documents: {', '.join(N[:5])}.",
    f"Of the 5 documents returned, two are on tariffs: {N[0]} and {N[1]}.",
    f"Here are 5 notices among those that matched: {', '.join(N[:5])}.",
    f"These 5 notices are a sample: {', '.join(N[:5])}.",
    # the total in the same paragraph, in digits and in words
    f"57 documents matched the search. All five were published on 2026-10-02: {', '.join(N[:5])}.",
    f"Fifty-seven documents matched the search. Five notices were published on 2026-10-02: {', '.join(N[:5])}.",
])
def test_subset_wording_or_the_total_in_the_same_paragraph_keeps_the_number_returned_from_a_warning(text):
    out = ask([S(), A(text)], [found(57, 5)])
    assert out["warnings"] == [] and out["count_problems"] == [], out["warnings"]


def test_a_count_the_question_asked_for_is_not_the_number_returned_given_as_all_there_are():
    """REAL, Q19 Haiku: "Give me the five newest ..." answered with "Five documents matching the
    search ... are:". The reader called it clean: it "makes no claim about how many exist". The
    same sentence under a question that names no count is still warned, like Q16 above."""
    text = f"Five documents matching the search for tariffs are:\n\n{listing(N[:5])}"
    asked = ask([S(), A(text)], [found(171, 5)], "Give me the five newest notices on tariffs.")
    assert asked["warnings"] == [] and asked["grounding"] == "ok"
    digits = ask([S(), A(text)], [found(171, 5)], "Show me 5 notices on tariffs.")
    assert digits["warnings"] == []
    not_asked = ask([S(), A(text)], [found(171, 5)], "What notices on tariffs were published in the last 5 days?")
    assert not_asked["grounding_reasons"] == ["count_mismatch"]      # the 5 of "the last 5 days" is not a count asked for
    assert RETURNED_AS_ALL.format(total=171) in not_asked["warnings"][0]
    # the question asked for five, and the sentence says five is all there is: still warned
    only = ask([S(), A(f"Only five notices on tariffs were published:\n\n{listing(N[:5])}")], [found(171, 5)],
               "Give me the five newest notices on tariffs.")
    assert only["grounding_reasons"] == ["count_mismatch"]


def test_stated_limit_a_count_the_question_asked_for_passes_in_a_sentence_that_reads_as_all_there_are():
    """The price of the test above. Code cannot tell "here are the five you asked for" from "five
    exist" when no word says which."""
    out = ask([S(), A(f"The SEC published five notices on tariffs:\n\n{listing(N[:5])}")], [found(171, 5)],
              "Give me the five newest notices on tariffs.")
    assert out["grounding"] == "ok" and out["warnings"] == []
    assert "The API reported 171 matching document(s) in total and returned 5." in out["block"]


def test_stated_limit_all_three_were_published_with_the_total_nowhere_in_the_text_is_still_warned():
    """REAL, first pass, Q23 Sonnet, which the reader called minor because "all three of the
    newest presidential documents" are the newest 3 of 3131 matches and the text never says so.
    The warning names that fact. Pinned so the change of rule (b) is not read as wider than it
    is: the same sentence with the total in its paragraph (second pass) is not warned."""
    text = ("I can't confirm which document is the most recent executive order. The tool labels all three of the "
            f"newest presidential documents only as Notice. All three were published on 2026-10-02:\n\n{listing(N[:3])}")
    out = ask([S("executive order", doc_type="PRESDOCU", limit=3), A(text)], [found(3131, 3)])
    assert out["grounding_reasons"] == ["count_mismatch"]
    assert '"three were published": ' + RETURNED_AS_ALL.format(total=3131) in out["warnings"][0]


# ================================================================== (c) more than every search matched
@pytest.mark.parametrize("text, said", [
    (f"Three notices on tariffs were published: {N[0]}, {N[1]}, and a Commerce Department notice on export controls.",
     '"three notices": the tools returned 2 document(s) and the API reported total(s) of 2'),
    (f"Seven notices were published. The two most relevant are {N[0]} and {N[1]}.", '"seven notices"'),
])
def test_a_count_larger_than_every_total_and_than_the_block_is_still_a_warning(text, said):
    out = ask([S(), A(text)], [found(2, 2)])
    assert out["grounding_reasons"] == ["count_mismatch"] and said in out["warnings"][0]


def test_stated_limit_the_totals_of_two_searches_added_up_are_still_warned():
    """Not changed in the second pass: no real answer added totals up. A sum is larger than every
    total, so it is read as case (c), and as a number the model worked out."""
    two = [found(9, 5), second(16, 5)]
    calls = [S("cybersecurity", doc_type="RULE"), S("cybersecurity", doc_type="PRORULE")]
    out = ask([*calls, A(f"25 rules on cybersecurity were published. The newest are {N[0]} and {N[5]}.")], two)
    assert out["grounding_reasons"] == ["unverified_numbers", "count_mismatch"]
    assert '"25 rules": the tools returned 10 document(s) and the API reported total(s) of 9, 16' in out["warnings"][1]


# ================================================================== every other count comparison: one NOTE
NOT_A_FINDING = "This is information, not a finding"


@pytest.mark.parametrize("text, phrase", [
    # was a WARNING until the second pass: the same comparison warned five honest answers
    (f"Three notices are about tariffs. {N[1]} is one of them.", "three notices"),
    (f"Two notices: {N[0]}, and a Treasury notice on beneficial ownership reporting.", "two notices"),
    # an unverifiable remainder: 5 returned and one named leaves four, not three
    (f"{N[0]} fits. I left out the other 3 returned documents.", "3 returned documents"),
    # larger than the block and smaller than the total: a count of some of the matches, or of anything else
    (f"The search matched 57 documents. The first is {N[0]}, which summarises eight notices.", "eight notices"),
])
def test_a_count_that_equals_no_figure_of_the_block_is_a_note_and_not_a_warning(text, phrase):
    out = ask([S(), A(text)], [found(57, 5)])
    assert out["grounding"] == "ok" and out["warnings"] == [] and out["count_problems"] == [], out["warnings"]
    assert len(out["notes"]) == 1, out["notes"]
    note = out["notes"][0]
    assert note.startswith("NOTE: a count in the model's summary was compared with the figures in the block")
    assert NOT_A_FINDING in note
    assert f'"{phrase}": equals no total the API reported, no number a search returned and not the number of ' \
           "documents in the block (5)" in note
    answer = out["answer"]
    assert answer.index(out["block"]) < answer.index(note) < answer.index(g.SUMMARY_LABEL)


def test_all_count_comparisons_of_an_answer_share_one_note_line():
    text = ("57 documents matched the search and I was given the 5 newest. Three notices are about tariffs, and "
            f"{N[1]} is one of them. Two notices are about fisheries.")
    out = ask([S(), A(text)], [found(57, 5)])
    assert out["warnings"] == [] and len(out["notes"]) == 1
    note = out["notes"][0]
    assert note.startswith("NOTE: counts in the model's summary were compared with the figures in the block")
    assert "\n" not in note and NOT_A_FINDING in note
    assert '"three notices": equals no total' in note and '"two notices": equals no total' in note
    # a count that equals a figure of the block, with fewer documents named than that count
    assert '"5 newest": ' not in note      # "the 5 newest" is not a phrase the count rule reads
    out = ask([S(), A(f"Two notices: {N[0]}, and a Treasury notice on reporting.")], [found(2, 2)])
    assert out["warnings"] == [] and len(out["notes"]) == 1
    assert '"two notices": equals a figure in the block; the summary names 1 of the 2 returned document(s) by number' \
        in out["notes"][0] and NOT_A_FINDING in out["notes"][0]


def test_a_remainder_that_code_can_work_out_again_gets_neither_a_warning_nor_a_note():
    """n minus k: the documents returned less the documents named, and the matches less the
    documents returned. Only with wording that says it is a remainder or a part."""
    left_out = ask([S(), A(f"{N[0]} fits. I left out the other 4 returned documents.")], [found(57, 5)])
    assert left_out["warnings"] == [] and left_out["notes"] == []
    not_returned = ask([S(), A(f"The 5 newest are {', '.join(N[:5])}. The other 52 matches were not returned.")],
                       [found(57, 5)])
    assert not_returned["warnings"] == [] and not_returned["notes"] == [] and not_returned["unverified_numbers"] == []
    # a number that is neither remainder is still an unverified number
    wrong = ask([S(), A(f"The 5 newest are {', '.join(N[:5])}. The other 51 matches were not returned.")], [found(57, 5)])
    assert wrong["unverified_numbers"] == ["51"] and wrong["grounding"] == "warned"
    # the same number with no such wording is a NOTE: code cannot tell what it counts
    bare = ask([S(), A(f"Four notices are about tariffs. {N[0]} is one of them.")], [found(57, 5)])
    assert bare["warnings"] == [] and len(bare["notes"]) == 1 and '"four notices": equals no total' in bare["notes"][0]


def test_a_total_of_a_search_that_returned_fewer_is_not_compared_with_the_documents_named():
    """Seen in the second pass (Q22 Sonnet): "9 documents matched ..." drew the NOTE "the summary
    names 2 of the 10 returned document(s) by number". Nine matched and five of them were
    returned; how many the text names says nothing about that sentence."""
    two = [found(9, 5), second(16, 5)]
    calls = [S("cybersecurity", doc_type="RULE"), S("cybersecurity", doc_type="PRORULE")]
    text = (f"9 documents matched the search among final rules and 16 matched among proposed rules. Two I can't rule "
            f"out: {N[0]} and {N[5]}.")
    out = ask([*calls, A(text)], two)
    assert out["warnings"] == [] and out["notes"] == []
