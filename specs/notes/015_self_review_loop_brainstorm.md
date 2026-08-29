# The Coach - an autonomous self-improvement loop over every subsystem

Rewritten 2026-08-29, superseding the 2026-08-28 draft (git history holds it). The first draft
routed every finding through human ratification. Direction from the user: **that is the wrong
trade for a hackathon** - human gates block the fast feedback loop, this is paper trading, the
risk is tolerable. The system should improve itself autonomously; the human reads clear metrics,
charts and reports afterwards and *steers* if it drifts, rather than *approving* before it moves.
This is the operating agreement the whole project already runs under, applied to the bot itself:
**reversibility replaces permission.** Every change the loop makes must be data, recorded, and
instantly revertible - then it does not need to ask.

**Status: designed and simulated, not built.** The simulation record is at the bottom; the
design presented first is its winner.

---

## Intent, held in one paragraph

The system is subsystems: muse, discovery, research, decide, sizing, exit rules, memory. Each
one currently gets better only when a human-led session finds a defect (D-074's shakedown,
D-076's critique). The Coach makes improvement a *runtime* behaviour: each subsystem exposes
what "good" looks like as measured numbers, exposes the choices it could make differently as
declared variants, runs controlled A/B trials against its own evidence, promotes winners
automatically, and records everything in time-series form so a human can see the trajectory and
intervene by editing declarations - never by being a blocking approval step. One protocol, every
subsystem, so the improvements stay in harmony rather than becoming seven bespoke loops.

## What survives from the first draft - constraints backed by evidence, not preference

These are kept **not** as caution but because this project measured them:

1. **P&L cannot judge anything in this window (D-045).** A genuinely 60%-edge agent beats a coin
   flip only 69% of the time over 20 trades. All rewards below are behavioural and dense - they
   accrue per candidate or per cycle, not per resolved trade.
2. **The constitution and elfmem's blocks stay out of the autonomous lever space (ADR 0003).**
   elfmem's own project simulated four architectures for automatic constitutional evolution and
   none beat baseline. That is a measured result, not a governance preference - so memory gets
   gauges and reporting only, and keeps its existing learning machinery. Everything else is fair
   game.
3. **Compute the gap, never ask the model to notice it** (research.py's own principle, re-proven
   by D-081). Rewards and gap-detection are deterministic; LLM calls generate *candidates* for
   improvement, never the *scores*.
4. **The loop needs its own heartbeat from cycle one** (the D-074/D-082/D-086 tautology, fixed
   four times in one day). `coach_run` journal rows record trials assigned and results scored,
   independent of whether anything was promoted, with both silence flags set correctly at birth.

And one piece of luck: **D-045 already built the provenance this needs.** Every decision
journals `{prompt: fingerprint}` (`prompts.py`), added precisely because "a decision recorded
today without a prompt label can never be compared against tomorrow's." The machinery D-045
deferred is exactly what is being asked for now.

---

## The design: one protocol, four parts per subsystem

Every subsystem registers four things with `coach.py`. The registry is code (a dict per
subsystem), the *state* is data.

### 1. Gauges - deterministic measures, recorded over time

Each subsystem names the numbers that define "working well," computed from stores that already
exist (journal, ledger, usage, calibration). Housekeeping snapshots every gauge every run into
**`data/metrics.jsonl`** (append-only, same convention as journal and ledger). This is the
time-series the user asked for: divergence becomes visible as a trajectory, not an anecdote.

Gauges are for **sentinels and the report only - never for promotion.** Promotion uses local
rewards (below). This split is what keeps concurrent activity attributable: a global metric
moving proves nothing about which change moved it, so nothing global is ever allowed to promote
anything.

### 2. Levers - bounded autonomy, variants as data

A lever is a declared choice the Coach may change on its own: a prompt variant, a sampling
policy, a threshold, a collision arity. **Everything not declared as a lever is off-limits** -
the Coach cannot touch code, gate semantics, sizing math, the sentinels, or its own reward
functions. The human pre-authorises the *space*, not each move; that is the entire replacement
for the approval gate, and it is enforceable by construction because variants live as data under
`data/state/levers/` (current incumbent + at most one challenger per lever), not as edits to
source.

The one hard structural rule: **a lever's set and its experiment's reward set must be disjoint,
and the scheduler refuses any experiment where they intersect.** The muse's gauntlet gates score
muse prompt trials - so the gates cannot be a lever while such a trial runs. The thing that
measures must never be movable by the thing measured; this is the Goodhart defence, held as a
scheduling invariant rather than a hope.

Gate thresholds *are* still tunable - on their own slower cadence, scored by a different signal
they cannot influence: **gate regret**, from D-081's rejected-thesis recording (a rejected
candidate still resolves; "we refused it and it would have held" scores the gate's threshold at
zero cost, against real outcomes).

