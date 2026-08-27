# trdrbot Dev Diary — Social Media Approach

## The shift: diary, not marketing

The first draft of this doc organized content into "pillars" — evergreen angles you could post in
any order. That's the wrong shape. What we're building only reads as interesting if you can see
the actual sequence: a design decision, a test that broke it, a fix, a live moment where the
agent did something worth quoting. Marketing copy flattens that into a highlight reel. A diary
keeps the order, which is what makes it credible and what makes it a story instead of an ad.

So: **write posts as dated entries, in the order things actually happened**, first person, plain
language. Post the boring days too, briefly — a diary that only has good days reads as curated,
which defeats the purpose.

## The throughline — why this is actually interesting

Every entry should trace back to one question, even the small ones: **can an agent tell the
difference between being right and being lucky?**

Most "AI trading agent" projects can't answer that, because they score themselves on P&L, and
over a one-week window P&L is close to noise — we measured it: a genuinely skilled agent with a
60% edge only beats a coin flip 69% of the time over 20 trades, and a zero-skill agent can land
anywhere from -7.8% to +8.2% by pure chance. An agent that learns from P&L alone will reinforce
whatever story happened to correlate with money. That's how a system acquires a superstition.

So the whole build — the calibration tracking, the view-vs-structure attribution, the friction
costs charged before the decision, the sizing that has to be earned — is one long answer to that
single question. When a post feels like it's just describing a feature, tie it back to this. When
it doesn't tie back, it's probably not worth posting.

## What Alpaca actually wants to see

Alpaca is a sponsor, a platform, and an audience all at once. Their own hackathon framing is "What
if your next trading strategy wrote and executed itself?" — so the content that serves them best
is content that makes *their* pitch look true, using specifics rather than adjectives.

Concretely:

- **Show the agent deciding and executing through their tools, by name.** Not "our AI trades
  options" — "the agent called the MCP server's options-chain and multi-leg order tools, priced a
  spread against real Greeks, and placed it in the paper account." Specificity is what makes this
  read as a genuine product testimonial rather than a generic claim.
- **Surface options depth, not just single-leg trades.** Their submission requirement is options
  trading; their judging criteria explicitly score "options strategy sophistication." A post about
  a multi-leg spread, with real IV/Greeks numbers, demonstrates exactly what they're asking
  entrants to prove — and it's the kind of concrete technical detail worth featuring.
- **Use their own pitch back at them.** "Real market data, zero real money at risk, $100k
  simulated" is literally their paper-trading pitch. Screenshots of the Alpaca dashboard, journal
  entries referencing real fills — that's free advertising for them, and it's the kind of post a
  platform account is likely to reshare.
- **Be constructively honest about rough edges.** A specific, calm note about something clunky
  (an API quirk, a doc gap) reads as genuine hands-on usage, not a complaint — and product teams
  generally read hackathon feedback closely. Frame it as "here's what we found and how we handled
  it," never as a takedown.
- **Don't chase returns.** Alpaca is brokerage-adjacent and regulated; a post that leads with "we
  made X% this week" reads as investment hype, which is exactly the tone a company like this will
  not want attached to their brand, and a one-week return is statistically close to meaningless
  anyway (see the throughline above). Lead with decision quality and calibration, not P&L.
- **Community signal matters.** Engage with other teams' posts, not just self-promotion — this is
  a hackathon Alpaca is trying to build a developer community around, and visible community
  behavior is part of what gets a project noticed.
- **Tag deliberately.** Official Alpaca account: **@AlpacaHQ**. lablab.ai's account:
  **@lablabai**. Check the hackathon's own submission page for a required campaign hashtag before
  the first post — don't guess one; use whatever they've actually specified.

## Format & voice for a diary entry

A good entry has four beats, and doesn't need to be long:

1. **What happened** — plain, specific, dated.
2. **Why it mattered** — one sentence tying it to the throughline.
3. **The artifact** — the actual number, quote, or screenshot. This is non-negotiable; a diary
   entry with no artifact is just an adjective.
4. **What's next** — optional, one line, keeps the thread feeling like a diary rather than an
   isolated post.

Voice: first person plural, past tense for what happened, no hype adjectives ("game-changing",
"revolutionary") — let the specific number do the work. Most entries are 3-6 sentences. Let a few
run longer as threads only when the day's finding is genuinely meaty.

## Safety, still non-negotiable

- Never post real account numbers, API keys, or credentials — check every screenshot before it
  goes out.
- Caveat paper trading in the first post of any thread: "$100k simulated, Alpaca paper account,
  zero real money."
- Don't post exact position sizes or return figures framed as a track record until there's
  actually enough resolved trades for the number to mean something — otherwise it's the same
  one-week-noise problem the whole project exists to avoid.

## Draft entries — real material, ready to adapt

These are drawn directly from the actual build log (`specs/log.md`) and README, in the order it
happened. Some are from the design week before the hackathon's official start (Aug 28) — post
those as a "here's what we did before day one" retrospective thread, or trickle them out as
flashback entries once the hackathon window opens. Fill in the artifact/quote from the real
journal once it exists for anything marked *(live, once it happens)*.

---

**Day -2 (Aug 26) — the measurement that set the direction**

Before writing any trading logic, we asked how much a one-week paper-trading result actually
proves. Answer: not much. A genuinely skilled agent with a 60% edge only beats a coin flip 69% of
the time over 20 trades. A zero-skill agent can land anywhere from -7.8% to +8.2% purely by luck
in a week. So we're not scoring ourselves on P&L — more on that as the build continues.

---

**Day -2 (Aug 26) — we threw away the first architecture**

