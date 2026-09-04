# 029 - The Desk: a claim-first options desk a person can sit at

Audience: an LLM implementer with full repo access. The problem, the design, why the
alternatives lost, the scenarios walked, the exact data contract, the JavaScript port and the
harness that pins it, the edge cases with their required handling, and the tests that must
exist. Read notes/028 first (the replay this sits beside, and the exporter sections it
added), then `web/CLAUDE.md`, then D-099 in `specs/decisions.md` - this plan reopens a question
D-099 closed, and says why.

Plain dashes throughout. No em dashes in code, docs, prompts, or page copy.

## 0. What already exists (read this before proposing anything)

| Piece | State |
|---|---|
| `/demo` (notes/028) | **Works.** A rule-selected reel of real decide cycles replayed through Sense, Think, Act, Learn, Remember. Components it built are reusable here: `PriceBand`, `CandidateTable`, `PayoffChart` with its `band` prop, `Funnel`, `ForecastDots`, `CoachCard`, `CycleReel`, and `demo.js`'s view-model helpers |
| `snapshot.json` sections | **Work.** `positions[]` (26 fields incl. `exit_rules`, `exit_state`, `greeks_at_entry`, `entry_iv`, `payoff`), `cycles[]`, `funnel`, `coach`, `forecasts_resolved[]` extended with claim text, `account`, `competence` (with the earned ladder and the applied caps), `book`, `calibration`, `counts` |
| Server-only loads (notes/028 commit 1) | **Works.** Each page's HTML carries only its own slice; the client bundle no longer contains the snapshot. The desk must keep it that way |
| `publish.sh --force` | **Works.** Export, sync-static, inject, build, verify, deploy - the one deploy path |
| `npm test` (`node --test scripts/*.test.mjs`) | **Works locally, not in CI.** `.github/workflows/agent-tests.yml` runs only the agent's suite |
| The arithmetic, in Python | **Works, and is the only copy.** `optmath` (payoff, lognormal grid, band-conditional), `playbook` (shape, catalogue, anchors, `evaluate`), `sizing` (shrink, Kelly, the constraint order, `binding`), `competence` (tiers, applied caps), `calibration`, `market_stats` (realised vol, bootstrap, band inflation), the muse gates |
| D-099 | **A recorded decision this plan must answer.** `docs/risk_appetite_explorer.html` once carried a JavaScript reimplementation of `shrinkProbability`, `kellyFraction`, `postureFor`, `sizePosition`; it drifted three ways while printing "verified against Python"; the fix was to delete it and ship a Python-computed lookup table. A test asserts those four names never return to that page |
| Price history | **Works.** `agent/data/state/returns/<T>.json`: 112 tickers, exactly 300 sessions each, 216 KB minified for the lot; 73 fresh by the codebase's own 4-day rule; `dates` present on the 73 fresh ones and absent on the 39 stale ones |
| Exit rules | **Work.** `exit_state` is `{"signal:direction:threshold": [bool, bool, bool]}`, a 2-of-3 debounce that only accumulates on open-market ticks for price signals; `exit` rows carry a deterministic `explanation` string |
| Per-position marks | **One number, refreshed every tick.** `last_pnl_pct` (a FRACTION of net entry cost despite the name), written by `exit_rules.py:346` on every tick, open or closed. Its timestamp is the position page's `generated.at`, stamped on every save and **never exported** |
| Market open/closed | **Not journalled.** The broker's `get_clock` decides it per tick and nothing writes it down. The `learn_run` heartbeat's inter-row gap recovers it exactly: 5 minutes open, 30 closed, matching `run.json`'s argv |

**So the arithmetic, the record, and the price history all exist. What does not exist is a
surface a person can operate.**

## 1. The actual gap

`/demo` is a documentary: it replays what Theo did, one cycle at a time, and it does that
well. But a judge who has just come from the other entries has seen *interfaces* - watchlists,
tickets, blotters, a chart - and the question they carry to trdrbot.com is not "can I read
about this" but "what would it be like to use this." The replay cannot answer that, because
nothing on it is operable: you cannot state a claim, you cannot see the desk react, you cannot
be told no.

The conventional options interface those other entries copy is: symbol, chart, chain grid,
strategy builder, order ticket, positions blotter, P&L. Theo inverts that order, and the
inversion IS the product. You do not open a chain and assemble a spread; you **state a claim** -
a ticker, a band, a date, a probability - and the desk derives everything else: the shape of
the claim, the structures that express it, how each one pays when the claim holds and when it
fails, how big the position is allowed to be and which constraint set that size, and two
equally weighted answers, trade it or decline and record the claim. Then it scores you.

The gap is a page that makes that inversion something a visitor does with their hands, on the
latest data, without a backend, and without lying about which numbers are the record, which
are contract arithmetic, and which are a model.

### Three constraints that shape everything

1. **Static stays static.** Every page prerenders from the snapshot; there is no server. "Live"
   means "rebuilt on every publish", within a tick of the loop. The desk's only runtime
   requests are same-origin static JSON files written by the exporter.
2. **D-099 is not overturned lightly.** The house rule is "anything that can drift lives in
   Python and is emitted as data; the page does lookup and arithmetic." A visitor's claim is
   continuous in ticker, band, horizon and probability, so no lookup table can serve it
   (section 7 says exactly why the obvious one is not exact). The port therefore exists, but
   under conditions D-099's fork never met: pinned by fixtures Python regenerates and Node
   executes on every `npm test`, in CI, with the four dead names still forbidden where they
   died.
3. **Nothing on this page may be a fact it is not.** Three provenance tags, on every panel:
   `Fact - the record`, `Fact - contract arithmetic`, `Modelled - <what was assumed>`. A
   visitor's numbers never sit in the same list as Theo's without the split being visible.

## 2. Empirical validation, before the design

Measured on 2026-09-03 against the live tree (tick 858, journal 2,723 rows, ledger 203 rows).

**The book.** 3 open positions (SPY reverse iron condor +7.1%, NVDA bull call spread -17.5%,
PLTR bear put spread +4.8% of net entry cost), each with 3-4 armed rules whose `exit_state`
triples are all `[false, false, false]`. `last_pnl_pct` is written every tick; its
timestamp (`generated.at`, 20:55:40 on all three pages) is up to 58 minutes fresher than the
account strip's `competence` row (19:57:51), which is written only on decide cycles. **One
"as of" on the page would be wrong for two of the three clocks.** The desk shows three.

**The claims.** 62 open (27 muse, 21 standalone, 14 thesis), 8 traded, 5 gate-rejected; 33
resolve tomorrow, 16 on 11 Sep. Every `standalone` row carries a human sentence in `notes`
(median 306 chars, hard cap 400) - the agent's own reason for declining, pre-sized for a card.
`thesis` notes are mechanical (`"3 structures simulated"`); `muse` notes are collision traces.

**The tape.** Of ~640 journal rows in the last 24 hours, ~570 are heartbeats (`exit_run`,
`learn_run`, `attribution_run`, `interim_run`, `coach_run`) and plain declines. A tape that
shows everything is 90% noise; the 70 remaining rows are the desk's tape, and every one has
fields from which a one-line summary is built deterministically (section 9.5).

**Market state.** `get_clock` decides it and nobody writes it down. The `learn_run` gap
histogram over 435 rows: 226 gaps of ~5 minutes, 143 of ~30, matching the loop's two
cadences exactly. `interim_run` presence is only 91% precise (force-decide runs). The gap is
the signal.

**The sandbox's inputs.** 112 tickers x 300 sessions; 73 within 4 days by the codebase's own
`_series_age_days`; all 57 research dossiers have a returns file. No IV series exists
anywhere; the agent's own fallback when a chain has no IV is `compute_stats().realized_vol`
(21-session annualised, percent) stamped `iv_source: "realized"`, and it refuses when even
that is missing. The sandbox reuses exactly that chain.

