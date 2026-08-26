# System Architecture Research — the trdrbot harness (v2)

Deliverable for the 2026-08-26 architecture pivot: user-directed redesign around a headless
LangGraph runtime, an inbox pipeline, elfmem + LLM wiki + elfsim memory/forecasting, and no
guardrails. This document restates the intent, shows the design iterations and simulations
that shaped the result, and lands on a recommended v1. Decisions extracted from it:
D-008..D-012 in [decisions.md](../decisions.md).

**Status of evidence:** COMPLETE (2026-08-26). All three background verifications have landed
in §10: the MCP path is verified (local stdio), elfsim turned out to be spec-only (→ D-013),
and elfmem is confirmed real, tested, and integrable as a library (§10.1).

---

## 1. The intent, restated

trdrbot is a small ecosystem of cooperating parts rather than one agent loop:

A **schedule** wakes the system. A **collector** looks at the world — options chains, stock
quotes, our positions and orders, fills, possibly news — and drops what it sees, as discrete
typed items, into an **inbox**. A second stage — the **processor** — is triggered by inbox
content: it picks the items up, makes sense of them, and hands the situation to the
intelligence layer. That layer is **elfmem**: an evolving agent memory that holds goals and a
constitution, learns patterns from experience, knows how to consult a long-term **LLM wiki**,
and can reach for MCP tools, CLI tools, or plain deterministic code to fill gaps. To choose
between candidate actions it can consult **elfsim**, which forecasts how those actions might
play out. Chosen actions execute directly against the Alpaca paper account — **no guardrails**,
because this is a hackathon on simulated money and gates would slow the iteration loop that
matters more than anything else. Every decision and outcome lands in a **journal**; outcomes
feed back into elfmem's patterns and the wiki's lessons, so the system improves as it trades.

Three memories, three tempos: elfmem evolves by the hour (working memory), the wiki accretes
over days (reference memory), the journal never forgets (ground truth). elfsim looks forward;
everything else looks at now or backward.

The ask: reduce this to its core pillars, keep it simple, make it robust/flexible/elegant, and
get the basic structures in place early.

## 2. Core pillars

Six responsibilities. The trick is implementing them as only **three moving parts**.

| Pillar | What it does | Lives in |
|---|---|---|
| **Sense** | Poll the world, emit typed observations | Collector |
| **Decide** | Turn observations + memory + forecasts into an action | Processor (decide path) |
| **Act** | Execute the action via Alpaca MCP | Processor (act node) |
| **Remember** | Working memory, long-term knowledge, ground truth | elfmem + wiki + journal (files) |
| **Forecast** | Project candidate-action outcomes | elfsim (called from decide path) |
| **Learn** | Fold outcomes back into memory | Processor (learn path) |

The three moving parts: **Collector** (a deterministic script), **Processor** (one LangGraph
graph), and the **file system** (inbox, journal, wiki — no databases, no brokers, no daemons).

## 3. The chassis

The "infrastructure that holds the whole system together" is deliberately boring:

```
trdrbot/
  pyproject.toml
  .env                       # APCA keys, gateway keys — never committed
  config.yaml                # model id, tick cadence, watchlist symbols, timeouts
  run.sh                     # one tick: flock → collect → process
  src/trdrbot/
    chassis/                 # config, storage paths, MCP client factory, LLM gateway, locks
    collector.py             # entrypoint 1 (Sense)
    processor/               # entrypoint 2 (one LangGraph graph)
      graph.py               #   wiring
      router.py              #   item-type routing
      decide.py              #   context assembly → forecast → LLM → action
      act.py                 #   MCP order execution
      learn.py               #   journal backfill, memory consolidation
    memory/
      elfmem_adapter.py      # integration surface TBD by exploration (§10)
      wiki.py                # index-first read, schema'd writes
      journal.py             # append-only JSONL writer
    forecast/
      elfsim_adapter.py      # timeout-guarded, degrades to no-op
  data/
    inbox/pending/           # items awaiting processing
    inbox/processed/<date>/  # immutable archive — doubles as the wiki's "raw" layer
    journal.jsonl
    wiki/                    # AGENTS.md, index.md, log.md, strategy.md, lessons.md, positions/
```

Scheduling: `run.sh` invoked by launchd (or, during dev, a `while sleep 300` loop in tmux —
zero scheduler debugging, visible logs). `flock` makes ticks single-flight: if a tick overruns
into the next, the next skips — harmless in an at-least-once design.

Model swapping: the gateway layer (`chassis/llm.py`) resolves the model from `config.yaml`.
Every journal entry records which model decided, so a mid-competition swap keeps results
attributable.

