"""Scaffold: the whole loop driven end to end, offline. **Burn-down complete.**

    uv run python tests/scaffold_adversarial.py

NOT collected by pytest (D-079). A fake broker the scenario controls, real
copies of the return histories and the wiki, and the REAL code for every
deterministic stage.

This file was the burn-down chart for the 2026-09-02 adversarial audit: sixteen
attacks (X1-X17), each written so that a PASS meant the attack LANDED. As each
defect was fixed its check flipped to FAIL, and the row was deleted and its
scenario pinned as a regression test. **All sixteen are gone** (D-115 through
D-121), and every one of them now lives in the suite:

  X1, X2   -> test_exit_and_risk::test_a_persistent_wide_print_on_an_unmoved_
              underlying_never_closes, ::test_the_overnight_mark_does_not_pre_
              satisfy_the_debounce_window, ::test_an_unjudgeable_breach_still_
              debounces_to_a_close
  X3       -> test_exit_and_risk::test_an_unreadable_account_sizes_nothing_and_
              says_why and its three siblings
  X4       -> test_memory_and_credit::test_a_close_in_flight_is_not_adopted_as_
              an_orphan and ::test_a_position_closed_moments_ago_keeps_its_legs
  X5       -> test_regressions::test_an_order_that_never_filled_is_never_attributed
  X6       -> test_regressions::test_one_trade_contributes_exactly_one_forecast_
              to_calibration
  X7       -> test_regressions::test_a_forecast_matures_when_its_session_ends_
              not_when_its_date_begins
  X8, X15  -> test_regressions::test_a_frontmatter_fence_is_a_line_never_a_
              substring, ::test_recording_one_fill_twice_yields_one_page
  X9       -> test_regressions::test_a_lowercase_leg_symbol_is_stored_as_the_
              broker_spells_it
  X10      -> test_regressions::test_marking_a_thesis_traded_leaves_a_standalone_
              forecast_alone
  X11      -> the unit refusal in local_tools._suspect_pct_units (D-116)
  X13, X14 -> test_regressions::test_the_sizing_stash_is_matched_on_the_structure_
              not_just_the_count, ::test_a_missing_expiry_is_derived_from_the_legs
  X16      -> test_regressions::test_the_resumed_cycle_adopts_the_orphan_stub_it_raced
  X17      -> test_exit_and_risk::test_the_high_water_mark_ignores_an_
              unrealisable_option_print

**X12 stays, and it was never an attack.** It is the control the attacks were
read against, and it is the only place the shared-leg close is driven all the
way through the real decide -> record -> reconcile -> exit path rather than
from two pages written straight into the store. It must keep passing as a
control; the day it fails, D-112 has regressed.
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
        rec = local_tools.build_record_position(
            self.store, "dec_sim", elfmem_blocks={"attention": {"blk_a": 0.9, "blk_b": 0.4}},
            generated_by="sim", calibration=self.calib, sources=[], shared=shared,
            ledger=self.ledger, journal=self.journal)
        legs = [{"symbol": occ(underlying, expiry, "P", long_k), "side": "long", "qty": 1,
                 "right": "P", "strike": long_k, "price": 3.0, "expiry": expiry},
                {"symbol": occ(underlying, expiry, "P", short_k), "side": "short", "qty": 1,
                 "right": "P", "strike": short_k, "price": 1.2, "expiry": expiry}]
        dte = (date.fromisoformat(expiry) - ids.today()).days
        claim = f"{underlying} falls to {short_k} by {horizon}"
        sim_out = await sim.ainvoke({
            "thesis_claim": claim, "underlying": underlying, "horizon": horizon,
            "drift_pct": -1.5, "spot": spot, "iv_pct": 18.0, "days_to_expiry": dte,
            "candidates": [{"name": "bear_put_spread", "legs": legs},
                           {"name": "long_put", "legs": [dict(legs[0])]}],
            "band_high": long_k,
        })
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
        placed = self.broker.place_option_order(legs=order_legs, underlying=underlying)
        rec_out = await rec.ainvoke({
            "underlying": underlying, "strategy": "bear_put_spread",
            "legs": [dict(l) for l in order_legs],
            "thesis": claim, "confidence": stated, "expiry": expiry,
            "stop_loss_pct": -65.0, "profit_target_pct": 140.0,
            "underlying_stop_above": spot * 1.03})
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
if NOTES:
    print("\nFindings demonstrated:")
    for n in NOTES:
        print(f"- {n}")
