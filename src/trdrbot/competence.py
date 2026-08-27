"""Size earned by demonstrated competence, not by the calendar (D-048).

Replaces the deadline-phased posture of D-047, which keyed the risk budget on
days-to-deadline. That was an artifact of one competition, and it had a bug
waiting for the day after: once `days_left` went negative the system entered
its no-new-risk phase permanently and would never trade again.

A trading desk does not scale a trader by the date. It scales them by what
they have demonstrated, on a ladder they climb by meeting criteria and fall
down by breaching them. Four tiers here, and the criteria are the ones this
system can actually measure:

    tier        needs                                            book cap
    EXPLORE     nothing - the starting allocation                   10%
    ESTABLISH   >=5 resolved theses                                 15%
    SCALE       >=15 resolved, >=60% attributable                   20%
    MATURE      >=40 resolved, >=70% attributable, reliability<0.04 25%

Reliability gates MATURE only, not SCALE - see D-050. It is not a measurable
discriminator below ~n=40, and gating on a statistic before it can discriminate
rejects good agents and passes bad ones at roughly the same rate.

Three properties, each deliberate:

**Monotonic in evidence.** More knowledge never means less size. The previous
design could size an earned record SMALLER than an unproven one; that is
incoherent and it happened.

**Asymmetric.** Promotion needs a sustained record; demotion on drawdown is
immediate and drops a whole tier. A losing streak is evidence that the regime
has changed out from under the record, and the record was earned in the old
one - which is principle "regimes", applied to the agent's own competence.

**Attribution is a promotion criterion, not just a metric.** A trade that
profited on a wrong thesis is luck, and a book of luck is not competence
however good the P&L looks. Promotion past ESTABLISH requires that most
resolved theses were actually ATTRIBUTABLE - that the agent knows *why* it was
right. That is this system's distinctive signal and it is the honest measure of
"level of understanding" the size ladder should key on.

The deadline has not disappeared - it is a POSITION-level horizon check
(`can_open`), asking whether a specific trade can resolve before a hard stop.
That fires for a competition deadline or a planned shutdown and is simply
inert in normal operation, which is where it belongs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

EXPLORE, ESTABLISH, SCALE, MATURE = "explore", "establish", "scale", "mature"
_ORDER = (EXPLORE, ESTABLISH, SCALE, MATURE)

#: Exploration allocation while the record is too thin for Kelly to mean
#: anything. Deliberately a fixed fraction, not an edge estimate: with no
#: record the shrinkage collapses any stated edge to zero, and a system that
#: cannot place a first trade can never earn a record (measured, D-047).
SEED_FRACTION = 0.022

TIERS: dict[str, dict[str, Any]] = {
    EXPLORE:   {"cap": 0.10, "kelly": 0.00, "min_n": 0,  "max_rel": None, "min_attr": 0.0},
    ESTABLISH: {"cap": 0.15, "kelly": 0.10, "min_n": 5,  "max_rel": None, "min_attr": 0.0},
    # SCALE deliberately has NO reliability gate. Measured on our own scorer
    # (D-050): at n=15-20 a perfectly calibrated agent and a badly
    # overconfident one score 0.022 vs 0.038 - overlapping distributions, so
    # any threshold there rejects good agents and passes bad ones roughly
    # alike. Reliability only becomes a real discriminator around n=40, where
    # a perfect agent is blocked 2% of the time and a bad one 92%. Gating on a
    # statistic before it can discriminate is theatre that costs real size.
    SCALE:     {"cap": 0.20, "kelly": 0.18, "min_n": 15, "max_rel": None, "min_attr": 0.6},
    MATURE:    {"cap": 0.25, "kelly": 0.25, "min_n": 40, "max_rel": 0.04, "min_attr": 0.7},
}

#: Continuous ramp within a tier, so no single trade is a step change. The
#: tier sets the ceiling; evidence within the tier walks toward it.
RAMP_K = 6.0

#: Drawdown from the equity high-water mark. One tier down at the first
#: threshold, all the way to EXPLORE at the second.
DEMOTE_ONE_TIER_AT = 0.05
DEMOTE_TO_EXPLORE_AT = 0.10

#: A position must have this many days to resolve before a hard stop, or it is
#: not worth opening - it would be closed at whatever the book offers.
MIN_DAYS_TO_RESOLVE = 2


@dataclass(frozen=True)
class Competence:
    tier: str
    resolved: int
    reliability: float | None
    attributable_rate: float
    drawdown: float
    book_cap: float
    kelly_multiplier: float
    seed_fraction: float
    reason: str

    @property
    def uses_kelly(self) -> bool:
        return self.kelly_multiplier > 0

    def next_tier_needs(self) -> str:
        """What the agent must demonstrate to earn more size. Shown in-prompt:
        the ladder only motivates if the next rung is visible."""
        i = _ORDER.index(self.tier)
        if i == len(_ORDER) - 1:
            return "at the top tier"
        nxt = _ORDER[i + 1]
        t = TIERS[nxt]
        needs = [f"{t['min_n']} resolved theses (have {self.resolved})"]
        if t["max_rel"] is not None:
            have = f"{self.reliability:.3f}" if self.reliability is not None else "unmeasured"
            needs.append(f"reliability <{t['max_rel']} (have {have})")
        if t["min_attr"] > 0:
            needs.append(f"{t['min_attr']:.0%} attributable (have {self.attributable_rate:.0%})")
        return f"{nxt.upper()} needs " + ", ".join(needs)


def attributable_rate(positions: list[Any]) -> tuple[float, int]:
    """Share of resolved theses we could actually explain, and the count.

    'Attributable' means the outcome told us something: the view was right and
    the structure fit, or the view was right and the structure was not, or the
    view was wrong and the structure was faithful. It EXCLUDES the two that
    teach nothing - an unscoreable thesis, and a profit on a wrong view, which
    is luck wearing a win's clothing.
    """
    from .experiments import THESIS_WRONG_PROFITED_ANYWAY, UNSCOREABLE

    verdicts = [p.attribution for p in positions if getattr(p, "attribution", "")]
    if not verdicts:
        return 0.0, 0
    useful = sum(1 for v in verdicts
                 if v not in (UNSCOREABLE, THESIS_WRONG_PROFITED_ANYWAY))
    return useful / len(verdicts), len(verdicts)


def _earned_tier(n: int, reliability: float | None, attr: float) -> str:
    best = EXPLORE
    for name in _ORDER:
        t = TIERS[name]
        if n < t["min_n"]:
            continue
        if t["max_rel"] is not None and (reliability is None or reliability > t["max_rel"]):
            continue
        if attr < t["min_attr"]:
            continue
        best = name
    return best


def _demote(tier: str, drawdown: float) -> tuple[str, str]:
    if drawdown >= DEMOTE_TO_EXPLORE_AT:
        return EXPLORE, f"{drawdown:.1%} drawdown - back to exploration size"
    if drawdown >= DEMOTE_ONE_TIER_AT:
        i = max(0, _ORDER.index(tier) - 1)
        return _ORDER[i], f"{drawdown:.1%} drawdown - one tier down"
    return tier, ""


def assess(
    *,
    resolved: int,
    reliability: float | None,
    positions: list[Any],
    equity: float,
    high_water: float,
) -> Competence:
    """Where the agent sits on the ladder right now. Deterministic, no LLM."""
    attr, _ = attributable_rate(positions)
    drawdown = max(0.0, 1.0 - equity / high_water) if high_water > 0 else 0.0

    earned = _earned_tier(resolved, reliability, attr)
    tier, demotion = _demote(earned, drawdown)
    t = TIERS[tier]

    # Ramp within the tier so the boundary is not a cliff.
    kelly = t["kelly"] * (resolved / (resolved + RAMP_K)) if t["kelly"] > 0 and resolved else 0.0
    if t["kelly"] > 0 and resolved:
        kelly = max(kelly, TIERS[ESTABLISH]["kelly"] * 0.5)

    if demotion:
        reason = f"{tier.upper()} ({demotion}; earned {earned.upper()})"
    elif tier == EXPLORE:
        reason = (f"EXPLORE - {resolved} resolved theses, fixed {SEED_FRACTION:.1%} "
                  f"exploration allocation paid for the record")
    else:
        reason = (f"{tier.upper()} - {resolved} resolved, {attr:.0%} attributable, "
                  f"Kelly x{kelly:.2f}")

    return Competence(
        tier=tier, resolved=resolved, reliability=reliability,
        attributable_rate=attr, drawdown=drawdown,
        book_cap=t["cap"], kelly_multiplier=kelly,
        seed_fraction=0.0 if kelly > 0 else SEED_FRACTION,
        reason=reason,
    )


def can_open(deadline: str | None, expiry: str | None, today: date | None = None) -> tuple[bool, str]:
    """Position-level horizon check, separate from the size ladder.

    A hard stop (competition deadline, planned shutdown) makes a position that
    cannot resolve before it worthless: it gets closed at whatever the book
    offers. Inert when there is no deadline, which is the normal case.
    """
    if not deadline:
        return True, ""
    today = today or date.today()
    try:
        left = (date.fromisoformat(deadline) - today).days
    except (ValueError, TypeError):
        return True, ""
    if left < MIN_DAYS_TO_RESOLVE:
        return False, (f"{left}d to the hard stop {deadline} - a new position cannot "
                       f"resolve and would be closed at whatever the book offers")
    if expiry:
        try:
            if date.fromisoformat(expiry) > date.fromisoformat(deadline):
                return False, (f"expiry {expiry} is past the hard stop {deadline}")
        except (ValueError, TypeError):
            pass
    return True, ""


# ------------------------------------------------------------ high-water mark

def high_water_path(state_dir: Path) -> Path:
    return state_dir / "high_water.json"


def update_high_water(state_dir: Path, equity: float) -> float:
    p = high_water_path(state_dir)
    hw = 0.0
    if p.exists():
        try:
            hw = float(json.loads(p.read_text()).get("high_water", 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            hw = 0.0
    if equity > hw:
        hw = equity
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"high_water": hw}))
    return hw
