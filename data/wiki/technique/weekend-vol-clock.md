---
type: Technique
status: stable
sources:
- id: src-1
  resource: research:trading_techniques_review
  author: trdrbot/research
  last_modified: '2026-08-27T16:31:59.555379+00:00'
generated:
  at: '2026-08-27T16:31:59.555399+00:00'
---

# Rule
Volatility does not accrue when the market is shut. Three calendar days from a Friday is 2.00 volatility days, not 3.

# When it applies
Every greek, every cross-expiry IV comparison, and the expected move at 2-10 DTE, where the effect dominates rather than rounds away.

# What it means
An unadjusted calendar clock overstates time by up to 50% over a weekend and manufactures a spurious IV jump every Monday morning. Our pricer already weights weekend days at 0.5; do not re-derive time from raw calendar days.

# Evidence
Removing Friday-to-Monday positions from a 1DTE SPX put-write study cut cumulative return from 28.07% to 8.94% - about two thirds of profit came from weekend-spanning trades.