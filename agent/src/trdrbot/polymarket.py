"""Polymarket Gamma API client - prediction-market odds. Read-only, no auth.

Prediction markets are pre-digested crowd wisdom (D-015): tiny, numeric, and
the highest signal-to-noise source available. They also feed the calibration
synergy - a market-implied probability is a free external benchmark against
our own stated confidence (D-013).

Every defensive branch below encodes a quirk verified live against the real
endpoints by a prior incarnation of this project (see
docs/sources/polymarket_gamma_api.md). They are not hypothetical: quirk 1
alone silently yields a single character where a caller expects a price.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

GAMMA = "https://gamma-api.polymarket.com"

#: One event can nest a very long tail of markets (a real case: q="iran"
#: matched an event with 123 candidate-leader markets). Without a per-event
#: cap that single event fills every result slot and crowds out everything
#: relevant.
MAX_PER_EVENT = 3


def _decode_json_field(raw: Any) -> list[Any]:
    """`outcomes` / `outcomePrices` arrive as JSON-encoded STRINGS, not arrays.

    The API returns `"outcomePrices": "[\\"0.505\\", \\"0.495\\"]"` - a string
    that happens to contain JSON. Indexing it directly gives a character, not
    a price, which is a silent corruption rather than an error. Requires a
    second decode.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            out = json.loads(raw)
            return out if isinstance(out, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _coerce_float(v: Any) -> float | None:
    """None on failure, never a fabricated 0.0 - absence must read as absence."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _volume(m: dict[str, Any]) -> float | None:
    """`volume` is frequently a string while `volumeNum` is a native float."""
    return _coerce_float(m.get("volumeNum")) or _coerce_float(m.get("volume"))


def _usable(m: dict[str, Any]) -> bool:
    """An 'open' event can still nest markets that are useless to us.

    Event-level active/closed filters do NOT filter the nested markets, so a
    returned open event may contain already-resolved markets (closed, with
    degenerate 0/1 prices) and unlaunched placeholders (inactive, prices
    literally null). Both must be rejected here or they read as real
    probabilities of 0% and 100%.
    """
    if m.get("closed") is True or m.get("active") is False:
        return False
    prices = [_coerce_float(p) for p in _decode_json_field(m.get("outcomePrices"))]
    if len(prices) != 2 or any(p is None for p in prices):
        return False
    # Degenerate pair = already resolved. A genuine live market never sits
    # exactly at 0/1.
    if {round(p, 4) for p in prices} <= {0.0, 1.0}:
        return False
    return True


def _yes_probability(m: dict[str, Any]) -> float | None:
    """Implied P(Yes) for a binary Yes/No market, else None.

    Non-binary markets (head-to-head match-ups, Over/Under lines) are skipped
    deliberately rather than coerced - reading 'the first outcome' of a market
    that isn't Yes/No produces a confident, meaningless number.
    """
    outcomes = [str(o).strip().lower() for o in _decode_json_field(m.get("outcomes"))]
    prices = [_coerce_float(p) for p in _decode_json_field(m.get("outcomePrices"))]
    if len(outcomes) != 2 or len(prices) != 2:
        return None
    if "yes" not in outcomes or "no" not in outcomes:
        return None
    return prices[outcomes.index("yes")]


def _flatten(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in events:
        kept = 0
        for m in ev.get("markets") or []:
            if kept >= MAX_PER_EVENT:
                break
            if not _usable(m):
                continue
            p = _yes_probability(m)
            if p is None:
                continue
            out.append({
                "slug": m.get("slug"),
                "question": m.get("question") or ev.get("title"),
                "probability": p,
                "volume": _volume(m),
                "end_date": m.get("endDate"),
                "event_title": ev.get("title"),
            })
            kept += 1
    return out


async def search(query: str, *, limit: int = 5, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Free-text market discovery via Gamma's relevance ranking.

    Deliberately sends no `sort` param: adding `sort=volume` destroys
    relevance (verified live - a q="iran" search returned an unrelated
    high-volume World Cup market as its top hit). Gamma's default relevance
    ordering is the useful one here.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(f"{GAMMA}/public-search", params={"q": query})
        r.raise_for_status()
        body = r.json()

    # A genuine zero-result response OMITS the `events` key entirely rather
    # than returning an empty list - body["events"] raises KeyError on a
    # perfectly valid, common response.
    events = body.get("events") or []
    return _flatten(events)[:limit]


async def check(timeout: float = 10.0) -> bool:
    """Reachability probe. No auth required or used."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                f"{GAMMA}/markets", params={"limit": 1, "active": "true", "closed": "false"}
            )
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False
