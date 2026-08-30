"""Scaffold: a trader's gauntlet - regimes, real edge, skew, paths, streaks.

    uv run python tests/scaffold_trader_gauntlet.py

NOT collected by pytest (filename does not start with `test_`). The structure
zoo (D-079) proved the stack is UNBIASED AT ZERO EDGE at one market point
(spot 100, IV 25%, 7 DTE). This gauntlet asks the questions a desk would ask
next, none of which the zoo touched:

  G1  Does zero-edge coherence survive regime extremes (8%..150% IV, 0.5..365 DTE)?
  G2  When there IS a real edge, does size respond - monotonically,
      proportionately, and at a sane hurdle? (The profitability side.)
  G3  A skewed surface priced fairly at its own per-leg IVs: how much edge
      does the flat-IV evaluation manufacture out of nothing?
  G4  Exit rules driven through price PATHS: whipsaw, gap, conflicting
      triggers, stale quotes, slow bleed, blind marks.
  G5  The ladder under a losing streak: demotion boundaries, luck-blocking,
      and how much a full demotion actually cuts per-position size.
  G6  Degenerate corners: unbounded structures, friction-eaten payoffs and
      the max/max fallback that forgets friction.

Method as in D-079: every structure is priced at its expected intrinsic under
THE SAME lognormal grid the stack prices with, so a fair bet is fair BY
CONSTRUCTION and any edge the stack reports on one is an artefact of the
stack, not of the market.
"""
from __future__ import annotations

from types import SimpleNamespace

from trdrbot import competence, ids, optmath, sizing
from trdrbot.analytics import Snapshot
from trdrbot.calibration import Calibration
from trdrbot.exit_rules import evaluate, invalid_rules, watched_signals
from trdrbot.experiments import (
    DEFAULT_ROUND_TRIP_COST,
    THESIS_RIGHT_EXPRESSION_RIGHT,
    THESIS_WRONG_PROFITED_ANYWAY,
)
from trdrbot.optmath import Leg, _lognormal_grid
from trdrbot.positions import Position

SPOT = 100.0
EQUITY = 100_000.0

violations: list[str] = []
findings: list[str] = []


def check(cond, msg):
    if not cond:
        violations.append(msg)
    return cond


def note(msg):
    findings.append(msg)


def report(title):
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")


def fair_price(right, strike, iv, days, spot=SPOT):
    """Expected intrinsic under the SAME grid the stack prices with."""
    grid = _lognormal_grid(spot, iv, days)
    if right == "C":
        return sum(w * max(0.0, s - strike) for s, w in grid)
    return sum(w * max(0.0, strike - s) for s, w in grid)


def structures(iv, days):
    def L(r, k, side, qty=1):
        return Leg(right=r, strike=k, side=side, qty=qty,
                   price=fair_price(r, k, iv, days))
    return {
        "put credit 95/100": [L("P", 100, "short"), L("P", 95, "long")],
        "call debit 100/105": [L("C", 100, "long"), L("C", 105, "short")],
        "iron condor 90-110": [L("P", 95, "short"), L("P", 90, "long"),
                               L("C", 105, "short"), L("C", 110, "long")],
        "fly 95/100/105": [L("C", 95, "long"), L("C", 100, "short", 2),
                           L("C", 105, "long")],
    }


def gross_premium(legs):
    return sum(l.price * l.qty * 100 for l in legs)


def cal(n, rel=0.02):
    return Calibration(n=n, brier=0.15, reliability=rel, resolution=0.05,
                       uncertainty=0.24, base_rate=0.6)


def posture(n, rel=0.02, attr_good=None, equity=EQUITY, hw=EQUITY):
    good = attr_good if attr_good is not None else n
    positions = ([SimpleNamespace(attribution=THESIS_RIGHT_EXPRESSION_RIGHT)] * good
                 + [SimpleNamespace(attribution=THESIS_WRONG_PROFITED_ANYWAY)] * (n - good))
    return competence.assess(resolved=n, reliability=rel, positions=positions,
                             equity=equity, high_water=hw)


