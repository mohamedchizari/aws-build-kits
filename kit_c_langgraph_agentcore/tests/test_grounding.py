"""Review finding B1 (round 1): an invented document must not reach the reader unwarned.

The rule under test (agent/graph.py, finalize), as it stands after round 2:

  replace the model's text with fixed text when no tool result supports it at all
      - no tool was called
      - every search came back empty (fixed text, then the searches as they were sent)
      - every lookup failed
  otherwise show the block that code builds from the tool results, then a plain WARNING,
  then the model's text under its label, when
      - it cites a document number or an "NN FR NNNN" citation no tool returned
      - a tool failed but other tool results exist
      - it names none of the documents the tools returned
      (round 2 added numbers, dates, URLs and counts: tests/test_r2_answer_check.py)

The eight cases the round 1 reviewer ran are numbered R1 to R8. Offline: scripted model,
recorded or canned Federal Register responses.
"""
from __future__ import annotations

import datetime as dt
import io
import json

import pytest
from botocore.response import StreamingBody
from conftest import ACCOUNT, RUNTIME_ARN, RUNTIME_ID, CannedSession, ReplaySession, load_fixture, load_script, make_aws
from langchain_core.messages import AIMessage

from agent import graph as g
from agent.fake_model import ScriptedChatModel, tool_call

TODAY = dt.date(2026, 10, 7)
REAL = "2026-19964"       # returned by the recorded search and by the recorded document lookup
REAL_2 = "2026-19071"     # returned by the recorded search
REAL_CITATION = "91 FR 61988"  # returned by the recorded document lookup only


def _search_args(fixture: str) -> dict:
    params = load_fixture(fixture)["request"]["params"]
    get = lambda key: next(v for k, v in params if k == key)  # noqa: E731
    return {"term": get("conditions[term]"), "doc_type": get("conditions[type][]"),
            "date_from": get("conditions[publication_date][gte]"),
            "date_to": get("conditions[publication_date][lte]"), "limit": int(get("per_page"))}


SEARCH = tool_call("search_federal_register", _search_args("search_ai_rules.json"))
EMPTY_SEARCH = tool_call("search_federal_register", _search_args("search_no_results.json"))
LOOKUP = tool_call("get_federal_register_document", {"document_number": REAL})


def ask(responses, *fixtures, session=None):
    session = session or ReplaySession(*fixtures)
    model = ScriptedChatModel(responses=list(responses))
    graph = g.build_graph(model, g.build_tools(session=session, today=TODAY))
    return g.run_question(graph, "What final rules about energy storage were published?", today=TODAY)


def leads_with_warning(out) -> bool:
    """A WARNING stands in front of the model's text (and after the code-built block)."""
    if not out["warnings"] or out["model_summary"] is None:
        return False
    answer = out["answer"]
    return (answer.startswith(out["block"]) and out["warnings"][0].startswith("WARNING:")
            and answer.index(out["warnings"][0]) < answer.index(g.SUMMARY_LABEL))


# ------------------------------------------------------------------ the reviewer's eight cases
def test_R1_no_tool_call_invented_document_with_a_number_is_withheld():
    invented = ("The Department of Energy published 'Grid Storage Incentive Rule' (2026-18888), "
                "https://www.federalregister.gov/d/2026-18888.")
    out = ask([AIMessage(content=invented)])
    assert out["tool_calls"] == []
    assert out["answer"] == g.REFUSAL_NO_TOOL
    assert "Grid Storage" not in out["answer"] and "2026-18888" not in out["answer"]
    assert out["answer_replaced"] is True and out["withheld_answer"] == invented
    assert out["unverified_document_numbers"] == ["2026-18888"]
    assert out["grounding"] == "replaced" and "no_tool_called" in out["grounding_reasons"]


def test_R2_no_tool_call_invented_document_cited_as_91_FR_is_withheld():
    out = ask([AIMessage(content="The Department of Energy published the final rule 'Grid Storage "
                                 "Incentive Rule' on September 30, 2026 (91 FR 55123).")])
    assert out["answer"] == g.REFUSAL_NO_TOOL
    assert out["unverified_document_numbers"] == ["91 FR 55123"]


