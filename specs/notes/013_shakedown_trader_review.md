# Shakedown — a trader's review of the running system (2026-08-28)

Third simulation pass, and the first run against the **implementation** rather than the design.
Notes [006](006_simulation_stress_run.md) and [007](007_simulation_regression_run.md) traced
scenarios through `architecture.md`; this one traces them through the live journal, the usage
ledger, the position frontmatter, the elfmem SQLite and the real Alpaca responses, asking one
question per subsystem: **does this do what it says?**

**14 defects. Four of them meant a headline capability was not running at all.** The 156-test
suite was green throughout and caught none of them, which is now the fourth consecutive pass where
that has been true and is itself the most useful finding in the file.

Method, unchanged from D-070 because it keeps working: read live state against what the code
claims, and when reasoning cannot settle a question, compute it.

---

## 1. The four that were not running

These are the important ones. Each is a capability the README describes, that has a module, that
has tests, and that produced nothing in production.

### 1.1 Every mark-based exit rule on the book was unreachable — CRITICAL

`analytics.position_pnl_pct` divided position P&L by the **gross premium summed across all legs**.
On a vertical spread gross and net differ by 2–7x, so every stop and target the agent has ever
written was measured against a base several times larger than the money it actually put up.

Priced at the two live positions' own entry parameters:

| position | rule | fires at | structure allows | verdict |
|---|---|---|---|---|
| NVDA 230/240 debit | `stop_loss -60%` | −$2,287 | max loss $2,253 | **never fires** |
| NVDA 230/240 debit | `profit_target +70%` | +$2,668 | max profit $7,747 | fires at **+118% of the debit** |
| SPY 755/750 credit | `profit_target +50%` | +$1,057 | max profit $535 | **never fires** |
| SPY 755/750 credit | `stop_loss -100%` | −$2,114 | max loss $1,965 | **never fires** |

Three of four could not trigger; the fourth triggered at nearly twice its stated level. The agent
believed it had a −60% stop on NVDA. It had a sentence.

`trdrbot health` has reported `exit_rules never ran` for two days, and it was read as a quiet
market. It was arithmetic.

**Fixed:** the denominator is the **net debit paid or credit received** — what a broker's P&L%
column shows and what a trader means. A debit spread's loss is then bounded at −100%; a credit
spread's `+50%` is the standard "buy it back for half the credit". A near-zero net cost returns
`None` rather than dividing by noise, so an unobservable signal holds instead of firing blind.

Added on top, because the fix removes the symptom and not the class: `record_position` now names
any mark-based rule that **cannot** trigger against the structure `simulate_experiments` priced —
matched by legs, so nothing is re-declared. Same shape as `watched_signals` (a stated level no rule
watches), one level deeper: a rule that is watched and cannot fire.

### 1.2 Interim scoring has been dead since the day it was added — CRITICAL

`INTERIM_BANDS = (25.0, 50.0)`, compared against `position_pnl_pct`, which returns a **fraction**.
Band 1 therefore required +2500%. Interim scoring is the mechanism INV-24 introduced to make the
learning loop turn inside an 8-day window at all, and it has never fired since the bands landed.

The journal is unambiguous: eight `interim_outcome` rows, **all** dated 2026-08-26, none since,
across ~250 subsequent ticks.

Both unit tests passed the whole time. They spoke percents (`-3, -12, -27`); the caller spoke
fractions. Each side was internally consistent and jointly wrong — which is exactly why a test
written against a constant proves nothing about the seam.

**Fixed:** bands are fractions. The replacement test derives its input from `position_pnl_pct`
itself rather than from a literal, so the unit is pinned to its one producer.

### 1.3 Option-chain compaction has never once run — HIGH (cost and accuracy)

D-065 describes result compaction as the larger of its two levers. It has never executed.

