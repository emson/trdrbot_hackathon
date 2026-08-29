"""The research cycle - where theses come from (D-032).

Top-down, once a day, on the slow/expensive path:

    regime  <- computed stats + news + prediction-market odds
    dossier <- per company: what it is, why/why not to invest, people,
               environment, and its measured historical behaviour
    opportunities <- 0-3 ranked candidate theses, each falsifiable

Everything durable lands in the wiki as OKF concepts with stable headings
(the augmentation guard permits updating content under existing headings,
refuses dropping them - so the schema is enforced by the guard itself).
Opportunities enter the system through the EXISTING seam: they are inbox
items, consumed by the decide cycle like any other observation. Research
proposes; the decide cycle disposes - it still runs simulate/size/record
against live chain prices before anything is executed.

Division of labour: numbers are computed (market_stats), never asked of the
LLM; the LLM does what only it can - synthesis, narrative, and judgment about
what is worth attention. Dates/events must come from the supplied news and
odds, not model memory, which is stale by construction.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import market_stats, mcp_client, news_extract
from .config import Config
from .inbox import Inbox
from .journal import Journal
from .llm import build_model
from .wiki import Concept, Wiki

RESEARCH_PROMPT = """You are the research desk for an options trading agent. Produce a daily \
market assessment and candidate opportunities.

Numbers below are COMPUTED from real price history - do not recompute or contradict them. \
Event dates must come from the news/odds provided; if the material does not establish a date, \
write "unknown" rather than recalling one from memory.

{stats_block}

## Recent news (headline | source | symbols)
{news_block}

## Prediction-market odds (crowd probabilities, secondary trust)
{odds_block}

## Existing regime assessment (update it, don't rewrite from scratch)
{prior_regime}

Respond with EXACTLY this structure:

REGIME_MARKDOWN:
(markdown for the regime page. Keep these exact headings: "# Assessment",
"# Drivers", "# Calendar", "# Watch". Under Calendar list only events the
material above establishes, with dates or "unknown".)

DOSSIERS_JSON:
(a JSON object mapping ticker -> {{"what_it_is": str, "bull_case": str,
"bear_case": str, "people": str, "environment": str}} - one entry per ticker
in the stats block. 2-3 sentences per field. people/environment may draw on
your general knowledge but must be marked with trailing "(model knowledge)"
where not supported by the material above.)

