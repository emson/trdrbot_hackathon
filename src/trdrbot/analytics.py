"""C21 - the analytics pack. Deterministic, no LLM.

Computed every tick and always injected into the decide context. Includes
portfolio aggregate exposure, which matters *especially* because D-009 removed
everything that would constrain it: the agent cannot reason about risk it
cannot see.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import health, ids, mcp_client


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
    #: Did we actually SUCCEED in reading the broker's holdings this tick?
    #:
    #: `broker_positions == []` means two irreconcilable things - the broker
    #: holds nothing, or we could not ask - and reconcile treats the first as
    #: proof a position is gone. Absence-as-evidence (D-038's class, and I-46's
    #: twin one seam over): a dead MCP session made every open position look
    #: phantom, closed it in our records, scored it, and left the real exposure
    #: live and unwatched because a terminal position is no longer evaluated.
    #: False means "no conclusions may be drawn from what is missing here".
    broker_readable: bool = False
    #: Same rule for the order book (D-112). Reconcile reads "no working order"
    #: off an EMPTY list, which is the one conclusion an unreadable order book
    #: cannot support - it transitioned an `opening` position to `abandoned`
    #: (terminal) whose limit order then filled with no exit rules and nothing
    #: watching. `broker_readable` closed this hole for positions (I-55); the
    #: orders read had the same shape and the same bare print.
    orders_readable: bool = False
    #: Previous session's CLOSE per underlying, when the feed carried one.
    #:
    #: The exit engine's corroboration rule needs a RECENT reference point to
    #: tell a wide quote from a real move, and the only one it had was the
    #: entry price - which is days old and drifts (D-113). Absent rather than
    #: guessed when the snapshot endpoint is unavailable: a fabricated
    #: reference is worse than an admitted one, and the rule debounces without
    #: it, which is the safe direction.
    prev_closes: dict[str, float] = field(default_factory=dict)

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


def position_pnl_fraction(symbols: list[str], snap: Snapshot) -> float | None:
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


def filled_legs(symbols: list[str], snap: Snapshot) -> list[Any] | None:
    """The position's legs priced at what the broker ACTUALLY filled, or None.

    Everything here is derived from `cost_basis`, and deliberately so. It is a
    signed DOLLAR TOTAL for the leg - the one broker cost field whose units are
    unambiguous, the one this module already computes every stop against
    (`position_pnl_fraction` above), and therefore the only one whose meaning
    is already load-bearing in production rather than newly assumed here.
    `avg_entry_price` would need a second belief - per-share or per-contract? -
    that nothing in this repo currently tests, and getting it wrong by the
    100x contract multiplier would silently corrupt every book cap downstream.

        side  = sign of cost_basis   (paid for it = long, received = short)
        price = |cost_basis| / (qty x 100)

    which round-trips exactly: `optmath.entry_cost` of these legs is the same
    signed net that `position_pnl_fraction` divides by.

    None - never a partial answer - when any leg is absent, unparseable, or
    carries no cost. A max loss recomputed from half a spread is worse than
    the stated one it would replace.
    """
    from . import optmath

    held = snap.by_symbol()
    out = []
    for symbol in symbols:
        row = held.get(symbol)
        if row is None:
            return None
        cost = _f(row.get("cost_basis"))
        qty = abs(int(_f(row.get("qty"), 0.0)))
        if cost == 0.0 or qty == 0:
            return None  # unusable: side and premium are both undecidable
        leg = optmath.Leg.from_position_leg({
            "symbol": symbol,
            "side": "long" if cost > 0 else "short",
            "qty": qty,
            "price": abs(cost) / (qty * optmath.CONTRACT_MULTIPLIER),
        })
        if leg is None:
            return None  # not an OCC option symbol (assigned stock, say)
        out.append(leg)
    return out or None


#: The data feed a paper account is entitled to. One constant, because
#: `attribution` and this module were passing their own copies of the string.
FEED = "iex"

#: How stale the last trade may be before it stops counting as a price.
#:
#: Enforced only while the market is open, where it means "the tape has moved
#: and this print has not". Fifteen minutes is the delayed-data convention and
#: is deliberately loose: the failure being guarded is an hours-old print on a
#: thin ETF, not a quiet minute on SPY. Tune it from `degraded` rows carrying
#: `analytics.spot`, never from taste.
SPOT_MAX_AGE_MINUTES = 15.0


@dataclass(frozen=True)
class SpotQuote:
    """One underlying's price, when it printed, and the previous close.

    The previous close travels WITH the price because the two are read from
    one endpoint and are only comparable to each other: a spot from one feed
    against a close from another is a made-up gap.
    """

    price: float
    #: When the trade printed. None when the feed omitted a timestamp - which
    #: means the age is unknown, and unknown is not the same as fresh.
    as_of: datetime | None = None
    prev_close: float | None = None

    def age_minutes(self) -> float | None:
        if self.as_of is None:
            return None
        return (ids.utc_now() - self.as_of).total_seconds() / 60.0


def _price_in(node: Any) -> float | None:
    """A price out of any of the shapes Alpaca uses for one."""
    if not isinstance(node, dict):
        return None
    for key in ("p", "c", "price", "close"):
        px = _f(node.get(key), 0.0)
        if px > 0:
            return px
    return None


def _time_in(node: Any) -> datetime | None:
    """The trade timestamp, or None. Never raises - an unparseable stamp is an
    unknown age, and the caller already treats unknown as unjudgeable."""
    if not isinstance(node, dict):
        return None
    raw = str(node.get("t") or node.get("timestamp") or "").strip()
    if not raw:
        return None
    # RFC3339 with NANOSECONDS ("...T15:30:00.123456789Z"), which
    # `fromisoformat` rejects outright - it takes at most microseconds. Trim
    # the fraction rather than the whole stamp: a dropped timestamp reads as
    # "age unknown" and would silently disable the staleness check that is the
    # entire point of reading it.
    raw = raw.replace("Z", "+00:00")
    raw = re.sub(r"\.(\d{6})\d+", r".\1", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def spot_quote(tools: dict[str, Any], symbol: str,
                     *, feed: str = FEED) -> SpotQuote | None:
    """Last price for one underlying, with its age and the previous close.

    ONE reader for a question three modules were answering separately - this
    module by `get_stock_latest_trade`, `attribution` by `get_stock_snapshot`
    with a latest-trade fallback, each with its own shape-guessing. The
    snapshot endpoint returns everything the trade endpoint does and two things
    it does not: when the trade printed, and where the previous session
    closed. Both are load-bearing now (D-113), so the richer call leads and the
    older one remains the fallback, exactly as attribution already had it.

    Returns None when no usable price came back at all. Never raises: an
    unreachable data endpoint must not take the tick down (INV-8).
    """
    try:
        snap = await mcp_client.call(tools, "get_stock_snapshot",
                                     symbols=symbol, feed=feed)
        if isinstance(snap, dict):
            # Alpaca nests per symbol on a multi-symbol request and returns the
            # bare object on a single one. Both shapes are live.
            node = snap.get(symbol) if isinstance(snap.get(symbol), dict) else snap
            trade = node.get("latestTrade") or node.get("latest_trade")
            px = _price_in(trade) or _price_in(node.get("dailyBar") or node.get("daily_bar"))
            prev = _price_in(node.get("prevDailyBar") or node.get("prev_daily_bar"))
            if px:
                return SpotQuote(px, _time_in(trade), prev)
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] snapshot unavailable for {symbol}: {exc!r}")

    try:
        t = await mcp_client.call(tools, "get_stock_latest_trade",
                                  symbols=symbol, feed=feed)
        # Shape is {"trades": {"SPY": {"p": 767.46, ...}}} - nested under
        # `trades`, not under the symbol directly. The original parser looked
        # one level too shallow, found nothing, and left the price map EMPTY
        # without raising: the underlying_stop exit rules that read it were
        # therefore inert in production while passing every unit test, because
        # the tests supplied the map directly (D-042).
        node = None
        if isinstance(t, dict):
            node = (t.get("trades") or {}).get(symbol) or t.get(symbol) or t
        px = _price_in(node)
        if px:
            # No previous close on this endpoint, and none invented: the
            # corroboration rule debounces without one, which is the safe side.
            return SpotQuote(px, _time_in(node), None)
    except Exception as exc:  # noqa: BLE001
        print(f"[analytics] underlying {symbol} price unavailable: {exc!r}")
    return None


async def snapshot(tools: dict[str, Any], underlyings: list[str] | None = None,
                   journal: Any = None) -> Snapshot:
    """Gather deterministic state. A failing call degrades, never aborts."""
    snap = Snapshot(as_of=ids.market_today().isoformat())

    try:
        clock = await mcp_client.call(tools, "get_clock")
        snap.market_open = bool(clock.get("is_open")) if isinstance(clock, dict) else False
    except Exception as exc:  # noqa: BLE001
        # `market_open` stays False, which is the SAFE side - nothing submits -
        # but a submit gate latched shut by a flaky clock on expiry day is a
        # position riding into pin risk while the heartbeat reads clean (D-112).
        # Positions and orders failures write a `degraded` row; so does this.
        health.degraded(journal, "analytics.clock",
                        "could not read the market clock - treated as CLOSED, so no "
                        "close will be submitted this tick", error=repr(exc)[:200])

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
            snap.broker_readable = True
    except Exception as exc:  # noqa: BLE001
        # NOT just a print: everything downstream reads an empty list as "the
        # broker holds nothing", which is the one conclusion this failure
        # cannot support. `broker_readable` stays False and reconcile refuses
        # to draw it.
        health.degraded(journal, "analytics.positions",
                        "could not read broker holdings - no absence conclusions "
                        "may be drawn this tick", error=repr(exc)[:200])

    for u in underlyings or []:
        q = await spot_quote(tools, u)
        if q is None:
            # Still a print, not a `degraded` row: an absent price is not
            # itself a fail-open, and on a thin name it would write one every
            # tick forever. What it CAUSES is counted where it bites - the
            # exit engine's `blind:underlying` tally, which names the position
            # left unwatched rather than the symbol left unquoted (D-113).
            print(f"[analytics] underlying {u}: no usable price in response")
            continue
        # A STALE print is different in kind, and this is the one the exit
        # rules cannot survive: a real number, from a real trade, that stopped
        # describing the market some time ago. IEX carries a small share of
        # consolidated volume, so on XLE/XLP/XLV the last IEX trade can be
        # minutes or hours old while the tape moves - and an underlying stop
        # reading it does not merely miss, it decides on fiction. Only while
        # the market is OPEN: after the close every last trade is old by
        # definition and that is not a fault.
        age = q.age_minutes()
        if snap.market_open and age is not None and age > SPOT_MAX_AGE_MINUTES:
            health.degraded(journal, "analytics.spot",
                            f"{u} last traded {age:.0f} minutes ago on the {FEED} feed - "
                            f"too old to stop on, so the price is DROPPED and the rules "
                            f"that read it hold", symbol=u, age_minutes=round(age, 1))
            continue
        snap.underlying_prices[u] = q.price
        if q.prev_close:
            snap.prev_closes[u] = q.prev_close

    try:
        orders = await mcp_client.call(tools, "get_orders", status="open")
        if isinstance(orders, list):
            snap.open_orders = orders
            snap.orders_readable = True
    except Exception as exc:  # noqa: BLE001
        health.degraded(journal, "analytics.orders",
                        "could not read the order book - no absence conclusions may be "
                        "drawn about working orders this tick", error=repr(exc)[:200])

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
        for leg in getattr(pos, "legs", []):
            parsed = optmath.Leg.from_position_leg(leg)
            if parsed is None:
                legs = []
                break
            legs.append(parsed)
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
