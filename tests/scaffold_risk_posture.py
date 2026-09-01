"""Scaffold: risk posture - is this book UNDER-betting, and where does it happen?

    uv run python tests/scaffold_risk_posture.py

NOT collected by pytest (filename does not start with `test_`). The structure
zoo asks "is each piece unbiased?". The trader gauntlet asks "does each piece
survive regimes and streaks?". The harmony scaffold asks "do the pieces
COMPOSE?". All three ask about correctness.

This one asks the question a risk officer asks after all three come back
clean, and it is the only one of the four with a DIRECTION:

    every gate here is individually defensible - is their PRODUCT a posture
    anyone chose?

Caution has a property aggression does not: it is locally free. Every haircut
looks prudent on its own and none of them has a counterparty arguing the other
side, so a stack of them drifts one way only. The constitution already names
this (principle 4, `assumptions`, traced to D-076: "four defensible haircuts
... together made a whole regime untradeable: 18 theses simulated, 0 traded").
This scaffold measures whether that verdict still holds, and prices it.

  R1  Utilisation. Of the risk the ladder PERMITS, how much is deployed?
  R2  The attribution deadlock. Is the next rung reachable at all?
  R3  Dynamic range. Does conviction move size, or is size a constant?
  R4  The delta illusion. Does the book's headline risk number exceed the
      most the book can actually lose?
  R5  The haircut chain. Every multiplier between a stated edge and a
      contract count, multiplied out.
  R6  The price of it. Kelly log-growth actually captured vs. targeted -
      split into the part sizing costs and the part frequency costs.

Method: the REAL functions - `sizing.size_position`, `competence.assess`,
`optmath.payoff_ratio`, `optmath.net_greeks`, `optmath.pnl_at` - and the REAL
journal, so a finding here is about the system as it ran, not a model of it.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from trdrbot import competence, market_stats, optmath, sizing
from trdrbot.calibration import Calibration
from trdrbot.experiments import THESIS_RIGHT_EXPRESSION_RIGHT
from trdrbot.optmath import Leg

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

findings: list[str] = []


def note(msg: str) -> None:
    findings.append(msg)


def report(title: str) -> None:
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")


# ---------------------------------------------------------------- the real book
#
# Taken from the last `competence` and `book_risk` rows in the live journal and
# the position page on disk, so every number below is the one the system was
# actually reasoning with.
EQUITY = 101_678.06
HIGH_WATER = 102_432.06
RESOLVED = 29
RELIABILITY = 0.021926
LIVE_MAX_LOSS = 2_171.0
LIVE_BOOK_DELTA_PCT = -3.48  # pct_equity_per_1pct_spy, last book_risk row

# 13x SPY 766/758 bear put spread, at the prices it was opened at.
LIVE = [Leg(right="P", strike=766, side="long", qty=13, price=3.30),
        Leg(right="P", strike=758, side="short", qty=13, price=1.63)]
ENTRY_SPOT, ENTRY_IV, ENTRY_DTE = 769.05, 0.10, 6
NOW_SPOT, NOW_DTE = 765.90, 3


def cal(n: int = RESOLVED, rel: float = RELIABILITY) -> Calibration:
    return Calibration(n=n, brier=0.15, reliability=rel, resolution=0.05,
                       uncertainty=0.24, base_rate=0.6)


def posture_at(tier_positions: int, *, attributed: bool, n: int = RESOLVED,
               rel: float | None = RELIABILITY, equity: float = EQUITY,
               hw: float = HIGH_WATER) -> competence.Competence:
    """The ladder's verdict. `attributed` is the whole question in R2: the same
    record with verdicts on its positions and without."""
    attr = THESIS_RIGHT_EXPRESSION_RIGHT if attributed else ""
    positions = [SimpleNamespace(attribution=attr)] * tier_positions
    return competence.assess(resolved=n, reliability=rel, positions=positions,
                             equity=equity, high_water=hw)


def journal_rows() -> list[dict]:
    out = []
    for line in (DATA / "journal.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ================================================================ R1 UTILISATION
report("R1  Utilisation - of the risk the ladder PERMITS, how much is deployed?")
print("Every cap below is measured the same way the sizer measures it: dollars")
print("of DEFINED max loss against equity (D-037). The book is one position.\n")

live_posture = posture_at(3, attributed=False)
CAPS = [
    ("per-position ceiling (tier)", live_posture.position_cap),
    ("per-underlying (SPY, tier)", live_posture.underlying_cap),
    (f"book cap ({live_posture.tier.upper()})", live_posture.book_cap),
    ("book cap (MATURE, the top rung)", competence.TIERS[competence.MATURE]["cap"]),
]
print(f"{'cap':<36} {'permitted $':>12} {'deployed $':>11} {'used':>7}  headroom")
print("-" * 96)
for label, pct in CAPS:
    permitted = pct * EQUITY
    used = LIVE_MAX_LOSS / permitted
    print(f"{label:<36} {permitted:>12,.0f} {LIVE_MAX_LOSS:>11,.0f} {used:>6.0%}  "
          f"${permitted - LIVE_MAX_LOSS:,.0f} unused")

book_used = LIVE_MAX_LOSS / (live_posture.book_cap * EQUITY)
note(f"R1: the book carries ${LIVE_MAX_LOSS:,.0f} of defined risk against a "
     f"${live_posture.book_cap * EQUITY:,.0f} {live_posture.tier.upper()} cap - "
     f"{book_used:.0%} utilisation. 100% cash at 0% expected return is a position "
     f"too, and it is {1 - book_used:.0%} of the risk budget.")

print()
rows = journal_rows()
cycles = [r for r in rows if r.get("kind") in ("execution", "no_op")]
used_tool = Counter()
for r in cycles:
    for t in set(r.get("tool_calls") or []):
        used_tool[t] += 1
ledger = [json.loads(x) for x in
          (DATA / "state" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
theses = [r for r in ledger if r.get("kind") == "thesis"]
traded = [r for r in theses if r.get("traded")]

print("The decide funnel, from the live journal:\n")
FUNNEL = [
    ("decide cycles that reached a verdict", len(cycles)),
    ("... that simulated a structure", used_tool["simulate_experiments"]),
    ("... that ASKED THE SIZER", used_tool["size_position"]),
    ("... that placed an order", used_tool["place_option_order"]),
    ("... that recorded a position", used_tool["record_position"]),
]
base = FUNNEL[0][1]
for label, n in FUNNEL:
    bar = "#" * max(1, round(60 * n / base)) if n else ""
    print(f"{label:<40} {n:>4}  {n / base:>5.1%}  {bar}")
print(f"\npre-registered theses {len(theses)}, traded {len(traded)} "
      f"({len(traded) / max(1, len(theses)):.0%})")

sized_share = used_tool["size_position"] / base
note(f"R2': the sizer - Kelly, the shrink, the tier ceiling, all three book caps - "
     f"was consulted in {used_tool['size_position']} of {base} decide cycles "
     f"({sized_share:.1%}). The quantitative risk machinery is not what is "
     f"declining these trades. It is almost never asked.")

# ==================================================== R2 THE ATTRIBUTION DEADLOCK
report("R2  The attribution deadlock - is the next rung reachable at all?")
print("`_earned_tier` requires BOTH a resolved count and an attributable rate,")
print("and they are measured on different populations at different clocks:")
print("`resolved` counts FORECASTS (29 in six days), `min_attr` counts POSITION")
print("verdicts (3 positions, 0 verdicts, none reachable before their horizons).")
print()
print("WAS: `attributable_rate` returned 0.0 with no verdicts at all - the same")
print("score a book of pure luck earns - so the ladder read a young pipeline as")
print("a damning measurement and pinned itself to ESTABLISH for the whole run.")
print("NOW (WU-8.2): unknown is None and holds its peace below MATURE, the same")
print("rule D-050 already applied to reliability at SCALE.\n")

no_verdicts = competence.attributable_rate([SimpleNamespace(attribution="")] * 3)
all_luck = competence.attributable_rate(
    [SimpleNamespace(attribution="thesis_wrong_profited_anyway")] * 3)


def _rate(r):
    return "unmeasured" if r[0] is None else f"{r[0]:.0%}"


print(f"  3 positions, none resolved yet   -> {_rate(no_verdicts):>10} (n={no_verdicts[1]})")
print(f"  3 positions, all of them LUCK    -> {_rate(all_luck):>10} (n={all_luck[1]})")
print("  ^ FIXED (WU-8.2): distinguishable. Unknown holds its peace below MATURE;")
print("    a measured 0% still blocks, and at MATURE silence blocks too.\n")

print(f"{'record':<44} {'tier':>10} {'book cap':>9} {'kelly x':>8}")
print("-" * 96)
SCENARIOS = [
    ("live: 29 resolved, 0 position verdicts", posture_at(3, attributed=False)),
    ("same record, 3 verdicts, all explicable", posture_at(3, attributed=True)),
    ("same record, 1 verdict, explicable", posture_at(1, attributed=True)),
]
for label, p in SCENARIOS:
    print(f"{label:<44} {p.tier.upper():>10} {p.book_cap:>8.0%} {p.kelly_multiplier:>8.3f}")

live_t, unlocked_t = SCENARIOS[0][1], SCENARIOS[2][1]
if live_t.tier == unlocked_t.tier:
    print("\nAll three rows now agree, which is the point: whether a verdict has")
    print("ARRIVED no longer changes the tier while the sample is too small to")
    print("discriminate. What changes it is what the verdicts SAY, once there are")
    print("enough of them to say anything.")
else:
    note(f"R2: the ladder is still held at {live_t.tier.upper()} by a criterion "
         f"measured on a population of THREE while its partner is measured on "
         f"{RESOLVED}.")

print(f"\nreliability is {RELIABILITY:.4f} - inside MATURE's {competence.TIERS['mature']['max_rel']} "
      f"gate, the hardest rung on the ladder. It now sits at "
      f"{live_t.tier.upper()}, one rung short of the top, blocked by the one "
      f"criterion that SHOULD still block it: MATURE alone treats an unexplained "
      f"book as a verdict rather than as youth.\n")

# When could the gate open at all? `attribution.pending` needs a CLOSED position
# with a thesis whose horizon has PASSED, so the earliest verdict is bounded by
# the real horizons on disk - which is a date, not a matter of trading better.
attrib = [r for r in rows if r.get("kind") == "attribution_run"]
horizons = []
for f in sorted((DATA / "wiki" / "positions").glob("*.md")):
    text = f.read_text(encoding="utf-8")
    claim = [ln for ln in text.splitlines() if ln.startswith("thesis_claim:")]
    hz = [ln for ln in text.splitlines() if ln.startswith("thesis_horizon:")]
    h = hz[0].split(":", 1)[1].strip().strip("'\"") if hz else ""
    has_claim = bool(claim and claim[0].split(":", 1)[1].strip().strip("'\""))
    horizons.append((f.name[:34], h or "(none)", has_claim))
print(f"{'position':<36} {'thesis horizon':>16} {'attributable?':>15}")
print("-" * 96)
for name, h, has_claim in horizons:
    verdict = "never - no thesis" if not has_claim else f"not before {h}"
    print(f"{name:<36} {h:>16} {verdict:>15}")
earliest = min((h for _, h, c in horizons if c and h != "(none)"), default="(none)")
print(f"\nattribution_run has fired {len(attrib)} times. Every single row reads")
print("`attributed 0, pending 0, skipped_no_price 0` - it has never produced a")
print("verdict, and `pending` counts only positions ALREADY ripe, so a position")
print("waiting on its horizon is indistinguishable from no position at all.")
note(f"R2'': the promotion criterion depends on `attribution.run`, which has "
     f"returned zero in {len(attrib)} consecutive runs and logs a clean row each "
     f"time. The earliest date any verdict can exist is {earliest} - the day before "
     f"the {'2026-09-04'} deadline. The four-tier ladder therefore has exactly ONE "
     f"reachable rung for this entire run, and nothing in the logs says so.")

# ======================================================== R3 THE DYNAMIC RANGE
report("R3  Dynamic range - does conviction move size, or is size a constant?")
print("The live structure, swept through the real sizer at the real calibration.")
print("A desk expresses a view in SIZE; the question is how much room there is.\n")

# ONE spread, not the 13-lot: the sizer's `contracts` counts whatever unit the
# max_loss it is handed describes. Passing the whole live position makes every
# tier quantise to {1, 2} and measures the scaffold, not the ladder.
UNIT = [Leg(right="P", strike=766, side="long", qty=1, price=3.30),
        Leg(right="P", strike=758, side="short", qty=1, price=1.63)]
pr = optmath.payoff_ratio(UNIT, ENTRY_SPOT, ENTRY_IV, ENTRY_DTE,
                          drift=-0.004, friction=3.0)
b = pr[2] if pr else 1.5
mp, ml = optmath.max_profit_loss(UNIT)
print(f"per-spread conditional payoff b = {b:.2f}  (E[win|win] ${pr[0]:,.0f} / "
      f"E[loss|loss] ${pr[1]:,.0f}), max loss ${abs(ml):,.0f}/spread\n")

# One posture per RUNG, each forced to the tier it names, plus the live book.
# Reading the tier off the record is what the ladder is for; a sweep that wants
# to compare rungs has to pin them, or a change to the promotion rule silently
# relabels the columns (it did - all three collapsed onto SCALE after WU-8.2).
POSTURES = [("EXPLORE", posture_at(0, attributed=False, n=0)),
            ("ESTABLISH", posture_at(8, attributed=True, n=10)),
            ("SCALE", posture_at(20, attributed=True, n=20)),
            ("MATURE", posture_at(50, attributed=True, n=50))]
for want, p in POSTURES:
    assert p.tier == want.lower(), f"{want} row is actually {p.tier}"
print(f"{'caps by rung':<14} " + " ".join(
    f"{w:>16}" for w, _ in POSTURES))
print(f"{'  position':<14} " + " ".join(f"{p.position_cap:>15.1%} " for _, p in POSTURES))
print(f"{'  underlying':<14} " + " ".join(f"{p.underlying_cap:>15.1%} " for _, p in POSTURES))
print(f"{'  book':<14} " + " ".join(f"{p.book_cap:>15.1%} " for _, p in POSTURES))
print()

print(f"{'stated':>7} {'shrunk':>7} {'full f*':>8} " + " ".join(
    f"{w:>16}" for w, _ in POSTURES))
print("-" * 96)
span: dict[str, list[float]] = {k: [] for k, _ in POSTURES}
for stated in (0.55, 0.60, 0.65, 0.70, 0.80, 0.90):
    cells = []
    adj = sizing.shrink_probability(stated, cal())
    full = sizing.kelly_fraction(adj, mp, ml, payoff_ratio=b) or 0.0
    for key, p in POSTURES:
        d = sizing.size_position(
            equity=EQUITY, stated_confidence=stated, max_profit=mp, max_loss=ml,
            calibration=cal(), posture=p, underlying="SPY", payoff_ratio=b)
        span[key].append(d.fraction_of_equity)
        cells.append(f"{d.contracts:>3}c {d.fraction_of_equity:>6.2%}")
    print(f"{stated:>6.0%} {adj:>7.0%} {full:>8.3f} " + " ".join(
        f"{c:>16}" for c in cells))

print()
print(f"{'rung':<12} {'size range':>20} {'conviction span':>16}  binding cap")
print("-" * 96)
for key, p in POSTURES:
    lo, hi = min(span[key]), max(span[key])
    binds = ("per-position ceiling" if abs(hi - p.position_cap) < 5e-4
             else "per-underlying cap" if abs(hi - p.underlying_cap) < 5e-4
             else "Kelly (no cap binding)")
    print(f"{key:<12} {lo:>9.2%} .. {hi:<8.2%} "
          f"{hi / lo if lo else float('inf'):>15.2f}x  {binds}")

# The reason the top rung has to clear it: this is the posture sizing.py's own
# docstring names as correct, and a flat 5% ceiling sat below it at every tier.
quarter = (sizing.kelly_fraction(sizing.shrink_probability(0.65, cal()), mp, ml,
                                 payoff_ratio=b) or 0.0) * sizing.ESTABLISHED_KELLY
top = POSTURES[-1][1]
print(f"\nquarter Kelly on this structure is {quarter:.1%} of equity; the MATURE "
      f"per-position ceiling is now {top.position_cap:.1%} (was a flat "
      f"{sizing.MAX_FRACTION:.0%} at every rung, i.e. permanently below the target).")
lo_e, hi_e = min(span["ESTABLISH"]), max(span["ESTABLISH"])
note(f"R3: the four rungs now size differently ({span['EXPLORE'][0]:.2%} to "
     f"{max(span['MATURE']):.2%} at the extremes) and MATURE clears quarter Kelly "
     f"({quarter:.1%}). Within a rung, conviction still moves size only "
     f"{hi_e / lo_e if lo_e else float('inf'):.2f}x from a 55% view to a 90% one - "
     f"the sizer's dynamic range is real but narrow, so the trade/no-trade "
     f"boundary still carries most of the risk posture.")

# ======================================================== R4 THE DELTA ILLUSION
report("R4  The delta illusion - a linear risk number on a truncated payoff")
print("WAS: the decide prompt LED with beta-weighted delta as '% of equity per")
print("1% SPY move' under a CONCENTRATED stamp - the reason given in 41 of 89")
print("declines. It is a LINEAR extrapolation of a payoff that is flat beyond")
print("its far strike, so it quotes a per-1% loss larger than the position's")
print("entire lifetime max loss. The rows below are why that number cannot be")
print("read as a loss.")
print("NOW (WU-8.2): defined risk leads and carries the flag; the delta follows,")
print("labelled a LOCAL SLOPE and framed as the diversification lens it is.\n")

def bs_put(strike: float, spot: float, iv: float, days: float) -> float:
    """Put mark per share, r=0, on the module's own clock. The greeks above are
    the derivatives of exactly this, so the linear line and the curve below are
    guaranteed tangent - the divergence is convexity, not two different models."""
    t = optmath.year_fraction(days)
    st = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / st
    return strike * optmath._norm_cdf(-(d1 - st)) - spot * optmath._norm_cdf(-d1)


def live_mark(spot: float, days: float) -> float:
    """The 13-lot's mark, in dollars, at this spot and time."""
    return (bs_put(766, spot, ENTRY_IV, days)
            - bs_put(758, spot, ENTRY_IV, days)) * 100 * 13


