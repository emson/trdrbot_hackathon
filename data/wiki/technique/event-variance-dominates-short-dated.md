---
type: Technique
status: stable
sources:
- id: src-1
  resource: research:trading_techniques_review
  author: trdrbot/research
  last_modified: '2026-08-27T16:31:59.556884+00:00'
generated:
  at: '2026-08-27T16:31:59.556896+00:00'
---

# Rule
Before trading any window containing earnings or a macro print, ask what share of the total variance that single day represents.

# What it means
Variance is additive in time, volatility is not: IV_total^2 * T_total = IV_diffusive^2 * T_normal + IV_event^2 * T_event. A worked case: one earnings day inside a 40-day window was 57% of total straddle variance while being 2.5% of the days.

# Consequence
At 2-10 DTE a single event is usually the majority of what you are buying or selling. Priced scheduled risk is VARIANCE, not direction - so express an event view with vol structures, not directional ones.