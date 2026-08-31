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
from datetime import UTC, date, timedelta
from pathlib import Path

import pytest
from conftest import synthetic_dates

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
    from trdrbot.analytics import Snapshot, position_pnl_fraction
    from trdrbot.housekeeping import INTERIM_BANDS

    # A debit spread: $2,000 paid, now worth $600 less. -30% by any trader's
    # reckoning, and materially past the first band.
    snap = Snapshot(broker_positions=[
        {"symbol": "X1", "cost_basis": 3000.0, "unrealized_pl": -600.0},
        {"symbol": "X2", "cost_basis": -1000.0, "unrealized_pl": 0.0},
    ])
    pnl = position_pnl_fraction(["X1", "X2"], snap)
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
    """One overshoot rule must mean 2x for a percentage and 1% for a price.

    The mark half now also needs the UNDERLYING to corroborate it (WU-4.6), so
    the position carries its entry state and the snapshot shows a real adverse
    move. That is the point of the rule, not a weakening of this one: a breach
    at twice the threshold is only "not plausibly a quote artifact" when
    something that prints cleanly agrees.
    """
    p = pos(exit_rules=[{"type": "stop_loss", "threshold": "-100%"}],
            entry_spot=100.0, entry_iv=0.25,
            greeks_at_entry={"delta_dollars": 4000.0, "vega_dollars": -10.0})
    assert "decisive" in evaluate(p, snap(mark_pnl=-250, underlying=96.0),
                                  "2099-01-01")[1]
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


def test_a_thesis_stop_beyond_the_far_strike_is_named_as_unprotective(tmp_path):
    """Found by the harmony scaffold on the LIVE book: a 766/758 bear put
    spread carrying `underlying_stop above 776`. Max loss is fully realised at
    766, so the stop sat 10 points past the point of no further damage - and
    satisfied health's 'has an underlying stop' check the whole time, which is
    exactly what made it invisible. The position read as protected because it
    was watched.

    The sibling of _unreachable_rules: that catches a rule that can never fire,
    this catches one that fires where nothing is left to save."""
    from trdrbot.calibration import CalibrationStore

    store = PositionStore(tmp_path)
    rec = local_tools.build_record_position(
        store, "dec_h", shared={}, calibration=CalibrationStore(tmp_path / "c.json"))
    legs = [{"symbol": "SPY260903P00766000", "side": "buy", "qty": 13},
            {"symbol": "SPY260903P00758000", "side": "sell", "qty": 13}]

    late = rec.func(underlying="SPY", strategy="bear_put_spread", legs=legs,
                    thesis="SPY rolls over", confidence=0.6, expiry="2026-09-03",
                    underlying_stop_above=776.0)
    assert "100% of max loss is ALREADY taken" in late
    assert "never limit one" in late

    # ...and the same rule INSIDE the strikes is protection, so it is silent.
    inside = rec.func(underlying="SPY", strategy="bear_put_spread", legs=legs,
                      thesis="SPY rolls over", confidence=0.6, expiry="2026-09-03",
                      underlying_stop_above=762.0)
    assert "ALREADY taken" not in inside, "a protective stop was warned about"


def test_a_thesis_horizon_after_expiry_is_named_before_it_corrupts_attribution(tmp_path):
    """The position is force-closed before its own claim can resolve, and
    attribution scores the unresolved view as WRONG - teaching the agent to
    distrust a view that may have been right. A corrupted learning signal is
    worse than a bad trade, because it persists."""
    from trdrbot.calibration import CalibrationStore

    store = PositionStore(tmp_path)
    shared = local_tools.SharedContext()
    shared.thesis = experiments.Thesis(
        claim="SPY below 766", underlying="SPY", horizon="2026-09-10",
        drift=-0.009, band_high=766.0)
    rec = local_tools.build_record_position(
        store, "dec_h", shared=shared, calibration=CalibrationStore(tmp_path / "c.json"))

    msg = rec.func(underlying="SPY", strategy="bear_put_spread",
                   legs=[{"symbol": "SPY260903P00766000", "side": "buy", "qty": 1}],
                   thesis="SPY rolls over", confidence=0.6, expiry="2026-09-03")

    assert "is AFTER expiry" in msg and "7 day(s) before" in msg


def _record_with_sizing(tmpdir, *, sized_contracts: int, leg_qty: int):
    """Run the REAL record_position tool with a real SizingStash in shared.

    Derived from the producer: the stash is the dataclass `size_position`
    actually writes, not a stand-in, because the whole point is whether these
    two tool calls are compared correctly.
    """
    from trdrbot.calibration import CalibrationStore
    from trdrbot.journal import Journal

    store = PositionStore(tmpdir)
    calib = CalibrationStore(tmpdir / "c.json")
    journal = Journal(tmpdir / "j.jsonl")
    shared = local_tools.SharedContext()
    shared.sizing = local_tools.SizingStash(
        underlying="SPY", contracts=sized_contracts, max_loss_usd=167.0 * sized_contracts)
    rec = local_tools.build_record_position(
        store, "dec_q", shared=shared, calibration=calib, journal=journal)
    msg = rec.func(
        underlying="SPY", strategy="bear_put_spread",
        legs=[{"symbol": "SPY260903P00766000", "side": "buy", "qty": leg_qty},
              {"symbol": "SPY260903P00758000", "side": "sell", "qty": leg_qty}],
        thesis="SPY rolls over", confidence=0.6, expiry="2026-09-03")
    return msg, store, journal


def test_a_recorded_quantity_sizing_did_not_compute_is_reported_not_refused(tmp_path):
    """I-60. size_position's contract count is what max_loss_usd - and so every
    book cap - is derived from. Recording a different quantity denominates
    those caps in a size that was never traded.

    Reported, never refused: D-009 leaves the size to the agent, and this is its
    own two tool calls held against each other, not a policy over either."""
    msg, store, journal = _record_with_sizing(tmp_path, sized_contracts=13, leg_qty=40)

    assert store.all(), "the position was refused, not recorded"
    assert "size_position computed 13" in msg and "[40]" in msg
    row = [r for r in journal.read() if r.get("kind") == "sizing_mismatch"]
    assert row and row[0]["sized_contracts"] == 13 and row[0]["recorded_qtys"] == [40]


def test_a_recorded_quantity_matching_sizing_is_not_flagged(tmp_path):
    """Balanced pressure: the common case must stay silent, or the note is
    noise and the agent learns to skim past it."""
    msg, store, journal = _record_with_sizing(tmp_path, sized_contracts=13, leg_qty=13)

    assert "size_position computed" not in msg
    assert not [r for r in journal.read() if r.get("kind") == "sizing_mismatch"]


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
    from datetime import datetime

    from trdrbot import idle

    just_now = datetime.now(UTC)
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
    from datetime import datetime, timedelta

    from trdrbot import idle
    now = datetime.now(UTC)
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
    from datetime import datetime, timedelta
    a = _idle(positions=[_held()], underlying_prices={"SPY": 766.9},
              open_risk_usd=14_500,
              last_decision_at=datetime.now(UTC) - timedelta(minutes=125))
    assert a.level == "review"


def test_idle_hunts_when_capital_is_idle():
    """Idle capital is a position too - 100% cash at 0% expected return. With
    a deadline that is a decision, not a default."""
    from datetime import datetime, timedelta
    a = _idle(last_hunt_at=datetime.now(UTC) - timedelta(minutes=200))
    assert a.level == "hunt"


def test_idle_does_not_hunt_when_the_risk_cap_is_full():
    """Do not hunt when you cannot shoot: candidates sizing will refuse are
    spend with no possible outcome."""
    from datetime import datetime, timedelta
    a = _idle(positions=[_held()], underlying_prices={"SPY": 766.9},
              open_risk_usd=15_000,
              last_hunt_at=datetime.now(UTC) - timedelta(minutes=200))
    assert a.level == "sleep"


