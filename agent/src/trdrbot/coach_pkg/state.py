"""The Coach's ground state: thresholds, the lever registry, variants, the log.

The layer everything else in the package sits on. Split out because `gauges`
and `mutate` both need it and neither should import the orchestrator - which
is what the five function-local imports inside the old single module were
working around.

Nothing here decides anything. Promotion maths is `posterior`, measurement is
`gauges`, challenger generation is `mutate`, and the orchestration that calls
all three is `coach` itself.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .. import ids, store

# --- promotion defaults ----------------------------------------------------
#
# The evidence unit is a CANDIDATE, not a run: one muse run yields ~5
# candidates through ~8 gates, so 8 runs is ~40 Bernoulli trials per arm -
# plenty for a real effect to clear 0.90 while still refusing a lucky streak.
# The RUN floor exists only so a single freak run cannot carry a promotion,
# and the CANDIDATE floor exists because 8 runs of one candidate each is 8
# trials wearing 8 runs' clothing.
PROMOTE_AT = 0.90
FUTILITY_AT = 0.05
MIN_RUNS = 8
MIN_CANDIDATES = 24
FUTILITY_MIN_RUNS = 6
CAP_RUNS = 40

#: Gauges are snapshotted on a cadence, not every pulse - the pulse itself is
#: event-driven (after a muse run, and at housekeeping) and a snapshot per
#: event would make the series sampling-rate-dependent rather than time-series.
SNAPSHOT_EVERY_MIN = 30
#: An LLM call generates challengers. Cheap tier, but not free, and there is
#: nothing to learn from mutating faster than trials can score.
MUTATE_COOLDOWN_MIN = 180
#: Attempts per mutation, each fed the previous rejection reason. Measured
#: against the real model: a first attempt fails validation a meaningful
#: fraction of the time - always the same way, literal braces written in prose
#: (`{X and Y}`), which `.format()` reads as a placeholder - and a second
#: attempt told exactly that usually fixes it. Cheap tier, so three attempts
#: cost far less than losing a whole mutation cooldown to a fixable typo.
MUTATE_ATTEMPTS = 3

SEED_VARIANT_ID = "v0"


# --- registry --------------------------------------------------------------


@dataclass(frozen=True)
class Lever:
    """A declared space the Coach may move within, autonomously.

    Everything the generic machinery needs about a lever lives HERE, as data.
    It did not: `mutate` formatted the muse's placeholders into its prompt and
    passed the muse's validator anchors as literals, `_rejection_digest` read
    muse journal rows by kind, and the seed text was a
    `{"muse.prompt": muse.MUSE_PROMPT}` dict copy-pasted at three call sites.
    Registering a second lever meant editing the Coach's internals - which is
    exactly what "the Coach touches data, never code" was supposed to make
    unnecessary.

    Deliberately DATA, not callables. A callable in a module-level registry
    would have to be imported at module scope, and importing subsystems from
    the registry is how the coach package's import cycle would come straight
    back - `seed_ref` is resolved lazily instead (see `seed_text`).

    `reward_modules` is what enforces rule 3: an experiment on this lever is
    scored by these modules, so no OTHER lever naming any of them may run an
    experiment at the same time.
    """

    name: str
    subsystem: str
    reward_modules: tuple[str, ...]
    kind: str  # prompt | policy
    #: Where the seed text lives, as (module, attribute). Resolved on demand.
    seed_ref: tuple[str, str] = ("", "")
    #: Format placeholders a variant MUST preserve verbatim, or the subsystem's
    #: `.format()` call raises on a prompt the Coach itself produced.
    placeholders: tuple[str, ...] = ()
    #: Substrings a variant must keep - the anchors that stop a mutation
    #: quietly dropping the part of the contract the parser depends on.
    must_contain: tuple[str, ...] = ()
    #: Journal kind whose recent rows carry this lever's rejection evidence,
    #: fed to the mutation prompt so a challenger knows what keeps failing.
    #: Empty means no digest is available, which is a fine steady state.
    evidence_kind: str = ""
    #: "How it is scored", in the mutator's own prompt. It was a muse-shaped
    #: paragraph hardcoded in `MUTATE_PROMPT`, so a second lever's challengers
    #: would have been told they were judged by the muse's gates. The registry
    #: promised everything the generic machinery needs lives here; this is the
    #: piece that did not.
    reward_description: str = ""
    #: What a variant must not change - the contracts with code, in the
    #: mutator's prompt. Same reason as `reward_description`.
    contract_note: str = ""
    #: An optional deterministic validator, (module, attribute) resolved on
    #: demand exactly like `seed_ref`: `callable(text) -> ""` when the text is
    #: safe to run, else the defect. A policy lever's text is DATA with its own
    #: schema, and the format-template checks that guard a prompt say nothing
    #: about it.
    validator_ref: tuple[str, str] = ("", "")


#: Placeholders the muse's prompt template must keep. Lives with the lever
#: that owns it rather than inside the generic mutation code.
_MUSE_PLACEHOLDERS = ("today", "n", "k", "concepts", "news", "odds",
                      "earliest", "preferred", "latest")

LEVERS: tuple[Lever, ...] = (
    Lever(
        "muse.prompt", "muse", ("muse.gates",), "prompt",
        seed_ref=("trdrbot.muse", "MUSE_PROMPT"),
        placeholders=_MUSE_PLACEHOLDERS,
        # The schema keys the gates READ. Drop `"probability"` and `_prob`
        # defaults every candidate to 0.5, every gate still passes, and
        # fabricated 0.5s enter calibration via mark_stated (D-112).
        must_contain=("band_low_pct", "band_high_pct", "JSON array",
                      '"probability"', '"horizon"', '"underlying"', '"claim"'),
        evidence_kind="muse",
        # Verbatim from the mutation prompt it used to be hardcoded in, so the
        # rendered prompt the muse's challengers are generated from is
        # byte-identical (test_coach pins it).
        reward_description=(
            "Each candidate this prompt produces is run through fixed gates: it needs "
            "usable price history, a falsifiable band, a plausible band, a horizon "
            "inside the allowed window, a bootstrap base probability that is neither a "
            "lottery ticket nor vacuous, and a tradeable options chain. The reward is "
            "the FRACTION of candidates that survive every gate. You cannot change the "
            "gates."),
        contract_note=(
            "Do not change the output schema, the placeholder names, or the "
            "percent-move band convention - those are contracts with code."),
    ),
    # The playbook's catalogue of structure families (notes/026). A POLICY
    # lever: the text is YAML data with its own validator, not a template.
    # Scored by arithmetic no lever can move, so it may run beside the muse's
    # experiment - `_disjoint` sees no shared reward module.
    Lever(
        "playbook.catalogue", "playbook",
        ("optmath.band_conditional", "experiments.simulate"), "policy",
        seed_ref=("trdrbot.playbook", "SEED_CATALOGUE"),
        placeholders=(),
        must_contain=("families:", "shapes:", "anchor:", "sigma:"),
        evidence_kind="playbook",
        reward_description=(
            "Each family you propose is instantiated on the live option chain for every "
            "opportunity whose thesis SHAPE it declares (range, bull_target, bear_target, "
            "bull_floor, bear_ceiling), with strikes placed from your anchors and sigma "
            "offsets. Each instance then meets fixed gates: every leg quoted, loss bounded, "
            "pays after entry costs IF the thesis band holds, and wins at least 25 points "
            "more often when the band holds than when it fails. The reward is the FRACTION "
            "of instances that survive every gate. A family that fits a shape badly fails "
            "often; a shape no family covers scores as failures."),
        contract_note=(
            "Keep the YAML schema exactly: version, families[].name/shapes/legs[].right/side/"
            "qty/at.anchor/at.sigma. Anchors are spot, band_low, band_high, band_mid; sigma "
            "within -2.5..2.5. Between 3 and 12 families; every shape covered; every family "
            "must have a bounded loss and no naked short. Put the full replacement YAML in "
            "the `prompt` field."),
        validator_ref=("trdrbot.playbook", "validate_catalogue"),
    ),
)

#: TO REGISTER A NEW LEVER, in full:
#:
#:   1. Add a `Lever(...)` above declaring its data fields - including how it
#:      is scored and what a variant may not change, because the mutator
#:      renders those per lever and a lever that omits them is mutated blind.
#:      A `policy` lever (data, not a `.format()` template) names a
#:      `validator_ref` for its own schema.
#:   2. Its subsystem calls `coach.arms(cfg, "<name>", seed_text=<seed>)` on
#:      its hot path and runs BOTH arms through ONE gate cascade - the shadow
#:      arm reaching identical verdicts while writing nothing.
#:   3. Its subsystem calls `coach.record_trial(...)` with the paired scores.
#:
#: That is the whole contract; no Coach internals change. Know the cost before
#: you do it: a live lever spends one mutation call per cooldown plus a second
#: full subsystem run per trial, for as long as an experiment is open.


def lever(name: str) -> Lever | None:
    return next((l for l in LEVERS if l.name == name), None)


def seed_text(lv: Lever) -> str:
    """The lever's in-code seed prompt, imported on demand.

    Lazy and forgiving by design: the registry must not import subsystems at
    module scope (cycles), and a seed that cannot be resolved must not take a
    pulse down with it. An empty seed already means "run the incumbent from
    state", which is the honest degrade.
    """
    module, attr = lv.seed_ref
    if not module:
        return ""
    try:
        import importlib

        return str(getattr(importlib.import_module(module), attr, ""))
    except Exception as exc:  # noqa: BLE001 - a bad ref must not break a pulse
        print(f"[coach] lever {lv.name}: cannot resolve seed {lv.seed_ref}: {exc!r}")
        return ""


def validator_of(lv: Lever) -> Callable[[str], str] | None:
    """The lever's own deterministic validator, imported on demand, or None.

    Same lazy, forgiving shape as `seed_text` and for the same reason: the
    registry must not import subsystems at module scope. A validator that
    cannot be resolved is reported and the generic checks still run - but a
    policy lever without its validator would accept any text that merely
    parses as nothing in particular, so `mutate` refuses to open on one.
    """
    module, attr = lv.validator_ref
    if not module:
        return None
    try:
        import importlib

        fn = getattr(importlib.import_module(module), attr, None)
        return fn if callable(fn) else None
    except Exception as exc:  # noqa: BLE001 - a bad ref must not break a pulse
        print(f"[coach] lever {lv.name}: cannot resolve validator {lv.validator_ref}: {exc!r}")
        return None


def seeds() -> dict[str, str]:
    """{lever: seed text} for every registered lever.

    Replaces a `{"muse.prompt": muse.MUSE_PROMPT}` literal that existed at
    three call sites - the shape that makes a second lever a code change in
    four places instead of one declaration.
    """
    return {lv.name: seed_text(lv) for lv in LEVERS}


# --- variants and lever state ---------------------------------------------


@dataclass
class Variant:
    id: str
    text: str
    fingerprint: str = ""
    since: str = ""
    origin: str = "seed"  # seed | mutation | human
    #: WHY this variant was proposed, in the mutator's own words. Carried onto
    #: the `experiment_closed` row so the graveyard can render it (I-95): the
    #: digest read `r.get("rationale")` from a row that only ever carried
    #: `challenger_text`, so "Variants already tried and beaten (do not
    #: re-propose these)" always read `- v1 (refuted, P=0.03): ` and the
    #: mutator re-litigated dead ideas, which is what the section exists to
    #: prevent.
    rationale: str = ""

    def __post_init__(self) -> None:
        # Recompute rather than trust: a human editing the state file by hand
        # is a supported steering move, and a stale fingerprint beside edited
        # text would silently mislabel every trial that variant runs in.
        self.fingerprint = fingerprint(self.text)


def fingerprint(text: str) -> str:
    """Delegates to `prompts.fingerprint` - one hash, one meaning. Kept as a
    name here because lever state files store its output and callers use it."""
    from ..prompts import fingerprint as _fp

    return _fp(text)


@dataclass
class LeverState:
    lever: str
    incumbent: Variant
    previous: Variant | None = None
    challenger: Variant | None = None
    exp_id: str | None = None
    paused: bool = False
    #: The demo-day freeze the operator config has always promised (I-94).
    #: Commit 10563c8 deleted the code and left the comment, `load_state` stopped
    #: reading the key and `save_state` dropped it on the next write - so the
    #: live `muse.prompt.json` still carries `"pinned": false` and a pinned
    #: lever opened an experiment on the next pulse and could promote mid-demo.
    #:
    #: DIFFERENT FROM `paused`, and that difference is the point: `paused`
    #: closes any open experiment as an operator override, while `pinned`
    #: freezes what PRODUCTION runs - no new experiments and no promotion - and
    #: leaves an open trial gathering evidence for when the pin lifts.
    pinned: bool = False
    sentinel_block: dict[str, Any] | None = None
    next_variant_n: int = 1
    last_mutation_at: str = ""
    #: The state file existed and could not be parsed. Set by `load_state`, and
    #: `save_state` REFUSES to write over it (I-96): the docstring promised the
    #: unreadable file was kept for a human, and then the cooldown save and
    #: `_open`'s save in the same pulse replaced it with a fresh seed state -
    #: which spawned a second experiment beside the one the log said was open,
    #: reset `next_variant_n` so the new challenger reused the id `reconcile`
    #: keys on, and ran a prior promotion as the seed until housekeeping.
    unreadable: bool = False

    @property
    def blocked(self) -> str:
        """Why no new experiment may open. Empty string when clear."""
        if self.unreadable:
            return "the lever's state file is unreadable and is being kept for inspection"
        if self.paused:
            return "paused by operator"
        if self.pinned:
            return "pinned by operator (production frozen; no promotion)"
        if self.sentinel_block:
            return f"sentinel: {self.sentinel_block.get('name')}"
        return ""


def _levers_dir(cfg: Any) -> Path:
    return Path(cfg.paths.state) / "levers"


def _state_path(cfg: Any, lever_name: str) -> Path:
    return _levers_dir(cfg) / f"{lever_name}.json"


def _variant(raw: Any) -> Variant | None:
    if not isinstance(raw, dict) or not raw.get("text"):
        return None
    return Variant(id=str(raw.get("id") or SEED_VARIANT_ID), text=str(raw["text"]),
                   since=str(raw.get("since") or ""), origin=str(raw.get("origin") or "seed"),
                   rationale=str(raw.get("rationale") or ""))


def load_state(cfg: Any, lever_name: str, seed_text: str) -> LeverState:
    """Lever state, or a fresh one seeded from the in-code default.

    A corrupt or unreadable file degrades to incumbent-only and says so. It is
    deliberately NOT overwritten here: a human may want to read what broke, and
    a self-healing write would destroy the evidence. The next legitimate state
    change rewrites it.
    """
    path = _state_path(cfg, lever_name)
    seed = Variant(id=SEED_VARIANT_ID, text=seed_text, since="", origin="seed")
    if not path.exists():
        return LeverState(lever=lever_name, incumbent=seed)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        inc = _variant(raw.get("incumbent")) or seed
        return LeverState(
            lever=lever_name,
            incumbent=inc,
            previous=_variant(raw.get("previous")),
            challenger=_variant(raw.get("challenger")),
            exp_id=raw.get("exp_id") or None,
            paused=bool(raw.get("paused")),
            pinned=bool(raw.get("pinned")),
            sentinel_block=raw.get("sentinel_block") or None,
            next_variant_n=int(raw.get("next_variant_n") or 1),
            last_mutation_at=str(raw.get("last_mutation_at") or ""),
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"[coach] lever state unreadable ({lever_name}): {exc!r} - "
              f"running incumbent-only from the in-code seed, and KEEPING the file")
        return LeverState(lever=lever_name, incumbent=seed, unreadable=True)


def save_state(cfg: Any, st: LeverState) -> None:
    """Atomic: write-temp then os.replace, so a crash mid-write cannot leave a
    half-file that the next load would read as corrupt.

    **Refuses to write over an unreadable file** (I-96). `load_state`'s
    docstring promised the corrupt file was kept for a human to read, and then
    the very next save in the same pulse overwrote it with a fresh seed state.
    """
    if st.unreadable:
        print(f"[coach] not overwriting the unreadable state file for {st.lever} - "
              f"it is the only evidence of what broke")
        return
    path = _state_path(cfg, st.lever)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "lever": st.lever,
        "paused": st.paused,
        "pinned": st.pinned,
        "incumbent": asdict(st.incumbent),
        "previous": asdict(st.previous) if st.previous else None,
        "challenger": asdict(st.challenger) if st.challenger else None,
        "exp_id": st.exp_id,
        "sentinel_block": st.sentinel_block,
        "next_variant_n": st.next_variant_n,
        "last_mutation_at": st.last_mutation_at,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# --- the event log ---------------------------------------------------------


def events_path(cfg: Any) -> Path:
    return Path(cfg.paths.data) / "experiments.jsonl"


def metrics_path(cfg: Any) -> Path:
    return Path(cfg.paths.data) / "metrics.jsonl"


def _append(path: Path, row: dict[str, Any]) -> None:
    """Advisory: bookkeeping never blocks a run."""
    store.append_jsonl(path, {"ts": ids.utc_now().isoformat(), **row}, advisory=True)


def _read(path: Path) -> list[dict[str, Any]]:
    return store.read_jsonl(path)[0]


def events(cfg: Any) -> list[dict[str, Any]]:
    return _read(events_path(cfg))


def opened_event(cfg: Any, exp_id: str) -> dict[str, Any] | None:
    """The `experiment_opened` row for this experiment, or None.

    The log is the truth and the state file is a cache of it, so "what were the
    two arms when this experiment opened" is a question only the log can answer
    (I-91). Both fingerprints are on that row now, which is what makes an
    edit to EITHER arm mid-trial detectable at all.
    """
    if not exp_id:
        return None
    return next((r for r in events(cfg)
                 if r.get("kind") == "experiment_opened" and r.get("exp_id") == exp_id), None)


# --- config accessors ------------------------------------------------------


def enabled(cfg: Any) -> bool:
    return bool((getattr(cfg, "coach", None) or {}).get("enabled", True))


def floors(cfg: Any, lever_name: str = "") -> dict[str, Any]:
    """Promotion floors: the global `coach.*` values, overridden per lever by
    `coach.levers.<name>.*` where present.

    Per lever because the right bar depends on the reward's base rate. The
    muse survives ~89% of its gates, so an equal challenger has almost no room
    to look better by luck; a lever scored near 50% has symmetric headroom and
    the same sequential peeking promotes an equal arm about one time in three
    under the global 0.90 (notes/026 section 5). One number for both is wrong
    for one of them.
    """
    c = getattr(cfg, "coach", None) or {}
    per = ((c.get("levers") or {}).get(lever_name) or {}) if lever_name else {}

    def pick(key: str, default: Any) -> Any:
        return per.get(key, c.get(key, default))

    return {
        "min_runs": pick("min_runs", MIN_RUNS),
        "min_candidates": pick("min_candidates", MIN_CANDIDATES),
        "promote_at": pick("promote_at", PROMOTE_AT),
        "futility_at": pick("futility_at", FUTILITY_AT),
        "futility_min_runs": pick("futility_min_runs", FUTILITY_MIN_RUNS),
        "cap_runs": pick("cap_runs", CAP_RUNS),
    }


