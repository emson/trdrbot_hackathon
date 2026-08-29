"""The A/B decision: a Beta posterior, a tally, and one verdict function.

Pure and dependency-free by construction - `math` only, a fixed grid, no
sampling - so the same counts always give the same answer and a test can pin
it exactly. Split out of the 1,200-line coach module because this is the part
that decides every promotion the system ever makes, and it should be readable
and testable without a filesystem anywhere near it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .state import (
    CAP_RUNS,
    FUTILITY_AT,
    FUTILITY_MIN_RUNS,
    MIN_CANDIDATES,
    MIN_RUNS,
    PROMOTE_AT,
    events,
)

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

    def add(self, inc: dict[str, Any], ch: dict[str, Any]) -> None:
        """Fold one paired result in.

        Used by the replay below AND by `record_trial`, so the posterior a row
        RECORDS is computed by the same arithmetic that later reads it back.
        It was not: `record_trial` tallied before appending the row it
        decorates, so every `trial_result` carried the posterior of the
        previous state and the first row of every experiment read exactly 0.5
        no matter what it had just measured (D-093).
        """
        if ch.get("voided"):
            self.voided += 1
            return
        self.runs += 1
        self.s_i += int(inc.get("survived") or 0)
        self.f_i += int(inc.get("failed") or 0)
        self.s_c += int(ch.get("survived") or 0)
        self.f_c += int(ch.get("failed") or 0)


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
    # A run_nonce is unique per muse run, and the field existed from the start
    # with nothing reading it. It has to be read: `muse.run` derives the nonce
    # from today's `muse` journal rows but calls `record_trial` BEFORE
    # appending its own row, so a crash in that window makes the next run
    # compute the SAME nonce and write a second trial_result for one run. Both
    # then counted toward `runs`, the successes, the failures and therefore the
    # posterior - inflating the evidence for whichever arm happened to be
    # duplicated.
    seen_nonces: set[Any] = set()
    for r in rows:
        if r.get("kind") != "trial_result" or r.get("exp_id") != exp_id:
            continue
        nonce = r.get("run_nonce")
        if nonce is not None and nonce in seen_nonces:
            t.voided += 1
            continue
        seen_nonces.add(nonce)
        t.add(r.get("incumbent") or {}, r.get("challenger") or {})
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


