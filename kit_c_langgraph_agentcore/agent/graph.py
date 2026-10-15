"""The LangGraph graph: model -> tools -> model -> ... -> finalize -> END.

Three nodes:
  model     calls the chat model with the two tools bound
  tools     runs the tool calls the model asked for, at most
            MAX_TOOL_CALLS_PER_TURN of them per model turn
  finalize  a plain function, no model: it reads the tool results of this run
            and builds what the reader is shown.

What the reader is shown (review round 2, 2026-10-07). The model's text is
never the answer by itself. A kept answer has these parts, in this order:

  1. A BLOCK BUILT BY CODE from the tool results of this run: each search as it
     was sent and the total the API reported, with a fixed sentence that the
     total counts documents matching the search words and not documents about
     the topic; then each document a tool returned, with document number, type,
     publication date, agencies, title and URL, copied from the API's fields,
     and for a document that a search returned one line counted by code: how
     many of the search's words stand in its title and in its abstract
     (fr_tools.search_word_report). That line is a word count, not a judgement
     of relevance. The model writes none of the block. This is the supported
     part of the answer.
  2. WARNING lines, when a check on the model's text failed (below).
  3. NOTE lines: information that is not a failed check (below).
  4. The model's text, under a fixed label that says it is the model's summary
     and says what was and was not compared with the block.
  When the whole output is longer than a screen the warnings are repeated as
  the last line.

The model's text is REPLACED by fixed text, and no block of documents is shown
because there is none, when no tool result supports anything:
    - no tool was called (REFUSAL_NO_TOOL);
    - every search came back empty and no document was fetched (NO_RESULTS_TEXT,
      followed by the searches as they were sent);
    - every lookup failed (REFUSAL_TOOL_FAILED, followed by what failed);
    - the run was stopped at the step limit.

What is compared in the model's text, after normalising it (normalize_reference_text):
  a. document numbers, only against the "document_number" fields the tools
     returned, and "NN FR NNNN" citations, only against the "citation" fields.
     A number that only appears inside the free text of a returned document (a
     title, an abstract) gets its own warning: mentioned inside a returned
     document, not returned as one. One that stands in a returned "docket_ids"
     field is a docket id the tool returned and gets a NOTE, not a warning, as
     long as the text names the document whose field holds it and does not call
     the docket id a document; otherwise it gets a warning. One that the
     QUESTION names and no tool returned gets a warning in other words: the
     user asked about it, and the lookup failed or was not tried;
  b. every other number of two or more digits, and every group of numbers
     joined by a hyphen, a dot, a slash or a colon (63.1234, 119-45, 11:59),
     against the text of the successful tool results, the question, and the
     current year; and every "NN CFR part NN" reference, against the CFR
     references the tools returned. Since review round 4 a two-digit number
     is read with a unit or a label joined to it ("a 60-day period", "$83M",
     "No.83"), and two numbers joined by ONE hyphen are compared one by one
     ("parts 70-71"), except, since round 5, a docket id (letters and a
     hyphen, then a year: "FAA-2025-0491"), which must match a returned
     group whole. NOT compared: a single digit ("5 percent"), a number in
     words, a two-digit ordinal ("the 21st") and two digits that follow
     letters ("COVID-19", "FY27"). A CFR reference in the model's text is
     read within one line only; the numbering of a list or of a table's
     first column is not a claim;
  b2. the year of a full date (day, month, year) in a tool result counts as
     returned; the year of a month and year alone ("June 2025") does not;
  c. every date, against the dates in the tool results, the dates of the
     searches as they were sent (the block shows them), today, and the dates in
     the question in any of the written forms _DATE_PATTERNS reads (since round
     4 also "15-Nov-2026", "November the 15th", "November fifteenth, 2026" and
     "the fifteenth of November"); a day and
     month without a year in the question takes the year or years the question
     names, or the current year when it names none;
  d. every URL, against the URL fields the tools returned; since round 4 also
     an address written without "https://" when it has a path
     ("regulations.gov/docket/X"; a bare "regulations.gov" names a site and
     is not compared);
  e. a stated count of documents ("seven final rules", "only two"), against the
     number each search returned, the totals the API reported and the number
     of documents in the block. Code knows those figures and nothing else
     about a count, so a count is a WARNING in three cases only (second
     rehearsal pass, 2026-10-07: the wider rule warned eight of the 39
     answers a reader called clean):
       e1. the number returned presented as all there are: a search returned
           fewer documents than matched, the count equals what a search
           returned or the size of the block and no total, the sentence has
           no subset or sample wording (_SUBSET_WORDS: newest, first,
           returned, shown, given, other, remaining, "here are", "of the
           5", ...), no larger total stands in the same paragraph or, given
           as a count of matches, in an earlier one, and the question did
           not ask for that many ("the five newest"; a sentence with "only",
           "exactly" or the like is not excused by the question or by an
           earlier paragraph). Round 4: when the sentence says with its own
           verb that the count MATCHED ("ten documents matched the search",
           "the search matched ten documents"; since round 5 also "ten
           documents were matched by the search"), a subset word counts only
           within three words of the count, so "among Coast Guard final
           rules" at the end of the sentence no longer excuses it. Round 5:
           "among" as the only subset word of a sentence counts only within
           three words of the count either way;
       e2. a count that equals the total of a search which returned fewer
           documents than matched, in a sentence with none of the words of
           _MATCH_WORDS (match, search, results, hits, returned, API, mention,
           contain): the total counts matches of the search words, and the
           sentence gives it as a count of documents. It reads only phrases
           that find_count_claims reads ("31 proposed rules", "27 were
           published"). Not when an earlier sentence of the same paragraph
           gave that total with one of those words and this one refers back
           to it ("all 31", "the 31", "these 31", "those 31"; since round 5);
       e5. more documents than every search of this run matched and than the
           block holds.
     Every other comparison of a count is one NOTE line that says it is
     information and not a finding: a count that equals no total, no number
     returned and not the size of the block, and a count that equals a figure
     of the block when the text names fewer documents by number. No line at
     all: a count no larger than the number of documents the text names (the
     model's own grouping of them), and a remainder code can work out again,
     in words that say it is one ("the other 4 returned documents" after one
     of five was named, "the other 6 matches were not returned" of 11). Such
     a remainder is not an unverified number under (b) either, and neither
     are the counts the block prints in its headings ("Documents returned
     (10)");
     a stated count of CFR parts is compared with the list the lookup
     returned and stays a warning;
  e3. when the text names none of the returned documents (by number, by
     complete title or by URL): a WARNING, unless a sentence gives a number
     that a search matched or returned together with one of those words, or
     the block holds one document only; then a NOTE. Code cannot tell "I did
     not list them" from an invented claim in the next sentence;
  e4. a NOTE, never a warning: a sentence with "newest", "most recent" or
     "latest" that names exactly one returned document and has none of the
     words of _MATCH_WORDS, when neither the title nor the abstract of that
     document holds one word of any search that returned it. It rests on a
     count of words and can be wrong both ways;
  f. "the last N days", against the searches: it stands only when a search in
     this run had its dates computed by the tool from that N;
  g. a phrase of two or more words in quotation marks, against the words of the
     tool results, the question and the search terms: quotation marks claim
     "word for word", so an invented or reworded title in them gets a warning.
     Every string of a tool result may be quoted, the tool's own sentences
     included; a phrase with "..." in it is compared piece by piece, the
     pieces in order inside one string of a tool result (since round 5);
  h. a line of the model's text that starts like one of the kit's own (WARNING:,
     NOTE:, the heading of the block, the label of the summary) is shown with
     MODEL_LINE_MARK in front, and the last two also draw a WARNING. Since
     round 5 look-alike characters are folded before the comparison (a curly
     apostrophe, a no-break or zero-width space), and terminal control
     characters are taken out of the model's text before anything else.
  A field that the tool had to cut short never counts as a source for (a) to (c).

What is NOT compared, and cannot be by rules like these: the wording of titles
and summaries outside quotation marks, which agency did what, whether a real
number is attached to the right document, WHETHER A RETURNED DOCUMENT IS WHAT
THE QUESTION ASKED FOR, and any other claim with no digits, dates or URLs in
it. An invented rule with no number and no quotation marks passes without a
warning. So does a returned document that the text calls "the newest rule on
X" when its own title and abstract are about something else: in the rehearsal
on real model text (round 3, 2026-10-07) that and a search total given as a
count of documents on a topic were the commonest real errors, and rule e2
sees only some wordings of the second. The block is there so the reader has
the supported facts, and the word counts, next to the unsupported prose.

Nothing in this file imports AWS. The model is passed in, so tests pass a
scripted fake and real runs pass ChatBedrockConverse (agent/model.py).
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import re
import unicodedata
import urllib.parse
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph

from . import fr_tools

# One model turn plus one tool turn is two graph steps, and the last model turn
# and the finalize node are two more. Measured with the fake model on
# langgraph 1.2.14: a limit of 12 lets four tool rounds finish and stops a fifth.
DEFAULT_RECURSION_LIMIT = 12
MAX_QUESTION_CHARS = 2000
# A model may ask for several tool calls in one turn. Each is one request to the
# Federal Register, so the number run per turn is capped; the rest are refused
# with an error the model can read. With the step limit above this bounds one
# question at 6 tool turns x 3 = 18 requests: measured, a model that never finishes
# gets six tool turns before the step limit stops it (a question that finishes has
# had at most four, so at most 12 requests).
MAX_TOOL_CALLS_PER_TURN = 3
# The block lists at most this many documents and says how many it left out.
BLOCK_MAX_DOCUMENTS = 30
# "Longer than a screen": more lines than this, or more characters than this many
# 80-column lines. Then the warnings are repeated as the last line.
SCREEN_LINES = 24
MAX_ITEMS_PER_WARNING = 20

BLOCK_HEADER = ("FROM THE FEDERAL REGISTER API. Built by code from the tool results of this run. "
                "The model did not write this block.")
SUMMARY_LABEL = (
    "MODEL'S SUMMARY. Written by the model, not by code. Compared with the tool results: its document "
    "numbers, Federal Register citations, other numbers of two or more digits, dates, URLs (with or "
    "without https://), counts of documents, and phrases of two or more words in quotation marks. NOT "
    "checked: its wording, its titles and descriptions unless quoted, which agency did what, whether a "
    "document it lists is about what you asked, single digits, numbers written as words, a two-digit "
    "number that is an ordinal such as 21st or follows letters as in COVID-19 or FY27, and anything "
    "else with no digits in it."
)
# Fixed words under every search in the block.
MATCHES_NOT_TOPIC = (
    "This total counts documents that match the search words, not documents about the topic. "
    "The documents listed below were not checked for relevance.")
ZERO_MATCHES_NOT_TOPIC = (
    "That is about these search words: a document on the topic that uses other words would not match.")
SEARCH_WORDS_LEGEND = (
    '"Search words" lines are counts made by code, not judgements of relevance: the words of the '
    "search term (leaving out " + ", ".join(fr_tools.SEARCH_STOP_WORDS) + "), each counted when it "
    "stands in the title or in the abstract as a whole word, ignoring upper and lower case and a "
    "final s. A document can hold every search word and be about something else.")
NO_RESULTS_TEXT = (
    "No documents. Every Federal Register search this agent sent returned no matching documents. "
    "That is a statement about the searches listed below, which the model chose, not about your "
    "question: a different search might find something. The model's own text has been withheld."
)
REFUSAL_NO_TOOL = (
    "No checked answer. The agent did not call a Federal Register tool for this question, so "
    "nothing it wrote could be checked against the Federal Register, and its text has been "
    "withheld. This agent only answers questions about documents published in the Federal Register."
)
REFUSAL_TOOL_FAILED = (
    "No checked answer. The Federal Register lookups in this run failed and no document was "
    "returned, so nothing could be checked, and the model's text has been withheld."
)
REFUSAL_NOTHING_RETURNED = (
    "No checked answer. No tool returned a document in this run, so nothing could be checked, "
    "and the model's text has been withheld."
)
WARNING_PREFIX = "WARNING: "
# A NOTE is information for the reader. It is not a failed check and does not make an answer "warned".
NOTE_PREFIX = "NOTE: "

SYSTEM_PROMPT = """You answer questions about documents published in the U.S. Federal Register.

Today's date is {today}. When the question says "the last N days", pass
last_n_days=N to the search tool and leave date_from and date_to out: the tool
works out the date range itself. Use date_from and date_to only for explicit dates.

How your answer is shown. The reader first sees a block that code builds from
the tool results: every search you sent with the total the API reported, and
every document returned with its number, type, date, agencies, title and URL.
Under each search the block says that the total counts documents that match
the search words, not documents about the topic, and under each document it
says how many of your search words stand in its title and in its abstract.
Your text comes after it, labelled as the model's summary. Code then compares
every document number, citation, number, date, URL and count of documents in
your text with the tool results, and puts a warning in front of your text for
anything it cannot find there. It does the same when you write "the last N
days" without having passed last_n_days=N to a search, and when you give a
search total as a count of documents without saying it is a count of matches.

Rules:
1. Use the tools. Do not answer from memory about what was published.
2. search_federal_register finds documents. doc_type RULE means a final rule,
   PRORULE a proposed rule, NOTICE a notice, PRESDOCU a presidential document.
   Put an exact phrase in double quotes inside term. The tools take only the
   arguments they list; any other argument is refused.
3. get_federal_register_document returns the details of one document number.
   Call it only when the question needs more than the search result gives.
4. Cite every document you mention by its document number and its html_url,
   exactly as the tools returned them. Never invent a document number, a
   citation, a date, a count or a URL, and never mention a document the tools
   did not return. Use quotation marks only around words copied exactly from
   a tool result; code compares every quoted phrase with the tool results.
5. If a search returns count 0, say plainly that nothing matched that search.
   Do not guess, and do not say that nothing was published on the subject:
   a document that uses other words would not have matched.
   "count" is the API's total; "returned" is how many of them you were given.
   Never present the number returned as the number that exist.
6. If a tool returns an error, say what failed. Do not pretend it worked.
7. A text field that ends in [TRUNCATED] was cut short. Do not quote numbers or
   dates from it, and do not guess what the missing part says.
8. Keep the answer short: a sentence of summary, then one line per document
   with agency, title, publication date, document number and URL.
9. Ask for at most three tool calls in one turn.
10. "count" is the number of documents that MATCH THE SEARCH WORDS. It is not
    the number of documents about the subject: a document matches when the
    words occur anywhere in it, and many matches are about something else.
    Always word a total as a count of matches: "N documents matched the search
    for X". Never word it as a count of documents on a subject: not "the
    agency published N rules on X", and not "N rules on X were published".
