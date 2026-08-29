"""Silent-failure detector (D-038). `trdrbot health`.

`doctor` answers "can this system start?" - credentials, MCP, model. Nothing
answered "is it actually doing anything?", and that is the gap every serious
bug in this project has walked through: attribution ran dead for days while
every log line read healthy, sensors declared a policy nothing read, a status
never got wired, stats described a market six weeks stale.

The shared shape is a subsystem that RUNS but never PRODUCES, where silence is
indistinguishable from a legitimate "nothing to do". So the detector is:

    ran >= threshold AND produced == 0  ->  suspicious

plus a few state checks for the other recurring classes - a value whose
absence quietly loosens a constraint, and a plan stated in prose that no code
enforces.

This does not gate anything (D-009). It reports, which is what turns a silent
failure into a loud one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OK, WARN, BAD = "ok", "warn", "PROBLEM"


@dataclass(frozen=True)
class Probe:
    """One subsystem's liveness question."""

    name: str
    #: journal kinds that mean "this subsystem ran"
    ran_kinds: tuple[str, ...]
    #: given the rows where it ran, how many times did it produce its output?
    produced: Callable[[list[dict[str, Any]]], int]
    #: below this many runs, silence is not yet evidence
    min_runs: int
    #: what it means if it ran plenty and produced nothing
    meaning: str
    #: How much work was actually AVAILABLE. Optional, and the difference
    #: between "broken" and "idle" (D-070): attribution ran 36x and produced
    #: nothing, which read as a hard FAIL - but every run recorded `pending: 0`,
    #: so there was simply nothing due yet (theses resolve at their horizon).
    #: A health check that cries wolf is worse than none, because it trains
    #: the reader to skip the one line that finally matters. When this is
    #: given and returns 0, silence is explained rather than alarming.
    work: Callable[[list[dict[str, Any]]], int] | None = None
    #: Some subsystems are CORRECT when they have NEVER YET produced anything.
    #: An exit engine is a fire alarm: evaluating every tick and never firing
    #: is the healthy state, not a stall. Set only where zero output so far is
    #: a plausible steady state - never as a way to silence a probe that is
    #: genuinely dead.
    never_producing_is_ok: bool = False
    #: Distinct from the above, and NOT implied by it. Some subsystems fire
    #: once as a genuinely one-shot event (a triggered exit closes ITS
    #: position; nothing about that predicts the next 40 ticks), so staying
    #: quiet after one real production is not staleness. Others - interim
    #: scoring above all - are the OPPOSITE: producing once and then going
    #: silent despite continued eligibility is the exact shape a units bug
    #: took once already (D-074), and that staleness check must survive
    #: `never_producing_is_ok` being set for the same probe's "not yet due"
    #: case. Keep this False unless a one-shot event is genuinely all the
    #: subsystem is allowed to ever produce for one input.
    stopping_after_output_is_ok: bool = False


