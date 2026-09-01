# Dev Journal - 2026-09-01: the knob, and the four places it could have lied

The ask was small enough to say in a sentence: let the user turn the risk up and down. What
shipped is one config number. Almost none of the day was the number.

The interesting part is that every hour of it went to the same question in a different costume -
*if I build this, where does it quietly not work, and what would have told me?* The system has a
long history of answering that badly. The compactor, the cache, the shared session all shipped as
code that ran, returned, logged healthily and did nothing. A risk lever is a prime candidate for
the same fate, because a knob that moves an inert constraint looks exactly like one that works.

---

## The research was right about the shape and wrong about the sequence

`research_risk_appetite.md` had already done the hard thinking: one scalar over the posture, two
clamps, a prerequisite to fix first, and a Monte Carlo saying what it buys. Building it meant
driving the real sizer under the proposal rather than a model of it, and four things fell out.

**A clamp that cannot fire.** The design carried a half-Kelly ceiling on the multiplier. The
tables make its maximum exactly 0.50 - `max(TIERS.kelly) x APPETITE_MAX = 0.25 x 2.0` - reachable
only in the limit as the resolved count goes to infinity. It is a correct invariant and dead
runtime code, so it became a test. And a second clamp on the exploration floor turned out to be
actively *wrong* once the floor derived from the book cap: at `0.35 x 0.22 = 7.7%` it would bind
and re-introduce a fourth loose constant, breaking the one property the whole lever rests on -
that a single multiplication reaches all four risk scopes.

Three clamps became one. The one that stayed is the ruin bound, which is the only one that was
ever load-bearing.

**A prerequisite that was not one.** The research sequenced I-69 first, because the shrink target
moves Kelly by 3x and the lever multiplies whatever Kelly produces. True, and it does not reach
size: the exploration floor binds above Kelly at every rung, so the 3x span lands entirely inside
a quantity `max(kelly, floor)` throws away. Kelly only governs above a shrunk probability of 52.6%
at the live rung, and this book's live claim shrinks to 42.0%.

The confirmation was not a simulation. It was four rows in `data/state/`:

```
pos_20260826_SPY_bull_put_spread    $2,210  = 2.12% of equity
pos_20260827_NVDA_bull_call_spread  $2,100  = 2.01%
pos_20260828_SPY_bear_put_spread    $2,171  = 2.08%
pos_20260901_SPY_bear_put_spread    $2,052  = 1.97%
```

Every position this system has ever opened, sized by the floor, four for four, each just under the
2.2% constant and short only by contract rounding. The entire Kelly apparatus - the shrink, the
ramp, the tier multiplier, the calibration record that earns it - has never once decided a trade.

That is uncomfortable and it is now written down as I-70 rather than discovered again in three
weeks.

---

## The floor had to move first, and it is the larger half

`SEED_FRACTION` was one constant, 0.022, across all four rungs. D-098 had already moved the other
three risk scopes onto the tier and left this one behind. Two consequences nobody chose.

The drawdown circuit breaker had no contacts. An 11% loss demotes MATURE all the way to EXPLORE -
and cut the next trade by **13%**, because the tier changed and the floor did not. That is the
mechanism an aggressive appetite setting would have been relying on to contain it. Derived from
the tier's own cap, the same demotion now cuts **63%**.

And EXPLORE, ESTABLISH and SCALE sized *identically*. Promotion changed the label and not the
money. The ladder was decorative in the one direction it exists for.

---

## The finding that made the rest of the day worth it

I applied the derived floor on its own and ran the suite. **535 tests passed.**

The exploration allocation had gone from 2.2% to 5.5% at MATURE. A 2.5x increase in how much of
the account a single trade puts at risk, and nothing in the repo objected. No test referenced
`seed_fraction` at all, and the one test whose entire job is "more evidence never means less size"
measures integer *contracts* at a payoff where the `contracts < 1 -> 1` promotion flattens every
rung to the same number - a blind spot D-098 had already documented for that same test and which
had gone on being blind.

So a green suite was not evidence. It had never been evidence for this. That reframed the rest of
the work: eleven new invariants sweeping the whole rung x appetite space on *fractions*, and each
one mutation-verified by reverting the fix and watching it fail. Reverting the derived floor fails
four. Removing the ruin clamp fails two. Double-scaling the floor - the `a²` bug, the single
easiest mistake in this change - fails one, caught by the invariant that says appetite must never
change *which* constraint binds.

---

## Where a knob hides

The design work kept turning up places the number could be set and quietly absorbed, and each one
got a surface rather than a comment.

