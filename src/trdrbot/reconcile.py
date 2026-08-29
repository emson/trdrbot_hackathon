"""C13 - reconcile broker truth against our records. Deterministic, no LLM.

Runs BEFORE the exit-rule evaluator every tick (INV-25). That ordering is the
fix from D-019: with C24 first, it could evaluate rules against a position the
broker had already resolved by assignment or expiry, acting on stale local
state. Reconciling first flips such positions to terminal, so C24's candidate
set excludes them by construction rather than by an extra check.
"""

from __future__ import annotations

from typing import Any

from . import learn
from .analytics import Snapshot
from .calibration import CalibrationStore
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import PositionStore
from .wiki import Wiki


def _working_symbols(orders: list[dict[str, Any]]) -> set[str]:
    """Symbols with a live order, including the legs of a multi-leg order.

    Without this a pending limit order looks identical to a vanished position,
    and reconciliation kills a position that is merely waiting to fill.
    """
    out: set[str] = set()
    for o in orders:
        if o.get("symbol"):
            out.add(o["symbol"])
        for leg in o.get("legs") or []:
            if isinstance(leg, dict) and leg.get("symbol"):
                out.add(leg["symbol"])
    return out


async def reconcile(
    store: PositionStore, snap: Snapshot, journal: Journal, mem: ElfmemAdapter, wiki: Wiki,
    calibration: CalibrationStore | None = None,
) -> dict[str, list[str]]:
    """Diff broker holdings against our open position pages."""
    held = snap.by_symbol()
    working = _working_symbols(snap.open_orders)
    ours = store.open_positions()

    result: dict[str, list[str]] = {"phantom": [], "orphan": [], "drift": [], "filled": []}
    claimed: set[str] = set()
    #: THIS tick's failures, not a lifetime count - a heartbeat that reports a
    #: running total cannot show a rate, and the delta is what says whether
    #: memory is failing right now (D-088).
    learn_errors = 0

    for pos in ours:
        syms = pos.symbols
        claimed.update(syms)
        if not syms:
            continue

        present = [s for s in syms if s in held]
        pending = [s for s in syms if s in working]

        if pos.status == "opening":
            # Submitted but unconfirmed. Three outcomes, and telling them apart
            # is the whole point of the `opening` state.
            if present:
                pos.status = "open"
                store.save(pos)
                journal.append("reconciliation", position_id=pos.position_id,
                               finding="fill_confirmed", legs=present)
                ok = await learn.guarded(  # F2 - advisory, never aborts the fast path
                    learn.on_fill(pos, store, mem, journal),
                    journal, stage="on_fill", position_id=pos.position_id)
                learn_errors += 0 if ok else 1
                result["filled"].append(pos.position_id)
            elif pending:
                pass  # still working - leave it alone
            else:
                # No fill, no live order: the order died (expired, rejected,
                # cancelled). Never became real exposure, so `abandoned`.
                if store.transition(pos, "abandoned", close_reason="never_filled"):
                    journal.append("reconciliation", position_id=pos.position_id,
                                   finding="abandoned", detail="no fill and no working order")
                    result["phantom"].append(pos.position_id)
            continue

        if not present and not pending and pos.status in ("open", "closing", "adjusting"):
            # We think we hold it, the broker does not: expired, assigned, or
            # closed outside our loop. Terminal, and scored exactly once.
            if store.transition(pos, "closed", close_reason="external"):
                journal.append(
                    "reconciliation",
                    position_id=pos.position_id,
                    finding="phantom",
                    detail="in our records, absent at broker",
                )
                # F3: no P&L available - the position already vanished from
                # holdings by the time we noticed. D-018 #9 skips credit
                # assignment here rather than guessing a sign.
                ok = await learn.guarded(
                    learn.on_resolution(pos, store, mem, wiki, journal, pnl_fraction=None,
                                        calibration=calibration),
                    journal, stage="on_resolution", position_id=pos.position_id)
                learn_errors += 0 if ok else 1
                result["phantom"].append(pos.position_id)
        elif present and len(present) != len(syms) and not pending:
            journal.append(
                "reconciliation",
                position_id=pos.position_id,
                finding="leg_divergence",
                intended=syms,
                actual=present,
            )
            result["drift"].append(pos.position_id)

    # Heartbeat, same reason as `exit_run` and `attribution_run` (D-074):
    # learning was the only subsystem in this cluster with no record of its own
    # activity, so "ran and had nothing to learn from" and "stopped running"
    # were the same observation. `errors` is what makes a degraded elfmem
    # visible - the failures are advisory now, which is exactly why they need
    # somewhere to be counted.
    if result["filled"] or result["phantom"]:
        journal.append("learn_run",
                       fills=len(result["filled"]), resolutions=len(result["phantom"]),
                       errors=learn_errors)

    for symbol in held:
        if symbol not in claimed:
            # At the broker with no story of ours. A position we cannot explain
            # is still a position - record it rather than ignoring it.
            journal.append(
                "reconciliation",
                finding="orphan",
                symbol=symbol,
                detail="held at broker, no position page",
            )
            result["orphan"].append(symbol)

    return result


def summarise(result: dict[str, list[str]]) -> str:
    parts = [f"{k}={len(v)}" for k, v in result.items() if v]
    return ", ".join(parts) if parts else "clean"
