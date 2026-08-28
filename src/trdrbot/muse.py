"""The muse - creative thesis generation by forced collision (D-060).

Research (D-032) and discovery (D-035) are top-down: regime -> universe ->
opportunity. They can only find what their funnel points at. The muse works
the other way: pick concepts from the knowledge base and recent news that were
never meant to be read together, and force the question "what happens to WHOM
if these are both true?" - the domino chains and second-order effects a
funnel never asks about.

Discipline, because creativity without it is noise:

  1. The collision is RANDOM (seeded per-day, so a day's run is reproducible)
     - novelty comes from the sampling, not from asking an LLM to "be
     creative", which produces the same three ideas every time.
  2. The LLM narrates and argues; every claim must terminate in a falsifiable
     band-and-horizon thesis or it is discarded at parse time.
  3. EVERY candidate is registered in the pre-registration ledger, including
     the ones rejected a moment later - the multiple-testing correction needs
     the trials that failed, and an LLM's discards are exactly the selection
     bias DSR exists to catch (D-052).
  4. Evaluation is deterministic and adversarial: the drift-free bootstrap
     gives the band's BASE probability from the underlying's own history; the
     candidate's edge claim is (stated - base), and a claim without daily
     closes or an options chain inside the horizon cannot graduate.
  5. At most the top 2 graduate to the inbox. The decide cycle still owns the
     trade decision and prices against live quotes - the muse proposes,
     exactly as research and discovery do.
"""

from __future__ import annotations

import json
import random
import re
from typing import Any

from . import competence, ids, market_stats, mcp_client, news_extract
from .config import Config
from .discovery import _options_gate, _plausible_band
from .inbox import Inbox
from .journal import Journal
from .ledger import Ledger
from .llm import build_model
from .research import _parse_json_block
from .wiki import Wiki

#: How many wiki concepts collide with the news per run.
CONCEPTS_PER_RUN = 3
#: Candidates requested from the narration step.
CANDIDATES = 5
#: How many graduate to the inbox at most.
EMIT_TOP = 2
#: A candidate's band must have a bootstrap base probability inside this range:
#: below it the claim is a lottery ticket, above it the claim is vacuous and
#: carries no information either way.
BASE_PROB_FLOOR, BASE_PROB_CEIL = 0.10, 0.90

MUSE_PROMPT = """You are an unusually creative options strategist doing a lateral-thinking \
exercise. Today is {today}. Below are {n} concepts drawn AT RANDOM from your knowledge \
base, plus today's news and prediction-market odds. They were not chosen to fit together - \
that is the point.

Argue about what happens when they collide. Trace domino chains: if X is true and Y is \
happening, who gets squeezed, who benefits second-order, what does the market not yet price? \
Geopolitics, supply chains, sector rotation, positioning - follow the dominoes two or three \
steps, not one.

## Random concepts from the knowledge base
{concepts}

## Recent news
{news}

## Prediction-market odds
{odds}

Produce {k} CANDIDATE THESES. For each, the causal chain must be explicit and each step \
arguable. Rules: liquid US-listed optionable underlyings only.

HORIZONS. Date every horizon from TODAY ({today}), never from memory. \
**Every horizon must fall between {earliest} and {latest} inclusive; anything outside is \
rejected.** Aim the bulk at {preferred} or sooner. A forecast teaches nothing until it \
RESOLVES, and nothing it teaches can move a decision already made - so one slow forecast is \
worth less than three fast ones, and short horizons are harder, which is the point: they test \
judgement rather than drift. But a domino chain needs room to fall: do NOT crush a \
multi-step thesis into one session just to be early. SPREAD your candidates across the \
window rather than clustering on one date, and place each horizon where its own chain \
actually resolves.

band_low/band_high are PRICES IN DOLLARS between which the claim HOLDS at the horizon \
(at least one non-null); probability is your honest P(band holds), not rounded to \
0.5/0.75. Bands must be TIGHT enough to be informative - a band the underlying almost \
always stays inside says nothing; place the band edges where your causal chain actually \
bites. It is fine for some candidates to be long-shot (p 0.15-0.35) if the reasoning is \
genuinely non-obvious - that is where mispricing lives.

Respond with ONLY a JSON array:
[{{"underlying": str, "claim": str, "chain": [str, ...], "direction": "bullish"|"bearish"|"neutral",
   "probability": float, "band_low": float|null, "band_high": float|null,
   "horizon": "YYYY-MM-DD", "suggested_structures": [str, ...]}}]
"""


