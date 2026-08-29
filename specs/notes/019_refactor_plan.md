# 019 · Refactoring plan - from hackathon organism to evolvable system

**Input:** six parallel deep reviews (core loop, LLM layer, thesis sources, trading math,
learning/memory, tests/specs) over the full source tree, cross-checked against live state,
logs, and the installed dependencies. Findings marked *verified* were reproduced by running
code, not read. Architecture research grounding the target shape:
[docs/sources/cognitive_modules_research.md](../../docs/sources/cognitive_modules_research.md).

**Written 2026-08-29.** Companion: the new I-30..I-37 entries in [issues.md](../issues.md).

---

## 0. Governing constraint and the ratchet

The refactor is **strictly behaviour-preserving** except where a verified defect contradicts
the system's own documented design (each such fix is listed in Phase 1 and is a bug fix, never
folded into a structural move). Concretely:

- **No capability regressions.** Coach, calibration, muse gauntlet, exit rules, attribution,
  idle ladder keep their exact semantics.
- **State is sacred.** Every persistent file is either untouched, read-compatible, or migrated
  with a verified round-trip (§6). The earned calibration record and competence progress
  survive intact.
- **Tests are the ratchet.** The suite passes at every commit. A test changed by a refactor is
  changed because it was coupled to *structure* (the 27 source-inspection tests), and each
  such change says so in the commit message.
- **Small reversible steps.** One concern per commit; bug-fix commits never mixed with move
  commits; any step is a one-commit revert.
- **Fixes are verified the way the defects were found:** run the code, paste the number.

## 1. The diagnosis, distilled

Six reviews converged, independently, on the same five structural facts:

1. **The system's own principles are unenforced.** `docs/principles_coding.md` mandates ruff +
   mypy strict as non-negotiable; neither is configured (265 ruff errors at default settings).
   The vacuum was filled by 27 tests that string-match source text - which will shatter under
   any refactor while missing actual regressions.
2. **Every hard-won pattern exists, once, next to N places that lack it.** Atomic write: 1 of
   ~12 writers (`coach.save_state`). Skip-bad-line JSONL reading: 4 of 6 readers, 4 different
   policies (`journal.read` and `CalibrationStore` - the two most critical - guard nothing).
   Reply-text flattening: the good version (`tick._text_of`) has 1 call site, 6 inline copies
   elsewhere. Failure-renders-into-prompt: research does it; discovery and muse tell the model
   "(none)" when the API failed. The refactor's core job is *promotion of existing good
   patterns to their whole population*, not invention.
3. **The seams the bugs came from are untyped.** The bug history (D-001..D-090, ~38 defects)
   is dominated by seam drift, unit confusion, and silent no-ops - and the seams involved are
   `dict[str, Any]`: the `shared` cross-tool bus, the 25-key sim result, opportunity payloads,
   exit-rule dicts, journal rows (4 silently-drifted shapes on `decision` alone).
4. **The deterministic safety path is more killable than the advisory paths.** Sensors,
   analytics, hunt, muse, coach all degrade gracefully; `reconcile` → `learn` → `exit_rules` -
   the capital-protection spine - has no containment, so a corrupt `minds.json`, one malformed
   exit-rule threshold, or a symbol-less broker row disarms stop evaluation for the tick
   (verified). INV-8's logic applied everywhere except where it matters most.
5. **Chassis guarantees drifted from spec.** The production run loop (`trdrbot run`) never
   takes the tick lock (INV-7 unenforced on the only unattended path); `watchdog_seconds` is
   configured and read by nothing (FM-26 unmitigated); the langgraph 1.x upgrade silently
   inverted tool-error handling so a transport blip now kills the decide cycle and burns every
   inbox item's retry budget (verified against installed deps).

Plus six verified wrong-number defects in production now (Phase 1 table).

## 2. The target shape

### 2.1 Cognitive modules - the organizing principle

Per the research brief: the module boundaries this system already has (muse, research,
discovery, decide, coach, calibration, attribution, memory) are the right ones - they map
cleanly onto the CoALA frame and the inbox is a textbook blackboard. What upgrades a subsystem
from "a file" to "an evolvable cognitive module" is not the boundary but five properties:

