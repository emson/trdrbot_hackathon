"""Scaffold: harmony - do the layers AGREE with each other?

    uv run python tests/scaffold_harmony.py

NOT collected by pytest (filename does not start with `test_`). The structure
zoo (D-079) proved each piece is individually unbiased; the trader gauntlet
proved each piece survives regimes, paths and streaks. Both ask "is this layer
right?". This one asks the question a desk asks after both come back clean:

    every layer is locally correct - do they COMPOSE into a coherent position?

Disharmony is not a bug in any one layer. It is two correct layers whose
correct behaviours cancel, or a rule that satisfies a check without doing the
job the check exists to confirm. It does not show up in a unit test, because
every unit passes.

  H1  A thesis stop outside the structure's own payoff range. Does the level
      the agent chose fire while there is still capital left to protect, or
      only after max loss is already locked?
  H2  A stop inside the position's own noise. How far must the underlying
      travel to trigger the stop, against how far it travels on an ordinary
      day?
  H3  Thesis horizon vs expiry. Does the position live long enough to test the
      view, and not so long that it pays theta for time the view never uses?
  H4  The size cliff. Confidence is continuous; is size?
  H5  Corroboration vs the clock. Does the anti-artifact rule stay reachable
      by a real gap as a position ages?

Method: the REAL functions throughout - `optmath.pnl_at`, `net_greeks`,
`sizing.size_position`, `exit_rules._mark_corroborated` - driven with the shape
of the position actually on the book, so a finding here is a finding about the
system as configured, not about a model of it.
"""
from __future__ import annotations

from types import SimpleNamespace

from trdrbot import competence, exit_rules, optmath, sizing
from trdrbot.analytics import Snapshot
from trdrbot.calibration import Calibration
from trdrbot.experiments import THESIS_RIGHT_EXPRESSION_RIGHT
from trdrbot.optmath import Leg

EQUITY = 101_360.68  # the real book's high-water mark

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


def cal(n, rel=0.02):
    return Calibration(n=n, brier=0.15, reliability=rel, resolution=0.05,
                       uncertainty=0.24, base_rate=0.6)


def posture(n, rel=0.02, equity=EQUITY, hw=EQUITY):
    positions = [SimpleNamespace(attribution=THESIS_RIGHT_EXPRESSION_RIGHT)] * n
    return competence.assess(resolved=n, reliability=rel, positions=positions,
                             equity=equity, high_water=hw)


# The position actually on the book, at the prices it was opened at:
# 13x SPY 766/758 bear put spread, net debit $2,171 (=$1.67/share).
LIVE = [Leg(right="P", strike=766, side="long", qty=13, price=3.30),
        Leg(right="P", strike=758, side="short", qty=13, price=1.63)]
LIVE_SPOT, LIVE_IV, LIVE_DTE = 769.05, 0.10, 6


# ================================================== H1  STOPS OUTSIDE THE PAYOFF
report("H1  A thesis stop outside the structure's own payoff range")
print("`health` WARNs when a position has no underlying_stop: 'a break in the")
print("underlying closes nothing'. A stop set beyond where max loss is already")
print("locked SILENCES that warning without doing the job it exists to check.\n")
print("For each structure: the spot where the stop fires, and how much of max")
print("loss the payoff has ALREADY taken by the time it does.\n")
print(f"{'structure':<34} {'stop':>7} {'fires at':>9} {'loss locked':>12}  verdict")
print("-" * 96)


def loss_locked_at(legs, level):
    """Fraction of max loss already realised at expiry at `level`."""
    _, ml = optmath.max_profit_loss(legs)
    if ml is None or ml == 0:
        return None
    return min(1.0, max(0.0, optmath.pnl_at(legs, level) / ml))


