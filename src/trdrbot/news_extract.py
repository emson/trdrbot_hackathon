"""News extraction: dense structured signal in place of headline-only (D-066).

D-065 compacted news to headlines because bodies were assumed to be filler -
an assumption, not a measurement. The user's own read: sentiment, named
organisations/people, the kind of event, and which regime it speaks to
(macro/sector/company) are frequently exactly what separates a real thesis
from noise, and a bare headline throws that away.

The fix is not "send bodies back" (that reintroduces the ~2k-char/article cost
D-065 removed) - it is a cheap dedicated extraction pass that reads the body
ONCE per article and distills it to a few structured fields plus one dense
sentence. That distillation is then:

  1. injected into every prompt that used to get a headline (research,
     discovery, muse, and decide's compacted get_news), replacing "- headline
     | source | symbols" with a denser line carrying the same char budget but
     more decision-relevant content, and
  2. PERSISTED, keyed by article id, in `state/news_extracts.json` - this is
     the standardised structured store: same schema every time, one record
     per article, deduplicated for free because the same article recurs
     across research/discovery/muse/sensors within a day and each currently
     pulls overlapping windows.

**Fail open, per record.** A batch extraction call covers every uncached
article in one shot (cheap model, one call per cycle - never one call per
article). If the call fails outright, or the model mismatches/omits an id,
that article falls back to a BARE extract (dense=headline, everything else
unset) rather than losing it - same discipline as compact.py. Bare extracts
are never written to the cache, so a transient failure gets retried next
cycle instead of being permanently frozen as "unknown".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import ids
from .config import Config
from .llm import build_model

# Deferred import (not at module top level): research.py imports THIS module
# to render its news block, so an eager import here would be circular. By
# call time both modules are already fully loaded, so this is safe.

#: Controlled-ish vocabulary offered to the model so `activity` stays
#: consistent enough to scan across articles; not enforced, just prompted.
ACTIVITIES = ["earnings", "guidance", "M&A", "regulatory", "macro_data",
              "rating_change", "product", "leadership", "other"]
REGIMES = ["macro", "sector", "company"]

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
    dense: str = ""
    model: str = ""
    extracted_at: str = ""

    def is_bare(self) -> bool:
        return self.sentiment is None


def bare(item: dict[str, Any]) -> Extract:
    return Extract(
        id=str(item.get("id")), headline=str(item.get("headline") or ""),
        source=str(item.get("source") or ""), symbols=list(item.get("symbols") or []),
        created_at=str(item.get("created_at") or ""), dense=str(item.get("headline") or ""),
    )


class ExtractCache:
    """Standardised structured store, one record per article id.

    Same shape as `sensors.SensorState` - a flat JSON dict, load on
    construction, rewrite whole-file on save. Deliberately not a database:
    volume is a few dozen articles a day, and a plain file is inspectable
    with `cat` mid-competition.
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
        self.path.write_text(json.dumps(self._items, indent=2, sort_keys=True))


def _coerce(raw: Any, item: dict[str, Any], model_name: str) -> Extract:
    """One salvaged record from the model's JSON -> a validated Extract.

    Every field is defensively typed - a model returning a string where a
    list was asked for must not crash the batch, just fall back to empty.
    """
    if not isinstance(raw, dict):
        return bare(item)
    sentiment = raw.get("sentiment")
    if not isinstance(sentiment, (int, float)):
        return bare(item)
    orgs = [str(x) for x in raw.get("organizations", []) if isinstance(x, str)][:5]
    people = [str(x) for x in raw.get("people", []) if isinstance(x, str)][:3]
    dense = str(raw.get("dense") or item.get("headline") or "")[:240]
    return Extract(
        id=str(item.get("id")), headline=str(item.get("headline") or ""),
        source=str(item.get("source") or ""), symbols=list(item.get("symbols") or []),
        created_at=str(item.get("created_at") or ""),
        sentiment=max(-1.0, min(1.0, float(sentiment))),
        organizations=orgs, people=people,
        activity=str(raw.get("activity") or "")[:40], regime=str(raw.get("regime") or "")[:20],
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
            activities=", ".join(ACTIVITIES), regimes=", ".join(REGIMES), articles=articles,
        )
        reply = await model.ainvoke(prompt)
        text = reply.content if isinstance(reply.content, str) else "\n".join(
            b.get("text", "") for b in reply.content if isinstance(b, dict) and b.get("type") == "text"
        )
        served = (getattr(reply, "response_metadata", None) or {}).get("model_name", "news_extract")
        from .research import _parse_json_block
        parsed = _parse_json_block(text)
        by_id = {str(r.get("id")): r for r in parsed if isinstance(r, dict)} if isinstance(parsed, list) else {}
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
    text, identical in information content to the pre-D-066 compaction, so a
    total extraction outage degrades to exactly the old behaviour rather than
    to something worse.
    """
    lines = []
    for e in extracts:
        symbols = ",".join(e.symbols) or "-"
        when = e.created_at[:16]
        if e.is_bare():
            lines.append(f"- {e.dense} | {symbols} | {e.source} | {when}")
            continue
        orgs = ", ".join(e.organizations) or "-"
        people = ", ".join(e.people) or "-"
        lines.append(
            f"- [{e.sentiment:+.1f}] {e.activity or '?'}/{e.regime or '?'} | "
            f"orgs: {orgs} | people: {people} | {symbols} | "
            f'"{e.dense}" | {e.source} {when}'
        )
    return "\n".join(lines)