11. Read the title and the abstract of every returned document before you list
    it. When they do not show that the document is what the question asked
    for, do not list it as an answer. Say next to it that it matched the
    search but that its title and abstract are about something else, or leave
    it out and say how many returned documents you left out.
    search_words_in_title and search_words_in_abstract only count words: a
    document can contain every search word and still be about something else.
12. Write "the newest", "the most recent", "the latest" or "the" document on a
    subject only about a document whose own fields (type, title, abstract,
    action) show that it is the kind of document the question asked for. When
    no returned document clearly fits, say what the search returned and that
    none of it clearly fits the question. The first result is the newest match
    of your search words. That is not always the newest document of the kind
    asked for.
13. A comparison ("more than", "fewer than") or a "most" needs a figure that a
    tool returned for each side. With a figure for one side only, or with
    figures only for the documents returned and not for everything that
    matched, say that the tool results do not show it.
"""

# --------------------------------------------------------------------------
# normalising text, and finding numbers, dates and URLs in it
# --------------------------------------------------------------------------
# Characters that are not in Unicode's dash category but are written where a hyphen belongs.
_DASH_LIKE = "\u2212\u2796\u30fc\uff5e\u2053\u3030~"
_SOFT_HYPHEN = "\u00ad"
_MARKUP = "*_`\\"
# The long dashes. Between two words they are punctuation, and between two fields of a list
# line too: "2026-19964 \u2014 2026-09-30 \u2014 NHTSA" is a number, a date and an agency. Inside the
# fold each becomes this private-use character until _join_dashes decides what it stands for.
_LONG_DASHES = "\u2013\u2014\u2015\u2e3a\u2e3b\ufe58\ufe31\ufe32"
_LONG = "\ue000"


def _fold(text: str, soft_hyphen: str) -> str:
    """One normal form of a text. soft_hyphen is what U+00AD becomes ("-" or "")."""
    text = html.unescape(text or "")
    text = urllib.parse.unquote(text)
    text = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    for ch in text:
        if ch == _SOFT_HYPHEN:
            out.append(soft_hyphen)
            continue
        category = unicodedata.category(ch)
        if category == "Nd":            # every decimal digit of every script becomes 0-9
            out.append(str(unicodedata.decimal(ch)))
        elif ch in _LONG_DASHES:                    # decided below, by what stands on each side
            out.append(_LONG)
        elif category == "Pd" or ch in _DASH_LIKE:   # every other dash becomes "-"
            out.append("-")
        elif category in {"Cf", "Mn", "Me"}:        # format characters and marks print as nothing
            continue
        elif ch in "\n\r\v\f\x85\u2028\u2029":       # every kind of line break, kept for one step
            out.append("\n")
        elif category == "Cc":                      # other control characters, tab included
            out.append(" ")
        elif ch in _MARKUP:                         # markdown emphasis and backslash escapes
            continue
        else:
            out.append(ch)
    text = "".join(out).upper()
    # A hyphen that starts a line and is followed by a space is a list bullet, not part of a
    # number: "...Model Years 2022\n- 2026-19071" must not read as 2022-2026-19071. The number
    # of a numbered list goes the same way, and so does the numbering column of a table.
    text = re.sub(r"(^|\n)[ \t]*[-" + _LONG + r"](?=[ \t])", r"\1; ", text)
    text = _LIST_NUMBER.sub(r"\1; ", text)
    text = _blank_table_numbering(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"-{2,}", _LONG, text)   # "--" is written where a long dash belongs
    return _join_dashes(text).strip()


_DIGIT_GROUP_END = re.compile(r"[0-9./-]*$")
_DIGIT_GROUP_START = re.compile(r"[0-9./-]*")
_LONG_DASH_RUN = re.compile("( ?)" + _LONG + "+( ?)")
_SPACED_HYPHEN = re.compile(r"(?<=\d) - (?=\d)")
_TABLE_ROW_NUMBER = re.compile(r"([ \t]*\|[ \t]*)(\d{1,3})[.)]?(?=[ \t]*\|)")


def _plain_numbers_on_both_sides(text: str, start: int, end: int) -> bool:
    """True when the digits that end at `start` and the digits that begin at `end` are two
    plain numbers, neither of them already part of a group such as 2026-19964 or 10/01/2026."""
    left = _DIGIT_GROUP_END.search(text[:start]).group(0)
    right = _DIGIT_GROUP_START.match(text[end:]).group(0).rstrip(".")
    return left.isdigit() and right.isdigit()


def _join_dashes(text: str) -> str:
    """Decide what each long dash and each hyphen with a space on both sides stands for.

    Between two plain numbers it is a hyphen: "2026 - 18889" and "2026\u201318889" are a document
    number written to slip past, and "September 1 \u2013 30" is a range. Where either side is
    already a group of numbers it separates two things: "2026-19964 \u2014 2026-09-30" is a
    document number and a date, and "2026-09-07 \u2013 2026-10-07" is two dates (review round 4,
    M2: read as one group, each was reported as an invented number in an honest list). A
    hyphen with a space on one side only stays part of the number it touches ("2026- 18889",
    a number broken over two lines)."""
    def long_dash(match: re.Match) -> str:
        before, after = text[: match.start()], text[match.end():]
        if before[-1:].isdigit() and after[:1].isdigit():
            return "-" if _plain_numbers_on_both_sides(text, match.start(), match.end()) else " - "
        return match.group(1) + "-" + match.group(2)

    def spaced(match: re.Match) -> str:
        return "-" if _plain_numbers_on_both_sides(match.string, match.start(), match.end()) else " - "

    text = _LONG_DASH_RUN.sub(long_dash, text)
    text = _SPACED_HYPHEN.sub(spaced, text)
    # A hyphen with a space on one side only, between two digits.
    return re.sub(r"(?<=\d)(?: -|- )(?=\d)", "-", text)


def _blank_table_numbering(text: str) -> str:
    """Blank the numbering column of a table: a whole number alone in the first cell of a row,
    when the rows count 1, 2, 3 and so on. Like the number of a numbered list it is not a claim
    (review round 4: "| 11 | 2026-18055 | ..." in a table of twenty returned documents was
    reported as seven invented numbers)."""
    last = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        match = _TABLE_ROW_NUMBER.match(line)
        if match:
            value = int(match.group(2))
            if value == 1 or value == last + 1:
                lines[index] = match.group(1) + ";" + line[match.end():]
                last = value
            else:
                last = 0
        elif not line.lstrip().startswith("|"):
            last = 0
    return "\n".join(lines)


def normalize_reference_text(text: str) -> str:
    """The normal form the checks run on: HTML entities and percent-escapes decoded, NFKC,
    every digit as 0-9, every Unicode dash and the soft hyphen as "-", all other format
    characters dropped, markdown emphasis and backslashes stripped, upper case, and all
    whitespace (newlines included) collapsed, with none left around a hyphen between digits."""
    return _fold(text, "-")


def _variants(text: str) -> list[str]:
    """The normal forms to check. A soft hyphen may stand for a hyphen (2026<SHY>18889) or for
    nothing (2026-18<SHY>889), so a text that has one is checked both ways."""
    first = _fold(text, "-")
    if _SOFT_HYPHEN not in html.unescape(urllib.parse.unquote(text or "")):
        return [first]
    return [first, _fold(text, "")]


# Federal Register document numbers, after normalisation (upper case, plain hyphens):
#   2026-19964, 2010-1234   four-digit year
#   06-4321, 99-12345       two-digit year (documents before about 2010)
#   E9-31418, Z7-12345      letter-digit prefix
#   C1-2026-12345           correction prefix in front of any of the above
# Not a document number: the tail of a longer hyphenated identifier (NHTSA-2025-0491 is a
# docket id), or the head of one (2026-19964-2).
_DOC_NUMBER = re.compile(
    r"(?<![A-Z0-9])(?<![A-Z0-9]-)(?:[A-Z]\d-)?(?:\d{4}|[A-Z]\d)-\d{3,6}(?![A-Z0-9]|-\d)"
    r"|(?<![A-Z0-9])(?<![A-Z0-9]-)\d{2}-\d{3,6}(?![A-Z0-9]|-\d)"
)
# Federal Register citations: volume, "FR" in any of its spellings, an optional "at" or
# "page", then the page.
_FR_CITATION = re.compile(
    r"(?<![A-Z0-9])(\d{1,3})[ -]?(?:F\.? ?R\.?|FED(?:ERAL)?\.? ?REG(?:ISTER)?\.?)[ -]?"
    r"(?:AT |PP?\.? ?|PAGES? )?(\d{1,3}(?:,\d{3})+|\d{1,6})(?![A-Z0-9])"
)
# Code of Federal Regulations references: title, "CFR", and optionally a part or a section.
# The title is not the tail of a date or of another group of numbers ("2026-11-05 CFR ...").
_CFR = re.compile(r"(?<![A-Z0-9])(?<!\d[-./:,])(\d{1,2}) ?C\.?F\.?R\.?(?: ?(?:PARTS?|PT\.?|SECTIONS?|SEC\.?|\u00a7+))?"
                  r"(?: ?(\d{1,4}[A-Z]?(?:\.\d+[A-Z]?)?))?(?![A-Z0-9])")
_URL = re.compile(r"HTTPS?://[^\s<>\"'\]\)]+")
# An address written without "https://": a host name that ends in one of these, then a slash
# and a path ("regulations.gov/docket/FAA-2026-2730", "www.faa.gov/aircraft", "//www.faa.gov/x").
# A host name with no path ("regulations.gov") is the name of a site and is not compared.
_BARE_URL = re.compile(r"(?<![A-Z0-9@./:-])(?://)?(?:[A-Z0-9-]+\.)+(?:GOV|COM|ORG|NET|EDU|MIL|INT|INFO|IO|US)"
                       r"/[^\s<>\"'\]\)]+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_COMPOUND = re.compile(r"\d+(?:[-./:]\d+)+")
_DIGIT_RUN = re.compile(r"\d{3,}")
# A two-digit number. Read: one standing by itself ("60 days"), one with a unit joined behind it
# ("a 60-day period", "an 83-page rule", "45mph", "$83M", "83T"), one after "~" or a minus sign,
# and one after a label ("No.83", "Pages:83"). Until review round 4 only the first was read, and
# "a 60-day comment period" passed where "a comment period of 60 days" was warned (M1).
# NOT read, because these are names far more often than claims: two digits that follow letters
# or a hyphen after letters ("COVID-19", "FY27", "MD-11", "PM10"), and an ordinal ("21st
# century", "the 83rd"). A clock time ("11:59") is a group, compared whole like 63.1234.
_TWO_DIGITS = re.compile(
    r"(?:(?<![A-Z0-9.,/:-])|(?<=[A-Z][.:])|(?<=[ (]-)|(?<=^-))"
    r"\d{2}(?!\d)(?![.,/:-]\d)(?!(?:ST|ND|RD|TH)(?![A-Z]))")
# The numbering of a list is not a claim: "1. ...", "12) ...", "(3) ...".
_LIST_NUMBER = re.compile(r"(^|\n)[ \t]*\(?\d{1,3}[.)](?=[ \t])")
_YEAR_RANGE = re.compile(r"(\d{4})-(\d{4})")

_MONTHS = {name: number for number, names in enumerate([
    ("JANUARY", "JAN"), ("FEBRUARY", "FEB"), ("MARCH", "MAR"), ("APRIL", "APR"), ("MAY",),
    ("JUNE", "JUN"), ("JULY", "JUL"), ("AUGUST", "AUG"), ("SEPTEMBER", "SEPT", "SEP"),
    ("OCTOBER", "OCT"), ("NOVEMBER", "NOV"), ("DECEMBER", "DEC")], 1) for name in names}
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + ")"
# The day of a month written as a word: "fifteenth", "twenty-first".
_DAY_WORDS = {name: number for number, name in enumerate(
    ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH",
     "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH", "FIFTEENTH", "SIXTEENTH", "SEVENTEENTH",
     "EIGHTEENTH", "NINETEENTH", "TWENTIETH", "TWENTY-FIRST", "TWENTY-SECOND", "TWENTY-THIRD",
     "TWENTY-FOURTH", "TWENTY-FIFTH", "TWENTY-SIXTH", "TWENTY-SEVENTH", "TWENTY-EIGHTH",
     "TWENTY-NINTH", "THIRTIETH", "THIRTY-FIRST"], 1)}
_DAY_WORD = "(" + "|".join(sorted(_DAY_WORDS, key=len, reverse=True)) + ")"
_THE_BEFORE_ORDINAL = r"THE (?=\d{1,2}(?:ST|ND|RD|TH)(?![A-Z]))"
_DATE_PATTERNS = [
    # (kind, pattern). Tried in this order; what one pattern matched is blanked for the next.
    ("ymd", re.compile(r"(?<![\d/-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d-])")),
    # 2026/09/01 and 2026.09.01, not the date inside a URL path (.../documents/2026/09/01/...)
    ("ymd", re.compile(r"(?<![\d/.-])(\d{4})[/.](\d{1,2})[/.](\d{1,2})(?![\d/-]|\.\d)")),
    # "September 1-30, 2026", "Sept. 1 to 30, 2026", "September 1 and 30, 2026": two dates
    ("md_range_words", re.compile(
        r"(?<![A-Z])" + _MONTH + r"\.? (\d{1,2})(?:ST|ND|RD|TH)? ?(?:-|TO|THROUGH|THRU|UNTIL|AND) ?"
        r"(\d{1,2})(?:ST|ND|RD|TH)?,? (\d{4})(?!\d)")),
    # "November the 15th, 2026". After "the" the day must carry its ending: "in September the
    # 10 newest notices" is not a date.
    ("mdy_words", re.compile(r"(?<![A-Z])" + _MONTH + r"\.? (?:" + _THE_BEFORE_ORDINAL
                             + r")?(\d{1,2})(?:ST|ND|RD|TH)?,? (\d{4})(?!\d)")),
    # "November fifteenth, 2026": a day in words counts only with a year after it
    ("mdy_words", re.compile(r"(?<![A-Z])" + _MONTH + r"\.? (?:THE )?" + _DAY_WORD + r",? (\d{4})(?!\d)")),
    ("dmy_words", re.compile(r"(?<!\d)(\d{1,2})(?:ST|ND|RD|TH)? (?:OF )?" + _MONTH + r"\.?,? (\d{4})(?!\d)")),
    ("dmy_words", re.compile(r"(?<![A-Z-])" + _DAY_WORD + r" OF " + _MONTH + r"\.?,? (\d{4})(?!\d)")),
    # 15-Nov-2026, 15-Nov-26
    ("dmy_words", re.compile(r"(?<![\d/-])(\d{1,2})-" + _MONTH + r"-(\d{4}|\d{2})(?![\d-])")),
    ("mdy_digits", re.compile(r"(?<![\d/-])(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?![\d/-])")),
    ("my_words", re.compile(r"(?<![A-Z])" + _MONTH + r"\.?,? (?:OF )?(\d{4})(?!\d)")),
    ("md_words", re.compile(r"(?<![A-Z])" + _MONTH + r"\.? (?:" + _THE_BEFORE_ORDINAL
                            + r")?(\d{1,2})(?:ST|ND|RD|TH)?(?![\dA-Z])")),
    # "November the fifteenth": a day in words counts after "the", or before "of" (next line)
    ("md_words", re.compile(r"(?<![A-Z])" + _MONTH + r"\.? THE " + _DAY_WORD + r"(?![A-Z-])")),
    ("dm_words", re.compile(r"(?<![\d.,/:-])(\d{1,2})(?:ST|ND|RD|TH)? (?:OF )?" + _MONTH + r"(?![A-Z])")),
    ("dm_words", re.compile(r"(?<![A-Z-])" + _DAY_WORD + r" OF " + _MONTH + r"(?![A-Z])")),
]


def find_document_numbers(text: str) -> set[str]:
    """Document numbers mentioned in text, normalised. A year range such as 2027-2031 is not one."""
    found = set()
    for variant in _variants(text):
        for match in _DOC_NUMBER.findall(variant):
            head, _, tail = match.rpartition("-")
            if (len(head) == 4 and head.isdigit() and len(tail) == 4
                    and 1900 <= int(head) < int(tail) <= 2100):
                continue  # an ascending range of years, not a document number
            found.add(match)
    return found


def find_fr_citations(text: str) -> set[str]:
    """Federal Register citations mentioned in text, normalised to 'VOLUME FR PAGE'."""
    return {
        f"{int(volume)} FR {int(page.replace(',', ''))}"
        for variant in _variants(text)
        for volume, page in _FR_CITATION.findall(variant)
    }


def find_references(text: str) -> set[str]:
    return find_document_numbers(text) | find_fr_citations(text)


def find_cfr_references(text: str, across_lines: bool = True) -> set[tuple[str, str]]:
    """CFR references in text as (title, part or section): ("49", "571.305"), ("14", "39"),
    ("49", "") when only the title is given.

    across_lines=False reads each line by itself. The model's text is read that way: "Pages:
    3" followed by a line "CFR: 14 CFR part 39" is not a reference to title 3 (review round 4,
    M3: a warning named a CFR title the model never wrote). A tool result is read whole."""
    parts = [text] if across_lines else _LINE_BREAKS.sub("\n", html.unescape(text or "")).split("\n")
    return {(str(int(title)), ref) for part in parts for variant in _variants(part)
            for title, ref in _CFR.findall(variant)}


def find_urls(text: str) -> set[str]:
    """URLs in text that start with http:// or https://, normalised, without trailing
    punctuation or a trailing slash."""
    return {match.rstrip(".,;:!?").rstrip("/") for variant in _variants(text)
            for match in _URL.findall(variant)}


def find_bare_urls(text: str) -> set[str]:
    """Addresses written without a scheme and with a path (see _BARE_URL), normalised the same way."""
    return {match.rstrip(".,;:!?").rstrip("/") for variant in _variants(text)
            for match in _BARE_URL.findall(variant)}


def _url_key(url: str) -> str:
    """A normalised URL without its scheme and without a leading "www.": what an address
    written without a scheme is compared on."""
    return re.sub(r"^(?:HTTPS?:)?(?://)?(?:WWW\.)?", "", url)


def _urls_as_written(text: str) -> dict[str, str]:
    """Normalised address -> the same address as the text writes it, for the warning line."""
    written: dict[str, str] = {}
    for token in re.findall(r"[^\s<>\"'\]\)\[\(]+", unicodedata.normalize("NFKC", html.unescape(text or ""))):
        for found in find_urls(token) | find_bare_urls(token):
            written.setdefault(found, token.rstrip(".,;:!?"))
    return written


def _valid_date(year: int, month: int, day: int) -> bool:
    try:
        _dt.date(year, month, day)
    except ValueError:
        return False
    return True


def _day(token: str) -> int:
    return int(token) if token.isdigit() else _DAY_WORDS[token]


def _scan_dates(folded: str) -> tuple[dict, str]:
    """Dates written in an already normalised text. Returns ({"full": {(y, m, d)},
    "month_year": {(y, m)}, "month_day": {(m, d)}}, the text with those dates blanked)."""
    found: dict = {"full": set(), "month_year": set(), "month_day": set()}
    for kind, pattern in _DATE_PATTERNS:
        def take(match: re.Match, kind: str = kind) -> str:
            groups = match.groups()
            if kind == "ymd":
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            elif kind == "md_range_words":
                year, month = int(groups[3]), _MONTHS[groups[0]]
                first, last = int(groups[1]), int(groups[2])
                if not (1800 <= year <= 2200 and _valid_date(year, month, first)
                        and _valid_date(year, month, last)):
                    return match.group(0)
                found["full"].update({(year, month, first), (year, month, last)})
                return " "
            elif kind == "mdy_words":
                year, month, day = int(groups[2]), _MONTHS[groups[0]], _day(groups[1])
            elif kind == "dmy_words":
                year, month, day = int(groups[2]), _MONTHS[groups[1]], _day(groups[0])
                if year < 100:
                    year += 2000
            elif kind == "mdy_digits":
                year, month, day = int(groups[2]), int(groups[0]), int(groups[1])
                if year < 100:
                    year += 2000
            elif kind == "my_words":
                year, month = int(groups[1]), _MONTHS[groups[0]]
                if not 1800 <= year <= 2200:
                    return match.group(0)
                found["month_year"].add((year, month))
                return " "
            elif kind in {"md_words", "dm_words"}:
                month, day = ((_MONTHS[groups[0]], _day(groups[1])) if kind == "md_words"
                              else (_MONTHS[groups[1]], _day(groups[0])))
                if not _valid_date(2024, month, day):  # 2024 is a leap year
                    return match.group(0)
                found["month_day"].add((month, day))
                return " "
            if not (1800 <= year <= 2200 and _valid_date(year, month, day)):
                return match.group(0)  # not a date: leave it for the number check
            found["full"].add((year, month, day))
            return " "

        folded = pattern.sub(take, folded)
    return found, folded


def find_dates(text: str) -> dict:
    """Dates written in text: full dates, "September 2026" and "September 30" forms."""
    merged: dict = {"full": set(), "month_year": set(), "month_day": set()}
    for variant in _variants(text):
        found, _ = _scan_dates(variant)
        for key in merged:
            merged[key] |= found[key]
    return merged


_YEAR_ALONE = re.compile(r"(?<![A-Z0-9.,/:-])((?:19|20)\d{2})(?![A-Z0-9/:-]|[.,]\d)")


def find_years(text: str) -> set[int]:
    """The years a text names: the year of every date in it and every four-digit number from
    1900 to 2099 that stands by itself (not the head of a document number such as 2026-19964)."""
    years: set[int] = set()
    for variant in _variants(text):
        found, without_dates = _scan_dates(variant)
        years |= {y for y, _, _ in found["full"]} | {y for y, _ in found["month_year"]}
        years |= {int(y) for y in _YEAR_ALONE.findall(without_dates)}
    return years


def _scan_numbers(folded_without_dates: str) -> tuple[set[str], set[str]]:
    """(numbers, compounds) in a normalised text whose dates were already blanked. Numbers are
    the digit runs of three or more digits and the two-digit numbers _TWO_DIGITS reads;
    compounds are number groups such as 63.1234, 119-45 or 11:59. Thousands separators are
    dropped first, so 55,123 reads 55123. A single digit is not taken: "3 rules", "step 2"."""
    text = _THOUSANDS.sub("", folded_without_dates)
    return set(_DIGIT_RUN.findall(text)) | set(_TWO_DIGITS.findall(text)), set(_COMPOUND.findall(text))


def find_numbers(text: str) -> tuple[set[str], set[str]]:
    runs: set[str] = set()
    compounds: set[str] = set()
    for variant in _variants(text):
        _, without_dates = _scan_dates(variant)
        r, c = _scan_numbers(without_dates)
        runs |= r
        compounds |= c
    return runs, compounds


_NUMBER_WORDS = {
    "ZERO": 0, "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7, "EIGHT": 8,
    "NINE": 9, "TEN": 10, "ELEVEN": 11, "TWELVE": 12, "THIRTEEN": 13, "FOURTEEN": 14, "FIFTEEN": 15,
    "SIXTEEN": 16, "SEVENTEEN": 17, "EIGHTEEN": 18, "NINETEEN": 19, "TWENTY": 20, "THIRTY": 30,
    "FORTY": 40, "FIFTY": 50, "SIXTY": 60, "SEVENTY": 70, "EIGHTY": 80, "NINETY": 90, "BOTH": 2,
    "SINGLE": 1, "DOZEN": 12,
}
for _tens in ("TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"):
    for _unit in ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"):
        _NUMBER_WORDS[f"{_tens}-{_unit}"] = _NUMBER_WORDS[_tens] + _NUMBER_WORDS[_unit]
_NUMBER = r"(\d{1,6}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_DOC_NOUNS_PLURAL = ("DOCUMENTS|RULES|NOTICES|RESULTS|MATCHES|ITEMS|RECORDS|REGULATIONS|CORRECTIONS|"
                     "ENTRIES|HITS|PUBLICATIONS|RULEMAKINGS|PROCLAMATIONS|ORDERS")
_DOC_NOUNS_SINGULAR = ("DOCUMENT|RULE|NOTICE|RESULT|MATCH|ITEM|RECORD|REGULATION|CORRECTION|ENTRY|HIT|"
                       "PUBLICATION|RULEMAKING|PROCLAMATION|ORDER")
# Words that may not stand between the number and the noun: then it is not a count of documents
# ("one line per document", "30 days two rules", "2 of the 5 rules").
_NOT_BETWEEN = set(_NUMBER_WORDS) | {
    "PER", "OF", "IN", "FOR", "TO", "FROM", "THE", "A", "AN", "AND", "OR", "IS", "ARE", "WAS", "WERE",
    "AT", "ON", "BY", "WITH", "EACH", "EVERY", "THAT", "WHICH", "AS", "DAY", "DAYS", "YEAR", "YEARS",
    "MONTH", "MONTHS", "WEEK", "WEEKS", "PAGE", "PAGES", "PART", "PARTS", "SECTION", "SECTIONS",
    "AGENCY", "AGENCIES", "PERCENT", "TIMES", "HOURS", "MINUTES", "CFR", "FR", "USC", "TITLE",
}
_NOT_BEFORE = re.compile(r"(?:CFR|FR|REG\.?|TITLE|PARTS?|SECTIONS?|NO\.?|NUMBER|DOC\.?|DOCUMENT|ORDER|LAW|"
                         r"PAGES?|VOL\.?|VOLUME|RULES?|ITEM|STEP|\u00a7|\$) $")
_COUNT_CLAIM = re.compile(
    r"(?<![A-Z0-9.-])" + _NUMBER + r"((?: [A-Z][A-Z'-]*){0,3}?) (" + _DOC_NOUNS_PLURAL + "|"
    + _DOC_NOUNS_SINGULAR + r")(?![A-Z-])")
_COUNT_VERB = re.compile(
    r"(?<![A-Z0-9.-])" + _NUMBER + r" (?:WERE|WAS|ARE|IS|HAVE BEEN|HAS BEEN) "
    r"(?:PUBLISHED|ISSUED|RETURNED|FOUND|LISTED|IDENTIFIED|FINALIZED|FINALISED)(?![A-Z])")
_PARTS_CLAIM = re.compile(r"(?<![A-Z0-9.-])" + _NUMBER + r"((?: [A-Z][A-Z'-]*){0,2}?) PARTS?(?![A-Z-])")
# "the last 30 days", "the past seven days": a claim about the window that was searched.
_LAST_N_DAYS = re.compile(r"(?<![A-Z])(?:LAST|PAST|PREVIOUS|PRIOR) " + _NUMBER + r" DAYS?(?![A-Z])")
# A count of what was returned is honest when the sentence says it is a part of something, a
# sample of it, or what is left of it. Second rehearsal pass: the honest sentences the system
# prompt asks for ("I left out the other 4 returned documents", "of those 5, one ...", "I was
# given the 5 newest") are worded with these. MATCHED and SEARCH are not here on purpose: "Ten
# documents matched the search", when 20 matched and 10 were returned, is the error itself.
_SUBSET_WORDS = re.compile(
    r"\b(?:NEWEST|MOST RECENT|LATEST|FIRST|TOP|SHOWN|SHOWING|RETURNED|LISTED|DISPLAYED|RETRIEVED|"
    r"(?:WAS|WERE) GIVEN|GAVE ME|ABOVE|BELOW|FOLLOWING|THESE|THOSE|AMONG|OTHERS?|REMAINING|REST|LEFT OUT|"
    r"SAMPLE|EXAMPLES?|HERE (?:IS|ARE)|OF THEM|OF (?:THE|THESE|THOSE) " + _NUMBER + r")\b")
# A count that the sentence itself says MATCHED, with "matched" as its verb: "ten documents
# matched the search", "the search matched 10 documents". Such a sentence gives the count as
# the number of matches, so when it is only the number returned, a subset word somewhere else
# in the sentence does not excuse it. Review round 4, B1: "Ten documents matched the search for
# safety zone among Coast Guard final rules", when 20 matched, passed because of "among", and
# 23 of the 28 real answers of the second pass that say "matched the search" have "among" in
# that sentence. Not read this way: "five documents matching the search ... are:" and "10
# documents that match", which head a list (a real clean answer of the second pass), and the
# nouns "matches" and "hits". Since review round 5 (F6) also the passive voice, "two documents
# were matched by the search", which says the same.
_MATCHED_AFTER = re.compile(r"^ (?:MATCH(?:ED)?|(?:WERE|WAS|ARE|IS|HAVE BEEN|HAS BEEN) MATCHED)(?![A-Z])")
_MATCHED_BEFORE = re.compile(r"(?<![A-Z])MATCH(?:ED|ES)(?: (?:ONLY|JUST|EXACTLY|ABOUT|A TOTAL OF))? $")
# How many words on each side of such a count are looked at for a subset word that belongs to
# it: "the 10 newest documents matched", "these 10 documents matched".
_NEAR_WORDS = 3
# A count that refers back to a total given before: "all 31", "the 31", "those 31". Review round
# 5, F4: rule e2 excused any restatement of a total that an earlier sentence called matches, so
# "31 documents matched the search. 31 final rules ... were published by the FAA this year."
# passed; only a count with one of these words right before it is excused that way.
_REFERS_BACK = re.compile(r"(?<![A-Z])(?:ALL|THE|THESE|THOSE) $")
# Words that say a count is all there is. With one of them a count is not excused by the
# question having asked for that many ("Give me the five newest" / "Only five were published").
_ONLY_WORDS = re.compile(r"\b(?:ONLY|JUST|EXACTLY|ALTOGETHER|IN TOTAL|IN ALL|NO MORE|NO OTHERS?)\b")


# The words that say a count is a count of what a search matched, not of documents on a subject.
# A sentence that gives the total of a search which returned fewer documents than matched, and
# has none of these words, gets a warning (check_prose, rule e2). "Mention" and "contain" are
# here because a document that matches a full-text search does mention or contain the words.
_MATCH_WORDS = re.compile(r"\b(?:MATCH(?:ES|ED|ING)?|SEARCH(?:ES|ED|ING)?|RESULTS?|HITS?|RETURNED|RETURNS|API|"
                          r"MENTION(?:S|ED|ING)?|CONTAIN(?:S|ED|ING)?)\b")
# "The newest rule on X is <document>": the three words the system prompt's rule 12 names.
_SUPERLATIVE = re.compile(r"\b(?:NEWEST|MOST RECENT|LATEST)\b")
# Where one statement ends in the model's text besides the end of a sentence: an empty line, a
# line that ends in a colon, and the start of a list item. A wrapped line is not an end.
_LINE_BREAKS = re.compile("\r\n?|[\v\f\x85\u2028\u2029]")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n|(?<=:)[ \t]*\n|\n(?=[ \t]*(?:[*+\u2022-]|\(?\d{1,3}[.)])[ \t])")
# A whole number standing by itself in normalised text: not part of an identifier or a decimal.
_INTEGER_ALONE = re.compile(r"(?<![A-Z0-9.,/:-])\d{1,6}(?![A-Z0-9/:-]|[.,]\d)")


def _paragraphs(text: str) -> list[str]:
    """The model's text cut where a statement cannot run on (see _PARAGRAPH_BREAK)."""
    text = _LINE_BREAKS.sub("\n", html.unescape(text or ""))
    return [part for part in _PARAGRAPH_BREAK.split(text) if part.strip()]


