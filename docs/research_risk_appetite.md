# Research: a risk-appetite lever

> **AMENDED 2026-09-01 — this shipped as D-099, with four corrections.** The measurements below
> stand; they were correct for the design they tested. What changed, all of it measured against the
> real sizer and written up in [`plan_risk_appetite.md`](plan_risk_appetite.md) §1:
>
> 1. **One runtime clamp, not two.** `KELLY_CEILING` cannot fire — `max(TIERS.kelly) x
>    APPETITE_MAX = 0.25 x 2.0 = 0.50` exactly — so it is pinned as a test instead of carried as
>    dead code. §5's `FLOOR_CEILING` became *wrong* once the floor derived from the cap.
> 2. **§9's sequencing was wrong about I-69.** Fixing the shrink target is not a prerequisite: the
>    floor binds above Kelly at every rung, so its 3x span never reaches size. Do it on its own
>    merits.
> 3. **The floor is scaled once, THROUGH the cap** (`book_cap * SEED_SHARE`), not multiplied by the
>    appetite a second time — and the lever is a *parameter of* `assess`, never §3's
>    `with_appetite()` transform.
> 4. **§6's belief table was recomputed** under the shipped design; the conclusion holds (the
>    minimum is optimal to ~60% belief) but 1.0x is worse than it looks — a >20% drawdown becomes
>    more likely than not *even when the thesis is right*.
>
> §10's third open question — "`SEED_SHARE = 0.22` has never been fitted to anything" — is now
> load-bearing and tracked as **I-70**.

**Question.** Can one knob make this system take more risk (more profit, more losses) and less
risk (less profit, safer) — robustly, flexibly, and without adding entropy?

**Answer.** Yes, and it is small: one config number scaling two fields of one dataclass.
But it cannot ship first. The simulation found three things upstream of it, and a lever
added today would be a knob wired to nothing.

Evidence throughout is `tests/scaffold_risk_appetite.py`, which drives the **real**
`sizing.size_position` and `competence.assess` with a modified posture, over SPY's own
resampled return history at the production estimator's holdout-fitted inflation.

---

## 0. The methodological trap, stated first

The live 766/758 spread was bought for **$1.67** against a bootstrap fair value of **$2.45**.
Simulating it at its traded price hands the agent a 32% mispricing, and *every* setting looks
brilliant — the first version of this simulation showed a 0.25x-appetite book turning $100k into
$734k and I nearly believed it.

The legs are therefore **repriced to zero EV** under SPY's own history at zero drift, so edge
enters only through a stated drift. Verified in the scaffold header: EV/contract at zero drift is
**+$0.3** and P(profit) lands exactly on the break-even probability.

This matters beyond hygiene. At the traded price, full Kelly on the structure is **0.48**. Fair
priced, it is **0.075**. Every conclusion below turns on which of those two numbers is real, and
the earlier `scaffold_risk_posture.py` used the first one.

---

## 1. Three findings that change the design

### 1.1 The seed floor is the position sizer. Kelly and the ladder are not.

Full Kelly on a realistic claimed edge is **0.075**. At SCALE the tier multiplier is 0.138, so
Kelly asks for **1.04% of equity** — below the **2.2% `SEED_FRACTION`**. `sizing` takes
`max(kelly, floor)`, so the floor wins.

Doubling one quantity at a time, at SCALE:

| ×2 applied to | size | change |
|---|---|---|
| book cap (and the two caps under it) | 2.01% | **inert** |
| Kelly multiplier | 3.02% | +50% |
| seed floor | 4.27% | +112% |
| Kelly + caps — *the obvious proposal* | 3.02% | +50% |
| **Kelly + caps + floor** | **4.27%** | **+112%** |

A lever attached to caps alone moves **nothing**. This is the project's most expensive bug class
— the compactor, the cache, the shared session all shipped as code that ran and did nothing — and
a risk knob is a prime candidate for it.

### 1.2 The drawdown circuit breaker does not brake