1. **Stable typed contract** at its seam (Opportunity in, verdict out).
2. **Owned policy surface** - prompts/thresholds as versioned, fingerprinted data (the Coach's
   lever files, generalised).
3. **Own metric**, computable before P&L where possible. No metric → it is honestly a fixed
   workflow (exit rules, reconcile), which is fine and stays deterministic.
4. **Own heartbeat separate from its output** (the existing health rule) + own test file.
5. **Cheap lever hook** - registering a policy artifact with the Coach is uniform, not bespoke.

The boundary test: *a module is correctly drawn iff it can be improved without editing another
module's code, judged by its own metric, and rolled back by reverting its own state.*

The evolvable unit stays **policy-as-data, never code** - the literature (DSPy, AlphaEvolve's
evaluator lesson) independently confirms D-088's touches-data-never-code rule. And boundaries
live at seams that survive model improvement: stores, metrics, provenance, evaluation - never
reasoning microstructure.

### 2.2 Module map (target)

| Module | Contract in → out | Policy surface | Metric | Heartbeat |
|---|---|---|---|---|
| research | universe → dossiers + Opportunities | RESEARCH_PROMPT | opportunities admitted / emitted | `research` row |
| discovery | news → nominees → Opportunities | 2 prompts | gauntlet survival | `discovery` row (incl. empty runs) |
| muse | concepts×news → Opportunities | MUSE_PROMPT (lever v1) | gate survival (Coach reward) | `muse` row |
| decide | Inbox batch → ≤1 action | SYSTEM_PROMPT + tool contracts | calibration Brier / attribution rate | `decision`/`no_op` rows |
| exit rules | positions + marks → closes | *(none - fixed workflow)* | — | `exit` rows |
| calibration | forecasts → Brier/Murphy | *(math)* | its own score | resolution rows |
| attribution+learn | closed positions → credit | ATTRIBUTION_SIGNAL table | attributable rate | `learn_run` row (**new**) |
| coach | trial events → promotions | MUTATE_PROMPT + sentinels | posterior + sentinels | `coach_run` row |
| memory (elfmem+wiki) | queries → context | constitution, lessons | recall relevance (I-18 contract test) | wiki_guard / sweep rows |

### 2.3 Layering

Three layers, enforced by import direction (and eventually by lint):

- **Pure core** (no IO): optmath, calibration math, sizing, competence rules, coach posterior,
  idle ladder, exit-rule evaluation logic.
- **Stores** (one module per persistent concern, all atomic, all schema-tolerant): journal,
  ledger, calibration store, positions, wiki, inbox, lever state, usage - built on one shared
  `store.py` (append-only JSONL + `write_atomic`).
- **Orchestration** (the only layer that touches network/LLM/clock): tick, housekeeping, cli,
  sensors, the three sources' `run()`, mcp_client, llm.

What stays exactly as it is: `build_model`/`resolve_model_spec` (correctly sized), the
three-source blackboard, the prompts-in-code convention, the FACTS/MODELLED discipline, the
deterministic gauntlets, elfmem integration, journal-first ordering, the regression-test
docstrings (institutional memory - survive verbatim).

## 3. Phase 0 - safety net (before anything moves)

0.1 **Wire ruff.** `[tool.ruff.lint] select = ["E","F","B","SIM","UP","I","PT"]`; fix
    `test_regressions.py:1308`'s indentation-sensitive assertion *first*; `ruff check --fix`
    (185 auto); triage the rest. No `ruff format` until the source-inspection tests are triaged.
0.2 **Wire mypy strict, module-by-module** starting with the pure core (optmath,
    calibration, sizing, competence). Expect it to surface real `float | None`
    absence-as-zero handling - that is the point.
0.3 **Behavioural tests for the credit spine.** A `FakeElfmem` honouring the documented
    contract; characterization tests invoking `attribution.run()` and `learn.on_resolution()`
    for real. This is the densest historical bug cluster (D-056/57/58/59/72/73) and today has
    *zero* behavioural coverage - eleven source-inspection tests police it by grep. Required
    before Phase 1.9 and any Phase 2 touch of learn/attribution.
0.4 **Snapshot state.** `data/state` + `data/wiki` + journal copied aside before Phase 1 lands
    (one `tar` line in the plan-execution commit message). Cheap undo for everything below.