CASES = [
    # (name, legs, stop direction, stop level, the trader's intent)
    ("LIVE 766/758 put debit", LIVE, "above", 776.0, "bearish; stop if SPY rallies"),
    ("LIVE 766/758 put debit", LIVE, "above", 770.0, "same, tightened to just OTM"),
    ("LIVE 766/758 put debit", LIVE, "above", 764.0, "same, inside the spread"),
    ("call debit 100/105",
     [Leg(right="C", strike=100, side="long", qty=1, price=2.6),
      Leg(right="C", strike=105, side="short", qty=1, price=0.9)],
     "below", 94.0, "bullish; stop if it breaks down"),
    ("put credit 95/100",
     [Leg(right="P", strike=100, side="short", qty=1, price=2.6),
      Leg(right="P", strike=95, side="long", qty=1, price=0.9)],
     "below", 92.0, "bullish credit; stop below the short strike"),
]

decorative = []
for name, legs, direction, level, intent in CASES:
    frac = loss_locked_at(legs, level)
    if frac is None:
        continue
    verdict = ("DECORATIVE - nothing left to protect" if frac >= 0.99 else
               "late - most of the loss is already taken" if frac >= 0.75 else
               "protective")
    print(f"{name:<34} {direction[0]}{level:>6.0f} {level:>9.0f} {frac:>11.0%}  {verdict}")
    if frac >= 0.99:
        decorative.append(f"{name} {direction} {level:g}")

print(f"\n{len(decorative)} of {len(CASES)} stops here are decorative, including the LIVE")
print("position's (above 776, against a long strike of 766).")

# CLOSED by _late_underlying_stops - so this scaffold now guards the fix that
# it found, rather than re-reporting a finding every run.
from trdrbot.local_tools import _late_underlying_stops  # noqa: E402

live_legs = [{"symbol": "SPY260903P00766000", "side": "buy", "qty": 13},
             {"symbol": "SPY260903P00758000", "side": "sell", "qty": 13}]
warned = _late_underlying_stops(live_legs, None, 776.0)
protective = _late_underlying_stops(live_legs, None, 762.0)
check(warned, "H1: the live position's decorative stop is no longer named at record time")
check(not protective, "H1: a PROTECTIVE stop inside the strikes is being warned about")
print(f"\nrecord_position on the live shape, stop above 776 -> "
      f"{'WARNS' if warned else 'silent'}")
print(f"record_position on the live shape, stop above 762 -> "
      f"{'WARNS' if protective else 'silent'} (inside the strikes: real protection)")

print("\nThe shape of it: a vertical's payoff is FLAT beyond its far strike, so any")
print("stop placed past that strike is outside the range where price still moves")
print("P&L. The live position's stop sits 10 points beyond the long strike.")


# ================================================== H2  STOPS INSIDE THE NOISE
report("H2  A stop inside the position's own noise")
print("A mark stop is quoted as a percent of net debit. Translated through the")
print("position's own delta, how far must the underlying move to trigger it -")
print("and how does that compare with an ordinary day's move?\n")
print(f"{'stop':>6} {'$ move'.rjust(9)} {'spot move':>10} {'vs 1-day':>9} "
      f"{'vs life':>8}  verdict")
print("-" * 96)

g = optmath.net_greeks(LIVE, LIVE_SPOT, LIVE_IV, LIVE_DTE)
net_cost = abs(optmath.entry_cost(LIVE))
# `delta_shares`, NOT `delta_dollars`. The latter is delta_shares x spot - a
# NOTIONAL, not a rate - and dividing a loss by it answers a question nobody
# asked. This scaffold got that wrong on its first run and reported every stop
# as 0.00x a daily move; it is the same percent-vs-fraction, dollars-vs-shares
# unit collision D-092 and I-45 are about, which is worth saying out loud in
# the one file whose job is to catch layers disagreeing about units.
delta_per_point = abs(g["delta_shares"])
em_1d = optmath.expected_move(LIVE_SPOT, LIVE_IV, 1.0)
em_life = optmath.expected_move(LIVE_SPOT, LIVE_IV, LIVE_DTE)

