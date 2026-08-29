"""Scaffold: sweep a zoo of option structures through the whole decision stack.

    uv run python tests/scaffold_structure_zoo.py

NOT collected by pytest (the filename does not start with `test_`) - the
invariants it checks are pinned as real tests in `test_regressions.py` under
D-079. What this adds is the READABLE form: the tables a trader wants to look
at when asking "is the stack balanced", which an assertion cannot show.

The method is the point. Every structure is priced at its expected intrinsic
under **the same lognormal grid the stack itself prices with**, so a fair bet
is fair BY CONSTRUCTION and any edge the stack reports on one is an artefact of
the stack rather than of the market. That is what turned a vague "is Kelly
biased?" into a number: max/max Kelly reached -2.313 on bets with precisely
zero edge.
"""
from __future__ import annotations

from trdrbot import competence, experiments, optmath, sizing
from trdrbot.calibration import Calibration
from trdrbot.local_tools import _unreachable_rules
from trdrbot.optmath import Leg, _lognormal_grid

SPOT, DAYS, IV = 100.0, 7.0, 0.25


def fair_price(right: str, strike: float, spot=SPOT, iv=IV, days=DAYS) -> float:
    """Expected intrinsic under the SAME grid the stack prices with."""
    grid = _lognormal_grid(spot, iv, days)
    if right == "C":
        return sum(w * max(0.0, s - strike) for s, w in grid)
    return sum(w * max(0.0, strike - s) for s, w in grid)


def leg(right, strike, side, qty=1):
    return Leg(right=right, strike=strike, side=side, qty=qty,
               price=fair_price(right, strike))


def zoo():
    """A realistic structure zoo, every one priced at fair value."""
    out = {}
    for lo, hi in ((98, 103), (100, 105), (95, 100), (90, 95), (103, 108)):
        out[f"call debit {lo}/{hi}"] = [leg("C", lo, "long"), leg("C", hi, "short")]
        out[f"put credit {lo}/{hi}"] = [leg("P", hi, "short"), leg("P", lo, "long")]
        out[f"call credit {lo}/{hi}"] = [leg("C", lo, "short"), leg("C", hi, "long")]
        out[f"put debit {lo}/{hi}"] = [leg("P", hi, "long"), leg("P", lo, "short")]
    out["iron condor 90/95-105/110"] = [
        leg("P", 95, "short"), leg("P", 90, "long"),
        leg("C", 105, "short"), leg("C", 110, "long")]
    out["iron condor 97/99-101/103"] = [
        leg("P", 99, "short"), leg("P", 97, "long"),
        leg("C", 101, "short"), leg("C", 103, "long")]
    out["call butterfly 95/100/105"] = [
        leg("C", 95, "long"), leg("C", 100, "short", 2), leg("C", 105, "long")]
    out["long straddle 100"] = [leg("C", 100, "long"), leg("P", 100, "long")]
    out["short strangle 95/105"] = [leg("P", 95, "short"), leg("C", 105, "short")]
    return out


def report(title):
    print(f"\n{'='*92}\n{title}\n{'='*92}")


violations: list[str] = []


def check(cond, msg):
    if not cond:
        violations.append(msg)
    return cond


# ---------------------------------------------------------------- INV-A
report("INV-A  Kelly's sign must agree with EV's sign on a FAIRLY priced structure")
print("A fair bet has EV = 0, so Kelly must be 0. Anything else is the stack inventing")
print("an edge (or refusing a real one) out of its own payoff arithmetic.\n")
print(f"{'structure':<28} {'EV':>8} {'P(win)':>7} | {'b max/max':>10} {'Kelly':>8} "
      f"| {'b cond':>7} {'Kelly':>8}")
print("-" * 92)
worst_maxmax = 0.0
for name, legs in zoo().items():
    ev = optmath.expected_value(legs, SPOT, IV, DAYS)
    p = optmath.prob_profit(legs, SPOT, IV, DAYS)
    mp, ml = optmath.max_profit_loss(legs)
    pr = optmath.payoff_ratio(legs, SPOT, IV, DAYS)
    if mp is None or ml is None or pr is None:
        print(f"{name:<28} {ev:>8.2f} {p:>7.1%} | {'unbounded / no conditional ratio':>44}")
        continue
    b_mm = mp / abs(ml)
    k_mm = sizing.kelly_fraction(p, mp, ml)
    k_cd = sizing.kelly_fraction(p, mp, ml, payoff_ratio=pr[2])
    worst_maxmax = max(worst_maxmax, abs(k_mm))
    print(f"{name:<28} {ev:>8.2f} {p:>7.1%} | {b_mm:>10.2f} {k_mm:>+8.3f} "
          f"| {pr[2]:>7.2f} {k_cd:>+8.3f}")
    check(abs(ev) < 1.0, f"INV-A: {name} EV {ev:.2f} not ~0 on a fairly priced structure")
    check(abs(k_cd) < 0.02,
          f"INV-A: {name} conditional Kelly {k_cd:+.3f} not ~0 on a FAIR bet")
    # ...and with real friction charged, a FAIR bet must be REFUSED, not merely
    # sized small: you are paying to take a coin flip.
    gross = sum(l.price * l.qty * 100 for l in legs)
    fr = gross * experiments.DEFAULT_ROUND_TRIP_COST
    pr_net = optmath.payoff_ratio(legs, SPOT, IV, DAYS, friction=fr)
    k_net = (sizing.kelly_fraction(p, mp, ml, payoff_ratio=pr_net[2])
             if pr_net else None)
    check(k_net is None or k_net < 0,
          f"INV-A(friction): {name} Kelly {k_net} >= 0 on a fair bet that costs "
          f"${fr:.0f} to put on")