g_now = optmath.net_greeks(LIVE, NOW_SPOT, ENTRY_IV, NOW_DTE)
max_loss_pct = LIVE_MAX_LOSS / EQUITY * 100
mark_now = live_mark(NOW_SPOT, NOW_DTE)
print(f"the spread marks at ${mark_now:,.0f} with {NOW_DTE}d left. It is a LONG debit")
print(f"spread, so ${mark_now:,.0f} is every dollar it can still lose, at any spot.\n")

print(f"{'SPY move':>9} {'spot':>8} {'linear delta says':>19} {'the mark actually':>19}  "
      f"overstatement")
print("-" * 96)
for mv in (0.005, 0.01, 0.02, 0.03, 0.05):
    spot = NOW_SPOT * (1 + mv)
    linear = g_now["delta_dollars"] * mv if g_now else 0.0
    actual = live_mark(spot, NOW_DTE) - mark_now
    over = (linear / actual) if actual else float("inf")
    flag = "  <- more than the position is WORTH" if linear < -mark_now else ""
    print(f"{mv:>8.1%} {spot:>8.2f} {linear:>18,.0f} {actual:>19,.0f}  "
          f"{over:>6.2f}x{flag}")

print(f"\nthe book's headline number:  {LIVE_BOOK_DELTA_PCT:.2f}% of equity per 1% SPY move")
print(f"the book's actual worst case: {-max_loss_pct:.2f}% of equity, ever, "
      f"in every state of the world")