0.5 **conftest.py**: shared `paths(tmp_path)` / `cfg(tmp_path, **overrides)` fixtures; kill the
    five `Path("/tmp")` call sites (they create `/tmp/state` on the dev machine) and the two
    incompatible `_cfg` helpers.

## 4. Phase 1 - stop the bleeding (verified defects; bug fixes, not refactors)

Each row = one commit, smallest possible diff, its own regression test. Ordered by severity.
None of these is a behaviour *change* against design intent; every one restores a documented
guarantee. (The one genuine semantics decision - 1.9 - is flagged.)

| # | Defect (all verified) | Fix | Size |
|---|---|---|---|
| 1.1 | langgraph 1.x re-raises tool errors: a transport blip kills the decide cycle, mis-burns every item's retry budget, and can leave a filled order unjournalled | `ToolNode(tools, handle_tool_errors=True)` into `create_react_agent` (tick.py:463) | 1 line |
| 1.2 | `trdrbot run` never takes the tick lock → INV-7 unenforced; second lock impl (`_acquire_run_lock`) weaker + relative path | wrap loop body in `tick_lock`; delete `_acquire_run_lock` | −10 lines |
| 1.3 | Watchdog configured, unimplemented (FM-26): hung LLM call stalls the 8-day run | `asyncio.wait_for(agent.ainvoke(...), config.watchdog_seconds)`; TimeoutError → existing TRANSIENT path | 2 lines |
| 1.4 | Memory failure disarms exit rules: `learn.on_fill/on_resolution` unguarded on the fast path | wrap both reconcile call sites advisory-style; add `learn_run` heartbeat | ~10 lines |
| 1.5 | Fast path killable: malformed exit-rule threshold parses to a live stop at breakeven (`_pct`→0.0); one bad rule aborts evaluation for every position; symbol-less broker row KeyErrors reconcile | `_pct`/`_normalise` return None on malformed (drop rule loudly); per-position try in `exit_rules.run`; `by_symbol` skips bad rows | ~15 lines |
| 1.6 | `beta` aligns closes by array position, no dates; QQQ reads +0.10 (R² .004) vs +1.48 (R² .84); feeds the concentration warning | store `(date, close)` pairs; align on date intersection; old files degrade to `ASSUMED_BETA` (honest) | ~30 lines |
| 1.7 | `book_greeks` prices calendars at leg[0]'s expiry → riskless-looking zeros; `require_single_expiry` guards only an unreachable path | call the guard in `book_greeks`, count into `positions_skipped`; guard rejects partial expiry population | ~10 lines |
| 1.8 | Unguarded `json.loads`: one truncated line in `forecasts.jsonl` kills every tick at construction; same for `journal.read` (ground truth, least tolerant reader) | per-line skip-and-count, matching ledger/health | ~8 lines |
| 1.9 | **Double crediting** (semantics decision): `learn.on_resolution` credits blocks 0.9/0.1 by P&L at close; attribution judges the same blocks at horizon; a lucky win takes +0.9 then "learn nothing" - installing the superstition the README's core table forbids | defer block credit to attribution (keep the calibration resolve + `mind_outcome` at close), per `ATTRIBUTION_SIGNAL`'s own docstring; cross-reference the two files | ~10 lines |
| 1.10 | Non-atomic full-file rewrites on ledger/calibration/positions/sensors/minds/high-water/wiki (`ledger.jsonl.bak-before-repair` says this already bit) | promote `coach.save_state`'s tmp+`os.replace` to `store.write_atomic`; adopt at all writers | ~20 lines |
| 1.11 | Inbox floods: opportunity ids are uuid4-unique by construction; 22 pending items on disk incl. XLE ×6 with byte-identical bands | content-hash id for `type=="opportunity"`; `write` no-ops on existing pending id (uuid4 stays for news/fills) | ~10 lines |
| 1.12 | Muse/coach trial integrity: one malformed candidate (`"probability": null`) aborts both arms; `_open` orders state-before-event (crash = permanently stuck lever); duplicate `run_nonce` double-counts in the posterior | per-candidate try; swap `_open` ordering to match `_close`/`_promote`; dedup `(exp_id, run_nonce)` in `tally` | ~12 lines |
| 1.13 | Discovery's options gate counts the substring "symbol" in `str(response)` - an error payload scores tradeable; also breaks permanently if compaction ever runs first | parse the actual contract list | ~10 lines |
| 1.14 | Odds-failure divergence: discovery/muse render API failure as "(none)" | shared failure convention "(odds unavailable: X)" (fold into Phase 2 `evidence.py`, or 2-line interim) | 2 lines |
| 1.15 | High-water fail-open: corrupt file resets drawdown to 0 → demotion silently off | fail loud (skip demotion *update*, journal a degraded row, keep last posture) | ~6 lines |
| 1.16 | Clock split: deadline compared in local time in the run loop; attribution horizons/`Entry.matured`/DTE via `date.today()` on UTC-stamped data; Saturday gate fires Friday 20:30 ET | one `ids.today()` (UTC) + ET where market semantics demand; replace all `date.today()` | ~15 sites |
| 1.17 | Compaction has *never executed live* and its table omits the OCC symbol the agent needs to trade | render `occ` column; then force one live `get_option_chain` before the deadline and read the log | ~5 lines + a live check |
| 1.18 | `model_served` honesty gap on positions: `generated_by=config.model` is the chain head, not who answered (the D-070 defect, half-fixed) | stamp the chain at open + served list at close, mirroring the journal fix | ~5 lines |

