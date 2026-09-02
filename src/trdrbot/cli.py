"""CLI - every command the system exposes to a human.

`trdrbot --help` is the list, and it is generated from the parser below rather
than restated here: this docstring enumerated four commands for most of the
project's life while the parser grew to seventeen, and the first thing anyone
reads should not be the thing most likely to be stale.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import failures, ids, mcp_client
from . import llm as llm_mod
from . import store as store_mod
from .inbox import Inbox
from .journal import Journal
from .lock import tick_lock
from .tick import run_tick


async def _doctor() -> int:
    print("[doctor] loading config...")
    cfg = config_mod.load()
    print(f"  model:     {cfg.model}")
    print(f"  watchlist: {cfg.watchlist}")
    print(f"  deadline:  {cfg.deadline or 'none - running indefinitely'}")
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
        # llm.ROLES, not a hardcoded five: the list used to omit coach_mutate
        # and news_extract under a comment claiming it probed EVERY model, and
        # their specs were covered only incidentally by other chains.
        for role in llm_mod.ROLES:
            for spec in cfg.model_chain(role):
                if spec in seen:
                    continue
                seen.add(spec)
                try:
                    real_spec, conn_kwargs = cfg.resolve_model_spec(spec)
                    m = init_chat_model(real_spec, max_tokens=16, max_retries=0, **conn_kwargs)
                    r = await m.ainvoke("Say: ok")
                    served = (r.response_metadata or {}).get("model_name", "?")
                    print(f"  OK   {spec:<34} -> {served}")
                    reachable += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  DEAD {spec:<34} {type(exc).__name__}: {str(exc)[:80]}")
        # A role key the CODE does not have is silently ignored by
        # `model_chain` - that role just runs the default chain, which is the
        # intended degradation but is invisible. `doctor` exists to catch
        # exactly this class, and it was iterating the code's roles, so it
        # could never see a typo in the config's (I-53).
        unknown_roles = sorted(set((cfg.raw.get("llm") or {}).get("roles") or {})
                               - set(llm_mod.ROLES))
        for key in unknown_roles:
            print(f"  WARN llm.roles.{key} is not a role this code has - it is "
                  f"ignored, and that role runs the default chain. Known: "
                  f"{', '.join(llm_mod.ROLES)}")
        print(f"  {reachable}/{len(seen)} configured models reachable")
        if reachable == 0:
            print("  NO MODEL IS REACHABLE - the system cannot make a decision.")
            return 1
        print(f"  reachable - replied {str(reply.content)[:40]!r}")
    except Exception as exc:  # noqa: BLE001
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
    # THE SAME TWO BOUNDS THE RUN LOOP HAS (I-110, I-102). This is the
    # run.sh/launchd path, and it had neither: `run_tick` was awaited bare, so
    # a wedged MCP subprocess spawn or a hung broker read stalled the process
    # indefinitely while holding the lock. The lock's staleness window is the
    # same watchdog, or a second cron tick would break a lock this process is
    # still legitimately holding.
    outer_timeout = cfg.watchdog_seconds * OUTER_WATCHDOG_FACTOR
    try:
        with tick_lock(cfg.paths.state / "tick.lock", stale_after=outer_timeout):
            await asyncio.wait_for(run_tick(cfg, force_decide=force),
                                   timeout=outer_timeout)
    except BlockingIOError as exc:
        print(f"[tick] {exc}")
        return 0
    except TimeoutError:
        print(f"[tick] exceeded the {outer_timeout}s watchdog and was cancelled")
        return 1
    except Exception as exc:  # noqa: BLE001 - the loop degrades; so does this
        # `run.sh` points cron/launchd at this path, where a raw traceback is
        # the least useful thing an operator can be handed. The run loop has
        # classified-and-continued since it existed; this classifies and exits
        # non-zero, which is the single-shot equivalent. No journalling from
        # here - the journal write may be the very thing that failed.
        cause = failures.classify(exc)
        print(f"[tick] failed ({cause}): {failures.advice(cause, exc)}")
        return 1
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
    from . import ledger as ledger_mod
    from .calibration import CalibrationStore

    cfg = config_mod.load()
    store = CalibrationStore(cfg.paths.state / "forecasts.jsonl")
    # THE SAME number the ladder and the sizing tool read. This command used to
    # score closed positions only, so it reported one calibration while size
    # was gated on another - and the declined-thesis forecasts D-052 exists to
    # accumulate were invisible in the very report you would check them in.
    book = ledger_mod.Ledger(cfg.paths.state / "ledger.jsonl")
    cal = store.score(ledger_mod.as_forecasts(book.resolved()))
    pending = store.pending()
    pending_ledger = [e for e in book.all()
                      if e.outcome is None and e.scoreable() and e.probability_stated]

    print(f"\n{cal.verdict()}\n")
    if cal.n:
        print(f"  Brier score  : {cal.brier:.4f}   (0 = perfect, 0.25 = coin flip)")
        print("  reliability  : "
              + (f"{cal.reliability:.4f}   (lower is better - overconfidence signal)"
                 if cal.reliability is not None else
                 "unmeasured   (within-bin noise exceeds the estimate at this n)"))
        print(f"  resolution   : {cal.resolution:.4f}   (higher is better - discrimination)")
        print(f"  uncertainty  : {cal.uncertainty:.4f}   (irreducible, given the base rate)")
        print(f"  base rate    : {cal.base_rate:.0%} of resolved forecasts came in")
    print(f"\n  sample       : {cal.sample_note()}")
    print(f"\n  resolved: {cal.n}   pending: {len(pending) + len(pending_ledger)}")
    for f in pending:
        print(f"    - position {f.position_id}: forecast {f.probability:.0%}, not yet resolved")
    for e in sorted(pending_ledger, key=lambda x: x.horizon):
        print(f"    - {e.horizon} {e.underlying}: {e.probability:.0%} "
              f"[{e.band_low}, {e.band_high}]")
    return 0


async def _research(force: bool = False) -> int:
    from . import research
    from .journal import Journal
    from .wiki import Wiki

    cfg = config_mod.load()
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    # One session for the whole cycle: research fetches bars and chains for the
    # entire universe, and per-call sessions respawn `uvx alpaca-mcp-server`
    # for every one of them (mcp_client.session_tools).
    async with mcp_client.session_tools(cfg) as tl:
        tools = {t.name: t for t in tl}
        r = await research.run(tools, cfg, inbox, Wiki(cfg.paths.wiki),
                               Journal(cfg.paths.journal), force=force)
    print(f"research skipped: {r['skipped']} (pass --force)" if r.get("skipped")
          else f"research complete: {r}")
    return 0


async def _discover() -> int:
    from . import discovery
    from .journal import Journal
    from .wiki import Wiki

    cfg = config_mod.load()
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    async with mcp_client.session_tools(cfg) as tl:
        tools = {t.name: t for t in tl}
        r = await discovery.run(tools, cfg, inbox, Wiki(cfg.paths.wiki), Journal(cfg.paths.journal))
    print(f"discovery complete: nominees={r['nominees']} opportunities={r['opportunities']}")
    return 0


#: No legitimate reason to poll a live broker faster than this. A stray
#: 5-second smoke-test loop once hammered the API and burned LLM calls for
#: half an hour before it was noticed - the floor bounds the blast radius of
#: that mistake even when process cleanup fails (D-044).
MIN_INTERVAL_SECONDS = 30


#: The tick's own watchdog bounds the LLM call (tick.py). This one bounds
#: EVERYTHING ELSE in a tick - a wedged MCP subprocess spawn, a stuck elfmem
#: call, a hung broker read - so it has to sit well above the inner bound or
#: it would fire first and mask it. 4x is a backstop, not a second policy.
OUTER_WATCHDOG_FACTOR = 4

#: Consecutive CONFIG/BUG-classified tick failures before the loop gives up.
#: A transient must never stop an unattended run (INV-8), but a failure in our
#: own config or code is deterministic - it fails identically next tick, so
#: "keep going" becomes "never trade again, quietly, with rc 0" (I-104).
#: Three, for the same reason `ORDERS_WITHOUT_SIZING` is three: one is an
#: artifact and two is a coincidence.
OWN_FAULT_LIMIT = 3


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

    Two chassis guarantees this loop went without until D-091, both specified
    long before and enforced only on the `tick` subcommand - which is to say,
    not on the path that actually runs unattended:

    - **The tick lock (INV-7).** This loop called `run_tick` directly, so a
      launchd-driven `run.sh` alongside a `trdrbot run` would interleave two
      ticks freely: two tick-counter read-modify-writes, two elfmem sessions
      on one SQLite file, two decide cycles draining one inbox batch. There
      was a second, weaker lock here (a bare pid file at a RELATIVE path, no
      timestamp, never unlinked on exit) which `tick_lock` supersedes in every
      respect - it carries a pid AND a timestamp, so a crashed run is
      stale-breakable rather than fatal.
    - **The watchdog (FM-26).** `tick.watchdog_seconds` was configured and
      read by nothing, so a hung LLM call stalled the run indefinitely, with
      no stale-lock signal to notice it by either.
    """
    from datetime import date

    from .tick import run_tick

    cfg = config_mod.load()
    # BOTH cadences (I-111). The floor guarded `--interval` only, so
    # `--closed-interval 0` ticked back to back all weekend - the same live
    # broker, the same LLM spend, through the argument nobody thought of as
    # the polling one.
    for name, seconds in (("--interval", interval), ("--closed-interval", closed_interval)):
        if seconds < MIN_INTERVAL_SECONDS and not allow_fast:
            print(f"[run] refusing {name} {seconds}s - floor is {MIN_INTERVAL_SECONDS}s "
                  f"(pass --allow-fast to override). Polling a live broker faster than "
                  f"this is never legitimate.", flush=True)
            return 2

    lock_path = cfg.paths.state / "tick.lock"
    outer_timeout = cfg.watchdog_seconds * OUTER_WATCHDOG_FACTOR
    # None means run indefinitely (D-101). The loop's job is to keep ticking;
    # a hard stop, when there is one, is an upper bound on that and not the
    # reason it exists. `--max-ticks` remains the way to bound a smoke test.
    deadline = date.fromisoformat(cfg.deadline) if cfg.deadline else None
    n = 0
    # WHO IS RUNNING, AND ON WHAT CODE (D-108). A long-lived process holds the
    # config and every module in memory from the moment it started. On
    # 2026-09-02 the live loop turned out to have been started 40 hours and
    # SEVEN decisions earlier: the discovery corpse, the deadlocked Coach, the
    # single-name watchlist and a deadline two days from force-closing the
    # whole book were all still executing, while the repo said they were
    # fixed. Nothing detected it. This file is what `trdrbot health` compares
    # against HEAD, so "the live process predates N commits" is a finding.
    _git_head = ""
    try:
        import subprocess
        _git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cfg.paths.root,
                                   capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is best-effort, never blocking
        pass
    store_mod.write_atomic(cfg.paths.state / "run.json", json.dumps({
        "pid": os.getpid(), "started": ids.utc_now().isoformat(),
        "git_sha": _git_head, "argv": sys.argv[1:]}))
    print(f"[run] pid {os.getpid()} looping "
          + (f"until {deadline}" if deadline else "indefinitely (no deadline)")
          + f"; open={interval}s closed={closed_interval}s watchdog={outer_timeout}s"
          + (f"; stopping after {max_ticks} ticks" if max_ticks else ""), flush=True)
    # The market state the LAST tick observed (I-111). A failed tick knows
    # nothing about the clock, and assuming "open" made every failure poll on
    # the 5-minute cadence through a closed weekend. The last observation is
    # the best available answer; a lock SKIP still forces the open cadence,
    # because it means another process is actively trading right now.
    open_now = True
    consecutive_ours = 0
    while deadline is None or ids.market_today() <= deadline:
        if max_ticks and n >= max_ticks:
            print(f"[run] reached --max-ticks {max_ticks}, stopping", flush=True)
            break
        n += 1
        skipped = False
        try:
            with tick_lock(lock_path, stale_after=outer_timeout):
                r = await asyncio.wait_for(run_tick(cfg, verbose=True),
                                           timeout=outer_timeout)
            open_now = bool(r.get("market_open", r.get("status") != "housekeeping"))
            consecutive_ours = 0
        except BlockingIOError as exc:
            print(f"[run] {exc}", flush=True)
            skipped = True
        except TimeoutError:
            print(f"[run] tick {n} exceeded the {outer_timeout}s watchdog and was "
                  f"cancelled - continuing", flush=True)
            consecutive_ours = 0
        except Exception as exc:  # noqa: BLE001 - a bad tick must not end the run
            print(f"[run] tick {n} failed, continuing: {exc!r}", flush=True)
            # A FAILURE THAT IS OURS DOES NOT GET RETRIED FOREVER (I-104). A
            # transient deserves the loop's whole point - keep ticking, an
            # eight-day run meets provider blips - but a CONFIG or BUG failure
            # is deterministic: it will fail identically next tick, and the
            # loop returned 0 forever while never deciding, never archiving the
            # inbox, and reading green because the decision row it wrote before
            # failing counted as output. Three in a row is not weather.
            cause = failures.classify(exc)
            consecutive_ours = (consecutive_ours + 1
                                if cause in (failures.Cause.CONFIG, failures.Cause.BUG)
                                else 0)
            if consecutive_ours >= OWN_FAULT_LIMIT:
                print(f"\n[run] STOPPING: {consecutive_ours} consecutive {cause.value} "
                      f"failures - this is ours, not the market's, and it will fail "
                      f"identically next tick.\n\n  {failures.advice(cause, exc)}\n",
                      flush=True)
                return 2
        await asyncio.sleep(interval if (open_now or skipped) else closed_interval)
    print(f"[run] stopped after {n} ticks"
          + (f" - deadline {deadline} reached" if deadline else ""), flush=True)
    return 0