def test_R3_empty_search_and_an_invented_title_becomes_exactly_the_no_results_sentence():
    out = ask([EMPTY_SEARCH, AIMessage(content="DOE published the final rule 'Grid Storage Incentive "
                                               "Rule' on September 30, 2026.")],
              "search_no_results.json")
    assert out["no_results"] is True
    assert out["answer"].startswith(g.NO_RESULTS_TEXT)  # fixed text, then only the searches as sent
    assert out["answer"] == g.NO_RESULTS_TEXT + "\n" + out["block"] and "Grid Storage" not in out["answer"]
    assert out["answer_replaced"] is True and "Grid Storage" in out["withheld_answer"]


def test_R4_empty_search_and_an_invented_number_becomes_exactly_the_no_results_sentence():
    out = ask([EMPTY_SEARCH, AIMessage(content="DOE published 'Grid Storage Incentive Rule' "
                                               "(FR Doc. 2026-18888).")], "search_no_results.json")
    assert out["answer"].startswith(g.NO_RESULTS_TEXT) and "2026-18888" not in out["answer"]
    assert out["unverified_document_numbers"] == ["2026-18888"]


def test_R5_real_search_plus_invented_numbers_in_other_spellings_gets_a_leading_warning():
    answer = (f"1. SAFE Vehicles Rule III ({REAL}). 2. 'Battery Safety Standards' (FR Doc. 2026\u201318889). "
              "3. 'Old storage rule' (06-4321). 4. e9-31418. 5. 2010-1999.")
    out = ask([SEARCH, AIMessage(content=answer)], "search_ai_rules.json")
    assert out["unverified_document_numbers"] == ["06-4321", "2010-1999", "2026-18889", "E9-31418"]
    assert leads_with_warning(out)
    for number in ("06-4321", "2010-1999", "2026-18889", "E9-31418"):
        assert number in out["warnings"][0]
    # the answer is kept, after the warning (and before the warning repeated at the end)
    assert out["answer"].index(out["warnings"][0]) < out["answer"].index(answer)
    # since the acceptance run of round 2 the two quoted titles that no tool returned are listed too
    assert out["unverified_quotes"] == ["Battery Safety Standards", "Old storage rule"]
    assert [c["document_number"] for c in out["citations"]] == [REAL]
    assert out["grounding"] == "warned" and out["answer_replaced"] is False


def test_R6_known_limit_a_real_number_with_an_invented_title_and_agency_is_not_caught():
    """The checks compare numbers, dates, URLs, counts and phrases in quotation marks. They do
    not read titles or agencies written without quotation marks. This test pins that limit so
    nobody mistakes the check for more than it is (README section 7). Since round 2 an invented
    date next to the real number is caught, an invented title in quotation marks is caught, and
    the block in front of the model's text shows the real title and agency of the document."""
    quoted = f"The Environmental Protection Agency published 'Ban on Home Batteries' (document {REAL})."
    warned = ask([SEARCH, AIMessage(content=quoted)], "search_ai_rules.json")
    assert warned["grounding"] == "warned" and warned["unverified_quotes"] == ["Ban on Home Batteries"]
    answer = quoted.replace("'", "")
    out = ask([SEARCH, AIMessage(content=answer)], "search_ai_rules.json")
    assert out["model_summary"] == answer and out["grounding"] == "ok" and out["warnings"] == []
    assert out["unverified_document_numbers"] == []
    block = out["block"]
    assert block.index("National Highway Traffic Safety Administration") < out["answer"].index("Ban on Home Batteries")
    dated = ask([SEARCH, AIMessage(content=answer.replace("(document", "on 2026-09-15 (document"))],
                "search_ai_rules.json")
    assert dated["unverified_dates"] == ["2026-09-15"] and leads_with_warning(dated)


def test_R7_a_lookup_that_returns_404_and_a_model_that_cites_the_number_anyway_is_withheld():
    out = ask([tool_call("get_federal_register_document", {"document_number": "0000-00000"}),
               AIMessage(content="Document 0000-00000 is a final rule on storage.")],
              "document_not_found.json")
    assert out["answer"].startswith(g.REFUSAL_TOOL_FAILED)
    assert "final rule on storage" not in out["answer"]
    assert out["unverified_document_numbers"] == ["0000-00000"]
    assert out["tool_errors"] and out["tool_errors"][0].startswith("not_found")
    assert "tool_failed" in out["grounding_reasons"]


def test_R8_a_search_that_fails_with_http_500_and_an_answer_from_memory_is_withheld():
    session = CannedSession({"/documents.json": (500, None)})
    out = ask([SEARCH, AIMessage(content="DOE published the final rule 'Grid Storage Incentive Rule' last month.")],
              session=session)
    assert out["answer"].startswith(g.REFUSAL_TOOL_FAILED)
    assert "Grid Storage" not in out["answer"]
    assert "HTTP 500" in out["answer"]  # what failed is said in plain words
    assert out["grounding"] == "replaced"


