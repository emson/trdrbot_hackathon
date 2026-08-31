# Known issues - the living bug ledger (D-060)

Every open defect, deliberate deferral, or known limitation, in one place. The rule:
**a bug found is recorded here the moment it is found, and removed only by a commit that
fixes it (link the D-number).** Health (`trdrbot health`) detects; this ledger remembers.
Sorted by severity.

## Open

- ~~**I-56 · A calendar exit rule fires off-hours and submits a close into a shut market**~~ **FIXED 2026-08-31 (D-096).** `deadline`, `days_to_expiry` and `leg_divergence` read a date or a stored counter, so they fire on the 00:15 tick of expiry day exactly as at noon; the close was submitted regardless. Detection is now unaffected by the clock and only the broker-mutating call waits for the session - debounce state is already persisted, so the same reason re-fires at the open with nothing lost. Verified by reverting the fix and watching two regression tests fail.
- ~~**I-57 · A failed close stranded the position in `closing`, outside every safety net**~~ **FIXED 2026-08-31 (D-096).** `run()` fetched `closing` positions (they are in `ACTIVE`) then skipped them on `status != "open"`, forever. One failed `close_position` call therefore cost a position its stop, its target and any retry in a single move, with reconcile only noticing once the legs were already gone. `closing` is now a second candidate status, retried and never re-evaluated, sharing one close path with the fresh trigger. Verified by reverting the fix and watching five regression tests fail.
- ~~**I-58 · The whole-book-close guard counted only `open`, undercounting live exposure**~~ **FIXED 2026-08-31 (D-096).** D-046's refusal fires above one open position, but the count excluded `opening` (order working) and `closing` (mid-liquidation), so a book of three could read as one. Now counts every `ACTIVE` status except `proposed`. Verified by reverting the fix and watching the regression test fail.
- ~~**I-59 · `max_loss_usd` - what every book cap sums - was never checked against a fill**~~ **FIXED 2026-08-31 (D-096).** The model supplied a per-contract max loss, sizing multiplied it, `record_position` stored it, and nothing ever compared it to what the broker filled - so a position whose real risk exceeded its stated risk silently bought headroom for the NEXT position too. Repriced once at fill confirmation, derived from `cost_basis` alone (the one broker cost field whose units are already load-bearing in production). Verified by reverting the fix and watching the regression test fail.
- ~~**I-60 · A recorded quantity that sizing did not compute was invisible**~~ **FIXED 2026-08-31 (D-096).** `size_position`'s contract count is what `max_loss_usd` is derived from, so recording a different quantity denominates the caps in a size never traded. Reported in the tool's own note and journalled as `sizing_mismatch`, never refused - D-009 leaves the size to the agent, and this holds its own two tool calls against each other rather than gating either. Verified by reverting the fix and watching four regression tests fail.
- ~~**I-61 · An orphan was journalled and then left unmanaged**~~ **FIXED 2026-08-31 (D-096).** A position held at the broker with no page of ours had no exit rules, so nothing evaluated it and the deadline sweep (INV-26) could not see it - it sat unexplained AND unwatched until a human read the journal. This is the tail of I-56/I-57's scenario: an auto-exercised leg arrives as exactly this. Now adopted as a stub with `status="open"`, grouped by `(underlying, expiry)` so a broken spread is closed together (INV-19), with the risk figure and thesis left empty so `health` reports it as needing a human. Implements the FM-9 stub the architecture already specified. Verified by reverting the fix and watching four regression tests fail.
- ~~**I-62 · `simulate_experiments` priced against the raw bootstrap, not the calibrated one**~~ **FIXED 2026-08-31 (D-096).** D-089 fitted the I-29 inflation and wired it into the muse's gates, naming the EV grids as the next site. That call feeds the EV/POP/payoff_ratio the agent picks a structure from, and then sizing's Kelly gate, so an optimistic tail there is an optimistic bet size downstream. One kwarg, mirroring `muse.py`; fails safe to 1.0 until a fit exists. `_vacuity_check` and `discovery.py` still run raw, deliberately - D-089's discipline is apply where measured, validate forward, then extend.
- ~~**I-63 · Three beliefs about Alpaca that this phase rests on were untested**~~ **PARTIALLY ADDRESSED 2026-08-31 (D-096).** The load-bearing one - `cost_basis` is a signed dollar total, pinned by its relationship to `qty x avg_entry_price x 100` - now runs by default in the contract tier. **Still open:** two skipped-by-default tests need a supervised manual run - whether the broker refuses a naked short (i.e. whether sizing is the ONLY guard against unbounded loss), and what a close submitted off-hours does to a position we actually hold. Neither belongs in an automated run inside the competition window.
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
- ~~**I-38 · `implied_vs_realized` inflated every premium reading by 20%**~~ **FIXED 2026-08-29
  (D-093, WU-3.6).** The function adjusted the realized side by sqrt(252/365) before dividing, on
  the reasoning that "implied annualises over 365 calendar days, realized over 252 sessions". It
  does not survive the derivation: a world with per-trading-day variance `sd^2` has annualised
  realized vol `sd*sqrt(252)`, and an option there spanning `n_c` calendar days covers
  `n_t = n_c*252/365` sessions with total variance `n_t*sd^2`, which BS charges as
  `sigma^2 * n_c/365` - so `sigma = sd*sqrt(252)`, the same number. The trading-day count is
  already inside both sides. A market charging exactly fair value therefore read 1.20x, a fifth of
  a premium that was not there, **always in the direction that says sell**. Inert until WU-3.6
  gave the function its first caller, which is how it was found: the number went in front of the
  agent as "the market is charging MORE than the tape has delivered", and that had to be true
  before it could be shown.