`langchain_mcp_adapters` builds tools with `response_format="content_and_artifact"`, so a tool's
coroutine returns `([{"type": "text", "text": "<json>"}], artifact)` — never the dict the
compactors were written against. Every call hit the `isinstance(result, dict)` guard and took the
**fail-open** path, which returns the original. It fails open by design and looks identical to
success: no error, and the `[compact]` line only prints when output actually shrinks.

Measured against the real server: one SPY chain is **79,052 characters (~20k tokens)**, re-sent on
every subsequent agent turn. 28 chain calls sit on the journal; not one was compacted. D-065's
measured 48% saving came entirely from the tool allowlist.

**Fixed**, and verified live: `79,542 → 6,076 chars, a 92% reduction`.

Two things surfaced once it started working:

- The **ATM inference was 6% wrong** on real data. A SPY chain page comes back as 100 contracts,
  strikes 500–773, **all calls, no puts**, with a next page — so the put-call-parity method found
  nothing and the median-strike fallback put ATM at 724 against a tape of 771.67. Parity from one
  side fixes it: `min(C + K)` is the tightest upper bound on the forward and converges to it deep
  ITM. Live: 769.67 against 771.67.
- The compacted header now states **what is actually on the page** — rights present, strike range,
  whether more pages exist. An agent pricing a put spread off a calls-only page is pricing nothing,
  and it could not see that from a table of rows.

### 1.4 `_market_pulse` was defined, tested, and never called — MEDIUM

`idle.decide` absorbed the whole rung when D-043 landed; nothing removed the original. Worse than
dead: it carried its **own copies** of both thresholds, so anyone tuning `PULSE_MOVE` would have
changed system behaviour by exactly nothing while its test kept passing.

**Deleted.** `idle.MATERIAL_MOVE` and `idle.MAX_SILENCE_MIN` are now the only copies, and the test
exercises the path production takes.

---

## 2. Calibration, measured rather than assumed

The user's question was whether everything is in tune. Three things were not.

### 2.1 Murphy reliability read the bin centre, not the stated probability — HIGH

```python
reliability = sum(len(os_) * (sum(pb for pb in [b]) - mean_outcome) ** 2 ...)
#                             ^^^^^^^^^^^^^^^^^^^^ this is just `b`, the bin CENTRE
```

Murphy's decomposition needs each bin's mean **forecast**. Bin count is `max(2, min(10, n // 8))`,
so below n=24 there are two bins: every forecast under 0.5 was scored as if stated at 0.25 and
everything above it at 0.75.

Against the live record — one resolved forecast, stated 0.38, outcome true:

| | reliability |
|---|---|
| what the code returned | **0.5625** |
| the honest figure `(0.38 − 1)²` | **0.3844** |

And on a synthetic agent stating 0.95 while right half the time, at n=16:

| n | code | honest | MATURE gate (<0.04) |
|---|---|---|---|
| 16 | 0.019 | 0.150 | **passed** — should be blocked |
| 20 | 0.077 | 0.250 | blocked |

The error runs both ways (it also punishes an underconfident forecaster) and it feeds
`sizing.shrink_probability`, where `trust = 1 − reliability/0.05` turns an understated reliability
directly into real position size. Kelly's whole fragility is estimate quality, and this was the
estimate.

**Fixed.** After: the 0.95-claiming coin flip is blocked at every n tested; a genuinely calibrated
agent still passes. The decomposition identity `brier = reliability − resolution + uncertainty` is
now a test, because an identity that holds is the cheapest guard against this class returning.

### 2.2 The size ladder inverted — twice — HIGH

`competence.py` states the invariant plainly: *"Monotonic in evidence. More knowledge never means
less size."* It was violated at the first rung and again at the eighth.

**Inversion 1 — promotion costs size.** A 1:1 payoff at 62% confidence:

| n | tier | contracts | % equity |
|---|---|---|---|
| 4 | EXPLORE | 4 | 2.00% |
| **5** | **ESTABLISH** | **1** | **0.50%** |

