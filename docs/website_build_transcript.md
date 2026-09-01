# trdrbot.com — website build transcript

> **Audience:** an AI coding agent implementing this end to end, with no prior context beyond
> this repo. Everything needed to build, deploy and keep publishing the site is here.
> **Written:** 2026-09-01. **Hard deadline:** 2026-09-04 15:00 UTC (16:00 BST).
> **Status when written:** tick 597, equity $103,555.81, 4 positions, 0 published site.

---

## 0. The one-paragraph brief

Build `trdrbot.com`: a static SvelteKit 5 site, prerendered, deployed to Cloudflare Pages via
`wrangler`, that presents the running trdrbot agent to hackathon judges and to anyone who follows
a link from social media. Its content is **generated from the agent's own live files** by a Python
exporter in this repo, and a decoupled publisher loop re-exports, rebuilds and redeploys every ~10
minutes so new trades appear without anyone touching it. The site's job, in order: satisfy the
hackathon's *Application URL* requirement; make the project's differentiator (it knows the
difference between being right and being lucky) legible in 90 seconds; and stand as a permanent,
auditable public record of every decision the agent made.

---

## 1. Why this exists — the requirements it satisfies

Verified against `docs/submission_and_judging.md` and `docs/submission_assets_checklist.md`.

| Requirement | How the site satisfies it |
|---|---|
| **"Application URL — a live/hosted demo URL, not just the repo"** (form field, currently marked *"Needs an explicit decision, not a default"*) | This site is the answer. Highest-priority reason it exists. |
| **Judging cat. 4 — Presentation & Execution**: *"how clearly and effectively the project communicates its idea, demonstrates the agent in action, and presents the reasoning behind its strategy and results"* | The whole site is scored here. This is the category the site moves most. |
| **Judging cat. 1 — P&L Performance** | `/scoreboard` reports the real number plainly, with the sample-size honesty the project already practises. |
| **Judging cat. 3 — Creativity & Originality** | The attribution 2x2, the muse, the Coach, the declines feed — surfaced, not buried. |
| **Judging cat. 5 — Social engagement** | Per-trade permalinks with per-page OG metadata give X/LinkedIn posts something to link to. |
| **"Evidence of options trading, multi-leg preferred"** | Every trade page shows legs, strikes, expiry, greeks, `client_order_id`, and a payoff-at-expiry chart derived from the contract. |
| **One-page write-up (AI logic / risk gates / Alpaca infra)** | `SUBMISSION.md` rendered at `/submission`, alongside the deck and the video link. |
| **Slide presentation** | `docs/deck.html` hosted at `/deck`. |
| **Public GitHub repo** | Linked site-wide from `site.config.js`, with per-page source links. |

**Non-goals.** SEO, search-engine registration, and lead capture. The awf pipeline's GSC/Bing/
keyword steps are skipped — three days of indexing is worth nothing here. Fathom analytics is
optional and cheap; take it only if Phase 4 is reached.

---

## 2. Reasoning: how the structure was chosen

*(Kept because the tradeoffs matter to anyone changing the structure later. Skip to §3 to build.)*

### 2.1 Audiences, ranked

1. **A hackathon judge, tab 14 of 60, three minutes.** Needs: what is this, is it real, what's
   different, where's the evidence, where's the repo. Will not scroll far.
2. **A developer or trader who followed the GitHub link.** Wants architecture and the interesting
   ideas.
3. **A visitor from a social post about one specific trade.** Arrives deep, wanders shallow.
4. **The team.** The site must be a byproduct of the running system, not a second system to feed.

### 2.2 Structures considered

- **A. Marketing page + full docs mirror.** Complete, but the differentiator drowns in 338KB of
  `decisions.md`. Fails "easy to understand". Rejected.
- **B. Live dashboard first.** Demonstrates the agent, but a dashboard of gauges does not explain
  *why this is different*, and with 4 positions and thin calibration it reads as empty. Every
  other submission will have a dashboard. Rejected as the primary frame.
- **C. The trade blog is the site.** Matches the brief's "central index in latest order", gives
  social a permalink target, always fresh — but alone it never answers "what is this and why is it
  clever" for a three-minute judge. Rejected alone.
- **D. Narrative → evidence → machinery → record.** Chosen. The site is structured to *prove* the
  project's own claim rather than assert it: the claim (Home), the record (Ledger), the scorecard
  (Scoreboard), the machinery (How it works), the making of it (Build log), and a judge-facing
  index (For judges).

### 2.3 The organising device

The design system (`docs/design_system.md`) names **two registers** — *brand* (Fredoka, rounded,
warm accent; used where Theo is being **introduced**) and *ledger* (Fraunces, sharp, sage; used
where Theo is being **audited**). The site adopts this literally as its information architecture:
**the page changes register as you move from being pitched to, to inspecting the evidence.** Home
and `/submission` are brand register; everything carrying a number is ledger register. This is not
decoration — it is the project's own epistemics rendered as typography, and it is the single
strongest defence against the site looking like generic AI output.

### 2.4 Scenarios simulated, and what each changed

Twenty-five scenarios were run against draft D. The ones that changed the design:

