"""One test per bug this system has actually had.

Not coverage for its own sake - every test here is a real failure that reached
running code, named by its decision record. The discipline (D-038): a bug is
not fixed until the test that would have caught it exists. Verification done
in a throwaway shell snippet protects nothing the next time someone edits the
file.

All tests are pure and offline. The bugs were in logic, not in the network.
"""

from __future__ import annotations

import math
import random
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from trdrbot import discovery, experiments, local_tools, market_stats, optmath, sizing
from trdrbot.analytics import Snapshot
from trdrbot.exit_rules import evaluate, watched_signals
from trdrbot.housekeeping import _materiality_band
from trdrbot.optmath import Leg
from trdrbot.positions import Position, PositionStore
from trdrbot.sizing import Calibration


# --------------------------------------------------------------- helpers

def gbm(n=300, sigma=0.20, seed=7, drift_per_day=0.0):
    rng = random.Random(seed)
    sd = sigma / math.sqrt(252)
    out = [100.0]
    for _ in range(n):
        out.append(out[-1] * math.exp(rng.gauss(drift_per_day - 0.5 * sd * sd, sd)))
    return out


def pos(**kw):
    kw.setdefault("status", "open")
    kw.setdefault("underlying", "SPY")
    kw.setdefault("legs", [{"symbol": "A", "side": "sell", "qty": 1}])
    return Position(position_id="t", **kw)


def snap(mark_pnl=None, underlying=None):
    s = Snapshot()
    if underlying is not None:
        s.underlying_prices = {"SPY": underlying}
    if mark_pnl is not None:
        s.broker_positions = [{"symbol": "A", "cost_basis": 100, "unrealized_pl": mark_pnl}]
    return s


ESTABLISHED = Calibration(n=30, brier=0.18, reliability=0.02,
                          resolution=0.05, uncertainty=0.24, base_rate=0.5)


# ------------------------------------------------- D-032 bootstrap drift

def test_bootstrap_is_demeaned_so_sample_luck_is_not_projected():
    """Raw resampling inherited the sample period's directional luck - a year
    that happened to rally was projected forward as structural. Caught by this
    convergence check, which failed by 16pp before demeaning."""
    closes = gbm(sigma=0.20, drift_per_day=0.0008)  # deliberately lucky path
    spot = closes[-1]
    legs = [Leg.parse({"right": "C", "strike": round(spot), "side": "long",
                       "qty": 1, "price": 2.0})]
    factors = market_stats.bootstrap_factors(closes, 21, n_paths=4000, seed="t")
    boot = sum(1 for f in factors if optmath.pnl_at(legs, spot * f) > 0) / len(factors)
    lognormal = optmath.prob_profit(legs, spot, 0.20, 21)
    assert abs(boot - lognormal) < 0.04, (
        f"bootstrap {boot:.3f} vs lognormal {lognormal:.3f} - sample drift leaking through"
    )


def test_bootstrap_is_martingale_without_a_stated_view():
    closes = gbm()
    factors = market_stats.bootstrap_factors(closes, 21, n_paths=4000, seed="t")
    assert abs(sum(factors) / len(factors) - 1.0) < 0.01


def test_bootstrap_drift_is_applied_deliberately():
    closes = gbm()
    for d in (-0.03, 0.0, 0.03):
        f = market_stats.bootstrap_factors(closes, 21, n_paths=4000, seed="t", drift=d)
        assert abs(sum(f) / len(f) - (1 + d)) < 0.01


def test_bootstrap_refuses_insufficient_history():
    assert market_stats.bootstrap_factors(gbm(n=30), 21) == []


# ------------------------------------- D-034 interim scoring accumulation

def test_materiality_bands_speak_the_unit_the_caller_passes():
    """The bands were 25.0/50.0 against a caller passing a FRACTION, so band 1
    needed +2500% and interim scoring was dead from the day it was added -
    silently, because `health` reported the eight rows written before the
    bands existed. Both these tests passed throughout: they spoke percents,
    the caller spoke fractions, and each was internally consistent.

    So the unit is pinned to its ONE producer rather than to a literal."""
    from trdrbot.analytics import Snapshot, position_pnl_pct
    from trdrbot.housekeeping import INTERIM_BANDS

    # A debit spread: $2,000 paid, now worth $600 less. -30% by any trader's
    # reckoning, and materially past the first band.
    snap = Snapshot(broker_positions=[
        {"symbol": "X1", "cost_basis": 3000.0, "unrealized_pl": -600.0},
        {"symbol": "X2", "cost_basis": -1000.0, "unrealized_pl": 0.0},
    ])
    pnl = position_pnl_pct(["X1", "X2"], snap)
    assert abs(pnl - (-0.30)) < 1e-9, "P&L is a fraction of NET entry cost"
    assert max(INTERIM_BANDS) < 1.0, "bands must be fractions, like their input"
    assert _materiality_band(pnl) == 1, "a real -30% move must be material"


def test_noise_marks_never_fire_interim_scoring():
    """Eight interim scores accumulated on one unresolved position - 0.8 of
    evidence against a resolution's 1.0 - all from a -$45 bid/ask wobble."""
    band, fired = 0, 0
    for pnl in [-0.031, -0.042, -0.028, -0.035, -0.040, -0.032, -0.029, -0.036]:
        b = _materiality_band(pnl)
        if b > band:
            band, fired = b, fired + 1
    assert fired == 0


def test_interim_scoring_is_bounded_and_monotonic():
    band, fired = 0, 0
    for pnl in [-0.03, -0.12, -0.27, -0.31, -0.26, -0.30, -0.55, -0.52, -0.58]:  # incl. oscillation
        b = _materiality_band(pnl)
        if b > band:
            band, fired = b, fired + 1
    assert fired == 2, "at most one score per materiality band, never re-fired"
    assert fired * 0.1 < 1.0, "cumulative interim weight must stay under a resolution"


# ------------------------------------------------ D-037 exit rule engine

def test_debounce_state_is_per_rule_not_per_type():
    """Two underlying stops at different levels shared one debounce history."""
    p = pos(exit_rules=[{"type": "underlying_stop", "direction": "below", "level": 750.0},
                        {"type": "underlying_stop", "direction": "below", "level": 740.0}])
    evaluate(p, snap(underlying=745.0), "2099-01-01")
    evaluate(p, snap(underlying=745.0), "2099-01-01")
    assert p.exit_state["underlying:below:740"] == [False, False]
    assert p.exit_state["underlying:below:750"] == [True, True]


def test_stop_beats_profit_target_when_both_breach():
    """Resolved by list order before - a position at both could book a
    fictional win depending on which the agent listed first."""
    p = pos(exit_rules=[{"type": "profit_target", "threshold": "-10%"},
                        {"type": "stop_loss", "threshold": "-5%"}])
    s = snap(mark_pnl=-8)
    evaluate(p, s, "2099-01-01")
    assert evaluate(p, s, "2099-01-01")[0] == "stop_loss"


def test_deadline_outranks_everything():
    p = pos(exit_rules=[{"type": "profit_target", "threshold": "50%"}])
    s = snap(mark_pnl=+80)
    today = date.today().isoformat()
    evaluate(p, s, today)
    assert evaluate(p, s, today)[0] == "deadline"


def test_unobservable_signal_holds_never_fires_blind():
    p = pos(exit_rules=[{"type": "underlying_stop", "direction": "below", "level": 757.5}])
    assert evaluate(p, snap(underlying=None), "2099-01-01")[0] is None


def test_single_wide_quote_does_not_trigger_a_stop():
    p = pos(exit_rules=[{"type": "stop_loss", "basis": "position_mark", "threshold": "-100%"}])
    assert evaluate(p, snap(mark_pnl=-105), "2099-01-01")[0] is None
    assert evaluate(p, snap(mark_pnl=-20), "2099-01-01")[0] is None


def test_decisive_breach_skips_debounce_on_both_conventions():
    """One overshoot rule must mean 2x for a percentage and 1% for a price."""
    p = pos(exit_rules=[{"type": "stop_loss", "threshold": "-100%"}])
    assert "decisive" in evaluate(p, snap(mark_pnl=-250), "2099-01-01")[1]
    q = pos(exit_rules=[{"type": "underlying_stop", "direction": "below", "level": 757.5}])
    assert "decisive" in evaluate(q, snap(underlying=748.0), "2099-01-01")[1]


def test_legacy_rule_shapes_still_evaluate():
    """Position files written before the registry carry `basis` and "-100%"."""
    p = pos(exit_rules=[{"type": "stop_loss", "basis": "position_mark", "threshold": "-100%"}])
    s = snap(mark_pnl=-110)
    assert evaluate(p, s, "2099-01-01")[0] is None
    assert evaluate(p, s, "2099-01-01")[0] == "stop_loss"


def test_stale_pre_registry_debounce_state_self_heals():
    p = pos(exit_rules=[{"type": "stop_loss", "threshold": "-50%"}],
            exit_state={"stop_loss": [True, True], "profit_target": [False]})
    evaluate(p, snap(mark_pnl=-10), "2099-01-01")
    assert all(":" in k for k in p.exit_state)


def test_time_stop_fires_immediately_time_is_not_noisy():
    p = pos(expiry=(date.today() + timedelta(days=1)).isoformat(),
            exit_rules=[{"type": "time_stop", "days_before_expiry": 1}])
    assert evaluate(p, snap(), "2099-01-01")[0] == "time_stop"


def test_watched_signals_exposes_a_mark_only_position():
    """F1's root cause: a narrated invalidation level nothing enforced."""
    mark_only = pos(exit_rules=[{"type": "stop_loss", "threshold": "-50%"}])
    guarded = pos(exit_rules=[{"type": "underlying_stop", "direction": "below", "level": 757.5}])
    assert "underlying" not in watched_signals(mark_only)
    assert "underlying" in watched_signals(guarded)


# ------------------------------------------------------- D-037 risk caps

def _size(**kw):
    base = dict(equity=100_000, stated_confidence=0.70, max_profit=800.0,
                max_loss=-1200.0, calibration=ESTABLISHED)
    return sizing.size_position(**{**base, **kw})


def test_concentration_cap_refuses_more_of_the_same_name():
    d = _size(underlying="SPY", open_risk_usd=7_500,
              open_risk_by_underlying={"SPY": 7_500})
    assert d.contracts == 0 and "concentration" in d.reason


def test_concentration_cap_still_permits_diversification():
    """The old count divisor punished an uncorrelated name just as hard."""
    d = _size(underlying="NVDA", open_risk_usd=7_500,
              open_risk_by_underlying={"SPY": 7_500})
    assert d.contracts > 0


def test_portfolio_cap_refuses_when_the_book_is_full():
    d = _size(underlying="META", open_risk_usd=14_500,
              open_risk_by_underlying={"SPY": 5_000, "NVDA": 5_000, "QQQ": 4_500})
    assert d.contracts == 0 and "portfolio" in d.reason


def test_caps_shrink_to_fit_rather_than_refuse_outright():
    partial = _size(underlying="META", open_risk_usd=12_000,
                    open_risk_by_underlying={"SPY": 12_000})
    full = _size(underlying="META")
    assert 0 < partial.contracts < full.contracts


def test_unbounded_loss_is_refused_not_estimated():
    d = _size(max_loss=None, max_profit=None)
    assert d.contracts == 0 and "unbounded" in d.reason.lower()


def test_no_record_sizes_minimally_rather_than_refusing():
    """Deliberate behaviour change (D-048). This once asserted 0 contracts,
    which encoded the deadlock: shrinking an unmeasured confidence to the base
    rate and then letting Kelly VETO meant a first trade was impossible, so the
    record that unlocks size could never be built. Below MIN_SAMPLE the
    shrinkage is a blunt heuristic and must size down, never veto. A proven
    record still buys strictly more."""
    empty = Calibration(n=0, brier=None, reliability=None, resolution=None,
                        uncertainty=None, base_rate=None)
    unproven = _size(calibration=empty, max_profit=3600.0, max_loss=-1200.0).contracts
    proven = _size(calibration=ESTABLISHED, max_profit=3600.0, max_loss=-1200.0).contracts
    assert unproven >= 1, "must be able to place a first trade"
    assert proven > unproven, "a proven record must still buy more"


def test_a_none_posture_never_raises():
    """A None posture once dereferenced posture.tier and raised - the
    competence ladder must not break callers that predate it."""
    empty = Calibration(n=0, brier=None, reliability=None, resolution=None,
                        uncertainty=None, base_rate=None)
    assert _size(calibration=empty).reason


# ------------------------------------------------- D-035 LLM unit confusion

def test_percentage_bands_are_rejected_as_prices():
    """The LLM emitted [-6.0, 8.0] on an $87 stock. holds_at() would have been
    always-False and attribution would have scored every thesis as failed."""
    assert not discovery._plausible_band({"band_low": -6.0, "band_high": 8.0}, 87.0)
    assert not discovery._plausible_band({"band_low": 5.0, "band_high": None}, 766.0)
    assert discovery._plausible_band({"band_low": 745.0, "band_high": 790.0}, 766.0)
    assert discovery._plausible_band({"band_low": None, "band_high": 736.0}, 723.0)


# ------------------------------------------------------- optmath invariants

def test_long_straddle_has_unbounded_profit():
    legs = [Leg.parse({"right": "C", "strike": 100, "side": "long", "qty": 1, "price": 2}),
            Leg.parse({"right": "P", "strike": 100, "side": "long", "qty": 1, "price": 2})]
    mp, ml = optmath.max_profit_loss(legs)
    assert mp is None, "unbounded upside must be None, never a finite sample maximum"
    assert ml is not None


def test_calendar_spreads_are_refused_not_approximated():
    legs = [Leg.parse({"right": "C", "strike": 100, "side": "long", "qty": 1,
                       "price": 2, "expiry": "2026-09-04"}),
            Leg.parse({"right": "C", "strike": 100, "side": "short", "qty": 1,
                       "price": 1, "expiry": "2026-09-11"})]
    with pytest.raises(optmath.MultiExpiryError):
        optmath.pnl_at(legs, 100.0)


def test_thesis_without_a_band_is_unscoreable_not_assumed_true():
    t = experiments.Thesis(claim="vibes", underlying="SPY", horizon="2026-09-04")
    assert t.holds_at(766.0) is None