Also in this phase, zero-risk deletions (all verified dead): `_market_pulse` remnants are
already gone, but `research._valid_opportunity`, `wiki.should_mint`, `Concept.verify/trust_tier`,
`build_size_position`'s unread `open_count`, the three ignored `start` params in optmath,
`housekeeping`'s unused `Config as _C`, `cli`'s duplicate imports, `tick.py`'s unused `sensed`
(wire it into the verbose line + return dict instead - it is the only fast-path subsystem whose
output the tick discards), and the three permanently-red OpenCode-Zen contract tests.
Decide-and-delete: `implied_vs_realized`/`vol_days` (dead, tests-only) - either wire the I-14
consumer (fixing the percent/fraction trap at `Stats.realized_vol`) or delete ~60 lines; wiring
it is most of I-14 and the better move. **RESOLVED (D-093, WU-3.6): both, one each.**
`implied_vs_realized` was wired - and wiring it revealed the function was wrong by 20% in the
direction that says sell (I-38), which is the argument for the "wire it" branch stated better
than the plan managed. `vol_days` was deleted: its only stated purpose was the conversion that
turned out to be the defect.

## 5. Phase 2 - foundations (structure; strictly behaviour-preserving)

**2.1 `store.py`** - the one new module that earns its place:
`write_atomic(path, text)`, `append(path, kind, **fields)` (stamps `id`, `ts`, `v`),
`read(path)` (skip-and-count, one policy). Adopt across journal, coach events/metrics, usage,
ledger, calibration. Ledger `Entry` construction becomes drift-tolerant (ignore unknown keys)
so a schema change stops silently *deleting* incompatible history on the next rewrite. The `v`
field is what makes the next schema change auditable - the journal has already drifted 4 ways
on `decision` alone with no way to tell populations apart.

**2.2 `llm.py` grows three functions, no classes:** `ask(config, role, prompt) -> str`
(deletes 6 inline invocation copies; promotes `tick._text_of`); `parse_json_array/object`
(moved from `research._parse_json_block` + salvager - 4 modules import a private sibling name
today, one via a cycle-dodging local import; callers state their expected shape, deleting three
per-caller unwrap hacks). Envelope unwrapping single-homed in `mcp_client.unwrap`.

**2.3 `opportunity.py`** - typed `Opportunity` dataclass + one `admit(...) -> defect | None`
folding `opportunity_defect` + `_plausible_band` + horizon window + options gate;
`Inbox.write_opportunity(op, source=)`. Research instantly gains the three gates it lacks
(it is currently the unguarded source - the D-035 dollar-band bug is still open there); muse
stops hand-building a payload that would fail the shared check. Sources keep their own
prompts, evidence, and extra gates - only "may this enter the inbox" is shared.