note(f"R4: the risk number the agent declines on ({LIVE_BOOK_DELTA_PCT:.2f}% per 1%) "
     f"is {abs(LIVE_BOOK_DELTA_PCT) / max_loss_pct:.2f}x the position's ENTIRE max loss "
     f"({-max_loss_pct:.2f}%). A defined-risk book cannot lose what the linear "
     f"metric says a 1% move costs. Delta is the right measure for a hedger with "
     f"unbounded exposure; against a truncated payoff it is a caution amplifier "
     f"with no upper bound.")

# ========================================================== R5 THE HAIRCUT CHAIN
report("R5  The haircut chain - every multiplier between a stated edge and a size")
print("Constitution principle 4: 'Caution compounds - haircuts stack into a")
print("verdict nobody chose.' Here is the stack, on the live structure, at a")
print("stated 65% - each step defensible alone, the product chosen by no one.\n")

STATED = 0.65
infl = market_stats.band_inflation(DATA / "state", 3)
raw_pr = optmath.payoff_ratio(UNIT, ENTRY_SPOT, ENTRY_IV, ENTRY_DTE, drift=-0.004)
fr_pr = optmath.payoff_ratio(UNIT, ENTRY_SPOT, ENTRY_IV, ENTRY_DTE,
                             drift=-0.004, friction=3.0)
