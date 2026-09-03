---
type: Technique
status: stable
sources:
- id: src-1
  resource: specs/notes/014_trader_critique_and_response.md
  author: trdrbot/review
  last_modified: '2026-08-28T15:30:00.000000+00:00'
generated:
  at: '2026-08-28T15:30:00.000000+00:00'
---

# Rule
Before pricing a structure, ask which variable it lives on. Compare **dollars per 1% move in
the underlying** (delta_dollars x 0.01) against **dollars per 1 point of implied vol**
(vega_dollars). Whichever is several times larger is what the trade actually is; the simulated
candidate now prints this as `NEEDS a DIRECTION bet (9x)` or `a VOL bet (3x)`.

# When it applies
Every candidate, before comparing EVs. Two structures on the same underlying and the same expiry
can be opposite bets, and pricing both off one volatility assumption hides that.

# What it means
Measured on one live board, SPY, 5 days to expiry:

| structure | per 1% spot | per vol point | what it is |
|---|---|---|---|
| iron condor 761/766-776/781 | $9 | $23 | a **vol** bet (3x) |
| call debit 775/785 | $199 | $22 | a **direction** bet (9x) |
| bull put 765/760 | $114 | $12 | a **direction** bet (10x) |

The third row is the useful one. A far-OTM credit spread **is not a premium-selling trade** — it
is a leveraged directional position wearing a premium-selling costume. It has the shape people
associate with theta harvesting (high win rate, small credit, short vega) while its P&L is
dominated by where the underlying goes. That is why it can look like the safe choice and be the
riskiest thing on the board: it needs an 84% win rate AND it is 10:1 a direction bet.

The corollary for the breakeven: read the one in the DOMINANT variable. A call spread's breakeven
vol is nearly irrelevant, and its breakeven drift is the trade.

# Caveat
Both sensitivities are Black-Scholes outputs at one spot and one vol, so they inherit that model's
caveats and they move as spot does. The ratio is a classification, not a hedge ratio. A "balanced"
label means the position genuinely rides both, which is information, not a failure to decide.
