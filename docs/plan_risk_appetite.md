# Implementation plan: the risk-appetite lever

**Status:** ready to build. Written for a coding LLM.
**Research:** [`research_risk_appetite.md`](research_risk_appetite.md) - the why, the Monte Carlo, the design space.
**This document:** the what and the order. It **corrects the research doc in four places** (§1); every
correction was measured by driving the real `sizing.size_position` and `competence.assess`, and by
adversarially applying the change to the repo and running the suite.

The research answered *"can one knob move this system's risk, honestly?"* This answers *"what has
to be built so the operator can turn it - and so it cannot ship as a knob wired to nothing?"*

---

## 0. The whole change, on one page

One config number, multiplied into **one field pair** on the posture `competence.assess` already
returns.

```yaml
trading:
  risk_appetite: 0.50    # 1.0 = the posture the ladder alone would choose
```

```python
# competence.assess, after the tier and the ramp are known
a = min(APPETITE_MAX, max(APPETITE_MIN, appetite))     # [0.25, 2.0]
book_cap      = min(BOOK_CEILING, t["cap"] * a)        # 0.35 - the ruin bound
kelly_mult    = kelly * a
seed_fraction = book_cap * SEED_SHARE                  # 0.22 - derived, NOT a constant
```

`position_cap` and `underlying_cap` already derive from `book_cap` (D-098). Adding
`seed_fraction` to that list makes **one multiplication reach all four risk scopes**, and they
cannot desynchronise. That is the entire mechanism. Everything else exists to stop it being silent:

| Concern | Answer |
|---|---|
| Could it ship doing nothing? | `SizingDecision.binding` names the constraint that set every size. WU-1. |
| Could a value be quietly ignored? | The posture reports its **realised** appetite; `trdrbot health` flags a divergence. WU-3, WU-5. |
| Could the agent be told it *earned* an operator's choice? | `reason` states earned **and** applied. WU-3. |
| Could the Coach move it? | It writes only `data/state/levers/`. Pinned by a test. WU-3. |
| Could a published surface lie about it? | **Four** copies of this policy exist. WU-6 reduces them to one. |
| Could it ship green and wrong? | It would today - see §1.4. WU-7 is the only evidence this change has. |

---

## 1. Four corrections to the research doc

### 1.1 `KELLY_CEILING` cannot fire and `FLOOR_CEILING` is wrong. Ship ONE clamp.

The research proposes two runtime clamps (§3); the scaffold carries three
(`tests/scaffold_risk_appetite.py:127-130`). Measured:

| clamp | on | can it bind? |
|---|---|---|
| `BOOK_CEILING` 0.35 | `book_cap` | **yes** - above 1.75x at SCALE, above 1.40x at MATURE |
| `KELLY_CEILING` 0.50 | `kelly_multiplier` | **no.** `max(TIERS[*].kelly) x APPETITE_MAX = 0.25 x 2.0 = 0.5000` exactly - reachable only as `resolved -> inf`. Highest value at any real n: 0.446. |
| `FLOOR_CEILING` 0.05 | `seed_fraction` | **yes, and wrongly.** Once the floor derives from `book_cap` its maximum is `0.35 x 0.22 = 7.7%`. A 5% ceiling would bind and re-introduce a fourth independent constant, breaking the very property the lever depends on. |

**Do:** keep `BOOK_CEILING` as the one runtime clamp. Delete `FLOOR_CEILING`. Demote
`KELLY_CEILING` to a **test-enforced invariant** (I8) - it costs nothing at runtime and still fails
loudly if anyone raises a tier's Kelly or `APPETITE_MAX`. Dead runtime code is entropy; a pinned
invariant is not.

### 1.2 I-69 is real but is NOT a prerequisite. Re-sequence it.

Research §9 makes "decide the shrink target" step 1, because it moves Kelly by 3x. It does. It does
not move **size**, because Kelly is not the binding constraint. Kelly reaches size only when
`full_kelly x kelly_multiplier > seed_fraction` (appetite cancels - §1.3):

| rung | n | multiplier | floor | Kelly binds only above a **shrunk** p of |
|---|---|---|---|---|
| ESTABLISH | 5 | 0.050 | 3.3% | **77.8%** |
| SCALE | 15 | 0.129 | 4.4% | **57.0%** |
| SCALE | **49 (live)** | 0.160 | 4.4% | **52.6%** |
| MATURE | 40 | 0.217 | 5.5% | **51.2%** |

The live claim is a stated 39.6%, which shrinks to **42.0%**. The book's structure class is long
debit spreads at 25-45% stated. **Confirmed against the real record** - every position this book has
ever opened was sized by the floor, never by Kelly:

```
pos_20260826_SPY_bull_put_spread    $2,210  = 2.12% of equity
pos_20260827_NVDA_bull_call_spread  $2,100  = 2.01%
pos_20260828_SPY_bear_put_spread    $2,171  = 2.08%
pos_20260901_SPY_bear_put_spread    $2,052  = 1.97%   (open)
```

Four for four, each just under the 2.2% `SEED_FRACTION`, short only by contract rounding.

**Do:** fix I-69 on its own merits, in its own commit, whenever. It is a code/intent divergence
either way. It is **not** a blocker, and holding the lever behind it pays a sequencing cost for a
coupling that does not reach size.

### 1.3 Appetite is shape-preserving - and that is a testable guarantee

`floor = cap x a x SEED_SHARE` and `kelly_frac = full x mult x a`. The `a` cancels, so **which
constraint binds is invariant under appetite.** Verified across every rung x every appetite.

This is what makes the lever honest: it scales size without distorting the sizing function's shape.
It is also the first thing that would break if someone later scaled the floor independently. Pin it
(I4).

