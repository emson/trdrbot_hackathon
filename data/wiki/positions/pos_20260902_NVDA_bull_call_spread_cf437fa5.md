---
type: Position
position_id: pos_20260902_NVDA_bull_call_spread_cf437fa5
status: open
interim_band: 0
max_loss_usd: 5700.0
last_pnl_pct: -0.22631578947368422
greeks_at_entry:
  delta_shares: 830.97
  delta_dollars: 187258.83
  gamma_shares: 36.14
  theta_dollars: -402.21
  vega_dollars: 40.22
entry_iv: 0.4
entry_spot: 225.35
strategy: bull_call_spread
underlying: NVDA
opened: '2026-09-02T17:33:31.350258+00:00'
expiry: '2026-09-04'
legs:
- symbol: NVDA260904C00225000
  side: long
  qty: 30
- symbol: NVDA260904C00230000
  side: short
  qty: 30
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
  level: 218.0
exit_state:
  leg_divergence:above:2:
  - false
  - false
  - false
  position_mark:below:-0.6:
  - false
  - false
  - false
  position_mark:above:0.75:
  - false
  - false
  - false
  days_to_expiry:below:0:
  - false
  - false
  - false
  underlying:below:218:
  - false
  - false
  - false
close_reason: null
decision_ref: jrn_20260902T173203Z_dec9e4618
sources:
- id: new_20260902T173200Z_alpaca_news_b39223f9
  resource: inbox/new_20260902T173200Z_alpaca_news_b39223f9
  author: alpaca_news
generated:
  by: openai:gpt-5.6-sol | anthropic:claude-opus-5 | openai:gpt-5
  at: '2026-09-02T22:34:18.332666+00:00'
verified:
- by: trdrbot/reconcile
  at: '2026-09-02T17:38:43.814575+00:00'
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
    f0d0787ab7c007e7: 0.0
    da48c7b3fb414b0d: 0.0
    a37245d6d4cf2b11: 0.0
  attention:
    39fc9a266a7d276c: 0.8977987094448948
    4934dada6d2db2bd: 1.0
mind_decision_block_id: fef6e773e65ec49b
thesis_claim: From $225.35, NVDA will hold post-earnings support above $218 and finish
  between $218 and $232 on September 4, with modest drift toward $227, as AI-demand
  support outweighs macro pressure despite payroll-related gap risk.
thesis_horizon: '2026-09-04'
thesis_band_low: 218.0
thesis_band_high: 232.0
thesis_drift: 0.0075
thesis_vol_view: 0.45
leg_divergence_count: 0
attribution: ''
provenance: agent
---

## Thesis

From $225.35, NVDA should hold post-earnings support above $218 and finish between $218 and $232 on September 4, with modest drift toward $227 as AI-demand support outweighs macro pressure. A trade below $218 invalidates the premise; September 4 payrolls are acknowledged gap risk.
