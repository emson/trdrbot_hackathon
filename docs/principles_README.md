# Engineering Principles for LLM-Maintained Python Projects

This directory holds three portable principles documents that guide LLM agents
(and humans) to write robust, flexible, and elegant Python. They are designed to
be dropped into any Python project unchanged.

| Document | Scope |
|----------|-------|
| [`principles_coding.md`](principles_coding.md) | How to write and modify production code |
| [`principles_testing.md`](principles_testing.md) | How to write, run, and maintain tests |
| [`principles_agent_api.md`](principles_agent_api.md) | How to design libraries and tools that LLM agents consume |

## The layering model

Instructions reach an LLM agent in three layers. Keeping them separate is what
makes these documents portable and what prevents drift:

1. **Always-on layer** (`CLAUDE.md` / `AGENTS.md` at repo root). Tiny. Holds only
   non-guessable commands, repo etiquette, and pointers to these documents.
   Every line here competes with the task for attention, so each line must pass
   the test: "would removing this cause a mistake?"
2. **Reference layer** (these documents). Loaded on demand when writing code,
   tests, or agent-facing APIs. Universal: nothing project-specific appears
   above the Project Overlay section.
3. **Project Overlay** (the final section of each document). The only place
   project-specific rules may live: domain naming, deviations from defaults,
   local commands. When rules conflict, the overlay wins.

To adopt in a new project: copy the three documents, fill in each Project
Overlay, add one pointer line per document to the always-on file, and wire up
the Mechanical Enforcement section (linter, type checker, test gate).

## Design rules these documents follow

These documents practise what current evidence says makes LLMs follow
instructions. When editing them, preserve these properties:

- **Tools enforce, prose guides.** Prose rules get roughly 25-40% compliance;
  the same rules as lint/type/CI gates get ~95%. Anything deterministic lives
  in the Mechanical Enforcement map, not in extra paragraphs.
- **Positive, imperative phrasing.** Rules say what to do, not what to avoid.
  Negations make models more likely to produce the banned thing.
- **Few, prioritised non-negotiables.** Models reliably follow only on the
  order of 150-200 instructions total, including their system prompt. Each
  document marks a short MUST list; everything else is a strong default.
- **Good/bad example pairs.** A short paired example teaches a model more than
  a paragraph of abstraction. Rules that matter carry one.
- **Right altitude.** Concrete enough to act on, flexible enough to generalise.
  No brittle step-by-step procedures, no platitudes like "write clean code".
- **Pointers over copies.** Reference `file:line` and live commands rather than
  pasting code that goes stale.

## Maintaining these documents

Treat them as code. Add a rule only to fix an observed failure, verify the
behaviour actually changed, and prune regularly. If a rule stops earning its
place, delete it: bloat causes models to ignore the rules that matter.

## Evidence base

Key sources behind the design (retrieved 2026-07):

- Anthropic, Claude Code best practices: https://code.claude.com/docs/en/best-practices
- Anthropic, Effective context engineering for AI agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- OpenAI, AGENTS.md guide: https://developers.openai.com/codex/guides/agents-md
- HumanLayer, Writing a good CLAUDE.md: https://www.humanlayer.dev/blog/writing-a-good-claude-md
- Chroma, Context rot: https://www.trychroma.com/research/context-rot
- ImpossibleBench (test gaming by models): https://arxiv.org/html/2510.20270v1
- Negative-instruction effectiveness: https://eval.16x.engineer/blog/the-pink-elephant-negative-instructions-llms-effectiveness-analysis
