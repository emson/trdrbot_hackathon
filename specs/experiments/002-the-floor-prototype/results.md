# Experiment 002: Theo's Floor - an ambient, read-only dashboard prototype

## Hypothesis

`docs/research_dashboard_concepts.md` brainstormed three dashboard metaphors for watching
trdrbot's autonomous decide loop (a newsroom, a mission-control room, a live elimination
tournament) and cherry-picked a synthesis, "the Floor": a multi-panel, walk-up-and-glance
overview that sits one level above the existing `/demo` single-cycle replay, built from a
reinvented trading-terminal panel grammar (the wire, the gate ladder, the ticket, the book, the
Coach). The hypothesis: that synthesis can be prototyped as a single self-contained HTML page
that (a) reads as a real multi-panel instrument rather than a single article, (b) makes the
muse's alternative theses visibly compete and narrow to one, (c) keeps `held/failed` and
attribution as two separate marks everywhere a position appears (the one hard requirement the
research doc's scenario pass surfaced), and (d) never implies a control surface exists.

This is a design and interaction spike, not a benchmark - there is no pass/fail threshold, only
"does the panel grammar hold together and read as the ideas described."

## Method

`code/the-floor.html` is a zero-dependency, single-file HTML/CSS/JS page (~730 lines) built
directly (no framework, no build step), following the exact convention
`specs/experiments/001-the-desk-prototype/code/theos-desk.html` set: brand tokens, fonts, theme
system and several component classes (pills, gate rows, the ticket/stamp) are carried over
verbatim for continuity, since this page is explicitly a sibling of that one, not a replacement.

Unlike 001, this page does not port trdrbot's pricing math - it is a read-only monitor, not an
input surface, so there is nothing to price. Instead it holds one illustrative day of seven
decide cycles, hand-authored (not randomly generated) to exercise every scenario the research
doc's own battery named: a busy multi-candidate muse collision that trades, a muse collision
where nothing graduates, a discovery nomination that fails the gauntlet, a research thesis
blocked by the correlation cap ("scored anyway"), a position exit, a quiet positions-only
review, and an aborted cycle. Wherever the real project's own vocabulary was available it was
used verbatim rather than invented: tick 812's structure, edge, sizing and payoff points are the
worked example from `specs/notes/028_demo_page.md` section 8.1; every gate-rejection and
muse-fate string (`"rejected: base probability 7% - a lottery ticket"`,
`"rejected: indifferent to the thesis (edge +0.23)"`, `"no options chain inside the deadline"`)
is drawn from that spec or the real README; the muse's long-tail collision partners (SMCI, MU,
ASTS, OLLI, GIII, PATH, VRT) are real tickers already tracked in `agent/data/wiki/research/`.

## Results

Published and reviewed in the browser (Artifact preview, light theme) before finalizing, per
the artifact-design skill's process. Two real defects were found in that review and fixed, not
assumed away:

- **An HTML-entity double-escaping bug.** Several data fields (`bracket.round1[].name`, gate
  `detail`, ticket row values) intentionally embedded `&middot;`/`&times;` for their separator
  and multiplication marks, then were passed through the page's own `esc()` sanitizer before
  insertion - which escapes `&` to `&amp;`, turning `&times;` into literal on-screen text
  `&times;` instead of the "x" it was meant to render as. Fixed the same way 001's mojibake
  defect was fixed: not by loosening `esc()` (a real XSS-safety habit worth keeping even though
  this page has no untrusted input), but by moving every affected glyph out of the escaped data
  and into a `·`/`×` JS escape, matching the existing `−`/`✓`/`✗`
  pattern the file already used elsewhere. Verified by re-inspecting the rendered page: "SPY x
  XLE" and "0.31 x MIN_BAND_EDGE 0.25" (using the multiplication and middle-dot glyphs) render
  correctly.
- **A layout collision on the ticket stamp.** The `TRADED` stamp is absolutely positioned in the
  ticket card's top-right corner; the flagship cycle's claim text is long enough to wrap under
  it, and the wrapped line ran directly behind the stamp, obscuring a word. Fixed with
  `padding-right` on `.claim-text` sized to the stamp's footprint, with a narrow-viewport
  override that stacks the claim below the stamp instead.