PROBES: tuple[Probe, ...] = (
    Probe(
        "decide", ("decision",),
        lambda rows: len(rows), 1,
        "the agent never reasoned - inbox never fills, or decide is never reached",
    ),
    Probe(
        "execution", ("no_op", "execution"),
        lambda rows: sum(len(r.get("order_calls") or []) for r in rows), 6,
        "many decide cycles, zero orders ever placed. Correct if declining "
        "deliberately; a dead order path looks identical from here",
    ),
    Probe(
        "attribution", ("attribution_run",),
        lambda rows: sum(int(r.get("attributed") or 0) for r in rows), 3,
        "the view-vs-structure loop is not turning - check skipped_no_price",
        work=lambda rows: sum(int(r.get("pending") or 0) for r in rows),
    ),
    Probe(
        "research", ("research",),
        lambda rows: sum(int(r.get("opportunities") or 0) for r in rows), 2,
        "research runs but never emits a usable opportunity - check rejections",
    ),
    Probe(
        "discovery", ("discovery",),
        lambda rows: sum(int(r.get("opportunities") or 0) for r in rows), 2,
        "discovery nominates but nothing survives its gates",
    ),
    # `ran` is the HEARTBEAT, not the trigger. Reading `exit` rows as evidence
    # the engine ran made this a tautology: an open position with five armed
    # rules and a live debounce history reported "never ran" simply because
    # nothing had breached. `work` is the number of rule-checks actually
    # performed, so "evaluated 40 times, nothing breached" reads as healthy and
    # "positions open, zero rules evaluated" reads as broken - which are very
    # different things and used to be the same line.
    Probe(
        "exit_rules", ("exit_run",),
        lambda rows: sum(int(r.get("triggered") or 0) for r in rows), 0,
        "positions were watched and no rule ever fired - check that the "
        "thresholds are reachable against the net-cost base",
        work=lambda rows: sum(int(r.get("rules") or 0) for r in rows),
        never_producing_is_ok=True,
        stopping_after_output_is_ok=True,
    ),
    # `ran` is the HEARTBEAT, not the output. Reading the output rows as
    # evidence of running makes the probe a tautology (see the `interim_run`
    # note in housekeeping): it can only report "never ran" or "ran Nx,
    # produced N", so a scorer that fired eight times and then died read as
    # healthy for two days and ~250 ticks.
    #
    # `never_producing_is_ok`: the bands are deliberately wide (25%/50%) so
    # they do not fire on noise, and most positions plausibly close - by
    # stop, target or deadline - before ever crossing one. "Eligible every
    # cycle, never scored" is therefore the SAME shape as an exit rule that
    # never breaches: a threshold watcher that stays quiet for a position's
    # whole life is a legitimate, common, healthy outcome, not evidence of
    # brokenness. Found live: a position at -12.66% (well under the first
    # 25% band) read `interim_scoring FAIL` after six housekeeping runs
    # across under two hours of a freshly opened position - the exact false
    # alarm this flag exists to prevent, one probe over from where D-082
    # first fixed it for exit_rules.
    #
    # `stopping_after_output_is_ok` is DELIBERATELY NOT set here, unlike
    # exit_rules. The class of bug this probe WAS built to catch - a units
    # mismatch silently zeroing every score despite real moves, after having
    # scored correctly once - is exactly "produced before, now suspiciously
    # quiet", and that staleness check must survive `never_producing_is_ok`
    # covering the unrelated "not yet due" case. Regression-tested directly
    # against the original bug's shape (score once, then 40 silent runs).
    Probe(
        "interim_scoring", ("interim_run",),
        lambda rows: sum(int(r.get("scored") or 0) for r in rows), 3,
        "positions were eligible every cycle and none was ever scored - check "
        "the materiality bands against the units position_pnl_pct returns",
        work=lambda rows: sum(int(r.get("eligible") or 0) for r in rows),
        never_producing_is_ok=True,
    ),
    # The improvement loop watching itself. `ran` is the heartbeat written
    # every pulse; `produced` is trials actually scored. The keys read here
    # MUST match what `coach.pulse` writes - a probe reading a key nobody
    # writes reports a confident zero forever, which is how `_market_pulse`
    # stayed dead with a passing test (D-074). There is a test pinning the two
    # key sets together.
    #
    # `never_producing_is_ok`: no open experiment is a legitimate steady state
    # (nothing to trial yet, a sentinel is blocking, or a human pinned the
    # lever), and `work` reports open experiments so "0 trials, 0 experiments"
    # reads as idle rather than broken.
    #
    # `stopping_after_output_is_ok` is deliberately NOT set: scoring trials and
    # then falling silent WHILE an experiment is still open is exactly the
    # shape of a broken assignment path, and that is the failure this probe
    # exists to catch.
    Probe(
        "coach", ("coach_run",),
        lambda rows: sum(int(r.get("trials_scored") or 0) for r in rows), 3,
        "experiments are open but no trial is being scored - the muse is not "
        "running, or the challenger arm is not reaching record_trial",
        work=lambda rows: sum(int(r.get("experiments_open") or 0) for r in rows),
        never_producing_is_ok=True,
    ),
)

#: A subsystem can produce for a while and then stop. Totals hide that
#: perfectly - which is exactly how a dead interim scorer kept reporting
#: "ran 8x, produced 8". Once this many runs have gone by since the last
#: output, say so.
STALE_AFTER_RUNS = 20


