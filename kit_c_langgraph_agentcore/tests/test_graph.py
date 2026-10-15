"""The graph, end to end, with a scripted fake model and recorded tool responses.

No credentials and no network: the model is agent.fake_model.ScriptedChatModel,
and the tools answer from tests/fixtures through ReplaySession.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
from conftest import ReplaySession, load_fixture
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent import graph as g
from agent.fake_model import ScriptedChatModel, demo_script, tool_call

TODAY = dt.date(2026, 10, 7)


def _search_args(fixture: str) -> dict:
    params = load_fixture(fixture)["request"]["params"]
    get = lambda key: next(v for k, v in params if k == key)  # noqa: E731
    return {
        "term": get("conditions[term]"),
        "doc_type": get("conditions[type][]"),
        "date_from": get("conditions[publication_date][gte]"),
        "date_to": get("conditions[publication_date][lte]"),
        "limit": int(get("per_page")),
    }


def _docs(fixture: str = "search_ai_rules.json") -> list[dict]:
    return load_fixture(fixture)["body"]["results"]


def _build(model, *fixtures):
    session = ReplaySession(*fixtures)
    return g.build_graph(model, g.build_tools(session=session, today=TODAY)), session


# ---------------------------------------------------------------- routing
def test_routing_model_tool_model_finalize_end():
    doc = _docs()[0]
    answer = f"One final rule matched: {doc['title']} ({doc['document_number']}) {doc['html_url']}"
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", _search_args("search_ai_rules.json")),
            AIMessage(content=answer),
        ]
    )
    graph, session = _build(model, "search_ai_rules.json")
    visited = []
    messages = [
        SystemMessage(content=g.SYSTEM_PROMPT.format(today=TODAY.isoformat())),
        HumanMessage(content="What final rules mention artificial intelligence?"),
    ]
    for update in graph.stream({"messages": messages}, stream_mode="updates"):
        visited.extend(update.keys())
    assert visited == ["model", "tools", "model", "finalize"]
    assert model.calls == 2
    assert len(session.calls) == 1
    assert model.bound_tool_names == ["search_federal_register", "get_federal_register_document"]


def test_run_question_returns_answer_tool_calls_and_citations():
    doc = _docs()[0]
    answer = f"Found {doc['document_number']}: {doc['html_url']}"
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", _search_args("search_ai_rules.json")),
            AIMessage(content=answer),
        ]
    )
    graph, _ = _build(model, "search_ai_rules.json")
    out = g.run_question(graph, "What final rules mention artificial intelligence?", today=TODAY)
    assert out["stopped"] is None
    # the code-built block first, then the label, then the model's text, and no warning
    assert out["answer"] == out["block"] + "\n\n" + g.SUMMARY_LABEL + "\n" + answer
    assert out["model_summary"] == answer and out["warnings"] == [] and out["grounding"] == "ok"
    assert [c["name"] for c in out["tool_calls"]] == ["search_federal_register"]
    assert out["citations"] == [
        {"document_number": doc["document_number"], "title": doc["title"], "html_url": doc["html_url"],
         "type": doc["type"], "publication_date": doc["publication_date"],
         "agencies": [a["name"] for a in doc["agencies"]]}
    ]
    assert out["searches"] == [{"query": json.loads([m for m in model.seen[1] if isinstance(m, ToolMessage)]
                                                    [0].content)["query"], "api_total": 2, "returned": 2}]
    assert out["no_results"] is False
    assert out["unverified_document_numbers"] == []
    assert out["tool_errors"] == []


def test_two_tool_rounds_search_then_document():
    doc = load_fixture("document_detail.json")["body"]
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", _search_args("search_ai_rules.json")),
            tool_call("get_federal_register_document", {"document_number": doc["document_number"]}),
            AIMessage(content=f"{doc['document_number']} takes effect on {doc['effective_on']}."),
        ]
    )
    graph, session = _build(model, "search_ai_rules.json", "document_detail.json")
    out = g.run_question(graph, "When does the newest AI rule take effect?", today=TODAY)
    assert [c["name"] for c in out["tool_calls"]] == [
        "search_federal_register", "get_federal_register_document",
    ]
    assert len(session.calls) == 2
    assert [c["document_number"] for c in out["citations"]] == [doc["document_number"]]


def test_system_prompt_carries_the_date_passed_per_call():
    model = ScriptedChatModel(responses=[AIMessage(content="No tools needed.")])
    graph, _ = _build(model)
    g.run_question(graph, "hello", today=dt.date(2031, 1, 2))
    first_prompt = model.seen[0][0]
    assert isinstance(first_prompt, SystemMessage)
    assert "Today's date is 2031-01-02" in first_prompt.content


# ---------------------------------------------------------------- no results
def test_no_results_path_replaces_the_answer_with_the_plain_statement():
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", _search_args("search_no_results.json")),
            AIMessage(content="Here is what I found."),
        ]
    )
    graph, _ = _build(model, "search_no_results.json")
    out = g.run_question(graph, "Any final rules about zzqxv?", today=TODAY)
    assert out["no_results"] is True
    assert out["citations"] == []
    # fixed text, then the search as it was sent; the model's own text is not kept beside it
    assert out["answer"].startswith(g.NO_RESULTS_TEXT + "\nSearches sent (1):\n  1. term: zzqxv")
    # round 3: and one fixed line that a count of 0 is about the search words, not the topic
    assert out["answer"].endswith("The API reported 0 matching documents.\n     " + g.ZERO_MATCHES_NOT_TOPIC)
    assert "Here is what I found" not in out["answer"]
    assert out["withheld_answer"] == "Here is what I found." and out["model_summary"] is None


def test_no_results_path_flags_invented_document_number():
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", _search_args("search_no_results.json")),
            AIMessage(content="See document 2026-99999 at https://www.federalregister.gov/d/2026-99999."),
        ]
    )
    graph, _ = _build(model, "search_no_results.json")
    out = g.run_question(graph, "Any final rules about zzqxv?", today=TODAY)
    assert out["no_results"] is True
    assert out["unverified_document_numbers"] == ["2026-99999"]
    assert out["answer"].startswith(g.NO_RESULTS_TEXT)
    assert "2026-99999" not in out["answer"]


def test_grounded_answer_with_one_invented_number_is_flagged_not_cited():
    doc = _docs()[0]
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", _search_args("search_ai_rules.json")),
            AIMessage(content=f"See {doc['document_number']} and also 2026-00001."),
        ]
    )
    graph, _ = _build(model, "search_ai_rules.json")
    out = g.run_question(graph, "AI rules?", today=TODAY)
    assert [c["document_number"] for c in out["citations"]] == [doc["document_number"]]
    assert out["unverified_document_numbers"] == ["2026-00001"]
    assert out["no_results"] is False
    assert out["answer"].startswith(out["block"]) and "2026-00001" not in out["block"]
    assert len(out["warnings"]) == 1 and out["warnings"][0].startswith("WARNING:")
    assert "2026-00001" in out["warnings"][0]
    answer = out["answer"]
    assert answer.index(out["warnings"][0]) < answer.index(g.SUMMARY_LABEL) < answer.index("and also 2026-00001")


def test_answer_without_tools_is_reported_as_such():
    model = ScriptedChatModel(responses=[AIMessage(content="I can only answer Federal Register questions.")])
    graph, session = _build(model)
    out = g.run_question(graph, "What is the weather?", today=TODAY)
    assert out["tool_calls"] == [] and out["citations"] == [] and out["no_results"] is False
    assert session.calls == []
    assert out["answer"] == g.REFUSAL_NO_TOOL and out["grounding"] == "replaced"


# ---------------------------------------------------------------- recursion limit
def test_recursion_limit_stops_a_model_that_never_finishes():
    model = ScriptedChatModel(
        responses=[tool_call("search_federal_register", _search_args("search_no_results.json"))],
        loop_last=True,
    )
    graph, session = _build(model, "search_no_results.json")
    out = g.run_question(graph, "loop forever", today=TODAY, recursion_limit=6)
    assert out["stopped"] == "recursion_limit"
    assert out["answer"].startswith("Stopped: the agent did not finish within 6 graph steps")
    assert out["citations"] == []
    assert 1 <= model.calls <= 6
    assert len(session.calls) <= 6


@pytest.mark.parametrize("rounds, stopped", [(4, None), (5, "recursion_limit")])
def test_default_recursion_limit_allows_four_tool_rounds_and_stops_a_fifth(rounds, stopped):
    doc = _docs()[0]
    calls = [tool_call("search_federal_register", _search_args("search_ai_rules.json"))] * rounds
    model = ScriptedChatModel(responses=calls + [AIMessage(content=f"Done: {doc['document_number']}")])
    graph, _ = _build(model, "search_ai_rules.json")
    out = g.run_question(graph, "several rounds", today=TODAY)
    assert g.DEFAULT_RECURSION_LIMIT == 12
    assert out["stopped"] == stopped
    if stopped is None:
        assert len(out["tool_calls"]) == rounds


@pytest.mark.parametrize("asked_per_turn, sent", [(1, 6), (3, 18), (5, 18)])
def test_a_model_that_never_finishes_sends_at_most_18_requests(asked_per_turn, sent):
    """The comment beside MAX_TOOL_CALLS_PER_TURN said 15 (5 tool turns x 3). A round 4 test rig reported 18 and the
    review measured it later: the step limit of 12 lets SIX tool turns run before it stops a
    model that never finishes (a question that finishes has had at most four)."""
    one = tool_call("search_federal_register", _search_args("search_no_results.json"))
    turn = AIMessage(content="", tool_calls=[dict(one.tool_calls[0], id=f"call_{i}") for i in range(asked_per_turn)])
    model = ScriptedChatModel(responses=[turn], loop_last=True)
    graph, session = _build(model, "search_no_results.json")
    out = g.run_question(graph, "never finishes", today=TODAY)
    assert out["stopped"] == "recursion_limit" and model.calls == 6
    assert len(session.calls) == sent == min(asked_per_turn, g.MAX_TOOL_CALLS_PER_TURN) * 6
    source = (pathlib.Path(g.__file__)).read_text(encoding="utf-8")
    assert "6 tool turns x 3 = 18 requests" in source and "x 3 = 15" not in source


# ---------------------------------------------------------------- tool errors reach the model
def test_invalid_tool_arguments_come_back_to_the_model_as_json_error():
    model = ScriptedChatModel(
        responses=[
            tool_call("search_federal_register", {"term": "ai", "doc_type": "MEMO"}),
            AIMessage(content="The search could not run: the document type was not valid."),
        ]
    )
    graph, session = _build(model)
    out = g.run_question(graph, "AI memos?", today=TODAY)
    tool_messages = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
    assert json.loads(tool_messages[0].content)["error"] == "invalid_input"
    assert session.calls == []
    assert out["tool_errors"] and out["tool_errors"][0].startswith("invalid_input")
    assert out["no_results"] is False


def test_document_not_found_reaches_the_model():
    model = ScriptedChatModel(
        responses=[
            tool_call("get_federal_register_document", {"document_number": "0000-00000"}),
            AIMessage(content="There is no document 0000-00000."),
        ]
    )
    graph, _ = _build(model, "document_not_found.json")
    out = g.run_question(graph, "Show me 0000-00000", today=TODAY)
    assert out["tool_errors"][0].startswith("not_found")
    assert out["unverified_document_numbers"] == ["0000-00000"]


# ---------------------------------------------------------------- small pure pieces
def test_find_document_numbers_ignores_year_ranges():
    text = "Model years 2027-2031; see 2026-19964, E9-31418 and C1-2026-12345, not 1999-2004."
    assert g.find_document_numbers(text) == {"2026-19964", "E9-31418", "C1-2026-12345"}


def test_text_of_handles_bedrock_content_blocks():
    message = AIMessage(content=[{"type": "text", "text": "Hello "}, {"type": "text", "text": "there"}])
    assert g._text_of(message) == "Hello there"


@pytest.mark.parametrize("bad", ["", "   ", None, 7, "x" * 2001])
def test_run_question_rejects_bad_questions(bad):
    model = ScriptedChatModel(responses=[AIMessage(content="unused")])
    graph, _ = _build(model)
    with pytest.raises(ValueError):
        g.run_question(graph, bad, today=TODAY)
    assert model.calls == 0


def test_tool_schemas_are_what_a_model_will_see():
    tools = {t.name: t for t in g.build_tools()}
    search = tools["search_federal_register"].tool_call_schema.model_json_schema()
    assert search["required"] == ["term"]
    assert set(search["properties"]) == {"term", "agencies", "doc_type", "date_from", "date_to", "limit",
                                         "last_n_days"}
    assert all(p.get("description") for p in search["properties"].values())
    one = tools["get_federal_register_document"].tool_call_schema.model_json_schema()
    assert one["required"] == ["document_number"]


def test_demo_model_lists_exactly_what_the_search_returned():
    session = ReplaySession("search_ai_rules.json", ignore_params=True)
    graph = g.build_graph(demo_script("energy storage"), g.build_tools(session=session))
    out = g.run_question(graph, "energy storage", today=TODAY)
    assert out["model_summary"].startswith("FAKE MODEL") and out["answer"].startswith(g.BLOCK_HEADER)
    assert out["tool_calls"][0]["args"] == {"term": "energy storage", "limit": 3}
    assert len(session.calls) == 1
    assert [c["document_number"] for c in out["citations"]] == sorted(d["document_number"] for d in _docs())
    assert out["grounding"] == "ok" and out["unverified_document_numbers"] == []


def test_demo_model_with_an_empty_search_ends_in_the_no_results_sentence():
    session = ReplaySession("search_no_results.json", ignore_params=True)
    graph = g.build_graph(demo_script("zzqxv"), g.build_tools(session=session))
    out = g.run_question(graph, "zzqxv", today=TODAY)
    assert out["answer"].startswith(g.NO_RESULTS_TEXT) and out["no_results"] is True
    assert "term: zzqxv" in out["answer"] and "FAKE MODEL" not in out["answer"]


def test_last_n_days_is_turned_into_dates_by_code_not_by_the_model():
    """Review minor 8. The recorded search covers 2026-09-07 to 2026-10-07, which is 30 days back
    from 2026-10-07. The model sends only last_n_days=30; the request must match the recording."""
    args = _search_args("search_ai_rules.json")
    del args["date_from"], args["date_to"]
    args["last_n_days"] = 30
    doc = _docs()[0]
    model = ScriptedChatModel(responses=[tool_call("search_federal_register", args),
                                         AIMessage(content=f"Found {doc['document_number']}.")])
    graph, session = _build(model, "search_ai_rules.json")  # exact parameter match is required
    out = g.run_question(graph, "AI rules in the last 30 days?", today=TODAY)
    assert len(session.calls) == 1 and out["grounding"] == "ok"
    echoed = json.loads([m for m in model.seen[1] if isinstance(m, ToolMessage)][0].content)["query"]
    assert (echoed["date_from"], echoed["date_to"]) == ("2026-09-07", "2026-10-07")
    assert "computed in code" in echoed["date_note"]
    assert "last_n_days=N" in g.SYSTEM_PROMPT
