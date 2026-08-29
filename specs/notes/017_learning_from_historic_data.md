# Learning from historic data - what is reachable, what it is worth, and what it already found

Research + brainstorm + evaluation, 2026-08-29. Question: can we test the system against
historical data and learn something real from it? **Answer: yes, further than expected - and the
investigation itself already produced a measured defect in a number the system treats as ground
truth.** Nothing here is built; this is the assessment and the plan.

Every capability claim below was verified by a live call, not read from documentation - the
discipline D-083/084/085 arrived at the hard way.

---

## 1. What is actually reachable (measured, not assumed)

| Source | Depth | Verified how |
|---|---|---|
| **Stock daily bars** (`get_stock_bars`) | **2016+** (10 years) | pulled SPY bars from 2016-01-04, 2020-01-02, 2024-01-02 |
| **Expired option contracts** (`get_option_contracts`, `status="inactive"`) | **Feb 2024+** | listed SPY contracts expiring 2024-02, 2024-06, 2025-06 |
| **Historical option OHLCV** (`get_option_bars`) | **Jun 2024+** (~2.3 yrs) | `SPY240621C00530000`: 15 daily bars, close 8.86 -> 14.36 |
| **Cached local closes** (`data/state/returns/`) | 56 tickers x 300 sessions | offline, free, no network |
| Also present, unexplored | `get_option_trades`, `get_stock_quotes`, `get_portfolio_history` | listed in the 72-tool surface |

**The decisive capability is historical option BARS for expired contracts.** That is what separates
a real backtest from a simulation: we can reconstruct a spread at the prices it actually traded at
and follow it to settlement.

### Proof of concept, run end to end

A bull put spread on SPY, entered 2026-06-15, expiring 2026-07-17, priced at real daily closes:

```
entry   sell 740P @ 6.83   buy 730P @ 4.87   ->  credit 1.96
expiry       740P @ 0.02        730P @ 0.01  ->  cost   0.01
REALIZED  +$195 per contract   (max profit $196, max loss $804)

our stack on entry day, using ONLY the 248 closes available then:
  bootstrap P(SPY >= 740 at expiry) = 74.3%
  actual SPY at expiry 742.15  ->  WIN (by $2.15)
```

Real fills, real settlement, real P&L, and the estimate made from a strictly truncated history.
The loop closes. **This is the single most important fact in this note: everything below is
buildable, not hypothetical.**

---

## 2. The thing that will ruin this if ignored: lookahead

Two distinct problems, and only one of them is an engineering problem.

**(a) Harness leakage - solvable by discipline.** Showing the model or the code anything dated
after the as-of date: a wiki dossier written later, news from after the date, `market_stats`
closes that run past the cut, `stale_after` computed from today, a ledger entry that already
resolved. Fixable with an as-of clock threaded through every read, and testable (assert no
artefact newer than the as-of date was touched).

**(b) Model memory - NOT solvable.** The LLM's training covers this period. Asked to forecast SPY
from 2026-06-01, it may simply recall what happened. This is the project's own `[premise]`
principle and D-081's finding ("never ask a model for a number it can only recall") arriving in a
new place. **Any LLM backtest over a period inside the training window measures memory plus skill
and cannot separate them by construction.**

The consequence shapes the whole design: **split the work by whether an LLM is in the loop.**

---

## 3. Brainstormed approaches, and what each is actually worth

### Tier A - deterministic replay. No LLM, therefore no contamination, at all.

The entire quantitative stack has no memory, so it can be replayed honestly over the full history.
Candidate questions, roughly in value order:

1. **Is the bootstrap base rate calibrated?** It is the muse's gate and the system's "honest odds"
   anchor. *Already run - see §4, and the answer is no.*
2. **Do the exit rules help?** They have **never fired in production** (I-9). A replay would
   exercise stop/target against hold-to-expiry across thousands of positions. Currently the single
   most unvalidated component in the system.
3. **Is `breakeven_vol` calibrated?** When the board says "wins if realized vol < 7.5%", does the
   trade win when realized comes in under 7.5%? Directly checkable.
