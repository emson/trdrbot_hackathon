# Trading Techniques Review — what we researched, and what we should do about it

Consolidated from two web research sweeps run 2026-08-27: one on **options strategy technique**,
one on **systematic/quant practice** (sizing, evaluation, risk, forecasting). This is the durable
record — the raw briefs existed only in a session transcript.

Every item below carries a verdict. The bar is this project's own: does it change a decision, can
it be computed deterministically, and is it meaningful at our sample size (currently **n=0
resolved theses**, 1-5 concurrent defined-risk positions, 2-10 DTE, ~$100k)?

**Read the "do not build" list first.** It is longer than the build list, and the discipline it
represents is worth more than any single technique on it.

---

## A note on source quality

The options sweep flagged that a large share of 2026 search results are **AI-generated affiliate
content emitting confident, unsourced statistics** — it named FlashAlpha, MenthorQ, fattail.ai,
quantwheel, optionspilot, daystoexpiry, apexvol, strike-watch, optionx.trade, tradeedgepro. Two
examples it declined to encode: a precise "theta-to-gamma ratio 0.8 at 60 DTE / 3.5 at 1 DTE"
table, and "weeklies Sharpe 0.8-0.9 vs monthlies 1.0-1.2". Neither cites a study.

The trustworthy non-academic sources were **Moontower** (Kris Abdelmessih, ex-market-maker),
**OptionMetrics research** (Garrett DeSimone), and arXiv preprints. Broker content (tastytrade,
IBKR, Schwab) is mechanically correct but commercially motivated on anything involving trade
frequency.

---

## ALREADY BUILT — the research validates what we have

Worth recording, because it bounds how much is genuinely missing.

