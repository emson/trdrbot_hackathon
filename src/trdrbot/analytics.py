"""C21 - the analytics pack. Deterministic, no LLM.

Computed every tick and always injected into the decide context. Includes
portfolio aggregate exposure, which matters *especially* because D-009 removed
everything that would constrain it: the agent cannot reason about risk it
cannot see.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ids, mcp_client


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
        # A bare `p["symbol"]` here KeyErrored the whole fast path on one
        # symbol-less broker row - and this is the first thing reconcile calls,
        # so a single odd row from the broker took reconciliation AND exit-rule
        # evaluation down for the tick. Every other broker field in this file
        # is already read defensively through `_f`/`.get`.
        return {p["symbol"]: p for p in self.broker_positions
                if isinstance(p, dict) and p.get("symbol")}

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


#: A spread whose legs nearly cancel has almost no net entry cost, and a P&L
#: fraction against it is a division by noise. Below this share of the gross
#: premium traded the base is refused, and an unobservable signal HOLDS rather
#: than firing blind - the same discipline exit_rules already applies.
MIN_NET_COST_SHARE = 0.02


def position_pnl_pct(symbols: list[str], snap: Snapshot) -> float | None:
    """Position-level P&L as a fraction of NET ENTRY COST (INV-19).

    Shared by C24 (exit rules) and housekeeping's interim scoring (INV-24) -
    one implementation, so the two never quietly disagree on what "the P&L"
    of a position means.

    **The denominator is the net debit paid or net credit received**, which is
    what "-60%" means to anyone who has traded a spread, and what every broker
    P&L% column shows. It was previously the GROSS premium summed across legs,
    and on a vertical spread those differ by 2-7x - so every mark-based stop
    and target the agent has ever written was evaluated against a base several
    times larger than the money it actually put up. Measured on the two live
    positions at the prices they were opened at:

        NVDA 230/240 debit spread, stop -60%   fired at -$2,287 against a
                                               $2,253 max loss - UNREACHABLE
        NVDA 230/240 debit spread, target +70% fired at +118% of the debit
        SPY  755/750 credit spread, target +50% fired at +$1,057 against a
                                               $535 max profit - UNREACHABLE

    Three of the four mark-based rules on the book could never fire, and the
    fourth fired at nearly twice the level stated. `trdrbot health` reported
    "exit_rules never ran" for two days and that was the reason: not a quiet
    market, an arithmetic base that made the agent's own stops inert.

    On this base a debit spread's loss is bounded at -100% (the debit) and a
    credit spread's target of +50% is the standard "buy it back for half the
    credit". A credit spread's LOSS can still exceed -100%, which is correct
    and is why the classic credit stop is quoted at 2x the credit.
    """
    held = snap.by_symbol()
    legs = [held[s] for s in symbols if s in held]
    if not legs:
        return None
    # Signed sum: positive = net debit paid, negative = net credit received.
    net = abs(sum(_f(l.get("cost_basis")) for l in legs))
    gross = sum(abs(_f(l.get("cost_basis"))) for l in legs)
    if gross == 0 or net < MIN_NET_COST_SHARE * gross:
        return None
    return sum(_f(l.get("unrealized_pl")) for l in legs) / net


async def snapshot(tools: dict[str, Any], underlyings: list[str] | None = None) -> Snapshot:
    """Gather deterministic state. A failing call degrades, never aborts."""
    snap = Snapshot(as_of=ids.market_today().isoformat())

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
            # Shape is {"trades": {"SPY": {"p": 767.46, ...}}} - nested under
            # `trades`, not under the symbol directly. The original parser
            # looked one level too shallow, found nothing, and left the price
            # map EMPTY without raising: the underlying_stop exit rules that
            # read it were therefore inert in production while passing every
            # unit test, because the tests supplied the map directly (D-042).
            node = None
            if isinstance(t, dict):
                node = (t.get("trades") or {}).get(u) or t.get(u)
            px = _f((node or {}).get("p") or (node or {}).get("price"), 0.0)
            if px > 0:
                snap.underlying_prices[u] = px
            else:
                print(f"[analytics] underlying {u}: no usable price in response")
        except Exception as exc:  # noqa: BLE001
            print(f"[analytics] underlying {u} price unavailable: {exc!r}")

    try:
        orders = await mcp_client.call(tools, "get_orders", status="open")
        if isinstance(orders, list):
            snap.open_orders = orders
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] orders unavailable: {exc!r}")

    return snap


def book_greeks(positions: list[Any], underlying_prices: dict[str, float],
                state_dir: Path | None = None, equity: float = 0.0) -> dict[str, Any] | None:
    """Approximate net greeks of the whole book, re-priced now (D-040).

    Legs are re-derived from their OCC symbols and priced at the CURRENT spot
    and CURRENT days-to-expiry, with each position's entry IV (the one honest
    staleness in the estimate, and it is labelled). This is what makes "a
    second short-vol position doubles the factor bet" a number instead of a
    sentence. None when nothing is priceable; partial books are summed and
    the skipped count reported - a partially-priced book is still far more
    informative than none, unlike a partially-priced POSITION (which is why
    net_greeks is all-or-nothing but this is not).
    """
    from datetime import date as _date

    from . import optmath

    total = {"delta_dollars": 0.0, "theta_dollars": 0.0, "vega_dollars": 0.0, "gamma_shares": 0.0}
    priced, skipped = 0, 0
    per_underlying_delta: dict[str, float] = {}
    for pos in positions:
        spot = underlying_prices.get(getattr(pos, "underlying", ""))
        iv = getattr(pos, "entry_iv", None)
        if not spot or not iv:
            skipped += 1
            continue
        legs = []
        for l in getattr(pos, "legs", []):
            o = optmath.parse_occ(str(l.get("symbol", "")))
            if o is None:
                legs = []
                break
            legs.append(optmath.Leg(
                right=o["right"], strike=o["strike"],
                side="long" if str(l.get("side", "")).lower() in ("long", "buy") else "short",
                qty=int(l.get("qty", 1) or 1), price=0.0, expiry=o["expiry"],
            ))
        if not legs:
            skipped += 1
            continue
        # A calendar priced at legs[0]'s expiry comes out RISKLESS - measured
        # on a real one (long 09-04 / short 10-16, same strike): delta, theta,
        # vega and gamma all exactly 0.0, against an honest -$31.83/day of
        # theta and -$71.97 per vol point. Zero is the worst possible wrong
        # answer here, because it reads as "this position adds nothing to the
        # book". Unpriceable is the truthful answer, and `positions_skipped`
        # already reports it. The guard existed and was only ever called on a
        # path the model cannot reach.
        try:
            optmath.require_single_expiry(legs)
        except optmath.MultiExpiryError:
            skipped += 1
            continue
        days = None
        with contextlib.suppress(ValueError):
            days = (_date.fromisoformat(legs[0].expiry) - ids.market_today()).days
        g = optmath.net_greeks(legs, spot, iv, days) if days and days > 0 else None
        if g is None:
            skipped += 1
            continue
        priced += 1
        for k in total:
            total[k] += g[k]
        u = getattr(pos, "underlying", "").upper()
        per_underlying_delta[u] = per_underlying_delta.get(u, 0.0) + g["delta_dollars"]
    if priced == 0:
        return None
    total["positions_priced"] = priced
    total["positions_skipped"] = skipped

    # Beta-weighted delta (D-055). Summing raw delta across names treats $10k
    # of XLE exposure as identical to $10k of NVDA, which it is not: over the
    # last 120 sessions NVDA ran a beta of 1.85 to SPY. Beta-weighting converts
    # the whole book into ONE number - how it moves when the market moves - and
    # that is the exposure the per-underlying risk cap cannot see, because that
    # cap counts names rather than factor loadings.
    if state_dir is not None and per_underlying_delta:
        from . import market_stats

        betas, assumed = market_stats.betas_for(state_dir, list(per_underlying_delta))
        bw = sum(d * betas.get(u, market_stats.ASSUMED_BETA)
                 for u, d in per_underlying_delta.items())
        total["beta_weighted_delta"] = bw
        total["betas"] = {u: round(betas.get(u, 1.0), 2) for u in per_underlying_delta}
        total["betas_assumed"] = assumed
        # The interpretable form: P&L per 1% market move, against equity. Raw
        # delta dollars are notional and look alarming on any spread (our NVDA
        # position carries $54,860 of delta against $2,100 of max loss); this
        # says what a 1% SPY move actually costs.
        if equity > 0:
            total["pct_equity_per_1pct_spy"] = (bw * 0.01) / equity * 100.0
    return total
