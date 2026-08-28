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
from dataclasses import dataclass
from typing import Any, Iterable

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
    def parse(cls, d: dict[str, Any]) -> "Leg":
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


def require_single_expiry(legs: Iterable[Leg]) -> None:
    """Guard every payoff computation. Raises MultiExpiryError on a calendar."""
    expiries = {l.expiry for l in legs if l.expiry}
    if len(expiries) > 1:
        raise MultiExpiryError(
            f"legs span {len(expiries)} expiries ({sorted(expiries)}). Payoff-at-expiry "
            f"maths assumes one shared expiry; a calendar/diagonal needs the far leg "
            f"priced at the near expiry, which this module deliberately does not model."
        )


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


def vol_days(days: float, start: "date | None" = None) -> float:
    """Calendar days -> volatility-weighted days.

    NOT the pricing clock (see `year_fraction`). This measures how much
    TRADING time a calendar window contains, which is what you need to compare
    an implied vol against a realized one - implied is annualised over 365
    calendar days, realized over 252 sessions.

    Without a start date we cannot know which days are weekends, so we scale
    by the average weekday share - honest, and still better than counting
    weekends at full weight.
    """
    from datetime import date as _date, timedelta

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


def bs_greeks(right: str, strike: float, spot: float, iv: float, days: float,
              start: "date | None" = None) -> dict[str, float] | None:
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


def net_greeks(legs: list[Leg], spot: float, iv: float, days: float,
               start: "date | None" = None) -> dict[str, float] | None:
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
                      leg.iv if leg.iv is not None else iv, days, start)
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


def expected_move(spot: float, iv: float, days: float,
                  start: "date | None" = None) -> float | None:
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