Spent the morning on a guardrail-heavy design, then scrapped it for something simpler: a headless
pipeline with an inbox, no guardrails layer, and the agent's own stated exit rules doing the job
instead. Simpler won. More on why "no guardrails" was a deliberate choice, not a shortcut, coming
up.

---

**Day -2 (Aug 26) — we simulated the failure before writing the trading code**

Ran the architecture through 6 scenarios, step by step, before a single line of trading logic
existed. Found 14 gaps. 3 were critical — including one where nothing in the design would resolve
inside the 8-day competition window, so the whole learning loop would run for a week and produce
zero usable output while looking completely healthy. Fixed before it ever mattered.

---

**Day -1 (Aug 26) — first real multi-leg order cleared**

A real multi-leg options order filled mid-session. The pipeline reconciled it against the broker,
recorded the thesis behind it, and correctly tagged it as machine-confirmed. First full trip
through the whole chain, verified by checking the actual journal and position record — not
assumed. *(Add screenshot of the Alpaca position + our journal entry side by side — this is a
strong one for showing Alpaca's tools working end to end.)*

---

**Day -1 (Aug 26) — the bug that would have silently destroyed 90% of our data**

Our news sensor reported "20 new of 20 fetched." Only 2 files existed on disk. Every ID was
derived from a timestamp hash at one-second resolution — any batch written inside the same second
collided into a single ID, and 18 of 20 real articles were silently overwritten. No error, no
warning. Found it by checking the actual file count against the log line, not by reading the
code. Fixed with proper unique IDs; verified 20/20 persist now.

---

**Day -1 (Aug 26) — what we said no to, and why**

Reviewed six extra data sources for the agent. Adopted one (Polymarket — free, no auth, and its
macro odds are exactly what our index-level thesis needs). Rejected a genuinely useful one because
it needed four OAuth secrets, cost real credits mid-run, and would need a separate server staying
alive for 8 unattended days. Sometimes the right call is the boring one.

---

**Day -1 (Aug 26) — confidence now has to be earned**

Wired up calibration tracking. The agent can say it's 70% confident in a trade — with no track
record, that 70% buys zero contracts. Once it has a real 30-sample calibration record, the same
stated 70% buys 16. That's the actual self-improving loop: better calibration isn't a number on a
dashboard, it's permission to size up.

---

**Day -1 (Aug 26) — two bugs testing caught that reading the code didn't**

Our payoff maths said a long straddle had a finite max profit. It doesn't — that leg is unbounded
by construction, and a bug had silently overwritten the correct answer. Separately, calendar
spreads were computing silently wrong because our option model was missing an expiry field. Both
found by testing real cases, not code review. Both fixed and independently re-verified against
known math (a fair option should have exactly zero expected value — it does now).

---

**Day 0/1 (Aug 27) — we almost fooled ourselves with our own backtest**

Built a Monte Carlo simulator seeded from real historical returns. First version looked great —
too great. Turned out raw resampling was inheriting 16 percentage points of pure directional luck
from whichever historical window it happened to sample. Demeaned the returns before resampling;
it now converges to the actual answer within 1.6pp. The fix that made our numbers *less*
impressive was the correct one.

---

**Day 1 (Aug 27) — the system found its own bug by disagreeing with itself**

Ran the daily research funnel for the first time: it wrote up a market view, generated two
concrete trade ideas, then rejected both — one on the payoff math not clearing costs, one because
the live price didn't match its own stored stats. That second one led us to a real bug: our stats
were six weeks stale from a sort-order issue. The system caught its own bug on its first real run,
without being told to look for one.

---

**Day 1 (Aug 27) — we decided the agent doesn't get to rewrite its own principles**

Talked through whether the agent's memory should be able to evolve its own guiding principles
automatically. Decided no — not because it isn't technically possible, but because the evidence
(including from our own prior research) is that automatic self-amendment doesn't actually beat a
fixed baseline. If the agent's principles change, a human signs off. Worth stating plainly: not
every kind of self-improvement is one you want unsupervised.

---

**Day (live, once it happens) — the trade the agent turned down**

*(This already exists in the README from a live run — post it verbatim once dated, or wait for a
fresh one during the hackathon window and quote it live.)*

> "Both negative after costs, so I stopped before size_position. The call credit spread is exactly
> the trap: collect $51 to risk $449 needs ~90% accuracy to break even [...] Call-side IV is 7.4%
> vs put-side 16.5% — selling upside calls here means selling the cheap wing of a heavily skewed
> surface into an earnings print."

This is the single strongest post in the whole diary. Most trading-bot demos only ever show wins.
A well-reasoned no is the moment that makes people stop scrolling — collect every real instance of
this during the week and post them as they happen.

---

**Day (live, once it happens) — first resolved position, first real attribution verdict**

Once a position closes and its thesis horizon arrives, post the verdict from the 2x2 grid: did the
view hold, did the structure hold, and — the important case — if it made money despite a wrong
view, say so plainly and note that the system is built to learn nothing from that trade. That
admission is more convincing than any win would be.

---

**Day (live, before submission) — calibration scoreboard**

Once enough trades have resolved, post the actual Brier score and Murphy decomposition, not just
a claim of being "well-calibrated." Whatever the number is, post it — the point of building this
was to have an honest number to look at, so showing an unflattering one is still a win for the
premise.

---

**Day (final, ~Sept 4) — honest limitations, before anyone asks**

Close the diary with what we deliberately chose not to build: calendar and diagonal spreads are
refused rather than approximated wrong; there's no guardrail layer by choice, with the agent's own
exit rules doing that job instead; the probability model is lognormal-at-current-IV and real
returns have fatter tails than that. Stating limitations plainly, unprompted, is what makes
everything earlier in the diary credible.
