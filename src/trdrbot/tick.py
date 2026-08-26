"""One tick, split by cost (D-017).

    EVERY TICK (cheap, deterministic, no LLM)
        C21 analytics  ->  C13 reconcile  ->  C24 exit rules
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        That order is the D-019 fix (INV-25): reconciling first means a
        position the broker already resolved is terminal before exit rules
        run, so it is excluded by construction rather than by a later check.

    EVERY N TICKS (expensive)
        resume-check -> assemble context -> decide -> act -> journal

Fast monitoring with slow deciding shortens the exposure window while cutting
LLM spend - the exit evaluator needs no model to notice a breached stop.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.prebuilt import create_react_agent

from . import analytics, exit_rules, failures, ids, local_tools, mcp_client, reconcile, tool_guard
from .config import Config
from .inbox import Inbox, Item
from .journal import Journal
from .llm import SYSTEM_PROMPT, build_model
from .positions import PositionStore


def _tick_count(config: Config) -> int:
    p = config.paths.state / "tick_count"
    n = int(p.read_text().strip() or 0) + 1 if p.exists() else 1
    p.write_text(str(n))
    return n


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
        lines.append(f"- **{p.position_id}** [{p.status}] {p.strategy} on {p.underlying}")
        lines.append(f"  legs: {', '.join(p.symbols) or '(none)'} | exits: {rules}")
        lines.append(f"  thesis: {p.thesis[:200]}")
    return "\n".join(lines)


async def run_tick(config: Config, *, verbose: bool = True) -> dict[str, Any]:
    journal = Journal(config.paths.journal)
    inbox = Inbox(config.paths, max_retries=config.max_retries)
    store = PositionStore(config.paths.wiki)

    n = _tick_count(config)
    tools_list = await mcp_client.get_tools(config)
    tools = {t.name: t for t in tools_list}

    # ---------- fast path: every tick, no LLM ----------
    snap = await analytics.snapshot(tools)
    recon = reconcile.reconcile(store, snap, journal)
    triggered = await exit_rules.run(
        store, snap, tools, journal, config.deadline, verbose=verbose
    )

    if verbose:
        print(f"[tick {n}] market_open={snap.market_open} equity=${snap.equity:,.0f} "
              f"holdings={len(snap.broker_positions)}")
        print(f"[tick {n}] reconcile: {reconcile.summarise(recon)}")
        if triggered:
            print(f"[tick {n}] exit rules closed: {triggered}")

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

    # The model authors every tool argument, so without this it invents its own
    # client_order_id and INV-18's idempotency guarantee silently evaporates.
    guarded = tool_guard.enforce_order_ids(tools_list, batch)

    decision_id = journal.append(  # write-ahead (INV-18)
        "decision",
        batch=batch,
        model=config.model,
        tick=n,
        item_ids=[i.id for i in items],
        resumed_from=prior["id"] if prior else None,
    )

    agent_tools = guarded + [local_tools.build_record_position(store, decision_id)]
    agent = create_react_agent(build_model(config), agent_tools, prompt=SYSTEM_PROMPT)

    prompt = "\n\n".join([
        snap.render(),
        _render_positions(store),
        "## Observations this cycle\n\n"
        + "\n".join(f"- [{i.type} | trust={i.trust}] {json.dumps(i.payload)}" for i in items),
        f"## Constraints\n- Competition deadline: {config.deadline} "
        f"(everything is force-closed then, so prefer expiries well inside it).\n"
        f"- Watchlist: {', '.join(config.watchlist)}",
    ])
    if prior:
        prompt += (
            f"\n\n## Resuming\nA previous decision for this batch did not complete. "
            f"Its order id is idempotent, so re-attempting the same action is safe - "
            f"a duplicate will be rejected."
        )

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
        summary=str(getattr(final, "content", ""))[:2000],
    )

    inbox.archive(items)

    # An order placed without a recorded position has no exit rules and nothing
    # can act on it - worth surfacing rather than discovering it days later.
    if orders and not recorded:
        print("\n[tick] WARNING: order placed but record_position was not called - "
              "this position has no exit rules and the evaluator cannot see it.")

    if verbose:
        print(f"\n[tick {n}] tools: {[tc.get('name') for tc in calls] or 'none'}")
        print(f"[tick {n}] orders={len(orders)} positions_recorded={len(recorded)}")
        print(f"\n--- agent ---\n{getattr(final, 'content', '')}\n")

    return {"status": "done", "tick": n, "batch": batch, "orders": len(orders),
            "recorded": len(recorded), "exits": triggered}