**Above 1.75x at SCALE the knob does nothing.** The book cap pins at the 35% ruin bound and every
further turn is swallowed. So the posture computes its own `realised_appetite`, `trdrbot health`
warns when it diverges from what was set, and `trdrbot risk 2.0` says it in the one place the
decision is actually made: *2.00x only realises 1.75x*.

**The prompt would have told the agent it earned this.** `reason` is built from the tier table and
fed verbatim to the decide agent, sitting directly beside `next_tier_needs()` - which promises more
size for more resolved theses. Reporting only the applied Kelly would have had the system telling
its own agent it had *earned* a posture the operator chose, while the ladder went on advertising a
reward the appetite had already halved. It now says both: `Kelly x0.16 earned -> x0.08 applied`.

**A refusal would have blamed the wrong thing.** Cut the appetite far enough and an expensive
structure stops fitting under the per-position ceiling. The message read *"Position too large for
the account"* - identical whether the structure was genuinely oversized or the operator had turned
their own knob down. It now names the appetite and says what equity it would take.

**Cutting the appetite leaves the book over cap.** Sizing gates new risk and never liquidates,
which is correct - a preference dial that submits market orders is not a preference dial - but it
means the book runs above its new target until positions expire. Unstated, an operator reads their
own change as a failure. The prompt now says the cap is a target on the way down.

---

## Four copies of one policy, and a badge that could not fail

The last piece was not code at all. `trdrbot.com/risk-explorer.html` is an interactive page that
lets you drag a risk-appetite slider and watch 400 simulated books. It worked by re-implementing
`size_position`, the calibration shrink, the tier table and the demotion ladder in JavaScript.

It had drifted three ways. Its tier table back-solved to *three different* resolved counts, so one
rung was a fabricated agent presented as part of one ladder. Its derived-floor branch applied a
ceiling the Python does not. Its demotion looked up a neighbouring tier's frozen row instead of
re-assessing at the same evidence, so every drawdown path in the simulation under-sized.

And the page printed **"verified against Python"** through all three, because the nine reference
points it checked covered neither the affected rung, nor the affected mode, nor any demotion path.

That is the worst artifact of the day. A verification badge that structurally cannot fail is worse
than no badge, because it converts an unverified page into one that claims verification - on a
public site, about the exact numbers a judge would be checking.

The fix turned on a small observation: **`frac` does not depend on equity.** The fraction of the
account a trade takes is decided entirely by the posture and the structure; equity only enters when
you divide by the per-contract risk to get an integer. So the whole policy is a lookup table -
4 rungs x 15 appetite stops x 3 drawdown states, 180 rows - and everything the browser does on top
of it is two multiplications. `scripts/gen_risk_explorer.py` computes those rows with the real
`assess` and the real `size_position`; the page displays them. Roughly 100 lines of forked policy
deleted, along with a control for a mode the system no longer has and about 40% of the data blob
that nothing read.

The badge is gone. In its place, a test rebuilds the table from the committed inputs and fails if
the page stops matching the sizer - so changing the ladder without regenerating the page is caught
by CI rather than asserted by a green pill on the page itself. Verified by changing `SEED_SHARE`
and watching it fail.

A fourth copy turned up on the live scoreboard: `CompetenceLadder.svelte` hardcoded the four book
caps and the prose "Fixed 2.2% exploration allocation", then rendered the appetite-*scaled* Kelly
right beside the hardcoded *earned* caps. Two meanings of one number, on a public page. It now
reads the ladder from the snapshot.

---

## What it is set to, and why that is the only judgement call left

`risk_appetite: 0.50`, and the arithmetic is the argument: `0.20 x 0.50 x 0.22 = 0.022`, today's
flat floor at today's rung. The mechanism lands with the live book's position size **unchanged**,
so any behaviour change after this commit is a bug rather than the knob. That is the discipline
D-098 already ran on when it picked shares that made a fresh account's first trade byte-identical.

It holds today's size at today's *rung*, not forever - the whole point of the derived floor is that
size now moves with the ladder. When attribution produces its first verdicts and the book demotes,
the floor falls with it. That is the brake, working.

The measured case for going lower is strong and deliberately not taken today. At neutral, the
derived floor makes a >20% drawdown **more likely than not even when the thesis is right** - 53.8%
of paths. And the belief table says that for a book at a coin flip on whether its edge is real, the
growth-maximising setting is the *minimum*, all the way up to 60% confidence. This book has 49
resolved forecasts and **zero attributed positions**. Moving to 0.25 is a one-line commit whose
effect will be unambiguous, which is exactly why it should be its own commit.