# ------------------------------------------------------------------ further cases
@pytest.mark.parametrize("spelling", [
    "2026-18889",            # plain
    "2026\u201318889",       # en dash
    "2026\u201418889",       # em dash
    "2026\u201118889",       # non-breaking hyphen
    "2026\u221218889",       # minus sign
    "2026 - 18889",          # spaces around the hyphen
    "2026 \u2013 18889",     # spaces around an en dash
    "2026-\u200b18889",      # zero-width space
    "\uff12\uff10\uff12\uff16-18889",  # full-width digits
    "FR Doc. 2026-18889.",
    "https://www.federalregister.gov/d/2026-18889",
    "https://www.federalregister.gov/documents/2026/10/01/2026-18889/battery-safety",
])
def test_every_spelling_of_an_unreturned_number_is_found(spelling):
    assert g.find_document_numbers(f"See {spelling} for details") == {"2026-18889"}
    out = ask([SEARCH, AIMessage(content=f"SAFE rule {REAL}. Also see {spelling}")], "search_ai_rules.json")
    assert out["unverified_document_numbers"] == ["2026-18889"]
    assert leads_with_warning(out)


@pytest.mark.parametrize("text, expected", [
    ("e9-31418", {"E9-31418"}), ("E9\u201331418", {"E9-31418"}), ("c1-2026-12345", {"C1-2026-12345"}),
    ("R1-2024-10001", {"R1-2024-10001"}), ("Z7-12345", {"Z7-12345"}),
    ("06-4321", {"06-4321"}), ("99-12345", {"99-12345"}), ("2010-1999", {"2010-1999"}),
    ("Docket No. FAA-2026-1234", set()),  # the tail of a docket id is not a document number (round 2, F5)
    ("2026-19964-2", set()), ("final rule 2025-0491", {"2025-0491"}),
    ("model years 2027-2031", set()), ("fiscal years 2024 \u2013 2026", set()),
    ("published 2026-09-15", set()), ("call 202-555-0100", set()), ("ZIP 20230-0001", set()),
    ("42 U.S.C. 7401-7671q", set()), ("10-15 minutes", set()), ("Public Law 117-58", set()),
])
def test_document_number_forms(text, expected):
    assert g.find_document_numbers(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("91 FR 55123", {"91 FR 55123"}), ("91 fr 55123", {"91 FR 55123"}), ("91 F.R. 55123", {"91 FR 55123"}),
    ("91 Fed. Reg. 55,123", {"91 FR 55123"}), ("91 Federal Register 55123", {"91 FR 55123"}),
    ("91\u00a0FR\u00a055123", {"91 FR 55123"}), ("91FR55123", {"91 FR 55123"}),
    ("40 CFR 60", set()), ("49 CFR part 523", set()),
])
def test_fr_citation_forms(text, expected):
    assert g.find_fr_citations(text) == expected


def test_a_citation_returned_by_a_tool_is_verified_in_any_spelling_and_another_page_is_not():
    good = ask([LOOKUP, AIMessage(content=f"{REAL} was published at 91 Fed. Reg. 61,988.")], "document_detail.json")
    assert good["unverified_document_numbers"] == [] and good["grounding"] == "ok"
    bad = ask([LOOKUP, AIMessage(content=f"{REAL} was published at 91 FR 61999.")], "document_detail.json")
    assert bad["unverified_document_numbers"] == ["91 FR 61999"] and leads_with_warning(bad)


def test_a_citation_no_tool_returned_is_unverified_even_after_a_real_search():
    """The search tool does not return citations, so the model cannot know one from a search alone."""
    out = ask([SEARCH, AIMessage(content=f"{REAL} ({REAL_CITATION})")], "search_ai_rules.json")
    assert out["unverified_document_numbers"] == [REAL_CITATION] and leads_with_warning(out)


def test_a_number_the_model_only_typed_into_its_own_search_is_not_treated_as_returned():
    """The tool echoes the query. A number in the echo was written by the model, not by the Register."""
    args = dict(_search_args("search_ai_rules.json"))
    session = ReplaySession("search_ai_rules.json", ignore_params=True)
    args["term"] = "2026-18888"
    out = ask([tool_call("search_federal_register", args), AIMessage(content=f"{REAL} and 2026-18888.")],
              session=session)
    assert out["unverified_document_numbers"] == ["2026-18888"] and leads_with_warning(out)