One consequence, stated plainly because it is uncomfortable: **after WU-2 the exploration floor
binds above Kelly at every rung and every appetite for this book's structure class.** The lever
works perfectly; the Kelly arm of the ladder stays decorative, and the band in which conviction
does not move size gets *wider* (SCALE's crossover goes from ~48% to ~53% shrunk). That is I-66
made worse, knowingly, in exchange for a drawdown brake that actually brakes. Record it as
**I-70**. Do not fix it here by inventing a second `SEED_SHARE` table.

### 1.4 The suite is blind to this change. Green proves nothing.

**Measured, not argued:** applying `seed_fraction = book_cap * SEED_SHARE` to the repo and running
`uv run pytest` gives **535 passed** - while the exploration allocation goes 2.2% -> 3.3% / 4.4% /
**5.5%** at ESTABLISH / SCALE / MATURE. A 2.5x size increase at the top rung that nothing objects
to.

Why: no test in the repo references `seed_fraction` at all.
`test_size_is_monotonic_in_evidence` (`test_regressions.py:1076`) measures integer **contracts**,
where the `contracts < 1 -> 1` floor flattens every rung to the same value - the exact blind spot
D-098 already documented for this test. `test_the_three_risk_scopes_nest_at_every_rung:1080` pins
only EXPLORE.

**So: the tests in WU-7 are not a formality, they are the only evidence this change has.** Do not
read a green suite as confirmation at any point before they exist.

A second, related trap: existing tests call `assess` with no appetite, so they exercise **1.0 only**
while production runs 0.50. `test_the_per_position_ceiling_rises_with_the_ladder:1063`
(`assert caps[0] == sizing.MAX_FRACTION`) and `:1080` (EXPLORE reproduces 5% / 8% / 10% exactly)
stay true at 1.0 and become false in production, where they are 2.5% / 4% / 5%. Amend their
docstrings to say *at appetite 1.0*; do not weaken the assertions.

---

## 2. The design

### 2.1 Where the number lives

`config.yaml`, under `trading:`. Not a state file, not an env var, not a Coach lever.

- **git-tracked and reviewable** - a change to the book's risk posture leaves a diff.
- **structurally out of the Coach's reach** - the Coach writes only `data/state/levers/`
  (`coach_pkg/state.py:274`). No policy needed, because no enforcement is needed.
- **absent means 1.0, never OFF** - the rule `Config.coach` already states.

**When a change takes effect depends on the deployment mode, and both are in this repo:**

| mode | behaviour |
|---|---|
| `run.sh` (launchd/cron) - `exec uv run trdrbot tick` | a fresh process per tick, so config is re-read **every tick**. An edit takes effect on the next tick. |
| `trdrbot run` (`cli.py:_run_loop`) | `config.load()` once, before the while-loop. An edit needs a **restart**. |

Document both in the config comment. **Rejected:** moving `config.load()` inside the while-loop.
One line, with a blast radius covering every config key - models, watchlist, tool bindings - plus a
`load_dotenv(override=True)` and `paths.ensure()` per tick. Enormous scope for a knob turned rarely
and deliberately. The appetite is journalled every tick, so the record shows which value each
decision ran under either way.

### 2.2 Where it attaches

**A parameter of `competence.assess`, not a post-hoc transform.**

The scaffold models it as `with_appetite(posture, a)` via `dataclasses.replace`. Do **not** ship
that shape. A transform every caller must remember to apply is precisely the "wired to nothing"
failure this project keeps paying for - the compactor, the cache, the shared session. With
`assess(appetite=...)` there is exactly one way to obtain a posture and it is always correct.
`appetite=1.0` as the default keeps every existing caller and scaffold byte-identical.

### 2.3 What the posture reports - including in prose

`Competence` gains **one field** and **one property**:

```python
#: The operator's size preference, already clamped to [APPETITE_MIN, APPETITE_MAX].
#: 1.0 means "the posture the ladder alone would choose" - a definition, not a
#: preference. The agent sees it, the Coach cannot reach it, and nothing in this
#: module may set it.
appetite: float = 1.0

@property
def realised_appetite(self) -> float:
    """What the appetite actually came to on the book scope, after BOOK_CEILING.

    Set 2.0 at MATURE and the book cap pins at 0.35, so the realised appetite is
    1.40 and turning the knob further does nothing. A number the operator set and
    the system silently absorbed is exactly the bug class this project keeps
    finding, so it is computed and shown rather than implied.
    """
    return self.book_cap / TIERS[self.tier]["cap"]
```

No second stored copy - the earned cap is always `TIERS[self.tier]["cap"]`.

**`reason` must scale too, and this is not cosmetic.** `reason` is built from the tier table at
`competence.py:329-338` and fed verbatim to the decide agent at `tick.py:417-422`. Applied at 0.50
on the live posture it currently reads:

```
SCALE - 49 resolved, attribution unmeasured (0 verdicts), Kelly x0.08
```

Earned Kelly is 0.16. The agent is told it **earned** a posture the operator chose, and
`next_tier_needs()` then promises more size for more resolved theses - a promise appetite has
silently halved. State both:

```
SCALE - 49 resolved, attribution unmeasured (0 verdicts), Kelly x0.16 earned,
x0.08 applied at 0.50x risk appetite (operator-set)
```

Append `" - clamped from 2.00x"` when the input was out of range, and
`" - book capped at 35%, realised 1.40x"` when `BOOK_CEILING` bound.

### 2.4 What the sizer reports

`SizingDecision` gains `binding: str` - the constraint that actually set the size: `"Kelly"`,
`"exploration floor"`, `"position ceiling"`, `"one contract (indivisible)"`, `"portfolio cap"`,
`"<TICKER> concentration"`, or `""` on a refusal.

Not appetite-specific machinery: it is the observable the whole sizing stack has been missing. It
answers I-68's question (*why did it size that way?*), it makes the lever's liveness visible
without a second code path, and `docs/risk_appetite_explorer.html` already proved it is the right
field by computing it independently (line 696). No caller destructures `SizingDecision`
positionally, so appending the field is safe.

### 2.5 What this lever cannot move, and why that is by design

Realized book risk is trade **frequency x size**. Appetite moves size only. `size_position` is
consulted in 2 of 89 decide cycles (I-68) - the other 87 are prose, and the decision to trade or
decline is made there, upstream of every multiplication this lever performs. Turning appetite to
0.25 does not make the agent decline more; turning it to 2.0 does not make it find more setups.
That is not a gap to close - a lever that touched selectivity would be a second EV gate wearing the
first one's name, and research §4 already refuses that on both axes (lower expected return, higher
variance, simultaneously). But it means an operator expecting "less risk" to mean "the agent trades
less often" will be surprised, so WU-4.1's prompt clause states the boundary in the one place the
agent's prose-side behaviour is actually shaped: *"scales size, not selectivity - what is worth
trading is unchanged."* Say the same thing in the `risk_appetite` config comment.

