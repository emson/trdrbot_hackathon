---
type: Technique
status: stable
sources:
- id: src-1
  resource: research:trading_techniques_review
  author: trdrbot/research
  last_modified: '2026-08-27T16:31:59.557577+00:00'
generated:
  at: '2026-08-27T16:31:59.557588+00:00'
---

# Rule
Ignore the '50% of max credit, or 21 DTE' management convention.

# What it means
It was popularised by a broker with a direct commercial interest in trade frequency, and the best independent test found the PASSIVE version beat the managed one on both CAGR (5.46% vs 4.44%) and Sharpe (0.67 vs 0.52) - before slippage, which biases toward the active version. And a 21-DTE stop is undefined when you enter at 7 DTE.

# What to do instead
Close when the expected remaining P&L from simulation falls below the expected round-trip exit cost plus a charge for remaining tail exposure. A computed decision, not a convention.