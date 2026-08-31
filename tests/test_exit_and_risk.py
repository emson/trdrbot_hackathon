"""The deterministic capital-protection path, fed the inputs it actually gets.

Exit rules are authored by an LLM and stored as YAML on disk, so "malformed"
is a normal operating condition here, not a corner case. The existing suite
only ever fed this path clean, well-formed rules - which is how a threshold
that fails to parse came to mean a stop at exactly breakeven.
"""

from __future__ import annotations

from typing import Any

from conftest import FakeMem, journal_rows, tools_for

from trdrbot import exit_rules, reconcile
from trdrbot.analytics import Snapshot
from trdrbot.calibration import CalibrationStore
from trdrbot.journal import Journal
from trdrbot.positions import PositionStore
from trdrbot.wiki import Wiki


def _underwater(symbols: list[str], pnl_fraction: float, *,
                market_open: bool = True) -> Snapshot:
    """A broker snapshot showing the position at `pnl_fraction` of its net
    entry cost - built the way `position_pnl_fraction` actually reads it, not the
    way a test would find convenient.

    `market_open=True` is stated rather than inherited from the dataclass
    default: every caller of this helper is asking whether a breach CLOSES, and
    since I-56 a close only actuates in session. The old default said "closed"
    and these tests passed anyway, which meant they were not testing what they
    read as testing. Same honest-form correction as I-55's `broker_readable`.
    """
    per_leg = 1000.0 / max(1, len(symbols))
    return Snapshot(market_open=market_open, broker_positions=[
        {"symbol": s, "cost_basis": per_leg, "unrealized_pl": per_leg * pnl_fraction}
        for s in symbols
    ])


async def _run(store: PositionStore, snap: Snapshot, journal: Journal, paths: Any,
               tools: dict[str, Any] | None = None) -> list[str]:
    return await exit_rules.run(
        store, snap, tools or {}, journal, "2099-01-01", FakeMem(), Wiki(paths.wiki),
        calibration=CalibrationStore(paths.state / "forecasts.jsonl"), verbose=False,
    )


def _exit_run(journal: Journal) -> dict[str, Any]:
    rows = journal_rows(journal, "exit_run")
    assert rows, "the evaluator left no heartbeat"
    return rows[-1]


# ------------------------------------------------------- threshold parsing


async def test_an_unparseable_threshold_holds_instead_of_stopping_at_breakeven(
    paths, make_position
):
    """`_pct` leaned on `_f`, whose default is 0.0, so a threshold of "abc"
    became a stop at EXACTLY BREAKEVEN - and any position slightly underwater
    debounced into a close on the second check. `_normalise`'s docstring
    already promised to return None for anything unrecognised; it did not."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(exit_rules=[
        {"type": "stop_loss", "basis": "position_mark", "threshold": "abc"},
        {"type": "profit_target", "basis": "position_mark", "threshold": "140.0%"},
    ])
    store.save(pos)
    snap = _underwater(pos.symbols, -0.05)  # 5% down: nowhere near any real stop

    triggered = await _run(store, snap, journal, paths)
    triggered += await _run(store, snap, journal, paths)  # twice: debounce needs 2 of 3

    assert triggered == [], "an unreadable threshold closed a healthy position"
    assert _exit_run(journal)["invalid_rules"] == 1, "the unreadable rule was not reported"


async def test_a_valid_rule_alongside_a_broken_one_still_fires(paths, make_position):
    """Dropping the bad rule must not disarm the good one."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(exit_rules=[
        {"type": "stop_loss", "basis": "position_mark", "threshold": ""},
        {"type": "stop_loss", "basis": "position_mark", "threshold": "-20.0%"},
    ])
    store.save(pos)
    snap = _underwater(pos.symbols, -0.9)  # past 2x the -20% stop

    # Two ticks, because the breach is on the MARK and this snapshot carries no
    # underlying to corroborate it (WU-4.6) - so it takes the ordinary 2-of-3
    # debounce rather than the immediate path. The subject of this test is
    # unchanged: a broken rule beside a good one must not disarm the good one.
    await _run(store, snap, journal, paths, tools_for(close_position=lambda **k: {}))
    triggered = await _run(store, snap, journal, paths,
                           tools_for(close_position=lambda **k: {}))

    assert triggered == [pos.position_id]


