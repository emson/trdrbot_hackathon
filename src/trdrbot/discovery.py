"""Thesis-building by discovery: the news nominates the companies (D-035).

The daily research cycle (D-032) studies a FIXED universe. This is the other
half: scan broad market news + prediction-market odds, let the LLM nominate
interesting companies, then subject every nominee to the same deterministic
discipline as the fixed universe - real price history, technical stats,
bootstrap Monte Carlo - plus two things nominees specifically need:

  * a fundamentals snapshot (Yahoo Finance: market cap, P/E, sector, analyst
    target, earnings date) - the piece Alpaca has no API for. Prices still
    come from Alpaca: consistent with the bootstrap machinery, and yfinance's
    unofficial API is flakiest exactly there.
  * an options-liquidity gate - a news-hot name whose chain has no strikes
    inside the competition deadline is not an opportunity for THIS project,
    however good the story.

Two LLM calls: nominate (from evidence, with tickers it must justify), then
synthesise (forecast + falsifiable opportunities) AFTER the computed layer
has had its say. Between them, everything is deterministic and journalled.
Output lands through the existing seams: dossiers to the wiki, opportunities
to the inbox, where the decide cycle validates them against live quotes.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from . import ids, market_stats, mcp_client
from .config import Config
from .inbox import Inbox
from .journal import Journal
from .llm import build_model
from .research import _parse_json_block, _valid_opportunity
from .wiki import Concept, Wiki

NOMINATE_PROMPT = """You are scouting for an options trading agent (paper account, all positions \
must close by {deadline}). Below is broad market news and prediction-market odds.

Nominate 3-5 individual companies (liquid US-listed, optionable) that the material makes \
INTERESTING - a catalyst, a dislocation, a misprice, an overreaction. Not the biggest names, \
the most interesting ones. EXCLUDE: {exclude}.

Rules: every nomination must cite which headlines/odds justify it. No nominations from your \
general knowledge alone - if the material does not support a name, do not nominate it.

## News (headline | source | symbols)
{news_block}

## Prediction-market odds
{odds_block}

Respond with ONLY a JSON array:
[{{"ticker": str, "company": str, "why_interesting": str, "evidence": [str, ...],
   "direction_hint": "bullish"|"bearish"|"unclear"}}]
