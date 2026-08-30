# Testing Principles

Universal testing principles for Python codebases written and maintained by LLM
agents working alongside humans. Everything above the Project Overlay is
project-agnostic and portable to any Python project.

**Purpose of the suite:** tests are the executable specification of behaviour
and the verification loop that lets an agent prove its change works. A test
suite that can be gamed, or that tests implementation instead of behaviour,
fails at both jobs.

## How to apply this document

- Read the Non-negotiables before touching any test. Everything else is a
  strong default.
- Precedence when rules conflict: Project Overlay, then this document, then
  general pytest convention.
- The test suite is the arbiter: "the change works" means the relevant tests
  ran and passed, with the output shown.

## Non-negotiables

1. Make failing tests pass by fixing the code under test. Weakening an
   assertion, deleting a test, adding a skip, or special-casing test inputs in
   production code MUST NOT be how a failure is resolved. If a test is
   genuinely obsolete because the specified behaviour changed on purpose, say
   so explicitly in the change description and update it as its own step.
2. For every bug fix, first write (or run) a test that fails for the reported
   reason, then fix the code, then show the test passing. A fix without a
   failing-then-passing test is unverified.
3. Tests MUST NOT call real external services (network APIs, LLM providers,
   production databases). Substitute fakes or mocks at the adapter boundary.
   Tests that intentionally hit real services are opt-in, marked (for example
   `@pytest.mark.slow`), and excluded from the default run.
4. Run the affected test suite before declaring work complete, and report the
   actual command and output. "Should pass" is not a result.
5. Each test MUST be independent: fresh fixtures, no reliance on execution
   order, no shared mutable state between tests.

## What to test

### Behaviour through the public API

Test what the code promises, not how it delivers. Exercise the same entry
points real callers use; a refactor that preserves behaviour should leave the
suite green.

```python
# GOOD: observable behaviour through the public API
def test_register_rejects_duplicate_email(service: UserService) -> None:
    service.register("a@example.com", "pw")
    with pytest.raises(DuplicateUserError):
        service.register("a@example.com", "pw")

# BAD: implementation details; breaks on any internal refactor
def test_register_calls_hash_then_insert(service, mocker):
    spy_hash = mocker.spy(service, "_hash_password")
    service.register("a@example.com", "pw")
    assert spy_hash.call_count == 1
    assert service._pending_inserts[0][0] == "a@example.com"
```

Skip private methods, internal state, and third-party library internals. If a
private helper is complex enough to need direct tests, that is a signal to
promote it to a public function of its own module.

### Real use cases at the right level

- Cover the paths users actually hit: the happy path plus the failure modes a
  caller can trigger (bad input, missing file, empty result).
- Prefer a moderate number of integration tests through the public API, with
  focused unit tests for pure functions (parsing, validation, calculation).
- Test CLIs at the command level with the framework's test runner (for
  example Typer/Click `CliRunner.invoke()`), asserting on exit code and
  output, not by calling the underlying functions directly.
- Leave theoretical scenarios untested; a test for a state the system cannot
  reach is maintenance cost with no information value.

## How to write tests

### Structure: Arrange, Act, Assert

One behaviour per test. Several assertions on the outcome of one action are
fine; several actions each with their own assertions belong in separate tests.

```python
def test_summary_counts_only_valid_rows() -> None:
    # Arrange
    rows = [make_row(amount=10), make_row(amount=-1), make_row(amount=5)]
    # Act
    summary = summarise(rows)
    # Assert
    assert summary.total == 15
    assert summary.skipped == 1
```

### Naming

`test_<unit>_<scenario>_<expected>` so the failure line reads as a sentence:
`test_summarise_negative_amounts_are_skipped`, not `test_summary_2`.

### Error paths

Assert the exception type and a stable fragment of the message, never the
whole string. Exact-string assertions break on harmless rewording.

```python
# GOOD
with pytest.raises(ConfigError, match="database.url"):
    load_config(path)

# BAD: brittle exact match on presentation
with pytest.raises(ConfigError, match=r"^Missing key 'database\.url' in /tmp/x\.yaml\. Add it or set\.\.\.$"):
    load_config(path)
```

### Parametrize pure functions

Table-driven tests document the input space in one place and make gaps
visible. For pure functions with a wide input domain, consider a
property-based test (Hypothesis) asserting an invariant instead of enumerating
examples.

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [("AAPL", "AAPL"), ("aapl", "AAPL"), ("brk-b", "BRK-B")],
)
def test_normalise_symbol(raw: str, expected: str) -> None:
    assert normalise_symbol(raw) == expected
