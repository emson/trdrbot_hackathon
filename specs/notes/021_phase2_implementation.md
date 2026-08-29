# 021 · Phase 2 implementation spec (LLM-executable)

The foundations phase of [019_refactor_plan.md](019_refactor_plan.md): shared seams, typed
contracts, config singularity, and the big decompositions - executed the way
[020](020_phase1_implementation.md) was. Written for an LLM implementer. Every claim below was
verified against the source as of commit `52c5e61` (2026-08-29, after Phase 1 and its entropy
pass); line numbers are from that snapshot - **re-read the named region before editing, and
trust the file over this document if they have drifted.**

**Two deliberate deltas from 019's Phase 2 sketch, decided here with reasons:**

- **`SimResult` stays a dict.** 019 §2.6 proposed replacing `simulate()`'s 25-key dict with a
  dataclass. Its consumers (`rank`, `render_comparison`, the `structures` stash) are adjacent
  in one module and have produced no seam bug; converting them is ~30 mechanical accessor edits
  with churn risk and no demonstrated defect class. The typed-seam budget goes where the bugs
  actually lived: the invisible `shared` dict crossing four tools and the tick.
- **`wiki.append_log` keeps its rewrite.** 019 §2.5 said "actually append". The log is
  NEWEST-FIRST with dated headings - OKF's own `log.md` convention (D-022) - so a true append
  would invert the format. Phase 1 already made the rewrite atomic, which was the real risk;
  the O(file) cost is irrelevant at this file's size. Kept, with this reasoning.

---

## A. Global rules (read first, apply to every work unit)

Rules A.1-A.9 of [020](020_phase1_implementation.md) apply verbatim: one WU = one commit,
suite green before and after (baseline: **332 passed**), regression test per behaviour fix,
seam-level tests with producer-derived inputs and fakes only at adapter boundaries, no new
`inspect.getsource` tests, preserve guards and incident-history comments, verify APIs by
running them, state files sacred, plain dashes, no co-author trailers.

Phase 2 adds three of its own:

- **A.10 - Phase 2 is BEHAVIOUR-PRESERVING, stricter than Phase 1.** Phase 1 fixed defects;
  this phase moves structure. The suite must pass **unmodified** at every WU except where a
  test names an import path this phase deliberately changes - each such edit is listed in the
  WU and is an import/path change only, never an assertion change. Anything that looks like a
  behaviour delta mid-WU is a bug in the WU: stop and re-read.
- **A.11 - Fight entropy: every WU should be net-negative or near-net-zero in `src/` lines**
  (docstrings excluded from the judgement, not from the count). This phase exists to DELETE
  the six copies of the reply-flattener, the two section parsers, the three odds loops, the
  three leg-coercion rules, the two dossier templates, the 17-branch dispatch. If a WU is
  finishing net-positive, something got added that was not paid for by a deletion - find it.
  The final WU audits the whole phase diff.
- **A.12 - Renames never touch persisted keys.** Journal field names (`pnl_pct` on
  `reflection` rows), position frontmatter (`last_pnl_pct`, `max_loss_usd`), inbox payload
  keys, and tool argument names the MODEL reads (`drift_pct`, `stop_loss_pct` - genuinely
  percent) are all wire formats. Code identifiers may be renamed; wire formats may not.

