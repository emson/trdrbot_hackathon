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
from datetime import datetime, timezone


def _short_hash(*parts: str, n: int = 8) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return h[:n]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(dt: datetime | None = None) -> str:
    return (dt or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def position_id(underlying: str, strategy: str, dt: datetime | None = None) -> str:
    """e.g. pos_20260828_SPY_bull_put_spread_a3f2c1d8 - sortable and greppable."""
    d = (dt or utc_now()).strftime("%Y%m%d")
    return f"pos_{d}_{underlying.upper()}_{strategy}_{_short_hash(d, underlying, strategy, utc_stamp())}"


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
    return f"jrn_{utc_stamp()}_{kind[:3]}{_short_hash(kind, utc_stamp(), n=4)}"


def item_id(kind: str, source: str) -> str:
    return f"{kind[:3]}_{utc_stamp()}_{source}_{_short_hash(kind, source, utc_stamp(), n=6)}"
