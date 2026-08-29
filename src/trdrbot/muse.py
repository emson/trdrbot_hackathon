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

from . import coach, competence, ids, market_stats, mcp_client, news_extract
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

band_low_pct/band_high_pct are PERCENT MOVES FROM THE UNDERLYING'S CURRENT PRICE between \
which the claim HOLDS at the horizon - band_low_pct=-8 and band_high_pct=-2 means "it falls \
between 2%% and 8%%". At least one non-null. **Do NOT give absolute dollar prices: you do not \
know the current price of anything here, and a level recalled from memory will be wrong by a \
factor of three.** The prices are computed from these percentages against live data. \
probability is your honest P(band holds), not rounded to \
0.5/0.75. Bands must be TIGHT enough to be informative - a band the underlying almost \
always stays inside says nothing; place the band edges where your causal chain actually \
bites. It is fine for some candidates to be long-shot (p 0.15-0.35) if the reasoning is \
genuinely non-obvious - that is where mispricing lives.

Respond with ONLY a JSON array:
[{{"underlying": str, "claim": str, "chain": [str, ...], "direction": "bullish"|"bearish"|"neutral",
   "probability": float, "band_low_pct": float|null, "band_high_pct": float|null,
   "horizon": "YYYY-MM-DD", "suggested_structures": [str, ...]}}]
