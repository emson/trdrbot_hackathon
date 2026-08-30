# Submission Assets Checklist

> **RE-VERIFIED 2026-08-30** directly against the live event page and the team's own `/trdrbot`
> submission page (see `submission_and_judging.md` for the full verification note — the earlier
> "four dimensions, no P&L" judging claim this checklist was written against was wrong). Tier 1
> and Tier 2 below are rewritten to the platform's actual field list; Tier 3 is unchanged and
> still the right differentiation strategy.

What to hand Alpaca/lablab.ai judges so they can actually assess how well trdrbot performed —
not just whether it made money. Organized by tier: what's mandatory, what's strongly
recommended, and what's the real differentiator worth pushing hardest.

## Why this isn't just "export the P&L"

P&L Performance **is** one of the five real judging categories (verified) — this checklist is
not an argument for omitting it. But raw P&L over a one-week window is close to statistical
noise, trdrbot's own founding premise (a genuinely skilled 60%-edge agent only beats a coin flip
69% of the time over 20 trades). So the move is to report the P&L number plainly *and* supply the
layer of interpretation that makes it mean something — calibration, attribution, declined trades
— which happens to be exactly what this project was built to produce, and is what should carry
the Creativity/Originality and Presentation categories even where the P&L number itself is thin
(as it currently is: 1 resolved forecast, 0 attributed positions as of 2026-08-30 — expected,
not a bug, since thesis horizons run to 09-03).

## Tier 1 — Required by the hackathon rules (verified against the live form)

- [ ] **Brand-new, dedicated Alpaca paper account, starting balance exactly $100,000**
      Verbatim requirement: *"Projects run on an existing or reused account will not be eligible
      for judging."* **Action needed:** confirm the account currently trading was actually
      created fresh for this hackathon, not reused from earlier prototyping - if unsure, create
      a new one and let it accrue a few real ticks before submission rather than submitting late.
- [ ] **The Alpaca paper trading account ID**, entered directly into the submission form
      Not just "linked to profile" - it is its own required field, stated as how judges identify
      trading activity and evaluate P&L. Have it ready, unredacted, for the form itself (redact
      it only in anything made PUBLIC - screenshots, video, repo).
- [ ] **Working trading agent, demonstrably executing via Alpaca's Trading API + MCP or CLI**
      Covered by the repo + README.
- [ ] **Evidence of options trading**, multi-leg preferred (scored explicitly on sophistication)
      A few concrete examples with strikes, legs, and Greeks - not exhaustive.
- [ ] **A one-page write-up covering three named topics: AI logic, risk gates, Alpaca
      infrastructure implementation**
      This is its own explicit, separate requirement on the challenge page - distinct from the
      form's "long description" field. Does not exist yet (`SUBMISSION.md` or equivalent).
      One page means one page: this is the tightest-scoped asset on the list, not the deepest.
- [ ] **Submission on lablab.ai**, before 15:00 UTC (16:00 BST) Sept 4 - submit early, not
      last-minute. As of 2026-08-30, no submission has been made yet.

## Tier 2 — Required submission-form fields, not "recommended" (corrected)

Everything below is a field the live form actually asks for - this tier was previously labelled
"recommended" on an assumption; it is closer to mandatory in practice since the form has a slot
for each.

- [ ] **Project title, short description, long description, technology & category tags**
      The form's own basic-info fields. Not yet drafted.
- [ ] **Cover image**
      A single representative image for the project card/listing.
- [ ] **Video presentation**
      Public. Short - 2-5 minutes. Show the agent making one real decision end to end, ideally
      including a declined trade (see Tier 3) - most demos only ever show a "yes".
- [ ] **Slide presentation**
      A SEPARATE asset from the video, not previously tracked in this checklist. A short deck
      (5-10 slides) covering the same ground as the one-page write-up, structured for a live or
      recorded walkthrough rather than as a document to read.
