"""The credit-assignment spine, tested by RUNNING it.

This path - reconcile -> learn -> elfmem, and attribution -> elfmem at horizon -
produced six decision records of bugs (D-056, D-057, D-058, D-059, D-072,
D-073), the densest cluster in the project. Until now it was policed entirely
by `inspect.getsource` string matches: eleven assertions about the TEXT of the
code, which a behaviour-preserving refactor breaks and a behaviour-changing
edit slips past.

These tests run the real stores (Journal, PositionStore, Wiki, CalibrationStore)
on tmp_path with a fake only at the elfmem boundary, and assert on what
actually reaches memory. That is the loop-smoke shape, and loop smoke is what
found two of the six bugs above in the first place.
"""

from __future__ import annotations

from typing import Any

from conftest import FakeMem, journal_rows, tools_for

from trdrbot import attribution, experiments, learn, reconcile
from trdrbot.analytics import Snapshot
from trdrbot.calibration import CalibrationStore
from trdrbot.journal import Journal
from trdrbot.positions import PositionStore
from trdrbot.wiki import Wiki


def _stores(paths: Any) -> tuple[PositionStore, Journal, Wiki, CalibrationStore]:
    return (
        PositionStore(paths.wiki),
        Journal(paths.journal),
        Wiki(paths.wiki),
        CalibrationStore(paths.state / "forecasts.jsonl"),
    )


# ---------------------------------------------------------------- resolution


async def test_a_close_with_known_pnl_resolves_calibration_and_records_the_lesson(
    paths, make_position, mem: FakeMem
):
    """The happy path of F3, end to end through the real stores."""
    store, journal, wiki, calib = _stores(paths)
    pos = make_position(status="closed", close_reason="external", last_pnl_pct=0.5)
    store.save(pos)
    calib.record(pos.position_id, probability=0.6, subject="SPY")

    await learn.on_resolution(pos, store, mem, wiki, journal, pnl_fraction=None, calibration=calib)

    # pnl_fraction=None fell back to the position's own last observation (D-058:
    # the same measured number failed to reach three consumers in a row).
    resolved = calib.resolved()
    assert len(resolved) == 1 and resolved[0].outcome is True

    reflection = journal_rows(journal, "reflection")
    assert len(reflection) == 1
    # The journal FIELD keeps its name: it is a wire format that 388
    # historical rows already carry (D-092 renamed code identifiers only).
    assert reflection[0]["pnl_pct"] == 0.5

    lesson = wiki.read("lessons")
    assert lesson is not None and pos.position_id in lesson.body

    # The mind's prediction is a binary claim and it genuinely resolves here.
    assert mem.mind_outcomes == [("mind_dec_1", True)]

    # Block credit does NOT happen here (D-091). It used to, at full weight, on
    # a money-derived 0.9/0.1 signal applied to the very blocks attribution
    # judges later from the verdict - so every position was credited twice and
    # the first credit followed the P&L.
    assert mem.credited == [], "blocks credited at close - attribution judges them later"
    assert reflection[0]["credit_deferred"] is True


async def test_a_close_with_no_pnl_anywhere_skips_credit_rather_than_guessing(
    paths, make_position, mem: FakeMem
):
    """An unknown P&L is not evidence. Skipping is the honest answer; guessing
    a sign would poison both calibration and credit."""
    store, journal, wiki, calib = _stores(paths)
    pos = make_position(status="closed", close_reason="external", last_pnl_pct=None)
    store.save(pos)
    calib.record(pos.position_id, probability=0.6, subject="SPY")

    await learn.on_resolution(pos, store, mem, wiki, journal, pnl_fraction=None, calibration=calib)

    assert mem.credited == []
    assert mem.mind_outcomes == []
    assert calib.resolved() == []  # unresolved, not resolved-as-a-loss
    assert journal_rows(journal, "reflection")[0]["credit_assigned"] is False


# ---------------------------------------------------------------- reconcile