def test_a_null_day_count_on_a_time_stop_is_dropped_not_raised():
    """`float(rule.get("days_before_expiry", 0))` raised TypeError on an
    explicit null - the key is present, so the default never fired, and the
    raise took every other position's evaluation down with it."""
    assert exit_rules._normalise({"type": "time_stop", "days_before_expiry": None}) is None
    assert exit_rules._normalise({"type": "time_stop", "days_before_expiry": 2}) is not None


async def test_one_unevaluable_position_does_not_blind_the_evaluator_to_the_others(
    paths, make_position, monkeypatch
):
    """A single position's bad data used to take capital protection offline for
    the WHOLE BOOK, every tick, until someone hand-fixed the file."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    bad = make_position(position_id="pos_bad")
    good = make_position(position_id="pos_good", exit_rules=[
        {"type": "stop_loss", "basis": "position_mark", "threshold": "-20.0%"},
    ])
    store.save(bad)
    store.save(good)

    real_evaluate = exit_rules.evaluate

    def explode(pos: Any, snap: Any, deadline: str, **kw: Any) -> Any:
        if pos.position_id == "pos_bad":
            raise ValueError("unreadable debounce state")
        return real_evaluate(pos, snap, deadline, **kw)

    monkeypatch.setattr(exit_rules, "evaluate", explode)
    snap = _underwater(good.symbols, -0.9)

    # Two ticks: the mark breach debounces without an underlying to corroborate
    # it (WU-4.6). What is under test - one bad position must not blind the
    # evaluator to the rest of the book - is unchanged.
    await _run(store, snap, journal, paths, tools_for(close_position=lambda **k: {}))
    triggered = await _run(store, snap, journal, paths,
                           tools_for(close_position=lambda **k: {}))

    assert triggered == ["pos_good"], "one bad position blinded the evaluator"
    assert _exit_run(journal)["errors"] == 1


# ------------------------------------------------------------- broker rows


async def test_a_symbol_less_broker_row_does_not_kill_the_fast_path(paths, make_position):
    """`by_symbol` did a bare `p["symbol"]`, and it is the FIRST thing reconcile
    calls - so one odd row from the broker took reconciliation and exit-rule
    evaluation down for the whole tick."""
    store = PositionStore(paths.wiki)
    pos = make_position()
    store.save(pos)
    snap = Snapshot(broker_positions=[{}, {"no_symbol": 1},
                                      *({"symbol": s} for s in pos.symbols)])

    result = await reconcile.reconcile(store, snap, Journal(paths.journal), FakeMem(),
                                       Wiki(paths.wiki), None)

    assert result["phantom"] == [], "the junk rows hid the legs that were really there"


# ------------------------------------------------------------ book greeks


def test_a_calendar_position_is_skipped_rather_than_priced_as_riskless(paths, make_position):
    """`book_greeks` priced every leg at legs[0]'s days-to-expiry, so a
    calendar came out with delta, theta, vega and gamma all exactly 0.0 -
    against an honest -$31.83/day of theta and -$71.97 per vol point on a real
    one. Zero is the worst possible wrong answer: it reads as "this position
    adds nothing to the book", which is the one thing a calendar is not.

    `require_single_expiry` existed the whole time and was only ever called on
    the simulate path, which cannot even receive a per-leg expiry.
    """
    from trdrbot.analytics import book_greeks

    vertical = make_position(position_id="pos_vertical")
    calendar = make_position(position_id="pos_calendar", legs=[
        {"symbol": "SPY260904C00770000", "side": "buy", "qty": 1},
        {"symbol": "SPY261016C00770000", "side": "sell", "qty": 1},
    ])

    both = book_greeks([vertical, calendar], {"SPY": 770.0}, state_dir=paths.state,
                       equity=100_000.0)
    just_vertical = book_greeks([vertical], {"SPY": 770.0}, state_dir=paths.state,
                                equity=100_000.0)

    assert both["positions_skipped"] == 1, "the calendar was priced anyway"
    assert both["positions_priced"] == 1
    assert both["theta_dollars"] == just_vertical["theta_dollars"], \
        "the calendar contributed to the book total"


def test_a_partially_dated_leg_set_is_refused_not_assumed_shared():
    """The guard read a blank expiry as "assume shared", which is precisely the
    assumption it exists to refuse: the legs that DO carry a date are the
    evidence, and one of them differing is the case worth catching."""
    import pytest

    from trdrbot import optmath

    dated = optmath.Leg(right="C", strike=100.0, side="long", qty=1, price=1.0,
                        expiry="2026-09-04")
    blank = optmath.Leg(right="C", strike=105.0, side="short", qty=1, price=0.5)

    optmath.require_single_expiry([blank, blank])  # the simulate path: legitimate
    with pytest.raises(optmath.MultiExpiryError):
        optmath.require_single_expiry([dated, blank])


# ==================================================================== PILLAR-3
# CAPITAL-PROTECTION PATHS  (WU-4.6..4.7; issue I-42, notes/023-024)
#
# Driven as PATHS, tick by tick, because the failures here are sequences: a
# breach that should wait, a gap that should not, a bleed that never resolves.
# The relationship pinned is "a close happens when the world agrees it should",
# never a threshold level - the levels are the agent's own to write.
# Governed by docs/principles_testing.md - the four pillars.

from datetime import timedelta

from trdrbot import ids
from trdrbot.positions import Position


def _spread(**kw) -> Position:
    """A live credit spread carrying the entry state D-040 records: spot, IV and
    greeks. Built through the real dataclass, defaults overridable per test."""
    kw.setdefault("greeks_at_entry", {"delta_dollars": 4000.0, "gamma_shares": -7.0,
                                      "theta_dollars": 7.0, "vega_dollars": -40.0})
    kw.setdefault("entry_spot", 100.0)
    kw.setdefault("entry_iv", 0.25)
    kw.setdefault("opened", (ids.utc_now() - timedelta(days=1)).isoformat())
    kw.setdefault("exit_rules", [{"type": "stop_loss", "threshold": "-50%"}])
    kw.setdefault("expiry", "2099-01-30")
    return Position(
        position_id="p1", status="open", underlying="X",
        legs=[{"symbol": "A", "side": "sell", "qty": 1}], **kw)


def _mark(pnl_fraction: float, underlying: float) -> Snapshot:
    return Snapshot(
        broker_positions=[{"symbol": "A", "cost_basis": 1000.0,
                           "unrealized_pl": 1000.0 * pnl_fraction}],
        underlying_prices={"X": underlying})


def test_one_wide_print_no_longer_closes_a_healthy_spread(monkeypatch):
    """I-42: `position_mark`'s immediate_overshoot of 1.0 and its own comment
    about "-100%-of-credit on a HEALTHY spread" name the SAME number, so the
    single most common quote artifact skipped the debounce built for it and
    closed the position on one print, at the worst quote of the day."""
    pos, stats = _spread(), {}

    # -100% of net against a -50% stop is exactly overshoot 1.0 - and the
    # underlying has not moved at all, so nothing corroborates it.
    reason, why, _ = exit_rules.evaluate(pos, _mark(-1.00, 100.0), "2099-01-01",
                                         stats=stats)

    assert reason is None, why
    assert stats["mark_breach_suppressed"] == 1

    # ...and it is HELD, not ignored: a second print confirms it the ordinary
    # way, which is what the 2-of-3 debounce has always been for.
    reason, _why, _ = exit_rules.evaluate(pos, _mark(-1.00, 100.0), "2099-01-01")
    assert reason == "stop_loss"


def test_a_real_gap_still_closes_on_the_first_print():
    """The other half, and the reason corroboration is not just a delay: a gap
    moves the UNDERLYING, which prints tightly. Protection is unchanged."""
    pos, stats = _spread(), {}

    # Same -100% print, but the underlying has fallen through its own expected
    # move against a long-delta position.
    reason, why, _ = exit_rules.evaluate(pos, _mark(-1.00, 96.0), "2099-01-01",
                                         stats=stats)

    assert reason == "stop_loss"
    assert "underlying confirms" in why
    assert stats["mark_breach_confirmed"] == 1


def test_a_favourable_move_never_corroborates_a_loss_claim():
    """The artifact case that matters most: the mark says catastrophe while the
    underlying says the thesis is working. One of those two is lying, and it is
    not the one that prints continuously."""
    pos = _spread()

    reason, _why, _ = exit_rules.evaluate(pos, _mark(-1.00, 104.0), "2099-01-01")

    assert reason is None


def test_a_vol_structure_is_corroborated_by_a_move_either_way():
    """A condor is hurt by a large move in EITHER direction, so its
    corroboration is on magnitude - `dominant_risk` already knows which kind of
    bet the position is, from the greeks recorded at entry."""
    condor = _spread(greeks_at_entry={"delta_dollars": 50.0, "gamma_shares": -7.0,
                                      "theta_dollars": 7.0, "vega_dollars": -400.0})

    up, _w, _ = exit_rules.evaluate(condor, _mark(-1.00, 104.0), "2099-01-01")
    assert up == "stop_loss", "a big move up hurts a short-vol position too"

    condor.exit_state.clear()
    flat, _w2, _ = exit_rules.evaluate(condor, _mark(-1.00, 100.2), "2099-01-01")
    assert flat is None, "an unmoved underlying corroborates nothing"


def test_a_legacy_position_without_entry_state_debounces_rather_than_guessing():
    """None means "cannot judge", and cannot-judge takes the conservative path.
    Positions written before D-040 carry no entry greeks at all."""
    legacy = _spread(greeks_at_entry=None, entry_spot=None, entry_iv=None)

    first, _w, _ = exit_rules.evaluate(legacy, _mark(-1.00, 100.0), "2099-01-01")
    second, _w2, _ = exit_rules.evaluate(legacy, _mark(-1.00, 100.0), "2099-01-01")

    assert first is None and second == "stop_loss"


def test_an_underlying_stop_needs_no_corroborating():
    """The underlying IS the corroborator - it prints continuously and tightly,
    which is why thesis stops watch it. Gapping through the level stays
    immediate, and this is the regression that would catch over-applying the
    rule to every signal in the registry."""
    pos = _spread(exit_rules=[{"type": "underlying_stop", "direction": "below",
                               "level": 95.0}])

    reason, why, _ = exit_rules.evaluate(pos, _mark(0.0, 93.0), "2099-01-01")

    assert reason == "underlying_stop" and "decisive" in why


def _dte(days: int) -> str:
    """An expiry `days` from the market's today, so the test states DTE."""
    return (ids.market_today() + timedelta(days=days)).isoformat()