One more thing worth recording, because it looks like a free choice and is not. `SEED_SHARE = 0.22`
with `appetite = 0.50` produces numerically identical results at every rung to `SEED_SHARE = 0.11`
with `appetite = 1.00`. The difference is entirely representational - and it matters. 0.22 is
*derived* (`0.022 / 0.10`) and has a provenance; 0.11 would be *fitted* to today's tier, which will
change. Putting the operator's preference inside the constant would hide a choice inside a
derivation, and the whole day was about not doing that.

---

**Shipped:** 548 tests (+13), lint clean, all four scaffolds green, mutation-verified five ways.
Live effect on the real book: nothing. SCALE, exploration floor 2.20%, the same 13 contracts.
Which is what shipping a mechanism behaviour-neutral is supposed to look like.

---

## Later the same day: the deadline came off, and a corpse fell out

Two more asks: run indefinitely, and trade more than one name. The first was a config change with
a trap in it. The second turned out not to be a feature request at all.

**Removing the deadline was mostly already done.** `can_open` is documented as inert without one,
and the force-close sweep is an ordinary exit rule whose signal returns `None` and therefore
*holds* - "unobservable signal holds; it never fires blind". Two of the three things that had to be
right were right before I touched anything.

The third was the trap. `forecast_window` returned `None` with no deadline, and each caller had its
own fallback for that: the muse's was the literal string `"10 days out"` - **the exact 1-10 day
range D-070 deleted** after measuring that its output clustered at the far end. Deleting the
deadline would have silently reinstated the bug the deadline had been masking, and nothing would
have complained, because every fallback reads as sensible in isolation. A constraint whose removal
restores the defect it replaced is not a constraint, it is a coincidence. Short horizons are a
property of good forecasting, not of a competition, so the window now always exists and a hard stop
merely tightens it.

**The multi-asset question had a much worse answer.** I expected a config change. What the
investigation found was six lines in the journal:

```
2026-08-31 13:39 / 15:53 / 17:58, 2026-09-01 14:03 / 16:09 / 18:15
  hunt  opportunities=0  error=TypeError("'list' object is not callable")
```

`discovery.run` binds `section = [...]` for a block of per-ticker prose. That makes `section`
function-local for the whole body - including the `section(text2, ...)` call fifty lines later that
splits the model's reply into its two JSON halves. `llm.section` was never imported. So every hunt
that successfully nominated candidates then crashed, after spending two LLM calls, a bar fetch, a
yfinance call and an option chain **per nominee**. Six consecutive runs over two days. The
fail-open handler printed it and moved on.

Discovery is the only source that can introduce a name from outside the fixed five-name research
universe. The muse collides wiki concepts, and housekeeping had deprecated 25 of 30 research
dossiers, leaving exactly those five - so the "random collision" engine was colliding the universe
with itself. The book did not become single-name by judgement. Its supply of new names had been
severed and every log line read healthy.

Introduced by a refactor whose commit message was *"one reply-text seam, one JSON parser home"*.

**The class is what matters, not the instance.** An imported callable rebound in its own scope is a
`NameError` that only fires when that line runs: it passes import, passes lint, and dies on the
branch nobody exercises in a test. So the guard is a whole-package AST check rather than a test for
this function - every `from X import f` where some function both calls `f` and assigns to `f`.
Mutation-verified by putting the shadowing back.

**And then the four things that kept it single-name even when candidates did arrive.** 62
opportunities across 40+ names had reached the inbox; the agent formed theses on two.

- The only news feed was scoped to `config.watchlist` - `"SPY"` - so the observations block was a
  SPY feed by construction and the agent was right that it had nothing new.
- The snapshot priced only names *already held*, so a candidate arrived with bands and no mark. On
  both cycles where non-SPY candidates were presented, the agent made **zero** tool calls and its
  summary mentioned neither. An option you cannot see the price of is not an option.
- The prompt said `- Watchlist: SPY` under a heading called `## Constraints`. Nothing in
  `tool_guard`, `sizing` or the order path filters by symbol, and the book had already traded
  NVDA. One word, under the wrong heading, outranked every line of code in the repo for a fortnight.
- The beta-delta flag stamped *"these positions are one market bet, whatever the names suggest"* on
  a book holding **one** position, where that is a tautology. It was the stated reason for
  declining in five of the last six no-ops - against a $2,052 max loss with $15,652 of budget free.
  A second name would have lowered that number. The flag was telling it not to.

Verified by running it: `trdrbot discover` completed for the first time since 08-31 and nominated
PANW, MDB, HOOD, LRCX, PCG, writing five dossiers - which also doubles the muse's collapsed concept
pool from five names to ten.

The thing I keep re-learning on this project is that "why isn't it doing X" is almost never a
preference. Four of the five findings today were surfaces telling the agent something false, and
the fifth was a corpse.