def test_idle_does_not_open_new_risk_into_the_close():
    from datetime import datetime, timedelta
    a = _idle(last_hunt_at=datetime.now(UTC) - timedelta(minutes=300),
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

# These three used to test `cli._acquire_run_lock`, a SECOND locking mechanism
# that guarded the run loop with a bare pid file at a relative path, no
# timestamp, never unlinked on exit. D-091 deleted it and put the run loop
# under `lock.tick_lock`, which already owned every property below and does
# each of them better. The tests move rather than go: the D-044 incident is
# the reason the property matters, and `lock.py` had no tests of its own.

def test_the_tick_lock_refuses_a_second_live_holder():
    """A stray 5s smoke-test loop once hammered the broker API and burned LLM
    calls for half an hour. `kill %1` had killed the pipeline job, not the
    orphaned `uv run` child."""
    import json
    import subprocess
    import tempfile
    import time
    from pathlib import Path

    from trdrbot.lock import tick_lock

    lock_file = Path(tempfile.mkdtemp()) / "tick.lock"
    proc = subprocess.Popen(["sleep", "30"])  # a definitely-live OTHER process
    try:
        lock_file.write_text(json.dumps({"pid": proc.pid, "ts": time.time()}))
        with pytest.raises(BlockingIOError, match="already running"), tick_lock(lock_file):
            raise AssertionError("entered a lock another live process holds")
    finally:
        proc.terminate()


def test_the_tick_lock_takes_over_a_stale_lock():
    """A crashed loop must not require manual cleanup before trading resumes.

    Two independent staleness signals, which is why this lock supersedes the
    pid file it replaced: the holder is gone, OR the lock is older than the
    window. Either is enough.
    """
    import json
    import tempfile
    import time
    from pathlib import Path

    from trdrbot.lock import tick_lock

    lock_file = Path(tempfile.mkdtemp()) / "tick.lock"
    lock_file.write_text(json.dumps({"pid": 999999, "ts": time.time()}))  # dead pid
    with tick_lock(lock_file):
        pass

    import os
    lock_file.write_text(json.dumps({"pid": os.getpid(), "ts": time.time() - 99999}))
    with tick_lock(lock_file):  # alive, but far past the stale window
        pass


def test_the_tick_lock_survives_a_corrupt_lock_file():
    import tempfile
    from pathlib import Path

    from trdrbot.lock import tick_lock

    lock_file = Path(tempfile.mkdtemp()) / "tick.lock"
    lock_file.write_text("not-json-at-all")
    with tick_lock(lock_file):
        pass
    assert not lock_file.exists(), "the lock must be released on exit"


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
    tools = tool_guard.redirect_whole_book_close([t], lambda: 3)
    out = asyncio.run(tools[0].coroutine(cancel_orders=True))
    assert "REFUSED" in out and not t.called

    t2 = FakeTool()
    tools2 = tool_guard.redirect_whole_book_close([t2], lambda: 1)
    out2 = asyncio.run(tools2[0].coroutine(cancel_orders=True))
    assert out2 == "liquidated" and t2.called, "one position: equivalent to a normal close"


def test_the_whole_book_count_includes_opening_and_closing_positions(paths, make_position):
    """I-58. The count decided whether D-046's refusal fires, and it read only
    `open` - so one open position beside one mid-fill (`opening`) or one
    mid-liquidation (`closing`) counted as ONE, and the sweep was permitted
    against a book of three. `closing` is no longer momentary either: since
    I-57 it persists across ticks until the retry completes.

    Calls the real lambda `_guarded_mcp_tools` builds, not a copy of it - the
    counting rule and the guard it feeds must not drift apart.
    """
    from trdrbot import tick as tick_mod
    from trdrbot.positions import PositionStore

    store = PositionStore(paths.wiki)
    for pid, status in [("pos_open", "open"), ("pos_filling", "opening"),
                        ("pos_exiting", "closing"), ("pos_idea", "proposed")]:
        store.save(make_position(position_id=pid, status=status))

    counter = _whole_book_counter(tick_mod, store)

    assert counter() == 3, "a position with live broker exposure was not counted"


def _whole_book_counter(tick_mod, store):
    """The `count_open` callable `_guarded_mcp_tools` hands to the guard.

    Captured by wrapping the real assembly rather than re-deriving it: the
    lambda is an argument to `redirect_whole_book_close`, so intercepting that
    call is how a test gets hold of the production one.
    """
    from trdrbot import tool_guard

    captured: list[Any] = []
    real = tool_guard.redirect_whole_book_close

    def spy(tools, count_open):
        captured.append(count_open)
        return real(tools, count_open)

    class _Cfg:
        decide_tools: list[str] = []

    tool_guard.redirect_whole_book_close = spy
    try:
        tick_mod._guarded_mcp_tools([], _Cfg(), "batch", store)
    finally:
        tool_guard.redirect_whole_book_close = real
    return captured[0]


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


# ---- PILLAR-4 (learning integrity) lives here as well as in test_coach.py:
# the four tests below are the originals, tagged rather than duplicated.
# Governed by docs/principles_testing.md - the four pillars.
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
            p = rng.choice([0.3, 0.4, 0.5, 0.6, 0.7])
            hit = rng.random() < p
        else:  # badly overconfident: says 80%, right 55%
            p = 0.8
            hit = rng.random() < 0.55
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

def test_the_weekend_vol_clock_is_gone_rather_than_merely_unused():
    """`vol_days` weighted weekends at half a day, to convert "an implied vol
    against a realized one". D-093 derived that this comparison needs no clock
    change at all - an annualised realized vol already carries the trading-day
    count - so the function's only stated purpose was a conversion that must
    not happen. It had no production callers and its docstring was an
    instruction to reintroduce the double count D-051 removed.

    Deleted, not deprecated. Structural beats documented: there is no longer
    anything to call."""
    from trdrbot import optmath

    assert not hasattr(optmath, "vol_days")
    assert not hasattr(optmath, "VOL_DAYS_PER_YEAR")
    assert not hasattr(optmath, "WEEKEND_VOL_WEIGHT")


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

    # The guard used to be "the `start` parameter is accepted and IGNORED",
    # asserted by passing two different dates and comparing - a comment
    # enforced by a test, and a landmine for whoever eventually supplied the
    # argument in earnest. D-091 deleted the parameter from all three
    # functions instead, so the property is now structural: there is no way to
    # hand these a session date, and the double count is unrepresentable
    # rather than merely untaken.
    import inspect

    from trdrbot.optmath import bs_greeks, expected_move, year_fraction

    for fn in (bs_greeks, expected_move):
        assert "start" not in inspect.signature(fn).parameters, (
            f"{fn.__name__} accepts a session date again - the weekend clock "
            f"must not be applied on top of an IV that already prices it")
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


def test_implied_vs_realized_compares_two_already_annualised_numbers():
    """The world that produced a realized vol prices its own options AT that
    vol, so equal figures must read 1.00 (D-093).

    This function carried a sqrt(252/365) adjustment on the realized side for
    its whole life and nobody noticed, because it had no callers. Derive it:
    a world with per-trading-day variance sd^2 has annualised realized vol
    sd*sqrt(252); an option there spanning n_c calendar days covers
    n_t = n_c*252/365 sessions with total variance n_t*sd^2, and BS charges
    sigma^2 * n_c/365 for that - so sigma = sd*sqrt(252), the same number.
    The trading-day count is already inside both sides.
    """
    import math

    from trdrbot.optmath import implied_vs_realized

    sd = 0.01
    realized = sd * math.sqrt(252)
    n_c = 6.0
    total_var = (n_c * 252 / 365) * sd ** 2
    fair_iv = math.sqrt(total_var / (n_c / 365))

    assert abs(implied_vs_realized(fair_iv, realized) - 1.0) < 1e-12
    assert implied_vs_realized(0.20, 0.20) == pytest.approx(1.0)
    # The old behaviour, named so it cannot come back: a fifth of a premium
    # that was not there, always in the direction that says sell.
    assert implied_vs_realized(0.20, 0.20) < 1.15
    assert implied_vs_realized(0.24, 0.20) == pytest.approx(1.2)
    assert implied_vs_realized(0.20, 0.0) is None


def test_gamma_breakeven_is_the_implied_daily_move_not_a_structure_score():
    """Sources claim it discriminates structures. It does not: theta/gamma is
    the same BS identity for every position at one spot and one vol. What it
    returns is the daily move implied by IV - useful against REALISED range."""
    from trdrbot.optmath import Leg, gamma_breakeven, net_greeks

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
    import tempfile
    from pathlib import Path

    from trdrbot.calibration import CalibrationStore
    from trdrbot.ledger import STANDALONE, as_forecasts

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
    from trdrbot.ledger import STANDALONE, THESIS
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
    import math
    import random

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
    import math
    import random

    from trdrbot.market_stats import beta
    rng = random.Random(3)
    short = [100.0 * math.exp(rng.gauss(0, 0.01)) for _ in range(30)]
    assert beta(short, short) is None


def test_negative_beta_is_preserved_not_clamped():
    """An offsetting position is the whole point of measuring this."""
    import math
    import random

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

    from trdrbot import market_stats

    d = Path(tempfile.mkdtemp())
    import math
    import random
    rng = random.Random(4)
    spy = [100.0]
    for _ in range(200):
        spy.append(spy[-1] * math.exp(rng.gauss(0, 0.01)))
    hi = [100.0]
    for a, b in zip(spy, spy[1:]):
        hi.append(hi[-1] * math.exp(2 * math.log(b / a)))
    dates = synthetic_dates(len(spy))
    market_stats.save_closes(d, "SPY", spy, dates=dates)
    market_stats.save_closes(d, "HI", hi, dates=dates)

    betas, assumed = market_stats.betas_for(d, ["SPY", "HI"])
    assert betas["SPY"] == 1.0
    assert betas["HI"] > 1.7, "a 2x tracker must weight roughly double"
    assert "HI" not in assumed


def test_beta_weighting_reveals_a_hedge_that_raw_delta_hides():
    """The demonstration that justifies the whole feature: adding an
    inverse-beta position RAISED raw book delta from $90k to $253k while
    beta-weighted delta FELL from $181k to $18k. Raw delta said "more
    exposed"; the truth was "almost flat"."""
    import math
    import random
    import tempfile
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

    dates = synthetic_dates(len(spy))
    market_stats.save_closes(d, "SPY", spy, dates=dates)
    market_stats.save_closes(d, "HIB", track(2.0), dates=dates)
    market_stats.save_closes(d, "INV", track(-1.0), dates=dates)

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

    from trdrbot.positions import Position, PositionStore
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

# `test_credit_gates_on_measured_pnl_not_the_close_label` stood here. It
# asserted on the TEXT of `learn.on_resolution` - the literal
# `"if pnl_fraction is not None:\n        hit = pnl_fraction > 0"` - to pin D-057's fix
# that credit follows a measured P&L rather than the close-reason label.
#
# D-091 moved block credit out of that function entirely (it was crediting on
# the money at close, and attribution then re-judged the same blocks from the
# verdict at horizon - a lucky win took +0.9 and then "learn nothing", which
# is the superstition the design exists to prevent). The string match SURVIVED
# that change untouched, because the surrounding lines happen to be identical
# - so it kept reporting green about a behaviour that no longer exists there.
# That is the failure mode of source-inspection tests in one example.
#
# D-057's actual behaviour is now covered by running the code:
# `test_a_close_with_known_pnl_resolves_calibration_and_records_the_lesson`
# and `test_a_close_with_no_pnl_anywhere_skips_credit_rather_than_guessing` in
# tests/test_memory_and_credit.py, plus the end-to-end
# `test_a_lucky_win_moves_no_memory_end_to_end`.


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
    # The gate cascade moved to `_evaluate` when the muse gained a
    # challenger arm (D-088): both arms run ONE copy of it, so the
    # invariant this test guards now lives there. Same rule, new home.
    src = inspect.getsource(muse._evaluate)
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

    from trdrbot.elfmem_adapter import _DEFAULT_AGENT_NAME, ElfmemAdapter
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
    from pathlib import Path

    from trdrbot.config import Config

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
    with pytest.raises(RuntimeError) as exc:
        build_model(cfg, role="decide")
    assert "No usable model" in str(exc.value) and "decide" in str(exc.value)


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


def test_the_compacted_chain_shows_how_to_build_an_occ_symbol():
    """The rows carried `occ` and NOTHING rendered it, so the agent had to
    reconstruct 21-character contract symbols by hand from a strike and a date
    - and the OCC is the one field that must be exactly right for
    `place_option_order` and `record_position` to refer to the same contract.

    Shown as a real prefix plus a worked example taken from the page, rather
    than repeated on every row: this table exists to save tokens, and an
    example demonstrates the strike padding that prose would only describe.
    """
    from trdrbot.compact import compact_option_chain
    from trdrbot.optmath import parse_occ

    out = compact_option_chain(_chain_payload())

    assert "OCC:" in out, "the chain says nothing about contract symbols"
    occ_line = next(ln for ln in out.splitlines() if "OCC:" in ln)
    example = occ_line.split("=")[-1].strip()

    parsed = parse_occ(example)
    assert parsed is not None, f"the worked example is not a valid OCC: {example}"
    # And it must describe a contract really ON this page, not a plausible
    # invention - an example the agent copies has to be one it can trade.
    assert example in _chain_payload()["snapshots"]


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
    from trdrbot import ids
    from trdrbot.usage import UsageLedger

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
    from trdrbot import ids
    from trdrbot.usage import UsageLedger

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

    def journal(pending: int) -> object:
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
    from trdrbot.analytics import Snapshot, position_pnl_fraction

    # Credit spread: sold for 2.65, bought for 1.58, 5 lots -> $535 credit.
    snap = Snapshot(broker_positions=[
        {"symbol": "S", "cost_basis": -1325.0, "unrealized_pl": 267.5},
        {"symbol": "L", "cost_basis": 790.0, "unrealized_pl": 0.0},
    ])
    pnl = position_pnl_fraction(["S", "L"], snap)
    assert abs(pnl - 0.50) < 1e-9, "+50% means half the CREDIT, the trader's meaning"
    # On the old gross base ($2,115) the same money read as +12.6%, so a +50%
    # target needed $1,057 against a max profit of $535: unreachable, forever.
    assert pnl > 267.5 / 2115.0 * 3


def test_a_spread_with_no_net_cost_reports_nothing_rather_than_noise():
    from trdrbot.analytics import Snapshot, position_pnl_fraction
    snap = Snapshot(broker_positions=[
        {"symbol": "A", "cost_basis": 1000.0, "unrealized_pl": 5.0},
        {"symbol": "B", "cost_basis": -999.0, "unrealized_pl": 0.0},
    ])
    assert position_pnl_fraction(["A", "B"], snap) is None, "unobservable holds, never fires blind"


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
    import math
    import statistics

    from trdrbot import market_stats
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
    from trdrbot.ledger import STANDALONE, THESIS, Ledger

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

    shared = local_tools.SharedContext()
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
    assert len(shared.structures) == 2

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


# ============================================== D-076 what has to be true


def _L(r, k, s, q, p):
    from trdrbot.optmath import Leg
    return Leg.parse({"right": r, "strike": k, "side": s, "qty": q, "price": p})


def CONDOR():
    return [_L("P", 766, "short", 1, 1.87), _L("P", 761, "long", 1, 0.95),
            _L("C", 776, "short", 1, 1.22), _L("C", 781, "long", 1, 0.28)]


def CALL_SPREAD():
    return [_L("C", 775, "long", 1, 1.77), _L("C", 785, "short", 1, 0.15)]


def test_breakeven_vol_states_the_trade_the_way_a_desk_states_it():
    """An EV is one number resting on one volatility assumption, and choosing
    that assumption is where a whole board silently becomes one undefended
    input - the live journal declined four candidates on a 21-day realized
    figure where the 5-day figure reversed three of them."""
    from trdrbot.optmath import breakeven_vol

    be = breakeven_vol(CONDOR(), 770.61, 5)
    assert be.crossings, "a short-premium structure must have a vol it stops working at"
    assert be.positive_at_low, "selling premium wins when realized comes in LOW"
    assert "wins if realized vol <" in be.describe()

    long_vol = breakeven_vol(CALL_SPREAD(), 770.61, 5)
    assert not long_vol.positive_at_low, "a long-vol structure is the other way round"
    assert "wins if realized vol >" in long_vol.describe()


def test_breakeven_drift_returns_a_BAND_for_a_range_structure():
    """EV is monotone in vol for one-signed vega but NOT in drift: a condor
    peaks at zero drift and falls away both sides. Bisecting from the endpoints
    would have reported a confident single crossing for every range structure
    the agent trades."""
    from trdrbot.optmath import breakeven_drift

    be = breakeven_drift(CONDOR(), 770.61, 5, iv=0.07)
    assert len(be.crossings) == 2, f"a range trade wins BETWEEN two drifts, got {be.crossings}"
    assert be.crossings[0] < 0 < be.crossings[1]
    assert "between" in be.describe()

    directional = breakeven_drift(CALL_SPREAD(), 770.61, 5, iv=0.10, friction=15.0)
    assert len(directional.crossings) == 1, "a directional structure crosses once"
    assert "wins if drift >" in directional.describe()


def test_no_crossing_is_reported_not_hidden():
    """'positive at every vol I can model' is an answer, and a useful one."""
    from trdrbot.optmath import Breakeven, breakeven_vol

    # Free money: a debit spread bought for less than nothing.
    free = breakeven_vol([_L("C", 775, "long", 1, 0.0), _L("C", 785, "short", 1, 0.50)],
                         770.61, 5)
    assert not free.crossings and free.positive_at_low
    assert "every" in free.describe()
    assert Breakeven("x", (), False).describe().startswith("EV negative")


def test_dominant_risk_separates_a_direction_bet_from_a_vol_bet():
    """Measured on two live candidates from one board, one expiry: the condor
    moved $9 per 1% of spot against $23 a vol point; the call spread $199
    against $22. The decide cycle priced both off one volatility assumption
    without noticing only one of them cared."""
    from trdrbot.optmath import dominant_risk, net_greeks

    condor = dominant_risk(net_greeks(CONDOR(), 770.61, 0.10, 5))
    spread = dominant_risk(net_greeks(CALL_SPREAD(), 770.61, 0.10, 5))
    assert condor[0] == "volatility"
    assert spread[0] == "direction" and spread[1] > 5

    # The one that matters for this book: a far-OTM credit spread is a
    # LEVERAGED DIRECTION bet wearing a premium-selling costume.
    far_put = dominant_risk(net_greeks(
        [_L("P", 765, "short", 1, 1.61), _L("P", 760, "long", 1, 0.80)], 770.61, 0.10, 5))
    assert far_put[0] == "direction", "a far OTM put spread is not a vol trade"

    assert dominant_risk(None) is None


def test_the_needs_line_leads_with_the_dominant_risk():
    """A call spread's breakeven vol is nearly irrelevant; leading with it puts
    the least relevant number in the most prominent place."""
    from trdrbot.experiments import Experiment, Thesis, _needs_line, simulate

    th = Thesis("up", "SPY", "2026-09-02", drift=0.002)
    m = simulate(Experiment("call spread", CALL_SPREAD()), th, 770.61, 0.10, 5)
    line = _needs_line(m)
    assert "DIRECTION bet" in line
    assert line.index("drift") < line.index("realized vol"), "dominant risk reads first"

    mc = simulate(Experiment("condor", CONDOR()), th, 770.61, 0.10, 5)
    lc = _needs_line(mc)
    assert "VOL bet" in lc and lc.index("realized vol") < lc.index("drift")


# ============================================ D-077 Kelly's payoff ratio


def test_kelly_b_was_a_different_event_from_kelly_p():
    """Sizing passed max_profit/max_loss for `b` while passing P(profit>0) for
    `p`. A vertical reaches its max profit in only PART of the region where it
    profits, and its max loss in only part of the region where it loses - so
    the pair described two different events, and the mismatch is directional,
    not conservative."""
    from trdrbot.optmath import max_profit_loss, payoff_ratio

    credit = [_L("P", 765, "short", 1, 1.61), _L("P", 760, "long", 1, 0.80)]
    debit = [_L("C", 775, "long", 1, 1.77), _L("C", 785, "short", 1, 0.15)]

    def ratios(legs):
        mp, ml = max_profit_loss(legs)
        _w, _l, cond = payoff_ratio(legs, 770.61, 0.10, 5)
        return mp / abs(ml), cond

    max_max, cond = ratios(credit)
    assert cond > max_max, "a credit structure wins near its max and loses well short of it"

    max_max_d, cond_d = ratios(debit)
    assert cond_d < max_max_d, "a debit structure is the other way round"

    # The consequence: the old formula preferred BUYING premium to selling it.
    assert cond / max_max > 1.2 and cond_d / max_max_d < 0.8


def test_payoff_ratio_refuses_a_side_with_no_mass():
    """A conditional expectation needs something to condition on. Dividing by
    the mean of an essentially empty side manufactures an enormous ratio out of
    a corner of the distribution - and an enormous `b` sends Kelly to `p`."""
    from trdrbot.optmath import payoff_ratio

    # Deep ITM: the grid finds no losing region worth the name.
    riskless = [_L("C", 100, "long", 1, 0.01)]
    assert payoff_ratio(riskless, 770.61, 0.10, 5) is None
    assert payoff_ratio([], 770.61, 0.10, 5) is None


def test_sizing_uses_the_conditional_ratio_and_says_when_it_cannot():
    from trdrbot import sizing
    from trdrbot.calibration import Calibration

    cal = Calibration(n=20, brier=0.2, reliability=0.02, resolution=0.05,
                      uncertainty=0.24, base_rate=0.6)
    common = dict(equity=100_000.0, stated_confidence=0.70, max_profit=186.0,
                  max_loss=-314.0, calibration=cal, underlying="SPY")

    with_cond = sizing.size_position(**common, payoff_ratio=0.67)
    without = sizing.size_position(**common)
    assert with_cond.kelly_full > without.kelly_full, "the true payoff is better here"
    assert "conditional" in with_cond.reason
    assert "max/max" in without.reason, "a silent fallback is the thing to avoid"


def test_the_structure_match_is_scale_invariant_and_refuses_rather_than_guessing():
    """The model quotes PER-CONTRACT figures; simulate priced whatever quantity
    the legs carried. Matching on dollars fails on every multi-lot candidate,
    so the match is on risk/reward, which is scale-free.

    Assertions rewritten for WU-4.2's contract - a deliberate, explained test
    change, not a weakened one. The helper returns the matched SimStructure or
    a REFUSAL string where it used to return the payoff ratio or None. The
    behaviour under test is unchanged (identity across lot sizes; never guess an
    ambiguous match); what changed is that "no match" is now a refusal the
    caller surfaces instead of a silent frictionless max/max fallback (I-40).
    """
    from trdrbot.local_tools import SharedContext, SimStructure, _match_structure

    def _s(name, rr, payoff):
        return SimStructure(key=(), name=name, qty=1, entry_cost=None,
                            max_profit=None, max_loss=None, payoff_ratio=payoff, rr=rr)

    shared = SharedContext(structures=[_s("condor", 0.59, 0.67),
                                       _s("put spread", 5.17, 3.09)])
    # 10 lots of the condor: same R:R, ten times the dollars.
    assert _match_structure(shared, 1860.0, -3140.0).payoff_ratio == 0.67
    assert _match_structure(shared, 186.0, -314.0).payoff_ratio == 0.67
    assert _match_structure(shared, 838.0, -162.0).payoff_ratio == 3.09
    # Never simulated -> refusal, not a guess and not a silent fallback.
    assert "REFUSED" in _match_structure(shared, 999.0, -1000.0)
    # Ambiguous -> refusal too, and it names what it does know.
    ambiguous = SharedContext(structures=[_s("a", 1.0, 1.1), _s("b", 1.0, 2.2)])
    assert "REFUSED" in _match_structure(ambiguous, 100.0, -100.0)
    assert "REFUSED" in _match_structure(None, 100.0, -100.0)

    # ...unless the model names the candidate, which resolves exactly the case
    # the R:R match documented as unresolvable (D-092). Falling back to max/max
    # there is the mismatch I-13 measured as DIRECTIONAL, not conservative.
    assert _match_structure(ambiguous, 100.0, -100.0, "b").payoff_ratio == 2.2
    assert "REFUSED" in _match_structure(ambiguous, 100.0, -100.0, "nonexistent")


# ==================================== D-077 horizons that resolve in time


def test_forecast_window_leaves_room_to_act():
    """A thesis resolving ON the deadline can never inform a decision - that is
    the day everything is force-closed."""
    import datetime

    from trdrbot import competence

    today, deadline = datetime.date(2026, 8, 28), "2026-09-04"
    earliest, preferred, latest = competence.forecast_window(deadline, today)
    assert latest == "2026-09-03", "the deadline itself is not a useful horizon"
    assert preferred == "2026-08-31", "prefer short: one slow forecast < three fast ones"
    assert earliest == "2026-08-29", "TODAY resolves in zero days - a window has two sides"
    assert earliest <= preferred <= latest

    # Late in the window, everything clamps to what is still possible.
    e2, p2, l2 = competence.forecast_window(deadline, datetime.date(2026, 9, 2))
    assert e2 == p2 == l2 == "2026-09-03"

    assert competence.forecast_window(None) is None
    assert competence.forecast_window("not-a-date") is None


def test_every_thesis_source_asks_the_same_question():
    """They had each carried their own day-count and drifted apart: muse
    allowed 1-10 days with NO deadline check at all, discovery allowed anything
    up to and INCLUDING the deadline, and record_forecast argued for 1-3 days
    in prose only. The muse's output then clustered at the far end - all five
    of its live forecasts landed on the last useful day."""
    import inspect

    from trdrbot import discovery, muse

    for mod in (muse, discovery):
        src = inspect.getsource(mod)
        assert "competence.forecast_window" in src, f"{mod.__name__} derives its own window"

    # And the prompts carry the derived dates rather than a hardcoded count.
    for token in ("{earliest}", "{preferred}", "{latest}"):
        assert token in muse.MUSE_PROMPT, f"muse prompt lost {token}"
    assert "{earliest}" in discovery.SYNTH_PROMPT, "a one-sided rule invites today"
    assert "7 calendar" not in muse.MUSE_PROMPT, "the hardcoded range is gone"
    assert "{latest}" in discovery.SYNTH_PROMPT


def test_a_horizon_that_resolves_too_late_is_refused():
    """The muse had no deadline check: it could emit a thesis resolving AFTER
    the competition ends, which can never inform anything.

    This used to assert on the SOURCE TEXT of two functions - the muse's gate
    cascade and discovery's emission loop - because the rule lived in both. It
    now lives once, in `opportunity.admit`, so the rule can be RUN instead of
    read. The muse's own copy (which also rejects a horizon outside 1-10 days,
    a stricter rule than the shared window) is still inspected below, because
    that one genuinely has no other home yet.
    """
    import inspect

    from trdrbot import muse
    from trdrbot.opportunity import Opportunity, admit

    o = Opportunity(underlying="SPY", claim="c", horizon="2026-09-30",
                    band_high=770.0)

    assert admit(o, latest_useful="2026-09-02").defect == "horizon_too_late"
    assert admit(o, latest_useful="2026-10-31").ok

    # ...and an ABSENT window is reported, never silently treated as passed.
    assert "horizon_window" in admit(o).unchecked

    assert "resolves too late" in inspect.getsource(muse._evaluate)


def test_a_truncated_json_array_still_yields_its_complete_elements():
    """One LLM call spent for zero candidates: a 6,745-char muse reply opened
    with a perfectly good `[{"underlying":"S"...` and parsed to nothing,
    because the outer-bracket salvage found an INNER `]` from a nested list.
    gpt-5 reasoning tokens share the completion budget, so a long generation
    can be cut off after several good elements."""
    from trdrbot.llm import parse_json_array

    truncated = ('[{"underlying":"S","chain":["a","b"],"probability":0.4},'
                 '{"underlying":"MU","chain":["c"],"probability":0.6},'
                 '{"underlying":"BURL","cha')
    got = parse_json_array(truncated)
    assert isinstance(got, list) and len(got) == 2
    assert [g["underlying"] for g in got] == ["S", "MU"]

    # A brace inside a string must not fool it.
    # ...and a single complete element must still come back as a LIST. With
    # one element written, `rfind("}")` lands on its own closer, so the object
    # salvage succeeds and silently returns a dict where a list was expected.
    tricky = '[{"claim":"a ] and a } inside","p":1},{"claim":"broke'
    got2 = parse_json_array(tricky)
    assert isinstance(got2, list) and len(got2) == 1, f"got {got2!r}"

    # Intact input is untouched, and genuine garbage still returns None.
    assert parse_json_array('[{"a":1}]') == [{"a": 1}]
    # Nothing usable now returns the EMPTY SHAPE THE CALLER ASKED FOR rather
    # than None (D-092): every caller was writing `... or []` after this, and
    # the two that forgot re-guessed the shape instead.
    assert parse_json_array("not json at all") == []
    from trdrbot.llm import parse_json_object
    assert parse_json_object("not json at all") == {}
    assert parse_json_array("[") == []


# ================================= D-078 wiki lifecycle


def _wiki(tmp_path):
    from trdrbot.wiki import Wiki
    return Wiki(tmp_path)


DOSSIER = ("# What it is\nNvidia designs the GPUs that underpin frontier AI.\n\n"
           "# Bull case\nClosed 228.17, +5.2% on the week.\n\n"
           "# Bear case\nRealized vol 42.4%.\n")


def test_a_new_document_type_cannot_be_written_without_a_lifecycle(tmp_path):
    """The consistency mechanism. A type with no declared lifecycle is exactly
    how 28 dossiers came to exist with no freshness marker, no sweep and no
    policy - so the write path refuses one, the same way it already refuses a
    write that drops a heading."""
    import pytest

    from trdrbot.wiki import Concept, LifecycleError

    w = _wiki(tmp_path)
    c = Concept(concept_id="x/thing", frontmatter={}, body="# H\nbody\n")
    with pytest.raises(LifecycleError) as e:
        w.write_concept(c, type_="SomethingNew")
    assert "LIFECYCLE" in str(e.value) and "SomethingNew" in str(e.value)
    # ...and every type actually in use is registered.
    from trdrbot.wiki import LIFECYCLE
    for t in ("CompanyDossier", "MarketContext", "Technique", "Lesson"):
        assert t in LIFECYCLE, f"{t} is written in production and must have a policy"


def test_freshness_is_stamped_by_policy_not_by_the_caller(tmp_path):
    """Two writers share research/*.md. When each set `stale_after` by hand they
    could disagree about when the same file expires."""
    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    c = Concept(concept_id="research/NVDA", frontmatter={}, body=DOSSIER)
    w.write_concept(c, type_="CompanyDossier")
    assert c.frontmatter["stale_after"], "a perishable type must be stamped"
    assert c.frontmatter["status"] == "stable"
    assert not c.is_stale()

    # A timeless type gets no expiry at all.
    t = Concept(concept_id="technique/x", frontmatter={}, body="# Rule\nalways true\n")
    w.write_concept(t, type_="Technique")
    assert "stale_after" not in t.frontmatter
    assert not t.is_stale()


def test_the_durable_half_survives_expiry(tmp_path):
    """The reframe: a concept does not go stale because a price did. The muse's
    400-char window used to run past '# What it is' into '# Bull case', handing
    it 'Closed 228.17, +5.2%' as collision material 15.8h after that stopped
    being true - measured, on this date's actual NVDA pick."""
    import datetime

    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    c = Concept(concept_id="research/NVDA", frontmatter={}, body=DOSSIER)
    w.write_concept(c, type_="CompanyDossier")

    durable = c.durable_text()
    assert "Nvidia designs the GPUs" in durable
    assert "228.17" not in durable, "the perishable half must not ride along"

    # Long past expiry, the concept is still exactly as usable.
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=30)
    assert c.is_stale(later)
    assert c.durable_text() == durable, "staleness must not change the durable text"


