# Experiment 004: Theo's Floor v3 - charts, and the edge stated plainly

Third iteration. [002](../002-the-floor-prototype/results.md) proved the content,
[003](../003-the-floor-tabbed/results.md) fixed the interface, and this one answers the
remaining objection: it read like a report, not an instrument a trader would want to watch.

## Hypothesis

A dashboard for an autonomous trading agent earns a trader's attention through charts, not
prose, and the charts have to show something no other dashboard can. The hypothesis: trdrbot's
own record supports four charts that are genuinely unavailable to anyone else in this
competition, and drawing them turns the page from a readable summary into an instrument.

## The chart selection rule

A chart earned space only if (a) real trdrbot data stands behind it and (b) it shows something a
generic trading dashboard cannot. That excluded candlesticks (the agent never reasons in OHLC),
a book-composition donut (decoration), and a Sankey funnel (notes/028 rejected one on the merits
already). It included:

**1. The claim cone.** Price history to the decision day, then the lognormal cone the underlying's
own implied volatility projects forward, with the *claimed band* drawn over it. The whole bet
becomes one picture: the claim is tighter than the market's implied move, in a chosen direction.
When it resolves, a dot lands inside or outside the band and is labelled `held` or `failed`. No
other entry can draw this, because no other entry states a falsifiable band with a probability
before it trades.

**2. Payoff over the terminal distribution.** The payoff polyline (contract arithmetic, tagged
`fact`) drawn across the modelled lognormal density of the terminal price (tagged `modelled`), on
one shared x-axis, with the claimed band shaded through both. Their product is the expected value,
which the edge panel then states in dollars. This renders the project's own facts-versus-models
rule as a picture rather than a caption. Hovering reads out the price, the per-contract P/L and
the position P/L at 18 contracts.

**3. The annotated equity curve.** Eight sessions, $100,000 to $110,123, with the markers that
explain the shape: the first position, the 11% drawdown that demoted the tier, the restoration,
the playbook promotion. It shows the dip rather than hiding it, which is the more credible chart.

**4. The Coach posterior trace.** P(challenger better) climbing across paired trials toward its
promote threshold, drawn per lever with the 0.90 and 0.95 bars marked and the futility line below.
A chart of a trading system improving itself is, as far as this build is aware, unique.

Three cheaper additions carry the texture: a **sizing waterfall** (which constraint actually set
the size, with the binding one lit), a **reliability plot** (stated probability against realized
frequency, dot area by sample size, against the 45-degree line), and **sparklines** on every
position row.

## What makes it feel live

- **Play the day.** One button walks the dashboard through all seven cycles at 1.9s each, and every
  panel and chart re-renders as it goes. Any manual click stops it.
- **Hover readouts** on the cone, the payoff, the equity curve and the reliability plot, each with
  a crosshair and a tooltip carrying the numbers that chart is actually about.
- **Scrollable panels**, which raised the data density substantially without making the page
  taller: the collision now shows nine competing theses rather than six, the book carries eight
  positions, the wire carries eleven items across the day, and the Coach log nine events.
- **Charts redraw on theme change**, since their colors come from the token set.

## The edge panel

Added beside the cone, because "would this make money" is the question a trader actually arrives
with. It states the agent's own probability against the modelled `P(band holds)`, the defined max
profit and max loss at the traded size, and then the comparison that matters: the market's implied
move (`-/+ $12.92`) against what the claim needs (`-/+ $6.50`), as two bars on one scale, with the
modelled expected value underneath. Nothing there is a promise; every number is derived from the
chain and labelled where it is modelled.

## Results

The first clean load was reviewed in the browser. The header, cycle strip, filter, play control,
the claim cone with its band and 1/2-sigma envelopes, and the edge panel all render as designed;
the cone reads exactly as intended, with the claimed band sitting visibly tighter than the cone it
is drawn against. One defect was found and removed in that pass: a dead code path left in the cone
renderer, computing an unused point array with garbled index arithmetic before the real one.

The artifact viewer then became unresponsive after repeated reloads, as it did in 003, so the
lower half of the loop tab and the book and coach tabs could not be re-checked visually. Those
paths were instead exercised directly under a DOM stub in node: `drawEquity`, `drawCal`,
`drawAttr` and `renderLevers` all produce substantial output without throwing, all seven cycles
paint (including the ones with no chart, no payoff and no bracket), and the book rows render. The
same harness independently confirmed the maths: `pBand` returns 0.3062 for the NVDA claim, which
is the 31% the edge panel displayed in the browser, so the modelled probability shown on screen is
the one the function actually computes.

## Caveats

- **Layout of the book and coach tabs is unreviewed.** Their code runs and emits markup; nobody
  has looked at the result. Same for the payoff chart, the bracket scrollbox and the waterfall,
  which sit below the fold on the loop tab.
- **Price history is synthetic**, seeded per symbol so it is stable across reloads, anchored on the
  real spots and implied vols. The cone, the density and `P(band holds)` are real maths over that
  synthetic history, and are labelled `modelled` wherever they appear.
- **The lognormal is the model, and it is the honest one to use here** since it is what the
  project's own bootstrap and playbook arithmetic assume, but it is still a model: no skew, no
  term structure, drift zero.
- The theme toggle remains unverified by automation, carried forward from 002 and 003.

## Spec Impact

- The claim cone is the strongest candidate to carry into the real site. It needs only data
  `snapshot.json` already has (`closes`, `band_low`, `band_high`, `horizon`, `entry_iv`) plus the
  same lognormal grid `optmath` already uses, and it says more in one picture than the existing
  `PriceBand` component does.
- The edge panel's implied-versus-claimed comparison is worth stealing back into `/demo`, where
  the claim is currently stated without any reference to what the market was pricing.
- Confirms the discipline from 003 survives contact with a much larger file: 1,230 lines, zero raw
  non-ASCII characters, no entity ever placed inside data that passes through `esc()`, and the
  display glyphs held in `\uXXXX` constants.
