---
type: Technique
status: stable
sources:
- id: src-1
  resource: research:trading_techniques_review
  author: trdrbot/research
  last_modified: '2026-08-27T16:31:59.557218+00:00'
generated:
  at: '2026-08-27T16:31:59.557229+00:00'
---

# Rule
Treat any Kelly number on a high-win-rate, negatively-skewed payoff as an overestimate.

# What it means
Kelly has a structural preference for high win rates, which always arrive with negative skew - exactly the shape of a credit spread. Full Kelly carries a one-in-three chance of halving the bankroll before doubling it.

# Related, and more useful
Positive skew VALIDATES FASTER. At a per-trade Sharpe of 0.25 a positively-skewed structure needs about 28 trades to prove itself; a negatively-skewed one needs 64. For an agent that must earn evidence before it is allowed size, long-convexity structures are cheaper to learn from - a statistical argument, independent of the risk one.