# 026 - The Playbook: structure choice becomes a Coach lever, measured before trusted

Audience: an LLM implementer with full repo access. This document is self-contained: the
finding, the design and why the alternatives lost, the simulation evidence, exact schemas,
module-by-module specs, the edge cases with their required handling, the tests that must
exist, the docs to update, and the verification sequence. It follows the shape of
[notes/016](016_coach_implementation_plan.md), which built the first lever; read that one's
"where the build diverged, the build is right" table and apply the same rule here.

Plain dashes throughout. No em dashes anywhere in code, docs or prompts.

## 0. Read these before writing any code

| File | Why |
|---|---|
| `agent/src/trdrbot/coach.py` (module docstring + `arms`, `record_trial`, `pulse`, `_disjoint`) | The four rules and the protocol every lever obeys. Rule 3 (measured/measurer) decides what a reward may be |
| `agent/src/trdrbot/coach_pkg/state.py` | `Lever` registry (data, not callables), `TO REGISTER A NEW LEVER` comment, `LeverState`, floors |
| `agent/src/trdrbot/coach_pkg/mutate.py` | `MUTATE_PROMPT` is muse-shaped today; this plan generalises it. `validate_prompt` is the deterministic gate a challenger must pass |
| `agent/src/trdrbot/coach_pkg/gauges.py` | Gauges (omit, never zero), `Sentinel`, `_cost_today` roles, `survived()` - the one definition of "survived" |
| `agent/src/trdrbot/coach_pkg/posterior.py` | `Tally`, `verdict`, `p_challenger_better`. Every promotion goes through `verdict` |
| `agent/src/trdrbot/muse.py` (`run`, `_evaluate`, `_score_arm`, `ShadowLedger`) | The reference implementation of a paired shadow trial. Copy its structure: one gate cascade, both arms, a shared memo, a void on exception |
| `agent/src/trdrbot/opportunity.py` | The inbox seam's ONE shape. `to_payload` is a wire format; `ids.opportunity_id` hashes three of its keys |
| `agent/src/trdrbot/experiments.py` (`Thesis`, `simulate`, `render_comparison`, `attribute`) | The facts/models split and the view-vs-structure attribution this lever is the pre-trade mirror of |
| `agent/src/trdrbot/optmath.py` (`Leg`, `_lognormal_grid`, `pnl_at`, `max_profit_loss`, `expected_move`, `parse_occ`) | Everything the reward needs already exists here; the plan adds one pure function |
| `agent/src/trdrbot/local_tools.py` (`simulate_experiments`, `size_position`) | What the decide agent reads per candidate; where agent-simulated structures can be journalled for resolution |
| `agent/src/trdrbot/tick.py` (`_build_decide_prompt`, the hunt rung around line 760) | Where opportunities render into the decide prompt (today: raw JSON), and where the muse pulses the Coach |
| `agent/src/trdrbot/llm.py` `SYSTEM_PROMPT` | The decide system prompt. Gets two sentences, not a mapping |
| `agent/src/trdrbot/housekeeping.py` (forecast resolution around line 177) | Where the expiry resolver hooks in; `_resolved_value` is "one place a metric resolves" |
| `agent/src/trdrbot/health.py` (`Probe`, `heartbeat`) | Heartbeat fields are enforced at write time; a new `*_run` kind declares them |
| `agent/src/trdrbot/ledger.py` `GATES`, `gate_of` | The fate classifier the rejection digest keys on. Extend, do not fork |
| `agent/src/trdrbot/wiki.py` `LIFECYCLE` | `Technique` type exists (timeless). A new page needs no new lifecycle |
| `agent/src/trdrbot/lessons.py` | The shape of a measured lesson with a cue |
| `agent/tests/test_coach.py`, `tests/fixtures_lever.py`, `tests/conftest.py` (`FakeTool`, `tools_for`, `journal_rows`) | Test fixtures and the registry-override pattern (`monkeypatch.setattr(coach, "LEVERS", ...)` AND `trdrbot.coach_pkg.state.LEVERS`) |
| `agent/tests/scaffold_structure_zoo.py` | The zoo of structures at fair value; reuse `zoo()` and `fair_price` |
| `docs/principles_coding.md`, `docs/principles_testing.md` (four pillars, six admission rules), `docs/principles_agent_api.md` | Not optional |
| `specs/decisions.md` D-028, D-052, D-077, D-088, D-090, D-104, D-105 | The evidence the constraints rest on |
| `specs/issues.md` I-16, I-27, I-28, I-68 | The open items this plan touches |

## 1. The finding, and why the obvious fix is wrong

Checked in code, not assumed:

- **The maths is already structure-agnostic.** `optmath` prices any single-expiry leg set;
  `simulate_experiments` accepts arbitrary legs; friction is summed per real leg spread
  (`local_tools.py` around line 267); `payoff_ratio` is the conditional pair (D-077), so the
  sizer treats condors and verticals fairly. No leg-count assumption exists in `exit_rules`,
  `positions` or `local_tools`. Iron condors, flies, strangles are legal and priceable today.
- **In practice only 1-2 leg structures have ever been traded** (journal: every `reconciliation`
  and `exit` row carries 1 or 2 legs). Nothing tells the decide agent which structure family
  fits which thesis shape, and the technique pages that discuss it (`what-am-i-actually-betting-on`,
  `credit-vs-debit-is-not-a-choice`, `skew-does-not-select-structures`) are **never read by the
  decide prompt** - `_build_decide_prompt` reads the regime page, elfmem recall, `lessons.md`
  and calibration; techniques reach the agent only as muse collision material.
- **The constitution is full** (427/430 tokens, I-17). Nothing about structures goes there.

The obvious fix - a "structure families by thesis shape" paragraph in `SYSTEM_PROMPT` - is a
human-asserted mapping nothing scores. The project's own rules say the mapping should be
**data the Coach can move, scored by the stack's own economics, promoted on evidence**. That
is what this plan builds.

## 2. The design in one paragraph

A new deterministic subsystem, **the playbook**, runs once for every opportunity at the moment
it is admitted to the inbox. It reads a **catalogue** (YAML data - the lever) of structure
families, each declaring which *thesis shapes* it applies to and where its strikes sit
**relative to the thesis band** in units of the expected move. For the opportunity's shape it
instantiates every applicable family on the live chain (real strikes, real mids, real spreads,
per-leg IV), runs each through fixed **band-conditional gates** - *every leg quoted, loss
bounded, pays after entry costs IF the thesis band holds, wins materially more often when the
band holds than when it fails* - and attaches the priced menu to the opportunity. The decide
agent sees the menu beside the claim and is told to use it as the starting point for its
"at least two genuinely different structures". The Coach trials catalogue variants exactly as
it trials the muse prompt: a shadow challenger instantiated on the same chain memo, scored by
the same gates, writing nothing; reward = fraction of proposed candidates that survive. Every
proposed candidate (survivor or rejected) is journalled with its legs and **resolved at expiry
against the close** - exact arithmetic, no model - which is the slow evidence that audits the
fast one, and delivers I-16 for structures the agent priced and declined.

