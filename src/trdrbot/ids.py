"""Identifier derivation - the provenance spine (D-014, D-018, D-019).

Two ids carry the whole design:

- ``position_id`` threads a strategic position through the journal, the wiki,
  elfmem, and Alpaca. Alpaca has no multi-leg position concept, so this is the
  only thing tying the legs of a spread to one another and to a thesis.

- ``client_order_id`` derives from the inbox BATCH and the ORDER'S OWN
  CONTENT, never from the decision. A crash-retry re-invokes a
  nondeterministic LLM, which may decide something different; a
  decision-derived id would then differ and Alpaca would accept a second,
  different position. Batch-derivation makes any resubmission of the SAME
  intent from the same batch carry the same id, so the broker rejects the
  duplicate - while a genuinely different order in the same cycle gets a
  different id and can actually execute.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
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


def market_now() -> datetime:
    """The current moment in US-market (ET) time."""
    return datetime.now(ZoneInfo("America/New_York"))


def market_today() -> date:
    """The US-market (ET) date - for anything that means "the trading day".

    Days-to-expiry, the competition deadline and weekday gates are claims
    about the market's calendar, not about UTC. A UTC date is already tomorrow
    from 20:00 ET, which puts DTE off by one every single evening - precisely
    when a short-dated option's gamma makes the number matter most. The
    Saturday research gate had the mirror error: keyed on the UTC weekday, it
    suppressed research from Friday 20:00 ET.
    """
    return market_now().date()


#: When the US equity session ends. One definition: `idle.minutes_to_close`
#: had its own copy, and a clock this project keeps two copies of is a clock it
#: eventually disagrees with itself about.
MARKET_CLOSE_ET = time(16, 0)


def session_closed_on(day: Any, now: datetime | None = None) -> bool:
    """Has the trading session ON `day` ENDED? False if it cannot be judged.

    **A DATE IS NOT A SESSION** (I-79), and this is D-107's other half. Maturity
    was `horizon <= market_today()`, which is true from 00:00 ET - so the first
    overnight housekeeping tick after midnight resolved every forecast for that
    day against `_spot`, i.e. the PREVIOUS session's last print or an
    after-hours IEX trade, sixteen hours before the session it named had closed.
    `Entry.matured`'s own docstring already promised "the horizon's SESSION has
    ended - not merely its UTC date begun", and the code delivered the ET
    version of exactly the bug D-107 fixed, four hours later. The journal shows
    the morning side of it: CRWD and XOM for 09-01, both resolved at 05:25 ET on
    09-01.

    One helper, two callers - `ledger.Entry.matured` and
    `attribution._horizon_passed` - so the two halves of resolution cannot drift
    apart again. An unparseable day is "cannot judge", which leaves the row
    PENDING rather than resolving it against nothing.
    """
    try:
        d = day if isinstance(day, date) else date.fromisoformat(str(day))
    except (ValueError, TypeError):
        return False
    et = now or market_now()
    if d < et.date():
        return True
    return d == et.date() and et.time() >= MARKET_CLOSE_ET


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


def client_order_id(batch: str, legs: Sequence[tuple[str, str, int]] = ()) -> str:
    """Derived from the batch AND the order's own content (INV-18).

    `legs` is the order as `(symbol, side, qty)` triples, sorted here so leg
    order cannot change the id. Three properties, and the third is why this
    argument exists (I-101):

    - **Stable across a crash-retry of the same intent.** Same batch, same
      legs, same id - the broker rejects the duplicate, which is the whole
      guarantee.
    - **Distinct for a genuinely different order in the same cycle.** The id
      used to be computed once per tool and stamped on every call, so
      close-A-then-open-B could not execute: the second order was refused as a
      duplicate of the first, and the model's own retry id was overwritten and
      refused again. The live journal already carries a two-order cycle.
    - **Identical for two IDENTICAL orders in one cycle**, which collapse to
      one submission. That is the safe direction and is exactly what "at most
      one action per situation" already meant.

    Kept short deliberately: Alpaca's length limit for this field is not yet
    verified, and a short hash fits any plausible limit.
    """
    parts = sorted(f"{str(sym).strip().upper()}|{str(side).strip().lower()}|{int(qty)}"
                   for sym, side, qty in legs)
    return f"trdr-{_short_hash(batch, *parts, n=16)}"


def journal_id(kind: str) -> str:
    """Same collision flaw as item_id had, less destructive but still wrong.

    The journal is append-only JSONL so entries are never overwritten - but
    two entries sharing an id breaks traceability, and `decision_ref` lookups
    could resolve to the wrong entry. Several entries per second is normal
    (decision + execution + reconciliation in one tick).
    """
    return f"jrn_{utc_stamp()}_{kind[:3]}{uuid.uuid4().hex[:6]}"


def age_days(stamp: Any) -> float | None:
    """How long ago an ISO timestamp was, in days. None if it is not one.

    One reader for "how old is this row", because two had already appeared -
    the Coach's gauge window and health's recurrence scoring ask the same
    question of the same `ts` field, and a clock this project keeps two copies
    of is a clock this project eventually disagrees with itself about.

    None means UNPARSEABLE, which is not the same as old: every caller here
    treats an unknown age as "cannot judge" and takes the path that does not
    discard the row.
    """
    raw = str(stamp or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (utc_now() - dt).total_seconds() / 86400.0


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
