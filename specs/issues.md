# Known issues - the living bug ledger (D-060)

Every open defect, deliberate deferral, or known limitation, in one place. The rule:
**a bug found is recorded here the moment it is found, and removed only by a commit that
fixes it (link the D-number).** Health (`trdrbot health`) detects; this ledger remembers.
Sorted by severity.

## Open

- ~~**I-30 · `beta` aligns close series by array position with no dates - VERIFIED wrong live**~~ **FIXED 2026-08-29 (D-091).** beta now stores per-bar dates and aligns on the date intersection; a series without dates degrades to the reported ASSUMED_BETA rather than a positional estimate, and self-heals on the next research pass. Verified by reverting the fix and watching the regression test fail.
- ~~**I-31 · langgraph 1.x re-raises runtime tool errors - the decide cycle dies on a transport
  blip**~~ **FIXED 2026-08-29 (D-091).** decide_tool_node binds tools with handle_tool_errors=True, restoring the contract the whole decide path assumes (guards return refusal STRINGS, the compactor fails open). Verified by reverting the fix and watching the regression test fail.
- ~~**I-32 · Closed positions are credited twice, and the first credit follows the money**~~ **FIXED 2026-08-29 (D-091).** block credit is deferred to attribution at the thesis horizon; the mind's own prediction still resolves at close, where P&L is the honest answer to it. Verified by reverting the fix and watching the regression test fail.
- ~~**I-33 · The capital-protection fast path is killable by one bad input**~~ **FIXED 2026-08-29 (D-091).** learn is advisory at all three call sites (learn.guarded + a learn_run heartbeat); _pct/_normalise return None on anything unparseable; evaluate is isolated per position; by_symbol skips symbol-less rows. Verified by reverting the fix and watching the regression test fail.
- ~~**I-34 · `trdrbot run` never takes the tick lock, and the watchdog is config-only**~~ **FIXED 2026-08-29 (D-091).** the run loop takes tick_lock and the weaker pid-file lock is deleted; the watchdog bounds the decide call and, x4, the whole tick. Verified by reverting the fix and watching the regression test fail.
- ~~**I-35 · `book_greeks` prices every leg at leg[0]'s expiry - a calendar renders as zero
  risk**~~ **FIXED 2026-08-29 (D-091).** book_greeks calls require_single_expiry and counts a calendar into positions_skipped; the guard also refuses a partially-dated leg set instead of assuming shared. Verified by reverting the fix and watching the regression test fail.
- ~~**I-36 · The two most critical readers are the least guarded, and most writers are
  non-atomic**~~ **FIXED 2026-08-29 (D-091).** journal.read and CalibrationStore skip-and-count bad lines; both loaders ignore unknown keys so drift cannot be deleted by the next rewrite; store.write_atomic is used by every state writer. Verified by reverting the fix and watching the regression test fail.
- ~~**I-37 · Opportunity items never dedup - the inbox floods**~~ **FIXED 2026-08-29 (D-091).** opportunity ids are content-derived per source per day, and Inbox.write returns the existing item rather than adding a duplicate. Verified by reverting the fix and watching the regression test fail.
- **I-29 · The bootstrap base rate is overconfident by 15-18pp where credit spreads live**
  ([notes/017](notes/017_learning_from_historic_data.md)). Measured offline over **21,280
  historical band-forecasts** (56 tickers, horizons 3/5/10, 5 band shapes, history sliced before
  every estimate so lookahead is structurally impossible). In the 0.7-0.9 predicted band the
  bootstrap says 0.753 and reality delivers 0.572; it says 0.851 and reality delivers 0.700. The
  gap grows with horizon (3d +0.020, 5d +0.033, 10d +0.041) and is shape-dependent: symmetric
  bands are overstated ~12pp while BOTH one-sided bands are understated, so the modelled
  distribution is too narrow at both tails. **This is not decoration** - `claimed_edge = stated -
  base`, so an overstated base understates the agent's edge on every high-base-rate band (a
  measured contributor to D-076's stacked conservatism), `BASE_PROB_CEIL = 0.90` rejects "vacuous"
  bands using an optimistic number, and range structures are flattered by ~12pp, which is the
  classic way to be carried out selling premium. **Two candidate fixes tested and REJECTED, both
  recorded so nobody re-tries them blind:** a block bootstrap preserving volatility clustering
  made it worse (Brier 0.2223 -> 0.2273 - at a 3-7 draw horizon a 5-day block collapses path
  diversity), and feeding trailing realized drift narrows the gaps but worsens Brier (0.2225 ->
  0.2255) because trailing drift is noisy. **Root cause NOT established; recorded without one.**
  `bootstrap_factors`' own docstring already declared the limitation ("IID resampling destroys
  autocorrelation and volatility clustering... still not truth") - the contribution here is the
  magnitude. **PARTIALLY ADDRESSED (D-089):** a fitted variance-inflation correction
  (k=1.30/1.30/1.25 at 3/5/10d) is live at the muse's base rate, holdout-validated on both a
  time split and a ticker split, with `base_inflate` recorded on every verdict for the forward
  audit. **Still open:** (a) root cause - the correction is empirical, not explanatory; (b) the
  EV grids/tail_gap/sizing deliberately still run raw pending the forward audit; (c) **the
  forward audit itself** - when the pending muse resolutions land (08-31+), score calibrated
  base vs raw base as predictors; that result decides whether the correction extends to the
  pricing grid or gets revisited.