# ================================================================ G1 REGIMES
report("G1  Zero-edge coherence across regimes (IV 8%..150%, DTE 0.5..365)")
print("Fair-priced by construction: EV must be ~0 and conditional Kelly ~0 at EVERY")
print("point, or the stack invents/refuses edge as a function of regime alone.\n")
print(f"{'regime':<16} {'structure':<20} {'EV':>8} {'P(win)':>7} {'Kelly_cond':>10}  note")
print("-" * 96)
for iv in (0.08, 0.25, 0.60, 1.50):
    for days in (0.5, 7, 90, 365):
        for name, legs in structures(iv, days).items():
            ev = optmath.expected_value(legs, SPOT, iv, days)
            p = optmath.prob_profit(legs, SPOT, iv, days)
            mp, ml = optmath.max_profit_loss(legs)
            pr = optmath.payoff_ratio(legs, SPOT, iv, days)
            tag = ""
            if pr is None:
                tag = "conditional refused (thin side) -> max/max fallback"
                k = None
            else:
                k = sizing.kelly_fraction(p, mp, ml, payoff_ratio=pr[2])
                check(abs(k) < 0.02,
                      f"G1: {name} @ IV{iv:.0%}/{days}d Kelly {k:+.3f} on a fair bet")
            check(ev is None or abs(ev) < 0.5,
                  f"G1: {name} @ IV{iv:.0%}/{days}d EV {ev:.2f} not ~0 though fair")
            kk = f"{k:+.3f}" if k is not None else "   n/a"
            print(f"IV{iv:>4.0%} {days:>5g}d  {name:<20} {ev:>8.2f} {p:>7.1%} {kk:>10}  {tag}")

# --- breakeven_vol must recover the priced IV - including ABOVE the grid cap
report("G1b breakeven_vol recovery at every regime, and the range it admits to")
# CHANGED (WU-4.3): `iv_hint` is passed, as `experiments.simulate` now does, so
# the scan follows the quote instead of stopping at a fixed 120%. The IV 150%
# rows used to report "EV positive at every realized vol tested" - a claim about
# the grid that read as a claim about the world (I-44).
for iv, days in ((0.08, 30), (0.60, 30), (1.50, 7)):
    for name in ("put credit 95/100", "iron condor 90-110"):
        legs = structures(iv, days)[name]
        be = optmath.breakeven_vol(legs, SPOT, days, iv_hint=iv)
        if be is None:
            print(f"IV{iv:>4.0%} {days:>3g}d  {name:<20} -> None")
            continue
        got = be.crossings[0] if be.crossings else None
        print(f"IV{iv:>4.0%} {days:>3g}d  {name:<20} -> {be.describe()}")
        check(got is not None and abs(got - iv) < 0.01,
              f"G1b: {name} priced at {iv:.0%} but breakeven found {got}")
# ...and a scan that genuinely finds nothing still says how far it looked.
free = [Leg("C", 105, "long", 1, 0.0), Leg("C", 110, "short", 1, 0.50)]
print(f"{'free money (no crossing)':<32} -> {optmath.breakeven_vol(free, SPOT, 7).describe()}")
check("searched to" in optmath.breakeven_vol(free, SPOT, 7).describe(),
      "G1b: a no-crossing verdict must name the range it searched")

# ================================================================ G2 EDGE RESPONSE
report("G2  Edge-response: a REAL vol edge, honestly stated - when does the stack trade?")
print("Market prices the structure at IV 25%; true vol is lower by `edge`, and the agent")
print("states the honest P(win) under it. MIXED is what production did before WU-4.5:")
print("p from the agent's vol, payoff `b` from the market's - two measures in one Kelly.")
print("ONE MEASURE is `Thesis.vol_view`: both from the vol the thesis declares. Friction")
print("charged either way. SCALE tier, n=20.\n")

