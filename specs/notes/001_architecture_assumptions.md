# Architecture Assumptions — Research Findings

Research pass (4 parallel forks, web research against 2025-2026 sources) answering the
foundational questions raised before specifying the agent's core loop:
1. Claude Code session vs. Claude Agent SDK?
2. How do we check the API — hooks on events, or a scheduled wake-up?
3. How does the agent go from (environment + current commitments) → best next action?
4. How do we build in a self-improving loop?

## 1. Runtime: Claude Code vs. Agent SDK

**Finding:** These are not rival architectures. Claude Code's headless mode (`claude -p`) *is*
the Agent SDK's CLI entry point — same tool loop, same context management. The real choice is
between driving it via CLI/skills (Anthropic manages scheduling/session state) vs. embedding
the SDK in a custom process you run and supervise yourself (full control, days of extra
plumbing: scheduler, MCP client, state store, process supervision).

**Scheduling options compared:**

| | Local (`/loop`, Desktop scheduled tasks) | Cloud Routines (`/schedule`) | Agent SDK (own process) |
|---|---|---|---|
| Setup effort | Minutes | Minutes | Days |
| Min. interval | 1 minute | 1 hour (cron floor) | Unlimited |
| Runs without your machine on | No | **Yes** (Anthropic-managed) | Yes, if self-hosted |
| Event triggers | Hooks fire only *within* a running session — can't wake a cold process | API call / GitHub event / cron | Anything you wire |
| State across runs | Session resume, or re-query Alpaca each cycle | Fresh clone each run — externalize state yourself | Yours to design |

**Recommendation:** Claude Code directly, not a bespoke SDK service — building scheduler/MCP
client/state store from scratch is not a good use of a 9-day window when Claude Code already
provides all three.

**Open sub-question this creates:** local (`/loop`/Desktop task, fast but needs the machine on)
vs. Cloud Routines (hourly floor, but unattended/reliable across a multi-day competition
window). See "Open Decision" below.

