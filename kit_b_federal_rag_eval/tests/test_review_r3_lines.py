"""Round 3 (rehearsal on real model text), defect 2: one row must stay one line.

What was wrong: 50_run_eval.py read raw.jsonl with str.splitlines(), which also splits on LINE
SEPARATOR (U+2028), PARAGRAPH SEPARATOR (U+2029), NEXT LINE (U+0085), VT, FF, FS, GS and RS, and
the rows were written with ensure_ascii=False, which writes three of those characters raw. One such
character in a model's answer, in a judge's reply or in a retrieved passage cut a row in two, and
the run stopped with a JSONDecodeError after the last question, when every call had been billed
and before the summary was written. --resume failed the same way. A lone surrogate, which Python's
JSON reader produces for an unpaired escape in a service response, stopped the run at the first
write instead.

The rule since round 3 (kitlib/jsonl.py): a row is written as one physical line whatever text it
holds, and a line-delimited file is split on the line feed and on nothing else.

Every odd character in this file is built with chr(), so that the file itself holds none of them.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json

import pytest

import fakeaws
from conftest import KIT_DIR
from kitlib import config, evalloop, scoring
from kitlib.evalloop import Passage
from test_evalloop import ITEMS, LABEL_SETS, SCRIPT, FakeBackend
from test_review_r1_eval import BILLS, write_build, write_state

# What str.splitlines() splits on besides the line feed, and three more characters that break
# other things: a NUL, and the two kinds of lone surrogate.
ODD = {
    "LINE SEPARATOR U+2028": chr(0x2028),
    "PARAGRAPH SEPARATOR U+2029": chr(0x2029),
    "NEXT LINE U+0085": chr(0x85),
    "VERTICAL TAB": chr(0x0B),
    "FORM FEED": chr(0x0C),
    "FILE SEPARATOR U+001C": chr(0x1C),
    "GROUP SEPARATOR U+001D": chr(0x1D),
    "RECORD SEPARATOR U+001E": chr(0x1E),
    "bare carriage return": "\r",
    "carriage return and line feed": "\r\n",
    "line feed": "\n",
    "NUL": chr(0),
    "lone high surrogate": chr(0xD800),
    "lone low surrogate": chr(0xDFFF),
}
SPLITTERS = [chr(c) for c in (0x0A, 0x0D, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029)]
# All of them in one text. A bar stands between them, because a high surrogate directly followed by a
# low one is not two lone surrogates: it is one character written in two halves, and JSON reads it as one.
ALL_ODD = "|".join(ODD.values())


def test_the_list_above_is_what_splitlines_splits_on():
    """Every character Python splits a line on is in SPLITTERS, found by trying all of them."""
    found = [chr(code) for code in range(0x110000) if len(("a" + chr(code) + "b").splitlines()) == 2]
    assert sorted(found) == sorted(SPLITTERS)
    assert all(ch in ALL_ODD for ch in SPLITTERS)


class OddBackend(FakeBackend):
    """The scripted fake backend, with one odd character put into the answers, the judge's replies or
    the passages. q-001 and q-005 keep a clean answer when the character is in the passage or in the
    judge's reply, so the table still has something to count."""
    where = "answer"
    char = ""
    judge_fail_on: set = set()
    calls = 0

    def __init__(self, *args, **kwargs):
        super().__init__()

    def retrieve(self, question):
        type(self).calls += 1
        passages = super().retrieve(question)
        if self.where != "passage":
            return passages
        return [Passage(text=f"text of {p.doc_id} first{self.char}second{self.char}", doc_id=p.doc_id, score=p.score)
                for p in passages]

    def generate(self, system, user):
        reply = super().generate(system, user)
        if self.where == "passage":
            assert self.char in user                           # the passage reached the generation prompt
        if self.where == "answer":
            reply["text"] = reply["text"][:8] + self.char + reply["text"][8:] + self.char
        return reply

    def judge(self, system, user):
        if self.current in type(self).judge_fail_on:
            self.log.append(("judge", self.current))
            raise RuntimeError("ModelErrorException: the model returned an error" + self.char)
        reply = super().judge(system, user)
        if self.where == "judge":
            word = json.loads(reply["text"])["verdict"]
            reply["text"] = '{"verdict": "%s", "reason": "first%ssecond"}%s' % (word, self.char, self.char)
        return reply