post20, cal20 = posture(20), cal(20)
for name in ("iron condor 90-110", "put credit 95/100"):
    legs = structures(0.25, 7)[name]
    mp, ml = optmath.max_profit_loss(legs)
    fr = gross_premium(legs) * DEFAULT_ROUND_TRIP_COST
    print(f"--- {name}: friction ${fr:.0f}/contract, maxP ${mp:.0f}, maxL ${ml:.0f}")
    print(f"{'edge':>6} {'stated':>7} {'EV_true-f':>9} | {'MIXED measure':>21} "
          f"| {'ONE measure (vol_view)':>25}")
    print(f"{'':>6} {'':>7} {'':>9} | {'gate':>5} {'frac':>7} {'Kelly':>7} "
          f"| {'gate':>5} {'frac':>7} {'Kelly':>7}")
    prev_frac, first_trade, ev_cross = -1.0, None, None
    mixed_all_seed, one_earns, refused_from = True, False, None
    for e_bp in range(0, 130, 10):
        e = e_bp / 1000.0
        iv_true = 0.25 - e
        stated = optmath.prob_profit(legs, SPOT, iv_true, 7)
        ev_true = optmath.expected_value(legs, SPOT, iv_true, 7) - fr

        def _size(payoff):
            """Production's path: no usable conditional payoff means REFUSE.

            The max/max fallback is deliberately NOT modelled here - WU-4.2
            removed it from every path the agent can reach, so a scaffold that
            still took it would be measuring dead code.
            """
            if payoff is None:
                return None
            return sizing.size_position(
                equity=EQUITY, stated_confidence=stated, max_profit=mp, max_loss=ml,
                calibration=cal20, posture=post20, underlying="X",
                payoff_ratio=payoff[2])

        def _cells(d):
            if d is None:
                return f"{'refuse':>5} {'-':>7} {'-':>7}"
            return (f"{'open' if d.contracts else 'shut':>5} "
                    f"{d.fraction_of_equity:>7.2%} {(d.kelly_full or 0):>+7.3f}")

        # What production did before WU-4.5: p from the agent's vol, b from the
        # market's. Kept as the measured contrast, not as behaviour.
        mixed = _size(optmath.payoff_ratio(legs, SPOT, 0.25, 7, friction=fr))
        # CHANGED (WU-4.5): the thesis carries `vol_view`, so `simulate` prices
        # the payoff under the SAME vol the stated probability came from.
        one = _size(optmath.payoff_ratio(legs, SPOT, iv_true, 7, friction=fr))

        if one is not None and one.contracts and first_trade is None:
            first_trade = e
        if ev_true > 0 and ev_cross is None:
            ev_cross = e
        # Monotonicity holds only where a conditional payoff EXISTS. Past that
        # the structure has no losing side left to condition on and the stack
        # refuses outright, which is a fall in size and the correct one.
        if one is not None:
            check(one.fraction_of_equity >= prev_frac - 1e-9,
                  f"G2: {name} size fell as real edge grew at edge {e:.1%}")
            prev_frac = one.fraction_of_equity
            if one.contracts and (one.kelly_full or 0) > 0:
                one_earns = True
        elif not refused_from:
            refused_from = e
        if mixed is not None and mixed.contracts and (mixed.kelly_full or 0) > 0:
            mixed_all_seed = False
        print(f"{e:>6.1%} {stated:>7.1%} {ev_true:>9.0f} "
              f"| {_cells(mixed)} | {_cells(one)}")
    check(mixed_all_seed, f"G2: {name} - the MIXED measure was expected to never "
                          f"earn Kelly; if it now does, this contrast is stale")
    check(one_earns, f"G2: {name} - a real vol edge must earn Kelly under one measure")
    if first_trade is not None and ev_cross is not None:
        gap = first_trade - ev_cross
        print(f"    one measure: first trade at {first_trade:.1%} vol edge; "
              f"EV-after-costs positive from {ev_cross:.1%}; gap {gap:+.1%} "
              f"(one grid step = 1.0%)")
        check(abs(gap) <= 0.011,
              f"G2: {name} gate opens {gap:+.1%} from EV>0 - the measures have "
              f"drifted apart again")
    if refused_from is not None:
        print(f"    beyond a {refused_from:.0%} vol edge the losing side thins past "
              f"MIN_CONDITIONAL_MASS and the stack REFUSES to size at all")
        note(f"G2: {name} - past ~{refused_from:.0%} of claimed vol edge the losing "
             f"side of this structure holds under 1% of the agent's own "
             f"distribution, so `payoff_ratio` refuses and (since WU-4.2) sizing "
             f"refuses with it. An extreme vol view SELF-REFUSES rather than "
             f"manufacturing an enormous Kelly out of a corner of the grid - the "
             f"layers cover each other, which is what balance looks like. Worth "
             f"knowing rather than fixing: the agent gets no position from a view "
             f"that says a trade cannot lose, which is the correct reading of "
             f"such a view.")

