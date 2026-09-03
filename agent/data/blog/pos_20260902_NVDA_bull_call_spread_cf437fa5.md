---
title: "NVDA bull call spread"
position_id: pos_20260902_NVDA_bull_call_spread_cf437fa5
date: 2026-09-02
time: "17:33:31.350258+00:00"
underlying: NVDA
strategy: bull_call_spread
status: opening
expiry: 2026-09-04
max_loss_usd: 5670.0
confidence: 0.49
decision_ref: jrn_20260902T173203Z_dec9e4618
batch: bat_90ccd91b2929
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# NVDA bull call spread

Opened **2026-09-02T17:33:31.350258+00:00** — max loss $5,670.00, expiry 2026-09-04.

## The thesis

**Claim:** From $225.35, NVDA will hold post-earnings support above $218 and finish between $218 and $232 on September 4, with modest drift toward $227, as AI-demand support outweighs macro pressure despite payroll-related gap risk.

**Resolves:** 2026-09-04, band [218.0, 232.0]

**Expected drift:** +0.8%

**Vol view:** 45.0% annualized realized


From $225.35, NVDA should hold post-earnings support above $218 and finish between $218 and $232 on September 4, with modest drift toward $227 as AI-demand support outweighs macro pressure. A trade below $218 invalidates the premise; September 4 payrolls are acknowledged gap risk.

## Why this trade

Opened **30× NVDA Sep 4 $225/$230 bull call spreads**.

- **Fill:** $1.90 debit
- **Maximum loss:** $5,700
- **Maximum profit:** $9,300
- **Breakeven:** $226.90
- **Thesis:** NVDA holds above $218 and drifts toward $227–230 by September 4.
- **Modelled EV after costs:** approximately **+$32 per spread**
- **Confidence:** 49%
- **Exit rules recorded:** +75% profit target, −60% premium stop, underlying invalidation below $218, hold through expiration day.
- **Key risk:** September 4 payrolls can produce a gap; defined risk limits exposure.

The 220/215 put spread offered only about +$1 EV with poor payoff, while the butterfly remained negative EV after costs. A 35%–55% realized-volatility forecast was also recorded.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| NVDA Sep4 225/230 bull call spread | $189.00 | $311.00 | $-189.00 | 1.33 | **chosen** |
| NVDA Sep4 220/215 bull put spread | $-56.00 | $56.00 | $-444.00 | 0.19 |  |
| NVDA Sep4 222.5/227.5/232.5 call butterfly | $135.50 | $364.50 | $-135.50 | 1.12 |  |

## Sources

- **alpaca_news** — `inbox/new_20260902T173200Z_alpaca_news_b39223f9`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| long | 30 | NVDA260904C00225000 |
| short | 30 | NVDA260904C00230000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -60.0% |
| profit_target | basis position_mark, threshold 75.0% |
| time_stop | days_before_expiry 0 |
| underlying_stop | direction below, level 218.0 |

## Outcome

**Closed:** external

**Why:** in our records, absent at broker - no P&L observed at close

**Result:** not observed at close.
