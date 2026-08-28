# Agent-First API Design Principles

Universal principles for designing Python libraries, services, and tools that
LLM agents consume, whether via tool-use, MCP, code generation, or direct
programmatic integration. Everything above the Project Overlay is
project-agnostic and portable to any project.

## The core distinction

A human developer reads tutorials, experiments in a REPL, and builds a mental
model over days. An agent has one interaction loop:

1. Read tool descriptions or documentation (one shot)
2. Decide whether and how to call this API
3. Pass parameters
4. Interpret the result
5. Decide what to do next

Every design decision serves this loop. The enemy is ambiguity, surprise, and
friction at any step. Examples below use a generic document-store client
(`add`, `search`, `sync`, `status`); substitute your own domain.

## Non-negotiables

1. Every operation MUST return a typed result object with an agent-optimised
   `__str__` and a `to_dict()`. Never raw dicts, bare tuples, or `None`.
2. Every library exception MUST carry a `recovery` field containing the exact
   code or command that fixes the problem.
3. "Nothing to do" MUST return an empty result, never raise. Duplicate and
   repeated calls MUST be safe.
4. Tier 1 usage MUST work with zero configuration and zero lifecycle
   ceremony.
5. All public types MUST be importable from the package root.

## Discovery: how agents find and choose operations

### Self-describing API (`guide()`)

External documentation is not accessible at runtime; agents rely on what the
library can tell them about itself. Provide a built-in `guide()` returning an
agent-optimised reference.

```python
client.guide()          # all operations, one line each
client.guide("search")  # structured deep dive on one operation
```

Each entry answers the loop's questions in order:

```python
@dataclass
class AgentGuide:
    name: str      # operation name
    what: str      # one sentence: what does this do?
    when: str      # when should an agent call this?
    when_not: str  # anti-patterns: when is this the wrong choice?
    cost: str      # "Instant" | "LLM call (~2s)" | "Slow (batch)"
    returns: str   # what comes back; enumerate status values and meanings
    next: str      # typical follow-up actions
    example: str   # minimal working example
```

`guide("nonexistent")` returns the list of valid names with one-liners.
`guide()` never raises: agents recover better from helpful responses than
from exceptions.

### Structured docstrings

Every public method's docstring follows one strict template, because the
docstring is the agent's primary decision aid when generating code:

```python
def search(self, query: str, top_k: int = 5) -> SearchResult:
    """Find documents relevant to a query.

    USE WHEN: The agent needs stored knowledge to answer a question or
    ground a decision.

    DON'T USE WHEN: The information is already in the prompt context, or
    the agent needs an exact-ID lookup (use get()).

    COST: Fast. One embedding call, no LLM.

    RETURNS: SearchResult with .documents (ranked), .count, and .summary.
    count == 0 means no match above threshold, not an error.

    NEXT: Read result.documents; call get(doc_id) for full content.
    """
```

The five fields map one-to-one onto the agent loop: what is this, should I
call it now, am I misusing it, will it be slow, what do I do with the result.

### Naming for intent, not implementation

- Verbs for operations (`add`, `search`, `sync`); nouns for state queries
  (`status`, `history`, `guide`).
- Prefer domain vocabulary over mechanism (`sync`, not `run_batch_job`).
- A good name lets an agent guess what the method does and when to use it
  without opening it. Consistency across the API beats perfect individual
  names.
- Keep precise domain terms even when obscure; make them crystal clear in
  docstrings and `guide()` rather than renaming to something generic and
  lossy.

### Minimal import surface

One top-level import gives access to everything an agent needs:

```python
from doclib import DocStore, DocStoreConfig, SearchResult, DocStoreError
```

Export from `__init__.py`: the main entry class, config, all result types,
and the exception hierarchy. Exclude internals, base classes, and test
utilities.

## Results: what agents read back

### String-first returns

Result objects get serialised into the agent's context window; the string is
the real interface. Every result type's `__str__`:

- Leads with what happened (past-tense verb)
- Includes the most actionable context (counts, thresholds, state)
- Suggests a next action when one is clear
- Fits on one or two lines

```python
str(add_result)     # "Stored doc 4f2a. Pending sync: 8/10. Auto-syncs at 10."
str(sync_result)    # "Synced 10 documents: 9 indexed, 1 duplicate skipped."
str(search_result)  # "No matching documents."

# BAD: repr noise the agent cannot act on
# "AddResult(doc_id='4f2a91c8', status='created')"

# BAD: verbose preamble wasting context tokens
# "I successfully stored your document. The operation completed without..."
```

