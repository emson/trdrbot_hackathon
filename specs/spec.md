# trdrbot — Specification

## Overview
trdrbot is an AI-driven options trading agent built for the Alpaca AI Trading Agents Hackathon.
It runs as a headless LangGraph service woken on a schedule *(D-008, D-003)*. Each tick, a
deterministic Collector polls Alpaca via MCP and writes typed observations into a file-based
inbox; a Processor — one LangGraph graph — drains the inbox and routes items by type *(D-010)*:
market observations flow into a decide path where a gateway-selected LLM, primed with elfmem's
goals/constitution/patterns, the LLM wiki's long-term knowledge, and per-trade outcome
forecasts from the calibration module *(D-011, D-013)*, chooses actions and executes them
directly through Alpaca's MCP order tools —
there is no guardrail layer *(D-009)*. Fill and outcome items flow into a learn path that
backfills the journal and consolidates lessons into elfmem and the wiki. Everything persistent
lives in files: the inbox archive, `journal.jsonl`, and the wiki.

Two simulation passes ([notes/006](notes/006_simulation_stress_run.md),
[notes/007](notes/007_simulation_regression_run.md)) hardened this design before any code was
written: a per-tick deterministic layer now reconciles broker state, evaluates agent-authored
exit rules, and force-closes on the competition deadline — all before the slower LLM decide path
runs *(D-017, D-019)*, and all in a fixed order (reconcile before exit rules) that matters for
correctness, not just cost. See [architecture.md](architecture.md) for the full component
catalogue, invariants, and failure-mode table.

## Architecture
```
launchd/cron tick (market-hours aware, D-003, D-008)
    |
    v
Collector (deterministic Python — no LLM)
    |  polls via Alpaca MCP: account, positions, open orders,
    |  option chains, fills; emits typed JSON items
    v
inbox/pending/*.json   <---- manual injection (testing), future feeds
    |  drained every tick; at-least-once; flock single-flight
    v
Processor — one LangGraph graph (D-008, D-010)
    |
    ├─ route by item type
    |
    ├─ observations ──> DECIDE path
    |     context:  elfmem — goals, constitution, patterns   (D-011)
    |               wiki — index-first lookup, lessons,       (D-011)
    |                      positions/<id>.md entity pages
    |               journal + portfolio state
    |     forecast: calibration module — outcome probability   (D-013)
    |               per candidate action, advisory only
    |     decide:   gateway-selected LLM (model per config)   (D-008)
    |     act:      Alpaca MCP order tools — direct, no gate  (D-009)
    |
    ├─ fills/outcomes ──> LEARN path
    |     journal backfill (thesis vs outcome), elfmem
    |     pattern update, wiki consolidation
    |
    └─ housekeeping ──> wiki/index upkeep, daily digest
    |
    v
journal.jsonl (append-only)   wiki/   inbox/processed/ (immutable archive)
```
- One AI decision-maker (the gateway-selected LLM inside the graph); deterministic code
  everywhere else *(D-008)*.
- MCP is the integration path to Alpaca; polling only, no WebSocket streaming in v1 *(D-003)*.
- All activity targets the paper trading endpoint; there is no live-trading code path in v1.
- No risk-policy layer *(D-009)*. Correctness plumbing only: idempotent orders via
  `client_order_id`, at-least-once inbox semantics, append-only journal.
- Memory roles *(D-011)*: elfmem = evolving working memory; wiki = durable long-term knowledge;
  journal = ground truth. Consolidation flows journal → elfmem patterns → wiki lessons.

## Planned Modules
<!-- Full specification (inputs/outputs/behaviour/edge cases/errors) is pending — Specify mode,
     next session. Listed here so build sequence and acceptance criteria can reference them. -->
- **Chassis** — config, secrets, storage layout, MCP client factory, LLM gateway wiring,
  scheduler entrypoint, tick counter, locking *(D-008)*.
- **Collector + Sensor Registry** — scheduled deterministic polling driven by declarative sensor
  entries (cadence, policy, trust); emits typed inbox items *(D-010, D-015)*.
- **Analytics Engine** — deterministic Python: regime, indicators, per-position and portfolio
  greeks; emits `regime_change` events *(D-016)*.
- **Digester** — LLM condensation of high-volume source batches, preserving open-position
  mentions verbatim *(D-015)*.