`SEED_FRACTION` is one constant for all four tiers, and it binds at three of them. So demotion
changes the tier and not the size:

| | EXPLORE | ESTABLISH | SCALE | MATURE |
|---|---|---|---|---|
| size at neutral appetite | 2.01% | 2.01% | 2.01% | 2.26% |

An 11% drawdown demotes MATURE → EXPLORE and cuts the next trade by **13%**. The ladder is a
circuit breaker with no contacts, and it is exactly what an aggressive setting would rely on.

### 1.3 `shrink_probability` inverts below 50% (recorded as I-69)

The docstring says "pull toward the observed base rate"; `decisions.md` says so at D-013, D-047
and D-076; `Calibration.base_rate` is computed and displayed. The code hardcodes **0.5**.

Live base rate is 28%. Measured at n=29:

| stated | shrunk | |
|---|---|---|
| 20.0% | 26.9% | **raised** |
| 39.6% | 42.0% | **raised** |
| 65.0% | 61.6% | lowered |

For every claim below 50% — which is *every long debit spread*, the structure class this book
trades — the "shrink" makes the agent more confident and sizes it larger. Kelly on the live
structure is **0.111 / 0.075 / 0.035** depending on whether you shrink to 0.5, don't shrink, or
shrink to the base rate: a **3x span** set entirely by that one constant.

A lever multiplies whatever Kelly produces. Decide this first, or the knob amplifies a bias.

---

## 2. Design space

Seven dimensions of "risk appetite" in an options book, and what each is worth here:

| dimension | verdict |
|---|---|
| **size per bet** (Kelly ×, floor, caps) | **the lever.** The one theoretically-grounded growth/variance dial |
| **the EV gate** (`p > 1/(1+b)`) | **refuse.** See §4 |
| trade frequency above the gate | the LLM's prose, not arithmetic — reachable only through the prompt |
| concentration (per-name, per-factor) | already derives from the book cap since D-098; moves for free |
| structure choice (defined vs undefined risk) | out of scope: unbounded loss is refused for a Kelly reason, not a taste reason |
| stop tightness | couples the lever to the exit engine; see I-64 |
| drawdown response | *should* be automatic negative feedback — see §1.2, it currently isn't |

---

## 3. The recommendation

```yaml
trading:
  # 1.0 = the posture the ladder alone would choose. Clamped to [0.25, 2.0].
  risk_appetite: 1.0
```

```python
def with_appetite(p: Competence, a: float) -> Competence:
    a = min(2.0, max(0.25, a))
    return replace(p,
        kelly_multiplier=min(KELLY_CEILING, p.kelly_multiplier * a),   # 0.50 = half Kelly
        book_cap=min(BOOK_CEILING, p.book_cap * a))                    # 0.35 absolute
```

**Why this is low-entropy.** D-098 already made position cap, per-name cap and (per §5) the seed
floor all derive from `book_cap`. So one multiplication reaches every risk scope and they cannot
desynchronise. The lever is one config key, one function, two assignments.

**Why two clamps and not none.**

- `KELLY_CEILING = 0.50` — half Kelly captures ~75% of the growth for ~25% of the variance, and
  above it the curve is dominated by estimation error rather than edge. `sizing.py` already cites
  this.
- `BOOK_CEILING = 0.35` — an absolute share of equity in defined max loss that no appetite may
  cross. **The lever moves the growth/variance tradeoff; it must never move the ruin bound.**

**Why the range is asymmetric.** `[0.25, 2.0]` is two halvings down and one doubling up. That is
deliberate — see §6.

**Where it must not live.** Not a Coach lever, ever. The Coach's charter is that it touches data,
never "a gate threshold, sizing math, or a sentinel", and the measured/measurer rule (notes/015)
forbids anything the Coach can move from scoring its own trial. Risk appetite is the principal's
preference, not the agent's. The agent should *see* it in the prompt so its prose selectivity
aligns; it must never set it.

---

## 4. The asymmetry that decides the shape