**Execution order:** WU-2.0 → 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6 → 2.7 → 2.8 → 2.9 → 2.10 →
2.11. Dependencies: 2.3 needs 2.2 (the parser's new home); 2.6 before 2.7 (the golden test);
2.9's tick extraction is easier after 2.6/2.8 shrink `_run_tick`.

**Bookkeeping at close (WU-2.11):** decision entry `D-092 - Phase 2 foundations`, strike
I-20 in `specs/issues.md` (WU-2.5 closes it), note the 019 deltas above in D-092.

---

## B. Work units

### WU-2.0 · Snapshot and stop the loop

Same as 020's WU-0.1: check `pgrep -f "trdrbot run"`, stop the loop if live (note the pid),
`tar -czf ../trdrbot_state_backup_$(date +%Y%m%d_%H%M).tgz data/`, restart at WU-2.11. Confirm
baseline: `uv run pytest -q` → 332 passed; `uvx ruff check src/` → clean; `uv run mypy` →
strict core clean.

### WU-2.1 · `store.py` grows the JSONL half

**Files:** `src/trdrbot/store.py`, `src/trdrbot/journal.py`, `src/trdrbot/coach.py`
(`_append` :242, `_read` :251), `src/trdrbot/usage.py` (`UsageLedger.record` / `calls`).

**Current:** Phase 1 left `store.py` holding only `write_atomic`. Three appenders remain with
three different failure policies (`Journal.append` propagates; `coach._append` and
`UsageLedger.record` swallow OSError with a print), and three hand-rolled skip-bad-lines
readers (`journal.read`, `coach._read`, `usage.calls`) alongside the two Phase 1 hardened
(ledger, calibration). Rows carry three timestamp conventions (`ts` / `created` / `at`) and
only the journal's rows have ids. Nothing carries a schema version, and the journal has
already drifted four ways on `decision` alone with no way to tell populations apart.

**Change:** two functions in `store.py`, adopted where each fits - NOT a class, NOT a
migration of old rows:

```python
def append_jsonl(path: Path, row: dict[str, Any], *, advisory: bool = False) -> bool:
    """One row, one line, one buffered append. `v` is stamped if absent - the
    schema version that makes the NEXT drift auditable; nothing rewrites old
    rows. advisory=True swallows OSError with a print (bookkeeping never
    blocks a run); advisory=False propagates (the journal is ground truth and
    a failed write there must be loud)."""

def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """(rows, skipped). One policy: skip the unparseable line, count it."""
```

- `Journal.append` builds its row (id, ts, kind, fields, `v: 1`) and calls
  `append_jsonl(..., advisory=False)`; `Journal.read` wraps `read_jsonl`, keeping its
  print-if-skipped behaviour and generator signature.
- `coach._append` → `append_jsonl(path, {"ts": ..., **row}, advisory=True)`; `coach._read` →
  `read_jsonl(path)[0]`. Delete both local implementations.
- `UsageLedger.record`'s file write goes through `append_jsonl(..., advisory=True)`;
  `UsageLedger.calls` reads via `read_jsonl`. Keep its own row shape untouched (wire format,
  A.12).

**Explicitly not doing:** unifying `ts`/`created`/`at` field names (wire formats), giving
coach events ids (nothing consumes one yet; the nonce dedup from Phase 1 covers the real
replay case), rotating files.

**Tests:** extend `tests/test_store_resilience.py` - `append_jsonl` advisory vs loud on a
read-only path (`chmod 0o444` the parent, restore in teardown); `read_jsonl` skip-and-count;
every new journal row carries `v`; an OLD row without `v` still reads (mixed-file test).

**Done when:** the three deleted implementations are gone (`grep -n "def _read\|def _append"
src/trdrbot/coach.py` finds nothing), suite green, net lines negative.

### WU-2.2 · One reply-text seam, one JSON parser home (I-19-adjacent)

**Files:** `src/trdrbot/llm.py`; `src/trdrbot/research.py` (`_section` :80,
`_salvage_truncated_array` :86, `_parse_json_block` :120); the six inline flatten copies
(grep `isinstance(reply.content, str)` - research, discovery x2, muse, news_extract, coach);
`src/trdrbot/tick.py` (`_text_of` :77); `src/trdrbot/news_extract.py:305` (the
cycle-dodging local import); `src/trdrbot/cli.py` (doctor's role list :~66);
`src/trdrbot/prompts.py` (`inventory` :70); `src/trdrbot/coach.py` (`fingerprint` :128).

**Current:** the de facto structured-output layer is a PRIVATE function in the research
module, imported by four siblings (one through a function-local import that exists only to
break a cycle, documented at news_extract.py:86-88). The reply-flattening idiom exists seven
times: six inline copies that raise TypeError on any content that is neither str nor list,
and one good version (`tick._text_of`) with the `.strip()` and `str(content)` fallback and
the docstring explaining the extended-thinking block problem. Because `_parse_json_block`
returns "whatever I could rescue", each caller re-guesses the shape afterwards
(muse unwraps `{"candidates": [...]}`, news_extract guards `isinstance(parsed, list)`, coach
takes `parsed[0]`). Two section parsers exist for one `LABEL:` convention (research's
`_section` and discovery's inline `re.search` around :215).

**Change:** grow `llm.py` by four functions - no classes, no role registry:

1. `text_of(message) -> str` - `tick._text_of` promoted verbatim, docstring included. Delete
   the six inline copies and the tick original; every `.ainvoke` call site uses it.
2. `async ask(config, role, prompt) -> str` - `text_of(await build_model(config,
   role=role).ainvoke(prompt))`. Adopt at the six bare-invoke sites (research, discovery x2,
   muse `_generate`'s invoke, news_extract, coach.mutate). The decide agent path is untouched.
3. `parse_json_array(raw) -> list` / `parse_json_object(raw) -> dict` - move
   `_parse_json_block` + `_salvage_truncated_array` here (docstrings verbatim - they carry the
   I-19 incident), split so the CALLER states its expected shape and the shape-fixups die:
   muse.py's dict-unwrap (`{"candidates": ...}` → array accepts a dict with exactly one
   list value and unwraps it, stated in the docstring), news_extract.py:307's list guard,
   coach's `parsed[0]`. `research._parse_json_block` becomes a thin alias for one release?
   NO - update the four importers in this WU and delete the private name; `from .research
   import _parse_json_block` importing a sibling's underscore name was the smell.
4. `section(text, name, next_names) -> str` - research's `_section` promoted; discovery's
   inline regexes (grep `OPPORTUNITIES_JSON:` in discovery.py) call it instead.

Same-area consolidations, small and in-scope here:
- **Doctor probes every role code can request.** `cli.py` hardcodes five roles under a
  comment claiming "EVERY model". Add `ROLES: tuple[str, ...]` to `llm.py` naming all seven
  (`decide, research, discovery, muse, doctor, coach_mutate, news_extract`) - the one place a
  new role gets added - and doctor iterates it.
- **`prompts.inventory` covers what it claims.** Its module docstring says eight artefacts;
  it lists six. Add `news_extract.EXTRACT_PROMPT` and the coach's `MUTATE_PROMPT` (the
  in-code seed - the mutation prompt is not a lever).
- **One fingerprint.** `coach.fingerprint` (:128) and `prompts.PromptRef.fingerprint` (:44)
  are the same sha256-hexdigest[:8]. `coach` imports the helper from `prompts` (safe:
  prompts.py has no top-level trdrbot imports). Keep `coach.fingerprint`'s name as a thin
  delegate - lever state files store its output and tests call it.

**Tests:** move the parser tests' imports (`grep -rn "_parse_json_block" tests/` - they live
in test_regressions) to the new public names - import-path edits only (A.10 lists them in the
commit). New: `test_text_of_handles_str_list_and_neither` (the six copies' missing fallback,
now impossible to reintroduce); `test_parse_json_array_unwraps_a_single_keyed_dict` (muse's
old hack, now contract); parametrized truncation cases reusing the existing incident inputs.

**Edge cases:** `ask` must not add retry/timeout logic - `build_model` already carries
`LLM_MAX_RETRIES` and the watchdog belongs to callers. muse's `_generate` also journals the
raw reply on parse failure - keep that at the call site, not in `ask`.

**Done when:** `grep -rn "isinstance(reply.content" src/` → 0; `grep -rn "from .research
import _parse" src/` → 0; the news_extract function-local import is gone; suite green.

### WU-2.3 · A typed Opportunity and one admission gate

**Files:** new `src/trdrbot/opportunity.py`; `src/trdrbot/research.py`
(`opportunity_defect` :157, emission loop :292-299); `src/trdrbot/discovery.py`
(`_plausible_band` :93, emission loop - grep `research_rejected`); `src/trdrbot/muse.py`
(hand-built payload in `run`, grep `inbox.write("opportunity"`); `src/trdrbot/inbox.py`.

**Current:** three sources write the same seam under three different rule sets (the drift
table in 019's review). Research has NO horizon-window check, NO band-plausibility check -
the exact D-035 dollar-band bug (`holds_at` always-False poisoning attribution) is still
open on the research path. Muse hand-builds its payload and would fail the shared defect
check it never calls (`claim` can be None, `drift_pct` hardcoded 0.0). Discovery skips the
band check silently when it has no spot - the gate absent exactly when the data is worst.
Research and discovery share the `research_rejected` journal kind with no `source` field, so
rejections cannot be attributed to their producer.

**Change:**

1. `opportunity.py`:

```python
@dataclass(frozen=True)
class Opportunity:
    underlying: str
    claim: str
    horizon: str                      # YYYY-MM-DD
    direction: str = "neutral"
    drift_pct: float = 0.0
    band_low: float | None = None
    band_high: float | None = None
    why: str = ""
    suggested_structures: tuple[str, ...] = ()
    # from_payload(dict) -> Opportunity | None; to_payload() -> dict matching
    # the CURRENT inbox payload keys byte-for-byte (A.12 - the decide prompt
    # renders these and ids.opportunity_id hashes them).

@dataclass(frozen=True)
class Admission:
    defect: str | None        # None = admitted
    unchecked: tuple[str, ...] = ()   # gates that could not run, BY NAME

def admit(o: Opportunity, *, spot: float | None,
          latest_useful: str | None,
          options_tradeable: bool | None) -> Admission:
```

`admit` folds, in order: the current `opportunity_defect` field checks (moved here verbatim,
including the reason-naming D-071 docstring); the horizon window (inside
`competence.forecast_window`'s latest, when `latest_useful` given); band plausibility (the
`_plausible_band` rule, moved here); the options gate verdict. **A gate whose input is None
lands in `unchecked`, never silently skipped** - the caller journals
`unchecked=list(a.unchecked)` on the emission row, which is what fixes discovery's
silent-skip and makes research's missing options gate honest rather than invisible.

2. `Inbox.write_opportunity(o: Opportunity, *, source, trust="primary") -> Item` - thin:
   `self.write("opportunity", o.to_payload(), ...)`. Dedup from Phase 1 applies unchanged.
3. Each source calls `admit` + `write_opportunity`; each keeps its OWN prompts, evidence and
   extra gates (muse's bootstrap base rate and pre-registration, discovery's gauntlet) -
   only "may this enter the inbox" is shared. Rejection rows gain `source=` and keep kind
   `research_rejected` (wire format).
4. `research.opportunity_defect` and `discovery._plausible_band` are deleted at their old
   homes; muse imports move (`from .discovery import _plausible_band` dies).

**Two behaviour deltas, both deliberate, both loud (state in the commit):** research now
rejects out-of-window horizons and implausible bands it previously admitted (closing the
open D-035 hole - these are wrong items reaching the decide prompt today); a muse candidate
with an empty claim is now rejected at emission like every other source's.

**Tests:** new `tests/test_opportunity_admission.py` - table-driven `admit` cases per gate
including every `unchecked` combination; round-trip `from_payload(to_payload(o)) == o`;
producer-derived payload equality (build the payload muse emits today from a survivor
verdict, assert `to_payload` matches it key-for-key). Seam test per source: research's
emission loop drops a percent-band opportunity and journals `unchecked=["options"]`.
Existing getsource tests to check: `grep -rn "opportunity_defect\|_plausible_band" tests/` -
update import paths only.

**Done when:** three sources emit through one door; `grep -rn '"opportunity", {' src/` shows
no hand-built payloads; net lines ≈ zero (the dataclass is paid for by the deleted drift).

### WU-2.4 · One evidence gather

**Files:** new function in `src/trdrbot/evidence.py` (or fold into `news_extract.py` if,
when writing it, the module ends up under ~40 lines - implementer's call, say which and why);
`research.py` (news ~:220, odds ~:237), `discovery.py` (:180-199), `muse.py` (:505-524).

**Current:** the news fetch+enrich block exists three times (limits 25/40/30; research's is
symbol-scoped to the universe) and the odds loop three times. Phase 1 aligned the odds
FAILURE rendering; the copies remain, and one query failing still kills the remaining
queries inside each copy's single try.

**Change:**

```python
async def gather(tools, config, *, symbols: list[str] | None = None,
                 news_limit: int = 30) -> tuple[str, str]:
    """(news_block, odds_block) for a prompt. One failure convention: a failed
    fetch renders as "(... unavailable: X)" - an empty block claims the world
    is quiet, which is a different statement from "we could not look"."""
```

Per-query isolation inside the odds loop (one query's failure appends its own unavailable
line and continues). The three call sites collapse to one call each with their own
`news_limit`/`symbols`.

**Tests:** seam tests with `conftest.tools_for` - news up + odds down renders both truths;
one odds query raising does not lose the other's lines; symbol-scoped vs broad passes the
right kwargs (assert on `FakeTool.calls`).

**Done when:** `grep -rn "polymarket.search" src/` shows one call site; three copies deleted.

### WU-2.5 · The wiki behaves like a store (closes I-20)

**Files:** `src/trdrbot/wiki.py` (`path_for` :165, `_parse` :174, `is_stale` :116),
`src/trdrbot/research.py` + `src/trdrbot/discovery.py` (dossier heading templates - grep
`"# What it is"` or the dossier body f-string in each), `src/trdrbot/muse.py`
(`_sample_concepts` :~230), `src/trdrbot/tick.py` (regime injection, grep
`context/regime`).

**Current, each verified:** `path_for` is `self.root / f"{concept_id}.md"` with concept ids
built from MODEL OUTPUT (`f"research/{sym.upper()}"`) - a key containing `../` writes
outside the wiki root. `_parse` does `text.split("---", 2)` and unpacks three values - a
file with unterminated frontmatter raises ValueError on the hot path (`read()` has no guard;
`all_concepts` catches per-page). No `encoding=` argument exists anywhere in `src/` and live
dossiers carry non-ASCII (U+2011 in AFRM.md). The dossier heading template exists in both
research and discovery, protected only by a getsource test that regexes the heading literals
out of both functions. `is_stale` returns False when `stale_after` is absent, so the 24
legacy dossiers are permanently unsweepable (I-20). The decide prompt injects
`context/regime` without checking staleness (it is stale on disk right now), and
`_sample_concepts` reimplements `all_concepts`' filter over a raw rglob and does not skip
`status: deprecated` pages.

**Change:**

1. `path_for` validates: `concept_id` must match `^[A-Za-z0-9][A-Za-z0-9._/-]*$` with no
   `..` segment and no leading `/`; raise ValueError naming the id. (LLM-controlled input
   reaches this - it is a boundary, and boundary validation is the fail-fast rule, not
   defensiveness.)
2. `_parse` degrades: malformed frontmatter (bad split, non-dict yaml) → parse as
   `{}` + whole text as body, with one print - matching `all_concepts`' existing policy so
   `read()` on the hot path cannot raise.
3. `encoding="utf-8"` on every `read_text`/`write_text`/`open` in: `store.py` (write_atomic
   + the jsonl pair from 2.1), `wiki.py`, `positions.py`, `journal.py`, `ledger.py`,
   `calibration.py`, `inbox.py`, `news_extract.py`, `sensors.py`, `market_stats.py`,
   `coach.py`, `competence.py`, `usage.py`. Enable ruff's rule so it stays done: add `"PLW1514"`
   (unspecified-encoding, in the `PL` set - verify the code against the installed ruff first,
   A.6) to the select list, per-file-ignore for tests.
4. **One dossier builder.** `def dossier(ticker: str, *, what_it_is, bull_case, bear_case,
   people, environment, computed: str) -> Concept` in `research.py` (research owns the
   document type; discovery imports the public name). Both writers fill fields; the heading
   set exists once. DELETE `test_both_dossier_writers_keep_identical_headings` (grep
   tests/ for it) - its docstring said it existed to police copy-paste; the copy-paste is
   gone, and a seam test asserts both sources produce concepts with identical `headings()`.
5. **Staleness reaches readers.** `is_stale` falls back, for a type whose policy is
   perishable, to `generated.at + perishable_after_hours` when `stale_after` is absent -
   this is what makes the 24 legacy dossiers age out (I-20 closes; strike it). The decide
   prompt's regime section renders a `(STALE - generated <date>, treat as history)` prefix
   when `is_stale()`. `_sample_concepts` calls `wiki.all_concepts()` (deleting its rglob
   copy) and skips `status: deprecated` pages - a tombstoned dossier must not feed the muse.

**Behaviour deltas, deliberate:** legacy dossiers become sweepable (that is I-20's fix); the
muse stops sampling deprecated pages; the regime block gains a staleness label. Say all
three in the commit.

**Tests:** path traversal refused (`../x`, `/abs`, `a/../b`); unterminated frontmatter
degrades not raises; non-ASCII round-trips byte-identically through write_concept/read;
legacy dossier (no `stale_after`, old `generated.at`) is stale and sweepable while a fresh
one is not; deprecated pages absent from `_sample_concepts` (producer-derived: write via
`write_concept`, tombstone via `sweep`).

### WU-2.6 · The shared bus gets a type

**Files:** `src/trdrbot/local_tools.py` (`_legs_key` :26, `_matching_payoff_ratio` :470,
the four `shared[...]` writers/readers), `src/trdrbot/tick.py` (`shared: dict[str, Any] =
{}` - grep), `src/trdrbot/analytics.py` (:~230 leg build), `src/trdrbot/optmath.py`
(`Leg`).

**Current:** the cross-tool message bus is an untyped dict: `simulate_experiments` writes
`thesis`/`market`/`ranked`/`structures`, `size_position` reads `structures` and writes
`sizing`, `record_position` reads `thesis`/`market`/`structures`/`sizing` - a schema spread
across four closures with `.get()` chains and a bare `mkt["spot"]`. Leg-side coercion
(`"buy"/"long"` → long) exists three times (analytics :~230, local_tools :366, :412) with a
rule that DISAGREES with the canonical `Leg.parse` (which rejects "buy").
`_matching_payoff_ratio` matches structures by R:R within an absolute 0.02 - tight at 5.17,
loose at 0.19 - because `size_position`'s model-facing signature has no legs to match on.

**Change:**

1. `SharedContext` dataclass in `local_tools.py` (mutable, slotted):

```python
@dataclass
class SharedContext:
    """What one decide cycle's tools know about each other. Replaces the bare
    dict that was the system's real domain model and invisible (019 review)."""
    thesis: experiments.Thesis | None = None
    market: MarketParams | None = None            # spot, iv, days - frozen
    ranked: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    structures: list[SimStructure] = field(default_factory=list)  # frozen: key, name, qty, entry_cost, max_profit, max_loss, payoff_ratio, rr
    sizing: SizingStash | None = None             # frozen: underlying, contracts, max_loss_usd
```

   The four tool builders take `shared: SharedContext`; tick constructs it. Attribute access
   replaces every `.get()` chain; `mkt["spot"]` becomes `shared.market.spot` guarded by
   `shared.market is not None` (mypy now checks what the dict hid).
2. `Leg.from_position_leg(d: dict) -> Leg | None` in optmath - the ONE home for the
   side-vocabulary rule (`buy`→long, `sell`→short, else as-is; None on an unparseable OCC
   when a `symbol` key is the source). The three copies call it. `Leg.parse` (the
   model-facing strict validator) is unchanged and its docstring cross-references the
   permissive sibling and why both exist.
3. `size_position` gains an optional `structure_name: str = ""` argument: when given, match
   the simulated structure BY NAME (they are echoed in `render_comparison`); fall back to
   the R:R tolerance match, whose docstring already explains itself. Additive to the tool
   contract - the model may ignore it. Extend the arg docstring telling the model to pass
   the candidate name.

**Tests:** existing tool tests exercise the bus already (grep `shared` in tests/) - they
construct dicts; update them to `SharedContext` (mechanical, listed in the commit per A.10).
New: name-match beats R:R-match when two candidates share an R:R (the documented ambiguity
case that returns None today); the three coercion sites agree via
`Leg.from_position_leg` parametrized over `buy/long/sell/short`.

**Done when:** `grep -rn 'shared\[' src/ | wc -l` → 0; mypy passes with `local_tools`
promoted into the strict list.

### WU-2.7 · One pricing pass per candidate, provably identical

**Files:** `src/trdrbot/optmath.py` (`pnl_at` :144, `_crossings`, `breakevens`,
`breakeven_vol`, `breakeven_drift`, `_lognormal_grid`), `src/trdrbot/experiments.py`
(`simulate` :77).

**Current, measured (019 review):** one two-leg candidate costs ~1.0s of pure CPU
(**726,544 `pnl_at` calls**; a condor ~1.5s), and the agent submits 3-5 candidates, so
3-7 seconds sit inside the watchdogged decide call. 94% is `breakeven_vol` (~550ms) +
`breakeven_drift` (~480ms) grid searches. `entry_cost` and `require_single_expiry` are
recomputed inside `pnl_at` on EVERY evaluation of a constant structure; `_crossings`
re-evaluates `f(lo)` every bisection iteration.

**Change - golden test FIRST, then the refactor:**

1. **Golden characterization test** (`tests/test_simulation_golden.py`): a fixed two-leg
   vertical and a fixed condor through `experiments.simulate` with pinned inputs (spot, iv,
   days, drift, bands, a fixed `terminal_factors` list) - assert the full
   `render_comparison` string EQUALS a captured literal, and the numeric dict values equal
   captured values (exact, not approx - the refactor claims identity, so test identity).
   Capture the goldens by running the CURRENT code; commit the test green BEFORE touching
   optmath.
2. Internal `_PricedStructure` (private to optmath): legs tuple + cached `entry_cost` +
   validated-once expiry; `pnl_at` keeps its public signature and builds one internally,
   while the grid-search internals (`expected_value`, `breakeven_vol`, `breakeven_drift`,
   `prob_profit`, `breakevens`) construct it once per call and reuse. Memoize
   `_lognormal_grid` per `(spot, iv, days, drift)` within a simulate pass (a plain dict
   threaded through, NOT `functools.lru_cache` - a module-level cache would survive across
   ticks and hide staleness). Fix `_crossings`/`breakevens` to carry `f(lo)` forward.
3. Measure before/after in the commit message: `uv run python -m timeit`-style timing of one
   `simulate` call on the golden inputs. Expect roughly an order of magnitude.

**Edge cases:** float identity - reordering arithmetic can change last-ulp results and the
golden test will catch exactly that; if it fires, the refactor changed evaluation ORDER, and
the fix is to preserve order, not to loosen the test to approx.

**Done when:** goldens byte-identical, timing in the commit, `pnl_at`'s public behaviour
unchanged (the whole existing optmath suite is the second witness).

### WU-2.8 · Config singularity, and caps live with the thing they cap

**Files:** `src/trdrbot/housekeeping.py` (`_load_config` :50, call sites :140/:159/:208,
`run` signature :55), `src/trdrbot/tick.py` (housekeeping call), `src/trdrbot/prompts.py`
(`_active_muse_prompt` :51, `inventory` :70, `fingerprints` :98), `src/trdrbot/muse.py`
(`run`), `src/trdrbot/research.py` (`run`), `src/trdrbot/cli.py` (`_muse`, `_research`),
`src/trdrbot/tick.py` (`MUSE_RUNS_PER_DAY` :110 and the cap check in the hunt rung; the
research day-marker lives in housekeeping :~124).

**Current:** `housekeeping.run` takes six stores but not config, so it re-loads from disk
THREE times per run - and each `config.load` re-runs `load_dotenv(override=True)` and
re-mkdirs every path. `prompts._active_muse_prompt` calls `config.load(quiet=True)` inside
`fingerprints()`, which executes on EVERY decision write (tick journals prompts
fingerprints). The run loop's config is captured once while housekeeping and prompts see the
file as it is NOW - edit config.yaml mid-run and the system runs two configurations at once.
The muse's 3/day cap is enforced only at the tick call site; `trdrbot muse` bypasses it (the
journal showed 9 runs against a cap of 3 on 2026-08-29). The research day-marker gate lives
only in housekeeping; `trdrbot research` bypasses it.

**Change:**

1. `housekeeping.run(..., config: Config)` - tick passes its own; `_load_config` and all
   three reload sites die.
2. `prompts._active_muse_prompt(config: Config | None)` → threading: `inventory(tools,
   config=None)`, `fingerprints(tools=None, config=None)`; tick passes its config; the CLI
   path passes its own load; `None` keeps the current self-load as fallback so
   `render_inventory` callers outside a config context still work. The hidden
   `load_dotenv`+mkdir inside every decision write dies.
3. **Caps move inside the subsystem** (019 §11.3, decided: the CLI honours them, with an
   override): `muse.run(..., force: bool = False)` checks its own journal-derived daily
   count against `MUSE_RUNS_PER_DAY` (constant moves from tick.py to muse.py, its natural
   home) and returns `{"skipped": "daily_cap", ...}` unless `force`. `research.run(...,
   force: bool = False)` owns the day-marker check the same way (marker file logic moves
   from housekeeping). Tick and housekeeping call with `force=False` and drop their own
   copies; `cli._muse`/`cli._research` gain `--force` argparse flags passed through.

**Behaviour delta, deliberate:** `trdrbot muse` and `trdrbot research` without `--force` now
respect the caps they previously bypassed. State it.

**Tests:** seam test - `muse.run` twice past the cap returns skipped without invoking
`_generate` (monkeypatch `_generate` with a counter, the established pattern in
test_coach.py); `fingerprints(config=cfg)` triggers zero `config.load` calls (monkeypatch
`config.load` to raise); housekeeping runs against a tmp config with no disk reload (same
technique).

### WU-2.9 · The decompositions

Three sub-commits, in this order, each suite-green:

**(a) tick extraction.** `_run_tick` is ~420 lines. Extract exactly two functions, both
pure-assembly, both taking what they read today:

- `_build_decide_tools(tools_list, config, batch, store, shared, journal_deps...) -> list`
  - the allowlist filter → `compact.wrap_heavy_tools` → `tool_guard.enforce_order_ids` →
  `redirect_whole_book_close` → four local tools concatenation (tick.py :435-516). Decide
  the exact signature by reading the block; prefer passing the already-built local tools in
  rather than their dependencies.
- `_build_decide_prompt(snap, store, config, posture, cal_now, ctx, items, news_render,
  prior) -> str` - the `prompt_parts` sequence (:520-601), including the inline
  `from datetime import date as _date` cleanup (hoist to module imports).

The fast path, idle ladder, and post-invoke bookkeeping STAY inline - the module docstring's
ordering guarantees (INV-25, D-019) are the module's whole point and scattering them loses
the plot. Do not extract further.

**(b) coach package.** `coach.py` is 1,190 lines mixing seven concerns with five
function-local imports dodging cycles. Split into a package along its own `# ---` section
markers (mapped at :50/:83/:110/:231/:272/:312/:416/:466/:485/:672/:723/:913):

```
coach/__init__.py   registry, Variant/LeverState, load/save_state, events, arms,
                    record_trial, tally, is_closed, verdict?, floors, enabled,
                    pulse, reconcile, _open/_close/_promote   (~550 lines)
coach/posterior.py  _beta_logpdf, p_challenger_better, Tally                (pure, ~90)
coach/gauges.py     survived, _survival.._seed_entropy, _cost_today,
                    snapshot_gauges, marker, Sentinel, _sentinel_*, SENTINELS (~260)
coach/mutate.py     MUTATE_PROMPT, RETRY_SUFFIX, clean_prompt, validate_prompt,
                    digests, mutate                                          (~200)
```

`__init__` re-exports EVERY name tests and callers use today (`grep -rn "coach\." src/
tests/ | grep -oP "coach\.\w+" | sort -u` is the checklist) so `from trdrbot import coach;
coach.X` is unchanged and `tests/test_coach.py` passes UNMODIFIED - that is the acceptance
gate for this sub-commit. `verdict` imports `Tally` from posterior; keep `verdict` in
`__init__` (it reads floors). The five function-local imports become top-level in their new
homes; if one still cycles, that is the split telling you a function is in the wrong file -
move the function, do not keep the local import.

**(c) cli dispatch.** Every `sub.add_parser(...)` gets
`.set_defaults(handler=<callable(args)>)`; `main()` becomes parse → `result =
args.handler(args)` → `asyncio.run(result)` if it is a coroutine → `sys.exit`. The
17-branch `elif args.cmd ==` chain (:625-663) dies. Handlers that ignore args wrap in
`lambda args: _health()` style at the parser, so the handler signatures do not churn.

**Tests:** (a) and (c) are covered by the existing suite + chassis tests; (b)'s gate is
test_coach unmodified. Add one smoke: `trdrbot --help` and each subcommand's `--help` exit 0
(subprocess, in test_chassis.py) - the dispatch rewrite's cheapest full-coverage check.

### WU-2.10 · The `_pct` suffix means one thing

**Files:** `src/trdrbot/analytics.py` (`position_pnl_pct` :~95), its callers (`exit_rules`,
`housekeeping`, tests), `src/trdrbot/learn.py` (`pnl_pct` params), `src/trdrbot/exit_rules.py`
(`_pct` :~102), `src/trdrbot/housekeeping.py` (`_materiality_band`).

**Current:** `_pct` means FRACTION in `position_pnl_pct`/`last_pnl_pct`/`pnl_pct` params
(-0.30 = -30%) and PERCENT in `drift_pct`/`stop_loss_pct`/`iv_pct`/`band_low_pct` (-60.0).
housekeeping.py:24-33's own comment records this exact collision shipping a bug (interim
bands dead on arrival). Seven unit bugs in this codebase's history are this class.

**Change (renames only - A.12 governs what may NOT change):**

- `analytics.position_pnl_pct` → `position_pnl_fraction` (docstring keeps the D-074
  incident; first line states the unit).
- `learn.on_resolution(pnl_pct=...)` → `pnl_fraction=...`; call sites in reconcile,
  exit_rules, housekeeping, tests. The `reflection` JOURNAL FIELD stays `pnl_pct` (wire).
- `exit_rules._pct` → `_pct_string_to_fraction` (it converts; the name now says so).
- `housekeeping._materiality_band(pnl_pct)` → `(pnl_fraction)`.
- `Position.last_pnl_pct` KEEPS its name (persisted frontmatter) and gains one `#:` comment
  stating it is a FRACTION despite the suffix, with a pointer to this WU.
- Sweep check: `grep -rn "_pct" src/ | grep -v "drift_pct\|stop_loss_pct\|profit_target_pct\|iv_pct\|band_low_pct\|band_high_pct\|last_pnl_pct\|pnl_pct.*wire"` -
  every survivor must genuinely be a percent.

**Tests:** the suite is the test (pure rename). Check `grep -rn "position_pnl_pct\|pnl_pct"
tests/` and update call sites; any getsource test matching these names gets its literal
updated in the same commit with the reason (A.10 listing).

### WU-2.11 · Entropy close-out

Per the standing instruction (memory: fight-entropy-every-change) - the phase is not done
until its own diff has been audited:

1. `git diff --shortstat <phase-start>..HEAD -- src/` - Phase 2 should be **net negative**
   in src/. If it is not, name what did not pay for itself and fix or justify it.
2. `uvx ruff check src/ tests/` → clean, no new suppressions without an in-config reason.
3. `uv run mypy` - promote `trdrbot.optmath`, `trdrbot.sizing`, `trdrbot.competence`,
   `trdrbot.store`, `trdrbot.opportunity`, `trdrbot.local_tools` into the strict list (their
   callers are now typed enough to make it honest); fix what surfaces; descope any module
   over ~20 errors to `disallow_untyped_defs` with a note, as 020 WU-0.3 did.
4. Helper-duplication audit across test files (`grep "^def _" tests/*.py`) - consolidate
   into conftest anything that grew a second copy this phase.
5. Live smoke: one `uv run trdrbot tick` (housekeeping path), `trdrbot health`,
   `trdrbot prompts` (exercises the threaded inventory), `trdrbot muse` twice (the second
   must report the cap). Verify state intact: ledger trials count, calibration Brier,
   coach experiment state - same checks as 020's close-out, same expected values unless
   live trading moved them.
6. `D-092` decision entry: what moved, the two 019 deltas (SimResult, append_log), the
   measured simulate speedup, the three deliberate behaviour deltas (research gates, muse
   deprecated-page sampling, CLI caps). Strike I-20. Update the README's command list if
   `--force` flags warrant a line.
7. Restart the run loop; note in the log message that config edits now require a restart to
   be picked up ANYWHERE (single-load is the new contract - that is a feature, state it).

## C. What this phase deliberately does NOT do

Phase 3's evolution enablers (uniform lever registration, health probes derived from journal
kinds, per-module metrics in report, degraded-row journaling from compact/usage fail-opens);
Phase 4's test restructure (splitting test_regressions.py, converting the remaining ~20
source-inspection tests); `SimResult` as a dataclass and a true-append log (reasons in the
header); unit-wrapper NewTypes (escalate only if a unit bug ships AFTER WU-2.10); any
UsageLedger/store-construction registry; renaming `experiments.py` (the module/file name
collision with `data/experiments.jsonl` is real but the rename touches the D-052 paper trail
- Phase 4 at the earliest); `implied_vs_realized` (operator decision 019 §11.2 still open -
leave the code untouched either way).
