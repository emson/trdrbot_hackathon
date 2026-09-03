# Dev Journal - 2026-09-03: a second lever, a smaller deck, and the numbers stop drifting

Four threads today, in the order they actually happened: a second Coach lever for structure
choice, a rewrite of the submission deck down to something a judge can actually read, a git
authorship incident that turned out to be a misconfigured email pointing at a stranger's GitHub
account, and a small build pipeline so the deck's own numbers stop being retyped by hand. None of
these were planned together. Each one found the next.

---

## The playbook: structure choice becomes a measured lever

The maths was already there. `optmath` prices any single-expiry leg set, the sizer treats a
condor and a vertical fairly, friction is summed per real leg - iron condors, flies, strangles
have been legal and priceable since D-028. What was missing was any signal telling the decide
agent *which* structure fits *which* thesis shape. The journal showed only one- and two-leg
structures ever traded, and the technique pages that discuss the choice
(`what-am-i-actually-betting-on`, `credit-vs-debit-is-not-a-choice`) are never read by the decide
prompt - they reach the agent only as muse collision material.

The obvious fix - a mapping paragraph in `SYSTEM_PROMPT` - is a human-asserted rule nothing
scores. The project's own rule from D-088 says a choice like this should be DATA the Coach can
move, scored by arithmetic it cannot reach, promoted on evidence. So: a catalogue of structure
families, each declaring the thesis shapes it fits (range, bull target, bear target, bull floor,
bear ceiling - derived from the band and the spot, never the model's `direction` label) and where
its strikes sit against the band in expected-move units. Every admitted opportunity gets the
incumbent catalogue instantiated on the live chain, scored by `optmath.band_conditional` -
`experiments.attribute` mirrored pre-trade: does the structure pay when the thesis holds, and
does it stop paying when the thesis fails.

Two things the build found that the plan did not. A condor whose short strikes sit ON a target
band is a faithful expression of *that* target - the reward correctly passes it, which meant the
plan's own fair-value table (computed at spot-centred strikes) was the wrong fixture for the
pillar test, not the reward. And the gate's own chain page is the feed's first page - the nearest
expiry, 100 contracts - which on MRK matched the horizon and still carried one put against a 150
spot; `Chain.covers` now triggers a targeted refetch when the page lacks enough quoted strikes of
either right, found live within an hour of shipping the first version.

The registry generalisation underneath it mattered as much as the lever itself. `MUTATE_PROMPT`
had the muse's scoring paragraph and contract sentence hardcoded, so a second lever's challengers
would have been generated against the wrong subsystem's ruler - moved onto the `Lever` declaration
itself, with the muse's rendered prompt pinned byte-identical by test so the move could not be
felt. Found on the way: the live muse challenger `v1` carries a nine-dash echo of the mutation
prompt's own rule line, because `clean_prompt` matched only the literal ten-dash fence. Not edited
in place - editing either arm mid-trial closes the experiment as `operator_override` - just fixed
for the next mutation and logged as I-124. And a real cost of the new lever's own reward sitting
near 50%: at the global promotion floors an equal challenger clears `P(better) >= 0.90` by
sequential peeking about one time in three (I-125), so `playbook.catalogue` runs at 0.95 instead.

Six commits, `D-122`.

## The deck: 21 slides to 13

Then a different kind of work: "simplify the deck so people without context can follow it." The
loop was told three times over - a five-card overview, one slide per stage, then an architecture
diagram of the same five stages over the same four stores. Those seven slides became two: the
diagram, relabelled in plain language, and one new slide contrasting the model's single job
against everything code decides, which used to be scattered across four places. Jargon went too -
"falsifiable thesis" became "a claim that can be proved wrong", Brier/reliability/resolution
became what they actually tell you, the attribution grid's axes became "view right / view wrong"
against "made money / lost money" instead of the internal vocabulary (held/failed, thesis/
expression).

Two follow-on passes. First, the numbers were stale the moment they were retyped by hand - equity,
return, the calibration figures, even the deck's own claimed line count (22,900, when the real
count was 23,027 that day and would keep moving). Second, an author byline: name, personal site,
X handle, added to the deck's title slide, the how-it-works page, and the site footer, all from
one shared `siteConfig.author` entry so the three copies cannot drift the way the hero wording once
did. Fixing that surfaced an unrelated, real bug: `sync-static.mjs` had never once copied
`docs/assets/` into the built site, so every elf illustration in the hosted deck has been a 404 in
production since the deck was written. Confirmed live on `trdrbot.com` before fixing it.