def test_a_position_with_no_time_stop_is_closed_at_the_gamma_wall():
    """G4/P5: a position pinned just above its stop bled to expiry with nothing
    ever firing. The implicit time stop bounds that with the mechanism the
    implicit deadline rule already uses - a default nobody has to remember."""
    pos = _spread(expiry=_dte(3))

    assert exit_rules.evaluate(pos, _mark(-0.49, 100.0), "2099-01-01")[0] is None
    pos.expiry = _dte(2)
    assert exit_rules.evaluate(pos, _mark(-0.49, 100.0), "2099-01-01")[0] is None

    pos.expiry = _dte(1)
    reason, why, _ = exit_rules.evaluate(pos, _mark(-0.49, 100.0), "2099-01-01")

    assert reason == "time_stop", why


def test_the_agents_own_time_stop_wins_including_a_deliberate_zero():
    """The implicit rule is a default, not a policy. Zero means "hold to
    expiry", and it must survive - a default that cannot be overridden is a
    guardrail, and this system deliberately has none."""
    pos = _spread(expiry=_dte(1), exit_rules=[
        {"type": "stop_loss", "threshold": "-50%"},
        {"type": "time_stop", "days_before_expiry": 0},
    ])

    assert exit_rules.evaluate(pos, _mark(-0.49, 100.0), "2099-01-01")[0] is None

    pos.expiry = _dte(0)
    assert exit_rules.evaluate(pos, _mark(-0.49, 100.0), "2099-01-01")[0] == "time_stop"