b_raw = raw_pr[2] if raw_pr else 0.0
b_fr = fr_pr[2] if fr_pr else 0.0
adj = sizing.shrink_probability(STATED, cal())
f_stated = sizing.kelly_fraction(STATED, mp, ml, payoff_ratio=b_raw) or 0.0
f_friction = sizing.kelly_fraction(STATED, mp, ml, payoff_ratio=b_fr) or 0.0
f_shrunk = sizing.kelly_fraction(adj, mp, ml, payoff_ratio=b_fr) or 0.0
f_tier = f_shrunk * live_posture.kelly_multiplier
f_final = min(max(f_tier, live_posture.seed_fraction), sizing.MAX_FRACTION)

CHAIN = [
    ("stated edge, raw payoff", f_stated, "the agent's own claim"),
    ("+ friction charged both sides", f_friction, "$3/spread round trip"),
    (f"+ calibration shrink 65% -> {adj:.0%}", f_shrunk,
     f"trust {min(1.0, max(0.0, 1 - RELIABILITY / 0.05)) * min(1.0, RESOLVED / 30):.2f}"),
    (f"x tier multiplier {live_posture.kelly_multiplier:.3f}", f_tier,
     f"{live_posture.tier.upper()} ramp, {RESOLVED} resolved"),
    ("floor/ceiling applied", f_final,
     f"seed floor {live_posture.seed_fraction:.1%}, ceiling {sizing.MAX_FRACTION:.0%}"),
]
print(f"{'step':<44} {'fraction':>10} {'of raw':>8} {'this step':>10}  note")
print("-" * 96)
prev = f_stated
for label, f, why in CHAIN:
    step = f / prev if prev else 1.0
    print(f"{label:<44} {f:>10.4f} {f / f_stated if f_stated else 0:>7.0%} "
          f"{step:>9.0%}  {why}")
    prev = f

