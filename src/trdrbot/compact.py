"""Boundary compaction: heavy tool results rewritten before they reach context (D-065).

Measured composition of one $0.83 decide cycle (553k input tokens, 7 calls):

  tool schemas        20,875 tok/call - 71% of it for 55 tools NEVER used once
  one option chain    ~15,000 tok     - re-sent on every subsequent agent turn
  everything else     ~8-10k/call     - prompt, positions, memory, inbox

So the two levers, in order, and both IMPROVE accuracy while cutting cost:

**1. Tool allowlist** (config `decide.tools`). Binding 72 tools costs ~21k
tokens per call; the agent has ever used 17. Distractor tools are not free
context - tool-selection error rates rise with menu size, so the unused 55
were actively hurting the decision while costing ~104k tokens per cycle.

**2. Result compaction** (this module). One option-chain contract arrives as
~850 chars of five OHLC bars and exchange metadata; the decision needs one
line: strike, side, bid x size, ask x size, last. A 100-contract page is 61k
chars of which perhaps 4k is decision-relevant - and burying the relevant rows
in the middle of 57k of noise is precisely the lost-in-the-middle regime where
model recall degrades. Skimming the fat is not a compromise between cost and
accuracy; it serves both.

Rules of the layer:

- The tool INTERFACE is untouched - same name, same schema, same arguments.
  Only the result is rewritten, so the agent's tool-use behaviour and every
  guard (tool_guard, whole-book redirect) compose unchanged.
- **Fail open, loudly.** If a payload does not parse as expected, the ORIGINAL
  result passes through and the mismatch is printed. A compactor that returns
  an empty string on surprise would starve the decision silently - the exact
  null-path class this project keeps finding (D-038).
- Trading data survives compaction untouched in VALUE - prices and sizes are
  reproduced verbatim, never rounded. What is dropped is repetition (five bars
  per contract) and metadata (exchange codes, update timestamps).
"""

from __future__ import annotations

import json
from typing import Any

from . import optmath

#: Strikes further than this from the inferred at-the-money level are dropped.
#: Wide enough for any wing this book trades (the widest so far was ~4% OTM);
#: an agent genuinely needing a 15% wing can still get it - the tail line of
#: every compacted chain says how to.
STRIKE_WINDOW = 0.12


def _mid(q: dict[str, Any]) -> float | None:
    bp, ap = q.get("bp"), q.get("ap")
    if isinstance(bp, (int, float)) and isinstance(ap, (int, float)) and ap >= bp > 0:
        return (bp + ap) / 2
    return None


