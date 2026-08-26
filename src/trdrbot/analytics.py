"""C21 - the analytics pack. Deterministic, no LLM.

Computed every tick and always injected into the decide context. Includes
portfolio aggregate exposure, which matters *especially* because D-009 removed
everything that would constrain it: the agent cannot reason about risk it
cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import mcp_client


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class Snapshot:
    """Everything the deterministic layer knows this tick."""

    market_open: bool = False
    account: dict[str, Any] = field(default_factory=dict)
    broker_positions: list[dict[str, Any]] = field(default_factory=list)
    open_orders: list[dict[str, Any]] = field(default_factory=list)
    as_of: str = ""

    @property
    def equity(self) -> float:
        return _f(self.account.get("equity"))

    @property
    def buying_power(self) -> float:
        return _f(self.account.get("buying_power"))

    @property
    def total_unrealized(self) -> float:
        return sum(_f(p.get("unrealized_pl")) for p in self.broker_positions)

    def by_symbol(self) -> dict[str, dict[str, Any]]:
        return {p["symbol"]: p for p in self.broker_positions}

    def render(self) -> str:
        lines = [
            "## Account",
            f"- market open: {self.market_open}",
            f"- equity: ${self.equity:,.2f}   buying power: ${self.buying_power:,.2f}",
            f"- open positions: {len(self.broker_positions)}   open orders: {len(self.open_orders)}",
            f"- total unrealised P&L: ${self.total_unrealized:,.2f}",
        ]
        if self.broker_positions:
            lines.append("\n## Holdings (from broker)")
            for p in self.broker_positions:
                lines.append(
                    f"- {p['symbol']} qty={p.get('qty')} entry={p.get('avg_entry_price')} "
                    f"mark={p.get('current_price')} "
                    f"P&L=${_f(p.get('unrealized_pl')):,.2f} "
                    f"({_f(p.get('unrealized_plpc')) * 100:+.1f}%)"
                )
        if self.open_orders:
            lines.append("\n## Open orders")
            for o in self.open_orders:
                lines.append(f"- {o.get('symbol')} {o.get('side')} {o.get('qty')} [{o.get('status')}]")
        return "\n".join(lines)


async def snapshot(tools: dict[str, Any]) -> Snapshot:
    """Gather deterministic state. A failing call degrades, never aborts."""
    snap = Snapshot(as_of=date.today().isoformat())

    try:
        clock = await mcp_client.call(tools, "get_clock")
        snap.market_open = bool(clock.get("is_open")) if isinstance(clock, dict) else False
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] clock unavailable: {exc!r}")

    try:
        acct = await mcp_client.call(tools, "get_account_info")
        if isinstance(acct, dict):
            snap.account = acct
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] account unavailable: {exc!r}")

    try:
        pos = await mcp_client.call(tools, "get_all_positions")
        if isinstance(pos, list):
            snap.broker_positions = pos
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] positions unavailable: {exc!r}")

    try:
        orders = await mcp_client.call(tools, "get_orders", status="open")
        if isinstance(orders, list):
            snap.open_orders = orders
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] orders unavailable: {exc!r}")

    return snap
