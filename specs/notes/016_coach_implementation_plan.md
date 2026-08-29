# Coach implementation plan - a build-ready handoff

> **BUILT 2026-08-29 (D-088).** Phases 1 and 2 are implemented and live; phase 3's audit and
> sampling lever are deferred (I-28). This document is kept as the design record, not as an
> outstanding to-do. **Where the build diverged from this plan, the build is right** - the plan's
> own closing rule, applied to itself:
>
> | Plan said | Built instead | Why |
> |---|---|---|
> | pulse from housekeeping | pulse from housekeeping **and** after every muse run | housekeeping runs only while the market is CLOSED and the muse only while it is OPEN, so promotions would have waited for the next night |
> | `min_runs=12`, `min_candidates=30` | 8 and 24, config-driven | the evidence unit is the candidate (~5/run x ~8 gates), and the window is 6 days |
> | `shadow=True` flag through `_evaluate` | `ShadowLedger` null object, one shared gate cascade | a flag puts a branch in every gate; two arms running near-identical code is this project's most familiar bug |
> | `calibration.evaluate` | `calibration.score` | the function is named `score` |
> | gauge reward reads `candidate` fates | shared `coach.survived()` used by gauge **and** reward | `_score_arm` missed `EMITTED`; harmless today, but it would have biased promotions toward the challenger |
> | (not anticipated) | `coach.clean_prompt` | the first live mutation echoed the harness's own delimiters into the challenger text |


Audience: an LLM implementer with full repo access. This document is self-contained: the
problem, the design, exact schemas, module-by-module specs, the edge cases with their required
handling, the tests that must exist, and the project conventions that are not optional. The
design itself was simulated and chosen in [notes/015](015_self_review_loop_brainstorm.md) -
read it first; this plan does not re-argue the design, it specifies the build.

## 0. Read these before writing any code

| File | Why |
|---|---|
| `specs/notes/015_self_review_loop_brainstorm.md` | The design and its constraints. This plan implements its winner |
| `src/trdrbot/muse.py` | The first (and in phase 1, only) subsystem the Coach wraps. Read `run()` end to end |
| `src/trdrbot/health.py` | The `Probe` dataclass and the heartbeat discipline (two silence flags, D-086) |
| `src/trdrbot/journal.py` | `Journal.append(kind, **fields)` / `.read()` - the append-only pattern every new store copies |
| `src/trdrbot/prompts.py` | `PromptRef.fingerprint` - variant identity reuses this, never a second hash scheme |
| `src/trdrbot/housekeeping.py` | Where the Coach's periodic work hooks in; note the heartbeat comment style |
| `src/trdrbot/ledger.py` | `Entry` fields and the additive-field pattern for `variant` |
| `src/trdrbot/config.py` | `Config` property style; where `coach` config accessors go |
| `specs/decisions.md` D-045, D-052, D-080, D-081, D-086 | The evidence the constraints rest on |
| `tests/test_regressions.py` (skim naming) | Test style: long descriptive names, one behaviour per test |

## 1. Mission

Build `coach.py` and its surroundings so that the muse improves itself: its collision prompt
and (later) its seed-sampling policy run controlled paired A/B trials against deterministic
rewards, winners are promoted automatically, sentinels revert anything that drifts, and every
number lands in time-series stores a human can read as a report. **Phase 1 ships the full
protocol for ONE lever (the muse prompt) end to end** - registry, trials, promotion,
graveyard, heartbeat, health probe, CLI - because a thin slice that completes the loop beats a
wide slice that doesn't. Later phases add levers and subsystems to the SAME protocol without
changing it.

## 2. Non-negotiable rules (each traces to a measured incident)

1. **Rewards are deterministic, computed from gates and stores - never an LLM's opinion of an
   output.** (D-081: "numbers are computed, never asked of the LLM".)
2. **A lever's experiment may never have that lever's own scoring machinery as a reward, and
   the scheduler must refuse the overlap.** Concretely: while a muse-prompt experiment is
   open (reward = gauntlet survival), the gauntlet's thresholds (`BASE_PROB_FLOOR` etc.) are
   not adjustable by any concurrent experiment. Enforced in code, tested.
3. **The Coach touches data, never code.** Variants live in `data/state/levers/`. Source files,
   gate semantics, sizing math, sentinel definitions and reward functions are out of reach by
   construction - there must be no code path from Coach state to any of them.