| # | Scenario | Outcome — what it changed |
|---|---|---|
| 1 | Judge never scrolls past the fold | Live proof strip + the 2x2 must sit within the first screen-and-a-half; added a dedicated `/submission` page mapping the five judging categories to on-site evidence |
| 2 | "Trades" page shows only 4 rows and looks thin | **Reframed the page as the *ledger of decisions*, not trades** — 98 decisions, 84 declines, 13 theses, 57 resolved forecasts. Thinness becomes discipline: *a decline is a logged answer* |
| 2b | One `no_op.summary` in the journal is a base64 thinking-signature blob, not prose | Exporter needs a **prose sanitizer** with a *reported* drop count (a silent drop would be this project's own signature bug class) |
| 2c | The journal has never been published; project has a documented history of credential-shadowing bugs | **Redaction scan that hard-fails the export**, not a warning. This is the one gate that belongs — it is outward-facing and irreversible |
| 3 | A trade closes while a judge is reading | Every page carries `data as of <ts> · tick <n>`. Honest staleness beats fake liveness. Client-side liveness rejected: same staleness, more failure modes |
| 4 | A broken build deploys at 3am | Publisher **verifies before deploying**; on any failure it does nothing, and the previous Pages deployment stays live |
| 4b | A half-written data file yields a snapshot with fewer trades than the last one | **Monotonicity guard**: refuse to deploy on a shrink, log it |
| 5 | Domain not yet owned / DNS not propagated | **Deploy to `*.pages.dev` first and immediately.** That URL is a valid Application URL. Domain work runs in parallel and never blocks content |
| 6 | A trade gets shared on X | Static OG image + per-page `og:title`/`og:description` in Phase 1. Per-trade generated OG images deferred to Phase 4 (satori font loading is a known time sink) |
| 8 | "You say muse survival is 92% — prove it" | **Every number carries its provenance**: a mono caption naming the source file and key, plus a `/data` page with the raw exports. Deeply on-brand for a project whose own wiki has a note called *who-audits-this-number* |
| 9 | GitHub repo not public yet (no remote configured today) | Repo URL lives in `site.config.js`; when empty the CTA is **omitted**, never rendered as a dead link |
| 11 | Blog frontmatter and wiki frontmatter have different keys; the agent may add more | Exporter is tolerant: unknown keys pass through, missing keys render as an explicit **"not recorded"** state. **The exporter never fabricates** |
| 12 | Someone clones the repo and runs `npm run build` with no Python env | `snapshot.json` is a **committed file**; the exporter refreshes it. Build never depends on the exporter having just run |
| 12b | Auto-committing the snapshot every 10 min for 3 days = ~400 commits in a repo judges will read | **Publisher does not auto-commit.** One deliberate commit before submission |
| 13 | Two publishes race | Lockfile, same pattern as `src/trdrbot/lock.py` |
| 14 | `deck.html` / `report.html` / the explorers hosted as-is have no way back to the site | Build step injects a one-line back-link banner **into the copy**, leaving the source files untouched |
| 15 | Judges look specifically for options sophistication | **Payoff-at-expiry chart per trade**, labelled *FACT — contract arithmetic*, with MODELLED figures (POP, EV) under a separate heading. The project's core epistemic distinction, rendered visually |
| 15b | A structure whose payoff can't be derived from the record | **Refuse to draw it** and say so. Never guess a chart |
| 16 | 0 of 4 positions attributed today | Show the empty 2x2 *with* an honest caption. Hiding it would contradict the project's voice |
| 19 | Vite inlines a 500KB JSON into every page chunk | Snapshot is imported **only inside `+page.js` load functions**, each plucking what it needs. This is the single most likely performance mistake |
| 21 | "This is all narrative — where's the code?" | `<SourceLink>` component builds GitHub permalinks from `repoUrl` + the snapshot's `git_sha` |
| 22 | Site prose contradicts the repo (README says D-001…D-094; there are 98) | **Rule: no hardcoded numbers in any Svelte component.** Every figure comes from the snapshot |
| 23 | A trade closes badly and the site looks bad | Loss states get the same design dignity as wins, with the attribution question beside them. A UI that only looks right when green is a broken UI |
| 24 | Judging happens days after the run has stopped; the site looks abandoned | `site.config.frozen` swaps the live tick indicator for a **"competition run complete — record final as of …"** badge |
| 25 | Keyboard / screen-reader use | Semantic headings, skip link, visible focus, alt text, `<th scope>`, and the design system's existing rule that colour is never the only signal |

### 2.5 Decisions that fall out of the above

1. **The site lives inside this repo, at `web/`.** One git history, no cross-repo sync, and the
   build reads `../data/**` directly — including `data/state/**` and `data/journal.jsonl`, which
   are **gitignored** and therefore invisible to any CI runner. This alone rules out Cloudflare's
   Git integration and settles the next decision.
2. **Build locally, deploy the built output with `wrangler`.** Exactly what `awf-deploy` does.
3. **The publisher is a separate process from the trading loop.** A 40-second `npm run build` or a
   network hiccup at Cloudflare must never delay an exit-rule check. Decoupled, always.
4. **awf skills own infrastructure only** — zone, Pages project, DNS, nameservers, and optionally
   analytics. The site itself is hand-built SvelteKit; the awf landing-page template is discarded
   after `awf-create-project` writes `passport.json`.

---

## 3. Site map

Six nav items. Everything else is reachable from the footer or in context.

```
/                          Home              brand register
/ledger                    Decision stream   ledger register
/ledger/[position_id]      One trade         ledger register
/scoreboard                Results           ledger register
/how-it-works              Architecture      ledger register
/how-it-works/risk         Risk appetite     ledger register
/build-log                 Dev journals      ledger register
/build-log/[slug]          One entry         ledger register
/notes                     The agent's wiki  ledger register
/notes/[slug]              One note          ledger register
/submission                For judges        brand register
/data                      Provenance        ledger register
/glossary                  Plain English     ledger register

static passthrough (hosted verbatim, back-link banner injected):
/deck.html                 docs/deck.html
/coach-report.html         data/report.html            (regenerated each publish)
/risk-explorer.html        docs/risk_appetite_explorer.html
/risk-research.html        docs/research_risk_appetite.html
/design-system.html        docs/design_system.html
```

**Nav:** Home · Ledger · Scoreboard · How it works · Build log · For judges
**Footer:** Notes · Data · Glossary · Deck · Coach report · Design system · GitHub · theme toggle

---

## 4. Page specifications

Every page: `<h1>`, a one-line standfirst, and a footer line `data as of <ts> · tick <n> ·
source: <file>`. No page may hardcode a number.

### 4.1 `/` — Home (brand register)

Purpose: convert a three-minute judge into someone who clicks one more link.

1. **Hero.** Fredoka h1: *"Theo knows the difference between being right and being lucky."*
   Standfirst: the SUBMISSION.md one-sentence summary. Mascot art on a cream plate
   (`docs/assets/crops/hero_illustration.png` or `elf-thinking.jpg`) — the cream `#FCF7F4` ground
   is a brand constant and is **never** re-themed. Two CTAs: *See the ledger* (primary),
   *For judges* (ghost). GitHub CTA only if `repoUrl` is set.
2. **Live proof strip.** A pulsing dot + `tick <n> · <relative time> ago`, then stat tiles:
   equity, P&L %, positions open, theses formed, decisions made, declines, resolved forecasts,
   days running. Each tile carries a provenance caption. When `frozen`, the dot becomes a
   completed-run badge.
3. **The 2x2.** The view/outcome matrix from README, with live counts and an honest caption when
   counts are zero. The site's signature visual — reused on `/scoreboard` and `/submission`.
4. **Three doors.** Cards: *the record* → `/ledger`, *the machine* → `/how-it-works`,
   *the scorecard* → `/scoreboard`.
5. **Latest decision.** The most recent ledger item inline — a trade or a decline, with the
   agent's own words. Proves liveness better than any badge.
6. **Honest limitations teaser.** Three bullets from `README.md`, linking to the full list.

### 4.2 `/ledger` — the decision stream (the brief's "central index")

Reverse-chronological, typed, filterable. **This is the page the brief asked for.**

- **Filter chips** (client-side, URL-synced): `all` · `traded` · `declined` · `forecast resolved` ·
  `exit fired` · `closed`. Default `all`.
- **Item kinds and what each row shows:**
  - `traded` — status pill, underlying, strategy, opened, expiry, max loss, stated confidence,
    the thesis claim, a payoff mini-sparkline, link to the trade page.
  - `declined` — status pill `declined`, timestamp, tick, model, tools called, and the agent's
    **verbatim** reasoning in an expandable block. Sanitized; unreadable summaries excluded.
  - `forecast resolved` — underlying, stated probability, held/failed, price at horizon, whether
    it was traded. Zero-capital claims that still moved calibration.
  - `exit fired` / `closed` — which rule, which signal, threshold, outcome.
- **Header stat line:** counts per kind, so the shape of the record is visible before scrolling.
- **Empty state:** the `empty_nothing_here.png` crop with a plain caption — never a blank page.

### 4.3 `/ledger/[position_id]` — one trade

Ordered so a reader meets the reasoning before the machinery.

1. **Header** — underlying, strategy, status pill, opened/closed, expiry, model that decided it,
   `decision_ref`, `batch`, `client_order_id` as mono chips.
2. **The thesis** — the claim verbatim, the resolution band and horizon, expected drift, vol view,
   stated confidence. Callout if confidence was below 0.5, quoting the agent's own line about not
   rounding up.
3. **Why this trade** — the prose from `data/blog/<id>.md`, rendered.
4. **What was rejected** — the alternative structures with their numbers, and the agent's reason.
   If `simulate_experiments` wasn't called, print the blog's own "not on record" sentence — do not
   invent alternatives.
5. **Payoff at expiry** — SVG chart. Heading: **FACT — contract arithmetic.** Breakevens, max
   profit, max loss marked. Skipped with an explanation when not derivable (see §6.4).
6. **Modelled** — P(profit), EV under the market's drift, EV under the thesis's drift, payoff
   ratio. Heading: **MODELLED — depends on a distribution.** Visually distinct from §5. This
   separation is a load-bearing project principle, not a layout choice.
7. **The contract** — legs table (side, qty, OCC symbol, parsed strike/right/expiry), greeks at
   entry, entry IV, entry spot.
8. **Exit rules** — each rule, its basis, threshold, and current/final state from `exit_state`.
9. **Sources** — the inbox items and their authors (research / discovery / muse), linked to the
   note or dossier where one exists.
10. **Outcome** — close reason, P&L, and the attribution verdict (view × structure). Where
    unattributed, say why in the project's own words.
11. **Provenance footer** — the wiki page path, the blog path, the journal `decision_ref`, and a
    `<SourceLink>` to each on GitHub.

### 4.4 `/scoreboard`

1. **P&L, plainly.** Equity, start, absolute and percent, high water, current drawdown. One
   paragraph, adapted from `docs/submission_and_judging.md`, saying the number *and* why a
   one-week P&L is a poor instrument — the measured 60%-edge-beats-a-coinflip-69%-of-20-trades
   result. Report first, interpret second. Never omit the number.
2. **Equity curve.** From `competence` rows in the journal (they carry `equity` and `high_water`).
3. **Calibration.** Brier score, Murphy decomposition, `n`, and `n_eff` side by side, with sample
   size stated beside every figure. A reliability plot when there are enough bins; otherwise the
   raw resolved forecasts as a table.
4. **The 2x2, populated.** With the honest caption about what is not yet attributed.
5. **The competence ladder.** EXPLORE → ESTABLISH → SCALE → MATURE, current rung marked, with
   `next_tier_needs` shown verbatim.
6. **Book risk.** Beta-weighted delta, raw delta, vega, theta, and `pct_equity_per_1pct_spy`, with
   the README's own line about names not being exposures.
7. **Honest gaps.** The open items from `specs/issues.md`, rendered as they are written. This
   section is a feature: publishing your own open bug ledger is the strongest possible support for
   every other claim on the site.

### 4.5 `/how-it-works`

Ported from `docs/deck.html`'s slide sequence — that content is already written, judged-tested
prose. Sections: the five-stage loop (Sense → Think → Act → Learn → Remember); three thesis
sources (research / discovery / muse) with live counts; what the model decides vs what the code
decides; the four memory stores; **the Alpaca integration** (MCP one session per tick, real
multi-leg orders, 19 of 72 tools bound, deterministic `client_order_id`, the reconciler running
first) — this section is scored under Technology Implementation, so give it real estate; and the
Coach, with a link to the live report. Two or three real code excerpts with `<SourceLink>`s.

### 4.6 `/how-it-works/risk`

Kelly on the conditional payoff, the calibration shrink, the three caps, the refusal of unbounded
loss, exit rules as the agent's own commitments, and the two rules it cannot override
(deadline sweep, vanished leg). Cross-links to `/risk-explorer.html` (interactive) and
`/risk-research.html` (the research write-up), both hosted verbatim.

### 4.7 `/build-log` and `/build-log/[slug]`

The seven `docs/dev_journals/*.md` entries, newest first, with date, title, and the first
paragraph as a standfirst. This is the best writing in the repo and the best social-share
material. Mascot punctuation (`mascot_coding.png`) in the index header.

### 4.8 `/notes` and `/notes/[slug]`

The agent's own wiki: 12 technique notes, 30 research dossiers, the regime page, the lessons file.
Grouped by kind with a short explanation that **the agent wrote these**, and that the technique
notes are the muse's raw material. Low build cost, high "it really is doing this" value.

### 4.9 `/submission` — For judges (brand register)

One page a judge can read alone and be fully briefed.

- The one-sentence summary and the hackathon facts (event, deadline, paper trading only).
- **The five judging categories, each with the claim and a direct link to the evidence on this
  site.** An executive summary, not a plea — write it factually.
- `SUBMISSION.md` rendered in full (it is already scoped to one page).
- Asset links: deck, video, GitHub, raw data, coach report.
- A note on the Alpaca paper account: **the account ID goes in the submission form, not on this
  page.** State that the record here is the full trading activity and that the ID is supplied
  privately to judges.
- Honest limitations, verbatim from README.

### 4.10 `/data` — provenance

Every export, downloadable, with row counts, byte sizes and generation timestamp:
`snapshot.json`, `ledger.jsonl`, `metrics.jsonl`, `experiments.jsonl`, `forecasts.jsonl`, the
redacted `journal.jsonl`, and the raw markdown for blog/wiki/journals. Plus the integrity report:
redaction scan result, patterns checked, sanitizer drop count. **This page is what makes every
number on the site checkable, and no competing submission will have it.**

### 4.11 `/glossary`

~25 terms in plain English: bear put spread, debit, net credit, breakeven, max loss, delta,
beta-weighted delta, vega, theta, implied vol, realised vol, Brier score, Murphy decomposition,
calibration, Kelly fraction, conditional payoff, attribution, thesis, falsifiable, pre-registration,
bootstrap Monte Carlo, MCP, paper trading, assignment, pin risk. Authored as
`web/src/lib/glossary.json`; also powers the inline `<Term>` component site-wide.

---

## 5. Technical architecture

### 5.1 Layout

```
trdrbot_hack/
├── src/trdrbot/site_export.py        NEW — the exporter
├── scripts/publish.sh                 NEW — the publisher loop step
├── data/publish_log.jsonl             NEW — append-only publish record
└── web/                               NEW — the SvelteKit project (awf project root)
    ├── passport.json                  written by awf-create-project
    ├── wrangler.toml                  name = "trdrbot", pages_build_output_dir = "build"
    ├── svelte.config.js               adapter-static
    ├── vite.config.js
    ├── package.json
    ├── src/
    │   ├── app.html                   fonts, theme bootstrap, favicon
    │   ├── app.css                    ported verbatim from docs/deck.html's <style>
    │   ├── lib/
    │   │   ├── data/snapshot.json     GENERATED — committed before submission
    │   │   ├── site.config.js         repoUrl, videoUrl, frozen, socialLinks
    │   │   ├── glossary.json
    │   │   ├── format.js              usd, pct, relativeTime, occSymbolParse
    │   │   ├── payoff.js              expiry payoff from legs + net debit
    │   │   ├── markdown.js            build-time markdown → HTML (marked)
    │   │   └── components/            see §5.5
    │   ├── routes/                    see §3
    │   └── static/                    logo, mascots, icons, OG image, the passthrough HTML
    └── build/                         adapter-static output → wrangler
```

### 5.2 Stack

- **SvelteKit 2 + Svelte 5 (runes).** `$state`/`$derived` for the ledger filters; everything else
  is static.
- **`@sveltejs/adapter-static`** with `pages: 'build'`, `assets: 'build'`, `precompress: false`,
  `strict: true`. Root `+layout.js` sets `export const prerender = true`. Dynamic routes export an
  `entries()` function enumerating ids from the snapshot.
- **`marked`** for markdown, at build time only.
- **No CSS framework.** `app.css` is ported verbatim from `docs/deck.html`'s `<style>` block —
  tokens, both themes, `.brand`/`.ledger` register modifiers, `.card`, `.kicker`, `.tag`, `.num`,
  `.big`, `.scroll`, table rules. That file is already a complete, hand-built implementation of
  `docs/design_system.md`; re-deriving it would be pure loss.
- **Charts:** hand-written SVG. No charting library. Four chart types only (payoff, equity curve,
  reliability plot, gauge sparkline), each ~60 lines, all themeable via CSS variables.

### 5.3 Data flow

```
  data/journal.jsonl ─┐
  data/state/*.jsonl ─┤
  data/metrics.jsonl ─┤
  data/blog/*.md      ├─▶ trdrbot site export ─▶ web/src/lib/data/snapshot.json
  data/wiki/**/*.md   │        (redact, sanitize, guard)          │
  docs/dev_journals/  │                                            ▼
  specs/issues.md    ─┘                             +page.js load() plucks per route
                                                                   │
                                                    npm run build (prerender all)
                                                                   │
                                                        wrangler pages deploy
```

### 5.4 The critical performance rule

**Import `snapshot.json` only inside `+page.js` / `+layout.js` `load()` functions, and return only
the slice that route needs.** Never import it into a component or a shared module. With
prerendering, each route's `load()` runs at build time and only its returned slice is serialised
into that page's `__data.json`. Importing it into a shared module makes Vite inline the entire
snapshot into every page's JS chunk.

**Split threshold:** if `snapshot.json` exceeds 1.5MB, move `notes` and `journals` bodies into
per-slug files under `web/src/lib/data/notes/` and `journals/`, loaded by `import.meta.glob`.
Today it will be ~400-600KB; the threshold is a rule, not a task.

### 5.5 Components

| Component | Notes |
|---|---|
| `Nav`, `Footer`, `ThemeToggle` | Theme persists in `localStorage`, `data-theme` on `<html>`, wrapped in try/catch |
| `StatTile` | Big mono tabular number, label, optional `provenance` prop |
| `Provenance` | Small mono caption: source file + key. Used everywhere a number appears |
| `StatusPill` | `traded` / `declined` / `open` / `closed` / `expired` / `rejected` / `gap` — dot + mono uppercase label. Colour never alone |
| `Callout` | Accent-tinted, left border, mono uppercase eyebrow ("factual note", "honest gap") |
| `MonoChip` | Inline ticker/ID/timestamp chip |
| `DataTable` | Wraps in `.scroll` for mobile; `<th scope>`; right-aligned mono numerics |
| `MarkdownBody` | Renders pre-converted HTML with ledger-register typography |
| `Term` | Inline glossary term — dotted underline, tooltip on hover, `<details>` on tap |
| `SourceLink` | `{repoUrl}/blob/{git_sha}/{file}#L{line}`; renders as plain text if `repoUrl` empty |
| `PayoffChart` | SVG; FACT heading; refuses to render when not derivable |
| `EquityCurve` | SVG line + high-water line |
| `ReliabilityPlot` | SVG; falls back to a table below a bin-count threshold |
| `Attribution2x2` | The signature visual; handles all-zero honestly |
| `LedgerItem` | One row in the decision stream, polymorphic on kind |
| `TickIndicator` | Pulsing dot + relative time; completed-run badge when `frozen` |
| `EmptyState` | Mascot crop + plain caption |

### 5.6 Design rules, enforced

1. **No hardcoded numbers in components.** Everything from the snapshot.
2. **Every number gets a `Provenance`.**
3. **FACT and MODELLED never share a heading or a card.**
4. **Colour is never the only signal** — always paired with a label or icon.
5. **Missing data renders as an explicit "not recorded"**, styled `caution`. Never blank, never
   invented.
6. **The mark's cream ground `#FCF7F4` is never re-themed.** Mascot art always sits on its own
   cream plate in both themes.
7. **Brand register (Fredoka, 18px radius, warm `#A8582C`) only on `/` and `/submission`.**
   Everything carrying a number is ledger register (Fraunces, 4px, sage accent).
8. Every wide table inside `overflow-x: auto`; the body never scrolls horizontally.

---

## 6. The exporter — `src/trdrbot/site_export.py`

CLI: `uv run trdrbot site export [--out web/src/lib/data/snapshot.json] [--strict]`
Registered in `src/trdrbot/cli.py` as a `site` subcommand with an `export` action, following the
existing `coach`/`constitution`/`modelcal` sub-action pattern.

Follows this project's own conventions: **derive, never re-declare** (D-037); never fabricate;
report what it dropped; and fail loudly on the one thing that must not go wrong.

### 6.1 Inputs

| Source | Used for |
|---|---|
| `data/journal.jsonl` | decisions, no_ops (declines), executions, fills, `forecast_resolved`, `book_risk`, `competence` (equity curve, tier), `exit_run`, `coach_run`, tool-call lists, model IDs |
| `data/state/ledger.jsonl` | every thesis formed, traded or not |
| `data/state/forecasts.jsonl`, `high_water.json`, `model_calibration.json` | calibration inputs |
| `data/metrics.jsonl` | gauge series and latest snapshot |
| `data/experiments.jsonl` | Coach trials |
| `data/blog/*.md` | the trade stories (frontmatter + prose) |
| `data/wiki/positions/*.md` | the machine record: legs, greeks, exit rules, exit state, attribution |
| `data/wiki/{technique,research,context}/*.md`, `lessons.md` | the notes section |
| `docs/dev_journals/*.md` | the build log |
| `SUBMISSION.md`, `README.md` | rendered pages |
| `specs/issues.md` | the open items only |
| `specs/decisions.md` | the **index only** (id, title, date, status) — bodies stay on GitHub |
| `data/state/tick_count`, `git rev-parse HEAD` | freshness and source links |

### 6.2 Output shape

```jsonc
{
  "generated_at": "ISO8601", "tick": 597, "git_sha": "…", "git_dirty": false,
  "run_started": "2026-08-26T18:30:08Z", "days_running": 6,

  "account":     { equity, start, pnl_usd, pnl_pct, high_water, drawdown, as_of, source },
  "competence":  { tier, resolved, reliability, attributable_rate, kelly_multiplier,
                   seed_fraction, book_cap, next_tier_needs[] },
  "book":        { positions, delta_dollars, beta_weighted_delta, vega_dollars,
                   theta_dollars, pct_equity_per_1pct_spy, as_of },
  "calibration": { n, resolved, brier, n_eff, murphy{reliability,resolution,uncertainty},
                   bins[{p_lo,p_hi,n,observed}] },
  "attribution": { held_profit, held_loss, failed_loss, failed_profit,
                   unattributed, note },
  "gauges":      { latest{…}, series[{ts, …}] },

  "positions":   [{ id, underlying, strategy, status, opened, closed, expiry,
                    max_loss_usd, confidence, model, decision_ref, batch,
                    client_order_id, entry_spot, entry_iv,
                    thesis{claim, band_low, band_high, horizon, drift, vol_view},
                    legs[{side, qty, symbol, strike, right, expiry}],
                    greeks_at_entry{…}, exit_rules[…], exit_state[…],
                    sources[{id, author, resource}],
                    story_html, alternatives[…], modelled{pop, ev_market, ev_thesis,
                    payoff_ratio}, payoff{derivable, net_debit, points[…], breakevens[…],
                    max_profit, max_loss}, outcome{close_reason, pnl_usd, pnl_pct,
                    attribution} }],

  "ledger_items":[{ ts, kind, tick, model, title, body_html, position_id?, tool_calls[],
                    meta{…} }],          // the merged decision stream, newest first
  "theses":      [ … ledger.jsonl rows … ],
  "forecasts":   [ … resolved forecasts … ],
  "experiments": [ … coach trials … ],
  "notes":       [{ slug, kind, title, html, source_path }],
  "journals":    [{ slug, date, title, standfirst, html, source_path }],
  "docs":        { submission_html, readme_html, issues_open[], decisions_index[] },

  "counts":      { positions, traded, declined, forecasts_resolved, theses, ticks,
                   journal_rows, notes, journals, decisions_logged },
  "integrity":   { redaction_scan: "clean", patterns_checked: n,
                   summaries_dropped: n, dropped_reasons[…] }
}
```

### 6.3 Three guards — all mandatory

**1. Redaction scan (hard fail).** Before writing, scan every string destined for the snapshot for
credential-shaped tokens: `sk-`, `pk_`, `PK[A-Z0-9]{16,}`, `AKIA`, `xoxb-`, `ghp_`, `Bearer\s+\S+`,
any 32+ char base64/hex run adjacent to `key|token|secret|password`, plus the literal values of
every variable present in `.env`. **On any hit: print the match location, exit non-zero, write
nothing.** This is the only place in the pipeline where stopping is correct — publishing a key is
irreversible and outward-facing.

**2. Prose sanitizer (drop and report).** `no_op.summary` and `decision` summaries occasionally
contain base64 thinking-signature blobs rather than prose (verified: 1 of 84 today). Reject a
summary when: it contains no whitespace in its first 80 characters; or its first 200 characters
are >85% base64 alphabet; or it does not begin with a letter, `#`, or `*`. **Count every drop and
put the count in `integrity.summaries_dropped`** — a silent drop is exactly the failure class this
project has spent five phases hunting.

**3. Monotonicity guard (refuse and log).** Compare `counts` against the previous snapshot. If
`positions`, `journal_rows` or `theses` has decreased, exit non-zero without writing. A shrink
means a half-written file or a path bug, never a legitimate state.

### 6.4 Payoff derivation (the one piece of new math)

Parse the OCC symbol: `SPY260903P00763000` → root `SPY`, expiry `2026-09-03`, right `P`,
strike `763000/1000 = 763.0`.

Per-share payoff at expiry:
`payoff(S) = Σ_legs sign(side) · qty · intrinsic(S, K, right) · 100 − net_cost`
where `intrinsic = max(0, K−S)` for puts, `max(0, S−K)` for calls, and `sign = +1` for buy.

Net debit is derived from the record, not assumed: for a debit structure,
`net_debit_per_contract = max_loss_usd / (qty · 100)`. Verify against the position's own
`max_loss_usd` and refuse on disagreement beyond a cent.

**Set `payoff.derivable = false`** — and render an explanation instead of a chart — whenever:
`max_loss_usd` is missing; a leg's symbol does not parse; legs have differing expiries (a calendar,
which this project refuses to price by design); or the reconstructed max loss disagrees with the
record. **Never draw an approximate payoff.**

