"""C24 - evaluate agent-authored exit rules. Deterministic, no LLM (D-017).

Not a guardrail. Every rule here was written by the agent itself at entry, and
it may rewrite or delete any of them on any decide cycle. This just makes sure
that what it said it would do actually happens, on a cadence far faster than
the LLM runs.

Every exit rule is the same operation: read a SIGNAL, compare it to a
threshold in one direction, debounce. Rule types differ only in which signal
they read, so they live in a registry (D-037) rather than as branches - the
same shape as the sensor registry (D-015). Adding a rule type is a registry
entry plus one clause in `_normalise`, not another copy of the debounce logic.

Invariants preserved from the regression pass (D-019):
  - N-of-M debounce, not strictly-consecutive: a single stale or abnormally
    wide quote must not reset progress toward a real breach.
  - Magnitude override: a breach far beyond the threshold fires immediately,
    because that is not plausibly a quote artifact. Expressed once, as
    relative overshoot, so it means the right thing for percentages (2x a
    -50% stop) and for prices (1% through a level) without special cases.
  - INV-19: a trigger closes ALL legs. Closing one leg of a spread can leave
    an unbounded naked short - strictly worse than the position it protected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


def _days_to(day: str) -> int | None:
    try:
        return (date.fromisoformat(str(day)) - date.today()).days
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class ExitSignal:
    """One observable an exit rule can watch."""

    name: str
    read: Callable[[Position, Snapshot, str], float | None]
    #: Relative overshoot past the threshold that fires immediately, skipping
    #: debounce. 1.0 = twice the threshold (the old percentage rule); 0.01 =
    #: 1% through a price level; 0.0 = any breach is decisive (time is not
    #: noisy, so a date-based rule never needs confirming).
    immediate_overshoot: float
    render: Callable[[float], str]


#: The registry. A new rule type usually needs no new signal at all.
EXIT_SIGNALS: dict[str, ExitSignal] = {
    # Noisiest signal available on an options position: a wide or stale quote
    # can print -100%-of-credit on a healthy spread. Debounce matters most here.
    "position_mark": ExitSignal(
        "position_mark", lambda p, s, d: position_pnl_pct(p.symbols, s),
        1.0, lambda v: f"{v:+.1%}",
    ),
    # What a professional actually exits on: the underlying breaking the level
    # that invalidates the thesis. Prints continuously and tightly.
    "underlying": ExitSignal(
        "underlying", lambda p, s, d: s.underlying_prices.get(p.underlying),
        0.01, lambda v: f"{v:.2f}",
    ),
    "days_to_expiry": ExitSignal(
        "days_to_expiry", lambda p, s, d: _days_to(p.expiry),
        0.0, lambda v: f"{v:.0f}d",
    ),
    # The competition sweep (INV-26): an ordinary rule, implicit on every
    # position, rather than a special case sitting above the loop.
    "days_to_deadline": ExitSignal(
        "days_to_deadline", lambda p, s, d: _days_to(d),
        0.0, lambda v: f"{v:.0f}d",
    ),
}

#: Lower fires first when several rules trigger in one tick. Risk before
#: reward: a position simultaneously at its stop and its target (a crazy
#: quote, or a gap through both) must exit as a stop, not book a fictional
#: win. Previously this was list order, i.e. accidental.
_PRIORITY = {"deadline": 0, "stop_loss": 1, "underlying_stop": 1,
             "time_stop": 2, "profit_target": 3}


def _pct(v: Any) -> float:
    return _f(str(v).rstrip("%")) / 100.0


def _normalise(rule: dict[str, Any]) -> tuple[str, str, float, str] | None:
    """A rule in any recorded form -> (signal, direction, threshold, type).

    Reads both current and legacy shapes - position files written before the
    registry carry `basis: position_mark` and a "-100%" string threshold.
    Returns None for anything unrecognised or incomplete, which holds rather
    than guesses.
    """
    kind = str(rule.get("type") or "")

    if kind == "deadline":
        return ("days_to_deadline", "below", 0.0, kind)
    if kind == "stop_loss" and rule.get("threshold") is not None:
        return ("position_mark", "below", _pct(rule["threshold"]), kind)
    if kind == "profit_target" and rule.get("threshold") is not None:
        return ("position_mark", "above", _pct(rule["threshold"]), kind)
    if kind == "time_stop":
        return ("days_to_expiry", "below", float(rule.get("days_before_expiry", 0)), kind)
    if kind == "underlying_stop":
        level = _f(str(rule.get("level")), 0.0)
        if level > 0:
            return ("underlying", str(rule.get("direction", "below")), level, kind)
    return None


def _overshoot(x: float, thr: float, direction: str) -> float:
    """How far past the threshold, relative to the threshold's own size."""
    past = (thr - x) if direction == "below" else (x - thr)
    return past / abs(thr) if thr else past