print(f"\nbootstrap band inflation at 3d: x{infl:.2f} (holdout-validated, D-089) - "
      f"widens the\ndistribution BEFORE any of the above, so every probability in "
      f"the chain is\nalready computed on a deliberately fatter tail.")
note(f"R5: read the 'this step' column. Friction costs 1% and the calibration "
     f"shrink 9% - both honest work, and neither is the story. The TIER MULTIPLIER "
     f"costs {1 - live_posture.kelly_multiplier:.0%}, cutting {f_shrunk:.3f} to "
     f"{f_tier:.4f}. There was never a stack of compounding haircuts here: there is "
     f"ONE haircut, and before WU-8.2 it was the attribution deadlock wearing a "
     f"multiplier (x0.083). At {live_posture.tier.upper()} it is now "
     f"x{live_posture.kelly_multiplier:.3f} - the ramp doing its actual job, which "
     f"is to buy size back as evidence arrives rather than to hold it at zero.")

# ============================================================ R6 THE PRICE OF IT
report("R6  The price of it - Kelly log-growth captured vs targeted")
print("If the agent's edge is real, under-betting costs compounding. g(f) =")
print("p*ln(1+bf) + (1-p)*ln(1-f), per bet. Assume a genuine 60% at the live")
print("structure's conditional payoff - the edge the system is BUILT to find.\n")


