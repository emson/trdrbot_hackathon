# 022 · Phase 3 implementation spec (LLM-executable)

The evolution-enablers phase of [019_refactor_plan.md](019_refactor_plan.md) §7, executed the
way [020](020_phase1_implementation.md) and [021](021_phase2_implementation.md) were. Written
for an LLM implementer. Every claim below was verified against the source as of commit
`1c6508a` (2026-08-29, after Phase 2's close-out); line numbers are from that snapshot -
**re-read the named region before editing, and trust the file over this document if they have
drifted.**

**Where this sits.** Phases 0-2 delivered the safety net, the verified-defect fixes, and the
structural foundations (one store, one llm seam, one admission gate, one evidence gather, a
typed bus, a 3.6x pricing pass, config singularity, the decompositions). Phase 3 is the payoff
of the architecture research
([docs/sources/cognitive_modules_research.md](../../docs/sources/cognitive_modules_research.md)):
what makes a module *evolvable* is not its boundary but the evaluator attached to it. This
phase attaches the evaluators - a metric per module, a heartbeat whose contract cannot drift
from its detector, a lever registry where "become evolvable" is a declaration, and the first
new *scored claim type* (the stated vol forecast) so calibration keeps growing evidence.

**Three deltas from 019's Phase 3 sketch, decided here with reasons:**

- **`Journal.nothing_happened()` is dropped.** 019 §7.3.2 proposed it so "ran but produced
  nothing" is authored. The five `*_run` heartbeats already author exactly that
  (`exit_run`, `attribution_run`, `interim_run`, `coach_run`, `learn_run` - the last added in
  Phase 1), and WU-3.2's write-time contract closes the drift half. A second authoring API
  for the same fact would be the two-identities smell this project keeps deleting.
- **No second lever goes LIVE.** 019 named discovery's nomination prompt as the candidate.
  A live lever costs real money (mutate calls + a paired LLM run per trial) and doubles the
  Coach's spend - an operator decision, not a refactoring one. WU-3.1 instead proves the
  machinery generic with a synthetic lever exercised end-to-end in tests, and leaves going
  live as a one-declaration change with the recipe written down.
- **Vol-forecast scoring is ADDED** (not in 019's Phase 3). It is I-14 - called "highest-value
  next step" in the issues ledger - it is squarely an evolution enabler (calibration is the
  evaluator everything else keys on, and this multiplies its evidence), and it resolves the
  last open operator decision (019 §11.2) by giving `implied_vs_realized` its missing
  consumer instead of deleting it.

---

## A. Global rules

Rules A.1-A.12 of [020](020_phase1_implementation.md)/[021](021_phase2_implementation.md)
carry over verbatim: one WU = one commit with the suite output pasted, regression test per
fix, seam-level tests with producer-derived inputs, fakes only at adapter boundaries, no
`inspect.getsource` tests, preserve incident-history comments, verify APIs by running them,
state files sacred, wire formats never renamed, plain dashes, no co-author trailers.

Phase 3 adjusts two:

- **A.13 - This phase is ADDITIVE, not behaviour-preserving.** It exists to add capability:
  new journal kinds (`degraded`), new fields on new rows, new tool parameters, new gauges, a
  new ledger metric. The discipline that replaces "preserve behaviour" is: every addition is
  **backwards-compatible at every store** (old rows load, old lever state loads, absent new
  fields mean the old behaviour), every addition lands with its seam test, and anything that
  changes what an EXISTING path does is called out in its WU as a delta the way 021 did.
- **A.14 - Additions are paid for where they touch.** The net-lines target stays honest
  rather than pretending: this phase will be net-positive in src. The rule is that each WU
  deletes the duplication adjacent to what it adds (the three seeds dicts, health's private
  reader, the muse-specific hardcodings in the generic mutate path), and WU-3.7 audits the
  whole diff the way 021's close-out did - reporting the code-only number, not the gross one.

**Baseline:** 395 passed, src lint clean, strict-mypy modules clean, run loop live on pid
recorded in WU-3.0. **Execution order:** 3.0 → 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7.
3.3 depends on 3.2 (gauges read heartbeat rows); 3.6 is independent and largest - do it last
before close-out so its schema addition soaks under the whole suite.

---

## B. Work units

### WU-3.0 · Snapshot and baseline

As 021's WU-2.0: check `pgrep -f "bin/trdrbot run"` (a loop IS live - note its pid, stop it,
restart at 3.7), `tar -czf ../trdrbot_state_backup_$(date +%Y%m%d_%H%M).tgz data/`, confirm
395 passed / ruff clean / `uv run mypy` at its recorded count.

