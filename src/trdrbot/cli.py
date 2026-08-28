"""CLI - the exploration surface for the walking skeleton.

    trdrbot doctor    # verify config, secrets, and the Alpaca MCP connection
    trdrbot inject    # drop an observation into the inbox by hand
    trdrbot tick      # run one tick end to end
    trdrbot journal   # show what happened
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import config as config_mod
from . import mcp_client
from .inbox import Inbox
from .journal import Journal
from .lock import tick_lock
from .tick import run_tick


async def _doctor() -> int:
    print("[doctor] loading config...")
    cfg = config_mod.load()
    print(f"  model:     {cfg.model}")
    print(f"  watchlist: {cfg.watchlist}")
    print(f"  deadline:  {cfg.deadline}")
    print(f"  data:      {cfg.paths.data}")

    print("\n[doctor] connecting to Alpaca MCP (spawns `uvx alpaca-mcp-server`)...")
    try:
        tools = await mcp_client.get_tools(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {exc!r}")
        print("\n  Check: .env has ALPACA_API_KEY / ALPACA_SECRET_KEY (not APCA_*),")
        print("  and that `uvx alpaca-mcp-server` runs.")
        return 1

    names = sorted(t.name for t in tools)
    print(f"  connected - {len(names)} tools")
    order_tools = [n for n in names if n in mcp_client.ORDER_TOOLS]
    print(f"  order-affecting tools present: {order_tools}")
    unknown = mcp_client.ORDER_TOOLS - set(names)
    if unknown:
        print(f"  NOTE: expected but absent: {sorted(unknown)}")

    print(f"\n[doctor] checking LLM gateway ({cfg.model})...")
    try:
        from langchain.chat_models import init_chat_model

        from .llm import build_model

        reply = await build_model(cfg, role="doctor").ainvoke("Reply with the single word: ok")
        print(f"  doctor model replied: {str(reply.content)[:40]!r}")

        # Probe EVERY model in every configured chain. A fallback that has
        # never been exercised is a promise, not a capability - and the whole
        # point of the chain is that it works on the day the primary stops
        # (D-062). Reports each independently; one dead provider is a warning,
        # not a failure, because the chain is what must survive.
        print("\n[doctor] probing every configured model...")
        seen: set[str] = set()
        reachable = 0
        for role in ("decide", "research", "discovery", "muse", "doctor"):
            for spec in cfg.model_chain(role):
                if spec in seen:
                    continue
                seen.add(spec)
                try:
                    m = init_chat_model(spec, max_tokens=16, max_retries=0)
                    r = await m.ainvoke("Say: ok")
                    served = (r.response_metadata or {}).get("model_name", "?")
                    print(f"  OK   {spec:<34} -> {served}")
                    reachable += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  DEAD {spec:<34} {type(exc).__name__}: {str(exc)[:80]}")
        print(f"  {reachable}/{len(seen)} configured models reachable")
        if reachable == 0:
            print("  NO MODEL IS REACHABLE - the system cannot make a decision.")
            return 1
        print(f"  reachable - replied {str(reply.content)[:40]!r}")
    except Exception as exc:  # noqa: BLE001
        from . import failures

        cause = failures.classify(exc)
        print(f"  FAILED ({cause.value}): {type(exc).__name__}: {exc}")
        print(f"\n  {failures.advice(cause, exc)}")
        return 1

    print(f"\n  all Alpaca tools: {', '.join(names)}")
    print("\n[doctor] all checks passed")
    return 0


def _inject(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    payload = json.loads(args.payload) if args.payload else {
        "note": "manual test observation",
        "watchlist": cfg.watchlist,
    }
    item = inbox.write(args.type, payload, source="manual", trust="primary")
    print(f"injected {item.id} -> {item.path}")
    return 0


async def _tick(force: bool = False) -> int:
    cfg = config_mod.load()
    try:
        with tick_lock(cfg.paths.state / "tick.lock"):
            await run_tick(cfg, force_decide=force)
    except BlockingIOError as exc:
        print(f"[tick] {exc}")
        return 0
    return 0


def _journal(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    entries = list(Journal(cfg.paths.journal).read())
    for e in entries[-args.n :]:
        extra = ""
        if e["kind"] in ("execution", "no_op"):
            extra = f" tools={e.get('tool_calls')} orders={len(e.get('order_calls') or [])}"
        print(f"{e['ts']}  {e['kind']:<10} {e['id']}{extra}")
    print(f"\n({len(entries)} entries total)")
    return 0


def _calibration() -> int:
    from .calibration import CalibrationStore

    cfg = config_mod.load()
    store = CalibrationStore(cfg.paths.state / "forecasts.jsonl")
    cal = store.score()
    pending = store.pending()

    print(f"\n{cal.verdict()}\n")
    if cal.n:
        print(f"  Brier score  : {cal.brier:.4f}   (0 = perfect, 0.25 = coin flip)")
        print(f"  reliability  : {cal.reliability:.4f}   (lower is better - overconfidence signal)")
        print(f"  resolution   : {cal.resolution:.4f}   (higher is better - discrimination)")
        print(f"  uncertainty  : {cal.uncertainty:.4f}   (irreducible, given the base rate)")
        print(f"  base rate    : {cal.base_rate:.0%} of closed positions profitable")
    print(f"\n  resolved: {cal.n}   pending: {len(pending)}")
    for f in pending:
        print(f"    - {f.position_id}: forecast {f.probability:.0%}, not yet resolved")
    return 0


async def _research() -> int:
    from . import research
    from .journal import Journal
    from .wiki import Wiki

    cfg = config_mod.load()
    tools = {t.name: t for t in await mcp_client.get_tools(cfg)}
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    r = await research.run(tools, cfg, inbox, Wiki(cfg.paths.wiki), Journal(cfg.paths.journal))
    print(f"research complete: {r}")
    return 0


async def _discover() -> int:
    from . import discovery
    from .journal import Journal
    from .wiki import Wiki

    cfg = config_mod.load()
    tools = {t.name: t for t in await mcp_client.get_tools(cfg)}
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    r = await discovery.run(tools, cfg, inbox, Wiki(cfg.paths.wiki), Journal(cfg.paths.journal))
    print(f"discovery complete: nominees={r['nominees']} opportunities={r['opportunities']}")
    return 0


#: No legitimate reason to poll a live broker faster than this. A stray
#: 5-second smoke-test loop once hammered the API and burned LLM calls for
#: half an hour before it was noticed - the floor bounds the blast radius of
#: that mistake even when process cleanup fails (D-044).
MIN_INTERVAL_SECONDS = 30


def _acquire_run_lock(pid_path: "Path") -> bool:
    """One run loop per machine. Returns False if another is already alive.

    A stale lock (the recorded process is gone) is taken over rather than
    treated as fatal: a crashed loop must not require manual cleanup before
    trading can resume.
    """
    import os

    if pid_path.exists():
        try:
            other = int(pid_path.read_text().strip())
        except (ValueError, OSError):
            other = None
        if other and other != os.getpid():
            try:
                os.kill(other, 0)  # signal 0 = liveness probe, no effect
            except ProcessLookupError:
                print(f"[run] stale lock from pid {other}, taking over")
            except PermissionError:
                print(f"[run] pid {other} is alive and not ours - refusing to start")
                return False
            else:
                print(f"[run] another run loop is already alive (pid {other}). "
                      f"Stop it first, or delete {pid_path} if you know it is dead.")
                return False
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))
    return True


async def _run_loop(interval: int, closed_interval: int, *,
                    max_ticks: int = 0, allow_fast: bool = False) -> int:
    """Tick until the deadline. Two cadences, because the work differs.

    Open: the decide path, the market pulse and exit-rule evaluation, on a
    short interval - exits and stops are worthless if checked hourly.
    Closed: housekeeping, research, attribution, consolidation - all of which
    are daily-ish by nature and cost LLM calls, so a long interval.

    A failing tick NEVER stops the loop: an eight-day unattended run will meet
    provider transients, and a crash that halts trading is worse than a tick
    that is skipped and journalled (INV-8).
    """
    from datetime import date

    from .tick import run_tick

    from pathlib import Path

    cfg = config_mod.load()
    if interval < MIN_INTERVAL_SECONDS and not allow_fast:
        print(f"[run] refusing interval {interval}s - floor is {MIN_INTERVAL_SECONDS}s "
              f"(pass --allow-fast to override). Polling a live broker faster than "
              f"this is never legitimate.", flush=True)
        return 2

    pid_path = Path("logs/run.pid")
    if not _acquire_run_lock(pid_path):
        return 3

    deadline = date.fromisoformat(cfg.deadline)
    n = 0
    print(f"[run] pid {__import__('os').getpid()} looping until {deadline}; "
          f"open={interval}s closed={closed_interval}s"
          + (f"; stopping after {max_ticks} ticks" if max_ticks else ""), flush=True)
    while date.today() <= deadline:
        if max_ticks and n >= max_ticks:
            print(f"[run] reached --max-ticks {max_ticks}, stopping", flush=True)
            break
        n += 1
        open_now = False
        try:
            r = await run_tick(cfg, verbose=True)
            open_now = bool(r.get("market_open", r.get("status") != "housekeeping"))
        except Exception as exc:  # noqa: BLE001 - a bad tick must not end the run
            print(f"[run] tick {n} failed, continuing: {exc!r}", flush=True)
        await asyncio.sleep(interval if open_now else closed_interval)
    print(f"[run] deadline {deadline} reached after {n} ticks", flush=True)
    return 0


async def _prompts() -> int:
    from . import local_tools, prompts
    shared: dict = {}
    tools = [local_tools.build_simulate_experiments(shared),
             local_tools.build_size_position(None, 1.0, 0),
             local_tools.build_record_position(None, "d")]
    print(prompts.render_inventory(prompts.inventory(tools)))
    return 0


async def _lessons(action: str) -> int:
    from . import lessons
    from .elfmem_adapter import ElfmemAdapter

    if action == "show":
        for l in lessons.LESSONS:
            print(f"\n[{l.key}]  tags={list(l.tags)}")
            print(f"  cue: {l.cue}")
            print(f"  {l.text[:200]}...")
        print()
        return 0

    cfg = config_mod.load()
    mem = await ElfmemAdapter.build(cfg.paths.state / "elfmem.db")
    try:
        if action == "seed":
            r = await lessons.seed(mem.mem)
            print(f"seeded={r['created']} already_present={r['skipped']}")
            return 0
        # verify: can each lesson actually be RECALLED by its own cue? Stored
        # is not recalled, and only a retrieval check proves it (D-041).
        await mem.begin()
        missing = []
        for l in lessons.LESSONS:
            hits = await mem.mem.recall(l.cue, frame="attention", top_k=6)
            if not any(f"[{l.key}]" in getattr(h, "content", "") for h in hits):
                missing.append(l.key)
            else:
                rank = next(i for i, h in enumerate(hits, 1)
                            if f"[{l.key}]" in getattr(h, "content", ""))
                print(f"  ok   {l.key:<38} recalled at rank {rank}")
        await mem.end()
        for k in missing:
            print(f"  MISS {k:<38} not recalled by its own cue")
        print(f"\n{len(lessons.LESSONS) - len(missing)}/{len(lessons.LESSONS)} "
              f"lessons recallable by their cue.")
        return 1 if missing else 0
    finally:
        await mem.close()


def _usage() -> int:
    from . import usage

    cfg = config_mod.load(quiet=True)
    led = usage.UsageLedger(cfg.paths.state / "usage.jsonl", cfg.pricing)
    print(usage.render(led.summary()))
    return 0


def _ledger() -> int:
    from . import ledger as ledger_mod

    cfg = config_mod.load(quiet=True)
    book = ledger_mod.Ledger(cfg.paths.state / "ledger.jsonl")
    s = book.summary()
    print(f"\n=== pre-registration ledger ===\n")
    print(f"  theses considered (N for multiple-testing): {s['trials']}")
    print(f"  traded {s['traded']} | declined {s['declined']} | "
          f"resolved {s['resolved']} | pending {s['pending']}")
    if s["hit_rate"] is not None:
        print(f"  hit rate on resolved: {s['hit_rate']:.0%}")
    print()
    for e in book.all()[-15:]:
        state = ("HELD" if e.outcome else "MISSED") if e.outcome is not None else "pending"
        tag = "traded" if e.traded else "declined"
        print(f"  [{tag:>8}] {e.underlying:<6} {e.probability:>4.0%} "
              f"[{e.band_low},{e.band_high}] by {e.horizon}  {state}")
        print(f"             {e.claim[:88]}")
    print()
    return 0


def _health() -> int:
    from . import health
    from .positions import PositionStore

    cfg = config_mod.load(quiet=True)
    store = PositionStore(cfg.paths.wiki)
    findings = health.check(cfg.paths.journal, store.all())
    print(health.render(findings))
    return 1 if any(f[0] == health.BAD for f in findings) else 0


async def _constitution(action: str) -> int:
    from . import constitution
    from .elfmem_adapter import ElfmemAdapter

    if action == "show":
        print(constitution.render())
        print(f"Budget: {constitution.estimate_tokens()} tokens of "
              f"{constitution.SELF_FRAME_TOKEN_BUDGET} in the SELF frame "
              f"(ceiling {constitution.CONSTITUTION_TOKEN_CEILING}).")
        return 0

    cfg = config_mod.load()
    mem = await ElfmemAdapter.build(cfg.paths.state / "elfmem.db")
    try:
        if action == "reseed":
            await constitution.purge(mem.mem)
            r = await constitution.seed(mem.mem)
            print(f"reseeded={r['created']}")
            return 0

        if action == "seed":
            r = await constitution.seed(mem.mem)
            print(f"seeded={r['created']} already_present={r['skipped']} total={r['total']}")
            print("SELF blocks queue in the inbox until consolidation; "
                  "run `trdrbot constitution verify` after the next housekeeping tick.")
            return 0

        if action == "verify":
            # The check that matters: does the frame ACTUALLY render all ten?
            # Greedy budget rendering drops overflow silently, so counting
            # stored blocks proves nothing about what the agent will see.
            fr = await mem.self_frame()
            text = fr.text or ""
            missing = [p.key for p in constitution.PRINCIPLES
                       if p.text.split(".")[0][:40] not in text]
            print(f"SELF frame renders {len(fr.blocks)} block(s), "
                  f"~{len(text)//4} tokens.\n")
            print(text[:1500])
            print()
            if missing:
                print(f"MISSING from the rendered frame: {missing}")
                print("These principles are stored but the agent never sees them.")
                return 1
            print(f"All {len(constitution.PRINCIPLES)} principles render. ")
            return 0

        if action == "review":
            r = await mem.mem.review_constitutional()
            if getattr(r, "insufficient_history", False):
                print("insufficient_history: not enough operational record to judge drift.")
                print("Expected here - review needs ~20 recently-reinforced blocks and "
                      "blocks at least 30 days old (elfmem ReviewConfig defaults).")
                return 0
            props = getattr(r, "proposals", []) or []
            if not props:
                print("No drift proposals. The constitution matches operational behaviour.")
                return 0
            print(f"{len(props)} PROPOSED amendment(s) - none applied. "
                  f"Ratify explicitly if you agree:\n")
            for pr in props:
                print(f"- block {getattr(pr,'block_id','?')} "
                      f"(drift {getattr(pr,'drift_score',0):.2f})")
                print(f"  proposed: {getattr(pr,'proposed_content','')[:300]}")
                print(f"  rationale: {getattr(pr,'rationale','')[:300]}\n")
            return 0
    finally:
        await mem.close()
    return 0


async def _muse() -> int:
    from . import ledger as ledger_mod, muse
    from .journal import Journal
    from .wiki import Wiki

    cfg = config_mod.load()
    tools = {t.name: t for t in await mcp_client.get_tools(cfg)}
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    book = ledger_mod.Ledger(cfg.paths.state / "ledger.jsonl")
    r = await muse.run(tools, cfg, inbox, Wiki(cfg.paths.wiki),
                       Journal(cfg.paths.journal), book)
    print(f"muse complete: {r['candidates']} candidates, {r['emitted']} emitted")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="trdrbot")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="verify config, secrets and MCP connectivity")

    inj = sub.add_parser("inject", help="write an observation into the inbox")
    inj.add_argument("--type", default="manual", help="item type")
    inj.add_argument("--payload", help="JSON payload")

    tk = sub.add_parser("tick", help="run one tick end to end")
    tk.add_argument("--force", action="store_true",
                    help="run the decide path even when the market is closed")

    jrn = sub.add_parser("journal", help="show journal entries")
    jrn.add_argument("-n", type=int, default=20)

    sub.add_parser("calibration", help="show forecast calibration (Brier/Murphy)")
    sub.add_parser("research", help="run the daily research cycle now")
    sub.add_parser("discover", help="news-driven company discovery + thesis building")
    sub.add_parser("muse", help="creative theses by random concept collision")
    sub.add_parser("health", help="detect subsystems that run but never produce")
    sub.add_parser("prompts", help="inventory every prompt the models read")
    sub.add_parser("usage", help="LLM token usage and cost, by model and role")
    sub.add_parser("ledger", help="every thesis ever formed, traded or declined")
    les = sub.add_parser("lessons", help="measured lessons in evolving memory")
    les.add_argument("action", choices=["show", "seed", "verify"], default="show", nargs="?")
    run = sub.add_parser("run", help="loop ticks continuously until the deadline")
    run.add_argument("--interval", type=int, default=300,
                     help="seconds between ticks while the market is open (default 300)")
    run.add_argument("--closed-interval", type=int, default=1800,
                     help="seconds between ticks while closed (default 1800)")
    run.add_argument("--max-ticks", type=int, default=0,
                     help="stop after N ticks (0 = run to the deadline). Use for smoke "
                          "tests so they terminate themselves instead of needing a kill")
    run.add_argument("--allow-fast", action="store_true",
                     help="permit an interval below the safety floor")
    con = sub.add_parser("constitution", help="the epistemic constitution in elfmem's SELF frame")
    con.add_argument("action", choices=["show", "seed", "verify", "review", "reseed"], default="show",
                     nargs="?", help="show text | seed into elfmem | verify it renders | "
                                     "review for drift (PROPOSES only, never accepts)")

    args = p.parse_args()
    if args.cmd == "doctor":
        sys.exit(asyncio.run(_doctor()))
    elif args.cmd == "inject":
        sys.exit(_inject(args))
    elif args.cmd == "tick":
        sys.exit(asyncio.run(_tick(getattr(args, "force", False))))
    elif args.cmd == "journal":
        sys.exit(_journal(args))
    elif args.cmd == "calibration":
        sys.exit(_calibration())
    elif args.cmd == "research":
        sys.exit(asyncio.run(_research()))
    elif args.cmd == "discover":
        sys.exit(asyncio.run(_discover()))
    elif args.cmd == "muse":
        sys.exit(asyncio.run(_muse()))
    elif args.cmd == "health":
        sys.exit(_health())
    elif args.cmd == "prompts":
        sys.exit(asyncio.run(_prompts()))
    elif args.cmd == "usage":
        sys.exit(_usage())
    elif args.cmd == "ledger":
        sys.exit(_ledger())
    elif args.cmd == "lessons":
        sys.exit(asyncio.run(_lessons(args.action)))
    elif args.cmd == "run":
        sys.exit(asyncio.run(_run_loop(args.interval, args.closed_interval,
                                       max_ticks=args.max_ticks,
                                       allow_fast=args.allow_fast)))
    elif args.cmd == "constitution":
        sys.exit(asyncio.run(_constitution(args.action)))