What worked as designed, confirmed by stepping through the reel in the browser:

- Selecting a reel chip re-renders the wire highlight, the center stage (bracket, single-claim
  card, or exit summary depending on the cycle's `kind`), the gate ladder, and the ticket
  together from one piece of state - the same "one interaction model runs the whole page"
  discipline `/demo`'s own spec insists on.
- The two-round muse bracket (six concepts collide, two graduate, three structures are then
  priced for the graduate that traded) reads as an elimination, not a list - `GRADUATES` and
  `CHOSEN` badges pick out the survivors, rejected rows sit muted with their fate string
  attached, exactly answering the brief's "see the Muse create alternative theses and then see
  how the most appropriate ones get chosen."
- The declined-as-modal-outcome problem the research doc flagged as the hardest design question
  held up in practice: the quiet cycle (tick 811) renders as a calm, genre-appropriate "nothing
  to sense, nothing to think through" card rather than a broken-looking gap, and the muse-quiet
  cycle (tick 807) closes with "No entrant graduated this round" rather than an empty box.
- The book keeps `held`/`failed` and attribution strictly separate everywhere, including the one
  case the whole project's README calls "the important one" - the SPY tile shows `FAILED` (the
  claimed band broke) directly beside `learn nothing - this was luck` (the position still
  profited), with the mechanism spelled out rather than asserted.
- Zero control surface: there is no button anywhere that commits, cancels, or overrides
  anything - the only interactive elements are the reel, the wire items, and the theme toggle,
  all pure navigation.

## Conclusion

**Confirmed, with one open item.** The Floor's panel grammar and the specific ideas cherry-picked
into it in `docs/research_dashboard_concepts.md` section 6 hold together as a real page: the
bracket makes elimination legible, the gate ladder makes "why" the primary content rather than a
tooltip, and the ticket gives the eye one object to follow from Think to Act, matching the
"one interaction model" goal. The single biggest finding was the entity-escaping defect, which
is a small but real instance of the general lesson 001 already logged for this class of file
(ASCII-source discipline is not optional for a standalone page built outside the site's own
`format.js`) - this page now passes the same zero-raw-non-ASCII bar `theos-desk.html` does.

## Caveats

- **Not a data-contract implementation.** This is a design and interaction spike with hand-authored
  illustrative data, not wired to a real `snapshot.json` export - see
  `docs/research_dashboard_concepts.md` section 8 for what the real exporter would need (the
  muse bracket's eliminated-candidate claim text, specifically) before this could read live data.
- **Theme toggle unverified by automation.** The dark/light toggle button reuses
  `theos-desk.html`'s exact, previously-working theme code verbatim (same `themeInit`/
  `currentTheme`/click-handler pattern). Repeated automated clicks against the published Artifact
  preview did not visibly change the rendered theme, and the Artifact's cross-origin sandboxing
  blocked scripted inspection of the iframe's internal DOM state, so the automated test was
  inconclusive rather than a confirmed failure - it could not distinguish "the toggle doesn't
  fire" from "the automated click didn't land on the button inside the sandboxed frame." Worth a
  quick manual click-check before this page is treated as a template for anything further.
- **One day, seven cycles, hand-picked for coverage.** No claim is made that this is a typical
  day - it was assembled to hit every scenario the research doc's battery named at least once,
  the same way 001's five tickers were chosen for shape variety, not typicality.

## Spec Impact

- Confirms `docs/research_dashboard_concepts.md`'s synthesis (section 6, "the Floor") is worth
  building for real: the panel grammar, the two-round bracket, and the held/failed-vs-attribution
  separation all read correctly in a real browser, not just on paper.
- Adds one concrete lesson to the ASCII-source-discipline note 001's own results.md already
  raised for this file class: the discipline has to cover *entities embedded in JS data that
  later pass through an HTML-escaping helper*, not only raw literal characters in markup - a
  narrower failure mode than 001's mojibake bug, but the same family of defect, and worth a
  one-line callout in whatever review checklist a future standalone-HTML experiment uses.
- No changes to `docs/research_dashboard_concepts.md` itself - this experiment is deliberately
  downstream of and looser than that document, a prototype of its section 6, not a substitute
  for the open questions its section 8 already logged.