- **I-27 · The Coach's gate reward is ASYMMETRIC, measured over 9 real paired runs** (D-088).
  Opened as "the reward may have a ceiling" after one 5/5-vs-5/5 trial; now measured properly and
  the answer is more useful than the worry. Over 9 live paired runs the incumbent scored **40/45
  (88.9%)** and the challenger **39/45 (86.7%)**, posterior 0.379 - so survival is NOT pinned at
  100% and the reward does discriminate (run 6 was the first to separate the arms, and the gap
  held through run 9). But the headroom is one-sided: with a ~89% base rate a **degrading**
  variant has ~89 points to fall through and an **improving** one has ~11 to climb, so the reward
  detects harm far faster than benefit. That is a defensible bias for an autonomous loop - it fails safe, and the incumbent
  keeps its place on a tie - but it means "no promotion" must never be read as "no better variant
  exists". **Not fixed, and deliberately:** the trigger stated when this was opened (survival at
  or near 100%) is NOT met, so the gate reward stays as the primary - it is the one that cannot be
  gamed. **Action due if promotions stay absent past ~20 trials:** add a secondary reward with
  more headroom (candidates per run, |claimed_edge| among survivors, or emission rate) ALONGSIDE
  the gate reward, never replacing it.
- **I-28 · The Coach's outcome audit is designed but unbuilt** (D-088, notes/016 phase 3).
  Promotion currently rests on the proximate reward alone (surviving the gauntlet); nothing yet
  checks a promoted variant against what its theses actually DID at horizon, or re-matches it
  against the previous incumbent when they degrade. Blocked on resolutions, which do not exist
  yet - `Entry.variant` is stamped from D-088 onward specifically so the join is possible when
  they land. **Action due:** build the audit once a promoted variant has ~10 resolved entries.
- **I-25 · Grok-4.6 on OpenCode Zen was down at time of testing, now demoted** (D-084, D-085).
  Confirmed live: Zen's own `/v1/models` lists `grok-4.6` correctly and the same key serves
  `glm-5.2`, but grok-4.6 itself returned HTTP 500 (reproduced 3x) and grok-4.5 (same family)
  returned 503. No longer the primary or in the active chain - superseded by gpt-5.6-sol, which
  works (D-085). Kept in pricing for reference. **Action due, low priority:** re-run
  `uv run pytest -m contract -k grok` if OpenCode Zen is ever reconsidered.
- **I-26 · gpt-5.6-sol pricing is promotional and time-boxed** (D-085). $4.00/$20.00 per M tokens
  is confirmed from OpenAI's own docs page directly (the first of three models today with a real
  primary source), but OpenAI states this rate is promotional through at least 2026-11-21.
  **Action due:** re-check `developers.openai.com/api/docs/models/gpt-5.6-sol` after that date.

- ~~**I-23 · GLM-5.2/OpenCode Zen tool-calling is unverified**~~ **SUPERSEDED 2026-08-28
  (D-084).** With a real key, GLM-5.2 proved reliable for simple prompts but exhausted its ENTIRE
  8000-token completion budget on invisible reasoning for the muse's actual prompt -
  finish_reason="length", zero visible characters, reproduced deterministically. Demoted out of
  the active chain before its tool-calling belief was ever tested - the question I-23 asked is
  moot for now, not answered.