def test_numbers_inside_what_the_tools_returned_are_not_flagged():
    """A docket id from the document lookup and a year range from a title are not inventions."""
    out = ask([LOOKUP, AIMessage(content=f"{REAL}, docket NHTSA-2025-0491, covers model years 2022-2031.")],
              "document_detail.json")
    assert out["unverified_document_numbers"] == [] and out["grounding"] == "ok"


def test_a_grounded_answer_is_kept_whole_after_the_block_with_no_warning():
    answer = f"Two final rules matched: {REAL} and {REAL_2}."
    out = ask([SEARCH, AIMessage(content=answer)], "search_ai_rules.json")
    assert out["model_summary"] == answer and out["warnings"] == [] and out["grounding"] == "ok"
    assert out["answer"] == out["block"] + "\n\n" + g.SUMMARY_LABEL + "\n" + answer
    assert out["answer_replaced"] is False and out["withheld_answer"] is None


def test_real_documents_but_an_answer_that_names_none_of_them_gets_a_leading_warning():
    answer = "DOE published the final rule 'Grid Storage Incentive Rule' last month."
    out = ask([SEARCH, AIMessage(content=answer)], "search_ai_rules.json")
    assert leads_with_warning(out) and out["model_summary"] == answer
    assert out["answer"].index(out["warnings"][-1]) < out["answer"].index(answer)
    assert "no_document_cited" in out["grounding_reasons"]


def test_a_failed_lookup_next_to_a_good_search_gets_a_leading_warning_and_keeps_the_answer():
    session = CannedSession({"/documents.json": (200, load_fixture("search_ai_rules.json")["body"]),
                             "/documents/2026-19964.json": (500, None)})
    answer = f"{REAL} is a final rule."
    out = ask([SEARCH, LOOKUP, AIMessage(content=answer)], session=session)
    # Since round 3 the block is longer than a screen after any search (it says what a total
    # counts and counts the search words per document), so the warning is also the last line.
    assert leads_with_warning(out) and (g.SUMMARY_LABEL + "\n" + answer) in out["answer"]
    assert out["answer"].splitlines()[-1].startswith("WARNING: (repeated from above")
    assert "tool_failed" in out["grounding_reasons"] and out["answer_replaced"] is False
    assert "HTTP 500" in out["warnings"][0] and "Tool calls that failed (1)" in out["block"]


def test_empty_search_and_the_models_text_is_replaced_whatever_it_says():
    """Round 1 let the model's text through when it was word for word the fixed sentence. Since
    round 2 the fixed text also lists the searches as they were sent, which the model cannot
    write for itself, so the text is always replaced and the call always counts as replaced."""
    for text in (g.NO_RESULTS_TEXT, "I found nothing, but you might try the EPA site.", "Nothing matched."):
        out = ask([EMPTY_SEARCH, AIMessage(content=text)], "search_no_results.json")
        assert out["answer"].startswith(g.NO_RESULTS_TEXT + "\nSearches sent (1):")
        assert out["answer_replaced"] is True and out["grounding"] == "replaced"
        assert out["no_results"] is True and "EPA site" not in out["answer"]


def test_a_refusal_without_a_tool_call_is_also_replaced_by_the_fixed_text():
    out = ask([AIMessage(content="I can only answer Federal Register questions.")])
    assert out["answer"] == g.REFUSAL_NO_TOOL and out["unverified_document_numbers"] == []


# ------------------------------------------------------------------ tool-call cap (review minor 6)
def test_one_model_turn_asking_for_forty_searches_makes_at_most_the_cap():
    session = ReplaySession("search_ai_rules.json", ignore_params=True)
    many = AIMessage(content="", tool_calls=[
        {"name": "search_federal_register", "args": {"term": f"t{i}"}, "id": f"c{i}"} for i in range(40)])
    out = ask([many, AIMessage(content=f"done {REAL}")], session=session)
    assert len(session.calls) == g.MAX_TOOL_CALLS_PER_TURN == 3
    assert len(out["tool_calls"]) == 40  # what the model asked for is still reported
    assert sum(1 for e in out["tool_errors"] if e.startswith("too_many_tool_calls")) == 37
    assert leads_with_warning(out)


