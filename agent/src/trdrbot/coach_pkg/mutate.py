"""Generating a challenger variant: the prompt, the cleaners, the validator.

The only LLM-touching part of the Coach, and the only part that can produce
something the rest of the system will run. Everything here is about refusing a
bad candidate cheaply - `validate_prompt` names the exact defect so the retry
can correct it.
"""

from __future__ import annotations

import contextlib
from typing import Any

from .. import ids
from .state import (
    MUTATE_ATTEMPTS,
    LeverState,
    Variant,
    events,
    fingerprint,
    lever,
)

# --- mutation: generating challengers --------------------------------------

MUTATE_PROMPT = """You improve the prompt of an automated system, judged by a \
deterministic scorer you cannot influence. Return ONE replacement prompt.

## The prompt in production now (everything between the two rule lines)
- - - - - - - - - -
{incumbent}
- - - - - - - - - -

## How it is scored
Each candidate this prompt produces is run through fixed gates: it needs usable \
price history, a falsifiable band, a plausible band, a horizon inside the allowed \
window, a bootstrap base probability that is neither a lottery ticket nor vacuous, \
and a tradeable options chain. The reward is the FRACTION of candidates that survive \
every gate. You cannot change the gates.

## What has actually been rejected recently, by gate
{rejections}

## Variants already tried and beaten (do not re-propose these)
{graveyard}

Change exactly ONE thing you can argue will raise the survival fraction, and say \
what in `rationale`. Do not change the output schema, the placeholder names, or the \
percent-move band convention - those are contracts with code.

**The prompt is passed through Python's `.format()`, so EVERY literal curly brace \
must be doubled - `{{` and `}}` - everywhere in the text, not only inside the JSON \
example. `{{X and Y}}` in ordinary prose is a format placeholder and will crash the \
system. The ONLY single braces allowed are these placeholders, which must all survive, \
spelled exactly, with no others added: {placeholders}.**

Respond with ONLY a JSON object:
{{"rationale": "one sentence", "prompt": "the full replacement prompt text"}}
"""

#: Appended when a first attempt fails validation. The check is deterministic and
#: its message names the exact defect, so handing that back is strictly better
#: than spending the next pulse's call rediscovering it - and measured: the very
#: first contract-test run produced `KeyError: ' and '` from braces written in
#: prose, which is precisely the mistake a model corrects when told.
RETRY_SUFFIX = """

## Your previous attempt was REJECTED
{reason}

Fix exactly that and return the corrected JSON object. Change nothing else.
"""

#: Framing the model tends to echo back around the prompt it was handed.
#: Measured on the first live mutation: the reply copied the delimiter lines
#: verbatim into the challenger text, and nothing downstream would have
#: noticed - the result still formats, still validates, and would have gone
#: into production carrying two lines of this module's own scaffolding. A
#: prompt is a precise artefact; contaminating it with the harness that
#: produced it is a quiet quality leak.
_FENCE_LINES = ("<<<prompt", "prompt", "```", "```json", "```text",
                "- - - - - - - - - -", "---")


def clean_prompt(text: str) -> str:
    """Strip echoed delimiters and code fences from a generated prompt."""
    lines = text.strip().splitlines()
    while lines and lines[0].strip().lower() in _FENCE_LINES:
        lines.pop(0)
    while lines and lines[-1].strip().lower() in _FENCE_LINES:
        lines.pop()
    return "\n".join(lines).strip()


def validate_prompt(text: str, incumbent: str, placeholders: tuple[str, ...],
                    *, must_contain: tuple[str, ...] = ()) -> str:
    """"" if the text is safe to run, else the reason it is not.

    A mutated prompt is a `.format()` template, so a stray brace from a JSON
    example is a live crash on the next muse run. Every failure mode here is
    cheaper to catch now than in production, and the checks are deterministic -
    the model's opinion of its own output is not evidence.
    """
    if not text or len(text) < 200:
        return "too short to be a replacement prompt"
    if len(text) > 2 * len(incumbent):
        return f"{len(text)} chars against an incumbent of {len(incumbent)} - prompt bloat"
    # NORMALISED, not exact (I-98). `mutate()` runs `clean_prompt()` - which
    # strips - before this, and `MUSE_PROMPT` ends with a newline, so an ECHO of
    # the incumbent (which a model told to "change exactly ONE thing" sometimes
    # returns) passed as a novel challenger. Both arms were then token-identical
    # after formatting: a coin flip that runs to the 40-run cap, roughly two
    # weeks and 40 challenger calls, and times out.
    if fingerprint(clean_prompt(text)) == fingerprint(clean_prompt(incumbent)):
        return "identical to the incumbent once normalised - nothing to test"
    for token in must_contain:
        if token not in text:
            return f"dropped the contract token {token!r}"
    # Safety first: an UNKNOWN placeholder is a live KeyError on the next run.
    try:
        text.format(**{p: "x" for p in placeholders})
    except (KeyError, IndexError, ValueError) as exc:
        return f"not a safe format template ({type(exc).__name__}: {exc})"
    # Then PRESENCE (D-112). `str.format` catches an EXTRA placeholder and says
    # nothing about a missing one, so a challenger could delete
    # {concepts}/{news}/{odds} - the muse's whole mandate - score 5/5 on gate
    # survival, and promote. Every declared placeholder must still be used.
    for p in placeholders:
        if "{" + p + "}" not in text:
            return f"dropped the placeholder {{{p}}}"
    return ""


