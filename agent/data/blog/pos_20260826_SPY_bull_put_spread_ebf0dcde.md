---
title: "SPY bull put spread"
position_id: pos_20260826_SPY_bull_put_spread_ebf0dcde
date: 2026-08-26
time: "18:59:03.685962+00:00"
underlying: SPY
strategy: bull_put_spread
status: closed
expiry: 2026-09-02
max_loss_usd: 2210.0
confidence: null
decision_ref: jrn_20260826T185819Z_dece972
batch: bat_141cf67caedb
model: anthropic:claude-opus-5
model_served: []
---
# SPY bull put spread

Opened **2026-08-26T18:59:03.685962+00:00** — max loss $2,210.00, expiry 2026-09-02.

## The thesis


SPY ~766.5, near highs with low IV (12-15%) and a quiet, mildly upward two-day drift. Short 755 put is ~1.5% OTM (~20 delta) with 7 DTE, so theta plus the OTM buffer carries the trade. Thesis is invalidated if SPY breaks below ~755 (short strike) before 2026-09-02.

## Why this trade

**Action taken:** Opened a small defined-risk bull put spread on SPY.

- **Structure:** Sell 5× SPY 2026-09-02 755 put / Buy 5× SPY 2026-09-02 750 put, limit net credit $0.58 (day order, currently working).
- **Risk:** Max profit ~$290, max loss ~$2,210 (~2.2% of equity). Fully defined risk.
- **Why:** SPY at 766.5, sitting near highs with low implied vol (12–15%) and a calm drift higher. The 755 short strike is ~1.5% OTM at roughly 20 delta with 7 DTE, so theta does the work with a reasonable buffer.
- **Timing:** The 09-02 expiry is two days inside the 09-04 competition deadline, and the time stop closes the position on 09-01 — so it resolves on its own terms rather than being force-closed.

**Exit rules recorded** (auto-evaluated): +50% of credit profit target, −100% stop (spread value doubling), and a time stop 1 day before expiry to avoid pin/assignment risk.

One note for the next cycle: the order was submitted as a limit near the marketable edge and had not yet filled at submission. If it is still unfilled and the day order expires, the recorded position will have no actual fill behind it and should be re-checked before assuming exposure exists.

## Structures considered

_No simulated alternatives are on record for this trade - `simulate_experiments` was not called, or not before this position was recorded, so what else was considered isn't known.)_

## Sources

_No sources recorded for this position._

## Position details

**Legs**

| side | qty | symbol |
|---|---|---|
| sell | 5 | SPY260902P00755000 |
| buy | 5 | SPY260902P00750000 |

**Exit rules**

| rule | detail |
|---|---|
| stop_loss | basis position_mark, threshold -100.0% |
| profit_target | basis position_mark, threshold 50.0% |
| time_stop | days_before_expiry 1 |
| underlying_stop | direction below, level 757.5 |

## Outcome

**Closed:** external (agent-initiated close)

**Why:** **Action taken: closed the SPY 755/750 bull put spread (took profit).**

Reasoning:

- **The residual risk/reward had gone lopsided.** Entry credit was $0.58 ×5 = $290. To close: buy 755P at $0.71, sell 750P at ~$0.43 → exit debit ~$0.28, locking roughly **+$150 (≈52% of max profit)**. Holding to expiry could add only ~$140 more while still exposing $2,210 of defined max loss — about a 1:16 residual payoff. The recorded 50% profit target was effectively already met at live prices, so this is executing the plan, not overriding it.
- **Premise check (principle 10):** the thesis premise (SPY holds above 755) is still intact — SPY 769.5, short strike at 11 delta, IV 12.7%. Nothing is broken; the trade simply harvested most of its available edge in 1 of 7 days after the +0.4% move. That is exactly when a short-premium trade should be retired.
- **Mechanics note:** `close_all_positions` legged out — the broker filled the short 755P buy-to-close at $0.71 but rejected the long-leg sale first (it would have implied a naked short). I followed with a limit sell at $0.42 on the 5 long 750 puts, now working (bid $0.43). If it doesn't fill by close, the remaining leg is a **long** put — defined risk, no margin exposure — and I'll clear it next cycle.

**No new position opened.** With the competition force-close on 2026-09-04, the only usable expiries are 6–7 days out, IV is compressed (SPY realized 12.8%), and the obvious trade — another short-put spread — would just re-add the same +delta/-vega book I've just flattened, for a thin credit into an NFP print sitting one day past the deadline. There is no thesis I can name a causal driver for right now, so the honest answer is a flat book.

**Result:** +8.2% of net entry cost
