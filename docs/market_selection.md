# Market Selection Review

For the team — what markets trdrbot actually trades and researches today, why that's the right
call for the hackathon window, and what's worth deciding on together before we expand it.

## Current configuration (config.yaml)

```yaml
research:
  universe: ["SPY", "QQQ", "NVDA"]   # daily regime page + company dossiers

trading:
  watchlist: ["SPY"]                  # the only symbol we actually place trades on

polymarket:
  queries: ["fed rate cut", "us recession", "cpi inflation"]  # macro odds
```

So: **we research three names, but only trade one.** That's a deliberate scope decision, not an
oversight — here's the reasoning, and where it's worth a team call.

## Why SPY is the right (and only) traded market right now

**It's the most liquid options market that exists.** Tightest spreads, deepest chains, weekly and
even daily expiries. That matters twice over: it makes our friction-cost modelling (see README —
a real candidate went from +$25 EV to +$9 after costs) realistic rather than punishing, and it
gives us short-dated expiries that can actually *resolve* inside an 8-day competition window.

**It's the natural target for our macro signals.** The Polymarket sensors we run — Fed rate cut
odds, recession odds, CPI odds — are macro, index-level questions (D-027). They map cleanly onto
a broad index like SPY. They don't map cleanly onto a single name, where earnings, product news,
or idiosyncratic moves would swamp the macro signal we're trying to correlate against.

**It suits defined-risk multi-leg strategies.** Spreads and condors — our core expressions — want
a smooth, liquid IV surface. Index products give us that; single names are more prone to skew and
gaps that make multi-leg pricing unreliable.

**It concentrates our calibration sample.** The whole point of D-013 (calibration/Brier scoring)
is a track record that's honest, and honest requires *enough resolved trades to say something
statistically*. Splitting a one-week trade count across three or four symbols would thin the
sample right when we need it thickest. One symbol, more resolved trades, a calibration record
that actually means something.

## Why QQQ and NVDA are research-only, not traded

They're in the **research universe** — the daily regime page and company dossiers cover them —
but deliberately *not* in the trading watchlist. That gives the agent broader context (different
sector, different beta, NVDA's much higher IV) to reason about without multiplying the number of
live positions we have to reconcile, size, and attribute inside a short, unattended build window.

This is the same instinct behind D-019's competition-deadline sweep: everything about this build
is scoped to guarantee the learning loop actually *closes* inside 8 days. More traded symbols is
more content variety, but it's also more surface area for something to go wrong mid-week with
less time to recover.

## The trade-off, stated plainly

| | Stay SPY-only | Add a second traded symbol |
|---|---|---|
| Calibration sample | Concentrated, statistically meaningful | Thinner, split across symbols |
| Demo/content variety | One deep, well-attributed thesis chain | Multiple stories, more social content |
| Execution risk | Lower — one reconciliation surface | Higher — more moving pieces mid-sprint |
| Macro-signal fit | Clean (Polymarket → index) | NVDA introduces idiosyncratic noise the macro sensors don't cover |

## Recommendation

1. **Keep SPY as the only traded market through the core build phase** (through ~Sept 2). The
   architecture, the macro sensors, and the calibration design all point the same direction — don't
   dilute the one thing we need most this week, which is enough resolved SPY trades to make the
   calibration record mean something.
2. **Keep QQQ and NVDA as research-only** unless we have a specific reason to trade them.
3. **If we do add a second traded symbol, NVDA is the natural pick** — already researched, high
   IV, and it's a better fit for a volatility play (straddle/strangle) that would complement SPY's
   income/directional spreads and round out the strategy showcase. Only do this once the SPY loop
   is proven end-to-end (thesis → execution → resolution → attribution, at least once) — adding it
   earlier risks debugging two symbols at once with no working reference case.
4. **Not currently in scope, worth a team discussion:** sector ETFs (e.g. XLF for the Fed-cut
   thesis, XLE for macro-energy questions) would let us trade the macro theme more directly than
   SPY does, at the cost of adding yet another symbol. Raise it if we want that narrative, but it's
   not free — same sample-dilution trade-off as above.

**Bottom line for the team:** the narrow scope is intentional and load-bearing, not something we
forgot to widen. Any change to the trading watchlist should be a deliberate call weighed against
calibration sample size and execution risk, not a default expansion once things feel stable.
