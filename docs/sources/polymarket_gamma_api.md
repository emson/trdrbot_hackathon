---
type: data-source-note
status: approved
created: 2026-07-16
updated: 2026-07-16
description: >-
  Polymarket's public Gamma market-data API (no auth) — nine quirks
  verified live against the real endpoints during the polymarket organ's
  get_market()/detect_edge() build and its later top_markets()/
  search_markets() discovery build (propose@1.0), each with a real
  correctness consequence for anything reading this API.
sources:
  - https://gamma-api.polymarket.com/markets (live GET calls, 2026-07-16 — see Verification notes)
  - https://gamma-api.polymarket.com/events (live GET calls, 2026-07-16 — see Verification notes)
  - https://gamma-api.polymarket.com/public-search (live GET calls, 2026-07-16 — see Verification notes)
  - https://gamma-api.polymarket.com/tags/slug/<slug> (live GET calls, 2026-07-16 — see Verification notes)
  - ops/organs/tool/polymarket/impl.py (get_market(), detect_edge(), top_markets(), search_markets())
  - ops/organs/tool/polymarket/guide.md
---

# Polymarket Gamma API — verified quirks

> **Provenance:** carried over 2026-08-26 from a prior incarnation of this project
> (`~/Dropbox/devel/projects/ai/trdrbot`), where all nine quirks were verified by live
> calls against the real endpoints. Adopted here per D-027. Paths in the original text
> (`ops/organs/tool/polymarket/impl.py`) refer to that repo; our equivalent is
> `src/trdrbot/polymarket.py`, which implements the same defences.
>
> Quirk 1 re-verified live in this repo on adoption: the raw `outcomePrices` field came
> back as the string `'["0.0425", "0.9575"]'`, so a naive `prices[0]` yields the
> character `'['` rather than a price — silent corruption, not an error.

Nine things about `https://gamma-api.polymarket.com`'s `/markets`,
`/events`, `/public-search`, and `/tags/slug/<slug>` endpoints confirmed by
live calls (not assumed from documentation), each relevant to any future
code reading this API beyond what `ops/organs/tool/polymarket/impl.py`
already handles correctly.

## 1. `outcomes` and `outcomePrices` are JSON-encoded *strings*, not arrays

A market's `outcomes` and `outcomePrices` fields are not JSON arrays in the
response body — they are strings that themselves contain JSON, e.g.
`"outcomes": "[\"Yes\", \"No\"]"`, `"outcomePrices": "[\"0.505\",
\"0.495\"]"`. A caller that does `market["outcomePrices"][0]` gets a string
character, not a price. Requires a second `json.loads()` on each field
before use — `get_market()` already does this correctly
(`json.loads(m.get("outcomes", "[]"))`); anything reading the raw API
response directly needs the same double-parse.

## 2. `slug` filtering is exact-match, not fuzzy or prefix

`GET /markets?slug=<full-slug>` returns the one matching market (verified:
`new-rhianna-album-before-gta-vi-926` → 1 result). A truncated or partial
slug returns an **empty list**, not a fuzzy/prefix match (verified:
`new-rhianna-album-before-gta-vi` → 0 results, even though it's a strict
prefix of a real slug). This matters for correctness, not just convenience:
`get_market()`'s `matches[0]` pick is safe *because* the API guarantees an
exact match rather than the first of several loosely-matching candidates —
worth knowing before anyone "improves" this into a fuzzy lookup and quietly
breaks that guarantee.

## 3. `limit` silently caps at 100 regardless of the requested value