| We have | Research says |
|---|---|
| Fractional Kelly gated on measured calibration | Correct. Full Kelly gives a 1/3 chance of halving the bankroll before doubling; Kelly systematically **overbets high-win-rate negatively-skewed payoffs** — exactly a credit spread |
| Bootstrap MC from real returns | This is the *real-world* measure; keep it strictly separate from anything IV-derived (*risk-neutral*). The **gap between them is the risk premium** |
| Portfolio at-risk cap + per-underlying cap | Right shape. Gap: does not catch correlated names or same-direction vol bets (see #8) |
| Drawdown de-risking from a high-water mark | This *is* TIPP (Time-Invariant Portfolio Protection). Steal nothing further from CPPI |
| Brier + Murphy decomposition | Was **biased against us** at small n — already fixed, D-050 |
| Competence ladder keyed on demonstrated skill | Validated: past performance in domain is the strongest predictor of future forecast accuracy (GJP year-to-year correlation 0.65) |
| Transaction cost from real bid/ask | Correct, but model the **exit** at a stressed spread, not the entry spread (see #5) |

---

## BUILD NOW — cheap, decision-changing, and fixes something real

### 1. Volatility clock (business-day weighting) — **highest priority**
Black-Scholes counts calendar days; volatility does not accrue over a weekend. Professionals
weight: business day 1.0, weekend/holiday 0.5, overnight 0.25 — roughly a 308-day year.

**Why it is first-order for us:** Friday close to Monday open is 2.25 calendar days but ~1.25
vol-clock days — a 33% error. On 30 DTE that is a rounding error; **at our 2-10 DTE it dominates**,
and it corrupts every greek, every cross-expiry IV comparison, and the expected-move number the
agent compares its thesis band against. An unadjusted clock manufactures a spurious IV jump every
Monday.

Independent corroboration: DeSimone (OptionMetrics) tested SPX 1DTE put-writes by weekday, Mar
2018 – Sep 2025. Removing Friday→Monday positions cut cumulative return from 28.07% to 8.94% —
**about two thirds of all profit came from weekend-spanning trades.**

*Verdict: BUILD. Half a day. Corrects every downstream number.*

### 2. Daily gamma breakeven — one line, guards the commonest error
`breakeven_move = sqrt(2 · |theta_per_day| / |gamma|)`, from the Black-Scholes identity
`theta ≈ -½γσ²S²`.

Converts the whole greeks vector into **one number comparable against the underlying's typical
daily move**. A short position whose breakeven is below the name's usual daily range is a losing
trade however attractive the credit looks. This is the cleanest guard against "high credit, high
IV rank, therefore sell" — which is precisely the reasoning our agent has to resist every cycle.

*Verdict: BUILD. We already have theta and gamma. Hours.*

### 3. Unconditional forecast logging — **the highest-leverage item for us specifically**
Forecast-level observations are far cheaper than trade-level ones. The agent can forecast
outcomes for setups it **declines** to trade, forecast intermediate checkpoints on open
positions, forecast realised-vs-implied vol, forecast whether its own exit rule will fire — each
a resolvable binary at **zero capital risk and zero execution cost**.

Why this matters more here than anywhere else: we are at **n=0** and the honest thresholds are
brutal — ~50 resolved forecasts before calibration is *measured* rather than guessed, 152 to
distinguish a 60% hit rate from a coin flip. At 1-5 concurrent positions, trade-level n will
never get there. Our agent has already declined ~10 times with detailed, falsifiable reasoning
that we simply threw away.

*Verdict: BUILD. This is the only realistic path to a meaningful calibration record.*

### 4. Pre-registration ledger — cannot be backfilled
Append-only record of **every** thesis generated, including declined ones, with its falsification
criterion written *before* the outcome.

The LLM-specific blind spot: a human quant tests ~20 ideas a year; an LLM generates 200 plausible
theses in an afternoon and silently discards the ones that look bad. Under a *true* Sharpe of
zero, the expected maximum Sharpe across N filtered trials is 1.19σ at N=5, **1.90σ at N=20**,
2.53σ at N=100. Our competence ladder would promote that. The ledger supplies the trial count N
that makes the Deflated Sharpe Ratio computable later; without it, DSR is uncomputable and the
ladder is unprotected.

We already journal `research_rejected` and every no-op decision — this is mostly **formalising
what we half-have**, and it merges naturally with #3.

*Verdict: BUILD. Cheap, and the deadline is real: it cannot be reconstructed retroactively.*

### 5. Chain arbitrage validator — a free data-quality gate
Before trusting any chain: vertical-spread monotonicity, butterfly convexity, and **calendar
variance monotonicity** (total implied variance must be non-decreasing in T).

**This is our failure class.** Stale quotes, crossed markets and bad wing IVs are described as the
number-one silent killer of systematic options agents — and silent data corruption is exactly what
has bitten this project repeatedly (stale bars, the empty price map, the SIP feed). The checks are
arithmetic, catch the problem before it poisons greeks and MC, and cost nothing.

Also from this item: model the **exit** at a stressed spread. High-win-rate defined-risk strategies
are exceptionally sensitive to exit slippage because losing exits happen when spreads are widest;
modelling entry costs only systematically overstates edge.

*Verdict: BUILD. A day, and it defends the class of bug we keep hitting.*

---

## BUILD SOON — real value, more work

### 6. Event variance extraction
Variance is additive in time, volatility is not:
`IV_total²·T_total = IV_diffusive²·T_normal + IV_event²·T_event`. Solve for the event vol, convert
to an implied event move.

Worked example: 40 business days, IV 36%, base 24% annualised, one earnings day inside →
implied event move ≈ **8.6%**, meaning that single day is **57% of total straddle variance while
being 2.5% of the days**.

At our tenor a single earnings or CPI print is often the majority of the variance being bought or
sold. Without decomposition we cannot compare IV across expiries or names, compare IV to our
realised-vol forecast, or ask whether the implied event move is rich against the name's own
history. Academic backing (Zhong, arXiv 2606.12872): adding an explicit event jump cut IV MAE
from 0.108 to 0.097 on SPX across 101 events — and, importantly, **priced scheduled risk is
variance/convexity, not directional skew**. So trade events with vol structures, not directional
ones.

*Verdict: BUILD after the Tier-1 items. Probably the highest-value new capability we lack.*

### 7. IV versus a realised-vol *forecast*, replacing IV level/rank
IV rank says where IV sits versus its own history; it says nothing about whether IV exceeds
*expected future* realised vol, which is the actual edge. Use `IV(matched tenor) / forecast_RV`.
Yang-Zhang and Garman-Klass (OHLC-based) beat close-to-close historical vol; **VIX9D outperformed
VIX30 for short-dated strategies**.

*Verdict: BUILD. We have the OHLC bars. Calibrate our own thresholds — the widely-quoted
1.15/0.85 buy/sell cutoffs are vendor heuristics from a firm selling the forecast.*

### 8. Beta-weighted portfolio delta + aggregate greek limits
Our per-underlying cap does not stop three positions in NVDA/AMD/AVGO, or three short-vol bets
across different tickers. Beta-weight every delta to SPY, aggregate, enforce a band, and check
**post-trade** portfolio greeks before opening anything.

Correlations converge toward 1 exactly when it hurts: rolling pairwise correlation across S&P
sector ETFs sits at 0.40-0.50 in calm markets and hit **0.83 (2008), 0.92 (euro crisis), 0.92
(Mar 2020)**.

*Verdict: BUILD. This is the largest remaining gap between "five sound trades" and "one
concentrated bet that all loses on the same day".*

### 9. SPAN-style scenario grid and Expected Shortfall
Replace/augment the flat at-risk cap with full revaluation over a fixed grid: spot shocks crossed
with IV shocks, worst case and mean-of-worst-5% reported. SPAN itself uses 16 scenarios.

VaR and parametric measures are simply wrong for options — P&L is not linear in the underlying, so
the loss distribution is not characterised by mean and variance. ES is also sub-additive, so it
correctly credits diversification. Basel's FRTB replaced 99% VaR with 97.5% ES for internal models,
effective Jan 2025.

**Add one column the standard grid lacks: a correlated shock** — every underlying moved the same
signed amount with IV up across the board. That handles correlation without estimating a
correlation matrix, which at 1-5 positions we have no business doing.

*Verdict: BUILD. Trivially cheap at 5 positions, and it is the honest answer to "how bad can this
get".*

### 10. Exit-cost-aware close rule (replacing any fixed profit target)
Close when `E[remaining P&L from MC] < expected round-trip exit cost + a risk charge for remaining
tail exposure`. A computed decision rather than a convention — and we already have the MC.

*Verdict: BUILD. See the "do not build" entry on the 50%/21-DTE rule for why the conventional
alternative is wrong for us.*

---

## LATER — right idea, wrong sample size today

| Technique | Why later |
|---|---|
| **MinTRL / PSR as the promotion gate** | Replaces our arbitrary n≥5/15/40 with a threshold computed from the measured edge and its shape. Needs a trade history to compute. **Carries a genuinely surprising corollary worth acting on now** (see below) |
| **Deflated Sharpe Ratio** | Needs the pre-registration ledger populated first |
| **CUSUM on live performance** | Detects slow edge *decay* where our drawdown trigger only catches fast losses. Complementary, not redundant. ~30 trades |
| **Bootstrap risk-of-ruin** | Resample our own R-multiples. Honest at ~30 trades, misleading before |
| **Meta-labeling** | Maps almost exactly onto our architecture (thesis = primary model, calibration/attribution = secondary). Needs *hundreds* of labelled signals |
| **Risk-neutral density extraction** | Replaces lognormal PoP with the market's actual distribution. Real maths, but uncertain benefit over our existing bootstrap — test before building |

**The MinTRL corollary worth acting on immediately:** positive skew *sharply reduces* the sample
needed to validate an edge. At per-trade Sharpe 0.25, a positively-skewed structure needs **28
trades** to validate; a negatively-skewed one needs **64**. That is a statistical-learning
argument for preferring long-convexity/debit structures over premium selling, entirely independent
of the usual risk argument — and it matters most for an agent that must *earn* its evidence
before it is allowed size. Worth putting in the prompt now, at zero cost.

---

## DO NOT BUILD — and why

The most valuable section. Both sweeps independently reached most of these.

| Rejected | Reason |
|---|---|
| **Risk parity / ERC / HRP** | Solves a 50-500 asset problem we do not have. Unstable with few assets and few observations; HRP's single-linkage clustering *concentrates* weight — the opposite of the intent |
| **CPPI with a formal floor** | The guarantee is void under gap risk, which is precisely what an options book carries, and continuous rebalancing is uneconomic at $100k. We already have TIPP's useful half |
| **HMM regime models** | Excessive switching from geometric-sojourn misspecification, plus an easy and fatal error: evaluating on **smoothed** state probabilities (which use the future) rather than filtered. The clean charts in the literature are often look-ahead bias |
| **Regime-conditional position sizing** | Divides an already-fatal sample by k. With 20 trades and 3 regimes that is ~7 observations each. **The most seductive curve-fit available to us.** Record regime as a covariate; do not let it modulate size |
| **Extremising aggregated forecasts** | Evidence genuinely mixed — small gains usually, **large losses sometimes**. Wrong asymmetry for a trading agent |
| **Credit-vs-debit branching logic** | Put-call parity: a bull put and bull call spread at the same strikes are synthetically equivalent — same theta, same vega, same R:R. "Credit spreads have better theta" is **false**. Branch on strike selection and which side has the tighter market instead |
| **Skew-driven structure selection at 2-10 DTE** | Quantified: moving skew from the 25th to 75th percentile changed a 60-day QQQ put spread by ~7% (33.8% vs 31.5% implied probability), and near-dated sensitivity is *smaller* still — "paying an extra commission charge". Build skew metrics as **diagnostics**, never as structure selectors at our tenor. Broken-wing butterflies justified by "harvesting skew" are a rationalisation for a different strike bet |
| **The 50%-of-credit / 21-DTE management rule** | Contested even on its own turf — the best independent test (SPX 16-delta strangles, 2001-2020) found the *passive* version beat the managed one on both CAGR (5.46% vs 4.44%) and Sharpe (0.67 vs 0.52), before slippage, which biases toward the active version. And a 21-DTE stop is **undefined when you enter at 7 DTE**. Popularised by a broker with a direct interest in trade frequency. Use #10 instead |
| **Rolling rules** | Every source was broker or content-farm output with no backtests. The one principle worth keeping is logically forced rather than empirical: **a roll is a new trade** — evaluate it through the identical entry gate, and if it would not pass as a new position, close instead |
| **GEX / dealer gamma positioning** | Mechanism is real but dealer sign is not observable from public data; every published series rests on unverifiable assumptions and is sold by subscription |
| **Post-earnings announcement drift** | Actively contested (may have died in non-microcaps by 2006), and even where it survives it is a multi-week equity effect — not expressible in 2-10 DTE options after two-legged spread costs |
| **Delta-hedging bands as hedge triggers** | Share-hedging costs exceed the benefit at our size, and defined-risk structures already cap the exposure. Use the band formula as an **adjust-or-close trigger** instead |
| **Deep-learning regime/return models** | Unvalidatable at our sample size; DSR would eat any result |
| **Chasing P&L statistical significance** | 64-371 trades depending on skew and edge. At 1-5 concurrent positions that is 1-3 years. Optimise the metrics that actually converge |

---

## The organising principle across both sweeps

**Optimise the metrics that converge inside the agent's lifetime.**

| Metric | Observations to be meaningful |
|---|---|
| Execution cost / implementation shortfall | ~5 |
| Process compliance (simulated before recording, stop set, etc.) | ~10 |
| Calibration, measured rather than guessed | ~50 |
| Hit rate 60% distinguishable from 50% | **152** |
| Per-trade Sharpe > 0 at realistic edge | **64-371** |

P&L is the last of these to converge and the first everyone reaches for. Everything in the BUILD
NOW list targets the top of that table — which is also why **unconditional forecast logging (#3)
is the single highest-leverage item**: it manufactures cheap observations of the one thing that
actually gates our size ladder.

---

## Sources worth keeping

**Options:** [Moontower — weekend theta](https://blog.moontower.ai/weekend-theta/) ·
[extracting earnings from the vol term structure](https://blog.moontower.ai/how-an-option-trader-extracts-earnings-from-a-vol-term-structure/) ·
[straddles and win rates](https://moontowermeta.com/straddles-volatility-and-win-rates/) ·
[a sense of proportion around skew](https://moontowermeta.com/a-sense-of-proportion-around-skew/) ·
[OptionMetrics — Selling Saturdays](https://optionmetrics.com/blog/selling-saturdays-weekend-risk-premia-in-1dte-put-write-strategies/) ·
[Zhong, scheduled event risk (arXiv 2606.12872)](https://arxiv.org/html/2606.12872v2) ·
[Wysocki, Sizing the Risk (arXiv 2508.16598)](https://arxiv.org/pdf/2508.16598) ·
[Wizman et al., arbitrage removal to density extraction (arXiv 2605.22792)](https://arxiv.org/html/2605.22792) ·
[Blom, does managing winners add value](https://steadyoptions.com/articles/does-%E2%80%9Cmanaging-winners%E2%80%9D-add-value-to-short-strangles-r618/)

**Systematic:** [Bailey & López de Prado, Sharpe Ratio Efficient Frontier](https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf) ·
[Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) ·
[Ferro & Fricker, bias-corrected Brier decomposition](https://empslocal.ex.ac.uk/people/staff/ferro/Publications/ferro-fricker2012copyright.pdf) *(already applied — D-050)* ·
[Dimitriadis, Gneiting & Jordan, stable reliability diagrams (PNAS 2021)](https://www.pnas.org/doi/10.1073/pnas.2016191118) ·
[Harvey, Liu & Zhu, …and the Cross-Section of Expected Returns](https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF) ·
[AI Impacts, good forecasting practices from the GJP](https://aiimpacts.org/evidence-on-good-forecasting-practices-from-the-good-judgment-project/) ·
[CFTC, SPAN margin system](https://www.cftc.gov/sites/default/files/files/tm/tmspan_margining043001.pdf) ·
[Man Group, the case for Expected Shortfall](https://www.man.com/insights/covering-your-tail-expected-shortfall)