4. **elfmem blocks and the constitution are not levers and never will be** (elfmem ADR 0003:
   four automatic-evolution architectures, none beat baseline). Gauges/report only.
5. **Heartbeat from the first commit** (D-074/D-086): `coach_run` journal rows are written
   every housekeeping pass whether or not anything happened, and they are a DIFFERENT record
   from trial results. The health probe reads the heartbeat, never the output.
6. **Every store is append-only** (journal convention). Nothing in `metrics.jsonl` or
   `experiments.jsonl` is ever rewritten. Mutable state (`levers/*.json`) is tiny, atomic
   (write-temp-then-`os.replace`), and every change to it is mirrored as an append event.
7. **Production behaviour is unchanged while a trial runs.** The incumbent arm IS the
   production run. The challenger arm is shadow-only (see 5.3 - this is the plan's most
   important edge case).
8. **Fail open for bookkeeping, fail loud for correctness.** A Coach bookkeeping error must
   never block a muse run (match `_reject`'s try/except style); a corrupt lever state file
   must degrade to incumbent-only and say so, never crash and never guess.
9. Docs and comments: plain dashes, never em dashes. Comments explain constraints and
   incidents, not what the next line does - match the density and voice of `muse.py`.

## 3. Architecture at a glance

```
                    consults                      appends
  muse.run() ─────────────────► coach.active_trial("muse.prompt")
      │  incumbent arm = production (ledger/inbox as today)
      │  challenger arm = shadow (gates only, no side effects)
      │
      └── per-candidate gate fates for BOTH arms ──► coach.record_trial()
                                                          │
  housekeeping.run() ──► coach.pulse():                   ▼
      - snapshot gauges          ──►  data/metrics.jsonl       (append-only)
      - evaluate promotion       ──►  data/experiments.jsonl   (append-only)
      - check sentinels          ──►  data/state/levers/*.json (atomic swap)
      - run audit                ──►  journal: coach_run heartbeat
      - open next experiment (mutation role generates a challenger)

  trdrbot coach   - status: levers, open experiment, posterior, recent promotions
  trdrbot report  - data/report.html from metrics + experiments
  trdrbot health  - gains a "coach" probe on coach_run rows
```

New files: `src/trdrbot/coach.py`, `src/trdrbot/report.py`,
`tests/test_coach.py` (or fold into `test_regressions.py` - follow whichever the suite prefers
after reading it; keep the naming style either way).
Touched files: `muse.py` (refactor + trial hooks), `housekeeping.py` (pulse call),
`health.py` (probe), `cli.py` (two commands), `config.py` (accessors), `config.yaml`
(coach block + mutate role), `prompts.py` (muse prompt joins the inventory), `ledger.py`
(additive `variant` field).

## 4. Data schemas (exact)

### 4.1 `data/state/levers/muse.prompt.json` - mutable, atomic, human-editable

```json
{
  "lever": "muse.prompt",
  "paused": false,
  "pinned": false,
  "incumbent": {"id": "v0", "fingerprint": "ab12cd34", "text": "<full prompt text>",
                 "since": "2026-08-29T00:00:00+00:00", "origin": "seed"},
  "previous":  null,
  "challenger": null
}
```

- `id`: `v0` for the seeded incumbent (the current `MUSE_PROMPT` verbatim), then `v1`, `v2`...
  monotonically; never reused, even after a graveyarded challenger.
- `fingerprint`: `hashlib.sha256(text).hexdigest()[:8]` - identical scheme to
  `prompts.PromptRef.fingerprint`. Recompute on load; if it disagrees with the stored value,
  trust the text and log the mismatch (a human edited the file, which is allowed).
- `origin`: `seed` | `mutation` | `human`.
- `paused: true` - Coach opens no experiments on this lever and cancels any open one
  (closed as `operator_override`). `pinned: true` - same, plus the audit never re-matches.
  Both are the human steering surface; the Coach only ever sets them back to nothing.
- `previous` holds the pre-promotion incumbent, for the audit's re-match.

### 4.2 `data/experiments.jsonl` - append-only event log

One JSON object per line, `ts` in UTC ISO (use `ids.utc_now().isoformat()`), kinds:

```
{"kind": "experiment_opened", "exp_id": "exp_...", "lever": "muse.prompt",
 "incumbent": "v0", "challenger": "v3", "challenger_origin": "mutation",
 "challenger_fp": "…", "floors": {"min_runs": 12, "min_candidates": 30},
 "cap_runs": 40, "ts": "…"}

{"kind": "trial_result", "exp_id": "…", "run_nonce": 3,
 "incumbent": {"candidates": 5, "survived": 1, "fates": ["…", …]},
 "challenger": {"candidates": 4, "survived": 2, "fates": ["…", …]},
 "posterior_p_challenger_better": 0.71, "ts": "…"}

{"kind": "experiment_closed", "exp_id": "…", "outcome": "promoted" | "refuted" |
 "timeout" | "sentinel_reverted" | "operator_override" | "voided",
 "runs": 17, "final_posterior": 0.93, "reason": "…", "ts": "…"}

{"kind": "audit_result", "lever": "…", "promoted": "v3", "previous": "v0",
 "promoted_hits": [7, 3], "previous_hits": [9, 2],
 "p_promoted_worse": 0.31, "action": "none" | "rematch_opened", "ts": "…"}

{"kind": "sentinel_fired", "sentinel": "cost_ceiling", "value": 12.4, "limit": 10.0,
 "action": "paused_and_reverted", "exp_id": "…|null", "ts": "…"}
```

`exp_id` via a new `ids` helper following the existing `ids.journal_id` pattern. The
graveyard is not a separate store: it is the set of `experiment_closed` rows with outcome
`refuted`/`timeout`, joined to their `experiment_opened` row for the challenger text
fingerprint. Store the defeated challenger's full text in the `experiment_closed` row
(`challenger_text` field) so the mutation prompt can summarise it without a second lookup.

### 4.3 `data/metrics.jsonl` - append-only gauge snapshots

```
{"kind": "snapshot", "ts": "…", "gauges": {
  "muse.survival_rate_10": 0.32,       // survivors/candidates over the last 10 muse runs
  "muse.candidates_per_run_10": 4.6,
  "muse.seed_entropy_10": 5,           // distinct concept-type pairs sampled, last 10 runs
  "coach.open_experiments": 1,
  "coach.trials_today": 2,
  "coach.cost_usd_today": 1.83,        // UsageLedger, roles muse + coach_mutate, this UTC day
  "calibration.n": 13, "calibration.n_eff": 4.2,
  "health.problems": 0
}}
{"kind": "marker", "ts": "…", "label": "promotion", "lever": "muse.prompt",
 "detail": "v0 -> v3"}
```

Markers are written at promotion/revert/sentinel time so the report can overlay Coach actions
on gauge trajectories. Every gauge is computed from existing stores (journal, ledger, usage,
calibration, health) - if a gauge needs new instrumentation, it is the wrong gauge for
phase 1. Missing inputs (e.g. no muse runs yet) - omit the key rather than writing null or 0;
a 0 that means "no data" is the absence-as-zero failure class (notes/012).

### 4.4 Journal kinds (existing `Journal`, new kinds)

- `coach_run` - THE HEARTBEAT. Written once per `coach.pulse()` call, always:
  `{experiments_open, trials_scored_today, promotions_today, sentinels_active: [...]}`.
- `coach_promotion`, `coach_revert` - one row each, duplicating the marker (journal is the
  ground truth and rebuild path; metrics.jsonl is derived convenience).
- Muse rows (`kind="muse"`) gain two fields: `prompt_variant` (e.g. `"v0"`) and `prompt_fp`.
  Additive - nothing that reads muse rows today may break; check `health.py` probes and any
  journal consumers by grepping for `"muse"` before assuming.

### 4.5 `ledger.Entry` gains `variant: str = ""`

Additive dataclass field with a default, so old JSONL rows load unchanged (verify `Ledger`
construction tolerates missing keys - it should, via dataclass defaults; if it uses
`Entry(**row)`, missing keys are fine but UNKNOWN extra keys would crash old code reading new
rows - it doesn't, only this code reads it, but confirm). The muse passes the active
incumbent's variant id at `register()`. This is what the audit joins on.

## 5. Component specs

### 5.1 `coach.py` - registry, trials, promotion, sentinels

```python
@dataclass(frozen=True)
class Lever:
    name: str                      # "muse.prompt"
    subsystem: str                 # "muse"
    reward_modules: tuple[str, ...]  # ("muse.gates",) - what scores it; used by rule 2
    kind: str                      # "prompt" | "policy"

@dataclass(frozen=True)
class GaugeSpec:
    name: str
    compute: Callable[..., float | int | None]   # returns None -> omit from snapshot
```

Module-level registries: `LEVERS: tuple[Lever, ...]`, `GAUGES: tuple[GaugeSpec, ...]`,
`SENTINELS` (below). Phase 1 registers exactly one lever. Registry is code; state is data.

Key functions (all synchronous except the mutation call; all bookkeeping wrapped so failures
print-and-continue, matching `_reject`):

- `active_trial(lever_name) -> Trial | None`. Loads lever state; returns a `Trial` carrying
  the incumbent and challenger variant texts + ids + the experiment id, or None when no
  experiment is open / lever paused / state unreadable. Called by `muse.run` at the top.
- `record_trial(exp_id, run_nonce, incumbent_result, challenger_result)` - appends the
  `trial_result` row with the running posterior. Called by `muse.run` after evaluation.
- `pulse(cfg, journal, ...) -> dict` - the housekeeping entry point, in this order:
  1. snapshot gauges -> metrics.jsonl
  2. check sentinels; on any firing: close the open experiment (`sentinel_reverted`,
     challenger to graveyard), write marker + journal row, set an in-state `sentinel_block`
     note (see sentinel spec for resume rules)
  3. evaluate the open experiment against floors/cap -> maybe promote / refute / timeout
  4. run the audit over resolved ledger entries
  5. if no experiment open, lever not paused/pinned, no sentinel block: generate a challenger
     via the mutation role and open one
  6. append the `coach_run` heartbeat - LAST, and unconditionally (even if steps 1-5 threw;
     wrap them individually)
- `promote(lever_state, exp)` - atomically: `previous := incumbent`,
  `incumbent := challenger`, `challenger := None`, bump `since`; append `experiment_closed`
  (outcome `promoted`), marker, journal row.

**Promotion math** (pure function, unit-testable, no I/O):

- Reward unit: one candidate; success = survived every gate (`fate == "candidate"` or
  `"EMITTED"` / rank-cut - anything past the last gate counts as survived; the emit ranking
  is not a gate).
- Arms accumulate `(s_i, f_i)`, `(s_c, f_c)` across all trial rows of the experiment.
- Posteriors `Beta(1+s, 1+f)`. `P(p_c > p_i)` computed by deterministic numerical
  integration: for x on a 2001-point uniform grid over (0,1), pdf of the challenger Beta at x
  (via `math.exp(math.lgamma(a+b) - math.lgamma(a) - math.lgamma(b) + (a-1)*log(x) +
  (b-1)*log(1-x))`) times the incumbent's CDF at x (running trapezoid of its pdf on the same
  grid), trapezoid-summed. No numpy/scipy dependency decisions to make - `math` only, ~15
  lines, deterministic. Property tests below pin it.
- **Promote** when `P >= 0.90` AND `runs >= 12` AND `min(candidates_i, candidates_c) >= 30`.
- **Refute early** when `P <= 0.05` AND `runs >= 8` (futility - stop paying for a loser).
- **Timeout** at `runs >= 40` without either: close, keep incumbent.
- Ties/insufficient data at timeout: incumbent stays. The conservative default is free
  because the incumbent is already what production runs.

### 5.2 `muse.py` refactor - one gate pipeline, two callers

`run()` currently interleaves generation, gating, ledger writes and inbox emission. Split it,
keeping ONE copy of every gate (the project's single-copy principle - two copies of the gate
logic is how the two-EV-loops bug happened, D-074):

- `_gather_inputs(...)` - concepts, news, odds, window. Unchanged logic, called once per run.
- `_generate(prompt_text, inputs, cfg) -> list[dict]` - format + invoke + parse. Takes the
  prompt TEXT as a parameter (this is the lever seam).
- `_evaluate(raw, tools, cfg, ledger, *, shadow: bool, variant: str) -> list[verdict]` - the
  existing gate cascade. When `shadow=True`: **no `ledger.register`, no `mark_stated`, no
  `_reject`, no inbox writes** - fates are computed and returned only. When `shadow=False`:
  exactly today's behaviour, plus `variant=` threaded into `ledger.register`.
- `run()` orchestrates: gather once; incumbent arm = `_generate(incumbent.text)` ->
  `_evaluate(shadow=False)` -> emit survivors (unchanged); if `active_trial` returned a
  trial: challenger arm = `_generate(challenger.text)` -> `_evaluate(shadow=True)`;
  `coach.record_trial(...)` with both arms' per-candidate fates; muse journal row gains
  `prompt_variant`/`prompt_fp` and, when a trial ran, `exp_id`.

**Determinism and fairness across arms:**

- RNG: today `random.Random(f"muse|{date}")` makes every run in a day sample the SAME
  concepts - fine for one run/day, wrong for trials (each "paired run" would be the same
  run). Change the seed to `f"muse|{date}|{nonce}"` where `nonce` = count of existing `muse`
  journal rows today (derived, deterministic, no clock in the seed). Concepts are sampled
  ONCE per run, before the arms - both arms collide the same concepts by construction.
- Memoize per-run the network-dependent gate inputs so both arms see identical data:
  `load_closes`/`fetch_daily_closes` results and `_options_gate` results, keyed by
  underlying, in a plain dict passed through `_evaluate`. Without this, arms can disagree
  because a quote moved between calls - a fairness bug that would be invisible.
- If a gate raises for an underlying (network flake), exclude that CANDIDATE from the trial's
  reward on WHICHEVER arm it appears (score it in neither `s` nor `f`); production handling
  (`no usable price history` fate) is unchanged for the incumbent arm.

**Void trials:** if the challenger's LLM call raises (HTTP error), the trial is VOID - append
`trial_result` with `challenger: {"voided": "<exc type>"}` and score nothing. If the call
succeeds but parses to zero candidates, that is a REAL result: score 0 survivors from 0
candidates... which contributes nothing to a Bernoulli count - so additionally count a
parse-to-nothing reply as `f += CANDIDATES` (the variant was asked for `CANDIDATES` theses
and produced zero usable ones). This is the GLM-5.2 lesson (D-084): an empty "success" is
the worst failure precisely because nothing else penalises it - the reward must.

### 5.3 THE critical edge case - why the challenger must be shadow

A naive implementation calls `muse.run` twice, once per variant. That would: register every
challenger candidate in the thesis ledger (inflating D-052's trial count with experiment
artifacts and re-polluting calibration - D-080's exact defect, rebuilt), emit challenger
survivors to the inbox (production behaviour changed by an experiment), and double every
journal row. The shadow rules exist to prevent all three. The test
`test_shadow_arm_never_touches_ledger_inbox_or_journal_thesis_rows` is the contract: run a
paired trial against fakes and assert ledger row count, inbox file count and `muse` journal
row count are IDENTICAL to a no-trial run.

### 5.4 Mutation role - generating challengers

- New role `coach_mutate` in `config.yaml` `llm.roles`, cheap tier:
  `["openai:gpt-5-mini", "anthropic:claude-opus-5"]` (synthesis, not judgement - D-066's
  reasoning). New pricing entries are NOT needed (both already priced).
- Inputs to the prompt: the incumbent prompt text; the last ~30 rejection fates grouped by
  gate (from muse journal rows - `fates` field); a graveyard digest (each defeated
  challenger: its diff-summary or first 200 chars + final posterior). Ask for ONE full
  replacement prompt that keeps the contract (below) and changes ONE thing, stated in a
  `rationale` field: `{"rationale": str, "prompt": str}`.
- **Deterministic validation before the challenger may enter an experiment** (a bad mutation
  must die at generation time, not crash a muse run later):
  1. All placeholders present: `{today} {n} {k} {concepts} {news} {odds} {earliest}
     {preferred} {latest}` - and no OTHERS: attempt `text.format(**dummy_values)` in
     try/except; a stray `{` from JSON examples in the mutated text raises KeyError/
     ValueError here rather than in production. (Note the incumbent survives this because
     its JSON block uses `{{`-escaped braces - the validator proves the mutation kept that.)
  2. The literal substring `band_low_pct` and `band_high_pct` and the words "JSON array"
     survive (the schema contract).
  3. Length <= 2x the incumbent's character count (prompt bloat is a cost lever too).
  Failures: journal `coach_mutation_rejected` with the reason, no experiment opens this
  pulse; try again next pulse. Two consecutive failures - skip a day (backoff, coarse).
- The mutated text goes into lever state as `challenger` with `origin: "mutation"`.

### 5.5 Sentinels (phase 2, but the hooks land in phase 1)

Config block (accessors on `Config`, defaults in code so an absent block degrades to
defaults, never to off):

```yaml
coach:
  enabled: true
  cost_ceiling_usd_per_day: 10.0
  churn_max_promotions_per_day: 2
  entropy_min_type_pairs_10: 3
```

| Sentinel | Predicate (deterministic, from stores) | On fire | Resume |
|---|---|---|---|
| `cost_ceiling` | `UsageLedger` cost for THIS UTC day, roles `muse`+`coach_mutate`, > ceiling | close open experiment (`sentinel_reverted`), no new ones | next UTC day |
| `health_problem` | `health.check()` has any BAD persisting across 2 consecutive pulses | pause new experiments (leave open one running - it may be unrelated; note it in the row) | first clean pulse |
| `entropy_floor` | distinct concept-type pairs over last 10 muse runs < min | close open experiment, revert | 10 fresh runs above floor |
| `churn` | promotions today > max | pause new experiments | next UTC day |

"Close and revert" always means: incumbent stays live (it already is - shadow design means
there is nothing to roll back in production), challenger graveyarded, `sentinel_fired` +
journal + marker rows written. Persist which sentinel is blocking inside the lever state
(`"sentinel_block": {"name": …, "since": …}`) so resume rules survive restarts; clear it when
the resume condition holds.

### 5.6 Audit (phase 3)

Runs inside `pulse` step 4. Join resolved ledger entries (`outcome is not None`) with
`variant`. For a lever whose current incumbent was PROMOTED (state has `previous`): once both
sides have >= 10 resolved entries since the promotion... they will not, inside a hackathon -
so the rule is windowless: compare ALL resolved entries by variant id, promoted vs previous,
hit = `outcome`. Same Beta comparison as promotion; if `P(promoted worse) >= 0.9` with >= 10
resolved per side, open a re-match experiment (previous incumbent as challenger - it
re-earns its place through the normal trial machinery rather than being restored by fiat).
At most one auto re-match per lever per 7 days (count `experiment_opened` rows whose
challenger origin is `"audit_rematch"`). Append `audit_result` every pulse it evaluates,
even with `action: "none"` - the audit's own null path must leave evidence.

### 5.7 `report.py` + CLI (phase 2)

- `trdrbot report`: read metrics.jsonl + experiments.jsonl + journal markers; write
  `data/report.html`, self-contained (inline CSS, inline SVG; zero external requests).
  Sections, in order: **What changed** (last 7 days: promotions, reverts, sentinels, opened/
  closed experiments); **Open experiments** (lever, variants, runs so far, current posterior,
  floors remaining); **Gauges** (one sparkline each - a simple `<svg><polyline>` from the
  snapshot series, min/max/latest labelled, promotion/revert markers as vertical lines);
  **Sentinels** (state + last fired); **Coach self** (trials, promotion count,
  realized-vs-claimed once the audit exists). Keep it under ~250 lines of Python; this is a
  utility page, not a product.
- `trdrbot coach`: terminal status - per lever: incumbent id/fp/since/origin, paused/pinned,
  open experiment with posterior and run counts, last 3 closed experiments with outcomes,
  sentinel blocks. Follow `cli.py`'s existing `_health`/`_usage` formatting style; register
  the subcommands exactly as the existing `sub.add_parser` pattern does.

### 5.8 `health.py` probe

```python
Probe(
    "coach", ("coach_run",),
    lambda rows: sum(int(r.get("trials_scored_today") or 0) for r in rows), 2,
    "the improvement loop is not scoring trials - experiments open but no muse "
    "runs are feeding them, or trial recording is broken",
    work=lambda rows: sum(int(r.get("experiments_open") or 0) for r in rows),
    never_producing_is_ok=True,          # no experiment open is a legitimate steady state
    stopping_after_output_is_ok=False,   # scored once then silent WITH an open experiment
                                          # is exactly the D-074 shape - flag it
)
```

The heartbeat row must therefore carry `experiments_open` and `trials_scored_today` with
these exact key names, or the probe silently reads zeros - add a test asserting the keys the
probe reads are the keys `pulse` writes (this exact mismatch is how `_market_pulse` died).

### 5.9 Muse cadence (the trials need runs to feed on)

The muse today runs only via `trdrbot muse`. Trials need repetition: wire `muse.run` into the
hunt rung in `tick.py` (where discovery already fires, ~line 322), after discovery, capped at
3 muse runs per UTC day (count today's `muse` journal rows - no new marker file). This is a
cadence default, not a law - record the chosen number in the decision record. Cost note for
the record: with a trial open, each muse run is 2 muse-role calls; at 3/day that is within
the cost sentinel's default ceiling by a wide margin at current per-call costs (measure and
state actuals in the decision record, do not copy this sentence).

### 5.10 `prompts.py` - the muse joins the inventory

`inventory()` today omits the muse prompt entirely (predates it). Add
`PromptRef("muse.collide", "free_standing", <ACTIVE incumbent text>)` - read through the
lever state with a fallback to the in-code `MUSE_PROMPT` when no state file exists. The
in-code `MUSE_PROMPT` constant remains as the v0 seed and the fallback; it is not deleted.

## 6. Phases, each with acceptance criteria

**Phase 1 - the loop end to end, one lever.** coach.py (registry, state, trials, promotion
math, graveyard, pulse steps 1/3/5/6), muse refactor + shadow arm, mutation role +
validation, journal kinds, health probe, `trdrbot coach`, cadence wiring, tests.
DONE WHEN: with a fake model and fake tools, a full experiment runs from `experiment_opened`
through 12+ paired trials to a promotion that swaps lever state and survives a process
restart; the shadow-arm invariance test passes; `trdrbot health` shows the coach probe OK on
a fresh install; all existing tests still pass.

**Phase 2 - sentinels + report.** Sentinel evaluation in pulse step 2, config accessors,
`report.py`, `trdrbot report`, markers.
DONE WHEN: a synthetic over-ceiling usage day closes an open experiment and blocks new ones
until the (simulated) next day; the report renders from empty stores without error and from
populated stores with visible markers.

**Phase 3 - audit + sampling lever.** `variant` on ledger entries (goes in phase 1 already
since registration must tag from the start - move it there), audit in pulse step 4,
re-match; second lever `muse.sampling` (incumbent: uniform stratified as today; challenger:
Thompson over concept-TYPE pairs, Beta per pair, reward = a candidate seeded from the pair
survives; epsilon floor 0.2 uniform). Sampling trials pair on news only (concepts
necessarily differ - that IS the treatment); note it in the experiment row.
DONE WHEN: audit emits `audit_result` rows on real resolutions; the sampling lever runs an
experiment using the identical trial/promotion machinery with zero changes to coach.py's
protocol code (if it needs protocol changes, the protocol is wrong - stop and reconsider).

**Explicitly OUT of scope for this build:** discovery/research/decide levers, gate-threshold
levers, decide-shadow trials, any elfmem/constitution lever, any external charting library,
any new config knob not listed in 5.5.

## 7. Edge cases - the complete required-handling list

| # | Case | Required handling |
|---|---|---|
| 1 | Challenger arm side effects | Shadow rules, 5.3. The invariance test is the contract |
| 2 | Same-day rng seed collision | Per-run nonce in the seed, derived from journal count, 5.2 |
| 3 | Mutated prompt breaks `.format` | Dummy-format validation at generation time, 5.4 |
| 4 | Mutated prompt drops the JSON schema | Substring checks, 5.4 |
| 5 | Challenger LLM call raises | Trial VOID - recorded, unscored, 5.2 |
| 6 | Challenger parses to nothing | Scored as `CANDIDATES` failures - the GLM lesson, 5.2 |
| 7 | Quote moves between arms | Per-run memoization of closes + options gate, 5.2 |
| 8 | Gate network flake on one candidate | Candidate excluded from reward on both arms, 5.2 |
| 9 | Corrupt/missing lever state JSON | Log, run incumbent-only from in-code v0 seed, never crash; do NOT overwrite the corrupt file (a human may want to read it) - write a fresh one only on the next legitimate state change |
| 10 | Human edits state mid-experiment | `pulse` re-reads state each time; if the open experiment's variant ids no longer match, close as `operator_override`, no promotion |
| 11 | Crash between promotion append and state swap | Order: append `experiment_closed` FIRST, then swap state atomically. On startup/pulse, reconcile: a `promoted` close whose lever state still shows the old incumbent is re-applied (idempotent - state swap keyed by exp_id, skip if `since` already >= close ts) |
| 12 | Two pulses racing (CLI + loop) | Same single-process assumption the rest of the system makes (run lock exists in cli). Do not build locking; note the assumption in coach.py's docstring |
| 13 | Journal grows; gauge reads slow | Gauges read via one pass over `journal.read()` per pulse, shared across gauges (collect rows once, dispatch) - not one full read per gauge |
| 14 | UTC-day boundaries | All "today" logic uses `ids.utc_now().date()` - never local time, never `datetime.now()` |
| 15 | No muse runs for days (market closed, loop down) | Experiments simply idle; timeout counts RUNS, not days - no clock-based expiry |
| 16 | Coach disabled in config | `coach.enabled: false` - pulse writes the heartbeat with `experiments_open: 0` and does nothing else; health stays quiet (never_producing_is_ok) |
| 17 | Absence-as-zero in gauges | Omit unknown gauges from the snapshot; report renders gaps, not zeros |
| 18 | Promotion floor gaming by tiny candidates | The `min_candidates >= 30` floor exists because 12 runs of 1 candidate each is 12 Bernoulli trials wearing 12 runs' clothing |

## 8. Tests that must exist (project naming style; every one maps to a rule above)

Pure logic (no I/O, no network):
- `test_p_challenger_better_is_half_when_posteriors_are_identical` (grid integration sanity,
  assert 0.5 +- 0.01)
- `test_a_fair_coin_challenger_is_never_promoted` - simulate 40 runs where both arms draw
  from the same deterministic fate sequence; assert no promotion (the Coach's zero-EV
  property, same spirit as the structure zoo's Kelly test)
- `test_promotion_needs_the_posterior_and_both_floors` (three cases: high P low runs, high P
  low candidates, low P high runs - none promote)
- `test_futility_closes_early_and_keeps_the_incumbent`
- `test_timeout_at_the_run_cap_keeps_the_incumbent`

Integration (fakes for model/tools, tmp_path stores):
- `test_shadow_arm_never_touches_ledger_inbox_or_journal_thesis_rows` (5.3 - the contract)
- `test_both_arms_of_a_paired_run_see_identical_closes_and_options_gates`
- `test_a_challenger_reply_that_parses_to_nothing_scores_as_failures_not_a_void`
- `test_a_challenger_http_error_voids_the_trial_and_scores_nothing`
- `test_promotion_swaps_incumbent_keeps_previous_and_survives_a_reload`
- `test_promotion_is_idempotent_across_a_crash_between_close_and_swap` (edge 11)
- `test_a_mutated_prompt_missing_a_placeholder_is_rejected_before_any_experiment`
- `test_a_mutated_prompt_with_stray_braces_is_rejected_by_the_dummy_format`
- `test_corrupt_lever_state_degrades_to_the_seed_incumbent_and_does_not_crash`
- `test_operator_pause_closes_the_open_experiment_without_promotion` (edge 10)
- `test_lever_reward_disjointness_is_enforced_by_the_scheduler` (construct a synthetic lever
  whose reward_modules overlap an open experiment's; scheduler refuses)
- `test_coach_heartbeat_keys_match_what_the_health_probe_reads` (5.8 - the `_market_pulse`
  lesson as a test)
- `test_the_muse_journal_row_carries_the_variant_and_fingerprint`
- `test_sentinel_cost_ceiling_reverts_and_blocks_until_the_next_day` (phase 2)
- `test_the_report_renders_from_empty_stores` (phase 2)
- `test_the_audit_files_at_most_one_rematch_per_week` (phase 3)

Contract (`tests/test_contracts.py`, real network, skip without keys):
- `test_the_mutation_role_returns_a_prompt_that_passes_validation` - the belief that a cheap
  model can do this task at all is exactly the kind that must be verified against the real
  endpoint, not assumed (D-083/084/085's whole arc).

## 9. Conventions checklist for the implementer

- Run `uv run pytest -q` before every commit; the suite must be green INCLUDING your new
  tests. Never pipe pytest output in a way that masks the exit code.
- Append a decision record `D-088` to `specs/decisions.md` in the house style: context,
  measured findings, choices WITH the rejected alternatives and why, verified-with-numbers
  footer. Read D-086 as the template.
- Any deliberate deferral or discovered defect gets an `I-N` entry in `specs/issues.md`.
- Update `README.md` with a short "self-improvement (the Coach)" section: what it does, the
  two CLI commands, where the state lives, how to pause/pin.
- Plain dashes everywhere. No agent co-author trailer on commits. Commit locally per phase
  with messages in the existing style (read `git log --oneline -20`).
- New journal kinds, store paths and config keys: exactly the names in this document -
  downstream consumers (probe, report, tests) key on them literally.
- When a claim in this plan disagrees with the code you find (a signature moved, a field is
  named differently), the CODE wins - adapt, and note the divergence in D-088 rather than
  forcing the plan's wording onto a changed interface.