def _sentences_by_paragraph(text: str) -> list[tuple[str, list[str]]]:
    """(normalised paragraph, its sentences) for each paragraph of a text, with dates blanked
    and thousands separators dropped."""
    out: list[tuple[str, list[str]]] = []
    for paragraph in _paragraphs(text):
        _, without_dates = _scan_dates(normalize_reference_text(paragraph))
        folded = _THOUSANDS.sub("", without_dates)
        out.append((folded, [part for part in re.split(r"(?<=[.!?;]) ", folded) if part.strip()]))
    return out


def _sentences(text: str) -> list[str]:
    """Normalised sentences of a text, with its dates blanked and thousands separators dropped."""
    return [sentence for _, sentences in _sentences_by_paragraph(text) for sentence in sentences]


def _integers_stated(folded: str) -> set[int]:
    """The whole numbers a normalised text states, in digits standing alone or in words."""
    stated = {int(n) for n in _INTEGER_ALONE.findall(folded)}
    stated |= {value for word, value in _NUMBER_WORDS.items()
               if re.search(r"(?<![A-Z-])" + word + r"(?![A-Z-])", folded)}
    return stated


def _question_counts(question: str) -> set[int]:
    """The counts a question names ("the five newest notices", "show me 3 rules"): its whole
    numbers other than dates and the N of "the last N days"."""
    _, without_dates = _scan_dates(normalize_reference_text(question))
    return _integers_stated(_LAST_N_DAYS.sub(" ", _THOUSANDS.sub("", without_dates)))