Sample the curve across `[0.85 · min(K), 1.15 · max(K)]` at 200 points, plus exact kink points at
every strike so the corners are sharp.

---

## 7. The publisher — `scripts/publish.sh`

Idempotent, lock-guarded, fail-safe. Never touches the trading loop.

```
 1. acquire data/.publish.lock (flock or mkdir); on contention → log skip, exit 0
 2. uv run trdrbot report                       # refresh data/report.html
 3. uv run trdrbot site export                  # guards run here; non-zero → log, exit 1
 4. content hash of snapshot.json unchanged     → log noop, exit 0
 5. node web/scripts/sync-static.mjs            # copy + back-link-inject the passthrough HTML
 6. (cd web && npm run build)
 7. verify build/: index.html exists and is >2KB, contains the marker "trdrbot",
    build/ledger/index.html exists, and the prerendered trade-page count == counts.positions
 8. (cd web && npx wrangler pages deploy build --project-name trdrbot --commit-dirty=true)
 9. append to data/publish_log.jsonl:
    { ts, hash, tick, counts, dropped, deploy_url, duration_s, status }
10. release lock
```

Any failure at 3, 6 or 7 exits non-zero **without deploying**, so the last good Pages deployment
stays live. Every outcome — including the no-ops — is a row in `publish_log.jsonl`, because
observability beats gating.

