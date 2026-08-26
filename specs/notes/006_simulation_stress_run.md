# Simulation — Stress Run Against the Architecture (2026-08-26)

Dynamics-altitude stress simulation of [architecture.md](../architecture.md), design held fixed.
Six priority scenarios traced step-wise. **14 gaps found, 3 critical.** Ranked in §8; each names
the component, invariant, or failure mode it breaks, plus a concrete mitigation.

Nothing is built — this is pure design simulation. Findings become spec additions and test specs.

---

## 1. World model

**Components in play:** C2 Tick Runner (flock, tick counter), C6 Collector + C20 Sensor Registry,
C7 Inbox, C8 Router, C22 Digester, C21 Analytics, C9 Context Assembler, C10 Forecaster,
C11 Decider, C12 Actor, C13 Reconciler, C14 Learner, C15 Calibration Scorer, C16 Housekeeper,
C17 Journal, C18 Wiki, C19 elfmem.

**State variables tracked per step:** `tick_count`, `inbox.pending[]`, `positions{id: status}`,
`journal[]`, `alpaca.holdings[]`, `elfmem.blocks_recalled[]`, `context_tokens`, `lock_held`.

**Rules:** one action per decide cycle; at-least-once inbox; append-only journal; advisory inputs
degrade rather than block; no guardrails (D-009).

**Assumptions surfaced:** LLM decisions are **nondeterministic** across identical inputs; elfmem
`frame()` reinforces and updates `last_recall_block_ids`; Alpaca rejects duplicate
`client_order_id`; options positions are per-leg rows.

---

## 2. Scenario 1 — Does the learning loop close end-to-end?

| Step | Event | State transition | Observation |
|---|---|---|---|
| 1 | Tick 10, C9 assembles | calls elfmem `frame(self)`, `frame(task)`, `frame(attention)` | **`last_recall_block_ids` holds only the LAST call** → self/task blocks lost → **INV-5 breaks** |
| 2 | C11 decides: open SPY bull put spread | `positions[pos_A] = proposed` | — |
| 3 | C12 submits, C17 journals | `positions[pos_A] = opening` | Journal written *after* submit (see Scenario 3) |
| 4 | Tick 11, C6 sees fill | `positions[pos_A] = open` | — |
| 5 | C14 creates page, calls elfmem | `remember(thesis, cue)` ok; `mind_predict(mind_block_id, ...)` | **Requires a `mind_block_id` — a Theory-of-Mind subject.** No mapping specified from "trade thesis" to an elfmem mind entity |
| 6 | …tick 500, expiry | C13 detects phantom → F3 | — |
| 7 | Also: C6 may emit a close/fill item for the same event | **two independent paths into F3** | **No exactly-once guard → `outcome()` twice → INV-6 breaks** |
| 8 | C15 computes Brier, C14 calls `outcome()` | learning signal written | Only if steps 5–7 survived |

**The dominant finding is at step 6.** The competition window is **Aug 28 → Sep 4 (8 days)**.
Standard options expiries are monthly (Sep 18) or weekly. If the decider selects conventional
30–45 DTE spreads — the default for the strategy family — **no position expires before the
deadline**. Resolution then depends entirely on the agent choosing to close, which nothing
requires it to do.

Consequence: Brier scoring never fires, `outcome()` never fires, no lessons are written, elfmem
accumulates but never learns. **The system's differentiating feature produces zero output during
the entire competition, while appearing to run correctly.** It fails silently — every tick looks
healthy.

---

## 3. Scenario 2 — Cold-start context assembly, 20 positions, FOMC flood

| Step | Event | `context_tokens` (relative) | Observation |
|---|---|---|---|
| 1 | 20 position pages, full thesis + timeline | dominant share of budget | Positions are top priority by design |
| 2 | elfmem frames (self 600 + task 800 + attention 2000) | fixed ~3.4k | Bounded, fine |
| 3 | Analytics pack, 20 positions of greeks | moderate | Compact numerics, fine |
| 4 | FOMC: primary news, Polymarket Fed odds, macro + social digests | **budget exhausted** | Lowest priority dropped first |
| 5 | INV-15 records what was cut | drops = macro digest, social digest, **prediction markets** | — |

**The priority order inverts on exactly the days that matter.** Position count — which has nothing
to do with today's importance — crowds out the Fed signal that should dominate the decision. The
15th position's full timeline outranks a 30-point move in Fed-cut odds.

Total context fits a modern window, so this is not a hard limit failure; it is **attention
dilution plus cost**, and a static priority order that cannot express "today, macro matters more
than position detail."

---

## 4. Scenario 3 — FM-1 crash window and idempotency

