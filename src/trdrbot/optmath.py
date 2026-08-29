"""Options payoff and probability maths. Deterministic, no LLM (D-016).

Two layers, deliberately separated by how much you should trust them:

  EXACT      payoff at expiry, entry cost, max profit/loss, breakevens.
             Arithmetic on the option contract itself - no model, no
             assumptions, no way for it to be "wrong" beyond a coding error.

  MODELLED   probability of profit, expected value. These need a distribution
             for the terminal price, and we use lognormal parameterised by
             implied vol. That is the standard assumption and it is still an
             ASSUMPTION - real returns have fatter tails, and IV is itself a
             forecast. Treated as advisory throughout, never as truth.

Keeping the two apart matters: an agent that conflates "max loss is $300"
(a fact) with "probability of profit is 68%" (a model output) will place far
too much weight on the second.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

CONTRACT_MULTIPLIER = 100


class MultiExpiryError(ValueError):
    """Legs span more than one expiry - the single-expiry payoff model is invalid.

    A calendar or diagonal's near leg expires while the far leg still has time
    value, so its real payoff depends on pricing the survivor at the near
    expiry - which needs a pricing model, not arithmetic. Without an expiry
    field these were previously indistinguishable from a same-expiry pair and
    computed to a confident, completely wrong number. Refused by name instead.
    """


@dataclass(frozen=True)
class Leg:
    right: str  # "C" | "P"
    strike: float
    side: str  # "long" | "short"
    qty: int
    price: float  # per-share premium at entry
    expiry: str = ""  # YYYY-MM-DD; blank means "unspecified, assume shared"
    #: Optional per-leg implied vol as a FRACTION (0.165 = 16.5%). Real
    #: surfaces are skewed - the agent has measured 16.5%-vs-7.4% put/call
    #: splits live - and a single flat IV erases exactly that observation.
    #: None falls back to the shared IV at the call site.
    iv: float | None = None

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    @classmethod
    def parse(cls, d: dict[str, Any]) -> Leg:
        right = str(d.get("right", "")).upper()[:1]
        if right not in ("C", "P"):
            raise ValueError(f"leg right must be C or P, got {d.get('right')!r}")
        side = str(d.get("side", "")).lower()
        if side not in ("long", "short"):
            raise ValueError(f"leg side must be long or short, got {d.get('side')!r}")
        qty = int(d.get("qty", 0))
        if qty <= 0:
            raise ValueError(f"leg qty must be positive, got {qty} (use side for direction)")
        strike, price = float(d["strike"]), float(d.get("price", 0.0))
        if strike <= 0:
            raise ValueError(f"leg strike must be positive, got {strike}")
        if price < 0:
            raise ValueError(f"leg price cannot be negative, got {price}")
        iv = d.get("iv_pct")
        return cls(
            right=right, strike=strike, side=side, qty=qty, price=price,
            expiry=str(d.get("expiry", "") or ""),
            iv=(float(iv) / 100.0) if iv is not None else None,
        )


    @classmethod
    def from_position_leg(cls, d: dict[str, Any]) -> Leg | None:
        """A RECORDED leg (OCC symbol + broker side) -> a Leg, or None.

        The permissive sibling of `parse`, and the one home for a rule that
        had three copies which DISAGREED with the strict one: analytics and
        both local_tools sites accepted "buy"/"sell" (what the broker and the
        model actually write), while `parse` rejects anything but
        long/short. The same leg dict therefore parsed differently depending
        on which of four paths read it.

        Both exist deliberately. `parse` validates MODEL-AUTHORED arguments,
        where a vague side is a defect worth refusing; this reads legs the
        system already recorded, where refusing would mean losing a real
        position's greeks over a vocabulary difference.
        """
        occ = parse_occ(str(d.get("symbol", "")))
        if occ is None:
            return None
        side = str(d.get("side", "")).lower()
        try:
            qty = int(d.get("qty", 1) or 1)
        except (TypeError, ValueError):
            qty = 1
        return cls(
            right=occ["right"], strike=occ["strike"],
            side="long" if side in ("long", "buy") else "short",
            qty=qty, price=float(d.get("price", 0.0) or 0.0), expiry=occ["expiry"],
        )


def require_single_expiry(legs: Iterable[Leg]) -> None:
    """Guard every payoff computation. Raises MultiExpiryError on a calendar.

    A PARTIALLY dated set raises too. It used to be read as "assume shared",
    which is the assumption this guard exists to refuse: the legs that do
    carry a date are the evidence, and one of them differing is exactly the
    case worth catching. All-blank is still allowed - that is the legitimate
    shape of the `simulate_experiments` path, whose leg schema has no expiry
    field and prices one horizon for the whole call.
    """
    legs = list(legs)
    expiries = {l.expiry for l in legs if l.expiry}
    dated = sum(1 for l in legs if l.expiry)
    if len(expiries) > 1 or (expiries and dated != len(legs)):
        raise MultiExpiryError(
            f"legs span {len(expiries)} expiries ({sorted(expiries)}) across {len(legs)} "
            f"legs, {dated} of them dated. Payoff-at-expiry maths assumes one shared "
            f"expiry; a calendar/diagonal needs the far leg priced at the near expiry, "
            f"which this module deliberately does not model."
        )


def band_holds(price: float, low: float | None, high: float | None) -> bool | None:
    """Is `price` inside the claimed band? None when there is no band at all.

    ONE definition of what a forecast band means, because there were two:
    `experiments.Thesis.holds_at` and `ledger.Entry.holds_at` implemented the
    same rule separately - and DISAGREED on the empty case, Thesis returning
    None ("unfalsifiable, do not guess") and Entry returning True ("vacuously
    holds"). Only `Ledger.register` refusing band-less rows kept that
    divergence from ever being reached, which is a guarantee held by an
    unrelated function rather than by the rule itself.

    Bounds are INCLUSIVE: a price exactly on the edge holds the claim. That
    convention now lives in one place, so changing it is one edit rather than
    two that must be remembered together.
    """
    if low is None and high is None:
        return None
    if low is not None and price < low:
        return False
    if high is not None and price > high:
        return False
    return True


def entry_cost(legs: Iterable[Leg]) -> float:
    """Net cash at entry. Positive = debit paid, negative = credit received."""
    return sum(l.sign * l.price * l.qty * CONTRACT_MULTIPLIER for l in legs)


def intrinsic(leg: Leg, spot: float) -> float:
    """Value of one leg's contracts at expiry, signed by side."""
    if leg.right == "C":
        per_share = max(0.0, spot - leg.strike)
    else:
        per_share = max(0.0, leg.strike - spot)
    return leg.sign * per_share * leg.qty * CONTRACT_MULTIPLIER


def pnl_at(legs: Iterable[Leg], spot: float) -> float:
    """P&L at expiry for a terminal price. Exact - no model involved."""
    legs = list(legs)
    require_single_expiry(legs)
    return sum(intrinsic(l, spot) for l in legs) - entry_cost(legs)


def _critical_points(legs: list[Leg]) -> list[float]:
    """Strikes are where the payoff curve bends; sample around and between."""
    strikes = sorted({l.strike for l in legs})
    lo, hi = strikes[0], strikes[-1]
    span = max(hi - lo, hi * 0.5, 1.0)
    pts = [max(0.01, lo - span), *strikes, hi + span]
    # midpoints, so a flat-between-strikes region is sampled too
    mids = [(a + b) / 2 for a, b in zip(pts, pts[1:])]
    return sorted(set(pts + mids))


def max_profit_loss(legs: Iterable[Leg]) -> tuple[float | None, float | None]:
    """(max_profit, max_loss). None means unbounded in that direction.

    Unboundedness is detected structurally from net contract exposure beyond
    the outermost strikes, not by sampling - a naked short call's loss is
    genuinely unbounded and must never be reported as a large finite number,
    which would read as a real worst case.
    """
    legs = list(legs)
    if not legs:
        return (0.0, 0.0)

    # Above the highest strike every call is ITM and every put worthless:
    # net call exposure sets the slope. Below the lowest strike, puts set it.
    call_slope = sum(l.sign * l.qty for l in legs if l.right == "C")
    put_slope = sum(l.sign * l.qty for l in legs if l.right == "P")

    samples = [pnl_at(legs, s) for s in _critical_points(legs)]
    floor_pnl = pnl_at(legs, 0.01)  # spot cannot go below zero

    # Upside is unbounded iff net long calls; that verdict is final and must
    # not be overwritten by the bounded downside. An earlier version let the
    # put branch replace a correctly-unbounded max_profit with the finite
    # floor value - a long straddle then reported a specific max profit
    # despite having genuinely unlimited upside, understating the position
    # and reporting a confident wrong number about its own risk.
    if call_slope > 0:
        max_profit: float | None = None
    else:
        max_profit = max(samples)
        if put_slope > 0:  # long puts pay most as spot -> 0
            max_profit = max(max_profit, floor_pnl)

    if call_slope < 0:  # net short calls: loss grows without limit
        max_loss: float | None = None
    else:
        max_loss = min(samples)
        if put_slope < 0:  # short puts: large but finite, floored at spot 0
            max_loss = min(max_loss, floor_pnl)

    return (max_profit, max_loss)


def breakevens(legs: Iterable[Leg], *, tol: float = 0.01) -> list[float]:
    """Terminal prices where P&L crosses zero. Bisection between sign changes."""
    legs = list(legs)
    pts = _critical_points(legs)
    out: list[float] = []
    for a, b in zip(pts, pts[1:]):
        fa, fb = pnl_at(legs, a), pnl_at(legs, b)
        if fa == 0:
            out.append(a)
        if fa * fb < 0:
            lo, hi = a, b
            for _ in range(60):
                mid = (lo + hi) / 2
                if pnl_at(legs, lo) * pnl_at(legs, mid) <= 0:
                    hi = mid
                else:
                    lo = mid
                if hi - lo < tol:
                    break
            out.append(round((lo + hi) / 2, 2))
    return sorted(set(out))


# ---------------------------------------------------------------- modelled


def _lognormal_grid(spot: float, iv: float, days: float, *, drift: float = 0.0,
                    n: int = 801, width: float = 5.0):
    """Terminal-price grid with lognormal weights. ONE grid, one clock.

    ln(S_T/S_0) ~ N(ln(1+drift) - sigma^2*T/2, sigma^2*T). `drift` is the
    expected TOTAL return over the horizon; 0.0 is the risk-neutral case where
    the underlying is a martingale. Yields (price, weight) pairs with weights
    summing to 1. A grid rather than closed-form because it handles ANY leg
    combination without per-structure case analysis - the same code prices a
    spread, a condor, or something the agent invents.

    There used to be two copies of this loop, one here and one inside
    `pop_given_view`, which is how the market view and the agent's view came to
    be computed by different code. They are now the same code with a parameter,
    so the GAP between them is attributable to the drift and to nothing else.
    """
    t = year_fraction(days)
    sig = max(iv, 1e-6) * math.sqrt(max(t, 1e-9))
    mu = math.log(1.0 + drift) - 0.5 * sig * sig if drift > -1 else -0.5 * sig * sig

    zs = [(-width + 2 * width * i / (n - 1)) for i in range(n)]
    prices = [spot * math.exp(mu + sig * z) for z in zs]
    dens = [math.exp(-0.5 * z * z) for z in zs]
    total = sum(dens)
    return list(zip(prices, [d / total for d in dens]))


def prob_profit(legs: Iterable[Leg], spot: float, iv: float, days: float) -> float | None:
    """P(P&L > 0) at expiry under a lognormal terminal distribution.

    MODELLED, not exact. Assumes lognormal returns and treats current IV as
    the true forward vol - both standard, both wrong in the tails.
    """
    legs = list(legs)
    if not legs or spot <= 0:
        return None
    return sum(w for s, w in _lognormal_grid(spot, iv, days) if pnl_at(legs, s) > 0)


def expected_value(legs: Iterable[Leg], spot: float, iv: float, days: float,
                   *, drift: float = 0.0) -> float | None:
    """Probability-weighted P&L. `drift` = 0 is the MARKET's own distribution.

    **EV at drift 0 is approximately minus the mispricing, and that is the
    point of reporting it - not a reason to decide on it.** A fairly priced
    structure has an expected value of roughly zero under the distribution the
    price itself implies, so once friction is charged the number is negative by
    construction, for every candidate, forever. The live journal shows exactly
    that: cycle after cycle declining "on negative EV after costs", which was
    never a finding about those trades.

    Pass the thesis's own drift to get the number the agent is actually
    claiming. See `experiments.simulate`, which now reports both.
    """
    legs = list(legs)
    if not legs or spot <= 0:
        return None
    return sum(w * pnl_at(legs, s) for s, w in _lognormal_grid(spot, iv, days, drift=drift))


#: A conditional expectation needs something to condition ON. When the model
#: says a structure essentially never wins (or never loses) over the searched
#: grid, the mean of that empty side is not a small number, it is not a number
#: - and dividing by it manufactures an enormous payoff ratio out of a corner
#: of the distribution. Below this probability on either side the ratio is
#: refused and the caller falls back to max/max, which is at least a bound.
MIN_CONDITIONAL_MASS = 0.01


def payoff_ratio(legs: Iterable[Leg], spot: float, iv: float, days: float,
                 *, drift: float = 0.0, friction: float = 0.0
                 ) -> tuple[float, float, float] | None:
    """(E[win | win], E[loss | loss], ratio) - the payoff the bet ACTUALLY offers.

    Kelly's `b` is "how much do I win per unit staked when I win". Sizing has
    been passing `max_profit / max_loss` for it while passing P(profit > 0) for
    `p` - and those are two different events. A vertical spread reaches its max
    profit only in part of the region where it profits at all, and loses its max
    only in part of the region where it loses; pairing the tail-to-tail ratio
    with a whole-region probability is not a conservative approximation, it is a
    DIRECTIONAL one.

    Measured on real structures at live quotes (SPY, 5 days, 10% vol):

        bull put 765/760     max/max 0.19  ->  conditional 0.26   (understated 35%)
        iron condor          max/max 0.59  ->  conditional 0.66   (understated 11%)
        call debit 775/785   max/max 5.17  ->  conditional 2.94   (OVERstated 43%)

    Credit structures win nearly their whole max when they win and lose well
    short of it when they lose, so the tail ratio understates them; debit
    structures are the reverse. The formula was therefore biasing the book
    toward BUYING premium and away from selling it, structurally, at every
    sample size - a preference nobody chose and nothing recorded.

    The agent's own probability is deliberately NOT replaced here. It supplies
    `p`, calibration shrinks it, and this supplies the payoff shape - the same
    facts-and-models split the rest of the module keeps.

    **`friction` is charged to BOTH sides, because you pay it either way.** It
    is what closes the last gap between the two layers that decide a trade: the
    sizing gate opens when `p > 1/(1+b)`, and with friction netted out that is
    algebraically identical to "expected value after costs is positive". Without
    it the gate ran ahead of the EV column by a structure-dependent margin -
    measured on a fair-value zoo at 1.4pp for a wide condor, 4.7pp for a
    vertical, and **16.4pp for a narrow four-leg condor**, which pays four
    spreads that Kelly could not see. Two layers disagreeing about cost is the
    same defect class as two clocks or two calibration numbers.

    A structure whose entire expected win is eaten by friction returns None,
    not a negative ratio: there is no payoff to bet on, and `kelly_fraction`
    should refuse rather than compute with it.
    """
    legs = list(legs)
    if not legs or spot <= 0:
        return None
    p_win = e_win = p_loss = e_loss = 0.0
    for s, w in _lognormal_grid(spot, iv, days, drift=drift):
        pnl = pnl_at(legs, s)
        if pnl > 0:
            p_win += w
            e_win += w * pnl
        else:
            p_loss += w
            e_loss += w * -pnl
    if p_win < MIN_CONDITIONAL_MASS or p_loss < MIN_CONDITIONAL_MASS:
        return None
    mean_win = e_win / p_win - friction
    mean_loss = e_loss / p_loss + friction
    if mean_loss <= 0 or mean_win <= 0:
        return None
    return (mean_win, mean_loss, mean_win / mean_loss)


# ------------------------------------------------ what has to be true (MODELLED)
#
# A desk does not ask "what is the EV" first. It asks **what am I betting on,
# and what has to be true for this to pay** - and then whether it believes that.
# EV at one chosen vol answers neither, and choosing that vol is where a whole
# board of candidates quietly becomes a single unexamined assumption.

#: Search grids for the breakeven scan. Wide enough to bracket any short-dated
#: structure, fine enough not to step over a sign change. Deliberately a scan
#: rather than a bisection from the endpoints: EV is monotone in vol for a
#: structure with one-signed vega, but NOT in drift - a condor peaks at zero
#: drift and falls away both sides, so its breakeven is a BAND. Assuming a
#: single crossing would have reported a confident wrong number for every
#: range structure the agent trades.
_VOL_GRID = tuple(0.005 * i for i in range(1, 241))        # 0.5% .. 120%
_DRIFT_GRID = tuple(-0.20 + 0.002 * i for i in range(201))  # -20% .. +20%


@dataclass(frozen=True)
class Breakeven:
    """Where a structure's EV crosses zero in one variable, and which side wins.

    `crossings` is empty when EV never changes sign across the searched range,
    which is itself the answer ("this is positive at any vol I can model") and
    is reported rather than hidden.
    """

    variable: str
    crossings: tuple[float, ...]
    positive_at_low: bool
    unit: str = "%"

    def describe(self) -> str:
        f = (lambda v: f"{v:.1%}") if self.unit == "%" else (lambda v: f"{v:g}")
        if not self.crossings:
            side = "positive" if self.positive_at_low else "negative"
            return f"EV {side} at every {self.variable} tested"
        if len(self.crossings) == 1:
            c = f(self.crossings[0])
            return (f"wins if {self.variable} < {c}" if self.positive_at_low
                    else f"wins if {self.variable} > {c}")
        lo, hi = f(self.crossings[0]), f(self.crossings[-1])
        return (f"wins if {self.variable} outside {lo}..{hi}" if self.positive_at_low
                else f"wins if {self.variable} between {lo} and {hi}")


def _crossings(f, grid: tuple[float, ...], *, tol: float = 1e-4) -> tuple[float, ...]:
    """Zeros of `f` over `grid`, by scan then bisection. Same shape as `breakevens`."""
    out: list[float] = []
    for a, b in zip(grid, grid[1:]):
        fa, fb = f(a), f(b)
        if fa is None or fb is None:
            continue
        if fa == 0:
            out.append(a)
        elif fa * fb < 0:
            lo, hi = a, b
            for _ in range(60):
                mid = (lo + hi) / 2
                fm = f(mid)
                if fm is None:
                    break
                if f(lo) * fm <= 0:
                    hi = mid
                else:
                    lo = mid
                if hi - lo < tol:
                    break
            out.append((lo + hi) / 2)
    return tuple(sorted(set(out)))


def breakeven_vol(legs: Iterable[Leg], spot: float, days: float, *,
                  friction: float = 0.0, drift: float = 0.0) -> Breakeven | None:
    """The REALIZED VOL at which this structure's EV after costs crosses zero.

    The honest statement of a premium trade. "EV is -$20" depends entirely on
    which volatility you fed it, and the live journal shows a whole board of
    candidates declined on a 21-day realized figure where the 5-day figure
    would have reversed three of them - the number that decided everything was
    the one input nobody had to defend.

    "Wins if realized comes in under 9.2%" cannot be fudged the same way. It is
    a claim about the world, it resolves against the tape, and it is the form a
    vol desk states a trade in.

    Caveat worth keeping: for a structure held to expiry and not delta-hedged,
    P&L is driven by the TERMINAL price, not by the realized-vol path - two
    paths with identical realized vol can settle in different places. This is
    the terminal-distribution width that breaks even, expressed in vol units.
    That is the right unit for the decision and the wrong unit for a variance
    swap, and the difference matters at the tails.
    """
    legs = list(legs)
    if not legs or spot <= 0:
        return None

    def f(iv: float) -> float | None:
        ev = expected_value(legs, spot, iv, days, drift=drift)
        return None if ev is None else ev - friction

    lo = f(_VOL_GRID[0])
    if lo is None:
        return None
    return Breakeven("realized vol", _crossings(f, _VOL_GRID), lo > 0)


def breakeven_drift(legs: Iterable[Leg], spot: float, days: float, *,
                    friction: float = 0.0, iv: float = 0.20) -> Breakeven | None:
    """The TOTAL RETURN over the horizon at which EV after costs crosses zero.

    The same question for a directional structure, where vol is not the bet.
    Returns a BAND for a range structure - a condor wins between two drifts and
    loses outside them, and reporting a single crossing there would be a
    confident wrong number.
    """
    legs = list(legs)
    if not legs or spot <= 0:
        return None

    def f(d: float) -> float | None:
        ev = expected_value(legs, spot, iv, days, drift=d)
        return None if ev is None else ev - friction

    lo = f(_DRIFT_GRID[0])
    if lo is None:
        return None
    return Breakeven("drift", _crossings(f, _DRIFT_GRID), lo > 0)


#: How much one sensitivity must exceed the other before the structure is
#: called a bet on it. Below this the position genuinely rides both and saying
#: so is more useful than forcing a label.
DOMINANCE_RATIO = 2.0


def dominant_risk(greeks: dict[str, float] | None) -> tuple[str, float] | None:
    """Is this a DIRECTION bet or a VOL bet? Returns (label, ratio).

    Compared in the only units that make them commensurable: dollars per 1%
    move in the underlying (delta) against dollars per 1 point of implied vol
    (vega). Measured on two live candidates - an iron condor moved $9 per 1%
    of spot against $23 a vol point, a call spread $199 against $22. Same
    board, same expiry, opposite bets, and the decide cycle priced both off one
    volatility assumption without ever noticing that only one of them cared.
    """
    if not greeks:
        return None
    per_pct_move = abs(greeks.get("delta_dollars", 0.0)) * 0.01
    per_vol_point = abs(greeks.get("vega_dollars", 0.0))
    if per_pct_move <= 0 and per_vol_point <= 0:
        return None
    if per_vol_point <= 0:
        return ("direction", float("inf"))
    if per_pct_move <= 0:
        return ("volatility", float("inf"))
    ratio = per_pct_move / per_vol_point
    if ratio >= DOMINANCE_RATIO:
        return ("direction", ratio)
    if ratio <= 1.0 / DOMINANCE_RATIO:
        return ("volatility", 1.0 / ratio)
    return ("balanced", max(ratio, 1.0 / ratio))


def pop_given_view(
    legs: Iterable[Leg], spot: float, iv: float, days: float, *, drift: float
) -> float | None:
    """P(profit) under the agent's OWN directional view, not the market's.

    `drift` is the expected total return over the horizon (0.02 = +2%). The
    risk-neutral grid above deliberately assumes zero edge; this one lets a
    thesis actually express itself, which is the whole point of forming one.
    The gap between the two numbers IS the claimed edge - and making that gap
    visible is what stops a thesis from being decorative.
    """
    legs = list(legs)
    if not legs or spot <= 0:
        return None
    return sum(w for s, w in _lognormal_grid(spot, iv, days, drift=drift)
               if pnl_at(legs, s) > 0)


# ------------------------------------------------------------- greeks (MODELLED)
#
# Black-Scholes closed form with r=0. Rho is deliberately absent: at <= 7 DTE
# with rates ~4% its effect is cents per contract, and pretending otherwise
# would be precision theatre. Everything here inherits the same caveat as the
# lognormal grid - these are model numbers, advisory, assumption-carrying.

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


#: Volatility does not accrue evenly across the calendar. A business day is a
#: full unit; a weekend or holiday day contributes far less, because the
#: underlying is not trading. Weighting them gives roughly a 308-day year.
#:
#: Corroborated independently: removing Friday->Monday positions from a 1DTE
#: SPX put-write study (Mar 2018 - Sep 2025) cut cumulative return from 28.07%
#: to 8.94% - about two thirds of all profit came from weekend-spanning trades,
#: which is what over-counting weekend time looks like from the other side.
WEEKEND_VOL_WEIGHT = 0.5
VOL_DAYS_PER_YEAR = 308.0

#: Sessions in a trading year. What a realized vol computed from daily closes
#: is annualised by (`market_stats._rolling_vol` uses sqrt(252)).
TRADING_DAYS_PER_YEAR = 252.0

#: What the model's time axis is measured in, and it is CALENDAR time on
#: purpose - see `year_fraction`.
CALENDAR_DAYS_PER_YEAR = 365.0


def year_fraction(days: float) -> float:
    """Calendar days -> years, on the same clock the quoted IV was struck on.

    **ACT/365 calendar time, deliberately, and this reverses what half of this
    module used to do.** Two clocks were live at once: `bs_greeks` and
    `expected_move` divided volatility-weighted days by 308, while the
    lognormal grid divided calendar days by 365. Greeks and probabilities for
    the SAME position were therefore computed on different time axes and
    rendered side by side in one table.

    Unifying them is easy; picking which one is right is the part that matters,
    and the weekend clock is the wrong one HERE:

    **An implied vol already prices the weekend.** OPRA/Alpaca invert
    Black-Scholes with T = calendar days / 365, so a Friday quote's IV is
    already deflated by exactly the weekend it is about to span - that IS the
    observed "Monday IV jump", seen from the price side. Taking that number and
    ALSO discounting the weekend counts the same adjustment twice: on a Friday
    with a Monday expiry it shrinks the modelled 1-sigma move to 89% of what
    the option's own price implies. Every probability, greek and expected move
    then disagrees with the market we are trading against, in the direction
    that makes short premium look safer than it is.

    The weekend clock was never doing damage in production only because no
    caller ever passed `start`, so it silently fell back to a flat 6/7 average
    - within 1.6% of ACT/365, and a landmine for the first person to "fix" the
    missing argument.

    `vol_days` survives for the one job it is genuinely right for: converting a
    trading-time realized vol into calendar-time implied terms, so
    implied-vs-realized is a fair comparison. See `implied_vs_realized`.
    """
    return max(days, 0.0) / CALENDAR_DAYS_PER_YEAR


def vol_days(days: float, start: date | None = None) -> float:
    """Calendar days -> volatility-weighted days.

    NOT the pricing clock (see `year_fraction`). This measures how much
    TRADING time a calendar window contains, which is what you need to compare
    an implied vol against a realized one - implied is annualised over 365
    calendar days, realized over 252 sessions.

    Without a start date we cannot know which days are weekends, so we scale
    by the average weekday share - honest, and still better than counting
    weekends at full weight.
    """
    if days <= 0:
        return 0.0
    if start is None:
        return days * (5 + 2 * WEEKEND_VOL_WEIGHT) / 7.0
    total = 0.0
    whole = int(days)
    for i in range(whole):
        d = start + timedelta(days=i)
        total += 1.0 if d.weekday() < 5 else WEEKEND_VOL_WEIGHT
    frac = days - whole
    if frac:
        d = start + timedelta(days=whole)
        total += frac * (1.0 if d.weekday() < 5 else WEEKEND_VOL_WEIGHT)
    return total


def implied_vs_realized(iv: float, realized_vol: float) -> float | None:
    """Ratio of implied to realized vol, both in the SAME units. >1 = premium.

    The single most useful number a short-premium book has, and it is easy to
    get wrong by 20%: an implied vol is annualised over 365 calendar days, a
    realized vol computed from daily closes over 252 sessions. Comparing them
    raw understates implied by sqrt(252/365) = 0.83 - i.e. it makes selling
    premium look like a worse deal than it is by a fifth, every single time.

    Converts the realized figure onto the implied's calendar clock before
    dividing, so 1.0 genuinely means "the market is charging what the tape has
    been delivering".
    """
    if realized_vol is None or realized_vol <= 0 or iv is None or iv <= 0:
        return None
    realized_calendar = realized_vol * math.sqrt(
        TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR)
    return iv / realized_calendar


def gamma_breakeven(greeks: dict[str, float] | None) -> float | None:
    """The daily underlying move at which gamma P&L exactly offsets theta.

    From theta ~= -0.5 * gamma * sigma^2 * S^2, so breakeven = sqrt(2|theta|/|gamma|).

    **It does not discriminate between structures, and sources claiming it does
    are wrong.** Measured: at a flat 13% IV a short put spread, a long straddle
    and an iron condor all return $5.21 - because theta/gamma is that same BS
    identity for every position at one spot and one vol. What it actually
    returns is **the daily move implied by IV, in dollars** ($3.21 at 8% IV,
    $14.03 at 35%), varying between structures only through skew when legs
    carry different IVs.

    That makes it useful for exactly one thing, which is the important thing:
    compare it against the underlying's REALISED daily range. Implied above
    realised means short premium is being paid for; below means it is being
    donated. It is the implied-vs-realised edge test, denominated in dollars a
    day instead of vol points - which is the same test as an IV/forecast-RV
    ratio, in units the agent can check against the tape directly.

    **The move it returns is per CALENDAR day**, because theta is per calendar
    day and t is calendar time. A realised range measured from daily closes is
    per SESSION, and there are 252 of those against 365 calendar days - so
    comparing the two raw understates implied by sqrt(252/365) = 17%. Use
    `implied_vs_realized` for the vol-point version, which does the conversion.
    """
    if not greeks:
        return None
    theta = greeks.get("theta_dollars", 0.0)
    gamma = greeks.get("gamma_shares", 0.0)
    if gamma == 0:
        return None
    return math.sqrt(2.0 * abs(theta) / abs(gamma))


def bs_greeks(right: str, strike: float, spot: float, iv: float,
              days: float) -> dict[str, float] | None:
    """Per-share greeks for one contract. None when the model is undefined.

    At days <= 0 or iv <= 0 the formulas divide by zero - and the honest
    answer is that an expiring option has no smooth sensitivities, it has a
    cliff. None, never an extrapolation (same refusal discipline as
    MultiExpiryError and unbounded-loss sizing).
    """
    if days <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return None
    # ONE clock, and it is the one the quoted IV was struck on (year_fraction).
    # `start` is accepted and ignored: threading a weekend weighting in here
    # would double-count an adjustment the IV already carries.
    t = year_fraction(days)
    st = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / st
    delta = _norm_cdf(d1) if right == "C" else _norm_cdf(d1) - 1.0
    gamma = _norm_pdf(d1) / (spot * st)
    # theta per CALENDAR day, r=0 (call and put theta coincide at r=0), which
    # is now consistent with t: annual theta / 365 is the decay over one day of
    # the same clock the price is on.
    theta = -(spot * _norm_pdf(d1) * iv) / (2.0 * math.sqrt(t)) / CALENDAR_DAYS_PER_YEAR
    # vega per 1 IV POINT (0.01), the unit traders quote
    vega = spot * _norm_pdf(d1) * math.sqrt(t) / 100.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def net_greeks(legs: list[Leg], spot: float, iv: float,
               days: float) -> dict[str, float] | None:
    """Whole-position greeks in trader units, or None if any leg is undefined.

    delta_shares  equivalent stock shares (signed)
    delta_dollars delta_shares x spot - directional exposure in money
    gamma_shares  shares of delta gained per $1 move in the underlying
    theta_dollars P&L per calendar day from time passing (+ = decay is income)
    vega_dollars  P&L per 1-point move in IV (+ = long vol)

    Per-leg IV is honoured when the leg carries one (skew); otherwise the
    shared IV applies. All-or-nothing: one unpriceable leg makes the position
    shape unknown, and a partial sum would be silently wrong (the same
    reasoning as INV-19's all-legs closes).
    """
    d_sh = g_sh = th = ve = 0.0
    for leg in legs:
        g = bs_greeks(leg.right, leg.strike, spot,
                      leg.iv if leg.iv is not None else iv, days)
        if g is None:
            return None
        k = leg.sign * leg.qty * CONTRACT_MULTIPLIER
        d_sh += k * g["delta"]
        g_sh += k * g["gamma"]
        th += k * g["theta"]
        ve += k * g["vega"]
    return {
        "delta_shares": d_sh,
        "delta_dollars": d_sh * spot,
        "gamma_shares": g_sh,
        "theta_dollars": th,
        "vega_dollars": ve,
    }


def expected_move(spot: float, iv: float, days: float) -> float | None:
    """The market's own 1-sigma move by the horizon, in dollars.

    The first professional sanity check on any thesis: a band INSIDE the
    expected move is agreeing with the market and paying theta for the
    privilege; a band claiming much more than the expected move needs a
    reason the whole market lacks."""
    if spot <= 0 or iv <= 0 or days <= 0:
        return None
    # The MARKET's forecast, so it uses the market's own clock (year_fraction).
    # `start` accepted and ignored, same reason as bs_greeks.
    return spot * iv * math.sqrt(year_fraction(days))


# OCC symbol: ROOT + YYMMDD + C/P + strike*1000 zero-padded to 8.
_OCC = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def parse_occ(symbol: str) -> dict[str, Any] | None:
    """SPY260902P00755000 -> {underlying, expiry, right, strike}. None if not OCC."""
    m = _OCC.match(str(symbol).strip().upper())
    if not m:
        return None
    root, ymd, right, strike = m.groups()
    return {
        "underlying": root,
        "expiry": f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}",
        "right": right,
        "strike": int(strike) / 1000.0,
    }