**Run it as:** `while true; do ./scripts/publish.sh >> logs/publish.log 2>&1; sleep 600; done`
under `nohup` or in a tmux pane. A launchd plist is the durable option if the machine sleeps.

**No auto-commit.** Before submission, run once:
`git add web/src/lib/data/snapshot.json && git commit -m "chore(site): final snapshot"`.

---

## 8. Infrastructure — the awf sequence

Prerequisite: `/awf-doctor` passes (Cloudflare + Namecheap credentials present, `wrangler whoami`
authed).

**Checkpoint before starting:** confirm `trdrbot.com` is registered and sitting in the Namecheap
account the awf skills are configured against. If it is not, everything below still works —
**the site ships on `trdrbot.pages.dev`, which is a perfectly valid Application URL.** Do not let
domain ownership block a single content step.

```
1. /awf-create-project trdrbot.com --in <repo>/web --no-git
      → writes web/passport.json. --no-git because we're inside an existing repo.
      → the landing-page template files it copies (build.mjs, static/index.html,
        package.json) are deleted in step 2; passport.json and any static/*.txt stay.

2. Scaffold SvelteKit over the top (npm create svelte / manual), keeping passport.json.
   Write wrangler.toml:  name = "trdrbot"
                         pages_build_output_dir = "build"
   Ensure package.json has a "build" script — awf-deploy calls `npm run build`.

3. /awf-setup-domain
      → Cloudflare zone, Pages project "trdrbot", apex CNAME → trdrbot.pages.dev,
        www → apex, always_use_https, www→apex bulk redirect.
      → stashes the zone nameservers in passport.launch.gates.domain_setup.meta.

4. /awf-install       (npm ci)
5. /awf-deploy        → FIRST LIVE URL on *.pages.dev. Do this before anything else is
                        polished. It is the safety net for the Application URL field.

6. /awf-setup-nameservers   → points Namecheap at Cloudflare. Propagation runs in the
                              background and blocks nothing.

7. (optional, Phase 4) /awf-setup-analytics   → Fathom site id into passport.json.

SKIP: awf-generate-content, awf-review-passport (content is ours, not passport-driven),
      awf-setup-gsc, awf-verify-gsc, awf-submit-bing (search indexing is worthless in 3 days).
```

