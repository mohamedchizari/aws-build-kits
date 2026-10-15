"""Fake chat models for offline runs. No network, no credentials, no token cost.

ScriptedChatModel returns the AIMessages it was given, in order. bind_tools is
accepted and remembered but changes nothing, which is all the graph needs to
exercise its routing. The tests use it.

DemoChatModel is what --fake-model uses in the local scripts. It asks for one
search, then writes its "answer" from what the search tool really returned:
the document numbers and URLs, copied, nothing added. That way the offline
demo also shows the citation check passing, and shows the fixed no-results
sentence when the search finds nothing.
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    responses: List[AIMessage]
    loop_last: bool = False
    calls: int = 0
    bound_tool_names: List[str] = []
    seen: List[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        self.bound_tool_names = [getattr(t, "name", str(t)) for t in tools]
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        index = self.calls
        self.calls += 1
        if index >= len(self.responses):
            if not self.loop_last:
                raise RuntimeError("ScriptedChatModel ran out of scripted responses")
            index = len(self.responses) - 1
        message = self.responses[index].model_copy(deep=True)
        if message.tool_calls:
            # give each repeated call its own id, as a real model would
            message.tool_calls = [
                {**call, "id": f"{call.get('id') or 'call'}-{self.calls}"}
                for call in message.tool_calls
            ]
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict, call_id: str = "call") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


FAKE_BANNER = "FAKE MODEL: no language model was called."


class DemoChatModel(BaseChatModel):
    """One search for the question, then a listing of exactly what the search returned."""

    question: str
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "demo-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "DemoChatModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls += 1
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        if not tool_messages:
            message = AIMessage(content="", tool_calls=[{
                "name": "search_federal_register",
                "args": {"term": self.question[:200], "limit": 3},
                "id": "demo-search-1",
            }])
            return ChatResult(generations=[ChatGeneration(message=message)])
        try:
            data = json.loads(tool_messages[-1].content)
        except (TypeError, ValueError):
            data = {}
        results = data.get("results") if isinstance(data, dict) else None
        if isinstance(data, dict) and data.get("error"):
            text = f"{FAKE_BANNER} The search tool reported an error: {data['error']}."
        elif not results:
            text = f"{FAKE_BANNER} The search tool ran for real and returned no documents."
        else:
            lines = [f"{FAKE_BANNER} The search tool ran for real and returned:"]
            for doc in results:
                lines.append(f"- {doc.get('document_number')}  {doc.get('title')}  {doc.get('html_url')}")
            text = "\n".join(lines)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def demo_script(question: str) -> DemoChatModel:
    return DemoChatModel(question=question)
