"""News extraction: dense structured signal in place of headline-only (D-066,
field set + citation extended D-067).

D-065 compacted news to headlines because bodies were assumed to be filler -
an assumption, not a measurement. D-066 fixed that with a cheap dedicated
extraction pass. D-067 grounds the field list in actual practice (scout
research, 2026-08-28: SEntFiN/JASIST 2022, "Beyond Sentiment" arXiv 2607.28496,
"Trade the Event" ACL 2021, "Numerical Claim Detection" EMNLP FEVER 2024,
Dolphin et al. arXiv 2607.08346) rather than intuition, and adds the citation
trail the user asked for directly.

What the research supports and this module adopts:
  - event type as the primary structured field, defined by ECONOMIC CONTENT
    (what happened) not a label or filing code - `activity` already did this;
    the vocabulary gained dividend/buyback/split, the three other predictable-
    impact categories named across sources.
  - numeric claims typed forecast-vs-established-fact (EMNLP FEVER 2024) - a
    guidance figure and a reported print carry opposite information content
    and must never collapse into one field. -> `key_number` + `claim_type`.
  - claim time horizon (arXiv 2607.28496) - no verified source maps this onto
    OPTIONS specifically (tenor, event-vs-expiry alignment), which is exactly
    what this agent needs it for, so it earns its place despite thinner
    academic backing. -> `time_horizon`.
  - every extracted claim should be traceable to source text (converges
    across SEntFiN, Dolphin et al.'s per-tag quote requirement, and FinVet's
    verdict/evidence/source/confidence schema). -> `quote` + `url`.

What the research supports but this module deliberately does NOT build:
  - full per-entity sentiment decomposition: the standalone justification (a
    claimed ~26% of headlines carry CONFLICTING per-entity sentiment) was
    refuted on verification - only multi-entity presence was confirmed, not
    conflict. Our articles already arrive symbol-scoped via Alpaca's
    `symbols` field, so one sentiment per article is the right size here.
  - a second-pass, quote-grounded confidence GRADER: Dolphin et al. measured
    this raising precision from 12% to 96% over inline self-rating, which is
    the single most actionable finding in the research - but it is a second
    LLM call per batch, doubling this role's cost, and rests on one recent
    single-source preprint. `confidence` below is the cheap inline version,
    documented honestly as the weaker signal it is. Revisit if news-driven
    theses start showing a real false-positive problem.
  - automated quote verification (n-gram overlap or similar): the specific
    mechanism researched was refuted on verification. `quote` is stored as
    the model's claim, not a verified grounding - same "unverified, labelled
    as such" discipline as `confidence`.
  - novelty/staleness detection beyond article-id dedup: literature confirms
    it matters a lot (event-driven return math flips from +1.74% to -0.07%
    within the same minute once a signal is stale) but the mechanism
    (embedding similarity, story-chain linking) was never verified as
    something to copy. Article-id caching already gives exact-duplicate
    dedup for free; near-duplicate/re-hash detection is a real open problem,
    not a corner we cut - see specs/issues.md.

The fix is not "send bodies back" (that reintroduces the ~2k-char/article cost
D-065 removed) - it is a cheap dedicated extraction pass that reads the body
ONCE per article and distills it to structured fields plus one dense sentence
and a citation. That distillation is then:

  1. injected into every prompt that used to get a headline (research,
     discovery, muse, and decide's compacted get_news), and
  2. PERSISTED, keyed by article id, in `state/news_extracts.json` - the
     standardised structured store: same schema every time, one record per
     article, deduplicated for free because the same article recurs across
     research/discovery/muse/sensors within a day and each currently pulls
     overlapping windows.

**Fail open, per record.** A batch extraction call covers every uncached
article in one shot (cheap model, one call per cycle - never one call per
article). If the call fails outright, or the model mismatches/omits an id,
that article falls back to a BARE extract (dense=headline, url preserved,
everything else unset) rather than losing it - same discipline as compact.py.
Bare extracts are never written to the cache, so a transient failure gets
retried next cycle instead of being permanently frozen as "unknown".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import ids, store
from .config import Config
from .llm import build_model, parse_json_array, text_of

# Deferred import (not at module top level): research.py imports THIS module
# to render its news block, so an eager import here would be circular. By
# call time both modules are already fully loaded, so this is safe.

#: Controlled-ish vocabulary offered to the model so `activity` stays
#: consistent enough to scan across articles; not enforced, just prompted.
#: dividend/buyback/split added per research (D-067): named across multiple
#: sources as predictable-price-impact corporate-event categories.
ACTIVITIES = ["earnings", "guidance", "M&A", "regulatory", "macro_data",
              "rating_change", "product", "leadership", "dividend", "buyback",
              "split", "other"]
REGIMES = ["macro", "sector", "company"]
#: When does the claim's effect play out - the field with no verified source
#: mapping it onto options specifically (D-067), but the one this agent most
#: needs for tenor selection: an "immediate" claim wants this week's expiry,
#: a "long_term" one may not resolve before any reasonable expiry at all.
TIME_HORIZONS = ["immediate", "near_term", "long_term"]
CLAIM_TYPES = ["forecast", "established"]

#: One batched call per cycle, not one per article - the whole cost point.
MAX_BATCH = 40

EXTRACT_PROMPT = """Extract structured signal from these news articles for a trading agent's context. \
For EACH article return one JSON object. Be terse and factual - no speculation beyond what the text states.

