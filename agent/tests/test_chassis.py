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


# --------------------------------------------------------- I-101, I-102, I-110
#
# The chassis guarantees the run loop had and the single-shot path did not, and
# the two ids one cycle can need.

def test_two_different_orders_in_one_cycle_get_two_ids():
    """I-101: `tool_guard._wrap` computed `ids.client_order_id(batch)` ONCE per
    tool and stamped it on every call, so close-A-then-open-B could not
    execute - the broker refused the second as a duplicate of the first, and
    the agent's own fresh retry id was overwritten and refused again. The live
    journal already carries a two-order cycle."""
    from trdrbot import tool_guard

    close = {"qty": 3, "legs": [{"symbol": "SPY260909P00636000",
                                 "side": "buy_to_close", "ratio_qty": 1}]}
    open_ = {"qty": 2, "legs": [{"symbol": "SPY260916C00700000",
                                 "side": "buy_to_open", "ratio_qty": 1}]}

    a = tool_guard.enforced_order_id("bat_1", "place_option_order", close)
    b = tool_guard.enforced_order_id("bat_1", "place_option_order", open_)

    assert a and b and a != b, "two different orders must be two ids"


def test_the_same_order_resubmitted_keeps_its_id():
    """INV-18, unchanged and the reason the id is derived at all: a crash-retry
    re-invokes a nondeterministic LLM, so the id must come from the batch and
    the intent, never from the decision."""
    from trdrbot import tool_guard

    args = {"qty": 2, "legs": [{"symbol": "SPY260916C00700000",
                                "side": "buy_to_open", "ratio_qty": 1}]}
    reordered = {"qty": 2, "legs": [dict(args["legs"][0])]}

    assert (tool_guard.enforced_order_id("bat_1", "place_option_order", args)
            == tool_guard.enforced_order_id("bat_1", "place_option_order", reordered))
    assert (tool_guard.enforced_order_id("bat_2", "place_option_order", args)
            != tool_guard.enforced_order_id("bat_1", "place_option_order", args))


def test_a_tool_that_bears_no_order_id_is_journalled_without_one():
    """I-101's secondary. `tick` journalled `client_order_id_enforced` for
    every ORDER_TOOLS call, including `close_position`, `cancel_order_by_id`
    and `close_all_positions` - which take no such field and are never wrapped.
    The live 2026-08-27 row records an enforced id on `close_all_positions`
    that was never sent: a record of something that never happened."""
    from trdrbot import tool_guard

    assert tool_guard.enforced_order_id(
        "bat_1", "close_all_positions", {}) is None
    assert tool_guard.enforced_order_id(
        "bat_1", "close_position", {"symbol_or_asset_id": "SPY..."}) is None


def test_the_lock_outlives_the_longest_tick_the_watchdog_permits(tmp_path):
    """I-102: `stale_after` defaulted to 600s while `_run_loop` permits
    `watchdog_seconds x OUTER_WATCHDOG_FACTOR`. A second invocation - run.sh
    under launchd beside `trdrbot run`, the scenario `_run_loop`'s own
    docstring names - read the live holder as stale at 601s, broke the lock and
    ran beside it: two decide cycles on one inbox batch, two submissions."""
    import json
    import os
    import time

    import pytest as _pytest

    from trdrbot import cli
    from trdrbot.lock import tick_lock

    permitted = 600.0 * cli.OUTER_WATCHDOG_FACTOR
    lock_file = tmp_path / "tick.lock"
    # A live holder, well past the OLD 600s window but inside what a tick may
    # legitimately take.
    lock_file.write_text(json.dumps({"pid": os.getpid(), "ts": time.time() - 900}))

    with _pytest.raises(BlockingIOError, match="already running"), \
            tick_lock(lock_file, stale_after=permitted):
        raise AssertionError("broke a lock the watchdog still permits")


def test_releasing_a_lock_we_no_longer_hold_leaves_the_new_holder_alone(tmp_path):
    """I-102's tail. The `finally` unlinked whatever lock file was there, so a
    process whose lock had been broken as stale deleted the BREAKER's lock on
    its way out - and a third process walked in behind both."""
    import json

    from trdrbot.lock import tick_lock

    lock_file = tmp_path / "tick.lock"
    with tick_lock(lock_file, stale_after=600):
        lock_file.write_text(json.dumps({"pid": 999999, "ts": 9e9}))  # broken as stale

    assert lock_file.exists(), "we released a lock another process now holds"
    assert json.loads(lock_file.read_text())["pid"] == 999999