# Phrases in quotation marks: straight and curly, double and single. A single quotation mark
# opens only when no letter or digit stands before it (DOE's is a possessive), and an apostrophe
# between two letters does not close it ('the Department's rule').
# A quotation in double marks may run over one line break, not over an empty line or into a
# list item. Besides the straight and the curly pair: guillemets, the German low-high pair, and
# a curly mark closed by a straight one or the other way round (review round 4, m2).
_IN_QUOTE = r"(?:[^{marks}\n]|\n(?![ \t]*(?:\n|[*+\u2022-][ \t]|\(?\d{{1,3}}[.)][ \t]))){{2,2000}}"
_DOUBLE_MARKS = '"\u201c\u201d\u201e\u201f\u00ab\u00bb'
_QUOTED = [
    re.compile('"(' + _IN_QUOTE.format(marks=_DOUBLE_MARKS) + ')"'),
    re.compile("\u201c(" + _IN_QUOTE.format(marks=_DOUBLE_MARKS) + ")\u201d"),
    re.compile("\u00ab(" + _IN_QUOTE.format(marks=_DOUBLE_MARKS) + ")\u00bb"),
    re.compile("\u201e(" + _IN_QUOTE.format(marks=_DOUBLE_MARKS) + ")[\u201c\u201d\u201f\"]"),
    re.compile("\u201c(" + _IN_QUOTE.format(marks=_DOUBLE_MARKS) + ')"'),
    re.compile('"(' + _IN_QUOTE.format(marks=_DOUBLE_MARKS) + ")\u201d"),
    re.compile(r"(?<![A-Za-z0-9])'(?=\S)((?:[^'\n]|(?<=[A-Za-z])'(?=[A-Za-z])){2,2000}?)(?<=\S)'(?![A-Za-z0-9])"),
    re.compile("(?<![A-Za-z0-9])\u2018(?=\\S)((?:[^\u2018\u2019\n]|(?<=[A-Za-z])\u2019(?=[A-Za-z])){2,2000}?)"
               "(?<=\\S)\u2019(?![A-Za-z0-9])"),
]
QUOTE_MIN_WORDS = 2
QUOTE_MIN_CHARS = 8
# The tools' own vocabulary, which the system prompt gives to the model. In quotation marks
# these are not a quotation from a document.
QUOTABLE_ALWAYS = ("final rule", "proposed rule", "presidential document", "Federal Register",
                   "Code of Federal Regulations")


def _words(text: str) -> str:
    """Letters and digits only, upper case, one space between words: what "word for word" is
    compared on, so that punctuation and letter case do not matter."""
    return re.sub(r"[^A-Z0-9]+", " ", normalize_reference_text(text)).strip()


def find_quoted_phrases(text: str) -> list[str]:
    """Phrases of QUOTE_MIN_WORDS or more words that the text puts in quotation marks, as
    written, in order, each once."""
    text = unicodedata.normalize("NFKC", html.unescape(text or ""))
    found: list[tuple[int, str]] = []
    for pattern in _QUOTED:
        for match in pattern.finditer(text):
            phrase = " ".join(match.group(1).split()).strip(" .,;:!?")
            words = _words(phrase)
            if len(words.split()) >= QUOTE_MIN_WORDS and len(words) >= QUOTE_MIN_CHARS:
                found.append((match.start(), phrase))
    ordered: list[str] = []
    for _, phrase in sorted(found):
        if phrase not in ordered:
            ordered.append(phrase)
    return ordered


# Where a quotation says that words were left out: "...", "[...]", ". . .".
_ELLIPSIS = re.compile(r"\[?(?:\.[ ]?){3,}\]?")


def _quote_found(phrase: str, quotable: str) -> bool:
    """True when the words of a quoted phrase stand in `quotable` (words joined by one space).
    A phrase with an ellipsis in it says itself that words are missing, so each piece is
    looked for by itself, as whole words (review round 4: "provides draft recommendations for
    premarket submissions ... (RASDs)", every word of it from the abstract, was warned), in
    order and inside one string of the tool results (review round 5, F5)."""
    if _words(phrase) in quotable:
        return True
    pieces = [_words(piece) for piece in _ELLIPSIS.split(phrase)]
    if len(pieces) < 2:
        return False
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return False
    # Review round 5, F5: the pieces must stand in order inside ONE string of the tool results.
    # Until then each was looked for anywhere in the run, so "is superseding ... The Boeing
    # Company airplanes", spliced from the Airbus abstract and the Boeing one, passed.
    for string in quotable.split(" | "):
        padded, at = f" {string} ", 0
        for piece in pieces:
            where = padded.find(f" {piece} ", at)
            if where < 0:
                break
            at = where + len(piece) + 1
        else:
            return True
    return False


