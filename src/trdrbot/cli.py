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
    print(f"\n  all tools: {', '.join(names)}")
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


async def _tick() -> int:
    cfg = config_mod.load()
    try:
        with tick_lock(cfg.paths.state / "tick.lock"):
            await run_tick(cfg)
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


def main() -> None:
    p = argparse.ArgumentParser(prog="trdrbot")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="verify config, secrets and MCP connectivity")

    inj = sub.add_parser("inject", help="write an observation into the inbox")
    inj.add_argument("--type", default="manual", help="item type")
    inj.add_argument("--payload", help="JSON payload")

    sub.add_parser("tick", help="run one tick end to end")

    jrn = sub.add_parser("journal", help="show journal entries")
    jrn.add_argument("-n", type=int, default=20)

    args = p.parse_args()
    if args.cmd == "doctor":
        sys.exit(asyncio.run(_doctor()))
    elif args.cmd == "inject":
        sys.exit(_inject(args))
    elif args.cmd == "tick":
        sys.exit(asyncio.run(_tick()))
    elif args.cmd == "journal":
        sys.exit(_journal(args))