| Step | Event | State | Observation |
|---|---|---|---|
| 1 | Tick 20: C11 decides → `pos_A`; `client_order_id = f(pos_A)` | — | Key derives from the decision |
| 2 | C12 submits; Alpaca **accepts** | `alpaca.holdings += legs` | — |
| 3 | **Crash** before C17 journal + C7 archive | `inbox.pending` unchanged | At-least-once retains the batch |
| 4 | Tick 21: C8 re-routes the *same* items | — | — |
| 5 | C9 assembles, C11 decides **again** | **LLM is nondeterministic → may produce `pos_B`** | — |
| 6 | `client_order_id = f(pos_B)` ≠ `f(pos_A)` | **Alpaca does not dedup** | **INV-11 breaks; FM-1's mitigation does not hold** |

**The idempotency key is derived from a nondeterministic decision.** It only dedups if the retry
reproduces the identical decision, which an LLM cannot guarantee. The realistic outcome is not
one duplicated order but **two different positions** opened from one batch — worse, because
neither looks like a duplicate to any check.

Compounding: F1 journals *after* submitting, so a crash in the window leaves **no record that an
order was ever attempted**. Recovery has nothing to reconcile against.

---

## 5. Scenario 4 — False viral social item, no guardrails

| Step | Event | State | Observation |
|---|---|---|---|
| 1 | Day 3, `x_social` returns "SPY halted, circuit breaker" (false) | `trust: social` | Filter passes it — names an open underlying |
| 2 | Low volume tick → no digest, passed raw | in context, tier-labelled | Trust tiering working as designed |
| 3 | Constitution (self frame): "social requires corroboration" | present in prompt | Instruction, not enforcement |
| 4 | Analytics pack shows SPY price normal, no halt | contradiction available | A careful model dismisses it |
| 5 | **Adversarial branch:** model panics, closes 4 positions at a loss | `positions[*] = closed` | Nothing prevents this (D-009) |
| 6 | C14/C15 score the closes | Brier scores the **entry theses** as misses | — |
| 7 | `outcome()` penalises entry-thesis blocks and their sources | **wrong blocks penalised** | Sound theses marked bad because of a panic *exit* |

**Trust tiering plus corroborating analytics gives the model what it needs to reject the item —
but the design gives it no way to be *required* to.** That is the accepted D-009 trade-off, and
the simulation confirms the residual exposure is real, not theoretical.

The subtler failure is step 6–7: **credit assignment conflates entry quality with exit quality.**
A good thesis exited badly is recorded as a bad thesis, and the memories and sources that produced
a *correct* entry get penalised. This teaches the system the opposite of the truth, and it happens
whenever an exit is driven by anything other than the original thesis playing out.

The social source *is* correctly penalised — but only because the close decision cited it. That
part works.

---

## 6. Scenario 5 — Partial multi-leg fill (broken spread)

| Step | Event | State | Observation |
|---|---|---|---|
| 1 | C12 submits 2-leg spread | — | — |
| 2 | Short leg fills; long leg does not | **naked short put** | Risk profile now unbounded |
| 3 | Fill lands between ticks | undetected | Up to a full cadence blind (~5 min) |
| 4 | Next tick C13 diffs `intended_legs` vs `actual_legs` | divergence flagged on the page | Detection works |
| 5 | C9 assembles context — 20 positions, busy day | **flagged position may be summarised or dropped by budget** | Compounds with Scenario 2 |
| 6 | C11 may never see the flag prominently | naked short persists | — |

Detection is sound; **escalation is missing**. A divergence flag carries no priority weight, so the
single most urgent position competes on equal footing with 19 routine ones, and can lose.

---

## 7. Scenario 6 — Expiry and assignment

| Step | Event | State | Observation |
|---|---|---|---|
| 1 | Short put assigned at expiry | option leg disappears | C13 sees **phantom** → F3 |
| 2 | Simultaneously, 500 shares of SPY appear | unexpected holding | C13 sees **orphan** → stub page, `provenance: unknown` |
| 3 | Two events, treated independently | causal link lost | Agent inherits a stock position it "cannot explain" — though we know exactly where it came from |
| 4 | If Alpaca *also* surfaces an assignment event | third path into F3 | **Double resolution risk again (INV-6)** |

Assignment is the one lifecycle event that produces a **correlated phantom + orphan pair**, and the
reconciler models them as unrelated. The `provenance: unknown` label is actively misleading here.

---

## 8. Failure rankings