4. **Does the conditional `payoff_ratio` (D-077/079) predict realized P&L?** Proven algebraically
   exact at fair value; never checked against actual outcomes.
5. **Does Kelly sizing beat flat sizing** under our own tier caps and friction, on realized paths?
6. **Is the friction model right?** Compare modelled round-trip cost against real bid/ask.

Cost: near zero (offline for 1 and 5, cheap network for the rest). Contamination: structurally
impossible. **This is where the value is.**

### Tier B - LLM replay. Contaminated; useful only with controls.

- **B1 anonymise.** Strip ticker and date; hand the model a normalised price series and derived
  features. It cannot recall "SPY in July 2026" if it does not know which name or when. Testable.
- **B2 post-cutoff only.** Restrict to dates after the model's training cutoff. Genuinely clean,
  but a small window and it shrinks every time a model is upgraded.
- **B3 measure the contamination first.** Run the same task named-and-dated vs anonymised. If
  skill collapses under anonymisation, the named result was memory. **This probe should be built
  before any Tier B result is believed** - it costs one experiment and prices everything after it.
- **B4 score the PROCESS, not the forecast.** Whether the agent verified its premise, cited a
  principle, stated a breakeven, respected the horizon window - all contamination-immune, because
  recalling the outcome does not tell it to follow its own method.

### Tier C - historical replay as a Coach trial generator

The Coach currently gets ~3 muse runs/day; today's 9-run experiment took hours and ended
undecided. A historical harness could run dozens of trials per minute. **But only for
contamination-immune rewards** - and gate survival is *partially* contaminated (a model recalling
the future can place bands that clear the base-rate window more reliably). B4-style process
rewards are the clean ones. Worth doing, after B3 has priced the leakage.

### Rejected outright

- **Feeding historical results into the agent's calibration sample.** They are not claims the
  agent made about an unknown future; scoring them as such is exactly D-080's defect (half the
  calibration sample was material the system had itself rejected). Historical results validate
  COMPONENTS. They must never touch `probability_stated`.
- **Optimising thresholds against 2024-2026.** That window is ~one regime (+29.4% annualised
  drift across our 56 names, measured). Tuning `BASE_PROB_FLOOR` to it is fitting a bull market,
  and the constitution's `[regimes]` principle says exactly this.

---

## 4. What the investigation already found, before any harness exists

Running the Tier A #1 question offline over the cached closes - **21,280 band-forecasts, 56
tickers, horizons 3/5/10 days, 5 band shapes, history sliced before every estimate so lookahead
is structurally impossible**:

```
RELIABILITY of the bootstrap base rate
  predicted      n    mean pred   realized      gap
  0.1-0.2    1,617      0.156      0.220     -0.065   underconfident
  0.3-0.4    6,729      0.351      0.347     +0.004   good
  0.7-0.8      989      0.753      0.572     +0.181   OVERCONFIDENT
  0.8-0.9    1,260      0.851      0.700     +0.151   OVERCONFIDENT
  0.9-1.0    1,894      0.965      0.891     +0.074
overall Brier 0.2118;  gap grows with horizon: 3d +0.020, 5d +0.033, 10d +0.041
```

**The bootstrap systematically overstates the chance a price stays inside a band, by 15-18 points
in the 0.7-0.9 region** - which is precisely the region a credit spread or condor lives in.

Decomposed by band shape (n=1,792 x 4):

```
  sym +-3%     real 0.414   predicted 0.537   +0.123
  sym +-5%     real 0.590   predicted 0.720   +0.130
  down <=-2%   real 0.329   predicted 0.306   -0.022
  up >=+2%     real 0.378   predicted 0.294   -0.084
```

Both one-sided bands come in MORE often than predicted while the middle comes in LESS: the modelled
distribution is too narrow at both tails.

**Two candidate explanations were tested and neither closes it** - recorded because a mechanism
that fails a cheap test is worth more as a rejected candidate than as a shipped fix (D-076's own
rule):