def test_an_unreadable_time_stop_does_not_disarm_the_implicit_one():
    """Absence-as-zero (D-038) wearing a different hat: a rule the evaluator
    cannot parse is a typo, not a commitment, and must not silently remove the
    default that would otherwise have applied."""
    pos = _spread(expiry=_dte(1), exit_rules=[
        {"type": "time_stop", "days_before_expiry": None},
    ])

    assert exit_rules.invalid_rules(pos) == 1, "precondition: the rule is unreadable"
    assert exit_rules.evaluate(pos, _mark(0.0, 100.0), "2099-01-01")[0] == "time_stop"


def test_a_position_with_no_expiry_is_unaffected():
    """An unobservable signal holds; it never fires blind."""
    pos = _spread(expiry="")

    assert exit_rules.evaluate(pos, _mark(-0.49, 100.0), "2099-01-01")[0] is None


# ---- PILLAR-3 continued: the structure itself going missing (WU-6.3, I-48)

def test_a_confirmed_leg_divergence_closes_at_deadline_priority():
    """I-48: the remainder of a broken spread can be an undefined-risk naked
    leg - the exact thing INV-19 refuses to create through our own close path,
    arriving via the broker instead. It outranks every rule about the intact
    position, because those rules describe something that no longer exists."""
    pos = _spread(leg_divergence_count=exit_rules.LEG_DIVERGENCE_CONFIRM,
                  exit_rules=[{"type": "profit_target", "threshold": "+50%"}])

    reason, why, _ = exit_rules.evaluate(pos, _mark(+2.00, 100.0), "2099-01-01")

    assert reason == "leg_divergence", why
    assert "consecutive" in why