## A stranger's GitHub account, in a private repo

Then a question that wasn't code at all: `github.com/emson/trdrbot_hackathon/commits?author=ben`
was attributing recent commits to a GitHub user who isn't the repo's owner. The local git history
told the whole story - every commit read `Ben Emson`, but the email on the 29 most recent ones was
`ben@users.noreply.github.com`, GitHub's legacy no-reply format, which happens to be a *different*
account's address (username `ben`, not `emson`). GitHub links commit authorship display to
whichever account owns the email, independent of the name field, so it had silently been crediting
a stranger for two days of real work.

The cause: this repository's local `.git/config` had a `user.email` override that isn't the
owner's, set sometime the evening before, overriding the correct global config. Fixed in two parts
- the local override removed so future commits are right, and the 29 already-pushed commits
rewritten with `git-filter-repo` and a mailmap, verified byte-identical in tree content against
the pre-rewrite state before force-pushing. `git-filter-repo` also strips the `origin` remote as a
safety measure, which wiped the branch's upstream tracking - the next `git push` failed with "no
upstream branch", diagnosed as a plain fast-forward and fixed with `git push -u`.

## The figures pipeline: one command, one set of figures

The deck-numbers fix above was still a hand job - type the right numbers once, and they go stale
again the moment anyone edits the deck or the loop keeps trading. `site_export.py` already writes
`web/src/lib/data/snapshot.json` on every tick with almost everything the deck needs; the actual
gap was that nothing read the deck's numbers *from* it.

Validated before designing anything: every trading figure already in the deck was checked against
the live snapshot, formatted through the site's own `format.js`. Twelve of twelve reproduced
byte-identically. This was a wiring problem, not a data problem.

The design: a figure is a `<span data-figure="account.equity" data-format="usd0">$114,085</span>`
- baked text, not a placeholder, because the deck is a standalone document hosted and opened
as-is, and a template marker left in place would render literally to anyone viewing the source. An
injector (`inject-figures.mjs`, zero new dependencies - Node's own built-in test runner covers it)
rewrites the text from the snapshot; a second run reports zero changes; `--check` is the drift
detector the original request actually asked for.

Two category errors the injector would otherwise have quietly baked over, both worth naming
because they are the same mistake in different clothes. The worked-example slide's "+129.1%" is a
historical fact about one specific trade from 28 August - not the book's current closed-P&L
maximum, even though the two numbers agree today by coincidence. Tagging it would let a bigger
winner closing next week silently rewrite what a *specific past trade* actually did. And the
size-ladder diagram's four rung headers (EXPLORE / ESTABLISH / SCALE / MATURE) are permanent
column names, not "the current tier" - only the prose line naming where Theo actually sits is
live. Getting this distinction right mattered more than the wiring itself.

`scripts/release.sh` is the "one command": export with `--refresh-tests` (the test count is the
one figure expensive enough - a subprocess importing the whole suite - that it does not run on
every publish, only here), inject `--write` into `docs/deck.html` in place, regenerate the PDF,
build the site locally, then stop. It never commits, pushes, or deploys - review the diff, then
decide. `publish.sh`, which runs on the trading loop, injects only into the generated static copy,
so the live site's numbers stay current with zero git churn on the tracked source.

Running `release.sh` for real (not just syntax-checking it) caught a bug in itself: the local PDF
render server was started as a backgrounded subshell, so `$!` captured the subshell's pid rather
than the actual `python3` process holding the port - the cleanup trap was killing nothing, and
`lsof` still showed the port listening after a completed run. Fixed with `--directory`, which
needs no subshell at all.

## What keeps being true

Every thread today was some version of the same shape: a number, a name, or a piece of state that
was correct once and had no mechanism keeping it that way. A prompt paragraph hardcoded to one
lever. A slide retyped by hand. An email that was right on one machine and wrong in this one
repo's config. A `sync-static.mjs` that never copied the folder its own output referenced. None of
these were exotic bugs - each one was found by asking, once, *is this still true right now*, and
then building the thing that keeps asking.

**Shipped:** D-122 (the playbook, six commits), the deck rewrite and its author byline, the git
authorship rewrite, and notes/027's figures pipeline (five commits). 757 tests, ruff clean, both
new scripts run for real before being called done.
