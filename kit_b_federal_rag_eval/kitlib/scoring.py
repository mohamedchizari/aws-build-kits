"""Scoring. Pure functions, no AWS, no network: everything here is unit-tested.

These functions produce the numbers in the results table. Since the round 2 review the two
readers in this file work from allow-lists, so that what they credit is narrow and written down:

  * exact match credits an answer ONLY IF, once the question's own words (the use case name,
    the agency the question names, the question itself when it is repeated), the field-name
    phrases and exactly one accepted spelling of the expected value are taken out, every word
    that is left is on the short list FILLER_PHRASES below. Any other word, any character
    outside ALLOWED_PUNCTUATION (a question mark, a slash, an equals sign), a second value, or
    a sentence shaped like a question makes the answer "unclear". Unclear counts as NOT
    correct and is reported in a row of its own. The rule can miss a correct answer. It is
    built not to credit a wrong one; where that was measured, and on what, is in README
    section 8;
  * a refusal is the fixed sentence and nothing else: equality after trimming whitespace and
    one trailing period, with no other character removed or changed;
  * a judge reply is read as CORRECT or DECLINED only when it states exactly one verdict and
    no word in its reason, or anywhere else in the reply, contradicts it. Anything else is
    UNPARSEABLE and is never counted as correct. Since the rehearsal on real model text
    (round 3) the reader is given the question, so that a VALUE the judge quotes ("Not
    High-impact", the use case name, "NO ANSWER") is not read as the judge's own words, and
    so that a reason which names another value than the reference is refused. Since the round 4
    review a CORRECT is also refused when what the reply says about the candidate is not tied to the
    reference (the block "Round 4" below), and the word lists are longer. Since the round 5 review,
    with the question known, what a DECLINED reason says of the candidate must be a refusal and a
    CORRECT reason may not speak of a value in words of its own (the block "Round 5");
  * a question that hit an error is left out of every rate and the run is marked incomplete.

What these readers still cannot do is listed in README section 2, items 8 and 9. Read the rows.
"""
from __future__ import annotations

import functools
import json
import math
import re
import unicodedata

# The generation prompt tells the model to use exactly this sentence when the
# passages do not hold the answer. Only this sentence, alone, counts as a refusal
# in the exact-match columns.
DECLINE_SENTENCE = "I cannot answer this from the inventory documents provided."
DECLINE_CORE = "cannot answer this from the inventory"

# Written into run_config.json. Change it whenever a scoring rule changes, so that a run
# scored under older rules cannot be resumed and mixed with rows scored under these.
SCORING_VERSION = "2026-10-08.r5"

VERDICTS = ("CORRECT", "INCORRECT", "DECLINED")
UNPARSEABLE = "UNPARSEABLE"

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212-"), " ")


def normalise(text: str | None) -> str:
    """Lower-case, fold Unicode, turn every dash and punctuation mark into a space."""
    text = unicodedata.normalize("NFKC", text or "").casefold().translate(_DASHES)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_decline(answer: str | None) -> bool:
    """True only for the fixed refusal sentence on its own.

    Whitespace around it is trimmed and one trailing period is optional. Nothing else is
    removed or folded: not case, not quotation marks, not characters outside a-z. (Until the
    round 2 review every character that is not a-z or 0-9 was stripped first, so the sentence
    followed by an answer in another script still counted as a refusal.)
    """
    text = (answer or "").strip()
    if text.endswith("."):
        text = text[:-1]
    return text == DECLINE_SENTENCE[:-1]


def mentions_decline(answer: str | None) -> bool:
    """The refusal sentence, or its core, appears somewhere in the answer."""
    return normalise(DECLINE_CORE) in normalise(answer)


# =====================================================================================
# Exact match: the allow-list. Everything the reader accepts is written out in this block.
# =====================================================================================

# The words an answer may hold besides the expected value. Phrases are matched whole, in
# lower case, on the words of the answer (punctuation between the words is ignored). There is
# no single "a", "an", "to", "be", "of", "by", "in", "as" or "for" in here on purpose: each
# of them is allowed only inside a phrase, because alone it can build "is to be Deployed",
# "a use case of the agency" and the like. "was" is allowed for the agency only, where the
# report is a past event ("was reported by"); for a stage it would be a change of tense.
FILLER_PHRASES = {
    "common": (
        "the", "it", "is", "it's", "its", "this", "is a", "is an", "as a", "as an", "answer",
        "use case", "ai use case", "named",
        "recorded", "recorded for", "recorded as", "listed as", "given as", "for the", "for this",
        "in the", "inventory", "federal", "2025",
        "according to the inventory", "according to the record", "according to the passage",
        "according to the passages", "according to the document", "according to the documents",
        "according to passage", "according to document",
    ),
    "agency": ("agency", "reporting", "was", "reported", "reported by", "that reported", "u s", "united states"),
    "stage": ("stage", "stage of development", "development stage", "has been"),
    "high_impact": ("determination", "high impact determination", "high impact determinations",
                    "high impact status", "yes", "determined to be", "was determined to be",
                    "has been determined to be"),
}

# Round 4 (fourth review, MINOR 11): ways to open or close a right answer that lost every one of the 100
# real right answers of the rehearsal when they were put around them. They are matched like FILLER_PHRASES
# and are kept in a list of their own, so that the 53 phrases of rounds 2 and 3 stay as they were reviewed.
# None of them is a negation, a hedge, a tense or a comparison. 32 name where the answer comes from: one of
# "based on", "per", "stated in", "as stated in", followed by one of the eight sources "according to"
# already has ("based on the passages", "as stated in the document", "per the record"). The other five:
# "sure" says yes to the request, "as of the" stands before "2025 inventory" ("as of May 2025" is still
# unclear: "may" is on no list), and "has a", "classified as" and "listed under" are more ways to join
# the field and its value. One more join is in read_answer itself: "of" between the name of the field
# and the value ("has a stage of development of Deployed"). There is no single "passage", "record" or
# "stated" in here: alone they build "The passage is a Department of Energy record."
_SOURCES = ("the inventory", "the record", "the passage", "the passages", "the document", "the documents",
            "passage", "document")
LEAD_IN_PHRASES = {
    "common": tuple(f"{opener} {source}" for opener in ("based on", "per", "stated in", "as stated in")
                    for source in _SOURCES) + ("as of the", "sure", "has a", "classified as", "listed under"),
}

# Field-name phrases that hold the words of a value ("high-impact determination" holds
# "High-impact"). They are taken out BEFORE values are looked for, so the name of the field
# is never read as its value. Each is also in FILLER_PHRASES.
FIELD_NAME_PHRASES = {
    "agency": (),
    "stage": ("stage of development", "development stage"),
    "high_impact": ("high impact determination", "high impact determinations", "high impact status"),
}

# Characters an answer may hold besides letters, digits and white space. Anything else makes
# the answer unclear: "?" (a question), "/" (an alternative), "=" "!" "<" ">" "~" "+" (a
# comparison, a negation or a struck-out word), "|" "#" "{" "}" "[" "]" (a table or a structure).
ALLOWED_PUNCTUATION = ".,;:\"'()*_`-" + "\u2010\u2011\u2012\u2013\u2014\u2015\u2018\u2019\u201c\u201d"

# The two citation marks the generation prompt itself shows the model ("[1] (document uc-0001)").
# They are removed before the answer is read; any other bracket makes the answer unclear. Round 4: the
# number in "passage 1" and "document 2" is a citation too ("according to passage 1" was unclear for
# the "1", although "according to passage" is on the list).
CITATION_MARKS = (r"\[\d{1,2}\]", r"\(\s*document\s+uc-\d{4,}\s*\)", r"(?<=\b[Pp]assage )\d{1,2}\b",
                  r"(?<=\b[Dd]ocument )\d{1,2}\b")
# An exclamation mark that ends a sentence is the same as a period (round 4): directly after a word or a closing
# mark, and before white space, a closing mark or the end. Anywhere else ("!=", "!Deployed", "! Deployed") it
# stays outside the allowed characters.
_SENTENCE_BANG = re.compile(r"(?<=[^\W_]|[\"')*`\u201d\u2019])!(?=\s|$|[\"')*_`\u201d\u2019])")

# A whole answer that is one JSON object with ONE of these keys and the value as a string is
# read as that string. No other JSON, key-value or table shape is accepted.
JSON_ANSWER_KEYS = {
    "agency": ("agency", "agency_name", "federal_agency"),
    "stage": ("stage", "stage_of_development", "development_stage"),
    "high_impact": ("high_impact_determination", "high_impact", "is_high_impact", "determination"),
}

# A sentence that starts with one of these verbs, or holds the verb directly before "it",
# "this" or "that", is a question whether or not a question mark follows ("Is it Deployed").
QUESTION_OPENERS = frozenset({"is", "was", "has", "are", "were", "have", "does", "did", "do"})
INVERTED_SUBJECTS = frozenset({"it", "this", "that"})
# A value with one of these words directly after it (nothing but a space between) is a verb
# with an object, not a value: "It deployed the use case", "The agency retired it".
OBJECTS_AFTER_A_VERB = frozenset({"it", "this", "that", "the", "its"})

# Other spellings of a value that are accepted, value by value.
EXTRA_SPELLINGS = {"Pre-deployment": ("Predeployment",)}