report("G2b Directional edge (drift knob EXISTS): gate must open exactly at EV>0")
legs = structures(0.25, 7)["call debit 100/105"]
mp, ml = optmath.max_profit_loss(legs)
fr = gross_premium(legs) * DEFAULT_ROUND_TRIP_COST
print(f"--- call debit 100/105: friction ${fr:.0f}, maxP ${mp:.0f}, maxL ${ml:.0f}")
print(f"{'drift':>6} {'stated':>7} {'EV_true-f':>9} {'gate':>5} {'frac':>7} {'ctr':>4}  sign-agree")
prev_frac = -1.0
for d_bp in (0, 5, 10, 15, 20, 30, 40, 60):
    dr = d_bp / 1000.0
    stated = optmath.pop_given_view(legs, SPOT, 0.25, 7, drift=dr)
    ev_true = optmath.expected_value(legs, SPOT, 0.25, 7, drift=dr) - fr
    pr = optmath.payoff_ratio(legs, SPOT, 0.25, 7, drift=dr, friction=fr)
    d = sizing.size_position(
        equity=EQUITY, stated_confidence=stated, max_profit=mp, max_loss=ml,
        calibration=cal20, posture=post20, underlying="X",
        payoff_ratio=pr[2] if pr else None)
    agree = (d.contracts > 0) == (ev_true > 0)
    check(d.fraction_of_equity >= prev_frac - 1e-9,
          f"G2b: size fell as drift edge grew at {dr:+.1%}")
    prev_frac = d.fraction_of_equity
    if abs(ev_true) > 25:  # away from the boundary the signs must agree exactly
        check(agree, f"G2b: at drift {dr:+.1%} gate={'open' if d.contracts else 'shut'} "
                     f"but EV_true-f = {ev_true:+.0f}")
    print(f"{dr:>+6.1%} {stated:>7.1%} {ev_true:>9.0f} "
          f"{'open' if d.contracts else 'shut':>5} {d.fraction_of_equity:>7.2%} "
          f"{d.contracts:>4}  {'yes' if agree else 'NO'}")
note("G2: at the gate boundary size steps 0 -> seed floor (2.2% of equity) in one "
     "tick of stated confidence - the exploration floor applies at EVERY tier, so "
     "near-zero-EV trades are sized 2.2%, not Kelly-small.")

# ================================================================ G3 SKEW
report("G3  A fairly-priced SKEWED surface, evaluated at one flat IV")
print("Each leg priced at its own IV (typical equity put skew). The market has zero")
print("edge by construction under its own quotes. EV/POP/payoff evaluate at flat ATM")
print("25% (per-leg IV is used by greeks ONLY). Any EV shown is manufactured.\n")
SKEW = {90: 0.34, 95: 0.30, 100: 0.25, 105: 0.21, 110: 0.19}
DAYS = 7


def skew_leg(r, k, side, qty=1):
    return Leg(right=r, strike=k, side=side, qty=qty,
               price=fair_price(r, k, SKEW[k], DAYS), iv=SKEW[k])


skewed = {
    "put credit 95/100": [skew_leg("P", 100, "short"), skew_leg("P", 95, "long")],
    "put debit 95/100": [skew_leg("P", 100, "long"), skew_leg("P", 95, "short")],
    "call credit 105/110": [skew_leg("C", 105, "short"), skew_leg("C", 110, "long")],
    "iron condor 90-110": [skew_leg("P", 95, "short"), skew_leg("P", 90, "long"),
                           skew_leg("C", 105, "short"), skew_leg("C", 110, "long")],
    "risk reversal 95/105": [skew_leg("P", 95, "short"), skew_leg("C", 105, "long")],
}
print(f"{'structure':<22} {'EV@flat':>8} {'EV-fric':>8} {'gate opens at':>13}  "
      f"vs fair-under-quotes 0")
for name, legs in skewed.items():
    ev = optmath.expected_value(legs, SPOT, 0.25, DAYS)
    fr = gross_premium(legs) * DEFAULT_ROUND_TRIP_COST
    pr = optmath.payoff_ratio(legs, SPOT, 0.25, DAYS, friction=fr)
    gate_at = 1.0 / (1.0 + pr[2]) if pr else None
    ga = f"{gate_at:.1%}" if gate_at is not None else "refused"
    print(f"{name:<22} {ev:>8.2f} {ev - fr:>8.2f} {ga:>13}")
