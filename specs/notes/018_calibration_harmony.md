# Calibration harmony - every load-bearing number earns a measured reliability

Design session 2026-08-29, following notes/017's finding (I-29: the bootstrap base rate is
overconfident 15-23pp where credit spreads live). Question: what is the *systemic* lesson, and
how does the system find harmony across its calibration, its learning, and its activity?
**Status: designed via the optimize loop below, winner BUILT and live (D-089).**

---

## The disharmony, named precisely

The system runs three layers that each produce or consume probabilities:

1. **Model layer** - bootstrap base rates, lognormal grids, breakeven vol, payoff ratios,
   friction. Deterministic, dense, and - until I-29 - *never scored against reality*.
2. **Agent layer** - stated probabilities from LLM roles. Scored by `calibration.py` against
   live resolutions. Honest but starved: n=1 resolved, 68 pending.
3. **Policy layer** - gates and thresholds (`BASE_PROB_FLOOR/CEIL`, shrinkage, tiers, exit
   rules) that consume the first two as if they were true.

The errors compound in one direction. D-076 found it qualitatively: four defensible haircuts
multiply into a structural no (18 theses, 0 traded). I-29 made one link quantitative: an
overstated base **understates claimed_edge** on every high-base band, and the vacuity ceiling
rejects bands using a number that is 15-23 points optimistic. Meanwhile the understated tails
auto-reject breakout theses at the lottery floor. **The system was refusing work partly because
its own ruler was wrong - and fewer theses means fewer resolutions, which starves the agent's
calibration, which keeps sizing at the floor. Disharmony is a starvation loop.**

## The principle that generalises

**Every load-bearing number should be scored against the densest evidence stream that can score
it honestly, and the correction must carry provenance and be auditable by the next-slower
stream.** The system already does this in three places without naming it:

| Quantity | Evidence stream | Cadence | Mechanism |
|---|---|---|---|
| Agent probabilities | live resolutions | days | `calibration.py`, shrinkage |
| Memory blocks | scored outcomes | days | elfmem Beta posteriors |
| Coach variants | paired gate trials | hours | trial posteriors (D-088) |
| **Model distribution** | **historic replay** | **minutes, 21k samples** | **MISSING until D-089** |
| Exit rules / friction | historic replay | minutes | still missing (notes/017 Tier A) |

The model layer was the one producer whose numbers nothing ever audited - and it is the layer
everything else stands on. The historic-replay stream (no LLM, lookahead structurally
impossible, thousands of samples) is precisely suited to it.

## The optimize loop

**Goal:** correct the measured model-layer defect in a way that increases system harmony -
throughput, calibration, sizing feeding each other - without introducing a new unaudited number.
**Fitness:** correctness of functional form / out-of-sample honesty / blast-radius safety /
harmony effect / simplicity.

**Frozen scenarios:**

| ID | Scenario |
|---|---|
| F1 | Regime shifts after fitting (2024-26 is one +29%-drift regime) |
| F2 | Double correction: the agent later learns to discount the base too |
| F3 | Consumer coverage: base feeds muse gates, EV grids, tail_gap, sizing |
| F4 | Harmony: does it unstick D-076's over-caution without opening floodgates? |
| F5 | Overfitting the correction itself |
| F6 | Corrupt/stale/insane correction artifact |
| F7 | A Coach experiment is OPEN while the reward machinery changes |
| F8 | The correction must itself be auditable forward (68 pending resolutions) |

**Iteration 1 - baseline: record I-29, change nothing.** Fails F4 outright - the ruler stays
wrong and the starvation loop keeps turning. Safe, honest, inert. *Incumbent to beat.*

**Iteration 2 - report-only** (show the agent "your 75% base is historically 57%"). Respects
D-009, zero mechanical risk - but the defect's main consumers are **gates in code** (F3): the
vacuity ceiling and lottery floor never read prose. Fixes the judgment path, leaves the
mechanical path wrong. *REJECTED as the whole answer; kept as a component.*

**Iteration 3 - binned p->p reliability map.** Directly targets the measured curve. But the
shape decomposition kills it: at the same predicted p, symmetric bands are OVERstated while
one-sided bands are UNDERstated - one map per probability cannot tell them apart and would
correct breakout bands the wrong direction. Also ~10 fitted numbers (F5). *REJECTED - wrong
functional form for the measured signature.*

**Iteration 4 - fitted variance inflation, holdout-vetoed, muse-first.** The signature (middle
too high, both tails too low) is exactly what a too-narrow distribution produces, so widen it:
scale demeaned returns by k, recenter the martingale at k². One parameter per horizon (F5).
**Grounding lever, run before believing it:** fit on the first 60% of history, validate on the
last 40%, plus a ticker split:

```
             train k*   holdout Brier      0.7-0.9 bin gap (holdout)
   3d          1.30     0.2160 -> 0.2021      +0.227 -> +0.100
   5d          1.30     0.2353 -> 0.2174      +0.238 -> +0.156
  10d          1.25     0.2161 -> 0.2097      +0.152 -> -0.004
  ticker split (fit even, test odd): better at every horizon there too
```

