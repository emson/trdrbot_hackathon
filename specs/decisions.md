# Decisions Log

<!-- Append new decisions below. Sequential numbering (next = highest + 1).
     Append-only: supersede entries, never delete or renumber them. -->

## D-001: Claude + Alpaca MCP Server drives trading decisions
**Date:** 2026-08-26
**Status:** accepted
**Superseded by:** D-008 (the "single AI decision-maker over Alpaca MCP" core carries forward;
"Claude" generalizes to "gateway-selected LLM" and the harness changes)
**Context:** The agent needs a decision engine for when/what options trades to place. Three
options considered: pure AI-driven (Claude + MCP), pure rule-based algorithm, or a hybrid
where rules generate signals and Claude approves/sizes them.
**Choice:** Claude, connected to Alpaca's Trading MCP Server, analyses market and options data
directly and decides when and what options strategy to place. This is the primary v1 approach —
it best showcases the "AI trading agent" theme of the hackathon and leverages the MCP Server's
65 tools directly rather than building a parallel rules engine.
**Why not alternatives:**
- Rule-based algorithm: simpler and more deterministic to test, but doesn't demonstrate the
  AI-agent angle the hackathon is themed around, and is a weaker judging story.
- Hybrid (rules + AI overlay): more robust long-term, but adds a second system (the rules
  engine) to build and integrate in a 9-day window — unnecessary complexity for v1.
**Evidence:** none yet — decision made on hackathon fit and time constraint, not a spike.
**Revisit if:** Claude's tool-calling proves unreliable for placing multi-leg options orders
in testing, or the judging story turns out to reward deterministic/backtestable strategies
more than AI-agent autonomy.

## D-002: Runtime is Claude Code, scheduled locally via /loop — not the Agent SDK or a Cloud Routine
**Date:** 2026-08-26
**Status:** accepted
**Superseded by:** D-008
**Context:** Needed to decide how the agent runs and wakes up: a custom Claude Agent SDK
service, Claude Code driven locally (`/loop`/Desktop task, 1-min floor), or Claude Code Cloud
Routines (Anthropic-managed, 1-hour floor, survives the machine being off).
**Choice:** Run as Claude Code, woken on a schedule via `/loop` (or a Desktop scheduled task),
polling during market hours. Headless Claude Code (`claude -p`) is itself the Agent SDK's CLI
entry point, so a separate SDK service would duplicate scheduler/MCP-client/state-store
infrastructure Claude Code already provides — not a good use of a 9-day build window.
**Why not alternatives:**
- Agent SDK (own process): full control, but days of extra plumbing (scheduler, MCP client,
  state store, process supervision) for no capability we actually need in v1.
- Cloud Routines: more reliable unattended (keeps running if the machine sleeps), but has a
  1-hour polling floor and no local file/repo access between runs (fresh clone each run) —
  worse fit for active dev/iteration this week. Chosen against for now in favour of faster
  local iteration; see Revisit below.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md)
**Revisit if:** the live trading window needs to run unattended overnight or across days without
the team's machine staying on — switch the live-run leg to a Cloud Routine at that point
(hourly cadence is adequate for options strategies; see [notes/001](notes/001_architecture_assumptions.md)
§2). Also revisit if `/loop`'s 1-minute floor turns out to be too fast/expensive in practice.

**Correction (2026-08-26, post-verification):** `/loop` sessions expire 7 days after creation
(resumable within that window via `--resume`, but not beyond it). The competition window
(Aug 28 – Sep 4) is 8 days, longer than `/loop` alone can cover unattended. **Use a Desktop
scheduled task, not raw `/loop`, for the live multi-day run** — `/loop` remains fine for local
dev/testing this week. If using Desktop scheduled tasks turns out to have its own limits,
fall back to manually resuming `/loop` before the 7-day mark, or move to a Cloud Routine.

## D-003: Trading is triggered by scheduled polling only — no event-driven/webhook triggers
**Date:** 2026-08-26
**Status:** accepted
**Context:** Alpaca has no outbound webhooks, and the official Trading MCP Server exposes no
streaming/websocket tools — confirmed directly from its GitHub README. Genuine push events
(order fills, price ticks) exist only via a separate WebSocket client outside the MCP Server.
**Choice:** The agent wakes on a schedule (per D-002) and polls Alpaca via MCP for state each
cycle; no separate WebSocket listener in v1.
**Why not alternatives:**
- WebSocket streaming: would mean a second integration surface alongside the MCP Server,
  disproportionate effort for a build where options strategies don't need sub-minute reaction.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md) §2
**Revisit if:** latency between a market move and the agent noticing it becomes a demonstrated
problem, or a future strategy needs sub-minute reaction.

## D-004: One deterministic guardrail module gates both trade execution and self-improvement
**Date:** 2026-08-26
**Status:** accepted
**Superseded by:** D-009 (guardrails removed entirely)
**Context:** Every source researched independently warned that risk limits must be enforced in
code, not left to LLM judgment — both for validating a proposed trade before it reaches the
broker, and for bounding what the self-improvement loop is allowed to change.
**Choice:** A single deterministic guardrail module — implemented as a `PreToolUse` hook on the
Alpaca order-submission MCP tool — enforces: max position size (% of equity), max concurrent
open positions, max daily loss / circuit breaker, market-hours check. The same module's limits
bound the self-improvement loop (D-006): guidance updates may only tighten or add within these
limits, never loosen them, and the LLM never has authority to bypass the check.
**Why not alternatives:**
- Prompt-only constraints (asking Claude to "stay within risk limits"): explicitly warned
  against — prompt instructions get overridden by hallucination or framing under real market
  conditions.
- A second LLM call acting as "risk manager" (as in multi-agent frameworks like TradingAgents):
  better Sharpe in research, but conflicts with D-001 (single decision-making component) and
  is unnecessary weight for a 9-day build when a deterministic check is cheaper and testable.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md) §2-4
**Revisit if:** guardrail logic grows complex enough that it needs its own spec module separate
from "hook implementation detail."

## D-005: Decision loop is a fixed 6-step sequence per wake cycle
**Date:** 2026-08-26
**Status:** accepted
**Superseded by:** D-010 (the 6 steps survive inside the processor's decide path, minus the
guardrail step; the single fused loop is replaced by the inbox pipeline)
**Context:** Needed a concrete shape for "gather environment + commitments → decide best next
action," specific enough to become spec content.
**Choice:** Each wake cycle: (1) gather state via MCP — account, positions, orders, options
chain/Greeks, quote; (2) assess existing commitments against their logged thesis/stop-loss/
target/expiration; (3) decide exactly one action (open/adjust-close/no-action), stating
underlying, strategy, entry price, stop-loss, profit target, position size, thesis + exit
condition; (4) validate against the guardrail module (D-004); (5) execute via MCP; (6) log a
structured record. "Maximize profit" is scoped as "maximize profit subject to the guardrails
in step 4," not a bare objective.
**Why not alternatives:**
- Multi-agent (separate analyst/trader/risk-manager LLM roles, per TradingAgents): shown to
  improve Sharpe in research, but conflicts with D-001 and is heavier than 9 days supports.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md) §3, Alpaca's own reference
MCP trading workflow (analyze → order → log) uses the same shape.
**Revisit if:** a single-agent loop proves unable to hold enough context to reason well about
multiple concurrent positions — consider splitting "assess commitments" into its own pass.

## D-006: Self-improvement loop is a trade journal + guidance doc, reviewed every 3-5 trades
**Date:** 2026-08-26
**Status:** accepted
**Superseded by:** D-011 (journal survives; guidance.md is absorbed into elfmem's constitution;
the fixed review cadence is replaced by event-driven learning on fill/outcome items)
**Context:** Needed a concrete, buildable design for the requested "self-improving loop" that
fits a 9-day window without risking overfitting to a tiny sample.
**Choice:** An append-only trade journal (timestamp, state snapshot, action, thesis, later
backfilled with outcome) plus a short "current guidance" doc read by every decision cycle. A
separate review pass triggers every 3-5 closed trades or once daily (whichever first), proposes
at most 1-2 additions/edits to guidance (capped magnitude, never a full rewrite), and is blocked
below a minimum sample size (≥3 trades). Guidance updates can only tighten or add within the
guardrail module's limits (D-004), never loosen them.
**Why not alternatives:**
- Vector/semantic memory: FinMem/FinAgent research shows layered, recency-weighted memory
  outperforms pure vector search for this use case, and plain structured files get most of the
  benefit for a fraction of the engineering.
- Backtesting-in-the-loop: real overfitting risk (LLM training-data overlap with historical
  prices can make backtests look good via memorization, not skill) — deferred to roadmap.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md) §4
**Revisit if:** the journal shows the same mistake recurring despite guidance updates (may need
a stronger review mechanism), or trade volume is too low in 9 days for 3-5-trade batches to
ever trigger a review (fall back to daily review regardless of count).

## D-007: Accept the risk that Claude autonomously deciding trades may conflict with Anthropic's Consumer Terms
**Date:** 2026-08-26
**Status:** accepted
**Context:** Anthropic's Consumer Terms (§3, prohibited use #9) state users may not "rely upon
the Services... to buy or sell securities or to provide or receive advice about securities,
commodities, derivatives, or other financial products or services, as Anthropic is not a
broker-dealer or registered investment adviser." Verified verbatim against
anthropic.com/legal/consumer-terms directly (not just cited secondhand). Options are explicitly
named as derivatives — this is squarely in scope. It applies to Claude.ai, Pro/Max
subscriptions, and *individual* Anthropic API key users — i.e. it covers Claude Code under a
personal plan and an Agent SDK build under a personal API key equally; switching runtime does
not avoid it. Commercial Terms are silent on this specific clause but only apply to an actual
business agreement with Anthropic, not available in a 9-day hackathon window. No Anthropic
statement was found reconciling this with Alpaca's own MCP tooling explicitly built and
promoted for AI-agent trading, and this is not an Anthropic-run hackathon (Alpaca + lablab.ai).
The language does not distinguish paper trading from live trading.
**Choice:** Proceed with the fully autonomous design (D-001, D-005) — Claude decides and the
guardrail module (D-004) executes with no mandatory human confirmation step. This is a
knowing, accepted risk for a paper-trading hackathon context, not a resolved compliance
position.
**Why not alternatives:**
- Human-approval step before execution (Claude proposes, a person confirms): would weaken the
  "reliance" reading and matches a pattern another team in this hackathon category already
  ships (Discord approval), and lablab.ai's judging criteria reward approval checkpoints. Not
  chosen — team prioritized full autonomy as the stronger demo of the "AI trading agent" theme.
- Asking lablab.ai/Alpaca for explicit clarification first: not chosen — team chose to proceed
  rather than pause on this.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md), verified quote from
anthropic.com/legal/consumer-terms (§3, item 9) and anthropic.com/legal/commercial-terms.
**Revisit if:** Anthropic or the hackathon organizers publish explicit guidance either
permitting or prohibiting this use case; or before any move beyond paper trading toward real
funds, at which point this decision must be re-made, not carried forward.

**Note (2026-08-26):** D-008 replaces the runtime and routes LLM calls through a gateway, so
the executing model may not be Claude. When a non-Anthropic model makes the trade decision,
Anthropic's Consumer Terms no longer govern that call path — the chosen provider's terms apply
instead. The risk-acceptance stance is unchanged.

## D-008: Runtime is a headless LangGraph service with an LLM gateway
**Date:** 2026-08-26
**Status:** accepted
**Supersedes:** D-001, D-002
**Context:** User directive following the harness research in [notes/002](notes/002_harness_comparison.md):
model-swapping via a gateway is load-bearing, and removing guardrails (D-009) removes Claude
Code's one structural advantage for this project (the PreToolUse hook).
**Choice:** A headless Python service built on LangGraph. LLM calls go through a gateway layer
(config-selected model — e.g. `init_chat_model`/LiteLLM) so models swap by config, not code.
Alpaca is reached via MCP from inside the graph (D-003's polling stance carries forward
unchanged). Scheduled via launchd/cron on the team machine; Claude Code remains the development
tool, not the runtime. The journal records the model id used for every decision so results are
attributable across model swaps.
**Why not alternatives:**
- Stay on Claude Code: no model-swap, 7-day session caps, and with D-009 no hook advantage left.
- Bare Python, no framework: LangGraph provides the graph structure, MCP adapters, and
  checkpointing for free; hand-rolling those costs days we don't have.
**Evidence:** [notes/002](notes/002_harness_comparison.md), [notes/004](notes/004_system_architecture_research.md)
**Revisit if:** the LangGraph→MCP→Alpaca path fails verification (fallback: direct `alpaca-py`
calls wrapped as LangGraph tools — still gateway-swappable, loses MCP tool discovery).

## D-009: No guardrails
**Date:** 2026-08-26
**Status:** accepted
**Supersedes:** D-004
**Context:** User directive: hackathon speed on a paper-only account; a gating layer would slow
iteration and add debugging surface during a 9-day build.
**Choice:** No risk-policy layer anywhere — the decider's order tool calls execute directly
against the paper account. What remains is correctness plumbing, not policy: idempotent orders
via `client_order_id`, at-least-once inbox semantics, append-only journal. These prevent bug
classes (duplicate orders on crash-retry), they never block a deliberate decision. Soft
self-governance lives, if anywhere, in elfmem's constitution (D-011) — principles the model
reads, not gates that block it.
**Why not alternatives:**
- Keep D-004's guardrail module: gating + debugging friction in exchange for protecting
  simulated money — wrong trade in this window.
**Revisit if:** any move beyond paper trading (mandatory re-decision before real funds), or
repeated pathological behaviour wastes the competition window — first-line remedy is a paper
account reset plus a constitution edit, not a gate.

## D-010: Event-driven inbox pipeline
**Date:** 2026-08-26
**Status:** accepted
**Supersedes:** D-005
**Context:** User architecture direction — decouple sensing from deciding via an inbox.
**Choice:** A Collector (deterministic Python, no LLM, scheduled) polls Alpaca via MCP and
writes typed observation items — account, positions, open orders, option-chain snapshots,
fills, news, housekeeping — to a file-based inbox (one JSON file per item,
`inbox/pending/` → `inbox/processed/` on success). The Processor — one LangGraph graph —
drains all pending items each tick and routes by type: observations → decide path (context
from D-011 memory + D-012 forecasts, LLM decision, MCP execution); fills/outcomes → learn
path; housekeeping → consolidation. v1 trigger is sequential (one scheduler tick runs collect
then process); the inbox remains a real interface so items can be injected by hand for testing
or by future feeds without touching the pipeline.
**Why not alternatives:**
- Single fused loop: loses the inbox's testability (inject a synthetic item, run the processor
  once, watch the whole pipeline) and the user's explicit decoupling direction.
- Message broker (Redis/RabbitMQ): needless on one machine; files are inspectable and durable.
**Evidence:** [notes/004](notes/004_system_architecture_research.md)
**Revisit if:** multiple machines or concurrent producers ever write to the inbox — then a
real queue earns its place.

## D-011: Memory is elfmem (short-term evolving) + LLM wiki (long-term) + JSONL journal
**Date:** 2026-08-26
**Status:** accepted
**Supersedes:** D-006
**Context:** User directive to reuse their elfmem project
(`~/Dropbox/devel/projects/ai/elf0_mem_sim`, branch `self-frame-contract`) together with the
Karpathy-style LLM wiki pattern from [notes/003](003_competitive_landscape_and_knowledge_store.md).
**Choice:** Three stores with distinct roles. **elfmem** holds the evolving working memory —
goals, constitution (trading principles), learned patterns — and drives recall at the start of
every decide cycle. The **LLM wiki** (markdown, `AGENTS.md`-schema'd: `index.md`, `log.md`,
`strategy.md`, `lessons.md`, `positions/<id>.md`) holds durable long-term knowledge. The
**journal** (`journal.jsonl`) is the append-only ground-truth record of decisions, executions,
fills, and reflections, including the model id per decision. Consolidation flows
journal → elfmem patterns → wiki lessons. The inbox's `processed/` archive doubles as the wiki
pattern's immutable raw layer — no separate `raw/` directory in v1.
**Why not alternatives:**
- Flat journal + guidance.md (the D-006 design): no pattern learning, no entity pages, no
  reusable memory machinery.
- Vector/semantic store: [notes/001](notes/001_architecture_assumptions.md) §4 — layered,
  recency-weighted memory beats vector search for this use case, at far less engineering cost.