### 3. Trials - paired A/B, promoted by posterior, everything registered

- **Paired by default.** During a muse trial, one run feeds the *same* sampled concepts and the
  same news to incumbent and challenger prompts; per-candidate pass/fail through the same gates
  gives paired evidence, which at this project's n is the difference between a usable signal and
  noise. Each run yields ~5 candidates x ~8 gates, so evidence is dense even when runs are few.
- **Promotion rule:** challenger replaces incumbent when P(challenger > incumbent) >= 0.9 on the
  paired reward (Beta-Binomial for pass/fail; demeaned-bootstrap over paired differences for
  continuous rewards - the same estimator discipline the trading side already uses), with a
  floor of 12 paired runs, capped at 40. Ties and timeouts keep the incumbent - the conservative
  default costs nothing because the incumbent is already the thing running.
- **Concurrency: at most one experiment per subsystem, at most two system-wide.** Confounds are
  prevented by scheduling, not untangled by statistics afterwards.
- **Every trial is registered, including the losers** - D-052's multiple-testing discipline,
  reapplied one level up. Defeated challengers go to a **graveyard** in the experiment ledger
  (`data/experiments.jsonl`, append-only) with their evidence, and the mutation prompt (below)
  receives the graveyard summary so the loop never re-litigates a dead idea blind - the same
  reason D-076 recorded its killed mechanisms.

### 4. Sentinels - the autonomic brake, and the revert path

Global, deterministic, checked every housekeeping run: daily LLM cost ceiling; a `health` FAIL
persisting across two windows; calibration reliability collapsing; seed-entropy floor (below);
promotion churn (more than K promotions/day is itself suspicious). A sentinel firing **pauses
new trials, reverts any in-flight experiment to its incumbent, and flags itself at the top of
the report.** Reverting is instant and safe because variants are data. The book cap, tool
guard and gauntlet stay exactly where they are - the Coach sits above them and cannot loosen
them.

### Two-tier reward: the fast one promotes, the slow one audits

Proximate rewards (gauntlet survival, band-anchoring accuracy) arrive in minutes and drive
promotion. Outcome rewards (did the band actually hold at horizon) arrive in days and **audit**:
every promotion carries the gain it claimed, and when resolved outcomes land, realized-vs-claimed
is scored. A promoted variant whose outcomes degrade triggers an automatic **re-match** against
the previous incumbent - autonomy preserved, but evidence gets the last word. This is the
calibration philosophy applied to the loop itself: the Coach keeps a Brier-style score on its
own promotions, and that score is a gauge on the report.

### Challenger generation - the creative channel, muse-shaped

Two generators, both trial-registered:

- **Mutation.** An LLM role receives the incumbent prompt, the recent rejection evidence (which
  gates killed which candidates, verbatim fates), and the graveyard summary, and produces ONE
  challenger variant. This is how prompts improve without a human writing variants - directed
  creativity, aimed by real failure data.
- **Wildcard collision.** The muse's own trick pointed inward: sample two unrelated signals (an
  uncited lesson + a flat gauge; a scaffold finding + a gate's regret record) and ask whether a
  causal story connects them. Survivors that map onto an existing lever become experiments.
  Survivors that don't - structural ideas needing new code - are appended to `specs/issues.md`
  as `[coach]`-tagged entries: an autonomous write to a human-read file, blocking nothing. The
  dev sessions consume that queue. (Live example of what belongs there: I-15, entry commitments
  not surviving a decide cycle - no lever can fix it, code must.)

### Scaffolds as evidence generators, and the offline pre-screen