ESTABLISH's Kelly ceiling is 0.10 and its ramp starts at 0.05, so a full Kelly of 0.12 buys 0.6% of
equity — less than the 2.2% the agent was already permitted while knowing nothing.

**Inversion 2 — measurement removes permission.** An 0.18:1 credit spread at 88%, with reliability
held at an excellent 0.02 throughout:

| n | contracts |
|---|---|
| 5 | 1 |
| **8** | **0** — and zero for every n after |

Crossing `MIN_SAMPLE` swapped the *gate* from the stated probability to the shrunk one. At n=8 the
trust term is still `n/30 = 0.27`, so 88% shrank to 72% — below the payoff's ~85% break-even. The
agent demonstrating **more of the same good calibration** lost the ability to trade the structure.
That is the identical failure the block's own comment describes ("promotion took sizing from 1
contract to 0"), arriving one threshold later.

**Fixed, two changes:**

1. The exploration allocation is a **floor**, not an alternative. Kelly can only raise size above
   it, never below.
2. **The gate reads the stated probability, always.** Two questions, two answers: "is there an edge
   at this payoff" is about the structure; "how much do we bet" is about the track record, and
   fractional Kelly plus the tier cap is the entire answer to it. Letting the record also veto the
   trade charges the same evidence twice, discontinuously. The shrunk view is not discarded — it is
   *reported* ("your record does not support this claim... take it as a test of the view"), which
   is D-009's posture applied where it belongs.

Verified monotonic across four payoff shapes × twelve sample sizes. A genuinely edgeless structure
(70% on 0.18:1) is still refused outright.

**Why the original invariant test missed both:** it measured integer **contracts** at **one**
payoff, where the `contracts < 1 → 1` floor pinned every rung to the same number. The replacement
sweeps the payoff surface and asserts on the fraction.

### 2.3 Two numbers called "your calibration", disagreeing inside one decision — MEDIUM

Within a single decide cycle:

- the **competence tier** was assessed on the ledger-inclusive sample (positions + declined-thesis
  forecasts, which is the whole point of D-052);
- **`size_position`** called `calibration.score()` with no argument — positions only — and shrank
  the agent's confidence against that;
- the **prompt** showed a third figure, also positions-only;
- and **`trdrbot calibration`**, the command you would check this in, showed the positions-only
  view with the eleven pending ledger forecasts invisible.

One number now, computed once and passed everywhere.

---

## 3. The modelled layer: a trader's read

### 3.1 The EV the agent decides on could not be moved by its thesis — HIGH

`ev_after_costs` was `expected_value(...)` at **drift zero** — the market's own distribution — minus
friction. A fairly priced structure is worth roughly nothing under the distribution its own price
implies, so after friction that number is negative **for every candidate, always**, regardless of
what the thesis says.

The journal is full of cycles declining on exactly it. That was never a finding about those trades;
it is what the arithmetic had to return. A thesis engine whose thesis cannot move the number the
decision rests on is decorative.

