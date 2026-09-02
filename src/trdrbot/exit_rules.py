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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from . import blog, health, ids, learn, mcp_client, optmath
from .analytics import Snapshot, _f, position_pnl_fraction
from .calibration import CalibrationStore
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import Position, PositionStore
from .wiki import Wiki

WINDOW = 3  # M
NEEDED = 2  # N

#: Days before expiry at which a position carrying no time stop of its own is
#: closed. The gamma wall: short-dated premium concentrates its risk at the
#: strike into the final session, where delta flips on a small move and the
#: mark stops being a fair description of the risk. It also bounds the slow
#: bleed the scaffold found - a position pinned just above its stop rides to
#: expiry with nothing ever firing (G4/P5).
#:
#: The agent overrides it by writing ANY usable time_stop, including 0, which
#: means "hold to expiry deliberately". Same mechanism as the implicit deadline
#: rule (INV-26), which is the point: a default nobody has to remember.
IMPLICIT_TIME_STOP_DAYS = 1

#: Consecutive reconcile passes that must see a leg missing at the broker
#: before the remainder is closed. 2 = one confirmation tick, which on the open
#: cadence is five minutes of exposure - chosen to survive a single stale or
#: mid-fill snapshot, which is the only false positive this signal has.
#:
#: Tune it from the journal, never from taste: `leg_divergence` rows carry
#: `consecutive`, and a recovery writes `leg_divergence_cleared`. A stream of
#: cleared-at-1 rows says 2 is too tight; a real assignment sitting at 2 for
#: several ticks before anyone notices says it is too loose.
LEG_DIVERGENCE_CONFIRM = 2


def _days_to(day: str) -> int | None:
    try:
        return (date.fromisoformat(str(day)) - ids.market_today()).days
    except (ValueError, TypeError):
        return None


#: How much of the underlying's OWN expected move must already have happened
#: before a mark-based breach counts as decisive rather than debounced.
#:
#: A starting point, not a measurement - and deliberately the only number this
#: rule adds. Tune it from the journal's own `exit_run` rows once they have
#: counted real suppressions against real gaps (WU-4.10 records both), never by
#: taste. At 0.25 a genuine gap - which moves the underlying hard - still closes
#: on the first print, while a lone wide quote on an unmoved underlying waits
#: for the 2-of-3 confirmation that already exists for it.
CORROBORATION_FRACTION = 0.25


def _days_since(iso: str) -> float:
    """Days a position has been open, floored at one.

    The floor matters: `expected_move` over zero days is zero, which would make
    every threshold trivially met on the day of entry - the opposite of the
    intent. One day is the tightest honest yardstick.
    """
    try:
        opened = datetime.fromisoformat(str(iso))
    except (ValueError, TypeError):
        return 1.0
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    return max((ids.utc_now() - opened).total_seconds() / 86400.0, 1.0)


def _mark_corroborated(pos: Position, snap: Snapshot, direction: str) -> bool | None:
    """Does the UNDERLYING agree with what the option mark is claiming?

    The registry set `position_mark`'s immediate_overshoot to 1.0 on the grounds
    that a breach at twice the threshold "is not plausibly a quote artifact" -
    while its own comment says a wide or stale quote "can print -100%-of-credit
    on a HEALTHY spread". Those two statements name the SAME number: -100%
    against the standard -50% stop is exactly overshoot 1.0. So the single most
    common artifact on a credit spread skipped the debounce that exists for it
    and closed the position on one print, at the worst quote of the day (I-42).

    The underlying is the disambiguator - it prints continuously and tightly,
    which is why thesis stops watch it. A real gap moves it; a wide quote does
    not. So a loss claim must be matched by a real adverse move before it is
    believed on a single print; otherwise it debounces like any other breach.

    Returns None when the position cannot be judged (a legacy row without entry
    greeks, an unpriced underlying) - and None debounces, the conservative
    direction. Gains are left decisive: booking a win early on a wild print
    costs opportunity, not capital, and is not the failure this guards.
    """
    if direction != "below":
        return True
    spot = snap.underlying_prices.get(pos.underlying)
    entry, iv = pos.entry_spot, pos.entry_iv
    if spot is None or not entry or not iv:
        return None
    move = spot - entry
    em = optmath.expected_move(entry, iv, _days_since(pos.opened))
    if not em:
        return None
    needed = CORROBORATION_FRACTION * em

    # What counts as ADVERSE depends on what the position is betting on, and
    # `dominant_risk` already answers exactly that question from the entry
    # greeks. A VOL bet is hurt by a large move either way, so its test is on
    # magnitude. Anything carrying a directional stake - including a position
    # `dominant_risk` calls "balanced" - uses the SIGNED test, which is the
    # conservative reading: a move that helped the position can never confirm a
    # claim that the position collapsed, and refusing to confirm only means the
    # ordinary debounce applies.
    dom = optmath.dominant_risk(pos.greeks_at_entry)
    delta = (pos.greeks_at_entry or {}).get("delta_dollars", 0.0)
    if (dom and dom[0] == "volatility") or not delta:
        return abs(move) >= needed
    return (-move if delta > 0 else move) >= needed


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
    #: Second opinion on a decisive breach, for signals noisy enough that
    #: "far past the threshold" and "bad print" are the same observation.
    #: (pos, snap, direction) -> True to confirm, False to debounce, None when
    #: it cannot be judged (which debounces too). Absent on signals that print
    #: cleanly - the underlying and the calendar need no corroborating.
    corroborate: Callable[[Position, Snapshot, str], bool | None] | None = None