```

### Fixtures and helpers

Shared setup goes in fixtures and `make_*` builder helpers with sensible
defaults, so each test states only what it cares about. Duplicated multi-line
setup across tests is the signal to extract one.

## Test doubles policy

- Substitute at the adapter boundary: replace the HTTP client or the LLM
  adapter, never internal functions of the code under test.
- Prefer fakes (in-memory implementations honouring the real contract) over
  mock objects; prefer mock objects over patching module internals.
- Assert on outcomes, not on the double's internals. Call counts and call
  arguments are implementation details unless the call itself is the contract
  (for example "sends exactly one notification").
- A test whose every collaborator is mocked verifies nothing but the mocks.
  If everything is fake, delete the test or widen it into an integration test.

```python
# GOOD: fake at the boundary, assert on behaviour
def test_report_uses_latest_rates() -> None:
    fake_rates = FakeRatesClient({"USD": 1.0, "EUR": 1.1})
    report = build_report(orders=[make_order(currency="EUR")], rates=fake_rates)
    assert report.total_usd == pytest.approx(110.0)

# BAD: tests that the mock was called; behaviour unverified
def test_report_calls_rates(mocker):
    m = mocker.patch("reports.build._get_rates")
    build_report(orders=[], rates=None)
    m.assert_called_once()
```

## Anti-patterns

Documented failure modes, most of them characteristic of model-written tests.
Produce the alternative listed for each.

| Instead of | Do this |
|------------|---------|
| Editing the assertion until the suite goes green | Fix the code under test; the assertion encodes the spec |
| Deleting or skipping a failing test | Investigate; if behaviour changed on purpose, update the test as an explicit, explained step |
| `assert result is not None` as the only check | Assert the actual expected value or property |
| Tests that re-state the implementation (tautologies) | Compute the expected value independently in the test |
| `time.sleep()` to wait for async or background work | Wait on the condition itself (polling helper, event, `pytest-asyncio`) |
| Asserting on exact formatted output everywhere | Assert on data; keep at most a few presentation tests |
| Ignoring deprecation warnings in test output | Fix the usage now, while the migration is small |
| One giant test covering ten behaviours | One behaviour per test, named for its scenario |

## Maintenance

- Update tests in the same change as the behaviour they specify; a green suite
  after a behaviour change means missing coverage.
- Delete obsolete tests deliberately, stating why they no longer apply.
- Keep the default suite fast enough to run habitually; push slow and
  service-hitting tests behind marks.
- When a bug escapes to production, the fix includes the regression test that
  would have caught it.

## Mechanical enforcement

| Rule | Tool | Typical configuration |
|------|------|-----------------------|
| Suite passes before merge | pytest in CI | required status check |
| No accidental network calls | `pytest-socket` or equivalent | disable sockets by default |
| Slow/real-service tests excluded by default | pytest marks | `-m "not slow"` in default addopts |
| Coverage floor on changed code | coverage.py / codecov | patch threshold, advisory not gamed-for |
| Test file/function naming | pytest discovery + ruff `PT` rules | `[tool.ruff.lint]` |

Coverage is a smoke alarm, not a target: use it to find untested branches,
never write assertion-free tests to raise the number.

## Checklist

Before committing:
- [ ] New behaviour has tests through the public API
- [ ] Bug fixes include the failing-then-passing regression test
- [ ] Full relevant suite run; command and output reported
- [ ] No real services called by default-run tests
- [ ] No assertions weakened and no tests deleted to achieve green
- [ ] Warnings in test output addressed or explained

---

## Project Overlay

Project-specific rules live here and nowhere else. When they conflict with the
sections above, the overlay wins. Fill in on adoption; keep it short.

### trdrbot overlay

- **Test command:** `uv run pytest` (default: fast, offline, no network).
  Contract suite: `uv run pytest -m contract` — real APIs, real keys, run before
  a deploy and after any dependency bump.
- **Network is blocked by default** (`pytest-socket`, `--disable-socket`). A unit
  test that reaches the network is both slow and a lie about what it proves.
  Only `tests/test_contracts.py` re-enables it, per-file and explicitly.
- **Marks:** `contract` (external service, opt-in), `slow`.
- **Deviation from "prefer integration tests":** see the tier table below. The
  general advice assumes bugs live in composition. Ours don't.

#### The four tiers, and why they are weighted this way

We categorised every bug this project has had (~24, all in `specs/decisions.md`).
The finding that shaped this overlay: **9 were found by measuring, 5 by running,
4 by verifying output — essentially none by a unit test catching a logic error
in a pure function.** Our bugs are not miscalculations. They are wrong beliefs
about a seam, and silent no-ops. So the suite is weighted at the seams.

| Tier | File | What it catches | Cost |
|---|---|---|---|
| **Unit / invariant** | `test_regressions.py` | maths, parsing, rules — plus *properties* across the input space | free, always run |
| **Loop smoke** | `test_loop_smoke.py` | emergent bugs visible only when stages run together | free, always run |
| **Contract** | `test_contracts.py` | wrong beliefs about Alpaca / elfmem / LangChain | ~25s, opt-in |
| **Runtime** | `trdrbot health` | silent no-ops in production — *not a test* | continuous |

**Invariant tests earn their place.** A monotonicity check over the whole
competence ladder caught two separate size inversions that had already shipped;
a convergence check (bootstrap vs closed form) caught a 16pp drift bug. Both
found *design* errors, not typos, and neither needed an enumerated example.
Prefer one invariant over ten examples.

**Contract tests are the highest-value new tier.** Each encodes one belief about
the outside world, written so its failure names the belief:
`assert "trades" in r, "price is no longer nested under 'trades'"`. Assert the
SHAPE and the discriminating property, never a live value — "SPY costs 767.61"
is not a contract. When one fails because upstream *fixed* something, say so and
simplify our workaround; that is the test doing its job in the good direction.

**Regression rule, from the non-negotiables and worth restating:** every bug gets
one test named for the bug, carrying the incident in its docstring. Verification
done in a throwaway shell command protects nothing against the next edit.

#### The four pillars, and the rules that keep them from multiplying

Four named invariant classes, greppable as `PILLAR-1`…`PILLAR-4`. They exist because
threshold-flavoured tests contradict each other in pairs ("trade more" vs "refuse more",
"exit fast" vs "don't churn"), and a suite that argues with itself gets ignored.

| | guards | lives in |
|---|---|---|
| **PILLAR-1** economic conscience | on fair pricing, zero size at every regime; the gate opens exactly where EV-after-costs turns positive, under the measure the thesis declares | `test_regressions.py` |
| **PILLAR-2** one measure, seams refuse | `p` and `b` from one measure with friction in every path that can size; a seam that loses either refuses rather than substituting | `test_regressions.py` |
| **PILLAR-3** capital-protection paths | the exit engine driven as price PATHS: whipsaw, corroborated gap, artifact print, stale quote, bleed | `test_exit_and_risk.py` |
| **PILLAR-4** learning integrity | luck never promotes, drawdown demotes, more evidence never means less size, fitted numbers are holdout-vetoed | `test_regressions.py`, `test_coach.py` |

**Pillars pin RELATIONSHIPS, never levels.** An exactness invariant cannot contradict a
monotonicity invariant; two thresholds eventually always do. PILLAR-1 is the worked example:
*the gate opens iff EV-after-costs is positive* is simultaneously "never pay for a coin flip"
and "never starve a real edge" - the two goals a pair of threshold tests would fight over.

Six rules govern admission, and they are the reason the set stays small:

1. **Mutation-verified.** A pillar test ships only with proof it FAILS when its fix is reverted.
   Every I-3x/I-4x entry in `issues.md` carries that sentence because the revert was actually
   performed. Not a published LLM-eval practice - ours, and it has caught real gaps here.
2. **Frozen and additive.** Scenario tables only ever gain rows. A row is never edited to make a
   candidate pass; behaviour changed on purpose is a new row plus a `# CHANGED (WU-x.y)` note
   naming the reason.
