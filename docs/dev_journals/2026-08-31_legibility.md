# Dev Journal - 2026-08-31: legibility

The day split cleanly in two, and only in hindsight do the two halves look like the same
question asked at different altitudes. The morning asked "where could this lose an unexpected
amount" and answered it in code. The afternoon asked "could anyone who has never seen this
system understand why it just did that" and answered it in prose, tokens, and a mascot. Both are
the same problem: something is true about the system, and nothing outside it can see that yet.

---

## The stress test found the thing it was looking for

A stress simulation - brainstorm scenarios, run them step by step, rank by severity - is supposed
to surface a plausible catastrophe, not a certain one. This one surfaced both at once: a calendar
exit rule fires on every tick regardless of the clock, so it can submit a close at 00:15 on expiry
day, into a shut market, with no verified belief about what the broker does with that. If it
fails, `store.transition` had already moved the position to `closing` - a status the exit engine
fetched every tick and then skipped forever, on `status != "open"`. No retry. No stop. Nothing
watching it again. On the book that was actually open at the time, that chain ends in an
auto-exercised long put and roughly $1M of short SPY landing the morning of a payrolls print,
against a recorded max loss of $2,171.

That is not a hypothetical bug in an abstract system. It was the bug in the position sitting in
`data/wiki/positions/` while I was reading about it.

Three designs got weighed for the fix, and the reasoning behind rejecting two of them is worth
keeping. Two parallel loops (a dedicated retry loop plus the existing evaluate loop) was the
obvious shape and got rejected for duplicating the close-and-finalize logic twice - exactly the
kind of drift this pass existed to remove. Deleting `closing` as a real status, so a failed close
just stays `open` and re-fires naturally next tick, looked even simpler - and lost on a property I
almost missed: `closing` is the only durable signal on disk that a close is in flight, which the
whole-book-close guard's count depends on, and it discards `close_reason`, the thing that lets a
retry finish the *original* decision instead of re-deriving a possibly different one. The design
that shipped - one loop, branching on status, sharing one close-attempt tail - turned out strictly
smaller than the two-loop version and had a bonus property neither alternative had: broker-truth
leg filtering now applies on the *first* attempt too, not only retries, so a leg reconcile already
found missing this same tick is never blindly resubmitted.

Six work units followed the same shape - a position's risk repriced from the actual fill instead
of the model's word, a recorded quantity that diverged from what sizing computed surfaced rather
than gated, an orphan adopted into the managed set instead of just logged, the bootstrap
correction threaded to the one call site that still ran raw. Every one of them is the same
sentence with the nouns changed: *something the system believed had diverged from what was true,
and nothing looked again.* That is I-55's shape, from two days ago, at six more seams. Naming it
once made the six fixes read as one phase instead of six unrelated patches.

## A second pass found what the first pass's own logic couldn't see

Two existing scaffolds already prove things about this system: the structure zoo proves the stack
is unbiased at zero edge, the trader gauntlet proves it survives regimes and streaks. Both ask "is
this layer right." A third scaffold asked a different question, on purpose: every layer here is
individually correct - does it *compose*? Disharmony doesn't show up in a unit test, because every
unit passes; it's two correct behaviours that cancel, or a rule that satisfies the check built to
confirm it without doing the job the check exists for.

It found that shape on the live position. The 766/758 spread's `underlying_stop above 776` reads
as protection - it satisfies `health`'s "has an underlying stop" check - and cannot actually limit
a loss, because a vertical's payoff is flat past its far strike: by the time 776 prints, the whole
max loss is already taken. The stop can confirm a loss, never prevent one. Fixed the same way
`_unreachable_rules` already catches a mark rule that can never fire - this is its sibling, one
step out, catching a rule that fires reliably and too late.

Three more findings got measured and explicitly *not* fixed, and writing why matters as much as
the fix above did. The live mark stop triggers inside the position's own path noise (a stop at
-65% fires on 44% of the position's whole-life expected move) - not fixed, because the honest
answer is changing what the agent is asked for (stops in units of expected move), not adding a
check on what it already wrote. The corroboration guard against a wide single quote is nearly open
one day after entry on a low-IV name - not fixed, because `CORROBORATION_FRACTION` was declared
tunable from its own journal counters on the day it shipped, and tuning it from a morning's
observation would be exactly the taste it was written to avoid. Size stepping from zero straight
to the full exploration allocation with no room in between - not fixed, because it's the seed
floor working precisely as designed. Three defensible reasons not to touch three real findings,
each recorded in the issue ledger so none of them get rediscovered as news.

