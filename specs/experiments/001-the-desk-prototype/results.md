# Experiment 001: Theo's Desk - a claim-first UI prototype

## Hypothesis

The claim-first inversion notes/029 designs - state a claim by drawing a band and a horizon
onto a chart, rather than opening a chain and building a spread - can be prototyped as a single
self-contained HTML page that (a) feels like a professional trading instrument rather than a
form, (b) prices structures and sizes a trade using a faithful port of trdrbot's real playbook
and sizer arithmetic, and (c) is genuinely fun to operate: dragging the claim visibly changes
what gets priced, what it costs, and how big it's allowed to be.

This is a design and interaction spike, not a benchmark - there is no pass/fail threshold,
only "does the core loop hold together and feel right."

## Method

`code/theos-desk.html` is a zero-dependency, single-file HTML/CSS/JS page (~1,470 lines) built
directly (no framework, no build step) and reviewed once in a real browser before publishing,
per the artifact-design skill's process. It embeds:

- trdrbot's real brand tokens (Fraunces / Public Sans / IBM Plex Mono, the sage-green ledger
  register, light and dark themes) - not invented, carried over from the live site.
- Five real tickers from trdrbot's live 4 Sep 2026 book (SPY, NVDA, PLTR, XLE, AVGO) with their
  real spot prices and IVs, each given a seeded synthetic 78-session history plus a hidden
  16-session future (mulberry32, string-seeded, so a given ticker's chart is identical on every
  reload - and its future is fixed the moment the page loads, so resolving a claim early is
  "revealing" a deterministic outcome, not rerolling one).
- A direct JS port of the functions notes/029 section 10 scopes for the real desk:
  `shapeOf`, the full nine-family `SEED_CATALOGUE` verbatim, `entryCost`/`intrinsic`/`pnlAt`/
  `maxProfitLoss`/`breakevens`/`lognormalGrid`/`bandConditional`/`payoffRatio`/`evaluate` (with
  the real `MIN_BAND_EDGE = 0.25` gate and the real rejection-string shapes), and
  `shrinkProbability`/`kellyFraction`/`sizePosition`'s full ordered waterfall (tier multiplier,
  exploration floor, position ceiling, portfolio and per-name concentration caps), all wired to
  trdrbot's actual applied posture on 4 Sep 2026 (tier SCALE, equity $116,169.98, calibration
  n=77/reliability unmeasured, the real per-name open risk on SPY/NVDA/PLTR).
- One deliberate simplification the plan itself calls out as the honest option where no chain
  exists: leg premiums are priced as the expectation of intrinsic value on the same drift-0
  lognormal grid that scores the structure ("Modelled - synthetic chain"), not a Black-Scholes
  quote - there is no BS pricer anywhere in the real codebase either.

The interaction: a single price chart splits at "today" into solid history (left) and a tinted
"claim" zone (right); two horizontal lines are dragged directly in that zone to set the band,
so drawing the claim IS the band input, not a pair of number fields beside a chart. A
semicircular dial (paired with a real `<input type="range">` for keyboard/screen-reader access)
sets the stated probability. Everything downstream - the shape badge, the gate checklist, the
priced structures, the payoff chart, the sizing waterfall, the ticket - recomputes on every
drag, live. Trading or declining stamps the ticket and records to `localStorage`; a
"fast-forward to horizon" button on each recorded claim reveals the pre-generated future close
and scores it, building a running Brier score exactly as trdrbot scores its own forecasts.

## Results

Built and reviewed once in Chrome (light and dark) before publishing. What worked as designed:

- The band-drag-as-claim interaction reads as a single continuous act, not a form: dragging
  toward or away from spot visibly flips the shape badge between RANGE / BULL TARGET /
  BEAR TARGET / BULL FLOOR / BEAR CEILING in real time.
- The structures panel genuinely differentiates families by shape - e.g. NVDA's default
  bull-target claim prices `bull_call_debit` and `bull_call_debit_on_band` as survivors with a
  real edge and fate string; a range claim on SPY prices `iron_condor` / `iron_butterfly` /
  `call_butterfly` instead, with real rejections (`indifferent to the thesis`, `unbounded loss`)
  when a claim genuinely doesn't support a structure.
- The sizing waterfall correctly lights different binding constraints depending on inputs
  observed in testing: `exploration floor` and `Kelly` both fire on different bands; the
  concentration caps are real numbers derived from the live open-risk figures.
- The resolve loop closes the story: recording a claim, fast-forwarding, and seeing `held` /
  `failed` against the ticker's own pre-generated future, with a running Brier score and the
  same "below 15 this says nothing yet" humility line trdrbot's real calibration copy uses.

One real defect was found and fixed in the single review pass, not assumed away: every em
dash, en dash, middle dot, arrow, multiplication sign, and the typographic minus sign rendered
as mojibake (no `<meta charset>` was guaranteed at the point the page was first inspected, and
the raw UTF-8 bytes were being misinterpreted). Fixed by removing em/en dashes entirely
(matching this project's own house style) and re-encoding every remaining special character as
an ASCII-safe escape - `\uXXXX` inside the script block, numeric character references outside
it - so the page no longer depends on any charset guess to render correctly. Verified with
`node --check` on the extracted script block and one final visual pass.

## Conclusion

**Confirmed.** The claim-first interaction holds together as a real, playable loop end to end,
and a faithful-enough port of the real Python arithmetic is small enough to write and read in
one file. The single biggest craft finding was interaction-design, not math: making the band
*itself* the input (rather than a form next to a chart) is what makes the page feel like an
instrument instead of a wizard, and it cost less code than a conventional form would have.

## Caveats

- **Not the production port.** This experiment has no parity fixtures and is not pinned to the
  Python source the way notes/029 section 10 requires before any of this logic could ship on
  `/desk` for real - it is closer to the same math with looser tolerances (a 161-point grid
  instead of 801, unsnapped synthetic strikes, a flat 10% friction assumption) and no CI.
  D-099's lesson stands: this code must never be presented as verified against Python.
- **Price history is entirely synthetic**, seeded per ticker for reproducibility, not live data
  - the page says so in its footer, but it bears repeating here.
- **No book/name-cap variety was exhaustively exercised** - the five seeded tickers and their
  default claims were enough to see every binding label at least once, not proof every branch
  of `sizePosition` is reachable and correct from the UI alone.

## Spec Impact

- Confirms notes/029's central design bet (claim-first, chart-as-input) is worth building for
  real, and confirms the "price the leg on the same grid that scores it" simplification
  (section 5.4) reads as coherent and honest in practice, not just on paper.
- The em-dash/mojibake failure mode is worth a note for the production build too: any
  standalone HTML surface trdrbot ships (this experiment, `docs/risk_appetite_explorer.html`,
  `docs/architecture_explorer.html`) should have an explicit `<meta charset="utf-8">` and,
  ideally, an ASCII-only source discipline for exactly this reason - not raised as a new issue
  against the real site since those two documents were spot-checked and do declare charset
  correctly, but worth carrying into any new one.
- No changes to notes/029 itself - this experiment is deliberately upstream of and looser than
  that plan, not a substitute for its parity harness.
