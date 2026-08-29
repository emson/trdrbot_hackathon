"""D-013 - forecast calibration. Deterministic, no LLM.

elfsim turned out to be spec-only with zero implementation (notes/004 §10.2),
so this implements the one genuinely concrete and differentiated slice of its
design: the Brier/Murphy calibration loop.

Most trading systems track P&L. Almost none track whether their own stated
confidence was *justified*. The difference matters: an agent that says "70%
confident" and is right 70% of the time is well-calibrated and can be trusted
to size positions; one that says 70% and is right 40% of the time is
systematically overconfident, and that is a fixable, learnable defect rather
than bad luck.

Brier score = mean((forecast - outcome)^2), lower is better, 0 is perfect.
Murphy's decomposition splits it into:
    reliability  - do stated probabilities match observed frequencies?
                   (this is the overconfidence signal; lower is better)
    resolution   - do forecasts actually discriminate between outcomes?
                   (higher is better; 0 means always predicting the base rate)
    uncertainty  - the irreducible variance of the outcomes themselves
Brier = reliability - resolution + uncertainty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import store


@dataclass
class Forecast:
    position_id: str
    probability: float  # stated P(profitable) at decision time
    outcome: bool | None = None  # None until resolved
    resolved_at: str | None = None
    #: What this forecast is ABOUT - the underlying. Carried only so the
    #: sample's concentration can be measured; never used for scoring.
    subject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "probability": self.probability,
            "outcome": self.outcome,
            "resolved_at": self.resolved_at,
            "subject": self.subject,
        }


#: Below this share, the sample is concentrated enough that its face value
#: materially overstates the evidence, and every surface says so.
CONCENTRATION_WARN = 0.6


def effective_n(forecasts: list[Forecast]) -> float | None:
    """Independent-equivalent sample size: inverse-Herfindahl over subjects.

    `n` counts forecasts. This counts BETS. Seventeen SPY theses in one week
    are not seventeen pieces of evidence, and the difference is not academic -
    measured on this system's own ledger, 38 theses came to **4.2** effective,
    and the 9 with a positive Kelly came to **2.0**, so sizing each at its
    individual Kelly would have overbet by 4.6x (D-080).

    `(sum n_i)^2 / sum(n_i^2)` - the effective number of categories. Equal to
    `n` when every forecast is about a different underlying, and to 1 when they
    are all about the same one.

    Deliberately REPORTED, never used as a gate. Calibration asks "when I say
    70%, does it happen 70% of the time", and repeated forecasts on one name at
    different bands and horizons are genuinely separate judgements even when
    their outcomes correlate. Concentration is a reason to distrust
    GENERALISING from the sample, which is a judgement for the reader - and
    D-009's report-don't-gate posture is the house rule for exactly that.
    A forecast with no recorded subject counts as its own singleton.
    """
    if not forecasts:
        return None
    counts: dict[str, int] = {}
    for i, f in enumerate(forecasts):
        key = f.subject.upper() if f.subject else f"__unknown_{i}"
        counts[key] = counts.get(key, 0) + 1
    denom = sum(v * v for v in counts.values())
    return (len(forecasts) ** 2) / denom if denom else None


@dataclass
class Calibration:
    n: int
    brier: float | None
    reliability: float | None
    resolution: float | None
    uncertainty: float | None
    base_rate: float | None
    #: Independent-equivalent sample size (see `effective_n`). None when there
    #: is nothing to measure.
    n_eff: float | None = None

    @property
    def concentration(self) -> float | None:
        """n_eff as a share of n. 1.0 = every forecast a different name."""
        if not self.n or self.n_eff is None:
            return None
        return self.n_eff / self.n

    def sample_note(self) -> str:
        """One line on how much this sample is really worth."""
        if self.n_eff is None or not self.n:
            return f"{self.n} forecast(s)"
        base = f"{self.n} forecast(s), {self.n_eff:.1f} effective"
        share = self.concentration
        if share is not None and share < CONCENTRATION_WARN:
            return (base + f" ({share:.0%} of face value - the sample is concentrated "
                           f"in a few names, so it says less about NEW ones than the "
                           f"count suggests)")
        return base

    def verdict(self) -> str:
        """Plain-language read - the point of the exercise, not the raw numbers."""
        if self.n < 3 or self.brier is None:
            return f"only {self.n} resolved forecast(s) - too few to judge calibration"
        parts = [f"Brier {self.brier:.3f} over {self.sample_note()}"]
        if self.reliability is not None and self.reliability > 0.05:
            parts.append("poorly calibrated - stated confidence does not match observed frequency")
        elif self.reliability is not None:
            parts.append("well calibrated")
        if self.resolution is not None and self.resolution < 0.01:
            parts.append("no discrimination - forecasts are not distinguishing winners from losers")
        return "; ".join(parts)


class CalibrationStore:
    """Append-only forecast ledger, resolved in place at position close."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: list[Forecast] = []
        if not path.exists():
            return
        skipped = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                # Ignore unknown keys rather than raising on them: a field
                # added to Forecast later must not make every OLD row
                # unreadable, and `_flush` rewrites the whole file, so a row
                # skipped on load is a row DELETED on the next write.
                self._items.append(
                    Forecast(**{k: v for k, v in d.items()
                                if k in Forecast.__dataclass_fields__})
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                skipped += 1
        if skipped:
            # Loud, because these rows are the calibration record itself.
            print(f"[calibration] skipped {skipped} unreadable forecast(s) "
                  f"in {path.name} - they will be dropped on the next write")

    def _flush(self) -> None:
        # Atomic: this rewrites the WHOLE calibration record on every
        # record() and every resolve(), so a crash mid-write would truncate
        # the earned forecast history rather than lose one row.
        store.write_atomic(
            self.path, "\n".join(json.dumps(f.to_dict()) for f in self._items) + "\n"
        )

    def record(self, position_id: str, probability: float, subject: str = "") -> None:
        probability = max(0.0, min(1.0, probability))
        self._items.append(Forecast(position_id=position_id, probability=probability,
                                    subject=subject.upper()))
        self._flush()

    def resolve(self, position_id: str, outcome: bool, at: str) -> bool:
        for f in self._items:
            if f.position_id == position_id and f.outcome is None:
                f.outcome, f.resolved_at = outcome, at
                self._flush()
                return True
        return False

    def resolved(self) -> list[Forecast]:
        return [f for f in self._items if f.outcome is not None]

    def pending(self) -> list[Forecast]:
        return [f for f in self._items if f.outcome is None]

    def score(self, extra: list[Forecast] | None = None) -> Calibration:
        """Calibration over closed positions PLUS any extra resolved forecasts.

        The extras are ledger entries - predictions on setups the agent
        declined to trade (D-052). They cost nothing, they score exactly the
        same judgement, and at 1-5 concurrent positions they are the only way
        this sample ever reaches a size where calibration means anything.
        """
        return score(self.resolved() + list(extra or []))


def score(forecasts: list[Forecast]) -> Calibration:
    """Brier score with Murphy's three-way decomposition."""
    n = len(forecasts)
    if n == 0:
        return Calibration(0, None, None, None, None, None, None)
    n_eff = effective_n(forecasts)

    probs = [f.probability for f in forecasts]
    outs = [1.0 if f.outcome else 0.0 for f in forecasts]

    brier = sum((p - o) ** 2 for p, o in zip(probs, outs)) / n
    base = sum(outs) / n
    uncertainty = base * (1 - base)

    # Murphy's decomposition needs forecasts grouped by stated probability.
    # Round to a coarse bin so near-identical forecasts share a group -
    # with a handful of trades, per-unique-value grouping would make every
    # group size 1 and reliability trivially (and misleadingly) zero.
    # Bin width adapts to sample size (D-050). Fixed 0.1 bins leave ~4
    # forecasts per bin at n=20, and a bin of one cannot have its sampling
    # variance estimated at all - so it escapes the bias correction entirely
    # and re-imports the very bias the correction exists to remove. Target
    # roughly 8 forecasts per bin, between 2 and 10 bins.
    n_bins = max(2, min(10, n // 8))
    width = 1.0 / n_bins
    # Each bin keeps BOTH halves of the pair. Reliability asks "when you said
    # X, how often did it happen" - so it needs the mean STATED probability in
    # the bin, not the bin's geometric centre. This used to read
    # `sum(pb for pb in [b])`, which is just `b`, the centre. At the sample
    # sizes this system actually runs at that is not a rounding error: n_bins
    # is 2 below n=24, so every forecast under 0.5 was scored as if it had
    # been stated at 0.25 and everything above it at 0.75.
    #
    # Measured against the live record - one resolved forecast, stated 0.38,
    # outcome true: the centre form returned reliability 0.5625 where the
    # honest figure is 0.3844. Measured on a synthetic agent stating 0.95 and
    # right half the time at n=16: 0.019 against a true 0.150, which PASSES the
    # MATURE gate (<0.04) that exists to catch precisely that agent. The error
    # runs both ways - it also punishes an underconfident forecaster - and it
    # feeds `sizing.shrink_probability`, where an understated reliability buys
    # real size. It also breaks the decomposition identity
    # (brier = reliability - resolution + uncertainty), which is now pinned as
    # a test, because an identity that holds is the cheapest possible guard
    # against this class of error returning.
    bins: dict[float, tuple[list[float], list[float]]] = {}
    for p, o in zip(probs, outs):
        centre = min(n_bins - 1, int(p / width)) * width + width / 2
        ps_, os_ = bins.setdefault(round(centre, 4), ([], []))
        ps_.append(p)
        os_.append(o)

    reliability = sum(
        len(os_) * ((sum(ps_) / len(ps_)) - (sum(os_) / len(os_))) ** 2
        for ps_, os_ in bins.values()
    ) / n
    resolution = sum(
        len(os_) * ((sum(os_) / len(os_)) - base) ** 2 for _, os_ in bins.values()
    ) / n

    # Ferro-Fricker bias correction (D-050). The empirical decomposition
    # OVERSTATES reliability at small n, because each bin's observed frequency
    # is itself estimated from few outcomes and its sampling variance lands in
    # the reliability term. Measured on this very code: a PERFECTLY calibrated
    # agent (true reliability 0) scored 0.072 at n=15 and 0.061 at n=20 -
    # which, against a promotion gate demanding <0.05, blocked a flawless
    # agent 58-67% of the time. Worse, the bias shrinks as n grows, so it
    # would have looked exactly like "the agent is learning" when nothing had
    # changed. Unbiased estimator of p(1-p) from m samples is m/(m-1) * o(1-o),
    # so the variance leaking into each bin is o(1-o)/(m-1).
    #   Ferro & Fricker, QJRMS 2012.
    within = sum(
        len(os_) * (sum(os_) / len(os_)) * (1 - sum(os_) / len(os_)) / (len(os_) - 1)
        for _, os_ in bins.values() if len(os_) > 1
    ) / n
    overall = base * (1 - base) / (n - 1) if n > 1 else 0.0
    # Reliability cannot truly be negative; clamping keeps the gate honest
    # rather than rewarding an over-correction on a tiny sample.
    reliability = max(0.0, reliability - within)
    resolution = max(0.0, resolution - within + overall)
    uncertainty = uncertainty + overall

    return Calibration(
        n=n,
        brier=brier,
        reliability=reliability,
        resolution=resolution,
        uncertainty=uncertainty,
        base_rate=base,
        n_eff=n_eff,
    )
