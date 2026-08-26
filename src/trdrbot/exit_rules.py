"""C24 - evaluate agent-authored exit rules. Deterministic, no LLM (D-017).

Not a guardrail. Every rule here was written by the agent itself at entry, and
it may rewrite or delete any of them on any decide cycle. This just makes sure
that what it said it would do actually happens, on a cadence far faster than
the LLM runs.

Two rules from the regression pass (D-019):
  - N-of-M debounce, not strictly-consecutive. A single stale or abnormally
    wide quote must not reset progress toward a real breach.
  - Magnitude override: a breach beyond 2x the threshold fires immediately,
    because that is not plausibly a quote artifact.

And INV-19: a trigger closes ALL legs of a position. Closing one leg of a
spread can leave an unbounded naked short - strictly worse than the position it
was meant to protect.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import learn, mcp_client
from .analytics import Snapshot, _f, position_pnl_pct
from .calibration import CalibrationStore
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import Position, PositionStore
from .wiki import Wiki

WINDOW = 3  # M
NEEDED = 2  # N
MAGNITUDE_OVERRIDE = 2.0


def _days_to(expiry: str) -> int | None:
    try:
        return (date.fromisoformat(str(expiry)) - date.today()).days
    except (ValueError, TypeError):
        return None


def evaluate(pos: Position, snap: Snapshot, deadline: str) -> tuple[str | None, str, float | None]:
    """Return (close_reason, explanation, pnl_pct). close_reason None means hold.

    pnl_pct is returned alongside the reason so the caller can feed it
    straight to learn.on_resolution() without recomputing it - the position's
    net mark is exactly the signal credit assignment needs (D-018 #9).
    """
    pnl = position_pnl_pct(pos.symbols, snap)

    # The deadline sweep is independent of any position's own expiry (INV-26).
    # A conventional-DTE position would otherwise never resolve inside the
    # competition, and the learning loop would produce nothing at all.
    try:
        if date.today() >= date.fromisoformat(deadline):
            return "deadline", f"competition deadline {deadline} reached", pnl
    except (ValueError, TypeError):
        pass

    dte = _days_to(pos.expiry)

    for rule in pos.exit_rules:
        kind = rule.get("type")
        key = str(kind)

        if kind == "time_stop":
            n = int(rule.get("days_before_expiry", 0))
            if dte is not None and dte <= n:
                return "time_stop", f"{dte}d to expiry <= {n}d", pnl
            continue

        if pnl is None:
            continue

        threshold = rule.get("threshold")
        if threshold is None:
            continue
        thr = _f(str(threshold).rstrip("%")) / 100.0

        if kind == "stop_loss":
            breached = pnl <= thr
            severe = pnl <= thr * MAGNITUDE_OVERRIDE
        elif kind == "profit_target":
            breached = pnl >= thr
            severe = pnl >= thr * MAGNITUDE_OVERRIDE
        else:
            continue

        history = list(pos.exit_state.get(key, []))[-(WINDOW - 1) :] + [breached]
        pos.exit_state[key] = history

        if severe:
            return kind, f"{pnl:+.1%} beyond {MAGNITUDE_OVERRIDE}x threshold {thr:+.0%} - immediate", pnl
        if sum(history) >= NEEDED:
            return kind, f"{pnl:+.1%} vs threshold {thr:+.0%} ({sum(history)}/{len(history)} checks)", pnl

    return None, "", pnl


async def run(
    store: PositionStore,
    snap: Snapshot,
    tools: dict[str, Any],
    journal: Journal,
    deadline: str,
    mem: ElfmemAdapter,
    wiki: Wiki,
    *,
    calibration: CalibrationStore | None = None,
    verbose: bool = True,
) -> list[str]:
    """Evaluate every still-open position and close those that trigger."""
    triggered: list[str] = []

    for pos in store.open_positions():
        if pos.status != "open":
            continue  # only fully-open positions are candidates

        reason, why, pnl = evaluate(pos, snap, deadline)
        store.save(pos)  # persist debounce state either way

        if not reason:
            continue

        # INV-17: first detector wins. If reconciliation already resolved this
        # position earlier in the tick, transition refuses and we do not act.
        if not store.transition(pos, "closing", close_reason=reason):
            continue

        if verbose:
            print(f"[exit] {pos.position_id}: {reason} - {why}")

        closed_ok = True
        for symbol in pos.symbols:  # ALL legs (INV-19)
            try:
                await mcp_client.call(tools, "close_position", symbol_or_asset_id=symbol)
            except Exception as exc:  # noqa: BLE001
                closed_ok = False
                print(f"[exit] failed closing leg {symbol}: {exc!r}")

        journal.append(
            "exit",
            position_id=pos.position_id,
            close_reason=reason,
            explanation=why,
            legs=pos.symbols,
            submitted=closed_ok,
        )
        if closed_ok:
            store.transition(pos, "closed")  # INV-17: terminal, exactly once
            await learn.on_resolution(pos, store, mem, wiki, journal, pnl_pct=pnl,
                                       calibration=calibration)  # F3
        triggered.append(pos.position_id)

    return triggered
