# trdrbot — Theo, a self-improving options-trading agent

**Theo learns *why* it was right, not just whether it made money.**

Every cycle it gathers research, forms a falsifiable thesis, simulates the ways to trade it, and
sizes the one it trusts most by a track record it has to *earn*. Then it scores itself honestly —
was the **view** right, was the **structure** right, or did it just get lucky — and only the first
two ever move its confidence.

Built for the [Alpaca AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon).
**Paper trading only — no real money, and nothing here is financial advice.**

[**The live record →**](https://trdrbot.com) · [Slide deck](https://trdrbot.com/deck.html) ·
[For judges](https://trdrbot.com/submission) · [Written brief](SUBMISSION.md) · MIT licensed

---

## The idea, in one table

Most trading agents score themselves on P&L. Over a one-week window that is close to meaningless,
and we measured it rather than assuming: a genuinely skilled agent with a 60% edge out-scores a
coin flip only **69% of the time over 20 trades**. Worse, an agent that learns from P&L alone
reinforces whatever story happened to correlate with money — which is how a system acquires a
superstition.

So Theo separates two questions that P&L conflates:

| thesis | outcome | what it learns |
|---|---|---|
| held | profit | reinforce both |
| held | loss | **the view was fine** — the strikes, width or stop were wrong |
| failed | loss | correct the view; the structure was faithful |
| failed | profit | **learn nothing** — this was luck |

That bottom row is the important one. P&L-based scoring treats a lucky win as strong confirmation.
Here it moves nothing, and it actively blocks promotion up the size ladder.

```
news ─┐
odds ─┼─▶ research ─┐
wiki ─┘   discovery ─┼─▶ thesis ─▶ simulate ─▶ size ─▶ execute ─▶ attribute ─┐
          muse ──────┘      ▲                                                │
                            └──────────── what it learned ───────────────────┘
```

## Where things live

Two projects share this repository. Each is self-contained and has its own README.

| path | what it is | start here |
|---|---|---|
| **`agent/`** | The Python trading agent — the loop, the models, the maths, and the record it keeps. Owns its own `pyproject.toml`, virtualenv, `config.yaml`, `.env` and `data/`. | [`agent/README.md`](agent/README.md) |
| **`web/`** | [trdrbot.com](https://trdrbot.com) — a SvelteKit site generated entirely from the agent's own record. No hand-written numbers. | [`web/README.md`](web/README.md) |
| `agent/data/` | The record itself: journal, thesis ledger, wiki, per-position stories. The live-state files are gitignored; the wiki and the stories are committed. | [Provenance](https://trdrbot.com/data) |
| `docs/` | Engineering principles, the slide deck, dev journals, research notes, hackathon reference. | [`docs/README.md`](docs/README.md) |
| `specs/` | Architecture, and the two logs that stop work being redone: every design decision and every known defect. | [`specs/decisions.md`](specs/decisions.md) |
| `scripts/` | `publish.sh` — the one script that spans both projects: export → build → verify → deploy. | — |

**The agent runs from `agent/`, not from the repository root.** That is the whole rule; `uv run`
anywhere else finds no project and says so.

## Quick start

Run the agent (needs [uv](https://docs.astral.sh/uv/), Python 3.11+, an Alpaca **paper** account
and at least one LLM key):

```bash
cd agent
cp .env.example .env     # Alpaca paper keys + at least one LLM key
uv sync
uv run trdrbot doctor    # verifies MCP, credentials, and every configured model
uv run trdrbot tick      # one full cycle
```

Run the site (needs Node 20+); it reads a committed snapshot, so it never needs Python running:

```bash
cd web
npm install
npm run dev
```

Full command reference, model configuration and the unattended loop:
[`agent/README.md`](agent/README.md).

## What the record says

Live and continuously updated at [trdrbot.com](https://trdrbot.com). As of **2026-09-03**, after
eight days of paper trading:

| | |
|---|---|
| Equity | **$110,123** from $100,000 (**+10.1%**) |
| Positions opened | 9 |
| Theses formed | 165 — every one pre-registered, traded or not |
| Forecasts resolved | 95, Brier **0.237** over the 76 that score |
| Competence tier | SCALE (size is earned, not chosen) |
| Decisions logged | 120 · known defects logged: see [`specs/issues.md`](specs/issues.md) |

The P&L is reported plainly because it is genuinely judged — and the calibration and attribution
machinery above is the argument for why one week of it is a poor way to judge trading skill.
Both things are true at once, and the project refuses to pretend only the convenient one is.

## Testing

```bash
cd agent
uv run pytest            # 679 tests, offline, network blocked
```

Four tiers — unit/invariant, loop smoke, contract, and a runtime health probe that catches what
tests structurally cannot: a subsystem that runs, returns, logs healthily, and does nothing. The
reasoning is in [`docs/principles_testing.md`](docs/principles_testing.md).

## Hackathon submission

| requirement | where |
|---|---|
| One-page write-up: AI logic, risk gates, Alpaca infrastructure | [`SUBMISSION.md`](SUBMISSION.md) |
| Public repository | this repo, MIT licensed |
| Live application URL | [trdrbot.com](https://trdrbot.com) |
| Slide presentation | [`docs/deck.html`](docs/deck.html) ([hosted](https://trdrbot.com/deck.html), [PDF](docs/deck.pdf)) |
| Alpaca paper account | dedicated to this hackathon, $100,000 start |

Judged on P&L performance, technology implementation, creativity and originality, presentation and
execution, and social engagement. The requirements this repo verified against the live event page
are recorded in [`docs/submission_and_judging.md`](docs/submission_and_judging.md).

## Honest limitations

Calendar and diagonal spreads are **refused**, not approximated — pricing the far leg needs a model
this deliberately does not have, and a confident wrong payoff is worse than a refusal. Calibration
is young: every threshold that matters wants ~50 resolved forecasts, and the size ladder correctly
reflects a record this short. There is no separate approval gate, by choice — the deterministic
sizing math is the guardrail. Known defects are logged the moment they are found and removed only
by the commit that fixes them: [`specs/issues.md`](specs/issues.md).

The longer list, with the reasoning: [`agent/README.md`](agent/README.md#honest-limitations).

## Licence

[MIT](LICENSE) © 2026 Ben Emson.

Paper trading only. This is a hackathon research project, not investment advice, and not a
recommendation to trade any instrument.