**Fixed:** one grid with a `drift` parameter (there were two copies of the loop, which is how the
market view and the agent's view came to be computed by different code), and both columns rendered:
`EV after costs, YOUR VIEW ... | at market's own drift ...`, with a note saying the market column is
closer to a measure of what you are paying to trade than a verdict on the trade.

**Live, on the first cycle after the change** — the agent built this table unprompted:

| Candidate | EV at my view | EV at market drift |
|---|---|---|
| 773/778 call debit | +$18 | −$30 |
| Long 772 call | +$114 | −$12 |
| 775/780 call debit | +$25 | −$19 |
| 765/760 bull put | +$14 | −$12 |

and declined all four on the grounds that the edge lived entirely in its own drift assumption. That
is the comparison the column exists to enable, and it could not have been made before.

### 3.2 Two clocks, and the weekend one was the wrong one — MEDIUM

`bs_greeks` and `expected_move` divided volatility-weighted days by 308; the lognormal grid divided
calendar days by 365. Greeks and probabilities for the same position, on different time axes,
rendered side by side in one table.

Unifying them is trivial. Choosing which survives is the part that matters, and **the weekend clock
is wrong here**: OPRA/Alpaca invert Black-Scholes with `T = calendar days / 365`, so a Friday
quote's IV is *already* deflated by the weekend it is about to span — that is the observed "Monday
IV jump" seen from the price side. Discounting it again counts the same adjustment twice, shrinking
the modelled Friday-to-Monday 1-sigma move to **89% of what the option's own price implies**, in
the direction that makes short premium look safer than it is.

D-051's underlying observation is not wrong; it was being applied to a number that already carried
it. The clock was inert in production only because no caller ever passed `start` — which made it a
landmine for the first person to supply the missing argument. `start` is now accepted and ignored,
and that is a test.

`vol_days` survives for the one job it is genuinely right for. Added `implied_vs_realized`, because
implied is annualised over 365 calendar days and realized over 252 sessions: comparing them raw
understates implied by `sqrt(252/365)` = **17%**, every time, in the direction that says do not
sell.

### 3.3 The bootstrap resampled calendar days as if they were sessions — MEDIUM

`bootstrap_factors(closes, days)` drew one daily return per **calendar** day to expiry. On a typical
6-day tenor that is 6 draws where 4 sessions occur: **1.45x too much variance, a ~20% too-wide
distribution.**

`tail_gap` compares that bootstrap directly against the lognormal and warns above 5pp — so a fifth
of every *"the tails disagree, this edge is assumption-dependent"* flag was manufactured by the
units rather than by tail shape. On a system whose distinctive claim is that the gap between the
two estimates is itself the signal, that matters.

---

## 4. Cost — measured, and the two levers pulled

The bill before this pass: **$11.63, of which $10.37 was 18 Opus calls on the decide role, and 81%
of that was input tokens.** A react agent re-sends its accumulated context every turn, so cost grows
super-linearly in turns, and the prefix — tool schemas, system prompt, opening message — is byte
identical on every one of them.

| lever | before | after |
|---|---|---|
| chain payload into context | 79,542 chars | 6,076 chars (**−92%**) |
| MCP tool calls | one `uvx` subprocess **per call** (12.3s / 6 calls, 515 spawns in one run log) | one session per tick (2.75s, **−78%**) |
| prefix re-sent per turn | full price × 7 turns | 17,508 tokens cached, read back at 0.1x |

Prompt caching is the largest single item and was simply absent. A cache breakpoint at the end of
the opening message covers tool schemas, system prompt and prompt together (Anthropic caches the
prefix up to the marked block, and tool definitions sit ahead of the messages). Verified safe across
the fallback chain: `gpt-5-mini` and `gpt-4o-mini` both accept a `cache_control` block and ignore
the key, so an Anthropic outage still falls through.

The ledger had to learn about it too — `usage_metadata.input_tokens` is the **total** and already
includes cached tokens, so a cache read billed at full rate would have made caching look like it
saved nothing. Cached input is now priced at its own multiplier and the share is a column in
`trdrbot usage`; a zero there next to a large `in` means caching is not engaging.

**Measured, same command, adjacent cycles:**

| | calls | input tokens | cost |
|---|---|---|---|
| baseline (old code) | 5.7 avg | ~187k | **$3.46** |
| + compaction, + EV fix | 6 | 155k | $3.12 |
| + prompt caching | 5 | 111k | **$1.32** |

**62% cheaper per decide cycle, with output that got better rather than worse** — §3.1's table is
from the cheapest of the three cycles. Wall clock fell from 5:19 to 1:56, which also buys back
headroom against `tick.watchdog_seconds`.

---

## 5. The rest

| # | defect | severity | state |
|---|---|---|---|
| 11 | `health` read a subsystem's own OUTPUT rows as evidence it had RUN, making three probes tautologies. `interim_scoring` reported "ran 8x, produced 8" off day-one rows for two days and ~250 ticks | MEDIUM | fixed — `interim_run` heartbeat, plus a staleness check: produced-then-stopped no longer reads as healthy |
| 12 | `Ledger.register` dedup matched across `probability_stated`, so a standalone forecast could be swallowed by a pre-registration placeholder and its stated probability never written. D-062's exact symptom, in the one place D-062 did not look | MEDIUM | fixed — has not bitten live only because the agent has always drawn its standalone bands differently |
| 13 | Stray empty `data/wiki/positions/positions/` directory | trivial | removed |
| 14 | `Ledger` constructed twice per decide cycle, and `elfmem history()` still raises `TypeError` upstream (I-5, unchanged in 0.20.0) | LOW | first fixed; second re-verified and still open |

---

## 6. What this pass did **not** settle

Recorded rather than glossed, in the same spirit as notes 006 and 007.

- **The exit-rule engine has still never fired on live data.** Both positions to date closed
  externally, and the book is currently flat. §1.1 fixes the arithmetic that made its rules
  unreachable, but the deterministic path that protects capital when the agent is not looking
  remains unexercised in production. The reachability warning in §1.1 is likewise untested against a
  real `record_position` call.
- **Interim scoring is fixed but unfired** — it needs an open position moving 25% of its net cost,
  and there is no open position. The `interim_run` heartbeat now makes the distinction between
  "idle" and "stalled" legible, which is the part that can be verified today.
- **Attribution has still never written to elfmem.** All `block_outcomes` rows come from the mind
  subsystem; the trading credit path waits on a thesis horizon. Eleven forecasts are now pending,
  four of them resolving 2026-09-01 — early enough to inform a decision, which was D-070's strategic
  finding and is now visible in `trdrbot calibration`.
- **The muse still dates its forecasts at the far horizon.** All five of its ledger entries resolve
  2026-09-03, one day before the deadline. D-070 fixed the horizon guidance in `record_forecast`'s
  docstring only; `muse.py` allows anything inside 7 days and its output clusters at the far end.
  Left alone this pass — it is a prompt change, and prompt changes want their own before/after.
- **ESTABLISH is barely a promotion.** With the floor in place, the tier's Kelly ceiling (0.10,
  ramping from 0.05) keeps size at the 2.2% exploration allocation for essentially every payoff
  tested. The real step-ups are SCALE and MATURE, both of which gate on attribution — which has
  never run. Coherent, but worth naming: the ladder's first rung currently changes nothing but the
  book cap.