**2.4 `evidence.py`** - one `gather(tools, config, *, symbols, news_limit)` for the 3× news
and 3× odds copies, with the one failure convention (1.14).

**2.5 Wiki as a real store:** atomic writes; `append_log` actually appends (today it rewrites
the full history); `path_for` rejects `..`/absolute (LLM-controlled path components reach it);
`encoding="utf-8"` everywhere (zero `encoding=` args exist in src/); `read()` degrades like
`all_concepts` already does; one `dossier(ticker, **fields)` template shared by research +
discovery (deletes the copy-paste-policing test); staleness checked on the *read* path (regime
is stale-on-disk right now and still injected); `_sample_concepts` uses `all_concepts` and
skips deprecated; backfill `stale_after` on the 24 legacy dossiers.

**2.6 Typed cross-tool seam:** `SharedContext` dataclass replaces tick's bare `shared` dict;
`SimResult` replaces the 25-key dict; a `Structure` object built once per candidate (hoisting
`entry_cost` out of 726k `pnl_at` calls and memoising the grid - measured ~1.0-1.5s per
candidate today, expect ~10×); structures matched by leg key, deleting the by-value R:R
tolerance match; `Leg.from_position_leg` single-homes the side-vocabulary rule that currently
has three disagreeing copies.

**2.7 Config singularity:** pass `config` into `housekeeping.run` (deletes 3 disk reloads per
run) and `prompts._active_muse_prompt` (deletes a `load_dotenv` + mkdir inside every decision
write); the run loop's config becomes the single authority. Move cost caps inside
`muse.run`/`research.run` (the CLI bypasses both today; the journal shows 9 muse rows against
a cap of 3 on 2026-08-29).

