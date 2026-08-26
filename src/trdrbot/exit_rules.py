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

from . import mcp_client
from .analytics import Snapshot, _f
from .journal import Journal
from .positions import Position, PositionStore

WINDOW = 3  # M
NEEDED = 2  # N
MAGNITUDE_OVERRIDE = 2.0


def _pct(pos: Position, held: dict[str, dict[str, Any]]) -> float | None:
    """Position-level P&L fraction, summed across legs (INV-19)."""
    legs = [held[s] for s in pos.symbols if s in held]
    if not legs:
        return None
    cost = sum(abs(_f(l.get("cost_basis"))) for l in legs)
    if cost == 0:
        return None
    return sum(_f(l.get("unrealized_pl")) for l in legs) / cost


def _days_to(expiry: str) -> int | None:
    try:
        return (date.fromisoformat(str(expiry)) - date.today()).days
    except (ValueError, TypeError):
        return None


def evaluate(pos: Position, snap: Snapshot, deadline: str) -> tuple[str | None, str]:
    """Return (close_reason, explanation). close_reason None means hold."""
    # The deadline sweep is independent of any position's own expiry (INV-26).
    # A conventional-DTE position would otherwise never resolve inside the
    # competition, and the learning loop would produce nothing at all.
    try:
        if date.today() >= date.fromisoformat(deadline):
            return "deadline", f"competition deadline {deadline} reached"
    except (ValueError, TypeError):
        pass

    held = snap.by_symbol()
    pnl = _pct(pos, held)
    dte = _days_to(pos.expiry)

    for rule in pos.exit_rules:
        kind = rule.get("type")
        key = str(kind)

        if kind == "time_stop":
            n = int(rule.get("days_before_expiry", 0))
            if dte is not None and dte <= n:
                return "time_stop", f"{dte}d to expiry <= {n}d"
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
            return kind, f"{pnl:+.1%} beyond {MAGNITUDE_OVERRIDE}x threshold {thr:+.0%} - immediate"
        if sum(history) >= NEEDED:
            return kind, f"{pnl:+.1%} vs threshold {thr:+.0%} ({sum(history)}/{len(history)} checks)"

    return None, ""


async def run(
    store: PositionStore,
    snap: Snapshot,
    tools: dict[str, Any],
    journal: Journal,
    deadline: str,
    *,
    verbose: bool = True,
) -> list[str]:
    """Evaluate every still-open position and close those that trigger."""
    triggered: list[str] = []

    for pos in store.open_positions():
        if pos.status != "open":
            continue  # only fully-open positions are candidates

        reason, why = evaluate(pos, snap, deadline)
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
        triggered.append(pos.position_id)

    return triggered
