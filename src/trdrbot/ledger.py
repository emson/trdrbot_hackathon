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
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import ids, optmath, store

#: How a forecast came to exist. `thesis` rows are auto-registered from
#: simulate_experiments; `standalone` rows are the agent putting a view on
#: record without trading it.
THESIS, STANDALONE = "thesis", "standalone"

#: What `band_low`/`band_high` are bounds ON.
#:
#: Every entry was implicitly a PRICE claim: resolution fetched spot and asked
#: whether the band held. Meanwhile the agent states a realized-vol view in
#: prose every cycle ("I forecast 8.5%; the condors needed sub-7.5%") and
#: nothing scored it, so the most falsifiable thing it says moved no
#: calibration and earned no size - which is most of the point of saying it
#: (I-14).
#:
#: Vol bands are in PERCENT, annualized, matching the units the agent reads
#: them in: the stats block quotes "realized vol 21d 12.3%", and a forecast
#: must be scored in the units it was stated in or the seam is a units bug
#: waiting to happen.
PRICE_BAND, REALIZED_VOL_PCT = "price_band", "realized_vol_pct"


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
    #: Did the AGENT state this probability, or is it a pre-registration
    #: placeholder? Only stated forecasts may score calibration (D-062).
    probability_stated: bool = True
    traded: bool = False      # did this thesis become a position?
    position_id: str | None = None
    #: What the band is a claim about. Defaults to the price band every
    #: historical row implicitly was, so nothing on disk needs rewriting.
    metric: str = PRICE_BAND
    #: resolution
    outcome: bool | None = None
    resolved_at: str | None = None
    #: The resolved value the band was checked against. Wire name kept because
    #: it is on every row ever written; for a `realized_vol_pct` entry it holds
    #: the annualized realized vol in percent, not a price.
    price_at_horizon: float | None = None
    notes: str = ""
    #: Which gate threw this candidate out, if one did. Structured rather than
    #: buried in `notes`, because the useful question is about the GATES:
    #: a rejected thesis still carries a band and a horizon, so it still
    #: resolves - and comparing "we refused it" against "it would have held"
    #: is a scored test of the gate's own threshold. That scores the SYSTEM,
    #: never the agent; the reject is not a claim anybody made, which is why
    #: `probability_stated` stays False (D-080).
    rejected_by: str = ""
    #: Which prompt/policy VARIANT produced this thesis (D-088). Empty for
    #: everything written before the Coach existed, and for every source that
    #: has no lever. This is the join the outcome audit needs: a variant
    #: promoted on a fast proximate reward (surviving the gates) still has to
    #: be checked against what its theses actually did at horizon, and that
    #: comparison is impossible unless the variant is stamped at registration
    #: time. Provenance is the part of A/B testing with a deadline (D-045).
    variant: str = ""

    def scoreable(self) -> bool:
        return self.band_low is not None or self.band_high is not None

    def holds_at(self, price: float) -> bool:
        """Whether the claim held. Only ever called on a `scoreable()` entry,
        so a band-less row (which the shared rule reports as None) resolves
        FALSE rather than vacuously true - it made no checkable claim."""
        return optmath.band_holds(price, self.band_low, self.band_high) is True

    def matured(self, today: date | None = None) -> bool:
        """Has the horizon's SESSION ended - not merely its UTC date begun.

        This compared against `ids.today()`, the UTC date. Housekeeping runs
        while the market is closed, which in the evening ET is already the next
        UTC day - so a forecast for Wednesday matured on Tuesday evening and was
        scored against Tuesday's close. Measured live (D-107): 94 of 95 resolved
        entries, and 71 of 71 in the calibration sample that drives the ladder,
        were scored before 16:00 ET on their own horizon date. `market_today`
        exists for exactly this and is the clock every other date decision in
        the system uses.
        """
        try:
            return date.fromisoformat(self.horizon) <= (today or ids.market_today())
        except (ValueError, TypeError):
            return False


