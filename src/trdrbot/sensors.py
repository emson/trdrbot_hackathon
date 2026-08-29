"""C6/C20 - the sensor registry (D-015). Deterministic, no LLM.

A sensor is a declared information source. Adding Polymarket, Google feeds or
an X/Twitter MCP is one registry entry, not new pipeline code - that is the
whole point of the shape.

Four properties do the work:
  every_n_ticks  cadence as counter-modulo, so we only reach for a source the
                 tick actually needs (and only spawn the MCP servers required)
  policy         raw | filter | change_only
  trust          primary | secondary | social - propagates into every derived
                 item and into the decide prompt (INV-13)
  state          per-sensor last-seen ids, so the same article is not re-emitted
                 on every poll (FM-22)

A failing sensor never fails a tick (INV-16): it logs, is skipped, and the
others proceed.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .inbox import Inbox

# A fetch fn takes (tools, config) and returns a list of raw records.
FetchFn = Callable[[dict[str, Any], Config], Awaitable[list[dict[str, Any]]]]


@dataclass
class Sensor:
    id: str
    every_n_ticks: int
    trust: str
    #: `filter` - emit records whose identity has not been seen (articles).
    #: `change_only` - emit only when a numeric value moves materially (odds).
    #: `raw` - emit everything, every poll.
    policy: str
    item_type: str
    fetch: FetchFn
    #: stable identity for a record - dedup key (filter) or value key (change_only)
    key_of: Callable[[dict[str, Any]], str] = lambda r: json.dumps(r, sort_keys=True)
    #: turns a raw record into an inbox item payload
    to_payload: Callable[[dict[str, Any]], dict[str, Any]] = lambda r: r
    #: change_only: the number being watched. None means "skip this record".
    value_of: Callable[[dict[str, Any]], float | None] | None = None
    #: change_only: minimum absolute move from the last emitted value
    change_threshold: float = 0.0

    def due(self, tick: int) -> bool:
        return tick % self.every_n_ticks == 0


class SensorState:
    """Per-sensor memory of what has already been emitted.

    Two shapes, because the two policies need different things: `filter`
    remembers which identities it has seen; `change_only` remembers the last
    value it emitted per key, so materiality is measured against what the
    agent was actually last told - not against the previous poll.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: dict[str, list[str]] = {}
        self._values: dict[str, dict[str, float]] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._seen = raw.get("seen", {})
                self._values = raw.get("values", {})
            except json.JSONDecodeError:
                pass

    def unseen(self, sensor_id: str, keys: list[str]) -> list[str]:
        seen = set(self._seen.get(sensor_id, []))
        return [k for k in keys if k not in seen]

    def mark(self, sensor_id: str, keys: list[str], *, keep: int = 500) -> None:
        prior = self._seen.get(sensor_id, [])
        self._seen[sensor_id] = (prior + keys)[-keep:]

    def last_value(self, sensor_id: str, key: str) -> float | None:
        return self._values.get(sensor_id, {}).get(key)

    def set_value(self, sensor_id: str, key: str, value: float) -> None:
        self._values.setdefault(sensor_id, {})[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"seen": self._seen, "values": self._values}, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------- fetchers


async def _fetch_alpaca_news(tools: dict[str, Any], config: Config) -> list[dict[str, Any]]:
    """Alpaca's news tool is watchlist-scopeable server-side (verified: it takes
    a `symbols` param), so the bulk of relevance filtering happens before the
    data ever reaches us - much lighter than client-side keyword matching."""
    from . import mcp_client

    symbols = ",".join(config.watchlist)
    r = await mcp_client.call(
        tools, "get_news", symbols=symbols, limit=20, exclude_contentless=True, sort="desc"
    )
    if isinstance(r, dict):
        return r.get("news") or []
    return r if isinstance(r, list) else []


def _news_payload(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        # The publisher's own article id. Used as this sensor's dedup key
        # above, and CARRIED THROUGH deliberately (D-070): it is the cache key
        # `news_extract` uses. Dropping it - as this payload originally did -
        # meant the decide path fell back to the inbox item id, so the same
        # article extracted from the inbox and from a direct `get_news` call
        # landed under two different keys, was paid for twice, and stored
        # twice. The dedup the cache exists for, silently defeated.
        "id": rec.get("id"),
        "headline": rec.get("headline"),
        "summary": (rec.get("summary") or "")[:400],
        "source": rec.get("source"),
        "symbols": rec.get("symbols"),
        "created_at": rec.get("created_at"),
        "url": rec.get("url"),
    }