async def _prompts() -> int:
    from . import local_tools, prompts
    shared = local_tools.SharedContext()
    tools = [local_tools.build_simulate_experiments(shared),
             local_tools.build_size_position(None, 1.0),
             local_tools.build_record_position(None, "d")]
    print(prompts.render_inventory(prompts.inventory(tools, config_mod.load())))
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
    print("\n=== pre-registration ledger ===\n")
    print(f"  theses considered (N for multiple-testing): {s['trials']}")
    print(f"  traded {s['traded']} | declined {s['declined']} | "
          f"resolved {s['resolved']} | pending {s['pending']}")
    if s["hit_rate"] is not None:
        print(f"  hit rate on resolved: {s['hit_rate']:.0%}")
    # Gate regret (D-104): what each gate refused, and how much of it held.
    # Read against the admitted hold rate, because that is the counterfactual.
    regret, baseline = ledger_mod.gate_regret(book.all())
    if regret:
        print(f"\n  gate regret (admitted claims held "
              f"{baseline:.0%})" if baseline is not None else "\n  gate regret")
        for g in sorted(regret.values(), key=lambda x: -x.rejected):
            print(f"    {g.gate:<18} {g.read(baseline)}")
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
    print(health.render(findings, health.scope_label(cfg.paths.journal)))
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