def growth(p: float, b_: float, f: float) -> float:
    if f <= 0 or f >= 1:
        return 0.0
    return p * math.log(1 + b_ * f) + (1 - p) * math.log(1 - f)


P_TRUE, B = 0.60, b_fr
f_star = P_TRUE - (1 - P_TRUE) / B
g_full = growth(P_TRUE, B, f_star)

sized = sizing.size_position(
    equity=EQUITY, stated_confidence=P_TRUE, max_profit=mp, max_loss=ml,
    calibration=cal(), posture=live_posture, underlying="SPY", payoff_ratio=B)
f_actual = sized.fraction_of_equity

LEVELS = [
    ("full Kelly", f_star),
    ("quarter Kelly - the stated policy", f_star * sizing.ESTABLISHED_KELLY),
    ("what the system actually sizes", f_actual),
]
print(f"{'policy':<38} {'fraction':>9} {'g per bet':>10} {'% of full-Kelly growth':>23}")
print("-" * 96)
for label, f in LEVELS:
    g = growth(P_TRUE, B, f)
    print(f"{label:<38} {f:>9.2%} {g:>10.5f} {g / g_full:>22.1%}")

g_actual = growth(P_TRUE, B, f_actual)
g_quarter = growth(P_TRUE, B, f_star * sizing.ESTABLISHED_KELLY)
trade_rate = len(traded) / max(1, len(theses))
size_capture = g_actual / g_quarter
print(f"\nSizing alone captures {size_capture:.0%} of the quarter-Kelly policy "
      f"the module docstring states.")