Sources: [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview),
[Headless mode](https://code.claude.com/docs/en/headless),
[Hooks reference](https://code.claude.com/docs/en/hooks),
[Scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks)

## 2. Alpaca event triggers vs. polling

**Finding:** Alpaca has no outbound webhooks. The official MCP Server
(`alpacahq/alpaca-mcp-server`) is confirmed request/response only — no streaming or webhook
tools. Genuine push events exist only via a separate WebSocket (`trade_updates` stream for
order/fill events, plus a market-data stream), which would mean bypassing the MCP Server
entirely for a second integration surface.

Every comparable 2025-2026 project surveyed (QuantInsti's Agentic Portfolio Manager, Alpaca's
own "Agent M" and multi-agent writeups, `sentient-trader`) uses a **scheduled polling loop**,
not streaming — typically every 5-15 minutes intraday, sometimes with a separate faster
position-monitor loop for stops/targets.

**Recommendation:** scheduled polling against the MCP Server; skip WebSocket streaming for v1.
It's not on the critical path — the MCP Server (our chosen integration, D-001) doesn't support
it anyway, and options strategies don't need sub-minute reaction. Roadmap item if latency ever
becomes the bottleneck.

**Where hooks *do* fit:** not as a wake-up mechanism (see above), but as a **guardrail
enforcement point within a running session**. A `PreToolUse` hook on the Alpaca order-submission
MCP tool can deterministically validate a proposed trade (size, concurrent positions, daily
loss cap) and block it before it reaches the broker — see finding 3 below on why this must be
code, not LLM judgment.

Sources: [alpacahq/alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server),
[WebSocket streaming docs](https://docs.alpaca.markets/us/docs/websocket-streaming),
[trade_updates event docs](https://forum.alpaca.markets/t/documentation-for-the-tradeupdate-web-socket-event/6696),
[QuantInsti Agentic Portfolio Manager](https://www.quantinsti.com/articles/agentic-ai-portfolio-manager-alpaca-trading-bot/),
[Alpaca: Agent M](https://alpaca.markets/learn/agent-m-an-autonomous-multi-agent-trading-platform-using-alpaca),
[Alpaca: multi-agent trading system](https://alpaca.markets/learn/building-a-multi-agent-ai-trading-system-on-alpaca)

## 3. Decision-loop architecture

**Finding:** the field converges on a 6-step loop per wake cycle:

1. **Gather state** — via MCP: account (buying power, equity), open positions, open orders,
   options chain + Greeks for the target underlying(s), current quote.
2. **Assess commitments** — compare open positions against their originally-logged thesis /
   stop-loss / profit-target / expiration (requires persisting thesis at entry-time — Alpaca's
   raw position data alone doesn't carry it).
3. **Decide action** — Claude proposes exactly *one* of: open new position, adjust/close an
   existing one, or no-action. Must state: underlying, strategy, entry price, stop-loss
   (price + %), profit target (price + %, as risk/reward ratio), position size (% of equity),
   and a one-line thesis + exit condition.
4. **Validate against deterministic guardrails, enforced outside the LLM** — max position size
   (e.g. 1-2% of equity/trade), max concurrent positions, max daily loss / circuit breaker,
   market-hours check. A failed check blocks execution and logs the rejection.
5. **Execute** via MCP.
6. **Log** a structured record: asset, strategy, entry price, stop-loss, target, R:R, thesis,
   timestamp.

Alpaca's own official reference workflow (analyze → place order → log to Sheets) uses this
exact shape, deriving stop-loss/target dynamically from live price rather than hardcoding
thresholds.

**On "maximize profit" as the objective:** every source warns against a bare profit-maximizing
objective — it should be reframed as *"maximize profit subject to the hard constraints in
step 4,"* with those constraints as spec requirements, not aspirational prompt guidance.
Multi-agent frameworks (TradingAgents: separate analyst/researcher/trader/risk-manager LLM
roles) show better Sharpe than single-agent baselines, but are heavier than 9 days supports and
conflict with D-001 (single decision-making component). The one idea worth borrowing without
the full multi-agent structure: treat "risk manager" as a separate **deterministic, non-LLM**
check (step 4), not a second model call.

Sources: [TradingAgents paper](https://arxiv.org/abs/2412.20138),
[TradingAgents repo](https://github.com/tauricresearch/tradingagents),
[Alpaca: MCP trading workflow with Claude + Google Sheets](https://alpaca.markets/learn/mcp-trading-with-claude-alpaca-google-sheets),
[QuantInsti: guardrailed risk-manager agent](https://blog.quantinsti.com/ai-aapl-trading-risk-manager-deepseek-python/)

## 4. Self-improving loop

**Finding:** reflection (Reflexion-style critique-revise) is best understood as a guardrail
against the agent's *own recurring mistakes* (stale data, ignored costs, regime mismatch),
not a source of new alpha. FinMem/FinAgent (2024-2025) use **layered, recency-weighted memory**
rather than vector search — for a 9-day build, a structured trade journal (plain
files/JSON, most-recent-N + pinned high-impact lessons) gets most of the benefit for a fraction
of the engineering.

**Proposed design:**
- **Trade journal** (append-only, e.g. `journal.jsonl`): one entry per decision cycle —
  timestamp, market snapshot summary, action taken (or no-op), stated thesis, later backfilled
  with outcome (fill price, P&L, whether thesis held).
- **Current guidance doc**: a short file holding active lessons (e.g. "avoid opening new
  spreads within 2 days of earnings — thesis broke on the last 2 attempts"). Read by every
  decision cycle as context.
- **Review trigger:** every 3-5 closed trades, or once daily — whichever comes first. Not every
  cycle; too few data points is noise.
- **Review step:** a separate Claude pass reads the journal since the last review, checks each
  thesis against actual outcome, proposes at most 1-2 additions/edits to the guidance doc
  (capped magnitude, never a full rewrite).

**Guardrails (deterministic, non-negotiable, same enforcement layer as decision-loop step 4):**
- Hard max position size / max % buying power per trade
- Hard max concurrent open positions
- Every opened position must have a stated, code-checked exit condition
- Minimum sample size (≥3 trades) before any guidance-doc update
- The self-improvement loop may only *tighten or add* guidance — never loosen a risk guardrail

**9-day reality check:** the journal + guidance-doc loop is buildable in the window and is a
strong demo story. Full backtesting-in-the-loop, vector memory, or multi-agent reflection →
roadmap, not v1. Also flagged: LLM backtests risk memorization-driven overfitting (the model
may have training overlap with historical prices), which matters if backtesting is added later
but is less relevant to live paper-trading during the hackathon.

Sources: [Agentic Trading survey (arXiv)](https://arxiv.org/pdf/2605.19337),
[Reflective LLM-based Agent overview](https://www.emergentmind.com/topics/reflective-llm-based-agent),
[FinMem (arXiv)](https://arxiv.org/abs/2311.13743),
[Hardening an AI trading agent](https://medium.com/@conniezhou678/machine-learning-for-algorithmic-trading-part-28-hardening-your-ai-trading-agent-backtesting-96a2dda18c7d),
[QuantInsti: guardrailed risk-manager agent](https://blog.quantinsti.com/ai-aapl-trading-risk-manager-deepseek-python/),
[Backtesting an AI trading agent before going live](https://obside.com/trading-ai-agents/backtest-ai-trading-agent)

## Cross-cutting insight

Findings 2, 3, and 4 converge on the same structural point: **one deterministic guardrail
module**, enforced outside the LLM (as a `PreToolUse` hook on the order-submission MCP tool,
or equivalent), used for two purposes — (a) gating every individual trade proposal in the
decision loop, and (b) bounding what the self-improvement review is allowed to change. This
should be a single spec'd component, not two.
