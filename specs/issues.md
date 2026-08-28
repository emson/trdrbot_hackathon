# Known issues - the living bug ledger (D-060)

Every open defect, deliberate deferral, or known limitation, in one place. The rule:
**a bug found is recorded here the moment it is found, and removed only by a commit that
fixes it (link the D-number).** Health (`trdrbot health`) detects; this ledger remembers.
Sorted by severity.

## Open

- **I-25 · Grok-4.6 on OpenCode Zen is currently down** (D-084). Confirmed live, not assumed:
  Zen's own `/v1/models` lists `grok-4.6` correctly and the same key serves `glm-5.2`
  successfully, but grok-4.6 itself returns HTTP 500 (reproduced 3x) and grok-4.5 (same family)
  returns 503 "Endpoint is unavailable". Left as the declared primary because the fallback chain
  is verified to survive it (`test_the_decide_chain_survives_grok_being_down`, real network,
  confirms `decide` answers via Claude with zero risk) - but every cycle currently pays one
  wasted call. **Action due:** re-run `uv run pytest -m contract -k grok` periodically; once it
  passes, confirm with `trdrbot doctor` and note the outage as cleared. If still down after the
  competition window matters, drop it a rung rather than keep paying the latency.

- ~~**I-23 · GLM-5.2/OpenCode Zen tool-calling is unverified**~~ **SUPERSEDED 2026-08-28
  (D-084).** With a real key, GLM-5.2 proved reliable for simple prompts but exhausted its ENTIRE
  8000-token completion budget on invisible reasoning for the muse's actual prompt -
  finish_reason="length", zero visible characters, reproduced deterministically. Demoted out of
  the active chain in favour of Grok-4.6 before its tool-calling belief was ever tested - the
  question I-23 asked is moot for now, not answered.
- **I-24 · Third-party-sourced pricing, now covering two models** (D-083, D-084). GLM-5.2
  ($1.40/$4.40) and Grok-4.6 ($2.00/$6.00, cache $0.50) both came from pricing trackers and
  aggregators, not Zen's own pricing page directly. Grok's figure is corroborated by two
  independent sources agreeing exactly - stronger than GLM's had - but still not primary.
  Re-verify against the first real invoice before this matters for live spend.

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
- **I-20 · 24 legacy dossiers carry no lifecycle stamp** (D-078). `is_stale()` is False without
  `stale_after`, so they are never swept until re-researched - deliberate, fail-safe migration.
  Their durable sections also still carry the old welded text (22 of 28 read "Company Inc. -
  Strong Q4 results..."), corrected only on the next write of that ticker. No action needed; they
  self-heal as tickers are re-nominated.
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