def _rows(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    out = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _runs_since_last_output(ran: list[dict[str, Any]], probe: Probe) -> int:
    """How many runs have gone by with nothing produced, counting back.

    Zero when the most recent run produced. Also zero when there was no WORK
    available in those runs - an idle subsystem is not a stalled one, the same
    distinction `Probe.work` draws for the totals.
    """
    idle_tail = 0
    for row in reversed(ran):
        if probe.produced([row]) > 0:
            break
        idle_tail += 1
    if idle_tail and probe.work is not None and probe.work(ran[-idle_tail:]) == 0:
        return 0
    return idle_tail


def check(journal_path: Path, positions: list[Any]) -> list[tuple[str, str, str]]:
    """Return (level, subject, detail). Pure - takes data, returns findings."""
    rows = _rows(journal_path)
    findings: list[tuple[str, str, str]] = []

    # --- 1. subsystems that run but never produce -----------------------
    for probe in PROBES:
        ran = [r for r in rows if r.get("kind") in probe.ran_kinds]
        made = probe.produced(ran) if ran else 0
        if not ran:
            level = WARN if probe.min_runs > 0 else OK
            findings.append((level, probe.name, "never ran"))
        elif made == 0 and probe.work is not None and probe.work(ran) == 0:
            findings.append((OK, probe.name,
                             f"ran {len(ran)}x, nothing was due - idle, not stalled"))
        elif made == 0 and probe.never_producing_is_ok:
            findings.append((OK, probe.name,
                             f"ran {len(ran)}x, nothing to report - watching, not stalled"))
        elif made == 0 and len(ran) >= probe.min_runs > 0:
            findings.append((BAD, probe.name,
                             f"ran {len(ran)}x, produced nothing - {probe.meaning}"))
        else:
            # It has produced SOMETHING - but when? A total cannot tell a live
            # subsystem from one that worked at the start and then died.
            since = (0 if probe.stopping_after_output_is_ok
                     else _runs_since_last_output(ran, probe))
            if since >= STALE_AFTER_RUNS:
                findings.append((BAD, probe.name,
                                 f"ran {len(ran)}x, produced {made} - but nothing in the "
                                 f"last {since} runs. {probe.meaning}"))
            else:
                findings.append((OK, probe.name, f"ran {len(ran)}x, produced {made}"))

    # --- 2. the null paths, when they explain themselves ----------------
    skipped = sum(int(r.get("skipped_no_price") or 0)
                  for r in rows if r.get("kind") == "attribution_run")
    if skipped:
        findings.append((BAD, "attribution.spot",
                         f"{skipped} attribution(s) skipped for want of a price - "
                         "the loop is stalled on data, not on judgment"))

    rejects: dict[str, int] = {}
    for r in rows:
        if r.get("kind") == "research_rejected":
            rejects[str(r.get("reason"))] = rejects.get(str(r.get("reason")), 0) + 1
    for reason, n in sorted(rejects.items(), key=lambda kv: -kv[1]):
        findings.append((WARN if n < 3 else BAD, f"rejected:{reason}",
                         f"{n} opportunities dropped - a repeating reason is a "
                         "systematic mismatch, not bad luck"))

    # --- 3. errors that keep coming back --------------------------------
    causes: dict[str, int] = {}
    for r in rows:
        if r.get("kind") == "error":
            causes[str(r.get("cause"))] = causes.get(str(r.get("cause")), 0) + 1
    for cause, n in causes.items():
        findings.append((WARN if n < 3 else BAD, f"error:{cause}",
                         f"{n} occurrences - a 'transient' seen repeatedly is permanent"))

    # --- 4. absence that quietly loosens a constraint --------------------
    from .exit_rules import watched_signals

    for p in positions:
        if getattr(p, "status", "") not in ("open", "opening"):
            continue
        if getattr(p, "max_loss_usd", None) is None:
            findings.append((BAD, f"position:{p.position_id[:28]}",
                             "no max_loss_usd - counts as ZERO risk against the "
                             "book caps, silently loosening them"))
        watching = watched_signals(p)
        if "underlying" not in watching:
            findings.append((WARN, f"position:{p.position_id[:28]}",
                             f"watches {', '.join(watching) or 'nothing'} - no "
                             "thesis-level stop, so a break in the underlying "
                             "closes nothing"))
        # No thesis at all is worse than an unfalsifiable one: the position
        # will NEVER be attributed, silently, because pending() filters on
        # thesis_claim being truthy. Found live: the very first position ever
        # opened (tick 1) went get_option_chain -> place_option_order ->
        # record_position with simulate_experiments never called in between,
        # so the `shared["thesis"]` record_position reads from was never
        # populated. BAD, not WARN - this position's view-vs-structure
        # learning is permanently lost, not merely degraded.
        if not getattr(p, "thesis_claim", ""):
            findings.append((BAD, f"position:{p.position_id[:28]}",
                             "no thesis recorded at all - will NEVER be attributed "
                             "(simulate_experiments likely skipped before entry)"))
        # An unfalsifiable thesis can never be attributed either, so it can
        # never teach - a lesser version of the same failure.
        elif not (p.thesis_band_low is not None or p.thesis_band_high is not None):
            findings.append((WARN, f"position:{p.position_id[:28]}",
                             "thesis has no band - unscoreable, will never attribute"))

    return findings


def render(findings: list[tuple[str, str, str]]) -> str:
    mark = {OK: "  ok  ", WARN: " warn ", BAD: " FAIL "}
    lines = ["", "=== trdrbot health: is anything silently doing nothing? ===", ""]
    for level in (BAD, WARN, OK):
        rows = [f for f in findings if f[0] == level]
        for _, subject, detail in rows:
            lines.append(f"[{mark[level]}] {subject:<34} {detail}")
    bad = sum(1 for f in findings if f[0] == BAD)
    warn = sum(1 for f in findings if f[0] == WARN)
    lines += ["", f"{bad} problem(s), {warn} warning(s). "
                  "Nothing here is a gate - it is evidence." , ""]
    return "\n".join(lines)
