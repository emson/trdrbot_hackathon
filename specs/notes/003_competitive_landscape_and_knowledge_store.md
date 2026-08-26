# Competitive Landscape & Knowledge-Store Pattern — state of play, 2026-08-26

Dive-mode research (inline, angle-based search — not the heavy fan-out) answering: what are
other Alpaca hackathon teams actually building, and what does a sensible MCP + knowledge-store
+ CLI setup look like right now? Includes a targeted X/Twitter check per user request.

## The short version

Direct evidence about competing teams' architecture is thin — X and team pages surface team
*names* but not implementation details; nobody found their pages readable or their socials
posting build details. What's strong is adjacent prior art: an existing open-source
`AlpacaTradingAgent` project (LangGraph, direct API not MCP) independently converged on almost
exactly trdrbot's own decision-loop and self-improvement-loop shapes, and Alpaca itself ships a
first-party hosted MCP endpoint (`agentic` repo) that changes our architecture cost model. For
the "LLM wiki" knowledge store, there's a real, named, well-documented pattern (Andrej
Karpathy's) that's a substantially better fit for D-006 than our current flat-file design.

## Themes

### Other teams: names known, architecture unknown

Every search — direct, X-restricted, GitHub-restricted — surfaces the same seven team pages
(LS101, Dawn Of The Trading Agents, Team Scorpians, ALIENS, Stormers, AgentTrade AI, AgentAlpha)
via search-result snippets, but none exposed tech-stack detail through search, and direct
fetches of lablab.ai team pages return HTTP 403 (confirmed earlier this session too — this
domain blocks WebFetch). X/Twitter search found only lablab.ai's own announcement tweet
[x.com/lablabai/status/2089757334746677309], no participant build-in-public threads, demo
clips, or screenshots. **Honest conclusion: we don't know what other teams are building.** If
this matters, the only way to actually see it is a logged-in browser session against lablab.ai
team pages, which this research couldn't do.

### Prior art: an existing Alpaca+LangGraph project validates our own design independently

[huygiatrng/AlpacaTradingAgent](https://github.com/huygiatrng/AlpacaTradingAgent) (pre-existing
open-source project, not a hackathon entry) is close enough to trdrbot's shape to be worth
citing directly:
- **Framework:** LangGraph, multi-agent (5 analysts + researcher/trader/risk-management teams,
  debate-driven consensus between bull/bear researchers before the trader decides).
- **Alpaca integration:** direct API, not MCP.
- **Memory:** "Completed decisions are written to a markdown memory log and later resolved with
  realized returns and reflections" — functionally the same shape as trdrbot's D-006 (trade
  journal + review), independently arrived at.
- **Reliability:** per-symbol SQLite checkpoints so failed LangGraph runs resume; successful
  runs clean up.
- **Scheduling:** "Configurable recurring analysis every N hours," automatic during market
  hours — same shape as D-003.

This is convergent validation, not a contradiction of anything decided so far — worth citing in
the submission write-up as evidence the design pattern is sound, independently of the
hackathon.

### Alpaca ships a first-party plugin/MCP hub beyond the OSS server

