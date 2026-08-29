# trdrbot — an options trading agent called Theo

Theo learns *why* it was right, not just whether it made money.

Built for the Alpaca AI Trading Agents Hackathon. Paper trading only.

```
news ─┐
odds ─┼─▶ research ─┐
wiki ─┘   discovery ─┼─▶ thesis ─▶ simulate ─▶ size ─▶ execute ─▶ attribute ─┐
          muse ──────┘      ▲                                                │
                            └──────────── what it learned ───────────────────┘
```

---

## The idea

Most trading agents score themselves on profit and loss. Over a one-week window that is close to
meaningless, and we measured it rather than assuming: a genuinely skilled agent with a 60% edge
out-scores a coin flip only **69% of the time over 20 trades**, and a zero-skill agent lands
anywhere between **−7.8% and +8.2%**. Worse, an agent that learns from P&L alone reinforces
whatever story happened to correlate with money — which is how a system acquires a superstition.

So Theo separates two questions that P&L conflates:

**Was the view right?** and **was the way I expressed it right?**

| thesis | outcome | what it learns |
|---|---|---|
| held | profit | reinforce both |
| held | loss | **the view was fine** — the strikes, width or stop were wrong |
| failed | loss | correct the view; the structure was faithful |
| failed | profit | **learn nothing** — this was luck |

That bottom row is the important one. P&L-based scoring treats a lucky win as strong
confirmation. Here it moves nothing — and it actively blocks promotion up the size ladder.

## Quick start

```bash
cp .env.example .env          # Alpaca paper keys + at least one LLM key
uv sync
uv run trdrbot doctor         # verifies MCP, credentials, and EVERY configured model
```

```bash
uv run trdrbot tick           # one cycle
uv run trdrbot run            # loop until the deadline (see Running unattended)
```

## Configuring models

Any provider LangChain supports works. `init_chat_model` **is** the provider registry, so adding
one is a line of config plus (usually) one package — no code changes.

```yaml
llm:
  # ORDERED FALLBACK CHAIN — first model that answers wins.
  models:
    - "openai:gpt-5.6-sol"
    - "anthropic:claude-opus-5"
    - "openai:gpt-5"
  max_tokens: 8000

  # A model's own API quirk, NOT a provider-wide one — composes with
  # `providers:` below rather than replacing it. gpt-5.6-sol refuses tool
  # calls on the classic Chat Completions endpoint while reasoning is
  # active; a live 400 named the fix. Applying this globally would break
  # ChatAnthropic, which has no such kwarg, the moment Claude shares a
  # chain with it — the same reason gateway overrides are per-spec too.
  model_options:
    "openai:gpt-5.6-sol":
      use_responses_api: true

  # Optional per-role chains. A role not listed here uses `models` above.
  roles:
    decide:    ["openai:gpt-5.6-sol", "anthropic:claude-opus-5", "openai:gpt-5"]
    research:  ["openai:gpt-5.6-sol", "openai:gpt-5-mini", "anthropic:claude-opus-5"]
    discovery: ["openai:gpt-5.6-sol", "openai:gpt-5-mini", "anthropic:claude-opus-5"]
    muse:      ["openai:gpt-5.6-sol", "openai:gpt-5-mini", "anthropic:claude-opus-5"]
    doctor:    ["openai:gpt-4o-mini"]

  # USD per MILLION tokens. Operator-supplied — verify against current published
  # rates; these are not fetched and will go stale. A model missing here is
  # reported as UNPRICED, never counted as free.
  pricing:
    "openai:gpt-5.6-sol":     {input: 4.00, output: 20.00}
    "anthropic:claude-opus-5": {input: 15.0, output: 75.0}
    "openai:gpt-5":            {input: 1.25, output: 10.0}
```

Adding a provider LangChain has a builtin for:

```bash
uv add langchain-google-genai          # 1. the package
export GOOGLE_API_KEY=...              # 2. the key, in .env
# 3. add "google_genai:gemini-2.5-pro" to llm.models — done
```