- **Block bootstrap** (contiguous 5-day blocks, preserving the volatility clustering the docstring
  admits IID resampling destroys): made it **worse**, Brier 0.2223 -> 0.2273. At a 3-7 draw
  horizon a 5-day block means 1-2 blocks per path, which collapses path diversity.
- **Trailing realized drift** fed to the existing `drift` parameter: helps the gaps (+0.123 ->
  +0.102, -0.084 -> -0.055) but Brier gets slightly worse (0.2225 -> 0.2255), because trailing
  drift is a noisy estimator. Drift is a minority of the effect, not the cause.

**Root cause not established, and the finding is recorded without one.** What is established: the
magnitude, the direction, the shape-dependence, and that it grows with horizon.

**Why this matters more than it looks.** The base rate is not decoration:
- `claimed_edge = stated - base`. An overstated base **understates the agent's edge** on any
  high-base-rate band - a measured, quantitative contributor to the stacked conservatism D-076
  found by reasoning (18 theses, zero traded).
- The muse's `BASE_PROB_CEIL = 0.90` rejects bands as "vacuous" using a number that is ~7-15
  points optimistic there.
- Range structures (condors, symmetric theses) are flattered by ~12 points, and short premium
  looking safer than it is happens to be the classic way to be carried out.

The docstring already declared this limitation honestly - *"IID resampling destroys
autocorrelation and volatility clustering... better tails than lognormal, still not truth."*
**Historical data converted a declared caveat into a measured magnitude.** That is the whole
argument for doing this work.

---

## 5. Scenarios simulated, and where each design breaks

| # | Scenario | Outcome |
|---|---|---|
| S1 | Replay a vertical at real historical prices | **Works** - proven above, real fills to settlement |
| S2 | Score the bootstrap over 21k band-forecasts | **Works, found a real defect** (§4) |
| S3 | Backtest exit rules vs hold-to-expiry | Buildable; needs daily option bars per leg. The highest-value untested component |
| S4 | LLM muse on a historical date | **Contaminated** - unusable without B3 first |
| S5 | Contamination probe (named vs anonymised) | Cheap, and it prices every Tier B result. Build before B |
| S6 | Coach trials on replayed history | Partially contaminated via the base-rate gate; use process rewards |
| S7 | Thin/illiquid contracts | **Real trap.** The 741P traded 322 contracts against the 740P's 6,046. Daily-bar closes are not fills; a spread reconstructed on an untradeable strike shows profit nobody could take. Filter on volume, and prefer round strikes |
| S8 | Close-to-close pricing overstates achievable P&L | **Real trap.** Bars give OHLCV, not bid/ask. Every backtested edge must be charged the friction model, and the friction model itself is unvalidated (Tier A #6) |
| S9 | 2024-2026 is one regime | **Real limit.** +29.4% annualised drift measured. Nothing tuned on this window generalises to a crash; report it as an in-sample result, always |

---

## 6. Evaluation and recommendation

**Do Tier A first, and specifically the exit-rule replay (S3).** It is the largest unvalidated
component in the system (never fired in production, I-9), the replay is contamination-free, and
the machinery to price it now demonstrably exists. Second: `breakeven_vol` and `payoff_ratio`
against realized outcomes - both are recent, both are load-bearing in the decision, neither has
ever met an outcome.

**Do not build Tier B before the B3 contamination probe.** An LLM backtest over the training
window that nobody has priced for leakage will produce an impressive, meaningless number, and
this project's whole method is refusing to believe those.

**The bootstrap finding (§4) needs an owner regardless of whether the harness is built** - it is
live, it is affecting real decisions today, and it was found in an afternoon. Recorded as I-29.

**What this is worth, honestly.** It does not give the agent calibration - only real forward
forecasts do, and the 68 pending ones land 08-31 to 09-03. What it gives is validation of the
machinery underneath the agent, on sample sizes three orders of magnitude larger than the live
record, at near-zero cost. Given the system currently has **one** resolved forecast, that is the
difference between a system whose components are argued for and one whose components are measured.
