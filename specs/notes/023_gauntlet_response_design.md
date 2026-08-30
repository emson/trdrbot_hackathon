# 023 - Gauntlet response: one measure, refusal that propagates, pillar evals

2026-08-30. The trader gauntlet (`tests/scaffold_trader_gauntlet.py`, issues I-40..I-45)
measured six defect-grade behaviours and four design observations. This note is the design
response, produced by the optimize protocol (candidates simulated against the gauntlet's own
scenarios as a frozen set; journey table at the bottom). Status: **designed and simulated, not
built.** The winner is presented first, per notes/015 convention.

---

## The organising insight: the defect taxonomy generalises

This project keeps fixing instances of the same class and naming each one:

- two clocks for one position (D-074)
- two calibration numbers for one record (D-076)
- two cost views for one gate (D-079)
- **two probability measures for one Kelly** (I-41: `p` from the agent's vol view, `b` from
  the market's) - and a seam that silently DROPS the cost view (I-40)
- two rule-health checks that both miss unobservable rules (I-45, cousin of I-42's
  `_unreachable_rules`)

The class: **two layers computing one decision quantity under different assumptions.** The
existing cure - "one definition, one clock, one copy" - generalises to the whole decision:

> **One measure per decision.** Every probability, expected value, and payoff ratio that feeds
> one gate/size decision is computed under one declared measure (drift, vol). A seam that loses
> the measure, or any part of it (friction included), refuses rather than substituting.

Everything below is that rule plus three companions, and the gauntlet scenarios are what it is
scored against.

## The design (winner of the loop)

### R1 - The thesis carries its vol view; the measure is the thesis

`Thesis` gains `vol_view: float | None` - the realized-vol forecast the agent already states
and already scores (`record_forecast(metric="realized_vol")`, WU-3.6). When present,
`simulate` computes `pop_thesis`, `ev_thesis` and `payoff` under `(drift, vol_view)`; when
absent, market IV, byte-identical to today. The market-measure columns stay, as today, so the
gap between measures remains the visible claimed edge.

Why this is the profitability unlock: D-079's algebra (gate opens ⇔ EV-after-costs > 0) is
measure-agnostic - it is conditional-expectation arithmetic. Extending the measure to vol makes
the gate exact for vol theses the way it already is for drift theses (gauntlet G2b verified the
drift case to the dollar). Measured consequence of NOT having it (G2): a condor with 12 vol
points of true, honestly-stated edge pins at the seed allocation forever - full Kelly under the
mixed measure never turns positive. The system's best-scored signal (the vol forecast) is
currently disconnected from size.

Deliberately deferred: deriving the stated probability FROM the view (gate-on-scored-parameters
instead of gate-on-claim). It is the cleaner end state - the claim degree of freedom disappears
and calibration scores the view parameters directly - but it changes calibration semantics, and
R1 alone already aligns the measures. Recorded as a direction, not built.

### R2 - Refusal propagates; the fallback pays friction; b is conditional

Three sub-rules, one principle (a refusal upstream is information, not an inconvenience):

1. When simulated structures exist this cycle and `_matching_payoff_ratio` finds no match,
   `size_position` REFUSES ("structure does not match anything simulated - simulate it first").
   Today it silently falls back to frictionless max/max: measured (G6), the same fair condor at
   the same claimed 70% flips from refused (gate needs 79%) to **224 contracts at the 5% cap**
   (gate needs 22%).
2. When nothing was simulated at all, the max/max fallback charges friction:
   `b = (maxP - f) / (|maxL| + f)`. Strictly more conservative than today's fallback.
3. Kelly refuses on unbounded LOSS only. Unbounded PROFIT with a finite conditional ratio
   (a long call: E[win|win] is finite) sizes on the conditional ratio. This DELETES a special
   case rather than adding one, and unbans convexity (G6: long calls currently refused at any
   edge, payoff 1.96 notwithstanding).

### R3 - Decisive mark closes require corroboration

The magnitude override on `position_mark` currently makes the documented artifact case (one
-100%-of-credit print on a healthy spread) the decisive case (I-42). Fix: a mark breach may
skip the debounce only when the underlying corroborates - has moved adversely by at least a
fraction of the position's expected move over the remaining horizon (start 0.25x; tune from the
journal's own artifact-vs-gap history, not by taste). Otherwise the breach debounces normally
(2-of-3). Underlying and date signals are unchanged - the underlying prints tightly and time is
not noisy. A real gap moves the underlying, so gap protection survives; a lone crazy quote no
longer realises an artifact loss at the widest spread of the day.

### R4 - Tools confess their domain

Honesty renderings, no behaviour change:

- `breakeven_vol` with no crossing reports "no crossing in searched range (0.5%-120%)", never
  "EV positive at every realized vol tested"; grid extends to `max(120%, 1.5 x priced IV)`
  (I-44 - a meme-IV name currently reads as *wins at any vol*, the exact confident wrongness
  the tool exists to kill).
- `record_position` warns when net cost < 2% of gross: "mark rules can never print
  (MIN_NET_COST_SHARE) - add an underlying or time rule" (I-45). Same pattern and same home as
  `_unreachable_rules`. Report, don't gate (D-009).

### F1 - Implicit time stop, same mechanism as the implicit deadline rule

`days_to_expiry <= 1 -> close` on every position unless the agent wrote its own time_stop.
Bounds the slow bleed (G4/P5: -49% forever, nothing fires) and the expiry cliff with machinery
that already exists (the deadline is already an implicit rule on every position, INV-26).

### F2 - Evaluate skew at the vega-weighted leg IV, and show the span

When legs carry IVs, the flat evaluation vol becomes the vega-weighted leg IV instead of the
caller's ATM guess, and simulate reports the EV span across the leg IVs as the
undefendable-input band (same philosophy as `breakeven_vol`: name what has to be true, don't
pick silently). Measured motivation (G3): a fair-by-construction skewed board gates a put
credit at 71% and its mirror call credit at 97% - 26pp apart on zero edge either way. A full
smile-consistent model is deliberately refused, same reason calendars are refused: a confident
wrong distribution is worse than a stated approximation.

## What the winner deliberately does NOT include (rejected in the loop)

- **An EV hurdle above the seed floor** (last critique's item 7). With R1, the gate is exact in
  the DECISION measure, so the boundary case is EV-after-costs = 0 exactly - and paying the
  seed allocation at zero EV is the exploration design working ("a bounded cost paid for
  information", D-047), governed behaviourally by `[exploration-budget-is-not-a-mandate]`.
  A hurdle would re-stack haircuts into exactly the D-076 "nobody chose this verdict" class.
  The cliff was never the bug; the wrong measure under it was.
- **Book-level vega/beta-delta CAP.** No gauntlet scenario measured it failing; adding a gate
  in anticipation violates both the working agreement and this project's history (the opaque
  open-count divisor D-037 removed). Instead: a GAUGE (below). Measure first, cap if the
  trajectory says so.
- **Full smile model, escalating stops, regime-conditional sizing** - complexity without a
  measured scenario, or contradicting the refusal stance.
- **A constitution amendment.** The constitution is FULL (427/430 tokens - adding means
  retiring), and its own scope rule decides this anyway: "anything a deterministic check can
  enforce stays in code." One-measure is deterministically enforceable. It becomes code plus a
  pillar eval, not identity.
- **LLM-replay decision evals as a CI gate.** Contradicts "we do not test LLM output quality"
  and would make every code change wait on model nondeterminism. What IS adopted instead - at
  promotion time, not in CI - is the golden decision set (below), which grades the ACTION and
  the resulting state, never the wording. The distinction is the published one: grade outcome
  and end-state, use transcripts only to diagnose (Anthropic, "Demystifying evals for AI
  agents").

## Memory and knowledge changes

Small on purpose - the gauntlet found SYSTEM defects, and defects belong to code and its tests.
Memory gets only what judgement must carry:

- **One new lesson** `[both-sides-of-the-smile]`: "On a zero-edge skewed board my flat-IV
  evaluation gated a put credit spread at 71% and its mirror call credit at 97% - the same
  no-edge trade, 26pp apart, purely by which side of the smile it sat on. When legs quote IVs
  far from the vol I evaluate at, re-run the conclusion at the leg IVs before trusting EV; the
  choice of evaluation vol is an assumption to test both ways." Cue: "when leg IVs differ
  materially from the ATM or evaluation vol". This survives F2 (the discipline outlives the
  default) and is `[assumptions]` applied to the smile.
- **Wiki, two timeless technique concepts** for the muse to collide (D-053 pattern):
  *volatility skew* (why the smile exists; what selling it means) and *pin risk / the gamma
  wall* (why short-dated short premium concentrates risk at the strike). Cheap, enriches
  collisions, no risk surface.
- **No new constitution principle** (scope rule, above). No lesson for I-40/I-42/I-44/I-45 -
  once enforced in code, a lesson would be a second copy of a rule, and second copies drift.

## The eval architecture: three layers, one worry answered

The worry is right: threshold-flavoured evals contradict in pairs ("trade more" vs "refuse
more", "exit fast" vs "don't churn"), and guardrail sprawl measurably inflates false alarms
(PostHog measured A/A false-alert rates of ~14% at 3 guardrail metrics, ~40% at 10). The
resolution has two parts. First, **pillar evals pin RELATIONSHIPS (exactness, monotonicity,
refusal, conservation), never levels** - an exactness invariant cannot contradict a
monotonicity invariant; two thresholds always eventually do. Second, **the suite stays tiny by
construction**: external guidance and this project's own history agree that evals must emerge
from observed failures, never from theory (Hamel Husain's evals FAQ; this repo's own rule that
a gauge needing new instrumentation is the wrong gauge).

Three layers, by when they run:

| layer | runs | what it is |
|---|---|---|
| pillar invariants | every `pytest`, free | deterministic properties of the maths core |
| golden decision set | at promotion time / weekly | recorded seams replayed through the real decide agent |
| gauges + sentinels + gate regret | continuously | drift watched on live behaviour, real outcomes |

### Layer 1 - the four pillar invariants (offline, every run)

Each guards one named class, each with its scenario table frozen and additive:

- **P1 Economic conscience** (extends the D-079 zoo + G1/G2/G2b): on fair pricing, zero size at
  every regime; size monotone in true edge; **gate opens ⇔ EV-after-costs > 0 under the
  declared decision measure, for drift AND vol theses**. This single invariant IS both "never
  pay for coin flips" and "never starve real edge" - the two goals that would otherwise be
  contradictory evals.
- **P2 One measure / seams refuse**: p and b provenance identical per decision; friction
  present in every path that can size (incl. fallback); upstream None + simulations present ⇒
  downstream refusal. Kills the I-40 class, not the instance.
- **P3 Capital protection paths**: the G4 path table as parametrized regression - whipsaw fires
  on schedule, uncorroborated artifact print does NOT fire, corroborated gap DOES, stale quotes
  hold while the underlying still watches, blind-mark positions are flagged at record time,
  the implicit time stop bounds the bleed.
- **P4 Learning integrity**: luck never promotes (attr gate); drawdown demotes; more evidence
  never means less size; fitted corrections are holdout-vetoed before use (the modelcal
  discipline, pinned); seeded lessons/constitution still recall (`lessons verify`).

### Layer 2 - the golden decision set (promotion-time, the missing middle)

The gap in the current strategy: nothing evaluates the DECIDE AGENT's judgement between the
deterministic core (pillars) and slow live outcomes (calibration). The published pattern fits
this system exactly (Anthropic "Demystifying evals for AI agents"; Braintrust agents guide):

- **20-50 recorded scenarios**, harvested from real cycles the journal already holds plus the
  gauntlet's synthetic boards: snapshot + inbox + option chain, market seams stubbed for
  deterministic replay. Early effect sizes are large, so small N genuinely suffices.
- **Grade the final action and end state, never the path or wording**: traded/declined, the
  structure class, size within the caps, exit rules parseable+observable+reachable, thesis
  band falsifiable, stated probability within a tolerance of the declared view's pop. All
  code-graded, binary. No LLM judge - every dimension here is checkable.
- **pass^k, not pass@k**: run each scenario k times (k=3 to start); ALL runs must grade.
  Reliability-critical agents need consistency, not best-of-k.
- **Balanced by construction: equal take-cases and decline-cases.** One-sided evals create
  one-sided optimisation, and this system has already lived both failure directions (18
  simulated / 0 traded on one side; the I-40 max-cap sizing on the other). The
  `[abstention-has-a-price]` lesson and the friction discipline become two halves of ONE
  balanced set instead of two contradictory pressures.
- **When it runs**: before promoting anything that touches the decide path (prompt change,
  lever promotion, model swap), and on a slow cadence (weekly) as a canary. Never in CI.
- **Frozen-holdout rule**: the Coach and any prompt iteration may tune against a DEV subset;
  the frozen subset is consulted only at promotion and its scenarios are never edited to make
  a candidate pass (dev/test split per Hamel's FAQ; the Coach never sees the frozen half).

Cost note: ~40 scenarios x 3 runs x a compacted decide cycle is a few dollars at current
per-cycle cost - cheap enough weekly, too dear per-commit, which is the right shape.

### Layer 3 - live (gauges, sentinels, gate regret)

Detailed in "The live side" below. One addition from the power arithmetic: detecting a 2%
forecasting edge at 80% power needs ~350 resolved binary forecasts (Foresight Arena, arXiv
2605.00420) - at this book's decision rate, outcome-based promotion is noise for months.
So promotion decisions run on process metrics (calibration trend, rule compliance, survival
rates); P&L and its cousins are lagging audits, logged with sample-size caveats. This is
D-045's own measurement, now with an external number agreeing.

Governance - how the suite stays small and un-gamed:

1. **Mutation rule, promoted from culture to law**: an eval ships only with proof it fails
   when its fix is reverted (the ledger already writes "verified by reverting the fix" on
   every I-3x - make it a requirement for eval admission). Not a named published LLM-eval
   practice (the research flagged it as folk/TDD hygiene) - it is OUR practice, and it has
   caught real gaps here, so it stays law locally.
2. **Frozen and additive**: scenario tables only ever gain rows. A row is never edited to make
   a candidate pass; behaviour changed on purpose = a new row plus an explicit note, the same
   rule as principles_testing non-negotiable #1.
3. **Admission requires an address AND an incident**: a new eval must name the single
   invariant class it guards (P1-P4, the golden set, or a new named pillar), must not restate
   an existing one, and must trace to an observed failure - never to theory. Mirrors "one
   definition" and the constitution's traces_to discipline; prevents sprawl and the pairwise
   contradictions sprawl breeds.
4. **Balanced pressure**: any eval that pushes toward an action (trade, close, decline) must
   land in a set that also contains its opposite direction, or be expressed as an exactness/
   band invariant. One-sided evals plus a self-improvement loop is the fastest route to
   always/never-trade drift.
5. **Saturated evals retire into the canary suite**: an eval at 100% for a long stretch stops
   being an improvement signal and becomes a fast regression canary (exactly what D-079's
   pinned tests are). It is never deleted for being boring.
6. **The measured/measurer split stays law** (notes/015): rewards and gauges are deterministic;
   nothing the Coach can move may score its own trial; gates cannot be levers while trials
   score through them; the Coach never sees the frozen half of the golden set.
7. **Scaffolds stay readable, invariants get pinned**: the zoo/gauntlet split earns its keep -
   the scaffold is the trader-readable table, the pinned test is the tripwire. Both, per D-079.
8. **Every eval run logs its own protocol**: prompt fingerprints (already journalled per
   decision - D-045 built this), cost assumptions, scenario-set version, and how many
   candidates were searched before this one (the walk-forward/multiple-testing checklist from
   the agentic-trading literature; D-052 one level up).

## The live side: drift is watched, not prevented by hope

Offline evals catch regressions; drift needs runtime eyes. The metric set has a named shape -
**one north star, few guardrails** (each extra guardrail measurably inflates false alarms):

- **North star: calibration skill** - the Brier/Murphy trend the system already computes,
  n_eff-weighted. The one number improvement is FOR.
- **Guardrails (must-not-degrade, both-sided where they push on behaviour)**: rule compliance
  (invalid + unobservable exit rules, from the exit_run heartbeat), the decline-rate BAND
  (both edges - always-trading and never-trading are the two measured drift directions),
  and cost/staleness (the existing cost ceiling and cal_age gauges).

Everything below feeds those, all from data that already exists (the gauge rule: new
instrumentation = wrong gauge):

- **`sizing.fallback_used`** per window - SizingDecision already knows it fell back; journal it.
  A rising count is the I-40 class resurfacing in production.
- **`exit.decisive_closes`** split corroborated/uncorroborated - the I-42 class trend.
- **`book.beta_delta_dollars` and `book.vega_dollars`** per snapshot (net_greeks + beta exist) -
  the concentration trajectory that decides whether a vega cap is ever earned.
- **Existing sentinels stand**: cost ceiling, churn, entropy floor, calibration collapse.
- **Gate regret** (designed in notes/015, unbuilt): rejected theses already resolve on the
  ledger; "we refused it and it would have held" scores gate thresholds against reality at zero
  capital cost. This is the correct LIVE eval for the G2 hurdle question - implement when
  rejected-thesis resolutions reach a scoreable count, and let it, not intuition, move gate
  parameters.

## The journey (optimize protocol, frozen set S1-S10 = gauntlet scenarios + regression guard)

| iter | candidate | vs frozen set | verdict |
|---|---|---|---|
| 1 | baseline (current) | fails S1-S9, passes S10 | incumbent by default |
| 2 | nine independent patches (previous critique list) | S1-S9 pass; S10 partial - EV hurdle re-stacks conservatism (D-076 class), nine local rules, three new tunables | KEPT (beats baseline); weaknesses become the target |
| 3 | **one measure + refusal propagates + corroborated exits + confession (R1-R4, F1-F2)** | S1-S9 pass; S8/S9 pass *by deletion* (no hurdle, no special case); S10 clean - vol_view=None is byte-identical, fallback strictly more conservative, gaps still fire | **KEPT - new incumbent** |
| 4 | iter-3 + heavy additions (vega cap, smile MC, escalating stops, LLM-replay CI) | no frozen-set gain; smile MC contradicts refusal stance; unmeasured gates; CI flake | REJECTED - one idea harvested (vega as GAUGE) |
| 5 | iter-3 + gauge harvest (fallback, decisive-close, book greeks) | unchanged on S1-S10; pure observability | KEPT (refinement) |

Stopped: plateau after iteration 4's rejection; iteration 5 marginal-accept. Winner: iteration
5's build - four rules, two small features, three gauges, one lesson, two wiki concepts, four
pillar evals with five governance rules.

## Implementation order (each step: failing test -> fix -> passing, per principles_testing)

1. R2.1 + R2.2 (fallback seam) - smallest diff, biggest risk closed. Pin in P2.
2. R4 (both confessions) - honesty, zero behaviour risk. Pin in P2/P3.
3. R3 (corroboration) - pin in P3 with the G4 table.
4. R1 (vol_view) - the profitability unlock. Pin in P1 (extend G2 sweep to exactness).
5. F1, F2, R2.3 - pin in P3, P1.
6. Gauges + lesson + wiki concepts + `report` wiring.
7. Gate regret, when rejected-resolution volume suffices.
8. Golden decision set: harvest from the journal + gauntlet boards, stub seams, code-grade
   actions, split dev/frozen. Gate: exists before the next decide-path promotion.

Rough cost: steps 1-2 are each an afternoon-sized diff; 3-5 a day each with their tables;
nothing here touches the Coach's lever space, so no trial interference. The golden decision
set is its own workstream (8): harvest scenarios from the journal, stub the seams, grade
actions - build it before the next decide-prompt promotion, not before the code fixes.

## Sources (fetched 2026-08-30; primary/vendor docs unless noted)

- Anthropic, "Demystifying evals for AI agents" - outcome/state grading, pass^k, balanced
  cases, saturated-evals-as-canaries, 20-50 tasks.
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- LangSmith trajectory-eval docs (final-response / single-step / trajectory split).
  https://docs.langchain.com/langsmith/trajectory-evals
- Braintrust agents best practices - snapshotted state, stubbed tools, harvest low-scoring
  production runs into golden datasets. https://www.braintrust.dev/docs/best-practices/agents
- OpenAI agent-evals guide (trace grading -> datasets + graders).
  https://developers.openai.com/api/docs/guides/agent-evals
- Hamel Husain, evals FAQ - error-analysis-first, dev/frozen split, binary grading, judge
  validation by TPR/TNR. https://hamel.dev/blog/posts/evals-faq/
- PostHog / Mixpanel on guardrail-metric sprawl and false-alarm inflation.
  https://posthog.com/product-engineers/guardrail-metrics
- Evidently / NannyML - monitoring tiers by label latency; CBPE for pre-label calibration
  decay. https://www.evidentlyai.com/ml-in-production/model-monitoring
- Anthropic Managed Agents cookbook - prompt-version pinning, promotion as deployment.
  https://platform.claude.com/cookbook/managed-agents-cma-prompt-versioning-and-rollback
- DataRobot champion-challenger; shadow-mode LLM rollout writeups.
  https://www.datarobot.com/blog/introducing-mlops-champion-challenger-models/
- Foresight Arena (arXiv 2605.00420) - Brier + Murphy decomposition as the standard; ~350
  resolved forecasts to detect a 2% edge at 80% power.
- "Agentic Trading" survey (arXiv 2605.19337) - 15 of 19 published LLM-trading evals
  irreproducible; reporting checklist (splits, costs, timing).
