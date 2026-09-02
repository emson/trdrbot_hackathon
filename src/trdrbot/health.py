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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ids, store

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
    #: The fields a row of this kind MUST carry, enforced at WRITE time by
    #: `heartbeat()`. Only the `*_run` heartbeats declare it - output rows
    #: (decision, execution, research, discovery) are wire formats this table
    #: only reads.
    #:
    #: This closes the half of D-074/D-082 that kept coming back. Those probes
    #: read journal fields BY NAME that five emitters wrote by hand, with
    #: nothing tying the two together - and a probe reading a key nobody
    #: writes reports a confident zero forever. It shipped twice.
    heartbeat_fields: tuple[str, ...] = ()
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
        heartbeat_fields=("pending", "attributed", "skipped_no_price"),
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
        heartbeat_fields=("positions", "rules", "triggered", "blind_signals"),
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
        "the materiality bands against the units position_pnl_fraction returns",
        work=lambda rows: sum(int(r.get("eligible") or 0) for r in rows),
        heartbeat_fields=("eligible", "scored"),
        never_producing_is_ok=True,
    ),
    # Learning is ADVISORY on the fast path (D-091 made it so, because an
    # elfmem failure inside reconcile was disarming that tick's stop-losses) -
    # and advisory means failures are survivable, not that they are acceptable.
    # `produced` is events that actually completed, so "5 fills, 5 errors"
    # reads as broken while "5 fills, 0 errors" reads as working. The row has
    # existed since D-091 with nothing reading it, which is half of the very
    # gap this work unit closes.
    Probe(
        "learning", ("learn_run",),
        lambda rows: sum(int(r.get("fills") or 0) + int(r.get("resolutions") or 0)
                         - int(r.get("errors") or 0) for r in rows), 2,
        "fills and resolutions happened and every one of them failed to learn - "
        "check the learn_error rows for the cause",
        work=lambda rows: sum(int(r.get("fills") or 0) + int(r.get("resolutions") or 0)
                              for r in rows),
        heartbeat_fields=("fills", "resolutions", "errors"),
    ),
    # The improvement loop watching itself. `ran` is the heartbeat written
    # every pulse; `produced` is trials actually scored. The keys read here
    # MUST match what `coach.pulse` writes - a probe reading a key nobody
    # writes reports a confident zero forever, which is how `_market_pulse`
    # stayed dead with a passing test (D-074). There is a test pinning the two
    # key sets together.
    #
    # `never_producing_is_ok`: no open experiment is a legitimate steady state
    # (nothing to trial yet, a sentinel is blocking, or a human paused the
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
        "the muse ran but no trial is being scored - the challenger arm is "
        "not reaching record_trial",
        # NOT `experiments_open`: that only says a lever is ACTIVE, and stays
        # 1 through every housekeeping pulse over a closed weekend regardless
        # of whether the muse ran. `record_trial` has exactly one call site,
        # inside `muse.run` - so a trial can exist only where a muse run does,
        # and this is the count of those chances. Found live: the coach read
        # "ran 24x, produced 4 - but nothing in the last 20 runs" on a
        # Saturday, purely from 30-minute housekeeping cycles counting against
        # a muse that structurally cannot run on a day the market never opens
        # (D-093).
        work=lambda rows: sum(int(r.get("muse_runs_since_pulse") or 0) for r in rows),
        heartbeat_fields=("experiments_open", "trials_scored", "muse_runs_since_pulse"),
        never_producing_is_ok=True,
    ),
    # The sizing tool answering, or refusing. A refusal is deliberate and
    # useful - WU-4.2 made it one named sentence per cause - but refusals
    # CLUSTERING is the shape of a seam that has stopped identifying which
    # simulated structure it is sizing (the I-40 class), or of an agent that
    # has stopped naming its structures. Neither is visible anywhere else: the
    # gauge charts it, and a chart needs someone to look.
    #
    # `produced` counts verdicts, not calls: a refusal is the tool declining to
    # answer, so a window of nothing but refusals reads as "ran plenty,
    # produced nothing", which is exactly what it is. No `heartbeat_fields` -
    # `sizing` is an output row written by the tool, not a `*_run` heartbeat.
    #
    # The lesson this points at is the agent's own: when candidates die at one
    # gate en masse, the instrument is the suspect before the candidates are.
    Probe(
        "sizing", ("sizing",),
        lambda rows: sum(1 for r in rows
                         if str(r.get("result")) in ("sized", "no_position")), 8,
        "every recent sizing call REFUSED - the structure-matching seam is "
        "losing the conditional payoff, or structures are no longer being named. "
        "See [when-refusals-cluster-audit-the-ruler]: clustered refusals indict "
        "the instrument before the candidates",
    ),
)

