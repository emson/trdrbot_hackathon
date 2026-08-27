"""Append-only JSONL journal - ground truth and rebuild path (D-014).

Write-ahead is mandatory (INV-18): the decision is journalled BEFORE the order
is submitted. INV-27 is the other half - on retry, the processor must read that
record and resume rather than re-decide, or write-ahead buys nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from . import ids


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
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry["id"]

    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def last_decision_at(self):
        """When the agent last actually reasoned. None if never.

        Used by the market pulse (D-042) to notice it has gone quiet while
        holding risk - the failure mode is silence that looks like calm.
        """
        from datetime import datetime
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
