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
    entry cost - built the way `position_pnl_pct` actually reads it, not the
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
    snap = _underwater(pos.symbols, -0.9)  # decisive: past 2x the -20% stop

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

    def explode(pos: Any, snap: Any, deadline: str) -> Any:
        if pos.position_id == "pos_bad":
            raise ValueError("unreadable debounce state")
        return real_evaluate(pos, snap, deadline)

    monkeypatch.setattr(exit_rules, "evaluate", explode)
    snap = _underwater(good.symbols, -0.9)

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
