# Session Log

## 2026-08-26
**Did:** Charter + spec scaffolded; hackathon research (docs/); D-001..D-007 recorded, then a
major pivot: user redirected to a headless LangGraph harness with an inbox pipeline, no
guardrails, and reuse of elfmem + elfsim + an LLM wiki. D-001/D-002/D-004/D-005/D-006
superseded by D-008..D-012. Architecture research written to notes/004.
Data model + provenance spine designed (D-014, spec.md Data Model). Conceptual architecture
written to architecture.md, then extended with the information & tooling layer (D-015 sensor
registry; D-016 analytics pack + tool registry): now C1-C23, 6 flows, 3 state machines,
16 invariants, 22 failure modes, and a simulation guide.
Stress simulation run against the architecture (notes/006): 6 scenarios traced step-wise,
**14 gaps found, 3 critical** — nothing resolves inside the 8-day window so the learning loop
never closes; poison-pill inbox items stall the pipeline; the idempotency key derives from a
nondeterministic decision so FM-1's mitigation does not hold.
Gaps folded in as D-018 (hardening #1-#8 pre-code, #9-#12 into module specs) plus D-017
(agent-authored exit rules + split fast/slow tick model). architecture.md now C1-C24, F1-F7,
INV-1..24, FM-1..31.
Regression simulation (notes/007) against the hardened design: none of the 3 CRITICAL fixes
fully holds as specified. Idempotency fix downgraded CRITICAL→MEDIUM (real exposure risk
closed, recovery-procedure gap remains). New HIGH bug found: C24 exit-rule evaluator runs
before reconciliation in F1, acting on stale data across assignment/expiry — one-line reorder
fix also closes an adversarial race for free. 7 new findings total; not yet folded into specs.
Regression findings folded in as D-019: reordered fast-tick path (C13 before C24, closes the
new HIGH ordering bug + an adversarial race for free), added a competition-deadline sweep
independent of DTE, added a resume-from-journal check so write-ahead logging actually enables
recovery, reworded INV-6 to resolve its conflict with INV-24, capped the needs-attention tier
against systemic regime shifts, and refined dead-lettering + exit-rule debounce. D-018's note
points to D-019 for the completed items. architecture.md, spec.md, charter.md all updated
(architecture.md now includes INV-25..30, FM-32..37).
Researched Google's Open Knowledge Format (real, verified against primary SPEC.md — decision-
mode fan-out, 53 agents): adopted as D-022 (normative frontmatter: type/sources/generated/
verified/status/stale_after, replacing wiki_refs) and D-023 (house rules borrowed from OKF's
non-normative reference agent: four-gate mint test, monotonic-augmentation write guard — the
actual mechanism against wiki degradation). spec.md's Position entity and architecture.md's
wiki section updated. Portable cross-project reference saved to
docs/sources/open_knowledge_format.md.
**CODE GAP, folded into stage 3:** src/trdrbot/positions.py predates D-022/D-023 — no
`type`/`sources`/`generated`/`verified` fields, no augmentation guard. Fixed as part of building
the wiki write path in stage 3 (memory), not separately.

