"""Build the fixed evaluation set from the CSV fields. No language model is involved.

Every expected answer is copied from a CSV cell of the row the question is
about. Questions are filled-in templates. The only randomness is which rows
are picked, and that is driven by one seed.

Question types
  agency                     expected = agency_name (the abbreviation is an accepted alias)
  stage                      expected = development_stage
  high_impact                expected = is_high_impact
  unanswerable_heldout       asks about a real use case that was left OUT of the corpus
  unanswerable_absent_field  asks for an attribute the inventory does not record
For the two unanswerable types the system should decline.

Near-duplicates (added after the round 1 review). The inventory holds groups of use cases
whose names differ by a word ("R (Forecasting, ...)" and "Matlab (Forecasting, ...)").
Two rules keep them from blurring what a question measures:

  * An answerable question is not built on a row when another corpus document has a
    similar name (difflib ratio of the lower-cased names >= 0.75) AND the same value of
    the field asked about: the right answer could then come from the wrong document, and
    "correct without a retrieval hit" would not mean what it says. If the similar document
    has ANOTHER value the question is kept, because confusing the two gives a wrong
    answer, and the item carries the similar documents in "near_duplicate_doc_ids".
  * A held-out question is not built on a row when a corpus document OF THE SAME AGENCY
    has a similar name (ratio >= 0.70) or nearly the same description (>= 0.80 of the
    row's description words): an "invented" agency could then be the true one.

Rows turned down this way are listed in eval_set_meta.json under "near_duplicates".
"""
from __future__ import annotations

import difflib
import random
import re
import unicodedata
from collections import Counter, defaultdict

from .corpus import (
    FIELD_AGENCY, FIELD_AGENCY_ABBR, FIELD_BENEFITS, FIELD_BUREAU, FIELD_CLASS, FIELD_HIGH_IMPACT,
    FIELD_OUTPUTS, FIELD_PROBLEM, FIELD_STAGE, FIELD_TOPIC, FIELD_USE_CASE, Row, is_eligible,
)

NO_ANSWER = "NO_ANSWER_IN_CORPUS"

# Valid values as the CSV stores them (shorthand codes in the OMB data dictionary,
# Validation/data_dictionary.md at the pinned commit).
STAGE_LABELS = ["Pre-deployment", "Pilot", "Deployed", "Retired"]
HIGH_IMPACT_LABELS = [
    "High-impact",
    "Not High-impact",
    "Presumed High-Impact, but Not High-impact",
]

TEMPLATES = {
    "agency": 'Which federal agency reported the AI use case named "{name}" '
              "in the 2025 federal AI use case inventory?",
    "stage": 'What stage of development is recorded for the AI use case named "{name}", '
             "reported by the {agency_name}?",
    "high_impact": 'What high-impact determination is recorded for the AI use case named "{name}", '
                   "reported by the {agency_name}?",
}

# Attributes the inventory has no column for. A document is used for one of these
# only if none of the stems appears in the row's free text, so the corpus cannot
# hold an answer by accident.
ABSENT_FIELD_TEMPLATES = [
    ("annual_budget",
     'What annual budget in dollars is recorded for the AI use case named "{name}", '
     "reported by the {agency_name}?",
     ("budget", "$", "dollar", "cost", "funding", "million", "billion")),
    ("staff_count",
     'How many full-time staff are recorded as assigned to the AI use case named "{name}", '
     "reported by the {agency_name}?",
     ("staff", "fte", "employee", "personnel", "headcount", "full-time", "full time")),
    ("accuracy_percentage",
     'What accuracy percentage is recorded for the AI use case named "{name}", '
     "reported by the {agency_name}?",
     ("accura", "%", "percent", "precision", "recall", "f1")),
]

DEFAULT_COUNTS = {
    "agency": 40,
    "stage": 30,
    "high_impact": 30,
    "unanswerable_heldout": 12,
    "unanswerable_absent_field": 8,
}

