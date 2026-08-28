"""F2/F3 - learning is an item type, not a subsystem (architecture.md §5).

Both a fill and a resolution route through here regardless of which detector
found them (reconciliation's phantom path for an external close, or the
exit-rule evaluator's own trigger) - one place, so credit assignment can't be
duplicated or skipped depending on which path happened to notice first.
"""

from __future__ import annotations

from . import ids
from .calibration import CalibrationStore
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
    # The thesis block IS the decision's subject matter, so it carries full
    # credit weight regardless of what retrieval scored (D-073).
    pos.add_recalled_block("attention", block_id, similarity=1.0)
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
    calibration: CalibrationStore | None = None,
) -> None:
    """F3: a position reached a terminal state, however it got there.

    pnl_pct is None when the resolving detector has no P&L to hand (e.g. an
    external close discovered after the position already vanished from
    holdings) - credit assignment is skipped rather than guessed, same
    philosophy as skipping a non-self-resolved close.
    """
    # Fall back to the position's own last observed P&L when the detecting
    # caller has none (D-058). Reconciliation discovers an external close only
    # AFTER the position has left the broker, so it has no P&L to pass - and
    # that silently skipped both calibration and credit for our only closed
    # trade, leaving a recorded 38% forecast permanently unresolved. The
    # position has carried `last_pnl_pct` since D-056; this is the third place
    # the same measured number failed to reach its consumer, so the fallback
    # goes HERE, where every caller inherits it, rather than in each detector.
    if pnl_pct is None and pos.last_pnl_pct is not None:
        pnl_pct = pos.last_pnl_pct

    self_resolved = pos.close_reason in SELF_RESOLVED
    scored = False

    # Calibration (D-013) resolves on ANY close with a known P&L, including a
    # non-self-resolved one. This is deliberately a wider gate than credit
    # assignment: the forecast was "will this position close profitable", and
    # a stop-triggered loss answers that question honestly even though it says
    # nothing about whether the entry thesis was sound. Suppressing those would
    # bias the calibration record toward trades that went well.
    if calibration is not None and pnl_pct is not None:
        calibration.resolve(pos.position_id, outcome=pnl_pct > 0, at=ids.utc_now().isoformat())

    # Credit gates on a KNOWN P&L, not on the close-reason label (D-057).
    # It used to require close_reason in SELF_RESOLVED, which silently skipped
    # credit assignment for every 'external' close - and both real closes so
    # far have been external, because the agent manages its own exits through
    # the broker (repricing its profit-target limit) rather than through our
    # evaluator. A close with a measured P&L is honest evidence however the
    # position ended; only an UNKNOWN P&L skips, because that would be a guess.
    # Same principle as D-056: measured, not inferred from a label.
    if pnl_pct is not None:
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
