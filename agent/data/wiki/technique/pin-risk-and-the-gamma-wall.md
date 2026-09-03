---
type: Technique
status: stable
sources:
- id: src-1
  resource: specs/notes/023_gauntlet_response_design.md
  author: trdrbot/scaffold
  last_modified: '2026-08-30T00:00:00.000000+00:00'
generated:
  at: '2026-08-30T00:00:00.000000+00:00'
---

# Rule
Close short-dated short premium at the gamma wall - roughly the last day before expiry - unless there is a stated reason to carry it into settlement.

# When it applies
Any short-premium position inside its final sessions: credit spreads, condors, anything collecting decay near the strike.

# What it means
Gamma is not a smooth risk near expiry, it is a cliff. As time to expiry goes to zero the delta of a strike-adjacent option approaches a step function: the position is short 40 deltas, then a $1 move makes it short 90, then the underlying settles a cent the other side and it is flat. The greeks that described the position at entry stop describing it, and the mark stops being a fair summary of what is at risk - which is exactly when a mark-based stop is least able to protect anything.

The reward for carrying it is the last, smallest sliver of theta. The risk is the largest, least controllable part of the distribution. That trade was worth taking when the position was opened and stops being worth taking here, which makes closing the default rather than a decision.

Two consequences this book has coded rather than remembered. An implicit time stop closes any position with no time stop of its own at 1 DTE, the same way the competition deadline is implicit on every position - a default nobody has to recall under pressure. And it is a default, not a guardrail: writing an explicit `time_stop` of 0 means "hold to expiry deliberately" and is honoured.

The related trap is assignment, not just P&L: an in-the-money short leg at expiry is a stock position on Monday, at a size the account never sized for.
