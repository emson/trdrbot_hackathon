---
type: Position
position_id: pos_20260827_NVDA_bull_call_spread_01a75fab
status: open
interim_band: 0
max_loss_usd: 2100.0
greeks_at_entry:
  delta_shares: 242.96
  delta_dollars: 54859.81
  gamma_shares: 13.75
  theta_dollars: -124.49
  vega_dollars: 55.33
entry_iv: 0.36
entry_spot: 225.8
strategy: bull_call_spread
underlying: NVDA
opened: '2026-08-27T15:26:00.288014+00:00'
expiry: '2026-09-04'
legs:
- symbol: NVDA260904C00230000
  side: long
  qty: 10
- symbol: NVDA260904C00240000
  side: short
  qty: 10
exit_rules:
- type: stop_loss
  basis: position_mark
  threshold: -60.0%
- type: profit_target
  basis: position_mark
  threshold: 70.0%
- type: time_stop
  days_before_expiry: 1
- type: underlying_stop
  direction: below
  level: 218.0
exit_state:
  days_to_deadline:below:0:
  - false
  - false
  - false
  position_mark:below:-0.6:
  - false
  - false
  - false
  position_mark:above:0.7:
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
close_reason: null
decision_ref: jrn_20260827T152254Z_dec775fcc
sources:
- id: opp_20260827T152232Z_discovery_36d5c9a3
  resource: inbox/opp_20260827T152232Z_discovery_36d5c9a3
  author: discovery
- id: opp_20260827T152232Z_discovery_514a73bb
  resource: inbox/opp_20260827T152232Z_discovery_514a73bb
  author: discovery
generated:
  by: anthropic:claude-opus-5
  at: '2026-08-27T15:53:53.380067+00:00'
verified:
- by: trdrbot/reconcile
  at: '2026-08-27T15:27:06.400573+00:00'
elfmem_blocks:
  self:
  - 59b91203222b42e4
  - 02cd0d2bd26d4372
  - 465e166c50d74b09
  - 75e029865c8e435d
  - b6966a829bb7482b
  - c4bc0e4a120042b4
  - db0fc2a34d0446bd
  - f42cf6233e384136
  - c5ea572afbc149e9
  - 78fb513481984036
  - 5c42bcc0efd19526
  task: []
  attention:
  - 622adbc1707582cd
  - 8542b75a79eb0ef7
  - 7b36fdbb80f4cc35
mind_decision_block_id: b9c57f86edd8565c
thesis_claim: NVDA holds its post-earnings gap (blowout Q2, broad PT raises to $300-400)
  and drifts modestly higher into 2026-09-03, finishing between 220 and 245.
thesis_horizon: '2026-09-03'
thesis_band_low: 220.0
thesis_band_high: 245.0
thesis_drift: 0.015
attribution: ''
provenance: agent
---

## Thesis

NVDA reported a blowout Q2 last night and re-rated +7.3% to ~225.8 with broad sell-side PT raises ($300/$330/$400); the event binary is now behind it and semi/QQQ ETF inflows are running. I expect the gap to hold and drift modestly higher (+1.5%) into 2026-09-03, finishing 220-245. Invalidated if NVDA gives back the bulk of the gap (below ~218) - today's fade in the sympathy names (SMCI +1.5% off +4% premarket, MRVL round-tripping) already says the AI bid is being sold into, so gap-fill is the live risk. Edge is small and drift-dependent: simulator put EV at only +$10/contract.
