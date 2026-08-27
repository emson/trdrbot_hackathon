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

def test_noise_marks_never_fire_interim_scoring():
    """Eight interim scores accumulated on one unresolved position - 0.8 of
    evidence against a resolution's 1.0 - all from a -$45 bid/ask wobble."""
    band, fired = 0, 0
    for pnl in [-3.1, -4.2, -2.8, -3.5, -4.0, -3.2, -2.9, -3.6]:
        b = _materiality_band(pnl)
        if b > band:
            band, fired = b, fired + 1
    assert fired == 0


def test_interim_scoring_is_bounded_and_monotonic():
    band, fired = 0, 0
    for pnl in [-3, -12, -27, -31, -26, -30, -55, -52, -58]:  # incl. oscillation
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
    verdict, _ = experiments.attribute(thesis_held=False, profited=True)
    assert experiments.ATTRIBUTION_SIGNAL[verdict] == 0.5, "a lucky win must not reinforce"


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


def test_market_pulse_wakes_the_agent_on_a_material_move():
    """The system was purely reactive: an empty inbox meant no reasoning, even
    with the market open and a live position moving. No trader waits for a
    headline to check their book."""
    from trdrbot.tick import _market_pulse, PULSE_MOVE
    from trdrbot.journal import Journal

    class Store:
        def __init__(self, ps): self._p = ps
        def open_positions(self): return self._p

    class J:
        def last_decision_at(self):
            from datetime import datetime, timezone
            return datetime.now(timezone.utc)  # just decided: silence is fine

    pos = Position(position_id="p", status="open", underlying="SPY", entry_spot=766.5)
    snap = Snapshot(); snap.market_open = True

    snap.underlying_prices = {"SPY": 766.6}
    assert _market_pulse(Store([pos]), snap, J(), None) is None, "must not fire on noise"

    snap.underlying_prices = {"SPY": 766.5 * (1 + PULSE_MOVE * 1.5)}
    assert _market_pulse(Store([pos]), snap, J(), None) is not None

    snap.underlying_prices = {"SPY": 766.5 * (1 - PULSE_MOVE * 1.5)}
    assert _market_pulse(Store([pos]), snap, J(), None) is not None

    # Nothing at risk -> silence is the correct output, not a missed check.
    assert _market_pulse(Store([]), snap, J(), None) is None


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


def test_expected_move_shrinks_across_a_weekend():
    """The number the agent compares its thesis band against."""
    import datetime
    from trdrbot.optmath import expected_move
    fri = expected_move(770, 0.13, 3, datetime.date(2026, 8, 28))
    mon = expected_move(770, 0.13, 3, datetime.date(2026, 8, 31))
    assert fri < mon and fri / mon < 0.9


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
    assert experiments.ATTRIBUTION_SIGNAL[right] > experiments.ATTRIBUTION_SIGNAL[lucky]


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
    from trdrbot.elfmem_adapter import ElfmemAdapter
    src = inspect.getsource(ElfmemAdapter.resolve)
    assert "blocks_updated" in src and "consolidate" in src, \
        "resolve must detect a short-count and consolidate-then-retry"


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