- ~~**I-24 · Third-party-sourced pricing**~~ **PARTIALLY RESOLVED 2026-08-28 (D-085).**
  gpt-5.6-sol's figure now comes from OpenAI's own docs page directly. GLM-5.2 ($1.40/$4.40) and
  Grok-4.6 ($2.00/$6.00) remain third-party-sourced, both now demoted from the active chain -
  carried for reference only.

- **I-1 · NVDA thesis block carries `self/goal`/`self/style` tags** (found D-059).
  Deliberately deferred: content is live until the 2026-09-03 horizon, never suffered score
  pollution, and the SELF frame currently drops nothing - zero present cost. **Action due:**
  retire-and-replace after 2026-09-03 resolution, same procedure as the SPY block.
- **I-2 · SPY mind carries a residual false miss in its Beta posterior** (D-059). The
  correction was appended (0.43 -> 0.45) but the API cannot delete the wrong signal. Cost:
  the mind's confidence recovers only with further genuine hits. Watch, no action possible.
- **I-3 · `betas_for` assumes beta 1.0 for names with no stored closes** (D-055). Reported
  in the render, but an assumed 1.0 on a genuinely high-beta name UNDERSTATES book exposure.
  Mitigation available: fetch closes at position open for any name entering the book.
- ~~**I-4 · `record_forecast` unused**~~ **RESOLVED 2026-08-28** - the agent used it
  unprompted on its first decide cycle after the D-052 prompt change, recording a 0.67 SPY
  forecast, and CAUGHT A BUG doing so (see D-062: the ledger showed 50%).
- ~~**I-8 · One decide cycle costs ~$0.83**~~ **ADDRESSED 2026-08-28 (D-074).** The figure had
  drifted to **$3.46** on Opus. Three levers pulled - option-chain compaction (which had never
  once executed), one MCP session per tick instead of a subprocess per tool call, and prompt
  caching (absent entirely) - took adjacent measured cycles to **$1.32**, a 62% cut, with better
  output and wall clock down from 5:19 to 1:56. Still worth watching: input is ~80% of the bill and
  scales with agent turns.
- **I-5 · `history()` in elfmem raises TypeError** (upstream; found D-059 investigation:
  `'<' not supported between str and int`). Blocks per-block audit trails. Reported upstream? NO -
  add to next elfmem report. **Re-verified unchanged against elfmem 0.20.0** (D-075).
- **I-9 · The exit-rule engine is ARMED on live data but has never fired** (D-071 -> D-082).
  Progressed 2026-08-28: a SPY 766/758 bear put spread is open, `status: open`, with five rules
  evaluating every tick and a populated debounce history - the first time the deterministic
  capital-protection path has run against a real position. Nothing has breached, which is the
  engine working rather than missing. D-082 fixed the health probe that could not tell those apart
  (it read `exit` trigger rows as evidence the engine had RUN, so it reported "never ran" while the
  engine was evaluating). **Still unverified:** an actual trigger, and the D-074 reachability
  warning, which this position did not need - its -65% stop and +140% target are both reachable
  against the net-cost base.
- **I-10 · Interim scoring is fixed but unfired** (D-074). It needs an open position moving 25% of
  its net entry cost and there is no open position. The `interim_run` heartbeat now distinguishes
  "idle" from "stalled", which is the part verifiable today.
- ~~**I-11 · The muse dates every forecast at the far horizon**~~ **FIXED 2026-08-28 (D-077).**
  All three thesis sources now derive their horizon window from one place
  (`competence.forecast_window`), and the muse gained the deadline check it never had. Before:
  five forecasts, all on 2026-09-03. After: 2026-08-30, 08-31, 08-31, 09-02, 09-03.
- **I-12 · ESTABLISH is barely a promotion.** With D-074's exploration floor in place, the tier's
  Kelly ceiling (0.10, ramping from 0.05) leaves size at the 2.2% exploration allocation for
  essentially every payoff tested. The real step-ups are SCALE and MATURE, both gated on
  attribution, which has never run. Coherent, but the first rung currently changes nothing but the
  book cap.
- ~~**I-21 · Nothing computes effective sample size**~~ **FIXED 2026-08-28 (D-081).**
  `Forecast.subject` carries the underlying; `Calibration.n_eff` (inverse-Herfindahl) and
  `sample_note()` reach `verdict()`, `trdrbot calibration` and the decide prompt. Reported, never
  gated - a test asserts `n_eff` appears in neither `sizing` nor `competence`, because calibration
  and portfolio correlation are different questions. The measurement that motivated it: 38 theses
  are 4.2 effective bets, the 9 positive-Kelly ones are 2.0, and naive per-bet Kelly across them
  overbets by 4.6x.
