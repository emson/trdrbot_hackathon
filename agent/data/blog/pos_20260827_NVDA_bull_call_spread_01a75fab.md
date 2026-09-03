---
title: "NVDA bull call spread"
position_id: pos_20260827_NVDA_bull_call_spread_01a75fab
date: 2026-08-27
time: "15:26:00.288014+00:00"
underlying: NVDA
strategy: bull_call_spread
status: closed
expiry: 2026-09-04
max_loss_usd: 2100.0
confidence: null
decision_ref: jrn_20260827T152254Z_dec775fcc
batch: bat_a79548fd7b0e
model: anthropic:claude-opus-5
model_served: []
---
# NVDA bull call spread

Opened **2026-08-27T15:26:00.288014+00:00** — max loss $2,100.00, expiry 2026-09-04.

## The thesis

**Claim:** NVDA holds its post-earnings gap (blowout Q2, broad PT raises to $300-400) and drifts modestly higher into 2026-09-03, finishing between 220 and 245.

**Resolves:** 2026-09-03, band [220.0, 245.0]

**Expected drift:** +1.5%


NVDA reported a blowout Q2 last night and re-rated +7.3% to ~225.8 with broad sell-side PT raises ($300/$330/$400); the event binary is now behind it and semi/QQQ ETF inflows are running. I expect the gap to hold and drift modestly higher (+1.5%) into 2026-09-03, finishing 220-245. Invalidated if NVDA gives back the bulk of the gap (below ~218) - today's fade in the sympathy names (SMCI +1.5% off +4% premarket, MRVL round-tripping) already says the AI bid is being sold into, so gap-fill is the live risk. Edge is small and drift-dependent: simulator put EV at only +$10/contract.

## Why this trade

**Action taken: opened a 10x NVDA 230/240 call spread expiring 2026-09-04, $2,100 debit (2.1% of equity, the EXPLORE allocation).**

What drove the decision, and what I'm uneasy about:

- **Two stored priors died on contact with the tape.** The desk's NVDA read ("post-event fade at 209.77, crowded long being distributed") was written before last night's print; NVDA is +7.3% at 225.8 with PT raises to $300–400. And the stored SMCI thesis ("holds the NVDA-datacenter bid, band 38–48") is invalidated at the premise: on the single biggest possible catalyst SMCI went +4% premarket to +1.5%, and spot 37.98 is *below* the band floor. MRVL's bearish thesis is also unusable — it reports tonight, so it's a coin flip on information I don't have. I kept the tension rather than resolving it: NVDA held its gap while every derivative of it faded. That says the bid is name-specific, and it is exactly the risk to this trade.
- **The edge is genuinely small and I won't dress it up.** Simulator: ATM spread EV ~$0, butterfly −$13, credit spread −$8 (risk $908 to make $92 — the textbook trap). The 230/240 was the only positive one, at +$10/contract, and that entirely rests on my +1.5% drift view. Post-earnings drift is a weak effect in $5T mega-caps. Honest probability 38%, which is what I recorded — a losing-more-often-than-not trade with 3.8:1 payoff, not a "probably wins" trade.
- **Why trade at all rather than no-op:** friction is $5 round-trip, risk is defined and capped, it resolves in six sessions inside the deadline, and with zero resolved theses the scored record is the thing that actually compounds here.

Exit rules are live: −60% stop, +70% target, close if NVDA breaks 218 (gap-fill = thesis dead, per principle 10), and a time stop one day before expiry so NFP morning on 9/4 can't decide this for me.

## Structures considered

_No simulated alternatives are on record for this trade - `simulate_experiments` was not called, or not before this position was recorded, so what else was considered isn't known.)_

## Sources

- **discovery** — `inbox/opp_20260827T152232Z_discovery_36d5c9a3`
- **discovery** — `inbox/opp_20260827T152232Z_discovery_514a73bb`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| long | 10 | NVDA260904C00230000 |
| short | 10 | NVDA260904C00240000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -60.0% |
| profit_target | basis position_mark, threshold 70.0% |
| time_stop | days_before_expiry 1 |
| underlying_stop | direction below, level 218.0 |

## Outcome

**Closed:** external

**Why:** A working limit order to close the spread (repriced twice, see the entry reasoning's close-attempt notes) filled at the broker between ticks. Reconciliation found it absent and marked it closed; no P&L was observable at the moment of detection, so this uses the position's last observed mark.

**Result:** +52.8% of net entry cost
