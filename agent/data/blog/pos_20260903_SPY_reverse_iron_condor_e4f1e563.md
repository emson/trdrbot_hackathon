---
title: "SPY reverse iron condor"
position_id: pos_20260903_SPY_reverse_iron_condor_e4f1e563
date: 2026-09-03
time: "13:59:29.067300+00:00"
underlying: SPY
strategy: reverse_iron_condor
status: opening
expiry: 2026-09-11
max_loss_usd: 5888.0
confidence: 0.58
decision_ref: jrn_20260903T135813Z_dec15332d
batch: bat_847cb9309e80
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# SPY reverse iron condor

Opened **2026-09-03T13:59:29.067300+00:00** — max loss $5,888.00, expiry 2026-09-11.

## The thesis

**Claim:** From 769.2, SPY should realize about 12% annualized volatility through September 11 as payrolls and rate/geopolitical risks break the recent low-volatility consolidation, with a mild downside bias and a September 11 close between 755 and 775.

**Resolves:** 2026-09-11, band [755.0, 775.0]

**Expected drift:** -0.6%

**Vol view:** 12.0% annualized realized


From 769.2, SPY should realize roughly 12% annualized volatility through September 11 as payrolls and rate/geopolitical risks break the recent low-volatility consolidation; the position needs SPY outside roughly 762.45-777.55 at expiry. The premise is invalidated if the event passes and SPY remains pinned near 765-775 while realized volatility falls below the structure's approximately 9.5% breakeven volatility.

## Why this trade

Submitted one paper-trade action:

- **SPY Sep 11 reverse iron condor, 23×**
  - Sell 760 put
  - Buy 765 put
  - Buy 775 call
  - Sell 780 call
- **Limit debit:** $2.56
- **Maximum risk:** $5,888, or 5.19% of equity
- **Expiration breakevens:** approximately $762.45 and $777.55
- **Status at last check:** live, unfilled limit order

Thesis: payrolls and macro risks lift realized volatility toward 12%, above the structure’s roughly 9.5% breakeven volatility. Estimated after-cost EV was **+$35 per spread** under that view.

Recorded management rules: **-55% stop, +50% profit target, hold through expiry**. Also recorded a 57% forecast that SPY realized volatility lands between **9.5% and 14.5%** through September 11.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| SPY 760/765/775/780 reverse iron condor | $255.50 | $244.50 | $-255.50 | 0.88 | **chosen** |
| SPY 760/770/780 reverse iron butterfly | $679.00 | $321.00 | $-679.00 | 0.72 |  |
| SPY 765/760 bear put spread | $112.00 | $388.00 | $-112.00 | 2.88 |  |

## Sources

- **idle** — `inbox/pos_20260903T135812Z_idle_7e501550`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| sell | 23 | SPY260911P00760000 |
| buy | 23 | SPY260911P00765000 |
| buy | 23 | SPY260911C00775000 |
| sell | 23 | SPY260911C00780000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -55.0% |
| profit_target | basis position_mark, threshold 50.0% |
| time_stop | days_before_expiry 0 |

## Outcome

_Open - this section fills in when the position resolves._
