---
type: Position
position_id: pos_20260826_SPY_bull_put_spread_ebf0dcde
status: closed
interim_band: 0
max_loss_usd: 2210.0
last_pnl_pct: 0.08190045248868778
greeks_at_entry: null
entry_iv: 0.165
entry_spot: 766.5
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
- type: underlying_stop
  direction: below
  level: 757.5
exit_state:
  days_to_deadline:below:0:
  - false
  - false
  - false
  position_mark:below:-1:
  - false
  - false
  - false
  position_mark:above:0.5:
  - false
  - false
  - false
  days_to_expiry:below:1:
  - false
  - false
  - false
  underlying:below:757.5:
  - false
  - false
  - false
close_reason: external
decision_ref: jrn_20260826T185819Z_dece972
sources: []
generated:
  by: ''
  at: '2026-09-02T09:25:04.723939+00:00'
verified:
- by: trdrbot/reconcile
  at: '2026-08-26T20:05:59.099229+00:00'
elfmem_blocks:
  attention:
  - 5c42bcc0efd19526
mind_decision_block_id: 8542b75a79eb0ef7
thesis_claim: ''
thesis_horizon: ''
thesis_band_low: null
thesis_band_high: null
thesis_drift: 0.0
thesis_vol_view: null
leg_divergence_count: 0
attribution: unscoreable
provenance: agent
---

## Thesis

SPY ~766.5, near highs with low IV (12-15%) and a quiet, mildly upward two-day drift. Short 755 put is ~1.5% OTM (~20 delta) with 7 DTE, so theta plus the OTM buffer carries the trade. Thesis is invalidated if SPY breaks below ~755 (short strike) before 2026-09-02.
