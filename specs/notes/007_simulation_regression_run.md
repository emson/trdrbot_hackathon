# Simulation — Regression Run Against the Hardened Design (2026-08-26)

Iteration 2 of the stress simulation. Iteration 1 ([notes/006](006_simulation_stress_run.md))
found 14 gaps, 3 critical; D-017/D-018 hardened the design in response. This run re-traces the
same 6 scenarios as a frozen regression set, verifies each fix rather than assuming it, and adds
5 new adversarial scenarios against components that didn't exist in iteration 1 (C24 exit-rule
evaluator, split tick timing, write-ahead journal, dead-letter, interim scoring).

**Headline: none of the three CRITICAL fixes fully holds.** Each is structurally sound but has a
concrete residual gap. One new HIGH-severity bug was introduced by adding C24 without
re-examining existing ordering — with a one-line fix that also closes two other findings for free.

---

## World model (delta from iteration 1)

New state: `positions[id].close_reason`, `positions[id].exit_rules`, `positions[id].consecutive_breach_count`,
`journal[].kind ∈ {decision, execution, exit, interim_outcome, ...}`, `lock{pid, ts}`,
`item.retry_count`. New components: C24 (Exit Rule Evaluator). New rule: fast path
(C21 analytics → C24 exit rules → C13 reconcile) runs every tick; slow path (C8→C11 decide) runs
every N ticks, per architecture.md F1 as currently written.

---

## Regression scenario run (frozen set, verdicts)

### 1. Learning loop closure — **PARTIALLY HOLDS**

Traced: agent opens a position with a `time_stop: {days_before_expiry: 2}` rule but a
conventional 30–45 DTE expiry (nothing enforces the "≤7 DTE" constraint — it is strategy
guidance, not code, and D-009 forbids anything that would enforce it). `time_stop` fires 2 days
before **that position's own expiry**, not 2 days before the competition deadline. Day 43 is
outside the 8-day window. **The fix only works if the DTE guidance is followed, and nothing
guarantees that** — this is the same "constitution says, nothing enforces" pattern iteration 1
found in the false-viral scenario, now reappearing in the resolution-timing fix meant to close
that exact gap.

Separately: **INV-6 and INV-24 now directly conflict as worded.** INV-6 says elfmem blocks
receive `outcome()` "exactly once, at resolution." INV-24 requires interim scoring at every
housekeeping before resolution — which calls `outcome()` repeatedly. Both can't be literally true
at once; the invariant set needs INV-6 reworded to scope "exactly once" to the full-weight
terminal call, with interim low-weight calls explicitly exempted.

Also flagged, not resolved by reasoning: repeated **daily** interim scoring reinforces/penalises
the *same* thesis blocks against a signal (unrealised P&L) that can swing sign day to day for an
options position. Whether this stabilises or destabilises elfmem's Beta posterior before true
resolution is an empirical question, not one this simulation can answer by reasoning alone — flag
for the grounding lever (a small computational check) before relying on it.

**Mitigation:** add a **competition-deadline sweep**, independent of any position's own DTE — a
fixed calendar date, force-closing everything still open. This is not a guardrail (it blocks
nothing about *which* trades happen; it only enforces a fact about when the competition ends,
the same category as the market-hours check). Also reword INV-6.

### 2. Cold-start context at 20 positions, FOMC flood — **PARTIALLY HOLDS**

The two-tier split (needs-attention full detail / everyone else one-line) works for the general
case. But one of the three promotion criteria is **regime-flagged**, and a market-wide regime
shift — exactly what FOMC day produces — can plausibly touch every open position at once. Traced:
if all 20 positions are regime-flagged simultaneously, the needs-attention tier absorbs the whole
portfolio and the two-tier split collapses back into the original problem, on precisely the day
it exists to solve.

**Mitigation:** cap the needs-attention tier (e.g. top-K by urgency), and represent a systemic
regime shift as **one portfolio-level context item** ("regime shifted, affects N positions") in
place of promoting every affected position individually.

### 3. FM-1 crash window — **PARTIALLY HOLDS**

Traced the crash at three points, not just the one iteration 1 covered:

- **Before write-ahead completes:** safe — nothing was submitted, retry is a clean re-decide.
- **After write-ahead, before submit:** the journal now has an orphaned decision with no
  execution. On retry, nothing was specified to check for this before re-deciding — the pipeline
  re-invokes the LLM, which may decide differently, and journals a **second** decision for the
  same batch, orphaning the first.
- **After submit, before execution journalled:** same gap. A retry re-decides rather than
  resuming. Reassuring finding: because `client_order_id` is derived from the **batch**, not the
  decision, *any* resubmission attempt from that batch — regardless of what the LLM redecides —
  carries the identical id and Alpaca rejects it as a duplicate. **This structurally prevents real
  duplicate market exposure**, which was iteration 1's actual fear. What it does *not* prevent is
  a wasted LLM call and an orphaned/confusing journal record.

