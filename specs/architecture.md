# trdrbot — Conceptual Architecture

**One-pager for humans; simulation input for LLMs.**
Companion to [charter.md](charter.md) (why), [spec.md](spec.md) (normative detail, data model),
[decisions.md](decisions.md) (D-003, D-007..D-023). This document is the conceptual layer: what
the components are, how they interact, what must always be true, and where it can break.
Hardened twice by simulation: [notes/006](notes/006_simulation_stress_run.md) (initial stress
run) and [notes/007](notes/007_simulation_regression_run.md) (regression + new adversarial
scenarios) — the fixes from both passes are folded in below, not left as separate documents to
cross-reference.

---

## 1. What trdrbot is

An AI options-trading agent for the Alpaca hackathon (paper trading, deadline 2026-09-04).
A scheduler wakes it; it observes markets and the wider world, decides at most one action per
situation, executes against Alpaca, records why, and learns from the outcome. It has **no risk
guardrails** by deliberate choice *(D-009)* — speed of iteration over protection of simulated
money. Its distinguishing feature is not the trading strategy but the **memory and provenance
loop**: every position carries a reconstructable chain back to the reasoning and knowledge that
produced it, and that position's outcome feeds back as reinforcement on the exact memories and
sources that informed it.

**Every tick is a cold start.** No context carries between runs. Continuity exists only in files.

---

## 2. System at a glance

```
        ┌──────────────────────────────────────────────────────────────┐
        │  RUNTIME & CHASSIS                                           │
        │  Scheduler → Tick Runner (flock) → config, secrets,          │
        │  MCP client factory, LLM gateway, tick counter               │
        └───────────────┬──────────────────────────────────────────────┘
                        │ fires
        ┌───────────────▼───────────────────────────────────────────────┐
        │  SENSE   (deterministic — no LLM)                             │
        │  Collector, driven by the SENSOR REGISTRY:                    │
        │    alpaca_market ▪ alpaca_news ▪ x_social ▪ google_feed       │
        │    ▪ polymarket ▪ internal_analytics                          │
        │  each: cadence · filter · trust tier · change detection       │
        │                          │ typed items                        │
        │                          ▼                                    │
        │                    ┌──────────┐                               │
        │                    │  INBOX   │◀── manual injection (testing) │
        │                    └────┬─────┘                               │
        └─────────────────────────┼─────────────────────────────────────┘
                                  │ drains
        ┌─────────────────────────▼─────────────────────────────────────┐
        │  THINK  (LangGraph)                                           │
        │  Router ─┬─ observations ─▶ Digester ─▶ Context Assembler     │
        │          │                   (if volume)   │ (budgeted)       │
        │          │                                 ▼                  │
        │          │                  Analytics Pack ─▶ Forecaster      │
        │          │                                 │        │         │
        │          │                                 └▶ Decider ◀───────┼── Tool
        │          ├─ fills/closes ──────────────────▶ (LEARN)          │   Registry
        │          └─ housekeeping ──────────────────▶ (LEARN)          │
        └─────────────────────────┬─────────────────────────────────────┘
                                  │ chosen action
        ┌─────────────────────────▼────┐        ┌──────────────────────┐
        │  ACT                          │        │  REMEMBER            │
        │  Actor ──▶ Alpaca MCP         │◀──────▶│  Journal (truth)     │
        │  Reconciler (diff holdings)   │        │  Wiki (narrative +   │
        └─────────────────────────┬────┘        │        context)      │
                                  │ outcomes     │  elfmem (patterns)   │
        ┌─────────────────────────▼────┐        └──────────┬───────────┘
        │  LEARN                        │───────────────────┘
        │  Learner, Calibration Scorer, │
        │  Housekeeper                  │
        └──────────────────────────────┘
```

Six subsystems. Three moving parts in practice: a **Collector script**, a **LangGraph
Processor**, and the **filesystem**. Everything else is a library or a registry entry inside one
of those. Adding a news source or a math tool adds **no new component** — only a registry entry.

---

## 3. The information & tooling layer

The design principle that keeps this simple: **two registries, two rhythms.**

### 3.1 Sensors — scheduled, push into the inbox

A sensor is a declared information source. Adding X, Polymarket, or anything future is one
registry entry, not new pipeline code.

```yaml
sensors:
  - id: alpaca_market      every_n_ticks: 1   trust: primary    policy: raw
  - id: alpaca_news        every_n_ticks: 3   trust: primary    policy: filter
  - id: internal_analytics every_n_ticks: 1   trust: primary    policy: change_only
  - id: polymarket         every_n_ticks: 12  trust: secondary  policy: change_only
  - id: google_feed        every_n_ticks: 12  trust: secondary  policy: filter
  - id: x_social           every_n_ticks: 6   trust: social     policy: filter
```

Four properties do all the work:

- **`every_n_ticks`** — cadence as a simple counter modulo, not clock arithmetic. Deterministic,
  trivially simulatable, and it means we only spawn the MCP servers a given tick actually needs.
