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
    #: Same measure over the last 5 days. The decide cycle caught the desk
    #: citing 21d vol against a market pricing the last few days - both were
    #: right, the window was the disagreement. Report both, remove the guess.
    realized_vol_5d: float | None
    vol_percentile: float | None  # today's 21d vol vs its own 1y history
    sma20_state: str  # above | below
    sma50_state: str
    rsi14: float | None
    max_drawdown_1y: float | None

    def render(self) -> str:
        f = lambda v, fmt: (fmt % v) if v is not None else "n/a"
        return (
            f"{self.symbol}: close {self.last_close:.2f} | "
            f"5d {f(self.ret_5d, '%+.1f%%')} 21d {f(self.ret_21d, '%+.1f%%')} "
            f"63d {f(self.ret_63d, '%+.1f%%')} | "
            f"realized vol 21d {f(self.realized_vol, '%.1f%%')} / 5d {f(self.realized_vol_5d, '%.1f%%')} "
            f"(21d pctile {f(self.vol_percentile, '%.0f')}) | "
            f"px {self.sma20_state} SMA20, {self.sma50_state} SMA50 | "
            f"RSI14 {f(self.rsi14, '%.0f')} | "
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


def _rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI. >70 conventionally overbought, <30 oversold."""
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for a, b in zip(closes, closes[1:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


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
    v5 = _rolling_vol(rets, window=5)
    realized5 = v5[-1] * 100 if v5 else None
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
        realized_vol_5d=realized5,
        vol_percentile=pctile,
        rsi14=_rsi(closes),
        sma20_state="above" if (sma20 and last > sma20) else "below",
        sma50_state="above" if (sma50 and last > sma50) else "below",
        max_drawdown_1y=dd,
    )


def bootstrap_factors(
    closes: list[float], days: int, *, n_paths: int = 2000, seed: str = "",
    drift: float = 0.0, inflate: float = 1.0,
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
    # `days` is CALENDAR days to expiry, but the returns being resampled are
    # per SESSION - so drawing one per calendar day priced in weekends that
    # never traded. On a typical 6-calendar-day tenor that is 6 draws where 4
    # sessions occur: variance 1.45x too high, the distribution ~20% too wide.
    # The bootstrap is compared directly against the lognormal to produce
    # `tail_gap`, which warns above 5pp - so a fifth of every "the tails
    # disagree, this edge is assumption-dependent" flag was manufactured by the
    # units, not by tail shape. Round to at least one draw.
    draws = max(1, round(days * TRADING_DAYS / 365.0))
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    # Center so E[exp(r')] ~= 1 per session (martingale), same correction as
    # the lognormal grid - which is what makes the two comparable, and their
    # GAP attributable to tail shape rather than to drift.
    # `inflate` widens the distribution by scaling each demeaned return - a
    # MEASURED empirical correction, not a modelling choice. Scored offline
    # over 21,280 historical band-forecasts with the history sliced before
    # every estimate (I-29 / notes/017): the raw bootstrap overstates
    # P(stays inside a band) by 15-23pp exactly where credit spreads live,
    # and UNDERstates both tails - the signature of a too-narrow
    # distribution, which is why the fix is variance inflation rather than a
    # p->p map (a map cannot tell band shapes apart; widening corrects both
    # directions at once). Validated OUT-OF-SAMPLE on both a time split and
    # a ticker split before being wired in; the fitted values, their
    # provenance and their holdout scores live in the artifact
    # `band_inflation()` reads. At 1.0 this is byte-identical to the
    # uninflated bootstrap, and there is a test pinning that. The martingale
    # recentering scales with inflate^2 so E[factor] stays ~1.
    #
    # The residual the correction deliberately does NOT touch: the upside
    # tail stays understated, because demeaning strips drift BY DESIGN -
    # direction is something the agent states, never something the data
    # smuggles in. That gap is where the agent's view is supposed to live.
    var_i = var * inflate * inflate
    target_mean = -0.5 * var_i + (math.log(1.0 + drift) / draws if drift > -1 else 0.0)
    adj = [(r - mean) * inflate + target_mean for r in rets]

    # `inflate` is deliberately NOT in the seed: the same seed draws the same
    # return indices at every inflation, so calibrated and raw estimates are
    # paired on identical paths rather than differing by resampling noise.
    rng = random.Random(f"{seed}|{len(adj)}|{days}|{drift:.6f}")
    out = []
    for _ in range(n_paths):
        out.append(math.exp(sum(rng.choice(adj) for _ in range(draws))))
    return out


# ----------------------------------------- model calibration (D-089)
#
# The agent's probabilities are calibrated against live resolutions
# (calibration.py). Nothing calibrated the MODEL's probabilities until I-29
# measured them against history and found a real defect. This is the model
# layer's counterpart: fit against the dense evidence stream (historic
# replay, thousands of samples, no LLM, lookahead structurally impossible),
# validate on held-out data, store as an artifact with provenance, and let
# the slow evidence stream (live forward resolutions) audit it.

#: Sanity bounds on a fitted inflation. A fit wanting more than the ceiling
#: is evidence of something structural, not a bigger knob - refuse it.
INFLATE_MIN, INFLATE_MAX = 1.0, 1.5
FIT_HORIZONS = (3, 5, 10)
_FIT_BANDS = ((-0.03, 0.03), (-0.05, 0.05), (None, -0.02), (0.02, None))


def model_cal_path(state_dir: Path) -> Path:
    return state_dir / "model_calibration.json"


def band_inflation(state_dir: Path, days: int) -> float:
    """The fitted inflation for this horizon, clamped, 1.0 when absent.

    Fail-safe by construction: no artifact, an unreadable one, or an insane
    value all degrade to the uninflated bootstrap - the behaviour the system
    had for its whole life before the fit existed. Never raises.
    """
    try:
        d = json.loads(model_cal_path(state_dir).read_text())
        per_h = d.get("per_horizon") or {}
        if not per_h:
            return 1.0
        nearest = min(per_h, key=lambda h: abs(int(h) - days))
        k = float(per_h[nearest])
        return max(INFLATE_MIN, min(INFLATE_MAX, k))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return 1.0


def fit_band_inflation(
    series: dict[str, list[float]], *, horizons: tuple[int, ...] = FIT_HORIZONS,
    n_paths: int = 400, step: int = 9,
) -> dict[str, Any]:
    """Fit per-horizon inflation on historic closes, holdout-validated.

    Pure: takes {symbol: closes}, returns the artifact dict (not written).
    For every (ticker, date, band) the estimate uses ONLY closes before the
    date - lookahead is impossible by slicing, not by care. The time split
    (fit on the first 60%, validate on the last 40%) is the honest one for
    forward use; a k that only helps in-sample is reported as 1.0.

    Speed and fairness share one trick: per path, the sum S of demeaned
    draws is computed once, and the factor at any k is exp(k*S - draws *
    k^2 * var / 2) - so every candidate k is scored on IDENTICAL draws.
    """
    ks = [round(1.0 + 0.05 * i, 2) for i in range(11)]  # 1.00 .. 1.50
    per_h: dict[str, float] = {}
    diag: dict[str, Any] = {}
    for h in horizons:
        draws = max(1, round(h * TRADING_DAYS / 365.0))
        train: list[tuple[list[float], float, float, float]] = []
        test: list[tuple[list[float], float, float, float]] = []
        for sym, closes in sorted(series.items()):
            if len(closes) < 150:
                continue
            cutoff = 120 + int(0.6 * (len(closes) - 120 - h))
            for i in range(120, len(closes) - h, step):
                rets = _log_returns(closes[:i])
                if len(rets) < 60:
                    continue
                mean = sum(rets) / len(rets)
                var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
                dm = [r - mean for r in rets]
                rng = random.Random(f"fit|{sym}|{i}|{h}")
                S = [sum(dm[rng.randrange(len(dm))] for _ in range(draws))
                     for _ in range(n_paths)]
                row = (S, var, closes[i], closes[i + h])
                (test if i >= cutoff else train).append(row)

        def brier(pts: list, k: float) -> float | None:
            tot = n = 0
            for S, var, spot, fut in pts:
                tm = -0.5 * var * k * k
                facs = [math.exp(k * s + draws * tm) for s in S]
                for lo_p, hi_p in _FIT_BANDS:
                    lo = spot * (1 + lo_p) if lo_p is not None else None
                    hi = spot * (1 + hi_p) if hi_p is not None else None
                    held = sum(1 for x in facs
                               if (lo is None or spot * x >= lo)
                               and (hi is None or spot * x <= hi))
                    p = held / len(facs)
                    a = 1 if ((lo is None or fut >= lo)
                              and (hi is None or fut <= hi)) else 0
                    tot += (p - a) ** 2
                    n += 1
            return tot / n if n else None

        if not train or not test:
            continue
        scored = [(brier(train, k), k) for k in ks]
        _, k_star = min(scored)
        b1, bk = brier(test, 1.0), brier(test, k_star)
        # The holdout has the veto: an in-sample-only k ships as 1.0.
        chosen = k_star if (b1 is not None and bk is not None and bk < b1) else 1.0
        per_h[str(h)] = chosen
        diag[str(h)] = {"k_star": k_star, "chosen": chosen,
                        "train_n": len(train) * len(_FIT_BANDS),
                        "test_n": len(test) * len(_FIT_BANDS),
                        "test_brier_raw": round(b1, 4) if b1 else None,
                        "test_brier_fit": round(bk, 4) if bk else None}

    return {
        "kind": "bootstrap_band_inflation",
        "fitted": ids.utc_now().isoformat(),
        "per_horizon": per_h,
        "bounds": [INFLATE_MIN, INFLATE_MAX],
        "sample": {"tickers": len(series), "horizons": list(horizons),
                   "n_paths": n_paths, "step": step},
        "holdout": diag,
        "provenance": "notes/017 + D-089; time-split holdout has the veto; "
                      "root cause of the raw defect NOT established (I-29)",
    }


def load_all_closes(state_dir: Path) -> dict[str, list[float]]:
    """Every cached return series, regardless of age - for FITTING, where an
    old series is still a valid historical sample (unlike live use, where
    `load_closes` correctly refuses stale data)."""
    out: dict[str, list[float]] = {}
    for p in sorted((state_dir / "returns").glob("*.json")):
        try:
            d = json.loads(p.read_text())
            if isinstance(d.get("closes"), list):
                out[str(d.get("symbol") or p.stem)] = d["closes"]
        except (OSError, json.JSONDecodeError):
            continue
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


# ------------------------------------------------------- beta to the market

#: Sessions of overlap used to estimate beta. Long enough to be stable, short
#: enough that a regime change eventually shows up in it.
BETA_WINDOW = 120
MIN_BETA_SAMPLE = 60
#: What an unknown name is assumed to be. 1.0 is the market itself - and for a
#: single name that is usually an UNDERSTATEMENT (most single stocks run above
#: 1). So this default makes the book look safer than it is, which is the
#: absence-as-zero failure class (D-038). It is therefore always REPORTED as
#: assumed rather than silently applied.
ASSUMED_BETA = 1.0
BENCHMARK = "SPY"


def beta(sym_closes: list[float], bench_closes: list[float],
         window: int = BETA_WINDOW) -> tuple[float, float] | None:
    """OLS beta against the benchmark, with its R-squared. None if not estimable.

    **The R-squared is returned because the beta is meaningless without it.**
    Measured on our own stored data: MU came out at -0.45 while NVDA came out
    at +1.85 - both semiconductors, over the same 120 sessions. That is not two
    different market sensitivities, it is one estimate dominated by
    name-specific moves. A single-name beta with low explanatory power is a
    number pretending to be knowledge, and shrinking it toward 1.0 in
    proportion to how little it explains is the honest treatment.

    Sign is preserved deliberately. A negative beta is not an error and must
    not be clamped: XLE ran -0.42 correlation to SPY over the same window, and
    a genuinely offsetting position is the entire point of measuring this.
    """
    a, b = _log_returns(sym_closes), _log_returns(bench_closes)
    n = min(len(a), len(b), window)
    if n < MIN_BETA_SAMPLE:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    var_b = sum((y - mb) ** 2 for y in b)
    var_a = sum((x - ma) ** 2 for x in a)
    if var_b <= 0 or var_a <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    raw = cov / var_b
    r2 = (cov * cov) / (var_a * var_b)
    return raw, r2


#: Below this explanatory power the beta says more about one name's own news
#: than about its market sensitivity, so it is shrunk toward the market.
MIN_R2_FOR_FULL_WEIGHT = 0.30


def shrunk_beta(raw: float, r2: float) -> float:
    """Pull a poorly-fitted beta toward 1.0, in proportion to how little it explains.

    Same shrinkage logic already used for stated probabilities (sizing.py): an
    estimate is trusted to the degree it is supported. A beta explaining 5% of
    variance is almost pure noise and should barely move the exposure estimate;
    one explaining 60% is worth taking at close to face value.
    """
    w = min(1.0, max(0.0, r2 / MIN_R2_FOR_FULL_WEIGHT))
    return 1.0 + (raw - 1.0) * w


def betas_for(state_dir: Path, symbols: list[str]) -> tuple[dict[str, float], list[str]]:
    """{symbol: beta} from persisted closes, plus the symbols we had to assume.

    Reads only what the research cycle already stored, so this costs no network
    calls. The benchmark is beta 1.0 by definition, never estimated against
    itself.
    """
    bench = load_closes(state_dir, BENCHMARK, max_age_days=10)
    out: dict[str, float] = {}
    assumed: list[str] = []
    for sym in symbols:
        u = sym.upper()
        if u == BENCHMARK:
            out[u] = 1.0
            continue
        closes = load_closes(state_dir, u, max_age_days=10) if bench else None
        est = beta(closes, bench) if closes and bench else None
        if est is None:
            out[u] = ASSUMED_BETA
            assumed.append(u)
        else:
            raw, r2 = est
            out[u] = shrunk_beta(raw, r2)
            if r2 < MIN_R2_FOR_FULL_WEIGHT:
                assumed.append(u)  # reported: the fit does not support the raw number
    return out, assumed