Two things a lever *could* move look similar and are not:

- **Size on a +EV bet** — more return *and* more variance. A genuine preference: the operator
  picks a point on one curve.
- **The EV gate** — bets below `p > 1/(1+b)` have *lower* expected return *and* higher variance.
  There is no curve to sit on. It is strictly worse on both axes, and it breaks PILLAR-1, which
  pins the gate at exactly EV-after-costs > 0 under the thesis's declared measure.

So an "aggressive" setting that loosened the gate would not buy risk. It would buy losses.
Verified: maximum appetite on a structure with no claimed edge still returns **0 contracts** —
the gate is upstream of every appetite multiplication.

---

## 5. Prerequisite: derive the seed floor from the tier

The same move D-098 made for the other three scopes, at a share that leaves EXPLORE untouched:

```python
SEED_SHARE = 0.22        # 0.10 book cap x 0.22 = 2.2%, today's constant exactly
seed_fraction = book_cap * SEED_SHARE
```

| tier | floor now | floor derived |
|---|---|---|
| EXPLORE | 2.2% | **2.2%** (unchanged) |
| ESTABLISH | 2.2% | 3.3% |
| SCALE | 2.2% | 4.4% |
| MATURE | 2.2% | 5.5% |

An 11% drawdown then cuts the next trade by **63%** instead of 13%.

**But it is not a safety improvement on its own.** It *raises* the base, so swapped in at the same
appetite it loses more, brake and all. Monte Carlo, wrong thesis:

| config | median | 5th pct | mean DD | P(DD>20%) |
|---|---|---|---|---|
| constant floor, 2.00x | $64,815 | $35,344 | 47.3% | 99.0% |
| tier-derived, 2.00x | $60,963 | $33,620 | 50.9% | 100.0% |
| **tier-derived, 0.85x — matched peak size** | **$80,983** | **$63,239** | **27.9%** | **86.2%** |

At matched size the brake is worth a great deal: mean drawdown **47% → 28%**, 5th percentile
**$35k → $63k**. The derived floor buys *responsiveness*; the safety comes from responsiveness
plus a recalibrated neutral appetite. It must ship as a pair, not as a drop-in.

---

## 6. What the lever actually buys

500 paths × 50 trades, SPY's own returns, drawdown demotion live in the loop.

**Thesis right** (drift −0.3%, EV +$34/contract):

| appetite | median | mean log g | 5th pct | mean DD | P(DD>20%) |
|---|---|---|---|---|---|
| 0.25x | $103,592 | 0.033 | $95,473 | 4.2% | 0.0% |
| 1.00x | $114,364 | 0.130 | $80,397 | 16.4% | 24.4% |
| 2.00x | $124,413 | 0.224 | $62,211 | 30.9% | 84.8% |

**Thesis wrong** (drift +0.3%, EV −$43/contract):

| appetite | median | mean log g | 5th pct | mean DD | P(DD>20%) |
|---|---|---|---|---|---|
| 0.25x | $95,439 | −0.044 | $89,473 | 7.1% | 0.0% |
| 1.00x | $81,407 | −0.197 | $60,912 | 26.8% | 76.6% |
| 2.00x | $64,794 | −0.429 | $34,950 | 47.1% | 99.0% |

So the user's question answers cleanly: **2.0x buys +$10k of median upside when right and costs
−$17k when wrong.** The knob works in both directions and the downside grows faster — which is
Kelly's own fragility, visible in this book's own numbers.

### How to choose a setting

Expected log growth under a belief mixture — *how sure are you the edge is real?*

