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
    idle,
    prompts,
    sizing,
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


def _render_positions(store: PositionStore, snap: "analytics.Snapshot | None" = None) -> str:
    """Two-tier context (D-019): detail for what needs attention, one line for the rest."""
    positions = store.open_positions()
    if not positions:
        return "## Our positions\n\n(none)"

    lines = ["## Our positions", ""]
    # Book shape first: correlated exposure in its native units. Three
    # bullish put spreads on three tickers LOOK diversified and ARE one
    # +delta/-vega/+theta position - this line is where that becomes
    # visible before a fourth one gets added (D-040).
    if snap is not None:
        bg = analytics.book_greeks(positions, snap.underlying_prices)
        if bg:
            skip = f" ({bg['positions_skipped']} unpriced)" if bg["positions_skipped"] else ""
            lines.append(
                f"Book greeks (est., entry IV): delta ${bg['delta_dollars']:+,.0f}"
                f" | theta ${bg['theta_dollars']:+,.0f}/day"
                f" | vega ${bg['vega_dollars']:+,.0f}/IVpt{skip}. Before adding a"
                f" position, check whether it grows or offsets these."
            )
            lines.append("")
    for p in positions:
        rules = ", ".join(
            f"{r['type']}={r.get('threshold', r.get('days_before_expiry'))}" for r in p.exit_rules
        ) or "NO EXIT RULES"
        lines.append(f"- **{p.position_id}** [{p.status}] {p.strategy} on {p.underlying} "
                      f"(trust: {p.trust_tier()})")
        lines.append(f"  legs: {', '.join(p.symbols) or '(none)'} | exits: {rules}")
        lines.append(f"  thesis: {p.thesis[:200]}")
    return "\n".join(lines)


#: A move of this fraction in an underlying we hold is worth a fresh look,
#: even with nothing in the news. Roughly a third of a typical daily range on
#: an index - big enough not to fire on noise, small enough to precede a stop.
PULSE_MOVE = 0.004
#: And look at least this often while the market is open, regardless.
PULSE_MAX_SILENCE_MIN = 90


