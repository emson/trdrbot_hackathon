"""Local LangGraph tools (D-016 - local capability is a tool, not an MCP server).

`record_position` is the bridge from the model's prose to machine-readable
state. Without it the agent states a stop-loss in a sentence and nothing can
act on it; with it, the exit-rule evaluator has something deterministic to
check every 60 seconds.

This is why the agent is *required* to call it after opening a position: an
exit rule that exists only in prose is not an exit rule.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from . import experiments, ids, optmath
from .calibration import CalibrationStore
from .positions import Position, PositionStore


def build_simulate_experiments(shared: dict[str, Any]) -> StructuredTool:
    """Tool: score several expressions of one thesis before risking anything.

    Takes ALL candidates in a single call rather than one per call - that is
    deliberate. A per-candidate tool lets the agent simulate one structure and
    stop, which is just a slower way of deciding first and justifying after.
    Requiring the list up front forces the comparison to actually happen.
    """

    def simulate_experiments(
        thesis_claim: str,
        underlying: str,
        horizon: str,
        drift_pct: float,
        spot: float,
        iv_pct: float,
        days_to_expiry: int,
        candidates: list[dict[str, Any]],
        band_low: float | None = None,
        band_high: float | None = None,
    ) -> str:
        """Simulate several candidate structures expressing ONE thesis, and rank them.

        Call this BEFORE placing any order. Give at least two genuinely
        different structures - if every candidate is the same shape with
        different strikes, you are not exploring, you are decorating a choice
        you already made.

        Args:
            thesis_claim: your falsifiable view in one sentence
            underlying: e.g. "SPY"
            horizon: YYYY-MM-DD by which the thesis is decided
            drift_pct: expected TOTAL return over the horizon (2.0 = +2%).
                This is your view. If it is 0 you are claiming no directional
                edge, and the thesis edge column will show that honestly.
            spot: current underlying price
            iv_pct: implied vol as a percent (20.0 = 20%)
            days_to_expiry: calendar days to the options' expiry
            band_low: thesis holds only if price >= this at horizon
            band_high: thesis holds only if price <= this at horizon.
                Give at least one band - without one the thesis cannot be
                scored later and you lose the ability to learn whether your
                VIEW or your STRUCTURE was wrong.
            candidates: list of {name, rationale, legs}, where legs is a list
                of {right: "C"|"P", strike, side: "long"|"short", qty, price}
        """
        thesis = experiments.Thesis(
            claim=thesis_claim, underlying=underlying, horizon=horizon,
            drift=drift_pct / 100.0, band_low=band_low, band_high=band_high,
        )
        built: list[experiments.Experiment] = []
        for c in candidates:
            try:
                legs = [optmath.Leg.parse(l) for l in (c.get("legs") or [])]
            except ValueError as e:
                return f"Invalid legs in candidate {c.get('name')!r}: {e}"
            if not legs:
                return f"Candidate {c.get('name')!r} has no legs."
            built.append(experiments.Experiment(
                name=str(c.get("name") or f"candidate {len(built)+1}"),
                legs=legs, rationale=str(c.get("rationale") or ""),
            ))
        if len(built) < 2:
            return (
                "Give at least two genuinely different structures. One candidate is not "
                "an experiment, it is a decision already made."
            )

        results = [
            (e, experiments.simulate(e, thesis, spot, iv_pct / 100.0, days_to_expiry))
            for e in built
        ]
        ranked = experiments.rank(results)
        shared["thesis"] = thesis
        shared["ranked"] = [(e.name, m) for e, m in ranked]
        return experiments.render_comparison(thesis, ranked)

    return StructuredTool.from_function(
        func=simulate_experiments,
        name="simulate_experiments",
        description=simulate_experiments.__doc__,
    )


def build_record_position(
    store: PositionStore,
    decision_ref: str,
    *,
    elfmem_blocks: dict[str, list[str]] | None = None,
    generated_by: str = "",
    calibration: "CalibrationStore | None" = None,
    sources: list[dict[str, Any]] | None = None,
    shared: dict[str, Any] | None = None,
) -> StructuredTool:
    def record_position(
        underlying: str,
        strategy: str,
        legs: list[dict[str, Any]],
        thesis: str,
        confidence: float,
        expiry: str = "",
        stop_loss_pct: float | None = None,
        profit_target_pct: float | None = None,
        time_stop_days_before_expiry: int | None = None,
    ) -> str:
        """Record a position you have just opened, with its exit conditions.

        Call this immediately after a successful order placement. The exit
        rules you give here are evaluated automatically every tick and will
        close the position without asking you, so state them deliberately.

        Args:
            underlying: e.g. "SPY"
            strategy: e.g. "long_call", "bull_put_spread"
            legs: one dict per leg, each with "symbol" (OCC), "side", "qty"
            thesis: one or two sentences - why, and what invalidates it
            confidence: your honest probability (0.0-1.0) that this position
                closes profitable. This is scored: over time your stated
                confidence is compared against how often you were actually
                right (Brier/Murphy calibration). Saying 0.9 on everything
                will be detected as overconfidence, and a well-calibrated
                0.55 is worth more than an inflated 0.9. Be honest, not
                optimistic.
            expiry: option expiry as YYYY-MM-DD
            stop_loss_pct: close at this loss, as a negative percent (-50 = -50%)
            profit_target_pct: close at this gain, as a percent (50 = +50%)
            time_stop_days_before_expiry: close this many days before expiry
        """
        rules: list[dict[str, Any]] = []
        if stop_loss_pct is not None:
            rules.append({"type": "stop_loss", "basis": "position_mark", "threshold": f"{stop_loss_pct}%"})
        if profit_target_pct is not None:
            rules.append({"type": "profit_target", "basis": "position_mark", "threshold": f"{profit_target_pct}%"})
        if time_stop_days_before_expiry is not None:
            rules.append({"type": "time_stop", "days_before_expiry": time_stop_days_before_expiry})

        pos = Position(
            position_id=ids.position_id(underlying, strategy),
            # `opening`, not `open`: the order is submitted, not confirmed
            # filled. Reconciliation promotes it once the broker shows the
            # legs. Claiming `open` here would make an unfilled limit order
            # look like real exposure, and exit rules would evaluate against a
            # position that does not exist.
            status="opening",
            strategy=strategy,
            underlying=underlying.upper(),
            opened=ids.utc_now().isoformat(),
            expiry=expiry,
            legs=legs,
            exit_rules=rules,
            thesis=thesis,
            decision_ref=decision_ref,
            # elfmem blocks recalled for THIS decision (INV-22, per-frame) -
            # the credit-assignment targets at resolution (D-011).
            elfmem_blocks=dict(elfmem_blocks or {}),
            generated_by=generated_by,
            # OKF sources (D-022): what the agent actually read this cycle,
            # so a resolved position can credit or discredit its inputs.
            sources=list(sources or []),
        )
        # Carry the thesis onto the position so resolution can attribute the
        # outcome to the VIEW or the STRUCTURE rather than just to P&L.
        th = (shared or {}).get("thesis")
        if th is not None:
            pos.thesis_claim = th.claim
            pos.thesis_horizon = th.horizon
            pos.thesis_band_low = th.band_low
            pos.thesis_band_high = th.band_high
            pos.thesis_drift = th.drift
        path = store.save(pos)
        if calibration is not None:
            calibration.record(pos.position_id, confidence)
        return (
            f"Recorded {pos.position_id} with {len(rules)} exit rule(s) at {path.name}, "
            f"confidence {confidence:.0%} (will be scored for calibration at close). "
            f"Exit rules are now evaluated automatically every tick."
        )

    return StructuredTool.from_function(
        func=record_position,
        name="record_position",
        description=record_position.__doc__,
    )