Thereafter the publisher calls `wrangler` directly rather than `awf-deploy`, because it needs the
export/verify steps around the deploy. `awf-deploy` stays available for a manual push.

---

## 9. Build phases

Ordered so that **the project has a valid, defensible submission at the end of Phase 1** and
everything after is upside.

### Phase 0 — infrastructure (~30 min)
`awf-doctor` → `awf-create-project` → SvelteKit skeleton with a placeholder page →
`awf-setup-domain` → `awf-install` → `awf-deploy`. **Exit criterion: a live `*.pages.dev` URL.**
Then `awf-setup-nameservers` and forget about DNS.

### Phase 1 — the spine (~4 h) — **this alone is shippable**
1. `site_export.py` with all three guards, emitting the full snapshot.
2. `app.css` ported from `docs/deck.html`; `app.html` with fonts and theme bootstrap.
3. Shell: `Nav`, `Footer`, `ThemeToggle`, `StatTile`, `Provenance`, `StatusPill`, `Callout`,
   `MarkdownBody`, `DataTable`, `EmptyState`.
4. `/` — hero, live proof strip, the 2x2, three doors, latest decision.
5. `/ledger` — the decision stream with filters.
6. `/ledger/[position_id]` — the full trade page (payoff chart may be a Phase 3 stub).
7. `scripts/publish.sh` + the loop. **Exit criterion: a trade closes and the site updates by
   itself.**

