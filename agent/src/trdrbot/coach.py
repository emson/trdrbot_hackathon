"""The Coach - autonomous subsystem self-improvement (D-088).

Every subsystem here improves only when a human-led session finds a defect.
This makes improvement a RUNTIME behaviour: a subsystem declares what "good"
looks like as deterministic numbers, declares the choices it could make
differently as variants, and the Coach runs paired A/B trials against its own
evidence, promotes winners, and reverts anything that drifts.

Four rules, each from a measured incident rather than a preference:

  1. Rewards are COMPUTED, never an LLM's opinion of an output. The muse's own
     gauntlet already scores its candidates deterministically; that is the
     reward. (research.py's principle, re-proven by D-081.)
  2. The Coach touches DATA, never code. Variants live in
     `data/state/levers/*.json`. There is deliberately no code path from Coach
     state to a gate threshold, sizing math, or a sentinel definition - the
     human pre-authorises the SPACE, which is what replaces an approval gate.
  3. A lever's experiment may never be scored by machinery that same
     experiment can move (`_disjoint`). The thing that measures must not be
     movable by the thing measured.
  4. The heartbeat is a DIFFERENT record from the output. `coach_run` is
     written every pulse whether or not anything happened, because "found
     nothing" and "never ran" were the same number four separate times in this
     project's history (D-074, D-082, D-086).

elfmem blocks and the constitution are NOT levers and will not become ones:
elfmem's own ADR 0003 simulated four architectures for automatic
constitutional evolution and none beat baseline. That is evidence, not
caution. They get gauges and reporting.

Concurrency: single-process, like the rest of the system (the run lock in
`cli` enforces one loop). Two pulses racing would interleave appends
harmlessly but could double-promote; not defended against, because the
assumption holds everywhere else here too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import health, ids
from .coach_pkg.gauges import (  # noqa: E402,F401 - re-exported for callers
    GAUGE_WINDOW,
    SENTINELS,
    SURVIVED_PREFIXES,
    Sentinel,
    _candidates_per_run,
    _cost_today,
    _last_snapshot_at,
    _minutes_since,
    _muse_rows,
    _seed_entropy,
    _sentinel_churn,
    _sentinel_cost,
    _sentinel_entropy,
    _survival,
    marker,
    snapshot_gauges,
    survived,
)
from .coach_pkg.mutate import (  # noqa: E402,F401 - re-exported for callers
    _FENCE_LINES,
    MUTATE_PROMPT,
    RETRY_SUFFIX,
    _graveyard_digest,
    _rejection_digest,
    clean_prompt,
    mutate,
    validate_prompt,
)
from .coach_pkg.posterior import (  # noqa: E402,F401 - re-exported for callers
    Tally,
    _beta_logpdf,
    is_closed,
    p_challenger_better,
    tally,
    verdict,
)
from .coach_pkg.state import (  # noqa: E402,F401 - re-exported for callers
    CAP_RUNS,
    LEVERS,
    MIN_CANDIDATES,
    MIN_RUNS,
    MUTATE_ATTEMPTS,
    MUTATE_COOLDOWN_MIN,
    PROMOTE_AT,
    SEED_VARIANT_ID,
    SNAPSHOT_EVERY_MIN,
    Lever,
    LeverState,
    Variant,
    _append,
    _state_path,
    enabled,
    events,
    events_path,
    fingerprint,
    floors,
    lever,
    load_state,
    metrics_path,
    opened_event,
    save_state,
    seeds,
)

# --- what a subsystem asks for at run time --------------------------------


@dataclass
class Arms:
    """What the muse needs to run one (possibly paired) cycle."""

    incumbent: Variant
    challenger: Variant | None = None
    exp_id: str | None = None

    @property
    def paired(self) -> bool:
        return self.challenger is not None and self.exp_id is not None


def arms(cfg: Any, lever_name: str, *, seed_text: str) -> Arms:
    """The variants a subsystem should run right now. Never raises.

    One state read gives both the production variant and (when an experiment
    is open) the shadow challenger, so a subsystem needs exactly one Coach call
    on its hot path.
    """
    try:
        st = load_state(cfg, lever_name, seed_text)
        # DISABLED MEANS "RUN NO EXPERIMENTS", NOT "DISCARD THE PROMOTION"
        # (I-93). This returned the SEED while `prompts._active_muse_prompt`,
        # `trdrbot report` and `trdrbot coach` all read the state incumbent - so
        # every journalled decision fingerprinted a prompt nothing was running,
        # which is the outcome `prompts.py` calls worse than no provenance at
        # all. `paused` freezes the incumbent and closes any open trial; this
        # simply stops new ones.
        if not enabled(cfg):
            return Arms(incumbent=st.incumbent)
        if st.challenger and st.exp_id and not is_closed(cfg, st.exp_id):
            return Arms(incumbent=st.incumbent, challenger=st.challenger, exp_id=st.exp_id)
        return Arms(incumbent=st.incumbent)
    except Exception as exc:  # noqa: BLE001 - never break a run over the Coach
        print(f"[coach] arms() failed, running the seed incumbent: {exc!r}")
        return Arms(incumbent=Variant(SEED_VARIANT_ID, seed_text))


def record_trial(cfg: Any, exp_id: str, *, run_nonce: int | str,
                 incumbent: dict[str, Any], challenger: dict[str, Any]) -> None:
    """Append one paired result. Never raises."""
    try:
        # Fold THIS trial in before recording. The row decorates the trial it
        # belongs to, so a posterior read off the tally BEFORE the append
        # describes the state one trial ago (D-093). Rows written before that
        # fix are one trial stale; the tally itself was always correct, because
        # it replays the log rather than trusting the recorded number.
        t = tally(cfg, exp_id) or Tally(exp_id=exp_id, lever="", incumbent="",
                                        challenger="")
        t.add(incumbent, challenger)
        _append(events_path(cfg), {
            "kind": "trial_result", "exp_id": exp_id, "run_nonce": run_nonce,
            "incumbent": incumbent, "challenger": challenger,
            "posterior_p_challenger_better": round(t.posterior, 4),
        })
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] could not record trial: {exc!r}")


# --- the split modules, re-exported ------------------------------------------
#
# `coach` stayed one 1,200-line module mixing seven concerns because each was
# small when it arrived. Splitting on its own section boundaries costs nothing
# and buys two things: the promotion maths becomes testable without a
# filesystem, and the four cross-module reads (usage, calibration, ledger,
# market_stats) stop needing function-local imports to dodge cycles.
#
# Every name is re-exported so `from trdrbot import coach; coach.X` is
# unchanged for every caller and for tests/test_coach.py, which passes
# UNMODIFIED - that was the acceptance gate for this split.

# --- rule 3: a lever may not be scored by machinery it can move ------------


def _disjoint(cfg: Any, want: Lever) -> str:
    """"" if `want` may open an experiment, else why not.

    The muse's gauntlet gates score muse-prompt trials, so no experiment that
    could MOVE those gates may run at the same time. Enforced by the scheduler
    rather than trusted to sequencing, because the failure would be invisible:
    both experiments would look healthy while each quietly rewrote the other's
    ruler.
    """
    for l in LEVERS:
        if l.name == want.name:
            continue
        st = load_state(cfg, l.name, "")
        if not (st.exp_id and not is_closed(cfg, st.exp_id)):
            continue
        shared = set(l.reward_modules) & set(want.reward_modules)
        if shared:
            return (f"{l.name} has an open experiment scored by "
                    f"{sorted(shared)} - the same machinery this lever moves")
    return ""


# --- the pulse -------------------------------------------------------------


async def pulse(cfg: Any, journal: Any, *, seed_override: dict[str, str] | None = None,
                verbose: bool = False) -> dict[str, Any]:
    """One Coach cycle. Called after every muse run and at housekeeping.

    Ordering matters and is deliberate: sentinels run BEFORE promotion, so a
    firing sentinel cannot be beaten to the punch by a promotion in the same
    pulse; the heartbeat is written LAST and unconditionally, so a failure in
    any step above still leaves evidence that the Coach ran.
    """
    # Derived from the lever registry rather than passed in: every caller
    # filled this with the identical `{"muse.prompt": MUSE_PROMPT}` literal,
    # which is a code change in four places the moment a second lever exists.
    # The override stays for tests that need a lever with a controlled seed.
    lever_seeds = seed_override if seed_override is not None else seeds()
    # REPAIR BEFORE ANYTHING READS STATE (I-92). `housekeeping.run` called
    # `reconcile` then `pulse`; `tick.py` called `pulse` alone after every muse
    # run - so on the tick path a crash between `_promote`'s log append and its
    # `save_state` left the pulse seeing a closed experiment, passing the
    # cooldown, spending a mutation call and opening v2 against v0 while the log
    # said v1 was promoted. That night `reconcile` re-applied v1 and cleared the
    # new experiment's id: an `experiment_opened` row with no close row, ever.
    # It is cheap and idempotent, so it belongs here rather than at one caller.
    reconcile(cfg, seed_override)
    state = {"experiments_open": 0, "trials_scored": 0, "trials_scored_today": 0,
             "promotions_today": 0, "sentinels_active": [], "snapshotted": False,
             "opened": None, "closed": None, "muse_runs_since_pulse": 0}
    if not enabled(cfg):
        health.heartbeat(journal, "coach_run", experiments_open=0, trials_scored=0,
                         trials_scored_today=0, promotions_today=0,
                         sentinels_active=[], muse_runs_since_pulse=0, disabled=True)
        return state

    rows: list[dict[str, Any]] = []
    try:
        rows = list(journal.read())
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] could not read the journal: {exc!r}")

    day = ids.utc_now().date().isoformat()
    evs = events(cfg)
    # A heartbeat reports what happened SINCE THE LAST HEARTBEAT, not a running
    # total - the same convention `interim_run` (scored) and `exit_run`
    # (triggered) already use. It matters because `health` SUMS this field
    # across every heartbeat row: a running total would be counted once per
    # pulse, so three pulses over seven trials reported "produced 5". The
    # verdict was right either way (the probe only tests > 0) but the number
    # was not, and a health line nobody can trust is one nobody reads.
    last_beat = ""
    for r in reversed(rows):
        if r.get("kind") == "coach_run":
            last_beat = str(r.get("ts", ""))
            break
    state["trials_scored"] = sum(
        1 for r in evs if r.get("kind") == "trial_result"
        and str(r.get("ts", "")) > last_beat)
    state["trials_scored_today"] = sum(
        1 for r in evs if r.get("kind") == "trial_result" and str(r.get("ts", ""))[:10] == day)
    # How many CHANCES this pulse had to see a trial, same delta convention as
    # `trials_scored`. Housekeeping pulses every 30 minutes while the market is
    # closed; the muse - the only thing that can ever produce a trial (see
    # `record_trial`'s one call site) - runs only while it is open. Without
    # this, a health check counting bare `coach_run` heartbeats since the last
    # trial cannot tell "20 housekeeping cycles over a closed weekend, nothing
    # COULD have been scored" from "20 muse runs in a row, the challenger arm
    # stopped reaching record_trial" - and the first is a quiet Saturday, not a
    # stall (D-093).
    state["muse_runs_since_pulse"] = sum(
        1 for r in rows if r.get("kind") == "muse" and str(r.get("ts", "")) > last_beat)
    state["promotions_today"] = sum(
        1 for r in evs if r.get("kind") == "experiment_closed"
        and r.get("outcome") == "promoted" and str(r.get("ts", ""))[:10] == day)

    # 1. gauges, on their own cadence
    try:
        if _minutes_since(_last_snapshot_at(cfg)) >= SNAPSHOT_EVERY_MIN:
            _append(metrics_path(cfg), {"kind": "snapshot",
                                        "gauges": snapshot_gauges(cfg, rows)})
            state["snapshotted"] = True
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] gauge snapshot failed: {exc!r}")

    # 2. sentinels
    fired: list[Sentinel] = []
    try:
        for s in SENTINELS:
            hit, value, limit = s.check(cfg, rows)
            if hit:
                fired.append(s)
                state["sentinels_active"].append(s.name)
                _append(events_path(cfg), {
                    "kind": "sentinel_fired", "sentinel": s.name, "value": value,
                    "limit": limit, "action": "revert" if s.reverts else "block_new",
                    "meaning": s.meaning})
                marker(cfg, "sentinel", sentinel=s.name, value=value, limit=limit)
    except Exception as exc:  # noqa: BLE001
        print(f"[coach] sentinel check failed: {exc!r}")

    for lv in LEVERS:
        seed = lever_seeds.get(lv.name, "")
        try:
            st = load_state(cfg, lv.name, seed)
            if st.unreadable:
                # KEPT, not overwritten, and not acted on (I-96). Every write
                # below would replace the only evidence of what broke, and
                # `save_state` refuses anyway - so a pulse that pretended to
                # manage this lever would open a SECOND experiment beside the
                # one the log says is running and reuse the variant id
                # `reconcile` keys on.
                print(f"[coach] skipping {lv.name}: {st.blocked}")
                continue
            open_exp = st.exp_id and not is_closed(cfg, st.exp_id)

            # 2b. apply sentinels to this lever
            reverting = [s for s in fired if s.reverts]
            if reverting and open_exp:
                _close(cfg, st, "sentinel_reverted",
                       f"sentinel {reverting[0].name}: {reverting[0].meaning}", journal)
                state["closed"] = "sentinel_reverted"
                open_exp = False
            if fired:
                st.sentinel_block = {"name": fired[0].name, "since": ids.utc_now().isoformat()}
                save_state(cfg, st)
            elif st.sentinel_block:
                st.sentinel_block = None
                save_state(cfg, st)

            # 2c. a human edited state out from under an open experiment
            if open_exp:
                override = _operator_override(cfg, st)
                if override:
                    _close(cfg, st, "operator_override", override, journal)
                    open_exp = False

            # 3. promote / refute / timeout. A PIN blocks promotion as well as
            #    opening (I-94): freezing what production runs and then
            #    promoting into it during the freeze is not a freeze. The trial
            #    keeps gathering evidence and settles when the pin lifts.
            if open_exp and not st.pinned:
                t = tally(cfg, st.exp_id or "")
                if t:
                    outcome, reason = verdict(t, floors(cfg))
                    if outcome == "promoted":
                        # ...and only if it ACTUALLY promoted (I-97). `_promote`
                        # returns early when the challenger is gone, and the
                        # pulse reported `closed="promoted"` and bumped
                        # `promotions_today` regardless: a promotion in the
                        # heartbeat, zero close rows, the incumbent unchanged.
                        if _promote(cfg, st, t, reason, journal):
                            state["closed"] = "promoted"
                            state["promotions_today"] += 1
                            open_exp = False
                    elif outcome:
                        _close(cfg, st, outcome, reason, journal, t=t)
                        state["closed"] = outcome
                        open_exp = False

            # 5. open the next experiment
            if not open_exp and not st.blocked and seed:
                clash = _disjoint(cfg, lv)
                if clash:
                    if verbose:
                        print(f"[coach] not opening on {lv.name}: {clash}")
                elif _minutes_since(st.last_mutation_at) >= MUTATE_COOLDOWN_MIN:
                    # The timestamp is saved BEFORE the attempt, so a mutation
                    # that fails validation three times burns the cooldown.
                    # Deliberate: the failures are LLM calls that already cost
                    # money, and a lever whose challengers keep failing would
                    # otherwise retry every pulse forever. A wasted cooldown is
                    # three hours; an unbounded retry loop is the bill.
                    st.last_mutation_at = ids.utc_now().isoformat()
                    save_state(cfg, st)
                    ch = await mutate(cfg, st, rows, journal)
                    if ch:
                        _open(cfg, st, ch, journal)
                        state["opened"] = ch.id
                        open_exp = True

            if open_exp or (st.exp_id and not is_closed(cfg, st.exp_id)):
                state["experiments_open"] += 1
        except Exception as exc:  # noqa: BLE001 - one lever never breaks the pulse
            print(f"[coach] lever {lv.name} failed this pulse: {exc!r}")

    # 6. the heartbeat, LAST and unconditional
    health.heartbeat(journal, "coach_run",
                     experiments_open=state["experiments_open"],
                     trials_scored=state["trials_scored"],
                     trials_scored_today=state["trials_scored_today"],
                     promotions_today=state["promotions_today"],
                     sentinels_active=state["sentinels_active"],
                     muse_runs_since_pulse=state["muse_runs_since_pulse"])
    if verbose:
        print(f"[coach] open={state['experiments_open']} "
              f"trials={state['trials_scored']} (today {state['trials_scored_today']}) "
              f"sentinels={state['sentinels_active'] or 'none'}")
    return state


def _operator_override(cfg: Any, st: LeverState) -> str:
    """Why this open experiment is no longer the one that was opened, or "".

    **Either arm moving ends the pairing** (I-91). The check compared only the
    challenger id, so a hand-edited INCUMBENT - which README says is supported
    and `gauges.py` admits "corrupts the pairing" - kept the experiment open:
    `arms()` paired the rewritten incumbent with the old challenger, later
    trials folded into one tally under `v0` with two different incumbent texts,
    and D-111's documented undo (swap `incumbent`/`previous`) done mid-trial
    left the log saying v8 vs v0 while `arms()` ran v8 vs v7. `experiment_opened`
    recorded `challenger_fp` and no incumbent fingerprint, so it was not even
    detectable after the fact; it records both now.

    A NULLED challenger is the third case (I-97). The old check was guarded by
    `st.challenger and`, so an operator cancelling one left the lever wedged
    forever: `arms()` unpaired so no trials arrived, nothing closed, nothing
    opened, and `experiments_open` read 1 indefinitely.
    """
    if st.paused:
        return st.blocked
    if not st.challenger:
        return "the challenger was removed from lever state - nothing is being tested"
    t = tally(cfg, st.exp_id or "")
    if t and t.challenger != st.challenger.id:
        return "lever state no longer matches the open experiment"
    opened = opened_event(cfg, st.exp_id or "")
    if not opened:
        return ""
    for arm, fp, variant in (("challenger", opened.get("challenger_fp"), st.challenger),
                             ("incumbent", opened.get("incumbent_fp"), st.incumbent)):
        if fp and fp != variant.fingerprint:
            return (f"the {arm} was edited while the experiment was open "
                    f"({fp[:12]} -> {variant.fingerprint[:12]}) - the pairing no "
                    f"longer describes what ran")
    return ""


def _open(cfg: Any, st: LeverState, challenger: Variant, journal: Any) -> None:
    """Open an experiment. EVENT FIRST, then the state swap.

    Ordering matters and this was the one site that had it backwards. `_close`
    and `_promote` both append before mutating state, deliberately, because the
    log is the truth and the state file is a cache of it - a crash between them
    leaves a recoverable inconsistency that `reconcile` repairs.

    Opening state-first left the opposite: lever state naming an `exp_id` with
    no `experiment_opened` row. `tally()` returns None for it forever and
    `is_closed()` returns False forever, so `arms()` keeps handing the muse a
    paired challenger, `record_trial` keeps writing results nothing can score,
    and `verdict` never runs. The lever is stuck mid-experiment permanently,
    and no existing path repairs it.
    """
    exp_id = ids.journal_id("exp")
    _append(events_path(cfg), {
        "kind": "experiment_opened", "exp_id": exp_id, "lever": st.lever,
        "incumbent": st.incumbent.id, "challenger": challenger.id,
        "challenger_origin": challenger.origin, "challenger_fp": challenger.fingerprint,
        # BOTH arms' fingerprints (I-91). Only the challenger's was recorded, so
        # a hand-edited incumbent mid-trial was undetectable even after the
        # fact - and it is the arm the operator is most likely to edit.
        "incumbent_fp": st.incumbent.fingerprint,
        "floors": floors(cfg)})
    st.challenger = challenger
    st.exp_id = exp_id
    st.next_variant_n = max(st.next_variant_n + 1,
                            int(challenger.id.lstrip("v") or 0) + 1)
    save_state(cfg, st)
    journal.append("coach_experiment_opened", lever=st.lever, exp_id=exp_id,
                   incumbent=st.incumbent.id, challenger=challenger.id)
    marker(cfg, "experiment_opened", lever=st.lever,
           detail=f"{st.incumbent.id} vs {challenger.id}")


def _close(cfg: Any, st: LeverState, outcome: str, reason: str, journal: Any,
           t: Tally | None = None) -> None:
    """Close WITHOUT promoting. The challenger's full text goes into the event
    so the graveyard needs no second lookup, and so a good idea killed by an
    unrelated sentinel is recoverable by a human reading the log."""
    exp_id, ch = st.exp_id, st.challenger
    _append(events_path(cfg), {
        "kind": "experiment_closed", "exp_id": exp_id, "lever": st.lever,
        "outcome": outcome, "reason": reason,
        "runs": t.runs if t else None,
        "final_posterior": round(t.posterior, 4) if t else None,
        "challenger": ch.id if ch else None,
        "challenger_text": ch.text if ch else None,
        # WHAT IT WAS TRYING TO DO (I-95). `_graveyard_digest` renders
        # `r.get("rationale")` from this row, which never carried one - so
        # "Variants already tried and beaten (do not re-propose these)" read
        # `- v1 (refuted, P=0.03): ` and the mutator re-litigated dead ideas,
        # which is the one thing that section exists to prevent.
        "rationale": ch.rationale if ch else ""})
    st.challenger, st.exp_id = None, None
    save_state(cfg, st)
    journal.append("coach_experiment_closed", lever=st.lever, exp_id=exp_id,
                   outcome=outcome, reason=reason[:200])
    marker(cfg, "experiment_closed", lever=st.lever, detail=f"{outcome}: {reason[:80]}")


def _promote(cfg: Any, st: LeverState, t: Tally, reason: str, journal: Any) -> bool:
    """Swap in the challenger.

    Ordering is crash-safe on purpose: the CLOSE is appended first, then the
    state swap. A crash between them leaves a `promoted` close whose lever
    state still shows the old incumbent - which `reconcile` detects and
    re-applies, because the append-only log is the truth and the state file is
    a cache of it.
    """
    ch = st.challenger
    if ch is None:
        return False  # the caller must not report a promotion that did not happen
    _append(events_path(cfg), {
        "kind": "experiment_closed", "exp_id": st.exp_id, "lever": st.lever,
        "outcome": "promoted", "reason": reason, "runs": t.runs,
        "final_posterior": round(t.posterior, 4),
        "challenger": ch.id, "challenger_text": ch.text,
        "rationale": ch.rationale,
        "promoted_from": st.incumbent.id})
    st.previous = st.incumbent
    st.incumbent = Variant(id=ch.id, text=ch.text, since=ids.utc_now().isoformat(),
                           origin=ch.origin, rationale=ch.rationale)
    st.challenger, st.exp_id = None, None
    save_state(cfg, st)
    journal.append("coach_promotion", lever=st.lever, promoted=ch.id,
                   previous=st.previous.id, reason=reason[:200])
    marker(cfg, "promotion", lever=st.lever,
           detail=f"{st.previous.id} -> {ch.id}")
    print(f"[coach] PROMOTED {st.lever}: {st.previous.id} -> {ch.id} ({reason})")
    return True


def reconcile(cfg: Any, seed_override: dict[str, str] | None = None) -> list[str]:
    """Repair lever state against the event log, which is the truth.

    Two repairs, both for a crash between an append and the state swap:

    - a promotion that was LOGGED but never applied (the `_promote` ordering
      is deliberate so this is always recoverable);
    - an experiment named in state that has NO `experiment_opened` row. That
      one was unreachable before `_open` was reordered, and permanent: the
      tally is None forever, `is_closed` is False forever, so the muse keeps
      running a paired trial whose results can never be scored. Clearing it
      lets the lever open a fresh experiment.

    Idempotent: a promotion whose incumbent already matches is skipped.
    """
    lever_seeds = seed_override if seed_override is not None else seeds()
    applied: list[str] = []
    for lv in LEVERS:
        st = load_state(cfg, lv.name, lever_seeds.get(lv.name, ""))

        if st.unreadable:
            continue  # kept for inspection; nothing here may write over it (I-96)

        if st.exp_id and not opened_event(cfg, st.exp_id):
            orphan = st.exp_id
            st.challenger, st.exp_id = None, None
            save_state(cfg, st)
            applied.append(f"{lv.name}: cleared orphaned experiment {orphan}")
            print(f"[coach] {lv.name}: experiment {orphan} has no opened event - "
                  f"cleared so the lever is not stuck mid-trial")

        # ...and the MIRROR of that (I-92): an `experiment_opened` row whose
        # experiment is no longer in state and was never closed. `trdrbot
        # report` derives open experiments from the log and listed it forever
        # while the `coach.open_experiments` gauge derives from state and said
        # 0 - one question, two readers, two answers. Closing it makes the log
        # self-consistent, which is the whole basis for the state file being a
        # cache of it.
        rows = events(cfg)
        closed_ids = {r.get("exp_id") for r in rows if r.get("kind") == "experiment_closed"}
        for r in rows:
            if (r.get("kind") != "experiment_opened" or r.get("lever") != lv.name
                    or r.get("exp_id") in closed_ids or r.get("exp_id") == st.exp_id):
                continue
            _append(events_path(cfg), {
                "kind": "experiment_closed", "exp_id": r.get("exp_id"), "lever": lv.name,
                "outcome": "abandoned",
                "reason": "no longer in lever state and never closed - a crash between "
                          "the open and a later write, repaired by reconcile",
                "runs": None, "final_posterior": None,
                "challenger": r.get("challenger"), "challenger_text": None,
                "rationale": ""})
            closed_ids.add(r.get("exp_id"))
            applied.append(f"{lv.name}: closed dangling experiment {r.get('exp_id')}")
            print(f"[coach] {lv.name}: experiment {r.get('exp_id')} was opened and never "
                  f"closed and is no longer in state - closed as abandoned")

        closes = [r for r in events(cfg)
                  if r.get("kind") == "experiment_closed" and r.get("lever") == lv.name
                  and r.get("outcome") == "promoted"]
        if not closes:
            continue
        last = closes[-1]
        want = str(last.get("challenger") or "")
        # UNAPPLIED means the lever has never held `want` at all (D-111). This
        # used to re-apply whenever the incumbent was not `want` - so the
        # operator's documented undo (edit the lever's state file back) was
        # re-promoted on the next pulse, every pulse, forever. A crash between
        # the `experiment_closed` row and `save_state` leaves `want` nowhere in
        # the state: repair that. An operator who reverted by swapping
        # incumbent and previous leaves `want` as `previous`: respect that.
        held_before = st.previous is not None and st.previous.id == want
        if (want and st.incumbent.id != want and not held_before
                and last.get("challenger_text")):
            st.previous = st.incumbent
            st.incumbent = Variant(id=want, text=str(last["challenger_text"]),
                                   since=str(last.get("ts", "")), origin="mutation")
            st.challenger, st.exp_id = None, None
            save_state(cfg, st)
            applied.append(f"{lv.name}: {st.previous.id} -> {want}")
    return applied