def test_lucky_win_teaches_nothing():
    """Updated deliberately (D-072): this asserted `== 0.5`, which was the bug.
    elfmem's update is a Beta posterior mean, so a 0.5 signal is not neutral -
    it drags a block toward 0.5 from wherever it sits. Measured with elfmem's
    own function against the live database: it moved the constitution -0.250
    and moved a prediction that had ALREADY MISSED +0.018, punishing what was
    right and rewarding what was wrong. Teaching nothing means applying
    nothing."""
    verdict, _ = experiments.attribute(thesis_held=False, profited=True)
    assert experiments.ATTRIBUTION_SIGNAL[verdict] is None, \
        "a lucky win must apply NO update, not an update toward 0.5"


def test_a_neutral_signal_is_not_neutral_which_is_why_luck_applies_none():
    """The arithmetic that forced the change above, pinned so it cannot be
    argued away: the same 0.5 'neutral' signal moves two blocks in OPPOSITE
    directions depending only on where they already sit."""
    from elfmem.operations.outcome import compute_bayesian_update_ab as upd

    _, _, high = upd(1.0, 0.0, 0.5, 1.0)    # a block at confidence 1.0
    _, _, low = upd(3.1, 7.9, 0.5, 1.0)     # a block at confidence ~0.28
    assert high < 1.0, "0.5 PUNISHES a high-confidence block"
    assert low > 3.1 / 11.0, "0.5 REWARDS a discredited block"


# ------------------------------------------------------- position storage

def test_position_round_trips_new_risk_fields():
    d = Path(tempfile.mkdtemp())
    store = PositionStore(d)
    p = Position(position_id="pos_x", status="open", underlying="CRM",
                 interim_band=1, max_loss_usd=3600.0)
    store.save(p)
    back = [q for q in store.all() if q.position_id == "pos_x"][0]
    assert back.interim_band == 1
    assert back.max_loss_usd == 3600.0


# ------------------------------------------------- D-038 the detector itself

def test_health_flags_a_position_that_counts_as_zero_risk():
    from trdrbot import health
    p = Position(position_id="pos_x", status="open", underlying="SPY",
                 exit_rules=[{"type": "stop_loss", "threshold": "-50%"}])
    findings = health.check(Path(tempfile.mkdtemp()) / "none.jsonl", [p])
    assert any(f[0] == health.BAD and "max_loss_usd" in f[2] for f in findings)


def test_health_flags_a_subsystem_that_runs_but_never_produces():
    """The shape of every serious bug here: ran fine, produced nothing, logs
    read healthy."""
    from trdrbot import health
    d = Path(tempfile.mkdtemp())
    j = d / "journal.jsonl"
    j.write_text("\n".join(
        '{"kind": "attribution_run", "pending": 2, "attributed": 0, "skipped_no_price": 2}'
        for _ in range(4)
    ))
    findings = health.check(j, [])
    assert any(f[0] == health.BAD and f[1] == "attribution" for f in findings)
    assert any("skipped for want of a price" in f[2] for f in findings)


def test_health_stays_quiet_while_a_subsystem_is_merely_young():
    from trdrbot import health
    d = Path(tempfile.mkdtemp())
    j = d / "journal.jsonl"
    j.write_text('{"kind": "attribution_run", "pending": 0, "attributed": 0}')
    findings = health.check(j, [])
    assert not any(f[0] == health.BAD and f[1] == "attribution" for f in findings), (
        "one quiet run is not evidence of failure"
    )


# ---------------------------------------- thesis-missing-at-entry (D-038)

def test_health_flags_a_position_with_no_thesis_at_all():
    """The very first position ever opened: get_option_chain -> place_order ->
    record_position with simulate_experiments never called in between, so
    shared["thesis"] was never set. Worse than an unfalsifiable thesis - this
    position can NEVER be attributed, and nothing noticed."""
    from trdrbot import health
    p = Position(position_id="pos_x", status="open", underlying="SPY",
                 max_loss_usd=2210.0, thesis_claim="",
                 exit_rules=[{"type": "underlying_stop", "direction": "below", "level": 750.0}])
    findings = health.check(Path(tempfile.mkdtemp()) / "none.jsonl", [p])
    assert any(f[0] == health.BAD and "no thesis recorded" in f[2] for f in findings)


def test_record_position_warns_when_simulate_was_skipped():
    import tempfile as tf
    from trdrbot.calibration import CalibrationStore
    d = Path(tf.mkdtemp())
    store = PositionStore(d)
    calib = CalibrationStore(d / "c.json")
    rec = local_tools.build_record_position(store, "dec_z", shared={}, calibration=calib)
    msg = rec.func(underlying="SPY", strategy="x",
                   legs=[{"symbol": "A", "side": "sell", "qty": 1}],
                   thesis="prose the model wrote, but never wired to shared",
                   confidence=0.6, expiry="2026-09-04")
    assert "no thesis on file" in msg
    pos = store.all()[0]
    assert pos.thesis_claim == ""  # the free-text `thesis` arg is NOT thesis_claim


# ---------------------------------------------------- D-040 greeks layer

def test_bull_put_spread_shape_is_bullish_theta_income_short_vol():
    legs = [Leg.parse({"right": "P", "strike": 755, "side": "short", "qty": 5, "price": 0.6}),
            Leg.parse({"right": "P", "strike": 750, "side": "long", "qty": 5, "price": 0.3})]
    g = optmath.net_greeks(legs, 766.0, 0.13, 6)
    assert g["delta_dollars"] > 0 and g["theta_dollars"] > 0 and g["vega_dollars"] < 0


def test_long_straddle_shape_is_flat_delta_long_gamma_pays_theta():
    legs = [Leg.parse({"right": "C", "strike": 766, "side": "long", "qty": 1, "price": 4}),
            Leg.parse({"right": "P", "strike": 766, "side": "long", "qty": 1, "price": 4})]
    g = optmath.net_greeks(legs, 766.0, 0.13, 6)
    assert abs(g["delta_shares"]) < 12 and g["gamma_shares"] > 0
    assert g["theta_dollars"] < 0 and g["vega_dollars"] > 0


def test_greeks_refuse_expiring_and_zero_vol_rather_than_extrapolate():
    assert optmath.bs_greeks("C", 100, 100, 0.2, 0) is None
    assert optmath.bs_greeks("C", 100, 100, 0.0, 5) is None
    legs = [Leg.parse({"right": "C", "strike": 766, "side": "long", "qty": 1, "price": 4})]
    assert optmath.net_greeks(legs, 766.0, 0.0, 6) is None


def test_put_call_delta_parity_at_zero_rates():
    c = optmath.bs_greeks("C", 100, 100, 0.2, 7)
    p = optmath.bs_greeks("P", 100, 100, 0.2, 7)
    assert abs(c["delta"] - p["delta"] - 1.0) < 1e-9


def test_gamma_explodes_toward_expiry():
    g7 = optmath.bs_greeks("C", 766, 766, 0.13, 7)["gamma"]
    g1 = optmath.bs_greeks("C", 766, 766, 0.13, 1)["gamma"]
    assert g1 / g7 > 2, "the near-expiry warning must rest on a real effect"


def test_per_leg_iv_changes_net_vega_skew_is_measurable():
    flat = optmath.net_greeks(
        [Leg.parse({"right": "P", "strike": 755, "side": "short", "qty": 1, "price": 1}),
         Leg.parse({"right": "C", "strike": 777, "side": "short", "qty": 1, "price": 1})],
        766.0, 0.12, 6)
    skew = optmath.net_greeks(
        [Leg.parse({"right": "P", "strike": 755, "side": "short", "qty": 1, "price": 1, "iv_pct": 16.5}),
         Leg.parse({"right": "C", "strike": 777, "side": "short", "qty": 1, "price": 1, "iv_pct": 7.4}),],
        766.0, 0.12, 6)
    assert abs(skew["vega_dollars"] - flat["vega_dollars"]) > 0.5


def test_occ_symbols_parse_and_reject():
    o = optmath.parse_occ("SPY260902P00755000")
    assert o == {"underlying": "SPY", "expiry": "2026-09-02", "right": "P", "strike": 755.0}
    assert optmath.parse_occ("SPY") is None
    assert optmath.parse_occ("") is None


def test_expected_move_is_rendered_next_to_the_thesis_band():
    th = experiments.Thesis(claim="range", underlying="SPY", horizon="2026-09-02",
                            band_low=755.0, band_high=785.0)
    e = experiments.Experiment("s", [
        Leg.parse({"right": "P", "strike": 755, "side": "short", "qty": 1, "price": 0.6}),
        Leg.parse({"right": "P", "strike": 750, "side": "long", "qty": 1, "price": 0.3})])
    out = experiments.render_comparison(th, [(e, experiments.simulate(e, th, 766.42, 0.105, 6))])
    assert "expected move" in out and "GREEKS" in out


def test_book_greeks_sums_and_reports_unpriced_positions():
    from trdrbot.analytics import book_greeks
    good = Position(position_id="a", status="open", underlying="SPY", entry_iv=0.13,
                    legs=[{"symbol": "SPY990902P00755000", "side": "sell", "qty": 5},
                          {"symbol": "SPY990902P00750000", "side": "buy", "qty": 5}])
    legacy = Position(position_id="b", status="open", underlying="QQQ",
                      legs=[{"symbol": "QQQ990902P00700000", "side": "sell", "qty": 1}])
    bg = book_greeks([good, legacy], {"SPY": 766.0, "QQQ": 723.0})
    assert bg is not None
    assert bg["positions_priced"] == 1 and bg["positions_skipped"] == 1
    assert bg["delta_dollars"] > 0  # the priced bull put spread is bullish
    assert book_greeks([legacy], {"QQQ": 723.0}) is None


# ------------------------------------------------ D-041 constitution

def test_constitution_fits_the_self_frame_budget():
    """The SELF frame renders greedily and BREAKS at the first block that
    overflows - principles past the budget vanish with no error. Measured at
    499 tokens before trimming, against a 600 budget that template overhead
    eats into."""
    from trdrbot import constitution
    assert constitution.estimate_tokens() <= constitution.CONSTITUTION_TOKEN_CEILING
    assert constitution.CONSTITUTION_TOKEN_CEILING < constitution.SELF_FRAME_TOKEN_BUDGET


def test_every_principle_is_traceable_and_cued():
    """notes/009's standing test: a principle you cannot trace is a platitude.
    And block 5 applied to itself - a cueless block is lexically inert."""
    from trdrbot import constitution
    for p in constitution.PRINCIPLES:
        assert p.traces_to.strip(), f"{p.key} cites no incident"
        assert p.cue.strip() and not p.cue.lower().startswith("when relevant")
        assert len(p.text) // 4 <= 45, f"{p.key} is too long for a scarce frame"


def test_constitution_keys_are_unique():
    from trdrbot import constitution
    keys = [p.key for p in constitution.PRINCIPLES]
    assert len(keys) == len(set(keys))


# ------------------------------------- D-042 the loop that must actually turn

def test_latest_trade_response_is_parsed_from_its_real_shape():
    """The live response nests under `trades`, not the symbol. The original
    parser looked one level too shallow, left underlying_prices EMPTY without
    raising, and so made every underlying_stop rule inert in production - while
    passing every unit test, because the tests supplied the price map directly.
    A parser test must use a REAL captured response."""
    from trdrbot.analytics import _f
    real = {"trades": {"SPY": {"c": [" "], "i": 52983527340113, "p": 767.46,
                               "s": 40, "t": "2026-08-27T13:35:35Z", "x": "V", "z": "B"}}}
    node = (real.get("trades") or {}).get("SPY") or real.get("SPY")
    assert _f((node or {}).get("p"), 0.0) == 767.46


def test_credit_assignment_excludes_the_constitution():
    """A losing trade must not degrade identity. Principles carry PERMANENT
    decay, so P&L-driven damage to them would never recover, and D-033 puts
    them under human-ratified incident review instead."""
    p = Position(position_id="x", elfmem_blocks={
        "self": ["c1", "c2"], "task": ["t1"], "attention": ["a1", "a2"]})
    assert set(p.all_elfmem_block_ids) == {"t1", "a1", "a2"}
    assert set(p.recalled_block_ids()) == {"c1", "c2", "t1", "a1", "a2"}


def test_material_move_wakes_the_agent_through_the_idle_ladder():
    """The system was purely reactive: an empty inbox meant no reasoning, even
    with the market open and a live position moving. No trader waits for a
    headline to check their book.

    This used to test `tick._market_pulse`, which was defined, tested and NEVER
    CALLED - `idle.decide` had absorbed the rung and kept its own copy of the
    two thresholds. The test passed for as long as the function was dead. It
    now exercises the path production actually takes."""
    from datetime import datetime, timezone
    from trdrbot import idle

    just_now = datetime.now(timezone.utc)
    pos = Position(position_id="p", status="open", underlying="SPY", entry_spot=766.5)

    def rung(price, positions=(pos,)):
        return idle.decide(
            market_open=True, positions=list(positions),
            underlying_prices={"SPY": price}, last_decision_at=just_now,
            last_hunt_at=just_now, open_risk_usd=2_000.0, equity=100_000.0,
            risk_cap_fraction=0.15, minutes_to_close_=120.0,
        ).level

    assert rung(766.6) == "sleep", "must not fire on noise"
    assert rung(766.5 * (1 + idle.MATERIAL_MOVE * 1.5)) == "review"
    assert rung(766.5 * (1 - idle.MATERIAL_MOVE * 1.5)) == "review"

    # And the thresholds live in exactly one place now.
    import trdrbot.tick as tick_mod
    assert not hasattr(tick_mod, "PULSE_MOVE"), "duplicate threshold reintroduced"
    assert not hasattr(tick_mod, "_market_pulse"), "dead pulse reintroduced"


# -------------------------------------------- D-043 the idle ladder

def _idle(**kw):
    from datetime import datetime, timedelta, timezone
    from trdrbot import idle
    now = datetime.now(timezone.utc)
    base = dict(market_open=True, positions=[], underlying_prices={},
                last_decision_at=now - timedelta(minutes=5),
                last_hunt_at=now - timedelta(minutes=5),
                open_risk_usd=0.0, equity=100_000, risk_cap_fraction=0.15,
                minutes_to_close_=180.0)
    return idle.decide(**{**base, **kw})


def _held(spot=766.5):
    return Position(position_id="p", status="open", underlying="SPY",
                    entry_spot=spot, max_loss_usd=2210.0)


def test_idle_sleeps_when_the_book_is_quiet_and_recently_checked():
    a = _idle(positions=[_held()], underlying_prices={"SPY": 766.9},
              open_risk_usd=14_500)
    assert a.level == "sleep"


def test_idle_reviews_on_a_material_move_under_a_held_position():
    a = _idle(positions=[_held()], underlying_prices={"SPY": 761.9},
              open_risk_usd=14_500)
    assert a.level == "review" and "-0.6" in a.reason


