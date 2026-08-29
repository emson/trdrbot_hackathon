"""Append-only JSONL journal - ground truth and rebuild path (D-014).

Write-ahead is mandatory (INV-18): the decision is journalled BEFORE the order
is submitted. INV-27 is the other half - on retry, the processor must read that
record and resume rather than re-decide, or write-ahead buys nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ids, store


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, kind: str, **fields: Any) -> str:
        entry = {
            "id": ids.journal_id(kind),
            "ts": ids.utc_now().isoformat(),
            "kind": kind,
            **fields,
        }
        store.append_jsonl(self.path, entry)  # advisory=False: ground truth
        return str(entry["id"])

    def read(self) -> Iterator[dict[str, Any]]:
        """Every entry, skipping any line that cannot be parsed.

        This is the ground-truth store and it was once the LEAST fault-tolerant
        reader in the system: a bare `json.loads` per line, where `ledger` and
        `health` already skipped bad ones. Appends are a buffered write and
        rows carry a 2000-char summary plus the recalled block ids, so a crash
        mid-flush really can leave a partial line - and one of those made
        `last_decision_at`, `unresolved_decision`, the muse nonce, the muse
        daily cap and `coach.pulse` all raise at once.

        Skipping is right rather than raising, but silence is not: a corrupt
        line means a lost event, so it is counted and printed.
        """
        rows, skipped = store.read_jsonl(self.path)
        if skipped:
            print(f"[journal] skipped {skipped} unparseable line(s) in {self.path.name}")
        yield from rows

    def last_decision_at(self) -> datetime | None:
        """When the agent last actually reasoned. None if never.

        Used by the market pulse (D-042) to notice it has gone quiet while
        holding risk - the failure mode is silence that looks like calm.
        """
        latest = None
        for row in self.read():
            if row.get("kind") not in ("decision",):
                continue
            ts = row.get("ts")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if latest is None or dt > latest:
                latest = dt
        return latest

    def last_hunt_at(self) -> datetime | None:
        """When opportunity hunting last ran. Gates the hunt cooldown."""
        latest = None
        for row in self.read():
            if row.get("kind") not in ("hunt", "discovery"):
                continue
            ts = row.get("ts")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if latest is None or dt > latest:
                latest = dt
        return latest

    def unresolved_decision(self, batch: str) -> dict[str, Any] | None:
        """INV-27: a decision for this batch with no terminal entry after it.

        Regression simulation found that without this check a crash between the
        write-ahead journal and the submit produced an orphaned decision record
        and a wasted LLM call on every single retry. The batch-derived
        client_order_id already prevents real duplicate exposure; this prevents
        the bookkeeping mess and the cost.
        """
        decision: dict[str, Any] | None = None
        for e in self.read():
            if e.get("batch") != batch:
                continue
            if e["kind"] == "decision":
                decision = e
            elif e["kind"] in ("execution", "rejected", "no_op"):
                decision = None
        return decision