"""


#: Widest percentage move the muse may claim for a horizon inside 10 days.
#: Beyond this it is not a thesis, it is a typo - and a band 3x from spot is
#: exactly what absolute-price bands produced.
MAX_BAND_PCT = 60.0


class _ShadowEntry:
    """Stands in for a `ledger.Entry` on the challenger arm."""

    __slots__ = ("id",)

    def __init__(self) -> None:
        self.id = "shadow"


class ShadowLedger:
    """A Ledger-shaped no-op, for scoring a challenger variant without writing.

    The challenger arm of an A/B trial must reach exactly the same verdicts as
    production while touching NOTHING - no ledger row, no inbox item, no
    `mark_stated`. The obvious implementation (a `shadow=True` flag threaded
    through the gate cascade) would put a branch inside every gate, and two
    arms running subtly different code is precisely the failure this project
    keeps finding: two EV loops (D-074), two clocks (D-074), two calibration
    numbers (D-076). So the arms share ONE gate cascade byte for byte, and only
    the ledger object differs.

    `register` mirrors the one piece of real gate logic the ledger owns:
    returning None when a candidate carries no band at all, which production
    reads as "unfalsifiable" and refuses. Getting that wrong would let the
    challenger past a gate the incumbent must pass, which is an unfair trial
    that would look like a genuine improvement.
    """

    def __init__(self) -> None:
        self.registered = 0

    def register(self, *, band_low: float | None = None,
                 band_high: float | None = None, **_: Any) -> "_ShadowEntry | None":
        if band_low is None and band_high is None:
            return None
        self.registered += 1
        return _ShadowEntry()

    def mark_rejected(self, *_a: Any, **_k: Any) -> bool:
        return True

    def mark_stated(self, *_a: Any, **_k: Any) -> bool:
        return True


def _reject(ledger: Ledger, entry: "Any", reason: str) -> None:
    """Record the gate that refused a candidate, on its own ledger row.

    The reason used to live only in the journal, so "which gate rejects most,
    and was it right?" needed a manual join across two stores. A rejected
    candidate still carries a band and a horizon, so it still RESOLVES - and
    comparing the refusal against what actually happened is a scored test of
    the gate's threshold. It scores the system, not the agent.
    """
    if entry is not None:
        try:
            ledger.mark_rejected(entry.id, reason)
        except Exception as exc:  # noqa: BLE001 - bookkeeping never blocks a run
            print(f"[muse] could not record rejection: {exc!r}")


def _bands_from_pct(cand: dict[str, Any], spot: "float | None") -> tuple[float | None, float | None]:
    """Percent moves -> prices, computed against live closes.

    **The muse is never asked for an absolute price.** It was, and it answered
    from training data: NVDA [650, 920] against a spot of 218.97, QQQ
    [355, 385] against 716, MSTR [420, 860] against 126.87. Its own gates
    caught 13 of 15 such candidates, so the defect was contained - but it was
    contained by refusing whole LLM calls, which is an expensive way to be
    right.

    The project already states the rule, in research.py's own docstring:
    *numbers are COMPUTED, never asked of the LLM*. A model can reason about
    "this falls 2-8%"; it cannot recall what a stock costs today. So ask for
    the relationship and compute the number.

    Note this needs no spot at PROMPT time, which matters because the muse
    names arbitrary underlyings - a central price service could not have
    supplied them in advance, because nobody knows which names it will pick
    until it has answered.
    """
    if spot is None or spot <= 0:
        return (None, None)

    def one(key: str) -> float | None:
        v = cand.get(key)
        if v is None:
            return None
        try:
            pct = float(v)
        except (TypeError, ValueError):
            return None
        if abs(pct) > MAX_BAND_PCT:
            return None
        return round(spot * (1.0 + pct / 100.0), 2)

    lo, hi = one("band_low_pct"), one("band_high_pct")
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return (lo, hi)


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
    # Read the DURABLE half of each concept, not its first 400 characters.
    # Those two used to be the same thing and it poisoned the collisions: the
    # 400-char window ran past "# What it is" into "# Bull case", so the muse
    # was handed "Closed 228.17, +5.2% on the week" as raw material 15.8 hours
    # after it stopped being true (measured - that exact NVDA dossier was one
    # of this date's three picks, against a live tape of 223.90, -1.8%).
    #
    # A concept does not go stale because a price did. Reading the durable
    # section means an old dossier stays USEFUL rather than needing to be
    # excluded, which is what keeps the pool from starving on a day with no
    # research run - and colliding a month-old company concept with today's
    # news is the muse's whole mandate, not a defect.
    out = []
    for p in picks:
        cid = str(p.relative_to(root)).removesuffix(".md")
        c = wiki.read(cid)
        text = c.durable_text() if c else re.sub(
            r"^---.*?---\s*", "", p.read_text(), flags=re.DOTALL).strip()
        out.append((cid, text[:400]))
    return out


async def _generate(prompt_text: str, fields: dict[str, Any], config: Config,
                    journal: Journal, *, variant: str, verbose: bool) -> list[dict[str, Any]]:
    """Format, invoke, parse. The prompt arrives as a PARAMETER - this is the
    seam the Coach's prompt lever moves, and the only thing that differs
    between the two arms of a trial."""
    prompt = prompt_text.format(**fields)
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
                       reply_len=len(text), variant=variant)
        if verbose:
            print(f"[muse] reply did not parse ({len(text)} chars): {text[:160]!r}")
    return raw if isinstance(raw, list) else []


async def _evaluate(
    raw: list[dict[str, Any]], tools: dict[str, Any], config: Config,
    ledger: "Ledger | ShadowLedger", *, latest: str, variant: str,
    cache: dict[str, Any],
) -> list[dict[str, Any]]:
    """The gate cascade. ONE copy, run by both arms of a trial.

    `cache` memoises the two network-dependent gate inputs (daily closes and
    the options chain) for the length of a run, so the challenger is judged on
    IDENTICAL data to the incumbent. Without it a quote moving between the two
    arms' calls would score as a variant difference - an unfairness that would
    be invisible in the results and would slowly promote noise.
    """
    evaluated: list[dict[str, Any]] = []
    for cand in raw:
        if not isinstance(cand, dict) or not cand.get("underlying"):
            continue
        u = str(cand["underlying"]).upper()
        verdict = {"underlying": u, "claim": str(cand.get("claim", ""))[:300],
                   "stated": float(cand.get("probability", 0.5)),
                   "chain": cand.get("chain", [])}

        # 1. PRICE HISTORY FIRST, because the band arrives as a percentage move
        # and cannot become a price without one. This is data availability, not
        # a judgement gate - a candidate that gets this far is still registered
        # below whatever happens next.
        ckey = f"closes|{u}"
        if ckey in cache:
            closes = cache[ckey]
        else:
            closes = market_stats.load_closes(config.paths.state, u)
            if closes is None:
                try:
                    closes = await market_stats.fetch_daily_closes(tools, u)
                    if len(closes) >= 60:
                        market_stats.save_closes(config.paths.state, u, closes)
                except Exception:  # noqa: BLE001
                    closes = None
            cache[ckey] = closes
        usable = bool(closes) and len(closes) >= 60
        spot = closes[-1] if usable else None
        band_low, band_high = _bands_from_pct(cand, spot)

        # 2. register EVERY candidate before any gate can discard it - the
        # multiple-testing correction needs the trials that failed (D-052).
        # But registered as a TRIAL, not as a claim: `probability_stated=False`
        # until it survives every gate below, at which point `mark_stated`
        # promotes it. Registration and belief are different events, and
        # conflating them put 13 of this ledger's 15 muse rows into the
        # calibration sample as claims the muse had itself rejected - bands 3x
        # from spot, base rates of 0% and 100%, a horizon already in the past.
        entry = ledger.register(
            kind="muse", underlying=u, claim=str(cand.get("claim", "")),
            probability=float(cand.get("probability", 0.5)),
            probability_stated=False,
            horizon=str(cand.get("horizon", "")),
            band_low=band_low, band_high=band_high,
            variant=variant,
            notes="muse: " + " -> ".join(str(c) for c in cand.get("chain", []))[:300],
        )
        if not usable:
            verdict["fate"] = "rejected: no usable price history"
            _reject(ledger, entry, verdict["fate"])
            evaluated.append(verdict)
            continue
        if entry is None:
            verdict["fate"] = "rejected: unfalsifiable (no band)"
            _reject(ledger, entry, verdict["fate"])
            evaluated.append(verdict)
            continue
        # The bands are now COMPUTED from live closes, so a level recalled from
        # training data cannot get in. `_plausible_band` stays as a backstop for
        # an absurd percentage rather than as the primary defence it used to be.
        cand["band_low"], cand["band_high"] = band_low, band_high
        if not _plausible_band(cand, spot):
            verdict["fate"] = f"rejected: band is not a plausible price (spot {spot:.2f})"
            _reject(ledger, entry, verdict["fate"])
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
            _reject(ledger, entry, verdict["fate"])
            evaluated.append(verdict)
            continue
        if latest and str(cand.get("horizon", "")) > latest:
            verdict["fate"] = (f"rejected: horizon {cand.get('horizon')} resolves too late "
                               f"to act on before {config.deadline} (latest useful {latest})")
            _reject(ledger, entry, verdict["fate"])
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
            _reject(ledger, entry, verdict["fate"])
            evaluated.append(verdict)
            continue
        if base > BASE_PROB_CEIL and not disagrees:
            verdict["fate"] = (f"rejected: base {base:.0%} and the model agrees - "
                               f"vacuous, carries no information")
            _reject(ledger, entry, verdict["fate"])
            evaluated.append(verdict)
            continue

        gkey = f"gate|{u}"
        if gkey not in cache:
            cache[gkey] = await _options_gate(tools, u, config.deadline)
        gate = cache[gkey]
        if not gate.get("tradeable"):
            verdict["fate"] = "rejected: no options chain inside the deadline"
            _reject(ledger, entry, verdict["fate"])
            evaluated.append(verdict)
            continue

        # Survived every gate - NOW it is a claim the system stands behind,
        # and only now may it score calibration.
        ledger.mark_stated(entry.id)
        verdict["fate"] = "candidate"
        verdict["_cand"] = cand
        evaluated.append(verdict)
    return evaluated


def _score_arm(evaluated: list[dict[str, Any]], asked: int) -> dict[str, Any]:
    """One arm's paired-trial reward: candidates that survived every gate.

    A reply that parses to NOTHING is scored as `asked` failures rather than as
    an empty result. GLM-5.2 spent an entire 8,000-token budget on invisible
    reasoning and returned zero characters (D-084) - a "successful" call that
    no other mechanism penalises. If an empty reply scored nothing, a variant
    that always produced nothing would be unfalsifiable by its own reward.
    """
    hits = sum(1 for v in evaluated if coach.survived(v.get("fate")))
    total = len(evaluated) or asked
    return {"candidates": len(evaluated), "survived": hits,
            "failed": max(0, total - hits),
            "fates": [str(v.get("fate", ""))[:80] for v in evaluated]}


async def run(
    tools: dict[str, Any], config: Config, inbox: Inbox, wiki: Wiki,
    journal: Journal, ledger: Ledger, *, verbose: bool = True,
) -> dict[str, Any]:
    # Which prompt variant is live, and is a challenger being trialled?
    arms = coach.arms(config, "muse.prompt", seed_text=MUSE_PROMPT)

    # Seeded per-day PLUS a per-run nonce. The day-only seed made every run in
    # a day collide the SAME concepts - correct when the muse ran once a day,
    # but it would have made every paired trial a repeat of one sample rather
    # than a fresh draw. The nonce is derived (today's muse rows), never a
    # clock, so a run stays reproducible from the journal alone.
    nonce = sum(1 for r in journal.read()
                if r.get("kind") == "muse"
                and str(r.get("ts", ""))[:10] == ids.utc_now().date().isoformat())
    rng = random.Random(f"muse|{ids.utc_now().date().isoformat()}|{nonce}")

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
    fields = dict(
        today=ids.utc_now().date().isoformat(),
        earliest=earliest or "tomorrow", preferred=preferred or "3 days out",
        latest=latest or "10 days out",
        n=len(concepts), k=CANDIDATES, concepts=concept_block,
        news="\n".join(news_lines) or "(none)", odds="\n".join(odds_lines) or "(none)",
    )

    # Shared across BOTH arms so the challenger is judged on identical data.
    cache: dict[str, Any] = {}

    raw = await _generate(arms.incumbent.text, fields, config, journal,
                          variant=arms.incumbent.id, verbose=verbose)
    evaluated = await _evaluate(raw, tools, config, ledger, latest=latest,
                                variant=arms.incumbent.id, cache=cache)

    # --- the challenger arm: scored, never acted on ------------------------
    # It writes NOTHING - no ledger row (the shadow ledger), no inbox item (the
    # emission below is incumbent-only), no thesis journal row. A challenger
    # that registered candidates would inflate D-052's trial count with
    # experiment artefacts and re-pollute calibration, which is D-080's exact
    # defect rebuilt by the mechanism meant to improve things.
    trial_result: dict[str, Any] | None = None
    if arms.paired and arms.challenger is not None:
        try:
            ch_raw = await _generate(arms.challenger.text, fields, config, journal,
                                     variant=arms.challenger.id, verbose=False)
            ch_eval = await _evaluate(ch_raw, tools, config, ShadowLedger(),
                                      latest=latest, variant=arms.challenger.id,
                                      cache=cache)
            trial_result = _score_arm(ch_eval, CANDIDATES)
        except Exception as exc:  # noqa: BLE001
            # A raised call is a VOID trial, not a loss: an HTTP 500 says
            # nothing about the variant's quality, and scoring it as failure
            # would let one provider outage refute a good challenger (D-084's
            # distinction between a loud external failure and a silent bad one).
            trial_result = {"voided": type(exc).__name__}
            print(f"[muse] challenger arm voided: {exc!r}")
        coach.record_trial(
            config, arms.exp_id or "", run_nonce=nonce,
            incumbent=_score_arm(evaluated, CANDIDATES), challenger=trial_result)

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
                   prompt_variant=arms.incumbent.id,
                   prompt_fp=arms.incumbent.fingerprint,
                   exp_id=arms.exp_id,
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
