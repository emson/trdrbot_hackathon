"""Scaffold: the WHOLE loop, offline, on a throwaway copy of the real data.

    uv run python tests/scaffold_whole_system.py

NOT collected by pytest (D-079). Every deterministic stage of the system is
driven for real - the fast path, the decide-cycle tools, housekeeping, the
learning chain, the Coach's tally - against a FAKE BROKER whose prices the
scenario controls and a REAL copy of the ledger, wiki and return histories.
Only the LLM is absent: the decide-cycle tools are called in the sequence the
agent would call them, which exercises every seam the agent's output crosses
(the graph plumbing itself is `test_chassis`'s business).

The question is not "does each function work" - the unit tier answers that.
It is "does the LOOP close": a thesis becomes a position, the position is
guarded every tick, it resolves, resolution reaches calibration, calibration
reaches the ladder, the ladder reaches the next size. And at every seam: does
the system say what it did.

  W1  the world: fake broker, real data, one fresh state tree
  S1  happy path - open a spread, hold it, resolve it, learn from it
  S2  the stop fires, in session, and reconcile agrees with the broker
  S3  broker unreadable - no absence conclusions, nothing closes
  S4  two names at once - both priced, both guarded, both capped
  S5  the wiki: written, protected, tombstoned - never deleted; revived
  S6  the Coach's tally advances across a day boundary and can conclude
  S7  gate regret: a refused thesis resolves, is scored, never enters calibration
  S8  the risk posture: appetite reaches the size the agent is handed
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import FakeMem, FakeTool, days_out, occ  # noqa: E402

from trdrbot import (  # noqa: E402
    analytics,
    coach,
    competence,
    exit_rules,
    housekeeping,
    ids,
    local_tools,
    reconcile,
    sizing,
)
from trdrbot import (  # noqa: E402
    config as config_mod,
)
from trdrbot import (  # noqa: E402
    ledger as ledger_mod,
)
from trdrbot.calibration import CalibrationStore  # noqa: E402
from trdrbot.journal import Journal  # noqa: E402
from trdrbot.positions import PositionStore  # noqa: E402
from trdrbot.wiki import Concept, Wiki  # noqa: E402

findings: list[str] = []
FAIL: list[str] = []


def note(msg: str) -> None:
    findings.append(msg)


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'PASS' if ok else '** FAIL **'}  {label}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def h(t: str) -> None:
    print(f"\n{'=' * 94}\n{t}\n{'=' * 94}")


# ============================================================== W1  the world
class Broker:
    """A broker the scenario can move. Shaped exactly as `analytics.snapshot`,
    `reconcile` and `exit_rules` read the real one - the envelope is what
    `mcp_client.unwrap` produces, so the same parsers run."""

    def __init__(self, equity: float = 104_060.0) -> None:
        self.equity = equity
        self.prices: dict[str, float] = {"SPY": 640.0, "NVDA": 120.0, "XLE": 90.0}
        #: Where each name closed yesterday. A scenario that moves `prices`
        #: without touching this has produced a session MOVE, which is what
        #: the exit engine's corroboration rule reads (D-113).
        self.prev_closes: dict[str, float] = dict(self.prices)
        self.positions: list[dict[str, Any]] = []      # broker-side legs
        self.orders: list[dict[str, Any]] = []
        self.market_open = True
        self.readable = True
        self.closed: list[str] = []
        self.placed: list[dict[str, Any]] = []

    # ---- the tool handlers
    def get_clock(self, **_: Any) -> dict[str, Any]:
        return {"is_open": self.market_open}

    def get_account_info(self, **_: Any) -> dict[str, Any]:
        return {"equity": self.equity, "cash": self.equity, "buying_power": self.equity}

    def get_all_positions(self, **_: Any) -> list[dict[str, Any]]:
        if not self.readable:
            raise RuntimeError("simulated broker outage")
        return list(self.positions)

    def get_orders(self, **_: Any) -> list[dict[str, Any]]:
        return list(self.orders)

    def get_stock_latest_trade(self, symbols: str = "", **_: Any) -> dict[str, Any]:
        return {"trades": {symbols: {"p": self.prices.get(symbols, 0.0),
                                     "t": ids.utc_now().isoformat()}}}

    def get_stock_snapshot(self, symbols: str = "", **_: Any) -> dict[str, Any]:
        return {symbols: {
            "latestTrade": {"p": self.prices.get(symbols, 0.0),
                            # A fresh print. A scenario testing staleness moves
                            # this back; the default must never be old, or every
                            # underlying stop in the scaffold reads blind.
                            "t": ids.utc_now().isoformat()},
            "prevDailyBar": {"c": self.prev_closes.get(symbols, 0.0)},
        }}

    def close_position(self, symbol_or_asset_id: str = "", **_: Any) -> dict[str, Any]:
        self.closed.append(symbol_or_asset_id)
        self.positions = [p for p in self.positions if p["symbol"] != symbol_or_asset_id]
        return {"status": "accepted", "symbol": symbol_or_asset_id}

    def place_option_order(self, **kw: Any) -> dict[str, Any]:
        self.placed.append(kw)
        for leg in kw.get("legs", []):
            # Alpaca's own convention, mirrored from the reconcile tests: a long
            # leg has qty > 0 and cost_basis > 0; a short leg has both negative.
            side = 1 if leg.get("side", "buy") == "buy" else -1
            q = int(leg.get("qty", 1))
            self.positions.append({
                "symbol": leg["symbol"], "qty": side * q,
                "cost_basis": side * float(leg.get("price", 1.0)) * 100 * q,
                "unrealized_pl": 0.0,
            })
        return {"status": "filled", "id": f"ord_{len(self.placed)}"}

    def get_news(self, **_: Any) -> dict[str, Any]:
        return {"news": []}

    def tools(self) -> dict[str, FakeTool]:
        names = ("get_clock", "get_account_info", "get_all_positions", "get_orders",
                 "get_stock_latest_trade", "get_stock_snapshot", "close_position",
                 "place_option_order", "get_news")
        return {n: FakeTool(n, getattr(self, n)) for n in names}

    # ---- scenario controls
    def mark(self, symbol_prefix: str, pnl_fraction: float) -> None:
        """Move every leg of a structure to `pnl_fraction` of its cost basis."""
        for p in self.positions:
            if p["symbol"].startswith(symbol_prefix):
                p["unrealized_pl"] = p["cost_basis"] * pnl_fraction


class World:
    def __init__(self, tag: str) -> None:
        self.root = ROOT / "data" / f".scaffold_{tag}"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.paths = config_mod.Paths.build(self.root)
        self.paths.ensure()
        # REAL histories and REAL wiki, copied - so the bootstrap, the vacuity
        # check and the concept pool are the production ones.
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
        # Start with an EMPTY book: the scenarios open their own.
        for p in self.store.all():
            p.path.unlink()
        self.wiki = Wiki(self.paths.wiki)
        self.ledger = ledger_mod.Ledger(self.paths.state / "ledger.jsonl")
        self.calib = CalibrationStore(self.paths.state / "forecasts.jsonl")
        self.mem = FakeMem()
        self.config = SimpleNamespace(
            paths=self.paths, deadline=None, risk_appetite=1.75,
            watchlist=["SPY"], research_universe=["SPY", "NVDA", "XLE"],
            events=[], polymarket_queries=[], coach={"enabled": False}, pricing={},
            model_chain=lambda role="decide": ["scripted"],
        )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- the stages, exactly as tick.py composes them
    async def snapshot(self) -> analytics.Snapshot:
        names = sorted({p.underlying for p in self.store.open_positions() if p.underlying}
                       | set(self.config.research_universe))
        return await analytics.snapshot(self.tools, underlyings=names, journal=self.journal)

    async def fast_path(self) -> tuple[analytics.Snapshot, dict[str, Any], list[str]]:
        snap = await self.snapshot()
        recon = await reconcile.reconcile(self.store, snap, self.journal, self.mem,
                                          self.wiki, self.calib)
        closed = await exit_rules.run(self.store, snap, self.tools, self.journal,
                                      self.config.deadline, self.mem, self.wiki,
                                      calibration=self.calib, verbose=False)
        return snap, recon, closed

    def posture(self, snap: analytics.Snapshot) -> competence.Competence:
        cal = self.calib.score(ledger_mod.as_forecasts(self.ledger.resolved()))
        hw = competence.update_high_water(self.paths.state, snap.equity or 0.0, self.journal)
        return competence.assess(
            resolved=cal.n, reliability=cal.reliability, positions=self.store.all(),
            equity=snap.equity or 0.0, high_water=hw, effective=cal.n_eff,
            appetite=self.config.risk_appetite)

    async def decide_open(self, *, underlying: str, spot: float, expiry: str,
                          long_k: float, short_k: float, stated: float,
                          horizon: str) -> dict[str, Any]:
        """The decide cycle's tool sequence, as the agent would call it:
        simulate -> size -> place -> record. Every tool is the REAL closure."""
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
            extra_forecasts=ledger_mod.as_forecasts(self.ledger.resolved()),
            journal=self.journal)
        rec = local_tools.build_record_position(
            self.store, "dec_scaffold", elfmem_blocks={}, generated_by="scaffold",
            calibration=self.calib, sources=[], shared=shared, ledger=self.ledger,
            journal=self.journal)

        # `simulate_experiments` speaks long/short; the broker order speaks
        # buy/sell - the same two seams the real agent crosses.
        legs = [{"symbol": occ(underlying, expiry, "P", long_k), "side": "long", "qty": 1,
                 "right": "P", "strike": long_k, "price": 3.0, "expiry": expiry},
                {"symbol": occ(underlying, expiry, "P", short_k), "side": "short", "qty": 1,
                 "right": "P", "strike": short_k, "price": 1.2, "expiry": expiry}]
        dte = (ids.date.fromisoformat(expiry) - ids.today()).days
        sim_out = await sim.ainvoke({
            "thesis_claim": f"{underlying} falls to {short_k} by {horizon}",
            "underlying": underlying, "horizon": horizon, "drift_pct": -1.5,
            "spot": spot, "iv_pct": 18.0, "days_to_expiry": dte,
            "candidates": [
                {"name": "bear_put_spread", "legs": legs},
                {"name": "long_put", "legs": [dict(legs[0])]},
            ],
            "band_high": long_k,
        })
        st = shared.structures[0] if shared.structures else None
        mp = float(getattr(st, "max_profit", 0.0) or 0.0) if st else 180.0
        ml = float(getattr(st, "max_loss", 0.0) or 0.0) if st else -180.0
        size_out = await size.ainvoke({
            "stated_confidence": stated, "max_profit": mp, "max_loss": ml,
            "underlying": underlying, "structure_name": "bear_put_spread"})
        qty = int(getattr(shared.sizing, "contracts", 0) or 0) if shared.sizing else 0
        qty = qty or 1
        order_legs = [{"symbol": l["symbol"], "side": "buy" if l["side"] == "long" else "sell",
                       "qty": qty, "price": l["price"]} for l in legs]
        placed = self.broker.place_option_order(legs=order_legs, underlying=underlying)
        rec_out = await rec.ainvoke({
            "underlying": underlying, "strategy": "bear_put_spread",
            "legs": order_legs,
            "thesis": f"{underlying} falls to {short_k} by {horizon}", "confidence": stated,
            "expiry": expiry, "stop_loss_pct": -65.0, "profit_target_pct": 140.0,
            "underlying_stop_above": spot * 1.03,
        })
        # The next tick's fast path confirms the fill: 'opening' -> 'open'.
        await self.fast_path()
        return {"sim": str(sim_out), "size": str(size_out), "placed": placed,
                "record": str(rec_out), "posture": posture, "shared": shared}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# ============================================================== S1 happy path
h("S1  happy path: research -> decide opens a spread -> guarded -> resolved -> learned")
w = World("s1")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    out = run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry,
                            long_k=round(spot - 4), short_k=round(spot - 12),
                            stated=0.42, horizon=horizon))
    print("  simulate:", out["sim"][:120].replace("\n", " "))
    print("  size    :", out["size"][:160].replace("\n", " "))
    print("  record  :", out["record"][:120].replace("\n", " "))
    opened = w.store.open_positions()
    check(len(opened) == 1, "record_position wrote one open position", f"{len(opened)}")
    p = opened[0] if opened else None
    check(bool(p and p.max_loss_usd), "the position carries a max_loss_usd",
          f"${p.max_loss_usd:,.0f}" if p and p.max_loss_usd else "None")
    check(bool(p and p.exit_rules), "and exit rules", f"{len(p.exit_rules) if p else 0} rules")
    check(bool(p and p.thesis_claim and p.thesis_horizon), "and a falsifiable thesis",
          f"horizon {p.thesis_horizon if p else '-'}")
    traded = [e for e in w.ledger.all() if e.traded]
    check(len(traded) == 1, "the ledger marks exactly one thesis as TRADED", f"{len(traded)}")
    check("[size set by:" in out["size"], "sizing named its binding constraint")
    sz = out["shared"].sizing
    check(bool(sz and sz.contracts > 1), "sizing produced a real quantity at 1.75x",
          f"{sz.contracts if sz else None} contracts")
    # -- guarded every tick, nothing fires on a flat mark
    snap, recon, closed = run(w.fast_path())
    check("SPY" in snap.underlying_prices, "the fast path priced the held underlying")
    check(closed == [], "a flat mark closes nothing", f"closed {closed}")
    check(recon.get("adopted", []) == [] and recon.get("closed", []) == [],
          "reconcile agrees with the broker", f"{ {k: v for k, v in recon.items() if v} }")
    # -- the thesis resolves at horizon and reaches calibration / the ladder
    cal0 = w.calib.score(ledger_mod.as_forecasts(w.ledger.resolved()))
    n0 = cal0.n
    # jump the calendar: the horizon has passed and the close is known
    matured = [e for e in w.ledger.all() if e.traded]
    for e in matured:
        w.ledger.resolve(e.id, spot - 8.0, ids.utc_now().isoformat())
    cal1 = w.calib.score(ledger_mod.as_forecasts(w.ledger.resolved()))
    # D-105 FOUND a real gap here on its first run - the traded thesis sat at
    # its 0.5 placeholder and the loop was open exactly where money had crossed
    # it. **D-116 revises the MECHANISM** (I-78): the confidence was already
    # reaching calibration through the POSITION row, so stating the ledger row
    # too made one number n=2 on two events that can disagree. The property
    # this scenario cares about is unchanged and is now stated directly: one
    # trade, one forecast, at the confidence it was traded at.
    check(bool(matured) and cal1.n == n0 and not matured[0].probability_stated
          and matured[0].probability == 0.42 and matured[0].position_id,
          "a traded thesis is LINKED and scored once - by the position row, not twice",
          f"ledger n {n0} -> {cal1.n}, stated={matured[0].probability_stated if matured else '-'}, "
          f"p={matured[0].probability if matured else '-'}")
    pend = [f for f in w.calib.pending() + w.calib.resolved()
            if f.position_id == (matured[0].position_id if matured else "")]
    check(len(pend) == 1 and pend[0].probability == 0.42,
          "and the position row is the ONE calibration forecast for that trade",
          f"{[(f.position_id, f.probability) for f in pend]}")
finally:
    w.cleanup()

# ============================================================== S2 the stop
h("S2  the stop fires in session, is refused off-hours, and reconcile follows the broker")
w = World("s2")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon))
    # 80% of the debit gone, AND the underlying moved to cause it. Since D-115
    # a mark breach closes only when the underlying corroborates it (I-77): a
    # wide quote on an unmoved underlying is the artifact the debounce exists
    # for, and it persists for hours on an illiquid strike. This is a bearish
    # spread, so the loss is SPY rallying through it - which is what an -80%
    # print on a real move looks like.
    w.broker.mark("SPY", -0.80)
    w.broker.prices["SPY"] = spot + 6.0
    w.broker.market_open = False
    snap, _, closed = run(w.fast_path())
    check(closed == [], "OFF-HOURS: the breach is detected but no close is submitted",
          f"closed {closed}, broker closes {w.broker.closed}")
    w.broker.market_open = True
    snap, _, closed = run(w.fast_path())
    check(len(closed) == 1, "IN SESSION: the stop closes the position", f"closed {closed}")
    check(len(w.broker.closed) >= 1, "and the broker received the close", f"{w.broker.closed}")
    st = {p.position_id: p.status for p in w.store.all()}
    check(all(s in ("closing", "closed") for s in st.values()),
          "store status moved off 'open'", f"{st}")
    # the broker has now flattened; next tick reconcile must finalise
    snap, recon, _ = run(w.fast_path())
    st2 = {p.position_id: p.status for p in w.store.all()}
    check(all(s == "closed" for s in st2.values()),
          "next tick: reconcile finalises against an empty broker", f"{st2}")
finally:
    w.cleanup()

# ============================================================== S3 outage
h("S3  broker unreadable: no absence conclusions, nothing closes, and it is SAID")
w = World("s3")
try:
    expiry, horizon = days_out(7), days_out(3)
    spot = w.broker.prices["SPY"]
    run(w.decide_open(underlying="SPY", spot=spot, expiry=expiry, long_k=round(spot - 4),
                      short_k=round(spot - 12), stated=0.42, horizon=horizon))
    w.broker.readable = False
    snap, recon, closed = run(w.fast_path())
    check(snap.broker_readable is False, "snapshot says the broker was unreadable")
    check(closed == [] and not w.broker.closed, "nothing was closed on an unreadable broker")
    st = {p.position_id: p.status for p in w.store.all()}
    check(all(s == "open" for s in st.values()), "the position was NOT marked closed", f"{st}")
    rows = [r for r in w.journal.read() if r.get("kind") == "degraded"]
    check(any(r.get("subsystem") == "analytics.positions" for r in rows),
          "a `degraded` row says so", f"{len(rows)} degraded rows")
finally:
    w.cleanup()

# ============================================================== S4 two names
h("S4  two names at once: both priced, both guarded, per-name cap binds per name")
w = World("s4")
try:
    expiry, horizon = days_out(7), days_out(3)
    for u in ("SPY", "NVDA"):
        spot = w.broker.prices[u]
        out = run(w.decide_open(underlying=u, spot=spot, expiry=expiry,
                                long_k=round(spot * 0.99, 0), short_k=round(spot * 0.97, 0),
                                stated=0.42, horizon=horizon))
        print(f"  {u}: {out['size'][:110].replace(chr(10), ' ')}")
    opened = w.store.open_positions()
    check(len(opened) == 2, "two positions on two names are open", f"{[p.underlying for p in opened]}")
    snap, recon, closed = run(w.fast_path())
    check({"SPY", "NVDA"} <= set(snap.underlying_prices), "both underlyings priced",
          f"{sorted(snap.underlying_prices)}")
    check(closed == [], "flat marks close nothing")
    # a third SPY position must be judged against SPY's OWN cap, not NVDA's
    spot = w.broker.prices["SPY"]
    posture = w.posture(snap)
    by = {p.underlying: (p.max_loss_usd or 0.0) for p in opened}
    d = sizing.size_position(
        equity=snap.equity, stated_confidence=0.42, max_profit=300.0, max_loss=-200.0,
        calibration=w.calib.score([]), posture=posture, underlying="SPY",
        open_risk_usd=sum(by.values()), open_risk_by_underlying=by, payoff_ratio=1.5)
    check(d.contracts > 0, "a third position on SPY still fits under SPY's name cap",
          f"{d.contracts} contracts, binding: {d.binding or 'refused'}")
    # The underlying moves with the mark (D-115/I-77): corroboration now applies
    # to every mark breach, not only the decisive one, so a loss the underlying
    # does not show is held as the artifact it probably is.
    w.broker.mark("NVDA", -0.80)
    w.broker.prices["NVDA"] = w.broker.prices["NVDA"] * 1.02
    # ...and a CORROBORATED breach closes on the FIRST print, which is the
    # whole point of asking the underlying: the debounce is what a breach it
    # cannot judge falls back to, not a delay applied to every one.
    snap, _, closed = run(w.fast_path())
    nv = [p for p in w.store.all() if p.underlying == "NVDA"]
    xr = [r for r in w.journal.read() if r.get("kind") == "exit_run"][-1:]
    print(f"  NVDA status={[p.status for p in nv]} max_loss={[p.max_loss_usd for p in nv]} "
          f"rules={[len(p.exit_rules) for p in nv]}")
    print(f"  broker NVDA legs: {[ (b['symbol'], b['cost_basis'], b['unrealized_pl']) for b in w.broker.positions if b['symbol'].startswith('NVDA')]}")
    print(f"  last exit_run: { {k: v for k, v in (xr[0] if xr else {}).items() if k not in ('ts','id')} }")
    check(closed and all("NVDA" in c for c in closed), "only the NVDA stop fired",
          f"closed {closed}")
finally:
    w.cleanup()

# ============================================================== S5 the wiki
h("S5  the wiki: written, protected by a live claim, tombstoned when stale - never deleted")
w = World("s5")
try:
    before = {c.concept_id for c in w.wiki.all_concepts("research")}
    # a freshly written dossier and a stale one nothing claims
    fresh = Concept(concept_id="research/ZZZFRESH", frontmatter={"type": "CompanyDossier"},
                    body="fresh")
    w.wiki.write_concept(fresh, type_="CompanyDossier")
    stale = w.wiki.read("research/ZZZFRESH")
    stale.frontmatter["stale_after"] = (ids.utc_now() - timedelta(days=2)).isoformat()
    w.wiki.write_concept(stale, type_="CompanyDossier", touch_generated=False)
    claimed = Concept(concept_id="research/ZZZCLAIM", frontmatter={"type": "CompanyDossier"},
                      body="claimed")
    w.wiki.write_concept(claimed, type_="CompanyDossier")
    c2 = w.wiki.read("research/ZZZCLAIM")
    c2.frontmatter["stale_after"] = (ids.utc_now() - timedelta(days=2)).isoformat()
    w.wiki.write_concept(c2, type_="CompanyDossier", touch_generated=False)
    # a STATED live claim on ZZZCLAIM
    e = w.ledger.register(kind="muse", underlying="ZZZCLAIM", claim="c", probability=0.4,
                          horizon=days_out(3), band_low=1.0, band_high=2.0,
                          probability_stated=False)
    w.ledger.mark_stated(e.id)
    swept = run(housekeeping.run(w.store, analytics.Snapshot(), w.mem, w.wiki, w.journal,
                                 w.config, tools=None, verbose=False))
    after = {c.concept_id for c in w.wiki.all_concepts("research")}
    check(before | {"research/ZZZFRESH", "research/ZZZCLAIM"} <= after,
          "NO dossier was deleted by the sweep", f"{len(before)} -> {len(after)}")
    check(w.wiki.read("research/ZZZFRESH").frontmatter.get("status") == "deprecated",
          "the stale, unclaimed page was tombstoned in place")
    check(w.wiki.read("research/ZZZCLAIM").frontmatter.get("status") != "deprecated",
          "the stale page with a STATED live claim was protected")
    # revival: a rewrite is a revival
    z = w.wiki.read("research/ZZZFRESH")
    z.body = "refreshed"
    w.wiki.write_concept(z, type_="CompanyDossier")
    check(w.wiki.read("research/ZZZFRESH").frontmatter.get("status") == "stable",
          "re-research REVIVES a tombstoned page (status back to stable)")
    check(len(list(w.wiki.all_concepts("research"))) >= len(before),
          "deprecated pages remain readable to `all_concepts` (only the muse filters them)")
finally:
    w.cleanup()

# ============================================================== S6 the coach
h("S6  the Coach: paired trials across a day boundary count, and the verdict can close")
w = World("s6")
try:
    cfg = SimpleNamespace(paths=w.paths, coach={"enabled": True}, pricing={})
    coach._append(coach.events_path(cfg), {"kind": "experiment_opened", "exp_id": "e1",
                                            "lever": "muse.prompt", "incumbent": "v0",
                                            "challenger": "v1"})
    strong_c, weak_i = {"survived": 5, "failed": 0, "candidates": 5}, {"survived": 1, "failed": 4, "candidates": 5}
    for day in range(12):
        for k in range(3):
            coach.record_trial(cfg, "e1", run_nonce=f"{days_out(-day)}|{k}",
                               incumbent=weak_i, challenger=strong_c)
    t = coach.tally(cfg, "e1")
    check(t.runs == 36 and t.voided == 0, "36 runs over 12 days all COUNT (no day-boundary voiding)",
          f"runs {t.runs} voided {t.voided}")
    outcome, reason = coach.verdict(t, coach.floors(cfg))
    check(outcome == "promoted", "a genuinely better challenger is PROMOTED", f"{outcome}: {reason[:60]}")
    # and the same nonce twice within a day is still caught
    coach.record_trial(cfg, "e1", run_nonce=f"{days_out(0)}|0", incumbent=weak_i, challenger=strong_c)
    check(coach.tally(cfg, "e1").voided == 1, "a genuine same-day duplicate is still voided")
finally:
    w.cleanup()

# ============================================================== S7 gate regret
h("S7  gate regret: a refused thesis resolves, is scored, and NEVER enters calibration")
w = World("s7")
try:
    e = w.ledger.register(kind="muse", underlying="SPY", claim="lottery", probability=0.2,
                          horizon=days_out(-1), band_low=600.0, band_high=700.0,
                          probability_stated=False)
    w.ledger.mark_rejected(e.id, "rejected: base probability 5% - a lottery ticket")
    n_before = w.calib.score(ledger_mod.as_forecasts(w.ledger.resolved())).n
    w.ledger.resolve(e.id, 650.0, ids.utc_now().isoformat())
    n_after = w.calib.score(ledger_mod.as_forecasts(w.ledger.resolved())).n
    check(n_after == n_before, "the resolved REJECTION did not move calibration", f"n {n_before} -> {n_after}")
    regret, baseline = ledger_mod.gate_regret(w.ledger.all())
    g = regret.get("lottery")
    check(bool(g and g.resolved >= 1 and g.held >= 1), "but it IS scored against the gate",
          f"lottery: {g.read(baseline) if g else 'missing'}")
finally:
    w.cleanup()

# ============================================================== S8 posture
h("S8  the risk posture the agent is handed: appetite reaches size, ceiling is reported")
w = World("s8")
try:
    snap = run(w.snapshot())
    p = w.posture(snap)
    check(p.appetite == 1.75 and p.realised_appetite == 1.75,
          "1.75x is applied and fully realised at this rung", f"{p.tier.upper()} book {p.book_cap:.0%}")
    from types import SimpleNamespace as _NS

    from trdrbot.experiments import THESIS_RIGHT_EXPRESSION_RIGHT as _G
    p2 = competence.assess(resolved=40, reliability=0.02,
                           positions=[_NS(attribution=_G)] * 10,
                           equity=snap.equity, high_water=snap.equity, appetite=2.0)
    check(p2.tier == competence.MATURE and p2.realised_appetite < 2.0
          and "realised" in p2.reason,
          "at MATURE, 2.0x is absorbed by the ruin bound AND the posture says so",
          f"{p2.tier} realised {p2.realised_appetite:.2f}x")
    check(w.posture(snap).realised_appetite == 1.75,
          "at EXPLORE (this fresh world) 1.75x is not absorbed - the bound is far")
    check(int(p.book_cap / p.seed_fraction) >= 6, "the book can hold >= 6 floor-sized positions",
          f"{p.book_cap / p.seed_fraction:.1f}")
finally:
    w.cleanup()

# ============================================================== verdict
h("VERDICT")
print(f"{len(FAIL)} failing check(s)" + (": " + "; ".join(FAIL) if FAIL else ""))
for f in findings:
    print(f"\n- {f}")
print()