NAME_MIN_CHARS = 15
NAME_MAX_CHARS = 150
NAME_MIN_WORDS = 3
HELDOUT_MAX_JACCARD = 0.5
NEAR_DUPLICATE_NAME_RATIO = 0.75
HELDOUT_SAME_AGENCY_NAME_RATIO = 0.70
HELDOUT_SAME_AGENCY_TEXT_OVERLAP = 0.80
# Plain characters only: no quotes (the name sits inside quotes in the question) and
# none of the mis-encoded characters ("?") that a few CSV cells carry.
NAME_ALLOWED = re.compile(r"[A-Za-z0-9 \-/&(),.:'+]+")


def norm_name(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def name_tokens(text: str) -> frozenset[str]:
    return frozenset(norm_name(text).split())


def name_counts(rows: list[Row]) -> Counter:
    return Counter(norm_name(r.get(FIELD_USE_CASE)) for r in rows)


def name_similarity(a: str, b: str, at_least: float = 0.0) -> float:
    """difflib ratio of two names, lower-cased, between 0 and 1.

    `at_least` lets the cheap upper bounds skip the full comparison: when they show the ratio
    cannot reach it, 0.0 is returned.
    """
    matcher = difflib.SequenceMatcher(None, (a or "").casefold(), (b or "").casefold(), autojunk=False)
    if at_least and (matcher.real_quick_ratio() < at_least or matcher.quick_ratio() < at_least):
        return 0.0
    return matcher.ratio()


def description_words(row: Row) -> frozenset[str]:
    """Words of four or more characters in the problem and benefits text of a row."""
    text = f"{row.get(FIELD_PROBLEM)} {row.get(FIELD_BENEFITS)}".casefold()
    return frozenset(re.findall(r"[a-z0-9]{4,}", text))


def description_overlap(row: Row, other: Row) -> float:
    """Share of `row`'s description words that also occur in `other`'s description."""
    words = description_words(row)
    return len(words & description_words(other)) / len(words) if words else 0.0


def good_name(row: Row, counts: Counter) -> bool:
    """A name is usable in a question if it is unique in the WHOLE CSV and specific."""
    name = row.get(FIELD_USE_CASE)
    if not (NAME_MIN_CHARS <= len(name) <= NAME_MAX_CHARS):
        return False
    if len(name.split()) < NAME_MIN_WORDS or not NAME_ALLOWED.fullmatch(name):
        return False
    return counts[norm_name(name)] == 1


def leaks_agency(row: Row) -> bool:
    """True if the use case name itself gives away its own agency."""
    name = row.get(FIELD_USE_CASE)
    abbr = row.get(FIELD_AGENCY_ABBR)
    agency = row.get(FIELD_AGENCY)
    if abbr and re.search(rf"(?<![A-Za-z0-9]){re.escape(abbr)}(?![A-Za-z0-9])", name, re.IGNORECASE):
        return True
    return bool(agency) and norm_name(agency) in norm_name(name)


def name_contains_value(name: str, label_set: list[dict]) -> bool:
    """True if the use case name contains any value of the field being asked about.

    Such a name (for example "... Pilot" in a question about the stage) would make
    the exact-match check ambiguous when the model repeats the name, so the row is
    not used for that question type.
    """
    padded = f" {norm_name(name)} "
    for entry in label_set:
        if f" {norm_name(entry['label'])} " in padded:
            return True
        for alias in entry.get("aliases", []):
            text = alias.get("text") or ""
            if not text:
                continue
            if alias.get("case_sensitive"):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(text)}(?![A-Za-z0-9])", name):
                    return True
            elif f" {norm_name(text)} " in padded:
                return True
    return False


def agency_label_set(rows: list[Row]) -> list[dict]:
    """All agencies in the CSV, as closed-set labels with their abbreviations as aliases."""
    pairs = sorted({(r.get(FIELD_AGENCY), r.get(FIELD_AGENCY_ABBR)) for r in rows if r.get(FIELD_AGENCY)})
    return [{"label": name, "aliases": [{"text": abbr, "case_sensitive": True}] if abbr else []}
            for name, abbr in pairs]


def simple_label_set(labels: list[str]) -> list[dict]:
    return [{"label": label, "aliases": []} for label in labels]


