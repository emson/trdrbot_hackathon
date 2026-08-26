"""Position pages - the narrative store and the status machine (D-014).

`wiki/positions/<position_id>.md` is frontmatter (machine spine) plus prose
(what the model reads). Alpaca knows what we hold; this knows why.

Status is also the exactly-once guard (INV-17). Three different detectors can
observe the same resolution - the reconciler, the collector, and the exit-rule
evaluator - and only the first may act on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TERMINAL = {"closed", "expired", "assigned", "abandoned"}
ACTIVE = {"proposed", "opening", "open", "adjusting", "closing"}


@dataclass
class Position:
    position_id: str
    status: str = "proposed"
    strategy: str = ""
    underlying: str = ""
    opened: str = ""
    expiry: str = ""
    legs: list[dict[str, Any]] = field(default_factory=list)
    exit_rules: list[dict[str, Any]] = field(default_factory=list)
    exit_state: dict[str, list[bool]] = field(default_factory=dict)
    close_reason: str | None = None
    thesis: str = ""
    decision_ref: str = ""
    provenance: str = "agent"
    path: Path | None = None

    @property
    def symbols(self) -> list[str]:
        return [leg["symbol"] for leg in self.legs if leg.get("symbol")]

    def frontmatter(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "status": self.status,
            "strategy": self.strategy,
            "underlying": self.underlying,
            "opened": self.opened,
            "expiry": self.expiry,
            "legs": self.legs,
            "exit_rules": self.exit_rules,
            "exit_state": self.exit_state,
            "close_reason": self.close_reason,
            "decision_ref": self.decision_ref,
            "provenance": self.provenance,
        }


class PositionStore:
    def __init__(self, wiki_dir: Path) -> None:
        self.dir = wiki_dir / "positions"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, position_id: str) -> Path:
        return self.dir / f"{position_id}.md"

    def save(self, pos: Position) -> Path:
        p = self._path(pos.position_id)
        body = (
            f"---\n{yaml.safe_dump(pos.frontmatter(), sort_keys=False)}---\n\n"
            f"## Thesis\n\n{pos.thesis or '(none recorded)'}\n"
        )
        p.write_text(body)
        pos.path = p
        return p

    def load(self, position_id: str) -> Position | None:
        p = self._path(position_id)
        if not p.exists():
            return None
        return self._parse(p)

    def all(self) -> list[Position]:
        out = []
        for p in sorted(self.dir.glob("*.md")):
            try:
                out.append(self._parse(p))
            except Exception as exc:  # noqa: BLE001 - a bad page must not stop a tick
                print(f"[positions] skipping unreadable {p.name}: {exc!r}")
        return out

    def open_positions(self) -> list[Position]:
        return [p for p in self.all() if p.status in ACTIVE]

    def _parse(self, path: Path) -> Position:
        text = path.read_text()
        _, fm, body = text.split("---", 2)
        d = yaml.safe_load(fm) or {}
        thesis = body.split("## Thesis", 1)[-1].strip() if "## Thesis" in body else ""
        return Position(
            position_id=d["position_id"],
            status=d.get("status", "proposed"),
            strategy=d.get("strategy", ""),
            underlying=d.get("underlying", ""),
            opened=d.get("opened", ""),
            expiry=d.get("expiry", ""),
            legs=d.get("legs") or [],
            exit_rules=d.get("exit_rules") or [],
            exit_state=d.get("exit_state") or {},
            close_reason=d.get("close_reason"),
            thesis=thesis,
            decision_ref=d.get("decision_ref", ""),
            provenance=d.get("provenance", "agent"),
            path=path,
        )

    def transition(self, pos: Position, new_status: str, close_reason: str | None = None) -> bool:
        """Move a position's status. Returns False if the move is not allowed.

        INV-17: a position may enter a terminal state at most once. Whichever
        detector gets there first wins; the others are refused, which is what
        stops the same resolution being scored twice.
        """
        if pos.status in TERMINAL:
            return False
        pos.status = new_status
        if close_reason:
            pos.close_reason = close_reason
        self.save(pos)
        return True
