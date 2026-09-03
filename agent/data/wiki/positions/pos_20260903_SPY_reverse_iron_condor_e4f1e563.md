---
type: Position
position_id: pos_20260903_SPY_reverse_iron_condor_e4f1e563
status: open
interim_band: 0
max_loss_usd: 5865.0
last_pnl_pct: 0.09019607843137255
greeks_at_entry:
  delta_shares: -24.72
  delta_dollars: -19016.54
  gamma_shares: 28.59
  theta_dollars: -280.42
  vega_dollars: 407.89
entry_iv: 0.11
entry_spot: 769.2
strategy: reverse_iron_condor
underlying: SPY
opened: '2026-09-03T13:59:29.067300+00:00'
expiry: '2026-09-11'
legs:
- symbol: SPY260911P00760000
  side: sell
  qty: 23
  iv_pct: 11.0
- symbol: SPY260911P00765000
  side: buy
  qty: 23
  iv_pct: 11.0
- symbol: SPY260911C00775000
  side: buy
  qty: 23
  iv_pct: 11.0
- symbol: SPY260911C00780000
  side: sell
  qty: 23
  iv_pct: 11.0
exit_rules:
- type: stop_loss
  basis: position_mark
  threshold: -55.0%
- type: profit_target
  basis: position_mark
  threshold: 50.0%
- type: time_stop
  days_before_expiry: 0
exit_state:
  leg_divergence:above:2:
  - false
  - false
  - false
  position_mark:below:-0.55:
  - false
  - false
  - false
  position_mark:above:0.5:
  - false
  - false
  - false
  days_to_expiry:below:0:
  - false
  - false
  - false
close_reason: null
closed_at: ''
decision_ref: jrn_20260903T135813Z_dec15332d
sources:
- id: pos_20260903T135812Z_idle_7e501550
  resource: inbox/pos_20260903T135812Z_idle_7e501550
  author: idle
generated:
  by: openai:gpt-5.6-sol | anthropic:claude-opus-5 | openai:gpt-5
  at: '2026-09-03T17:37:03.752267+00:00'
verified:
- by: trdrbot/reconcile
  at: '2026-09-03T14:04:47.704897+00:00'
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
    39fc9a266a7d276c: 0.911501012243324
    478f17213fb5749e: 1.0
mind_decision_block_id: a45023f792e8a623
thesis_claim: From 769.2, SPY should realize about 12% annualized volatility through
  September 11 as payrolls and rate/geopolitical risks break the recent low-volatility
  consolidation, with a mild downside bias and a September 11 close between 755 and
  775.
thesis_horizon: '2026-09-11'
thesis_band_low: 755.0
thesis_band_high: 775.0
thesis_drift: -0.006
thesis_vol_view: 0.12
leg_divergence_count: 0
attribution: ''
provenance: agent
---

## Thesis

From 769.2, SPY should realize roughly 12% annualized volatility through September 11 as payrolls and rate/geopolitical risks break the recent low-volatility consolidation; the position needs SPY outside roughly 762.45-777.55 at expiry. The premise is invalidated if the event passes and SPY remains pinned near 765-775 while realized volatility falls below the structure's approximately 9.5% breakeven volatility.