### WU-3.1 · Levers are declarations (the cheap path to "evolvable")

**Files:** `src/trdrbot/coach_pkg/state.py` (`Lever` ~:84, `LEVERS`),
`src/trdrbot/coach_pkg/mutate.py` (`MUSE_PLACEHOLDERS` :77, `_rejection_digest` :127,
`MUTATE_PROMPT.format` :165-171, `validate_prompt` call :190-192), `src/trdrbot/coach.py`
(pulse's mutate step), the three seeds dicts (`tick.py:528`, `housekeeping.py:200-202`,
`cli.py:~483`), `src/trdrbot/prompts.py` (`_active_muse_prompt` - reads one lever by name).

**Current:** `Lever` declares `name, subsystem, reward_modules, kind` - and everything else a
lever needs is hardcoded to the muse inside the GENERIC machinery: `mutate()` formats
`MUSE_PLACEHOLDERS` into its prompt and passes a literal
`must_contain=("band_low_pct", "band_high_pct", "JSON array")`; `_rejection_digest` reads
muse journal rows by kind; and the seed text is a `{"muse.prompt": muse.MUSE_PROMPT}` dict
copy-pasted at three call sites. Registering a second lever today means editing the Coach's
internals, which is exactly what "touches data, never code" was supposed to prevent needing.

**Change:**

1. `Lever` grows the four things the machinery currently hardcodes - all DATA, no callables
   (a callable in a module-level registry is how the coach-split's import cycle came back):

```python
@dataclass(frozen=True)
class Lever:
    name: str
    subsystem: str
    reward_modules: tuple[str, ...]
    kind: str                      # prompt | policy
    #: Where the seed text lives: ("trdrbot.muse", "MUSE_PROMPT"). Resolved
    #: lazily by `seed_text()`, so the registry never imports a subsystem.
    seed_ref: tuple[str, str]
    #: Format placeholders a variant must preserve, verbatim.
    placeholders: tuple[str, ...]
    #: Substrings a variant must keep (the validator's anchors).
    must_contain: tuple[str, ...]
    #: Journal kind whose recent rows carry this lever's rejection evidence,
    #: read by the mutation's rejection digest. "" = no digest available.
    evidence_kind: str = ""
```

2. `state.seed_text(lever) -> str` - `importlib.import_module` + `getattr`, cached per
   process. `coach.seeds() -> dict[str, str]` builds the pulse/reconcile seeds from the
   registry; the three hand-built dicts die. `prompts._active_muse_prompt` keeps its name
   (callers) but resolves the seed through the registry too.
3. `mutate()` and the pulse's validate call read `st`'s lever (`lever(st.lever)`) for
   placeholders/must_contain/evidence; `_rejection_digest(rows, kind)` takes the kind as an
   argument. `MUSE_PLACEHOLDERS` moves into the muse lever's declaration; the constant
   survives as a re-export only if something imports it (grep; else delete).
4. A **registration recipe** as the `LEVERS` docstring: the five things a new lever declares,
   the two things its subsystem must do (call `coach.arms()` on its hot path; score both
   arms through ONE gate cascade and `record_trial` the pair), and the warning that a live
   lever costs a mutate call plus a paired LLM run per trial.

**Tests** (`tests/test_coach.py` additions - the file's existing `_cfg` fixture pattern):
- `test_a_lever_is_registered_by_declaration_alone` - THE proof. Monkeypatch `LEVERS` to add
  a synthetic lever (`seed_ref` pointing at a test-module constant via
  `monkeypatch.setattr` on an importable dummy - simplest: point it at an existing tiny
  constant like `("trdrbot.llm", "SYSTEM_PROMPT")` is wrong-shaped; instead create
  `tests/fixtures_lever.py` with `SEED = "..."` and reference `("fixtures_lever", "SEED")`),
  then drive the FULL cycle with no muse involvement: `seeds()` includes it → `arms()`
  returns its incumbent → `_open` a challenger → two `record_trial`s → `tally` →
  `verdict` → `_promote` → `load_state` shows the new incumbent. Every step through public
  coach functions.
- `test_mutate_reads_the_levers_own_anchors` - a lever whose `must_contain` differs from the
  muse's is validated against ITS anchors (drive `validate_prompt` via the lever fields, and
  one seam assertion that `mutate` formats the lever's placeholders - monkeypatch
  `build_model` at the module boundary as existing mutate tests do; grep them first).
- `test_the_three_seed_dicts_are_gone` is a grep in Done-when, not a test.

**Edge cases:** `seed_text` on an unimportable ref must not kill a pulse - degrade to ""
with a loud print (an empty seed already means "incumbent-only from state", the existing
posture). Lever state files on disk carry no new fields - untouched.

**Done when:** `grep -rn '"muse.prompt": ' src/` → 0 matches outside the registry;
`grep -rn "MUSE_PLACEHOLDERS" src/trdrbot/coach*` → only the lever declaration; test_coach
green including the synthetic-lever cycle.

### WU-3.2 · The heartbeat contract lives with its detector

**Files:** `src/trdrbot/health.py` (`Probe` :33, `PROBES` :73-174, `_rows` :183),
emitters: `exit_rules.py` (`exit_run`), `housekeeping.py` (`interim_run`), `reconcile.py`
(`learn_run`), `coach.py` (`coach_run`), `attribution.py` (`attribution_run`),
`discovery.py` (the empty-nominees early return).

**Current:** health's probes read journal fields BY NAME (`triggered`, `rules`, `pending`,
`attributed`, `eligible`, `scored`, `trials_scored`, `experiments_open`) that five emitters
write by hand. Nothing ties the two together except one test pinning one subsystem's key
set - and the drift has shipped twice (D-074, D-082: a probe reading a key nobody writes
reports a confident zero forever). `health._rows` is a private skip-bad-lines reader that
predates `store.read_jsonl`. And discovery's empty-nominees return
(`return {"nominees": 0, ...}`) journals NOTHING, so a run that produced nothing is
invisible to its probe - the exact D-038 null-path rule, violated by the subsystem next to
the detector that enforces it.

