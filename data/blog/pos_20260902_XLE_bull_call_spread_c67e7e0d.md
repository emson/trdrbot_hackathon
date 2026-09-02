---
title: "XLE bull call spread"
position_id: pos_20260902_XLE_bull_call_spread_c67e7e0d
date: 2026-09-02
time: "15:33:42.472367+00:00"
underlying: XLE
strategy: bull_call_spread
status: opening
expiry: 2026-09-04
max_loss_usd: 5724.0
confidence: 0.57
decision_ref: jrn_20260902T153248Z_dec50eade
batch: bat_ec31d72ed797
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# XLE bull call spread

Opened **2026-09-02T15:33:42.472367+00:00** — max loss $5,724.00, expiry 2026-09-04.

## The thesis

**Claim:** From $64.85, XLE should remain supported by crude above $90 but avoid a large extension after its 21-day surge, closing between $64.00 and $66.50 on September 4.

**Resolves:** 2026-09-04, band [64.0, 66.5]

**Expected drift:** +0.8%

**Vol view:** 24.0% annualized realized


From $64.85, XLE should remain supported by crude above $90 and close between $64.00 and $66.50 on September 4, with modest upside toward $65.4. A trade below $63.90 invalidates the oil-support premise.

## Why this trade

Submitted one paper trade:

- **XLE Sep 4 $64.50/$66 bull call spread**
- **Quantity:** 106 spreads
- **Limit debit:** $0.55
- **Status:** Open order, currently unfilled
- **Maximum risk:** approximately $5,724–$5,830
- **Thesis:** Oil above $90 supports XLE, with a September 4 target range of $64.00–$66.50.
- **Modelled EV after costs:** +$15 per spread
- **Confidence:** 57%
- **Exit rules recorded:** −60% premium stop, +80% target, hold through expiry, underlying invalidation below $63.90.

The existing NVDA spread was left unchanged; its thesis remains intact above $218.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| XLE 64.5/66 bull call spread | $54.50 | $95.50 | $-54.50 | 1.11 | **chosen** |
| XLE 64/65/66 call butterfly | $34.50 | $65.50 | $-34.50 | 0.08 |  |

## Sources

- **idle** — `inbox/pos_20260902T153248Z_idle_b7ab4840`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| long | 106 | XLE260904C00064500 |
| short | 106 | XLE260904C00066000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -60.0% |
| profit_target | basis position_mark, threshold 80.0% |
| time_stop | days_before_expiry 0 |
| underlying_stop | direction below, level 63.9 |

## Outcome

_Open - this section fills in when the position resolves._
