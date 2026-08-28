# A professional trader's critique, and what Theo learned from it (2026-08-28)

An independent options-trader review of the live decision log, then an optimize simulation of the
response, then implementation. Distinct from [notes/013](013_shakedown_trader_review.md), which
audited whether the code did what it claimed: this asks whether the *decisions* were good.

**Verdict on the decisions: the individual rejections were mostly right; the aggregate posture was
wrong.** And the reviewer would have taken a trade the system declined.

---

## 1. The critique

### What the agent got right

- Refusing the 765/760 put spread: collect $74-86 against $414-426 needs an 84-85% win rate
  against its own 72-83% models. The high-probability/poor-payoff trap, correctly named.
- Refusing to tune the vol input: *"I could have made these print positive by feeding the
  simulator 9% vol instead of 11% - that is tuning the input until it agrees with me."*
- Explicitly resisting the pull to repeat its one prior winner, calling it *"the weakest kind of
  argument"*. Pattern-matching on n=1 is what most humans do here.
- Passing on NVDA: buying a call spread at 41% post-earnings IV with quotes 5-10x wider than SPY's.

### The measured problem

| measurement | value |
|---|---|
| theses simulated since the ledger began | **18** |
| of those traded | **0** |
| stated SPY price forecasts holding at review | **5 of 5** |

**The views were right and none was expressed.** That is the signature of a miscalibrated gate,
not of bad judgement.

### Root cause: four defensible haircuts, stacked

The 21-day vol anchor, the bootstrap fat-tail correction, full round-trip friction, and a drift
haircut. Each is right on its own. Multiplied, they make a calm-regime trade arithmetically
impossible - so the system can only ever trade in high-vol regimes, which is where its edge claims
are weakest. A structural bias, not caution.

The vol anchor did most of the work. Same tape, same day: **21d realized 11.3%, 5d realized 5.9%**.
The agent quoted the 21-day figure against a 5-day horizon - a window contaminated by NVDA earnings
week - and dismissed the 5-day as "one quiet week, not a forecast". True, but 11.3% is not a
forecast either; it is a different backward window, chosen because it is the cautious one.

At live quotes and worst-case fills the declined condor collected **$186 against $314** with a 63%
breakeven win rate, and priced positive at any realized vol under ~9%.

### Two further findings

- **Its own act-triggers are decoration.** At 07:15 it committed to *"775/785 at <= ~$2.10 -> act"*.
  Live at 13:00: **$1.62**, spot unchanged. No cycle ever re-checked it. Every cycle is a cold
  start that re-derives from scratch and re-states fresh conditions the next one ignores.
- **It observes the skew and then prices it flat.** It correctly noted puts at 12.5-13.8% IV
  against calls at 8.5-9%, then simulated every structure at a single ~11% vol, muting the one
  genuine mispricing it had found.

---

## 2. The optimize simulation

Goal: convert a correct view into a position at the right size, and make a decline a scored
falsifiable claim - without becoming an agent that trades to feel busy.

Frozen scenario set of eight, including adversarial cases (regime break after selling premium;
agent games the mechanism; cold start with no history; vol call wrong five times running).

Two candidate mechanisms **failed the grounding lever** and were discarded before implementation:

| candidate discriminator | condor (good) | put spread (bad) | discriminates? |
|---|---|---|---|
| EV across a 6-14% vol band | −$92 .. +$95 | −$71 .. +$24 | **no** - both straddle zero |
| margin over breakeven win-rate | −21.5% .. +16.4% | −14.4% .. +4.6% | **no** - both "vol-dependent" |
| **breakeven vol** | wins if RV **< 9.2%** | wins if RV **< 7.6%** | **yes** - ranks them, names the bet |

A constitution principle saying "abstention is a position" was also rejected: the agent had
**already written that policy itself, in three separate cycles**, and declined anyway. A principle
it already believes is how a constitution becomes decorative.

### The correction the simulation forced

Breakeven vol alone would have been wrong. Measured on one board, one expiry:

| structure | per 1% spot | per vol point | what it is |
|---|---|---|---|
| iron condor | $9 | $23 | a **vol** bet (3x) |
| call debit 775/785 | $199 | $22 | a **direction** bet (9x) |
| bull put 765/760 | $114 | $12 | a **direction** bet (10x) |

Quoting a breakeven vol for the call spread puts the least relevant number in the most prominent
place. And a condor's EV is **non-monotone in drift** - it peaks at zero and falls away both sides -
so its breakeven in drift is a *band*; bisecting from the endpoints would have reported a confident
wrong number for every range structure the agent trades.

The third row is the finding a desk would care about most: **a far-OTM credit spread is not a
premium-selling trade, it is a leveraged direction bet wearing a premium-selling costume.** It has
the shape people associate with theta harvesting while its P&L is dominated by where the underlying
goes - which is why it looks like the safe choice and is the riskiest thing on the board.

