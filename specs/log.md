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
**Open:** all three MCP/elfmem/elfsim verifications from notes/004 landed (MCP: local stdio confirmed; elfsim: spec-only →
D-013 in-repo calibration module using elfmem's mind loop; elfmem: real, import as library,
pin to self-frame-contract branch). notes/004 complete. Next: Specify mode for the six
planned modules, then the day-0/1 walking skeleton.
