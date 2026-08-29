---
sources:
- id: src-1
  resource: specs/notes/018_calibration_harmony.md
  author: trdrbot/review
  last_modified: '2026-08-29T12:58:07.628792+00:00'
type: Technique
generated:
  at: '2026-08-29T12:58:07.629543+00:00'
---

# Rule
Every number a decision leans on must name the evidence stream that audits it. Before trusting
a probability, a threshold, or a correction, ask: what has ever scored this against reality,
and how recently? A number nothing audits is the one that lies longest.

# When it applies
When a gate refuses many candidates for one numeric reason; when adopting any parameter fitted
from history; when two subsystems disagree about the same quantity; when a comparison keeps
returning "no difference".

# The audit map
Each layer is scored by the densest stream that can score it honestly, and audited by the next
slower, truer one:

| quantity | scored by | cadence | audited by |
|---|---|---|---|
| model distribution (bootstrap, grids) | historic replay, holdout-vetoed | minutes, thousands of samples | live forward resolutions |
| my stated probabilities | live resolutions (Brier/Murphy) | days | realized P&L and attribution |
| prompt/policy variants | paired A/B trials against the gates | hours | resolved outcomes of their theses |
| gate thresholds | gate regret (rejected theses still resolve) | days | the same |
| memory blocks | scored outcomes (Beta posteriors) | days | retrieval usefulness over regimes |

# What it means
Fast evidence proposes; slow evidence disposes. A fit that only works in-sample ships as
no-change. A correction that worked and then stops working on live data is a regime signal.
And failed fixes are recorded WITH their evidence (the graveyard rule) - a rejected idea with
its numbers prevents the next person, or the next version of me, from re-trying it blind.

# Where it came from
The bootstrap base rate ran unaudited for the system's whole life and was measured 15-23 points
overconfident exactly where credit spreads live - while the improvement loop was busy tuning a
prompt to please the broken number. One afternoon of historic replay found what no amount of
prompt evolution could have fixed.
