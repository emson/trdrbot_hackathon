# Open Knowledge Format (OKF) — Research for trdrbot's Wiki

Decision-mode fan-out (53 agents, primary sources fetched directly). Full portable reference
(reusable across projects) saved separately at
`~/Dropbox/devel/projects/ai/notes_open_knowledge_format.md` — this note covers only what's
specific to applying it here, on top of what's already built (D-011, D-014, D-015).

## The headline

OKF is real: Google Cloud's Data Cloud team, announced 2026-06-12, now v0.2, spec at
[GoogleCloudPlatform/open-knowledge-format](https://github.com/GoogleCloudPlatform/open-knowledge-format).
A bundle is a directory of markdown files with YAML frontmatter; `type` is the only required
key; `index.md`/`log.md` are reserved. Confirmed distinct from schema.org, the Knowledge Graph
API, `llms.txt`/`AGENTS.md`, NotebookLM, and (the real trap) the unrelated UK Open Knowledge
Foundation, which shares the OKF acronym.

**We are already most of the way there.** D-011's Karpathy-pattern wiki
(`index.md`, `log.md`, `positions/`, `lessons.md`, `strategy.md`, `context/`) already matches
OKF's reserved-filename convention and directory-of-markdown-with-frontmatter shape. This isn't
a redesign — it's formalizing frontmatter conventions we'd have had to invent ourselves anyway,
using ones that are already documented and (for the retrieval-lever parts) genuinely well-suited
to what we need.

## What answers the user's four questions

**How much information per note / population rules** — OKF's spec is silent on this by design
(explicit non-goal). The answer comes from the reference agent's non-normative but concrete
**four-gate mint test**: referenceable-by-name, not bundle-meta, passes a "See the [X] for..."
citation test, and would be reused by ≥2 existing concepts (or is load-bearing background for
one). Directly answers "when does something deserve its own `lessons.md` entry" — most
speculative or one-off observations should fail gate 4 and simply not get minted.

**How do we reduce degradation** — this is the most valuable single finding. OKF itself defines
no anti-degradation mechanism beyond `status: deprecated` (tombstone, never delete) and
`stale_after`. The reference agent's answer is **enforced monotonic augmentation**: writes are
full-replacement, not patches, and a code-level guard refuses any write that shrinks an existing
`sources[]`/`tags[]` list or drops a heading that was already there. This is exactly the
mechanism our `wiki.py` write path needs and didn't have a concrete design for yet — a shrinking
write is a symptom of an LLM "rewriting" rather than "extending" a note, which is precisely how
knowledge quietly degrades over many autonomous cycles.

**How do we accurately retrieve information** — OKF explicitly punts (no query/embedding/
chunking guidance; "prescribing storage, serving, or query infrastructure" is a listed
non-goal). What it hands us instead is a strong metadata filter/rank layer: `type`, `tags`,
`status`, `stale_after`, derived trust tier, `sources[].usage_count`. This slots directly onto
our existing division of labour (elfmem = semantic recall, wiki = curated reference) — the wiki
side gets frontmatter filtering, elfmem keeps doing embedding-based recall on its own store.
Nothing here changes D-011's elfmem/wiki split; it just gives the wiki side a real filter layer
instead of an ad hoc one.

## Direct upgrades to our existing wiki design

1. **`type:` on every concept** — `Position`, `Lesson`, `MarketContext`, `Metric` (for a
   calibration/Brier-tracking page). Costs nothing; we were already implicitly typing pages by
   directory.
2. **`sources[]` replaces/extends `wiki_refs`** — richer than our sha-hash-only design: adds
   `author`, `usage_count`, `last_modified` as credibility *signals* rather than a stored score
   (their own reasoning for this — a stored score "is subjective, unportable, and goes stale" —
   applies exactly as well to us). Footnote-keyed attribution (not positional) matters
   specifically for us because our learn path rewrites `lessons.md` and `strategy.md` over time;
   a positional citation would silently misattribute the moment the list reorders.
3. **`generated`/`verified` trust tiers** — `generated.by` is exactly our existing "which model
   made this decision" tracking (D-008), now with a name. `verified` gives us a real second
   tier: when the reconciler independently confirms something the decide path wrote (e.g. a
   fill, a close), that's a legitimate `machine-confirmed` verification event distinct from the
   original `unverified` write — a distinction we didn't have before and can get for free.
4. **`status` + `stale_after` on `wiki/context/*.md`** — these three pages (`regime.md`,
   `macro.md`, `calendar.md`) are precisely the "slow-changing, needs a freshness marker" case
   the format was designed around. `stale_after` for `regime.md` can be set to the next
   housekeeping cycle; for a page keyed off `calendar.md`'s known events (FOMC, CPI), to that
   event's date.
5. **`Attested Computation` for calibration scores** — a plausible fit for D-013's Brier/Murphy
   output (a number that should be provably reproducible, not just asserted), but the runtime
   protocol is explicitly deferred in v0.2 and not ready to depend on. Treat as directional; if
   we use the shape at all, implement our own minimal executor/attester rather than assume any
   forthcoming Google tooling.
6. **Link convention: pick one, deliberately.** The spec recommends absolute bundle-relative
   (`/`-rooted) links; Google's own reference agent forbids them because a leading `/` breaks
   GitHub rendering. Our `positions/*.md` pages are a submission artifact judges may read on
   GitHub — that tips the choice decisively toward the reference agent's **relative-link**
   convention, not the spec's.

## What stays exactly as designed

Nothing about D-011's elfmem/wiki/journal split changes, nothing about D-014's `position_id`
provenance spine changes, and nothing about the sensor/tooling design (D-015/D-016) changes.
OKF is additive frontmatter convention and two borrowed authoring disciplines (mint gate,
augmentation guard) — not a new subsystem.

## Sources

Full citation list in the portable reference doc
(`~/Dropbox/devel/projects/ai/notes_open_knowledge_format.md`). Primary: `SPEC.md` and
`README.md` fetched directly from the canonical repo, not summarized secondhand. Caveat carried
forward: the June 2026 blog post describes v0.1, already superseded on two field names
(`timestamp`→`generated.at`, body `# Citations`→frontmatter `sources`) — every claim here is
checked against the live v0.2 `SPEC.md`.
