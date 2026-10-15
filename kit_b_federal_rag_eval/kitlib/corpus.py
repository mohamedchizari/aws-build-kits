"""Turn the OMB inventory CSV into small text documents with metadata sidecars.

Pure functions, no network and no AWS. `10_build_corpus.py` does the download
and the file writing.

Metadata sidecar format (one `<file>.metadata.json` beside each document, at
most 10 KB):
DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html (read 2026-10-07)
DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-s3.html (read 2026-10-07)
Both pages show the typed form
    {"metadataAttributes": {"key": {"value": {"type": "STRING", "stringValue": "..."}}}}
and the first page also shows the simple form {"metadataAttributes": {"key": "value"}}.
The typed form is the default here because it is on both pages.
UNVERIFIED: that a customer-managed knowledge base accepts the typed form WITHOUT the
"includeForEmbedding" field (every typed example on the first page carries it; the
managed page's example does not). If ingestion reports metadata errors with
KB_TYPE=s3vectors, rebuild with `10_build_corpus.py --metadata-format simple`.
Chunking is left at the service default. For a managed knowledge base that default is
documented: "If you omit this configuration or specify the default chunking strategy, the
service uses fixed-size chunking with 300 tokens and 20% overlap."
DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html (read 2026-10-07)
UNVERIFIED: how many chunks one of these documents (about 900 characters) becomes in practice,
on either knowledge base type. Documents are kept short and put the checkable facts first so
that a split should not separate a fact from the use case name.

Contact details. The CSV has a contact_email column, which is never read. One free-text cell
of the pinned CSV also holds an e-mail address (row 1396, problem_solved). Every cell that is
read passes through scrub(), which replaces e-mail addresses and phone-shaped strings with a
marker, and build_corpus() refuses to return a file in which either can still be found.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import unicodedata
from dataclasses import dataclass

# E-mail addresses and phone-shaped strings are replaced in every cell that is read.
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# Ten-digit North American forms, with or without a leading +1 or 1: (202) 555-0123, 202-555-0123,
# 202.555.0123, 202 555 0123; and numbers written with a + country code.
PHONE_PATTERN = re.compile(
    r"(?<![\w.])(?:\+?1[\s.\-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.\-])\d{3}[\s.\-]\d{4}(?!\w)"
    r"|(?<![\w.])\+\d{1,3}[\s.\-]?\d[\d\s.\-]{6,14}\d(?!\w)")
EMAIL_REMOVED = "[e-mail address removed]"
PHONE_REMOVED = "[phone number removed]"


def scrub(text: str) -> str:
    """Replace e-mail addresses and phone-shaped strings with a marker."""
    return PHONE_PATTERN.sub(PHONE_REMOVED, EMAIL_PATTERN.sub(EMAIL_REMOVED, text))


def has_contact_details(text: str) -> bool:
    return bool(EMAIL_PATTERN.search(text) or PHONE_PATTERN.search(text))


# Columns read from the CSV. contact_email is deliberately NOT used anywhere.
FIELD_USE_CASE = "use_case_name"
FIELD_AGENCY_ABBR = "agency"
FIELD_AGENCY = "agency_name"
FIELD_BUREAU = "agency_bureau"
FIELD_STAGE = "development_stage"
FIELD_HIGH_IMPACT = "is_high_impact"
FIELD_TOPIC = "topic_area"
FIELD_CLASS = "classification"
FIELD_PROBLEM = "problem_solved"
FIELD_BENEFITS = "benefits"
FIELD_OUTPUTS = "system_outputs"

REQUIRED_COLUMNS = (
    FIELD_USE_CASE, FIELD_AGENCY_ABBR, FIELD_AGENCY, FIELD_BUREAU, FIELD_STAGE,
    FIELD_HIGH_IMPACT, FIELD_TOPIC, FIELD_CLASS, FIELD_PROBLEM, FIELD_BENEFITS, FIELD_OUTPUTS,
)

# Free-text fields are cut so a whole document stays near 300 tokens, the
# default chunk size, and the checkable facts sit at the top of the file.
FREE_TEXT_LIMITS = {FIELD_PROBLEM: 400, FIELD_BENEFITS: 250, FIELD_OUTPUTS: 150}
NOT_REPORTED = "Not reported"
TRUNCATED = " [truncated]"

# Limits the sidecar must respect.
SIDECAR_MAX_BYTES = 10 * 1024          # per metadata file (both S3 connector pages)
S3_VECTORS_METADATA_MAX_BYTES = 1024   # custom metadata per vector with S3 Vectors
S3_VECTORS_METADATA_MAX_KEYS = 35
# DOC: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html (read 2026-10-07)


@dataclass(frozen=True)
class Row:
    """One CSV row plus its position. row_number is 1-based, header excluded."""
    row_number: int
    fields: dict

    @property
    def doc_id(self) -> str:
        return f"uc-{self.row_number:04d}"

    def get(self, name: str) -> str:
        """One cell: whitespace collapsed, e-mail addresses and phone-shaped strings replaced."""
        return scrub(clean(self.fields.get(name, "")))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(files: dict[str, bytes | str]) -> str:
    """One SHA-256 over the names and contents of a set of corpus files, in name order.

    The builder puts it in the manifest, the deploy step recomputes it from the files it
    uploads, and the evaluation refuses to run when the two differ.
    """
    digest = hashlib.sha256()
    for name in sorted(files):
        content = files[name]
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest.update(name.encode("utf-8") + b"\0" + sha256_bytes(data).encode("ascii") + b"\n")
    return digest.hexdigest()


def clean(value: str | None) -> str:
    """Collapse all whitespace (the CSV has newlines inside cells) and strip."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value))).strip()


