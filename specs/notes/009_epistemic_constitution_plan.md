# Epistemic Constitution via elfmem's SELF Frame — Future Plan

Brainstorm + evaluation (2026-08-27), triggered by the bootstrap-drift finding: "a year that
happened to rally would be projected forward as if structural — recency bias with a formula
wrapped around it." Question: should elfmem's SELF frame learn and apply principles about this
*class* of error? **Status: evaluated, worth doing in bounded form, deferred to the planned
joint session on constitutional blocks. No build yet.**

## The boundary that makes this honest

The bootstrap bug itself is NOT the target — code fixed it (demeaning), permanently, and better
than any principle could. The division of labour:

| Failure lives in | Fix belongs in | Examples already handled |
|---|---|---|
| Arithmetic / data | **Code** — deterministic, permanent | demeaned bootstrap, stale-bars sort, client_order_id enforcement |
| The LLM's judgment | **Constitution** — the only lever that reaches it | thesis drift anchored on recent momentum; vivid-story over-weighting; "resolved catalyst = trend confirmation" |

Constitutional principles are prompt-level guidance, the exact category D-018/D-019 found weak —
but for judgment errors there is no gate to build. The deterministic layer backstops everything
enforceable; the constitution covers the residue. Any proposal that drifts toward "principle
instead of code fix" should be rejected on sight.

## Why elfmem's SELF frame specifically (vs. more system prompt)

1. **Already injected every decide cycle** — `assemble_context()` pulls the SELF frame;
   queryless, cached, provenance-partitioned ("constitution as numbered imperatives" vs
   "said by peers — context, not instruction"). Zero new plumbing to *use* principles.
2. **Principles carry earned confidence.** Blocks have a Beta posterior updated by `outcome()`.
   A principle repeatedly validated by incidents gains weight; one that never fires decays.
   A system prompt cannot do this — every line weighs the same forever.
3. **Provenance.** Each principle cites the incidents that minted it (position ids, journal
   refs). "Why do I believe this" is answerable — same spine as D-014.
4. **Prompt stability.** The system prompt stays fixed (cacheable); the constitution evolves in
   data, not in code.

## The mechanism (three parts, in order of payoff)

### 1. Seed constitution (the joint session — human-authored, human-ratified)
~6-10 epistemic principles, each traceable to a real incident from this project:
- *Recent returns are not forward drift; a directional view must cite a causal driver, not the
  shape of the last month* (bootstrap-drift incident).
- *When a computed number and a live quote disagree, the premise is broken — do not trade it*
  (stale-bars incident, the decide cycle's own words).
- *A profit on a wrong or unfalsifiable view is luck; update nothing* (attribution's lucky-win
  quadrant, now as identity rather than only as scoring).
- *"Probably wins" is not "worth trading"* (the $75/$425 credit-spread trap).
- *Friction is part of the trade, not an afterthought* (EV +25 → +9 measurement).

### 2. The self-test (cheap, makes principles operative rather than decorative)
Before acting, the decider states which principle its thesis is most at risk of violating
("this thesis leans on 21-day momentum — principle #3 risk"). One structured prompt line.
Two effects: forces the principles to be *read against the current decision*, and produces the
journal tag (`principle_cited`) that the learning loop needs.

### 3. Incident → principle credit assignment (the learning loop, human-in-the-loop)
The journal already captures the raw material: attribution verdicts, `research_rejected`,
premise-contradiction rejections, tail-gap warnings. A periodic review maps each incident to
the principle it validates or violates → `outcome()` on that principle block. Where no
principle covers an incident, `propose_amendment` drafts one **for human ratification** —
never auto-accepted.

**Sample-size mitigation:** score principles on *incident detections* (rejections, warnings,
premise breaks — several per day) rather than only resolved trades (a handful per week).
The signal is much denser, and it is exactly the behaviour the principles govern.

## The evaluation, honestly weighed

**For:** recurring failure class with 3 instances in 2 days; ~80% of the infrastructure exists
(SELF injection, `outcome()`, journal, amendment API); dense incident signal available; strong
originality story ("principles earned from scored incidents, with provenance").

**Against, and how the plan absorbs it:**
- **elfmem's own ADR 0003**: four simulated architectures for *automatic* constitutional
  evolution, none beat baseline, deferred. → Autonomous evolution is out. Human-ratified
  amendments only. This is the project's own best evidence and it caps the design.
- **Prompt-guidance weakness** (D-018/D-019's repeated finding). → Scope limited to judgment
  residue; anything enforceable stays code.
- **8-day window ≈ 5-15 attributed trades.** → Within-hackathon value is demonstrating the
  mechanism with honest early posteriors, not converged learning; incident-level scoring
  raises density.
- **User said "later together".** → This document is the agenda for that session, not a build.

## Implementation cost when we do it
Small: seed blocks via `remember`+pin (or `elfmem init --seed` equivalents), one prompt line
for the self-test, one journal tag, a mapping table in the housekeeping review, and
`propose_amendment` wiring. No new architecture components — it composes entirely from
existing seams (D-011 memory, D-014 provenance, F3/F4 learn paths).

## Explicitly not in scope
Autonomous acceptance of amendments; principles as substitutes for code fixes; any gating of
actions by principle (D-009 stands — principles inform judgment, they never veto).