**The honest gap:** the one fix from this pass - the dead stop - shipped without its own I-number.
It's in the commit, it's tested, it's real, and the issue ledger doesn't say so. Exactly the kind
of thing this project's own testing principles say a health probe exists to catch and a changelog
doesn't - noted here because the journal is where it belongs until the ledger gets it.

## A process was running yesterday's code

Asked whether the system was actually working, tick by tick - and it was, cleanly, every five
minutes, for over a day. It was also running the code from before any of the morning's fixes
existed. Python doesn't reload a running process's source files; a long-lived loop is a photograph
of whatever was on disk when it started, not a window onto what's on disk now. The bug the morning
had just closed was still fully live in the process actually holding the position.

The restart itself needed one more piece of care: the working tree the live process reads from is
the same directory git operates on, and a literal `git checkout` of an older branch would swap the
files on disk out from under a process mid-tick before a merge brought them back. Moved the branch
pointer directly instead (`git branch -f`) and only checked out once the target was already
identical to HEAD - a merge with zero working-tree disruption, verified by watching the process
tick straight through both branch switches without a hiccup.

## Every trade gets a story now

`record_position` already computes the matched simulated structure and still has every rejected
one in scope, right at the line where it saves the position - so capturing that context cost one
append to a list, not a second pass over anything. `write_entry`/`write_outcome` write one
markdown file per position, appended to (not duplicated) when the position resolves, whichever
detector gets there first. Both are synchronous, both swallow their own exceptions - publishing a
trade's story must never be able to take the tick down with it.

Backfilled the three positions that predate the mechanism from the exact real journal rows the
live version would have used - and one more honest gap, stated in the commit rather than
papered over: the rejected-alternatives table is empty on all three, because that data lived only
in that decide cycle's in-memory `SharedContext` and nothing ever persisted it. Every trade from
here forward has it; those three don't, and pretending otherwise would be worse than the gap.

## Making the invisible legible to someone who has never seen it

The afternoon's question was different in kind, not just subject. Two documents already existed -
a glossary for a novice reader, a decision-transparency report quoting the system's own reasoning
verbatim - and both worked. Then a real logo arrived: a hand-drawn, monochrome elf mascot on warm
cream, a rounded wordmark, nothing like the cool serif "ledger" voice those two documents already
used. The instinct to pick one and discard the other was wrong. The mark carries no color of its
own, so the accent already in use needed no reconciling at all; the two visual languages became
two named registers - brand, for anywhere Theo is being introduced, and ledger, for anywhere it's
being audited - and the design-system page performs the switch between them rather than just
describing it, because a style guide that only asserts its own rules is asking to be ignored.

The pitch deck that followed is the same design principle under real content constraints: fourteen
slides, real numbers throughout, and the deliberate choice to give the stress-test story its own
slide rather than folding it into a feature list. A hackathon deck that claims "risk management"
is a sentence every team can write. "We simulated our own system failing, found a real bug in the
safety net protecting a live position, and shipped the fix the same day, verified by reverting it
first and watching the new tests fail" is not a sentence every team can write, and it's true.

## The count

525 tests (+35 across the day), every fix revert-verified before its issue was struck - I-56
through I-63 closed by name, I-64/65/66 recorded and deliberately left open, one fix shipped
without its own ledger entry (noted above). All three scaffolds (zoo, gauntlet, harmony) clean.
`trdrbot health` showing the same pre-existing warnings and nothing new. Three branches
(`phase7-divergence-gaps` → `walking-skeleton` → `main`) fast-forwarded to the same commit with
zero working-tree disruption to the live process throughout. Three published artifacts - Theo's
Ledger, the Theo Design System, and the fourteen-slide deck - plus `docs/design_system.md` and
`docs/design_system.html` saved for direct use. One real position, still open, still doing exactly
what its thesis said it would.