print(f"\nmax |Kelly| under max/max on a fair bet: {worst_maxmax:+.3f}  "
      f"<- the bias the conditional ratio removes")

# ---------------------------------------------------------------- INV-B
report("INV-B  Conditional expectations must sit inside the structure's own bounds")
bad = 0
for name, legs in zoo().items():
    mp, ml = optmath.max_profit_loss(legs)
    pr = optmath.payoff_ratio(legs, SPOT, IV, DAYS)
    if pr is None or mp is None or ml is None:
        continue
    w, l, _ = pr
    if not (w <= mp + 1e-6 and l <= abs(ml) + 1e-6):
        bad += 1
        violations.append(f"INV-B: {name} E[win]={w:.2f}>maxP={mp:.2f} or E[loss]={l:.2f}>maxL={abs(ml):.2f}")
print(f"checked {len(zoo())} structures, {bad} out of bounds")

# ---------------------------------------------------------------- INV-C
report("INV-C  EV at the reported breakeven vol must actually be ~0")
print(f"{'structure':<28} {'breakeven':>10} {'EV there':>10}  reads as")
print("-" * 92)
for name, legs in list(zoo().items())[:8] + [("iron condor 90/95-105/110", zoo()["iron condor 90/95-105/110"])]:
    be = optmath.breakeven_vol(legs, SPOT, DAYS, friction=0.0)
    if not be or not be.crossings:
        print(f"{name:<28} {'no crossing':>10}")
        continue
    v = be.crossings[0]
    ev_there = optmath.expected_value(legs, SPOT, v, DAYS)
    print(f"{name:<28} {v:>10.2%} {ev_there:>10.3f}  {be.describe()}")
    check(abs(ev_there) < 0.5, f"INV-C: {name} EV {ev_there:.3f} at its own breakeven vol")

# ---------------------------------------------------------------- INV-D
report("INV-D  dominant_risk must classify the zoo the way a desk would")
expect = {"iron condor": "volatility", "long straddle": "volatility",
          "short strangle": "volatility", "butterfly": "volatility"}
for name, legs in zoo().items():
    g = optmath.net_greeks(legs, SPOT, IV, DAYS)
    d = optmath.dominant_risk(g)
    label = d[0] if d else "n/a"
    want = next((v for k, v in expect.items() if k in name), "direction")
    flag = "" if label == want else f"   <- expected {want}"
    if flag:
        violations.append(f"INV-D: {name} classified {label}, a desk would say {want}")
    print(f"  {name:<28} {label:<12} ratio {d[1]:>6.1f}{flag}" if d else f"  {name:<28} n/a")

# ---------------------------------------------------------------- INV-E
report("INV-E  Size must never fall as evidence grows, at any payoff in the zoo")
inversions = 0
for name, legs in zoo().items():
    mp, ml = optmath.max_profit_loss(legs)
    pr = optmath.payoff_ratio(legs, SPOT, IV, DAYS)
    if mp is None or ml is None or pr is None:
        continue
    p = optmath.prob_profit(legs, SPOT, IV, DAYS)
    stated = min(0.95, p + 0.08)          # the agent claims a modest edge
    prev = -1.0
    for n in [0, 1, 4, 5, 8, 12, 20, 40, 100]:
        cal = Calibration(n=n, brier=0.2, reliability=0.02, resolution=0.05,
                          uncertainty=0.24, base_rate=0.6)
        post = competence.assess(resolved=n, reliability=0.02 if n >= 8 else None,
                                 positions=[], equity=100_000.0, high_water=100_000.0)
        f = sizing.size_position(
            equity=100_000.0, stated_confidence=stated, max_profit=mp * 100,
            max_loss=ml * 100, calibration=cal, posture=post, underlying="X",
            payoff_ratio=pr[2]).fraction_of_equity
        if f < prev - 1e-9:
            inversions += 1
            violations.append(f"INV-E: {name} n={n} sized {f:.3%} < previous {prev:.3%}")
        prev = f
print(f"swept {len(zoo())} structures x 9 sample sizes: {inversions} inversion(s)")

# ---------------------------------------------------------------- INV-F
report("INV-F  A stop the agent typically writes must be REACHABLE on the net-cost base")

print(f"{'structure':<28} {'net':>8} {'maxP':>8} {'maxL':>8}  -50%/+50%   -100%/+100%")
print("-" * 92)
for name, legs in zoo().items():
    mp, ml = optmath.max_profit_loss(legs)
    if mp is None or ml is None:
        continue
    net = optmath.entry_cost(legs)
    a = _unreachable_rules(-50.0, 50.0, net_cost=net, max_profit=mp, max_loss=ml)
    b = _unreachable_rules(-100.0, 100.0, net_cost=net, max_profit=mp, max_loss=ml)
    print(f"{name:<28} {net:>8.2f} {mp:>8.2f} {ml:>8.2f}  "
          f"{'OK' if not a else str(len(a))+' unreachable':<11} "
          f"{'OK' if not b else str(len(b))+' unreachable'}")

# ---------------------------------------------------------------- verdict
report("VERDICT")
if violations:
    print(f"{len(violations)} invariant violation(s):\n")
    for v in violations:
        print("  *", v)
else:
    print("all invariants hold")