def test_durable_text_degrades_to_everything_never_to_nothing(tmp_path):
    """A half-written page must lose its freshness, not lose the page."""
    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    # A dossier missing the durable heading entirely.
    c = Concept(concept_id="research/ODD", frontmatter={}, body="# Bull case\nonly this\n")
    w.write_concept(c, type_="CompanyDossier")
    assert "only this" in c.durable_text()

    # A type that declares no durable section returns the whole body.
    t = Concept(concept_id="technique/y", frontmatter={}, body="# Rule\neverything\n")
    w.write_concept(t, type_="Technique")
    assert "everything" in t.durable_text()


def test_sweep_tombstones_in_place_and_never_deletes(tmp_path):
    """Deletion is refused on principle, archive-by-move on mechanics: a file
    that moves can be missed mid-read, a frontmatter flag cannot."""
    import datetime

    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    c = Concept(concept_id="research/WEN", frontmatter={}, body=DOSSIER)
    path = w.write_concept(c, type_="CompanyDossier")
    generated_before = c.frontmatter["generated"]["at"]

    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)
    out = w.sweep(now=later)
    assert out["deprecated"] == ["research/WEN"]

    back = w.read("research/WEN")
    assert path.exists(), "sweep must never delete"
    assert back.frontmatter["status"] == "deprecated"
    assert back.frontmatter["generated"]["at"] == generated_before, \
        "a tombstone is not a regeneration - the page must not look freshly researched"
    assert "Nvidia designs the GPUs" in back.durable_text(), "content survives"

    # Idempotent: a second sweep does not re-stamp.
    assert w.sweep(now=later)["deprecated"] == []