def compact_option_chain(result: Any) -> Any:
    """61k chars of snapshots -> a table the decision actually reads."""
    if not isinstance(result, dict) or "snapshots" not in result:
        return result  # fail open: shape changed, pass the original through
    snaps = result["snapshots"]
    if not isinstance(snaps, dict) or not snaps:
        return result

    rows = []
    for occ, snap in snaps.items():
        meta = optmath.parse_occ(occ)
        if meta is None or not isinstance(snap, dict):
            continue
        q = snap.get("latestQuote") or {}
        t = snap.get("latestTrade") or {}
        rows.append({
            "occ": occ, "expiry": meta["expiry"], "right": meta["right"],
            "strike": meta["strike"],
            "bid": q.get("bp"), "bid_size": q.get("bs"),
            "ask": q.get("ap"), "ask_size": q.get("as"),
            "last": t.get("p"), "mid": _mid(q),
        })
    if not rows:
        return result  # nothing parsed: fail open

    # ATM inference without another network call: the strike where call and
    # put mids are closest is, by put-call parity, the forward. Falls back to
    # the median strike when one side is missing.
    by_strike: dict[float, dict[str, float]] = {}
    for r in rows:
        if r["mid"] is not None:
            by_strike.setdefault(r["strike"], {})[r["right"]] = r["mid"]
    both = [(abs(v["C"] - v["P"]), k) for k, v in by_strike.items()
            if "C" in v and "P" in v]
    if both:
        atm = min(both)[1]
    else:
        strikes = sorted({r["strike"] for r in rows})
        atm = strikes[len(strikes) // 2]

    lo, hi = atm * (1 - STRIKE_WINDOW), atm * (1 + STRIKE_WINDOW)
    kept = [r for r in rows if lo <= r["strike"] <= hi]
    dropped = len(rows) - len(kept)

    def fmt(v, width=7):
        return f"{v:>{width}.2f}" if isinstance(v, (int, float)) else " " * (width - 3) + "  -"

    lines = [f"Option chain (compacted): {len(kept)} contracts within "
             f"{STRIKE_WINDOW:.0%} of ATM~{atm:g}; {dropped} outside dropped. "
             f"Prices verbatim, bid x size / ask x size / last."]
    for expiry in sorted({r["expiry"] for r in kept}):
        lines.append(f"\n== expiry {expiry} ==")
        lines.append(f"{'strike':>8} {'C bid x sz':>12} {'C ask x sz':>12} {'C last':>7}"
                     f" | {'P bid x sz':>12} {'P ask x sz':>12} {'P last':>7}")
        per = {}
        for r in kept:
            if r["expiry"] == expiry:
                per.setdefault(r["strike"], {})[r["right"]] = r
        for strike in sorted(per):
            c, p = per[strike].get("C"), per[strike].get("P")

            def side(x):
                if not x:
                    return f"{'-':>12} {'-':>12} {'-':>7}"
                b = f"{x['bid']:.2f}x{x['bid_size']}" if x["bid"] is not None else "-"
                a = f"{x['ask']:.2f}x{x['ask_size']}" if x["ask"] is not None else "-"
                return f"{b:>12} {a:>12} {fmt(x['last'])}"

            lines.append(f"{strike:>8g} {side(c)} | {side(p)}")
    if result.get("next_page_token"):
        lines.append("\n(more strikes exist on further pages)")
    lines.append(f"\nNeed strikes outside the {STRIKE_WINDOW:.0%} window? Call again with "
                 f"strike_price_gte/strike_price_lte set to the range you want.")
    return "\n".join(lines)


def compact_news(result: Any) -> Any:
    """Full articles -> headline, source, symbols, time. The agent reasons from
    headlines; article bodies at ~2k chars each are summary-resistant filler."""
    if not isinstance(result, dict) or "news" not in result:
        return result
    items = result.get("news")
    if not isinstance(items, list) or not items:
        return result
    lines = [f"News ({len(items)} items, headlines only):"]
    for it in items:
        if not isinstance(it, dict):
            continue
        lines.append(f"- [{str(it.get('created_at',''))[:16]}] {it.get('headline')} "
                     f"| {it.get('source')} | {it.get('symbols')}")
    return "\n".join(lines)


#: tool name -> result rewriter. Adding one is one entry; anything not listed
#: passes through untouched.
COMPACTORS = {
    "get_option_chain": compact_option_chain,
    "get_news": compact_news,
}


def wrap_heavy_tools(tools: list[Any]) -> list[Any]:
    """Attach result compaction to the tools that need it. Interface unchanged."""
    for t in tools:
        fn = COMPACTORS.get(getattr(t, "name", ""))
        if fn is None:
            continue
        original = t.coroutine

        async def _compacted(*args: Any, __orig=original, __fn=fn, __name=t.name, **kw: Any) -> Any:
            result = await __orig(*args, **kw)
            try:
                before = len(result if isinstance(result, str) else json.dumps(result, default=str))
                out = __fn(result)
                after = len(out if isinstance(out, str) else json.dumps(out, default=str))
                if after < before:
                    print(f"[compact] {__name}: {before:,} -> {after:,} chars")
                return out
            except Exception as exc:  # noqa: BLE001 - fail open, loudly
                print(f"[compact] {__name} compaction failed, passing original through: {exc!r}")
                return result

        t.coroutine = _compacted
    return tools