- **Tool Registry** — agent-invocable LangGraph tools for ad-hoc math *(D-016)*.
- **Exit Rule Evaluator** — deterministic per-tick evaluation of agent-authored `exit_rules`;
  closes all legs on breach; no LLM *(D-017)*.
- **Inbox** — the data contract: item schema, pending/processed lifecycle, injection for
  testing *(D-010)*.
- **Processor graph** — LangGraph router + decide path + act node + learn path *(D-008, D-010)*.
- **Memory integration** — elfmem adapter, wiki library, journal writer *(D-011)*.
- **Calibration module** — per-trade outcome forecasts at decide time, Brier/Murphy scoring at
  close, calibration lessons into memory *(D-013)*.

## Data Model

### The provenance spine

Alpaca is authoritative for **what we hold**; trdrbot is authoritative for **why**. Alpaca also
has no concept of a multi-leg strategic position — a bull put spread is two independent
per-leg rows. One decision therefore has to be stitched to N broker rows by us.

Everything hangs off one identifier, `position_id`, threaded through every store:

```
position_id: pos_20260828_SPY_bps_a3f2
   |
   ├─ journal.jsonl        decision → execution → fill → reflection  (append-only truth)
   ├─ wiki/positions/<position_id>.md   the living narrative          (curated, edited)
   ├─ elfmem                thesis block + mind_predict               (evolving, scored)
   └─ Alpaca               client_order_id carries it back            (broker round-trip)
```

Format: `pos_<YYYYMMDD>_<underlying>_<strategy>_<short-hash>` — sortable, greppable, readable
as a filename.

**Provenance is not documentation, it is the learning substrate.** The decision record captures
which elfmem blocks were recalled (`mem.last_recall_block_ids`) and which wiki pages were read.
When the position closes, those exact block ids are what `outcome(block_ids, signal)` reinforces
or penalises *(D-011)*. Without the chain there is no credit assignment, and elfmem accumulates
instead of learning.

### Division of labour

| Store | Mutability | Answers | Role |
|---|---|---|---|
| `journal.jsonl` | append-only, never edited | "what happened, in order" | ground truth; rebuild spine |
| `wiki/positions/*.md` | edited as position evolves | "what is the story of this position" | what the LLM reads at decide time |
| elfmem | evolves, scored, can forget | "what do I know that's relevant now" | generalised patterns, not a position store |

elfmem deliberately does **not** hold positions — it holds theses, patterns, and live
predictions. Position state lives in files so it survives an elfmem reset.

### Entity: Position (`wiki/positions/<position_id>.md`)

Frontmatter is the machine-readable spine; the prose below it is what the model actually reads.
Frontmatter follows OKF conventions *(D-022)*: `type` is the only field OKF itself requires;
`sources`/`generated`/`verified` are OKF's provenance/trust fields, adopted directly.

```markdown
---
type: Position                       # OKF-required field (D-022)
position_id: pos_20260828_SPY_bps_a3f2
status: proposed|opening|open|adjusting|closing|closed|expired|assigned|orphaned
strategy: bull_put_spread
underlying: SPY
opened: 2026-08-28T14:35:00Z
expiry: 2026-09-18
intended_legs:                      # what we meant to hold
  - {occ: SPY260918P00560000, side: short, qty: 5}
  - {occ: SPY260918P00555000, side: long,  qty: 5}
actual_legs:                        # what Alpaca says we hold — divergence is a real state
  - {occ: SPY260918P00560000, side: short, qty: 5, fill: 3.20}
  - {occ: SPY260918P00555000, side: long,  qty: 5, fill: 1.85}
decision_ref: jrn_20260828T143500Z_d41
exit_rules:                          # authored by the agent at entry (D-017)
  - {type: stop_loss,     basis: position_mark, threshold: -50%}
  - {type: profit_target, basis: position_mark, threshold: 50%}
  - {type: time_stop,     days_before_expiry: 2}
close_reason: null                   # thesis_resolved | stop_triggered | target_hit
                                     # | time_stop | deadline | external | agent_discretion
forecast: {p_max_profit: 0.65, verify_at: 2026-09-18, mind_block: 7c2a...}
elfmem_blocks:                       # ← credit-assignment targets, captured PER FRAME (INV-22)
  self: [f90171e2...]
  task: [b12c9d04...]
  attention: [a3b81c04...]
sources:                             # OKF provenance (D-022) — replaces the old wiki_refs shape
  - {id: lessons-1, resource: lessons.md, author: "trdrbot/decide", last_modified: 2026-08-28T14:30:00Z}
  - {id: strategy-1, resource: strategy.md, author: "trdrbot/decide", last_modified: 2026-08-27T09:00:00Z}
generated: {by: "anthropic:claude-opus-5", at: 2026-08-28T14:35:00Z}   # OKF (D-022)
verified: []                         # populated by reconciliation on fill confirmation (D-022)
---

## Thesis
One paragraph: why this trade, what must be true, what invalidates it.[^lessons-1][^strategy-1]

## Timeline
- 2026-08-28 opened for 1.35 credit
- 2026-08-29 underlying +0.8%, at 40% max profit

## Outcome
Written at close: realised P&L, did the thesis hold, Brier resolution, lesson extracted.

[^lessons-1]: current lessons.md guidance active at decision time
[^strategy-1]: current strategy.md playbook active at decision time
```

