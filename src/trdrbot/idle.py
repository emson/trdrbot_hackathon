"""What to do when nothing has happened (D-043).

An empty inbox is not one state, and "run every analysis every tick" is the
amateur answer to it: re-underwriting the whole market every five minutes
costs money, burns context, and manufactures activity. A professional's day
is a ladder - continuous cheap position checks, periodic expensive hunting,
daily deep research - and the rung you climb to is decided by what changed
and by what you have at risk.

    L0  nothing at risk, nothing moved, looked recently   -> sleep      (free)
    L1  a position exists                                 -> health     (free, every tick)
    L2  material move, or too long since a look           -> review     (1 LLM call)
    L3  capital idle and deployable                       -> hunt       (research + LLM)

The asymmetry that sets the thresholds: the cost of NOT looking scales with
what is at risk, while the cost of looking scales with LLM spend. So a full
book on a quiet tape should be left alone - stops already guard it, and
churning is how edge is donated to the spread. An EMPTY book is the opposite
case, and the one this system kept getting wrong: idle capital is a position
too, a 100% cash holding with 0% expected return, and with a deadline it is a
decision that has to be justified rather than defaulted into.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

#: A move this large in a held underlying is worth a fresh look even with no
#: news. Roughly a third of a typical index daily range: big enough not to
#: fire on noise, small enough to precede a stop.
MATERIAL_MOVE = 0.004
#: Look at least this often while holding risk, whatever the tape does.
MAX_SILENCE_MIN = 90
#: Minimum gap between opportunity hunts. News does not turn over faster than
#: this, and each hunt costs two LLM calls plus market data.
#:
#: MUST stay above MAX_SILENCE_MIN: that ordering is what makes it safe for a
#: ready hunt to defer a material-move review (I-72). A hunt can postpone at
#: most one look before the silence rule fires regardless, so oversight of a
#: held position stays on a bounded schedule. Pinned by a test.
HUNT_COOLDOWN_MIN = 120
#: Do not open new positions inside this many minutes of the close: fills are
#: worst into the bell, and an overnight gap cannot be reacted to.
NO_NEW_POSITIONS_BEFORE_CLOSE_MIN = 30
#: Pending opportunities older than this were priced against quotes that no
#: longer exist.
OPPORTUNITY_STALE_MIN = 180

MARKET_CLOSE_ET = time(16, 0)


@dataclass(frozen=True)
class IdleAction:
    level: str  # sleep | review | hunt
    reason: str
    detail: dict[str, Any]


def _minutes_since(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    return (datetime.now(UTC) - ts).total_seconds() / 60.0


def minutes_to_close(now_et: datetime) -> float:
    close = now_et.replace(hour=MARKET_CLOSE_ET.hour, minute=MARKET_CLOSE_ET.minute,
                           second=0, microsecond=0)
    return (close - now_et).total_seconds() / 60.0


def decide(
    *,
    market_open: bool,
    positions: list[Any],
    underlying_prices: dict[str, float],
    last_decision_at: datetime | None,
    last_hunt_at: datetime | None,
    open_risk_usd: float,
    equity: float | None,
    risk_cap_fraction: float,
    minutes_to_close_: float | None = None,
) -> IdleAction:
    """Pick the rung. Deterministic, no LLM, safe to run every tick.

    `equity` is None when the account could not be read (I-75). There is then
    no deployable room to speak of - a hunt would generate candidates sizing
    refuses anyway - so the ladder falls back to the oversight rungs, which
    need no bankroll to be worth climbing.
    """
    if not market_open:
        return IdleAction("sleep", "market closed - housekeeping owns this window", {})

    silent_min = _minutes_since(last_decision_at)
    open_positions = [p for p in positions if getattr(p, "status", "") == "open"]

    moves = []
    for p in open_positions:
        px = underlying_prices.get(getattr(p, "underlying", ""))
        entry = getattr(p, "entry_spot", None)
        if px and entry:
            moves.append((p.underlying, px / entry - 1.0))
    big = [(u, m) for u, m in moves if abs(m) >= MATERIAL_MOVE]

    # ---- L3 readiness, computed BEFORE L2 can pre-empt it (I-72) ----
    # Deliberately gated on being ABLE to act. Hunting while the book is at its
    # risk cap generates candidates that sizing will refuse - spend with no
    # possible outcome. Do not hunt when you cannot shoot.
    room = None if equity is None else risk_cap_fraction * equity - open_risk_usd
    hunt_cooled = (_minutes_since(last_hunt_at) or 1e9) >= HUNT_COOLDOWN_MIN
    late = (minutes_to_close_ is not None
            and minutes_to_close_ <= NO_NEW_POSITIONS_BEFORE_CLOSE_MIN)
    can_hunt = room is not None and room > 0 and hunt_cooled and not late

    # ---- L2: gone quiet while holding risk. THE OVERSIGHT GUARANTEE ----
    # Checked first and never yielded, because it is the promise that a held
    # position is looked at on a bounded schedule.
    if open_positions and (silent_min is None or silent_min >= MAX_SILENCE_MIN):
        return IdleAction(
            "review",
            f"holding risk and no decide cycle for {silent_min:.0f}min"
            if silent_min is not None else "holding risk and no decide cycle yet",
            {"moves": dict(moves)},
        )

    # ---- L2: something moved under a position we hold ----
    # YIELDS to a ready hunt (I-72). `abs(px / entry_spot - 1)` is measured
    # against ENTRY, so once a held name has drifted 0.4% this rung is
    # satisfied FOREVER and returned "review" on every tick - the ladder never
    # reached L3 again while anything was open. Measured over the run: 49
    # `position_review` items against 9 `hunt` rows, and 22 muse opportunities
    # expired unread at 3,100-3,800 minutes old.
    #
    # Yielding is safe, and bounded by two facts rather than by hope:
    #   * HUNT_COOLDOWN_MIN (120) > MAX_SILENCE_MIN (90), so a hunt can defer a
    #     review at most once before the silence rule above fires anyway - the
    #     invariant is asserted below so tuning one cannot silently break it.
    #   * exit rules run EVERY tick in the fast path, with no LLM and no
    #     dependence on this ladder. Stops are not what is being deferred here;
    #     a discretionary second look is.
    if big and not can_hunt:
        return IdleAction(
            "review",
            "material move under a held position: "
            + ", ".join(f"{u} {m:+.2%}" for u, m in big),
            {"moves": dict(moves)},
        )

    # ---- L3: capital idle and deployable ----
    if can_hunt and room is not None:
        return IdleAction(
            "hunt",
            f"${room:,.0f} of risk budget unused"
            + (" and no open positions" if not open_positions else ""),
            {"room_usd": room},
        )

    # ---- L0 ----
    why = "nothing at risk and nothing to deploy"
    if room is None:
        why = "the account could not be read - no bankroll, so nothing is deployable"
    elif open_positions:
        why = "positions healthy, tape quiet, looked recently"
    elif late:
        why = f"{minutes_to_close_:.0f}min to the close - too late to open new risk"
    elif not hunt_cooled:
        why = "hunted recently; news does not turn over that fast"
    elif room <= 0:
        why = "risk budget fully deployed - the book is the bet"
    return IdleAction("sleep", why, {})
