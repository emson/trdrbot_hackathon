# 020 · Phase 0+1 implementation spec (LLM-executable)

The first executable phase of [019_refactor_plan.md](019_refactor_plan.md): the safety net
(Phase 0) and the verified-defect fixes (Phase 1). Written for an LLM implementer. Every
claim below was verified against the actual source on 2026-08-29; line numbers are from that
snapshot - **re-read the named region before editing, and trust the file over this document
if they have drifted.**

---

## A. Global rules (read first, apply to every work unit)

1. **One work unit (WU) = one commit.** Commit message starts `WU-<n>:`. Bug-fix WUs are
   never mixed with cleanup WUs. Any WU is a one-commit revert.
2. **The suite is the ratchet.** `uv run pytest` green before AND after every WU; paste the
   summary line into the commit message. Never weaken an assertion, delete, or skip a test to
   get green - the two deliberate test replacements in this phase (WU-1.9, noted inline) are
   explicit, documented steps.
3. **Every bug-fix WU carries its regression test**: written first, shown failing for the
   bug's reason, then passing. Name it for the bug, put the incident in the docstring - that
   is this repo's institutional-memory convention (see any test in `test_regressions.py`).
4. **Test at the seam, not the unit.** This project measured its own bug history: essentially
   none were caught by unit tests on pure functions; they were wrong beliefs about seams and
   silent no-ops (`docs/principles_testing.md`, trdrbot overlay). So:
   - Prefer tests that run real stages together on `tmp_path` stores (the
     `test_loop_smoke.py` shape) with **producer-derived inputs** - build inputs with the
     real producer (`market_stats.save_closes`, `PositionStore.save`, `Inbox.write`), never
     hand-rolled literals that can drift from the caller.
   - Fake at the adapter boundary only (`ElfmemAdapter`, MCP tools dict). Never patch
     internals of the module under test; never assert call counts unless the call IS the
     contract.
   - The gap all six review agents found: the suite feeds only clean, well-formed inputs.
     Every fix below lands with its **malformed-input** test.
   - Do NOT add `inspect.getsource` string-matching tests. Ever.
5. **Preserve every guard and every docstring you touch.** The comments carry measured
   incident history; they are worth more than the code around them. When a change makes a
   comment false, update the comment in the same WU.
6. **Verify APIs by running them** (`uv run python -c "..."`), especially langgraph/langchain
   imports - versions installed: langgraph 1.2.11, langchain 1.3.17, langchain-core 1.6.0.
7. **State files are sacred.** Never hand-edit or regenerate `data/journal.jsonl`,
   `data/state/ledger.jsonl`, `data/state/forecasts.jsonl`, `data/state/elfmem.db`,
   `data/wiki/**`. Code may write them only through existing code paths.
8. Conventions: plain dashes (no em dashes), no co-author trailers on commits, constants
   named in code with rationale comments (NOT moved to config.yaml).
9. **Bookkeeping at the end of the phase** (its own commit): add one decision entry `D-091 -
   Phase 1 hardening from the 019 review` to `specs/decisions.md` summarising what landed,
   and strike each fixed item in `specs/issues.md` (I-30..I-37 as applicable) with
   `~~...~~ FIXED <date> (D-091)`, per the ledger's own rule.

**Execution order:** WU-0.1 → 0.2 → 0.3 → 0.4 → 0.5, then WU-1.1 … 1.19 in order.
Dependencies are noted where they bind (1.9 needs 0.4; 1.10 before 1.15).

---

## B. Phase 0 - the safety net

### WU-0.1 · State snapshot (do this before anything else)

```bash
tar -czf ../trdrbot_state_backup_$(date +%Y%m%d_%H%M).tgz data/ logs/run.pid
```
Check no run loop is live first (`cat logs/run.pid`, `ps -p <pid>`); if one is running, stop
it for the duration of this phase. This tarball is the blanket undo for the whole phase - name
it in the WU-0.1 commit message (the tarball itself stays untracked, outside the repo).

### WU-0.2 · Wire ruff

