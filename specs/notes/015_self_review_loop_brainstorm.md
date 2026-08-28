# A Scheduled/Triggered Self-Review Loop for Theo — Brainstorm

Requested 2026-08-28: "a scheduled or triggered reinforcement LLM loop that... internally
review[s] how it's operating and its own prompts and its own performance and tries to minimise
the gap between its goals and its current state," asked explicitly to be creative and to draw on
the muse's collision mechanism for "alternative ideas." **Status: brainstormed and evaluated, not
built.** Companion to [notes/009](009_epistemic_constitution_plan.md) and
[notes/010](010_constitutional_blocks_brainstorm.md), which already did this exercise for the
constitution specifically; this note is broader — behaviour and prompts, not only principles.

## The prior art this has to be honest about

**Today's own D-076 is a working demo of exactly what's being asked for, done by hand.** A
human read the live journal with an adversarial "would I trade this?" lens, found that 18 theses
had produced zero trades while all five price forecasts were holding — a miscalibration invisible
to any per-decision check because every individual refusal was locally defensible. The fix
touched code (`breakeven_vol`/`dominant_risk`), memory (amended two lessons, added two), and the
constitution (`[assumptions]`). **That whole cycle — read the aggregate, diagnose the gap, propose
fixes across three different stores — is the loop the user is asking to automate.** So the
question isn't "should this exist," it visibly already worked once. The question is what's safe
and useful to run without a human doing the reading.

**And the loop this most resembles has already been tried, inside the dependency this system is
built on, and failed.** `constitution.py`'s own docstring: elfmem's ADR 0003 found that four
architectures for *automatic* constitutional evolution all failed to beat baseline. That's why
`trdrbot constitution review` (already wired, `cli.py`) calls `review_constitutional` and only
ever shows proposals — nothing auto-applies. Any new design here inherits that constraint at full
force: **whatever this loop produces, a human ratifies.** The interesting design space is
entirely in what gets reviewed, how it's triggered, and how "here's a gap" turns into something
concrete enough to ratify — not in whether the loop gets to act on its own.

**Two more constraints this project already discovered the hard way:**
- **D-045: P&L cannot judge two versions of anything within this window.** A genuinely 60%-edge
  agent beats a coin flip only 69% of the time over 20 trades. A self-review loop that judges
  itself by "did returns improve" is measuring noise. What CAN be measured, per D-045, is
  behaviour — it accrues every cycle, not every trade.
  - **D-074/D-082/D-086: a check that never fires reads as healthy.** This loop is itself a new
  subsystem with exactly the silent-no-op risk the whole day's throughline was about. Whatever
  gets built needs its OWN heartbeat from day one — "reviewed N times, found M gaps" — not
  bolted on after it goes quiet for a week unnoticed, which is precisely how three of today's
  four bugs got as old as they did.
- **The constitution is full.** 427 of 430 tokens (D-076). A loop that proposes new constitutional
  principles is proposing into a queue that requires retiring one to add one. That's not a flaw
  to design around — it's a good forcing function, and any design here should make retirement
  proposals a normal output, not an edge case.

## What already exists that this must NOT duplicate

| Mechanism | What it already does | Gap it leaves |
|---|---|---|
| `health.py` | Deterministic: is each subsystem running and producing? | Never asks whether the OUTPUT is good, only whether it exists |
| `housekeeping.run()` (interim scoring, wiki sweep, `dream()`) | Scheduled maintenance, already the place elfmem consolidation is allowed to run | Maintains state; doesn't diagnose the agent's own behaviour |
| Credit assignment (D-072, D-073) | Incidents → principle/lesson credit, similarity-weighted | Operates on EXISTING blocks; can't notice a missing principle or a bad prompt |
| `constitution review` (elfmem `review_constitutional`) | Drift proposals for EXISTING constitutional blocks, human-ratified | Constitution-only; needs ~20 reinforced blocks + 30-day age (rarely satisfiable inside an 8-day hackathon — confirmed today, `insufficient_history` is the live answer) |
| The muse | Forced collision of unrelated wiki concepts + news → falsifiable trading theses, deterministic gauntlet | Only ever produces TRADING theses, never a claim about the SYSTEM itself |

