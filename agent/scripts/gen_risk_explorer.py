"""Regenerate the data block in `docs/risk_appetite_explorer.html` (D-099).

    uv run python scripts/gen_risk_explorer.py

The explorer used to carry a JavaScript RE-IMPLEMENTATION of `sizing.py` and
`competence.py` - the sizer, the calibration shrink, the tier table, the
demotion ladder. It had already drifted three ways while its own on-load badge
printed "verified against Python", because the nine reference points it checked
covered neither the ESTABLISH rung nor the derived-floor mode nor any demotion
path. A verification badge that structurally cannot fail is worse than none: it
converts an unverified page into one that claims verification.

So the page stops modelling the policy and starts DISPLAYING it. Everything
that could drift is computed here, by the real `competence.assess` and
`sizing.size_position`, and emitted as a lookup table. What is left in the
browser is arithmetic over that table plus the drawing code.

The insight that makes it cheap: **`frac` does not depend on equity.**
`max(kelly_frac, floor)` capped by the position ceiling uses no equity at all -
only `contracts = floor(equity * frac / per_contract)` does. So the whole policy
is 4 tiers x 15 appetites x 3 drawdown states = 180 rows, and the simulation on
top of it is two multiplications per trade.

TWO BLOCKS, because they have different truth conditions:

  policy  - derived from CODE. `tests/test_regressions.py` rebuilds it from the
            committed `market` inputs and fails if it no longer matches, so
            changing the ladder without regenerating this page is caught.
  market  - derived from DATA that moves as the book runs. A dated snapshot,
            labelled as one. The test does not pin it, because a resolved
            thesis tomorrow would fail a clean tree.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent          # agent/ - the code and the state
REPO_ROOT = ROOT.parent                                # the repo - docs/ lives here
sys.path.insert(0, str(ROOT / "src"))

from trdrbot import competence, ids, market_stats, optmath, sizing  # noqa: E402
from trdrbot.calibration import Calibration  # noqa: E402
from trdrbot.experiments import THESIS_RIGHT_EXPRESSION_RIGHT  # noqa: E402
from trdrbot.optmath import Leg  # noqa: E402

PAGE = REPO_ROOT / "docs" / "risk_appetite_explorer.html"
BEGIN = "/* BEGIN GENERATED - scripts/gen_risk_explorer.py - do not edit by hand */"
END = "/* END GENERATED */"

EQUITY = 100_000.0
SPOT, DTE, FRICTION = 769.05, 6, 3.0
STRIKES = (766, 758)

#: 15 stops across the permitted range, matching the slider's own resolution.
APPETITES = [round(competence.APPETITE_MIN + i * 0.125, 3) for i in range(15)]

#: Each rung is shown at the MINIMUM evidence that earns it - one rule, stated
#: on the page. The old blob back-solved to three different `resolved` counts
#: (10 / 29 / 50) with nothing saying so, which made the ESTABLISH row a
#: fabricated agent presented as a rung of one ladder.
RESOLVED_AT = {competence.EXPLORE: 0, competence.ESTABLISH: 5,
               competence.SCALE: 15, competence.MATURE: 40}

#: equity/high-water ratios that land in each demotion band. Produced by driving
#: the REAL `_demote` through `assess`, never by looking up a neighbouring tier:
#: the old page did the latter, so a demoted SCALE agent borrowed ESTABLISH's
#: Kelly (0.0625) instead of keeping its own evidence (0.0829).
DD_STATES = [1.00, 0.93, 0.88]


def _positions(n: int) -> list[SimpleNamespace]:
    """Verdicts enough to clear MATURE's strict attribution gate."""
    return [SimpleNamespace(attribution=THESIS_RIGHT_EXPRESSION_RIGHT)] * (10 if n >= 40 else 0)


