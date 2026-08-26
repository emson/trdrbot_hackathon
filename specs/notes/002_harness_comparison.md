# Harness Comparison — Alternatives to Plain Claude Code

Research pass (1 scout fan-out, 58 agents, decision mode — inconclusive on harness ranking;
followed by 9 targeted primary-source checks on the one property that actually discriminates)
evaluating whether a different agent harness would serve trdrbot better than Claude Code
(current baseline, [D-002](../decisions.md)), given a new set of requirements: an LLM gateway
for model-swapping, MCP client support, CLI execution, wiki/knowledge-store integration,
multi-day scheduled loops, and hooks.

## Why the first pass came back empty on ranking

The scout fan-out confirmed hard facts about Alpaca's MCP server (see below) but could not
verify a single claim about which named harness supports a synchronous, deny-capable
pre-tool-call hook — the one requirement that's genuinely hard to retrofit (the other five are
commodity capabilities buildable on almost any runtime). All three survey claims it found on
this topic traced to one paper (arXiv 2603.20953) and were unanimously refuted by adversarial
verification. A second, targeted round did direct primary-source inspection per framework
instead.

## Universal finding: Alpaca's MCP server has no hosted endpoint — CORRECTED 2026-08-26

Original finding: confirmed directly from Alpaca's own docs and the `alpacahq/alpaca-mcp-server`
repo, "Alpaca does not provide a hosted remote MCP server" — every user self-hosts.

**This turned out to be incomplete.** A separate Alpaca repo, `alpacahq/agentic`, documents
genuinely Alpaca-operated hosted MCP endpoints requiring no self-hosting at all:
`https://api.alpaca.markets/mcp` (live) and `https://paper-api.alpaca.markets/mcp` (paper),
plus broker equivalents. Connect via OAuth plugin (Cursor/Claude Code/Codex) or manual client
config pointing straight at the URL — no process to run or supervise. See
[notes/003](003_competitive_landscape_and_knowledge_store.md) for the source and detail.

Reconciliation: these appear to be two distinct offerings — `alpaca-mcp-server` (open-source,
self-hostable reference implementation, stdio-first) and `agentic`'s hosted first-party
endpoint (a separate, newer product). Both are real; they answer different needs. **For trdrbot,
this removes the self-hosting cost previously treated as fixed across every harness** — point
at the hosted paper endpoint instead. Verify by actually connecting before relying on it (this
is a single-fetch finding, not adversarially verified like the rest of this document).

## Pre-execution deny hook, per harness (the discriminating requirement)

