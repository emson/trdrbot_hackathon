"""Deterministic measures recorded over time, and the sentinels that brake on them.

Split out of the coach module because this is the only part that reaches into
`usage`, `calibration`, `ledger` and `market_stats` - four cross-module reads
that had to be function-local imports to dodge cycles while they lived
alongside everything else.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import ids
from .posterior import is_closed
from .state import (
    LEVERS,
    _append,
    _read,
    events,
    load_state,
    metrics_path,
)

# --- gauges: deterministic measures, recorded over time -------------------
#
# Every gauge is computed from a store that already exists. A gauge needing new
# instrumentation is the wrong gauge - the point is to record what the system
# already knows, so divergence becomes a trajectory instead of an anecdote.
#
# A gauge returning None is OMITTED from the snapshot rather than written as 0.
# A zero that means "no data" is the absence-as-zero class (notes/012), and on
# a chart it is indistinguishable from a real collapse to zero.

GAUGE_WINDOW = 10

#: How old a DAILY source's run may be and still describe the present.
#:
#: Research and discovery run once a day, so `GAUGE_WINDOW` rows of them span
#: a fortnight and an outage inside that span is invisible - the same ten rows
#: are re-averaged every pulse and the number never moves. Three days, because
#: a Friday run is the freshest thing that exists on a Sunday and a bound that
#: fires every weekend is a bound nobody reads.
DAILY_SOURCE_MAX_AGE_DAYS = 3.0

#: What "survived the gauntlet" means, in ONE place. The muse relabels a
#: survivor to `EMITTED` or `candidate, not emitted (rank)` AFTER the gates have
#: run, so a reward reading only `candidate` scores the same outcome
#: differently depending on when it is asked. Today the trial is recorded
#: before that relabelling and the two agree by luck; the moment someone moves
#: that call one line later, every trial would silently under-count the
#: INCUMBENT and bias promotions toward the challenger. Two copies of one
#: definition drifting apart is this project's most familiar bug (two EV loops,
#: two clocks, two calibration numbers), so there is one copy and both the
#: gauge and the trial reward ask it.
SURVIVED_PREFIXES = ("candidate", "EMITTED")


def survived(fate: Any) -> bool:
    return str(fate or "").startswith(SURVIVED_PREFIXES)


def _muse_rows(rows: list[dict[str, Any]], n: int = GAUGE_WINDOW) -> list[dict[str, Any]]:
    return _kind_rows(rows, "muse", n)


def _survival(rows: list[dict[str, Any]]) -> float | None:
    muse = _muse_rows(rows)
    cands = sum(int(r.get("candidates") or 0) for r in muse)
    if not cands:
        return None
    hits = sum(sum(1 for f in (r.get("fates") or []) if survived(f.get("fate")))
               for r in muse)
    return round(hits / cands, 4)


def _candidates_per_run(rows: list[dict[str, Any]]) -> float | None:
    muse = _muse_rows(rows)
    if not muse:
        return None
    return round(sum(int(r.get("candidates") or 0) for r in muse) / len(muse), 3)


def _age_days(row: dict[str, Any]) -> float | None:
    """How long ago a journal row was written. None when it carries no stamp."""
    return ids.age_days(row.get("ts"))


def _kind_rows(rows: list[dict[str, Any]], kind: str,
               n: int = GAUGE_WINDOW,
               max_age_days: float | None = None) -> list[dict[str, Any]]:
    """Recent rows of one journal kind. `_muse_rows` generalised, because
    three of the module map's metrics needed the same slice of a different
    kind and copying it three times is how `_muse_rows` became muse-shaped in
    the first place.

    "Recent" was COUNT only, and that is not the same thing for a subsystem
    that runs once a day (D-113). Research's last 10 rows are ten days of
    history: if the daily cycle died on Thursday, the same ten rows kept being
    averaged and `research.opportunities_per_run` went on reporting a healthy
    number all week, computed entirely from a period that had ended. An
    age bound makes the window mean what its name says - and a gauge with
    nothing recent to read returns None, which this module OMITS rather than
    writing as a zero, because a zero on a chart is a collapse.
    """
    of_kind = [r for r in rows if r.get("kind") == kind]
    if max_age_days is not None:
        # An UNKNOWN age is not evidence of staleness, so an unstamped row is
        # kept. Every real journal row carries `ts`; if that ever stopped being
        # true, dropping them here would silently zero the gauge, while keeping
        # them leaves `<kind>.days_since_run` to go missing and say so.
        of_kind = [r for r in of_kind
                   if (age := _age_days(r)) is None or age <= max_age_days]
    return of_kind[-n:]


def _research_yield(rows: list[dict[str, Any]]) -> float | None:
    """Opportunities per research run. The top-down source's own metric.

    Named in the module map (019 s2.2) and measured nowhere, so a glance at
    the report could not answer whether the daily cycle was still producing.
    """
    runs = _kind_rows(rows, "research", max_age_days=DAILY_SOURCE_MAX_AGE_DAYS)
    if not runs:
        return None
    return round(sum(int(r.get("opportunities") or 0) for r in runs) / len(runs), 3)


def _days_since_run(rows: list[dict[str, Any]], kind: str) -> float | None:
    """How long since this subsystem last produced a row. None if it never has.

    The companion to the age bound above: a yield gauge that goes missing and
    one that was never there look identical on a chart, and only one of them
    is a subsystem that stopped.
    """
    of_kind = [r for r in rows if r.get("kind") == kind]
    if not of_kind:
        return None
    age = _age_days(of_kind[-1])
    return round(age, 2) if age is not None else None


def _discovery_survival(rows: list[dict[str, Any]]) -> float | None:
    """Share of nominees that survive the gauntlet to become opportunities.

    Discovery's analogue of the muse's survival rate, and the number that says
    whether its gates are getting stricter or its nominations worse - which
    are opposite problems with the same symptom.
    """
    runs = _kind_rows(rows, "discovery", max_age_days=DAILY_SOURCE_MAX_AGE_DAYS)
    nominated = sum(len(r.get("nominees") or []) for r in runs)
    if not nominated:
        return None
    return round(sum(int(r.get("opportunities") or 0) for r in runs) / nominated, 4)


def _attributable_rate(rows: list[dict[str, Any]]) -> float | None:
    """Share of attributed theses the system could actually EXPLAIN.

    The ladder's own promotion criterion past ESTABLISH, computed live in
    `competence.assess` and never trended - so the one number that gates real
    size had no history. Derived from the journal's `attribution` rows rather
    than the position store, because gauges take `cfg` and a store coupling
    here would be the wrong dependency for a measurement.

    Same definition as `competence.attributable_rate`: a lucky win and an
    unscoreable outcome both teach nothing and neither counts.
    """
    from ..experiments import THESIS_WRONG_PROFITED_ANYWAY, UNSCOREABLE

    verdicts = [str(r.get("verdict") or "") for r in rows
                if r.get("kind") == "attribution" and r.get("verdict")]
    if not verdicts:
        return None
    useful = sum(1 for v in verdicts
                 if v not in (UNSCOREABLE, THESIS_WRONG_PROFITED_ANYWAY))
    return round(useful / len(verdicts), 4)


def _funnel_overlap_rate(cfg: Any, rows: list[dict[str, Any]]) -> float | None:
    """Share of recent muse candidates on names the funnel already covers.

    The muse's stated value is finding "what a funnel never asks about", and
    discovery explicitly excludes the research universe and the watchlist from
    its nominations while the muse excludes nothing - so it can spend one of
    two daily emission slots re-discovering a name research already has a
    thesis on.

    **Measured before gated, deliberately.** Two reasons not to just add the
    exclusion. The muse prompt is the Coach's one LIVE lever: editing it from
    outside corrupts the pairing of any open A/B trial and re-fingerprints an
    artefact mid-experiment. And the premise is unproven - the muse's mandate
    is novel THESES, not novel names, so a fresh angle on a covered name may be
    exactly its job. This is the trajectory that has to justify a gate, the
    same discipline that held the vega cap to measure-first (D-094).
    """
    muse = _muse_rows(rows)
    if not muse:
        return None
    covered = {str(s).upper() for s in
               (list(getattr(cfg, "research_universe", []) or [])
                + list(getattr(cfg, "watchlist", []) or []))}
    if not covered:
        return None
    seen = [str(f.get("underlying", "")).upper()
            for r in muse for f in (r.get("fates") or [])
            if isinstance(f, dict)]
    seen = [u for u in seen if u and u != "?"]
    if not seen:
        return None
    return round(sum(1 for u in seen if u in covered) / len(seen), 4)


def _sizing_refused_rate(rows: list[dict[str, Any]]) -> float | None:
    """Share of recent sizing calls that REFUSED rather than returned a size.

    The production-visible face of I-40. A refusal here means the tool could not
    identify which simulated structure it was sizing, or the structure's whole
    expected win was eaten by friction - and before WU-4.2 every one of those
    cases silently became a frictionless max/max fallback instead. A rising
    share is either the model losing the habit of naming its structures or the
    seam losing the conditional payoff again; both are worth seeing early, and
    neither is visible anywhere else.
    """
    calls = _kind_rows(rows, "sizing")
    if not calls:
        return None
    refused = sum(1 for r in calls if str(r.get("result")) == "refused")
    return round(refused / len(calls), 4)


def _uncorroborated_decisives(rows: list[dict[str, Any]]) -> int | None:
    """Mark breaches past the immediate threshold that the underlying did not
    confirm, over the recent window.

    These close NOTHING, so they leave no exit row - the count is the only
    trace they exist. It is also the data that will eventually tune
    `CORROBORATION_FRACTION` against real artifacts rather than taste: a
    persistent stream of suppressions beside no confirmed gaps says the
    threshold is too loose, and none at all over a volatile stretch says it is
    too tight.
    """
    beats = _kind_rows(rows, "exit_run")
    if not beats:
        return None
    return sum(int(r.get("mark_breach_suppressed") or 0) for r in beats)


def _book_risk(rows: list[dict[str, Any]], field: str) -> float | None:
    """The latest book-level exposure reading, in dollars.

    Trended rather than capped, deliberately. The per-underlying cap counts
    NAMES and cannot see that three positions on correlated names are one bet
    (the `correlated-names-are-one-bet` lesson measured SPY/QQQ at 0.92); a
    vega or beta-delta CAP would see it, and would also be a gate nobody has
    yet measured the need for. So this is the trajectory that has to justify
    one first - measure, then gate, never the other way round.
    """
    beats = _kind_rows(rows, "book_risk", 1)
    if not beats:
        return None
    v = beats[-1].get(field)
    return round(float(v), 2) if v is not None else None


def _seed_entropy(rows: list[dict[str, Any]]) -> int | None:
    """Distinct concept PAIRS sampled recently.

    The muse's mandate is random collision. A sampling policy optimised for
    survival could quietly converge on one productive pair and stop being a
    muse at all - so the diversity of what it collides is measured, and a
    sentinel watches it.
    """
    muse = _muse_rows(rows)
    if not muse:
        return None
    pairs = set()
    for r in muse:
        cs = sorted(str(c) for c in (r.get("concepts") or []))
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                pairs.add((cs[i], cs[j]))
    return len(pairs)


def _playbook_rows(rows: list[dict[str, Any]], n: int = GAUGE_WINDOW) -> list[dict[str, Any]]:
    """Recent playbook rows that actually PRICED something - voids carry no
    candidates and would read as a collapse in every rate below."""
    return [r for r in _kind_rows(rows, "playbook", n * 3) if not r.get("voided")][-n:]


def _playbook_survival(rows: list[dict[str, Any]]) -> float | None:
    pb = _playbook_rows(rows)
    cands = sum(len(r.get("candidates") or []) for r in pb)
    if not cands:
        return None
    hits = sum(sum(1 for c in (r.get("candidates") or []) if survived(c.get("fate")))
               for r in pb)
    return round(hits / cands, 4)


def _playbook_candidates_per_opportunity(rows: list[dict[str, Any]]) -> float | None:
    pb = _playbook_rows(rows)
    if not pb:
        return None
    return round(sum(len(r.get("candidates") or []) for r in pb) / len(pb), 3)


def _playbook_family_entropy(rows: list[dict[str, Any]]) -> int | None:
    """Distinct families that SURVIVED recently. The playbook's version of the
    muse's seed entropy: a catalogue optimised purely for survival could
    converge on one family for every shape, and a menu of one is not a menu."""
    pb = _playbook_rows(rows)
    if not pb:
        return None
    return len({str(c.get("family")) for r in pb for c in (r.get("candidates") or [])
                if survived(c.get("fate"))})


#: Below this many resolved outcomes a hit rate is not a measurement - the
#: same floor `competence.MIN_ATTR_VERDICTS` and `ledger.MIN_GATE_RESOLVED` use.
MIN_OUTCOMES = 5


def _playbook_outcome_hit_rate(rows: list[dict[str, Any]]) -> float | None:
    """Share of resolved proposals that made money at expiry, over the
    window. The lever's slow evidence, trended beside its fast reward so the
    two can be read against each other (I-28's shape)."""
    outs = [r for r in _kind_rows(rows, "playbook_outcome", GAUGE_WINDOW * 5)
            if r.get("won") is not None]
    if len(outs) < MIN_OUTCOMES:
        return None
    return round(sum(1 for r in outs if r.get("won")) / len(outs), 4)


def _cost_today(cfg: Any, roles: tuple[str, ...] = ("muse", "coach_mutate")
                ) -> tuple[float, int]:
    """(priced spend today, count of UNPRICED calls) for the sentineled roles.

    The second number exists because summing `cost_usd or 0.0` alone is
    `usage.py`'s own named anti-pattern committed inside the safety brake:
    that module documents `cost_usd=None` as "the model is not in the pricing
    table - UNPRICED, never counted as free", and `usage.render()` surfaces it
    loudly to a human. The Coach's cost sentinel was the one reader that
    swallowed it, so a model added to the fallback chain without an
    `llm.pricing` entry spent real money against `cost_ceiling_usd_per_day`
    while the gauge read $0 (I-46, absence-as-zero, D-038).
    """
    from ..usage import UsageLedger

    day = ids.utc_now().date().isoformat()
    led = UsageLedger(Path(cfg.paths.state) / "usage.jsonl", cfg.pricing)
    today = [c for c in led.calls() if c.role in roles and str(c.ts)[:10] == day]
    priced = round(sum(c.cost_usd for c in today if c.cost_usd is not None), 4)
    return priced, sum(1 for c in today if c.cost_usd is None)


def snapshot_gauges(cfg: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """All gauges, computed from one already-loaded pass over the journal."""
    from .. import calibration as _cal
    from .. import ledger as _led

    g: dict[str, Any] = {}

    def put(name: str, value: Any) -> None:
        if value is not None:
            g[name] = value

    def guarded(name: str, compute: Any) -> None:
        """Run one gauge's computation. A failure OMITS the gauge and says so.

        This module's own rule is that a gauge with no data must be omitted
        rather than written as zero, because on a chart those are
        indistinguishable. An exception used to omit it identically and
        SILENTLY - so "the calibration store is broken" and "there is no
        calibration data yet" produced the same empty slot, which is D-038's
        absence-as-zero defect reappearing inside the module that preaches
        against it. The gauge is still never worth an exception; it is worth
        a line saying which one went missing and why.
        """
        try:
            compute()
        except Exception as exc:  # noqa: BLE001 - a gauge never breaks a pulse
            print(f"[coach] gauge {name} unavailable: {exc!r}")
            g.setdefault("gauges_failed", []).append(name)

    put("muse.survival_rate", _survival(rows))
    put("muse.candidates_per_run", _candidates_per_run(rows))
    put("muse.seed_entropy", _seed_entropy(rows))
    put("muse.funnel_overlap_rate", _funnel_overlap_rate(cfg, rows))
    put("muse.runs_total", sum(1 for r in rows if r.get("kind") == "muse") or None)
    # The second lever's own gauges (notes/026), same omit-never-zero rule.
    put("playbook.survival_rate", _playbook_survival(rows))
    put("playbook.candidates_per_opportunity", _playbook_candidates_per_opportunity(rows))
    put("playbook.family_entropy", _playbook_family_entropy(rows))
    put("playbook.runs_total", sum(1 for r in rows if r.get("kind") == "playbook") or None)
    put("playbook.outcome_hit_rate", _playbook_outcome_hit_rate(rows))
    # The other two thesis sources and the ladder's own promotion criterion.
    # Each omitted (never zeroed) when there is no data - a gauge reading 0 is
    # indistinguishable from a collapse on a chart.
    put("research.opportunities_per_run", _research_yield(rows))
    put("discovery.gauntlet_survival", _discovery_survival(rows))
    # ...and how long ago each last ran, which is the number that says whether
    # the two above are a measurement or an echo (D-113). Omitting a stale
    # yield stops the report lying; only this says WHY it went missing.
    put("research.days_since_run", _days_since_run(rows, "research"))
    put("discovery.days_since_run", _days_since_run(rows, "discovery"))
    put("attribution.attributable_rate", _attributable_rate(rows))
    # The three seams WU-4.1..4.8 closed, watched where they would reopen.
    # Every one reads a row the system already writes - a gauge needing new
    # instrumentation is the wrong gauge.
    put("sizing.refused_rate", _sizing_refused_rate(rows))
    put("exit.uncorroborated_decisives", _uncorroborated_decisives(rows))
    put("book.vega_dollars", _book_risk(rows, "vega_dollars"))
    put("book.beta_delta_dollars", _book_risk(rows, "beta_weighted_delta"))

    def _calibration_gauges() -> None:
        book = _led.Ledger(Path(cfg.paths.state) / "ledger.jsonl")
        resolved = book.resolved()
        # The SAME n the ladder reads: stated AND resolved (D-112). Counting
        # pending rows put 102 on the report beside the ladder's 73 - two
        # calibration numbers, which this module's own header names as this
        # project's most familiar bug.
        stated = [e for e in book.all() if e.probability_stated and e.outcome is not None]
        put("calibration.n", len(stated) or None)
        put("calibration.resolved", len(resolved) or None)
        if resolved:
            cal = _cal.score(_led.as_forecasts(resolved))
            put("calibration.brier", round(cal.brier, 4) if cal.brier is not None else None)
            put("calibration.n_eff", round(cal.n_eff, 2) if cal.n_eff else None)
        # Gate regret (D-104): the one self-improvement signal a gate lever
        # could be scored by without measuring itself. Measured gates only -
        # an unmeasured one is omitted, never zeroed, like every other gauge.
        regret, baseline = _led.gate_regret(book.all())
        put("gates.admitted_hold_rate", round(baseline, 4) if baseline is not None else None)
        for g in regret.values():
            if g.measured and g.regret is not None:
                put(f"gates.{g.gate}.regret", round(g.regret, 4))
                put(f"gates.{g.gate}.resolved", g.resolved)

    guarded("calibration", _calibration_gauges)
    # PRICED spend only, deliberately: a gauge that silently folded unpriced
    # calls in would be mixing "dollars" with "dollars plus an unknown", and a
    # chart cannot show that. Unpriced spend is the SENTINEL's business
    # (`_sentinel_cost`), where it can stop the loop rather than blur a line.
    guarded("coach.cost_usd_today",
            lambda: put("coach.cost_usd_today", _cost_today(cfg)[0]))

    # The model layer's calibration (D-089): the fitted inflation and how old
    # the fit is. A drifting inflation across refits, or a fit going stale
    # while the market moves regimes, is exactly the trajectory the report
    # exists to make visible.
    def _model_gauges() -> None:
        from .. import market_stats as _ms

        path = _ms.model_cal_path(Path(cfg.paths.state))
        if not path.exists():
            return  # no fit yet is the NORMAL case, and no gauge is the answer
        art = json.loads(path.read_text(encoding="utf-8"))
        per_h = art.get("per_horizon") or {}
        if "5" in per_h:
            put("model.inflation_5d", float(per_h["5"]))
        fitted = str(art.get("fitted", ""))
        if fitted:
            from datetime import datetime

            age = (ids.utc_now() - datetime.fromisoformat(fitted)).days
            put("model.cal_age_days", age)

    # "No artifact" and "the artifact is corrupt" both used to produce silence.
    # The first is expected and handled above; the second now reports.
    guarded("model_calibration", _model_gauges)

    opens = 0
    for l in LEVERS:
        st = load_state(cfg, l.name, "")
        if st.exp_id and not is_closed(cfg, st.exp_id):
            opens += 1
    g["coach.open_experiments"] = opens
    g["coach.promotions_total"] = sum(
        1 for r in events(cfg)
        if r.get("kind") == "experiment_closed" and r.get("outcome") == "promoted")
    return g


def _last_snapshot_at(cfg: Any) -> str:
    rows = [r for r in _read(metrics_path(cfg)) if r.get("kind") == "snapshot"]
    return str(rows[-1].get("ts", "")) if rows else ""


def _minutes_since(iso: str) -> float:
    if not iso:
        return 1e9
    try:
        from datetime import datetime

        return (ids.utc_now() - datetime.fromisoformat(iso)).total_seconds() / 60.0
    except (ValueError, TypeError):
        return 1e9


def marker(cfg: Any, label: str, **detail: Any) -> None:
    """A Coach action, timestamped onto the same series as the gauges, so the
    report can show "survival rose AFTER this promotion" as a picture rather
    than as a claim."""
    _append(metrics_path(cfg), {"kind": "marker", "label": label, **detail})


# --- sentinels: the autonomic brake ---------------------------------------


@dataclass(frozen=True)
class Sentinel:
    name: str
    #: (cfg, rows) -> (fired, value, limit). Deterministic, from stores only.
    check: Callable[[Any, list[dict[str, Any]]], tuple[bool, Any, Any]]
    #: True = close any open experiment. False = only block NEW ones.
    reverts: bool
    meaning: str
    #: Which levers this sentinel governs. Empty means every lever (cost,
    #: churn). A sentinel about one subsystem's behaviour - the muse's concept
    #: diversity - has nothing to say about another lever's experiment, and
    #: without a scope it would close it anyway.
    levers: tuple[str, ...] = ()


def _sentinel_cost(cfg: Any, rows: list[dict[str, Any]]) -> tuple[bool, Any, Any]:
    """Brake on the day's spend - and on spend it CANNOT price.

    Unpriced calls fire it too. The alternative is the failure this sentinel
    exists to prevent, arriving invisibly: an unpriced model is spending an
    amount nobody knows, and a ceiling compared against a number that omits it
    is not a ceiling. Firing here pauses experimentation until a human adds the
    pricing entry, which is the cheap and correct repair.
    """
    c = getattr(cfg, "coach", None) or {}
    limit = float(c.get("cost_ceiling_usd_per_day", 10.0))
    spent, unpriced = _cost_today(cfg)
    value = f"${spent}" + (f" + {unpriced} UNPRICED call(s)" if unpriced else "")
    return (spent > limit or unpriced > 0), value, f"${limit}"


def _sentinel_churn(cfg: Any, rows: list[dict[str, Any]]) -> tuple[bool, Any, Any]:
    c = getattr(cfg, "coach", None) or {}
    limit = int(c.get("churn_max_promotions_per_day", 2))
    day = ids.utc_now().date().isoformat()
    n = sum(1 for r in events(cfg)
            if r.get("kind") == "experiment_closed" and r.get("outcome") == "promoted"
            and str(r.get("ts", ""))[:10] == day)
    return n > limit, n, limit


def _sentinel_entropy(cfg: Any, rows: list[dict[str, Any]]) -> tuple[bool, Any, Any]:
    c = getattr(cfg, "coach", None) or {}
    limit = int(c.get("entropy_min_type_pairs", 3))
    ent = _seed_entropy(rows)
    # None = not enough runs to judge. Never fire on absent evidence.
    if ent is None or len(_muse_rows(rows)) < GAUGE_WINDOW:
        return False, ent, limit
    return ent < limit, ent, limit


def _sentinel_playbook_entropy(cfg: Any, rows: list[dict[str, Any]]) -> tuple[bool, Any, Any]:
    c = getattr(cfg, "coach", None) or {}
    limit = int(c.get("playbook_entropy_min_families", 3))
    ent = _playbook_family_entropy(rows)
    if ent is None or len(_playbook_rows(rows)) < GAUGE_WINDOW:
        return False, ent, limit  # not enough priced opportunities to judge
    return ent < limit, ent, limit


SENTINELS: tuple[Sentinel, ...] = (
    Sentinel("cost_ceiling", _sentinel_cost, True,
             "the improvement loop is outspending its allowance"),
    Sentinel("churn", _sentinel_churn, False,
             "promoting faster than evidence can plausibly arrive"),
    Sentinel("entropy_floor", _sentinel_entropy, True,
             "the muse has stopped colliding diverse concepts - it is being "
             "optimised into a momentum machine",
             levers=("muse.prompt",)),
    Sentinel("playbook_entropy_floor", _sentinel_playbook_entropy, True,
             "the playbook has collapsed to one or two families - a menu of one "
             "is not a menu",
             levers=("playbook.catalogue",)),
)