print(f"But growth is per BET, and the system trades {len(traded)} of {len(theses)} "
      f"pre-registered theses ({trade_rate:.0%}).")
print(f"Frequency-adjusted, it captures {size_capture * trade_rate:.1%} of "
      f"its own stated policy.\n")

# The two effects MULTIPLY (0.22 x 0.08), so the shortfall splits in LOGS. An
# additive split of (1 - capture) attributes >100% between two causes and reads
# backwards - the arithmetic has to match the compounding it is describing.
print("The two losses compound rather than add, so the shortfall splits in logs:\n")
print(f"{'shortfall attributable to':<40} {'capture':>9} {'share of the gap':>18}")
print("-" * 96)
l_size, l_freq = -math.log(size_capture), -math.log(trade_rate)
total = l_size + l_freq
print(f"{'position SIZE (sizer, ladder, caps)':<40} {size_capture:>9.0%} "
      f"{l_size / total:>17.0%}")
print(f"{'trade FREQUENCY (the decision to act)':<40} {trade_rate:>9.0%} "
      f"{l_freq / total:>17.0%}")
note(f"R6: at a genuine 60% edge the system captures {size_capture * trade_rate:.1%} of "
     f"the quarter-Kelly growth its own sizing module states as policy. "
     f"{l_freq / total:.0%} of that shortfall is the decision NOT TO TRADE and "
     f"{l_size / total:.0%} is the size of the trades taken - so tuning the Kelly "
     f"multiplier or the tier caps addresses the smaller half.")

# ===================================================================== VERDICT
report("VERDICT")
print(f"{len(findings)} risk-posture finding(s):\n")
for f in findings:
    body = f.split(": ", 1)[1] if ": " in f else f
    tag = f.split(":", 1)[0]
    print(f"  {tag}. {body}\n")