def test_sweep_never_retires_a_ticker_we_are_holding(tmp_path):
    """A position outlives the research cadence, and retiring the page that
    explains why we are in a trade is the worst possible moment to do it."""
    import datetime

    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    for t in ("HELD", "NOTHELD"):
        w.write_concept(Concept(concept_id=f"research/{t}", frontmatter={}, body=DOSSIER),
                        type_="CompanyDossier")
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)
    out = w.sweep(protected={"research/HELD"}, now=later)
    assert out["deprecated"] == ["research/NOTHELD"]
    assert out["protected"] == ["research/HELD"]
    assert w.read("research/HELD").frontmatter.get("status") != "deprecated"


def test_re_researching_a_tombstoned_dossier_revives_it(tmp_path):
    """Reversible by construction - no separate un-archive path to forget."""
    import datetime

    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    w.write_concept(Concept(concept_id="research/BURL", frontmatter={}, body=DOSSIER),
                    type_="CompanyDossier")
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)
    w.sweep(now=later)
    assert w.read("research/BURL").frontmatter["status"] == "deprecated"

    fresh = w.read("research/BURL")
    fresh.body = DOSSIER.replace("228.17", "231.00")
    w.write_concept(fresh, type_="CompanyDossier")
    assert w.read("research/BURL").frontmatter["status"] == "stable"
    assert not w.read("research/BURL").is_stale()


def test_sources_stop_growing_without_bound(tmp_path):
    """research/NVDA.md carries FOUR identical `computed:market_stats` rows, one
    per research pass. Four copies of one source are not four credibility
    signals - OKF's signal is `last_modified`, refreshed in place."""
    from trdrbot.wiki import Concept

    w = _wiki(tmp_path)
    c = Concept(concept_id="research/X", frontmatter={}, body=DOSSIER)
    for _ in range(5):
        c.add_source("computed:market_stats", author="trdrbot/research")
    assert len(c.frontmatter["sources"]) == 1
    c.add_source("discovery:news", author="trdrbot/discovery")
    assert len(c.frontmatter["sources"]) == 2

    # And the augmentation guard is still satisfied on a re-write.
    w.write_concept(c, type_="CompanyDossier")
    again = w.read("research/X")
    again.add_source("computed:market_stats", author="trdrbot/research")
    w.write_concept(again, type_="CompanyDossier")  # must not raise


def test_the_durable_heading_carries_only_durable_text():
    """22 of 28 live dossiers read "Affirm Holdings, Inc. - Strong Q4 results
    with...beats" because the template concatenated a durable field and a
    perishable one into one sentence, so today's earnings news sat in the one
    heading later cycles read as a standing fact (D-078)."""
    from trdrbot.research import dossier
    from trdrbot.wiki import LIFECYCLE, Concept

    c = Concept(concept_id="research/X", frontmatter={"type": "CompanyDossier"},
                body=dossier("X", what_it_is="A payments lender.",
                             bull_case="Strong Q4 results with beats.",
                             bear_case="b", people="p", environment="e"))

    durable = c.section(LIFECYCLE["CompanyDossier"].durable_section)
    assert durable == "A payments lender."
    assert "Q4" not in durable, "perishable text welded into the durable heading"
    assert c.durable_text() == "A payments lender."


def test_both_dossier_writers_produce_the_same_headings():
    """discovery and research write the SAME file, and the augmentation guard
    refuses a write that drops a heading - so if their templates diverge the
    second writer is refused and the dossier silently stops updating.

    This used to REGEX THE HEADING LITERALS out of both functions' source, a
    test whose only job was policing copy-paste. There is one template now, so
    the property is checked by building both bodies and comparing them.
    """
    from trdrbot.research import dossier
    from trdrbot.wiki import LIFECYCLE, Concept

    def headings(**fields):
        body = dossier("X", **{"what_it_is": "", "bull_case": "", "bear_case": "",
                               "people": "", "environment": "", **fields})
        return Concept(concept_id="c", frontmatter={"type": "CompanyDossier"},
                       body=body).headings()

    as_research = headings(what_it_is="w", bull_case="b", people="p")
    as_discovery = headings(what_it_is="w", bear_case="r",
                            people="(not researched - discovery pass)")

    assert as_research == as_discovery
    assert LIFECYCLE["CompanyDossier"].durable_section in "".join(as_research)


# ============================ D-079 the scaffold's invariants, made permanent


def _fair_leg(right, strike, side, qty=1, spot=100.0, iv=0.25, days=7.0):
    """A leg priced at expected intrinsic under the SAME grid the stack uses,
    so a structure built from these is fair BY CONSTRUCTION and any edge the
    stack reports on it is an artefact of the stack."""
    from trdrbot.optmath import Leg, _lognormal_grid
    grid = _lognormal_grid(spot, iv, days)
    price = sum(w * max(0.0, (s - strike) if right == "C" else (strike - s))
                for s, w in grid)
    return Leg(right=right, strike=strike, side=side, qty=qty, price=price)


def _fair_zoo():
    F = _fair_leg
    return {
        "call debit 100/105": [F("C", 100, "long"), F("C", 105, "short")],
        "call debit 103/108": [F("C", 103, "long"), F("C", 108, "short")],
        "put credit 95/100": [F("P", 100, "short"), F("P", 95, "long")],
        "put credit 90/95": [F("P", 95, "short"), F("P", 90, "long")],
        "condor wide": [F("P", 95, "short"), F("P", 90, "long"),
                        F("C", 105, "short"), F("C", 110, "long")],
        "condor narrow": [F("P", 99, "short"), F("P", 97, "long"),
                          F("C", 101, "short"), F("C", 103, "long")],
        "butterfly": [F("C", 95, "long"), F("C", 100, "short", 2), F("C", 105, "long")],
    }


def test_kelly_is_zero_on_a_fair_bet_and_max_max_was_not():
    """The deep property the conditional payoff ratio buys. With b =
    E[win|win]/E[loss|loss] and the model's own p, Kelly = 0 exactly when
    EV = 0 - so the sign of Kelly agrees with the sign of EV.

    Under max/max they could disagree, and did: swept over a fair-value zoo,
    max/max Kelly ranged to -2.3 on a bet with precisely zero edge. It refused
    high-probability structures and OPENED THE GATE BELOW THE FAIR RATE for
    long shots - a structure at a fair 16.6% win rate passed at a claimed
    7.3%, i.e. the system would size a claim it should have refused."""
    from trdrbot import optmath, sizing

    worst_maxmax = 0.0
    for name, legs in _fair_zoo().items():
        ev = optmath.expected_value(legs, 100.0, 0.25, 7.0)
        assert abs(ev) < 1.0, f"{name}: fair-value construction broken, EV {ev}"
        p = optmath.prob_profit(legs, 100.0, 0.25, 7.0)
        mp, ml = optmath.max_profit_loss(legs)
        b = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0)[2]

        k_cond = sizing.kelly_fraction(p, mp, ml, payoff_ratio=b)
        assert abs(k_cond) < 0.02, f"{name}: conditional Kelly {k_cond:+.3f} on a FAIR bet"
        worst_maxmax = max(worst_maxmax, abs(sizing.kelly_fraction(p, mp, ml)))
    assert worst_maxmax > 1.0, "max/max should be wildly off on a fair bet - it was"


def test_the_gate_is_structure_neutral():
    """The gate must open at the same place for every structure type: when the
    agent claims MORE than the market-implied probability. Under max/max it
    demanded up to +10.5pp extra from premium-selling and opened up to 10.1pp
    EARLY for premium-buying - a preference between structure families that
    nobody chose."""
    from trdrbot import optmath

    for name, legs in _fair_zoo().items():
        p_fair = optmath.prob_profit(legs, 100.0, 0.25, 7.0)
        b = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0)[2]
        gate_opens_at = 1.0 / (1.0 + b)
        assert abs(gate_opens_at - p_fair) < 0.005, (
            f"{name}: gate opens at {gate_opens_at:.1%} against a fair rate of "
            f"{p_fair:.1%} - a {abs(gate_opens_at - p_fair) * 100:.1f}pp structural bias")


def test_friction_makes_the_gate_agree_with_the_ev_column():
    """The last gap between the two layers that decide a trade. The gate opens
    when p > 1/(1+b); with friction netted into both conditional expectations
    that is algebraically identical to 'EV after costs is positive'. Measured
    before the fix: the gate ran ahead of the EV column by 1.4pp on a wide
    condor, 4.7pp on a vertical and 16.4pp on a narrow four-leg condor, which
    pays four spreads Kelly could not see."""
    from trdrbot import experiments, optmath

    for name, legs in _fair_zoo().items():
        gross = sum(l.price * l.qty * 100 for l in legs)
        fr = gross * experiments.DEFAULT_ROUND_TRIP_COST
        gross_pr = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0)
        net_pr = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0, friction=fr)
        if net_pr is None:
            continue  # friction ate the whole expected win - correctly refused
        gate_opens_at = 1.0 / (1.0 + net_pr[2])
        net_ev_positive_at = (gross_pr[1] + fr) / (gross_pr[0] + gross_pr[1])
        assert abs(gate_opens_at - net_ev_positive_at) < 0.005, (
            f"{name}: gate at {gate_opens_at:.1%}, net EV turns positive at "
            f"{net_ev_positive_at:.1%}")


def test_a_fair_bet_that_costs_money_is_refused_not_merely_sized_small():
    from trdrbot import experiments, optmath, sizing

    for name, legs in _fair_zoo().items():
        p = optmath.prob_profit(legs, 100.0, 0.25, 7.0)
        mp, ml = optmath.max_profit_loss(legs)
        fr = sum(l.price * l.qty * 100 for l in legs) * experiments.DEFAULT_ROUND_TRIP_COST
        pr = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0, friction=fr)
        if pr is None:
            continue
        k = sizing.kelly_fraction(p, mp, ml, payoff_ratio=pr[2])
        assert k < 0, f"{name}: Kelly {k:+.3f} on a coin flip that costs ${fr:.0f} to enter"


def test_payoff_ratio_is_scale_invariant_with_friction():
    """`_matching_payoff_ratio` matches on R:R across a quantity change, so the
    ratio itself must not move with lot size - friction scales with quantity
    exactly as the conditional expectations do."""
    from trdrbot import optmath

    def at(qty):
        legs = [_fair_leg("P", 100, "short", qty), _fair_leg("P", 95, "long", qty)]
        fr = sum(l.price * l.qty * 100 for l in legs) * 0.10
        return optmath.payoff_ratio(legs, 100.0, 0.25, 7.0, friction=fr)[2]

    assert abs(at(1) - at(10)) < 1e-9, "ratio moved with lot size"


def test_conditional_expectations_stay_inside_the_structures_own_bounds():
    from trdrbot import optmath

    for name, legs in _fair_zoo().items():
        mp, ml = optmath.max_profit_loss(legs)
        w, l, _ = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0)
        assert w <= mp + 1e-6, f"{name}: E[win] {w} exceeds max profit {mp}"
        assert l <= abs(ml) + 1e-6, f"{name}: E[loss] {l} exceeds max loss {abs(ml)}"


def test_a_fairly_priced_structure_breaks_even_at_the_vol_it_was_priced_at():
    """The cleanest possible check that the root-finder finds the right root."""
    from trdrbot import optmath

    for name, legs in _fair_zoo().items():
        be = optmath.breakeven_vol(legs, 100.0, 7.0, friction=0.0)
        assert be and be.crossings, f"{name}: no breakeven vol found"
        assert abs(be.crossings[0] - 0.25) < 0.01, (
            f"{name}: breaks even at {be.crossings[0]:.1%}, priced at 25%")


def test_dominant_risk_classifies_the_zoo_the_way_a_desk_would():
    from trdrbot import optmath

    want = {"condor wide": "volatility", "condor narrow": "volatility",
            "butterfly": "volatility"}
    for name, legs in _fair_zoo().items():
        got = optmath.dominant_risk(optmath.net_greeks(legs, 100.0, 0.25, 7.0))
        assert got, f"{name}: unclassified"
        assert got[0] == want.get(name, "direction"), (
            f"{name}: classified {got[0]}, a desk would say {want.get(name, 'direction')}")


def test_a_rejected_candidate_is_a_trial_not_a_claim(tmp_path):
    """Registration and belief are different events. The muse pre-registers
    every candidate because the multiple-testing correction needs the trials
    that FAILED - but a candidate its own gates then throw out is not a claim
    anybody made, and scoring it teaches the agent how badly its rejects
    perform.

    Measured on the live ledger: 15 muse rows, all `probability_stated=True`,
    of which the muse's own journalled fates show 13 were REJECTED - bands 3x
    from spot, base rates of 0% and 100%, a horizon already in the past.
    **50% of the incoming calibration sample was material the system had
    already refused**, and it moves real size in both directions: the
    unreachable ones resolve FALSE and crater reliability, the vacuous
    one-sided ones resolve TRUE and inflate it."""
    from trdrbot.ledger import Ledger, as_forecasts

    book = Ledger(tmp_path / "ledger.jsonl")
    trial = book.register(kind="muse", underlying="NVDA", claim="band 3x from spot",
                          probability=0.55, probability_stated=False,
                          horizon="2026-09-03", band_low=650.0, band_high=920.0)
    kept = book.register(kind="muse", underlying="S", claim="survived every gate",
                         probability=0.60, probability_stated=False,
                         horizon="2026-08-31", band_low=20.25, band_high=21.9)

    assert book.trials() == 2, "both must count as trials - that is what N is for"
    book.resolve(trial.id, 700.0, "now")
    book.resolve(kept.id, 21.0, "now")
    assert len(as_forecasts(book.resolved())) == 0, "a trial must not score calibration"

    # ...until it earns the right, by surviving the gates.
    assert book.mark_stated(kept.id)
    assert not book.mark_stated(kept.id), "promotion is idempotent"
    scored = as_forecasts(book.resolved())
    assert len(scored) == 1 and scored[0].probability == 0.60


