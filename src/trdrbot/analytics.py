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
    #: Latest trade per underlying of every open position. What the
    #: underlying-based exit rules (thesis stops) evaluate against - the
    #: underlying prints far more reliably than a wide option mark.
    underlying_prices: dict[str, float] = field(default_factory=dict)
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
        if self.underlying_prices:
            lines += [
            "- underlying marks: " + ", ".join(
                f"{k} {v:.2f}" for k, v in sorted(self.underlying_prices.items())),
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


def position_pnl_pct(symbols: list[str], snap: "Snapshot") -> float | None:
    """Position-level P&L fraction, summed across legs (INV-19).

    Shared by C24 (exit rules) and housekeeping's interim scoring (INV-24) -
    one implementation, so the two never quietly disagree on what "the P&L"
    of a position means.
    """
    held = snap.by_symbol()
    legs = [held[s] for s in symbols if s in held]
    if not legs:
        return None
    cost = sum(abs(_f(l.get("cost_basis"))) for l in legs)
    if cost == 0:
        return None
    return sum(_f(l.get("unrealized_pl")) for l in legs) / cost


async def snapshot(tools: dict[str, Any], underlyings: list[str] | None = None) -> Snapshot:
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

    for u in underlyings or []:
        try:
            t = await mcp_client.call(tools, "get_stock_latest_trade", symbols=u, feed="iex")
            node = t.get(u) if isinstance(t, dict) else None
            px = _f((node or {}).get("p") or (node or {}).get("price"), 0.0)
            if px > 0:
                snap.underlying_prices[u] = px
        except Exception as exc:  # noqa: BLE001
            print(f"[analytics] underlying {u} price unavailable: {exc!r}")

    try:
        orders = await mcp_client.call(tools, "get_orders", status="open")
        if isinstance(orders, list):
            snap.open_orders = orders
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] orders unavailable: {exc!r}")

    return snap