pyproject.toml updated: elfmem now a real git dependency
(`github.com/emson/elfmem.git@elfmem_index`, superseding the earlier local-path/branch
reference — matches charter.md's already-updated constraint). Verified: `uv sync` resolves
clean (115 packages, no conflicts with existing deps), `elfmem` 0.20.0.dev0 imports,
`MemorySystem` exposes the expected surface (`frame`, `dream`, `curate`, `from_config`, etc.)
per the earlier elfmem exploration in notes/004 §10.1.
**Open:** all three MCP/elfmem/elfsim verifications from notes/004 landed

Stage 3 built and verified live (not synthetic): wiki.py (OKF concept read/write + augmentation
guard), positions.py updated with OKF fields (D-022 folded in as promised), elfmem_adapter.py,
learn.py (F2/F3 credit assignment), housekeeping.py (F4, interim scoring INV-24). A real
multi-leg order pending since stage 2 filled mid-session: reconciliation promoted it, on_fill
remembered the thesis + created a mind prediction + marked it machine-confirmed, market closed
so housekeeping ran and interim-scored it. Full chain confirmed via journal + position page
inspection, not assumed.

Two real findings recorded: D-024 (elfmem's mind_create duplicate detection is unreliable once
other memory ops happen first — verified live; worked around with our own local
underlying->mind_id mapping) and D-025, now RESOLVED — user supplied a valid OPENAI_API_KEY.
Verified end to end by forcing dream() directly: remember() -> dream() -> recall() round-trip
confirmed, assemble_context() now returns real text in all three frames. elfmem's semantic
recall is fully functional. (First verification attempt hit the same shell-shadowing class of
bug as the earlier Anthropic key issue, self-inflicted by an ad hoc test script that skipped
config.load() — not a new bug, a reminder to always load secrets through it.)

Stage 4 built: sensors.py (D-015 registry, alpaca_news live — verified get_news IS
watchlist-scopeable via `symbols`, resolving an architecture.md §12 unknown) and
calibration.py (D-013 Brier + Murphy decomposition, math verified against known cases:
Murphy's identity rel-res+unc=Brier holds exactly; overconfidence correctly detected).
record_position now takes a `confidence` the agent is told is scored; the decide prompt
shows the agent its own calibration record. New `trdrbot calibration` CLI view.

**D-026 — serious latent bug found by running it:** the news sensor reported "20 new of 20
fetched" and left 2 files on disk. item_id/journal_id/position_id all derived their unique
component from a second-resolution timestamp hash, so any batch written within one second
collided into a single id. 18 of 20 real news articles were silently destroyed. Latent
since the walking skeleton — unreachable until a batch-emitting producer existed. Fixed
with uuid4; batch_id/client_order_id verified STILL deterministic since INV-18 depends on
that. 20/20 items now persist. (MCP: local stdio confirmed; elfsim: spec-only →
D-013 in-repo calibration module using elfmem's mind loop; elfmem: real, import as library,
pin to self-frame-contract branch). notes/004 complete. Next: Specify mode for the six
planned modules, then the day-0/1 walking skeleton.


Reviewed the prior trdrbot project's tools/MCPs (D-027). Adopted **Polymarket** — the
only candidate with zero operational friction (no auth, no cost, no separate process) and
literally #2 in our own D-015 sensor order. Rejected **xmcp** despite genuine usefulness:
4 OAuth secrets, real credit cost (their journal logs an HTTP 402 depletion mid-run), a
separate ~9s-startup server to keep alive for 8 unattended days, and the lowest trust tier
our own FM-18 flagged. Rejected elfmem/elfsim MCPs (we use the library / it has no impl)
and six organs that duplicate what we built.

The real transfer was knowledge, not code: nine live-verified Gamma API quirks now in
docs/sources/polymarket_gamma_api.md. Quirk 1 re-verified live here — `outcomePrices` is a
JSON-encoded *string*, so naive `prices[0]` yields the character `'['`. Silent corruption,
not an error.

Surfaced a latent bug in our own stage-4 code: `Sensor.policy` was declared but never read,
and alpaca_news was mislabeled. Policy is now real (filter/change_only/raw), with
change_only measuring against the last *emitted* value so slow drift still surfaces.
Live: 8 macro markets ingested (Fed cut odds, US recession, CPI); second poll emitted 0.

Built the thesis->experiment->execute->attribute loop (D-028) across 10 test/harden
iterations. New: optmath.py (exact payoff maths vs modelled probability, labelled
separately), experiments.py (Thesis/Experiment/simulate/rank/attribute),
attribution.py (horizon-timed view-vs-structure verdict), simulate_experiments tool.

The core idea: a thesis can be RIGHT while its expression is WRONG, and a thesis can be
WRONG while the trade profits anyway. P&L-only learning cannot tell these apart and
reinforces whichever story correlates with money - which is how an agent learns a
superstition. The elfmem signal now follows the attribution, not the P&L.

Two real bugs found by testing, not review: max_profit_loss reported a finite max profit
for a long straddle whose upside is unbounded (put branch overwrote a correct None), and
calendar spreads computed silently wrong because Leg had no expiry field. Both fixed and
verified. Maths validated independently: E[S_T]=spot exactly, EV of a fair option = 0.0000.

## 2026-08-27
**Did:** Built the research funnel (D-032): market_stats.py (computed technicals + demeaned
bootstrap MC from real returns - the convergence test caught raw resampling inheriting the
sample path's directional luck, 16pp off; demeaned it converges to 1.6pp), research.py
(daily regime page + company dossiers + falsifiable opportunities through the inbox seam),
HISTORY row + tail-gap warning in simulate_experiments. Full funnel verified live: research
wrote 4 OKF wiki pages + emitted opportunities; the decide cycle then REJECTED both initial
opportunities - one on payoff arithmetic, one on a price discrepancy that exposed a real
bars bug (ascending limit truncates from range START; stats were six weeks stale). Fixed
with sort=desc. The funnel validated itself on its first run.
Evaluated the user's proposal to use elfmem's SELF frame for epistemic principles (the
recency-bias class): worth doing in human-ratified form only — elfmem's own ADR 0003 found
automatic constitutional evolution never beat baseline across four simulated architectures,
so autonomous self-amendment is out. Plan + mechanism in notes/009, recorded as D-033.
notes/009 is the agenda for the joint constitutional session.
**Open:** live open-market execution of the full chain (market opens 09:30 ET today);
elfmem constitution + self-frame session with the user — agenda now at notes/009.