**The arithmetic, and why a lookup table cannot serve a visitor's claim.** The catalogue's
anchors are in expected-move units and the lognormal grid is built in z-space, so it is
tempting to precompute one dimensionless surface per shape and let the page look it up. It
is not exact: a band placed at spot + k x sigma_dollars maps to z = (ln(1 + k x sig) + sig^2/2)
/ sig where sig = iv x sqrt(t), so the surface depends on sig as a second axis. Making it
exact means a grid over sig too, at several megabytes, and still quantises the band. The
honest options are a port or no sandbox.

**Three parity blockers found by reading the Python, not by porting and discovering.**
(1) There is no Black-Scholes price function anywhere; legs are priced from chain mids in
production and, in the one script that ever needed a synthetic premium, from the bootstrap
expectation of intrinsic. (2) The muse's base probability is `random.Random(str)` seeded
MT19937 with rejection sampling - portable in principle, absurd in practice for a base rate.
(3) Python `round()` is half-to-even on the exact double; JS `toFixed` picks the larger
candidate at an exact binary tie. Section 10 handles all three.

**Page weight.** The desk's own inlined slice, budgeted in section 9.9, lands near 250 KB;
the replay page is 311 KB today. Per-ticker files are fetched on demand and total ~3.4 MB in
the build, none of it on the critical path.

## 3. The design in one paragraph

`/desk` is an application frame, not a page: a status strip, a left rail (the book, the
claims, yours), a centre column (the chart with the claimed band, the structures priced for
the claim, the payoff against the claim), a right column (the ticket), and a tape along the
bottom. Select any real claim or position and the ticket replays Theo's own record of it:
the claim, its shape, the structures it priced with the rejected ones and their reasons, the
size and the constraint that set it, what it did, how it resolved, with a one-click jump to
the full replay on `/demo`. Press **New claim** and the ticket turns warm and becomes yours:
pick a ticker from the 112 with history on disk, drag the band on the chart or type it, pick
a date inside Theo's own 1-10 day window, state a probability, and watch the desk derive the
shape, run the claim through Theo's gates with Theo's exact refusal strings, instantiate the
incumbent catalogue on a modelled chain, score every structure band-conditionally, and size
the one you pick through the same waterfall of constraints Theo's sizer walks, with the
binding row lit. Two equal buttons: **Trade it** and **Decline, record the claim**. Both
record to this browser only; Theo is the only one who trades. Come back after the horizon
and the desk resolves your claim against the real closes and shows your Brier score with the
same humility copy Theo applies to its own. Everything is tagged as record, arithmetic, or
model. Nothing pulses that is not real.

## 4. The desk, panel by panel

Copy is verbatim so the voice cannot drift. Headings are short declarative sentences with a
full stop; panel labels are mono uppercase; numbers go through `format.js`. The frame lives
in the ledger register (precision, hairlines, 4px radii); the sandbox state borrows the brand
register's warm accent to mark what is yours.

### 4.0 The frame

Desktop (>= 1100px): a fixed-height workspace, `calc(100vh - var(--nav-h))`, panels scrolling
internally, no page scroll. Grid:

```
[ status strip                                                          ]
[ rail 268px ][ centre 1fr                          ][ ticket 380px      ]
[ tape                                                                  ]
```

Tablet (760-1099px): rail and ticket stack under the centre, page scrolls. Mobile (< 760px):
four tabs - **Book**, **Claims**, **Ticket**, **Tape** - with the chart at the top of the
Ticket tab; a floating **New claim** button.

`<title>`: `The desk - trdrbot`. No `PageHeader`; the strip is the header.

### 4.1 Status strip

One line, mono, four groups separated by hairlines:

```
● market open · ET clock, holidays unknown        (or ○ market closed)
last tick 20:55 UTC · open cadence · updated 12m ago
equity $116,170 (+16.2%) · SCALE · book 21% of 35% cap
Theo: holding 3 · last decided tick 854, declined       [elf-thinking 32px]
```

- Market state is computed client-side from the ET clock (weekday, 09:30-16:00 ET) and
  labelled as such; beside it, in `.fine`, the last tick's *observed* state from the record
  (`market.last_tick_open`, section 9.6): `last tick saw it open`. When the two disagree the
  strip shows both without resolving them.
- `frozen: true` (siteConfig) replaces the first two groups with `competition run complete ·
  record final as of {date}` and greys the dot; every "N ago" and "watching" phrase on the
  page has the same branch.
- The elf is `elf-thinking.jpg` when the last outcome was declined, `elf-confident.jpg` when
  traded, `elf-analysing.jpg` when an error.

### 4.2 The rail: Book

Label `BOOK (3)`. One row per open position, selectable:

```
SPY  reverse iron condor      +7.1%   ●●○   exp 11 Sep
NVDA bull call spread        −17.5%   ●●○   exp 11 Sep
PLTR bear put spread          +4.8%   ●●●   exp 11 Sep
```

