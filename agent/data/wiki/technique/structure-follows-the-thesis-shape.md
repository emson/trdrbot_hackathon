---
type: Technique
status: stable
tags:
- structure
- playbook
- expectancy
sources:
- id: src-1
  resource: specs/notes/026_playbook_structure_lever.md
  author: trdrbot/review
  last_modified: '2026-09-03T15:58:34.213195+00:00'
- id: src-2
  resource: specs/decisions.md#D-122
  author: trdrbot/review
  last_modified: '2026-09-03T15:58:34.213476+00:00'
generated:
  at: '2026-09-03T15:58:34.213706+00:00'
---

# Rule
Before comparing expected values, name the SHAPE of the claim - range, bull target, bear
target, bull floor, bear ceiling - and ask of every structure two questions: does it pay if
the claim holds, and does it stop paying when the claim fails? A structure that wins about as
often either way is not expressing the thesis, whatever its EV says.

# When it applies
Every time a thesis is turned into legs: choosing between the playbook's menu and your own
candidates, reading `simulate_experiments`, and especially when every candidate on the board
is a vertical.

# What it means
Faithfulness is a property of where the strikes sit against the band, not of the family's
name. The shape is derived from the band and the spot - a claim that NVDA closes 222-232 with
spot at 224 is a RANGE claim, not a rally - and each family's strikes are anchored to the band
in expected-move units. The two questions are computed on the market's own distribution,
conditional on the band: E[pnl | band holds] after entry costs, P(win | holds) and P(win |
fails). The gates the playbook applies: every leg quoted, loss bounded, pays after entry costs
if the band holds, and wins at least 25 points more often when the band holds than when it
fails.

# Evidence
A fair-value board (spot 100, 7 days, 25% vol, 1-sigma $3.46), every structure priced on the
grid the stack scores with, so any preference is the reward's own:

| claim | survives | refused |
|---|---|---|
| range [98,102] (1.2s) | condor 97/99-101/103 (wins 100% holds / 4% fails), call fly 95/100/105, put credit 95/100 | call debit 100/105 pays -$85 when it holds; long straddle -$192; the WIDE condor 90/95-105/110 is indifferent (+0.23) |
| range [93,107] (4.0s) | condor 90/95-105/110 (91% / 0%) | the narrow condor pays -$9 when it holds; the fly -$29 |
| bullish target [103,108] | call debit 100/105 (100% / 21%), put credit 95/100 | every bearish and range structure; the spot-centred condor pays -$19 |
| bullish floor [98, inf) | put credit 95/100 (89% / 0%), call debit 100/105 | bear structures; a tight fly pays -$23 |

Two corrections to the intuition. A condor whose short strikes sit ON a target band is a
faithful expression of that target - the reward passes it, and it should. And a butterfly
narrower than the band loses inside the very band it claims to express (99/100/101 under
[98,102]: -$13 when the claim holds), so the reward cannot be gamed by ever-tighter flies.

Live, same day: NVDA 222-232 at 224.44 on the 09-11 chain (IV 31%) - condor, iron fly and
call fly all survive; the condor frees about a third of a vertical's capital at a similar
P(win), the iron fly trades P(win) for payoff, and only a long strangle wants vol expansion.
SPY's floor claim at 760 keeps the put credit and refuses the 765/777 call debit, which pays
-$202 when the floor merely holds.

# The catalogue is the live version; this page is why
The mapping itself is DATA the Coach moves - `data/state/levers/playbook.catalogue.json`,
seeded from `playbook.SEED_CATALOGUE` - scored by the gates above on every admitted
opportunity, with a shadow challenger on the same chain, and promoted on evidence. Every
proposal, and every structure the agent simulates itself, resolves at its expiry close
(`playbook_outcome`), which is the slow evidence that audits the fast reward. Read
`trdrbot playbook status` for survival by shape and family and outcomes by family;
`trdrbot playbook try TICKER --band LO,HI --horizon D` prices the catalogue on a live chain.
