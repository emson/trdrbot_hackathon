---
title: "AVGO bull call spread"
position_id: pos_20260903_AVGO_bull_call_spread_c02306dd
date: 2026-09-03
time: "15:51:39.511238+00:00"
underlying: AVGO
strategy: bull_call_spread
status: opening
expiry: 2026-09-11
max_loss_usd: 9660.0
confidence: 0.52
decision_ref: jrn_20260903T155046Z_dec8ba426
batch: bat_5beee293e280
model: openai:gpt-5.6-sol
model_served: ['gpt-5.6-sol']
---
# AVGO bull call spread

Opened **2026-09-03T15:51:39.511238+00:00** — max loss $9,660.00, expiry 2026-09-11.

## The thesis

**Claim:** AVGO will rebound from its post-earnings selloff and close between $359.02 and $374.78 on 2026-09-11 as investors distinguish supply-constrained revenue timing from weakening AI demand.

**Resolves:** 2026-09-11, band [359.02, 374.78]

**Expected drift:** +3.5%


AVGO should rebound from its post-earnings selloff and close between $359.02 and $374.78 on September 11 as investors distinguish supply-constrained revenue timing from weakening AI demand. A trade below the September 3 post-earnings low near $342 invalidates the rebound premise.

## Why this trade

Placed one **AVGO bullish call-spread order**:

- **Buy 21** AVGO 2026-09-11 $355 calls
- **Sell 21** AVGO 2026-09-11 $375 calls
- **Limit debit:** $4.60
- **Maximum risk:** $9,660
- **Status:** Open/unfilled at last check

Rationale: expected post-earnings rebound into **$359.02–$374.78** by September 11. Simulation estimated **+$407 EV per spread after costs** under the stated +3.5% drift view; sizing prescribed 21 contracts.

Management was recorded with 52% confidence, a 75% profit target, −60% premium stop, expiry-day time stop, and $342 thesis invalidation. The $342 underlying stop is a thesis check rather than effective loss protection because it lies below the long strike.

## Structures considered

| structure | entry cost | max profit | max loss | payoff ratio | |
|---|---:|---:|---:|---:|---|
| AVGO 355/375 bull call spread | $459.50 | $1,540.50 | $-459.50 | 2.36 | **chosen** |
| AVGO 355/365/375 call butterfly | $143.50 | $856.50 | $-143.50 | 1.30 |  |
| AVGO 355 long call | $610.00 | unknown | $-610.00 | 2.95 |  |

## Sources

- **muse** — `inbox/opp_20260903_muse_098f2cfa40c9`
- **muse** — `inbox/opp_20260903_muse_42a7ddf45c1e`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| buy | 21 | AVGO260911C00355000 |
| sell | 21 | AVGO260911C00375000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -60.0% |
| profit_target | basis position_mark, threshold 75.0% |
| time_stop | days_before_expiry 0 |
| underlying_stop | direction below, level 342.0 |

## Outcome

_Open - this section fills in when the position resolves._
