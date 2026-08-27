"""Phased risk budget across the competition window (D-047).

Kelly maximises long-run log growth over an unbounded horizon. A competition
is a *finite* horizon with a terminal score, and applying an unearned-record
penalty to it produced a deadlock we measured rather than guessed:

    resolved trades   n=0  n=3  n=5  n=7  n=8  n=12
    contracts sized     0    0    0    0    0     1

With no track record the probability shrinkage pulls a stated 70% back toward
the base rate, Kelly returns ~0, and **the system can never place the trade
that would build the record it needs to be allowed to trade.** Eight days of
0% is not risk discipline, it is a formula returning zero and nobody noticing.

The resolution: **size and learning rate are independent here.** Learning comes
from the NUMBER of resolved theses, not their size, and survival is already
guaranteed structurally by defined-risk legs plus a portfolio cap - not by
sizing small. So a small size buys no extra safety and no extra learning; it
only shrinks the result. A desk does not hand a new trader zero, it hands them
a bounded exploration allocation and expects to pay for the information.

Three phases, and two independent gates that must BOTH permit - the tightest
binds, exactly as the three risk caps already compose:

    phase (calendar)          how much time a thesis has left to work
    evidence (calibration)    whether size has been earned yet

    VALIDATE  > 5 days left, or n < MIN_SAMPLE
              fixed exploration allocation, Kelly is NOT trusted yet
    DEPLOY    2-5 days left AND n >= MIN_SAMPLE
              Kelly with a continuous ramp; the widest risk budget
    HARVEST   < 2 days left
              no NEW risk - a position opened now cannot resolve, and an
              unresolved position at the deadline is closed at whatever the
              book offers
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

VALIDATE, DEPLOY, HARVEST = "validate", "deploy", "harvest"

#: Exploration allocation per position while the record is unproven. Sized to
#: what the first live trade actually risked (2.2% of equity) - deliberate,
#: bounded, and paid for information rather than derived from an edge estimate
#: we have no grounds to trust yet.
SEED_FRACTION = 0.022
SEED_MAX_POSITIONS = 3

#: Portfolio at-risk ceiling by phase, as a fraction of equity. HARVEST is 0
#: for NEW risk; existing positions run to their own exits.
PHASE_PORTFOLIO_CAP = {VALIDATE: 0.10, DEPLOY: 0.20, HARVEST: 0.0}

#: Days remaining that separate the phases.
DEPLOY_FROM_DAYS = 5
HARVEST_BELOW_DAYS = 2

#: Evidence needed before Kelly is trusted at all.
MIN_SAMPLE_FOR_KELLY = 8
#: Continuous ramp constant: multiplier reaches halfway to ESTABLISHED at n=k.
#: Replaces a hard n>=8 cliff, which made the difference between the 7th and
#: 8th resolved trade larger than every trade before it.
RAMP_K = 6.0

#: Equity drawdown from the high-water mark at which risk is throttled, and
#: how hard. A desk cuts size into a losing streak; the streak is evidence the
#: current regime is not the one the record was earned in.
DRAWDOWN_TRIGGER = 0.03
DRAWDOWN_FLOOR = 0.25


@dataclass(frozen=True)
class RiskPosture:
    phase: str
    days_left: int
    portfolio_cap: float       # fraction of equity, after all modifiers
    kelly_multiplier: float    # 0 when Kelly is not trusted yet
    seed_fraction: float       # fixed per-position allocation, 0 once Kelly is on
    drawdown_throttle: float
    reason: str

    @property
    def uses_kelly(self) -> bool:
        return self.kelly_multiplier > 0


def _days_left(deadline: str, today: date | None = None) -> int:
    return (date.fromisoformat(deadline) - (today or date.today())).days


def kelly_ramp(n: int, unproven: float, established: float) -> float:
    """Continuous evidence ramp, replacing the n>=8 cliff.

    Same shrinkage shape already used for probabilities: weight = n/(n+k). At
    n=0 it returns `unproven`, at n=RAMP_K it sits halfway, and it approaches
    `established` asymptotically. No single trade is ever a step change.
    """
    if n <= 0:
        return unproven
    w = n / (n + RAMP_K)
    return unproven + (established - unproven) * w


def drawdown_throttle(equity: float, high_water: float) -> float:
    """1.0 when at highs; scales toward DRAWDOWN_FLOOR as drawdown deepens."""
    if high_water <= 0 or equity >= high_water:
        return 1.0
    dd = 1.0 - equity / high_water
    if dd <= DRAWDOWN_TRIGGER:
        return 1.0
    # Linear from full size at the trigger to the floor at 3x the trigger.
    span = DRAWDOWN_TRIGGER * 2.0
    frac = min(1.0, (dd - DRAWDOWN_TRIGGER) / span)
    return max(DRAWDOWN_FLOOR, 1.0 - frac * (1.0 - DRAWDOWN_FLOOR))


def posture(
    *,
    deadline: str,
    calibration_n: int,
    equity: float,
    high_water: float,
    unproven_kelly: float,
    established_kelly: float,
    today: date | None = None,
) -> RiskPosture:
    """The risk budget for right now. Deterministic; no LLM, no market data."""
    days = _days_left(deadline, today)
    throttle = drawdown_throttle(equity, high_water)

    if days < HARVEST_BELOW_DAYS:
        return RiskPosture(
            HARVEST, days, 0.0, 0.0, 0.0, throttle,
            f"{days}d left - no new risk can resolve before the deadline; "
            "existing positions run to their own exits",
        )

    earned = calibration_n >= MIN_SAMPLE_FOR_KELLY
    # BOTH gates must permit. The calendar can say DEPLOY while the record says
    # otherwise; the tighter one binds, exactly as the three risk caps compose.
    if days <= DEPLOY_FROM_DAYS and earned:
        cap = PHASE_PORTFOLIO_CAP[DEPLOY] * throttle
        return RiskPosture(
            DEPLOY, days, cap,
            kelly_ramp(calibration_n, unproven_kelly, established_kelly), 0.0, throttle,
            f"{days}d left and {calibration_n} resolved theses - Kelly earned, "
            f"widest budget{'' if throttle == 1.0 else f', throttled {throttle:.0%} on drawdown'}",
        )

    cap = PHASE_PORTFOLIO_CAP[VALIDATE] * throttle
    why = (f"{calibration_n} resolved theses (<{MIN_SAMPLE_FOR_KELLY}) - Kelly not trusted; "
           f"fixed {SEED_FRACTION:.1%} exploration allocation, paid for the record"
           if not earned else f"{days}d left - too early for the widest budget")
    return RiskPosture(VALIDATE, days, cap, 0.0, SEED_FRACTION, throttle, why)


# ------------------------------------------------------------ high-water mark

def high_water_path(state_dir: Path) -> Path:
    return state_dir / "high_water.json"


def update_high_water(state_dir: Path, equity: float) -> float:
    """Track the peak equity the drawdown throttle measures against."""
    p = high_water_path(state_dir)
    hw = 0.0
    if p.exists():
        try:
            hw = float(json.loads(p.read_text()).get("high_water", 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            hw = 0.0
    if equity > hw:
        hw = equity
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"high_water": hw}))
    return hw