OPPORTUNITIES_JSON:
(a JSON array, 0 to 3 entries, ONLY where the material supports a genuine
view. Each: {{"underlying": str, "claim": str, "direction": "bullish"|"bearish"|"neutral",
"drift_pct": float, "band_low": float|null, "band_high": float|null,
"horizon": "YYYY-MM-DD", "why": str, "suggested_structures": [str, ...]}}.
band_low/band_high are the prices between which the claim HOLDS - at least
one must be non-null or the thesis cannot be scored. horizon must be within
the next 10 days. An empty array is a valid, often correct answer.)
"""


def _section(text: str, name: str, next_names: list[str]) -> str:
    pattern = rf"{name}:\s*\n(.*?)(?=(?:{'|'.join(next_names)}):|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _salvage_truncated_array(raw: str, start: int) -> list[Any]:
    """Complete elements from a JSON array that was cut off mid-flight.

    The outer-bracket salvage below cannot help here: a truncated array has no
    closing `]`, so `rfind` lands on an INNER one (a `suggested_structures`
    list, say) and the fragment fails to parse - discarding four good
    candidates because a fifth was half-written.

    That is not hypothetical. The muse asks for five candidates each carrying a
    causal chain and structure list, and gpt-5's reasoning tokens count against
    the same completion budget as its output, so a run can spend most of an
    8,000-token ceiling before it starts writing. Observed live: a 6,745-char
    reply that opened with a perfectly good `[{"underlying":"S"...` and parsed
    to nothing, one LLM call spent for zero candidates.

    Uses the stdlib decoder's own incremental mode rather than counting
    brackets, so a brace inside a string cannot fool it.
    """
    decoder = json.JSONDecoder()
    out: list[Any] = []
    i = start + 1
    while i < len(raw):
        while i < len(raw) and raw[i] in ", \t\r\n":
            i += 1
        if i >= len(raw) or raw[i] == "]":
            break
        try:
            obj, i = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            break  # the incomplete tail - everything before it is still good
        out.append(obj)
    return out


def _parse_json_block(raw: str) -> Any:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # An unterminated ARRAY is salvaged before the outer-bracket attempt
        # when the reply opens with one. Order matters: with exactly one
        # complete element written, `rfind("}")` lands on that element's own
        # closer, so the object salvage succeeds and returns a DICT where the
        # caller is unpacking a list - a truncated array quietly becoming a
        # single candidate is worse than returning nothing.
        if raw.startswith("["):
            partial = _salvage_truncated_array(raw, 0)
            if partial:
                print(f"[parse] reply was truncated; salvaged {len(partial)} complete "
                      f"element(s) from an unterminated array")
                return partial
        # Salvage the outermost JSON value if the model wrapped it in prose.
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = raw.find(opener), raw.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    continue
        # ...or an array that was wrapped in prose AND truncated.
        start = raw.find("[")
        if start != -1:
            partial = _salvage_truncated_array(raw, start)
            if partial:
                print(f"[parse] reply was truncated; salvaged {len(partial)} complete "
                      f"element(s) from an unterminated array")
                return partial
    return None


def opportunity_defect(o: Any) -> str | None:
    """Why this opportunity cannot be scored, or None if it can.

    Returns the SPECIFIC missing field rather than a bare bool (D-071).
    "unscoreable_opportunity" was journalled for every rejection, so a
    fully-reasoned CRM thesis - correct bands, correct drift, the date stated
    in its own claim text - was indistinguishable in the log from genuine
    garbage. It was dropped for one absent `horizon` field, and the rejection
    could not say so. A repeating defect is a fixable prompt problem; an
    opaque one is just attrition.
    """
    if not isinstance(o, dict):
        return "not_an_object"
    for field in ("underlying", "claim", "horizon"):
        if not o.get(field):
            return f"missing_{field}"
    if o.get("band_low") is None and o.get("band_high") is None:
        return "missing_band"
    try:
        float(o.get("drift_pct", 0))
    except (TypeError, ValueError):
        return "bad_drift_pct"
    try:
        from datetime import date
        date.fromisoformat(str(o["horizon"]))
    except (TypeError, ValueError):
        return "bad_horizon_format"
    return None


def _valid_opportunity(o: Any) -> bool:
    """An unscoreable opportunity is worse than none - it would occupy a slot
    in the decide context while being immune to ever being judged wrong."""
    return opportunity_defect(o) is None


async def run(
    tools: dict[str, Any],
    config: Config,
    inbox: Inbox,
    wiki: Wiki,
    journal: Journal,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    universe = config.research_universe

    # ---- deterministic layer: stats + persisted closes per ticker ----
    stats_lines = []
    for sym in universe:
        try:
            closes = await market_stats.fetch_daily_closes(tools, sym)
            if len(closes) >= 60:
                market_stats.save_closes(config.paths.state, sym, closes)
                stats_lines.append("- " + market_stats.compute_stats(sym, closes).render())
            else:
                stats_lines.append(f"- {sym}: insufficient history ({len(closes)} bars)")
        except Exception as exc:  # noqa: BLE001 - one symbol must not sink the cycle
            stats_lines.append(f"- {sym}: stats unavailable ({type(exc).__name__})")
    stats_block = "## Computed statistics (from real daily closes)\n" + "\n".join(stats_lines)

    # ---- gather news + odds ----
    news_lines = []
    try:
        r = await mcp_client.call(
            tools, "get_news", symbols=",".join(universe), limit=25,
            exclude_contentless=True, sort="desc",
        )
        items = (r.get("news") or []) if isinstance(r, dict) else []
        news_lines.append(news_extract.render_block(await news_extract.enrich(items, config)))
    except Exception as exc:  # noqa: BLE001
        news_lines.append(f"(news unavailable: {type(exc).__name__})")

    odds_lines = []
    try:
        from . import polymarket
        for q in config.polymarket_queries:
            for m in await polymarket.search(q, limit=2):
                odds_lines.append(f"- {m['probability']:.0%} {m['question']}")
    except Exception as exc:  # noqa: BLE001
        odds_lines.append(f"(odds unavailable: {type(exc).__name__})")

    prior = wiki.read("context/regime")
    prior_text = prior.body[:1500] if prior else "(none yet)"

    # ---- LLM synthesis: one call for the whole cycle ----
    prompt = RESEARCH_PROMPT.format(
        stats_block=stats_block,
        news_block="\n".join(news_lines) or "(none)",
        odds_block="\n".join(odds_lines) or "(none)",
        prior_regime=prior_text,
    )
    reply = await build_model(config, role="research").ainvoke(prompt)
    text = reply.content if isinstance(reply.content, str) else "\n".join(
        b.get("text", "") for b in reply.content if isinstance(b, dict) and b.get("type") == "text"
    )

    regime_md = _section(text, "REGIME_MARKDOWN", ["DOSSIERS_JSON", "OPPORTUNITIES_JSON"])
    dossiers = _parse_json_block(_section(text, "DOSSIERS_JSON", ["OPPORTUNITIES_JSON"])) or {}
    raw_opps = _parse_json_block(_section(text, "OPPORTUNITIES_JSON", ["\\Z"])) or []

    # ---- write wiki (OKF, augmentation-guarded) ----
    wrote = []
    if regime_md and "# Assessment" in regime_md:
        c = wiki.read("context/regime") or Concept(
            concept_id="context/regime", frontmatter={"type": "MarketContext"}, body=""
        )
        c.body = regime_md + "\n"
        # `status` and `stale_after` are stamped by wiki.LIFECYCLE now. They
        # were set here by hand, which is exactly how one file ends up with two
        # writers disagreeing about when it expires.
        c.add_source("computed:market_stats", author="trdrbot/research")
        try:
            wiki.write_concept(c, type_="MarketContext")
            wrote.append("context/regime")
        except Exception as exc:  # noqa: BLE001 - guard refusal is a data point, not a crash
            journal.append("error", cause="wiki_guard", error=repr(exc), concept="context/regime")

    for sym, d in (dossiers.items() if isinstance(dossiers, dict) else []):
        if not isinstance(d, dict):
            continue
        cid = f"research/{sym.upper()}"
        c = wiki.read(cid) or Concept(concept_id=cid, frontmatter={"type": "CompanyDossier"}, body="")
        c.body = (
            f"# What it is\n{d.get('what_it_is','')}\n\n"
            f"# Bull case\n{d.get('bull_case','')}\n\n"
            f"# Bear case\n{d.get('bear_case','')}\n\n"
            f"# People\n{d.get('people','')}\n\n"
            f"# Environment\n{d.get('environment','')}\n"
        )
        c.add_source("computed:market_stats", author="trdrbot/research")
        try:
            wiki.write_concept(c, type_="CompanyDossier")
            wrote.append(cid)
        except Exception as exc:  # noqa: BLE001
            journal.append("error", cause="wiki_guard", error=repr(exc), concept=cid)

    # ---- emit opportunities through the existing seam ----
    emitted = 0
    for o in raw_opps if isinstance(raw_opps, list) else []:
        defect = opportunity_defect(o)
        if defect:
            journal.append("research_rejected", reason=f"unscoreable:{defect}", raw=str(o)[:300])
            continue
        inbox.write("opportunity", o, source="research", trust="primary")
        emitted += 1

    journal.append(
        "research",
        universe=universe,
        wiki_written=wrote,
        opportunities=emitted,
        rejected=len(raw_opps) - emitted if isinstance(raw_opps, list) else 0,
    )
    if verbose:
        print(f"[research] wiki: {wrote} | opportunities emitted: {emitted}")
    return {"wiki": wrote, "opportunities": emitted}
