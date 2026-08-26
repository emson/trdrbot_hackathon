# Open Knowledge Format (OKF) — Reference Notes

Researched 2026-08-26 (decision-mode fan-out, 53 agents, primary sources fetched directly —
not summarized secondhand). Written to be reusable on any project building an LLM-agent-
maintained wiki/knowledge base. trdrbot's specific application of this lives in
`specs/notes/008_open_knowledge_format_research.md` and `specs/decisions.md` (D-022, D-023).

## What it is

**Open Knowledge Format (OKF)** — a real, current, open specification published by
**Google Cloud's Data Cloud team** (announced 2026-06-12 on the Google Cloud blog, by BigQuery/
Data Analytics tech leads Amir Hormati and Sam McVeety). Currently **v0.2**. Canonical repo:
[GoogleCloudPlatform/open-knowledge-format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
(split out 2026-08-11 from `GoogleCloudPlatform/knowledge-catalog/okf`, both still resolve).

**⚠️ Version skew trap:** the widely-cited June 2026 blog post describes **v0.1**. The live spec
is v0.2 and renamed two things: `timestamp` → `generated.at`, body `# Citations` → frontmatter
`sources`. Build against `SPEC.md`, never the blog. v0.2 is weeks old as of this writing —
expect further churn; no formal governance body, no conformance test suite.

### Disambiguation (confirmed, not this)

- **Not** Google DeepMind, not a model/agent product
- **Not** schema.org, RDF/OWL, or any ontology — type values are "not registered centrally"
- **Not** the Knowledge Graph API / Knowledge Panels — no service, no API surface
- **Not** `llms.txt` or `AGENTS.md` — those are single-file root conventions; OKF is a
  hierarchical multi-file bundle with per-concept provenance and lifecycle
- **Not** NotebookLM's internal format — no documented relationship
- **Not** the UK **Open Knowledge Foundation** (CSVW, Frictionless Data) — same OKF/OKFN
  acronym, completely unrelated organization. This is the collision most likely to bite you
  when searching.

## Structural spec (v0.2, from SPEC.md directly)

A **Knowledge Bundle** is a directory tree of UTF-8 markdown files with YAML frontmatter.
"There is no schema registry, no central authority, and no required tooling." Deliberately
minimal, deliberately permissive:

- **Concept** = one markdown document. **Concept ID** = its path minus `.md`.
- **`type`** is the *only* always-required frontmatter key. A concept with just `type` is
  fully conformant. Everything else (title, description, resource, tags) is optional/recommended.
- Type values are freeform (`BigQuery Table`, `Metric`, `Playbook`, `Reference`,
  `Attested Computation`, ...) — consumers **MUST** tolerate unknown types.
- Producers **MAY** add arbitrary extra keys; consumers **MUST NOT** reject documents for
  unrecognized fields, missing optional fields, or broken links.
- Reserved filenames at any directory level: **`index.md`** (progressive-disclosure listing,
  no frontmatter except an optional root `okf_version`) and **`log.md`** (dated change history,
  newest-first, `**Update**`/`**Creation**`/`**Deprecation**` entries by convention).
- Distribution: git repo (recommended), tarball/zip, or a subdirectory of a larger repo.

### Provenance & trust (v0.2 addition — this is the part that matters for agent-maintained wikis)

- **`sources[]`**: each entry has a required `resource` (URL, bundle-relative path, or a scope
  descriptor) plus credibility *signals* — `author`, `usage_count` (with a `usage_window`),
  `last_modified`. Deliberately **no stored credibility score**: "a score is subjective,
  unportable across consumers, and goes stale. Credibility is *inferred* from the signals."
- Per-claim attribution uses **markdown footnotes keyed by `sources[].id`**, not positional
  index — "agents constantly rewrite these documents; a positional index misattributes silently
  the moment the list is reordered."
- **`generated: {by, at}`** (who/when produced this) vs **`verified: [{by, at}, ...]`** (who/when
  confirmed it) → three derived trust tiers: no `verified` = **unverified**; verified by a
  non-human actor = **machine-confirmed**; verified by `human:<id>` = **human-reviewed**.
  "Trust tiers are advisory signals, not access control."
- Actor convention: `<producer>/<version>` for agents (e.g. `reference_agent/gemini-2.5-pro`),
  `human:<id>`, `process:<id>`.

### Freshness (v0.2 addition)

- **`status`**: `draft` (unreviewed) | `stable` (default) | `deprecated` (tombstone-in-place,
  kept for links/history — never delete).
- **`stale_after`**: an **absolute ISO-8601 instant**, not a relative TTL. "A concept is stale
  when `now >= stale_after`. An absolute instant... keeps the staleness decision a plain
  comparison with no reference to when the concept was read."
- That's it. **No decay curve, no re-verification cadence, no contradiction-detection rule** —
  those are out of scope by design.

### Attested Computation (v0.2 addition, notable, unfinished)

A concept type for numeric facts that can be *proven*, not just asserted: `Executor` (runs the
sanctioned computation, returns a receipt) + `Attester` (deterministic, no-LLM code that checks
the receipt and returns a verdict). Good fit for anything like a calculated metric, a scored
outcome, a reproducible number you want an agent to trust without re-deriving it. **The full
runtime protocol (receipt/verdict wire format, attester ABI, sandboxing, caching) is explicitly
deferred** — v0.2 defines the concept shape, not how to execute it. Treat as directional, not
ready to depend on wholesale.

### Linking & retrieval — deliberately out of scope

Markdown links form an untyped directed graph. Spec recommends **absolute bundle-relative**
links (starting with `/`, stable across file moves); Google's own reference-agent prompts
**forbid** that convention and use relative links instead, because a leading `/` breaks GitHub
rendering. **Pick one and be consistent** — if the bundle will ever be browsed on GitHub or in
Obsidian, relative links are what actually renders.

OKF prescribes **no query engine, no index, no embedding scheme, no chunking rule, no
hybrid-retrieval pattern** — explicit non-goal ("prescribing storage, serving, or query
infrastructure"). What it *does* give you as a retrieval lever: frontmatter (`type`, `tags`,
`status`, `stale_after`, derived trust tier, `sources[].usage_count`) as a metadata filter/rank
layer, and `index.md` for progressive disclosure instead of loading a whole bundle. Everything
past that — per-file vs per-section chunking, vector vs keyword vs hybrid, multi-hop
link-traversal — is ordinary RAG engineering you own.

## What's normative vs. what's borrowed practice

**Only `SPEC.md` is normative.** Everything below comes from the repo's reference-agent
(Python + prompt files) — an explicitly-labeled proof of concept, not spec. It's the most
concrete, battle-tested answer available to exactly the questions OKF itself declines to
answer (note size, when to split, how to prevent degradation), so it's worth adopting
deliberately as *house rules* — just don't cite it as "the spec says."

### The four-gate test for minting a new note (answers: how much per note, when to split)

All four must hold before creating a new reference concept:
1. **Topic shape** — defines something referenceable by name (an entity, a metric, an enum,
   a glossary term, a convention) — not a narrative.
2. **Not bundle-level meta** — skip anything that's really an overview/intro/getting-started/
   changelog/roadmap in disguise.
3. **Citation test** — you can write a real sentence like *"See the [X reference](...) for..."*
   naming a concrete noun. "If the best sentence you can write is 'see the overview for
   context', it fails."
4. **Reuse test** — at least two existing concepts would cite it, or one needs it as load-bearing
   background that doesn't fit inline.

"When in doubt, skip. A bundle full of overview/getting-started docs is noise."

### Naming & atomicity

One file per atomic fact — e.g. one file per metric, one canonical file per relationship
(name the two related things, sorted alphabetically, joined by `__`, so it's the same file
regardless of which side you approach it from). Single-source-of-truth: the canonical file
owns the detail (e.g. the actual formula/SQL); anything referencing it links, never duplicates.

### Anti-orphan rule

A minted reference note with nothing linking to it is a bug, not a deliverable. Before finishing
a batch of writes, verify every new note is cited from at least one primary document, and
back-link both sides of any relationship.

### The actual answer to "how do we reduce degradation": monotonic augmentation, enforced

This is the single most reusable idea here. The reference agent's write tool **refuses writes
that shrink an existing document**:

- If a doc has a `# Schema` section with N fields, a rewrite can't drop below N.
- `sources` and `tags` are **union-merged**, never replaced — a write that would shrink the list
  is rejected outright.
- Every top-level heading in the existing body must reappear, in the same order, with the same
  wording — you may extend, add sub-sections, or append new headings, but not delete/rename/
  silently rewrite what's there.
- `generated` is the only frontmatter key you're allowed to drop (it gets refreshed on write).
- Writes are **full replacements, not patches** — the caller must supply every existing key, which
  forces the augmentation discipline above rather than letting a partial write silently lose data.
- "A rejected write did not happen — fix it and retry, do not give up."

This is a code-level guard, not a prompt suggestion, and it's the difference between an
LLM-maintained wiki that accumulates knowledge and one that slowly overwrites itself into mush.

### Agent workflow (observe → extract → write)

1. `read_existing_doc(concept_id)` — if it exists, refine it, don't rewrite from scratch.
2. Read the raw source material.
3. `list_concepts()` first, so cross-links reference IDs that actually exist — "do not invent
   link targets."
4. Write **exactly once per concept** per pass — if a source yields several distinct facts,
   make multiple separate writes, one per concept, rather than one sprawling document.
5. Style: concrete over vague; don't invent unsupported detail; no preamble/apology/reasoning
   narration inside the document body — the body is knowledge, not a transcript.

## Practical checklist for adopting OKF in a new project

- [ ] Every concept file gets a `type:` — freeform is fine, just be consistent per type
- [ ] Reserve `index.md` and `log.md`, don't repurpose those filenames
- [ ] Decide your link style up front (relative if GitHub/Obsidian browsing matters) and enforce it
- [ ] Give slow-changing pages a `stale_after`; pick who sets it (per-type default is simplest)
- [ ] Track `sources[]` with keyed footnotes wherever a claim needs attribution
- [ ] Use `generated`/`verified` if you have any notion of human review or automated confirmation
- [ ] Build retrieval yourself — frontmatter as filter/rank layer, index.md for progressive
      disclosure, and your own chunking/embedding choice; OKF gives you the metadata, not the engine
- [ ] Adopt (don't just skim) the reference agent's four-gate mint test and monotonic-augmentation
      write guard — they're the concrete answers to questions the spec deliberately leaves open
- [ ] Re-check `SPEC.md` directly before relying on any secondhand summary (blog posts,
      "explainer" articles) — version skew between v0.1 and v0.2 is already live in the wild

## Open questions (unresolved as of this research)

- Adoption/tooling beyond Google's own reference agent — real exporters, third-party producers,
  a validator — unconfirmed.
- What retrieval architecture actually performs best on an OKF bundle at scale is unanswered by
  anyone; it's a green field.
- No merge/split/contradiction-resolution story beyond `status: deprecated` + `stale_after`.
- The Attested Computation runtime (receipts, attester ABI, sandboxing) isn't defined yet —
  don't build against it as if it were stable.
- Who sets `stale_after`, and to what, is left entirely to the implementer — this is the one
  decision that determines whether a wiki decays gracefully or noisily.

## Sources

- [SPEC.md (raw, primary)](https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/SPEC.md)
- [README.md (raw, primary)](https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/README.md)
- [GoogleCloudPlatform/open-knowledge-format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
- [Google Cloud blog announcement, 2026-06-12](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing) (describes v0.1 — see version-skew warning above)
- Reference agent prompts (proof-of-concept, not normative):
  [`reference_instruction.md`](https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/src/reference_agent/prompts/reference_instruction.md),
  [`web_ingestion_instruction.md`](https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/src/reference_agent/prompts/web_ingestion_instruction.md)
- [`bundle_tools.py`](https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/src/reference_agent/tools/bundle_tools.py) (the augmentation-guard implementation)