def parse_csv(data: bytes) -> list[Row]:
    """Parse the inventory CSV. The data dictionary says the file is UTF-8 with a BOM."""
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"CSV is missing expected columns: {missing}")
    return [Row(i, dict(r)) for i, r in enumerate(reader, start=1)]


def is_eligible(row: Row) -> bool:
    """A row can become a document if it has a name and an agency."""
    return bool(row.get(FIELD_USE_CASE)) and bool(row.get(FIELD_AGENCY))


def select_rows(rows: list[Row], sample_size: int, seed: int) -> list[Row]:
    """Deterministic sample of eligible rows. sample_size <= 0 means all of them."""
    eligible = [r for r in rows if is_eligible(r)]
    if sample_size <= 0 or sample_size >= len(eligible):
        return eligible
    chosen = random.Random(seed).sample(eligible, sample_size)
    return sorted(chosen, key=lambda r: r.row_number)


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + TRUNCATED


def render_document(row: Row, commit: str) -> str:
    """Plain text for one use case. Checkable facts first, free text after."""
    def val(name: str) -> str:
        return row.get(name) or NOT_REPORTED

    def free(name: str) -> str:
        text = row.get(name)
        return _cut(text, FREE_TEXT_LIMITS[name]) if text else NOT_REPORTED

    lines = [
        "Federal AI use case inventory record (OMB 2025 consolidated inventory)",
        f"Document ID: {row.doc_id}",
        f"Use case name: {val(FIELD_USE_CASE)}",
        f"Agency: {val(FIELD_AGENCY)} ({val(FIELD_AGENCY_ABBR)})",
        f"Bureau or component: {val(FIELD_BUREAU)}",
        f"Stage of development: {val(FIELD_STAGE)}",
        f"High-impact determination: {val(FIELD_HIGH_IMPACT)}",
        f"Topic area: {val(FIELD_TOPIC)}",
        f"AI classification: {val(FIELD_CLASS)}",
        f"Problem to be solved: {free(FIELD_PROBLEM)}",
        f"Expected benefits: {free(FIELD_BENEFITS)}",
        f"System outputs: {free(FIELD_OUTPUTS)}",
        f"Source: OMB 2025 Federal Agency AI Use Case Inventory, commit {commit[:12]}, CSV row {row.row_number}",
    ]
    return "\n".join(lines) + "\n"


