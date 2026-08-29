---
sources:
- id: src-1
  resource: specs/notes/018_calibration_harmony.md
  author: trdrbot/review
  last_modified: '2026-08-29T12:59:42.230244+00:00'
- id: src-2
  resource: specs/issues.md#I-27
  author: trdrbot/review
  last_modified: '2026-08-29T12:59:42.230409+00:00'
type: Technique
generated:
  at: '2026-08-29T12:59:42.230435+00:00'
---

# Rule
At a high success rate, information is asymmetric: failures teach at many times the rate of
successes. Weight the rare side accordingly - one loss at a 90% win rate deserves roughly nine
wins' worth of attention, and "no problem observed" must be discounted by how few chances a
problem has had to show itself.

# When it applies
Judging any high-win-rate strategy (short premium above all); judging whether a change improved
anything; reading a clean track record; interpreting "no difference detected" from any
comparison or test.

# What it means
Two consequences, one for trades and one for self-improvement. For trades: a short-premium book
hands you nine confirmations per disconfirmation, so absence of loss is weak evidence of absence
of risk - the book looks safest precisely when the least information has arrived, which is the
classic mechanism of being carried out. For self-improvement: at a high base rate, evidence that
a change HARMS accumulates fast while evidence that it HELPS accumulates slowly, so degradation
should be acted on quickly and "not proven better" should never be read as "not better".

# Evidence
Measured on this system's own A/B machinery, 9 paired trials at an ~89% base success rate: a
degrading variant had ~89 percentage points of room to reveal itself and an improving one ~11,
so the arms sat statistically indistinguishable (posterior 0.38 after 45 candidates per side)
despite real differences plausibly existing. The same arithmetic governs a credit spread
collecting $51 against $449 of risk: it needs ~90% accuracy to break even, and its failures
arrive too rarely to teach you before one of them is expensive.