async def _muse(force: bool = False) -> int:
    from . import ledger as ledger_mod
    from . import muse
    from .journal import Journal
    from .wiki import Wiki

    cfg = config_mod.load()
    inbox = Inbox(cfg.paths, max_retries=cfg.max_retries)
    book = ledger_mod.Ledger(cfg.paths.state / "ledger.jsonl")
    async with mcp_client.session_tools(cfg) as tl:
        tools = {t.name: t for t in tl}
        r = await muse.run(tools, cfg, inbox, Wiki(cfg.paths.wiki),
                           Journal(cfg.paths.journal), book, force=force)
    if r.get("skipped"):
        print(f"muse skipped: {r['skipped']} ({r.get('ran_today')} run(s) today). "
              f"Pass --force to override.")
    else:
        print(f"muse complete: {r['candidates']} candidates, {r['emitted']} emitted")
    return 0


async def _coach(action: str) -> int:
    from . import coach, ids
    from .journal import Journal

    cfg = config_mod.load()
    journal = Journal(cfg.paths.journal)

    if action == "pulse":
        applied = coach.reconcile(cfg)
        for a in applied:
            print(f"reconciled a logged-but-unapplied promotion: {a}")
        r = await coach.pulse(cfg, journal, verbose=True)
        print(f"pulse: open={r['experiments_open']} opened={r['opened'] or '-'} "
              f"closed={r['closed'] or '-'} sentinels={r['sentinels_active'] or 'none'}")
        return 0

    if not coach.enabled(cfg):
        print("coach: DISABLED in config.yaml (coach.enabled: false)\n")

    evs = coach.events(cfg)
    print("\n=== the Coach: what it is improving, and on what evidence ===\n")
    for lv in coach.LEVERS:
        st = coach.load_state(cfg, lv.name, coach.seeds().get(lv.name, ""))
        print(f"{lv.name}  ({lv.subsystem}, scored by {', '.join(lv.reward_modules)})")
        print(f"  incumbent   {st.incumbent.id} {st.incumbent.fingerprint} "
              f"({st.incumbent.origin}, since {st.incumbent.since[:16] or 'seed'})")
        if st.previous:
            print(f"  previous    {st.previous.id} {st.previous.fingerprint}")
        print(f"  state       {st.blocked or 'running'}")

        if st.exp_id and not coach.is_closed(cfg, st.exp_id):
            t = coach.tally(cfg, st.exp_id)
            if t:
                fl = coach.floors(cfg)
                outcome, reason = coach.verdict(t, fl)
                print(f"  EXPERIMENT  {t.challenger} vs {t.incumbent}  "
                      f"P(better)={t.posterior:.3f}")
                print(f"              {t.runs} paired run(s): challenger "
                      f"{t.s_c}/{t.n_c}, incumbent {t.s_i}/{t.n_i}"
                      + (f", {t.voided} voided" if t.voided else ""))
                print(f"              {'-> ' + outcome + ': ' + reason if outcome else 'still gathering evidence'}")
        else:
            print("  experiment  none open")

        hist = [r for r in evs if r.get("kind") == "experiment_closed"
                and r.get("lever") == lv.name][-3:]
        for r in reversed(hist):
            print(f"  past        {r.get('challenger')} {r.get('outcome'):<18} "
                  f"{str(r.get('reason', ''))[:70]}")
        print()

    day = ids.utc_now().date().isoformat()
    trials = sum(1 for r in evs if r.get("kind") == "trial_result"
                 and str(r.get("ts", ""))[:10] == day)
    proms = sum(1 for r in evs if r.get("kind") == "experiment_closed"
                and r.get("outcome") == "promoted")
    print(f"{trials} trial(s) scored today, {proms} promotion(s) all time. "
          f"`trdrbot report` charts the trajectory.\n")
    return 0