check(True, "")  # measurements, not invariants: no unique flat-IV truth exists
mag = max(abs(optmath.expected_value(l, SPOT, 0.25, DAYS)) for l in skewed.values())
note(f"G3: evaluating skewed quotes at one flat IV moves EV by up to ${mag:.0f} per "
     f"contract on zero-edge structures - the distribution ignores Leg.iv while "
     f"net_greeks honours it, so risk and edge are computed under DIFFERENT "
     f"surfaces (the two-layers-disagree defect class, D-074/D-076/D-079).")

# ================================================================ G4 EXIT PATHS
report("G4  Exit rules driven through price paths (real evaluate(), real debounce)")
DEADLINE = "2026-12-31"


def mkpos(rules, legs_syms=("XYZ261016P00100000", "XYZ261016P00095000"), **kw):
    # Entry state as D-040 records it, so mark breaches can be checked against
    # the underlying the way production does (WU-4.6).
    kw.setdefault("entry_spot", 100.0)
    kw.setdefault("entry_iv", 0.25)
    kw.setdefault("greeks_at_entry", {"delta_dollars": 4000.0, "vega_dollars": -10.0})
    kw.setdefault("expiry", "2026-10-16")
    return Position(position_id="SIM", status="open", underlying="XYZ",
                    legs=[{"symbol": s} for s in legs_syms],
                    exit_rules=list(rules), **kw)


def snap(pnl_frac, under_px, *, missing_leg=False, basis=(-350.0, 150.0)):
    rows = []
    if not missing_leg and pnl_frac is not None:
        net = abs(sum(basis))
        rows = [
            {"symbol": "XYZ261016P00100000", "cost_basis": basis[0],
             "unrealized_pl": pnl_frac * net},
            {"symbol": "XYZ261016P00095000", "cost_basis": basis[1],
             "unrealized_pl": 0.0},
        ]
    return Snapshot(market_open=True, broker_positions=rows,
                    underlying_prices={"XYZ": under_px})


def run_path(label, pos, ticks, expect_fire_at, expect_kind=None):
    fired_at, kind = None, None
    for i, s in enumerate(ticks, 1):
        reason, why, _ = evaluate(pos, s, DEADLINE)
        if reason:
            fired_at, kind = i, reason
            break
    ok = fired_at == expect_fire_at and (expect_kind is None or kind == expect_kind)
    check(ok, f"G4: {label} fired at tick {fired_at} as {kind}, "
              f"expected tick {expect_fire_at} as {expect_kind}")
    exp = f"tick {expect_fire_at} ({expect_kind})" if expect_fire_at else "never"
    got = f"tick {fired_at} ({kind})" if fired_at else "never"
    print(f"  {label:<52} expected {exp:<22} got {got}")
    return kind


run_path("P1 whipsaw -52/-30/-55 vs -50% stop (2-of-3)",
         mkpos([{"type": "stop_loss", "threshold": "-50%"}]),
         [snap(-0.52, 100), snap(-0.30, 100), snap(-0.55, 100)], 3, "stop_loss")

# CHANGED (WU-4.6): the artifact case now DEBOUNCES. One -100%-of-net print on
# an unmoved underlying is exactly what position_mark's own comment warns a wide
# quote can produce, so it is held for confirmation instead of closing the
# position at the worst quote of the day (I-42).
run_path("P2 ONE wide print -100%, underlying unmoved (the artifact)",
         mkpos([{"type": "stop_loss", "threshold": "-50%"}]),
         [snap(-1.00, 100)], None)
run_path("P2b same print, underlying gapped 96 (the real thing)",
         mkpos([{"type": "stop_loss", "threshold": "-50%"}]),
         [snap(-1.00, 96)], 1, "stop_loss")
run_path("P2c artifact print twice - the debounce still closes it",
         mkpos([{"type": "stop_loss", "threshold": "-50%"}]),
         [snap(-1.00, 100), snap(-1.00, 100)], 2, "stop_loss")

run_path("P3 underlying gap 93.5 + crazy +120% mark, both decisive",
         mkpos([{"type": "underlying_stop", "level": "95", "direction": "below"},
                {"type": "profit_target", "threshold": "+50%"}]),
         [snap(+1.20, 93.5)], 1, "underlying_stop")