- **Kelly still uses `max_profit / max_loss` as the payoff ratio** with `p = P(profitable)`. Those
  are two different events for any structure that can finish partially in the money, and the same
  grid that produces `pop_thesis` could produce a conditional `E[win] / E[loss]` instead. Deferred
  deliberately: it changes what the size tool means, and this pass had already changed the gate.

---

## 7. What to take from the pattern

Four passes now, and the ratio has not moved: **the defects that matter are not logic errors, and
the test suite does not find them.** This pass adds a sharper version of the observation.

Three of the four §1 defects were *silent no-ops in code with passing tests*, and in two cases the
test and the caller disagreed about units or types while each was internally consistent
(§1.2 percents-vs-fractions, §1.3 dict-vs-tuple). A test that constructs its own input from a
literal proves the function is self-consistent; it says nothing about the seam. Both replacements
now derive their input from the real producer — `position_pnl_pct` for the bands, the actual MCP
envelope for the compactor.

And §1.3, §1.4 and §2.2 share one shape worth naming: **a feature that exists, is documented, is
tested, and does nothing.** `health` was built for exactly this class and did not catch any of
them, because it can only see subsystems that write a journal row. The cheap generalisation, and
the one adopted here, is that a component's heartbeat must be a *different* record from its output —
otherwise "ran" and "produced" are the same number and the check is a tautology.

**Verified:** 173 default tests (14 new, one per defect) + 14 contract tests against real Alpaca,
real elfmem 0.20.0 and real LLMs. Two live decide cycles on the fixed code.
