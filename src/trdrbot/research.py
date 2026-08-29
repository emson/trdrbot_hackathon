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

from typing import Any

from . import competence, evidence, ids, market_stats
from .config import Config
from .inbox import Inbox
from .journal import Journal
from .llm import ask, parse_json_array, parse_json_object, section
from .opportunity import Opportunity, admit
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


#: The five headings a CompanyDossier carries, DURABLE first. Two writers
#: share this file - research and discovery - and the augmentation guard
#: refuses any write that drops a heading, so a heading set that drifted
#: between them would wedge dossier updates permanently. It existed twice and
#: was policed by a test that regexed the literals out of both functions;
#: now it exists once and the test can go.
def dossier(ticker: str, *, what_it_is: str, bull_case: str, bear_case: str,
            people: str, environment: str) -> str:
    """A dossier body. Durable above, perishable below.

    "What it is" is true next month; the bull and bear cases are a snapshot of
    a tape that has already moved. These used to be welded into one sentence -
    "Affirm Holdings, Inc. - Strong Q4 results with...beats" - so 22 of 28
    dossiers had today's earnings news sitting in the one heading later cycles
    read as a standing fact (D-078).
    """
    return (
        f"# What it is\n{what_it_is}\n\n"
        f"# Bull case\n{bull_case}\n\n"
        f"# Bear case\n{bear_case}\n\n"
        f"# People\n{people}\n\n"
        f"# Environment\n{environment}\n"
    )


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


def _due_today(config: Config) -> tuple[bool, str]:
    """(should run, why not). Research's own cadence, held where it belongs.

    Once per calendar day, and never on Saturday: a Saturday run reads
    Friday's close and is stale twice over by Monday's open, while Sunday's
    regime read feeds Monday. The weekday is the MARKET's - keyed on UTC it
    suppressed research every Friday evening from 20:00 ET, which is the run
    that reads a fresh close and is the most useful of the week.

    This lived in `housekeeping` alone, so `trdrbot research` bypassed both
    the marker and the weekday gate (D-092).
    """
    if ids.market_today().weekday() == 5:
        return False, "saturday"
    marker = config.paths.state / "last_research"
    today = ids.today().isoformat()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
        return False, "already_ran_today"
    return True, ""


def _mark_ran(config: Config) -> None:
    (config.paths.state / "last_research").write_text(
        ids.today().isoformat(), encoding="utf-8")


async def run(
    tools: dict[str, Any],
    config: Config,
    inbox: Inbox,
    wiki: Wiki,
    journal: Journal,
    *,
    verbose: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    due, why = _due_today(config)
    if not due and not force:
        if verbose:
            print(f"[research] skipped: {why} (pass force=True to override)")
        return {"skipped": why, "wiki": [], "opportunities": 0}

    universe = config.research_universe

    # ---- deterministic layer: stats + persisted closes per ticker ----
    stats_lines = []
    #: Spot per symbol, so the band-plausibility gate has the anchor it needs.
    #: An LLM-supplied value cannot validate an LLM-supplied value, so this
    #: must be a number the system computed itself (D-035).
    last_close: dict[str, float] = {}
    for sym in universe:
        try:
            dates, closes = await market_stats.fetch_daily_series(tools, sym)
            if len(closes) >= 60:
                # Dates go in too: without them beta pairs two series by array
                # POSITION, which is only correct when both were fetched the
                # same day (D-091).
                market_stats.save_closes(config.paths.state, sym, closes, dates=dates)
                last_close[sym.upper()] = closes[-1]
                stats_lines.append("- " + market_stats.compute_stats(sym, closes).render())
            else:
                stats_lines.append(f"- {sym}: insufficient history ({len(closes)} bars)")
        except Exception as exc:  # noqa: BLE001 - one symbol must not sink the cycle
            stats_lines.append(f"- {sym}: stats unavailable ({type(exc).__name__})")
    stats_block = "## Computed statistics (from real daily closes)\n" + "\n".join(stats_lines)

    # ---- gather news + odds ----
    news_block, odds_block = await evidence.gather(
        tools, config, symbols=universe, news_limit=25, journal=journal)
    prior = wiki.read("context/regime")
    prior_text = prior.body[:1500] if prior else "(none yet)"

    # ---- LLM synthesis: one call for the whole cycle ----
    prompt = RESEARCH_PROMPT.format(
        stats_block=stats_block,
        news_block=news_block,
        odds_block=odds_block,
        prior_regime=prior_text,
    )
    text = await ask(config, "research", prompt)

    regime_md = section(text, "REGIME_MARKDOWN", ["DOSSIERS_JSON", "OPPORTUNITIES_JSON"])
    dossiers = parse_json_object(section(text, "DOSSIERS_JSON", ["OPPORTUNITIES_JSON"]))
    raw_opps = parse_json_array(section(text, "OPPORTUNITIES_JSON", ["\\Z"]))

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
        c.body = dossier(
            sym, what_it_is=d.get("what_it_is", ""), bull_case=d.get("bull_case", ""),
            bear_case=d.get("bear_case", ""), people=d.get("people", ""),
            environment=d.get("environment", ""),
        )
        c.add_source("computed:market_stats", author="trdrbot/research")
        try:
            wiki.write_concept(c, type_="CompanyDossier")
            wrote.append(cid)
        except Exception as exc:  # noqa: BLE001
            journal.append("error", cause="wiki_guard", error=repr(exc), concept=cid)

    # ---- emit opportunities through the existing seam ----
    emitted = 0
    # Research had NONE of the gates discovery and the muse earned through
    # shipped bugs - no horizon window, no band-plausibility check, no options
    # gate - so the D-035 defect (percentage moves emitted as dollar bands,
    # making holds_at always-False and scoring every thesis as failed) was
    # still open on the path whose output the agent reads every morning.
    latest = (competence.forecast_window(config.deadline, ids.today()) or ("", "", ""))[2]
    for raw in raw_opps:
        o = Opportunity.from_payload(raw)
        if o is None:
            journal.append("research_rejected", source="research",
                           reason="unscoreable:not_an_object", raw=str(raw)[:300])
            continue
        verdict = admit(o, spot=last_close.get(o.underlying),
                        latest_useful=latest or None)
        if not verdict.ok:
            journal.append("research_rejected", source="research",
                           reason=f"unscoreable:{verdict.defect}", raw=str(raw)[:300])
            continue
        inbox.write_opportunity(o, source="research")
        emitted += 1
        if verdict.unchecked:
            # Admitted on partial evidence, and the row says which gates could
            # not run rather than letting an absent check read as a passed one.
            journal.append("research_admitted_unchecked", source="research",
                           underlying=o.underlying, unchecked=list(verdict.unchecked))

    _mark_ran(config)
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