## 4. Data contracts

**Inbox item** — one JSON file per item, filename = id:

```json
{
  "id": "obs_20260828T143500Z_chain_SPY",
  "ts": "2026-08-28T14:35:00Z",
  "type": "account | positions | orders | options_chain | fill | news | housekeeping | manual",
  "source": "collector | alpaca | user",
  "payload": { }
}
```

Lifecycle: written to `pending/`, moved to `processed/<date>/` only after the processor
completes the batch. Crash mid-batch → items remain pending → reprocessed next tick
(at-least-once). `type: manual` is the testing backdoor: drop a hand-written item in, run the
processor once, watch the whole pipeline respond.

**Journal entry** — append-only JSONL:

```json
{
  "ts": "...", "kind": "decision | execution | fill | reflection | error",
  "batch_ids": ["obs_..."], "model": "<gateway model id>",
  "thesis": "one-line reasoning", "action": { },
  "forecast": "elfsim ref or 'degraded'", "result": { }
}
```

**Wiki** — Karpathy pattern per [notes/003](003_competitive_landscape_and_knowledge_store.md):
`AGENTS.md` is the schema (how the agent maintains the wiki — update canonical pages, no
duplication, log meaningful changes), `index.md` navigation, `positions/<id>.md` one entity
page per position (thesis, exits, outcome, reflection), `lessons.md` durable lessons,
`strategy.md` current playbook, `log.md` chronological activity. The inbox archive is the
immutable raw layer, so the wiki holds only derived knowledge.

**Idempotency** — every order carries a `client_order_id` derived from the decision's journal
ref. Crash-retry of a batch that already placed its order → Alpaca rejects the duplicate → the
processor reconciles and archives. This is bug-prevention, not a guardrail: it never blocks a
deliberate decision (D-009).

## 5. Design iterations — how the shape was found

**v0 — literal transcription of the concept.** Scheduler service + collector service + queue
broker + file-watcher trigger + processor service + separate learner service. *Evaluated:*
every seam is a failure mode needing supervision; six processes on one laptop for a 9-day
build. Killed for complexity.

**v1 — collapse to files and two entrypoints.** File inbox, cron, watchdog file-watcher to
trigger the processor. *Evaluated:* better, but the watcher is still a long-running daemon that
dies silently at 2am. *Improved:* the same tick runs `collect && process` sequentially — the
trigger becomes "collector finished". The inbox stays a real interface (anything can drop items
in; the processor drains whatever is pending regardless of who wrote it), so the decoupling
survives without a daemon.