# ---------------------------------------------------------------- registry

async def _fetch_polymarket(tools: dict[str, Any], config: Config) -> list[dict[str, Any]]:
    """Prediction-market odds for the configured macro questions.

    Read-only, no auth, no cost - the cheapest external signal we have, and
    the densest: one number that already aggregates a crowd's view.
    """
    from . import polymarket

    out: list[dict[str, Any]] = []
    for query in config.polymarket_queries:
        try:
            out.extend(await polymarket.search(query, limit=3))
        except Exception as exc:  # noqa: BLE001 - one bad query must not lose the rest
            print(f"[sensor polymarket] query {query!r} failed: {exc!r}")
    return out


REGISTRY: list[Sensor] = [
    Sensor(
        id="alpaca_news",
        every_n_ticks=1,  # aligned to the decide cadence; config-tunable later
        trust="primary",  # a newswire, not social chatter
        policy="filter",  # dedup by article id - news has no value to threshold
        item_type="news",
        fetch=_fetch_alpaca_news,
        key_of=lambda r: str(r.get("id")),
        to_payload=_news_payload,
    ),
    Sensor(
        id="polymarket",
        # Slow-moving by nature (D-015). Polling odds every tick would spend
        # requests to learn nothing - they move over hours, not seconds.
        every_n_ticks=12,
        trust="secondary",  # a real market's aggregate, but not a newswire fact
        policy="change_only",
        item_type="prediction_market",
        fetch=_fetch_polymarket,
        key_of=lambda r: str(r.get("slug")),
        value_of=lambda r: r.get("probability"),
        # 5 percentage points. Below that an implied probability is mostly
        # noise and liquidity drift; above it, something changed.
        change_threshold=0.05,
        to_payload=lambda r: {
            "question": r.get("question"),
            "implied_probability": r.get("probability"),
            "volume_usd": r.get("volume"),
            "resolves": r.get("end_date"),
            "slug": r.get("slug"),
        },
    ),
    # Remaining in signal-per-token order (D-015): google_feed -> x_social.
    # Each is one entry here plus a fetch fn - no pipeline change.
]


async def collect(
    tools: dict[str, Any], config: Config, inbox: Inbox, tick: int, *, verbose: bool = True
) -> dict[str, int]:
    """Run every sensor due this tick; write new material to the inbox."""
    state = SensorState(config.paths.state / "sensors.json")
    counts: dict[str, int] = {}

    for sensor in REGISTRY:
        if not sensor.due(tick):
            continue
        try:
            records = await sensor.fetch(tools, config)
        except Exception as exc:  # noqa: BLE001 - INV-16: never fail the tick
            print(f"[sensor {sensor.id}] failed, skipping: {exc!r}")
            continue

        if sensor.policy == "change_only":
            # Emit only when the watched number has moved materially since the
            # last time we told the agent about it. Comparing against the last
            # EMITTED value (not the previous poll) means a slow drift still
            # eventually surfaces instead of creeping past unnoticed one
            # sub-threshold step at a time.
            fresh = []
            for rec in records:
                if sensor.value_of is None:
                    continue
                value = sensor.value_of(rec)
                if value is None:
                    continue
                key = sensor.key_of(rec)
                prev = state.last_value(sensor.id, key)
                if prev is None or abs(value - prev) >= sensor.change_threshold:
                    fresh.append(rec)
                    state.set_value(sensor.id, key, value)
        elif sensor.policy == "raw":
            fresh = list(records)
        else:  # `filter` - identity dedup
            keys = [sensor.key_of(r) for r in records]
            fresh_keys = set(state.unseen(sensor.id, keys))
            fresh = [r for r, k in zip(records, keys) if k in fresh_keys]
            state.mark(sensor.id, keys)

        for rec in fresh:
            inbox.write(
                sensor.item_type,
                sensor.to_payload(rec),
                source=sensor.id,
                trust=sensor.trust,
            )
        counts[sensor.id] = len(fresh)
        if verbose and fresh:
            print(f"[sensor {sensor.id}] {len(fresh)} new of {len(records)} fetched")

    state.save()
    return counts
