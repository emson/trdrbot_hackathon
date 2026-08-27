"""Thesis -> candidate experiments -> simulate -> execute one -> attribute.

The loop this enables:

    1. form a falsifiable thesis about the underlying
    2. generate several DIFFERENT structures expressing that same thesis
    3. simulate all of them deterministically, before risking anything
    4. execute one
    5. at resolution, attribute the outcome to the THESIS or the EXPRESSION
    6. form the next thesis knowing which of the two was actually wrong

Step 5 is the one that makes the loop worth building. A thesis can be right
while its expression is wrong (called the direction correctly, picked strikes
too tight, stopped out) and a thesis can be wrong while the trade still profits
(got paid for the wrong reason). A system that scores only P&L cannot tell
these apart, and reinforces whichever story happens to correlate with money -
which is how an agent learns a superstition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import optmath
from .optmath import Leg


@dataclass
class Thesis:
    """A falsifiable claim, with a machine-checkable condition.

    `claim` is for the reader; `band_low`/`band_high` are what actually gets
    scored. A thesis with no checkable band cannot be attributed at
    resolution, so it is not really a thesis - `holds_at` returns None and the
    learning path treats it as unscoreable rather than guessing.
    """

    claim: str
    underlying: str
    horizon: str  # YYYY-MM-DD
    drift: float = 0.0  # expected total return over the horizon (0.02 = +2%)
    band_low: float | None = None
    band_high: float | None = None

    def holds_at(self, price: float) -> bool | None:
        if self.band_low is None and self.band_high is None:
            return None  # unfalsifiable - deliberately not guessed
        if self.band_low is not None and price < self.band_low:
            return False
        if self.band_high is not None and price > self.band_high:
            return False
        return True

    def summary(self) -> str:
        band = ""
        if self.band_low is not None or self.band_high is not None:
            lo = f"{self.band_low:g}" if self.band_low is not None else "-inf"
            hi = f"{self.band_high:g}" if self.band_high is not None else "+inf"
            band = f" [holds if {lo} <= price <= {hi} on {self.horizon}]"
        return f"{self.claim}{band} (drift {self.drift:+.1%})"


@dataclass
class Experiment:
    """One candidate structure expressing a thesis."""

    name: str
    legs: list[Leg]
    rationale: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


#: Round-trip cost per contract as a fraction of the premium, when the agent
#: supplies mid prices. Options spreads are wide - you buy at the ask and sell
#: at the bid, twice (entry and exit). Simulating at mid and ignoring this
#: systematically overstates every edge, and does so most for the cheap
#: far-OTM options that look most attractive on a payoff diagram.
DEFAULT_ROUND_TRIP_COST = 0.10


def simulate(
    exp: Experiment, thesis: Thesis, spot: float, iv: float, days: float,
    *, round_trip_cost: float = DEFAULT_ROUND_TRIP_COST,
    terminal_factors: list[float] | None = None,
    friction_usd: float | None = None,
) -> dict[str, Any]:
    """Score one candidate. Exact facts and modelled estimates kept distinct."""
    legs = exp.legs
    try:
        cost = optmath.entry_cost(legs)
        mp, ml = optmath.max_profit_loss(legs)
        bes = optmath.breakevens(legs)
    except optmath.MultiExpiryError as e:
        return {"error": str(e), "usable": False}

    # Frictions, charged against the gross premium traded across all legs.
    gross_premium = sum(l.price * l.qty * optmath.CONTRACT_MULTIPLIER for l in legs)
    # Real spreads beat the flat model whenever the agent has quotes: a
    # round trip crosses roughly one full bid/ask spread per leg, and
    # spreads are wildly non-uniform (7% on a liquid SPY call, 30%+ on a
    # single-name weekly). The flat 10%-of-premium default remains the
    # fallback when no quotes were supplied.
    friction = friction_usd if friction_usd is not None else gross_premium * round_trip_cost

    greeks = optmath.net_greeks(legs, spot, iv, days)
    pop_market = optmath.prob_profit(legs, spot, iv, days)
    pop_thesis = optmath.pop_given_view(legs, spot, iv, days, drift=thesis.drift)
    ev_market = optmath.expected_value(legs, spot, iv, days)

    # Risk/reward only means something when both ends are bounded. An
    # unbounded loss has no ratio - reporting one would imply a cap that
    # does not exist.
    rr = None
    if mp is not None and ml is not None and ml != 0:
        rr = abs(mp / ml)

    # The claimed edge: how much better this looks under the agent's own view
    # than under the market's. If a thesis cannot move this number, it is
    # decorative - the structure would look the same to someone with no view.
    edge = None
    if pop_thesis is not None and pop_market is not None:
        edge = pop_thesis - pop_market

    # Bootstrap from real historical returns (demeaned): same martingale
    # centering as the lognormal grid, so the GAP between the two is
    # attributable to tail shape - when they diverge, the edge depends on
    # the tail assumption, and the agent should know that.
    pop_bootstrap = None
    tail_gap = None
    if terminal_factors:
        wins = sum(1 for f in terminal_factors if optmath.pnl_at(legs, spot * f) > 0)
        pop_bootstrap = wins / len(terminal_factors)
        if pop_market is not None:
            tail_gap = pop_bootstrap - pop_market

    return {
        "usable": True,
        # exact - arithmetic on the contract, no model
        "entry_cost": cost,
        "net": "debit" if cost > 0 else "credit",
        "max_profit": mp,
        "max_loss": ml,
        "unbounded_loss": ml is None,
        "breakevens": bes,
        "risk_reward": rr,
        # modelled - lognormal + IV, advisory only
        "pop_market": pop_market,
        "pop_thesis": pop_thesis,
        "ev_market": ev_market,
        "ev_after_costs": (ev_market - friction) if ev_market is not None else None,
        "est_friction": friction,
        "thesis_edge": edge,
        "pop_bootstrap": pop_bootstrap,
        "tail_gap": tail_gap,
        "greeks": greeks,
        "days": days,
        "expected_move": optmath.expected_move(spot, iv, days),
        "spot": spot,
    }


def rank(results: list[tuple[Experiment, dict[str, Any]]]) -> list[tuple[Experiment, dict[str, Any]]]:
    """Order candidates best-first by thesis edge, then bounded risk.

    Deliberately NOT by expected value: EV under a lognormal-with-current-IV
    assumption is the single most model-dependent number here, and ranking by
    it would quietly hand the decision to the model's tails. Edge (how much
    the thesis improves the odds) is what the agent is actually claiming to
    know; bounded risk breaks ties toward structures whose worst case is a
    fact rather than an estimate.
    """

    def key(item: tuple[Experiment, dict[str, Any]]):
        _, m = item
        if not m.get("usable"):
            return (2, 0.0, 0.0)
        unbounded = 1 if m.get("unbounded_loss") else 0
        edge = m.get("thesis_edge")
        return (unbounded, -(edge if edge is not None else -1.0), 0.0)

    return sorted(results, key=key)


# ------------------------------------------------------------- attribution

THESIS_RIGHT_EXPRESSION_RIGHT = "thesis_right_expression_right"
THESIS_RIGHT_EXPRESSION_WRONG = "thesis_right_expression_wrong"
THESIS_WRONG_EXPRESSION_FAITHFUL = "thesis_wrong_expression_faithful"
THESIS_WRONG_PROFITED_ANYWAY = "thesis_wrong_profited_anyway"
UNSCOREABLE = "unscoreable"


def attribute(thesis_held: bool | None, profited: bool) -> tuple[str, str]:
    """Separate 'was the view right' from 'was the trade right'.

    Returns (verdict, what-to-learn). The two failure modes need opposite
    corrections, and the lucky-win case needs no reinforcement at all:
    """
    if thesis_held is None:
        return (UNSCOREABLE, "thesis had no checkable condition - cannot attribute; write falsifiable bands next time")
    if thesis_held and profited:
        return (THESIS_RIGHT_EXPRESSION_RIGHT, "reinforce both the view and this way of expressing it")
    if thesis_held and not profited:
        return (
            THESIS_RIGHT_EXPRESSION_WRONG,
            "the VIEW was correct - do not weaken it. The structure lost anyway: "
            "strikes, width, sizing or the stop were wrong for a thesis that came true",
        )
    if not thesis_held and not profited:
        return (
            THESIS_WRONG_EXPRESSION_FAITHFUL,
            "the VIEW was wrong - the structure faithfully expressed it and lost as it should. "
            "Correct the view, not the structure",
        )
    return (
        THESIS_WRONG_PROFITED_ANYWAY,
        "PROFITED ON A WRONG VIEW - do not reinforce the thesis. This was luck or an "
        "unrelated effect; treating it as confirmation is how a superstition forms",
    )


#: Signal fed to elfmem at resolution. Deliberately NOT proportional to P&L.
#: A lucky win must not reinforce, and a right-view-wrong-structure loss must
#: not punish the view - so the signal follows the ATTRIBUTION, not the money.
ATTRIBUTION_SIGNAL = {
    THESIS_RIGHT_EXPRESSION_RIGHT: 0.9,
    THESIS_RIGHT_EXPRESSION_WRONG: 0.65,  # view held up; keep most of the credit
    THESIS_WRONG_EXPRESSION_FAITHFUL: 0.1,
    THESIS_WRONG_PROFITED_ANYWAY: 0.5,  # neutral: learn nothing from luck
    UNSCOREABLE: 0.5,
}


def _greeks_line(g: dict[str, Any] | None, days: float) -> str:
    if not g:
        return ""
    warn = ""
    # Near-expiry warning, quantified: short gamma into the final days is pin
    # risk - delta can flip on a $1 move. Surface, never gate (D-009).
    if g["gamma_shares"] < 0 and days <= 2:
        warn = "  <- short gamma near expiry: delta unstable, pin risk"
    return (
        f"\n   GREEKS   delta ${g['delta_dollars']:+,.0f}"
        f" ({g['delta_shares']:+.0f} sh) | theta ${g['theta_dollars']:+,.0f}/day"
        f" | vega ${g['vega_dollars']:+,.0f}/IVpt"
        f" | gamma {g['gamma_shares']:+.1f} sh/$" + warn
    )


def render_comparison(
    thesis: Thesis, ranked: list[tuple[Experiment, dict[str, Any]]]
) -> str:
    """Comparison table for the decide prompt - facts and estimates separated."""
    lines = [f"### Thesis\n{thesis.summary()}"]
    # The market's own 1-sigma forecast, next to the thesis's claim. A band
    # inside the expected move is agreeing with the market and paying for the
    # privilege; a band claiming much more needs a reason the market lacks.
    for _, m0 in ranked:
        em, sp = m0.get("expected_move"), m0.get("spot")
        if em and sp:
            lo = f"{thesis.band_low:g}" if thesis.band_low is not None else "-inf"
            hi = f"{thesis.band_high:g}" if thesis.band_high is not None else "+inf"
            lines.append(
                f"Market 1-sigma expected move by horizon: +/-${em:,.2f}"
                f" (i.e. {sp - em:,.2f} to {sp + em:,.2f}; spot {sp:,.2f})."
                f" Thesis band [{lo}, {hi}]."
            )
            break
    lines.append("\n### Candidate expressions (ranked)")
    for i, (exp, m) in enumerate(ranked, 1):
        if not m.get("usable"):
            lines.append(f"\n**{i}. {exp.name}** - UNUSABLE: {m.get('error')}")
            continue
        ml = "UNBOUNDED" if m["max_loss"] is None else f"${m['max_loss']:,.0f}"
        mp = "UNBOUNDED" if m["max_profit"] is None else f"${m['max_profit']:,.0f}"
        rr = f"{m['risk_reward']:.2f}" if m["risk_reward"] is not None else "n/a (unbounded)"
        edge = f"{m['thesis_edge']:+.1%}" if m["thesis_edge"] is not None else "n/a"
        pm = f"{m['pop_market']:.0%}" if m["pop_market"] is not None else "n/a"
        pt = f"{m['pop_thesis']:.0%}" if m["pop_thesis"] is not None else "n/a"
        eac = f"${m['ev_after_costs']:+,.0f}" if m["ev_after_costs"] is not None else "n/a"
        boot = ""
        if m.get("pop_bootstrap") is not None:
            gap = m.get("tail_gap")
            warn = "  <- tails disagree, edge is assumption-dependent" if gap is not None and abs(gap) >= 0.05 else ""
            boot = f"\n   HISTORY  P(profit) from real-return bootstrap {m['pop_bootstrap']:.0%}" \
                   f" (vs lognormal {pm}){warn}"
        lines.append(
            f"\n**{i}. {exp.name}** ({m['net']} ${abs(m['entry_cost']):,.0f})"
            f"\n   FACTS    max profit {mp} | max loss {ml} | R:R {rr}"
            f" | breakevens {m['breakevens']}"
            f"\n   MODELLED P(profit) market {pm} -> your view {pt} | thesis edge {edge}"
            f"{_greeks_line(m.get('greeks'), m.get('days') or 0)}"
            f"{boot}"
            f"\n   COSTS    est. round-trip friction ${m['est_friction']:,.0f}"
            f" | EV after costs {eac}"
            f"\n   {exp.rationale}"
        )
    lines.append(
        "\n_FACTS are arithmetic on the contracts. MODELLED assumes lognormal returns at "
        "current IV - the tails are wrong and IV is itself a forecast. Weight accordingly._"
    )
    return "\n".join(lines)