def _number_value(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def find_count_claims(text: str) -> list[dict]:
    """Stated counts of documents in text: [{"count": 7, "phrase": "SEVEN FINAL RULES",
    "sentence": "...", "paragraph": "..."}]. Only phrases that read as a count of documents
    are taken."""
    claims: list[dict] = []
    for paragraph_index, paragraph, sentence_index, sentence in (
            (i, p, j, s) for i, (p, sentences) in enumerate(_sentences_by_paragraph(text))
            for j, s in enumerate(sentences)):
        seen: set[tuple[int, str]] = set()
        for match in list(_COUNT_CLAIM.finditer(sentence)) + list(_COUNT_VERB.finditer(sentence)):
            token = match.group(1)
            value = _number_value(token)
            between = match.group(2).split() if match.re is _COUNT_CLAIM else []
            if any(word in _NOT_BETWEEN for word in between):
                continue
            if _NOT_BEFORE.search(sentence[: match.start()]):
                continue
            if match.re is _COUNT_CLAIM:
                plural = re.fullmatch(_DOC_NOUNS_PLURAL, match.group(3)) is not None
                if plural != (value != 1):
                    continue  # "the 2026 final rule", "1 rules": not a count
            if token.isdigit() and 1900 <= value <= 2100:
                continue  # "the 2026 rules": a year, checked by the number rule
            if (value, match.group(0)) not in seen:
                seen.add((value, match.group(0)))
                before, after = sentence[: match.start()], sentence[match.end():]
                claims.append({
                    "count": value, "phrase": match.group(0), "sentence": sentence,
                    "paragraph": paragraph, "paragraph_index": paragraph_index,
                    "sentence_index": sentence_index,
                    # the count is said to have matched (see _MATCHED_AFTER)
                    "says_matched": bool(match.re is _COUNT_CLAIM and (
                        _MATCHED_AFTER.search(after) or _MATCHED_BEFORE.search(before))),
                    # the few words on each side of the count, and those between number and noun
                    "near": " ".join(before.split()[-_NEAR_WORDS:] + between + after.split()[:_NEAR_WORDS]),
                    # the count refers back to a total said before ("all 31 final rules")
                    "refers_back": bool(_REFERS_BACK.search(before)),
                })
    return claims


def find_cfr_part_claims(text: str) -> list[dict]:
    """Stated counts of CFR parts ("amends five parts of 49 CFR")."""
    folded = _THOUSANDS.sub("", normalize_reference_text(text))
    claims = []
    for sentence in re.split(r"(?<=[.!?;]) ", folded):
        if "CFR" not in sentence:
            continue
        for match in _PARTS_CLAIM.finditer(sentence):
            if any(word in _NOT_BETWEEN for word in match.group(2).split()):
                continue
            if _NOT_BEFORE.search(sentence[: match.start()]):
                continue
            claims.append({"count": _number_value(match.group(1)), "phrase": match.group(0)})
    return claims


class AgentState(MessagesState):
    """messages (from MessagesState), today's date as the caller gave it, and the finalize
    node's report."""

    report: dict
    today: str


# --------------------------------------------------------------------------
# tools as LangChain tools
# --------------------------------------------------------------------------
def build_tools(session: Any = None, today: _dt.date | None = None) -> list[StructuredTool]:
    """Wrap the two plain functions. Results and errors both go back as JSON text.

    today is for tests. Left as None, the search tool reads the clock on each call.
    """

    def search_federal_register(
        term: str,
        agencies: Optional[list[str]] = None,
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: Optional[int] = None,
        last_n_days: Optional[int] = None,
    ) -> str:
        """Search Federal Register documents, newest first. The "count" in the result is the
        number of documents that match the search words, not the number about a subject.

        Args:
            term: words to search for. Put an exact phrase in double quotes.
            agencies: optional list of agency slugs, lower case with hyphens,
                for example ["commerce-department"].
            doc_type: optional, one of RULE (final rule), PRORULE (proposed rule),
                NOTICE, PRESDOCU (presidential document).
            date_from: optional earliest publication date, YYYY-MM-DD.
            date_to: optional latest publication date, YYYY-MM-DD.
            limit: optional number of results, 1 to 10. Default 5.
            last_n_days: optional whole number of days. Use this for "the last N
                days": the tool computes the date range from today's date and
                ignores date_from and date_to.
        """
        try:
            result = fr_tools.search_documents(
                term, agencies, doc_type, date_from, date_to, limit,
                last_n_days=last_n_days, today=today, session=session,
            )
        except fr_tools.ToolInputError as exc:
            result = {"error": "invalid_input", "detail": str(exc)}
        return json.dumps(result, ensure_ascii=False)

    def get_federal_register_document(document_number: str) -> str:
        """Get the details of one Federal Register document.

        Args:
            document_number: the document number exactly as a search returned it,
                for example "2026-19964".
        """
        try:
            result = fr_tools.get_document(document_number, session=session)
        except fr_tools.ToolInputError as exc:
            result = {"error": "invalid_input", "detail": str(exc)}
        return json.dumps(result, ensure_ascii=False)

    return [
        StructuredTool.from_function(search_federal_register, parse_docstring=True),
        StructuredTool.from_function(get_federal_register_document, parse_docstring=True),
    ]


def make_tools_node(tools: list):
    """The tools node. Every tool call gets an answer, so the model's next turn is well formed;
    calls beyond MAX_TOOL_CALLS_PER_TURN are answered with an error and are not run, and so is
    a call that carries an argument the tool does not have (it used to be dropped silently, so
    a model that sent page=3 was given page 1 and not told)."""
    by_name = {tool.name: tool for tool in tools}

    def run_tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        answers: list[ToolMessage] = []
        for index, call in enumerate(getattr(last, "tool_calls", None) or []):
            name = call.get("name")
            args = call.get("args") or {}
            if index >= MAX_TOOL_CALLS_PER_TURN:
                content: Any = {
                    "error": "too_many_tool_calls",
                    "detail": f"only the first {MAX_TOOL_CALLS_PER_TURN} tool calls of a turn are "
                              "run; this one was not run",
                }
            elif name not in by_name:
                content = {"error": "unknown_tool", "detail": f"there is no tool named {name!r}"}
            else:
                known = set(getattr(by_name[name], "args", {}) or {})
                unknown = sorted(str(key) for key in args if key not in known) if isinstance(args, dict) else []
                if unknown:
                    content = {
                        "error": "invalid_input",
                        "detail": f"{name} has no argument named {', '.join(unknown)}. Its arguments "
                                  f"are: {', '.join(sorted(known))}. The call was not run.",
                    }
                else:
                    try:
                        content = by_name[name].invoke(args)
                    except Exception as exc:  # the arguments did not fit the tool's schema
                        content = {"error": "invalid_input",
                                   "detail": f"{type(exc).__name__}: {str(exc)[:300]}"}
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            answers.append(ToolMessage(content=content, tool_call_id=call.get("id"), name=name))
        return {"messages": answers}

    return run_tools


# --------------------------------------------------------------------------
# reading a finished run
# --------------------------------------------------------------------------
def _text_of(message: Any) -> str:
    """Message content as plain text. Bedrock returns a list of content blocks."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


_ENTRY_FIELDS = ("type", "publication_date", "agencies", "title", "html_url", "citation",
                 "effective_on", "comments_close_on", "pdf_url")
_URL_FIELDS = ("html_url", "pdf_url")
_DATE_FIELDS = ("publication_date", "effective_on", "comments_close_on")
# Written by the tool's code from the model's own search term, not by the Federal Register:
# never a source for a number, a date or a reference in the model's text.
_CODE_COUNTED_FIELDS = ("search_words_in_title", "search_words_in_abstract")


def _complete_strings(doc: dict) -> list[str]:
    """Every string and number in one returned document, as text, leaving out the fields the
    tool cut short and the record of the cut itself. A truncated field never counts as a
    source: its last word may be a stump, and the rest of it was never seen."""
    cut = set((doc.get("truncated") or {}).keys()) if isinstance(doc.get("truncated"), dict) else set()
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for inner in value.values():
                walk(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                walk(inner)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, (str, int, float)):
            strings.append(str(value))

    for key, value in doc.items():
        if key == "truncated" or key in cut or key in _CODE_COUNTED_FIELDS:
            continue
        walk(value)
    return strings


def _all_strings(value: Any) -> list[str]:
    """Every string anywhere in a tool result, the tool's own fixed sentences included
    ("count is the number of documents that match the search words."). The warning on a quoted
    phrase says it stands "in no tool result of this run", so every word of a tool result may
    be quoted (review round 4: that sentence, quoted exactly, was warned). These strings are
    a source for quotations only, never for numbers or dates."""
    if isinstance(value, str):
        return [value.replace(fr_tools.TRUNCATION_MARK, " ")]
    if isinstance(value, dict):
        return [text for inner in value.values() for text in _all_strings(inner)]
    if isinstance(value, (list, tuple)):
        return [text for inner in value for text in _all_strings(inner)]
    return []


def _cell(value: Any, limit: int = 600) -> str:
    """One value of a tool result as it is printed in the block: on one line, without control
    characters, and no longer than `limit` characters. fr_tools cleans the fields it returns;
    this is the second net, so that nothing a tool result holds can start a line of the block
    (review round 4, m6)."""
    text = "".join(" " if unicodedata.category(ch) in {"Cc", "Zl", "Zp"} else ch for ch in str(value))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _query_line(query: dict) -> str:
    parts = [f"term: {query.get('term')}"]
    if query.get("agencies"):
        parts.append("agencies " + ", ".join(map(str, query["agencies"])))
    if query.get("doc_type"):
        parts.append(f"type {query['doc_type']}")
    if query.get("date_from") or query.get("date_to"):
        dates = f"published {query.get('date_from') or 'any date'} to {query.get('date_to') or 'any date'}"
        dates += (f" ({query['date_note']})" if query.get("date_note")
                  else " (dates chosen by the model)")
        parts.append(dates)
    parts.append(f"limit {query.get('limit')}")
    return "; ".join(parts)


def summarize_tool_results(messages: list) -> dict:
    """What the tools returned in this run, read from the ToolMessages.

    documents            every document a tool returned, keyed by its "document_number" field
                         (upper case), in the order returned, with the structured fields the
                         block shows. Only this makes a document number "returned".
    citations            the "citation" fields of those documents, normalised
    urls                 their URL fields, normalised
    mentioned            document numbers and citations that appear in the free text of a
                         complete field (a title, an abstract) but were not returned as a
                         document, as a citation field or inside a docket_ids field
    docket_references    strings in a returned "docket_ids" field that have the form of a document
                         number (an SEC release number such as 33-11438), each with the document
                         numbers whose field holds it: a docket id the tool returned, not a document
    failed_lookups       document number -> what failed, for every lookup that returned an error
    search_dates         the date_from and date_to of every successful search as it was sent,
                         whoever chose them: the block shows them
    cfr                  CFR references: the "cfr_references" fields of looked-up documents, and
                         any written in the text of a complete field
    numbers, compounds,  the digit runs, number groups and dates found in the complete fields
    dates                of successful results (and, for a search whose dates were computed in
                         code, those dates). The "query" echo is otherwise left out: the model
                         wrote that, the Federal Register did not.
    searches             one entry per successful search: the query as sent, the API's total,
                         how many came back
    Each document also carries "search_words": for every search that returned it, the line
    fr_tools.search_word_report gives for its title and for its abstract.
    """
    documents: dict[str, dict] = {}
    citations: set[str] = set()
    urls: set[str] = set()
    source_strings: list[str] = []
    quotable_strings: list[str] = []   # the visible part of cut fields, search terms, tool errors
    titles: list[str] = []
    searches: list[dict] = []
    lookups: list[str] = []
    empty_searches = 0
    errors: list[str] = []
    tool_calls: list[dict] = []
    cfr_counts: set[int] = set()
    cfr_fields: set[tuple[str, str]] = set()
    docket_references: dict[str, set[str]] = {}
    failed_lookups: dict[str, str] = {}
    search_dates: set[tuple[int, int, int]] = set()
    calls_by_id: dict = {}
    first_titles: dict[str, str] = {}

    def take(doc: dict, search: tuple[int, Any] | None = None) -> None:
        number = str(doc["document_number"]).strip().upper()
        entry = documents.setdefault(number, {"document_number": number})
        cut = doc.get("truncated") if isinstance(doc.get("truncated"), dict) else {}
        if search is not None:
            # counted here from the fields of the tool result, not copied from it
            words = fr_tools.search_content_words(search[1])
            in_title = len(words) - len(fr_tools.search_words_missing(words, doc.get("title")))
            abstract = doc.get("abstract")
            has_abstract = isinstance(abstract, str) and bool(abstract.replace(fr_tools.TRUNCATION_MARK, " ").strip())
            entry.setdefault("search_words", []).append({
                "search": search[0],
                "term": search[1],
                # no search word in the title, and none in the abstract or no abstract at all
                "none_found": bool(words) and in_title == 0 and (
                    not has_abstract or len(fr_tools.search_words_missing(words, abstract)) == len(words)),
                "title": fr_tools.search_word_report(search[1], doc.get("title"), "title" in cut, "title"),
                "abstract": fr_tools.search_word_report(search[1], doc.get("abstract"), "abstract" in cut,
                                                        "abstract"),
            })
            # the two figures of the title line are in the block, so the text may repeat them
            source_strings.extend([str(in_title), str(len(words))])
        if isinstance(doc.get("docket_ids"), list):
            for docket in doc["docket_ids"]:
                if isinstance(docket, str):
                    for reference in find_references(docket):
                        docket_references.setdefault(reference, set()).add(number)
        for field in _ENTRY_FIELDS:
            if doc.get(field) not in (None, "", []):
                entry[field] = doc[field]
        if isinstance(doc.get("title"), str) and "title" not in cut:
            # One number returned twice with two different complete titles: the block shows both.
            earlier = first_titles.setdefault(number, doc["title"])
            if earlier != doc["title"] and earlier not in entry.get("other_titles", []):
                entry.setdefault("other_titles", []).append(earlier)
        if "title" in cut:
            entry["title_truncated"] = True
        elif isinstance(doc.get("title"), str):
            entry.pop("title_truncated", None)
            titles.append(doc["title"])
        if isinstance(doc.get("citation"), str):
            citations.update(find_fr_citations(doc["citation"]))
        for field in _URL_FIELDS:
            if isinstance(doc.get(field), str) and field not in cut:
                urls.update(find_urls(doc[field]))
        source_strings.extend(_complete_strings(doc))
        # A cut field is no source for numbers or dates, but the words that are shown of it
        # are real, so they may be quoted.
        quotable_strings.extend(str(doc[key]).replace(fr_tools.TRUNCATION_MARK, " ")
                                for key in cut if isinstance(doc.get(key), str))
        if isinstance(doc.get("cfr_references"), list):
            refs = [ref for ref in doc["cfr_references"] if isinstance(ref, dict)]
            total = doc.get("cfr_references_total")
            cfr_counts.add(total if isinstance(total, int) else len(refs))
            by_title: dict = {}
            for ref in refs:
                # str(): a title that is a list or an object must not stop the run (review
                # round 4, m5: TypeError, unhashable type, and no answer at all)
                title = str(ref.get("title"))
                by_title[title] = by_title.get(title, 0) + 1
                cfr_fields.add((title, str(ref.get("part") or "").upper()))
            cfr_counts.update(by_title.values())

    for m in messages:
        if isinstance(m, AIMessage):
            for call in m.tool_calls or []:
                tool_calls.append({"name": call.get("name"), "args": call.get("args")})
                calls_by_id[call.get("id")] = call
        if not isinstance(m, ToolMessage):
            continue
        try:
            data = json.loads(_text_of(m))
        except (TypeError, ValueError):
            errors.append("a tool returned text that is not JSON")
            continue
        if not isinstance(data, dict):
            errors.append("a tool returned JSON that is not an object")
            continue
        if data.get("error"):
            errors.append(f"{data['error']}: {data.get('detail', '')}".strip())
            quotable_strings.append(errors[-1])
            call = calls_by_id.get(getattr(m, "tool_call_id", None)) or {}
            asked = data.get("document_number")
            if not isinstance(asked, str) and call.get("name") == "get_federal_register_document" \
                    and isinstance(call.get("args"), dict):
                asked = call["args"].get("document_number")
            if isinstance(asked, str) and asked.strip():
                failed_lookups[normalize_reference_text(asked)] = errors[-1]
            continue
        if "results" in data:
            results = data["results"]
            if (not isinstance(results, list) or isinstance(data.get("count"), bool)
                    or not isinstance(data.get("count"), int)
                    or any(not isinstance(d, dict) or not isinstance(d.get("document_number"), str)
                           or not d["document_number"].strip() for d in results)):
                errors.append("upstream_error: a search result did not have the expected fields")
                continue
            query = data.get("query") if isinstance(data.get("query"), dict) else {}
            quotable_strings.append(str(query.get("term") or ""))
            quotable_strings.extend(_all_strings(data))
            searches.append({"query": query, "count": data["count"], "returned": len(results),
                             "count_note": data.get("count_note")})
            if not results:
                empty_searches += 1
            for doc in results:
                take(doc, (len(searches), query.get("term")))
            for key in ("date_from", "date_to"):
                try:
                    day = _dt.date.fromisoformat(str(query.get(key) or ""))
                except ValueError:
                    continue
                search_dates.add((day.year, day.month, day.day))
            source_strings.extend(str(data[key]) for key in ("count", "returned", "note", "count_note")
                                  if data.get(key) is not None)
            if query.get("date_note"):  # these dates were computed by the tool, not by the model
                source_strings.extend(str(query[key]) for key in ("date_from", "date_to", "last_n_days")
                                      if query.get(key) is not None)
            if isinstance(query.get("limit"), int):  # set by the tool: at most 10, whatever was asked
                source_strings.append(str(query["limit"]))
        elif isinstance(data.get("document_number"), str) and data["document_number"].strip():
            lookups.append(data["document_number"].strip().upper())
            take(data)
            quotable_strings.extend(_all_strings(data))
            if data.get("note"):
                source_strings.append(str(data["note"]))
        else:
            errors.append("upstream_error: a tool result was neither a search result nor a document")

    source_text = " | ".join(source_strings)
    docket_references = {ref: owners for ref, owners in docket_references.items()
                         if ref not in documents and ref not in citations}
    mentioned = find_references(source_text) - set(documents) - citations - set(docket_references)
    numbers, compounds = find_numbers(source_text)
    return {
        "tool_calls": tool_calls,
        "searches": searches,
        "lookups": lookups,
        "empty_searches": empty_searches,
        "documents": documents,
        "citations": citations,
        "urls": urls,
        "titles": titles,
        "mentioned": mentioned,
        "docket_references": docket_references,
        "failed_lookups": failed_lookups,
        "search_dates": search_dates,
        "numbers": numbers,
        "compounds": compounds,
        "dates": find_dates(source_text),
        "quotable": " | ".join(_words(text) for text in source_strings + quotable_strings),
        "cfr_counts": cfr_counts,
        "cfr": cfr_fields | find_cfr_references(source_text),
        "returned_references": set(documents) | citations,
        "tool_errors": errors,
    }


def token_usage(messages: list) -> dict:
    """Input and output tokens the model reported for this run, summed over its turns."""
    total = {"input_tokens": 0, "output_tokens": 0, "model_turns": 0}
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        usage = getattr(m, "usage_metadata", None)
        if usage:
            total["model_turns"] += 1
            total["input_tokens"] += int(usage.get("input_tokens") or 0)
            total["output_tokens"] += int(usage.get("output_tokens") or 0)
    return total


def _shorten(items: list[str], limit: int = 3, chars: int = 200) -> str:
    shown = "; ".join(str(item)[:chars] for item in items[:limit])
    extra = len(items) - limit
    return shown + (f"; and {extra} more" if extra > 0 else "")


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_ITEMS_PER_WARNING])
    extra = len(items) - MAX_ITEMS_PER_WARNING
    return shown + (f", and {extra} more" if extra > 0 else "")


def _search_lines(searches: list[dict]) -> list[str]:
    lines = [f"Searches sent ({len(searches)}):"]
    for index, search in enumerate(searches, 1):
        lines.append(f"  {index}. {_query_line(search['query'])}")
        count, returned = search["count"], search["returned"]
        line = (f"     The API reported {count} matching document(s) in total and returned "
                f"{returned}." if count else "     The API reported 0 matching documents.")
        if search.get("count_note"):
            line += f" Note: {search['count_note']}"
        elif count > returned:
            line += " The total is the API's own figure; this agent did not count the matches."
        lines.append(line)
        lines.append("     " + (MATCHES_NOT_TOPIC if count else ZERO_MATCHES_NOT_TOPIC))
    return lines


def build_block(summary: dict) -> str:
    """The code-built part of an answer. Every line comes from a tool result's own fields."""
    documents = list(summary["documents"].values())
    lines = [BLOCK_HEADER]
    if summary["searches"]:
        lines += _search_lines(summary["searches"])
    if summary["lookups"]:
        lines.append(f"Lookups by document number that returned a document ({len(summary['lookups'])}): "
                     + ", ".join(summary["lookups"]))
    lines.append(f"Documents returned ({len(documents)}), in the order the API returned them:")
    if any(doc.get("search_words") for doc in documents[:BLOCK_MAX_DOCUMENTS]):
        lines.append("  " + SEARCH_WORDS_LEGEND)
    for index, doc in enumerate(documents[:BLOCK_MAX_DOCUMENTS], 1):
        agencies = doc.get("agencies")
        agencies = "; ".join(map(str, agencies)) if isinstance(agencies, list) else str(agencies or "")
        lines.append(f"  {index}. {_cell(doc['document_number'], 80)} | "
                     f"{_cell(doc.get('type') or 'type not given', 80)} | "
                     f"published {_cell(doc.get('publication_date') or 'date not given', 40)} | "
                     f"{_cell(agencies or 'agency not given', 400)}")
        lines.append(f"     Title: {_cell(doc.get('title') or 'not given', 1000)}")
        for other in doc.get("other_titles") or []:
            lines.append("     The API returned this document number twice, the other time with the title: "
                         + _cell(other, 1000))
        lines.append(f"     URL: {_cell(doc.get('html_url') or 'not given')}")
        extra = []
        if doc.get("citation"):
            extra.append(f"Federal Register citation {_cell(doc['citation'], 80)}")
        if doc.get("effective_on"):
            extra.append(f"effective {_cell(doc['effective_on'], 40)}")
        if doc.get("comments_close_on"):
            extra.append(f"comments close {_cell(doc['comments_close_on'], 40)}")
        if extra:
            lines.append("     " + "; ".join(extra))
        for counted in doc.get("search_words") or []:
            lines.append(f"     Search words (search {counted['search']}): in title: {counted['title']}; "
                         f"in abstract: {counted['abstract']}")
    hidden = len(documents) - BLOCK_MAX_DOCUMENTS
    if hidden > 0:
        lines.append(f"  {hidden} more returned document(s) are not shown in this block.")
    if summary["tool_errors"]:
        # Each error through _cell, as every other value of the block: an error text can hold the
        # name of an argument the model made up, newlines included (review round 5, F8).
        lines.append(f"Tool calls that failed ({len(summary['tool_errors'])}): "
                     + _shorten([_cell(error) for error in summary["tool_errors"]]))
    return "\n".join(lines)


def _mask_titles(folded: str, titles: list[str]) -> str:
    """Blank every word-for-word copy of a complete returned title. A number inside a title
    the model copied whole (a docket number, for example) is not a claim by the model."""
    for title in sorted({normalize_reference_text(t) for t in titles}, key=len, reverse=True):
        if len(title) >= 12:
            folded = folded.replace(title, " ")
    return folded


# A docket id: letters and a hyphen, then a year, then a number ("FAA-2026-0491",
# "EPA-HQ-OAR-2021-0317"). It is an identifier, not a range or a model number, so it is compared
# whole (review round 5, F2: "FAA-2026-0491" passed because 2026 is the current year and 0491 is
# a part of the returned FAA-2025-0491, and "FAA-2026-2730" passed as a range of two years). Not
# "DHC-8-103" or "CL-600-2B19": after letters a model number does not start with a year.
_DOCKET_YEAR = re.compile(r"(?:19|20)\d{2}")


def _written_as_identifier(folded_without_dates: str) -> set[str]:
    """The groups of _COMPOUND in a normalised text, with dates blanked, that are written as a
    docket id (see the comment above)."""
    text = _THOUSANDS.sub("", folded_without_dates)
    found: set[str] = set()
    for match in _COMPOUND.finditer(text):
        group = match.group(0)
        if re.fullmatch(r"[A-Z]-", text[max(match.start() - 2, 0): match.start()]) \
                and _DOCKET_YEAR.fullmatch(group.split("-")[0]):
            found.add(group)
    return found


def _hyphen_parts_supported(compound: str, allowed_numbers: set[str], allowed_compounds: set[str]) -> bool:
    """True for two numbers joined by one hyphen when each is supported by itself: a part of
    two or more digits is a number the tools returned, a part with a dot or a slash in it is a
    group the tools returned, and a single digit is not compared. One hyphen joins two numbers
    (a range, "parts 70-71"; a model number, "A350-1041" after "A350-941 and -1041"), so the
    two are compared one by one. Review round 4: both were reported as invented. A group with
    two or more hyphens is an identifier and is compared whole ("2026-19964-2" is not the
    returned 2026-19964)."""
    if compound.count("-") != 1:
        return False
    for part in compound.split("-"):
        if part.isdigit():
            if len(part) >= 2 and part not in allowed_numbers:
                return False
        elif part not in allowed_compounds:
            return False
    return True


def check_prose(prose: str, summary: dict, question: str, today: _dt.date) -> dict:
    """Compare the model's text with the tool results. Returns the lists of what failed."""
    documents = summary["documents"]
    question_numbers, question_compounds = find_numbers(question)
    question_dates = find_dates(question)
    # "between September 1 and September 30, 2026": the first date has no year of its own. It
    # takes the year or years the question names, or the current year when it names none.
    question_years = find_years(question) or {today.year}
    question_inferred = {(y, m, d) for m, d in question_dates["month_day"] for y in question_years
                         if _valid_date(y, m, d)}
    allowed_numbers = summary["numbers"] | question_numbers | {str(today.year)}
    allowed_compounds = summary["compounds"] | question_compounds
    # Two numbers a tool returned joined by one hyphen ("parts 70-71") are two numbers it
    # returned: the text may write them apart, as it may join two that the tool wrote apart.
    allowed_numbers |= {part for compound in allowed_compounds if re.fullmatch(r"\d+-\d+", compound)
                        for part in compound.split("-") if len(part) >= 2}
    # A date of a search as it was sent is in the block ("published 2026-09-01 to 2026-09-30"),
    # so the text may repeat it. Only the two ends of the range: a day between them is not.
    allowed_full = (summary["dates"]["full"] | question_dates["full"] | question_inferred
                    | summary.get("search_dates", set()) | {(today.year, today.month, today.day)})
    allowed_month_year = ({(y, m) for y, m, _ in allowed_full} | summary["dates"]["month_year"]
                          | question_dates["month_year"])
    allowed_month_day = ({(m, d) for _, m, d in allowed_full} | summary["dates"]["month_day"]
                         | question_dates["month_day"])
    # The year of a full date that a tool returned is a number the tool returned: "published on
    # May 31, 2022" supports "the 2022 rule" (a false warning in the rehearsal on real model
    # text). Only full dates: with the year of "June 2025" allowed too, one of the reviewer's
    # scripted runs (an essay from memory that names "the 2025 chip export rule") passed.
    allowed_numbers |= {str(y) for y, _, _ in allowed_full}
    # The counts the block prints in its own headings ("Documents returned (10)") are figures
    # code worked out from the tool results. Second rehearsal pass, Q22, both writers: two
    # searches returned 5 documents each, and "none of the 10 returned documents" was warned as
    # a number that appears in no tool result.
    allowed_numbers |= {str(len(documents)), str(len(summary["searches"])),
                        str(len(summary.get("lookups") or [])), str(len(summary.get("tool_errors") or []))}

    refs: set[str] = set()
    cited_documents: set[str] = set()
    bad_numbers: set[str] = set()
    bad_dates: set[str] = set()
    for variant in _variants(prose):
        cited_documents |= {n for n in _DOC_NUMBER.findall(variant) if n in documents}
        # A returned number of a form _DOC_NUMBER does not read (2010-99 and X94-61230 are real)
        # is still named when the text holds it exactly as the tool returned it.
        cited_documents |= {n for n in documents if n not in cited_documents and re.search(
            r"(?<![A-Z0-9-])" + re.escape(n) + r"(?![A-Z0-9]|-\d)", variant)}
        masked = _mask_titles(variant, summary["titles"])
        for match in _DOC_NUMBER.findall(masked):
            head, _, tail = match.rpartition("-")
            if not (len(head) == 4 and head.isdigit() and len(tail) == 4
                    and 1900 <= int(head) < int(tail) <= 2100):
                refs.add(match)
        refs |= {f"{int(v)} FR {int(p.replace(',', ''))}" for v, p in _FR_CITATION.findall(masked)}
        dates, without_dates = _scan_dates(variant)
        bad_dates |= {f"{y:04d}-{m:02d}-{d:02d}" for y, m, d in dates["full"] - allowed_full}
        bad_dates |= {f"{y:04d}-{m:02d}" for y, m in dates["month_year"] - allowed_month_year}
        bad_dates |= {f"month {m}, day {d} (no year given)" for m, d in dates["month_day"] - allowed_month_day}
        runs, compounds = _scan_numbers(without_dates)
        bad_numbers |= runs - allowed_numbers
        identifiers = _written_as_identifier(without_dates)
        for compound in compounds - allowed_compounds:
            if compound in identifiers:
                bad_numbers.add(compound)   # a docket id: compared whole (review round 5, F2)
                continue
            years = _YEAR_RANGE.fullmatch(compound)
            if years and years.group(1) in allowed_numbers and years.group(2) in allowed_numbers \
                    and int(years.group(1)) < int(years.group(2)):
                continue  # "2022-2031" built from two years the tools returned
            if _hyphen_parts_supported(compound, allowed_numbers, allowed_compounds):
                continue  # "70-71", "A350-941 and A350-1041": each part is a number a tool returned
            bad_numbers.add(compound)

    # Remainders code can work out again from the figures of the block: for each search the
    # matches less the documents returned, and the documents returned less the documents the
    # text names. "The other 52 matches were not returned" (of 57, 5 returned) is not a number
    # the model invented, and "the other 4 returned documents" is not a count to question.
    remainders = {s["count"] - s["returned"] for s in summary["searches"] if s["count"] > s["returned"]}
    if 0 < len(cited_documents) < len(documents):
        remainders.add(len(documents) - len(cited_documents))
    bad_numbers -= {str(n) for n in remainders}

    returned = summary["returned_references"]
    docket_owners = summary.get("docket_references", {})
    docket_ids = set(docket_owners)
    # The form of a document number, but a docket id that a returned "docket_ids" field holds.
    # It stands as a docket id when the text names the document whose field holds it and does
    # not call it a document; otherwise it gets a warning.
    docket_only: list[str] = []
    docket_misused: list[str] = []
    for ref in sorted((refs - returned) & docket_ids):
        called_a_document = any(
            re.search(r"(?:DOCUMENT|DOC\.?)(?: NUMBER| NO\.?| NOS\.?)? ?" + re.escape(ref) + r"(?![A-Z0-9-])", variant)
            for variant in _variants(prose)) if " FR " not in ref else False
        if called_a_document or not (docket_owners[ref] & cited_documents):
            docket_misused.append(ref)
        else:
            docket_only.append(ref)
    mentioned_only = sorted((refs - returned - docket_ids) & summary["mentioned"])
    not_found = refs - returned - docket_ids - summary["mentioned"]
    # a number the user asked about is not the model's invention; it is still not a returned document
    asked = sorted(not_found & find_references(question))
    unverified = sorted(not_found - set(asked))
    # A number that is part of a reference already listed is not listed a second time.
    bad_compounds = {n for n in bad_numbers if not n.isdigit()}
    other_numbers = sorted(
        n for n in bad_numbers
        # a whole part of such a reference (a run of digits), or a group that stands inside it
        if not any((n in re.split(r"[^0-9]+", ref)) if n.isdigit() else (n in ref)
                   for ref in unverified + mentioned_only + asked + docket_misused)
        and not (n.isdigit() and any(n in re.split(r"[-./:]", c) for c in bad_compounds)))
    bad_urls = sorted(find_urls(prose) - summary["urls"])
    # An address written without "https://" is compared without the scheme and "www." on both sides.
    returned_keys = {_url_key(url) for url in summary["urls"]}
    prose_bare_urls = find_bare_urls(prose)
    bad_urls += sorted(url for url in prose_bare_urls if _url_key(url) not in returned_keys)
    as_written = _urls_as_written(prose)
    quotable = " | ".join([summary.get("quotable", ""), _words(question)] + [_words(w) for w in QUOTABLE_ALWAYS])
    bad_quotes = [phrase for phrase in find_quoted_phrases(prose) if not _quote_found(phrase, quotable)]
    # A document is also named by its URL or by its complete title, word for word.
    prose_keys = {_url_key(url) for url in find_urls(prose) | prose_bare_urls}
    named_otherwise: set[str] = set()
    for number, doc in documents.items():
        if any(_url_key(url) in prose_keys for field in _URL_FIELDS if isinstance(doc.get(field), str)
               for url in find_urls(doc[field])):
            named_otherwise.add(number)
        title = doc.get("title")
        if isinstance(title, str) and not doc.get("title_truncated"):
            folded_title = normalize_reference_text(title)
            if len(folded_title) >= 12 and any(folded_title in variant for variant in _variants(prose)):
                named_otherwise.add(number)

    # ---- CFR references: a title and part are small numbers, so the digit rule cannot see them ----
    question_cfr = find_cfr_references(question)
    allowed_cfr = summary["cfr"] | question_cfr
    allowed_titles = {title for title, _ in allowed_cfr}
    allowed_parts = {(title, ref.split(".")[0]) for title, ref in allowed_cfr if ref}
    for title, ref in sorted(find_cfr_references(prose, across_lines=False)):
        known = title in allowed_titles if not ref else (
            (title, ref) in allowed_cfr or (title, ref.split(".")[0]) in allowed_parts)
        if not known:
            other_numbers = [n for n in other_numbers if n not in (title, ref)]
            other_numbers.append(f"{title} CFR {ref}".strip())

    # ---- counts ----
    # What code knows about a count: the total the API reported for each search, how many
    # documents each search returned, and how many documents are in the block. It does not know
    # which documents a count is about. So a count is a WARNING only where it contradicts those
    # figures in a way that reads reliably (e1, e2, e5 in the module docstring), and every other
    # comparison is a NOTE. Until the second rehearsal pass a count that equalled none of the
    # figures was a WARNING. On the 39 answers of that pass that a reader called clean it fired
    # six times, on sentences the system prompt asks for ("I left out the other 4 returned
    # documents"), and rule e1 as it then was fired twice more.
    searches = summary["searches"]
    totals = {s["count"] for s in searches}
    returned_counts = {s["returned"] for s in searches}
    cut_searches = [(i, s) for i, s in enumerate(searches, 1) if s["count"] > s["returned"]]
    some_search_was_cut = bool(cut_searches)
    question_counts = _question_counts(question)
    count_problems: list[str] = []
    count_notes: list[str] = []
    total_problems: list[str] = []
    by_paragraph = [sentences for _, sentences in _sentences_by_paragraph(prose)]
    for claim in find_count_claims(prose):
        k = claim["count"]
        phrase = claim["phrase"].lower()
        subset_wording = bool(_SUBSET_WORDS.search(claim["sentence"]))
        if not (k in totals or k in returned_counts or k == len(documents)):
            if k > len(documents) and k > max(totals, default=0):
                # e5: more than every search matched and than the block holds
                count_problems.append(
                    f'"{phrase}": the tools returned {len(documents)} document(s)'
                    + (f" and the API reported total(s) of {', '.join(map(str, sorted(totals)))}"
                       if totals else ""))
            elif k in remainders and subset_wording:
                pass  # "the other 4 returned documents", "the other 6 matches were not returned"
            elif k > len(cited_documents):
                # Equal to no figure a tool returned, and more than the text names: a NOTE. A
                # count no larger than the number of documents named is the model's own
                # grouping of them and gets no line.
                count_notes.append(
                    f'"{phrase}": equals no total the API reported, no number a search returned and '
                    f"not the number of documents in the block ({len(documents)}); the summary names "
                    f"{len(cited_documents)} document(s) by number")
            continue
        cut_with_this_total = [(i, s) for i, s in cut_searches if s["count"] == k]
        if not cut_with_this_total and 0 < len(cited_documents) < k:
            # The count of what a search returned or of the block, with fewer documents named.
            # A WARNING until round 3. Not said of the total of a search that returned fewer
            # than matched: how many documents the text names says nothing about that.
            count_notes.append(f'"{phrase}": equals a figure in the block; the summary names '
                               f"{len(cited_documents)} of the {len(documents)} returned document(s) by number")
        if cut_with_this_total:
            # rule e2: the total of a search that returned fewer documents than matched
            # Not when an earlier sentence of the same paragraph gave this total as a count of
            # matches and this one refers back to it: "31 documents matched the search ... I did
            # not see all 31 proposed rules, only the 10 newest" (review round 4, an honest text
            # that was warned; "refers back" since review round 5, F4).
            said_before = claim["refers_back"] and any(
                _MATCH_WORDS.search(sentence) and k in _integers_stated(sentence)
                for sentence in by_paragraph[claim["paragraph_index"]][: claim["sentence_index"]])
            if not _MATCH_WORDS.search(claim["sentence"]) and not said_before:
                i, search = cut_with_this_total[0]
                total_problems.append(
                    f'"{phrase}": {k} is the total the API reported for search {i} '
                    f"(term: {search['query'].get('term')}), which returned {search['returned']} of them")
        elif some_search_was_cut and k not in totals:
            # rule e1: the number returned presented as the number that exist. Not when the
            # sentence says it is a part or a sample, not when a larger total stands in the
            # same paragraph, and not when the question asked for that many.
            larger_total_nearby = any(total > k for total in _integers_stated(claim["paragraph"]) & totals)
            says_only = bool(_ONLY_WORDS.search(claim["sentence"]))
            # A larger total given as a count of matches in an earlier paragraph also counts,
            # unless this sentence says "only", "exactly" or the like (review round 4, M4: "10
            # documents matched the search ...", an empty line, then "Here are the 5 notices:").
            larger_total_earlier = not says_only and any(
                total > k
                for sentences in by_paragraph[: claim["paragraph_index"]] for sentence in sentences
                if _MATCH_WORDS.search(sentence) for total in _integers_stated(sentence) & totals)
            asked_for = k in question_counts and not says_only
            if claim["says_matched"]:
                # "Ten documents matched the search", when more matched: only a subset word next
                # to the count excuses it ("the 10 newest documents matched ...").
                subset_wording = bool(_SUBSET_WORDS.search(claim["near"]))
            elif {hit.group(0) for hit in _SUBSET_WORDS.finditer(claim["sentence"])} == {"AMONG"}:
                # Review round 5, F6: "Two final rules ... were published among FAA documents"
                # was excused by "among" at the far end of the sentence, where it names what
                # was searched. When it is the only subset word, it counts only next to the
                # count ("among them, two final rules").
                subset_wording = bool(re.search(r"\bAMONG\b", claim["near"]))
            if not subset_wording and not larger_total_nearby and not larger_total_earlier and not asked_for:
                count_problems.append(
                    f'"{phrase}": that is how many documents were returned, but the API reported '
                    f"{max(totals)} in total")
    # ---- note e4: "the newest X is <one document>" ----
    # Seen in the rehearsal on real model text: "The most recent executive order ... is document
    # 2026-20322", for a document the search for "executive order" returned whose title has
    # neither word and which has no abstract. Narrow on purpose: one returned document named in
    # the sentence, one of the three words, no word that says "the newest match of my search",
    # and not one search word in the document's title or abstract for any search that returned it.
    superlative_notes: list[str] = []
    for sentence in _sentences(prose):
        if not _SUPERLATIVE.search(sentence) or _MATCH_WORDS.search(sentence):
            continue
        named = {n for n in _DOC_NUMBER.findall(sentence) if n in documents}
        if len(named) != 1:
            continue
        number = named.pop()
        counted = documents[number].get("search_words") or []
        if counted and all(c["none_found"] for c in counted):
            superlative_notes.append(
                f"{number} (search {counted[0]['search']}, term: {counted[0]['term']})")
    superlative_notes = sorted(set(superlative_notes))
    # ---- does the text give a search count as a search count? (for the "names none" line) ----
    search_counts = {n for n in totals | returned_counts if n > 0}
    worded_counts: set[int] = set()
    for sentence in _sentences(prose):
        if _MATCH_WORDS.search(sentence):
            worded_counts |= _integers_stated(sentence) & search_counts
    # ---- "the last N days": only true of a search whose dates the tool computed from N ----
    computed_windows = {s["query"].get("last_n_days") for s in summary["searches"]
                        if s["query"].get("date_note")}
    window_problems: list[str] = []
    for token in sorted(set(_LAST_N_DAYS.findall(normalize_reference_text(prose)))):
        days = _number_value(token)
        if days not in computed_windows:
            sent = "; ".join(_query_line(s["query"]) for s in summary["searches"][:3]) or "no search ran"
            window_problems.append(
                f'"the last {days} days": no search in this run was limited to the last {days} days by '
                f"the tool. The searches sent were: {sent}")
    if summary["cfr_counts"]:
        for claim in find_cfr_part_claims(prose):
            if claim["count"] not in summary["cfr_counts"]:
                count_problems.append(
                    f'"{claim["phrase"].lower()}": the returned document(s) list '
                    f"{', '.join(map(str, sorted(summary['cfr_counts'])))} CFR part(s)")
    return {
        "unverified_references": unverified,
        "asked_references": asked,
        "docket_references": docket_only,
        "docket_misused": docket_misused,
        "mentioned_only_references": mentioned_only,
        "count_notes": count_notes,
        "total_problems": total_problems,
        "superlative_notes": superlative_notes,
        "worded_counts": sorted(worded_counts),
        "unverified_numbers": other_numbers,
        "unverified_dates": sorted(bad_dates),
        "unverified_urls": bad_urls,
        "unverified_urls_as_written": [as_written.get(url, url.lower()) for url in bad_urls],
        "unverified_quotes": bad_quotes,
        "count_problems": count_problems,
        "window_problems": window_problems,
        "cited_documents": sorted(cited_documents),
        "named_by_title_or_url": sorted(named_otherwise - cited_documents),
    }


def compose_answer(block: str, warnings: list[str], prose: str, notes: list[str] | None = None) -> str:
    """Block, then warnings, then notes, then the labelled model text; warnings again as the
    last line when the whole is longer than a screen."""
    parts = [block]
    if warnings:
        parts.append("\n".join(warnings))
    if notes:
        parts.append("\n".join(notes))
    parts.append(SUMMARY_LABEL + "\n" + (mark_model_lines(prose) or "(The model wrote no summary.)"))
    text = "\n\n".join(parts)
    if warnings and (text.count("\n") + 1 > SCREEN_LINES or len(text) > SCREEN_LINES * 80):
        text += "\n\n" + repeated_warning(warnings)
    return text


# The words that start a line written by this kit. A line of the model's text that starts with
# one of them is shown with MODEL_LINE_MARK in front, so that it cannot be taken for the kit's.
_KIT_LINE_STARTS = (WARNING_PREFIX.strip(), NOTE_PREFIX.strip(), "FROM THE FEDERAL REGISTER API", "MODEL'S SUMMARY")
MODEL_LINE_MARK = "[written by the model, not by the kit] "


# Apostrophes that look like the kit's "'" (review round 5, F7).
_APOSTROPHES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u2032": "'", "\u00b4": "'",
                              "\u0060": "'"})