def test_idle_reviews_after_too_long_without_looking():
    from datetime import datetime, timedelta, timezone
    a = _idle(positions=[_held()], underlying_prices={"SPY": 766.9},
              open_risk_usd=14_500,
              last_decision_at=datetime.now(timezone.utc) - timedelta(minutes=125))
    assert a.level == "review"


def test_idle_hunts_when_capital_is_idle():
    """Idle capital is a position too - 100% cash at 0% expected return. With
    a deadline that is a decision, not a default."""
    from datetime import datetime, timedelta, timezone
    a = _idle(last_hunt_at=datetime.now(timezone.utc) - timedelta(minutes=200))
    assert a.level == "hunt"


def test_idle_does_not_hunt_when_the_risk_cap_is_full():
    """Do not hunt when you cannot shoot: candidates sizing will refuse are
    spend with no possible outcome."""
    from datetime import datetime, timedelta, timezone
    a = _idle(positions=[_held()], underlying_prices={"SPY": 766.9},
              open_risk_usd=15_000,
              last_hunt_at=datetime.now(timezone.utc) - timedelta(minutes=200))
    assert a.level == "sleep"


def test_idle_does_not_open_new_risk_into_the_close():
    from datetime import datetime, timedelta, timezone
    a = _idle(last_hunt_at=datetime.now(timezone.utc) - timedelta(minutes=300),
              minutes_to_close_=15.0)
    assert a.level == "sleep" and "close" in a.reason


def test_idle_respects_the_hunt_cooldown():
    a = _idle()  # hunted 5 minutes ago
    assert a.level == "sleep"


def test_idle_sleeps_when_the_market_is_closed():
    a = _idle(market_open=False, positions=[_held()],
              underlying_prices={"SPY": 700.0})
    assert a.level == "sleep" and "closed" in a.reason


def test_interim_marks_do_not_score_the_mind_prediction():
    """A mind prediction is a claim about the thesis at its horizon - right or
    wrong once. mind_outcome takes a binary hit with no weight, so an interim
    mark recorded a full miss: live, the SPY mind sat at confidence 0.34,
    hit/total 0/1, on a position that was PROFITABLE."""
    import inspect
    from trdrbot.elfmem_adapter import ElfmemAdapter
    src = inspect.getsource(ElfmemAdapter.resolve)
    assert "not interim" in src, "mind_outcome must be gated on a true resolution"


# ------------------------------------- D-044 stray background processes

def test_run_lock_refuses_a_second_live_loop():
    """A stray 5s smoke-test loop once hammered the broker API and burned LLM
    calls for half an hour. `kill %1` had killed the pipeline job, not the
    orphaned `uv run` child."""
    import os, tempfile
    from pathlib import Path
    from trdrbot.cli import _acquire_run_lock

    pid_file = Path(tempfile.mkdtemp()) / "run.pid"
    pid_file.write_text(str(os.getpid()))  # a definitely-alive process
    # Our own pid is treated as ours (re-entrant), so use a live *other* pid:
    import subprocess
    proc = subprocess.Popen(["sleep", "30"])
    try:
        pid_file.write_text(str(proc.pid))
        assert _acquire_run_lock(pid_file) is False
    finally:
        proc.terminate()


def test_run_lock_takes_over_a_stale_lock():
    """A crashed loop must not require manual cleanup before trading resumes."""
    import tempfile
    from pathlib import Path
    from trdrbot.cli import _acquire_run_lock

    pid_file = Path(tempfile.mkdtemp()) / "run.pid"
    pid_file.write_text("999999")  # not a live pid
    assert _acquire_run_lock(pid_file) is True


def test_run_lock_survives_a_corrupt_pid_file():
    import tempfile
    from pathlib import Path
    from trdrbot.cli import _acquire_run_lock

    pid_file = Path(tempfile.mkdtemp()) / "run.pid"
    pid_file.write_text("not-a-pid")
    assert _acquire_run_lock(pid_file) is True


def test_interval_floor_is_above_any_legitimate_polling_rate():
    from trdrbot.cli import MIN_INTERVAL_SECONDS
    assert MIN_INTERVAL_SECONDS >= 30


# ------------------------------- D-046 whole-book liquidation

def test_close_all_positions_is_refused_while_several_are_open():
    """Observed live: the agent reached for close_all_positions intending to
    close ONE spread, then placed a separate sell on a leg the sweep had
    already closed. Only fill sequencing prevented a naked short."""
    import asyncio
    from trdrbot import tool_guard

    class FakeTool:
        name = "close_all_positions"
        def __init__(self): self.called = False
        async def coroutine(self, **kw):
            self.called = True
            return "liquidated"

    t = FakeTool()
    orig_called = lambda: t.called
    tools = tool_guard.redirect_whole_book_close([t], lambda: 3)
    out = asyncio.run(tools[0].coroutine(cancel_orders=True))
    assert "REFUSED" in out and not t.called

    t2 = FakeTool()
    tools2 = tool_guard.redirect_whole_book_close([t2], lambda: 1)
    out2 = asyncio.run(tools2[0].coroutine(cancel_orders=True))
    assert out2 == "liquidated" and t2.called, "one position: equivalent to a normal close"


# ------------------------------- D-048 competence ladder (replaces D-047 phases)

GOOD_V = "thesis_right_expression_right"
LUCK_V = "thesis_wrong_profited_anyway"
NOSCORE_V = "unscoreable"


def _hist(n, verdict=GOOD_V):
    return [Position(position_id=f"h{i}", attribution=verdict) for i in range(n)]


def _comp(resolved, rel=0.02, verdicts=None, equity=100_000, hw=100_000):
    from trdrbot import competence
    pos = verdicts if verdicts is not None else _hist(max(1, resolved))
    return competence.assess(resolved=resolved, reliability=rel, positions=pos,
                             equity=equity, high_water=hw)


def _size_tier(comp, resolved, mp=800.0, ml=-1200.0, risk=0.0, by=None):
    from trdrbot import sizing
    from trdrbot.sizing import Calibration
    cal = Calibration(n=resolved, brier=0.2, reliability=comp.reliability,
                      resolution=0.05, uncertainty=0.24, base_rate=0.5)
    return sizing.size_position(equity=100_000, underlying="SPY", stated_confidence=0.70,
                                max_profit=mp, max_loss=ml, calibration=cal,
                                posture=comp, open_risk_usd=risk,
                                open_risk_by_underlying=by)


def test_size_is_monotonic_in_evidence():
    """Two separate ladder inversions have shipped and been caught here: an
    earned record sizing smaller than an unproven one, and promotion from
    EXPLORE to ESTABLISH taking sizing from 1 contract to 0."""
    prev = -1
    for n in [0, 2, 5, 8, 12, 15, 20, 30, 40, 60, 100]:
        c = _comp(n)
        got = _size_tier(c, n).contracts
        assert got >= prev, f"n={n} sized {got}, below the previous {prev}"
        prev = got


def test_luck_does_not_buy_size():
    """A profit on a wrong view teaches nothing. Promotion past ESTABLISH
    requires theses we could actually explain."""
    from trdrbot import competence
    lucky = _comp(15, verdicts=_hist(10, LUCK_V) + _hist(5, GOOD_V))
    earned = _comp(15, verdicts=_hist(11, GOOD_V) + _hist(4, LUCK_V))
    assert lucky.tier == competence.ESTABLISH
    assert earned.tier == competence.SCALE


def test_unscoreable_theses_do_not_buy_size():
    from trdrbot import competence
    c = _comp(15, verdicts=_hist(10, NOSCORE_V) + _hist(5, GOOD_V))
    assert c.tier == competence.ESTABLISH


def test_poor_calibration_blocks_the_top_tier_only():
    """Reliability gates MATURE, not SCALE (D-050): below ~n=40 the statistic
    cannot separate a perfect forecaster from a badly overconfident one, so a
    gate there would reject good agents and pass bad ones alike."""
    from trdrbot import competence
    assert _comp(40, rel=0.09).tier == competence.SCALE
    assert _comp(40, rel=0.02).tier == competence.MATURE


def test_drawdown_demotes_immediately_and_recovers():
    from trdrbot import competence
    assert _comp(40).tier == competence.MATURE
    assert _comp(40, equity=94_000).tier == competence.SCALE
    assert _comp(40, equity=88_000).tier == competence.EXPLORE
    assert _comp(40, equity=100_000).tier == competence.MATURE


def test_the_ladder_has_no_calendar_in_it():
    """The previous design keyed on days-to-deadline and would have entered a
    no-new-risk phase permanently once the date passed."""
    import inspect
    from trdrbot import competence
    src = inspect.getsource(competence.assess)
    assert "date" not in src and "deadline" not in src


def test_hard_stop_is_a_position_check_not_a_sizing_regime():
    import datetime
    from datetime import date
    from trdrbot import competence
    soon = (date.today() + datetime.timedelta(days=1)).isoformat()
    far = (date.today() + datetime.timedelta(days=30)).isoformat()
    assert competence.can_open(soon, None)[0] is False
    assert competence.can_open(far, None)[0] is True
    assert competence.can_open(None, None)[0] is True, "no deadline: always open"
    past = (date.today() + datetime.timedelta(days=45)).isoformat()
    assert competence.can_open(far, past)[0] is False


def test_book_supports_several_symbols_and_refuses_concentration():
    c = _comp(20)
    d1 = _size_tier(c, 20, ml=-1500.0, risk=6_000, by={"SPY": 6_000})
    d2 = _size_tier(c, 20, ml=-1500.0, risk=6_000, by={"NVDA": 6_000})
    assert d2.contracts >= d1.contracts, "a different name must not be punished as concentration"


def test_next_tier_is_visible_to_the_agent():
    c = _comp(7, rel=0.06, verdicts=_hist(5, GOOD_V) + _hist(2, LUCK_V))
    needs = c.next_tier_needs()
    assert "SCALE" in needs and "15" in needs


# ------------------------------- D-050 calibration bias at small n

def _synthetic(kind, n, seed=11):
    import random
    from trdrbot.calibration import Forecast
    rng = random.Random(seed)
    out = []
    for i in range(n):
        if kind == "perfect":
            p = rng.choice([0.3, 0.4, 0.5, 0.6, 0.7]); hit = rng.random() < p
        else:  # badly overconfident: says 80%, right 55%
            p = 0.8; hit = rng.random() < 0.55
        out.append(Forecast(position_id=f"f{i}", probability=p, outcome=hit))
    return out


def test_a_perfect_forecaster_is_not_penalised_at_small_n():
    """The empirical Brier decomposition OVERSTATES reliability at small n.
    Measured before the fix: a perfectly calibrated agent scored 0.072 at
    n=15 against a promotion gate demanding <0.05 - blocking a flawless agent
    most of the time, with the phantom penalty shrinking as n grew so it would
    have looked exactly like learning."""
    from trdrbot.calibration import score
    rels = [score(_synthetic("perfect", 20, seed=s)).reliability for s in range(40)]
    assert sum(rels) / len(rels) < 0.035, "small-sample bias is back"


def test_a_genuinely_overconfident_forecaster_is_still_caught():
    """The correction must not launder real miscalibration."""
    from trdrbot.calibration import score
    perfect = [score(_synthetic("perfect", 60, seed=s)).reliability for s in range(30)]
    bad = [score(_synthetic("overconf", 60, seed=s)).reliability for s in range(30)]
    assert sum(bad) / len(bad) > 3 * (sum(perfect) / len(perfect))


def test_reliability_gates_only_where_it_can_discriminate():
    """At n=15-20 perfect and bad forecasters score 0.022 vs 0.038 -
    overlapping. Gating there is theatre that costs real size."""
    from trdrbot import competence
    assert competence.TIERS[competence.SCALE]["max_rel"] is None
    assert competence.TIERS[competence.MATURE]["max_rel"] is not None
    assert competence.TIERS[competence.MATURE]["min_n"] >= 40


def test_reliability_is_never_negative():
    from trdrbot.calibration import score
    for s in range(20):
        c = score(_synthetic("perfect", 12, seed=s))
        assert c.reliability >= 0.0 and c.resolution >= 0.0


# --------------------------- D-051 vol clock and gamma breakeven

def test_weekend_time_is_not_full_volatility_time():
    """Friday->Monday is 2.25 calendar days but ~1.25 vol days. At 30 DTE that
    is a rounding error; at 2-10 DTE it corrupts every greek and the expected
    move the thesis band is checked against."""
    import datetime
    from trdrbot.optmath import vol_days
    friday = datetime.date(2026, 8, 28)
    monday = datetime.date(2026, 8, 31)
    assert vol_days(3, friday) < vol_days(3, monday)
    assert abs(vol_days(3, monday) - 3.0) < 1e-9, "a midweek run is all trading days"
    assert vol_days(3, friday) == 2.0, "Fri 1.0 + Sat 0.5 + Sun 0.5"
    assert vol_days(0, friday) == 0.0


def test_vol_clock_degrades_honestly_without_a_start_date():
    from trdrbot.optmath import vol_days
    assert 0 < vol_days(7) < 7, "must discount weekends even when we cannot date them"


def test_the_vol_clock_is_never_applied_on_top_of_a_quoted_iv():
    """A quoted IV ALREADY prices the weekend, so discounting it again is a
    double count - and it used to be one, silently.

    `bs_greeks`/`expected_move` divided vol-weighted days by 308 while the
    lognormal grid divided calendar days by 365: two clocks, one table, greeks
    and probabilities for the same position on different time axes. The
    weekend half was inert in production only because no caller ever passed
    `start`, which made it a landmine for whoever supplied the missing
    argument - doing so shrinks the modelled 1-sigma Friday-to-Monday move to
    ~89% of what the option's own price implies, in the direction that makes
    short premium look safer than it is.

    So `start` is accepted and IGNORED, and this pins that."""
    import datetime
    from trdrbot.optmath import expected_move, bs_greeks, year_fraction

    fri, mon = datetime.date(2026, 8, 28), datetime.date(2026, 8, 31)
    assert expected_move(770, 0.13, 3, fri) == expected_move(770, 0.13, 3, mon)
    assert bs_greeks("C", 770, 770, 0.13, 3, fri) == bs_greeks("C", 770, 770, 0.13, 3, mon)
    assert abs(year_fraction(365) - 1.0) < 1e-12, "ACT/365, the clock IV is struck on"