| # | Gap | Severity | Breaks | Root cause | Mitigation |
|---|---|---|---|---|---|
| 1 | **Nothing resolves inside the 8-day window** → learning loop never closes, silently | **CRITICAL** | Whole learn path; D-013 | Conventional DTE outlives the competition; resolution is optional | Constrain strategy to ≤7 DTE in constitution/strategy.md; **add low-weight interim scoring at housekeeping** on unrealised P&L (elfmem `outcome()` takes a `weight`, so interim = low, resolution = full); force-close before deadline |
| 2 | **Poison-pill inbox item stalls the pipeline forever** | **CRITICAL** | INV-2, C7, C8 | Malformed item is retried every tick under at-least-once, blocking the batch permanently | Per-item retry counter; after N attempts move to `inbox/failed/` and continue (dead-letter) |
| 3 | **Idempotency key derives from a nondeterministic decision** | **CRITICAL** | INV-11, FM-1, C12 | Retry re-decides; new `position_id` → new key → no dedup → two *different* positions | Derive `client_order_id` from the **batch** (hash of item ids) — one action per cycle makes this safe; plus **write-ahead journal** the intent before submitting |
| 4 | No exactly-once guard on F3 resolution | HIGH | INV-6, C13/C14 | Reconciler and collector can both detect the same terminal event | Status transition is the guard: refuse open→terminal if already terminal; journal resolution once per `position_id` |
| 5 | No tick-level timeout; hung LLM stalls unattended run | HIGH | C2, C11 | `flock` makes every later tick skip silently; no watchdog | Hard tick timeout; lock file carries PID+timestamp so stale locks break |
| 6 | elfmem session auto-consolidates on exit | HIGH | **INV-10**, C19 | `async with mem.session()` triggers `dream()` if `should_dream` — inside the tick | Suppress auto-consolidation for tick sessions; call `dream()` explicitly only at housekeeping |
| 7 | Static context priority inverts on event days | HIGH | INV-15, C9 | Position count crowds out event-critical macro signal | **Two-tier positions**: one-line summary for all, full detail only for "needs attention" (divergence, near expiry/stop, regime-flagged); promote that tier above news |
| 8 | Multi-frame recall clobbers `last_recall_block_ids` | HIGH | **INV-5**, C9/C19 | Three `frame()` calls; only the last survives in the property | Capture block ids per frame at assembly; store union as `context.elfmem_blocks` |
| 9 | Credit assignment conflates entry thesis with exit decision | MEDIUM | C14/C15 | Panic or external exits score the entry thesis as wrong | Journal a `close_reason` (thesis_resolved / stopped / external / panic); score entry theses only on self-resolved positions; score exits separately |
| 10 | Divergence flag has no priority escalation | MEDIUM | FM-2, C9 | Broken spread competes equally with routine positions for budget | Covered by #7's "needs attention" tier — divergence forces full detail, top priority |
| 11 | Assignment yields uncorrelated phantom + orphan | MEDIUM | INV-9, C13 | Reconciler treats the two halves as unrelated events | Detect the assignment signature (short leg vanishing at expiry + matching stock quantity at strike); link them; set real provenance |
| 12 | `mind_predict` needs a mind subject; mapping unspecified | MEDIUM | D-013, C14/C19 | elfmem's mind loop models an *agent's* mind, not a market outcome | Decide the mapping before building: a mind per underlying, or bypass the mind loop and store forecasts natively |
| 13 | 5-minute cadence likely mostly no-ops | LOW (cost) | C1 | ~78 decide calls/day at full context for few actions | Default to 15 min; adaptive fast mode only when positions near triggers or regime just flipped |
| 14 | `lessons.md` grows unbounded into the budget | LOW | C18/C16 | Every close appends a lesson; decide reads them all | Lesson dedup/consolidation at housekeeping; cap injected lessons by recency + relevance |

---

## 9. Residual risks

| Risk | Note |
|---|---|
| Sensor value unmeasurable by simulation | Whether news/social/Polymarket improve decisions needs the live control run (architecture §11 Q7) — no design analysis can settle it |
| LLM decision quality | Simulation can prove the *plumbing* closes; it cannot predict whether the trades are good |
| elfmem integration specifics | Gaps #6, #8, #12 all stem from elfmem behaviours inferred from its docs, not exercised — verify against the real library early |
| Alpaca assignment reporting | Gap #11's fix depends on the unverified assumption about how assignment surfaces |
| Wiki navigability at 8 days | Traced as manageable (~20–40 position pages, daily index refresh); only `lessons.md` growth (#14) is a real pressure |

---

## 10. What this changes

Gaps #1, #2, #3 are build-blocking: each individually defeats a core promise of the design while
the system continues to look healthy. #1 is the most consequential — it would let us ship a
"self-improving" agent that never once completes a learning cycle.

#4–#8 are hardening required for an 8-day unattended run.
#9–#12 are correctness-of-learning issues that degrade the feedback signal rather than stop it.
#13–#14 are efficiency.

Recommended: fold #1–#8 into the spec and build order before writing code; carry #9–#12 into the
module specs; leave #13–#14 as tuning during the live run.
