---
type: Position
position_id: pos_20260903_AVGO_bull_call_spread_c02306dd
status: abandoned
interim_band: 0
max_loss_usd: 9660.0
last_pnl_pct: null
greeks_at_entry:
  delta_shares: 652.52
  delta_dollars: 229039.35
  gamma_shares: 21.43
  theta_dollars: -489.72
  vega_dollars: 212.92
entry_iv: 0.368
entry_spot: 351.01
strategy: bull_call_spread
underlying: AVGO
opened: '2026-09-03T15:51:39.511238+00:00'
expiry: '2026-09-11'
legs:
- symbol: AVGO260911C00355000
  side: buy
  qty: 21
- symbol: AVGO260911C00375000
  side: sell
  qty: 21
exit_rules:
- type: stop_loss
  basis: position_mark
  threshold: -60.0%
- type: profit_target
  basis: position_mark
  threshold: 75.0%
- type: time_stop
  days_before_expiry: 0
- type: underlying_stop
  direction: below
  level: 342.0
exit_state: {}
close_reason: never_filled
closed_at: '2026-09-03T16:07:15.376217+00:00'
decision_ref: jrn_20260903T155046Z_dec8ba426
sources:
- id: opp_20260903_muse_098f2cfa40c9
  resource: inbox/opp_20260903_muse_098f2cfa40c9
  author: muse
- id: opp_20260903_muse_42a7ddf45c1e
  resource: inbox/opp_20260903_muse_42a7ddf45c1e
  author: muse
generated:
  by: openai:gpt-5.6-sol | anthropic:claude-opus-5 | openai:gpt-5
  at: '2026-09-03T16:07:15.376249+00:00'
verified: []
elfmem_blocks:
  self:
    cf4026ebe4e5f325: 0.0
    78ec8cb80ae8e249: 0.0
    78b0c92502a8cab5: 0.0
    95209bc148c6a7b9: 0.0
    df86248db03497d9: 0.0
    1af203536546c2ef: 0.0
    9d43b52dbc4fff0e: 0.0
    64452a897a4cf9c3: 0.0
    1ce8ed99b7938d82: 0.0
    fdf58a3178eae813: 0.0
    8280fd77641477e7: 0.0
    35794dde13c9705d: 0.0
  task:
    7b36fdbb80f4cc35: 0.0
    da48c7b3fb414b0d: 0.0
    f0d0787ab7c007e7: 0.0
    a37245d6d4cf2b11: 0.0
  attention: {}
mind_decision_block_id: null
thesis_claim: AVGO will rebound from its post-earnings selloff and close between $359.02
  and $374.78 on 2026-09-11 as investors distinguish supply-constrained revenue timing
  from weakening AI demand.
thesis_horizon: '2026-09-11'
thesis_band_low: 359.02
thesis_band_high: 374.78
thesis_drift: 0.035
thesis_vol_view: null
leg_divergence_count: 0
attribution: ''
provenance: agent
---

## Thesis

AVGO should rebound from its post-earnings selloff and close between $359.02 and $374.78 on September 11 as investors distinguish supply-constrained revenue timing from weakening AI demand. A trade below the September 3 post-earnings low near $342 invalidates the rebound premise.