def heartbeat(journal: Any, kind: str, **fields: Any) -> str:
    """Emit a subsystem heartbeat THROUGH the module that reads it.

    The probe table declares which fields each heartbeat must carry, and this
    refuses a row that omits one - so "a probe reading a key nobody writes"
    becomes a loud failure at the emitting call site, in the first test that
    runs it, rather than a confident zero forever.

    That drift has shipped twice. D-074: a scorer fired eight times, died, and
    reported "ran 8x, produced 8" for two days. D-082: the exit probe read
    trigger rows as evidence the engine had RUN, so an armed engine with a
    populated debounce history reported "never ran". Both were read/write
    disagreements that no test could catch, because the two halves were
    written in different files by different hands.

    Raises rather than degrades, deliberately. Every one of the five emitters
    is exercised by the suite, so a violation cannot reach production green -
    and a swallowed contract violation would be the original bug with extra
    steps.

    Extra fields are always fine; the contract is a floor, not a schema.
    """
    probe = next((p for p in PROBES if kind in p.ran_kinds and p.heartbeat_fields), None)
    if probe is not None:
        missing = [f for f in probe.heartbeat_fields if f not in fields]
        if missing:
            raise ValueError(
                f"heartbeat {kind!r} is missing {missing} - probe {probe.name!r} reads "
                f"{list(probe.heartbeat_fields)}, so those fields would read as zero "
                f"forever. Add them at the emitting call site."
            )
    return str(journal.append(kind, **fields))


def degraded(journal: Any, subsystem: str, reason: str, **fields: Any) -> None:
    """Record that a fail-open path was taken: the run continued on less.

    Failing open is the right policy - advisory input must never take a tick
    down (INV-8) - but it looks EXACTLY like working. That is not a theory:
    the compactor shipped dead for its entire life because its unrecognised-
    envelope branch printed a line and returned the original, and 28 option
    chains went through uncompacted while every log read normal (D-074).

    A print in an unattended run is a message to nobody. This leaves a row
    that section 3.5 of `check` reads back, so the emitter and the reader are
    the same module and cannot drift - the same reason `heartbeat` lives here.

    Never raises and never blocks: instrumentation that can break the run it
    instruments is worse than none.
    """
    print(f"[degraded] {subsystem}: {reason}")
    if journal is None:
        return
    try:
        journal.append("degraded", subsystem=subsystem, reason=reason, **fields)
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"[degraded] could not journal {subsystem}: {exc!r}")


#: A subsystem can produce for a while and then stop. Totals hide that
#: perfectly - which is exactly how a dead interim scorer kept reporting
#: "ran 8x, produced 8". Once this many runs have gone by since the last
#: output, say so.
STALE_AFTER_RUNS = 20

#: Orders placed since sizing was last consulted, before that reads as the gate
#: being bypassed rather than as one cycle's ordering. A REPORTING threshold,
#: not a behaviour knob - health gates nothing (D-009) - and it lives beside
#: `STALE_AFTER_RUNS`, which is the same judgment for a different subsystem.
#: Three because one is an ordering artifact and two is a coincidence.
ORDERS_WITHOUT_SIZING = 3

#: Consecutive exit runs with the same signal unreadable before it stops being
#: weather. Five, because the engine runs every tick and a data feed that has
#: missed five in a row is not having a moment - it is not serving that symbol.
BLIND_RUN_WINDOW = 5


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