- ~~**I-22 · The muse places bands at prices that do not exist**~~ **FIXED 2026-08-28 (D-081).**
  It was asked for "PRICES IN DOLLARS" with no spot anywhere in its prompt, so it answered from
  training data (NVDA [650,920] against 218.97). The schema now takes `band_low_pct`/`band_high_pct`
  and `_bands_from_pct` converts against live closes - a central price service could NOT have fixed
  this, since the muse names arbitrary underlyings and nobody knows which spots to supply until it
  has replied. Measured same-day: 13 of 15 candidates rejected -> 1 of 5, bands landing -2.1% and
  +3.8% from spot.
- ~~**I-20 · 24 legacy dossiers carry no lifecycle stamp**~~ **FIXED 2026-08-29 (D-092).** `is_stale` falls back to `generated.at + perishable_after_hours` when no `stale_after` is stamped, so the pre-lifecycle dossiers age out and reach `sweep()` instead of being permanently un-tombstoneable and permanently eligible as muse collision material. The muse's sampler also skips `status: deprecated` pages now, which the raw rglob it used could not see.
- **I-18 · D-073's credit weighting has gone nearly inert** (found D-077 by its own contract
  test failing). `credit_weight` was built on elfmem min-max normalising each recall - worst match
  exactly 0.0, best exactly 1.0 - giving a documented 4x credit differential. Measured against the
  live database now that the block pool has grown: a recall returns a filtered top SLICE, so
  similarities cluster (0.926-1.000 on a real query) and **the differential is ~1.05x, not 4x.**
  Deliberately NOT "fixed" by renormalising: a block returned at 0.93 genuinely is relevant, and
  forcing a 4x split across near-identical scores would invent discrimination the data does not
  contain. The irrelevant-block case it was built for (a SPY mind model at 0.0 against an NVDA
  query) no longer comes back at all. The floor stays mandatory - elfmem still rejects weight <= 0.
  **Watch:** if elfmem's retrieval changes again, the contract test is what will say so.
- **I-19 · The muse runs close to its output ceiling.** A live run produced a 6,745-char reply that
  parsed to nothing - one LLM call spent for zero candidates. gpt-5's reasoning tokens share the
  8,000-token completion budget with its output, and the muse asks for five candidates each
  carrying a causal chain and structure list. D-077 made `_parse_json_block` salvage complete
  elements from a truncated array, so a cut-off reply now yields four candidates instead of none -
  but the truncation itself is unaddressed. **Options:** a per-role max_tokens, or fewer candidates
  per run at the cost of the diversity that is the muse's whole point.
- **I-14 · The stated vol forecast is not scored** (D-076). The agent now states a realized-vol
  forecast and compares it to each structure's breakeven vol ("I forecast 8.5%, the condors needed
  sub-7.5%") - but nothing resolves that claim against realized vol at the horizon, so it moves no
  calibration and earns no size, which is most of the point of making it explicit. Resolution needs
  `market_stats._rolling_vol` over stored closes (no network, no LLM) plus one `metric` field on a
  ledger Entry. **Highest-value next step.**
- **I-15 · Entry commitments do not survive the cycle** (D-076). The agent committed at 07:15 to
  "775/785 at <= ~$2.10 -> act"; it traded at $1.62 six hours later with spot unchanged, and no
  cycle re-checked it. Every cycle is a cold start that states fresh act-conditions and discards
  the previous one's. The system has a mechanism for commitments about POSITIONS (exit rules) and
  none for commitments about ENTRIES. Proposed shape: expiring, wake-only triggers on the existing
  exit-rule signal registry - they schedule a decide cycle, never place an order.
- **I-16 · Declines are never scored** (D-076). 18 theses simulated, 0 traded, and no record of
  what any decline would have made. A decline that was right about vol and one that was right about
  direction are indistinguishable, and `friction-is-the-size-of-the-edge` was asserting "and I was
  right to" off no measurement at all (amended). Proposed: journal the declined STRUCTURE with its
  legs, resolve at its horizon like a traded one.
- **I-17 · The constitution is full** (D-076). 427 of a 430-token ceiling, live SELF frame ~580 of
  elfmem's 600. The next principle requires RETIRING one; raising the ceiling past the frame's own
  budget buys a silent drop, not room (the D-041 failure mode).
