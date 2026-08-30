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


def _underwater(symbols: list[str], pnl_fraction: float) -> Snapshot:
    """A broker snapshot showing the position at `pnl_fraction` of its net
    entry cost - built the way `position_pnl_fraction` actually reads it, not the
    way a test would find convenient."""
    per_leg = 1000.0 / max(1, len(symbols))
    return Snapshot(broker_positions=[
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
