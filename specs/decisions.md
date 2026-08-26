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