def _line_start(line: str) -> str:
    """A line as it is compared with the starts of the kit's own lines: NFKC-folded (a no-break
    or other wide space becomes a space), with invisible format characters such as a zero-width
    space removed, look-alike apostrophes made "'", and the spaces and markup in front of it
    taken off. Review round 5, F7: "MODEL\u2019S SUMMARY", a zero-width space before "FROM THE
    FEDERAL REGISTER API" and a no-break space before "NOTE:" were neither marked nor warned."""
    folded = unicodedata.normalize("NFKC", line)
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf").translate(_APOSTROPHES)
    return re.sub(r"^[\s>*_#-]+", "", folded)


def mark_model_lines(prose: str) -> str:
    """The model's text as it is shown: unchanged, except that a line which starts the way the
    kit's own lines start (WARNING:, NOTE:, the heading of the block, the label of the
    summary) gets MODEL_LINE_MARK in front. Review round 4, m7: a model's text that ended in
    "NOTE: every statement in this summary was compared ... and found" was shown as written."""
    lines = _LINE_BREAKS.sub("\n", prose or "").split("\n")
    return "\n".join(
        MODEL_LINE_MARK + line if _line_start(line).startswith(_KIT_LINE_STARTS) else line
        for line in lines)


def imitates_block(prose: str) -> bool:
    """True when a line of the model's text starts like the heading of the block or the label
    of the summary. (A line that starts WARNING: or NOTE: is only marked: a model may write
    "NOTE:" in good faith.)"""
    return any(_line_start(line).startswith(_KIT_LINE_STARTS[2:])
               for line in _LINE_BREAKS.sub("\n", prose or "").split("\n"))