@pytest.fixture
def run_eval(monkeypatch, tmp_path):
    fakeaws.install(monkeypatch, fakeaws.World())
    spec = importlib.util.spec_from_file_location("run_eval_script_r3", KIT_DIR / "50_run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_build(tmp_path)
    write_state()
    OddBackend.where, OddBackend.char, OddBackend.judge_fail_on, OddBackend.calls = "answer", "", set(), 0
    monkeypatch.setattr(module.api, "BedrockBackend", OddBackend)
    return module


def the_run(tmp_path):
    runs = sorted((tmp_path / "results").iterdir())
    assert len(runs) == 1
    return runs[0]


def physical_lines(path) -> list[str]:
    """The lines of a file as the strictest reader sees them: every separator Python knows splits."""
    return path.read_bytes().decode("utf-8").splitlines()


def check_files(out_dir, rows_expected: int, questions: int = len(ITEMS)) -> list[dict]:
    """raw.jsonl and per_question.csv hold one row per physical line, and every file can be read."""
    raw_text = (out_dir / "raw.jsonl").read_bytes().decode("utf-8")       # strict UTF-8: no lone surrogate on disk
    assert raw_text.endswith("\n") and raw_text.count("\n") == rows_expected
    lines = physical_lines(out_dir / "raw.jsonl")
    assert len(lines) == rows_expected                                     # no other separator anywhere in a row
    rows = [json.loads(line) for line in lines]
    assert not any(ch in raw_text.replace("\n", "") for ch in SPLITTERS)
    assert chr(0) not in raw_text and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in raw_text)

    table = out_dir / "per_question.csv"
    assert len(physical_lines(table)) == 1 + questions                     # header and one line per question
    with table.open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == questions
    assert chr(0) not in table.read_text(encoding="utf-8")
    json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert "| Measure | Guardrail off | Guardrail on |" in (out_dir / "summary.md").read_text(encoding="utf-8")
    return rows


# --- the full run, one odd character at a time, in each of the three places ---------------------------------------

@pytest.mark.parametrize("where", ["answer", "judge", "passage"])
@pytest.mark.parametrize("name", sorted(ODD))
def test_a_run_reaches_its_summary_whatever_character_the_text_holds(run_eval, tmp_path, capsys, where, name):
    OddBackend.where, OddBackend.char = where, ODD[name]
    assert run_eval.main([BILLS]) == 0
    out_dir = the_run(tmp_path)
    rows = check_files(out_dir, rows_expected=len(ITEMS))
    assert "| Measure | Guardrail off | Guardrail on |" in capsys.readouterr().out   # the summary was printed
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is True and summary["questions_with_errors"] == 0
    assert summary["answerable_n"] == 4 and summary["unanswerable_n"] == 2

    # raw.jsonl holds the text exactly as the model or the service gave it, character for character
    first = rows[0]
    if where == "answer":
        clean = SCRIPT["q-001"]["answer"]
        assert first["answer"] == clean[:8] + ODD[name] + clean[8:] + ODD[name]
    elif where == "judge":
        assert first["judge_raw"] == '{"verdict": "CORRECT", "reason": "first%ssecond"}%s' % (ODD[name], ODD[name])
    else:
        assert first["retrieved_passages"][0]["text"] == f"text of uc-0001 first{ODD[name]}second{ODD[name]}"
        # a passage with an odd character changes nothing in the scores of this scripted run
        assert (first["exact"], first["judge_verdict"], first["hit_rank"]) == (True, "CORRECT", 1)

    # and the script's own reader gives back what was written
    latest, earlier = run_eval.read_attempts(out_dir / "raw.jsonl")
    assert latest == rows and earlier == []


