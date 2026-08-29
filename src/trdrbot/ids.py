"""Identifier derivation - the provenance spine (D-014, D-018, D-019).

Two ids carry the whole design:

- ``position_id`` threads a strategic position through the journal, the wiki,
  elfmem, and Alpaca. Alpaca has no multi-leg position concept, so this is the
  only thing tying the legs of a spread to one another and to a thesis.

- ``client_order_id`` derives from the inbox BATCH, never from the decision.
  A crash-retry re-invokes a nondeterministic LLM, which may decide something
  different; a decision-derived id would then differ and Alpaca would accept a
  second, different position. Batch-derivation makes any resubmission from the
  same batch carry the same id, so the broker rejects the duplicate. Safe
  because a cycle produces at most one action.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo


def _short_hash(*parts: str, n: int = 8) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return h[:n]


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_stamp(dt: datetime | None = None) -> str:
    return (dt or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def today() -> date:
    """The UTC date - for anything compared against UTC-stamped data.

    Horizons, ledger maturity, attribution, cache `as_of` staleness and journal
    ages are all written from `utc_now()`, so they must be READ against the
    same clock. `date.today()` is the local date, which on any machine west of
    UTC is yesterday for part of every day - so a horizon written as today's
    UTC date looked unreached, and a cache written this morning looked a day
    older than it was.
    """
    return utc_now().date()


def market_today() -> date:
    """The US-market (ET) date - for anything that means "the trading day".

    Days-to-expiry, the competition deadline and weekday gates are claims
    about the market's calendar, not about UTC. A UTC date is already tomorrow
    from 20:00 ET, which puts DTE off by one every single evening - precisely
    when a short-dated option's gamma makes the number matter most. The
    Saturday research gate had the mirror error: keyed on the UTC weekday, it
    suppressed research from Friday 20:00 ET.
    """
    return datetime.now(ZoneInfo("America/New_York")).date()


def position_id(underlying: str, strategy: str, dt: datetime | None = None) -> str:
    """e.g. pos_20260828_SPY_bull_put_spread_a3f2c1d8 - sortable and greppable.

    Unique per call. Two positions on the same underlying and strategy opened
    in the same second previously collided into one id - which would have
    meant two real positions silently sharing (and overwriting) a single
    wiki page, with the second one's thesis and exit rules destroying the
    first's. Same root cause as the item_id collision found live.
    """
    d = (dt or utc_now()).strftime("%Y%m%d")
    return f"pos_{d}_{underlying.upper()}_{strategy}_{uuid.uuid4().hex[:8]}"


def batch_id(item_ids: list[str]) -> str:
    """Stable across retries: same set of pending items -> same id, any order."""
    return f"bat_{_short_hash(*sorted(item_ids), n=12)}"


def client_order_id(batch: str, leg: int = 0) -> str:
    """Derived from the batch (INV-18).

    Kept short deliberately: Alpaca's length limit for this field is not yet
    verified, and a short hash fits any plausible limit. If the limit turns out
    to be generous we can make this more readable.
    """
    return f"trdr-{_short_hash(batch, str(leg), n=16)}"


def journal_id(kind: str) -> str:
    """Same collision flaw as item_id had, less destructive but still wrong.

    The journal is append-only JSONL so entries are never overwritten - but
    two entries sharing an id breaks traceability, and `decision_ref` lookups
    could resolve to the wrong entry. Several entries per second is normal
    (decision + execution + reconciliation in one tick).
    """
    return f"jrn_{utc_stamp()}_{kind[:3]}{uuid.uuid4().hex[:6]}"


def opportunity_id(source: str, payload: dict[str, Any]) -> str:
    """Identity of an opportunity is the CLAIM, not the moment it was written.

    Every other item type wants `item_id`'s uuid4, and for a good measured
    reason (see below). Opportunities are the exception: they are generated
    repeatedly from overlapping evidence, so uniqueness-by-construction meant
    identical claims could never dedup. Measured on the live pending directory:
    22 opportunities, XLE six times and MU five, with three byte-identical band
    pairs from three separate muse runs - all entering ONE decide batch and one
    prompt, where they read as five independent signals rather than one claim
    made five times.

    Keyed on (underlying, horizon, rounded bands) per source per UTC day. The
    source stays in the id deliberately: two DIFFERENT generators reaching the
    same claim is real corroboration and the decide cycle should see both.
    The date keeps a claim re-made tomorrow, against tomorrow's quotes, a new
    item rather than a duplicate of today's.
    """
    def _band(v: Any) -> str:
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return "-"

    key = _short_hash(
        str(payload.get("underlying", "")).upper(),
        str(payload.get("horizon", "")),
        _band(payload.get("band_low")),
        _band(payload.get("band_high")),
        n=12,
    )
    return f"opp_{utc_stamp()[:8]}_{source}_{key}"


def item_id(kind: str, source: str) -> str:
    """Unique per item, not merely per second.

    The previous form hashed (kind, source, utc_stamp) - all identical for
    items written in the same second - so a sensor emitting a batch produced
    N identical filenames and silently overwrote its own output. Found live:
    a news sensor reported "20 new" and left 2 files on disk. Nothing before
    sensors ever wrote more than one item per second, so it stayed invisible
    until then. uuid4 removes the collision entirely rather than narrowing
    the window with finer timestamps.
    """
    return f"{kind[:3]}_{utc_stamp()}_{source}_{uuid.uuid4().hex[:8]}"