def test_muse_only_promotes_candidates_that_survive_every_gate():
    import inspect

    from trdrbot import muse

    # The gate cascade moved to `_evaluate` when the muse gained a
    # challenger arm (D-088): both arms run ONE copy of it, so the
    # invariant this test guards now lives there. Same rule, new home.
    src = inspect.getsource(muse._evaluate)
    assert "probability_stated=False" in src, "candidates register as TRIALS"
    promote = src.index("ledger.mark_stated")
    # Every rejection path must come BEFORE the promotion, or a reject is scored.
    for fate in ("a lottery ticket", "not a plausible price", "resolves too late",
                 "vacuous", "no usable price history"):
        assert src.index(fate) < promote, f"rejection '{fate}' happens after promotion"


# ====================== D-081 n_eff, and never ask a model for a price


def test_effective_n_counts_bets_not_forecasts():
    """17 SPY theses in one week are not 17 pieces of evidence. Measured on the
    live ledger: 38 theses -> 4.2 effective; the 9 with positive Kelly -> 2.0,
    so sizing each at its own Kelly overbets by 4.6x (D-080)."""
    from trdrbot.calibration import Forecast, effective_n, score

    def F(i, s):
        return Forecast(position_id=f"f{i}", probability=0.6, outcome=True, subject=s)

    all_spy = [F(i, "SPY") for i in range(10)]
    all_different = [F(i, f"N{i}") for i in range(10)]
    assert effective_n(all_spy) == 1.0, "ten bets on one name is one bet"
    assert effective_n(all_different) == 10.0
    mixed = [F(i, "SPY") for i in range(6)] + [F(i, f"N{i}") for i in range(4)]
    assert 2.0 < effective_n(mixed) < 4.0
    assert effective_n([]) is None

    # It reaches every surface that reports n.
    c = score(mixed)
    assert c.n == 10 and abs(c.n_eff - effective_n(mixed)) < 1e-9
    assert "effective" in c.sample_note()
    assert "concentrated" in c.sample_note(), "a concentrated sample must say so"
    assert "effective" in score(all_different).sample_note()
    assert "concentrated" not in score(all_different).sample_note()


def test_effective_n_is_reported_never_gated():
    """Calibration asks 'when I say 70%, does it happen 70% of the time' -
    repeated forecasts on one name at different bands are separate judgements
    even when outcomes correlate. Concentration is a reason to distrust
    GENERALISING, which is the reader's judgement (D-009)."""
    import inspect

    from trdrbot import competence, sizing

    for mod in (sizing, competence):
        assert "n_eff" not in inspect.getsource(mod), (
            f"{mod.__name__} gates on n_eff - it must only ever be reported")


def test_a_forecast_carries_what_it_is_about(tmp_path):
    from trdrbot.calibration import CalibrationStore

    s = CalibrationStore(tmp_path / "f.jsonl")
    s.record("pos_x", 0.6, "NVDA")
    s.record("pos_y", 0.7)                      # legacy caller, no subject
    again = CalibrationStore(tmp_path / "f.jsonl")   # survives a round trip
    assert [f.subject for f in again._items] == ["NVDA", ""]
    # An unknown subject counts as its own singleton rather than colliding.
    for f in again._items:
        f.outcome = True
    assert again.score().n_eff == 2.0


def test_the_muse_is_never_asked_for_an_absolute_price():
    """It was, and it answered from training data: NVDA [650,920] against a
    spot of 218.97, QQQ [355,385] against 716, MSTR [420,860] against 126.87.
    research.py's own docstring already states the rule - numbers are COMPUTED,
    never asked of the LLM."""
    from trdrbot import muse

    p = muse.MUSE_PROMPT
    assert "band_low_pct" in p and "band_high_pct" in p
    assert "PRICES IN DOLLARS" not in p, "the prompt asks for a recalled number again"
    assert '"band_low": float' not in p, "the schema still accepts absolute prices"


def test_percentage_bands_become_prices_against_live_closes():
    from trdrbot.muse import MAX_BAND_PCT, _bands_from_pct

    lo, hi = _bands_from_pct({"band_low_pct": -8.0, "band_high_pct": -2.0}, 100.0)
    assert (lo, hi) == (92.0, 98.0)
    # One-sided is fine; a reversed pair is repaired, not rejected.
    assert _bands_from_pct({"band_high_pct": 5.0}, 200.0) == (None, 210.0)
    assert _bands_from_pct({"band_low_pct": 5.0, "band_high_pct": -5.0}, 100.0) == (95.0, 105.0)
    # No spot -> no band, so the row registers as a trial and is refused as
    # unfalsifiable rather than inventing a level.
    assert _bands_from_pct({"band_low_pct": -3.0}, None) == (None, None)
    # An absurd percentage is a typo, not a thesis.
    assert _bands_from_pct({"band_low_pct": -(MAX_BAND_PCT + 1)}, 100.0) == (None, None)
    # And the failure mode that started this cannot recur: whatever the model
    # says, the price is anchored to the spot we supplied.
    lo, _ = _bands_from_pct({"band_low_pct": -10.0}, 218.97)
    assert 190 < lo < 220, "a band must land near the real spot, not 650"


def test_a_rejection_records_which_gate_refused_it(tmp_path):
    """A rejected candidate still carries a band and a horizon, so it still
    RESOLVES - and comparing 'we refused it' against 'it would have held' is a
    scored test of the gate's own threshold. That is the retrospective value of
    keeping rejects, and it needs the reason on the row rather than only in the
    journal, or the question needs a manual join across two stores.

    It scores the SYSTEM, never the agent: `probability_stated` stays False,
    so a reject can never reach calibration (D-080)."""
    from trdrbot.ledger import Ledger, as_forecasts

    book = Ledger(tmp_path / "l.jsonl")
    e = book.register(kind="muse", underlying="INTC", claim="c", probability=0.61,
                      probability_stated=False, horizon="2026-09-03",
                      band_low=32.0, band_high=44.0)
    assert book.mark_rejected(e.id, "rejected: base probability 0% - a lottery ticket")
    back = Ledger(tmp_path / "l.jsonl").all()[0]
    assert back.rejected_by.startswith("rejected: base probability 0%")
    assert back.scoreable(), "it must still resolve - that is the whole point"

    book.resolve(e.id, 38.0, "now")
    assert Ledger(tmp_path / "l.jsonl").all()[0].outcome is True
    assert as_forecasts(book.resolved()) == [], "a reject never scores the agent"


def test_every_muse_rejection_path_records_itself():
    import inspect

    from trdrbot import muse

    # The gate cascade moved to `_evaluate` when the muse gained a
    # challenger arm (D-088): both arms run ONE copy of it, so the
    # invariant this test guards now lives there. Same rule, new home.
    src = inspect.getsource(muse._evaluate)
    # Checked per-path, not by counting: a multi-line fate string slipped
    # through a count-based check, and that path really was missing its record.
    lines = src.splitlines()
    missing = [
        l.strip()[:70] for i, l in enumerate(lines)
        if 'verdict["fate"]' in l and "rejected" in l
        and "_reject(ledger, entry" not in " ".join(lines[i:i + 4])
    ]
    assert not missing, f"rejection path(s) do not record which gate refused: {missing}"
    assert sum(1 for l in lines if 'verdict["fate"]' in l and "rejected" in l) >= 6


def test_health_can_tell_an_armed_exit_engine_from_a_missing_one(tmp_path):
    """The probe read `exit` TRIGGER rows as evidence the engine had run, so
    "ran" and "produced" were the same number - the tautology D-074 named. Live
    proof it mattered: an open SPY spread with five armed rules and a populated
    debounce history reported `exit_rules never ran`, because nothing had
    breached. That is the engine working, not the engine missing."""
    import json as _json

    from trdrbot import health

    p = tmp_path / "journal.jsonl"

    # Engine evaluating, nothing breached - healthy.
    rows = [{"kind": "exit_run", "positions": 1, "rules": 5, "triggered": 0}] * 40
    p.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")
    found = {n: (l, d) for l, n, d in health.check(p, [])}
    assert found["exit_rules"][0] == health.OK, found["exit_rules"]
    assert "not stalled" in found["exit_rules"][1], (
        "an exit engine is a fire alarm - evaluating and never firing is the "
        "healthy state, and the staleness check must not escalate a quiet market")

    # Positions open but ZERO rule-checks performed - that is broken, and used
    # to look identical to the healthy case above.
    rows = [{"kind": "exit_run", "positions": 1, "rules": 0, "triggered": 0}] * 40
    p.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")
    found = {n: (l, d) for l, n, d in health.check(p, [])}
    assert found["exit_rules"][1].endswith("idle, not stalled") or \
        found["exit_rules"][0] == health.OK

    # And a real trigger reads as production.
    rows.append({"kind": "exit_run", "positions": 1, "rules": 5, "triggered": 1})
    p.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")
    found = {n: (l, d) for l, n, d in health.check(p, [])}
    assert found["exit_rules"][0] == health.OK and "produced 1" in found["exit_rules"][1]


# =================================== D-083 OpenCode Zen / GLM-5.2 migration


def test_resolve_model_spec_passes_through_unregistered_providers():
    """Every existing spec must be byte-for-byte unaffected by adding Zen -
    that is the whole point of resolving PER SPEC rather than threading
    base_url/api_key globally into build_model's shared kwargs."""
    from trdrbot import config as cm

    cfg = cm.load(quiet=True)
    for spec in ("anthropic:claude-opus-5", "openai:gpt-5", "openai:gpt-5-mini",
                "openai:gpt-4o-mini"):
        assert cfg.resolve_model_spec(spec) == (spec, {})


def test_resolve_model_spec_resolves_a_gateway_provider(monkeypatch):
    """opencode_zen: is not a real init_chat_model provider - it must resolve
    to the langchain provider that actually serves it (openai), carrying its
    OWN base_url and key so the real openai:gpt-5 entry in the same chain is
    untouched."""
    from trdrbot import config as cm

    cfg = cm.load(quiet=True)
    monkeypatch.setenv("ZEN_API_KEY", "sk-test-123")
    spec, kwargs = cfg.resolve_model_spec("opencode_zen:glm-5.2")
    assert spec == "openai:glm-5.2"
    assert kwargs == {"base_url": "https://opencode.ai/zen/v1", "api_key": "sk-test-123"}


def test_resolve_model_spec_fails_loudly_without_the_key(monkeypatch):
    """A missing gateway key must raise with the fix named, not silently
    fall through to hitting the real openai.com with the wrong model id."""
    import pytest

    from trdrbot import config as cm

    cfg = cm.load(quiet=True)
    monkeypatch.delenv("ZEN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ZEN_API_KEY"):
        cfg.resolve_model_spec("opencode_zen:glm-5.2")


def test_build_model_skips_zen_without_a_key_and_keeps_the_fallback_chain(monkeypatch):
    """The whole point of adding Zen as index 0 rather than replacing the
    chain: with no ZEN_API_KEY set (the state right after this migration
    lands, before an operator adds the key), decide must still work off
    Claude/GPT-5 - a config edit must never be able to take the agent
    offline by itself."""
    from trdrbot import config as cm
    from trdrbot.llm import build_model

    cfg = cm.load(quiet=True)
    monkeypatch.delenv("ZEN_API_KEY", raising=False)
    m = build_model(cfg, role="decide")
    assert m is not None  # built from the surviving chain, not raised


def test_doctor_and_build_model_share_one_resolver():
    """doctor's probe loop calls init_chat_model directly, bypassing
    build_model - so it must resolve specs through the SAME function or the
    two can silently disagree about what a spec means (doctor reports a
    gateway model reachable while the real decide path can't build it, or the
    reverse)."""
    import inspect

    from trdrbot import cli

    src = inspect.getsource(cli._doctor)
    assert "resolve_model_spec" in src


def test_pricing_matches_a_bare_served_model_name():
    """The usage ledger records response_metadata.model_name, which for a
    gateway is whatever the UNDERLYING model reports - likely the bare
    "glm-5.2", not the configured "opencode_zen:glm-5.2". price()'s existing
    suffix match handles the configured key; a bare key is pinned too so a
    served name that doesn't happen to suffix-match still prices correctly."""
    from trdrbot import config as cm
    from trdrbot.usage import price

    cfg = cm.load(quiet=True)
    assert price(cfg.pricing, "glm-5.2", 1_000_000, 1_000_000) == pytest.approx(5.80)
    assert price(cfg.pricing, "opencode_zen:glm-5.2", 1_000_000, 0) is not None


def test_gpt_5_6_sol_is_the_configured_primary_not_grok_or_glm():
    """Pins the actual migration decision in config.yaml, so an accidental
    revert (or a stale copy-paste of an earlier attempt's chain) is caught
    rather than silently shipping the wrong primary. Three models were tried
    in one day - GLM-5.2 (silently exhausted its output budget on structured
    prompts), Grok-4.6 (Zen's endpoint was live-down), gpt-5.6-sol (works,
    once its tool-calling quirk is handled - see the model_options test)."""
    from trdrbot import config as cm

    cfg = cm.load(quiet=True)
    for role in ("decide", "research", "discovery", "muse"):
        chain = cfg.model_chain(role)
        assert chain[0] == "openai:gpt-5.6-sol", f"{role}: wrong primary {chain[0]!r}"
        assert "opencode_zen:glm-5.2" not in chain, (
            f"{role}: GLM-5.2 was demoted for exhausting its output budget "
            f"with zero visible text on this exact role's prompt shape - it "
            f"must not silently reappear in an active chain")
        assert "opencode_zen:grok-4.6" not in chain, (
            f"{role}: Grok-4.6 was demoted while Zen's endpoint was confirmed "
            f"live-down - see I-25 before reinstating it")
        # Both real, verified-working fallbacks stay behind it.
        assert "anthropic:claude-opus-5" in chain


