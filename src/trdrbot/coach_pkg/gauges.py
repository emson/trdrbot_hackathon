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
    return [r for r in rows if r.get("kind") == "muse"][-n:]


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


def _cost_today(cfg: Any, roles: tuple[str, ...] = ("muse", "coach_mutate")) -> float:
    from ..usage import UsageLedger

    day = ids.utc_now().date().isoformat()
    led = UsageLedger(Path(cfg.paths.state) / "usage.jsonl", cfg.pricing)
    return round(sum(c.cost_usd or 0.0 for c in led.calls()
                     if c.role in roles and str(c.ts)[:10] == day), 4)


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
    put("muse.runs_total", sum(1 for r in rows if r.get("kind") == "muse") or None)

    def _calibration_gauges() -> None:
        book = _led.Ledger(Path(cfg.paths.state) / "ledger.jsonl")
        resolved = book.resolved()
        stated = [e for e in book.all() if e.probability_stated]
        put("calibration.n", len(stated) or None)
        put("calibration.resolved", len(resolved) or None)
        if resolved:
            cal = _cal.score(_led.as_forecasts(resolved))
            put("calibration.brier", round(cal.brier, 4) if cal.brier is not None else None)
            put("calibration.n_eff", round(cal.n_eff, 2) if cal.n_eff else None)

    guarded("calibration", _calibration_gauges)
    guarded("coach.cost_usd_today", lambda: put("coach.cost_usd_today", _cost_today(cfg)))

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


def _sentinel_cost(cfg: Any, rows: list[dict[str, Any]]) -> tuple[bool, Any, Any]:
    c = getattr(cfg, "coach", None) or {}
    limit = float(c.get("cost_ceiling_usd_per_day", 10.0))
    spent = _cost_today(cfg)
    return spent > limit, spent, limit


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


SENTINELS: tuple[Sentinel, ...] = (
    Sentinel("cost_ceiling", _sentinel_cost, True,
             "the improvement loop is outspending its allowance"),
    Sentinel("churn", _sentinel_churn, False,
             "promoting faster than evidence can plausibly arrive"),
    Sentinel("entropy_floor", _sentinel_entropy, True,
             "the muse has stopped colliding diverse concepts - it is being "
             "optimised into a momentum machine"),
)