**v2 — the unification insight.** First draft had the learn loop as separate machinery
(D-006's "review every 3-5 trades" timer). Simulation of a fill arriving showed it's just
another observation: **fills, news, chain snapshots, and housekeeping ticks are all inbox
items, and the processor is one graph that routes by type.** Learning stops being a scheduled
side-process and becomes event-native — a fill item *is* the trigger for reflection on that
trade. The daily housekeeping item (emitted by the collector once per day, or when the market
is closed) drives wiki consolidation. One pipeline, three behaviours, zero extra machinery.

v2 is the recommended shape. Each iteration deleted a component; none added one.

## 6. Scenario simulations

**S1 — normal trading tick (Mon 14:35 UK / 09:35 ET).** Collector polls: account, 2 open
positions, 1 open order, SPY + AAPL chains → 5 items. Processor routes all to decide. Context
assembly: elfmem recall (goals, constitution, active patterns), wiki index → 2 position pages +
lessons, journal tail. elfsim projects 3 candidate actions. LLM decides: open an SPY bull put
spread, states thesis + exits. Act: `place_option_order` (multi-leg) with `client_order_id`.
Journal: decision + execution. Wiki: new `positions/SPY-bps-0828.md`. Items archived. *Outcome:
clean; the whole tick is 1 LLM decision + 1 optional elfsim call — cost-bounded.*

**S2 — news burst.** 40 news items land (future feed or manual injection). *Failure found:*
naive processing puts 40 items into one prompt. *Mitigation:* deterministic pre-filter in the
router — news mentioning held/watchlist tickers passes, rest is archived unread; batch cap with
"n items dropped" noted in context. Cheap code, no LLM.

**S3 — crash between order placement and archive.** Tick dies after Alpaca accepts the order.
Next tick reprocesses the batch. *Failure found:* duplicate spread. *Mitigation:* the
`client_order_id` dedup in §4 — Alpaca rejects, processor sees the existing order, reconciles,
archives. This is the one crash window that could cost (paper) money; idempotency closes it.

**S4 — elfsim times out / elfmem unreadable.** Decide proceeds with whatever context loaded;
journal entry records `"forecast": "degraded"`. *Design rule extracted:* every intelligence
input is advisory; only Alpaca (portfolio truth) and the inbox (work to do) are load-bearing.
The pipeline never blocks on its own brain.

**S5 — market closed (weekend/overnight).** Collector checks the Alpaca clock: emits only a
daily housekeeping item instead of observations. Processor routes it to consolidation: wiki
upkeep, elfmem pattern digestion, daily digest into `wiki/log.md`. *Outcome:* the same
pipeline trades when the market is open and studies when it isn't — no special-case code path,
just an item type.*

**S6 — runaway decider (no guardrails, so simulate the worst).** The LLM decides something
absurd — 50 contracts of a far-OTM strangle. Nothing blocks it; it executes on paper.
*Consequences traced:* worst case is a damaged paper account, which is (a) informative — the
learn path will reflect on the loss, and the constitution can be edited, (b) recoverable —
Alpaca paper accounts reset on demand (journal and wiki survive a reset; note the divergence in
`wiki/log.md`). *Design rule extracted:* the remedy for bad behaviour is memory (constitution
edit + lessons), not gates. Soft self-governance through elfmem's constitution is the
architecture's own answer, and it improves with evidence — which is the demo story.

## 7. Edge cases and mitigations

| Edge case | Mitigation | Cost |
|---|---|---|
| Duplicate order on crash-retry | `client_order_id` from decision ref | ~5 lines |
| Overlapping ticks | `flock` single-flight; skip is harmless | 1 line in run.sh |
| Stale data (after-hours quotes) | Items carry `ts`; decide prompt states data age — informed, not blocked | prompt line |
| Open order from last tick still unfilled | Collector includes open orders; decide sees them and doesn't stack intents | free (S1 already collects) |
| Partial / per-leg options fills | Fill items reconciled by order id in learn path | small |
| Inbox flood | Router pre-filter + batch cap (S2) | small |
| LLM/gateway outage | Items stay pending; retried next tick | free (at-least-once) |
| elfmem/elfsim failure | Advisory-only rule (S4) | timeout wrapper |
| Wiki growth | Index-first reads; housekeeping consolidation (S5) | inherent to pattern |
| Machine asleep mid-window | launchd + power settings; or deploy `run.sh` to a small VM later | config / optional |
| Paper account reset mid-competition | Journal + wiki survive; log the divergence | documentation |
| Market-hours/timezone confusion | Alpaca clock API is the only time authority | 1 call per tick |

## 8. Alternatives considered and rejected

- **Previous design (Claude Code + guardrail hook + fused loop):** superseded by user
  direction. Notably, removing guardrails (D-009) removed Claude Code's one structural
  advantage — the PreToolUse hook — which made the LangGraph move strictly cheaper than it was
  in [notes/002](002_harness_comparison.md).
- **Message broker inbox (Redis/RabbitMQ):** nothing here needs cross-machine delivery;
  files are durable, inspectable, and injectable with `cp`.
- **LangGraph checkpoint state as the inbox:** couples sensing to the graph runtime; a
  directory of JSON is toolable by anything (including a human).
- **Multi-agent decider (analyst/trader/risk crews à la TradingAgents / AlpacaTradingAgent):**
  better Sharpe in research, but multiplies LLM calls and prompts to debug; one decider with
  rich memory is the 9-day-sized bet. The graph makes it upgradeable later without re-architecting.
- **Vector store memory:** rejected per notes/001 §4 — layered recency-weighted memory (which
  elfmem + wiki are) outperforms it for this use case at far lower cost.
- **WebSocket streaming for fills:** collector polls fills each tick; D-003 stands.

## 9. Evaluation against the bar

**Robust** — at-least-once inbox; idempotent orders; single-flight ticks; every intelligence
component degrades to "decide with less context"; ground truth (Alpaca + journal) survives any
crash; paper reset is a full recovery path.

**Flexible** — model swap is a config edit (journal keeps attribution); new information sources
are just new item types (no pipeline change); elfmem/elfsim sit behind adapters with declared
fallbacks (D-011/D-012); more MCP servers can join the client factory; the decide path can
later grow into multi-agent without touching Sense/Act/Learn.

**Elegant** — six responsibilities, three moving parts; learning is an item type, not a
subsystem; the inbox archive doubles as the wiki's raw layer; the constitution doubles as the
(soft) risk stance; one graph explains the whole system in one diagram.

**Simplicity receipts** (things deleted during design): queue broker, file-watcher daemon,
separate learner service, guardrail module, review-cadence timer, separate `raw/` directory,
Claude Code session-cap workarounds.

## 10. Integration findings — elfmem, elfsim, MCP path

### 10.3 MCP path — VERIFIED (2026-08-26): local stdio subprocess

The LangGraph→Alpaca route is confirmed, with one recommendation flip versus
[notes/003](003_competitive_landscape_and_knowledge_store.md):

- **`langchain-mcp-adapters` is the official, maintained bridge**
  ([repo](https://github.com/langchain-ai/langchain-mcp-adapters),
  [docs](https://docs.langchain.com/oss/python/langchain/mcp)). `MultiServerMCPClient`
  supports stdio (spawns a subprocess), streamable HTTP, and SSE; stateless by default.
- **The hosted Alpaca endpoint is OAuth-interactive-only** — browser-based plugin auth for
  Cursor/Claude Code/Codex, no documented API-key/bearer path. Not usable from a headless
  service. The `agentic` repo itself says: "Run the open-source Trading MCP Server locally when
  you want API-key authentication or control over the server process" — exactly our case.
  notes/003's "use the hosted endpoint" recommendation is therefore reversed *for this
  runtime*: hosted suits interactive IDE assistants; headless wants local stdio.
- **v1 connection:** `MultiServerMCPClient` spawns `uvx alpaca-mcp-server` as a stdio child
  process — no separate hosting, dies with the tick, version-pinnable. **v2 env var naming**
  (corrects earlier docs/ material, which used the REST SDK's `APCA_*` names): the MCP server
  wants `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER_TRADE` (default `true` — good),
  and optional `ALPACA_TOOLSETS` to restrict the tool surface.

```python
client = MultiServerMCPClient({
    "alpaca": {
        "command": "uvx", "args": ["alpaca-mcp-server"], "transport": "stdio",
        "env": {"ALPACA_API_KEY": "...", "ALPACA_SECRET_KEY": "..."},
    }
})
tools = await client.get_tools()
```

### 10.2 elfsim — EXPLORED (2026-08-26): spec-only, nothing to integrate

Exhaustively verified (full directory listing, `git log`, import test): the elfsim repo is
**nine Markdown design documents with zero lines of implementation and no commits**. The
`CLAUDE.md` commands (`uv run python -m elfsim simulate`) would all fail; there is no package,
version, or test suite to depend on. Everything in its docs — the five-layer simulation engine,
MCP server, elfmem bridge — is aspirational, and its central DSL semantics (how causal-edge
`strength` becomes a number) is an acknowledged spec gap.

What IS concrete and valuable in the spec, per the exploration:
- **The calibration loop**: Brier Index (`(1 − √Brier) × 100%`) with Murphy decomposition
  (reliability/resolution/uncertainty) — standard, verifiable statistics that tell an agent
  *why* it was wrong ("overconfident, not merely wrong"), not just its P&L. Most trading
  systems track P&L but not forecast calibration — this is the differentiated piece.
- **The forecast/resolution record shape**: scenario → probability forecast → resolution →
  score, as YAML/frontmatter entities.
- The spec's own research table concludes "elfsim for prediction, separate execution engine" —
  it never wanted to be in the execution path, which matches D-012's advisory-only stance.

Two useful side-findings: elfsim's docs confirm **elfmem is real and mature** (v0.19.3,
tests, migrations, built dist — the inverse of elfsim's state), and elfmem's
`docs/coding_principles.md` is titled "elf0_trader" with market-data examples — the author was
already circling this integration.

**Consequence → D-013**: don't integrate elfsim (nothing exists to integrate); instead
implement its calibration slice directly in trdrbot as a small module — the decide path
records outcome-probability forecasts per trade, the learn path resolves them at close and
scores Brier/Murphy per domain, and calibration summaries feed back into elfmem/wiki. Outcome
probabilities come from real options math (the position's Greeks/IV are already in the
collector's chain snapshots), not a generic Monte Carlo DSL. Days of work, not the spec's
multi-month roadmap, and the forecast node in §3's graph keeps the same interface so a future
real elfsim can slot in.

### 10.1 elfmem — EXPLORED (2026-08-26): real, tested, import-as-library

**Confirmed working by execution**: package `elfmem` v0.19.3 on the `self-frame-contract`
branch — 1500 tests passing, `mypy --strict` clean, 30k LOC, 4.5 months of daily dogfooding.
Three surfaces ship (library, 29-command CLI, 30-tool stdio MCP server); the **library import
is the recommended path** — async, typed results, and the best-tested code path (engine ~97%
coverage vs CLI 50% / MCP 66%).

**Integration sketch** (construct once, session per tick):

```python
from elfmem import MemorySystem
mem = await MemorySystem.from_config("data/elfmem/trader.db", config)   # app start

async with mem.session(task_type="trade_decision"):                     # per tick
    ctx = await mem.frame("attention", query="SPY spread near resistance")
    # ctx.text → straight into the decide prompt
    await mem.remember("SPY rejected 560 for the third time",
                       cue="when reasoning about SPY resistance levels")
# session exit auto-consolidates if mem.should_dream
```

**The frame system maps directly onto our design:** `self` frame = the constitution
(queryless, cached, provenance-partitioned — the branch's headline fix makes peer content
"context, not instruction," a real prompt-injection defense); `task` frame = goals;
`attention` frame = per-decision context (hybrid vector+BM25+graph retrieval). Trade P&L wires
into `outcome(block_ids, signal)` using `mem.last_recall_block_ids` as the bridge — that loop
is what makes memory adapt rather than accumulate. `dream(host_analyses=...)` lets our graph
supply its own analyses and skip elfmem's consolidation LLM cost entirely.

**Bonus for D-013:** elfmem ships a working, tested **`mind` prediction/outcome cycle**
(`mind_predict` requires a dated, falsifiable `verify_at`; `mind_outcome` resolves hit/miss
into a Beta posterior; calibration dashboard included; no LLM calls). A trading thesis is
exactly this shape — thesis → `mind_predict(verify_at=expiry)` → resolve at close. elfmem does
not compute Brier scores itself (documented as intended, not built) — our calibration module
computes Brier/Murphy and feeds the result to `outcome()`. D-013 just got cheaper.

**Two corrected assumptions** (both were in the original intent statement):
1. **elfmem has no LLM-wiki lookup.** Verified — no wiki subsystem; wikilink expansion was
   explicitly dropped. What it has is its own Obsidian-compatible markdown *substrate*
   (`.elfmem/memory/`, files-authoritative on this branch). So the Karpathy wiki in §4 is
   **our code's responsibility**: `wiki.py` reads index-first and injects pages into the decide
   prompt alongside elfmem's frames. Two markdown corpora coexist with distinct roles: elfmem's
   substrate (its memory), our wiki (curated long-term knowledge).
2. **elfmem is a callee, not a caller.** It makes only LLM-completion and embedding calls —
   no MCP, no subprocess, no HTTP. Tool use (Alpaca MCP, CLI tools, deterministic code) is
   entirely the host's job, i.e. our LangGraph graph. §3's architecture already had this
   right, but the intent statement's "elfmem can use MCP/CLI tools" should read "the
   processor uses tools; elfmem supplies the memory that informs those calls."

**Operational cautions:** pin to the `self-frame-contract` branch, not PyPI (PyPI serves
0.19.2 — missing the SELF-frame fix, cue fix, and lazy imports); **hand-write a `cue` line on
every `remember()`** (it's the BM25 half of retrieval — no cue means findable only by its own
wording); commit `.elfmem/memory/` and `.elfmem/ledger/` to git (the only undo for
`forget()`/`edit()`); call `dream()` between sessions, never inside a tick.

## 11. Recommended build order (basic structures early)

1. **Walking skeleton (days 0-1):** repo + chassis + inbox schema + journal writer + wiki
   scaffold + MCP smoke test (read account, place one test order) + gateway wired to one
   model + `run.sh`. *Milestone: one end-to-end tick places a real paper trade from a manual
   inbox item.*
2. **Sense + Decide v1 (days 2-3):** collector item types; processor router; minimal decide
   prompt; act node with idempotency; journal entries. *Milestone: scheduled ticks trade
   unattended.*
3. **Memory (days 3-5):** elfmem adapter (per §10 findings), wiki read/write in decide and
   learn paths, fill-event learning. *Milestone: a closed trade produces a reflection and a
   lesson.*
4. **Forecast + polish (days 5-7):** calibration module in the decide/learn paths (D-013 —
   per-trade forecasts, Brier/Murphy scoring); constitution seeding; prompt iteration against
   live paper results; consolidation housekeeping.
5. **Submission (days 7-8):** demo capture, strategy write-up citing journal/wiki evidence,
   README. Buffer.

## 12. Open questions

- §10's three pending verifications.
- Watchlist scope for the collector (fixed symbols vs discovered) — start fixed
  (SPY + 2-3 liquid names), revisit after first live days.
- Whether news enters v1 at all, or ships as a post-skeleton item type (recommend: defer until
  the trading loop is stable; the pipeline accepts it whenever it arrives).
