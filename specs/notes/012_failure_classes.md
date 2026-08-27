# The failure classes this project actually produces

Written after the same *shape* of bug appeared for the sixth time. Not generic
engineering advice - a taxonomy derived from this repo's own incident record, with the
detection question that would have caught each one.

## Why one taxonomy rather than a longer checklist

Every serious bug here shares a property: **the system kept running and the logs kept
reading healthy.** None crashed. None logged an error. Each was found by accident - by
reading a journal, by a second code path disagreeing, by a convergence test written for
another purpose. That is the thing to attack, and it decomposes into six classes.

| # | Class | Instances | Detection question |
|---|---|---|---|
| A | **Silent no-op** - a path that never runs, or runs and does nothing | `attribution._spot` dead for days; `Sensor.policy` declared and never read; `opening` status never wired; bars six weeks stale | *Can I distinguish "ran and found nothing" from "never ran"?* If not, the null path needs a heartbeat. |
| B | **Absence-as-zero** - a missing value coerced to a benign default that LOOSENS a constraint | `max_loss_usd` unset counted as zero risk against the book caps | *Does this default make the system safer or looser?* A default that loosens must be loud. |
| C | **Unit confusion at an LLM boundary** | bands emitted as percentage moves, not prices; `symbol_or_symbols` vs `symbols` | *Is this value range-checked against something the system computed itself?* An LLM value cannot validate an LLM value. |
| D | **Accumulation not priced** - correct per-event weight, unbounded repetition | 8 interim scores = 0.8 of evidence vs a resolution's 1.0 | *What is the CUMULATIVE bound, not the per-event bound?* |
| E | **Identity collision** - two logical things sharing one key | debounce keyed by rule type, so two stops shared history | *Is the key unique per logical entity, or merely per category?* |
| F | **Order-dependence masquerading as a decision** | simultaneous stop and target resolved by list order | *If two things are true at once, is the winner chosen or accidental?* |

## The three mechanisms

**1. `trdrbot health` - the silent-no-op detector (class A, and B/D by state check).**
Reads the journal and asks of every subsystem: *ran >= threshold and produced nothing?*
`doctor` answers "can this system start"; `health` answers "is it doing anything". It
found a real class-B problem on its very first run (the live position counting as zero
risk). It gates nothing (D-009) - it turns a silent failure into a loud one.

**2. Instrument the null path.** `attribution.run()` had a bare `continue` when the price
lookup failed - no journal entry, so "never ran" and "ran, found nothing" were the same
observation. It now always emits `attribution_run` with `pending`/`attributed`/
`skipped_no_price`. **The rule: any early `continue`/`return` that means "nothing
happened" must leave evidence saying why.** Success paths are instrumented by habit; the
null path is the one that goes wrong quietly.

**3. `tests/test_regressions.py` - one test per bug that actually happened.** 31 tests,
each named by its decision record, all pure and offline. The discipline: **a bug is not
fixed until the test that would have caught it exists.** Verification done in a throwaway
shell snippet - which is what I had been doing all week - protects nothing the next time
someone edits the file.

## What generalises beyond this repo

The one mechanism that has caught the most, without being designed to: **two independent
paths computing the same quantity, with their disagreement surfaced.** The stale-bars bug
died because the decide cycle checked research's numbers against live quotes and said so
out loud. The bootstrap-drift bug died because a convergence test compared two estimators
that should have agreed. Neither was a test written for that bug. Where a second opinion
is cheap, compute it and journal the delta.

## Applying this to a new subsystem

Before merging anything that runs unattended, answer six questions - one per class:
does its null path leave evidence (A); does any default loosen a constraint (B); is every
LLM-supplied number anchored to a computed one (C); is repetition bounded (D); is every
key unique per entity (E); is every tie broken deliberately (F).