def _stale_process(run_json: Path) -> list[tuple[str, str, str]]:
    """Is the live `trdrbot run` older than the code on disk?

    Reads the pid and git sha the loop wrote at startup. A dead pid is not a
    finding (the loop was stopped, or `run.sh` is driving one process per
    tick and never writes this file). A live pid on a sha that is not HEAD is
    the finding, and the number of commits in between is how far behind it is.
    """
    import json as _json
    import os as _os
    import subprocess as _sp

    if not run_json.exists():
        return []
    try:
        info = _json.loads(run_json.read_text(encoding="utf-8"))
        pid, sha = int(info.get("pid", 0)), str(info.get("git_sha") or "")
        _os.kill(pid, 0)                      # raises if the pid is gone
    except (ValueError, TypeError, OSError, _json.JSONDecodeError):
        return []
    if not sha:
        return [(WARN, "live_process", f"pid {pid} is running but recorded no git sha - "
                                        "cannot tell whether it is current")]
    try:
        root = run_json.parents[2]
        head = _sp.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                       text=True, timeout=5).stdout.strip()
        if not head or head == sha:
            return []
        # Commits that touch what the PROCESS runs. A decision record or a dev
        # journal is not a fix that is not running, and a probe that demanded a
        # restart for every docs commit would be ignored by the second day.
        behind = _sp.run(["git", "rev-list", "--count", f"{sha}..{head}", "--",
                          "src/", "config.yaml", "scripts/", "pyproject.toml", "uv.lock"],
                         cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
        if behind in ("", "0"):
            return []
    except Exception:  # noqa: BLE001 - git is optional evidence, not a dependency
        return []
    return [(BAD, "live_process",
             f"pid {pid} started on {sha[:7]} (since {str(info.get('started', ''))[:16]}); "
             f"HEAD is {head[:7]}, {behind} commit(s) later. Every one of them is a fix that "
             f"is NOT running. Restart `trdrbot run` to apply them")]


#: An occurrence this many times inside the current era stops being weather.
#: Three, because one is an incident and two is a coincidence - the same
#: judgment as `ORDERS_WITHOUT_SIZING`, for the same reason.
RECURRENCE_LIMIT = 3


class Era:
    """How far back "now" reaches, and how to say so.

    Health asks one question - "is anything silently doing nothing?" - and an
    append-only journal answers it with a LIFETIME TOTAL, which is a different
    question. Measured on this system's own output on 2026-09-02: every FAIL
    and every WARN it reported named something that had already stopped. Three
    errors from six days earlier. Fourteen opportunities rejected as
    `horizon_too_late` by a deadline D-102 had removed, produced by a process
    D-108 found forty hours stale - under the config actually on disk, all
    fourteen are admitted. One learn error whose guard shipped the same day. A
    detector whose findings never clear is a detector nobody reads, which is
    precisely the failure health exists to prevent.

    The boundary is the RUNNING PROCESS rather than a wall-clock window,
    because that is what actually separates "the system as it is now" from
    "the system that had that bug" - a fix lands as a restart, not as a
    timeout - and the file recording it is one health already reads (D-108).
    A wall-clock window would have kept those fourteen failing for two more
    days after they became impossible.

    No live process - a one-shot CLI run, a test, a stopped loop - means there
    is no "now" to speak of, and the whole journal is then the honest scope.
    That is also the behaviour every caller had before this existed.
    """

    def __init__(self, run_json: Path) -> None:
        self.age_days: float | None = None
        self.label = "the whole journal"
        import json as _json
        import os as _os

        try:
            info = _json.loads(run_json.read_text(encoding="utf-8"))
            _os.kill(int(info.get("pid", 0)), 0)   # raises if the pid is gone
            age = ids.age_days(info.get("started"))
        except (ValueError, TypeError, OSError, _json.JSONDecodeError):
            return
        if age is None:
            return
        self.age_days = age
        self.label = f"this run ({_duration(age)} so far)"

    def live(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The rows produced by the system as it is running now.

        An UNSTAMPED row counts as live, the same rule the Coach's gauge window
        keeps: unknown age is not evidence of staleness, and if `ts` ever
        stopped being written, dropping those rows would switch this detector
        off silently, which is worse than it being noisy.
        """
        if self.age_days is None:
            return rows
        return [r for r in rows
                if (age := ids.age_days(r.get("ts"))) is None
                or age <= self.age_days]


def _duration(days: float) -> str:
    if days < 1 / 24:
        return f"{days * 1440:.0f}m"
    if days < 1:
        return f"{days * 24:.0f}h"
    return f"{days:.1f}d"


def _ago(age: float | None) -> str:
    return f", last {_duration(age)} ago" if age is not None else ""


def _recurrences(
    rows: list[dict[str, Any]], kind: str, prefix: str,
    key: Callable[[dict[str, Any]], str],
    sentence: Callable[[dict[str, Any]], str],
    era: Era,
) -> list[tuple[str, str, str]]:
    """One finding per recurring cause, scored over the current era.

    Four tallies had grown the same six-line loop - rejections, errors,
    fail-open paths, sizing divergences - each with its own escalation and none
    with any notion of WHEN. One shape, one place, so they cannot drift about
    what "repeatedly" means.

    A cause with nothing in this era is reported at OK rather than dropped:
    the history is real and worth seeing, it is simply not a problem with the
    system that is running.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("kind") == kind:
            groups.setdefault(key(r), []).append(r)

    out: list[tuple[str, str, str]] = []
    for subject, seen in groups.items():
        live, newest = era.live(seen), seen[-1]
        age = ids.age_days(newest.get("ts"))
        if not live:
            out.append((OK, f"{prefix}:{subject}",
                        f"{len(seen)}x, none since this run started{_ago(age)} - "
                        f"history, not a live problem"))
            continue
        count = (f"{len(live)}x this run" if len(live) == len(seen)
                 else f"{len(live)}x this run ({len(seen)} ever)")
        out.append((WARN if len(live) < RECURRENCE_LIMIT else BAD,
                    f"{prefix}:{subject}", f"{count}{_ago(age)} - {sentence(newest)}"))
    return sorted(out, key=lambda f: (f[0] != BAD, f[0] != WARN, f[1]))


def scope_label(journal_path: Path) -> str:
    """What `check` scored its recurrences over, for the report header.

    `check` keeps its signature - every caller and every test passes a journal
    path and gets findings - so the label is asked for separately rather than
    threaded through a tuple nobody else wants.
    """
    return Era(journal_path.parent / "state" / "run.json").label


def check(journal_path: Path, positions: list[Any]) -> list[tuple[str, str, str]]:
    """Return (level, subject, detail). Pure - takes data, returns findings."""
    rows = store.read_jsonl(journal_path)[0]
    era = Era(journal_path.parent / "state" / "run.json")
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

    # --- 1.5 cross-kind checks a single probe cannot express -------------
    #
    # A Probe asks one subsystem "did you run and produce?". These ask whether
    # one subsystem's output implies another's - a question about the SEAM
    # between two, which is where this project's bug history actually lives
    # (notes/019: the seams the bugs came from are the untyped ones).
    #
    # Both are SELF-ARMING: inert until the row kind they watch has been seen
    # at least once, so neither fires on the era before the row existed. A
    # health check that cries wolf trains the reader to skip the one line that
    # finally matters (D-070), and "this feature shipped yesterday" is the
    # cheapest possible false alarm to avoid.
    last_sizing = max((i for i, r in enumerate(rows) if r.get("kind") == "sizing"),
                      default=None)
    if last_sizing is not None:
        since = sum(len(r.get("order_calls") or []) for r in rows[last_sizing + 1:])
        if since >= ORDERS_WITHOUT_SIZING:
            findings.append((BAD, "sizing.bypassed",
                             f"{since} order(s) placed since sizing was last consulted - "
                             f"the Kelly gate and the book caps are being routed around, "
                             f"which looks identical to normal trading from every other "
                             f"signal"))

    last_book_risk = max((i for i, r in enumerate(rows) if r.get("kind") == "book_risk"),
                         default=None)
    if last_book_risk is not None and any(
            getattr(p, "status", "") == "open" for p in positions):
        decisions_since = sum(1 for r in rows[last_book_risk + 1:]
                              if r.get("kind") == "decision")
        if decisions_since >= STALE_AFTER_RUNS:
            findings.append((WARN, "book_risk.stale",
                             f"positions are open but no book-risk reading in the last "
                             f"{decisions_since} decide cycles - correlated exposure is "
                             f"invisible to the report, and names are not exposures"))

    # --- 2. the null paths, when they explain themselves ----------------
    skipped = sum(int(r.get("skipped_no_price") or 0)
                  for r in era.live(rows) if r.get("kind") == "attribution_run")
    if skipped:
        findings.append((BAD, "attribution.spot",
                         f"{skipped} attribution(s) skipped for want of a price - "
                         "the loop is stalled on data, not on judgment"))

    findings += _recurrences(
        rows, "research_rejected", "rejected",
        key=lambda r: str(r.get("reason")),
        sentence=lambda r: ("opportunities dropped for one reason - a repeating "
                            "reason is a systematic mismatch, not bad luck"),
        era=era)

    # --- 3. errors that keep coming back --------------------------------
    # Rows predating classification carry no cause; "unclassified" is what that
    # is, and `error:None` is a Python repr leaking into a report a human is
    # meant to read.
    findings += _recurrences(
        rows, "error", "error",
        key=lambda r: str(r.get("cause") or "unclassified"),
        sentence=lambda r: "a 'transient' seen repeatedly is permanent",
        era=era)

    # --- 3.5 fail-open paths that were actually taken --------------------
    #
    # An error row means something stopped. A degraded row means something
    # CONTINUED, on worse input, which is the harder failure to see: the tick
    # succeeded, the position opened, and the agent reasoned over bare
    # headlines or an uncompacted chain. Same escalation as the errors above,
    # because a fail-open path taken once is weather and taken repeatedly is
    # a subsystem that is quietly no longer running.
    #
    # Grouped by (subsystem, reason), because "something fell back 6 times" is
    # not a finding - the reason IS the finding.
    findings += _recurrences(
        rows, "degraded", "degraded",
        key=lambda r: f"{r.get('subsystem')}",
        sentence=lambda r: (f"fell back - {r.get('reason')} - the run continued on "
                            "reduced input, which reads as success everywhere else"),
        era=era)

    # The learning probe nets errors against successes, so one good fill and
    # one failed resolution read "produced 1" (D-112). A resolution that fails
    # to learn is the whole point of the row; say so when they ALL do.
    lr = [r for r in era.live(rows) if r.get("kind") == "learn_run"]
    n_res = sum(int(r.get("resolutions") or 0) for r in lr)
    n_err = sum(int(r.get("errors") or 0) for r in lr)
    if n_res and n_err >= n_res:
        findings.append((BAD, "learning",
                         f"{n_res} resolution(s) and {n_err} learn error(s) - every outcome "
                         f"that reached the learner failed to be learned from; see learn_error"))

    # A rule whose SIGNAL cannot be read is a stop that never fires, and it
    # reads exactly like a stop that evaluated and held (D-113). One tick of it
    # is a feed hiccup; every tick of it is a position guarded by nothing. The
    # live shape this was found on: three ETF positions whose only loss guard
    # is an `underlying_stop`, reading a price map that drops a symbol whenever
    # the IEX feed has no recent print for it - and `watched_signals` below
    # still reports "underlying" as watched, because the RULE is there.
    exit_rows = [r for r in rows if r.get("kind") == "exit_run"]
    recent = exit_rows[-BLIND_RUN_WINDOW:]
    if len(recent) >= BLIND_RUN_WINDOW:
        every = [r for r in recent if r.get("blind_signals")]
        if len(every) == len(recent):
            names: dict[str, int] = {}
            for r in every:
                for sig, n in (r.get("blind_signals") or {}).items():
                    names[str(sig)] = names.get(str(sig), 0) + int(n or 0)
            findings.append((BAD, "exit_blind",
                             f"{', '.join(sorted(names))} unreadable on every one of the "
                             f"last {len(recent)} exit runs - the rules that watch "
                             f"{'them' if len(names) > 1 else 'it'} have never had a value "
                             f"to compare against, and holding blind reads as holding"))
    elif exit_rows and exit_rows[-1].get("blind_signals"):
        findings.append((WARN, "exit_blind",
                         f"{', '.join(sorted(exit_rows[-1]['blind_signals']))} could not be "
                         f"read on the most recent exit run - the rules watching "
                         f"them held without a value"))

    # A recorded or placed quantity that is not the one sizing computed means
    # the book caps were derived from a size that was never traded. Once is a
    # deliberate override the agent is entitled to make (D-009); a pattern of
    # it means size_position's answer is not reaching the trade at all.
    findings += _recurrences(
        rows, "sizing_mismatch", "sizing_mismatch",
        key=lambda r: str(r.get("underlying") or "?"),
        sentence=lambda r: (f"traded a quantity size_position did not compute "
                            f"({r.get('sized_contracts')} sized, "
                            f"{r.get('placed_qtys') or r.get('recorded_qtys')} "
                            f"{r.get('seam') or 'recorded'}) - the caps were sized "
                            f"against a trade that was not made"),
        era=era)

    # --- 4. absence that quietly loosens a constraint --------------------
    # Two open pages sharing an OCC leg (D-111): the broker aggregates by
    # symbol, so both mark-based stops read one fabricated cost base, and can
    # go permanently unobservable together. Both pages are named.
    owners: dict[str, list[str]] = {}
    for p in positions:
        if getattr(p, "status", "") in ("open", "opening", "closing"):
            for sym in getattr(p, "symbols", []) or []:
                owners.setdefault(sym, []).append(p.position_id)
    for sym, ids_ in sorted(owners.items()):
        if len(ids_) > 1:
            findings.append((BAD, f"leg_overlap:{sym[:24]}",
                             f"held by {len(ids_)} open positions ({', '.join(i[:28] for i in ids_)}) - "
                             f"the broker aggregates by symbol, so every mark-based stop on "
                             f"them reads a shared, fabricated cost base"))

    # The whole repository is the absence, when the process that trades is
    # older than the code (D-108). `trdrbot run` writes run.json at startup;
    # if that pid is alive and its sha is not HEAD, every commit since is a
    # fix that is NOT running. Silence here cost 40 hours and seven decisions.
    findings.extend(_stale_process(journal_path.parent / "state" / "run.json"))

    # ...and its mirror image: a knob that is SET and quietly does nothing.
    # Above 1.75x at SCALE and 1.40x at MATURE the book cap is pinned at the
    # ruin bound, so the operator's number is partly absorbed and every surface
    # keeps reporting the value they typed. Same shape as everything else in
    # this file - a constraint that stopped meaning what it says (D-099).
    comp_rows = [r for r in rows if r.get("kind") == "competence"]
    if comp_rows:
        last = comp_rows[-1]
        asked, applied = last.get("appetite_config"), last.get("appetite")
        realised = last.get("realised_appetite")
        if asked is not None and applied is not None and asked != applied:
            findings.append((WARN, "risk_appetite",
                             f"config says {asked}, the ladder applied {applied} - "
                             f"clamped to [0.25, 2.0]. The setting on disk is not the "
                             f"one running"))
        elif applied is not None and realised is not None and applied != 1.0 \
                and abs(realised - applied) > 1e-6:
            findings.append((WARN, "risk_appetite",
                             f"set to {applied} but only {realised} was realised - the "
                             f"{last.get('tier', '')} book cap is pinned at the ruin "
                             f"bound, so turning it further changes nothing"))

    from .exit_rules import watched_signals

    for p in positions:
        # A position mid-liquidation is retried every open tick (I-57), so one
        # failed attempt is weather and a run of them is a close that is not
        # happening - real exposure the book still believes it is exiting.
        # Counted from the `exit` rows' own `submitted` flag rather than a new
        # field, because the retry already writes one row per attempt.
        if getattr(p, "status", "") == "closing":
            failed = sum(1 for r in rows
                         if r.get("kind") == "exit"
                         and r.get("position_id") == p.position_id
                         and r.get("submitted") is False)
            if failed:
                findings.append((WARN if failed < 3 else BAD,
                                 f"position:{p.position_id[:28]}",
                                 f"stuck in 'closing' - {failed} close attempt(s) failed; "
                                 "legs may still be live at the broker"))
            continue
        # A CLOSED position with no scoreable thesis used to be permanently
        # stuck (D-109): `attribution.pending` needed a claim AND a parseable
        # horizon, so it never became pending, the probe's `work` read 0, and
        # the subsystem reported "idle, not stalled" - a permanently empty
        # queue and a permanently stuck item are the same observation.
        #
        # The queue drains now (D-114): attribution records UNSCOREABLE with
        # the reason, once, so this state lasts from the close until the next
        # attribution run. That makes the finding SELF-CLEARING, and a
        # self-clearing finding that does not clear means the sweep is not
        # running - which is worth exactly as much alarm as the old permanent
        # one, for a reason that can actually be acted on.
        if getattr(p, "status", "") == "closed" and not getattr(p, "attribution", ""):
            from .attribution import unscoreable_reason
            why = unscoreable_reason(p)
            if why:
                findings.append((BAD, f"position:{p.position_id[:28]}",
                                 f"closed and unscoreable ({why}), and attribution has "
                                 f"not recorded it - the sweep that answers this runs "
                                 f"every tick, so it is not running"))
            continue
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


def render(findings: list[tuple[str, str, str]], scope: str = "") -> str:
    mark = {OK: "  ok  ", WARN: " warn ", BAD: " FAIL "}
    lines = ["", "=== trdrbot health: is anything silently doing nothing? ==="]
    # WHICH system these findings are about. Recurrences are scored over the
    # running process (see `Era`), so a report that did not say so would be
    # ambiguous in exactly the way the totals used to be.
    lines += [f"    recurrences scored over {scope}" if scope else "", ""]
    for level in (BAD, WARN, OK):
        rows = [f for f in findings if f[0] == level]
        for _, subject, detail in rows:
            lines.append(f"[{mark[level]}] {subject:<34} {detail}")
    bad = sum(1 for f in findings if f[0] == BAD)
    warn = sum(1 for f in findings if f[0] == WARN)
    lines += ["", f"{bad} problem(s), {warn} warning(s). "
                  "Nothing here is a gate - it is evidence." , ""]
    return "\n".join(lines)