"""

SYNTH_PROMPT = """You are the research desk. For each candidate below you have: the nomination \
rationale, COMPUTED technical statistics from real price history, a fundamentals snapshot, a \
bootstrap Monte Carlo forecast (resampled from the stock's own returns, drift-free), and an \
options-chain check. Do not contradict computed numbers.

{candidates_block}

Task: forecast each candidate's potential over the next 5 trading days, then propose 0-3 \
OPPORTUNITIES total (across all candidates - only where evidence, technicals and the forecast \
line up; an empty array is a valid answer). All positions must close by {deadline}, so the \
horizon must be on or before it. Candidates that failed the options gate cannot be opportunities.

Respond with EXACTLY this structure:

FORECASTS_JSON:
{{"<ticker>": {{"outlook": str, "key_risk": str, "verdict": "opportunity"|"watch"|"pass"}}}}

OPPORTUNITIES_JSON:
[{{"underlying": str, "claim": str, "direction": "bullish"|"bearish"|"neutral",
   "drift_pct": float, "band_low": float|null, "band_high": float|null,
   "horizon": "YYYY-MM-DD", "why": str, "suggested_structures": [str, ...]}}]

band_low/band_high are PRICES IN DOLLARS (the underlying's price range within which the claim
HOLDS at the horizon), never percentage moves. At least one must be non-null.
"""


async def _fundamentals(ticker: str) -> dict[str, Any]:
    """Yahoo snapshot. Advisory: empty dict on any failure, never a crash."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        earnings = info.get("earningsTimestamp")
        return {
            "market_cap_bn": round(info["marketCap"] / 1e9, 1) if info.get("marketCap") else None,
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "analyst_target": info.get("targetMeanPrice"),
            "next_earnings": (
                datetime.fromtimestamp(earnings, tz=timezone.utc).date().isoformat()
                if earnings else None
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": type(exc).__name__}


async def _options_gate(tools: dict[str, Any], ticker: str, deadline: str) -> dict[str, Any]:
    """Does a chain exist with an expiry on/before the deadline? Sample its spread."""
    try:
        r = await mcp_client.call(
            tools, "get_option_chain", underlying_symbol=ticker,
            expiration_date_lte=deadline,
        )
        text = str(r)
        n = text.count("symbol") or text.count(ticker)
        return {"tradeable": n > 0, "contracts_seen": n}
    except Exception as exc:  # noqa: BLE001
        return {"tradeable": False, "error": type(exc).__name__}


async def run(
    tools: dict[str, Any], config: Config, inbox: Inbox, wiki: Wiki, journal: Journal,
    *, verbose: bool = True,
) -> dict[str, Any]:
    deadline = config.deadline
    exclude = sorted(set(config.research_universe) | set(config.watchlist))
    model = build_model(config)

    # ---- broad sweep: market-wide news (no symbol filter) + odds ----
    news_lines: list[str] = []
    try:
        r = await mcp_client.call(tools, "get_news", limit=40, exclude_contentless=True, sort="desc")
        for item in (r.get("news") or []) if isinstance(r, dict) else []:
            news_lines.append(f"- {item.get('headline')} | {item.get('source')} | {item.get('symbols')}")
    except Exception as exc:  # noqa: BLE001
        news_lines.append(f"(news unavailable: {type(exc).__name__})")

    odds_lines: list[str] = []
    try:
        from . import polymarket
        for q in config.polymarket_queries:
            for m in await polymarket.search(q, limit=2):
                odds_lines.append(f"- {m['probability']:.0%} {m['question']}")
    except Exception:  # noqa: BLE001
        pass

    # ---- LLM call 1: nominate from evidence ----
    reply = await model.ainvoke(NOMINATE_PROMPT.format(
        deadline=deadline, exclude=", ".join(exclude),
        news_block="\n".join(news_lines) or "(none)",
        odds_block="\n".join(odds_lines) or "(none)",
    ))
    text = reply.content if isinstance(reply.content, str) else "\n".join(
        b.get("text", "") for b in reply.content if isinstance(b, dict) and b.get("type") == "text")
    nominees = _parse_json_block(text) or []
    nominees = [n for n in nominees if isinstance(n, dict) and n.get("ticker")][:5]
    if verbose:
        print(f"[discovery] nominated: {[n['ticker'] for n in nominees]}")
    journal.append("discovery_nominees", tickers=[n["ticker"] for n in nominees])
    if not nominees:
        return {"nominees": 0, "opportunities": 0}

    # ---- deterministic layer per nominee ----
    blocks: list[str] = []
    last_close: dict[str, float] = {}
    for n in nominees:
        t = n["ticker"].upper()
        section = [f"### {t} - {n.get('company','')}",
                   f"Nominated because: {n.get('why_interesting','')}",
                   f"Evidence: {'; '.join(n.get('evidence', []))[:400]}"]

        closes = []
        try:
            closes = await market_stats.fetch_daily_closes(tools, t)
        except Exception as exc:  # noqa: BLE001
            section.append(f"Price history: UNAVAILABLE ({type(exc).__name__})")
        if len(closes) >= 60:
            last_close[t] = closes[-1]
            market_stats.save_closes(config.paths.state, t, closes)
            stats = market_stats.compute_stats(t, closes)
            section.append(f"Computed technicals: {stats.render()}")
            # Drift-free bootstrap from the stock's OWN returns: what a
            # 5-day move looks like when the story is ignored entirely.
            fac = market_stats.bootstrap_factors(closes, 5, seed=t)
            if fac:
                fac.sort()
                q = lambda p: fac[int(p * (len(fac) - 1))]
                up5 = sum(1 for f in fac if f >= 1.05) / len(fac)
                dn5 = sum(1 for f in fac if f <= 0.95) / len(fac)
                section.append(
                    "Bootstrap 5-day forecast (own history, no view): "
                    f"5%ile {q(0.05):+.1%}, median {q(0.5):+.1%}, 95%ile {q(0.95):+.1%} "
                    f"(as moves); P(+5% or more) {up5:.0%}, P(-5% or worse) {dn5:.0%}"
                    .replace("+1", "+").replace("1.0%", "0%")
                )
        elif closes:
            section.append(f"Price history: too short ({len(closes)} bars)")

        f = await _fundamentals(t)
        section.append("Fundamentals (Yahoo): " + json.dumps(f))
        gate = await _options_gate(tools, t, deadline)
        section.append(
            f"Options gate (expiries on/before {deadline}): "
            + ("PASS" if gate.get("tradeable") else f"FAIL {gate}")
        )
        n["_options_ok"] = bool(gate.get("tradeable"))
        blocks.append("\n".join(section))

    # ---- LLM call 2: synthesise after the numbers ----
    reply2 = await model.ainvoke(SYNTH_PROMPT.format(
        candidates_block="\n\n".join(blocks), deadline=deadline))
    text2 = reply2.content if isinstance(reply2.content, str) else "\n".join(
        b.get("text", "") for b in reply2.content if isinstance(b, dict) and b.get("type") == "text")

    import re
    m = re.search(r"FORECASTS_JSON:\s*\n(.*?)OPPORTUNITIES_JSON:", text2, re.DOTALL)
    forecasts = _parse_json_block(m.group(1)) if m else {}
    m2 = re.search(r"OPPORTUNITIES_JSON:\s*\n(.*)", text2, re.DOTALL)
    raw_opps = _parse_json_block(m2.group(1)) if m2 else []

    # ---- wiki dossiers for nominees worth keeping ----
    wrote = []
    for n in nominees:
        t = n["ticker"].upper()
        fc = (forecasts or {}).get(t, {})
        cid = f"research/{t}"
        c = wiki.read(cid) or Concept(concept_id=cid, frontmatter={"type": "CompanyDossier"}, body="")
        c.body = (
            f"# What it is\n{n.get('company','')} - {n.get('why_interesting','')}\n\n"
            f"# Bull case\n{fc.get('outlook','(no forecast)')}\n\n"
            f"# Bear case\n{fc.get('key_risk','(no forecast)')}\n\n"
            f"# People\n(not researched - discovery pass)\n\n"
            f"# Environment\nVerdict: {fc.get('verdict','?')}. Evidence: "
            f"{'; '.join(n.get('evidence', []))[:300]}\n"
        )
        c.add_source("discovery:news+polymarket+yahoo", author="trdrbot/discovery")
        try:
            wiki.write_concept(c, type_="CompanyDossier")
            wrote.append(cid)
        except Exception as exc:  # noqa: BLE001
            journal.append("error", cause="wiki_guard", error=repr(exc), concept=cid)

    # ---- opportunities through the seam, options gate enforced in code ----
    ok_tickers = {n["ticker"].upper() for n in nominees if n.get("_options_ok")}
    emitted = 0
    for o in raw_opps if isinstance(raw_opps, list) else []:
        if not _valid_opportunity(o):
            journal.append("research_rejected", reason="unscoreable_opportunity", raw=str(o)[:300])
            continue
        if o["underlying"].upper() not in ok_tickers:
            journal.append("research_rejected", reason="failed_options_gate", raw=str(o)[:300])
            continue
        if date.fromisoformat(str(o["horizon"])) > date.fromisoformat(config.deadline):
            journal.append("research_rejected", reason="horizon_past_deadline", raw=str(o)[:300])
            continue
        # Bands must be PRICES. Found live on the first run: the LLM emitted
        # percentage moves ([-6.0, 8.0] on a $87 stock), which would make
        # holds_at() always-False and attribution score every thesis as
        # failed - silently corrupting the learning loop. Anchor plausibility
        # to the computed close: a real band lives within [0.3x, 3x] of it.
        spot = last_close.get(o["underlying"].upper())
        if spot:
            bad = any(
                b is not None and not (0.3 * spot <= float(b) <= 3.0 * spot)
                for b in (o.get("band_low"), o.get("band_high"))
            )
            if bad:
                journal.append("research_rejected", reason="band_not_a_price",
                               raw=str(o)[:300], spot=spot)
                continue
        inbox.write("opportunity", o, source="discovery", trust="primary")
        emitted += 1

    journal.append("discovery", nominees=[n["ticker"] for n in nominees],
                   wiki_written=wrote, opportunities=emitted)
    if verbose:
        print(f"[discovery] dossiers: {wrote} | opportunities emitted: {emitted}")
    return {"nominees": len(nominees), "opportunities": emitted,
            "forecasts": forecasts, "wiki": wrote}
