"""The AgentCore entrypoint, served in-process. No port is opened, no AWS, no network.

BedrockAgentCoreApp is a Starlette application, so Starlette's TestClient can
call POST /invocations and GET /ping directly. This checks the HTTP contract
the hosted runtime depends on, with the fake model and recorded tool results.
"""
from __future__ import annotations

import importlib

import pytest
from conftest import ReplaySession
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from agent import fr_tools
from agent.fake_model import ScriptedChatModel, tool_call

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


@pytest.fixture()
def entry(monkeypatch):
    module = importlib.import_module("agentcore_app")
    module = importlib.reload(module)  # fresh graph cache for every test
    replay = ReplaySession("search_ai_rules.json", ignore_params=True)
    monkeypatch.setattr(fr_tools, "_default_session", lambda: replay)
    module.replay = replay
    return module


def test_ping_reports_healthy(entry):
    with TestClient(entry.app) as client:
        resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.json()["status"] == "Healthy"


def test_invocations_with_fake_model(entry, monkeypatch):
    monkeypatch.setenv("KIT_FAKE_MODEL", "1")
    session_id = "kit-test-session-0123456789abcdef0123456789"
    with TestClient(entry.app) as client:
        resp = client.post(
            "/invocations", json={"prompt": "energy storage"}, headers={SESSION_HEADER: session_id}
        )
    assert resp.status_code == 200
    body = resp.json()
    # the three parts, separately and combined: block built by code, no warning, the model's text
    assert body["block"].startswith("FROM THE FEDERAL REGISTER API. Built by code")
    assert "2026-19964" in body["block"] and "2026-19071" in body["block"]
    assert body["warning"] == "" and body["prose"].startswith("FAKE MODEL")
    assert body["result"] == body["block"] + "\n\n" + body["prose_label"] + "\n" + body["prose"]
    assert [c["document_number"] for c in body["citations"]] == ["2026-19071", "2026-19964"]
    assert body["grounding"] == "ok" and body["warnings"] == [] and body["answer_replaced"] is False
    assert body["tool_calls"] == [
        {"name": "search_federal_register", "args": {"term": "energy storage", "limit": 3}}
    ]
    assert body["session_id"] == session_id
    assert body["model_id"].startswith("fake")
    assert body["stopped"] is None
    assert len(entry.replay.calls) == 1


@pytest.mark.parametrize("payload", [{}, {"prompt": ""}, {"prompt": 5}, {"question": "x"}, ["prompt"]])
def test_invocations_rejects_a_missing_or_bad_prompt(entry, monkeypatch, payload):
    monkeypatch.setenv("KIT_FAKE_MODEL", "1")
    with TestClient(entry.app) as client:
        resp = client.post("/invocations", json=payload)
    assert resp.status_code == 200
    assert resp.json()["error"] == "invalid_input"
    assert entry.replay.calls == []


def test_invocations_rejects_an_overlong_prompt(entry, monkeypatch):
    monkeypatch.setenv("KIT_FAKE_MODEL", "1")
    with TestClient(entry.app) as client:
        resp = client.post("/invocations", json={"prompt": "x" * 2001})
    assert resp.json()["error"] == "invalid_input"


def test_invalid_json_is_a_400(entry):
    with TestClient(entry.app) as client:
        resp = client.post("/invocations", content=b"{not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


def test_real_model_path_builds_the_graph_once_and_reuses_it(entry, monkeypatch):
    """Stands in for Bedrock: make_bedrock_model is replaced, nothing else."""
    built = []

    def fake_factory(*args, **kwargs):
        model = ScriptedChatModel(
            responses=[
                tool_call("search_federal_register", {"term": "ai"}),
                AIMessage(content="first answer: 2026-19964"),
                tool_call("search_federal_register", {"term": "ai"}),
                AIMessage(content="second answer: 2026-19071"),
            ]
        )
        built.append(model)
        return model

    import agent.model

    monkeypatch.setattr(agent.model, "make_bedrock_model", fake_factory)
    monkeypatch.setenv("MODEL_ID", "us.example.model-v1:0")
    with TestClient(entry.app) as client:
        first = client.post("/invocations", json={"prompt": "ai rules"}).json()
        second = client.post("/invocations", json={"prompt": "ai rules again"}).json()
    assert len(built) == 1
    assert first["prose"].startswith("first answer") and first["result"].endswith("first answer: 2026-19964")
    assert second["prose"].startswith("second answer")
    assert first["model_id"] == "us.example.model-v1:0"


def test_importing_the_entrypoint_builds_nothing(entry):
    assert entry._graph is None


def test_the_listen_address_is_passed_explicitly(entry, monkeypatch):
    """Review minors 3 and 15: 127.0.0.1 on your machine, whatever 30_deploy.py set when hosted."""
    monkeypatch.delenv("KIT_BIND_HOST", raising=False)
    assert entry.bind_host() == "127.0.0.1"
    monkeypatch.setenv("KIT_BIND_HOST", "0.0.0.0")
    assert entry.bind_host() == "0.0.0.0"
    started = {}
    monkeypatch.setattr(entry.app, "run", lambda **kwargs: started.update(kwargs))
    import runpy

    monkeypatch.setattr(entry.BedrockAgentCoreApp, "run", lambda self, **kwargs: started.update(kwargs))
    runpy.run_path(entry.__file__, run_name="__main__")
    assert started == {"host": "0.0.0.0"}
