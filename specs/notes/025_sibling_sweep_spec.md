# 025 · Phase 6 implementation spec - the sibling sweep (LLM-executable)

The executable response to the 2026-08-30 whole-system review (four parallel audits over the
subsystems phase 4 did not touch; findings recorded as **I-46..I-53** in
[issues.md](../issues.md)). Written for an LLM implementer in the
[020](020_phase1_implementation.md)/[024](024_one_measure_implementation_spec.md) convention.
Every line reference below was verified against source on 2026-08-30 - **re-read the named
region before editing, and trust the file over this document if they have drifted.**

Phase numbering: Phase 5 (the golden decision set, 024 §D) remains specified-and-deferred; this
phase is expected to land BEFORE it, because two of its findings sit in code phase 4 shipped.

The one-line intent: **the review found no new defect class - it found the project's oldest one
("every hard-won pattern exists once, next to N places that lack it", notes/019 §1.2) relocated
to newer ground, twice into code written the same day. This sweep applies each existing
discipline to the sibling that lacks it, and adds NO new mechanisms beyond one registry entry.**

---

## A. What was reviewed and deliberately NOT fixed (read this first - it bounds the phase)

The review produced 15 findings. Seven do not become work, and the reasons are load-bearing:

1. **Muse exclusion list (the review's fix direction) - REJECTED; measure instead.** Threading
   `research_universe | watchlist` into `MUSE_PROMPT` touches the Coach's one LIVE lever
   (`muse.prompt` runs paired A/B trials; the seed constant is the incumbent until a promotion).
   Editing it from outside the Coach corrupts the running trial's pairing and changes the
   fingerprinted artefact mid-experiment. And the premise is unproven: a novel thesis on a
   covered name is legitimately the muse's job - its mandate is novel THESES, not only novel
   names. So: the overlap gets a GAUGE (WU-6.4), computed from journal rows that already carry
   per-candidate underlyings, and a gate must earn its existence from that trajectory - the
   identical discipline that held the vega cap to "measure first, gate later" (D-094).
2. **Ledger legs/structure field (I-16 refinement) - OUT OF SCOPE, routed to the gate-regret
   workstream.** Scoring declines needs the D-070 gaming question answered first (auto-stated
   probabilities that walk the size ladder), a schema addition, and per-candidate confidence
   capture at simulate time. That is a feature with its own design questions, not a sibling of
   an existing discipline. It blocks gate regret (notes/015 §2) and belongs with it.
3. **Research options-liquidity gate - RECLASSIFIED as a deliberate limitation** (now recorded
   in issues.md's limitations section). Research runs while the market is closed; there is no
   chain to check. The gap is already surfaced honestly (`unchecked` + journal row) and dies
   loudly downstream. A "fix" would be checking liquidity against no data.
4. **`fit_band_inflation` single holdout** - already tracked inside I-29 with a forward audit
   pending; adding cross-validation now would be tuning the instrument before the live audit
   reports. No action.
5. **Wiki staleness lag** - by design (sweep-stamped, bounded by one housekeeping interval).
6. **elfmem decide-time guards** - traced during the review and CLOSED with no finding:
   `assemble_context` (tick.py:599) runs after reconcile and exit_rules complete (tick.py:463-464),
   so a failure cannot disarm a stop; the run loop's outer handler (cli.py:284) contains it; the
   other three calls route through `learn.py`, advisory since D-091.
7. **cli.py's stale module docstring** - folded into WU-6.8 rather than standing alone.

## B. Global rules

Rules 1-7 of [020 §A](020_phase1_implementation.md) verbatim, plus 024's additions: the
**entropy line** on every commit; **behaviour changed on purpose = scaffold row updated in the
same WU**; **issue closure discipline** (strike I-4x only after a PERFORMED revert-verify);
pillar governance per `docs/principles_testing.md` (every new test names its pillar and its
incident). Phase-specific:

8. **One new tunable constant is permitted in the whole phase** (`LEG_DIVERGENCE_CONFIRM`,
   WU-6.3), docstring naming the journal rows that would tune it. A WU wanting a second must
   justify it against a measurement or not add it.
9. **WU-6.3 touches exit_rules.py**: re-run BOTH scaffolds (`scaffold_structure_zoo.py`,
   `scaffold_trader_gauntlet.py`) and paste both verdicts into the commit.
10. **No new subsystems, no new stores, no new row kinds.** Every fix lands inside an existing
    mechanism: a Probe, a registry entry, a gauge function, a field on an existing row or
    dataclass. If a fix seems to need a new mechanism, stop and re-read the finding - the whole
    phase's thesis is that the mechanism already exists somewhere.

## C. Work units

Dependency order: 6.1, 6.2, 6.4-6.8 are independent (any order; parallel-safe). 6.3 is the
largest and touches the capital-protection spine - do it with the most care, after at least one
smaller WU has warmed up the conventions. 6.9 is investigation-only, last.

### WU-6.1 - The cost sentinel refuses to read unpriced spend as free (I-46)

**Files:** `src/trdrbot/coach_pkg/gauges.py` (`_cost_today` ~line 156, `_sentinel_cost` ~line
292), `tests/test_coach.py` (PILLAR-4 section).

**Current, verified:** `_cost_today` returns `round(sum(c.cost_usd or 0.0 ...), 4)` over today's
muse/coach_mutate calls; `_sentinel_cost` compares that to the ceiling. `usage.py` documents
`cost_usd=None` as "UNPRICED, never counted as free" and renders it loudly - everywhere except
the one place that brakes autonomous spend.

**Change:** `_cost_today` returns `(usd: float, unpriced: int)` - the count of today's calls in
the sentineled roles whose `cost_usd is None`. `_sentinel_cost` fires when `usd > limit OR
unpriced > 0`, and its returned `value` names both (`f"${usd} + {unpriced} unpriced call(s)"`)
so the report's sentinel line says WHY. The `coach.cost_usd_today` gauge keeps putting the
priced sum only (its docstring gains one line saying unpriced spend is the SENTINEL's job, not
this gauge's - a gauge silently mixing units would be its own defect). Callers of `_cost_today`:
verify both (the gauge put and the sentinel) and any test fixtures.

**Tests (failing first):** `test_cost_sentinel_fires_on_unpriced_spend` - a UsageLedger row for
role "muse" with no pricing entry → sentinel fires with $0 priced spend; and the inverse,
priced-under-ceiling with zero unpriced → does not fire. Producer-derived: write the usage row
through `UsageLedger`'s real writer, never a hand-built dict. Incident: I-46, and the docstring
sentence in usage.py it violated.

**Entropy:** none added - one return value widened, one condition. Strike I-46 (revert-verify).

### WU-6.2 - Health learns to ask about phase 4's own rows (I-47)

**Files:** `src/trdrbot/health.py` (Probe dataclass lines 34-81, `PROBES` tuple line 84+, and
the state-check section of `check()` - READ THE WHOLE FILE first; `check(journal_path,
positions)` takes the positions list, which one check below needs),
`tests/test_health_contract.py`.

**Current, verified:** no probe or check mentions `sizing` or `book_risk`.

**Three additions, each in the mechanism that fits it:**

1. **Probe "sizing"** - native ran/produced shape: `ran_kinds=("sizing",)`, `produced` = count
   of rows whose `result` is `sized` or `no_position` (i.e. the tool reached a verdict; a
   refusal is the tool declining to answer), `min_runs=8`,
   meaning: "every recent sizing call REFUSED - the structure-matching seam is losing the
   conditional payoff (the I-40 class), or the agent has stopped naming its structures. See the
   [when-refusals-cluster-audit-the-ruler] lesson: clustered refusals indict the instrument
   before the candidates." `never_producing_is_ok=False`.
2. **State check: orders without sizing** - in `check()`'s state-check section: over the probe
   window, `sum(order_calls across execution rows) > 0` with zero `sizing` rows → **BAD**,
   "orders are being placed with sizing never consulted - the Kelly gate is bypassed". This is
   cross-kind, which is why it is a state check and not a Probe.
3. **State check: the book-risk feed died** - open positions exist (the `positions` argument)
   AND ≥ N decision rows in the window AND zero `book_risk` rows → **WARN**, "positions are open
   but the book-risk series stopped - concentration is invisible to the report". WARN not BAD:
   `book_risk` legitimately skips when the snapshot carries no underlying prices.

**Tests:** three, in test_health_contract.py's existing style (journal rows written via
`Journal.append` / `health.heartbeat`, never hand-rolled files where a producer exists): all-
refused window flags; orders-without-sizing flags BAD; open positions + decisions + no
book_risk flags WARN; and each check stays QUIET on the healthy shape (the crying-wolf half is
part of the contract - D-070's "a health check that cries wolf trains the reader to skip it").

**Entropy:** none - one Probe row, two checks in an existing section. Strike I-47.

### WU-6.3 - A vanished leg becomes a close, through the machinery that already exists (I-48)

**Files:** `src/trdrbot/reconcile.py` (the `leg_divergence` elif - the block journaling
`finding="leg_divergence"`), `src/trdrbot/positions.py` (`Position` dataclass),
`src/trdrbot/exit_rules.py` (registry `EXIT_SIGNALS`, `_normalise`, `_PRIORITY`, the implicit-
rule list from WU-4.7), `tests/test_exit_and_risk.py` (PILLAR-3), `tests/test_loop_smoke.py`
(the reconcile→exit sequence within one tick).

**Current, verified:** the divergence is journalled and added to `result["drift"]`; nothing
else. Downstream `position_pnl_fraction`/`evaluate` silently price the surviving legs forever.

**Design, and why this shape.** The remainder of a broken spread can be an undefined-risk naked
leg - the exact thing INV-19 exists to never create. The deterministic layer must not hold that
waiting for an LLM. But reconcile has no `tools` and must not gain them (entropy rule 10), and
a single stale broker snapshot must not liquidate a healthy spread. All three constraints are
met by the machinery already in place: **reconcile counts, the exit registry closes.**
`reconcile` runs immediately before `exit_rules.run` in the same tick (tick.py:463-464), so
confirmation costs exactly one tick of exposure - 5 minutes on the open cadence.

**Changes:**

1. `Position` gains `leg_divergence_count: int = 0` (loaders ignore unknown keys since D-091,
   so old position files are safe - same pattern as `thesis_vol_view`, WU-4.5).
2. In reconcile's loop: the divergence elif increments the counter and `store.save(pos)`
   (journal row unchanged, but add `consecutive=pos.leg_divergence_count` to it); add the
   missing third branch - fully present (`len(present) == len(syms)`) with a nonzero counter →
   reset to 0 and save, journaling `finding="leg_divergence_cleared"` so a transient glitch
   leaves a trace instead of silently un-counting.
3. In exit_rules: a registry entry, exactly the D-037 recipe ("a new rule type is a registry
   entry plus one clause in `_normalise`"):
   - module constant `LEG_DIVERGENCE_CONFIRM = 2` - the phase's one permitted tunable.
     Docstring: "consecutive reconcile passes that must see the leg missing before the close
     fires. 2 = one confirmation tick, chosen to survive a single stale snapshot; tune only
     from journalled `leg_divergence` vs `leg_divergence_cleared` counts, never by taste."
   - `EXIT_SIGNALS["leg_divergence"]`: `read=lambda p, s, d: float(p.leg_divergence_count)`,
     `immediate_overshoot=0.0` (the counter IS the debounce - it is not a noisy signal),
     `render=lambda v: f"{v:.0f} consecutive"`. No `corroborate` - reconcile against the
     broker's own holdings is the corroboration.
   - `_normalise` clause: `kind == "leg_divergence"` → `("leg_divergence", "above",
     float(LEG_DIVERGENCE_CONFIRM), kind)`.
   - `_PRIORITY["leg_divergence"] = 0` - a broken structure outranks every rule about the
     intact one, alongside the deadline.
   - the implicit-rule list (WU-4.7's block) gains `{"type": "leg_divergence"}`
     unconditionally - like the deadline, it is not the agent's to override: the agent's rules
     describe a position that no longer exists.
   The whole existing close path then does the rest: INV-19 closes ALL remaining legs,
   `close_reason="leg_divergence"` flows to the journal and to `learn.on_resolution`.
4. **Stated limitation, recorded in the WU's D-entry, not silently accepted:** the
   `pnl_fraction` passed to learning at that close is computed over the SURVIVING legs only -
   the vanished leg took its P&L with it, the same honest gap as D-056's external closes. And
   assigned STOCK appearing at the broker is out of scope here: it will surface through
   reconcile's existing "at the broker with no story of ours" branch, which is the correct
   place for it.

**Tests:**
- unit, PILLAR-3: a position with `leg_divergence_count=2` fires `leg_divergence` at priority
  over a simultaneously-breached profit_target; count 1 holds; count 0 holds.
- seam (test_loop_smoke.py style, producer-derived): full sequence across two ticks - broker
  snapshot missing one leg → reconcile increments (journal row carries `consecutive=1`), exit
  holds; second tick same → increments to 2, exit closes ALL remaining legs, position
  terminal, `learn` ran; and the glitch path - missing then present → counter reset,
  `leg_divergence_cleared` journalled, nothing closed.

**Scaffold:** add a G4 path row (`P7 leg vanishes at broker: tick1 held, tick2 closes all
remaining legs`). Re-run both scaffolds (rule 9). **Entropy:** one field, one registry entry,
one constant; zero new mechanisms. Strike I-48.

### WU-6.4 - The muse's books balance: malformed candidates counted, funnel overlap measured (I-49)

**Files:** `src/trdrbot/muse.py` (the per-candidate skip ~line 299, before `ledger.register`
~line 336; the two fates sites ~lines 462 and 594-603 - match their exact key sets),
`src/trdrbot/coach_pkg/gauges.py`, `tests/test_thesis_gates.py` or `tests/test_coach.py`.

**Changes:**

1. **Malformed candidates enter the accounting.** At the skip site, instead of a bare
   `continue`, append a minimal verdict to `evaluated` with `fate="malformed reply element"`
   and whatever keys the two downstream sites read (VERIFY both comprehensions' key sets and
   supply every key, `underlying="?"` where absent - a KeyError here would take the whole muse
   run down, which is the opposite of the point). Consequences, both intended: the journal row
   and trial record now count it, so `gauges.survived()` scores it as a non-survivor and **a
   prompt variant that produces garbage now loses A/B trials on that garbage** - the reward
   gets honest. It still does NOT reach `ledger.register` (a band-less, underlying-less row is
   exactly what `register` refuses); the invariant becomes "every candidate is COUNTED", which
   is what the multiple-testing correction actually needs. Note in the commit: an open A/B
   experiment sees this from its next paired run onward, both arms identically - pairing is
   preserved.
2. **`muse.funnel_overlap_rate` gauge** in gauges.py: over the recent muse rows (the existing
   `_muse_rows` window), the share of candidates whose `fates[].underlying` is in
   `set(cfg.research_universe) | set(cfg.watchlist)`. Omitted-never-zero when no candidates.
   Docstring states the decision it exists to inform (§A.1): an exclusion gate must earn its
   existence from this trajectory, and the muse prompt is a live lever nobody edits from
   outside the Coach.

**Tests:** malformed element in a synthetic reply → counted in the journal row's fates as a
non-survivor, run completes, well-formed siblings still registered; overlap gauge computed from
producer-written muse rows; omitted with no data.

**Entropy:** none - one gauge, one appended verdict shape. Strike I-49.

### WU-6.5 - Per-leg IV survives the trade (I-50)

**Files:** `src/trdrbot/local_tools.py` (`SimStructure` ~line 38, its construction ~lines
276-292, `record_position`'s occ-legs/greeks block ~lines 419-431, `_legs_key` line 84),
`src/trdrbot/optmath.py` (`Leg.from_position_leg` lines 84-112), `tests/test_regressions.py`
(PILLAR-1 or the D-040 greeks section - fit the existing home).

**Current, verified:** `from_position_leg` parses symbol/side/qty/price only - `.iv` is never
set, so entry-recorded greeks and every later `book_greeks` render price a skew-built position
at one flat vol, while `net_greeks` would honour per-leg IV if only it were given one. The
simulated structure the trade was matched to HAD the per-leg IVs.

**Change - derive, don't declare (D-037), then persist:**
1. `SimStructure` gains `leg_ivs: dict | None` - mapping the same `(right, strike, side)`
   identity `_legs_key` uses → the leg's iv fraction, populated at stash time from `e.legs`
   (None when no leg carried one).
2. In `record_position`, where the traded key already matches a `SimStructure`: write
   `iv_pct` into each recorded leg dict (`pos.legs`) from the matched structure's `leg_ivs`,
   keyed by the parsed OCC leg's (right, strike, side). The leg dicts are the position file's
   wire format; an added key is ignored by old readers (D-091 loader tolerance).
3. `Leg.from_position_leg` reads `d.get("iv_pct")` exactly as `parse` does (fraction
   conversion included). `net_greeks` and `book_greeks` then honour it with zero further
   change.

**Tests (producer-derived, end to end):** simulate two candidates with skewed `iv_pct` legs →
record the traded one → the saved position's leg dicts carry `iv_pct`; `greeks_at_entry`
differs from the flat-IV computation of the same legs (assert direction using the measured
16.5-vs-7.4 style split); a flat-quoted candidate round-trips with no `iv_pct` keys and
byte-identical greeks (the WU-4.5/4.8 identity discipline).

**Entropy:** one field threaded along an existing match; no new tunables. Strike I-50.

### WU-6.6 - The lock verifies its own claim (I-51)

**Files:** `src/trdrbot/lock.py` (lines 27-45), `tests/test_regressions.py` (the D-044 lock
section, three existing tests to keep green).

**Change:** after `path.write_text(...)`, read the file back; if the recorded pid is not ours,
another process won the race - raise `BlockingIOError` naming both pids, and do NOT unlink in
the finally (the lock is theirs). This collapses the TOCTOU window from "the whole tick" to a
microsecond re-read without changing the stale-breaking design the three existing tests pin.
Deliberately NOT flock/O_EXCL rewrites: the pid+timestamp design is tested, cross-checkable by
a human reading the file, and the residual window after verification is a single filesystem
read - proportionate to a same-machine race that requires two loops started in the same
instant.

**Tests:** `test_the_tick_lock_loses_a_race_it_did_not_win` - acquire, then overwrite the file
with a rival live pid before the verify step runs (monkeypatch or reorder via a hook seam -
whatever is honest against the real implementation) → BlockingIOError, rival's file intact.
The three existing lock tests unchanged and green.

**Entropy:** three lines and a test. Strike I-51.

### WU-6.7 - The single-shot tick fails the way the loop degrades (I-52)

**Files:** `src/trdrbot/cli.py` (`_tick` lines 116-124; `failures.classify`/`advice` lines
72/89 of failures.py).

**Change:** wrap `_tick`'s body: on any non-`BlockingIOError` exception, print one classified
line (`[tick] failed ({cause}): {advice}`) and **return 1** - cron/launchd sees a clean
failure signal instead of a raw traceback, and the operator sees the same classification
vocabulary the health warnings already use. No journaling from the handler (the journal write
path may be the very thing that failed). The loop path (cli.py:276-284) is untouched - its
print-and-continue is correct for its job.

**Tests:** CliRunner-level per the testing overlay: a monkeypatched `run_tick` raising →
exit code 1, output contains the classified cause; `BlockingIOError` still exits 0 with the
skip message.

**Entropy:** reuses the existing classifier; no new machinery. Strike I-52.

### WU-6.8 - Doctor sees typo'd roles; cli.py's docstring stops lying (I-53)

**Files:** `src/trdrbot/cli.py` (`_doctor` ~lines 27-90; module docstring lines 1-7),
`src/trdrbot/config.py` (`model_chain` ~lines 94-109 - read to find where the yaml `roles:`
keys are reachable), `src/trdrbot/llm.py` (the code's role list - verify its actual name).

**Change:** in `_doctor`, after the per-role probes: compute `set(config's roles keys) -
set(code's roles)` and print one warning line per unknown key ("roles.reserach is not a role
this code has - it is silently ignored and that role runs the default chain. Known roles:
..."). Never fatal - degradation-to-default remains the design; invisibility was the defect.
And replace the module docstring's stale 4-command enumeration with one line pointing at
`trdrbot --help`, so it cannot drift again.

**Tests:** doctor with a misspelled role key in a tmp config → warning names the key; clean
config → no warning.

**Entropy:** negative - deletes an enumeration that was already wrong. Strike I-53.

### WU-6.9 - Trace the MCP mid-tick death path, then pin it or ledger it (no issue yet)

**Files to read:** `src/trdrbot/mcp_client.py` (`session_tools` lines 49-67), the watchdog
wrapping in cli.py's `_run_loop` (lines 275-284), tick.py's session usage.

**This WU is an investigation with two possible outcomes, and machinery is not one of them:**
trace what actually happens when the MCP session dies mid-tick (kill the subprocess under a
running test tick, or fake the transport error at the adapter boundary). If the failure is
contained as believed - exception → watchdog/loop handler → next tick builds a fresh session -
**pin it** with one seam test (`test_a_dead_mcp_session_fails_one_tick_not_the_loop`, the
adapter-boundary fake, loop-smoke style) and a comment in mcp_client.py saying it is verified.
If it is NOT contained, do not fix it in this WU: record it as I-54 with the trace, per the
ledger rule. Building a reconnect path in anticipation is exactly what rule 10 forbids.

---

## D. Phase acceptance

1. `uv run pytest` green; expect net +~14 tests; paste the summary.
2. Both scaffolds re-run (required by WU-6.3 regardless): zero violations; the new G4/P7 row
   present; paste both verdicts.
3. I-46..I-53 struck with performed revert-verifies; either the WU-6.9 pin test exists or I-54
   does.
4. `trdrbot health` run against live data: the two new checks appear and read healthy (or
   honestly explain why not).
5. One D-entry (D-095) in decisions.md for the phase, in the D-094 voice: what the sweep
   closed, what §A deliberately left alone and why, and the entropy accounting (expected: one
   constant, one registry entry, one Position field, one SimStructure field, one gauge, one
   Probe, two state checks - and zero new mechanisms).
6. One dev-journal entry closing the phase.
7. Restart the run loop only after acceptance passes (same graceful SIGTERM procedure as
   2026-08-30; note WU-6.3's behaviour change for any live position: a leg vanishing at the
   broker now closes the remainder after one confirmation tick).