class Ledger:
    """Append-only. Every thesis the agent ever formed, traded or not."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: list[Entry] = []
        skipped = 0
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    # Unknown keys are IGNORED, not fatal. `_rewrite` rewrites
                    # the whole file, so a row skipped on load is a row DELETED
                    # on the next mark_stated - which made adding one field to
                    # Entry a silent way to destroy the pre-registration
                    # history the multiple-testing correction depends on.
                    self._items.append(
                        Entry(**{k: v for k, v in d.items()
                                 if k in Entry.__dataclass_fields__})
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    skipped += 1
        if skipped:
            # Loud: every skipped row is a pre-registered trial that the next
            # rewrite will delete, and the trial count N is what the
            # multiple-testing correction rests on.
            print(f"[ledger] skipped {skipped} unreadable row(s) in {path.name} - "
                  f"they will be dropped on the next write")

    def _append(self, e: Entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(e)) + "\n")

    def _rewrite(self) -> None:
        # Atomic: fires once per candidate per gate during a muse run, over
        # the whole file. `ledger.jsonl.bak-before-repair` on disk is what this
        # class of failure looks like when it lands.
        store.write_atomic(
            self.path, "".join(json.dumps(asdict(e)) + "\n" for e in self._items))

    def register(
        self, *, kind: str, underlying: str, claim: str, probability: float,
        horizon: str, band_low: float | None, band_high: float | None,
        notes: str = "", probability_stated: bool = True, variant: str = "",
        metric: str = PRICE_BAND,
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
            probability_stated=probability_stated, variant=variant,
            band_low=band_low, band_high=band_high, notes=notes[:400],
            metric=metric,
        )
        # Do not double-register the same thesis on repeated simulate calls in
        # one decide cycle - the agent often simulates twice while comparing.
        #
        # `probability_stated` is part of the identity, and it has to be. A
        # pre-registered thesis carries an unstated 0.5 placeholder; a
        # standalone forecast on the same name, horizon and band carries the
        # agent's real number. Matching across that boundary returned the
        # PLACEHOLDER for a genuine forecast - so the stated probability was
        # never written, `record_forecast` reported back "50%" for a 67% call,
        # and the row stayed invisible to calibration because placeholders are
        # excluded from it. That is D-062's exact symptom ("if the system log
        # shows 50% instead of 67%, the intent is 0.67") surviving in the one
        # place D-062 did not look. It has not bitten live only because the
        # agent has always drawn its standalone bands differently.
        for prior in self._items:
            if (prior.outcome is None and prior.underlying == e.underlying
                    and prior.horizon == e.horizon
                    and prior.probability_stated == e.probability_stated
                    and prior.metric == e.metric
                    and prior.band_low == e.band_low and prior.band_high == e.band_high):
                return prior
        self._items.append(e)
        self._append(e)
        return e

    def mark_rejected(self, entry_id: str, reason: str) -> bool:
        """Record which gate refused this candidate, keeping it as a trial."""
        for e in self._items:
            if e.id == entry_id:
                e.rejected_by = reason[:120]
                self._rewrite()
                return True
        return False

    def mark_stated(self, entry_id: str) -> bool:
        """Promote a trial to a SCOREABLE claim - it survived every gate.

        Registration and belief are different events, and conflating them
        polluted half the calibration sample. A candidate is pre-registered the
        moment it exists, because the multiple-testing correction needs the
        trials that FAILED (D-052) - but a trial the system then threw out is
        not a claim anybody made about the world, and scoring it teaches the
        agent nothing except how badly its own rejects perform.

        Measured on the live ledger before this existed: the muse registered
        15 candidates with `probability_stated=True` and its own gates rejected
        13 of them - bands 3x away from spot, base rates of 0% or 100%, a
        horizon in the past. **50% of the incoming calibration sample was
        material the system had already refused.** Most would resolve FALSE,
        cratering reliability; the vacuous one-sided ones would resolve TRUE,
        inflating it. Both directions move real size, on evidence of nothing.

        So a claim now earns the right to be scored, rather than being born
        with it.
        """
        for e in self._items:
            if e.id == entry_id and not e.probability_stated:
                e.probability_stated = True
                self._rewrite()
                return True
        return False

    def mark_traded(self, underlying: str, horizon: str, position_id: str,
                    probability: float | None = None) -> bool:
        """Link a registered thesis to the position it became - and STATE it.

        Trading a thesis is the strongest statement of a probability the agent
        can make: it is the number `size_position` was handed as
        `stated_confidence`, and money went behind it. Yet this used to leave
        the entry at its 0.5 pre-registration placeholder with
        `probability_stated=False`, so the theses the agent actually bet on
        were the ONLY theses excluded from the calibration record that gates
        how much it may bet next. Measured live (D-105): 13 `thesis` entries,
        2 traded, 0 stated - one already resolved TRUE and did not count,
        while 105 muse candidates it never touched did.

        `probability` is the agent's own `confidence` from `record_position`.
        None keeps the old behaviour for the one caller that has no number.
        """
        for e in reversed(self._items):
            if (e.underlying == underlying.upper() and e.horizon == horizon
                    and not e.traded):
                e.traded, e.position_id = True, position_id
                if probability is not None:
                    e.probability = float(probability)
                    e.probability_stated = True
                self._rewrite()
                return True
        return False

    def matured_unresolved(self, today: date | None = None) -> list[Entry]:
        return [e for e in self._items
                if e.outcome is None and e.scoreable() and e.matured(today)]

    def resolve(self, entry_id: str, value: float, at: str) -> Entry | None:
        """Score one entry against the resolved value of its metric - a price
        for a price band, an annualized realized vol in percent for a vol
        band. `holds_at` needs no metric branch: a band is a band."""
        for e in self._items:
            if e.id == entry_id and e.outcome is None:
                e.outcome = e.holds_at(value)
                e.price_at_horizon = value
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
                 outcome=bool(e.outcome), resolved_at=e.resolved_at,
                 # Carried so concentration is measurable: 17 SPY theses in one
                 # week are not 17 pieces of evidence (D-081).
                 subject=e.underlying)
        # Only forecasts the agent actually STATED. A pre-registered thesis
        # carries a 0.5 placeholder so the trial can be counted for
        # multiple-testing purposes - feeding that into calibration would score
        # the agent on a prediction it never made, and 0.5 is the most
        # corrosive possible value: maximally uninformative, and it drags every
        # real forecast toward the base rate. The agent caught this itself,
        # writing "if the system log shows 50% instead of 67%, the intent is
        # 0.67" (D-062).
        for e in entries if e.outcome is not None and e.probability_stated
    ]


# ------------------------------------------------------------ gate regret

#: `rejected_by` is prose, written by whichever gate refused the candidate, on
#: an append-only ledger - so the GATE is recovered from the text rather than
#: stored beside it, and every historical row classifies the same way a new one
#: does. Order matters only where two needles could both match; none do today.
#: A string no needle matches is "other", which is reported, never dropped: a
#: gate that starts rejecting under a wording nobody classified must show up as
#: a growing "other", not vanish.
GATES: tuple[tuple[str, str], ...] = (
    ("no usable price history", "price_history"),
    ("unfalsifiable", "unfalsifiable"),
    ("not a plausible price", "implausible_band"),
    ("outside 1-10 days", "horizon_window"),
    ("resolves too late", "horizon_window"),
    ("lottery ticket", "lottery"),
    ("model agrees", "vacuous"),
    ("no options chain", "no_chain"),
    ("error:", "error"),
)

#: Below this many RESOLVED rejections a gate's regret is not a measurement -
#: the same floor the ladder uses for attribution (`competence.
#: MIN_ATTR_VERDICTS`), for the same reason: a rate over three outcomes cannot
#: discriminate, and reporting it as if it could is how a threshold gets
#: "tuned" on noise.
MIN_GATE_RESOLVED = 5


def gate_of(rejected_by: str) -> str:
    """Which gate a `rejected_by` string came from. 'other' if none match."""
    for needle, key in GATES:
        if needle in rejected_by:
            return key
    return "other"


@dataclass
class GateRegret:
    """What one gate refused, and how much of it would have held (I-73, D-104).

    A rejected candidate is registered with `probability_stated=False`, so it
    never enters calibration - and it still carries a band and a horizon, so
    it still RESOLVES. "We refused it and it would have held" is therefore a
    score for the gate's threshold computed from outcomes the gate cannot
    influence: the only self-improvement signal in this system that does not
    violate the measured/measurer rule (specs/notes/015). Recorded since D-081.
    Computed here for the first time.
    """

    gate: str
    rejected: int
    resolved: int
    held: int

    @property
    def regret(self) -> float | None:
        """Share of this gate's resolved refusals that would have held."""
        return self.held / self.resolved if self.resolved else None

    @property
    def measured(self) -> bool:
        return self.resolved >= MIN_GATE_RESOLVED

    def read(self, baseline: float | None) -> str:
        """One honest line. A gate whose refusals hold as often as the claims
        it admits is throttling, not filtering; one whose refusals hold MORE
        often is refusing better theses than it accepts."""
        if self.regret is None:
            return f"{self.rejected} refused, none resolved yet"
        head = f"{self.resolved} resolved, {self.regret:.0%} would have held"
        if not self.measured:
            return head + f" - unmeasured below {MIN_GATE_RESOLVED}"
        if baseline is None:
            return head
        if self.regret > baseline + 0.10:
            return head + f" vs {baseline:.0%} admitted - REFUSING BETTER THAN IT ADMITS"
        if self.regret >= baseline - 0.10:
            return head + f" vs {baseline:.0%} admitted - not discriminating"
        return head + f" vs {baseline:.0%} admitted - earning its keep"


def gate_regret(entries: list[Entry]) -> tuple[dict[str, GateRegret], float | None]:
    """Per-gate regret, plus the baseline it must be read against.

    The baseline is the hold rate of resolved claims that PASSED every gate
    (`probability_stated`), because that is what "the gate let this through"
    would have meant. A rejection that holds no more often than an admission
    was refused for nothing.
    """
    by: dict[str, GateRegret] = {}
    for e in entries:
        if not e.rejected_by:
            continue
        g = by.setdefault(gate_of(e.rejected_by), GateRegret(gate_of(e.rejected_by), 0, 0, 0))
        g.rejected += 1
        if e.outcome is not None:
            g.resolved += 1
            g.held += int(bool(e.outcome))
    admitted = [e for e in entries if e.probability_stated and e.outcome is not None]
    baseline = (sum(1 for e in admitted if e.outcome) / len(admitted)) if admitted else None
    return by, baseline