run_path("P4 both legs stale (mark blind), underlying 93 breaks 95",
         mkpos([{"type": "stop_loss", "threshold": "-50%"},
                {"type": "underlying_stop", "level": "95", "direction": "below"}]),
         [snap(None, 93.0, missing_leg=True)], 1, "underlying_stop")

run_path("P5 slow bleed: eight ticks at -49% vs -50% stop (far from expiry)",
         mkpos([{"type": "stop_loss", "threshold": "-50%"}]),
         [snap(-0.49, 100)] * 8, None)
# CHANGED (WU-4.7): the same bleed is now BOUNDED - at 1 DTE the implicit
# gamma-wall time stop closes it, so "rides to expiry unchallenged" is no
# longer a path the book has.
import datetime as _dt  # noqa: E402
_soon = (ids.market_today() + _dt.timedelta(days=1)).isoformat()
run_path("P5b same bleed, now 1 day from expiry",
         mkpos([{"type": "stop_loss", "threshold": "-50%"}], expiry=_soon),
         [snap(-0.49, 100)], 1, "time_stop")

blind = mkpos([{"type": "stop_loss", "threshold": "-50%"},
               {"type": "profit_target", "threshold": "+50%"}])
r, _, _ = evaluate(blind, snap(-0.90, 100, basis=(500.0, -495.0)), DEADLINE)
check(r is None, "G4: near-zero-net-cost position unexpectedly fired")
print(f"  P6 net cost $5 on $995 gross: mark signal refused    "
      f"invalid_rules={invalid_rules(blind)} watched={watched_signals(blind)}")
# CHANGED (WU-4.4): the evaluator's behaviour is unchanged and correct - it
# holds, because the mark base is genuinely unobservable here. What changed is
# that the agent is TOLD at record time instead of discovering it at a loss;
# invalid_rules()=0 and watched_signals()=[position_mark] still read healthy,
# which is exactly why the warning had to live in record_position (I-45, pinned
# by test_record_position_warns_when_mark_rules_can_never_print).
print("     (record_position now warns at entry; the evaluator still holds - "
      "both correct)")

# ================================================================ G5 LADDER
report("G5  The ladder under a losing streak")
for eq, want in ((95_100.0, "scale"), (95_000.0, "establish"), (89_990.0, "explore")):
    p = posture(20, equity=eq, hw=EQUITY)
    ok = check(p.tier == want,
               f"G5: dd {(1 - eq / EQUITY):.1%} gave tier {p.tier}, expected {want}")
    print(f"  drawdown {(1 - eq / EQUITY):>5.1%}: {p.tier.upper():<10} "
          f"{'ok' if ok else 'WRONG'}  ({p.reason})")
# At equity exactly 90,000/100,000, `1 - equity/hw` is 0.09999999999999998 and the
# >= 0.10 full demotion does NOT fire. Knife-edge float trivia, recorded not flagged.

p_luck = posture(20, attr_good=10)
check(p_luck.tier == "establish",
      f"G5: 50% lucky book reached {p_luck.tier}, luck must block SCALE")
print(f"  20 resolved but half lucky-profits: {p_luck.tier.upper()} "
      f"(attr {p_luck.attributable_rate:.0%} < 60% blocks SCALE) ok")

legs = structures(0.25, 7)["put credit 95/100"]
mp, ml = optmath.max_profit_loss(legs)
fr = gross_premium(legs) * DEFAULT_ROUND_TRIP_COST
pr = optmath.payoff_ratio(legs, SPOT, 0.25, 7, friction=fr)
sizes = {}
for label, post_, cal_ in (
        ("MATURE n=60", posture(60, attr_good=48), cal(60)),
        ("after 10% dd -> EXPLORE", posture(60, attr_good=48, equity=89_990.0), cal(60)),
):
    d = sizing.size_position(equity=89_990.0 if "dd" in label else EQUITY,
                             stated_confidence=0.78, max_profit=mp, max_loss=ml,
                             calibration=cal_, posture=post_, underlying="X",
                             payoff_ratio=pr[2] if pr else None)
    sizes[label] = d
    print(f"  {label:<26} tier={post_.tier.upper():<10} frac={d.fraction_of_equity:.2%} "
          f"contracts={d.contracts} bookcap={post_.book_cap:.0%}")
