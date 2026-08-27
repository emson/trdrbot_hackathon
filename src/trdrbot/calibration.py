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


@dataclass
class Forecast:
    position_id: str
    probability: float  # stated P(profitable) at decision time
    outcome: bool | None = None  # None until resolved
    resolved_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "probability": self.probability,
            "outcome": self.outcome,
            "resolved_at": self.resolved_at,
        }


@dataclass
class Calibration:
    n: int
    brier: float | None
    reliability: float | None
    resolution: float | None
    uncertainty: float | None
    base_rate: float | None

    def verdict(self) -> str:
        """Plain-language read - the point of the exercise, not the raw numbers."""
        if self.n < 3 or self.brier is None:
            return f"only {self.n} resolved forecast(s) - too few to judge calibration"
        parts = [f"Brier {self.brier:.3f} over {self.n} forecasts"]
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
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    d = json.loads(line)
                    self._items.append(Forecast(**d))

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "\n".join(json.dumps(f.to_dict()) for f in self._items) + "\n"
        )

    def record(self, position_id: str, probability: float) -> None:
        probability = max(0.0, min(1.0, probability))
        self._items.append(Forecast(position_id=position_id, probability=probability))
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

    def score(self) -> Calibration:
        return score(self.resolved())


def score(forecasts: list[Forecast]) -> Calibration:
    """Brier score with Murphy's three-way decomposition."""
    n = len(forecasts)
    if n == 0:
        return Calibration(0, None, None, None, None, None)

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
    bins: dict[float, list[float]] = {}
    for p, o in zip(probs, outs):
        centre = min(n_bins - 1, int(p / width)) * width + width / 2
        bins.setdefault(round(centre, 4), []).append(o)

    reliability = sum(
        len(os_) * (sum(pb for pb in [b]) - (sum(os_) / len(os_))) ** 2
        for b, os_ in bins.items()
    ) / n
    resolution = sum(
        len(os_) * ((sum(os_) / len(os_)) - base) ** 2 for b, os_ in bins.items()
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
        for os_ in bins.values() if len(os_) > 1
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
    )
