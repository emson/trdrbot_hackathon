"""elfmem integration (D-011) - short-term evolving memory.

Verified directly against the installed 0.20.0.dev0 API (not assumed from
docs): `session()` calls `dream()` on exit if `should_dream` is true - which
would violate INV-10/23 (never auto-consolidate inside a tick). So this
adapter replicates `begin_session`/`end_session` manually, skipping the
dream-on-exit, and `dream()` is reachable only through `housekeeping_dream()`,
called from nowhere but the housekeeping path.

Per-frame block capture (INV-22, a bug simulation found in the original
design): `FrameResult.blocks` is read immediately after each `frame()` call.
`last_recall_block_ids` is never used - it only reflects the most recent call,
which silently drops the self/task frames' contribution to credit assignment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elfmem import MemorySystem

from .positions import Position

#: How many learned blocks ATTENTION contributes to a decide cycle.
ATTENTION_KEEP = 5


@dataclass
class ContextResult:
    text: str
    blocks: dict[str, list[str]]  # frame name -> block ids (INV-22)


class ElfmemAdapter:
    def __init__(self, mem: MemorySystem, minds_path: Path | None = None) -> None:
        self.mem = mem
        self._minds_path = minds_path

    @classmethod
    async def build(
        cls, db_path: Path, config: dict[str, Any] | None = None, *, minds_path: Path | None = None
    ) -> "ElfmemAdapter":
        mem = await MemorySystem.from_config(str(db_path), config)
        return cls(mem, minds_path=minds_path or db_path.parent / "minds.json")

    async def close(self) -> None:
        await self.mem.close()

    # -- manual session replication, deliberately without auto-dream (INV-10/23) --

    async def begin(self, task_type: str = "trade_decision") -> None:
        await self.mem.begin_session(task_type=task_type)

    async def end(self) -> None:
        # No dream() here - see module docstring. Only housekeeping_dream() may
        # call it.
        await self.mem.end_session()

    # -- context assembly --

    async def assemble_context(self, query: str) -> ContextResult:
        """self + task + attention frames, captured per-frame (INV-22)."""
        blocks: dict[str, list[str]] = {}
        parts: list[str] = []
        # SELF needs top_k >= the constitution size. elfmem defaults top_k to 5
        # (memory.top_k), so the default call renders FIVE of ten principles and
        # says nothing about the other five - the agent would hold half a
        # constitution and never know (D-041).
        from .constitution import PRINCIPLES
        self_k = len(PRINCIPLES) + 4  # principles + identity + learned self
        seen: set[str] = set()
        for name in ("self", "task"):
            fr = await self.mem.frame(name, None, top_k=self_k if name == "self" else None)
            ids = [b.id for b in fr.blocks if b.id not in seen]
            seen.update(ids)
            blocks[name] = ids
            if fr.text:
                parts.append(fr.text)

        # ATTENTION is built from recall() rather than frame(), because
        # constitutional blocks are semantically close to almost any reasoning
        # query AND carry PERMANENT decay - so once seeded they dominate it.
        # Measured live: 10 of 12 attention hits were principles (0.77-0.96),
        # and after de-duplicating against SELF the frame returned NOTHING.
        # The agent's own learned market knowledge had been entirely displaced
        # by its own identity. Over-fetch, drop anything already in SELF/TASK,
        # keep what was actually learned.
        want = ATTENTION_KEEP
        candidates = await self.mem.recall(query, frame="attention", top_k=want + self_k)
        kept = [b for b in candidates if b.id not in seen][:want]
        blocks["attention"] = [b.id for b in kept]
        if kept:
            parts.append(
                "## Relevant memory\n\n"
                + "\n".join(f"- {b.content.strip()}" for b in kept)
            )
        return ContextResult(text="\n\n".join(parts), blocks=blocks)

    # -- fill-event learning (F2) --

    async def remember_thesis(self, pos: Position) -> str:
        """Cue is hand-written, not derived - a missing cue means the block is
        findable only by its own wording later (verified against elfmem's own
        retrieval design: the cue forms the BM25 half of hybrid retrieval)."""
        cue = f"when reasoning about {pos.underlying} {pos.strategy} setups"
        r = await self.mem.remember(
            pos.thesis or f"{pos.strategy} on {pos.underlying}",
            tags=[pos.underlying.lower(), pos.strategy],
            category="knowledge",
            source=pos.position_id,
            cue=cue,
        )
        return r.block_id

    async def _mind_for(self, underlying: str) -> str:
        """One mind per underlying (resolves notes/006 gap #12's open mapping
        question).

        Reuse is tracked in OUR OWN local mapping file, not elfmem's built-in
        duplicate detection. Verified live that `mind_create`'s dedup is
        unreliable in realistic sequences: two consecutive calls with an
        identical subject correctly dedupe in isolation (status
        "duplicate_rejected", same block_id) - but the SAME two calls after
        other memory operations (a remember(), an earlier predict()) each
        return status "created" with a DIFFERENT block_id, silently minting
        duplicate minds. `mind_list()` doesn't help either: a freshly created
        mind sits in elfmem's inbox and is invisible to mind_list() until a
        dream() consolidation runs, which under our design (D-018 #6/INV-23)
        only happens at housekeeping - so a list-first check would report
        "not found" on every call within a tick and mint a new mind every
        time regardless. A small local JSON file is simpler and fully within
        our control.
        """
        minds: dict[str, str] = {}
        if self._minds_path and self._minds_path.exists():
            minds = json.loads(self._minds_path.read_text())

        if underlying in minds:
            return minds[underlying]

        subject = f"{underlying} options trading"
        r = await self.mem.mind_create(subject, goals=[f"trade {underlying} options profitably"])
        minds[underlying] = r.block_id
        if self._minds_path:
            self._minds_path.parent.mkdir(parents=True, exist_ok=True)
            self._minds_path.write_text(json.dumps(minds, indent=2))
        return r.block_id

    async def predict(self, pos: Position) -> str:
        """Returns the decision_block_id to store on the position - the bridge
        to mind_outcome() at resolution."""
        mind_id = await self._mind_for(pos.underlying)
        r = await self.mem.mind_predict(
            mind_id, pos.thesis or f"{pos.strategy} resolves favourably",
            verify_at=pos.expiry or pos.opened,
        )
        return r.decision_block_id

    # -- resolution learning (F3) - the actual credit-assignment step --

    async def resolve(self, pos: Position, *, hit: bool, signal: float, weight: float = 1.0) -> None:
        """Score both systems: the mind prediction, and the recalled blocks
        that informed the decision. This is what makes elfmem learn instead of
        merely accumulate (D-011's design goal)."""
        if pos.mind_decision_block_id:
            await self.mem.mind_outcome(
                pos.mind_decision_block_id, hit=hit, reason=pos.close_reason or "resolved"
            )
        block_ids = pos.all_elfmem_block_ids
        if block_ids:
            await self.mem.outcome(block_ids, signal, weight=weight, source=pos.position_id)

    # -- housekeeping only (INV-10/23: dream() lives here and nowhere else) --

    async def housekeeping_dream(self) -> bool:
        """Consolidate the inbox into recallable memory. Returns True on success.

        dream() calls the configured embedding provider (elfmem ships only an
        OpenAI adapter for embeddings + a mock - no Anthropic option exists,
        since Anthropic has no embeddings API). This is advisory infrastructure
        like every other memory/forecast input (INV-8): a failure here degrades
        (frame()/recall() keep returning whatever was already consolidated)
        rather than crashing housekeeping's other work (portfolio regen,
        interim scoring). Confirmed live: remember()/mind_predict()/outcome()
        are all pure-DB and unaffected even when dream() cannot complete.
        """
        if not self.mem.should_dream:
            return True
        try:
            await self.mem.dream()
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[elfmem] dream() failed, consolidation skipped this cycle: {exc!r}")
            return False