async def test_reconcile_confirms_a_fill_and_remembers_the_thesis(
    paths, make_position, mem: FakeMem
):
    """F2: `opening` + the legs present at the broker = a real position."""
    store, journal, wiki, calib = _stores(paths)
    pos = make_position(status="opening")
    store.save(pos)
    snap = Snapshot(broker_positions=[{"symbol": s} for s in pos.symbols],
                    broker_readable=True)

    result = await reconcile.reconcile(store, snap, journal, mem, wiki, calib)

    assert result["filled"] == [pos.position_id]
    assert store.load(pos.position_id).status == "open"
    assert mem.remembered == [f"blk_{pos.position_id}"]
    # The thesis block is the decision's own subject matter, so it enters at
    # full credit weight regardless of what retrieval scored (D-073).
    reloaded = store.load(pos.position_id)
    assert reloaded.elfmem_blocks["attention"][f"blk_{pos.position_id}"] == 1.0


async def test_a_phantom_close_resolves_exactly_once(paths, make_position, mem: FakeMem):
    """INV-17 through the real transition guard: two detectors, one resolution.
    Double credit assignment is the failure this guard exists to prevent."""
    store, journal, wiki, calib = _stores(paths)
    pos = make_position(status="open", last_pnl_pct=0.2)
    store.save(pos)
    empty_broker = Snapshot(broker_positions=[], broker_readable=True)

    await reconcile.reconcile(store, empty_broker, journal, mem, wiki, calib)
    await reconcile.reconcile(store, empty_broker, journal, mem, wiki, calib)

    assert store.load(pos.position_id).status == "closed"
    assert store.load(pos.position_id).close_reason == "external"
    assert len(journal_rows(journal, "reflection")) == 1, "resolved twice - INV-17 breached"


async def test_a_pending_order_is_not_mistaken_for_a_vanished_position(
    paths, make_position, mem: FakeMem
):
    """A working limit order looks exactly like a phantom unless open orders
    are consulted - and killing a position that is merely waiting to fill is
    the expensive direction of that mistake."""
    store, journal, wiki, calib = _stores(paths)
    pos = make_position(status="opening")
    store.save(pos)
    snap = Snapshot(broker_positions=[],
                    open_orders=[{"legs": [{"symbol": s} for s in pos.symbols]}])

    await reconcile.reconcile(store, snap, journal, mem, wiki, calib)

    assert store.load(pos.position_id).status == "opening"


# ------------------------------------------- learning must never disarm risk


async def test_a_memory_failure_does_not_disarm_the_capital_protection_path(
    paths, make_position
):
    """The highest-consequence failure in the cluster, both halves.

    `learn.on_fill` / `on_resolution` were awaited bare inside `reconcile`,
    which runs BEFORE the exit-rule evaluator every tick. Any elfmem failure -
    a corrupt minds.json, a locked SQLite file - propagated out and that tick's
    stop-losses were never evaluated. A persistent one disarmed capital
    protection indefinitely, and `health` could not see it: its probes compare
    rows that EXIST, so a subsystem that stops emitting entirely moves no
    counter.
    """
    from trdrbot import exit_rules

    store, journal, wiki, calib = _stores(paths)
    broken = FakeMem(fail_with=RuntimeError("minds.json is corrupt"))

    # Half one: reconcile still resolves the phantom and still returns.
    gone = make_position(position_id="pos_gone", status="open", last_pnl_pct=0.2)
    store.save(gone)
    result = await reconcile.reconcile(store,
                                       Snapshot(broker_positions=[], broker_readable=True),
                                       journal, broken, wiki, calib)

    assert result["phantom"] == ["pos_gone"]
    assert store.load("pos_gone").status == "closed"
    errors = journal_rows(journal, "learn_error")
    assert [r["stage"] for r in errors] == ["on_resolution"]
    assert journal_rows(journal, "learn_run")[0]["errors"] == 1

    # Half two: a breached stop still closes, with memory still broken.
    breached = make_position(position_id="pos_stop", status="open",
                             exit_rules=[{"type": "stop_loss", "basis": "position_mark",
                                          "threshold": "-10.0%"}])
    store.save(breached)
    snap = Snapshot(broker_positions=[
        {"symbol": s, "cost_basis": 1000.0, "unrealized_pl": -900.0}
        for s in breached.symbols
    ])
    closer = tools_for(close_position=lambda **kw: {"status": "ok"})

    # Two ticks: this snapshot carries no underlying, so the mark breach takes
    # the ordinary debounce rather than the immediate path (WU-4.6). What is
    # under test - a breached stop still closes while memory is broken - is
    # unchanged, and the debounce path exercises MORE of the evaluator.
    await exit_rules.run(store, snap, closer, journal, "2099-01-01",
                         broken, wiki, calibration=calib, verbose=False)
    triggered = await exit_rules.run(store, snap, closer, journal, "2099-01-01",
                                     broken, wiki, calibration=calib, verbose=False)

    assert triggered == ["pos_stop"], "a broken memory stopped the stop-loss firing"
    assert len(closer["close_position"].calls) == len(breached.symbols)  # INV-19: all legs
    assert journal_rows(journal, "exit")[0]["close_reason"] == "stop_loss"