The mirror of this limit is the lever's best argument: because the exploration floor binds on
every trade this book's structure class has ever produced (§1.2, §1.3), and the floor is now
`book_cap x SEED_SHARE`, appetite is **linear over the entire realized trade population**, not just
over a theoretical Kelly region the book rarely reaches. A mechanism that only moved the rare
Kelly-bound trade would satisfy the invariants in §3 while doing nothing to the book anyone can
observe; this one does not have that gap.

---

## 3. The invariants (the contract)

All measured passing under the proposed design. Each maps to a named test in WU-7.

| # | Invariant | Pillar |
|---|---|---|
| I1 | `position_cap <= underlying_cap <= book_cap` at every rung x every appetite | 4 |
| I2 | Every posture field is non-decreasing up the ladder, at every appetite | 4 |
| I3 | **Size** is non-decreasing up the ladder, at every appetite - *more evidence never means less size* | 4 |
| I4 | Which constraint binds is **invariant** under appetite (§1.3) | 4 |
| I5 | Appetite cannot change the sizer's regime: EXPLORE at 2.0x still has `uses_kelly is False`; MATURE at 0.25x still uses Kelly | 4 |
| I6 | Max appetite on a structure with **no claimed edge** returns 0 contracts - the EV gate is upstream of every multiplication | 1 |
| I7 | `book_cap` never exceeds `BOOK_CEILING`, at any rung, on any input including garbage | 4 |
| I8 | `max(TIERS[*].kelly) x APPETITE_MAX <= 0.50` (half Kelly), asserted on the live tables | 4 |
| I9 | 0 / negative / 100 / non-finite clamps to the boundary **and the clamp is reported** | - |
| I10 | Drawdown demotion cuts the next trade by >50% (it cuts 11% today) | 4 |
| I11 | `appetite=1.0` reproduces every pre-change number **except** `seed_fraction` above EXPLORE | - |

**Balanced pressure** (testing principle 4): I3/I5 push toward more size, I6/I7/I8 toward less.
Ship them together. Pin **relationships, never levels** - do not add a test asserting "2.0x gives
4.27%".

**I3 must not measure integer contracts.** That is what let §1.4's blind spot exist: the
`contracts < 1 -> 1` promotion flattens every rung at a small per-contract risk. Assert on
`fraction_of_equity`, or choose a per-contract risk small enough that rounding cannot mask a rung.

### Measured response surface

Fair-priced SPY 766/758 put spread, $100k equity, stated 39.6%, conditional payoff 1.88. Each rung
assessed at the n that earns it; because the floor binds everywhere, these are n-independent.

```
  rung            0.25x     0.50x     0.75x     1.00x     1.25x     1.50x     1.75x     2.00x   span
  EXPLORE         0.50%     1.01%     1.51%     2.01%     2.51%     3.27%     3.77%     4.27%   8.5x
  ESTABLISH       0.75%     1.51%     2.26%     3.27%     4.02%     4.77%     5.53%     6.53%   8.7x
  SCALE           1.01%     2.01%     3.27%     4.27%     5.28%     6.53%     7.54%     7.54%   7.5x
  MATURE          1.26%     2.51%     4.02%     5.28%     6.78%     7.54%     7.54%     7.54%   6.0x
                                                                    ^ binding: exploration floor, everywhere
```

Read the flat tails: **above 1.75x at SCALE and 1.40x at MATURE the knob does nothing** -
`BOOK_CEILING` has absorbed it. That is why `realised_appetite` exists.

---

## 4. Work units, in order