def _market_pulse(store, snap, journal, config) -> dict | None:
    """Should the agent look, absent any external event? Deterministic, no LLM."""
    positions = [p for p in store.open_positions() if p.status == "open"]
    if not positions:
        return None  # nothing at risk; silence is correct

    last = journal.last_decision_at()
    silent_min = None
    if last is not None:
        from datetime import datetime, timezone
        silent_min = (datetime.now(timezone.utc) - last).total_seconds() / 60.0

    moves = []
    for p in positions:
        px = snap.underlying_prices.get(p.underlying)
        if px and p.entry_spot:
            moves.append((p.underlying, (px / p.entry_spot) - 1.0))

    big = [(u, m) for u, m in moves if abs(m) >= PULSE_MOVE]
    if big:
        return {
            "reason": "material move since entry: "
                      + ", ".join(f"{u} {m:+.2%}" for u, m in big),
            "moves": dict(moves),
            "positions": [p.position_id for p in positions],
        }
    if silent_min is None or silent_min >= PULSE_MAX_SILENCE_MIN:
        return {
            "reason": f"no decide cycle for {silent_min:.0f}min" if silent_min
                      else "no decide cycle yet today",
            "moves": dict(moves),
            "positions": [p.position_id for p in positions],
        }
    return None


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
        snap = await analytics.snapshot(
        tools, underlyings=sorted({p.underlying for p in store.open_positions() if p.underlying})
    )
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
            return {"status": "housekeeping", "tick": n, "market_open": snap.market_open, "exits": triggered, **hk}

        # ---------- slow path: every N ticks ----------
        if n % config.decide_every_n_ticks != 0:
            if verbose:
                print(f"[tick {n}] fast path only (decide runs every "
                      f"{config.decide_every_n_ticks} ticks)")
            return {"status": "fast_only", "tick": n, "market_open": snap.market_open, "exits": triggered}

        items = inbox.pending()

        # Stale candidates are worse than none: they were priced against
        # quotes that no longer exist, and the agent has correctly declined
        # them on exactly that basis. Expire before they reach the prompt.
        if items:
            fresh = inbox.expire_stale(idle.OPPORTUNITY_STALE_MIN, journal)
            if fresh:
                items = inbox.pending()
                if verbose:
                    print(f"[tick {n}] expired {fresh} stale opportunity item(s)")

        if not items:
            # An empty inbox is several states, not one (D-043). The ladder
            # picks the cheapest rung that the situation actually justifies.
            from datetime import datetime
            import zoneinfo
            et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
            action = idle.decide(
                market_open=snap.market_open,
                positions=store.open_positions(),
                underlying_prices=snap.underlying_prices,
                last_decision_at=journal.last_decision_at(),
                last_hunt_at=journal.last_hunt_at(),
                open_risk_usd=sum(p.max_loss_usd or 0.0 for p in store.open_positions()),
                equity=snap.equity or 100000.0,
                risk_cap_fraction=sizing.PORTFOLIO_MAX_AT_RISK,
                minutes_to_close_=idle.minutes_to_close(et),
            )
            if verbose:
                print(f"[tick {n}] idle -> {action.level}: {action.reason}")

            if action.level == "hunt" and tools:
                # Intraday opportunity generation, priced at LIVE quotes. Every
                # candidate the agent had seen until now was researched while
                # the market was CLOSED, and it kept declining them for exactly
                # that reason ("any spread I priced now would be simulated on
                # prices that no longer exist").
                try:
                    from . import discovery
                    r = await discovery.run(tools, config, inbox, wiki, journal,
                                            verbose=verbose)
                    journal.append("hunt", opportunities=r["opportunities"],
                                   reason=action.reason)
                    items = inbox.pending()
                except Exception as exc:  # noqa: BLE001 - hunting is advisory
                    print(f"[tick {n}] hunt failed, continuing: {exc!r}")
                    journal.append("hunt", opportunities=0, error=repr(exc))
            elif action.level == "review":
                inbox.write("position_review", {
                    "reason": action.reason, **action.detail,
                }, source="idle", trust="primary")
                items = inbox.pending()

        if not items:
            if verbose:
                print(f"[tick {n}] inbox empty - no decide cycle")
            return {"status": "idle", "tick": n, "market_open": snap.market_open, "exits": triggered}

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
            # Which prompts actually produced this decision. Cannot be
            # reconstructed later, so it is recorded now even though no
            # second variant exists yet (D-045).
            prompts=prompts.fingerprints(),
            item_ids=[i.id for i in items],
            resumed_from=prior["id"] if prior else None,
            elfmem_blocks=ctx.blocks,
        )

        shared: dict[str, Any] = {}
        sim_tool = local_tools.build_simulate_experiments(shared, config.paths.state)
        open_pos = store.open_positions()
        open_risk = sum(p.max_loss_usd or 0.0 for p in open_pos)
        by_underlying: dict[str, float] = {}
        for op in open_pos:
            if op.underlying:
                by_underlying[op.underlying.upper()] = (
                    by_underlying.get(op.underlying.upper(), 0.0) + (op.max_loss_usd or 0.0)
                )
        size_tool = local_tools.build_size_position(
            calib, snap.equity or 100000.0, len(open_pos),
            open_risk_usd=open_risk, open_risk_by_underlying=by_underlying, shared=shared,
        )
        record_tool = local_tools.build_record_position(
            store, decision_id, elfmem_blocks=ctx.blocks, generated_by=config.model,
            calibration=calib,
            sources=[{"id": i.id, "resource": f"inbox/{i.id}", "author": i.source}
                     for i in items],
            shared=shared,
        )
        guarded = tool_guard.redirect_whole_book_close(
            guarded, lambda: len([p for p in store.open_positions() if p.status == "open"])
        )
        agent_tools = guarded + [sim_tool, size_tool, record_tool]
        agent = create_react_agent(build_model(config), agent_tools, prompt=SYSTEM_PROMPT)

        prompt_parts = [snap.render(), _render_positions(store, snap)]
        if config.events:
            from datetime import date as _date
            ev_lines = []
            for ev in config.events:
                try:
                    days = (_date.fromisoformat(str(ev["date"])) - _date.today()).days
                except (KeyError, ValueError):
                    continue
                if 0 <= days <= 14:
                    ev_lines.append(f"- {ev['date']} ({days}d away): {ev.get('name','')}")
            if ev_lines:
                prompt_parts.append(
                    "## Known macro events (binary risk - check every holding window)\n"
                    + "\n".join(ev_lines)
                )
        regime = wiki.read("context/regime")
        if regime and regime.body.strip():
            prompt_parts.append(
                f"## Market regime (research desk, {regime.frontmatter.get('generated',{}).get('at','')[:10]})\n\n"
                + regime.body[:1800]
            )
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

        return {"status": "done", "tick": n, "market_open": snap.market_open, "batch": batch, "orders": len(orders),
                "recorded": len(recorded), "exits": triggered}
    finally:
        await mem.end()  # no dream() here - see module docstring
        await mem.close()
