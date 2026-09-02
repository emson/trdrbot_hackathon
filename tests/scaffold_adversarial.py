"""Scaffold: ADVERSARIAL scenarios against the whole loop, offline.

    uv run python tests/scaffold_adversarial.py

NOT collected by pytest (D-079). Same world as scaffold_whole_system.py - a fake
broker the scenario controls, real copies of the return histories and the wiki,
and the REAL code for every deterministic stage - but every scenario here is an
attack on a seam rather than a happy path. A PASS means the attack LANDED: the
label states the defect, and the check asserts the code exhibits it. When a
defect is fixed its check flips to FAIL, which is the signal to move the row
into a pinned regression test.

Rows are DELETED as their defect is fixed and its scenario is pinned as a
regression test - the file is the burn-down chart, and the goal state is an
empty one. Gone so far: X1 and X2 (I-77/I-76, now
tests/test_exit_and_risk.py::test_a_persistent_wide_print_on_an_unmoved_underlying_never_closes
and ::test_the_overnight_mark_does_not_pre_satisfy_the_debounce_window), X3
(I-75, ::test_an_unreadable_account_sizes_nothing_and_says_why and its three
siblings), X17 (I-86, ::test_the_high_water_mark_ignores_an_unrealisable_option_print).

  X5   an order that never filled is attributed at its horizon and credits memory
  X7   a forecast matures at 00:00 ET on its horizon date, 16h before that session closes
  X8   '---' inside a thesis claim truncates or destroys the position page
  X12  (control) shared-leg close by quantity leaves the sibling intact
"""
from __future__ import annotations

import asyncio
import contextlib
import io
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

# ============================================================== X12
h("X12 (control) shared-leg close by quantity: closing A must not leg B out (D-112)")
w = World("x12")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon, qty_override=2))
    # B is a DIFFERENT structure that happens to be short the same contract.
    # It used to be a byte-identical copy of A at another quantity, which is
    # not "two positions sharing a leg" - it is one leg set, i.e. one fill, and
    # since D-116 the second record updates the first page instead of writing a
    # sibling. The control's premise was wrong, not its point.
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 8),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon, qty_override=3))
    a, b = sorted(w.store.open_positions(), key=lambda p: int(p.legs[0]["qty"]))  # A = the 2-lot
    w.broker.prices["SPY"] = spot + 6.0
    # only A's stop should fire: give A an underlying stop just above spot
    a.exit_rules.append({"type": "underlying_stop", "direction": "above", "level": spot + 5.0})
    w.store.save(a)
    run(w.fast_path())
    _, _, c = run(w.fast_path())
    check(c == [a.position_id], "A's underlying stop fires (2 of 3)", f"closed={c}")
    shared_sym = occ("SPY", expiry, "P", round(spot - 12))
    by_sym = dict(w.broker.closed)
    check(by_sym.get(shared_sym) == "2" and by_sym.get(occ("SPY", expiry, "P", round(spot - 4))) is None,
          "the SHARED leg closes by quantity, the sole-holder leg closes whole",
          f"{w.broker.closed}")
    left = {p["symbol"]: p["qty"] for p in w.broker.positions}
    check(all(abs(q) == 3 for q in left.values()), "B's 3 lots remain at the broker", f"{left}")
    snap, recon, c2 = run(w.fast_path())
    b2 = w.store.load(b.position_id)
    check(b2.status == "open" and b2.leg_divergence_count == 0, "B is untouched", f"{b2.status} div={b2.leg_divergence_count}")
finally:
    w.cleanup()

# ============================================================== verdict
h("VERDICT")
print(f"{len(FAIL)} failing check(s)" + (": " + "; ".join(FAIL) if FAIL else ""))
print("\nFindings demonstrated:")
for n in NOTES:
    print(f"- {n}")
