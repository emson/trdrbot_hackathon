---
title: "XLE bull call spread"
position_id: pos_20260902_XLE_bull_call_spread_8bfe89e1
date: 2026-09-02
time: "17:39:54.685068+00:00"
underlying: XLE
strategy: bull_call_spread
status: opening
expiry: 2026-09-04
max_loss_usd: 8460.0
confidence: 0.55
decision_ref: jrn_20260902T173844Z_dec353966
batch: bat_645ab69ff0ca
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# XLE bull call spread

Opened **2026-09-02T17:39:54.685068+00:00** — max loss $8,460.00, expiry 2026-09-04.

## The thesis

**Claim:** From $65.05, XLE will hold above $64.50 and finish between $64.50 and $67.00 on September 4 as the oil shock continues to support energy equities, while the recent overbought run limits upside.

**Resolves:** 2026-09-04, band [64.5, 67.0]

**Expected drift:** +1.0%


From $65.05, XLE should hold above $64.50 and finish between $64.50 and $67.00 on September 4 as the oil shock continues to support energy equities; a trade below $64.50 invalidates the support premise.

## Why this trade

### Action: Submitted XLE bull call spread

- **Buy 180** XLE Sep 4 $65 calls
- **Sell 180** XLE Sep 4 $67 calls
- **Limit debit:** $0.47
- **Order status:** Pending/unfilled when submitted
- **Maximum risk if filled:** $8,460, or 7.6% of equity
- **Maximum profit:** $27,540
- **Combined book defined risk:** $14,160, approximately 12.7% of equity

**Thesis:** XLE holds above $64.50 and finishes between $64.50–$67 on September 4 as elevated oil supports energy equities. The expected upside is deliberately capped because XLE is already overbought.

Simulation estimated **+$28 EV per spread after costs** under a +1.0% two-day drift. The alternative bull-put spread was approximately breakeven after costs with an unattractive payoff, while the butterfly had negative EV.

**Recorded exits:**
- Profit target: **+75%**
- Premium stop: **−60%**
- Underlying invalidation: **below $64.50**
- Time stop: **hold through expiry**
- Confidence: **55%**

The $64.50 underlying stop primarily confirms thesis failure rather than protecting expiry value; the −60% premium stop provides the earlier loss control.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| XLE Sep4 65/67 bull call spread | $47.00 | $153.00 | $-47.00 | 1.80 | **chosen** |
| XLE Sep4 64/62 bull put spread | $-14.00 | $14.00 | $-186.00 | 0.11 |  |
| XLE Sep4 64/65/66 call butterfly | $31.50 | $68.50 | $-31.50 | 0.29 |  |

## Sources

- **alpaca_news** — `inbox/new_20260902T173840Z_alpaca_news_197e8e15`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| buy | 180 | XLE260904C00065000 |
| sell | 180 | XLE260904C00067000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -60.0% |
| profit_target | basis position_mark, threshold 75.0% |
| time_stop | days_before_expiry 0 |
| underlying_stop | direction below, level 64.5 |

## Outcome

_Open - this section fills in when the position resolves._
