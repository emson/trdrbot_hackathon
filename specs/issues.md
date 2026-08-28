# Known issues - the living bug ledger (D-060)

Every open defect, deliberate deferral, or known limitation, in one place. The rule:
**a bug found is recorded here the moment it is found, and removed only by a commit that
fixes it (link the D-number).** Health (`trdrbot health`) detects; this ledger remembers.
Sorted by severity.

## Open

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
- **I-9 · The exit-rule engine has never fired on live data** (D-071, still true at D-074). Both
  positions to date closed externally and the book is currently flat. D-074 fixed the arithmetic
  that made every mark-based rule on those positions *unreachable* and added a reachability
  warning at `record_position` - but the deterministic path that protects capital when the agent
  is not looking, and the warning itself, remain unexercised in production. **Action due:** confirm
  on the first position opened after D-074.
- **I-10 · Interim scoring is fixed but unfired** (D-074). It needs an open position moving 25% of
  its net entry cost and there is no open position. The `interim_run` heartbeat now distinguishes
  "idle" from "stalled", which is the part verifiable today.
- **I-11 · The muse dates every forecast at the far horizon.** All five of its ledger entries
  resolve 2026-09-03, one day before the deadline. D-070 argued for 1-3 day horizons in
  `record_forecast`'s docstring only; `muse.py` allows anything inside 7 days and its output
  clusters at the far end, which is D-070's strategic finding surviving in a second producer.
  **Action due:** a prompt change with its own before/after.
- **I-12 · ESTABLISH is barely a promotion.** With D-074's exploration floor in place, the tier's
  Kelly ceiling (0.10, ramping from 0.05) leaves size at the 2.2% exploration allocation for
  essentially every payoff tested. The real step-ups are SCALE and MATURE, both gated on
  attribution, which has never run. Coherent, but the first rung currently changes nothing but the
  book cap.
- **I-13 · Kelly uses `max_profit / max_loss` against `p = P(profitable)`.** Those are two
  different events for any structure that can finish partially in the money. The same lognormal
  grid that produces `pop_thesis` could produce a conditional `E[win] / E[loss]` instead. Deferred
  at D-074: it changes what `size_position` means, and that pass had already changed the gate.
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