def _sample_concepts(wiki: Wiki, rng: random.Random, k: int) -> list[tuple[str, str]]:
    """K random concepts, stratified: mostly MARKET content, at most one rule.

    An unstratified sample can draw three technique/ concepts (it did, on the
    first dry run) - and colliding three trading rules produces process talk,
    not market theses. Companies, regimes and events are what collide into
    opportunities; a technique is allowed one slot as a lens.
    """
    root = wiki.root if hasattr(wiki, "root") else wiki.dir
    all_paths = sorted(p for p in root.rglob("*.md")
                       if "positions/" not in str(p) and p.name not in ("log.md",))
    market = [p for p in all_paths if "technique/" not in str(p)]
    rules = [p for p in all_paths if "technique/" in str(p)]
    picks = rng.sample(market, min(k - 1, len(market)))
    if rules and len(picks) < k:
        picks.append(rng.choice(rules))
    out = []
    for p in picks:
        body = p.read_text()
        body = re.sub(r"^---.*?---\s*", "", body, flags=re.DOTALL)  # strip frontmatter
        out.append((str(p.relative_to(root)).removesuffix(".md"), body[:400]))
    return out


async def run(
    tools: dict[str, Any], config: Config, inbox: Inbox, wiki: Wiki,
    journal: Journal, ledger: Ledger, *, verbose: bool = True,
) -> dict[str, Any]:
    # Seeded per-day: a day's collisions are reproducible, tomorrow's differ.
    rng = random.Random(f"muse|{ids.utc_now().date().isoformat()}")

    concepts = _sample_concepts(wiki, rng, CONCEPTS_PER_RUN)
    concept_block = "\n\n".join(f"### {cid}\n{txt}" for cid, txt in concepts)

    news_lines: list[str] = []
    try:
        r = await mcp_client.call(tools, "get_news", limit=30,
                                  exclude_contentless=True, sort="desc")
        items = (r.get("news") or []) if isinstance(r, dict) else []
        news_lines.append(news_extract.render_block(await news_extract.enrich(items, config)))
    except Exception as exc:  # noqa: BLE001
        news_lines.append(f"(news unavailable: {type(exc).__name__})")

    odds_lines: list[str] = []
    try:
        from . import polymarket
        for q in config.polymarket_queries:
            for m in await polymarket.search(q, limit=2):
                odds_lines.append(f"- {m['probability']:.0%} {m['question']}")
    except Exception:  # noqa: BLE001
        pass

    # Derived, not recalled (D-032's date discipline), and shared with every
    # other thesis source so the three cannot drift apart again.
    window = competence.forecast_window(config.deadline, ids.utc_now().date())
    earliest, preferred, latest = window or ("", "", "")
    prompt = MUSE_PROMPT.format(
        today=ids.utc_now().date().isoformat(),
        earliest=earliest or "tomorrow", preferred=preferred or "3 days out",
        latest=latest or "10 days out",
        n=len(concepts), k=CANDIDATES, concepts=concept_block,
        news="\n".join(news_lines) or "(none)", odds="\n".join(odds_lines) or "(none)",
    )
    reply = await build_model(config, role="muse").ainvoke(prompt)
    text = reply.content if isinstance(reply.content, str) else "\n".join(
        b.get("text", "") for b in reply.content
        if isinstance(b, dict) and b.get("type") == "text")
    raw = _parse_json_block(text) or []
    # The model sometimes wraps the array in an object ({"candidates": [...]}),
    # and _parse_json_block salvages {} before [] - so `raw` arrives as a dict,
    # the list-guard below silently skips everything, and the run reports "0
    # candidates" with no evidence of why. Unwrap the first list found.
    if isinstance(raw, dict):
        raw = next((v for v in raw.values() if isinstance(v, list)), [])
    if not raw:
        # Null-path evidence (D-038's own rule, nearly violated here): a parse
        # failure with no trace is undiagnosable. Keep enough of the reply to
        # see WHY next time.
        journal.append("muse_parse_failure", reply_head=text[:400],
                       reply_len=len(text))
        if verbose:
            print(f"[muse] reply did not parse ({len(text)} chars): {text[:160]!r}")

    evaluated: list[dict[str, Any]] = []
    for cand in raw if isinstance(raw, list) else []:
        if not isinstance(cand, dict) or not cand.get("underlying"):
            continue
        u = str(cand["underlying"]).upper()
        verdict = {"underlying": u, "claim": str(cand.get("claim", ""))[:300],
                   "stated": float(cand.get("probability", 0.5)),
                   "chain": cand.get("chain", [])}

        # 1. register EVERY candidate before any gate can discard it
        entry = ledger.register(
            kind="muse", underlying=u, claim=str(cand.get("claim", "")),
            probability=float(cand.get("probability", 0.5)),
            horizon=str(cand.get("horizon", "")),
            band_low=cand.get("band_low"), band_high=cand.get("band_high"),
            notes="muse: " + " -> ".join(str(c) for c in cand.get("chain", []))[:300],
        )
        if entry is None:
            verdict["fate"] = "rejected: unfalsifiable (no band)"
            evaluated.append(verdict)
            continue

        # 2. deterministic evaluation, adversarial by construction
        closes = market_stats.load_closes(config.paths.state, u)
        if closes is None:
            try:
                closes = await market_stats.fetch_daily_closes(tools, u)
                if len(closes) >= 60:
                    market_stats.save_closes(config.paths.state, u, closes)
            except Exception:  # noqa: BLE001
                closes = None
        if not closes or len(closes) < 60:
            verdict["fate"] = "rejected: no usable price history"
            evaluated.append(verdict)
            continue
        if not _plausible_band(cand, closes[-1]):
            verdict["fate"] = f"rejected: band is not a plausible price (spot {closes[-1]:.2f})"
            evaluated.append(verdict)
            continue

        try:
            from datetime import date
            days = (date.fromisoformat(str(cand["horizon"])) - date.today()).days
        except (ValueError, TypeError, KeyError):
            days = 0
        # The muse had NO deadline check at all - it could emit a thesis that
        # resolves after the competition ends, which can never inform anything.
        # And its output clustered at the far end of whatever range it was
        # given: all five live forecasts landed on the last useful day but one.
        if days <= 0 or days > 10:
            verdict["fate"] = f"rejected: horizon {cand.get('horizon')} outside 1-10 days"
            evaluated.append(verdict)
            continue
        if latest and str(cand.get("horizon", "")) > latest:
            verdict["fate"] = (f"rejected: horizon {cand.get('horizon')} resolves too late "
                               f"to act on before {config.deadline} (latest useful {latest})")
            evaluated.append(verdict)
            continue

        factors = market_stats.bootstrap_factors(closes, days, seed=f"muse|{u}")
        spot = closes[-1]
        lo, hi = cand.get("band_low"), cand.get("band_high")
        held = sum(1 for f in factors
                   if (lo is None or spot * f >= lo) and (hi is None or spot * f <= hi))
        base = held / len(factors) if factors else 0.0
        verdict["base_prob"] = round(base, 3)
        verdict["claimed_edge"] = round(verdict["stated"] - base, 3)

        # The gate is about INFORMATION, not the base rate alone. A band that
        # history almost always holds is vacuous ONLY if the model agrees with
        # history - a stated 27% against a 99% base is a breakout call, and
        # that disagreement IS the claim (found on the first live run: the
        # naive ceiling rejected exactly the most interesting candidate). The
        # floor stays hard: a band the drift-free bootstrap can never reach
        # needs a jump the model cannot evidence, which is a lottery ticket
        # whatever the model says.
        disagrees = abs(verdict["claimed_edge"]) >= 0.25
        if base < BASE_PROB_FLOOR:
            verdict["fate"] = f"rejected: base probability {base:.0%} - a lottery ticket"
            evaluated.append(verdict)
            continue
        if base > BASE_PROB_CEIL and not disagrees:
            verdict["fate"] = (f"rejected: base {base:.0%} and the model agrees - "
                               f"vacuous, carries no information")
            evaluated.append(verdict)
            continue

        gate = await _options_gate(tools, u, config.deadline)
        if not gate.get("tradeable"):
            verdict["fate"] = "rejected: no options chain inside the deadline"
            evaluated.append(verdict)
            continue

        verdict["fate"] = "candidate"
        verdict["_cand"] = cand
        evaluated.append(verdict)

    # 3. rank survivors by |claimed edge| - the size of the disagreement with
    # the underlying's own history is the size of the claim being made, and a
    # muse thesis with no disagreement is not worth a slot.
    survivors = [v for v in evaluated if v["fate"] == "candidate"]
    survivors.sort(key=lambda v: -abs(v["claimed_edge"]))
    emitted = 0
    for v in survivors[:EMIT_TOP]:
        c = v.pop("_cand")
        inbox.write("opportunity", {
            "underlying": v["underlying"], "claim": c.get("claim"),
            "direction": c.get("direction", "neutral"),
            "drift_pct": 0.0,
            "band_low": c.get("band_low"), "band_high": c.get("band_high"),
            "horizon": c.get("horizon"),
            "why": ("MUSE domino chain: " + " -> ".join(str(x) for x in c.get("chain", []))
                    + f" | stated {v['stated']:.0%} vs history's base {v['base_prob']:.0%}"),
            "suggested_structures": c.get("suggested_structures", []),
        }, source="muse", trust="primary")
        v["fate"] = "EMITTED"
        emitted += 1
    for v in survivors[EMIT_TOP:]:
        v.pop("_cand", None)
        v["fate"] = "candidate, not emitted (rank)"

    journal.append("muse", concepts=[c for c, _ in concepts],
                   candidates=len(raw) if isinstance(raw, list) else 0,
                   emitted=emitted,
                   fates=[{k: v[k] for k in ("underlying", "fate", "stated")
                           if k in v} for v in evaluated])
    if verbose:
        print(f"[muse] collided {[c for c, _ in concepts]}")
        for v in evaluated:
            edge = f" edge={v.get('claimed_edge'):+}" if "claimed_edge" in v else ""
            print(f"  {v['underlying']:<6} p={v['stated']:.0%}{edge}  {v['fate']}")
            if v.get("chain") and v["fate"] == "EMITTED":
                print(f"         chain: {' -> '.join(str(c) for c in v['chain'])[:150]}")
    return {"candidates": len(evaluated), "emitted": emitted, "evaluated": evaluated}
