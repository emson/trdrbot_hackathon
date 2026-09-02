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
from datetime import UTC, datetime
from typing import Any

from . import competence, evidence, ids, market_stats
from .config import Config
from .inbox import Inbox
from .journal import Journal
from .llm import (
    build_model,
    note_truncation,
    parse_json_array,
    parse_json_object,
    section,
    text_of,
)
from .opportunity import Opportunity, admit, options_gate
from .research import dossier
from .wiki import Concept, Wiki

NOMINATE_PROMPT = """You are scouting for an options trading agent (paper account; {horizon}). \
Below is broad market news and prediction-market odds.

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
[{{"ticker": str, "company": str, "what_it_is": str, "why_interesting": str,
   "evidence": [str, ...], "direction_hint": "bullish"|"bearish"|"unclear"}}]

`what_it_is` is a DURABLE one-liner: what the business does, in terms that stay true next \
month. No prices, no earnings dates, no "just beat" - those belong in why_interesting. It is \
the only part of the dossier later cycles read as a standing fact.
"""

SYNTH_PROMPT = """You are the research desk. For each candidate below you have: the nomination \
rationale, COMPUTED technical statistics from real price history, a fundamentals snapshot, a \
bootstrap Monte Carlo forecast (resampled from the stock's own returns, drift-free), and an \
options-chain check. Do not contradict computed numbers.

{candidates_block}

Task: forecast each candidate's potential over the next 5 trading days, then propose 0-3 \
OPPORTUNITIES total (across all candidates - only where evidence, technicals and the forecast \
line up; an empty array is a valid answer). {horizon} \
**Every horizon must fall between {earliest} and {latest} inclusive; outside that is rejected.** \
Aim the bulk at {preferred} or sooner. A thesis needs room AFTER it resolves to be worth forming, \
and one dated today resolves in zero days. Candidates that failed the options gate cannot be \
opportunities.

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


def _plausible_band(o: dict[str, Any], spot: float) -> bool:
    """Are this opportunity's bands actually PRICES, given the computed spot?

    Found live (D-035): the LLM emitted percentage moves ([-6.0, 8.0] on an
    $87 stock). `holds_at()` would then be always-False and attribution would
    score every thesis as failed - silent false negatives straight into the
    learning loop. Anchored to a number the system computed itself, because
    an LLM-supplied value cannot validate an LLM-supplied value.
    """
    if spot <= 0:
        return True  # no anchor to judge against; do not invent one
    for b in (o.get("band_low"), o.get("band_high")):
        if b is None:
            continue
        try:
            v = float(b)
        except (TypeError, ValueError):
            return False
        if not (0.3 * spot <= v <= 3.0 * spot):
            return False
    return True


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
                datetime.fromtimestamp(earnings, tz=UTC).date().isoformat()
                if earnings else None
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": type(exc).__name__}


async def run(
    tools: dict[str, Any], config: Config, inbox: Inbox, wiki: Wiki, journal: Journal,
    *, verbose: bool = True,
) -> dict[str, Any]:
    deadline = config.deadline
    _earliest, _preferred, _latest = competence.forecast_window(
        deadline, ids.utc_now().date())
    horizon = (f"all positions are force-closed on {deadline}"
               if deadline else
               "there is no hard stop, so a position is closed by its own exit rules")
    exclude = sorted(set(config.research_universe) | set(config.watchlist))
    model = build_model(config, role="discovery")

    # ---- broad sweep: market-wide news (no symbol filter) + odds ----
    news_block, odds_block = await evidence.gather(
        tools, config, symbols=None, news_limit=40, journal=journal)
    # ---- LLM call 1: nominate from evidence ----
    reply1 = await model.ainvoke(NOMINATE_PROMPT.format(
        horizon=horizon, exclude=", ".join(exclude),
        news_block=news_block,
        odds_block=odds_block,
    ))
    # A cut-off reply parses to FEWER nominees, not to an error (D-113), and
    # `nominees[:5]` below would then silently be a shortlist of three.
    note_truncation(reply1, "discovery.nominate", journal)
    nominees = parse_json_array(text_of(reply1))
    nominees = [n for n in nominees if isinstance(n, dict) and n.get("ticker")][:5]
    if verbose:
        print(f"[discovery] nominated: {[n['ticker'] for n in nominees]}")
    journal.append("discovery_nominees", tickers=[n["ticker"] for n in nominees])
    if not nominees:
        # The `discovery` row goes out even on the empty path. Without it a
        # run that produced nothing was INVISIBLE to its own health probe -
        # "ran, found nothing" and "stopped running" were the same
        # observation, which is the null-path rule (D-038) broken by the
        # subsystem sitting next to the detector that enforces it.
        journal.append("discovery", nominees=[], wiki_written=[], opportunities=0)
        return {"nominees": 0, "opportunities": 0}

    # ---- deterministic layer per nominee ----
    blocks: list[str] = []
    last_close: dict[str, float] = {}
    for n in nominees:
        t = n["ticker"].upper()
        # NOT `section` (D-102): that is `llm.section`, called below to split
        # the second reply. Binding it to a list here made it function-local
        # for the WHOLE body, so every hunt that produced nominees died on
        # `TypeError: 'list' object is not callable` - six consecutive runs
        # over two days, each burning two LLM calls, a bar fetch, a yfinance
        # call and an option chain per nominee before crashing.
        lines = [f"### {t} - {n.get('company','')}",
                 f"Nominated because: {n.get('why_interesting','')}",
                 f"Evidence: {'; '.join(n.get('evidence', []))[:400]}"]

        closes: list[float] = []
        dates: list[str] = []
        try:
            dates, closes = await market_stats.fetch_daily_series(tools, t)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Price history: UNAVAILABLE ({type(exc).__name__})")
        if len(closes) >= 60:
            last_close[t] = closes[-1]
            market_stats.save_closes(config.paths.state, t, closes, dates=dates)
            stats = market_stats.compute_stats(t, closes)
            lines.append(f"Computed technicals: {stats.render()}")
            # Drift-free bootstrap from the stock's OWN returns: what a
            # 5-day move looks like when the story is ignored entirely.
            fac = market_stats.bootstrap_factors(closes, 5, seed=t)
            if fac:
                fac.sort()
                def q(pct: float, _f: list[float] = fac) -> float:
                    return _f[int(pct * (len(_f) - 1))]

                up5 = sum(1 for f in fac if f >= 1.05) / len(fac)
                dn5 = sum(1 for f in fac if f <= 0.95) / len(fac)
                lines.append(
                    "Bootstrap 5-day forecast (own history, no view): "
                    f"5%ile {q(0.05):+.1%}, median {q(0.5):+.1%}, 95%ile {q(0.95):+.1%} "
                    f"(as moves); P(+5% or more) {up5:.0%}, P(-5% or worse) {dn5:.0%}"
                    .replace("+1", "+").replace("1.0%", "0%")
                )
        elif closes:
            lines.append(f"Price history: too short ({len(closes)} bars)")

        f = await _fundamentals(t)
        lines.append("Fundamentals (Yahoo): " + json.dumps(f))
        gate = await options_gate(tools, t, _latest)
        lines.append(
            f"Options gate (expiries on/before {_latest}): "
            + ("PASS" if gate.get("tradeable") else f"FAIL {gate}")
        )
        n["_options_ok"] = bool(gate.get("tradeable"))
        blocks.append("\n".join(lines))

    # ---- LLM call 2: synthesise after the numbers ----
    # Derived, not recalled, and shared with muse and record_forecast so the
    # three thesis sources cannot drift apart on what "in time" means.
    reply2 = await model.ainvoke(SYNTH_PROMPT.format(
        candidates_block="\n\n".join(blocks), horizon=horizon,
        earliest=_earliest, preferred=_preferred, latest=_latest))
    note_truncation(reply2, "discovery.synthesise", journal)
    text2 = text_of(reply2)

    # `section` rather than two inline regexes: one parser for one LABEL:
    # convention, so a change to the convention is one edit. The old inline
    # form also hard-required the literal "OPPORTUNITIES_JSON:" terminator -
    # a reply that omitted it lost the forecasts silently.
    forecasts = parse_json_object(section(text2, "FORECASTS_JSON", ["OPPORTUNITIES_JSON"]))
    raw_opps = parse_json_array(section(text2, "OPPORTUNITIES_JSON", ["\\Z"]))

    # ---- wiki dossiers for nominees worth keeping ----
    wrote = []
    for n in nominees:
        t = n["ticker"].upper()
        fc = (forecasts or {}).get(t, {})
        cid = f"research/{t}"
        c = wiki.read(cid) or Concept(concept_id=cid, frontmatter={"type": "CompanyDossier"}, body="")
        # Same builder as research: two writers share this file and the
        # augmentation guard refuses a write that drops a heading, so a
        # heading set that drifted between them would wedge dossier updates
        # permanently. One template, filled differently.
        c.body = dossier(
            t,
            what_it_is=n.get("what_it_is") or n.get("company", ""),
            bull_case=f"{n.get('why_interesting','')} {fc.get('outlook','(no forecast)')}",
            bear_case=fc.get("key_risk", "(no forecast)"),
            people="(not researched - discovery pass)",
            environment=(f"Verdict: {fc.get('verdict','?')}. Evidence: "
                         f"{'; '.join(n.get('evidence', []))[:300]}"),
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
    for raw in raw_opps:
        o = Opportunity.from_payload(raw)
        if o is None:
            journal.append("research_rejected", source="discovery",
                           reason="unscoreable:not_an_object", raw=str(raw)[:300])
            continue
        # One gate, four checks, and the band check no longer VANISHES when the
        # close fetch failed - it reports itself unchecked instead, which is
        # exactly when the data is worst and the silence cost most.
        verdict = admit(
            o,
            spot=last_close.get(o.underlying),
            latest_useful=_latest or None, earliest_useful=_earliest,
            options_tradeable=o.underlying in ok_tickers,
        )
        if not verdict.ok:
            journal.append("research_rejected", source="discovery",
                           reason=verdict.defect, raw=str(raw)[:300],
                           spot=last_close.get(o.underlying))
            continue
        inbox.write_opportunity(o, source="discovery")
        emitted += 1
        if verdict.unchecked:
            journal.append("research_admitted_unchecked", source="discovery",
                           underlying=o.underlying, unchecked=list(verdict.unchecked))

    journal.append("discovery", nominees=[n["ticker"] for n in nominees],
                   wiki_written=wrote, opportunities=emitted)
    if verbose:
        print(f"[discovery] dossiers: {wrote} | opportunities emitted: {emitted}")
    return {"nominees": len(nominees), "opportunities": emitted,
            "forecasts": forecasts, "wiki": wrote}
