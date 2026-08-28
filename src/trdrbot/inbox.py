"""File-based inbox: pending -> processed, with a dead-letter path.

The inbox is the testing seam. Anything can drop an item in - the collector,
a future feed, or a human with `cp` - and the processor drains whatever is
pending without caring who wrote it.

At-least-once: items are archived only after the batch completes, so a crash
mid-batch leaves them pending and they are reprocessed. That is what makes
INV-20's dead-letter necessary - without it a permanently-failing item is
retried every tick forever and the pipeline stalls while appearing healthy.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ids
from .config import Paths
from .failures import Cause


@dataclass
class Item:
    id: str
    ts: str
    type: str
    source: str
    payload: dict[str, Any]
    trust: str = "primary"
    retry_count: int = 0
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "type": self.type,
            "source": self.source,
            "trust": self.trust,
            "retry_count": self.retry_count,
            "payload": self.payload,
        }


class Inbox:
    def __init__(self, paths: Paths, max_retries: int = 3) -> None:
        self.paths = paths
        self.max_retries = max_retries

    def write(
        self,
        type_: str,
        payload: dict[str, Any],
        source: str = "manual",
        trust: str = "primary",
    ) -> Item:
        item = Item(
            id=ids.item_id(type_, source),
            ts=ids.utc_now().isoformat(),
            type=type_,
            source=source,
            payload=payload,
            trust=trust,
        )
        path = self.paths.inbox_pending / f"{item.id}.json"
        path.write_text(json.dumps(item.to_dict(), indent=2))
        item.path = path
        return item

    def expire_stale(self, max_age_min: float, journal=None) -> int:
        """Move opportunity items older than max_age_min out of pending.

        An opportunity priced against quotes that no longer exist is worse
        than no opportunity: it occupies the decide context and the agent
        spends a cycle rejecting it on staleness, which it has done
        repeatedly. Only `opportunity` items expire - news and fills are
        history and stay valid however old (D-043).
        """
        from datetime import datetime, timezone
        n = 0
        for item in self.pending():
            if item.type != "opportunity":
                continue
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(item.ts)).total_seconds() / 60.0
            except (ValueError, TypeError, AttributeError):
                continue
            if age > max_age_min:
                self.archive([item])
                if journal is not None:
                    # `item_kind`, not `kind` - Journal.append's own first
                    # positional IS `kind`, so passing it as a keyword raises
                    # TypeError. Latent since D-043: it only fires once an
                    # opportunity actually ages past the stale window, which
                    # took three days to happen and would have crashed a live
                    # tick (D-062).
                    journal.append("inbox_expired", item_id=item.id,
                                   age_min=round(age, 1), item_kind=item.type,
                                   reason="stale_opportunity")
                n += 1
        return n

    def pending(self) -> list[Item]:
        items: list[Item] = []
        for p in sorted(self.paths.inbox_pending.glob("*.json")):
            try:
                d = json.loads(p.read_text())
                items.append(
                    Item(
                        id=d["id"],
                        ts=d["ts"],
                        type=d["type"],
                        source=d.get("source", "unknown"),
                        payload=d.get("payload", {}),
                        trust=d.get("trust", "primary"),
                        retry_count=int(d.get("retry_count", 0)),
                        path=p,
                    )
                )
            except (json.JSONDecodeError, KeyError):
                # Malformed on disk: straight to dead-letter, it will never parse.
                self._dead_letter(p, reason="unparseable")
        return items

    def archive(self, items: list[Item]) -> None:
        day = ids.utc_now().strftime("%Y-%m-%d")
        dest = self.paths.inbox_processed / day
        dest.mkdir(parents=True, exist_ok=True)
        for it in items:
            if it.path and it.path.exists():
                # Idempotent: a re-archive of an already-moved item is a no-op,
                # which matters for the watchdog-killed-mid-archive case.
                shutil.move(str(it.path), str(dest / it.path.name))

    def record_failure(self, item: Item, reason: str, cause: Cause = Cause.TRANSIENT) -> None:
        """Apply the retry policy for this failure's cause (D-019 #6).

        CONFIG failures deliberately do not touch the retry counter: our setup
        being broken is not the item's fault, and letting it dead-letter an
        innocent observation loses a real signal for a reason unrelated to it.
        """
        if not item.path or not item.path.exists():
            return

        if cause in (Cause.CONFIG, Cause.BUG):
            return  # blameless - leave it pending, untouched

        if cause is Cause.PERMANENT:
            self._dead_letter(item.path, reason=f"[permanent] {reason}")
            return

        item.retry_count += 1
        if item.retry_count >= self.max_retries:
            self._dead_letter(item.path, reason=f"[transient x{item.retry_count}] {reason}")
        else:
            item.path.write_text(json.dumps(item.to_dict(), indent=2))

    def _dead_letter(self, path: Path, reason: str) -> None:
        self.paths.inbox_failed.mkdir(parents=True, exist_ok=True)
        dest = self.paths.inbox_failed / path.name
        shutil.move(str(path), str(dest))
        (self.paths.inbox_failed / f"{path.stem}.reason.txt").write_text(reason)