def test_one_divergent_snapshot_is_not_enough_to_close():
    """A slow broker page or a snapshot taken mid-fill must not liquidate a
    healthy spread. The count IS the debounce."""
    pos = _spread(leg_divergence_count=1)

    assert exit_rules.evaluate(pos, _mark(0.0, 100.0), "2099-01-01")[0] is None


def test_an_intact_position_never_sees_the_rule():
    pos = _spread(leg_divergence_count=0)

    assert exit_rules.evaluate(pos, _mark(0.0, 100.0), "2099-01-01")[0] is None


async def test_reconcile_counts_divergence_and_the_exit_engine_closes_it(
    paths, make_position
):
    """The seam, across two ticks, driven by the real pair in the real order -
    reconcile counts, the registry closes. Producer-derived throughout: the
    position is written by PositionStore and re-read from disk between ticks,
    because "the counter persisted" is half of what is under test."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="open")
    store.save(pos)
    assert len(pos.symbols) > 1, "the fixture must be a multi-leg position"

    # The broker shows every leg but one - an early assignment's signature.
    partial = Snapshot(market_open=True, broker_positions=[
        {"symbol": s, "cost_basis": 500.0, "unrealized_pl": 0.0}
        for s in pos.symbols[:-1]
    ], broker_readable=True)
    closed_legs: list[str] = []
    closer = tools_for(close_position=lambda **kw: closed_legs.append(
        kw.get("symbol_or_asset_id")) or {"status": "ok"})

    # Tick 1: counted, not closed.
    await reconcile.reconcile(store, partial, journal, FakeMem(), Wiki(paths.wiki), None)
    triggered = await _run(store, partial, journal, paths, closer)

    assert store.load(pos.position_id).leg_divergence_count == 1
    assert triggered == [] and closed_legs == []

    # Tick 2: confirmed, and every leg the broker STILL SHOWS closes. The
    # vanished leg is deliberately not resubmitted (I-57): reconcile found it
    # missing moments earlier in this same tick, and closing what is already
    # gone can only turn a clean `submitted: true` into a false failure.
    # INV-19 is about never leaving a survivor behind, which this satisfies.
    await reconcile.reconcile(store, partial, journal, FakeMem(), Wiki(paths.wiki), None)
    triggered = await _run(store, partial, journal, paths, closer)

    assert triggered == [pos.position_id]
    assert store.load(pos.position_id).status == "closed"
    assert sorted(closed_legs) == sorted(pos.symbols[:-1]), "every surviving leg, no orphan"
    assert store.load(pos.position_id).close_reason == "leg_divergence"


async def test_a_transient_divergence_clears_and_leaves_a_trace(paths, make_position):
    """A glitch must un-count - and say so, so the confirm threshold can be
    tuned from the journal instead of from taste."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="open")
    store.save(pos)

    partial = Snapshot(broker_positions=[
        {"symbol": s, "cost_basis": 500.0, "unrealized_pl": 0.0}
        for s in pos.symbols[:-1]
    ], broker_readable=True)
    whole = Snapshot(broker_positions=[
        {"symbol": s, "cost_basis": 500.0, "unrealized_pl": 0.0} for s in pos.symbols
    ], broker_readable=True)

    await reconcile.reconcile(store, partial, journal, FakeMem(), Wiki(paths.wiki), None)
    assert store.load(pos.position_id).leg_divergence_count == 1

    await reconcile.reconcile(store, whole, journal, FakeMem(), Wiki(paths.wiki), None)

    assert store.load(pos.position_id).leg_divergence_count == 0
    findings = [r.get("finding") for r in journal_rows(journal, "reconciliation")]
    assert "leg_divergence_cleared" in findings
    assert store.load(pos.position_id).status == "open", "a glitch closes nothing"