- [ ] **Public GitHub repo**
      Public, not private - judges triaging many submissions won't request individual invites.
      **Currently no git remote is configured** (checked 2026-08-30) - the repo has never been
      pushed anywhere. Needs a remote, a push, and the visibility set to public.
      **Needs a `LICENSE` file** - the prize terms require submissions be "MIT-compliant"; none
      exists in the repo today.
- [ ] **README with overview + setup instructions**
      Public. Already exists and is thorough - the main gap is that it is written for a
      developer picking up the code, not a judge triaging many submissions in a few minutes; the
      one-page write-up above is the judge-facing complement, not a replacement.
- [ ] **A hosted "demo application" + its URL**
      A live application URL is its own form field, separate from the GitHub repo link. trdrbot
      is currently a CLI/background-loop system with no web frontend - **decide what this field
      points to**: candidates are the generated `trdrbot report` HTML (static, could be hosted
      as-is), a link to one of this project's own published Artifact reports, or a short note in
      the long-description field explaining the system is agent-driven with no UI by design,
      pointing instead at the video. Needs an explicit decision, not a default.

## Tier 3 — The assets that let anyone judge "how well," not just "whether"

This is where trdrbot has something most submissions won't: it tracks *why*, not just outcomes.
Push these hardest — they carry the P&L Performance and Creativity & Originality categories with
more than a bare number, and are the material the one-page write-up and slide deck should draw
from directly.

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
      **Status as of 2026-08-30: 1 of 68 forecasts resolved** (68 pending — most horizons run to
      09-03, just before the deadline). This will fill in over the remaining days but may still
      be thin at submission time. That is not a flaw to hide — it is exactly the "n=1, treat
      with the caution the sample size demands" honesty the whole project is built around
      (README's own "Honest limitations" section says this already). State the sample size next
      to the number, every time it's cited.
- [ ] **Attribution breakdown** — the view-vs-structure 2x2, populated with real trade counts
      Public. The differentiator judges are least likely to have seen before: separates "right
      view, right structure" from "wrong view, got lucky" explicitly. Lead with this.
      **Status as of 2026-08-30: 0 of 3 positions attributed yet** (2 closed positions have
      thesis horizons of 09-03; the first-ever SPY position has none by design — see README's
      documented limitation, a thesis fabricated retroactively would be worse than the gap).
      Re-check close to the deadline; the two 09-03 horizons should resolve just in time.
- [ ] **A few real declined-trade examples**, with the agent's own reasoning quoted verbatim
      Public. Most trading-bot demos only show wins — a well-reasoned "no" is stronger evidence
      of judgment quality than another win would be.
- [ ] **A real friction/cost example** (EV before vs. after transaction costs)
      Public. One or two concrete numbers — shows the agent isn't pricing off mid-price fantasy.

## Tier 4 — Social engagement (its own scored category, optional but not free to skip)

- [ ] **Up to 5 links to X or LinkedIn posts**, tagging `@lablabai` / lablab.ai and `@AlpacaHQ` /
      Alpaca. Scored on BOTH content quality and the engagement it generates (likes, comments,
      shares) - two separate winning teams get a dedicated $500 + subscriptions prize for this
      category alone, independent of the main placings.
      `docs/social_media_playbook.md` already has a ready-to-adapt diary-entry draft set, written
      before this category's scoring weight was confirmed live - still the right voice and
      content, now confirmed worth the effort rather than optional flavour.
      **Currently: zero posts published.** Needs a decision on whether to run this before
      drafting content.

## Documentation depth guide

- **Write once, at depth, for judges:** the mandatory one-page write-up (`SUBMISSION.md`),
  scoped to its actual brief — AI logic, risk gates, Alpaca infrastructure implementation — plus
  the calibration/attribution results, 2-3 concrete trade examples (a win, a loss where the view
  still held, a decline), and honest limitations, as space allows within one page. Maps directly
  onto all five judging categories, but stays ONE page — the long-description form field is
  where extra room exists if needed, not this document.
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