`GET /markets?limit=500` returns at most 100 markets — confirmed by
requesting `limit` values of 50 (→50), 100 (→100), 150 (→100), and 500
(→100) against the same live, filtered query
(`active=true&closed=false`). The API neither errors nor paginates by
default when a higher limit is requested; it silently truncates. **Update
2026-07-16 (discovery build):** now deliberately exercised —
`top_markets()` requests `/events?limit=25`, which stays comfortably under
this cap (see quirk 6, the same cap applies to `/events`). Any future
capability wanting more than 100 results in one call will need real
pagination (`offset`, per Gamma's own docs, not verified here) rather than
a single higher `limit`.

## 4. `GET /events?order=volume&ascending=false` sorts reliably where `/markets`' sort did not

`/markets`' own `order`/`ascending` params did NOT reliably sort by volume
when tested live (results came back in no clear volume order). `GET
/events?tag_id=<id>&order=volume&ascending=false` did — live-verified
2026-07-16 against the real "Geopolitics" category (`tag_id=100265`):
genuinely volume-descending results, $123.5M → $93.8M → $66.0M. This is
the reliable path for "top N by volume in a category"; `top_markets()`
(`ops/organs/tool/polymarket/impl.py`) uses it for exactly this reason.
Polymarket's own documented `order` values include `volume_24hr`,
`volume`, `liquidity`, `start_date`, `end_date`, `competitive`,
`closed_time`.

## 5. Event-level `active`/`closed` filters do NOT filter nested markets

`GET /events?active=true&closed=false` filters the *event*, not its
nested `markets[]` — live-verified 2026-07-16. A returned "open" event can
still contain:
- **Already-resolved markets**: `closed: true` (even though the event
  itself is `closed: false`), with degenerate `outcomePrices: ["0", "1"]`
  — e.g. `netanyahu-out-by-may-31` inside the still-open
  `netanyahu-out-before-2027` event.
- **Unlaunched placeholder markets**: `active: false`, `outcomePrices:
  null` (not even a JSON string) — e.g. 41 of the
  `venezuela-leader-end-of-2026` event's candidate-leader markets were
  inactive placeholders at verification time.

Any code flattening nested markets out of `/events` must re-check
`closed`/`active` per market and re-parse `outcomes`/`outcomePrices`
defensively — skipping this is exactly the "false quantitative confidence"
bug class this organ was previously caught on (the `favored_price` fix).
`top_markets()`/`search_markets()`'s shared `_flatten_event_markets()`
helper does this.

## 6. `/events`' `limit` also silently caps at 100

Same behavior as quirk 3 but on a different endpoint — confirmed live:
`limit=150` on a real `/events` query returned exactly 100 results.
Harmless for `top_markets()` (`EVENTS_SCAN_WINDOW=25`, well under the
cap), but load-bearing if that window is ever widened past 100 expecting
more results — real pagination would be needed, not a bigger `limit`.

## 7. `/public-search`: required `q`, silent zero-result shape, and a relevance-destroying sort option

`GET /public-search` (docs.polymarket.com/api-reference/search) — full-text
search over markets, events, and profiles together. Confirmed live,
2026-07-16:
- `q` is required: omitting it returns HTTP 422
  (`{"type":"validation error","error":"query argument \"q\": empty"}`).
- A genuine zero-result query returns `{"pagination": {"hasMore": false,
  "totalResults": 0}}` — the `"events"` key is **omitted entirely**, not
  an empty list. `body.get("events") or []` is required; `body["events"]`
  raises `KeyError` on this valid, common response shape.
- Adding `sort=volume&ascending=false` to a real `q="iran"` search
  **destroyed relevance**: the #1 result became `"world-cup-winner"` (an
  unrelated, merely high-volume event) instead of any Iran-related event.
  `search_markets()` deliberately sends no `sort` param and relies on
  Gamma's default relevance ranking for this reason — a future
  "improvement" adding volume-sort to text search would be a regression,
  not an improvement.
- Nested markets inside `/public-search`'s `events[].markets[]` carry the
  same double-JSON-encoded `outcomes`/`outcomePrices` quirk as `/markets`
  (quirk 1) and the same closed-inside-open-event trap as `/events`
  (quirk 5) — e.g. the `iran-leader-end-of-2026` event matched by
  `q="iran"` has 123 nested markets, one per candidate leader.

