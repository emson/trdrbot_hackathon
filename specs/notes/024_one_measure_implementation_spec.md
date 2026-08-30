# 024 · Phase 4+5 implementation spec - One Measure (LLM-executable)

The executable form of [023_gauntlet_response_design.md](023_gauntlet_response_design.md):
four rules (R1-R4), two features (F1-F2), the memory/gauge additions, the pillar-eval
consolidation, and the golden decision set. Written for an LLM implementer. Every claim below
was verified against the actual source on 2026-08-30 - **re-read the named region before
editing, and trust the file over this document if they have drifted.** Measured findings cited
as I-4x live in [issues.md](../issues.md); the scenarios cited as G-x are
`tests/scaffold_trader_gauntlet.py` sections.

The one-line intent, to hold while implementing anything here: **every probability, EV and
payoff ratio feeding one gate/size decision is computed under one declared measure (drift,
vol), friction included - and a seam that loses any part of the measure refuses rather than
substitutes.**

---

## A. Global rules (read first, apply to every work unit)

Rules 1-7 of [020 §A](020_phase1_implementation.md) apply verbatim: one WU = one commit
(`WU-4.x:` prefix); suite green before and after, summary line pasted into the commit message;
every bug-fix WU carries its failing-then-passing regression test named for the bug with the
incident in its docstring; test at the seam with producer-derived inputs, fake only at the
adapter boundary; preserve every guard and incident-carrying comment you touch (update a
comment your change falsifies, in the same WU); verify APIs by running them; state files are
sacred.

Additions for this phase:

8. **The entropy line.** Every WU's commit message ends with `Entropy:` naming what the WU
   deleted, avoided adding, or consolidated (or `none`, honestly). This phase adds exactly TWO
   new tunable constants (`CORROBORATION_FRACTION`, `IMPLICIT_TIME_STOP_DAYS`); any WU that
   wants a third must first justify it against a journal-derived measurement, in the constant's
   docstring, or not add it.
9. **The measure check.** Any WU touching `simulate`, `payoff_ratio`, `pop_*`, `ev_*`,
   `kelly_fraction` or `size_position` re-runs
   `uv run python tests/scaffold_trader_gauntlet.py` and pastes the VERDICT block into the
   commit message. Zero invariant violations, always.
10. **Behaviour changed on purpose = scaffold row updated in the same WU**, with a one-line
    `# CHANGED (WU-4.x):` comment above the row. Never silently re-baseline.
11. **Issue closure discipline**: the commit that lands a fix strikes its I-4x entry in
    `specs/issues.md` (`~~...~~ **FIXED <date> (WU-4.x).** <one-line what changed> Verified by
    reverting the fix and watching the regression test fail.`) - and actually perform that
    revert-verify before writing the sentence. Record a `D-0xx` decision entry per landed WU
    cluster (one per phase-4 wave is fine), in the existing decisions.md voice.
12. **Prompt surface**: the three tool docstrings ARE prompts (fingerprinted as
    `tool.simulate_experiments` etc. via `prompts.py`). Docstring edits are therefore prompt
    changes - deliberate, minimal, and they must keep describing the real signature.

---

## B. Design → work-unit map

| rule | closes | WU | files |
|---|---|---|---|
| R2.3 conditional-b / unbounded profit | frees long calls (G6) | 4.1 | sizing.py |
| R2.1/R2.2 tool refuses, seam strict | I-40 | 4.2 | local_tools.py, tick.py |
| R4.1 breakeven_vol confession + grid | I-44 | 4.3 | optmath.py, experiments.py |
| R4.2 unobservable-mark warning | I-45 | 4.4 | local_tools.py |
| R1 thesis vol_view = decision measure | I-41 | 4.5 | experiments.py, local_tools.py, positions.py, llm.py |
| R3 corroborated decisiveness | I-42 | 4.6 | exit_rules.py |
| F1 implicit time stop | slow bleed (G4/P5) | 4.7 | exit_rules.py, local_tools.py |
| F2 vega-weighted IV + skew span | I-43 | 4.8 | optmath.py, experiments.py |
| memory: lesson + wiki page | - | 4.9 | lessons.py, data/wiki/technique/ |
| gauges + report | - | 4.10 | tick.py, coach_pkg/gauges.py, report.py |
| pillar consolidation + docs | - | 4.11 | tests/, specs/, README.md |
| golden decision set | - | 5.1-5.3 | evals/, cli.py |

Dependency order: 4.1 → 4.2 (same seam, sequential). 4.3, 4.4 independent (parallel-safe).
4.5 before 4.8 (both edit `simulate`; sequential). 4.6, 4.7 independent of 4.5. 4.9-4.11
after the code WUs they describe. Phase 5 needs only 4.5 landed.

