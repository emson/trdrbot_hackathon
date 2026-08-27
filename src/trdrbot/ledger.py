"""Pre-registration ledger and unconditional forecasts (D-052).

Two ideas from the technique research that turn out to be one mechanism:
**record the forecast even when you do not act on it.**

**Why pre-registration.** A human quant tests maybe twenty ideas a year; an LLM
generates two hundred plausible theses in an afternoon and silently discards
the ones that look bad. Under a TRUE Sharpe of zero, the expected maximum
Sharpe across N filtered trials is 1.19 sigma at N=5, **1.90 sigma at N=20**,
2.53 at N=100 - and the competence ladder would happily promote that. The
ledger supplies the trial count N without which a Deflated Sharpe Ratio cannot
be computed at all. It cannot be reconstructed later, which is the whole point:
a thesis considered today and unrecorded is gone.

**Why unconditional forecasts.** Our size ladder gates on calibration, and the
honest thresholds are brutal - roughly 50 resolved forecasts before calibration
is *measured* rather than guessed, 152 before a 60% hit rate is distinguishable
from a coin flip. At 1-5 concurrent positions, trade-level observations will
never get there. But forecasts are far cheaper than trades: the agent can
predict what happens to a setup it DECLINES, at zero capital risk and zero
execution cost. It has already declined about ten times with detailed,
falsifiable reasoning that was simply thrown away.

**The design decision that matters:** pre-registration is AUTOMATIC. Every
thesis passed to `simulate_experiments` is registered from inside the tool -
the agent cannot forget, cannot skip it under pressure, and pays no extra
prompt burden. Same "derive, do not declare" principle that made position risk
trustworthy (D-037). A separate tool exists for standalone predictions the
agent wants to put on the record.

Resolution is deterministic: a forecast is scoreable only if it carries a price
band and a horizon, so at the horizon we fetch the spot and check it. An
unfalsifiable forecast is refused at write time rather than silently kept -
that is the same discipline `Thesis.holds_at` already enforces.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

#: How a forecast came to exist. `thesis` rows are auto-registered from
#: simulate_experiments; `standalone` rows are the agent putting a view on
#: record without trading it.
THESIS, STANDALONE = "thesis", "standalone"


@dataclass
class Entry:
    id: str
    kind: str                 # thesis | standalone
    created: str
    underlying: str
    claim: str
    probability: float        # stated P(the band holds at the horizon)
    horizon: str              # YYYY-MM-DD
    band_low: float | None
    band_high: float | None
    traded: bool = False      # did this thesis become a position?
    position_id: str | None = None
    #: resolution
    outcome: bool | None = None
    resolved_at: str | None = None
    price_at_horizon: float | None = None
    notes: str = ""

    def scoreable(self) -> bool:
        return self.band_low is not None or self.band_high is not None

    def holds_at(self, price: float) -> bool:
        if self.band_low is not None and price < self.band_low:
            return False
        if self.band_high is not None and price > self.band_high:
            return False
        return True

    def matured(self, today: date | None = None) -> bool:
        try:
            return date.fromisoformat(self.horizon) <= (today or date.today())
        except (ValueError, TypeError):
            return False


class Ledger:
    """Append-only. Every thesis the agent ever formed, traded or not."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: list[Entry] = []
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._items.append(Entry(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue

    def _append(self, e: Entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(e)) + "\n")

    def _rewrite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(asdict(e)) + "\n" for e in self._items))

    def register(
        self, *, kind: str, underlying: str, claim: str, probability: float,
        horizon: str, band_low: float | None, band_high: float | None,
        notes: str = "",
    ) -> Entry | None:
        """Record a forecast. Returns None if it could never be scored.

        Refusing at write time rather than storing an unscoreable row keeps the
        trial count N honest: a thesis that can never be judged is not evidence
        of anything, and counting it would make the multiple-testing correction
        *more* punitive for no informational gain.
        """
        from . import ids

        if band_low is None and band_high is None:
            return None
        e = Entry(
            id=ids.journal_id("fc"), kind=kind, created=ids.utc_now().isoformat(),
            underlying=underlying.upper(), claim=claim[:400],
            probability=max(0.0, min(1.0, probability)), horizon=horizon,
            band_low=band_low, band_high=band_high, notes=notes[:400],
        )
        # Do not double-register the same thesis on repeated simulate calls in
        # one decide cycle - the agent often simulates twice while comparing.
        for prior in self._items:
            if (prior.outcome is None and prior.underlying == e.underlying
                    and prior.horizon == e.horizon
                    and prior.band_low == e.band_low and prior.band_high == e.band_high):
                return prior
        self._items.append(e)
        self._append(e)
        return e

    def mark_traded(self, underlying: str, horizon: str, position_id: str) -> bool:
        """Link a registered thesis to the position it became."""
        for e in reversed(self._items):
            if (e.underlying == underlying.upper() and e.horizon == horizon
                    and not e.traded):
                e.traded, e.position_id = True, position_id
                self._rewrite()
                return True
        return False

    def matured_unresolved(self, today: date | None = None) -> list[Entry]:
        return [e for e in self._items
                if e.outcome is None and e.scoreable() and e.matured(today)]

    def resolve(self, entry_id: str, price: float, at: str) -> Entry | None:
        for e in self._items:
            if e.id == entry_id and e.outcome is None:
                e.outcome = e.holds_at(price)
                e.price_at_horizon = price
                e.resolved_at = at
                self._rewrite()
                return e
        return None

    # -- reporting ------------------------------------------------------

    def all(self) -> list[Entry]:
        return list(self._items)

    def resolved(self) -> list[Entry]:
        return [e for e in self._items if e.outcome is not None]

    def trials(self) -> int:
        """N for a multiple-testing correction: every thesis ever considered."""
        return len(self._items)

    def summary(self) -> dict[str, Any]:
        res = self.resolved()
        hits = sum(1 for e in res if e.outcome)
        traded = sum(1 for e in self._items if e.traded)
        return {
            "trials": self.trials(),
            "traded": traded,
            "declined": self.trials() - traded,
            "resolved": len(res),
            "hit_rate": (hits / len(res)) if res else None,
            "pending": sum(1 for e in self._items if e.outcome is None),
        }


def as_forecasts(entries: list[Entry]) -> list[Any]:
    """Resolved ledger entries as calibration Forecasts.

    This is the point of the whole module: forecasts on setups we DECLINED
    score the agent's judgement at zero capital risk, and they are the only
    realistic route to a calibration sample that means anything.
    """
    from .calibration import Forecast

    return [
        Forecast(position_id=e.position_id or e.id, probability=e.probability,
                 outcome=bool(e.outcome), resolved_at=e.resolved_at)
        for e in entries if e.outcome is not None
    ]