## 8. `/tags/slug/<slug>`: single object, string `id`, case-tolerant, clean 404

`GET /tags/slug/<slug>` (e.g. `/tags/slug/geopolitics`) returns a single
tag object, not a list — confirmed live, 2026-07-16:
- `{"id": "100265", "label": "Geopolitics", "slug": "geopolitics", ...}` —
  `id` is a JSON **string**, not a number.
- Case-tolerant: `/tags/slug/Geopolitics` (capitalized) resolves to the
  same tag as the canonical lowercase slug.
- A literal space in the slug (e.g. `"middle east"` unencoded) returns
  HTTP 422 (`{"type":"validation error","error":"slug is invalid"}`) —
  callers must normalize (strip/lower/hyphenate) before requesting.
- An unknown slug returns a clean HTTP 404
  (`{"type":"not found error","error":"slug not found"}`), not an empty
  200 body — easy to turn into a named, actionable failure rather than a
  confusing empty result.
- Polymarket's full tag list (`GET /tags`) is large (hundreds) and
  inconsistently curated — real categories sit alongside apparent noise
  (e.g. "product marekt fit", "virgins"). Slug lookup is the reliable path
  for a known category name; browsing the full list is not recommended.

## 9. Nested-market `volume` is sometimes a string while `volumeNum` is a float

Confirmed live, 2026-07-16, across many nested markets inside both
`/events` and `/public-search` responses: a market's `volume` field is
frequently a JSON *string* (e.g. `"107740.76147199978"`) while its
`volumeNum` field is a native float carrying the same value. `volumeNum`
is the field to prefer; `volume` is a fallback. Coerce defensively either
way — `top_markets()`/`search_markets()`'s `_coerce_volume()` helper
returns `None` (never a fabricated `0.0`) when neither parses, so a
missing/junk volume reads as absence, not a false zero.

## Verification notes

Quirks 1–3 confirmed via direct `httpx.get()` calls against the live
endpoint during the original `get_market()`/`detect_edge()` build,
2026-07-16 — see that build's own live check:
`get_market("new-rhianna-album-before-gta-vi-926")` and
`detect_edge(0.6, "new-rhianna-album-before-gta-vi-926")` both returned
correctly-shaped, real data at review time (market price 0.505, edge
+0.095, favoring Yes).

Quirks 4–9 confirmed via direct `httpx.get()`/`uv run python` calls against
the live endpoints during the later `top_markets()`/`search_markets()`
discovery build, same day. Live smoke of the finished functions at that
review: `top_markets("geopolitics")` returned 10 genuinely volume-
descending open markets whose #1 slug (`will-the-us-invade-iran-before-
2027`) fed straight into `get_market()` without translation;
`top_markets("Middle East")` resolved correctly via slug normalization;
`top_markets("definitely-not-a-tag")` returned a named `ok=False`;
`search_markets("iran")` returned 10 relevance-ordered open markets with
no event contributing more than 3 and zero degenerate `0`/`1` price pairs
in the result set.

No CLOB (order-book/private) endpoints were touched in either build — out
of scope, paper-only (`ops/organs/tool/polymarket/guide.md`).

## Provenance

Filed by Kelly (Reviewer role) during the `propose` playbook's
`get_market()`/`detect_edge()` build review, `needs_review` (hard rule 3).
Quirks 1–2 were already handled correctly by that build; quirk 3 didn't
affect any function that existed yet at the time.

**Updated 2026-07-16 (same day, later build)** by Kelly (Dev role) during
the `top_markets()`/`search_markets()` discovery build: quirks 4–9 added,
each one live-verified specifically because it has a real correctness
consequence for `_flatten_event_markets()` (quirks 1, 5, 9), `_resolve_tag()`
(quirk 8), or the choice of endpoint/sort strategy in each function
(quirks 3, 4, 6, 7). Quirk 3's "not exercised by anything in this repo
today" line is now stale and has been corrected in place — `top_markets()`
deliberately bounds its `/events` request under this cap.