D-079's structure zoo is re-runnable, deterministic, and LLM-free - it converted "is sizing
biased?" into an exact measurement. Generalised: a **scaffold registry**, re-run by housekeeping
on cadence, whose outputs are gauges (invariants pass/fail, measured biases in pp). A scaffold
finding that *shifts* between runs auto-files an improvement thesis. And where a lever has an
offline scorer, challengers are **pre-screened offline before burning live paired trials** -
the full pipeline being: mutate -> offline screen -> live paired trial -> promote -> outcome
audit. The diagnostic pass may also propose *missing* scaffolds ("nothing covers calendar
spreads"), which is the outside-the-box channel for test coverage itself.

### The report - the human's steering interface

`trdrbot report` renders `data/metrics.jsonl` + `data/experiments.jsonl` into one self-contained
HTML page (`data/report.html`, inline SVG sparklines, no external deps), regenerated by
housekeeping. It leads with **what changed**: promotions, reverts, sentinel fires, top gauge
deltas, open experiments, cost - then each gauge's trajectory with the Coach's own actions
overlaid as markers, so "muse survival rate rose after promotion #3" is a picture, not a claim.

Steering is by editing state, not by approving actions: pin a variant, pause a subsystem's
experimentation, adjust a sentinel ceiling - honoured at the next cycle. Demo day is one pin.

### The Coach is itself a subsystem

It registers its own gauges (trials run, promotion rate, realized-vs-claimed gain, experiment
cost share), its own sentinels (churn, cost), and its own heartbeat. It must eat its own food,
and the report shows the Coach's trajectory next to everyone else's.

---

## Worked example: the muse

The user's own example, and the correct first target - dense signal, cheap runs, isolated
blast radius (its output faces the gauntlet before anything real happens).

**Gauges:** candidates per run; gauntlet survival rate (D-081 measured this moving 13/15
rejected -> 1/5 in one fix - it is *known* to be sensitive to prompt quality); band-anchoring
error (|band mid vs realized move| at horizon, computable since bands became percent moves);
distinct underlyings per week; seed-type entropy (which concept types actually got sampled);
gate regret (rejected theses that resolved inside their bands).

**Levers:**
- *Seed sampling policy.* Incumbent: uniform random. Challenger: Thompson sampling over
  **concept-type pairs** (technique x research, research x regime...), reward = a candidate
  seeded from that pair survives the gauntlet. Hierarchical on purpose: type-pair arms
  generalise at low n where per-concept arms cannot, and an epsilon exploration floor plus the
  seed-entropy sentinel guard the muse's actual mandate - random collision - from being
  optimised away into a momentum machine.
- *Collision prompt.* Incumbent vs one mutated challenger, paired runs as above.
- *Collision arity* (2 vs 3 concepts).
- *Gauntlet thresholds* (`BASE_PROB_FLOOR` etc.) - slower cadence, scored by gate regret only,
  never concurrent with any experiment that uses the gates as its reward (the disjointness
  rule, in the flesh).

**Rewards:** per-candidate gauntlet survival (proximate, promotes); band resolution at horizon
(audit). Both deterministic, both from mechanisms the muse cannot touch.

**What improvement looks like here, concretely:** within days the Coach can learn *which kinds
of collisions produce theses that survive scrutiny* and *which prompt wording anchors bands
better* - the two things currently frozen at whatever the first version happened to be.

## The same protocol, across the board

| Subsystem | Gauges (examples) | Levers | Proximate reward | Audit signal |
|---|---|---|---|---|
| muse | survival rate, band error, entropy | sampling policy, prompt, arity | gauntlet survival | band resolution |
| discovery | nominee survival, dossier quality flags | nominate prompt, synth prompt | gauntlet survival | thesis resolution |
| research | premise-break rate downstream, "date unknown" honesty | dossier prompt | downstream premise checks passing | forecast resolution |
| decide | abstention streak, principle citation, stated-prob Brier, premise-verification rate | context assembly weights, prompt variant | behavioural metrics via **shadow trials** | resolved forecast calibration |
| gates/sizing thresholds | gate regret, refusal EV | threshold values | - (slow lane only) | gate regret vs resolved rejects |
| memory/constitution | citation rates, credit flow | **none (ADR 0003)** | - | report only |
| the Coach | promotions, realized-vs-claimed, cost | its own cadence | - | its own audit |

**Decide runs shadow trials:** the challenger decides on the same live inputs, its decision
journaled but never executed, scored counterfactually by the same retrospective machinery D-080
built (bands vs subsequent price history). Paired comparison at zero position risk; the cost is
LLM spend, so shadows run every Nth cycle under the cost sentinel, and decide is deliberately
the *last* subsystem enabled.

**Rollout order:** muse -> discovery -> research -> decide-shadow. Gate thresholds join once
enough rejects have resolved to make regret a real signal.

---

## Simulation record (optimize; ephemeral; stop on goal-reached or 5 iterations)

**Goal:** a loop that autonomously improves subsystems on evidence, stays bounded and
non-interfering, and is observable/steerable by a human who never becomes a gate.
**Fitness:** velocity 🟢/🟡/🔴, safety, statistical honesty, harmony, observability, simplicity.

**Frozen scenario set:**

| ID | Scenario | Nature |
|---|---|---|
| F1 | Muse dry spell: 3 runs, 0 gauntlet survivors | happy-path improvement |
| F2 | Mutated challenger is genuinely worse (survival halves) | adversarial |
| F3 | Challenger games the reward: near-duplicate SPY candidates pass gates, diversity collapses | Goodhart |
| F4 | Sampling-policy and prompt experiments proposed on the muse simultaneously | confound |
| F5 | Challenger ahead 4-1 after 5 trials by luck | low-n |
| F6 | Decide-shadow doubles daily LLM spend | resource |
| F7 | Experiment assignment silently stops; nothing notices | the tautology class |
| F8 | Promoted variant fine on proximate reward; its resolved bands miss high, systematically | delayed failure |
| F9 | Operator wants incumbent pinned and experiments paused for demo day | steering |
| F10 | Diagnostic finds I-15 (commitments don't survive a cycle) - no lever can express the fix | structural gap |

**Iteration 1 - baseline: the v1 human-ratified design.** F1: gap detected, fix waits on
ratification - days lost. F2-F5, F8: no experiments exist to fail. F9, F10: fine. Fitness:
velocity 🔴, safety 🟢, honesty 🟢, harmony 🟢, observability 🟡, simplicity 🟢.
**Verdict: incumbent to beat - it fails the brief's core requirement by design.**

**Iteration 2 - full self-modification: an LLM critiques recent behaviour and edits prompts and
parameters directly.** F1: acts fast 🟢. F2: bad edit ships live, found only by later drift.
F3: nothing measures diversity. F4: several edits land together, attribution unrecoverable.
F5: promotes luck. F7: no heartbeat. Matches the shape ADR 0003 already measured as
not-better-than-baseline. Velocity 🟢, safety 🔴, honesty 🔴, harmony 🔴.
**Verdict: REJECTED. Incumbent unchanged.**

**Iteration 3 - gauges/levers/trials/sentinels, unpaired, single-tier reward.** F2: challenger
loses on evidence, reverted 🟢. F4: scheduler refuses the second experiment 🟢. F6: cost
sentinel pauses 🟢. F9: pin honoured 🟢. F10: routed to the issues queue 🟢. But F5: unpaired
trials at n=5 stay noisy - the 0.9 threshold helps, slowly 🟡. F1: no challenger exists unless a
human writes one 🟡. F3: no diversity gauge 🔴. F8: uncaught 🔴.
**Verdict: KEPT - beats baseline on velocity while holding safety. New incumbent.**

**Iteration 4 - + paired trials, 12-run floor, type-pair Thompson arms, mutation generator with
graveyard.** F5: paired evidence + floor rejects the lucky streak 🟢. F1: mutation produces a
challenger from the rejection evidence itself 🟢. F2: cheaper to reject (paired variance) 🟢.
F3, F7, F8 still open.
**Verdict: KEPT. New incumbent.**

**Iteration 5 - + outcome-audit tier with auto re-match, seed-entropy sentinel, scaffold
registry + offline pre-screen, metrics.jsonl + annotated report, Coach heartbeat.** F3: entropy
sentinel fires, experiment reverted, flagged 🟢. F7: heartbeat rows make assignment silence a
health FAIL 🟢. F8: audit compares realized vs claimed, files the re-match 🟢. F6: offline
screen cuts live shadow trials needed 🟢. Full frozen set passes.
**Verdict: KEPT - winner. Stopping reason: goal reached on the frozen set (and the iteration
cap is adjacent).**

**Journey:**

| Iter | Change | Frozen-set vs incumbent | Kept? |
|---|---|---|---|
| 1 | v1 human-gated baseline | fails F1 (velocity) by design | incumbent to beat |
| 2 | direct self-modification | fast, fails F2/F3/F4/F5/F7 | REJECTED |
| 3 | gauges/levers/trials/sentinels | fixes F2/F4/F6/F9/F10 | KEPT |
| 4 | pairing, floors, arms, mutation | fixes F1/F5 | KEPT |
| 5 | audit, entropy, scaffolds, report, heartbeat | fixes F3/F7/F8, all pass | **KEPT - winner** |

## Residual risks

| Risk | Note |
|---|---|
| Low n is physics | Promotions inside a hackathon week will be few; paired + dense per-candidate evidence is the mitigation, and the report says so honestly rather than dressing it up |
| Regime shift after promotion | The audit re-match is the counter, and it is slow by nature; the previous incumbent is always retained as the re-match opponent |
| Goodhart beyond enumerated sentinels | Sentinels are a list, not a proof; the annotated report and the human's read of it are the backstop - which is what "steer, don't gate" means |
| Mutation quality variance | A weak challenger costs one bounded experiment and enriches the graveyard; the failure mode is wasted trials, not damage |
| Complexity creep | The registry must stay small; muse-only first, and every later subsystem must reuse the identical protocol or not join |
| The Coach competes with trading for budget | The cost sentinel arbitrates, and the Coach's own cost share is a gauge on the report |

## Build sketch (when built)

`coach.py` (registry, scheduler, trial assignment, promotion, sentinels) + `data/state/levers/`
(variant state, human-editable) + `data/metrics.jsonl` / `data/experiments.jsonl` (append-only)
+ `trdrbot coach` (status) / `trdrbot report` (HTML) + hooks: `muse.run` consults the registry
for its active variant per trial; housekeeping snapshots gauges, checks sentinels, runs the
audit and the scaffold registry; `coach_run` heartbeat journaled every pass. Muse first, alone,
until the first honest promotion or rejection lands end-to-end.
