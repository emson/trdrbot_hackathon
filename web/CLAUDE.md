# trdrbot.com content map

The hero tagline and elevator pitch are duplicated across several files by
necessity (page `<title>`s, meta descriptions, a standalone slide deck, a
design-system reference page). None of these import from a shared source —
they're plain text in each file. **Whenever the hero wording changes, check
every file below before calling the update done**, not just `+page.svelte`.

## Source of truth

- `web/src/routes/+page.svelte` — the hero `<h1>` + lead paragraph. This is
  the canonical wording; everything else either quotes it or paraphrases it
  for a different audience.

## Echoes the hero near-verbatim (update together, same wording)

- `web/src/routes/+page.svelte` — its own `<svelte:head><title>`
- `web/src/routes/+layout.svelte` — sitewide `<title>` + meta description
  (this is what search results and social-share previews show)
- `docs/deck.html` — title slide (`data-title="Theo — the one sentence"`):
  `<h1>` + lead paragraph, and the document's own `<title>`/meta description
- `docs/design_system.html` — section 8 "Applied" → "Website hero (brand
  register)" example block

`docs/deck.html` and `docs/design_system.html` are the **source** files.
`web/static/deck.html` and `web/static/design-system.html` are generated —
never hand-edit them; run `node scripts/sync-static.mjs` (from `web/`) to
regenerate them after editing the `docs/` originals.

`docs/deck.pdf` is also generated from `docs/deck.html`, and it is what the
submission form links to — so it goes stale silently. After any deck edit
(prose, layout, or figures), regenerate it with `../scripts/release.sh` from
`web/` (or run it from the repo root as `./scripts/release.sh`) — it re-exports
the record, refreshes every tagged figure in `docs/deck.html` in place, and
re-renders the PDF from the updated HTML, all in one command. It touches
tracked source files and is meant to be run by hand and reviewed
(`git diff docs/deck.html`) before committing — never on a loop, and it never
commits, pushes, or deploys on its own.

One slide per 13.333in × 7.5in page, light palette forced, print rules in the
deck's own `@media print` block. Check the page count matches the slide count
(`release.sh`'s own PDF step prints the byte count it wrote; open the file to
confirm the page count by eye after a structural change to the slides).

## Figures: numbers the deck reads from the record instead of carrying by hand

The deck used to have ~16 hand-typed numbers (equity, position counts,
calibration, lines of code, issue counts…) that duplicated what
`web/src/lib/data/snapshot.json` already knows, and drifted the moment anyone
edited the deck without also re-deriving every figure in it by hand. Any
number in `docs/deck.html` that is a FACT FROM THE RECORD — not narrative
prose about a specific dated event — should be a tagged figure instead:

```html
<span data-figure="account.equity" data-format="usd0">$116,301</span>
```

- `data-figure` is a dot-path into `snapshot.json` (e.g. `calibration.n`,
  `repo.python_lines`, `positions_summary.closed_pnl_max_pct`).
- `data-format` names a formatter exported from `web/src/lib/format.js` -
  the SAME module the Svelte pages use, so the deck and the site can never
  render one fact two different ways. Add a formatter there before tagging a
  figure that needs one that doesn't exist yet; keep it a plain function of
  one value (see `usd0`/`num1`/`num3`/`upper`/`deckDateTime` for the shapes
  already in use) since the injector calls it with no other arguments.
- The element must be a `<span>` containing **only** the number - no nested
  markup, and no other words inside the same span (wrap only the digits:
  `<strong><span data-figure="...">9.8</span> independent</strong>`, not
  `<strong data-figure="...">9.8 independent</strong>`).

**A worked example is not the same thing as a live figure.** The "A real
trade" slides quote specific numbers from one named, dated trade (`+129.1%`
on the 28 August SPY spread) - that is a historical fact about an event, not
a fact the current record restates, and tagging it would let some *other*
position's later result silently overwrite what that specific trade actually
did. Only the Results slide's book-wide aggregate is tagged. The same
reasoning protects the ladder diagram's four rung names (EXPLORE / ESTABLISH
/ SCALE / MATURE) - permanent column headers, not "the current tier" (only
the prose line naming the current tier is tagged).

Two scripts, two different jobs - see `../scripts/release.sh` and
`../scripts/publish.sh` for the full reasoning:

- **`./scripts/release.sh`** (by hand, before submitting) refreshes the
  figures IN `docs/deck.html` itself, regenerates the PDF, and stops - review
  the diff, then commit. This is the "one command" for a figures refresh.
- **`./scripts/publish.sh`** (the automated loop) refreshes figures only in
  the generated `web/static/deck.html` copy, so the live site's numbers never
  go stale without ever dirtying the tracked deck source.
- **`node web/scripts/inject-figures.mjs snapshot.json doc.html`** (no flag)
  checks without writing - it exits non-zero if any tagged figure disagrees
  with the record, which is the drift check itself. Add `--write` to fix it
  in place.