Net: **downgrade this from CRITICAL to MEDIUM** — the financial-integrity risk (double exposure)
is closed by the batch-derived id; what remains is a bookkeeping and cost problem, not a
duplicate-order problem.

**Mitigation:** before deciding, check the journal for an existing decision on this batch with no
matching terminal entry; if found, resume (re-attempt the same submission, which is safely
idempotent) rather than re-deciding. Write-ahead logging only delivers its promise if the
recovery path actually reads it.

### 4. False-viral social item, no guardrails — **HOLDS** (with a refinement opportunity)

`close_reason` correctly separates the social source's penalty (still scored, still correctly
penalised) from the entry thesis (no longer wrongly penalised for a panic exit). Traced as
designed: this is the one regression scenario that holds cleanly.

Refinement, not a regression: on a non-`thesis_resolved` close, the design currently skips entry
credit entirely rather than crediting a thesis that was genuinely on track before a forced exit.
Safe (doesn't teach the wrong lesson) but leaves a correct lesson uncaptured. The interim-scoring
machinery built for gap #1 could supply exactly this signal — worth reusing rather than treating
as a separate mechanism.

### 5. Multi-leg divergence escalation — **PARTIALLY HOLDS**

Shares scenario 2's root cause exactly: if the needs-attention tier bloats under systemic
regime-flagging, a divergence-flagged position's priority is diluted among other promoted
positions on the same high-stakes day. One fix (scenario 2's tier cap + portfolio-level regime
item) resolves both.

### 6. Expiry/assignment, three detectors — **DOES NOT HOLD AS SPECIFIED**

This is the most important finding of the run. The fast-path ordering in architecture.md F1 is
**C21 (analytics) → C24 (exit rules) → C13 (reconcile)**. Traced: on the tick an assignment
posts at the broker, C24 runs *before* C13 has diffed broker state against our records — so C24
evaluates exit rules against a position whose leg composition Alpaca has already changed, using
stale local assumptions. Best case, C24's close attempt is rejected by Alpaca as invalid; worst
case, it computes a nonsensical mark for a spread now missing a leg. Either way, C24 acts (or
tries to) on data that reconciliation — running one step later — would have corrected first.

**Mitigation: reorder to C21 → C13 → C24.** Reconciliation runs first and flips any
externally-resolved position to a terminal status; C24's loop is scoped to positions still
`open`, so an already-resolved position is excluded *by construction*. One-line fix.

---

## New adversarial scenarios (targeting components iteration 1 never exercised)

| # | Scenario | Verdict | Severity |
|---|---|---|---|
| 7 | C24 vs. decide path, same tick | Holds by design intent, contingent on an unstated implementation requirement | LOW-MEDIUM — needs an explicit rule |
| 8 | Watchdog kills a hung tick at 3 points | Same root cause as regression #3 in all three cases | (folds into #3, not separately ranked) |
| 9 | Dead-letter discards a transiently-failed valid item | Position-facts (fills, assignments) have a redundant recovery path; source items (news, social) do not | MEDIUM |
| 10 | Exit-rule debounce vs. a flapping/stale quote | Protects against false positives; a single reassuring-but-wrong quote resets the counter and can delay a genuine breach, worse on thin ≤7 DTE contracts | MEDIUM-HIGH |
| 11 | Exit-rule stop and assignment race in the same tick | Resolved for free by scenario 6's reordering fix; residual real-world timing risk accepted | LOW (post-fix) |

**#7 detail:** the architecture note ("a position it has moved to closing is already marked when
C9 assembles context") is only true if C9 reads position state fresh each invocation rather than
from a tick-start snapshot. Add this as an explicit implementation requirement and an explicit
rule that closing/terminal positions are informational-only in the decide context, never a
target for action.

**#8 detail:** all three watchdog crash points (after write-ahead/before submit, after
submit/before execution-journal, mid-archive) trace to the identical missing mitigation as
regression #3 — a resume-from-journal check on reprocessing. Not a new bug; the same bug appearing
via a different trigger. Archiving also needs to be idempotent (moving an already-moved file is a
no-op, not an error) to support the mid-archive case cleanly.

**#9 detail:** C13's reconciliation runs every tick independent of any specific inbox item
surviving, so a dead-lettered *fill* or *assignment* item is not truly lost — reconciliation
rediscovers the underlying fact on a later tick regardless. A dead-lettered *news* or *social*
item has no such redundancy; that context is genuinely and permanently gone. Refine
dead-lettering to distinguish malformed-data failures (dead-letter fast) from
dependency-outage failures (retry longer, with backoff) before finalising N.

**#10 detail:** "2 consecutive checks" resets to zero on any single non-breaching read. In a
genuinely volatile move this costs at most ~60–120s, acceptable. But a stale or artificially wide
quote — the exact failure mode already flagged as a §12 assumption risk for thin ≤7 DTE
contracts — can produce a false "looks fine" reading that resets the counter and delays a real
breach past what's safe. Consider N-of-M debounce instead of strictly consecutive, plus a
magnitude override: a breach more than 2× threshold triggers immediately regardless of debounce
history, since that's not plausibly a quote artifact.