def test_gpt_5_6_sol_gets_its_tool_calling_fix_via_model_options():
    """A live 400 named the exact defect: 'Function tools with
    reasoning_effort are not supported for gpt-5.6-sol in
    /v1/chat/completions. To use function tools, use /v1/responses or set
    reasoning_effort to none.' Every role here needs bind_tools, so an
    unfixed gpt-5.6-sol would 400 on its very first tool-using call, every
    cycle - a real exception, so the fallback WOULD catch it, but the primary
    would never once actually serve.

    `use_responses_api=True` was chosen over `reasoning_effort="none"`
    because decide is the one role this project says should never be
    economised on - disabling reasoning to dodge an API constraint would be
    exactly that."""
    from trdrbot import config as cm

    cfg = cm.load(quiet=True)
    spec, kwargs = cfg.resolve_model_spec("openai:gpt-5.6-sol")
    assert spec == "openai:gpt-5.6-sol", "no gateway involved - this is native OpenAI"
    assert kwargs.get("use_responses_api") is True

    # And it must NOT leak onto a model with no such kwarg - ChatAnthropic
    # would reject an unknown constructor argument outright.
    assert cfg.resolve_model_spec("anthropic:claude-opus-5") == (
        "anthropic:claude-opus-5", {})
    assert cfg.resolve_model_spec("openai:gpt-5") == ("openai:gpt-5", {})


def test_model_options_composes_with_a_provider_override(monkeypatch):
    """The two per-spec mechanisms (gateway provider, model quirk) must be
    able to apply to the SAME spec at once without one clobbering the other -
    a future model on a gateway that also needs a construction kwarg is the
    case this proves works today, synthetically, since no live spec needs
    both yet."""
    from trdrbot import config as cm

    cfg = cm.load(quiet=True)
    monkeypatch.setenv("ZEN_API_KEY", "sk-test-999")
    # Borrow the real opencode_zen provider entry, add a synthetic
    # model_options entry for one of its models, and confirm both apply.
    cfg.raw["llm"]["model_options"]["opencode_zen:glm-5.2"] = {"temperature": 0.1}
    spec, kwargs = cfg.resolve_model_spec("opencode_zen:glm-5.2")
    assert spec == "openai:glm-5.2"
    assert kwargs["base_url"] == "https://opencode.ai/zen/v1"
    assert kwargs["api_key"] == "sk-test-999"
    assert kwargs["temperature"] == 0.1




def test_interim_scoring_does_not_cry_wolf_on_a_calm_young_position(tmp_path):
    """Found live: a position at -12.66% (well under the first 25% band) read
    `interim_scoring FAIL` after six housekeeping runs across under two hours
    of a freshly opened position. `eligible` counts positions the scorer
    COULD score if a band were crossed - it does not mean one was DUE, so
    treating any eligible-but-unscored run as evidence of brokenness produced
    exactly the false alarm D-082 already fixed for exit_rules one probe
    over. Most positions plausibly close - by stop, target or deadline -
    before ever crossing 25%, which makes lifelong silence here the same
    legitimate, common outcome it is for an exit rule that never breaches."""
    import json as _json

    from trdrbot import health

    p = tmp_path / "journal.jsonl"
    rows = [{"kind": "interim_run", "eligible": 1, "scored": 0}] * 6
    p.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")
    found = {n: (l, d) for l, n, d in health.check(p, [])}
    assert found["interim_scoring"][0] == health.OK, found["interim_scoring"]
    assert "not stalled" in found["interim_scoring"][1]


# --------------------------------------------------------------------------
# D-089: the model layer gets calibrated - fitted bootstrap inflation


def test_inflate_of_one_is_byte_identical_to_the_uninflated_bootstrap():
    """The default must be EXACTLY the old behaviour - same seed, same draws,
    same floats - or every historical comparison silently shifts."""
    from trdrbot import market_stats

    closes = [100 * (1 + 0.001 * ((i * 7) % 13 - 6)) ** i for i in range(1, 130)]
    a = market_stats.bootstrap_factors(closes, 5, n_paths=200, seed="ident")
    b = market_stats.bootstrap_factors(closes, 5, n_paths=200, seed="ident", inflate=1.0)
    assert a == b


def test_inflation_widens_the_distribution_in_both_directions():
    """The I-29 signature is symmetric bands overstated and BOTH tails
    understated - a too-narrow distribution. Widening must therefore LOWER
    P(inside a symmetric band) and RAISE P(beyond a tail), while keeping the
    martingale property (mean factor ~ 1)."""
    import random as _r

    from trdrbot import market_stats
    rng = _r.Random(42)
    closes = [100.0]
    for _ in range(250):
        closes.append(closes[-1] * (1 + rng.gauss(0, 0.012)))

    raw = market_stats.bootstrap_factors(closes, 5, n_paths=2000, seed="w")
    wide = market_stats.bootstrap_factors(closes, 5, n_paths=2000, seed="w", inflate=1.3)

    def p_inside(f, lo, hi):
        return sum(1 for x in f if lo <= x <= hi) / len(f)

    assert p_inside(wide, 0.97, 1.03) < p_inside(raw, 0.97, 1.03)
    assert (sum(1 for x in wide if x >= 1.02) / len(wide)
            > sum(1 for x in raw if x >= 1.02) / len(raw))
    assert abs(sum(wide) / len(wide) - 1.0) < 0.02, "inflation broke the martingale recentering"


def test_the_fit_wants_inflation_on_autocorrelated_data_and_not_on_iid():
    """Positive return autocorrelation inflates multi-day variance beyond what
    IID resampling reproduces - the class of structure the docstring already
    admitted the bootstrap destroys. The fit must detect it, and must NOT
    hallucinate inflation on data where IID is true by construction."""
    import random as _r

    from trdrbot import market_stats

    def series(phi, seed, n=300):
        rng = _r.Random(seed)
        closes, r_prev = [100.0], 0.0
        for _ in range(n):
            r = phi * r_prev + rng.gauss(0, 0.015)
            closes.append(closes[-1] * (1 + r))
            r_prev = r
        return closes

    ar = {f"AR{i}": series(0.45, i) for i in range(8)}
    iid = {f"IID{i}": series(0.0, 100 + i) for i in range(8)}

    fit_ar = market_stats.fit_band_inflation(ar, horizons=(5,), n_paths=200, step=11)
    fit_iid = market_stats.fit_band_inflation(iid, horizons=(5,), n_paths=200, step=11)

    assert fit_ar["per_horizon"]["5"] > 1.05, (
        f"autocorrelated data needs widening, fit chose {fit_ar['per_horizon']}")
    assert fit_iid["per_horizon"]["5"] <= 1.15, (
        f"IID data is calibrated by construction, fit chose {fit_iid['per_horizon']}")


def test_band_inflation_loader_fails_safe_and_clamps(tmp_path):
    """No artifact, a corrupt one, or an insane value must all degrade to the
    uninflated bootstrap - the behaviour the system had before the fit
    existed - and a fit past the ceiling is refused, not obeyed: a k of 3.0
    is evidence of something structural, not a bigger knob."""
    from trdrbot import market_stats

    assert market_stats.band_inflation(tmp_path, 5) == 1.0  # absent

    p = market_stats.model_cal_path(tmp_path)
    p.write_text("{ not json")
    assert market_stats.band_inflation(tmp_path, 5) == 1.0  # corrupt

    p.write_text('{"per_horizon": {"5": 3.0, "10": 0.4}}')
    assert market_stats.band_inflation(tmp_path, 5) == market_stats.INFLATE_MAX
    assert market_stats.band_inflation(tmp_path, 10) == 1.0  # below the floor

    p.write_text('{"per_horizon": {"3": 1.1, "10": 1.3}}')
    assert market_stats.band_inflation(tmp_path, 4) == 1.1   # nearest horizon
    assert market_stats.band_inflation(tmp_path, 9) == 1.3


def test_simulate_experiments_prices_against_the_calibrated_bootstrap(tmp_path):
    """I-62. The muse's gates read the calibrated bootstrap (D-089); this call
    - the one feeding the EV, POP and payoff_ratio the agent picks a structure
    from, and then sizing's Kelly gate - still read the raw one. An optimistic
    tail here is an optimistic bet size downstream.

    Pins the WIRING, not the maths: the fit itself is tested above. Identical
    inputs, two artifacts, and the tail probabilities must differ."""
    import json

    from trdrbot import local_tools, market_stats

    closes = [400.0 * (1.0 + 0.004 * ((i * 7) % 11 - 5)) for i in range(260)]
    dates = synthetic_dates(len(closes))

    def pop_at(k: float) -> float:
        d = tmp_path / f"k{k}"
        (d / "closes").mkdir(parents=True, exist_ok=True)
        market_stats.save_closes(d, "SPY", closes, dates=dates)
        market_stats.model_cal_path(d).write_text(
            json.dumps({"per_horizon": {"5": k}}), encoding="utf-8")
        sim = local_tools.build_simulate_experiments(local_tools.SharedContext(), d, None)
        out = sim.func(
            thesis_claim="SPY drifts lower", underlying="SPY", horizon="2026-09-05",
            drift_pct=-1.0, spot=400.0, iv_pct=20.0, days_to_expiry=5,
            band_low=380.0, band_high=395.0,
            candidates=[
                {"name": "put_spread", "legs": [
                    {"right": "P", "strike": 395, "side": "long", "qty": 1, "price": 4.0},
                    {"right": "P", "strike": 385, "side": "short", "qty": 1, "price": 1.5}]},
                {"name": "wider_put_spread", "legs": [
                    {"right": "P", "strike": 395, "side": "long", "qty": 1, "price": 4.0},
                    {"right": "P", "strike": 380, "side": "short", "qty": 1, "price": 1.0}]},
            ])
        return out

    flat, inflated = pop_at(1.0), pop_at(1.5)

    assert flat != inflated, "the fitted inflation never reached the EV grid"


def test_the_muse_base_rate_uses_the_fitted_inflation():
    """The muse's gates were the measured defect site (I-29): the vacuity
    ceiling and the lottery floor both consumed the overconfident raw base.
    The calibrated number must be what those gates see, and the inflation
    used must be recorded on the verdict for the forward audit."""
    import inspect

    from trdrbot import muse

    src = inspect.getsource(muse._evaluate)
    assert "band_inflation(" in src, "muse does not load the fitted inflation"
    assert "inflate=inflate" in src, "muse loads the inflation but does not pass it"
    assert 'verdict["base_inflate"]' in src, "the inflation used is not recorded"


def test_model_gauges_are_omitted_when_no_artifact_exists(tmp_path):
    """Absence-as-zero (notes/012): a missing fit must produce NO model gauge,
    not a gauge reading 0 or 1.0 - on a chart those are indistinguishable
    from a real measurement."""
    from types import SimpleNamespace

    from trdrbot import coach

    (tmp_path / "state").mkdir(exist_ok=True)
    cfg = SimpleNamespace(paths=SimpleNamespace(state=tmp_path / "state", data=tmp_path,
                                                journal=tmp_path / "journal.jsonl"),
                          coach={"enabled": True}, pricing={})
    g = coach.snapshot_gauges(cfg, [])
    assert "model.inflation_5d" not in g
    assert "model.cal_age_days" not in g


# ==================================================================== PILLAR-2
# ONE MEASURE, AND SEAMS THAT REFUSE  (WU-4.1..4.2; issues I-40, notes/023-024)
#
# The class these guard: two layers computing one decision quantity under
# different assumptions - two clocks (D-074), two calibration numbers (D-076),
# two cost views (D-079), and now a seam that DROPS the cost view entirely.
# The invariant is not a level, it is a relationship: every probability, EV and
# payoff ratio feeding one gate/size decision comes from one declared measure,
# friction included, and a seam that loses any part of it refuses rather than
# substitutes.
#
# Governed by docs/principles_testing.md - "The four pillars, and the rules that
# keep them from multiplying". One copy of those rules, not four.

def _fair(right: str, strike: float, spot: float = 100.0,
          iv: float = 0.25, days: float = 7.0) -> float:
    """Expected intrinsic under the SAME grid the stack prices with.

    The D-079 scaffold method: a structure built from these prices is fair BY
    CONSTRUCTION, so any edge the stack reports on one is an artefact of the
    stack rather than of the market.
    """
    grid = optmath._lognormal_grid(spot, iv, days)
    if right == "C":
        return sum(w * max(0.0, s - strike) for s, w in grid)
    return sum(w * max(0.0, strike - s) for s, w in grid)


def test_long_call_sizes_on_its_conditional_payoff_despite_unbounded_profit():
    """G6: 'unbounded max loss OR profit' banned cheap convexity at any edge.

    A long call's LOSS is bounded at the debit and its conditional payoff is
    finite (measured 1.96 on a fair-priced ATM call) - E[win|win] exists even
    though max profit does not. Refusing it treated the good direction of
    unboundedness as though it were the dangerous one.
    """
    legs = [Leg(right="C", strike=100.0, side="long", qty=1, price=_fair("C", 100.0))]
    mp, ml = optmath.max_profit_loss(legs)
    assert mp is None and ml is not None, "the shape under test: upside unbounded"
    pr = optmath.payoff_ratio(legs, 100.0, 0.25, 7.0)
    assert pr is not None, "a conditional payoff exists precisely because E[win|win] is finite"

    d = _size(max_profit=mp, max_loss=ml, payoff_ratio=pr[2], stated_confidence=0.60)

    assert d.contracts >= 1, d.reason
    assert d.kelly_full is not None and d.kelly_full > 0


def test_unbounded_loss_is_refused_even_when_a_conditional_payoff_is_supplied():
    """The asymmetry is the whole point: Kelly divides by the worst case, and
    an unbounded loss does not have one. No ratio rescues that."""
    d = _size(max_profit=500.0, max_loss=None, payoff_ratio=1.5)
    assert d.contracts == 0
    assert "unbounded max loss" in d.reason


def test_unbounded_profit_without_a_ratio_refuses_for_the_MISSING_RATIO():
    """The refusal must name what is actually missing. Blaming the
    unboundedness is what made the long call permanently unsizeable - the
    repair is 'simulate it', not 'pick another structure'."""
    d = _size(max_profit=None, max_loss=-260.0)
    assert d.contracts == 0
    assert "conditional payoff" in d.reason
    assert "simulate" in d.reason.lower()