# An agency abbreviation is accepted on its own only when it cannot be taken for a US state
# or territory code or for an ordinary word. The others ("VA", "ED", "STATE", "DOC", "DOT",
# "DOE", "SEC" in the inventory at the pinned commit) count only directly after the full name,
# as the documents write it: "Department of State (STATE)".
US_STATE_CODES = frozenset("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH
    NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC AS GU MP PR VI""".split())
# Hand-written for the abbreviations of the inventory at the pinned commit, plus the words a
# federal agency is most likely to be shortened to. It is not a dictionary: review it before
# using another CSV (20_build_eval_set.py prints which abbreviations were ruled out).
ORDINARY_WORD_ABBREVIATIONS = frozenset("""STATE DOC DOT DOE SEC ED ARMY NAVY AIR MINT PEACE ACTION ARTS AID TRADE
    LABOR ENERGY JUSTICE INTERIOR COMMERCE TREASURY DEFENSE WAR EDUCATION POST FED USA US MAIL ACT ADD ALL ANY ARE
    ASK BAR CAN CAR DAY END FAR FEW FIT FOR GET HAS HER HIM HIS HOW ITS LAW LET MAY NEW NOT NOW OLD ONE OUR OUT
    OWN PER PUT RAN RED RUN SAY SEE SET SHE THE TOO TOP TWO USE WAS WAY WHO WHY YES YET YOU CORPS FIRST HOUSE
    SENATE COURT MINE MINES LAND PARK FISH CENSUS PATENT""".split())


def abbreviation_stands_alone(abbreviation: str) -> bool:
    """May this agency abbreviation be credited when it is not next to the agency's full name?"""
    text = (abbreviation or "").strip()
    if len(text) < 3 or not text.isalpha() or text != text.upper():
        return False                                   # two letters: a state code or too short to trust
    return text not in US_STATE_CODES and text not in ORDINARY_WORD_ABBREVIATIONS


def _plain_words(text: str) -> tuple[str, ...]:
    return tuple(normalise(text).split())


def _all_fillers(kind: str) -> frozenset:
    return frozenset(tuple(p.split()) for p in FILLER_PHRASES["common"] + FILLER_PHRASES.get(kind, ())
                     + LEAD_IN_PHRASES["common"])


def agency_short_names(label_set: list[dict]) -> tuple[dict[str, list[str]], list[dict]]:
    """Short names of the "Department of X" agencies, checked against EVERY agency in the set.

    For "Department of [the] X": "X Department", "Dept of [the] X", and "X" alone when X is two
    words or more ("Veterans Affairs"; never "Energy" or "State", which are ordinary words).
    A short name is dropped, for every agency that would get it, when its words are found inside
    another agency's full name, when two agencies would share it, or when it consists of filler
    words only. Returns ({label: [short names]}, [what was dropped and why]).
    """
    full = {entry["label"]: _plain_words(entry["label"]) for entry in label_set}
    fillers = _all_fillers("agency")
    candidates: dict[str, list[str]] = {label: [] for label in full}
    for label, words in full.items():
        if words[:2] != ("department", "of") or len(words) < 3:
            continue
        subject = label.split(" of ", 1)[1]                      # "the Treasury", "Veterans Affairs"
        bare = subject[4:] if subject.lower().startswith("the ") else subject
        candidates[label] += [f"{bare} Department", f"Dept of {subject}"]
        if len(bare.split()) >= 2:
            candidates[label].append(bare)

    def inside(short: tuple[str, ...], longer: tuple[str, ...]) -> bool:
        return any(longer[i:i + len(short)] == short for i in range(len(longer) - len(short) + 1))

    owners: dict[tuple[str, ...], list[str]] = {}
    for label, names in candidates.items():
        for name in names:
            owners.setdefault(_plain_words(name), []).append(label)
    dropped: list[dict] = []
    kept: dict[str, list[str]] = {label: [] for label in full}
    for label, names in candidates.items():
        for name in names:
            words = _plain_words(name)
            reason = None
            if len(owners[words]) > 1:
                reason = "shared by " + " and ".join(sorted(owners[words]))
            elif all((word,) in fillers for word in words):
                reason = "made of filler words only"
            else:
                for other, other_words in full.items():
                    if other != label and inside(words, other_words):
                        reason = f"its words are inside the name of {other}"
                        break
                else:
                    for other_words, other_labels in owners.items():
                        if other_labels != [label] and (inside(words, other_words) or inside(other_words, words)):
                            reason = f"it overlaps a short name of {other_labels[0]}"
                            break
            if reason:
                dropped.append({"label": label, "short_name": name, "why": reason})
            else:
                kept[label].append(name)
    return kept, dropped


def _freeze(label_set: list[dict]) -> tuple:
    return tuple((entry["label"], tuple((alias.get("text") or "") for alias in entry.get("aliases", [])
                                        if alias.get("case_sensitive"))) for entry in label_set)


@functools.lru_cache(maxsize=16)
def _spellings(frozen: tuple, kind: str) -> tuple:
    """Every accepted spelling of every value: (words, label, how, text as shown to a person).

    how: "plain" (any case), "exact" (an abbreviation, as written), "with_abbreviation" (the full
    name directly followed by the agency's own abbreviation, as the documents write it) and, since
    round 4, "abbreviation_first" (the abbreviation directly followed by the full name in brackets:
    "VA (Department of Veterans Affairs)").
    """
    out = []
    label_set = [{"label": label, "aliases": [{"text": a, "case_sensitive": True} for a in abbreviations]}
                 for label, abbreviations in frozen]
    short = agency_short_names(label_set)[0] if kind == "agency" else {}
    full_names = {_plain_words(label): label for label, _ in frozen}
    for label, abbreviations in frozen:
        out.append((_plain_words(label), label, "plain", label))
        for abbreviation in abbreviations:
            if not abbreviation:
                continue
            out.append((_plain_words(label) + (abbreviation,), label, "with_abbreviation",
                        f"{label} ({abbreviation})"))
            out.append(((abbreviation,) + _plain_words(label), label, "abbreviation_first",
                        f"{abbreviation} ({label})"))
            if abbreviation_stands_alone(abbreviation):
                out.append(((abbreviation,), label, "exact", abbreviation))
        for name in short.get(label, []) + list(EXTRA_SPELLINGS.get(label, ())):
            out.append((_plain_words(name), label, "plain", name))
        # Round 4: "Department of Treasury" for "Department of the Treasury", unless those words are
        # another agency's name or stand inside one.
        words = _plain_words(label)
        if kind == "agency" and words[:3] == ("department", "of", "the") and len(words) > 3:
            without_the = words[:2] + words[3:]
            taken = any(without_the == other or any(other[i:i + len(without_the)] == without_the
                                                    for i in range(len(other) - len(without_the) + 1))
                        for other in full_names if other != words)
            if not taken:
                out.append((without_the, label, "plain", "Department of " + label.split(" of the ", 1)[1]))
    return tuple(out)


_HYPHENS = "-" + "".join(chr(c) for c in range(0x2010, 0x2016))


@functools.lru_cache(maxsize=4096)
def _value_gaps(shown: str) -> tuple:
    """What stands between the words of a value as the CSV (or this file) writes it: "space", "hyphen", "comma"."""
    found = list(_WORD.finditer(shown))
    gaps = []
    for position in range(1, len(found)):
        between = shown[found[position - 1].end():found[position].start()]
        gaps.append("comma" if "," in between else "hyphen" if any(ch in between for ch in _HYPHENS) else "space")
    return tuple(gaps)


def accepted_spellings(label_sets: dict[str, list[dict]], kind: str) -> dict[str, list[str]]:
    """{value: [every spelling of it that exact match accepts]}, for a person to read."""
    listed: dict[str, list[str]] = {entry["label"]: [] for entry in label_sets[kind]}
    for _, label, _, shown in _spellings(_freeze(label_sets[kind]), kind):
        listed[label].append(shown)
    return listed


_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*")
# What may sit between two words of one value (round 4, MINOR 9: "It is not, High-impact." and "not - High-impact"
# were read as the value "Not High-impact", because any mix of spaces, commas and dashes was let through).
# Where the value has a space: white space. Where it has a hyphen: white space or one hyphen or dash
# ("High impact", "High - impact"). Where it has a comma: the comma, or white space.
_INSIDE_A_VALUE = {
    "space": re.compile(r"[ \t]+"),
    "hyphen": re.compile(r"[ \t]+|[ \t]*[\-\u2010-\u2015][ \t]*"),
    "comma": re.compile(r"[ \t]*,[ \t]*|[ \t]+"),
}
_GLUED = re.compile(r"_+")
_AFTER_DEPT = re.compile(r"\.[ \t]*")                                  # "Dept. of Energy"
# "Department of State (STATE)", and since round 4 with emphasis marks around the name: "**Department of State** (STATE)"
_BEFORE_AN_ABBREVIATION = re.compile(r"[*_]{0,3}[ \t]*\(?[ \t]*[*_]{0,3}")
_AFTER_AN_ABBREVIATION = re.compile(r"[*_]{0,3}[ \t]*\([ \t]*[*_]{0,3}")                 # "VA (Department of Veterans Affairs)"
# Round 4, MINOR 5: a semicolon starts a clause too ("The agency was reported; is the ... named").
_SENTENCE_END = re.compile(r"[.!?;\n]")
_QUOTED_SPAN = re.compile('"([^"\\n]*)"|' + chr(0x201C) + "([^" + chr(0x201C) + chr(0x201D) + "\\n]*)" + chr(0x201D))
_AGENCY_IN_QUESTION = re.compile(r'", reported by the (.+)\?$')


def _tokens(text: str) -> list[dict]:
    """The words of a text: lower-cased, as written, and what stands between each and the one before."""
    out = []
    position = 0
    for match in _WORD.finditer(text):
        gap = text[position:match.start()]
        out.append({"norm": match.group().casefold(), "raw": match.group(), "gap": gap, "at": match.start(),
                    "starts_sentence": not out or bool(_SENTENCE_END.search(gap))})
        position = match.end()
    return out


def _unwrap_json(text: str, kind: str) -> tuple[str | None, bool]:
    """(the answer inside an accepted JSON object, True) or (None, True) for any other JSON-like text.

    (text, False) is not returned here: the caller keeps the text when no brace is in it.
    """
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", body, flags=re.DOTALL)
    if fenced:
        body = fenced.group(1).strip()
    try:
        pairs = json.loads(body, object_pairs_hook=list)
    except ValueError:
        return None, True
    if not (body.startswith("{") and isinstance(pairs, list) and len(pairs) == 1):
        return None, True
    key, value = pairs[0]
    if key not in JSON_ANSWER_KEYS.get(kind, ()) or not isinstance(value, str) or "{" in value or "}" in value:
        return None, True
    return value, True


def _uncovered(words: list[str], fillers: frozenset) -> list[str]:
    """The fewest words of a run that no combination of filler phrases covers, in order."""
    longest = max((len(phrase) for phrase in fillers), default=1)
    best: list[tuple[int, list[str]]] = [(0, [])]                    # best[i]: cost and leftovers of words[:i]
    for end in range(1, len(words) + 1):
        cost, left = best[end - 1]
        choice = (cost + 1, left + [words[end - 1]])
        for length in range(1, min(longest, end) + 1):
            if tuple(words[end - length:end]) in fillers and best[end - length][0] < choice[0]:
                choice = best[end - length]
        best.append(choice)
    return best[-1][1]


def read_answer(item: dict, answer: str, label_sets: dict[str, list[dict]]) -> dict:
    """Read one answer to an answerable question by the allow-list. See the module docstring.

    Returns {"note": str, "found": [values found, in order], "unread": "words not on any list"}.
    note is "match", "different_value", or starts with "unclear".

    Order of the steps: (1) the refusal sentence anywhere makes the answer unclear; (2) a JSON object
    in the one accepted form is replaced by its value; (3) the question, if repeated word for word,
    and the two citation marks are removed; (4) any character outside ALLOWED_PUNCTUATION makes the
    answer unclear; (5) the use case name, and "reported by the <agency>" as the question words it,
    are deleted; (6) field-name phrases are set aside; (7) values are found, longest spelling first;
    (8) every word left must be covered by FILLER_PHRASES; (9) the question and verb shapes are refused.
    """
    kind = item["label_set"]
    expected = item["expected_answer"]

    def result(note: str, found=(), unread=()) -> dict:
        return {"note": note, "found": list(dict.fromkeys(found)), "unread": " ".join(unread)}

    if mentions_decline(answer):
        return result("unclear_mixed_with_the_refusal_sentence")
    text = unicodedata.normalize("NFKC", answer).replace("\u2019", "'").replace("\u2018", "'")
    if "{" in text or "}" in text:
        inner, _ = _unwrap_json(text, kind)
        if inner is None:
            return result("unclear_json_form_not_accepted")
        text = inner
    question = unicodedata.normalize("NFKC", item.get("question") or "")
    if question and question in text:
        text = text.replace(question, " \n ", 1)               # the question repeated, once, word for word
    for mark in CITATION_MARKS:
        text = re.sub(mark, " ", text)
    name = unicodedata.normalize("NFKC", item.get("use_case_name") or "").strip()
    if name:
        # The name as the question gives it, characters and all (a name may hold "/" or "&"), with the
        # quotation marks around it. What replaces it is a pair of brackets, so the words on its two sides
        # are never read as one value. (Until round 4 it was one quotation mark; brackets leave the other
        # quotation marks of the answer in pairs, which the check for a foreign quoted name below needs.)
        marks = '["' + chr(0x201C) + chr(0x201D) + "]"
        text = re.sub(marks + "?" + r"\s+".join(re.escape(part) for part in name.split()) + "(?:[.]?" + marks + ")?",
                      " ( ) ", _SENTENCE_BANG.sub(".", text), flags=re.IGNORECASE)
    text = _SENTENCE_BANG.sub(".", text)
    odd = sorted({ch for ch in text if not (ch.isalnum() or ch.isspace() or ch in ALLOWED_PUNCTUATION)})
    if odd:
        return result("unclear_character_outside_the_allowed_list", unread=odd)

    tokens = _tokens(text)

    def take_out(words: tuple[str, ...]) -> None:
        """Delete every occurrence of a word sequence the question itself gave."""
        if not words:
            return
        position = 0
        while position <= len(tokens) - len(words):
            if tuple(t["norm"] for t in tokens[position:position + len(words)]) == words:
                first = tokens[position]
                del tokens[position:position + len(words)]
                if position < len(tokens):
                    # What stood around the deleted words stays between its neighbours, so two halves
                    # of a value are not read as one across them. The next word does not become the
                    # start of the sentence: in '"<name>" is Deployed' the name was the subject.
                    tokens[position]["gap"] = first["gap"] + " ( ) " + tokens[position]["gap"]
            else:
                position += 1

    take_out(tuple(t["norm"] for t in _tokens(unicodedata.normalize("NFKC", item.get("use_case_name") or ""))))
    # The stage and high-impact questions end "..., reported by the <agency>?". Those words, as a
    # whole, are the question's own. The agency name anywhere else in the answer is not taken out:
    # "The <agency> deployed it" has to stay unreadable.
    named_agency = _AGENCY_IN_QUESTION.search(question) if kind != "agency" else None
    if named_agency:
        take_out(("reported", "by", "the") + tuple(t["norm"] for t in _tokens(named_agency.group(1))))

    taken: dict[int, str] = {}                                 # token position -> "field" or the value's label
    spans: list[tuple[int, str]] = []                          # (first token, label) of every value found

    def free(first: int, width: int) -> bool:
        return all(position not in taken for position in range(first, first + width))

    def joined(first: int, width: int, gaps: tuple = ()) -> bool:
        """Between the words of one value only what the value itself has there (_INSIDE_A_VALUE); a period
        only after "Dept". gaps: what the value has between its words, for the words from the second on."""
        for offset, position in enumerate(range(first + 1, first + width)):
            kind_of_gap = gaps[offset] if offset < len(gaps) else "space"
            if not (_INSIDE_A_VALUE[kind_of_gap].fullmatch(tokens[position]["gap"])
                    or (tokens[position - 1]["norm"] == "dept" and _AFTER_DEPT.fullmatch(tokens[position]["gap"]))):
                return False
        return True

    for phrase in sorted(FIELD_NAME_PHRASES.get(kind, ()), key=lambda p: -len(p.split())):
        words = tuple(phrase.split())
        for first in range(len(tokens) - len(words) + 1):
            if free(first, len(words)) and tuple(t["norm"] for t in tokens[first:first + len(words)]) == words:
                taken.update({position: "field" for position in range(first, first + len(words))})

    spellings = sorted(_spellings(_freeze(label_sets[kind]), kind), key=lambda s: (-len(s[0]), s[1], s[2]))
    for words, label, how, shown in spellings:
        width = len(words)
        gaps = _value_gaps(shown)
        for first in range(len(tokens) - width + 1):
            if not free(first, width):
                continue
            window = tokens[first:first + width]
            if how == "plain":
                ok = tuple(t["norm"] for t in window) == words and joined(first, width, gaps)
            elif how == "exact":
                ok = window[0]["raw"] == words[0]
            elif how == "abbreviation_first":                  # the abbreviation, then the full name in brackets
                ok = (window[0]["raw"] == words[0] and tuple(t["norm"] for t in window[1:]) == words[1:]
                      and joined(first + 1, width - 1, gaps[1:])
                      and bool(_AFTER_AN_ABBREVIATION.fullmatch(window[1]["gap"])))
            else:                                              # the full name, then its own abbreviation
                ok = (tuple(t["norm"] for t in window[:-1]) == words[:-1] and window[-1]["raw"] == words[-1]
                      and joined(first, width - 1, gaps[:-1])
                      and bool(_BEFORE_AN_ABBREVIATION.fullmatch(window[-1]["gap"])))
            if ok:
                taken.update({position: label for position in range(first, first + width)})
                spans.append((first, label))
    spans.sort()
    found = [label for _, label in spans]

    # Round 4, MINOR 5: text in quotation marks that is not the question's use case name (that one is gone by
    # now) and holds no value: another name, built from list words ('named "AI Use Case Inventory"').
    foreign_name = False
    for span in _QUOTED_SPAN.finditer(text):
        inside = [position for position, token in enumerate(tokens) if span.start() < token["at"] < span.end()]
        if inside and all(position not in taken for position in inside):
            foreign_name = True

    fillers = _all_fillers(kind)
    unread: list[str] = []
    run: list[str] = []
    for position, token in enumerate(tokens + [None]):
        if token is None or (position in taken and taken[position] != "field"):
            unread += _uncovered(run, fillers)                 # a value ends the run: no phrase spans it
            run = []
        elif position not in taken:
            # round 4: "of" between the name of the field and the value ("a stage of development of Deployed")
            if (token["norm"] == "of" and taken.get(position - 1) == "field"
                    and taken.get(position + 1, "field") != "field"):
                continue
            # Round 4: two words run together with an underscore ("was_determined") are not two words of a
            # phrase. The underscore goes into the run as a thing of its own, which is on no list.
            if run and position - 1 not in taken and _GLUED.fullmatch(token["gap"]):
                run.append("_")
            run.append(token["norm"])

    asks = False
    rest = [(position, token) for position, token in enumerate(tokens) if position not in taken]
    for index, (position, token) in enumerate(rest):
        if token["norm"] not in QUESTION_OPENERS:
            continue
        follows = rest[index + 1] if index + 1 < len(rest) else None
        if token["starts_sentence"] or (follows and follows[0] == position + 1
                                        and follows[1]["norm"] in INVERTED_SUBJECTS):
            asks = True

    as_a_verb = False
    for position in range(1, len(tokens)):
        if (position not in taken and taken.get(position - 1, "field") != "field"
                and tokens[position]["norm"] in OBJECTS_AFTER_A_VERB and not tokens[position]["gap"].strip()):
            as_a_verb = True

    if not spans:
        return result("unclear_no_value_found", found, unread)
    # Round 4, MINOR 4: ONE value written in two places is one value ("EPA (Environmental Protection Agency)",
    # a headline line and then the sentence). Two DIFFERENT values of the field are still unclear.
    # Three places at most ("Deployed, Deployed, Deployed." is in the kit's own hand-labelled set as an answer
    # a person accepts): a model that writes the value more often is repeating itself, and until round 4
    # every such answer was unclear.
    if len(set(found)) > 1:
        return result("unclear_more_than_one_value", found, unread)
    if len(found) > 3:
        return result("unclear_one_value_written_more_than_three_times", found, unread)
    if unread:
        return result("unclear_words_outside_the_filler_list", found, unread)
    if foreign_name:
        return result("unclear_quoted_text_that_is_not_the_use_case_name", found, unread)
    if asks:
        return result("unclear_reads_as_a_question", found, unread)
    if as_a_verb:
        return result("unclear_value_used_as_a_verb", found, unread)
    return result("match" if set(found) == {expected} else "different_value", found)


def score_exact(item: dict, answer: str | None, label_sets: dict[str, list[dict]]) -> dict:
    """Deterministic check of one answer against the expected CSV value.

    Returns {"exact", "declined", "unclear", "note", "asserted", "found", "unread"}.
      exact     True only for note "match" (answerable) or the refusal sentence alone (unanswerable)
      unclear   the allow-list could not read the answer: counted as NOT correct, in its own row
      asserted  the one value the answer states cleanly ([] when the answer is unclear)
      found     every value of the field the reader saw, clean or not
      unread    the words or characters that are on no list, for the person who reads the row
    """
    answer = answer or ""
    declined = is_decline(answer)
    base = {"exact": False, "declined": declined, "unclear": False, "note": "", "asserted": [],
            "found": [], "unread": ""}
    if not item["answerable"]:
        if declined:
            note = "declined_as_it_should"
        elif mentions_decline(answer):
            note = "decline_sentence_with_other_text"
        else:
            note = "answered_an_unanswerable_question"
        return dict(base, exact=declined, note=note)
    if declined:
        return dict(base, note="declined_an_answerable_question")
    if not answer.strip():
        return dict(base, unclear=True, note="empty_answer")

    reading = read_answer(item, answer, label_sets)
    clean = reading["note"] in ("match", "different_value")
    return dict(base, exact=reading["note"] == "match", unclear=not clean, note=reading["note"],
                asserted=reading["found"] if clean else [], found=reading["found"], unread=reading["unread"])


def retrieval_hit(expected_doc_id: str | None, retrieved_doc_ids: list[str | None]) -> dict:
    """Is the source document among the retrieved chunks, and at which rank (1-based)?"""
    if not expected_doc_id:
        return {"hit": None, "rank": None}
    for position, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id == expected_doc_id:
            return {"hit": True, "rank": position}
    return {"hit": False, "rank": None}


# =====================================================================================
# The judge's reply. CORRECT and DECLINED are the two verdicts that give the system credit
# (CORRECT on a question that has an answer, DECLINED on one that has none), so they are
# returned only when nothing in the reply speaks against them. The word lists are below.
# =====================================================================================

# Keys an object may carry next to "verdict". Any other key makes the reply unparseable.
JUDGE_REASON_KEYS = frozenset({"reason", "reasoning", "explanation", "rationale", "justification", "note",
                               "notes", "comment"})
JUDGE_NUMBER_KEYS = frozenset({"confidence"})

# The reference shown to the judge for a question that has no answer in the corpus. It names
# the two verdicts that make sense and does not use the word "correct" for declining. It is
# defined here (kitlib/evalloop.py builds the judge prompt from it) because the reader below
# has to know it: "NO ANSWER" in a judge's reason is this reference quoted, not the judge
# saying that no answer was given.
NO_ANSWER_REFERENCE = (
    "NO ANSWER. The documents do not contain the answer to this question. A candidate that declines "
    "gets DECLINED. A candidate that gives any answer gets INCORRECT."
)
NO_ANSWER_TOKEN = "NO ANSWER"

# What replaces a quoted value in the judge's text before the word lists are applied.
JUDGE_MASK = " <value> "

# Field names a judge writes that hold the words of a value ("the high-impact determination").
# They are set aside before values are looked for, in addition to FIELD_NAME_PHRASES.
JUDGE_FIELD_NAME_PHRASES = {
    "high_impact": ("high impact classification", "high impact designation", "high impact field",
                    "high impact value", "high impact question", "high impact label", "high impact category",
                    "high impact rating"),
}

# "does not decline", "not a refusal", "no refusal": the reply says the candidate did NOT decline.
# Under CORRECT that is no contradiction, so the phrase is taken out before the list is applied.
JUDGE_NEGATED_DECLINE = (
    r"\b(?:no|not|never|without)\s+(?:(?:a|an|any|the|really|actually|clean|proper|real|true|full)\s+){0,2}"
    r"(?:declin\w*|refus\w*)",
)
# The same, and "instead of declining", "should have declined", "fails to decline". Under DECLINED
# each of them contradicts the verdict; under INCORRECT none of them is "the candidate declined".
JUDGE_NOT_DECLINING = JUDGE_NEGATED_DECLINE + (
    r"\b(?:instead of|rather than)\s+(?:declin\w*|refus\w*)",
    r"\b(?:should|ought to|needed to|was expected to|was supposed to)\s+(?:have\s+)?(?:declin\w*|refus\w*)",
    r"\b(?:fail\w*|refus\w*|declin\w*)\s+to\s+(?:declin\w*|refus\w*)",
    r"\b(?:cannot|can\s+not|unable\s+to)\s+(?:declin\w*|refus\w*)",
    r"\bnot\s+(?:give|offer|provide|contain|constitute|make)\w*\s+(?:a|an|any)\s+(?:declin\w*|refus\w*)",
)
# Under DECLINED only: "does not say it cannot answer".
JUDGE_NOT_SAYING_IT_CANNOT = (
    r"\bnot\s+(?:say|state|claim|indicate|mention)\w*\s+(?:that\s+)?(?:it\s+)?(?:cannot|can not|is unable)",
)

# Round 3: "nothing incorrect", "not incorrect", "no errors", "nothing in it is wrong".
_NOTHING_INCORRECT = (
    r"\b(?:no|not|nothing|without)\s+(?:(?:is|was|are|a|an|any|in\s+it|stated|added|factually)\s+){0,2}"
    r"(?:incorrect\w*|wrong\w*|inaccura\w*|error\w*|mistak\w*|mismatch\w*|discrepan\w*)(?!-|\s+free\b)"
    r"(?:\s+(?:is|was|are)\s+(?:added|stated|present|found|included))?"
)

# Phrases that hold a contradicting word but say the opposite of a contradiction. They are
# taken out of the text before the lists below are applied. A phrase never crosses a comma:
# "No, it contradicts the reference" is not one of them. Every phrase is a negation followed by
# the BAD thing it denies; a negation that is not in one of these phrases still contradicts.
JUDGE_SAFE_PHRASES = (
    r"\b(?:no|not|nothing|never|without)\s+(?:(?:any|other|additional|a|fact|facts|statement|statements|claim|"
    r"claims|detail|details|information|that|which)\s+){0,3}(?:contradict\w*|conflict\w*)"
    r"(?:\s+(?:fact|facts|statement|statements|claim|claims|detail|details|information))?",
    r"\b(?:different|differing)\s+(?:wording|words|phrasing|spelling|case|capitali[sz]ation|format|formatting|"
    r"punctuation)\b",
    r"\b(?:wording|phrasing|spelling|format|formatting|punctuation|capitali[sz]ation)\s+(?:may\s+|might\s+|can\s+)?"
    r"differs?\b",
    r"\bworded\s+differently\b",
    r"\blet me know if you (?:need|have|want|would like)\b[^.\n?]*",        # the usual closing line
    _NOTHING_INCORRECT,
    # round 3: "adds no other facts.", "no additional claims are added", "and nothing else." Only at the
    # end of a clause: "no other facts are correct" is not one of them.
    r"\b(?:no|without)\s+(?:(?:any|added)\s+)?(?:other|additional|extra|further|extraneous|unsupported)\s+"
    r"(?:fact|facts|claim|claims|statement|statements|detail|details|information)"
    r"(?:\s+(?:is|are|was|were)\s+(?:added|stated|given|included|present))?(?=\s*(?:[.,;:)]|$))",
    r"\bnothing\s+(?:else|more|further)(?:\s+(?:is|was)\s+(?:added|stated|given|included))?(?=\s*(?:[.,;:)]|$))",
)
# The phrases of JUDGE_SAFE_PHRASES that are also taken out under DECLINED ("nothing incorrect is stated").
JUDGE_SAFE_UNDER_DECLINED = (_NOTHING_INCORRECT,)

# A reply whose verdict is CORRECT is unparseable when its reason, or any other text in it,
# holds one of these (regular expressions on the lower-cased text, "n't" read as " not").
CONTRADICTS_CORRECT = (
    r"\bincorrect\w*", r"\bdeclin\w*", r"\brefus\w*", r"\bnot\b", r"\bno\b", r"\bnon\b", r"\bnever\b",
    r"\bnone\b", r"\bneither\b", r"\bnor\b", r"\bnothing\b", r"\bcannot\b", r"\bunable\b", r"\bwithout\b",
    r"\bwrong\w*", r"\bfalse\b", r"\berror\w*", r"\bmistak\w*", r"\binaccura\w*", r"\bmismatch\w*",
    r"\bdiffer\w*", r"\banother\b", r"\bother\b", r"\bcontradict\w*", r"\bconflict\w*", r"\black\w*",
    r"\bmissing\b", r"\babsent\b", r"\bomit\w*", r"\bfail\w*", r"\bpartial\w*", r"\bpartly\b", r"\bexcept\w*",
    r"\bbut\b", r"\bhowever\b", r"\balthough\b", r"\bthough\b", r"\byet\b", r"\bactually\b", r"\bdespite\b",
    r"\binstead\b", r"\brather\b", r"\bunlike\b", r"\bopposite\b", r"\bshould\b", r"\bwould\b", r"\bif\b",
    r"\bunless\b", r"\bonly\b", r"\bwait\b", r"\bcaveat\w*", r"\bunsure\b", r"\buncertain\w*", r"\bunclear\b",
    r"\bdoubt\w*", r"\bguess\w*", r"\bsecond look\b", r"\breflection\b", r"\?",
)

# What may follow "says" or "states" in a reply whose verdict is DECLINED (negative lookaheads).
_SAYS_IT_CANNOT = (
    r"(?!\s+(?:that\s+)?(?:it|they|there)\s+(?:cannot|can\s+not|is\s+unable|are\s+unable|does\s+not|do\s+not|"
    r"has\s+no|have\s+no|is\s+no|lacks?)\b)"
    r"(?!\s+(?:that\s+)?the\s+(?:documents?|passages?|inventory|information|answer)\s+(?:do|does|is|are)\s+not\b)"
    r"(?!\s*[:,]?\s+[\"'`" + chr(0x201C) + r"]?\s*i\s+(?:cannot|can\s+not|do\s+not|am\s+unable|have\s+no)\b)"
    r"(?!\s+(?:so|nothing|no)\b)"
)

_SAYS = r"\b(?:says?|said|states?|stated|replies|replied|responds|responded|writes|wrote)\b"

# A reply whose verdict is DECLINED is unparseable when its text holds one of these ...
CONTRADICTS_DECLINED = (
    r"\bcorrect\b", r"\bincorrect\w*", r"\bwrong\w*", r"(?<!not )\banswered\b", r"\bnames\b", r"\bnamed\b",
    # "gives Pilot" speaks against DECLINED; "does not give an answer" and "declines to give the budget" do not.
    r"(?<!declines to )(?<!declined to )(?<!not )\bgives?\s+(?!no\b|none\b|nothing\b)", r"\bnot\s+give\s+up\b",
    r"\bgave\b", r"\bguess\w*",
    r"\bbut\b", r"\bhowever\b",
    r"\balthough\b", r"\bthough\b", r"\byet\b", r"\bthen\b", r"\bactually\b", r"\bdespite\b", r"\binstead\b",
    r"\brather\b", r"\balso\b", r"\bstill\b", r"\banyway\b", r"\bnevertheless\b", r"\bwait\b", r"\?",
    # round 3: "says 4 million dollars", "states Pilot", "provides an agency", "does not answer correctly".
    # "says it cannot answer", "states that the documents do not contain it" and a quoted "I cannot ..." are
    # not among them.
    _SAYS + _SAYS_IT_CANNOT,
    r"(?<!not )\bprovid(?:es|ed|ing)\s+(?:an?|the|its)\b",
    r"\bnot\s+(?:\w+\s+)?correct\w*",
) + JUDGE_NOT_DECLINING + JUDGE_NOT_SAYING_IT_CANNOT
# ... and, when it gives a reason at all, unless that reason says the candidate declined.
SAYS_DECLINED = (
    r"\bdeclin\w*", r"\brefus\w*", r"\bcannot\b", r"\bcan not\b", r"\bunable\b", r"\bno answer\b",
    r"\bnot answer\w*", r"\bnot provide\w*", r"\bnot give\w*", r"\bgives? no\b", r"\bno information\b",
    r"\bnot know\b", r"\bnot contain\b", r"\babstain\w*", r"\bwithout answering\b",
)
# A reply whose verdict is INCORRECT cannot flatter the system. It is still unparseable when it
# also says the candidate declined, or says "is correct" with no qualifying word anywhere.
_SAYS_IS_CORRECT = re.compile(r"\b(?:is|are|was|seems|looks)\s+(?:\w+\s+)?(?:correct|right|accurate)\b")
_QUALIFIES = re.compile(r"\b(?:not|no|wrong\w*|but|however|partial\w*|partly|only|except\w*|although|differ\w*)\b")

_WORD_PATTERN = r"(correct|incorrect|declined)"
_MARKS = r"""["'*`_]*"""
# "Verdict: CORRECT", "verdict = incorrect", "The verdict is CORRECT." : one whole line.
_VERDICT_LINE = re.compile(
    r"^\s*" + _MARKS + r"(?:the\s+|my\s+)?(?:final\s+)?verdict" + _MARKS + r"\s*(?:is\b|[:=\-])\s*"
    + _MARKS + r"\s*" + _WORD_PATTERN + _MARKS + r"\s*[.,]?\s*" + _MARKS + r"\s*$", re.IGNORECASE)
# The reply is the word alone, or the word and then a dash, a colon, a period or a line break.
_LEADING_WORD = re.compile(
    r"^\s*" + _MARKS + _WORD_PATTERN + _MARKS
    + r"(?:\s*[.!]?\s*" + _MARKS + r"\s*$|\s*[-:\u2013.]\s+(?P<rest>.+)$|[ \t]*\n(?P<below>.+)$)",
    re.IGNORECASE | re.DOTALL)
_LABEL_LINE = re.compile(r"\b(?:candidate|reference|expected|actual|given|got|match\w*)\s*[:=]", re.IGNORECASE)
_REASON_LABEL = re.compile(r"^\s*(?:reason|reasoning|explanation|rationale)\s*[:=\-]\s*", re.IGNORECASE)
_UNREAD_VERDICT = re.compile(r"""verdict\w*["']?\s*[:=]\s*["']?\w""", re.IGNORECASE)
_OPEN_STRING = r'"(?:[^"\\]|\\.)*'      # a JSON string that may not have been closed yet
# JSON cut off by the token limit: optional prose, "{", the verdict pair FIRST, then at most a
# comma, one more key and its string value, either of which may be unfinished. Nothing else.
_CUT_OFF_JSON = re.compile(
    r'(?P<before>[^{]*)\{\s*"verdict"\s*:\s*"(?P<verdict>[^"\\]*)"\s*'
    r'(?:,\s*(?:(?P<key>' + _OPEN_STRING + r')(?:"\s*(?::\s*(?:(?P<value>' + _OPEN_STRING + r')"?)?)?)?)?)?\s*',
    re.DOTALL)


_UNESCAPED_REASON = re.compile(
    r'\s*\{\s*"verdict"\s*:\s*"(?P<verdict>[^"\\]*)"\s*,\s*"(?:reason|reasoning|explanation|rationale)"\s*:\s*'
    r'"(?P<value>.*)"\s*\}\s*', re.DOTALL)


class _NotAVerdict(ValueError):
    """The reply holds something that cannot be read as one clean verdict."""


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    keys = [str(key).strip().lower() for key, _ in pairs]
    if keys.count("verdict") > 1:
        raise _NotAVerdict("the key 'verdict' appears twice in one object")
    return dict(zip(keys, (value for _, value in pairs)))


def _closing_brace(text: str, start: int) -> int:
    """Index of the brace that closes the one at `start`, quotes respected. -1 if there is none."""
    depth, quote, position = 0, "", start
    while position < len(text):
        ch = text[position]
        if quote:
            if ch == "\\":
                position += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return -1


def _lenient_object(text: str):
    """Read an object that strict JSON refuses for one of two small reasons, or return None.

    The two reasons: a comma before the closing brace, and single quotes instead of double
    quotes (only when the text holds no double quote at all).
    """
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    if '"' not in fixed:
        fixed = fixed.replace("'", '"')
    if fixed == text:
        return None
    try:
        return json.loads(fixed, object_pairs_hook=_pairs)
    except ValueError:
        return None


def _matches(patterns: tuple[str, ...], text: str) -> list[str]:
    return [found.group() for pattern in patterns for found in re.finditer(pattern, text)]


def _odd_characters(parts: list[str]) -> list[str]:
    """The characters of a judge's text that are outside JUDGE_ALLOWED_PUNCTUATION, in order.

    The two mask tokens are taken out first: what they stand for (a value, the use case name, the
    question) was not written by the judge and may hold any character.
    """
    odd = []
    for part in parts:
        text = part.replace(JUDGE_MASK.strip(), " ").replace(JUDGE_QUOTED_MASK.strip(), " ")
        text = _JUDGE_SENTENCE_BANG.sub(" ", text)
        odd += [ch for ch in text if not (ch.isalnum() or ch.isspace() or ch in JUDGE_ALLOWED_PUNCTUATION)]
    return odd


# -------------------------------------------------------------------------------------
# Round 3. What in a judge's reply is a VALUE and not the judge's own assertion.
#
# The rehearsal on real model text (README section 8) found that every well-formed reply for
# the value "Not High-impact" was thrown away: the reason quoted the value, and the word "Not"
# in it was read as the judge speaking against its own verdict. So, when the reader is told
# which question the reply is for, these are replaced by JUDGE_MASK before the word lists are
# applied, because the judge did not choose their words:
#   * the question, if it is repeated word for word, and the use case name it asks about
#     (a name of one word only inside quotation marks; always as the question writes it);
#   * for a question that has no answer, the words NO ANSWER and the sentences of the
#     reference shown to the judge;
#   * every accepted spelling of the question's reference answer ("Not High-impact",
#     "Presumed High-Impact, but Not High-impact", the agency's name or its abbreviation) and
#     of a value the question itself gives ("..., reported by the Department of Energy?").
# The candidate's own words are NOT taken out, not even where the judge puts them in quotation
# marks: a quoted answer can hold the very words that speak against the verdict ('Candidate
# says "it is not Deployed"'). A draft of this reader took such spans out and read that reply
# as CORRECT. The price: a CORRECT whose reason quotes a right answer with an innocent list
# word in it ("no other stage is recorded") is unparseable.
# Every value of the three label sets is LOOKED FOR, but a value that is not the reference is
# never taken out. Taking words out can only help a verdict, so the same step also REFUSES
# more than round 2 did:
#   * CORRECT is refused when the reply names a value of the question's field that is not the
#     reference ("Candidate states Deployed; the reference is Pilot.");
#   * DECLINED is refused when the reply names any value that is neither the reference nor in
#     the question ("declines, then states Pilot").
# Without the question nothing is taken out and no value is looked for.
# -------------------------------------------------------------------------------------

_QUOTE_MARKS = "\"'`" + chr(0x201C) + chr(0x201D) + chr(0x2018) + chr(0x2019)


@functools.lru_cache(maxsize=16)
def _judge_spellings(frozen_sets: tuple) -> tuple:
    """Every way a value of any label set may be written in a judge's reply, longest first.

    (words, kind, label, exact, commas). exact: an abbreviation, matched as written; otherwise any
    case. commas: the positions where the value itself has a comma before a word ("Presumed
    High-Impact, but ..."); a comma anywhere else ends the value, so "Not, High-impact" is not one.
    Every abbreviation is in here, also the ones exact match does not accept alone ("DOE",
    "STATE"), because the judge prompt shows the abbreviation as acceptable.
    """
    out = set()
    for kind, frozen in frozen_sets:
        for words, label, how, shown in _spellings(frozen, kind):
            if how == "plain" and words:
                out.add(_judge_spelling(shown, kind, label, False))
        for label, abbreviations in frozen:
            for abbreviation in abbreviations:
                if _WORD.search(abbreviation):
                    out.add(_judge_spelling(abbreviation, kind, label, True))
    return tuple(sorted(out, key=_longest_first))


def _by_first_word(spellings) -> dict:
    """{(exact, first word): ((rank, spelling), ...)}: where to look, for each word of a reply."""
    index: dict[tuple[bool, str], tuple] = {}
    for rank, entry in enumerate(spellings):
        key = (entry[3], entry[0][0])
        index[key] = index.get(key, ()) + ((rank, entry),)
    return index


@functools.lru_cache(maxsize=16)
def _judge_index(frozen_sets: tuple) -> tuple:
    """(the spellings of _judge_spellings, the same as a set, and indexed by their first word)."""
    spellings = _judge_spellings(frozen_sets)
    return spellings, frozenset(spellings), _by_first_word(spellings)


def _judge_spelling(shown: str, kind: str, label: str, exact: bool) -> tuple:
    found = list(_WORD.finditer(shown))
    words = tuple(match.group() if exact else match.group().casefold() for match in found)
    commas = frozenset(position for position in range(1, len(found))
                       if "," in shown[found[position - 1].end():found[position].start()])
    return (words, kind, label, exact, commas)


def _longest_first(entry: tuple) -> tuple:
    return (-len(entry[0]), entry[1], entry[2], entry[3], entry[0])


# Between two words of one value in a judge's reply: spaces (also the no-break space), or one hyphen or dash.
_JUDGE_INSIDE_A_VALUE = re.compile("[ \\t" + chr(0xA0) + "]+|[-" + chr(0x2010) + "-" + chr(0x2015) + "]")
_JUDGE_AT_A_COMMA = re.compile("[ \\t]*,[ \\t]*")


def _name_pattern(name: str):
    """The use case name as the question writes it. One word: only inside quotation marks."""
    parts = name.split()
    if not parts:
        return None
    body = r"\s+".join(re.escape(part) for part in parts)
    if len(_WORD.findall(name)) < 2:
        marks = "[" + re.escape(_QUOTE_MARKS) + "]"
        return re.compile("(?<=" + marks + ")" + body + "(?=" + marks + ")")
    return re.compile(r"(?<![^\W_])" + body + r"(?![^\W_])")


def _judge_context(item: dict | None, label_sets: dict | None) -> dict | None:
    """What read_judge needs to know about the question. None when it was not told enough."""
    if not item or not label_sets:
        return None
    kinds = tuple(kind for kind in ("agency", "stage", "high_impact") if label_sets.get(kind))
    answerable = bool(item.get("answerable"))
    aliases = tuple((alias.get("text") or "", bool(alias.get("case_sensitive")))
                    for alias in item.get("accepted_aliases") or [])
    return _judge_context_of(tuple((kind, _freeze(label_sets[kind])) for kind in kinds), answerable,
                             (item.get("label_set") or None) if answerable else None,
                             (item.get("expected_answer") or None) if answerable else None, aliases,
                             (item.get("question") or "").strip(), (item.get("use_case_name") or "").strip())


@functools.lru_cache(maxsize=512)
def _judge_context_of(frozen_sets: tuple, answerable: bool, kind: str | None, expected: str | None,
                      aliases: tuple, question: str, name: str) -> dict:
    """The context of one question. Built once per question and never changed afterwards."""
    spellings, known, by_first_word = _judge_index(frozen_sets)
    kinds = tuple(set_kind for set_kind, _ in frozen_sets)
    if answerable and kind and expected:
        # The reference itself and its accepted aliases, in case the label set does not hold them.
        extra = [_judge_spelling(expected, kind, expected, False)]
        extra += [_judge_spelling(text, kind, expected, case_sensitive) for text, case_sensitive in aliases]
        extra = [entry for entry in dict.fromkeys(extra) if entry[0] and entry not in known]
        if extra:
            spellings = tuple(sorted(spellings + tuple(extra), key=_longest_first))
            by_first_word = _by_first_word(spellings)
    fields = []
    for field_kind in kinds:
        fields += [tuple(phrase.split()) for phrase in
                   FIELD_NAME_PHRASES.get(field_kind, ()) + JUDGE_FIELD_NAME_PHRASES.get(field_kind, ())]
    verbatim = [text for text in (question, question.rstrip("?").strip()) if len(text) > 12]
    if not answerable:
        verbatim += [NO_ANSWER_REFERENCE] + [part.strip() + "." for part in NO_ANSWER_REFERENCE.split(".")[1:]
                                             if part.strip()]
    context = {
        "kind": kind, "expected": expected, "answerable": answerable,
        "spellings": spellings, "by_first_word": by_first_word,
        "fields": sorted(set(fields), key=lambda words: -len(words)),
        "name": _name_pattern(name),
        "verbatim": [],
        "in_question": frozenset(),
        "everyday": _everyday_names(frozen_sets),
        "own_words": frozenset(found.group().casefold() for found in _WORD.finditer(question + " " + name)),
        "value_words": _value_words(frozen_sets),                  # round 5, F2
    }
    # A value the question itself gives ("..., reported by the Department of Energy?") may be
    # repeated in a reason without being an answer. The use case name is taken out first, so a
    # value that is only part of the name ("... Pilot") does not get this exemption.
    context["in_question"] = frozenset(_mask_judge_text(question, context)[1])
    context["verbatim"] = verbatim
    return context


def _mask_judge_text(text: str, context: dict, quoted_mask: str = JUDGE_MASK) -> tuple[str, list[tuple[str, str]]]:
    """(the text with every quoted value replaced by JUDGE_MASK, [(kind, label) of each value named]).

    quoted_mask: what replaces a quoted thing that is not the reference value (the name, the question,
    a value the question gives, NO ANSWER). read_judge passes JUDGE_QUOTED_MASK to tell the two apart.
    """
    masked = [0] * len(text)                                   # 0 as written, 1 the reference value, 2 another quoted thing

    def cover(start: int, end: int, what: int = 2) -> None:
        masked[start:end] = [what] * (end - start)

    for phrase in context["verbatim"]:
        for found in re.finditer(r"\s+".join(re.escape(part) for part in phrase.split()), text):
            cover(found.start(), found.end())
    if not context["answerable"]:
        for found in re.finditer(r"(?<![^\W_])" + re.escape(NO_ANSWER_TOKEN) + r"(?![^\W_])", text):
            cover(found.start(), found.end())
    if context["name"] is not None:
        for found in context["name"].finditer(text):
            cover(found.start(), found.end())

    words = [(found.group().casefold(), found.group(), found.start(), found.end()) for found in _WORD.finditer(text)]
    free = [not any(masked[start:end]) for _, _, start, end in words]

    def window(first: int, width: int, commas: frozenset = frozenset()) -> bool:
        """`width` words from `first` on that are still free and stand together as one value does."""
        if not all(free[first:first + width]):
            return False
        for position in range(first + 1, first + width):
            gap = text[words[position - 1][3]:words[position][2]]
            if not (_JUDGE_INSIDE_A_VALUE.fullmatch(gap)
                    or (position - first in commas and _JUDGE_AT_A_COMMA.fullmatch(gap))
                    or (words[position - 1][0] == "dept" and _AFTER_DEPT.fullmatch(gap))):
                return False
        return True

    for phrase in context["fields"]:                           # "high-impact determination" is not a value
        for first in range(len(words) - len(phrase) + 1):
            if window(first, len(phrase)) and tuple(w[0] for w in words[first:first + len(phrase)]) == phrase:
                free[first:first + len(phrase)] = [False] * len(phrase)
    # Every place where a spelling stands, then the longest spelling first (and, among equals, the
    # order of context["spellings"]), each only where its words are still free.
    found_at: list[tuple[int, int, tuple]] = []
    for first, word in enumerate(words):
        for rank, entry in context["by_first_word"].get((False, word[0]), ()) + context["by_first_word"].get((True, word[1]), ()):
            spelling, exact = entry[0], entry[3]
            if tuple(w[1] if exact else w[0] for w in words[first:first + len(spelling)]) == spelling:
                found_at.append((rank, first, entry))
    named: list[tuple[int, str, str]] = []
    for _, first, (spelling, kind, label, exact, commas) in sorted(found_at, key=lambda place: place[:2]):
        width = len(spelling)
        if not window(first, width, commas):
            continue
        free[first:first + width] = [False] * width
        named.append((first, kind, label))
        # Only a value the question vouches for is taken out: its reference, or one it gives.
        if kind == context["kind"] and label == context["expected"]:
            cover(words[first][2], words[first + width - 1][3], 1)
        elif (kind, label) in context["in_question"]:
            cover(words[first][2], words[first + width - 1][3])
        elif quoted_mask != JUDGE_MASK and context["kind"] and kind != context["kind"]:
            # Round 4, where the two masks are told apart: a value of ANOTHER field ("the use case is
            # Deployed" in the reason for an agency question) cannot speak against this field's value.
            cover(words[first][2], words[first + width - 1][3])

    # Round 4: the everyday names of a value, on the words no accepted spelling took (see _everyday_names).
    capitalised, abbreviations, stems = context.get("everyday") or ({}, {}, ())
    for first, (folded, raw, start, end) in enumerate(words):
        if not free[first]:
            continue
        found, width, another_form = None, 1, False
        if raw[:1].isupper() and folded in capitalised:
            found = capitalised[folded]
        elif raw.upper() in abbreviations and (abbreviations[raw.upper()][2] or sum(ch.isupper() for ch in raw) >= 2):
            found = abbreviations[raw.upper()][:2]
        elif context["kind"] == "stage":
            for leading, stem, kind, label in stems:
                last = first + len(leading)
                if (last < len(words) and tuple(w[0] for w in words[first:last]) == leading
                        and words[last][0].startswith(stem) and len(words[last][0]) <= len(stem) + 6
                        and window(first, len(leading) + 1)):
                    found, width, another_form = (kind, label), len(leading) + 1, True
                    break
        if not found:
            continue
        free[first:first + width] = [False] * width
        named.append((first, found[0], found[1]))
        # Another form of a stage word is NAMED, so that it can refuse a verdict, and never taken out:
        # "deployment is planned" is not the value "Deployed".
        if another_form:
            continue
        if found[0] == context["kind"] and found[1] == context["expected"]:
            cover(start, words[first + width - 1][3], 1)
        elif found in context["in_question"]:
            cover(start, words[first + width - 1][3])

    out, position = [], 0
    while position < len(text):
        if masked[position]:
            what = masked[position]
            while position < len(text) and masked[position] == what:
                position += 1
            out.append(JUDGE_MASK if what == 1 else quoted_mask)
        else:
            out.append(text[position])
            position += 1
    return "".join(out), [(kind, label) for _, kind, label in sorted(named)]


# -------------------------------------------------------------------------------------
# Round 4 (the fourth review, reader B, MAJOR 1). The round 3 reader still gave credit to a
# verdict that its own reason took back, in two ways: the other value was written as people
# write it ("Energy", "the State Dept", "piloting", "DoE"), or the mismatch was said in a word
# that is on no list ("is inconsistent with", "discrepancy", "!="). A list of bad words cannot
# be complete. So, where the reader knows the question, the reason of a CORRECT or DECLINED reply
# is now read by ALLOW-LIST, as exact match reads an answer; the lists of bad words were made
# longer for the reply that comes without its question. Every rule below can only REFUSE.
#
# With the question known, verdict CORRECT:
#   1. Everyday names (_everyday_names). A value is also recognised as the one-word name of a
#      "Department of X" agency written with a capital letter ("Energy", "Treasury": exact match
#      refuses these on purpose, so they were in no list), as an abbreviation in another letter
#      case ("DoE", "epa") and, for a stage question, as another form of a stage word
#      ("piloting", "deployment", "retirement"). Another form of a stage word is only NAMED, it
#      is never taken out: "deployment is planned" is not the value "Deployed".
#   2. The allow-list (_untied_statement). Once the reference value, the things the question
#      gives and the safe phrases are taken out, every word of the reason must be in
#      JUDGE_TIE_WORDS or JUDGE_PRO_FORMS or be one of the question's own words. "The candidate
#      says the Pentagon; the reference says EPA.", "The candidate's answer is at odds with the
#      reference." and "The candidate rejects EPA." are refused whatever the other value or the
#      phrase is: "pentagon", "odds" and "rejects" are on no list.
#   3. The tie. A sentence is cut at each mention of the candidate and of the reference. What
#      follows the candidate must hold the reference value, or be made of tie words alone and
#      say that it agrees, or lead straight to the reference. "The reference is Not High-impact;
#      the candidate says it is." is made of list words and is refused by this rule.
#   4. A reason must hold the reference value, a word of agreement (JUDGE_SAYS_IT_MATCHES) or a
#      safe phrase. "It is." holds none.
# With the question known, verdict DECLINED:
#   5. The reply may be made only of JUDGE_REFUSAL_WORDS, the question's own words and quoted
#      things: "declines in part", "nearly declines", "and volunteers the Navy" are refused.
#      Because of that net, the natural ways to say "the documents do not hold it" are now read
#      (JUDGE_SAYS_IT_IS_NOT_THERE); without the question they are not.
# With or without the question:
#   6. Without the question no value is known, so the reader compares what the reply says of the
#      candidate with what it says of the reference (_statements_differ): "The candidate says
#      Energy; the reference says EPA." gives two different things.
#   7. A character outside JUDGE_ALLOWED_PUNCTUATION ("=", "<", ">", "/", "+", "$", an emoji, the
#      not-equal sign) refuses CORRECT and DECLINED.
#   8. Longer lists: JUDGE_MISMATCH_WORDS under CORRECT, JUDGE_ADDS_TO_A_REFUSAL under DECLINED,
#      JUDGE_OUTSIDE_AGAINST for the text around a JSON object. They are kept apart from
#      CONTRADICTS_CORRECT and CONTRADICTS_DECLINED, which stay as rounds 2 and 3 reviewed them.
#   9. An object without a verdict may hold objects, lists and reason-like strings, nothing else
#      ({"match": 0, "grade": {"verdict": "CORRECT"}}), and "Correct: X. Candidate: Y." is a list
#      of labels, not a verdict.
# Read since round 4 where they were lost before (none of them can turn a reply into credit that
# its own words speak against, because everything in them is still read): "**Verdict:** CORRECT";
# a reason with quotation marks that are not escaped or with a raw line break; "says: I cannot
# ..."; and INCORRECT for an answer that declines and then answers ("declines but then names").
# What this still cannot do is in README section 2, item 9.
# -------------------------------------------------------------------------------------

# What replaces a quoted thing that is NOT the reference (the use case name, the question, a
# value the question gives, NO ANSWER) when read_judge asks for the two to be told apart.
JUDGE_QUOTED_MASK = " <quoted> "

# Characters a CORRECT or DECLINED reply may hold besides letters, digits and white space: the
# list exact match uses, brackets and braces, and the ellipsis. An exclamation mark is allowed only
# where it ends a sentence, and a tag such as <thinking> only in the text around the JSON object.
JUDGE_ALLOWED_PUNCTUATION = ALLOWED_PUNCTUATION + "[]{}" + chr(0x2026)
_JUDGE_TAG = re.compile(r"</?(?!value>|quoted>|fine>)[A-Za-z][A-Za-z0-9_-]{0,30}>")
_JUDGE_SENTENCE_BANG = _SENTENCE_BANG

# Words and phrases that say "not the same" and are not in CONTRADICTS_CORRECT. Regular
# expressions on the lower-cased text, applied under CORRECT after the safe phrases are taken out.
# The first three are families: almost every English word that starts with "un", "mis" or "dis"
# takes something back, and the few that do not are spelled out as exceptions.
JUDGE_MISMATCH_WORDS = (
    r"\bun(?!der|it\b|its\b|ite|ique|til\b|ion|ivers|iform)[a-z]{3,}",
    r"\bmis(?!sion|sile)[a-z]{3,}",
    r"\bdis(?!cuss|clos|play|trict|tribut|cover|eas|k\b|ks\b|ast|ab)[a-z]{3,}",
    r"\binconsisten\w*", r"\bincompat\w*", r"\bincomplet\w*", r"\binexact\w*", r"\binvalid\w*", r"\binadequa\w*",
    r"\binsufficien\w*", r"\binappropriat\w*", r"\binapplicab\w*", r"\birrelevan\w*", r"\birreconcil\w*",
    r"\billogical\w*", r"\bimprecis\w*", r"\bimproper\w*", r"\bimperfect\w*", r"\bimplausib\w*", r"\bimpossib\w*",
    r"\bincoheren\w*", r"\bincongru\w*", r"\bindirect\w*", r"\binconclusive\w*", r"\berroneous\w*", r"\bflaw\w*",
    r"\bdeviat\w*", r"\bdiverg\w*", r"\bdepart(?:s|ed|ing|ure|ures)?\b", r"\bvar(?:y|ies|ied|ying|iation\w*|iance|iant\w*)\b",
    r"\bstray\w*", r"\boppos\w*", r"\bcontrar\w*", r"\brevers\w*", r"\bnegat\w*", r"\binvert\w*", r"\binvers\w*",
    r"\bcounter\w*", r"\bversus\b", r"\bvs\b", r"\bat odds\b", r"\bclash\w*", r"\bcollid\w*", r"\bcontrast\w*",
    r"\bgap\w*", r"\btension\w*", r"\bdrift\w*", r"\brift\w*",
    r"\b(?:go|goes|going|went|run|runs|running|ran|speak|speaks|argue|argues|count|counts)\s+against\b",
    r"\b(?:fall|falls|fell|falling|stop|stops|come|comes)\s+short\b", r"\bshortfall\w*", r"\bshortcoming\w*",
    r"\b(?:leave|leaves|left|leaving)\s+out\b", r"\bdrop\w*", r"\bskip\w*", r"\btruncat\w*", r"\bhalf\b",
    r"\bfar\s+(?:cry|from|off|away|removed)\b", r"\bnowhere\b", r"\bhardly\b", r"\bbarely\b", r"\bscarcely\b",
    r"\brarely\b", r"\bseldom\b", r"\balmost\b", r"\bnearly\b", r"\broughly\b", r"\bapproximat\w*", r"\bsomewhat\b",
    r"\bloosely\b", r"\bvague\w*", r"\bambiguous\w*", r"\bsimilar\w*", r"\bresembl\w*", r"\blittle\b", r"\bless\b",
    r"\bbeyond\b", r"\bthan\b", r"\bearlier\b", r"\blater\b", r"\bformer\w*", r"\bprevious\w*", r"\boutdated\b",
    r"\bhallucinat\w*", r"\bfabricat\w*", r"\binvent(?!or)\w*", r"\bmade up\b", r"\b(?:make|makes|making) up\b",
    r"\bspurious\b", r"\bbogus\b", r"\bfictitious\b", r"\bconfus\w*", r"\bmix(?:es|ed|ing)?\s+up\b", r"\bswap\w*",
    r"\bsubstitut\w*", r"\breplac\w*", r"\balter\w*", r"\bquestionabl\w*", r"\bdubious\w*", r"\bsuspect\w*",
    r"\bproblem\w*", r"\bhmm+\b",
    # something more than the reference: "EPA, plus the Navy."
    r"\bplus\b", r"\bas well\b", r"\bin addition\b", r"\badditional\w*", r"\bmoreover\b", r"\bfurthermore\b",
    # a line of labels that says no: "MATCH: N", "same = 0"
    r"[:=]\s*(?:n|0)\b(?!\s*[a-z0-9])",
)

# Under DECLINED: the reply says the candidate did something more than decline, or gives a figure.
JUDGE_ADDS_TO_A_REFUSAL = (
    r"\badds?\b(?!\s+(?:no|nothing|none)\b)", r"\badded\b", r"\badding\b", r"\badditional\w*", r"\banother\b",
    r"\bother\b", r"\bsimilar\w*",
    r"\bpossibl\w*", r"\bpotential\w*", r"\bperhaps\b", r"\bmaybe\b", r"\bprobabl\w*", r"\blikely\b", r"\bsuggest\w*",
    r"\bpropos\w*", r"\bestimat\w*", r"\bspeculat\w*", r"\bidentif\w*", r"\bmention\w*", r"\bpoints?\s+to\b",
    r"\boffer(?:s|ed|ing)?\s+(?!no\b|none\b|nothing\b)", r"\bbeyond\b", r"\bbesides\b", r"\bexcept\w*", r"\bapart\b",
    r"\baside\b", r"\bplus\b", r"\bmillion\w*", r"\bbillion\w*", r"\bthousand\w*", r"\d",
    # "declines and <does something>": after the refusal only a few continuations say nothing new
    r"\b(?:declin\w*|refus\w*|cannot\s+answer|can\s+not\s+answer|unable\s+to\s+answer)\b[^.;:]{0,200}?[,\s](?:and|then)\s+"
    r"(?!then\b)(?!(?:gives?|offers?|provides?|states?|names?|has|adds?|makes?)\s+(?:no|nothing|none)\b)"
    r"(?!(?:does|did|do)\s+not\b)(?!(?:says?|states?)\s+(?:that\s+)?it\s+(?:cannot|can\s+not|has\s+no)\b)"
    r"(?!(?:the\s+)?reference\b)(?!so\b)(?!no\b)(?!nothing\b)(?!that\b)(?!this\b)(?!declin)(?!refus)\w+",
    r"\b(?:declin\w*|refus\w*)\s+(?:nothing|none|no\b)",
    r"\black\w*\s+(?:(?:a|an|any|the)\s+)?(?:declin\w*|refus\w*)",
    # "No information that it declines.", "no sign that the candidate refused"
    r"\b(?:no|not|never)\s+(?:\w+\s+){0,3}?that\s+(?:it|the\s+candidate|candidate)\s+(?:declin|refus)\w*",
)

# Round 4. The words a DECLINED reply may be made of when the question is known, besides the
# question's own words and quoted things. Any other word refuses the verdict. The lists above
# still apply ("names", "gives" followed by a thing, "but", "then" ...).
JUDGE_REFUSAL_WORDS = frozenset("""
    the a an its is are was be been does did do has have it i they there this that these
    candidate candidate's reference answer answers answered answering response reply question
    cannot can not no none nothing never unable any anything
    declines declined declining decline refuses refused refusing refusal abstains abstained abstaining
    says said say states stated state indicates indicated indicate acknowledges acknowledged explains explained
    notes noted reports reported writes wrote written replies replied responds responded
    give gives given giving provide provides provided providing name offer offers
    know knows determine determined find found tell
    information available contain contains hold holds cover covers include includes lack lacks lacking
    missing absent silent
    documents document passages passage inventory record records recorded data source sources
    from in on of for to by with about at and so as when because since which
    without appropriately correctly properly rightly expected behavior behaviour
    agency stage determination budget figure value number amount field fact facts
    verdict reason grade gets
    incorrect contradicting contradiction contradictions adds
    """.split())
# Round 5 (fifth review, reader B, F5): words of ordinary refusals that were lost ("explicitly declines", "uses the
# refusal sentence", "cannot answer based on the documents", "which is appropriate"). They are let in only because
# the rules of the block "Round 5" below read what a sentence says of the candidate.
JUDGE_REFUSAL_WORDS |= frozenset("appropriate explicitly stating uses used using sentence based exact".split())

# Round 4, with the question known only (there JUDGE_REFUSAL_WORDS refuses every word that is not a word
# of a refusal, so these can be read without opening a door): the natural ways to say "the candidate said
# the documents do not hold it". They count like SAYS_DECLINED, and "says" or "states" may be followed by them.
JUDGE_SAYS_IT_IS_NOT_THERE = (
    r"\bnot available\b", r"\bnot in the (?:documents?|passages?|inventory|records?)\b", r"\bnot record\w*",
    r"\bnot listed\b", r"\black(?:s|ing)?\b", r"\bcontains? no\b", r"\bthere is no\b", r"\bsilent\b",
    r"\boffers? no\b", r"\bno \w+ (?:is|are|was) (?:recorded|given|available|provided|listed)\b",
)
_SAYS_IT_IS_NOT_THERE = (
    r"(?!\s+(?:with\s+)?(?:(?:a|an|the|its)\s+)?(?:(?:exact|fixed|standard|expected|plain)\s+)?(?:refusal|decline)\b)"
    r"(?!\s+(?:that\s+)?the\s+(?:documents?|passages?|inventory|information|answer|records?|data)\s+"
    r"(?:lacks?|(?:contains?|holds?|has|have|gives?|records?|includes?)\s+no|(?:is|are|was|were)\s+silent)\b)"
    r"(?!\s+(?:that\s+)?the\s+\w+\s+(?:is|are|was)\s+not\s+(?:recorded|available|given|provided|listed|known|stated|in)\b)"
)
CONTRADICTS_DECLINED_WITH_THE_QUESTION = tuple(
    pattern + _SAYS_IT_IS_NOT_THERE if pattern == _SAYS + _SAYS_IT_CANNOT else pattern for pattern in CONTRADICTS_DECLINED)

# Under INCORRECT: the reply says the candidate declined AND went on to answer.
JUDGE_WENT_ON_TO_ANSWER = (
    r"\bthen\b", r"\bstill\b", r"\banyway\b", r"\bafter\s+(?:declin\w*|refus\w*)", r"\binitially\b", r"\bat first\b",
    r"\bhedg\w*",
)

# In the text AROUND a JSON object or a verdict line (never in the reason): the reply shows a
# format or an example, it does not give a verdict. 'Expected output for a matching answer: {...}'
JUDGE_OUTSIDE_AGAINST = (
    r"\bexpected\b", r"\bexample\w*", r"\bsample\b", r"\bformat\w*", r"\btemplate\w*", r"\bfor an?\b", r"\bsuch as\b",
    r"\bwhen\b",
)

# The words a CORRECT reply's reason may be made of when the question is known (besides the reference
# value, quoted things, safe phrases, the question's own words and JUDGE_PRO_FORMS): articles and forms
# of "be", "do" and "have"; nouns for the answer and the field; verbs of saying; words of agreement;
# connectives. Directly after "the candidate", where the value does not stand, ONLY these may stand:
# no pronoun that can stand for a value ("it", "yes", "one") is in here.
JUDGE_TIE_WORDS = frozenset("""
    the a an its is are was be been does did do has have
    answer answers answered response reply output statement wording text value values
    agency stage determination status field name use case fact facts development
    reporting reported recorded federal ai inventory question asked passage passages document documents
    source sources supported grounded
    says said say states stated state stating gives gave give given giving names named naming
    identifies identified identifying provides provided reports lists listed repeats repeated
    restates restated reproduces quotes quoted cites cited writes wrote written conveys conveyed
    mentions mentioned contains contain aligns aligned align refers refer abbreviates
    adds added adding includes included including abbreviation abbreviated acronym full form forms spelled out
    i e ie compared checked
    matches match matched matching agrees agree agreeing agreement equals equal same identical identically
    exact exactly precisely verbatim correct correctly right rightly accurate accurately consistent
    consistently equivalent properly faithfully factually fully completely entirely perfectly clearly
    both and as with to in by for of on from which that what so thus therefore word words per just here too also
    probably records record
    """.split())
# ... and the words of the field names ("classification", "designation"), but not "high" and "impact". Those two
# still reach a reason through JUDGE_PRO_FORMS and a high-impact question's own words, so until round 5 "The
# candidate matches the reference. The impact is high." was read as CORRECT. Since round 5 a word of a stage or
# high-impact value that stands outside the reference value and outside a field name refuses CORRECT (round 5
# block, _loose_value_words), in every kind of question.
JUDGE_TIE_WORDS |= frozenset(word for phrases in list(FIELD_NAME_PHRASES.values()) + list(JUDGE_FIELD_NAME_PHRASES.values())
                             for phrase in phrases for word in phrase.split()) - {"high", "impact"}
JUDGE_AGREEMENT_WORDS = frozenset("""
    matches match matched matching agrees agree agreeing agreement equals equal same identical identically
    exact exactly precisely verbatim correct correctly right rightly accurate accurately consistent
    consistently equivalent faithfully so
    """.split())

# Allowed next to the candidate only when the reference value stands there too: pronouns, and the words
# exact match allows around a value (a judge that quotes a right answer quotes these).
JUDGE_PRO_FORMS = frozenset("it this that these there one yes ok okay".split()) | frozenset(
    word for phrases in FILLER_PHRASES.values() for phrase in phrases for word in _WORD.findall(phrase))
# Allowed only in the text around a JSON object: "Here is my grading:", "End of grade."
JUDGE_LEAD_IN_WORDS = frozenset("""
    here my grading grade graded verdict assessment evaluation result results json object final below following
    requested end note reason reasoning explanation rationale sure thinking
    """.split())
# A CORRECT reply that gives a reason must hold the reference value or one of these (round 4).
JUDGE_SAYS_IT_MATCHES = JUDGE_AGREEMENT_WORDS - {"so"} | {"reference", "yes", "ok", "okay"}

_JUDGE_SENTENCE = re.compile(r"[.;!?]+(?=\s|$|[\"')\]])")
# "the reference", "the reference answer", "the expected answer", "the correct agency" ...
_JUDGE_SUBJECT = re.compile(
    r"\b(?:(?P<reference>reference(?:'s)?(?:\s+(?:answer|value))?"
    r"|(?:expected|correct|right|gold|true)\s+(?:answer|value|agency|stage|determination)|expected)"
    r"|(?P<candidate>candidate(?:'s)?(?:\s+(?:answer|response|reply|output))?"
    r"|(?<!an )(?<!any )(?<!no )(?<!to )(?<!same )(?<!not )(?:answer|response|reply|output|submission)))\b")
_SUBJECT_WORDS = frozenset("candidate candidate's reference reference's expected gold true response reply output "
                           "submission".split())
_VALUE_TOKEN = JUDGE_MASK.strip()
_QUOTED_TOKEN = JUDGE_QUOTED_MASK.strip()
# What a safe phrase ("no contradicting facts", "is not wrong", "does not decline") is replaced by
# before the tie rule reads the text: it says nothing against the verdict, and it is not a value.
_FINE_TOKEN = "<fine>"
_TIE_WORD = re.compile(r"<value>|<quoted>|<fine>|[^\W_]+(?:'[^\W_]+)*")


def _untied_statement(text: str, own_words: frozenset = frozenset(), around: bool = False) -> str:
    """The first thing in a CORRECT reply's text that is not tied to the reference value, or "".

    text: lower-cased; the reference value replaced by "<value>", every other quoted thing by
    "<quoted>", every safe phrase by "<fine>". own_words: the words of the question and of the use
    case name, which a judge may repeat one by one ("the chatbot pilot"). around: the text is what
    stands around the JSON object ("Here is my grading:"), where JUDGE_LEAD_IN_WORDS are allowed too.
      * Every word must be a tie word, a pronoun (JUDGE_PRO_FORMS), one of the question's own words,
        or stand for a value, a quoted thing or a safe phrase. "It is the navy, which matches." and
        "The candidate rejects <value>." are refused: "navy" and "rejects" are on no list.
      * Each sentence is cut at each mention of the candidate and of the reference. What follows the
        candidate and does NOT hold the reference value must be made of tie words only (no pronoun,
        none of the question's words) and must either hold a word of agreement or lead straight to,
        or come straight from, the reference ("states the reference answer"; "the reference is
        <value>, and the candidate says so"). "The reference is <value>; the candidate says it is."
        is refused.
    """
    def loose(word: str) -> bool:
        return (word in JUDGE_TIE_WORDS or word in JUDGE_PRO_FORMS or word in _SUBJECT_WORDS or word in own_words
                or word in (_VALUE_TOKEN, _QUOTED_TOKEN, _FINE_TOKEN) or (around and word in JUDGE_LEAD_IN_WORDS))

    for sentence in _JUDGE_SENTENCE.split(text):
        # "NOAA is part of <value>": a bureau of the reference agency, read as the agency
        sentence = _PART_OF_THE_REFERENCE.sub(" " + _VALUE_TOKEN, sentence)
        unknown = [word for word in _TIE_WORD.findall(sentence) if not loose(word)]
        if unknown:
            return "words on no list: " + " ".join(dict.fromkeys(unknown))
        subjects = list(_JUDGE_SUBJECT.finditer(sentence))
        for position, subject in enumerate(subjects):
            if not subject.group("candidate"):
                continue
            following = subjects[position + 1] if position + 1 < len(subjects) else None
            earlier = subjects[position - 1] if position else None
            said = _TIE_WORD.findall(sentence[subject.end():following.start() if following else len(sentence)])
            if _VALUE_TOKEN in said:
                continue                                       # the candidate's statement holds the reference value
            if not said and not following and sentence[:subject.start()].strip() == "":
                continue                                       # "Answer:" in front of the JSON object: a label
            shown = " ".join([subject.group()] + said).strip()
            if any(word not in JUDGE_TIE_WORDS and word != _FINE_TOKEN for word in said):
                return shown
            if any(word in JUDGE_AGREEMENT_WORDS or word == _FINE_TOKEN for word in said):
                continue                                       # "the candidate is correct", "... gives the right agency"
            # what stands before it, back to the last comma: "the reference is <value>, and the candidate says so"
            before = _TIE_WORD.findall(sentence[earlier.end() if earlier else 0:subject.start()].rsplit(",", 1)[-1])
            around_is_plain = all(word in JUDGE_TIE_WORDS or word in (_VALUE_TOKEN, _FINE_TOKEN) for word in before)
            to_the_reference = bool(following and following.group("reference"))
            from_the_reference = bool(earlier and earlier.group("reference"))
            if around_is_plain and (to_the_reference or from_the_reference or _VALUE_TOKEN in before):
                continue                                       # "the candidate states the reference answer"
            return shown
    return ""


_PART_OF_THE_REFERENCE = re.compile(
    r"(?<![^\W_])[^\W_]+\s+is\s+(?:an?\s+|the\s+)?(?:part|bureau|component|division|office|unit|branch|sub-?agency)"
    r"\s+of\s+(?:the\s+)?<value>")

_SAYING = (r"(?:says?|said|states?|stated|gives?|gave|is|was|are|names?|named|reports?|reported|answers|answered|"
           r"identifies|identified|provides?|provided|claims?|claimed|writes|wrote|lists?|listed|has|reads?|shows?)")
_STATEMENT = (r"(?:'s)?(?:\s+(?:answer|response|reply|output|stage|agency|value|determination))?\s*"
              r"(?::|=|\b" + _SAYING + r"\b(?:\s+with\b)?)\s*(?:that\s+)?(?P<object>[^.;:,\n]*)")
_CANDIDATE_STATEMENT = re.compile(r"\bcandidate" + _STATEMENT, re.IGNORECASE)
_REFERENCE_STATEMENT = re.compile(r"\breference" + _STATEMENT, re.IGNORECASE)
_OBJECT_ENDS = re.compile(r"\s+(?:and|while|whereas|but|which|when|though|although|so)\b.*$", re.IGNORECASE)
_OBJECT_LEAD = frozenset("the a an it is its this that as to be".split())
_IN_BRACKETS = re.compile(r"^(?P<first>[^()]+?)\s*\((?P<second>[^()]+)\)$")


def _statements_differ(text: str) -> str:
    """Without the question: "candidate says X ... reference says Y" where X and Y are not the same words.

    text: as the judge wrote it, not lower-cased. Returns the two objects for the note, or "". An
    object made only of tie words in lower case ("correct", "the same agency"), or one that speaks of
    the other side ("the reference answer"), states no value and is not compared. "X (Y)" is the same
    as "X" and as "Y" ("Environmental Protection Agency (EPA)" and "EPA"); nothing else is.
    """
    def objects(pattern) -> list[tuple[str, ...]]:
        found = []
        for match in pattern.finditer(text):
            words = _WORD.findall(_OBJECT_ENDS.sub("", match.group("object")))
            while words and words[0].lower() in _OBJECT_LEAD:
                words = words[1:]
            lowered = tuple(word.lower() for word in words)
            if "reference" in lowered or "candidate" in lowered:
                continue
            if words and any(word.lower() not in JUDGE_TIE_WORDS or word[:1].isupper() for word in words):
                raw = " ".join(_OBJECT_ENDS.sub("", match.group("object")).lower().split())
                forms = {lowered}
                bracketed = _IN_BRACKETS.match(raw.strip(" \"'`*"))
                if bracketed:
                    for part in (bracketed.group("first"), bracketed.group("second")):
                        part_words = [word for word in _WORD.findall(part)]
                        while part_words and part_words[0] in _OBJECT_LEAD:
                            part_words = part_words[1:]
                        forms.add(tuple(part_words))
                found.append(forms)
        return found

    said, wanted = objects(_CANDIDATE_STATEMENT), objects(_REFERENCE_STATEMENT)
    if not said or not wanted:
        return ""
    for candidate in said:
        if not any(candidate & reference for reference in wanted):
            return (f"{' '.join(max(candidate, key=len))!r} of the candidate and "
                    f"{' '.join(max(wanted[0], key=len))!r} of the reference")
    return ""


# -------------------------------------------------------------------------------------
# Round 5 (the fifth review, reader B). Two holes of the round 4 allow-lists, closed by reading what each
# sentence SAYS, with the question known (the lists alone cannot tell "the candidate reports that the
# passages contain no budget figure" from "the candidate reports the budget figure"):
#
# F1, DECLINED. JUDGE_REFUSAL_WORDS holds "contains", "includes", "reports", "found", "budget", "figure",
# "agency", because a refusal is described with them. So "The candidate's answer contains a budget figure that
# the documents lack." was made of list words, and "lack" counted as saying that the candidate declined: credit,
# 16 of 16 such replies. Now (_not_a_refusal):
#   1. Where the candidate, its answer, response or reply is the subject of a clause, the clause must be a
#      refusal (_REFUSAL_CLAUSE): declines, refuses, abstains; cannot answer, is unable to; does not answer,
#      give, provide ...; gives, has, offers ... no answer; uses or is the refusal sentence; or says, states,
#      notes, explains, reports ... (that) it cannot answer, or that the documents, the budget or the answer
#      are not there. "contains a budget figure", "reports the budget amount", "is an agency" and "explains the
#      budget figure, which is not in the documents" are not. Every later part of the sentence after a comma
#      or an "and" that starts with a verb belongs to the subject named last and is read the same way (after a
#      refusal it may also be a negation: "and is not sure"), and so is a "which" clause right after it.
#   2. "it", "they", "this", "the answer" and "the candidate's refusal" as a subject may decline, say that
#      something is not there, or be "the expected behaviour"; anything else with a verb ("it has a budget
#      figure") is refused, and so is "it" or "the candidate" before a verb that gives ("the figure it found").
#   3. A passive or a "there is" that gives something ("a budget figure is given", "the agency is in the
#      answer", "there is a figure in the answer", "with a budget figure") is refused unless a negation or a
#      refusal stands before it in its clause; "the candidate's figure", "the figure from the candidate" and
#      "declines: budget figure" always.
#   4. Every sentence must say something negative (a refusal, "no", "not", "lacks" ...) or be a plain one
#      such as "This is the expected behaviour." or "Reference is NO ANSWER.".
#   5. "The documents lack it" in the judge's own words no longer counts as saying that the candidate declined
#      (JUDGE_SAYS_IT_IS_NOT_THERE); it counts where the candidate is said to say it (rule 1).
# With these rules in place, ordinary refusals that were lost are read (F5): JUDGE_REFUSAL_WORDS took 9 more
# words, and "which is correct", "this is appropriate" after a refusal are no longer read against it.
#
# F2, CORRECT. "The candidate matches the reference. The impact is high." was CORRECT for the reference "Not
# High-impact": "high" and "impact" are in JUDGE_PRO_FORMS and in the question, and the second sentence says
# nothing of the candidate, so the tie rule never read it. Now a word of a stage or high-impact value
# (_value_words: "high", "impact", "presumed", "pilot", "deployed", "retired", "pre", "deployment", and
# "development") refuses CORRECT wherever it stands outside the reference value and outside a field name
# ("stage of development", "high-impact determination"), in every kind of question.
#
# What these rules still cannot do is in README section 2, item 9. They only refuse; none of them is applied
# without the question.
# -------------------------------------------------------------------------------------

_R5_SAYING = (r"(?:says?|said|states?|stated|stating|indicates?|indicated|acknowledges?|acknowledged|explains?|"
              r"explained|notes?|noted|reports?|reported|writes?|wrote|replies|replied|responds?|responded|tells?|"
              r"answers?|answered)")
_R5_HOLDERS = r"(?:documents?|passages?|inventory|records?|data|sources?|information|context|text)"
_R5_NOT_THERE = (
    r"(?:(?:it|they|i)\s+(?:cannot|can\s+not|could\s+not|(?:is|are|was|am)\s+(?:unable|not\s+able)|"
    r"(?:does|do|did)\s+not|(?:has|have)\s+no|lacks?|knows?\s+no)\b"
    r"|(?:(?:the|its|these|those)\s+)?(?:(?:provided|given|inventory|source|retrieved)\s+)?" + _R5_HOLDERS
    + r"(?:\s+(?:provided|given))?\s+(?:(?:do|does|did)\s+not|lacks?|lacking|(?:contains?|holds?|has|have|gives?|"
      r"provides?|includes?|records?|covers?|offers?)\s+no|(?:is|are|was|were)\s+(?:silent|not))\b"
    r"|(?:(?:the|a|an|its|this|that|any)\s+)?(?:(?:budget|agency|stage|annual)\s+)?(?:budget|figure|value|amount|"
    r"number|agency|stage|determination|information|answer|data|it|this|that)\s+(?:is|are|was|were)\s+"
    r"(?:not\s+(?:available|in|recorded|listed|given|provided|known|stated|found|contained|present|there|included|"
    r"specified|reported|mentioned|covered|held)|unavailable|absent|missing)\b"
    r"|there\s+(?:is|are|was|were)\s+no\b"
    r"|no\s+(?:[^\W_]+\s+){0,2}(?:is|are|was|were)\s+(?:recorded|given|available|provided|listed|in|reported|stated|"
    r"found|known|included|contained)\b"
    r"|nothing\s+(?:is|was)\b"
    r"|[\"'`]?\s*i\s+(?:cannot|can\s+not|do\s+not|am\s+unable|have\s+no)\b)"
)
# A clause whose subject is the candidate and that says it declined (rule 1). Matched at the clause's start.
_REFUSAL_CLAUSE = re.compile(
    r"(?:(?:has|have|had|is|was)\s+)?(?:declin|refus|abstain)\w*"
    r"|(?:cannot|can\s+not|could\s+not|(?:is|was)\s+(?:unable|not\s+able)|unable)\b"
    r"|(?:does|did|do|has|have|had)\s+not\s+(?:answer|provide|give|offer|name|know|determine|find|tell|state|say|"
    r"include|contain|hold|have|report|indicate)\w*"
    r"|(?:has|have|had|gives?|gave|provides?|provided|offers?|offered|states?|stated|names?|named|contains?|holds?|"
    r"includes?|knows?|reports?|indicates?|gets?)\s+(?:no|none|nothing)\b"
    r"|(?:uses?|used|using|is|was|gives?|states?|says?|writes?|wrote|provides?|offers?|returns?|repeats?|"
    r"(?:answers?|answered|replies|replied|responds?|responded)\s+with|consists\s+of|contains?|holds?|includes?)\s+"
    r"(?:(?:a|an|the|its)\s+)?(?:(?:exact|fixed|standard|expected|prescribed|required|plain|clean|full)\s+)?"
    r"(?:refusal|decline)\b(?!\s+(?:sentence\s+)?(?:with|and|plus|about|for|along|followed|then|but|of)\b)"
    r"|lacks?\s+(?:(?:the|any)\s+)?(?:information|data|answer|knowledge)\b"
    r"|" + _R5_SAYING + r"\s*(?:that\s+|:\s*)?" + _R5_NOT_THERE)
# What "it", "they", "this" or "the answer" may be said to be or do besides declining (rule 2).
_NEGATIVE_CLAUSE = re.compile(
    r"(?:is|are|was|were)\s+(?:not|nowhere|absent|missing|unavailable|silent)\b"
    r"|(?:does|do|did|has|have|had|could|can)\s*not\b|cannot\b|lacks?\b|lacking\b"
    r"|(?:has|have|had|holds?|contains?|gives?|provides?|offers?|includes?|records?|lists?|covers?|adds?|states?|"
    r"names?)\s+(?:no|nothing)\b")
_PLAIN_CLAUSE = re.compile(r"(?:is|was)\s+(?:(?:the|what\s+is)\s+)?(?:expected|appropriate|correct|right|proper)\b"
                           r"|(?:is|was)\s+<quoted>\s*$")
_R5_CLAUSE_LOOK = 400                         # characters of a clause the rules need to read
_R5_ADVERBS = frozenset("correctly appropriately properly rightly explicitly".split())
_R5_VERBS = frozenset("""
    is are was were be been does did do has have had can cannot could gets uses used using adds
    answer answers answered answering declines declined declining decline refuses refused refusing refuse
    abstains abstained abstaining abstain
    says said say states stated state stating indicates indicated indicate acknowledges acknowledged explains
    explained notes noted reports reported writes wrote replies replied responds responded tells tell
    give gives gave giving provide provides provided providing name names named offer offers offered
    know knows determine determines determined find finds found contain contains hold holds cover covers
    include includes lack lacks lacking
    """.split())
# The candidate as the subject of a clause, and the words that may stand for it (rules 1 and 2).
_R5_CANDIDATE = re.compile(r"(?:\b(?:the|a|this)\s+)?\bcandidate(?:'s)?(?:\s+(?:answer|response|reply|output))?(?![^\W_])"
                           r"|\b(?:the|its|this|their)\s+(?:response|reply|output|submission)\b|\bits\s+answer\b")
_R5_STANDS_FOR = re.compile(r"\b(?:it|they|this|(?:the|this)\s+answer|(?:the\s+)?candidate's\s+(?:refusal|decline|declining))\b")
# What may stand right before the subject of a clause: nothing, a mark, or one of these words.
_R5_CLAUSE_MARKS = ",:(-\u2013\u2014\"'`*"
_R5_CLAUSE_WORDS = frozenset("""and so because since as when while whereas but though although then that which if thus
                                therefore hence where after before once whether""".split())


def _starts_a_clause(before: str) -> bool:
    """Whether a subject that follows this text starts a clause ("the candidate says ..."), or is an object."""
    before = before.rstrip()
    return not before or before[-1] in _R5_CLAUSE_MARKS or before.rsplit(None, 1)[-1] in _R5_CLAUSE_WORDS
_R5_PARTS = re.compile(r"\s*,\s*|\s+and\s+")
# Rule 3.
_R5_GIVEN = re.compile(
    r"\b(?:is|are|was|were|been)\s+(?:given|stated|provided|reported|named|indicated|found|determined|included|"
    r"contained|offered|written|noted|explained|acknowledged|recorded|listed|available|known|held|covered|answered|"
    r"in\s+(?:the\s+|its\s+)?(?:candidate's\s+)?(?:answer|response|reply|output))\b"
    r"|\bthere\s+(?:is|are|was|were)\s+(?!no\b|not\b|nothing\b|none\b|never\b)"
    r"|\b(?:budget|figure|value|amount|number|agency|stage|determination)\s+(?:(?:given|stated|provided|reported|"
    r"named|offered|written)\s+)?(?:of|from|by|in)\s+(?:the\s+)?(?:candidate|answer|response|reply)\b"
    r"|\b(?:is|was|are|were)\s+(?:the|its|their)\s+(?:candidate's\s+)?(?:answer|response|reply)\b"
    r"|\b(?:with|plus)\s+(?:(?:a|an|the|its|one)\s+)?(?:(?:budget|annual)\s+)?(?:budget|figure|value|amount|number|"
    r"agency|stage|determination)\b")
# "the budget figure it found", "the agency they give": a word for the candidate and a verb that gives (rule 2).
_R5_IT_GIVES = re.compile(
    r"\b(?:(?:it|they)\s+(?:found|finds|determined|determines|gave|gives|provides|provided|names|named|reports|reported|"
    r"includes|included|contains|holds|has|have|offers|offered|states|stated|indicates|indicated|acknowledges|"
    r"acknowledged|explains|explained|notes|noted|knows|knew)"
    r"|candidate\s+(?:found|finds|determined|determines|gave|gives|provides|provided|names|named|includes|included|"
    r"contains|holds|has|have|offers|offered|knows|knew))\b"
    r"(?!\s+(?:no|nothing|none|not|that|there|it\s+(?:cannot|can\s+not|has\s+no|does\s+not)|"
    r"(?:the\s+)?(?:documents?|passages?|inventory|records?|data|sources?|information)\s+(?:do|does|did|is|are|was|"
    r"lacks?|contains?\s+no|holds?\s+no|has\s+no|have\s+no))\b)")
_R5_OWNS_A_VALUE = re.compile(r"\bcandidate's\s+(?:budget|figure|value|amount|number|agency|stage|determination)\b"
                               r"|:\s*(?:(?:a|an|the|its)\s+)?(?:budget|figure|value|amount|number|agency|stage|"
                               r"determination)\b")      # "declines: budget figure"
_R5_NEGATION = re.compile(r"\b(?:no|not|none|nothing|never|without|cannot|unable|declin\w*|refus\w*|abstain\w*|"
                          r"lack\w*|silent|missing|absent)\b")
# Rule 4.
_R5_SAYS_SOMETHING_NEGATIVE = re.compile(
    r"\b(?:no|not|none|nothing|never|without|cannot|unable|declin\w*|refus\w*|abstain\w*|lack\w*|missing|absent|"
    r"silent|unavailable)\b")
_R5_PLAIN_WORDS = frozenset("""
    this that it is was which the a an as expected behavior behaviour appropriate appropriately properly rightly
    correctly reference reference's verdict grade gets so response reply here
    """.split()) | {JUDGE_QUOTED_MASK.strip(), JUDGE_MASK.strip()}
# Under DECLINED with the question known: "which is correct" after a refusal is not read against it (F5).
JUDGE_SAFE_UNDER_DECLINED_WITH_THE_QUESTION = (
    r"\b(?:which|this|that)\s+is\s+(?:(?:the|what\s+is)\s+)?(?:correct|right|appropriate|expected|proper)\b"
    r"(?!\s+(?:answer|agency|stage|value|figure|amount|number|determination|budget)\b)",
)
# "does not use the refusal sentence", "did not give a refusal": the candidate did NOT decline (rule 1 reads
# "does not ..." as a refusal, so these are refused first).
JUDGE_NOT_A_REFUSAL = (
    r"\bnot\s+(?:use|give|offer|provide|contain|include|state|say|write|repeat|issue|make|return)\w*\s+"
    r"(?:(?:a|an|any|the|its)\s+)?(?:[^\W_]+\s+)?(?:declin\w*|refus\w*)",
)


def _not_a_refusal(text: str, around: bool = False) -> tuple[str, bool]:
    """(what in a DECLINED reply is not a refusal, or "", whether the candidate is said to decline).

    text: lower-cased, quoted things replaced, the safe phrases taken out. around: the text around the JSON
    object, where JUDGE_LEAD_IN_WORDS may make a plain sentence. See the block comment above. One pass over the
    parts of each sentence (cut at commas and "and"): a part that starts with a verb belongs to the subject named
    last before it, so the time grows with the length of the reply, not with its square.
    """
    declined = False
    plain_words = _R5_PLAIN_WORDS | (JUDGE_LEAD_IN_WORDS if around else frozenset())

    def first_words(part: str) -> str:
        words = part[:_R5_CLAUSE_LOOK].split()            # every rule is matched at the start of the clause
        while words and words[0] in _R5_ADVERBS:
            words = words[1:]
        return " ".join(words)

    def not_a_refusal(subject: list, clause: str) -> bool:
        """subject: [of the candidate, its words, refused in this clause already]. Reads one clause of it."""
        nonlocal declined
        if not clause or clause.split()[0] not in _R5_VERBS:
            return False                                       # not a verb: an object, an aside, another subject
        if _REFUSAL_CLAUSE.match(clause):
            declined = declined or subject[0]
            subject[2] = True
            return False
        if (subject[2] or not subject[0]) and _NEGATIVE_CLAUSE.match(clause):
            return False                                       # "declines, and is not sure"; "it is not recorded"
        return subject[0] or not _PLAIN_CLAUSE.match(clause)

    def shown(subject: list, clause: str) -> str:
        return (("what it says of the candidate is not a refusal: " if subject[0]
                 else "what it says of " + subject[1] + " is not a refusal: ") + (subject[1] + " " + clause).strip()[:60])

    for sentence in _JUDGE_SENTENCE.split(text):
        sentence = sentence.strip()
        if not _TIE_WORD.search(sentence):
            continue
        owned = _R5_OWNS_A_VALUE.search(sentence)
        if owned:
            return "the candidate's own value: " + owned.group(), declined
        for part in _R5_PARTS.split(sentence):
            for given in _R5_GIVEN.finditer(part):
                if not _R5_NEGATION.search(part[:given.start()]):   # "no answer was given", "the refusal is given"
                    return "something is given: " + part.strip()[:60], declined
        gives = _R5_IT_GIVES.search(sentence)
        if gives:
            return "it is said to give something: " + gives.group()[:60], declined
        if (not _R5_SAYS_SOMETHING_NEGATIVE.search(sentence)
                and not all(word in plain_words for word in _TIE_WORD.findall(sentence))):
            return "a sentence that says nothing of a refusal: " + sentence[:60], declined
        mentions = sorted((found.start(), found.end(), of_the_candidate, found.group())
                          for pattern, of_the_candidate in ((_R5_CANDIDATE, True), (_R5_STANDS_FOR, False))
                          for found in pattern.finditer(sentence)
                          if _starts_a_clause(sentence[max(0, found.start() - 80):found.start()]))
        spans, position = [], 0
        for cut in _R5_PARTS.finditer(sentence):
            spans.append((position, cut.start()))
            position = cut.end()
        spans.append((position, len(sentence)))
        subject, after_a_bare_subject, next_mention = None, False, 0
        for part_start, part_end in spans:
            own = []
            while next_mention < len(mentions) and mentions[next_mention][0] < part_end:
                if mentions[next_mention][0] >= part_start:
                    own.append(mentions[next_mention])
                next_mention += 1
            if own:                                            # this part names a subject: read what follows it
                for _, mention_end, of_the_candidate, words in own:
                    rest = sentence[mention_end:min(part_end, mention_end + _R5_CLAUSE_LOOK)]
                    if of_the_candidate and rest.lstrip().startswith(":"):
                        rest = " says " + rest.lstrip()[1:]   # "Candidate's answer: I cannot answer ..."
                    subject = [of_the_candidate, words, False]
                    clause = first_words(rest)
                    if not_a_refusal(subject, clause):
                        return shown(subject, clause), declined
                after_a_bare_subject = not first_words(sentence[own[-1][1]:min(part_end, own[-1][1] + _R5_CLAUSE_LOOK)])
                continue
            if subject is None:
                continue
            clause = first_words(sentence[part_start:min(part_end, part_start + _R5_CLAUSE_LOOK)])
            relative = re.match(r"(?:which|that|who)\s+", clause) if after_a_bare_subject else None
            after_a_bare_subject = False
            if relative:                                       # "The candidate's reply, which holds a figure, ..."
                clause = clause[relative.end():]
                if not (_REFUSAL_CLAUSE.match(clause) or _NEGATIVE_CLAUSE.match(clause) or _PLAIN_CLAUSE.match(clause)
                        or (clause.split()[:1] and clause.split()[0] not in _R5_VERBS)):
                    return ("what it says of " + subject[1] + " is not a refusal: "
                            + (subject[1] + ", " + clause)[:60]), declined
                continue
            if not_a_refusal(subject, clause):
                return shown(subject, clause), declined
    return "", declined


def _value_words(frozen_sets: tuple) -> frozenset:
    """The words of the stage and high-impact values, "development" and "use" (F2)."""
    words = {"development", "use"}
    for kind, frozen in frozen_sets:
        if kind in ("stage", "high_impact"):
            for label, _ in frozen:
                words.update(word.casefold() for word in _WORD.findall(label))
    return frozenset(words) - {"not", "but", "and", "or", "of", "the", "a", "an", "in", "to", "for", "with", "by"}


def _loose_value_words(text: str, context: dict) -> list[str]:
    """The words of a value in a CORRECT reply that stand outside the reference value and outside a field name.

    "use" counts only where it is not "use case" ("is in use"), and "development" also inside a field name when
    "in" or "in the" stands before it ("is in the development stage").
    """
    words = _TIE_WORD.findall(text)
    free = [True] * len(words)
    for phrase in tuple(context["fields"]) + (("use", "case"),):
        for first in range(len(words) - len(phrase) + 1):
            if tuple(words[first:first + len(phrase)]) == phrase:
                free[first:first + len(phrase)] = [False] * len(phrase)
    for position, word in enumerate(words):
        if word == "development" and (words[position - 1:position] == ["in"] or words[max(position - 2, 0):position] == ["in", "the"]):
            free[position] = True
    value_words = context.get("value_words") or frozenset()
    return list(dict.fromkeys(word for word, is_free in zip(words, free) if is_free and word in value_words))


def _stem(word: str) -> str:
    """ "deployed" and "deployment" -> "deploy", "retired" -> "retir", "pilot" -> "pilot"."""
    for suffix in ("ment", "ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


@functools.lru_cache(maxsize=16)
def _everyday_names(frozen_sets: tuple) -> tuple:
    """How people write a value that no accepted spelling covers: (capitalised, abbreviations, stems).

    capitalised   {"energy": (kind, label)}: the one word X of "Department of [the] X", counted when it
                  is written with a capital letter. A word two agencies would share is left out.
    abbreviations {"DOE": (kind, label, any_case)}: an agency abbreviation of three letters or more in
                  another letter case. any_case is True for the abbreviations exact match accepts alone
                  ("epa"); the others ("DOE", "STATE") need two capital letters ("DoE").
    stems         ((leading words, stem, kind, label), ...), longest first, for the "stage" set only:
                  "piloting", "pre-deploying", "deployment", "retirement".
    """
    capitalised: dict[str, list] = {}
    abbreviations: dict[str, tuple] = {}
    stems = set()
    for kind, frozen in frozen_sets:
        for label, shortened in frozen:
            words = _plain_words(label)
            if kind == "agency":
                subject = words[3:] if words[:3] == ("department", "of", "the") else words[2:]
                if words[:2] == ("department", "of") and len(subject) == 1:
                    capitalised.setdefault(subject[0], []).append((kind, label))
                for abbreviation in shortened:
                    if len(abbreviation) >= 3 and abbreviation.isalpha():
                        abbreviations[abbreviation.upper()] = (kind, label, abbreviation_stands_alone(abbreviation))
        if kind == "stage":
            for words, label, how, _ in _spellings(frozen, kind):
                if how == "plain" and words:
                    stems.add((words[:-1], _stem(words[-1]), kind, label))
    one_owner = {word: owners[0] for word, owners in capitalised.items() if len(owners) == 1}
    return one_owner, abbreviations, tuple(sorted(stems, key=lambda entry: (-len(entry[0]), -len(entry[1]), entry)))


def read_judge(text: str | None, item: dict | None = None, answer: str | None = None,
               label_sets: dict | None = None) -> dict:
    """Read the judge's reply. Returns {"verdict": one of VERDICTS or UNPARSEABLE, "why": str}.

    A verdict is stated by one of these, and by nothing else:
      1. a JSON object with a "verdict" key (any case of the key; a trailing period in the value,
         a trailing comma in the object and single quotes are tolerated; the object may sit one
         level inside another, or in a list). Next to "verdict" it may carry a reason-like key
         with a string and "confidence" with a number, nothing else;
      2. JSON cut off AFTER a complete "verdict": "<word>" pair that is the first pair of the object;
      3. a line "Verdict: <word>" (also "verdict = <word>", "The verdict is <word>.");
      4. the word at the very start of the reply, alone or followed by a dash, a colon, a period
         or a line break and then a reason.
    Every statement in the reply must give the same one of the three words. Then ALL the rest of
    the reply is read: the reason, other keys and values, objects without a verdict, the text
    before and after. CORRECT and DECLINED are returned only if none of it contradicts them
    (CONTRADICTS_CORRECT, CONTRADICTS_DECLINED and, since round 4, JUDGE_MISMATCH_WORDS,
    JUDGE_ADDS_TO_A_REFUSAL, a character outside JUDGE_ALLOWED_PUNCTUATION, and a statement about
    the candidate that is not tied to the reference) and, for DECLINED with a reason, the reason
    says the candidate declined (SAYS_DECLINED). Otherwise the reply is UNPARSEABLE.

    item, answer, label_sets: the question the reply is for (a row of the evaluation set), the
    candidate's answer, and the label sets of the evaluation set. The evaluation loop passes all
    three. With item and label_sets, values the judge only quotes are taken out before the word
    lists are applied, and a reply that names another value than the reference is refused (see
    the block comment above _judge_spellings). Without them nothing is taken out, so a reason
    that quotes "Not High-impact" is unparseable, as it was in round 2.
    answer is accepted so that the caller hands over everything it knows about the question,
    and is deliberately not used: nothing of the candidate's own words is taken out of a reply
    (the block comment says why).
    """
    def unparseable(why: str) -> dict:
        return {"verdict": UNPARSEABLE, "why": why}

    text = (text or "").strip()
    if not text:
        return unparseable("empty reply")
    body = re.sub(r"```[A-Za-z]*", " ", text)          # code fences carry no meaning

    cut_short = False                                  # JSON cut off inside or after the reason
    statements: list[object] = []                      # every verdict value the reply states
    reasons: list[str] = []                            # text given as the reason for it
    others: list[str] = []                             # every other string inside an object
    keys: list[str] = []                               # the keys of the objects wrapped around the verdict
    outside: list[str] = []                            # the text between and around the objects

    def walk(value, top: bool = True) -> None:
        if isinstance(value, dict):
            if "verdict" in value:
                statements.append(value["verdict"])
                for key, inner in value.items():
                    if key == "verdict":
                        continue
                    if key in JUDGE_REASON_KEYS and isinstance(inner, str):
                        reasons.append(inner)
                    elif key in JUDGE_NUMBER_KEYS and isinstance(inner, (int, float)) and not isinstance(inner, bool):
                        continue
                    else:
                        raise _NotAVerdict(f"the object with the verdict also carries {key!r}")
            else:
                # An object without a verdict is a wrapper ({"result": {...}}) or a note. Round 4: next
                # to the verdict it may hold objects, lists and reason-like strings, nothing else, so
                # that {"match": 0, "grade": {"verdict": "CORRECT"}} is not read as CORRECT.
                for key, inner in value.items():
                    if isinstance(inner, (dict, list)):
                        keys.append(str(key))
                        walk(inner, False)
                    elif key in JUDGE_REASON_KEYS and isinstance(inner, str):
                        others.append(inner)
                    else:
                        raise _NotAVerdict(f"an object without a verdict carries {key!r}")
        elif isinstance(value, list):
            for inner in value:
                walk(inner, False)
        elif isinstance(value, str):
            others.append(value)
        elif isinstance(value, bool) or value is None:
            raise _NotAVerdict("a true, false or null value next to the verdict")

    def rest_before_reason(leading) -> str:
        """What stands between the leading verdict word and its reason: ": ", " - ", ". " or a line break."""
        start = leading.start("rest") if leading.group("rest") is not None else leading.end(1)
        return leading.string[leading.end(1):start]

    decoder = json.JSONDecoder(object_pairs_hook=_pairs)
    position = 0
    try:
        while True:
            brace = body.find("{", position)
            if brace < 0:
                outside.append(body[position:])
                break
            outside.append(body[position:brace])
            try:
                value, stop = decoder.raw_decode(body, brace)
            except ValueError as exc:
                if isinstance(exc, _NotAVerdict):
                    raise
                close = _closing_brace(body, brace)
                value = _lenient_object(body[brace:close + 1]) if close > brace else None
                if value is None:
                    outside.append("{")                # an unread brace: what follows it stays in the text
                    position = brace + 1
                    continue
                stop = close + 1
            walk(value)
            position = stop
    except _NotAVerdict as exc:
        return unparseable(str(exc))
    rest = " ".join(outside)

    unescaped = _UNESCAPED_REASON.fullmatch(body) if not statements else None
    if unescaped and len(re.findall(r'"verdict"\s*:', body)) == 1:
        # Round 4: {"verdict": "CORRECT", "reason": "Candidate states "Deployed", matching reference."} is not
        # JSON, because the marks inside the reason are not escaped (a raw line break does the same). The
        # verdict pair is whole and comes first; everything after it is read as the reason.
        statements.append(unescaped.group("verdict"))
        reasons.append(unescaped.group("value"))
        outside[:] = []
        rest = ""
    if not statements and re.search(r'"verdict"\s*:', body):
        cut_off = _CUT_OFF_JSON.fullmatch(body)
        if not cut_off or len(re.findall(r'"verdict"\s*:', body)) != 1:
            return unparseable("an unfinished object whose verdict cannot be read")
        statements.append(cut_off.group("verdict"))
        key = (cut_off.group("key") or '"')[1:].strip().lower()
        if key and key not in JUDGE_REASON_KEYS and not any(k.startswith(key) for k in JUDGE_REASON_KEYS):
            return unparseable(f"the unfinished object carries {key!r}")
        reasons.append((cut_off.group("value") or '"')[1:])
        rest = cut_off.group("before")
        cut_short = True

    lines = []
    for line in rest.split("\n"):
        stated = _VERDICT_LINE.match(line)
        if stated:
            statements.append(stated.group(1))
        else:
            lines.append(line)
    rest = "\n".join(lines)
    if not statements:
        leading = _LEADING_WORD.match(rest)
        if leading:
            statements.append(leading.group(1))
            reasons.append(leading.group("rest") or leading.group("below") or "")
            rest = ""
            # Round 4: "Correct: Environmental Protection Agency. Candidate: Department of Energy." is a
            # list of labels, and its first word (with its colon) names the right answer, not a verdict.
            if ":" in rest_before_reason(leading) and _LABEL_LINE.search(reasons[-1]):
                return unparseable("the first word is one label in a list of labels, not a verdict")
    if not statements:
        return unparseable("no verdict stated in a shape this reader accepts")

    words = set()
    for stated in statements:
        if not isinstance(stated, str):
            return unparseable("a verdict that is not a string")
        word = stated.strip()
        word = (word[:-1] if word.endswith(".") else word).strip().upper()
        if word not in VERDICTS:
            return unparseable(f"a verdict outside the three words: {stated!r}")
        words.add(word)
    if len(words) != 1:
        return unparseable("more than one verdict")
    verdict = words.pop()
    if _UNREAD_VERDICT.search(rest):
        return unparseable("a second, unread verdict in the text")

    reason_lines = []
    for line in rest.split("\n"):
        labelled = _REASON_LABEL.match(line)
        if labelled:
            reasons.append(line[labelled.end():])
        else:
            reason_lines.append(line)
    rest = "\n".join(reason_lines)

    def plain(parts: list[str], lower: bool = True) -> str:
        joined = " \n ".join(parts)
        joined = (joined.lower() if lower else joined).replace(chr(0x2019), "'").replace("_", " ")
        return re.sub(r"\s+", " ", re.sub(r"n't\b", " not", joined)).strip()

    def without(phrases: tuple[str, ...], checked: str, marker: str = "") -> str:
        """The text without these phrases. With a marker, each phrase (and the rest of its last word, as in
        "no contradicting fact|s") is replaced by the marker instead of a space."""
        for phrase in phrases:
            checked = re.sub("(?:" + phrase + r")\w*", marker, checked) if marker else re.sub(phrase, " ", checked)
        return checked

    # Round 3: with the question known, quoted values are taken out first and the values named are kept.
    context = _judge_context(item, label_sets)
    named: list[tuple[str, str]] = []
    if context:
        def unquote(parts: list[str]) -> list[str]:
            cleaned = []
            for part in parts:
                text_without, values = _mask_judge_text(part, context, JUDGE_QUOTED_MASK)
                cleaned.append(text_without)
                named.extend(values)
            return cleaned
        reasons, others, rest = unquote(reasons), unquote(others), unquote([rest])[0]
    other_values = [label for kind, label in dict.fromkeys(named)
                    if (kind, label) not in context["in_question"]
                    and not (kind == context["kind"] and label == context["expected"])] if context else []

    reason_text = plain(reasons)
    everything = plain(reasons + others + keys + [rest])
    inside = plain(reasons + others)                           # what the reply says in its own words, objects only
    if verdict in ("CORRECT", "DECLINED"):
        # Round 4: a character outside the list.
        odd = _odd_characters(reasons + others) + _odd_characters([_JUDGE_TAG.sub(" ", rest)])
        if odd:
            return unparseable(f"{verdict}, but the reply holds a character outside the allowed list: "
                               + " ".join(dict.fromkeys(odd)))
        against = _matches(JUDGE_OUTSIDE_AGAINST, plain([rest]))
        if against:
            return unparseable(f"{verdict}, but the text around it reads as an example or a format: "
                               + ", ".join(sorted(set(against))))
    if verdict == "CORRECT":
        if context and context["kind"]:
            another = [label for kind, label in dict.fromkeys(named)
                       if kind == context["kind"] and label in other_values]
            if another:
                return unparseable("CORRECT, but the reply names another value of the field: " + ", ".join(another))
        cleaned = without(JUDGE_SAFE_PHRASES + JUDGE_NEGATED_DECLINE, everything)
        against = _matches(CONTRADICTS_CORRECT + JUDGE_MISMATCH_WORDS, cleaned)
        if against:
            return unparseable("CORRECT, but the reply also says: " + ", ".join(sorted(set(against))))
        if context and context["kind"]:
            marked = without(JUDGE_SAFE_PHRASES + JUDGE_NEGATED_DECLINE, inside, f" {_FINE_TOKEN} ")
            if cut_short:                                      # the last word may be half a word ("matching the refer")
                marked = re.sub(r"[^\W_]+\s*$", "", marked)
            around = without(JUDGE_SAFE_PHRASES + JUDGE_NEGATED_DECLINE, plain([_JUDGE_TAG.sub(" . ", rest)]),
                             f" {_FINE_TOKEN} ")
            untied = (_untied_statement(marked, context["own_words"])
                      or _untied_statement(around, context["own_words"], around=True))
            if untied:
                return unparseable("CORRECT, but the reason is not tied to the reference value: " + untied[:80])
            loose = _loose_value_words(marked, context) + _loose_value_words(around, context)
            if loose:                                          # round 5, F2: "The impact is high."
                return unparseable("CORRECT, but the reply speaks of a value in words of its own: "
                                   + " ".join(dict.fromkeys(loose)))
            said = set(_TIE_WORD.findall(marked))
            if said and not said & {_VALUE_TOKEN, _FINE_TOKEN} and not said & JUDGE_SAYS_IT_MATCHES:
                return unparseable("CORRECT, but the reason neither holds the reference value nor says that "
                                   "the answer matches")
        else:
            differing = _statements_differ(plain([part.replace("\n", " . ") for part in reasons + others + [rest]],
                                                 lower=False))
            if differing:
                return unparseable("CORRECT, but the reply gives two different things: " + differing[:120])
    elif verdict == "DECLINED":
        if other_values:
            return unparseable("DECLINED, but the reply names a value: " + ", ".join(other_values))
        # Round 5: with the question known, "which is correct" after a refusal is not read against it (F5).
        safe = JUDGE_SAFE_UNDER_DECLINED + (JUDGE_SAFE_UNDER_DECLINED_WITH_THE_QUESTION if context else ())
        against = _matches((CONTRADICTS_DECLINED_WITH_THE_QUESTION + JUDGE_NOT_A_REFUSAL if context
                            else CONTRADICTS_DECLINED) + JUDGE_ADDS_TO_A_REFUSAL, without(safe, everything))
        if against:
            return unparseable("DECLINED, but the reply also says: " + ", ".join(sorted(set(against))))
        around = plain([_JUDGE_TAG.sub(" . ", rest)])
        unknown = [word for word in _TIE_WORD.findall(without(safe, inside + " . " + around))
                   if word not in JUDGE_REFUSAL_WORDS and word not in context["own_words"]
                   and word not in JUDGE_LEAD_IN_WORDS and word not in (_VALUE_TOKEN, _QUOTED_TOKEN)] if context else []
        if unknown:
            return unparseable("DECLINED, but the reply holds words that are not words of a refusal: "
                               + " ".join(dict.fromkeys(unknown))[:80])
        declined = False
        if context:
            # Round 5 (F1): what each sentence says of the candidate must be a refusal (block "Round 5").
            for part, is_around in ((without(safe, inside), False), (without(safe, around), True)):
                wrong, said_so = _not_a_refusal(part, is_around)
                if wrong:
                    return unparseable("DECLINED, but " + wrong)
                declined = declined or said_so
        if reason_text and not (_matches(SAYS_DECLINED, reason_text) or declined):
            return unparseable("DECLINED, but the reason does not say that the candidate declined")
    else:
        # Round 4: "declines, but then names an agency" is an answer, and for a question that HAS an
        # answer a refusal is simply not correct. Only a bare "the candidate declined" for a question
        # without an answer leaves it open which of the two the judge meant.
        if (re.search(r"\bdeclin\w*", without(JUDGE_NOT_DECLINING, everything))
                and not (context and context["answerable"]) and not _matches(JUDGE_WENT_ON_TO_ANSWER, everything)):
            return unparseable("INCORRECT, but the reply also says the candidate declined")
        if _SAYS_IS_CORRECT.search(everything) and not _QUALIFIES.search(everything):
            return unparseable("INCORRECT, but the reply also says the candidate is correct")
    return {"verdict": verdict, "why": ""}


def parse_judge(text: str | None, item: dict | None = None, answer: str | None = None,
                label_sets: dict | None = None) -> str:
    """The judge's verdict: CORRECT, INCORRECT, DECLINED or UNPARSEABLE. See read_judge."""
    return read_judge(text, item, answer, label_sets)["verdict"]


def judged_correct(item: dict, verdict: str) -> bool:
    """Answerable: the judge must say CORRECT. Unanswerable: the judge must say DECLINED."""
    return verdict == ("CORRECT" if item["answerable"] else "DECLINED")


def answered_anyway(row: dict) -> bool:
    """An unanswerable question the judge says was answered: only the verdict INCORRECT counts."""
    return not row["answerable"] and row.get("judge_verdict") == "INCORRECT"


def judge_unclear(row: dict) -> bool:
    """No usable verdict: an unparseable reply, or CORRECT for a question that has no answer."""
    verdict = row.get("judge_verdict")
    return verdict == UNPARSEABLE or (not row["answerable"] and verdict == "CORRECT")


def with_guardrail(row: dict) -> dict:
    """Derive the guardrail-on outcome from the guardrail-off outcome and the guardrail verdict.

    A blocked answer is replaced by the guardrail's message, so it counts as a
    refusal: wrong for an answerable question, right for an unanswerable one.
    """
    blocked = bool(row.get("blocked"))
    answerable = row["answerable"]
    return {
        "exact_on": (row["exact"] and not blocked) if answerable else (row["exact"] or blocked),
        "judged_correct_on": (row["judged_correct"] and not blocked) if answerable
        else (row["judged_correct"] or blocked),
        "declined_on": bool(row["declined"]) or blocked,
    }


BLOCK_CATEGORIES = (
    "on_refusal_sentences",
    "on_answerable_judged_correct",
    "on_answerable_judged_incorrect",
    "on_unanswerable_answered_anyway",
    "on_unanswerable_soft_refusals",
    "on_unanswerable_judge_unclear",
)


def block_category(row: dict) -> str:
    """Put one blocked answer into exactly one bucket (the buckets sum to the total)."""
    if row["declined"]:
        return "on_refusal_sentences"            # the fixed refusal sentence itself was blocked
    if row["answerable"]:
        # "judged incorrect" here means "not judged CORRECT": INCORRECT, DECLINED or unparseable.
        return "on_answerable_judged_correct" if row["judged_correct"] else "on_answerable_judged_incorrect"
    if row["judged_correct"]:
        return "on_unanswerable_soft_refusals"   # judge read it as a refusal in other words
    if judge_unclear(row):
        return "on_unanswerable_judge_unclear"
    return "on_unanswerable_answered_anyway"


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion. None when n is 0."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(successes: int, n: int) -> dict:
    interval = wilson_interval(successes, n)
    return {
        "count": successes,
        "n": n,
        "rate": (successes / n) if n else None,
        "ci95_low": interval[0] if interval else None,
        "ci95_high": interval[1] if interval else None,
    }


def exact_outcome(row: dict) -> str:
    """One of four for an answerable row: correct, different_value, refused, unclear. They add up to n."""
    if row.get("exact"):
        return "correct"
    if row.get("declined"):
        return "refused"
    if row.get("exact_note") == "different_value":
        return "different_value"
    return "unclear"


def summarise(rows: list[dict], top_k: int, earlier_attempts: list[dict] | None = None,
              guardrail_applied: bool = True) -> dict:
    """Aggregate per-question rows into the off/on comparison.

    rows: the latest result of each question. earlier_attempts: results of the same questions
    from attempts that failed and were run again with --resume. They are in no rate, but
    their usage is added to the usage totals, because AWS billed the calls that succeeded.
    guardrail_applied False (--no-guardrail): the "on" numbers are still computed, and equal the
    "off" numbers, but the table prints "not applied" in their place.
    """
    earlier_attempts = list(earlier_attempts or [])
    errors = [r for r in rows if r.get("error")]
    ok = [r for r in rows if not r.get("error")]
    ans = [r for r in ok if r["answerable"]]
    una = [r for r in ok if not r["answerable"]]

    def count(pool, predicate) -> int:
        return sum(1 for r in pool if predicate(r))

    def unblocked(r) -> bool:
        return not r.get("blocked")

    # Document ids are read from the location of each retrieved passage. If none could be
    # read, a hit rate of 0 would be an artefact of the parser, not a measurement.
    passages = [doc_id for r in ok for doc_id in (r.get("retrieved_doc_ids") or [])]
    without_id = sum(1 for doc_id in passages if not doc_id)
    hit_measured = bool(passages) and without_id < len(passages)

    blocked = [r for r in ok if r.get("blocked")]
    billed = list(rows) + earlier_attempts
    summary = {
        "top_k": top_k,
        "questions_total": len(rows),
        "questions_scored": len(ok),
        "questions_with_errors": len(errors),
        "complete": not errors,
        "guardrail_applied": bool(guardrail_applied),
        "answerable_n": len(ans),
        "unanswerable_n": len(una),
        "judge_unparseable": count(ok, lambda r: r.get("judge_verdict") == UNPARSEABLE),
        "judge_correct_on_unanswerable": count(una, lambda r: r.get("judge_verdict") == "CORRECT"),
        "retrieval": {
            "hit_at_k": rate(count(ans, lambda r: r.get("hit") is True), len(ans)),
            "hit_at_1": rate(count(ans, lambda r: r.get("hit_rank") == 1), len(ans)),
            "hit_rate_measured": hit_measured,
            "passages_retrieved": len(passages),
            "passages_without_document_id": without_id,
            "questions_with_no_passage": count(ok, lambda r: not (r.get("retrieved_doc_ids") or [])),
        },
        "guardrail_off": {
            "answerable_exact_correct": rate(count(ans, lambda r: r["exact"]), len(ans)),
            "answerable_exact_unclear": rate(count(ans, lambda r: exact_outcome(r) == "unclear"), len(ans)),
            "answerable_exact_different_value": rate(
                count(ans, lambda r: exact_outcome(r) == "different_value"), len(ans)),
            "answerable_judged_correct": rate(count(ans, lambda r: r["judged_correct"]), len(ans)),
            "answerable_refused": rate(count(ans, lambda r: r["declined"]), len(ans)),
            "unanswerable_refused": rate(count(una, lambda r: r["declined"]), len(una)),
            "unanswerable_judged_declined": rate(count(una, lambda r: r["judged_correct"]), len(una)),
            "unanswerable_answered_anyway": rate(count(una, answered_anyway), len(una)),
            "unanswerable_judge_unclear": rate(count(una, judge_unclear), len(una)),
        },
        "guardrail_on": {
            "answerable_exact_correct": rate(count(ans, lambda r: r["exact_on"]), len(ans)),
            "answerable_exact_unclear": rate(
                count(ans, lambda r: exact_outcome(r) == "unclear" and unblocked(r)), len(ans)),
            "answerable_exact_different_value": rate(
                count(ans, lambda r: exact_outcome(r) == "different_value" and unblocked(r)), len(ans)),
            "answerable_judged_correct": rate(count(ans, lambda r: r["judged_correct_on"]), len(ans)),
            "answerable_refused": rate(count(ans, lambda r: r["declined_on"]), len(ans)),
            "unanswerable_refused": rate(count(una, lambda r: r["declined_on"]), len(una)),
            "unanswerable_judged_declined": rate(count(una, lambda r: r["judged_correct_on"]), len(una)),
            "unanswerable_answered_anyway": rate(
                count(una, lambda r: answered_anyway(r) and unblocked(r)), len(una)),
            "unanswerable_judge_unclear": rate(
                count(una, lambda r: judge_unclear(r) and unblocked(r)), len(una)),
        },
        "guardrail_blocks": {
            "total": len(blocked),
            **{name: count(blocked, lambda r, name=name: block_category(r) == name)
               for name in BLOCK_CATEGORIES},
        },
        "exact_vs_judge_agreement": rate(count(ans, lambda r: r["exact"] == r["judged_correct"]), len(ans)),
        "by_type": {},
        "usage": {
            "retrieve_calls": count(billed, lambda r: r.get("retrieved_doc_ids") is not None),
            "gen_input_tokens": sum(r.get("gen_input_tokens") or 0 for r in billed),
            "gen_output_tokens": sum(r.get("gen_output_tokens") or 0 for r in billed),
            "judge_input_tokens": sum(r.get("judge_input_tokens") or 0 for r in billed),
            "judge_output_tokens": sum(r.get("judge_output_tokens") or 0 for r in billed),
            "guardrail_text_units": sum(r.get("guardrail_units") or 0 for r in billed),
            "guardrail_calls": count(billed, lambda r: r.get("guardrail_action") is not None),
            "earlier_failed_attempts_included": len(earlier_attempts),
            # of those: attempts that were stopped (Ctrl-C, a kill) before their row was written, rebuilt
            # by --resume from last_question_calls.json
            "interrupted_attempts_included": count(earlier_attempts, lambda r: bool(r.get("interrupted"))),
        },
        # a call that ended at the token limit: the text is cut, whatever the scorers made of it
        "answers_cut_at_token_limit": count(ok, lambda r: r.get("gen_stop_reason") == "max_tokens"),
        "judge_replies_cut_at_token_limit": count(ok, lambda r: r.get("judge_stop_reason") == "max_tokens"),
    }
    for kind in sorted({r["type"] for r in ok}):
        pool = [r for r in ok if r["type"] == kind]
        measured = pool[0]["answerable"] and hit_measured
        summary["by_type"][kind] = {
            "n": len(pool),
            "hit_at_k": rate(count(pool, lambda r: r.get("hit") is True), len(pool)) if measured else None,
            "answerable": bool(pool[0]["answerable"]),
            "exact_off": rate(count(pool, lambda r: r["exact"]), len(pool)),
            "exact_unclear": count(pool, lambda r: r["answerable"] and exact_outcome(r) == "unclear"),
            "judged_off": rate(count(pool, lambda r: r["judged_correct"]), len(pool)),
            "exact_on": rate(count(pool, lambda r: r["exact_on"]), len(pool)),
            "judged_on": rate(count(pool, lambda r: r["judged_correct_on"]), len(pool)),
            "blocked": count(pool, lambda r: r.get("blocked")),
        }
    return summary


def _cell(value: dict | None) -> str:
    if not value or value["n"] == 0 or value["rate"] is None:
        return "n/a"
    return (f"{value['count']}/{value['n']} ({value['rate'] * 100:.1f}%, "
            f"95% CI {value['ci95_low'] * 100:.0f} to {value['ci95_high'] * 100:.0f})")


def retrieval_warnings(summary: dict) -> list[str]:
    """Plain sentences about anything that makes the hit rate untrustworthy. Empty when all is well."""
    retrieval = summary["retrieval"]
    total, missing = retrieval["passages_retrieved"], retrieval["passages_without_document_id"]
    lines = []
    if summary["questions_scored"] and total == 0:
        lines.append("WARNING: no passage was retrieved for any question, so the hit rate was NOT MEASURED. "
                     "Check the knowledge base and the ingestion statistics before reading any number below.")
    elif total and missing == total:
        lines.append(f"WARNING: no document id could be read from any of the {total} retrieved passages, so the "
                     "hit rate was NOT MEASURED (it is not 0). The passage locations do not look the way "
                     "kitlib/aws.py parse_retrieve_response expects; look at retrieved_passages in raw.jsonl.")
    elif missing:
        lines.append(f"WARNING: {missing} of {total} retrieved passages carried no readable document id. "
                     "The hit rates below are therefore a lower bound, not a measurement.")
    return lines


NOT_APPLIED = "not applied"


def render_summary_markdown(summary: dict, context: dict | None = None) -> str:
    """The comparison table that goes into RESULTS_TEMPLATE.md."""
    context = context or {}
    off, on = summary["guardrail_off"], summary["guardrail_on"]
    blocks = summary["guardrail_blocks"]
    k = summary["top_k"]
    applied = summary.get("guardrail_applied", True)

    def with_guardrail_cell(value) -> str:
        """A cell of the "Guardrail on" column: never a number when no guardrail was applied."""
        if not applied:
            return NOT_APPLIED
        return _cell(value) if isinstance(value, dict) or value is None else str(value)

    lines = []
    if not summary["complete"]:
        lines += [f"**INCOMPLETE RUN: {summary['questions_with_errors']} question(s) hit an error and are "
                  "left out of every rate below. Do not quote these numbers.**", ""]
    for warning in retrieval_warnings(summary):
        lines += [f"**{warning}**", ""]
    cut_answers = summary.get("answers_cut_at_token_limit", 0)
    cut_replies = summary.get("judge_replies_cut_at_token_limit", 0)
    if cut_answers or cut_replies:
        lines += [f"**WARNING: {cut_answers} answer(s) and {cut_replies} judge reply(ies) ended at the token limit "
                  "(stop reason max_tokens), so their text is cut off. They are scored as they arrived. The rows are "
                  "marked in per_question.csv (gen_stop_reason, judge_stop_reason).**", ""]
    for key, value in context.items():
        lines.append(f"- {key}: {value}")
    if context:
        lines.append("")
    measured = summary["retrieval"]["hit_rate_measured"]
    hit_at_k = _cell(summary["retrieval"]["hit_at_k"]) if measured else "NOT MEASURED (see the warning above)"
    hit_at_1 = _cell(summary["retrieval"]["hit_at_1"]) if measured else "NOT MEASURED (see the warning above)"
    if not summary["questions_scored"]:
        hit_at_k = hit_at_1 = "n/a"
    same = "same retrieval" if applied else NOT_APPLIED
    rows = [
        ("Answerable questions scored", summary["answerable_n"], with_guardrail_cell(summary["answerable_n"])),
        (f"Retrieval hit rate, source document in top {k}", hit_at_k, same),
        ("Retrieval hit rate, source document ranked first", hit_at_1, same),
        ("Answerable: correct by exact match", _cell(off["answerable_exact_correct"]),
         with_guardrail_cell(on["answerable_exact_correct"])),
        ("Answerable: unclear to exact match (counted as not correct)", _cell(off["answerable_exact_unclear"]),
         with_guardrail_cell(on["answerable_exact_unclear"])),
        ("Answerable: another value, read cleanly by exact match", _cell(off["answerable_exact_different_value"]),
         with_guardrail_cell(on["answerable_exact_different_value"])),
        ("Answerable: correct as judged", _cell(off["answerable_judged_correct"]),
         with_guardrail_cell(on["answerable_judged_correct"])),
        ("Answerable: refused or blocked", _cell(off["answerable_refused"]),
         with_guardrail_cell(on["answerable_refused"])),
        ("Unanswerable questions scored", summary["unanswerable_n"], with_guardrail_cell(summary["unanswerable_n"])),
        ("Unanswerable: refused or blocked (exact: the fixed sentence alone)", _cell(off["unanswerable_refused"]),
         with_guardrail_cell(on["unanswerable_refused"])),
        ("Unanswerable: refused or blocked (judged DECLINED)", _cell(off["unanswerable_judged_declined"]),
         with_guardrail_cell(on["unanswerable_judged_declined"])),
        ("Unanswerable: answered anyway (judged INCORRECT)", _cell(off["unanswerable_answered_anyway"]),
         with_guardrail_cell(on["unanswerable_answered_anyway"])),
        ("Unanswerable: judge verdict unclear (CORRECT or unparseable)", _cell(off["unanswerable_judge_unclear"]),
         with_guardrail_cell(on["unanswerable_judge_unclear"])),
        ("Guardrail blocks (grounding or relevance filter), total", NOT_APPLIED, with_guardrail_cell(blocks["total"])),
        ("... blocks of answers judged correct", NOT_APPLIED,
         with_guardrail_cell(blocks["on_answerable_judged_correct"])),
        ("... blocks of answers not judged correct (answerable)", NOT_APPLIED,
         with_guardrail_cell(blocks["on_answerable_judged_incorrect"])),
        ("... blocks of invented answers to unanswerable questions", NOT_APPLIED,
         with_guardrail_cell(blocks["on_unanswerable_answered_anyway"])),
        ("... blocks of refusals in other words (unanswerable)", NOT_APPLIED,
         with_guardrail_cell(blocks["on_unanswerable_soft_refusals"])),
        ("... blocks where the judge verdict was unclear (unanswerable)", NOT_APPLIED,
         with_guardrail_cell(blocks["on_unanswerable_judge_unclear"])),
        ("... blocks of the fixed refusal sentence", NOT_APPLIED,
         with_guardrail_cell(blocks["on_refusal_sentences"])),
    ]
    lines += ["| Measure | Guardrail off | Guardrail on |", "|---|---|---|"]
    lines += [f"| {name} | {off_cell} | {on_cell} |" for name, off_cell, on_cell in rows]
    lines.append("")
    if applied:
        lines.append(
            "The two columns are the same answers. \"Guardrail on\" differs from \"off\" only by the blocked answers "
            "counted above, so the difference between the columns is those counts. It is not a comparison of two "
            "samples, and the intervals are not a test of it.")
        lines.append(
            "A block means the guardrail intervened: either filter, grounding or relevance, scored the answer "
            "under its threshold (both are set to BLOCK). Which one it was is not counted here; the two scores "
            "of every answer are in per_question.csv (grounding_score, relevance_score).")
    else:
        lines.append(
            "The guardrail was NOT APPLIED in this run (--no-guardrail), so there is no \"guardrail on\" result: "
            "every cell of that column says so. Run without --no-guardrail to fill it.")
    lines += [
        "Exact match gives credit only when the answer is the expected value plus words from a short fixed list "
        "(kitlib/scoring.py, FILLER_PHRASES and LEAD_IN_PHRASES). Any other word, a question mark, a second, "
        "different value or a hedge makes "
        "the answer \"unclear\", which is counted as not correct. So the exact-match rate can undercount, and "
        f"the unclear row says by how much at most: {off['answerable_exact_unclear']['count']} of "
        f"{summary['answerable_n']} answerable answers here. Correct, unclear, another value and refused add up "
        "to the answerable questions. Read the unclear rows (exact_note and exact_unread in per_question.csv) "
        "before quoting the rate.",
        f"Exact match and judge agree on {_cell(summary['exact_vs_judge_agreement'])} of answerable questions "
        "(guardrail off). Read the rows where they disagree before quoting either number.",
        f"Judge replies that could not be parsed (counted as not correct, and as unclear for an unanswerable "
        f"question): {summary['judge_unparseable']}. A reply is unparseable when it states no single verdict, "
        "when its own reason or other text speaks against the verdict it states, or when the reason of a CORRECT or "
        "DECLINED verdict holds a word that is on none of the reader's lists (judge_note says which). So the judged "
        "rate can undercount too. Judge verdict CORRECT on a "
        f"question that has no answer (counted as unclear, never as a refusal): "
        f"{summary['judge_correct_on_unanswerable']}.",
        "",
        "| Answerable question type | n | Hit in top k | Exact correct, off | Exact unclear | Judged correct, off | "
        "Exact correct, on | Judged correct, on | Blocked |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_type = summary["by_type"]

    def is_answerable(kind: str, t: dict) -> bool:
        return t.get("answerable", not kind.startswith("unanswerable"))

    for kind, t in by_type.items():
        if is_answerable(kind, t):
            lines.append(
                f"| {kind} | {t['n']} | {_cell(t['hit_at_k'])} | {_cell(t['exact_off'])} | {t.get('exact_unclear', 0)} | "
                f"{_cell(t['judged_off'])} | {with_guardrail_cell(t['exact_on'])} | "
                f"{with_guardrail_cell(t['judged_on'])} | {with_guardrail_cell(t['blocked'])} |")
    lines += [
        "",
        "For a question that has no answer the right outcome is a refusal, so these columns count refusals:",
        "",
        "| Unanswerable question type | n | Refused with the fixed sentence, off | Judged DECLINED, off | "
        "Refused or blocked, on | Judged DECLINED or blocked, on | Blocked |",
        "|---|---|---|---|---|---|---|",
    ]
    for kind, t in by_type.items():
        if not is_answerable(kind, t):
            lines.append(
                f"| {kind} | {t['n']} | {_cell(t['exact_off'])} | {_cell(t['judged_off'])} | "
                f"{with_guardrail_cell(t['exact_on'])} | {with_guardrail_cell(t['judged_on'])} | "
                f"{with_guardrail_cell(t['blocked'])} |")
    return "\n".join(lines) + "\n"
