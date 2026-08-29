"""The epistemic constitution (D-041). Seeded into elfmem's SELF frame.

Ten principles, from [notes/010]. Each is traceable to a real incident in this
project or a verified elfmem mechanic - the standing test from notes/009 is
that a principle you cannot trace is a platitude, and platitudes are what make
a constitution decorative.

Scope is narrow on purpose. Anything a deterministic check can enforce stays
in code (luck-neutral attribution, friction, payoff-ratio refusal, book caps -
all already enforced, and all deliberately NOT repeated here). What is left is
the residue nothing else can reach: how to reason, and how to remember.

Change control is inside the constitution itself (block 10): elfmem's
`review_constitutional` PROPOSES amendments and `accept_amendment` applies
them, and the two are deliberately separate calls. Its own ADR 0003 found that
four architectures for automatic constitutional evolution all failed to beat
baseline - so `trdrbot constitution review` shows proposals and never accepts
one. A human ratifies, always.
"""

from __future__ import annotations

from dataclasses import dataclass

TAG = "self/constitutional"


@dataclass(frozen=True)
class Principle:
    key: str
    text: str
    #: WHEN a future decide cycle should surface this - the situation, not a
    #: summary of the conclusion. elfmem's own guidance: the cue is what
    #: rescues a memory whose wording differs from how the question later gets
    #: asked. Block 5 is this rule applied to itself.
    cue: str
    #: The incident or mechanic that minted it. Not decoration: this is the
    #: audit trail for whether the principle earned its slot.
    traces_to: str


PRINCIPLES: tuple[Principle, ...] = (
    # ---- how to reason ------------------------------------------------
    Principle(
        "regimes",
        "A pattern learned in one regime is a hypothesis in another, not a rule. My confidence in it falls when its regime ends - before the P&L does, not after.",
        cue="when a remembered pattern seems to fit the current setup",
        traces_to="D-032 regime page makes 'which regime am I in' checkable at recall time",
    ),
    Principle(
        "recency",
        "Recent direction is evidence about the recent past. A directional view must name a causal driver; the shape of the chart is not one.",
        cue="when forming a directional view or setting a drift on a thesis",
        traces_to="D-032 bootstrap-drift incident - 16pp of pure sample luck projected forward",
    ),
    Principle(
        "premise",
        "When live data contradicts a thesis's premise, the thesis is dead however good the structure looks. I check premises against the tape before acting.",
        cue="when research or a remembered figure disagrees with the live quote",
        traces_to="D-032 stale-bars incident - 'the note assumes NVDA at 224.11; the tape says 209.37'",
    ),
    Principle(
        "assumptions",
        "An input I chose is a judgement, not an observation. Caution compounds - haircuts stack into a verdict nobody chose. I test my answer against the alternative input.",
        cue="when a conclusion rests on a number I selected - a vol window, a haircut, a friction charge",
        traces_to="D-076 - four defensible haircuts and a 21d-vs-5d vol window choice, each right alone, together made a whole regime untradeable: 18 theses simulated, 0 traded",
    ),
    # ---- how to remember ----------------------------------------------
    Principle(
        "earned-confidence",
        "How often I recall something is not evidence it is true. Only scored outcomes move my trust in a memory.",
        cue="when a memory feels familiar or keeps coming up",
        traces_to="elfmem's record_use/outcome split exists because reinforcement once counted retrievals",
    ),
    Principle(
        "cues",
        "I store every fact with the situation I will need it in, phrased as I would ask for it. A memory findable only by its own wording is lost.",
        cue="when writing anything to memory",
        traces_to="verified elfmem mechanic - the cue is the lexical half of hybrid retrieval",
    ),
    Principle(
        "contradictions",
        "When evidence conflicts with something I hold, I keep both and mark the tension. Where my memory disagrees with the world is the most informative place I have.",
        cue="when new evidence conflicts with something I already believe",
        traces_to="elfmem's `contradicts` edge relation, built for exactly this",
    ),
    Principle(
        "precision",
        "Context serves the decision at hand. Unvalidated memories dilute the ones that matter; letting unused patterns decay is how relevance survives.",
        cue="when deciding whether something is worth remembering at all",
        traces_to="elfmem session-aware decay; D-019 #5 context-budget work at the assembly layer",
    ),
    Principle(
        "routing",
        "Events to the journal, evolving patterns to memory, stable reference to the wiki. Knowledge in the wrong store will not be found, or will not adapt.",
        cue="when deciding where a new piece of knowledge belongs",
        traces_to="D-011 three-store split",
    ),
    Principle(
        "fallible-recall",
        "Not finding a memory is not evidence it did not happen. When a judgment rests on absence I check the journal: it is the record, my memory only reconstructs it.",
        cue="when about to conclude something from the absence of a memory",
        traces_to="notes/010 addendum - metacognition about the substrate, not its mechanism",
    ),
    # ---- how to change -------------------------------------------------
    Principle(
        "amendments",
        "I propose amendments to these principles; I never enact them. A change cites the incidents that motivate it and waits for ratification.",
        cue="when these principles seem wrong or incomplete",
        traces_to="elfmem ADR 0003 - automatic constitutional evolution never beat baseline",
    ),
)


