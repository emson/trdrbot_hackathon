"""Historical price statistics and bootstrap Monte Carlo. Deterministic, no LLM.

Two jobs:

  1. Technical/regime statistics from real daily closes - trend vs moving
     averages, realized volatility and its percentile, drawdown, momentum.
     These feed the research cycle's regime assessment and company dossiers.

  2. A bootstrap terminal-price distribution: resample ACTUAL daily returns
     instead of assuming lognormal. Real returns have fatter tails than the
     lognormal grid in optmath assumes (a documented limitation) - the
     bootstrap keeps whatever tails the last year actually had. The GAP
     between lognormal P(profit) and bootstrap P(profit) is itself a signal:
     when they diverge, the position's edge depends on the tail assumption.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ids

TRADING_DAYS = 252


@dataclass
class Stats:
    symbol: str
    n_days: int
    last_close: float
    ret_5d: float | None
    ret_21d: float | None
    ret_63d: float | None
    realized_vol: float | None  # annualized, last 21 days
    vol_percentile: float | None  # today's 21d vol vs its own 1y history
    sma20_state: str  # above | below
    sma50_state: str
    max_drawdown_1y: float | None

    def render(self) -> str:
        f = lambda v, fmt: (fmt % v) if v is not None else "n/a"
        return (
            f"{self.symbol}: close {self.last_close:.2f} | "
            f"5d {f(self.ret_5d, '%+.1f%%')} 21d {f(self.ret_21d, '%+.1f%%')} "
            f"63d {f(self.ret_63d, '%+.1f%%')} | "
            f"realized vol {f(self.realized_vol, '%.1f%%')} "
            f"(pctile {f(self.vol_percentile, '%.0f')}) | "
            f"px {self.sma20_state} SMA20, {self.sma50_state} SMA50 | "
            f"max DD 1y {f(self.max_drawdown_1y, '%.1f%%')}"
        )


def _log_returns(closes: list[float]) -> list[float]:
    return [
        math.log(b / a)
        for a, b in zip(closes, closes[1:])
        if a > 0 and b > 0
    ]


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _rolling_vol(rets: list[float], window: int = 21) -> list[float]:
    out = []
    for i in range(window, len(rets) + 1):
        chunk = rets[i - window : i]
        mean = sum(chunk) / window
        var = sum((r - mean) ** 2 for r in chunk) / (window - 1)
        out.append(math.sqrt(var) * math.sqrt(TRADING_DAYS))
    return out


def compute_stats(symbol: str, closes: list[float]) -> Stats:
    """Closes oldest -> newest. Degrades to None per-field on short history."""
    rets = _log_returns(closes)
    last = closes[-1] if closes else 0.0

    def total_ret(days: int) -> float | None:
        if len(closes) <= days:
            return None
        return (closes[-1] / closes[-1 - days] - 1) * 100

    vols = _rolling_vol(rets)
    realized = vols[-1] * 100 if vols else None
    pctile = None
    if len(vols) >= 30:
        below = sum(1 for v in vols if v <= vols[-1])
        pctile = below / len(vols) * 100

    peak, dd = 0.0, None
    if closes:
        peak = closes[0]
        worst = 0.0
        for c in closes:
            peak = max(peak, c)
            worst = min(worst, (c / peak - 1))
        dd = worst * 100

    sma20, sma50 = _sma(closes, 20), _sma(closes, 50)
    return Stats(
        symbol=symbol,
        n_days=len(closes),
        last_close=last,
        ret_5d=total_ret(5),
        ret_21d=total_ret(21),
        ret_63d=total_ret(63),
        realized_vol=realized,
        vol_percentile=pctile,
        sma20_state="above" if (sma20 and last > sma20) else "below",
        sma50_state="above" if (sma50 and last > sma50) else "below",
        max_drawdown_1y=dd,
    )


def bootstrap_factors(
    closes: list[float], days: int, *, n_paths: int = 2000, seed: str = "",
    drift: float = 0.0,
) -> list[float]:
    """Terminal price multipliers by IID resampling of real daily returns.

    Keeps the empirical distribution's fat tails and skew, which lognormal
    throws away - but returns are DEMEANED first, and this matters. Raw
    resampling inherits the sample period's directional luck: a year that
    happened to rally +36% would be baked into every forecast as if it were
    structural, which is exactly recency bias with a formula wrapped round
    it (found by the convergence test, not by inspection - raw bootstrap
    disagreed with lognormal by 16pp on identically-distributed data purely
    because of the sample path's drift). Demeaning keeps the SHAPE and
    strips the luck; direction is then applied deliberately via `drift`
    (total expected return over the horizon, the thesis's own claim), so a
    view is something the agent states, never something the data smuggles in.

    Seeded deterministically - a simulation that changes on every call reads
    as noise to the agent.

    Honest limitations, by construction: IID resampling destroys
    autocorrelation and volatility clustering, and one year of history is one
    regime's sample. Better tails than lognormal, still not truth.
    """
    rets = _log_returns(closes)
    if len(rets) < 60 or days <= 0:
        return []
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    # Center so E[exp(r')] ~= 1 per day (martingale), same correction as the
    # lognormal grid - which is what makes the two comparable, and their GAP
    # attributable to tail shape rather than to drift.
    target_mean = -0.5 * var + (math.log(1.0 + drift) / days if drift > -1 else 0.0)
    adj = [r - mean + target_mean for r in rets]

    rng = random.Random(f"{seed}|{len(adj)}|{days}|{drift:.6f}")
    out = []
    for _ in range(n_paths):
        out.append(math.exp(sum(rng.choice(adj) for _ in range(days))))
    return out


# --------------------------------------------------------- persistence

def returns_path(state_dir: Path, symbol: str) -> Path:
    return state_dir / "returns" / f"{symbol.upper()}.json"


def save_closes(state_dir: Path, symbol: str, closes: list[float]) -> None:
    p = returns_path(state_dir, symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "symbol": symbol.upper(),
        "as_of": ids.utc_now().date().isoformat(),
        "closes": closes,
    }))


def load_closes(state_dir: Path, symbol: str, *, max_age_days: int = 4) -> list[float] | None:
    """None if absent or stale - stale history silently reused would make the
    bootstrap confidently describe a market that no longer exists."""
    p = returns_path(state_dir, symbol)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        from datetime import date
        age = (date.today() - date.fromisoformat(d["as_of"])).days
        if age > max_age_days:
            return None
        return [float(c) for c in d["closes"]]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


async def fetch_daily_closes(tools: dict[str, Any], symbol: str, *, days: int = 300) -> list[float]:
    """Daily closes via Alpaca bars, oldest -> newest. IEX feed (D-031: SIP 403s).

    `sort=desc` + reverse, NOT ascending-with-limit. Bars come oldest-first
    and `limit` truncates from the START of the range - an ascending fetch
    with a wide window returned data ending six weeks ago while every log
    line looked healthy. The research cycle then described a market that no
    longer existed, and only the decide cycle's cross-check against live
    quotes caught it ("the research note assumes NVDA at 224.11; the tape
    says 209.37"). Descending sort anchors the window to TODAY by
    construction: whatever the limit cuts off is the distant past, never the
    recent present.
    """
    from datetime import date, timedelta
    from . import mcp_client

    start = (date.today() - timedelta(days=int(days * 1.6))).isoformat()
    r = await mcp_client.call(
        tools, "get_stock_bars",
        symbols=symbol, timeframe="1Day", start=start, feed="iex",
        limit=days, sort="desc",
    )
    bars = []
    if isinstance(r, dict):
        bars = r.get("bars") or r.get(symbol) or []
        if isinstance(bars, dict):
            bars = bars.get(symbol) or []
    elif isinstance(r, list):
        bars = r
    closes = []
    for b in bars:
        c = b.get("c") if isinstance(b, dict) else None
        if c is None and isinstance(b, dict):
            c = b.get("close")
        if c is not None:
            closes.append(float(c))
    closes.reverse()  # desc -> oldest-first, which every consumer expects
    return closes