def _risk(proposed: float | None) -> int:
    """What the risk appetite is doing, and what another value would do.

    The operator has to pick a number in a range whose consequences are not
    obvious, and "did my edit take effect?" otherwise has no answer short of
    reading the journal. Deterministic and OFFLINE - it composes the same
    `competence.assess` and `sizing.size_position` production runs, off the last
    journalled equity, so it never touches the broker and never disagrees with
    the live posture. The stochastic half of the question (what an appetite BUYS
    over many trades) lives in the risk explorer, which is where a distribution
    belongs.
    """
    from . import competence, sizing
    from . import store as store_mod
    from .calibration import CalibrationStore
    from .ledger import Ledger
    from .positions import PositionStore

    cfg = config_mod.load(quiet=True)
    rows, _ = store_mod.read_jsonl(cfg.paths.journal)
    comp_rows = [r for r in rows if r.get("kind") == "competence"]
    if not comp_rows:
        print("No competence rows in the journal yet - run a tick first.")
        return 1
    last = comp_rows[-1]
    equity = float(last.get("equity") or 0.0)
    high_water = float(last.get("high_water") or equity)

    calib = CalibrationStore(cfg.paths.state / "forecasts.jsonl")
    book = Ledger(cfg.paths.state / "ledger.jsonl")
    cal = calib.score(_as_forecasts(book))
    positions = PositionStore(cfg.paths.wiki).all()

    def posture(a: float) -> competence.Competence:
        return competence.assess(
            resolved=cal.n, reliability=cal.reliability, positions=positions,
            equity=equity, high_water=high_water, effective=cal.n_eff, appetite=a)

    current = cfg.risk_appetite
    cols = [("now", current)] + ([("proposed", proposed)] if proposed is not None else [])
    ps = [posture(a) for _, a in cols]

    print("\nRisk appetite    " + "  ->  ".join(f"{p.appetite:.2f}x" for p in ps)
          + "          (config.yaml: trading.risk_appetite)")
    print(f"Competence       {ps[0].tier.upper()} - {cal.n} resolved, "
          + (f"{ps[0].attributable_rate:.0%} attributable"
             if ps[0].attributable_rate is not None else "attribution unmeasured")
          + f", Kelly x{ps[0].kelly_multiplier / ps[0].appetite:.3f} earned\n")

    head = "".join(f"{lbl + f' ({a:.2f}x)':>22}" for lbl, a in cols)
    print(f"  {'':<22}{head}")
    for name, get in (("book cap", lambda p: p.book_cap),
                      ("per-name cap", lambda p: p.underlying_cap),
                      ("per-position cap", lambda p: p.position_cap),
                      ("exploration floor", lambda p: p.seed_fraction)):
        print(f"  {name:<22}"
              + "".join(f"{get(p):>10.2%} {'$' + format(get(p) * equity, ',.0f'):>11}"
                        for p in ps))
    print(f"  {'Kelly multiplier':<22}"
          + "".join(f"{'x' + format(p.kelly_multiplier, '.4f'):>22}" for p in ps))
    print(f"  {'realised appetite':<22}"
          + "".join(f"{format(p.realised_appetite, '.2f') + 'x':>22}" for p in ps))
    for p, (lbl, _) in zip(ps, cols, strict=True):
        if abs(p.realised_appetite - p.appetite) > 1e-9:
            print(f"    ^ {lbl}: the {p.tier.upper()} book cap is pinned at the "
                  f"{competence.BOOK_CEILING:.0%} ruin bound, so "
                  f"{p.appetite:.2f}x only realises {p.realised_appetite:.2f}x")

    # What the NEXT trade would be, on a structure the book has actually traded.
    # Per-contract risk comes off the position's own legs rather than a stored
    # count: `max_loss_usd` is the whole position's, and the quantity that
    # produced it is the leg qty (D-099).
    def _per_contract(p: Any) -> float | None:
        qty = abs(int((p.legs or [{}])[0].get("qty") or 0)) if p.legs else 0
        return p.max_loss_usd / qty if (p.max_loss_usd and qty) else None

    priced = [x for x in (_per_contract(p) for p in positions) if x]
    if priced:
        per = priced[-1]
        print(f"\n  next trade, on a structure like the book's (${per:,.0f}/contract):")
        for p, (lbl, _) in zip(ps, cols, strict=True):
            d = sizing.size_position(
                equity=equity, stated_confidence=0.40, max_profit=per * 1.9,
                max_loss=-per, calibration=cal, posture=p, underlying="SPY",
                payoff_ratio=1.9)
            print(f"    {lbl:<10} {d.contracts:>3} contracts "
                  f"({d.fraction_of_equity:.2%}), binding: {d.binding or 'refused'}")
    else:
        print("\n  (no priced position on the book yet, so no next-trade preview)")

    at_risk = sum(p.max_loss_usd or 0.0 for p in positions
                  if getattr(p, "status", "") in ("open", "opening", "closing"))
    if at_risk:
        print(f"\n  book carries ${at_risk:,.0f} ({at_risk / equity:.2%} of equity) - "
              + ", ".join(f"{at_risk / (p.book_cap * equity):.0%} of the {lbl} book cap"
                          for p, (lbl, _) in zip(ps, cols, strict=True))
              + (f"; all of it {positions[-1].underlying.upper()}, against a per-name cap of "
                 f"${ps[0].underlying_cap * equity:,.0f}"
                 if len({q.underlying for q in positions if q.max_loss_usd}) == 1 else ""))
    if proposed is not None and proposed != current:
        print(f"\nTo apply: set `trading.risk_appetite: {proposed}` in config.yaml.")
        print("  run.sh / launchd: next tick.   `trdrbot run`: restart it.\n")
    else:
        print()
    return 0


