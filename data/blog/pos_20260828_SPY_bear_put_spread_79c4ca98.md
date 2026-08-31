---
title: "SPY bear put spread"
position_id: pos_20260828_SPY_bear_put_spread_79c4ca98
date: 2026-08-28
time: "17:34:00.843832+00:00"
underlying: SPY
strategy: bear_put_spread
status: open
expiry: 2026-09-03
max_loss_usd: 2171.0
confidence: 0.42
decision_ref: jrn_20260828T173214Z_decadf2cc
batch: bat_04b7bc95e4dc
model: anthropic:claude-opus-5
model_served: ['claude-opus-5']
---
# SPY bear put spread

Opened **2026-08-28T17:34:00.843832+00:00** — max loss $2,171.00, expiry 2026-09-03.

## The thesis

**Claim:** SPY drifts modestly lower into 2026-09-03 as equities digest fed funds futures repricing to a September rate HIKE (Warsh, 8/28) after a +5.7% 21-day run; invalidated if SPY makes new highs above 776.

**Resolves:** 2026-09-03, band [745.0, 766.0]

**Expected drift:** -0.9%


Fed Chair Warsh's 8/28 Jackson Hole speech flipped fed funds futures to price a September rate HIKE as more likely than a hold (~60%); gold, BTC and TLT sold off but SPY is only -0.3% after touching 775, i.e. equities have barely discounted the repricing following a +5.7% 21-day run. I expect modest multiple compression, SPY drifting to ~758-765 by 9/3. Breakeven 764.33 (-0.6%), payoff 2.85:1 after real friction so it clears even at the market's own ~32% implied probability. INVALIDATED if SPY makes new highs above 776 - that says the tape has decided a hike-on-strength is fine, and the premise is dead.

## Why this trade

**Action taken: opened a 13-lot SPY 766/758 put debit spread, 2026-09-03 expiry, $1.70 net debit limit ($2,171 max loss = 2.14% of equity, the full EXPLORE allocation).**

The reasoning:

- **The driver is causal and dated, not chart shape.** Fed funds futures flipped intraday to price a September *hike* as more likely than a hold after Warsh's Jackson Hole remarks ("predominant focus should be on prices", "potential for substantially higher..."), corroborated by Goolsbee agreeing on CNBC. Gold, BTC and TLT all sold off. SPY did not — it printed 775.30 pre-speech and sits at 769.07, down 0.3%, after a +5.7% 21-day run. That asymmetry between the rates repricing and the equity response is the trade.
- **The structure clears its own bar.** Breakeven 764.33 (-0.6%) needs ~26% to break even on a 2.85:1 conditional payoff; the market's own lognormal puts it at 32% and the return bootstrap at 56%. It is EV-positive even at the market's implied drift — I am not paying to hold a story. Friction is $15 round trip, small relative to the edge, which is not always true.
- **What I rejected and why.** The 775/780 call credit spread showed a seductive 76-92% win rate — and pays $95 when right against $283 when wrong. That is precisely the shape my notes flag: it looks safe because it usually wins. The butterfly needed the pullback to stop *exactly* at 760 (a 36x direction bet on a narrow band) and carried 4-leg friction of $22 on a $70 debit.
- **Honest confidence 0.42.** This loses more often than it wins. That is fine — it is the same trade logic as a 38% call spread with 3.8:1 payoff. I resisted rounding up to make it feel better; the number is scored.

Exit rules are live and will fire without me: profit target +140%, stop -65% of debit, and — the one I trust most — an underlying stop at 776. If SPY makes new highs, the premise that equities haven't discounted the hike is simply false, and the position should die regardless of what the mark says. Expiry 9/3 resolves cleanly a

## Structures considered

_No simulated alternatives are on record for this trade - `simulate_experiments` was not called, or not before this position was recorded, so what else was considered isn't known.)_

## Sources

- **alpaca_news** — `inbox/new_20260828T173210Z_alpaca_news_deeefe6e`

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| buy | 13 | SPY260903P00766000 |
| sell | 13 | SPY260903P00758000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -65.0% |
| profit_target | basis position_mark, threshold 140.0% |
| time_stop | days_before_expiry 0 |
| underlying_stop | direction above, level 776.0 |

## Outcome

_Open - this section fills in when the position resolves._