`pyproject.toml`, new sections:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "B", "SIM", "UP", "I"]
ignore = ["E501"]   # long rationale comments are house style; do not reflow them
```

Then: `uvx ruff check src/ tests/ --fix`, triage the remainder by hand. Constraints:

- **Do NOT run `ruff format`.** 27 tests string-match source text (they are retired in later
  phases); a formatter breaks them wholesale. `--fix` (unused imports, `==`/`is`, upgrade
  syntax) is safe, but after fixing run the full suite and if any `inspect.getsource` test
  fails, revert the specific autofix in that function rather than touching the test.
- The known unused imports the fix should remove include: `housekeeping.py:116`
  (`Config as _C`), `research.py:30` (`ids`), `cli.py:250` (duplicate `run_tick` import),
  duplicate `Journal` imports inside `cli` command functions.
- `tick.py:264-266` has broken indentation (args at col 8, closing paren at col 4) on the
  `analytics.snapshot(` call - fix it by hand while there.
- Remaining violations that are real findings (not style) get fixed only if trivially safe;
  otherwise list them in the commit message as deferred.

### WU-0.3 · Wire mypy (bounded)

`uv add --group dev mypy types-PyYAML`. Config:

```toml
[tool.mypy]
files = ["src/trdrbot"]
python_version = "3.11"
ignore_missing_imports = true      # langchain/langgraph/elfmem/yfinance ship no stubs

[[tool.mypy.overrides]]
module = ["trdrbot.optmath", "trdrbot.calibration", "trdrbot.sizing",
          "trdrbot.competence", "trdrbot.ids", "trdrbot.failures", "trdrbot.lock"]
strict = true
```

Run `uv run mypy`. Fix what surfaces in the strict modules (expect `float | None`
absence-handling issues - that is the point; each fix preserves behaviour). If a strict
module surfaces more than ~20 errors, downgrade that module to
`disallow_untyped_defs = true` for this phase and note it in the commit. The rest of the
package only needs to *pass* the lenient global pass. Do not chase strictness into
orchestration modules in this phase.

### WU-0.4 · Behavioural tests for the credit spine (prerequisite for WU-1.9)

The attribution → learn → elfmem path produced six decision records of bugs
(D-056/57/58/59/72/73) and today has **zero behavioural coverage** - it is policed by eleven
`getsource` string-matches. Before touching it, give it real tests.

New files: `tests/conftest.py` (see WU-0.5 - build them together) and
`tests/test_memory_and_credit.py`.

**`FakeMem`** - a fake at the adapter boundary, honouring `ElfmemAdapter`'s public surface as
used by `learn.py`, `reconcile.py`, `exit_rules.py`, `attribution.py` (read
`elfmem_adapter.py` in full first; the contract notes are in its docstrings):

```python
class FakeMem:
    """In-memory stand-in for ElfmemAdapter. Honours the real contract:
    weight <= 0 raises ValueError (elfmem's _validate_weight); credit_blocks
    returns (requested, applied); records every signal for assertions."""
    def __init__(self):
        self.credited: list[tuple[str, float, float, str]] = []  # (block, signal, weight, source)
        self.mind_outcomes: list[tuple[str, bool]] = []
        self.remembered: list[str] = []
        self.fail_with: Exception | None = None   # set to make any call raise
    async def remember_thesis(self, pos): ...      # returns f"blk_{pos.position_id}"
    async def predict(self, pos): ...              # returns f"mind_{pos.position_id}"
    async def resolve(self, pos, *, hit, signal, weight=1.0, interim=False): ...
    async def credit_blocks(self, block_ids, signal, *, weight=1.0, source=""): ...
    async def assemble_context(self, query): ...   # ContextResult(text="", blocks={})
    async def begin(self, task_type=""): ...
    async def end(self): ...
    async def close(self): ...
```

`resolve` must mirror the real one's composition (mind outcome when
`pos.mind_decision_block_id` and not interim, then `credit_blocks(pos.all_elfmem_block_ids,…)`)
so tests exercise the real learn.py logic against a faithful fake, not a hollow one.

**Characterization tests** (pin CURRENT behaviour; WU-1.9 changes two of them as an explicit,
documented step). All build positions through the real `PositionStore` on `tmp_path`, real
`Journal`, real `Wiki`:

1. `test_external_close_with_known_pnl_credits_blocks_at_close` - build an open Position with
   `elfmem_blocks={"attention": {"b1": 0.9}}` and `last_pnl_pct=0.5`; call
   `learn.on_resolution(..., pnl_pct=None, calibration=store)`; assert the fallback picked up
   0.5, blocks credited with signal 0.9, calibration resolved True, a `reflection` row
   journalled, a lesson heading written.
2. `test_resolution_with_no_pnl_skips_credit_and_says_so` - no pnl anywhere; assert zero
   credits, `credit_assigned=False` in the reflection row, lesson written with "not scored".
3. `test_reconcile_confirms_fill_and_remembers_thesis` - `opening` position whose leg symbol
   appears in a `Snapshot(broker_positions=[{"symbol": ...}])`; run `reconcile.reconcile`;
   assert status open, thesis block added at similarity 1.0, `fill` row journalled.
4. `test_reconcile_phantom_close_routes_to_resolution_exactly_once` - open position absent
   from broker; assert transition to closed/external, one reflection row; run reconcile again
   and assert no second reflection (INV-17 through the real transition guard).
5. `test_attribution_credits_by_verdict_at_horizon` - read `attribution.py` fully first.
   Closed position with `thesis_claim/horizon/bands` set, horizon in the past,
   `last_pnl_pct` set; provide the spot the way production does (write the closes file with
   the real producer `market_stats.save_closes` - check how `attribution._spot` actually
   reads it and feed that path); assert blocks credited with the `ATTRIBUTION_SIGNAL` value
   for the quadrant, weighted by `credit_weights()`, and the lucky-win quadrant
   (`held=False, profited=True`) credits nothing.

These are seam tests: real learn + real store + real journal + fake memory. That is the
loop-smoke shape, which is where this project's bugs actually live.

### WU-0.5 · conftest.py and the /tmp leak

- Create `tests/conftest.py` with two fixtures usable by new tests:
  `paths(tmp_path)` returning a real `config.Paths.build(tmp_path)` with `.ensure()` called,
  and `make_position(**overrides)` building a valid open `Position` with one OCC leg (take
  the shape from a live page in `data/wiki/positions/` - producer-derived, and note in the
  docstring which file it mirrors).
- `tests/test_coach.py` has five call sites passing `Path("/tmp")` into its `_cfg` helper
  (lines ~67, 76, 86, 107, 114), which creates `/tmp/state` on the developer machine -
  violates test-principles non-negotiable #5. Change them to use `tmp_path`.
- Do NOT mass-migrate `test_regressions.py` helpers in this phase (that is Phase 4).

---

## C. Phase 1 - the eighteen fixes

Each WU below: **Files / Current / Change / Tests / Edge cases / Done when.**

### WU-1.1 · Tool errors must not kill the decide cycle (I-31)

**Files:** `src/trdrbot/tick.py:463`, new test in `tests/test_regressions.py`.

**Current:** `create_react_agent(model, agent_tools, prompt=SYSTEM_PROMPT)` lets langgraph
build `ToolNode(tools)` with the ≥1.0 default: only pydantic argument-validation errors
become ToolMessages; **every runtime exception re-raises** (verified against installed
langgraph 1.2.11, `prebuilt/tool_node.py:383-395`). A dead MCP subprocess or a raise inside
`record_position` escapes `agent.ainvoke` into the except at `tick.py:570`, which classifies
TRANSIENT and calls `inbox.record_failure` on every pending item - three such blips
dead-letter every opportunity. Worst case: the raise lands after an order filled, so the
`execution` row is never journalled and the "order placed but record_position was not
called" warning at `tick.py:626` never runs.

**Change:** construct the ToolNode explicitly with the pre-1.0 semantics the whole design
assumes. Add a small factory so the test exercises the production construction:

```python
def decide_tool_node(agent_tools: list) -> "ToolNode":
    """Runtime tool errors become ToolMessages the agent can react to, not
    crashes that burn every inbox item's retry budget (langgraph >= 1.0
    inverted this default; guards return refusal STRINGS by design)."""
    from langgraph.prebuilt import ToolNode
    return ToolNode(agent_tools, handle_tool_errors=True)
```

and in `_run_tick`: `agent = create_react_agent(build_model(...), decide_tool_node(agent_tools), prompt=SYSTEM_PROMPT)`.
First verify by running: `create_react_agent` accepts a ToolNode instance for `tools`, and
the `ToolNode` import path, against the installed version (rule A.6).

**Tests:** `test_a_runtime_tool_error_becomes_a_tool_message_not_a_crash` - build
`decide_tool_node([raising_tool])` where `raising_tool` is a real `StructuredTool` whose
coroutine raises `RuntimeError("mcp pipe broke")`; invoke the node with a tool-call message
(copy the invocation shape from langgraph's own ToolNode tests - verify by running);
assert it RETURNS a ToolMessage containing the error, and does not raise. Docstring carries
the incident (langgraph 1.x default change, verified 2026-08-29).

**Edge cases:** guard/compaction wrappers return plain strings on refusal - unchanged,
they are results, not errors. `tool_guard.redirect_whole_book_close` returns a bare string -
also unchanged.

**Done when:** test passes; a full `uv run pytest` is green; `uv run trdrbot doctor` still
passes (construction path shared).

### WU-1.2 · The run loop takes the tick lock (I-34a)

**Files:** `src/trdrbot/cli.py` (`_run_loop` ~:235-283, `_acquire_run_lock` ~:204-232).

**Current:** `trdrbot run` calls `run_tick` directly - no `tick_lock` - so INV-7 is
unenforced on the only unattended path; `run.sh`+launchd alongside `trdrbot run` interleave
freely. `_acquire_run_lock` is a second, weaker lock (bare PID, no timestamp, never unlinked
on exit) at the codebase's only relative path (`Path("logs/run.pid")`).

**Change:** inside the loop body, wrap the tick exactly as `cli._tick` does:

```python
try:
    with tick_lock(cfg.paths.state / "tick.lock"):
        r = await run_tick(cfg, verbose=True)
    open_now = bool(r.get("market_open", r.get("status") != "housekeeping"))
except BlockingIOError as exc:
    print(f"[run] {exc}", flush=True)     # another tick holds it - skip, sleep the OPEN interval
    open_now = True
except Exception as exc:  # noqa: BLE001 - a bad tick must not end the run
    ...existing handler...
```

Delete `_acquire_run_lock` and its call site + the `pid_path` lines entirely (it adds nothing
`tick_lock` does not do better). Keep `MIN_INTERVAL_SECONDS`. The `__import__('os')` hack in
the startup print becomes a normal `os.getpid()` with a top-level import.

**Tests:** `test_run_loop_holds_the_tick_lock_around_each_tick` - call
`cli._run_loop(interval=..., closed_interval=..., max_ticks=1, allow_fast=True)` with
`trdrbot.tick.run_tick` monkeypatched (this is the seam, not an internal) to a probe that
asserts `cfg.paths.state / "tick.lock"` exists during the call and returns
`{"market_open": False, "status": "housekeeping"}`. Note `_run_loop` loads config itself -
monkeypatch `config_mod.load` to return a `tmp_path`-rooted config (build it with the real
`config.load(root=tmp_path)` against a minimal copied `config.yaml` + empty `.env` - the real
producer). Second test: with the lock already held by a live-PID JSON file, the patched
`run_tick` must NOT be called and the loop must survive the skip.

**Edge cases:** lock is stale-breakable at 600s (`lock.py:26`) - a tick legitimately longer
than 600s under the new watchdog (WU-1.3) cannot happen, which is exactly why 1.2 and 1.3
land together. `BlockingIOError` sleeps the open interval (a held lock means another process
is actively trading - check back soon, not in 30 minutes).

**Done when:** both tests pass; `rm -f logs/run.pid` noted in commit message (the file is
dead after this; the untracked pid file can be deleted).

### WU-1.3 · The watchdog exists (I-34b, FM-26)

**Files:** `src/trdrbot/tick.py` (~:569), `src/trdrbot/cli.py` (`_run_loop`), `config.yaml`
(`tick.watchdog_seconds`).

**Current:** `config.watchdog_seconds` (300) is read by nothing. A hung `agent.ainvoke`
stalls the unattended run forever; the tick lock never kills the holder, it only lets later
ticks skip.

**Change (two layers, one knob):**
1. Inner, `tick.py`: `result = await asyncio.wait_for(agent.ainvoke(...), timeout=config.watchdog_seconds)`.
   `TimeoutError` flows into the existing except (`failures.classify` maps it TRANSIENT -
   verify by reading `failures.py` first), so journalling/record_failure/re-raise all work
   unchanged.
2. Outer, `cli._run_loop`: wrap the locked tick in
   `asyncio.wait_for(..., timeout=cfg.watchdog_seconds * 4)` as the FM-26 backstop for a hang
   anywhere else in the tick (a stuck MCP subprocess spawn, a wedged elfmem call). On
   timeout: print loudly, continue the loop.
3. `config.yaml`: raise `watchdog_seconds` to **600** with a one-line comment - measured
   decide cycles have reached 5:19 wall clock (D-074), so 300 would kill legitimate work.

**Tests:** `test_a_hung_tick_does_not_stall_the_run_loop` - monkeypatch `tick.run_tick` to
`asyncio.sleep(30)`, config override `watchdog_seconds` tiny (0.05 via the raw dict of the
tmp config), `max_ticks=1`; assert `_run_loop` returns rather than hanging (bound the whole
test with `asyncio.timeout`). Docstring: FM-26, watchdog was config-only since D-017.

**Edge cases:** `asyncio.wait_for` cancels the inner task - the MCP session context manager
and the `finally: mem.end(); mem.close()` in `_run_tick` handle cancellation; verify by
reading `mcp_client.session_tools` teardown before landing. The elfmem `finally` must not
swallow the CancelledError (bare `await` calls are fine; do not add `except` there).

**Done when:** test passes; `uv run python -c` confirms no import issues; config comment
states why 600.

### WU-1.4 · Learning is advisory - a memory failure must not disarm exit rules (I-33a)

**Files:** `src/trdrbot/reconcile.py:68,94`, `src/trdrbot/exit_rules.py:267-268`,
`src/trdrbot/learn.py`.

**Current:** `learn.on_fill` / `learn.on_resolution` are awaited bare inside the fast path.
Any exception (corrupt `minds.json` -> unguarded `json.loads` in `_mind_for`; locked SQLite;
disk full) propagates out of `reconcile()` or `exit_rules.run()`, aborts the tick before
stop-loss evaluation, and the run loop prints one line. Every advisory subsystem around it
degrades; the capital-protection spine does not (INV-8 inverted).

**Change:** add one helper to `learn.py`:

```python
async def guarded(coro, journal: Journal, *, stage: str, position_id: str) -> bool:
    """Learning is advisory (INV-8): a memory failure must degrade, loudly,
    never abort the fast path that evaluates stop-losses. Returns False on
    failure, having journalled a learn_error row - printed AND journalled,
    because a print in an unattended run is a message to nobody."""
    try:
        await coro
        return True
    except Exception as exc:  # noqa: BLE001 - the one advisory boundary
        print(f"[learn] {stage} failed for {position_id}: {exc!r}")
        journal.append("learn_error", stage=stage, position_id=position_id,
                       error=repr(exc)[:300])
        return False
```

Use it at all three call sites (`reconcile.py` fill + phantom paths, `exit_rules.py`
post-close path). Everything else in those functions stays exactly as is.

**Tests (seam-level, uses WU-0.4's FakeMem):**
`test_a_memory_failure_does_not_disarm_the_exit_rules` - FakeMem with `fail_with =
RuntimeError(...)`; run `reconcile.reconcile` over a phantom-close position, assert it
returns normally, the position still transitioned to closed, and a `learn_error` row exists;
then run `exit_rules.run` (tools stubbed to a dict with an async `close_position` recorded
call) over a second position with a breached stop and assert the close was still submitted
and journalled. One test, both halves - this is the exact failure chain that motivated the
fix.

**Edge cases:** `learn.on_resolution`'s own internal writes (`_write_lesson`, `store.save`)
are inside the guarded coroutine - a wiki failure is also advisory now, correctly.
`calibration.resolve` moves with it (it lives inside on_resolution) - acceptable: a corrupt
calibration store already fails the whole tick today (fixed properly in WU-1.8).

**Done when:** test passes; no other call sites of on_fill/on_resolution exist
(`grep -rn "on_fill\|on_resolution" src/`).

### WU-1.5 · The fast path survives malformed inputs (I-33b)

**Files:** `src/trdrbot/exit_rules.py` (`_pct` :98, `_normalise` :102, `run` :229-269),
`src/trdrbot/analytics.py` (`Snapshot.by_symbol` :52).

**Current, all verified:** `_pct("abc")` → `_f` defaults 0.0 → a stop_loss at threshold
**0.0** - any position slightly underwater debounces to a close. `_normalise` promises "None
for anything unrecognised" and `_pct` defeats it; `time_stop` with `days_before_expiry: null`
raises TypeError at :119, and `evaluate` is called unguarded, so one malformed rule on one
position kills evaluation for every position, every tick. `by_symbol` does `p["symbol"]` -
one symbol-less broker row KeyErrors reconcile.

**Change:**
1. `_pct` returns `float | None`: `None` when the stripped string does not parse
   (`try: float(...)` - do not use `_f`'s default here).
2. `_normalise`: every branch that consumes `_pct` or `float(...)` returns `None` on
   unparseable input (wrap the `time_stop` float too). It now keeps its own promise.
3. `evaluate`: count invalid rules - `invalid = sum(1 for r in pos.exit_rules if _normalise(r) is None)`
   is already derivable; simplest is for `evaluate` to also return that count (extend the
   tuple) OR compute it in `run` via `watched_signals`-style pass. Pick the smaller diff:
   compute in `run`, add `invalid_rules=<n>` to the existing `exit_run` heartbeat row and a
   `print` when n > 0. No new journal kind, no per-tick spam beyond the heartbeat it already
   emits.
4. `run`: wrap the `evaluate(pos, snap, deadline)` call per-position in try/except -> print +
   count into the heartbeat as `errors=<n>`, continue to the next position.
5. `by_symbol`: `{p["symbol"]: p for p in self.broker_positions if isinstance(p, dict) and p.get("symbol")}`.

**Tests** (through the public `exit_rules.run` / `evaluate` with producer-derived positions):
- `test_an_unparseable_threshold_drops_the_rule_not_the_position` - position with
  `{"type": "stop_loss", "threshold": "abc"}` plus a valid target; assert the bad rule never
  fires (position slightly underwater does NOT close), the valid rule still evaluates, and
  the heartbeat row carries `invalid_rules=1`. Docstring: `_pct` parsed "abc" to a live stop
  at breakeven, found 2026-08-29.
- `test_one_malformed_rule_does_not_stop_the_other_positions` - two positions, first with
  `days_before_expiry: None` (the TypeError case), second with a genuinely breached stop;
  assert the second still closes.
- `test_a_symbol_less_broker_row_does_not_kill_reconcile` - Snapshot with one `{}` in
  broker_positions; `reconcile.reconcile` completes.

**Edge cases:** a threshold hand-edited to a FRACTION (`-0.6` meaning -60%) still parses as
-0.6% - do NOT guess; instead extend the `_normalise` docstring naming the hazard, and rely
on `local_tools.record_position` (the producer) always writing percent-strings. Real
mitigation is Phase 2.9's naming work.

**Done when:** all three tests pass and the pre-existing exit-rule tests still pass
untouched.

### WU-1.6 · Beta aligns on dates (I-30)

**Files:** `src/trdrbot/market_stats.py` (`save_closes` :374, `load_closes` :384,
`fetch_daily_closes` :401, `betas_for` :505), call sites of fetch+save
(`grep -rn "fetch_daily_closes\|save_closes" src/`- muse.py:315-317, discovery, research).

**Current, verified live:** closes are stored as bare floats with one file-level `as_of`;
files in `data/state/returns/` were fetched on three different days; `beta()` zips the last
N returns positionally. QQQ vs SPY: stored alignment gives +0.10 (R² 0.004); one-session
realignment gives +1.48 (R² 0.841). `shrunk_beta` then drags broken estimates toward 1.0,
hiding the defect. Feeds `book_greeks` → `beta_weighted_delta` → the CONCENTRATED warning in
the decide prompt.

**Change (read-compatible, self-healing):**
1. `fetch_daily_series(tools, symbol, *, days=300) -> tuple[list[str], list[float]]` - same
   body as `fetch_daily_closes` but also collects each bar's date (`b["t"][:10]`, verify the
   key against a real bar shape in the contract test file before assuming). `fetch_daily_closes`
   becomes a thin wrapper returning `[1]` - zero churn at its other callers.
2. `save_closes(state_dir, symbol, closes, dates=None)` - writes a parallel `"dates"` list
   when given. Existing readers of `"closes"` are untouched.
3. New `load_dated_closes(state_dir, symbol, *, max_age_days) -> tuple[list[str], list[float]] | None`
   - `None` when the file is absent, stale, or has no/mismatched `dates`.
4. `betas_for`: load benchmark and symbol via `load_dated_closes`; intersect on dates
   (sorted); require `len(intersection) - 1 >= MIN_BETA_SAMPLE` returns; compute
   `beta(aligned_sym, aligned_bench)` on the aligned closes (the pure `beta()` signature is
   unchanged). Any missing-dates case → `ASSUMED_BETA` + reported in `assumed`, which is the
   honest degrade the docstring already promises.
5. Update the three fetch+save call sites to
   `dates, closes = await fetch_daily_series(...)` … `save_closes(..., dates=dates)`.

**Migration:** none. Old files simply lack `dates` → assumed beta (reported) until the daily
research cycle rewrites them (≤1 day). State the delta in the commit: *beta-weighted delta
will read "assumed" for up to one day after deploy; that is honest, the previous numbers were
broken.*

**Tests** (producer-derived - write files with the real `save_closes`):
- `test_beta_aligns_on_dates_not_array_position` - synthesise a benchmark series and a
  symbol series with known beta 1.5 (`sym_ret = 1.5 * bench_ret`), save the symbol file
  MISSING the final date (one-session misalignment, the live defect); assert `betas_for`
  returns ≈1.5 (tolerance 0.05), not the ≈-0.09 the positional zip gives. Docstring carries
  the QQQ +0.10/R²0.004 measurement.
- `test_closes_without_dates_degrade_to_assumed_beta` - old-format file → beta 1.0 AND the
  symbol listed in `assumed`.
- `test_insufficient_date_overlap_is_assumed_not_guessed`.

**Done when:** the three tests pass; run the real check once:
`uv run python -c "from trdrbot import market_stats, config; c=config.load(); print(market_stats.betas_for(c.paths.state, ['QQQ','META','XLE']))"`
and paste the output in the commit - expect `assumed` until the next research pass, then
sane numbers.

### WU-1.7 · A calendar spread must not price as zero risk (I-35)

**Files:** `src/trdrbot/analytics.py` (`book_greeks` :214-233), `src/trdrbot/optmath.py`
(`require_single_expiry` :83).

**Current, verified:** `book_greeks` prices every leg at `legs[0]`'s days-to-expiry; a real
calendar (long 09-04 / short 10-16, same strike) sums to delta/theta/vega ≈ 0 - "adds
nothing to the book" - where the honest answer is theta -$31.83/day, vega -$71.97/pt.
`require_single_expiry` treats a blank expiry as "assume shared", and its only guarded path
(`simulate`) cannot even receive an expiry per leg.

**Change:**
1. In `book_greeks`, after the legs list is built:
   `if len({l.expiry for l in legs}) != 1: skipped += 1; continue` with a comment naming the
   incident (zero is the worst possible wrong answer for an unpriceable book).
2. In `require_single_expiry`: mixed population (some legs dated, some blank) raises
   `MultiExpiryError` instead of assuming shared. All-blank stays allowed (the simulate
   path's legitimate shape).

**Tests:** `test_a_calendar_position_is_skipped_not_priced_as_riskless` - Position via
`make_position` with two OCC legs differing only in expiry, spot + entry_iv present; assert
`book_greeks` returns `positions_skipped` incremented and the totals do NOT include the
calendar (pair with a second same-expiry position so the return is non-None and its numbers
are the vertical's alone). Plus `test_mixed_expiry_population_is_refused` for the guard.

**Edge cases:** check whether any existing regression test constructs mixed-blank legs
through `require_single_expiry` and relied on "assume shared" - if one fails, it is pinning
the bug; update it with an explicit docstring note (rule A.2's documented-change route).

### WU-1.8 · The two most critical readers stop being the least guarded (I-36a)

**Files:** `src/trdrbot/journal.py` (`read` :32-39), `src/trdrbot/calibration.py`
(`CalibrationStore.__init__` :135-142).

**Current:** both raise on one truncated line. `CalibrationStore` is constructed at
`tick.py:253` before anything else - one bad line kills every tick permanently. `journal.read`
feeds `last_decision_at`, `unresolved_decision`, the muse cap and nonce, `coach.pulse` - the
ground-truth store is the least fault-tolerant reader in the system. (`Forecast(**d)` also
raises TypeError on any unknown key - schema drift becomes a crash.)

**Change:** per-line `try/except (json.JSONDecodeError, TypeError): skipped += 1; continue`
in both, matching the policy `ledger.py:117-120` and `health._rows` already use; print
`f"[journal] skipped {skipped} unreadable line(s)"` (resp. `[calibration]`) when skipped > 0.
For `Forecast(**d)`, filter to known fields:
`Forecast(**{k: d[k] for k in d if k in Forecast.__dataclass_fields__})` - drift-tolerant,
same trick WU-1.10 notes for Ledger.

**Tests:** `test_one_truncated_journal_line_does_not_blind_the_tick` - real Journal on
tmp_path, three good rows, one truncated line appended raw, one row with an unknown key;
assert `read()` yields 4, `last_decision_at` works. Mirror test for CalibrationStore
(truncated line + unknown-key line) asserting construction succeeds and good forecasts
survive.

### WU-1.9 · One door for the outcome signal (I-32) - THE semantic change

**Depends on WU-0.4.** This is the one deliberate behaviour change in the phase, implementing
the system's own documented design (`experiments.ATTRIBUTION_SIGNAL`'s docstring and the
README's four-quadrant table). Decision recorded in 019 §11.1; undo is this commit's revert.

**Files:** `src/trdrbot/learn.py` (:89-97), `src/trdrbot/elfmem_adapter.py` (`resolve` :239),
`tests/test_regressions.py:1300-1310`, `tests/test_memory_and_credit.py`.

**Current:** `on_resolution` applies `signal = 0.9 if pnl_pct > 0 else 0.1` at FULL weight to
the same creditable blocks attribution later judges at horizon. A lucky win takes +0.9, then
attribution's `THESIS_WRONG_PROFITED_ANYWAY -> None` ("learn nothing") cannot undo it. The
superstition the README forbids is installed by the path that runs first. Live example:
the NVDA position closed external at +52.8%, blocks already credited, horizon 2026-09-03.

**Change:**
1. `elfmem_adapter.py`: split `resolve` - extract
   `async def record_mind_outcome(self, pos, *, hit: bool)` (the `mind_outcome` half; the
   mind's binary claim genuinely resolves at close). Keep `resolve` for the interim path
   (`housekeeping` calls it with `interim=True` - verify with grep) or refactor interim to
   call `credit_blocks` directly - smallest diff wins.
2. `learn.on_resolution`: when `pnl_pct is not None`, call `record_mind_outcome` only.
   Delete the 0.9/0.1 block credit. Keep calibration resolve, the lesson, the reflection
   row - add `credit_deferred=True` to the reflection row and update `_write_lesson`'s
   `credit_text` to say "deferred to attribution at horizon". Add a cross-reference comment
   both here and at `ATTRIBUTION_SIGNAL` naming each other - this bug survived because each
   file read correct in isolation.
3. Blocks are now credited exactly once, by `attribution.run` at horizon, through
   `credit_blocks` (the existing single door), with the verdict-derived signal.

**Tests:**
- UPDATE characterization test #1 from WU-0.4: external close now records the mind outcome
  and does NOT credit blocks; assert `credit_deferred` in the reflection row. State the
  deliberate change in its docstring with the D-091 reference.
- DELETE `test_credit_gates_on_measured_pnl_not_the_close_label`
  (`test_regressions.py:1300` - it string-matches the exact source lines being changed);
  its intent (a None P&L skips, a measured P&L is honest evidence) is now covered
  behaviourally by WU-0.4 tests #1/#2 plus the new one below. Say so in the commit message.
- NEW `test_a_lucky_win_moves_no_memory_end_to_end` - the loop-smoke of this phase: open →
  fill → external close with profit (mind outcome recorded, zero block credit) →
  attribution at horizon with `held=False, profited=True` → assert FakeMem.credited is
  still empty. Docstring: the double-credit incident, found 2026-08-29.

**Edge cases:** interim scoring (INV-24, low-weight credit on open positions at
housekeeping) is a DIFFERENT design and stays; verify its call path still works after the
resolve split (`grep -rn "resolve(" src/trdrbot/housekeeping.py`). Positions closed before
this lands were already credited at close - attribution will credit them again at horizon
(the old double), acceptable for the ~1 live position; note it in the commit rather than
building a migration.

### WU-1.10 · Atomic writes everywhere (I-36b)

**Files:** new `src/trdrbot/store.py`; adopters: `ledger.py:127` (`_rewrite`),
`calibration.py:144` (`_flush`), `positions.py:243` (`save`), `sensors.py` (`SensorState.save`),
`elfmem_adapter.py:224` (`_mind_for` write), `competence.py:306` (`update_high_water`),
`news_extract.py` (cache save ~:218), `wiki.py:262` (`write_concept`), `tick.py:67`
(`_tick_count`), `coach.py:224-226` (becomes a caller).

**Current:** `coach.save_state` is the only atomic writer (tmp + `os.replace`, with the
correct rationale docstring). Everything else truncate-writes in place;
`data/state/ledger.jsonl.bak-before-repair` on disk says this class already bit. `Ledger`'s
loader additionally *silently deletes* rows that no longer parse into `Entry` on the next
`_rewrite` (drift → data loss).

**Change:**
1. `store.py` (this file grows into the Phase-2 store; start it now):

```python
"""Shared persistence primitives. write_atomic is promoted from coach.save_state
(the one writer that got this right): a crash mid-write must never leave a
half-file that the next reader sees as corrupt - or, worse, that the next
rewrite silently truncates to nothing."""
def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
```

2. Convert every writer listed above to `store.write_atomic(...)`; `coach.save_state` calls
   it too (deleting its inline copy, keeping its docstring pointing at store.py).
3. `Ledger.__init__`: make loading drift-tolerant instead of drift-deleting -
   `Entry(**{k: v for k, v in d.items() if k in Entry.__dataclass_fields__})`, and count+print
   lines that still fail. A missing required field still skips (it cannot construct) - but an
   ADDED field no longer destroys history on the next rewrite.

**Tests:**
- `test_a_ledger_row_with_an_unknown_field_survives_the_next_rewrite` - write a valid row
  plus the same row with an extra `"future_field": 1` via raw append; construct Ledger; call
  `mark_rejected` on something; re-read the FILE raw and assert both logical entries are
  still present. Docstring: the loader deleted drift-incompatible history silently.
- `test_write_atomic_replaces_not_truncates` - crash simulation: monkeypatch `os.replace` to
  raise after `tmp` exists; assert the original file content is untouched and the `.tmp`
  file holds the new content.

**Edge cases:** wiki `append_log`'s read-rewrite-in-full behaviour is unchanged in this WU
(its real fix - actually appending - is Phase 2.5); it just becomes atomic. `_tick_count` and
`high_water` are tiny scalar files - write_atomic anyway, uniformity is the point.

### WU-1.11 · Opportunities dedup (I-37a)

**Files:** `src/trdrbot/ids.py`, `src/trdrbot/inbox.py` (`write` :54-72).

**Current:** `item_id` is uuid4-unique by construction (deliberately, for news batches - keep
that). So identical opportunities NEVER dedup: live pending dir holds 22 opportunities incl.
XLE ×6 with byte-identical bands from three muse runs, all entering one decide batch and one
prompt.

**Change:**
1. `ids.opportunity_id(source: str, payload: dict) -> str`:
   `f"opp_{utc_now():%Y%m%d}_{source}_{_short_hash(underlying, horizon, round(band_low,2), round(band_high,2), n=12)}"`
   (stringify None bands as "-"). Docstring: identity = the claim (name, horizon, bands),
   per-day; two sources making the same claim are still distinct (source in the id) - the
   decide prompt benefits from knowing two generators agree.
2. `Inbox.write`: when `type_ == "opportunity"`, use `opportunity_id`; if
   `pending/<id>.json` already exists, return the existing parsed Item (no write, no
   duplicate). All other types keep `item_id` untouched.

**Tests:** `test_the_same_opportunity_twice_in_one_day_is_one_pending_item` - real Inbox on
tmp_path, write the same payload twice, assert one file; write with different bands, assert
two. `test_news_items_never_dedup` (the uuid4 collision fix being protected - cite ids.py's
own incident docstring).

**Edge cases:** the 22 stale duplicates on disk need no migration - `expire_stale` ages
opportunities out at 180 min. An expired-then-reemitted identical claim same day re-enters
(pending file gone) - correct, it was re-priced.

### WU-1.12 · Trial integrity: per-candidate isolation, _open ordering, nonce dedup (I-33c-adjacent)

**Files:** `src/trdrbot/muse.py` (`_evaluate` :296-438), `src/trdrbot/coach.py`
(`_open` :1060, `tally` :340, `reconcile` :1128).

**Current, three defects:**
(a) `float(cand.get("probability", 0.5))` at muse.py:301 and :335 raises TypeError on
`"probability": null` (key present → default never fires); `_evaluate` has no per-candidate
guard, so one malformed candidate aborts the whole run, BOTH arms.
(b) `_open` saves state BEFORE appending `experiment_opened` - the opposite ordering of
`_close`/`_promote`, whose docstrings explain why event-first is the crash-safe order. A
crash in the window leaves lever state naming an exp_id with no opened event: `tally()`
returns None forever, `is_closed()` False forever, the lever is stuck mid-experiment and
`reconcile` cannot repair it.
(c) `muse.run` computes `nonce` from today's journal `muse` rows (:469) but `record_trial`
(:537) fires BEFORE the `muse` row is appended (:565). A crash between them → next run
recomputes the same nonce → duplicate `trial_result` rows that `tally` (:352-363) counts
twice. The `run_nonce` field exists and nothing reads it.

**Change:**
(a) A tiny `_prob(v) -> float` helper (`float(v)` if numeric else 0.5) used at both sites,
AND wrap the body of `_evaluate`'s per-candidate loop in try/except that follows the
existing rejection idiom exactly - set `verdict["fate"] = f"error: {type(exc).__name__}"`,
`_reject(ledger, entry, verdict["fate"])` (entry may be None - `_reject` already handles
that; verify), `evaluated.append(verdict)`, `continue`. **The idiom matters:** five
regression tests scan `_evaluate`'s source asserting every `verdict["fate"]` assignment is
followed by `_reject` within a few lines - keep that shape and they keep passing.
(b) `_open`: append the `experiment_opened` event FIRST, then mutate state + `save_state`,
matching its siblings; update the docstring. Extend `coach.reconcile` with the orphan
repair: a lever state whose `exp_id` has no `experiment_opened` row → clear
challenger/exp_id, save, report (this makes the pre-fix stuck state self-healing too).
(c) `tally`: skip duplicate `(exp_id, run_nonce)` pairs - a `seen` set, keep-first, count
skips into `t.voided`? No - add a separate counter or just skip silently with a comment;
smallest honest diff: skip and increment `t.voided` (a duplicate is a void observation, and
voided is already reported).

**Tests:**
- `test_one_malformed_candidate_costs_one_candidate_not_the_run` - call `_evaluate` (it is
  async, offline once closes are pre-seeded via `save_closes` and the options-gate is
  pre-cached via the `cache` param - producer-derived, no network) with
  `[{underlying, probability: None, ...}, <valid candidate>]`; assert the valid one is
  evaluated and the bad one's fate starts "error:".
- `test_a_duplicate_run_nonce_counts_once` - seed a real events file via `coach._append`
  with `experiment_opened` + two identical `trial_result` rows (same exp_id, same
  run_nonce); assert `tally().runs == 1`.
- `test_a_crash_between_open_event_and_state_save_self_heals` - append `experiment_opened`
  with no state change (the new ordering's crash window), run `coach.reconcile`, assert the
  lever is not stuck (arms() returns incumbent-only, no exp_id).

**Edge cases:** `_reject(ledger, entry=None, ...)` - read `_reject` before assuming; if it
requires an entry, guard the call. ShadowLedger must accept the same calls (it does - both
arms run the same `_evaluate`).

### WU-1.13 · The options gate parses contracts, not substrings

**Files:** `src/trdrbot/discovery.py` (`_options_gate` :138-149) - shared by muse via import.

**Current:** `n = str(r).count("symbol") or str(r).count(ticker)` - an error payload
`{"error": "no chain for symbol XYZ"}` scores n=1, `tradeable: True`. And if chain
compaction ever runs before this call, a compacted string contains neither token →
permanently untradeable, silently.

**Change:** recognise the real shape first, fall back honestly:

```python
r = await mcp_client.call(...)
snaps = r.get("snapshots") if isinstance(r, dict) else None
if isinstance(snaps, dict):
    n = sum(1 for occ in snaps if optmath.parse_occ(str(occ)))
    return {"tradeable": n > 0, "contracts_seen": n, "via": "snapshots"}
# unrecognised shape: keep the old heuristic but SAY so - a shape change must
# degrade loudly, not flip the gate to a coin toss (D-038)
text = str(r)
n = text.count("symbol") or text.count(ticker)
return {"tradeable": n > 0, "contracts_seen": n, "via": "substring_fallback"}
```

Error path unchanged (`tradeable: False, error: ...`).

**Tests:** three cases through `_options_gate` with a stubbed tools dict (async lambda
returning the canned response - the seam): a snapshots dict with 2 valid OCCs → tradeable,
via=snapshots; an error-shaped dict `{"error": "no chain for symbol XYZ"}` → NOT tradeable
(this is the regression - docstring it); an unrecognised-but-plausible shape → fallback with
via=substring_fallback.

### WU-1.14 · Odds failure renders as unavailable, not as none

**Files:** `src/trdrbot/discovery.py` (:169-176), `src/trdrbot/muse.py` (:486-493).

**Current:** both swallow a Polymarket failure with bare `pass`, so the prompt says
`(none)` - the model is told no prediction markets exist when the API failed. research.py
already does it right (renders `(odds unavailable: X)`).

**Change:** in both `except` blocks: `odds_lines.append(f"(odds unavailable: {type(exc).__name__})")`
- three-line diff, matches research's convention (the full shared `evidence.py` is Phase 2.4).

**Tests:** none needed beyond a docstring note in the Phase-2 evidence work; this is a
rendering convention fix - but since rule A.3 wants a test per bug fix: one parametrised
test calling the two run functions is too heavy for this; instead assert the convention
where it is cheap: skip - RECORD in commit message that the behavioural test arrives with
Phase 2.4's `evidence.gather` seam test. (Deliberate, stated exception to A.3.)

### WU-1.15 · High-water corruption is loud (I-33-adjacent) - depends on WU-1.10

**Files:** `src/trdrbot/competence.py` (`update_high_water` :295).

**Current:** a corrupt `high_water.json` silently resets hw to 0.0 → next line sets
hw = equity → drawdown reads exactly 0 → demotion silently off until a new peak forms.
Fail-open on a capital-protection input.

**Change:** the lost value cannot be recovered, so the fix is visibility + prevention:
WU-1.10 already made the write atomic (prevention). Here: on parse failure, print
`[competence] high_water.json unreadable - drawdown protection degraded until a new peak`
AND return... the same fallback as today (equity), but the caller must know: add a journal
row. `update_high_water` has no journal handle - keep the seam clean by returning a tuple?
No - smallest honest diff: give it an optional `journal=None` kwarg; `tick.py:427` passes
its journal; on corruption append `kind="state_corrupt", file="high_water.json"`. The
print stays for the CLI path.

**Tests:** `test_a_corrupt_high_water_file_is_loud` - write garbage to the file, call with a
real Journal on tmp_path, assert the `state_corrupt` row and that the function still returns
a float (the degrade is unchanged, only now visible).

### WU-1.16 · Two clocks, named (I-33-adjacent, issues I-6 neighbour)

**Files:** `src/trdrbot/ids.py` + every `date.today()` in src/
(`grep -rn "date.today()\|datetime.now()" src/trdrbot/` - expect hits in cli, tick,
exit_rules, competence, attribution, ledger, analytics, market_stats, muse, discovery,
housekeeping, local_tools).

**Current:** four clocks decide different things. Concretely wrong today: the run-loop
deadline compares LOCAL date while horizons are stamped UTC; `Entry.matured` and
attribution's horizon check use local against UTC-written horizons (off by one on a non-UTC
machine); the Saturday research skip keys on UTC weekday (fires Friday 20:30 ET).

**Change:** two named clocks in `ids.py`, then a mechanical sweep:

```python
def today() -> date:
    """UTC date - for anything compared against utc_now()-stamped data
    (ledger horizons, attribution, journal ages, cache as_of)."""
    return utc_now().date()

def market_today() -> date:
    """US-market (ET) date - for anything meaning 'the trading day': DTE,
    the competition deadline, weekday gates. A UTC date is tomorrow every
    evening ET, which puts DTE off by one exactly when gamma is worst."""
    return datetime.now(zoneinfo.ZoneInfo("America/New_York")).date()
```

Assignment table (apply, and cite in each site's diff): **UTC `today()`**: `Entry.matured`
default, attribution horizon check, `market_stats.load_closes` age vs `as_of`, muse horizon
`days` (:364 - horizons are written from `forecast_window(…, ids.utc_now().date())`, keep the
pair consistent). **ET `market_today()`**: `exit_rules._days_to` (DTE + deadline sweep),
`cli._run_loop` deadline compare, `tick.py` macro-event window, `competence.forecast_window`
/ `can_open` defaults, housekeeping's Saturday gate (switch its weekday check to ET),
`analytics.Snapshot.as_of`. Leave `date.today()` nowhere in src/ (mypy/E rules will not
catch a stray - grep is the check).

**Tests:** clocks are hard to integration-test without freezing time; keep it honest and
small: `test_no_bare_date_today_left_in_src` is a grep-shaped test - do NOT write it as
source inspection (rule A.4); instead rely on the grep in Done-when. Write ONE behavioural
test where the bug is directly expressible offline:
`test_ledger_maturity_uses_the_same_clock_the_horizon_was_written_with` - freeze via
parameter (matured takes `today`), assert a horizon equal to UTC-today is matured regardless
of local zone (construct the comparison explicitly with `ids.today()`).

**Edge cases:** DTE flipping to ET may change behaviour by one day for evening runs - that
is the fix, state it in the commit. Do not touch `utc_now()` call sites.

### WU-1.17 · The compacted chain carries the OCC symbol - then prove compaction live

**Files:** `src/trdrbot/compact.py` (row rendering below :139 - read the whole file first).

**Current, verified:** `rows` collect `occ` (:75) and the rendered table omits it - but OCC
is the identifier `place_option_order` legs and `record_position` legs require, so the agent
must reconstruct contract symbols by hand. Separately: zero `[compact]` lines in all 23 log
files - the path has NEVER run in production (the `_unpack` fix landed after the last chain
call).

**Change:** add the `occ` value as the first column of each rendered row (keep the table
alignment readable; the existing `fmt` helper handles numerics - occ is a string, pad it).
Update the header line's "Prices verbatim..." sentence to name the column.

**Tests:** extend the existing compaction regression tests (grep `compact_option_chain` in
tests/) - assert every rendered kept-row contains its OCC string.

**Done when (the live half):** with market data available, run one forced decide tick or a
direct call:
`uv run python -c "<build session_tools, call get_option_chain for SPY, run compact.compact_option_chain, print first 400 chars>"`
and paste the output - the first production execution of this path. If the envelope shape
surprises again, THAT is the finding; record it, do not fail silently (D-074's lesson).

### WU-1.18 · Position provenance stops lying about the model (D-070's other half)

**Files:** `src/trdrbot/tick.py:453`.

**Current, verified live:** `generated_by=config.model` stamps the chain HEAD; on 2026-08-28
the decide role was actually served by three different models (usage.jsonl) while the
position page records one name. The journal got this fix in D-070 (`model_served`); positions
did not.

**Change:** `generated_by=" | ".join(config.model_chain("decide"))` with a comment: the
chain is the honest claim at write time; the served model per call is in usage.jsonl keyed
by the decision's timestamps. (Stamping served-at-close needs the close path to know the
open call's window - out of scope; the chain is truthful, the head was not.)

**Tests:** one-line assertion added to whichever existing test drives `record_position`
through `local_tools` (grep for `generated_by` in tests/) - assert the stored value contains
every chain member.

### WU-1.19 · Verified-dead code deleted, one honest wiring

**Files/items (each verified dead by the review; re-verify with grep before deleting):**
- `research._valid_opportunity` (:187) - zero callers.
- `wiki.should_mint` (:335), `Concept.verify` (:159), `Concept.trust_tier` (:165) - zero
  callers (`tick.py:211` is `Position.trust_tier`, different class).
- `local_tools.build_size_position`'s `open_count` parameter - never read; remove it and the
  computation at `tick.py:448`.
- `optmath`: the three ignored `start` parameters on `bs_greeks`/`net_greeks`/`expected_move`
  - remove them and update call sites; their docstrings explain the ignoring (D-074) - move
  that rationale to the module docstring's clock section rather than deleting it.
- `tests/test_contracts.py`: the three OpenCode-Zen tests (:362, :404, :444) for models
  removed from every chain (I-25/D-084) - the belief "grok is in no chain" is already pinned
  offline at `test_regressions.py:3423`.
- The wiring: `tick.py:263`'s `sensed` is assigned and discarded - the only fast-path
  subsystem whose output the tick ignores. Add it to the verbose line and the return dict
  (`"sensed": sensed` - check `sensors.collect`'s return type first). NOT dead code -
  missing observability.
- **Deferred, not deleted:** `optmath.implied_vs_realized`/`vol_days` (019 §11.2 - operator
  decision pending: wire the I-14 consumer or delete). Leave untouched; note in commit.

**Tests:** the suite itself (deletions must strand no test - if a test imports a deleted
name, that test was pinning dead code: delete it WITH the code and say so, per A.2's
documented route).

---

## D. Phase close-out

1. Full suite: `uv run pytest` - paste the summary. Expected: everything green, three
   contract tests fewer, ~15 new tests.
2. `uv run mypy` green under the WU-0.3 config; `uvx ruff check src/ tests/` clean.
3. Live smoke: `uv run trdrbot tick` (market closed → housekeeping path), then
   `uv run trdrbot health` and read it - the point of half these fixes is that failures now
   land in the journal, so health can see them.
4. The D-091 decision entry + issues.md strikes (rule A.9).
5. Restart the run loop if it was stopped in WU-0.1, and note the WU-1.6 beta-assumed window
   in the log message.

## E. What this phase deliberately does NOT do

No store.py beyond `write_atomic` (Phase 2.1 adds append/read/v). No `ask()`/`parse_json`
consolidation (2.2), no Opportunity type (2.3), no evidence.py (2.4), no wiki store rework
(2.5), no typed SharedContext (2.6), no config threading (2.7), no tick/coach decomposition
(2.8), no percent/fraction renames (2.9), no test-file splitting (Phase 4), no muse-cap CLI
enforcement (019 §11.3, operator decision), no `ruff format`. If a WU tempts you into any of
these, stop at the WU boundary and leave a note in the commit message instead.