```
research ─┐                         ┌──── incumbent catalogue ──► priced menu ──► inbox ──► decide
discovery ┼─► admit() ─► playbook ──┤     (attached to the opportunity)                     │
muse ─────┘   (opportunity)  │      └──── challenger catalogue ──► scored, discarded         │
                             │            both arms: ONE chain memo, ONE gate cascade        │
                             ▼                                                              ▼
                     journal `playbook` row ─────────────► housekeeping resolves each      simulate_experiments
                     (legs + expiry per candidate)         candidate at expiry close       (agent's own candidates
                             │                             `playbook_outcome`               journalled the same way)
                             ▼
                     coach.record_trial ──► Beta posterior ──► promote / refute / timeout
```

## 3. Non-negotiable rules (each traces to a measured incident)

1. **The reward is computed, never asked.** Band-conditional gates over the production grid;
   no LLM opinion anywhere in scoring (D-081, D-088 rule 1).
2. **The Coach touches data, never code.** The catalogue is YAML in `data/state/levers/`. The
   gates, their constants (`MIN_BAND_EDGE`, `ENTRY_CROSSINGS`, sigma bounds), the validator
   and the sentinels are code the lever cannot reach (D-088 rule 2).
3. **Measured/measurer.** `reward_modules=("optmath.band_conditional", "experiments.simulate")`.
   No lever names those, so `_disjoint` lets the muse and the playbook run experiments
   concurrently - and neither can move the other's ruler (D-088 rule 3; notes/015).