def _round_robin(groups: dict[str, list[Row]], order: list[str], n: int, used: set[int],
                 skip=None) -> list[Row]:
    """Take rows from the groups in turn so every label gets a fair share.

    skip(row) True means the row is passed over (and not marked as used).
    """
    picked: list[Row] = []
    cursors = {key: 0 for key in order}
    while len(picked) < n:
        progressed = False
        for key in order:
            if len(picked) >= n:
                break
            pool = groups.get(key, [])
            while cursors[key] < len(pool) and (
                    pool[cursors[key]].row_number in used or (skip is not None and skip(pool[cursors[key]]))):
                cursors[key] += 1
            if cursors[key] < len(pool):
                row = pool[cursors[key]]
                cursors[key] += 1
                used.add(row.row_number)
                picked.append(row)
                progressed = True
        if not progressed:
            break
    return picked


def _free_text(row: Row) -> str:
    """Everything of this row that can reach a document, uncut and lower-cased."""
    parts = [row.get(f) for f in (FIELD_USE_CASE, FIELD_BUREAU, FIELD_TOPIC, FIELD_CLASS,
                                  FIELD_PROBLEM, FIELD_BENEFITS, FIELD_OUTPUTS)]
    return " ".join(parts).casefold()


def build_eval_set(rows: list[Row], corpus_row_numbers: set[int], seed: int,
                   counts: dict[str, int] | None = None) -> tuple[list[dict], dict]:
    """Return (items, meta). Deterministic for a given (rows, corpus, seed, counts)."""
    want = dict(DEFAULT_COUNTS)
    want.update(counts or {})
    rng = random.Random(seed)
    all_counts = name_counts(rows)

    in_corpus = [r for r in rows if r.row_number in corpus_row_numbers and good_name(r, all_counts)]
    used: set[int] = set()
    agency_set = agency_label_set(rows)
    stage_set = simple_label_set(STAGE_LABELS)
    high_impact_set = simple_label_set(HIGH_IMPACT_LABELS)

    def usable(pool: list[Row], label_set: list[dict]) -> list[Row]:
        return [r for r in pool if not name_contains_value(r.get(FIELD_USE_CASE), label_set)]

    def grouped(field: str, labels: list[str], pool: list[Row]) -> dict[str, list[Row]]:
        groups: dict[str, list[Row]] = defaultdict(list)
        for r in pool:
            if r.get(field) in labels:
                groups[r.get(field)].append(r)
        for key in groups:
            rng.shuffle(groups[key])
        return groups

    # Near-duplicates among the corpus documents (see the module docstring). The shuffles above
    # and below run on the same lists whether or not a row is later passed over, so the rule
    # changes only the rows it turns down and what replaces them.
    corpus_members = [r for r in rows if r.row_number in corpus_row_numbers]
    similar_cache: dict[int, list[Row]] = {}
    excluded: dict[str, list[int]] = {"agency": [], "stage": [], "high_impact": [], "unanswerable_heldout": []}

    def similar_documents(row: Row) -> list[Row]:
        """Other corpus documents whose name is close to this row's name."""
        if row.row_number not in similar_cache:
            name = row.get(FIELD_USE_CASE)
            similar_cache[row.row_number] = [
                other for other in corpus_members
                if other.row_number != row.row_number
                and name_similarity(name, other.get(FIELD_USE_CASE), NEAR_DUPLICATE_NAME_RATIO)
                >= NEAR_DUPLICATE_NAME_RATIO]
        return similar_cache[row.row_number]

    def twin_with_same_value(kind: str, field: str):
        def skip(row: Row) -> bool:
            if any(other.get(field) == row.get(field) for other in similar_documents(row)):
                if row.row_number not in excluded[kind]:
                    excluded[kind].append(row.row_number)
                return True
            return False
        return skip

    # Scarcest labels first, so they are not used up by another question type.
    hi_rows = _round_robin(grouped(FIELD_HIGH_IMPACT, HIGH_IMPACT_LABELS, usable(in_corpus, high_impact_set)),
                           HIGH_IMPACT_LABELS, want["high_impact"], used,
                           twin_with_same_value("high_impact", FIELD_HIGH_IMPACT))
    stage_rows = _round_robin(grouped(FIELD_STAGE, STAGE_LABELS, usable(in_corpus, stage_set)),
                              STAGE_LABELS, want["stage"], used, twin_with_same_value("stage", FIELD_STAGE))

    agency_pool = [r for r in usable(in_corpus, agency_set) if not leaks_agency(r)]
    agencies = sorted({r.get(FIELD_AGENCY) for r in agency_pool})
    agency_groups = grouped(FIELD_AGENCY, agencies, agency_pool)
    agency_order = list(agencies)
    rng.shuffle(agency_order)
    agency_rows = _round_robin(agency_groups, agency_order, want["agency"], used,
                               twin_with_same_value("agency", FIELD_AGENCY))

    # Unanswerable, type 1: real use cases that are not in the corpus.
    corpus_names = [r.get(FIELD_USE_CASE) for r in corpus_members]
    corpus_token_sets = [name_tokens(n) for n in corpus_names]
    corpus_norms = [norm_name(n) for n in corpus_names]
    corpus_text = " | ".join(norm_name(_free_text(r)) for r in corpus_members)

    def far_from_corpus(row: Row) -> bool:
        """No corpus document has a similar name, and none mentions this name in its text."""
        tokens = name_tokens(row.get(FIELD_USE_CASE))
        norm = norm_name(row.get(FIELD_USE_CASE))
        if norm in corpus_text:
            return False
        for other_tokens, other_norm in zip(corpus_token_sets, corpus_norms):
            if not other_norm:
                continue
            if norm in other_norm or other_norm in norm:
                return False
            union = tokens | other_tokens
            if union and len(tokens & other_tokens) / len(union) >= HELDOUT_MAX_JACCARD:
                return False
        return True

    heldout_pool = [r for r in rows
                    if r.row_number not in corpus_row_numbers and is_eligible(r)
                    and good_name(r, all_counts) and not leaks_agency(r)
                    and not name_contains_value(r.get(FIELD_USE_CASE), agency_set)]
    rng.shuffle(heldout_pool)
    by_agency: dict[str, list[Row]] = defaultdict(list)
    for member in corpus_members:
        by_agency[member.get(FIELD_AGENCY)].append(member)

    def has_same_agency_twin(row: Row) -> bool:
        """A corpus document of the same agency with a similar name or nearly the same description."""
        name = row.get(FIELD_USE_CASE)
        for other in by_agency.get(row.get(FIELD_AGENCY), []):
            if name_similarity(name, other.get(FIELD_USE_CASE), HELDOUT_SAME_AGENCY_NAME_RATIO) \
                    >= HELDOUT_SAME_AGENCY_NAME_RATIO:
                return True
            if description_overlap(row, other) >= HELDOUT_SAME_AGENCY_TEXT_OVERLAP:
                return True
        return False

    heldout_rows: list[Row] = []
    for r in heldout_pool:
        if len(heldout_rows) >= want["unanswerable_heldout"]:
            break
        if not far_from_corpus(r):
            continue
        if has_same_agency_twin(r):
            excluded["unanswerable_heldout"].append(r.row_number)
            continue
        heldout_rows.append(r)

    # Unanswerable, type 2: attributes the inventory does not record.
    absent_pool = [r for r in in_corpus if r.row_number not in used]
    rng.shuffle(absent_pool)
    absent_items: list[tuple[Row, str, str]] = []
    template_index = 0
    for r in absent_pool:
        if len(absent_items) >= want["unanswerable_absent_field"]:
            break
        key, template, stems = ABSENT_FIELD_TEMPLATES[template_index % len(ABSENT_FIELD_TEMPLATES)]
        if any(stem in _free_text(r) for stem in stems):
            continue
        used.add(r.row_number)
        absent_items.append((r, key, template))
        template_index += 1

    items: list[dict] = []

    def add(kind: str, row: Row, question: str, expected: str, label_set: str | None,
            aliases: list[dict], fields: list[str], answerable: bool, extra: dict | None = None) -> None:
        item = {
            "id": f"q-{len(items) + 1:03d}",
            "type": kind,
            "answerable": answerable,
            "question": question,
            "use_case_name": row.get(FIELD_USE_CASE),
            "expected_answer": expected,
            "accepted_aliases": aliases,
            "label_set": label_set,
            "source_doc_id": row.doc_id if answerable else None,
            "source_row": row.row_number,
            "csv_fields": fields,
            # Corpus documents with a similar name and ANOTHER value of the asked field.
            # Read these rows first when a question of this kind is answered wrongly.
            "near_duplicate_doc_ids": ([other.doc_id for other in similar_documents(row)]
                                       if answerable else []),
        }
        item.update(extra or {})
        items.append(item)

    for r in agency_rows:
        add("agency", r, TEMPLATES["agency"].format(name=r.get(FIELD_USE_CASE)),
            r.get(FIELD_AGENCY), "agency",
            [{"text": r.get(FIELD_AGENCY_ABBR), "case_sensitive": True}],
            [FIELD_USE_CASE, FIELD_AGENCY, FIELD_AGENCY_ABBR], True)
    for r in stage_rows:
        add("stage", r,
            TEMPLATES["stage"].format(name=r.get(FIELD_USE_CASE), agency_name=r.get(FIELD_AGENCY)),
            r.get(FIELD_STAGE), "stage", [], [FIELD_USE_CASE, FIELD_AGENCY, FIELD_STAGE], True)
    for r in hi_rows:
        add("high_impact", r,
            TEMPLATES["high_impact"].format(name=r.get(FIELD_USE_CASE), agency_name=r.get(FIELD_AGENCY)),
            r.get(FIELD_HIGH_IMPACT), "high_impact", [],
            [FIELD_USE_CASE, FIELD_AGENCY, FIELD_HIGH_IMPACT], True)
    for r in heldout_rows:
        add("unanswerable_heldout", r, TEMPLATES["agency"].format(name=r.get(FIELD_USE_CASE)),
            NO_ANSWER, None, [], [FIELD_USE_CASE], False,
            {"why_unanswerable": "this CSV row was not put in the corpus"})
    for r, key, template in absent_items:
        add("unanswerable_absent_field", r,
            template.format(name=r.get(FIELD_USE_CASE), agency_name=r.get(FIELD_AGENCY)),
            NO_ANSWER, None, [], [FIELD_USE_CASE, FIELD_AGENCY], False,
            {"why_unanswerable": f"the inventory has no column for {key}", "related_doc_id": r.doc_id})

    got = Counter(i["type"] for i in items)
    shortfalls = {k: want[k] - got.get(k, 0) for k in want if got.get(k, 0) < want[k]}
    meta = {
        "seed": seed,
        "requested": want,
        "built": dict(got),
        "answerable": sum(1 for i in items if i["answerable"]),
        "unanswerable": sum(1 for i in items if not i["answerable"]),
        "total": len(items),
        "shortfalls": shortfalls,
        "expected_answer_counts": {
            kind: dict(Counter(i["expected_answer"] for i in items if i["type"] == kind))
            for kind in ("agency", "stage", "high_impact")
        },
        "near_duplicates": {
            "name_ratio_answerable": NEAR_DUPLICATE_NAME_RATIO,
            "name_ratio_heldout_same_agency": HELDOUT_SAME_AGENCY_NAME_RATIO,
            "text_overlap_heldout_same_agency": HELDOUT_SAME_AGENCY_TEXT_OVERLAP,
            "measure": "difflib.SequenceMatcher ratio of the lower-cased use case names; share of a row's "
                       "description words (4+ characters, problem and benefits) found in the other row",
            "excluded_rows": {kind: sorted(numbers) for kind, numbers in excluded.items()},
            # One row can be turned down for more than one question type, so the candidates above can
            # add up to more than the number of different rows.
            "excluded_rows_distinct": len({number for numbers in excluded.values() for number in numbers}),
            "flagged_questions": sum(1 for i in items if i["near_duplicate_doc_ids"]),
        },
        "label_sets": {"agency": agency_set, "stage": stage_set, "high_impact": high_impact_set},
        "no_answer_token": NO_ANSWER,
    }
    return items, meta
