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
    # EV UNDER THE AGENT'S OWN VIEW. Its absence was the quiet defect at the
    # centre of this whole comparison: `ev_after_costs` was computed at drift
    # ZERO - the market's own distribution - where a fairly priced structure
    # has an EV of roughly nothing by definition. Charge friction against that
    # and the number is negative for every candidate, always, no matter what
    # the thesis says. The journal is full of cycles declining on exactly this
    # ("all declined on negative EV after costs"), which was never evidence
    # about those trades: it is what the arithmetic had to return.
    #
    # A thesis that cannot move the number the decision is made on is
    # decorative. This is the number it moves.
    ev_thesis = optmath.expected_value(legs, spot, iv, days, drift=thesis.drift)

    # The payoff this bet actually offers, conditional on winning and on
    # losing. `size_position` uses it as Kelly's `b` in place of max/max, which
    # pairs a tail-to-tail ratio with a whole-region probability.
    # Friction charged to both sides: it is paid whether the trade wins or
    # loses, and netting it here is what makes the sizing gate open at exactly
    # the point EV-after-costs turns positive instead of ahead of it.
    payoff = optmath.payoff_ratio(legs, spot, iv, days, drift=thesis.drift,
                                  friction=friction)

    # WHAT HAS TO BE TRUE. An EV is one number resting on one volatility
    # assumption, and choosing that assumption is where a whole board of
    # candidates silently becomes a single undefended input. These say what the
    # structure actually needs the world to do, and which of the two it is
    # betting on - a desk's first question, and one this comparison could not
    # previously answer.
    be_vol = optmath.breakeven_vol(legs, spot, days, friction=friction, drift=thesis.drift)
    be_drift = optmath.breakeven_drift(legs, spot, days, friction=friction, iv=iv)
    dominant = optmath.dominant_risk(greeks)

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
        "ev_market_after_costs": (ev_market - friction) if ev_market is not None else None,
        "ev_thesis": ev_thesis,
        # The decision number. Kept under the old key as well so nothing that
        # reads `ev_after_costs` silently starts reading a different quantity -
        # but it now carries the THESIS EV, which is what the name always
        # implied and never was.
        "ev_after_costs": (ev_thesis - friction) if ev_thesis is not None else None,
        "est_friction": friction,
        "payoff_ratio": (payoff[2] if payoff else None),
        "expected_win": (payoff[0] if payoff else None),
        "expected_loss": (payoff[1] if payoff else None),
        "breakeven_vol": be_vol,
        "breakeven_drift": be_drift,
        "dominant_risk": dominant,
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
#:
#: **None means APPLY NOTHING, and that is not the same as 0.5** (D-072).
#: elfmem's update is a Beta posterior mean: `new_conf = (a + s*w) / (a + b + w)`.
#: A signal only leaves a block unchanged if the block is ALREADY at that
#: confidence - so the 0.5 that used to encode "learn nothing from luck" was
#: in fact a force pulling every block toward 0.5 from wherever it sat.
#: Measured against the live database with elfmem's own function: a lucky win
#: moved the constitution -0.250 and moved a prediction that had already MISSED
#: +0.018. It punished what was right and rewarded what was wrong - the exact
#: inversion of the comment's intent. "Learn nothing" has to mean no Beta
#: update at all, so these two carry None and the caller skips.
ATTRIBUTION_SIGNAL: dict[str, float | None] = {
    THESIS_RIGHT_EXPRESSION_RIGHT: 0.9,
    THESIS_RIGHT_EXPRESSION_WRONG: 0.65,  # view held up; keep most of the credit
    THESIS_WRONG_EXPRESSION_FAITHFUL: 0.1,
    THESIS_WRONG_PROFITED_ANYWAY: None,   # luck teaches nothing - apply nothing
    UNSCOREABLE: None,                    # we could not judge it - assert nothing
}


