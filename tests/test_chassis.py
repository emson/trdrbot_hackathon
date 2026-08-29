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

    def bind_tools(self, tools: Any, **kw: Any) -> ScriptedModel:
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
async def test_a_hung_tick_does_not_stall_the_run_loop(monkeypatch, tmp_path):
    """FM-26. `watchdog_seconds` was configured and read by NOTHING, so a hung
    LLM call stalled an unattended run indefinitely - and because the loop held
    no tick lock either, there was not even a stale-lock signal to notice it
    by."""
    from trdrbot import cli

    cfg = _tmp_config(tmp_path, watchdog_seconds=0.05)
    monkeypatch.setattr(cli.config_mod, "load", lambda *a, **k: cfg)

    async def never_returns(*a: Any, **k: Any) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr("trdrbot.tick.run_tick", never_returns)

    async with asyncio.timeout(10):
        rc = await cli._run_loop(interval=0, closed_interval=0, max_ticks=1,
                                 allow_fast=True)
    assert rc == 0


async def test_the_run_loop_holds_the_tick_lock_around_each_tick(monkeypatch, tmp_path):
    """INV-7 was enforced on `trdrbot tick` and NOT on `trdrbot run` - the only
    path that runs unattended. A launchd-driven run.sh alongside a run loop
    would interleave two ticks freely: two tick-counter writes, two elfmem
    sessions on one SQLite file, two decide cycles on one inbox batch."""
    from trdrbot import cli

    cfg = _tmp_config(tmp_path)
    monkeypatch.setattr(cli.config_mod, "load", lambda *a, **k: cfg)
    seen: list[bool] = []

    async def probe(*a: Any, **k: Any) -> dict[str, Any]:
        seen.append((cfg.paths.state / "tick.lock").exists())
        return {"market_open": False, "status": "housekeeping"}

    monkeypatch.setattr("trdrbot.tick.run_tick", probe)

    await cli._run_loop(interval=0, closed_interval=0, max_ticks=1, allow_fast=True)

    assert seen == [True], "the tick ran without holding the lock"
    assert not (cfg.paths.state / "tick.lock").exists(), "lock outlived the tick"


async def test_a_held_lock_skips_the_tick_rather_than_ending_the_run(monkeypatch, tmp_path):
    """A lock held by a live process means another tick is trading right now.
    Skip and come back - never crash the loop, never break the lock."""
    import json
    import os
    import time

    from trdrbot import cli

    cfg = _tmp_config(tmp_path)
    monkeypatch.setattr(cli.config_mod, "load", lambda *a, **k: cfg)
    (cfg.paths.state / "tick.lock").write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time()})
    )
    called: list[int] = []

    async def probe(*a: Any, **k: Any) -> dict[str, Any]:
        called.append(1)
        return {"market_open": True, "status": "done"}

    monkeypatch.setattr("trdrbot.tick.run_tick", probe)

    rc = await cli._run_loop(interval=0, closed_interval=0, max_ticks=1, allow_fast=True)

    assert rc == 0
    assert called == [], "ran a second tick while another held the lock"


def _tmp_config(tmp_path: Any, **tick_overrides: Any) -> Any:
    """A real Config rooted at tmp_path, built by the real loader.

    Copies the project's own config.yaml so the test cannot drift from the
    shape production actually parses - the producer-derived rule applied to
    configuration.
    """
    import shutil
    from pathlib import Path

    from trdrbot import config as config_mod

    root = Path(__file__).resolve().parents[1]
    shutil.copy(root / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / ".env").write_text("")
    cfg = config_mod.load(tmp_path, quiet=True)
    if tick_overrides:
        cfg.raw["tick"].update(tick_overrides)
    # Tomorrow, so the deadline loop condition is true regardless of when the
    # suite runs. `max_ticks` is what actually stops these tests.
    from datetime import timedelta

    from trdrbot import ids
    cfg.raw["trading"]["deadline"] = (ids.utc_now().date() + timedelta(days=1)).isoformat()
    return cfg


def test_every_subcommand_parses_and_has_a_handler():
    """The dispatch was a 17-branch `elif args.cmd == "..."` chain restating
    every parser name as a string literal, so a typo in either half was a
    silent no-op argparse could not catch. Now one handler table - and this
    walks every declared subcommand to prove the two halves still agree.
    """
    import argparse
    import contextlib
    import io

    from trdrbot import cli

    # `main()` exits on any invocation, so drive it through --help per command
    # and assert the parser accepted it. SystemExit(0) is argparse succeeding.
    parser_names = []
    real_exit = SystemExit
    for name in ("doctor", "inject", "tick", "journal", "calibration", "research",
                 "discover", "muse", "health", "prompts", "usage", "ledger",
                 "lessons", "coach", "report", "modelcal", "run", "constitution"):
        with contextlib.redirect_stdout(io.StringIO()):
            import sys
            argv = sys.argv
            sys.argv = ["trdrbot", name, "--help"]
            try:
                cli.main()
            except real_exit as e:
                assert e.code == 0, f"{name} --help exited {e.code}"
                parser_names.append(name)
            finally:
                sys.argv = argv

    assert len(parser_names) == 18
    assert isinstance(argparse.ArgumentParser(), argparse.ArgumentParser)