The gap all five leave in common: **nothing reads the aggregate of the agent's own recent
behaviour against its own stated goals and says so in words.** That is specifically a judgement
task — comparing a measured pattern against `charter.md`'s intent isn't a threshold check — which
is the one thing on this list only an LLM call can do, and the one thing none of the five do.

## Candidate mechanisms, evaluated

**A — Continuous per-cycle self-test.** Every decide cycle states which principle its current
thesis is most at risk of violating (notes/009's original proposal). Cheapest: zero new LLM
calls, reuses the existing decide call. **Rejected as the sole mechanism**: each cycle only sees
itself. D-076's finding was invisible from any single cycle — every individual refusal was
locally fine — and only became visible by reading eighteen of them together. A per-cycle test
structurally cannot catch an aggregate pattern. Kept as a cheap COMPLEMENT (see chosen design).

**B — Full autonomy: let it change its own prompts/config directly.** Rejected outright, not
weighed against alternatives — ADR 0003 already answered this for the narrower case
(constitutional blocks alone) and came back negative even there. Extending unsupervised
self-modification to prompts and config is a strictly larger blast radius for a mechanism already
shown not to beat baseline in the smaller one.

**C — Pure collision, no structured review** ("meta-muse"): skip any deterministic gap-detection
step, just run periodic random pairings of unrelated behavioural signals (a lesson that's never
been cited + a metric that's been flat for N cycles) and ask if there's a hidden causal story.
**Rejected as the sole mechanism.** D-076's central finding — 18 theses, 0 trades — didn't need a
clever collision, it needed someone to count. A pure-serendipity mechanism would very plausibly
never stumble onto "count your own abstentions." Kept as a supplementary generator (below),
because it's genuinely good at the class of gap a straight metrics-diff would never think to
compute.

**D — Scheduled-only, no threshold trigger.** Simple, and it's what `housekeeping.dream()`
already does for consolidation. **Rejected as the sole trigger**: a fixed weekly cadence would
have let the 18-and-0 pattern run for a full week before the next scheduled look, burning the
system's entire trading window on a gate it wasn't going to loosen on its own. Kept as a backstop
(below), not the primary trigger.

**E (chosen) — Deterministic gap-detection gates a periodic, adversarially-framed diagnostic LLM
pass; every output is a typed, human-ratified proposal.** Detailed below.

## The chosen design

**1. Compute the gap, don't ask the model to notice it.** This project's own repeated principle
(`research.py`'s docstring, cited again in D-081: *numbers are computed, never asked of the LLM*)
applies here exactly as it does to trading. A small set of metrics ALREADY exist individually in
this codebase and just need diffing against an explicit target, not invented:

  - consecutive declined theses without a trade (the exact D-076 number — a threshold around 8
    would have caught it ten theses before a human did)
  - any `health` FAIL persisting across more than one review window
  - `n_eff` / concentration stalling above `CONCENTRATION_WARN` (already defined, D-081) across
    several calibration checks in a row
  - cache-hit share dropping in `trdrbot usage` (a regression on the exact lever D-074 measured)
  - the primary model's fallback rate rising (visible in `usage.jsonl`'s served-model field)
  - a constitutional principle with zero citations across N cycles (a real retirement candidate —
    directly enables the "retire one to add one" rule the full budget now requires)

  None of this needs an LLM call. It's the same shape as `health.py`, just aimed at PATTERN
  rather than PRESENCE.

**2. Trigger on threshold crossing, backstopped by a schedule.** Any one metric crossing its
threshold fires an immediate review (same discipline as the idle ladder's "do not hunt when you
cannot shoot" — don't burn a review call when nothing has moved). A fixed backstop cadence (e.g.
weekly, or however housekeeping's own maintenance cadence is tuned) catches slow drift that never
crosses a hard line — the D-quality of drift that's real but diffuse, which is exactly the kind a
threshold is bad at catching and a human reading the aggregate is good at.

**3. The diagnostic pass is deliberately adversarial, not neutral.** The single best piece of
evidence for this shape, gathered TODAY: the manual critique that found D-076 was explicitly
framed as "would a professional trader take this position," not "please review recent decisions."
A neutral review prompt invites the same harmonizing failure mode constitutional block 6 already
guards against in memory — smoothing over a tension instead of naming it. The reviewer role's
system prompt should ask it to find the sharpest defensible criticism of the last N cycles, the
same framing that worked once already today.

**4. A muse-style wildcard pass runs alongside it, not instead of it.** Sample two unrelated
behavioural signals at random (an unused lesson + a flat metric; two principles that fired in the
same cycle; a muse-rejected thesis + a resolved forecast) and ask whether a causal story connects
them. Most pairings will be noise, exactly like most muse candidates get rejected — that's fine,
it's the same trial-and-gate shape this project already trusts for trading ideas, and it should
be held to the same discipline: register every attempt so a later reviewer can see the trial
count, not just the survivors (D-052's multiple-testing correction, reapplied one layer up).

**5. Output is typed and routed to the store that already owns that type — never a new store.**
Mirroring notes/010's own routing answer (`[routing]`: events → journal, evolving patterns →
elfmem, stable reference → wiki), a self-review finding is none of those three — it's an
engineering proposal about the system itself, and this project already has a store for exactly
that: `specs/issues.md`, in the same `I-N` format used all day today, git-tracked and human-read.
A constitutional-amendment-shaped proposal goes through the mechanism that already exists for it
(`propose_amendment` / `trdrbot constitution review`) rather than inventing a second path. Nothing
writes to the wiki or to elfmem directly — those stores are about the MARKET, not about the agent's
own engineering, and blurring that would repeat exactly the mistake D-078 spent today fixing
(a store holding content of the wrong nature for what reads it).

**6. The loop gets its own heartbeat from cycle one.** `reviewed N times, M gaps surfaced, K
proposals ratified, K' rejected` — a record independent of whether it found anything, precisely
because "found nothing this week" and "never actually ran this week" must never look the same.
This is not optional polish; it's the single most repeated lesson of the day this note is
attached to (see the diary's throughline section), and building the heartbeat in from the start
is cheaper than discovering its absence three separate times the way `exit_rules` and
`interim_scoring` did.

## Would it have caught today's finding? A quick trace

Replaying D-076 against the design above: metric #1 (consecutive declines without a trade) would
have crossed a threshold of ~8 well before the actual count of 18 — call it roughly the midpoint
of the hackathon's trading window rather than three days from the deadline. The adversarial
diagnostic pass, given the journal slice up to that point plus `charter.md`'s stated goal, is
exactly the kind of read a "would a pro take this" framing is built for — this is not
speculative, it's the same prompt shape that produced D-076 by hand. The wildcard pass adds
something the targeted metric wouldn't: colliding "abstention count rising" with "which lessons
fired most often in the declined cycles" is a plausible route to noticing *which* haircut is doing
most of the work (the 21-day vol anchor, in the event) rather than just that abstention is high —
a level of diagnosis the threshold alone doesn't reach.

## What this deliberately does not attempt

- **No autonomous action.** Every output is a proposal in a human-read file or a
  `propose_amendment` call. ADR 0003 is the reason, stated plainly, not hedged.
- **No new memory store.** Proposals route to `specs/issues.md` or the existing amendment API;
  nothing new for elfmem or the wiki to hold.
- **No judging by P&L.** The gap metrics are behavioural (D-045's own finding about what's
  actually measurable in this window), never a trade-outcome comparison.
- **No unbounded constitutional growth.** A proposal to ADD a principle should come paired with a
  candidate to retire, given the budget is already full — this is a real constraint discovered
  today, not a nicety.

## Cost and next step

Cheap to prototype: the deterministic metrics mostly already exist as values computed elsewhere
in the codebase (an aggregation module, not new instrumentation); the diagnostic and wildcard
passes are two more LLM roles in the existing `llm.roles` chain, at whatever tier `research`/
`muse` already run at; the output path (`specs/issues.md` entries, `propose_amendment` calls) is
plumbing this project already has. **Not built** — this is the agenda for the next session that
wants it, the same status notes/009 carried for a day before its companion note was written.
