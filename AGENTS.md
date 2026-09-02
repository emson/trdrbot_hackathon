# trdrbot

Autonomous options-trading agent, paper trading only (see README.md). Self-improving via the
Coach (README "The Coach").

- Before touching tests: [`docs/principles_testing.md`](docs/principles_testing.md) — the four
  pillars section governs when a new eval is warranted; most of the time it isn't.
- Before touching production code: [`docs/principles_coding.md`](docs/principles_coding.md).
- Before designing an LLM-facing tool: [`docs/principles_agent_api.md`](docs/principles_agent_api.md).
- Before updating website copy (hero, deck, tiles): [`web/CLAUDE.md`](web/CLAUDE.md) — lists every
  page the hero wording touches, so a rewrite doesn't drift from the tiles or the deck.
- Test command: `uv run pytest` (offline by default; `-m contract` is opt-in, hits real services).
- State files (`data/*.jsonl`, `data/state/**`) are append-only and sacred — never hand-edit or
  regenerate.
- Defects and decisions are logged, not rediscovered:
  [`specs/decisions.md`](specs/decisions.md), [`specs/issues.md`](specs/issues.md).