for stop_pct in (-0.25, -0.50, -0.65, -1.00):
    loss_dollars = abs(stop_pct) * net_cost
    spot_move = loss_dollars / delta_per_point if delta_per_point else float("inf")
    ratio = spot_move / em_1d if em_1d else float("inf")
    life_ratio = spot_move / em_life if em_life else float("inf")
    verdict = ("INSIDE one day's noise" if ratio < 1.0 else
               "about one day's move" if ratio < 1.5 else
               "outside the daily noise")
    print(f"{stop_pct:>5.0%} {loss_dollars:>9,.0f} {spot_move:>10.2f} {ratio:>8.2f}x "
          f"{life_ratio:>7.2f}x  {verdict}")
    if abs(stop_pct - 0.65) < 1e-9 or stop_pct == -0.65:
        live_stop = (spot_move, ratio, life_ratio)

note(f"H2: the LIVE -65% mark stop triggers on a {live_stop[0]:.2f}-point move - "
     f"{live_stop[1]:.2f}x a single day's expected move, and only {live_stop[2]:.0%} of "
     f"the move expected over the position's whole life. A stop inside the position's "
     f"own lifetime volatility is a coin flip on path rather than a test of the thesis: "
     f"the view can be entirely right and still be stopped out on the way to being "
     f"proved right. Every tighter stop the agent might write is worse - at -25% it is "
     f"0.42x a SINGLE day.")

print(f"\nposition: net cost ${net_cost:,.0f}, delta {delta_per_point:,.0f} shares "
      f"(${delta_per_point:,.0f}/point), 1-day EM {em_1d:.2f}, "
      f"{LIVE_DTE}-day EM {em_life:.2f}")
print("The live stop is -65%. Read the row: that is the honest reason the")
print("corroboration rule (I-42) has to exist at all.")


# ================================================== H3  HORIZON vs EXPIRY
report("H3  Thesis horizon vs expiry - does the position outlive its own view?")
print("A view that resolves AFTER expiry cannot be tested by the trade that")
print("expresses it. A view that resolves long before expiry pays theta for")
print("time it never uses. Harmony is the two landing together.\n")
print(f"{'horizon':>8} {'expiry':>7} {'gap':>5}  reading")
print("-" * 96)

for horizon_d, expiry_d in ((6, 6), (10, 6), (3, 6), (2, 30)):
    gap = expiry_d - horizon_d
    if gap < 0:
        reading = "VIEW OUTLIVES THE TRADE - it expires before the claim resolves"
    elif gap == 0:
        reading = "aligned - the trade is alive exactly as long as the view"
    elif gap <= 0.5 * expiry_d:
        reading = "trade outlives the view - some theta bought and unused"
    else:
        reading = f"trade outlives the view by {gap}d of {expiry_d}d - mostly unused theta"
    print(f"{horizon_d:>7}d {expiry_d:>6}d {gap:>+5}  {reading}")

print("\nThe live position: horizon 2026-09-03, expiry 2026-09-03 - aligned.")

# CLOSED by _horizon_outlives_expiry - guarded here rather than re-reported.
from trdrbot.local_tools import _horizon_outlives_expiry  # noqa: E402

check(_horizon_outlives_expiry("2026-09-10", "2026-09-03"),
      "H3: a horizon after expiry is not named at record time")
check(_horizon_outlives_expiry("2026-09-03", "2026-09-03") is None,
      "H3: an ALIGNED horizon is being warned about")
print("record_position, horizon 2026-09-10 vs expiry 2026-09-03 -> WARNS")
print("record_position, horizon 2026-09-03 vs expiry 2026-09-03 -> silent")
print("\nThe asymmetry worth keeping in view: the OTHER direction (a trade that")
print("long outlives its view) is unpoliced and arguably should stay that way -")
print("buying more expiry than the claim needs is a deliberate, priced choice.")


# ================================================== H4  THE SIZE CLIFF
report("H4  The size cliff - confidence is continuous, is size?")
print("Sweeping stated confidence at a fixed payoff, through the real sizer.\n")
print("Payoff 4.99:1, so the gate's own break-even is p = 1/(1+b) = 16.7% - the")
print("sweep has to start below that to find the boundary at all.\n")
print(f"{'stated':>7} {'gate':>7} {'contracts':>10} {'% equity':>9} {'$ risk':>9}  note")
print("-" * 96)