### Phase 2 — the case (~4 h)
8. `/scoreboard` — P&L, equity curve, calibration, the 2x2, ladder, book risk, open issues.
9. `/how-it-works` + `/how-it-works/risk`.
10. `/submission` — the judge page, the five categories mapped to evidence.
11. Static passthrough with back-link injection: deck, coach report, both risk pages, design
    system. **Exit criterion: a judge can answer every one of the five categories without
    leaving the site.**

### Phase 3 — the depth (~3 h)
12. `PayoffChart`, `EquityCurve`, `ReliabilityPlot`, `Attribution2x2` as real SVG.
13. `/build-log` + `/build-log/[slug]`.
14. `/notes` + `/notes/[slug]`.
15. `/data` — provenance and downloads.
16. `/glossary` + the inline `<Term>` component.

### Phase 4 — polish, only if time remains
17. Per-trade OG images (satori + resvg at build time).
18. Fathom analytics; `sitemap.xml`, `robots.txt`, a designed `404`.
19. `site.config.frozen` end-of-run badge — **do run this one after the deadline.**
20. Final snapshot commit; verify every external link resolves.

---

## 10. Definition of done

- [ ] `https://trdrbot.com` and `https://trdrbot.pages.dev` both serve the site over HTTPS.
- [ ] The publisher has run unattended for ≥ 12 hours with no manual intervention, and
      `data/publish_log.jsonl` shows the successful redeploys.
