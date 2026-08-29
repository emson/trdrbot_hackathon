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


def compact_option_chain(result: Any, config: Any = None) -> Any:
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
    # put mids are closest is, by put-call parity, the forward.
    by_strike: dict[float, dict[str, float]] = {}
    for r in rows:
        if r["mid"] is not None:
            by_strike.setdefault(r["strike"], {})[r["right"]] = r["mid"]
    both = [(abs(v["C"] - v["P"]), k) for k, v in by_strike.items()
            if "C" in v and "P" in v]
    if both:
        atm = min(both)[1]
    else:
        # One-sided page - and this is the COMMON case, not the corner one.
        # Measured live: a SPY chain request returns 100 contracts, strikes
        # 500-773, ALL CALLS, with a next page. The median-strike fallback put
        # ATM at 724 against a tape of 771.67 - 6% out, which drags the
        # retained window 6% low and can crop the strikes the agent is
        # actually trading.
        #
        # Parity again, from one side. For a call, C + K = S + extrinsic >= S,
        # so the SMALLEST C + K across the page is the tightest upper bound on
        # the forward and converges to it as the call goes deep ITM. For a put,
        # K - P = S - extrinsic <= S, so the LARGEST is the tightest lower
        # bound. On that same live page: 768.78 against 771.67, 0.4% out.
        bounds = [b for b in (
            min((v["C"] + k for k, v in by_strike.items() if "C" in v), default=None),
            max((k - v["P"] for k, v in by_strike.items() if "P" in v), default=None),
        ) if b is not None]
        if bounds:
            atm = sum(bounds) / len(bounds)
        else:
            strikes = sorted({r["strike"] for r in rows})
            atm = strikes[len(strikes) // 2]

    lo, hi = atm * (1 - STRIKE_WINDOW), atm * (1 + STRIKE_WINDOW)
    kept = [r for r in rows if lo <= r["strike"] <= hi]
    dropped = len(rows) - len(kept)
    if not kept:  # window missed the page entirely - show it rather than nothing
        kept, dropped = rows, 0

    def fmt(v, width=7):
        return f"{v:>{width}.2f}" if isinstance(v, (int, float)) else " " * (width - 3) + "  -"

    # What is actually ON this page, said plainly. A SPY request really does
    # come back as 100 calls and zero puts across strikes 500-773 with a next
    # page, so an agent pricing a put spread off page one is pricing nothing.
    # It cannot see that from a table of rows; it can from this line.
    rights = sorted({r["right"] for r in rows})
    all_strikes = sorted({r["strike"] for r in rows})
    coverage = (f"page holds {'+'.join(rights)} only" if len(rights) == 1
                else "page holds both C and P")
    lines = [f"Option chain (compacted): {len(kept)} contracts within "
             f"{STRIKE_WINDOW:.0%} of ATM~{atm:.2f}; {dropped} outside dropped. "
             f"This {coverage}, strikes {all_strikes[0]:g}-{all_strikes[-1]:g}"
             f"{', MORE PAGES EXIST' if result.get('next_page_token') else ''}. "
             f"Prices verbatim, bid x size / ask x size / last."]
    for expiry in sorted({r["expiry"] for r in kept}):
        per = {}
        for r in kept:
            if r["expiry"] == expiry:
                per.setdefault(r["strike"], {})[r["right"]] = r

        # The OCC symbol is what `place_option_order` legs and
        # `record_position` legs both require, and the table used to omit it
        # entirely - the rows carried `occ` and nothing rendered it, so the
        # agent had to reconstruct 21-character contract symbols by hand from
        # a strike and a date. Rather than repeat a long string on every row
        # (this table exists to save tokens), each section states its real
        # prefix and one WORKED EXAMPLE lifted from the page - so the encoding
        # is shown rather than described, and the strike padding that is easy
        # to get wrong is visible in an instance the agent can copy.
        sample = next((r for s in sorted(per) for r in per[s].values() if r.get("occ")), None)
        head = f"\n== expiry {expiry} =="
        if sample:
            root = str(sample["occ"])[:len(str(sample["occ"])) - 15]
            head += (f"  OCC: {root}{str(sample['occ'])[len(root):len(root) + 6]}"
                     f"[C|P][strike x1000, 8 digits]"
                     f"   e.g. {sample['strike']:g} {sample['right']} = {sample['occ']}")
        lines.append(head)
        lines.append(f"{'strike':>8} {'C bid x sz':>12} {'C ask x sz':>12} {'C last':>7}"
                     f" | {'P bid x sz':>12} {'P ask x sz':>12} {'P last':>7}")
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


def compact_news(result: Any, config: Any = None) -> Any:
    """Full articles -> dense structured lines, from the news_extract cache
    (D-066). Falls back to headline-only for any article not yet extracted -
    identical to the pre-D-066 output - so a cold cache or a disabled/failing
    extraction role degrades gracefully rather than breaking the tool."""
    if not isinstance(result, dict) or "news" not in result:
        return result
    items = result.get("news")
    if not isinstance(items, list) or not items:
        return result

    from . import news_extract

    if config is not None:
        cache = news_extract.ExtractCache(config.paths.state / "news_extracts.json")
        extracts = [cache.get(str(it.get("id"))) or news_extract.bare(it)
                    for it in items if isinstance(it, dict)]
    else:  # no config threaded through - still compact, just headline-only
        extracts = [news_extract.bare(it) for it in items if isinstance(it, dict)]

    header = (f"News ({len(extracts)} items; [sentiment conf] activity/regime/horizon | orgs | "
              f"people | symbols | \"fact\" number(type) | source date <url>):")
    return header + "\n" + news_extract.render_block(extracts)


#: tool name -> result rewriter. Adding one is one entry; anything not listed
#: passes through untouched.
COMPACTORS = {
    "get_option_chain": compact_option_chain,
    "get_news": compact_news,
}


def _unpack(result: Any) -> tuple[Any, Any] | None:
    """MCP tool result -> (payload dict, rewrap function). None if not ours.

    **This is the layer that was missing, and its absence made every compactor
    a no-op in production.** `langchain_mcp_adapters` builds its tools with
    `response_format="content_and_artifact"`, so the coroutine returns a
    2-tuple `([{"type": "text", "text": "<json>"}], artifact)` - never the dict
    the compactors were written against. Every call therefore hit their
    `isinstance(result, dict)` guard and took the fail-open path, which returns
    the ORIGINAL unchanged. It fails open by design and it looked exactly like
    success: no error, no log line, and the `[compact]` message only prints
    when the output actually shrank.

    Measured live against the real server after the fix: one SPY chain arrives
    as 79,052 characters (~20k tokens) and re-enters context on every
    subsequent agent turn. 28 chain calls are on the journal and not one was
    ever compacted - so D-065's measured 48% saving came entirely from the
    tool allowlist, and the lever it called the larger of the two has never
    once been pulled.

    Alpaca then wraps its own payload again as
    `{"_alpaca_mcp_security": {...}, "data": {...}}` (its prompt-injection
    boundary), which is the shape `mcp_client.unwrap` already knows how to
    read, so that stays the single place that knowledge lives.
    """
    from .mcp_client import unwrap

    if isinstance(result, tuple) and len(result) == 2:
        content, artifact = result
        payload = unwrap(content)
        if not isinstance(payload, dict):
            return None
        def rewrap(text: str, _a=artifact) -> Any:
            return ([{"type": "text", "text": text}], _a)
        return payload, rewrap
    if isinstance(result, dict):  # already unwrapped (tests, direct callers)
        return result, (lambda text: text)
    return None


def wrap_heavy_tools(tools: list[Any], config: Any = None) -> list[Any]:
    """Attach result compaction to the tools that need it. Interface unchanged."""
    for t in tools:
        fn = COMPACTORS.get(getattr(t, "name", ""))
        if fn is None:
            continue
        original = t.coroutine

        async def _compacted(*args: Any, __orig=original, __fn=fn, __name=t.name,
                              __config=config, **kw: Any) -> Any:
            result = await __orig(*args, **kw)
            try:
                unpacked = _unpack(result)
                if unpacked is None:
                    # Genuinely unrecognised envelope. Loud, because the silent
                    # version of this line cost us 28 uncompacted chains.
                    print(f"[compact] {__name}: unrecognised result envelope "
                          f"({type(result).__name__}), passing original through")
                    return result
                payload, rewrap = unpacked
                before = len(json.dumps(payload, default=str))
                out = __fn(payload, __config)
                if not isinstance(out, str):
                    print(f"[compact] {__name}: compactor declined this payload, "
                          f"passing original through")
                    return result
                print(f"[compact] {__name}: {before:,} -> {len(out):,} chars")
                return rewrap(out)
            except Exception as exc:  # noqa: BLE001 - fail open, loudly
                print(f"[compact] {__name} compaction failed, passing original through: {exc!r}")
                return result

        t.coroutine = _compacted
    return tools