**Evidence:** [notes/001](notes/001_architecture_assumptions.md) §4,
[notes/003](003_competitive_landscape_and_knowledge_store.md),
[notes/004](notes/004_system_architecture_research.md) (elfmem integration-surface findings)
**Revisit if:** integrating elfmem as-is exceeds ~1 day of work — fallback is implementing its
contract minimally inside trdrbot (constitution + patterns as elfmem-compatible markdown),
keeping the interface so the real elfmem can slot in later.

**Note (2026-08-26, post-exploration — [notes/004](notes/004_system_architecture_research.md) §10.1):**
elfmem verified real and integrable (1500 tests passing; import as library; pin to the
`self-frame-contract` branch, not PyPI). Its frame system maps directly: `self` frame =
constitution, `task` = goals, `attention` = per-decision recall; trade outcomes wire into
`outcome()` via `last_recall_block_ids`. Two corrections to this decision's assumptions:
(1) elfmem has **no LLM-wiki lookup** — the Karpathy wiki is trdrbot's own module, read by the
decide path alongside elfmem's frames; (2) elfmem is a **callee, not a caller** — all tool use
(MCP/CLI) belongs to the processor graph. The revisit trigger did not fire.

## D-012: elfsim provides forecasting in the decide path, degrade-gracefully
**Date:** 2026-08-26
**Status:** accepted
**Superseded by:** D-013 (revisit trigger fired same day: exploration found elfsim is
spec-only with zero implementation)
**Context:** User directive to use their elfsim project (`~/Dropbox/devel/projects/ai/elfsim`)
to help forecast outcomes and improve decisions.
**Choice:** Before deciding, the processor may call elfsim to project outcomes of candidate
actions; forecasts are advisory context for the LLM, referenced in the journal entry for the
decision. elfsim runs behind a timeout; if unavailable or slow, the decide path proceeds
without forecasts and the journal notes the degradation. Forecasting is a pluggable pillar,
not a dependency the pipeline can be blocked by.
**Why not alternatives:**
- Hard-requiring forecasts: couples every trade to a second system's uptime in an 8-day
  unattended window.
**Evidence:** [notes/004](notes/004_system_architecture_research.md) (elfsim capability
findings)
**Revisit if:** exploration shows elfsim unsuited to market-outcome projection within the
hackathon window — fallback: v1 ships without forecasting, the graph node stays as a stub.

## D-013: Forecasting is an in-repo calibration module implementing elfsim's spec slice
**Date:** 2026-08-26
**Status:** accepted
**Supersedes:** D-012
**Context:** Exploration ([notes/004](notes/004_system_architecture_research.md) §10.2) found
the elfsim repo is a specification only — nine design documents, zero implementation, no git
commits, nothing importable. There is no artifact to integrate, pin, or trust.
**Choice:** Implement elfsim's genuinely concrete and differentiated slice directly inside
trdrbot as a small calibration module: the decide path records an outcome-probability forecast
with every trade decision; the learn path resolves forecasts when positions close and scores
them with Brier Index + Murphy decomposition (reliability/resolution/uncertainty); calibration
summaries ("you are overconfident on short-dated spreads") feed back into elfmem/wiki as
lessons. Outcome probabilities come from real options data already collected (Greeks, IV, chain
snapshots), not a generic Monte Carlo DSL. The forecast node keeps the same graph interface so
a future implemented elfsim can slot in unchanged. This still honors the intent — elfsim's
spec is the team's own design; trdrbot becomes its first partial implementation.
**Why not alternatives:**
- Integrate elfsim as planned (D-012): impossible — no code exists.
- Build elfsim first, then integrate: its own roadmap estimates 2-3 weeks for Phase 1 alone;
  the hackathon window is 9 days total.
- Ship no forecasting: loses the calibration story, which is cheap to build and differentiated
  (most trading systems track P&L but not forecast calibration).
**Evidence:** [notes/004](notes/004_system_architecture_research.md) §10.2
**Revisit if:** elfsim Phase 1 gets built after the hackathon — swap the in-repo module for
the real engine behind the same interface.

**Note (2026-08-26, calibration):** elfmem exploration ([notes/004](notes/004_system_architecture_research.md)
§10.1) found elfmem ships a working `mind` prediction/outcome cycle — `mind_predict` with a
required falsifiable `verify_at` date, `mind_outcome` resolving hit/miss into a Beta posterior,
calibration dashboard included. The calibration module builds on this instead of from scratch:
thesis → `mind_predict(verify_at=expiry)`; at close, trdrbot computes Brier/Murphy (elfmem
documents but does not compute Brier) and feeds `outcome()`. Materially less to build.

## D-014: A single position_id threads provenance across all four stores
**Date:** 2026-08-26
**Status:** accepted
**Context:** Positions and the decisions behind them must be recorded so that a cold-started
agent (every tick is a cold start) can reconstruct why it holds what it holds, and so decisions
can cite the wiki knowledge and elfmem memory that informed them. Two structural problems:
Alpaca stores no "why" at all, and it has no multi-leg position concept — one strategic
options position appears as N independent per-leg rows with nothing linking them.
**Choice:** One identifier, `position_id` (`pos_<date>_<underlying>_<strategy>_<hash>`),
threaded through the journal, the wiki position page, elfmem blocks, and Alpaca itself via
`client_order_id`. Each store keeps a distinct role: journal = append-only ground truth and
rebuild path; `wiki/positions/<id>.md` = the curated narrative the LLM reads at decide time;
elfmem = generalised patterns and live predictions, explicitly *not* a position store.
Every decision record captures the elfmem block ids recalled and the wiki pages read (with
content hashes, since the learn path rewrites the wiki). A deterministic per-tick reconciliation
diffs Alpaca holdings against position records, handling orphans, expiry/assignment, and
partial fills. Full schemas in [spec.md](spec.md) "Data Model".
**Why this shape:**
- The recalled-block ids are what `outcome()` reinforces or penalises at close (D-011), so
  provenance is the credit-assignment mechanism, not just an audit trail. Without it elfmem
  accumulates rather than learns.
- Content-hashing wiki refs costs ~2 lines and keeps post-hoc review honest against a wiki
  that the agent itself edits; git provides the retrieval path.
- `intended_legs` vs `actual_legs` makes a broken spread from a partial multi-leg fill visible
  — relevant precisely because D-009 removed anything that would prevent one.
**Why not alternatives:**
- Store positions in elfmem: they would be subject to decay/forget, and elfmem is retrieval-
  optimised for generalisation, not exact state.
- Journal only, no wiki pages: forces the decide path to replay event history every cold start
  instead of reading one curated page per position.
- Rely on Alpaca as the position record: no "why", no multi-leg grouping, no thesis.
**Revisit if:** open positions grow past a few dozen (reading a page per position stops being
trivial — add an index or summary tier).
**To verify during the walking skeleton:** Alpaca's `client_order_id` length limit (the
`trdrbot_<position_id>_<leg>` scheme must fit — fall back to a short hash if not), and how
Alpaca surfaces expiry/assignment events (distinct event vs. position simply disappearing).

## D-015: External information sources are declarative sensors with per-source cadence, policy and trust
**Date:** 2026-08-26
**Status:** accepted
**Context:** We want news and knowledge feeding decisions — Alpaca news, X/Twitter via MCP,
Google feeds, and Polymarket odds — without coupling tick latency to third-party APIs, drowning
the decide prompt in noise, or hard-wiring each source into pipeline code.
**Choice:** A **sensor registry** inside the Collector. Each source is a config entry with four
properties: `every_n_ticks` (cadence as counter-modulo, so we spawn only the MCP servers a tick
needs), `policy` (`raw` | `filter` | `change_only`), `trust` (`primary` | `secondary` |
`social`), and a small change-detection state file. Sensors may be external (Alpaca, X, Google,
Polymarket) or **internal** — `internal_analytics` emits a `regime_change` item from our own
computation, so regime shifts arrive as events rather than as a number buried in a prompt.
Volume is handled in three escalating defences: deterministic filter (always, free, in-sensor)
→ LLM digest (only above a volume threshold, must preserve open-position mentions verbatim)
→ priority-ordered context budget at assembly. Raw fetched data is always archived to
`inbox/processed/` regardless of filtering, so nothing is lost for later forensics or learning.
Durable market understanding accumulates in a new small wiki area, `wiki/context/`
(`regime.md`, `macro.md`, `calendar.md`), read by every decide cycle and refreshed at
housekeeping. Sources cited in a thesis are scored at position resolution alongside elfmem
blocks, so the system learns which sources to trust.
**Why this shape:**
- Sources have radically different natural cadences and signal densities (Polymarket odds move
  over hours; X produces hundreds of low-signal items per minute). One uniform poll is wrong
  in both directions — wasteful for slow sources, overwhelming for fast ones.
- Prediction markets are pre-digested crowd wisdom: tiny, numeric, high signal-to-noise, and
  a free forecast input for D-013's calibration module. Worth passing through nearly raw.
- Trust tiering is the mitigation for false-but-viral social content (FM-18) that fits D-009's
  philosophy — the remedy is memory and constitution, not a gate.
- Adding a source is a registry entry, not new pipeline code: this is the "modular tooling"
  requirement satisfied without new components.
**Why not alternatives:**
- Poll every source every tick: rate limits, cost, tick latency coupled to the slowest API,
  and an inbox flooded with mostly-irrelevant items.
- Pure on-demand agent-initiated search: no persistent record of what the world looked like, so
  "did sentiment precede this move" is unlearnable; re-fetches the same material every cycle;
  costs extra LLM round trips.
- Digest everything always: pays LLM cost on quiet days for no benefit.
- Deterministic filtering only: simulated against an FOMC-day flood, filtering alone still left
  ~80 items — insufficient on exactly the days that matter most.
**Evidence:** [architecture.md](architecture.md) §3, §10 (FM-16..FM-22), §11
**Revisit if:** the §11 Q7 control run (sensors disabled) shows the extra sources do not improve
decisions — drop the ones that do not earn their token cost.
**To verify before building:** that an X/Twitter MCP exists and is reachable with rate limits
suiting a ~6-tick cadence; that Polymarket exposes queryable odds suitable for automated
polling; and whether Alpaca's MCP news tool is watchlist-scopeable.

## D-016: Local computation is LangGraph tools plus an always-injected analytics pack — not an MCP server
**Date:** 2026-08-26
**Status:** accepted
**Context:** We want regime checks, trading analysis, and heavier mathematics available to the
agent, and need to decide whether these are agent-invoked tools, pre-computed context, or an
MCP service.
**Choice:** Both forms, split by purpose. (1) An **Analytics Pack** — deterministic Python
(numpy/scipy) computed before every decide call and always injected: regime, per-symbol
indicators (ATR, IV rank), per-position greeks and days-to-expiry, and **portfolio aggregate
greeks** (net delta/theta/vega, buying power used). (2) A **Tool Registry** of agent-invocable
LangGraph tools for ad-hoc questions: option pricing, IV surface, scenario math. Local
mathematics is exposed as plain LangGraph tools, **not** wrapped in an MCP server — MCP is
reserved for external/third-party/separately-hosted capabilities.
**Why this shape:**
- Mirrors how a trader actually works: a dashboard always in view, plus the ability to run a
  specific calculation when a question arises. Pre-computing alone is inflexible; tools alone
  risk the agent never thinking to call them.
- Portfolio aggregate exposure matters *especially* because D-009 removed everything that would
  constrain it — the agent cannot reason about risk it cannot see. This is information, not a
  gate; it never blocks a decision.
- A protocol boundary around code we own, running in our own process, adds latency and failure
  modes for nothing. Heavy computation needing isolation can move to a subprocess later without
  changing the registry's shape.
**Why not alternatives:**
- Everything as MCP tools: unnecessary IPC and subprocess management for local numpy.
- Pre-computed pack only: cannot answer questions the fixed set didn't anticipate.
- Agent-invoked only: unpredictable latency, extra LLM round trips, and standard context
  (greeks, exposure) might simply never get fetched.
**Evidence:** [architecture.md](architecture.md) §3.3, §4 (C21, C23)
**Revisit if:** analytics runtime starts pushing tick duration toward the cadence — move the
heavy parts to a subprocess or cache across ticks.

## D-017: Agent-authored exit rules, evaluated deterministically every tick
**Date:** 2026-08-26
**Status:** accepted
**Context:** The decide path runs on a slow cadence, so a position can breach its stop and stay
breached for a full cycle with nothing watching — dangerous for options near expiry. Simulation
([notes/006](notes/006_simulation_stress_run.md)) also found exits happening at inconsistent
points pollute the learning signal, and that a 5-minute LLM cadence is mostly wasted no-ops.
**Choice:** Every position carries machine-readable `exit_rules` in its page frontmatter,
**authored by the agent at entry** (D-005 already requires it to state a stop-loss and profit
target). A deterministic evaluator (no LLM) checks them on **every** tick and closes the position
when one triggers. The tick model splits by cost: cheap paths (collect, analytics, exit rules)
run every tick at ~60s; the expensive decide path runs every N ticks at ~15 min — reusing the
`every_n_ticks` machinery from D-015 rather than adding a scheduler.

Rule types are a small closed set, not a DSL: `stop_loss` (mark ≤ X or % loss), `profit_target`
(mark ≥ Y or % of max profit), `time_stop` (close N days before expiry). Rules evaluate on the
**position's net mark and close all legs together — never leg-level**, since stopping one leg of
a spread can leave an unbounded naked short.

Prefer broker-native stops (bracket/OCO) where Alpaca supports them for the instrument, because
they survive our process being down; fall back to the local evaluator otherwise. Multi-leg
almost certainly needs the local path.
**This does not reintroduce guardrails (D-009).** A guardrail is external policy that *blocks*
an agent's intended action before it happens. An exit rule is the agent's *own* stated intent,
executed reliably after the position exists. The agent authors every rule and may rewrite or
delete any of them on any decide cycle, so its authority is undiminished — this is a commitment
device it controls, not a constraint imposed on it.
**Why this shape:**
- Closes a real exposure window with no LLM cost.
- Makes `close_reason` mechanically reliable, which is precisely what gap #9's fix needs — the
  system learns whether a thesis resolved or was stopped, instead of inferring it.
- Cheap monitoring + slow deciding resolves gap #13's cadence waste as a side effect.
- Reuses existing cadence machinery: no new scheduling concept.
**Why not alternatives:**
- Status quo (agent checks stops at decide time): leaves the blind window and noisy exit data.
- Broker-native only: likely unsupported for multi-leg options; leg-level stops are dangerous.
- A general rule DSL: unnecessary expressiveness and a parser to debug in a 9-day build.
**Evidence:** [notes/006](notes/006_simulation_stress_run.md) gaps #5, #9, #13;
[architecture.md](architecture.md) §3.5, F7.
**Revisit if:** stops churn on noise (widen debounce or move to close-only evaluation), or if
Alpaca turns out to support native multi-leg stops (prefer them).
**To verify:** whether Alpaca supports stop / stop-limit / bracket orders on **options**, and
whether any of that extends to multi-leg positions.