3. **Admission needs an address AND an incident.** A new test names the pillar it belongs to and
   the observed failure it traces to. Evals from theory are how suites sprawl.
4. **Balanced pressure.** Any test pushing toward an action ships with its opposite direction, or
   is expressed as an exactness/band invariant. One-sided tests plus a self-improvement loop is
   the fastest route to always-trade or never-trade drift, and this book has measured both.
5. **Saturated tests retire into the canary set** - they stop giving improvement signal and keep
   catching regressions. Never deleted for being boring.
6. **The measured/measurer split is law** (notes/015): nothing the Coach can move may score its
   own trial.

**Scaffolds and pinned tests are both, deliberately** (D-079). `tests/scaffold_*.py` are the
trader-readable tables - the thing you look at to ask "is the stack balanced" - and are not
collected by pytest. The invariants they establish get pinned as real tests. The scaffold caught
two of my own wrong assumptions during phase 4 that no assertion would have surfaced, which is
its whole justification.

#### What we deliberately do NOT test

- LLM output quality or wording. Non-deterministic and not a contract.
- Market outcomes. Unknowable, and a test asserting one would be noise.
- Third-party internals beyond the single belief we depend on.
- States the system cannot reach.

#### Runtime checks are part of the strategy

`trdrbot health` asks of every subsystem: *ran ≥ threshold and produced nothing?*
It found the class of bug tests structurally cannot — a path that runs, returns,
logs healthily, and does nothing. Pair it with the rule that **any early
`return`/`continue` meaning "nothing happened" must journal why.** Tests prove
behaviour on known inputs; health proves the system is doing anything at all on
real ones. Neither substitutes for the other.
