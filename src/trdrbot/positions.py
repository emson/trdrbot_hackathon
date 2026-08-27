"""Position pages - the narrative store and the status machine (D-014).

`wiki/positions/<position_id>.md` is frontmatter (machine spine) plus prose
(what the model reads). Alpaca knows what we hold; this knows why.

Status is also the exactly-once guard (INV-17). Three different detectors can
observe the same resolution - the reconciler, the collector, and the exit-rule
evaluator - and only the first may act on it.

Frontmatter follows OKF conventions (D-022): `type` is the only field OKF
requires; `sources`/`generated`/`verified` are its provenance/trust fields.
Position pages deliberately do NOT go through wiki.py's Concept/augmentation-
guard machinery (D-023) - that guard targets open-ended LLM rewrites of
knowledge prose (lessons.md, strategy.md); position pages are a structured,
mostly code-driven write pattern (status transitions, exit-rule debounce
state) with their own typed shape, and forcing them through a generic
heading-diff guard would be the wrong tool for a different problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import ids

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
    # OKF provenance/trust fields (D-022)
    sources: list[dict[str, Any]] = field(default_factory=list)
    generated_by: str = ""
    verified: list[dict[str, Any]] = field(default_factory=list)
    # elfmem bridge (D-011): captured PER FRAME at decide time (INV-22 fix -
    # never rely on last_recall_block_ids, which reflects only the last call)
    elfmem_blocks: dict[str, list[str]] = field(default_factory=dict)
    mind_decision_block_id: str | None = None
    # Thesis carried from simulate_experiments, so resolution can attribute
    # the outcome to the view or the structure (experiments.attribute).
    thesis_claim: str = ""
    thesis_horizon: str = ""
    thesis_band_low: float | None = None
    thesis_band_high: float | None = None
    thesis_drift: float = 0.0
    attribution: str = ""          # set once the horizon has passed
    #: Highest materiality band already interim-scored (INV-24). Monotonic:
    #: caps how much cumulative evidence one unresolved position can
    #: contribute, and stops a mark flapping across a threshold re-firing.
    interim_band: int = 0
    path: Path | None = None

    @property
    def symbols(self) -> list[str]:
        return [leg["symbol"] for leg in self.legs if leg.get("symbol")]

    @property
    def all_elfmem_block_ids(self) -> list[str]:
        return [b for blocks in self.elfmem_blocks.values() for b in blocks]

    def trust_tier(self) -> str:
        """OKF trust tiers (D-022): unverified / machine-confirmed / human-reviewed."""
        if not self.verified:
            return "unverified"
        if any(str(v.get("by", "")).startswith("human:") for v in self.verified):
            return "human-reviewed"
        return "machine-confirmed"

    def mark_verified(self, by: str) -> None:
        self.verified.append({"by": by, "at": ids.utc_now().isoformat()})

    def frontmatter(self) -> dict[str, Any]:
        return {
            "type": "Position",  # OKF-required field (D-022)
            "position_id": self.position_id,
            "status": self.status,
            "interim_band": self.interim_band,
            "strategy": self.strategy,
            "underlying": self.underlying,
            "opened": self.opened,
            "expiry": self.expiry,
            "legs": self.legs,
            "exit_rules": self.exit_rules,
            "exit_state": self.exit_state,
            "close_reason": self.close_reason,
            "decision_ref": self.decision_ref,
            "sources": self.sources,
            "generated": {"by": self.generated_by, "at": ids.utc_now().isoformat()},
            "verified": self.verified,
            "elfmem_blocks": self.elfmem_blocks,
            "mind_decision_block_id": self.mind_decision_block_id,
            "thesis_claim": self.thesis_claim,
            "thesis_horizon": self.thesis_horizon,
            "thesis_band_low": self.thesis_band_low,
            "thesis_band_high": self.thesis_band_high,
            "thesis_drift": self.thesis_drift,
            "attribution": self.attribution,
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
        generated = d.get("generated") or {}
        return Position(
            position_id=d["position_id"],
            status=d.get("status", "proposed"),
            interim_band=int(d.get("interim_band", 0) or 0),
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
            sources=d.get("sources") or [],
            generated_by=generated.get("by", ""),
            verified=d.get("verified") or [],
            elfmem_blocks=d.get("elfmem_blocks") or {},
            mind_decision_block_id=d.get("mind_decision_block_id"),
            thesis_claim=d.get("thesis_claim", ""),
            thesis_horizon=d.get("thesis_horizon", ""),
            thesis_band_low=d.get("thesis_band_low"),
            thesis_band_high=d.get("thesis_band_high"),
            thesis_drift=float(d.get("thesis_drift") or 0.0),
            attribution=d.get("attribution", ""),
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