Adding a NEW tagged figure: put the current, correct value as the element's
baked text (so the document is still right if the script never runs again),
run `node web/scripts/inject-figures.mjs web/src/lib/data/snapshot.json
docs/deck.html` (no `--write`) to confirm it resolves cleanly, then
`--write` once to fix any typo before committing.

## Paraphrases the hero for a different audience (check for contradiction, not exact wording)

- `web/src/routes/submission/+page.svelte` — the "For judges" lead paragraph
  (more technical/detailed restatement), plus the five `CATEGORIES` card
  blurbs further down the same file
- `web/src/routes/how-it-works/+page.svelte` — the standfirst under
  "Five stages, looped so the system can learn from itself."
- `web/src/routes/+page.svelte` — the tiles/cards below the hero:
  - "Two questions, not one." section (the attribution 2×2)
  - "Three ways in." cards — The record / The machine / The scorecard
- `web/src/routes/demo/+page.svelte` — the standfirst under "Watch Theo
  decide.", and each frame's own heading (see "The demo page" below)
- `docs/deck.html` — the "What the model decides, and what the code decides"
  slide and the closing slide ("Any agent can make money for a week…"). Treat
  these as the *backing evidence* for the hero's claims — if the hero says
  something these slides don't support, fix the hero, not the slides.

## The demo page (notes/028, restructured as "Theo's Floor")

`/demo` replays real decide cycles from `snapshot.cycles[]` (the `cycles`,
`funnel`, `coach`, and extended `forecasts_resolved` sections `site_export.py`
builds - see `build_cycles`, `build_funnel`, `build_coach`,
`extend_forecasts`). The copy in `+page.svelte`'s frames is the source of
truth for that page's wording; check it, not this file, before rewriting it.

**Three tabs, not one scroll.** The five stages are still all there and still
in order, but split by the question a reader is asking rather than stacked:

- **The loop** - the cycle reel, then the claim (the tape plus the modelled
  cone), the edge, what arrived, the competing claims, the structures priced
  and thrown out, the payoff, what it did, how it scored, what it kept.
- **The book** - the annotated equity curve, every position, the attribution
  table as bars, the reliability plot, the forecast dots, and the funnel.
- **The coach** - one posterior trace per lever, then `CoachCard`.

**The cone and the edge are MODELLED, and only drawn when the record can
back them.** `marketFor` looks for a chain the cycle actually priced, then
for a position it opened (`entry_iv`/`entry_spot`), and returns null when
neither exists - most declined cycles never priced a chain, and those draw a
band with no cone plus a line saying so. `P(band holds)` prefers the agent's
OWN recorded `p_band` (the number it gated on) over anything recomputed here.
The lognormal is drift-zero with no skew, matching what the playbook itself
scores against; `sigmaT`/`coneBounds`/`pBandHolds` are in `demo.js` and
node-tested.

Two rules that matter more than the wording:

- **The reel selects itself.** `build_cycles`' reel rule (the latest cycle
  always qualifies; an older one needs to have traded, recorded a thesis, or
  priced a structure) picks which cycles appear - never hand-pick a "good"
  cycle by editing the exporter or the page.
- **A frame renders `not recorded` or its own stated empty line, never a
  reconstruction.** If a value is not on a `cycles[]` row, it does not
  appear - it is not derived, parsed from prose, or guessed at on the page.

`web/src/lib/demo.js` holds the page's view-model logic (cycle/thesis/
candidate selection, the URL hash round-trip, `daysUntil` computed from
`generatedAt` rather than the browser clock) - node-tested in
`scripts/demo.test.mjs`, same runner as `inject-figures.test.mjs`.

## Publish checklist for a copy or code change

1. Edit the source files above, commit.
2. `./scripts/publish.sh --force` from the repo root.

That one command re-exports the trading snapshot, re-syncs the `docs/*.html`
standalone documents into `static/`, refreshes the static deck's figures,
builds, verifies `build/index.html` and `build/ledger.html` are non-empty,
and deploys to production. `--force` is what makes it deploy when the record
hasn't moved: without it, `publish.sh` is the loop's form and **no-ops if the
snapshot's hash is unchanged**, which it will be if no trades happened since
the last tick's publish. Never deploy with a bare `npm run build` +
`wrangler` - that path skips the export, and the site goes live carrying an
older tick's figures next to the new copy (it happened; the redeploy on
2026-09-03 shipped tick 844's numbers after the loop had moved on).

For a FIGURES-only refresh (nobody edited any prose, the numbers just went
stale), use `../scripts/release.sh` instead of this checklist - it does
steps 1-3 above for the deck's tagged figures specifically, plus the PDF, in
one command. Reach for the manual checklist when prose, layout, or anything
outside `docs/deck.html` changed.