# ------------------------------------------------------------------ token count after a stop (review minor 5)
def test_a_run_stopped_at_the_step_limit_still_reports_the_tokens_it_used():
    looping = AIMessage(content="", tool_calls=[{"name": "search_federal_register",
                                                 "args": _search_args("search_ai_rules.json"), "id": "c"}],
                        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
    model = ScriptedChatModel(responses=[looping], loop_last=True)
    graph = g.build_graph(model, g.build_tools(session=ReplaySession("search_ai_rules.json"), today=TODAY))
    out = g.run_question(graph, "loop forever", today=TODAY)
    assert out["stopped"] == "recursion_limit"
    assert out["usage"]["model_turns"] == model.calls >= 5
    assert out["usage"]["input_tokens"] == 100 * model.calls
    assert len(out["tool_calls"]) == model.calls
    assert out["answer"].startswith("Stopped:") and out["grounding"] == "stopped"


# ------------------------------------------------------------------ the hosted entrypoint
def test_the_hosted_entrypoint_returns_the_guarded_text_and_the_report(monkeypatch):
    import importlib

    import agent.model
    from starlette.testclient import TestClient

    from agent import fr_tools

    module = importlib.reload(importlib.import_module("agentcore_app"))
    monkeypatch.setattr(fr_tools, "_default_session", lambda: ReplaySession("search_ai_rules.json", ignore_params=True))
    invented = f"{REAL} and also 2026-00001, 2026-00002 and 91 FR 55123."
    monkeypatch.setattr(agent.model, "make_bedrock_model", lambda *a, **k: ScriptedChatModel(
        responses=[tool_call("search_federal_register", {"term": "ai"}), AIMessage(content=invented)]))
    with TestClient(module.app) as client:
        body = client.post("/invocations", json={"prompt": "ai rules"}).json()
    assert body["result"].startswith(body["block"]) and (body["prose_label"] + "\n" + invented) in body["result"]
    assert body["result"].splitlines()[-1].startswith("WARNING: (repeated from above")
    assert body["warning"].startswith("WARNING:") and body["prose"] == invented
    assert body["notes"] == [] and body["total_problems"] == []   # round 3: the new lists are sent too
    assert body["result"].index(body["warning"]) < body["result"].index(invented)
    assert body["unverified_document_numbers"] == ["2026-00001", "2026-00002", "91 FR 55123"]
    assert body["grounding"] == "warned" and body["warnings"]
    assert body["answer_replaced"] is False and body["withheld_answer_chars"] == 0


def test_the_hosted_entrypoint_never_sends_withheld_text_back(monkeypatch):
    import importlib

    import agent.model
    from starlette.testclient import TestClient

    module = importlib.reload(importlib.import_module("agentcore_app"))
    invented = "The Department of Energy published 'Grid Storage Incentive Rule' (2026-18888)."
    monkeypatch.setattr(agent.model, "make_bedrock_model",
                        lambda *a, **k: ScriptedChatModel(responses=[AIMessage(content=invented)]))
    with TestClient(module.app) as client:
        response = client.post("/invocations", json={"prompt": "storage rules"})
    body = response.json()
    assert body["result"] == g.REFUSAL_NO_TOOL and body["answer_replaced"] is True
    assert body["withheld_answer_chars"] == len(invented) and "withheld_answer" not in body
    assert "Grid Storage" not in response.text  # nowhere in the response, under any key
    assert body["unverified_document_numbers"] == ["2026-18888"]


# ------------------------------------------------------------------ the hosted caller, 50_invoke_hosted.py
def _streaming(payload: dict) -> StreamingBody:
    raw = json.dumps(payload).encode("utf-8")
    return StreamingBody(io.BytesIO(raw), len(raw))


def _hosted_run(kit, stubs, bodies):
    script = load_script("50_invoke_hosted.py")
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_arn=RUNTIME_ARN,
              runtime_id=RUNTIME_ID, idle_timeout_s=120, max_lifetime_s=900)
    stubs.add("sts", "get_caller_identity",
              {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/someone", "UserId": "AIDAEXAMPLE"}, {})
    for body in bodies:
        stubs.add("bedrock-agentcore", "invoke_agent_runtime",
                  {"statusCode": 200, "contentType": "application/json", "response": _streaming(body)})
    stubs.add("bedrock-agentcore", "stop_runtime_session", {"statusCode": 200})
    lines: list[str] = []
    rc = script.main(["--i-understand-this-bills", "--sessions", "1", "--calls-per-session", str(len(bodies))],
                     aws=make_aws(kit, stubs, lines), out=lines.append, state=state)
    stubs.assert_all_used()
    return rc, "\n".join(lines), json.loads(kit.STATE_PATH.read_text())["sessions"][0]["calls"]


def _clean_body():
    return {"result": f"One rule: {REAL}.", "tool_calls": [{"name": "search_federal_register", "args": {}}],
            "citations": [{"document_number": REAL}], "unverified_document_numbers": [], "tool_errors": [],
            "warnings": [], "grounding": "ok", "grounding_reasons": [], "answer_replaced": False,
            "usage": {"input_tokens": 900, "output_tokens": 120}, "stopped": None}


def test_hosted_caller_prints_stores_and_counts_unverified_numbers(kit, stubs):
    warned = _clean_body()
    warned.update(result="WARNING: this answer cites 3 reference(s) that no tool returned in this run: "
                         "2026-00001, 2026-00002, 2026-00003.\n\n" + "x" * 400,
                  unverified_document_numbers=["2026-00001", "2026-00002", "2026-00003"],
                  warnings=["WARNING: this answer cites 3 reference(s) that no tool returned in this run"],
                  grounding="warned", grounding_reasons=["unverified_references"])
    rc, text, calls = _hosted_run(kit, stubs, [warned])
    assert rc == 1
    assert "document numbers or citations no tool returned: 2026-00001, 2026-00002, 2026-00003" in text
    assert text.index("WARNING: this answer cites 3 reference(s)") < text.index("FLAGGED")
    for number in ("2026-00001", "2026-00002", "2026-00003"):
        assert number in text
    assert calls[0]["unverified_document_numbers"] == ["2026-00001", "2026-00002", "2026-00003"]
    assert calls[0]["flagged"] is True
    assert "Failed or flagged calls: 1" in text


def test_hosted_caller_prints_stores_and_counts_tool_errors(kit, stubs):
    failed = _clean_body()
    failed.update(result=g.REFUSAL_TOOL_FAILED + " upstream_error: HTTP 500 from the Federal Register API",
                  tool_errors=["upstream_error: HTTP 500 from the Federal Register API"], citations=[],
                  grounding="replaced", grounding_reasons=["tool_failed"], answer_replaced=True)
    rc, text, calls = _hosted_run(kit, stubs, [_clean_body(), failed])
    assert rc == 1
    assert "upstream_error: HTTP 500" in text
    assert calls[0]["flagged"] is False and calls[1]["flagged"] is True
    assert calls[1]["tool_errors"] == ["upstream_error: HTTP 500 from the Federal Register API"]
    assert "Failed or flagged calls: 1" in text


def test_hosted_caller_treats_a_body_without_a_grounding_report_as_unchecked(kit, stubs):
    """A zip built from an older copy of the kit returns no report. That must not pass for a checked answer."""
    old = {"result": "answer citing 2026-00001", "tool_calls": [{}], "citations": [],
           "usage": {"input_tokens": 1, "output_tokens": 1}, "stopped": None}
    rc, text, calls = _hosted_run(kit, stubs, [old])
    assert rc == 1 and calls[0]["flagged"] is True
    assert "no grounding report" in text


def test_hosted_caller_passes_a_clean_run(kit, stubs):
    rc, text, calls = _hosted_run(kit, stubs, [_clean_body(), _clean_body()])
    assert rc == 0, text
    assert "Failed or flagged calls: 0" in text and not calls[0]["flagged"] and not calls[1]["flagged"]


# ------------------------------------------------------------------ the local script
def test_local_script_prints_the_warning_before_the_answer_and_withholds_replaced_text(capsys):
    script = load_script("10_run_local.py")
    out = ask([SEARCH, AIMessage(content=f"{REAL} and also 2026-00001.")], "search_ai_rules.json")
    lines: list[str] = []
    script.print_result(out, 1.0, "scripted", lines.append)
    text = "\n".join(lines)
    assert text.index("WARNING:") < text.index("and also 2026-00001.")
    answer_part = text.split("Answer:")[1]
    assert answer_part.lstrip("\n").startswith(g.BLOCK_HEADER)  # the code-built block comes first
    assert lines[-1].startswith("WARNING: (repeated from above") and "2026-00001" in lines[-1]

    withheld = ask([AIMessage(content="Invented rule 2026-18888.")])
    lines = []
    script.print_result(withheld, 1.0, "scripted", lines.append)
    text = "\n".join(lines)
    assert "Invented rule" not in text and g.REFUSAL_NO_TOOL in text
    assert "withheld" in text.lower()
