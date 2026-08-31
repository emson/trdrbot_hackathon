# trdrbot — an options-trading agent that knows the difference between right and lucky

**One sentence:** trdrbot senses markets and news, forms a falsifiable thesis, simulates several
option structures expressing it, sizes the winner by Kelly gated on its *own earned track
record*, executes and manages it through Alpaca, then scores afterwards whether its **view** was
right, its **structure** was right, or it just got lucky — and only the first two ever move its
confidence.

## The loop

A scheduler wakes the agent every 60s. Cheap deterministic work — analytics, broker
reconciliation, exit-rule checks — runs **every tick**; the one LLM decision cycle runs every
~15 min. Three independent sources propose theses into one inbox: **research** (daily top-down:
regime + news + prediction-market odds → opportunities), **discovery** (bottom-up: news nominates
companies, a deterministic gauntlet of technicals/fundamentals/liquidity filters before an LLM
ever writes one up), and **the muse** (creative collision of random wiki concepts × news,
argued into chains, adversarially gated). The decide cycle reads the inbox and *very often
declines* — a no-op is a logged, legitimate answer, not a failure.

## AI logic — what the model decides, what the code decides

The LLM's job is narrow: **form a thesis, propose ≥2 structurally different expressions of it,
state a probability, and state a vol view if the thesis is about volatility.** Everything after
that is arithmetic. `simulate_experiments` prices every candidate under **one declared
measure** — the thesis's own drift and (optionally) its own realized-vol forecast — so directional
and volatility theses are judged on the terms they actually claim, with the market's own pricing
shown alongside as the contrast. `size_position` computes Kelly from the structure's
*conditional* payoff (E[win|win]/E[loss|loss] — the naive max/max ratio is measurably biased
toward buying premium) and a probability *shrunk toward the agent's own measured calibration*: a
90%-caller who's right half the time gets cut down; a 70%-caller whose 70%s land 70% of the time
earns the full fraction. Facts (payoff at expiry, breakevens — contract arithmetic) and models
(P(profit), EV — a distributional assumption) are shown under separate headings, deliberately, so
neither gets mistaken for the other.

## Risk gates — deterministic, no LLM veto layer

There is no separate approval step that vetoes an LLM decision after the fact. What replaces it
is stricter: **the agent cannot execute a mistake the math itself refuses to compute.** Kelly
refuses any structure with unbounded *loss* outright (unbounded *profit*, like a long call, is
fine — only the loss side is the danger). Size is capped three ways at once — per-position,
per-underlying, whole-book, all in dollars of defined max loss — and a payoff the sizing tool
can't verify against a real simulated structure **refuses to size at all** rather than falling
back to an optimistic estimate. Once open, a position's own agent-authored exit rules run against
the underlying every 60 seconds — debounced against quote artifacts, but decisive the instant the
underlying itself corroborates a real move. Two rules the agent cannot override: a
competition-deadline sweep, and a rule that closes a position outright if a leg vanishes at the
broker (early assignment) — the survivor of a broken spread can be an unbounded naked position,
worse than the one it replaced. **A "no trade" verdict from any gate is a correct answer, not a
fallback.**

## Alpaca infrastructure

The Alpaca MCP server is the sole broker interface — one stdio session shared for a whole tick
rather than re-spawned per call (−78% wall-clock) — for order placement, the options chain,
quotes, and account reads. Every order's `client_order_id` is derived deterministically from the
decision batch and enforced at the tool-call boundary, so a crash-and-retry resumes the same
intended order rather than opening a second one. A reconciler runs first every tick, diffing
Alpaca's real holdings against trdrbot's own records *before* the exit-rule evaluator sees them,
so a fill, assignment, or external close is never evaluated against stale local state.
`trdrbot doctor` probes every configured LLM and the live MCP connection before anything trades;
`trdrbot health` separately asks, of every subsystem, "did it run *and* produce, or run and
silently do nothing" — the failure mode that has actually cost this project more than any
exception.

## The differentiator: scored honesty, not just P&L

A genuinely 60%-edge agent only beats a coin flip 69% of the time over 20 trades — measured, not
assumed. So position size is *earned*, on a four-tier ladder gated on resolved theses, calibration
reliability, and — the distinctive part — **attribution rate**: whether the agent could actually
explain why it was right, not just whether it made money. A profit on a wrong thesis is excluded
from what lets it size up, by construction.

## Honest limitations

Calendar/diagonal spreads are refused, never approximated, absent a pricing model for the far leg.
No separate guardrail layer exists by choice — the deterministic gates above are the guardrail.
Calibration is young (paper account, one week); every number reported carries its sample size.
