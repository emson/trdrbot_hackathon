# Submission & Judging Guide

> **RE-VERIFIED 2026-08-30 directly against the live event page** (`lablab.ai/ai-hackathons/
> alpaca-ai-trading-agents-hackathon`) and the team's own submission page. This supersedes the
> 2026-08-26 version of this document, whose "four dimensions" judging claim was itself a
> correction of an earlier guess — and turns out to have been **wrong**, not just superseded.
> Read the whole file; the judging-criteria section below is the load-bearing correction.

## Submission Timeline

| Date/Time | Event |
|-----------|-------|
| August 28, 2026, 16:00 BST | Hackathon Kick-off |
| September 4, 2026, 16:00 BST = **15:00 UTC** | **SUBMISSION DEADLINE** ("End of Submissions!") |
| After Sept 4 | Judging Period |
| TBD | Winner Announcement |

As of 2026-08-30 (checked live): **5 days, 0 hours left.** Team `trdrbot`'s own page confirms:
**"Team Leader hasn't made a submission yet."**

## Core requirements (verified, verbatim from the challenge page)

- **Autonomous agents** — must build autonomous AI trading agents using Alpaca's Trading API.
- **MCP or CLI** — the project must use either Alpaca's MCP server or its CLI tools.
- **Options trading** — all strategies must incorporate options trading.

## Account requirements (verified — stricter than earlier drafts of this doc assumed)

- Explore/prototype freely on **any** paper account during development.
- **The final submission must run on a brand-new Alpaca paper account created specifically for
  this hackathon.** Verbatim: *"Projects run on an existing or reused account will not be
  eligible for judging."*
- **Starting balance must be set to $100,000.**
- **The Alpaca paper trading account ID itself is a required submission field** — not just an
  account "linked to profile". Verbatim: *"Your final submission must include the Alpaca paper
  trading account ID used for the hackathon. This allows the judging team to identify your
  trading activity and evaluate your P&L performance."*
- **Action needed:** confirm the account currently trading is (a) actually new/dedicated to this
  hackathon and (b) was started at exactly $100,000. If the account in use predates the
  hackathon or was reused from earlier prototyping, a fresh one is needed before submission.

## What the submission form asks for (verified — the platform's own "What to submit" list)

**Basic information**
- Project title
- Short description
- Long description
- Technology & category tags

**Cover image and presentation**
- Cover image
- Video presentation
- **Slide presentation** — a separate asset from the video; not previously documented here

**App hosting and repository**
- Public GitHub repository
- Demo application platform
- Application URL — a live/hosted demo URL, not just the repo
- **Alpaca paper trading account ID** (see above — explicitly required for judging)

**Social engagement (optional, but scored — see prize section)**
- Up to 5 links to posts on X or LinkedIn, tagging both `@lablabai` / lablab.ai and `@AlpacaHQ` /
  Alpaca

**Additional mandatory item, stated separately on the challenge page (not part of the form list
above, but required):**
- **A one-page write-up covering: your AI logic, your risk gates, and your Alpaca infrastructure
  implementation.** This is the closest match to what this repo already calls `SUBMISSION.md` —
  it does not yet exist and needs to be written to this exact brief (one page, three named
  topics).

## Judging Criteria — VERIFIED, REPLACING THE EARLIER "FOUR DIMENSIONS" CLAIM

The 2026-08-26 correction in this file claimed judging uses "Application of Technology,
Presentation, Business Value, Originality" and stated **"Raw P&L is not one of them."** Read
directly off the live page on 2026-08-30, that is wrong. The actual five categories, verbatim:

1. **P&L Performance** — "The trading performance of the submitted agent in the Alpaca paper
   trading environment. Judges will consider the project's P&L and how effectively the strategy
   performs through its trading activity."
2. **Technology Implementation** — how effectively the project uses Alpaca's Trading API, MCP
   server, CLI, and other required technologies to build an autonomous trading agent.
3. **Creativity & Originality** — originality of the concept, trading strategy, agent behavior,
   and overall approach. Judges value thoughtful and creative use of the technology.
4. **Presentation & Execution** — how clearly and effectively the project communicates its idea,
   demonstrates the agent in action, and presents the reasoning behind its strategy and results.
5. **Social engagement** — quality of build-in-public content AND the engagement it generates
   (likes, comments, shares).

**What this means for trdrbot specifically.** P&L genuinely is judged directly — the
"P&L doesn't matter over one week" thesis this whole project is built on is a real, measured, and
still-correct statistical fact (D-029, the 60%-edge-agent-beats-a-coinflip-69%-of-the-time
result), but it is not a reason to *omit* the P&L number from the submission; it is the reasoning
that should accompany it. The honest move given both truths at once: report the actual P&L
plainly (whatever it is), and use the calibration/attribution machinery to argue *why* a
short-window P&L number alone would be a bad way to judge trading skill — turning "Creativity &
Originality" and "Presentation & Execution" into the categories where the project's actual
differentiator (a system that knows the difference between being right and being lucky) does the
work P&L can't. Chasing P&L variance in the remaining days to look better on category 1 would
undermine categories 3 and 4, which this project has spent five phases earning honestly.

## Prizes (verified, corrects the earlier "estimated" breakdown)

**Total pool: $6,300** (not the $6,000 headline figure once stated elsewhere — Featherless
credits are counted in).

- 🥇 1st: **$2,500** + $300 in Featherless AI credits
- 🥈 2nd: **$1,500**
- 🥉 3rd: **$1,000**
- **Social Engagement Prize — 2 winning teams**, independent of the main placings: $500 USD per
  team + 1 month of Algo Trader Plus for every team member.

Prizes are paid to **individuals**, not teams — a team win requires designating one member to
receive payment, or confirming a split with lablab's finance team in advance. W-9 (US) or W-8BEN
(non-US) plus government photo ID and bank details are required before payment; paid within 90
days of event end once documents clear.

**Submissions must be original and MIT-compliant.** This repo currently has no `LICENSE` file —
needs one before submission if this term is to be satisfied cleanly.

## Best practices (unchanged, still sound)

- Submit well before the deadline, not at the last minute — the form itself may have quirks
  worth discovering with time to fix them.
- Verify every link (GitHub, demo URL, video) actually resolves before submitting.
- Keep a backup of everything submitted.

---

**Verified:** 2026-08-30, against the live event page and the team's own `/trdrbot` submission
page (both rendered via authenticated browser session, not a cached fetch — the event page
blocks the plain HTTP fetch this doc's earlier version relied on).

**Event page:** https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
**Team page:** https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon/trdrbot