**`sources[]` replaces the old flat `wiki_refs` list** *(D-022)*: each entry is `resource`
(what was read) plus credibility signals `author`, `usage_count`, `last_modified` — no stored
score, since a score would itself go stale. Per-claim footnotes are **keyed by `sources[].id`,
not position**, because **the learn path actively rewrites the wiki** — by review time the page
that informed a decision may read differently, and a positional citation (`sources[0]`) would
silently misattribute the moment the list reorders. The wiki directory is in git, so
`git log -p -- lessons.md` around `last_modified` recovers what the model actually saw.

**`generated`/`verified` are OKF's trust-tier fields** *(D-022)*: `generated.by` is the model
that made the decision (formalizes D-008's existing model-attribution requirement).
`verified: []` starts empty (**unverified** tier) and gains an entry — `{by: "trdrbot/reconcile",
at: ...}` — when reconciliation independently confirms the fill, promoting the position to
**machine-confirmed**. A `human:<id>` entry would be **human-reviewed**, not expected in normal
autonomous operation but the field exists if a team member ever intervenes.

`intended_legs` vs `actual_legs` exists because with no guardrails *(D-009)* a partial multi-leg
fill can leave a broken spread whose risk profile is nothing like the intent. We do not prevent
it; we make it visible — and a divergence puts the position in the **needs-attention** tier so it
cannot be summarised away under context pressure *(D-018 #7)*.

`exit_rules` are the agent's own commitments, evaluated deterministically every tick and closing
**all legs together** *(D-017, INV-19)*. `close_reason` is what keeps credit assignment honest:
a thesis is scored only when the position resolved on its own terms, so a sound thesis exited by
a stop or an external event is not recorded as a bad thesis *(D-018 #9)*.

**Position status is the exactly-once guard** *(INV-17)*: a position may enter a terminal state
only once, whichever detector fires first (reconciler, collector, or exit-rule evaluator). This
is what prevents double credit assignment when two paths observe the same resolution.

### Entity: Journal entry (`journal.jsonl`, append-only)

```json
{
  "id": "jrn_20260828T143500Z_d41",
  "ts": "2026-08-28T14:35:00Z",
  "kind": "decision|execution|fill|adjustment|close|reflection|error|reconciliation",
  "position_id": "pos_20260828_SPY_bps_a3f2",
  "batch_ids": ["obs_..."],
  "model": "<gateway model id>",
  "context": {
    "elfmem_blocks": ["f90171e2..."],
    "wiki_refs": [{"path": "lessons.md", "sha": "9f2b1a"}],
    "forecast": {"p_max_profit": 0.65}
  },
  "thesis": "one line",
  "action": {},
  "result": {}
}
```

The journal is the only store that never loses history, so it is the rebuild path: position
pages can be regenerated from it if the wiki is damaged or elfmem is reset.

**Write-ahead ordering is mandatory** *(INV-18, D-018 #3)*: the `decision` entry is journalled
**before** the order is submitted, and `client_order_id` derives from the **inbox batch**, not
from the decision. LLM decisions are nondeterministic, so a crash-retry that re-decides would
otherwise generate a different key and open a second, *different* position — a failure no
duplicate check would catch. Batch-derivation is safe because a cycle produces at most one action.

**Write-ahead only pays off if retry reads it** *(INV-27, D-019)*: before deciding, the processor
checks whether the current batch already has a `decision` entry with no matching `execution` or
rejection. If so, it **resumes** — re-attempts the same submission, safely idempotent because the
`client_order_id` is identical — rather than re-invoking the LLM. Regression simulation found
that without this check, a crash between write-ahead and submit produced an orphaned decision
record and a wasted LLM call on every retry; the batch-derived id alone prevents real duplicate
market exposure, but not this bookkeeping cost.

### Entity: Inbox lifecycle and dead-lettering *(D-018 #2, refined by D-019)*

`pending/` → `processed/<date>/` on success; an item that fails processing carries a retry
counter and moves to `inbox/failed/` after N attempts so the batch can proceed. Without this, one
malformed item is retried every tick forever and the pipeline stalls permanently while appearing
to run. **Failure cause determines patience** *(INV-30)*: a schema-validation failure dead-letters
quickly (it will never succeed); an MCP/dependency-outage failure retries longer with backoff
(it may well succeed once the dependency recovers). Reconciliation (F5) independently rediscovers
position-affecting facts (fills, assignments) on a later tick regardless of what happens to their
inbox item, so dead-lettering one is not a true loss — only a delay. A dead-lettered news or
social item has no such redundancy and is genuinely, permanently lost.

### Entity: Source item (inbox, from external/internal sensors) *(D-015)*

```json
{
  "id": "src_20260828T143500Z_polymarket_fedcut",
  "ts": "2026-08-28T14:35:00Z",
  "type": "news | social | prediction_market | regime_change",
  "sensor": "alpaca_news | x_social | google_feed | polymarket | internal_analytics",
  "trust": "primary | secondary | social",
  "payload": {},
  "digest_of": ["src_...", "src_..."]
}
```

`trust` propagates into every derived item and into the decide prompt (INV-13). `digest_of`
links a briefing back to the raw items it condensed — the raw is always archived (INV-12), so a
digest is never the only copy. Source item ids cited in a decision are recorded in the journal's
`context` and scored at resolution alongside elfmem blocks, which is how the system learns which
sources to trust.

### Entity: Market context (`wiki/context/*.md`, slow-changing) *(D-015)*

Three small pages read by every decide cycle and refreshed at housekeeping:

- **`regime.md`** — current trend/volatility assessment, with the date it last changed.
- **`macro.md`** — the standing macro picture (rate cycle, prevailing themes).
- **`calendar.md`** — forward calendar of known events (FOMC, CPI, earnings), which pairs with
  options expiry selection and with the calibration module *(D-013)*.

These are the agent's equivalent of what a trader keeps in their head: compact, durable, and
always in context — as distinct from position pages, which are per-position and read on demand.

### Entity: Portfolio (`wiki/portfolio.md`, regenerated)

Not a stored aggregate — a rendered snapshot, rebuilt from Alpaca holdings joined to position
pages at housekeeping. One row per open position: underlying, strategy, days to expiry, current
P&L, one-line thesis, link to its page. This is the at-a-glance view for the agent, and the
artifact a judge reads to understand the whole book at once.

### Lifecycle and who writes what

| Event | Writer | Effect |
|---|---|---|
| Decision made | decide path | journal `decision` **write-ahead**, with full context refs; no wiki page yet (may not fill) |
| Order submitted | act path | `client_order_id` derives from the batch; journal `execution` |
| **Exit rule breached** | exit-rule evaluator | status → `closing`; close **all legs**; journal exit with `close_reason` *(D-017)* |
| **Housekeeping (position still open)** | housekeeping path | interim outcome scored at **low weight**, so the loop turns even before resolution *(INV-24)* |
| Fill observed | learn path | create `positions/<id>.md`; elfmem `remember(thesis, cue=...)` + `mind_predict(verify_at=expiry)`; journal `fill` |
| Position evolves | learn path | append to Timeline |
| Close / expiry / assignment | learn path | Outcome section; compute Brier *(D-013)*; `mind_outcome()`; `outcome(elfmem_blocks, signal)`; lesson → `lessons.md` + elfmem |
| Housekeeping | housekeeping path | regenerate `portfolio.md`, update `index.md` |

**Options-specific lifecycle events happen to us, not from us**: expiry, assignment, and
exercise close positions with no decision of ours. The collector detects them by diffing
Alpaca holdings against open position records, and emits them as inbox items like any other
observation — the learn path resolves them through the same route as a deliberate close.

### Reconciliation (each tick, deterministic — no LLM)

Diff Alpaca holdings against open position pages:

- **In Alpaca, not in our records** → create a stub page, `status: orphaned`,
  `provenance: unknown`. Never crash; a position with no story is still a position.
- **In our records, not in Alpaca** → expired, assigned, or closed outside our loop; route to
  the learn path to resolve.
- **Quantities disagree** → partial fill or partial close; update `actual_legs` and flag the
  divergence from `intended_legs`.

This is correctness plumbing, not policy — it never blocks a decision *(D-009)*.

**Ordering matters, not just presence** *(INV-25, D-019)*: reconciliation runs **before** exit-rule
evaluation (C24) in every tick. Regression simulation found that the reverse order let the exit
evaluator act on stale local state at the exact tick an assignment posted at the broker — best
case a rejected order, worst case a nonsensical mark for a spread already missing a leg. With
reconciliation first, a position resolved externally this tick is already terminal by the time
exit rules run, and is excluded from consideration by construction, not by an extra check.

**The competition deadline is enforced independently of any position's own expiry** *(INV-26,
D-019)*: on or after the fixed deadline date, every remaining open position is force-closed via
the same exit-rule mechanism, `close_reason: deadline`. A position's own `time_stop` only bounds
it to its own expiry — for a conventional 30-45 DTE spread that falls weeks past the competition,
which would otherwise mean the learning loop never completes a single true resolution. This is
not a guardrail: it blocks no trade, it only enforces a known scheduling fact, the same category
as the market-hours check.

### Cold-start reconstruction

Every tick starts with no memory of the last one. "Why do I hold this" is answered purely from
files: read Alpaca positions, join to `positions/<id>.md` by `position_id`, inject the thesis
and timeline into the decide prompt alongside elfmem's `attention`/`task`/`self` frames. The
position page exists precisely so that a cold agent can inherit the reasoning of a warm one.

## Modules

<!-- Copy this block for each module: -->

### [Module Name]
**Does:** <!-- one sentence -->

**Inputs:**
- <!-- what it receives, from where, in what format -->

**Outputs:**
- <!-- what it produces, to where, in what format -->

**Behaviour:**
1. <!-- step — what happens (include what happens when it fails) -->
2. <!-- step -->

**Edge Cases:**
- <!-- what if input is empty/malformed/huge? -->
- <!-- what if a dependency is unavailable? -->
- <!-- what if there's concurrent access? -->

**Errors:**
| Condition | Response | Recovery |
|---|---|---|
| <!-- error case --> | <!-- what happens --> | <!-- how to recover --> |

## API / Interfaces
<!-- Every boundary where components talk to each other or the outside world.
     For each endpoint: method, path, auth, request shape, response shape(s), errors, pagination, rate limits -->

## Non-Functional Requirements
<!-- Performance targets, security requirements, deployment approach,
     monitoring, logging — but ONLY what the build team needs to know -->

## Build Sequence
<!-- What order to build things in. What can be parallelised.
     Integration checkpoints. -->
1. 
2. 

## Acceptance Criteria
<!-- Per-feature: Given/When/Then format. Must be testable, not subjective.
     Trace each criterion back to a charter success criterion. -->

## Test Specifications

### Coverage Matrix
<!-- Generated during assembly — maps charter success criteria to test IDs -->
| Charter Success Criterion | Test IDs | Coverage |
|---|---|---|
| <!-- criterion --> | <!-- TEST-XXX-NNN --> | <!-- ✓ Full / ○ Partial / ✗ None --> |

<!-- Test specs are generated progressively:
     - Baseline: one per behaviour path + one per error condition when a module is specified
     - Simulation-derived: added as walkthroughs, contract tests, and consequence analyses discover edge cases
     - Format per test spec:

### TEST-[MODULE]-[NNN]: [Title]
**Source:** [spec section this verifies]
**Type:** [unit | API contract | integration | performance | manual review]
**Preconditions:**
- [what must be true before the test]
**Steps:**
1. [action]
**Expected:**
- [precise, verifiable outcome]
**Derived from:** [baseline | simulation ID]
-->

## Glossary
<!-- Domain terms that might be ambiguous. Define them precisely. -->
| Term | Definition |
|---|---|