#: The registry. A new rule type usually needs no new signal at all.
EXIT_SIGNALS: dict[str, ExitSignal] = {
    # Noisiest signal available on an options position: a wide or stale quote
    # can print -100%-of-credit on a healthy spread. Debounce matters most here.
    "position_mark": ExitSignal(
        "position_mark", lambda p, s, d: position_pnl_fraction(p.symbols, s),
        1.0, lambda v: f"{v:+.1%}",
        corroborate=_mark_corroborated,
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
    # The structure itself is gone, not merely moving. Reconcile counts
    # consecutive passes where a leg was missing at the broker (early
    # assignment, a partial external close), and this reads that count.
    #
    # `immediate_overshoot=0.0` because the COUNT IS the debounce - reaching
    # the threshold already means several independent broker snapshots agreed,
    # which is a stronger confirmation than N-of-M over one noisy signal. And
    # no `corroborate`: the broker's own holdings are the corroboration.
    "leg_divergence": ExitSignal(
        "leg_divergence", lambda p, s, d: float(p.leg_divergence_count),
        0.0, lambda v: f"{v:.0f} consecutive",
    ),
}

#: Lower fires first when several rules trigger in one tick. Risk before
#: reward: a position simultaneously at its stop and its target (a crazy
#: quote, or a gap through both) must exit as a stop, not book a fictional
#: win. Previously this was list order, i.e. accidental.
_PRIORITY = {"deadline": 0, "leg_divergence": 0, "stop_loss": 1,
             "underlying_stop": 1, "time_stop": 2, "profit_target": 3}


def _pct_string_to_fraction(v: Any) -> float | None:
    """A "-65.0%" threshold string as a FRACTION. None when it does not parse.

    Named for what it converts, because the `_pct` suffix meant two things in
    this codebase and one of the collisions shipped a dead subsystem (D-092).

    This used to lean on `_f`, whose default is 0.0 - so a threshold of "abc",
    or an empty string, became a stop at EXACTLY BREAKEVEN. Any position
    slightly underwater would then debounce into a close on the second check.
    `_normalise`'s docstring already promised to return None "for anything
    unrecognised or incomplete, which holds rather than guesses"; this is what
    makes that true.
    """
    try:
        return float(str(v).strip().rstrip("%")) / 100.0
    except (TypeError, ValueError):
        return None


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
    if kind == "leg_divergence":
        return ("leg_divergence", "above", float(LEG_DIVERGENCE_CONFIRM), kind)
    if kind in ("stop_loss", "profit_target") and rule.get("threshold") is not None:
        thr = _pct_string_to_fraction(rule["threshold"])
        if thr is None:
            return None  # unparseable threshold: hold, never guess a level
        direction = "below" if kind == "stop_loss" else "above"
        return ("position_mark", direction, thr, kind)
    if kind == "time_stop":
        # An explicit 0 is a real rule ("close on expiry day") and the live
        # book carries one. A MISSING day count is not a rule at all, and
        # coercing it to 0 would arm a stop the agent never wrote - the
        # absence-as-zero class (D-038). It used to raise TypeError instead,
        # taking every other position's evaluation down with it.
        raw = rule.get("days_before_expiry")
        if raw is None:
            return None
        try:
            return ("days_to_expiry", "below", float(raw), kind)
        except (TypeError, ValueError):
            return None
    if kind == "underlying_stop":
        level = _f(str(rule.get("level")), 0.0)
        if level > 0:
            return ("underlying", str(rule.get("direction", "below")), level, kind)
    return None


def invalid_rules(pos: Position) -> int:
    """How many of this position's rules cannot be read at all.

    Reported on the `exit_run` heartbeat rather than silently skipped: a rule
    the agent wrote and the evaluator cannot parse is a commitment that will
    never be honoured, and the agent has no other way to find that out.
    """
    return sum(1 for rule in pos.exit_rules if _normalise(rule) is None)


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


def evaluate(pos: Position, snap: Snapshot, deadline: str,
             *, stats: dict[str, int] | None = None
             ) -> tuple[str | None, str, float | None]:
    """Return (close_reason, explanation, pnl_fraction). None means hold.

    pnl_fraction comes back alongside the reason so the caller can feed it straight
    to learn.on_resolution() without recomputing - the position's net mark is
    exactly the signal credit assignment needs (D-018 #9).

    `stats` is an optional counter bag the caller owns. It exists because the
    interesting event here does NOT produce a close and therefore leaves no exit
    row: a decisive mark breach that the underlying refused to corroborate is a
    position NOT closed, and without a count nothing downstream could ever see
    it happening (WU-4.6). The keys are `mark_breach_suppressed` and
    `mark_breach_confirmed`.
    """
    pnl = position_pnl_fraction(pos.symbols, snap)
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
    # Two rules belong to the SYSTEM, not to the agent: the deadline (INV-26)
    # and leg divergence. Neither is the agent's to override, and for the same
    # reason - the agent's exit rules all describe a position that, in these
    # two cases, either cannot resolve in time or no longer exists.
    # ASSIGNED SHARES LEAVE (D-109). Reconcile adopts a non-OCC broker row as
    # `orphan_equity` so it is watched - and every rule that could watch it is
    # dead: `deadline` and `time_stop` read `_days_to("")` -> None and hold,
    # and a single-symbol position that vanishes takes the phantom branch, so
    # `leg_divergence` can never count. Live shape: the book's short 758P is
    # assigned early on a drop through 758 -> 1,200 shares bought at 758 =
    # $909,600 of stock on a ~$100k account, held indefinitely by rules that
    # cannot fire. Shares are outside a defined-risk options mandate on any
    # reading; the only correct exit rule for them is "now". Submitted in
    # session and retried through `closing` like every other close.
    if pos.strategy == "orphan_equity":
        return ("orphan_equity", "assigned or stray shares are outside the defined-risk "
                                 "mandate - flattened, not held", None)
    implicit: list[dict[str, Any]] = [{"type": "deadline"}, {"type": "leg_divergence"}]
    # A gamma-wall time stop is the second, unless the agent wrote a USABLE one
    # of its own. Keyed on whether the rule PARSES rather than on whether one
    # is present: a time_stop the evaluator cannot read is a typo, not a
    # commitment, and letting it disarm the default would be the
    # absence-as-zero class (D-038) wearing a different hat.
    if not any((n := _normalise(r)) and n[3] == "time_stop" for r in pos.exit_rules):
        implicit.append({"type": "time_stop",
                         "days_before_expiry": IMPLICIT_TIME_STOP_DAYS})
    for rule in implicit + list(pos.exit_rules):
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
        confirmed: bool | None = None
        if decisive and signal.corroborate is not None:
            confirmed = signal.corroborate(pos, snap, direction)
            decisive = confirmed is True
            if stats is not None:
                key = "mark_breach_confirmed" if decisive else "mark_breach_suppressed"
                stats[key] = stats.get(key, 0) + 1
        if decisive or sum(history) >= NEEDED:
            note = ""
            if decisive and confirmed is True:
                note = ", underlying confirms"
            elif confirmed is not None and not decisive:
                note = " - the underlying has not confirmed it, so this is the"\
                       " debounce, not the print"
            why = (
                f"{sig_name} {signal.render(x)} {direction} {signal.render(thr)}"
                + (f" - decisive, immediate{note}" if decisive
                   else f" ({sum(history)}/{len(history)} checks){note}")
            )
            fired.append((_PRIORITY.get(kind, 5), kind, why))

    if not fired:
        return None, "", pnl
    fired.sort(key=lambda t: t[0])
    _, kind, why = fired[0]
    return kind, why, pnl


async def _close_legs(tools: dict[str, Any], symbols: list[str],
                      qty_by_symbol: dict[str, int] | None = None) -> bool:
    """Attempt to close every symbol. True iff every attempt succeeded.

    One helper, two callers - a fresh trigger and a retry - because the two
    used to be one inline loop and a plan to write a second copy of it. A
    single close path is the only way the retry cannot drift from the thing it
    is retrying.
    """
    ok = True
    for symbol in symbols:
        # BY QUANTITY when the symbol is shared (D-112). `close_position` on a
        # bare symbol closes the broker's whole AGGREGATE in it, so closing
        # position A also closed the leg position B held in the same contract -
        # legging B out into a bare short for two ticks until divergence
        # noticed. The tool accepts `qty`; it is passed exactly when another
        # open page holds the symbol, and never otherwise (INV-19: a whole
        # position closes whole).
        kw: dict[str, Any] = {"symbol_or_asset_id": symbol}
        if qty_by_symbol and symbol in qty_by_symbol:
            kw["qty"] = str(qty_by_symbol[symbol])
        try:
            r = await mcp_client.call(tools, "close_position", **kw)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[exit] failed closing leg {symbol}: {exc!r}")
            continue
        # READ THE ANSWER (D-109). Success used to be the absence of an
        # exception - and `mcp_client.unwrap` hands an Alpaca error envelope
        # back as ordinary data, never raising. A rejected close therefore
        # "succeeded", the position was transitioned to `closed` (terminal,
        # exactly once - INV-17), a fictional outcome was scored into
        # calibration and memory, and the real spread stayed live at the
        # broker with nothing watching it. The contract test that would have
        # caught this was skipped with a note saying exactly that. Same
        # error shapes discovery already reads off its option-chain call.
        why = mcp_client.in_band_error(r)
        if why:
            ok = False
            print(f"[exit] broker refused closing leg {symbol}: {why}")
    return ok


def _shared_leg_qtys(pos: Position, store: PositionStore) -> dict[str, int]:
    """{symbol: this position's own qty} for legs another open page also holds."""
    others = {s for p in store.open_positions() if p.position_id != pos.position_id
              for s in p.symbols}
    return {str(l.get("symbol")): abs(int(l.get("qty") or 0))
            for l in pos.legs if l.get("symbol") in others and int(l.get("qty") or 0)}


def _legs_to_close(pos: Position, snap: Snapshot) -> list[str]:
    """Which of this position's legs to send to `close_position`.

    Broker truth when we have it: a leg the broker no longer shows is already
    gone, and resubmitting it is noise that can only mask a real failure in the
    `submitted` flag beside it. This applies to a FIRST attempt exactly as much
    as to a retry - reconcile runs immediately before this every tick (INV-25),
    so a leg it just found missing must not then be blindly closed.

    When the read itself failed, absence proves nothing (I-55) and every leg is
    attempted: a close call against a leg that is already gone errors
    harmlessly, while a leg skipped on bad information is real exposure left
    unattended. The asymmetry decides it.
    """
    if not snap.broker_readable:
        return list(pos.symbols)
    held = snap.by_symbol()
    return [s for s in pos.symbols if s in held]


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
    blog_dir: Path | None = None,
    verbose: bool = True,
) -> list[str]:
    """Evaluate every still-open position and close those that trigger.

    Two candidate statuses, one close path. `open` positions are evaluated;
    `closing` positions are ones a previous tick already decided to close and
    could not finish - they are retried, never re-evaluated, because the
    decision to close is made once and finishing it is not a fresh judgment
    (I-57). Before this, `closing` was a dead end: `open_positions()` returned
    those positions and the loop skipped them forever, so a single failed
    `close_position` call left real exposure with no stop, no retry and nothing
    watching it at all.
    """
    triggered: list[str] = []
    watched = rules_checked = unreadable = errors = retried = 0
    #: Owned here, filled by `evaluate`. A suppressed breach closes nothing, so
    #: it would leave no trace at all without a count of its own.
    stats: dict[str, int] = {}

    for pos in store.open_positions():
        # Captured BEFORE any transition, which mutates status in place.
        is_retry = pos.status == "closing"

        if is_retry:
            # The reason was decided on the tick that first fired. Re-running
            # `evaluate` here could surface a DIFFERENT reason for a position
            # already mid-liquidation, and would re-debounce a decision that is
            # no longer in question.
            if not snap.market_open:
                continue
            reason = pos.close_reason or "retry"
            why = "retry: a previous close attempt did not complete"
            pnl = position_pnl_fraction(pos.symbols, snap)
        elif pos.status == "open":
            watched += 1
            rules_checked += len(watched_signals(pos)) + 1  # +1 for the implicit deadline
            unreadable += invalid_rules(pos)

            # One position's bad data must not blind the evaluator to every OTHER
            # position. `evaluate` reads model-authored YAML off disk, so a single
            # malformed rule used to take capital protection offline for the whole
            # book, every tick, until someone hand-fixed the file.
            try:
                reason, why, pnl = evaluate(pos, snap, deadline, stats=stats)
            except Exception as exc:  # noqa: BLE001 - per-position isolation
                errors += 1
                print(f"[exit] {pos.position_id}: rule evaluation failed, holding: {exc!r}")
                continue
            store.save(pos)  # persist debounce state either way

            if not reason:
                continue

            # DETECTION is unaffected by the clock; only the broker-mutating
            # close is gated. The calendar signals (deadline, days_to_expiry)
            # read a date and nothing else, so they fire on the 00:15 tick of
            # expiry day as readily as at noon - and a close submitted into a
            # shut session is the first domino of I-56: it fails, the position
            # parks in `closing`, and before I-57 above nothing looked at it
            # again. Debounce state is already persisted, so the same reason
            # re-fires the moment the market reopens; nothing is lost by
            # waiting, and the position is still watched while it waits.
            if not snap.market_open:
                continue

            # INV-17: first detector wins. If reconciliation already resolved this
            # position earlier in the tick, transition refuses and we do not act.
            if not store.transition(pos, "closing", close_reason=reason):
                continue
        else:
            continue  # proposed/opening/adjusting: nothing to act on

        remaining = _legs_to_close(pos, snap)
        if not remaining:
            # Every leg already gone at the broker. Reconcile's phantom branch
            # owns this resolution (it covers `closing`) and will take it next
            # tick with the same exactly-once guard; closing it from here would
            # race that for no gain.
            continue

        if is_retry:
            retried += 1
        if verbose:
            print(f"[exit] {pos.position_id}: {reason} - {why}")

        closed_ok = await _close_legs(tools, remaining,  # ALL surviving legs (INV-19)
                                      qty_by_symbol=_shared_leg_qtys(pos, store))

        journal.append(
            "exit",
            position_id=pos.position_id,
            close_reason=reason,
            explanation=why,
            legs=remaining,
            submitted=closed_ok,
            retry=is_retry,
        )
        if closed_ok:
            store.transition(pos, "closed")  # INV-17: terminal, exactly once
            await learn.guarded(  # F3 - advisory, never aborts the evaluator
                learn.on_resolution(pos, store, mem, wiki, journal, pnl_fraction=pnl,
                                    calibration=calibration),
                journal, stage="on_resolution", position_id=pos.position_id)
            if blog_dir is not None:
                blog.write_outcome(pos, close_reason=reason, why=why, pnl_fraction=pnl,
                                   blog_dir=blog_dir, journal=journal)
        triggered.append(pos.position_id)

    # Heartbeat, same reason as housekeeping's `interim_run` (D-074): the health
    # probe read the `exit` rows themselves as evidence the engine had RUN, so
    # "ran" and "produced" were the same number and it could only ever report
    # "never ran". Live proof it mattered: an open SPY spread with five rules
    # armed and a populated debounce history read as `exit_rules never ran`,
    # because nothing had breached - which is the engine working, not the
    # engine missing. An engine that evaluates and correctly holds must be
    # distinguishable from one that is not evaluating at all.
    if watched or retried:
        health.heartbeat(journal, "exit_run", positions=watched, rules=rules_checked,
                         triggered=len(triggered),
                       # A retry is work the engine did that no rule evaluation
                       # accounts for - without its own count, a tick that
                       # spent itself finishing a stuck close reads as idle.
                       retried=retried,
                       # An unreadable rule is a commitment that can never be
                       # honoured, and an evaluation error is a position going
                       # unwatched. Both are silent otherwise.
                       invalid_rules=unreadable, errors=errors,
                       # A mark breach the underlying refused to confirm closes
                       # nothing, so these two counts are the ONLY record that
                       # the corroboration rule is doing anything at all - and
                       # the data that will eventually tune its fraction.
                       mark_breach_suppressed=stats.get("mark_breach_suppressed", 0),
                       mark_breach_confirmed=stats.get("mark_breach_confirmed", 0))
        if unreadable or errors:
            print(f"[exit] WARNING: {unreadable} unreadable rule(s), "
                  f"{errors} position(s) failed evaluation - those are not being watched")
        if stats.get("mark_breach_suppressed"):
            print(f"[exit] {stats['mark_breach_suppressed']} mark breach(es) past the "
                  f"immediate threshold held for confirmation - the underlying has not "
                  f"moved enough to corroborate them; the debounce still applies")

    return triggered
