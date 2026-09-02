# Remediation plan: I-75 to I-123

**Forty-nine defects, eleven root causes, six waves.** Every entry in `specs/issues.md` from I-75
to I-123 was reproduced against the real code before it was written down, and none is caught by
the current suite (609 green). This plan says what to fix, in what order, at which seam, and how
each fix is proved.

Companion to [`specs/issues.md`](../specs/issues.md) (the defects),
[`specs/decisions.md`](../specs/decisions.md) (why the code is the way it is), and
[`docs/principles_testing.md`](principles_testing.md) (the four pillars, which govern where every
new test lands).

---

## 0. The whole plan on one page

```
W1  capital protection      I-75 I-76 I-77 I-101 I-102 I-110        the loop is live; these bite this week
W2  one fill, one page      I-81 I-82 I-83 I-85 I-89 I-90           two pages for one fill, and pages that lose their legs
W3  the record              I-78 I-79 I-80 I-84 I-88 I-105 I-117    what the ladder reads is wrong or double
                            I-115 I-116 I-119 I-123
W4  the measurement         I-100 I-107 I-29                        re-measure before trusting; may withdraw a correction
W5  the Coach               I-91..I-99                              autonomy is fine; the bookkeeping under it is not
W6  operator truth          I-86 I-87 I-103 I-104 I-106 I-108       health, config and reports that say the wrong thing
                            I-109 I-111 I-112 I-113 I-114 I-118
                            I-120 I-121 I-122
```

Two rules run through all of it.

**Fix the cause, not the entry.** Forty-nine issues collapse into eleven code changes plus four
decisions. `---` in a claim is one bug in two parsers (I-84, I-123). Two pages claiming one fill is
one missing identity rule wearing four hats (I-81, I-82, I-83, and the crash case I-82 describes).
A calendar day read as a session is one unit error in two callers (I-100, I-107).

**The scaffold is the burn-down chart.** `tests/scaffold_adversarial.py` PASSes when an attack
lands. As each fix ships, its row flips to FAIL, which is the signal to move that scenario into a
pinned regression test and delete the row. "0 failing checks" today means every attack still works;
the goal state is that the file is empty and its scenarios live in `test_regressions.py`,
`test_exit_and_risk.py` and `test_coach.py`.

---

## 1. What is true right now

The loop has been trading throughout the audit, so these numbers move. Measured 2026-09-02:

| | |
|---|---|
| Positions opened today | 3 (NVDA x2, XLE), all carrying the I-78 double-count |
| Calibration rows that are the same stated number twice | 3 pairs, pending resolution |
| `exit_run` heartbeats written outside the session today | 182 of 308 (I-76 feeds on these) |
| Resolved positions that have lost an elfmem block | 3 of 3 (I-115) |
| Live bootstrap inflation | k = 1.30 / 1.30 / 1.25, fitted by the harness I-100 shows is mismatched |
| Wiki-guard refusals so far | 0 (I-121 is armed, not yet fired) |

Two of these are accumulating damage rather than sitting still: every trade adds a double-counted
calibration pair (I-78), and every muse gate and every `simulate_experiments` grid runs through an
over-wide bootstrap (I-100). They set the order of W3 and W4.

---

## 2. Eleven root causes

| # | Root cause | Issues | Wave |
|---|---|---|---|
| R1 | Absence becomes a number instead of a refusal | I-75, I-104 | W1, W6 |
| R2 | A debounce window counts repeats of one observation | I-76, I-77 | W1 |
| R3 | One idempotency key for a whole cycle, and a lock that expires mid-tick | I-101, I-102, I-110 | W1 |
| R4 | A broker fill has no identity both writers agree on | I-81, I-82, I-83, I-85, I-90 | W2 |
| R5 | One stated number, two owners | I-78, I-88, I-105 | W3 |
| R6 | A date is not a session | I-79, I-106 | W3 |
| R7 | A frontmatter fence is matched as a substring | I-84, I-123 | W3 |
| R8 | Terminal states are scored as if they were trades | I-80, I-117 | W3 |
| R9 | One text stored twice, and a count that double-counts it | I-115, I-116, I-119, I-118 | W3 |
| R10 | Calendar days drawn as sessions | I-100, I-107 | W4 |
| R11 | A reader and a writer disagree about a field that was never written | I-91..I-99, I-108, I-120, I-121, I-122 | W5, W6 |