def watched_signals(pos: Position) -> list[str]:
    """Which signals this position's rules actually read (F1 transparency).

    The failure that motivated the underlying stop was a position whose agent
    NARRATED a thesis-invalidation level while its coded rules watched only
    the mark. Surfacing this at record time makes the divergence visible
    instead of silent - reporting, not gating (D-009).
    """
    out: list[str] = []
    for rule in pos.exit_rules:
        norm = _normalise(rule)
        if norm and norm[0] not in out:
            out.append(norm[0])
    return out


def evaluate(pos: Position, snap: Snapshot, deadline: str) -> tuple[str | None, str, float | None]:
    """Return (close_reason, explanation, pnl_pct). None means hold.

    pnl_pct comes back alongside the reason so the caller can feed it straight
    to learn.on_resolution() without recomputing - the position's net mark is
    exactly the signal credit assignment needs (D-018 #9).
    """
    pnl = position_pnl_pct(pos.symbols, snap)
    # Remember the last time we could see it. A position that closes outside
    # our rules leaves the broker, taking its final P&L with it (D-056).
    if pnl is not None:
        pos.last_pnl_pct = pnl
    fired: list[tuple[int, str, str]] = []

    # Self-healing: drop debounce state written by the pre-registry engine,
    # which keyed on rule type alone. Inert (new keys always contain ":") but
    # position files are human-readable artifacts and stale state reads as
    # live state to anyone inspecting one.
    for stale in [k for k in pos.exit_state if ":" not in k]:
        pos.exit_state.pop(stale, None)

    # The deadline is an implicit rule on every position (INV-26): without it
    # a conventional-DTE position never resolves inside the competition and
    # the learning loop produces nothing at all.
    for rule in [{"type": "deadline"}] + list(pos.exit_rules):
        norm = _normalise(rule)
        if norm is None:
            continue
        sig_name, direction, thr, kind = norm
        signal = EXIT_SIGNALS.get(sig_name)
        if signal is None:
            continue

        x = signal.read(pos, snap, deadline)
        if x is None:
            continue  # unobservable signal holds; it never fires blind

        breached = x <= thr if direction == "below" else x >= thr

        # Debounce state is keyed by the WHOLE rule, not its type: two
        # underlying stops at different levels are different rules and must
        # not share a history (they did, before the registry).
        key = f"{sig_name}:{direction}:{thr:g}"
        history = list(pos.exit_state.get(key, []))[-(WINDOW - 1):] + [breached]
        pos.exit_state[key] = history
        if not breached:
            continue

        decisive = _overshoot(x, thr, direction) >= signal.immediate_overshoot
        if decisive or sum(history) >= NEEDED:
            why = (
                f"{sig_name} {signal.render(x)} {direction} {signal.render(thr)}"
                + (" - decisive, immediate" if decisive
                   else f" ({sum(history)}/{len(history)} checks)")
            )
            fired.append((_PRIORITY.get(kind, 5), kind, why))

    if not fired:
        return None, "", pnl
    fired.sort(key=lambda t: t[0])
    _, kind, why = fired[0]
    return kind, why, pnl


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
    watched = rules_checked = 0

    for pos in store.open_positions():
        if pos.status != "open":
            continue  # only fully-open positions are candidates
        watched += 1
        rules_checked += len(watched_signals(pos)) + 1  # +1 for the implicit deadline

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

    # Heartbeat, same reason as housekeeping's `interim_run` (D-074): the health
    # probe read the `exit` rows themselves as evidence the engine had RUN, so
    # "ran" and "produced" were the same number and it could only ever report
    # "never ran". Live proof it mattered: an open SPY spread with five rules
    # armed and a populated debounce history read as `exit_rules never ran`,
    # because nothing had breached - which is the engine working, not the
    # engine missing. An engine that evaluates and correctly holds must be
    # distinguishable from one that is not evaluating at all.
    if watched:
        journal.append("exit_run", positions=watched, rules=rules_checked,
                       triggered=len(triggered))

    return triggered