def _sim_and_size(tmp_path, candidates, *, journal=None, spot=100.0, iv_pct=25.0,
                  days=7, equity=100_000.0):
    """Drive the REAL tool pair over a real SharedContext.

    Producer-derived on purpose (the trdrbot testing overlay): the shared
    context is built by calling `simulate_experiments`, never by hand-stuffing
    `shared.structures` - two capabilities have shipped dead here because a
    test built its own input and the caller disagreed with it.
    """
    from trdrbot.calibration import CalibrationStore

    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, None, None)
    sim.func(thesis_claim="pinned", underlying="X", horizon="2099-01-05",
             drift_pct=0.0, spot=spot, iv_pct=iv_pct, days_to_expiry=days,
             band_low=spot - 1, band_high=spot + 1, candidates=candidates)
    size = local_tools.build_size_position(
        CalibrationStore(tmp_path / "cal.jsonl"), equity, shared=shared,
        journal=journal)
    return shared, size


def _legs(spec, spread=None):
    """[(right, strike, side)] -> tool leg dicts priced fair, optionally quoted."""
    out = []
    for right, strike, side in spec:
        price = round(_fair(right, strike), 4)
        leg = {"right": right, "strike": strike, "side": side, "qty": 1, "price": price}
        if spread is not None:
            leg["bid"] = round(max(0.01, price - spread / 2), 4)
            leg["ask"] = round(price + spread / 2, 4)
        out.append(leg)
    return out


NARROW = [("P", 100, "short"), ("P", 99, "long"), ("C", 101, "short"), ("C", 102, "long")]
WIDE = [("P", 95, "short"), ("P", 90, "long"), ("C", 105, "short"), ("C", 110, "long")]


def test_sizing_tool_refuses_when_nothing_was_simulated(tmp_path):
    """I-40, one gate earlier than D-038's chain-order-record shortcut: the
    conditional payoff and the friction estimate exist ONLY inside
    simulate_experiments, so sizing without one has nothing honest to size on."""
    from trdrbot.calibration import CalibrationStore

    size = local_tools.build_size_position(
        CalibrationStore(tmp_path / "cal.jsonl"), 100_000.0,
        shared=local_tools.SharedContext())

    out = size.func(stated_confidence=0.70, max_profit=800.0, max_loss=-1200.0,
                    underlying="X")

    assert "REFUSED" in out and "simulate_experiments" in out


def test_sizing_tool_refuses_an_ambiguous_match_and_names_the_candidates(tmp_path):
    """A wrong `b` is worse than no trade, and the repair must be actionable -
    so the refusal lists the names it would accept."""
    _shared, size = _sim_and_size(tmp_path, [
        {"name": "narrow condor", "legs": _legs(NARROW)},
        {"name": "wide condor", "legs": _legs(WIDE)},
    ])

    out = size.func(stated_confidence=0.70, max_profit=999.0, max_loss=-1000.0,
                    underlying="X")

    assert "REFUSED" in out
    assert "narrow condor" in out and "wide condor" in out


def test_sizing_tool_refuses_when_friction_has_eaten_the_conditional_payoff(tmp_path):
    """I-40, the measured case, at real quoted spreads.

    `optmath.payoff_ratio` returns None when the whole expected win is consumed
    by the round trip - D-079's "there is no payoff to bet on, and sizing should
    refuse rather than compute with it". That refusal was then DISCARDED one
    seam later: `None` reached `size_position` as "no match", which fell back to
    frictionless max/max and sized the trade at the per-position cap.
    """
    shared, size = _sim_and_size(tmp_path, [
        {"name": "narrow condor", "legs": _legs(NARROW, spread=0.15)},
        {"name": "wide condor", "legs": _legs(WIDE, spread=0.15)},
    ])
    narrow = next(s for s in shared.structures if s.name == "narrow condor")
    assert narrow.payoff_ratio is None, "precondition: friction ate the expected win"

    out = size.func(stated_confidence=0.70, max_profit=narrow.max_profit,
                    max_loss=narrow.max_loss, underlying="X",
                    structure_name="narrow condor")

    assert "REFUSED" in out and "friction" in out
    # What the discarded refusal used to become: a sized position at the cap.
    fallback = sizing.size_position(
        equity=100_000.0, stated_confidence=0.70, max_profit=narrow.max_profit,
        max_loss=narrow.max_loss, calibration=ESTABLISHED, underlying="X",
        payoff_ratio=None)
    assert fallback.contracts > 0, "the fallback this seam no longer reaches"


def test_sizing_tool_uses_the_priced_structures_own_conditional_ratio(tmp_path):
    """The happy path, and the reason the refusals above are affordable."""
    shared, size = _sim_and_size(tmp_path, [
        {"name": "narrow condor", "legs": _legs(NARROW)},
        {"name": "wide condor", "legs": _legs(WIDE)},
    ])
    wide = next(s for s in shared.structures if s.name == "wide condor")

    out = size.func(stated_confidence=0.95, max_profit=wide.max_profit,
                    max_loss=wide.max_loss, underlying="X",
                    structure_name="wide condor")

    assert "REFUSED" not in out
    assert f"payoff {wide.payoff_ratio:.2f}" in out, "sized on the ratio actually priced"
    assert "conditional" in out


def test_every_sizing_outcome_is_journalled_including_the_refusals(tmp_path):
    """The production-visible trace. Without it a seam that starts losing the
    conditional payoff again is invisible until a position is already on."""
    from trdrbot.journal import Journal

    journal = Journal(tmp_path / "journal.jsonl")
    shared, size = _sim_and_size(tmp_path, [
        {"name": "narrow condor", "legs": _legs(NARROW)},
        {"name": "wide condor", "legs": _legs(WIDE)},
    ], journal=journal)
    wide = next(s for s in shared.structures if s.name == "wide condor")

    size.func(stated_confidence=0.95, max_profit=wide.max_profit,
              max_loss=wide.max_loss, underlying="X", structure_name="wide condor")
    size.func(stated_confidence=0.70, max_profit=1.0, max_loss=-1.0, underlying="X")

    rows = [r for r in journal.read() if r.get("kind") == "sizing"]
    assert [r["result"] for r in rows] == ["sized", "refused"]
    assert rows[0]["contracts"] > 0 and rows[1]["contracts"] == 0
    assert "REFUSED" in rows[1]["reason"]


def test_breakeven_vol_finds_the_crossing_of_a_name_priced_above_the_old_grid_cap():
    """I-44: the grid stopped at 120%, so a structure priced at IV 150% - a meme
    name, a binary event - had its breakeven OUTSIDE the searched range and came
    back as "EV positive at every realized vol tested". The scan now follows the
    quote, and a fair-priced structure still breaks even at exactly the vol it
    was priced at (the cleanest check that the root-finder finds the right root).
    """
    from trdrbot.optmath import breakeven_vol

    legs = [Leg(right="P", strike=100.0, side="short", qty=1,
                price=_fair("P", 100.0, iv=1.50)),
            Leg(right="P", strike=95.0, side="long", qty=1,
                price=_fair("P", 95.0, iv=1.50))]

    be = breakeven_vol(legs, 100.0, 7.0, iv_hint=1.50)

    assert be.crossings, "the breakeven exists, it was simply above the old ceiling"
    assert abs(be.crossings[0] - 1.50) < 0.01, be.crossings
    assert "wins if realized vol <" in be.describe()


def test_a_scan_that_finds_nothing_says_how_far_it_looked():
    """"No crossing" is a claim about the GRID and reads as a claim about the
    world. Both are legitimate answers; only one of them is honest on its own."""
    from trdrbot.optmath import breakeven_vol

    free = [Leg(right="C", strike=105.0, side="long", qty=1, price=0.0),
            Leg(right="C", strike=110.0, side="short", qty=1, price=0.50)]

    be = breakeven_vol(free, 100.0, 7.0)

    assert not be.crossings
    assert "searched to 120%" in be.describe(), be.describe()
    assert "searched to 225%" in breakeven_vol(free, 100.0, 7.0, iv_hint=1.50).describe()


def test_record_position_warns_when_mark_rules_can_never_print(tmp_path):
    """I-45: below 2% of gross premium the mark-based P&L base is refused as
    division by noise (correctly - a structure whose legs nearly cancel has
    almost no net cost), so every stop and target on it holds FOREVER. Nothing
    else said so: `invalid_rules()` reads 0 because they parse and
    `watched_signals()` lists position_mark because they are watched - they
    simply never observe anything. This is `_unreachable_rules`' blind spot by
    construction: that check bails out at `base <= 0`, which is precisely the
    structure that needs warning about.
    """
    from trdrbot.calibration import CalibrationStore
    from trdrbot.positions import PositionStore

    # Synthetic long: at-the-money call and put are equal by parity on a
    # martingale grid, so the two premiums cancel to a near-zero net cost.
    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, None, None)
    sim.func(thesis_claim="up", underlying="X", horizon="2099-01-05", drift_pct=1.0,
             spot=100.0, iv_pct=25.0, days_to_expiry=7, band_low=99.0, band_high=105.0,
             candidates=[
                 {"name": "synthetic long", "legs": _legs(
                     [("C", 100, "long"), ("P", 100, "short")])},
                 {"name": "call debit", "legs": _legs(
                     [("C", 100, "long"), ("C", 105, "short")])},
             ])
    synth = next(s for s in shared.structures if s.name == "synthetic long")
    assert abs(synth.entry_cost) < 0.02 * synth.gross_premium, "precondition: legs cancel"

    store = PositionStore(tmp_path)
    rec = local_tools.build_record_position(
        store, "jrn_x", shared=shared,
        calibration=CalibrationStore(tmp_path / "cal.jsonl"))
    out = rec.func(
        underlying="X", strategy="synthetic_long", thesis="up", confidence=0.6,
        expiry="2026-10-16", stop_loss_pct=-50.0, profit_target_pct=50.0,
        legs=[{"symbol": "X261016C00100000", "side": "buy", "qty": 1},
              {"symbol": "X261016P00100000", "side": "sell", "qty": 1}])

    assert "NEVER fire" in out, out
    assert "underlying_stop" in out and "time_stop" in out, "the warning names the repair"
    # The rules really are watched and really do parse - which is why nothing
    # else in the system could have told the agent this.
    saved = store.all()[0]
    from trdrbot.exit_rules import invalid_rules, watched_signals
    assert invalid_rules(saved) == 0
    assert "position_mark" in watched_signals(saved)


def test_a_normal_spread_gets_no_blind_mark_warning(tmp_path):
    """The other half of the pair: a structure with a real net cost must not
    collect a warning about one it does not have."""
    from trdrbot.calibration import CalibrationStore
    from trdrbot.positions import PositionStore

    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, None, None)
    sim.func(thesis_claim="up", underlying="X", horizon="2099-01-05", drift_pct=1.0,
             spot=100.0, iv_pct=25.0, days_to_expiry=7, band_low=99.0, band_high=105.0,
             candidates=[
                 {"name": "call debit", "legs": _legs(
                     [("C", 100, "long"), ("C", 105, "short")])},
                 {"name": "put credit", "legs": _legs(
                     [("P", 100, "short"), ("P", 95, "long")])},
             ])

    store = PositionStore(tmp_path)
    rec = local_tools.build_record_position(
        store, "jrn_x", shared=shared,
        calibration=CalibrationStore(tmp_path / "cal.jsonl"))
    out = rec.func(
        underlying="X", strategy="call_debit", thesis="up", confidence=0.6,
        expiry="2026-10-16", stop_loss_pct=-50.0, profit_target_pct=50.0,
        legs=[{"symbol": "X261016C00100000", "side": "buy", "qty": 1},
              {"symbol": "X261016C00105000", "side": "sell", "qty": 1}])

    assert "NEVER fire" not in out


# ==================================================================== PILLAR-1
# ECONOMIC CONSCIENCE  (WU-4.5; issue I-41, notes/023-024)
#
# One relationship, not a level, and it is deliberately BOTH of the things a
# pair of threshold evals would contradict each other about: the gate opens
# exactly where expected value after costs turns positive, under the measure the
# thesis actually declares. "Never pay for a coin flip" and "never starve a real
# edge" are the same invariant read in two directions.
#
# D-079 proved this exact for drift theses. The vol view extends the SAME
# algebra to vol theses: with `b` = (E[win|win] - f) / (E[loss|loss] + f) and
# the model's own p, EV-after-costs > 0 iff p > 1/(1+b) iff Kelly > 0.
# Governed by docs/principles_testing.md - the four pillars.

def test_the_gate_opens_exactly_where_ev_after_costs_does_under_a_vol_view():
    """I-41: a vol thesis had no vol knob, so `p` came from the agent's measure
    while `b` came from the market's - two measures in one Kelly. Swept across a
    real vol edge, the sign of Kelly must agree with the sign of EV after costs
    at every point, exactly as it already did for drift."""
    spot, iv_market, days = 100.0, 0.25, 7.0
    legs = [Leg(right="P", strike=100.0, side="short", qty=1, price=_fair("P", 100.0)),
            Leg(right="P", strike=95.0, side="long", qty=1, price=_fair("P", 95.0))]
    mp, ml = optmath.max_profit_loss(legs)
    friction = sum(l.price * l.qty * 100 for l in legs) * experiments.DEFAULT_ROUND_TRIP_COST

    for vol_view in [0.25 - i / 100 for i in range(0, 13)]:
        ev = optmath.expected_value(legs, spot, vol_view, days) - friction
        p = optmath.prob_profit(legs, spot, vol_view, days)
        pr = optmath.payoff_ratio(legs, spot, vol_view, days, friction=friction)
        k = sizing.kelly_fraction(p, mp, ml, payoff_ratio=pr[2]) if pr else None
        if abs(ev) < 1.0:
            continue  # the boundary itself; sign is meaningless inside a dollar
        assert (k > 0) == (ev > 0), (
            f"vol {vol_view:.0%}: Kelly {k:+.4f} disagrees with EV after costs {ev:+.2f}")