def build_policy(structure: dict, cal_raw: dict) -> dict:
    """The response surface, from the real ladder and the real sizer.

    Pure in (structure, calibration, code): given the same two inputs it is
    reproducible exactly, which is what lets a test pin it.
    """
    cal = Calibration(n=cal_raw["n"], brier=0.15, reliability=cal_raw["reliability"],
                      resolution=0.05, uncertainty=0.24, base_rate=0.6)
    rows: dict[str, list[list[dict]]] = {}
    for tier, n in RESOLVED_AT.items():
        per_appetite = []
        for a in APPETITES:
            per_dd = []
            for ratio in DD_STATES:
                p = competence.assess(
                    resolved=n, reliability=0.02, positions=_positions(n),
                    equity=EQUITY * ratio, high_water=EQUITY, appetite=a)
                d = sizing.size_position(
                    equity=EQUITY, stated_confidence=structure["stated"],
                    max_profit=structure["maxProfit"], max_loss=structure["maxLoss"],
                    calibration=cal, posture=p, underlying="SPY",
                    payoff_ratio=structure["b"])
                per_dd.append({
                    "tier": p.tier, "frac": round(d.kelly_used, 6),
                    "binding": d.binding, "book": round(p.book_cap, 6),
                    "pos": round(p.position_cap, 6), "name": round(p.underlying_cap, 6),
                    "seed": round(p.seed_fraction, 6),
                    "kelly": round(p.kelly_multiplier, 6),
                    # What Kelly ASKS for on this structure, before the floor
                    # and the ceiling have their say. The page shows it beside
                    # `frac` so a reader can see the floor winning.
                    "kellyAsk": round(max(0.0, (d.kelly_full or 0.0) * p.kelly_multiplier), 6),
                    "realised": round(p.realised_appetite, 4),
                })
            per_appetite.append(per_dd)
        rows[tier] = per_appetite
        # The rung must actually BE the rung at zero drawdown, or the table is
        # labelled with a tier it never reaches.
        assert rows[tier][0][0]["tier"] == tier, f"{tier} row assessed as {rows[tier][0][0]['tier']}"
    return {
        "appetites": APPETITES,
        "tiers": list(RESOLVED_AT),
        "builtAtResolved": RESOLVED_AT,
        "demote": {"oneTier": competence.DEMOTE_ONE_TIER_AT,
                   "toExplore": competence.DEMOTE_TO_EXPLORE_AT},
        "bookCeiling": competence.BOOK_CEILING,
        "appetiteMin": competence.APPETITE_MIN,
        "appetiteMax": competence.APPETITE_MAX,
        "seedShare": competence.SEED_SHARE,
        "rows": rows,
    }


def build_market() -> dict:
    """SPY's own resampled returns on a FAIR-PRICED version of the live spread.

    The repricing is the reason these numbers can be trusted at all: the live
    766/758 spread was bought at $1.67 against a bootstrap fair value of $2.45,
    so simulating it at its traded price hands the agent a 32% mispricing and
    every appetite looks brilliant. Priced to zero EV at zero drift, edge enters
    only through a stated drift.
    """
    state = ROOT / "data" / "state"
    closes = market_stats.load_closes(state, "SPY")
    inflate = market_stats.band_inflation(state, 3)

    def factors(drift: float, seed: str, n: int = 6000) -> list[float]:
        return market_stats.bootstrap_factors(closes, DTE, n_paths=n, seed=seed,
                                              drift=drift, inflate=inflate)

    fair = factors(0.0, "fair")
    unit = [Leg(right="P", strike=STRIKES[0], side="long", qty=1,
                price=statistics.fmean(max(STRIKES[0] - SPOT * f, 0) for f in fair)),
            Leg(right="P", strike=STRIKES[1], side="short", qty=1,
                price=statistics.fmean(max(STRIKES[1] - SPOT * f, 0) for f in fair))]
    mp, ml = optmath.max_profit_loss(unit)

    def pool(drift: float) -> list[float]:
        return [round(optmath.pnl_at(unit, SPOT * f) - FRICTION, 2)
                for f in factors(drift, f"d{drift}", n=500)]

    pools = {"right": sorted(pool(-0.003)), "wrong": sorted(pool(+0.003))}
    wins = [x for x in pools["right"] if x > 0]
    losses = [-x for x in pools["right"] if x <= 0]
    b = statistics.fmean(wins) / statistics.fmean(losses)
    stated = len(wins) / len(pools["right"])
    return {
        # ids.market_today(), not date.today(): the same date discipline the
        # rest of the project runs on (D-032).
        "asOf": ids.market_today().isoformat(),
        "structure": {"maxProfit": round(mp, 2), "maxLoss": round(ml, 2),
                      "perContractRisk": round(abs(ml), 2), "b": round(b, 4),
                      "stated": round(stated, 4), "breakEven": round(1 / (1 + b), 4)},
        "cal": {"n": 29, "reliability": 0.021926},
        "pools": pools,
        "poolStats": {k: {"ev": round(statistics.fmean(v), 2)} for k, v in pools.items()},
    }


def main() -> int:
    market = build_market()
    policy = build_policy(market["structure"], market["cal"])
    block = (f"{BEGIN}\nconst DATA = "
             + json.dumps({"policy": policy, "market": market}, separators=(",", ":"))
             + f";\n{END}")
    html = PAGE.read_text(encoding="utf-8")
    new, n = re.subn(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block,
                     html, count=1, flags=re.S)
    if not n:
        print(f"markers not found in {PAGE} - add {BEGIN} ... {END} around the DATA const")
        return 1
    PAGE.write_text(new, encoding="utf-8")
    cells = len(policy["tiers"]) * len(APPETITES) * len(DD_STATES)
    print(f"wrote {PAGE.name}: {cells} policy rows, {len(market['pools']['right'])} "
          f"P&L samples per regime, market as of {market['asOf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
