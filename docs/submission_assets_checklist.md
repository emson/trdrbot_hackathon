# Submission Assets Checklist

What to hand Alpaca/lablab.ai judges so they can actually assess how well trdrbot performed —
not just whether it made money. Organized by tier: what's mandatory, what's strongly
recommended, and what's the real differentiator worth pushing hardest.

## Why this isn't just "export the P&L"

Raw P&L over an 8-day window is close to statistical noise — that's trdrbot's own founding
premise (a genuinely skilled 60%-edge agent only beats a coin flip 69% of the time over 20
trades). So this checklist covers both the raw ground truth (the account data) *and* the layer
of interpretation that makes the raw numbers mean something — calibration, attribution, declined
trades — which happens to be exactly what this project was built to produce.

## Tier 1 — Required by the hackathon rules

- [ ] **New, dedicated Alpaca paper account, linked to hackathon profile**
      No document needed — just confirm the linkage is actually done.
      **Verify on the actual submission form** whether that link gives Alpaca/lablab read access
      to trade data directly, or whether teams need to export/screenshot it themselves — our own
      docs don't specify which. If ambiguous, provide the exports below as a safety net regardless.
- [ ] **Working trading agent, demonstrably executing via Alpaca API/MCP/CLI**
      Covered by the repo + README (Tier 2).
- [ ] **Evidence of options trading**, multi-leg preferred (scored explicitly on sophistication)
      A few concrete examples with strikes, legs, and Greeks — not exhaustive.
- [ ] **Submission on lablab.ai**, before 15:00 UTC Sept 4 — submit early, not last-minute.

## Tier 2 — Recommended deliverables

- [ ] **Public GitHub repo**
      Public, not private — judges triaging many submissions won't request individual invites.
- [ ] **README with overview + setup instructions**
      Public. This is what actually gets read — should stand alone without requiring a second
      file to understand what the project does.
- [ ] **Strategy write-up**: trading logic, why options were chosen, risk management, market
      conditions tested
      Public. Its own scored category ("Trading Strategy Quality"). A few paragraphs of
      reasoning, not the full decision log.
- [ ] **Demo video or screenshots of trading activity**
      Public. Short — 2-5 minutes. Show the agent making one real decision end to end.

## Tier 3 — The assets that let anyone judge "how well," not just "whether"

This is where trdrbot has something most submissions won't: it tracks *why*, not just outcomes.
Push these hardest — they answer "Results & Performance" with more than a P&L number.

- [ ] **Portfolio/order history export** (Alpaca dashboard: portfolio_history, orders, positions)
      Public — nothing here is real money, so full disclosure is free. Redact the exact account
      number from screenshots regardless (no financial exposure, just no reason to broadcast an
      identifier unnecessarily). A dashboard screenshot or CSV is evidence, not argument — no
      narrative needed.
- [ ] **The journal** (`journal.jsonl`) — the full decision/execution/fill/reflection trail, with
      the model ID per decision
      Public, after verifying no secrets are logged (grep for key-shaped strings before
      publishing — the project has a documented history of credential-shadowing bugs, so check
      rather than assume). Excerpt a handful of representative entries in the write-up; the full
      file can sit in the repo for anyone who wants to dig.
- [ ] **Calibration report** (`trdrbot calibration` — Brier score + Murphy decomposition)
      Public. The single most credible performance metric available — answers a harder, more
      honest question than "did it make money." One paragraph explaining what it means, then the
      real number, whatever it is — including if unflattering.
- [ ] **Attribution breakdown** — the view-vs-structure 2x2, populated with real trade counts
      Public. The differentiator judges are least likely to have seen before: separates "right
      view, right structure" from "wrong view, got lucky" explicitly. Lead with this.
- [ ] **A few real declined-trade examples**, with the agent's own reasoning quoted verbatim
      Public. Most trading-bot demos only show wins — a well-reasoned "no" is stronger evidence
      of judgment quality than another win would be.
- [ ] **A real friction/cost example** (EV before vs. after transaction costs)
      Public. One or two concrete numbers — shows the agent isn't pricing off mid-price fantasy.

## Documentation depth guide

- **Write once, at depth, for judges:** a single submission-facing summary (`SUBMISSION.md`, or
  extend the README) — what the agent does, why this strategy approach, the calibration/
  attribution results, 2-3 concrete trade examples (a win, a loss where the view still held, a
  decline), honest limitations. Maps directly onto all five judging categories.
- **Leave available, don't summarize:** `specs/architecture.md`, `specs/decisions.md`,
  `specs/notes/*` — link as "design rationale, for the curious." Their value is existing and
  being internally consistent, not being read cover to cover. A judge triaging many submissions
  reads a few hundred words, not a design corpus.

## What NOT to make public (security/hygiene pass)

- [ ] API keys, secrets, `.env` — already `.gitignore`'d; double-check nothing was hand-committed
      before making the repo public.
- [ ] Exact account number in any dashboard screenshot or demo video — blur or crop it.
- [ ] Anything in `data/inbox/` or `data/journal.jsonl` — grep for key-shaped strings before
      publishing, as a final check rather than an assumption.
- [ ] Team members' personal details beyond what they're comfortable attaching to a public
      submission.

Everything else — trade sizes, dollar P&L, win/loss counts, the full reasoning trail — is
genuinely safe to publish in full. Paper trading removes the usual reason to redact trading
performance: no real capital, no counterparty risk, no regulatory disclosure concern.