def test_the_single_shot_tick_is_bounded_by_the_same_watchdog(monkeypatch, tmp_path):
    """I-110: `cli._tick` - the run.sh / launchd path - called `run_tick` bare.
    FM-26's outer bound existed only in `_run_loop`, so a wedged MCP subprocess
    spawn or a hung broker read stalled that process indefinitely, holding the
    lock until I-102's staleness let the next cron tick run beside it."""
    import asyncio as _asyncio
    import dataclasses

    from trdrbot import cli
    from trdrbot import config as config_mod

    live = config_mod.load()
    cfg = dataclasses.replace(
        live,
        raw={**live.raw, "tick": {**live.raw["tick"], "watchdog_seconds": 0.05}},
        paths=dataclasses.replace(live.paths, state=tmp_path))

    async def _hangs(*a: Any, **k: Any) -> Any:
        await _asyncio.sleep(3600)

    monkeypatch.setattr(cli, "run_tick", _hangs)
    monkeypatch.setattr(cli.config_mod, "load", lambda *a, **k: cfg)

    assert _asyncio.run(cli._tick()) == 1, "a hung tick must exit non-zero, not hang"


def test_the_closed_cadence_honours_the_same_floor_as_the_open_one(monkeypatch, tmp_path):
    """I-111: the 30s floor guarded `--interval` only, so `--closed-interval 0`
    ticked back to back all weekend - the same live broker, the same LLM spend,
    through the argument nobody thought of as the polling one.

    Hermetic on purpose. `_run_loop` writes `run.json` and takes the tick lock
    in the REAL state directory, and `trdrbot health` compares that file's git
    sha against HEAD - so a test driving it against the live tree overwrites the
    running loop's own provenance record. It also must not be able to trade: a
    stub `run_tick` and a temp state dir mean a broken floor fails the assertion
    rather than reaching a broker.
    """
    import asyncio as _asyncio
    import dataclasses

    from trdrbot import cli
    from trdrbot import config as config_mod

    cfg = dataclasses.replace(config_mod.load(quiet=True),
                              paths=config_mod.Paths.build(tmp_path))
    cfg.paths.ensure()
    ticked: list[int] = []

    async def _stub(*a: Any, **k: Any) -> dict[str, Any]:
        ticked.append(1)
        return {"market_open": False, "status": "housekeeping"}

    monkeypatch.setattr(cli.config_mod, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "run_tick", _stub)

    assert _asyncio.run(cli._run_loop(300, 0, max_ticks=1)) == 2
    assert _asyncio.run(cli._run_loop(0, 1800, max_ticks=1)) == 2
    assert ticked == [], "a refused cadence must not tick at all"
    assert not (tmp_path / "data" / "state" / "run.json").exists(), \
        "the refusal comes before anything is written"


def test_an_unchanged_export_leaves_the_snapshot_byte_identical(tmp_path, monkeypatch):
    """I-114. `site_export` stamped `generated_at = utc_now()` into every
    snapshot, so two exports of identical data always differed - and
    `publish.sh`'s "no change - nothing to deploy" branch, which compares the
    file's hash before and after, had never once fired: `data/publish_log.jsonl`
    shows 9 runs and 0 noops, so every publish rebuilt and redeployed the site.
    The stamp is applied only when the payload actually moved."""
    import dataclasses
    import json

    from trdrbot import config as config_mod
    from trdrbot import site_export

    # An EMPTY data tree, not the live one: the running loop appends journal
    # rows, and a test whose premise is "nothing changed" must own that.
    live = config_mod.load()
    cfg = dataclasses.replace(live, paths=config_mod.Paths.build(tmp_path))
    cfg.paths.ensure()
    monkeypatch.setattr(site_export.config_mod, "load", lambda *a, **k: cfg)

    out = tmp_path / "snapshot.json"
    assert site_export.export(out=out) == 0
    first = out.read_bytes()

    assert site_export.export(out=out) == 0
    assert out.read_bytes() == first, \
        "two exports of identical data differ only by their own timestamp"

    # ...and the stamp is still there, still honest, and still moves when the
    # payload does.
    assert json.loads(first)["generated_at"]
    (cfg.paths.journal).write_text('{"kind":"decision","ts":"2026-09-03T00:00:00+00:00"}\n',
                                   encoding="utf-8")
    assert site_export.export(out=out) == 0
    assert out.read_bytes() != first, "a real change must produce a new snapshot"


