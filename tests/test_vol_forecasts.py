"""The stated vol view becomes a scored forecast (I-14).

The agent says "I forecast 8.5% realized; the condors needed sub-7.5%" in
prose every cycle. Nothing resolved it, so the most falsifiable thing it says
moved no calibration and earned no size - which is most of the point of saying
it out loud.

These tests hold the four seams that make the new claim type real: measuring
realized vol over a window, storing a band that is not a price, resolving it
without ever guessing, and the percent-to-fraction conversion that this
project has got wrong in both directions before.
"""

from __future__ import annotations

import json
import math
import random
from types import SimpleNamespace

import pytest

from trdrbot import ledger as ledger_mod
from trdrbot import market_stats
from trdrbot.ledger import PRICE_BAND, REALIZED_VOL_PCT, Ledger


def _series(days: int, daily_vol: float, seed: int = 7,
            start: str = "2026-06-01") -> tuple[list[str], list[float]]:
    """A synthetic close series with a KNOWN per-day volatility.

    Built with a parameter and then measured, the `test_market_stats_beta`
    pattern - a test that measures its own hardcoded output measures nothing.
    """
    from conftest import synthetic_dates

    rng = random.Random(seed)
    price = 100.0
    closes = []
    for _ in range(days):
        price *= math.exp(rng.gauss(0.0, daily_vol))
        closes.append(round(price, 4))
    # Consecutive calendar dates, weekends included: the window filter is
    # calendar based and must not care which days the tape actually traded.
    return synthetic_dates(days, start), closes


# --- measuring realized vol over a window ---------------------------------


def test_realized_vol_between_recovers_a_known_volatility():
    """Annualized, in PERCENT, because that is the unit the claim is stated
    in - the stats block the agent reads quotes "realized vol 21d 12.3%"."""
    daily = 0.01
    dates, closes = _series(200, daily)

    got = market_stats.realized_vol_between(dates, closes, dates[0], dates[-1])

    expected_pct = daily * math.sqrt(market_stats.TRADING_DAYS) * 100
    assert got == pytest.approx(expected_pct, rel=0.15), f"{got} vs ~{expected_pct}"
    assert 10 < got < 25, "a percent, not a fraction - 0.16 here would be a units bug"


def test_the_window_is_the_window_and_nothing_outside_it():
    """A forecast made on the 1st and judged on the 20th is a claim about
    those days. Including the quiet month before it would score a different
    prediction from the one that was made."""
    dates, closes = _series(120, 0.004)
    # A violent month bolted onto the end of a calm series.
    loud_dates, loud_closes = _series(30, 0.04, seed=99, start="2026-11-01")
    dates += loud_dates
    closes += loud_closes

    calm = market_stats.realized_vol_between(dates, closes, "2026-06-01", "2026-09-30")
    loud = market_stats.realized_vol_between(dates, closes, "2026-11-01", "2026-11-30")

    assert loud > calm * 3, f"the window is leaking: calm {calm}, loud {loud}"


def test_a_window_too_short_to_measure_returns_nothing_rather_than_a_number():
    """A vol estimate from four returns is noise wearing a number's clothing,
    and a forecast resolved against it enters calibration as evidence."""
    dates, closes = _series(60, 0.01)

    assert market_stats.realized_vol_between(dates, closes, "2026-06-01", "2026-06-03") is None
    assert market_stats.realized_vol_between([], [], "2026-06-01", "2026-07-01") is None
    assert market_stats.realized_vol_between(dates, closes, "2030-01-01", "2030-02-01") is None


# --- the ledger carries a claim that is not about price -------------------


def test_a_vol_band_round_trips_through_the_ledger(tmp_path):
    book = Ledger(tmp_path / "ledger.jsonl")

    e = book.register(kind=ledger_mod.STANDALONE, underlying="spy",
                      claim="realized stays subdued", probability=0.62,
                      horizon="2026-09-02", band_low=7.0, band_high=9.5,
                      metric=REALIZED_VOL_PCT)

    assert e is not None and e.metric == REALIZED_VOL_PCT
    assert e.holds_at(8.2) is True and e.holds_at(11.0) is False
    # Reloaded from disk by a second reader, which is how housekeeping sees it.
    again = Ledger(tmp_path / "ledger.jsonl")
    assert again.all()[0].metric == REALIZED_VOL_PCT


