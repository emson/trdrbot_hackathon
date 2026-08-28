# Coding Principles

Universal Python coding principles for codebases written and maintained by LLM
agents working alongside humans. Everything above the Project Overlay is
project-agnostic and portable to any Python project.

**Philosophy: SIMPLE, ELEGANT, FLEXIBLE, ROBUST.** Functional-style Python that
both humans and LLMs can understand, modify, and debug: a functional core of
pure functions, wrapped in a thin imperative shell that does the I/O.

## How to apply this document

- Read the Non-negotiables before writing code. Everything else is a strong
  default: follow it unless it clearly harms clarity in a specific case, and
  say why in the commit or PR description when you deviate.
- Precedence when rules conflict: Project Overlay, then this document, then
  general Python convention.
- Rules that a tool can check are enforced by tools (see Mechanical
  Enforcement). Run the tools; treat their output as authoritative.

## Non-negotiables

1. Every function MUST have complete type hints, public and private, and pass
   the project's type checker in strict mode.
2. Exceptions MUST bubble up from business logic and be caught once at system
   boundaries (CLI entry point, HTTP handler, MCP tool, job runner). Write
   business logic without `try/except`; put the single boundary handler where
   the program talks to the outside world.
3. When modifying or regenerating a function, preserve its existing guards,
   validations, and edge-case handling. Removing a guard is a deliberate,
   stated decision in the PR description, never a silent side effect of a
   rewrite.
4. Every API you call MUST exist. Verify by running the import or the code,
   not by plausibility. If you cannot run it, say so explicitly.
5. Delete dead code. Remove unused functions, commented-out blocks, and
   unreached branches in the same change that makes them dead.
6. Search the codebase for an existing helper before writing a new one, and
   extend the existing pattern rather than duplicating it.
7. Keep the diff scoped to the task. Improvements outside the task's scope go
   in a separate change with their own description.
8. Name every magic number and string as a constant whose name states its
   meaning.

## Core patterns

Each pattern below shows the shape to produce and the shape to replace.
Examples use a generic records-processing domain; substitute your own.

### 1. Compose small functions into pipelines

Functions do one thing and read as a sequence of named steps. Treat roughly 50
lines as a smell threshold: when a function grows past it, look for a named
step to extract.

```python
# GOOD: composite function built from named steps
def process_records(source: Path) -> Summary:
    """Pipeline: load, validate, normalise, summarise."""
    raw = load_records(source)
    valid = validate_records(raw)
    normalised = normalise_records(valid)
    return summarise(normalised)

# BAD: one function mixing loading, validation, and reporting across 200 lines
```

Counter-rule: extract a helper only when it has a truthful name and either gets
reused or removes a full conceptual step from the parent. Shredding a function
into single-use fragments (`_step_1`, `_do_rest`) makes code harder to follow
than one coherent 60-line function. The line limit is a smell, not a law.

### 2. Guard clauses and early returns

Handle rejection and edge cases first, then write the main path unindented.

```python
# GOOD: guard clauses, main path at top level
def validate_username(name: str) -> str:
    if not name:
        raise ValueError("Username required")
    if not name.isidentifier():
        raise ValueError(f"Invalid username: {name!r}")
    return name.lower()

# BAD: nested conditionals that bury the main path
def validate_username(name: str) -> str:
    if name:
        if name.isidentifier():
            return name.lower()
        else:
            raise ValueError(f"Invalid username: {name!r}")
    else:
        raise ValueError("Username required")
```

### 3. Transform data, return new values

Functions take input and return output. Leave arguments unmutated; the caller
must be able to trust that passing a value does not change it.

```python
# GOOD: return a new value
def with_totals(orders: list[Order]) -> list[Order]:
    return [replace(o, total=sum(li.price for li in o.lines)) for o in orders]

# BAD: mutate the argument and return None
def with_totals(orders: list[Order]) -> None:
    for o in orders:
        o.total = sum(li.price for li in o.lines)
```

