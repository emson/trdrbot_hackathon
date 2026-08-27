"""Position sizing - the largest single lever on long-run profit.

Sizing was previously left entirely to the model, which picked a quantity with
no reference to edge, bankroll, or its own track record. Kelly links size to
edge; the literature is unanimous that full Kelly is unusable in practice
because it is acutely fragile to estimation error, and that the right posture
is fractional Kelly used as a CEILING rather than a target (Thorp: half-Kelly
captures ~75% of the growth rate for ~25% of the variance).

The part that matters most here: **the fraction is earned, not assumed.**

An agent's stated confidence is an estimate, and Kelly's fragility is entirely
about estimate quality - so size is gated on the agent's own measured
calibration (D-013). A model that says 0.90 and is right half the time gets
its probabilities shrunk toward the base rate and its fraction cut. A model
that has demonstrated, over a real sample, that its 0.70s come in about 70% of
the time earns a larger fraction.

That closes the self-improving loop in the most direct way available: better
calibration is not a metric on a dashboard, it is literally permission to bet
more. Experience -> demonstrated reliability -> larger size -> more profit,
with no step that rewards mere confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calibration import Calibration

#: Never exceed this share of equity on one position, whatever Kelly says.
#: A hard ceiling, because every input to Kelly is an estimate and estimates
#: fail together in exactly the conditions that matter.
MAX_FRACTION = 0.05
#: Three caps, each a distinct meaning, all measured the same way: dollars of
#: DEFINED max loss against equity (D-037). Per-position bounds a single
#: mistake; per-underlying bounds correlated mistakes (several options
#: positions on one name are one bet wearing hats); portfolio bounds the book.
#: This replaced an opaque `frac /= (1 + open_count)` divisor that was a proxy
#: for the same idea, invented before real risk was tracked - it double-counted
#: with the portfolio cap and produced an effective limit nobody chose.
PER_UNDERLYING_MAX_AT_RISK = 0.08
PORTFOLIO_MAX_AT_RISK = 0.15

#: Kelly multiplier once calibration is genuinely established. Quarter-Kelly
#: is the conservative end of the practitioner range, chosen because an
#: 8-day sample can never make our estimates "statistically stable".
ESTABLISHED_KELLY = 0.25

#: Multiplier before any calibration record exists. Deliberately tiny: at this
#: point the agent's stated probabilities are unvalidated assertions.
UNPROVEN_KELLY = 0.05

#: Resolved forecasts needed before calibration is treated as informative.
MIN_SAMPLE = 8


@dataclass
class SizingDecision:
    contracts: int
    fraction_of_equity: float
    kelly_full: float | None
    kelly_used: float
    adjusted_probability: float
    reason: str

    def explain(self) -> str:
        return (
            f"{self.contracts} contract(s) = {self.fraction_of_equity:.2%} of equity. "
            f"{self.reason}"
        )


def shrink_probability(stated: float, cal: Calibration) -> float:
    """Pull a stated probability toward the observed base rate.

    An agent's confidence is only worth its demonstrated reliability. With no
    track record we shrink hard toward 0.5; as the sample grows and the
    reliability term stays low, the stated number is trusted more. This is the
    mechanism by which overconfidence costs money instead of just showing up
    in a report.
    """
    if cal.n < MIN_SAMPLE or cal.reliability is None:
        return 0.5 + (stated - 0.5) * 0.5  # halve the claimed edge

    # reliability is mean squared gap between stated confidence and observed
    # frequency; 0 is perfect. 0.05 is already poor calibration.
    trust = max(0.0, 1.0 - (cal.reliability / 0.05))
    trust = min(1.0, trust)
    # Sample size also buys trust, saturating around 30 resolved forecasts.
    trust *= min(1.0, cal.n / 30.0)
    return 0.5 + (stated - 0.5) * (0.5 + 0.5 * trust)


def kelly_fraction(prob: float, max_profit: float, max_loss: float) -> float | None:
    """Full-Kelly fraction for a bounded bet. None if it is not computable.

    f* = p - (1-p)/b  where b = win/loss payoff ratio.
    """
    if max_loss >= 0 or max_profit <= 0:
        return None
    b = max_profit / abs(max_loss)
    if b <= 0:
        return None
    return prob - (1 - prob) / b


def size_position(
    *,
    equity: float,
    stated_confidence: float,
    max_profit: float | None,
    max_loss: float | None,
    calibration: Calibration,
    underlying: str = "",
    open_risk_usd: float = 0.0,
    open_risk_by_underlying: dict[str, float] | None = None,
) -> SizingDecision:
    """How many contracts to trade. Returns 0 when there is no defensible size."""
    adj = shrink_probability(stated_confidence, calibration)

    # An unbounded loss has no Kelly fraction - the formula divides by a
    # worst case that does not exist. Refuse rather than substitute a number.
    if max_loss is None or max_profit is None:
        return SizingDecision(
            0, 0.0, None, 0.0, adj,
            "REFUSED: unbounded max loss or profit - Kelly is undefined without a "
            "bounded worst case. Use a defined-risk structure.",
        )

    full = kelly_fraction(adj, max_profit, max_loss)
    if full is None or full <= 0:
        return SizingDecision(
            0, 0.0, full, 0.0, adj,
            f"NO POSITION: calibration-adjusted probability {adj:.0%} implies no edge "
            f"at this payoff (Kelly {full if full is not None else float('nan'):+.3f}). "
            f"Not trading is the correct action.",
        )

    established = calibration.n >= MIN_SAMPLE and (calibration.reliability or 1.0) < 0.05
    mult = ESTABLISHED_KELLY if established else UNPROVEN_KELLY

    frac = min(full * mult, MAX_FRACTION)
    risk_budget = equity * frac
    per_contract_risk = abs(max_loss)
    contracts = int(risk_budget // per_contract_risk) if per_contract_risk > 0 else 0

    if contracts < 1:
        return SizingDecision(
            0, 0.0, full, frac, adj,
            f"NO POSITION: risk budget ${risk_budget:,.0f} is below one contract's "
            f"max loss ${per_contract_risk:,.0f}. Position too large for the account.",
        )

    # Book caps, tightest-binding wins. Both measured in dollars of defined
    # max loss so the number means the same thing everywhere.
    same_name = (open_risk_by_underlying or {}).get(underlying.upper(), 0.0)
    caps = [
        ("portfolio", PORTFOLIO_MAX_AT_RISK * equity - open_risk_usd,
         PORTFOLIO_MAX_AT_RISK, open_risk_usd, "the book"),
        (f"{underlying.upper() or 'underlying'} concentration",
         PER_UNDERLYING_MAX_AT_RISK * equity - same_name,
         PER_UNDERLYING_MAX_AT_RISK, same_name, f"{underlying.upper() or 'one name'}"),
    ]
    for label, budget_left, pct, already, subject in caps:
        if budget_left < per_contract_risk:
            return SizingDecision(
                0, 0.0, full, frac, adj,
                f"REFUSED ({label}): already carrying ${already:,.0f} of defined max-loss "
                f"against a {pct:.0%} cap (${pct * equity:,.0f}). Adding more means "
                f"{subject}, not this trade, is the bet.",
            )
        contracts = min(contracts, int(budget_left // per_contract_risk))

    actual = (contracts * per_contract_risk) / equity
    track = (
        f"calibration established (n={calibration.n}, reliability "
        f"{calibration.reliability:.3f}) so {ESTABLISHED_KELLY:.0%} Kelly"
        if established
        else f"calibration unproven (n={calibration.n}) so {UNPROVEN_KELLY:.0%} Kelly"
    )
    return SizingDecision(
        contracts, actual, full, frac, adj,
        f"stated {stated_confidence:.0%} -> calibration-adjusted {adj:.0%}; "
        f"full Kelly {full:.3f}; {track}"
        + (f"; ${open_risk_usd:,.0f} already at risk in the book"
           f" (${same_name:,.0f} on {underlying.upper()})" if open_risk_usd else ""),
    )