a = sizes["MATURE n=60"].fraction_of_equity
b = sizes["after 10% dd -> EXPLORE"].fraction_of_equity
if a > 0:
    note(f"G5: a 10% drawdown demotes MATURE->EXPLORE yet cuts per-position size only "
         f"{a:.2%} -> {b:.2%} ({1 - b / a:.0%} cut): the seed floor (2.2%) applies at "
         f"every tier, so demotion mostly acts through the book cap "
         f"(25% -> 10%), not through the next trade's size.")

d = sizing.size_position(equity=EQUITY, stated_confidence=0.78, max_profit=mp,
                         max_loss=ml, calibration=cal(20), posture=posture(20),
                         underlying="X", open_risk_usd=19_900.0,
                         payoff_ratio=pr[2] if pr else None)
check(d.contracts == 0 and "portfolio" in d.reason,
      f"G5: portfolio cap failed to refuse: {d.reason[:90]}")
print(f"  portfolio cap: $19,900 at risk vs 20% SCALE cap -> {d.reason[:74]}")
d = sizing.size_position(equity=EQUITY, stated_confidence=0.78, max_profit=mp,
                         max_loss=ml, calibration=cal(20), posture=posture(20),
                         underlying="X", open_risk_by_underlying={"X": 7_900.0},
                         payoff_ratio=pr[2] if pr else None)
check(d.contracts == 0 and "concentration" in d.reason,
      f"G5: concentration cap failed to refuse: {d.reason[:90]}")
print(f"  concentration:  $7,900 on X vs 8% cap        -> {d.reason[:74]}")

# ================================================================ G6 CORNERS
report("G6  Degenerate corners")
strangle = [Leg("P", 95, "short", 1, fair_price("P", 95, 0.25, 7)),
            Leg("C", 105, "short", 1, fair_price("C", 105, 0.25, 7))]
d = sizing.size_position(equity=EQUITY, stated_confidence=0.80, max_profit=None,
                         max_loss=None, calibration=cal20, posture=post20, underlying="X")
check(d.contracts == 0 and "REFUSED" in d.reason, "G6: short strangle not refused")
print(f"  short strangle (unbounded loss)  -> {d.reason[:70]}")

# CHANGED (WU-4.1): a long call is now SIZED on its conditional payoff. The
# refusal is for unbounded LOSS only - unbounded profit has a finite E[win|win].
long_call = [Leg("C", 100, "long", 1, fair_price("C", 100, 0.25, 7))]
mp, ml = optmath.max_profit_loss(long_call)
pr_lc = optmath.payoff_ratio(long_call, SPOT, 0.25, 7)
d = sizing.size_position(equity=EQUITY, stated_confidence=0.80, max_profit=mp,
                         max_loss=ml, calibration=cal20, posture=post20, underlying="X",
                         payoff_ratio=pr_lc[2] if pr_lc else None)
check(d.contracts >= 1, "G6: long call refused despite a finite conditional payoff")
print(f"  long ATM call: maxP={mp}, conditional payoff {pr_lc[2]:.2f} "
      f"-> {d.contracts} contract(s) {d.fraction_of_equity:.2%}")
no_b = sizing.size_position(equity=EQUITY, stated_confidence=0.80, max_profit=mp,
                            max_loss=ml, calibration=cal20, posture=post20,
                            underlying="X", payoff_ratio=None)
check(no_b.contracts == 0 and "conditional payoff" in no_b.reason,
      "G6: unbounded profit with NO ratio must refuse, naming the missing ratio")
print(f"  ...same call with no simulated ratio    -> {no_b.reason[:60]}")

narrow = [Leg("P", 100, "short", 1, fair_price("P", 100, 0.25, 7)),
          Leg("P", 99, "long", 1, fair_price("P", 99, 0.25, 7)),
          Leg("C", 101, "short", 1, fair_price("C", 101, 0.25, 7)),
          Leg("C", 102, "long", 1, fair_price("C", 102, 0.25, 7))]
mp, ml = optmath.max_profit_loss(narrow)
fr = gross_premium(narrow) * DEFAULT_ROUND_TRIP_COST
pr_n = optmath.payoff_ratio(narrow, SPOT, 0.25, 7, friction=fr)
b_cond = pr_n[2] if pr_n else None
b_mm = mp / abs(ml)
with_pr = sizing.size_position(equity=EQUITY, stated_confidence=0.70, max_profit=mp,
                               max_loss=ml, calibration=cal20, posture=post20,
                               underlying="X", payoff_ratio=b_cond)
