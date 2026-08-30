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

from . import ids, store

TERMINAL = {"closed", "expired", "assigned", "abandoned"}
ACTIVE = {"proposed", "opening", "open", "adjusting", "closing"}

#: Floor on credit weight. Two independent reasons, both measured (D-073):
#:
#: 1. elfmem REJECTS `weight <= 0.0` outright (`_validate_weight` raises
#:    ValueError), and `similarity` is MIN-MAX NORMALISED within each result
#:    set - so the worst-matching block of every single recall carries exactly
#:    0.0. Passing similarity through raw would crash attribution on its first
#:    weighted credit, in the path that has never yet run.
#: 2. A block that matched least still sat in the context that produced the
#:    decision. It earns less credit, not none - a floor says "contributed
#:    little", zero would claim "was not there", and only one of those is true.
#:
#: The best-matching block therefore carries 4x the worst. That ratio is the
#: mechanism; the exact number is not load-bearing.
CREDIT_WEIGHT_FLOOR = 0.25


def credit_weight(similarity: float | None) -> float:
    """Retrieval similarity -> credit weight in [FLOOR, 1.0].

    `None` means no similarity was recorded (a pre-v2 position), which credits
    at 1.0 - the behaviour those positions were written under.
    """
    if similarity is None:
        return 1.0
    try:
        s = min(1.0, max(0.0, float(similarity)))
    except (TypeError, ValueError):
        return 1.0  # an unreadable weight must not silently zero a block's credit
    return CREDIT_WEIGHT_FLOOR + (1.0 - CREDIT_WEIGHT_FLOOR) * s


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
    # never rely on last_recall_block_ids, which reflects only the last call).
    #
    # Two shapes, both valid (D-073). Since v2 a frame maps id -> retrieval
    # similarity, so credit can be weighted by how well each block actually
    # matched the decision's query. Positions written before that carry a
    # plain list, which reads as "no weights recorded" and credits at 1.0 -
    # the old behaviour exactly. Nothing rewrites old files. Every accessor
    # below iterates the frame, and iterating a dict yields its keys, so the
    # id-only readers are shape-agnostic for free.
    elfmem_blocks: dict[str, list[str] | dict[str, float]] = field(default_factory=dict)
    mind_decision_block_id: str | None = None
    # Thesis carried from simulate_experiments, so resolution can attribute
    # the outcome to the view or the structure (experiments.attribute).
    thesis_claim: str = ""
    thesis_horizon: str = ""
    thesis_band_low: float | None = None
    thesis_band_high: float | None = None
    thesis_drift: float = 0.0
    #: The vol half of the decision measure this position was sized under
    #: (a FRACTION, None = priced at the market's own IV). Recorded for the
    #: same reason as thesis_drift: resolution can ask whether the VIEW was
    #: right, and for a vol trade the view is this number (WU-4.5).
    thesis_vol_view: float | None = None
    attribution: str = ""          # set once the horizon has passed
    #: Highest materiality band already interim-scored (INV-24). Monotonic:
    #: caps how much cumulative evidence one unresolved position can
    #: contribute, and stops a mark flapping across a threshold re-firing.
    interim_band: int = 0
    #: Defined worst case in dollars at entry (from simulate_experiments).
    #: Feeds the portfolio-level at-risk cap (D-036). None on legacy
    #: positions - counted as zero risk by the cap, leniently.
    max_loss_usd: float | None = None
    #: **A FRACTION despite the `_pct` suffix** (-0.30 = -30%). The name is a
    #: WIRE FORMAT - it is the frontmatter key every position page on disk
    #: already carries - so D-092's rename of the `_pct`-means-two-things
    #: collision deliberately stopped at the persistence boundary. The
    #: producer is `analytics.position_pnl_fraction`, whose name does say so.
    #:
    #: Last observed P&L fraction while the position was visible at the
    #: broker. When a position closes OUTSIDE our exit rules - the agent
    #: repricing its own limit, an assignment, an expiry - the broker no
    #: longer has it and its final P&L cannot be fetched. This is the last
    #: honest observation, and it is what attribution scores (D-056).
    last_pnl_pct: float | None = None
    #: Net position greeks computed at entry (D-040) - the risk SHAPE the
    #: agent chose, quotable at entry and re-priceable on later ticks.
    greeks_at_entry: dict | None = None
    entry_iv: float | None = None
    entry_spot: float | None = None
    path: Path | None = None

    @property
    def symbols(self) -> list[str]:
        return [leg["symbol"] for leg in self.legs if leg.get("symbol")]

    #: Frames whose blocks are CREDITED at resolution. Deliberately excludes
    #: "self": constitutional principles are identity, not a bet on this trade.
    #: Crediting them would let a losing week silently degrade the constitution
    #: - and since principles carry PERMANENT decay they would never recover.
    #: Principles are scored by incident review with human ratification
    #: (D-033/D-041), never automatically by P&L.
    CREDITED_FRAMES = ("task", "attention")

    @property
    def all_elfmem_block_ids(self) -> list[str]:
        """Blocks that informed this decision AND may be credited by its outcome."""
        return [
            b
            for frame, blocks in self.elfmem_blocks.items()
            if frame in self.CREDITED_FRAMES
            for b in blocks
        ]

    def recalled_block_ids(self) -> list[str]:
        """Every block that informed the decision, including identity. For
        provenance and audit - never for credit assignment."""
        return [b for blocks in self.elfmem_blocks.values() for b in blocks]

    def credit_weights(self) -> dict[str, float]:
        """Creditable block id -> credit weight, derived from retrieval similarity.

        The weight answers "how much did this block have to do with THIS
        decision", which is a different question from the signal's "what
        happened" - collapsing them was the flaw (D-073). Measured live: the
        SPY mind model came back at similarity 0.0 on BOTH a SPY and an NVDA
        query while being credited at full weight, so uniform credit was
        paying full price for a block that matched nothing.

        A pre-v2 position stores a plain list and gets 1.0 throughout, which
        is exactly what it received before, so old positions attribute
        identically rather than being silently re-weighted by a rule that did
        not exist when they were written.
        """
        out: dict[str, float] = {}
        for frame, blocks in self.elfmem_blocks.items():
            if frame not in self.CREDITED_FRAMES:
                continue
            for bid in blocks:
                sim = blocks.get(bid) if isinstance(blocks, dict) else None
                out[bid] = credit_weight(sim)
        return out

    def add_recalled_block(self, frame: str, block_id: str, similarity: float = 1.0) -> None:
        """Record a block against a frame, preserving whichever shape is in use."""
        blocks = self.elfmem_blocks.setdefault(frame, {})
        if isinstance(blocks, dict):
            blocks[block_id] = similarity
        elif block_id not in blocks:
            blocks.append(block_id)

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
            "max_loss_usd": self.max_loss_usd,
            "last_pnl_pct": self.last_pnl_pct,
            "greeks_at_entry": self.greeks_at_entry,
            "entry_iv": self.entry_iv,
            "entry_spot": self.entry_spot,
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
        store.write_atomic(p, body)
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
        text = path.read_text(encoding="utf-8")
        _, fm, body = text.split("---", 2)
        d = yaml.safe_load(fm) or {}
        thesis = body.split("## Thesis", 1)[-1].strip() if "## Thesis" in body else ""
        generated = d.get("generated") or {}
        return Position(
            position_id=d["position_id"],
            status=d.get("status", "proposed"),
            interim_band=int(d.get("interim_band", 0) or 0),
            max_loss_usd=(float(d["max_loss_usd"]) if d.get("max_loss_usd") is not None else None),
            last_pnl_pct=(float(d["last_pnl_pct"]) if d.get("last_pnl_pct") is not None else None),
            greeks_at_entry=d.get("greeks_at_entry") or None,
            entry_iv=(float(d["entry_iv"]) if d.get("entry_iv") is not None else None),
            entry_spot=(float(d["entry_spot"]) if d.get("entry_spot") is not None else None),
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