- ~~**I-13 · Kelly uses `max_profit / max_loss` against `p = P(profitable)`**~~
  **FIXED 2026-08-28 (D-077).** Measured: the mismatch was directional, not conservative - credit
  structures understated 11-35%, debit structures overstated 43%, so the formula quietly preferred
  buying premium to selling it. `optmath.payoff_ratio` supplies the conditional E[win]/E[loss] and
  sizing matches it to the traded structure scale-invariantly on R:R, falling back to max/max with
  the fallback STATED rather than applied silently.
- ~~**I-7 · elfmem's SELF template header hardcodes "You are elf"**~~ **FIXED UPSTREAM (D-068)** -
  D-061 patched it at our boundary; `elfmem_index` @ cebc242e fixed the actual gap
  (`project.agent_name` now threads through `frame()` itself), verified directly against the
  installed package. Boundary patch retired, `build()` now sets `project.agent_name` at
  construction instead of rewriting the rendered text after the fact.
- **I-6 · Weekend/holiday calendar is weekday-based only** (D-051 vol clock, D-060 research
  gate). US market holidays (Labor Day 2026-09-07 is INSIDE the competition window... after
  deadline, irrelevant this run, real for continued operation) count as full trading days.

## Deliberate limitations (not bugs, recorded so nobody "fixes" them)

- Attribution waits for the thesis horizon; a stopped-early position is recorded, not judged.
- The first SPY position can never be attributed (no thesis recorded at entry, D-039).
  Fabricating one retroactively would be worse.
- `reinforcement_count` is retrieval frequency, not trust - relevance ranking uses it by
  design in elfmem; our defence is correct tagging + retiring stale blocks (D-059).
- SPY/NVDA `last_pnl_pct` values are cumulative-equity estimates, not fill records.

## Resolved (most recent first - keep the last ~10 for pattern-reading)

- ~~legacy dossiers never aged out, so the sweep could not reach them~~ (D-092)

- ~~beta aligned two close series by array position; QQQ read +0.10 (R2 .004) vs +1.48~~ (D-091)
- ~~langgraph 1.x re-raised tool errors, so an MCP blip burned every item's retry budget~~ (D-091)
- ~~closed positions credited twice, the first credit following the money not the verdict~~ (D-091)
- ~~one malformed exit-rule threshold became a live stop at breakeven~~ (D-091)
- ~~`trdrbot run` never took the tick lock; the watchdog was configured and read by nothing~~ (D-091)
- ~~a calendar spread priced as riskless - delta, theta and vega all exactly zero~~ (D-091)
- ~~one truncated line in forecasts.jsonl killed every tick, permanently~~ (D-091)
- ~~the Ledger DELETED drift-incompatible rows on the next rewrite~~ (D-091)
- ~~opportunities could never dedup; the inbox held XLE six times in one batch~~ (D-091)
- ~~four clocks: UTC horizons read in local time, DTE off by one every evening~~ (D-091)

- ~~Every mark-based exit rule was unreachable (P&L% of gross, not net premium)~~ (D-074)
- ~~Interim scoring dead since the bands landed - percent constants, fraction input~~ (D-074)
- ~~Option-chain compaction never executed - wrong result envelope, failed open silently~~ (D-074)
- ~~Murphy reliability read the bin centre, not the stated probability~~ (D-074)
- ~~The size ladder inverted at EXPLORE->ESTABLISH and again at MIN_SAMPLE~~ (D-074)
- ~~`ev_after_costs` computed at the market's drift, so no thesis could move it~~ (D-074)
- ~~Two clocks in optmath; the weekend one double-counted an adjustment the IV carries~~ (D-074)
- ~~Bootstrap resampled calendar days as sessions - 1.45x variance~~ (D-074)
- ~~`_market_pulse` defined, tested, never called, with duplicate thresholds~~ (D-074)
- ~~Health probes read their own output as evidence they had run~~ (D-074)
- ~~Attribution scored close-reason label, not measured profit~~ (D-056)
- ~~Credit assignment skipped on every external close~~ (D-057)
- ~~`outcome()` on unconsolidated blocks silently lost~~ (D-057)
- ~~Calibration never resolved when reconcile had no P&L~~ (D-058)
- ~~Stale SPY block dominating recall; mind false miss~~ (D-059)
- ~~Thesis blocks auto-tagged into the SELF frame~~ (D-059 root fix)
