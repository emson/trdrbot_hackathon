# Research: three dashboards for a desk nobody sits at

**Question.** What does a dashboard look like for a trading agent that never asks permission -
where the only thing a person can do is watch, understand, and trust or distrust what they see?

**Answer.** Three genuinely different metaphors were designed and pressure-tested against the
same battery of scenarios: a newsroom (**the Wire**), a launch control room (**Mission
Control**), and a live elimination tournament (**the Arena**). None of them wins outright. The
recommended design, **the Floor**, cherry-picks the piece each one got right and rejects the
piece each one got wrong, and every rejection is on the record in section 7 so it doesn't get
re-proposed later without the reason attached.

This is a brainstorm, not a build plan. Nothing here is scoped into commits, module names, or a
data-contract diff the way `specs/notes/029_the_desk.md` is for the claim-input desk. If section
6's design gets a green light, it earns a notes/0NN plan of its own before anyone writes Svelte.

---

## 0. The brief, and what already exists

The ask, restated: a dashboard that dramatizes the loop's own shape -

```
news ─┐
odds ─┼─▶ research ─┐
wiki ─┘   discovery ─┼─▶ thesis ─▶ simulate ─▶ size ─▶ execute ─▶ attribute ─┐
          muse ──────┘      ▲                                                │
                            └──────────── what it learned ───────────────────┘
```

- headlines arrive, and several agents (research, discovery, the muse) can each put forward a
  reading of them as a competing **thesis**;
- most of those readings lose, on the record, with a reason;
- the survivor becomes a **ticket** - a structure, a size, an order - handed to execution;
- the fill becomes a position, and the position eventually **grades itself**, honestly, against
  the claim it was supposed to prove;
- and a person watches all of it happen without a single control in reach. No approve button, no
  override, no "trade this instead." `agent/README.md`'s Coach section already states the
  principle this dashboard has to respect, not invent: *"It is autonomous on purpose - approval
  gates block the feedback loop."* The one knob a principal owns, `trading.risk_appetite`, lives
  in `config.yaml`, not in a UI, and is out of scope here on purpose - see
  [`specs/decisions.md`](../specs/decisions.md) D-099.

Two things already exist and set the floor this has to clear, not the ceiling it has to invent:

