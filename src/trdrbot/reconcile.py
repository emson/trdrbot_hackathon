"""C13 - reconcile broker truth against our records. Deterministic, no LLM.

Runs BEFORE the exit-rule evaluator every tick (INV-25). That ordering is the
fix from D-019: with C24 first, it could evaluate rules against a position the
broker had already resolved by assignment or expiry, acting on stale local
state. Reconciling first flips such positions to terminal, so C24's candidate
set excludes them by construction rather than by an extra check.
"""

from __future__ import annotations

from typing import Any

from . import health, ids, learn, optmath
from .analytics import Snapshot, _f, filled_legs
from .calibration import CalibrationStore
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import Position, PositionStore
from .wiki import Wiki


#: How far a refilled max loss must move before it is worth a journal row.
#: A starting point, not a measurement - the same honest footing as
#: exit_rules' CORROBORATION_FRACTION. The absolute floor keeps a near-zero
#: prior from making every rounding difference a finding; the relative one
#: keeps a large position from flagging on cents. Tune from the
#: `max_loss_recomputed` rows themselves once there are enough to look at.
REPRICE_REPORT_USD, REPRICE_REPORT_SHARE = 50.0, 0.05


def _reprice_max_loss(pos: Position, snap: Snapshot, journal: Journal) -> None:
    """Recompute `max_loss_usd` from the fill, at the moment it is confirmed.

    Until now this number was whatever the MODEL said - `size_position` derived
    it from a per-contract max loss the model itself supplied, and
    `record_position` stored it. Nothing ever checked it against what the
    broker actually filled. It is not a display figure: `tick` sums it across
    open positions to enforce the portfolio and per-underlying caps, so a
    position whose real risk exceeds its stated risk silently buys headroom
    for the NEXT position too.

    Once per position, here, because this is the one moment the fill is both
    complete and freshly observed. A failure to price it leaves the stated
    figure alone rather than overwriting it with a worse guess.
    """
    legs = filled_legs(pos.symbols, snap)
    if legs is None:
        return
    try:
        _, recomputed = optmath.max_profit_loss(legs)
    except optmath.MultiExpiryError:
        return  # a calendar: refused here for the same reason it is everywhere
    if recomputed is None:
        return  # unbounded - `None` is the honest answer and must not become a number
    recomputed = round(abs(recomputed), 2)
    prior = pos.max_loss_usd
    if prior is None or abs(recomputed - prior) > max(
            REPRICE_REPORT_USD, REPRICE_REPORT_SHARE * abs(prior)):
        journal.append("reconciliation", position_id=pos.position_id,
                       finding="max_loss_recomputed", prior=prior, recomputed=recomputed,
                       detail="risk repriced from the fill; the book caps sum this field")
    pos.max_loss_usd = recomputed


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

        # EVERY conclusion in this loop reasons from what is MISSING at the
        # broker, and missing means nothing when the read itself failed. A dead
        # MCP session returns an empty holdings list indistinguishable from an
        # empty account - and acting on it marked live positions `closed`
        # (or `abandoned`, one branch up), scored them, and left the real
        # exposure unwatched, because a terminal position is no longer
        # evaluated by the exit engine (I-55). Nothing here is safe without a
        # readable broker, and nothing here is LOST by waiting a tick: the
        # presence-based branches cannot fire on an empty list anyway.
        if not snap.broker_readable:
            continue

        present = [s for s in syms if s in held]
        pending = [s for s in syms if s in working]

        if pos.status == "opening":
            # Submitted but unconfirmed. Three outcomes, and telling them apart
            # is the whole point of the `opening` state.
            if present:
                pos.status = "open"
                if len(present) == len(syms):
                    _reprice_max_loss(pos, snap, journal)
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
            # COUNT, do not close. The remainder of a broken spread can be an
            # undefined-risk naked leg - exactly what INV-19 refuses to create
            # via our own close path, arriving through the broker instead - so
            # it cannot be left priced on the legs it still has. But one stale
            # snapshot must not liquidate a healthy position either, and
            # reconcile has no tools and should not grow them.
            #
            # So the count is the signal and the exit registry is the actuator
            # (WU-6.3). `exit_rules.run` is the very next thing this tick does,
            # so confirmation costs one tick of exposure.
            pos.leg_divergence_count += 1
            store.save(pos)
            journal.append(
                "reconciliation",
                position_id=pos.position_id,
                finding="leg_divergence",
                intended=syms,
                actual=present,
                consecutive=pos.leg_divergence_count,
            )
            result["drift"].append(pos.position_id)
        elif present and len(present) == len(syms) and pos.leg_divergence_count:
            # It came back. A transient - a slow broker page, a snapshot taken
            # mid-fill - leaves a trace rather than silently un-counting, so
            # the tuning question ("is the confirm threshold right?") can be
            # answered from the journal instead of from taste.
            pos.leg_divergence_count = 0
            store.save(pos)
            journal.append(
                "reconciliation",
                position_id=pos.position_id,
                finding="leg_divergence_cleared",
                intended=syms,
            )

    # Heartbeat, same reason as `exit_run` and `attribution_run` (D-074):
    # learning was the only subsystem in this cluster with no record of its own
    # activity, so "ran and had nothing to learn from" and "stopped running"
    # were the same observation. `errors` is what makes a degraded elfmem
    # visible - the failures are advisory now, which is exactly why they need
    # somewhere to be counted.
    # UNCONDITIONAL, and that is the whole point. Guarded by "only if something
    # was learned", the row is written exactly when the probe least needs it -
    # so a quiet week and a dead learning path produce the same silence, which
    # is the collapse the paragraph above says this heartbeat exists to
    # prevent. `work` reports fills+resolutions, so a run with nothing to learn
    # from reads "ran Nx, nothing was due - idle, not stalled" rather than
    # "never ran".
    health.heartbeat(journal, "learn_run",
                     fills=len(result["filled"]),
                     resolutions=len(result["phantom"]),
                     errors=learn_errors)

    if snap.broker_readable:
        _adopt_orphans(store, snap, journal, claimed, result)

    return result