**2.8 Decompose without dissolving:** `tick._build_decide_prompt(...)` and
`_build_decide_tools(...)` out of the 395-line `_run_tick`; orchestration ordering stays
inline and visible (the D-019 ordering guarantees are the module's whole point). `coach.py`
splits on its existing seams into `coach/{posterior,mutate,gauges,__init__}.py` - pure
numerics testable without a filesystem, and the 5 cycle-dodging local imports disappear.
`cli` dispatch via `set_defaults(func=...)` (−40 lines, one class of typo).

**2.9 Percent/fraction:** the pragmatic middle of the two reviewers' positions. No wrapper
types yet: (a) rename the fraction-valued `_pct` names (`position_pnl_pct` → `_frac`, interim
bands) so the suffix means one thing; (b) mypy strict makes `float | None` guards mechanical
(the absence-as-zero class); (c) conversions happen only at the LLM tool boundary
(`local_tools`), where percentages legitimately enter. Escalate to `NewType` only if a unit
bug ships *after* this - per the house rule: machinery on demonstrated need.

## 6. Migration safety (every persistent artifact)

| Artifact | Treatment | Verification |
|---|---|---|
| `journal.jsonl` | untouched; new rows gain `v` | old readers `.get()` - already tolerant |
| `ledger.jsonl` | untouched; loader becomes drift-tolerant | round-trip: parse → rewrite → byte-compare on live copy |
| `forecasts.jsonl` | untouched; reader hardened | same round-trip |
| `elfmem.db` | **never touched** | — |
| wiki pages | content untouched; writes become atomic; legacy dossiers gain `stale_after` only | augmentation guard already refuses loss |
| lever state | untouched (already atomic) | fingerprints recomputed = unchanged |
| `returns/` closes cache | new format `(date, close)`; old files unusable *for beta* → honest `ASSUMED_BETA` until refreshed (≤1 day) | live beta spot-check vs known pairs |
| `model_calibration.json`, high-water, sensors, minds | format untouched; writes atomic | — |
| usage / experiments / metrics | untouched; appends via store.py | — |

Phase-0 snapshot is the blanket undo.

## 7. Phase 3 - the evolution enablers

3.1 **Uniform lever registration.** Extract what `muse.prompt` needed into the cheap path:
    declare artifact + metric hook → the Coach can trial it. Candidate second lever (only when
    wanted): discovery's nomination prompt, scored by its existing gauntlet - same shape as the
    muse's. This is the generalization the research brief calls the real payoff.
3.2 **Health probes derived from journal kinds** - one artifact instead of two hand-synced
    lists (D-074/D-082 were both the drift between them); a `Journal.nothing_happened(reason=)`
    helper so "ran but produced nothing" is authored, not inferred.
3.3 **Per-module metrics in `report`** - each module's metric from §2.2 on the existing gauge
    chart, so "is the muse getting better" is a glance, not a grep.
3.4 **Journal degraded-rows** from the fail-open sites (compact, usage, news_extract) so a
    subsystem broken for a day is visible to `trdrbot report` (D-038 applied to the
    instrumentation itself).
3.5 **Delete speculative coach machinery:** `pinned` (byte-identical to `paused` in effect),
    `Variant.origin="audit_rematch"`, the report's pinning claim. Keep `Entry.variant` -
    provenance cannot be backfilled, and I-28's audit will need it.

## 8. Phase 4 - test restructure (after 0-2, never before)

4.1 Convert or retire the 27 source-inspection tests: behavioural where Phase 0.3's fakes
    reach; type/import-boundary where mypy + `__all__` now enforce; for genuine structural
    rules (muse gate order - inspected five times today), encode the cascade as a data table
    and assert on list order.
4.2 Split `test_regressions.py` (3,638 lines) by module along its own section banners -
    `test_optmath`, `test_market_stats`, `test_calibration_and_sizing`, `test_exit_and_risk`,
    `test_memory_and_credit`, `test_ingest`, `test_ledger_and_wiki`, `test_config_pins`,
    `test_health` - **every docstring preserved verbatim** (they are the institutional
    memory). Config-value pins get their own clearly-labelled file.
4.3 Contract tier rebalance: delete the 3 Zen tests (models out of every chain); add the two
    missing seams - `polymarket.py` (152 lines, 3 dependants, zero tests) and the Alpaca
    *order* path; probe roles for doctor derived from config instead of a hardcoded five.
4.4 Session-scope `_fair_zoo` (kills most of the 17s hot spot); resolve the 3
    `SocketBlockedError` warnings explicitly.
4.5 Malformed-state tests: the six high-severity Phase 1 defects all lived where the suite
    only ever fed clean, aligned inputs. Each Phase 1 fix lands with its malformed-input test.

## 9. Explicitly not doing (from all six reviews, unanimous)

No DI container, plugin framework, message bus, module base-class hierarchy, LLM client class,
provider abstraction, role→tools registry table (one role has tools), repository layer over
the YAML store, store-construction registry, unit-wrapper types (yet - §2.9), typed classes
for all 25 journal kinds (the `v` field buys most of it), config keys for the
measured-constants-in-code (the comments carry incident history a YAML key would lose), and no
`ruff format` sweep until the string-matching tests are gone.

## 10. Sequencing

```
Phase 0  safety net          ~½ day    (ruff, mypy core, credit-spine tests, snapshot)
Phase 1  stop the bleeding   ~1 day    (18 small fixes, each own commit + test)
Phase 2  foundations         ~1½ days  (store/llm_json/opportunity/evidence, wiki,
                                        typed seams, config, decompositions)
Phase 3  evolution enablers  ~½ day
Phase 4  test restructure    ~1 day    (can interleave after Phase 2)
```

Order within phases is dependency order as written. The competition deadline is 2026-09-04:
Phases 0-1 are worth doing **before** the deadline (they fix live wrong numbers and unattended-
run fragility); Phases 2-4 are the post-hackathon foundation and can proceed at leisure. If
only one day exists, do Phase 0.1 + Phase 1 rows 1.1-1.8.

## 11. Open decisions for the operator

1. **1.9 (double crediting)** - the one semantic change. The fix implements the README's own
   table; the alternative (low-weight interim credit at close) preserves a "money teaches a
   little" signal the design explicitly rejects. Recommended: defer credit to attribution.
2. ~~**`implied_vs_realized`** - wire its consumer (≈ I-14, recommended) or delete it.~~
   **DONE (D-093):** wired into `render_comparison`, and the wiring found the function itself
   defective (I-38). `vol_days` deleted.
3. **Muse cap semantics** - should the CLI honour `MUSE_RUNS_PER_DAY`? Recommended: yes, with
   `--force` to override; the cap moves inside `muse.run` either way.
