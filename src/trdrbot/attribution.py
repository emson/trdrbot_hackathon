"""Attribute a closed position's outcome to its VIEW or its STRUCTURE.

Runs at housekeeping, not at close, and that timing is the point. A stop
triggering on day 2 of a 10-day thesis says nothing about whether the thesis
was right - the horizon has not arrived. Scoring it at close would record
"thesis wrong" for a view that had not yet been tested, which is precisely
the mis-attribution this module exists to prevent.

So: close records the P&L; attribution waits for the horizon; elfmem is fed a
signal derived from the ATTRIBUTION rather than from the money.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import analytics, experiments, health, ids
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import Position, PositionStore
from .wiki import Wiki


def _horizon_passed(pos: Position) -> bool:
    # `market_today`, not the UTC date (D-107): evening housekeeping is the
    # next UTC day, so a Wednesday horizon "passed" on Tuesday night and the
    # position was attributed against Tuesday's close. Same clock as
    # `ledger.Entry.matured`, so the two halves of resolution agree.
    try:
        return ids.market_today() >= date.fromisoformat(pos.thesis_horizon)
    except (ValueError, TypeError):
        return False


def unscoreable_reason(pos: Position) -> str:
    """Why this position can never be attributed, or "" if it can.

    The two ways a thesis becomes permanently unjudgeable, both of which are
    decided at ENTRY and neither of which any later event can repair. Kept
    beside `pending` because it is the other half of the same predicate.
    """
    if not pos.thesis_claim:
        return "no thesis was recorded at entry"
    try:
        date.fromisoformat(str(pos.thesis_horizon))
    except (ValueError, TypeError):
        return f"the thesis horizon {str(pos.thesis_horizon)!r} is not a date"
    return ""


def pending(store: PositionStore) -> list[Position]:
    """Closed positions still owed an attribution: due, or impossible.

    "Impossible" belongs in the queue, and leaving it out is what made this
    subsystem's null path indistinguishable from its empty one (D-114). The
    old predicate required a thesis claim and a parseable horizon, so a
    position missing either was never pending, never attributed, and never
    counted - a permanently stuck item and a permanently empty queue are the
    same observation from here, and health could only say so once, forever,
    about a state nothing would ever change.

    A closed position is now in exactly one of three states rather than four:
    scoreable and due (attribute it), scoreable and not yet due (wait), or
    unscoreable (record WHY, once, and stop). There is no fourth.
    """
    return [
        p
        for p in store.all()
        if not p.attribution
        and p.status not in ("proposed", "opening", "open", "adjusting", "closing")
        and (unscoreable_reason(p) or _horizon_passed(p))
    ]


#: Our Alpaca subscription does not permit recent SIP (consolidated) data - the
#: default feed 403s with "subscription does not permit querying recent SIP
#: data". IEX is what the free tier serves. Found live: without this, every
#: spot lookup failed, `_spot` always returned None, and attribution silently
#: never ran - the self-improving loop's most important step dead while every
#: log line still read healthy.
#:
#: Re-exported from `analytics`, which is now the one place that talks to the
#: price feed. This module's own copy of the constant, its own price-shape
#: reader and its own snapshot-then-trade fallback were a second implementation
#: of one question, and the two had already drifted: only this one knew about
#: `dailyBar`, only the other knew the `{"trades": {...}}` envelope (D-113).
FEED = analytics.FEED


async def _spot(tools: dict[str, Any], underlying: str) -> float | None:
    """Last price for the underlying. None if genuinely unavailable - never guessed."""
    q = await analytics.spot_quote(tools, underlying, feed=FEED)
    return q.price if q else None


async def run(
    store: PositionStore,
    tools: dict[str, Any],
    mem: ElfmemAdapter,
    wiki: Wiki,
    journal: Journal,
    *,
    verbose: bool = True,
) -> dict[str, int]:
    """Attribute every position whose thesis horizon has now passed."""
    done = 0
    waiting = list(pending(store))
    no_price = 0
    unjudgeable = 0
    for pos in waiting:
        # A thesis that can never be judged still gets an ANSWER, once. The
        # verdict already exists and already means exactly this - UNSCOREABLE
        # carries signal None, "we could not judge it, assert nothing", and
        # `attributable_rate` already excludes it from what the loop learned
        # (D-114). Writing it does three things silence did not: the queue
        # drains, the rate stops flattering itself by ignoring its own
        # failures, and the position page says what happened instead of
        # looking like one still waiting for its horizon.
        why = unscoreable_reason(pos)
        if why:
            pos.attribution = experiments.UNSCOREABLE
            store.save(pos)
            journal.append("attribution", position_id=pos.position_id,
                           verdict=experiments.UNSCOREABLE, signal=None,
                           unscoreable=why, blocks_credited=0, blocks_applied=0,
                           thesis=pos.thesis_claim, horizon=pos.thesis_horizon)
            wiki.append_log(f"attributed {pos.position_id}: unscoreable ({why})")
            if verbose:
                print(f"[attribution] {pos.position_id}: unscoreable - {why}")
            unjudgeable += 1
            done += 1
            continue

        spot = await _spot(tools, pos.underlying)
        if spot is None:
            # Never guess the price - but never fail silently either. This
            # `continue` is exactly how attribution ran dead for days while
            # every log line read healthy: no journal entry meant "never ran"
            # and "ran, found nothing" were indistinguishable (D-038).
            no_price += 1
            continue

        held = experiments.Thesis(
            claim=pos.thesis_claim, underlying=pos.underlying, horizon=pos.thesis_horizon,
            drift=pos.thesis_drift, band_low=pos.thesis_band_low, band_high=pos.thesis_band_high,
        ).holds_at(spot)

        # Profit is measured, not inferred from a label. `close_reason` was
        # standing in for it, so anything closed outside our own exit rules -
        # `external` - scored as a LOSS however much money it made. Caught
        # live: an NVDA spread the agent closed itself by repricing its profit
        # target made +$1,290 and would have been attributed as a losing
        # thesis, teaching the loop the exact opposite of what happened
        # (D-056).
        if pos.last_pnl_pct is not None:
            profited = pos.last_pnl_pct > 0
        else:
            profited = (pos.close_reason or "") in ("target_hit", "thesis_resolved")
        verdict, lesson = experiments.attribute(held, profited)
        signal = experiments.ATTRIBUTION_SIGNAL[verdict]

        pos.attribution = verdict
        store.save(pos)

        # The signal follows the attribution, NOT the P&L - so a lucky win on a
        # wrong view teaches nothing and a right view that lost keeps its credit.
        # `signal is None` means exactly that: apply NOTHING, rather than the
        # 0.5 that used to drag every block toward the midpoint (D-072).
        requested = applied = 0
        if signal is not None:
            # Weight by how well each block matched the query that produced
            # this decision (D-073). Grouped by rounded weight so a 3-block
            # position costs one or two calls, not three - and so the grouping
            # is deterministic, which matters for a path we want to be able to
            # replay from the journal.
            groups: dict[float, list[str]] = {}
            for bid, w in pos.credit_weights().items():
                groups.setdefault(round(w, 2), []).append(bid)
            for weight, bids in sorted(groups.items()):
                req, app = await mem.credit_blocks(
                    bids, signal, weight=weight,
                    source=f"attribution:{pos.position_id}",
                )
                requested += req
                applied += app
            if requested and applied < requested:
                # Credit that reaches zero blocks is indistinguishable from
                # credit that was never attempted, unless it says so. The SPY
                # position's only creditable block is archived, and elfmem
                # skips non-active blocks - so this path really does fire.
                journal.append("attribution_credit_short",
                               position_id=pos.position_id,
                               requested=requested, applied=applied)
                if verbose:
                    print(f"[attribution] {pos.position_id}: credit applied to "
                          f"{applied}/{requested} blocks")

        journal.append(
            "attribution",
            blocks_credited=requested,
            blocks_applied=applied,
            position_id=pos.position_id,
            thesis=pos.thesis_claim,
            horizon=pos.thesis_horizon,
            price_at_horizon=spot,
            thesis_held=held,
            profited=profited,
            verdict=verdict,
            signal=signal,
        )
        wiki.append_log(f"attributed {pos.position_id}: {verdict} (price {spot:.2f})")
        if verbose:
            print(f"[attribution] {pos.position_id}: {verdict}")
            print(f"              {lesson}")
        done += 1

    # Heartbeat: always record that the subsystem ran and what it concluded,
    # including when it concluded nothing. The null path is the one that goes
    # wrong quietly, so it is the one that must leave evidence.
    health.heartbeat(
        journal, "attribution_run",
        pending=len(waiting),
        attributed=done,
        skipped_no_price=no_price,
        # Counted apart from `attributed`, because they are the opposite of
        # what this subsystem is for: the loop closed a position and learned
        # nothing from it. A rising share here is the entry path failing to
        # record theses, which is where the fix belongs.
        unscoreable=unjudgeable,
    )
    return {"attributed": done, "pending": len(waiting),
            "skipped_no_price": no_price, "unscoreable": unjudgeable}
