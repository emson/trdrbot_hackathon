# trdrbot

## Problem
Team trdrbot is competing in the Alpaca AI Trading Agents Hackathon (lablab.ai, Aug 28 - Sept 4 2026).
The hackathon requires a working AI-driven trading agent that trades options through Alpaca's
paper trading environment. Without a clear, buildable spec, a 9-day hackathon risks stalling on
architecture debate instead of shipping a working, demoable agent by the deadline.

## Users
The trdrbot team itself, building and operating the agent, and the hackathon judges who will
evaluate the submission (working demo, code quality, strategy soundness, options usage,
documentation). There is no external end user in v1 — this is a self-operated agent.

## Success Looks Like
- Agent successfully places and manages at least one options strategy (e.g. a call/put spread)
  in the Alpaca paper trading account, driven by an automated or AI-assisted decision process.
- Submission is made on lablab.ai before September 4, 2026, 15:00 UTC, using a new dedicated
  Alpaca paper trading account, with a working demo and documentation of the strategy logic.
- A judge could read the repo + submission docs and understand what the agent does and why,
  without needing to ask the team questions.

## Scope (v1)
**In:**
- A headless LangGraph service (D-008) with LLM calls behind a gateway so models swap by
  config; integration with Alpaca via MCP against the paper trading account.
- An event-driven pipeline (D-010): a scheduled Collector writes typed market/portfolio
  observations to an inbox; a Processor drains it, decides, and executes.
- Memory (D-011): elfmem for short-term evolving memory (goals, constitution, patterns), an
  LLM wiki for long-term knowledge, and a JSONL journal as the ground-truth trade record.
- External information sources as declarative sensors (D-015): Alpaca news, X/Twitter MCP,
  Google feeds, and Polymarket odds — each with its own cadence, filtering policy and trust
  tier, added one at a time after the core loop is proven.
- Local analytics and mathematics (D-016): an always-injected analytics pack (regime,
  indicators, position and portfolio greeks) plus agent-invocable tools for ad-hoc computation.
- Forecasting (D-013): an in-repo calibration module implementing elfsim's spec slice —
  per-trade outcome forecasts, Brier/Murphy scoring at close, calibration lessons fed back
  into memory.
- Basic position/order tracking and P&L visibility (via Alpaca dashboard, journal, and wiki).
- Submission artifacts: repo, README, strategy write-up, demo.

- Agent-authored exit rules (D-017): stop-loss, profit-target and time-stop conditions the agent
  sets at entry and a deterministic evaluator honours every tick. Not a guardrail — the agent
  writes and may rewrite every rule; this executes its own stated intent.
- A competition-deadline sweep (D-019): every open position is force-closed on a fixed date,
  independent of its own expiry — needed because two rounds of design simulation found that
  without it, a conventional-DTE position simply never resolves inside the 8-day window and the
  learning loop produces zero output while looking healthy.

**Out:**
- Live/real-money trading.
- Multi-broker support.
- A custom dashboard/UI (Alpaca's own dashboard is sufficient for v1).
- Backtesting engine or historical strategy optimisation.
- WebSocket/streaming integration with Alpaca — v1 uses scheduled polling only (D-003).
- Any guardrail/risk-policy layer — deliberately none in v1 (D-009); no VaR modelling,
  portfolio-level hedging, or multi-agent risk review.

## Constraints
- Must use Alpaca's Trading API together with its MCP Server or CLI (hackathon rule).
- Must incorporate options trading as a core component (hackathon rule).
- Must use a new, dedicated Alpaca paper trading account (hackathon rule) — already created.
- Submission deadline: September 4, 2026, 15:00 UTC — hard cutoff, ~9 days from hackathon start.
- Team: trdrbot, small team, building solo/pair-programming style with Claude Code as the
  primary dev tool.
- No real money at risk — paper trading only, $100,000 simulated starting capital.
- Runs as a headless service scheduled via launchd/cron on the team machine (D-008) — the
  machine must stay on during the trading window, unless the service is later deployed to a
  small VM.
- No event-driven triggers from Alpaca exist (no webhooks, MCP Server has no streaming) — all
  checks happen on a schedule (D-003).
- Anthropic's Consumer Terms restrict relying on Claude to buy/sell securities/derivatives;
  applies when Claude is the gateway-selected model (D-008). Known, accepted risk, not
  resolved — see D-007.
- Reuses elfmem (`elf0_mem_sim`, v0.20.0, published on PyPI — real, mature package;
  supersedes the earlier `self-frame-contract` local-path reference and the interim
  `elfmem_index` git-branch dependency) per D-011. elfsim is spec-only with no implementation;
  trdrbot implements its calibration slice in-repo instead (D-013).
