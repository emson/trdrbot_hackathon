"""Bootstrap lessons into elfmem (D-054).

The normal way a lesson arrives is `learn.py`: a position resolves, the
outcome is attributed, and the blocks that informed it move. This module is
the exception - things we MEASURED but the loop has not yet lived through, so
there is no outcome to learn them from.

Routing, per the constitution's own `[routing]` principle:

    journal   what happened, dated - the record
    wiki      stable reference - the technique concepts (D-053)
    elfmem    evolving patterns whose confidence should move with outcomes  <- here
    SELF      identity: how to reason and remember - the constitution

So a lesson here is deliberately NOT a principle and NOT a technique. It is a
specific, falsifiable claim about how THIS book behaves, carrying the numbers
that produced it, and it decays like any other memory if it stops being
validated. That is the point: `[earned-confidence]` says only scored outcomes
move trust, and these enter unproven.

Every lesson carries a **cue** - the situation in which a future decide cycle
should surface it, phrased as the agent would ask for it. `[cues]` applied to
itself: a lesson findable only by its own wording is already lost.
"""

from __future__ import annotations

from dataclasses import dataclass

TAG = "lesson"

#: elfmem consolidates at most this many blocks per call (ADR 0007); a bigger
#: host_analyses batch is not queued, the surplus gets LLM-analysed instead.
MAX_INBOX_PER_RUN = 5


@dataclass(frozen=True)
class Lesson:
    key: str
    text: str
    cue: str
    tags: tuple[str, ...] = ()


LESSONS: tuple[Lesson, ...] = (
    Lesson(
        "correlated-names-are-one-bet",
        "A second position only diversifies if the underlyings are actually "
        "uncorrelated, and ours mostly are not. Measured over 120 sessions: "
        "SPY/QQQ correlate at 0.92, SPY/NVDA at 0.66, and my original research "
        "universe averaged 0.75 pairwise - three names, one factor. The "
        "per-underlying risk cap cannot see this because it counts NAMES, not "
        "exposures: three 'diversified' tech positions pass every check and "
        "lose together. Before adding a position, ask whether it offsets the "
        "book's existing delta and vega or grows them. XLE runs -0.42 against "
        "SPY, XLP -0.04, XLV +0.16 - those genuinely diversify.",
        cue="when considering a second position while already holding one",
        tags=("risk", "correlation", "sizing"),
    ),
    Lesson(
        "friction-is-the-size-of-the-edge",
        "At my tenor, transaction cost is routinely the same order as the "
        "whole edge, and it is worst on exactly the structures that look most "
        "attractive. Measured: a candidate's expected value fell from +$25 to "
        "+$9 once real round-trip friction was charged - a 65% haircut. Four "
        "legs of a condor cross four spreads. Price the exit at a STRESSED "
        "spread too, because losing exits happen when markets are widest. "
        "I have declined roughly ten cycles on this basis and been right to.",
        cue="when a structure's premium or expected value looks attractive",
        tags=("costs", "edge"),
    ),
    Lesson(
        "research-notes-go-stale-by-design",
        "My research desk runs while the market is CLOSED, so every note I "
        "read was written against yesterday's tape. It has been wrong about "
        "spot three times that I caught: NVDA quoted 224.11 in the note versus "
        "209.37 live, MRNA 142.57 versus 145.48, and SMCI below the band floor "
        "its own thesis required. The note is a hypothesis about the market, "
        "not a description of it. Re-check spot and IV against the live quote "
        "before acting on any desk figure, and treat a mismatch as the thesis "
        "being dead rather than as a rounding difference.",
        cue="when a research note's price or volatility differs from the live quote",
        tags=("research", "data-quality"),
    ),
    Lesson(
        "post-event-iv-is-already-gone",
        "The premium worth selling around an event has usually gone by the "
        "time I look. Measured repeatedly: after NVDA's print, implied had "
        "crushed to roughly its own realised level; MRVL's ATM straddle priced "
        "a 12.5% implied move into earnings, above my own 9-10% skip rule. "
        "Selling premium after the catalyst is selling fair value and paying "
        "spread for the privilege. The tradeable question is whether implied "
        "sits above my realised-vol FORECAST, not whether it looks high.",
        cue="when considering selling premium after an earnings or macro print",
        tags=("volatility", "events"),
    ),
    Lesson(
        "exploration-budget-is-not-a-mandate",
        "My exploration allocation exists to buy resolved theses at roughly "
        "neutral expected value, so that a calibration record can form at all. "
        "It is NOT permission to pay negative EV. Buying a structure I have "
        "already priced as losing, in order to generate a data point, is not "
        "calibration - it is a donation with a story attached. If nothing "
        "prices positively, the correct output is a recorded FORECAST on the "
        "setup I declined, which scores my judgement at zero cost.",
        cue="when tempted to trade because the risk budget is sitting unused",
        tags=("sizing", "discipline"),
    ),
    Lesson(
        "a-38-percent-trade-can-be-the-right-trade",
        "Win rate is not the decision; payoff times probability is. I opened "
        "an NVDA call spread at an honest 38% probability because the payoff "
        "was 3.8:1 - a losing-more-often-than-not trade with positive "
        "expectancy. The trap runs the other way: a credit spread collecting "
        "$51 to risk $449 needs about 90% accuracy merely to break even, and "
        "it looks safe precisely because it usually wins. Record the honest "
        "probability, not the comfortable one.",
        cue="when judging a structure by how often it wins",
        tags=("expectancy", "calibration"),
    ),
)


