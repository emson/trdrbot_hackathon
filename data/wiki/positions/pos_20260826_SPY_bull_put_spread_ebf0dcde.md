---
position_id: pos_20260826_SPY_bull_put_spread_ebf0dcde
status: opening
strategy: bull_put_spread
underlying: SPY
opened: '2026-08-26T18:59:03.685962+00:00'
expiry: '2026-09-02'
legs:
- symbol: SPY260902P00755000
  side: sell
  qty: 5
- symbol: SPY260902P00750000
  side: buy
  qty: 5
exit_rules:
- type: stop_loss
  basis: position_mark
  threshold: -100.0%
- type: profit_target
  basis: position_mark
  threshold: 50.0%
- type: time_stop
  days_before_expiry: 1
exit_state: {}
close_reason: null
decision_ref: jrn_20260826T185819Z_dece972
provenance: agent
---

## Thesis

SPY ~766.5, near highs with low IV (12-15%) and a quiet, mildly upward two-day drift. Short 755 put is ~1.5% OTM (~20 delta) with 7 DTE, so theta plus the OTM buffer carries the trade. Thesis is invalidated if SPY breaks below ~755 (short strike) before 2026-09-02.
