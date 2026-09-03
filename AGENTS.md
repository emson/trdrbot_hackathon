# trdrbot

Autonomous options-trading agent, paper trading only (see README.md). Self-improving via the
Coach (agent/README.md "The Coach").

**Two projects, one repo.** `agent/` is the Python trading agent - it owns its own
`pyproject.toml`, virtualenv, `config.yaml`, `.env` and `data/`, and every agent command runs
from inside it. `web/` is the SvelteKit site. `docs/` and `specs/` are shared and stay at the
repo root. Nothing in `agent/` reaches sideways into `web/` except `site_export`, which is the
one component that publishes.

- Before touching tests: [`docs/principles_testing.md`](docs/principles_testing.md) — the four
  pillars section governs when a new eval is warranted; most of the time it isn't.
- Before touching production code: [`docs/principles_coding.md`](docs/principles_coding.md).
- Before designing an LLM-facing tool: [`docs/principles_agent_api.md`](docs/principles_agent_api.md).
- Before updating website copy (hero, deck, tiles): [`web/CLAUDE.md`](web/CLAUDE.md) — lists every
  page the hero wording touches, so a rewrite doesn't drift from the tiles or the deck.
- Test command: `cd agent && uv run pytest` (offline by default; `-m contract` is opt-in, hits
  real services). `uv run` from the repo root finds no project and fails.
- State files (`agent/data/*.jsonl`, `agent/data/state/**`) are append-only and sacred — never
  hand-edit or regenerate.
- Defects and decisions are logged, not rediscovered:
  [`specs/decisions.md`](specs/decisions.md), [`specs/issues.md`](specs/issues.md).
- Before adding or changing a Coach lever: the `TO REGISTER A NEW LEVER` comment in
  `agent/src/trdrbot/coach_pkg/state.py`, and
  [`specs/notes/026_playbook_structure_lever.md`](specs/notes/026_playbook_structure_lever.md)
  for the second lever's build record and the rules a reward must obey.
