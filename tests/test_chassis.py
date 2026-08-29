"""The runtime chassis: tool-error containment, the tick lock, the watchdog.

These guard INV-7 (one tick at a time) and FM-26 (a hung call must not stall
an eight-day unattended run) - both of which were specified in
`specs/architecture.md` and, until this phase, unenforced on the only path
anyone actually runs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from trdrbot import tick as tick_mod


class ScriptedModel(BaseChatModel):
    """A model that plays a fixed script and accepts `bind_tools`.

    Substituting at the model boundary is what lets this exercise the REAL
    agent graph - the seam a tool error actually travels through - rather than
    a ToolNode in isolation, which cannot even be invoked without a graph
    runtime.
    """

    responses: list[AIMessage] = []
    i: int = 0

    def bind_tools(self, tools: Any, **kw: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None,
                  **kw: Any) -> ChatResult:
        msg = self.responses[min(self.i, len(self.responses) - 1)]
        object.__setattr__(self, "i", self.i + 1)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "scripted"


def _exploding_tool() -> StructuredTool:
    async def boom(x: str) -> str:
        raise RuntimeError("mcp pipe broke")

    return StructuredTool.from_function(coroutine=boom, name="boom",
                                        description="raises like a dead MCP subprocess")


def _script() -> list[AIMessage]:
    return [
        AIMessage(content="", tool_calls=[{"name": "boom", "args": {"x": "1"},
                                           "id": "c1", "type": "tool_call"}]),
        AIMessage(content="the tool failed, so I declined"),
    ]


async def test_a_runtime_tool_error_reaches_the_model_instead_of_killing_the_cycle():
    """langgraph >=1.0 flipped the tool-error default and this project's pin is
    `langgraph>=0.2`, so the change arrived silently under a design that
    assumes the old behaviour (every tool_guard refusal is a STRING, the
    compactor fails open).

    Verified against the installed 1.2.11: without the flag a tool raising
    RuntimeError propagates out of `agent.ainvoke`. In production that escape
    burns EVERY pending inbox item's retry budget via record_failure, and a
    raise from record_position after a fill loses the execution row entirely.
    """
    agent = create_react_agent(ScriptedModel(responses=_script()),
                               tick_mod.decide_tool_node([_exploding_tool()]))

    result = await agent.ainvoke({"messages": [("user", "go")]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages, "the tool error never came back as a message"
    assert "mcp pipe broke" in tool_messages[0].content
    assert tool_messages[0].status == "error"
    assert result["messages"][-1].content == "the tool failed, so I declined"


async def test_the_unpatched_default_really_does_raise():
    """Pins the belief the fix rests on, so this test starts failing the day
    langgraph changes the default back - at which point the wrapper is
    redundant rather than load-bearing, and that is worth knowing."""
    agent = create_react_agent(ScriptedModel(responses=_script()), [_exploding_tool()])

    with pytest.raises(RuntimeError, match="mcp pipe broke"):
        await agent.ainvoke({"messages": [("user", "go")]})