no_pr = sizing.size_position(equity=EQUITY, stated_confidence=0.70, max_profit=mp,
                             max_loss=ml, calibration=cal20, posture=post20,
                             underlying="X", payoff_ratio=None)  # fallback path
gate_cond = 1.0 / (1.0 + b_cond) if b_cond else None
print(f"  narrow condor 99/100-101/102, friction ${fr:.0f} vs maxP ${mp:.0f}:")
print(f"    conditional b after friction {b_cond:.2f} (gate needs {gate_cond:.0%}) "
      f"vs max/max fallback b {b_mm:.2f} (gate needs {1 / (1 + b_mm):.0%})")
print(f"    stated 70% WITH ratio -> {with_pr.contracts} contracts; "
      f"WITHOUT (fallback) -> {no_pr.contracts} contracts "
      f"({no_pr.fraction_of_equity:.2%} of equity)")
check(with_pr.contracts == 0, "G6: friction-aware path should refuse 70% on b=0.26")

# CHANGED (WU-4.2): the frictionless max/max fallback above is still reachable
# from a DIRECT caller (and still measured, as the contrast), but production
# can no longer reach it - the tool refuses at every seam that would have
# produced payoff_ratio=None. Driven through the real tool, not the function.
from trdrbot.calibration import CalibrationStore  # noqa: E402
from trdrbot.local_tools import (  # noqa: E402
    SharedContext, build_simulate_experiments, build_size_position,
)

_shared = SharedContext()
_sim = build_simulate_experiments(_shared, None, None)
_sim.func(thesis_claim="pinned", underlying="X", horizon="2099-01-05", drift_pct=0.0,
          spot=SPOT, iv_pct=25.0, days_to_expiry=7, band_low=99.0, band_high=101.0,
          candidates=[
              {"name": "narrow condor", "legs": [
                  {"right": r, "strike": k, "side": s, "qty": 1,
                   "price": round(fair_price(r, k, 0.25, 7), 4)}
                  for r, k, s in (("P", 100, "short"), ("P", 99, "long"),
                                  ("C", 101, "short"), ("C", 102, "long"))]},
              {"name": "wide condor", "legs": [
                  {"right": r, "strike": k, "side": s, "qty": 1,
                   "price": round(fair_price(r, k, 0.25, 7), 4)}
                  for r, k, s in (("P", 95, "short"), ("P", 90, "long"),
                                  ("C", 105, "short"), ("C", 110, "long"))]},
          ])
import tempfile as _tf  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

with _tf.TemporaryDirectory() as _d:
    _cal = CalibrationStore(_Path(_d) / "cal.jsonl")
    _size = build_size_position(_cal, EQUITY, shared=_shared)
    unnamed = _size.func(stated_confidence=0.70, max_profit=999.0, max_loss=-1000.0,
                         underlying="X")
    never_simmed = build_size_position(
        _cal, EQUITY, shared=SharedContext()
    ).func(stated_confidence=0.70, max_profit=999.0, max_loss=-1000.0, underlying="X")
check("REFUSED" in unnamed, "G6: tool guessed an unmatched structure instead of refusing")
check("REFUSED" in never_simmed, "G6: tool sized without any simulation")
print(f"    via the TOOL: unmatched -> {unnamed.split('.')[0][:56]}")
print(f"                  no sim    -> {never_simmed.split('.')[0][:56]}")

g = optmath.bs_greeks("C", 100, SPOT, 0.25, 0)
check(g is None, "G6: greeks at 0 DTE should refuse")
ev0 = optmath.expected_value(structures(0.25, 7)["call debit 100/105"], SPOT, 0.25, 0)
print(f"  0 DTE: greeks -> {g}, EV degrades to intrinsic-cost ({ev0:+.2f}) - ok")

# ================================================================ VERDICT
report("VERDICT")
if violations:
    print(f"{len(violations)} invariant violation(s):")
    for v in violations:
        if v:
            print("  *", v)
else:
    print("all hard invariants hold")
print(f"\n{len(findings)} measured finding(s) for the critique:")
for i, f in enumerate(findings, 1):
    print(f"  F{i}. {f}\n")