## D-018: Simulation-driven hardening folded into the design
**Date:** 2026-08-26
**Status:** accepted
**Context:** The stress simulation ([notes/006](notes/006_simulation_stress_run.md)) traced six
scenarios step-wise and found 14 gaps, three of which individually defeat a core promise of the
design while the system continues to look healthy.
**Choice:** Adopt these fixes before writing code (gaps #1-#8), and carry #9-#12 into the module
specs:
1. **Resolution inside the window (#1, CRITICAL)** — constrain strategy to ≤7 DTE; add a
   `time_stop` exit rule (D-017); score **interim** unrealised outcomes at housekeeping with low
   `weight`, reserving full weight for true resolution. Without this the learning loop never
   completes a single cycle during the competition.
2. **Dead-letter inbox (#2, CRITICAL)** — per-item retry counter; after N attempts move to
   `inbox/failed/` and continue, so one malformed item cannot stall the pipeline forever.
3. **Batch-derived idempotency + write-ahead journal (#3, CRITICAL)** — `client_order_id` derives
   from the inbox batch, not the decision (safe because one action per cycle), and the decision
   is journalled *before* submission. LLM nondeterminism means a re-decided retry would otherwise
   produce a different key and thus two *different* positions.
4. **Exactly-once resolution guard (#4)** — the position status transition is the guard; a
   position may enter a terminal state only once, so reconciler and collector cannot both score it.
5. **Tick watchdog + stale lock (#5)** — hard tick timeout; lock carries PID and timestamp so a
   crashed run does not silently skip every subsequent tick for the rest of the competition.
6. **No elfmem auto-consolidation in tick sessions (#6)** — suppress it; call `dream()` explicitly
   at housekeeping only (INV-10).
7. **Two-tier position context (#7, #10)** — one-line summaries for all positions, full detail
   only for a "needs attention" tier (exit-rule proximity, leg divergence, near expiry, regime
   flag), promoted above news. Fixes both static-priority inversion on event days and the
   unescalated broken-spread flag.
8. **Per-frame elfmem block capture (#8)** — capture recalled block ids per frame at assembly;
   never rely on `last_recall_block_ids`, which only reflects the most recent call (INV-5).
**Evidence:** [notes/006](notes/006_simulation_stress_run.md)
**Revisit if:** a later simulation run shows a fix has introduced a worse failure than the one it
removed.

**Note (2026-08-26, regression — [notes/007](notes/007_simulation_regression_run.md)):** the
revisit trigger fired. Items #1, #3, and #7 above are each real but incomplete — #1's `time_stop`
bounds a position to its own expiry, not the competition deadline; #3's batch-derived id closes
the real exposure risk but nothing resumes from the write-ahead record on retry; #7's tier can
be defeated by a systemic regime shift touching every position at once. Completed by D-019, which
also fixes a new HIGH-severity ordering bug the regression found in item #4/#6's interaction with
D-017's C24. Items #2, #5, #8 held up under adversarial re-testing and needed nothing further.

## D-019: Regression-driven hardening, round two
**Date:** 2026-08-26
**Status:** accepted
**Context:** A regression simulation ([notes/007](notes/007_simulation_regression_run.md))
re-traced D-018's six fixed scenarios against the hardened design instead of assuming they held,
and adversarially attacked the components D-017/D-018 introduced (the exit-rule evaluator, the
split tick model, the write-ahead journal, dead-lettering, interim scoring). None of the three
former CRITICAL fixes fully held; one new HIGH bug was found in a component added since the last
pass without re-checking existing ordering.
**Choice:**
1. **Reorder the fast tick path to C21 → C13 → C24** (analytics → *reconcile* → exit rules), not
   C21 → C24 → C13 as D-017 originally specified. Reconciliation must run before the exit-rule
   evaluator so a position already resolved externally (assignment, expiry) is excluded from
   exit-rule evaluation *by construction* — C24 only considers positions still `open`. Discovered
   by tracing C24 evaluating a position at the exact tick an assignment posted at the broker,
   acting on data reconciliation would have corrected one step later. This single reorder also
   closes the "exit-rule-vs-assignment race" adversarial scenario for free.
2. **Add a competition-deadline sweep**, independent of any position's own DTE — a fixed
   calendar date at which every open position is force-closed. This is what actually bounds
   resolution inside the 8-day window; D-018's `time_stop` bounds a position only to *its own*
   expiry, which for a conventional 30-45 DTE spread falls weeks after the competition ends, and
   nothing enforces the "≤7 DTE" guidance that fix depended on (per D-009, nothing can). Not a
   guardrail — it blocks no trade, only enforces a known scheduling fact, the same category as
   the market-hours check.
3. **Add a resume-from-journal check before re-deciding a batch.** Write-ahead journalling
   (D-018 #3) only delivers its promise if the recovery path reads it: on drain, check whether
   this batch already has a decision entry with no matching terminal entry, and if so resume
   (re-attempt the same submission — safe, since batch-derived `client_order_id` makes it
   idempotent) rather than re-invoking the LLM. Without this, a crash between write-ahead and
   submit produces an orphaned decision record and a wasted LLM call on every retry, rather than
   the clean recovery D-018 intended. Also downgrades D-018 #3's severity: the batch-derived id
   already structurally prevents *real* duplicate exposure regardless of this fix — what was
   missing was bookkeeping cleanliness, not financial-integrity risk.
4. **Reword INV-6** to scope "exactly once" to the full-weight terminal `outcome()` call,
   explicitly exempting D-018's low-weight interim calls (INV-24). As written the two invariants
   contradicted each other.
5. **Cap the needs-attention context tier and represent a systemic regime shift as one
   portfolio-level context item**, not N per-position promotions. A market-wide regime change —
   exactly what an FOMC day produces — can flag every open position at once under D-018 #7's
   original criteria, collapsing the two-tier split back into full detail for everything on
   precisely the day it exists to prevent that.
6. **Distinguish dead-letter causes**: a schema-validation failure dead-letters quickly; an
   MCP/dependency-outage failure retries longer with backoff before giving up. Reconciliation
   already provides a redundant recovery path for position-affecting items (fills, assignments)
   regardless, but news/social items have no such redundancy and are genuinely, permanently lost
   if dead-lettered during a transient outage.
7. **Debounce exit rules on N-of-M breaches (not strictly consecutive), plus a magnitude
   override**: a breach more than 2× the rule's threshold triggers immediately regardless of
   debounce history, since that magnitude isn't plausibly a stale-quote artifact. Strictly
   consecutive debounce resets on any single reassuring-but-wrong reading, which a stale or wide
   quote on a thin ≤7 DTE contract can produce, delaying a genuine breach past what's safe.
**Why not alternatives:**
- Leave D-018's fixes as specified and treat the regression findings as future-work: rejected —
  #1 (deadline sweep) and #4/#6's ordering are load-bearing for the demo actually producing
  learning output and not mis-executing on an assignment day; both are cheap to fix now.
- A general rule DSL for debounce/deadlines: unnecessary; both additions are small, closed-form
  checks, consistent with D-017's existing "small closed set, not a DSL" stance.
**Evidence:** [notes/007](notes/007_simulation_regression_run.md)
**Not adopted from the regression run, carried forward as open/unchanged:** interim scoring's
effect on elfmem's confidence posterior (needs a grounding computation, not resolvable by
reasoning — see notes/007 residual risks); D-018 #6 (no auto-consolidation) and #8 (per-frame
block capture) were not re-traced this round, since both depend on elfmem's actual runtime
behaviour rather than the architecture document — verify directly against the library, not by
further paper simulation; iteration 1's gaps #11 (phantom+orphan correlation) and #12
(`mind_predict` subject mapping) remain open and out of scope for this pass; #14 (`lessons.md`
growth) remains low-priority and deferred.
**Revisit if:** a future simulation pass finds the reordering (#1 above) has itself introduced a
new race, or the deadline sweep interacts badly with an in-flight multi-leg order at the exact
cutoff (worth a dedicated scenario next time a simulation runs).

## D-020: Order arguments authored by the model must be normalised before dispatch
**Date:** 2026-08-26
**Status:** accepted
**Context:** Found by running the walking skeleton, not by simulation. Both simulation passes
reasoned about `client_order_id` as something *we* set (INV-18). In the real system the LLM
calls the Alpaca MCP tools directly, so it authors **every** argument — and it duly invented its
own id (`trdrbot-skeleton-20260826-spy260918c765`) while the journal recorded the batch-derived
one we assumed had been sent. Two failures at once: INV-18's idempotency guarantee was void (a
crash-retry would invent a *different* id and open a second, different position — exactly the
failure D-018 #3 was written to prevent), and the journal was recording something that never
happened.
**Choice:** Wrap the order-*placing* MCP tools (`place_stock_order`, `place_option_order`,
`place_crypto_order`) and overwrite `client_order_id` with the batch-derived value before the
call leaves the process, logging any replacement. Cancel/close tools are addressed by order or
position id and take no `client_order_id`, so they are left untouched. The journal now records
the model's arguments verbatim *alongside* the enforced id, so a divergence is visible in the
record rather than hidden by it.
**This is not a guardrail (D-009).** It blocks nothing, rejects nothing, and vetoes no decision —
it normalises one argument so an existing invariant actually holds. Same category as
reconciliation: correctness plumbing, not policy.
**Generalised lesson:** any invariant that depends on the value of a tool argument is
unenforceable if the model authors that argument. Simulation could not have caught this, because
the design documents describe what the system *should* send without modelling *who* composes the
call. Worth re-checking the other invariants against this question: which of them assume we
control a value the model actually controls?
**Evidence:** observed directly in the first successful end-to-end tick; journal entry
`jrn_20260826T184458Z_exe47db` records the divergence.
**Revisit if:** we add order tools beyond the three `place_*` variants, or move off MCP to direct
SDK calls (in which case we author the arguments again and the wrapper becomes unnecessary).

## D-021: Submitted is not filled - the `opening` state must be used, and reconciliation must consult open orders
**Date:** 2026-08-26
**Status:** accepted
**Context:** Found by running stage 2. The agent placed a multi-leg limit order and recorded the
position as `open`; the broker showed **0 positions and 1 working order**. On the next tick
reconciliation would have seen "in our records, absent at broker", concluded phantom, and marked
a perfectly healthy pending order as externally closed — destroying a live position's record
while the order was still working. The `opening` state existed in the architecture's position
lifecycle from the start; it was simply never wired, and nothing in either simulation pass caught
that because both reasoned about positions as either open or gone.
**Choice:** Two changes. (1) `record_position` writes `status: opening`, not `open` — an order is
submitted, not filled, and claiming otherwise makes an unfilled limit look like real exposure
that exit rules would then evaluate against a position which does not exist. (2) Reconciliation
consults **open orders as well as holdings**, including the nested legs of a multi-leg order, and
resolves `opening` three ways: broker shows the legs → promote to `open`; a live order exists →
leave alone; neither → `abandoned` / `never_filled`, because it never became real exposure and
must not be scored as a trade that closed.
**Why it matters beyond the bug:** `abandoned` and `closed` are different outcomes for learning.
An order that never filled says nothing about whether the thesis was right, and scoring it as a
resolved trade would poison the calibration signal with non-events.
**Evidence:** observed live — position page `pos_20260826_SPY_bull_put_spread_ebf0dcde` claiming
`open` against a broker showing zero positions and one working `mleg` order. All four lifecycle
paths (pending / filled / died / vanished) now unit-tested.
**Generalised lesson (with D-020):** both findings come from the gap between what the design says
happens and what the broker actually does. Simulation validated the *logic*; only execution
validated the *interface*. Worth assuming every remaining broker-facing assumption is wrong until
a live tick proves otherwise.
**Revisit if:** partial fills on a multi-leg order need finer handling than the existing
`intended_legs` vs `actual_legs` divergence flag (currently suppressed while an order is still
working, which is correct but means a genuinely broken spread is not flagged until the order
completes).

## D-022: Adopt Google's Open Knowledge Format (OKF) frontmatter conventions for the wiki
**Date:** 2026-08-26
**Status:** accepted
**Context:** User directive to research OKF as a basis for the wiki. Verified via decision-mode
research (53 agents, primary-source fetch of `SPEC.md`/`README.md` directly, not secondhand
summary — see [notes/008](notes/008_open_knowledge_format_research.md)): OKF is a real, current
specification from Google Cloud's Data Cloud team (announced 2026-06-12, now v0.2, canonical
repo `GoogleCloudPlatform/open-knowledge-format`), confirmed distinct from schema.org, the
Knowledge Graph API, `llms.txt`/`AGENTS.md`, and the unrelated UK Open Knowledge Foundation
(same acronym). D-011's existing Karpathy-pattern wiki (`index.md`, `log.md`, `positions/`,
`lessons.md`, `strategy.md`, `context/`) already matches OKF's reserved-filename and
directory-of-markdown convention — this is formalization, not a redesign.
**Choice — normative OKF fields adopted, cited to `SPEC.md` directly:**
- `type:` on every concept file (`Position`, `Lesson`, `MarketContext`, `Metric`) — the only
  field OKF requires.
- `sources[]` replaces the flat `wiki_refs` sha-hash list from D-014: each entry carries
  `resource`, optional `id`, and credibility *signals* `author`/`usage_count`/`last_modified` —
  deliberately no stored score, since "a score is subjective, unportable, and goes stale."
  Per-claim attribution uses footnotes **keyed by `sources[].id`, not position**, because our
  learn path rewrites `lessons.md`/`strategy.md` over time and a positional citation would
  silently misattribute the moment the list reorders.
- `generated: {by, at}` / `verified: [{by, at}]` → three trust tiers (unverified /
  machine-confirmed / human-reviewed). `generated.by` formalizes the model-attribution tracking
  D-008 already required; `verified` is new capacity — when the reconciler independently
  confirms something the decide path wrote (a fill, a close), that becomes a legitimate
  machine-confirmed event distinct from the original unverified write.
- `status: draft|stable|deprecated` + `stale_after` (an absolute ISO instant, not a relative
  TTL) on `wiki/context/{regime,macro,calendar}.md` — exactly the "slow-changing, needs a
  freshness marker" case the field was designed for.
- Link convention: **relative paths**, not the spec's recommended absolute bundle-relative
  (`/`-rooted) form. Deliberate deviation — `positions/*.md` are a submission artifact judges
  may read on GitHub, and a leading `/` breaks GitHub's markdown rendering (the spec's own
  reference agent forbids the form it recommends, for the same reason).
**Why not alternatives:**
- Invent our own frontmatter schema from scratch: OKF already solved the provenance/trust/
  freshness questions we would otherwise have designed ad hoc, with reasoning (e.g. "no stored
  credibility score") directly applicable to our situation.
- Adopt OKF wholesale including its deferred `Attested Computation` runtime: the runtime
  protocol (receipt/verdict format, attester ABI, sandboxing) is explicitly unfinished in v0.2 —
  not safe to depend on. Noted as a directional fit for D-013's calibration scores, not adopted.
**Evidence:** [notes/008](notes/008_open_knowledge_format_research.md), `SPEC.md` §2-§7, §12-§13
**Revisit if:** OKF v0.3/v1.0 renames any field we've adopted (v0.2 already broke two v0.1
fields — `timestamp`→`generated.at`, `# Citations`→`sources` — so this has already happened
once in the format's short life), or if maintaining OKF-shaped frontmatter under a 9-day
deadline costs more than the retrieval/attribution benefit it buys.

## D-023: Wiki house rules borrowed from OKF's reference implementation — not the spec itself
**Date:** 2026-08-26
**Status:** accepted
**Context:** OKF's spec deliberately leaves note atomicity, when-to-split, deduplication, and
anti-degradation policy unspecified (explicit non-goals). The format's own reference-agent
implementation — labeled a proof of concept, not normative — has concrete, battle-tested answers
to exactly these questions. Adopting them as our own house rules, distinctly *not* citing them
as "the OKF spec," per [notes/008](notes/008_open_knowledge_format_research.md)'s own
normative-vs-illustrative distinction.
**Choice:**
1. **Four-gate mint test** before creating any new `lessons.md`/reference entry: (a)
   referenceable by name, not narrative; (b) not bundle-level meta (not an overview/changelog in
   disguise); (c) passes a "See the [X] for..." citation-sentence test; (d) would be cited by
   ≥2 existing concepts, or is load-bearing background for one. A speculative or one-off
   observation that fails gate (d) should not be minted as a standing lesson.
2. **Monotonic augmentation, enforced in code** — this is our concrete answer to "how do we
   reduce degradation," and the wiki's write path (`wiki.py`, not yet built) must implement it:
   writes are full-replacement, not patches; a guard refuses any write that shrinks an existing
   `sources[]`/`tags[]` list or drops a heading present in the prior version; `generated` is the
   only frontmatter key allowed to shrink to nothing (it gets refreshed on write). A rejected
   write means retry with a proper superset, not silent data loss.
3. **Anti-orphan rule** — a minted reference note with nothing linking to it is a bug; the
   learn/housekeeping path should verify new notes are cited from at least one primary page
   before considering a write cycle complete.
4. **Write workflow**: read the existing note first and refine rather than rewrite from
   scratch; write exactly one concept per call rather than one sprawling document covering
   several facts.
**Why this shape:** these rules exist specifically because an LLM is the primary and only
writer of this wiki, with no human review step (D-009's no-guardrails philosophy extends here —
the wiki has no gate on what gets written, only a discipline for how). Monotonic augmentation is
the load-bearing one: without a code-level guard, a "helpful" rewrite that drops detail is
indistinguishable from a good edit until the knowledge has already quietly degraded across many
autonomous cycles.
**Why not alternatives:**
- Trust prompt instructions alone to prevent degradation: the same category of gap D-018/D-019
  already found elsewhere (constitution says X, nothing enforces it) — a code-level guard is
  required, not optional, given the pattern's track record in this project specifically.
**Evidence:** [notes/008](notes/008_open_knowledge_format_research.md); reference-agent prompt
files and `bundle_tools.py`'s augmentation guard, read directly (not summarized).
**Revisit if:** the augmentation guard proves too rigid in practice (e.g. a genuine correction
that must legitimately shrink a section) — add an explicit `supersedes` escape hatch rather than
removing the guard.

## D-024: One mind per underlying, tracked in a local file — not elfmem's own duplicate detection
**Date:** 2026-08-26
**Status:** accepted
**Context:** Resolves notes/006 gap #12 (mind_predict needs a mind subject; mapping
unspecified) during stage 3 build. Verified live against the installed 0.20.0.dev0 library:
`mind_create`'s duplicate detection is unreliable under realistic use. Two consecutive calls
with an identical subject correctly dedupe in isolation (`duplicate_rejected`, same
`block_id`) — but the identical two calls issued after other memory operations (a `remember()`,
an earlier `predict()`) each returned `created` with a *different* `block_id`, silently minting
a second mind for the same underlying. `mind_list()` cannot substitute as a pre-check either:
a freshly created mind sits in elfmem's inbox and is invisible to `mind_list()` until a `dream()`
consolidation runs, which under D-018 #6/INV-23 only happens at housekeeping — so a list-first
check would report "not found" on every call within a tick regardless.
**Choice:** `underlying -> mind_block_id` is tracked in a small local JSON file
(`data/state/minds.json`), fully within our own control, checked before ever calling
`mind_create`. elfmem's own dedup is not relied on at all.
**Why not alternatives:**
- Trust `mind_create`'s built-in duplicate detection: demonstrated unreliable above — would
  fragment prediction tracking per underlying across an unpredictable number of duplicate minds.
- Check `mind_list()` first: reports false negatives inside the dream-less window that is our
  entire normal operating mode (every tick except housekeeping).
**Evidence:** live verification against the installed library, not the docs — see git history
for the exact reproduction sequence.
**Revisit if:** a future elfmem release changes duplicate-detection semantics; our local mapping
would then be redundant but harmless, not something that needs removing urgently.

## D-025: elfmem's dream() requires a working embedding provider we do not yet have
**Date:** 2026-08-26
**Status:** resolved 2026-08-26 — user supplied a valid `OPENAI_API_KEY`
**Context:** `dream()` (consolidation — the step that promotes freshly `remember()`'d content
from elfmem's inbox into anything `frame()`/`recall()` can actually return) calls out to an
embedding provider. elfmem ships only two embedding adapters: a real OpenAI adapter, and an
explicit test-only mock — no Anthropic option exists, because Anthropic has no embeddings API.
Live-tested: the `OPENAI_API_KEY` currently in `.env` returns 401 (invalid). `remember()`,
`mind_predict()`, `mind_outcome()`, and `outcome()` are all confirmed pure-DB and unaffected —
writes and credit-assignment work regardless. What's blocked is retrieval: `frame()`/`recall()`
return nothing for anything not yet consolidated, and `dream()` itself cannot complete.
**Current behaviour (not a fix, a safe degrade):** `housekeeping_dream()` catches the failure,
logs it, and returns `False` rather than crashing housekeeping's other work (INV-8's
advisory-input philosophy, extended to consolidation) — verified live. The rest of stage 3
(remember/predict/outcome/mind_outcome, all writes) works correctly regardless of this gap.
**What's actually degraded:** the `self`/`task`/`attention` frames injected into the decide
prompt will stay empty until consolidation succeeds at least once — so the agent is currently
deciding without elfmem's semantic recall contributing anything, even though every write is
being correctly recorded and will retroactively become recallable once a valid key exists.
**Resolution:** user added a valid `OPENAI_API_KEY` to `.env`. Verified end to end, forcing
`dream()` directly rather than waiting for the inbox threshold: a `remember()`'d block was
consolidated ("1 promoted, 0 edges"), then correctly returned by `recall()`, and
`assemble_context()` populated all three frames (`self`/`task`/`attention`) with real text.
**One recurrence of the same class of bug as the Anthropic key earlier this session**: the first
verification attempt still hit the old invalid key, because the ad hoc test script never called
`config.load()` and so never applied our own `.env`-overrides-shell fix — it picked up a stale
shell `OPENAI_API_KEY` instead. Not a new bug; a reminder that any script touching secrets must
go through `config.load()`, not construct its own environment.
**Evidence:** `elfmem/adapters/` contains only `openai.py` and `mock.py`; live dream()/recall()
round-trip confirmed via `trdrbot.config.load()`.

## D-026: Unique-per-call ids must not be derived from second-resolution timestamps
**Date:** 2026-08-26
**Status:** accepted
**Context:** Found live during stage 4. The `alpaca_news` sensor reported "20 new of 20
fetched" and left **2 files on disk**. Root cause: `item_id` hashed `(kind, source,
utc_stamp)` — all three identical for items written in the same second — so every item in a
sensor batch got an identical filename and silently overwrote the previous one. 18 of 20 real
news articles were destroyed with no error, no warning, and a log line that said everything
worked. Auditing the rest of `ids.py` found the same flaw in `journal_id` (less destructive —
the journal is append-only so nothing is overwritten, but duplicate ids break traceability and
`decision_ref` lookups could resolve to the wrong entry) and in `position_id` (**most severe** —
two positions on the same underlying/strategy opened in the same second would silently share
one wiki page, the second's thesis and exit rules destroying the first's).
**Why it stayed hidden until now:** nothing before sensors ever wrote more than one item per
second. Stages 1-3 wrote at most one position and a handful of journal entries per tick, each
comfortably separated. The bug was latent from the walking skeleton onward and only became
reachable when a batch-emitting producer existed.
**Choice:** `item_id`, `journal_id` and `position_id` now use `uuid4` for their unique
component instead of a timestamp hash — removing the collision entirely rather than narrowing
the window with finer-grained timestamps, which would only make it rarer and harder to
reproduce. Verified 100/100 unique for each.
**Critically unchanged:** `batch_id` and `client_order_id` remain fully deterministic — they
*must* be, because INV-18's crash-retry idempotency depends on the same batch producing the
same order id. Verified explicitly after the change (order-stable, repeatable) rather than
assumed.
**Generalised lesson (with D-020, D-021):** the third find this project that only surfaced by
running the system rather than reasoning about it — and the first that was latent in code
written three stages earlier. A design-level review would not have caught it: the id function
looked correct in isolation and only failed under a call pattern that did not yet exist.
**Evidence:** live sensor run (20 fetched → 2 persisted → 20 persisted after fix); uniqueness
and determinism both re-verified at 100 samples.
**Revisit if:** any id needs to become deterministic later — it would then need an explicit
content-derived key, not a timestamp.

## D-027: Adopt Polymarket from the prior trdrbot project; reject xmcp and the rest
**Date:** 2026-08-26
**Status:** accepted
**Context:** Reviewed the tools and MCPs in a prior incarnation of this project
(`~/Dropbox/devel/projects/ai/trdrbot`) for anything worth bringing across. It carries three
MCPs (`xmcp`, `elfmem`, `elfsim`) and eight "organs" (polymarket, fred, rss-news, yfinance,
alpaca, market-analysis, paper-ledger, ask), plus a knowledge vault of live-verified
data-source quirks.
**Choice — adopt Polymarket only.** Evaluated against operational friction and our own
signal-per-token order (D-015):

| Candidate | Auth | Cost | Process | D-015 rank | Verdict |
|---|---|---|---|---|---|
| polymarket | none | $0 | none (plain HTTP) | #2, next up | **adopt** |
| xmcp (X/news) | 4 OAuth secrets | credits, 402 seen live | separate server, ~9s startup | #4, last | reject |
| fred | API key | $0 | none | not in order | defer |
| elfmem MCP | — | — | subprocess | — | reject: we use the library (D-011), which the research found strictly better |
| elfsim MCP | — | — | subprocess | — | reject: spec-only, no implementation (D-013) |
| rss-news, yfinance, alpaca, market-analysis, paper-ledger, ask | — | — | — | — | reject: duplicate what we already built |

**Why Polymarket wins decisively:** it is the only candidate with *zero* operational friction —
no credentials, no cost, no separate process — and it is literally the next sensor in our own
planned order. It also resolves architecture.md §12's open assumption ("Polymarket exposes
queryable market odds suitable for automated polling") with a **yes**, and feeds the calibration
synergy D-015 §3.4 identified: a market-implied probability is a free external benchmark against
our own stated confidence (D-013).
**Why xmcp is rejected despite being genuinely useful:** four OAuth secrets, real per-call
credit cost (the prior project's own journal logs an `HTTP 402, credits depleted` mid-run), and
a separate long-running local server with ~9s startup that would have to survive an 8-day
unattended window. It is also the *lowest* trust tier (`social`), which our own simulation
flagged as the false-viral risk (FM-18). High friction, lowest signal, last in priority — a bad
trade for a 9-day build. The capability is documented here should the window ever widen.
**What actually transferred:** not just code — the load-bearing value is nine **live-verified
API quirks** (now `docs/sources/polymarket_gamma_api.md`), several of which are silent-corruption
bugs rather than errors. Quirk 1 is the sharpest: `outcomes`/`outcomePrices` arrive as
JSON-encoded *strings*, so `prices[0]` returns the character `'['` rather than a price.
Re-verified live on adoption. Our `src/trdrbot/polymarket.py` implements the same defences
(double-decode, skip closed/inactive/degenerate markets nested inside open events, prefer
`volumeNum` over string `volume`, never fabricate `0.0`, no `sort=volume` on text search, and
`.get("events") or []` because a zero-result search omits the key entirely).
**A latent bug this surfaced in our own code:** `Sensor.policy` was declared but never read —
`collect()` applied identity-dedup to everything regardless, and `alpaca_news` was mislabeled
`change_only` when it is really dedup-by-article-id. Polymarket needs `change_only` to mean
something, so policy is now real: `filter` (identity dedup), `change_only` (numeric threshold),
`raw` (pass through). Change detection compares against the **last emitted** value, not the
previous poll, so a slow drift still surfaces instead of creeping past one sub-threshold step at
a time — verified explicitly.
**Evidence:** live end-to-end run (8 markets ingested: Fed cut odds by meeting, US recession,
CPI prints; second poll correctly emitted zero); change-detection semantics verified across
six transitions.
**Revisit if:** the competition window widens enough to justify xmcp's setup cost, or FRED's
backward-looking series become useful alongside Polymarket's forward-looking probabilities.

## D-028: Thesis -> experiments -> execute -> attribute loop, with view/structure separation
**Date:** 2026-08-26
**Status:** accepted
**Context:** The agent could form a thesis and place one trade, but could not compare candidate
expressions of that thesis before committing, and — more seriously — could not tell whether a
loss meant its *view* was wrong or merely its *structure*. P&L-only learning conflates the two.
**Choice:** A five-part loop.
1. **`optmath.py`** — options maths split into two layers by how much they deserve to be
   trusted. **EXACT** (payoff at expiry, entry cost, max profit/loss, breakevens) is arithmetic
   on the contract with no model. **MODELLED** (probability of profit, EV) needs a terminal
   distribution and uses lognormal-at-current-IV, which is standard and still an assumption.
   The two are labelled separately everywhere they surface, because an agent that treats
   "P(profit) 68%" with the same confidence as "max loss $300" will size wrongly.
2. **`experiments.py`** — `Thesis` (falsifiable, with machine-checkable price bands),
   `Experiment` (one structure expressing it), `simulate`, `rank`.
3. **`simulate_experiments` tool** — takes ALL candidates in one call and refuses fewer than
   two. A per-candidate tool would let the agent simulate one structure and stop, which is a
   slower way of deciding first and justifying afterwards.
4. **Ranking is by thesis edge, deliberately not EV.** EV under lognormal-at-current-IV is the
   most model-dependent number available; ranking by it hands the decision to the model's tails.
   "Thesis edge" (P(profit) under the agent's own drift, minus P(profit) under the market's
   zero-drift assumption) is what the agent actually claims to know. A thesis that cannot move
   that number is decorative, and the column shows it.
5. **`attribution.py`** — the reason the loop is worth building. Four quadrants:
   | thesis | outcome | verdict | signal |
   |---|---|---|---|
   | held | profit | both right | 0.90 |
   | held | loss | **expression wrong, view keeps its credit** | 0.65 |
   | failed | loss | view wrong, structure faithful | 0.10 |
   | failed | profit | **lucky — reinforce nothing** | 0.50 |
   The elfmem signal follows the *attribution*, never the money. P&L-based scoring would give
   the lucky win 0.90 and the right-view-wrong-structure loss 0.10 — exactly backwards, and
   exactly how an agent learns a superstition.
**Timing is load-bearing:** attribution runs at housekeeping when the thesis **horizon** has
passed, not at position close. A stop triggering on day 2 of a 10-day thesis says nothing about
whether the view was right; scoring it at close would record "thesis wrong" for a view that had
not yet been tested — the precise mis-attribution the module exists to prevent. Verified: a
closed-but-pre-horizon position is correctly excluded from the attribution queue.
**Bugs found and fixed while building (all by testing, not review):**
- **`max_profit_loss` reported a finite max profit for a long straddle** (+$9,199) when its
  upside is genuinely unbounded. The put-side branch overwrote a correctly-`None` result. A
  confident wrong number about a position's own risk profile. Now verified across ten
  structures including every unbounded case.
- **Calendar/diagonal spreads computed silently wrong.** `Leg` had no expiry field, so legs at
  different expiries were indistinguishable from a same-expiry pair and produced a confident
  garbage payoff. Now `MultiExpiryError`, refused by name at the single chokepoint (`pnl_at`)
  every other function routes through.
**Validation:** grid weights sum to 1.000000; `E[S_T]` = spot exactly (martingale under r=0,
confirming the −σ²T/2 correction); EV of a fairly-priced option = +0.0000, moving to ±100 for a
∓1.00 mispricing; P(profit) monotone in strike; independently sanity-checked against σ-distance
(a −1σ breakeven reporting 84% is right).
**Revisit if:** calendars become worth supporting (needs a pricing model for the far leg at the
near expiry — real work and real model risk, deliberately deferred), or the lognormal assumption
proves materially wrong against realised outcomes, which the calibration record (D-013) will show.

## D-029: Optimise expected profit via calibrated decisions, not this week's P&L
**Date:** 2026-08-26
**Status:** accepted
**Context:** The stated project goal is "generate as much profit as possible". Before tuning
the system toward that, two things were checked rather than assumed.

**First, what actually wins.** Our own `docs/submission_and_judging.md` listed a "Results &
Performance" criterion including raw returns — but it was explicitly marked *(Inferred)* and had
never been verified. Researched: **lablab.ai scores across four dimensions — Application of
Technology, Presentation, Business Value, Originality.** Raw P&L is not among them. A comparable
AI-trading hackathon states rankings use "risk-adjusted profitability, drawdown control, and
validation quality, not just raw PnL". The docs are corrected in place.

**Second, whether a week of P&L means anything.** Simulated: a genuinely skilled 60%-edge agent
out-scores a coin flip only **69% of the time over 20 trades**; a zero-skill agent risking 1% per
trade lands between **-7.8% and +8.2%** (90% interval). Over an 8-day window with our cadence,
raw P&L cannot distinguish skill from luck in either direction.

**Choice:** keep the goal — profit — but change the objective function from "maximise this week's
P&L" to "maximise expected profit per unit of risk, with the decision process demonstrably
improving". These are not in tension about *what to build*; they are in tension about *what to
optimise*. Swinging for a big week maximises variance, and a blow-up would cost marks on all four
real dimensions while proving nothing about skill.

**Why this is the profit-maximising choice and not a hedge:** the machinery that wins the rubric
(calibration, view-vs-structure attribution, provenance, earned sizing) is the *same* machinery
that produces profit over any horizon long enough to be meaningful. Optimising the one-week
number is the only variant that trades the two off against each other.
**Evidence:** lablab.ai's published four-dimension rubric; statistical power simulation above.
**Revisit if:** the organisers publish trading-performance-based criteria for this specific event.

## D-030: Position size is derived from edge and EARNED by calibration
**Date:** 2026-08-26
**Status:** accepted
**Context:** Sizing was the model's free choice, unconnected to edge, bankroll, or track record —
which made every other piece of machinery decorative, since a well-reasoned trade at a reckless
size is a reckless trade. Sizing is the single largest lever on long-run profit.
**Choice:** `sizing.py` — Kelly, scaled fractionally, gated on measured calibration.
- Full Kelly is unusable (acutely fragile to estimation error, per the literature); the
  practitioner consensus is fractional Kelly used as a **ceiling, not a target** (Thorp:
  half-Kelly captures ~75% of growth for ~25% of the variance).
- **The fraction is earned.** Stated confidence is shrunk toward the base rate in proportion to
  how well the agent's probabilities have actually held up (D-013). No record → 5% Kelly and a
  halved claimed edge. Established calibration over a real sample → 25% Kelly.
- Hard ceiling of 5% of equity per position regardless, because every Kelly input is an estimate
  and estimates fail together in exactly the conditions that matter.
- Concentration divisor: several options positions on one underlying are one bet wearing hats.
- Unbounded max loss → **refused**, not sized: Kelly divides by a worst case that does not exist.
**Why this is the self-improving loop, concretely:** better calibration is not a dashboard
metric, it is *permission to bet more*. Experience → demonstrated reliability → larger size →
more profit, with no step that rewards confidence unbacked by evidence. Verified: the same stated
70% confidence yields **0 contracts with no track record and 16 with a proven 30-sample record**.
**A useful thing it catches:** Kelly refuses high-probability-*looking* credit spreads with poor
payoff ratios — collecting $75 against $425 of risk needs ~85% accuracy just to break even, and
the module returns zero contracts below that. "Probably wins" is not "worth trading".
**Also added:** round-trip friction in the simulation. Options spreads are wide, and simulating
at mid systematically overstates every edge — most for the cheap far-OTM options that look best
on a payoff diagram. Measured on a real candidate: EV +25.4 before costs, **+8.9 after** — a 65%
reduction, with friction comparable in magnitude to the edge itself.
**Evidence:** Kelly/fractional-Kelly research (Thorp half-Kelly result, quarter-Kelly under
estimate uncertainty, "ceiling not target"); differentiation verified across payoff ratios and
confidence levels.
**Revisit if:** the sample grows past ~50 resolved forecasts, at which point the literature
supports recalculating and possibly raising the fraction.

## D-031: Findings from the first full open-market-logic run
**Date:** 2026-08-26
**Status:** accepted
**Context:** First execution of the complete reasoning chain (thesis -> experiments -> sizing)
against real market data, via a new `--force` flag that runs the decide path outside market
hours. Orders queue rather than fill, so this tests the DECISION, not execution — and it is
also how the agent's reasoning gets demonstrated without waiting for the bell.
**What worked, unprompted:** the agent ran `simulate_experiments` with two genuinely different
structures, read EV-after-costs, and **declined to trade** — "both negative after costs, so I
stopped before `size_position`". It independently identified the credit-spread trap (collect $51
to risk $449 needs ~90% accuracy), noticed call-side IV at 7.4% against put-side 16.5% and
reasoned about selling the cheap wing of a skewed surface into an earnings print, and flagged
that a second short-vol SPY position would double existing factor exposure rather than
diversify. The transaction-cost work (D-030) directly changed the decision: "friction alone eats
the edge."
**Bugs found by running it, all silent-failure class:**
1. **`attribution._spot` could never succeed.** Two faults at once: the parameter is `symbols`,
   not `symbol_or_symbols` (the wrong name is dropped from the parameter map and the request
   400s), and the default SIP feed 403s because our subscription does not permit recent
   consolidated data. `_spot` therefore always returned `None` and attribution **silently never
   ran** — the self-improving loop's most important step dead while every log line read healthy.
   Now pinned to the `iex` feed with a `get_stock_latest_trade` fallback. Verified live: 766.42.
2. **Thinking blocks polluted the journal.** Extended-thinking responses return a block list —
   an opaque signature blob then the real text. Stringifying the list dumped base64 into the
   journal and console and consumed the 2000-char summary budget. Now extracts `text` blocks only.
3. **A 529 Overloaded discarded an entire decide cycle.** Provider transients are routine and
   certain across an 8-day unattended run. `OverloadedError`/`ServiceUnavailable` are now named
   explicitly in the transient set (previously correct only by fallback), and LLM calls retry
   five times — retrying inside the call is far cheaper than losing the tick and re-assembling
   the same context next cycle.
4. **A printf format error crashed the comparison renderer** (`%+,.0f` — the comma flag is
   f-string only). The agent had already called the tool successfully; the crash was in showing
   it the answer. Render path now regression-tested across bounded, unbounded-loss,
   unbounded-profit, calendar and zero-price candidates.
**Evidence:** live runs, ticks 16-19.

## D-032: A daily research cycle produces the theses - regime, dossiers, opportunities
**Date:** 2026-08-27
**Status:** accepted
**Context:** Everything downstream (simulate -> size -> execute -> attribute) started at "a
thesis exists," but nothing produced theses with research behind them. The user's intent: a
top-down process - macro regime from news/calendar/geopolitics, then a researched company
universe (what it is, why/why not to invest, the people, the environment, historical trading),
technicals on real price history, Monte Carlo over outcomes, then opportunity selection.
**Choice:** `research.py`, a once-daily cycle on the slow path (housekeeping-triggered, plus a
`trdrbot research` command). Division of labour is strict: **numbers are computed, never asked
of the LLM** (`market_stats.py` - trend vs SMAs, realized vol + percentile, drawdown, momentum,
from real Alpaca bars); the LLM does what only it can - synthesis and judgment. Event dates must
come from the supplied news/odds, not model memory ("unknown" is the required answer otherwise -
and the first live run correctly wrote "date unknown" four times). Outputs:
- `wiki/context/regime.md` - the standing market assessment, OKF-typed, `stale_after` end of
  day, stable headings so the augmentation guard enforces the schema.
- `wiki/research/<ticker>.md` - company dossiers (what it is / bull / bear / people /
  environment), model-knowledge content explicitly marked as such.
- 0-3 **opportunity items into the existing inbox seam** - falsifiable (band + horizon
  validated in code before emission; unscoreable ones are rejected and journalled). Research
  proposes; the decide cycle still validates against live chain prices, sizes, and disposes.
**Bootstrap Monte Carlo** (`bootstrap_factors`): terminal distributions resampled from real
daily returns rather than assumed lognormal - directly addressing the documented wrong-tails
limitation. Returns are **demeaned** first: the convergence test caught raw resampling
disagreeing with lognormal by 16pp on identically-distributed data purely because the sample
path happened to rally - recency bias with a formula wrapped round it. Demeaning keeps the
shape, strips the luck; direction is applied deliberately via the thesis drift. Verified:
demeaned bootstrap vs lognormal gap 1.6pp on identical data, E[factor]=1.0004, drift tracks
exactly. `simulate_experiments` now shows a HISTORY row and flags a >=5pp tail gap as
"edge is assumption-dependent".
**The full funnel worked on its first live run - and validated itself.** The decide cycle
rejected both initial opportunities: one on payoff arithmetic (nearly-free condor premium),
and one on a **price discrepancy that turned out to be a real data bug** - ascending bars with
`limit` truncate from the START of the range, so the research stats described a market six
weeks stale while every log line read healthy. "The research note assumes NVDA at 224.11; the
tape says 209.37. I won't trade a thesis whose premise is contradicted by the price feed."
Fixed with `sort=desc` + reverse, which anchors the window to today by construction. That
catch is the architecture doing its job: research proposes, decide verifies against live data.
**Evidence:** live research run (4 wiki pages, 3 valid opportunities with current data);
convergence + drift tests on the bootstrap; the decide cycle's rejection transcript.
**Revisit if:** the universe grows past ~6 names (one LLM call per day stops being enough), or
a real fundamentals data source is added (Alpaca has none on our tier - dossier fundamentals
are model-knowledge + news, explicitly marked).

## D-033: Epistemic constitution in elfmem's SELF frame — evaluated worth doing, deferred to the joint session
**Date:** 2026-08-27
**Status:** accepted as future plan — no build until the planned joint session
**Context:** The bootstrap-drift finding ("recency bias with a formula wrapped around it") is
one instance of a class: epistemic failures in market reasoning. Code fixed that instance
permanently; nothing inoculates the LLM's *judgment* against the next instance of the class —
three of which occurred within two days. Question evaluated: should elfmem's SELF frame hold
learned epistemic principles that the decider reads as identity?
**Verdict: yes, in the human-ratified form only, scoped to the judgment residue code cannot
reach.** Full brainstorm, mechanism (seed constitution → self-test prompt line → incident-level
credit assignment on principle blocks → `propose_amendment` for human ratification), and the
honest case against, in [notes/009](notes/009_epistemic_constitution_plan.md).
**The two constraints that shaped the verdict:**
- elfmem's own ADR 0003 simulated four architectures for *automatic* constitutional evolution
  and none beat baseline — so autonomous self-amendment is contraindicated by the project's own
  best evidence. Amendments are proposed by the agent with cited incidents, ratified by a human.
- D-018/D-019's repeated finding that prompt-level guidance is weak — so principles are scoped
  strictly to judgment errors, where no gate can be built; everything enforceable stays code.
  A proposal that drifts toward "principle instead of code fix" is rejected on sight.
**Why elfmem rather than a longer system prompt:** principles carry Beta-posterior confidence
earned from scored incidents (a system prompt weighs every line equally forever), cite the
incidents that minted them (D-014's provenance spine extended to reasoning rules), and evolve in
data while the prompt stays stable and cacheable.
**Sample-size honesty:** an 8-day window yields too few resolved trades for converged learning;
principles are therefore scored on incident detections (premise breaks, rejections, tail-gap
warnings — several per day) as well as trade outcomes, and the within-hackathon value is the
demonstrated mechanism with honest early posteriors, not converged weights.
**Evidence:** [notes/009](notes/009_epistemic_constitution_plan.md); elfmem exploration
(notes/004 §10.1: SELF-frame contract, amendment API, ADR 0003); this project's incident record.
**Revisit if:** the joint session finds the seed principles impossible to trace to real
incidents (a sign they are platitudes, not learned rules), or incident-level scoring proves too
noisy to move a posterior meaningfully.

**Note (2026-08-27, D-033 extension):** the constitutional *content* is now brainstormed and
evaluated in [notes/010](notes/010_constitutional_blocks_brainstorm.md) — nine candidate blocks
(three epistemic, five meta-memory, one change-control), each traced to a real incident or
verified elfmem mechanic, sized to the SELF frame's ~600-token budget. As important: an explicit
cut list — everything with a deterministic backstop (luck-neutrality, friction, payoff-ratio,
defined-risk) *loses* its slot per notes/009's boundary, and market views are ruled a category
error for the constitution outright. Simulated against three scenarios: blocks 1+6+7 compose
into the pattern-degradation arc the user asked for (contradiction recorded → pattern demoted to
hypothesis on regime mismatch → decays if never re-validated). Wiki ingestion evaluated: a
single `wiki_ingest.py` chokepoint with per-type schemas-as-data, deferred until a third writer
or an agent wiki-write tool exists; when built, it also owns promotion/demotion between stores
(elfmem pattern that survives a regime change → promoted to wiki; wiki page past stale_after
unverified → deprecated), completing the consolidation arc D-011 designed but never assigned an
owner. notes/010 ends with the joint-session agenda.

## D-034: Interim scoring fires on materiality bands, not on every cycle
**Date:** 2026-08-27
**Status:** accepted
**Supersedes:** the cadence half of D-018 #1 / INV-24 (the low weight stands; the per-cycle
trigger does not)
**Context:** Scaffold pass over the journal after a full tick. INV-24 gave interim scores a
deliberately low weight (0.1) so an unrealised mark could not rival a true resolution (1.0). The
weight was right; **repetition was the hole nobody priced.** One unresolved position had
accumulated **eight** interim scores - 0.8 of cumulative evidence, approaching a real resolution -
and every one scored `hit=False` from a -$45 mark that was bid/ask noise on a freshly opened
spread whose thesis was intact, with the underlying sitting 1.5% clear of the short strike. The
learning loop was busy teaching itself that a good position was bad, from spread noise, eight
times over. Exactly the failure the iteration-2 simulation asked about ("does repeated interim
scoring over-weight the signal relative to a single true resolution?") - answered live: yes.
**Choice:** score only on **first entry into a materiality band** (|P&L| >= 25%, then >= 50%),
tracked per position in a monotonic `interim_band` field. Consequences: a position contributes at
most two interim signals (cumulative weight 0.2, comfortably under a resolution's 1.0); each is
earned by a move too large to be spread noise; and because bands are one-way, a mark oscillating
across a threshold cannot re-fire - the same debounce reasoning as INV-19's exit rules, applied
to learning rather than execution.
**Verified:** eight noise marks around -3% now fire 0 scores (was 8); a genuine deterioration to
-58% fires 2, at -27% and -55%; the field round-trips through disk and legacy position files
without it default to 0; live unforced housekeeping logged `interim_scored=0` where the old code
would have written a ninth false negative.
**Also found:** `tick --force` skips housekeeping entirely, so forced runs exercise only the
decide half - research, attribution and interim scoring never run. Correct behaviour for a flag
whose job is to force the decide path, but worth knowing when reading forced-run output as
evidence: it is half the system. Noted rather than changed.
**Evidence:** journal entries (8 x interim_outcome on one unresolved position); live tick 23.

## D-035: News-driven discovery - the news nominates the companies
**Date:** 2026-08-27
**Status:** accepted
**Context:** The daily research cycle (D-032) studies a FIXED universe, so the system could
never trade a story it wasn't already watching. The user's thesis-building exercise: broad news
+ prediction-market odds -> nominate interesting companies -> forecast with simulations ->
historic data + technical analysis -> suggest opportunities.
**Choice:** `discovery.py` (`trdrbot discover`). Two LLM calls with the deterministic layer
between them: (1) NOMINATE 3-5 companies strictly from supplied evidence - nominations from
general knowledge alone are forbidden by prompt; (2) SYNTHESISE forecasts and 0-3 falsifiable
opportunities only after each nominee has been through computed technicals (now incl. Wilder
RSI-14), a drift-free bootstrap Monte Carlo 5-day forecast from its own returns, a Yahoo
fundamentals snapshot, and an options-liquidity gate. Gates enforced in code, not prompt: no
options expiring inside the deadline -> cannot become an opportunity regardless of story;
horizon past deadline -> rejected; bands that are not plausible prices -> rejected.
**Data-source split, evidence-based:** Alpaca for price history (authenticated, consistent with
the bootstrap machinery), Yahoo/yfinance for fundamentals only (market cap, P/E, sector, analyst
target, next earnings - the data Alpaca has no API for; yfinance's unofficial API is flakiest at
prices and strongest exactly here). Verified live before choosing: yfinance NVDA close 209.66 vs
Alpaca IEX 209.77.
**Bug caught by inspecting the first live run:** the LLM emitted bands as PERCENTAGE MOVES
([-6.0, 8.0] on an $87 stock). `holds_at()` would have been always-False and attribution would
have scored every discovery thesis as failed - silently corrupting the learning loop with
false negatives. Fixed twice over: prompt now states bands are prices in dollars, and a code
gate anchored to the computed close rejects any band outside [0.3x, 3x] of spot
(`band_not_a_price`). Second run emitted clean price bands (CRM 198-228, META 555-640).
**First live run:** nominated CRM, CRWD, META, MRVL, BBY from the morning's news; wrote five
dossiers; emitted 2 opportunities that survived all gates. Output flows through the existing
seams (wiki + inbox) so the decide cycle validates against live quotes before anything trades.
**Evidence:** live runs 1 and 2; journal `discovery_nominees`/`discovery` entries.
**Revisit if:** yfinance breaks (unofficial API - the fundamentals block already degrades to
`unavailable` without sinking the run), or nomination quality drifts toward megacap defaults
(the "not the biggest names, the most interesting ones" instruction stops working).

## D-036: Trader-review hardening - thesis stops, portfolio cap, real friction, event calendar
**Date:** 2026-08-27
**Status:** accepted
**Context:** Full-logic review through a professional trader's lens ([notes/011](notes/011_trader_review.md)).
The edge process (simulate, rank by thesis edge, refuse unbounded loss, decline freely) was
already sound; the gaps were all on the RISK side.
**Implemented, all verified:**
1. **`underlying_stop` exit rules (F1).** The agent's stated invalidation ("break below
   ~757-758") and its coded exits (mark-based only) disagreed - and the mark is the noisiest
   signal an options position produces. New rule type evaluates the UNDERLYING against the
   thesis level (same N-of-M debounce, immediate at 1% beyond); the snapshot fetches a live
   underlying mark per open position; `record_position` exposes it and the prompt directs the
   agent to set it at the level it would state out loud.
2. **Portfolio at-risk cap (F2).** `PORTFOLIO_MAX_AT_RISK = 0.15` of equity over the sum of
   open defined max-losses plus the candidate; `Position.max_loss_usd` recorded at entry;
   sizing shrinks to the remaining budget and refuses when the book is full. Per-position caps
   alone allowed a 25% correlated book in 5% clothing.
3. **Real spread friction (F3).** `simulate_experiments` accepts bid/ask per leg; when every
   leg carries a quote pair, friction = one full spread per leg instead of flat 10% of premium.
4. **Event calendar (F4).** `events:` config (rule-derived/user-verified dates only), rendered
   into decide context within 14 days. Seeded with the landmine: payrolls = first Friday =
   2026-09-04 = the deadline day.
5. **Execution discipline (F5).** Prompt: always limit orders at mid or better on options.
**Evaluated, parked with reasons (notes/011 F6-F9):** contest-variance sizing (revisit ~Sept 1
as a recorded decision if flat with proven calibration), order-rate breaker (D-009 stands),
IV-rank store (post-hackathon), mark-vs-liquidation honesty (F1+F3 cover the sharp edges).
**Evidence:** live verification of each: debounced underlying stop fires 2-of-3 at 756.8 vs
757.5 and immediately at 748; portfolio cap 3 contracts empty-book, refused at $14.5k open
risk; real friction $6 vs flat $9 flowing into EV-after-costs; tick 24 clean end-to-end.

## D-037: One exit-signal registry, one risk unit - collapsing D-036's five mechanisms
**Date:** 2026-08-27
**Status:** accepted
**Supersedes:** the *implementation* of D-036 F1/F2 (findings unchanged, mechanisms replaced)
**Context:** D-036 fixed five real trader-review findings in one pass, but each as its own
ad-hoc mechanism. Reviewing the result against "minimal, elegant, consistent": four exit-rule
branches with copy-pasted debounce and two different severity conventions; a `max_loss_usd`
field the LLM had to remember or the book cap silently under-counted; three overlapping size
limits; debounce state keyed by rule TYPE so two rules of one type shared history; and nothing
connecting the agent's stated invalidation to what was enforced.
**Choice - the unifying insight:** every exit rule is *read a signal, compare to a threshold,
debounce*. Rule types differ only in which signal they read, so signals became a registry
(`EXIT_SIGNALS`) with one uniform evaluator - the same shape as the sensor registry (D-015),
which is what "consistent with the underlying system" means here. Consequences:
- Severity unified as **relative overshoot**, reproducing both old conventions from one
  comparison (1.0 = 2x a percentage stop; 0.01 = 1% through a price level; 0.0 = time is not
  noisy so any breach is decisive).
- The deadline sweep became an ordinary implicit rule instead of a special case above the loop.
- Debounce keys are now `signal:direction:threshold`, fixing a **real bug**: two
  `underlying_stop` rules at different levels shared one history.
- Multiple simultaneous triggers resolve by explicit priority (deadline > stop/underlying >
  time > target) instead of list order, so a position at both its stop and its target exits as
  a stop rather than booking a fictional win.
- Stale pre-registry state self-heals on first evaluation.
**Risk is derived, not declared.** `size_position` stashes the size it computed in `shared`;
`record_position` reads it - the same mechanism already carrying `thesis`. A forgotten field
used to count a position as **zero risk** and quietly loosen the caps; that path is gone.
Cross-ticker mismatch is guarded (NVDA sizing never attaches to a META position).
**Risk measured one way.** The opaque `frac /= (1 + open_count)` divisor - a proxy invented
before real risk was tracked - is replaced by a per-underlying cap (8% of equity), joining the
per-position (5%) and portfolio (15%) caps. Three caps, three distinct meanings, all in dollars
of defined max loss. The proxy punished an uncorrelated fourth position exactly as hard as a
fourth position in the same name; the explicit cap permits diversification and refuses
concentration, which is the behaviour that was actually wanted.
**Stated vs enforced (F1's root cause) is now visible:** `watched_signals()` reports which
signals a position's rules read, and `record_position` returns it - warning explicitly when a
position watches only the mark. Reporting, not gating (D-009): observability beats a veto.
**Verified:** 10 exit scenarios incl. both old bugs (wide-quote debounce, decisive underlying
break with a healthy mark, per-rule debounce isolation, stop-beats-target, missing signal holds,
legacy rule shapes, immediate time stop, implicit deadline, deadline outranking a target);
6 sizing scenarios (concentration refusal, diversification permitted, portfolio refusal,
shrink-to-fit, the uncorrelated-fourth case the old divisor punished); 4 derived-risk scenarios
incl. the model omitting `max_loss_usd` entirely ($3,600 derived correctly). Tick 25 clean.
**Applied to the live position:** the open SPY spread was the F1 case in the flesh - the agent
had narrated "invalidated on a decisive break below ~757-758" while its rules watched only the
mark. Added `underlying_stop below 757.5`, encoding what it had already said. Backup at
scratchpad/pos_backup.md.

## D-038: Detect silent failures systematically - health probe, null-path evidence, regression tests
**Date:** 2026-08-27
**Status:** accepted
**Context:** The same *shape* of bug had appeared six times: the system kept running, the logs
kept reading healthy, and something was quietly doing nothing. `attribution._spot` dead for
days; `Sensor.policy` declared and never read; the `opening` status never wired; bars six weeks
stale; 8 interim scores accumulating; `max_loss_usd` absent counting as zero risk. Each was
found by accident. Taxonomy of the six classes with detection questions in
[notes/012](notes/012_failure_classes.md).
**Three mechanisms, in order of what they catch:**
1. **`trdrbot health`** - a data-driven probe table asking of every subsystem *ran >= threshold
   and produced nothing?* `doctor` answers "can this system start"; health answers "is it doing
   anything". It found a real problem on its first run: the live position had no `max_loss_usd`
   and so counted as ZERO risk against the book caps, silently loosening them (backfilled to
   $2,210). It also checks positions for mark-only exit rules and unscoreable theses. Reports,
   never gates (D-009).
2. **Instrument the null path.** `attribution.run()` had a bare `continue` on a failed price
   lookup - no journal entry, so "never ran" and "ran, found nothing" were indistinguishable,
   which is exactly how it stayed dead. It now always emits `attribution_run` with
   pending/attributed/skipped_no_price. **Rule: any early exit meaning "nothing happened" must
   leave evidence saying why.**
3. **`tests/test_regressions.py`** - 31 tests, one per bug that actually reached running code,
   each named by its decision record, all pure and offline. **A bug is not fixed until the test
   that would have caught it exists.** This session had been verifying fixes in throwaway shell
   snippets, which protects nothing against the next edit; those checks are now permanent.
   `_plausible_band` was extracted from `discovery.run` so the D-035 unit-confusion check is
   testable rather than buried inline.
**The mechanism that has caught the most, unplanned:** two independent paths computing the same
quantity with the disagreement surfaced. The stale-bars bug died because the decide cycle
checked research's numbers against live quotes and said so out loud; the bootstrap-drift bug
died because a convergence test compared two estimators that should have agreed. Where a second
opinion is cheap, compute it and journal the delta.
**Evidence:** `trdrbot health` output before and after the backfill; 31 passing tests incl.
three that test the detector itself (flags zero-risk position, flags run-but-never-produced,
stays quiet while a subsystem is merely young).

## D-039: The first-ever position has no thesis and can never be attributed
**Date:** 2026-08-27
**Status:** accepted (documented gap, not fixed - see below)
**Context:** User asked "why no thesis horizon has arrived?" - investigating the honest answer
surfaced a second, more serious fact hiding behind the first. The open SPY position (tick 1,
2026-08-26, the system's very first trade) has `thesis_claim: ''`. Its tool-call sequence was
`get_option_chain -> place_option_order -> record_position` with `simulate_experiments` never
called in between, so the `shared["thesis"]` that `record_position` reads was never populated.
This is worse than an unfalsifiable thesis (which at least attempts scoring and gets marked
unscoreable): this position **can never be attributed at all**, silently, because
`attribution.pending()` filters on `thesis_claim` being truthy.
**Why `trdrbot health` (D-038) missed it on its first run:** the band-check only fired when
`thesis_claim` was already truthy - an empty thesis skipped the check entirely and surfaced only
as the vaguer "attribution never ran" warning, which is also true for the mundane reason that no
position has closed yet. Two different causes, one indistinguishable symptom.
**Fix:** `health.check()` now flags a missing thesis as its own BAD finding, ranked above the
weaker unfalsifiable-thesis WARN. `record_position` now detects the same condition live and
returns an explicit note: "no thesis on file - simulate_experiments was not called... this
position can NEVER be scored." Reporting, not enforcement (D-009) - the position is not
retroactively fixable (no thesis was ever formed to attach), so the fix is visibility for every
position from here forward, not repair of this one.
**Left as-is, deliberately:** this specific position is not backfilled with an invented thesis.
Fabricating one after the fact would be worse than the gap it patches - it would look like an
attributed judgment where none exists, exactly the kind of manufactured signal this project's
attribution machinery exists to prevent. It remains a known, visible, permanent gap in the
learning record: one trade this loop cannot learn from.
**Evidence:** journal `jrn_20260826T185911Z_exe9276`, tool_calls confirms simulate_experiments
absent from the sequence; live `trdrbot health` before/after; 2 new regression tests.

## D-040: The greeks layer - risk shape as a first-class input
**Date:** 2026-08-27
**Status:** accepted
**Context:** The system simulated only TERMINAL outcomes (payoff at expiry, P(profit), EV) -
zero intra-life sensitivity anywhere. The agent reasoned about risk shape qualitatively
("doubling the same factor exposure", "short-strike delta 0.239") with numbers it gleaned from
chain quotes. Judging explicitly scores options-strategy sophistication, and risk shaping IS
the substance of multi-leg trading (docs/sources/multi_leg_and_greeks_explained.md).
**Choice - compute, don't fetch:** Black-Scholes closed form in optmath (r=0; rho deliberately
absent - at <=7 DTE its effect is cents and pretending otherwise is precision theatre). Chosen
over reading Alpaca chain greeks: zero new inputs, works offline and in tests, and the
exact/modelled split stays honest - we know which assumptions produced every number. Greeks are
MODELLED-layer citizens with the same refusal discipline as the rest of optmath: 0 DTE or 0 IV
returns None (an expiring option has a cliff, not smooth sensitivities), and one unpriceable leg
makes the whole POSITION's shape None (a partial sum is silently wrong - INV-19's reasoning).
**What was added, each verified:**
1. **`net_greeks` in trader units** - delta$ (direction in money), theta$/day (time income or
   cost), vega$/IVpt (vol exposure), gamma sh/$ (delta instability). Per-leg `iv_pct` honoured:
   the agent has measured 16.5%-vs-7.4% put/call skew live, and a flat surface erases exactly
   that observation - selling the rich side IS the trade, so measure it.
2. **GREEKS row in `simulate_experiments`** - shape sits between MODELLED and HISTORY for every
   candidate; short gamma with <=2 DTE renders a pin-risk warning (surfaced, never gated).
3. **Expected move vs thesis band** in the comparison header - the first professional sanity
   check: a band inside the market's 1-sigma move is agreeing with the market and paying for
   the privilege. Rendered from inputs already present.
4. **Entry greeks stored on the position** - derived (OCC-parsed executed legs priced with the
   market params simulate stashed in `shared`), not declared, same pattern as D-037's risk.
5. **Book greeks in every decide context** - open positions re-priced at current spot and DTE
   with entry IV (the one labelled staleness). Partial books sum with a skipped count: a
   partially-priced BOOK is informative where a partially-priced position is not. This is what
   turns "three bullish put spreads on three tickers are one +delta/-vega/+theta position" from
   a sentence into a number the agent sees before adding a fourth.
6. **Prompt playbook** - match shape to thesis (range view = theta income; breakout = own
   gamma; vol view = vega trade), check the book first, expected-move comparison, final-two-days
   gamma discipline, per-leg IV for skew.
7. **Dual-window realized vol** (21d + 5d) after the live decide cycle caught the desk citing
   21d vol against a market pricing the last few days - both were right, the WINDOW was the
   disagreement; now both render and the guess is removed.
**Verified:** put-call delta parity at r=0; bull put spread = +delta/+theta/-vega; long straddle
= flat delta/+gamma/-theta/+vega; ATM gamma 2.6x from 7 DTE to 1 DTE (the pin-risk warning
rests on a real effect); skew-aware vega diverges from flat; refusal on 0 DTE/0 IV; OCC parse
round-trip; book aggregation with legacy positions skipped-and-counted. 42 regression tests
pass. Live forced tick 27 ran clean; the agent declined on stale pre-open quotes - correctly.
**Parked:** beta-weighted book delta (over-engineering for a 3-5 name book); IV-rank store
(F8 stands); intraday P&L attribution by greek (post-hackathon).

## D-041: The epistemic constitution, seeded into elfmem's SELF frame
**Date:** 2026-08-27
**Status:** accepted
**Context:** Implements [notes/009](notes/009_epistemic_constitution_plan.md) (mechanism) and
[notes/010](notes/010_constitutional_blocks_brainstorm.md) (the ten ratified principles).
elfmem updated to `elfmem_index` HEAD (8a38bba3) first; every load-bearing fact re-verified on
the new build.
**What elfmem actually provides, verified not assumed:** `determine_decay_tier` grants PERMANENT
decay (~34yr half-life) to any block tagged `self/constitutional`; `SELF_FRAME` guarantees those
blocks slots, is queryless, and has `token_budget=600`; `review_constitutional` PROPOSES and
`accept_amendment` applies, deliberately separate, with ADR 0003 cited in its own docstring as
the reason. The plan drafted before reading the library matched the library.
**Deliberately NOT used: `setup(seed=True)`.** It seeds ten domain-neutral personality blocks
("I am elf - a curious, adaptive cognitive agent"), which is exactly the platitude class
notes/010 cut. Our ten are incident-traced and displace nothing we would rather have.
**Four silent gates between "seeded" and "visible", each found by checking rather than trusting
the success message:**
1. **Inbox.** `remember()` reported ten successes while `frame("self")` rendered NOTHING - SELF
   blocks queue until consolidation. Stored is not visible.
2. **Consolidation rewrites content.** The LLM turned terse imperatives into third-person
   description - faithful, but ~2x the tokens, which pushed five principles past the budget
   where the greedy renderer drops them in silence. Fixed with `host_analyses`: we supply the
   summary, so principles land in the words they were ratified in, at the measured token cost,
   and at zero LLM cost.
3. **Batch cap.** `consolidate()` processes at most 5 per call (ADR 0007). Submitting ten in one
   `host_analyses` dict does not queue the surplus - it gets LLM-analysed on a later pass,
   silently reinstating the rewriting. Detectable only by inspecting tags: LLM-analysed blocks
   carry inferred `self/value` tags we never supplied. Batches are now capped and progress is
   measured by what LEAVES the inbox, never by what was submitted.
4. **`top_k` defaults to 5.** The decide cycle would have rendered FIVE of ten principles and
   said nothing about the rest - the agent holding half a constitution without knowing.
   `assemble_context` now requests `len(PRINCIPLES) + 4` for the SELF frame.
**Token discipline:** principles were measured at 499 tokens before trimming, against a 600
budget the template also draws on. Trimmed to imperative cores (rationale lives in `traces_to`,
for humans) at 351 tokens; the frame now renders all ten at 501 with headroom.
`CONSTITUTION_TOKEN_CEILING` and a regression test keep it there.
**`trdrbot constitution show|seed|reseed|verify|review`.** `verify` is the important one: it
asserts the frame ACTUALLY RENDERS every principle, because counting stored blocks proves
nothing - three of the four gates above passed a naive count. `review` proposes and never
accepts; ratification is a human act (principle 10).
**Honest limitation for the competition:** `review_constitutional` cannot fire inside the
8-day window - its defaults require blocks >= 30 days old and >= 20 recently-reinforced blocks.
The amendment path is real, wired and demonstrable, but it will report `insufficient_history`
until well after the deadline. That is correct behaviour, not a gap: churning principles on
eight days of data is the overfitting notes/009 warned about.
**Self-test wired:** the decide prompt now asks the agent to name the ONE principle its current
reasoning is most at risk of violating - what makes the constitution operative rather than
decorative (notes/009 §2).
**Evidence:** live `constitution verify` renders 10/10 at 501 tokens; `assemble_context` in the
real decide path contains 10/10; 45 regression tests pass.

## D-042: Scaffold run at the open - three dead paths found, plus the scheduler
**Date:** 2026-08-27
**Status:** accepted
**Context:** Full-system scaffold simulation at the 09:30 ET open, with the specific brief of
checking that the system records what it learns and recalls and acts on it. Three of the
findings were dead code paths that every unit test passed.
**1. `underlying_stop` exit rules were INERT in production.** The live-trade response nests
under `trades` (`{"trades": {"SPY": {"p": 767.46}}}`), not under the symbol. The parser looked
one level too shallow, found nothing, and left `underlying_prices` EMPTY **without raising** -
so the thesis-invalidation stop built in D-036 and unified in D-037 could never fire. Every
unit test passed because the tests supplied the price map directly. The most important risk
control in the system was decorative for a day. Fixed; verified live: SPY 767.61 against a
757.5 stop, ARMED. Regression test now uses a REAL captured response, not a hand-built dict.
**2. Trade outcomes were credited to the constitution.** `all_elfmem_block_ids` flattened ALL
frames including `self`, so `resolve()` would push trade P&L signal onto all ten constitutional
principles - and since they carry PERMANENT decay, damage would never wash out. Split into
`all_elfmem_block_ids` (task + attention, credited) and `recalled_block_ids` (all frames,
provenance only). Principles are scored by human-ratified incident review (D-033), never by P&L.
**3. The constitution had crowded out learned knowledge.** Constitutional blocks are
semantically close to almost any reasoning query AND never decay, so they dominated ATTENTION:
10 of 12 hits were principles (0.77-0.96), and after de-duplicating against SELF the frame
returned NOTHING - the agent's own market knowledge entirely displaced by its own identity, one
day after seeding it. ATTENTION now builds from `recall()` with over-fetch and cross-frame
dedupe. Verified: the agent's stored MU note and its own prediction now reach the decide cycle.
**4. The system was purely reactive** - an empty inbox meant no reasoning, even with the market
open and a live position moving. Found at the open: equity had moved and the agent did nothing
because no headline had arrived. Added the **market pulse**: a material move (0.4%) in a held
underlying, or 90 minutes of silence while holding risk, is itself an observation and wakes the
decide cycle. Deliberately silent when nothing is at risk.
**5. Principles were cited by unstable number.** The SELF frame orders by how load-bearing each
has proven, so numbering shifts between cycles - the agent cited "Principle 10" for what is
principle 3. Prompt now requires citing by opening words.
**Scheduler:** `trdrbot run --interval 300 --closed-interval 1800`. Two cadences because the
work differs: open runs decide/pulse/exit-rules (stops checked hourly are worthless), closed
runs housekeeping/research/attribution/consolidation (daily by nature, and they cost LLM calls).
A failing tick never stops the loop (INV-8) - over eight unattended days provider transients are
certain, and a crash that halts trading is worse than a journalled skipped tick.
**Evidence the loop is closed, from the live open-market decide cycle:** the agent recalled its
own stored note ("my stored note is bullish on DRAM/HBM ASP repricing"), applied a principle by
name ("I'm marking the tension rather than resolving it in my own favour" - the contradictions
principle), read its book greeks ("a book already carrying +$29.9k delta"), enforced its own
pre-registered rule ("skip entirely if the ATM straddle prices materially above 9-10%" - it
priced at 12.5%, so it skipped), and killed a thesis on a stale premise (its note said MRNA
142.57; the tape said 145.48). 48 regression tests pass.

## D-043: The idle ladder - what to do when nothing has happened
**Date:** 2026-08-27
**Status:** accepted
**Context:** With an empty inbox the system did nothing, even with the market open and a live
position. The naive fix is "run every analysis every tick" - which is the amateur answer:
re-underwriting the market every five minutes costs LLM spend, burns context, and manufactures
activity. A professional's day is a ladder, and the rung is chosen by what changed and by what
is at risk.
**Choice (`idle.py`), cheapest rung first:**
- **L0 sleep** - nothing at risk, nothing moved, looked recently. Free, and usually correct.
- **L1 health** - deterministic per-tick work that already runs: reconcile, exit rules, greeks.
- **L2 review** - a material move (0.4%) under a held underlying, or 90 minutes of silence
  while holding risk. One LLM call.
- **L3 hunt** - capital idle and deployable: run discovery for fresh, LIVE-priced candidates.
**The asymmetry that sets the thresholds:** the cost of NOT looking scales with what is at
risk; the cost of looking scales with LLM spend. A full book on a quiet tape is left alone -
stops already guard it and churning donates edge to the spread. An empty book is the opposite,
and the case this system kept getting wrong: **idle capital is a position too, 100% cash at 0%
expected return, and against a deadline that is a decision to be justified, not defaulted into.**
**Intraday opportunity generation (L3) closes the real gap:** every candidate the agent had seen
was researched while the market was CLOSED, and it declined them on exactly that basis - "any
spread I priced now would be simulated on prices that no longer exist". Hunting now happens
in-session against live quotes.
**Edge cases, each mitigated deterministically:**
- *Hunting while the book is full* - gated on remaining risk budget. Do not hunt when you cannot
  shoot: candidates sizing will refuse are spend with no possible outcome.
- *Churning* - 120-minute hunt cooldown; news does not turn over faster than that.
- *Opening risk into the close* - refused inside 30 minutes of the bell: fills are worst into
  the close and an overnight gap cannot be reacted to.
- *Stale candidates lingering* - opportunity items expire from the inbox after 180 minutes and
  are journalled. Only opportunities expire; news and fills are history and stay valid.
- *Flapping on noise* - the 0.4% move threshold is ~1/3 of a typical index daily range.
**Also fixed here: interim marks were resolving the mind prediction.** `mind_outcome` takes a
binary hit with no weight, so every interim score recorded a full MISS - live, the SPY mind sat
at `confidence=0.34, hit/total=0/1` on a position that was profitable and whose horizon had not
arrived. `resolve(interim=True)` now scores blocks at low weight and leaves the mind alone; a
prediction is right or wrong once, at its horizon.
**Verified:** 8 ladder scenarios (sleep/review-on-move/review-on-silence/hunt/cap-full/cooldown/
near-close/market-closed), 57 regression tests, and live at 09:59 ET - "idle -> sleep: positions
healthy, tape quiet, looked recently".

## D-044: A stray smoke-test loop hammered the API for half an hour
**Date:** 2026-08-27
**Status:** accepted
**Context:** Starting the production run loop found a leftover `trdrbot run --interval 5` still
alive from an earlier smoke test - polling the broker every 5 seconds and burning LLM calls,
unnoticed, for roughly half an hour.
**Root cause was six compounding failures, none of them bad luck:**
1. `kill %1` targeted the backgrounded PIPELINE job, not the `uv run` -> python child, which was
   orphaned and reparented rather than killed.
2. No process-group kill (`pkill -P` / `kill -- -PGID`), so the tree survived its parent.
3. No PID file, so later cleanup was guesswork against `pgrep` output.
4. Death was never verified - "smoke test done" was printed without checking.
5. Piping into `head -8` should SIGPIPE upstream, but a buffered `uv run` need not die from it.
6. **`timeout` does not exist on macOS.** `timeout 200 uv run ...` returned exit 127 (command
   not found) and the safety net I believed I had silently did not exist.
**Choice - make the class structurally impossible rather than remembered:**
- **Singleton lock.** `trdrbot run` writes `logs/run.pid` and refuses to start when that pid is
  alive. A stale lock (recorded process gone) is taken over rather than treated as fatal - a
  crashed loop must not require manual cleanup before trading can resume. A corrupt pid file is
  also taken over. Deliberately reuses the pid file already written by the live loop, so the
  currently-running process is protected retroactively.
- **Interval floor.** `MIN_INTERVAL_SECONDS = 30`, overridable only with `--allow-fast`. No
  legitimate reason exists to poll a live broker faster, and the floor bounds the blast radius
  of the mistake even when process cleanup fails. This alone would have prevented the damage.
- **`--max-ticks N`.** Smoke tests terminate themselves rather than depending on an external
  kill that may target the wrong process. The original failure was in the *cleanup*, so removing
  the need for cleanup is the more reliable fix.
**Operational hygiene alongside the code:** the production loop now writes a PID file, logs to
`logs/current.log`, and its liveness was verified after start rather than assumed.
**Verified:** second loop refused against a live pid; stale and corrupt locks taken over;
`--interval 5` refused with a clear message; `--max-ticks 1` self-terminated. 61 tests pass.

## D-045: Prompt inventory and fingerprinting - provenance now, variants later
**Date:** 2026-08-27
**Status:** accepted
**Context:** How many prompts does this system have, and should they move to a `prompts/`
directory as templates for future A/B testing?
**Measured: 8 artefacts, ~3,140 tokens.** They are NOT homogeneous, and that is the whole
answer - "put all prompts in a directory" is the wrong shape because three kinds behave
differently:
- **free-standing (4, ~1,684 tok)** - `decide.system`, `research.daily`, `discovery.nominate`,
  `discovery.synthesise`. Pure text; nothing but an LLM reads them. Safely extractable.
- **tool contracts (3, ~1,100 tok - a THIRD of the surface)** - the `simulate_experiments`,
  `size_position` and `record_position` docstrings. Each is the documented contract of a live
  function signature. Extracting one lets the description drift from the parameters it
  describes: this project's most familiar failure class, a thing that reads correct and
  silently is not. These stay next to their functions.
- **ratified (1, ~356 tok)** - the constitution, already external in elfmem with human
  ratification and its own change control (D-041). It must not acquire a second home.
**Why P&L cannot be the A/B metric, and this is decisive:** the project's own power calculation
(notes/007) shows a genuinely 60%-edge agent beats a coin flip only 69% of the time over 20
trades, with a zero-skill range of -7.8%/+8.2%. We will resolve perhaps 5-15 trades. Two prompts
**cannot** be distinguished by returns in this window - not "hard to", cannot. An A/B on P&L
would measure noise and crown a winner.
**What CAN be measured are behaviours, which accrue per CYCLE rather than per trade** (50+
decide cycles against ~10 trades - the sample-size problem solves itself at this level):
process compliance (simulated before recording? >= 2 genuinely different candidates? an
`underlying_stop` set? a principle cited by name?), cost (tokens, tool calls), decisiveness
(trade vs refusal rate), error rate (malformed calls, rejected opportunities), and - slowest but
truest - calibration (Brier of stated confidences at resolution).
**Choice: build the provenance, defer the machinery.** Every decision now journals
`prompts={name: fingerprint}` (sha256[:8] of the exact text). This is the only part with a
deadline: **a decision recorded today without a prompt label can never be compared against
tomorrow's.** The variant registry, assignment and reporting can all be built later against
already-labelled history; provenance cannot be backfilled. Consistent with the project rule of
adding machinery when a concrete need justifies it, never in anticipation.
**`trdrbot prompts`** renders the full inventory with fingerprints and token counts.
**Deferred deliberately:** a `prompts/` directory, variant assignment, and the comparison
report. Trigger to build them: a genuine second variant worth running, which does not exist yet.
**Evidence:** measured inventory; 62 tests pass.

## D-046: The agent reached for a whole-book liquidation
**Date:** 2026-08-27
**Status:** accepted
**Context:** Closing out the first live position, the agent called
`close_all_positions(cancel_orders=True)` - which liquidates the ENTIRE book - intending to
close one spread, then followed it with a separate `sell_to_close` on the long 750 leg the
sweep had already closed. The account ended flat and profitable (+$190), but only because of
fill sequencing: had the second order rested and filled, it would have opened a **naked short
put**, the exact unbounded-risk structure sizing refuses to size (D-030) and exit rules exist
to prevent (INV-19).
**Choice:** `close_all_positions` is refused while more than one position is open, with a
message naming the correct instrument (`close_position` per symbol, for every leg). With a
single position open it is equivalent to a legitimate close and passes through untouched.
**Why this is not a guardrail (D-009):** it vetoes no view, blocks no strategy and gates no
judgment. It refuses ONE instrument whose blast radius exceeds any single-position intent. The
agent may still flatten the entire book - one position at a time, deliberately. Same category
as `tool_guard`'s existing client_order_id enforcement: correctness plumbing, not policy.
**Evidence:** journal execution 14:46:24 (`close_all_positions` then a separate leg sell);
broker flat at $100,181.18 with zero open orders; regression test covering both the multi-
position refusal and the single-position pass-through.

## D-047: Phased risk posture - breaking the sizing deadlock
**Date:** 2026-08-27
**Status:** accepted
**Supersedes:** the F6 deferral in [notes/011](notes/011_trader_review.md) ("revisit ~Sept 1").
The evidence arrived early and is stronger than expected.
**The deadlock, measured not guessed:**
```
resolved trades   n=0  n=3  n=5  n=7  n=8  n=12
contracts sized     0    0    0    0    0     1
```
With no track record the probability shrinkage pulls a stated 70% back to the base rate, Kelly
on a typical 0.67:1 payoff lands at exactly 0.000, and the system **can never place the trade
that would build the record it needs in order to be allowed to trade.** Eight days of 0% is not
risk discipline; it is a formula returning zero with nobody checking. Live calibration is n=0 -
our one closed trade carried no thesis (D-039) - so this was the actual trajectory.
**The insight that resolves it: size and learning rate are independent here.** Learning comes
from the NUMBER of resolved theses, not their size, and survival is guaranteed structurally by
defined-risk legs plus a book cap - not by sizing small. So a tiny size buys no extra safety and
no extra learning; it only shrinks the result. A desk does not hand a new trader zero, it hands
them a bounded exploration allocation and expects to pay for the information.
**Three phases, two independent gates that must BOTH permit** (tightest binds, exactly as the
three risk caps already compose):
- **VALIDATE** (>5 days left, or n<8): fixed 2.2%-of-equity exploration allocation, deliberately
  NOT Kelly - we do not trust the edge MAGNITUDE yet. The go/no-go gate uses the agent's STATED
  confidence rather than the shrunk one, because shrinking to base rate and then demanding
  Kelly>0 is precisely what made a first trade impossible.
- **DEPLOY** (2-5 days AND n>=8): Kelly with a continuous evidence ramp, 20% book cap.
- **HARVEST** (<2 days): no NEW risk - a position opened now cannot resolve, and an unresolved
  position at the deadline is closed at whatever the book offers.
**Continuous ramp replaces the n>=8 cliff:** `mult = unproven + (established-unproven)*n/(n+6)`,
the same shrinkage shape already used for probabilities. Under the old gate the 8th resolved
trade was a bigger step than every trade before it combined.
**Indivisible contracts.** Kelly on a mediocre payoff routinely lands below one contract (0.9%
of equity on a 0.67:1 at 62%), and rounding that to zero made an EARNED record size *smaller*
than the unproven exploration allocation - the ladder inverted. A desk takes one contract or
none. One is now the floor when the edge is positive; the book caps still bound above, and the
per-position ceiling still refuses anything genuinely too large for the account.
**Drawdown throttle:** below a 3% drawdown from the equity high-water mark the book cap scales
down toward a 25% floor. A losing streak is evidence the current regime is not the one the
record was earned in.
**Regime deliberately NOT a separate term:** the agent's stated confidence already reflects the
regime it can see, and sizing already shrinks that confidence by measured calibration. A second
regime multiplier would double-count the same information.
**Verified:** 9 new tests - first trade now possible at n=0; ladder monotonic in evidence;
HARVEST refuses; both gates required for DEPLOY; ramp continuous with no step >3%; drawdown
throttles the cap; book cap still binds at $19.5k; a genuine 3:1 edge scales to 4 contracts; an
oversized position still refused. 71 tests pass. Posture is journalled every decide cycle and
rendered into the prompt.

## D-048: Size earned by competence, not by the calendar
**Date:** 2026-08-27
**Status:** accepted
**Supersedes:** D-047's deadline-phased posture (the deadlock diagnosis stands; the phasing does not)
**Context:** D-047 keyed the risk budget on days-to-deadline. The bot will keep running after
this competition, and that design had a bug waiting for the day after: once `days_left` went
negative it entered its no-new-risk phase **permanently and would never trade again**. Worse, it
was conceptually wrong - a desk does not scale a trader by the date.
**Choice: a competence ladder climbed by demonstrated skill, with the calendar removed entirely
from sizing** (there is a test asserting `assess()` contains no date logic at all):

| tier | requires | book cap |
|---|---|---|
| EXPLORE | nothing - the starting allocation | 10% |
| ESTABLISH | >=5 resolved theses | 15% |
| SCALE | >=15, reliability <0.05, >=60% attributable | 20% |
| MATURE | >=40, reliability <0.03, >=70% attributable | 25% |

**Attribution is a promotion criterion, not just a metric** - the distinctive part. A profit on a
wrong thesis is luck, and a book of luck is not competence however good the P&L. Promotion past
ESTABLISH requires that most resolved theses were ATTRIBUTABLE - that the agent knows *why* it
was right. Verified: 15 resolved that are mostly lucky wins, or mostly unscoreable, both stay at
ESTABLISH; 15 understood reach SCALE. This is "level of understanding" made measurable, and it
is the honest thing for a size ladder to key on.
**Asymmetric by design:** promotion needs a sustained record; demotion is immediate - one tier
down at 5% drawdown, all the way to EXPLORE at 10%, recovering when equity does. A losing streak
is evidence the regime has moved out from under the record, which is the "regimes" principle
applied to the agent's own competence.
**The deadline did not disappear** - it became a POSITION-level horizon check (`can_open`):
can this specific trade resolve before a hard stop? That fires for a competition deadline or a
planned shutdown and is inert in normal operation, which is where it belongs.
**The scaffold found a second ladder inversion.** Promotion from EXPLORE to ESTABLISH at n=5
took sizing from 1 contract to **0**: competence promotes at 5, but `shrink_probability` applies
a blunt "halve the claimed edge" heuristic below MIN_SAMPLE=8, driving Kelly to exactly zero.
Fixed at the root: **below MIN_SAMPLE the shrinkage sizes down, it never vetoes** - it is a
heuristic, not a measurement. A monotonicity test now runs the whole ladder and asserts more
evidence never means less size; two separate inversions have now been caught by it.
**Multi-symbol confirmed working end to end:** at SCALE with a $20k book cap, sizing filled
SPY/NVDA/CRM/META to $19.1k and then refused; exit rules fire per position (CRM breaking its
thesis level closed CRM alone, SPY and NVDA untouched); one price fetch covers every held
underlying; book greeks aggregate across all of them. The per-underlying cap actively rewards
diversification and refuses concentration.
**Verified:** 72 tests, incl. monotonicity across n=0..100, luck/unscoreable blocking promotion,
poor calibration blocking promotion despite volume, drawdown demotion and recovery, the
no-calendar assertion, hard-stop position checks, and multi-symbol book behaviour.

## D-049: Principles carry their name in the block; ATTENTION returns to frame()
**Date:** 2026-08-27
**Status:** accepted
**Context (citation):** The agent cited "Principle 10" for what was principle 3. The SELF frame
numbers its blocks and **re-orders them by how load-bearing each has proven**, so a number
refers to nothing stable and means a different principle next cycle. Telling it in the prompt to
cite by wording did not work - the rendered list still presented numbers and nothing else.
**Choice:** put the name inside the block: `[regimes] A pattern learned in one regime is...`.
The only handle worth citing is the one the agent can actually see. Costs ~32 tokens; the
budget guard caught the overrun against the 380 ceiling on the first test run (which is what it
is for) and the ceiling moved to 430, still comfortably inside the frame's 600.
**Context (ATTENTION):** elfmem d86e6d6 fixes the partial-exclusion leak reported in
`frames_and_credit_assignment_report.md` - constitutional blocks no longer reach ATTENTION at
all. Verified live: 0 leaked, 0 in the dropped list, `excluded_by_filter=10`.
**Choice:** revert the hand-rolled recall+dedupe workaround and use `frame("attention")` again,
regaining the frame template and its TTL cache. The cross-frame dedupe stays as cheap
belt-and-braces.
**Verified:** 72 tests; 10/10 named principles render in the real decide context; ATTENTION
carries the agent's own learned blocks (its SPY position note and mind model) rather than its
identity.

## D-050: Our calibration scorer was penalising a perfect forecaster
**Date:** 2026-08-27
**Status:** accepted
**Context:** Web research (Ferro & Fricker, QJRMS 2012) flagged that the empirical Brier
decomposition **overstates reliability at small n** - each bin's observed frequency is itself
estimated from few outcomes, and its sampling variance lands in the reliability term. Checked
against our own scorer rather than taken on trust, by simulating a PERFECTLY calibrated agent
(true reliability = 0):

| n | measured reliability | SCALE gate (needed <0.05) | MATURE gate (needed <0.03) |
|---|---|---|---|
| 15 | 0.072 | blocked 67% | blocked 83% |
| 20 | 0.061 | blocked 58% | blocked 83% |
| 40 | 0.027 | blocked 10% | blocked 33% |

A flawless agent was denied promotion most of the time by a **phantom penalty**. Worse, the bias
shrinks as n grows - so it would have looked exactly like "the agent is learning" while nothing
had changed. This was a live defect in the competence ladder shipped hours earlier (D-048).
**Fix 1 - Ferro-Fricker bias correction.** The unbiased estimator of p(1-p) from m samples is
m/(m-1)·o(1-o), so the variance leaking into each bin is o(1-o)/(m-1). Subtract it from
reliability, adjust resolution and uncertainty correspondingly, clamp at zero. Perfect-agent
reliability at n=15 fell 0.072 -> 0.024.
**Fix 2 - adaptive binning.** Fixed 0.1-wide bins leave ~4 forecasts per bin at n=20, and a bin
of ONE cannot have its sampling variance estimated at all, so it escapes the correction and
re-imports the bias. Bins now target ~8 forecasts each, between 2 and 10 bins.
**Fix 3 - gate only where the statistic discriminates.** Measured after correction: at n=15-20 a
perfect agent scores 0.022 and a badly overconfident one (says 80%, right 55%) scores 0.038 -
**overlapping distributions**, so any threshold there rejects good agents and passes bad ones at
similar rates. At n>=40 the separation is real: perfect blocked 2%, bad blocked 92%. So the
reliability gate moved to MATURE only (n>=40, <0.04); SCALE now gates on sample size and
attribution alone. **Gating on a statistic before it can discriminate is theatre that costs real
size.**
**Verified:** 4 new tests - a perfect forecaster is not penalised at n=20; a genuinely
overconfident one still scores 3x higher at n=60; the gate exists only where it discriminates;
reliability is never negative. 76 tests pass.

## D-051: Volatility clock and implied daily move
**Date:** 2026-08-27
**Status:** accepted
**Context:** Two items from the technique research ([docs/sources/trading_techniques_review.md](../docs/sources/trading_techniques_review.md)).
**1. The volatility clock.** Black-Scholes counted calendar days; volatility does not accrue when
the market is shut. Weighting a weekend/holiday day at 0.5 gives a ~308-day year. **At 30 DTE
this is a rounding error; at our 2-10 DTE it dominates.** Measured: 3 calendar days from a Friday
is **2.00 vol days, a 50% overstatement**, which moved the expected move the thesis band is
checked against from $9.88 to $8.07 and theta by 22%. An unadjusted clock also manufactures a
spurious IV jump every Monday. Corroborated independently: removing Friday->Monday positions from
a 1DTE SPX put-write study (Mar 2018 - Sep 2025) cut cumulative return from 28.07% to 8.94% -
about two thirds of all profit came from weekend-spanning trades, which is what over-counting
weekend time looks like from the other side. Theta is still quoted per CALENDAR day, because that
is what a holder actually experiences.
**2. Implied daily move (gamma breakeven), and a correction to the source.** `sqrt(2|theta|/|gamma|)`
was recommended as a structure-selection guard. **It is not one, and the sources claiming it is
are wrong.** Measured: at a flat 13% IV a short put spread, a long straddle and an iron condor all
return $5.21, because theta/gamma is the same Black-Scholes identity for every position at one
spot and one vol. What it actually returns is **the daily move implied by IV in dollars** ($3.21
at 8% IV, $14.03 at 35%), varying between structures only through skew. That makes it useful for
exactly one thing, which is the important thing: **compare it against the underlying's realised
daily range.** Above realised, short premium is being paid for; below, it is being donated. It is
the implied-vs-realised edge test denominated in dollars a day - the same test as an
IV/forecast-RV ratio, in units the agent can check against the tape directly. Rendered on every
candidate with that instruction in the prompt.
**Verified:** 4 new tests, incl. one asserting the breakeven does NOT discriminate structures, so
nobody re-adds that belief later. 80 tests pass.

## D-052: Pre-registration ledger and unconditional forecasts
**Date:** 2026-08-27
**Status:** accepted
**Context:** Two findings from the technique research that turn out to be one mechanism -
**record the forecast even when you do not act on it.**
**Why pre-registration:** a human quant tests ~20 ideas a year; an LLM generates 200 plausible
theses in an afternoon and silently discards the ones that look bad. Under a TRUE Sharpe of
zero, the expected maximum Sharpe across N filtered trials is 1.19 sigma at N=5, **1.90 at
N=20**, 2.53 at N=100 - and the competence ladder (D-048) would promote it. The ledger supplies
the trial count N without which a Deflated Sharpe Ratio is uncomputable. It cannot be
reconstructed later, which is the whole point.
**Why unconditional forecasts:** size is gated on measured calibration, and the honest
thresholds are ~50 resolved forecasts before calibration is measured rather than guessed, 152
before a 60% hit rate is distinguishable from a coin flip. At 1-5 concurrent positions,
trade-level observations will never get there. But a forecast on a setup we DECLINE costs
nothing and scores the same judgement. The agent had already declined ~10 times with detailed,
falsifiable reasoning that was thrown away.
**The design decision that matters: pre-registration is AUTOMATIC.** Every thesis passed to
`simulate_experiments` is registered from inside the tool - the agent cannot forget it, cannot
skip it under pressure, and pays no extra prompt burden. Same derive-don't-declare principle
that made position risk trustworthy (D-037). A separate `record_forecast` tool exists for
standalone views the agent wants on the record.
**Refusal at write time:** a forecast with no price band could never be scored, so it is
rejected rather than stored. Counting an unjudgeable thesis would make the multiple-testing
correction *more* punitive for no informational gain. Repeat registrations of one thesis within
a cycle are de-duplicated, so comparing structures twice does not inflate N.
**Resolution:** matured forecasts are scored against the tape at housekeeping and flow into
`CalibrationStore.score(extra=...)`. Verified end to end: 4 theses registered (1 traded, 3
declined), 3 matured and resolved against real prices, calibration **n=0 -> n=3 from trades we
never made**. `trdrbot ledger` reports trials/traded/declined/resolved and the hit rate.
**Verified:** 6 new tests. 86 pass.

## D-053: Our research universe was one bet wearing three hats
**Date:** 2026-08-27
**Status:** accepted
**Context:** Asked whether to add symbols. Measured the correlation of daily returns over the
last ~120 sessions before answering:

```
        SPY    QQQ   NVDA    XLE    GLD    TLT    XLV    XLP
SPY    1.00   0.92   0.66  -0.42   0.52   0.43   0.16  -0.04
```

**SPY/QQQ correlate at 0.92.** The old universe (SPY/QQQ/NVDA) had a mean pairwise correlation
of **0.75** - researching it produced three views on one factor, and the per-underlying risk cap
(D-037) cannot see that, because it counts names rather than exposures.
**Choice:** universe becomes `SPY, NVDA, XLE, XLV, XLP`. QQQ dropped as redundant with SPY; XLE
(-0.42 vs SPY), XLP (-0.04) and XLV (+0.16) added for measured independence, all liquid and
optionable. Mean |pairwise correlation| **0.75 -> 0.27**. Discovery still nominates any liquid
name freely - this list only governs what gets researched daily.
**Also written: 8 technique concepts into the wiki** (`technique/*`), as operational rules the
agent recalls rather than a literature review: implied-vs-realised as THE edge test, the weekend
vol clock, credit-vs-debit is not a choice (put-call parity), skew does not select structures at
this tenor, event variance dominates short-dated windows, Kelly overbets short premium (and
positive skew validates faster), profit-target conventions do not transfer, and a roll is a new
trade. Each states when it applies and what it changes - the wiki is what the AGENT reads, so
the evidence is compressed to what alters a decision.

## D-054: Measured lessons seeded into evolving memory
**Date:** 2026-08-27
**Status:** accepted
**Context:** Asked to make sure the agent has actually *learned* to diversify. The routing
question came first, and the constitution's own `[routing]` principle answers it: the journal
holds what happened, the wiki holds stable reference (the technique concepts, D-053), the SELF
frame holds identity, and **evolving patterns whose confidence should move with outcomes belong
in elfmem**. A measured claim about how OUR book behaves is the third of those.
**Six lessons, each carrying the numbers that produced it** - a lesson without a measurement is a
platitude, which is the same test the constitution uses:
- `[correlated-names-are-one-bet]` - the diversification lesson. Not "diversify" but the specific
  failure: SPY/QQQ correlate at 0.92, our old universe averaged 0.75 pairwise, and **the
  per-underlying cap cannot see it because it counts NAMES, not exposures** - three "diversified"
  tech positions pass every check and lose together.
- `[friction-is-the-size-of-the-edge]` - EV +$25 -> +$9 after real round-trip cost, a 65% haircut.
- `[research-notes-go-stale-by-design]` - the desk runs while the market is closed; three caught
  mismatches (NVDA 224.11 vs 209.37, MRNA 142.57 vs 145.48, SMCI below its own band floor).
- `[post-event-iv-is-already-gone]` - implied crushes to realised before we look.
- `[exploration-budget-is-not-a-mandate]` - the agent's own line, preserved: buying a
  known-negative-EV structure to generate a data point "is a donation with a story attached".
- `[a-38-percent-trade-can-be-the-right-trade]` - payoff times probability, not win rate.
**Deliberately NOT constitutional.** These are ordinary knowledge blocks that decay and are moved
by outcomes. Pinning a measured claim as PERMANENT identity is precisely what `[regimes]` warns
against - a correlation measured in one regime is a hypothesis in the next.
**Reused two hard-won lessons from seeding the constitution (D-041) rather than rediscovering
them:** seeded blocks sit in an inbox until consolidation (measured again here - **0 of 6
recallable immediately after a successful seed**), and consolidation rewrites content unless we
supply `host_analyses`, in batches capped at the per-run limit.
**Verified by retrieval, not by storage:** `trdrbot lessons verify` recalls each lesson by its own
cue - 6/6, ranks 2-7. And on the real decide-cycle query *"should I open a second position
alongside the NVDA spread I already hold"*, `[correlated-names-are-one-bet]` surfaces first.

## D-055: Beta-weighted book delta - names are not exposures
**Date:** 2026-08-27
**Status:** accepted
**Context:** Closes the gap D-054's `[correlated-names-are-one-bet]` lesson names but could not
enforce: the per-underlying risk cap counts NAMES, so three correlated positions pass every
check and lose together. Until now the lesson told the agent to check by hand what the code
should check for it.
**Choice:** every position's delta is converted to SPY-equivalent by its measured beta and
summed, giving one number for the whole book. Betas come from the closes the research cycle
already persists, so this costs **no network calls**.
**Beta is returned with its R-squared, and shrunk toward 1.0 when the fit is poor.** This
mattered immediately: on our own stored data MU estimated at **-0.45 while NVDA estimated at
+1.85** over the same 120 sessions - both semiconductors. That is not two market sensitivities,
it is one estimate dominated by name-specific news. A beta without its explanatory power is a
number pretending to be knowledge. After shrinkage (same logic sizing already applies to stated
probabilities): MU -0.45 at R2=0.00 becomes 0.98, MRNA -1.52 at R2=0.02 becomes 0.86, while
QQQ (R2=0.84) and NVDA (R2=0.47) keep their genuine betas. Negative beta is never clamped - an
offsetting position is the entire point.
**Reported as P&L per 1% market move, not raw delta dollars.** Raw delta is notional and looks
alarming on any spread - our live NVDA position carries $63,987 of delta against $2,100 of max
loss. The interpretable form is "+1.17% of equity per 1% SPY move".
**What it revealed on the live book immediately:** one NVDA position, raw delta $63,987,
**beta-weighted $118,261** - raw delta understated market exposure by 85%, because NVDA runs a
beta of 1.85. A book that looks small is a levered directional bet.
**Demonstration that justifies the feature:** adding an inverse-beta position RAISED raw book
delta from $90k to $253k while beta-weighted delta FELL from $181k to $18k, and the
concentration flag cleared. Raw delta said "more exposed"; the truth was "almost flat".
**Reported, never gated (D-009):** flagged above 1.5% of equity per 1% market move. It bounds
variance, not ruin, and defined-risk legs already bound the worst case.
**Also fixed:** the positions block rendered `underlying_stop=None` because it read only
`threshold`, while underlying stops carry `level` - telling the agent its most important guard
was missing when it was set.
**Verified:** 5 new tests incl. a 2x tracker recovering beta 2.0 at R2>0.9, pure noise shrinking
back to the market, negative beta preserved, thin history refused, and the hedge demonstration.
93 tests pass.
