# Dev Journal - 2026-08-30 (third entry): from correct to legible

The first two entries today covered phase 4 (One Measure) and phase 6 (the sibling sweep) - eleven
work units, ten more, twenty-one defects closed between them. This entry covers what happened
after the code was done: turning a system that is now provably more correct into one a stranger -
a hackathon judge, someone reading a repo cold - can actually verify is correct, without taking
the README's word for it. Same day, same discipline, a different kind of bug.

---

## The throughline: an unverified claim is the same defect at a different layer

Twice today, work that looked like writing stopped and became fact-checking instead, for the same
reason two of the phase's code fixes did: something had been asserted once, copied forward, and
never re-checked against the thing it claimed to describe.

`docs/submission_and_judging.md` carried a "four dimensions, no P&L" reading of the hackathon's
judging criteria - itself already a correction of an earlier guess, dated 2026-08-26, and treated
since as settled. It was wrong. Read directly off the live event page, there are five categories
and P&L Performance is the first of them, named explicitly. Four days of planning - including this
project's own founding argument that raw P&L is close to noise over one week - had been built
partly on a claim nobody had gone back to check.

That is I-43's shape from this morning's entry: a headline that felt right, wasn't re-verified
against its source, and sat in a ledger as if it had been. The fix there was to correct the record
in place rather than quietly drop it. The fix here was the same move, applied to prose instead of
code: read the actual page, replace the wrong claim with the verified one, and say plainly in the
document that the earlier version was wrong, not just superseded.

## Evals: the answer was "no, we have enough," and it's now a rule instead of a memory

The open question from the morning - do more evals need adding, and does that need a convention -
resolved without new tests. `docs/principles_testing.md`'s four-pillars section, written during
phase 4, already says when a new eval earns its place: it pins a relationship (`PILLAR-1`: the gate
opens iff EV-after-costs is positive), not a threshold, and most proposed evals fail that test.
The gap wasn't missing evals, it was that the rule for judging a proposed eval lived in one
person's head instead of in the repo.

`AGENTS.md` closes that gap, and states the evals answer as its own line rather than as a
paragraph someone would have to remember to re-derive:

    the four pillars section governs when a new eval is warranted; most of the time it isn't.

It exists at the repo root for the reason the project's own three-layer docs model
(`docs/principles_README.md`) argues for: a reader arriving cold - human or agent - needs one page
that says which of the principles docs to read *before* touching tests, production code, or an
LLM-facing tool, not a wiki to search. `CLAUDE.md` is a symlink to it, so the same page answers
both readers without two copies to keep in sync.

## SUBMISSION.md: the one page the other five phases were building toward

The hackathon's own brief is narrow and specific - one page, three named topics: AI logic, risk
gates, Alpaca infrastructure implementation. `SUBMISSION.md` is written to exactly that brief, at
roughly 830 words, plus a closing "Honest limitations" paragraph the brief doesn't require but the
project's own convention (README's own limitations section) does.

The discipline that mattered was refusing to write a single number that wasn't already measured
and sitting somewhere in the repo. The two headline figures - the MCP session-reuse win (-78%
wall-clock, from sharing one stdio session per tick instead of respawning per call) and the
calibration argument (a genuinely 60%-edge agent only beats a coin flip 69% of the time over 20
trades, D-029) - were checked against their source before being typed, not recalled from memory.
A one-page write-up is exactly the kind of document where a rounded-off or misremembered number is
invisible to the writer and load-bearing to the reader.

## Two explainers, for two different readers

The one-pager exists twice, deliberately, because a submission-form field and a person reading for
five minutes want different things from the same content. The Markdown is what the form asks for.
The HTML version - "Right or Lucky," published as an artifact, set in Atkinson Hyperlegible - is
the same words with typographic hierarchy a form field can't give them: the `.eg`/`.why` structure
elsewhere in this project's docs, applied to prose instead of code, so a skim gets the section
headers and a close read gets the reasoning.

A specific question about the limitations section - what does "calendar/diagonal spreads are
refused" actually mean, and why - turned into a small piece of the same explaining work. The answer
is not "unsupported feature," it's the risk-gates philosophy from `SUBMISSION.md` applied to
pricing rather than sizing: a calendar spread's value depends on the *far* leg's implied vol at the
*near* leg's expiry, which is a forecast the system has no model for, and rather than substitute a
flat-vol guess for a number it cannot measure, the sizing tool refuses the whole structure. It's
the same refusal shape as Kelly refusing unbounded loss - a `SimStructure` that can't be priced
honestly doesn't get priced optimistically.

## The architecture map, and checking the check

The interactive architecture explorer ("The Trdrbot Loop") was built to answer a harder version of
the same question the one-pager answers: not just what the system does, but which of the ~45 real
modules does which part of it, with a live worked example rather than an abstract description.

Its first version had a bug the user caught before I did: arrow labels between the four main
stages were sized for gaps narrower than the label text itself, so text spilled across box edges.
The fix was straightforward - wider gaps, shorter labels, boxes re-sized to fit two to three lines
of subtext with real padding. What mattered more than the fix was how it got checked. An earlier
geometry pass in this same session had been verified by arithmetic alone (box width minus label
width, on paper) and looked fine until the user actually looked at it. This time the check was a
real screenshot, taken twice - once against the published artifact directly, once against the file
served locally to get past the artifact viewer's iframe not exposing scroll state to the outer
page - specifically because "I calculated it and it should fit" had already been wrong once today
in spirit if not in this exact file.

The rebuild also added what the user asked for beyond the fix: a plain-language overview before any
diagram; a "how it works / example / why" treatment for every stage; a seven-step worked example
built from the repo's own live SPY position - the real thesis text, the real breakevens, the real
exit rules, the real timestamps - rather than an invented one; and a closing reference section
naming every real module (`muse`, `coach`, `reconcile`, `optmath`, and around forty others) so
nothing in the diagram is a euphemism for a subsystem the reader can't go find.

## What's left, honestly

`SUBMISSION.md` is written but not yet committed. The submission checklist's Tier 1/2 items -
confirming the trading account is genuinely fresh and dedicated, recording video and slides,
pushing the repo public with a `LICENSE` file, filing the account ID into the form, the submission
itself - are all still open, and all of them need a human, not more writing. The judging-criteria
correction closes the biggest risk in the submission strategy (P&L is scored directly, not just
context), but the P&L number itself is still thin by construction: one resolved forecast, most
thesis horizons running to the day before the deadline. That's the same honesty the rest of the
project has been built around, stated here rather than discovered by a judge.
