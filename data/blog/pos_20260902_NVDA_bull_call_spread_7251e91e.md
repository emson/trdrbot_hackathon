---
title: "NVDA bull call spread"
position_id: pos_20260902_NVDA_bull_call_spread_7251e91e
date: 2026-09-02
time: "14:44:13.844500+00:00"
underlying: NVDA
strategy: bull_call_spread
status: opening
expiry: 2026-09-04
max_loss_usd: 7200.0
confidence: 0.49
decision_ref: jrn_20260902T144306Z_dec4584c9
batch: bat_b1d1966aeb17
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# NVDA bull call spread

Opened **2026-09-02T14:44:13.844500+00:00** — max loss $7,200.00, expiry 2026-09-04.

## The thesis

**Claim:** From $224.15, NVDA will hold its post-earnings support above $218 and close between $222 and $232 on September 4, with modest upside toward $227 as AI-demand support outweighs macro pressure.

**Resolves:** 2026-09-04, band [222.0, 232.0]

**Expected drift:** +1.3%

**Vol view:** 40.0% annualized realized


From $224.15, NVDA should hold post-earnings support above $218 and close between $222 and $232 on September 4, with modest upside toward $227 as AI-demand support outweighs macro pressure. A trade below $218 invalidates the premise.

## Why this trade

Opened **48 NVDA Sep 4 $225/$230 bull call spreads**.

- **Fill:** $1.51 debit
- **Capital at risk:** $7,248 maximum
- **Maximum profit:** $16,752
- **Breakeven:** $226.51 at expiry
- **Thesis:** NVDA holds above $218 and closes September 4 between $222–$232, with upside toward $227
- **Confidence:** 49%
- **Sizing:** 48 contracts, as prescribed by `size_position`
- **Exit rules:** +100% profit target, −60% premium stop, underlying invalidation below $218, hold through September 4 expiry
- **Key risk:** September 4 payrolls and geopolitical gap risk

I also recorded the associated 40% realized-volatility forecast for calibration.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| 225/230 bull call spread | $149.50 | $350.50 | $-149.50 | 1.94 | **chosen** |
| Long 225 call | $220.00 | unknown | $-220.00 | 2.67 |  |
| 220/217.5 bull put spread | $-46.00 | $46.00 | $-204.00 | 0.21 |  |

## Sources

- **alpaca_news** — `inbox/new_20260902T144303Z_alpaca_news_4e50e05b`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| long | 48 | NVDA260904C00225000 |
| short | 48 | NVDA260904C00230000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -60.0% |
| profit_target | basis position_mark, threshold 100.0% |
| time_stop | days_before_expiry 0 |
| underlying_stop | direction below, level 218.0 |

## Outcome

**Closed:** external

**Why:** in our records, absent at broker - no P&L observed at close

**Result:** not observed at close.
