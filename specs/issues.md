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
- **I-4 · The agent has not yet used `record_forecast` unprompted** (D-052). Ledger n=1.
  The prompt instructs it; no decide cycle has exercised it since. Watch the next few
  declines - if still unused by 2026-08-29, strengthen the prompt or auto-extract forecasts
  from declines.
- **I-5 · `history()` in elfmem raises TypeError** (upstream; found D-059 investigation:
  `'<' not supported between str and int`). Blocks per-block audit trails. Reported upstream? NO -
  add to next elfmem report.
- **I-7 · elfmem's SELF template header hardcodes "You are elf"** (found D-060 while
  seeding the identity name). Our identity block says Theo; the frame header still says
  elf. Cosmetic-but-confusing; add to the next upstream report.
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

- ~~Attribution scored close-reason label, not measured profit~~ (D-056)
- ~~Credit assignment skipped on every external close~~ (D-057)
- ~~`outcome()` on unconsolidated blocks silently lost~~ (D-057)
- ~~Calibration never resolved when reconcile had no P&L~~ (D-058)
- ~~Stale SPY block dominating recall; mind false miss~~ (D-059)
- ~~Thesis blocks auto-tagged into the SELF frame~~ (D-059 root fix)
