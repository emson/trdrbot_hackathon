"""Beta, and the alignment it silently depended on.

The stored cache is written per-symbol as each ticker is researched, with a
ten-day staleness window allowed independently per symbol - so two series
routinely come from different days. Beta paired them by array POSITION, which
is only correct if that never happens.

Measured on the live cache before the fix, QQQ against SPY: +0.10 at an
R-squared of 0.004 as stored; +1.48 at 0.841 once realigned by one session.
Downstream this feeds beta_weighted_delta and the CONCENTRATED warning the
decide prompt shows the agent.
"""

from __future__ import annotations

import math
import random

from conftest import synthetic_dates

from trdrbot import market_stats


def _series(n: int = 200, beta: float = 1.5, seed: int = 7) -> tuple[list[float], list[float]]:
    """A benchmark and a symbol with a KNOWN beta, so the estimator has a
    right answer to be measured against rather than merely a plausible one."""
    rng = random.Random(seed)
    bench, sym = [100.0], [50.0]
    for _ in range(n):
        r = rng.gauss(0.0, 0.01)
        bench.append(bench[-1] * math.exp(r))
        sym.append(sym[-1] * math.exp(beta * r))
    return bench, sym


def test_beta_recovers_a_known_value_when_the_series_are_aligned(tmp_path):
    bench, sym = _series()
    dates = synthetic_dates(len(bench))
    market_stats.save_closes(tmp_path, "SPY", bench, dates=dates)
    market_stats.save_closes(tmp_path, "QQQ", sym, dates=dates)

    betas, assumed = market_stats.betas_for(tmp_path, ["QQQ"])

    assert abs(betas["QQQ"] - 1.5) < 0.05, betas
    assert assumed == []


def test_a_one_session_offset_does_not_destroy_the_estimate(tmp_path):
    """THE regression. The symbol was fetched a day before the benchmark - the
    ordinary case for a cache written per-symbol - so a positional zip compared
    Monday's move against Tuesday's. On a series with a true beta of 1.50 and
    an R-squared of 1.000, that returns -0.087 at R-squared 0.003."""
    bench, sym = _series()
    dates = synthetic_dates(len(bench))
    market_stats.save_closes(tmp_path, "SPY", bench, dates=dates)
    # QQQ's cache is one session behind: same history, stopped a day earlier.
    market_stats.save_closes(tmp_path, "QQQ", sym[:-1], dates=dates[:-1])

    betas, assumed = market_stats.betas_for(tmp_path, ["QQQ"])

    assert abs(betas["QQQ"] - 1.5) < 0.05, f"misaligned estimate: {betas['QQQ']}"
    assert assumed == []


def test_positional_pairing_really_would_have_broken_it(tmp_path):
    """Pins the defect itself, so the fix cannot be quietly undone: the same
    two series compared position-by-position give an answer with no
    relationship to the truth."""
    bench, sym = _series()
    misaligned = market_stats.beta(sym[:-1], bench[1:])

    assert misaligned is not None
    raw, r2 = misaligned
    assert abs(raw - 1.5) > 1.0, "expected the positional estimate to be badly wrong"
    assert r2 < 0.05, "expected the positional estimate to explain almost nothing"


def test_a_series_with_no_stored_dates_is_assumed_rather_than_guessed(tmp_path):
    """Every file written before this fix has no `dates`. Those must degrade to
    the reported assumption, not to a positional estimate - honest ignorance
    beats a confident wrong number, and the next research pass self-heals it."""
    bench, sym = _series()
    market_stats.save_closes(tmp_path, "SPY", bench)  # legacy shape, no dates
    market_stats.save_closes(tmp_path, "QQQ", sym)

    betas, assumed = market_stats.betas_for(tmp_path, ["QQQ"])

    assert betas["QQQ"] == market_stats.ASSUMED_BETA
    assert assumed == ["QQQ"]


def test_too_little_overlap_is_assumed_rather_than_estimated(tmp_path):
    """Two dated series that barely overlap cannot support an estimate, and
    MIN_BETA_SAMPLE is what says so."""
    bench, sym = _series()
    dates = synthetic_dates(len(bench))
    market_stats.save_closes(tmp_path, "SPY", bench, dates=dates)
    keep = market_stats.MIN_BETA_SAMPLE // 2
    market_stats.save_closes(tmp_path, "QQQ", sym[:keep], dates=dates[:keep])

    betas, assumed = market_stats.betas_for(tmp_path, ["QQQ"])

    assert betas["QQQ"] == market_stats.ASSUMED_BETA
    assert assumed == ["QQQ"]


def test_the_benchmark_is_never_estimated_against_itself(tmp_path):
    bench, _ = _series()
    market_stats.save_closes(tmp_path, "SPY", bench, dates=synthetic_dates(len(bench)))

    betas, assumed = market_stats.betas_for(tmp_path, ["SPY"])

    assert betas["SPY"] == 1.0 and assumed == []


def test_saving_without_dates_stays_readable_by_the_bootstrap(tmp_path):
    """`dates` is additive. A file with none is still a perfectly good sample
    for everything that does not need alignment, and `load_closes` - which the
    bootstrap uses - must not have become stricter."""
    bench, _ = _series()
    market_stats.save_closes(tmp_path, "SPY", bench)

    assert market_stats.load_closes(tmp_path, "SPY") == bench
    assert market_stats.load_dated_closes(tmp_path, "SPY") is None
