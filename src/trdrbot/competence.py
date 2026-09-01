"""Size earned by demonstrated competence, not by the calendar (D-048).

Replaces the deadline-phased posture of D-047, which keyed the risk budget on
days-to-deadline. That was an artifact of one competition, and it had a bug
waiting for the day after: once `days_left` went negative the system entered
its no-new-risk phase permanently and would never trade again.

A trading desk does not scale a trader by the date. It scales them by what
they have demonstrated, on a ladder they climb by meeting criteria and fall
down by breaching them. Four tiers here, and the criteria are the ones this
system can actually measure:

    tier        needs                                            book  position
    EXPLORE     nothing - the starting allocation                  10%      5%
    ESTABLISH   >=5 resolved theses                                15%    7.5%
    SCALE       >=15 resolved, >=60% attributable                  20%     10%
    MATURE      >=40 resolved, >=70% attributable, reliability<0.04 25%   12.5%

BOTH caps move with the tier, and the second column is derived from the first
(`POSITION_SHARE_OF_BOOK`): one earned risk budget, applied at two scopes,
rather than a ladder for the book and a constant for the position.

Reliability gates MATURE only, not SCALE - see D-050. It is not a measurable
discriminator below ~n=40, and gating on a statistic before it can discriminate
rejects good agents and passes bad ones at roughly the same rate. The
attributable rate now follows that same rule (`MIN_ATTR_VERDICTS`): below five
position verdicts it is not a measurement, so it does not block - except at
MATURE, where a book that has never explained itself must not reach the top.

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

from . import ids, store

EXPLORE, ESTABLISH, SCALE, MATURE = "explore", "establish", "scale", "mature"
_ORDER = (EXPLORE, ESTABLISH, SCALE, MATURE)

#: Exploration allocation while the record is too thin for Kelly to mean
#: anything. Deliberately a fixed fraction, not an edge estimate: with no
#: record the shrinkage collapses any stated edge to zero, and a system that
#: cannot place a first trade can never earn a record (measured, D-047).
SEED_FRACTION = 0.022

TIERS: dict[str, dict[str, Any]] = {
    EXPLORE:   {"cap": 0.10, "kelly": 0.00, "min_n": 0,  "max_rel": None,
                "min_attr": 0.0, "strict_attr": False},
    ESTABLISH: {"cap": 0.15, "kelly": 0.10, "min_n": 5,  "max_rel": None,
                "min_attr": 0.0, "strict_attr": False},
    # SCALE deliberately has NO reliability gate. Measured on our own scorer
    # (D-050): at n=15-20 a perfectly calibrated agent and a badly
    # overconfident one score 0.022 vs 0.038 - overlapping distributions, so
    # any threshold there rejects good agents and passes bad ones roughly
    # alike. Reliability only becomes a real discriminator around n=40, where
    # a perfect agent is blocked 2% of the time and a bad one 92%. Gating on a
    # statistic before it can discriminate is theatre that costs real size.
    #
    # `strict_attr` applies that SAME rule to the sibling gate. An attributable
    # rate over fewer than MIN_ATTR_VERDICTS verdicts cannot discriminate
    # either, so below that it does not block - except at MATURE, where the
    # record is deep enough that silence is itself informative.
    SCALE:     {"cap": 0.20, "kelly": 0.18, "min_n": 15, "max_rel": None,
                "min_attr": 0.6, "strict_attr": False},
    MATURE:    {"cap": 0.25, "kelly": 0.25, "min_n": 40, "max_rel": 0.04,
                "min_attr": 0.7, "strict_attr": True},
}

#: Position verdicts below which the attributable rate is not a measurement.
#: Attribution needs a CLOSED position whose thesis horizon has PASSED, so the
#: rate moves on a clock the agent cannot hurry: measured live, `attribution.run`
#: returned zero for 172 consecutive runs with three positions on the book, two
#: of them already closed and profitable, purely because their horizons had not
#: arrived. Scoring that as 0% - which is what `sum([])/len([])` guarded by a
#: `return 0.0` amounts to - gave a book with nothing resolved yet the identical
#: grade as a book of pure luck, and pinned the ladder to one rung for the whole
#: run. Unknown is not zero.
MIN_ATTR_VERDICTS = 5

#: A single position may never be more than this share of the risk the BOOK is
#: permitted to carry, which makes the per-position ceiling a property of the
#: tier exactly as the book cap already is.
#:
#: It replaced a flat `sizing.MAX_FRACTION = 0.05` that did not move with the
#: ladder at all, and that was incoherent in two directions. Upward: a MATURE
#: agent with 40 resolved theses and demonstrated reliability earned a bigger
#: BOOK and the identical single POSITION as a day-one EXPLORE agent - the same
#: more-evidence-must-never-mean-less-size invariant this module already
#: enforces twice, violated in the one place nothing checked. Downward: quarter
#: Kelly on a live structure measured 12% of equity, so a flat 5% ceiling sat
#: BELOW the posture `sizing.py`'s own docstring names as correct, and no amount
#: of demonstrated competence could ever reach it.
#:
#: At 0.5 the EXPLORE rung is 5% - byte-identical to the constant it replaces,
#: so nothing about a fresh account's first trade changes - and MATURE reaches
#: 12.5%, which clears quarter Kelly by enough for the target to be reachable
#: rather than decorative.
POSITION_SHARE_OF_BOOK = 0.5

#: Per-NAME cap, on the same earned budget. It has to scale with the other two
#: or the three stop nesting: with the position cap moved onto the ladder and
#: this one left flat at 0.08, MATURE permitted 12.5% on one POSITION and only
#: 8% on the NAME it sits on, so the tighter constraint was the wider scope.
#: An ordering that inverts at the top of the ladder is not a cap, it is two
#: caps disagreeing.
#:
#: 0.8 is not a new opinion about concentration: it is the ratio the flat
#: constants already implied (0.08 / 0.10), so the EXPLORE rung reproduces
#: 5% / 8% / 10% exactly. Every tier above it inherits the same shape, and
#: `position <= underlying <= book` now holds by construction rather than by
#: three constants happening to be in order.
UNDERLYING_SHARE_OF_BOOK = 0.8

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
    #: None means NOT YET MEASURABLE - too few resolved position verdicts to
    #: tell an explicable book from a lucky one. Distinct from 0.0, which is
    #: the real and damning answer that nothing resolved could be explained.
    attributable_rate: float | None
    drawdown: float
    book_cap: float
    kelly_multiplier: float
    seed_fraction: float
    reason: str
    verdicts: int = 0
    #: Independent-equivalent sample size behind `resolved` (`calibration.
    #: effective_n`). REPORTED, never gated - `effective_n`'s own docstring
    #: forecloses gating on it under D-009, and that call stands. It is carried
    #: here because the ladder's thresholds are counted in raw forecasts while
    #: the calibration layer says what those forecasts are worth, and an
    #: operator reading "15 resolved (have 29)" deserves to see that the 29 is
    #: 11.8 independent bets before concluding the next rung is nearly earned.
    effective: float | None = None

    @property
    def uses_kelly(self) -> bool:
        return self.kelly_multiplier > 0

    @property
    def position_cap(self) -> float:
        """Most of equity one position may put at defined risk, at this tier."""
        return self.book_cap * POSITION_SHARE_OF_BOOK

    @property
    def underlying_cap(self) -> float:
        """Most of equity one NAME may carry, at this tier. Nests between the
        other two by construction: position <= underlying <= book."""
        return self.book_cap * UNDERLYING_SHARE_OF_BOOK

    def next_tier_needs(self) -> str:
        """What the agent must demonstrate to earn more size. Shown in-prompt:
        the ladder only motivates if the next rung is visible."""
        i = _ORDER.index(self.tier)
        if i == len(_ORDER) - 1:
            return "at the top tier"
        nxt = _ORDER[i + 1]
        t = TIERS[nxt]
        have_n = f"have {self.resolved}"
        if self.effective is not None and self.effective < self.resolved:
            have_n += f", {self.effective:.1f} independent"
        needs = [f"{t['min_n']} resolved theses ({have_n})"]
        if t["max_rel"] is not None:
            have = f"{self.reliability:.3f}" if self.reliability is not None else "unmeasured"
            needs.append(f"reliability <{t['max_rel']} (have {have})")
        if t["min_attr"] > 0:
            if self.attributable_rate is None or self.verdicts < MIN_ATTR_VERDICTS:
                # The honest reading of an unmeasured gate, and the one the
                # agent needs: it is not failing this criterion, it is waiting
                # on closed positions whose horizons have passed. Printing
                # "have 0%" here is what made a jammed pipeline look like a
                # verdict on the agent's judgement.
                #
                # Whether that BLOCKS is the next rung's own business, and
                # saying "not blocking" under MATURE - which requires the
                # statistic to have spoken - would be the same class of untruth
                # one level down.
                have_a = (f"unmeasured - needs {MIN_ATTR_VERDICTS} resolved position "
                          f"verdicts, have {self.verdicts}; "
                          + ("BLOCKS this rung" if t["strict_attr"] else "not blocking"))
            else:
                have_a = f"have {self.attributable_rate:.0%} over {self.verdicts}"
            needs.append(f"{t['min_attr']:.0%} attributable ({have_a})")
        return f"{nxt.upper()} needs " + ", ".join(needs)


def attributable_rate(positions: list[Any]) -> tuple[float | None, int]:
    """Share of resolved theses we could actually explain, and the count.

    'Attributable' means the outcome told us something: the view was right and
    the structure fit, or the view was right and the structure was not, or the
    view was wrong and the structure was faithful. It EXCLUDES the two that
    teach nothing - an unscoreable thesis, and a profit on a wrong view, which
    is luck wearing a win's clothing.

    **None when nothing has been attributed yet, never 0.0.** A rate of zero is
    a real and damning measurement - everything that resolved was luck or
    unscoreable - and the empty case shares none of its meaning. Returning 0.0
    for both made them indistinguishable to the one caller that matters, and
    `coach_pkg.gauges._attributable_rate` had already reached the right answer
    for the same number, so this also ends a two-definitions-one-quantity split
    that was live in the codebase.
    """
    from .experiments import THESIS_WRONG_PROFITED_ANYWAY, UNSCOREABLE

    verdicts = [p.attribution for p in positions if getattr(p, "attribution", "")]
    if not verdicts:
        return None, 0
    useful = sum(1 for v in verdicts
                 if v not in (UNSCOREABLE, THESIS_WRONG_PROFITED_ANYWAY))
    return useful / len(verdicts), len(verdicts)


def _attr_ok(t: dict[str, Any], attr: float | None, verdicts: int) -> bool:
    """Does the attributable rate clear this rung - or is it not yet a number?

    Three states, and collapsing the last two is the bug this exists to keep
    fixed: MEASURED AND GOOD promotes, MEASURED AND POOR blocks, and NOT YET
    MEASURED holds its peace below MATURE. A criterion that cannot discriminate
    should not be allowed to decide, which is D-050's finding about reliability
    at SCALE stated for its sibling gate.

    MATURE is the exception on purpose. It needs 40 resolved theses, by which
    point positions have had ample time to close and be scored, so an empty
    verdict list there is no longer a young pipeline - it is a book that has
    never once explained itself, and the top of the ladder is precisely where
    that must count against it.
    """
    if t["min_attr"] <= 0:
        return True
    if attr is None or verdicts < MIN_ATTR_VERDICTS:
        return not t["strict_attr"]
    return attr >= t["min_attr"]


def _earned_tier(n: int, reliability: float | None, attr: float | None,
                 verdicts: int) -> str:
    best = EXPLORE
    for name in _ORDER:
        t = TIERS[name]
        if n < t["min_n"]:
            continue
        if t["max_rel"] is not None and (reliability is None or reliability > t["max_rel"]):
            continue
        if not _attr_ok(t, attr, verdicts):
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
    effective: float | None = None,
) -> Competence:
    """Where the agent sits on the ladder right now. Deterministic, no LLM.

    `effective` is the independent-equivalent forecast count. It is carried
    onto the result and shown, never gated on - see `Competence.effective`.
    """
    attr, verdicts = attributable_rate(positions)
    drawdown = max(0.0, 1.0 - equity / high_water) if high_water > 0 else 0.0

    earned = _earned_tier(resolved, reliability, attr, verdicts)
    tier, demotion = _demote(earned, drawdown)
    t = TIERS[tier]

    # Ramp within the tier so the boundary is not a cliff.
    kelly = t["kelly"] * (resolved / (resolved + RAMP_K)) if t["kelly"] > 0 and resolved else 0.0
    if t["kelly"] > 0 and resolved:
        kelly = max(kelly, TIERS[ESTABLISH]["kelly"] * 0.5)

    attr_note = (f"{attr:.0%} attributable" if attr is not None
                 else f"attribution unmeasured ({verdicts} verdicts)")
    if demotion:
        reason = f"{tier.upper()} ({demotion}; earned {earned.upper()})"
    elif tier == EXPLORE:
        reason = (f"EXPLORE - {resolved} resolved theses, fixed {SEED_FRACTION:.1%} "
                  f"exploration allocation paid for the record")
    else:
        reason = (f"{tier.upper()} - {resolved} resolved, {attr_note}, "
                  f"Kelly x{kelly:.2f}")

    return Competence(
        tier=tier, resolved=resolved, reliability=reliability,
        attributable_rate=attr, drawdown=drawdown,
        book_cap=t["cap"], kelly_multiplier=kelly,
        # The exploration allocation is a FLOOR, not an alternative. It used to
        # zero out the moment Kelly engaged, which inverted the ladder at its
        # very first rung: at n=4 a 1:1 payoff at 62% confidence sized 4
        # contracts (2.0% of equity), and at n=5 - promoted to ESTABLISH,
        # strictly MORE evidence - it sized 1 contract (0.5%). ESTABLISH's
        # Kelly ceiling is 0.10 and its ramp starts at 0.05, so a full Kelly of
        # 0.12 buys 0.6% of equity: less than the 2.2% the agent was already
        # permitted while knowing nothing. Sizing takes the larger of the two,
        # so Kelly can only ever RAISE size above the exploration allocation.
        # `test_size_is_monotonic_in_evidence` asserted exactly this property
        # and missed it: it measured integer CONTRACTS at one payoff where the
        # `contracts < 1 -> 1` floor pinned every rung to the same value.
        seed_fraction=SEED_FRACTION,
        reason=reason,
        verdicts=verdicts,
        effective=effective,
    )


#: A forecast only teaches once it RESOLVES, and nothing it teaches can move a
#: decision that has already been made. So a horizon needs room after it: this
#: many days between resolution and the hard stop, or the answer arrives too
#: late to act on and the forecast was a diary entry.
MIN_DAYS_TO_ACT_ON = 1
#: Preferred horizon, in days from today. D-070's argument, now arithmetic
#: instead of prose: one slow forecast is worth less than three fast ones, and
#: short horizons are harder, which is the point - they test judgement rather
#: than drift.
PREFERRED_HORIZON_DAYS = 3


def forecast_window(deadline: str | None, today: date | None = None
                    ) -> tuple[str, str, str] | None:
    """(earliest, preferred, latest) as ISO dates, or None with no deadline.

    Derived, never recalled - the same date discipline D-032 imposed after the
    agent dated horizons from memory. Every thesis source asks this rather than
    carrying its own day-count, because they had drifted apart: `record_forecast`
    argued for 1-3 days in prose, `discovery` allowed anything up to and
    including the deadline, and `muse` allowed 1-10 days with no deadline check
    at all. The muse's output clustered at the far end and every one of its five
    live forecasts landed on the last useful day but one.

    **`earliest` exists because the first version of this returned only a
    preferred date and the prompt said "prefer X or earlier".** The muse read
    that exactly as written and dated a candidate TODAY, which resolves in zero
    days and was thrown out by the very next gate. A one-sided instruction
    invites the degenerate end of it; a window has two sides.
    """
    if not deadline:
        return None
    today = today or ids.market_today()
    try:
        stop = date.fromisoformat(deadline)
    except (ValueError, TypeError):
        return None
    from datetime import timedelta

    latest = stop - timedelta(days=MIN_DAYS_TO_ACT_ON)
    earliest = min(today + timedelta(days=1), latest)
    preferred = min(today + timedelta(days=PREFERRED_HORIZON_DAYS), latest)
    return (earliest.isoformat(), preferred.isoformat(), latest.isoformat())


def can_open(deadline: str | None, expiry: str | None, today: date | None = None) -> tuple[bool, str]:
    """Position-level horizon check, separate from the size ladder.

    A hard stop (competition deadline, planned shutdown) makes a position that
    cannot resolve before it worthless: it gets closed at whatever the book
    offers. Inert when there is no deadline, which is the normal case.
    """
    if not deadline:
        return True, ""
    today = today or ids.market_today()
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


def update_high_water(state_dir: Path, equity: float, journal: Any = None) -> float:
    """The peak equity drawdown is measured against. Corruption is LOUD.

    A corrupt file used to reset `hw` to 0.0, at which point `equity > hw` was
    trivially true and the peak became today's equity - so drawdown computed
    to exactly 0 and demotion silently stopped working until a new peak formed
    naturally. Fail-open on a capital-protection input, and invisible.

    The lost peak cannot be recovered (atomic writes now stop it being lost in
    the first place), so the fix is to say so: a `state_corrupt` row makes the
    degraded window visible to `trdrbot health` and `trdrbot report` instead
    of leaving the ladder quietly unguarded.
    """
    p = high_water_path(state_dir)
    hw = 0.0
    if p.exists():
        try:
            hw = float(json.loads(p.read_text(encoding="utf-8")).get("high_water", 0.0))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            print(f"[competence] high_water.json unreadable ({exc!r}) - drawdown "
                  f"protection is degraded until a new peak forms")
            if journal is not None:
                journal.append("state_corrupt", file="high_water.json",
                               consequence="drawdown_unguarded", error=repr(exc)[:200])
            hw = 0.0
    if equity > hw:
        hw = equity
        store.write_atomic(p, json.dumps({"high_water": hw}))
    return hw