---

## C. Phase 4 work units

### WU-4.1 - Kelly refuses unbounded LOSS only; conditional b carries unbounded profit

**Files:** `src/trdrbot/sizing.py` (`kelly_fraction` ~line 96, `size_position` refusal block
~line 148, `payoff` explain-string ~line 293).

**Current, verified:** `size_position` refuses when `max_loss is None or max_profit is None`
("unbounded max loss or profit"). A long ATM call - loss bounded at the debit, conditional
payoff finite (G6 measured 1.96) - is unsizeable at any edge. `kelly_fraction` guards
`if max_loss >= 0 or max_profit <= 0: return None`.

**Change:**
- `kelly_fraction(prob, max_profit, max_loss, *, payoff_ratio=None)`: accept
  `max_profit: float | None`. Guard becomes: `max_loss` non-negative → None;
  `payoff_ratio` given → use it regardless of `max_profit`; else `max_profit` None or ≤ 0 →
  None. Docstring: unbounded profit with a conditional ratio is well-defined - E[win|win] is
  finite even when max profit is not; the refusal is for unbounded LOSS, where the worst case
  Kelly divides by does not exist.
- `size_position`: split the refusal. `max_loss is None` → refuse (current text, corrected to
  say "unbounded max loss"). `max_profit is None and payoff_ratio is None` → refuse with its
  own sentence ("unbounded max profit with no simulated conditional payoff - simulate the
  structure so its conditional win is known"). Otherwise proceed; the `payoff` explain-string's
  max/max branch must guard `max_profit is None` (it cannot occur on that branch after this
  change - assert, don't format None).

**Tests (write failing first):** in `tests/test_regressions.py`, new section
`# --- PILLAR-2: one measure / seams refuse (WU-4.1..4.2)`:
- `test_long_call_sizes_on_conditional_ratio_despite_unbounded_profit` - build the long-call
  legs fair-priced via `optmath._lognormal_grid` (the gauntlet's `fair_price` pattern),
  compute `payoff_ratio` directly, call `sizing.size_position` with `max_profit=None` and that
  ratio at a stated prob above the gate → contracts ≥ 1. Incident: G6 / note 023 R2.3.
- `test_unbounded_loss_still_refused_with_or_without_ratio` - short strangle: `max_loss=None`
  refused even with a ratio passed.

**Scaffold:** update G6 long-call rows: sizing WITH `pr_lc[2]` now sizes (`# CHANGED
(WU-4.1)`); keep the strangle refusal row unchanged.

**Entropy:** deletes a special case (the unbounded-profit refusal); adds no constant.

### WU-4.2 - The sizing tool refuses at every lost seam (I-40)

**Files:** `src/trdrbot/local_tools.py` (`_matching_payoff_ratio` lines 525-554,
`build_size_position` / inner `size_position` lines 557-640, `SimStructure` line 38),
`src/trdrbot/tick.py` (tool construction ~line 627).

**Current, verified:** `_matching_payoff_ratio` returns `float | None`, where None conflates
four states: no simulation ran; no unique match (name unknown + rr ambiguous/absent); matched
structure whose own `payoff_ratio` is None (friction-eaten or one-sided per
`optmath.MIN_CONDITIONAL_MASS`); and legitimate direct-caller absence. `sizing.size_position`
then falls back to frictionless max/max - measured flipping a refusal (gate 79%) into 224
contracts at the 5% cap (gate 22%), G6.

**Change:**
- Replace `_matching_payoff_ratio` with `_match_structure(shared, max_profit, max_loss, name)
  -> SimStructure | str` - a str is a refusal reason. Reasons, each naming the repair:
  - no `shared.structures`: "size_position requires simulate_experiments this cycle - the
    conditional payoff and friction exist only there. Simulate first." (This also covers the
    D-038 chain→order→record shortcut, one gate earlier.)
  - name given but unknown / no unique rr match: "no simulated structure matches - pass
    structure_name exactly as rendered: <list of `s.name`>."
  - matched but `st.payoff_ratio is None`: "REFUSED: '<name>' has no usable conditional payoff
    after friction - its expected win is eaten by costs, or it wins/loses too one-sidedly to
    condition on (see the comparison). There is no payoff to bet on; not trading is the
    answer." **This is the sentence D-079 promised and the seam dropped.**
- In the tool, a str result returns immediately as the tool output (a refusal string is the
  established guard convention - see tool_guard/D-091 note in README). A `SimStructure` result
  passes `st.payoff_ratio` to `sizing.size_position` - production now never passes None.
- `sizing.size_position`'s internal max/max fallback REMAINS for direct callers and tests;
  update its docstring: "production's tool layer refuses before this fallback can run
  (WU-4.2); it exists for direct callers and is stated in explain()".
- **Journal the outcome** (feeds the 4.10 gauge): `build_size_position` gains a
  `journal: Journal | None = None` param; after each call append
  `journal.append("sizing", underlying=..., result=<"sized"|"no_position"|"refused_no_sim"|
  "refused_no_match"|"refused_no_payoff">, contracts=d.contracts if sized else 0,
  structure=structure_name)`. Wire `journal` at the tick.py construction site (in scope at
  line 424). Guard with try/except like the ledger calls - a journal failure never blocks a
  decision.
- Tool docstring (= prompt): add one paragraph - simulate first; name the structure; a refusal
  here is a real answer, not an error to route around.

**Tests:** producer-derived seam tests (build the `SharedContext` by CALLING
`build_simulate_experiments`'s inner function with a real candidate list - never hand-stuff
`shared.structures`):
- `test_sizing_tool_refuses_without_simulation` (empty shared → refusal mentions
  simulate_experiments).
- `test_sizing_tool_refuses_ambiguous_structure` (two candidates, same rr, no name).
- `test_sizing_tool_refuses_friction_eaten_payoff` - the G6 narrow condor
  (99/100-101/102 fair-priced at IV 25%/7d) with the flat 10% friction: simulate, then size at
  stated 0.70 → refusal, zero contracts. Incident line: I-40, 224 contracts.
- `test_sizing_tool_sizes_named_match` (happy path, ratio equals the simulate metric's).

**Scaffold:** G6 fallback rows: the "WITHOUT (fallback)" measurement now demonstrates the
*function-level* fallback only; add a row driving the TOOL and expecting refusal
(`# CHANGED (WU-4.2)`).

**Issue:** strike I-40 (revert-verify first). **Entropy:** four conflated None-states become
named refusals; no new tunables; one new journal row kind.

### WU-4.3 - breakeven_vol confesses its searched range and extends it (I-44)

**Files:** `src/trdrbot/optmath.py` (`_VOL_GRID` line 459, `Breakeven` dataclass line 463,
`breakeven_vol` line 521), `src/trdrbot/experiments.py` (`simulate` call site line 134).

**Current, verified:** `_VOL_GRID` stops at 120%. A put credit priced at IV 150% renders
"EV positive at every realized vol tested" (G1b) - the confident wrongness the tool exists to
kill, in the regime where short premium clusters.

**Change:**
- `Breakeven` gains `searched_hi: float | None = None` (None = drift grid / not applicable,
  keeps the drift path untouched). `describe()`'s no-crossing branch becomes:
  `f"EV {side} at every {self.variable} tested (searched to {self.searched_hi:.0%})"` when
  `searched_hi` is set.
- `breakeven_vol` gains `iv_hint: float | None = None`. Grid: `_VOL_GRID` extended in the same
  0.5% steps up to `1.5 * iv_hint` whenever that exceeds 1.20. Set `searched_hi` to the grid's
  top. `simulate` passes `iv_hint=iv` (after WU-4.8: the effective iv).
- Check `tests/test_regressions.py` and `test_vol_forecasts.py` for pinned `describe()`
  strings; update in this WU with the explicit-behaviour-change note.

**Tests:** `test_breakeven_vol_found_above_old_grid_cap` - fair-priced put credit at IV 1.50,
7d (gauntlet construction): crossing within 1% of 1.50. `test_breakeven_vol_names_searched
_range_when_no_crossing` - a structure with genuinely one-signed EV: describe() contains
"searched to". Incident docstrings cite I-44.

**Issue:** strike I-44. **Entropy:** none added; one dataclass field.

### WU-4.4 - record_position warns when mark rules can never print (I-45)

**Files:** `src/trdrbot/local_tools.py` (`SimStructure` line 38, stash construction lines
276-292, `record_position` matched-structure block lines 468-483), import
`MIN_NET_COST_SHARE` from `.analytics` (the one definition - do not copy the 0.02).

**Current, verified:** `analytics.position_pnl_fraction` refuses the P&L base when
`net < MIN_NET_COST_SHARE * gross` (correct), so every mark rule on such a position holds
forever; `invalid_rules()`=0 and `watched_signals()` lists `position_mark`, so the board reads
protected (G4/P6).

**Change:** `SimStructure` gains `gross_premium: float | None`; compute at stash time as
`sum(l.price * l.qty * optmath.CONTRACT_MULTIPLIER for l in e.legs)`. In `record_position`,
inside the existing matched-structure loop (it already scales by qty): if any mark-based rule
was given and `abs(entry_cost*scale) < MIN_NET_COST_SHARE * gross_premium*scale` → append to
`note`: "WARNING - net cost is under 2% of gross premium, so position-mark P&L is refused as
division-by-noise (analytics.MIN_NET_COST_SHARE) and your stop_loss/profit_target can NEVER
fire. Add underlying_stop or a time stop; the mark rules are decorative on this structure."
Same reported-never-blocked stance (D-009) and same home as `_unreachable_rules` - this is its
cousin one layer deeper (I-45's own phrasing).

**Tests:** producer-derived: simulate a near-zero-net candidate (e.g. long 100C short 100P
plus offsetting legs priced so |net| < 2% gross - or simply a box-like pair), record with a
stop → returned string contains "NEVER fire"/"division-by-noise" fragment; and the normal-net
case does NOT contain it. Incident: I-45.

**Issue:** strike I-45. **Entropy:** one field; reuses the existing constant and warning seam.

### WU-4.5 - The thesis carries its vol view; the decision measure is the thesis (I-41)

**Files:** `src/trdrbot/experiments.py` (`Thesis` line 30, `simulate` lines 77-215,
`render_comparison` line 368), `src/trdrbot/local_tools.py` (`simulate_experiments` signature
line 145 + docstring, `record_position` thesis-carry block lines 440-447),
`src/trdrbot/positions.py` (`Position` thesis fields ~line 95), `src/trdrbot/llm.py`
(workflow item 1, line ~262).

**Current, verified:** a thesis has a drift knob and no vol knob; `simulate` computes
`pop_thesis`/`ev_thesis`/`payoff` at the MARKET iv with the thesis drift. Measured consequence
(G2): 12 points of true, honestly stated vol edge never lifts full Kelly above 0 - the seed
allocation forever, "record disagrees" on every row - while drift theses ramp 2.1%→4.9% and
their gate is exact (G2b). The vol forecast the agent already records and has scored
(`record_forecast(metric="realized_vol")`, WU-3.6) is disconnected from size.

**Change:**
- `Thesis` gains `vol_view: float | None = None` (FRACTION internally, like `Leg.iv`; the
  tool boundary converts, like `iv_pct`). `summary()` appends `, vol view {v:.1%}` when set.
- In `simulate`: `dec_iv = thesis.vol_view if thesis.vol_view is not None else iv` - THE
  decision measure's vol. Compute under `dec_iv`: `pop_thesis`, `ev_thesis`, `payoff`
  (drift + friction as today), and `be_drift` (its `iv=` argument: "given MY vol, what drift
  is needed"). Everything market-labelled stays at market iv: `pop_market`, `ev_market`,
  `greeks` (risk shape vs the market, per-leg IV honoured), `breakeven_vol` (it SWEEPS vol -
  measure-free by construction). Result dict gains `"vol_view_pct": thesis.vol_view * 100 if
  set else None`. Update the big `ev_after_costs` comment: it now carries the thesis EV under
  the DECLARED measure - drift and vol both.
- `render_comparison`: one line under the thesis summary naming the measure:
  `decision measure: drift +X% , vol Y% (your forecast)` vs `market IV Z%` - the gap between
  the two POP columns is the claimed edge, as today, now including its vol component.
- Tool: `vol_view_pct: float | None = None` argument; docstring paragraph: "your annualized
  realized-vol forecast for this horizon, in percent. This is the vol your EV, POP and payoff
  are computed under - the measure your size is earned in. State it when the thesis is about
  vol (selling rich premium, buying cheap); omit it to price under the market's own IV. It
  should be the same number you record with record_forecast(metric='realized_vol') - that is
  what makes it a SCORED input rather than a claim." Deliberately NOT auto-registered as a
  forecast: a point view has no honest band, and fabricating one would violate the refusal
  discipline; the existing record_forecast flow already covers it (its docstring says so).
- `Position` gains `thesis_vol_view: float | None = None` (mirrors `thesis_drift`);
  `record_position` carries it from `shared.thesis`.
- `llm.py` workflow item 1: append one sentence - "State drift AND, for a vol thesis, your
  vol_view_pct - a vol view left unstated prices your edge under the market's own vol, which
  by construction shows none."

**Tests:**
- **Byte-identity regression first** (this is the load-bearing one): extend
  `tests/test_simulation_golden.py` - a fixture WITHOUT vol_view must produce an identical
  `simulate` result dict before and after this WU (golden captured pre-change).
- `test_gate_exact_under_vol_measure` (PILLAR-1 section): fair-priced condor + put credit at
  market IV 0.25 (gauntlet construction); for `vol_view` in {0.13..0.25}: compute
  `payoff = payoff_ratio(legs, spot, vol_view, days, friction=fr)`, `p = prob_profit(legs,
  spot, vol_view, days)`, and `ev = expected_value(...) - fr`; assert
  `sign(kelly_fraction(p, mp, ml, payoff_ratio=payoff[2])) == sign(ev)` outside a small
  |ev| tolerance band - D-079's algebra, now measure-parameterised.
- `test_vol_edge_now_earns_kelly` - the G2 sweep through `simulate` + `size_position` with
  vol_view: at a large edge, `kelly_full > 0` and fraction rises above the seed floor.
  Incident: I-41, "pinned at 1.86-1.91% at every edge".

**Scaffold:** G2 gains the vol_view rows (`# CHANGED (WU-4.5)`), keeping the old
market-measure rows as the documented contrast.

**Issue:** strike I-41. **Entropy:** one field threaded through an existing seam; no new
module, no new tunable; the EV-hurdle patch this replaces is named in the D-entry as
deliberately NOT built (023's reasoning).

### WU-4.6 - Decisive mark closes require corroboration (I-42)

**Files:** `src/trdrbot/exit_rules.py` (`ExitSignal` line 51, registry line 66, `evaluate`
lines 236-243, `run` journal row line 306).

**Current, verified:** `position_mark`'s `immediate_overshoot=1.0` makes one -100%-of-net
print on a -50% stop decisive - and the registry's own comment says a wide quote "can print
-100%-of-credit on a healthy spread". The documented artifact IS the decisive case (G4/P2).

**Change:**
- `ExitSignal` gains `corroborate: Callable[[Position, Snapshot, str], bool | None] | None =
  None` (third arg = the breached rule's direction, "below"|"above"). Only `position_mark`
  defines one:
  - Inputs, all already on `Position` (D-040): `entry_spot`, `entry_iv`, `greeks_at_entry`
    (delta sign), `opened` (ISO). Any missing → return None.
  - `move = current_underlying - entry_spot`; the position-adverse direction is
    `-sign(delta_dollars)`. A "below" breach (stop_loss) corroborates when the underlying has
    moved ADVERSELY; an "above" breach (profit_target) when it has moved FAVOURABLY.
  - Threshold: `CORROBORATION_FRACTION * optmath.expected_move(entry_spot, entry_iv,
    max(days_since_open, 1.0))`. Module constant `CORROBORATION_FRACTION = 0.25`, docstring:
    "starting point, not a measurement - tune from the journal's own decisive-close rows
    (corroborated vs not) once they exist (WU-4.10), never by taste. Both directions are
    pinned in PILLAR-3."
- In `evaluate`: `decisive = overshoot >= signal.immediate_overshoot and (signal.corroborate
  is None or signal.corroborate(pos, snap, direction) is True)`. None (can't judge) and False
  both fall through to the debounce - the conservative direction: a lone crazy print waits
  2-of-3; a real gap moves the underlying and stays immediate. The `why` string appends
  " - corroborated by underlying" or " - uncorroborated print, debouncing".
- `run`: the exit journal row gains `decisive: bool, corroborated: bool | None` (from
  evaluate's fired tuple - extend it; keep the (reason, why, pnl) public return).

**Tests** (in `tests/test_exit_and_risk.py`, PILLAR-3 marker): drive real `evaluate` with the
gauntlet's Position/Snapshot builders:
- artifact print alone (-100% mark, underlying at entry) → holds tick 1, debounce fires on
  schedule if the breach persists;
- print + corroborating gap (underlying adversely through 0.25×expected_move) → immediate;
- legacy position (no entry_spot) → debounce path, never immediate on mark alone;
- underlying_stop decisiveness UNCHANGED (gap through the level still immediate - the
  underlying needs no corroborator).
Incident docstrings cite I-42 and the registry's own wide-quote comment.

**Scaffold:** G4/P2 expectation flips to "debounced" (`# CHANGED (WU-4.6)`); add the
corroborated-gap row.

**Issue:** strike I-42. **Entropy:** one optional registry field + one justified constant;
the registry shape absorbs the rule (no new branch in evaluate beyond the one guard).

### WU-4.7 - Implicit time stop, same mechanism as the implicit deadline (bleed bound)

**Files:** `src/trdrbot/exit_rules.py` (`evaluate` implicit-rule line 212),
`src/trdrbot/local_tools.py` (`record_position` docstring, `time_stop_days_before_expiry`).

**Current, verified:** `evaluate` prepends `[{"type": "deadline"}]` (INV-26). A position at
-49% against a -50% stop bleeds to expiry with nothing armed unless the agent wrote a time
stop (G4/P5).

**Change:** module constant `IMPLICIT_TIME_STOP_DAYS = 1` (docstring: the gamma-wall default;
the agent overrides by writing any time_stop of its own, `0` = deliberately hold to expiry).
In `evaluate`, the implicit list becomes deadline + (`{"type": "time_stop",
"days_before_expiry": IMPLICIT_TIME_STOP_DAYS}` unless any agent rule has
`type == "time_stop"`). A position with no expiry reads signal None and holds (existing
behaviour). `record_position` docstring for `time_stop_days_before_expiry`: "...defaults are
not neutral: if you write NO time stop, an implicit one closes the position
1 day before expiry (the gamma wall). Write your own - 0 means hold to expiry - to override."

**Tests:** bleed position with only a -50% stop and expiry in 3d: no fire at 3d/2d, fires
`time_stop` at 1d; agent-written `days_before_expiry: 0` → implicit absent, no fire at 1d;
no-expiry position unaffected. **Scaffold:** G4/P5 gains the bounded outcome row.

**Entropy:** second (and last) new constant; reuses the implicit-rule mechanism verbatim.

### WU-4.8 - Skew: vega-weighted evaluation vol, and the span reported (I-43)

**Files:** `src/trdrbot/optmath.py` (new helper next to `net_greeks`),
`src/trdrbot/experiments.py` (`simulate`, `render_comparison`).

**Current, verified:** greeks honour `Leg.iv`; the lognormal grid takes one flat iv, so a
fair-by-construction skewed board manufactures up to $18/contract EV and gates mirror-image
zero-edge spreads 26pp apart (G3). The README's "per-leg IV so measured skew is priced" is
true only of the risk layer.

**Change:**
- `optmath.vega_weighted_iv(legs, spot, days, fallback_iv) -> float | None`: weights =
  per-leg BS vega × qty at each leg's own iv (fallback for legs without one); None when no leg
  carries an iv or all vegas are 0. Docstring: "the single flat vol that best represents a
  skewed set of quotes for a one-distribution evaluation - an approximation and SAID to be one;
  the honest full answer (a smile-consistent distribution) is deliberately refused, same
  reason as calendars (MultiExpiryError)."
- In `simulate`: `iv_eff = vega_weighted_iv(legs, spot, days, iv) or iv`. Use `iv_eff`
  wherever the MARKET measure is evaluated (`pop_market`, `ev_market`, `breakeven_vol`'s
  `iv_hint`, and as the `dec_iv` fallback when no vol_view). When any leg carried an iv, add
  metrics `iv_eff_pct` and `ev_span`: `(expected_value at min leg iv, at max leg iv)` - the
  undefendable-input band. `render_comparison`: one line when present -
  `skew: evaluated at vega-weighted {iv_eff:.1%} (legs {lo:.1%}..{hi:.1%}); EV would read
  {a:+.0f}..{b:+.0f} across that range - treat the choice as an assumption ([assumptions])`.
- Byte-identity: with no leg ivs, `iv_eff == iv` and metrics/render are unchanged - extend the
  golden test to assert it.

**Tests:** the G3 skewed board (put credit + call credit at the gauntlet's SKEW dict):
`abs(ev at iv_eff)` strictly smaller than `abs(ev at flat ATM)` for both spreads, and their
gate thresholds (from friction-charged payoff at iv_eff) closer together than the measured
71%/97%; `ev_span` present and ordered. Incident: I-43, the $18/26pp numbers.

**Issue:** strike I-43 with the residual stated (no smile model, by refusal). **Entropy:** one
helper, one render line; no tunables.

### WU-4.9 - Memory: one lesson, one wiki page (and only those)

**Files:** `src/trdrbot/lessons.py` (LESSONS tuple), `data/wiki/technique/` (one new page).

- Append lesson `both-sides-of-the-smile` (measured claim, decaying - NOT a rule copy):
  text carrying the G3 numbers: "On a zero-edge board priced fairly at its own skewed quotes,
  my flat-IV evaluation gated a put credit spread at 71% claimed and its mirror call credit at
  97% - the same no-edge trade, 26pp apart, purely by smile side ($18/contract of manufactured
  EV at the extreme). My evaluation vol is an assumption: when leg IVs sit far from it, re-run
  the conclusion at the leg IVs (the simulator prints the span since WU-4.8) before trusting
  EV, and treat a structure that only looks good on one side of the span as untested, not
  attractive." cue: "when leg IVs differ materially from the ATM or evaluation vol, or a
  credit spread looks much better than its mirror". tags: ("volatility", "assumptions",
  "instruments"). Run `uv run trdrbot lessons seed` and paste its output (idempotence by key
  handles the rest; seeding requires elfmem up - if unavailable, land the code and note the
  pending seed in the commit).
- Hand-author `data/wiki/technique/pin-risk-and-the-gamma-wall.md` in the existing technique
  format (frontmatter `type: Technique`, `status: stable`, a source row naming
  `specs/notes/023`; sections `# Rule`, `# When it applies`, `# What it means`) - content: why
  short-dated short premium concentrates risk at the strike into expiry, and why the default
  time stop (WU-4.7) exists. Hand-authored pages do not go through `write_concept` (D-023
  comment, wiki.py line 70) - follow the on-disk format exactly.
- Deliberately NOT added: a skew technique page (`skew-does-not-select-structures.md` already
  exists - verified), any constitution change (FULL at 427/430; scope rule routes enforceable
  rules to code), lessons restating WU-4.2/4.6 fixes (a lesson that copies an enforced rule is
  a second definition waiting to drift).

### WU-4.10 - Gauges: the drift line, from rows the system now writes

**Files:** `src/trdrbot/tick.py` (~line 197, where `book_greeks` is already computed),
`src/trdrbot/coach_pkg/gauges.py` (`snapshot_gauges`), `src/trdrbot/report.py` (surface the
new series).

- **tick**: where the position-context renderer already computed `bg = analytics.book_greeks`,
  journal `journal.append("book_risk", delta_dollars=..., vega_dollars=...,
  beta_weighted_delta=bg.get(...), pct_equity_per_1pct_spy=bg.get(...))` - once per decide
  cycle, only when `bg` is truthy. Data already computed; this is recording, not new
  instrumentation.
- **gauges** (all windowed like `_kind_rows`, omitted-never-zero per the module's own rule):
  `sizing.refused_rate` (share of `sizing` rows with result startswith "refused", window 10) -
  the I-40-class trend; `exit.uncorroborated_decisives` (count of exit rows with
  decisive=True, corroborated=False) - the I-42-class trend; `book.vega_dollars` /
  `book.beta_delta_dollars` (latest `book_risk` row) - the trajectory that decides whether a
  vega CAP is ever earned (023: measure first, gate later).
- **report**: plot the three new series with the existing gauge machinery; add a one-line
  legend note naming the north star (calibration skill) and the guardrails (rule compliance,
  decline-rate band, cost/staleness) so the chart reads as 023 §"live side" intends.
- No new sentinels in this WU: a sentinel needs a measured normal range first; these gauges
  create it.

**Tests:** gauge unit tests with journal rows written through `Journal.append`
(producer-derived); omitted-when-absent asserted (the absence-as-zero class, D-038).

### WU-4.11 - Pillars pinned, scaffold refreshed, docs squared

**Files:** `tests/test_regressions.py`, `tests/test_exit_and_risk.py`,
`tests/scaffold_trader_gauntlet.py`, `specs/issues.md`, `specs/decisions.md`, `README.md`.

- Ensure the four pillar sections exist as greppable markers - `PILLAR-1` (economic
  conscience: WU-4.5 exactness + existing D-079 pins + monotone-in-edge), `PILLAR-2` (seams:
  WU-4.1/4.2), `PILLAR-3` (paths: WU-4.6/4.7 + existing exit tests), `PILLAR-4` (learning
  integrity: point the marker at the existing ladder-monotonicity, luck-blocking and
  holdout-veto tests rather than duplicating them). One comment block at each marker states
  the governance rules that bind it (frozen-additive; mutation-verified; admission needs an
  address and an incident - 023 §governance).
- Scaffold: full re-run; every `# CHANGED (WU-4.x)` row present; VERDICT still zero
  violations; paste output in the commit.
- Docs: strike remaining I-4x lines; README "Honest limitations": remove the long-call
  implication if any, add one line "evaluation vol on a skewed board is vega-weighted, not
  smile-consistent - the span is printed, the model is refused"; decisions.md gains the
  phase-4 D-entries.

---

## D. Phase 5 - the golden decision set (after WU-4.5; independent of the rest)

The missing middle tier (023 §layer-2): the decide agent's judgement, graded on actions and
state, never wording. Runs at promotion time and weekly - **never in pytest, never in CI**.

### WU-5.1 - Harvest recorder

**SPEC GAP found while building phase 4 - resolve this before writing the code.** The bundle
as originally specified (snapshot render, inbox item, chain text, market params, deadline,
posture, fingerprints) is the DECIDE PROMPT's inputs, and that is not enough to replay a
cycle. The decide agent is a tool-using loop: the option chain, the live quotes and the
account state arrive as TOOL RESPONSES during the loop, not in the prompt. Replay them absent
and the agent calls `get_option_chain`, gets a stub, and the graded "decision" is a decision
about nothing - a harness that runs and proves nothing, which is the exact failure class this
project keeps naming (D-074/D-082/D-086).

So WU-5.1 is two captures, not one:

1. **Prompt inputs** as originally specified, at assembly time in `_build_decide_prompt`.
2. **Tool responses**, keyed by `(tool_name, arguments-digest)`, recorded at the MCP boundary
   as the loop runs. `compact.wrap_heavy_tools` already wraps every heavy tool result and is
   the natural interception point - it sees the response before compaction, which is also the
   form a replay wants. `mcp_client.call` is the alternative if the compactor's coverage
   turns out to be partial; check which before choosing.

Both land in one bundle at `data/evals/harvest/<date>_<decision_ref>.json`. Bounded: keep the
newest 50 (delete older on write). Guarded like every tick side-write (failure prints, never
aborts). Verify the capture is sufficient by replaying ONE bundle before curating any others -
a scenario set built on an insufficient bundle is a week of work that grades nothing.

### WU-5.2 - Runner and graders

`evals/` at repo root: `scenarios/dev/*.json`, `scenarios/frozen/*.json`, plus
`src/trdrbot/evals.py` and a CLI verb `trdrbot eval [--frozen] [--k 3]`.
- A scenario = a harvested bundle (or synthetic board from the gauntlet constructions) + an
  `expect` block: `{action: "trade"|"decline", structure_class?: "credit_spread"|..., notes}`.
- The runner builds the REAL decide graph with the real local tools over tmp stores, and a
  fake MCP tools dict serving the recorded market data (the established adapter-boundary
  fake - test_llm_seam.py shows the shape). Real LLM calls; cost is the point of the weekly
  cadence (~40 scenarios × k=3 ≈ a few dollars at the compacted per-cycle cost).
- Graders, all code, all binary, per 023: action matches expect; structure class matches when
  specified; size within caps; `record_position` called iff traded; exit rules parse
  (`invalid_rules()==0`), observable (not the I-45 case), reachable (`_unreachable_rules`
  empty); thesis band falsifiable (a band exists); stated confidence within ±15pp of the
  declared measure's own `pop_thesis` (coherence, not truth). pass^k: ALL k runs pass.
- Output: `data/evals/results.jsonl` row per scenario×run + a rendered table; every run row
  carries prompt fingerprints, scenario-set version, and k (the reporting checklist).

### WU-5.3 - Curation and governance

Populate: ~10 harvested real cycles + ~10 synthetic (gauntlet boards, incl. one vol-edge
take-case, one friction decline-case, one skew trap, one blind-mark trap). **Balanced: equal
take and decline cases** - this system has measured both drift directions (18-simulated/
0-traded; the 224-contract fallback). Split: half dev, half frozen; `evals/README.md` states
the rules: frozen consulted only at promotion; the Coach and any prompt iteration see dev
only; rows are added, never edited-to-pass; a scenario the suite saturates moves to dev as a
canary. Wire one line into the Coach's promotion path docs (015 §4): a decide-path lever
promotion requires a frozen-set pass at current k.

---

## E. Deferred, with re-entry conditions (do NOT build in this phase)

- **Gate regret** (015 §2): build when ≥ ~30 rejected theses have RESOLVED on the ledger
  (check `trdrbot ledger`); it then becomes the live eval for gate thresholds.
- **Gate-on-derived-pop** (023 R1 deferral): revisit after ~30 resolved vol_view theses show
  the stated-vs-derived gap gauge is small; it deletes the self-report degree of freedom but
  changes calibration semantics.
- **Book vega CAP**: only if the WU-4.10 gauge trajectory shows concentration the
  per-underlying cap misses; bring a measured incident to the D-entry.
- **Smile-consistent pricing**: refused on principle (WU-4.8 docstring is the record).

## F. Phase acceptance

1. `uv run pytest` green; paste the summary (expect net +~25 tests).
2. `uv run python tests/scaffold_trader_gauntlet.py` → VERDICT: zero violations; G2 shows
   Kelly engaging under vol_view; G6 shows the tool refusing; paste the VERDICT block.
3. `uv run python tests/scaffold_structure_zoo.py` → still "all invariants hold" (D-079
   untouched).
4. Every I-40..I-45 entry struck with its WU reference and a performed revert-verify.
5. `uv run trdrbot prompts` - tool-contract fingerprints changed ONLY for the three touched
   tools + decide.system; note them in the phase-close commit (provenance for the journal).
6. One dev-journal entry (docs/dev_journals convention) closing the phase.
