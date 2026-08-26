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

from . import ids
from .positions import Position, PositionStore


def build_record_position(
    store: PositionStore,
    decision_ref: str,
    *,
    elfmem_blocks: dict[str, list[str]] | None = None,
    generated_by: str = "",
) -> StructuredTool:
    def record_position(
        underlying: str,
        strategy: str,
        legs: list[dict[str, Any]],
        thesis: str,
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
        )
        path = store.save(pos)
        return (
            f"Recorded {pos.position_id} with {len(rules)} exit rule(s) at {path.name}. "
            f"These will now be evaluated automatically every tick."
        )

    return StructuredTool.from_function(
        func=record_position,
        name="record_position",
        description=record_position.__doc__,
    )