Improves out-of-sample on both split types, every horizon - where the block bootstrap and
trailing drift (notes/017) both failed. The residual up-tail gap is the *deliberate* demeaning:
direction belongs to the agent's stated view, so that gap is where the agent lives. *KEPT.*

**Iteration 5 - root-cause bootstrap redesign** (regime-conditional resampling, GARCH-style).
Two mechanism hypotheses already failed cheap tests; cost unbounded, window 6 days. *REJECTED
for now - I-29 stays open on root cause, with the measured correction in place.*

**Iteration 6 - a general "calibrated quantity" framework.** One abstraction wrapping every
number with (raw, correction, provenance, reliability). *REJECTED - machinery before a second
instance, this project's standing rule. The PATTERN is this note; the second instance (exit
rules) should be built concretely too, and only then does a framework earn consideration.*

**Journey:** 1 incumbent -> 2 partial (kept as component) -> 3 rejected (form) -> **4 KEPT,
winner** -> 5 rejected (cost/uncertainty) -> 6 rejected (premature abstraction). **Stopping
reason: goal reached** - the winner passes every frozen scenario (see mitigation table) and is
validated on held-out data twice.

## The winner, as built (D-089)

- `bootstrap_factors(..., inflate=1.0)` - at 1.0 byte-identical to before (tested); inflation
  scales demeaned returns and recenters the martingale; same seed draws identical paths at
  every k, so raw-vs-calibrated is paired, not noisy.
- `fit_band_inflation()` - pure, holdout has the **veto** (an in-sample-only k ships as 1.0);
  property-tested: detects autocorrelated data, refuses to hallucinate on IID data.
- Artifact `data/state/model_calibration.json` with provenance, holdout scores, bounds.
  Loader clamps to [1.0, 1.5] and fails safe to 1.0 on absence/corruption/insanity (F6): a fit
  wanting k=3 is evidence of something structural, not a bigger knob.
- **The muse consumes it** - the measured defect site - and records `base_inflate` on every
  verdict and journal row, so the forward audit can score calibrated-vs-raw when resolutions
  land (F8). Fitted live: k = 1.30/1.30/1.25 at 3/5/10d.
- The EV grids, tail_gap and sizing deliberately still run raw (F3): apply at the measured
  site, validate forward, then extend. tail_gap in particular MUST stay raw - it compares
  bootstrap tails to lognormal tails, and inflating one side would manufacture permanent
  disagreement.
- Coach gauges `model.inflation_5d` and `model.cal_age_days` put the correction on the report's
  trajectory; `trdrbot modelcal [fit]` is the operator surface.

**Measured live effect:** a SPY 5d symmetric band read 97.3% raw -> 91.9% calibrated (below the
vacuity ceiling: now carries information); an upside breakout read 5.6% raw -> 10.2%
(crosses the lottery floor: now survives to be judged). Both movements are in the direction
D-076 said the system needed - **more honest throughput, not looser standards: the gates are
unchanged, the number they read just stopped lying.**

**Edge-case mitigations (F1-F8):** F1 regime - artifact age is a gauge, refit is one command,
and the forward audit (below) is the drift detector; a correction fitted on trailing data that
stops working on live data IS the regime signal, feeding `[regimes]`. F2 double-correction -
one owner (the estimator), applied at one site, `base_inflate` recorded so nothing downstream
can correct blind. F7 - the open muse experiment's arms both face the changed gates equally, so
the trial stays unbiased between arms; noted in D-089. F4 floodgates - the gates themselves are
untouched, and DSR still counts every trial.

## The harmony flywheel this is part of

```
historic replay (dense, honest)          live forward record (slow, true)
        |                                          ^
        v                                          |
  model corrections  -->  honest gates  -->  more surviving theses
        ^                                          |
        |                                          v
  Coach gauges/refit  <--  resolutions  <--  calibration + gate regret
```

Each stream audits the faster one: history fits the model correction; live resolutions audit
the correction AND the agent; gate regret (D-081) audits the thresholds; the Coach watches all
of it as gauges and runs the trials. The self-improvement claim stops being a slogan when every
arrow in that loop is a mechanism that exists.

## Roadmap, in value order

1. **Forward audit of the correction** - when the pending muse resolutions land (08-31+), score
   `base_prob` (calibrated, recorded with `base_inflate`) as a predictor vs what raw would have
   said. The data is being recorded as of today; the join is one script.
2. **Exit-rule replay** (notes/017 S3) - the largest never-validated component; the same
   pattern: dense historic stream, correction-or-confidence out, forward audit in.
3. **Friction model vs real bid/ask** - the number every edge is charged.
4. **Weekly refit owned by the Coach** - refit as a pulse step behind a sentinel (a refit that
   moves k by more than ~0.1 pauses and flags rather than applies). Deferred: autonomy over a
   live estimator input deserves its own decision record.
5. **Contamination probe before any LLM replay** (notes/017 B3) - unchanged.

## What was deliberately not done

No change to gates or thresholds (the numbers they read changed, honestly). No touch to agent
calibration (D-080's lesson: historic results are not the agent's claims). No framework. No
root-cause claim - I-29 stays open, saying exactly what is and is not known.