def test_greeks_and_probabilities_share_one_clock():
    """They did not, and the gap was rendered side by side in one table."""
    import math
    from trdrbot.optmath import Leg, bs_greeks, prob_profit, year_fraction

    # A far OTM call's delta and its P(profit) both key off the same sigma*sqrt(T).
    days, iv, spot = 6, 0.20, 100.0
    t = year_fraction(days)
    g = bs_greeks("C", 100.0, spot, iv, days)
    # N(d1) with d1 = 0.5*sigma*sqrt(t) for an ATM strike at r=0.
    expect = 0.5 * (1.0 + math.erf((0.5 * iv * math.sqrt(t)) / math.sqrt(2.0)))
    assert abs(g["delta"] - expect) < 1e-12
    # And the grid the probabilities come off uses that same t: a long call
    # profits iff spot ends above break-even, so P must be < 0.5 at any
    # positive premium and must move with the same sigma.
    leg = Leg.parse({"right": "C", "strike": 100.0, "side": "long", "qty": 1, "price": 1.0})
    assert 0.0 < prob_profit([leg], spot, iv, days) < 0.5


def test_implied_vs_realized_converts_before_comparing():
    """252 sessions against 365 calendar days. Comparing raw understates
    implied by 17% - every time, in the direction that says do not sell."""
    import math
    from trdrbot.optmath import implied_vs_realized

    # Implied and realised describing the SAME world must read as 1.0.
    realized = 0.20                       # annualised over 252 sessions
    implied = realized * math.sqrt(252 / 365)   # the same vol, ACT/365
    assert abs(implied_vs_realized(implied, realized) - 1.0) < 1e-12
    assert implied_vs_realized(0.20, 0.20) > 1.15, "raw equality is really a premium"
    assert implied_vs_realized(0.20, 0.0) is None


def test_gamma_breakeven_is_the_implied_daily_move_not_a_structure_score():
    """Sources claim it discriminates structures. It does not: theta/gamma is
    the same BS identity for every position at one spot and one vol. What it
    returns is the daily move implied by IV - useful against REALISED range."""
    from trdrbot.optmath import Leg, net_greeks, gamma_breakeven

    def L(r, k, side, q=1):
        return Leg.parse({"right": r, "strike": k, "side": side, "qty": q, "price": 1.0})

    spread = net_greeks([L("P", 755, "short", 5), L("P", 750, "long", 5)], 766.0, 0.13, 6)
    straddle = net_greeks([L("C", 766, "long"), L("P", 766, "long")], 766.0, 0.13, 6)
    assert abs(gamma_breakeven(spread) - gamma_breakeven(straddle)) < 0.01

    low = gamma_breakeven(net_greeks([L("C", 766, "long")], 766.0, 0.08, 6))
    high = gamma_breakeven(net_greeks([L("C", 766, "long")], 766.0, 0.35, 6))
    assert high > 2 * low, "it must scale with IV - that is its actual content"
    assert gamma_breakeven(None) is None


# ------------------- D-052 pre-registration ledger & unconditional forecasts

def _book():
    import tempfile
    from pathlib import Path
    from trdrbot.ledger import Ledger
    return Ledger(Path(tempfile.mkdtemp()) / "ledger.jsonl")


def test_unfalsifiable_forecasts_are_refused_at_write_time():
    """A thesis that can never be judged is not evidence, and counting it would
    make the multiple-testing correction more punitive for no gain."""
    from trdrbot.ledger import STANDALONE
    b = _book()
    assert b.register(kind=STANDALONE, underlying="QQQ", claim="vibes", probability=0.6,
                      horizon="2026-09-30", band_low=None, band_high=None) is None
    assert b.trials() == 0


def test_declined_theses_still_score_calibration():
    """The whole point: at 1-5 concurrent positions, trade-level observations
    never reach the ~50 needed for calibration to mean anything. Forecasts on
    setups we DECLINE cost nothing and score the same judgement."""
    import datetime
    from trdrbot.calibration import CalibrationStore
    from trdrbot.ledger import STANDALONE, as_forecasts
    import tempfile
    from pathlib import Path

    b = _book()
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    for i, (lo, hi, px) in enumerate([(200.0, 238.0, 249.0), (100.0, 150.0, 120.0)]):
        e = b.register(kind=STANDALONE, underlying=f"X{i}", claim="declined",
                       probability=0.45, horizon=past, band_low=lo, band_high=hi)
        b.resolve(e.id, px, "now")

    cal = CalibrationStore(Path(tempfile.mkdtemp()) / "c.json")
    assert cal.score().n == 0, "no traded positions"
    assert cal.score(as_forecasts(b.resolved())).n == 2, "declined forecasts must count"


def test_resolution_checks_the_band_against_the_tape():
    import datetime
    from trdrbot.ledger import THESIS
    b = _book()
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    e = b.register(kind=THESIS, underlying="NVDA", claim="holds", probability=0.38,
                   horizon=past, band_low=220.0, band_high=245.0)
    assert b.resolve(e.id, 231.0, "now").outcome is True
    e2 = b.register(kind=THESIS, underlying="SPY", claim="holds", probability=0.7,
                    horizon=past, band_low=750.0, band_high=None)
    assert b.resolve(e2.id, 740.0, "now").outcome is False


def test_a_forecast_is_not_resolved_before_its_horizon():
    import datetime
    from trdrbot.ledger import STANDALONE
    b = _book()
    future = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    b.register(kind=STANDALONE, underlying="SMCI", claim="later", probability=0.3,
               horizon=future, band_low=38.0, band_high=48.0)
    assert b.matured_unresolved() == []


def test_the_same_thesis_is_not_double_registered():
    """The agent often simulates twice while comparing structures; the trial
    count must not inflate from that."""
    from trdrbot.ledger import THESIS
    b = _book()
    for _ in range(3):
        b.register(kind=THESIS, underlying="NVDA", claim="holds", probability=0.4,
                   horizon="2099-01-01", band_low=220.0, band_high=245.0)
    assert b.trials() == 1


def test_traded_and_declined_are_distinguishable():
    from trdrbot.ledger import THESIS, STANDALONE
    b = _book()
    b.register(kind=THESIS, underlying="NVDA", claim="a", probability=0.4,
               horizon="2099-01-01", band_low=220.0, band_high=245.0)
    b.register(kind=STANDALONE, underlying="SPY", claim="b", probability=0.6,
               horizon="2099-01-02", band_low=750.0, band_high=None)
    b.mark_traded("NVDA", "2099-01-01", "pos_1")
    s = b.summary()
    assert s["traded"] == 1 and s["declined"] == 1 and s["trials"] == 2


# ------------------------------------------- D-054 measured lessons

def test_every_lesson_is_cued_named_and_specific():
    """A lesson findable only by its own wording is lost ([cues] applied to
    itself), and one without numbers is a platitude."""
    from trdrbot import lessons
    keys = [l.key for l in lessons.LESSONS]
    assert len(keys) == len(set(keys))
    for l in lessons.LESSONS:
        assert l.cue.strip().startswith("when"), f"{l.key}: cue must name a situation"
        assert lessons.block_text(l).startswith(f"[{l.key}]"), "name-first for stable citation"
        assert any(ch.isdigit() for ch in l.text), f"{l.key}: no measurement in it"
        assert len(l.text) > 200, f"{l.key}: too thin to be actionable"


def test_lessons_are_not_constitutional():
    """They must decay and be moved by outcomes. Pinning a measured claim as
    identity is exactly what [regimes] warns against."""
    from trdrbot import constitution, lessons
    assert lessons.TAG != constitution.TAG
    for l in lessons.LESSONS:
        assert constitution.TAG not in l.tags


def test_a_reworded_lesson_replaces_rather_than_duplicates():
    """Content-based idempotence looks right until a lesson is REWORDED: the
    new text does not match, a second block is written, and the stale twin
    lives on saying something subtly different. Measured: rewording one lesson
    produced 7 blocks for 6 lessons. Keys must be the handle, not content."""
    import inspect
    from trdrbot import lessons
    src = inspect.getsource(lessons.seed)
    assert "lesson/" in src, "must key on a per-lesson tag"
    assert "forget" in src, "must drop the superseded block"


# ----------------------------- D-055 beta-weighted book delta

def test_beta_is_returned_with_its_fit_quality():
    """A beta without R-squared is a number pretending to be knowledge.
    Measured on real data: MU came out at -0.45 and NVDA at +1.85 over the
    same 120 sessions - both semiconductors. That is one estimate dominated by
    name-specific moves, not two market sensitivities."""
    import math, random
    from trdrbot.market_stats import beta, shrunk_beta
    rng = random.Random(5)
    bench = [100.0]
    for _ in range(150):
        bench.append(bench[-1] * math.exp(rng.gauss(0, 0.01)))
    br = [math.log(b / a) for a, b in zip(bench, bench[1:])]

    # a true 2x tracker: high beta, high R2, taken at face value
    tracker = [100.0]
    for r in br:
        tracker.append(tracker[-1] * math.exp(2 * r))
    raw, r2 = beta(tracker, bench)
    assert abs(raw - 2.0) < 0.1 and r2 > 0.9
    assert abs(shrunk_beta(raw, r2) - raw) < 0.05, "a well-fitted beta is not shrunk"

    # pure noise: whatever beta falls out must be shrunk back toward the market
    noise = [100.0]
    for _ in range(150):
        noise.append(noise[-1] * math.exp(rng.gauss(0, 0.02)))
    raw_n, r2_n = beta(noise, bench)
    assert r2_n < 0.2
    assert abs(shrunk_beta(raw_n, r2_n) - 1.0) < abs(raw_n - 1.0), "noise must shrink to market"


def test_beta_refuses_rather_than_guessing_on_thin_history():
    import math, random
    from trdrbot.market_stats import beta
    rng = random.Random(3)
    short = [100.0 * math.exp(rng.gauss(0, 0.01)) for _ in range(30)]
    assert beta(short, short) is None


def test_negative_beta_is_preserved_not_clamped():
    """An offsetting position is the whole point of measuring this."""
    import math, random
    from trdrbot.market_stats import beta
    rng = random.Random(9)
    bench = [100.0]
    for _ in range(150):
        bench.append(bench[-1] * math.exp(rng.gauss(0, 0.01)))
    inverse = [100.0]
    for a, b in zip(bench, bench[1:]):
        inverse.append(inverse[-1] * math.exp(-math.log(b / a)))
    raw, r2 = beta(inverse, bench)
    assert raw < -0.9 and r2 > 0.9


def test_book_delta_is_beta_weighted_and_can_offset():
    """Raw delta treats $10k of a 1.85-beta name as $10k of the market. On our
    own live book that understated market exposure by 85%."""
    import tempfile
    from pathlib import Path
    from trdrbot.analytics import book_greeks, Snapshot
    from trdrbot import market_stats

    d = Path(tempfile.mkdtemp())
    import math, random
    rng = random.Random(4)
    spy = [100.0]
    for _ in range(200):
        spy.append(spy[-1] * math.exp(rng.gauss(0, 0.01)))
    hi = [100.0]
    for a, b in zip(spy, spy[1:]):
        hi.append(hi[-1] * math.exp(2 * math.log(b / a)))
    market_stats.save_closes(d, "SPY", spy)
    market_stats.save_closes(d, "HI", hi)

    betas, assumed = market_stats.betas_for(d, ["SPY", "HI"])
    assert betas["SPY"] == 1.0
    assert betas["HI"] > 1.7, "a 2x tracker must weight roughly double"
    assert "HI" not in assumed


def test_beta_weighting_reveals_a_hedge_that_raw_delta_hides():
    """The demonstration that justifies the whole feature: adding an
    inverse-beta position RAISED raw book delta from $90k to $253k while
    beta-weighted delta FELL from $181k to $18k. Raw delta said "more
    exposed"; the truth was "almost flat"."""
    import math, random, tempfile
    from pathlib import Path
    from trdrbot import market_stats
    from trdrbot.analytics import book_greeks

    d = Path(tempfile.mkdtemp())
    rng = random.Random(4)
    spy = [100.0]
    for _ in range(200):
        spy.append(spy[-1] * math.exp(rng.gauss(0, 0.01)))

    def track(m):
        o = [100.0]
        for a, b in zip(spy, spy[1:]):
            o.append(o[-1] * math.exp(m * math.log(b / a)))
        return o

    market_stats.save_closes(d, "SPY", spy)
    market_stats.save_closes(d, "HIB", track(2.0))
    market_stats.save_closes(d, "INV", track(-1.0))

    def pos(u, qty):
        return Position(position_id=f"p_{u}", status="open", underlying=u, entry_iv=0.30,
                        legs=[{"symbol": f"{u}990904C00095000", "side": "buy", "qty": qty}])

    prices = {"HIB": 100.0, "INV": 100.0}
    one = book_greeks([pos("HIB", 10)], prices, state_dir=d, equity=100_000)
    two = book_greeks([pos("HIB", 10), pos("INV", 18)], prices, state_dir=d, equity=100_000)

    assert two["positions_priced"] == 2, "OCC roots are max 6 chars - both must price"
    assert two["delta_dollars"] > one["delta_dollars"], "raw delta grows"
    assert abs(two["beta_weighted_delta"]) < abs(one["beta_weighted_delta"]) / 5, "true exposure falls"
    assert two["betas"]["INV"] < 0


# ------------------- D-056 measured profit, and a warning that cried wolf

def test_attribution_scores_measured_profit_not_the_close_label():
    """close_reason was standing in for profit, so anything closed outside our
    own exit rules - 'external' - scored as a LOSS however much it made. Caught
    live: an NVDA spread the agent closed itself by repricing its profit target
    made +$1,290 and would have taught the loop the opposite of what happened."""
    import inspect
    from trdrbot import attribution, experiments
    src = inspect.getsource(attribution.run)
    assert "last_pnl_pct" in src, "profit must be measured, not inferred from a label"

    # the two verdicts must differ on a profitable trade whose thesis failed
    right, _ = experiments.attribute(True, True)
    lucky, _ = experiments.attribute(False, True)
    assert experiments.ATTRIBUTION_SIGNAL[right] > 0.5, "a right view must reinforce"
    assert experiments.ATTRIBUTION_SIGNAL[lucky] is None, \
        "a lucky win must apply nothing at all (D-072)"


def test_last_pnl_survives_a_position_leaving_the_broker():
    import tempfile
    from pathlib import Path
    from trdrbot.positions import PositionStore, Position
    st = PositionStore(Path(tempfile.mkdtemp()))
    st.save(Position(position_id="pos_x", status="open", last_pnl_pct=0.53))
    assert [p for p in st.all() if p.position_id == "pos_x"][0].last_pnl_pct == 0.53
    st.save(Position(position_id="pos_y", status="open"))
    assert [p for p in st.all() if p.position_id == "pos_y"][0].last_pnl_pct is None