Fields per article:
  id             - copy verbatim from the input
  sentiment      - float -1.0 (very negative for the named tickers) to 1.0 (very positive), 0.0 if neutral/mixed
  organizations  - up to 5 company/institution names actually named in the text (not just the ticker's own name unless it acted)
  people         - up to 3 named people who are the subject of an action (executives, officials) - [] if none
  activity       - the single best fit from: {activities}
  regime         - the single best fit from: {regimes} (macro = rates/inflation/employment/geopolitics; \
sector = affects a whole industry; company = specific to the named tickers)
  time_horizon   - the single best fit from: {horizons} (immediate = today/this week; near_term = weeks to \
one quarter, e.g. "reports earnings Oct 14"; long_term = a quarter or more out, or no resolution date stated)
  key_number     - the SINGLE most decision-relevant number stated, with its unit and context, e.g. \
"$2.50 EPS guidance, up from $2.30" - "" if no material number is stated
  claim_type     - if key_number is set: {claim_types} (forecast = guidance/target/estimate not yet realised; \
established = an already-reported/confirmed figure) - "" if key_number is ""
  confidence     - your own confidence 0.0-1.0 that this extraction is correct and unambiguous - NOTE: this is a \
same-pass self-rating, known to run overconfident; a low value here is more meaningful than a high one
  quote          - the single sentence or clause from the article text that most directly supports `dense` - copy \
it as close to verbatim as you can from the summary given, do not fabricate one if the summary does not contain it
  dense          - ONE sentence, <=200 chars, the single most decision-relevant fact - not a rephrased headline, \
the CONTENT (e.g. "Guidance raised on services growth, cites AI-driven demand" not "Apple reports earnings")

Return ONLY a JSON array, one object per article, same order as input. No prose, no markdown fence.

Articles:
{articles}
"""


@dataclass
class Extract:
    id: str
    headline: str
    source: str = ""
    #: The citation. Always populated (bare or enriched) straight from
    #: Alpaca's own `url` field - not model-derived, so it survives even a
    #: total extraction outage (D-067, the user's own ask: preserve the
    #: original reference).
    url: str = ""
    symbols: list[str] = field(default_factory=list)
    created_at: str = ""
    #: None means extraction never succeeded for this article - `dense` is
    #: just the headline and every other field is unset. Distinguishes a real
    #: neutral (0.0) from "we never actually looked at this one".
    sentiment: float | None = None
    organizations: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    activity: str = ""
    regime: str = ""
    time_horizon: str = ""
    key_number: str = ""
    claim_type: str = ""
    #: Same-pass self-rating - NOT a calibrated probability. Research finding
    #: (D-067): inline confidence collapses to a near-binary flag; a genuine
    #: dial needs a second quote-grounded grading pass, deliberately not
    #: built here (see module docstring). Treat a LOW value as informative
    #: and a HIGH one as "the model didn't flag a problem", nothing stronger.
    confidence: float | None = None
    #: The model's claimed supporting quote - UNVERIFIED against the source
    #: text (no automated grounding check is run; that specific mechanism
    #: had no support on verification). A citation trail, not a proof.
    quote: str = ""
    dense: str = ""
    model: str = ""
    extracted_at: str = ""

    def is_bare(self) -> bool:
        return self.sentiment is None


def bare(item: dict[str, Any]) -> Extract:
    return Extract(
        id=str(item.get("id")), headline=str(item.get("headline") or ""),
        source=str(item.get("source") or ""), url=str(item.get("url") or ""),
        symbols=list(item.get("symbols") or []),
        created_at=str(item.get("created_at") or ""), dense=str(item.get("headline") or ""),
    )


class ExtractCache:
    """Standardised structured store, one record per article id.

    Same shape as `sensors.SensorState` - a flat JSON dict, load on
    construction, rewrite whole-file on save. Deliberately not a database:
    volume is a few dozen articles a day, and a plain file is inspectable
    with `cat` mid-competition. Forward-compatible by construction: `Extract`
    fields all carry defaults, so a cache written before D-067 added new
    fields still loads cleanly - the new fields just read empty for old rows.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                self._items = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                self._items = {}

    def get(self, article_id: str) -> Extract | None:
        raw = self._items.get(article_id)
        return Extract(**raw) if raw else None

    def put_many(self, extracts: list[Extract]) -> None:
        for e in extracts:
            if not e.is_bare():  # never freeze a failure as permanent
                self._items[e.id] = asdict(e)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        store.write_atomic(self.path, json.dumps(self._items, indent=2, sort_keys=True))


def _coerce(raw: Any, item: dict[str, Any], model_name: str) -> Extract:
    """One salvaged record from the model's JSON -> a validated Extract.

    Every field is defensively typed - a model returning a string where a
    list was asked for must not crash the batch, just fall back to empty.
    `url` is never sourced from `raw` (the model doesn't see it and
    shouldn't invent one) - always the real Alpaca field via `item`.
    """
    if not isinstance(raw, dict):
        return bare(item)
    sentiment = raw.get("sentiment")
    if not isinstance(sentiment, (int, float)):
        return bare(item)
    orgs = [str(x) for x in raw.get("organizations", []) if isinstance(x, str)][:5]
    people = [str(x) for x in raw.get("people", []) if isinstance(x, str)][:3]
    dense = str(raw.get("dense") or item.get("headline") or "")[:240]

    time_horizon = str(raw.get("time_horizon") or "")
    if time_horizon not in TIME_HORIZONS:
        time_horizon = ""
    claim_type = str(raw.get("claim_type") or "")
    if claim_type not in CLAIM_TYPES:
        claim_type = ""
    key_number = str(raw.get("key_number") or "")[:120]
    if not key_number:
        claim_type = ""  # a claim_type with no number attached is meaningless

    confidence = raw.get("confidence")
    confidence = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else None

    return Extract(
        id=str(item.get("id")), headline=str(item.get("headline") or ""),
        source=str(item.get("source") or ""), url=str(item.get("url") or ""),
        symbols=list(item.get("symbols") or []),
        created_at=str(item.get("created_at") or ""),
        sentiment=max(-1.0, min(1.0, float(sentiment))),
        organizations=orgs, people=people,
        activity=str(raw.get("activity") or "")[:40], regime=str(raw.get("regime") or "")[:20],
        time_horizon=time_horizon, key_number=key_number, claim_type=claim_type,
        confidence=confidence, quote=str(raw.get("quote") or "")[:400],
        dense=dense, model=model_name, extracted_at=ids.utc_now().isoformat(),
    )


async def enrich(items: list[dict[str, Any]], config: Config) -> list[Extract]:
    """Cached-or-extracted structured records for these raw Alpaca news items.

    One LLM call covers every uncached article (capped at MAX_BATCH - beyond
    that, the oldest overflow articles fall back to bare rather than growing
    the call further; they get cached on the next cycle that has headroom).
    """
    cache = ExtractCache(config.paths.state / "news_extracts.json")
    out: list[Extract] = []
    pending: list[dict[str, Any]] = []
    for item in items:
        cached = cache.get(str(item.get("id")))
        if cached is not None:
            out.append(cached)
        else:
            pending.append(item)

    if not pending:
        return out

    to_call, overflow = pending[:MAX_BATCH], pending[MAX_BATCH:]
    out.extend(bare(item) for item in overflow)

    try:
        model = build_model(config, role="news_extract")
        articles = "\n\n".join(
            f"id: {it.get('id')}\nheadline: {it.get('headline')}\n"
            f"summary: {str(it.get('summary') or '')[:800]}"
            for it in to_call
        )
        prompt = EXTRACT_PROMPT.format(
            activities=", ".join(ACTIVITIES), regimes=", ".join(REGIMES),
            horizons=", ".join(TIME_HORIZONS), claim_types=", ".join(CLAIM_TYPES),
            articles=articles,
        )
        reply = await model.ainvoke(prompt)
        text = text_of(reply)
        served = (getattr(reply, "response_metadata", None) or {}).get("model_name", "news_extract")
        by_id = {str(r.get("id")): r for r in parse_json_array(text) if isinstance(r, dict)}
    except Exception as exc:  # noqa: BLE001 - fail open: bare extracts, never lose the articles
        print(f"[news_extract] batch of {len(to_call)} failed, falling back to headlines: {exc!r}")
        by_id, served = {}, ""

    fresh = [_coerce(by_id.get(str(it.get("id"))), it, served) for it in to_call]
    cache.put_many(fresh)
    out.extend(fresh)
    return out


def render_block(extracts: list[Extract]) -> str:
    """Dense text for prompt injection - one line per article.

    A bare extract (extraction never succeeded) renders as plain headline
    text plus the URL, identical in information content to the pre-D-066
    compaction plus the citation, so a total extraction outage degrades to
    that rather than to something worse.
    """
    lines = []
    for e in extracts:
        symbols = ",".join(e.symbols) or "-"
        when = e.created_at[:16]
        cite = f" <{e.url}>" if e.url else ""
        if e.is_bare():
            lines.append(f"- {e.dense} | {symbols} | {e.source} | {when}{cite}")
            continue
        orgs = ", ".join(e.organizations) or "-"
        people = ", ".join(e.people) or "-"
        number = f" | {e.key_number} ({e.claim_type})" if e.key_number else ""
        horizon = f"/{e.time_horizon}" if e.time_horizon else ""
        conf = f" conf={e.confidence:.1f}" if e.confidence is not None else ""
        lines.append(
            f"- [{e.sentiment:+.1f}{conf}] {e.activity or '?'}/{e.regime or '?'}{horizon} | "
            f"orgs: {orgs} | people: {people} | {symbols} | "
            f'"{e.dense}"{number} | {e.source} {when}{cite}'
        )
    return "\n".join(lines)