prev_frac = 0.0
for conf in (0.10, 0.15, 0.17, 0.20, 0.30, 0.50, 0.65, 0.80):
    d = sizing.size_position(
        equity=EQUITY, stated_confidence=conf, max_profit=833.0, max_loss=-167.0,
        calibration=cal(0), posture=posture(0), underlying="SPY", payoff_ratio=4.99)
    frac = d.fraction_of_equity
    jump = ""
    if prev_frac == 0.0 and frac > 0.0:
        jump = f"<- CLIFF: 0 -> {frac:.1%} of equity in one step"
    print(f"{conf:>6.0%} {'open' if d.contracts else 'shut':>7} {d.contracts:>10} "
          f"{frac:>8.2%} {frac * EQUITY:>9,.0f}  {jump}")
    if jump:
        note(f"H4: size steps 0 -> {frac:.1%} of equity ({frac * EQUITY:,.0f}) at the "
             f"gate boundary. There is no small position: the system either declines "
             f"or takes a full exploration allocation.")
    prev_frac = frac

print("\nThis is the seed floor doing exactly what it was built to do (a bounded")
print("cost paid for information) - and the consequence a desk would name is that")
print("a 58%-confidence trade and an 80%-confidence trade are the SAME SIZE.")
print("Conviction is not expressed in size until the ladder reaches SCALE.")


# ================================================== H5  CORROBORATION vs CLOCK
report("H5  Corroboration vs the clock - how much adverse move does it actually demand?")
print("`_mark_corroborated` exists so ONE wide or stale quote printing -100% cannot")
print("close a healthy spread on a single tick (I-42). It demands the underlying have")
print("moved 25% of its own expected move since entry. The question is not whether a")
print("real gap clears that bar - it obviously does - but how SMALL the bar is, since")
print("anything above it re-arms the single-print close the rule was added to stop.\n")
print(f"{'held':>5} {'needed':>8} {'as % of spot':>13} {'as % of 1-day EM':>18}  reading")
print("-" * 96)

for held_days in (1, 2, 3, 5, 10, 20):
    em = optmath.expected_move(LIVE_SPOT, LIVE_IV, held_days)
    needed = exit_rules.CORROBORATION_FRACTION * em
    pct_spot = needed / LIVE_SPOT
    pct_em1 = needed / em_1d if em_1d else float("inf")
    reading = ("ordinary drift clears it - the guard is nearly open"
               if pct_em1 < 0.5 else "needs a real move")
    print(f"{held_days:>4}d {needed:>8.2f} {pct_spot:>12.2%} {pct_em1:>17.0%}  {reading}")
    if held_days == 1:
        day1 = (needed, pct_spot, pct_em1)

note(f"H5: one day after entry the corroboration bar is {day1[0]:.2f} points "
     f"({day1[1]:.2%} of spot, {day1[2]:.0%} of ONE day's expected move). A position "
     f"that has merely drifted that far - noise, not damage - is enough to re-arm the "
     f"single-print decisive close that I-42 added this rule to prevent. The bar is a "
     f"fraction of a fraction, and it is weakest on exactly the low-IV names where a "
     f"wide option quote is most misleading. It reaches one full day's move only after "
     f"~20 days held, by which point most of this book's positions have expired.")

print("\nThe bar is a fraction of a fraction: 25% of the expected move over days HELD,")
print("which on a 10%-IV name at 1 day is 0.13% of spot. The rule correctly refuses")
print("to confirm a loss claim on an unmoved underlying - and confirms one on an")
print("underlying that has barely moved at all.")


# ================================================== VERDICT
report("VERDICT")
if violations:
    print(f"{len(violations)} hard invariant violation(s):")
    for v in violations:
        print(f"  X {v}")
else:
    print("all hard invariants hold")

if findings:
    print(f"\n{len(findings)} harmony finding(s) - layers that are individually")
    print("correct and jointly incoherent:\n")
    for i, f in enumerate(findings, 1):
        print(f"  F{i}. {f}\n")