# ---- PILLAR-3 continued: the close itself failing, and the clock (I-56, I-57)
#
# The incident: a calendar rule (deadline, or the implicit 1-DTE time stop)
# reads a DATE and nothing else, so it fires on the 00:15 tick of expiry day
# with the market shut. The close was submitted anyway, failed, and the
# position parked in `closing` - a status `run()` fetched and then skipped
# forever, so it lost its stop, its target and its retry in one move. On the
# live book that ended in an auto-exercised long put and ~1,300 short shares
# nothing was watching. Two fixes, tested here as one story.


async def test_a_deadline_trigger_holds_off_hours_and_fires_on_the_next_open_tick(
    paths, make_position
):
    """The trigger is real and must survive to the open, not be spent into a
    shut session. Detection is deliberately NOT gated - only the broker call."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="open", exit_rules=[])
    store.save(pos)
    closer = tools_for(close_position=lambda **kw: {"status": "ok"})

    shut = _underwater(pos.symbols, 0.0, market_open=False)
    triggered = await exit_rules.run(
        store, shut, closer, journal, "2020-01-01", FakeMem(), Wiki(paths.wiki),
        calibration=CalibrationStore(paths.state / "forecasts.jsonl"), verbose=False)

    assert triggered == [], "a close was submitted into a shut market"
    assert closer["close_position"].calls == []
    assert store.load(pos.position_id).status == "open", "parked in `closing` off-hours"

    # Same deadline, same position, market now open: it fires.
    triggered = await exit_rules.run(
        store, _underwater(pos.symbols, 0.0), closer, journal, "2020-01-01",
        FakeMem(), Wiki(paths.wiki),
        calibration=CalibrationStore(paths.state / "forecasts.jsonl"), verbose=False)

    assert triggered == [pos.position_id]
    assert store.load(pos.position_id).status == "closed"
    assert store.load(pos.position_id).close_reason == "deadline"


async def test_a_mark_breach_also_holds_off_hours(paths, make_position):
    """The gate is uniform, not calendar-only. A mark breach off-hours is
    reading a stale quote by definition - there is no session to price it."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="open", exit_rules=[
        {"type": "stop_loss", "basis": "position_mark", "threshold": "-20.0%"},
    ])
    store.save(pos)
    closer = tools_for(close_position=lambda **kw: {"status": "ok"})
    shut = _underwater(pos.symbols, -0.9, market_open=False)

    await _run(store, shut, journal, paths, closer)
    triggered = await _run(store, shut, journal, paths, closer)  # past the debounce

    assert triggered == [] and closer["close_position"].calls == []
    assert store.load(pos.position_id).status == "open"


