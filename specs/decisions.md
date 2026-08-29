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

## D-056: Attribution scored a label, not a profit
**Date:** 2026-08-27
**Status:** accepted
**Context:** The NVDA spread closed while the loop was running - and it closed *well*. The agent
noticed its own profit-target limit had gone stale ("3.40 sat ~5% above mid while the position
bleeds -$84/day. A stale profit-target price is not an exit; it's a hope"), repriced it to 3.18,
and it filled. Total P&L **+$1,290** on the day.
**The bug that exposed:** because the agent closed it with its own order rather than through our
exit-rule evaluator, reconciliation marked it `close_reason='external'` - and attribution read
`profited = close_reason in ("target_hit", "thesis_resolved")`. So a **+52% trade would have
been attributed as a loss**, teaching the learning loop the exact opposite of what happened, on
the only position with a scoreable thesis. It was about to fire on the 2026-09-03 horizon.
**Fix:** profit is MEASURED. `Position.last_pnl_pct` is written every tick while the position is
visible at the broker, because a position closing outside our rules leaves the broker taking its
final P&L with it - the last observation is the honest one. Attribution scores that, falling
back to the label only when no observation exists. The live position was backfilled from measured
equity (100,181.18 -> 101,290.18 with nothing else open, +$1,109 on $2,100 risk = +52.8%);
attribution now yields `thesis_right_expression_right` if NVDA lands in [220, 245] and
`thesis_wrong_profited_anyway` (signal 0.5, teaches nothing) if it does not - which is the
correct pair of answers.
**Second fix - a warning that cried wolf.** "order placed but record_position was not called"
fired on `replace_order_by_id` when the agent repriced its own EXIT, demanding a position record
for something it was closing. Only orders that OPEN a position now qualify. A warning that fires
on correct behaviour trains everyone to ignore warnings - the same class as the
`underlying_stop=None` rendering bug (D-055), a signal that lies.
**Verified:** 3 new tests; 97 pass.

## D-057: The learning-loop simulation - two credit-loss bugs found and fixed
**Date:** 2026-08-27
**Status:** accepted
**Context:** Ran the learning loop end to end with KNOWN inputs (scratchpad sim): synthetic
agents with known calibration through the real scorer/ladder/sizer, then four known positions -
one per attribution quadrant - through the real resolution -> attribution -> memory path.
**What passed first time:** the career arcs. A perfectly calibrated agent promotes
EXPLORE->ESTABLISH->SCALE->MATURE over 8 weeks with size 1->4 contracts, monotonic. An
overconfident agent (says 85%, right 55%) with lucky wins is held at ESTABLISH by the
attribution gate and sized at half. Drawdown demotes to EXPLORE at -11% and recovery restores.
All four attribution quadrants produce the correct verdict, and the attributable rate excludes
exactly the lucky win.
**Bug 1: credit assignment silently skipped on every external close.** `learn.on_resolution`
gated `mem.resolve()` on `close_reason in SELF_RESOLVED` - and BOTH real closes so far have been
'external', because the agent manages its own exits through the broker (repricing its own
profit-target limit) rather than through our evaluator. The gate predates D-056's measured P&L;
with P&L now measured, an external close is honest evidence. Credit now gates on a KNOWN P&L,
skipping only when P&L is unknown (a guess would be worse than silence).
**Bug 2: `outcome()` on an unconsolidated block is a silent zero.** Measured directly:
updated=0 before consolidation, updated=1 after, no error either way. Theses are remembered at
FILL and consolidation runs at market-closed housekeeping - so any same-day resolution loses its
memory credit invisibly. Our first profitable NVDA trade did exactly this. `resolve()` now
detects a short count, consolidates, and retries once; the live NVDA credit was repaired
manually (3 blocks, updated=3). Reported upstream (report addendum 2) with the suggested
`OutcomeResult.pending_inbox` field - same silent-reducer pattern as everything else in that
report.
**Also:** the sim initially hit an OpenAI 401 because the script skipped `config.load()` and the
stale shell key shadowed .env - our own D-shadowing lesson, re-learned in miniature.
**Verified:** the full simulation passes end to end; 99 regression tests.

## D-058: The same measured P&L failed to reach a third consumer
**Date:** 2026-08-27
**Status:** accepted
**Context:** A status review found calibration at **n=0** despite a closed, profitable, recorded
trade. The forecast row existed (p=0.38) with `outcome=None` - never resolved.
**Cause, and the pattern:** reconciliation discovers an external close only AFTER the position
has left the broker, so it calls `learn.on_resolution(pnl_pct=None)`. Every consumer downstream
gates on P&L being known, so calibration AND credit were both skipped in silence. This is the
**third** consumer of the same number to miss it: D-056 (attribution scored a close-reason label
instead), D-057 (credit gated on the label too), and now calibration.
**Fix placed at the shared entry point, not the detector.** `on_resolution` now falls back to
`pos.last_pnl_pct` when the caller has none - so every present and future detector inherits it.
Fixing the reconcile call site alone would have left the same trap for the next detector, which
is precisely how this reached three consumers.
**Repaired live:** the NVDA row resolved at +52.8% -> hit=True. **Calibration is now n=1**, and
the first datapoint is a good one: the agent stated **38%** on a trade that returned **+52.8%** -
honest underconfidence on a positive-expectancy structure, which is exactly what its reasoning
claimed at entry ("a losing-more-often-than-not trade with 3.8:1 payoff").
**Verified:** 100 regression tests.

## D-059: Memory-quality repair - a stale block, a false miss, and a leak found while fixing it
**Date:** 2026-08-27
**Status:** accepted
**Context:** Status review flagged two things: a memory block at reinforcement 49 (the most
reinforced thing in memory bar the constitution), and the SPY mind reading confidence 0.43,
hit/total 0/1. Investigated precisely before touching anything, since these are memory
mutations.
**Correction to my own earlier framing, stated honestly:** I had described the reinforcement-49
block as "the loudest voice in the room" implying it was over-TRUSTED. Checking its actual Beta
confidence (via `recall()`'s `ScoredBlock.confidence`, distinct from the raw `reinforcement_count`
`ls()` exposes) showed **confidence=0.3** - correctly LOW, because the 8 polluted interim scores
(D-034) pulled it down as they should have. The real bug was narrower and different: `reinforce_
blocks()` fires on every `recall()`/`outcome()`/`record_use()` call (confirmed by reading
elfmem's source), so `reinforcement_count` is a pure FREQUENCY counter, not a trust score - and
this block's frequency dominance meant it still ranked #1 by overall relevance `score` (0.91) for
any SPY-adjacent query, low confidence notwithstanding. Two concrete faults, not one vague one:
(a) it was auto-tagged `self/goal`/`self/constraint` during consolidation, so it competed in the
SELF identity frame as if it were identity; (b) its retrieval-frequency dominance crowded out
fresher content in ATTENTION even after the position closed and the content went stale.
**Fix 1 - the stale block.** `edit()` cannot change tags or reset `reinforcement_count` (checked
against the API directly), so the correct action was retire-and-replace: `forget(SUPERSEDED)`
on the polluted block, then a fresh `remember()` with the true outcome, correct tags
(`history`/`closed-position`, no `self/*`), pinned via `host_analyses` (same discipline as
D-041/D-054) so free consolidation cannot re-introduce the leak. Verified: old block inactive,
new block recalls on its cue, reinforcement resets honestly to 1.
**Fix 2 - the mind's false miss.** The linked prediction had `verify_at: 2026-09-02` but was
resolved six days early - by the pre-D-043 interim-scoring bug, on a negative unrealized mark.
`mind_outcome()` **cannot delete a prior resolution, only append another** (confirmed by reading
`elfmem/operations/mind.py`: it calls `record_outcome`, a Beta-posterior update, never an
overwrite). Appending the true resolution now is justified because the position has since fully
closed - real, completed evidence, not speculation ahead of `verify_at`. Called with
`hit=True` and a `reason` documenting the correction explicitly, consistent with
`[contradictions]` (mark the tension, do not silently erase it). **Result, stated honestly: this
partially corrects the record, it does not erase the mistake.** Confidence moved 0.43 -> 0.45,
a small nudge - the wrong signal remains in the Beta posterior alongside the correction, which is
the only available and the intellectually honest outcome given the API.
**Also backfilled, found while fixing the mind:** the SPY position's `last_pnl_pct` was still
None - D-058's repair script only iterated positions that already had it set, silently skipping
SPY. Estimated from cumulative account equity (the only SPY position open from $100,000 to
$100,181 at close, tick 184->186 in the logs): **+8.2%**. Stated explicitly as a cumulative-equity
estimate, not an exact fill record, same limitation as NVDA's earlier backfill.
**A THIRD instance of the same leak found while verifying the fix, and deliberately NOT
retroactively touched.** The NVDA thesis block carries the identical `self/goal`/`self/style`
tags. Unlike SPY's, this content is not stale - the thesis resolves 2026-09-03 - and NVDA never
suffered the interim-scoring pollution (0 interim scores; confirmed), so its confidence is clean.
Forgetting it would destroy real, still-relevant signal for a governance fix with **zero current
operational cost**: the SELF frame renders 11 blocks with 0 dropped, so this one extra leaked
block is not actually crowding anything out today. Left as-is, to be retired the same way once
its thesis resolves and the content becomes genuinely historical.
**Root cause fixed, not just the two instances.** `remember_thesis()` called plain `remember()`
with no `host_analyses`, so EVERY future position's thesis block was exposed to the same leak.
Now pins `[underlying, strategy]` tags at write time, draining the inbox itself rather than
depending on a caller to do it. Verified against a fresh synthetic position: zero `self/*` tags,
recallable by its cue.
**Verified:** live repair script output (printed and reviewed line by line before any write);
`old block active: False`; `SELF frame leaked blocks: 1 (NVDA, documented, deliberate)`; fresh
history block recalls on cue; mind confidence 0.43->0.45; 101 regression tests (removed one
placeholder test that asserted nothing - padding a test suite with `assert True` is the same
dishonesty as anything else in this note).

## D-060: The muse, the bug ledger, the weekend gate, and a name
**Date:** 2026-08-27
**Status:** accepted
**1. Closed-market tick cost - measured, not assumed.** Overnight journal: closed ticks emit
`research` (once daily, the ONLY recurring LLM cost), `attribution_run`, and free bookkeeping;
sensors and snapshots are API calls costing nothing. The 30-minute cadence is therefore already
near-free, and halving it to 1 hour would save pennies while doubling reaction lag to overnight
news accumulation. Kept at 1800s. The real saving found: **Saturday research burned an LLM call
on Friday-stale data** that would be stale twice over by Monday's open. Research now skips
Saturday and keeps Sunday (its regime read feeds Monday). Weekends otherwise: the loop ticks
harmlessly at the closed cadence throughout.
**2. `specs/issues.md` - the living bug ledger.** Rule: a bug is recorded the moment it is
found and removed only by the commit that fixes it. Seeded with 7 open items, the deliberate
limitations (so nobody "fixes" them), and the last 6 resolved for pattern-reading. Health
detects; the ledger remembers.
**3. The muse (`trdrbot muse`) - creative theses by forced collision.** Random wiki concepts x
news x odds -> LLM narrates domino chains -> EVERY candidate pre-registered in the ledger ->
deterministic adversarial evaluation (drift-free bootstrap base probability, band plausibility,
options gate) -> top 2 by |claimed edge| graduate to the inbox. Building it surfaced three
unlogged null paths IN ONE MODULE, each found by running rather than reading: the model wrapping
its array in an object (parsed as dict, silently skipped), horizons dated 2025 (the prompt never
said what today was), and a parse failure leaving no evidence. All three now logged or fixed -
D-038's own rule, nearly violated by the module written the same day.
**4. The information gate, corrected by its first live run.** The naive "base probability >90%
is vacuous" ceiling rejected a candidate stating 27% against a 99% base - which is not vacuous
but a BREAKOUT call, the disagreement being the claim. The ceiling now rejects only when the
model AGREES with the extreme base; the floor stays hard (a band the bootstrap can never reach
needs a jump no history evidences). First live run: 5 candidates, 3 correctly rejected as
wide/vacuous, 1 emitted - SentinelOne, a name no funnel was pointing at, with an explicit
software-guidance-regime chain.
**5. The agent has a name: Theo** - for theta, the greek a short-dated book lives on. Short,
easy to spell, not elf. Seeded as an identity block (renders in SELF under "Learned about
yourself"); system prompt aligned. Upstream nit filed (I-7): elfmem's template header still
hardcodes "You are elf".
**On "research the latest science": deliberately NOT re-run** - two comprehensive sweeps
completed hours ago (docs/sources/trading_techniques_review.md) remain current; re-running would
duplicate spend. The unimplemented top items from it (event variance extraction, chain arbitrage
validator) stay next in the build queue.
**Verified:** 104 tests; muse live run end to end; Theo rendering in the real SELF frame;
weekend gate unit-checked via weekday logic.

## D-061: Rename "You are elf" to "You are Theo" at our boundary
**Date:** 2026-08-28
**Status:** accepted
**Context:** Named the agent Theo (D-060). elfmem's SELF frame still opened every rendered
context with "## You are elf... answer as elf" - checked directly against the installed
package: `context/rendering.py::_SELF_PREAMBLE` is a hardcoded module-level string, with no
config field or name parameter threaded through `frame()`, `FrameDefinition`, or anywhere else
in the API. Not fixable from our config; genuinely upstream-only if fixed at the source.
**Choice: patch the two exact phrases at OUR boundary**, downstream of `frame("self")`, in
`assemble_context` - the same place we already post-process text for ATTENTION dedupe.
Monkey-patching elfmem's private module constant was the alternative and was rejected: reaching
into a dependency's internal state is a larger, less reversible surface than rewriting text we
already own after it crosses into our process.
**My own verification test caught a real bug before it shipped.** A plain `.replace("You are
elf", "You are Theo")` also matches as a substring of a hypothetical "You are elfbot9000" -
producing "You are Theobot9000" instead of leaving it alone. Fixed with a word-boundaried regex
(`\bYou are elf\b`), so a future lookalike name passes through untouched rather than being
mangled.
**Fails safe by construction.** If upstream ever changes the wording, the pattern doesn't
match, the text passes through unchanged, and a warning prints naming the exact heading seen -
the same null-path-must-leave-evidence discipline as everything else this project has built
(D-038). Silently reintroducing "elf" or emitting garbled text were both live risks; neither
survived the test suite.
**Verified against real memory, not just the unit function:** `assemble_context()` on the live
decide-cycle query now renders "You are Theo... answer as Theo" with zero remaining occurrences
of "elf" outside the word "elfmem" itself.
**Issue I-7 closed** (was open since D-060), with a note that the upstream gap - no name
override for the SELF preamble - is still worth reporting, just no longer blocking.
**Verified:** 4 new tests (real text renames; lookalike name not mangled; unrelated content
untouched; safe no-op with a printed warning on a genuine rewording). 108 pass.

## D-062: Provider-agnostic model chains, with cost accounting
**Date:** 2026-08-28
**Status:** accepted
**Context:** Anthropic credits ran out. The system had ONE model string and no fallback, so the
next decide cycle would simply have failed.
**The foundation was already right, and that shaped the design.** `build_model()` was a single
entry point over LangChain's `init_chat_model`, which IS a provider registry. So this is not a
new abstraction layer - adding a provider stays "a line in config plus, usually, one package".
What was missing were the three things the registry does not do:
1. **Fallback chains.** `llm.models` is an ordered list; first that answers wins. Verified live
   against the genuinely exhausted key: the credit error arrives as
   `AnthropicInvalidRequestError` (a **400**, not a rate-limit or auth class - a fallback keyed
   on the wrong exception would never have fired), and `.with_fallbacks()` recovers from it.
   `bind_tools()` and `create_react_agent` both accept the wrapped runnable, so the decide path
   works too - checked before building anything on it.
2. **Per-role chains.** `llm.roles.<role>` overrides the default. decide keeps the strongest
   model; research/discovery/muse run on a cheaper one; doctor uses the cheapest. A role with no
   entry falls back to the default list, so this is opt-in.
3. **Cost accounting** (`usage.py`, `trdrbot usage`): every call's role, the model that ACTUALLY
   served, tokens, and price, appended to `state/usage.jsonl` from a callback - so all five call
   sites are covered without knowing it exists.
**Two bugs found by verifying rather than assuming, both in my own new code:**
- **The decide cycle was being silently under-metered.** `.with_config(callbacks=[...])`
  recorded **ZERO** of a LangGraph agent's LLM calls; constructor `callbacks=[...]` recorded all
  of them. Measured side by side. The config route would have reported a comfortable near-zero
  spend while the real bill accrued unseen - the most expensive path in the system, invisible.
  After the fix, one decide cycle measures **7 calls, 553k input tokens, $0.83**.
- **THE AGENT CAUGHT A BUG I HAD WRITTEN.** It recorded a 0.67 SPY forecast and noted in its own
  reasoning: *"If the system log shows 50% instead of 67%, the intent is 0.67."* It was right.
  `simulate_experiments`' auto-registration writes `probability=0.5` as a pre-registration
  placeholder, and that placeholder was flowing into calibration via `as_forecasts()` - scoring
  the agent on a prediction it never made, at the most corrosive possible value (0.5 is
  maximally uninformative and drags every real forecast toward the base rate). Entries now carry
  `probability_stated`; only stated forecasts score calibration, while placeholders still count
  as TRIALS for the multiple-testing correction, which is what they were for. Live ledger
  backfilled: 6 stated, 1 placeholder correctly excluded.
**Unpriced models are reported, never counted as free** - `render()` prints a WARNING naming
them and excludes them from the total, rather than silently adding $0.00. Pricing is
operator-supplied config with an explicit "verify against current published rates" comment: not
fetched, and it will go stale.
**Also fixed, unrelated and latent since D-043:** `journal.append("inbox_expired", ..., kind=...)`
collided with `append`'s own positional `kind` and raised `TypeError`. It only fires once an
opportunity actually ages past the 180-minute stale window - which took three days - and would
have crashed a live tick.
**`doctor` now probes EVERY configured model**, not just the first: a fallback that has never
been exercised is a promise, not a capability. Live: 3/4 reachable, the exhausted Anthropic key
correctly reported DEAD.
**Verified:** 6 new tests (role/default/legacy resolution, unpriced reporting, dated-model-id
price matching, callback never raising on malformed payloads, unbuildable models skipped not
fatal, clear error when nothing is usable); 114 pass; a full decide cycle ran end to end on the
fallback provider.

## D-063: A testing strategy derived from where our bugs actually came from
**Date:** 2026-08-28
**Status:** accepted
**Context:** "We seem to be uncovering bugs all the time." Rather than answer with "write more
unit tests", categorised every bug this project has had (~24, all in this file). The finding
reframes the whole question: **9 were found by MEASURING, 5 by RUNNING, 4 by VERIFYING output -
and essentially none by a unit test catching a logic error in a pure function.** Our bugs are not
miscalculations. They are wrong beliefs about a seam (`symbols` vs `symbol_or_symbols`, bars
truncating from the wrong end, prices nested under `trades`, `outcome()` silently no-oping on an
inbox block, `.with_config(callbacks=)` metering nothing) and silent no-ops. More unit tests
would not have caught one of them.
**Choice: four tiers, weighted at the seams, and mechanical enforcement so the default stays
honest.**
1. **Unit + INVARIANT** (`test_regressions.py`, always run). The invariants earn their keep: a
   monotonicity check across the whole competence ladder caught two size inversions that had
   already SHIPPED, and a convergence check caught the 16pp bootstrap-drift bug. Both found
   design errors, not typos. One invariant beats ten enumerated examples.
2. **Loop smoke** (`test_loop_smoke.py`, offline, always run). The whole learning ladder with
   known inputs. Its scratch ancestor found two credit-assignment bugs every unit test passed
   over, because they were only visible when the stages ran together.
3. **Contract** (`test_contracts.py`, `-m contract`, ~25s). One belief per test, checked against
   the real service, written so the failure NAMES the belief rather than saying "assertion
   failed". Assert shape and the discriminating property, never a live value.
4. **Runtime** (`trdrbot health`) - not a test, and the only thing that catches a path which
   runs, returns, logs healthily and does nothing.
**Mechanical:** `pytest-socket` blocks the network in the default run; only the contract file
re-enables it, per-file and explicitly. A unit test that reaches the network is both slow and a
lie about what it proves.
**The contract tier immediately caught a real, shipped bug.** Our "You are elf" -> "You are Theo"
rename lived inside `assemble_context()`, so the decide path said Theo while `constitution
verify` and every future caller still said elf - a fix correct where applied and absent
everywhere else. The test caught it by asserting on the SYSTEM's output rather than one code
path. Fixed by routing every caller through one door, `ElfmemAdapter.self_frame()`.
**Contract tests also watch for good news:** the elfmem inbox-outcome test asserts the silent
zero still happens. When upstream fixes it, that test fails, and the correct response is to
delete our consolidate-and-retry workaround.
**Recorded in the Project Overlay** of `docs/principles_testing.md`, which is where that document
says project rules belong, including an explicit "what we deliberately do NOT test" list (LLM
wording, market outcomes, unreachable states).
**Verified:** 118 default tests pass offline in 2.5s; 9 contract tests pass against real
services in 22s.

## D-064: Model routing - the cost lever is context, not model tier
**Date:** 2026-08-28
**Status:** accepted
**Context:** Asked to reason about the optimum cost-to-intelligence ratio per LLM call: should
research use a small model?
**Measured first.** One real decide cycle: 7 calls, 553,054 input tokens, 13,380 output, $0.83.
**84% of that cost is INPUT**, at ~79k tokens per call. One `get_option_chain` payload is ~15,000
tokens, and the agent re-sends accumulated context every turn.
**Conclusion, and the second half is counterintuitive:**
- `decide` keeps the strongest model. Multi-step tool use under uncertainty, and the only role
  where bad judgment costs real money. Economising there is false thrift.
- **Routing research/discovery/muse to cheap models saves very little** - they are one call each
  with small context, a few cents. Worth doing for RESILIENCE (they keep working when the primary
  is down or out of credit) and tidiness, not for cost.
- **The real lever is context size.** Trimming option chains to a strike window near spot before
  they enter context would cut far more than any model downgrade. Logged as the next
  optimisation; a contract test now watches the chain payload size so a change in either
  direction is noticed.
**README rewritten** around this, plus provider configuration, the four testing tiers, all 15 CLI
commands (each verified to exist), and honest limitations including calibration n=1.

## D-065: The context diet - 48% cheaper AND sharper, measured
**Date:** 2026-08-28
**Status:** accepted
**Context:** 84% of decide-cycle cost was input tokens (D-064). Measured the composition before
designing anything: **tool schemas were 20,875 tokens PER CALL - and 71% of that (14.8k tokens)
described 55 tools the agent has never used once.** Across a 7-call cycle, ~104k tokens per
decision spent listing capabilities that are pure distraction - and a larger tool menu
measurably worsens tool selection, so the unused 55 were hurting accuracy while costing money.
The other lever: one `get_option_chain` payload is 61k chars (~15k tokens) - five OHLC bars and
exchange metadata per contract when the decision needs one line - re-sent in full on every
subsequent agent turn, burying the relevant strikes mid-context in exactly the
lost-in-the-middle regime where recall degrades.
**The design principle: cutting fat and improving accuracy are the SAME move here**, not a
trade-off. Less distraction in the tool menu, and the decision-relevant rows no longer buried.
**Two mechanisms:**
1. **Tool allowlist** (`decide.tools` in config): the 17 tools ever used plus close_position/
   cancel_order_by_id (the deterministic exit path uses them; the agent may need them). Empty
   config = bind everything - a missing section degrades to working-but-expensive, never broken.
2. **Boundary compaction** (`compact.py`): a registry of result rewriters applied before results
   enter context. Chain: 13x smaller, strikes within 12% of an ATM inferred by put-call parity
   (no extra network call), prices and sizes VERBATIM never rounded, with the escape hatch
   stated in the output ("call again with strike_price_gte/lte"). News: headlines only, 78x.
   **Fails open, loudly**: any parse surprise passes the ORIGINAL through and prints - a
   compactor returning empty on surprise would starve the decision silently (D-038's class).
   The tool INTERFACE is untouched, so tool_guard and the whole-book redirect compose unchanged.
**Measured live, before vs after, same forced-decide conditions:**

| | baseline | after | change |
|---|---|---|---|
| input tokens | 553,054 | 230,097 | **-58%** |
| cost | $0.8251 | $0.4326 | **-48%** |
| avg input/call | 79,007 | 28,762 | -64% |
| chain fetches | 2 | **4** | the agent explored MORE |

That last row is the accuracy story: with chains cheap, the agent examined four expiry/strike
sets instead of two, priced three candidate structures, cited `[friction-is-the-size-of-the-edge]`
by name, and recorded a 0.74 forecast - the decision got more thorough, not less.
**Verified:** compactor offline against the real payload shape (13x, ATM correct, six fail-open
cases pass through untouched); 123 default tests; live cycle measured above.

## D-066: News extraction - a cheap model reads bodies once, so nobody has to reread them
**Date:** 2026-08-28
**Status:** accepted
**Context:** D-065's headline-only news compaction was an ASSUMPTION ("bodies are summary-resistant
filler"), not a measurement, and the user correctly pushed back: sentiment, named
organisations/people, the kind of event, and which regime it speaks to (macro/sector/company) are
often exactly what separates a real thesis from noise - a bare headline throws that away. The fix
is not "send bodies back" (that reintroduces the ~2k chars/article D-065 removed); it is reading
each article's body ONCE with a cheap model and distilling it to structured fields plus one dense
sentence, then reusing that distillation everywhere instead of re-deriving it four times a cycle.
**The standardised store the user asked for:** `state/news_extracts.json`, one JSON record per
article id (`Extract`: sentiment, organizations, people, activity, regime, dense summary, model,
extracted_at) - same flat-file shape as `sensors.SensorState`, deliberately not a database at this
volume. Keyed by article id, so the SAME article recurring across research/discovery/muse/sensors
within a day is extracted exactly once and every consumer since reads the cache. `news_extract.py`
owns the schema; every writer and reader goes through it, so the shape cannot drift per call site.
**One batched call per cycle, never per article** - all uncached articles in one prompt, one model
reply parsed as a JSON array matched back by id (reuses `research._parse_json_block`, the same
JSON-in-prose parser every other synthesis call in this project already relies on).
**Fails open PER RECORD, and never freezes a failure.** A malformed field degrades that one
record (`_coerce`); a failed call degrades the whole batch to bare extracts (`dense`=headline,
`sentiment`=None) - identical in information content to the pre-D-066 output, so a cold cache or an
extraction-role outage degrades to exactly the old behaviour, never to something worse. Bare
extracts are deliberately NOT written to the cache, so a transient failure is retried next cycle
rather than being permanently recorded as "unknown".
**Wired through four call sites**, replacing each one's ad hoc `headline | source | symbols`
reduction with `news_extract.render_block(await news_extract.enrich(items, config))`:
research.py, discovery.py, muse.py (all prompt-facing), and `compact.compact_news` (decide's
tool-result compactor, cache-read-only - no LLM call inside the hot tool-wrapping path; it renders
whatever is already cached and falls back to bare for anything not yet extracted).
**Role, not a code path:** `news_extract` in `llm.roles`, cheapest tier
(`gpt-4o-mini` → `gpt-5-mini`) - this is bulk structured extraction, not judgement, the same
reasoning as D-064's cost-tiering.
**Verified live** (not mocked): two synthetic-but-realistic articles through the real model -
correctly gave the Apple guidance beat +0.8 sentiment (Apple Inc / Tim Cook / guidance / company)
and the Fed-patience story 0.0 (Federal Reserve / Christopher Waller / macro_data / macro), and a
second `enrich()` call on the same ids took 0.000s - proof the cache hit skipped the LLM, not just
an assertion about it. Test articles were removed from the real `data/state/news_extracts.json`
after verification. Offline: 5 new regression tests exercise the real fail-open path (an
unbuildable model, exactly like `test_build_model_skips_unbuildable_models_rather_than_dying`) -
cache-hit skips the model, cache-miss-on-failure returns bare and is never persisted, malformed
model output degrades one field at a time. 127 default tests pass.
**Left for later, not built:** rolling the day's extracts into the wiki's `context/regime` /
`CompanyDossier` concepts as structured frontmatter. Not needed yet - research.py's synthesis call
already turns news into wiki prose, and it now reads the DENSE extracted block instead of bare
headlines, so the wiki should already improve without a second storage schema. Revisit only if the
wiki's own narrative synthesis is found to lose the structured signal on the way to prose.
## D-068: News extraction field set grounded in research, plus the citation URL
**Date:** 2026-08-28
**Status:** accepted
**Context:** D-066 shipped a field set (sentiment, orgs, people, activity, regime, dense) chosen by
intuition, not evidence - the same mistake D-065's "bodies are filler" assumption made. The user
asked for two things: research what should actually be extracted, and preserve the original
article URL as a citation. Ran a decision-mode scout research pass (5 angles, 21 primary sources
fetched, 105 claims extracted, 15 adversarially verified 2-vote) against academic financial-NLP
literature and commercial-product claims. The commercial-product claims (RavenPack, Bloomberg
Event-Driven Feed, LSEG/Refinitiv, Benzinga, AlphaSense) did NOT survive verification - zero
vendor field-schema claims confirmed - so this decision rests on academic literature only:
SEntFiN (Sinha et al., JASIST 2022), "Beyond Sentiment" (arXiv 2607.28496), "Trade the Event"
(Zhou/Ma/Liu, ACL Findings 2021), "Numerical Claim Detection" (Shah et al., EMNLP FEVER 2024),
Dolphin et al. (arXiv 2607.08346).
**Adopted (evidence-weighted, each cheap):**
- `url` - the citation itself. Alpaca-sourced, never model-derived, threaded through `bare()` and
  `_coerce()` identically so it survives even when extraction fails outright - answers the user's
  ask directly rather than treating it as one more extractable field.
- `quote` - the model's claimed supporting sentence for `dense`. Converges across three sources as
  a schema element (SEntFiN's entity claims, Dolphin et al.'s per-tag quote requirement, FinVet's
  verdict/evidence/source/confidence output) but is stored HONESTLY as unverified - the specific
  automated grounding mechanism researched (n-gram overlap validation) was refuted on our own
  verification pass, so no claim is made that `quote` is checked against the source text.
- `key_number` + `claim_type` (forecast|established) - "Numerical Claim Detection" formalises
  exactly this split ("a speculative financial forecast" vs "a numerical statement about a past
  event... a confirmed fact") because a guidance figure and a reported print carry opposite
  information content; conflating them was the gap.
- `time_horizon` (immediate|near_term|long_term) - named in "Beyond Sentiment" as one of six
  extraction dimensions, medium confidence (single recent preprint) - but adopted anyway because
  no verified source anywhere maps a claim's horizon onto OPTIONS TENOR, which is exactly this
  agent's need, and the field is nearly free to add to an existing extraction call.
- `confidence` - inline self-rating. Dolphin et al.'s central finding is that this specific
  approach is markedly overconfident and collapses to a near-binary flag (~75% of tags land at the
  top score) versus 12%->96% monotone precision from a SECOND quote-grounded grading pass. Adopted
  the cheap version anyway, documented in the dataclass docstring as "informative when low,
  meaningless when high" - the honest framing, not a claim of calibration we didn't build.
- `activity` vocabulary gained dividend/buyback/split - "Trade the Event"'s 11-type taxonomy names
  these as predictable-price-impact categories our prior 9-type list omitted.
**Explicitly NOT adopted, and why:**
- full per-entity sentiment decomposition - its only standalone justification (~26% of headlines
  carry CONFLICTING per-entity sentiment) was REFUTED on verification; only multi-entity presence
  was confirmed, not conflict. Our articles already arrive symbol-scoped via Alpaca's own
  `symbols` field, so one sentiment per article is the right size, not under-modelling.
- a second-pass confidence grader - the highest-leverage finding in the whole research pass
  (12%->96% precision), deliberately deferred: it doubles this role's LLM call volume for a result
  resting on one vendor-authored preprint. Documented in the module docstring as known-better,
  not-built, with the explicit trigger to revisit ("if news-driven theses start showing a real
  false-positive problem").
- automated quote verification - the specific mechanism researched (n-gram overlap, 40% threshold,
  auto-retry) was refuted 0-2 on our own verification. No fabricated substitute was built.
- source credibility tiering and relevance/materiality scoring - zero surviving evidence either
  was even attempted by name in the literature searched; not invented to fill the gap.
- novelty/staleness detection beyond article-id dedup - confirmed as first-order for tradability
  (an event-driven signal went from +1.74% to -0.07% average return within the same minute once
  stale) but the mechanism was never verified as something to copy, and building an unverified
  heuristic would be worse than the honest gap. Logged as an open item, not silently skipped.
**Verified:** live extraction against a realistic article (Apple EPS guidance raise, explicit
before/after figures, a stated earnings date) correctly produced `key_number="$2.50 EPS guidance,
up from $2.30"`, `claim_type="forecast"`, `time_horizon="near_term"`, a `quote` that genuinely
appears in the source summary, and the real Alpaca `url` carried through untouched. 9 new
regression tests (URL survives total outage; URL never model-sourced; closed-vocabulary fields
degrade to empty on garbage input rather than passing through; a claim_type with no key_number is
dropped as meaningless; confidence clamps to [0,1] or None). 130 default tests pass. Test articles
purged from the real `data/state/news_extracts.json` after both live verification passes.

## D-069: Retire the SELF-preamble boundary rename - elfmem fixed it upstream (redone)
**Date:** 2026-08-28
**Status:** accepted
**Context:** A separate session working directly on the elfmem library accidentally wrote to
*this* repository while landing the upstream fix - an uncommitted D-067 draft (elfmem_adapter.py,
uv.lock, decisions.md, specs/issues.md, test_contracts.py) sitting in the working tree, discovered
mid-task and left untouched (this project's own D-068 was numbered around it to avoid collision).
The user has since confirmed that session backed its own accidental writes out and instead landed
the real fix on the `elfmem_index` branch. This entry supersedes the numbering gap left at D-067
and redoes the integration from scratch against the actual shipped fix, not the reverted draft's
description of it - `uv lock --upgrade-package elfmem` (`d86e6d62` -> `cebc242e`), then read the
installed package directly: `api.py` line ~1907, `host_name = proj.agent_name if proj and
proj.agent_name else "elf"`, threaded into `render_blocks()`/`_render_self_template()` - confirms
`project.agent_name` now reaches the SELF preamble, closing the exact 4-hop gap
`docs/self_preamble_naming_report.md` traced (and which elfmem's own `config.py` now cites by
name, crediting that report).
**Choice: set `project.agent_name` once, at `ElfmemAdapter.build()`, delete the boundary patch.**
`cfg.setdefault("project", {}).setdefault("agent_name", _DEFAULT_AGENT_NAME)` before
`MemorySystem.from_config()` - setdefault, not overwrite, so a future caller passing its own
config keeps the final say. `_rename_self_preamble`, `_SELF_PATTERN` and the `_SELF_NAME_FROM/TO`
constants are deleted; `self_frame()` keeps existing (it still owns the top_k default that renders
the WHOLE constitution, D-041) but no longer post-processes the text - elfmem renders the right
name itself now.
**Not run: elfmem's own `elfmem migrate apply`.** `elfmem migrate status` reports two pending
steps, but both target the shared `~/.elfmem/` global config/db used across this user's other
projects (`movemyth`, etc.), not trdrbot's own store - trdrbot never uses elfmem's CLI-managed
project scaffolding, it calls `MemorySystem.from_config(db_path, config_dict)` directly with an
inline dict. Running the CLI migration would touch state outside this project's scope for no
benefit here; the actual migration this project needed was the code change above.
**Verified live, not just re-pointed:** `test_self_frame_still_says_you_are_and_renders_the_constitution`
(real `MemorySystem`, real `data/state/elfmem.db`, no mocks) passes with zero rename code running -
confirms `mem.self_frame()` itself now reads "You are Theo", not that a patch still papers over an
unfixed upstream. Two tests already sitting in `test_regressions.py` from the reverted draft
(`test_build_sets_agent_name_by_default`, `test_build_does_not_clobber_an_explicit_agent_name`)
had been swept into this project's own D-068 commit by an imprecise `git add` - caught here,
reconciled by renaming this implementation's constant to match what they already asserted
(`_DEFAULT_AGENT_NAME`) rather than rewriting tests that test the right thing. specs/issues.md I-7
updated from "fixed at our boundary" to "fixed upstream".
**Verified:** 9 contract tests pass (real elfmem, real Alpaca, real LLM calls) + 130 default tests.

## D-070: Shakedown - six defects found by reading live state, not by testing
**Date:** 2026-08-28
**Status:** accepted
**Context:** A full professional-trader review of the running system. Every finding below came
from reading LIVE state (journal, usage ledger, elfmem SQLite, position frontmatter) against what
the code claims - the same method that produced 9 of this project's bugs, and again the method
that worked: the 137-test suite was green throughout and caught none of these.

**1. The journal lied about which model decided.** `model=config.model` recorded the configured
FIRST CHOICE, not what answered. Live: 19 decide cycles journalled `anthropic:claude-opus-5` while
`usage.jsonl` showed `gpt-5` served every one - the Anthropic credit exhaustion had silently
failed over. Fallback is not an error and leaves no error record, so nothing in the system would
ever have contradicted the wrong attribution, and D-008's whole promise ("results stay
attributable across a mid-competition swap") was void exactly when it mattered. Fixed with
`UsageLedger.served_since(role, since_ts)` reading the provider's own response metadata, and a new
`model_served` field alongside the intent. A LIST, not one value: a chain that fails over mid-cycle
genuinely was served by two models, and flattening that trades a known lie for a subtler one.

**2. The decide path never received enriched news.** D-068 wired extraction into research/discovery/
muse, and `compact_news` reads the cache - but nothing on the decide path ever WROTE it, and those
three run daily at best. Live proof: zero production `news_extract` calls, no cache file, while the
decide prompt rendered raw JSON payloads. So the highest-value, most-frequent consumer of news got
the pre-D-066 behaviour. Enrichment now happens at the decide seam itself, deliberately NOT at
ingestion: sensors are architecturally LLM-free (D-015), and enriching at decide means the freshest
article - the one that just arrived and matters most - is enriched at the moment of the decision.
Measured on two live articles: raw JSON 1,322 chars vs enriched 824 - **38% smaller while adding
sentiment, event type, regime, claim horizon and entities**, for ~$0.0002. Cheaper AND better.

**3. The news cache key was defeated.** `_news_payload` used the publisher's article id as the
sensor dedup key then DROPPED it, so the decide path fell back to the inbox item id. The same
article reached the cache under two different keys depending on which path saw it - extracted
twice, paid for twice, and the cross-consumer dedup the cache exists for silently defeated. Fixed
by carrying `id` through the payload.

**4. Five memories were being sent to the model twice per prompt.** `assemble_context` deduped
block IDS across frames but appended each frame's TEXT regardless. Measured live: TASK returned 5
blocks, **all 5 already in SELF, 0 unique, every cycle** - so ~819 chars/call of the same memories
under a second heading, resent every agent turn. The cost is minor; the distortion is not.
Repeating five of eleven principles doubles their weight against the six that appear once, quietly
corrupting the constitution this frame exists to present faithfully. Now: a frame contributing no
new block contributes no text (SELF exempt - it is the identity frame).

**5. `record_forecast` had no vacuity guard, and calibration gates SIZE.** The competence ladder's
only n-gate is a COUNT (`min_n`), so "SPY between 0 and 10000 next Tuesday" was a scoreable
forecast that resolves true, counts toward `resolved`, and walks the agent up the size ladder on
evidence of nothing - the cheapest possible way to earn real risk budget dishonestly, and nothing
else in the system would have noticed. Added `_vacuity_check`: bootstrap the band's base
probability from persisted closes (no network) and refuse when history almost always holds it AND
the model agrees. Reuses the muse's hard-won refinement (D-060) - **disagreement IS the claim**, so
a stated 27% against a 100% base is a breakout call and passes. Fails OPEN without price history:
an invented judgement is worse than an unguarded one. Verified on real SPY data: both gaming
vectors refused, the tight uncertain band and the contrarian call both accepted.

**6. Health cried wolf.** `attribution ran 36x, produced nothing` read as a hard FAIL, but every
run recorded `pending: 0` - nothing was DUE, because theses resolve at their horizon. A check that
cries wolf trains the reader to skip the one line that finally matters, which is precisely how the
silent no-op it exists to catch would slip through. `Probe` gained an optional `work` predicate:
ran, produced nothing, and nothing was available now reads "idle, not stalled". The real signal is
preserved and tested - work waiting with nothing attributed still FAILS.

**The strategic finding, not a bug.** Every forecast in the ledger resolved 2026-09-02/03 against a
2026-09-04 deadline, and ESTABLISH needs 5 resolved. The system was therefore **mathematically
locked at EXPLORE** (kelly_multiplier 0.0, fixed 2.2% allocation) for the entire competition: the
learning loop is real, but its output arrived after the last moment it could change a decision. You
cannot learn from a feedback loop slower than your operating window. Fixed where it belongs - in
the `record_forecast` docstring, which now argues for 1-3 day horizons and says why ("one slow
forecast is worth less than three fast ones"). Verified causally on the very next cycle: the agent
recorded SPY >=768 by **09-01** and reasoned, unprompted, that it "resolves in two sessions (inside
the deadline, with time left to act on the result)" - previous batch was 09-03 to a man.

**Does elfmem have impact? Measured, and the honest answer is split.** READ side: demonstrably yes -
11 SELF + 4-5 ATTENTION blocks recalled into every cycle, and the agent cites principles BY NAME in
its output (`[premise]` x3, `[contradictions]` x2, `[recency]`, `[fallible-recall]`,
`[research-notes-go-stale-by-design]`, and `[correlated-names-are-one-bet]` - the diversification
lesson taught after the SPY/QQQ 0.92 correlation finding, now visibly steering live decisions).
Confidence is differentiated sensibly: a missed prediction sits at 0.28, a validated lesson at 0.75,
the constitution at 1.0, and D-059's stale SPY price block is correctly `archived`. WRITE side: **it
has never once learned from a trade.** All 21 `block_outcomes` rows come from the mind subsystem;
there is not a single `attribution:*` outcome, because attribution waits for a horizon no position
has reached. elfmem is currently a well-functioning read cache for hard-won principles, and an
untested write path - which is exactly what finding 6 was masking.

**Verified:** 137 default tests (7 new, one per finding plus the contrarian-call and fail-open cases
for the vacuity guard). Live forced decide cycle on the new code: `model_served: ['claude-opus-5']`
recorded correctly, news cache written from the decide path, 4 structures priced and all declined on
negative EV after costs, with the agent noting ATM IV 10.5% against 21-day realized 11.3% and
refusing to cherry-pick the 5.9% five-day figure - "turning any of these positive would require me
to raise my drift input until the answer I wanted appeared."

## D-071: The three health warnings, closed out
**Date:** 2026-08-28
**Status:** accepted
**Context:** D-070 fixed six defects and left three health *warnings* uninvestigated. All three
turned out to be real, and one was a silent data-loss path.

**1. Our own code bugs were classified TRANSIENT.** Live record: `ValueError: unsupported format
character ','` - a broken format string in our own logic - classified `transient`, which queues
the blameless observation that happened to be in flight to burn three retries and then
dead-letter itself for a defect it had nothing to do with. That is precisely the loss the CONFIG
category was created to prevent ("an invalid Anthropic key bumped a perfectly good observation's
retry count"), arriving through the one door CONFIG did not cover. The transient default is right
for UNKNOWN failures - "retrying costs a tick, discarding costs the signal" - but a deterministic
exception from our own code will fail identically next tick, so retrying costs three ticks AND
discards the signal anyway. Added `Cause.BUG` (TypeError/ValueError/AttributeError/NameError/
IndexError/ZeroDivisionError/NotImplementedError) sharing CONFIG's blameless policy with its own
advice. **Ordering matters and is tested:** `ConnectionError` and `TimeoutError` subclass
OSError/RuntimeError, so the name-marker checks must stay ahead of the isinstance check, and a
provider SDK error subclassing ValueError must still be read by name.

**2. Rejected opportunities did not say why.** Every rejection journalled the same opaque
`unscoreable_opportunity`, so a fully-reasoned CRM thesis - correct bands, correct drift, its
horizon stated in its own claim text but absent from the `horizon` FIELD - was indistinguishable
in the log from genuine garbage. 2 of 10 opportunities were being dropped this way, ~20% of
research LLM spend, with no way to tell whether the cause was fixable. `opportunity_defect()` now
returns the specific defect (`missing_horizon`, `missing_band`, `bad_horizon_format`, ...) and the
journal records it. The rejection itself was CORRECT and is unchanged - an opportunity with no
machine-readable horizon genuinely cannot be scored, and salvaging a date out of free claim text
would be an LLM-supplied value validating an LLM-supplied value, which `_plausible_band` exists to
forbid. What changed is that a repeating defect is now visible as a fixable prompt problem rather
than as attrition.

**3. The 401 with `cause=None` is historical.** Dated 2026-08-26T18:30, it is the very run that
motivated the CONFIG category; the record predates the fix. `AnthropicAuthenticationError` now
classifies as CONFIG, verified directly.

**Not fixed, and honestly not fixable from here:** the exit-rule evaluator has still never fired
in production (0 `exit` journal entries) because both positions to date closed externally. The
deterministic path that protects capital when the agent is not looking remains unexercised on
live data. Logged rather than papered over.

**Verified:** 141 default tests (4 new), including that a `Cause.BUG` failure leaves the inbox
item's retry counter untouched on disk - the actual data-loss this fixes.

## D-072: Credit assignment, phase 1 - what happened vs what it applied to
**Date:** 2026-08-28
**Status:** accepted
**Context:** An optimize simulation of the elfmem learning loop, grounded against the live SQLite
and elfmem's own update function rather than reasoned about. It first CORRECTED a claim made in
D-070's review: the constitution is NOT eroding - `positions.CREDITED_FRAMES = ("task",
"attention")` already excludes the SELF frame from credit (D-033/D-041). What the grounding did
find is three real defects, all in the one path that has never yet run.

**1. The "neutral" luck signal was not neutral.** elfmem's update is a Beta posterior mean:
`new_conf = (a + s*w) / (a + b + w)`. A signal leaves a block unchanged only if the block already
sits at that confidence - so the 0.5 encoding "learn nothing from luck" was a force pulling every
block toward 0.5 from wherever it was. Measured with elfmem's own function against live blocks: a
lucky win moved the constitution **-0.250** and moved a prediction that had already MISSED
**+0.018**. It punished what was right and rewarded what was wrong, the exact inversion of the
comment's stated intent. `ATTRIBUTION_SIGNAL` now carries `None` for
`THESIS_WRONG_PROFITED_ANYWAY` and `UNSCOREABLE`, and the caller skips: teaching nothing means
applying nothing.

**2. Attribution bypassed the consolidate-and-retry fix.** `attribution.run()` called
`mem.mem.outcome()` directly while `learn.py` went through `ElfmemAdapter.resolve()` - so the MAIN
trading credit path was the single path missing D-057's protection against elfmem silently
returning `updated=0` on unconsolidated blocks. Same shape as the SELF-preamble rename living in
only one caller (D-063), same fix: `credit_blocks()` is now THE door, both callers use it, and it
returns `(requested, applied)` because a caller that cannot see `applied` cannot tell
credit-applied from credit-silently-dropped. A short count journals `attribution_credit_short` -
which will fire, since the SPY position's only creditable block is archived and elfmem skips
non-active blocks.

**3. The ATTENTION query was a constant.** `" ".join(config.watchlist) + " options setup"` - with
watchlist `["SPY"]`, every recall asked about SPY regardless of what was being decided. That is
why the NVDA position was decided with SPY memories in context and would then have CREDITED them:
**2 of its 3 creditable blocks were about the wrong underlying.** Retrieval was answering a
question nobody asked and the learning loop was about to score the answer. `_attention_query()`
now ranks by how directly a name bears on the decision - open positions, then opportunities, then
news - capped at 6.

**The news filter was forced by the first live run, before shipping.** The unfiltered version, run
against the real pending inbox, produced `"AGG BND GLD SPY options setup"` from one broad-market
article tagging twelve ETFs - asking memory about bond and gold noise and pushing SPY, the only
name in the book, to fourth. That was WORSE than the constant it replaced. News symbols are now
filtered to names we could actually trade (watchlist + research universe); opportunities are never
filtered, because nominating off-universe is exactly discovery's job. An article's ticker list is
what it mentions, not what we are deciding about.

**Rejected in the simulation:** LLM-scored block relevance. Plausible, but it is an LLM-asserted
value validating an LLM-asserted decision - what `_plausible_band` exists to forbid - and
non-deterministic credit makes the loop unauditable. Deferred to phase 2: similarity-weighted
credit (`ScoredBlock.similarity`, deliberately NOT `.score`, which folds in confidence and
reinforcement and would make trusted blocks accrue trust faster - rich-get-richer, the pathology
D-059 already caught once).

**Verified:** 148 default tests. Four existing tests asserted the old `0.5` contract and were
updated deliberately as their own step, with the arithmetic that disproved them pinned in a new
test. Live forced cycle: `model_served: ['claude-opus-5']`, task frame contributing 0 blocks with
no duplicate text, and a forecast recorded at a 09-01 horizon with the agent noting unprompted
that it "resolves Sep 1, which is early enough to still inform a decision before the deadline."

## D-073: Credit assignment, phase 2 - weight by how well the block matched
**Date:** 2026-08-28
**Status:** accepted
**Context:** D-072 fixed WHAT credit says (`signal`) and WHERE it goes (the query). This fixes HOW
MUCH each block gets. Credit was uniform across every creditable block, so on the NVDA position
the SPY mind model - which retrieval scored at similarity **0.0** against both a SPY and an NVDA
query - was set to receive exactly as much credit as the one block genuinely about NVDA.

**The weight is `ScoredBlock.similarity`, deliberately NOT `.score`.** `score` is the composite
and folds in `confidence` and `reinforcement`, so weighting by it would make already-trusted
blocks accrue trust faster - rich-get-richer, the exact pathology D-059 caught once already.
`similarity` measures only "how well did this block match the query this decision was made on",
which is the question a credit weight should answer, and it is computed by elfmem rather than
asserted by a model.

**The edge case that would have crashed it.** `similarity` is MIN-MAX NORMALISED within each
result set - the worst match in every recall is exactly 0.0 and the best exactly 1.0 - and
elfmem's `_validate_weight` raises `ValueError` on `weight <= 0`. Passing similarity through raw
would therefore have crashed attribution on its first weighted credit, in the path that has still
never run. Hence `CREDIT_WEIGHT_FLOOR = 0.25` and `credit_weight()` mapping into [0.25, 1.0]. The
floor has a second, independent justification: a block that matched least was still in the context
that produced the decision, so it earns LESS credit, not none - a floor says "contributed little",
zero would claim "was not there", and only one of those is true. Both beliefs are now pinned as
contract tests, because if elfmem changes either the design breaks silently.

**Because similarity is min-max normalised, the weight is a WITHIN-DECISION RANK, not an absolute
relevance.** It says this block matched better than that one on this query; it does not say either
matched well. That is the honest reading and it is enough for the job - the best-matching block
carries 4x the worst, which is the mechanism. The exact ratio is not load-bearing.

**Backward compatible by construction, not by migration.** `elfmem_blocks` accepts both a plain
list (pre-v2) and `{id: similarity}`. Iterating a dict yields its keys, so `all_elfmem_block_ids`
and `recalled_block_ids()` needed no change at all. A list-shaped position credits at 1.0 -
exactly the behaviour it was written under - rather than being retroactively re-weighted by a rule
that did not exist when it was created. No file is rewritten. `add_recalled_block()` preserves
whichever shape it finds, so `learn.py`'s fill-time write works on either.

**Only ATTENTION carries a meaningful weight.** SELF and TASK are framed with `query=None`, so
elfmem returns 0.0 for every block in them - harmless, since neither is credited, but documented
in `assemble_context` because it is a trap for anyone who later adds one to `CREDITED_FRAMES` and
finds every principle pinned at the floor.

**Verified:** 156 default + 11 contract tests. Live: `assemble_context` on an NVDA query returns
the NVDA fact at similarity 1.000 -> weight 1.000 and the SPY mind model at 0.000 -> weight 0.250,
a 4x differential where there was none; both stored positions (list-shaped) still credit at 1.0;
a dict-shaped position round-trips through YAML frontmatter intact. A forced decide cycle wrote
the weighted shape into the journal for all three frames, and the agent declined four structures
on negative post-friction EV, noting it could have made them print positive "by feeding the
simulator 9% vol instead of 11% - that is tuning the input until it agrees with me, not analysis."

## D-074: Shakedown - four capabilities that were not running, and a 62% cheaper cycle
**Date:** 2026-08-28
**Status:** accepted
**Context:** A full professional-trader review of the running implementation, traced in
[notes/013](notes/013_shakedown_trader_review.md). Method unchanged from D-070 because it keeps
working: read LIVE state against what the code claims, and compute what reasoning cannot settle.
14 defects. The 156-test suite was green throughout and caught none of them - the fourth
consecutive pass where that is true.

**The four that were not running at all.** Each is a documented capability with a module and
tests that produced nothing in production.

**1. Every mark-based exit rule on the book was unreachable.** `position_pnl_pct` divided by the
GROSS premium summed across legs; on a vertical spread that is 2-7x the net. Priced at their own
entry parameters: NVDA's `stop_loss -60%` fired at -$2,287 against a $2,253 max loss, SPY's
`profit_target +50%` at +$1,057 against $535 max profit, SPY's `stop_loss -100%` at -$2,114 against
$1,965. **Three of four could never trigger; the fourth triggered at +118% of the debit rather than
+70%.** `health` has said `exit_rules never ran` for two days and it was read as a quiet market. The
denominator is now the NET debit paid or credit received - what a broker's P&L% column shows and
what a trader means - so a debit spread's loss bounds at -100% and a credit spread's +50% is the
standard buy-back-at-half-credit. A near-zero net returns None rather than dividing by noise.
`record_position` additionally NAMES any rule that cannot fire, matched by legs against what
`simulate_experiments` priced: the same shape as `watched_signals` one level deeper, a rule that IS
watched and cannot trigger.

**2. Interim scoring has been dead since the day it was added.** `INTERIM_BANDS = (25.0, 50.0)`
against a caller passing a FRACTION - band 1 needed +2500%. This is INV-24, the mechanism that
exists to make the learning loop turn inside an 8-day window. The journal: eight `interim_outcome`
rows, ALL dated 2026-08-26, none across ~250 subsequent ticks. Both unit tests passed throughout
because they spoke percents while the caller spoke fractions - each internally consistent, jointly
wrong. The replacement derives its input from `position_pnl_pct` itself rather than from a literal.

**3. Option-chain compaction has never once executed.** `langchain_mcp_adapters` builds tools with
`response_format="content_and_artifact"`, so a coroutine returns `([{"type":"text","text":json}],
artifact)` - never the dict the compactors were written against. Every call took the FAIL-OPEN path
and returned the original, silently, for all 28 chain calls on the journal. So D-065's measured 48%
saving came entirely from the tool allowlist and the lever it called the larger of the two had
never been pulled. Fixed and verified live: **79,542 -> 6,076 chars, -92%**. Working compaction then
exposed two more: the ATM inference was 6% out (a real SPY page is 100 contracts, strikes 500-773,
ALL CALLS, no puts, with a next page - so the parity method found nothing and the median-strike
fallback said 724 against a tape of 771.67; one-sided parity `min(C+K)` gives 769.67), and the
header now states what is actually ON the page, because an agent pricing a put spread off a
calls-only page is pricing nothing and could not see that from a table of rows.

**4. `_market_pulse` was defined, unit-tested and never called.** `idle.decide` absorbed the rung at
D-043 and nothing removed the original. Worse than dead: it carried its OWN copies of both
thresholds, so tuning `PULSE_MOVE` would have changed behaviour by exactly nothing while its test
kept passing. Deleted; `idle.MATERIAL_MOVE` and `idle.MAX_SILENCE_MIN` are the only copies now.

**Calibration was out of tune in three places.** (a) Murphy reliability read the BIN CENTRE, not the
bin's mean stated probability - `sum(pb for pb in [b])` is just `b`. Below n=24 there are two bins,
so everything under 0.5 scored as 0.25 and everything above as 0.75. On the live record (one
forecast, stated 0.38, resolved true) it returned **0.5625 against an honest 0.3844**; on a
synthetic agent stating 0.95 while right half the time at n=16, **0.019 against 0.150 - which
PASSES the MATURE gate that exists to catch it**. It feeds `shrink_probability`, where an
understated reliability buys real size, and Kelly's whole fragility is estimate quality. The
decomposition identity is now a test. (b) **The size ladder inverted twice**, against its own
stated invariant: promotion EXPLORE->ESTABLISH took a 1:1 bet at 62% from 4 contracts to 1 (the
first Kelly rung sits below the exploration allocation), and crossing MIN_SAMPLE took an 88% credit
spread from 1 contract to ZERO at fixed excellent reliability, because the GATE swapped from the
stated probability to the shrunk one while the trust term was still n/30. Fixed by making the
exploration allocation a FLOOR that Kelly can only raise, and by gating on the stated probability
always: "is there an edge at this payoff" is a question about the STRUCTURE, "how much do we bet" is
the question about the record, and fractional Kelly plus the tier cap is the entire answer to the
second. Letting the record also veto charges the same evidence twice, discontinuously. The shrunk
view is REPORTED instead (D-009's posture). Verified monotonic across four payoff shapes x twelve
sample sizes; a genuinely edgeless structure is still refused. The original invariant test missed
both because it measured integer CONTRACTS at ONE payoff, where the `contracts < 1 -> 1` floor
pinned every rung to the same number. (c) **Two numbers called "your calibration" disagreed inside
one decision**: the tier used the ledger-inclusive sample, `size_position` used positions-only, the
prompt showed a third, and `trdrbot calibration` - the command you would check it in - hid the
eleven pending ledger forecasts entirely. One number now, computed once.

**The EV the agent decides on could not be moved by its thesis.** `ev_after_costs` was expected
value at drift ZERO - the market's own distribution - minus friction. A fairly priced structure is
worth about nothing under the distribution its own price implies, so after friction that number is
negative for EVERY candidate, always. The journal is full of cycles declining on exactly it, and
that was never a finding about those trades. One grid with a `drift` parameter now (there were two
copies of the loop, which is how the market view and the agent's view came to be computed by
different code), and both columns render. Live, first cycle after the change, the agent built its
own comparison table of "EV at my view" against "EV at market drift" across four structures and
declined all four because the edge lived entirely in its own drift assumption - the comparison the
column exists to enable, and one it could not have made before.

**Two clocks, and the weekend one was the wrong one.** `bs_greeks`/`expected_move` used
vol-days/308 while the lognormal grid used calendar/365 - greeks and probabilities for one position
on different axes, rendered side by side. Choosing which survives is the part that matters: OPRA
inverts Black-Scholes with T = calendar/365, so a Friday IV is ALREADY deflated by the weekend it
spans (that is the Monday IV jump, seen from the price side), and discounting it again shrinks the
modelled Friday-to-Monday move to 89% of what the option's own price implies - in the direction
that makes short premium look safer than it is. D-051's observation is right; it was being applied
to a number that already carried it. Inert in production only because no caller ever passed
`start`, which made it a landmine for whoever supplied the missing argument. `start` is now
accepted and ignored, and that is a test. `vol_days` survives for the job it IS right for, and
`implied_vs_realized` is new: implied annualises over 365 calendar days, realized over 252
sessions, and comparing them raw understates implied by 17% every time. **The bootstrap had the
same bug in reverse** - it drew one daily return per CALENDAR day, 1.45x too much variance on a
6-day tenor, so a fifth of every "the tails disagree" warning was units rather than tails.

**Cost: 62% cheaper per decide cycle, measured, with better output.** The bill was $11.63, $10.37 of
it 18 Opus decide calls, 81% input tokens. Three levers: compaction (above), one MCP session per
tick instead of one `uvx` subprocess PER TOOL CALL (12.3s for six calls against 2.75s; 515 server
spawns in one run log), and prompt caching, which was simply absent. A cache breakpoint at the end
of the opening message covers tool schemas, system prompt and prompt together. Verified safe across
the fallback chain - gpt-5-mini and gpt-4o-mini both accept a `cache_control` block and ignore the
key. The ledger had to learn about it too: `usage_metadata.input_tokens` is the TOTAL and already
includes cached tokens, so pricing them at full rate would have made caching look free of benefit;
cached share is now a column in `trdrbot usage`, and a zero next to a large `in` means caching is
not engaging. Adjacent cycles, same command: **$3.46 -> $3.12 -> $1.32**, wall clock 5:19 -> 1:56.

**Also fixed:** `health` read a subsystem's own OUTPUT rows as evidence it had RUN, making three
probes tautologies - `interim_scoring` reported "ran 8x, produced 8" off day-one rows for two days.
A heartbeat must be a DIFFERENT record from the output, or "ran" and "produced" are the same number;
`interim_run` now carries eligible/scored, and a produced-then-stopped subsystem no longer reads as
healthy. `Ledger.register` deduped across `probability_stated`, so a standalone forecast could be
swallowed by a pre-registration placeholder and its stated probability never written - D-062's
exact symptom in the one place D-062 did not look.

**Not fixed, recorded:** the exit-rule engine has still never fired on live data and the book is
flat, so both the corrected arithmetic and the new reachability warning remain unexercised in
production; interim scoring is fixed but unfired for want of an open position; the muse still dates
every forecast at the far horizon (D-070 fixed the guidance in `record_forecast`'s docstring only);
ESTABLISH is barely a promotion, since its Kelly ceiling keeps size at the exploration allocation
for essentially every payoff tested; and Kelly still uses max_profit/max_loss as the payoff ratio
against p = P(profitable), which are two different events - the same grid could produce a
conditional E[win]/E[loss] instead, deferred because it changes what the size tool means and this
pass had already changed the gate.

**Verified:** 173 default tests (14 new, one per defect) + 14 contract tests against real Alpaca,
real elfmem 0.20.0 and real LLMs. Two live decide cycles on the fixed code, one of which produced
the two-column EV table above.

## D-075: elfmem 0.20.0
**Date:** 2026-08-28
**Status:** accepted
**Context:** `uv lock --upgrade-package elfmem` on the `elfmem_index` branch, `cebc242e` ->
`9527951c` (0.20.0.dev0 -> 0.20.0).
**Verified against the real library, not re-pointed:** 14 contract tests pass, including the two
beliefs D-073's credit weighting rests on - that `ScoredBlock.similarity` is min-max normalised
within a result set, and that elfmem's `_validate_weight` rejects `weight <= 0`. Both still hold,
so `CREDIT_WEIGHT_FLOOR` is still load-bearing for the reason it was introduced. 173 default tests
pass unchanged.
**Still open upstream:** I-5, `history()` raises `TypeError: '<' not supported between instances of
'str' and 'int'`. Re-checked directly against 0.20.0 on the live database - unchanged. Per-block
audit trails remain blocked. Carry to the next elfmem report.

## D-076: What has to be true - breakeven vol, dominant risk, and a memory that was one-sided
**Date:** 2026-08-28
**Status:** accepted
**Context:** A professional options-trader review of the live decision log, an optimize simulation
of the response, then implementation. Traced in
[notes/014](notes/014_trader_critique_and_response.md). D-074 asked whether the code did what it
claimed; this asks whether the DECISIONS were good.

**The measured problem: 18 theses simulated since the ledger began, ZERO traded, while all five
price forecasts recorded instead were holding at review.** The views were right and none was
expressed - the signature of a miscalibrated gate, not of bad judgement. The individual refusals
were mostly correct (the 765/760 credit spread needs an 84% win rate against its own 72-83% models;
resisting the pull to repeat its one prior winner was genuinely good discipline). The AGGREGATE was
not: four defensible haircuts - a 21-day vol anchor, the bootstrap fat-tail correction, full
round-trip friction, a drift haircut - multiply into a structural no, so the system can only trade
in high-vol regimes, which is where its edge claims are weakest.

The vol anchor did most of the work. Same tape, same day: **SPY realized 11.3% over 21 sessions and
5.9% over 5**. The agent quoted the 21-day figure against a 5-day horizon and dismissed the 5-day
as "one quiet week, not a forecast" - true, and 11.3% is not a forecast either, it is a different
backward window chosen because it is the cautious one. Nothing in the system made that a choice it
had to defend.

**Choice: report what has to be TRUE, not what the EV is at one assumed vol.**
`optmath.breakeven_vol` and `breakeven_drift` return the value at which EV after costs crosses
zero; `dominant_risk` says which of the two the structure actually lives on. Every candidate now
carries a `NEEDS` line: "a VOL bet (3x) | wins if realized vol < 7.5%" or "a DIRECTION bet (9x) |
wins if drift > 0.1%". "EV is -$20" hides the input that produced it; "wins if realized comes in
under 7.5%" is a claim the tape can settle.

**Two candidate mechanisms were killed by the grounding lever before any code was written.** EV
across a 6-14% vol band does NOT discriminate (condor -$92..+$95, the bad put spread -$71..+$24 -
both straddle zero), and neither does the margin over a structure's breakeven win rate (both come
back "vol-dependent"). Only the breakeven vol ranks them and names the bet. Recorded because a
plausible mechanism that fails a five-line computation is worth more as a rejected candidate than
as a shipped feature.

**The simulation then forced a correction that changes the shape.** Breakeven vol alone would have
been wrong: measured on ONE board and ONE expiry, an iron condor moves $9 per 1% of spot against
$23 a vol point, while a call spread moves $199 against $22 - opposite bets priced off one
volatility assumption, and only one of them cared. So the `NEEDS` line leads with the dominant
risk. And EV is NON-MONOTONE in drift for a range structure (a condor peaks at zero drift and falls
away both sides), so the breakeven there is a BAND - bisecting from the endpoints would have
reported a confident wrong number for every range structure this book trades. Hence a generic
scan-then-bisect over a grid, the same shape as the existing `breakevens()`, with no crossing at
all reported ("EV positive at every vol tested") rather than hidden.

**The finding a desk would care about most, which fell out of `dominant_risk`: a far-OTM credit
spread is not a premium-selling trade.** The 765/760 put spread classifies as a DIRECTION bet at
10x. It has the shape people associate with theta harvesting - high win rate, small credit, short
vega - while its P&L is dominated by where the underlying goes. That is why it looks like the safe
choice and is the riskiest thing on the board. Written to the wiki as
`technique/what-am-i-actually-betting-on`.

**Memory: the amendments matter as much as the additions.** Routed per the constitution's own
`[routing]` principle. New SELF principle `[assumptions]` - "An input I chose is a judgement, not an
observation. Caution compounds - haircuts stack into a verdict nobody chose. I test my answer
against the alternative input" - because that residue is not enforceable by any check. **Rejected: a
principle saying "abstention is a position".** The agent had already WRITTEN that policy itself, in
three separate cycles, and declined anyway; a principle it already believes is how a constitution
becomes decorative.

The lesson set turned out to be **asymmetric - five of six lessons pushed toward "no"** - and the
worst offender was `friction-is-the-size-of-the-edge`, which ended "I have declined roughly ten
cycles on this basis and been right to": a claim never scored, sitting in the block most likely to
be recalled when a structure looks attractive. Amended to say so. `exploration-budget-is-not-a-
mandate` amended too: the agent quoted its "roughly neutral EV" bar accurately while declining
structures it had itself priced at -$0 and +$4, which are INSIDE that bar. Two new lessons:
`the-window-i-quote-is-a-forecast` (the 11.3%-vs-5.9% incident, pointing at the new breakeven line)
and `abstention-has-a-price` (the 18-and-0 record, and that a decline leaves exit rules unfired,
attribution empty and the ladder stuck). **Stacked conservatism was not only in the arithmetic; it
was in the memory.**

`[assumptions]` takes the constitution to **427 of its 430-token ceiling** and the live SELF frame
to ~580 of elfmem's 600, verified by rendering it. It is FULL: the next principle requires retiring
one, and raising the ceiling past the frame's own budget buys a silent drop rather than room.

**Verified live**, unprompted, on the first forced cycle after the change: *"I forecast 8.5%
realized and the condors needed sub-7.5%"* - a stated vol number against a breakeven, where before
there was a selected backward window presented as an observation. And, citing the amended lesson by
name against itself: *"My memory warns me that declining a +$4 to +$7 structure is an unstated
over-cautious rule, and I did just decline a +$7 structure... If I pass on a similar structure next
cycle with similar reasoning, that's a pattern worth challenging, not a principle worth
congratulating myself on."* It still declined, which is a legitimate answer - but on grounds the
tape can settle rather than on a hidden input.

**Deliberately NOT built, and the reason matters:** the vol forecast is now STATED but not SCORED,
so it moves no calibration and buys no size - which is most of the point. Resolving it needs
`market_stats._rolling_vol` over stored closes (no network, no LLM) and one `metric` field on a
ledger Entry. That is the highest-value next step. Also unbuilt: armed entry triggers (the agent
committed to "775/785 at <= $2.10 -> act", it hit $1.62 six hours later, and no cycle ever
re-checked - every cycle is a cold start that discards the previous one's commitments), and the
decline ledger with regret scoring.

**Verified:** 179 default tests (5 new) + 14 contract tests. Constitution renders 11/11 principles
at 580 tokens; 8/8 lessons recall by their cue.

## D-077: Kelly's payoff ratio, horizons that resolve in time, and a contract that caught itself
**Date:** 2026-08-28
**Status:** accepted
**Context:** Closing I-13 and I-11 from D-076's deferral list. Both turned out to be bigger than
their one-line descriptions, and the work surfaced two further findings - one of them by a
contract test failing exactly as designed.

**1. Kelly's `b` and Kelly's `p` were different events (I-13).** Sizing passed
`max_profit / max_loss` for the payoff ratio while passing P(profit > 0) for the probability. A
vertical reaches its max profit in only PART of the region where it profits at all, and its max
loss in only part of the region where it loses - so the pair described two different events. That
is not a conservative approximation, it is a DIRECTIONAL one, and measuring it on real structures
at live quotes shows which way:

    bull put 765/760     max/max 0.19  ->  conditional 0.26   (understated 35%)
    iron condor          max/max 0.59  ->  conditional 0.66   (understated 11%)
    call debit 775/785   max/max 5.17  ->  conditional 2.94   (OVERstated 43%)

Credit structures win near their max and lose well short of it; debit structures are the reverse.
**So the formula was biasing the book toward BUYING premium and away from selling it, structurally,
at every sample size** - a preference nobody chose and nothing recorded. `optmath.payoff_ratio`
returns (E[win|win], E[loss|loss], ratio) off the same lognormal grid the probabilities come from,
and `kelly_fraction` takes it as `b`. The agent's own probability is deliberately NOT replaced:
it supplies `p`, calibration shrinks it, the model supplies the payoff shape - the same
facts-and-models split the rest of the module keeps.

**Guarded against its own degenerate case:** a conditional expectation needs something to condition
on, and dividing by the mean of an essentially empty side manufactures an enormous ratio out of a
corner of the distribution - which sends Kelly to `p`. Below 1% mass on either side the ratio is
refused and the caller falls back. **Matched scale-invariantly on RISK/REWARD**, because the model
quotes per-contract figures while `simulate` priced whatever quantity the legs carried, so matching
on dollars fails on every multi-lot candidate. Ambiguity returns None rather than guessing, and the
fallback is stated in `explain()` - a silent switch between two `b` values that differ by tens of
percent is exactly the invisible change this project keeps finding.

**2. Horizons: three sources, three different rules, none of them right (I-11).**
`record_forecast` argued for 1-3 days in prose, `discovery` allowed anything up to and INCLUDING
the deadline, and `muse` allowed 1-10 days with **no deadline check at all** - it could emit a
thesis resolving after the competition ended. `competence.forecast_window` is now the one rule all
three ask, deriving (earliest, preferred, latest) from the deadline rather than each carrying its
own day-count. A thesis resolving ON the deadline can never inform a decision; that is the day
everything is force-closed.

**The first version of this made the mistake it was fixing.** It returned only a preferred date and
the prompt said "prefer {preferred} or earlier" - and the muse read that exactly as written and
dated a candidate TODAY, which resolves in zero days and was thrown out by the very next gate. A
one-sided instruction invites the degenerate end of it. Hence `earliest`, and a prompt that states
a window with two sides and asks for candidates SPREAD across it - plus an explicit "do not crush a
multi-step thesis into one session just to be early", because the muse's mandate is domino chains
and those need room to fall. Live before: five forecasts, every one on 2026-09-03. After:
2026-08-30, 08-31, 08-31, 09-02, 09-03, and one emitted where the previous run emitted none.

**3. A truncated JSON array threw away four good candidates for a fifth half-written one.** Found
running the muse: a 6,745-char reply opening with a perfectly good `[{"underlying":"S"...` parsed
to NOTHING - one LLM call spent for zero output. The outer-bracket salvage cannot help an
unterminated array, because `rfind("]")` lands on an INNER bracket. `_parse_json_block` now
salvages complete elements using the stdlib decoder's incremental mode (so a brace inside a string
cannot fool it), and says loudly that it did. **Ordering matters and is tested:** with exactly one
complete element written, `rfind("}")` finds that element's own closer, so the object salvage
succeeds and returns a DICT where the caller unpacks a list - a truncated array quietly becoming a
single candidate is worse than returning nothing. Array salvage therefore runs first when the reply
opens with `[`.

**4. A contract test caught its own premise going stale, which is the whole point of the file.**
`test_frame_similarity_is_min_max_normalised_within_the_result_set` failed - not from any change
here. D-073 built `credit_weight` on elfmem min-max normalising each recall (worst match exactly
0.0, best exactly 1.0) and reported a 4x credit differential. Measured now that the block pool has
grown: a recall returns a filtered top SLICE, similarities cluster at 0.926-1.000, and **the
differential is about 1.05x**. Deliberately NOT "fixed" by renormalising ourselves: a block
returned at 0.93 genuinely is relevant, and forcing a 4x split across near-identical scores would
invent discrimination the data does not contain. The irrelevant-block case D-073 was built for - a
SPY mind model scoring 0.0 against an NVDA query - simply does not come back any more. The test now
asserts what remains load-bearing and true (similarity is bounded in [0,1] and can arrive anywhere
in it, so the floor stays mandatory), and I-18 records the collapsed differential.

**Also fixed, self-inflicted:** the new prompt-cache contract test assumed the first call always
WRITES the cache. It runs against a shared 5-minute TTL, so a re-run inside that window finds the
prefix warm and the first call reads - the test passed once and failed on the very next run. It now
asserts the belief that actually matters (a marked prefix is served from cache at all), not which
call paid to put it there.

**Verified:** 187 default tests (8 new) + 14 contract tests. Live muse run with spread horizons and
a candidate emitted; live simulate showing the PAYOFF line and sizing picking the conditional ratio
up through a 10x quantity change.

## D-078: The wiki ages by policy - durable concepts, tombstoned snapshots, no deletions
**Date:** 2026-08-28
**Status:** accepted
**Context:** A worry that the wiki would fill with stale documents nobody updates, removes or
references. Investigating it corrected a claim I had made one answer earlier - that
`research/*.md` was write-only - which was wrong and made the problem worse than described.

**The dossiers ARE read back, at random, by the muse.** `_sample_concepts` draws uniformly from
every non-position markdown file and hands the first 400 characters to the collision prompt. That
window runs straight past `# What it is` into `# Bull case`, so on 2026-08-28 the muse's actual
seeded pick included `research/NVDA.md` at 15.8 hours old and read **"Closed 228.17, +5.2% on the
week"** as raw material - against a live tape of 223.90, **-1.8%**. Stale wiki content was not
inert clutter; it was an unlabelled input to thesis generation.

**Measured scale of the defect:** 22 of 28 dossiers had a contaminated durable section, because
`discovery.py`'s template welded a durable field to a perishable one in one sentence -
`f"# What it is\n{company} - {why_interesting}"` - producing "Affirm Holdings, Inc. - Strong Q4
results with revenue and adjusted EPS beats". `research.py`'s template was clean, so the two
writers of the same file disagreed about what the heading meant.

**The reframe, and it is the whole decision: the files were never the problem.** An optimize
simulation over ten frozen scenarios first tried expiring stale dossiers out of the muse's pool -
which fixed freshness and BROKE the muse, because on a day with no research run every dossier
expires and the pool collapses to two files. Labelling instead of excluding scored better but
still handed the model a dead number to argue from. What actually dissolves it is reading the
**durable half**: a company dossier's "what it is" is true next month, its "bull case" is a
snapshot of a tape that has already moved. Read the durable section and a stale document stays
useful, so nothing needs excluding, so nothing can starve - and colliding a month-old concept with
today's news is the muse's MANDATE, not a defect. It is also the constitution's own `[routing]`
principle applied one level down: **today's prices are an event, and events belong in the journal,
not in a standing note.**

**Choice, four parts:**

1. **`wiki.LIFECYCLE`, a per-type policy table, enforced at the write path.** A type absent from it
   **cannot be written** - `LifecycleError`, naming the fix. This is the consistency mechanism: a
   new document type must declare how it ages before it can exist, the same way the augmentation
   guard already refuses a write that drops a heading. OKF leaves `stale_after` to the implementer
   and says so plainly - *"who sets it, and to what, is the one decision that determines whether a
   wiki decays gracefully or noisily"* - and D-022 had adopted it for `context/*` only, before
   discovery existed and before dossiers reached 28. `research.py`'s hand-set `stale_after` is
   deleted: policy is the single source, because a per-caller stamp is how two writers of one file
   come to disagree about when it expires.

2. **`Concept.durable_text()`, and the muse reads it** instead of the first 400 characters. Falls
   back to the whole body when a type declares no durable section or the section is missing - a
   half-written page must lose its freshness, never lose the page.

3. **`discovery.py` stops welding.** Its nominate schema gained a `what_it_is` field asked for as
   a durable one-liner, with a fallback to `company`. Both dossier writers keep the SAME five
   headings, deliberately and now under test: they share the file, and the augmentation guard
   refuses a write that drops a heading, so divergent templates would make the second writer's
   updates silently fail. Verified live - AFRM now reads *"Offers point-of-sale financing and
   consumer credit products to merchants and shoppers (BNPL...)"* where it read *"Affirm Holdings,
   Inc. - Strong Q4 results with...beats"* an hour earlier.

4. **A housekeeping sweep that tombstones and never deletes.** `status: deprecated`, in place.
   **Deletion is refused on principle** - OKF's own answer to a dead concept is tombstone-in-place,
   and every other store here is append-only (journal, ledger, position pages). **Archiving by
   moving files is refused on mechanics** - a file that moves can be missed mid-read by a
   concurrent consumer; a frontmatter flag cannot, and the page stays where anyone looking for it
   will look. The sweep is position-aware: a ticker we hold is never retired, because a position
   outlives the research cadence and the page explaining why we are in a trade is the worst
   possible thing to retire mid-trade. `touch_generated=False` so a tombstone does not leave the
   page looking freshly researched. Revival needs no separate path - re-researching rewrites the
   page and `write_concept` restores `status: stable`.

**Also fixed: `sources[]` grew without bound.** `add_source` minted `src-{len+1}` every call, so
the id was always new and the entry always appended - `research/NVDA.md` carries four identical
`computed:market_stats` rows, one per research pass. Four copies of one source are not four
credibility signals; OKF's signal is `last_modified`, and it is now refreshed in place, keyed on
(resource, author). Existing duplicates are left alone rather than compacted, because the
augmentation guard would refuse a write that shrinks `sources` - our own rule, correctly applied
to us. The bloat stops growing, which was the part that mattered.

**Migration is fail-safe by construction.** `is_stale()` returns False with no `stale_after`, so
the 24 legacy dossiers are never swept until they pass through the new write path. Nothing is
retired on the strength of a policy it was never written under.

**Rejected:** automatic deletion (contradicts OKF, contradicts append-only, unrecoverable); moving
to `research/archive/` (race-prone for no benefit over a flag); expiring stale dossiers out of the
muse's pool (starves it on any day without a research run); a background re-verification cadence
(OKF explicitly declines to specify one, and there is nothing to re-verify - the durable half does
not decay).

**Verified:** 197 default tests (10 new, one per frozen scenario including starvation, the
held-position exemption, revival, and template divergence) + 14 contract tests. Live discovery run
writing a clean split, and the exact NVDA collision that was poisoned this morning now reads
"Nvidia designs the GPUs and accelerated-computing platforms..." with no price in it.

## D-079: Scaffold - the payoff fix has an exact property, and friction had one gap left
**Date:** 2026-08-28
**Status:** accepted
**Context:** A scaffold run over a zoo of 25 option structures - verticals both ways, condors wide
and narrow, a butterfly, a straddle, a strangle - sweeping the whole decision stack and checking
the invariants a desk would insist on. `tests/scaffold_structure_zoo.py`, re-runnable.

**The method is what made it decisive.** Every structure is priced at its expected intrinsic under
**the same lognormal grid the stack prices with**, so a fair bet is fair BY CONSTRUCTION. Any edge
the stack then reports on one is an artefact of the stack, not of the market. That converts a vague
"is the sizing biased?" into an exact measurement.

**D-077's conditional payoff ratio turns out to have an exact property, not just a smaller bias.**
With `b = E[win|win]/E[loss|loss]` and the model's own `p`, the algebra collapses: EV = 0 implies
`p*E[win] = (1-p)*E[loss]`, so `b = (1-p)/p`, so Kelly `= p - (1-p)/b = 0`. **Kelly is zero exactly
when EV is zero, so their signs agree.** Verified across the whole zoo: conditional Kelly came back
+-0.000 on every fairly priced structure, while max/max ranged to **-2.313** on bets with precisely
zero edge.

The shape of that old bias is worse than D-077 described. Expressed as the probability the agent had
to claim for the gate to open, against the structure's own fair win rate:

    put credit 95/100      fair 63.9%   gate opened at 74.4%   +10.5pp penalty
    iron condor (wide)     fair 87.0%   gate opened at 95.5%    +8.5pp penalty
    call debit 100/105     fair 35.2%   gate opened at 25.1%   -10.1pp FAVOUR
    call debit 103/108     fair 16.6%   gate opened at  7.3%    -9.3pp FAVOUR

The negative rows are the dangerous ones: **the gate opened BELOW the fair rate**, so an agent
claiming 10% on a structure whose honest win rate is 16.6% - a claim of NEGATIVE edge - would have
passed and been sized. After the fix every row reads +-0.0pp: the gate opens exactly when the agent
claims more than the market-implied probability, which is the correct economic criterion and is now
exact rather than approximate.

**The gap the scaffold found: the sizing gate could not see friction.** `size_position` decided on
GROSS edge while the agent read EV after costs - two layers disagreeing about cost, the same defect
class as two clocks (D-074) or two calibration numbers (D-076). Measured as the extra edge needed
beyond what the gate demanded, purely to cover the round trip:

    iron condor (wide)      +1.4pp
    call debit / put credit +4.7pp
    iron condor (NARROW)   +16.4pp   <- four legs, four spreads, invisible to Kelly

**Fixed by charging friction to BOTH conditional expectations**, since it is paid whether the trade
wins or loses. The same algebra as above then makes the gate open at exactly `(E[loss]+f) /
(E[win]+E[loss])`, which IS the condition for EV-after-costs to be positive - verified at +-0.0pp
across every structure. A structure whose entire expected win is eaten by friction returns None
rather than a negative ratio: there is no payoff to bet on, and sizing should refuse rather than
compute with it.

**What the scaffold confirmed already held:** conditional expectations stay inside each structure's
own max profit/loss; a fairly priced structure breaks even at exactly the vol it was priced at
(25.00% across the zoo, the cleanest possible check that the root-finder finds the right root);
`dominant_risk` classifies condors, butterflies, straddles and strangles as vol bets and every
vertical as a direction bet; and size is monotonic in evidence across 25 structures x 9 sample
sizes, 0 inversions.

**One honest reading recorded rather than fixed.** The reachability check fires on lopsided
structures - a deep-ITM debit spread whose max profit is 2% of its premium cannot reach a +50%
target, a far-OTM credit spread whose max loss is 8% of its credit cannot reach a -50% stop. Both
are correct warnings. The related case, a far-OTM condor collecting a tiny credit where a "-100%
stop" fires on a trivial move, is left alone because sizing already refuses it upstream: at a
conditional payoff of 0.07 the gate needs a claimed 93.5%. The layers cover each other, which is
what balance looks like.

**Verified:** 205 default tests (8 new, one per scaffold invariant) + 14 contract tests. Live board
after the change shows the condor at "wins if realized vol < 7.6%" with a post-cost payoff of
0.42:1 against a max/max of 0.59.

## D-080: Retrospective - half the calibration sample was material the system had rejected
**Date:** 2026-08-28
**Status:** accepted
**Context:** A request to retrospectively score the theses on the ledger and derive optimal
sizing. Only 1 of 38 had matured, so no outcome retrospective was available - but running the
underlyings' own price history against every band surfaced something worse than a missing answer.

**Bands placed at prices that do not exist.** NVDA at **[650, 920]** against a spot of 218.97.
QQQ **[355, 385]** against 716. MSTR **[420, 860]** against 126.87. WDC **[45, 72]** against
462.41. These are not wrong theses; they are real-world price levels recalled from model
training data, the `[premise]`/D-032 failure class arriving in the muse's band placement.

**The muse caught almost all of them. The ledger recorded them as claims anyway.** The journal
holds the ground truth - every candidate's fate: **15 muse candidates, 13 REJECTED** by the
muse's own gates (6 for a 0% base rate, 3 vacuous at 99-100%, 3 implausible bands, 1 horizon
already in the past). All 15 were registered with `probability_stated=True`, so **50% of the
incoming calibration sample was material the system had already refused.**

The damage runs both ways and both directions move real size through `shrink_probability`: the
unreachable bands resolve FALSE and crater reliability; the vacuous one-sided ones (MRVL [74,-]
against a spot of 217.50) resolve TRUE and inflate it. It is D-070's finding 5 in mirror image -
there, vacuous forecasts could earn size on evidence of nothing; here, rejected garbage destroys
it just as cheaply. The whole batch was due to land 09-01 to 09-03, taking calibration from n=1
to n=26 in one step, one day before the deadline, with half of it noise.

**Cause: registration and belief were the same event.** `muse.run` pre-registers every candidate
before any gate can discard it - correct, and deliberate: the multiple-testing correction needs
the trials that FAILED (D-052). But `Ledger.register` defaults `probability_stated=True`, so a
trial was born as a claim.

**Choice: a claim earns the right to be scored.** The muse now registers with
`probability_stated=False` and `Ledger.mark_stated()` promotes only after every gate has passed.
Trial count N is unchanged - the DSR correction still sees all 15. A test pins the ordering:
every rejection path must appear before the promotion, or a reject is scored.

**The record was repaired from the journalled fates, not from recomputation.** Recomputing base
rates today would use today's spot against a band placed against a different one, so the journal's
own contemporaneous verdict is the only honest ground truth. 13 rows downgraded to trials with the
rejection reason appended to their notes; nothing deleted; `ledger.jsonl.bak-before-repair` kept.
Calibration sample: 26 -> **13 stated claims**, 38 trials unchanged.

**On sizing, the answer is not the sum of the individual Kellys.** Scoring the 13 surviving claims
against each underlying's own demeaned bootstrap (fair odds `b = (1-base)/base`, Kelly on the pure
view, which isolates VIEW quality from expression quality):

    9 of 13 carry a positive Kelly
    naive sum of individual Kelly fractions      321.7% of bankroll
    effective independent bets (inv-Herfindahl)    2.0 of 9   <- five of the nine are SPY
    mean single-bet Kelly                          35.7%
    correlation-aware aggregate (mean x n_eff)     70.6%
    -> naive sizing overbets by 4.6x

**Correlated Kelly bets must be scaled to the EFFECTIVE number of bets, not the raw count.** That
is the professional answer to "what should optimal sizing have been", and it is the one thing no
current mechanism computes: the per-underlying cap counts NAMES, and `[correlated-names-are-one-bet]`
says in prose what `n_eff` says as a number.

The house rules then bind well below any of it - quarter-Kelly, then EXPLORE's fixed 2.2% seed,
then the 15% book cap ($15,187 on $101,250 against a correlation-aware full-Kelly $71,506). So the
caps were doing the work the correlation adjustment should have been doing explicitly, which is
luck rather than design, and it will stop being luck at SCALE and MATURE where the multipliers rise.

**Recorded, not fixed:** `n_eff` is computed here in analysis and nowhere in the system. Surfacing
it next to `n` on every calibration and sizing surface is the natural follow-on (I-21).

**Verified:** 207 default tests (2 new). Live calibration now reads 1 resolved of 13 pending
claims rather than 26.

## D-081: n_eff everywhere, and never ask a model for a number it can only recall
**Date:** 2026-08-28
**Status:** accepted
**Context:** Closing I-21 and I-22 from D-080, plus a decision on whether to keep rejected theses.

**1. `n_eff` next to `n`, on every surface (I-21).** `n` counts forecasts; `effective_n` counts
BETS - inverse-Herfindahl over the underlying each forecast is about. Measured on this ledger, 38
theses are **4.2** effective and the 9 positive-Kelly claims are **2.0**, so sizing each at its own
Kelly overbets by 4.6x. `Forecast` gained a `subject`, threaded from `Entry.underlying` and from
`record_position`; `Calibration` gained `n_eff` and a `sample_note()` that says *"26 forecast(s),
8.2 effective (32% of face value - concentrated in a few names, so it says less about NEW ones than
the count suggests)"*. It appears in `verdict()`, in `trdrbot calibration`, and in the decide
prompt.

**Deliberately REPORTED, never gated, and a test enforces that** (`n_eff` must not appear in
`sizing` or `competence`). Two different questions were nearly conflated: calibration asks "when I
say 70%, does it happen 70% of the time", and repeated forecasts on one name at different bands and
horizons are genuinely separate judgements even when their outcomes correlate. Concentration is a
reason to distrust GENERALISING from the sample - a judgement for the reader, which is exactly
D-009's report-don't-gate posture. The place correlation genuinely must bite is PORTFOLIO sizing,
where the beta-weighted book delta already measures it directly.

**2. Never ask the model for a price (I-22).** The muse was asked for "band_low/band_high are
PRICES IN DOLLARS" and given concepts, news and odds - **no spot, anywhere in its prompt.** So it
answered from training data: NVDA [650, 920] against a spot of 218.97, QQQ [355, 385] against 716,
MSTR [420, 860] against 126.87. D-078 made this marginally worse by removing the stale price that
used to leak through the dossier's first 400 characters - a worse anchor, but an anchor.

**A central price service would NOT have fixed this**, which was the tempting answer. The muse
names ARBITRARY underlyings; nobody knows which spots to supply until it has already replied. The
real defect is that the project holds a principle it was not applying - research.py's own
docstring: *"numbers are COMPUTED (market_stats), never asked of the LLM"*. So: ask for the
RELATIONSHIP, compute the number. The schema now takes `band_low_pct`/`band_high_pct` as percent
moves from the current price, and `_bands_from_pct` converts them against live closes. No spot
needed at prompt time, no second LLM call, and a level wrong by a factor of three is not
expressible.

Ordering had to change - the price history is fetched BEFORE registration now, because a percentage
cannot become a price without a spot. That is data availability rather than a judgement gate, and
the candidate is still registered whatever happens next, so D-052's trial count is untouched.
`_plausible_band` is demoted from primary defence to backstop.

**Measured, same day, same code path:** the muse went from **13 of 15 candidates rejected** to
**1 of 5**, with bands landing -2.1% and +3.8% from live spot. It had been spending whole LLM calls
to be right by refusal.

**3. Should we capture rejected theses? Yes - and we already did; what was missing is WHY.** A
rejected candidate still carries a band and a horizon, so it still RESOLVES. Comparing "we refused
it" against "it would have held" is a scored test of the GATE's own threshold - it tells us whether
`BASE_PROB_FLOOR = 0.10` is calibrated, at zero cost. That scores the SYSTEM, never the agent, and
the distinction is load-bearing: `probability_stated` stays False so a reject can never reach
calibration (D-080's whole finding). `Entry.rejected_by` now records the gate, structured, on the
row - it lived only in the journal, so "which gate rejects most, and was it right?" needed a manual
join across two stores.

**The test found a real gap while being written.** A count-based check (`_reject` calls >= rejection
paths) passed while one multi-line fate string had no record at all. Rewritten to check each path
individually against the following lines; the missed path - "horizon resolves too late" - is fixed.

**Verified:** 214 default tests (7 new) + 14 contract tests. Live muse run with 4 of 5 candidates
surviving and every band anchored to real spot.

## D-082: Checking whether the issues were fixed found two more
**Date:** 2026-08-28
**Status:** accepted
**Context:** A verification pass over the open issue ledger - reading each "FIXED" claim against
the code rather than trusting the entry. Two entries were stale and two live defects surfaced.

**The exit-rule probe was the same tautology D-074 named, still present in a second place.** A SPY
766/758 bear put spread is now open, `status: open`, with five rules evaluating every tick and a
populated debounce history - **the first time the deterministic capital-protection path has run
against a real position.** Health reported `exit_rules never ran`, because the probe read `exit`
TRIGGER rows as evidence the engine had RUN. "Ran" and "produced" were the same number, so it could
never distinguish an engine that is armed and correctly quiet from one that is not evaluating at
all. Fixed with an `exit_run` heartbeat carrying positions watched, rule-checks performed and
triggers fired.

**Then the test written for that fix found a second defect.** The staleness check (D-074) escalated
the newly-fixed probe to PROBLEM: 40 evaluations with zero triggers looked like a subsystem that
had produced once and died. But **an exit engine is a fire alarm - evaluating every tick and never
firing is the healthy state**, and `work` cannot rescue it because rule-checks are always non-zero
while a rule being CHECKED is not a rule being DUE. Added `Probe.silence_is_normal`, set only where
zero output is the expected steady state and explicitly not as a way to quiet a probe that is
genuinely dead. "Evaluated 40 times, nothing breached" now reads `armed, not stalled`; "positions
open, zero rules evaluated" still reads broken.

**Two issue entries had struck-through titles over unchanged bodies.** I-21 still ended "Surface
`n_eff`... next to `n`" and I-22 still ended "the band step should be too, explicitly" - both
already done in D-081. A resolved issue whose text still reads as action-due is the same
stale-record failure this ledger exists to prevent, appearing in the ledger itself. Rewritten with
what was actually built and measured.

**I-9 was re-stated rather than closed.** The engine being ARMED on live data is genuine progress
and distinct from a trigger, which remains unverified - as does D-074's reachability warning, which
this position did not need (its -65% stop and +140% target are both reachable against the net-cost
base).

**Verified:** 215 default tests (1 new). Live: `exit_rules  ran 1x, nothing breached - armed, not
stalled`.

## D-083: OpenCode Zen / GLM-5.2 - a config-level provider, not a code branch
**Date:** 2026-08-28
**Status:** accepted
**Context:** A request to migrate the model chain to GLM-5.2 via OpenCode Zen. Neither the
provider nor the model existed in training data with confidence, and this system's whole
architecture depends on reliable tool-calling - so this needed real research before any config
edit, not a guess dressed as a decision.

**What research established, from primary sources (opencode.ai's own docs, verified against a
live curl example) rather than search-summary boxes:** Zen serves GLM-5.2 over a standard
OpenAI-compatible `/v1/chat/completions` endpoint at `https://opencode.ai/zen/v1`, auth via
`Authorization: Bearer <key>`, key obtained at opencode.ai/auth. GLM-5.2 is documented as
"agent-oriented" with function-calling support. **Pricing (~$1.40/$4.40 per M input/output) is
sourced from third-party trackers, not Zen's own pricing page directly** - flagged in both
config.yaml and this record rather than trusted silently, per this project's own convention that
pricing is operator-supplied and goes stale.

**A central-provider question first: does `init_chat_model` support this out of the box?**
Inspected the installed package directly rather than trust docs. `provider="openai"` resolves to
a bare `ChatOpenAI(**kwargs)` call (`_BUILTIN_PROVIDERS["openai"] = (..., "ChatOpenAI", _call)`),
so `base_url`/`api_key` kwargs pass straight through - confirming D-008's "a package plus a line
of config" promise holds for THIS layer. It does not fully hold at the next layer up: this
project's config (`model_chain`) hands every model in a role's chain the SAME global kwargs, and
Zen needs a DIFFERENT `base_url` and a DIFFERENT key than the `openai:gpt-5` entry already sharing
that chain, using the identical `openai:` prefix. Threading `base_url` globally would silently
redirect the real OpenAI fallback to Zen too.

**Choice: `llm.providers`, a config-level indirection resolved by one function, `Config.
resolve_model_spec`.** A spec prefixed with a declared provider name (`"opencode_zen:glm-5.2"`)
resolves to the real `init_chat_model` spec (`"openai:glm-5.2"`) plus per-spec connection kwargs;
any other spec passes through unchanged - verified directly: `resolve_model_spec("openai:gpt-5")
== ("openai:gpt-5", {})`. **Both call sites that build a model from a spec string share this one
resolver** - `llm.build_model()` and `cli.py`'s independent `doctor` probe loop, which calls
`init_chat_model` directly and would otherwise raise "unsupported provider" on the new spec the
moment it landed. A second, undiscovered call site silently disagreeing with the first is exactly
the class of bug this project keeps finding (the SELF-preamble rename living in one caller, D-063;
attribution bypassing the consolidate-retry fix, D-072) - so this is a one-function fix on
purpose, not a helper duplicated per caller.

**A missing key fails LOUD, at resolution time, naming the fix - and the chain survives it.**
Verified live: with no `ZEN_API_KEY` set, `resolve_model_spec` raises `RuntimeError` naming the
env var; `build_model()` catches it in the same skip-and-continue path every other unbuildable
model already goes through, so `decide` builds successfully off Claude/GPT-5 with GLM-5.2 simply
absent from the chain. **A config edit adding a new primary must never be able to take the agent
offline by itself**, and the existing fallback machinery (verified in D-008 against a real
Anthropic 400) covers a gateway outage or absent key with zero new code.

**Placed as the new PRIMARY across every role, existing models kept as fallback, not removed** -
the literal reading of "migrate," made safe by the fact that nothing is lost if it never answers.
`doctor`'s existing "probe every configured model" loop picks up GLM-5.2 automatically once it is
in the chain, so `uv run trdrbot doctor` is now the operator's verification step once a real key
is added - live-run right now, honestly: `DEAD opencode_zen:glm-5.2  RuntimeError: ... needs
ZEN_API_KEY set`, `4/5 configured models reachable`, and `decide` still builds. That is the
correct state for code that is wired but not yet keyed - not a failure.

**What documentation cannot establish, and was not asserted as fact: whether GLM-5.2 reliably
drives a LangGraph `create_react_agent` tool call through Zen's endpoint.** Every role in this
system needs `bind_tools`, and a model that answers plain chat fine while mishandling tool schemas
would make `decide` look healthy while never calling `simulate_experiments` or `record_position` -
silently, exactly the failure class this project's contract-test file exists to catch externally.
A real contract test was written - real network, a bound tool, asserting the tool call actually
fires AND that the tool's result reaches the final answer - and it SKIPS (not fails, not asserts
success) with no key present, the same discipline `doctor`'s own probe uses. It has not been run
against a real key and its result is not claimed here.

**Verified:** 221 default tests (6 new) + a 15th contract test collected and confirmed to skip
cleanly without a key. Live `doctor` run: config loads, Alpaca connects, GLM-5.2 correctly reports
DEAD and named, the surviving 4/5-model chain answers. `.env.example` and README updated with the
reusable pattern - config-level gateway providers, not a one-off branch - for the next one.

**Action due, before this serves live decisions unattended:** add `ZEN_API_KEY` to `.env`, run
`uv run trdrbot doctor` to confirm GLM-5.2 answers, then `uv run pytest -m contract -k glm` to
confirm tool-calling specifically - that result determines whether GLM-5.2 stays primary or moves
behind Claude/GPT-5 in the chain.

## D-084: GLM-5.2 proved unsafe for structured output; Grok-4.6 is primary, but Zen has it down
**Date:** 2026-08-28
**Status:** accepted
**Context:** Verifying I-23 with a real `ZEN_API_KEY` (added between D-083 and this record), then
a request to try Grok-4.6 instead. Both findings came from actually running the real workload
against the real endpoint, not from reading documentation - the same discipline this project's
whole contract-test file exists to enforce, applied here to two brand-new external dependencies
in succession.

**GLM-5.2's real defect, reproduced deterministically.** The first live muse run under GLM-5.2
returned a 0-character reply. The usage ledger showed `out=8000` - exactly `max_tokens` - meaning
the model spent its ENTIRE completion budget and surfaced nothing. Isolated with a direct repro:
a trivial "reply ok" prompt worked fine (110 output tokens, visible content); the muse's actual
~925-token prompt (5 structured candidates, each with a causal chain, under a strict JSON schema)
returned `finish_reason="length"`, 8000/8000 tokens spent, zero visible characters, on every
attempt. A follow-up probe (500/2000/8000-token budgets on a "write a two-sentence story" prompt)
showed the pattern generally: GLM-5.2 burns a substantial, task-scaling reasoning overhead before
any visible output, and for a moderately complex generation task that overhead can consume the
entire budget with nothing to show. **No documented lever was found to bound it** - unlike GPT-5,
whose reasoning-token overrun at least leaves partial JSON to salvage (D-077's
`_salvage_truncated_array`), this returns nothing at all, and unlike Grok-4.6 (below) there is no
`reasoning_effort`-equivalent parameter in what was found.

**This failure mode does not trigger LangChain's fallback.** A real HTTP error raises an
exception, which `.with_fallbacks()` catches; a "successful" call with useless content does not.
GLM-5.2 sitting in the chain was therefore silently producing zero muse candidates every run it
served - the exact class of quiet failure this project's `health.py` exists to catch, arriving
through the one door that machinery cannot see (a subsystem reporting `candidates: 0` looks
identical whether the market genuinely offered nothing or the model choked on its own budget).
GLM-5.2 is demoted out of every active chain. Its pricing entry stays for reference; I-23 (its
unverified tool-calling belief) is marked superseded rather than resolved, because the question
was never actually answered - the model was pulled before that test mattered.

**Grok-4.6 was chosen to replace it, staying on the SAME `opencode_zen` gateway** rather than
adding a native `xai:` provider (which does exist as a real LangChain builtin,
`langchain_xai.ChatXAI`, confirmed by inspecting `_BUILTIN_PROVIDERS`). Reused the config-level
resolver built in D-083 for exactly this: swapping the model was a pure config.yaml edit, zero
code changes, because `resolve_model_spec` is generic over any model string under a declared
provider. This also preserves the original migration intent (one gateway, one key, one billing
surface) rather than fragmenting across two.

**A real, documented, controllable lever exists for Grok-4.6 that GLM-5.2 lacked:**
`reasoning_effort` (low/medium/high/xhigh, default high) - directly relevant given what had just
been proven about invisible-reasoning-budget exhaustion. It was never tested, because Grok itself
turned out to be unavailable.

**Verified live, not assumed, before wiring anything as primary this time:** Zen's own
`/v1/models` catalog confirms `grok-4.6` is the correct id. The identical key that serves
`glm-5.2` successfully returned a clean **HTTP 500, three times running**, on the plainest
possible prompt ("reply ok", 500-token budget) - ruling out prompt complexity as the cause.
`grok-4.5` (same family, same gateway) returned **503 "Endpoint is unavailable"** - a second,
independent signal that this is Zen's/xAI's own availability right now, not a request-shape
problem on our side.

**Choice: leave Grok-4.6 as the declared primary anyway, because the fallback chain is proven -
empirically, not inferred - to survive a real failure the way it cannot survive GLM-5.2's silent
one.** `build_model(cfg, role="decide")` was invoked directly, live: it answered via
`claude-opus-5` despite `grok-4.6` erroring first. A real HTTP 500 raises an exception, which
`.with_fallbacks()` catches - this is the exact mechanism D-008 verified once against a real
Anthropic 400, now re-verified against a real Zen 500. Every cycle currently pays one wasted call
for it, which is a cost, not a risk. Recorded as I-25 with an explicit retry instruction.

**Two new contract tests, and one of them is EXPECTED to fail right now, on purpose.**
`test_grok_4_6_via_opencode_zen_actually_calls_a_bound_tool` mirrors the GLM belief-test and does
NOT skip on a live provider error, only on a missing key - it fails loudly with the real 500,
which is the correct behaviour for a file whose whole job is naming a false belief rather than
hiding it. `test_the_decide_chain_survives_grok_being_down` is the adversarial case this outage
handed for free: it calls the real `build_model()` chain, not just the pure resolver logic, and
asserts an answer arrives from something OTHER than grok-4.6 - so it will start failing the
moment the outage clears, which is the intended tripwire to catch the config comment going stale.

**Pricing added with real, corroborated figures**: $2.00/M input, $6.00/M output, $0.50/M cached
input (below 200K-token prompts) - two independent sources converged on the identical number,
stronger evidence than GLM-5.2's single-tracker figure, though still not fetched from Zen's own
pricing page directly (flagged as I-24, now covering both models).

**Verified:** 222 default tests (2 new) + 17 contract tests (16 pass; the 1 expected failure is
the honest report of Grok-4.6's real outage, not a defect in the test). Live: `build_model`
confirmed answering via Claude with Grok as primary and down.

## D-085: GPT-5.6 Sol - the third model tried today, and the first that actually works
**Date:** 2026-08-28
**Status:** accepted
**Context:** After Grok-4.6 (D-084) proved live-down on OpenCode Zen, a request to try GPT-5.6
Sol - explicitly "on OpenAI", meaning direct, no gateway. Researched from OpenAI's own docs page
(`developers.openai.com/api/docs/models/gpt-5.6-sol`) rather than search summaries: model id
`gpt-5.6-sol`, OpenAI's flagship reasoning/coding tier, $4.00/M input ($0.40 cached) / $20.00/M
output - promotional pricing, explicitly time-boxed by OpenAI through at least 2026-11-21 -
1.05M context, 128K max output, function calling and structured outputs both listed as supported.

**Going direct simplified the provider question to zero.** `openai:` is a real `init_chat_model`
builtin and the existing `OPENAI_API_KEY` already covers it - no `llm.providers` entry, no new
env var, unlike both prior attempts today.

**A live 400 caught what documentation would not have, on the first real test.** A trivial
prompt worked; reproducing the muse's actual ~925-token structured-JSON prompt worked too
(`finish_reason: stop`, 2924/8000 output tokens, 1487 of them visible as tracked reasoning
tokens, 6109 valid characters - GLM-5.2's exact failure mode, absent here). But binding a tool
through `create_react_agent` failed outright:

    openai.BadRequestError: Function tools with reasoning_effort are not supported for
    gpt-5.6-sol in /v1/chat/completions. To use function tools, use /v1/responses or set
    reasoning_effort to 'none'.

Every role in this system needs `bind_tools` - this is not a corner case, it is the primary use,
and an unfixed model would 400 on its first tool call every single cycle. Unlike GLM-5.2's
silent empty-completion failure, a raised exception WOULD trigger the fallback chain - but the
declared primary would then never once actually serve, the same wasted-call tax D-084 accepted
for Grok while it stayed down.

**Choice: `use_responses_api=True`, not `reasoning_effort="none"`.** Both were named as valid
fixes by OpenAI's own error message. `reasoning_effort="none"` would disable extended reasoning
entirely to satisfy an API constraint - exactly the false economy this project's own README
argues against for `decide` ("the strongest reasoning... economising here is false thrift").
`use_responses_api` keeps full reasoning and switches the transport. Verified live, twice: a
bound-tool call fires correctly and its RESULT reaches the final answer, both in a standalone
repro and through the REAL `llm.build_model()` path (not a hand-assembled approximation) via a
new contract test. Constructor-callback usage tracking (D-062) was also verified to survive the
Responses API's list-shaped content - 2 calls recorded, correct bare model name `gpt-5.6-sol`
(matches the pricing table), correct costs.

**The fix needed a mechanism this project didn't have until today, and D-084 already half-built
it.** `use_responses_api` must apply to ONE spec, never globally - `ChatAnthropic` has no such
kwarg and would break the moment Claude shared a chain with it, the identical reasoning that
made `llm.providers` per-spec rather than global. But this is a MODEL quirk, not a PROVIDER
one - `openai:gpt-5.6-sol` needs no base_url or key override, so `llm.providers` (keyed on
prefix) is the wrong shape for it. `Config.resolve_model_spec` gained a second layer,
`llm.model_options`, keyed on the exact spec string as written in `models`/`roles`, merged in
after (and composable with) any provider-level override. One test constructs a synthetic case
where both apply to the same spec at once, to prove they don't clobber each other now that
nothing in the live config actually needs both simultaneously.

**Placed as PRIMARY across every role**, Grok-4.6 and GLM-5.2 both fully removed from the active
chain (not merely reordered) - Grok because it costs a wasted call every cycle for no live
benefit (I-25 stands, low priority now), GLM-5.2 because its failure mode is silent rather than
merely wasteful. Claude and GPT-5 remain the verified fallback.

**Verified, end to end:** `uv run trdrbot doctor` - 5/5 configured models reachable, primary
answers. 224 default tests (4 new: primary-pin, `model_options` resolution, the no-leak check
against Claude/plain-GPT-5, and the provider+model-options composition case) + 18 contract tests
(17 pass; the 1 expected failure is Grok's still-live Zen outage from D-084, unrelated to this
change and left in place as the tripwire it was designed to be).

**What this closes:** I-23 (GLM tool-calling) stays superseded rather than answered - moot, the
model was pulled first. I-24 (third-party pricing) is now partially resolved: gpt-5.6-sol's
figure is the first of three today sourced from the provider's own page directly, though still
time-boxed and needing a re-check after November. I-25 (Grok outage) is now low-priority rather
than urgent, since nothing live depends on it answering.

## D-086: interim_scoring's silence check needed two flags, not one
**Date:** 2026-08-28
**Status:** accepted
**Context:** A routine status check hit a live `health` FAIL: `interim_scoring ran 6x, produced
nothing`. Investigated before reporting it, since D-082 already fixed this exact tautology once
for `exit_rules` - checked whether this was a real regression or the same false alarm one probe
over.

**False alarm, confirmed against live state.** The open SPY spread sits at -12.66% unrealized;
`INTERIM_BANDS = (0.25, 0.50)` means nothing is due until 25%. Six housekeeping runs across under
two hours of a freshly opened position had correctly found nothing material - `health` was
reading "eligible every cycle" as evidence of brokenness, exactly the D-074 tautology, in the one
probe D-082's fix didn't reach.

**The first fix attempt was wrong, and a pre-existing regression test caught it before it
shipped.** Applying `exit_rules`' `silence_is_normal=True` flag directly to `interim_scoring`
fixed the live false alarm but broke `test_health_sees_a_subsystem_that_produced_once_and_then_died`
- the test literally encoding the original D-074 bug shape (scored once, then 40 silent runs
despite continued eligibility). The flag's implementation suppressed staleness-after-production
for BOTH the "never yet due" case and the "produced once, now suspiciously quiet" case, because
one boolean was controlling two different verdict paths in `check()`.

**The two cases are genuinely different, not the same question asked twice.** For `exit_rules`,
BOTH are legitimately fine: one trigger closes ITS position, so 40 quiet runs after it predicts
nothing about the next 40. For `interim_scoring`, only the FIRST is fine - "not yet due" is
common and healthy - but the second is exactly the failure this probe exists to catch: a units
bug silently zeroing every score after one correct one is indistinguishable, from `eligible`
alone, from genuine calm. Split into two independent fields: `never_producing_is_ok` (controls
the `made==0` verdict) and `stopping_after_output_is_ok` (controls staleness-after-production).
`exit_rules` sets both; `interim_scoring` sets only the first, so the D-074 regression test's
protection survives unchanged.

**Verified:** 225 default tests (1 new, `test_interim_scoring_does_not_cry_wolf_on_a_calm_young_position`,
plus the existing D-074 regression test re-passing unmodified in behaviour - only its exact
message-matching updated for the shared wording). Live: `health` now reads 0 problems where it
read 1 an hour ago, with the underlying position genuinely unchanged.

## D-087: elfmem off the git branch - PyPI now that upstream merged and published
**Date:** 2026-08-28
**Status:** accepted
**Context:** Upstream merged the `elfmem_index` branch to main and published `elfmem` 0.20.0 to
PyPI. `pyproject.toml` had pinned the git branch directly (D-075's install) because that was the
only place the code existed; the interim dependency was never the goal.

**Change:** `[tool.uv.sources]`'s git override removed; `elfmem[tools]` now version-pinned
(`>=0.20.0`) and resolved from PyPI like every other dependency. `uv lock` picked up the
identical commit (`9527951c`) via the PyPI artifact rather than the branch tip - same code, one
fewer moving part (no branch to track, no git fetch on every install).

**Verified:** `uv lock` resolved clean, 225 default tests pass unchanged against the PyPI
install. `specs/architecture.md` (C19) and `specs/charter.md` updated to describe the current
source; historical branch/commit citations elsewhere (issues.md, elfmem_adapter.py,
test_regressions.py) left as-is since they name where a past fix landed, not the current
dependency.

## D-088: The Coach - subsystems that improve themselves, on evidence, without asking
**Date:** 2026-08-29
**Status:** accepted
**Context:** Every subsystem here improves only when a human-led session finds a defect - D-074's
shakedown, D-076's critique. Designed in [notes/015](notes/015_self_review_loop_brainstorm.md)
(optimize simulation, 10 frozen scenarios, 5 iterations), specified in
[notes/016](notes/016_coach_implementation_plan.md), built here. The first draft of notes/015
routed every finding through human ratification and was rejected on direction: **human approval
gates block the feedback loop this hackathon needs, and paper trading tolerates the risk.** So the
question was never "should it be autonomous" but "what makes autonomy safe to run against a live
system", and the answer is bounded by construction rather than by asking.

**The mechanism: gauges, levers, trials, sentinels - one protocol, registered per subsystem.**
A lever is a DECLARED choice the Coach may change (currently one: the muse's collision prompt).
Variants live as data in `data/state/levers/*.json`, so there is no code path from Coach state to
a gate threshold, sizing math, a sentinel, or its own reward function. The human pre-authorises
the SPACE, not each move - that is the whole replacement for an approval step, and it is
enforceable rather than promised.

**Rewards are computed, never asked.** The muse's own gauntlet already scores its candidates
deterministically, and D-081 measured that reward moving 13-of-15-rejected to 1-of-5 on a single
prompt fix - so prompt quality is known to be visible in it. `p_challenger_better` is Beta
posteriors compared by deterministic grid integration using `math` only (no numpy, no sampling),
so identical evidence returns exactly 0.5 and a test can pin it.

**The critical design decision, and the one a naive build gets wrong: the challenger arm is a
SHADOW.** Running `muse.run` twice - once per variant - would register challenger candidates in
the thesis ledger (inflating D-052's trial count with experiment artefacts and feeding rejected
material into calibration, which is **D-080's exact defect rebuilt by the machinery meant to
improve things**), emit them to the inbox, and double every journal row. The obvious fix - a
`shadow=True` flag threaded through the gate cascade - was rejected because it puts a branch in
every gate, and two arms running subtly different code is this project's most familiar bug (two
EV loops, two clocks, two calibration numbers). **Instead the arms share ONE gate cascade byte for
byte and only the ledger object differs**: `ShadowLedger` is a ledger-shaped null object.

The subtlety that makes it correct: `Ledger.register` returning None **is a gate** in production
("unfalsifiable - no band"). A shadow arm that simply skipped the ledger would skip that gate too
and score the challenger against an easier gauntlet - an unfair trial that would read as genuine
improvement. `ShadowLedger.register` reproduces exactly that one piece of real logic and nothing
else. Both properties are tests.

**Three review findings corrected before the build, each from reading the code rather than the
plan.** (1) `housekeeping` runs only while the market is CLOSED and the muse only while it is
OPEN, so pulsing from housekeeping alone would defer every promotion to the following night - the
Coach now pulses after every muse run as well. (2) The plan's 12-run floor was too slow for the
window; the evidence unit is the CANDIDATE (~5 per run through ~8 gates), so 8 runs is ~40
Bernoulli trials per arm and the floors are config-driven. (3) The muse's per-day RNG seed made
every run in a day collide the SAME concepts - correct at one run per day, but it would have made
every paired trial a repeat of one sample. A derived per-run nonce fixes it without putting a
clock in the seed.

**Fairness across arms is a real failure mode and is handled explicitly.** Both arms share a
per-run memo of the two network-dependent gate inputs (daily closes, options chain), because a
quote moving between the two calls would score as a variant difference - invisible in the results,
and it would slowly promote noise. A challenger LLM call that RAISES is a VOID trial rather than a
loss (D-084's distinction: an HTTP 500 says nothing about variant quality). A challenger that
"succeeds" and parses to NOTHING is scored as full failures - that is GLM-5.2's exact failure mode
and nothing else in the stack penalises it, so a variant that always produced nothing would
otherwise be unfalsifiable by its own reward.

**Two defects found by the tests while writing them, both of the class this project keeps
hitting.** `_score_arm` counted only fates starting `candidate`, missing `EMITTED` - currently
harmless because the trial is recorded before the muse relabels survivors, but moving that call
one line later would have silently under-counted the INCUMBENT and biased every promotion toward
the challenger. Fixed with one shared `coach.survived()` used by both the reward and the gauge.
And the first live mutation echoed the harness's own delimiter lines into the challenger text -
it still formatted, still validated, and would have gone to production carrying two lines of
scaffolding; `clean_prompt` strips it.

**Mutation is validated deterministically before a challenger may enter an experiment**, because
a mutated prompt is a `.format()` template and a stray brace from a JSON example is a live crash
on the next muse run. Checks: every placeholder formats (an unknown one raises here rather than in
production), the schema contract tokens survive, not identical to the incumbent, and a length cap.
**Verified live**: given the real rejection digest, gpt-5-mini read that 10 of 17 recent rejections
were `base probability 0%/100%` and proposed a change targeting exactly that - directed by real
failure data, which is the point. Whether it actually helps is what the A/B test is for.

**Rule 3, enforced by the scheduler, not by sequencing:** a lever's experiment may never be scored
by machinery that same experiment can move. The muse's gates score muse-prompt trials, so a gates
lever cannot run an experiment concurrently. The failure would otherwise be invisible - both
experiments would look healthy while each quietly rewrote the other's ruler.

**elfmem's blocks and the constitution are NOT levers and will not become ones.** elfmem's own
ADR 0003 simulated four architectures for automatic constitutional evolution and none beat
baseline. That is measured evidence, and it is the only thing carved out of the lever space -
everything else is fair game, which is the difference between a bounded design and a timid one.

**Crash safety:** the `experiment_closed` event is appended BEFORE the state swap, so a crash
between them leaves a promoted experiment whose lever state still shows the old incumbent.
`reconcile` re-applies it, idempotently, on the next housekeeping pass - the append-only log is
truth and the state file is a cache of it, the same relationship the journal has with everything
else here.

**Observability replaces the approval gate.** `trdrbot report` writes a self-contained HTML page
(inline SVG sparklines, no external request of any kind - a report that needs the network is blank
exactly when something has gone wrong) leading with what changed, then open experiments with their
posteriors and remaining floors, then every gauge's trajectory with the Coach's own promotions and
sentinel fires overlaid as markers. Steering is by editing state: `paused` stops experimentation
on a lever, `pinned` additionally stops the audit re-matching it, and one pin freezes behaviour
for a demo.

**The muse now runs on the hunt rung**, capped at 3 per UTC day. It was CLI-only, so its lever had
nothing exercising it - a lever nothing runs improves nothing.

**Verified:** 258 default tests (33 new) + 18 contract tests. Live: a real experiment opened
(`v1`, mutation-generated, validated); a full lifecycle driven end to end through 8 paired trials
plus one void to an applied promotion that survived a reload, with the void correctly excluded
from the counts; `trdrbot coach status` and `trdrbot report` both rendering from empty and from
populated stores.

**Deliberately deferred, and recorded rather than half-built:** the outcome audit (proximate
reward promotes, resolved bands audit) needs resolutions that do not exist yet - `Entry.variant`
is stamped from today so the join will be possible when they land, which is the part with a
deadline (D-045's own reasoning). The sampling lever (Thompson over concept-type pairs) is
designed in notes/016 phase 3 and unbuilt; the test that matters for it is that it needs no
protocol change.

## D-089: The model layer gets calibrated - fitted bootstrap inflation, holdout-vetoed
**Date:** 2026-08-29
**Status:** accepted
**Context:** I-29 measured the bootstrap base rate overconfident by 15-23pp in the 0.7-0.9
region over 21,280 historical band-forecasts, with BOTH tails understated - and two mechanism
fixes (block bootstrap, trailing drift) already tested and failed. The systemic question, argued
through an optimize loop in [notes/018](notes/018_calibration_harmony.md): the agent's
probabilities are calibrated against live resolutions, memory blocks against scored outcomes,
Coach variants against paired trials - **the model layer was the one producer nothing ever
audited, and it is the layer everything else stands on.** Its natural evidence stream is
historic replay: dense (thousands of samples), LLM-free, and lookahead-impossible by slicing.

**Choice: a fitted variance-inflation factor, because the measured signature demands that
functional form and rejects the alternatives.** Symmetric bands overstated while one-sided
bands are UNDERstated at the same predicted p - a p->p reliability map cannot tell those apart
and would correct breakout bands the wrong direction; a too-narrow distribution is the one
explanation that produces both, and widening fixes both at once. One parameter per horizon,
against ten for a binned map.

**The holdout has the veto, and the fit passed it twice.** Fit on the first 60% of history,
validate on the last 40%: Brier 0.2160->0.2021 (3d), 0.2353->0.2174 (5d), 0.2161->0.2097 (10d),
with the 10d 0.7-0.9 gap going +0.152 -> -0.004. Ticker split (fit even, test odd): better at
every horizon there too. `fit_band_inflation` ships k=1.0 whenever the holdout does not confirm
- an in-sample-only improvement never reaches production. Property-tested: the fit detects
synthetic autocorrelated data (k>1.05) and refuses to hallucinate on IID data, which is the
pair of behaviours that separates a measurement from a knob.

**Applied at the measured defect site only, deliberately.** The muse's gates were where I-29
bit: the vacuity ceiling read an optimistic base and the lottery floor read understated tails.
The muse now consumes calibrated factors and records `base_inflate` on every verdict and
journal fate row - provenance is the part with a deadline, because the forward audit
(calibrated-vs-raw against real resolutions, landing 08-31+) is impossible for rows that never
recorded which number they used. **The EV grids, tail_gap and sizing still run raw**: apply
where measured, validate forward, then extend. tail_gap in particular must stay raw - it
compares bootstrap tails to lognormal tails, and inflating one side would manufacture a
permanent artificial disagreement.

**Fail-safe by construction:** `band_inflation()` returns 1.0 on a missing, corrupt or absurd
artifact and clamps to [1.0, 1.5] - a fit wanting k=3 is evidence of something structural, not
a bigger knob. `inflate=1.0` is byte-identical to the old bootstrap (tested, same seed, same
draws), and `inflate` is deliberately NOT in the RNG seed so calibrated and raw estimates are
paired on identical paths.

**Measured live effect, same day:** a SPY 5d symmetric band read 97.3% raw -> 91.9% calibrated
(below the vacuity ceiling - now carries information); an upside breakout read 5.6% -> 10.2%
(crosses the lottery floor - now survives to be judged). Both move in the direction D-076's
critique demanded, and **neither gate changed - the number they read stopped lying.** This is
the quantitative half of the stacked-conservatism diagnosis: the starvation loop (wrong ruler
-> fewer theses -> fewer resolutions -> starved calibration -> floor-stuck sizing) loses its
first link.

**Also:** Coach gauges `model.inflation_5d` / `model.cal_age_days` put the correction on the
report trajectory; `trdrbot modelcal [status|fit]` is the operator surface, the counterpart of
`trdrbot calibration` for the model layer. The open Coach experiment (v1 vs v0, 9 runs) sees
the changed gates equally in both arms, so the trial stays unbiased between them - noted rather
than restarted.

**Rejected, with reasons on the record:** report-only (the defect's main consumers are gates in
code, which never read prose - kept as a component, not the answer); the p->p map (wrong
functional form, above); root-cause bootstrap redesign (two mechanism attempts already failed
cheap tests; unbounded cost against a 6-day window - I-29 stays open on root cause); a general
calibrated-quantity framework (machinery before a second instance - the second instance is the
exit-rule replay, which should be built concretely first).

**Verified:** 266 default tests (6 new) + 19 contract. Live: artifact fitted on 56 tickers
(k=1.30/1.30/1.25 at 3/5/10d, holdout scores stored in it), `modelcal` rendering it, the
inflation flowing through `band_inflation -> bootstrap_factors -> muse` with the measured band
movements above.

## D-090: Theo learns the session - three lessons, one amendment, two technique notes, no constitutional change
**Date:** 2026-08-29
**Status:** accepted
**Context:** A request to distil this session's experiments (the Coach, D-088; the historic-data
findings, notes/017; the model calibration, D-089) into learning blocks. Method unchanged from
D-076: identify the concepts, route each to the store it belongs in per the constitution's own
`[routing]` principle, and apply the slot test - anything a deterministic mechanism enforces
stays code and gets NO memory slot; what memory holds is the judgment residue.

**The analysis was run on the actual record, not on recollection.** The session's 19 muse runs
show 12 of 21 rejections dying on ONE numeric gate ("base probability 0%/100%"), and the Coach's
two mutations - read from the journal - both independently targeted that pattern at the PROMPT
layer ("prevent absolute-certain probabilities") while the defect was in the measurement layer
(I-29: the bootstrap overconfident 15-23pp). The A/B trial rightly refused to promote the
wrong-layer fix (P=0.379 after 9 runs). That arc - refusals cluster, the loop tunes behaviour to
please the gate, the trial says no-better, the instrument turns out to be lying - is the
session's flagship learnable moment, and no existing block covered it.

**Three new lessons** (ordinary decaying blocks, cued, each carrying its measurement - the
existing lesson-quality test enforced that literally, rejecting a first draft with no number in
it, which is the test doing its job):

- `when-refusals-cluster-audit-the-ruler` - the full arc above. Cue: many candidates dying at
  the same numeric gate, or a change repeatedly failing to beat the incumbent.
- `losses-carry-the-information-at-high-win-rates` - I-27's measured asymmetry (89 points of
  room to prove harm, 11 to prove improvement) joined to its trading face: nine confirmations
  per disconfirmation on a 90% book means absence of loss is weak evidence of absence of risk.
- `fast-evidence-proposes-slow-evidence-disposes` - the holdout veto with its real numbers (two
  mechanism fixes failed it, the inflation passed twice, Brier 0.2353->0.2174), and a working
  correction that stops working live is a regime signal, not a nuisance.

**One amendment:** `abstention-has-a-price` gains its measured sequel - part of the 18-and-0
abstention record was manufactured by the instrument, so a refusal streak is evidence about me
OR about my ruler, and the ruler is the cheaper check.

**Two wiki technique notes**, written through the enforced lifecycle path in the canonical
structure (Rule / When it applies / What it means / Evidence), both durable and now in the
muse's collision pool: `technique/who-audits-this-number` (the audit map - every load-bearing
number names the evidence stream that scores it and the slower one that audits it; the
graveyard rule) and `technique/information-lives-in-the-rare-side` (the asymmetry as a
standing concept rather than a decaying lesson, because the arithmetic is timeless even if the
measured instance is not).

**Deliberately NO constitutional change, and the reasoning is the decision.** The candidate
principle - "instruments are claims too" - fails the slot test on both prongs: it is now
substantially CODE-backstopped (modelcal's holdout veto, the Coach's gauges, the forward audit,
the fail-safe loader), and the constitution sits at 427/430 tokens where adding means retiring.
The judgment residue that remains (noticing a refusal cluster as an instrument symptom) is
better held as a cued lesson that can earn confidence through outcomes than as pinned identity -
notes/010's own rule: a mechanism worth knowing has already been compiled into a principle
worth holding, and if it has not, it should not be in the SELF frame either way.

**Verified:** 11/11 lessons recallable by their cue (the new flagship recalls at rank 2);
both wiki notes read back through `durable_text()` with conforming headings; 266 default tests
+ 19 contract pass, including the lesson-quality gate that rejected the unmeasured draft.
