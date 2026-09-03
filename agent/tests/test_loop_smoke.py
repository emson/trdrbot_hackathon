"""Loop smoke: the whole learning ladder, offline, with KNOWN inputs.

Not a market simulation. Every input has known properties (a perfectly
calibrated forecaster, a badly overconfident one), so the machine's RESPONSE
is what is under test.

This tier exists because the scratch version of it found two credit-assignment
bugs that every unit test passed straight over (D-057): credit silently skipped
on external closes, and outcomes silently lost on unconsolidated blocks. Those
are emergent - visible only when the stages run together. Offline and fast, so
it runs in the default suite; the elfmem half stayed a contract test.
"""

from __future__ import annotations

import random

from trdrbot import competence, sizing
from trdrbot.calibration import Forecast, score
from trdrbot.positions import Position

GOOD = "thesis_right_expression_right"
LEARNED = "thesis_wrong_expression_faithful"
LUCK = "thesis_wrong_profited_anyway"


def _career(kind: str, weeks: int = 8, per_week: int = 6, seed: int = 11):
    """Weekly batches of resolved forecasts through the real scorer/ladder/sizer."""
    rng = random.Random(seed)
    resolved: list[Forecast] = []
    verdicts: list[str] = []
    rows = []
    for week in range(1, weeks + 1):
        for i in range(per_week):
            if kind == "calibrated":
                p = rng.choice([0.35, 0.45, 0.55, 0.65, 0.75])
                hit = rng.random() < p
                verdicts.append(GOOD if hit else LEARNED)
            else:  # says 85%, right 55%, and its wins are luck
                p, hit = 0.85, rng.random() < 0.55
                verdicts.append(LUCK if hit else LEARNED)
            resolved.append(Forecast(position_id=f"{kind}{week}{i}", probability=p,
                                     outcome=hit, resolved_at="t"))
        cal = score(resolved)
        comp = competence.assess(
            resolved=cal.n, reliability=cal.reliability,
            positions=[Position(position_id=f"h{j}", attribution=v)
                       for j, v in enumerate(verdicts)],
            equity=100_000.0, high_water=100_000.0)
        dec = sizing.size_position(
            equity=100_000.0, underlying="SPY", stated_confidence=0.70,
            max_profit=2400.0, max_loss=-1200.0, calibration=cal, posture=comp)
        rows.append((cal.n, comp.tier, dec.contracts))
    return rows


def test_a_calibrated_agent_earns_its_way_up_the_ladder():
    rows = _career("calibrated")
    tiers = [t for _, t, _ in rows]
    sizes = [k for _, _, k in rows]
    assert tiers[-1] in (competence.SCALE, competence.MATURE), f"stuck at {tiers[-1]}"
    assert sizes == sorted(sizes), f"size shrank as evidence grew: {sizes}"
    assert sizes[-1] > sizes[0], f"size never grew: {sizes}"


def test_an_overconfident_agent_is_held_back_by_attribution():
    """Its P&L is fine; its wins are luck. A book of luck is not competence."""
    good = _career("calibrated")
    bad = _career("overconfident")
    assert competence.MATURE not in [t for _, t, _ in bad]
    assert bad[-1][1] in (competence.EXPLORE, competence.ESTABLISH)
    assert bad[-1][2] <= good[-1][2], "overconfidence must not out-size calibration"


def test_drawdown_demotes_and_recovery_restores():
    cal = score([Forecast(position_id=f"d{i}", probability=0.6, outcome=(i % 5 != 0),
                          resolved_at="t") for i in range(48)])
    history = [Position(position_id=f"h{i}", attribution=GOOD) for i in range(40)]

    def tier_at(equity: float) -> str:
        return competence.assess(resolved=cal.n, reliability=cal.reliability,
                                 positions=history, equity=equity,
                                 high_water=100_000.0).tier

    assert tier_at(100_000) in (competence.SCALE, competence.MATURE)
    assert tier_at(89_000) == competence.EXPLORE
    assert tier_at(100_000) in (competence.SCALE, competence.MATURE), "must recover"


def test_every_attribution_quadrant_produces_its_own_verdict():
    """The four outcomes must stay distinguishable - collapsing any two is how
    the loop learns the wrong lesson from a real trade."""
    from trdrbot import experiments
    seen = {experiments.attribute(held, profited)[0]
            for held in (True, False) for profited in (True, False)}
    assert len(seen) == 4, f"quadrants collapsed: {seen}"
    signal = experiments.ATTRIBUTION_SIGNAL
    # "Teaches nothing" means NO Beta update, not an update toward 0.5 (D-072).
    # Measured with elfmem's own function: applying 0.5 moved the constitution
    # -0.250 and moved a prediction that had already MISSED +0.018. A signal
    # is only neutral for a block already sitting at that confidence.
    assert signal[experiments.THESIS_WRONG_PROFITED_ANYWAY] is None, \
        "luck must apply nothing at all - 0.5 is a force toward 0.5, not neutrality"
    assert signal[experiments.UNSCOREABLE] is None, \
        "an unjudgeable outcome must assert nothing about the blocks"
    assert signal[experiments.THESIS_RIGHT_EXPRESSION_RIGHT] > 0.5
    assert signal[experiments.THESIS_WRONG_EXPRESSION_FAITHFUL] < 0.5