@pytest.mark.parametrize("where", ["answer", "judge", "passage"])
def test_resume_works_with_every_odd_character_at_once(run_eval, tmp_path, capsys, where):
    OddBackend.where, OddBackend.char = where, ALL_ODD
    OddBackend.judge_fail_on = {"q-003"}
    assert run_eval.main([BILLS]) == 1                                     # one question failed: INCOMPLETE
    out_dir = the_run(tmp_path)
    check_files(out_dir, rows_expected=len(ITEMS))
    first_summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert first_summary["complete"] is False and first_summary["questions_with_errors"] == 1
    assert "INCOMPLETE" in capsys.readouterr().out

    OddBackend.judge_fail_on, OddBackend.calls = set(), 0
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert OddBackend.calls == 1                                           # only the failed question ran again
    rows = check_files(out_dir, rows_expected=len(ITEMS) + 1)              # every attempt is kept
    assert [row["id"] for row in rows].count("q-003") == 2
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is True and summary["questions_with_errors"] == 0
    assert summary["usage"]["earlier_failed_attempts_included"] == 1
    latest, earlier = run_eval.read_attempts(out_dir / "raw.jsonl")
    assert len(latest) == len(ITEMS) and len(earlier) == 1 and earlier[0]["error"]


def test_an_error_message_with_odd_characters_is_printed_and_kept(run_eval, tmp_path, capsys):
    """The failed call's message carries the characters; the progress line and the files survive it."""
    OddBackend.where, OddBackend.char = "judge", ALL_ODD
    OddBackend.judge_fail_on = {"q-001", "q-002", "q-003", "q-004", "q-005", "q-006"}
    assert run_eval.main([BILLS]) == 1
    rows = check_files(the_run(tmp_path), rows_expected=len(ITEMS))
    assert all(row["error"].startswith("RuntimeError: ModelErrorException") for row in rows)
    assert rows[0]["error"].endswith(ALL_ODD)                              # kept exactly in raw.jsonl
    out = capsys.readouterr().out
    progress = [line for line in out.split("\n") if line.lstrip().startswith("[")]
    assert len(progress) == len(ITEMS)                                     # one line on the screen per question
    assert not any(ch in line for line in progress for ch in SPLITTERS + [chr(0), chr(0xD800), chr(0xDFFF)])


# --- reading: the line feed and nothing else -------------------------------------------------------------------------

def old_style_line(row: dict) -> bytes:
    """A row as the kit wrote it before round 3: the three separators above U+007F are written raw."""
    return (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")


@pytest.mark.parametrize("name", ["LINE SEPARATOR U+2028", "PARAGRAPH SEPARATOR U+2029", "NEXT LINE U+0085"])
def test_a_file_written_before_round_3_is_read_back_whole(run_eval, tmp_path, name):
    rows = [{"id": "q-001", "answer": "first" + ODD[name] + "second", "error": None},
            {"id": "q-002", "answer": "plain", "error": None}]
    path = tmp_path / "raw.jsonl"
    path.write_bytes(b"".join(old_style_line(row) for row in rows))
    with pytest.raises(ValueError):                                        # the reader as it was: the defect
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest, earlier = run_eval.read_attempts(path)
    assert latest == rows and earlier == []


def test_carriage_returns_at_the_ends_of_lines_are_tolerated(run_eval, tmp_path):
    """A file that went through a Windows editor has CR LF line ends; the rows are still the rows."""
    path = tmp_path / "raw.jsonl"
    path.write_bytes(b'{"id": "q-001", "error": null}\r\n\r\n{"id": "q-002", "error": null}\r\n')
    latest, _ = run_eval.read_attempts(path)
    assert [row["id"] for row in latest] == ["q-001", "q-002"]
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())                 # and a byte order mark at the start
    assert [row["id"] for row in run_eval.read_attempts(path)[0]] == ["q-001", "q-002"]


def test_the_evaluation_set_is_read_by_line_feed_only(run_eval, tmp_path):
    """A question that holds a separator (written raw, as before round 3) is one question, not two halves."""
    items = [dict(item) for item in ITEMS]
    items[0]["question"] = 'Question 1 about "Use case 1"' + chr(0x2028) + chr(0x85) + "?"
    data = b"".join(old_style_line(item) for item in items)
    (tmp_path / "build" / "eval" / "eval_set.jsonl").write_bytes(data)
    loaded, _, _ = run_eval.load_eval_set(tmp_path / "build")
    assert loaded == items
    assert run_eval.main([BILLS]) == 0
    check_files(the_run(tmp_path), rows_expected=len(ITEMS))


