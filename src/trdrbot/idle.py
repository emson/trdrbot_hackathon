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
    equity: float,
    risk_cap_fraction: float,
    minutes_to_close_: float | None = None,
) -> IdleAction:
    """Pick the rung. Deterministic, no LLM, safe to run every tick."""
    if not market_open:
        return IdleAction("sleep", "market closed - housekeeping owns this window", {})

    silent_min = _minutes_since(last_decision_at)
    open_positions = [p for p in positions if getattr(p, "status", "") == "open"]

    # ---- L2: something moved under a position we hold ----
    moves = []
    for p in open_positions:
        px = underlying_prices.get(getattr(p, "underlying", ""))
        entry = getattr(p, "entry_spot", None)
        if px and entry:
            moves.append((p.underlying, px / entry - 1.0))
    big = [(u, m) for u, m in moves if abs(m) >= MATERIAL_MOVE]
    if big:
        return IdleAction(
            "review",
            "material move under a held position: "
            + ", ".join(f"{u} {m:+.2%}" for u, m in big),
            {"moves": dict(moves)},
        )

    # ---- L2: gone quiet while holding risk ----
    if open_positions and (silent_min is None or silent_min >= MAX_SILENCE_MIN):
        return IdleAction(
            "review",
            f"holding risk and no decide cycle for {silent_min:.0f}min"
            if silent_min is not None else "holding risk and no decide cycle yet",
            {"moves": dict(moves)},
        )

    # ---- L3: capital idle and deployable ----
    # Deliberately gated on being ABLE to act. Hunting while the book is at its
    # risk cap generates candidates that sizing will refuse - spend with no
    # possible outcome. Do not hunt when you cannot shoot.
    room = risk_cap_fraction * equity - open_risk_usd
    hunt_cooled = (_minutes_since(last_hunt_at) or 1e9) >= HUNT_COOLDOWN_MIN
    late = (minutes_to_close_ is not None
            and minutes_to_close_ <= NO_NEW_POSITIONS_BEFORE_CLOSE_MIN)
    if room > 0 and hunt_cooled and not late:
        return IdleAction(
            "hunt",
            f"${room:,.0f} of risk budget unused"
            + (" and no open positions" if not open_positions else ""),
            {"room_usd": room},
        )

    # ---- L0 ----
    why = "nothing at risk and nothing to deploy"
    if open_positions:
        why = "positions healthy, tape quiet, looked recently"
    elif late:
        why = f"{minutes_to_close_:.0f}min to the close - too late to open new risk"
    elif not hunt_cooled:
        why = "hunted recently; news does not turn over that fast"
    elif room <= 0:
        why = "risk budget fully deployed - the book is the bet"
    return IdleAction("sleep", why, {})