def _rejection_digest(rows: list[dict[str, Any]], kind: str = "", n: int = 30) -> str:
    """What keeps failing, BY GATE, so a challenger can aim at it.

    `kind` is the lever's declared `evidence_kind` rather than a hardcoded
    "muse": a lever with no evidence stream is a fine steady state and simply
    gets no digest, which is what the generic path must tolerate.

    Keyed through `ledger.gate_of` (I-99). It used to key on
    `fate.split(" - ")[0][:80]`, which keeps the embedded base rate, date or
    price - so nine rejections across four gates rendered as nine `x1` lines and
    the section headed "by gate" aggregated nothing. `gate_of` is D-104's
    canonical classifier and already reads every historical wording; one
    definition, not two.
    """
    from ..ledger import gate_of

    if not kind:
        return "(no rejection evidence for this lever)"
    gates: dict[str, int] = {}
    for r in [r for r in rows if r.get("kind") == kind][-20:]:
        for f in (r.get("fates") or []):
            fate = str(f.get("fate", ""))
            if fate.startswith("rejected"):
                g = gate_of(fate)
                gates[g] = gates.get(g, 0) + 1
    if not gates:
        return "(nothing rejected recently)"
    return "\n".join(f"- {k}  x{v}" for k, v in
                     sorted(gates.items(), key=lambda kv: -kv[1])[:n])


def _graveyard_digest(cfg: Any, lever_name: str, n: int = 4) -> str:
    """Defeated challengers, so the mutation never re-litigates a dead idea.

    D-076 recorded its killed mechanisms for exactly this reason: a rejected
    candidate is worth more as a record than as a thing tried twice.
    """
    dead = [r for r in events(cfg)
            if r.get("kind") == "experiment_closed" and r.get("lever") == lever_name
            and r.get("outcome") in ("refuted", "timeout")]
    if not dead:
        return "(none yet)"
    out = []
    for r in dead[-n:]:
        out.append(f"- {r.get('challenger')} ({r.get('outcome')}, "
                   f"P={r.get('final_posterior')}): "
                   f"{str(r.get('rationale') or '')[:160]}")
    return "\n".join(out)


async def mutate(cfg: Any, st: LeverState, rows: list[dict[str, Any]],
                 journal: Any) -> Variant | None:
    """One validated challenger, or None. Never raises."""
    from ..llm import build_model, parse_json_array, parse_json_object, text_of

    lv = lever(st.lever)
    if lv is None:
        print(f"[coach] no lever registered as {st.lever!r} - cannot mutate")
        return None
    try:
        prompt = MUTATE_PROMPT.format(
            incumbent=st.incumbent.text,
            rejections=_rejection_digest(rows, lv.evidence_kind),
            graveyard=_graveyard_digest(cfg, st.lever),
            placeholders=", ".join("{" + p + "}" for p in lv.placeholders),
        )
        model = build_model(cfg, role="coach_mutate")
        # Two attempts, because the validator's message names the exact defect
        # and a model corrects a named mistake. A rejected challenger otherwise
        # costs the whole mutation cooldown before anything is tried again.
        attempt_prompt, bad, parsed = prompt, "", None
        for attempt in range(1, MUTATE_ATTEMPTS + 1):
            reply = await model.ainvoke(attempt_prompt)
            text = text_of(reply)
            # The mutation reply is ONE {rationale, prompt} object. Asking
            # for the array and taking [0] was this caller re-guessing a shape
            # the parser would not state; now the parser states it, and a
            # model that wrapped it in a list is handled there.
            candidates = parse_json_array(text)
            parsed = candidates[0] if candidates else parse_json_object(text) or None
            if not isinstance(parsed, dict) or not parsed.get("prompt"):
                bad = "reply did not parse to {rationale, prompt}"
            else:
                candidate = clean_prompt(str(parsed["prompt"]))
                bad = validate_prompt(
                    candidate, st.incumbent.text, lv.placeholders,
                    must_contain=lv.must_contain)
                if not bad:
                    vid = f"v{st.next_variant_n}"
                    journal.append("coach_mutation", lever=st.lever, variant=vid,
                                   attempt=attempt,
                                   rationale=str(parsed.get("rationale", ""))[:300])
                    return Variant(id=vid, text=candidate,
                                   since=ids.utc_now().isoformat(), origin="mutation",
                                   # Carried so the close row can render it and
                                   # the graveyard stops re-proposing dead ideas
                                   # (I-95). It used to live only on the
                                   # journal's `coach_mutation` row.
                                   rationale=str(parsed.get("rationale", ""))[:300])
            journal.append("coach_mutation_rejected", lever=st.lever, reason=bad,
                           attempt=attempt,
                           rationale=str((parsed or {}).get("rationale", ""))[:200]
                           if isinstance(parsed, dict) else "")
            attempt_prompt = prompt + RETRY_SUFFIX.format(reason=bad)
        return None
    except Exception as exc:  # noqa: BLE001 - a failed mutation costs one pulse
        print(f"[coach] mutation failed: {exc!r}")
        with contextlib.suppress(Exception):
            journal.append("coach_mutation_rejected", lever=st.lever,
                           reason=f"{type(exc).__name__}: {exc}"[:200])
        return None