4. **The challenger is a shadow.** Both arms share one chain memo and one gate cascade byte for
   byte; only the incumbent's proposals reach the opportunity, the journal and the inbox
   (D-088's "most important edge case"). A challenger that RAISES voids the trial; a shared
   input that is ABSENT (no chain, no expiry in window) voids the trial for both arms - that
   is data absence, not variant quality, and differs deliberately from the muse's "empty reply
   is failures" rule, where emptiness is the variant's own doing.
5. **Heartbeat is a different record from output.** `playbook_run` is written on every attach
   whether or not anything was proposed; `playbook_resolve_run` on every housekeeping pass
   (D-074, D-082, D-086).
6. **Fail open for bookkeeping, fail loud for correctness.** `playbook.attach` never raises and
   never blocks an emission; on error it returns the opportunity unchanged and writes a
   `degraded("playbook", ...)` row.
7. **Production behaviour is unchanged while a trial runs.** The incumbent IS production.
8. **Nothing about structures enters the constitution** (I-17; D-088's carve-out). The
   knowledge goes to a cued lesson (elfmem, decaying) and a technique page (wiki, durable).
9. **Derive, never declare** (D-037). The traded structure's *family* is classified from its
   legs, never from the model's `strategy` string.
10. **Every store is append-only.** New journal kinds only; no rewriting of `playbook` rows on
    resolution - outcomes are separate rows keyed by the proposal row id.

## 4. Alternatives considered and rejected

| Alternative | Why it lost |
|---|---|
| **A. A `SYSTEM_PROMPT` fragment as the lever, shadow-paired by running a second decide loop** | ~$1.32 per decide cycle doubled; the shadow arm needs every order/record/register tool stubbed - a large, dangerous surface; and there is no deterministic Bernoulli event for "chose the right family" |
| **B. Score the muse/research/discovery `suggested_structures` strings** | Free text nothing validates; couples structure learning to prompt levers that are already under trial; edits to the muse prompt mid-trial corrupt its pairing (gauges.py, `_funnel_overlap_rate`) |
| **C. Reward = "the traded structure matched the menu's top family"** | Scores obedience, not quality |
| **D. A prompt lever trialled by alternating cycles (unpaired)** | Violates rule 7 - the challenger would run production. The protocol is paired for a reason (regime confounds) |
| **E. Reward = EV-after-costs under the thesis drift** (the sizing gate) | Muse opportunities carry `drift_pct = 0.0` (their view is a band + probability), so every structure fails at -friction, both arms tie at 0, the lever can never learn from the source that emits most. Two measures for one quantity is this project's most familiar bug |
| **F. A capital-efficiency gate (return on max loss when right)** | Kills condors on narrow ranges (E[pnl \| hold]/max loss = 0.13) while passing flies - the max/max bias D-077 removed from sizing, rebuilt in the reward. Deep-ITM gaming is closed structurally instead: the validator bounds strike offsets to +/-2.5 sigma from their anchor, so an 80/120 spread at spot 100 is unrepresentable |
| **G. Auto-writing a technique page on every promotion** | A second LLM call whose quality nothing scores (the D-081 rule). Promotions carry rationale + fingerprints in `experiments.jsonl`; a human distils at review time (D-090's pattern) |

## 5. Simulation evidence

Run against the production `optmath` grid (spot 100, 7 days, 25% IV, 1-sigma = $3.46), every
structure at fair value so any edge is the reward's own artefact. Gates: E[pnl | band holds]
minus entry friction > 0, and P(win | holds) - P(win | fails) >= 0.25.

| thesis shape | survives | rejected (reason) |
|---|---|---|
| range narrow [98,102] (1.2s) | iron fly (edge +0.83), iron condor (+0.36), both credit verticals (+0.33) | debit verticals (pay negative when it holds), **tight fly 99/100/101 (pays -$13 when it holds - narrower than the band)**, strangle, long call |
| range wide [93,107] (4.0s) | iron condor only (+0.83) | everything else pays <= 0 when it holds; the fly is -$4 |
| bullish target [103,108] | bull call debit (+0.79), bull put credit (+0.44), long call (+0.81), long strangle (+0.36) | every bearish and range structure; condor is "indifferent" (-0.37) |
| bullish floor [98, inf) | bull put credit (+0.89), iron fly (+0.51), bull call debit (+0.49), long call (+0.47) | condor at +0.21 falls under the 0.25 bar; tight fly pays -$23 |
| bearish ceiling (-inf,102] | bear call credit (+0.90), iron fly (+0.50), bear put debit (+0.50) | mirror of the floor row |

Reads as a desk would: premium structures on ranges, verticals on directional claims,
the fly only where the band is narrow, and a fly narrower than the band refused - so the
reward cannot be gamed by ever-tighter flies. The strangle surviving a bullish target is the
known soft spot (it pays on the right side); the outcome audit and the sizer both see through
it, and no catalogue pressure favours it since verticals pass at least as often.

Trial dynamics under the existing floors (5 candidates per opportunity, ~10 opportunities per
day, 120 simulated experiments each):

| arms (survival) | default floors 8/24/0.90 | `promote_at: 0.95` |
|---|---|---|
| 0.50 vs 0.70 (real improvement) | promoted 100%, mean 9.4 runs (~1 day) | promoted 98%, 11.5 runs |
| 0.50 vs 0.50 (no difference) | **promoted 33%**, refuted 23%, timeout 45% | promoted 17%, timeout 66% |
| raising `min_runs` to 16 / `min_candidates` to 60 | equal arms still promote 28% (peeking continues past the floor) | - |

A ~50% base rate gives this lever symmetric headroom - the I-27 asymmetry that stalls the muse
at 0.89 does not apply - but it also exposes the sequential-peeking cost the muse's ceiling was
hiding: one in three equal-arm experiments promotes. A false promotion swaps in an equally good
catalogue (harmless) at the cost of churn, which the churn sentinel bounds. `promote_at: 0.95`
halves it for a 20% speed cost. **Set it per lever, in config, with this table as the reason.**

## 6. The catalogue: schema, seed, semantics

### 6.1 Shapes - derived from the claim, never from the `direction` label

`playbook.shape_of(band_low, band_high, spot) -> str | None`, pure:

| bands | condition | shape |
|---|---|---|
| both | `lo <= spot <= hi` | `range` |
| both | `lo > spot` | `bull_target` |
| both | `hi < spot` | `bear_target` |
| low only | - | `bull_floor` |
| high only | - | `bear_ceiling` |
| neither | - | `None` (cannot happen after `admit()`; guard anyway) |

When the model's `direction` disagrees with the derived shape (a "bullish" claim with a
bearish band), journal `shape_disagrees=True` on the row and use the band. The band is what
resolves; the label is prose.

### 6.2 Anchors and offsets

A leg's strike is `anchor + sigma * expected_move`, snapped to the nearest listed strike at the
chosen expiry, where `expected_move = optmath.expected_move(spot, iv_atm, days_to_expiry)` -
days to EXPIRY, not horizon, because strikes live on the expiry's distribution.

Anchors: `spot`, `band_low`, `band_high`, `band_mid` (= (lo+hi)/2, needs both). A family whose
anchor is unresolvable for a shape it declares is a validator error, not a runtime one.

### 6.3 Schema (YAML, block or flow style both accepted)

```yaml
version: 1
families:
  - name: <slug, unique, [a-z0-9_]+>
    shapes: [<one or more of range|bull_target|bear_target|bull_floor|bear_ceiling>]
    legs:                     # 2..4 legs
      - right: C|P
        side: long|short
        qty: 1|2              # default 1
        at: {anchor: spot|band_low|band_high|band_mid, sigma: <float in [-2.5, 2.5]>}
```

### 6.4 Seed (`playbook.SEED_CATALOGUE`, the in-code default the lever is seeded from)

Nine families. Strikes sit **on the claim**: shorts at the band edges of a range, a debit
vertical spanning a target band, a short put AT a floor. The mutator will explore from here.

```yaml
version: 1
families:
  - name: bull_call_debit
    shapes: [bull_target, bull_floor]
    legs:
      - {right: C, side: long,  at: {anchor: spot, sigma: 0.0}}
      - {right: C, side: short, at: {anchor: spot, sigma: 1.0}}
  - name: bull_call_debit_on_band          # the literal expression of "rises into [lo, hi]"
    shapes: [bull_target]
    legs:
      - {right: C, side: long,  at: {anchor: band_low,  sigma: -0.25}}
      - {right: C, side: short, at: {anchor: band_high, sigma: 0.0}}
  - name: bull_put_credit                  # short put AT the floor the claim names
    shapes: [bull_floor]
    legs:
      - {right: P, side: short, at: {anchor: band_low, sigma: 0.0}}
      - {right: P, side: long,  at: {anchor: band_low, sigma: -1.0}}
  - name: bear_put_debit
    shapes: [bear_target, bear_ceiling]
    legs:
      - {right: P, side: long,  at: {anchor: spot, sigma: 0.0}}
      - {right: P, side: short, at: {anchor: spot, sigma: -1.0}}
  - name: bear_put_debit_on_band
    shapes: [bear_target]
    legs:
      - {right: P, side: long,  at: {anchor: band_high, sigma: 0.25}}
      - {right: P, side: short, at: {anchor: band_low,  sigma: 0.0}}
  - name: bear_call_credit
    shapes: [bear_ceiling]
    legs:
      - {right: C, side: short, at: {anchor: band_high, sigma: 0.0}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 1.0}}
  - name: iron_condor                      # shorts on the band edges: pays iff it stays inside
    shapes: [range]
    legs:
      - {right: P, side: short, at: {anchor: band_low,  sigma: 0.0}}
      - {right: P, side: long,  at: {anchor: band_low,  sigma: -1.0}}
      - {right: C, side: short, at: {anchor: band_high, sigma: 0.0}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 1.0}}
  - name: iron_butterfly
    shapes: [range]
    legs:
      - {right: P, side: short, at: {anchor: band_mid,  sigma: 0.0}}
      - {right: C, side: short, at: {anchor: band_mid,  sigma: 0.0}}
      - {right: P, side: long,  at: {anchor: band_low,  sigma: -0.5}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 0.5}}
  - name: call_butterfly                   # debit fly on the band
    shapes: [range]
    legs:
      - {right: C, side: long,  at: {anchor: band_low,  sigma: 0.0}}
      - {right: C, side: short, qty: 2, at: {anchor: band_mid, sigma: 0.0}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 0.0}}
```

### 6.5 Validator (`playbook.validate_catalogue(text: str) -> str`, "" when valid)

Deterministic, names the exact defect (the retry suffix hands it back to the mutator):

1. YAML parses to a mapping with `families: list`, 3 <= len <= 12 (`MAX_FAMILIES = 12`).
2. Names unique slugs; `shapes` non-empty, every value known; `legs` 2..4; `right` in C/P;
   `side` in long/short; `qty` in {1, 2}; `at.anchor` known; `-2.5 <= at.sigma <= 2.5`
   (`MAX_ANCHOR_SIGMA = 2.5` - this is what makes deep-ITM structures unrepresentable).
3. Every shape is covered by at least one family (a catalogue that cannot answer a range
   thesis is not a catalogue).
4. For each family and each shape it declares: the anchors resolve (`band_mid` needs both
   bands; `bull_floor` has only `band_low`), AND the family instantiated on a synthetic board
   (`SYNTHETIC_SPOT = 100`, `SYNTHETIC_SIGMA = 4.0`, bands per shape: range [96,104],
   bull_target [104,110], bear_target [90,96], bull_floor [97, None], bear_ceiling
   [None, 103]) has `optmath.max_profit_loss(legs)[1] is not None` - bounded loss by the
   same arithmetic that scores it. This is the "no naked short" rule stated as a property.
5. Two legs of one right may not resolve to the same strike on the synthetic board
   (degenerate by construction).

## 7. The reward

### 7.1 One new pure function in `optmath`

```python
@dataclass(frozen=True)
class BandConditional:
    p_band: float          # market-implied P(band holds) - context, not a gate
    e_pnl_hold: float      # E[pnl | S_T in band], dollars per 1x the legs' qty
    p_profit_hold: float   # P(pnl > 0 | S_T in band)
    p_profit_fail: float   # P(pnl > 0 | S_T not in band)

    @property
    def edge(self) -> float: return self.p_profit_hold - self.p_profit_fail

def band_conditional(legs, spot, iv, days, band_low, band_high) -> BandConditional | None:
    """Payoff conditional on the THESIS, under the market's own distribution.

    Splits `_lognormal_grid(spot, iv, days)` (drift 0 - deliberately the market's; the
    claim supplies the conditioning, so no second measure is invented) into the band
    region and its complement. None when either region carries < 1e-6 of the mass or
    there is no band. Uses `pnl_at`, so it refuses calendars the same way everything
    else does.
    """
```

Docstring must say why it exists: it is the pre-trade mirror of `experiments.attribute` -
attribution asks *after* the fact "was the view right, was the expression right"; this asks
*before* "if the view is right, does the expression pay, and does it stop paying when the
view is wrong".

### 7.2 Gates, in order, one fate string each (prefix `rejected: ` so `coach.survived` and the
digest read them; survivors are fated `candidate`)

| # | gate | fate wording (stable - `gate_of` keys on it) |
|---|---|---|
| 0 | shared inputs present (chain, spot, ATM IV, an expiry between horizon and window end) | not a fate - the whole trial is VOIDED with the reason |
| 1 | every leg has a quote with bid > 0 and ask > 0 | `rejected: unquoted leg <OCC>` |
| 2 | no two legs of one right collapsed to one strike after snapping | `rejected: degenerate - legs collapsed to one strike` |
| 3 | `max_loss is not None` | `rejected: unbounded loss` |
| 4 | `e_pnl_hold - entry_friction > 0` | `rejected: pays $<n> when the thesis holds` |
| 5 | `edge >= MIN_BAND_EDGE` | `rejected: indifferent to the thesis (edge +0.xx)` |

Constants, in `playbook.py`, each with a comment stating what audits it:

- `MIN_BAND_EDGE = 0.25` - from the table in section 5; tunable ONLY from `playbook_outcome`
  rows (do rejected-as-indifferent candidates keep winning?), never from taste. Same rule as
  `CORROBORATION_FRACTION` (I-65).
- `ENTRY_CROSSINGS = 0.5` - entry friction is HALF the round-trip spread per leg: a proposal
  is scored as held to expiry, and the lesson `friction-is-the-size-of-the-edge` records that
  a round trip charged on a hold-to-expiry structure is an exit never paid.
- The conditioning distribution is the lognormal at the expiry's ATM IV. The calibrated
  bootstrap (D-089) would be the natural refinement; it is deferred because it needs closes
  the muse's out-of-universe names often lack, and the arms are paired either way. Record
  `dist: "lognormal"` on every row so a later switch is auditable.

Extend `ledger.GATES` with the four new needles: `("unquoted leg", "unquoted")`,
`("degenerate", "degenerate")`, `("unbounded loss", "unbounded")`,
`("when the thesis holds", "unfaithful")`, `("indifferent to the thesis", "indifferent")`.
One classifier, not two (D-104).

### 7.3 Scoring an arm

`playbook.score_arm(verdicts, asked) -> {"candidates", "survived", "failed", "fates"}` - same
shape and same rule as `muse._score_arm`, using `coach.survived`. `asked` is the number of
families applicable to the shape; a catalogue with zero applicable families for a shape
scores `asked` failures (it could not answer the thesis - that is the variant's doing, unlike
a missing chain).

## 8. Module-by-module specification

### 8.1 `agent/src/trdrbot/playbook.py` (new, ~350 lines)

Public surface (all typed, no try/except in the pure functions):

```python
SEED_CATALOGUE: str                       # section 6.4, exactly
SHAPES: tuple[str, ...]
ANCHORS: tuple[str, ...]

def shape_of(band_low, band_high, spot) -> str | None
def parse_catalogue(text: str) -> Catalogue           # raises CatalogueError (message = defect)
def validate_catalogue(text: str) -> str              # "" or the defect; wraps parse + rules 3-5
def resolve_legs(family, shape, *, spot, sigma, band_low, band_high, chain: Chain) -> list[Leg] | str
    # strikes snapped to the chain; returns a fate string on gates 1-2
def classify(legs: list[Leg]) -> str
    # family NAME from leg geometry: single_call/put, vertical_debit/credit (bull/bear),
    # iron_condor, iron_butterfly, call/put_butterfly, straddle, strangle, ratio, other.
    # Pure; pinned against scaffold_structure_zoo.zoo().
def evaluate(legs, *, spot, iv, days, band_low, band_high, friction_rt) -> dict
    # gates 3-5 + the numbers: net, max_profit, max_loss, e_hold, p_hold, p_fail, edge,
    # entry_friction, fate
def score_arm(verdicts, asked) -> dict

async def attach(tools, config, journal, o: Opportunity, *, source: str,
                 chain: dict | None = None) -> Opportunity
    # THE hot-path entry. Never raises. Steps:
    #  1. arms = coach.arms(config, "playbook.catalogue", seed_text=SEED_CATALOGUE)
    #  2. shape_of(...); shared inputs: chain (passed in, else one get_option_chain call),
    #     spot (chain underlying price or last close), expiry choice, ATM IV, sigma
    #  3. incumbent: resolve + evaluate every applicable family -> verdicts
    #  4. if arms.paired: challenger on the SAME memo -> verdicts (void on exception or
    #     absent shared input); coach.record_trial(run_nonce=<opportunity id>)
    #  5. journal "playbook" row (incumbent only) + health.heartbeat("playbook_run", ...)
    #  6. return replace(o, proposed_structures=<survivors first, then rejected one-liners>)

async def resolve(config, tools, journal) -> dict
    # housekeeping: every `playbook` and `structures_simulated` row candidate whose expiry
    # session has closed (ids.session_closed_on) and has no `playbook_outcome` yet.
    # Close from market_stats.load_dated_closes; if the series does not reach the expiry
    # and expiry is within RESOLVE_FETCH_DAYS=5, one fetch_daily_series per name, saved;
    # still missing -> retry next pass; after RESOLVE_GIVE_UP_DAYS=10 -> outcome row with
    # unresolved="no_price". pnl = optmath.pnl_at(legs, close) - entry_friction.
    # Heartbeat "playbook_resolve_run": due, resolved, no_price, given_up.
```

`Chain` is a thin normalised view of the Alpaca snapshot dict: `{occ: {right, strike, expiry,
bid, ask, mid, iv}}` built with `optmath.parse_occ` and the `latestQuote.bp/ap` keys
`compact.py` already reads (`impliedVolatility` where present). Build it in `playbook`, do
not fork `compact.py`.

Expiry choice: the nearest listed expiry `>= horizon`; the chain was fetched with
`expiration_date_lte=<window latest>`, so if nothing qualifies the trial is VOIDED with
`no expiry between horizon and window end`. ATM IV: the mean IV of the call and put nearest
spot at that expiry; if the chain carries no IV, fall back to `market_stats.compute_stats`
realized vol from stored closes and record `iv_source="realized"`; if neither, VOID.

### 8.2 `optmath.py`

Add `BandConditional` and `band_conditional` (7.1). Nothing else changes.

### 8.3 `opportunity.py`

- `Opportunity` gains `proposed_structures: tuple[dict, ...] = ()`; `from_payload` reads it
  (list of dicts, tolerant), `to_payload` writes it. **`ids.opportunity_id` hashes
  underlying/horizon/bands only - verify with a test that the id is unchanged with and
  without proposals.**
- `options_gate` additionally returns `"chain": snaps` (the raw snapshots dict) when it
  answered via snapshots. Additive; every caller reads `.get("tradeable")` and ignores the
  rest. This is what lets the muse path make ZERO extra network calls.
- `render_for_decide(payload: dict) -> str`: the compact block the decide prompt shows
  (section 8.8). Lives here because the payload keys are this module's wire format.

### 8.4 The three emission sites - one line each, same shape (principles_coding rule 6)

Immediately before each `inbox.write_opportunity(o, source=...)`:

```python
o = await playbook.attach(tools, config, journal, o, source="research",
                          chain=<the options_gate result's "chain" if at hand, else None>)
```

- `research.py` ~line 345: the `tradeable()` memo already holds the gate result per ticker -
  keep the whole dict, not just the bool, and pass its `chain`.
- `discovery.py` ~line 330: nominees carry `_options_ok`; retain the gate dict on the nominee
  the same way and pass its `chain`.
- `muse.py` ~line 639: `cache[gkey]` already holds the gate dict; pass `cache[gkey].get("chain")`.

### 8.5 `coach_pkg/state.py` - the registry learns what it always claimed to know

`Lever` gains three data fields (all defaulted so the muse's declaration keeps working):

```python
reward_description: str = ""   # "How it is scored", in the mutator's prompt, per lever
contract_note: str = ""        # what a variant must not change, per lever
validator_ref: tuple[str, str] = ("", "")   # (module, attr) -> callable(text) -> "" | defect
```

Move the muse's scoring paragraph and its "Do not change the output schema..." sentence out of
`MUTATE_PROMPT` into its `Lever(...)`. Register:

```python
Lever(
    "playbook.catalogue", "playbook",
    ("optmath.band_conditional", "experiments.simulate"), "policy",
    seed_ref=("trdrbot.playbook", "SEED_CATALOGUE"),
    placeholders=(),
    must_contain=("families:", "shapes:", "anchor:", "sigma:"),
    evidence_kind="playbook",
    reward_description=(
        "Each family you propose is instantiated on the live option chain for every "
        "opportunity whose thesis SHAPE it declares (range, bull_target, bear_target, "
        "bull_floor, bear_ceiling), with strikes placed from your anchors and sigma offsets. "
        "Each instance then meets fixed gates: every leg quoted, loss bounded, pays after "
        "entry costs IF the thesis band holds, and wins at least 25 points more often when "
        "the band holds than when it fails. The reward is the FRACTION of instances that "
        "survive every gate. A family that fits a shape badly fails often; a shape no family "
        "covers scores as failures."),
    contract_note=(
        "Keep the YAML schema exactly: version, families[].name/shapes/legs[].right/side/"
        "qty/at.anchor/at.sigma. Anchors are spot, band_low, band_high, band_mid; sigma "
        "within -2.5..2.5. Between 3 and 12 families; every shape covered; every family must "
        "have a bounded loss - no naked shorts. Put the full replacement YAML in the "
        "`prompt` field."),
    validator_ref=("trdrbot.playbook", "validate_catalogue"),
)
```

`floors(cfg, lever_name: str = "")`: merge `cfg.coach["levers"][lever_name]` over the global
floors when present. Two call sites take the lever name (`pulse`, `cli` status).
`config.yaml` gets, with the section-5 table as its comment:

```yaml
coach:
  levers:
    playbook.catalogue:
      promote_at: 0.95
```

`Sentinel` gains `levers: tuple[str, ...] = ()` (empty = every lever). In `pulse`, filter
`fired` per lever by scope before applying `reverting`/`sentinel_block`. Without this the
muse's `entropy_floor` would close a playbook experiment and vice versa - a sentinel about
concept diversity reverting a lever about strike placement.

### 8.6 `coach_pkg/mutate.py`

- `MUTATE_PROMPT` templates `{how_scored}`, `{contract}` and `{format_rules}`. `format_rules`
  is the existing double-brace paragraph for `kind == "prompt"`, and for `kind == "policy"`:
  "The text is data, not a template. Return the complete replacement YAML."
- `validate_prompt(text, incumbent, placeholders, *, must_contain=(), kind="prompt",
  validator=None)`: the length, identity and `must_contain` checks run for every kind; the
  `.format()` safety and placeholder-presence checks run for `prompt` only (YAML flow
  mappings use braces); then `validator(text)` when given, its return being the defect.
  `mutate()` resolves `validator_ref` lazily, exactly as `seed_text` resolves `seed_ref`.
- `clean_prompt`: strip any trailing/leading line that is only dashes and spaces
  (`re.fullmatch(r"[-\s]+", line)`), not just the two literal fence strings. **Do not edit the
  live muse challenger `v1` text** - its last line is a 9-dash echo the current cleaner
  missed, and editing either arm mid-trial closes the experiment as `operator_override`
  (I-91). Fix the cleaner for the next mutation and record the leak as an issue (section 12).

### 8.7 `coach_pkg/gauges.py`

Gauges (omit when no data, as every other one):

- `playbook.survival_rate` - over the last `GAUGE_WINDOW` `playbook` rows.
- `playbook.candidates_per_opportunity`.
- `playbook.family_entropy` - distinct family names proposed in the window.
- `playbook.runs_total`.
- `playbook.outcome_hit_rate` - share of `playbook_outcome` rows with `won` over the window,
  only once `>= MIN_OUTCOMES = 5` exist.

Sentinel `playbook_entropy_floor` (`levers=("playbook.catalogue",)`, reverts): fires when
`family_entropy < 3` with at least `GAUGE_WINDOW` rows - "the playbook has collapsed to one
shape". `_cost_today` roles are unchanged: the playbook makes no LLM calls and its mutations
use the shared `coach_mutate` role already under the ceiling.

### 8.8 The decide prompt and the system prompt

In `_build_decide_prompt`, opportunity items render through `opportunity.render_for_decide`
instead of `json.dumps(payload)`. Target shape, deterministic, one opportunity:

```
- [opportunity | muse | trust=primary] NVDA - "NVDA holds post-earnings support above 218 and
  closes 222-232 on 2026-09-04" - bullish; holds if 222 <= price <= 232 on 2026-09-04.
  why: MUSE domino chain: ... | stated 49% vs history's base 31%
  PLAYBOOK (bull_target; priced 2026-09-03 13:02 on the 2026-09-04 chain, spot 224.44,
  1-sigma $5.10; indicative - re-simulate at live quotes before acting):
    bull_call_debit_on_band  +C222 -C232   debit $410  maxP $590 / maxL $-410 | holds: P(win) 91% E[pnl] +$402 | fails: P(win) 12%
    bull_call_debit          +C224 -C229   debit $215  maxP $285 / maxL $-215 | holds: 84% +$231 | fails: 18%
    rejected: iron_condor - indifferent to the thesis (edge +0.08); call_butterfly - pays $-31 when the thesis holds
```

Survivors first (at most `MENU_MAX = 5`), rejected as one line. Each survivor line carries
enough for the agent to write the legs into `simulate_experiments` (rights, strikes, sides,
the expiry in the header).

`SYSTEM_PROMPT`, workflow step 1, add after "at least TWO genuinely different structures":

> Opportunities arrive with a PLAYBOOK: structure families placed against the thesis band and
> priced indicatively, with what each pays if the thesis holds and if it fails. Start from it -
> two verticals are one shape, a vertical and a condor are two - re-simulate at live quotes,
> and propose your own when the menu misses the thesis's shape.

That is the whole prompt change. The mapping itself lives in the lever, not the prompt.

Optional, recommended as its own commit: `render_comparison` prints the band-conditional line
(`IF THE THESIS HOLDS: P(profit) x% E[pnl] $y | IF IT FAILS: P(profit) z%`) per candidate when
the thesis has a band. This changes `test_simulation_golden.py`'s exact output - update the
golden deliberately with a `# CHANGED (026)` note, never loosen it.

### 8.9 `local_tools.simulate_experiments` - the agent's own candidates resolve too (I-16)

After `results` are computed and when the thesis carries a band: journal one
`structures_simulated` row with the same per-candidate shape as a `playbook` row
(`family=classify(legs)`, legs with expiry derived from `days_to_expiry`, `entry_friction`,
the band-conditional numbers, `source="agent"`, `variant=None`). Not a trial, never scored by
the Coach - a different kind precisely so the lever's rejection digest does not read it. The
resolver treats both kinds identically. This is I-16's proposed shape ("journal the declined
STRUCTURE with its legs, resolve at its horizon") delivered for every structure the agent
prices, traded or not.

### 8.10 `attribution.py` and `sizing` rows carry the family

`journal.append("attribution", ..., family=playbook.classify(legs))` and the `sizing` row
gets `family=` from the matched structure's legs. Derived from legs (D-037), so "which
families have been right, wrong, or lucky" is answerable from the journal without trusting
`Position.strategy`. No Position schema change.

### 8.11 `health.py`

```python
Probe("playbook", ("playbook_run",),
      lambda rows: sum(int(r.get("proposed") or 0) for r in rows), 5,
      "the playbook runs and proposes nothing - chain, expiry window or anchors broken",
      heartbeat_fields=("opportunities", "proposed", "survived", "voided")),
Probe("playbook_resolve", ("playbook_resolve_run",),
      lambda rows: sum(int(r.get("resolved") or 0) for r in rows), 3,
      "proposals are never resolved at expiry - dated closes missing or the fetch is dead",
      work=lambda rows: sum(int(r.get("due") or 0) for r in rows),
      never_producing_is_ok=True,        # nothing due yet is the normal first week
      heartbeat_fields=("due", "resolved", "no_price", "given_up")),
```

`tests/test_health_contract.py` enumerates heartbeat fields - extend it.

### 8.12 `housekeeping.py`

After forecast resolution and before the Coach pulse: `await playbook.resolve(config, tools,
journal)`, isolated like `attribution.run` (a raise costs this step, not the pass).

### 8.13 CLI (`cli.py`)

- `trdrbot playbook show` - incumbent catalogue text, fingerprint, origin, since, rationale,
  state (`blocked` or running), open experiment summary.
- `trdrbot playbook try TICKER --band LO,HI --horizon YYYY-MM-DD [--variant challenger]` -
  live chain, one table per applicable family: legs, net, maxP/maxL, holds/fails columns,
  fate. The operator's verification surface; also what "run it, paste the output" means for
  this plan.
- `trdrbot playbook status` - survival by shape and family over the window; outcomes by family
  once they exist; the open experiment's tally.
- `trdrbot coach status` and `trdrbot report` iterate `coach.LEVERS` and `sorted(series)` -
  verify the new lever and gauges appear with NO edits; fix only if they do not.

## 9. Knowledge stores: what goes where, per the constitution's `[routing]`

| store | what | why here |
|---|---|---|
| `data/state/levers/playbook.catalogue.json` | the live mapping (data) | the Coach moves it; provenance in `experiments.jsonl` |
| elfmem (via `lessons.LESSONS`) | ONE new lesson, `structure-follows-the-thesis-shape`, carrying the section-5 numbers and the NVDA sim (same view: condor frees ~34% of the vertical's capital at similar P(win); the fly trades P(win) 70% -> 49% for payoff 0.43 -> 1.03; a long strangle is the only long-vega expression and bleeds ~$95/day). Cue: "when choosing between structures for a thesis, or when every candidate on the board is a vertical" | evolving, decaying, scored by outcomes - it is a claim about this book, not a rule |
| wiki `technique/structure-follows-the-thesis-shape.md` (type `Technique`) | the durable reasoning: shapes, anchors, the two conditional questions, the table, and "the catalogue is the live version; this page is why" | stable reference; muse lens material; human-readable |
| `specs/decisions.md` | D-1xx (section 12) | the record |
| constitution | nothing | full (I-17), and a structure rule is enforceable by a deterministic check, which the constitution's own scope test excludes |

Promoted variants are NOT auto-written as technique pages (section 4, G). `trdrbot playbook
show` prints the incumbent's rationale; a human distils at review time.

## 10. Edge cases and their required handling

| case | handling |
|---|---|
| No chain / gate answered via error or substring fallback | trial VOIDED (`voided="no_chain"`), opportunity unchanged, `playbook_run` written with `voided=1` |
| No listed expiry between horizon and window end | VOID, reason recorded |
| Chain carries no IV and no stored closes | VOID (`no_sigma`); never invent a vol |
| Leg quotes with bid or ask 0/missing | gate 1 fate; counts as the catalogue's failure (it chose an untradeable strike) - identical for both arms |
| Two legs snap to one strike (wide strike grid on a low-priced name) | gate 2 fate |
| Catalogue has no family for the shape | `asked=0` -> scored as failures for that arm (see 7.3); journal notes `uncovered_shape` |
| `direction` label disagrees with the band | use the band; `shape_disagrees=True` on the row |
| Same opportunity re-emitted next day | new opportunity id (per UTC day) -> a new trial; nonce dedup unaffected |
| Challenger raises | VOID, as the muse |
| Incumbent raises | opportunity emitted without a menu; `degraded("playbook", ...)`; no trial |
| Research runs while the market is closed | chain quotes are last prints; menu is labelled with its pricing time; still a fair paired trial |
| Realized-vol theses (`metric=realized_vol`) | out of scope: they are forecasts, not band opportunities; `attach` is never called for them |
| Resolution before expiry session closes | wait (`ids.session_closed_on`); never resolve on the previous session's print (I-79) |
| Expiry close missing for an out-of-universe name | one `fetch_daily_series` per name per pass within 5 days of expiry; give up at 10 with `unresolved="no_price"`; never guess |
| Lever state file unreadable | Coach's existing rule: incumbent-only from the seed, file kept |
| An operator edits the incumbent YAML by hand | supported; fingerprint recomputed; an open trial closes as `operator_override` (I-91) - say so in README |
| Muse `entropy_floor` fires | closes muse experiments only (sentinel scope, 8.5) |
| Both arms tie for 40 runs | `timeout`, incumbent keeps its place - by design |

## 11. Tests (names are the spec; one behaviour each; pillar tests carry the mutation sentence)

New `tests/test_playbook.py`:

- `test_shape_of_derives_five_shapes_from_band_and_spot` (parametrized, all rows of 6.1)
- `test_seed_catalogue_validates_and_every_family_is_bounded_on_every_declared_shape`
- `test_validate_catalogue_names_the_defect` (parametrized: naked short, unknown shape,
  sigma 3.0, uncovered shape, 13 families, band_mid on bull_floor, duplicate name)
- `test_band_conditional_matches_an_independent_grid_computation`
- `test_reward_prefers_premium_on_ranges_and_verticals_on_directional_claims` - PILLAR-4
  (learning integrity); pins RELATIONSHIPS from section 5 (condor survives range and fails
  target; bull call debit the reverse), not levels. Mutation-verified: negating
  `MIN_BAND_EDGE` or dropping gate 4 must fail it - perform the revert and say so in the
  docstring.
- `test_tight_fly_narrower_than_the_band_is_rejected_for_paying_negative_when_it_holds`
- `test_attach_shadow_arm_writes_nothing` - FakeTool chain, paired arms; assert exactly one
  `playbook` journal row, one `playbook_run`, one `trial_result` with both arms, and the
  returned opportunity carries only incumbent proposals
- `test_attach_shares_one_chain_fetch_across_both_arms` (FakeTool call count == 1, and 0 when
  `chain=` is passed)
- `test_attach_voids_the_trial_when_no_expiry_lies_inside_the_window`
- `test_attach_never_raises_and_degrades_when_the_incumbent_arm_fails`
- `test_resolve_scores_a_candidate_at_the_expiry_close_exactly` (synthetic dated closes;
  expected pnl computed independently in the test)
- `test_resolve_waits_for_the_expiry_session_to_close`
- `test_resolve_gives_up_after_ten_days_without_a_price_and_says_so`
- `test_classify_names_the_zoo` (parametrized over `scaffold_structure_zoo.zoo()`)
- `test_render_for_decide_lists_survivors_then_rejections_and_fits_in_eight_lines`
- `test_proposed_structures_round_trip_the_payload_without_changing_the_opportunity_id`
- `test_structures_simulated_row_is_written_for_the_agents_own_candidates_and_never_scored`

`tests/test_coach.py` additions:

- `test_mutate_prompt_renders_each_levers_own_scoring_and_contract_text`
- `test_validate_prompt_runs_format_checks_for_prompt_levers_only_and_the_lever_validator_for_policy`
- `test_clean_prompt_strips_any_dash_only_line` (the 9-dash leak; assert the live `v1` shape
  would now be cleaned)
- `test_floors_take_a_per_lever_override`
- `test_disjoint_lets_playbook_and_muse_run_experiments_concurrently`
- `test_sentinel_scope_reverts_only_its_own_lever`
- `test_playbook_gauges_omit_when_there_is_no_data`

`tests/test_loop_smoke.py`: extend the research -> inbox -> decide smoke so the rendered decide
prompt contains `PLAYBOOK (` for an admitted opportunity with a fake chain.

`tests/test_health_contract.py`: the two new heartbeats and their fields.

`tests/scaffold_structure_zoo.py`: add `INV-G  the band-conditional gates classify the zoo
per thesis shape the way a desk would` printing the section-5 table. Not collected; the
pinned relationships live in `test_playbook.py`.

Golden: only if 8.8's optional line ships, and then as an explicit `# CHANGED (026)` update.

## 12. Records and docs

- `specs/decisions.md` - **D-1xx "The Playbook: structure choice becomes a measured lever"**:
  context (section 1 verbatim findings), choice (section 2), the reward and why
  band-conditional (section 7 + E in section 4), the evidence tables (section 5), the
  sequential-peeking finding and the per-lever `promote_at`, the shadow/void rules, what was
  rejected (section 4), verified (the commands and outputs from section 13).
- `specs/issues.md`:
  - **I-16** amended: every playbook proposal and every agent-simulated structure now
    resolves at expiry (`playbook_outcome`); traded positions unchanged (attribution).
  - **new I - muse challenger `v1` carries a 9-dash scaffolding line**: `_FENCE_LINES` matched
    only the 10-dash fence; the live challenger text ends with `- - - - - - - - -`. Not edited
    (I-91 would close the trial); cleaner fixed for future mutations.
  - **new I - equal arms promote ~33% of the time at a 50% base under the default floors**
    (sequential peeking; section 5 table). Mitigated per lever with `promote_at: 0.95`;
    a proper sequential correction is deferred until churn is observed.
  - **I-27** note: the playbook's ~50% base has symmetric headroom; if the muse stays
    promotion-less past ~20 trials the secondary-reward action there still stands.
  - **I-28** note: `playbook_outcome` is the first resolved-outcome stream for a lever; the
    outcome audit can be built on it before the muse has resolutions.
- `agent/README.md`: "The Coach" - two levers, a short "The playbook" paragraph (what it
  proposes, what scores it, how to pause/pin/edit it - same controls as the muse, and that a
  hand edit closes an open trial); Commands table `playbook show|try|status`; "How a thesis is
  formed" - opportunities carry a playbook menu; Honest limitations - menus are priced at
  emission, realized-vol theses have no playbook.
- Root `CLAUDE.md`: one bullet - "Before adding or changing a Coach lever:
  `agent/src/trdrbot/coach_pkg/state.py` (TO REGISTER A NEW LEVER) and
  `specs/notes/026_playbook_structure_lever.md`."
- `config.yaml`: the `coach.levers` block (8.5) with the section-5 numbers as its comment.
- `agent/src/trdrbot/lessons.py`: the lesson (section 9); run `uv run trdrbot lessons seed`
  and `lessons verify` and paste the recall result.
- `data/wiki/technique/structure-follows-the-thesis-shape.md` via `wiki.write_concept` with
  `type_="Technique"` and a source row `research:026_playbook_structure_lever`.
- `specs/notes/026_...` (this file): append a "BUILT" header like 016's, with the divergence
  table.

## 13. Verification - commands, and what their output must show

Gate every commit on captured exit codes (pytest, ruff, mypy if configured, every
`tests/scaffold_*.py`, `scripts/suite_at.py 30`), and **restart the live loop after each code
commit** - `trdrbot run` loads config and code once (`agent/logs/agent.log`, pid in
`data/state/run.json`).

```bash
cd agent
uv run pytest                                  # all green; new tests present by name
uv run ruff check src tests
uv run python tests/scaffold_structure_zoo.py  # INV-G table matches section 5's shape
uv run python scripts/suite_at.py 30

uv run trdrbot playbook show                   # seed v0, fingerprint, 9 families, running
uv run trdrbot playbook try NVDA --band 222,232 --horizon <next Friday>
#   -> bull_target; bull_call_debit_on_band and bull_call_debit survive; iron_condor
#      rejected "indifferent"; call_butterfly rejected "pays $-n when the thesis holds"
uv run trdrbot playbook try SPY --band <spot-1%>,<spot+1%> --horizon <next Friday>
#   -> range; iron_condor / iron_butterfly survive; debit verticals rejected
uv run trdrbot muse --force                    # one live run: journal shows `playbook` rows
uv run trdrbot coach status                    # TWO levers listed; playbook experiment opens
                                               # after the 180-min mutation cooldown
uv run trdrbot tick --force                    # decide prompt renders "PLAYBOOK (" blocks -
                                               # confirm in the journal's decision/no_op summary
uv run trdrbot health                          # playbook probe OK; playbook_resolve "not yet due"
uv run trdrbot report                          # playbook.* gauges charted
```

After the first expiry passes: `trdrbot playbook status` shows `playbook_outcome` rows and
`playbook.outcome_hit_rate` appears once five exist.

## 14. Rollout - five commits, each green on its own

1. **Registry generalisation** - `Lever` fields, `MUTATE_PROMPT` templating, `validate_prompt`
   kinds, `clean_prompt` dash rule, per-lever floors, sentinel scope. Muse behaviour
   byte-identical (its scoring text moves, its rendered mutation prompt must not change -
   test it). No new lever yet.
2. **The playbook, offline** - `playbook.py`, `optmath.band_conditional`, `classify`, the
   validator, the seed, `test_playbook.py`, scaffold INV-G. No call sites yet.
3. **Wired in** - `Opportunity.proposed_structures`, `options_gate` chain passthrough, the
   three `attach` calls, the lever registration, gauges, sentinel, heartbeat, probe, CLI
   `show|try`, decide rendering, the two `SYSTEM_PROMPT` sentences, config floors. Live
   verification from section 13 pasted into the decision record.
4. **Resolution** - `playbook.resolve`, housekeeping hook, `structures_simulated` rows from
   `simulate_experiments`, family on attribution/sizing rows, `playbook status`, outcome gauge.
5. **Knowledge and records** - lesson seeded and verified, technique page, README, CLAUDE.md,
   decisions, issues, this note's BUILT header. Optional sixth: the `render_comparison` line
   with its golden update.

## 15. Deferred, recorded so it is not rediscovered

- **Auto-joining catalogue candidates into `simulate_experiments` at live quotes** (the tool
  fetching the chain through the tick's shared MCP session and appending the playbook's
  survivors to the agent's own candidates). The strongest lever on "only verticals get
  traded", and a network call inside a tool - build it once the emission-time menu has been
  observed in decisions for a week and the cost of a per-call chain fetch is measured.
- **Outcome audit disposes.** When a promoted catalogue has ~10 resolved outcomes per family,
  re-match it against the previous incumbent on `playbook_outcome` hit rate (I-28's shape).
  Report-only until then.
- **Calibrated bootstrap as the conditioning distribution** (D-089) - record `dist` now so the
  switch is auditable later.
- **Per-family lessons written by the resolver** - only after the outcome stream exists and a
  human has read it once.
- **A sequential-testing correction** for the peeking cost (section 5) - only if churn
  appears on the report.