- **`/demo`** (`specs/notes/028_demo_page.md`, shipped) already replays one real decide cycle as
  five stages - Sense, Think, Act/Declined, Learn, Remember - with real components:
  `PriceBand.svelte` (closes plus the claimed band, resolved with a held/failed dot),
  `CandidateTable`/`PayoffChart` (structures priced and thrown out, with `fate` strings
  verbatim), `Funnel.svelte` (idea counts to attribution, "no Sankey, the bars are the visual,
  the text is the record"), `ForecastDots.svelte` (every resolved forecast at its stated
  probability), `CoachCard.svelte` (the self-improvement loop's open experiments), and
  `CycleReel.svelte` (a chip strip to page between cycles). The elf mascots
  (`elf-thinking.jpg`, `elf-confident.jpg`, `elf-analysing.jpg`, `elf-success.jpg`,
  `elf-coding.jpg`) already mark each stage. This is a deep, honest, well-built **single-cycle
  reader**. It is not an ambient, multi-ticker, walk-up-and-glance **floor**, and it does not yet
  dramatize the muse's alternative theses *competing* before one wins - which is exactly what was
  asked for here.
- **`theos-desk.html`** (`specs/experiments/001-the-desk-prototype/`) is a different animal
  entirely, and worth being precise about why: it is an **input** surface. A visitor drags a band
  onto a chart, states their *own* claim, and the page prices and sizes *their* trade using a
  ported copy of the real playbook and sizer math. It is deliberately a practice instrument for a
  human trader, recorded to `localStorage`, never touching the real book. None of the three ideas
  below are a variation on it - this brief explicitly asks for the opposite thing, a
  **read-only** window onto Theo's own real decisions, and the two should stay visually
  distinguishable so a visitor never mistakes one for the other.

## 1. Constraints every idea has to hold to

These came out of reading the code before designing anything, the same discipline
`specs/notes/029_the_desk.md` §0 insists on:

1. **Zero control surface.** Nothing on the page can cancel an order, override a gate, or nudge a
   size. If a future idea wants a button, it opens a question, not a feature.
2. **Never fabricate liveness.** The agent ticks on a cadence and the site republishes on
   `publish.sh`; it is not a running server pushing frames. An *elapsed* clock ("last synced 4m
   ago") is a real fact. A *countdown* to an unannounced next tick is a guess wearing a clock
   face - exactly the kind of thing this project's own mojibake defect (`results.md`, the 001
   experiment) got caught doing once already, just in a different register (a UTF-8 assumption
   instead of a scheduling one).
3. **Nothing invented, nothing smoothed.** The standing rule from `/demo`'s own spec - "no
   Sankey, the bars are the visual, the text is the record" and "text always accompanies
   colour" - applies to every new visual idiom proposed here too. A bracket, a heat pulse, a
   status light: each one has to trace to a real field or it doesn't ship.
4. **Decline is the modal outcome, and the dashboard has to survive that.** The root
   `README.md`'s own numbers make the point without needing an invented ratio: **165 theses
   formed, 9 positions opened.** Most of what this system thinks does not become a trade, most
   cycles do nothing external at all, and a "trading dashboard" that only feels alive when money
   moves will feel dead almost all the time. This is the single hardest problem in the brief and
   the axis the three ideas differ on most.
5. **Build on the data that already exists.** `cycles[]` (notes/028 §8.1) already carries, per
   cycle: every thesis with its `probability`, `band_low/high`, `horizon`; every priced structure
   with its `fate` and rejected ones intact; the muse's rejected candidates as
   `think.muse_fates[]` (`underlying`, `fate` string, `stated` probability); the sizing waterfall
   and its `binding` constraint; the fill and any `orders_rejected`; the resolved forecast,
   attribution verdict, and what got written to which store. A design that needs none of this
   extended is cheaper and safer than one that needs a new exporter pass before it can be judged.

## 2. A shared vocabulary: reinventing the panel

A conventional trading terminal's panel set assumes a human is about to act. Reinventing it for
an observer of an autonomous system means keeping the *shape* - a wall of small, dense,
purpose-built rectangles - while being honest that the content underneath means something
different:

| Terminal panel | What it assumes | trdrbot's honest equivalent |
|---|---|---|
| Watchlist | prices you might trade | **Coverage** - what the wiki (`agent/data/wiki/research/*.md`) is actively researching, with regime context and staleness, not a price list |
| Order book / depth ladder | live stacked bid/ask | **The gate ladder** - the deterministic checks (edge, `p_band`, liquidity, correlation cap, `MIN_BAND_EDGE`) stacked and lit pass/fail, each with its `fate` string attached, never a bare colour |
| Level 2 / time & sales | trade-by-trade tape | **The wire** - inbound items in arrival order: news, research opportunities, discovery nominations, muse candidates, position reviews (`sense.items[]`) |
| Chart | candles for one symbol | **`PriceBand`**, reused as-is - the claimed band on real closes, a held/failed dot once resolved |
| Positions / P&L blotter | open risk and running P&L | **The book** - live positions, unrealized %, and the attribution tag once a position closes (never before - attribution needs the horizon to pass) |
| Order ticket | what you're about to send | **The ticket** - stamped `TRADED` / `DECLINED` / `REFUSED`, carrying the winning structure, the size, and *why that size* (`sizing.binding`) |
| Price alerts | a level got crossed | **The Coach** - promotions, newly opened experiments, sentinel trips: the alerts that matter here are epistemic, not price-based |

Every idea below is built out of this same seven-panel grammar, arranged differently and skinned
in a different voice. That shared grammar is itself one of the things worth keeping regardless of
which idea wins - see section 6.

## 3. Three ideas

### Idea A - The Wire (a newsroom filing stories about the market)

**One line.** Theo's three thesis sources are three reporters with different beats, filing
competing stories about the same headline; an editor's desk keeps the ones that survive the
gauntlet and spikes the rest; the survivor runs as a front page, then gets a correction if it was
wrong.

**Pipeline mapping.**

| Stage | Newsroom frame |
|---|---|
| Sense | The wire feed - news, research, discovery, muse items scroll in arrival order, each with a source byline |
| Think | The pitch meeting - every filed thesis is a story pitch card; the editor's red pen (the deterministic gates) crosses out the ones that fail, in the gate's own words, not a euphemism |
| Act | The front page - the winning structure, typeset as a headline plus deck, with the ticket stub stapled to the corner: `TRADED` / `DECLINED` / `REFUSED` |
| Learn | The correction box - "this story held" or "this story was wrong: here's what we got wrong about it," using the real attribution label, not a rewritten one |
| Remember | The morgue - what got filed to the journal, ledger, wiki and elfmem, styled as an archive drawer stamp |

**Layout sketch.**

```
+-----------------------------------------------------------------+
| THE WIRE            equity $110,123 (+10.1%)  tier SCALE  ...   |  <- vitals strip
+---------------------+--------------------------------------------+
| THE WIRE (ticker)    |  PITCH MEETING                            |
| 09:14 NVDA research  |  research: "NVDA breaks 235 on the print" |
| 09:15 headline: ...   |    band 232-245, stated 62%   [SURVIVES] |
| 09:16 muse: SPY x XLE|  muse: "SPY drifts into a range while XLE |
| 09:20 discovery: PLTR|    leaks" band 758-772  [rejected: p_band |
|                       |    edge -0.04]                            |
+-----------------------------------------------------------------+
| FRONT PAGE: NVDA 230/240 bull call debit          [TICKET: TRADED]|
|   payoff chart with the band shaded, 18 contracts, 5.06% of eq   |
+-----------------------------------------------------------------+
| CORRECTIONS (last 5 resolved)   |  THE MORGUE (this cycle)       |
+-----------------------------------------------------------------+
```

**How it handles decline as the modal outcome.** The newsroom has a real, familiar answer for
"most pitches don't run": the **spike** - the physical pile (later, the digital graveyard) of
stories an editor killed. A quiet cycle is not an empty page, it's a taller spike, and "3 stories
pitched, 3 spiked, nothing ran" is a completely normal, mildly interesting newsroom sentence
rather than a broken-looking void.

**What's novel and fun about it.** Turning `sense.items[].source` into three actual voices -
research as a beat reporter working the regime page, discovery as a stringer chasing one tip,
muse as the op-ed columnist pitching the collision nobody asked for - gives the *existing* source
field a personality it doesn't currently have anywhere on the site. The editor's red pen makes
rejection visually satisfying rather than merely informative.

**Risks.** Journalism implies narrative and spin, which is close to the one thing this project
works hardest to avoid - the whole differentiator is refusing to let a good story substitute for
a falsifiable claim. Every "headline" has to be the claim text verbatim, every "correction" the
real attribution label verbatim, or the metaphor undercuts the product. Overplayed, it reads as
twee rather than sharp.

### Idea B - Mission Control (an ops room around a fully autonomous flight computer)

**One line.** A launch control room where nobody flies the rocket - the flight computer does -
and the room's whole job is instrumented, legible telemetry plus a go/no-go poll before anything
irreversible happens.

**Pipeline mapping.**

| Stage | Mission control frame |
|---|---|
| Sense | Telemetry intake - the wire panel, styled as an incoming-data console, not renamed |
| Think | Trajectory plus go/no-go - `PriceBand` as the flight path against a target corridor (the band), and a stacked poll of every gate reporting `GO` / `NO-GO` with its reason |
| Act | Stage separation - the funnel redrawn as mission stages, each one shedding what didn't survive, ending in a stamped ticket exactly as in Idea A |
| Learn | Post-flight report - held/failed, attribution, P&L, in one debrief card |
| Remember | The mission log - journal/ledger/wiki/elfmem writes, styled as flight-log entries with a timestamp |

**Layout sketch.**

```
+-----------------------------------------------------------------+
| MISSION CONTROL      T+04:12 since last tick   NOMINAL          |  <- honest elapsed clock
+-----+------+------+------+------+------------------------------+
|SENSE|THINK |ACT   |LEARN |REMEM |  five status lights, always   |
| ON  | ON   | idle | ON   | ON   |  labelled, never colour-only  |
+-----+------+------+------+------+------------------------------+
| TRAJECTORY (PriceBand)          |  GO / NO-GO POLL              |
|  claim band shaded on the chart |  edge        GO  (+0.62)      |
|                                  |  p_band      GO  (0.31)       |
|                                  |  liquidity   GO               |
|                                  |  corr. cap   NO-GO (SPY 28%)  |
+-----------------------------------------------------------------+
| STAGE SEPARATION: ideas -> gates -> claims -> structures -> ... |
+-----------------------------------------------------------------+
| FLIGHT LOG (scrolling, bottom-pinned)                            |
+-----------------------------------------------------------------+
```

**How it handles decline as the modal outcome.** This is the metaphor's single strongest point.
"Nominal, no burn" is *in genre* - most of a real mission control shift is exactly that, and
nobody watching a launch feed reads a long stretch of green boards as the system being broken.
`NOMINAL · declined` costs nothing to say and matches how the audience already reads this kind of
room.

**What's novel and fun about it.** The funnel (already a plain bar chart in `/demo`) becomes a
literal staged process - ideas, gates, claims, structures, sizing, trading, scoring, attribution -
each one visibly shedding the majority that didn't make it, which is a closer visual match to
what a multi-stage filter *is* than a bar chart, without inventing a metric that doesn't exist.

**Risks.** Can read as self-important or sterile if played completely straight - a launch room has
no mascots. The elves have to be deliberately kept in (small, corner, unchanged from `/demo`) or
the tone tips too far from "trdrbot" and toward generic ops-dashboard boilerplate. The T+ clock
is also the idea's biggest honesty trap: it is trivial to slide from "T+4:12 since the last tick"
(true) into "T-1:48 to the next one" (a guess) without noticing the line got crossed.

### Idea C - The Arena (a tournament the ideas play, and a book that has vitals)

**One line.** Candidate theses enter a live elimination bracket; the book of open positions is a
thing with vitals, not a spreadsheet; the Coach is a gardener pruning and grafting a family tree
of lever variants.

**Pipeline mapping.**

| Stage | Arena frame |
|---|---|
| Sense | Same wire panel, unchanged |
| Think | **The bracket** - muse candidates collide and are eliminated round by round down to the two that graduate (`think.muse_fates[]` plus the survivors in `think.theses[]`); the survivors enter a second, smaller bracket where priced structures compete on edge until one is `chosen` |
| Act | The ticket, same stamped motif as A and B - the shared piece, see section 6 |
| Learn | The scoreboard - held/failed as a win/loss record, resolved claims accumulating like a season record |
| Remember | Tree rings - the Coach's lever lineage, incumbent -> challenger -> promoted, drawn as branching growth rather than a flat log |

**Layout sketch.**

```
+-----------------------------------------------------------------+
| THE ARENA     tier SCALE  [XP bar >>>>>>-----]   trust 0.76      |  <- competence + Brier as vitals
+-----------------------------------------------------------------+
| MUSE BRACKET (this cycle: 6 candidates)                          |
|  [SPY x XLE] -- eliminated: p_band edge -0.04                    |
|  [NVDA x AVGO] -- eliminated: base prob 7%, "a lottery ticket"   |
|  [NVDA solo] --------------------------> graduates                |
|  [PLTR x QQQ] -- eliminated: correlated with an open name         |
|                        \_____ STRUCTURE BRACKET ____/            |
|                          bull_call_debit  vs  bull_call_on_band  |
|                          edge +0.62 WINS  vs  edge +0.41          |
+-----------------------------------------------------------------+
| THE BOOK (tiles, pulse tied to interim P&L, number always shown)|
| SPY -3.1%  | NVDA +5.4% [chosen] | PLTR held flat                |
+-----------------------------------------------------------------+
| COACH: lever family tree (incumbent -> challenger -> promoted)   |
+-----------------------------------------------------------------+
```

**How it handles decline as the modal outcome.** Also natural in-genre: "no entrant advanced this
round" is just what most tournament rounds look like, and the bracket itself - the process of
watching six ideas get cut to one, or to zero - is entertaining independent of whether a trade
results. This is the idea that most directly answers "I'd like to see the Muse create alternative
theses and then see how the most appropriate ones get chosen," because the elimination *is* the
whole visual.

**What's novel and fun about it.** The most game-like, most screenshot-friendly of the three -
genuinely turns "the muse produced 6 ideas and 4 died" into something legible and even
satisfying, and the competence ladder as an XP bar plus the calibration Brier score as a "trust"
meter give two numbers that already exist (`competence.tier`, `calibration`) a much stronger
visual presence than a plain stat tile.

**Risks.** Gamifying decisions about (paper) capital risks trivializing them, and clashes with
the site's established "professional instrument" register - the Fraunces serif, the sage-green
ledger paper, the same visual language `theos-desk.html` deliberately carried over rather than
invented. A slot-machine feel is the failure mode to design against explicitly: every pulse and
bracket line needs a number next to it, never standing alone as pure animation.

## 4. Scenarios simulated

The same battery, run mentally against all three designs. Where a scenario surfaced a real
decision, it's called out in prose below the table.

| Scenario | What's in the data | Wire | Mission Control | Arena |
|---|---|---|---|---|
| Busy morning: 6 headlines, muse spins up 6 candidates, 2 graduate, 1 trades | rich `sense`/`think`/`act` | strong - many bylines, a real front page | strong - stage separation has real shedding to show | strong - the bracket has real rounds |
| Quiet afternoon: a positions-only review, zero new items | `sense.items_total == 0` | spike grows by one, front page silent | `NOMINAL`, all five lights but Act stay lit-but-idle | book tiles keep pulsing on interim marks; bracket panel shows "no entrants this round" |
| Drawdown demotes SCALE to EXPLORE, next size cut ~63% (`specs/decisions.md` D-099) | `act.competence.tier` changes cycle over cycle | correction-box "the desk got smaller" reads oddly | ladder rung change reads naturally as a status change, like altitude | XP bar visibly *drops* a level - the only idea where "losing" is drawn as loss, which is honest but needs care not to read as punitive |
| Coach promotes a challenger (`P(better) >= 0.90`) | `coach.levers[].experiment.verdict` | "breaking: new house style adopted" - cute but strains the metaphor | a clean flight-log entry, in genre | a branch on the family tree lights up gold - strong, legible |
| Error cycle, `act.error_class` populated | `act.error_class` (class only, never the full message, per `/demo` §4.3) | "the presses jammed" - too cute for a real fault | "anomaly, cycle aborted" - reads right without alarmism | bracket just stops mid-round, ambiguous without an explicit state |
| Muse fate: `"rejected: base probability 7% - a lottery ticket"` | `think.muse_fates[]` | red-pen note in the pitch meeting, verbatim, lands well | GO/NO-GO poll line, verbatim, lands well | bracket elimination caption, verbatim, lands well - all three carry it fine because it's already good copy from the code |
| Attribution nuance: profit, but the thesis was wrong (lucky) | `learn.attribution.verdict` = view-wrong-structure-faithful family | correction box has room for nuance in prose | debrief card has room in a labelled field | scoreboard's win/loss framing actively fights this - a "win" that should teach nothing looks like a win, unless the tile is explicitly split into `outcome` and `attribution` as two separate marks |
| First-time cold visitor (a judge), 30 seconds on the page | - | needs one read to get "editor rejected most pitches" | fastest read: green lights + one red NO-GO explains itself in a glance | needs one extra beat to learn bracket notation before it reads |
| Small viewport | - | wire collapses to a single feed, pitch cards stack - fine | five-light strip and poll both compress to a vertical list - fine | brackets are the hardest layout to reflow to one column without losing the "elimination" read |
| Colour-blind / screen-reader pass | - | red-pen strikethrough already implies rejection without colour | status lights need text labels (already planned) not just colour, poll needs `GO`/`NO-GO` text (already planned) | bracket "win" needs an explicit label, not just a highlighted box; pulse needs the numeric label to be real DOM text, not a title attribute |

**The attribution-nuance scenario is the one that actually breaks an idea outright.** The Arena's
scoreboard framing (win/loss) is structurally at odds with the project's central point - a
profitable trade on a wrong thesis is supposed to *not* look like a win. Any tournament-style
visual adopted into the synthesis has to keep outcome (held/failed) and attribution (view right /
structure right) as two separately labelled marks, never collapsed into one W/L symbol. This is
carried into section 6 as a hard requirement, not a nice-to-have.

**The error-cycle scenario is the one that most rewards restraint.** All three metaphors want to
reach for a dramatic word (jammed presses, an anomaly, a stalled bracket); the actual existing
copy discipline in `/demo` §4.3 - "the class only, never the full message" - is already correctly
boring, and the winning move in every idea is to under-narrate a fault, not dress it up.

## 5. Evaluation against the brief

| Criterion | Wire | Mission Control | Arena |
|---|---|---|---|
| Shows alternative theses genuinely competing | strong | medium (poll shows gates, not competing claims as directly) | strongest |
| A legible "ticket" handoff moment | strong (front page + stub) | medium (buried in stage separation) | medium (needs the stub borrowed in) |
| Foregrounds *why*, not just *what* | strong (red pen is reasons) | strongest (GO/NO-GO is nothing but reasons) | medium (bracket captions carry it, easy to skim past) |
| Survives decline as the modal outcome | strong (the spike) | strongest (NOMINAL is in-genre) | strong (an empty round is still content) |
| Holds the attribution nuance (previous section) | strong | strong | weak, needs a fix |
| Matches the site's existing visual register | medium risk (twee) | medium risk (sterile) | highest risk (gamified) |
| Buildable on the current data contract, no new export | yes | yes | partial - full bracket wants muse candidate claim text the export doesn't carry yet (see section 8) |
| Novelty / "fun," as asked for | good | good, drier | best |

No single idea clears every row. That's the expected outcome of the exercise, not a failure of
it - it's why section 6 is a synthesis rather than a pick.

## 6. The cherry-picked synthesis: the Floor

**Concept.** A new ambient overview page, one click above the existing single-cycle `/demo`, that
a person can glance at cold and understand in five seconds, then drill into any cycle for the
full replay `/demo` already gives. Not a replacement for `/demo` - an entry point above it, the
way a trading floor's wall of screens sits above any one trader's terminal.

**What's kept, from where, and why:**

- **The vitals strip stays pinned, always visible.** Equity, day P&L, book exposure, competence
  tier, and the calibration verdict - because every idea independently reached for this, and the
  brief asked for it explicitly ("I'd like to be able to see the state of P&L"). Tier renders as
  Idea C's level bar (a real, already-existing four-rung ladder deserves to look like a ladder);
  the calibration number keeps `/demo`'s own honest phrasing ("below 15 this says nothing yet")
  rather than becoming an unqualified "trust score."
- **The wire (Idea A) is the left rail**, inbound items in arrival order, source bylines kept as
  a small mono kicker rather than a full character voice - present, not performed.
- **Idea B's `NOMINAL`/elapsed-clock register is the default idle state**, everywhere, because
  section 4 found it the most honest and the least effortful to write correctly. `T+ since last
  synced` only, never a countdown. The Wire's "spike" survives as a single collapsed line under
  the wire panel ("3 pitches didn't run today") rather than a competing visual system - one idle
  idiom, not three.
- **The muse's collision gets Idea C's bracket, scoped down to what the data already supports**:
  the two-round shape (candidates to two graduates, thence to a priced-structure winner) using
  `think.muse_fates[]` for the eliminated and `think.theses[]`/`think.candidates[]` for the
  survivors. See section 8 for the one field this asks for that doesn't exist today.
- **The gate ladder (Idea B) sits on the right**, GO/NO-GO, always with the reason attached -
  this is where "decision-making is an important part of the system" gets its clearest possible
  treatment, because a gate list *is* the decision, stated plainly.
- **The ticket motif (A and B's shared instinct) is the one physical object that travels** from
  the Think column to the Act column on screen - stamped `TRADED` / `DECLINED` / `REFUSED` - so a
  visitor's eye has one thing to follow across the whole page, the same way `/demo`'s own spec
  wanted "one interaction model" to run the page.
- **The book renders as Idea C's tiles**, pulse tied to interim P&L, but each tile carries *two*
  marks once a position closes - `held`/`failed` and the attribution label - never merged into a
  single win/loss symbol, per section 4's finding.
- **The Coach becomes an alert log**, Mission Control's flight-log rhythm narrating Idea C's
  family-tree events (promotions, new experiments, sentinel trips) as they occur - the log is the
  primary surface, the tree a `/coach`-style detail view if it's ever built out further.
- **The panel grammar from section 2** is the skeleton under all of it, so a reader who's used to
  a conventional terminal recognises the *shape* of what they're looking at even though every
  panel means something different underneath.

**Rough layout.**

```
+-------------------------------------------------------------------------+
| THE FLOOR   equity $110,123 (+10.1%)  [tier SCALE >>>>-]  trust 0.76    |
|             last synced 4m ago                                          |
+---------------+-----------------------------------------+---------------+
| THE WIRE       |  MUSE BRACKET -> STRUCTURE BRACKET       | GATE LADDER   |
| 09:14 research |  6 collide -> NVDA solo graduates ->     | edge    GO    |
| 09:16 muse     |  bull_call_debit WINS edge +0.62         | p_band  GO    |
| 09:20 discovery|                                          | liq     GO    |
| ...            |  [ TICKET: TRADED, 18 contracts, 5.06% ] | corr    NO-GO |
| 3 spiked today |                                          |  (SPY 28%)    |
+---------------+-----------------------------------------+---------------+
| THE BOOK (tiles)                          | THE COACH (alert log)       |
| SPY -3.1% held/failed + attribution        | muse.prompt: challenger      |
| NVDA +5.4% [this cycle]                    |   crossed 0.90 -> promoted   |
+-------------------------------------------------------------------------+
```

Everything under the strip is a card that, clicked, opens the matching stage in `/demo`'s existing
single-cycle reader - the Floor is the wall of screens, `/demo` remains the terminal you sit down
at.

**A name.** "The Floor" (plural, ambient - deliberately not "the Desk," which is already the
name of the single-seat *input* experiment, and the two should never be confused). Alternatives
considered: "The Wire" (too specific to one of the three ideas to stand for the synthesis), "The
Deck" (collides with `docs/deck.html`), "Mission Control" (reads as if humans are steering,
exactly backwards for a zero-control-surface page). Not a final decision - a name for a page that
doesn't exist yet should get chosen when it's actually specced.

## 7. What this deliberately does not include, and why

- **No live WebSocket/streaming telemetry for v1.** The agent ticks on a cadence; the site
  republishes on `publish.sh`. A truly live feed would need either a new public read API on the
  running agent process or a push channel that doesn't exist today - real new surface area and
  real new coupling between the public site and the live agent, for a feeling ("live") the
  cadence itself would still cap. Worth a future note of its own if ever pursued; not solved and
  not assumed here.
- **No literal order-book / depth-of-market ladder.** trdrbot has no Level 2 options data from
  Alpaca to show - a real depth ladder would have to be invented, which section 1's honesty rule
  forbids outright. The gate ladder in section 2's table is the panel that earns the name instead.
- **No click-to-annotate, "flag this decision," or comment affordance**, even though it reads as
  harmless because it's read-only. A running commentary thread sitting next to a live autonomous
  decision reads, over time, as a channel of influence even when it's technically inert - and the
  project's whole distinguishing claim is that nothing steers it. Keep that boundary visibly
  bright rather than technically-true-but-fuzzy.
- **No candlestick/OHLC charts.** `PriceBand`'s plain close-line-plus-band already carries the one
  fact that matters - did the claim hold - without importing intraday noise the agent's own
  reasoning never looks at either. Matching the agent's own epistemics beats matching a
  conventional terminal's look.
- **No sentiment gauge or mood ring on news items.** That would mean inventing a sentiment score
  the pipeline doesn't compute. The claim and fate text already *are* the qualitative read, and
  they're real.

## 8. Open questions for whoever builds this next

- **The muse bracket wants one field the export doesn't carry today.** `think.muse_fates[]`
  currently holds `underlying`, `fate`, `stated` for the *eliminated* candidates - no claim text,
  so a full "candidate A's claim vs candidate B's claim" bracket can't be rendered from what's
  exported now. A cut-down version (counts plus the eliminated `fate` strings, without their full
  claim text) is buildable today; the richer version needs a small `site_export` addition, not a
  new pipeline capability - the data exists in the journal, it just isn't in `snapshot.json` yet.
- **Is the Floor a new route, or a new top section of `/demo`?** Section 6 assumes a new page
  above the existing one; an alternative is folding an ambient strip onto `/demo` itself. Both are
  live options and weren't decided here on purpose.
- **Does an ambient, multi-ticker view need a rollup `snapshot.json` doesn't have yet** - "today,
  across every ticker," rather than "this one cycle"? `cycles[]` is already per-cycle; a Floor
  that shows several tickers moving at once may want a same-day aggregate the exporter would need
  to compute new, worth sizing before committing to the full layout in section 6.
- **How much of the elf mascot system carries over.** `/demo` uses one elf per stage,
  contextually. The Floor's density is higher and the stages are compressed into panels rather
  than full-width frames - whether the elves still fit at that scale, or whether they become a
  single mascot in the vitals strip instead, is a visual-design question for whoever builds this,
  not a research one.