def _as_forecasts(book: Any) -> list[Any]:
    """Resolved ledger theses as calibration forecasts - the SAME sample the
    ladder is assessed on (D-052), so this preview cannot disagree with it."""
    from . import ledger as ledger_mod
    return ledger_mod.as_forecasts(book.resolved())


def _report() -> int:
    from . import report

    cfg = config_mod.load()
    out = report.write(cfg)
    print(f"wrote {out}")
    return 0


def _site(out: Path | None) -> int:
    from . import site_export
    return site_export.export(out=out) if out else site_export.export()


def _modelcal(action: str) -> int:
    """The MODEL layer's calibration (D-089) - the counterpart of
    `trdrbot calibration`, which scores the agent."""
    import json as _json

    from . import market_stats as ms

    cfg = config_mod.load()
    path = ms.model_cal_path(cfg.paths.state)

    if action == "fit":
        series = ms.load_all_closes(cfg.paths.state)
        if len(series) < 10:
            print(f"only {len(series)} cached return series - not enough to fit honestly")
            return 1
        print(f"fitting band inflation on {len(series)} tickers "
              f"(holdout has the veto; this takes a minute)...")
        art = ms.fit_band_inflation(series)
        path.write_text(_json.dumps(art, indent=2), encoding="utf-8")
        print(f"wrote {path}\n")

    if not path.exists():
        print("no model calibration artifact - run `trdrbot modelcal fit`")
        print("(the bootstrap runs UNINFLATED until one exists; I-29 measured it\n"
              "  overconfident where credit spreads live - the magnitude is under\n"
              "  re-measurement since D-119 corrected the harness's units)")
        return 0

    art = _json.loads(path.read_text(encoding="utf-8"))
    print(f"fitted {str(art.get('fitted', ''))[:16]}  "
          f"bounds {art.get('bounds')}  "
          f"tickers {(art.get('sample') or {}).get('tickers')}")
    print(f"\n{'horizon':>8} {'k':>6} {'holdout Brier raw -> fit':>26}")
    for h, d in sorted((art.get("holdout") or {}).items(), key=lambda kv: int(kv[0])):
        print(f"{h + 'd':>8} {d.get('chosen'):>6} "
              f"{d.get('test_brier_raw')} -> {d.get('test_brier_fit')}"
              + ("   (holdout vetoed the fit)" if d.get("chosen") == 1.0
                 and d.get("k_star") != 1.0 else ""))
    print(f"\nprovenance: {art.get('provenance', '')}")
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
    res = sub.add_parser("research", help="run the daily research cycle now")
    res.add_argument("--force", action="store_true",
                     help="run even if it already ran today, or it is Saturday")
    sub.add_parser("discover", help="news-driven company discovery + thesis building")
    mus = sub.add_parser("muse", help="creative theses by random concept collision")
    mus.add_argument("--force", action="store_true",
                     help="run even if today's cap is already reached")
    sub.add_parser("health", help="detect subsystems that run but never produce")
    sub.add_parser("prompts", help="inventory every prompt the models read")
    sub.add_parser("usage", help="LLM token usage and cost, by model and role")
    sub.add_parser("ledger", help="every thesis ever formed, traded or declined")
    les = sub.add_parser("lessons", help="measured lessons in evolving memory")
    les.add_argument("action", choices=["show", "seed", "verify"], default="show", nargs="?")
    coa = sub.add_parser("coach", help="the self-improvement loop: levers, trials, promotions")
    coa.add_argument("action", choices=["status", "pulse"], default="status", nargs="?")
    rsk = sub.add_parser("risk", help="the operator's risk appetite, and what another "
                                      "value would do to the live book")
    rsk.add_argument("appetite", type=float, nargs="?", default=None,
                     help="preview this appetite alongside the current one")
    sub.add_parser("report", help="write data/report.html - gauges, experiments, actions")
    mc = sub.add_parser("modelcal", help="the model layer's calibration: fitted bootstrap inflation")
    mc.add_argument("action", choices=["status", "fit"], default="status", nargs="?")
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
    site = sub.add_parser("site", help="export the agent's record to web/src/lib/data/snapshot.json")
    site.add_argument("action", choices=["export"], default="export", nargs="?")
    site.add_argument("--out", type=Path, default=None, help="override the snapshot output path")

    con = sub.add_parser("constitution", help="the epistemic constitution in elfmem's SELF frame")
    con.add_argument("action", choices=["show", "seed", "verify", "review", "reseed"], default="show",
                     nargs="?", help="show text | seed into elfmem | verify it renders | "
                                     "review for drift (PROPOSES only, never accepts)")

    #: One handler per subcommand, replacing a 17-branch `elif args.cmd == "..."`
    #: chain that restated every parser name as a string literal - a typo in
    #: either half was a silent no-op the parser could not catch.
    _H: dict[str, Any] = {}
    _H["doctor"] = lambda a: asyncio.run(_doctor())
    _H["inject"] = lambda a: _inject(a)
    _H["tick"] = lambda a: asyncio.run(_tick(a.force))
    _H["journal"] = lambda a: _journal(a)
    _H["calibration"] = lambda a: _calibration()
    _H["research"] = lambda a: asyncio.run(_research(a.force))
    _H["discover"] = lambda a: asyncio.run(_discover())
    _H["muse"] = lambda a: asyncio.run(_muse(a.force))
    _H["health"] = lambda a: _health()
    _H["prompts"] = lambda a: asyncio.run(_prompts())
    _H["usage"] = lambda a: _usage()
    _H["ledger"] = lambda a: _ledger()
    _H["lessons"] = lambda a: asyncio.run(_lessons(a.action))
    _H["coach"] = lambda a: asyncio.run(_coach(a.action))
    _H["risk"] = lambda a: _risk(a.appetite)
    _H["report"] = lambda a: _report()
    _H["modelcal"] = lambda a: _modelcal(a.action)
    _H["run"] = lambda a: asyncio.run(_run_loop(a.interval, a.closed_interval,
                                       max_ticks=a.max_ticks, allow_fast=a.allow_fast))
    _H["constitution"] = lambda a: asyncio.run(_constitution(a.action))
    _H["site"] = lambda a: _site(a.out)

    args = p.parse_args()
    sys.exit(_H[args.cmd](args))