def test_the_evaluation_set_is_written_one_question_per_line():
    from kitlib import jsonl
    item = dict(ITEMS[0], question="Which agency reported " + ALL_ODD + "?", use_case_name="Tool " + chr(0x2028))
    line = jsonl.dumps_line(item)
    assert line.endswith("\n") and len(line.splitlines()) == 1 and line.count("\n") == 1
    assert jsonl.loads_lines(line.encode("utf-8"), "eval_set.jsonl") == [item]
    source = (KIT_DIR / "20_build_eval_set.py").read_text(encoding="utf-8")
    assert "handle.write(jsonl.dumps_line(item))" in source and "handle.write(json.dumps(" not in source


def test_ordinary_text_is_written_exactly_as_before():
    """Nothing changes for a row without such a character, so eval_set.jsonl keeps its bytes and its SHA-256."""
    from kitlib import jsonl
    dash, accent, quote = chr(0x2013), chr(0xE9), chr(0x201C)
    for record in (ITEMS[0], {"id": "q-9", "question": f"Caf{accent} {dash} {quote}quoted{quote} \t tab", "n": [1, 2.5, None]}):
        assert jsonl.dumps_line(record) == json.dumps(record, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", sorted(ODD))
def test_one_record_is_one_line_and_comes_back_unchanged(name):
    from kitlib import jsonl
    record = {"id": "q-001", "answer": "first" + ODD[name] + "second", "passages": [{"text": ODD[name] * 3}],
              ODD[name] + "key": True}
    line = jsonl.dumps_line(record)
    assert line.endswith("\n") and line[:-1].splitlines() == [line[:-1]]
    line.encode("utf-8")                                                   # a lone surrogate would raise here
    assert json.loads(line) == record
    assert jsonl.loads_lines((line * 3).encode("utf-8"), "raw.jsonl") == [record] * 3


# --- a damaged raw.jsonl: said before any call, never after --------------------------------------------------------------

def test_a_row_cut_short_at_the_end_is_dropped_and_its_question_runs_again(run_eval, tmp_path, capsys):
    """The process was killed while it wrote the last row. --resume must not choke on the half row,
    and must not glue the next row to it. Since round 4 the calls of that question, which had all been
    answered, are counted: last_question_calls.json holds them, and --resume writes them to raw.jsonl as an
    attempt of their own (tests/test_review_r4_usage.py)."""
    assert run_eval.main([BILLS]) == 0
    out_dir = the_run(tmp_path)
    path = out_dir / "raw.jsonl"
    whole = path.read_bytes()
    lines = whole.split(b"\n")
    path.write_bytes(b"\n".join(lines[:5]) + b"\n" + lines[5][:40])        # five rows and the start of the sixth
    OddBackend.calls = 0
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 0
    assert OddBackend.calls == 1                                           # q-006 only
    assert "cut short" in capsys.readouterr().out
    latest, earlier = run_eval.read_attempts(path)
    assert [row["id"] for row in latest] == [item["id"] for item in ITEMS]
    assert [(row["id"], row["interrupted"], row["error"][:12]) for row in earlier] == [("q-006", True, "Interrupted:")]
    assert len(physical_lines(path)) == len(ITEMS) + 1                     # every line is a whole row again
    assert (out_dir / "raw_cut_off_row.txt").read_bytes() == lines[5][:40] + b"\n"   # the half row is kept aside
    assert json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))["complete"] is True


def test_a_row_cut_short_inside_a_character_is_dropped_too(run_eval, tmp_path):
    """Text is written as UTF-8, so the cut can fall between the bytes of one character."""
    accent = chr(0xE9).encode("utf-8")
    whole = b'{"id": "q-001", "error": null}\n'
    path = tmp_path / "raw.jsonl"
    path.write_bytes(whole + b'{"id": "q-002", "answer": "caf' + accent[:1])
    rows, cut_short = run_eval.read_rows(path)
    assert [row["id"] for row in rows] == ["q-001"] and cut_short is True
    path.write_bytes(whole + b'{"id": "q-002", "answer": "caf' + accent[:1] + b'"}\n' + whole)
    with pytest.raises(ValueError, match="line 2: not a complete JSON value .bytes that are not UTF-8."):
        run_eval.read_rows(path)                                           # not at the end: refused, with the line


