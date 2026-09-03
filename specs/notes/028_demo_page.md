# 028 - Watch it decide: the demo page

Audience: an LLM implementer with full repo access. The problem, the design, why the
alternatives lost, the scenarios walked, the edge cases with their required handling, the
exact data contract, and the tests that must exist. Read notes/027 first for the figures
pipeline this builds on, and `web/CLAUDE.md` for the site's content map.

Plain dashes throughout. No em dashes in code, docs, prompts, or page copy.

## 0. What already exists (read this before proposing anything)

| Piece | State |
|---|---|
| `web/src/lib/data/snapshot.json` | **Works.** 898 KB, 21 keys, rewritten by `site_export.py` on every publish. Positions with derived 160-point payoff curves, 460 ledger items (173 theses, 165 declines, 95 resolved forecasts, 14 gate rejections, 13 trades), a 179-point equity curve, calibration, attribution, the competence ladder, 73 wiki notes, 10 dev journals |
| `scripts/publish.sh [--force]` | **Works.** Export, sync-static, inject figures, build, verify, deploy. The site refreshes with the record every tick that moves it |
| The site | **Works.** Svelte 5 runes, adapter-static, zero runtime dependencies, one CSS file (`web/src/app.css`), hand-rolled SVG charts (`EquityCurve.svelte`, `PayoffChart.svelte`), `format.js` shared with the deck injector, the ledger register on every section, five elf illustrations in `web/static/img/` |
| `/ledger`, `/ledger/[id]`, `/scoreboard`, `/how-it-works` | **Work.** Every decision, every position, the scorecard, the five stages (Sense, Think, Act, Learn, Remember) and four stores (journal, wiki, elfmem, ledger) |
| The journal | **Works.** `agent/data/journal.jsonl`, 2,636 rows, 39 kinds. Every decide cycle writes a write-ahead `decision` row and exactly one outcome row (`no_op`, `execution`, or `error`) carrying `decision_ref` |
| The simulate step, on the record | **Works since 2026-09-03.** `structures_simulated` rows (agent path, linked to the ledger by `thesis_entry_id`) and `playbook` rows (Coach path) each carry EVERY candidate structure priced for a claim, with quoted legs, `fate` (kept, or `rejected: ...` with the reason), and the D-122 band-conditional numbers `p_band`, `e_hold`, `p_hold`, `p_fail`, `edge` |
| The size step, on the record | **Works.** `sizing` rows: contracts, fraction of equity, `binding` (which constraint bit: `Kelly`, `exploration floor`, `position ceiling`, ...), `payoff_ratio` |
| The Coach, on the record | **Works.** `agent/data/experiments.jsonl` (one open experiment, 21 paired trials with a running posterior), `agent/data/state/levers/*.json` (incumbent and challenger text), `coach_mutation` journal rows with the mutation's own rationale. `coach.tally` / `coach.verdict` produce the status prose |
| Price history | **Works.** `agent/data/state/returns/<TICKER>.json`, 112 tickers, ~300 daily closes each with dates |
| Inbox items | **Persist.** `agent/data/inbox/processed/<day>/<id>.json` from 2026-08-26 on. No purge exists. `decision.item_ids` names exactly the items each cycle read |

**So the record already holds a complete replay of every decision.** The site shows the
outcomes. Nothing shows the *deciding*.

## 1. The actual gap

Other entries in this hackathon ship a live dashboard (the reference the request named is
`alpha-hunter-frontend.onrender.com`): a status bar of "CONNECTED" pills, a watchlist, a
strategy grid with edge scores, a positions table, an "autonomous agent activity stream" of
timestamped lines. It looks alive. A judge cannot tell from it what the agent decided, why, or
whether it was right. Every panel competes for attention and none of them is a decision.

trdrbot.com has the opposite problem. The record is all there, honestly labelled, but spread
across four pages a judge has to assemble in their head: the ledger says what happened, the
position page says what a trade looked like, the scoreboard says how it went, how-it-works
says how it is supposed to work. Nowhere can a visitor **watch one cycle of the loop think**:
what arrived, what claim Theo made, which structures it priced and which it threw out and why,
how big it sized, what it actually did, and how that was scored later. Nowhere are the
**choices it did not make** shown next to the one it made.

The gap is one page, and the data for it is already on disk. Five things are not yet in the
snapshot, all cheap in bytes (measured in section 2): the per-cycle candidate structures
with their fates, the sizing decisions, the link from a decision to the items it read, the
Coach's experiment, and the claim text behind each resolved forecast.

### Two constraints that shape everything

1. **The site is static and must stay static.** Every page is prerendered; there is no
   runtime fetch anywhere in `web/src/` (verified by grep). "Live" on this site means
   "rebuilt from the record on every publish", which is within one tick of live. A demo that
   pretends otherwise (typewriter feeds, fake activity) would be exactly the reference site's
   failure, and dishonest about a five-minute loop besides.