# -------------------------------------------------------------- attribution


def _snapshot_tool(price: float):
    return tools_for(get_stock_snapshot=lambda **kw: {"latestTrade": {"p": price}})


async def test_attribution_credits_by_verdict_and_weights_by_retrieval_similarity(
    paths, make_position, mem: FakeMem
):
    """A thesis that HELD and made money reinforces both, at the weight each
    block earned by how well it matched the query that produced the decision
    (D-073)."""
    store, journal, wiki, _ = _stores(paths)
    pos = make_position(status="closed", close_reason="external", last_pnl_pct=0.4,
                        thesis_horizon="2020-01-01")  # long past
    store.save(pos)

    out = await attribution.run(store, _snapshot_tool(700.0), mem, wiki, journal, verbose=False)

    assert out["attributed"] == 1
    assert store.load(pos.position_id).attribution == experiments.THESIS_RIGHT_EXPRESSION_RIGHT
    signal = experiments.ATTRIBUTION_SIGNAL[experiments.THESIS_RIGHT_EXPRESSION_RIGHT]
    credited = {bid: (sig, w) for bid, sig, w, _ in mem.credited}
    assert credited["blk_a"] == (signal, 0.93)   # credit_weight(0.9)
    assert credited["blk_b"] == (signal, 0.55)   # credit_weight(0.4)


async def test_a_lucky_win_teaches_nothing_at_all(paths, make_position, mem: FakeMem):
    """The row the whole design turns on: thesis wrong, profited anyway.

    P&L-based scoring treats this as strong confirmation. Here it must move
    NOTHING - and "nothing" means applying no signal, not applying 0.5.
    Measured with elfmem's own function (D-072): a 0.5 "neutral" signal moved
    the constitution -0.250 and moved an already-missed prediction +0.018.
    """
    store, journal, wiki, _ = _stores(paths)
    pos = make_position(status="closed", close_reason="external", last_pnl_pct=0.4,
                        thesis_horizon="2020-01-01")
    store.save(pos)

    # Spot ABOVE the 766 band ceiling: the view was wrong, the money was good.
    await attribution.run(store, _snapshot_tool(800.0), mem, wiki, journal, verbose=False)

    assert store.load(pos.position_id).attribution == experiments.THESIS_WRONG_PROFITED_ANYWAY
    assert mem.credited == [], "a lucky win must move no memory at all"
    assert journal_rows(journal, "attribution")[0]["signal"] is None


async def test_a_lucky_win_moves_no_memory_end_to_end(paths, make_position, mem: FakeMem):
    """The whole loop for the row the design turns on, in one test.

    Close (profit) -> attribution at horizon (view was WRONG) -> memory. The
    two halves each looked correct alone, which is why the double credit
    survived: `learn.on_resolution` credited on the money at close, and
    `ATTRIBUTION_SIGNAL` then said "apply nothing" at the horizon. Net effect
    on a lucky win was +0.9, i.e. strong reinforcement of a view that did not
    happen - the exact superstition P&L-based scoring produces and this system
    is built to avoid.
    """
    store, journal, wiki, calib = _stores(paths)
    pos = make_position(status="open", thesis_horizon="2020-01-01")
    store.save(pos)

    # 1. it closes profitably, outside our rules, the way both real ones have.
    pos.last_pnl_pct = 0.4
    store.transition(pos, "closed", close_reason="external")
    await learn.on_resolution(pos, store, mem, wiki, journal, pnl_fraction=0.4,
                              calibration=calib)

    # 2. the horizon arrives and the underlying is ABOVE the band: view wrong.
    await attribution.run(store, _snapshot_tool(800.0), mem, wiki, journal, verbose=False)

    assert store.load(pos.position_id).attribution == experiments.THESIS_WRONG_PROFITED_ANYWAY
    assert mem.credited == [], "a lucky win reinforced memory somewhere in the loop"
    # The mind's own prediction still resolves - it asked a different question
    # ("does this position work out") and the money is its honest answer.
    assert mem.mind_outcomes == [("mind_dec_1", True)]


