---
title: "NVDA bull call spread"
position_id: pos_20260903_NVDA_bull_call_spread_7ab18bb3
date: 2026-09-03
time: "17:54:29.380890+00:00"
underlying: NVDA
strategy: bull_call_spread
status: opening
expiry: 2026-09-11
max_loss_usd: 5904.0
confidence: 0.46
decision_ref: jrn_20260903T175316Z_dec8a78e4
batch: bat_e9a83932dc01
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# NVDA bull call spread

Opened **2026-09-03T17:54:29.380890+00:00** — max loss $5,904.00, expiry 2026-09-11.

## The thesis

**Claim:** From about $230.2, NVDA should close between $232 and $245 on 2026-09-11 as post-earnings AI-demand support and the Hugging Face acquisition sustain modest upside, while a close below $225 would invalidate the continuation thesis.

**Resolves:** 2026-09-11, band [232.0, 245.0]

**Expected drift:** +1.0%


From about $230.2, NVDA should close between $232 and $245 on September 11 as post-earnings AI-demand support and the Hugging Face acquisition sustain modest upside. A trade below $225 invalidates the continuation premise; September 4 payrolls are acknowledged binary risk.

## Why this trade

Opened one position:

- **NVDA Sep 11 $230/$240 bull call spread**
- **Quantity:** 18 spreads
- **Filled debit:** **$3.15** per spread
- **Total debit / actual maximum loss:** **$5,670**
- **Maximum profit:** **$12,330**
- **Expiration breakeven:** **$233.15**

**Thesis:** NVDA closes $232–$245 by September 11, supported by post-earnings AI demand and the Hugging Face acquisition. Conservative assumed drift was +1%; modeled profit probability was 46% with positive estimated value after costs.

**Automated exits recorded:**
- Profit target: +50%
- P&L stop: -50%
- Underlying invalidation: below $225
- Time stop: one day before expiration

The $225 underlying stop confirms thesis failure but may not materially limit structural loss; the -50% premium stop is the primary loss control. Existing SPY position was left unchanged.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| NVDA 230/240 bull call spread | $328.50 | $671.50 | $-328.50 | 1.69 | **chosen** |
| NVDA 230/235/240 call butterfly | $90.50 | $409.50 | $-90.50 | 2.11 |  |
| NVDA 225/220 bull put spread | $-107.00 | $107.00 | $-393.00 | 0.30 |  |

## Sources

- **alpaca_news** — `inbox/new_20260903T175314Z_alpaca_news_9ef4ddea`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| buy | 18 | NVDA260911C00230000 |
| sell | 18 | NVDA260911C00240000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -50.0% |
| profit_target | basis position_mark, threshold 50.0% |
| time_stop | days_before_expiry 1 |
| underlying_stop | direction below, level 225.0 |

## Outcome

_Open - this section fills in when the position resolves._