#: The SELF frame's hard ceiling (elfmem FrameDefinition.token_budget) and
#: its estimator, len(text)//4. Rendering is GREEDY and BREAKS at the first
#: block that overflows - so principles past the limit are dropped in silence,
#: with no error and no log line. Measured before trimming: 499 tokens of
#: principles against 600, which template overhead would have pushed over,
#: costing us the last two principles invisibly (D-041).
SELF_FRAME_TOKEN_BUDGET = 600
#: elfmem's per-call consolidation ceiling (consolidation.max_inbox_per_run,
#: ADR 0007). Submitting a bigger host_analyses batch does not queue the
#: surplus - it gets LLM-analysed on a later pass instead.
MAX_INBOX_PER_RUN = 5
#: Leave room for the identity block, learned self-knowledge, and the template.
#: Raised from 380 when principles gained their `[name]` prefix (D-049): ~32
#: tokens buys the only stable handle the agent can cite. The guard caught
#: the overrun on the first test run, which is what it is for.
#:
#: **The constitution is now FULL: 427 of 430 with [assumptions] (D-076), and
#: the live SELF frame renders ~578 of its 600.** The next principle requires
#: RETIRING one, not raising this number - the budget is elfmem's and the
#: renderer is greedy, so raising the ceiling past the frame's does not buy
#: room, it buys a silent drop. Measure `mem.self_frame()` before assuming
#: otherwise; the 600 here is a mirror of elfmem's setting, not a constraint we
#: control.
CONSTITUTION_TOKEN_CEILING = 430