| Harness | Confirmed? | Mechanism | Source |
|---|---|---|---|
| Claude Code | ✅ Yes | `PreToolUse` hook | code.claude.com/docs/en/permissions (verified earlier this session) |
| Claude Agent SDK | ✅ Yes | Same permission/hook system as Claude Code | code.claude.com/docs/en/agent-sdk/overview |
| LangGraph | ✅ Yes | `wrap_tool_call` middleware — don't call `handler()` to block | reference.langchain.com/python/langchain/agents/middleware/types/wrap_tool_call |
| CrewAI | ✅ Yes | `@before_tool_call` (return `False`) or `@on(InterceptionPoint.PRE_TOOL_CALL)` (raise `HookAborted`) | docs.crewai.com/en/learn/tool-hooks |
| Microsoft Agent Framework | ✅ Yes | `FunctionMiddleware` — don't call `call_next()`, or raise `MiddlewareTermination` | learn.microsoft.com/en-us/agent-framework/agents/middleware |
| OpenAI Agents SDK | ✅ Yes | `@tool_input_guardrail` → `ToolGuardrailFunctionOutput.reject_content()` (NOT `on_tool_start`, which is observation-only) | openai.github.io/openai-agents-python/guardrails |
| Google ADK | ✅ Yes | `before_tool_callback` — return dict to skip, `None` to proceed. Deterministic, not model-based (corrects a refuted claim from the first pass) | google.github.io/adk-docs/callbacks/types-of-callbacks (redirect to adk.dev flagged as suspicious, fetched via raw.githubusercontent.com instead) |
| Mastra | ✅ Yes | `beforeToolCall` — return `{proceed: false, output}` skips `execute()` | mastra.ai/docs/agents/using-tools |
| Letta | ✅ Yes | Two paths: `PreToolUse` hook (shell exit code 2 = block) — deterministic, no human; or HITL approval flow | docs.letta.com/letta-code/hooks, docs.letta.com/guides/core-concepts/tools/human-in-the-loop |
| n8n | ⚠️ Human-gated only | "Require approval" node pauses the workflow for a human reviewer — not a no-human deterministic block | docs.n8n.io/build/integrate-ai/ai-examples/human-in-the-loop-for-tools |
| AutoGen/AG2 (older) | ⚠️ Not confirmed | Documented hooks intercept messages, not individual tool calls | docs.ag2.ai/latest/docs/contributor-guide/how-ag2-works/hooks — superseded by MS Agent Framework anyway |
| Vercel AI SDK | ❌ No | Lifecycle callbacks (`onToolExecutionStart` etc.) are explicitly observation-only; open, unresolved GitHub issue (vercel/ai#14649) confirms the gap | ai-sdk.dev/docs/ai-sdk-core/lifecycle-callbacks |
| Temporal | ✅ Yes, but build-it-yourself | Activity Interceptors — deterministic, in-process, confirmed replay-safe. No turnkey LLM tool-calling loop ships with it | docs.temporal.io/develop/python/workers/interceptors |
| Restack | ⚠️ Unclear | UI mentions "approve sensitive actions" but not documented as pre/post-execution or programmable; no turnkey agent loop either | docs.restack.io |

## What's still unverified

Requirements 1 (LLM gateway compatibility), 2 (MCP client), 3 (CLI execution), 4
(wiki/knowledge-store), 5 (scheduling reliability) were **not** independently re-verified per
framework in the targeted round — the original scout pass characterized these as "commodity,
bolt-on-able to almost any runtime," which is a reasonable inference but not a per-framework
verified claim. Treat any specific claim about e.g. "LangGraph has mature MCP adapters" as
`[from training data — verify if load-bearing]` unless a future pass confirms it directly.

**One load-bearing gap worth flagging explicitly:** Claude Code and the Claude Agent SDK are
both Anthropic/Claude-only by design — neither natively routes to other model providers the way
LiteLLM or OpenRouter do. Whether Claude Code's `ANTHROPIC_BASE_URL` override could point at a
gateway emulating the Anthropic API shape is untested this session and would need its own
verification before relying on it.

## Recommendation

**If model-swapping was more aspirational than load-bearing:** stay on Claude Code. Zero
switching cost — D-001/D-002/D-004/D-005/D-007 already assume it, hooks are confirmed, and
self-hosting Alpaca's MCP server is required either way.

**If model-swapping is a real requirement:** switch to **LangGraph**. It's the only candidate
that is simultaneously (a) confirmed deny-capable via `wrap_tool_call`, (b) built model-agnostic
from the ground up (LangChain's core design, not a bolt-on), (c) has a mature Python/MCP
ecosystem, and (d) fits a single-agent design without fighting the framework's paradigm (unlike
CrewAI, whose multi-agent-crew model sits awkwardly against D-001's single-decision-maker
choice). **Microsoft Agent Framework** is the strongest second choice — its governance-toolkit
framing (sub-0.1ms allow/deny) matches lablab.ai's own judging interest in safeguards almost
exactly, but it's newer and less battle-tested for a 9-day crunch.

**Switching cost if we move off Claude Code:** D-001 (Claude decides via Alpaca MCP — the "how"
changes, not the "what"), D-002 (runtime), D-004 (guardrail hook implementation), D-005
(decision loop — conceptually portable, mechanically not), and D-007 (compliance framing may
need revisiting under a different vendor's terms) would all need rework. Not yet decided —
pending user input.