def repeated_warning(warnings: list[str]) -> str:
    """One line that says all the warnings again, for the end of a long output."""
    bodies = [w[len(WARNING_PREFIX):] if w.startswith(WARNING_PREFIX) else w for w in warnings]
    return (f"{WARNING_PREFIX}(repeated from above, {len(warnings)} in all) " + " | ".join(bodies))


# Control characters that a terminal acts on (ESC starts a sequence that can move the cursor and
# erase lines). Each is replaced by a space in the model's text before anything is checked or
# shown (review round 5, F9), so that words it separated stay apart. Not the tab and not the
# line breaks, which _LINE_BREAKS reads.
_TERMINAL_CONTROLS = re.compile("[\x00-\x08\x0e-\x1f\x7f-\x84\x86-\x9f]")


def check_answer(answer: str, summary: dict, question: str = "", today: _dt.date | None = None) -> dict:
    """Decide what the reader sees. No model here; see the module docstring for the rule."""
    answer = _TERMINAL_CONTROLS.sub(" ", answer or "").strip()
    today = today or _dt.date.today()
    documents = summary["documents"]
    errors = summary["tool_errors"]
    searches = summary["searches"]
    no_results = (
        len(searches) > 0
        and summary["empty_searches"] == len(searches)
        and not documents
        and not errors
    )
    found = check_prose(answer, summary, question, today)
    not_returned = (found["unverified_references"] + found["asked_references"]
                    + found["mentioned_only_references"] + found["docket_misused"])

    reasons: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    replacement: str | None = None
    block = ""
    if not summary["tool_calls"]:
        reasons.append("no_tool_called")
        replacement = REFUSAL_NO_TOOL
    elif not documents:
        if errors:
            reasons.append("tool_failed")
            replacement = f"{REFUSAL_TOOL_FAILED} What failed: {_shorten([_cell(e) for e in errors]).rstrip('.')}."
            if summary["empty_searches"]:
                replacement += " The searches that did run returned no documents."
        elif no_results:
            reasons.append("no_results")
            block = "\n".join(_search_lines(searches))
            replacement = NO_RESULTS_TEXT + "\n" + block
        else:
            reasons.append("nothing_returned")
            replacement = REFUSAL_NOTHING_RETURNED
        if not_returned:
            reasons.append("unverified_references")
    else:
        block = build_block(summary)
        if found["unverified_references"]:
            reasons.append("unverified_references")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary cites {len(found['unverified_references'])} "
                "reference(s) that look like Federal Register document numbers or citations and that "
                "no tool returned as a document in this run. Treat them as unverified; they may be "
                f"invented: {_listed(found['unverified_references'])}.")
        if found["asked_references"]:
            # Rehearsal on real model text, round 3: "may be invented" was said of a number the
            # user had asked about, in an answer that correctly reported the failed lookup.
            reasons.append("asked_not_returned")
            failed = [r for r in found["asked_references"] if r in summary.get("failed_lookups", {})]
            not_tried = [r for r in found["asked_references"] if r not in failed]
            if failed:
                what = "; ".join(f"{r} ({summary['failed_lookups'][r][:200].rstrip('.')})" for r in failed)
                warnings.append(
                    f"{WARNING_PREFIX}your question names {_listed(failed)}, and the lookup of "
                    f"{'that number' if len(failed) == 1 else 'those numbers'} failed in this run: "
                    f"{what}. No tool returned a document with "
                    f"{'that number' if len(failed) == 1 else 'those numbers'}, so nothing is in the "
                    "block for it and anything the summary says about it, other than that the lookup "
                    "failed, rests on no tool result.")
            if not_tried:
                warnings.append(
                    f"{WARNING_PREFIX}your question names {_listed(not_tried)}. No tool returned a "
                    "document with that number or citation in this run, and no lookup of it failed "
                    "or succeeded, so nothing the summary says about it was checked.")
        if found["mentioned_only_references"]:
            reasons.append("mentioned_not_returned")
            warnings.append(
                f"{WARNING_PREFIX}mentioned inside a returned document, not returned as one: "
                f"{_listed(found['mentioned_only_references'])}. These appear in the free text of "
                "a returned document (a title or an abstract), but no tool returned a document with "
                "that number, so nothing the summary says about them was checked.")
        if found["docket_misused"]:
            reasons.append("docket_id_not_a_document")
            owners = sorted({n for ref in found["docket_misused"]
                             for n in summary.get("docket_references", {}).get(ref, ())})
            warnings.append(
                f"{WARNING_PREFIX}{_listed(found['docket_misused'])}: a docket id in the docket_ids field "
                f"of returned document {_listed(owners)}, not a document that a tool returned. The "
                "summary calls it a document, or does not name the document whose field holds it, so "
                "what the summary says about it was not checked.")
        if found["docket_references"]:
            notes.append(
                f"{NOTE_PREFIX}{_listed(found['docket_references'])} "
                f"{'has' if len(found['docket_references']) == 1 else 'have'} the form of a document "
                "number and stand in the docket_ids field of a returned document: docket ids the "
                "tool returned, not documents returned in this run. Which document a docket id "
                "belongs to was not compared.")
        if found["unverified_numbers"]:
            reasons.append("unverified_numbers")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary contains {len(found['unverified_numbers'])} "
                "number(s) that appear in no complete field of a tool result in this run, not in "
                "your question, and are not the current year. They may be invented, worked out by "
                "the model, or taken from a field the tool cut short: "
                f"{_listed(found['unverified_numbers'])}.")
        if found["unverified_dates"]:
            reasons.append("unverified_dates")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary gives {len(found['unverified_dates'])} date(s) "
                "that appear in no tool result in this run, not in your question and not as the "
                f"first or last day of a search that was sent: {_listed(found['unverified_dates'])}.")
        if found["unverified_urls"]:
            reasons.append("unverified_urls")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary gives {len(found['unverified_urls'])} URL(s) "
                "that no tool returned in this run. Use the URLs in the block above instead: "
                f"{_listed(found['unverified_urls_as_written'])}.")
        if found["unverified_quotes"]:
            reasons.append("unverified_quotes")
            quoted = "; ".join(f'"{phrase}"' for phrase in found["unverified_quotes"][:MAX_ITEMS_PER_WARNING])
            more = len(found["unverified_quotes"]) - MAX_ITEMS_PER_WARNING
            warnings.append(
                f"{WARNING_PREFIX}the model's summary puts {len(found['unverified_quotes'])} phrase(s) in "
                "quotation marks that appear word for word in no tool result of this run, not in your "
                "question and not in a search that was sent. A quoted title or passage that no tool "
                f"returned may be invented or reworded: {quoted}"
                + (f"; and {more} more." if more > 0 else "."))
        if found["count_problems"]:
            reasons.append("count_mismatch")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary states a count that the tool results do not "
                f"support: {_shorten(found['count_problems'], limit=5, chars=300)}.")
        if found["total_problems"]:
            reasons.append("search_total_as_count")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary gives a search total as a count of documents: "
                f"{_shorten(found['total_problems'], limit=5, chars=400)}. A total counts the "
                "documents that match the search words, wherever in a document the words occur. It "
                "is not a count of documents about a subject, the documents that were not returned "
                "were seen by nobody, and the sentence does not say that it is a count of matches.")
        if found["superlative_notes"]:
            # A NOTE, not a WARNING. As a warning it had no false alarm on the 33 answers a reader
            # called clean, and it fired on a hand-labelled honest answer ("The newest is
            # 2026-20311", after a search for the word "rule"): a count of words cannot carry a
            # warning about what a document is about.
            notes.append(
                f"{NOTE_PREFIX}the model's summary calls a document the newest, the most recent or "
                f"the latest: {_shorten(found['superlative_notes'], limit=5, chars=300)}. Neither the "
                "title nor the abstract of that document holds one word of the search that returned "
                "it, and the sentence does not say it is the newest match of a search. This is a "
                "count of words, not a judgement of relevance: read the title in the block before "
                "you take the document for what you asked for.")
        if found["count_notes"]:
            # One line for every comparison of a count that is not one of the three warnings.
            many = len(found["count_notes"]) > 1
            notes.append(
                f"{NOTE_PREFIX}{'counts' if many else 'a count'} in the model's summary "
                f"{'were' if many else 'was'} compared with the figures in the block (the total of each "
                "search, the number each search returned, the number of documents listed). This is "
                "information, not a finding: code cannot tell which documents a count is about. "
                f"{_shorten(found['count_notes'], limit=5, chars=300)}.")
        if found["window_problems"]:
            reasons.append("unverified_window")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary speaks of a period that the searches do not "
                f"show: {_shorten(found['window_problems'], limit=3, chars=400)}.")
        if errors:
            reasons.append("tool_failed")
            warnings.append(
                f"{WARNING_PREFIX}{len(errors)} tool call(s) failed in this run "
                f"({_shorten([_cell(error) for error in errors])}). "
                "Parts of the model's summary may not rest on a tool result.")
        if imitates_block(answer):
            # Review round 4, m7: a second block shaped like the kit's, with an invented
            # document in it and no digits to compare, was shown as written.
            reasons.append("imitates_kit_block")
            warnings.append(
                f"{WARNING_PREFIX}the model's summary contains a line that starts like this kit's "
                "own heading of the block or label of the summary. The model wrote that line and "
                "everything after the label below; code built only the one block at the top.")
        if not answer:
            reasons.append("no_summary")
            warnings.append(
                f"{WARNING_PREFIX}the model wrote no summary. The block above is all there is.")
        elif not found["cited_documents"] and not found["named_by_title_or_url"]:
            # Review round 4, m4: the warning used to end "so nothing in it could be tied to the
            # tool results", which was untrue of a text whose dates and quoted title had been
            # compared and found. A document is named by its number, by its complete title or by
            # its URL; the line now says only what code knows.
            if found["worded_counts"]:
                # An answer to "how many" may name no document. Rehearsal on real model text,
                # round 3: this line was a WARNING on two such answers that a reader called clean.
                notes.append(
                    f"{NOTE_PREFIX}the model's summary names none of the {len(documents)} document(s) "
                    "in the block above. It gives, as a count of what a search matched or returned, "
                    f"{_listed([str(n) for n in found['worded_counts']])}, which the block also "
                    "shows. Nothing else in it could be tied to a document.")
            elif len(documents) == 1:
                # One document in the block: there is no other the text could be about.
                notes.append(
                    f"{NOTE_PREFIX}the model's summary does not name the one document in the block "
                    "above by its number, its title or its URL. Its numbers, dates and quoted phrases "
                    "were compared with the tool results as usual.")
            else:
                reasons.append("no_document_cited")
                warnings.append(
                    f"{WARNING_PREFIX}the model's summary names none of the {len(documents)} "
                    "document(s) in the block above, by number, by complete title or by URL, and gives "
                    "no count of what a search matched or returned in words that say so. Its numbers, "
                    "dates and quoted phrases were compared with the tool results as usual, but code "
                    "cannot tell which document, if any, its statements are about.")

    if replacement is not None:
        final_text = replacement
        grounding = "replaced"
        prose: str | None = None
        block_out = block
    else:
        final_text = compose_answer(block, warnings, answer, notes)
        grounding = "warned" if warnings else "ok"
        prose = answer
        block_out = block

    def entry(number: str) -> dict:
        doc = documents[number]
        return {"document_number": doc["document_number"], "title": doc.get("title"),
                "html_url": doc.get("html_url"), "type": doc.get("type"),
                "publication_date": doc.get("publication_date"), "agencies": doc.get("agencies")}

    return {
        "final_text": final_text,
        "block": block_out,
        "model_summary": prose,
        "summary_label": SUMMARY_LABEL if prose is not None else None,
        "tool_calls": summary["tool_calls"],
        "searches": [{"query": s["query"], "api_total": s["count"], "returned": s["returned"]}
                     for s in searches],
        "no_results": no_results,
        "tool_errors": errors,
        "citations": [entry(n) for n in found["cited_documents"]],
        "documents_returned": [entry(n) for n in documents],
        "unverified_document_numbers": sorted(not_returned),
        "mentioned_only_references": found["mentioned_only_references"],
        "asked_not_returned": found["asked_references"],
        "docket_references": found["docket_references"],
        "docket_misused": found["docket_misused"],
        "unverified_numbers": found["unverified_numbers"],
        "unverified_dates": found["unverified_dates"],
        "unverified_urls": [u.lower() for u in found["unverified_urls"]],
        # words of the model's text: reported only when that text is shown
        "unverified_quotes": found["unverified_quotes"] if replacement is None else [],
        "count_problems": found["count_problems"],
        "total_problems": found["total_problems"],
        "window_problems": found["window_problems"],
        "used_tools": bool(summary["tool_calls"]),
        "warnings": warnings,
        # information lines; shown only with the model's text
        "notes": notes if replacement is None else [],
        "grounding": grounding,
        "grounding_reasons": reasons,
        "answer_replaced": replacement is not None,
        "withheld_answer": answer if replacement is not None else None,
    }


