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
        return cls(
            right=right, strike=strike, side=side, qty=qty, price=price,
            expiry=str(d.get("expiry", "") or ""),
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


def _lognormal_grid(spot: float, iv: float, days: float, *, n: int = 801, width: float = 5.0):
    """Terminal-price grid with lognormal weights (risk-neutral, r=0).

    ln(S_T/S_0) ~ N(-sigma^2*T/2, sigma^2*T). Yields (price, weight) pairs
    with weights summing to 1. A grid rather than closed-form because it
    handles ANY leg combination without per-structure case analysis - the
    same code prices a spread, a condor, or something the agent invents.
    """
    t = max(days, 0.0) / 365.0
    sig = max(iv, 1e-6) * math.sqrt(max(t, 1e-9))
    mu = -0.5 * sig * sig

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


def expected_value(legs: Iterable[Leg], spot: float, iv: float, days: float) -> float | None:
    """Probability-weighted P&L under the same lognormal assumption."""
    legs = list(legs)
    if not legs or spot <= 0:
        return None
    return sum(w * pnl_at(legs, s) for s, w in _lognormal_grid(spot, iv, days))


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
    t = max(days, 0.0) / 365.0
    sig = max(iv, 1e-6) * math.sqrt(max(t, 1e-9))
    mu = math.log(1.0 + drift) - 0.5 * sig * sig

    n, width = 801, 5.0
    zs = [(-width + 2 * width * i / (n - 1)) for i in range(n)]
    dens = [math.exp(-0.5 * z * z) for z in zs]
    total = sum(dens)
    return sum(
        (d / total)
        for z, d in zip(zs, dens)
        if pnl_at(legs, spot * math.exp(mu + sig * z)) > 0
    )
