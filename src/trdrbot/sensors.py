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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import Config
from .inbox import Inbox

# A fetch fn takes (tools, config) and returns a list of raw records.
FetchFn = Callable[[dict[str, Any], Config], Awaitable[list[dict[str, Any]]]]


@dataclass
class Sensor:
    id: str
    every_n_ticks: int
    trust: str
    policy: str
    item_type: str
    fetch: FetchFn
    #: extracts a stable dedup key from a raw record (change_only/filter policies)
    key_of: Callable[[dict[str, Any]], str] = lambda r: json.dumps(r, sort_keys=True)
    #: turns a raw record into an inbox item payload
    to_payload: Callable[[dict[str, Any]], dict[str, Any]] = lambda r: r

    def due(self, tick: int) -> bool:
        return tick % self.every_n_ticks == 0


class SensorState:
    """Per-sensor seen-keys, so a poll only emits genuinely new material."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, list[str]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except json.JSONDecodeError:
                self._data = {}

    def unseen(self, sensor_id: str, keys: list[str]) -> list[str]:
        seen = set(self._data.get(sensor_id, []))
        return [k for k in keys if k not in seen]

    def mark(self, sensor_id: str, keys: list[str], *, keep: int = 500) -> None:
        prior = self._data.get(sensor_id, [])
        self._data[sensor_id] = (prior + keys)[-keep:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))


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
        "headline": rec.get("headline"),
        "summary": (rec.get("summary") or "")[:400],
        "source": rec.get("source"),
        "symbols": rec.get("symbols"),
        "created_at": rec.get("created_at"),
        "url": rec.get("url"),
    }


# ---------------------------------------------------------------- registry

REGISTRY: list[Sensor] = [
    Sensor(
        id="alpaca_news",
        every_n_ticks=1,  # aligned to the decide cadence; config-tunable later
        trust="primary",  # a newswire, not social chatter
        policy="change_only",
        item_type="news",
        fetch=_fetch_alpaca_news,
        key_of=lambda r: str(r.get("id")),
        to_payload=_news_payload,
    ),
    # Next in signal-per-token order (D-015): polymarket -> google_feed ->
    # x_social. Each is one entry here plus a fetch fn - no pipeline change.
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

        keys = [sensor.key_of(r) for r in records]
        fresh_keys = set(state.unseen(sensor.id, keys))
        fresh = [r for r, k in zip(records, keys) if k in fresh_keys]

        for rec in fresh:
            inbox.write(
                sensor.item_type,
                sensor.to_payload(rec),
                source=sensor.id,
                trust=sensor.trust,
            )
        state.mark(sensor.id, keys)
        counts[sensor.id] = len(fresh)
        if verbose and fresh:
            print(f"[sensor {sensor.id}] {len(fresh)} new of {len(records)} fetched")

    state.save()
    return counts