def _question_of(messages: list) -> str:
    for m in messages:
        if isinstance(m, HumanMessage):
            return _text_of(m)
    return ""


def finalize(state: AgentState) -> dict:
    """The last node. Always writes the composed text as the final message."""
    messages = state["messages"]
    answer = _text_of(messages[-1]) if messages else ""
    try:
        today = _dt.date.fromisoformat(state.get("today") or "")
    except ValueError:
        today = _dt.date.today()
    report = check_answer(answer, summarize_tool_results(messages), _question_of(messages), today)
    final_text = report.pop("final_text")
    return {"messages": [AIMessage(content=final_text)], "report": report}


# --------------------------------------------------------------------------
# the graph
# --------------------------------------------------------------------------
def _route_after_model(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "finalize"


def build_graph(model: Any, tools: list | None = None):
    """Compile the graph around any chat model that supports bind_tools."""
    tools = tools if tools is not None else build_tools()
    model_with_tools = model.bind_tools(tools)

    def call_model(state: AgentState) -> dict:
        return {"messages": [model_with_tools.invoke(state["messages"])]}

    builder = StateGraph(AgentState)
    builder.add_node("model", call_model)
    builder.add_node("tools", make_tools_node(tools))
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model", _route_after_model, {"tools": "tools", "finalize": "finalize"}
    )
    builder.add_edge("tools", "model")
    builder.add_edge("finalize", END)
    return builder.compile()


def validate_question(question: Any) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("the question must be a non-empty string")
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"the question must be at most {MAX_QUESTION_CHARS} characters")
    return question


_EMPTY_LISTS = ("citations", "unverified_document_numbers", "mentioned_only_references",
                "asked_not_returned", "docket_references", "docket_misused",
                "unverified_numbers", "unverified_dates", "unverified_urls", "unverified_quotes",
                "count_problems", "total_problems", "window_problems", "warnings", "notes")


def run_question(
    graph: Any,
    question: str,
    *,
    today: _dt.date | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> dict:
    """Run one question through the graph and return a plain dict.

    Keys:
      answer                       everything the reader is shown, in one text: the code-built
                                   block, any WARNING lines, then the model's summary under its
                                   label; or the fixed text that replaced the model's text
      block                        the code-built part alone ("" when no tool returned anything)
      warnings                     the WARNING lines alone
      notes                        the NOTE lines alone: information, not a failed check
      model_summary                the model's text alone; None when it was withheld
      grounding                    "ok", "warned", "replaced" or "stopped"
      grounding_reasons            why: no_tool_called, no_results, tool_failed, nothing_returned,
                                   unverified_references, asked_not_returned,
                                   mentioned_not_returned, docket_id_not_a_document,
                                   unverified_numbers, unverified_dates,
                                   unverified_urls, unverified_quotes, count_mismatch,
                                   search_total_as_count, unverified_window, no_document_cited,
                                   imitates_kit_block, no_summary, recursion_limit
      answer_replaced              True when the model's text was withheld
      withheld_answer              that text, for debugging; None otherwise
      unverified_document_numbers  document numbers and FR citations in the model's text that
                                   no tool returned as a document or as a citation field
      mentioned_only_references    the ones among them that appear inside a returned document
      asked_not_returned           the ones among them that the question itself names
      docket_references            strings with the form of a document number that a returned
                                   docket_ids field holds (a NOTE, not a warning)
      docket_misused               the same, called a document or given without the document
                                   whose field holds them (a warning)
      unverified_numbers, unverified_dates, unverified_urls, unverified_quotes, count_problems,
      window_problems              what else in the model's text the tool results do not support
      total_problems               search totals the text gives as counts of documents
      tool_errors, tool_calls, searches (each query as sent with the API's total),
      citations (documents the model's text names that a tool returned), documents_returned,
      no_results, stopped (None or "recursion_limit"), steps,
      usage (tokens as reported by the model, also when the run was stopped; zeros when the
      model reports none).
    The date is worked out here, per call, never at import time.
    """
    question = validate_question(question)
    today = today or _dt.date.today()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(today=today.isoformat())),
        HumanMessage(content=question),
    ]
    start = {"messages": messages, "today": today.isoformat()}
    state: dict = dict(start)
    try:
        # stream_mode="values" hands back the whole state after every step, so when the step
        # limit stops the run the messages so far (and the tokens they cost) are still known.
        for state in graph.stream(start, config={"recursion_limit": recursion_limit},
                                  stream_mode="values"):
            pass
    except GraphRecursionError:
        seen = state.get("messages", messages)
        summary = summarize_tool_results(seen)
        stopped = {key: [] for key in _EMPTY_LISTS}
        stopped.update({
            "answer": (
                f"Stopped: the agent did not finish within {recursion_limit} graph steps. "
                "No answer was produced."
            ),
            "block": "",
            "model_summary": None,
            "summary_label": None,
            "stopped": "recursion_limit",
            "tool_calls": summary["tool_calls"],
            "searches": [{"query": s["query"], "api_total": s["count"], "returned": s["returned"]}
                         for s in summary["searches"]],
            "documents_returned": [
                {"document_number": d["document_number"], "title": d.get("title"),
                 "html_url": d.get("html_url"), "type": d.get("type"),
                 "publication_date": d.get("publication_date"), "agencies": d.get("agencies")}
                for d in summary["documents"].values()],
            "no_results": False,
            "tool_errors": summary["tool_errors"],
            "grounding": "stopped",
            "grounding_reasons": ["recursion_limit"],
            "answer_replaced": False,
            "withheld_answer": None,
            "steps": max(len(seen) - 2, 0),
            "usage": token_usage(seen),
        })
        return stopped
    report = state.get("report") or {}
    if "grounding" not in report:
        # Fail closed. The finalize node always writes a report; if there is none, the
        # check did not run and the model's text must not be passed on.
        summary = summarize_tool_results(state.get("messages", messages))
        report = check_answer("", summary, question, today)
        report.update(final_text=None, grounding="replaced", answer_replaced=True, block="",
                      model_summary=None, summary_label=None, warnings=[],
                      grounding_reasons=["check_did_not_run"])
        answer_text = REFUSAL_NOTHING_RETURNED
    else:
        answer_text = _text_of(state["messages"][-1]).strip()
    out = {key: report.get(key, []) for key in _EMPTY_LISTS}
    out.update({
        "answer": answer_text,
        "block": report.get("block", ""),
        "model_summary": report.get("model_summary"),
        "summary_label": report.get("summary_label"),
        "stopped": None,
        "tool_calls": report.get("tool_calls", []),
        "searches": report.get("searches", []),
        "documents_returned": report.get("documents_returned", []),
        "no_results": report.get("no_results", False),
        "tool_errors": report.get("tool_errors", []),
        "grounding": report.get("grounding", "replaced"),
        "grounding_reasons": report.get("grounding_reasons", []),
        "answer_replaced": report.get("answer_replaced", False),
        "withheld_answer": report.get("withheld_answer"),
        "steps": len(state["messages"]) - 2,
        "usage": token_usage(state["messages"]),
    })
    return out