Format conventions: `|` separates independent status facts, `:` binds
label to value, no filler words ("2 documents found", not "I found 2
documents"). Offer `.summary` (one sentence) and `to_dict()` (full data) so
callers choose verbosity.

### Consistent return shape

An agent that has learned one result type should be able to predict the rest.

- All results are dataclasses (or Pydantic models when validation is needed)
  with `__str__`, `to_dict()`, and the same field vocabulary throughout:
  `status`, `count`/`processed`/`created`, `summary`, `id`.
- Outcomes are signalled by `status` fields or typed exceptions, never by
  `None` returns or sentinel values.
- Batch operations always include counts, even when zero.

```python
# GOOD: one learnable pattern
add()    -> AddResult(doc_id, status, ...)
sync()   -> SyncResult(processed, indexed, skipped, ...)
search() -> SearchResult(documents, count, ...)

# BAD: three shapes for three methods
add()    -> str            # bare id
sync()   -> (int, int)     # mystery tuple
search() -> list[dict]     # raw rows
```

### Semantic status values

Agents branch on string values; make them read as plain English describing
the outcome, and enumerate every possible value in the docstring and guide.

```python
status: str  # "created" | "duplicate_skipped" | "superseded_existing"
```

Keep `__str__` compact and the semantic value in structured data:
`str(result)` says "Stored 4f2a.", `result.status` says `"created"`.

### Context budget control

Default to conservative output; let the agent ask for more. All retrieval
methods accept `top_k` and/or `max_tokens`. When rendered output is cut to
fit a budget, mark the cut explicitly (`"[...truncated]"`); never truncate
silently, because the agent must know its view is partial.

## State and observability

### Status as decision context

Agents deciding "should I sync now?" or "is this healthy?" need observable
state. Provide `status()` returning a snapshot plus a derived suggestion:

```python
@dataclass
class SystemStatus:
    pending_count: int
    pending_threshold: int
    indexed_count: int
    last_operation: str        # "sync (2h ago)"
    needs_sync: bool           # derived, near-threshold
    health: str                # "good" | "attention" | "degraded"
    suggestion: str            # one actionable sentence
```

`status()` is fast, never raises (it returns a degraded status instead), and
always includes the suggestion.

### Operation history through the API

When an agent gets a surprising result, it needs to see what happened, and it
cannot read stderr. Expose a lightweight audit trail through the API itself:

```python
str(client.history(last_n=3))
# "Recent operations:
#  1. add() -> created doc 4f2a (2 min ago)
#  2. add() -> duplicate_skipped (2 min ago)
#  3. sync() -> processed 8, indexed 7 (1 min ago)"
```

Record operation name, outcome, relative timestamp, and key identifiers.
Leave out debug internals and full payloads: this is operational visibility,
not a log file. It answers questions with delayed-effect causes, such as "why
doesn't search() return the document I just added?" (history shows sync never
ran).

## Errors and robustness

### Instructive errors

An agent that hits an error enters a recovery loop; the error message decides
whether that loop takes one turn or ten.

```python
class DocStoreError(Exception):
    """Base exception. All library errors include a recovery hint."""
    def __init__(self, message: str, recovery: str):
        super().__init__(message)
        self.recovery = recovery

    def __str__(self) -> str:
        return f"{super().__str__()} Recovery: {self.recovery}"

raise SessionError(
    "No active session.",
    recovery="Use 'with client.session():' to start one, or call "
             "client.begin_session() for manual control.",
)
```

Recovery messages contain the exact code or command, name the specific call
to make, and focus on what to do next rather than what went wrong.

### The recovery hierarchy

Prefer earlier options:

1. **Auto-recover:** fix the problem and continue (no session? start a
   transient one).
2. **Return gracefully:** empty or partial result whose `__str__` explains
   what happened and what to do.
3. **Raise with recovery:** typed exception, `recovery` field with the exact
   fix.
4. **Raise with diagnosis:** when the root cause is unclear, include the
   diagnostic detail alongside the best recovery hint.

Always surface failures through exceptions or status fields, return typed
results rather than `None`, and keep errors out of stderr-only logging, which
agents cannot read.

### Raise vs. return

