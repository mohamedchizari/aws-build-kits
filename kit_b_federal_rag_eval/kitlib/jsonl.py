"""Line-delimited files: one record, one physical line, whatever text the record holds.

Two files of this kit are line-delimited JSON: build/eval/eval_set.jsonl and
results/run-.../raw.jsonl. raw.jsonl holds text the kit did not write: the model's answer, the
judge's reply and the retrieved passages. The rehearsal on real model text (README section 8)
found that a run could stop after its last question, with every call billed and no summary
written, because one of those texts held a character that Python's str.splitlines() treats as
the end of a line. The rule since then:

  * writing (dumps_line): json.dumps escapes the line feed, the carriage return and every other
    character below U+0020. The characters it would write raw and that some reader takes for a
    line end or cannot store are escaped here as well: DEL and the C1 controls (U+007F to
    U+009F, which include NEXT LINE U+0085), LINE SEPARATOR U+2028, PARAGRAPH SEPARATOR U+2029,
    and a lone surrogate (U+D800 to U+DFFF), which UTF-8 cannot encode at all. Every other
    character is written as it is, so a row without such a character is byte for byte what it
    was before, and json.loads gives back exactly the text that went in;
  * reading (loads_lines): the bytes are split on the line feed and on nothing else. A file
    written before this rule, with one of those characters raw inside a row, is read whole.

one_line() is for a cell of per_question.csv and for a line on the screen, where an escape a
person can see is wanted instead of the character.
"""
from __future__ import annotations

import json
import re

# Characters that are legal inside a JSON string but must not be written raw into a line.
# Built with chr() so that this file holds none of them.
_ESCAPE_IN_A_LINE = re.compile("[" + chr(0x7F) + "-" + chr(0x9F) + chr(0x2028) + chr(0x2029)
                               + chr(0xD800) + "-" + chr(0xDFFF) + "]")
# For one_line(): the same, and every character below U+0020 except the tab (line feed, carriage
# return, NUL, ...).
_NOT_IN_A_CELL = re.compile("[" + chr(0) + "-" + chr(8) + chr(0xA) + "-" + chr(0x1F) + chr(0x7F) + "-" + chr(0x9F)
                            + chr(0x2028) + chr(0x2029) + chr(0xD800) + "-" + chr(0xDFFF) + "]")
_SHORT = {"\n": "\\n", "\r": "\\r"}


def _escape(match: re.Match) -> str:
    return "\\u%04x" % ord(match.group())


def dumps_line(record) -> str:
    """One record as one physical line that ends in a line feed. See the module docstring.

    A value JSON has no form for (it should not occur) is written as its text, not raised:
    a row that cannot be written would be a question that was billed and lost.
    """
    return _ESCAPE_IN_A_LINE.sub(_escape, json.dumps(record, ensure_ascii=False, default=str)) + "\n"


class BadLine(ValueError):
    """A line of a line-delimited file is not a JSON value. `line` is its 1-based number,
    `last` says whether it is the last line and has no line feed after it (a row cut short)."""

    def __init__(self, where: str, line: int, last: bool, reason: str):
        super().__init__(f"{where}, line {line}: not a complete JSON value ({reason})")
        self.where, self.line, self.last = where, line, last


def loads_lines(data: bytes, where: str, drop_cut_off_tail: bool = False) -> list:
    """The records of a line-delimited JSON file, split on the line feed ONLY.

    Blank lines are skipped; a carriage return before the line feed and a byte order mark at the
    start of the file (both left by some editors) are tolerated. A line that is not JSON raises
    BadLine with the file name and the line number. With drop_cut_off_tail a
    last line that has no line feed after it and is not JSON is left out instead (the process was
    stopped while it wrote that row); nothing else is ever left out.
    """
    # The bytes are split first and decoded line by line: the byte 0x0A is never part of a longer
    # UTF-8 character, and a row cut short may end in the middle of one.
    pieces = data.split(b"\n")
    if pieces[0].startswith(b"\xef\xbb\xbf"):
        pieces[0] = pieces[0][3:]
    records = []
    for number, piece in enumerate(pieces, start=1):
        if not piece.strip():
            continue
        try:
            records.append(json.loads(piece.decode("utf-8")))
        except ValueError as exc:                              # not JSON, or bytes that are not UTF-8
            last = number == len(pieces)
            if last and drop_cut_off_tail:
                continue
            reason = "bytes that are not UTF-8" if isinstance(exc, UnicodeDecodeError) else str(exc)[:80]
            raise BadLine(where, number, last, reason) from None
    return records


def ends_in_a_cut_off_line(data: bytes) -> bool:
    """True when the file's last line has no line feed after it and is not a JSON value."""
    tail = data.rsplit(b"\n", 1)[-1]
    if not tail.strip():
        return False
    try:
        json.loads(tail.decode("utf-8"))
    except ValueError:
        return True
    return False


def one_line(text) -> str:
    """Text for one cell or one line on the screen: no character that ends a line, no NUL, no lone
    surrogate. Each is replaced by an escape a person can read ("\\n", "\\x00", "\\u2028")."""
    def visible(match: re.Match) -> str:
        ch = match.group()
        if ch in _SHORT:
            return _SHORT[ch]
        return ("\\x%02x" if ord(ch) < 0x100 else "\\u%04x") % ord(ch)
    return _NOT_IN_A_CELL.sub(visible, str(text))