> **WU-2 and WU-3 must land in ONE commit.** WU-2 alone raises the exploration floor at three of
> four rungs and silently multiplies live position size. Research §5 says this explicitly ("it must
> ship as a pair, not as a drop-in") and §1.4 shows the suite will not catch it.

### WU-0 - Clear the landmine, then reproduce the measurements

**First, before touching `competence.py`:** `test_regressions.py:1181` asserts
`"date" not in inspect.getsource(competence.assess)`. Plain substring. Any comment containing
*update, candidate, validate, mandate, outdated, consolidate* fails it, with an error message about
calendars. Confirmed by writing `# The operator can update this between runs` inside `assess` and
watching `test_the_ladder_has_no_calendar_in_it` fail.

Tighten it to a word-boundary check (`re.search(r"\bdate\b|\bdeadline\b", src)`) in its own commit,
keeping its docstring. It is guarding a real thing (D-048); it is just guarding it with a substring.

**Then:** update `tests/scaffold_risk_appetite.py` to model the corrected design - one clamp, floor
derived from the already-scaled `book_cap`, `FLOOR_CEILING` deleted. Confirm §1's tables and §3's
surface reproduce. The scaffold is not collected by pytest (D-079); it is the trader-readable table
you look at to ask "is this balanced".

**Watch for the double-scale bug.** `seed_fraction` must be `book_cap * SEED_SHARE` where
`book_cap` is **already** appetite-scaled. Multiplying by `a` again gives an `a^2` response and is
the easiest mistake here to make and not notice. I4 catches it (the binding constraint would move).

### WU-1 - `SizingDecision.binding` (no behaviour change)

`src/trdrbot/sizing.py`:

```python
@dataclass
class SizingDecision:
    ...
    #: Which constraint actually set the size. The sizing stack could say what it
    #: decided and never which of five limits decided it, so a lever moving an
    #: inert constraint was indistinguishable from one that worked
    #: (research_risk_appetite.md SS1.1). Empty on a refusal.
    binding: str = ""
```

Set it where `frac` is decided (lines 252-277):

```python
    if posture is not None and not posture.uses_kelly:
        frac = min(posture.seed_fraction, ceiling)
        binding = ("exploration floor" if frac == posture.seed_fraction
                   else "position ceiling")
    else:
        ...
        kelly_frac = 0.0 if full is None else full * mult
        frac = max(kelly_frac, floor)
        binding = "Kelly" if kelly_frac >= floor else "exploration floor"
        if frac > ceiling:
            frac, binding = ceiling, "position ceiling"
```

Then: the `contracts < 1 -> 1` promotion (line 289) sets `"one contract (indivisible)"`; inside the
caps loop (line 316) set `binding = label` **only when the cap actually reduces `contracts`**, not
on every pass. Append it to `explain()` and journal it in `local_tools._journal_sizing`.

**Test:** `test_the_sizer_names_the_constraint_that_set_the_size` - one case per branch through the
real `size_position`. **Mutation-verify:** hardcode `binding = "Kelly"`, watch it fail.

*Ships alone. Nothing depends on it, and everything after it becomes measurable.*

### WU-2 + WU-3 - The floor derives, and the lever exists (ONE commit)

**`src/trdrbot/competence.py`**

1. Replace `SEED_FRACTION = 0.022` with a share, and leave the number 0.022 nowhere:
   ```python
   #: The exploration allocation as a share of the tier's book cap - the same move
   #: D-098 made for the other three scopes, at the share that reproduces today's
   #: constant EXPLORE floor exactly: 0.10 x 0.22 = 0.022.
   #:
   #: It replaced ONE constant across all four rungs, which made the drawdown
   #: circuit breaker a breaker with no contacts: an 11% drawdown demoted MATURE
   #: to EXPLORE and cut the next trade by 13%. It now cuts it by 62%.
   SEED_SHARE = 0.22
   ```

2. Add the constants and thread the parameter:
   ```python
   #: The operator's size preference. Two halvings down, one doubling up - see
   #: research_risk_appetite.md SS6: turning it down is nearly free, turning it up
   #: needs ~70% confidence that the edge is real.
   APPETITE_MIN, APPETITE_MAX = 0.25, 2.0

   #: An absolute share of equity in defined max loss that NO appetite may cross.
   #: The lever moves the growth/variance tradeoff; it must never move the ruin
   #: bound. The ONE runtime clamp - plan_risk_appetite.md SS1.1 explains why the
   #: research doc's other two are a test and a deletion instead.
   BOOK_CEILING = 0.35

   def assess(*, resolved, reliability, positions, equity, high_water,
              effective=None, appetite: float = 1.0) -> Competence:
   ```

3. Clamp **once**, inside `assess`; derive the floor from the scaled cap; scale `reason` per §2.3.

4. Add the `appetite` field and the `realised_appetite` property.

**`src/trdrbot/config.py`**
```python
@property
def risk_appetite(self) -> float:
    """The operator's size preference. 1.0 = the posture the competence ladder
    alone would choose. Clamped in `competence.assess`, deliberately NOT here:
    one clamp, at the point of use, so no caller can hold an unclamped value and
    no second place has to agree about the range."""
    return float((self.raw.get("trading") or {}).get("risk_appetite", 1.0))
```
Absent means 1.0, never 0. A non-numeric value raises at `config.load()` - process start, before
any trading, which is where a config typo should stop things.

**`config.yaml`**, under `trading:`, in the style of the file's other blocks:
```yaml
  # Operator risk appetite. 1.0 = the posture the competence ladder alone would
  # choose; clamped to [0.25, 2.0]. It scales the book cap (and through it the
  # per-name cap, the per-position cap and the exploration floor) and the Kelly
  # multiplier. It scales SIZE ONLY: the EV gate sits upstream of it, so no
  # setting can buy a trade that is not worth taking (research SS4).
  #
  # Takes effect on the NEXT TICK under run.sh (a fresh process per tick); needs a
  # RESTART under `trdrbot run`, which loads config once before its loop.
  #
  # 0.50 is not neutral, and that is the point. Deriving the exploration floor
  # from the tier (D-099) raises it from a flat 2.2% to 4.4% at SCALE, and 0.50 x
  # that is 2.2% - so this commit lands the MECHANISM with the live book's size
  # unchanged, and any behaviour change afterwards is a bug rather than the knob.
  # Research SS6's belief table says a book at a coin flip on whether its edge is
  # real belongs at the MINIMUM; moving to 0.25 is a separate one-line commit.
  # See plan_risk_appetite.md SS8.
  #
  # NOT a Coach lever, ever: the Coach writes only data/state/levers/, and the
  # measured/measurer rule (notes/015) forbids anything it can move from scoring
  # its own trial. This is the principal's preference, not the agent's.
  risk_appetite: 0.50
```

**`src/trdrbot/tick.py:704`** - pass it, and journal all three numbers:
```python
posture = competence.assess(..., appetite=config.risk_appetite)
...
journal.append("competence", ...,
               appetite=posture.appetite,               # applied, after clamping
               appetite_config=config.risk_appetite,    # requested
               realised_appetite=round(posture.realised_appetite, 4))
```
A reader diffing them sees both the clamp and the ceiling absorption. Rows before this commit carry
no `appetite` key - absent means pre-lever, and the journal is append-only.

**Test:** `test_the_coach_cannot_reach_risk_appetite` - assert `"risk_appetite"` is not in
`coach_pkg.state.LEVERS` and that nothing under `coach_pkg/` writes `config.yaml`. The exclusion is
structural today, but `state.py:115` carries a three-step "TO REGISTER A NEW LEVER" recipe, and one
contributor following it is all it takes. Add a one-line caveat beside that recipe too.

### WU-4 - The surfaces (six of them)

1. **The decide prompt** (`tick.py:417-422`). The scaled `reason` from §2.3 does most of the work.
   Add **one clause**, and only when `posture.appetite != 1.0`:
   > `These caps carry an operator risk appetite of 0.50x. It scales size, not selectivity - what is worth trading is unchanged.`

   No new section, no editorialising. `size_position` is consulted in 2 of 89 decide cycles (I-68),
   so the prompt is where a risk posture actually reaches behaviour today - which is exactly why it
   must state the number and stop. "Be bolder" would be a second lever wearing the first one's
   name, and would invite the agent to reason around the EV gate (research §4).

2. **The refusal message** (`sizing.py:293-298`). When one contract exceeds the position ceiling
   *and* appetite is below 1.0, say so. Today the operator reads `Position too large for the
   account` and cannot tell an oversized structure from a knob they turned down. Measured: a
   $2,600/contract structure at SCALE sizes 1 at 0.50x and refuses at 0.25x. Port the explorer's
   own sentence (line 674): *you would need about $X of equity at this appetite and tier.*

3. **Three docstrings in `sizing.py:32-60`** become factually false. `MAX_FRACTION`,
   `PER_UNDERLYING_MAX_AT_RISK` and `PORTFOLIO_MAX_AT_RISK` each claim to be "the EXPLORE rung's
   value". At appetite 0.50 the EXPLORE rung is 2.5% / 4% / 5%. Amend to "the EXPLORE rung's value
   **at appetite 1.0**".

4. **The over-cap book** (`tick.py:_render_book_risk`, line 218). Sizing gates NEW risk and never
   liquidates, so cutting the appetite below current usage leaves an over-cap book that unwinds
   naturally. Correct, and invisible: add a line when `at_risk > cap * equity` saying the cap is a
   *target on the way down*, nothing is being force-closed, and new risk is refused until it
   unwinds. **Do not add liquidation** - a preference dial that submits market orders is not a
   preference dial.

5. **`site_export.py:684-692`** exports `kelly_multiplier` / `seed_fraction` / `book_cap` from the
   journal row under the key `"competence"`. They are now appetite-scaled, so at 0.50 the website
   shows a 10% book cap for an agent that earned 20% - the ladder appearing to demote with no
   drawdown and no tier change. Add `appetite` and `realised_appetite` and label the scaled numbers
   as applied, not earned.

6. **`health.py` section 4** ("absence that quietly loosens a constraint") - add its mirror image, a
   knob that is *set* and quietly does nothing. From the latest `competence` row, warn when
   `appetite != 1.0` and `realised_appetite != appetite`. One `if`. This is the project's designated
   silent-no-op detector and this is a designated silent-no-op risk.

### WU-5 - `trdrbot risk [APPETITE]`

The operator must pick a number in a range whose consequences are not obvious, and "did my edit
take effect?" otherwise has no answer short of reading the journal.

Deterministic only - no Monte Carlo in production code. It composes `config.load`,
`calibration.score`, `competence.assess` and `sizing.size_position`; the stochastic half of the
question lives in the explorer, where it belongs.

```
$ uv run trdrbot risk 0.75

Risk appetite    0.50x  ->  0.75x          (config.yaml: trading.risk_appetite)
Competence       SCALE - 49 resolved, attribution unmeasured, Kelly x0.160 earned

                          now (0.50x)        proposed (0.75x)
  book cap                10.0%  $10,435      15.0%  $15,652
  per-name cap             8.0%   $8,348      12.0%  $12,522
  per-position cap         5.0%   $5,217       7.5%   $7,826
  exploration floor        2.2%   $2,296       3.3%   $3,443
  Kelly multiplier        x0.080              x0.120
  realised appetite        0.50x               0.75x

  next trade, on a structure like the book's ($256/contract):
       8 contracts (2.20%)          ->      13 contracts (3.30%)
       binding: exploration floor   ->      binding: exploration floor

  book carries $2,052 (1.97% of equity) - 20% of the cap now, 13% proposed.
  100% of it is SPY, against a per-name cap of $8,348.

To apply: set `trading.risk_appetite: 0.75` in config.yaml.
  run.sh / launchd: next tick.   `trdrbot run`: restart it.
```

No argument prints the current column only. Take the per-contract risk from the most recent
position (`max_loss_usd / contracts`); if the book has never traded, omit that block and say so.

**No `--set` flag.** `config.yaml` is 200 lines of load-bearing comments and a `yaml.dump`
round-trip destroys every one of them. Print the line to change.

### WU-6 - Reduce four copies of this policy to one

See §6.

### WU-7 - Tests, and the record

Tests in `tests/test_regressions.py` beside the existing ladder invariants, each naming its pillar
and the incident it traces to (testing principle 3). Prefer **one invariant over ten examples** -
I1-I8 are properties over the whole rung x appetite space.

**Every one mutation-verified** (testing principle 1): revert the fix, watch the named test fail,
write that sentence into the ledger entry. Specifically: reverting `seed_fraction = book_cap *
SEED_SHARE` to a flat constant must break I10, and removing the `BOOK_CEILING` clamp must break I7.
**Re-read §1.4 before believing a green run.**

Then:
- **`specs/decisions.md` D-099** - the derived floor, the lever, the single clamp, the two clamps
  that became a test and a deletion, the shipped 0.50 and its argument, and §1.4's blindness as the
  reason the new tests exist.
- **`specs/issues.md`** - amend **I-69** (re-sequenced, no longer a prerequisite, with §1.2's
  crossover table); amend **I-66** (the band widened, measured); open **I-70**: *the exploration
  floor binds above Kelly at every rung, so `SEED_SHARE = 0.22` now sets the size of every trade
  this book makes, and it has never been fitted to anything* (research §10 already flags it).
- **`docs/research_risk_appetite.md`** - a dated amendment block pointing here. Do not rewrite its
  measurements; they were correct for the design it tested.

---

## 5. Edge cases

Each was **run**, not asserted.

| # | Case | Behaviour | Mitigation |
|---|---|---|---|
| E1 | `risk_appetite` absent | 1.0 - neutral, never OFF | WU-3 |
| E2 | `risk_appetite: "bold"` | `float()` raises at `config.load()`, before any trade | WU-3. Deliberately uncaught: a config typo should stop a process, and config is read at process start so it cannot kill a tick mid-flight |
| E3 | `0`, `-5`, `100` | clamps to 0.25 / 0.25 / 2.0, and `reason` says so | I9 |
| E4 | 2.0x at MATURE | book pinned at 35%, **realised 1.40x** - turning it further does nothing | `realised_appetite`, WU-4.6, I7 |
| E5 | Appetite cut while the book exceeds the new cap | new risk refused, open positions untouched, unwinds naturally | WU-4.4. **Never liquidate** |
| E6 | Low appetite on an expensive structure | position ceiling refuses. $2,600/contract at SCALE: 1 contract at 0.50x, refused at 0.25x | WU-4.2 - the refusal must name the appetite |
| E7 | Appetite raised mid-position | open positions unaffected, new ones size larger | none needed |
| E8 | Drawdown demotion under appetite | 11% drawdown, MATURE -> EXPLORE: **62% cut** (13% today). Never raises a cap | I10, I2 |
| E9 | 2.0x with no claimed edge | **0 contracts** - the gate reads the stated probability, upstream of every multiplication | I6 |
| E10 | 2.0x at EXPLORE | `kelly_multiplier` stays 0.0, `uses_kelly` stays False - appetite cannot switch regime | I5 |
| E11 | Double-scaling the floor | `a^2` response - the easiest mistake here | WU-0's warning; caught by I4 |
| E12 | Journal rows across the change | pre-lever rows have no `appetite` key; absent means pre-lever. Append-only | WU-3 |
| E13 | The live book is **100% SPY** | at 0.50x the per-name cap is $8,348 - the concentration cap will bite before the book cap as positions accumulate | surfaced by WU-5 |
| E14 | Attribution's first verdicts land below 60% | SCALE -> ESTABLISH, floor 1.65% - a 25% cut below today's. **This is the brake working**, not a regression; §8 says so out loud | §8 |

---

## 6. Four copies of this policy exist. Reduce them to one.

| # | Copy | Where | Status |
|---|---|---|---|
| 1 | production | `src/trdrbot/{competence,sizing}.py` | the truth |
| 2 | Python fork | `tests/scaffold_risk_appetite.py:120-147, 395-413` | patches `Competence` via `replace` because production has no appetite |
| 3 | JavaScript fork | `docs/risk_appetite_explorer.html` `<script>` | **already drifted**, see below |
| 4 | Svelte fork | `web/src/lib/components/CompetenceLadder.svelte:8-13` | hardcoded caps + wrong prose, on the live `/scoreboard` |

**Copy 2** disappears the moment WU-3 lands: delete `with_appetite` and `tier_floor` from the
scaffold and call `competence.assess(appetite=...)` directly.

**Copy 4** hardcodes `cap: 0.1/0.15/0.2/0.25` and the prose *"Fixed 2.2% exploration allocation"* -
which the derived floor makes wrong at three of four rungs - then renders
`Kelly x{competence.kelly_multiplier}` from the **appetite-scaled** snapshot right beside the
**hardcoded earned** caps. Two meanings of one number, on a public page. Fix: drive the rungs from
`snapshot.json` (extend `site_export` to ship the ladder table) and rewrite the EXPLORE prose as a
derived share. If that is too large for this change, at minimum correct the prose and label the
Kelly figure as *applied*.

### Copy 3: the explorer

Its header comment claims the policy is *"ported from src/trdrbot/sizing.py"*. The appetite half of
it has no counterpart in `src/` at all - it is ported from a test scaffold. It has already drifted:

| # | Divergence | Consequence |
|---|---|---|
| D1 | `DATA.tiers[*].kelly` back-solves to **three different `resolved` counts** (10 / 29 / 50) | the ESTABLISH row is a fabricated agent presented as a rung of one ladder |
| D2 | The derived-floor branch applies `floorCeiling = 0.05`; the Python it was ported from does not, and reaches 5.5% at MATURE | the page's headline second mode understates the MATURE floor by 10% |
| D3 | Demotion re-looks-up a frozen tier row instead of re-assessing at the same `resolved`. SCALE->ESTABLISH uses 0.0625 where Python gives 0.0829 | every drawdown path in the 400-path simulation under-sizes |
| D4 | The `#verify` badge covers 9 reference calls: no `establish` rows, no `derived`-mode rows, one equity | it prints **"verified against Python"** through all of D1-D3 |
| D5 | `DATA.tiers.scale.kelly = 0.149143` was baked at n=29; the live book is at **n=49**, kelly **0.1604** | already stale today, and it goes stale again every time a thesis resolves |

D4 is the real defect: a verification badge that structurally cannot fail is worse than no badge -
it converts an unverified page into one that claims verification.

### The fix: a generated policy table, and the page does arithmetic

The insight that makes this cheap: **`frac` is equity-independent.**
`min(max(kelly_frac, floor), ceiling)` uses no equity - only
`contracts = floor(equity x frac / per_contract)` does. So the policy is a small lookup table and
everything else on the page is arithmetic over it.

**`scripts/gen_risk_explorer.py`** (new; `scripts/` already holds `publish.sh`) emits two blocks
between markers, because they have **different truth conditions**:

```
DATA.policy   -- derived from CODE. Pinnable exactly.
  [tier][appetiteStop][drawdownState] -> {frac, binding, book, pos, name, seed,
                                          kelly, realised}
  4 tiers x 15 appetite stops x 3 drawdown states = 180 rows, ~5 KB
  + built_at_resolved: {tier: n}    <- D5: the n each rung was assessed at
  + as_of: "YYYY-MM-DD"

DATA.market   -- derived from DATA that moves. A dated snapshot, labelled as one.
  {structure, cal, pools:{right,wrong}, poolStats}
```

Each row is produced by calling the **real** `assess` at a stated `resolved`, and the drawdown
states by passing a real `equity`/`high_water` ratio rather than by looking up a neighbouring tier.
That kills D1, D2 and D3 structurally, and `built_at_resolved` makes D5 *disclosed* instead of
silent - the page displays which agent each rung represents.

**The JS then contains no policy:**
```js
const row = DATA.policy[tier][aIdx][ddState];
let contracts = Math.floor(eq * row.frac / per);
if (contracts < 1) contracts = (per <= row.pos * eq) ? 1 : 0;
```
Delete `shrinkProbability`, `kellyFraction`, `postureFor`, `sizePosition`, `tierAfterDrawdown`,
`DATA.clamps`, `DATA.tiers`, `DATA.demote`, `DATA.refs` and the badge machinery. Drawing
(lines 447-614), the RNG, path bookkeeping and DOM wiring are untouched - they never held policy.

**Also delete:** the `floorMode` toggle (lines 208, 754) - after WU-2 there is one floor rule, and a
page modelling a mode the system does not have is modelling something else. The before/after
argument belongs in the research doc. And the dead payload: `DATA.structure.debit/maxProfit/
maxLoss/breakEven`, `DATA.tiers[*].pos/name_cap`, `DATA.poolStats[*].ev/pwin/b`, and the entire
`pools.neutral` array - ~40% of the blob, emitted and never read; `pools.neutral` alone is 500 dead
floats.

**The anti-drift guard replaces the badge, and this is the part that matters:**

```python
def test_the_published_explorer_still_matches_the_sizer_it_claims_to_model():
    """Two copies of one definition drifting apart is this project's most familiar
    bug, and this one is on the public website. Modelled on
    test_the_attributable_gauge_agrees_with_the_ladder_it_mirrors."""
```

Parse `DATA.policy` out of the committed HTML and assert it equals
`gen_risk_explorer.build_policy(resolved=<the stamped built_at_resolved>)`. **Rebuild at the
stamped n, not the live one** - otherwise the test fails on a clean tree the day after publish,
every time a thesis resolves (D5). The test then pins **code** drift, which is what it is for, and
stays silent on **data** drift, which regeneration handles. Offline, fast, no network.

**Performance, incidentally:** the page currently makes ~338,000 `sizePosition` calls per slider
`input` event. Against a lookup table that becomes ~7,000 multiplications.

**Publishing is a separate, human act.** Regenerate locally and stop. `scripts/publish.sh` syncs
`docs/*.html` to the live site; deploying is outward-facing and is not part of this plan.

---

## 7. Deliberately rejected

- **A per-dimension knob set** (size / frequency / concentration / stops). Four knobs is four ways
  to produce a posture nobody chose. Research §8.
- **Letting appetite touch the EV gate.** Bets below `p > 1/(1+b)` have *lower* return and *higher*
  variance - strictly worse on both axes, so there is no curve to sit on. Research §4, PILLAR-1.
- **Making appetite a Coach lever.** The measured/measurer rule (notes/015).
- **Named postures** (`cautious`/`bold`). Aliases can be added later over the same number; first
  puts two representations of one setting on disk. Research §8.
- **`with_appetite()` as a post-hoc transform.** §2.2 - the "wired to nothing" bug class by
  construction.
- **Per-tick config reload in `_run_loop`.** §2.1 - one line, blast radius covering every key. And
  `run.sh` already gives per-tick reads for free in the mode that matters.
- **Forced liquidation when the appetite is cut.** WU-4.4.
- **A `--set` flag on `trdrbot risk`.** WU-5 - a `yaml.dump` round-trip destroys the config's
  comments.
- **`KELLY_CEILING` / `FLOOR_CEILING` as runtime clamps.** §1.1.
- **Fixing I-69 first.** §1.2 - the coupling the research assumed does not reach size.
- **A demotion-only brake** - scaling the seed floor by 0.5 per rung dropped, leaving the earned
  base at 2.2%. It is genuinely cheaper: it buys the 62% drawdown cut with no base increase and
  without widening I-66. **Rejected because it fixes the brake and not the ladder.** Under a flat
  floor, EXPLORE / ESTABLISH / SCALE still size *identically* (research §1.2) - promotion changes
  the tier and not the size. It also adds a constant and a code path where `SEED_SHARE` removes a
  constant and unifies with D-098's existing derivation, and it makes the floor depend on hidden
  state (how far you fell) that the tier does not carry. Price it if I-70 ever forces the question.
- **Fixing I-70 here.** §1.3 - measure it, record it, decide it deliberately. Do not invent a second
  table inside a change that already moves the base.

---

## 8. The one human decision

Everything above is determined. This is not.

**What should `trading.risk_appetite` ship at?** Measured under the corrected design - 500 paths x
50 trades, SPY's own resampled returns, drawdown demotion live in the loop, SCALE rung:

| appetite | RIGHT: median | mean DD | P(DD>20%) | WRONG: median | mean DD | P(DD>20%) |
|---|---|---|---|---|---|---|
| **0.25x** | $106,803 | 7.3% | **0.0%** | $91,139 | 10.8% | **0.0%** |
| **0.50x** | $109,795 | 12.9% | 2.6% | $87,267 | 18.2% | 33.8% |
| 1.00x | $113,683 | 21.6% | **53.8%** | $77,692 | 31.2% | 92.8% |
| 2.00x | $120,007 | 35.4% | 99.0% | $60,746 | 50.7% | 100.0% |

Expected log growth under a belief mixture - *how sure are you the edge is real?*

| belief q | 0.25x | 0.50x | 0.75x | 1.00x | 1.50x | 2.00x | best |
|---|---|---|---|---|---|---|---|
| 30% | −0.034 | −0.062 | −0.093 | −0.130 | −0.203 | −0.285 | **0.25x** |
| 50% | −0.007 | −0.018 | −0.028 | −0.045 | −0.083 | −0.132 | **0.25x** |
| 60% | +0.006 | +0.005 | −0.000 | −0.009 | −0.031 | −0.064 | **0.25x** |
| 70% | +0.019 | +0.027 | +0.032 | +0.033 | +0.025 | +0.005 | **1.00x** |
| 80% | +0.035 | +0.057 | +0.072 | +0.086 | +0.091 | +0.092 | **2.00x** |

**0.50 - recommended for this commit.** It reproduces the live book's current position size exactly
(`0.20 x 0.50 x 0.22 = 0.022`, today's flat floor at today's rung), so the mechanism lands
behaviour-neutral and *any* change in the book afterwards is a bug rather than the knob. That is the
discipline D-098 already ran on when it chose shares making the EXPLORE rung byte-identical.

**It reproduces today's size at today's rung. It does not pin it there, and must not be sold as if
it does.** The whole point of the derived floor is that size now moves with the rung. When
attribution produces its first five verdicts below 60%, the book demotes to ESTABLISH and the floor
becomes 1.65% - a 25% cut. **That is the brake working**, and it is the change being bought.

**0.25 - what the evidence says.** At a coin flip on whether the edge is real the optimum is the
minimum, and it stays the minimum to 60% belief. This book has 49 resolved forecasts, **zero
attributed positions** (`attributable_rate` is `None`, 0 verdicts), and therefore no resolved
evidence at all that its theses carry edge. Note also that at 1.0x the derived floor
makes a >20% drawdown **more likely than not even when the thesis is right** - so 1.0 is not a safe
default under this design, which is itself a reason "neutral" and "correct" are different words.

**Why the preference lives in the appetite and not in `SEED_SHARE`.** `SEED_SHARE = 0.22` with
`appetite = 0.50` gives numerically identical results at every rung to `SEED_SHARE = 0.11` with
`appetite = 1.00`. The choice is representational, and it matters: 0.22 is *derived*
(`SEED_FRACTION / TIERS[EXPLORE]["cap"]`) and has a provenance, while 0.11 would be *fitted* to
today's tier, which will change. Putting the preference in the constant hides a choice inside a
derivation. Keep the geometry in `SEED_SHARE` and the preference in `risk_appetite`.

**Recommendation: ship 0.50, then move to 0.25 as a separate one-line commit** once WU-1's
`binding` field and the journalled appetite have confirmed the mechanism is live. Two commits, each
with an unambiguous effect. Revisit when attribution produces its first five verdicts and the belief
column stops being a guess.

Neither candidate puts the book over cap: it carries $2,052 (1.97% of equity) against a 5% book cap
even at 0.25x. But see E13 - the book is 100% SPY, so the per-name cap binds first.

**A mechanism check, separate from the number.** A tournament against five alternative mechanisms
(equity scaling, applying the scalar inside the sizer instead of the posture, a tier-shift dial, a
fully configurable tier table, and a runtime-mutable state file) confirmed this shape over all of
them - each alternative failed a different invariant (ruin bound, single-application-point honesty,
tier-meaning corruption, invariants-by-construction, or the Coach's structural wall), while this
design is the only one honest on every surface and a net remover of constants. See §2.5 for the one
limit every size-side mechanism shares (it moves size, not selectivity) and for why the floor
binding on every real trade makes this design's linearity a live property of the book, not a
theoretical one.

---

## 9. Verification checklist

- [ ] `test_the_ladder_has_no_calendar_in_it` tightened to a word boundary **first**, in its own
      commit (WU-0)
- [ ] `uv run pytest` green - **and §1.4 re-read before treating that as evidence**
- [ ] Every fix **mutation-verified**: reverted, named test observed failing, sentence written into
      `issues.md` / `decisions.md`
- [ ] `uv run python tests/scaffold_risk_appetite.py` reproduces §3's response surface, and no
      longer defines `with_appetite`
- [ ] `uv run trdrbot risk` and `trdrbot risk 1.0` run against the live book
- [ ] `uv run trdrbot health` reports no new findings on the live journal
- [ ] `uv run trdrbot tick` once: the `competence` row carries `appetite`, `appetite_config` and
      `realised_appetite`; the decide prompt states earned **and** applied Kelly
- [ ] With `risk_appetite: 1.0`, every number matches the pre-change run **except** `seed_fraction`
      above EXPLORE (I11)
- [ ] The explorer regenerates; its policy-table test passes at the **stamped** n; the page has no
      `shrinkProbability` / `kellyFraction` / `postureFor` / `sizePosition` left
- [ ] `CompetenceLadder.svelte` no longer says "Fixed 2.2% exploration allocation"
- [ ] `git grep -n "SEED_FRACTION"` returns nothing
- [ ] `git grep -n "0\.022"` returns nothing outside a comment
- [ ] Publishing the regenerated page is **not** done - it is a separate human act
