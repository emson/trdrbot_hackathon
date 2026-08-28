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

from typing import Any

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


def kelly_fraction(prob: float, max_profit: float, max_loss: float,
                   *, payoff_ratio: float | None = None) -> float | None:
    """Full-Kelly fraction for a bounded bet. None if it is not computable.

    f* = p - (1-p)/b  where b = win/loss payoff ratio.

    `payoff_ratio` overrides b with the CONDITIONAL one - E[win|win] over
    E[loss|loss] from the same lognormal grid the probabilities come off. The
    default, max_profit/max_loss, pairs a tail-to-tail ratio with a
    whole-region probability, and the two describe different events: a vertical
    reaches its max profit in only part of the region where it profits, and its
    max loss in only part of the region where it loses.

    That mismatch is directional, not conservative. Measured on live
    structures: credit spreads understated by 11-35%, debit spreads overstated
    by 43% - so the formula quietly preferred buying premium to selling it, at
    every sample size (see `optmath.payoff_ratio`).
    """
    if max_loss >= 0 or max_profit <= 0:
        return None
    b = payoff_ratio if payoff_ratio is not None else max_profit / abs(max_loss)
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
    posture: "Any" = None,
    underlying: str = "",
    open_risk_usd: float = 0.0,
    open_risk_by_underlying: dict[str, float] | None = None,
    payoff_ratio: float | None = None,
) -> SizingDecision:
    """How many contracts to trade. Returns 0 when there is no defensible size.

    `payoff_ratio` is the CONDITIONAL win/loss ratio from the simulated
    structure. Absent, Kelly falls back to max_profit/max_loss, which is a
    tail-to-tail ratio paired with a whole-region probability - see
    `kelly_fraction`. The fallback is stated in `explain()` rather than applied
    silently, because the two answers differ by tens of percent and in opposite
    directions for credit and debit structures.
    """
    adj = shrink_probability(stated_confidence, calibration)

    # An unbounded loss has no Kelly fraction - the formula divides by a
    # worst case that does not exist. Refuse rather than substitute a number.
    if max_loss is None or max_profit is None:
        return SizingDecision(
            0, 0.0, None, 0.0, adj,
            "REFUSED: unbounded max loss or profit - Kelly is undefined without a "
            "bounded worst case. Use a defined-risk structure.",
        )

    full = kelly_fraction(adj, max_profit, max_loss, payoff_ratio=payoff_ratio)
    # Below MIN_SAMPLE the shrinkage is a blunt 'halve the claimed edge'
    # heuristic, not a measurement - so it must not VETO a trade, only size
    # it down. Letting it veto inverted the ladder a second time: promotion
    # from EXPLORE to ESTABLISH at n=5 took sizing from 1 contract to 0,
    # because the fabricated shrink drove Kelly to exactly zero (found by
    # the monotonicity check in the D-048 scaffold, not by inspection).
    unmeasured = calibration.n < MIN_SAMPLE
    exploring = unmeasured or (posture is not None and not posture.uses_kelly)

    # THE GATE READS THE STATED PROBABILITY, ALWAYS - two questions, two
    # answers, and conflating them inverted the ladder a second time.
    #
    # "Is there an edge at all?" is a question about the STRUCTURE: a 0.18:1
    # payoff needs ~85% just to break even, and an agent claiming 88% is
    # claiming an edge. That claim is what gets recorded and scored.
    # "How much do we bet on it?" is the question about the TRACK RECORD, and
    # fractional Kelly on the shrunk probability plus the tier cap is the whole
    # answer to it. Letting the record ALSO veto the trade charges the same
    # evidence twice, and it did so discontinuously: the gate used to swap from
    # the stated probability to the shrunk one the moment n crossed
    # MIN_SAMPLE. Measured across the ladder at fixed, EXCELLENT reliability
    # (0.02), an 88%-confidence credit spread at a 0.18:1 payoff sized 1
    # contract at n=5 and ZERO at n=8 - the agent demonstrating more of the
    # same good calibration lost the ability to trade the structure at all,
    # because at n=8 the trust term is still only n/30 = 0.27 and shrank 88%
    # to 72%, below the payoff's break-even. That is the exact failure this
    # block's own comment describes, arriving one threshold later.
    #
    # The shrunk view is not discarded - it is REPORTED (D-009: surface, do not
    # gate) and it still sets the size below.
    gate = kelly_fraction(stated_confidence, max_profit, max_loss,
                          payoff_ratio=payoff_ratio)
    if gate is None or gate <= 0:
        return SizingDecision(
            0, 0.0, full, 0.0, adj,
            f"NO POSITION: your stated probability {stated_confidence:.0%} implies no edge "
            f"at this payoff (Kelly {gate if gate is not None else float('nan'):+.3f}). "
            f"Not trading is the correct action.",
        )
    #: Set when the agent claims an edge its own record does not support. The
    #: trade is permitted at the exploration allocation and the disagreement is
    #: stated, rather than being silently refused.
    record_disagrees = (
        not exploring and (full is None or full <= 0)
    )

    # Phase posture (D-047) supplies the multiplier and the ceiling. Without
    # one, fall back to the original cliff so callers that predate phases keep
    # working.
    if posture is not None and not posture.uses_kelly:
        # A fixed exploration allocation, deliberately NOT Kelly.
        # With no record the shrinkage kills the edge estimate and Kelly
        # returns ~0 - which deadlocked the system into never trading at all.
        # Exploration is a bounded cost paid for information.
        frac = posture.seed_fraction
    else:
        if posture is not None:
            mult = posture.kelly_multiplier
        else:
            established = calibration.n >= MIN_SAMPLE and (calibration.reliability or 1.0) < 0.05
            mult = ESTABLISHED_KELLY if established else UNPROVEN_KELLY
        # Kelly RAISES size above the exploration allocation; it never lowers
        # it. Without the floor, promotion out of EXPLORE cut a positive-edge
        # trade from 2.2% of equity to 0.6%, because the first Kelly rung
        # (x0.05 of a 0.12 full Kelly) is far below the fixed allocation the
        # agent was already trusted with when it knew nothing. More evidence
        # must never mean less size - that is the ladder's stated invariant
        # and it was being violated at the first promotion (see
        # competence.assess's seed_fraction note).
        floor = getattr(posture, "seed_fraction", 0.0) if posture is not None else 0.0
        kelly_frac = 0.0 if full is None else full * mult
        frac = min(max(kelly_frac, floor), MAX_FRACTION)
    risk_budget = equity * frac
    per_contract_risk = abs(max_loss)
    contracts = int(risk_budget // per_contract_risk) if per_contract_risk > 0 else 0

    # Contracts are indivisible: a desk takes one or none, never 0.7. Kelly on
    # a mediocre payoff routinely lands below a single contract (a 0.67:1
    # payoff at 62% confidence is ~0.9% of equity), and rounding that to zero
    # made an EARNED record size SMALLER than the unproven exploration
    # allocation - the ladder inverted. If the edge is positive, one contract
    # is the floor; the book caps below still bound it, and the per-position
    # ceiling still refuses anything genuinely too large for the account.
    if contracts < 1:
        if per_contract_risk <= MAX_FRACTION * equity:
            contracts = 1
        else:
            return SizingDecision(
                0, 0.0, full, frac, adj,
                f"NO POSITION: one contract risks ${per_contract_risk:,.0f}, above the "
                f"{MAX_FRACTION:.0%} per-position ceiling (${MAX_FRACTION * equity:,.0f}). "
                f"Position too large for the account.",
            )

    # Book caps, tightest-binding wins. Both measured in dollars of defined
    # max loss so the number means the same thing everywhere.
    same_name = (open_risk_by_underlying or {}).get(underlying.upper(), 0.0)
    portfolio_cap = posture.book_cap if posture is not None else PORTFOLIO_MAX_AT_RISK
    caps = [
        ("portfolio", portfolio_cap * equity - open_risk_usd,
         portfolio_cap, open_risk_usd, "the book"),
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
    if posture is not None and not posture.uses_kelly:
        track = (f"{posture.tier.upper()} tier, n={calibration.n} - fixed "
                 f"{posture.seed_fraction:.1%} exploration allocation, not Kelly")
    elif posture is not None:
        track = (f"{posture.tier.upper()} tier, n={calibration.n} - "
                 f"Kelly x{posture.kelly_multiplier:.2f} (evidence ramp)")
    else:
        established = calibration.n >= MIN_SAMPLE and (calibration.reliability or 1.0) < 0.05
        track = (
            f"calibration established (n={calibration.n}) so {ESTABLISHED_KELLY:.0%} Kelly"
            if established
            else f"calibration unproven (n={calibration.n}) so {UNPROVEN_KELLY:.0%} Kelly"
        )
    warn = ""
    if record_disagrees:
        warn = (
            f". NOTE: your record does not support this claim - shrunk to {adj:.0%} "
            f"your stated {stated_confidence:.0%} is break-even or worse at this payoff "
            f"(Kelly {full:+.3f}), so the size is the exploration allocation, not an "
            f"earned one. If you take it, take it as a test of the view"
        )
    payoff = (f"payoff {payoff_ratio:.2f} (conditional E[win]/E[loss])"
              if payoff_ratio is not None
              else f"payoff {max_profit / abs(max_loss):.2f} (max/max - no simulated "
                   f"structure matched, so this pairs a tail ratio with a "
                   f"whole-region probability)")
    return SizingDecision(
        contracts, actual, full, frac, adj,
        f"stated {stated_confidence:.0%} -> calibration-adjusted {adj:.0%}; "
        f"{payoff}; full Kelly {full:.3f}; {track}{warn}"
        + (f"; ${open_risk_usd:,.0f} already at risk in the book"
           f" (${same_name:,.0f} on {underlying.upper()})" if open_risk_usd else ""),
    )