def test_only_opening_orders_demand_a_recorded_position():
    """The warning fired on replace_order_by_id when the agent repriced its own
    EXIT, demanding a record_position for a position it was closing. A warning
    that cries wolf teaches everyone to ignore warnings."""
    def demands(o):
        return (str(o.get("name", "")).startswith("place_")
                and "close" not in str(o.get("args_as_model_supplied", {})
                                       .get("position_intent", "")).lower())

    assert not demands({"name": "replace_order_by_id", "args_as_model_supplied": {}})
    assert not demands({"name": "cancel_order_by_id", "args_as_model_supplied": {}})
    assert not demands({"name": "place_option_order",
                        "args_as_model_supplied": {"position_intent": "sell_to_close"}})
    assert demands({"name": "place_option_order",
                    "args_as_model_supplied": {"order_class": "mleg", "qty": "10"}})


# ---------------- D-057 credit lost on external closes and inbox blocks

def test_credit_gates_on_measured_pnl_not_the_close_label():
    """close_reason in SELF_RESOLVED silently skipped credit assignment for
    every 'external' close - and both real closes so far have been external,
    because the agent manages its own exits through the broker. Found by the
    learning-loop simulation: the credited block ended with reinforcement=None."""
    import inspect
    from trdrbot import learn
    src = inspect.getsource(learn.on_resolution)
    assert "if pnl_pct is not None:\n        hit = pnl_pct > 0" in src
    # the None-P&L guess path must still be skipped
    assert "skipped rather than guessed" in src


def test_resolve_self_heals_when_outcomes_hit_unconsolidated_blocks():
    """outcome() on a block still in elfmem's inbox returns updated=0
    SILENTLY. Theses are remembered at FILL and consolidation runs only at
    market-closed housekeeping, so any same-day resolution - like our first
    profitable NVDA trade - lost its memory credit invisibly. Measured:
    updated=0 before consolidation, updated=1 after."""
    import inspect
    from trdrbot import attribution
    from trdrbot.elfmem_adapter import ElfmemAdapter
    # The retry lives in `credit_blocks` now - THE single door both resolve()
    # and attribution.run() come through (D-072). It had to move: attribution
    # called `mem.outcome()` directly, so the MAIN trading credit path was the
    # one path missing this protection.
    src = inspect.getsource(ElfmemAdapter.credit_blocks)
    assert "blocks_updated" in src and "consolidate" in src, \
        "credit_blocks must detect a short-count and consolidate-then-retry"
    assert "credit_blocks" in inspect.getsource(ElfmemAdapter.resolve), \
        "resolve must go through the single credit door, not call outcome itself"
    assert "credit_blocks" in inspect.getsource(attribution.run), \
        "attribution must go through the single credit door - it did not, and "\
        "that is exactly how it missed the consolidate-and-retry fix"


def test_resolution_falls_back_to_the_positions_own_last_pnl():
    """Reconciliation discovers an external close only AFTER the position has
    left the broker, so it has no P&L to pass - which silently skipped BOTH
    calibration and credit for our only closed trade, leaving a recorded 38%
    forecast permanently unresolved. Third place the same measured number
    failed to reach its consumer, so the fallback lives at the shared entry
    point rather than in each detector."""
    import inspect
    from trdrbot import learn
    src = inspect.getsource(learn.on_resolution)
    assert "pos.last_pnl_pct" in src
    assert src.index("pos.last_pnl_pct") < src.index("self_resolved ="), \
        "the fallback must run before anything gates on P&L being known"


# ------------------------ D-059 memory-quality repair (SPY block, SPY mind)

def test_remember_thesis_pins_tags_to_avoid_a_self_leak():
    """Left to free consolidation, a thesis block reading 'I did X because Y,
    expecting Z' gets tagged self/goal or self/constraint/self/style - found
    live on two real positions (SPY: self/goal+self/constraint; NVDA:
    self/goal+self/style), both competing for SELF-frame slots as if they
    were identity rather than a dated trade rationale. Position theses are
    evolving patterns, never identity, so tags are pinned at write time."""
    import inspect
    from trdrbot.elfmem_adapter import ElfmemAdapter
    src = inspect.getsource(ElfmemAdapter.remember_thesis)
    assert "host_analyses" in src, "must pin its own tags, not trust free consolidation"
    assert 'tags = [pos.underlying.lower(), pos.strategy]' in src
    assert "self/" not in src.split("host_analyses={")[0].split("tags = [")[1][:80]


# ----------------------------------- D-060 the muse

def test_muse_unwraps_an_object_wrapped_candidate_array():
    """The model sometimes returns {"candidates": [...]} and _parse_json_block
    salvages {} before [] - so raw arrived as a dict, the list-guard silently
    skipped everything, and the run reported '0 candidates' with no evidence.
    Third unlogged null path found in one module."""
    raw = {"candidates": [{"underlying": "X"}], "note": "y"}
    if isinstance(raw, dict):
        raw = next((v for v in raw.values() if isinstance(v, list)), [])
    assert raw == [{"underlying": "X"}]


def test_muse_sampler_is_stratified_toward_market_content():
    """An unstratified draw produced three technique/ rules, which collide into
    process talk, not market theses."""
    import inspect
    from trdrbot import muse
    src = inspect.getsource(muse._sample_concepts)
    assert "technique/" in src and "k - 1" in src


def test_muse_keeps_a_breakout_call_against_a_calm_base():
    """A stated 27% against a 99% base is not vacuous - the disagreement IS the
    claim. The naive ceiling gate rejected exactly the most interesting
    candidate on the first live run."""
    import inspect
    from trdrbot import muse
    src = inspect.getsource(muse.run)
    assert "disagrees" in src
    assert "not disagrees" in src, "ceiling must only reject when the model AGREES"


# --------------------------- D-067 set agent_name at the source, not after

def test_build_sets_agent_name_by_default():
    """D-061's boundary rename (rewrite "You are elf" -> "You are Theo" after
    the fact, regex, word-boundaried, fail-safe) is retired: elfmem_index @
    c19dcc5 fixed the actual gap upstream (project.agent_name never reached
    the SELF preamble render path), so the correct fix is setting the name
    once, at the source, not correcting the text every time it's read."""
    import inspect
    from trdrbot.elfmem_adapter import ElfmemAdapter, _DEFAULT_AGENT_NAME
    src = inspect.getsource(ElfmemAdapter.build)
    assert "agent_name" in src, "build() must set project.agent_name"
    assert _DEFAULT_AGENT_NAME == "Theo"


def test_build_does_not_clobber_an_explicit_agent_name():
    """setdefault, not overwrite - a future caller passing its own config
    must keep the final say over its own agent_name."""
    import inspect
    from trdrbot.elfmem_adapter import ElfmemAdapter
    src = inspect.getsource(ElfmemAdapter.build)
    assert "setdefault" in src, \
        "must not silently overwrite a caller-supplied agent_name"


# ------------------------- D-062 provider fallback and cost accounting

def test_model_chain_resolves_role_then_default_then_legacy():
    """A pre-existing config with only `llm.model` must keep working untouched."""
    from trdrbot.config import Config
    from pathlib import Path

    class P:  # minimal paths stub
        state = Path("/tmp")
    legacy = Config(raw={"llm": {"model": "anthropic:claude-opus-5"}}, paths=P())
    assert legacy.model_chain("decide") == ["anthropic:claude-opus-5"]
    assert legacy.model == "anthropic:claude-opus-5"

    modern = Config(raw={"llm": {"models": ["a:1", "b:2"],
                                 "roles": {"research": ["c:3"]}}}, paths=P())
    assert modern.model_chain("decide") == ["a:1", "b:2"]      # falls to default
    assert modern.model_chain("research") == ["c:3"]           # role override
    assert modern.model_chain("unknown") == ["a:1", "b:2"]     # unknown role -> default
    assert modern.model == "a:1"                               # legacy accessor still works


def test_unpriced_model_is_reported_not_counted_as_free():
    """A cost report that silently understates spend is the absence-as-zero
    failure class in its most expensive form."""
    import tempfile
    from pathlib import Path
    from trdrbot.usage import UsageLedger

    led = UsageLedger(Path(tempfile.mkdtemp()) / "u.jsonl",
                      {"openai:gpt-4o-mini": {"input": 0.15, "output": 0.60}})
    led.record("decide", "gpt-4o-mini-2024-07-18", 1_000_000, 1_000_000)
    led.record("decide", "some-model-nobody-priced", 1_000_000, 1_000_000)
    s = led.summary()
    assert s["calls"] == 2
    assert s["unpriced_calls"] == 1
    assert "some-model-nobody-priced" in s["unpriced_models"]
    assert abs(s["total_cost_usd"] - 0.75) < 1e-9, "priced call only, unpriced NOT added as 0"
    assert "UNPRICED" in __import__("trdrbot.usage", fromlist=["render"]).render(s)


def test_pricing_matches_a_dated_provider_model_id():
    """Providers answer with dated ids (gpt-4o-mini-2024-07-18) for a model
    configured as openai:gpt-4o-mini - the table must still match, or every
    real call would be unpriced."""
    from trdrbot.usage import price
    table = {"openai:gpt-4o-mini": {"input": 0.15, "output": 0.60}}
    assert price(table, "gpt-4o-mini-2024-07-18", 1_000_000, 0) == 0.15
    assert price(table, "totally-different", 1_000_000, 0) is None


def test_usage_callback_never_raises_on_a_malformed_response():
    """Accounting that can halt trading is worse than no accounting."""
    import tempfile
    from pathlib import Path
    from trdrbot.usage import UsageCallback, UsageLedger

    cb = UsageCallback(UsageLedger(Path(tempfile.mkdtemp()) / "u.jsonl", {}), "decide")
    cb.on_llm_end(object())          # no .generations at all
    cb.on_llm_end(None)              # None
    class Weird:
        generations = [[object()]]   # generation with no .message
    cb.on_llm_end(Weird())


def test_build_model_skips_unbuildable_models_rather_than_dying(capsys):
    """One uninstalled optional provider package must not stop all trading."""
    from pathlib import Path
    from trdrbot.config import Config
    from trdrbot.llm import build_model

    class P:
        state = Path("/tmp")
    cfg = Config(raw={"llm": {"models": ["notaprovider:nope", "openai:gpt-4o-mini"],
                             "max_tokens": 16}}, paths=P())
    model = build_model(cfg, role="decide")
    assert model is not None
    assert "skipping notaprovider:nope" in capsys.readouterr().out


def test_build_model_raises_clearly_when_nothing_is_usable():
    from pathlib import Path
    from trdrbot.config import Config
    from trdrbot.llm import build_model

    class P:
        state = Path("/tmp")
    cfg = Config(raw={"llm": {"models": ["notaprovider:nope"], "max_tokens": 16}}, paths=P())
    try:
        build_model(cfg, role="decide")
        assert False, "should have raised"
    except RuntimeError as e:
        assert "No usable model" in str(e) and "decide" in str(e)


# ---------------------------- D-065 context diet

def _chain_payload(spot=767, strikes=range(600, 940, 5)):
    """Realistic fixture: full bar dicts, matching the ~850 chars/contract the
    live API sends. The first version slimmed bars to {"c": 1} and the 10x
    ratio assertion then failed against an unrealistically THIN payload - the
    fixture was the bug, not the compactor."""
    def snap(bid, ask, last):
        bar = {"c": last, "h": last * 1.1, "l": last * 0.9, "n": 62, "o": last,
               "t": "2026-08-27T04:00:00Z", "v": 255, "vw": last}
        return {"dailyBar": dict(bar), "minuteBar": dict(bar), "prevDailyBar": dict(bar),
                "latestQuote": {"ap": ask, "as": 10, "ax": "D", "bp": bid, "bs": 25,
                                "bx": "Z", "c": " ", "t": "2026-08-27T19:59:59.97Z"},
                "latestTrade": {"c": "I", "p": last, "s": 1,
                                "t": "2026-08-27T19:30:30.09Z", "x": "Q"}}
    snaps = {}
    for k in strikes:
        ic, ip = max(0.0, spot - k), max(0.0, k - spot)
        snaps[f"SPY260902C{k*1000:08d}"] = snap(ic + 1.0, ic + 1.1, ic + 1.05)
        snaps[f"SPY260902P{k*1000:08d}"] = snap(ip + 1.0, ip + 1.1, ip + 1.05)
    return {"next_page_token": "t", "snapshots": snaps}


def test_chain_compaction_keeps_near_atm_and_drops_far_strikes():
    """One chain payload is ~15k tokens re-sent every agent turn - 84% of
    decide cost was input. Compaction is 13x, and the near-ATM rows the
    decision actually needs survive with prices verbatim."""
    import json
    from trdrbot.compact import compact_option_chain
    payload = _chain_payload()
    out = compact_option_chain(payload)
    assert isinstance(out, str)
    assert len(out) * 10 < len(json.dumps(payload)), "must be ~13x smaller"
    assert "765" in out and "770" in out, "near-ATM strikes must survive"
    assert "3.00x25" in out, "prices and sizes reproduced verbatim"
    assert "strike_price_gte" in out, "the escape hatch must be stated"


def test_chain_compaction_fails_open_on_any_surprise():
    """A compactor that returns an empty string on a shape change would starve
    the decision silently - the null-path class again. Surprises pass the
    ORIGINAL through untouched."""
    from trdrbot.compact import compact_option_chain
    for weird in ({"weird": 1}, "not a dict", {"snapshots": {}},
                  {"snapshots": {"NOTANOCC": {}}}, None, 42):
        assert compact_option_chain(weird) == weird


def test_news_compaction_strips_bodies_keeps_headlines():
    from trdrbot.compact import compact_news
    news = {"news": [{"created_at": "2026-08-28T12:00:00Z", "headline": "H",
                      "source": "S", "symbols": ["SPY"], "content": "x" * 3000}]}
    out = compact_news(news)
    assert "H" in out and "x" * 50 not in out
    assert compact_news({"nope": 1}) == {"nope": 1}


def test_decide_tools_allowlist_empty_means_bind_everything():
    """A missing config section must degrade to working-but-expensive (all 72
    tools), never to broken (no tools)."""
    from pathlib import Path
    from trdrbot.config import Config

    class P:
        state = Path("/tmp")
    assert Config(raw={}, paths=P()).decide_tools == []
    cfg = Config(raw={"decide": {"tools": ["get_clock"]}}, paths=P())
    assert cfg.decide_tools == ["get_clock"]