def block_text(lesson: Lesson) -> str:
    """Name-first, so the agent can cite a lesson stably (same reason as D-049)."""
    return f"[{lesson.key}] {lesson.text}"


async def seed(mem, *, verbose: bool = True) -> dict[str, int]:
    """Write any missing lessons. Idempotent by content.

    Deliberately ordinary knowledge blocks - NOT tagged `self/constitutional`.
    These must be allowed to decay and to be moved by outcomes; pinning them as
    identity would make a measured claim permanent, which is exactly what
    `[regimes]` warns against.
    """
    existing = {b.content.strip() for b in await mem.ls(tag=TAG, limit=200)}
    pending: dict[str, Lesson] = {}
    skipped = 0
    for lesson in LESSONS:
        if block_text(lesson).strip() in existing:
            skipped += 1
            continue
        r = await mem.remember(
            block_text(lesson),
            tags=[TAG, *lesson.tags],
            category="knowledge",
            source=f"lesson:{lesson.key}",
            cue=lesson.cue,
        )
        pending[r.block_id] = lesson
        if verbose:
            print(f"  + {lesson.key}")

    # Seeded blocks sit in an inbox until consolidation, and an unconsolidated
    # block is NOT retrievable - measured here, 0 of 6 recallable by their own
    # cue immediately after a successful seed. Supply our own analyses so the
    # wording (and the [key] prefix that makes a lesson citable) survives, and
    # cap the batch at the per-run limit or the surplus gets LLM-rewritten on a
    # later pass. Both lessons learned the hard way seeding the constitution
    # (D-041); reusing them rather than rediscovering them.
    consolidated = 0
    for _ in range(len(LESSONS) + 2):
        if not pending:
            break
        inbox_ids = {b.id for b in await mem.inbox(max_count=200)}
        eligible = [(bid, l) for bid, l in pending.items() if bid in inbox_ids]
        batch = {
            bid: {"alignment_score": 0.75,
                  "tags": [TAG, *l.tags],
                  "summary": block_text(l)}
            for bid, l in eligible[:MAX_INBOX_PER_RUN]
        }
        if not batch:
            break
        await mem.begin_session()
        await mem.consolidate(host_analyses=batch)
        await mem.end_session()
        still = {b.id for b in await mem.inbox(max_count=200)}
        for bid in [b for b in batch if b not in still]:
            pending.pop(bid, None)
            consolidated += 1

    if verbose:
        print(f"[lessons] {consolidated} seeded and consolidated, "
              f"{skipped} already present")
        if pending:
            print(f"  ! {len(pending)} did not consolidate: "
                  f"{[l.key for l in pending.values()]}")
    return {"created": consolidated, "skipped": skipped, "total": len(LESSONS)}