- ~~**I-39 · The coach's staleness check counted heartbeats, not chances**~~ **FIXED 2026-08-29
  (D-093, live-caught on restart).** Found within an hour of the Phase 3 run-loop restart:
  `trdrbot health` read "coach ran 24x, produced 4 - but nothing in the last 20 runs" on a
  Saturday, with an experiment left open from Friday. `record_trial` has exactly one call site,
  inside `muse.run`, and the muse structurally cannot run on a day the market never opens - so the
  20 "silent" runs were 20 housekeeping cycles 30 minutes apart, not 20 missed chances. The probe's
  `work` measured `experiments_open` (an ACTIVE lever, which stays 1 through every housekeeping
  pulse regardless) rather than opportunities to see a trial. `pulse()` now records
  `muse_runs_since_pulse` - the same per-heartbeat-delta convention `trials_scored` already uses -
  and `work` sums that instead. A closed weekend of housekeeping noise now reads OK; a muse run
  that genuinely fails to reach `record_trial` still reads BAD, including when housekeeping noise
  sits either side of it.
- ~~**I-40 · The `payoff_ratio=None` fallback abandons friction, and it is the default on any
  structure mismatch**~~ **FIXED 2026-08-30 (WU-4.2).** `_matching_payoff_ratio` returned the ratio
  or None, and None meant four different things - nothing simulated, no unique match, the match's
  own payoff refused after friction, and a direct caller supplying nothing - which `size_position`
  then treated identically by falling back to frictionless max/max. It is now `_match_structure`,
  returning the matched structure or the REFUSAL that replaces it, one named sentence per cause
  (the friction one is D-079's own "there is no payoff to bet on", finally reaching the model).
  Production cannot reach the max/max fallback any more; it survives for direct callers and says
  so. Every sizing outcome, refusals included, is journalled for the `sizing.refused_rate` gauge.
  Verified by reverting local_tools.py and watching all six regression tests fail.
- ~~**I-41 · A short-vol trade can NEVER earn Kelly size - the ladder is inert for half the
  book**~~ **FIXED 2026-08-30 (WU-4.5).** `Thesis` now carries `vol_view`, the annualized realized
  vol the agent forecasts for the horizon, and it is the vol half of the DECISION MEASURE:
  `pop_thesis`, `ev_thesis` and the payoff ratio that sizes the trade are all computed under it,
  while every market-labelled column stays on the market's IV so the gap between them remains the
  claimed edge. D-079's algebra is measure-agnostic, so the gate is now exact for vol theses as it
  already was for drift ones - measured on the scaffold's own sweep, the put credit spread's gate
  opens at 4.0% of vol edge where EV-after-costs turns positive at 4.0% (it was 3 points late),
  and Kelly engages from 7 points with size ramping 1.86% -> 2.61% -> 3.72% instead of pinning at
  the seed allocation forever. `vol_view=None` is byte-identical to the old behaviour, pinned by
  the golden. One emergent property worth knowing (recorded, not fixed): past ~10 points of
  claimed vol edge the losing side of a wide condor holds under 1% of the agent's own
  distribution, `payoff_ratio` refuses, and sizing refuses with it - an extreme view self-refuses
  rather than manufacturing an enormous Kelly from a corner of the grid. Verified by reverting
  experiments.py and watching the wiring tests fail.
- ~~**I-42 · One wide print closes a credit spread immediately - the documented artifact IS the
  decisive case**~~ **FIXED 2026-08-30 (WU-4.6).** `position_mark`'s immediate_overshoot of 1.0
  and its own comment about "-100%-of-credit on a HEALTHY spread" named the same number, so the
  commonest quote artifact on a credit spread skipped the debounce built for it. A mark breach is
  now decisive only when the UNDERLYING corroborates it - an adverse move of at least
  `CORROBORATION_FRACTION` (0.25) of the position's own expected move since entry, using the entry
  spot, IV and greeks D-040 already records. `dominant_risk` decides what "adverse" means: a vol
  bet is hurt by a large move either way, and anything with a directional stake uses the signed
  test, so a favourable move can never confirm a loss claim. Gains stay decisive (booking a win
  early on a wild print costs opportunity, not capital), and an unjudgeable position debounces.
  Measured on the scaffold: the artifact print now holds and confirms on the second check, while
  the same print with the underlying gapped to 96 still closes on the first. A suppressed breach
  closes nothing and would leave no trace, so `evaluate` counts them into the `exit_run`
  heartbeat. Verified by reverting exit_rules.py and watching all five path tests fail.
- ~~**I-43 · EV, POP and the payoff ratio ignore `Leg.iv` - risk and edge are priced off
  different surfaces**~~ **FIXED 2026-08-30 (WU-4.8), and the original finding partly
  CORRECTED.** What was real: `net_greeks` honours each leg's IV while `_lognormal_grid` took one
  flat vol, so a structure was evaluated at a vol nobody quoted for its strikes. Measured on a
  call credit spread whose legs quote 19% and 21% on a 25%-ATM board: EV reads -$6.68 at the ATM
  figure and +$0.05 at the vega-weighted 21.0%. `simulate` now evaluates the market measure at
  `optmath.vega_weighted_iv` and reports the EV span across the legs' own IVs, so the residual is
  stated instead of chosen silently. A smile-consistent distribution is still refused, same reason
  as calendars.
  **What was overstated, recorded rather than quietly dropped:** the original entry claimed the
  flat evaluation "gates the same zero-edge trade 26pp apart purely by which side of the smile it
  sits on", comparing a put credit 95/100 against a call credit 105/110. Those are not mirror
  structures - one is struck at the money and the other 5% out - and the gap is mostly moneyness,
  not skew. Under the fix the two gates move from 71.2%/96.9% to 72.2%/96.0%, which is the
  measurement that killed the claim. There is also no single flat vol that makes a leg-wise-priced
  board zero-EV at all: the legs are priced under mutually inconsistent lognormals, which is what
  a smile IS to a model without one. The narrower defect was real and is fixed; the headline
  number was wrong and is withdrawn.
- ~~**I-44 · `breakeven_vol` caps its search at 120% and reports "EV positive at every realized vol
  tested" above it**~~ **FIXED 2026-08-30 (WU-4.3).** Two halves. The scan now follows the quote -
  `_vol_grid` widens to 1.5x the vol the structure was priced at whenever that exceeds the default
  ceiling, so a put credit spread or condor at IV 150% recovers its breakeven exactly (measured:
  "wins if realized vol < 150.0%", where it previously reported no crossing at all). And a scan
  that genuinely finds nothing now names the range it searched - "(searched to 120%)" - because
  "no crossing" is a claim about the GRID and was being read as a claim about the world, which is
  the confident wrongness the tool exists to refuse. Verified by reverting optmath.py and watching
  both regression tests fail.
- ~~**I-45 · A near-zero-net-cost position's mark rules are permanently blind, and record-time
  checks read it as protected**~~ **FIXED 2026-08-30 (WU-4.4).** `record_position` now warns when
  the traded structure's net cost is under `MIN_NET_COST_SHARE` of the gross premium it traded:
  the mark-based P&L base is refused as division by noise, so every stop and target holds forever,
  and the repair (an underlying stop or a time stop) is named in the same sentence. The constant
  is imported from `analytics`, not copied - one definition, per the defect class this whole phase
  is about. This is `_unreachable_rules`' blind spot by construction: that check bails at
  `base <= 0`, which is exactly the structure needing the warning. Reported, never blocked (D-009).
  Verified by reverting local_tools.py and watching the regression test fail.
- ~~**I-46 · The Coach's cost-ceiling sentinel counts unpriced-model spend as zero**~~ **FIXED
  2026-08-30 (WU-6.1).** `_cost_today` now returns `(priced_usd, unpriced_call_count)` and
  `_sentinel_cost` fires on `spent > limit OR unpriced > 0`, naming both in the value it reports
  so the report says WHY. The `coach.cost_usd_today` GAUGE keeps reporting priced spend only,
  deliberately and now documented: a gauge folding in unpriced calls would mix dollars with an
  unknown, which a chart cannot show - stopping the loop is the sentinel's job, blurring a line
  is not. Verified by reverting gauges.py and watching both tests fail.
- ~~**I-47 · Phase 4's two new journal kinds have no health probe**~~ **FIXED 2026-08-30
  (WU-6.2).** A `sizing` Probe (produced = verdicts, so a window of nothing but refusals reads as
  "ran plenty, produced nothing" - which is what it is), plus two cross-kind state checks a
  single probe cannot express: orders placed since sizing was last consulted (BAD - the Kelly
  gate routed around looks identical to normal trading from every other signal), and an open book
  with no `book_risk` reading in the last STALE_AFTER_RUNS decide cycles (WARN). Both checks are
  SELF-ARMING - inert until their row kind has been seen once - so neither fires on the era
  before the row existed; "this shipped yesterday" is the cheapest false alarm to avoid (D-070).
  Verified by reverting health.py and watching four of the five tests fail (the fifth asserts
  absence and correctly still passes).
- ~~**I-54 · `thesis_vol_view` never reached the position page**~~ **FIXED 2026-08-30 (WU-6.3a,
  found while implementing WU-6.3).** `Position.frontmatter()` is a hand-maintained allowlist and
  `_parse` is its hand-maintained mirror, so a field added to the dataclass is silently NOT
  persisted until someone remembers three places at once. WU-4.5 added `thesis_vol_view` - the
  whole point of which is that a vol thesis stays scoreable and attributable AFTER the cycle that
  formed it - and it never reached the page: set at record time, gone on the next read, invisible
  because every existing test checked the fields it already knew about. Both it and WU-6.3's
  `leg_divergence_count` now round-trip, and the gap is closed as a PROPERTY rather than two more
  examples: `test_every_position_field_survives_a_save_load_round_trip` walks
  `dataclasses.fields(Position)` and fails on any field that does not survive, unless it is on an
  exclusion list carrying a stated reason. Verified by reverting the frontmatter/_parse additions
  and watching the invariant name the exact missing field.
- ~~**I-48 · `leg_divergence` is journalled and nothing corrects the position**~~ **FIXED
  2026-08-30 (WU-6.3).** Reconcile now COUNTS consecutive divergences on `Position.
  leg_divergence_count` (and writes `leg_divergence_cleared` when the full set returns, so a
  transient leaves a trace instead of silently un-counting); the exit registry ACTUATES on that
  count via a `leg_divergence` signal at `LEG_DIVERGENCE_CONFIRM = 2`, implicit on every position
  like the deadline and at the same priority. Reconcile runs immediately before `exit_rules.run`
  in the same tick, so confirmation costs one tick - five minutes on the open cadence - and the
  existing close path does the rest: INV-19 closes ALL remaining legs, which is the point, since
  the remainder of a broken spread can be an undefined-risk naked short. No tools threaded into
  reconcile, no new mechanism: one registry entry plus one `_normalise` clause, the D-037 recipe.
  **Stated limitation:** the `pnl_fraction` learning sees at that close covers the SURVIVING legs
  only - the vanished leg took its P&L with it, the same honest gap as D-056's external closes.
  Assigned stock appearing at the broker remains out of scope here; it surfaces through
  reconcile's existing "at the broker with no story of ours" branch. Verified by reverting
  reconcile.py and exit_rules.py and watching all three fail.
- ~~**I-49 · Two muse accounting gaps: funnel overlap unmeasured, malformed candidates evade the
  trial count**~~ **FIXED 2026-08-30 (WU-6.4).** (a) A malformed reply element now appends a
  verdict (`fate="malformed reply element"`, with the exact keys the journal row and the verbose
  print read - a KeyError there would take the whole run down) instead of a bare `continue`. It
  still does not reach `ledger.register`, which refuses a row with no underlying and no band; the
  invariant it satisfies is "every candidate is COUNTED", which is what the multiple-testing
  correction actually needs. The consequence that matters: `coach.survived` scores it as a
  non-survivor, so **a prompt variant that produces garbage now loses its A/B trials on that
  garbage** rather than being invisible to its own reward. Both arms see the rule identically from
  the same run, so an open experiment's pairing is preserved. (b) `muse.funnel_overlap_rate`
  measures the share of candidates on names research/discovery already cover. Deliberately a
  GAUGE and not a gate: the muse prompt is the Coach's one live lever (editing it from outside
  corrupts an open trial's pairing and re-fingerprints the artefact mid-experiment), and the
  premise is unproven - the muse's mandate is novel THESES, not novel names. A gate must earn its
  existence from this trajectory, the measure-first discipline that held the vega cap (D-094).
  Verified by reverting muse.py and gauges.py and watching both tests fail.
- ~~**I-50 · Post-trade greeks are flat-IV even when the position was built from skewed
  quotes**~~ **FIXED 2026-08-30 (WU-6.5).** `SimStructure` carries the per-leg IVs it was priced
  with, `record_position` writes them onto the recorded legs from the structure the trade MATCHED
  (derived, never re-declared - D-037), and `Leg.from_position_leg` reads `iv_pct` on the same
  terms `parse` already used. `net_greeks` honoured per-leg IV all along; it was simply never
  given one on this path, so the entry greeks and every later book-greeks line described a
  skew-built position as though the board were flat. A flat board still records no `iv_pct` and
  is byte-identical. The structure match is now computed ONCE and reused by both consumers
  (the IVs and the exit-rule reachability warnings) rather than twice. Verified by reverting
  optmath.py and local_tools.py and watching the round-trip test fail.
- ~~**I-51 · The tick lock's write is the one non-atomic state write left**~~ **FIXED
  2026-08-30 (WU-6.6).** Acquisition now READS BACK what it wrote and raises `BlockingIOError`
  if the pid on disk is not ours, collapsing the read-check-write window from the length of a
  whole tick to one filesystem read. Deliberately not flock/O_EXCL: the pid+timestamp file is
  what makes a stale lock breakable and human-readable (D-018 #5), and the residual race after a
  read-back is proportionate to a collision requiring two processes within microseconds. Verified
  by reverting lock.py and watching the race test fail.
- ~~**I-52 · The single-shot tick path crashes raw where the loop degrades**~~ **FIXED
  2026-08-30 (WU-6.7).** `cli._tick` - the path `run.sh` points cron/launchd at - now classifies
  any non-`BlockingIOError` failure through the existing `failures.classify`/`advice` machinery,
  prints one line, and exits 1 so a scheduler sees a real failure signal instead of a traceback.
  No journalling from the handler: the journal write may be the very thing that failed. Verified
  by reverting cli.py and watching the test fail.
- ~~**I-53 · `doctor` cannot see a typo'd role key in `llm.roles`**~~ **FIXED 2026-08-30
  (WU-6.8).** `doctor` now prints the set difference between the config's `llm.roles` keys and
  the code's `ROLES`, warning per unknown key and naming the known ones. Never fatal -
  degradation to the default chain stays the design; invisibility was the defect. Confirmed
  silent against the live config. The `cli.py` module docstring, which enumerated four commands
  while the parser grew to seventeen, now points at `trdrbot --help` so it cannot drift again.
- ~~**I-55 · A dead MCP session made reconcile close every live position**~~ **FIXED 2026-08-30
  (WU-6.9/6.10, found by tracing rather than by reading).** `analytics.snapshot` degrades on a
  failed broker read and leaves `broker_positions == []` - which is indistinguishable from "the
  broker holds nothing", the one conclusion the failure cannot support. Reconcile treated it as
  proof: **every open position was marked `closed`/`external`, scored through learning, and left
  running at the broker with no exit rules watching it**, because a terminal position is never
  evaluated again. An `opening` position was marked `abandoned` the same way. Reproduced end to
  end before the fix (`phantom=['pos_live']`, status `closed`), and contained after.
  The same absence-as-evidence shape as D-038 and I-46 one seam over, so the fix is the same
  shape: `Snapshot.broker_readable` (defaulting FALSE - fail-closed on a capital guard), set only
  where the read actually succeeds, and reconcile draws no absence conclusions without it. The
  failed read now goes through `health.degraded`, which already exists precisely so a fail-open
  path leaves a row rather than a print in an unattended run. Verified by reverting analytics.py
  and reconcile.py and watching both tests fail.
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
- ~~**I-14 · The stated vol forecast is not scored** (D-076). The agent now states a realized-vol
  forecast and compares it to each structure's breakeven vol ("I forecast 8.5%, the condors needed
  sub-7.5%") - but nothing resolves that claim against realized vol at the horizon, so it moves no
  calibration and earns no size, which is most of the point of making it explicit.~~ **CLOSED
  (D-093, WU-3.6).** `Entry.metric` carries `realized_vol_pct`, `record_forecast(metric=
  "realized_vol")` records the claim in the percent the agent states it in, and housekeeping
  resolves it from stored dated closes via `market_stats.realized_vol_between` - no network, no
  LLM, and skipped rather than guessed when the series is absent, stale or too short. It enters
  calibration through `as_forecasts` unchanged, which needed no metric branch: calibration asks
  "when this agent says 70%, does it happen", a question that does not care what the claim was
  about.
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

- Research opportunities carry no options-liquidity check, by structure: the research desk runs
  while the market is CLOSED, so there is no chain to check against. `opportunity.admit` records
  the gap as `unchecked` and journals it; a non-optionable name dies at the decide cycle's live
  quotes, not silently (confirmed 2026-08-30 review - reclassified from finding to limitation).
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