**Change:**

1. `Probe` gains the write-side contract, as data: `heartbeat_fields: tuple[str, ...] = ()` -
   the fields a row of this kind MUST carry (the union of what its `produced`/`work` lambdas
   read plus the row's other counters). Only the five `*_run` heartbeat kinds declare it;
   output-row probes (decide, execution, research, discovery) leave it empty - their rows
   are wire formats this phase does not touch.
2. **The detector owns the emission door.** New in `health.py`:

```python
def heartbeat(journal: Any, kind: str, **fields: Any) -> str:
    """Emit a subsystem heartbeat THROUGH the module that will read it.

    The probe table declares which fields each heartbeat must carry, and this
    refuses a row that omits one - so "a probe reading a key nobody writes"
    (D-074, D-082, twice) becomes a loud failure at the emitting call site,
    in the first test that runs it, instead of a confident zero forever.
    Extra fields are fine; missing declared ones are not.
    """
```

   It validates against the probe's `heartbeat_fields` and calls
   `journal.append(kind, **fields)` - same bytes on disk, wire format untouched. Layering is
   clean in THIS direction: the five emitters already import journal, health's only
   subsystem import (`exit_rules`, :274) is function-local, and journal never imports
   health. Convert the five emitters to `health.heartbeat(journal, "exit_run", ...)`.
3. `health._rows` → `store.read_jsonl(journal_path)[0]` (delete the private reader - one
   policy, Phase 2's rule).
4. Discovery's empty-nominees return journals its row first:
   `journal.append("discovery", nominees=[], wiki_written=[], opportunities=0)` - so "ran,
   found nothing" and "stopped running" stop being the same observation. (Additive: a new
   row on an existing kind, same fields the non-empty path writes.)

**Tests** (`tests/test_health_contract.py`, new):
- `test_a_heartbeat_missing_a_declared_field_is_refused` - `health.heartbeat(journal,
  "exit_run", positions=1)` raises naming the missing fields; the full field set writes a
  row byte-compatible with what `check()` reads (assert the probe's `produced` lambda works
  on the row just written - the read/write round trip IS the contract).
- `test_every_declared_heartbeat_field_is_actually_read` - for each probe with
  heartbeat_fields, build a synthetic row carrying them and assert `produced`+`work` do not
  KeyError; and the reverse direction: a row missing each field in turn changes nothing
  silently (lambdas use `.get` - so the guarantee is the WRITE side; say so in the test's
  docstring rather than pretending both directions are enforced).
- `test_an_empty_discovery_run_is_visible` - drive `discovery.run` with a nominate reply of
  `[]` (monkeypatch at the `text_of`/model seam as test_coach does for muse) and assert the
  `discovery` journal row exists with `opportunities=0`.
- Existing suite is the regression net: the five emitters' rows must not change shape
  (test_memory_and_credit and test_exit_and_risk already assert on `learn_run`/`exit_run`
  fields).

**Edge cases:** `coach_run` is emitted inside pulse's `finally`-like tail - a refused
heartbeat there must not kill a pulse in production. Decision: `heartbeat` raises (that is
the point - it fails in TESTS), and the five call sites are exercised by the suite, so a
drift cannot reach production green. Do NOT wrap it in try/except at the call sites; a
swallowed contract violation is the old bug with extra steps.

**Done when:** `grep -rn "journal.append(\"exit_run\|journal.append(\"interim_run\|journal.append(\"coach_run\|journal.append(\"learn_run\|journal.append(\"attribution_run" src/` → 0
(all five go through the door); health's own reader deleted; suite green.

### WU-3.3 · Every module's metric reaches the report

**Files:** `src/trdrbot/coach_pkg/gauges.py` (`snapshot_gauges` - the `guarded()` pattern
from D-091 is already there), `src/trdrbot/report.py` (renders `series` generically at
:172-185, so new gauges appear with no report change - verify, then only the steering para
changes in WU-3.5).

**Current:** gauges cover the muse (survival, candidates/run, entropy, runs), calibration
(n, resolved, brier, n_eff), coach cost, and the model layer. The module map (019 §2.2)
names metrics for research, discovery and attribution that exist nowhere: a glance at the
report cannot answer "is discovery's gauntlet getting stricter" or "what share of resolved
theses could we actually explain" - and attributable_rate is the ladder's own promotion
criterion, computed live in `competence.assess` but never trended.

**Change:** add to `snapshot_gauges`, each through `guarded()` and each omitted (never zero)
when there is no data:

- `research.opportunities_per_run` and `discovery.survival` - from the journal rows already
  passed in (`rows`): mean `opportunities` over the last N `research` rows; for discovery,
  `sum(opportunities) / sum(len(nominees))` over the last N `discovery` rows (the gauntlet's
  pass rate). Reuse `GAUGE_WINDOW`.
- `attribution.attributable_rate` - `competence.attributable_rate(positions)` needs
  positions; gauges get `cfg` only. Read it the way the ladder's consumers do: from
  `attribution` journal rows' `verdict` fields over the whole history
  (`verdict not in (UNSCOREABLE, THESIS_WRONG_PROFITED_ANYWAY)` / total) - same definition,
  journal-derived, no store coupling. Import the two constants from `experiments`.

**Tests** (extend `test_coach.py`'s gauge section): journal rows in → expected gauge out,
per gauge; the no-data case omits the key (the existing
`test_a_gauge_with_no_data_is_omitted...` pattern); a broken read lands in `gauges_failed`
(already guaranteed by `guarded`, one assertion rides along).

**Done when:** `uv run trdrbot report` renders the new gauges once metrics rows exist (spot
check in WU-3.7's live smoke; until a snapshot fires they are absent, which is correct).

### WU-3.4 · Fail-open paths leave evidence (D-038 for the instrumentation)

**Files:** `src/trdrbot/compact.py` (the three fail-open returns in
`compact_option_chain`/`_unpack`/`wrap_heavy_tools` - grep `fail open`), `src/trdrbot/tick.py`
(compaction wiring + the `model_served` read ~:640), `src/trdrbot/news_extract.py`
(`enrich`'s batch-failure fallback :~308), `src/trdrbot/evidence.py` (threads a journal),
`src/trdrbot/health.py` (one new finding section).

**Current:** the compactor fails open with a print - correct policy, invisible outcome: it
shipped dead for its whole life precisely because failing open looks identical to working
(D-074; it has STILL never run live - zero `[compact]` log lines). `news_extract`'s batch
failure falls back to bare headlines with a print. A usage-ledger write failure silently
yields `model_served=[]` on the execution row - re-opening D-070's mis-attribution through
the back door, and under-reading the Coach's cost sentinel. Prints in an unattended run are
messages to nobody.

**Change:**
1. `wrap_heavy_tools(tools, config, journal=None)`; the wrapped tool's fail-open branches
   journal `kind="degraded", subsystem="compact", tool=<name>, reason=<why>` (once per tick
   per tool - a `seen` set on the wrapper closure, so a chain fetched five times is one row).
   `tick` passes its journal.
2. `news_extract.enrich(items, config, journal=None)` - the batch-failure fallback journals
   `kind="degraded", subsystem="news_extract", articles=<n>`. `evidence.gather` gains
   `journal=None` and threads it; the three source call sites and tick's direct call pass
   theirs.
3. In `tick`, after computing `model_served`: a decide cycle that made LLM calls but reads
   back an empty served list journals `kind="degraded", subsystem="usage",
   reason="no calls recorded for this cycle"` - detection at the consumer, because the
   usage callback itself runs sync-in-a-thread inside the agent loop and must not grow IO.
4. `health.check` section 3½: recent `degraded` rows grouped by subsystem →
   `WARN` (<3) / `BAD` (repeated), mirroring the error-cause section at :264-271.

**Tests:** compact's fail-open journals once per tick per tool (call the wrapped tool twice
with a bad envelope, one row); enrich's fallback journals with the batch size (monkeypatch
`build_model` to raise, the module's existing test seam); `health.check` surfaces a
`degraded` row as a warning; tick's usage detection - seam-level via a journal prefilled
with an execution row and an empty usage file is overkill; instead unit the predicate as a
small named function `_usage_went_dark(model_served, calls_made) -> bool` and test that,
wiring covered by review (state this explicitly in the WU commit).

**Edge cases:** `degraded` is a NEW kind - additive. Journal=None default keeps every
existing caller and test working unchanged.

### WU-3.5 · Delete the speculative machinery, fix the recorded posterior

**Files:** `src/trdrbot/coach_pkg/state.py` (`pinned` on `LeverState` + `load_state`/
`save_state`), `src/trdrbot/coach.py` (`record_trial`, any `pinned` reads - grep),
`src/trdrbot/report.py` (:209-215, the steering paragraph), `README.md` (the Coach section's
pinning sentence), `src/trdrbot/coach_pkg/state.py` (`Variant` docstring's `audit_rematch`
value).

**Current, verified:** `pinned` and `paused` are byte-identical in effect (both feed
`blocked`); the report and README both promise pinning "additionally stops the outcome audit
re-matching it" - an audit that does not exist (I-28, designed but unbuilt). `Variant.origin`
documents an `audit_rematch` value nothing produces. And `record_trial` computes the
posterior BEFORE appending the row it decorates, so every `trial_result` carries the
posterior of the PREVIOUS state - the recorded number is always one trial stale.

**Change:**
1. Delete `pinned` from `LeverState`, `load_state`, `save_state`, and every read (grep).
   Loaders already ignore unknown keys, so a state file on disk carrying `"pinned": false`
   loads fine and sheds the key on its next save. Report and README lose the pinning
   sentence; both now say `"paused": true` is the freeze (which is what pinning actually
   did). Keep `Entry.variant` and `Variant.origin` (drop only the `audit_rematch` doc
   value) - I-28's audit will need them.
2. `record_trial`: compute the tally, add THIS trial's counts to it, then record - so the
   posterior on row N reflects N trials. One historical caveat comment: rows written before
   D-093 are one trial stale.
3. The mutation-cooldown-burned-on-failure behaviour (cooldown consumed even when `mutate`
   returns None) is DOCUMENTED as deliberate cost control where the timestamp is saved,
   rather than changed.

**Tests:** `test_the_recorded_posterior_includes_its_own_trial` - seed an opened experiment,
`record_trial` once, assert the row's `posterior_p_challenger_better` equals
`p_challenger_better` of that single trial's counts (not 0.5). Pinned deletion: the suite is
the net (grep tests/ for `pinned` first - update any construction sites, listed per A.10).

**Behaviour delta, deliberate:** an operator who had set `pinned: true` would now find it
inert; the README told them it did something the code never did, which is the defect.
Verified against live state: `data/state/levers/muse.prompt.json` carries `"pinned": false` -
the KEY exists on disk (so the loader-ignores-unknown-keys path is what makes the deletion
safe, and the key sheds on the next save), but no pin is active.

### WU-3.6 · The stated vol forecast is scored (closes I-14, resolves 019 §11.2)

**Files:** `src/trdrbot/ledger.py` (`Entry`), `src/trdrbot/local_tools.py`
(`build_record_forecast` :695, `build_simulate_experiments`), `src/trdrbot/experiments.py`
(`simulate` + `render_comparison`), `src/trdrbot/housekeeping.py` (the matured-forecast
resolution loop - grep "Resolve matured"), `src/trdrbot/market_stats.py` (`_rolling_vol`
:80, `load_dated_closes`), `src/trdrbot/optmath.py` (`implied_vs_realized` - dead since
Phase 1 flagged it).

**Current:** the agent states a realized-vol view every cycle ("I forecast 8.5%; the condors
needed sub-7.5%") and nothing resolves it, so it moves no calibration and earns no size -
"which is most of the point of making it explicit" (I-14). Every ledger entry is implicitly
a PRICE claim: `resolve` fetches spot and checks the band. Meanwhile
`optmath.implied_vs_realized` - "the single most useful number a short-premium book has",
per its own docstring - has zero production callers, and its known unit trap is live:
`Stats.realized_vol` is a PERCENT (`vols[-1] * 100`, market_stats :119) while
`implied_vs_realized` expects fractions.

**Change - one new claim type, resolved deterministically, entering the same calibration:**

1. `Entry.metric: str = "price_band"` - the default preserves every historical row (loaders
   are drift-tolerant since Phase 1; `asdict` round-trips it). For
   `metric="realized_vol_pct"`, `band_low`/`band_high` are bounds on ANNUALIZED REALIZED VOL
   IN PERCENT (model-facing numbers are percent - the WU-2.10 convention - and the stats
   block the model reads quotes "realized vol 21d 12.3%"). `holds_at` needs no change: a
   band is a band. `price_at_horizon` (wire name, kept) stores the resolved value; its
   docstring says what it holds per metric.
2. `record_forecast` gains `metric: str = "price"` mapping to the two Entry metrics, with
   the docstring teaching the vol form: *"metric='realized_vol': band_low/band_high bound
   the ANNUALIZED realized vol in percent over entry→horizon (e.g. 7.0/9.5 = 'realized
   lands between 7% and 9.5%'). This is the claim your breakeven-vol comparison already
   makes in prose - recorded here, it is scored and moves your calibration."*
   `_vacuity_check` runs only for price claims (its bootstrap anchor is a price
   distribution; a vol analogue is future work - say so where it skips).
3. **Resolution.** New `market_stats.realized_vol_between(dates, closes, start, end) ->
   float | None` - annualized realized vol IN PERCENT over the calendar window, from the
   dated series Phase 1 added; None below a minimum sample (reuse the module's constants
   discipline). Housekeeping's resolution loop branches on `e.metric`: price entries as
   today; vol entries resolve via the stored dated closes for `e.underlying`
   (`load_dated_closes`, the 10-day staleness window callers already use) with
   `start = e.created[:10]` - and SKIP (never guess) when the series is absent, stale or
   too short, counted in the existing heartbeat's fields.
4. **`implied_vs_realized` gets its consumer.** `experiments.simulate` gains
   `realized_vol_pct: float | None = None`; when given, the FACTS section of
   `render_comparison` adds one line - entry IV vs trailing realized and their ratio via
   `optmath.implied_vs_realized(iv, realized_vol_pct / 100.0)` (**the percent→fraction
   conversion happens at this call site, explicitly, because this exact seam is the
   documented trap**). `build_simulate_experiments` computes the trailing figure from
   stored closes (`compute_stats` on `load_closes` output - already loaded for the
   bootstrap) and passes it. The golden test is UNCHANGED by construction: it passes no
   `realized_vol_pct`, and absent means absent line. Add a second golden-style case WITH
   the parameter pinning the new line's exact rendering.

**Tests** (`tests/test_vol_forecasts.py`, new):
- `realized_vol_between` on a synthetic constant-vol series recovers the known value
  (the `test_market_stats_beta.py` pattern - build with a known parameter, measure it);
  None on short/absent windows.
- Ledger round-trip: a vol entry registers, `matured`/`holds_at` behave, an OLD row without
  `metric` loads as `price_band` (write a raw legacy line, the store-resilience pattern).
- Resolution seam: seed dated closes with the real producer (`save_closes`), register a vol
  forecast whose band the synthetic series verifiably lands inside, run the housekeeping
  resolution loop (tools stubbed - vol entries must NOT fetch spot), assert
  `outcome=True` and that it now appears in `as_forecasts` → `calibration.score` counts it.
- The unit trap, pinned: `implied_vs_realized(0.12, 0.12)` == 1.0 and the render line for
  IV 12% vs realized 12% says ratio 1.0 - i.e. percent went in, fraction reached the
  function, nobody double-converted.
- Vacuity: a vol forecast skips the price-anchored check (registers fine with no closes).

**Edge cases:** a vol claim on an underlying with undated (legacy) closes cannot resolve -
skipped with the same honesty as a missing spot; the cache self-heals daily (D-091).
`as_forecasts` needs no change (it filters on stated+resolved, metric-agnostic - which is
correct: calibration asks "when I say 70%, does it happen", whatever the claim was about).

**Done when:** I-14 struck in issues.md (by this WU's commit, per the ledger's rule);
019 §11.2 noted resolved-by-wiring in D-093; the two dead functions
(`implied_vs_realized`, `vol_days`) both have production callers or - for `vol_days` - a
one-line note that it now serves `realized_vol_between`'s annualization (use it there if it
fits; delete it in place if it does not - decide while writing, state which).

### WU-3.7 · Close-out

1. Entropy audit as 021's: gross and code-only line deltas reported honestly; helper-dup
   check across new test files; trim anything the phase added that nothing uses.
2. `uv run mypy` - promote `trdrbot.health`, `trdrbot.journal`, `trdrbot.coach_pkg.state`
   into strict (their surfaces were touched and typed this phase); the 020 descope rule
   applies.
3. Live smoke: one `trdrbot tick`; `trdrbot health` (expect the degraded section absent -
   nothing degraded - and the five heartbeats reading as before); `trdrbot report` after a
   coach snapshot exists (or force one via `trdrbot coach pulse`) showing the new gauges;
   `trdrbot coach status` unchanged. State integrity: ledger trials, Brier, coach posterior
   - same checks, same expected values unless live trading moved them.
4. `D-093` decision entry: the heartbeat contract (drift shipped twice, now structural), the
   declarative lever registry with the synthetic-lever proof, the degraded-row rule, the
   pinned deletion (README promised an audit that never existed), vol forecasts as the new
   claim type with the unit-trap fixed at its named seam, and the three 019 deltas from this
   spec's header. Strike I-14 (3.6 does it); update README: pinning sentence gone, a line
   for vol forecasts under calibration, `--force` already documented from Phase 2? (check -
   add if not).
5. Restart the run loop; note the new journal kinds (`degraded`) in the log message.

## C. What this phase deliberately does NOT do

Phase 4's test restructure (splitting test_regressions.py, the ~19 remaining
source-inspection tests, contract-tier additions for polymarket and the order path); a live
second lever (one declaration away, operator's cost call - the recipe is the deliverable);
I-28's outcome audit (still blocked on resolutions existing; `Entry.variant` and the
now-honest posterior are its prerequisites, both in place after this phase); a vol-vacuity
gate (needs a vol-distribution anchor the bootstrap does not provide); renaming
`experiments.py`; anything in 021 §C not explicitly pulled in above.