---

## 3. What was built

**`optmath.breakeven_vol` / `breakeven_drift` / `dominant_risk`.** Generic scan-then-bisect over a
grid, the same shape as the existing `breakevens()`, so a two-sided band falls out naturally and no
structure needs case analysis. No crossing at all is reported ("EV positive at every vol tested"),
never hidden.

**A `NEEDS` line on every simulated candidate**, ordered so the dominant risk reads first:

```
NEEDS  a DIRECTION bet (9x) | wins if drift > 0.1% | wins if realized vol > 9.0%
NEEDS  a VOL bet (3x) | wins if realized vol < 7.5% | EV negative at every drift tested
```

**Memory, routed per the constitution's own `[routing]` rule:**

| store | change | why there |
|---|---|---|
| SELF | new principle `[assumptions]` | how to reason; not enforceable by a check |
| lesson | new `the-window-i-quote-is-a-forecast` | measured, falsifiable, should decay |
| lesson | new `abstention-has-a-price` | measured claim about how THIS book behaves |
| lesson | amended `friction-is-the-size-of-the-edge` | removed an unearned self-congratulation |
| lesson | amended `exploration-budget-is-not-a-mandate` | the bar cuts both ways |
| wiki | new `what-am-i-actually-betting-on` | stable technique concept, not an evolving claim |

The two amendments matter as much as the additions. **The lesson set was asymmetric**: five of six
lessons pushed toward "no", and `friction-is-the-size-of-the-edge` ended with *"I have declined
roughly ten cycles on this basis and been right to"* - a claim never scored, in the memory block
most likely to be recalled when a structure looks attractive. Stacked conservatism was not only in
the arithmetic; it was in the memory.

`[assumptions]` takes the constitution to **427 of its 430-token ceiling**, and the live SELF frame
to ~580 of elfmem's 600. It is full: the next principle requires retiring one, and raising the
ceiling past the frame's own budget buys a silent drop, not room.

---

## 4. Verified live

A forced decide cycle on the new code, unprompted output:

> *"the pricing didn't just reject my structures, it rejected them in the direction of my own view.
> **I forecast 8.5% realized and the condors needed sub-7.5%.** A thesis that is correct and still
> loses money at the offered prices is a real category."*

> *"My memory warns me that declining a +$4 to +$7 structure is an unstated over-cautious rule, and
> **I did just decline a +$7 structure.** I don't think I violated the rule — I passed on grounds of
> having no defensible thesis, not on grounds of the edge being small — but the two failure modes
> look identical from outside... If I pass on a similar structure next cycle with similar reasoning,
> that's a pattern worth challenging, not a principle worth congratulating myself on."*

The agent now states a **vol forecast as a number** and compares it to a breakeven, instead of
selecting a backward window and calling it an observation. It cites the amended lesson by name and
uses it against itself. It still declined - which is a legitimate answer - but it declined on
stated grounds that the tape can settle, rather than on a hidden input.

---

## 5. What was deliberately NOT built

- **Vol forecasts are stated but not yet SCORED.** The agent said 8.5%; nothing resolves that
  against realized vol at the horizon. The machinery is trivial (`market_stats._rolling_vol` over
  stored closes, no network, no LLM) and the ledger would need one field to carry the metric.
  Until it lands, the vol call moves no calibration and buys no size - which is the whole point of
  making it explicit. **This is the highest-value next step.**
- **Armed entry triggers.** The simulation kept them (expiring, wake-only, never auto-executing) as
  the only mechanism that fixes the dropped-commitment scenario. Not built.
- **The decline ledger with regret scoring.** Kept in the simulation for one reason nothing else
  covers: it separates a decline that was right about vol from one that was right about direction.
  Not built.
- **Friction on a hold-to-expiry structure.** Charging a full round trip on a spread intended to
  expire is an exit never paid. Named in the amended lesson rather than changed in code, because
  the agent does set profit targets and sometimes does exit - the honest fix needs the exit
  probability, not a flat assumption swap.

---

## 6. Residual risks

| risk | note |
|---|---|
| Breakeven vol is lognormal-derived, so it inherits the wrong tails | shown beside the bootstrap's disagreement, as the tail-gap warning already does |
| Realized vol over 5 sessions is a tiny, noisy sample to score against | genuine; still a scored commitment where there was none |
| The two new lessons recall at ranks 10-11, low | correct behaviour - they enter unproven, and `[earned-confidence]` says only scored outcomes move that |
| `[assumptions]` could push the agent toward trading | it says test the alternative, not prefer it; the edgeless-structure refusals in the frozen set still hold |
| Constitution is full at 427/430 | the guard test fails loudly rather than dropping silently |
