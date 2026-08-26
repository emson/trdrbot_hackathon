"""One tick, split by cost (D-017).

    EVERY TICK (cheap, deterministic, no LLM)
        C21 analytics  ->  C13 reconcile  ->  C24 exit rules
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        That order is the D-019 fix (INV-25): reconciling first means a
        position the broker already resolved is terminal before exit rules
        run, so it is excluded by construction rather than by a later check.

    EVERY N TICKS (expensive)
        resume-check -> assemble context (incl. elfmem frames) -> decide
        -> act -> journal

    MARKET CLOSED
        housekeeping instead of decide: interim scoring (INV-24), the only
        place elfmem's dream() is allowed to run (INV-10/23).

Fast monitoring with slow deciding shortens the exposure window while cutting
LLM spend - the exit evaluator needs no model to notice a breached stop.

elfmem's session() auto-consolidates on exit (verified against the running
library, see elfmem_adapter.py) - so a tick begins/ends its own session
manually and never calls dream() itself.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.prebuilt import create_react_agent

from . import (
    analytics,
    exit_rules,
    failures,
    housekeeping,
    ids,
    local_tools,
    mcp_client,
    reconcile,
    sensors,
    tool_guard,
)
from .calibration import CalibrationStore
from .config import Config
from .elfmem_adapter import ElfmemAdapter
from .inbox import Inbox, Item
from .journal import Journal
from .llm import SYSTEM_PROMPT, build_model
from .positions import PositionStore
from .wiki import Wiki


def _tick_count(config: Config) -> int:
    p = config.paths.state / "tick_count"
    n = int(p.read_text().strip() or 0) + 1 if p.exists() else 1
    p.write_text(str(n))
    return n


def _text_of(message: Any) -> str:
    """Readable text from a message whose content may be a block list.

    Extended-thinking responses return a list of blocks - a `thinking` block
    carrying an opaque signature blob, then the actual `text`. Stringifying
    the whole list dumped that blob into the journal and the console, burying
    the agent's reasoning in base64 and wasting the 2000-char summary budget.
    """
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return str(content)


def _render_positions(store: PositionStore) -> str:
    """Two-tier context (D-019): detail for what needs attention, one line for the rest."""
    positions = store.open_positions()
    if not positions:
        return "## Our positions\n\n(none)"

    lines = ["## Our positions", ""]
    for p in positions:
        rules = ", ".join(
            f"{r['type']}={r.get('threshold', r.get('days_before_expiry'))}" for r in p.exit_rules
        ) or "NO EXIT RULES"
        lines.append(f"- **{p.position_id}** [{p.status}] {p.strategy} on {p.underlying} "
                      f"(trust: {p.trust_tier()})")
        lines.append(f"  legs: {', '.join(p.symbols) or '(none)'} | exits: {rules}")
        lines.append(f"  thesis: {p.thesis[:200]}")
    return "\n".join(lines)


async def run_tick(
    config: Config, *, verbose: bool = True, force_decide: bool = False
) -> dict[str, Any]:
    journal = Journal(config.paths.journal)
    inbox = Inbox(config.paths, max_retries=config.max_retries)
    store = PositionStore(config.paths.wiki)
    wiki = Wiki(config.paths.wiki)
    calib = CalibrationStore(config.paths.state / "forecasts.jsonl")

    n = _tick_count(config)
    tools_list = await mcp_client.get_tools(config)
    tools = {t.name: t for t in tools_list}

    mem = await ElfmemAdapter.build(config.paths.state / "elfmem.db")
    await mem.begin(task_type="trade_decision")  # active-hours clock; no auto-dream (see module docstring)

    try:
        # ---------- fast path: every tick, no LLM ----------
        sensed = await sensors.collect(tools, config, inbox, n, verbose=verbose)
        snap = await analytics.snapshot(tools)
        recon = await reconcile.reconcile(store, snap, journal, mem, wiki, calib)
        triggered = await exit_rules.run(
            store, snap, tools, journal, config.deadline, mem, wiki,
            calibration=calib, verbose=verbose
        )

        if verbose:
            print(f"[tick {n}] market_open={snap.market_open} equity=${snap.equity:,.0f} "
                  f"holdings={len(snap.broker_positions)}")
            print(f"[tick {n}] reconcile: {reconcile.summarise(recon)}")
            if triggered:
                print(f"[tick {n}] exit rules closed: {triggered}")

        # ---------- market closed: housekeeping, not decide ----------
        # force_decide exercises the full reasoning chain outside market hours.
        # Orders queue rather than fill, so this tests the DECISION, not the
        # execution - useful for development and for demoing the agent's
        # reasoning without waiting for the bell.
        if not snap.market_open and not force_decide:
            hk = await housekeeping.run(store, snap, mem, wiki, journal, tools=tools, verbose=verbose)
            return {"status": "housekeeping", "tick": n, "exits": triggered, **hk}

        # ---------- slow path: every N ticks ----------
        if n % config.decide_every_n_ticks != 0:
            if verbose:
                print(f"[tick {n}] fast path only (decide runs every "
                      f"{config.decide_every_n_ticks} ticks)")
            return {"status": "fast_only", "tick": n, "exits": triggered}

        items = inbox.pending()
        if not items:
            if verbose:
                print(f"[tick {n}] inbox empty - no decide cycle")
            return {"status": "idle", "tick": n, "exits": triggered}

        batch = ids.batch_id([i.id for i in items])
        prior = journal.unresolved_decision(batch)
        if prior and verbose:
            print(f"[tick {n}] resuming unresolved decision {prior['id']} (not re-deciding)")

        # The model authors every tool argument, so without this it invents its
        # own client_order_id and INV-18's idempotency guarantee silently evaporates.
        guarded = tool_guard.enforce_order_ids(tools_list, batch)

        query = " ".join(config.watchlist) + " options setup"
        ctx = await mem.assemble_context(query)

        decision_id = journal.append(  # write-ahead (INV-18)
            "decision",
            batch=batch,
            model=config.model,
            tick=n,
            item_ids=[i.id for i in items],
            resumed_from=prior["id"] if prior else None,
            elfmem_blocks=ctx.blocks,
        )

        shared: dict[str, Any] = {}
        sim_tool = local_tools.build_simulate_experiments(shared)
        size_tool = local_tools.build_size_position(
            calib, snap.equity or 100000.0, len(store.open_positions())
        )
        record_tool = local_tools.build_record_position(
            store, decision_id, elfmem_blocks=ctx.blocks, generated_by=config.model,
            calibration=calib,
            sources=[{"id": i.id, "resource": f"inbox/{i.id}", "author": i.source}
                     for i in items],
            shared=shared,
        )
        agent_tools = guarded + [sim_tool, size_tool, record_tool]
        agent = create_react_agent(build_model(config), agent_tools, prompt=SYSTEM_PROMPT)

        prompt_parts = [snap.render(), _render_positions(store)]
        if ctx.text:
            prompt_parts.append(f"## What you remember\n\n{ctx.text}")
        prompt_parts.append(
            "## Observations this cycle\n\n"
            + "\n".join(f"- [{i.type} | trust={i.trust}] {json.dumps(i.payload)}" for i in items)
        )
        cal = calib.score()
        if cal.n:
            prompt_parts.append(
                f"## Your calibration so far\n\n{cal.verdict()}\n\n"
                f"Base rate: {cal.base_rate:.0%} of your closed positions were profitable. "
                f"Use this to set `confidence` honestly - it is scored."
            )
        prompt_parts.append(
            f"## Constraints\n- Competition deadline: {config.deadline} "
            f"(everything is force-closed then, so prefer expiries well inside it).\n"
            f"- Watchlist: {', '.join(config.watchlist)}"
        )
        if prior:
            prompt_parts.append(
                "## Resuming\nA previous decision for this batch did not complete. "
                "Its order id is idempotent, so re-attempting the same action is safe - "
                "a duplicate will be rejected."
            )
        prompt = "\n\n".join(prompt_parts)

        try:
            result = await agent.ainvoke({"messages": [("user", prompt)]})
        except Exception as exc:  # noqa: BLE001
            cause = failures.classify(exc)
            journal.append("error", batch=batch, decision_ref=decision_id,
                           cause=cause.value, error=repr(exc))
            for it in items:
                inbox.record_failure(it, reason=f"agent error: {exc!r}", cause=cause)
            if verbose:
                print(f"\n[tick {n}] FAILED ({cause.value}): {type(exc).__name__}: {exc}")
                print(f"\n  {failures.advice(cause, exc)}\n")
            raise

        messages = result["messages"]
        final = messages[-1]
        summary_text = _text_of(final)
        calls = [tc for m in messages for tc in (getattr(m, "tool_calls", None) or [])]
        orders = [tc for tc in calls if tc.get("name") in mcp_client.ORDER_TOOLS]
        recorded = [tc for tc in calls if tc.get("name") == "record_position"]

        journal.append(
            "execution" if orders else "no_op",
            batch=batch,
            decision_ref=decision_id,
            model=config.model,
            tick=n,
            client_order_id=ids.client_order_id(batch) if orders else None,
            tool_calls=[tc.get("name") for tc in calls],
            order_calls=[
                {"name": tc.get("name"),
                 "args_as_model_supplied": tc.get("args"),
                 "client_order_id_enforced": ids.client_order_id(batch)}
                for tc in orders
            ],
            positions_recorded=len(recorded),
            summary=summary_text[:2000],
        )

        inbox.archive(items)

        # An order placed without a recorded position has no exit rules and
        # nothing can act on it - worth surfacing rather than discovering it days later.
        if orders and not recorded:
            print("\n[tick] WARNING: order placed but record_position was not called - "
                  "this position has no exit rules and the evaluator cannot see it.")

        if verbose:
            print(f"\n[tick {n}] tools: {[tc.get('name') for tc in calls] or 'none'}")
            print(f"[tick {n}] orders={len(orders)} positions_recorded={len(recorded)}")
            print(f'\n--- agent ---\n{summary_text}\n')

        return {"status": "done", "tick": n, "batch": batch, "orders": len(orders),
                "recorded": len(recorded), "exits": triggered}
    finally:
        await mem.end()  # no dream() here - see module docstring
        await mem.close()
