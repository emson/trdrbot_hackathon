"""Simulation output, pinned exactly, so a performance refactor stays a refactor.

One two-leg candidate costs ~1.0s of pure CPU and a condor ~1.5s - measured at
726,544 `pnl_at` calls for the vertical - and the agent submits 3-5 per decide
cycle, so 3-7 seconds sit inside the watchdogged call. 94% of it is the
`breakeven_vol` and `breakeven_drift` grid searches re-deriving constants.

Making that faster is only safe if the numbers do not move, so these goldens
were captured from the CURRENT implementation and committed BEFORE it was
touched. They assert EXACT equality, not approximate: the refactor claims
identity, so the test claims identity. If it fires on a last-ulp difference
that means the change reordered arithmetic - the fix is to preserve the order,
not to loosen the assertion.
"""

from __future__ import annotations

import pytest

from trdrbot import experiments
from trdrbot.optmath import Leg

#: A fixed lognormal-free factor grid, so the bootstrap column is deterministic.
FACTORS = [1.0 + (i - 50) / 1000.0 for i in range(101)]

THESIS = experiments.Thesis(claim="SPY drifts down", underlying="SPY",
                            horizon="2026-09-03", drift=-0.012,
                            band_low=750.0, band_high=770.0)

SPOT, IV, DAYS = 769.05, 0.135, 6


def _vertical() -> list[Leg]:
    return [Leg(right="P", strike=766.0, side="long", qty=1, price=8.10),
            Leg(right="P", strike=758.0, side="short", qty=1, price=5.40)]


def _condor() -> list[Leg]:
    return [Leg(right="P", strike=750.0, side="long", qty=1, price=2.10),
            Leg(right="P", strike=760.0, side="short", qty=1, price=4.30),
            Leg(right="C", strike=780.0, side="short", qty=1, price=4.10),
            Leg(right="C", strike=790.0, side="long", qty=1, price=2.00)]


GOLDEN_VERTICAL = {
    "days": 6,
    "entry_cost": 270.0,
    "est_friction": 135.0,
    "ev_after_costs": 49.36254181545078,
    "ev_market": -27.59116188640572,
    "ev_market_after_costs": -162.59116188640573,
    "ev_thesis": 184.36254181545078,
    "expected_loss": 377.70311503658394,
    "expected_move": 13.31121009066192,
    "expected_win": 327.0958273962981,
    "max_loss": -270.0,
    "max_profit": 530.0,
    "net": "debit",
    "payoff_ratio": 0.8660130519829468,
    "pop_bootstrap": 0.42574257425742573,
    "pop_market": 0.3376983385520336,
    "pop_thesis": 0.6059396959051258,
    "risk_reward": 1.962962962962963,
    "spot": 769.05,
    "tail_gap": 0.08804423570539216,
    "thesis_edge": 0.2682413573530922,
    "unbounded_loss": False,
    "usable": True
}

GOLDEN_CONDOR = {
    "days": 6,
    "entry_cost": -429.99999999999994,
    "est_friction": 125.0,
    "ev_after_costs": -89.92839866301432,
    "ev_market": 157.54865903830674,
    "ev_market_after_costs": 32.54865903830674,
    "ev_thesis": 35.07160133698569,
    "expected_loss": 570.8241645599132,
    "expected_move": 13.31121009066192,
    "expected_win": 247.4641236979457,
    "max_loss": -570.0,
    "max_profit": 429.99999999999994,
    "net": "credit",
    "payoff_ratio": 0.433520756586632,
    "pop_bootstrap": 0.36633663366336633,
    "pop_market": 0.7164921889993048,
    "pop_thesis": 0.5876850161459956,
    "risk_reward": 0.7543859649122806,
    "spot": 769.05,
    "tail_gap": -0.35015555533593845,
    "thesis_edge": -0.12880717285330923,
    "unbounded_loss": False,
    "usable": True
}


@pytest.mark.parametrize(("name", "legs", "golden"), [
    ("vertical", _vertical(), GOLDEN_VERTICAL),
    ("condor", _condor(), GOLDEN_CONDOR),
])
def test_simulate_output_is_unchanged(name, legs, golden):
    exp = experiments.Experiment(name=name, legs=legs, rationale="r")

    got = experiments.simulate(exp, THESIS, spot=SPOT, iv=IV, days=DAYS,
                               terminal_factors=FACTORS)

    for key, want in sorted(golden.items()):
        assert got[key] == want, f"{name}.{key}: {got[key]!r} != {want!r}"


def test_the_rendered_comparison_is_unchanged():
    """The string the model actually reads, not just the numbers behind it."""
    exp = experiments.Experiment(name="vertical", legs=_vertical(), rationale="r")
    m = experiments.simulate(exp, THESIS, spot=SPOT, iv=IV, days=DAYS,
                             terminal_factors=FACTORS)

    rendered = experiments.render_comparison(THESIS, experiments.rank([(exp, m)]))

    assert rendered == RENDER_VERTICAL



RENDER_VERTICAL = "### Thesis\nSPY drifts down [holds if 750 <= price <= 770 on 2026-09-03] (drift -1.2%)\nMarket 1-sigma expected move by horizon: +/-$13.31 (i.e. 755.74 to 782.36; spot 769.05). Thesis band [750, 770].\n\n### Candidate expressions (ranked)\n\n**1. vertical** (debit $270)\n   FACTS    max profit $530 | max loss $-270 | R:R 1.96 | breakevens [763.3]\n   MODELLED P(profit) market 34% -> your view 61% | thesis edge +26.8%\n   PAYOFF   after costs, when it wins $327, when it loses $378 -> 0.87:1 (max/max says 1.96). Sizing uses this, not max/max\n   GREEKS   delta $-15,899 (-21 sh) | theta $-12/day | vega $+11/IVpt | gamma +0.8 sh/$ | implied daily move $5.43\n   HISTORY  P(profit) from real-return bootstrap 43% (vs lognormal 34%)  <- tails disagree, edge is assumption-dependent\n   COSTS    est. round-trip friction $135 | EV after costs, YOUR VIEW $+49 | at market's own drift $-163\n   NEEDS    a DIRECTION bet (15x) | wins if drift < -0.9% | EV positive at every realized vol tested\n   r\n\n_FACTS are arithmetic on the contracts. MODELLED assumes lognormal returns at current IV - the tails are wrong and IV is itself a forecast. Weight accordingly._\n_The two EV columns answer different questions. 'At market's own drift' prices the structure under the distribution the QUOTES imply, where a fairly priced trade is worth about zero and after friction is negative - that column is close to a measure of what you are paying to trade, not a verdict on the trade. 'YOUR VIEW' applies the drift you stated. If your thesis cannot make that column positive, the thesis is either too weak or too cheap to express this way._"