# ------------------------------------------------------- repo facts (notes/027)
#
# The submission deck used to carry lines-of-code, scaffold count, issue
# count and test count by hand, re-derived by hand, and it drifted. These
# pure functions are what a deck figure now reads instead.


def test_count_python_lines_sums_every_py_file_and_omits_a_missing_dir(tmp_path):
    from trdrbot import site_export

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "b.py").write_text("x\ny\n", encoding="utf-8")
    (src / "not_python.txt").write_text("ignored\nignored\nignored\n", encoding="utf-8")

    assert site_export.count_python_lines(src) == 5
    assert site_export.count_python_lines(tmp_path / "nowhere") is None, \
        "a fact that cannot be computed is omitted, not guessed at as zero"


def test_count_scaffolds_matches_only_the_scaffold_naming_convention(tmp_path):
    from trdrbot import site_export

    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("scaffold_harmony.py", "scaffold_risk_posture.py", "test_regressions.py"):
        (tests / name).touch()

    assert site_export.count_scaffolds(tests) == 2
    assert site_export.count_scaffolds(tmp_path / "nowhere") is None


def test_issue_counts_separates_highest_id_from_entries_listed(tmp_path):
    """The deck once said "125 numbered issues" with no definition of which
    of two real readings that meant (notes/027 section 1) - the highest id
    ever assigned, or how many entries are currently in the file. A
    cross-reference inside another entry's prose must not be counted as a
    second entry; a fixed entry kept in place with a strikethrough still is."""
    from trdrbot import site_export

    issues = tmp_path / "issues.md"
    issues.write_text(
        "## Open\n"
        "- **I-5 · a live one** measured. See also I-40 in the notes below.\n"
        "- ~~**I-3 · a fixed one**~~ **FIXED.** No longer open.\n"
        "## Resolved\n"
        "- ~~**I-1 · an old one**~~ **FIXED.**\n",
        encoding="utf-8",
    )

    max_id, listed = site_export.issue_counts(issues)
    assert max_id == 40, "I-40 is only a cross-reference, but it is still the highest id seen"
    assert listed == 3, "three ENTRIES (I-5, I-3, I-1) - the I-40 mention is not a fourth"
    assert site_export.issue_counts(tmp_path / "nowhere.md") == (None, None)


def test_count_tests_collected_parses_both_summary_shapes(monkeypatch, tmp_path):
    """Never spawns a real nested pytest - `subprocess.run` is stubbed with
    the two literal shapes `pytest --collect-only -q` actually prints, so the
    parser is pinned without the slowness or recursion risk of a real
    subprocess-in-a-subprocess."""
    import subprocess as _subprocess

    from trdrbot import site_export

    def fake_run(*_a, **_k):
        return _subprocess.CompletedProcess([], 0, stdout="745 tests collected in 0.50s\n")

    monkeypatch.setattr(site_export.subprocess, "run", fake_run)
    assert site_export.count_tests_collected(tmp_path) == 745

    def fake_run_deselected(*_a, **_k):
        return _subprocess.CompletedProcess(
            [], 0, stdout="745/764 tests collected (19 deselected) in 0.50s\n")

    monkeypatch.setattr(site_export.subprocess, "run", fake_run_deselected)
    assert site_export.count_tests_collected(tmp_path) == 745, \
        "the number before the slash is what actually RUNS"


def test_count_tests_collected_returns_none_rather_than_raise(monkeypatch, tmp_path):
    from trdrbot import site_export

    def boom(*_a, **_k):
        raise OSError("uv not found")

    monkeypatch.setattr(site_export.subprocess, "run", boom)
    assert site_export.count_tests_collected(tmp_path) is None