def estimate_tokens() -> int:
    """Total budget cost of the constitution, using elfmem's own estimator."""
    return sum(len(block_text(p)) // 4 for p in PRINCIPLES)


def render() -> str:
    """The constitution as text, for humans and for the seeding record."""
    lines = ["# Epistemic constitution", ""]
    for i, p in enumerate(PRINCIPLES, 1):
        lines += [f"{i}. **{p.key}** - {p.text}",
                  f"   _cue:_ {p.cue}",
                  f"   _traces to:_ {p.traces_to}", ""]
    return "\n".join(lines)


def block_text(p: Principle) -> str:
    """The principle as it renders in the SELF frame, name first.

    The frame numbers its blocks and orders them by how load-bearing each has
    proven, so the numbering CHANGES between cycles - and the agent cited
    "principle 10" for what was principle 3, a reference pointing at nothing
    stable. Telling it in the prompt to cite by wording did not work, because
    the rendered list still presented numbers and nothing else. Putting the
    name in the block itself is the structural fix: the only stable handle is
    the one the agent can actually see (D-049).
    """
    return f"[{p.key}] {p.text}"


async def seed(mem, *, verbose: bool = True) -> dict[str, int]:
    """Write the constitution into the SELF frame, verbatim. Idempotent.

    Two non-obvious steps, both found by verifying rather than assuming:

    1. **Seeded blocks sit in an inbox until consolidation runs.** `remember()`
       reported ten successes while `frame("self")` rendered nothing at all -
       stored is not the same as visible, and only a render check catches it.

    2. **Consolidation REWRITES block content by default**, and the rewrite is
       what renders. The LLM turned terse imperatives ("A pattern learned in
       one regime is a hypothesis in another") into third-person description
       ("The agent treats patterns learned in one regime as hypotheses...") -
       faithful, but roughly twice the tokens, which pushed five of the ten
       principles past the SELF frame's 600-token budget where the greedy
       renderer silently dropped them. So we supply our own `host_analyses`:
       the summary IS the rendered text, so the constitution lands in the
       words it was ratified in, at the token cost it was measured at, and
       costs no LLM calls.
    """
    existing = {b.content.strip() for b in await mem.ls(tag=TAG, limit=200)}
    pending: dict[str, Principle] = {}
    skipped = 0
    for p in PRINCIPLES:
        if block_text(p).strip() in existing:
            skipped += 1
            continue
        r = await mem.remember(
            block_text(p),
            tags=[TAG, f"principle/{p.key}"],
            category="knowledge",
            source=f"constitution:{p.key}",
            cue=p.cue,
        )
        pending[r.block_id] = p
        if verbose:
            print(f"  + {p.key}")

    # Consolidate OUR blocks with OUR text as the summary. alignment_score 1.0:
    # a ratified principle is by definition aligned with identity - that is
    # what ratification means.
    # consolidate() processes at most `max_inbox_per_run` blocks per call
    # (default 5, ADR 0007), so ten principles need repeated passes. Progress
    # is measured by what LEAVES the inbox, never by what we submitted: the
    # first version of this loop assumed one call drained the batch and left
    # five principles sitting unconsolidated while reporting all ten seeded -
    # the same "stored is not visible" trap one layer down.
    consolidated = 0
    for _ in range(len(PRINCIPLES) + 2):  # bounded; never spins
        if not pending:
            break
        inbox_ids = {b.id for b in await mem.inbox(max_count=200)}
        # Cap at the per-run limit. Submitting more than consolidate() will
        # process in one call does NOT queue the overflow with our analyses -
        # the surplus is picked up on a later pass and analysed by the LLM
        # instead, which silently reinstates the rewriting this exists to
        # avoid. Found by inspecting tags: LLM-analysed blocks carry inferred
        # `self/value` tags we never supplied.
        eligible = [(bid, pr) for bid, pr in pending.items() if bid in inbox_ids]
        batch = {
            bid: {
                "alignment_score": 1.0,
                "tags": [TAG, f"principle/{pr.key}"],
                "summary": block_text(pr),
            }
            for bid, pr in eligible[:MAX_INBOX_PER_RUN]
        }
        if not batch:
            break
        await mem.begin_session()
        await mem.consolidate(host_analyses=batch)
        await mem.end_session()
        still = {b.id for b in await mem.inbox(max_count=200)}
        done = [bid for bid in batch if bid not in still]
        consolidated += len(done)
        for bid in done:
            pending.pop(bid, None)
    if pending and verbose:
        print(f"  ! {len(pending)} principle(s) did not consolidate: "
              f"{[p.key for p in pending.values()]}")

    if verbose:
        print(f"[constitution] {consolidated} seeded and consolidated, "
              f"{skipped} already present")
    return {"created": consolidated, "skipped": skipped, "total": len(PRINCIPLES)}


async def purge(mem, *, verbose: bool = True) -> int:
    """Forget every constitutional block. For re-seeding after a wording change.

    Amendment is meant to go through ratification (principle 10); this exists
    for the development case where the seed text itself changed and leaving
    both versions in a PERMANENT-decay frame would be worse than a clean
    rewrite.
    """
    n = 0
    for b in await mem.ls(tag=TAG, limit=200):
        await mem.forget(b.id)
        n += 1
    if verbose:
        print(f"[constitution] purged {n} block(s)")
    return n