def metadata_attributes(row: Row) -> dict[str, str]:
    """Short, filterable attributes. Kept far below the S3 Vectors 1 KB limit."""
    attrs = {
        "doc_id": row.doc_id,
        "agency": row.get(FIELD_AGENCY_ABBR),
        "agency_name": row.get(FIELD_AGENCY),
        "development_stage": row.get(FIELD_STAGE) or NOT_REPORTED,
        "is_high_impact": row.get(FIELD_HIGH_IMPACT) or NOT_REPORTED,
        "topic_area": row.get(FIELD_TOPIC) or NOT_REPORTED,
        "classification": row.get(FIELD_CLASS) or NOT_REPORTED,
    }
    return {k: _cut(v, 120) for k, v in attrs.items()}


def render_sidecar(row: Row, metadata_format: str = "typed") -> str:
    attrs = metadata_attributes(row)
    if metadata_format == "typed":
        body = {"metadataAttributes": {
            k: {"value": {"type": "STRING", "stringValue": v}} for k, v in attrs.items()}}
    elif metadata_format == "simple":
        body = {"metadataAttributes": attrs}
    else:
        raise ValueError("metadata_format must be 'typed' or 'simple'")
    text = json.dumps(body, ensure_ascii=False, indent=1) + "\n"
    check_sidecar_limits(attrs, text)
    return text


def check_sidecar_limits(attrs: dict[str, str], sidecar_text: str) -> None:
    if len(sidecar_text.encode("utf-8")) > SIDECAR_MAX_BYTES:
        raise ValueError("metadata sidecar is larger than 10 KB")
    if len(attrs) > S3_VECTORS_METADATA_MAX_KEYS:
        raise ValueError("more than 35 metadata keys")
    payload = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in attrs.items())
    if payload > S3_VECTORS_METADATA_MAX_BYTES:
        raise ValueError("metadata keys and values exceed 1 KB (S3 Vectors limit)")


def document_filename(doc_id: str) -> str:
    return f"{doc_id}.txt"


def sidecar_filename(doc_id: str) -> str:
    return f"{doc_id}.txt.metadata.json"


def doc_id_from_uri(uri: str) -> str | None:
    """'s3://bucket/corpus/uc-0042.txt' -> 'uc-0042'. None if it is not one of ours."""
    match = re.search(r"(?<![A-Za-z0-9])(uc-\d{4,})\.txt$", uri or "")
    return match.group(1) if match else None


def is_doc_id(value: str) -> bool:
    return bool(re.fullmatch(r"uc-\d{4,}", value or ""))


def build_corpus(rows: list[Row], sample_size: int, seed: int, commit: str,
                 metadata_format: str = "typed") -> tuple[dict[str, str], dict]:
    """Return ({filename: content}, manifest). Writes nothing."""
    chosen = select_rows(rows, sample_size, seed)
    files: dict[str, str] = {}
    docs = []
    for row in chosen:
        text = render_document(row, commit)
        files[document_filename(row.doc_id)] = text
        files[sidecar_filename(row.doc_id)] = render_sidecar(row, metadata_format)
        docs.append({"doc_id": row.doc_id, "row_number": row.row_number, "chars": len(text)})
    leaking = sorted(name for name, content in files.items() if has_contact_details(content))
    if leaking:
        raise ValueError(f"{len(leaking)} file(s) still hold an e-mail address or a phone-shaped string after "
                         f"scrubbing (first: {leaking[0]}). Nothing is written. This is a bug in kitlib/corpus.py.")
    total_chars = sum(d["chars"] for d in docs)
    manifest = {
        "source_repo": "",  # filled in by the caller
        "commit": commit,
        "seed": seed,
        "sample_size_requested": sample_size,
        "csv_rows": len(rows),
        "eligible_rows": sum(1 for r in rows if is_eligible(r)),
        "documents": len(docs),
        "metadata_format": metadata_format,
        "total_document_chars": total_chars,
        "mean_document_chars": round(total_chars / len(docs), 1) if docs else 0,
        "max_document_chars": max((d["chars"] for d in docs), default=0),
        "corpus_fingerprint": fingerprint(files),
        "contact_details_replaced": {
            "e_mail_addresses": sum(content.count(EMAIL_REMOVED) for name, content in files.items()
                                    if name.endswith(".txt")),
            "phone_shaped_strings": sum(content.count(PHONE_REMOVED) for name, content in files.items()
                                        if name.endswith(".txt")),
        },
        "docs": docs,
    }
    return files, manifest