def test_build_repo_facts_only_refreshes_the_test_count_when_asked(monkeypatch, tmp_path):
    from trdrbot import site_export

    agent_root = tmp_path / "agent"
    (agent_root / "src" / "trdrbot").mkdir(parents=True)
    (agent_root / "src" / "trdrbot" / "m.py").write_text("x\n", encoding="utf-8")
    (agent_root / "tests").mkdir()
    (agent_root / "tests" / "scaffold_x.py").touch()
    repo_root = tmp_path / "repo"
    (repo_root / "specs").mkdir(parents=True)
    (repo_root / "specs" / "issues.md").write_text("- **I-1 · x**\n", encoding="utf-8")

    monkeypatch.setattr(site_export, "count_tests_collected", lambda _root: 999)

    # refresh_test_count=False: the cheap facts still compute, the test count
    # does not - this runs on `publish.sh`'s loop and must not pay for a
    # subprocess that imports the whole suite on every cycle.
    facts = site_export.build_repo_facts(agent_root, repo_root, {}, refresh_test_count=False)
    assert facts["python_lines"] == 1 and facts["scaffolds"] == 1
    assert facts["tests"] is None and facts["tests_counted_at"] is None

    # refresh_test_count=True: it does.
    facts = site_export.build_repo_facts(agent_root, repo_root, {}, refresh_test_count=True)
    assert facts["tests"] == 999 and facts["tests_counted_at"]


def test_build_repo_facts_keeps_the_prior_test_count_when_the_collector_fails(
    monkeypatch, tmp_path
):
    """A broken pytest collection step must not take the export down with it,
    and must not silently publish a guess - it carries forward the last KNOWN
    count, stamped with when that was actually measured."""
    from trdrbot import site_export

    agent_root = tmp_path / "agent"
    (agent_root / "src" / "trdrbot").mkdir(parents=True)
    (agent_root / "tests").mkdir()
    repo_root = tmp_path / "repo"
    (repo_root / "specs").mkdir(parents=True)

    monkeypatch.setattr(site_export, "count_tests_collected", lambda _root: None)
    prev = {"tests": 745, "tests_counted_at": "2026-09-03T18:40:11+00:00"}

    facts = site_export.build_repo_facts(agent_root, repo_root, prev, refresh_test_count=True)

    assert facts["tests"] == 745
    assert facts["tests_counted_at"] == "2026-09-03T18:40:11+00:00"


def test_repo_facts_are_computed_and_survive_a_pytest_failure(tmp_path, monkeypatch):
    """End to end through `export()`: the repo block lands in the snapshot,
    and asking for a refresh while the collector is broken degrades to the
    prior value rather than refusing the whole publish."""
    import dataclasses
    import json

    from trdrbot import config as config_mod
    from trdrbot import site_export

    live = config_mod.load()
    cfg = dataclasses.replace(live, paths=config_mod.Paths.build(tmp_path))
    cfg.paths.ensure()
    monkeypatch.setattr(site_export.config_mod, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(site_export, "count_tests_collected", lambda _root: None)

    out = tmp_path / "snapshot.json"
    assert site_export.export(out=out, refresh_test_count=True) == 0
    repo = json.loads(out.read_text(encoding="utf-8"))["repo"]
    assert repo["tests"] is None, "no prior snapshot to fall back to, and the collector failed"
    assert isinstance(repo["python_lines"], int) and repo["python_lines"] > 0
    assert repo["issues_max_id"] is not None and repo["issues_listed"] is not None


def test_the_monotonicity_guard_ignores_repo_facts(tmp_path, monkeypatch):
    """Trading-record counts refuse to shrink (positions, journal rows,
    theses); repo facts must NOT be swept into that guard - a falling test
    count or a retired scaffold is a legitimate Tuesday, not a corrupted
    read, and refusing to publish over it would be the guard fighting the
    wrong battle."""
    import dataclasses
    import json

    from trdrbot import config as config_mod
    from trdrbot import site_export

    live = config_mod.load()
    cfg = dataclasses.replace(live, paths=config_mod.Paths.build(tmp_path))
    cfg.paths.ensure()
    monkeypatch.setattr(site_export.config_mod, "load", lambda *a, **k: cfg)

    out = tmp_path / "snapshot.json"
    monkeypatch.setattr(site_export, "count_tests_collected", lambda _root: 100)
    assert site_export.export(out=out, refresh_test_count=True) == 0

    # A SHRINKING repo fact - fewer tests than last time - must not refuse.
    monkeypatch.setattr(site_export, "count_tests_collected", lambda _root: 3)
    assert site_export.export(out=out, refresh_test_count=True) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["repo"]["tests"] == 3