- [ ] A newly opened position appears at `/ledger` within 15 minutes with no human action.
- [ ] Every number on the site traces to a snapshot key, and every page shows its "as of".
- [ ] `integrity.redaction_scan == "clean"` in the deployed snapshot.
- [ ] Lighthouse ≥ 95 on performance and accessibility for `/` and `/ledger`.
- [ ] Both themes render correctly; the mascot's cream plate is unchanged in dark mode.
- [ ] Mobile: no horizontal body scroll on any page at 375px.
- [ ] `/submission` answers all five judging categories with working links.
- [ ] The GitHub CTA either links to a live public repo or is absent — never a 404.
- [ ] `snapshot.json` is committed at its final state before the form is submitted.

---

## 11. Explicitly deferred, with reasons

| Deferred | Why |
|---|---|
| Per-trade generated OG images | Real social value, but satori font loading is a reliable time sink. Static OG + per-page meta text covers 80% of it |
| Runtime liveness (client fetch of a hosted JSON) | Identical staleness to a build-time snapshot, with an extra failure mode. Rejected on simplicity |
| Cloudflare Pages Git integration | `data/state/**` and `journal.jsonl` are gitignored, so CI cannot see the agent's real record |
| Full `decisions.md` bodies on-site | 338KB. The index plus GitHub links is the right depth for the audience |
| Search | 60 pages. Nav and filters are enough |
| A comments or contact form | Nothing to gain, a spam surface to lose |
| GSC / Bing / keyword content | Three days of indexing is worth nothing for this audience |

---

## 12. Open questions for the operator

Answer these while Phase 0 runs; none of them blocks a single step.

1. **Is `trdrbot.com` registered in the Namecheap account awf is configured against?** If not, the
   site ships on `trdrbot.pages.dev` and the domain is added later with no rebuild.
2. **The GitHub repo URL**, once the remote exists and the repo is public — goes in
   `web/src/lib/site.config.js`.
3. **The video URL**, once recorded — same file.
4. **Should the Alpaca paper account ID appear on `/submission`?** Recommended: **no**. It goes in
   the submission form, which is where the rules require it; the site says the full trading record
   is published here and the ID is supplied to judges privately. Costs nothing, avoids
   broadcasting an identifier unnecessarily, and matches the checklist's own guidance.