| Scenario | Action |
|----------|--------|
| Fundamental API misuse (bad config, missing prerequisite) | Raise with recovery |
| Nothing to do (empty queue, no matches) | Return empty result with explanatory `__str__` |
| Transient failure (network, timeout) | Raise with retry hint |
| Bad parameter value | Raise with examples of valid values |

### Idempotency

Agents retry, call things out of order, and lose state; the library absorbs
this without punishing them.

- Duplicate writes return a graceful `duplicate_skipped` status (for example
  via content-hash dedup), never an error.
- Empty operations return zero counts.
- Redundant lifecycle calls are no-ops: `close()` twice is fine; opening a
  session when one is active returns the existing one.
- Where an operation needs prior state, either create it automatically or
  raise with a clear recovery message; silent failure is the one forbidden
  outcome.

## Ergonomics

### Progressive disclosure: three tiers

- **Tier 1 (2-3 methods, zero ceremony):** construct, write, read. No
  sessions, no config, sensible defaults for everything. Must be genuinely
  useful, not a toy that forces an upgrade.
- **Tier 2 (5-6 methods, explicit lifecycle):** sessions or transactions,
  multiple retrieval modes, hooks into the maintenance cycle.
- **Tier 3 (everything):** full configuration, manual lifecycle, custom
  policies, per-call overrides.

Tier 1 workflows never require knowledge of Tier 3 concepts.

### Configuration ergonomics

- Zero configuration works: `DocStore.from_config("store.db")` with no other
  arguments succeeds with sensible defaults.
- One factory accepts `None`, a path to a config file, a dict, or a config
  object.
- Keys read without documentation: `llm.model`, not `llm.mdl`.
- Support `LIBRARY_*` environment variables as a config layer for
  environments where files are impractical, and document them in
  `guide("config")`.
- Provide `config_example()` (or an example inside `guide("config")`) that
  emits valid starter config.

## Tool interface (MCP)

The most direct way for an agent to use a library is as a tool. For any
library intended for agent use, ship an MCP server (or equivalent tool
schema) as a first-class deliverable.

1. Tool names use `library_operation` format: `doclib_add`, `doclib_search`,
   `doclib_status`.
2. Descriptions are decision aids, not feature lists: "Store something worth
   keeping. Use when the agent finds information that should persist across
   sessions.", not "Stores a document in the SQLite database with
   deduplication."
3. Parameters are minimal; every optional parameter must earn its place.
4. Tool results are clean formatted strings (they land directly in the
   agent's context), not JSON blobs.
5. Lifecycle is automatic by default; expose explicit session tools only for
   advanced use.

Minimum tool surface for a stateful library: a write operation, a read/query
operation, `status`, and `guide`.

## The agent-first checklist

Discovery:
- [ ] All public types importable from the package root
- [ ] `guide()` returns runtime documentation; helpful on bad input
- [ ] Docstrings follow USE WHEN / DON'T USE WHEN / COST / RETURNS / NEXT
- [ ] MCP server or tool schema available

Results:
- [ ] Typed result objects everywhere; no raw dicts, tuples, or `None`
- [ ] Agent-optimised `__str__` (action-leading, one or two lines)
- [ ] `to_dict()` on every result; counts present even when zero
- [ ] Truncation always marked, never silent

State and errors:
- [ ] `status()` with derived `suggestion`; never raises
- [ ] `history()` accessible through the API
- [ ] Exception hierarchy with exact-fix `recovery` fields
- [ ] Empty operations return empty results; duplicates handled gracefully

Ergonomics:
- [ ] Tier 1 works with zero config and zero ceremony
- [ ] Config factory accepts None / path / dict / object; env vars supported
- [ ] Retrieval methods expose `top_k` / `max_tokens`
- [ ] Verbs for operations, nouns for state queries

---

## Project Overlay

Project-specific rules live here and nowhere else. When they conflict with
the sections above, the overlay wins. On adoption, replace the template with
a mapping table showing how this project implements each principle group, so
the mapping is auditable and gaps are visible.

```markdown
### <project-name> overlay

| Principle | Implementation here |
|-----------|---------------------|
| guide() | <method / command> |
| Result types | <list the concrete result classes> |
| Exception hierarchy | <base class, recovery field location> |
| status() / history() | <methods> |
| Tier 1 surface | <the 2-3 zero-ceremony calls> |
| MCP tools | <tool names> |

- Deviations: <each rule above that this project overrides, with the reason>
```
