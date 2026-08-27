---
type: Technique
status: stable
sources:
- id: src-1
  resource: research:trading_techniques_review
  author: trdrbot/research
  last_modified: '2026-08-27T16:31:59.553918+00:00'
generated:
  at: '2026-08-27T16:31:59.554439+00:00'
---

# Rule
The implied daily move (shown on every simulated candidate) is what IV charges per day. Compare it against the underlying's RECENT REALISED daily range.

# When it applies
Before selling any premium, and before buying any.

# What it means
Implied above realised: short premium is being paid for. Implied below realised: you are donating. This is the single edge test that matters for a short-dated book, and it replaces reasoning from IV level or IV rank, which say nothing about whether IV exceeds FUTURE realised vol.

# Caveat
The number is the same for every structure at one spot and one flat IV - it is a property of the underlying, not of the trade. It varies between structures only through skew.