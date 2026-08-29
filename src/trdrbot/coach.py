"""The Coach - autonomous subsystem self-improvement (D-088).

Every subsystem here improves only when a human-led session finds a defect.
This makes improvement a RUNTIME behaviour: a subsystem declares what "good"
looks like as deterministic numbers, declares the choices it could make
differently as variants, and the Coach runs paired A/B trials against its own
evidence, promotes winners, and reverts anything that drifts.

Four rules, each from a measured incident rather than a preference:

  1. Rewards are COMPUTED, never an LLM's opinion of an output. The muse's own
     gauntlet already scores its candidates deterministically; that is the
     reward. (research.py's principle, re-proven by D-081.)
  2. The Coach touches DATA, never code. Variants live in
     `data/state/levers/*.json`. There is deliberately no code path from Coach
     state to a gate threshold, sizing math, or a sentinel definition - the
     human pre-authorises the SPACE, which is what replaces an approval gate.
  3. A lever's experiment may never be scored by machinery that same
     experiment can move (`_disjoint`). The thing that measures must not be
     movable by the thing measured.
  4. The heartbeat is a DIFFERENT record from the output. `coach_run` is
     written every pulse whether or not anything happened, because "found
     nothing" and "never ran" were the same number four separate times in this
     project's history (D-074, D-082, D-086).

elfmem blocks and the constitution are NOT levers and will not become ones:
elfmem's own ADR 0003 simulated four architectures for automatic
constitutional evolution and none beat baseline. That is evidence, not
caution. They get gauges and reporting.

Concurrency: single-process, like the rest of the system (the run lock in
`cli` enforces one loop). Two pulses racing would interleave appends
harmlessly but could double-promote; not defended against, because the
assumption holds everywhere else here too.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import ids

# --- promotion defaults ----------------------------------------------------
#
# The evidence unit is a CANDIDATE, not a run: one muse run yields ~5
# candidates through ~8 gates, so 8 runs is ~40 Bernoulli trials per arm -
# plenty for a real effect to clear 0.90 while still refusing a lucky streak.
# The RUN floor exists only so a single freak run cannot carry a promotion,
# and the CANDIDATE floor exists because 8 runs of one candidate each is 8
# trials wearing 8 runs' clothing.
PROMOTE_AT = 0.90
FUTILITY_AT = 0.05
MIN_RUNS = 8
MIN_CANDIDATES = 24
FUTILITY_MIN_RUNS = 6
CAP_RUNS = 40

#: Gauges are snapshotted on a cadence, not every pulse - the pulse itself is
#: event-driven (after a muse run, and at housekeeping) and a snapshot per
#: event would make the series sampling-rate-dependent rather than time-series.
SNAPSHOT_EVERY_MIN = 30
#: An LLM call generates challengers. Cheap tier, but not free, and there is
#: nothing to learn from mutating faster than trials can score.
MUTATE_COOLDOWN_MIN = 180
#: Attempts per mutation, each fed the previous rejection reason. Measured
#: against the real model: a first attempt fails validation a meaningful
#: fraction of the time - always the same way, literal braces written in prose
#: (`{X and Y}`), which `.format()` reads as a placeholder - and a second
#: attempt told exactly that usually fixes it. Cheap tier, so three attempts
#: cost far less than losing a whole mutation cooldown to a fixable typo.
MUTATE_ATTEMPTS = 3

SEED_VARIANT_ID = "v0"


# --- registry --------------------------------------------------------------


@dataclass(frozen=True)
class Lever:
    """A declared space the Coach may move within, autonomously.

    `reward_modules` is what enforces rule 3: an experiment on this lever is
    scored by these modules, so no OTHER lever naming any of them may run an
    experiment at the same time.
    """

    name: str
    subsystem: str
    reward_modules: tuple[str, ...]
    kind: str  # prompt | policy


LEVERS: tuple[Lever, ...] = (
    Lever("muse.prompt", "muse", ("muse.gates",), "prompt"),
)


def lever(name: str) -> Lever | None:
    return next((l for l in LEVERS if l.name == name), None)


# --- variants and lever state ---------------------------------------------


@dataclass
class Variant:
    id: str
    text: str
    fingerprint: str = ""
    since: str = ""
    origin: str = "seed"  # seed | mutation | human | audit_rematch

    def __post_init__(self) -> None:
        # Recompute rather than trust: a human editing the state file by hand
        # is a supported steering move, and a stale fingerprint beside edited
        # text would silently mislabel every trial that variant runs in.
        self.fingerprint = fingerprint(self.text)


def fingerprint(text: str) -> str:
    """Identical scheme to `prompts.PromptRef.fingerprint` - one hash, one
    meaning. A second scheme is how two identities for one artefact begin."""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


@dataclass
class LeverState:
    lever: str
    incumbent: Variant
    previous: Variant | None = None
    challenger: Variant | None = None
    exp_id: str | None = None
    paused: bool = False
    pinned: bool = False
    sentinel_block: dict[str, Any] | None = None
    next_variant_n: int = 1
    last_mutation_at: str = ""

    @property
    def blocked(self) -> str:
        """Why no new experiment may open. Empty string when clear."""
        if self.paused:
            return "paused by operator"
        if self.pinned:
            return "pinned by operator"
        if self.sentinel_block:
            return f"sentinel: {self.sentinel_block.get('name')}"
        return ""


def _levers_dir(cfg: Any) -> Path:
    return Path(cfg.paths.state) / "levers"


def _state_path(cfg: Any, lever_name: str) -> Path:
    return _levers_dir(cfg) / f"{lever_name}.json"


def _variant(raw: Any) -> Variant | None:
    if not isinstance(raw, dict) or not raw.get("text"):
        return None
    return Variant(id=str(raw.get("id") or SEED_VARIANT_ID), text=str(raw["text"]),
                   since=str(raw.get("since") or ""), origin=str(raw.get("origin") or "seed"))


def load_state(cfg: Any, lever_name: str, seed_text: str) -> LeverState:
    """Lever state, or a fresh one seeded from the in-code default.

    A corrupt or unreadable file degrades to incumbent-only and says so. It is
    deliberately NOT overwritten here: a human may want to read what broke, and
    a self-healing write would destroy the evidence. The next legitimate state
    change rewrites it.
    """
    path = _state_path(cfg, lever_name)
    seed = Variant(id=SEED_VARIANT_ID, text=seed_text, since="", origin="seed")
    if not path.exists():
        return LeverState(lever=lever_name, incumbent=seed)
    try:
        raw = json.loads(path.read_text())
        inc = _variant(raw.get("incumbent")) or seed
        return LeverState(
            lever=lever_name,
            incumbent=inc,
            previous=_variant(raw.get("previous")),
            challenger=_variant(raw.get("challenger")),
            exp_id=raw.get("exp_id") or None,
            paused=bool(raw.get("paused")),
            pinned=bool(raw.get("pinned")),
            sentinel_block=raw.get("sentinel_block") or None,
            next_variant_n=int(raw.get("next_variant_n") or 1),
            last_mutation_at=str(raw.get("last_mutation_at") or ""),
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"[coach] lever state unreadable ({lever_name}): {exc!r} - "
              f"running incumbent-only from the in-code seed")
        return LeverState(lever=lever_name, incumbent=seed)


def save_state(cfg: Any, st: LeverState) -> None:
    """Atomic: write-temp then os.replace, so a crash mid-write cannot leave a
    half-file that the next load would read as corrupt."""
    path = _state_path(cfg, st.lever)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "lever": st.lever,
        "paused": st.paused,
        "pinned": st.pinned,
        "incumbent": asdict(st.incumbent),
        "previous": asdict(st.previous) if st.previous else None,
        "challenger": asdict(st.challenger) if st.challenger else None,
        "exp_id": st.exp_id,
        "sentinel_block": st.sentinel_block,
        "next_variant_n": st.next_variant_n,
        "last_mutation_at": st.last_mutation_at,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2))
    os.replace(tmp, path)


# --- the event log ---------------------------------------------------------


def events_path(cfg: Any) -> Path:
    return Path(cfg.paths.data) / "experiments.jsonl"


def metrics_path(cfg: Any) -> Path:
    return Path(cfg.paths.data) / "metrics.jsonl"


def _append(path: Path, row: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps({"ts": ids.utc_now().isoformat(), **row}) + "\n")
    except OSError as exc:  # noqa: BLE001 - bookkeeping never blocks a run
        print(f"[coach] could not append to {path.name}: {exc!r}")


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def events(cfg: Any) -> list[dict[str, Any]]:
    return _read(events_path(cfg))


# --- posterior comparison (pure, deterministic, no dependencies) ----------


def _beta_logpdf(x: float, a: float, b: float) -> float:
    return (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
            + (a - 1.0) * math.log(x) + (b - 1.0) * math.log1p(-x))


def p_challenger_better(s_c: int, f_c: int, s_i: int, f_i: int, *, grid: int = 2001) -> float:
    """P(challenger success rate > incumbent's) under Beta(1+s, 1+f) posteriors.

    Deterministic numerical integration of f_challenger(x) * F_incumbent(x),
    on a fixed grid, with `math` only - no numpy/scipy, no sampling, so the
    same counts always give the same answer and a test can pin it exactly.
    Uniform Beta(1,1) priors: with no evidence the answer is 0.5, which is the
    honest starting point for "is this variant better".
    """
    a_c, b_c = 1.0 + s_c, 1.0 + f_c
    a_i, b_i = 1.0 + s_i, 1.0 + f_i
    eps = 1e-9
    step = (1.0 - 2 * eps) / (grid - 1)
    xs = [eps + step * i for i in range(grid)]
    pdf_i = [math.exp(_beta_logpdf(x, a_i, b_i)) for x in xs]
    pdf_c = [math.exp(_beta_logpdf(x, a_c, b_c)) for x in xs]

    cdf_i, acc = [0.0] * grid, 0.0
    for k in range(1, grid):
        acc += 0.5 * (pdf_i[k] + pdf_i[k - 1]) * step
        cdf_i[k] = acc
    total = cdf_i[-1] or 1.0
    cdf_i = [c / total for c in cdf_i]

    num = den = 0.0
    for k in range(1, grid):
        vk, vp = pdf_c[k] * cdf_i[k], pdf_c[k - 1] * cdf_i[k - 1]
        num += 0.5 * (vk + vp) * step
        den += 0.5 * (pdf_c[k] + pdf_c[k - 1]) * step
    return num / den if den else 0.5


# --- experiment tallies ----------------------------------------------------


@dataclass
class Tally:
    exp_id: str
    lever: str
    incumbent: str
    challenger: str
    runs: int = 0
    voided: int = 0
    s_i: int = 0
    f_i: int = 0
    s_c: int = 0
    f_c: int = 0
    opened_ts: str = ""

    @property
    def n_i(self) -> int:
        return self.s_i + self.f_i

    @property
    def n_c(self) -> int:
        return self.s_c + self.f_c

    @property
    def posterior(self) -> float:
        return p_challenger_better(self.s_c, self.f_c, self.s_i, self.f_i)


def tally(cfg: Any, exp_id: str) -> Tally | None:
    """Replay the event log for one experiment. The log is truth; lever state
    holds only which variants are live, so nothing accumulative can drift."""
    rows = events(cfg)
    opened = next((r for r in rows if r.get("kind") == "experiment_opened"
                   and r.get("exp_id") == exp_id), None)
    if not opened:
        return None
    t = Tally(exp_id=exp_id, lever=str(opened.get("lever", "")),
              incumbent=str(opened.get("incumbent", "")),
              challenger=str(opened.get("challenger", "")),
              opened_ts=str(opened.get("ts", "")))
    for r in rows:
        if r.get("kind") != "trial_result" or r.get("exp_id") != exp_id:
            continue
        inc, ch = r.get("incumbent") or {}, r.get("challenger") or {}
        if ch.get("voided"):
            t.voided += 1
            continue
        t.runs += 1
        t.s_i += int(inc.get("survived") or 0)
        t.f_i += int(inc.get("failed") or 0)
        t.s_c += int(ch.get("survived") or 0)
        t.f_c += int(ch.get("failed") or 0)
    return t


def is_closed(cfg: Any, exp_id: str) -> bool:
    return any(r.get("kind") == "experiment_closed" and r.get("exp_id") == exp_id
               for r in events(cfg))


def verdict(t: Tally, floors: dict[str, Any]) -> tuple[str, str]:
    """(outcome, reason). `outcome` is "" while the experiment should continue.

    Pure: takes a tally and thresholds, returns a decision. Every promotion
    this system ever makes goes through this one function, so it is the one
    place a test has to pin.
    """
    p = t.posterior
    min_runs = int(floors.get("min_runs", MIN_RUNS))
    min_cands = int(floors.get("min_candidates", MIN_CANDIDATES))
    promote_at = float(floors.get("promote_at", PROMOTE_AT))
    futility_at = float(floors.get("futility_at", FUTILITY_AT))
    futility_runs = int(floors.get("futility_min_runs", FUTILITY_MIN_RUNS))
    cap = int(floors.get("cap_runs", CAP_RUNS))

    enough = t.runs >= min_runs and min(t.n_i, t.n_c) >= min_cands
    if p >= promote_at and enough:
        return "promoted", (f"P(better)={p:.3f} over {t.runs} paired runs "
                            f"({t.s_c}/{t.n_c} vs {t.s_i}/{t.n_i})")
    if p <= futility_at and t.runs >= futility_runs:
        return "refuted", (f"P(better)={p:.3f} after {t.runs} runs - futile, "
                           f"stop paying for it ({t.s_c}/{t.n_c} vs {t.s_i}/{t.n_i})")
    if t.runs >= cap:
        return "timeout", (f"{t.runs} runs without a verdict (P={p:.3f}) - "
                           f"the incumbent keeps its place")
    return "", ""


# --- what a subsystem asks for at run time --------------------------------


@dataclass
class Arms:
    """What the muse needs to run one (possibly paired) cycle."""

    incumbent: Variant
    challenger: Variant | None = None
    exp_id: str | None = None

    @property
    def paired(self) -> bool:
        return self.challenger is not None and self.exp_id is not None


def arms(cfg: Any, lever_name: str, *, seed_text: str) -> Arms:
    """The variants a subsystem should run right now. Never raises.

    One state read gives both the production variant and (when an experiment
    is open) the shadow challenger, so a subsystem needs exactly one Coach call
    on its hot path.
    """
    try:
        if not enabled(cfg):
            return Arms(incumbent=Variant(SEED_VARIANT_ID, seed_text))
        st = load_state(cfg, lever_name, seed_text)
        if st.challenger and st.exp_id and not is_closed(cfg, st.exp_id):
            return Arms(incumbent=st.incumbent, challenger=st.challenger, exp_id=st.exp_id)
        return Arms(incumbent=st.incumbent)
    except Exception as exc:  # noqa: BLE001 - never break a run over the Coach
        print(f"[coach] arms() failed, running the seed incumbent: {exc!r}")
        return Arms(incumbent=Variant(SEED_VARIANT_ID, seed_text))


def record_trial(cfg: Any, exp_id: str, *, run_nonce: int,
                 incumbent: dict[str, Any], challenger: dict[str, Any]) -> None:
    """Append one paired result. Never raises."""
    try:
        t = tally(cfg, exp_id)
        post = t.posterior if t else 0.5
        _append(events_path(cfg), {
            "kind": "trial_result", "exp_id": exp_id, "run_nonce": run_nonce,
            "incumbent": incumbent, "challenger": challenger,
            "posterior_p_challenger_better": round(post, 4),
        })
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] could not record trial: {exc!r}")


# --- config accessors ------------------------------------------------------


def enabled(cfg: Any) -> bool:
    return bool((getattr(cfg, "coach", None) or {}).get("enabled", True))


def floors(cfg: Any) -> dict[str, Any]:
    c = getattr(cfg, "coach", None) or {}
    return {
        "min_runs": c.get("min_runs", MIN_RUNS),
        "min_candidates": c.get("min_candidates", MIN_CANDIDATES),
        "promote_at": c.get("promote_at", PROMOTE_AT),
        "futility_at": c.get("futility_at", FUTILITY_AT),
        "futility_min_runs": c.get("futility_min_runs", FUTILITY_MIN_RUNS),
        "cap_runs": c.get("cap_runs", CAP_RUNS),
    }


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
    from .usage import UsageLedger

    day = ids.utc_now().date().isoformat()
    led = UsageLedger(Path(cfg.paths.state) / "usage.jsonl", cfg.pricing)
    return round(sum(c.cost_usd or 0.0 for c in led.calls()
                     if c.role in roles and str(c.ts)[:10] == day), 4)


def snapshot_gauges(cfg: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """All gauges, computed from one already-loaded pass over the journal."""
    from . import calibration as _cal, ledger as _led

    g: dict[str, Any] = {}

    def put(name: str, value: Any) -> None:
        if value is not None:
            g[name] = value

    put("muse.survival_rate", _survival(rows))
    put("muse.candidates_per_run", _candidates_per_run(rows))
    put("muse.seed_entropy", _seed_entropy(rows))
    put("muse.runs_total", sum(1 for r in rows if r.get("kind") == "muse") or None)

    try:
        book = _led.Ledger(Path(cfg.paths.state) / "ledger.jsonl")
        resolved = book.resolved()
        stated = [e for e in book.all() if e.probability_stated]
        put("calibration.n", len(stated) or None)
        put("calibration.resolved", len(resolved) or None)
        if resolved:
            cal = _cal.score(_led.as_forecasts(resolved))
            put("calibration.brier", round(cal.brier, 4) if cal.brier is not None else None)
            put("calibration.n_eff", round(cal.n_eff, 2) if cal.n_eff else None)
    except Exception:  # noqa: BLE001 - a gauge is never worth an exception
        pass

    try:
        put("coach.cost_usd_today", _cost_today(cfg))
    except Exception:  # noqa: BLE001
        pass

    # The model layer's calibration (D-089): the fitted inflation and how old
    # the fit is. A drifting inflation across refits, or a fit going stale
    # while the market moves regimes, is exactly the trajectory the report
    # exists to make visible.
    try:
        from . import market_stats as _ms

        art = json.loads(_ms.model_cal_path(Path(cfg.paths.state)).read_text())
        per_h = art.get("per_horizon") or {}
        if "5" in per_h:
            put("model.inflation_5d", float(per_h["5"]))
        fitted = str(art.get("fitted", ""))
        if fitted:
            from datetime import datetime

            age = (ids.utc_now() - datetime.fromisoformat(fitted)).days
            put("model.cal_age_days", age)
    except Exception:  # noqa: BLE001 - no artifact -> no gauge, never a zero
        pass

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


# --- mutation: generating challengers --------------------------------------

MUTATE_PROMPT = """You improve the prompt of an automated system, judged by a \
deterministic scorer you cannot influence. Return ONE replacement prompt.

## The prompt in production now (everything between the two rule lines)
- - - - - - - - - -
{incumbent}
- - - - - - - - - -

## How it is scored
Each candidate this prompt produces is run through fixed gates: it needs usable \
price history, a falsifiable band, a plausible band, a horizon inside the allowed \
window, a bootstrap base probability that is neither a lottery ticket nor vacuous, \
and a tradeable options chain. The reward is the FRACTION of candidates that survive \
every gate. You cannot change the gates.

## What has actually been rejected recently, by gate
{rejections}

## Variants already tried and beaten (do not re-propose these)
{graveyard}

Change exactly ONE thing you can argue will raise the survival fraction, and say \
what in `rationale`. Do not change the output schema, the placeholder names, or the \
percent-move band convention - those are contracts with code.

**The prompt is passed through Python's `.format()`, so EVERY literal curly brace \
must be doubled - `{{` and `}}` - everywhere in the text, not only inside the JSON \
example. `{{X and Y}}` in ordinary prose is a format placeholder and will crash the \
system. The ONLY single braces allowed are these placeholders, which must all survive, \
spelled exactly, with no others added: {placeholders}.**

Respond with ONLY a JSON object:
{{"rationale": "one sentence", "prompt": "the full replacement prompt text"}}
"""

#: Appended when a first attempt fails validation. The check is deterministic and
#: its message names the exact defect, so handing that back is strictly better
#: than spending the next pulse's call rediscovering it - and measured: the very
#: first contract-test run produced `KeyError: ' and '` from braces written in
#: prose, which is precisely the mistake a model corrects when told.
RETRY_SUFFIX = """

## Your previous attempt was REJECTED
{reason}

Fix exactly that and return the corrected JSON object. Change nothing else.
"""

#: Placeholders `muse.MUSE_PROMPT` is formatted with. A challenger missing one
#: raises KeyError in production; a challenger with an EXTRA one raises too.
#: Both are caught here, at generation time, rather than on a live muse run.
MUSE_PLACEHOLDERS = ("today", "n", "k", "concepts", "news", "odds",
                     "earliest", "preferred", "latest")


#: Framing the model tends to echo back around the prompt it was handed.
#: Measured on the first live mutation: the reply copied the delimiter lines
#: verbatim into the challenger text, and nothing downstream would have
#: noticed - the result still formats, still validates, and would have gone
#: into production carrying two lines of this module's own scaffolding. A
#: prompt is a precise artefact; contaminating it with the harness that
#: produced it is a quiet quality leak.
_FENCE_LINES = ("<<<prompt", "prompt", "```", "```json", "```text",
                "- - - - - - - - - -", "---")


def clean_prompt(text: str) -> str:
    """Strip echoed delimiters and code fences from a generated prompt."""
    lines = text.strip().splitlines()
    while lines and lines[0].strip().lower() in _FENCE_LINES:
        lines.pop(0)
    while lines and lines[-1].strip().lower() in _FENCE_LINES:
        lines.pop()
    return "\n".join(lines).strip()


def validate_prompt(text: str, incumbent: str, placeholders: tuple[str, ...],
                    *, must_contain: tuple[str, ...] = ()) -> str:
    """"" if the text is safe to run, else the reason it is not.

    A mutated prompt is a `.format()` template, so a stray brace from a JSON
    example is a live crash on the next muse run. Every failure mode here is
    cheaper to catch now than in production, and the checks are deterministic -
    the model's opinion of its own output is not evidence.
    """
    if not text or len(text) < 200:
        return "too short to be a replacement prompt"
    if len(text) > 2 * len(incumbent):
        return f"{len(text)} chars against an incumbent of {len(incumbent)} - prompt bloat"
    if fingerprint(text) == fingerprint(incumbent):
        return "identical to the incumbent - nothing to test"
    for token in must_contain:
        if token not in text:
            return f"dropped the contract token {token!r}"
    try:
        text.format(**{p: "x" for p in placeholders})
    except (KeyError, IndexError, ValueError) as exc:
        return f"not a safe format template ({type(exc).__name__}: {exc})"
    return ""


def _rejection_digest(rows: list[dict[str, Any]], n: int = 30) -> str:
    fates: dict[str, int] = {}
    for r in _muse_rows(rows, 20):
        for f in (r.get("fates") or []):
            fate = str(f.get("fate", ""))
            if fate.startswith("rejected"):
                key = fate.split(" - ")[0][:80]
                fates[key] = fates.get(key, 0) + 1
    if not fates:
        return "(nothing rejected recently)"
    return "\n".join(f"- {k}  x{v}" for k, v in
                     sorted(fates.items(), key=lambda kv: -kv[1])[:n])


def _graveyard_digest(cfg: Any, lever_name: str, n: int = 4) -> str:
    """Defeated challengers, so the mutation never re-litigates a dead idea.

    D-076 recorded its killed mechanisms for exactly this reason: a rejected
    candidate is worth more as a record than as a thing tried twice.
    """
    dead = [r for r in events(cfg)
            if r.get("kind") == "experiment_closed" and r.get("lever") == lever_name
            and r.get("outcome") in ("refuted", "timeout")]
    if not dead:
        return "(none yet)"
    out = []
    for r in dead[-n:]:
        out.append(f"- {r.get('challenger')} ({r.get('outcome')}, "
                   f"P={r.get('final_posterior')}): "
                   f"{str(r.get('rationale') or '')[:160]}")
    return "\n".join(out)


async def mutate(cfg: Any, st: LeverState, rows: list[dict[str, Any]],
                 journal: Any) -> Variant | None:
    """One validated challenger, or None. Never raises."""
    from .llm import build_model
    from .research import _parse_json_block

    try:
        prompt = MUTATE_PROMPT.format(
            incumbent=st.incumbent.text,
            rejections=_rejection_digest(rows),
            graveyard=_graveyard_digest(cfg, st.lever),
            placeholders=", ".join("{" + p + "}" for p in MUSE_PLACEHOLDERS),
        )
        model = build_model(cfg, role="coach_mutate")
        # Two attempts, because the validator's message names the exact defect
        # and a model corrects a named mistake. A rejected challenger otherwise
        # costs the whole mutation cooldown before anything is tried again.
        attempt_prompt, bad, parsed = prompt, "", None
        for attempt in range(1, MUTATE_ATTEMPTS + 1):
            reply = await model.ainvoke(attempt_prompt)
            text = reply.content if isinstance(reply.content, str) else "\n".join(
                b.get("text", "") for b in reply.content
                if isinstance(b, dict) and b.get("type") == "text")
            parsed = _parse_json_block(text)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else None
            if not isinstance(parsed, dict) or not parsed.get("prompt"):
                bad = "reply did not parse to {rationale, prompt}"
            else:
                candidate = clean_prompt(str(parsed["prompt"]))
                bad = validate_prompt(
                    candidate, st.incumbent.text, MUSE_PLACEHOLDERS,
                    must_contain=("band_low_pct", "band_high_pct", "JSON array"))
                if not bad:
                    vid = f"v{st.next_variant_n}"
                    journal.append("coach_mutation", lever=st.lever, variant=vid,
                                   attempt=attempt,
                                   rationale=str(parsed.get("rationale", ""))[:300])
                    return Variant(id=vid, text=candidate,
                                   since=ids.utc_now().isoformat(), origin="mutation")
            journal.append("coach_mutation_rejected", lever=st.lever, reason=bad,
                           attempt=attempt,
                           rationale=str((parsed or {}).get("rationale", ""))[:200]
                           if isinstance(parsed, dict) else "")
            attempt_prompt = prompt + RETRY_SUFFIX.format(reason=bad)
        return None
    except Exception as exc:  # noqa: BLE001 - a failed mutation costs one pulse
        print(f"[coach] mutation failed: {exc!r}")
        try:
            journal.append("coach_mutation_rejected", lever=st.lever,
                           reason=f"{type(exc).__name__}: {exc}"[:200])
        except Exception:  # noqa: BLE001
            pass
        return None


# --- rule 3: a lever may not be scored by machinery it can move ------------


def _disjoint(cfg: Any, want: Lever) -> str:
    """"" if `want` may open an experiment, else why not.

    The muse's gauntlet gates score muse-prompt trials, so no experiment that
    could MOVE those gates may run at the same time. Enforced by the scheduler
    rather than trusted to sequencing, because the failure would be invisible:
    both experiments would look healthy while each quietly rewrote the other's
    ruler.
    """
    for l in LEVERS:
        if l.name == want.name:
            continue
        st = load_state(cfg, l.name, "")
        if not (st.exp_id and not is_closed(cfg, st.exp_id)):
            continue
        shared = set(l.reward_modules) & set(want.reward_modules)
        if shared:
            return (f"{l.name} has an open experiment scored by "
                    f"{sorted(shared)} - the same machinery this lever moves")
    return ""


# --- the pulse -------------------------------------------------------------


async def pulse(cfg: Any, journal: Any, *, seeds: dict[str, str] | None = None,
                verbose: bool = False) -> dict[str, Any]:
    """One Coach cycle. Called after every muse run and at housekeeping.

    Ordering matters and is deliberate: sentinels run BEFORE promotion, so a
    firing sentinel cannot be beaten to the punch by a promotion in the same
    pulse; the heartbeat is written LAST and unconditionally, so a failure in
    any step above still leaves evidence that the Coach ran.
    """
    seeds = seeds or {}
    state = {"experiments_open": 0, "trials_scored": 0, "trials_scored_today": 0,
             "promotions_today": 0, "sentinels_active": [], "snapshotted": False,
             "opened": None, "closed": None}
    if not enabled(cfg):
        journal.append("coach_run", experiments_open=0, trials_scored=0,
                       trials_scored_today=0, promotions_today=0,
                       sentinels_active=[], disabled=True)
        return state

    rows: list[dict[str, Any]] = []
    try:
        rows = list(journal.read())
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] could not read the journal: {exc!r}")

    day = ids.utc_now().date().isoformat()
    evs = events(cfg)
    # A heartbeat reports what happened SINCE THE LAST HEARTBEAT, not a running
    # total - the same convention `interim_run` (scored) and `exit_run`
    # (triggered) already use. It matters because `health` SUMS this field
    # across every heartbeat row: a running total would be counted once per
    # pulse, so three pulses over seven trials reported "produced 5". The
    # verdict was right either way (the probe only tests > 0) but the number
    # was not, and a health line nobody can trust is one nobody reads.
    last_beat = ""
    for r in reversed(rows):
        if r.get("kind") == "coach_run":
            last_beat = str(r.get("ts", ""))
            break
    state["trials_scored"] = sum(
        1 for r in evs if r.get("kind") == "trial_result"
        and str(r.get("ts", "")) > last_beat)
    state["trials_scored_today"] = sum(
        1 for r in evs if r.get("kind") == "trial_result" and str(r.get("ts", ""))[:10] == day)
    state["promotions_today"] = sum(
        1 for r in evs if r.get("kind") == "experiment_closed"
        and r.get("outcome") == "promoted" and str(r.get("ts", ""))[:10] == day)

    # 1. gauges, on their own cadence
    try:
        if _minutes_since(_last_snapshot_at(cfg)) >= SNAPSHOT_EVERY_MIN:
            _append(metrics_path(cfg), {"kind": "snapshot",
                                        "gauges": snapshot_gauges(cfg, rows)})
            state["snapshotted"] = True
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] gauge snapshot failed: {exc!r}")

    # 2. sentinels
    fired: list[Sentinel] = []
    try:
        for s in SENTINELS:
            hit, value, limit = s.check(cfg, rows)
            if hit:
                fired.append(s)
                state["sentinels_active"].append(s.name)
                _append(events_path(cfg), {
                    "kind": "sentinel_fired", "sentinel": s.name, "value": value,
                    "limit": limit, "action": "revert" if s.reverts else "block_new",
                    "meaning": s.meaning})
                marker(cfg, "sentinel", sentinel=s.name, value=value, limit=limit)
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] sentinel check failed: {exc!r}")

    for lv in LEVERS:
        seed = seeds.get(lv.name, "")
        try:
            st = load_state(cfg, lv.name, seed)
            open_exp = st.exp_id and not is_closed(cfg, st.exp_id)

            # 2b. apply sentinels to this lever
            reverting = [s for s in fired if s.reverts]
            if reverting and open_exp:
                _close(cfg, st, "sentinel_reverted",
                       f"sentinel {reverting[0].name}: {reverting[0].meaning}", journal)
                state["closed"] = "sentinel_reverted"
                open_exp = False
            if fired:
                st.sentinel_block = {"name": fired[0].name, "since": ids.utc_now().isoformat()}
                save_state(cfg, st)
            elif st.sentinel_block:
                st.sentinel_block = None
                save_state(cfg, st)

            # 2c. a human edited state out from under an open experiment
            if open_exp:
                t = tally(cfg, st.exp_id or "")
                if t and st.challenger and t.challenger != st.challenger.id:
                    _close(cfg, st, "operator_override",
                           "lever state no longer matches the open experiment", journal)
                    open_exp = False
                elif (st.paused or st.pinned):
                    _close(cfg, st, "operator_override", st.blocked, journal)
                    open_exp = False

            # 3. promote / refute / timeout
            if open_exp:
                t = tally(cfg, st.exp_id or "")
                if t:
                    outcome, reason = verdict(t, floors(cfg))
                    if outcome == "promoted":
                        _promote(cfg, st, t, reason, journal)
                        state["closed"] = "promoted"
                        state["promotions_today"] += 1
                        open_exp = False
                    elif outcome:
                        _close(cfg, st, outcome, reason, journal, t=t)
                        state["closed"] = outcome
                        open_exp = False

            # 5. open the next experiment
            if not open_exp and not st.blocked and seed:
                clash = _disjoint(cfg, lv)
                if clash:
                    if verbose:
                        print(f"[coach] not opening on {lv.name}: {clash}")
                elif _minutes_since(st.last_mutation_at) >= MUTATE_COOLDOWN_MIN:
                    st.last_mutation_at = ids.utc_now().isoformat()
                    save_state(cfg, st)
                    ch = await mutate(cfg, st, rows, journal)
                    if ch:
                        _open(cfg, st, ch, journal)
                        state["opened"] = ch.id
                        open_exp = True

            if open_exp or (st.exp_id and not is_closed(cfg, st.exp_id)):
                state["experiments_open"] += 1
        except Exception as exc:  # noqa: BLE001 - one lever never breaks the pulse
            print(f"[coach] lever {lv.name} failed this pulse: {exc!r}")

    # 6. the heartbeat, LAST and unconditional
    journal.append("coach_run",
                   experiments_open=state["experiments_open"],
                   trials_scored=state["trials_scored"],
                   trials_scored_today=state["trials_scored_today"],
                   promotions_today=state["promotions_today"],
                   sentinels_active=state["sentinels_active"])
    if verbose:
        print(f"[coach] open={state['experiments_open']} "
              f"trials={state['trials_scored']} (today {state['trials_scored_today']}) "
              f"sentinels={state['sentinels_active'] or 'none'}")
    return state


def _open(cfg: Any, st: LeverState, challenger: Variant, journal: Any) -> None:
    exp_id = ids.journal_id("exp")
    st.challenger = challenger
    st.exp_id = exp_id
    st.next_variant_n = max(st.next_variant_n + 1,
                            int(challenger.id.lstrip("v") or 0) + 1)
    save_state(cfg, st)
    _append(events_path(cfg), {
        "kind": "experiment_opened", "exp_id": exp_id, "lever": st.lever,
        "incumbent": st.incumbent.id, "challenger": challenger.id,
        "challenger_origin": challenger.origin, "challenger_fp": challenger.fingerprint,
        "floors": floors(cfg)})
    journal.append("coach_experiment_opened", lever=st.lever, exp_id=exp_id,
                   incumbent=st.incumbent.id, challenger=challenger.id)
    marker(cfg, "experiment_opened", lever=st.lever,
           detail=f"{st.incumbent.id} vs {challenger.id}")


def _close(cfg: Any, st: LeverState, outcome: str, reason: str, journal: Any,
           t: "Tally | None" = None) -> None:
    """Close WITHOUT promoting. The challenger's full text goes into the event
    so the graveyard needs no second lookup, and so a good idea killed by an
    unrelated sentinel is recoverable by a human reading the log."""
    exp_id, ch = st.exp_id, st.challenger
    _append(events_path(cfg), {
        "kind": "experiment_closed", "exp_id": exp_id, "lever": st.lever,
        "outcome": outcome, "reason": reason,
        "runs": t.runs if t else None,
        "final_posterior": round(t.posterior, 4) if t else None,
        "challenger": ch.id if ch else None,
        "challenger_text": ch.text if ch else None})
    st.challenger, st.exp_id = None, None
    save_state(cfg, st)
    journal.append("coach_experiment_closed", lever=st.lever, exp_id=exp_id,
                   outcome=outcome, reason=reason[:200])
    marker(cfg, "experiment_closed", lever=st.lever, detail=f"{outcome}: {reason[:80]}")


def _promote(cfg: Any, st: LeverState, t: Tally, reason: str, journal: Any) -> None:
    """Swap in the challenger.

    Ordering is crash-safe on purpose: the CLOSE is appended first, then the
    state swap. A crash between them leaves a `promoted` close whose lever
    state still shows the old incumbent - which `reconcile` detects and
    re-applies, because the append-only log is the truth and the state file is
    a cache of it.
    """
    ch = st.challenger
    if ch is None:
        return
    _append(events_path(cfg), {
        "kind": "experiment_closed", "exp_id": st.exp_id, "lever": st.lever,
        "outcome": "promoted", "reason": reason, "runs": t.runs,
        "final_posterior": round(t.posterior, 4),
        "challenger": ch.id, "challenger_text": ch.text,
        "promoted_from": st.incumbent.id})
    st.previous = st.incumbent
    st.incumbent = Variant(id=ch.id, text=ch.text, since=ids.utc_now().isoformat(),
                           origin=ch.origin)
    st.challenger, st.exp_id = None, None
    save_state(cfg, st)
    journal.append("coach_promotion", lever=st.lever, promoted=ch.id,
                   previous=st.previous.id, reason=reason[:200])
    marker(cfg, "promotion", lever=st.lever,
           detail=f"{st.previous.id} -> {ch.id}")
    print(f"[coach] PROMOTED {st.lever}: {st.previous.id} -> {ch.id} ({reason})")


def reconcile(cfg: Any, seeds: dict[str, str] | None = None) -> list[str]:
    """Re-apply a promotion that was logged but never swapped into state.

    Idempotent: a promotion whose incumbent already matches is skipped. The
    event log is the ground truth and the state file is a cache of it - the
    same relationship the journal has with everything else here.
    """
    seeds, applied = seeds or {}, []
    for lv in LEVERS:
        st = load_state(cfg, lv.name, seeds.get(lv.name, ""))
        closes = [r for r in events(cfg)
                  if r.get("kind") == "experiment_closed" and r.get("lever") == lv.name
                  and r.get("outcome") == "promoted"]
        if not closes:
            continue
        last = closes[-1]
        want = str(last.get("challenger") or "")
        if want and st.incumbent.id != want and last.get("challenger_text"):
            st.previous = st.incumbent
            st.incumbent = Variant(id=want, text=str(last["challenger_text"]),
                                   since=str(last.get("ts", "")), origin="mutation")
            st.challenger, st.exp_id = None, None
            save_state(cfg, st)
            applied.append(f"{lv.name}: {st.previous.id} -> {want}")
    return applied