[alpacahq/agentic](https://github.com/alpacahq/agentic) is a separate repo from
`alpaca-mcp-server`: a "multi-platform plugin marketplace" offering OAuth-based plugins for
Cursor/Claude Code/Codex (no API-key management), **hosted remote MCP endpoints** —
`https://api.alpaca.markets/mcp` (live) and `https://paper-api.alpaca.markets/mcp` (paper),
plus broker equivalents — a local MCP server option, and the Trading CLI, all as alternative
connection paths. This corrects [notes/002](002_harness_comparison.md)'s "must self-host"
finding — see the correction there. Single-fetch finding; verify by connecting before relying
on it for the actual build.

### The "LLM wiki" pattern is real, named, and well-suited to D-006

The user's instinct ("most likely an llm wiki") matches an actual documented pattern —
originating from Andrej Karpathy, written up by multiple independent sources
([aaif.io](https://aaif.io/blog/karpathys-llm-wiki-as-agent-memory),
[decodingai.com](https://www.decodingai.com/p/llm-wiki-agent-memory),
[mindstudio.ai](https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-obsidian-codeex-second-brain)).
Three-layer architecture:

- **`raw/`** — immutable source material (fetched market data, Alpaca API responses). The
  agent reads and cites it, never edits it.
- **`wiki/`** — structured markdown the agent actively maintains: entity pages (one per
  position/underlying), topic/trend summaries, `index.md` for navigation, `log.md` for a
  chronological activity record.
- **schema (`AGENTS.md`)** — the instruction layer: conventions for avoiding duplication,
  updating canonical pages, and what counts as a loggable change.

Maps memory types cleanly: semantic (durable facts/lessons), entity (per-position pages),
episodic (`log.md` + dated entries), summary (compressed history so the agent doesn't
re-process every raw source every cycle), procedural (the schema itself). Critically, it's
explicitly designed for **independent, scheduled runs** — each wake cycle starts by reading the
wiki rather than reprocessing history, then writes updates. This is the same continuity problem
D-006 solves, with a more established structure and vocabulary than our current flat
`journal.jsonl` + `guidance.md`.

**Proposed mapping onto D-006** (not yet decided — flagging for a decision pass):
- `raw/` = per-cycle market/options-chain snapshots and Alpaca API responses (append-only).
- `wiki/positions/<underlying>-<date>.md` = one entity page per open/closed position: thesis,
  stop-loss, target, outcome, reflection — replaces the flat journal with something more
  legible and directly citable in the submission.
- `wiki/guidance.md` = what D-006 already calls the guidance doc — fits directly, no change.
- `wiki/log.md` = the chronological activity record — could subsume the raw `journal.jsonl`
  entirely, or sit alongside it.
- `AGENTS.md` = encodes D-006's own rules (tighten/add only, min. sample size, review cadence)
  as the schema the agent is instructed to follow — turns those constraints from "prose in a
  decision doc" into "the actual operating instructions read every cycle."

This is a real upgrade to D-006, not just relabeling: it comes with an established discipline
(don't touch raw/, always update via wiki/, log everything in log.md) that our original design
left implicit.

### CLI tools: no gap found, low-risk

No new finding beyond what we already know — Alpaca's own Trading CLI ("Alpaca Agent Tools")
exists for "scripts, CI, and focused agent actions," and every harness under consideration can
shell out to CLI tools as a matter of course. Not a discriminator; nothing here changes the
harness or D-004 guardrail design.

## Disagreements & open questions

- The `alpaca-mcp-server` repo says no hosted endpoint exists; the `agentic` repo says one does.
  Not actually a contradiction (two different products) but confirm which one the team should
  target before building against either — recommend the `agentic` hosted paper endpoint given
  it removes a real operational cost, but verify by connecting first.
- No evidence was found on what other teams are actually building. If competitive intelligence
  matters, it needs a logged-in browser pass against lablab.ai, which wasn't available this
  session (Chrome extension not connected — see earlier session note) and which WebFetch cannot
  do (403 on team pages).

## What would change this conclusion

- If connecting to `https://paper-api.alpaca.markets/mcp` fails or requires an unexpected
  approval/business process, the self-hosting cost from notes/002 is back in play.
- If a browser session against lablab.ai team pages surfaces actual competitor architecture,
  that would replace "unknown" with real signal and might change positioning/strategy.
- If building the LLM wiki structure turns out to cost more setup time than it saves in a 9-day
  window, the simpler flat-file D-006 design remains a reasonable fallback — this is additive,
  not a hard requirement.

## Sources

- [huygiatrng/AlpacaTradingAgent](https://github.com/huygiatrng/AlpacaTradingAgent) — tier 2 (community repo), fetched 2026-08-26
- [alpacahq/agentic](https://github.com/alpacahq/agentic) — tier 1 (official Alpaca repo), fetched 2026-08-26
- [Karpathy's LLM Wiki as Agent Memory — AAIF](https://aaif.io/blog/karpathys-llm-wiki-as-agent-memory) — tier 2, fetched 2026-08-26
- [Your Second Brain Is a Graveyard. Make It Agent Memory. — Decoding AI](https://www.decodingai.com/p/llm-wiki-agent-memory) — tier 2, referenced not fetched
- [ar9av/obsidian-wiki](https://github.com/ar9av/obsidian-wiki) — tier 2, referenced not fetched
- [x.com/lablabai/status/2089757334746677309](https://x.com/lablabai/status/2089757334746677309) — tier 1 (primary/organizer), only X activity found
- lablab.ai team pages — inaccessible via WebFetch (HTTP 403); names only, via search snippets
