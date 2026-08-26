# trdrbot

AI options trading agent for the Alpaca AI Trading Agents Hackathon
(paper trading only, deadline 2026-09-04).

Design lives in [`specs/`](specs/) - start with
[`specs/architecture.md`](specs/architecture.md) for the conceptual overview,
[`specs/decisions.md`](specs/decisions.md) for why things are the way they are.

## Status: walking skeleton

The end-to-end path is wired: **inbox -> decide -> act via Alpaca MCP ->
journal**. Sensors, memory (elfmem + wiki), exit rules, reconciliation and
calibration are designed but not yet built - see the build order in
`specs/architecture.md` §13.

## Setup

```bash
cp .env.example .env      # then fill in your keys
uv sync
uv run trdrbot doctor     # verifies config, secrets and the MCP connection
```

`doctor` spawns `uvx alpaca-mcp-server` as a stdio subprocess and lists the
tools it exposes. If it fails, it tells you what to check.

Note the credential names: the MCP server uses `ALPACA_API_KEY` /
`ALPACA_SECRET_KEY`, **not** the `APCA_*` names used by Alpaca's REST SDK.

## Exploring it

```bash
uv run trdrbot inject                 # drop a test observation into the inbox
uv run trdrbot tick                   # run one tick end to end
uv run trdrbot journal                # see what happened
```

The inbox is the seam: anything that writes a JSON file into
`data/inbox/pending/` gets picked up. That is how you test the whole pipeline
without waiting for a real market event.

```bash
uv run trdrbot inject --type manual --payload '{"note":"SPY looks range-bound"}'
```

`./run.sh` runs one tick and is what a scheduler should point at.

## What is deliberately real already

Four mechanics that two rounds of design simulation found load-bearing, built
in from the start because retrofitting them is painful:

- **Write-ahead journalling** - the decision is recorded *before* the order is
  submitted, and on retry the processor resumes from that record rather than
  re-invoking the LLM. An LLM is nondeterministic, so re-deciding after a crash
  would orphan the record and burn a call.
- **Batch-derived `client_order_id`** - the idempotency key comes from the
  inbox batch, not the decision. Any resubmission from the same batch carries
  the same id, so Alpaca rejects the duplicate. A decision-derived key would
  differ after a re-decide and open a *second, different* position.
- **Dead-lettering** - an item that fails repeatedly moves to
  `data/inbox/failed/`. Without it one malformed item is retried forever and
  the pipeline stalls while looking healthy.
- **Stale-breakable lock** - the tick lock carries a PID and timestamp, so a
  crashed run does not silently skip every subsequent tick.

## No guardrails, on purpose

There is no risk-policy layer (D-009). This is a paper account and iteration
speed matters more than protecting simulated money. What the design does have
is *agent-authored exit rules* (D-017) - stop-loss and profit-target conditions
the agent sets itself at entry and a deterministic evaluator honours. That is a
commitment device the agent controls, not a constraint imposed on it.