Everything below is organised by root cause. The issue numbers are the audit trail; the code
changes are the unit of work.

---

## 3. Wave 1 - capital protection

The loop is running unattended. These five can lose exposure or money before anything else is
touched, and every one of them is small.

### W1.1 · An unreadable account must not become $100,000 (R1, I-75)

**Seam.** `analytics.snapshot` leaves `account={}` on a failed `get_account_info` and prints;
`tick._run_tick` reads `equity_now = snap.equity or 100000.0` in two places.

**Fix.** The I-55 shape, applied one field over. Add `Snapshot.account_readable` defaulting False,
set only where the read succeeds, and write a `health.degraded` row on failure exactly as the
positions, orders and clock reads one line either side already do. Then:

- `size_position` refuses when equity is unknown ("the account could not be read this tick, so
  there is no bankroll to size against") rather than sizing against a constant.
- the ladder holds at the last journalled posture instead of recomputing drawdown against a
  fabricated peak.
- `idle.decide` treats unknown equity as "no deployable room", which sends it to review, not hunt.

**Test.** `test_exit_and_risk.py`, PILLAR-3: an unreadable account produces zero sized contracts
and a `degraded` row, and the ladder's tier is unchanged from the previous tick. Paired with the
opposite direction (rule 4): a readable account at the same equity still sizes normally.

**Risk.** Low. It converts a silent wrong number into a loud refusal on a path that already has a
refusal vocabulary.

### W1.2 · The debounce must count observations, not ticks (R2, I-76)

**Seam.** `exit_rules.evaluate` appends to `pos.exit_state[key]` on every tick; `run()` gates only
the broker call on `market_open`.

**Fix.** While the market is closed, evaluate but do not mutate the history of any signal whose
value cannot change - which is the mark. Detection stays unaffected (I-56's fix must survive: the
calendar rules still fire off-hours and wait for the session to submit), and the window is no
longer pre-satisfied at the open. State the rule in the constant's docstring: *N-of-M means N of
the last M observations, and a frozen mark is one observation repeated.*

**Test.** `test_exit_and_risk.py`, PILLAR-3, as a price path: 15:59 wide print, six overnight
ticks, healthy open print, one wide print at 09:35 - holds. Its opposite: two genuinely separate
in-session wide prints still close.

**Risk.** Low-medium. It makes stops slower to fire across a session boundary by design. The
magnitude override and W1.3's corroboration are what carry a real overnight gap.

### W1.3 · Corroboration belongs on every mark breach, not only the decisive one (R2, I-77)

**Seam.** `evaluate` fires on `decisive or sum(history) >= NEEDED`; only the `decisive` branch
consults `_mark_corroborated`.

**Fix.** A mark breach closes when the underlying corroborates it. When the underlying cannot be
judged (no previous close, unpriced, a legacy row with no entry greeks) the existing N-of-M
debounce is the fallback - `None` still debounces, which is the conservative direction and is
already the documented contract. Count the debounce path into `mark_breach_suppressed` and
`mark_breach_confirmed` too, or the tuning data those counters exist to collect stays one-sided
(and I-65's tuning question stays unanswerable).

**Decision it forces.** `CORROBORATION_FRACTION = 0.25` was declared a starting point to be tuned
from the journal, and I-65 already says it is nearly open on low-IV names. Widening its remit
without tuning it is a real change to how quickly capital is protected. **Do not tune it in this
commit** - ship the remit change, then tune from `exit_run` rows, per I-65.

**Test.** PILLAR-3 path pair: an artifact print on an unmoved underlying never closes; a
corroborated gap closes on the first print.

**Risk.** Medium - this is the capital-protection path. Mutation-verify both directions.

### W1.4 · One order, one id (R3, I-101)

**Seam.** `tool_guard._wrap` computes `ids.client_order_id(batch)` once per tool and stamps it on
every call; `ids.client_order_id(batch, leg=0)` declares a disambiguator nobody passes.

**Fix.** Derive the id from the order's own content, not from a counter:
`client_order_id(batch, legs)` hashing the batch plus the sorted `(symbol, side, qty)` triples.

- Stable across a crash-retry of the same intent, so INV-18 and FM-24 hold unchanged.
- Distinct for a genuinely different order in the same cycle, so close-A-then-open-B executes.
- Two *identical* orders in one cycle still collapse to one, which is the safe direction and is
  what "at most one action per situation" already says.

Separately: journal `client_order_id_enforced` only for the tools in `_ID_BEARING`. The live
2026-08-27 row records an enforced id on `close_all_positions`, which takes no such field and was
never wrapped - a record of something that never happened.

**Test.** `test_regressions.py`: two different orders in one batch get two ids; the same order
resubmitted gets the same id; a non-id-bearing tool is journalled without one.

**Risk.** Low, and it removes a live inability to act rather than adding one.

### W1.5 · A lock that outlives the tick it guards (R3, I-102, I-110)

**Fix.** Two lines. `tick_lock`'s `stale_after` must be at least the outer watchdog
(`watchdog_seconds * OUTER_WATCHDOG_FACTOR`), passed by the caller rather than hardcoded at 600;
and `cli._tick` - the `run.sh` path - gets the same `asyncio.wait_for` bound the run loop has.

**Test.** `test_chassis.py`: a live holder is not broken before the outer watchdog could have
fired; `trdrbot tick` returns non-zero on a hung tick rather than hanging.

**Risk.** Low. Note the interaction: with W1.5 alone a genuinely wedged process holds the lock
longer, which is exactly why W1.5 ships with the watchdog, not without it.

---

## 4. Wave 2 - one fill, one page

### W2.1 · Give a broker fill an identity (R4, I-81, I-82, I-83)

This is the largest single change in the plan and it closes four scenarios at once.

**The missing rule.** Nothing says what makes two observations "the same position". `reconcile`
claims legs from ACTIVE pages only; `record_position` creates a page unconditionally; neither
consults working orders. So a slow close (I-81), a crash between order and record (I-82) and a
retried tool call (I-83) all end with two pages for one fill, double-counted book risk, and two
scored resolutions.

**Fix.** The sorted leg-set is the identity of a fill.

1. `_adopt_orphans` skips a symbol that has a working order in `snap.open_orders`, and a symbol
   claimed by a page that reached a terminal state within the last few ticks. A close in flight is
   not an orphan.
2. `record_position` looks up an ACTIVE page with the same leg-set key. If one exists it is
   **updated in place** - thesis, exit rules, sizing, provenance promoted from `unknown` to
   `agent` - rather than a sibling being created. The `leg_overlap` warning already identifies the
   page; it should adopt it instead of narrating it.
3. Genuine leg sharing between two different structures (D-111's case) is unchanged: different
   leg-sets, different pages, and the existing warning still fires.

**Test.** `test_regressions.py`, three cases derived from the scaffold's X4, X15 and X16, plus the
D-111 control that two different structures sharing one leg stay two positions.

**Risk.** Medium. It touches the path that writes exposure. The scaffold rows are the acceptance
test: X4, X15 and X16 must all flip to FAIL.

### W2.2 · A leg symbol is uppercase OCC or it is nothing (R4, I-85)

**Fix.** `record_position` normalises `str(symbol).strip().upper()` at the boundary. `parse_occ`
already upper-cases; the matchers in `reconcile` and `exit_rules` do not, which is the whole
defect. One line, at the one place model-authored symbols enter the system.

**Test.** `test_regressions.py`: a lowercase symbol records, reconciles and is watched.

### W2.3 · Derive the expiry, warn on disagreement (I-89)

**Fix.** When `expiry` is absent, derive it from the OCC legs (the same `parse_occ` the greeks
already use) and say so in the reply; when it is present and disagrees with the legs, warn. Today
a missing expiry silently disarms the gamma-wall time stop and only `blind_signals` notices.

### W2.4 · Match the sizing stash on the structure, not just the count (I-90)

**Fix.** `SharedContext.sizing` records the structure key it was computed for; `record_position`
uses it only when the recorded legs match that key, and journals `sizing_mismatch` otherwise.
Low severity because `_reprice_max_loss` repairs it at fill, but until the fill the caps are
denominated in the wrong structure's risk.

---

## 5. Wave 3 - the record

### W3.1 · One stated number, one owner (R5, I-78)

**The conflict.** `record_position` writes the agent's `confidence` into *both* the calibration
store (resolved at close on P&L) and the ledger's traded row (resolved at horizon on the band).
`CalibrationStore.score` concatenates the two lists. One number, two events, n=2 - and the two can
resolve in opposite directions, which the scaffold demonstrates.

**Recommendation (a decision, see §8).** The **position row owns calibration**. `confidence` is
documented to the model as "your honest probability that this position closes profitable", and the
tool docstring is what the model reads, so that is the claim it made. The ledger's traded row keeps
everything else it does - the trial count N, gate regret, and the band that attribution scores -
but reverts to `probability_stated=False`.

**This deliberately revises D-105.** D-105's symptom was that a traded thesis never reached
calibration; its premise was incomplete, because the same confidence was already reaching
calibration through the position row. The fix stands, the mechanism changes. The scaffold check in
`scaffold_whole_system.py` S1 that asserts `matured[0].probability_stated` must be updated as an
explicit, explained step (testing non-negotiable #1), and D-105 amended in `decisions.md` rather
than silently contradicted.

**Test.** `test_regressions.py`, PILLAR-4: one trade contributes exactly one forecast to
`score()`, and `n` after a closed trade increases by one.

### W3.2 · A horizon passes when its session closes (R6, I-79)

**Fix.** `Entry.matured()` and `attribution._horizon_passed` become "the horizon date is behind us,
or it is today and the session has closed" - `market_today() > horizon`, or `== horizon` past
16:00 ET. One helper in `ids.py` (`session_closed_on(date)`), two callers, so the two halves of
resolution cannot drift again.

Already-resolved rows stay as they are: the ledger is append-only and re-scoring would rewrite the
record, which is the same call D-107 made.

**Watch for.** This interacts with W6.4 (I-106): a 1-3 day vol forecast still cannot resolve, for
a different reason.

### W3.3 · Split frontmatter on the fence, not the substring (R7, I-84, I-123)

**Fix.** One helper in `store.py` - `split_frontmatter(text)` matching `^---$` as a line - used by
`positions._parse` and `wiki.read`. Both currently do `text.split("---", 2)`, so a model-written
claim containing ` --- ` truncates every later key, and a claim line starting `---` makes the page
unparseable and the position vanish.

**Then repair.** A one-off scan for pages whose parsed field count is short of what is on disk
(see §7). This is the one defect that destroys data on disk: `attribution.run` marks a truncated
page `unscoreable` and saves it back, taking the claim, horizon and bands with it.

**Test.** `test_wiki_store.py`: a position and a wiki concept whose string values contain ` --- `
and a leading `---` line both round-trip every field.

### W3.4 · Terminal is not traded (R8, I-80, I-117)

**I-80.** `attribution.pending()` excludes `abandoned`. There was no expression to judge, so
there is no verdict to reach - and today a never-filled order is scored, credits memory at signal
0.1 or 0.65, and counts toward the attributable rate that gates SCALE and MATURE.

**I-117.** `attribution.run` credits first and saves the verdict on success, and `housekeeping`
calls it through `learn.guarded` like every other learning stage. Today a sqlite lock during credit
leaves the position permanently attributed with zero credit, no journal row, no heartbeat, and
takes the rest of housekeeping (forecast resolution, the sweep, the Coach pulse, dream) down with
it.

**Test.** PILLAR-4: an abandoned position is never attributed; a memory failure during credit
leaves the position attributable next run and housekeeping completes.

### W3.5 · The thesis is stored once (R9, I-115, I-116, I-119)

**I-115.** `remember_thesis` stores `pos.thesis`; `predict` stores `"Prediction: {pos.thesis}..."`.
elfmem archives one as a near-duplicate at cosine >= 0.95, with no audit row, on every position -
live on 3 of 3 resolved positions. Give the prediction distinct, structured text (the
`thesis_claim`, the horizon and the position id - which is also more useful to a human reading the
mind) and have `remember_thesis` verify the id it returns is active.

**I-116.** `applied = out.blocks_updated`, not `+ out.blocks_penalized`, which elfmem computes from
the same ids. Today the negative-verdict path - the one where blocks are actually lost - never
triggers the D-057 consolidate-and-retry and journals full credit.

**I-119.** `learn.on_fill` saves the page after `remember_thesis`, before `predict`, and a mind id
that is no longer active is dropped from `minds.json` rather than retried forever.

**Not repairable.** The blocks already archived cannot be un-archived (elfmem has no such call -
the I-2 precedent: watch, no action possible). Record that in the issue when it is closed.

### W3.6 · The ledger's dedup must not restate a claim (R5, I-105, I-88)

**I-105.** `register`'s dedup returns the prior row without updating its probability, so the muse
can promote a row to stated at a probability from a different run, while it still carries
`rejected_by` - counted by `gate_regret` as a refusal and an admission at once. Fix: the dedup
updates the returned row's probability, and refuses to return a row across a stated/unstated
boundary once it has been judged.

**I-88.** `mark_traded` walks backwards matching `(underlying, horizon, not traded)`, ignoring kind
and band, so a standalone forecast recorded in the same cycle is marked traded instead.
`simulate_experiments` already knows which entry it registered - pass its id through
`SharedContext` and mark that row by id.

---

## 6. Wave 4 - the measurement

### W4.1 · Re-fit the bootstrap inflation, and be willing to withdraw it (R10, I-100)

This is the only item whose outcome is not known in advance, and it gates the others in this wave.

**The defect.** `fit_band_inflation` draws `round(h * 252/365)` returns - treating `h` as calendar
days - and scores the result against `closes[i + h]`, which on a daily-bar cache is `h` sessions
ahead. The mismatch alone predicts a "needed" inflation of `sqrt(h/draws)` = 1.22/1.29/1.20. On
perfectly iid data where the true k is 1.0, the function chooses 1.15/1.30/1.30.

**Why it is not just a wrong constant.** The holdout that validated the artifact
(Brier 0.216 raw -> 0.202 fitted) runs through the same function, so it validated the fit against
the harness's own mismatch rather than against the tape.

**Sequence.**

1. **Neutralise without touching state.** `data/state/**` is append-only and sacred, so the
   artifact is not hand-edited. Instead stamp a `harness` version into the artifact and have
   `band_inflation` return 1.0 for any artifact fitted by the pre-fix harness. The code already
   fails safe to 1.0 when no fit exists, so this is the documented degraded path, not a new one.
2. **Fix the units.** Inside the fit, `h` is sessions throughout (`draws = h`). At the lookup,
   `band_inflation(days)` receives *calendar* days from the muse and `simulate_experiments`, so it
   converts to sessions before choosing the nearest key. Record the unit in the artifact.
3. **Re-fit and let the holdout veto.** `trdrbot modelcal fit` writes the artifact properly. If no
   k above 1.0 survives the holdout, the correction is **withdrawn** and I-29 returns to
   "measured, unexplained, uncorrected" - which is an honest outcome, not a failure.
4. **Re-open I-29.** Its measurement (notes/017) describes the same 3/5/10 horizon scoring. Whether
   it shares the draw-count mismatch is not recoverable from the repo, so the 15-18pp finding
   should be re-measured with the corrected harness before it is cited again.

**Test.** `test_regressions.py`, PILLAR-4 (fitted numbers are holdout-vetoed): on synthetic iid
data with a known true k of 1.0, the fit returns 1.0 within one grid step.

### W4.2 · Discovery's five days are calendar days (R10, I-107)

`discovery.py` passes 5 trading days to `bootstrap_factors`, which reads calendar days and converts
to 3 draws, while the synth prompt says "over the next 5 trading days" and tells the model not to
contradict the block. D-074's conversion fixed `simulate_experiments` and never reached this caller.
One-line fix; the test is a units assertion at the seam, derived from the real producer.

---

## 7. Wave 5 - the Coach

The Coach's autonomy is not the problem and must not be gated - the bookkeeping under it is. Nine
issues, four small commits.

| Commit | Issues | Change |
|---|---|---|
| C1 pairing integrity | I-91, I-98 | Record `incumbent_fp` at open; close as `operator_override` when *either* arm's fingerprint moves. Compare normalised text in `validate_prompt` so a whitespace echo is not a challenger. |
| C2 crash repair everywhere | I-92, I-96, I-97 | `reconcile` at the top of `pulse` (it is cheap and idempotent), so the tick path gets the repair the housekeeping path has. Keep a corrupt state file instead of overwriting it in the same pulse. A wedged `exp_id` with no challenger closes as `operator_override`; `pulse` never reports a promotion `_promote` refused. |
| C3 the operator's controls | I-93, I-94 | Decide `pinned` (§8). Make `enabled: false` mean "no new experiments", not "revert production to the seed" - today it silently discards a promotion while provenance, the report and the CLI all name the promoted variant. |
| C4 the mutator can see | I-95, I-99 | Write the rationale onto the close row the graveyard reads. Key the rejection digest through `ledger.gate_of`, the classifier D-104 already built, so it aggregates. |

---

## 8. Wave 6 - operator truth

Grouped by how they are proved, because none of them changes trading behaviour.

**Health and reporting say what is true.** `sizing.bypassed` counts only orders that open exposure,
reusing `tick._opens_a_position` rather than a second definition (I-108). `housekeeping_dream`
reports "nothing pending" separately from "consolidated" - today every half-hourly log line says
`consolidation ok` for a dream that has not run since 09-01 (I-120). `recent_lessons` splits on the
`## pos_` marker the writer actually emits, so a heading inside a thesis cannot evict a real lesson
(I-122). The wiki guard gets a recovery path - compare schema headings only, and archive *after* a
successful write, not before (I-121).

**Config fails at startup, not at trade time.** Touch every config property once in `config.load()`
and in `doctor`, and make the run loop stop on a CONFIG- or BUG-classified failure that repeats
rather than looping on it forever with rc 0 (I-104). Classify provider 400s as CONFIG so a billing
problem stops dead-lettering blameless observations, and stop mapping `KeyError` to PERMANENT
inside a block that never parses an item (I-103).

**Units and freshness.** Refuse a `stop_loss_pct` or `profit_target_pct` whose magnitude is under 1
- a fraction where a percent was meant, in a call whose neighbouring argument is a 0-1 fraction
(I-87). Measure close-cache staleness from the last *bar*, not the fetch date (I-109). Refuse a
`realized_vol` forecast at a horizon shorter than the resolver's own sample requirement, or resolve
on the returns available and record the count - today the tool recommends 1-3 days and nothing
inside 7 can ever resolve (I-106).

**Small and self-contained.** The high-water mark anchors on realised equity rather than intraday
marks, so one wide print cannot latch the drawdown brake (I-86). `--closed-interval` honours the
same floor as `--interval` (I-111). `_coerce` treats a string as absent rather than iterating it
into characters (I-112). The muse reads `competence.MAX_HORIZON_DAYS` instead of its own literal 10
(I-113). `site_export` stamps `generated_at` outside the hashed payload so publish's no-op branch
can fire (I-114). `CREDITED_FRAMES` and the adapter docstring are made to agree (I-118, and see §9).

---

## 9. Data repair

Three defects have already written bad data. State files are append-only and sacred, so repair is
by forward-writing or by a recorded gap, never by hand-editing.

| What | State | Action |
|---|---|---|
| Double-counted calibration pairs (I-78) | 3 pairs live, pending resolution | Do **not** rewrite. Once W3.1 ships, `score()` counts one per trade going forward; the existing pairs stay in the record and the amendment says so, as D-107 did for its early resolutions. |
| Truncated position pages (I-84) | Scan needed | One-off read-only scan comparing on-disk key count against parsed field count. Any page found truncated has already lost its claim to `attribution`'s save-back; record the loss per position rather than reconstructing a thesis. |
| Archived elfmem blocks (I-115) | 3 of 3 resolved positions | Not repairable - elfmem has no un-archive. Record in the issue on close, the I-2 precedent. |
| Bootstrap artifact (I-100) | Live, distorting | Neutralised by the harness stamp in W4.1 step 1, then rewritten by `trdrbot modelcal fit`. Never hand-edited. |
| Stray `self/*` tags on block 7b36fdbb (I-1, I-118) | Live in TASK on two SPY pages | Retire-and-replace after its horizon, per I-1's existing plan. |

---

## 10. Four decisions that are not the implementer's to make

Each has a recommendation; none should be settled inside a commit that also changes behaviour.

1. **Who owns a traded thesis's calibration row (I-78)?** *Recommended:* the position row, because
   `confidence` is documented to the model as P(closes profitable). The alternative - the ledger's
   band claim at the horizon - is defensible and arguably a better test of judgement, but it is not
   the claim the tool asks for. Either way D-105 is amended explicitly.
2. **Does `pinned` come back (I-94)?** *Recommended:* restore it, because the config comment
   promises a demo-day freeze and `paused` closes any open experiment while a pin should not. The
   cheaper answer is to delete the comment. What must not stand is a documented control that is
   silently dropped from the state file.
3. **What does `enabled: false` mean (I-93)?** *Recommended:* "run no experiments, keep the
   promoted incumbent". Today it reverts production to the seed while every reader says otherwise,
   which is the provenance failure `prompts.py` calls worse than none.
4. **Is the TASK frame credited (I-118)?** The adapter docstring says no, `CREDITED_FRAMES` says
   yes, and elfmem's 0.0 "never scored" sentinel makes it credit at the 0.25 floor.
   *Recommended:* stop crediting TASK, because the observed effect is a foreign underlying's thesis
   taking credit from every SPY verdict - the cross-underlying credit D-072 exists to prevent.

---

## 11. How each fix is proved

The project's own rules, restated because this plan produces a lot of commits:

1. **Failing test first.** Write or run the test that fails for the reported reason, fix, show it
   pass. Every issue here already carries a reproduction script - that is the failing test's
   starting point, not a substitute for it.
2. **Mutation-verified.** A test ships only with proof it fails when the fix is reverted. Every
   I-3x/I-4x entry in `issues.md` carries that sentence because the revert was actually performed.
3. **Balanced pressure.** Any test pushing toward an action ships with its opposite direction, or
   is expressed as an invariant. W1.2 and W1.3 are the ones this matters most for: it is easy to
   fix "closes too eagerly" into "never closes".
4. **Derive fixture inputs from the real producer.** Two capabilities were dead in production while
   their tests passed because the test built its own input. The scaffold worlds copy real return
   histories and the real wiki for exactly this reason.
5. **Dates come from `conftest.days_out(n)`.** I-74 already tracks 18 tests that will fail within
   30 days on hardcoded dates. Do not add to that pile; run `uv run python scripts/suite_at.py 30`
   before each commit.
6. **Gate the commit on captured exit codes.** `uv run pytest | tail && git commit` ships red -
   capture pytest's and ruff's exit status and gate on both.
7. **Restart the live loop after a code commit.** A long-lived `trdrbot run` holds config and every
   module in memory from the moment it started (D-108); `trdrbot health` compares the live
   process's git sha against HEAD and will say so.
8. **The issue is removed by the commit that fixes it**, linking the D-number, per the ledger's own
   rule.

---

## 12. Deliberately not doing

- **No approval gates.** Nothing here adds a human checkpoint to the Coach or to the trading loop.
  The fixes are observability and bookkeeping; autonomy bounded by construction stays the design.
- **No new guardrails.** D-009 stands. W1.1 refuses to *size* on unknown equity, which is the
  sizer declining to answer a question it has no input for, not a policy blocking a decision.
- **No re-scoring of resolved rows.** The ledger and the calibration store are append-only. Every
  fix here changes what happens next; the record of what happened stays.
- **No tuning inside a fix.** `CORROBORATION_FRACTION` (I-65), `SEED_SHARE` (I-70) and the shrink
  target (I-69) are all open, all unfitted, and all tempting to adjust while nearby code is open.
  They are separate decisions with their own measurements.

---

## 13. Checklist

- [ ] W1 lands and the loop is restarted; scaffold X1, X2, X3 flip to FAIL
- [ ] W2 lands; X4, X9, X13, X14, X15, X16 flip
- [ ] W3 lands; X5, X6, X7, X8, X10 flip; D-105 amended in `decisions.md`
- [ ] W4: harness fixed, re-fitted, holdout consulted, I-29 re-measured or the correction withdrawn
- [ ] W5: nine Coach issues closed across four commits; `coach_repro_1..9` all flip
- [ ] W6: the remaining sixteen; `chassis_repro_*`, `sources_repro_*`, `memory_repro_*` flip
- [ ] X11, X12, X17 flip (X12 is a control and must keep passing as a control, not as an attack)
- [ ] `tests/scaffold_adversarial.py` is empty and its scenarios are pinned regression tests
- [ ] `uv run pytest` green, `uv run python scripts/suite_at.py 30` green, ruff clean
- [ ] `specs/issues.md` carries no OPEN entry from I-75 to I-123 without a D-number
- [ ] The reproduction scripts move into the repo or are deliberately discarded
