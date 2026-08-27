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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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
    Probe(
        "exit_rules", ("exit",),
        lambda rows: len(rows), 0,
        "no exit has ever fired (fine early; suspicious once positions resolve)",
    ),
    Probe(
        "interim_scoring", ("interim_outcome",),
        lambda rows: len(rows), 0,
        "no interim signal yet - expected until a position moves materially",
    ),
)


def _rows(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    out = []
    for line in journal_path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


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
        elif made == 0 and len(ran) >= probe.min_runs > 0:
            findings.append((BAD, probe.name,
                             f"ran {len(ran)}x, produced nothing - {probe.meaning}"))
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
        # An unfalsifiable thesis can never be attributed, so it can never teach.
        if getattr(p, "thesis_claim", "") and not (
            p.thesis_band_low is not None or p.thesis_band_high is not None
        ):
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
