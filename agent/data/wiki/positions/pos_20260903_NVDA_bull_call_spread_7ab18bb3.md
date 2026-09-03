---
type: Position
position_id: pos_20260903_NVDA_bull_call_spread_7ab18bb3
status: open
interim_band: 0
max_loss_usd: 5670.0
last_pnl_pct: -0.06031746031746032
greeks_at_entry:
  delta_shares: 586.26
  delta_dollars: 134957.96
  gamma_shares: 21.67
  theta_dollars: -149.1
  vega_dollars: 77.5
entry_iv: 0.315
entry_spot: 230.2
strategy: bull_call_spread
underlying: NVDA
opened: '2026-09-03T17:54:29.380890+00:00'
expiry: '2026-09-11'
legs:
- symbol: NVDA260911C00230000
  side: buy
  qty: 18
  iv_pct: 31.19
- symbol: NVDA260911C00240000
  side: sell
  qty: 18
  iv_pct: 31.38
exit_rules:
- type: stop_loss
  basis: position_mark
  threshold: -50.0%
- type: profit_target
  basis: position_mark
  threshold: 50.0%
- type: time_stop
  days_before_expiry: 1
- type: underlying_stop
  direction: below
  level: 225.0
exit_state:
  leg_divergence:above:2:
  - false
  - false
  - false
  position_mark:below:-0.5:
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
  underlying:below:225:
  - false
  - false
  - false
close_reason: null
closed_at: ''
decision_ref: jrn_20260903T175316Z_dec8a78e4
sources:
- id: new_20260903T175314Z_alpaca_news_9ef4ddea
  resource: inbox/new_20260903T175314Z_alpaca_news_9ef4ddea
  author: alpaca_news
generated:
  by: openai:gpt-5.6-sol | anthropic:claude-opus-5 | openai:gpt-5
  at: '2026-09-03T19:20:33.318906+00:00'
verified:
- by: trdrbot/reconcile
  at: '2026-09-03T17:59:51.165738+00:00'
elfmem_blocks:
  self:
    cf4026ebe4e5f325: 0.0
    78ec8cb80ae8e249: 0.0
    78b0c92502a8cab5: 0.0
    95209bc148c6a7b9: 0.0
    df86248db03497d9: 0.0
    9d43b52dbc4fff0e: 0.0
    64452a897a4cf9c3: 0.0
    fdf58a3178eae813: 0.0
    1af203536546c2ef: 0.0
    1ce8ed99b7938d82: 0.0
    8280fd77641477e7: 0.0
    35794dde13c9705d: 0.0
  task:
    7b36fdbb80f4cc35: 0.0
    da48c7b3fb414b0d: 0.0
    a37245d6d4cf2b11: 0.0
    f0d0787ab7c007e7: 0.0
  attention:
    f487491a936a89ce: 1.0
mind_decision_block_id: 8455d93b435ce5af
thesis_claim: From about $230.2, NVDA should close between $232 and $245 on 2026-09-11
  as post-earnings AI-demand support and the Hugging Face acquisition sustain modest
  upside, while a close below $225 would invalidate the continuation thesis.
thesis_horizon: '2026-09-11'
thesis_band_low: 232.0
thesis_band_high: 245.0
thesis_drift: 0.01
thesis_vol_view: null
leg_divergence_count: 0
attribution: ''
provenance: agent
---

## Thesis

From about $230.2, NVDA should close between $232 and $245 on September 11 as post-earnings AI-demand support and the Hugging Face acquisition sustain modest upside. A trade below $225 invalidates the continuation premise; September 4 payrolls are acknowledged binary risk.