**Adding an OpenAI-compatible gateway** (a third-party router that serves several models
behind one endpoint — OpenCode Zen, OpenRouter, a company's internal proxy) is a different
case: `init_chat_model`'s provider table is fixed, and every model behind one real prefix
(`openai:`) shares one endpoint and one key by construction. A second OpenAI-compatible
service can't just reuse that prefix without hijacking the real `openai:gpt-5` entries in the
same chain. So it gets a config-level provider instead — `llm.providers.<name>` names which
builtin actually serves the traffic and supplies a per-spec `base_url`/`api_key_env`; a spec
like `"opencode_zen:<model-id>"` resolves to `openai:<model-id>` plus the gateway's own
connection, and every other spec is untouched. Not currently in the active chain (see
below), but the mechanism is exercised by both `providers:` and `model_options:` sharing the
one resolver:

```yaml
llm:
  providers:
    opencode_zen:
      langchain_provider: "openai"
      base_url: "https://opencode.ai/zen/v1"
      api_key_env: "ZEN_API_KEY"
```

```bash
export ZEN_API_KEY=...                       # 1. the key, in .env — get one at opencode.ai/auth
# 2. add "opencode_zen:<model-id>" anywhere a spec goes — done, no new package
```

`uv run trdrbot doctor` probes it exactly like a builtin provider (both share one resolver —
`Config.resolve_model_spec` — so they cannot silently disagree about what a spec means), and a
missing key skips that one entry with a logged reason rather than taking the chain down: the
fallback machinery this section already describes covers a gateway outage the same as a
builtin-provider one. **Tool-calling reliability through a new gateway is a belief, not a
given** — `bind_tools`/`create_react_agent` is what every role here actually needs, and a
model that answers plain chat fine but mishandles tool schemas would make `decide` look
healthy while never calling `simulate_experiments`. Verify it with a real contract test
before trusting it unattended (`uv run pytest -m contract -k <gateway>`), the same discipline
this project already applies to every other external belief (see Testing, below).

The fallback is verified against the real failure, not a guess: an exhausted Anthropic key
raises `AnthropicInvalidRequestError` — a **400**, not a rate-limit or auth class — and a
fallback keyed on the wrong exception would never fire. `uv run trdrbot doctor` probes **every**
configured model, because a fallback that has never been exercised is a promise, not a capability.

### Which role needs which model — and where the money actually goes

**~80% of the bill is input tokens, not output**, because a tool-using agent re-sends its whole
accumulated context on every turn. So the levers are all about what enters context and how often
it is paid for — not about model tier.

- **`decide` should keep the strongest model.** It is multi-step tool use under uncertainty, and
  it is the only role where a bad judgment costs real money. Economising here is false thrift.
- **Routing the other roles to cheap models saves very little.** `research`, `discovery` and
  `muse` are one call each with small context — a few cents. The reason to route them is
  **resilience** (they keep working when the primary provider is down or out of credit) and
  tidiness, not cost.

Three levers, measured on adjacent real cycles rather than estimated:

| lever | before | after |
|---|---|---|
| option chain into context | 79,542 chars (~20k tokens), re-sent every turn | 6,076 chars (**−92%**) |
| Alpaca MCP | a new `uvx` subprocess **per tool call** | one session per tick (**−78%** wall clock) |
| the repeated prefix | full price on all 7 turns | cached, read back at **0.1x** |

**$3.46 → $1.32 per decide cycle**, and the reasoning got sharper rather than thinner — trimming a
61k-character chain to the strikes near spot is not a trade-off against accuracy, because burying
the relevant rows in 57k of noise is exactly where model recall degrades.

The lesson that generalises: **all three had shipped as code that ran and did nothing.** The
compactor failed open against an envelope shape it did not recognise, the session was never shared,
the cache was never asked for. `trdrbot usage` now prints the cached share per model, because a
zero there next to a large input count is the only visible sign that caching stopped engaging.

```bash
uv run trdrbot usage          # spend by model and role, with cached share
```

## Commands

| | |
|---|---|
| `doctor` | verify MCP, credentials, and every configured model |
| `tick` / `tick --force` | one cycle; `--force` runs the decide path outside market hours |
| `run` | loop until the deadline, two cadences |
| `health` | which subsystems ran but produced nothing |
| `journal` / `ledger` / `usage` | what happened / every thesis ever formed / LLM spend and cached share |
| `calibration` | Brier score with Murphy decomposition |
| `research` / `discover` / `muse` | the three thesis sources, on demand |
| `constitution show\|seed\|verify` | the epistemic principles in memory |
| `lessons show\|seed\|verify` | measured lessons, and whether they still recall |
| `prompts` | every prompt the models read, with fingerprints |
| `coach status\|pulse` | the self-improvement loop: levers, open trials, promotions |
| `report` | write `data/report.html` - gauges over time, experiments, what the Coach did |

## The Coach — subsystems that improve themselves

Everything above improves when a human finds a defect. The Coach makes improvement a runtime
behaviour: it runs paired A/B trials on the muse's collision prompt, scores each variant by the
**fraction of its candidates that survive the muse's own deterministic gauntlet**, and promotes a
winner without asking.

It is autonomous on purpose — approval gates block the feedback loop, and this is paper trading.
What makes that safe is that autonomy is bounded **by construction**, not by asking:

- **It touches data, never code.** Variants live in `data/state/levers/*.json`. There is no code
  path from Coach state to a gate threshold, sizing math, or a sentinel.
- **The challenger is a shadow.** During a trial the incumbent runs production exactly as before;
  the challenger reaches the same verdicts through the *same gate code* but writes nothing — no
  ledger row, no inbox item. Both arms share one memo of closes and option chains, so a moving
  quote cannot masquerade as a variant difference.
- **Promotion needs real evidence.** `P(challenger better) ≥ 0.90` on Beta posteriors, plus floors
  of 8 paired runs and 24 candidates per arm. Identical arms return exactly 0.5 and time out.
- **Sentinels revert.** Daily cost ceiling, promotion churn, and a seed-entropy floor that stops
  the muse being optimised out of colliding diverse concepts — its whole mandate.
- **elfmem's constitution is not a lever** and will not become one: its own ADR 0003 measured
  automatic constitutional evolution as no better than baseline.

**Steering, not gating.** Read `trdrbot report` for the trajectory with the Coach's own actions
overlaid. To intervene, edit the lever's state file: `"paused": true` stops experimentation,
`"pinned": true` also stops the audit re-matching it — one pin freezes behaviour for a demo.
Editing the incumbent prompt by hand is supported; the fingerprint is recomputed from the text.

## How a thesis is formed

Three independent sources, all landing in the same inbox seam:

- **research** — daily, top-down. Computed technicals + news + prediction-market odds → a regime
  page and company dossiers in the wiki → falsifiable opportunities.
- **discovery** — the *news nominates the companies*. Nominations must cite their evidence, then
  every nominee passes a deterministic gauntlet (technicals, bootstrap forecast, Yahoo
  fundamentals, options-liquidity gate) before a second LLM call writes opportunities.
- **muse** — creative collision. Random wiki concepts × news × odds → argue the domino chains →
  every candidate pre-registered → adversarial evaluation → the top 2 graduate.

The decide cycle then owns the trade: it validates against live quotes, simulates competing
structures, sizes by earned calibration, and very often declines.

## What makes it work

**Position size is earned, not chosen.** A competence ladder — EXPLORE → ESTABLISH → SCALE →
MATURE — gated on resolved theses, calibration reliability, and *attribution rate*. That last one
is the distinctive part: **a profit on a wrong thesis is luck, and a book of luck is not
competence however good the P&L looks.** Promotion past ESTABLISH requires that most resolved
theses were actually explicable. Drawdown demotes immediately; recovery restores.

**Percentages mean what a trader means.** A stop or
target is a percent of the net debit paid or credit received, not of the notional or the gross
premium traded. Getting that wrong is not cosmetic: on the gross base, three of the four
mark-based exit rules this book has ever carried could not fire at all, and `record_position` now
says so out loud when a rule it is handed can never trigger.

**Facts and models are never mixed.** Payoff at expiry, max loss and breakevens are arithmetic on
the contract. Probability and expected value need a distribution and are labelled MODELLED. The
agent sees them under separate headings, because one deserves far more weight.

**Real returns, not just lognormal.** A bootstrap Monte Carlo resamples the underlying's *own*
history — demeaned, so a year that happened to rally isn't projected forward as structural. The
*gap* between the two estimates is itself the signal: when they disagree, the edge depends on the
tail assumption.

**Risk shape is first-class.** Black-Scholes greeks per candidate, per-leg IV so measured skew is
priced, and **beta-weighted book delta** — because names are not exposures. Measured live: SPY and
QQQ correlate at 0.92, and one NVDA position showed $63,987 of raw delta but **$118,261**
beta-weighted.

**Costs are charged before the decision**, and against the agent's *own* view. Two EV columns
sit side by side: expected value under the market's own drift — where a fairly priced structure is
worth about nothing, so after friction it is negative for everything, always — and expected value
under the drift the thesis actually claims. A thesis that cannot move the second column is
decorative, and for a while only the first one existed.

**One clock, and it is the market's.** Implied vol is quoted on ACT/365, so a Friday quote already
prices the weekend it spans; discounting it again counts the same adjustment twice. Greeks,
probabilities and the expected move now share that clock. The trading-day clock survives for the
one job it is right for — comparing a 365-day implied vol against a 252-session realised one, which
raw is a 17% error in the direction that says don't sell.

**Exit rules are the agent's own commitments, executed deterministically.** One signal registry:
every rule reads a signal, compares to a threshold, debounces. Thesis-level stops watch the
*underlying*, not the noisy option mark.

**Every position traces back to its reasoning** — one `position_id` through an append-only
journal, an OKF wiki, evolving memory, and back to the broker via `client_order_id`.

## Running unattended

```bash
uv run trdrbot run --interval 300 --closed-interval 1800
```

Two cadences, because the work differs. **Open:** decide, market-pulse and exit-rule evaluation
every 5 minutes — stops checked hourly are worthless. **Closed:** housekeeping, research,
attribution and memory consolidation every 30 minutes. A failing tick never stops the loop, and a
singleton lock plus a 30s interval floor prevent the runaway loops we actually caused once.

When the inbox is empty the system climbs an **idle ladder** rather than either spinning or
sleeping blindly: *sleep* (nothing at risk, nothing moved), *review* (a material move or too long
without looking), *hunt* (capital idle and deployable). The asymmetry that sets it: the cost of
not looking scales with what is at risk; the cost of looking scales with LLM spend. And idle
capital is a position too — 100% cash at 0% expected return.

## Testing

```bash
uv run pytest                 # fast, offline, network blocked — run habitually
uv run pytest -m contract     # real APIs; before a deploy or after a dependency bump
uv run trdrbot health         # runtime: what ran but produced nothing
```

Four tiers, weighted by where our bugs actually came from — we categorised all ~38 of them, and
**essentially none were found by a unit test catching a logic error.** They were wrong beliefs
about a seam, and silent no-ops. So:

- **unit + invariant** — a monotonicity check over the whole ladder caught two shipped size
  inversions; a convergence check caught a 16pp drift bug. One invariant beats ten examples.
  With a caveat learned the hard way: an invariant is only as good as the space it sweeps. That
  same monotonicity check went on passing through **two more** ladder inversions because it
  measured integer contracts at one payoff, where a rounding floor pinned every rung to the same
  number.
- **derive test inputs from the real producer, never from a literal.** Two capabilities were dead
  in production while their tests passed, because the test and the caller disagreed about units
  (percent vs fraction) or types (dict vs tuple) while each was internally consistent. A test that
  builds its own input proves a function is self-consistent and says nothing about the seam.
- **loop smoke** — the whole learning ladder offline with known inputs. Found two
  credit-assignment bugs every unit test passed straight over.
- **contract** — one file, one belief per test, checked against the real service, written so the
  failure names the belief: *"price is no longer nested under `trades`"*.
- **health** — not a test. Catches what tests structurally cannot: a path that runs, returns,
  logs healthily, and does nothing. **A subsystem's heartbeat must be a different record from its
  output**, or "ran" and "produced" are the same number and the check is a tautology — which is
  how a scorer that fired eight times and then died reported "ran 8x, produced 8" for two days.

Rationale and rules: [`docs/principles_testing.md`](docs/principles_testing.md).

## Honest limitations

- **Calendar and diagonal spreads are refused**, not approximated. Pricing the far leg needs a
  model this deliberately does not have, and a confident wrong payoff is worse than a refusal.
- **Calibration is n=1.** Every threshold that matters needs ~50 resolved forecasts. Unconditional
  forecast logging exists to get there faster, but the record is young and the size ladder
  correctly reflects that.
- **The first position can never be attributed** — no thesis was recorded at entry. Fabricating
  one retroactively would be worse than the gap.
- **No guardrails, by choice.** Paper account, iteration speed mattered. What exists instead is
  the agent's own exit rules, sizing that refuses unbounded-loss structures, and book-level caps.
- **Known issues are tracked openly** in [`specs/issues.md`](specs/issues.md) — recorded the
  moment they are found, removed only by the commit that fixes them.

Design decisions and their reasoning: [`specs/decisions.md`](specs/decisions.md) (D-001…D-075).
Architecture and invariants: [`specs/architecture.md`](specs/architecture.md).