**#11 detail:** once scenario 6's reordering fix lands, this scenario resolves as a side effect —
C13 already excludes externally-resolved positions from C24's candidate set before C24 runs. One
fix closes two findings. The only residual risk is the broker posting an assignment *between*
C13's check and C24's action within the same tick — genuinely outside our control, and self-heals
within one further tick via order rejection + reconciliation.

---

## Regression / journey table

| # | Iteration-1 gap | Iteration-2 status |
|---|---|---|
| 1 | Nothing resolves in-window (CRITICAL) | **Not closed** — needs a deadline sweep independent of DTE; also surfaced an INV-6/INV-24 wording conflict |
| 2 | Poison-pill stalls inbox forever (CRITICAL) | **Closed** — refinement suggested (#9 above), not required |
| 3 | Idempotency key from a nondeterministic decision (CRITICAL) | **Downgraded to MEDIUM** — real-exposure risk closed by batch-derived id; bookkeeping/recovery-procedure gap remains |
| 4 | No exactly-once resolution guard | **Mostly closed**, but adding C24 opened a new variant (→ #15 below) |
| 5 | No tick watchdog / stale lock | **Closed** |
| 6 | elfmem auto-consolidates inside a tick | **Not re-verified this pass** — needs a direct trace against elfmem's actual session behaviour |
| 7 | Static context priority inverts on event days | **Partially closed** — reopens under systemic regime-flagging (→ shared with #10 below) |
| 8 | `last_recall_block_ids` loses all but the last frame | **Not re-verified this pass** — implementation-level, needs a direct trace |
| 9 | Entry thesis penalised for exit decisions | **Closed**, refinement opportunity noted |
| 10 | Divergence flag not escalated | **Partially closed** — same root cause as #7 |
| 11 | Assignment yields uncorrelated phantom+orphan | **Unchanged**, out of scope this pass |
| 12 | `mind_predict` subject mapping unspecified | **Unchanged**, out of scope this pass |
| 13 | 5-min cadence mostly no-ops | **Closed** by the split tick model |
| 14 | `lessons.md` unbounded growth | **Unchanged**, still low priority |
| **15 (new)** | C24 runs before C13 — acts on stale data across an assignment/expiry boundary | **HIGH**, one-line reorder fix, also closes adversarial #11 |
| **16 (new)** | Needs-attention tier can bloat under systemic regime-flagging | **MEDIUM-HIGH**, shared fix with #7/#10 |
| **17 (new)** | No resume-from-journal recovery procedure | **HIGH**, the concrete missing piece behind #3's downgrade |
| **18 (new)** | INV-6 / INV-24 wording conflict | **MEDIUM**, spec hygiene, surfaced by #1 |
| **19 (new)** | Repeated interim scoring on a fluctuating signal — stabilising or destabilising elfmem's posterior is unverified | **MEDIUM**, needs grounding (real computation), not resolvable by reasoning alone |
| **20 (new)** | Dead-letter doesn't distinguish malformed vs. transient-outage failures | **MEDIUM** |
| **21 (new)** | Debounce vulnerable to stale/wide quotes on thin contracts | **MEDIUM-HIGH** |

**Score:** of 14 original gaps, 5 closed clean (#2, #5, #9, #13, and #4 mostly), 4 partially closed
and reopened by a shared root cause (#1, #7, #10, plus #3 downgraded not closed), 4 untouched by
this hardening pass (#6, #8, #11, #12, #14 — outside this round's scope), and **7 new findings**
surfaced by attacking the new components, one of them (#15) high-severity but trivially fixable.

---

## Ranked recommendations

1. **Reorder the fast path to C21 → C13 → C24** (closes #15 and #11 together; one line)
2. **Add a competition-deadline sweep**, independent of DTE (closes the real remainder of #1)
3. **Add a resume-from-journal check before re-deciding a batch** (closes #3/#17/#8 together)
4. **Reword INV-6** to exempt interim calls explicitly (closes #18)
5. **Cap the needs-attention tier + make regime shift a single portfolio-level item** (closes #7/#10/#16)
6. Refine dead-lettering to distinguish failure cause (#20); switch debounce to N-of-M plus a
   magnitude override (#21); both MEDIUM, both cheap
7. Ground #19 with a small computational check before trusting interim scoring's stability
8. Carry forward, unchanged: #6, #8 (elfmem behaviour — need a direct trace, not reasoning),
   #11, #12, #14

---

## Residual risks

| Risk | Note |
|---|---|
| #19 cannot be resolved by reasoning | Needs the grounding lever — a minimal computation against elfmem's actual Beta-update math, or empirical data from the live run |
| #6 and #8 unverified this pass | Both are claims about elfmem's actual runtime behaviour; iteration 1's confidence in them was inferred from docs, not exercised — worth a direct integration test before trusting either |
| Fix #15 is easy; verifying it stays fixed is not | Any future component added to the fast path needs the same ordering scrutiny — worth a standing rule: "reconcile before any component that can act on position state" |