# ---------------------------- D-066 news extraction + structured store

def _cfg_for_news_extract(tmp_path, models):
    from trdrbot.config import Config

    class P:
        state = tmp_path
    return Config(raw={"llm": {"roles": {"news_extract": models}, "max_tokens": 200}}, paths=P())


def test_bare_extract_renders_identically_to_pre_extraction_headlines():
    """A total extraction outage must degrade to EXACTLY the pre-D-066 output,
    not to something worse - the same fail-open guarantee compact.py already
    gives the option chain."""
    from trdrbot.news_extract import bare, render_block

    item = {"id": "1", "headline": "Fed holds rates steady", "source": "Reuters",
            "symbols": ["SPY"], "created_at": "2026-08-28T12:00:00Z"}
    e = bare(item)
    assert e.is_bare()
    assert e.dense == "Fed holds rates steady"
    out = render_block([e])
    assert "Fed holds rates steady" in out and "SPY" in out and "Reuters" in out
    assert "[" not in out.split("|")[0]  # no sentiment tag on a bare line


async def test_enrich_returns_cached_extracts_without_calling_the_model(tmp_path):
    """A cache hit must skip the LLM entirely - the whole point of keying by
    article id. Proven by pointing news_extract at an unbuildable model: if
    enrich() tried to call it, this would raise."""
    from trdrbot.news_extract import Extract, ExtractCache, enrich

    cache = ExtractCache(tmp_path / "news_extracts.json")
    cache.put_many([Extract(id="42", headline="H", sentiment=0.5, dense="Guidance raised",
                             activity="guidance", regime="company")])

    cfg = _cfg_for_news_extract(tmp_path, ["notaprovider:nope"])
    out = await enrich([{"id": "42", "headline": "H"}], cfg)
    assert len(out) == 1 and not out[0].is_bare()
    assert out[0].dense == "Guidance raised"


async def test_enrich_fails_open_to_bare_and_does_not_freeze_the_failure(tmp_path, capsys):
    """An unusable model must not lose the articles - they arrive bare (same
    as the old headline-only behaviour) and are NOT written to the cache, so
    the next cycle (a working model, or the same one recovered) retries them
    instead of being stuck on a permanent 'unknown'."""
    from trdrbot.news_extract import ExtractCache, enrich

    cfg = _cfg_for_news_extract(tmp_path, ["notaprovider:nope"])
    items = [{"id": "7", "headline": "Company X misses on guidance", "symbols": ["X"]}]
    out = await enrich(items, cfg)

    assert len(out) == 1
    assert out[0].is_bare()
    assert out[0].dense == "Company X misses on guidance"
    assert "falling back to headlines" in capsys.readouterr().out

    reloaded = ExtractCache(tmp_path / "news_extracts.json")
    assert reloaded.get("7") is None, "a bare fallback must not be frozen into the cache"


def test_coerce_defends_every_field_against_malformed_model_output():
    """One malformed field must not crash the batch - the model returning a
    string where a list was asked for, or an out-of-range sentiment, degrades
    that ONE record rather than the whole call."""
    from trdrbot.news_extract import _coerce

    item = {"id": "9", "headline": "H"}
    # missing sentiment entirely -> bare, not a crash
    assert _coerce({"organizations": "not a list"}, item, "m").is_bare()
    # sentiment out of [-1, 1] must clamp, not propagate
    e = _coerce({"sentiment": 5, "organizations": ["Apple", 3, "Google"]}, item, "m")
    assert e.sentiment == 1.0
    assert e.organizations == ["Apple", "Google"], "non-string entries must be dropped, not crash"


def test_compact_news_uses_the_extract_cache_when_config_is_given(tmp_path):
    """The decide-facing compactor must surface the richer signal once an
    article has been extracted by research/discovery/muse - not just the
    headline it would fall back to."""
    from pathlib import Path

    from trdrbot.compact import compact_news
    from trdrbot.config import Config
    from trdrbot.news_extract import Extract, ExtractCache

    cache = ExtractCache(tmp_path / "news_extracts.json")
    cache.put_many([Extract(id="1", headline="H", sentiment=-0.6, activity="regulatory",
                             regime="sector", organizations=["FDA"], dense="Trial halted")])

    class P:
        state = tmp_path
    cfg = Config(raw={}, paths=P())
    news = {"news": [{"id": "1", "headline": "H", "symbols": ["XYZ"], "created_at": "2026-08-28T09:00"}]}

    with_cache = compact_news(news, cfg)
    assert "Trial halted" in with_cache and "-0.6" in with_cache

    no_config = compact_news(news, None)
    assert "Trial halted" not in no_config, "without config it must fall back to headline-only, not crash"


# ---------------------------- D-067 field set from research + citation URL

def test_bare_extract_preserves_the_citation_url_even_on_total_outage():
    """The URL is real Alpaca data, not model output - it must survive
    exactly the failure mode the rest of the record does not (D-067, the
    user's explicit ask: preserve the original reference)."""
    from trdrbot.news_extract import bare, render_block

    item = {"id": "1", "headline": "H", "url": "https://example.com/article-1"}
    e = bare(item)
    assert e.url == "https://example.com/article-1"
    assert "<https://example.com/article-1>" in render_block([e])


def test_coerce_carries_url_from_the_item_never_from_model_output():
    """The model never sees the URL and must not be able to invent one -
    `url` always comes from the real Alpaca item, even when every other
    field comes from the model's JSON."""
    from trdrbot.news_extract import _coerce

    item = {"id": "1", "headline": "H", "url": "https://real.example/1"}
    e = _coerce({"sentiment": 0.2, "url": "https://fabricated.example/evil"}, item, "m")
    assert e.url == "https://real.example/1"


def test_coerce_validates_the_new_research_backed_fields():
    """time_horizon/claim_type are closed vocabularies - anything else must
    degrade to empty, not silently pollute a supposedly-controlled field.
    A claim_type with no key_number is meaningless and must be dropped too."""
    from trdrbot.news_extract import _coerce

    item = {"id": "1", "headline": "H"}
    e = _coerce({"sentiment": 0.1, "time_horizon": "next tuesday", "claim_type": "forecast"}, item, "m")
    assert e.time_horizon == "", "not in the controlled vocabulary - must not pass through"
    assert e.claim_type == "", "claim_type without a key_number is meaningless"

    e2 = _coerce({"sentiment": 0.1, "time_horizon": "near_term",
                  "key_number": "$2.50 EPS guidance", "claim_type": "forecast"}, item, "m")
    assert e2.time_horizon == "near_term" and e2.claim_type == "forecast"
    assert e2.key_number == "$2.50 EPS guidance"


def test_coerce_clamps_confidence_and_defends_quote():
    """Confidence is a same-pass self-rating, documented as unreliable - it
    must still be well-typed (clamped to [0,1], None when absent/malformed)
    so a bad value can't silently propagate as a false-precision number."""
    from trdrbot.news_extract import _coerce

    item = {"id": "1", "headline": "H"}
    assert _coerce({"sentiment": 0.0, "confidence": 5}, item, "m").confidence == 1.0
    assert _coerce({"sentiment": 0.0, "confidence": "high"}, item, "m").confidence is None
    e = _coerce({"sentiment": 0.0, "quote": "guidance raised to $2.50"}, item, "m")
    assert e.quote == "guidance raised to $2.50"


def test_render_block_shows_number_horizon_and_citation_together():
    from trdrbot.news_extract import Extract, render_block

    e = Extract(id="1", headline="H", sentiment=0.6, activity="guidance", regime="company",
                time_horizon="near_term", key_number="$2.50 EPS", claim_type="forecast",
                confidence=0.8, dense="Guidance raised", url="https://ex.com/a", source="Reuters")
    out = render_block([e])
    assert "$2.50 EPS (forecast)" in out
    assert "/near_term" in out
    assert "conf=0.8" in out
    assert "<https://ex.com/a>" in out


# ---------------------------- D-070 shakedown findings

def test_served_model_is_read_from_the_ledger_not_the_config(tmp_path):
    """The journal recorded `config.model` as "the model that made this
    decision". When the fallback fires that is false - 19 cycles were
    journalled as claude-opus-5 while the usage ledger showed gpt-5 served
    every one. Fallback is not an error and leaves no error record, so
    nothing else would ever have contradicted it."""
    from trdrbot.usage import UsageLedger

    from trdrbot import ids

    led = UsageLedger(tmp_path / "u.jsonl", {})
    led.record("decide", "claude-opus-5", 10, 10)   # an EARLIER cycle
    # Production takes the mark fresh, before the cycle's first call - not
    # from a prior call's timestamp (tick.py: `decide_started_at`).
    mark = ids.utc_now().isoformat()
    led.record("decide", "gpt-5", 10, 10)           # this cycle: fallback fired
    led.record("news_extract", "gpt-4o-mini", 5, 5)  # another role, same window

    served = led.served_since("decide", mark)
    assert served == ["gpt-5"], f"must report what actually served, got {served}"
    assert "gpt-4o-mini" not in served, "must not leak other roles' models"


def test_served_since_reports_every_model_when_a_chain_fails_over_mid_cycle(tmp_path):
    """One decide cycle is several LLM calls; a chain that fails over halfway
    genuinely WAS served by two models. Collapsing that to one name would
    trade a known lie for a subtler one."""
    from trdrbot.usage import UsageLedger

    from trdrbot import ids

    led = UsageLedger(tmp_path / "u.jsonl", {})
    mark = ids.utc_now().isoformat()
    for m in ("claude-opus-5", "gpt-5", "gpt-5"):
        led.record("decide", m, 1, 1)
    assert led.served_since("decide", mark) == ["claude-opus-5", "gpt-5"]


def test_news_payload_keeps_the_publisher_article_id():
    """The article id is the news_extract cache key. Dropping it - as the
    payload originally did - meant the same article cached under the inbox
    item id from the decide path and the publisher id from a direct get_news
    call: extracted twice, paid for twice, dedup silently defeated."""
    from trdrbot.sensors import _news_payload

    p = _news_payload({"id": "abc123", "headline": "H", "summary": "S",
                       "source": "reuters", "symbols": ["SPY"],
                       "created_at": "2026-08-28T09:00:00Z", "url": "https://x/1"})
    assert p["id"] == "abc123", "cache key must survive into the payload"
    assert p["url"] == "https://x/1", "citation must survive too"


def test_record_forecast_refuses_a_band_history_almost_always_holds(tmp_path):
    """Calibration gates SIZE, so a vacuous forecast that scores 'right'
    walks the agent up the ladder on evidence of nothing. The ladder's only
    n-gate is a COUNT, so inflating the count is the cheapest way to earn
    size dishonestly and nothing else would have noticed."""
    from datetime import date, timedelta
    from trdrbot import market_stats
    from trdrbot.local_tools import _vacuity_check

    closes = [100.0 * (1.0005 ** i) for i in range(120)]  # calm, no big moves
    market_stats.save_closes(tmp_path, "TEST", closes)
    spot = closes[-1]
    horizon = (date.today() + timedelta(days=3)).isoformat()

    gamed = _vacuity_check(tmp_path, "TEST", 0.97, horizon, 1.0, 100000.0)
    assert gamed and "uninformative" in gamed

    honest = _vacuity_check(tmp_path, "TEST", 0.55, horizon, spot * 0.999, spot * 1.001)
    assert honest is None, "a genuinely uncertain band must pass"


def test_vacuity_guard_keeps_a_contrarian_call_against_an_extreme_base(tmp_path):
    """The muse learned this the hard way: a naive ceiling rejected a stated
    27% against a 99% base - the single most interesting call it produced.
    Disagreeing with history IS the claim, so only AGREEMENT is vacuous."""
    from datetime import date, timedelta
    from trdrbot import market_stats
    from trdrbot.local_tools import _vacuity_check

    closes = [100.0 * (1.0005 ** i) for i in range(120)]
    market_stats.save_closes(tmp_path, "TEST", closes)
    spot = closes[-1]
    horizon = (date.today() + timedelta(days=3)).isoformat()

    assert _vacuity_check(tmp_path, "TEST", 0.27, horizon, spot * 0.8, spot * 1.2) is None


def test_vacuity_guard_fails_open_without_price_history(tmp_path):
    """No anchor means no judgement. An invented one is worse than none -
    the same rule _plausible_band follows when it has no spot."""
    from datetime import date, timedelta
    from trdrbot.local_tools import _vacuity_check

    horizon = (date.today() + timedelta(days=3)).isoformat()
    assert _vacuity_check(tmp_path, "NOHIST", 0.99, horizon, 1.0, 99999.0) is None
    assert _vacuity_check(None, "TEST", 0.99, horizon, 1.0, 99999.0) is None


def test_health_separates_idle_attribution_from_a_stalled_one(tmp_path):
    """attribution ran 36x and produced nothing, which health called a hard
    FAIL - but every run recorded `pending: 0`: nothing was DUE, because
    theses resolve at their horizon. A check that cries wolf trains the
    reader to skip the one line that finally matters. The real signal must
    still fire when work genuinely was waiting."""
    import json
    from trdrbot.health import BAD, OK, check

    def journal(pending: int) -> "object":
        p = tmp_path / f"j{pending}.jsonl"
        p.write_text("".join(
            json.dumps({"kind": "attribution_run", "pending": pending,
                        "attributed": 0, "skipped_no_price": 0}) + "\n"
            for _ in range(10)))
        return p

    idle = dict((name, (lvl, msg)) for lvl, name, msg in check(journal(0), []))
    assert idle["attribution"][0] == OK, "nothing due must not read as broken"
    assert "idle" in idle["attribution"][1]

    stalled = dict((name, (lvl, msg)) for lvl, name, msg in check(journal(4), []))
    assert stalled["attribution"][0] == BAD, \
        "work waiting and nothing attributed is a REAL failure and must still fire"


# ---------------------------- D-071 remaining shakedown fixes

def test_our_own_code_bugs_are_not_classified_as_transient():
    """Live: `ValueError: unsupported format character ','` - a broken format
    string in OUR code - was classified TRANSIENT, queueing a blameless
    observation to burn three retries and then dead-letter itself for a
    defect it had nothing to do with. Exactly the loss CONFIG was created to
    prevent, arriving through the one door CONFIG did not cover."""
    from trdrbot.failures import Cause, classify

    for exc in (ValueError("unsupported format character ','"),
                AttributeError("'NoneType' has no attribute 'x'"),
                TypeError("unsupported operand type(s)")):
        assert classify(exc) is Cause.BUG, f"{type(exc).__name__} is our bug, not a blip"