2. **Nothing on the page may be generated for the page.** Every number, claim, structure,
   rejection reason, and verdict shown is a row the loop wrote at the moment it happened. The
   page's own standfirst says so. If something was not recorded, the page says `not recorded`,
   never a plausible reconstruction (the `/data` page's standing promise).

## 2. Empirical validation, before the design

Measured on the live journal (2,636 rows) on 2026-09-03, with a throwaway script, before any
design was fixed. Numbers the implementer should be able to reproduce.

**A cycle is reconstructible.** 205 `decision` rows; 202 have exactly one outcome row whose
`decision_ref` names them; 0 have more than one; 3 are orphans (one from the first hour on
26 Aug before the model key worked, one a `resumed_from` re-run whose outcome attached to the
successor row, one followed two minutes later by a fresh decision - a restart). The
decision-to-outcome join is clean.

**The window join is NOT clean on its own.** Attributing the rows between a decision and its
outcome by file order fails in 11 places: the 3 orphans, plus 5 pairs on 27-28 Aug where two
decision batches ran *concurrently* and their rows interleave (decision A 13:46:13, decision B
13:46:16, outcome B 13:47:02, outcome A 13:47:05). Rule that survives it, used in section 8:

- rows that carry `decision_ref` join by it (outcome rows today; `sizing` and
  `structures_simulated` from the first commit on, see section 9.2);
- rows without it (`sizing` and `structures_simulated` written before that commit,
  `competence`) join by **interval containment**, `decision.ts <= row.ts <= outcome.ts`, and
  when two intervals both contain the row, by matching `underlying` to the cycle's theses,
  then by the earlier decision; the exporter counts and logs ambiguous attributions;
- `structures_simulated` additionally carries `thesis_entry_id`, a direct link to the ledger
  row, which is the preferred join when present.

Rows of interest that fall inside decision intervals: 4 of 4 `structures_simulated`, 12 of 12
`sizing`, 187 `competence`. `muse` (31) and `playbook` (5) rows are written BEFORE the
decision row in the same tick and are not part of a cycle; they feed the funnel and the
Coach section, and a playbook row is shown in a cycle only when it matches a thesis by
`(underlying, horizon)` within 15 minutes before the decision.

**Sense inputs are on disk.** `decision.item_ids` prefixes across all cycles: `new` 220,
`pos` 125, `opp` 59, `pre` 37, `man` 13, `mar` 2 (the prefix is `kind[:3]` from
`ids.item_id`). Every item of the five most recent decisions exists under
`agent/data/inbox/processed/<day>/`. Days present: 26, 27, 28, 31 Aug, 1, 2, 3 Sep. No purge
code exists in `inbox.py`.

**The tick field is not where it needs to be.** `decision`, `no_op`, `execution` carry
`tick`; `sizing`, `structures_simulated`, `playbook`, `muse` do not. The interval rule above
is why this does not matter for history, and section 9.2 is why it stops mattering for the
future.

**Byte budget.** A candidate's payoff at expiry is piecewise linear with kinks only at its
strikes, so its exact polyline is the strikes plus two end points: 4 to 8 points, not the 160
`derive_payoff` uses for positions. Twenty cycles at ~5 KB each (40 closes, up to 4 theses,
up to 6 candidates with kinked payoffs, the decline prose) is ~100 KB; the extended forecasts
~20 KB; funnel and Coach under 6 KB. About 125 KB on a 898 KB file.

**How the snapshot actually reaches the browser - a finding that changes the rollout.**
`ls -la web/build/_app/immutable/chunks/` shows one 864,845-byte chunk, and it contains the
snapshot (grep for `account.start_note`'s text finds it there). Every `+page.js` is a
*universal* load, so Vite bundles the JSON as a shared client chunk and **every page downloads
the whole 865 KB** on first visit, then slices it in the browser. The `load()` slicing that
the codebase believes protects page weight protects nothing. Fix: server-only loads
(`+page.server.js`, `+layout.server.js`), which under `adapter-static` + `prerender` run at
build time and inline only the returned slice into each page. This plan does that first
(section 12, commit 1), because the demo adds 125 KB to a file that should never have reached
the client at all. Expected result: largest chunk under 100 KB, every page's HTML carrying
only its own data.

## 3. The design in one paragraph

`/demo` is one page in the ledger register titled **Watch Theo decide.** Its spine is a
**replay of one real decide cycle**, chosen from a reel of the most informative recent cycles
(rule-selected on every publish, never hand-picked, always including the latest), laid out as
the five stages the how-it-works page already teaches: Sense (what arrived), Think (the
claim, drawn as a band on a real price chart, and every structure priced for it with the
rejected ones greyed and their reason verbatim), Act or Declined (what it did, how big and
why that big, or the recorded reason it did nothing), Learn (how the claim resolved against
the tape and what the position was attributed), Remember (what the cycle wrote to which
store). One interaction model runs the whole page: pick a cycle, and every frame re-renders
from that cycle's recorded rows; hover or tap a structure and its payoff draws with the thesis
band shaded so the viewer sees, in one picture, whether it pays when the claim holds. Below
the replay, three quiet sections put the cycle in context: **Where ideas go.** (a funnel of
real counts, with the not-taken remainder labelled at every step), **Scored anyway.** (every
resolved forecast as a dot at its stated probability, traded and declined alike, with the
honest n_eff caveat), and **Then it grades itself.** (the Coach's open experiment, its
posterior, its floors, the mutation's own rationale). The elves appear as small reactions in
the frame corners, never as decoration on empty space. A primary button in the hero, a nav
link, and a button on the judges page lead to it.

## 4. The page, frame by frame

Copy is given verbatim so the voice cannot drift. Headings are short declarative sentences
with a full stop; kickers are mono uppercase labels; numbers go through `format.js`.

### 4.0 Header and the reel

```
kicker      Watch it decide
h1          Watch Theo decide.
standfirst  One real cycle of the loop, replayed from the record: what arrived, the claim
            it made, the structures it priced and threw out, what it did about it, and how
            that was scored afterwards. Nothing here is generated for this page. Every
            number was written by the loop at the moment it happened, and it refreshes
            with the record.
record bar  Equity {usd0} ({pct pnl}) · {n} claims · {n} traded · {n} declined · {n} scored
```

The **reel** is a horizontally scrolling strip of cycle chips, newest first, each reading
`tick {tick} · {dd Mon} {HH:MM} · {underlying(s) or "holding"}` with an outcome pill using the
existing `.pill` classes: `traded`, `declined`, `rejected`, plus a `.pill.gap` for an `error`
outcome. The selected chip has `aria-pressed="true"` and the accent border. A `Latest` button
selects the first chip. Left and right arrow keys move the selection when the strip has focus.
The selection is mirrored into the URL hash as `#tick-812` via `history.replaceState`, read
once on hydration and on `hashchange`; an unknown tick falls back to the latest without an
error. Under the strip, one `.fine` provenance line: `decision {id} · outcome {kind} {id} ·
model {model} · {n} tool calls`.

**Reel selection rule** (exporter, section 8.1): newest first, a cycle qualifies if it traded,
or recorded at least one thesis, or has candidate structures, or has a sizing row; the latest
cycle qualifies unconditionally whatever it did; cap 20. `error` outcomes qualify only as the
latest. The full stream stays on `/ledger`; the page links there.

### 4.1 Sense. What arrived.

Kicker `01 · Sense`. Heading **What arrived.** A list of the items the decision read, at most
six shown with `and {n} more` after, in this order: opportunities, position reviews, news,
manual, other.

- opportunity: `{source} opportunity · {UNDERLYING}` chip row, then the claim in a `Callout`
  (`eyebrow` = `the claim, as it entered the prompt`), then `.fine`: `band {low}-{high} ·
  resolves {horizon} · suggested: {suggested_structures joined with " / "}`.
- position: `reviewing open position {UNDERLYING} {strategy}` linking to `/ledger/{position_id}`.
- news: headline, `.fine` `{source} · {created_at} · {symbols}`; the URL is not linked (no
  external links from the replay; the source label is enough).
- manual: `operator note` and the text.
- other kinds: `{kind} item {id}` in mono, nothing invented.

Right column (`.cols.side-r`): **the market it saw**, when a candidate row recorded it: spot,
IV, expected move (`sigma` in dollars when present, else `not recorded`), days to expiry, and
`priced {HH:MM}`. If nothing recorded it: one `.muted` line `No chain was priced this cycle.`

Empty state (a cycle with no items): `.muted` `The decision read no inbox items this cycle
(a positions-only review).` No elf on this frame.

### 4.2 Think. A claim that can be proved wrong.

Kicker `02 · Think`. Heading **A claim that can be proved wrong, and the ways to bet on it.**
Elf: `elf-thinking.jpg` in a `.plate.sm` at 96px, top right of the frame header.

**Theses** recorded in the cycle, as cards. When more than one, the cards are radio-selectable
(`role="radiogroup"`, arrow keys), and the selected thesis drives the chart and the candidate
table; default selection is the traded thesis, else the one with candidates, else the first.
Each card: `{UNDERLYING}` chip, source pill (`thesis` / `muse` / `standalone` as the ledger
kind), the claim, then `.fine`: `stated {pct}` or `probability not stated (0.5 assumed by
code, excluded from calibration)` when `probability_stated` is false; `resolves {horizon}`;
`band {low}-{high}` (one-sided bands render as `above {low}` or `below {high}`); `metric
realised vol` when `metric == realized_vol_pct`.

**The price chart** (new `PriceBand.svelte`, same skeleton as `EquityCurve`): the last 40
daily closes up to the decision day as an ink line, the decision day marked with a solid
vertical, the horizon with a dashed vertical, the band as an `--accent-soft` rectangle from
decision day to horizon (open-ended bands shade to the chart edge), and, once resolved, the
close at horizon as a dot: accent with a `✓ held` label, danger with a `✗ failed` label
(text always accompanies colour). Under two closes: `.muted` `No price history on record for
{UNDERLYING}.` Chart `aria-label`: `{UNDERLYING} closes with the claimed band`.

**The structures** priced for the selected thesis, as a table in a `.scroll` wrapper (cards
under 620px): structure, family (via `strategyLabel`), entry, max profit, max loss,
`P(profit | claim holds)`, `P(profit | claim fails)`, edge, and **fate**. Survivors in ink;
rejected rows in `--ink-faint` with the fate string verbatim in a `.tag.warn`
(`rejected: indifferent to the thesis (edge +0.23)`). The chosen structure (the one sized, or
traded) carries `.tag.good` `chosen`. Column header tooltips via `Term` for `edge` and
`P(profit | claim holds)` (add both to `glossary.js`). Hovering or focusing a row (tap on
touch) selects it; the default selection is the chosen one, else the first survivor.

**The payoff with the band** (new `CandidatePayoff.svelte`, or `PayoffChart` extended with an
optional `band` prop - prefer extending, one chart component): the selected structure's
payoff polyline from its kinks, the zero line, breakevens, entry spot, and the thesis band
shaded across the full height. Caption: `Fact - contract arithmetic. The shaded band is the
claim. A structure that expresses the claim is above zero inside it and below zero outside it.`
That sentence is the whole of D-122 in one picture.

Source line: `structures from {structures_simulated | playbook} row {id}`. When a cycle has
theses but no candidate rows (every cycle before 3 Sep): the table is replaced by one `.muted`
line `{n} structures were simulated for this claim (the record itemises them from 3 Sep 2026
on)` when the ledger note says so, else `No structures were priced for this claim.`; for a
traded position, add `see the trade story` linking to `/ledger/{position_id}` where the blog's
own table lives.

Empty state (no thesis this cycle): the frame collapses to its heading and one line, `No new
claim this cycle.` The elf stays.

### 4.3 Act. What it did, and how big. / Declined. Why it did nothing.

Kicker `03 · Act`. Heading by outcome: **What it did, and how big.** (traded), **Why it did
nothing.** (declined), **What went wrong.** (error). Elf: `elf-confident.jpg` when traded,
`elf-analysing.jpg` when declined, none on error.

Traded: three stat tiles - `Contracts` (`{n}` with provenance `{structure}`), `Fraction of
equity` (`{pct fraction}` with provenance `bound by {binding}`; `binding` missing renders
`binding not recorded`), `Max loss` (`{usd0}`); then the ladder position in one line, `sized
at the {tier} rung · book cap {pct} · Kelly multiplier {num}` from the cycle's `competence`
row; then the order as a leg table (`side · qty · OCC symbol · parsed strike/right/expiry`)
and a fill line: `fill confirmed at the broker` / `never filled - abandoned` / `fill not yet
reconciled`, from the reconciliation finding or the position status; a link `open the
position` to `/ledger/{position_id}`. If a sizing refusal was recorded, its reason appears as a
`Callout caution` (none exist yet; the code path does).

Declined: the outcome row's prose in a `.quote` block with `cite` `the decision's own summary`,
rendered through `md()` exactly as the ledger does. Below it, when the cycle recorded a thesis
anyway: a `Callout` eyebrow `scored anyway` - `Theo declined the trade but recorded the claim.
It resolves on {horizon} against the tape at zero capital risk, and counts in the calibration
sample exactly like a traded one.` (D-052 made visible.) When a muse fate rejected the idea
before it reached a thesis, the fate string in a `.tag.warn`.

Error: `The cycle failed before deciding: {error class only}` where the class is the text up
to the first `(`; never the full message.

### 4.4 Learn. How it was scored.

Kicker `04 · Learn`. Heading **How it was scored.** Elf: `elf-success.jpg` when every
resolved claim held, `elf-analysing.jpg` when any failed, none when unresolved.

Per thesis: `held` / `failed` pill with `close at horizon {usd} vs band {low}-{high}`; the same
dot is on the Think chart. Unresolved: `resolves {horizon}` with `in {n} days` computed from
`generated_at` (never from the browser clock, so the build is deterministic); horizon passed
but unresolved: `awaiting a price for {horizon}`. Per position: the exit row (`{close_reason}
- {explanation}`), the recorded P&L (`{pct last_pnl_pct} of net entry cost`), and the
attribution verdict as a `.tag` toned by the existing `ATTR_TONE` map with the label
(`view wrong, structure faithful`), or `attribution fires once the horizon has passed`
in `.muted`. Never-filled: `never filled, nothing to score`.

Interim outcomes (`interim_outcome` rows for the position) render as a `.fine` line
`interim marks: {list of pct}` only when present.

### 4.5 Remember. What it kept.

Kicker `05 · Remember`. Heading **What it kept.** Elf: `elf-coding.jpg`. Four small cards
in a `.cols.c4`, named exactly as how-it-works names the stores:

- **journal** - `{n} rows this cycle` and the kind breakdown as `.fine` (`decision 1 · sizing
  1 · structures_simulated 1 · execution 1`).
- **ledger** - `{n} claim(s) recorded` with the entry ids in mono.
- **wiki** - the position page path and blog path when a trade was recorded, else `nothing
  new`.
- **elfmem** - `fill credited a memory block` when a `fill` row exists, `attribution credited
  {n} block(s)` when attribution ran, else `nothing credited yet`.

### 4.6 Where ideas go.

Kicker `The funnel`. Heading **Where ideas go.** Standfirst: `Most of what Theo thinks of
dies before money moves. Every step below is a count from the record, and the part that did
not go on is written next to the part that did.` A vertical list of steps, each a label, a
count, a bar proportional to the count on a linear scale, and the not-taken remainder as
`.fine` text:

```
ideas            {muse candidates} from the muse · {research opps} from research · {discovery opps} from discovery
gates            {n} rejected at research · {n} rejected at the gates ({top two reasons})
claims           {n} recorded · {n} carried a code-default probability
structures       {n} claims priced · {n} structures thrown out
sized            {n} sized · {n} refused
traded           {n} traded · {n} never filled · {n} cycles declined outright
scored           {held} held · {failed} failed · {n} still open
attributed       {n} attributed · {n} unscoreable · {n} awaiting the horizon
```

No Sankey. The bars are the visual; the text is the record.

### 4.7 Scored anyway.

Kicker `Calibration`. Heading **Scored anyway.** Standfirst from
`calibration.verdict` verbatim, in a `Callout`. Then the dot strip (new `ForecastDots.svelte`):
x axis 0 to 100% stated probability, two lanes `held` (top) and `failed` (bottom), one dot per
resolved forecast with a stated probability; filled accent dot = traded, hollow = declined;
`<title>` on each dot = `{UNDERLYING}: {claim first 120 chars}`. Under it, a reliability table
by decile: `stated · n · held` with rows only for non-empty deciles, and the line `{n}
claims carried a code-default 0.5 and are not plotted.` Nothing is smoothed; nothing is
fitted.

### 4.8 Then it grades itself.

Kicker `The Coach`. Heading **Then it grades itself.** Standfirst: `Two levers the Coach is
allowed to move, each scored by arithmetic it cannot reach. A challenger is promoted only on
evidence, and there have been {promotions_total} promotions so far.` One card per lever:
name and subsystem, `incumbent {id} {fingerprint} ({origin}, since {date})`, the
`reward_description` as `.muted` prose (it is written for exactly this reader), and, when an
experiment is open: `{challenger} vs {incumbent}`, `{runs} paired runs · challenger
{s_c}/{n_c} · incumbent {s_i}/{n_i}`, a bar for `P(better) {num3}` with a tick at
`promote_at` and one at `futility_at`, the verdict line exactly as `trdrbot coach status`
prints it (`still gathering evidence` or `-> promoted: ...`), a sparkline of the posterior
across trials, and the mutation rationale as a `.quote` with `cite` `the Coach's own reason
for this challenger`. No experiment: `no experiment open`.

### 4.9 Close

A `.cols.c3` of three `a.card` doors: `Every decision, newest first.` (`/ledger`), `How the
loop is built.` (`/how-it-works`), `For judges.` (`/submission`).

## 5. Non-negotiable rules (each traces to a measured incident or a standing principle)

1. **No number is typed into the page.** Everything renders from the snapshot through
   `format.js` (notes/027: the deck and the site must never render one fact two ways).
2. **Nothing is reconstructed.** A missing row renders `not recorded` or the frame's stated
   empty line (the `/data` page's promise). No blog-table parsing, no re-pricing, no
   client-side payoff arithmetic: candidate payoffs are computed once, in Python, by the same
   `optmath.pnl_at` the agent uses.
3. **Selection is a rule, not a list.** The reel is chosen by the exporter's documented rule
   so it updates itself; an implementer must not hand-pick "good" cycles.
4. **Colour never carries meaning alone** (design system). Held/failed dots carry `✓`/`✗`
   text; rejected rows carry the fate string.
5. **Static stays static.** No `fetch`, no timers, no autoplay. The only client state is the
   selected cycle, thesis, and structure, and the URL hash mirror.
6. **Motion discipline.** CSS only, the site's one `pulse` keyframe plus at most one new
   `rise` keyframe for the frame stagger on cycle change, both under
   `@media (prefers-reduced-motion: reduce) { animation: none }`.
7. **Facts and models are labelled.** Payoff arithmetic carries the existing
   `tag code` `Fact - contract arithmetic`; `p_hold`, `p_fail`, `edge`, `p_band` carry a
   `tag ai`-style `Modelled - lognormal, drift 0` label once per table, not per cell.
8. **The page never claims what the record cannot back.** `playbook_outcome` is empty until
   11 Sep; attribution is 11 of 13 unattributed. The Coach section says "measuring, not yet
   concluding" through the verdict line, not through copy that hopes.
9. **Page weight is a budget.** After commit 1, no page's client JS may include the snapshot.
   The demo's own data slice must stay under 200 KB in the built HTML; the exporter prints
   the `cycles` byte size on every export.
10. **The hero wording map is respected.** Adding the button touches `+page.svelte` only; the
    hero sentence is not changed. `web/CLAUDE.md` gains the demo's own copy under a new
    heading so the next rewrite finds it.

## 6. Alternatives considered and rejected

| Alternative | Why it lost |
|---|---|
| A live dashboard with runtime fetch (the reference site's shape) | The site is static by design; the loop ticks every five minutes so a per-publish rebuild is within one tick of live anyway; and a wall of panels is the busy-ness the request rejected |
| Typewriter "activity stream" of journal rows | Motion without meaning; every row would need reading; it is the reference site's worst panel |
| A standalone HTML document in `docs/` like the risk explorer | Would duplicate `format.js`, the pill and chart components, and the snapshot slicing - the exact drift notes/027 removed. A Svelte route shares all of it |
| Scrollytelling with `IntersectionObserver`-driven reveals | Fragile on mobile and for screen readers; a picker plus five always-visible frames is simpler, keyboardable, and prints |
| A charting library | Zero-dependency site; `EquityCurve` and `PayoffChart` already prove the hand-rolled pattern; every chart here is a polyline, a rectangle, and dots |
| Sankey for the funnel | Pretty, busy, and wrong for eight stages whose counts differ by 20x; bars with the remainder written out say the same thing legibly |
| A spatial "Theo's desk" with objects to open | Illustration cost, gimmick, and the brand register the site never uses. The elves earn their place as *reactions* to real outcomes instead |
| Showing the muse prompt diff between incumbent and challenger | Strong, but the prompt is long and the diff noisy; the rationale carries the story. Deferred, section 14 |
| Parsing the blog's "Structures considered" markdown table for pre-3 Sep cycles | Reconstruction from a rendered artifact; brittle; and the page links to the story where the table already is |
| Client-side payoff arithmetic from candidate legs | A second implementation of `optmath.pnl_at` in JavaScript, which the notes/027 rule forbids; the kinked polyline from Python is exact and tiny |
| Naming the block `demo` in the snapshot | Data is named by what it is, not who reads it: `cycles`, `funnel`, `coach`, and the extended `forecasts_resolved` can serve the ledger and scoreboard later |

## 7. Scenarios simulated

| Scenario | What the page shows | Handling required |
|---|---|---|
| A judge with two minutes, desktop | Header, record bar, the latest cycle already selected, five frames scrolling | Latest is the default; nothing to click before the story starts |
| The latest cycle is a plain "holding" decline (most cycles are) | Sense lists the position reviews; Think collapses to `No new claim this cycle.`; Act shows the recorded reasoning with the analysing elf; Learn and Remember say what little happened | Honest and short; the reel's next chip is one keypress away |
| A traded cycle with structured candidates (3 Sep NVDA) | The full story: three structures, one chosen, band-shaded payoff, sizing bound by the exploration floor, fill confirmed, resolves 11 Sep | This is the showcase; make it the second chip's content by rule, not by hand |
| A cycle with three theses in one batch | Thesis radio cards; chart and table follow the selection | `selectedThesis` state; default rule in 4.2 |
| The loop stopped (`frozen: true`) | Everything still renders; `in {n} days` is computed from `generated_at`, so it freezes with the record | No browser clock anywhere |
| A thesis whose horizon passed without a price | `awaiting a price for {horizon}` | Distinguish `resolved_at` null with horizon past from horizon future |
| An `error` outcome (auth failure on day one) | Only shown when it is the latest; `What went wrong.` with the class only | Section 4.3 |
| Two concurrent batches (27-28 Aug) | Rows attributed by interval and underlying; the exporter's log line reports ambiguous attributions | Section 8.1 join; test in 11.1 |
| An inbox item file missing | `{kind} item {id}` with `not recorded` for its text | No invention |
| Mobile, 375px | Reel scrolls horizontally with a visible edge fade; candidate table becomes stacked cards; charts scale; frame elves hide under 620px | CSS in `app.css`; existing `.scroll` pattern |
| Screen reader | Reel is a `toolbar` of buttons with `aria-pressed`; frames are `section`s with headings; charts have `role="img"` and labels; the candidate table is a real `<table>` | Existing conventions |
| Dark mode | Tokens only; the band uses `--accent-soft`; plates keep the brand cream | Existing `.plate` |
| Deep link `#tick-812` shared in the submission | Opens with that cycle selected; unknown tick falls back to latest | `hashchange` handling |
| Snapshot grows for a week | Reel is capped at 20; closes at 40; candidates at their kinks; the exporter prints the block's size | Budget in rule 9 |
| A future sizing refusal | `Callout caution` with the recorded reason | Handled now, exercised later |
| `playbook_outcome` rows start on 11 Sep | Not shown by this plan; section 14 says where they go | No claim made before then |

## 8. The data contract: snapshot additions

All new keys are written by `site_export.export()` next to the existing ones, pass through the
redaction scan unchanged (it walks every string), and are excluded from the monotonicity
guard (a capped reel is not monotonic; `counts.cycles` is added to `counts` for the record but
NOT to the guard's key list, which stays deliberately narrow).

### 8.1 `cycles[]` (newest first, max 20, selection rule in 4.0)

```json
{
  "id": "jrn_20260903T175400Z_dec...",      "tick": 812,
  "ts": "2026-09-03T17:54:00Z",             "model": "openai:gpt-5.6-sol",
  "batch": "bat_...",                        "tool_calls": 7,
  "outcome": "traded" | "declined" | "error",
  "outcome_ref": "jrn_..._exe...",           "outcome_ts": "...",
  "ambiguous_joins": 0,
  "sense": {
    "items": [
      {"id": "opp_...", "kind": "opportunity", "source": "research", "underlying": "NVDA",
       "claim": "...", "band_low": 232.0, "band_high": 245.0, "horizon": "2026-09-11",
       "suggested_structures": ["..."]},
      {"id": "pos_...", "kind": "position", "position_id": "pos_...", "underlying": "SPY",
       "strategy": "reverse_iron_condor"},
      {"id": "new_...", "kind": "news", "headline": "...", "source": "benzinga",
       "created_at": "...", "symbols": ["NVDA"]},
      {"id": "man_...", "kind": "manual", "text": "..."},
      {"id": "pre_...", "kind": "pre", "text": null}
    ],
    "items_total": 3,
    "market": {"underlying": "NVDA", "spot": 230.2, "iv_pct": 31.5, "sigma": null,
               "days": 8, "expiry": "2026-09-11", "priced_at": "..."} | null
  },
  "think": {
    "theses": [
      {"entry_id": "jrn_..._fc...", "kind": "thesis", "underlying": "NVDA", "claim": "...",
       "probability": 0.62, "probability_stated": true, "horizon": "2026-09-11",
       "band_low": 232.0, "band_high": 245.0, "metric": "price_band",
       "traded": true, "position_id": "pos_...", "rejected_by": "",
       "outcome": null, "resolved_at": null, "price_at_horizon": null,
       "structures_note": "3 structures simulated",
       "closes": {"dates": ["2026-07-15", "..."], "closes": [154.4, "..."]},
       "candidates_ref": "jrn_..._str..." | null}
    ],
    "candidates": [
      {"ref": "jrn_..._str...", "source": "structures_simulated" | "playbook",
       "entry_id": "jrn_..._fc...",
       "rows": [
         {"name": "NVDA 230/240 bull call spread", "family": "bull_call_debit",
          "legs": [{"right": "C", "strike": 230.0, "side": "long", "qty": 1, "price": 5.1,
                    "expiry": "2026-09-11", "symbol": "NVDA260911C00230000"}],
          "fate": "candidate", "chosen": true,
          "net": 300.0, "max_profit": 700.0, "max_loss": -300.0, "entry_friction": 6.0,
          "p_band": 0.31, "e_hold": 210.4, "p_hold": 0.83, "p_fail": 0.21, "edge": 0.62,
          "payoff": {"points": [[195.5, -300.0], [230.0, -300.0], [240.0, 700.0],
                                [276.0, 700.0]],
                     "breakevens": [233.0], "max_profit": 700.0, "max_loss": -300.0}}
       ]}
    ],
    "muse_fates": [{"underlying": "NVDA", "fate": "rejected: base probability 7% - a lottery ticket",
                    "stated": 0.07}]
  },
  "act": {
    "sizing": {"contracts": 18, "fraction": 0.05063, "binding": "exploration floor",
               "payoff_ratio": 2.33, "structure": "NVDA 230/240 bull call spread",
               "family": "bull_call_debit", "result": "sized", "reason": null} | null,
    "competence": {"tier": "scale", "book_cap": 0.35, "kelly_multiplier": 0.2922,
                   "seed_fraction": 0.0525} | null,
    "position_id": "pos_..." | null, "legs": [...position legs with parsed...],
    "max_loss_usd": 5400.0 | null,
    "fill": "fill_confirmed" | "never_filled" | "unreconciled" | null,
    "orders_rejected": [{"name": "close_position", "error": "HTTP 422 ..."}],
    "summary_html": "<p>No action this cycle.</p>..." | null,
    "error_class": "AnthropicAuthenticationError" | null
  },
  "learn": {
    "forecasts": [{"entry_id": "...", "held": true, "price_at_horizon": 236.1,
                   "resolved_at": "..."}],
    "attribution": {"verdict": "thesis_wrong_expression_faithful",
                    "label": "view wrong, structure faithful", "signal": 0.1} | null,
    "exit": {"close_reason": "time_stop", "explanation": "...", "ts": "..."} | null,
    "last_pnl_pct": 0.542 | null,
    "interim": [{"ts": "...", "pnl_pct": -0.035}]
  },
  "remember": {
    "journal_kinds": {"decision": 1, "sizing": 1, "structures_simulated": 1, "execution": 1},
    "ledger_entry_ids": ["jrn_..._fc..."],
    "wiki_path": "data/wiki/positions/pos_....md" | null,
    "blog_path": "data/blog/pos_....md" | null,
    "elfmem": {"fill_credited": true, "blocks_credited": 0}
  }
}
```

`closes` holds the 40 sessions ending on the decision day plus every session through the
horizon that exists on disk (so the resolution dot has a line to sit on); dates and closes are
parallel arrays. `payoff.points` are the kinks: `optmath._critical_points(legs)` plus
`min_strike * 0.85` and `max_strike * 1.15`, each evaluated with `optmath.pnl_at`; the
exporter asserts `min(y) == max_loss` and `max(y) == max_profit` within one cent and drops
the payoff (not the row) with `payoff: {"derivable": false, "reason": ...}` if they do not
reconcile, mirroring `derive_payoff`'s discipline.

### 8.2 `funnel`

```json
{"ideas": {"muse_candidates": 0, "muse_emitted": 0, "research_opportunities": 0,
           "discovery_opportunities": 0},
 "rejected": {"research": 16, "gates": 14,
              "gate_reasons": [["no options chain inside the deadline", 9],
                               ["base probability N% - a lottery ticket", 5]]},
 "claims": {"recorded": 199, "code_default_probability": 51},
 "structures": {"claims_priced": 28, "thrown_out": 5, "kept": 15},
 "sized": {"sized": 12, "refused": 0},
 "traded": {"traded": 11, "never_filled": 3, "cycles_declined": 165},
 "scored": {"held": 38, "failed": 57, "open": 104},
 "attributed": {"attributed": 1, "unscoreable": 1, "awaiting": 11}}
```

Gate reasons are grouped by replacing the digits in `rejected: base probability N%` with `N`
before counting, and the `rejected: ` prefix is stripped for display. Where a funnel number
restates an existing `counts` key it is computed from the same source and a test pins the
equality (11.4).

### 8.3 `coach`

```json
{"enabled": true, "promotions_total": 0, "trials_scored_today": 3, "open_experiments": 1,
 "levers": [
   {"name": "muse.prompt", "subsystem": "muse", "kind": "prompt",
    "reward_modules": ["muse.gates"], "reward_description": "...",
    "incumbent": {"id": "v0", "fingerprint": "7809d229", "origin": "seed", "since": ""},
    "challenger": {"id": "v1", "fingerprint": "120b2390", "origin": "mutation",
                   "since": "2026-08-29T09:13:54Z"} | null,
    "state": "running" | "blocked: ...", "paused": false, "pinned": false,
    "experiment": {
      "exp_id": "...", "opened": "...", "runs": 15, "voided": 6,
      "challenger": {"survived": 69, "n": 75}, "incumbent": {"survived": 65, "n": 75},
      "posterior": 0.848, "floors": {"promote_at": 0.9, "futility_at": 0.05,
                                      "min_runs": 8, "cap_runs": 40},
      "verdict": {"outcome": "", "reason": "still gathering evidence"},
      "posterior_series": [0.5, 0.5, 0.61, "..."],
      "mutation_rationale": "..." | null
    } | null,
    "history": [{"challenger": "v1", "outcome": "promoted", "reason": "...", "ts": "..."}]}
 ]}
```

Built with `coach.LEVERS`, `coach.load_state`, `coach.tally`, `coach.floors`,
`coach.verdict`, `coach.events` - the same calls `cli._coach` makes, so the page's verdict
line and the terminal's are one function. `posterior_series` is
`posterior_p_challenger_better` from each `trial_result` row of the open experiment in
`run_nonce` order.

### 8.4 `forecasts_resolved[]` - extended in place

Each existing row gains `entry_id`, `claim`, `probability_stated`, `horizon`, `band_low`,
`band_high`, `kind` (ledger kind), joined from the ledger by `entry_id`. Existing consumers
read only the old keys and are unaffected.

### 8.5 `counts.cycles`

Total decide cycles (decision rows with an outcome). Recorded, not guarded.

## 9. Module-by-module specification

### 9.1 `agent/src/trdrbot/site_export.py`

New pure functions, each taking already-loaded rows so the tests need no filesystem beyond
a fixture directory:

- `build_cycles(rows, ledger_rows, positions, inbox_index, closes_dir, *, cap=20) ->
  tuple[list[dict], dict]` returns the reel and `{"cycles_total": n, "ambiguous_joins": n}`.
  Steps: index outcome rows by `decision_ref`; for each decision with an outcome build the
  interval; attach rows by `decision_ref` when present else by the interval rule; attach
  ledger entries by `created` in the interval (with the same underlying tie-break); attach
  `structures_simulated` by `thesis_entry_id` first; attach a `playbook` row when its
  `(underlying, horizon)` matches a thesis and `decision.ts - 15min <= row.ts < decision.ts`;
  attach `forecast_resolved` by `entry_id`, `attribution`/`exit`/`fill`/`reconciliation`/
  `interim_outcome`/`blog_entry` by `position_id`; classify the outcome; apply the reel rule.
- `inbox_index(inbox_dir) -> dict[str, dict]`: one glob over `processed/*/*.json` (and
  `manual/` if present), keyed by id, tolerant of unreadable files (skipped, counted, printed).
- `candidate_payoff(legs: list[dict]) -> dict`: kinks via `optmath.Leg(**leg)` and
  `optmath.pnl_at`, reconciled against the row's `max_profit`/`max_loss`.
- `closes_window(closes_dir, symbol, decision_day, horizon, *, back=40) -> dict | None`.
- `build_funnel(rows, ledger_rows, positions, counts) -> dict`.
- `build_coach(cfg) -> dict`, importing `coach` lazily exactly as `cli._coach` does.
- `extend_forecasts(forecasts_resolved, ledger_rows) -> list[dict]`.

`export()` calls them after `build_ledger_items`, adds `cycles`, `funnel`, `coach`, extends
`forecasts_resolved`, sets `counts["cycles"]`, and prints one line:
`[site_export] cycles: 20 of 202 (+{kb} KB), ambiguous joins: 0`. The decline prose reuses
`clean_prose` + `md`, the same path as `ledger_items`.

### 9.2 `agent/src/trdrbot/local_tools.py` and `tick.py` - the rows learn their cycle

`SharedContext` gains `decision_ref: str = ""`. `tick.py` sets `shared.decision_ref =
decision_id` immediately after constructing `shared` (the `decision_id` is already in scope,
`tick.py:833`). `build_simulate_experiments` passes `decision_ref=shared.decision_ref` into
the `structures_simulated` append (`local_tools.py:403`); every `_journal_sizing(...)` call
passes `decision_ref=shared.decision_ref` (`build_size_position` already receives `shared`,
`tick.py:910`). Two rows, one field each, so the interval rule becomes a fallback for history
rather than the join. Restart the loop after this commit (the running loop keeps old code).

### 9.3 Server-only loads (commit 1, before any demo code)

Rename every `web/src/routes/**/+page.js` that imports the snapshot to `+page.server.js`,
and `+layout.js` to `+layout.server.js`; keep `prerender = true` and the `entries()`
functions (both are valid in server files). `CompetenceLadder.svelte` imports the snapshot
directly; change it to take `competence` as a prop (the scoreboard already has the object).
Routes with no page file keep inheriting from the layout. Verify: `npm run build`, then the
largest file in `build/_app/immutable/chunks/` is under 100 KB and `grep -rl "start_note"
build/_app` finds nothing; `build/index.html` and `build/ledger.html` still render the same
figures (diff the built HTML of three pages before and after; only hashed asset names may
differ).

### 9.4 `web/src/routes/demo/+page.server.js`

```js
import snapshot from '$lib/data/snapshot.json';
export const prerender = true;
export function load() {
	const { cycles, funnel, coach, forecasts_resolved, calibration, account, counts,
	        generated_at } = snapshot;
	return { cycles, funnel, coach, forecasts: forecasts_resolved, calibration, account,
	         counts, generatedAt: generated_at };
}
```

### 9.5 `web/src/lib/demo.js` - pure view-model functions, node-tested

`selectCycle(cycles, hash)` (unknown → first), `defaultThesis(cycle)`, `defaultCandidate(rows)`,
`frameHeading(outcome)`, `daysUntil(iso, generatedAt)`, `groupGateReasons(list)`,
`deciles(forecasts)` (only `probability_stated`), `hashFor(cycle)`. Tested with `node --test`
in `web/scripts/demo.test.mjs`, the runner `inject-figures.test.mjs` already uses.

### 9.6 `web/src/routes/demo/+page.svelte` and components

- `+page.svelte`: `PageHeader` with the copy in 4.0; the record bar; `<CycleReel>`; the five
  `<section class="block ledger frame">` blocks; the funnel, calibration, and Coach sections;
  the close. State: `selectedId`, `selectedThesis`, `selectedCandidate` via `$state`, derived
  cycle via `$derived`. One `$effect` reads the hash on hydration and subscribes to
  `hashchange`; selection writes the hash with `history.replaceState`.
- `CycleReel.svelte`: the strip (`role="toolbar"`, chips as `<button aria-pressed>`), arrow
  keys, `Latest`.
- `PriceBand.svelte`: closes line, decision and horizon verticals, band rectangle, resolution
  dot with text label. Same `W/H/M`, `xs/ys`, `$props.id()` pattern as `EquityCurve`.
- `PayoffChart.svelte`: new optional `band = null` prop `{low, high}` drawing the shaded
  rectangle behind the payoff; existing callers unchanged.
- `CandidateTable.svelte`: the table and its stacked-card variant, row selection via
  hover/focus/tap, `Term` on two headers.
- `ForecastDots.svelte`: the two-lane dot strip.
- `Funnel.svelte`, `CoachCard.svelte`, `PosteriorBar.svelte` (bar with floor ticks and the
  sparkline).
- `Icon.svelte`: no new icons required.
- `glossary.js`: add `edge` and `P(profit | claim holds)`.

### 9.7 CSS (`web/src/app.css` only)

New classes, in the ledger register: `.record-bar`, `.reel` / `.reel-chip`, `.frame` and
`.frame-head` (kicker, heading, plate slot), `.frame-elf` (hidden under 620px), `.cand-table`
with `.rejected` rows, `.cand-cards` under 620px, `.funnel` / `.funnel-step` / `.funnel-bar`,
`.dots` lanes, `.posterior` bar with `.floor` ticks, and one keyframe `rise` (opacity 0 →
1, translateY 6px → 0, 240ms, staggered by `--i * 60ms`) applied to `.frame` when the
cycle changes, guarded by reduced-motion. Reuse `.pill`, `.tag`, `.callout`, `.quote`,
`.plate.sm`, `.stat-tile`, `.scroll`, `details.expand`, `svg.chart`, `.axis` as they are.

### 9.8 Entry points

- Hero (`web/src/routes/+page.svelte` CTA row): the demo becomes the **primary** button,
  `Watch it decide` with the `arrowRight` icon; `See the ledger` and `For judges` become
  `btn ghost`. Three buttons, existing flex-wrap.
- `Nav.svelte`: `{ href: '/demo', label: 'Demo' }` first in `links`. Add
  `@media (min-width: 760px) and (max-width: 900px) { .nav-links { gap: 1.1rem } }` and
  check the bar at 760, 820, and 900px. Also fold the mobile sheet's three hardcoded extra
  links (Notes, Data, Glossary) into a second array so there is one source (small entropy
  found on the way).
- `/submission`: a `btn primary` `Watch it decide` at the top of the asset button row.
- `/how-it-works`: the "See it live" kicker's card row gets a `Watch it decide` door.
- `Footer.svelte` Explore column: `Demo`.
- `docs/deck.html`: optional, one line on the closing slide `trdrbot.com/demo`; if added,
  regenerate via `release.sh`.

### 9.9 Docs

- `web/CLAUDE.md`: a `## The demo page` section listing the copy in section 4 as the source
  of truth, the reel rule, and the rule that frames render `not recorded` rather than
  reconstruct; the content map gains `/demo` under "paraphrases the hero".
- `specs/decisions.md`: `D-123 - Watch it decide: the demo replays recorded cycles, and the
  snapshot stops shipping to the browser` (both decisions, because the second changes every
  page's weight and belongs on the record).
- `specs/issues.md`: the items in section 13.
- This note gains the BUILT header and divergence table when done, like 026 and 027.

## 10. Edge cases and required handling

| Case | Handling |
|---|---|
| Decision without outcome (orphan, or the cycle running at export time) | Not a cycle; counted in the log line as `in progress: n` |
| Two decision intervals contain a row | Underlying tie-break, then earlier decision; `ambiguous_joins` incremented on the cycle and summed in the log |
| `sizing`/`structures_simulated` carry `decision_ref` (post 9.2) | Joined by it; interval rule only for older rows |
| Thesis with `band_high: null` or `band_low: null` | Rendered `above {low}` / `below {high}`; band shading open to the chart edge |
| `metric == realized_vol_pct` | Chart still shows closes; band line reads `realised vol {low}-{high}%`; no price band drawn |
| No closes file for a ticker | `closes: null`; chart shows the one-line fallback |
| Candidate legs across two expiries (a calendar) | `payoff.derivable: false` with the same reason string `derive_payoff` uses |
| Candidate kinks do not reconcile with the recorded bounds | Payoff dropped with reason; the row stays, the numbers stay |
| Sizing `binding` absent (the first row) | `binding not recorded` |
| `no_op.summary` fails `clean_prose` | `summary_html: null`; Act shows `The decision's summary was not usable (dropped by the prose guard).` - the same drop the ledger already counts |
| Outcome `execution` but no position recorded (an order replace or a close) | `outcome: "declined"`? No: `outcome: "traded"` only when a position was recorded in the interval; otherwise `outcome: "acted"` with heading **What it did.** and the execution summary; `acted` uses the `closed` pill |
| `error` outcome message contains anything key-like | The redaction scan already refuses the export; the page shows the class only regardless |
| Position never filled | `fill: "never_filled"`, Learn says `never filled, nothing to score` |
| Horizon in the future | `in {n} days` from `generated_at`; `n` can be 0 (`today`) |
| Reel has fewer than 2 cycles (a fresh run) | Strip shows what exists; the page works with one |
| Coach disabled in config | `coach.enabled: false` and the section reads `The Coach is disabled in config.` |
| No open experiment | `no experiment open` |
| `probability_stated: false` on every resolved forecast | Dots render nothing; the table says so; the exclusion line carries the count |
| Hash present but reel changed since the link was shared | Falls back to latest; no error |
| `prefers-reduced-motion` | No stagger |
| Under 620px | Elves hidden, table becomes cards, reel edge fade |

## 11. Tests that must exist

Per `docs/principles_testing.md`: pillar tests on the seams, no new eval, fixtures in
`agent/tests/fixtures/demo/` (a journal of ~30 rows, a ledger of 6, two closes files, four
inbox items).

1. `test_cycles_join`: the fixture holds a clean cycle, a concurrent pair (interleaved
   outcomes, different underlyings), an orphan decision, a `resumed_from` re-run, an `error`
   outcome, and a post-9.2 row carrying `decision_ref`. Asserts each row lands in the right
   cycle, `ambiguous_joins` is 0 for the pair (underlying resolves it) and 1 when the
   underlyings match, and orphans are counted as in-progress.
2. `test_reel_rule`: the latest cycle is always first even when it is a plain decline; an
   `error` cycle is included only as the latest; the cap holds; a cycle with only a sizing
   row qualifies.
3. `test_candidate_payoff_kinks`: for a vertical, a butterfly, and a condor from real
   `structures_simulated` rows, the kinks reconcile with `max_profit`/`max_loss` within a cent
   and the point count is at most strikes + 2; a two-expiry candidate returns
   `derivable: false`.
4. `test_funnel_reconciles`: `funnel.traded.traded == counts.traded`,
   `funnel.traded.cycles_declined == counts.declined`, `funnel.claims.recorded ==
   counts.theses`, `funnel.scored.held + failed == counts.forecasts_resolved`.
5. `test_coach_block_matches_status`: the block's verdict for the fixture experiment equals
   `coach.verdict(tally, floors)`; `posterior_series` is in `run_nonce` order.
6. `test_forecasts_extended`: every row keeps its old keys and gains the six new ones; a
   forecast whose ledger row is missing gets `claim: null`, not a crash.
7. `test_export_prints_size_line` (extends the existing export test): the log line names
   the cycle count and the KB delta.
8. Redaction: the existing `redaction_scan` test gains a case where a `sense.items[].text`
   holds a fake `sk-` key and the export refuses.
9. `web/scripts/demo.test.mjs`: `selectCycle` fallback, `defaultThesis` preference order,
   `daysUntil` at 0 and negative, `groupGateReasons` digit folding, `deciles` excluding
   unstated probabilities.
10. Build verification (in the rollout, not a test file): after commit 1 the largest chunk is
    under 100 KB and no built JS contains `start_note`.

## 12. Rollout, commit by commit

Each commit: `cd agent && uv run pytest`, `uvx ruff check .`, `cd web && npm test && npm run
build`, all exit codes captured; restart the loop after commits 2 and any later agent-side
change (`pkill -f "trdrbot run --interval"; nohup uv run trdrbot run --interval 300
--closed-interval 1800 > logs/agent.log 2>&1 &`, then confirm `data/state/run.json` carries
the new sha).

1. **The snapshot stops shipping to the browser** - server-only loads, `CompetenceLadder`
   takes a prop, before/after build diff, chunk size recorded in the commit message.
2. **The rows learn their cycle** - `SharedContext.decision_ref`, the two appends, tests.
   Restart the loop.
3. **`site_export`: cycles, funnel, coach, extended forecasts** - the six builders, tests
   1-8, the size line. Run the export for real and paste the log line into the commit.
4. **`/demo`, the replay** - route, `demo.js` + tests, `CycleReel`, `PriceBand`, `PayoffChart`
   band prop, `CandidateTable`, frames 1-5, CSS. Verify in the browser at 1280 and 375px,
   light and dark, with a traded cycle and a decline selected; keyboard through the reel.
5. **`/demo`, the context** - funnel, dots, Coach, close; elves; the `rise` stagger.
6. **Entry points and docs** - hero primary button, nav (with the 760-900px check), judges
   page, how-it-works door, footer, `web/CLAUDE.md`, D-123, issues. Deploy with
   `./scripts/publish.sh --force`, then verify `trdrbot.com/demo` by direct fetch (not the
   cached tool), and `#tick-{latest}` deep link.
7. **This note's BUILT header** with the divergence table.

## 13. Surfaced issues to fix in the same pass

- **I-126 (new): every page downloads the whole snapshot.** Section 2's finding. Fixed by
  commit 1; log it with the before/after chunk sizes.
- **I-127 (new): `agent/data/metrics.jsonl` carries a row stamped `2027-10-08`.** A year
  ahead of every other timestamp; `model.cal_age_days` reads 400 on it, so the clock was
  wrong for whatever wrote it (the report or a test writing to the real file). The data file
  is append-only and stays as it is; find the writer, make gauge readers ignore rows whose
  `ts` is after the export time, and log the row's origin in the issue.
- **`sizing` and `structures_simulated` rows carry no `decision_ref` or `tick`** - fixed by
  commit 2; note it under D-123 rather than as an issue, since it ships in the series.
- **`Nav.svelte` hardcodes three mobile-only links outside the array** - folded in commit 6.
- **`how-it-works/+page.svelte` uses a `.stage` class that no rule defines** - remove the
  dead class in commit 6.
- **`src/lib/resources.js` calls the loop "Sense → Think → Act → Learn"** (four stages); the
  canonical five include Remember - fix the blurb in commit 6.

## 14. Deferred, deliberately

- **`playbook_outcome` on the page.** The slow audit of the D-122 reward starts writing on
  11 Sep. When rows exist, the Coach section gets a line per resolved proposal (`won`,
  `band_held_at_expiry`, `e_hold` vs realised `pnl`); the exporter change is one builder.
- **The prompt diff** between incumbent and challenger, behind a `details.expand`, capped at
  40 changed lines from `difflib.unified_diff`.
- **Muse concept collisions in Sense** (`this idea came from colliding research/MDB with
  technique/who-audits-this-number`). Needs the opportunity to carry the muse row id; add it
  at the source first.
- **Simplifying `derive_payoff` to kinks** for positions too (160 points → about 6). Correct
  and smaller, but it touches a tested seam for no visible gain; do it when the position
  page is next touched.
- **A recorded walkthrough video** for `siteConfig.videoUrl`. Complementary; the page is the
  thing being recorded.