- **`policy`** — `raw` (pass through: small and high-signal), `filter` (deterministic relevance
  against watchlist, open positions, and a macro keyword list), `change_only` (emit solely on
  material change against the sensor's last-seen state).
- **`trust`** — `primary` | `secondary` | `social`. Propagates into every derived item and into
  the decide prompt. This is the mitigation for false-but-viral content (FM-18): the constitution
  can require corroboration for `social`, and the learn path scores sources over time.
- **change detection state** — a tiny per-sensor state file (last-seen ids, last odds). Prevents
  re-emitting the same article every poll.

Sensors may be **external** (Alpaca, X, Google, Polymarket) or **internal** — `internal_analytics`
runs our own Python and emits a `regime_change` item when regime flips. Internal derivation and
external fetching are the same shape, which is why regime shifts arrive as events rather than
being buried as a number in a prompt.

**A failing sensor never fails a tick.** N consecutive failures parks that sensor for the day
with a loud log. This is sensor health, not trade policy — it never blocks a decision *(D-009)*.

### 3.2 Handling volume: filter, then digest, then budget

Three defences, escalating only as needed:

1. **Deterministic filter (always, free)** — inside the sensor, which knows its own data shape.
   Drops the bulk of noise on ticker/keyword match.
2. **Digest (LLM, only above a volume threshold)** — condenses a large surviving batch into a
   few briefing items. Quiet days never pay for it. The digest prompt must preserve anything
   naming an open position's underlying **verbatim**, and it always carries trust tiers through.
   Raw items are archived regardless, so nothing is lost to a bad digest.
3. **Context budget (assembly time)** — sections are assembled in priority order to a size cap:
   open positions → analytics pack → primary news → prediction markets → macro digest → social
   digest. Over budget, the lowest priority degrades first and the journal records what was cut.

The Collector stays **strictly LLM-free**; digesting lives in Think. Sense gathers and filters;
Think interprets.

### 3.3 Tools — on-demand, called during reasoning

Distinct from sensors: these are functions, not feeds. Two forms, and the split matters:

- **Analytics Pack (pre-computed, always injected)** — deterministic Python run before the
  decide call: regime (trend vs moving averages, volatility percentile), per-symbol indicators
  (ATR, IV rank), per-position greeks and days-to-expiry, and **portfolio aggregate greeks**
  (net delta/theta/vega, buying power used). The aggregate exposure view matters especially
  because nothing constrains it — the agent should at least *see* what it is carrying.
- **Tool Registry (agent-invoked)** — LangGraph tools for ad-hoc questions: option pricing,
  implied-vol surface, scenario math, backtest-style checks over collected history.

**Local mathematics should be LangGraph tools, not an MCP server.** MCP earns its place for
external, third-party, or separately-hosted capabilities (Alpaca, X, Polymarket). For numpy/scipy
code we own, running in our own process, a protocol boundary adds latency and failure modes for
nothing. Heavy computation that genuinely needs isolation can move to a subprocess later without
changing the registry's shape.

### 3.4 Exit rules — the agent's own commitments, executed reliably *(D-017)*

Every position carries machine-readable `exit_rules` in its frontmatter, **authored by the agent
at entry**. A deterministic evaluator (C24, no LLM) checks them every tick and closes the position
when one triggers.

```yaml
exit_rules:
  - {type: stop_loss,     basis: position_mark, threshold: -50%}
  - {type: profit_target, basis: position_mark, threshold: 50%}   # of max profit
  - {type: time_stop,     days_before_expiry: 2}
```

A small closed set of rule types, not a DSL: `stop_loss`, `profit_target`, `time_stop`.

**This is not a guardrail** *(D-009 stands)*. A guardrail is external policy that blocks an
intended action before it happens. An exit rule is the agent's own stated intent, honoured after
the position exists. The agent writes every rule and may rewrite or delete any of them on any
decide cycle — a commitment device it controls, not a constraint imposed on it.

Three properties make it worth the ~100 lines:

- **Closes the blind window.** The decide path is slow; a stop breach would otherwise sit
  unattended for a full cycle, which options gamma near expiry makes genuinely dangerous.
- **Makes `close_reason` mechanically reliable**, which is exactly what the learning fix in
  §11 gap #9 requires — the system knows whether a thesis resolved or was stopped, rather than
  inferring it from an LLM's self-report.
- **Rules fire on the position's net mark and close all legs together — never leg-level.**
  Stopping one leg of a spread can leave an unbounded naked short: strictly worse than the
  position it was meant to protect.

Prefer broker-native stops (bracket/OCO) where Alpaca supports them, since those survive our
process being down; fall back to the local evaluator otherwise. Multi-leg almost certainly needs
the local path (unverified — §12).

### 3.5 Where this information lives

Nothing here needs a new store — it maps onto the existing three plus one new wiki area:

| Data | Home | Why |
|---|---|---|
| Raw fetched news/tweets/odds | `inbox/processed/` | Immutable archive; already the wiki pattern's raw layer |
| Digests assembled for a decision | Journal decision `context` | Ephemeral by nature; reconstructable from raw |
| Durable market understanding | **`wiki/context/`** (new) | `regime.md`, `macro.md`, `calendar.md` |
| Learned source reliability | elfmem | e.g. "social sentiment is unreliable pre-open" |

`wiki/context/` is the one genuine addition: a small, slow-changing set of pages read by every
decide cycle — the current regime assessment, the macro picture, and a forward calendar of known
events (FOMC, CPI, earnings). It is what a human trader keeps in their head, and `calendar.md`
pairs naturally with options expiry selection and with the forecasting module *(D-013)*.

**Frontmatter conventions follow the Open Knowledge Format (OKF)** *(D-022)* — Google Cloud's
markdown-bundle spec, verified real and current
([notes/008](notes/008_open_knowledge_format_research.md)). Every wiki page gets `type:` (the
only field OKF requires); `sources[]` with footnote-keyed attribution replaces ad hoc citation;
`generated`/`verified` give a three-tier trust signal (unverified / machine-confirmed /
human-reviewed); `status`/`stale_after` (an absolute instant, not a TTL) mark freshness on
`wiki/context/*.md` specifically. `index.md` and `log.md` are OKF-reserved filenames — which our
design already used before this research, a happy convergence rather than a rename. Two
authoring disciplines are borrowed from OKF's reference implementation as house rules, not spec
*(D-023)*: a four-gate test before minting any new `lessons.md` entry, and — the actual answer to
"how do we stop an LLM-maintained wiki from degrading" — a write guard that refuses any edit
shrinking an existing `sources[]`/`tags[]` list or dropping a heading that was already there.

**Synergy worth exploiting:** Polymarket publishes calibrated crowd probabilities for macro
events; our calibration module produces our own probabilities. Systematic disagreement that we
lose on is a first-class calibration lesson, and Polymarket odds are a free forecast input.

---

## 4. Component catalogue

Each entry: what it does, what triggers it, how it fails. IDs (C1…) are stable simulation handles.

### Runtime & Chassis

| ID | Component | Responsibility | Trigger | Fails by |
|---|---|---|---|---|
| **C1** | Scheduler | Fires the tick on cadence (~60s), market-hours aware | launchd/cron | Machine asleep; misfire |
| **C2** | Tick Runner | `flock` (PID+timestamp, stale-breakable); tick counter; **watchdog timeout**; cheap paths every tick, decide every N | C1 | Lock held → skip (benign); hung path → watchdog kills |
| **C3** | MCP Client Factory | `MultiServerMCPClient` over the servers this tick needs | Per tick | Subprocess won't spawn; hangs; dies mid-tick |
| **C4** | LLM Gateway | Resolves model from config; single swap point | Per LLM call | Outage, rate limit, timeout |
| **C5** | Config & Secrets | `config.yaml` + `.env`; watchlist, cadences, budgets, model id | Startup | Missing keys; malformed config |

### Sense (no LLM)

| ID | Component | Responsibility | Trigger | Fails by |
|---|---|---|---|---|
| **C6** | Collector | Runs sensors due this tick; emits typed items | C2 | Partial source failure (isolated) |
| **C20** | Sensor Registry | Declares sources: cadence, policy, trust, filter | Config | Misconfigured cadence; bad filter |
| **C21** | Analytics Engine | Deterministic Python: regime, indicators, greeks, portfolio exposure; emits `regime_change` | C6 (internal sensor) + pre-decide | Missing data; numerical error |
| **C24** | Exit Rule Evaluator | Evaluates agent-authored `exit_rules` (+ the deadline sweep) on position net mark; closes all legs on trigger. **No LLM.** *(D-017; runs AFTER C13 per D-019)* | **Every tick**, after reconcile, before decide | N-of-M debounce still lags a genuine breach by up to M-1 checks (mitigated by the magnitude override) |
| **C7** | Inbox | File queue `pending/` → `processed/<date>/` → `failed/` (cause-differentiated dead-letter — D-019). The testing seam. | C6 or manual | Disk full; poison-pill item |

### Think

| ID | Component | Responsibility | Trigger | Fails by |
|---|---|---|---|---|
| **C8** | Router | Drain pending, classify, route; batch caps | C2 | Unknown type; flood |
| **C22** | Digester | LLM-condenses high-volume batches into briefings; preserves position mentions and trust tiers | Volume > threshold | Drops a critical item; timeout |
| **C9** | Context Assembler | Priority-budgeted assembly: positions, analytics pack, `wiki/context/`, digests, elfmem frames | Observation items | elfmem down; over budget |
| **C10** | Forecaster | Outcome probability per candidate action; may use Polymarket odds *(D-013)* | Before decide | Timeout → degrade |
| **C23** | Tool Registry | Agent-callable tools: local math (LangGraph), external MCP | Decider invokes | Tool error; slow tool |
| **C11** | Decider | One LLM call → at most one action, with thesis + exits | After C9/C10 | Timeout; malformed output |

### Act

| ID | Component | Responsibility | Trigger | Fails by |
|---|---|---|---|---|
| **C12** | Actor | Submit via Alpaca MCP with `client_order_id` = f(**batch**, D-019) | Action chosen | Rejected; partial multi-leg fill; crash post-submit |
| **C13** | Reconciler | Diff Alpaca holdings vs our records; orphans/phantoms/drift; **runs before C24 (D-019)** so externally-resolved positions are excluded from exit-rule evaluation by construction. No LLM. | Every tick, first in the fast path | Ambiguous mapping |

### Learn

| ID | Component | Responsibility | Trigger | Fails by |
|---|---|---|---|---|
| **C14** | Learner | Fill → position page + elfmem thesis + `mind_predict`. Close → outcome, lesson, `outcome()` credit assignment (**including source credit**) | Fill/close/expiry | Missing provenance; double-scoring |
| **C15** | Calibration Scorer | Brier + Murphy at resolution *(D-013)* | Position resolved | Forecast never recorded |
| **C16** | Housekeeper | Regenerate `portfolio.md`, `index.md`, refresh `wiki/context/`; elfmem `dream()`; digest | Housekeeping item | Long consolidation |

### Remember

| ID | Component | Responsibility | Mutability | Fails by |
|---|---|---|---|---|
| **C17** | Journal | `journal.jsonl` — every event, append-only; rebuild path | Never edited | Write fails mid-batch |
| **C18** | Wiki | `positions/`, **`context/`**, `lessons.md`, `strategy.md`, `portfolio.md`, `index.md`, `AGENTS.md`; OKF frontmatter + monotonic-augmentation write guard *(D-022, D-023)* | Edited by C14/C16 | Frontmatter corruption; growth; a shrinking write silently degrading a note (guarded against by design, not yet implemented) |
| **C19** | elfmem Adapter | `MemorySystem` (library, PyPI `elfmem[tools]>=0.20.0`); frames in, `remember`/`outcome` out | Evolves, can forget | Unavailable; slow; cue omitted |

---

## 5. Data stores and their distinct roles

| Store | Answers | Authority | Tempo |
|---|---|---|---|
| **Alpaca** | "What do I hold?" | Holdings | Real-time |
| **Journal** | "What happened, in order?" | Events | Append-only, forever |
| **Wiki** | "What is the story here?" (positions + market context) | Narrative | Edited over days |
| **elfmem** | "What do I know that's relevant now?" | Generalisation | Evolves hourly |

Bound by `position_id` *(D-014)*, which round-trips through Alpaca inside `client_order_id`.
Full schemas in [spec.md](spec.md) "Data Model".

---

## 6. Interaction flows

### F1 — Tick (split by cost) *(D-017, reordered by D-019)*
```
C1 fires (~60s) → C2 takes lock, tick_count++, starts watchdog
                → C3 spawns only the MCP servers this tick needs

--- EVERY TICK (cheap, no LLM) ---
C6 runs sensors where tick_count % every_n_ticks == 0
   each sensor: fetch → filter/change-detect → emit typed items (with trust tier)
   a failing sensor logs and is skipped; others proceed
C21 computes the analytics pack (marks, greeks, regime)
C13 reconciles Alpaca holdings vs our records                       ← RUNS BEFORE C24 (D-019)
   any position externally resolved (assignment/expiry) flips to terminal HERE
C24 evaluates exit_rules on every position still `open`             ← see F7
   (a position C13 just closed is excluded by construction — not evaluated)
IF today is on/after the competition-deadline date (D-019): force-close every
   remaining open position via C24's close path, close_reason = deadline

--- EVERY N TICKS (~15 min, expensive) ---
C8 drains pending; for each batch, check the journal FIRST (D-019):
   an unresolved decision (no matching execution/rejection) for this batch already exists?
     → resume: re-attempt the SAME submission (idempotent via batch-derived client_order_id)
     → do NOT re-invoke the decider
   else: proceed to decide normally
C22 digests if volume > threshold (else pass through)
C9 assembles context to budget: needs-attention positions first (capped; a systemic
   regime shift is ONE portfolio-level item, not N per-position promotions — D-019),
   then summaries, analytics, primary news, prediction markets, macro digest, social digest
C10 forecasts candidates → C11 decides (≤1 action, may call C23 tools)
   → action: C17 journals the DECISION FIRST (write-ahead), then C12 submits with
     client_order_id derived from the BATCH, then C17 journals execution
   → no-op: C17 logs decision only

C7 archives batch (poison items → failed/ after N retries, cause-differentiated: schema
   failures dead-letter fast, dependency-outage failures retry longer — D-019) → lock released
```

### F2 — Fill arrives (learning is an item type, not a subsystem)
```
C6 observes fill → C8 routes to C14
C14: create wiki/positions/<id>.md (thesis, legs, provenance incl. source refs)
     elfmem remember(thesis, cue=...) + mind_predict(verify_at=expiry)
     C17 logs fill
```

### F3 — Position resolves (close / expiry / assignment)
```
C13 or C6 detects → C14
C14: Outcome section; C15 computes Brier/Murphy
     elfmem mind_outcome(hit/miss) + outcome(recalled_blocks, signal)   ← credit assignment
     source credit: sources cited in the thesis are scored too          ← learns what to trust
     lesson → wiki/lessons.md + elfmem
     C17 logs reflection
```

### F4 — Housekeeping (market closed / daily)
```
C6 emits housekeeping item instead of observations
C8 → C16: regenerate portfolio.md + index.md; refresh wiki/context/{regime,macro,calendar}.md
          from the day's accumulated raw; elfmem dream(); daily digest to wiki/log.md
```

### F5 — Reconciliation (every tick, deterministic)
```
C13 diffs Alpaca holdings vs open position records:
  in Alpaca not ours   → orphan stub page, provenance: unknown
  ours not in Alpaca   → expired/assigned/closed → route to F3
  quantity mismatch    → update actual_legs, flag divergence from intended_legs
```

### F7 — Exit rule triggers *(D-017, debounce revised by D-019)*
```
C24 (every tick, AFTER C13 reconciles — D-019): for each position still `open`,
  compute net mark from C21
  evaluate exit_rules → stop_loss | profit_target | time_stop | deadline
  trigger condition (D-019): breach on N-of-M recent checks (not strictly consecutive —
    a single reassuring-but-stale quote must not reset progress toward a real breach),
    OR immediately if the breach exceeds 2x the rule's threshold (unambiguous, not a
    quote artifact)
  → trigger:
      guard: position status must be `open` (never re-fire on closing/terminal) — satisfied
      by construction since C13 already excluded externally-resolved positions this tick
      set status = closing
      C12 submits a CLOSE for ALL LEGS of the position (never leg-level)
      C17 journals exit with close_reason = stop_triggered | target_hit | time_stop | deadline
      emit an inbox item so the next decide cycle learns the position is gone
  → the fill flows through F3 for scoring, where close_reason steers credit assignment
```
Because C24 (now after C13) runs before the decide path within a tick, a position it has moved
to `closing` is already marked when C9 assembles context — the decider cannot act on a position
being exited. **Implementation requirement:** C9 must read position status fresh each invocation,
never from a tick-start snapshot, or this guarantee silently doesn't hold. Closing/terminal
positions are informational-only in the decide context — never an actionable target.

### F6 — Regime change (internally generated event)
```
C21 computes regime each tick; compares to wiki/context/regime.md
  material change → emit regime_change item (trust: primary)
C8 routes as an observation → decide cycle sees it flagged prominently
C16 updates regime.md at housekeeping
```

---

## 7. State machines

### Position lifecycle
```
             ┌──────────┐
             │ proposed │  decision made, no order yet
             └────┬─────┘
                  ▼
             ┌──────────┐   order submitted
             │ opening  │──────────┐
             └────┬─────┘          │ rejected
                  ▼ filled          ▼
             ┌──────────┐      ┌──────────┐
      ┌─────▶│   open   │      │ abandoned│
      │      └────┬─────┘      └──────────┘
      │           │
 adjusting ◀──────┤
      │           ├──▶ closing ──▶ closed
      │           ├──▶ expired          (options: happens TO us)
      │           └──▶ assigned         (options: happens TO us)
      │
   orphaned  (discovered in Alpaca with no record)
```
Terminal states — `closed`, `expired`, `assigned`, `abandoned` — route to F3 exactly once.

### Inbox item lifecycle
```
written → pending → [processing] → processed/<date>/
                        │
                        └─ crash → stays pending → reprocessed (at-least-once)
```

### Sensor health
```
healthy ──failure──▶ degraded(n) ──n≥N──▶ parked (rest of day, logged)
   ▲                     │
   └─────success─────────┘
```

---

## 8. Invariants (simulation assertions)

| ID | Invariant | Violated when |
|---|---|---|
| **INV-1** | Every submitted order carries `client_order_id` derived from a `position_id` in the journal | Provenance broken |
| **INV-2** | No inbox item is archived before its batch completes | Work silently lost |
| **INV-3** | The journal is append-only | Audit/rebuild corrupted |
| **INV-4** | Every non-orphan open position has a wiki page with a thesis | Cold start can't explain itself |
| **INV-5** | Every `decision` entry records recalled elfmem blocks, wiki refs, **and source item ids** | Credit assignment impossible |
| **INV-6** | Each position's elfmem blocks receive a **full-weight** `outcome()` call **exactly once**, at true resolution — INV-24's low-weight interim calls are explicitly exempt and may repeat *(reworded, D-019)* | Double-counted or missing learning |
| **INV-7** | At most one tick runs at a time | Duplicate orders, interleaved writes |
| **INV-8** | The decide path never blocks on any advisory input — memory, forecast, **or any sensor** | Brain outage halts trading |
| **INV-9** | After reconciliation, our records and Alpaca holdings agree | Phantom/orphan drift |
| **INV-10** | `dream()` never runs inside a tick's decide path | Tick overrun |
| **INV-11** | No duplicate order results from a crash-retry | Doubled exposure |
| **INV-12** | Raw fetched source data is archived regardless of whether it was filtered or digested | Forensics/learning impossible |
| **INV-13** | Every derived item carries the `trust` tier of its source | Social treated as newswire |
| **INV-14** | A digest preserves verbatim any item naming an open position's underlying | Critical item summarised away |
| **INV-15** | Context assembly stays within budget; anything dropped is recorded in the journal | Silent truncation |
| **INV-16** | A single sensor failure never aborts a tick | Fragile to third-party outage |
| **INV-17** | A position enters a terminal state **at most once**, whatever detects it | Double credit assignment *(gap #4)* |
| **INV-18** | `client_order_id` derives from the inbox **batch**, is **enforced on the tool call** (the model authors tool args, so it will otherwise invent its own - D-020), and the decision is journalled **before** submission | Retry opens a second, different position *(gap #3)* |
| **INV-19** | An exit rule closes **all legs** of a position, never a single leg | Naked short with unbounded risk *(D-017)* |
| **INV-20** | An item failing N times moves to `inbox/failed/`; the batch proceeds | One poison item stalls forever *(gap #2)* |
| **INV-21** | Every closed position records a `close_reason` | Entry theses penalised for exit decisions *(gap #9)* |
| **INV-22** | elfmem recalled block ids are captured **per frame** at assembly, never from `last_recall_block_ids` | Self/task frame blocks silently lost *(gap #8)* |
| **INV-23** | `dream()` is called only at housekeeping; tick sessions never auto-consolidate | Tick overrun *(gap #6, INV-10)* |
| **INV-24** | Every open position is scored at least at interim weight each housekeeping | Learning loop never closes in-window *(gap #1)* |
| **INV-25** | C13 (reconcile) runs before C24 (exit rules) in every tick's fast path | C24 acts on stale data across an assignment/expiry boundary *(D-019, gap #15)* |
| **INV-26** | Every open position is force-closed on/after the competition-deadline date, regardless of its own DTE or exit rules | Learning loop never closes in-window even with a correctly-behaving `time_stop` *(D-019)* |
| **INV-27** | Before deciding, the processor checks for an unresolved decision on the current batch and resumes rather than re-decides | Orphaned decision records; wasted LLM calls on every crash-retry *(D-019, gap #17)* |
| **INV-28** | An exit-rule trigger requires N-of-M recent breaches, or one breach exceeding 2x threshold | Debounce delays a genuine breach indefinitely on noisy/stale quotes, or fires on a single bad reading *(D-019)* |
| **INV-29** | The needs-attention context tier is capped; a systemic regime shift is one portfolio-level item, not N per-position promotions | Two-tier context collapses back to full-detail-for-everything under a market-wide event *(D-019, gap #16)* |
| **INV-30** | A dead-lettered item's failure cause (malformed vs. dependency outage) determines retry patience before giving up | A transient outage silently and permanently discards a valid signal *(D-019, gap #20)* |

---

## 9. Timing model

Split by cost *(D-017)*: cheap deterministic work runs often; LLM work runs rarely.

| Event | Cadence | Notes |
|---|---|---|
| Tick | **~60s**, market hours | `flock` skip if overrun; watchdog timeout |
| `alpaca_market`, `internal_analytics` | every tick | Cheap, local / same MCP connection |
| **Exit rule evaluation (C24)** | **every tick** | Deterministic, no LLM — this is why ticks can be fast |
| Reconciliation (C13) | every tick | Deterministic |
| **Decide path (C9→C11)** | **every ~15 ticks (~15 min)** | The only routine LLM cost |
| `alpaca_news` | every ~15 ticks | Aligned to decide cycles |
| `x_social` | every ~30 ticks | Heavy filter; highest noise |
| `google_feed`, `polymarket` | every ~60 ticks | Slow-moving by nature |
| Digest | only above volume threshold | Cheap model; zero cost on quiet days |
| Housekeeping + `dream()` + interim scoring | daily / market closed | Refreshes `wiki/context/`; INV-24 |
| LLM calls per decide cycle | 1 decide (+1 digest when busy) | ~26/day rather than ~78 |

Fast monitoring with slow deciding cuts routine LLM spend roughly threefold versus a uniform
5-minute cadence, while *shortening* the exposure window from ~5 min to ~60s. Journal volume
stays trivial (~hundreds of entries/day); no rotation needed.

---

## 10. Failure modes (simulation scenarios)

| ID | Scenario | Designed response | Residual risk |
|---|---|---|---|
| **FM-1** | Crash between order submit and archive | `client_order_id` dedup; Alpaca rejects duplicate; reconcile | The one window that can double exposure |
| **FM-2** | Partial multi-leg fill → broken spread | `intended_legs` vs `actual_legs` flagged | Nothing prevents it *(D-009)*; risk profile changes silently until next tick |
| **FM-3** | Tick overrun | `flock` → next tick skips | Sparse decisions if chronic |
| **FM-4** | Alpaca MCP fails / dies mid-tick | Items stay pending; retry | Blind window |
| **FM-5** | LLM gateway timeout / rate limit | Items stay pending; retry | Missed opportunity |
| **FM-6** | elfmem slow or unavailable | Decide with reduced context; note degradation | Worse decisions, not stopped ones |
| **FM-7** | Forecast unavailable | Proceed; `forecast: degraded` | No Brier entry |
| **FM-8** | Inbox flood (news burst) | Filter → digest → budget | Relevant item dropped |
| **FM-9** | Orphan position in Alpaca | Stub page, `provenance: unknown` | Agent reasons about a position it can't explain |
| **FM-10** | Phantom position (expired/assigned) | Diff detects, routes to F3 | Up to one tick late |
| **FM-11** | Wiki frontmatter corrupted | Skip page, log, continue | That position loses its narrative |
| **FM-12** | Runaway decision (no guardrails) | None by design; learn path reflects; constitution edited | Paper damage; recoverable via reset |
| **FM-13** | Model swapped mid-competition | Journal records model per decision | Behaviour discontinuity |
| **FM-14** | Paper account reset | Journal + wiki survive; note divergence | Holdings/history mismatch |
| **FM-15** | Market-hours/timezone error | Alpaca clock is sole authority | Trading attempts when closed |
| **FM-16** | A source API is down or rate-limited | Sensor isolated; parked after N failures; tick proceeds | Decisions made blind to that source |
| **FM-17** | Digest drops the one critical item | Verbatim-preservation rule (INV-14); raw archived | Semantic misses still possible |
| **FM-18** | False-but-viral social content drives a bad trade | Trust tiering (INV-13); constitution requires corroboration; learn path penalises the source | Real exposure — no gate stops it |
| **FM-19** | Sensor returns malformed data (API change) | Schema validation; drop, log, park after N | Silent loss of that signal |
| **FM-20** | Context budget exceeded | Priority-ordered degradation, recorded (INV-15) | Useful context dropped |
| **FM-21** | MCP subprocess proliferation / one hangs on spawn | Per-server timeout; spawn only what the tick needs | Tick latency creep |
| **FM-22** | Stale content re-emitted every poll | Per-sensor change detection state | Duplicate reasoning if state lost |
| **FM-23** | Poison-pill item stalls the inbox forever | Retry counter → `inbox/failed/` (INV-20) | That signal is lost |
| **FM-24** | Crash-retry re-decides differently → two *different* positions | Batch-derived `client_order_id` + write-ahead journal (INV-18) | Recovery needs the write-ahead record to exist |
| **FM-25** | Two detectors resolve the same position | Status transition guard (INV-17) | — |
| **FM-26** | Hung LLM call stalls the unattended run | Watchdog timeout; stale lock breakable by PID+timestamp | Tick lost, not the run |
| **FM-27** | Nothing resolves inside the 8-day window | ≤7 DTE strategy constraint; `time_stop` rule; interim scoring (INV-24) | Weaker signal than true resolution |
| **FM-28** | Exit rule fires on a stale or abnormally wide quote | 2-check debounce; quote sanity check | Whipsaw on genuinely volatile marks |
| **FM-29** | Exit rule closes one leg, leaving a naked short | Position-level evaluation and close (INV-19) | — |
| **FM-30** | Exit rule and decide path act on the same position | C24 runs first within a tick and sets `closing`; decider sees it | — |
| **FM-31** | Process down → exit rules unmonitored | Prefer broker-native stops where supported | Multi-leg likely has no native path |
| **FM-32** | C24 evaluates a position the broker already resolved via assignment/expiry this tick | C13 runs first (INV-25); C24's candidate set excludes it by construction | None — closed by reordering, not mitigated |
| **FM-33** | Crash-retry re-decides instead of resuming, orphaning the write-ahead decision record | Resume-from-journal check (INV-27) | Wasted LLM call if the check itself is skipped |
| **FM-34** | Conventional-DTE position never resolves inside the competition window despite a correct `time_stop` | Competition-deadline sweep (INV-26), independent of DTE | None if the sweep date is correct |
| **FM-35** | Debounce reset by one stale/wide quote on a thin ≤7 DTE contract delays a genuine breach | N-of-M debounce + magnitude override (INV-28) | Residual delay up to M-1 checks for near-threshold breaches |
| **FM-36** | Systemic regime shift flags every open position, bloating the needs-attention tier | Tier cap + single portfolio-level regime item (INV-29) | — |
| **FM-37** | Dead-lettered item was a transient-outage casualty, not malformed | Cause-differentiated retry (INV-30); reconciliation independently recovers position-facts regardless | News/social items have no redundant recovery path |

---

## 11. Simulation guide

**Feed the simulator:** this document plus [spec.md](spec.md)'s Data Model.

**Vary**
- Market regime: trending / choppy / high-volatility / gap-open
- **News environment: quiet / normal / FOMC-day flood / false-viral-story**
- Tick cadence: 1, 5, 15, 60 min; and sensor cadences independently
- Concurrent open positions: 0, 1, 5, 20
- Failure injection: each FM-* individually and in pairs
- Duration: one day; full 8-day window
- Model swap mid-run (tests INV-5 attribution)

**Assert:** every INV-* in §8.

**Measure**
- Decisions/day; action vs no-op ratio
- Orders submitted / filled / rejected; **duplicates (target: 0)**
- Positions with complete provenance (target: 100% of non-orphans)
- `outcome()` calls per resolved position (target: exactly 1)
- Brier trend — is calibration improving?
- **Context size distribution; budget-drop frequency and what got dropped**
- **Per-source signal value: do trades citing `social` underperform those citing `primary`?**
- Tick duration; overrun frequency; MCP spawn latency
- Degraded decisions as % of total
- Orphans/phantoms detected and time-to-resolution

**Questions the simulation should answer**
1. Does the learning loop actually close, or do positions resolve without credit assignment?
2. Where does context assembly exceed budget, and is the priority order right?
3. Does FM-1 ever produce a real duplicate under realistic timing?
4. With no guardrails, what does the worst plausible 8-day run look like?
5. Is a 5-minute cadence useful, or mostly no-ops and cost?
6. Does the wiki stay navigable at 8 days of positions, lessons, and context?
7. **Do the extra sources improve decisions, or just add noise and cost?** (Run with sensors
   disabled as the control.)
8. **Does trust tiering actually change behaviour on a false-viral-story scenario (FM-18)?**
9. **What sensor cadences maximise signal per LLM token spent?**

---

## 12. Assumptions still unverified

Carry these into simulation as parameters, not facts.

| Assumption | Status | Impact if wrong |
|---|---|---|
| `client_order_id` fits `trdrbot_<position_id>_<leg>` | **Unverified** *(D-014)* | Fall back to short hash |
| Alpaca surfaces expiry/assignment as distinct events | **Unverified** *(D-014)* | Reconciler sole detector; one tick late |
| **An X/Twitter MCP exists, is reachable, and its rate limits suit a 6-tick cadence** | **Unverified** *(D-015)* | Drop or replace the social sensor |
| **Polymarket exposes queryable market odds (MCP or HTTP) suitable for automated polling** | **Unverified** *(D-015)* | Drop the highest-signal-per-token source |
| **Alpaca's MCP news tool is watchlist-scopeable** | **Unverified** *(D-015)* | Heavier client-side filtering |
| Multi-leg options orders execute atomically enough via MCP | **Unverified** | FM-2 frequency rises |
| **Alpaca supports stop / stop-limit / bracket orders on options** | **Unverified** *(D-017)* | Local evaluator is the only path; no cover while the process is down (FM-31) |
| **Any native stop support extends to multi-leg positions** | **Unverified, doubted** *(D-017)* | Local evaluator required for spreads regardless |
| **Short-dated (≤7 DTE) options on the watchlist are liquid enough to trade and exit** | **Unverified** *(gap #1 fix)* | Wide spreads make stops fire badly; reconsider the DTE constraint |
| **Repeated daily interim scoring on a fluctuating unrealised-P&L signal stabilises rather than destabilises elfmem's confidence posterior** | **Unverified, needs a grounding computation** *(D-019, gap #19)* | May need to widen the interim cadence or shrink interim weight further |
| **elfmem's session-exit does not auto-consolidate inside a tick, and per-frame block ids are actually capturable as designed** | **Unverified against the real library** *(D-018 #6, #8 — not re-traced in the D-019 regression)* | Needs a direct integration check, not further paper simulation |
| elfmem integrates in ≲1 day | Assumed *(D-011)* | Minimal in-repo contract fallback |
| One decide call holds enough context at 20 positions + 4 sources | Assumed | Needs summary tier *(D-014 revisit)* |
| 5-min cadence suits options strategies | Assumed *(notes/001)* | Tune cadence |

---

## 13. Build order

1. **Walking skeleton (d0-1)** — chassis (incl. **watchdog + stale-breakable lock**), inbox schema
   with **dead-letter**, journal with **write-ahead decisions**, wiki scaffold, Alpaca MCP smoke
   test, gateway, `run.sh`. *Milestone: one end-to-end tick places a paper trade from a manually
   injected inbox item.*
2. **Sense + Decide + Exit rules (d2-3)** — sensor registry with `alpaca_market` +
   `internal_analytics`; split tick cadence with **C13 reconcile running before C24 exit-rule
   evaluation (D-019)**; **competition-deadline sweep**; Router with **resume-from-journal check
   before deciding**; analytics pack; decide prompt; Actor with **batch-derived idempotency**;
   status-transition guard. *Milestone: scheduled ticks trade unattended, a breached stop closes
   a position with no LLM involved, and a killed-and-restarted tick resumes rather than
   re-decides.*
3. **Memory (d3-5)** — elfmem adapter (**per-frame block capture**, **no auto-consolidation in
   tick sessions**), wiki read/write incl. `context/`, **two-tier position context**, fill-event
   learning, credit assignment keyed on `close_reason`, **interim scoring at housekeeping**.
   *Milestone: a closed trade produces a reflection, a lesson, and exactly one `outcome()`; an
   open trade still produces a low-weight interim signal.*
4. **Sources + calibration (d5-6)** — add sensors one at a time in signal-per-token order:
   `alpaca_news` → `polymarket` → `google_feed` → `x_social`; digest + trust tiering; Brier
   scoring. *Milestone: a decision cites an external source and is later scored on it.*
5. **Polish (d6-7)** — constitution seeding, prompt iteration against live results, tool registry
   for ad-hoc math.
6. **Submission (d7-8)** — demo, write-up citing journal/wiki evidence, README. Buffer.

Sources land **after** the loop is proven, and one at a time — each is independently droppable if
its API disappoints, and the control run in §11 Q7 tells us whether it earned its place.