def test_network_failures_still_classify_as_transient_despite_being_oserrors():
    """ConnectionError and TimeoutError subclass OSError, so the name-marker
    checks MUST stay ahead of the isinstance check that spots our own bugs."""
    from trdrbot.failures import Cause, classify

    assert classify(ConnectionError("reset")) is Cause.TRANSIENT
    assert classify(TimeoutError("timed out")) is Cause.TRANSIENT


def test_a_code_bug_leaves_the_inbox_item_untouched(tmp_path):
    """The whole point: our bug must not consume the item's retries."""
    import json
    from trdrbot.failures import Cause
    from trdrbot.inbox import Inbox, Item

    class P:
        inbox_pending = tmp_path / "pending"
        inbox_failed = tmp_path / "failed"
    P.inbox_pending.mkdir(parents=True)
    item_path = P.inbox_pending / "i.json"
    item = Item(id="i", ts="2026-08-28T00:00:00Z", type="news", source="alpaca_news",
                payload={}, trust="primary", path=item_path)
    item_path.write_text(json.dumps(item.to_dict()))

    Inbox(P(), max_retries=3).record_failure(item, "our bug", cause=Cause.BUG)

    assert item_path.exists(), "a bug in our code must not dead-letter the item"
    assert json.loads(item_path.read_text()).get("retry_count", 0) == 0, \
        "a blameless item must not lose a retry to our defect"


def test_rejected_opportunity_names_the_field_that_was_missing():
    """Every rejection journalled the same opaque 'unscoreable_opportunity',
    so a fully-reasoned CRM thesis dropped for one absent `horizon` looked
    identical to genuine garbage. A repeating defect is a fixable prompt
    problem; an opaque one is just attrition."""
    from trdrbot.research import opportunity_defect

    crm = {"underlying": "CRM", "claim": "CRM holds above 232",
           "drift_pct": 1.0, "band_low": 232.0, "band_high": None}
    assert opportunity_defect(crm) == "missing_horizon"
    assert opportunity_defect(dict(crm, horizon="2026-09-03")) is None
    assert opportunity_defect({"underlying": "X", "claim": "c",
                               "horizon": "2026-09-03"}) == "missing_band"
    assert opportunity_defect({"underlying": "X", "claim": "c", "band_low": 1.0,
                               "horizon": "next tuesday"}) == "bad_horizon_format"


# ---------------------------- D-072 credit assignment phase 1

def _item(kind, payload, iid="i1"):
    from trdrbot.inbox import Item
    return Item(id=iid, ts="2026-08-28T00:00:00Z", type=kind,
                source="test", payload=payload, trust="primary")


def _cfg(watchlist):
    from pathlib import Path
    from trdrbot.config import Config

    class P:
        state = Path("/tmp")
    return Config(raw={"trading": {"watchlist": watchlist},
                       "research": {"universe": ["SPY", "NVDA"]}}, paths=P())


def test_attention_query_names_what_is_actually_being_traded():
    """Was a constant: `" ".join(watchlist) + " options setup"`. With watchlist
    ["SPY"], the NVDA position was decided with SPY memories in context and
    then CREDITED them - 2 of its 3 creditable blocks were about the wrong
    underlying. Retrieval was answering a question nobody asked."""
    from trdrbot.tick import _attention_query

    q = _attention_query([_item("opportunity", {"underlying": "NVDA"})], [], _cfg(["SPY"]))
    assert "NVDA" in q, "the name under consideration must reach memory"
    assert q.index("NVDA") < q.index("SPY"), "what we may act on outranks the static watchlist"


def test_attention_query_prefers_open_positions_over_everything():
    """Money already at risk is the most decision-relevant thing there is."""
    from trdrbot.tick import _attention_query

    class Pos:
        underlying = "XLE"
    q = _attention_query([_item("opportunity", {"underlying": "NVDA"})], [Pos()], _cfg(["SPY"]))
    assert q.startswith("XLE"), f"open position must lead the query, got {q!r}"


def test_attention_query_cannot_be_drowned_by_a_market_wrap_article():
    """Caught on the FIRST live run, before shipping: a real article tagged
    twelve ETFs and the unfiltered query asked memory about "AGG BND GLD",
    pushing SPY - the only name in the book - to fourth. That was worse than
    the constant it replaced. An article's ticker list is what it mentions,
    not what we are deciding about, so news names are filtered to ones we
    could actually trade."""
    from trdrbot.tick import _attention_query

    wrap = _item("news", {"symbols": ["AGG", "BND", "GLD", "IAU", "IEF",
                                      "ITOT", "OUNZ", "SPY", "VTI"]})
    q = _attention_query([wrap], [], _cfg(["SPY"]))
    assert q == "SPY options setup", f"untradeable news names must not enter: {q!r}"

    both = _attention_query([_item("opportunity", {"underlying": "NVDA"}), wrap], [], _cfg(["SPY"]))
    assert both.startswith("NVDA"), "the opportunity must still lead"
    assert "GLD" not in both and "AGG" not in both


def test_attention_query_keeps_an_opportunity_outside_the_universe():
    """Discovery nominates names off-universe on purpose - that is its job -
    so an opportunity is never filtered, only news is."""
    from trdrbot.tick import _attention_query

    q = _attention_query([_item("opportunity", {"underlying": "BURL"})], [], _cfg(["SPY"]))
    assert q.startswith("BURL"), f"a nominated candidate must reach memory: {q!r}"


def test_attention_query_falls_back_to_the_watchlist_when_nothing_is_in_play():
    """An empty cycle must still recall something, not query the empty string."""
    from trdrbot.tick import _attention_query

    assert _attention_query([], [], _cfg(["SPY"])) == "SPY options setup"


def test_attribution_skips_the_outcome_call_entirely_on_a_none_signal():
    """`signal is None` must mean no Beta update reaches elfmem at all - not
    an update with a neutral-looking number."""
    import inspect
    from trdrbot import attribution

    src = inspect.getsource(attribution.run)
    assert "signal is not None" in src, \
        "a None signal must gate the credit call, not be passed through"
    assert "attribution_credit_short" in src, \
        "credit reaching fewer blocks than requested must leave evidence"


# ---------------------------- D-073 similarity-weighted credit (phase 2)

def test_credit_weight_never_returns_zero_because_elfmem_rejects_it():
    """THE edge case that would have crashed attribution on its first weighted
    credit. `similarity` is MIN-MAX NORMALISED within each result set, so the
    worst-matching block of every recall carries exactly 0.0 - and elfmem's
    `_validate_weight` raises ValueError on weight <= 0. Measured live: the
    SPY mind model came back at similarity 0.0 on both a SPY and an NVDA
    query."""
    from trdrbot.positions import CREDIT_WEIGHT_FLOOR, credit_weight

    assert credit_weight(0.0) == CREDIT_WEIGHT_FLOOR > 0.0
    assert all(credit_weight(s) > 0.0 for s in (0.0, -1.0, 0.5, 1.0, 2.0))


def test_credit_weight_maps_similarity_monotonically_and_clamps():
    from trdrbot.positions import credit_weight

    assert credit_weight(1.0) == 1.0
    assert credit_weight(0.0) < credit_weight(0.5) < credit_weight(1.0)
    assert credit_weight(2.0) == 1.0, "out-of-range similarity must clamp, not extrapolate"
    assert credit_weight(-1.0) == credit_weight(0.0)


def test_credit_weight_defaults_to_full_when_no_similarity_was_recorded():
    """A pre-v2 position credits exactly as it did when it was written -
    never silently re-weighted by a rule that did not exist then. Unreadable
    input must not silently zero a block's credit either."""
    from trdrbot.positions import credit_weight

    assert credit_weight(None) == 1.0
    assert credit_weight("not a number") == 1.0


def test_old_list_shaped_positions_still_credit_at_full_weight():
    """Backward compatibility, on the real stored shape."""
    from trdrbot.positions import Position

    p = Position(position_id="p", underlying="NVDA", strategy="s",
                 elfmem_blocks={"attention": ["a", "b"], "self": ["c"]})
    assert p.credit_weights() == {"a": 1.0, "b": 1.0}
    assert p.all_elfmem_block_ids == ["a", "b"], "id readers must be shape-agnostic"


def test_weighted_position_credits_by_similarity_and_still_excludes_self():
    """The dilution fix: on an NVDA trade the SPY mind model (similarity 0.0)
    must earn a fraction of what the NVDA-relevant block earns, not the same."""
    from trdrbot.positions import Position

    p = Position(position_id="p", underlying="NVDA", strategy="s",
                 elfmem_blocks={"attention": {"nvda_fact": 1.0, "spy_mind": 0.0},
                                "self": {"principle": 0.9}})
    w = p.credit_weights()
    assert w["nvda_fact"] == 1.0
    assert w["spy_mind"] == 0.25
    assert "principle" not in w, "SELF is never credited (D-033/D-041)"
    assert sorted(p.recalled_block_ids()) == ["nvda_fact", "principle", "spy_mind"]


def test_add_recalled_block_preserves_whichever_shape_is_in_use():
    from trdrbot.positions import Position

    old = Position(position_id="p", underlying="X", strategy="s",
                   elfmem_blocks={"attention": ["a"]})
    old.add_recalled_block("attention", "b")
    assert old.elfmem_blocks["attention"] == ["a", "b"]

    new = Position(position_id="p", underlying="X", strategy="s",
                   elfmem_blocks={"attention": {"a": 0.5}})
    new.add_recalled_block("attention", "b", similarity=1.0)
    assert new.elfmem_blocks["attention"] == {"a": 0.5, "b": 1.0}

    fresh = Position(position_id="p", underlying="X", strategy="s")
    fresh.add_recalled_block("attention", "a")
    assert fresh.credit_weights() == {"a": 1.0}


def test_weighted_position_round_trips_through_yaml(tmp_path):
    """Position files are YAML frontmatter; a float-valued dict must survive."""
    from trdrbot.positions import Position, PositionStore

    store = PositionStore(tmp_path)
    store.save(Position(position_id="pos_x", underlying="NVDA", strategy="s",
                        elfmem_blocks={"attention": {"aaa": 1.0, "bbb": 0.0}}))
    back = store.load("pos_x")
    assert back.credit_weights() == {"aaa": 1.0, "bbb": 0.25}


def test_attribution_groups_credit_by_weight():
    """Blocks sharing a weight go in one call - a 3-block position costs one
    or two calls, not three, and the grouping is deterministic so the path can
    be replayed from the journal."""
    import inspect
    from trdrbot import attribution

    src = inspect.getsource(attribution.run)
    assert "credit_weights()" in src, "credit must be weighted, not uniform"
    assert "sorted(groups.items())" in src, "grouping must be deterministic"


# =============================================================== D-074 shakedown
# Every test below names a defect found by reading LIVE state against what the
# code claims, and pins the belief that was wrong.


def test_pnl_percent_is_of_net_entry_cost_not_gross_premium():
    """The exit-rule denominator. On a vertical spread gross and net differ by
    2-7x, so every mark-based stop the agent ever wrote was measured against a
    base several times larger than the money it put up - and three of the four
    rules on the live book could never fire at all."""
    from trdrbot.analytics import Snapshot, position_pnl_pct

    # Credit spread: sold for 2.65, bought for 1.58, 5 lots -> $535 credit.
    snap = Snapshot(broker_positions=[
        {"symbol": "S", "cost_basis": -1325.0, "unrealized_pl": 267.5},
        {"symbol": "L", "cost_basis": 790.0, "unrealized_pl": 0.0},
    ])
    pnl = position_pnl_pct(["S", "L"], snap)
    assert abs(pnl - 0.50) < 1e-9, "+50% means half the CREDIT, the trader's meaning"
    # On the old gross base ($2,115) the same money read as +12.6%, so a +50%
    # target needed $1,057 against a max profit of $535: unreachable, forever.
    assert pnl > 267.5 / 2115.0 * 3


def test_a_spread_with_no_net_cost_reports_nothing_rather_than_noise():
    from trdrbot.analytics import Snapshot, position_pnl_pct
    snap = Snapshot(broker_positions=[
        {"symbol": "A", "cost_basis": 1000.0, "unrealized_pl": 5.0},
        {"symbol": "B", "cost_basis": -999.0, "unrealized_pl": 0.0},
    ])
    assert position_pnl_pct(["A", "B"], snap) is None, "unobservable holds, never fires blind"


def test_unreachable_exit_rules_are_named_at_record_time():
    """A stop that cannot trigger is a sentence, not a stop."""
    from trdrbot.local_tools import _unreachable_rules

    # The live NVDA debit spread: $2,253 paid, max loss = that. On the CORRECT
    # base its -60% stop is reachable, which is the point - the old gross base
    # is what made it need a $2,287 loss on a position that could only lose
    # $2,253. Nothing to flag here any more.
    assert _unreachable_rules(-60.0, 70.0, net_cost=2253.0,
                              max_profit=7747.0, max_loss=-2253.0) == []
    # Beyond the whole premium, though, there is nothing left to lose.
    bad = _unreachable_rules(-120.0, None, net_cost=2253.0,
                             max_profit=7747.0, max_loss=-2253.0)
    assert any("stop_loss" in b and "NEVER" in b for b in bad)
    # A credit spread's max profit IS the credit, so any target above +100%
    # can never fire - the trap the +50%/-100% pair on the live SPY spread was
    # one arithmetic slip away from.
    bad2 = _unreachable_rules(None, 150.0, net_cost=535.0,
                              max_profit=535.0, max_loss=-1965.0)
    assert any("profit_target" in b and "NEVER" in b for b in bad2)
    assert _unreachable_rules(None, 50.0, net_cost=535.0,
                              max_profit=535.0, max_loss=-1965.0) == []
    # ...and a credit stop past the structure's own max loss.
    bad3 = _unreachable_rules(-400.0, None, net_cost=535.0,
                              max_profit=535.0, max_loss=-1965.0)
    assert any("stop_loss" in b and "NEVER" in b for b in bad3)
    assert _unreachable_rules(-50.0, 50.0, net_cost=0.0, max_profit=1.0, max_loss=-1.0) == []