Local mutation inside a function (building a list in a loop, updating a local
dict) is fine: the rule protects callers, not loop bodies.

### 4. Names reveal intent

Choose names an unfamiliar reader can act on without opening the function.
Spell out domain words; encode units and qualifiers in the name.

```python
# GOOD
def fetch_daily_metrics(account_id: str, start_date: date, end_date: date) -> DataFrame: ...
def rolling_average(values: Sequence[float], window_days: int = 20) -> list[float]: ...

# BAD: reader must open the function to learn what it does
def fetch(a: str, s: date, e: date) -> DataFrame: ...
def calc(v: Sequence[float], w: int = 20) -> list[float]: ...
```

### 5. Constants over magic values

```python
# GOOD: names carry the meaning
SECONDS_PER_DAY = 86_400
DEFAULT_RETRY_LIMIT = 3
REQUIRED_COLUMNS = ["timestamp", "account_id", "amount"]

# BAD: reader must guess what 86400 and 3 mean at each usage site
```

### 6. Same problem, same solution

When several functions solve the same shape of problem, they share the same
structure, argument order, and naming scheme. A reader (or model) who has seen
one can predict the rest.

```python
# GOOD: parallel structure across sources
def fetch_stripe(account_id: str, start: date, end: date) -> DataFrame:
    validate_account(account_id)
    raw = _call_stripe_api(account_id, start, end)
    return normalise_transactions(raw, source="stripe")

def fetch_paypal(account_id: str, start: date, end: date) -> DataFrame:
    validate_account(account_id)
    raw = _call_paypal_api(account_id, start, end)
    return normalise_transactions(raw, source="paypal")
```

Before adding a new variant, read one existing sibling and copy its structure.

### 7. Comments explain why, docstrings state the contract

Write a comment only for a constraint the code cannot show: a non-obvious
decision, an external quirk, a deliberate trade-off.

```python
# GOOD: records the non-obvious decision
# Upstream returns timezone-aware timestamps; we store UTC-naive so values
# from different sources compare directly.
ts = ts.tz_convert("UTC").tz_localize(None)

# BAD: restates the next line
# Convert the timestamp
ts = ts.tz_convert("UTC")
```

Public functions carry a docstring stating purpose, arguments, return value,
and raised exceptions. Keep it a contract, not a narrative. (Projects may
mandate a stricter template in the Project Overlay.)

## Error handling

### Fail fast, catch once

Errors must stay visible: a swallowed exception is invisible to the human, the
logs, and the model debugging the system later.

```python
# GOOD: business logic raises; nothing is hidden
def load_report(path: Path) -> Report:
    if not path.exists():
        raise FileNotFoundError(f"No report at {path}")
    data = json.loads(path.read_text())
    if "rows" not in data:
        raise ValueError(f"Report {path} missing 'rows'")
    return Report.from_dict(data)

# GOOD: one boundary handler where the program meets the user
@app.command()
def report(path: Path) -> None:
    try:
        console.print(render(load_report(path)))
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

# BAD: error hidden behind None; caller and debugger both lose the cause
def load_report(path: Path) -> Report | None:
    try:
        return Report.from_dict(json.loads(path.read_text()))
    except Exception:
        return None
```

### Where try/except belongs

| Location | try/except | Purpose |
|----------|------------|---------|
| Business logic / pure functions | None | Raise on bad input; let errors bubble |
| Adapter around a third-party library | Narrow, one exception type | Translate the library's exception into a domain exception, re-raising with `from` |
| Resource cleanup | `finally` or context manager | Release resources; prefer `with` |
| System boundary (CLI, HTTP, MCP, worker loop) | One handler | Format the error for the consumer, set exit status |

Validation at boundaries is not "defensive code"; it is the fail-fast rule
applied early. The pattern to produce is: validate inputs where data enters the
system, raise immediately on violation, and keep the core free of speculative
`except` blocks.

### Domain exceptions