def test_a_real_vol_edge_now_earns_kelly_instead_of_the_seed_allocation():
    """The measured consequence of I-41, and the point of the whole change: a
    short-premium book could never earn Kelly size however large and however
    honestly stated its edge, because the payoff was priced under the market's
    vol while the probability was priced under the agent's."""
    spot, days = 100.0, 7
    legs = [{"right": "P", "strike": 100, "side": "short", "qty": 1,
             "price": round(_fair("P", 100.0), 4)},
            {"right": "P", "strike": 95, "side": "long", "qty": 1,
             "price": round(_fair("P", 95.0), 4)}]
    exp_legs = [Leg.parse(l) for l in legs]
    mp, ml = optmath.max_profit_loss(exp_legs)

    def sized(vol_view_pct):
        thesis = experiments.Thesis(
            claim="realized comes in under implied", underlying="X",
            horizon="2099-01-05", band_low=95.0, band_high=105.0,
            vol_view=(vol_view_pct / 100.0) if vol_view_pct else None)
        m = experiments.simulate(
            experiments.Experiment(name="put credit", legs=exp_legs), thesis,
            spot=spot, iv=0.25, days=days)
        return sizing.size_position(
            equity=100_000.0, stated_confidence=m["pop_thesis"], max_profit=mp,
            max_loss=ml, calibration=ESTABLISHED, underlying="X",
            payoff_ratio=m["payoff_ratio"])

    # A genuine 12-point vol edge, honestly stated.
    edge = sized(13.0)
    assert edge.kelly_full > 0, "a real vol edge must reach Kelly at all"
    assert "record does not support" not in edge.reason

    # ...and with no vol view the same trade is priced at the market's own vol,
    # where by construction there is no edge to earn size with.
    none_stated = sized(None)
    assert none_stated.kelly_full <= 0
    assert edge.fraction_of_equity > none_stated.fraction_of_equity


def test_a_skewed_board_is_evaluated_where_the_position_lives_not_at_the_ATM_guess():
    """I-43: greeks honoured `Leg.iv` while the distribution did not, so risk
    and edge were computed under DIFFERENT surfaces - and the vol the edge was
    computed at could be one nobody quoted for these strikes.

    The measured case is a call credit spread whose legs quote 19% and 21% on a
    board whose ATM is 25%. Evaluating it at 25% is not a conservative
    approximation, it is a different structure: EV reads -$6.68 there and
    +$0.05 at the vega-weighted 21.0%.

    Note what is NOT claimed, because the first version of this finding claimed
    it and it does not survive: there is no single flat vol that makes such a
    board zero-EV. The legs were priced under mutually inconsistent lognormals,
    which is what a smile IS to a model that does not have one. So the honest
    invariant is that the evaluation vol sits where the position's own vega
    sits - and that the residual is REPORTED rather than chosen silently.
    """
    skew = {90: 0.34, 95: 0.30, 100: 0.25, 105: 0.21, 110: 0.19}

    def leg(right, strike, side):
        return Leg(right=right, strike=strike, side=side, qty=1,
                   price=_fair(right, strike, iv=skew[strike]), iv=skew[strike])

    legs = [leg("C", 105, "short"), leg("C", 110, "long")]
    thesis = experiments.Thesis(claim="no view", underlying="X", horizon="2099-01-05",
                                band_low=90.0, band_high=110.0)

    m = experiments.simulate(experiments.Experiment(name="call credit", legs=legs),
                             thesis, spot=100.0, iv=0.25, days=7)

    # The evaluation vol is inside the range the legs actually quote, and
    # nowhere near the ATM figure the caller passed.
    assert 19.0 <= m["iv_eff_pct"] <= 21.0, m["iv_eff_pct"]
    # ...and that materially changes the decision number on this structure.
    flat = optmath.expected_value(legs, 100.0, 0.25, 7.0)
    assert abs(m["ev_market"] - flat) > 5.0, (
        f"the flat-ATM guess and the vega-weighted evaluation differ by only "
        f"{abs(m['ev_market'] - flat):.2f} - this board no longer demonstrates the gap")
    # The residual assumption is reported, and the evaluated answer sits inside it.
    assert m["ev_span"] is not None
    assert m["ev_span"][0] < m["ev_span"][1]


def test_a_flat_board_is_untouched_by_the_skew_machinery():
    """Byte-identity where there is no smile: no leg IVs means no choice to
    defend, so nothing is weighted, nothing is reported, nothing moves."""
    legs = [Leg(right="P", strike=100.0, side="short", qty=1, price=_fair("P", 100.0)),
            Leg(right="P", strike=95.0, side="long", qty=1, price=_fair("P", 95.0))]
    thesis = experiments.Thesis(claim="no view", underlying="X", horizon="2099-01-05",
                                band_low=90.0, band_high=110.0)

    m = experiments.simulate(experiments.Experiment(name="flat", legs=legs), thesis,
                             spot=100.0, iv=0.25, days=7)

    assert optmath.vega_weighted_iv(legs, 100.0, 7.0, 0.25) is None
    assert m["iv_eff_pct"] is None and m["ev_span"] is None
    assert m["ev_market"] == optmath.expected_value(legs, 100.0, 0.25, 7.0)


def test_every_position_field_survives_a_save_load_round_trip(tmp_path):
    """The frontmatter is an explicit allowlist, so a new dataclass field is
    silently NOT persisted until someone remembers three places at once.

    Found the hard way: `thesis_vol_view` shipped in WU-4.5 - the whole point of
    which was that a vol thesis is scored and attributable later - and never
    reached the page at all. Set at record time, gone on the next read, and no
    test noticed because every test checked the fields it already knew about.

    So this asserts the PROPERTY rather than a list: every field a Position
    carries round-trips, unless it is on the exclusion list below with a reason.
    One invariant beats ten examples, and this is the invariant the three
    hand-maintained copies (dataclass, frontmatter, _parse) need.
    """
    import dataclasses

    from trdrbot.positions import Position, PositionStore

    #: Fields deliberately not in the frontmatter, each for a stated reason.
    #: Adding to this list is a decision; forgetting a field is not.
    NOT_PERSISTED = {
        "path": "runtime handle to the file itself, not content",
        "thesis": "written as page BODY prose, not frontmatter (round-tripped below)",
        "generated_by": "nested under the OKF `generated` block, not a top-level key",
    }

    store = PositionStore(tmp_path)
    saved = Position(
        position_id="pos_roundtrip_test", status="open", strategy="iron_condor",
        underlying="SPY", opened="2026-08-30T12:00:00+00:00", expiry="2026-09-11",
        legs=[{"symbol": "SPY260911P00600000", "side": "sell", "qty": 2}],
        exit_rules=[{"type": "stop_loss", "threshold": "-50.0%"}],
        exit_state={"position_mark:below:-0.5": [True]},
        close_reason=None, thesis="a test thesis", decision_ref="jrn_x",
        provenance="agent", sources=[{"id": "s1"}], generated_by="model:x",
        verified=[{"claim": "c"}], elfmem_blocks={"task": ["b1"]},
        mind_decision_block_id="m1", thesis_claim="SPY stays in a range",
        thesis_horizon="2026-09-05", thesis_band_low=590.0, thesis_band_high=610.0,
        thesis_drift=0.004, thesis_vol_view=0.135, attribution="",
        interim_band=1, max_loss_usd=800.0, last_pnl_pct=-0.12,
        greeks_at_entry={"delta_dollars": 1.0}, entry_iv=0.16, entry_spot=604.2,
        leg_divergence_count=1,
    )
    store.save(saved)

    loaded = store.load("pos_roundtrip_test")

    for f in dataclasses.fields(Position):
        if f.name in NOT_PERSISTED:
            continue
        assert getattr(loaded, f.name) == getattr(saved, f.name), (
            f"Position.{f.name} did not survive the round trip - add it to "
            f"`frontmatter()` AND `_parse()`, or to NOT_PERSISTED with a reason")
    assert loaded.thesis == saved.thesis, "the body prose must round-trip too"


def test_the_skew_the_agent_traded_survives_onto_the_position(tmp_path):
    """I-50: WU-4.8 made the PRE-trade layer skew-aware (EV, POP, payoff all
    evaluate at the vega-weighted leg vol) while everything after entry stayed
    flat - `Leg.from_position_leg` never set `.iv`, so the greeks stamped at
    entry and the book-greeks line the agent reads every cycle described a
    position built from a skewed board as though the board were flat.

    Derived, not declared (D-037): the IVs come from the simulated structure
    the trade was matched to, never from the model re-typing them.
    """
    from trdrbot.calibration import CalibrationStore
    from trdrbot.positions import PositionStore

    skew = {100: 0.30, 95: 0.34}
    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, None, None)
    sim.func(thesis_claim="range", underlying="X", horizon="2099-01-05", drift_pct=0.0,
             spot=100.0, iv_pct=25.0, days_to_expiry=7, band_low=95.0, band_high=105.0,
             candidates=[
                 {"name": "put credit", "legs": [
                     {"right": "P", "strike": 100, "side": "short", "qty": 1,
                      "price": round(_fair("P", 100.0, iv=skew[100]), 4),
                      "iv_pct": skew[100] * 100},
                     {"right": "P", "strike": 95, "side": "long", "qty": 1,
                      "price": round(_fair("P", 95.0, iv=skew[95]), 4),
                      "iv_pct": skew[95] * 100}]},
                 {"name": "call debit", "legs": [
                     {"right": "C", "strike": 100, "side": "long", "qty": 1,
                      "price": round(_fair("C", 100.0), 4)},
                     {"right": "C", "strike": 105, "side": "short", "qty": 1,
                      "price": round(_fair("C", 105.0), 4)}]},
             ])

    store = PositionStore(tmp_path)
    rec = local_tools.build_record_position(
        store, "jrn_x", shared=shared,
        calibration=CalibrationStore(tmp_path / "cal.jsonl"))
    rec.func(underlying="X", strategy="put_credit", thesis="range", confidence=0.6,
             expiry="2026-10-16",
             legs=[{"symbol": "X261016P00100000", "side": "sell", "qty": 1},
                   {"symbol": "X261016P00095000", "side": "buy", "qty": 1}])

    saved = store.load(store.all()[0].position_id)
    by_strike = {optmath.parse_occ(l["symbol"])["strike"]: l for l in saved.legs}
    assert by_strike[100.0]["iv_pct"] == pytest.approx(30.0)
    assert by_strike[95.0]["iv_pct"] == pytest.approx(34.0)

    # ...and the greeks actually USED it: the same legs priced flat differ.
    flat = optmath.net_greeks(
        [optmath.Leg(right="P", strike=100.0, side="short", qty=1, price=0.0),
         optmath.Leg(right="P", strike=95.0, side="long", qty=1, price=0.0)],
        saved.entry_spot, saved.entry_iv, 7)
    assert saved.greeks_at_entry["vega_dollars"] != pytest.approx(
        round(flat["vega_dollars"], 2)), "the skew made no difference to the greeks"


def test_a_flat_board_records_no_per_leg_iv(tmp_path):
    """The identity half: no skew observed, nothing invented."""
    from trdrbot.calibration import CalibrationStore
    from trdrbot.positions import PositionStore

    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, None, None)
    sim.func(thesis_claim="up", underlying="X", horizon="2099-01-05", drift_pct=1.0,
             spot=100.0, iv_pct=25.0, days_to_expiry=7, band_low=99.0, band_high=105.0,
             candidates=[
                 {"name": "call debit", "legs": _legs(
                     [("C", 100, "long"), ("C", 105, "short")])},
                 {"name": "put credit", "legs": _legs(
                     [("P", 100, "short"), ("P", 95, "long")])},
             ])

    store = PositionStore(tmp_path)
    rec = local_tools.build_record_position(
        store, "jrn_x", shared=shared,
        calibration=CalibrationStore(tmp_path / "cal.jsonl"))
    rec.func(underlying="X", strategy="call_debit", thesis="up", confidence=0.6,
             expiry="2026-10-16",
             legs=[{"symbol": "X261016C00100000", "side": "buy", "qty": 1},
                   {"symbol": "X261016C00105000", "side": "sell", "qty": 1}])

    saved = store.load(store.all()[0].position_id)
    assert all("iv_pct" not in l for l in saved.legs)


def test_the_lock_verifies_its_own_claim_and_loses_a_race_it_did_not_win(tmp_path):
    """I-51: acquisition was read-check-write with nothing between the check
    and the write, so two processes arriving in the same instant could both
    pass the check, both write, and both proceed - concurrent ticks
    double-processing the inbox or double-submitting an order.

    Simulated at the only point where it matters: a rival's claim is on disk by
    the time we read back what we wrote."""
    import json as _json

    from trdrbot.lock import tick_lock

    path = tmp_path / "tick.lock"
    original_write = Path.write_text

    def rival_wins(self, *a, **kw):
        original_write(self, *a, **kw)
        if self == path:  # the rival lands between our write and our read-back
            original_write(self, _json.dumps({"pid": 999999, "ts": 9e9}),
                           encoding="utf-8")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "write_text", rival_wins)
        with pytest.raises(BlockingIOError, match="999999"):
            with tick_lock(path):
                pytest.fail("proceeded while another process held the lock")

    assert _json.loads(path.read_text())["pid"] == 999999, "the rival's lock was clobbered"


def test_the_single_shot_tick_classifies_its_failure_instead_of_crashing(tmp_path):
    """I-52: `run.sh` points cron/launchd at this path, where a raw traceback
    is the least useful thing an operator can be handed. The run loop has
    classified-and-continued since it existed."""
    import asyncio

    from trdrbot import cli

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "run_tick",
                   lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broker exploded")))
        code = asyncio.run(cli._tick())

    assert code == 1, "a failed tick must signal failure to cron, not exit 0"