async def test_a_failed_close_is_retried_not_abandoned(paths, make_position):
    """I-57, the incident this whole pass exists for. One failed leg used to
    strand the position in `closing`, which `run()` skipped forever - no stop,
    no target, no second attempt, and reconcile only notices once the legs are
    ALREADY gone. It is retried now, and finishes."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="open", exit_rules=[
        {"type": "stop_loss", "basis": "position_mark", "threshold": "-20.0%"},
    ])
    store.save(pos)
    snap = _underwater(pos.symbols, -0.9)

    attempts: list[str] = []

    def flaky(**kw: Any) -> Any:
        attempts.append(kw.get("symbol_or_asset_id"))
        if len(attempts) == 1:  # the first leg of the first attempt only
            raise RuntimeError("stdio transport closed: broken pipe")
        return {"status": "ok"}

    closer = tools_for(close_position=flaky)

    await _run(store, snap, journal, paths, closer)   # debounce
    await _run(store, snap, journal, paths, closer)   # fires, one leg fails

    stranded = store.load(pos.position_id)
    assert stranded.status == "closing", "the failed close should be visible as in-flight"
    assert journal_rows(journal, "exit")[-1]["submitted"] is False

    triggered = await _run(store, snap, journal, paths, closer)  # the retry

    assert triggered == [pos.position_id]
    assert store.load(pos.position_id).status == "closed"
    retry_row = journal_rows(journal, "exit")[-1]
    assert retry_row["retry"] is True and retry_row["submitted"] is True
    assert store.load(pos.position_id).close_reason == "stop_loss", \
        "the retry must finish the ORIGINAL decision, not re-derive a new one"


async def test_a_retry_only_reattempts_the_legs_the_broker_still_shows(
    paths, make_position
):
    """A close that half-succeeded leaves half a spread. The retry must finish
    the job without resubmitting the leg that already went - resubmitting it
    fails, which would flip `submitted` false forever and retry a position that
    is in fact almost closed."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="closing", close_reason="stop_loss")
    store.save(pos)
    survivor = pos.symbols[-1]

    # Leg one already closed on the previous tick; only the survivor is held.
    partial = Snapshot(market_open=True, broker_readable=True, broker_positions=[
        {"symbol": survivor, "cost_basis": 500.0, "unrealized_pl": -100.0},
    ])
    closed_legs: list[str] = []
    closer = tools_for(close_position=lambda **kw: closed_legs.append(
        kw.get("symbol_or_asset_id")) or {"status": "ok"})

    triggered = await _run(store, partial, journal, paths, closer)

    assert closed_legs == [survivor], "the vanished leg was resubmitted"
    assert triggered == [pos.position_id]
    assert store.load(pos.position_id).status == "closed"


async def test_a_vanished_leg_is_not_resubmitted_so_the_close_can_succeed_at_all(
    paths, make_position
):
    """The property that makes the retry loop terminate. A leg_divergence close
    is BY DEFINITION missing a leg, so a close of every recorded symbol always
    fails against a real broker - which, now that `closing` is retried, would
    retry forever and never resolve. Broker-truth filtering is what stops the
    fix from becoming an infinite loop."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="open")
    store.save(pos)
    gone, survivor = pos.symbols[0], pos.symbols[-1]

    partial = Snapshot(market_open=True, broker_readable=True, broker_positions=[
        {"symbol": survivor, "cost_basis": 500.0, "unrealized_pl": 0.0},
    ])

    def broker(**kw: Any) -> Any:
        symbol = kw.get("symbol_or_asset_id")
        if symbol == gone:  # what Alpaca does with a position you do not hold
            raise RuntimeError("position not found")
        return {"status": "ok"}

    closer = tools_for(close_position=broker)

    for _ in range(exit_rules.LEG_DIVERGENCE_CONFIRM):
        await reconcile.reconcile(store, partial, journal, FakeMem(), Wiki(paths.wiki), None)
        await _run(store, partial, journal, paths, closer)

    assert store.load(pos.position_id).status == "closed", \
        "the close never succeeded, so the position would retry forever"
    assert journal_rows(journal, "exit")[-1]["submitted"] is True


async def test_an_unreadable_broker_still_attempts_every_leg(paths, make_position):
    """The other half of the filter, and the I-55 lesson applied to it: when
    the holdings read FAILED, absence proves nothing. Skipping a leg on that
    evidence would leave real exposure unattended, while attempting one that is
    already gone merely errors - so a failed read attempts everything."""
    store, journal = PositionStore(paths.wiki), Journal(paths.journal)
    pos = make_position(status="closing", close_reason="deadline")
    store.save(pos)

    # market open, holdings unreadable: exactly what a dead MCP session returns.
    blind = Snapshot(market_open=True, broker_positions=[], broker_readable=False)
    closed_legs: list[str] = []
    closer = tools_for(close_position=lambda **kw: closed_legs.append(
        kw.get("symbol_or_asset_id")) or {"status": "ok"})

    await _run(store, blind, journal, paths, closer)

    assert sorted(closed_legs) == sorted(pos.symbols), \
        "a failed read silently skipped legs it could not see"