def _adopt_orphans(store: PositionStore, snap: Snapshot, journal: Journal,
                   claimed: set[str], result: dict[str, list[str]]) -> None:
    """Give anything held at the broker with no page of ours a page, and rules.

    Recording an orphan was never the hard part - the branch this replaces
    already journalled one every tick. The gap was that a journal row is not a
    stop: an orphan had no exit rules, so nothing evaluated it, and the deadline
    sweep (INV-26) that force-closes every position before the competition ends
    could not see it either. It sat there, unexplained AND unmanaged, until a
    human read the journal.

    A stub fixes both at once by being an ordinary position: `status="open"`
    puts it in `exit_rules.run`'s candidate set, where the implicit deadline,
    time-stop and leg-divergence rules apply to it exactly as to anything else.
    This is the FM-9 stub the architecture already specifies, finally built.

    Legs sharing an underlying AND an expiry are adopted as ONE position, not
    one each. That is what they almost certainly are - the surviving legs of a
    spread whose page we lost - and it is what INV-19 requires: closing them
    together is the difference between exiting a spread and legging out of one
    into a naked short. A plain ticker (assigned stock, no OCC fields) has no
    expiry to group on and is adopted alone, which is correct: assigned stock is
    a whole position, not a fragment of one.

    `max_loss_usd` and the thesis are left EMPTY rather than guessed. Both are
    already BAD findings in `health.check` for any open position, so an adopted
    orphan reports itself as needing a human - which is exactly true, and better
    than a confident number nobody derived (D-038's absence-as-zero, inverted:
    do not invent presence either).
    """
    held = snap.by_symbol()
    groups: dict[tuple[str, str], list[str]] = {}
    for symbol in sorted(held):
        if symbol in claimed:
            continue
        occ = optmath.parse_occ(symbol)
        key = (occ["underlying"], occ["expiry"]) if occ else (symbol.upper(), "")
        groups.setdefault(key, []).append(symbol)

    for (underlying, expiry), symbols in groups.items():
        legs = []
        for symbol in symbols:
            row = held[symbol]
            qty = abs(int(_f(row.get("qty"), 0.0))) or 1
            # Side from the broker's own word where it gives one, else from the
            # sign of the quantity it reports. Both are stated here rather than
            # assumed, because a leg adopted with the wrong side would be closed
            # in the wrong direction - doubling the position instead of exiting.
            side = str(row.get("side") or "").lower()
            if side not in ("long", "short"):
                side = "short" if _f(row.get("qty"), 0.0) < 0 else "long"
            legs.append({"symbol": symbol, "side": side, "qty": qty})

        pos = Position(
            position_id=ids.position_id(underlying, "orphan"),
            status="open",
            strategy="orphan_option" if expiry else "orphan_equity",
            underlying=underlying,
            opened=ids.utc_now().isoformat(),
            expiry=expiry,
            legs=legs,
            thesis=(
                "Adopted orphan. Held at the broker with no position page of ours - "
                "an unrecorded fill, a crash between placing and recording, or an "
                "assignment. There is no thesis because there is no record of why "
                "this was opened; it is adopted so that it is WATCHED, not because "
                "it is understood."
            ),
            provenance="unknown",
        )
        store.save(pos)
        journal.append(
            "reconciliation",
            finding="orphan_adopted",
            position_id=pos.position_id,
            symbols=symbols,
            detail="held at broker with no page - adopted so the exit rules and the "
                   "deadline sweep can see it",
        )
        result["orphan"].extend(symbols)


def summarise(result: dict[str, list[str]]) -> str:
    parts = [f"{k}={len(v)}" for k, v in result.items() if v]
    return ", ".join(parts) if parts else "clean"