def test_a_row_written_before_metric_existed_loads_as_the_price_claim_it_was(tmp_path):
    """Every historical row is implicitly a price band. The default is what
    makes this migration a no-op on 100+ rows of live pre-registration."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps({
        "id": "fc_old", "kind": "thesis", "created": "2026-08-01T00:00:00+00:00",
        "underlying": "SPY", "claim": "old row", "probability": 0.6,
        "horizon": "2026-08-10", "band_low": 700.0, "band_high": 780.0,
    }) + "\n", encoding="utf-8")

    e = Ledger(path).all()[0]

    assert e.metric == PRICE_BAND
    assert e.holds_at(740.0) is True


def test_a_vol_claim_and_a_price_claim_are_not_the_same_forecast(tmp_path):
    """The dedup key stops a repeated simulate double-registering one thesis.
    Two claims about DIFFERENT quantities are not that, even if the numbers
    happen to coincide."""
    book = Ledger(tmp_path / "ledger.jsonl")
    common = dict(kind=ledger_mod.STANDALONE, underlying="SPY", claim="c",
                  probability=0.6, horizon="2026-09-02",
                  band_low=7.0, band_high=9.5)

    price = book.register(**common)
    vol = book.register(**common, metric=REALIZED_VOL_PCT)

    assert price is not None and vol is not None and price.id != vol.id


# --- resolution: never guess ----------------------------------------------


def _hk_cfg(tmp_path):
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(state=state)


@pytest.mark.asyncio
async def test_a_vol_forecast_resolves_from_stored_closes_without_touching_the_tape(tmp_path):
    """A vol claim needs no spot at all. Tools are a bare object here, so any
    attempt to fetch one is an AttributeError rather than a silent fallback."""
    from trdrbot.housekeeping import _resolved_value

    state = _hk_cfg(tmp_path).state
    dates, closes = _series(120, 0.01)
    market_stats.save_closes(state, "SPY", closes, dates=dates)
    book = Ledger(tmp_path / "ledger.jsonl")
    e = book.register(kind=ledger_mod.STANDALONE, underlying="SPY", claim="c",
                      probability=0.7, horizon=dates[-1],
                      band_low=1.0, band_high=99.0, metric=REALIZED_VOL_PCT)
    e.created = dates[0] + "T00:00:00+00:00"

    value = await _resolved_value(e, object(), state)

    assert value is not None
    assert value == pytest.approx(
        market_stats.realized_vol_between(dates, closes, dates[0], dates[-1]))
    assert book.resolve(e.id, value, "now").outcome is True


@pytest.mark.asyncio
async def test_a_vol_forecast_with_no_series_is_skipped_not_guessed(tmp_path):
    """Same honesty the missing-spot path has always had. An unresolved
    forecast resolves tomorrow; a wrongly resolved one is in calibration for
    good."""
    from trdrbot.housekeeping import _resolved_value

    state = _hk_cfg(tmp_path).state
    book = Ledger(tmp_path / "ledger.jsonl")
    e = book.register(kind=ledger_mod.STANDALONE, underlying="NOSUCH", claim="c",
                      probability=0.7, horizon="2026-09-02", band_low=1.0,
                      band_high=99.0, metric=REALIZED_VOL_PCT)

    assert await _resolved_value(e, object(), state) is None

    # And a series with closes but no dates is a sample, not a series: it can
    # bootstrap, and it cannot locate a calendar window.
    market_stats.save_closes(state, "NOSUCH", [100.0] * 120)
    assert await _resolved_value(e, object(), state) is None


@pytest.mark.asyncio
async def test_a_resolved_vol_forecast_reaches_calibration_like_any_other(tmp_path):
    """`as_forecasts` needs no metric branch, and that is correct: calibration
    asks "when this agent says 70%, does it happen 70% of the time" - a
    question that does not care what the claim was about."""
    from trdrbot import calibration
    from trdrbot.housekeeping import _resolved_value

    state = _hk_cfg(tmp_path).state
    dates, closes = _series(120, 0.01)
    market_stats.save_closes(state, "SPY", closes, dates=dates)
    book = Ledger(tmp_path / "ledger.jsonl")
    e = book.register(kind=ledger_mod.STANDALONE, underlying="SPY", claim="c",
                      probability=0.7, horizon=dates[-1], band_low=1.0,
                      band_high=99.0, metric=REALIZED_VOL_PCT)
    e.created = dates[0] + "T00:00:00+00:00"

    book.resolve(e.id, await _resolved_value(e, object(), state), "now")

    forecasts = ledger_mod.as_forecasts(book.all())
    assert len(forecasts) == 1 and forecasts[0].outcome is True
    assert calibration.score(forecasts).n == 1


# --- the tool the agent actually calls -------------------------------------


def _forecast_tool(tmp_path, book):
    from trdrbot.local_tools import build_record_forecast

    return build_record_forecast(book, state_dir=_hk_cfg(tmp_path).state).func


def test_the_tool_records_a_vol_claim_and_says_so_in_percent(tmp_path):
    book = Ledger(tmp_path / "ledger.jsonl")

    out = _forecast_tool(tmp_path, book)(
        underlying="SPY", claim="realized stays subdued", probability=0.62,
        horizon="2026-09-02", band_low=7.0, band_high=9.5, metric="realized_vol")

    assert "realized vol" in out and "[7.0%, 9.5%]" in out
    assert book.all()[0].metric == REALIZED_VOL_PCT


def test_an_unknown_metric_is_refused_by_name_rather_than_stored_as_a_price(tmp_path):
    book = Ledger(tmp_path / "ledger.jsonl")

    out = _forecast_tool(tmp_path, book)(
        underlying="SPY", claim="c", probability=0.6, horizon="2026-09-02",
        band_low=7.0, band_high=9.5, metric="variance_swap")

    assert out.startswith("REFUSED") and "realized_vol" in out
    assert book.all() == []


def test_a_vol_claim_skips_the_price_anchored_vacuity_check(tmp_path):
    """The vacuity anchor bootstraps a PRICE distribution, so [7.0, 9.5] would
    read as "SPY between $7 and $9.50" - a certainty, refused. Judging a claim
    by the wrong ruler is worse than not judging it."""
    state = _hk_cfg(tmp_path).state
    _, closes = _series(200, 0.01)
    market_stats.save_closes(state, "SPY", closes)
    book = Ledger(tmp_path / "ledger.jsonl")

    # Agreeing with a base rate of ~100% is what the guard refuses.
    priced = _forecast_tool(tmp_path, book)(
        underlying="SPY", claim="c", probability=0.97, horizon="2026-09-02",
        band_low=1.0, band_high=100000.0)
    vol = _forecast_tool(tmp_path, book)(
        underlying="SPY", claim="c", probability=0.97, horizon="2026-09-02",
        band_low=7.0, band_high=9.5, metric="realized_vol")

    assert priced.startswith("REFUSED"), "the price guard must still bite"
    assert not vol.startswith("REFUSED")
