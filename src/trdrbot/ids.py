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
from datetime import datetime, timezone


def _short_hash(*parts: str, n: int = 8) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return h[:n]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(dt: datetime | None = None) -> str:
    return (dt or utc_now()).strftime("%Y%m%dT%H%M%SZ")


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