def _greeks_line(g: dict[str, Any] | None, days: float) -> str:
    if not g:
        return ""
    warn = ""
    # Near-expiry warning, quantified: short gamma into the final days is pin
    # risk - delta can flip on a $1 move. Surface, never gate (D-009).
    if g["gamma_shares"] < 0 and days <= 2:
        warn = "  <- short gamma near expiry: delta unstable, pin risk"
    be = optmath.gamma_breakeven(g)
    be_txt = f" | implied daily move ${be:,.2f}" if be else ""
    return (
        f"\n   GREEKS   delta ${g['delta_dollars']:+,.0f}"
        f" ({g['delta_shares']:+.0f} sh) | theta ${g['theta_dollars']:+,.0f}/day"
        f" | vega ${g['vega_dollars']:+,.0f}/IVpt"
        f" | gamma {g['gamma_shares']:+.1f} sh/$" + be_txt + warn
    )


def _payoff_line(m: dict[str, Any]) -> str:
    """What you win when you win, against what you lose when you lose.

    R:R above is max-to-max: a vertical reaches its max profit in only part of
    the region where it profits at all, and its max loss in only part of the
    region where it loses. Sizing needs the CONDITIONAL pair, because Kelly's
    `b` asks "how much per unit staked when I win" - and pairing a tail ratio
    with a whole-region probability biased this book toward buying premium
    (measured: credit understated 11-35%, debit overstated 43%).
    """
    r, w, l = m.get("payoff_ratio"), m.get("expected_win"), m.get("expected_loss")
    if r is None or w is None or l is None:
        return ""
    rr = m.get("risk_reward")
    drift = f" (max/max says {rr:.2f})" if rr is not None else ""
    return (f"\n   PAYOFF   after costs, when it wins ${w:,.0f}, when it loses ${l:,.0f}"
            f" -> {r:.2f}:1{drift}. Sizing uses this, not max/max")


def _needs_line(m: dict[str, Any]) -> str:
    """What has to be true, and which variable the structure is really betting on.

    Ordered so the DOMINANT risk reads first: a call spread that moves $199 per
    1% of spot against $22 a vol point is a direction bet, and leading with its
    breakeven vol would put the least relevant number in the most prominent
    place. The other is still shown - a bet you are not primarily taking can
    still be the one that kills you.
    """
    dom, bv, bd = m.get("dominant_risk"), m.get("breakeven_vol"), m.get("breakeven_drift")
    parts: list[str] = []
    if dom:
        label, ratio = dom
        r = "" if ratio == float("inf") else f" ({ratio:.0f}x)"
        parts.append({"direction": f"a DIRECTION bet{r}",
                      "volatility": f"a VOL bet{r}",
                      "balanced": "riding direction and vol about equally"}[label])
    order = [bd, bv] if (dom and dom[0] == "direction") else [bv, bd]
    parts += [b.describe() for b in order if b is not None]
    return "\n   NEEDS    " + " | ".join(parts) if parts else ""


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
        evm = (f"${m['ev_market_after_costs']:+,.0f}"
               if m.get("ev_market_after_costs") is not None else "n/a")
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
            f"{_payoff_line(m)}"
            f"{_greeks_line(m.get('greeks'), m.get('days') or 0)}"
            f"{boot}"
            f"\n   COSTS    est. round-trip friction ${m['est_friction']:,.0f}"
            f" | EV after costs, YOUR VIEW {eac} | at market's own drift {evm}"
            f"{_needs_line(m)}"
            f"\n   {exp.rationale}"
        )
    lines.append(
        "\n_FACTS are arithmetic on the contracts. MODELLED assumes lognormal returns at "
        "current IV - the tails are wrong and IV is itself a forecast. Weight accordingly._"
        "\n_The two EV columns answer different questions. 'At market's own drift' prices "
        "the structure under the distribution the QUOTES imply, where a fairly priced "
        "trade is worth about zero and after friction is negative - that column is close "
        "to a measure of what you are paying to trade, not a verdict on the trade. 'YOUR "
        "VIEW' applies the drift you stated. If your thesis cannot make that column "
        "positive, the thesis is either too weak or too cheap to express this way._"
    )
    return "\n".join(lines)