def test_a_broken_row_in_the_middle_stops_resume_before_any_call(run_eval, tmp_path, capsys):
    assert run_eval.main([BILLS]) == 0
    out_dir = the_run(tmp_path)
    path = out_dir / "raw.jsonl"
    lines = path.read_bytes().split(b"\n")
    lines[2] = lines[2][:25]
    path.write_bytes(b"\n".join(lines))
    before = {p.name: p.read_bytes() for p in out_dir.iterdir()}
    OddBackend.calls = 0
    capsys.readouterr()
    assert run_eval.main([BILLS, "--resume", str(out_dir)]) == 1
    err = capsys.readouterr().err
    assert "Refusing to resume" in err and "line 3" in err and "raw.jsonl" in err
    assert "Nothing was sent to Bedrock" in err and "Traceback" not in err
    assert OddBackend.calls == 0
    assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == before


def test_a_damaged_evaluation_set_stops_the_run_before_any_call(run_eval, tmp_path, capsys):
    path = tmp_path / "build" / "eval" / "eval_set.jsonl"
    path.write_bytes(path.read_bytes()[:-30])
    assert run_eval.main([BILLS]) == 1
    err = capsys.readouterr().err
    assert "eval_set.jsonl" in err and "20_build_eval_set.py" in err and OddBackend.calls == 0
    assert not (tmp_path / "results").exists()


# --- per_question.csv: one question per physical line -------------------------------------------------------------------

def test_every_cell_of_the_csv_row_is_one_line():
    row = evalloop.evaluate_item(ITEMS[0], FakeBackend(), LABEL_SETS)
    row.update(answer="first" + ALL_ODD + "second", judge_note="note" + ALL_ODD, error="Boom: " + ALL_ODD,
               exact_unread=ALL_ODD, question="Question 1" + chr(0x2028) + "?", expected_answer="A" + chr(0x85) + "B")
    cells = evalloop.csv_row(row)
    for key, value in cells.items():
        if isinstance(value, str):
            assert len(value.splitlines()) <= 1, key
            assert chr(0) not in value and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value), key
            value.encode("utf-8")
    # what was taken out is still visible, as an escape a person can read
    assert "\\x00" in cells["error"] and "\\ud800" in cells["error"] and "\\u2028" in cells["error"]
    assert "\\n" in cells["error"] and "\\r" in cells["error"]
    assert cells["answer"].startswith("first") and cells["answer"].endswith("second")
    assert "\\x00" in cells["answer"] and "\\n" not in cells["answer"]     # white space collapsed, the rest shown
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=evalloop.CSV_COLUMNS)
    writer.writeheader()
    writer.writerow(cells)
    assert len(buffer.getvalue().splitlines()) == 2


def test_a_csv_row_without_odd_characters_is_unchanged():
    row = evalloop.evaluate_item(ITEMS[1], FakeBackend(), LABEL_SETS)
    row["answer"] = "The  stage of\tdevelopment\nis Pilot."
    cells = evalloop.csv_row(row)
    assert cells["answer"] == "The stage of development is Pilot."        # white space collapsed, as before
    assert cells["question"] == ITEMS[1]["question"] and cells["retrieved_doc_ids"] == "uc-0007 uc-0002"


def test_no_script_splits_a_data_file_with_splitlines():
    """The only splitlines() left in the kit reads config.env, which you write yourself."""
    import tokenize
    users = []
    for path in sorted(list(KIT_DIR.glob("*.py")) + list((KIT_DIR / "kitlib").glob("*.py"))):
        with path.open("rb") as handle:                                    # code only: no comment, no docstring
            names = {token.string for token in tokenize.tokenize(handle.readline) if token.type == tokenize.NAME}
        if "splitlines" in names or "readlines" in names:
            users.append(path.name)
    assert users == ["config.py"]
    assert "json.loads(line) for line in" not in (KIT_DIR / "50_run_eval.py").read_text(encoding="utf-8")


def test_the_scoring_survives_the_same_characters():
    """Exact match and the judge reader are given the odd characters directly: no exception, no credit."""
    for name, char in ODD.items():
        item = ITEMS[0]
        exact = scoring.score_exact(item, "The Department" + char + " of Energy." + char, LABEL_SETS)
        assert exact["exact"] in (True, False), name
        reading = scoring.read_judge('{"verdict": "CORRECT", "reason": "a' + char + 'b"}' + char, item,
                                     "The Department of Energy." + char, LABEL_SETS)
        assert reading["verdict"] in scoring.VERDICTS + (scoring.UNPARSEABLE,), name
