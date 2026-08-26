"""F2/F3 - learning is an item type, not a subsystem (architecture.md §5).

Both a fill and a resolution route through here regardless of which detector
found them (reconciliation's phantom path for an external close, or the
exit-rule evaluator's own trigger) - one place, so credit assignment can't be
duplicated or skipped depending on which path happened to notice first.
"""

from __future__ import annotations

from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import Position, PositionStore
from .wiki import Wiki

# D-018 #9: only these close reasons mean the position resolved on its own
# terms. A panic/external exit does not tell us whether the ENTRY thesis was
# right - scoring it as a resolved trade would poison credit assignment by
# blaming a good thesis for an exit it didn't choose.
SELF_RESOLVED = {"thesis_resolved", "stop_triggered", "target_hit", "time_stop", "deadline"}


async def on_fill(pos: Position, store: PositionStore, mem: ElfmemAdapter, journal: Journal) -> None:
    """F2: a position's order is confirmed filled. Remember the thesis, make
    it a falsifiable prediction, and mark the page machine-confirmed (D-022) -
    reconciliation independently verified this, which is a real trust
    upgrade over the original unverified write."""
    block_id = await mem.remember_thesis(pos)
    pos.elfmem_blocks.setdefault("attention", []).append(block_id)
    pos.mind_decision_block_id = await mem.predict(pos)
    pos.mark_verified(by="trdrbot/reconcile")
    store.save(pos)
    journal.append("fill", position_id=pos.position_id, elfmem_block=block_id,
                    mind_decision_block=pos.mind_decision_block_id)


async def on_resolution(
    pos: Position,
    store: PositionStore,
    mem: ElfmemAdapter,
    wiki: Wiki,
    journal: Journal,
    *,
    pnl_pct: float | None,
) -> None:
    """F3: a position reached a terminal state, however it got there.

    pnl_pct is None when the resolving detector has no P&L to hand (e.g. an
    external close discovered after the position already vanished from
    holdings) - credit assignment is skipped rather than guessed, same
    philosophy as skipping a non-self-resolved close.
    """
    self_resolved = pos.close_reason in SELF_RESOLVED
    scored = False

    if self_resolved and pnl_pct is not None:
        hit = pnl_pct > 0
        # elfmem's own idiom for this signal shape (verified against its
        # mind_outcome usage during the earlier exploration): 0.9/0.1, not a
        # bare 0/1 - a resolved position is still evidence under uncertainty,
        # not a certainty.
        signal = 0.9 if hit else 0.1
        await mem.resolve(pos, hit=hit, signal=signal, weight=1.0)
        scored = True
    else:
        hit = None

    lesson = _write_lesson(wiki, pos, pnl_pct=pnl_pct, scored=scored)

    journal.append(
        "reflection",
        position_id=pos.position_id,
        close_reason=pos.close_reason,
        pnl_pct=pnl_pct,
        self_resolved=self_resolved,
        credit_assigned=scored,
        hit=hit,
    )
    store.save(pos)  # persist any state the resolve step touched


def _write_lesson(wiki: Wiki, pos: Position, *, pnl_pct: float | None, scored: bool) -> str:
    """Append to the single evolving lessons.md concept (D-022/D-023).

    One growing body, one heading per resolved position - the augmentation
    guard (D-023) is naturally satisfied here since a new heading is always
    an addition, never a replacement of what came before.
    """
    existing = wiki.read("lessons") or _new_lessons_concept()
    heading = f"## {pos.position_id}"
    if heading in existing.body:
        return existing.concept_id  # already recorded, do not duplicate

    pnl_text = f"{pnl_pct:+.1%}" if pnl_pct is not None else "unknown (not self-resolved)"
    credit_text = "scored" if scored else "not scored (D-018 #9: not self-resolved, or P&L unavailable)"
    entry = (
        f"\n\n{heading}\n"
        f"{pos.underlying} {pos.strategy}, closed `{pos.close_reason}`, P&L {pnl_text}. "
        f"Credit assignment: {credit_text}.\n\n"
        f"> {pos.thesis[:300] if pos.thesis else '(no thesis recorded)'}\n"
    )
    existing.body = existing.body.rstrip("\n") + entry + "\n"
    existing.add_source(f"positions/{pos.position_id}.md", author="trdrbot/learn")
    wiki.write_concept(existing, type_="Lesson")
    wiki.append_log(f"lesson recorded for {pos.position_id} ({pos.close_reason})")
    return existing.concept_id


def _new_lessons_concept():
    from .wiki import Concept

    return Concept(concept_id="lessons", frontmatter={"type": "Lesson"}, body="# Lessons\n")
