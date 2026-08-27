# Trader Review — the system through a professional's eyes

2026-08-27. Full-logic review with a working trader's priorities: risk first, execution second,
edge third. Findings F1-F5 implemented same-day (D-036); F6-F9 evaluated and parked with
reasons.

## What already meets the professional bar

Worth stating, because it shapes what was NOT changed: refusing unbounded-loss structures
outright; friction charged before the decision; ranking candidates by thesis edge rather than
model EV; luck-neutral attribution; "not trading is a valid output" demonstrated live six times;
profit target at +50% of credit and a pre-expiry time stop (both consistent with practitioner
research on short premium); premise-verification against the live tape; whole-position closes
only (never legging out of a spread).

## Findings — implemented (D-036)

**F1 (most serious): stated invalidation and coded exits disagreed.** The agent narrated
"invalidated on a decisive break below ~757-758" while its recorded rules watched only the
position MARK. The mark is the noisiest signal an options position produces — a wide quote can
put a -100%-of-credit print on a healthy spread, and conversely the underlying can break the
thesis while a stale mark still looks fine. Professionals exit spreads on the underlying
breaking the thesis level. Fix: `underlying_stop` exit-rule type (direction + level, same
N-of-M debounce, immediate at 1% beyond the level), the snapshot now carries a live underlying
mark for every open position's underlying, and `record_position` exposes
`underlying_stop_below/_above` with the prompt telling the agent to set it at the level it
would state out loud. Verified: 2-of-3 debounce fires at 756.8 vs a 757.5 level; 748 fires
immediately; missing price data holds safely.

**F2: no portfolio-level risk cap.** Per-position 5% + count-division existed, but nothing
stopped the BOOK: five defined-risk positions at 5% each is a 25% correlated bet wearing five
hats — especially here, where every candidate so far shares one macro factor. Fix:
`PORTFOLIO_MAX_AT_RISK = 0.15` of equity across the sum of open defined max-losses plus the
candidate; positions store `max_loss_usd` at entry; sizing shrinks to fit the remaining budget
and refuses when full ("the book, not this trade, is the bet"). Verified: 3 contracts on an
empty book, still 3 at $11k open risk, refused at $14.5k. Lenient by design on legacy
positions (unknown risk counts as zero) — refusing would deadlock the book.

**F3: friction was a flat 10% of premium.** Real spreads are wildly non-uniform — 7% on a
liquid SPY call, 30%+ on a single-name weekly — and the agent already HAS the quotes when it
simulates. Fix: `simulate_experiments` accepts optional bid/ask per leg; when every leg has a
quote pair, friction = one full spread per leg (entry + exit each cross half), else the flat
model remains. The mid-vs-actual distinction now flows into EV-after-costs, which is the number
that has decided every trade so far.

**F4: no event calendar despite a known landmine.** Payrolls lands ON the deadline day —
derivable by arithmetic (first Friday), no model memory needed. Fix: `events:` in config
(rule-derived or user-verified dates only, per D-032's date discipline), rendered into the
decide context for anything within 14 days, labelled "binary risk - check every holding
window."

**F5: no execution discipline in the prompt.** Nothing told the agent limit-vs-market. A market
order on a wide options book donates the full spread instantly. Fix: system prompt — always
limit orders at mid or better; an unfilled limit repriced costs cents, a crossed spread costs
everything at once.

## Findings — evaluated, deliberately not implemented

**F6: contest variance.** Kelly maximises long-run log growth; a one-week contest scored partly
on final P&L rewards variance that Kelly suppresses. A pure P&L contest would argue for
2-3x the sizing multiplier. Held off because the rubric scores methodology and presentation as
much as profit, and discipline IS our differentiator. Revisit ~Sept 1: flat P&L + a proven
calibration record would justify raising `UNPROVEN_KELLY`/`ESTABLISHED_KELLY` deliberately, as
a recorded decision.

**F7: order-rate circuit breaker.** A pro desk has a daily-loss kill switch. D-009 (no
guardrails) reflects an explicit user instruction, and the existing protections (tool_guard
duplicate-order block, INV-17 exactly-once transitions, agent-authored exits) cover the bug
classes seen so far. Parked; would be infra-vs-bugs, not judgment-gating, if ever revisited.

**F8: IV rank.** Structure selection (credit vs debit) properly keys off where IV sits in its
own history, and we have no IV time series — realized-vol percentile is the standing proxy and
the agent has used cross-sectional IV comparisons well (call-side vs put-side skew, IV-vs-
realized). Building an IV history store is post-hackathon material.

**F9: marking-vs-liquidation honesty.** Mark-to-mid overstates what a position would fetch.
The real-spread friction (F3) now prices this at entry; exit rules still evaluate marks, but
underlying stops (F1) remove the worst consequence. Acceptable residual.

## The one-line summary a trader would give

"Your edge process was already better than most desks. Your risk process watched the wrong
variable (mark, not underlying), had no book-level limit, and didn't know payrolls falls on
your last day. Now it does."
