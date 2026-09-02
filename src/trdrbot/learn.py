"""F2/F3 - learning is an item type, not a subsystem (architecture.md §5).

Both a fill and a resolution route through here regardless of which detector
found them (reconciliation's phantom path for an external close, or the
exit-rule evaluator's own trigger) - one place, so credit assignment can't be
duplicated or skipped depending on which path happened to notice first.
"""

from __future__ import annotations

from typing import Any

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


async def guarded(coro: Any, journal: Journal, *, stage: str, position_id: str) -> bool:
    """Run a learning step advisorily. Returns False if it failed.

    Learning is advisory infrastructure and INV-8 says the decide path never
    blocks on advisory input - but the two calls below sit on the FAST path,
    inside `reconcile`, which runs BEFORE the exit-rule evaluator every tick.
    Awaited bare, any failure in here (a corrupt minds.json, a locked SQLite
    file, a full disk) propagated out of the tick and that tick's stop-losses
    were never evaluated. A persistent one disarmed capital protection
    indefinitely, and `health` could not see it: its probes compare rows that
    EXIST, so a subsystem that stops emitting entirely moves no counter.

    Every advisory subsystem around this one already degrades - sensors,
    analytics, hunt, muse, research, the coach. This was the exception, and it
    was the one place the exception cost the most.

    Journalled as well as printed: a print in an unattended run is a message
    to nobody, and `learn_error` is what makes the degradation visible to
    `trdrbot health` and `trdrbot report` (D-038).
    """
    try:
        # The stage's OWN verdict, when it has one (D-107). `on_resolution`
        # returns False when it guarded a memory failure internally and kept
        # going, so a degraded run is still COUNTED in `learn_run.errors` -
        # the number `health` reads. Swallowing the raise and returning a
        # constant True here would have been D-038's absence-as-success.
        ok = await coro
        return ok is not False
    except Exception as exc:  # noqa: BLE001 - the advisory boundary itself
        print(f"[learn] {stage} failed for {position_id}: {exc!r}")
        journal.append("learn_error", stage=stage, position_id=position_id,
                       error=repr(exc)[:300])
        return False


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
    pnl_fraction: float | None,
    calibration: CalibrationStore | None = None,
) -> bool:
    """F3: a position reached a terminal state, however it got there.

    pnl_fraction is None when the resolving detector has no P&L to hand (e.g. an
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
    if pnl_fraction is None and pos.last_pnl_pct is not None:
        pnl_fraction = pos.last_pnl_pct

    self_resolved = pos.close_reason in SELF_RESOLVED
    scored = False

    # Calibration (D-013) resolves on ANY close with a known P&L, including a
    # non-self-resolved one. This is deliberately a wider gate than credit
    # assignment: the forecast was "will this position close profitable", and
    # a stop-triggered loss answers that question honestly even though it says
    # nothing about whether the entry thesis was sound. Suppressing those would
    # bias the calibration record toward trades that went well.
    if calibration is not None and pnl_fraction is not None:
        calibration.resolve(pos.position_id, outcome=pnl_fraction > 0, at=ids.utc_now().isoformat())

    # The MIND's prediction resolves here, and only the mind's. It is a binary
    # claim about this position - right or wrong once - and a measured P&L is
    # the honest answer to it, on any close however it happened (D-057: gating
    # this on the close-reason label silently skipped every 'external' close,
    # which is how both real closes so far have ended).
    #
    # BLOCK CREDIT DOES NOT HAPPEN HERE, and that is the point of D-091.
    # This used to apply a money-derived 0.9/0.1 signal at full weight to the
    # very blocks `attribution.run` judges later, from the verdict, at the
    # thesis horizon. So every closed position was credited TWICE, and the
    # first credit followed the P&L - which means a lucky win took +0.9 here
    # and then "learn nothing" there, installing exactly the superstition the
    # design exists to prevent (see experiments.ATTRIBUTION_SIGNAL, whose
    # docstring assumes this function is not doing what it was doing).
    #
    # Deferring costs nothing real: attribution is where the view is actually
    # tested, and a position that closes before its horizon has not yet
    # produced the evidence that would justify moving a memory.
    degraded = False
    if pnl_fraction is not None:
        hit = pnl_fraction > 0
        # GUARDED (D-107). elfmem raises BlockNotActiveError when the decision
        # block has been archived as `superseded` by consolidation - which
        # happens whenever `on_fill` wrote the thesis text twice, so 2 of 4
        # live decision blocks were archived. Unguarded, one raise here skipped
        # the lesson, the reflection row and the store save for good: the
        # position was already terminal, and INV-17 refuses a second terminal
        # transition, so there is no retry. One closed position lost all three.
        # A memory that cannot take the outcome is a degraded memory, not a
        # reason to lose the lesson.
        try:
            await mem.record_mind_outcome(pos, hit=hit)
            scored = True
        except Exception as exc:  # noqa: BLE001 - memory never blocks the lesson
            journal.append("learn_error", stage="record_mind_outcome",
                           position_id=pos.position_id, error=repr(exc)[:200],
                           consequence="mind outcome not recorded; lesson and "
                                       "reflection still written")
            scored = False
            degraded = True
    else:
        hit = None

    _write_lesson(wiki, pos, pnl_fraction=pnl_fraction, scored=scored)

    journal.append(
        "reflection",
        position_id=pos.position_id,
        close_reason=pos.close_reason,
        pnl_pct=pnl_fraction,
        self_resolved=self_resolved,
        credit_assigned=scored,
        #: Block credit is attribution's job now (D-091). Recorded so the
        #: journal distinguishes "credited at close" (pre-D-091 rows) from
        #: "waiting for the horizon", which is otherwise invisible.
        credit_deferred=True,
        mind_resolved=hit is not None,
        hit=hit,
    )
    store.save(pos)  # persist any state the resolve step touched
    return not degraded


def _write_lesson(wiki: Wiki, pos: Position, *, pnl_fraction: float | None, scored: bool) -> str:
    """Append to the single evolving lessons.md concept (D-022/D-023).

    One growing body, one heading per resolved position - the augmentation
    guard (D-023) is naturally satisfied here since a new heading is always
    an addition, never a replacement of what came before.
    """
    existing = wiki.read("lessons") or _new_lessons_concept()
    heading = f"## {pos.position_id}"
    if heading in existing.body:
        return existing.concept_id  # already recorded, do not duplicate

    pnl_text = f"{pnl_fraction:+.1%}" if pnl_fraction is not None else "unknown (not self-resolved)"
    credit_text = (
        "prediction resolved; block credit deferred to attribution at the thesis "
        "horizon (D-091 - crediting on P&L here would let a lucky win reinforce a "
        "wrong view before the view was ever tested)"
        if scored else
        "nothing scored - no measured P&L, so both the prediction and the credit "
        "would be a guess"
    )
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


#: How many resolved positions the decide prompt is shown. Enough to see a
#: PATTERN (three losers in a row is a pattern; one is weather), few enough
#: that the block stays a paragraph rather than a second document. The page
#: itself keeps everything - this is the reading window, not the record.
LESSONS_IN_PROMPT = 5


def recent_lessons(wiki: Wiki, k: int = LESSONS_IN_PROMPT) -> str:
    """The last `k` resolved-position lessons, rendered for the decide prompt.

    `_write_lesson` has appended to `lessons.md` on every resolution since
    D-022, and until now NOTHING read it back: the loop wrote down what
    happened and then decided the next trade without it. The agent's only view
    of its own trading history was the open book and an aggregate calibration
    number - so "you have closed four positions and never self-resolved two of
    them" was on disk, in prose, and unreadable at the one moment it bears on
    anything.

    Reader and writer live in the same module deliberately. The section format
    is `## <position_id>` and that is an internal detail of the two functions
    either side of this comment; the moment it is parsed from somewhere else it
    becomes a wire format nobody declared.
    """
    concept = wiki.read("lessons")
    if concept is None or not concept.body.strip():
        return ""
    # Sections, not lines: one lesson is a heading plus its prose plus the
    # quoted thesis, and splitting on anything finer would hand the agent half
    # an entry. `[1:]` drops the "# Lessons" preamble, which is a title.
    sections = [s.strip() for s in concept.body.split("\n## ")[1:] if s.strip()]
    if not sections:
        return ""
    return "\n\n".join(f"## {s}" for s in sections[-k:])


def _new_lessons_concept():
    from .wiki import Concept

    return Concept(concept_id="lessons", frontmatter={"type": "Lesson"}, body="# Lessons\n")
