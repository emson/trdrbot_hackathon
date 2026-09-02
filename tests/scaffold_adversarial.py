"""Scaffold: ADVERSARIAL scenarios against the whole loop, offline.

    uv run python tests/scaffold_adversarial.py

NOT collected by pytest (D-079). Same world as scaffold_whole_system.py - a fake
broker the scenario controls, real copies of the return histories and the wiki,
and the REAL code for every deterministic stage - but every scenario here is an
attack on a seam rather than a happy path. A PASS means the attack LANDED: the
label states the defect, and the check asserts the code exhibits it. When a
defect is fixed its check flips to FAIL, which is the signal to move the row
into a pinned regression test.

  X1   a persistent wide option quote on an unmoved underlying closes a spread in two ticks
  X2   the frozen overnight mark saturates the debounce, so one print at the open closes
  X3   an unreadable account silently becomes $100,000 equity for sizing and the ladder
  X4   a close that has not filled is re-adopted as an orphan and scored twice
  X5   an order that never filled is attributed at its horizon and credits memory
  X6   one traded thesis enters calibration twice, with outcomes that can disagree
  X7   a forecast matures at 00:00 ET on its horizon date, 16h before that session closes
  X8   '---' inside a thesis claim truncates or destroys the position page
  X9   a lowercase OCC symbol is never matched to the broker: abandoned + orphan
  X10  mark_traded links a standalone forecast instead of the traded thesis
  X11  stop_loss_pct=-0.65 (a fraction) arms a -0.65% stop with no warning
  X12  (control) shared-leg close by quantity leaves the sibling intact
  X13  the sizing stash is never cleared: a second record inherits the wrong risk
  X14  a missing expiry blinds every calendar rule and the tool does not say so
  X15  record_position called twice for one fill: two pages, double risk, double scoring
  X16  crash between order and record: orphan adoption races the resume
  X17  one wide mark sets an equity high-water no fill can reach; the brake latches
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import FakeMem, FakeTool, days_out, occ  # noqa: E402

from trdrbot import (  # noqa: E402
    analytics,
    attribution,
    competence,
    exit_rules,
    ids,
    local_tools,
    reconcile,
    sizing,
)
from trdrbot import config as config_mod  # noqa: E402
from trdrbot import ledger as ledger_mod  # noqa: E402
from trdrbot.calibration import CalibrationStore  # noqa: E402
from trdrbot.journal import Journal  # noqa: E402
from trdrbot.positions import PositionStore  # noqa: E402
from trdrbot.wiki import Wiki  # noqa: E402

FAIL: list[str] = []
NOTES: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'PASS' if ok else '** FAIL **'}  {label}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def h(t: str) -> None:
    print(f"\n{'=' * 96}\n{t}\n{'=' * 96}")


def rows(journal: Journal, kind: str) -> list[dict[str, Any]]:
    return [r for r in journal.read() if r.get("kind") == kind]


# ============================================================== the world
class Broker:
    """Shaped exactly as analytics.snapshot / reconcile / exit_rules read the real one."""

    def __init__(self, equity: float = 104_060.0) -> None:
        self.equity = equity
        self.prices: dict[str, float] = {"SPY": 640.0, "NVDA": 120.0, "XLE": 90.0}
        self.prev_closes: dict[str, float] = dict(self.prices)
        self.positions: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.market_open = True
        self.readable = True
        self.account_readable = True
        self.orders_readable = True
        #: When True, close_position leaves the legs in place and parks a
        #: working order instead - a market close that has not filled yet.
        self.close_is_slow = False
        self.closed: list[tuple[str, str | None]] = []
        self.placed: list[dict[str, Any]] = []

    def get_clock(self, **_: Any) -> dict[str, Any]:
        return {"is_open": self.market_open}

    def get_account_info(self, **_: Any) -> dict[str, Any]:
        if not self.account_readable:
            raise RuntimeError("simulated account outage")
        return {"equity": self.equity, "cash": self.equity, "buying_power": self.equity}

    def get_all_positions(self, **_: Any) -> list[dict[str, Any]]:
        if not self.readable:
            raise RuntimeError("simulated broker outage")
        return [dict(p) for p in self.positions]

    def get_orders(self, **_: Any) -> list[dict[str, Any]]:
        if not self.orders_readable:
            raise RuntimeError("simulated order-book outage")
        return list(self.orders)

    def get_stock_latest_trade(self, symbols: str = "", **_: Any) -> dict[str, Any]:
        return {"trades": {symbols: {"p": self.prices.get(symbols, 0.0),
                                     "t": ids.utc_now().isoformat()}}}

    def get_stock_snapshot(self, symbols: str = "", **_: Any) -> dict[str, Any]:
        return {symbols: {
            "latestTrade": {"p": self.prices.get(symbols, 0.0), "t": ids.utc_now().isoformat()},
            "prevDailyBar": {"c": self.prev_closes.get(symbols, 0.0)},
        }}

    def close_position(self, symbol_or_asset_id: str = "", qty: str | None = None,
                       **_: Any) -> dict[str, Any]:
        self.closed.append((symbol_or_asset_id, qty))
        if self.close_is_slow:
            self.orders.append({"symbol": symbol_or_asset_id, "side": "sell", "qty": qty or "all",
                                "status": "accepted"})
            return {"status": "accepted", "symbol": symbol_or_asset_id}
        self._remove(symbol_or_asset_id, qty)
        return {"status": "accepted", "symbol": symbol_or_asset_id}

    def _remove(self, symbol: str, qty: str | None) -> None:
        out = []
        for p in self.positions:
            if p["symbol"] != symbol:
                out.append(p)
                continue
            if qty is None:
                continue  # whole aggregate gone
            q = int(qty)
            sign = 1 if p["qty"] > 0 else -1
            left = abs(p["qty"]) - q
            if left > 0:
                per = p["cost_basis"] / p["qty"]
                p = dict(p, qty=sign * left, cost_basis=per * sign * left)
                out.append(p)
        self.positions = out

    def settle_working_closes(self) -> None:
        for o in list(self.orders):
            q = None if o["qty"] == "all" else o["qty"]
            self._remove(o["symbol"], q)
        self.orders = []

    def place_option_order(self, **kw: Any) -> dict[str, Any]:
        self.placed.append(kw)
        for leg in kw.get("legs", []):
            side = 1 if leg.get("side", "buy") == "buy" else -1
            q = int(leg.get("qty", 1))
            self._add(leg["symbol"], side * q, side * float(leg.get("price", 1.0)) * 100 * q)
        return {"status": "filled", "id": f"ord_{len(self.placed)}"}

    def _add(self, symbol: str, qty: int, cost: float) -> None:
        # Alpaca AGGREGATES by symbol (D-111).
        for p in self.positions:
            if p["symbol"] == symbol:
                p["qty"] += qty
                p["cost_basis"] += cost
                return
        self.positions.append({"symbol": symbol, "qty": qty, "cost_basis": cost,
                               "unrealized_pl": 0.0})

    def get_news(self, **_: Any) -> dict[str, Any]:
        return {"news": []}

    def tools(self) -> dict[str, FakeTool]:
        names = ("get_clock", "get_account_info", "get_all_positions", "get_orders",
                 "get_stock_latest_trade", "get_stock_snapshot", "close_position",
                 "place_option_order", "get_news")
        return {n: FakeTool(n, getattr(self, n)) for n in names}

    def mark(self, symbol_prefix: str, pnl_fraction: float) -> None:
        for p in self.positions:
            if p["symbol"].startswith(symbol_prefix):
                p["unrealized_pl"] = p["cost_basis"] * pnl_fraction


class World:
    def __init__(self, tag: str, appetite: float = 1.75) -> None:
        self.root = ROOT / "data" / f".scaffold_adv_{tag}"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.paths = config_mod.Paths.build(self.root)
        self.paths.ensure()
        shutil.copytree(ROOT / "data" / "state" / "returns", self.paths.state / "returns")
        shutil.rmtree(self.paths.wiki)
        shutil.copytree(ROOT / "data" / "wiki", self.paths.wiki)
        for f in ("model_calibration.json",):
            if (ROOT / "data" / "state" / f).exists():
                shutil.copy(ROOT / "data" / "state" / f, self.paths.state / f)
        self.broker = Broker()
        self.tools = self.broker.tools()
        self.journal = Journal(self.paths.journal)
        self.store = PositionStore(self.paths.wiki)
        for p in self.store.all():
            p.path.unlink()
        # a clean lessons page so lesson checks are about THIS world
        lp = self.paths.wiki / "lessons.md"
        if lp.exists():
            lp.unlink()
        self.wiki = Wiki(self.paths.wiki)
        self.ledger = ledger_mod.Ledger(self.paths.state / "ledger.jsonl")
        self.calib = CalibrationStore(self.paths.state / "forecasts.jsonl")
        self.mem = FakeMem()
        self.config = SimpleNamespace(
            paths=self.paths, deadline=None, risk_appetite=appetite,
            watchlist=["SPY"], research_universe=["SPY", "NVDA", "XLE"],
            events=[], polymarket_queries=[], coach={"enabled": False}, pricing={},
            max_retries=3, model_chain=lambda role="decide": ["scripted"],
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    async def snapshot(self) -> analytics.Snapshot:
        names = sorted({p.underlying for p in self.store.open_positions() if p.underlying}
                       | set(self.config.research_universe))
        return await analytics.snapshot(self.tools, underlyings=names, journal=self.journal)

    async def fast_path(self, quiet: bool = True) -> tuple[analytics.Snapshot, dict[str, Any], list[str]]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf) if quiet else contextlib.nullcontext():
            snap = await self.snapshot()
            recon = await reconcile.reconcile(self.store, snap, self.journal, self.mem,
                                              self.wiki, self.calib)
            closed = await exit_rules.run(self.store, snap, self.tools, self.journal,
                                          self.config.deadline, self.mem, self.wiki,
                                          calibration=self.calib, verbose=False)
        self.last_stdout = buf.getvalue()
        return snap, recon, closed

    def posture(self, snap: analytics.Snapshot, equity: float | None = None) -> competence.Competence:
        cal = self.calib.score(ledger_mod.as_forecasts(self.ledger.resolved()))
        eq = equity if equity is not None else (snap.equity or 0.0)
        hw = competence.update_high_water(self.paths.state, eq, self.journal)
        return competence.assess(
            resolved=cal.n, reliability=cal.reliability, positions=self.store.all(),
            equity=eq, high_water=hw, effective=cal.n_eff, appetite=self.config.risk_appetite)

    async def decide_open(self, *, underlying: str, spot: float, expiry: str,
                          long_k: float, short_k: float, stated: float, horizon: str,
                          thesis_claim: str | None = None, place: bool = True,
                          record_kwargs: dict[str, Any] | None = None,
                          symbol_mangle=None, between=None, confirm: bool = True,
                          qty_override: int | None = None) -> dict[str, Any]:
        snap = await self.snapshot()
        posture = self.posture(snap)
        open_risk = sum(p.max_loss_usd or 0.0 for p in self.store.open_positions())
        by_name: dict[str, float] = {}
        for p in self.store.open_positions():
            by_name[p.underlying.upper()] = by_name.get(p.underlying.upper(), 0.0) + (p.max_loss_usd or 0.0)
        shared = local_tools.SharedContext()
        sim = local_tools.build_simulate_experiments(shared, self.paths.state, ledger=self.ledger)
        size = local_tools.build_size_position(
            self.calib, snap.equity or 0.0, open_risk_usd=open_risk,
            open_risk_by_underlying=by_name, shared=shared, posture=posture,
            extra_forecasts=ledger_mod.as_forecasts(self.ledger.resolved()), journal=self.journal)
        forecast = local_tools.build_record_forecast(self.ledger, self.paths.state)
        rec = local_tools.build_record_position(
            self.store, "dec_sim", elfmem_blocks={"attention": {"blk_a": 0.9, "blk_b": 0.4}},
            generated_by="sim", calibration=self.calib, sources=[], shared=shared,
            ledger=self.ledger, journal=self.journal)
        legs = [{"symbol": occ(underlying, expiry, "P", long_k), "side": "long", "qty": 1,
                 "right": "P", "strike": long_k, "price": 3.0, "expiry": expiry},
                {"symbol": occ(underlying, expiry, "P", short_k), "side": "short", "qty": 1,
                 "right": "P", "strike": short_k, "price": 1.2, "expiry": expiry}]
        dte = (date.fromisoformat(expiry) - ids.today()).days
        claim = thesis_claim or f"{underlying} falls to {short_k} by {horizon}"
        sim_out = await sim.ainvoke({
            "thesis_claim": claim, "underlying": underlying, "horizon": horizon,
            "drift_pct": -1.5, "spot": spot, "iv_pct": 18.0, "days_to_expiry": dte,
            "candidates": [{"name": "bear_put_spread", "legs": legs},
                           {"name": "long_put", "legs": [dict(legs[0])]}],
            "band_high": long_k,
        })
        if between is not None:
            await between(forecast)
        st = shared.structures[0] if shared.structures else None
        mp = float(getattr(st, "max_profit", 0.0) or 0.0) if st else 180.0
        ml = float(getattr(st, "max_loss", 0.0) or 0.0) if st else -180.0
        size_out = await size.ainvoke({"stated_confidence": stated, "max_profit": mp,
                                       "max_loss": ml, "underlying": underlying,
                                       "structure_name": "bear_put_spread"})
        qty = int(getattr(shared.sizing, "contracts", 0) or 0) if shared.sizing else 0
        qty = qty_override or qty or 1
        order_legs = [{"symbol": l["symbol"], "side": "buy" if l["side"] == "long" else "sell",
                       "qty": qty, "price": l["price"]} for l in legs]
        placed = self.broker.place_option_order(legs=order_legs, underlying=underlying) if place else None
        rec_legs = [dict(l) for l in order_legs]
        if symbol_mangle:
            for l in rec_legs:
                l["symbol"] = symbol_mangle(l["symbol"])
        kw = {"underlying": underlying, "strategy": "bear_put_spread", "legs": rec_legs,
              "thesis": claim, "confidence": stated, "expiry": expiry,
              "stop_loss_pct": -65.0, "profit_target_pct": 140.0,
              "underlying_stop_above": spot * 1.03}
        kw.update(record_kwargs or {})
        rec_out = await rec.ainvoke(kw)
        if confirm:
            await self.fast_path()
        return {"sim": str(sim_out), "size": str(size_out), "placed": placed,
                "record": str(rec_out), "posture": posture, "shared": shared, "qty": qty}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@contextlib.contextmanager
def clock_at(et_str: str):
    """Freeze ids.utc_now / ids.market_today / ids.today at an ET wall-clock time."""
    from zoneinfo import ZoneInfo
    et = datetime.fromisoformat(et_str).replace(tzinfo=ZoneInfo("America/New_York"))
    utc = et.astimezone(UTC)
    saved = (ids.utc_now, ids.market_today, ids.today)
    ids.utc_now = lambda: utc
    ids.market_today = lambda: et.date()
    ids.today = lambda: utc.date()
    try:
        yield
    finally:
        ids.utc_now, ids.market_today, ids.today = saved


# ============================================================== X1
h("X1  a PERSISTENT wide option quote on an UNMOVED underlying (the I-42 artifact, held for 10 min)")
w = World("x1")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon))
    # the underlying has not moved at all this session
    w.broker.prev_closes["SPY"] = spot
    w.broker.mark("SPY", -0.70)                 # stop is -65%; a wide quote prints -70%
    _, _, c1 = run(w.fast_path())
    _, _, c2 = run(w.fast_path())
    check(c1 == [], "tick 1: the artifact print holds (debounce armed)")
    check(c2 != [], "tick 2: the SAME persistent print closes the position - no corroboration on the debounce path",
          f"closed={c2}; SPY moved {w.broker.prices['SPY'] - w.broker.prev_closes['SPY']:+.2f} this session")
    xr = rows(w.journal, "exit")[-1] if rows(w.journal, "exit") else {}
    print(f"  exit row: {xr.get('explanation')}")
    # and the DECISIVE variant: a -140% print (overshoot > 1.0) on an unmoved underlying
    w2 = World("x1b")
    run(w2.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                       short_k=round(spot - 12), stated=0.42, horizon=horizon))
    w2.broker.prev_closes["SPY"] = spot
    w2.broker.mark("SPY", -1.40)
    _, _, d1 = run(w2.fast_path())
    _, _, d2 = run(w2.fast_path())
    hb = rows(w2.journal, "exit_run")
    check(d1 == [], "decisive print, tick 1: suppressed by corroboration (underlying unmoved)",
          f"suppressed={hb[-2].get('mark_breach_suppressed') if len(hb) > 1 else '?'}")
    check(d2 != [], "decisive print, tick 2: closes anyway via the 2-of-3 debounce - corroboration bought ONE tick",
          f"closed={d2}")
    w2.cleanup()
    NOTES.append("X1: a wide quote that persists for two ticks closes a healthy spread on an unmoved "
                 "underlying; corroboration guards only the immediate path, so it delays by one tick.")
finally:
    w.cleanup()

# ============================================================== X2
h("X2  overnight: the frozen closing mark feeds the debounce ~30 times, so ONE print at the open closes")
w = World("x2")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon))
    w.broker.prev_closes["SPY"] = spot
    pos = w.store.open_positions()[0]
    # last in-session tick: a wide closing mark, one breach on the history
    w.broker.mark("SPY", -0.70)
    _, _, c = run(w.fast_path())
    check(c == [], "15:59 wide close mark: one breach, holds")
    w.broker.market_open = False
    for _ in range(6):                         # overnight housekeeping ticks: same frozen mark
        _, _, c = run(w.fast_path())
    pos = w.store.load(pos.position_id)
    hist = pos.exit_state.get("position_mark:below:-0.65")
    check(c == [] and pos.status == "open", "off-hours: nothing submitted", f"status={pos.status}")
    check(hist == [True, True, True], "but the debounce window is now SATURATED by the frozen mark",
          f"history={hist}")
    # at the open the quote normalises: nothing fires (correct)
    w.broker.market_open = True
    w.broker.mark("SPY", -0.30)
    _, _, c = run(w.fast_path())
    check(c == [], "09:30 healthy mark: holds")
    pos = w.store.load(pos.position_id)
    hist = pos.exit_state.get("position_mark:below:-0.65")
    print(f"  history after healthy open print: {hist}")
    # a single wide print 5 min later, underlying still unmoved
    w.broker.mark("SPY", -0.70)
    _, _, c = run(w.fast_path())
    check(c != [], "09:35 ONE wide print closes the position: the overnight saturation counts as confirmation",
          f"closed={c}, history before={hist}")
    # control: the same single print with a clean in-session history holds
    w3 = World("x2b")
    run(w3.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                       short_k=round(spot - 12), stated=0.42, horizon=horizon))
    w3.broker.prev_closes["SPY"] = spot
    w3.broker.mark("SPY", -0.30)
    run(w3.fast_path())
    run(w3.fast_path())
    w3.broker.mark("SPY", -0.70)
    _, _, c3 = run(w3.fast_path())
    check(c3 == [], "CONTROL: the same single print on a clean history holds", f"closed={c3}")
    w3.cleanup()
    NOTES.append("X2: exit_rules.evaluate appends to the debounce history on every closed-market tick "
                 "against a frozen mark, so the 2-of-3 rule is pre-satisfied at the open.")
finally:
    w.cleanup()

# ============================================================== X3
h("X3  the account read fails: equity silently becomes $100,000 for sizing, the ladder and the idle ladder")
w = World("x3")
try:
    hw_path = competence.high_water_path(w.paths.state)
    hw_path.write_text(json.dumps({"high_water": 104_060.0}))
    w.broker.equity = 92_000.0          # a real 11.6% drawdown -> should demote to EXPLORE
    w.broker.account_readable = False
    snap = run(w.snapshot())
    check(snap.equity == 0.0, "snapshot.equity reads 0.0 when the account call fails", f"{snap.equity}")
    deg = [r for r in rows(w.journal, "degraded") if "account" in str(r)]
    check(len(deg) == 0, "and NO `degraded` row is written for it (positions/orders/clock all get one)",
          f"degraded rows mentioning account: {len(deg)}")
    # exactly what tick._run_tick does next:
    equity_now = snap.equity or 100000.0
    hw = competence.update_high_water(w.paths.state, equity_now, w.journal)
    cal = w.calib.score([])
    p_fallback = competence.assess(resolved=40, reliability=0.02,
                                   positions=[SimpleNamespace(attribution="thesis_right_expression_right")] * 10,
                                   equity=equity_now, high_water=hw, appetite=1.75)
    p_truth = competence.assess(resolved=40, reliability=0.02,
                                positions=[SimpleNamespace(attribution="thesis_right_expression_right")] * 10,
                                equity=92_000.0, high_water=104_060.0, appetite=1.75)
    check(p_truth.tier == "explore" and p_fallback.tier != "explore",
          "a real 11.6% drawdown that should demote to EXPLORE is read as 3.9% and the tier holds",
          f"truth={p_truth.tier} ({p_truth.drawdown:.1%})  with fallback={p_fallback.tier} ({p_fallback.drawdown:.1%})")
    d = sizing.size_position(equity=equity_now, stated_confidence=0.6, max_profit=300.0, max_loss=-200.0,
                             calibration=cal, posture=p_fallback, underlying="SPY", payoff_ratio=1.5)
    d2 = sizing.size_position(equity=92_000.0, stated_confidence=0.6, max_profit=300.0, max_loss=-200.0,
                              calibration=cal, posture=p_truth, underlying="SPY", payoff_ratio=1.5)
    check(d.contracts > d2.contracts, "and the next trade is sized on $100k at the un-demoted tier",
          f"{d.contracts} contracts vs {d2.contracts} on the truth")
    NOTES.append("X3: tick.py `equity_now = snap.equity or 100000.0` substitutes a constant when the "
                 "account read fails; nothing journals it; drawdown protection and every cap read it.")
finally:
    w.cleanup()

# ============================================================== X4
h("X4  a close that has not filled yet: the terminal page stops claiming its legs, so reconcile ADOPTS them")
w = World("x4")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    out = run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                            short_k=round(spot - 12), stated=0.42, horizon=horizon))
    pid = w.store.open_positions()[0].position_id
    w.broker.close_is_slow = True            # market close accepted, not yet filled
    w.broker.prices["SPY"] = spot + 6.0      # adverse gap for a bear put spread -> corroborates
    w.broker.mark("SPY", -1.40)
    _, _, c = run(w.fast_path())
    check(c == [pid], "the stop fires and the close is ACCEPTED (status -> closed)",
          f"status={w.store.load(pid).status}, working orders={len(w.broker.orders)}")
    snap, recon, _ = run(w.fast_path())      # next tick: legs still at the broker, close working
    orphans = [p for p in w.store.all() if p.provenance == "unknown"]
    check(len(orphans) == 1, "next tick: the SAME legs are adopted as an orphan position with no thesis",
          f"orphans={[p.position_id for p in orphans]} recon={reconcile.summarise(recon)}")
    w.broker.settle_working_closes()          # the close fills
    run(w.fast_path())
    o = w.store.load(orphans[0].position_id) if orphans else None
    check(bool(o and o.status == "closed" and o.close_reason == "external"),
          "then the orphan goes phantom -> closed/external and is SCORED as a resolution",
          f"orphan status={o.status if o else '-'} reason={o.close_reason if o else '-'}")
    refl = [r for r in rows(w.journal, "reflection") if r["position_id"] == (o.position_id if o else "")]
    lessons = w.wiki.read("lessons")
    check(bool(refl) and bool(lessons and o and f"## {o.position_id}" in lessons.body),
          "a `reflection` row and a lessons.md entry now exist for a position that never existed",
          f"reflection rows={len(refl)}")
    # and the real position's own learning ran too -> two resolutions for one trade
    real_refl = [r for r in rows(w.journal, "reflection") if r["position_id"] == pid]
    check(len(real_refl) == 1 and len(refl) == 1, "two reflections for one trade", "")
    NOTES.append("X4: reconcile._adopt_orphans ignores working orders and terminal pages; a close that "
                 "takes >1 tick to fill re-adopts the legs as an orphan and scores a phantom resolution.")
finally:
    w.cleanup()

# ============================================================== X5
h("X5  an order that NEVER FILLED is attributed at its horizon and credits memory")
w = World("x5")
try:
    expiry, horizon = days_out(7), days_out(-1)   # horizon already passed by the time we look
    spot = w.broker.prices["SPY"]
    with clock_at(f"{days_out(-3)}T14:00"):       # recorded three days ago
        run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                          short_k=round(spot - 12), stated=0.42, horizon=horizon, place=False,
                          confirm=False))
    pid = w.store.open_positions()[0].position_id
    snap, recon, _ = run(w.fast_path())           # no fill, no working order -> abandoned
    p = w.store.load(pid)
    check(p.status == "abandoned" and p.close_reason == "never_filled", "reconcile marks it abandoned",
          f"{p.status}/{p.close_reason}")
    pend = attribution.pending(w.store)
    check(any(x.position_id == pid for x in pend), "attribution.pending() lists the ABANDONED position")
    r = run(attribution.run(w.store, w.tools, w.mem, w.wiki, w.journal, verbose=False))
    p = w.store.load(pid)
    check(p.attribution not in ("", "unscoreable"),
          "it receives a real verdict - as if a trade had happened", f"verdict={p.attribution}")
    check(len(w.mem.credited) > 0, "and its recalled memory blocks are CREDITED on that verdict",
          f"credits={[(b, s, wt) for b, s, wt, _ in w.mem.credited]}")
    rate, n = competence.attributable_rate(w.store.all())
    check(n == 1, "and it counts toward the attributable rate that gates the size ladder",
          f"rate={rate} over {n} verdict(s)")
    NOTES.append("X5: attribution.pending() admits every non-active status including `abandoned`; "
                 "profited falls back to close_reason, so a never-filled order becomes a scored loss.")
finally:
    w.cleanup()

# ============================================================== X6
h("X6  one traded thesis, two calibration rows: the position forecast AND the ledger row, same id")
w = World("x6")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon))
    pid = w.store.open_positions()[0].position_id
    # the stop fires day 2 (corroborated gap), position closes at a loss
    w.broker.prices["SPY"] = spot + 6.0
    w.broker.mark("SPY", -1.40)
    _, _, c = run(w.fast_path())
    check(c == [pid], "the stop closed it at a loss")
    # the horizon arrives and the band (price <= long_k) turns out to HOLD
    traded = [e for e in w.ledger.all() if e.traded]
    w.ledger.resolve(traded[0].id, spot - 8.0, ids.utc_now().isoformat())
    fcs = w.calib.resolved() + ledger_mod.as_forecasts(w.ledger.resolved())
    same = [f for f in fcs if f.position_id == pid]
    cal = w.calib.score(ledger_mod.as_forecasts(w.ledger.resolved()))
    check(len(same) == 2, "calibration now carries TWO forecasts with this position_id",
          f"probabilities={[f.probability for f in same]} outcomes={[f.outcome for f in same]}")
    check(cal.n == 2, "n=2 from one stated number on one trade", f"n={cal.n}, base_rate={cal.base_rate}")
    check(same[0].outcome != same[1].outcome,
          "and they DISAGREE: P(closes profitable) resolved False, the same number scored as P(band holds) resolved True")
    NOTES.append("X6: record_position writes calibration.record(pos_id, confidence) AND "
                 "ledger.mark_traded(probability=confidence); CalibrationStore.score concatenates both.")
finally:
    w.cleanup()

# ============================================================== X7
h("X7  D-107's other half: a forecast MATURES at 00:00 ET on its horizon date, 16 hours before that session closes")
w = World("x7")
try:
    hz = "2026-09-10"
    e = w.ledger.register(kind="standalone", underlying="SPY", claim="c", probability=0.6,
                          horizon=hz, band_low=600.0, band_high=700.0)
    with clock_at("2026-09-09T20:05"):
        check(not e.matured(), "20:05 ET the evening before: NOT matured (D-107 fixed this)")
    with clock_at("2026-09-10T00:15"):
        check(e.matured(), "00:15 ET on the horizon date: MATURED - resolved by the first overnight housekeeping tick",
              f"matured={e.matured()} against ids.market_today()={ids.market_today()}")
        due = w.ledger.matured_unresolved()
        check(e in due, "matured_unresolved() hands it to the resolver, whose `_spot` is the previous close")
        pos = SimpleNamespace(thesis_horizon=hz)
        check(attribution._horizon_passed(pos), "attribution._horizon_passed agrees: the position is attributed at 00:15 too")
    NOTES.append("X7: Entry.matured() and attribution._horizon_passed compare the horizon to the ET DATE, "
                 "which is true from midnight; the docstring promises 'the horizon's SESSION has ended'.")
finally:
    w.cleanup()

# ============================================================== X8
h("X8  '---' inside the thesis claim: the position page is cut at the wrong place")
for tag, claim, mode in (("x8a", "SPY fades --- payrolls Friday --- into 628", "truncated"),
                         ("x8b", "SPY fades into payrolls\n--- invalidation: a close above 645", "unreadable")):
    w = World(tag)
    try:
        expiry, horizon = days_out(7), days_out(3)
        spot = w.broker.prices["SPY"]
        run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                          short_k=round(spot - 12), stated=0.42, horizon=horizon,
                          thesis_claim=claim, confirm=False))
        pages = list(w.store.dir.glob("*.md"))
        on_disk = pages[0].read_text()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loaded = w.store.all()
        lp = loaded[0] if loaded else None
        if mode == "truncated":
            check(lp is not None and "thesis_horizon:" in on_disk and not lp.thesis_horizon and lp.thesis_band_high is None,
                  f"[{tag}] inline ' --- ': page loads, but thesis_horizon/bands/attribution AFTER the claim are silently lost",
                  f"loaded horizon={lp.thesis_horizon!r} band_high={lp.thesis_band_high!r} claim={lp.thesis_claim!r}" if lp else "no position loaded")
            r = run(attribution.run(w.store, w.tools, w.mem, w.wiki, w.journal, verbose=False))
        else:
            check(lp is None, f"[{tag}] a claim line starting '---': the page is UNREADABLE and the position VANISHES",
                  buf.getvalue().strip()[:110])
            snap, recon, _ = run(w.fast_path())
            orphans = [p for p in w.store.all() if p.provenance == "unknown"]
            check(len(orphans) == 1, f"[{tag}] reconcile adopts the live legs as an ORPHAN: thesis, stops and sizing gone",
                  f"recon={reconcile.summarise(recon)}")
    finally:
        w.cleanup()
NOTES.append("X8: PositionStore._parse splits the whole file on '---' (maxsplit=2) regardless of line position; "
             "yaml.safe_dump emits a claim containing ' --- ' as a plain scalar.")

# ============================================================== X9
h("X9  the model writes a lowercase OCC symbol: the position is never matched to the broker")
w = World("x9")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon,
                      symbol_mangle=lambda s: s.lower(), confirm=False))
    pid = w.store.open_positions()[0].position_id
    snap, recon, _ = run(w.fast_path())
    p = w.store.load(pid)
    orphans = [q for q in w.store.all() if q.provenance == "unknown"]
    check(p.status == "abandoned", "the filled position is marked ABANDONED (never_filled)", f"{p.status}")
    check(len(orphans) == 1, "and the real legs are adopted as an orphan with no thesis and no stops",
          f"recon={reconcile.summarise(recon)}")
    NOTES.append("X9: record_position stores leg symbols verbatim; reconcile/exit_rules match by exact "
                 "string against the broker's uppercase OCC. parse_occ upper-cases, the matcher does not.")
finally:
    w.cleanup()

# ============================================================== X10
h("X10 mark_traded links the wrong ledger row when a standalone forecast shares underlying+horizon")
w = World("x10")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]

    async def between(forecast_tool):
        # the agent puts a DIFFERENT view on record for the same name and day, then trades
        await forecast_tool.ainvoke({"underlying": "SPY", "claim": "SPY stays above 600",
                                     "probability": 0.80, "horizon": horizon, "band_low": spot - 3, "band_high": spot + 3})

    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon, between=between))
    ents = w.ledger.all()
    thesis = [e for e in ents if e.kind == "thesis"]
    standalone = [e for e in ents if e.kind == "standalone"]
    check(len(thesis) == 1 and len(standalone) == 1, "one thesis row, one standalone row")
    check(standalone[0].traded and not thesis[0].traded,
          "the STANDALONE row was marked traded; the thesis that was actually traded was not",
          f"standalone traded={standalone[0].traded} p={standalone[0].probability}; thesis traded={thesis[0].traded} stated={thesis[0].probability_stated}")
    check(standalone[0].probability == 0.42, "and the agent's 80% standalone view was overwritten with the trade's 42%",
          f"p={standalone[0].probability}")
    NOTES.append("X10: Ledger.mark_traded matches on (underlying, horizon, not traded) from the end, "
                 "ignoring kind and band.")
finally:
    w.cleanup()

# ============================================================== X11
h("X11 a fraction where a percent was expected: stop_loss_pct=-0.65 arms a -0.65% hair-trigger, no warning")
w = World("x11")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    out = run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                            short_k=round(spot - 12), stated=0.42, horizon=horizon,
                            record_kwargs={"stop_loss_pct": -0.65, "profit_target_pct": 1.4}))
    print("  record_position said:", out["record"][:200].replace("\n", " "))
    check("stop_loss" not in out["record"].split("Watching")[-1] and "-0.65" not in out["record"],
          "no warning mentions the stop (the only WARNING is the unrelated late underlying stop)",
          out["record"][out["record"].find("WARNING"):][:90])
    pid = w.store.open_positions()[0].position_id
    w.broker.prev_closes["SPY"] = spot
    w.broker.mark("SPY", -0.02)         # a 2% mark move - bid/ask noise on a fresh spread
    run(w.fast_path())
    _, _, c = run(w.fast_path())
    check(c == [pid], "a -2% mark closes the position", f"closed={c}")
    ex = rows(w.journal, "exit")[-1]
    print(f"  exit: {ex['explanation']}")
    NOTES.append("X11: record_position formats stop_loss_pct as f'{x}%' unconditionally; confidence is a "
                 "0-1 fraction in the same call, so a mixed-units call arms a stop at -0.65%.")
finally:
    w.cleanup()

# ============================================================== X12
h("X12 (control) shared-leg close by quantity: closing A must not leg B out (D-112)")
w = World("x12")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon, qty_override=2))
    # B shares the short leg (its LONG is A's SHORT strike... no: share the SAME symbol/side)
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon, qty_override=3))
    a, b = sorted(w.store.open_positions(), key=lambda p: int(p.legs[0]["qty"]))  # A = the 2-lot
    w.broker.prices["SPY"] = spot + 6.0
    # only A's stop should fire: give A an underlying stop just above spot
    a.exit_rules.append({"type": "underlying_stop", "direction": "above", "level": spot + 5.0})
    w.store.save(a)
    run(w.fast_path())
    _, _, c = run(w.fast_path())
    check(c == [a.position_id], "A's underlying stop fires (2 of 3)", f"closed={c}")
    qtys = [q for s, q in w.broker.closed]
    check(all(q == "2" for q in qtys), "close_position was called BY QUANTITY for A's 2 lots", f"{w.broker.closed}")
    left = {p["symbol"]: p["qty"] for p in w.broker.positions}
    check(all(abs(q) == 3 for q in left.values()), "B's 3 lots remain at the broker", f"{left}")
    snap, recon, c2 = run(w.fast_path())
    b2 = w.store.load(b.position_id)
    check(b2.status == "open" and b2.leg_divergence_count == 0, "B is untouched", f"{b2.status} div={b2.leg_divergence_count}")
finally:
    w.cleanup()

# ============================================================== X13
h("X13 the sizing stash is never cleared: a second record on the same name inherits the first's risk")
w = World("x13")
try:
    spot = w.broker.prices["SPY"]
    expiry, horizon = days_out(7), days_out(3)
    snap = run(w.snapshot())
    posture = w.posture(snap)
    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, w.paths.state, ledger=w.ledger)
    size = local_tools.build_size_position(w.calib, snap.equity, shared=shared, posture=posture, journal=w.journal)
    rec = local_tools.build_record_position(w.store, "dec", shared=shared, ledger=w.ledger, journal=w.journal, calibration=w.calib)
    wide = [{"right": "P", "strike": spot - 4, "side": "long", "qty": 1, "price": 3.0},
            {"right": "P", "strike": spot - 12, "side": "short", "qty": 1, "price": 1.2}]
    narrow = [{"right": "P", "strike": spot - 4, "side": "long", "qty": 1, "price": 3.0},
              {"right": "P", "strike": spot - 6, "side": "short", "qty": 1, "price": 2.4}]
    run(sim.ainvoke({"thesis_claim": "c", "underlying": "SPY", "horizon": horizon, "drift_pct": -1.5,
                     "spot": spot, "iv_pct": 18.0, "days_to_expiry": 7,
                     "candidates": [{"name": "wide", "legs": wide}, {"name": "narrow", "legs": narrow}],
                     "band_high": spot - 4}))
    st = {s.name: s for s in shared.structures}
    run(size.ainvoke({"stated_confidence": 0.42, "max_profit": st["wide"].max_profit,
                      "max_loss": st["wide"].max_loss, "underlying": "SPY", "structure_name": "wide"}))
    sized = shared.sizing
    # the agent then trades the NARROW spread, at the same contract count
    legs = [{"symbol": occ("SPY", expiry, "P", spot - 4), "side": "buy", "qty": sized.contracts},
            {"symbol": occ("SPY", expiry, "P", spot - 6), "side": "sell", "qty": sized.contracts}]
    out = run(rec.ainvoke({"underlying": "SPY", "strategy": "narrow", "legs": legs, "thesis": "t",
                           "confidence": 0.42, "expiry": expiry}))
    p = w.store.open_positions()[0]
    true_risk = abs(st["narrow"].max_loss) * sized.contracts
    check(p.max_loss_usd == sized.max_loss_usd and abs(p.max_loss_usd - true_risk) > 1,
          "the page carries the WIDE spread's max loss for a NARROW spread; no mismatch note",
          f"recorded ${p.max_loss_usd:,.0f} vs true ${true_risk:,.0f}; sizing note={'size_position computed' in out}")
    NOTES.append("X13: record_position takes shared.sizing whenever the underlying matches, and only "
                 "checks contract COUNT, not which structure was sized. Reconcile repairs it at fill.")
finally:
    w.cleanup()

# ============================================================== X14
h("X14 record_position with NO expiry: every calendar rule is blind and nothing says so at record time")
w = World("x14")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    out = run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                            short_k=round(spot - 12), stated=0.42, horizon=horizon,
                            record_kwargs={"expiry": "", "stop_loss_pct": None, "profit_target_pct": None,
                                           "underlying_stop_above": None}))
    check("expiry" not in out["record"].lower(), "the tool's reply never mentions the missing expiry",
          out["record"][-160:].replace("\n", " "))
    p = w.store.open_positions()[0]
    check(p.expiry == "", "the page has expiry ''")
    hb = rows(w.journal, "exit_run")[-1]
    check(hb.get("blind_signals", {}).get("days_to_expiry") == 1 and hb.get("invalid_rules") == 0,
          "exit_run: the implicit gamma-wall time stop is BLIND every tick, invalid_rules=0",
          f"blind={hb.get('blind_signals')} invalid={hb.get('invalid_rules')} watched={exit_rules.watched_signals(p)}")
    NOTES.append("X14: expiry defaults to '' in record_position; the OCC legs carry the date but the page's expiry "
                 "is what days_to_expiry reads, so a missing field disarms the gamma-wall stop silently.")
finally:
    w.cleanup()

# ============================================================== X15
h("X15 the model calls record_position TWICE for one fill (a retried tool call)")
w = World("x15")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    out = run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                            short_k=round(spot - 12), stated=0.42, horizon=horizon, confirm=False))
    first = w.store.open_positions()[0]
    # second call, identical arguments, no second order
    shared = out["shared"]
    rec = local_tools.build_record_position(w.store, "dec_sim", elfmem_blocks={"attention": {"blk_a": 0.9}},
                                            shared=shared, ledger=w.ledger, journal=w.journal, calibration=w.calib)
    legs = [{"symbol": l["symbol"], "side": l["side"], "qty": l["qty"]} for l in first.legs]
    out2 = run(rec.ainvoke({"underlying": "SPY", "strategy": "bear_put_spread", "legs": legs,
                            "thesis": "t", "confidence": 0.42, "expiry": expiry, "stop_loss_pct": -65.0}))
    check("WARNING" in out2 and "already held" in out2, "the second call is WARNED (leg_overlap) but recorded")
    snap, recon, _ = run(w.fast_path())
    opens = w.store.open_positions()
    check(len(opens) == 2 and all(p.status == "open" for p in opens),
          "both pages confirm as OPEN against ONE broker fill", f"{[(p.status, p.max_loss_usd) for p in opens]}")
    at_risk = sum(p.max_loss_usd or 0 for p in opens)
    check(at_risk == 2 * (first.max_loss_usd or 0), "the book caps now count the risk TWICE",
          f"${at_risk:,.0f} vs one fill of ${first.max_loss_usd:,.0f}")
    check(len(w.calib.pending()) == 2, "two calibration forecasts pend for one trade", f"{len(w.calib.pending())}")
    fills = rows(w.journal, "fill")
    check(len(fills) == 2 and len(w.mem.remembered) == 2, "learn.on_fill ran twice: two thesis blocks, two mind predictions")
    NOTES.append("X15: a duplicated record_position call yields two pages for one fill; the overlap is warned, "
                 "then both confirm, double-count book risk, and both will be scored.")
finally:
    w.cleanup()

# ============================================================== X16
h("X16 crash between the order and record_position (FM-1): the orphan is adopted BEFORE the resume records it")
w = World("x16")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    # the order goes to the broker; the tick dies before record_position
    legs = [{"symbol": occ("SPY", expiry, "P", spot - 4), "side": "buy", "qty": 5, "price": 3.0},
            {"symbol": occ("SPY", expiry, "P", spot - 12), "side": "sell", "qty": 5, "price": 1.2}]
    w.broker.place_option_order(legs=legs, underlying="SPY")
    snap, recon, _ = run(w.fast_path())          # next tick: reconcile adopts
    orphans = [p for p in w.store.all() if p.provenance == "unknown"]
    check(len(orphans) == 1 and orphans[0].status == "open", "next tick adopts the fill as an orphan (stub, no stops)",
          f"recon={reconcile.summarise(recon)}")
    # the resumed decide cycle re-submits (broker rejects the duplicate id) and records the position
    shared = local_tools.SharedContext()
    rec = local_tools.build_record_position(w.store, "dec_resume", shared=shared, ledger=w.ledger,
                                            journal=w.journal, calibration=w.calib)
    out = run(rec.ainvoke({"underlying": "SPY", "strategy": "bear_put_spread",
                           "legs": [{"symbol": l["symbol"], "side": l["side"], "qty": 5} for l in legs],
                           "thesis": "t", "confidence": 0.42, "expiry": expiry, "stop_loss_pct": -65.0,
                           "underlying_stop_above": spot + 5}))
    check("already held by" in out and "orphan" in out, "record_position warns the legs are held by the ORPHAN page",
          out[:120].replace("\n", " "))
    snap, recon, _ = run(w.fast_path())
    opens = w.store.open_positions()
    check(len(opens) == 2 and all(p.status == "open" for p in opens),
          "two open pages for one fill: the orphan stub and the real record", f"{[(p.strategy, p.status) for p in opens]}")
    # the real page's stop fires: it closes ITS qty, the orphan is left claiming legs that are gone
    w.broker.prices["SPY"] = spot + 6.0
    run(w.fast_path())
    _, _, c = run(w.fast_path())
    snap, recon, _ = run(w.fast_path())
    o = [p for p in w.store.all() if p.provenance == "unknown"][0]
    check(o.status == "closed" and o.close_reason == "external", "the orphan is then scored as an EXTERNAL close",
          f"orphan={o.status}/{o.close_reason}; closes sent={w.broker.closed}")
    refl = rows(w.journal, "reflection")
    check(len(refl) == 2, "two reflections, two lessons for one trade", f"{len(refl)}")
    NOTES.append("X16: after a crash between order and record, the next tick's orphan adoption and the resumed "
                 "cycle's record_position both claim the fill; nothing merges them.")
finally:
    w.cleanup()

# ============================================================== X17
h("X17 a wide option mark inflates broker equity for ONE tick: the high-water mark keeps it forever")
w = World("x17")
try:
    hw0 = 104_060.0
    competence.high_water_path(w.paths.state).write_text(json.dumps({"high_water": hw0}))
    # a 13-lot spread whose short leg prints a wide bid for one tick: equity +5.5%
    w.broker.equity = hw0 * 1.055
    snap = run(w.snapshot())
    hw = competence.update_high_water(w.paths.state, snap.equity, w.journal)
    w.broker.equity = hw0                       # the quote normalises
    snap = run(w.snapshot())
    hw = competence.update_high_water(w.paths.state, snap.equity, w.journal)
    p = competence.assess(resolved=20, reliability=0.02,
                          positions=[SimpleNamespace(attribution="thesis_right_expression_right")] * 6,
                          equity=snap.equity, high_water=hw, appetite=1.75)
    check(hw > hw0 and p.drawdown >= competence.DEMOTE_ONE_TIER_AT and "drawdown" in p.reason,
          "with real equity unchanged the ladder now reads a 5.2% drawdown and demotes a tier",
          f"hw={hw:,.0f} drawdown={p.drawdown:.1%} -> {p.tier} ({p.reason[:60]})")
    NOTES.append("X17: update_high_water is a running max of Alpaca's marked equity, which includes option "
                 "marks; one wide print sets a peak no fill can reach and the drawdown brake latches.")
finally:
    w.cleanup()

# ============================================================== verdict
h("VERDICT")
print(f"{len(FAIL)} failing check(s)" + (": " + "; ".join(FAIL) if FAIL else ""))
print("\nFindings demonstrated:")
for n in NOTES:
    print(f"- {n}")
