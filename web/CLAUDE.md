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

## Paraphrases the hero for a different audience (check for contradiction, not exact wording)

- `web/src/routes/submission/+page.svelte` — the "For judges" lead paragraph
  (more technical/detailed restatement), plus the five `CATEGORIES` card
  blurbs further down the same file
- `web/src/routes/how-it-works/+page.svelte` — the standfirst under
  "Five stages, looped so the system can learn from itself."
- `web/src/routes/+page.svelte` — the tiles/cards below the hero:
  - "Two questions, not one." section (the attribution 2×2)
  - "Three ways in." cards — The record / The machine / The scorecard
- `docs/deck.html` — the "What 'self-improving' actually means" slide and
  the closing slide ("Any agent can make money for a week…"). Treat these as
  the *backing evidence* for the hero's claims — if the hero says something
  these slides don't support, fix the hero, not the slides.

## Publish checklist for a copy-only change

1. Edit the source files above.
2. `cd web && node scripts/sync-static.mjs` (re-syncs the `docs/*.html`
   standalone documents into `static/`)
3. `npm run build`, then verify `build/index.html` and `build/ledger.html`
   are non-empty.
4. `npx wrangler pages deploy build --project-name trdrbot-com --branch main --commit-dirty=true`

Don't rely on `../scripts/publish.sh` for a copy-only change — it exports
the trading snapshot first and **no-ops if that snapshot's hash is
unchanged**, which it will be if no trades happened. It's built for
data refreshes, not content edits.
