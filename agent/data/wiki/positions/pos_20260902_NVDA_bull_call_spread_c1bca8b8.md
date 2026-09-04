---
type: Position
position_id: pos_20260902_NVDA_bull_call_spread_c1bca8b8
status: closed
interim_band: 0
max_loss_usd: 6364.0
last_pnl_pct: 0.5174418604651163
greeks_at_entry:
  delta_shares: 1072.31
  delta_dollars: 235651.18
  gamma_shares: 65.77
  theta_dollars: -725.86
  vega_dollars: 71.3
entry_iv: 0.38299999999999995
entry_spot: 219.76
strategy: bull_call_spread
underlying: NVDA
opened: '2026-09-02T13:57:12.357502+00:00'
expiry: '2026-09-04'
legs:
- symbol: NVDA260904C00220000
  side: long
  qty: 37
  iv_pct: 38.31
- symbol: NVDA260904C00225000
  side: short
  qty: 37
  iv_pct: 37.29
exit_rules:
- type: stop_loss
  basis: position_mark
  threshold: -45.0%
- type: profit_target
  basis: position_mark
  threshold: 60.0%
- type: time_stop
  days_before_expiry: 1
- type: underlying_stop
  direction: below
  level: 218.0
exit_state:
  leg_divergence:above:2:
  - false
  - false
  - false
  position_mark:below:-0.45:
  - false
  - false
  - false
  position_mark:above:0.6:
  - false
  - false
  - false
  days_to_expiry:below:1:
  - false
  - false
  - false
  underlying:below:218:
  - false
  - false
  - false
close_reason: external
closed_at: ''
decision_ref: jrn_20260902T135542Z_deccf1ebf
sources:
- id: new_20260902T033512Z_alpaca_news_4348c942
  resource: inbox/new_20260902T033512Z_alpaca_news_4348c942
  author: alpaca_news
- id: new_20260902T063529Z_alpaca_news_3bd310de
  resource: inbox/new_20260902T063529Z_alpaca_news_3bd310de
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_0e43486d
  resource: inbox/new_20260902T071422Z_alpaca_news_0e43486d
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_1c68fa8d
  resource: inbox/new_20260902T071422Z_alpaca_news_1c68fa8d
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_31a8ad70
  resource: inbox/new_20260902T071422Z_alpaca_news_31a8ad70
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_5675a74a
  resource: inbox/new_20260902T071422Z_alpaca_news_5675a74a
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_86dd986f
  resource: inbox/new_20260902T071422Z_alpaca_news_86dd986f
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_8d9e20a8
  resource: inbox/new_20260902T071422Z_alpaca_news_8d9e20a8
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_8fb9df65
  resource: inbox/new_20260902T071422Z_alpaca_news_8fb9df65
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_92b1e86f
  resource: inbox/new_20260902T071422Z_alpaca_news_92b1e86f
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_ac4523bd
  resource: inbox/new_20260902T071422Z_alpaca_news_ac4523bd
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_b7aecbd7
  resource: inbox/new_20260902T071422Z_alpaca_news_b7aecbd7
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_d3f1fb47
  resource: inbox/new_20260902T071422Z_alpaca_news_d3f1fb47
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_dfc3a139
  resource: inbox/new_20260902T071422Z_alpaca_news_dfc3a139
  author: alpaca_news
- id: new_20260902T071422Z_alpaca_news_e5de1983
  resource: inbox/new_20260902T071422Z_alpaca_news_e5de1983
  author: alpaca_news
- id: new_20260902T081013Z_alpaca_news_ac06f47c
  resource: inbox/new_20260902T081013Z_alpaca_news_ac06f47c
  author: alpaca_news
- id: new_20260902T082923Z_alpaca_news_9bb450e8
  resource: inbox/new_20260902T082923Z_alpaca_news_9bb450e8
  author: alpaca_news
- id: new_20260902T095507Z_alpaca_news_87138962
  resource: inbox/new_20260902T095507Z_alpaca_news_87138962
  author: alpaca_news
- id: new_20260902T095507Z_alpaca_news_d5e6f68e
  resource: inbox/new_20260902T095507Z_alpaca_news_d5e6f68e
  author: alpaca_news
- id: new_20260902T102511Z_alpaca_news_16f8b22d
  resource: inbox/new_20260902T102511Z_alpaca_news_16f8b22d
  author: alpaca_news
- id: new_20260902T102511Z_alpaca_news_9cf3306c
  resource: inbox/new_20260902T102511Z_alpaca_news_9cf3306c
  author: alpaca_news
- id: new_20260902T112519Z_alpaca_news_a9f01cf0
  resource: inbox/new_20260902T112519Z_alpaca_news_a9f01cf0
  author: alpaca_news
- id: new_20260902T125531Z_alpaca_news_1be51e22
  resource: inbox/new_20260902T125531Z_alpaca_news_1be51e22
  author: alpaca_news
- id: new_20260902T132535Z_alpaca_news_a01ac8a6
  resource: inbox/new_20260902T132535Z_alpaca_news_a01ac8a6
  author: alpaca_news
- id: pre_20260901T220312Z_polymarket_2e2d469f
  resource: inbox/pre_20260901T220312Z_polymarket_2e2d469f
  author: polymarket
generated:
  by: openai:gpt-5.6-sol | anthropic:claude-opus-5 | openai:gpt-5
  at: '2026-09-03T20:03:20.257030+00:00'
verified:
- by: trdrbot/reconcile
  at: '2026-09-02T14:02:31.817368+00:00'
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
    39fc9a266a7d276c: 0.939350864723999
    9de1219e4fffad15: 1.0
mind_decision_block_id: a3ce113a75545323
thesis_claim: NVDA will hold above 218 and rebound modestly toward 222-224 by the
  September 3 close as post-earnings AI demand support outweighs semiconductor tariff
  and macro pressure.
thesis_horizon: '2026-09-03'
thesis_band_low: 218.0
thesis_band_high: 225.0
thesis_drift: 0.012
thesis_vol_view: 0.35
leg_divergence_count: 0
attribution: thesis_wrong_profited_anyway
provenance: agent
---

## Thesis

NVDA should hold above 218 and rebound modestly toward 222-224 by the September 3 close as post-earnings AI demand support outweighs semiconductor tariff and macro pressure. A trade below 218 invalidates the premise.