async def test_attribution_without_a_price_says_so_rather_than_guessing(
    paths, make_position, mem: FakeMem
):
    """The `continue` that ran attribution dead for days while every log line
    read healthy: no journal entry meant "never ran" and "ran, found nothing"
    were the same observation (D-038)."""
    store, journal, wiki, _ = _stores(paths)
    pos = make_position(status="closed", last_pnl_pct=0.4, thesis_horizon="2020-01-01")
    store.save(pos)
    no_price = tools_for(get_stock_snapshot=lambda **kw: {},
                         get_stock_latest_trade=lambda **kw: {})

    out = await attribution.run(store, no_price, mem, wiki, journal, verbose=False)

    assert out == {"attributed": 0, "pending": 1, "skipped_no_price": 1}
    assert journal_rows(journal, "attribution_run")[0]["skipped_no_price"] == 1
    assert mem.credited == []


async def test_an_open_position_is_never_attributed(paths, make_position, mem: FakeMem):
    """Attribution waits for the horizon AND for the position to be over. A
    stop on day 2 of a 10-day thesis says nothing about the view."""
    store, journal, wiki, _ = _stores(paths)
    store.save(make_position(status="open", thesis_horizon="2020-01-01"))

    out = await attribution.run(store, _snapshot_tool(700.0), mem, wiki, journal, verbose=False)

    assert out["pending"] == 0
    assert mem.credited == []


async def test_an_unreadable_broker_closes_nothing(paths, make_position, mem: FakeMem):
    """I-55, found by WU-6.9's trace of a mid-tick MCP death.

    `broker_positions == []` means two irreconcilable things - the broker holds
    nothing, or we could not ask - and reconcile treated the first as proof.
    A dead MCP session therefore marked every live position `closed`/`external`,
    scored it through learning, and left the real exposure running with NO exit
    rules watching it, because a terminal position is no longer evaluated.

    The same absence-as-evidence shape as D-038 and I-46, one seam over: the
    fix is that an unreadable broker draws no conclusions from what is missing.
    """
    store, journal, wiki, calib = _stores(paths)
    live = make_position(position_id="pos_live", status="open")
    opening = make_position(position_id="pos_opening", status="opening")
    store.save(live)
    store.save(opening)

    # Exactly what `analytics.snapshot` returns when every MCP call failed.
    dead = Snapshot(broker_positions=[], broker_readable=False)

    result = await reconcile.reconcile(store, dead, journal, mem, wiki, calib)

    assert result["phantom"] == [], "a failed read was treated as proof of absence"
    assert store.load("pos_live").status == "open"
    assert store.load("pos_opening").status == "opening", "nor abandoned"
    assert journal_rows(journal, "reflection") == [], "and nothing was scored"


async def test_a_dead_mcp_session_degrades_one_tick_and_says_so(paths):
    """WU-6.9's pin: the containment story, asserted rather than assumed.

    A dead stdio transport raises out of `mcp_client.call`; `analytics.snapshot`
    catches per-call and degrades; the tick continues on what it has. What must
    NOT happen is silence - an empty snapshot that reads as a real one is the
    input that made I-55 dangerous.
    """
    from trdrbot import analytics

    class Dead:
        def __init__(self, name): self.name = name
        async def ainvoke(self, kwargs):
            raise ConnectionError("stdio transport closed: broken pipe")

    tools = {n: Dead(n) for n in
             ("get_clock", "get_account_info", "get_all_positions", "get_orders")}
    journal = Journal(paths.journal)

    snap = await analytics.snapshot(tools, journal=journal)

    assert snap.broker_readable is False, "a failed read must not look successful"
    assert snap.broker_positions == []
    # health.degraded leaves the row `check()` reads back, so a fail-open path
    # taken repeatedly becomes visible instead of looking like success.
    rows = journal_rows(journal, "degraded")
    assert any(r["subsystem"] == "analytics.positions" for r in rows)