The three dots are the position's **armed rules**: one dot per `exit_state` key, filled when
that rule's last check breached, hollow otherwise, danger-toned when 2 of 3 have breached
(the engine's own `NEEDED = 2`). P&L is `last_pnl_pct` through `pct()` with a `.fine` `marked
{HH:MM}` from the new `marked_at` field. Empty state: `Flat. Theo is holding cash.` with the
thinking elf at 96px.

Selecting a position opens **Position** in the ticket (4.6) and draws its payoff in the
centre with the entry spot marked and the claimed band shaded.

### 4.3 The rail: Claims

Label `CLAIMS · open (62) · resolved (141)`, two chip filters. Rows sorted by horizon, nearest
first:

```
SPY   range 762–782   55%   resolves tomorrow    declined
NVDA  bull 232–245    62%   in 8 days            traded
XLE   floor 64        57%   resolves tomorrow    declined
```

`kind` shows as a pill: `thesis`, `muse` (warm), `standalone`. Rejected-by-a-gate rows carry
`.pill.rejected`. Resolved rows show `held` / `failed` in place of the countdown. `in N days`
is `daysUntil(horizon, generatedAt)` from `demo.js` - never the browser clock.

Selecting a claim opens **Claim** in the ticket (4.6) and draws its chart.

### 4.4 The rail: Yours

Label `YOURS (n)`, present only after the visitor has recorded at least one claim. Rows as
4.3 with a warm left border. Header line: `Recorded in this browser only. Theo is the only
one who trades.` Below the rows, **Your scorecard** (section 5.6).

### 4.5 The centre

Three stacked cards, each with its provenance tag in the header:

1. **The chart** - `PriceBand` from notes/028, extended: the band is draggable in sandbox
   mode (two horizontal handles; keyboard: arrow keys nudge the focused handle by 0.25% of
   spot, shift-arrow by 1%), the horizon is a dashed vertical, spot is marked, and a resolved
   claim shows its dot with `held` / `failed` text. Tag: `Fact - the tape` for the closes,
   with `as of {as_of} · {age} days old` when the ticker file is older than a day.
2. **Structures priced for this claim** - `CandidateTable` from notes/028 (name, entry, max
   profit, max loss, P(profit | claim holds), P(profit | claim fails), edge, fate), survivors
   in ink, rejected faint with the fate string verbatim, the chosen one tagged. In record mode
   the rows are the recorded candidate block; in sandbox mode they are computed (section 5.3).
   Tag: `Fact - the record` or `Modelled - synthetic chain, lognormal drift 0`.
3. **Payoff against the claim** - `PayoffChart` with `band`, for the selected structure. Tag:
   `Fact - contract arithmetic. The shaded band is the claim.`

Empty centre (nothing selected): the latest open claim is selected by default, so this state
only occurs with an empty ledger; then `Nothing on the record yet.`

### 4.6 The ticket (record mode)

The right column. Header `TICKET · Theo's record`, tag `Fact - the record`. Contents depend
on what is selected.

**Claim selected:**

```
NVDA · thesis · tick 832 · 3 Sep 18:04
"From $183.22, PLTR will retrace into $168.50-$178.60 by ..."      (the claim, verbatim)
band 168.5–178.6 · resolves 11 Sep · stated: not stated (0.5 assumed by code)
shape  ▸ BEAR TARGET                                   (derived from band vs spot)
structures  2 priced · 2 survived · chosen: PLTR 182.5/170 bear put spread
size   28 contracts · 8.6% of equity · bound by Kelly · payoff 2.07 (conditional)
did    TRADED → position PLTR bear put spread   [open the position]
scored resolves in 8 days                        [replay this decision →]
```

- For a `standalone` decline, the `did` line reads `DECLINED · recorded the claim anyway`
  and the agent's own `notes` sentence appears in a `.quote` with `cite` `Theo's reason`.
- For a `muse` claim, `notes` is the collision trace, rendered in `details.expand` (`show the
  collision`), and the fate (`EMITTED`, `candidate, not emitted (rank)`, or the rejection).
- For a gate-rejected claim, the rejection string in a `.tag.warn` and `scored anyway: it
  still resolves` (D-080's point).
- `[replay this decision →]` links to `/demo#cycle-{cycle_id}` when the claim has one.
- Lines whose value is not on the record read `not recorded` (a claim with no candidate
  block: `structures  not itemised on the record before 3 Sep 2026`).

**Position selected:**

```
PLTR bear put spread · open · marked 20:55 · +4.8% of net entry cost
legs   long  1 P 182.5  ·  short 1 P 170   ·  exp 11 Sep         (Fact - the record)
entry  spot 183.22 · IV 45.9% · max loss $9,940 · Δ$ −8,201 · θ$ −171
rules  (armed - watching)                                        (Fact - the record)
  stop loss       position mark below −50%      ○ ○ ○
  profit target   position mark above +50%      ○ ○ ○
  time stop       0 days before expiry          ○ ○ ○
  underlying      PLTR above 187.50             ○ ○ ○
  leg divergence  2 consecutive                 ○ ○ ○   (implicit)
claim  "PLTR will retrace into ..." · resolves 11 Sep · [open the claim]
attribution  fires once the horizon has passed
```

Rules are read from `exit_state` keys (what the engine is actually watching), rendered per
signal type: `position_mark` thresholds as percent, `underlying` as a price, `days_to_expiry`
as days, `leg_divergence` as a count; the dots are the debounce triple oldest to newest. A
row whose signal is `frozen_when_closed` shows `not counting while closed` in `.fine` when
the market is closed. Corroboration is one line under a stop loss: `a loss must be
corroborated by the underlying before it fires`.

### 4.7 The tape

Full width, mono, newest first, six rows visible, scrolls. Each row: `HH:MM · {one-liner}`,
and a click target when the row names a claim, position, or cycle. The one-liners are
built in the exporter from fields (section 9.5), never from prose. No animation; a row that
is newer than the visitor's last visit (localStorage stamp) is bold. Label: `TAPE · the last
60 things that were not heartbeats`. Frozen: `TAPE · record final`.

### 4.8 Keyboard

`/` focus the ticker search (sandbox) · `n` new claim · `j` / `k` move the rail selection ·
`Enter` open · `Esc` back to record mode · `t` trade it · `d` decline · `?` this list. A
`<dialog>` lists them. Every shortcut has a visible control too.

## 5. The sandbox: your claim

### 5.1 Entering

**New claim** (rail footer, floating on mobile, `n`) switches the ticket to sandbox mode:
header `TICKET · your claim`, warm left border, and a banner that stays for the whole flow:

> Theo's arithmetic on your claim. Recorded in this browser only. Theo is the only one who
> trades.

### 5.2 The claim

1. **Ticker** - a search box over `universe[]` (112 symbols), each row showing `last`, `rv21`,
   and a freshness badge: `fresh` (<= 4 days, the codebase's own rule), or `{n} days old ·
   Theo would refetch before pricing`. Both are allowed; the badge stays on the chart. Picking
   a ticker fetches `/data/tickers/{T}.json` (section 9.8) and draws the chart.
2. **Band** - two inputs and two chart handles, either end blankable (a one-sided claim).
   Theo's gate: each bound within `[0.3 x spot, 3.0 x spot]`, else `rejected: band is not a
   plausible price (spot {spot:.2f})`.
3. **Horizon** - a date input, default `preferred` from `forecast_window` (today + 3), bounds
   `earliest`..`latest` (today + 1 .. today + 10, ET date). Outside: `rejected: horizon
   {date} outside 1-10 days`.
4. **Probability** - a slider 5-95%, default 55%, with `stated` above it. (The gate's
   lottery/vacuous tests are on the *base* rate, section 5.3; the stated number feeds sizing.)

Beneath the inputs, live: `shape ▸ RANGE` (or bull target, bear target, bull floor, bear
ceiling) from `shape_of(band_low, band_high, spot)`, with `direction disagrees with the
shape` shown only if a direction field is ever added (it is not, today).

### 5.3 The gates

A checklist that fills as the inputs do, each line Theo's exact string on failure:

```
✓ usable price history          300 sessions, fresh
✓ falsifiable                   a band exists
✓ plausible band                within 0.3x–3x spot
✓ horizon                       in 1–10 days
✓ base probability 31%          neither a lottery ticket nor vacuous     Modelled - bootstrap quantiles
· tradeable chain               not checked - no chain here
```

- Base probability is the fraction of Theo's own bootstrap terminal factors landing in the
  band (`bootstrap_factors`, 2,000 paths, seeded, band-inflated per horizon), read from 401
  quantiles shipped per ticker per horizon (section 9.8). Exact to about a quarter of a
  percent; labelled. `< 10%` → `rejected: base probability {b:.0%} - a lottery ticket`;
  `> 90%` and `|stated - base| < 0.25` → `rejected: base {b:.0%} and the model agrees -
  vacuous, carries no information`.
- The chain gate is shown as `not checked` - the desk has no chain and says so. It never
  shows a tick it did not earn.

A failed gate greys the structures and the size, disables both buttons, and shows `Theo
would not register this claim.` This is the teaching moment; it is not softened.

### 5.4 The structures (modelled chain)

With every gate green, the desk instantiates the **incumbent playbook catalogue** (shipped
parsed, section 9.7) for the derived shape, exactly as `playbook.resolve_legs` would, on a
modelled board:

| Input | Production | Sandbox | Label |
|---|---|---|---|
| IV | chain ATM IV | 21-session realised vol from the closes (Theo's own fallback, `iv_source: realized`); an override slider 5-200% | `Modelled - realised vol as IV` |
| expiry | first listed expiry >= horizon | first Friday >= horizon | `Modelled - weekly listing assumed` |
| days | expiry - ET today | same | - |
| sigma | `expected_move(spot, iv, days)` | same function, ported | - |
| strikes | anchor + sigma offset, snapped to the chain | anchor + sigma offset, **unsnapped**, shown to 2dp | `Modelled - strikes are not a listing` |
| leg premium | chain mid | fair value at r = 0 on the same drift-0 lognormal grid that scores the structure: `sum(w x intrinsic(leg, S))` | `Modelled - priced on the scoring grid; real quotes carry skew and spread` |
| friction | `sum((ask - bid) x qty x 100)`, half charged | `DEFAULT_ROUND_TRIP_COST (0.10) x gross premium`, half charged - the house constant `experiments.simulate` already uses when no spreads are known | `Modelled - 10% round trip` |

Then `evaluate` (ported): `net`, `max_profit`, `max_loss`, `entry_friction`, and when bounded
and reachable `p_band`, `e_hold`, `p_hold`, `p_fail`, `edge`, with the fate string built by
the same rules and the same thresholds (`MIN_BAND_EDGE = 0.25`, `e_hold > 0`). The table is
`CandidateTable`, survivors first, `MENU_MAX` is not applied (a person may see all nine).
The payoff card draws the selected one with the band shaded.

Why fair value on the scoring grid and not Black-Scholes: the codebase has no BS pricer and
D-093/D-077 are explicit that no second measure is invented; pricing the legs on the same
distribution that scores them keeps the sandbox internally consistent and reproducible in
JS from one ported function. The one script that ever needed a synthetic premium used the
bootstrap expectation of intrinsic; the lognormal expectation is the same idea on the grid
the page already has. Both are models and the page says so.

### 5.5 The size

Selecting a structure computes the **size waterfall** with the live `sizing_inputs`
(section 9.6) - equity, calibration (`n`, `reliability`), competence (`kelly_multiplier`,
`seed_fraction`, `position_cap`, `book_cap`, `underlying_cap`), the book's open risk and
per-name open risk. Rendered as a vertical stack, every row a real step of `size_position`,
the binding row lit with an accent left border:

```
stated              62%
calibration-adjusted 56%      n=77, reliability unmeasured → halve the claimed edge
payoff (conditional) 2.07     E[win|win] / E[loss|loss], friction on both sides
full Kelly           0.35     p − (1−p)/b
× tier multiplier    0.29     SCALE, appetite 1.75 → 0.10
exploration floor    0.0525   ← the floor wins                          ● binding
position ceiling     0.175
risk budget          $6,099   equity × 5.25%
per contract         $359.50
contracts            16
portfolio headroom   $19,127 left of $40,660 cap · not binding
PLTR concentration   $22,590 left of $32,528 cap · not binding
→ 16 contracts · 5.0% of equity · bound by exploration floor
```

The `NO POSITION` branch (stated-probability Kelly <= 0) renders Theo's own sentence and
disables **Trade it** but not **Decline, record the claim**. The indivisibility and cap
refusals render their exact strings. `payoff_ratio` is computed by the ported
`payoff_ratio` on the drift-0 grid with the modelled friction, so the size is what Theo's
sizer would say given these modelled inputs - and the header says `Fact - Theo's sizing
arithmetic · Modelled inputs`.

### 5.6 Recording, resolution, and your scorecard

**Trade it** / **Decline, record the claim** both write one object to `localStorage`
(`trdrbot-desk-claims`, versioned):

```json
{"v": 1, "id": "you_20260903T210000Z_a1b2", "created": "...", "underlying": "SPY",
 "band_low": 762, "band_high": 782, "horizon": "2026-09-08", "stated": 0.55,
 "shape": "range", "structure": "SPY 765/760/780/785 iron condor" | null,
 "contracts": 16 | null, "binding": "exploration floor" | null,
 "action": "traded" | "declined", "iv_used": 0.11, "iv_source": "realized",
 "outcome": null, "price_at_horizon": null, "resolved_at": null}
```

Dedupe as the ledger does: same ticker, horizon, and band → the existing row takes the new
probability rather than a second row. A confirmation line: `Recorded. Resolves {date}. Come
back and it will be scored.` The claim appears under YOURS.

**Resolution** runs on every load: for each stored claim whose horizon session has ended
(`session_closed_on`, ported: ET date after the horizon, or the horizon date after 16:00 ET),
fetch the ticker file and take the close on the horizon date, or the first session after it
that exists; `held = band_holds(close, low, high)`. No close yet → `awaiting a close for
{date}`. The frozen site stops advancing closes, and the copy says so: `the record is final;
closes after {as_of} are not on it`.

**Your scorecard** (rail footer): `n resolved · held h · Brier {num3}` over stated
probabilities, and under it, verbatim, the same humility Theo applies to itself:
`{n} forecast(s). Below 15 this says nothing yet - Theo does not trust its own number until
then either.` No reliability, no resolution: the decomposition needs bins this sample cannot
fill.

Storage unavailable (private mode) → the flow works in memory and the banner adds `won't
persist in this browser`.

## 6. Non-negotiable rules (each traces to a measured incident or a standing decision)

1. **Record and sandbox never mix.** Theo's claims and yours live in different rails with
   different accents; a sandbox number never appears in a record panel; the tape never carries
   your claims. (The `/data` page's promise, applied to a page with two authors.)
2. **Theo is the only one who trades.** The sandbox records to this browser and says so at
   every step; no button ever reads `Place order`.
3. **Three tags, on every panel.** `Fact - the record`, `Fact - contract arithmetic`,
   `Modelled - <assumption>`. A model without its assumption named is a bug.
4. **Parity or no port.** Every ported function in section 10 has fixture cases regenerated
   by Python and executed by Node; both test suites run in CI; a mismatch fails the build. The
   four names D-099 killed stay dead in the risk explorer (the existing assertion), and the
   desk's port uses different names.
5. **Static stays static.** The only runtime requests are `/data/tickers/{T}.json` and
   `/data/desk/parity.json` is never fetched by the page (tests only).
6. **Every live affordance has a frozen branch.** Dots, `N ago`, `watching`, `resolves in`
   - all read the record's own date when `frozen`.
7. **No autoplay, no fake motion.** The tape does not scroll itself; the only animation is the
   existing `pulse` on a real open state and the notes/028 `rise` on selection change, both
   under reduced-motion.
8. **Never reconstruct.** A real claim with no candidate block says so; a position with no
   mark says `not marked`; a ticker without `dates` shows closes without a date axis and says
   `dates not on record`.
9. **Three clocks, shown as three.** Position marks (`marked_at`), account strip
   (`account.as_of`), snapshot (`generated_at`). Section 2 measured 58 minutes between the
   first two.
10. **Budget.** The desk's inlined data <= 300 KB; a ticker file <= 40 KB; the client bundle
    still contains no snapshot text (notes/028 commit 1's check, re-run).
11. **Theo's strings, not ours.** Gate refusals, fates, the sizer's `NO POSITION` and
    `REFUSED` sentences, `binding` labels - copied from Python via the fixtures, never
    paraphrased.

## 7. Alternatives considered and rejected

| Alternative | Why it lost |
|---|---|
| A live backend (FastAPI, WebSocket quotes) | The site is static by design; a demo whose backend is down at judging is worse than a static one; the loop already publishes every tick |
| A chain-first interface (strikes x expiries grid, strategy builder) | The conventional layout Theo deliberately inverts; offering it as the primary surface would say the opposite of the thesis. The legs a structure uses are shown; a chain is not |
| A standalone HTML document like the risk explorer | Same as notes/028: it would fork `format.js`, the pills and charts, and the snapshot slicing - the drift notes/027 removed. A Svelte route shares all of it |
| Precompute a dimensionless response surface per shape (D-099's pattern) | Not exact - the band's z-position depends on `sig = iv x sqrt(t)` as a second axis (section 2); exactness costs megabytes and still quantises the band. D-099's pattern is right when the domain is a small grid (four tiers x fifteen appetites); a visitor's claim is not |
| Port the bootstrap RNG (MT19937 + Python string seeding + `_randbelow`) for exact base rates | Hundreds of lines to reproduce a resampling whose only consumer is a 10%/90% gate; 401 quantiles per horizon give the same answer to a quarter of a percent and are labelled |
| A Black-Scholes pricer for synthetic legs | A new model with no Python counterpart to pin it to; the scoring grid already exists in the port and prices the leg on the same distribution that scores it |
| Ship the whole returns corpus inside the snapshot (216 KB) | Would ride into every page that imports the snapshot server-side and into the desk's own HTML; per-ticker files load only what is used |
| Replace `/demo` with the desk | Different jobs: the replay is the narrative, the desk is the instrument. The ticket links to the replay per decision |
| Let a failed gate be overridden (`record anyway`) | Theo's gate would not register the claim; the sandbox saying yes where Theo says no is the one lie the page must never tell |
| Real-time market clock from Alpaca | No broker on a static page; the ET clock with `holidays unknown` is exactly what the Python does outside `get_clock` |

## 8. Scenarios simulated

| Scenario | What the visitor sees | Required handling |
|---|---|---|
| Judge, desktop, two minutes | The frame with three open positions and their armed rules, 62 claims sorted by tomorrow first, the tape, the latest claim already in the ticket | Default selection = the nearest-horizon open claim; nothing to click before the story starts |
| Judge presses **New claim**, picks SPY, drags a range, states 60%, picks Monday | Shape RANGE; five gates green; iron condor, iron fly, call fly priced; condor edge +0.71 candidate; size 16 bound by the exploration floor; **Decline** → recorded, `resolves Mon` | Sections 5.2-5.6 |
| The same judge returns Tuesday | YOURS shows `held ✓ · close 771.20`; scorecard `1 resolved · Brier 0.16 · below 15 this says nothing yet` | Resolution on load; humility copy |
| A claim Theo's gate refuses (band at 5x spot) | `rejected: band is not a plausible price (spot 771.20)`; structures greyed; buttons disabled; `Theo would not register this claim.` | 5.3 |
| A stale ticker (WMT, 7 days old) | Allowed, with `7 days old · Theo would refetch before pricing` on the chart and in the gate line | 5.2 |
| A one-sided claim (`above 760`) | Shape BULL FLOOR; band shades to the chart edge; `bull_call_debit` and `bull_put_credit` priced | Anchors that need `band_high` return Theo's `anchor band_high does not exist for this band` |
| A claim whose structures were never itemised (pre 3 Sep) | Ticket: `structures  not itemised on the record before 3 Sep 2026` | Never reconstructed from the blog table |
| Market closed, weekend | Strip `○ market closed · ET clock, holidays unknown`; rule rows `not counting while closed`; sandbox works (closes are daily) | 4.1, 4.6 |
| Loop frozen after the competition | Strip `record final as of`; no `N ago`; YOURS resolution stops at the last close on record and says so | Rule 6 |
| Zero open positions | `Flat. Theo is holding cash.` | 4.2 |
| Mobile, 375px | Four tabs; chart at the top of Ticket; floating New claim; drag handles have 44px targets | 4.0 |
| Keyboard only / screen reader | Every panel is a `section` with a heading; rails are listboxes; the ticket is a form; shortcuts are duplicated by controls; charts have `role="img"` labels | 4.8 |
| Deep link `?claim=jrn_...` shared in the submission | Opens with that claim in the ticket; unknown id → default | 11.6 |
| Private browsing | Sandbox works in memory; banner says it will not persist | 5.6 |
| Python changes `MIN_BAND_EDGE` | `agent/tests` regenerates the fixture and fails until committed; `npm test` fails until the port follows; CI blocks both | Section 10 |
| Snapshot grows for a month | `claims[]` ~+30/day → ~150 KB in a month; the tape is capped at 60; budget check in the export log | 9.9 |

## 9. The data contract

All new keys are written by `site_export.export()`, pass through the redaction scan (it walks
every string), and are excluded from the monotonicity guard. `cycles[]`'s embedded candidate
blocks move to a top-level `candidates` map and are referenced by `ref` (a notes/028
divergence, recorded in its BUILT table when this ships).

### 9.1 `positions[]` - two fields added

`marked_at` (the page's `generated.at`, ISO) and `exit_watch` - the parsed `exit_state`:

```json
"exit_watch": [
  {"key": "position_mark:below:-0.5", "signal": "position_mark", "direction": "below",
   "threshold": -0.5, "label": "stop loss", "history": [false, false, false],
   "frozen_when_closed": true, "implicit": false, "corroborated": true}
]
```

`label` maps back from the signal and direction to the rule type name the agent wrote
(`stop_loss`, `profit_target`, `time_stop`, `underlying_stop`, `leg_divergence`,
`deadline`) using `exit_rules._normalise`'s table in reverse; `implicit` is true for the
engine-added rules; `corroborated` is true for `position_mark:below`.

### 9.2 `claims[]` - every ledger row

```json
{"id": "jrn_..._fc...", "kind": "standalone", "created": "...", "underlying": "XLE",
 "claim": "...", "probability": 0.57, "probability_stated": true, "horizon": "2026-09-04",
 "band_low": 64.0, "band_high": 66.5, "metric": "price_band", "traded": false,
 "position_id": null, "rejected_by": "", "outcome": null, "resolved_at": null,
 "price_at_horizon": null, "notes": "Oil above $90 and ...", "variant": "",
 "cycle_id": "jrn_..._dec..." | null, "candidates_ref": "jrn_..._str..." | null,
 "spot_at_claim": 64.83 | null}
```

`notes` is shipped whole for `standalone` and `thesis` (<= 400 chars), and truncated to 200
chars for `muse` with `notes_truncated: true`. `cycle_id` and `candidates_ref` reuse
`build_cycles`' joins (factored into a shared `_join_claims` so the two cannot disagree).
`spot_at_claim` is the underlying's close on the claim's creation date from the returns file,
or null; it is what `shape` is derived from on the page.

### 9.3 `candidates` - a map, deduplicated

`{ "<row id>": {"source": "structures_simulated" | "playbook", "underlying", "horizon",
"spot", "iv_pct", "days", "expiry", "band_low", "band_high", "rows": [...as notes/028...]} }`.
`cycles[].think.candidates[]` becomes a list of refs.

### 9.4 `market`

```json
{"last_tick_at": "2026-09-03T20:55:40Z", "last_tick_open": true,
 "open_interval_s": 300, "closed_interval_s": 1800, "derived_from": "learn_run gap",
 "run_git_sha": "3df5249...", "run_started": "..."}
```

`last_tick_open` is true when the gap between the last two `learn_run` rows is <= 10
minutes, false when >= 20, null when there is one row or the gap is in between.

### 9.5 `tape[]` - the last 60 rows that were not heartbeats

Whitelist and one-liners (built from fields only; `{}` are formatted values):

| kind | line | ref |
|---|---|---|
| `decision` | `tick {tick} · reasoned on {n} item(s) · {model}` | cycle |
| `no_op` | `tick {tick} · declined · {n} tool call(s), 0 orders` | cycle |
| `execution` | `tick {tick} · {n} tool calls · {positions_recorded} position(s) recorded, {len(orders_rejected)} rejected` | cycle |
| `fill` | `{UNDERLYING} {strategy} filled` | position |
| `reconciliation` | `{UNDERLYING}: {finding} on {len(legs)} leg(s)` | position |
| `exit` | `{UNDERLYING} closed on {close_reason}{" (retry)" if retry} · {explanation}` | position |
| `forecast_resolved` | `{UNDERLYING} {metric}: {held|failed} · stated {pct} · settled {price}` | claim |
| `attribution` | `{UNDERLYING}: {label}` | position |
| `interim_outcome` | `{UNDERLYING} marked at {pct} · interim signal` | position |
| `research` | `daily research: {len(universe)} tickers · {opportunities} opportunit(ies)` | - |
| `discovery` | `nominated {nominees joined} · {opportunities} opportunit(ies)` | - |
| `muse` | `{len(concepts)} concepts collided · {candidates} candidates, {emitted} emitted` | - |
| `playbook_run` | `{opportunities} opportunit(ies) · {proposed} proposed, {survived} survived` | - |
| `sizing` | `{UNDERLYING} sized to {contracts} · {binding}` / `{UNDERLYING} sizing refused` | - |
| `structures_simulated` | `{UNDERLYING}: {n} structures priced against the claim` | claim |
| `hunt` | `hunting: {reason}` | - |
| `coach_mutation` | `new {lever} variant {variant}` | - |
| `coach_experiment_opened` | `{lever}: {incumbent} vs {challenger}` | - |
| `degraded` | `{subsystem} degraded: {reason}` | - |
| `error` | `decide failed ({cause}): {error class}` | cycle |
| `research_universe_widened` | `research universe widened by {len(added)}` | - |

Each tape row: `{ts, kind, line, ref: {kind: "claim" | "position" | "cycle", id} | null}`.
Excluded: `exit_run`, `learn_run`, `attribution_run`, `interim_run`, `coach_run`,
`competence`, `book_risk`, `forecast_run`, `playbook_resolve_run`, `wiki_sweep`,
`inbox_expired`, `blog_entry`, `blog_outcome`, `learn_error`, `muse_parse_failure`,
`posture`, `reflection`, `playbook`, `discovery_nominees`, `research_rejected`, `decision`'s
siblings already covered by the outcome row when both exist in the window (keep the outcome).

### 9.6 `sizing_inputs`

Everything `size_position` reads, as of the latest `competence` row:

```json
{"equity": 116169.98, "as_of": "...",
 "calibration": {"n": 77, "reliability": null},
 "posture": {"tier": "scale", "uses_kelly": true, "kelly_multiplier": 0.2922,
             "seed_fraction": 0.0525, "position_cap": 0.175, "book_cap": 0.35,
             "underlying_cap": 0.28, "appetite": 1.75},
 "open_risk_usd": 21475.0,
 "open_risk_by_underlying": {"SPY": 5865.0, "NVDA": 5670.0, "PLTR": 9940.0}}
```

`open_risk_*` sum `max_loss_usd` over open positions, as `tick.py` computes them for the
tool. `underlying_cap` is `book_cap x UNDERLYING_SHARE_OF_BOOK`.

### 9.7 `catalogue`

The incumbent `playbook.catalogue` lever text parsed through `parse_catalogue` and emitted
as JSON: `{"version": 1, "fingerprint": "5a8b5667", "families": [{"name", "shapes": [],
"legs": [{"right", "side", "qty", "anchor", "sigma"}]}]}`. Also `catalogue_constants`:
`{"min_band_edge": 0.25, "entry_crossings": 0.5, "max_anchor_sigma": 2.5,
"default_round_trip_cost": 0.10}` - read from the modules, never retyped.

### 9.8 `universe[]` and `/data/tickers/{T}.json`

`universe[]` in the snapshot (one row per returns file):

```json
{"symbol": "SPY", "last": 771.20, "as_of": "2026-09-03", "age_days": 0, "sessions": 300,
 "usable": true, "rv21_pct": 9.4, "has_dossier": true, "has_dates": true}
```

Per-ticker files written by the exporter to `web/static/data/tickers/<T>.json` (the
directory is gitignored and rebuilt on every export, like `build/`):

```json
{"symbol": "SPY", "as_of": "2026-09-03", "age_days": 0, "dates": [...300] | null,
 "closes": [...300], "rv21_pct": 9.4, "rv5_pct": 8.1, "rsi14": 61.2,
 "sma20": "above", "sma50": "above", "ret_5d_pct": 1.2, "ret_21d_pct": 3.4,
 "bootstrap": {"1": [401 quantiles], "2": [...], ..., "10": [...]},
 "inflate": {"1": 1.1, ..., "10": 1.05}}
```

`bootstrap[d]` = sorted terminal factors from `bootstrap_factors(closes, d, seed=f"desk|{T}",
inflate=band_inflation(state, d))`, sampled at 401 evenly spaced quantiles. ~30 KB per file,
~3.4 MB for all 112, none on the critical path. `age_days` uses `_series_age_days`, the
codebase's own definition.

### 9.9 The desk's `+page.server.js` slice and budget

Returns: `positions` (without `story_html` and `payoff.points` beyond the kinks - a slim
projection built in the load), `claims`, `candidates`, `tape`, `market`, `catalogue`,
`catalogue_constants`, `sizing_inputs`, `universe`, `account`, `competence`, `book`,
`calibration`, `counts`, `coach` (summary only: `promotions_total`, `open_experiments`),
`generatedAt`. Budget: <= 300 KB inlined; the exporter prints `desk slice: {kb} KB` and the
build step checks `build/desk.html` against it.

## 10. The JavaScript port and its parity harness

### 10.1 What is ported, and what is not

`web/src/lib/desk/optmath.js`: `entryCost`, `intrinsic`, `pnlAt`, `criticalPoints`,
`maxProfitLoss`, `breakevens`, `lognormalGrid`, `bandHolds`, `bandConditional`,
`payoffRatio`, `expectedMove`, `yearFraction`, `fairValue` (the modelled premium: the
expectation of intrinsic on the drift-0 grid - NEW, labelled, but still fixture-tested
against a Python twin added to `site_export` for the purpose, so the two cannot drift).

`web/src/lib/desk/playbook.js`: `shapeOf`, `anchorValue`, `targetStrikes`, `instantiate`
(unsnapped), `evaluate`, `classify`, `fateString`.

`web/src/lib/desk/sizing.js`: `shrinkProbability`, `kellyFraction`, `sizePosition` (the
full ordered computation of section 4.4 of the math survey, returning
`{contracts, fraction, kellyFull, kellyUsed, adjusted, binding, reason, steps[]}` where
`steps[]` is the waterfall), `forecastWindow`, `sessionsIn`.

`web/src/lib/desk/gates.js`: `plausibleBand`, `horizonOk`, `baseProbability` (quantile
ECDF), `baseGate`, the exact refusal strings.

`web/src/lib/desk/clock.js`: `marketStateNow(now)` (ET, weekday, 09:30-16:00),
`sessionClosedOn(day, now)`, `firstFridayOnOrAfter(date)`.

`web/src/lib/desk/pyround.js`: `pyRound(x, d)` - half-to-even on exact binary ties,
`toFixed` otherwise (the two agree everywhere else, section 2); `pyFormat(spec, x)` for the
handful of formats the fate and sizing strings use (`+.2f`, `+,.0f`, `.0%`, `.1%`, `,`).

**Not ported:** `bootstrap_factors` (quantiles shipped), `band_inflation` (values shipped),
`compute_stats` (values shipped), `calibration.score` (values shipped), `competence.assess`
(the applied posture is shipped), anything that reads a chain.

### 10.2 The fixtures

`agent/src/trdrbot/desk_parity.py` builds `web/src/lib/desk/parity.json`:

```json
{"generated_from": "3df5249", "cases": {
  "pnl_at": [{"legs": [...], "spot": 100, "expect": -300.0}, ...],
  "max_profit_loss": [...], "breakevens": [...],
  "lognormal_grid": [{"spot", "iv", "days", "expect": {"n": 801, "first_price", "last_price", "sum_w": 1.0, "w_at_400"}}],
  "band_conditional": [{"legs", "spot", "iv", "days", "band_low", "band_high", "expect": {"p_band", "e_pnl_hold", "p_profit_hold", "p_profit_fail"} | null}],
  "payoff_ratio": [...], "fair_value": [...], "expected_move": [...],
  "shape_of": [...], "target_strikes": [...], "evaluate": [{"...", "expect": {"fate", "net", "max_profit", "max_loss", "e_hold", "edge", ...}}],
  "classify": [...],
  "shrink_probability": [...], "kelly_fraction": [...],
  "size_position": [{"inputs": {...}, "expect": {"contracts", "fraction_of_equity", "kelly_full", "kelly_used", "adjusted_probability", "binding", "reason"}}],
  "forecast_window": [...], "sessions_in": [...],
  "gates": [{"band_low", "band_high", "spot", "horizon", "today", "base", "stated", "expect": {"pass", "reason"}}],
  "pyround": [{"x": 0.125, "d": 2, "expect": 0.12}, {"x": 2.675, "d": 2, "expect": 2.67}, ...]
}}
```

Cases are chosen to hit every branch: the zoo from notes/026 section 5 (spot 100, 7d, 25%
vol) for the structures; every `binding` label and both refusals for sizing; every gate
refusal; the exact-tie rounding cases. Values are stored unrounded (Python `repr`), and the
fate strings are stored as formatted by Python.

### 10.3 The two-sided pin

- `agent/tests/test_desk_parity.py`: regenerates the fixture in memory and asserts it equals
  the committed file byte for byte. A Python change to any ported function fails here until
  `uv run trdrbot desk parity --write` (the CLI verb the module gains) is run and the file
  committed.
- `web/scripts/desk.parity.test.mjs`: loads the fixture and runs every case through the JS
  port. Numbers within `1e-9` relative (probabilities, dollars), strings exact. Committing a
  regenerated fixture without updating the port fails here.
- `.github/workflows/web-tests.yml` (new): `npm ci && npm test && npm run build` on push and
  PR, plus the notes/028 check that no built client chunk contains `start_note`.
- The existing D-099 assertion (`shrinkProbability`, `kellyFraction`, `postureFor`,
  `sizePosition` absent from the risk explorer) stays. The desk's names differ
  (`shrinkProbability` → `shrink`, `sizePosition` → `size`) so the assertion keeps its
  meaning; a new assertion pins that `web/src/lib/desk/*.js` never imports the snapshot.

### 10.4 Operand order and clocks

`pnlAt` sums `sign * perShare * qty * 100` in that order (the Python golden test pins the last
ulp). `yearFraction(days) = max(days, 0) / 365`, calendar. `lognormalGrid` uses `n = 801,
width = 5`, densities normalised by their own sum. `pnl === 0` is a loss in `payoffRatio`
and not a win anywhere. `sessionsIn` uses `pyRound(days * 252 / 365, 0)`.

## 11. Module-by-module specification

### 11.1 `agent/src/trdrbot/site_export.py`

- `export_position`: add `marked_at` (frontmatter `generated.at`, read through a new
  `Position.marked_at` field that `PositionStore._parse` now keeps) and `exit_watch`
  (`build_exit_watch(pos)`, using `exit_rules._normalise` and the signal registry for
  `frozen_when_closed` / corroboration).
- `_join_claims(journal_rows, theses, positions_by_id)` factored out of `build_cycles` and
  reused by `build_claims`; `build_candidates_map`; `cycles[]` reference candidates by ref.
- `build_tape(journal_rows, positions_by_id, claims_by_id, cap=60)` with a `TAPE_LINES`
  table of pure formatters, one per kind, each a plain function of the row.
- `build_market(journal_rows, state_dir)`: the `learn_run` gap rule plus `run.json`.
- `build_sizing_inputs(latest_competence, cal, positions)`.
- `build_catalogue(cfg)`: `coach.load_state(cfg, "playbook.catalogue", SEED_CATALOGUE)` →
  `parse_catalogue` → dicts; constants read from `playbook` and `experiments`.
- `build_universe(state_dir)` and `write_ticker_files(state_dir, out_dir)`: per file,
  `load_dated_closes` (max age unbounded here - the desk labels staleness rather than
  refusing), `compute_stats`, `bootstrap_factors` for d = 1..10 with `band_inflation`,
  401 quantiles via `statistics.quantiles(factors, n=400)` plus min and max.
- `fair_value(legs, spot, iv, days)`: the Python twin of the modelled premium (an expectation
  of intrinsic on `_lognormal_grid`), used only by the fixture generator - it lives here, not
  in `optmath`, so nothing in the trading path can mistake it for a quote.
- The export log gains `desk: {n} claims, {n} tape rows, {n} tickers ({kb} KB), slice {kb} KB`.

### 11.2 `agent/src/trdrbot/desk_parity.py` and `cli.py`

`build_fixture() -> dict`, `main(["--write"])`. `trdrbot desk parity [--write]` - without
`--write` it diffs and exits non-zero on drift (what CI's Python job runs, via the test).

### 11.3 `agent/src/trdrbot/positions.py`

`Position.marked_at: str = ""`, parsed from `generated.at`, written as before. One field.

### 11.4 `web/.gitignore`, `web/scripts/sync-static.mjs`

`static/data/tickers/` gitignored. `sync-static` untouched (the exporter writes the files
directly; they are build inputs like `snapshot.json`).

### 11.5 `web/src/lib/desk/*.js` (section 10) and `web/src/lib/desk/store.js`

`store.js`: `loadYours()`, `saveYours()`, `recordClaim()`, `dedupeKey()`, `resolveYours(claims,
tickerFiles)`, `brier(resolved)`, a `v` migration hook, and a try/catch around every storage
access (the artifact rules' localStorage discipline, applied to a static site).

### 11.6 `web/src/routes/desk/+page.server.js` and `+page.svelte`

- `+page.server.js`: the slice of 9.9, with the slim position projection.
- `+page.svelte`: the frame; state `selection = {kind: 'claim' | 'position' | 'yours' |
  'new', id}` mirrored to `?claim=` / `?position=` via `history.replaceState` and read once
  on hydration; `mode = 'record' | 'sandbox'`; the sandbox draft object; a `$effect` that
  fetches a ticker file on ticker change and caches it in a `Map`; keyboard handling on the
  frame (ignored inside inputs); the `<dialog>` for `?`; mobile tab state in
  `localStorage['trdrbot-desk-tab']`.

Components, all in `web/src/lib/components/desk/`:

| Component | Job |
|---|---|
| `StatusStrip.svelte` | 4.1, with the frozen branch and the two market readings |
| `BookRail.svelte` | 4.2; `ArmedDots.svelte` for the triple |
| `ClaimsRail.svelte` | 4.3 with the open/resolved chips and the sort |
| `YoursRail.svelte` | 4.4 and `Scorecard.svelte` |
| `DeskChart.svelte` | `PriceBand` plus drag handles (pointer events, 44px targets, keyboard nudging, `aria-valuenow`) |
| `Ticket.svelte` | the record/sandbox switch; `TicketClaim.svelte`, `TicketPosition.svelte`, `TicketSandbox.svelte` |
| `ExitRules.svelte` | 4.6's rules table from `exit_watch` |
| `Gates.svelte` | 5.3 |
| `SizeWaterfall.svelte` | 5.5 |
| `TickerSearch.svelte` | 5.2's combobox (`role="combobox"`, arrow keys, freshness badge) |
| `Tape.svelte` | 4.7 |
| `Shortcuts.svelte` | 4.8's dialog |

Reused unchanged: `CandidateTable`, `PayoffChart`, `PriceBand` (extended, not forked),
`StatusPill`, `Callout`, `Icon`, `Term`.

### 11.7 CSS (`web/src/app.css` only)

`.desk` (the grid, the three breakpoints, internal scrolling panels), `.desk-panel` with
`.desk-panel-head` (label + provenance tag), `.strip`, `.rail-row` with `[aria-selected]`,
`.armed-dots`, `.ticket` and `.ticket.yours` (warm border), `.gates` rows with `.pass` /
`.fail` / `.unchecked`, `.waterfall` rows with `.binding`, `.tape-row` with `.new`,
`.handle` for the chart, `.desk-tabs` for mobile. Tokens only; no new colours.

### 11.8 Entry points and the nav

- **Nav** (the user's explicit ask): `Desk` becomes the FIRST link. To keep the desktop bar at
  seven links (measured crowding at 760-900px, notes/028), `Demo` is relabelled `Replay`, and
  `Resources` moves from the desktop bar to the mobile sheet's extra links and the footer,
  where it already lives. Final bar: Desk · Replay · Ledger · Scoreboard · How it works ·
  Build log · For judges. Mobile extras: Resources · Notes · Data · Glossary.
- **Hero**: primary `Open the desk` → `/desk`; ghost `Watch a replay` → `/demo`; ghost `For
  judges`. The ledger button leaves the hero (it stays in "Three ways in." below).
- **Judges page**: primary `Open the desk`, then `Watch a replay`, deck, repo.
- **How-it-works**: the "See it live" door points at `/desk`; the replay door stays.
- **Footer** Explore: Desk, Replay, Resources, Notes, Data, Glossary.
- **`/demo`**: each cycle's provenance line gains `open on the desk →` (`/desk?claim=` the
  primary thesis id).
- `resources.js`: no entry (the desk is a route, not a document).

### 11.9 Docs

- `web/CLAUDE.md`: a `## The desk` section: the three provenance tags, the record/sandbox
  split, the parity rule ("a ported function without a fixture case does not ship"), the
  ticker-file directory being generated, and the budget.
- `specs/decisions.md`: `D-124 - The Desk: a claim-first surface, and the arithmetic
  returns to JavaScript under a two-sided pin` - explicitly citing D-099 and what is
  different.
- `specs/issues.md`: section 15.
- This note gains the BUILT header and divergence table when done.

## 12. Edge cases and required handling

| Case | Handling |
|---|---|
| Ticker file 404 (a returns file removed between export and deploy) | `price history not on this build` in the chart; the sandbox refuses that ticker |
| Ticker file without `dates` (the 39 stale ones) | Closes drawn on an index axis, `dates not on record`; horizon resolution for YOURS is impossible for that ticker and the record says `cannot resolve: no dates on record` |
| `spot_at_claim` null for a real claim (no close on its creation date) | Shape line reads `shape not derivable - no close on record for {date}` |
| A position with `last_pnl_pct` null | `not marked`, dots still shown |
| `exit_state` empty on an open position (freshly opened) | `rules armed, no checks yet` |
| Band inputs inverted (low > high) | Swapped silently, as `_bands_from_pct` does; a `.fine` note `swapped` |
| Band bound outside `[0.3x, 3x]` | The gate's exact string; the handle clamps visually at the limit with the string shown |
| Horizon on a weekend | Allowed (the Python allows calendar days); the chart's horizon line sits on the next session; resolution uses the first session on or after |
| Stated probability at 5% or 95% | Allowed; `NO POSITION` shows itself if Kelly says so |
| Anchor missing for a one-sided band (e.g. `iron_condor` on a floor) | Theo's `rejected: anchor band_high does not exist for this band` row, faint |
| Two legs resolving to one strike (a tiny band) | `rejected: degenerate - legs collapsed to one strike` (the port keeps the check even unsnapped, on a 1e-9 tolerance) |
| `payoff_ratio` null (conditional mass under 1%) | Size shows Theo's `REFUSED: ... no usable conditional payoff` sentence |
| Equity null (account unreadable at export) | Sandbox size shows Theo's `REFUSED: the account could not be read` sentence, with `as of` the last good strip |
| `market.last_tick_open` null | Strip shows only the ET clock reading |
| Storage quota exceeded | Oldest resolved YOURS rows dropped first, with a note |
| Ticker search with no match | `no history on record for that symbol - Theo can only price what it has closes for` |
| Reduced motion | No `rise`, no pulse |
| `frozen` | Section 6 rule 6 |

## 13. Tests that must exist

Per `docs/principles_testing.md`: pillar tests on the seams. Fixtures under
`agent/tests/fixtures/desk/`.

**Python**

1. `test_exit_watch_reads_exit_state_not_exit_rules`: a position whose `exit_rules` lists a
   rule the engine could not parse and whose `exit_state` holds the implicit `leg_divergence`
   - the export shows what is watched, marks the implicit one, and renders thresholds per
   signal type.
2. `test_marked_at_round_trips`: `generated.at` survives `PositionStore` parse and export.
3. `test_claims_and_cycles_share_one_join`: the same fixture journal through `build_claims`
   and `build_cycles` yields identical `cycle_id` / `candidates_ref` per claim.
4. `test_tape_lines_are_pure`: golden strings for every whitelisted kind; heartbeats
   excluded; cap honoured; `ref` correct.
5. `test_market_from_learn_run_gap`: 5-minute gaps → open, 30 → closed, single row → null.
6. `test_sizing_inputs_match_the_tool`: `open_risk_*` equal what `tick.py` would hand
   `build_size_position` for the same positions.
7. `test_catalogue_round_trips`: exported JSON → YAML → `parse_catalogue` equals the incumbent.
8. `test_ticker_files_are_bounded_and_honest`: 401 quantiles per horizon, `age_days` by the
   codebase's rule, `has_dates` false for a file without dates, size <= 40 KB.
9. `test_desk_parity_fixture_is_current`: section 10.3.
10. `test_fair_value_is_the_grid_expectation`: the Python twin equals
    `expected_value` of a single long leg at zero premium.
11. The export test gains the `desk slice` log line and the 300 KB budget assertion.

**Node**

12. `desk.parity.test.mjs`: every fixture case, per section 10.3.
13. `desk.store.test.mjs`: dedupe key, migration from a missing `v`, resolution against a
    ticker file (horizon on a session, on a weekend, in the future, on a file without
    dates), Brier over stated only.
14. `desk.clock.test.mjs`: `marketStateNow` at 09:29 / 09:30 / 16:00 ET on a Wednesday and a
    Sunday; `sessionClosedOn`; `firstFridayOnOrAfter`.
15. `desk.gates.test.mjs`: each refusal string byte-identical to the fixture.

**Build**

16. `build/desk.html` under 300 KB; no client chunk contains `start_note`; the web CI job
    runs all of it.

## 14. Rollout, commit by commit

Each commit: `cd agent && uv run pytest`, `uvx ruff check .`, `cd web && npm test && npm run
build`, exit codes captured; restart the loop after commits touching `agent/src` (1 and 2).

1. **The record learns what the desk needs** - `marked_at`, `exit_watch`, `claims[]`,
   `candidates` map (cycles by ref), `tape[]`, `market`, `sizing_inputs`, `catalogue`,
   `universe[]`, ticker files, the shared join, tests 1-8 and 11. Run the export for real;
   paste the log line into the commit.
2. **The port and its pin** - `desk_parity.py` + CLI verb, the fixture, `web/src/lib/desk/`,
   node tests 12-15, the web CI workflow, `fair_value`'s twin, tests 9-10 and 16.
3. **The desk, record mode** - frame, strip, rails, chart, structures, payoff, ticket (claim
   and position), exit rules, tape, keyboard, deep links, mobile tabs, CSS. Verify in the
   browser at 1280 and 375px, light and dark, with a traded claim, a declined claim, a
   position, and the frozen flag flipped locally.
4. **The desk, your claim** - sandbox mode, ticker search, drag handles, gates, modelled
   chain, waterfall, recording, YOURS, scorecard, resolution. Verify end to end in the
   browser including a returning visit with a hand-advanced ticker file.
5. **Entry points and docs** - nav, hero, judges, how-it-works, footer, the `/demo` link,
   `web/CLAUDE.md`, D-124, issues. Deploy with `./scripts/publish.sh --force`; verify
   `trdrbot.com/desk` by direct fetch and `?claim=` deep link.
6. **This note's BUILT header** with the divergence table.

## 15. Surfaced issues to fix in the same pass

- **`generated.at` is written on every position save and never read back** - the mark
  timestamp the whole book strip needs. Fixed in commit 1 (`Position.marked_at`).
- **`exit_run`'s `rules` comment says "+1 for the implicit deadline"** which no longer exists;
  the number is right, the comment is stale. Fix the comment in commit 1.
- **`posture` journal kind is dead** (one row, 27 Aug, no writer left). Note it in D-124;
  nothing reads it.
- **`docs/architecture_explorer.html` declares `font-family: "Libre Franklin"` and never
  loads it** (falls back to `system-ui`). One-line fix in commit 5: use the site's `--sans`.
- **`web/scripts/sync-static.mjs`'s banner colours are literals** and do not follow the
  page theme. Minor; log as an issue, do not fix here.
- **`npm test` is not in CI** (notes/027 and 028 added the tests; nothing runs them on push).
  Fixed in commit 2.
- **I-127** (the 2027 `metrics.jsonl` rows) is confirmed as five rows, not one; the issue's
  text is corrected in commit 5.

## 16. Deferred, deliberately

- **A real chain on the desk.** When the loop persists the chain it priced (a
  `chain_seen` row: expiry, strikes, mids, IVs for the strikes that mattered), the sandbox
  can snap to real listings and use real spreads for that ticker on that day, and the
  `Modelled - synthetic chain` tag can drop for those. Nothing on disk holds a chain today.
- **`playbook_outcome` on the ticket.** From 11 Sep the slow audit resolves proposals; the
  claim ticket gains `the playbook's own proposal for this claim resolved: won/lost`.
- **Your calibration, decomposed.** With 30+ resolved visitor claims the scorecard could run
  Theo's bias-corrected decomposition; the port of `calibration.score` waits for a visitor
  who gets there.
- **Sharing a sandbox claim by URL** (`/desk?you=<base64>`). Cheap, but it makes a
  visitor's claim look like a record link; do it only with a distinct path and the warm
  treatment.
- **A "what Theo would have said" replay** of a visitor's claim through the muse prompt -
  needs an LLM at runtime; out of the static site's reach by design.