| belief q | 0.25x | 0.50x | 0.75x | 1.00x | 1.50x | 2.00x | best |
|---|---|---|---|---|---|---|---|
| 30% | −0.022 | −0.043 | −0.064 | −0.107 | −0.178 | −0.258 | **0.25x** |
| 50% | −0.006 | −0.011 | −0.017 | −0.042 | −0.083 | −0.128 | **0.25x** |
| 60% | +0.002 | +0.005 | +0.007 | −0.009 | −0.036 | −0.064 | **0.75x** |
| 70% | +0.010 | +0.021 | +0.030 | +0.024 | +0.012 | +0.001 | **0.75x** |
| 80% | +0.018 | +0.036 | +0.053 | +0.056 | +0.059 | +0.066 | **2.00x** |
| 100% | +0.034 | +0.068 | +0.100 | +0.122 | +0.154 | +0.195 | **2.00x** |

**At a coin flip on whether the edge is real, the optimal setting is the minimum.** That is the
honest reading for a book with 29 forecasts, zero attributed positions, and no resolved evidence
that its theses carry edge — which is where this system stands today. The lever's first
justified use is *downward*.

This is why the range is asymmetric: turning it down is nearly free (at 0.25x a real edge still
compounds while the wrong-thesis loss more than halves), and turning it up needs ~70%+ confidence
that the edge is real.

---

## 7. Edge cases and mitigations

| case | behaviour | mitigation |
|---|---|---|
| **appetite cut while the book exceeds the new cap** | refused on the book cap; existing positions untouched — sizing gates *new* risk and never liquidates | correct, but the cap is a *target* on the way down, not an invariant. **Must be reported** or an operator reads an over-cap book as a bug |
| appetite `0`, negative, or `100` | clamped to [0.25, 2.0] | clamp at the boundary, and log the clamp — a silently clamped input is a config the operator thinks they set |
| `position ≤ underlying ≤ book` under every appetite | **holds** at every rung × every appetite | free: all three derive from `book_cap`, so one multiplication moves them together |
| more evidence never means less size | **holds** at every appetite | preserved because appetite is a uniform scalar across tiers |
| max appetite at MATURE | Kelly ×0.446 (ceiling 0.50), book 35% (ceiling), one position 17.5% | both clamps bind and say so |
| 11% drawdown at max appetite | still demotes to EXPLORE — appetite cannot switch the ladder off | but see §1.2: the demotion must actually cut size, which needs §5 |
| max appetite, no claimed edge | **0 contracts** | the EV gate is upstream of every multiplication |

---

## 8. Deliberately rejected

- **A per-dimension knob set** (size / frequency / concentration / stops). Four knobs is four
  ways to produce a posture nobody chose — the exact failure D-076's constitution principle 4
  names. One scalar, and the other dimensions derive or stay fixed.
- **Letting appetite touch the EV gate.** §4.
- **Making appetite a Coach lever.** §3.
- **Gating on `effective_n`.** Still open as I-67, unchanged by this work.
- **Named postures** (`cautious`/`bold`) instead of a float. Aliases can be added later over the
  same number; introducing them first would put two representations of one setting on disk.

---

## 9. Sequencing

1. **I-69** — decide the shrink target. It moves Kelly by 3x and everything downstream multiplies
   it. Cheapest fix, largest leverage, and it is currently a code/intent divergence either way.
2. **§5** — derive `seed_fraction` from the tier. Without it the ladder is decorative, the
   drawdown brake has no contacts, and the lever needs a third field to bite.
3. **§3** — add `risk_appetite`. Now one number, two fields, and it reaches everything.
4. Recalibrate the neutral default against §5's raised base, then set it from §6's belief table.

Steps 1 and 2 are worth doing whether or not the lever is ever built.

## 10. Open questions

- The pooled 28% base rate mixes claim types with genuinely different natural base rates. A
  per-metric base rate would be better and is more work; is it worth it? (I-69)
- `SEED_SHARE = 0.22` reproduces today's EXPLORE exactly, which makes it a safe default and an
  unexamined one. It has never been fitted to anything.
- The Monte Carlo assumes IID trades. Real books cluster — a wrong thesis tends to be wrong
  across several positions at once, which makes every drawdown figure here optimistic.
- 50 sequential trades is ~6 months at this book's rate. The competition horizon is days, so
  these are asymptotic properties, not a forecast of the run.
