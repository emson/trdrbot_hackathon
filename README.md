# trdrbot

An options-trading agent that learns *why* it was right, not just *whether* it made money.

Built for the Alpaca AI Trading Agents Hackathon. Paper trading only.

```
sensors ─▶ inbox ─▶ [ thesis ─▶ simulate N structures ─▶ size ─▶ execute ] ─▶ attribute ─▶ memory
                                        ▲                                                    │
                                        └──────────────── what it learned ───────────────────┘
```

---

## The idea

Most trading agents score themselves on profit and loss. Over a one-week window that is close to
meaningless, and we measured it rather than assuming: a genuinely skilled agent with a 60% edge
out-scores a coin flip only **69% of the time over 20 trades**, and a zero-skill agent lands
anywhere between **−7.8% and +8.2%**. A good week proves nothing. Worse, an agent that learns
from P&L alone reinforces whatever story happened to correlate with money — which is how a
system acquires a superstition.

So trdrbot separates two questions that P&L conflates:

**Was the view right?** and **was the way I expressed it right?**

| thesis | outcome | what it learns |
|---|---|---|
| held | profit | reinforce both |
| held | loss | **the view was fine** — the strikes, width or stop were wrong |
| failed | loss | correct the view; the structure was faithful |
| failed | profit | **learn nothing** — this was luck |

That bottom row is the important one. P&L-based scoring would treat a lucky win as strong
confirmation. Here it moves nothing.

## What makes it work

**Position size is earned, not chosen.** Sizing is the largest lever on long-run profit, and it
runs on Kelly — scaled fractionally, because full Kelly is acutely fragile to estimation error,
and gated on the agent's *measured* calibration. Stated confidence is shrunk toward the base rate
in proportion to how well the agent's probabilities have actually held up. With no track record,
a stated 70% confidence buys **zero contracts**. With a proven 30-sample record, the same 70%
buys **16**.

That is the self-improving loop made concrete: better calibration is not a number on a
dashboard, it is permission to bet more.

**Facts and models are never mixed.** Payoff at expiry, max loss and breakevens are arithmetic on
the contract — they cannot be wrong. Probability of profit and expected value need a distribution
and use lognormal-at-current-IV, which is standard and still an assumption with wrong tails. The
agent sees them under separate headings, because one deserves far more weight than the other.

**Costs are charged before the decision, not after.** Options spreads are wide; simulating at mid
overstates every edge, most for the cheap far-OTM options that look best on a payoff diagram. On
a real candidate this run: expected value **+$25 before friction, +$9 after**. Friction is
routinely the same size as the edge, and the agent has declined trades on exactly that basis.

**Exit rules are the agent's own commitments, executed deterministically.** It states a stop and
a target at entry; a no-LLM evaluator checks them every tick and closes the position without
asking. Rules fire on the position's net mark and close *all* legs — closing one leg of a spread
can leave an unbounded naked short.

**Every position traces back to its reasoning.** Alpaca knows what we hold and nothing about why.
One `position_id` threads each position through an append-only journal, a markdown knowledge base
following Google's Open Knowledge Format, the agent's evolving memory, and back through the
broker via `client_order_id`.

## A real decision

From a live run, deciding against a trade:

> Both negative after costs, so I stopped before `size_position`. The call credit spread is
> exactly the trap: collect $51 to risk $449 needs ~90% accuracy to break even […] Call-side IV
> is 7.4% vs put-side 16.5% — selling upside calls here means selling the cheap wing of a heavily
> skewed surface into an earnings print. And any call spread I sold would be stacked on top of an
> existing short-vol position, doubling the same factor exposure rather than diversifying it.

Not trading is a valid output, and the system is built so that it is frequently the correct one.

## Running it

```bash
cp .env.example .env      # Alpaca paper keys + an LLM key
uv sync
uv run trdrbot doctor     # verifies MCP connection, credentials and the model
```

```bash
uv run trdrbot tick             # one cycle
uv run trdrbot tick --force     # run the decide path outside market hours
uv run trdrbot journal          # what happened
uv run trdrbot calibration      # Brier score + Murphy decomposition
```

The inbox is the seam: drop a JSON file into `data/inbox/pending/` and the pipeline picks it up.
That is how you test the whole system without waiting for a market event.

```bash
uv run trdrbot inject --payload '{"note":"SPY looks range-bound into Friday"}'
```

## How it is put together

The tick splits by cost. Cheap deterministic work — collect, analytics, reconcile against the
broker, evaluate exit rules — runs every cycle with no model involved. The expensive reasoning
path runs on a slower cadence. That shortens the exposure window *and* cuts LLM spend, because
noticing a breached stop needs arithmetic, not intelligence.

| | |
|---|---|
| `sensors.py` | declarative sources — Alpaca news, Polymarket odds. Adding one is a registry entry |
| `optmath.py` | payoff and probability maths, split by how much each deserves trust |
| `experiments.py` | thesis, candidate structures, ranking, and the attribution verdicts |
| `sizing.py` | Kelly, fractional, gated on measured calibration |
| `calibration.py` | Brier score with Murphy's reliability/resolution/uncertainty decomposition |
| `exit_rules.py` | deterministic evaluation of the agent's own stated exits |
| `attribution.py` | view-vs-structure verdict, at the thesis horizon |
| `elfmem_adapter.py` | evolving memory — what it recalled is what gets credited |

Design decisions and their reasoning live in [`specs/decisions.md`](specs/decisions.md) (D-001
through D-031); the architecture, invariants and failure modes are in
[`specs/architecture.md`](specs/architecture.md). The design was stress-simulated twice before
any code was written, and both passes are recorded in [`specs/notes/`](specs/notes/).

## Honest limitations

- **Calendar and diagonal spreads are refused**, not approximated. Pricing the far leg at the
  near expiry needs a model this deliberately does not have, and a confident wrong payoff is
  worse than a clear refusal.
- **The probability model is lognormal at current IV.** Real returns have fatter tails. The
  calibration record is what would expose this, and it needs more resolved trades than one week
  provides.
- **No guardrails, by choice.** This is a paper account and iteration speed mattered more. What
  exists instead is the agent's own exit rules plus sizing that refuses unbounded-loss
  structures outright.
- **Attribution needs the thesis horizon to arrive.** A stop on day two of a ten-day thesis is
  recorded but not yet judged — scoring it early would be the exact mis-attribution the system
  exists to avoid.
