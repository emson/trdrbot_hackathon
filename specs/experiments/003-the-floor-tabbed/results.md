# Experiment 003: Theo's Floor v2 - tabbed, tiled, prose removed

Iteration on [experiment 002](../002-the-floor-prototype/results.md). Same content, restructured
for a user rather than for a spec.

## Hypothesis

002 proved the Floor's content works. Its interface did not: roughly ten lines of chrome sat
above the first piece of data (wordmark, three stat stacks, two clock lines, a five-line
standfirst), explanatory sentences hung off every heading, six separately-bordered cards did the
job of one tile with six rows, and all three subjects lived on one long scroll. The hypothesis:
the same content reads better with the chrome cut to one row, the explanation moved into links,
the small cards merged into fewer tiles, and the three subjects split across tabs.

## Method

`code/the-floor-v2.html`, a single self-contained page (~760 lines), rebuilt rather than patched.
Three design decisions drove it:

**1. Three tabs, from the three questions a viewer actually has.** *What is it thinking?* (the
loop), *how is it doing?* (the book), *is it getting better?* (the coach). Two thirds of the page
leaves the screen at any moment. The loop tab is the default because the decision story is the
compelling one, and a cold visitor should land on it.

**2. Fewer, larger tiles containing rows.** 002 drew a border around every bracket candidate and
every wire item. v2 draws one tile per concept and separates rows with hairlines, so the eye
counts four objects on the loop tab instead of twenty. State is carried by a badge and a tint on
the winning row, not by a border on every row.

**3. Explanation becomes a link.** Every sentence that explained how the system works was cut and
replaced, where it earned it, with a small link to the live site: `full replay` to `/demo`, `how`
to `/how-it-works`, `every decision` to `/ledger`. The page keeps only what is specific to what
just happened.

Header went from ten lines to one row: wordmark, three status pills (loop running, market closed,
tick), three stat tiles (equity, tier with its four rungs, brier). The standfirst and the two
footer disclaimer paragraphs are gone entirely - a demo does not need to announce that it is one.

Additions this iteration, three of them prompted by a reference dashboard shared mid-build
(Alpha Hunter, an Alpaca hackathon entry): status pills in the header instead of prose state, a
segmented filter on the cycle strip (`all` / `acted` / `declined`), and icons on the tabs and
tile headers. Its structure validated the tab direction; its dark-terminal skin was deliberately
not copied, since trdrbot already has a stronger identity of its own in the ledger register, and
consistency with the live site and deck is worth more than resembling another entry.

Content additions: the coach tab gained two real lever cards with a posterior bar and its promote
threshold marked (`muse.prompt` at 0.848 against a 0.90 bar; `playbook` at its 0.95 bar with no
open trial), which 002 only had room to show as log lines. The book tab gained a four-up account
stat row and a calibration stat row.

## Results

The loop tab was reviewed in the browser and renders as designed: one-row header, tab bar, filter,
a single-line cycle strip, and a two-column split of four tiles. The bracket reads as an
elimination without twenty borders, and the wire sits as one tile of rows with the selected
cycle tinted. Text above the first data point dropped from roughly ten lines to two.

The book and coach tabs were not confirmed visually. The artifact viewer stopped rendering after
several reloads in the same session, and `file://` navigation is blocked by the browser tool, so
the check could not be repeated. Their content is populated: every render call for those tabs runs
unconditionally before `paint()` at the end of the script, and `paint()` demonstrably ran, so
nothing in that sequence threw. What is unverified is their *layout*, not their data.

The v1-to-v2 comparison is worth keeping side by side rather than replacing:
[002](../002-the-floor-prototype/code/the-floor.html) is the content-complete draft,
[003](code/the-floor-v2.html) the designed one.

## Caveats

- **Book and coach tab layout is unreviewed** (above). Both use ordinary grid patterns already
  exercised elsewhere in the page, but neither has been looked at.
- **The theme toggle is still unverified**, carried over unchanged from 002 along with its open
  question - the same automated-click limitation applied again.
- Same illustrative day, same seven cycles, same provenance as 002: tick 812's figures are the
  worked example from `specs/notes/028_demo_page.md` section 8.1, and every fate and gate string
  is real trdrbot vocabulary rather than invented copy.

## Spec Impact

- The tab split maps cleanly onto the real site's existing routes, which is a useful signal for
  any production build: `the loop` is `/demo`'s territory, `the book` is `/ledger`'s, `the coach`
  is its own. A real `/floor` could be the index above those three rather than a fourth silo.
- Confirms the "explanation belongs in a link, not on the dashboard" rule is survivable: nothing
  on the page needed a sentence that a five-word link could not replace.
- The ASCII-source discipline held with no defects this time. The entity-through-`esc()` trap 002
  found was avoided structurally by keeping display glyphs in `\uXXXX` JS constants
  (`DOT`, `X`, `MINUS`, `CHK`, `CRS`) and never putting an HTML entity inside data.