def test_murphy_reliability_uses_the_stated_probability_not_the_bin_centre():
    """It read the bin CENTRE. Below n=24 there are only two bins, so every
    forecast under 0.5 was scored as if stated at 0.25 and everything above at
    0.75. Live: one forecast stated 0.38, resolved true, scored 0.5625 against
    an honest 0.3844."""
    from trdrbot.calibration import Forecast, score

    c = score([Forecast(position_id="p", probability=0.38, outcome=True)])
    assert abs(c.reliability - (0.38 - 1.0) ** 2) < 1e-9

    # And the gate it feeds now catches the agent it exists to catch.
    over = [Forecast(position_id=f"f{i}", probability=0.95, outcome=(i % 2 == 0))
            for i in range(16)]
    assert score(over).reliability > 0.04, "a 0.95-claiming coin flip must not pass MATURE"


def test_murphy_decomposition_identity_holds():
    """brier = reliability - resolution + uncertainty. It only holds when the
    reliability term uses each bin's mean FORECAST, so the identity is the
    cheapest possible guard against the bin-centre bug returning."""
    import random
    from trdrbot.calibration import Forecast, score

    # Deterministic and deliberately BOTH discriminating and miscalibrated, so
    # neither term hits the small-sample clamp - the clamp is the one place the
    # identity is allowed to break, and it is not what this test is about.
    # Says 0.10 when the truth is 0.30, and 0.90 when the truth is 0.70.
    fs = ([Forecast(position_id=f"lo{i}", probability=0.10, outcome=i < 12) for i in range(40)]
          + [Forecast(position_id=f"hi{i}", probability=0.90, outcome=i < 28) for i in range(40)])
    c = score(fs)
    assert c.reliability > 0.0 and c.resolution > 0.0, "clamp must not bite here"
    assert abs(c.brier - (c.reliability - c.resolution + c.uncertainty)) < 1e-9


def test_size_is_monotonic_in_evidence_across_payoff_shapes():
    """The original invariant test measured integer CONTRACTS at ONE payoff,
    where the `contracts < 1 -> 1` floor pinned every rung to the same number
    and hid two inversions. Sweeping the payoff surfaces both:

      - EXPLORE -> ESTABLISH cut a 1:1 bet at 62% from 4 contracts to 1,
        because the first Kelly rung sits below the exploration allocation;
      - crossing MIN_SAMPLE swapped the gate from the stated probability to
        the shrunk one, taking an 88% credit spread from 1 contract to zero
        while its calibration was excellent and unchanged."""
    from trdrbot import competence, sizing
    from trdrbot.calibration import Calibration

    shapes = [(500.0, -500.0, 0.62), (800.0, -1200.0, 0.70),
              (300.0, -1700.0, 0.88), (2000.0, -500.0, 0.35)]
    for mp, ml, conf in shapes:
        prev = -1.0
        for n in [0, 1, 4, 5, 8, 12, 15, 20, 30, 40, 60, 100]:
            cal = Calibration(n=n, brier=0.2, reliability=0.02, resolution=0.05,
                              uncertainty=0.24, base_rate=0.6)
            post = competence.assess(resolved=n, reliability=0.02 if n >= 8 else None,
                                     positions=[], equity=100_000.0, high_water=100_000.0)
            got = sizing.size_position(
                equity=100_000.0, stated_confidence=conf, max_profit=mp, max_loss=ml,
                calibration=cal, posture=post, underlying="SPY").fraction_of_equity
            assert got >= prev - 1e-9, (
                f"payoff {mp}/{ml} at {conf:.0%}: n={n} sized {got:.3%}, "
                f"below the previous {prev:.3%}")
            prev = got


def test_a_genuinely_edgeless_structure_is_still_refused():
    """The floor must not rescue a bet with no claimed edge at all."""
    from trdrbot import competence, sizing
    from trdrbot.calibration import Calibration

    cal = Calibration(n=20, brier=0.2, reliability=0.02, resolution=0.05,
                      uncertainty=0.24, base_rate=0.6)
    post = competence.assess(resolved=20, reliability=0.02, positions=[],
                             equity=100_000.0, high_water=100_000.0)
    d = sizing.size_position(equity=100_000.0, stated_confidence=0.70, max_profit=300,
                             max_loss=-1700, calibration=cal, posture=post, underlying="SPY")
    assert d.contracts == 0 and "NO POSITION" in d.reason


def test_a_claim_the_record_does_not_support_is_reported_not_hidden():
    from trdrbot import competence, sizing
    from trdrbot.calibration import Calibration

    cal = Calibration(n=20, brier=0.2, reliability=0.02, resolution=0.05,
                      uncertainty=0.24, base_rate=0.6)
    post = competence.assess(resolved=20, reliability=0.02, positions=[],
                             equity=100_000.0, high_water=100_000.0)
    d = sizing.size_position(equity=100_000.0, stated_confidence=0.88, max_profit=300,
                             max_loss=-1700, calibration=cal, posture=post, underlying="SPY")
    assert d.contracts >= 1
    assert "record does not support" in d.reason


def test_expected_value_moves_with_the_thesis():
    """`ev_after_costs` was computed at drift ZERO - the market's own
    distribution - where a fairly priced structure is worth about nothing and
    after friction is negative for every candidate, always. The journal is full
    of cycles declining on exactly that number."""
    from trdrbot.experiments import Experiment, Thesis, simulate
    from trdrbot.optmath import Leg

    legs = [Leg.parse({"right": "C", "strike": 100, "side": "long", "qty": 1, "price": 3.0}),
            Leg.parse({"right": "C", "strike": 105, "side": "short", "qty": 1, "price": 1.4})]
    exp = Experiment(name="call spread", legs=legs)
    flat = simulate(exp, Thesis("no view", "X", "2026-09-04", drift=0.0), 100.0, 0.25, 7)
    bull = simulate(exp, Thesis("up 4%", "X", "2026-09-04", drift=0.04), 100.0, 0.25, 7)

    assert flat["ev_after_costs"] < bull["ev_after_costs"], "the view must move the number"
    assert abs(flat["ev_after_costs"] - flat["ev_market_after_costs"]) < 1e-9
    assert bull["ev_market_after_costs"] == flat["ev_market_after_costs"], (
        "the market column must not move with the agent's view")


def test_bootstrap_resamples_sessions_not_calendar_days():
    """`days` is calendar days to expiry; the returns are per session. Drawing
    one per calendar day priced in weekends that never traded - variance 1.45x
    too high on a typical tenor, and a fifth of every 'the tails disagree'
    warning was the units rather than the tails."""
    import statistics
    from trdrbot import market_stats

    import math
    closes = gbm(n=2000, seed=5)
    rets = market_stats._log_returns(closes)
    sd_session = statistics.pstdev(rets)

    # 7 CALENDAR days is 5 sessions. Dispersion must scale by sqrt(5), not the
    # sqrt(7) the calendar-day loop produced - a 1.18x over-wide distribution
    # on this tenor, and 1.45x too much variance.
    got = statistics.pstdev([math.log(f)
                             for f in market_stats.bootstrap_factors(closes, 7, seed="a")])
    sessions, calendar = sd_session * math.sqrt(5), sd_session * math.sqrt(7)
    assert abs(got - sessions) < abs(got - calendar), (
        f"spread {got:.5f} sits closer to sqrt(7)={calendar:.5f} than "
        f"sqrt(5)={sessions:.5f} - still resampling calendar days")
    assert abs(got / sessions - 1.0) < 0.05
    assert market_stats.bootstrap_factors(closes, 1, seed="a"), "never zero draws"


def test_compaction_understands_the_real_mcp_envelope():
    """The compactors were written against a dict; the adapter returns
    `([{'type':'text','text': json}], artifact)` because it builds its tools
    with response_format='content_and_artifact'. Every call therefore took the
    fail-open path and returned the original - silently, for all 28 option
    chains on the journal."""
    import asyncio
    import json as _json
    from trdrbot import compact

    payload = {"snapshots": {
        f"SPY260902{r}{k * 1000:08d}": {
            "latestQuote": {"bp": 1.0, "ap": 1.2, "bs": 5, "as": 5},
            "latestTrade": {"p": 1.1},
        } for k in range(600, 900, 5) for r in "CP"
    }}
    envelope = {"_alpaca_mcp_security": {"trust": "untrusted_tool_output"}, "data": payload}

    class T:
        name = "get_option_chain"
        async def coroutine(self, **kw):
            return ([{"type": "text", "text": _json.dumps(envelope)}], None)

    tool = compact.wrap_heavy_tools([T()])[0]
    out = asyncio.run(tool.coroutine())
    assert isinstance(out, tuple) and len(out) == 2, "envelope shape must be preserved"
    text = out[0][0]["text"]
    assert "Option chain (compacted)" in text
    assert len(text) < len(_json.dumps(envelope)) / 2, "the whole point is the size"
    assert "1.00x5" in text and "1.20x5" in text, "prices reproduced verbatim"


def test_atm_is_inferred_by_parity_when_the_page_is_one_sided():
    """A real SPY chain page comes back as 100 CALLS, no puts, strikes 500-773,
    with a next page. The median-strike fallback put ATM at 724 against a tape
    of 771.67; parity from the calls alone gives 768.78."""
    from trdrbot import compact

    # C + K >= S, tightest at the deepest ITM strike.
    snaps = {}
    spot = 771.0
    for k in (700, 720, 740, 760):
        mid = spot - k + 0.5  # deep ITM call: intrinsic plus a little extrinsic
        snaps[f"SPY260902C{k * 1000:08d}"] = {
            "latestQuote": {"bp": mid - 0.05, "ap": mid + 0.05, "bs": 1, "as": 1}}
    out = compact.compact_option_chain({"snapshots": snaps})
    assert "page holds C only" in out
    header = out.splitlines()[0]
    atm = float(header.split("ATM~")[1].split(";")[0])
    assert abs(atm - spot) < 3.0, f"parity ATM {atm} should be near {spot}"


def test_a_stated_forecast_is_not_swallowed_by_a_placeholder(tmp_path):
    """A pre-registered thesis carries an unstated 0.5. Matching a standalone
    forecast to it returned the PLACEHOLDER, so the agent's real number was
    never written and the row stayed invisible to calibration."""
    from trdrbot.ledger import Ledger, STANDALONE, THESIS

    book = Ledger(tmp_path / "ledger.jsonl")
    book.register(kind=THESIS, underlying="SPY", claim="pre-reg", probability=0.5,
                  probability_stated=False, horizon="2026-09-02",
                  band_low=765.0, band_high=None)
    real = book.register(kind=STANDALONE, underlying="SPY", claim="my call",
                         probability=0.67, horizon="2026-09-02",
                         band_low=765.0, band_high=None)
    assert real.probability == 0.67 and real.probability_stated
    # ...while a genuine repeat of the SAME kind still dedups.
    again = book.register(kind=STANDALONE, underlying="SPY", claim="my call",
                          probability=0.67, horizon="2026-09-02",
                          band_low=765.0, band_high=None)
    assert again.id == real.id


def test_health_sees_a_subsystem_that_produced_once_and_then_died(tmp_path):
    """`interim_scoring` read its own OUTPUT rows as evidence it had run, so
    the probe was a tautology and eight rows from day one read as healthy for
    two days and ~250 ticks."""
    import json as _json
    from trdrbot import health

    rows = [{"kind": "interim_run", "eligible": 1, "scored": 1}]
    rows += [{"kind": "interim_run", "eligible": 1, "scored": 0}] * 40
    p = tmp_path / "journal.jsonl"
    p.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")
    found = {name: (lvl, detail) for lvl, name, detail in health.check(p, [])}
    lvl, detail = found["interim_scoring"]
    assert lvl == health.BAD and "last 40 runs" in detail

    # But an idle subsystem with nothing eligible is not a stalled one.
    idle_rows = [{"kind": "interim_run", "eligible": 1, "scored": 1}]
    idle_rows += [{"kind": "interim_run", "eligible": 0, "scored": 0}] * 40
    p.write_text("\n".join(_json.dumps(r) for r in idle_rows) + "\n")
    found = {name: (lvl, detail) for lvl, name, detail in health.check(p, [])}
    assert found["interim_scoring"][0] == health.OK


def test_the_reachability_warning_is_actually_WIRED(tmp_path):
    """`_unreachable_rules` being correct is not the same as it running. The
    wiring - match the traded legs against what simulate_experiments priced,
    scale by the quantity actually traded - is the part that silently no-ops,
    which is this whole pass's theme. So it is exercised end to end."""
    from trdrbot import local_tools
    from trdrbot.calibration import CalibrationStore
    from trdrbot.positions import PositionStore

    shared: dict = {}
    sim = local_tools.build_simulate_experiments(shared, None, None)
    sim.func(
        thesis_claim="up", underlying="SPY", horizon="2026-09-02", drift_pct=0.5,
        spot=771.0, iv_pct=11.0, days_to_expiry=5, band_low=765.0, band_high=782.0,
        candidates=[
            {"name": "debit", "legs": [
                {"right": "C", "strike": 773, "side": "long", "qty": 1, "price": 3.10},
                {"right": "C", "strike": 778, "side": "short", "qty": 1, "price": 1.35}]},
            {"name": "credit", "legs": [
                {"right": "P", "strike": 765, "side": "short", "qty": 1, "price": 1.90},
                {"right": "P", "strike": 760, "side": "long", "qty": 1, "price": 1.10}]},
        ])
    assert len(shared["structures"]) == 2

    store = PositionStore(tmp_path)
    rec = local_tools.build_record_position(
        store, "jrn_x", shared=shared,
        calibration=CalibrationStore(tmp_path / "f.jsonl"))

    # Simulated at 1 lot, traded at 3: the check must scale, not compare a
    # 3-lot loss against a 1-lot structure.
    def record(strategy, stop, target):
        return rec.func(
            underlying="SPY", strategy=strategy,
            legs=[{"symbol": "SPY260902C00773000", "side": "buy", "qty": 3},
                  {"symbol": "SPY260902C00778000", "side": "sell", "qty": 3}],
            thesis="up", confidence=0.6, expiry="2026-09-02",
            stop_loss_pct=stop, profit_target_pct=target, underlying_stop_below=765.0)

    assert "cannot trigger" not in record("s1", -50.0, 60.0)

    impossible = record("s2", -150.0, 400.0)
    assert "$525" in impossible, "max loss must be the 3-lot figure, not the 1-lot one"
    assert "$975" in impossible, "max profit must be scaled too"
    assert "stop_loss -150%" in impossible and "profit_target 400%" in impossible

    # Legs that match nothing simulated: skip silently rather than guess.
    other = rec.func(
        underlying="SPY", strategy="s3",
        legs=[{"symbol": "SPY260902P00700000", "side": "sell", "qty": 1}],
        thesis="x", confidence=0.6, expiry="2026-09-02", stop_loss_pct=-999.0)
    assert "cannot trigger" not in other
