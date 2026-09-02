---
title: "NVDA bull call spread"
position_id: pos_20260902_NVDA_bull_call_spread_c1bca8b8
date: 2026-09-02
time: "13:57:12.357502+00:00"
underlying: NVDA
strategy: bull_call_spread
status: opening
expiry: 2026-09-04
max_loss_usd: 6364.0
confidence: 0.52
decision_ref: jrn_20260902T135542Z_deccf1ebf
batch: bat_f73a44c636d3
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# NVDA bull call spread

Opened **2026-09-02T13:57:12.357502+00:00** — max loss $6,364.00, expiry 2026-09-04.

## The thesis

**Claim:** NVDA will hold above 218 and rebound modestly toward 222-224 by the September 3 close as post-earnings AI demand support outweighs semiconductor tariff and macro pressure.

**Resolves:** 2026-09-03, band [218.0, 225.0]

**Expected drift:** +1.2%

**Vol view:** 35.0% annualized realized


NVDA should hold above 218 and rebound modestly toward 222-224 by the September 3 close as post-earnings AI demand support outweighs semiconductor tariff and macro pressure. A trade below 218 invalidates the premise.

## Why this trade

Submitted one action:

- **NVDA Sep 4 220/225 bull call spread**
- **Quantity:** 37 spreads
- **Limit debit:** $1.72
- **Order status:** Working, currently unfilled
- **Maximum risk:** $6,364 (6.13% of equity)
- **Modelled EV after costs:** +$68 per spread under the stated +1.2% drift view
- **Confidence:** 52%

Management is recorded: 60% profit target, 45% premium-loss stop, exit one day before expiry, and thesis invalidation below NVDA $218. The time stop avoids holding through September 4 payroll risk.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| NVDA Sep4 220/225 bull call spread | $172.00 | $328.00 | $-172.00 | 1.66 | **chosen** |
| NVDA Sep4 217.5/212.5 bull put spread | $-103.50 | $103.50 | $-396.50 | 0.41 |  |
| NVDA Sep4 220/225/230 call butterfly | $121.00 | $379.00 | $-121.00 | 1.57 |  |

## Sources

- **alpaca_news** — `inbox/new_20260902T033512Z_alpaca_news_4348c942`
- **alpaca_news** — `inbox/new_20260902T063529Z_alpaca_news_3bd310de`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_0e43486d`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_1c68fa8d`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_31a8ad70`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_5675a74a`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_86dd986f`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_8d9e20a8`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_8fb9df65`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_92b1e86f`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_ac4523bd`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_b7aecbd7`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_d3f1fb47`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_dfc3a139`
- **alpaca_news** — `inbox/new_20260902T071422Z_alpaca_news_e5de1983`
- **alpaca_news** — `inbox/new_20260902T081013Z_alpaca_news_ac06f47c`
- **alpaca_news** — `inbox/new_20260902T082923Z_alpaca_news_9bb450e8`
- **alpaca_news** — `inbox/new_20260902T095507Z_alpaca_news_87138962`
- **alpaca_news** — `inbox/new_20260902T095507Z_alpaca_news_d5e6f68e`
- **alpaca_news** — `inbox/new_20260902T102511Z_alpaca_news_16f8b22d`
- **alpaca_news** — `inbox/new_20260902T102511Z_alpaca_news_9cf3306c`
- **alpaca_news** — `inbox/new_20260902T112519Z_alpaca_news_a9f01cf0`
- **alpaca_news** — `inbox/new_20260902T125531Z_alpaca_news_1be51e22`
- **alpaca_news** — `inbox/new_20260902T132535Z_alpaca_news_a01ac8a6`
- **polymarket** — `inbox/pre_20260901T220312Z_polymarket_2e2d469f`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| long | 37 | NVDA260904C00220000 |
| short | 37 | NVDA260904C00225000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -45.0% |
| profit_target | basis position_mark, threshold 60.0% |
| time_stop | days_before_expiry 1 |
| underlying_stop | direction below, level 218.0 |

## Outcome

**Closed:** external

**Why:** in our records, absent at broker - no P&L observed at close

**Result:** not observed at close.
