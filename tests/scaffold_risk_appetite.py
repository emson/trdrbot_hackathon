"""Scaffold: risk appetite - can ONE lever move the risk/return tradeoff?

    uv run python tests/scaffold_risk_appetite.py

NOT collected by pytest (filename does not start with `test_`). A design
exploration, not a regression guard: the lever does not exist yet, so this
models the proposed one by handing a MODIFIED posture to the REAL sizer. What
is measured is therefore actual `sizing.size_position` behaviour under the
proposal, not a reimplementation of it.

    is there a single knob that buys return for variance HONESTLY - and what
    does it do when the edge the size rests on is not there?

  A1  Where could a lever attach, and would it do anything? Candidate
      attachment points, each measured for INERTNESS.
  A2  The response curve. Size vs appetite at each rung, with the clamps.
  A3  Monte Carlo, three edge regimes, drawdown demotion live in the loop.
  A4  What appetite costs when the edge is imagined rather than real.
  A5  Edge cases, each one run rather than asserted.

**The structure is FAIR-PRICED by construction**, which is the whole reason
this scaffold's numbers can be trusted. The live 766/758 spread was bought at
$1.67 against a bootstrap fair value of $2.45, so simulating it at its traded
price hands the agent a 32% mispricing and every appetite looks brilliant. Legs
are therefore repriced to zero EV under SPY's own resampled history at zero
drift (the same estimator and the same holdout-fitted inflation production
uses), so edge enters ONLY through a stated drift and nowhere else. Verified in
the header line: EV/contract at zero drift is ~$0 and P(profit) lands on the
break-even probability, not near it.

That repricing is what surfaces A1's result, and the first version of this file
missed it entirely.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from trdrbot import competence, market_stats, optmath, sizing
from trdrbot.calibration import Calibration
from trdrbot.experiments import THESIS_RIGHT_EXPRESSION_RIGHT
from trdrbot.optmath import Leg

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "state"

findings: list[str] = []


def note(msg: str) -> None:
    findings.append(msg)


def report(title: str) -> None:
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")


# ------------------------------------------------------------------ the setup
EQUITY = 100_000.0
RESOLVED, RELIABILITY = 29, 0.021926
SPOT, DTE = 769.05, 6
FRICTION = 3.0
CLOSES = market_stats.load_closes(STATE, "SPY")
INFLATE = market_stats.band_inflation(STATE, 3)


def factors(drift: float, seed: str, n: int = 6000) -> list[float]:
    return market_stats.bootstrap_factors(CLOSES, DTE, n_paths=n, seed=seed,
                                          drift=drift, inflate=INFLATE)


_F0 = factors(0.0, "fair")
UNIT = [Leg(right="P", strike=766, side="long", qty=1,
            price=statistics.fmean(max(766 - SPOT * f, 0) for f in _F0)),
        Leg(right="P", strike=758, side="short", qty=1,
            price=statistics.fmean(max(758 - SPOT * f, 0) for f in _F0))]
MP, ML = optmath.max_profit_loss(UNIT)


def pool(drift: float) -> list[float]:
    return [optmath.pnl_at(UNIT, SPOT * f) - FRICTION for f in factors(drift, f"d{drift}")]


def conditional_b(p: list[float]) -> tuple[float, float]:
    w = [x for x in p if x > 0]
    ls = [-x for x in p if x <= 0]
    return statistics.fmean(w) / statistics.fmean(ls), len(w) / len(p)


REGIMES = [("thesis RIGHT", -0.003), ("no edge (fair)", 0.0), ("thesis WRONG", +0.003)]
POOLS = {lbl: pool(d) for lbl, d in REGIMES}
B, P_TRUE_RIGHT = conditional_b(POOLS["thesis RIGHT"])
# The agent states the probability that is TRUE in the RIGHT regime and repeats
# it in the other two - which is exactly the estimation error Kelly is fragile
# to, and the only interesting question about a risk lever.
STATED = P_TRUE_RIGHT
CAL = Calibration(n=RESOLVED, brier=0.15, reliability=RELIABILITY, resolution=0.05,
                  uncertainty=0.24, base_rate=0.6)
FULL_KELLY = sizing.kelly_fraction(STATED, MP, ML, payoff_ratio=B) or 0.0


def posture(n: int, *, verdicts: int = 20, equity: float = EQUITY,
            hw: float = EQUITY) -> competence.Competence:
    pos = [SimpleNamespace(attribution=THESIS_RIGHT_EXPRESSION_RIGHT)] * verdicts
    return competence.assess(resolved=n, reliability=RELIABILITY, positions=pos,
                             equity=equity, high_water=hw)


# ------------------------------------------------------- the PROPOSED lever
#
# Applied to the posture, which after D-098 is the single place all three risk
# scopes come from - so one multiplication reaches book, per-name and
# per-position caps together and cannot desynchronise them.
#
# It scales THREE fields, and A1 is the argument for why fewer will not do.
# Two clamps, and they are the whole safety case:
#   * KELLY_CEILING - half Kelly. Not arbitrary: half Kelly captures ~75% of
#     the growth for ~25% of the variance, and above it the curve is dominated
#     by estimation error rather than edge. `sizing.py` already cites it.
#   * BOOK_CEILING - an absolute share of equity in defined max loss no
#     appetite may cross, so the lever moves the growth/variance tradeoff and
#     never the ruin bound.
APPETITE_MIN, APPETITE_MAX = 0.25, 2.0
KELLY_CEILING = 0.50
BOOK_CEILING = 0.35
FLOOR_CEILING = 0.05


def with_appetite(p: competence.Competence, a: float) -> competence.Competence:
    a = min(APPETITE_MAX, max(APPETITE_MIN, a))
    return replace(
        p,
        kelly_multiplier=min(KELLY_CEILING, p.kelly_multiplier * a),
        seed_fraction=min(FLOOR_CEILING, p.seed_fraction * a),
        book_cap=min(BOOK_CEILING, p.book_cap * a),
    )


def size_at(p: competence.Competence, a: float, *, equity: float = EQUITY,
            open_risk: float = 0.0) -> sizing.SizingDecision:
    return sizing.size_position(
        equity=equity, stated_confidence=STATED, max_profit=MP, max_loss=ML,
        calibration=CAL, posture=with_appetite(p, a), underlying="SPY",
        payoff_ratio=B, open_risk_usd=open_risk)


APPETITES = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
RUNGS = [("EXPLORE", posture(0, verdicts=0)), ("ESTABLISH", posture(10, verdicts=8)),
         ("SCALE", posture(20)), ("MATURE", posture(50, verdicts=50))]
for _want, _p in RUNGS:
    assert _p.tier == _want.lower(), f"{_want} row is {_p.tier}"

print(f"Fair-priced structure: debit ${(UNIT[0].price - UNIT[1].price) * 100:.0f}, "
      f"max profit ${MP:.0f}, max loss ${ML:.0f}")
for lbl, d in REGIMES:
    b, pw = conditional_b(POOLS[lbl])
    print(f"  {lbl:<16} drift {d:>+5.1%}  EV ${statistics.fmean(POOLS[lbl]):>+7.1f}/contract  "
          f"P(profit) {pw:>5.1%}  b {b:.2f}  break-even p {1 / (1 + b):.1%}")
print(f"\nThe agent states {STATED:.1%} in all three regimes. Full Kelly on that "
      f"claim: {FULL_KELLY:.3f}\n(quarter Kelly = {FULL_KELLY * 0.25:.2%} of equity - "
      f"REMEMBER THIS NUMBER, it is the whole of A1).")

# ================================================== A1  WOULD IT DO ANYTHING?
report("A1  Attachment points - which are INERT?")
print("This project's most expensive bug class is code that runs and does")
print("nothing (the compactor, the cache, the shared session - all shipped")
print("dead). A risk lever is a prime candidate, and the answer here was not")
print("the expected one.\n")
print("Each row moves ONE quantity by x2 and reports the size change at SCALE.\n")

base = posture(20)
baseline = size_at(base, 1.0).fraction_of_equity


def probe(label: str, p: competence.Competence) -> float:
    got = sizing.size_position(
        equity=EQUITY, stated_confidence=STATED, max_profit=MP, max_loss=ML,
        calibration=CAL, posture=p, underlying="SPY", payoff_ratio=B
    ).fraction_of_equity
    delta = (got / baseline - 1.0) if baseline else 0.0
    verdict = "INERT - moves nothing" if abs(delta) < 1e-9 else f"{delta:+.0%}"
    print(f"{label:<48} {got:>8.2%} {verdict:>24}")
    return got


print(f"{'x2 applied to':<48} {'size':>8} {'change vs baseline':>24}")
print("-" * 96)
probe("book cap (0.20 -> 0.40), and the two caps under it",
      replace(base, book_cap=base.book_cap * 2))
probe("Kelly multiplier (0.149 -> 0.298)",
      replace(base, kelly_multiplier=base.kelly_multiplier * 2))
probe("seed floor (2.2% -> 4.4%)", replace(base, seed_fraction=base.seed_fraction * 2))
probe("Kelly + caps (the OBVIOUS proposal)",
      replace(base, kelly_multiplier=base.kelly_multiplier * 2,
              book_cap=base.book_cap * 2))
probe("Kelly + caps + floor (what actually works)", with_appetite(base, 2.0))
print(f"{'the EV gate (p > 1/(1+b))':<48} {'-':>8} {'REFUSED - see A4':>24}")

print(f"\nWhy: full Kelly on a realistic claimed edge is {FULL_KELLY:.3f}. At SCALE the")
print(f"tier multiplier is {base.kelly_multiplier:.3f}, so Kelly asks for "
      f"{FULL_KELLY * base.kelly_multiplier:.2%} of equity -")
print(f"BELOW the {base.seed_fraction:.1%} seed floor. `sizing` takes max(Kelly, floor),")
print("so the floor is what sets the size, and doubling Kelly changes nothing.")
note(f"A1: for a REALISTIC edge the seed floor sets the size at EXPLORE, ESTABLISH "
     f"and SCALE - full Kelly {FULL_KELLY:.3f} x the tier multiplier lands below "
     f"{base.seed_fraction:.1%} at every rung but MATURE. So the whole competence "
     f"ladder AND the obvious Kelly-and-caps lever are INERT for ordinary trades. "
     f"A lever that does not also scale the floor would have shipped as a knob that "
     f"moved nothing, and the earlier risk-posture scaffold missed this because it "
     f"priced the structure at its traded debit (a 32% mispricing) where full Kelly "
     f"was 0.48 rather than {FULL_KELLY:.3f}.")

# ==================================================== A2  THE RESPONSE CURVE
report("A2  The response curve - size vs appetite, per rung, with the clamps")
print(f"{'rung':<11}" + "".join(f"{a:>11.2f}x" for a in APPETITES) + "   span  binding")
print("-" * 96)
for name, p in RUNGS:
    fracs = [size_at(p, a).fraction_of_equity for a in APPETITES]
    lo, hi = min(fracs), max(fracs)
    top = with_appetite(p, APPETITES[-1])
    binds = ("seed floor" if abs(hi - top.seed_fraction) < 2e-3
             else "position cap" if abs(hi - top.position_cap) < 2e-3 else "Kelly")
    print(f"{name:<11}" + "".join(f"{x:>11.2%}" for x in fracs)
          + f"   {hi / lo if lo else float('inf'):>4.1f}x  {binds}")

note("A2: with the floor scaled too the lever WORKS - an 8.5x span from minimum to "
     "maximum appetite, monotone throughout. But read the columns, not the rows: "
     "EXPLORE, ESTABLISH and SCALE are IDENTICAL at every appetite. Appetite moves "
     "size and COMPETENCE DOES NOT, because the one constant floor binds at all "
     "three rungs. The lever would work perfectly while the ladder it sits on top of "
     "stayed decorative - which is A6.")

# =============================================== A3  MONTE CARLO, REAL RETURNS
report("A3  Monte Carlo - what appetite actually buys")
print("SPY's own resampled returns applied to the fair-priced structure. Drawdown")
print("demotion is LIVE in the loop, so the ladder's negative feedback is part of")
print(f"what is measured. {50} trades per path - roughly six months at this book's rate.\n")

N_SIMS, N_TRADES = 500, 50


def run_path(p_pool: list[float], appetite: float, rng: random.Random) -> tuple[float, float]:
    eq = hw = EQUITY
    worst = 0.0
    for _ in range(N_TRADES):
        p = posture(RESOLVED, equity=eq, hw=hw)
        d = size_at(p, appetite, equity=eq)
        if d.contracts:
            eq += d.contracts * rng.choice(p_pool)
        if eq <= 1000.0:
            return max(eq, 0.0), 1.0
        hw = max(hw, eq)
        worst = max(worst, 1.0 - eq / hw)
    return eq, worst


results: dict[tuple[str, float], tuple[float, float, float, float, float, float]] = {}
for lbl, _ in REGIMES:
    print(f"\n--- {lbl}")
    print(f"{'appetite':>9} {'median':>10} {'mean log g':>11} {'5th pct':>10} "
          f"{'95th pct':>10} {'mean DD':>8} {'P(DD>20%)':>10}")
    print("-" * 96)
    for a in APPETITES:
        rng = random.Random(abs(hash((lbl, a))) % 99991)
        outs = [run_path(POOLS[lbl], a, rng) for _ in range(N_SIMS)]
        eqs = sorted(o[0] for o in outs)
        dds = [o[1] for o in outs]
        g = statistics.fmean(math.log(e / EQUITY) if e > 1000 else -5.0 for e in eqs)
        row = (eqs[len(eqs) // 2], g, eqs[int(0.05 * len(eqs))],
               eqs[int(0.95 * len(eqs))], statistics.fmean(dds),
               sum(1 for d in dds if d > 0.20) / len(dds))
        results[(lbl, a)] = row
        print(f"{a:>8.2f}x {row[0]:>10,.0f} {row[1]:>11.4f} {row[2]:>10,.0f} "
              f"{row[3]:>10,.0f} {row[4]:>7.1%} {row[5]:>10.1%}")

# ============================================ A4  WHEN THE EDGE IS IMAGINED
report("A4  The asymmetry that decides the design")
print("Appetite is only an honest trade when the edge is real. Two things a")
print("lever COULD move look similar and are not:\n")
print("  SIZE on a +EV bet: more return AND more variance - a genuine")
print("       preference, the operator picking a point on one curve.")
print("  THE EV GATE: bets below p > 1/(1+b) lower expected return AND raise")
print("       variance. No curve to sit on, and it breaks PILLAR-1.\n")
print(f"{'appetite':>9} {'RIGHT med':>11} {'WRONG med':>11} {'gain vs 1x':>11} "
      f"{'extra loss':>11}  verdict")
print("-" * 96)
r1 = results[("thesis RIGHT", 1.0)][0]
w1 = results[("thesis WRONG", 1.0)][0]
for a in APPETITES:
    up = results[("thesis RIGHT", a)][0]
    dn = results[("thesis WRONG", a)][0]
    gain, extra = up - r1, w1 - dn
    print(f"{a:>8.2f}x {up:>11,.0f} {dn:>11,.0f} {gain:>+11,.0f} {extra:>+11,.0f}  "
          f"{'worth it' if gain > extra else 'downside grows faster'}")

# The table above weights RIGHT and WRONG equally, which no operator should,
# and differencing MEDIANS is too noisy to invert for a break-even belief (the
# first attempt produced a non-monotone q*, which is a sign the statistic is
# wrong, not that the world is strange). The clean form: expected LOG growth
# under a belief mixture, maximised over appetite. Log growth is the right
# objective for a compounding book and the mixture is monotone by construction.
print("\nIf you believe the thesis is right with probability q, which appetite")
print("maximises expected log growth? (WRONG carries the rest; 'no edge' sits")
print("between the two, so this brackets the honest answer.)\n")
print(f"{'belief q':>9} " + "".join(f"{a:>9.2f}x" for a in APPETITES) + "   best")
print("-" * 96)
for q in (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00):
    gs = {a: q * results[("thesis RIGHT", a)][1]
             + (1 - q) * results[("thesis WRONG", a)][1] for a in APPETITES}
    best = max(APPETITES, key=lambda a: gs[a])
    print(f"{q:>8.0%} " + "".join(f"{gs[a]:>+10.4f}" for a in APPETITES)
          + f"   {best:.2f}x")

worst_dd = results[("thesis WRONG", APPETITE_MAX)][4]
note("A4: appetite must NOT reach the EV gate. Size on a +EV bet is a point on a "
     "growth/variance curve the operator is entitled to pick; trading below the EV "
     "bar is a worse point on BOTH axes, and PILLAR-1 pins that gate at exactly "
     "EV>0 under the thesis's declared measure.")
note(f"A4': the lever is NOT symmetric. Raising appetite above 1.0x only pays if you "
     f"are roughly 60%+ sure the edge is real, because the wrong-thesis branch loses "
     f"faster than the right-thesis branch gains - Kelly's own fragility, visible in "
     f"the book's own numbers. A wrong thesis at {APPETITE_MAX}x averages a "
     f"{worst_dd:.0%} drawdown. Cutting appetite, by contrast, is nearly free: at "
     f"0.25x a real edge still compounds while the wrong-thesis loss is more than "
     f"halved. The knob should be cheap to turn DOWN and expensive to turn UP.")

# ==================================================== A5  EDGE CASES, RUN
report("A5  Edge cases - run, not asserted")
cases: list[tuple[str, str]] = []

p_hi = with_appetite(posture(20), 2.0)
d = size_at(posture(20), 0.5, open_risk=p_hi.book_cap * EQUITY * 0.9)
cases.append((
    "appetite CUT while the open book already exceeds the new cap",
    f"{d.contracts} contracts - refused on the book cap. Existing positions are "
    f"untouched: sizing only ever gates NEW risk, so a cut can never force a "
    f"liquidation. The book runs over-cap until positions expire."))

for bad, desc in ((0.0, "zero"), (-3.0, "negative"), (100.0, "absurdly large")):
    p = with_appetite(posture(20), bad)
    cases.append((f"appetite set to {desc} ({bad})",
                  f"clamped to [{APPETITE_MIN}, {APPETITE_MAX}] -> Kelly "
                  f"x{p.kelly_multiplier:.3f}, floor {p.seed_fraction:.2%}, "
                  f"book {p.book_cap:.0%}"))

bad_nest = [n for n, p in RUNGS for a in APPETITES
            if not (with_appetite(p, a).position_cap <= with_appetite(p, a).underlying_cap
                    <= with_appetite(p, a).book_cap)]
cases.append(("position <= underlying <= book, at every rung x every appetite",
              "HOLDS - all three derive from `book_cap`, so one multiplication moves "
              "them together" if not bad_nest else f"BROKEN at {set(bad_nest)}"))

mono = []
for a in APPETITES:
    sizes = [size_at(p, a).fraction_of_equity for _, p in RUNGS]
    if sizes != sorted(sizes):
        mono.append(a)
cases.append(("more evidence never means less size, at every appetite",
              "HOLDS across all rungs" if not mono else f"BROKEN at appetite {mono}"))

top = with_appetite(posture(50, verdicts=50), APPETITE_MAX)
cases.append((f"appetite {APPETITE_MAX}x at MATURE (the most the lever can ask)",
              f"Kelly x{top.kelly_multiplier:.3f} (ceiling {KELLY_CEILING}), floor "
              f"{top.seed_fraction:.1%}, book {top.book_cap:.0%} (ceiling "
              f"{BOOK_CEILING:.0%}), one position {top.position_cap:.1%}"))

dd = with_appetite(posture(50, verdicts=50, equity=89_000.0), APPETITE_MAX)
cases.append(("an 11% drawdown at maximum appetite",
              f"demoted to {dd.tier.upper()}, book {dd.book_cap:.0%} - the ladder's "
              f"own feedback still fires and appetite cannot switch it off"))

zero_edge = sizing.size_position(
    equity=EQUITY, stated_confidence=1 / (1 + B) - 0.01, max_profit=MP, max_loss=ML,
    calibration=CAL, posture=with_appetite(posture(50, verdicts=50), APPETITE_MAX),
    underlying="SPY", payoff_ratio=B)
cases.append(("maximum appetite on a structure with NO claimed edge",
              f"{zero_edge.contracts} contracts - '{zero_edge.reason[:60]}...'. The "
              f"EV gate is upstream of every appetite multiplication and untouched "
              f"by it."))

for i, (case, outcome) in enumerate(cases, 1):
    print(f"\n{i}. {case}\n   -> {outcome}")

note("A5: the one case with no clean answer is the CUT - lowering appetite can "
     "leave the book legitimately over its new cap, because sizing gates new risk "
     "and never liquidates. That is the right behaviour (a preference change must "
     "not become a forced seller) but it means the cap is a target on the way down, "
     "not an invariant, and it has to be REPORTED or an operator reads an over-cap "
     "book as a bug.")

# ======================================== A6  DOES THE CIRCUIT BREAKER BREAK?
report("A6  The drawdown brake - does demotion actually cut size?")
print("A3 shows a wrong thesis at 2.00x averaging a ~47% drawdown despite the")
print("ladder demoting all the way to EXPLORE at a 10% loss. A2 says why: the")
print("EXPLORE, ESTABLISH and SCALE rows are IDENTICAL, because `SEED_FRACTION`")
print("is one constant for every tier and it binds at all three. So demotion")
print("changes the tier and not the size. The safety argument for an aggressive")
print("lever - 'the ladder contains it' - is false as the code stands.\n")

#: The proposed repair, and it is the same move D-098 already made for the
#: other three scopes: derive the floor from the tier's own budget instead of
#: pinning it to a constant. 0.22 is chosen so EXPLORE keeps exactly today's
#: 2.2%, so a fresh account is unchanged.
SEED_SHARE = competence.SEED_FRACTION / competence.TIERS[competence.EXPLORE]["cap"]


def tier_floor(p: competence.Competence) -> competence.Competence:
    return replace(p, seed_fraction=p.book_cap * SEED_SHARE)


print(f"{'tier':<12} {'floor NOW':>11} {'floor DERIVED':>14}   size at 1.00x now -> derived")
print("-" * 96)
for name, p in RUNGS:
    now = size_at(p, 1.0).fraction_of_equity
    der = sizing.size_position(
        equity=EQUITY, stated_confidence=STATED, max_profit=MP, max_loss=ML,
        calibration=CAL, posture=tier_floor(with_appetite(p, 1.0)), underlying="SPY",
        payoff_ratio=B).fraction_of_equity
    print(f"{name:<12} {p.seed_fraction:>11.2%} {tier_floor(p).seed_fraction:>14.2%}   "
          f"{now:>10.2%} -> {der:.2%}")

top = posture(50, verdicts=50)
dd_post = posture(50, verdicts=50, equity=89_000.0)
now_full = size_at(top, 1.0).fraction_of_equity
now_dd = size_at(dd_post, 1.0, equity=89_000.0).fraction_of_equity
der_full = sizing.size_position(
    equity=EQUITY, stated_confidence=STATED, max_profit=MP, max_loss=ML, calibration=CAL,
    posture=tier_floor(with_appetite(top, 1.0)), underlying="SPY", payoff_ratio=B
).fraction_of_equity
der_dd = sizing.size_position(
    equity=89_000.0, stated_confidence=STATED, max_profit=MP, max_loss=ML, calibration=CAL,
    posture=tier_floor(with_appetite(dd_post, 1.0)), underlying="SPY", payoff_ratio=B
).fraction_of_equity
print("\nAn 11% drawdown, MATURE -> EXPLORE:")
print(f"  today:   {now_full:.2%} -> {now_dd:.2%}  ({1 - now_dd / now_full:+.0%} change)")
print(f"  derived: {der_full:.2%} -> {der_dd:.2%}  ({1 - der_dd / der_full:+.0%} change)")

# The comparison has to be at MATCHED SIZE or it measures the wrong thing: a
# derived floor is 5.5% at MATURE against today's flat 2.2%, so running both at
# 1.00x compares a more aggressive book with a less aggressive one and the
# brake is invisible underneath. The third row is the derived floor turned down
# to roughly today's base, which is the only fair test of whether demotion
# helps once it can actually cut.
print("\nMonte Carlo, WRONG thesis. The first two rows are NOT comparable - the")
print("derived floor is a bigger book at the same appetite. The third matches it.")
print(f"{'config':<28} {'median':>10} {'5th pct':>10} {'mean DD':>9} {'P(DD>20%)':>10}")
print("-" * 96)


def run_variant(p_pool, appetite, rng, derived: bool):
    eq = hw = EQUITY
    worst = 0.0
    for _ in range(N_TRADES):
        post = with_appetite(posture(RESOLVED, equity=eq, hw=hw), appetite)
        if derived:
            post = tier_floor(post)
        d = sizing.size_position(
            equity=eq, stated_confidence=STATED, max_profit=MP, max_loss=ML,
            calibration=CAL, posture=post, underlying="SPY", payoff_ratio=B)
        if d.contracts:
            eq += d.contracts * rng.choice(p_pool)
        if eq <= 1000.0:
            return max(eq, 0.0), 1.0
        hw = max(hw, eq)
        worst = max(worst, 1.0 - eq / hw)
    return eq, worst


VARIANTS = [("constant floor, 2.00x", False, 2.0),
            ("tier-derived, 2.00x", True, 2.0),
            ("tier-derived, 0.85x (matched)", True, 0.85)]
for label, derived, app in VARIANTS:
    rng = random.Random(4242)
    outs = [run_variant(POOLS["thesis WRONG"], app, rng, derived) for _ in range(N_SIMS)]
    eqs = sorted(o[0] for o in outs)
    dds = [o[1] for o in outs]
    print(f"{label:<28} {eqs[len(eqs) // 2]:>10,.0f} {eqs[int(0.05 * len(eqs))]:>10,.0f} "
          f"{statistics.fmean(dds):>8.1%} {sum(1 for d in dds if d > 0.20) / len(dds):>10.1%}")

note("A6: `SEED_FRACTION` is a single constant across all four tiers, so promotion "
     "and DEMOTION both leave size unchanged wherever the floor binds - which A1 "
     "shows is everywhere below MATURE for a realistic edge. An 11% drawdown "
     "currently cuts the next trade by 13%; with the floor derived from the tier it "
     "cuts by 63%. The drawdown circuit breaker does not brake today, and it is "
     "exactly what an aggressive appetite setting would have been relying on.")
note("A6': but the derived floor is NOT a safety improvement by itself - it RAISES "
     "the base (2.2% -> 5.5% at MATURE), so swapped in at the same appetite it loses "
     "MORE, brake and all. It buys RESPONSIVENESS: the ladder starts meaning "
     "something and the lever gets something to pull. It must therefore ship with a "
     "recalibrated neutral appetite rather than as a drop-in, and the matched row "
     "above is the only fair read of it.")

report("VERDICT")
print(f"{len(findings)} finding(s):\n")
for f in findings:
    tag, body = f.split(": ", 1)
    print(f"  {tag}. {body}\n")