Define a small hierarchy of specific exception types so callers can catch
precisely, and put the fix in the message.

```python
class ConfigError(ValueError):
    """Raised when configuration is missing or malformed."""

raise ConfigError(
    f"Missing key 'database.url' in {config_path}. "
    "Add it or set the DATABASE_URL environment variable."
)
```

A good error message names the exact thing that was wrong and the exact action
that fixes it.

## Module and file structure

- Group by function family with predictable locations: a reader should guess
  the file from the function name (`fetch_*` lives in `fetch.py`, `save_*` and
  `load_*` in `storage.py`).
- Module layout: module docstring, imports (stdlib, third-party, local),
  constants, public functions, private `_helpers` last.
- The package `__init__.py` exports the public API; consumers import from the
  package root, never from deep paths.

## Anti-patterns specific to LLM-generated code

These are the documented failure modes of model-written code. Produce the
alternative listed for each.

| Instead of | Do this |
|------------|---------|
| Writing a new helper that duplicates an existing one | Search first; extend or call the existing helper |
| Rewriting a function and quietly losing its edge-case handling | Diff against the original; carry every guard forward or justify its removal |
| Calling a plausible-but-unverified method | Run the import or a smoke call; check the installed version's API |
| Commenting out code "in case we need it" | Delete it; version control is the archive |
| Adding compatibility shims, re-exports, or config flags nobody asked for | Implement exactly the requested change |
| Broad `except Exception: pass` to make an error go away | Find the root cause; fix or raise a specific exception |
| Declaring success from reading the code | Run it; paste the actual output as evidence |

## Mechanical enforcement

Everything in this table is checked by tools, not by prose or review comments.
Wire these into pre-commit or CI so violations cannot merge.

| Rule | Tool | Typical configuration |
|------|------|-----------------------|
| Formatting, import order | ruff format / ruff `I` | default |
| Unused code, common bugs, simplification | ruff `E,F,B,SIM,UP` | `[tool.ruff.lint] select` |
| Complete and consistent types | mypy `strict = true` (or pyright strict) | `[tool.mypy]` |
| Tests pass | pytest in CI, required check | branch protection |
| Function complexity | ruff `C901` / `PLR` rules (optional) | threshold per project |

If a rule in this document can be expressed as a lint rule available in your
toolchain, enable the lint rule and rely on it.

## Checklist

Before starting:
- [ ] Read the task and the nearest similar existing code
- [ ] Identify the pattern to follow and the helpers to reuse

During implementation:
- [ ] Type hints on every function
- [ ] Pipelines of small named steps; guard clauses first
- [ ] Constants for magic values; names reveal intent
- [ ] try/except only at boundaries and adapters
- [ ] Existing guards preserved in any function you touched

Before committing:
- [ ] Linter, type checker, and tests all pass; output inspected, not assumed
- [ ] `git diff` reviewed line by line; no dead code, no out-of-scope changes
- [ ] Changelog or docs updated if behaviour visible to users changed

## Quick reference

| Instead of | Do this |
|------------|---------|
| Long multi-purpose functions | Compose named steps, roughly 50 lines each |
| Nested if/else | Guard clauses with early returns |
| Mutating arguments | Return new transformed values |
| try/except in business logic | Let errors bubble; one handler at the boundary |
| Cryptic names | Descriptive names that reveal intent |
| Magic numbers | Named constants |
| Hidden errors (`return None` on failure) | Specific exceptions with the fix in the message |
| New near-duplicate helpers | Reuse and extend the existing pattern |

---

## Project Overlay

Project-specific rules live here and nowhere else. When they conflict with the
sections above, the overlay wins. Fill in on adoption; keep it short.

```markdown
### <project-name> overlay

- Commands: <how to run lint / typecheck / tests here>
- Docstring template: <if stricter than the default contract style>
- Domain naming: <project vocabulary that trumps generic naming>
- Deviations: <each rule above that this project overrides, with the reason>
```
