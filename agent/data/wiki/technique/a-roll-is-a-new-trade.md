---
type: Technique
status: stable
sources:
- id: src-1
  resource: research:trading_techniques_review
  author: trdrbot/research
  last_modified: '2026-08-27T16:31:59.557893+00:00'
generated:
  at: '2026-08-27T16:31:59.557903+00:00'
---

# Rule
Evaluate any roll through the identical entry gate you would apply to a fresh position: current implied-vs-realised, current liquidity, post-trade portfolio greeks.

# What it means
If it would not pass as a new trade, close instead. Published rolling rules ('roll at 14-21 DTE if challenged', 'never roll for a debit') have no backtests behind them, but this reframing is logically forced and removes the loss-aversion failure mode without needing to believe any of them.