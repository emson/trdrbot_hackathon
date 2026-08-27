# Multi-Leg Options & Greeks, Explained From Scratch

A plain-language primer on two terms that show up constantly in this project — what they mean,
why they matter, and why they're worth featuring in dev-diary posts.

## The basic building block: an "option" and a "leg"

An option is a contract that gives you the *right* (not obligation) to buy or sell 100 shares of
a stock at a fixed price ("strike") by a certain date. There are two types:

- **Call** = right to *buy* at the strike (bet the stock goes up)
- **Put** = right to *sell* at the strike (bet the stock goes down)

One single option contract = **one leg**. If your trade is just "buy 1 call," that's a
**single-leg** trade.

## What "multi-leg" means

A multi-leg trade combines two or more legs into one package, executed together as a single
strategy. Here's a concrete example — a **bull call spread**:

```
Leg 1: BUY  1 call, strike $150, costs you $5.00 ($500 for the contract)
Leg 2: SELL 1 call, strike $155, you receive $3.00 ($300)
────────────────────────────────────────────
Net cost: $2.00 ($200) — you paid $500, got back $300
```

Why do this instead of just buying the call?

- **It's cheaper** ($200 instead of $500) because selling the second call gives you money back.
- **It caps your risk** — max loss is exactly $200, the amount you paid, no more.
- **The tradeoff:** it also caps your *profit* at $500 (the $5 gap between strikes), whereas the
  single call alone could theoretically make unlimited money.

That's the whole idea of multi-leg trading: **you're trading unlimited upside for a cheaper, more
precisely defined risk.** Iron condors (4 legs), straddles (2 legs), collars (2-3 legs) are all
the same principle — combine legs so the *shape* of your risk matches your actual view, instead
of just betting big in one direction.

**Why it matters for judging:** anyone can click "buy call." A multi-leg trade is proof you
understand risk shaping, not just direction-guessing — which is exactly why the hackathon's
judging criteria call out "options strategy sophistication" as its own category.

## What "Greeks" are

The Greeks answer one question each: **"If X changes by a little bit, how much does my option's
price change?"** They're named after Greek letters, but don't let that intimidate you — they're
just sensitivity numbers, like a speedometer or a fuel gauge.

### Delta — "how much does the price move if the stock moves $1?"

If a call option has a **delta of 0.50**, and the stock goes up $1, the option's price goes up
about $0.50.

- Deep-in-the-money options: delta close to 1.00 (moves almost dollar-for-dollar with the stock,
  acts like owning the stock)
- At-the-money options: delta around 0.50
- Far-out-of-the-money options: delta close to 0.00 (the stock would need a huge move to matter)

**Intuition:** delta is roughly "how much does this option act like just owning the stock."

### Gamma — "how fast does delta itself change?"

If delta is speed, gamma is acceleration. A high-gamma option's delta shifts fast as the stock
moves — meaning your risk profile can change quickly, especially right before expiration.

**Example:** an at-the-money option a day before expiry has huge gamma — a $1 stock move can flip
its delta from 0.50 to 0.90 almost instantly. That's why options traders get nervous near
expiration.

### Theta — "how much value do I lose just from time passing?"

Options are wasting assets — every single day, they lose a little value even if the stock doesn't
move at all, because there's less time left for the bet to pay off. Theta is usually shown as a
negative number.

**Example:** theta of **-$0.05** means the option loses about $0.05 (×100 shares = $5 per
contract) in value *every day*, all else equal, just from the calendar ticking forward.

**Intuition:** think of an ice cube melting. Theta is the melt rate.

### Vega — "how much does price change if expected volatility changes?"

Options get more expensive when the market expects bigger price swings (even if it doesn't know
which direction), and cheaper when things calm down. Vega measures sensitivity to that
expectation — called **implied volatility (IV)**.

**Example:** before an earnings announcement, IV spikes because everyone expects a big move —
options get pricier even though the stock hasn't moved yet. High vega means your option's price
is very sensitive to that expectation rising or falling.

### Rho — "how much does price change if interest rates change?"

The least important one for short-dated trades (like everything in this hackathon's 8-day
window) — it matters much more for options that expire years out. Usually safe to mention briefly
and move on.

## Putting it together with a real example

Say the agent is looking at that bull call spread from earlier:

```
Buy call @ $150, delta 0.55, theta -$0.06, vega 0.12
Sell call @ $155, delta 0.30, theta -$0.04, vega 0.09
```

The *combined* position has:

- **Net delta ≈ 0.25** — the spread is much less sensitive to the stock's direction than owning
  either call alone, because the short call cancels out part of the long call's directional
  exposure.
- **Net theta ≈ -$0.02** — time decay is much smaller than a single naked call, because the short
  leg is also decaying *in your favor*.
- **Net vega ≈ 0.03** — barely sensitive to changes in expected volatility.

That's the actual value of multi-leg trading in one sentence: **combining legs lets you cancel
out the risks you don't want (unlimited loss, heavy time decay, volatility exposure) while
keeping the direction you do want.**

## Why this is the thing to show off in dev-diary posts

A post that says "we bought a call" tells Alpaca nothing about your agent's sophistication. A
post that says:

> "The agent priced a bull call spread on SPY — net delta 0.25, theta -$0.02/day, vega 0.03 — and
> chose it specifically because it wanted moderate upside exposure without eating heavy time
> decay into the weekend"

...proves your agent is reasoning about *risk shape*, not just direction — which is precisely
what the judging criteria and Alpaca's own options-trading requirement are asking you to
demonstrate. It's also concrete and quotable, which is exactly what makes a dev-diary post land
instead of reading as a generic claim. See [`social_media_playbook.md`](../social_media_playbook.md)
for how this fits into the broader posting strategy.
