"""The heartbeat contract: the detector owns the emission door.

Health's probes read journal fields BY NAME that five emitters wrote by hand,
with nothing tying the two together - and a probe reading a key nobody writes
reports a confident zero forever. That drift shipped twice: D-074 (a scorer
fired eight times, died, and reported "ran 8x, produced 8" for two days) and
D-082 (the exit probe read trigger rows as evidence the engine had RUN, so an
armed engine with a live debounce history reported "never ran").
"""

from __future__ import annotations

import pytest
from conftest import journal_rows

from trdrbot import health
from trdrbot.journal import Journal


def _probe(name: str) -> health.Probe:
    return next(p for p in health.PROBES if p.name == name)


def test_a_heartbeat_missing_a_declared_field_is_refused(tmp_path):
    """The failure lands at the EMITTING call site, in the first test that
    runs it, rather than as a silent zero in a report weeks later."""
    journal = Journal(tmp_path / "journal.jsonl")

    with pytest.raises(ValueError, match="missing"):
        health.heartbeat(journal, "exit_run", positions=1)

    assert list(journal.read()) == [], "a refused heartbeat must not write"


def test_the_error_names_the_probe_and_the_fields_it_reads(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")

    with pytest.raises(ValueError) as e:
        health.heartbeat(journal, "interim_run", eligible=3)

    assert "scored" in str(e.value) and "interim_scoring" in str(e.value)


def test_extra_fields_are_fine_because_the_contract_is_a_floor(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")

    health.heartbeat(journal, "interim_run", eligible=3, scored=1, extra="context")

    assert list(journal.read())[0]["extra"] == "context"


@pytest.mark.parametrize("probe", [p for p in health.PROBES if p.heartbeat_fields],
                         ids=lambda p: p.name)
def test_what_each_heartbeat_declares_is_what_its_probe_can_read(probe, tmp_path):
    """The round trip IS the contract: a row carrying exactly the declared
    fields must satisfy the probe's own `produced` and `work` lambdas.

    Note the direction this guarantees. The lambdas use `.get`, so a MISSING
    field still reads as zero at check time - which is precisely why the
    enforcement has to live on the WRITE side, where the field is known.
    """
    journal = Journal(tmp_path / "journal.jsonl")

    health.heartbeat(journal, probe.ran_kinds[0],
                     **dict.fromkeys(probe.heartbeat_fields, 1))
    rows = list(journal.read())

    assert probe.produced(rows) is not None
    if probe.work is not None:
        assert probe.work(rows) is not None


def test_every_heartbeat_probe_is_actually_emitted_somewhere():
    """A declared contract nobody writes is the mirror of the bug this fixes:
    a probe that can only ever report "never ran"."""
    import pathlib
    import re

    src = pathlib.Path(health.__file__).parent
    emitted = set()
    for path in src.glob("*.py"):
        emitted |= set(re.findall(r'heartbeat\(\s*journal,\s*"(\w+)"', path.read_text()))

    declared = {p.ran_kinds[0] for p in health.PROBES if p.heartbeat_fields}
    assert declared <= emitted, f"declared but never emitted: {declared - emitted}"


async def test_a_discovery_run_that_nominates_nothing_still_says_so(paths, monkeypatch):
    """The null-path rule, broken by the subsystem next to the detector that
    enforces it: an empty nominee list returned early and journalled nothing,
    so "ran, found nothing" and "stopped running" were indistinguishable."""
    from types import SimpleNamespace

    from conftest import tools_for

    from trdrbot import discovery
    from trdrbot.inbox import Inbox
    from trdrbot.wiki import Wiki

    async def _no_evidence(*a, **k):
        return "(none)", "(none)"

    monkeypatch.setattr(discovery.evidence, "gather", _no_evidence)
    monkeypatch.setattr(discovery, "text_of", lambda reply: "[]")
    monkeypatch.setattr(discovery, "build_model",
                        lambda *a, **k: SimpleNamespace(ainvoke=_no_evidence))

    journal = Journal(paths.journal)
    cfg = SimpleNamespace(paths=paths, deadline="2099-01-01", research_universe=[],
                          watchlist=[], polymarket_queries=[])

    out = await discovery.run(tools_for(), cfg, Inbox(paths), Wiki(paths.wiki),
                              journal, verbose=False)

    assert out["nominees"] == 0
    rows = [r for r in journal.read() if r.get("kind") == "discovery"]
    assert len(rows) == 1 and rows[0]["opportunities"] == 0


# --- the other door: fail-open paths that were taken ----------------------


def _check(tmp_path, rows):
    """`check` is pure over a journal file, so a test is rows in, findings out."""
    import json

    path = tmp_path / "j.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return health.check(path, [])


def test_a_fail_open_path_leaves_a_row_the_detector_reads_back(tmp_path):
    """Failing open is right and looks exactly like working. The compactor
    shipped dead for its whole life on that resemblance (D-074)."""
    journal = Journal(tmp_path / "journal.jsonl")

    health.degraded(journal, "compact", "unrecognised result envelope",
                    tool="get_option_chain", detail="str")

    row = journal_rows(journal, "degraded")[-1]
    assert row["kind"] == "degraded"
    assert row["subsystem"] == "compact" and row["tool"] == "get_option_chain"


def test_the_degraded_door_never_takes_down_the_run_it_instruments():
    """Instrumentation that can break the path it watches is worse than none -
    the opposite policy to `heartbeat`, which raises deliberately because a
    heartbeat is emitted on the happy path where a test will catch it."""

    class Broken:
        def append(self, *a, **k):
            raise OSError("disk full")

    health.degraded(Broken(), "compact", "compaction raised")  # must not raise
    health.degraded(None, "compact", "compaction raised")  # journal-less caller


@pytest.mark.parametrize(("n", "expected"), [(1, health.WARN), (3, health.BAD)])
def test_a_repeated_degradation_escalates_from_warning_to_problem(tmp_path, n, expected):
    """Once is weather. Three times is a subsystem quietly no longer running -
    the same escalation the error-cause section makes, for the same reason."""
    rows = [{"kind": "degraded", "subsystem": "news_extract",
             "reason": "batch of 12 failed, falling back to headlines"}] * n

    hit = [f for f in _check(tmp_path, rows) if f[1] == "degraded:news_extract"]

    assert hit, f"a fail-open path taken {n}x is invisible in health"
    assert hit[0][0] == expected
    assert "reduced input" in hit[0][2]


@pytest.mark.parametrize("n,expected", [(1, health.WARN), (3, health.BAD)])
def test_a_stuck_closing_position_escalates_from_warning_to_problem(
    tmp_path, make_position, n, expected
):
    """A position mid-liquidation is retried every open tick (I-57). One failed
    attempt is a broker hiccup; a run of them is a close that is NOT happening,
    on exposure the book already believes it has exited. Same escalation as the
    degraded-subsystem section, for the same reason."""
    import json

    pos = make_position(status="closing", close_reason="stop_loss")
    rows = [{"kind": "exit", "position_id": pos.position_id,
             "close_reason": "stop_loss", "submitted": False}] * n
    path = tmp_path / "j.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    hit = [f for f in health.check(path, [pos]) if "stuck in 'closing'" in f[2]]

    assert hit, f"{n} failed close attempt(s) left no trace in health"
    assert hit[0][0] == expected


def test_a_closing_position_whose_retry_succeeded_is_not_flagged(tmp_path, make_position):
    """Balanced pressure: the probe must read the `submitted` flag, not the
    mere presence of a closing position mid-tick."""
    import json

    pos = make_position(status="closing", close_reason="stop_loss")
    path = tmp_path / "j.jsonl"
    path.write_text(json.dumps(
        {"kind": "exit", "position_id": pos.position_id, "submitted": True}) + "\n",
        encoding="utf-8")

    assert not [f for f in health.check(path, [pos]) if "stuck in 'closing'" in f[2]]


@pytest.mark.parametrize("n,expected", [(1, health.WARN), (3, health.BAD)])
def test_a_repeated_sizing_mismatch_escalates_from_warning_to_problem(
    tmp_path, n, expected
):
    """Once is a deliberate override the agent may make (D-009). A pattern of
    it means size_position's answer is not reaching the trade at all, and the
    caps have been sized against trades nobody placed."""
    rows = [{"kind": "sizing_mismatch", "underlying": "SPY",
             "sized_contracts": 13, "recorded_qtys": [40]}] * n

    hit = [f for f in _check(tmp_path, rows) if f[1] == "sizing_mismatch:SPY"]

    assert hit, f"a size divergence seen {n}x is invisible in health"
    assert hit[0][0] == expected


def test_two_subsystems_degrading_are_two_findings_not_one(tmp_path):
    """Grouped by (subsystem, reason), because "something fell back 6 times" is
    not actionable and "the compactor is passing chains through" is."""
    rows = [{"kind": "degraded", "subsystem": "compact", "reason": "compaction raised"},
            {"kind": "degraded", "subsystem": "usage",
             "reason": "no calls recorded for this cycle"}]

    subjects = {f[1] for f in _check(tmp_path, rows)}

    assert {"degraded:compact", "degraded:usage"} <= subjects


def test_a_clean_run_reports_no_degradation(tmp_path):
    assert not [f for f in _check(tmp_path, [{"kind": "no_op", "tick": 1}])
                if f[1].startswith("degraded:")]


# --- the three emitters ----------------------------------------------------


def test_the_compactor_journals_a_pass_through_once_per_tool_per_tick(tmp_path):
    """D-074's actual failure: 28 chains went through uncompacted while every
    log line read normal. One row per (tool, reason) per wrap, because the
    interesting fact is "this tool is passing through", not how many times the
    agent happened to ask for it."""
    import asyncio

    from trdrbot import compact

    class T:
        name = "get_option_chain"

        async def coroutine(self, **kw):
            return "not an envelope at all"

    journal = Journal(tmp_path / "journal.jsonl")
    tool = compact.wrap_heavy_tools([T()], None, journal)[0]

    for _ in range(3):
        assert asyncio.run(tool.coroutine()) == "not an envelope at all", "must fail OPEN"

    rows = journal_rows(journal, "degraded")
    assert len(rows) == 1, f"three calls, one row - got {len(rows)}"
    assert rows[0]["subsystem"] == "compact" and rows[0]["tool"] == "get_option_chain"


def test_a_news_batch_falling_back_to_headlines_says_how_many(tmp_path, monkeypatch):
    """The articles all survive as bare headlines, so every caller sees a full
    list and nothing downstream can tell the structure is missing."""
    import asyncio
    from types import SimpleNamespace

    from trdrbot import news_extract

    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(news_extract, "build_model", _boom)
    journal = Journal(tmp_path / "journal.jsonl")
    cfg = SimpleNamespace(paths=SimpleNamespace(state=tmp_path))
    items = [{"id": i, "headline": f"h{i}", "summary": "s"} for i in range(4)]

    out = asyncio.run(news_extract.enrich(items, cfg, journal))

    assert len(out) == 4, "fail open: never lose the articles"
    row = journal_rows(journal, "degraded")[-1]
    assert row["subsystem"] == "news_extract" and row["articles"] == 4


def test_a_cycle_that_called_an_llm_but_recorded_no_usage_is_degraded():
    """A failed usage-ledger write yields an empty `model_served` on the
    execution row - D-070's mis-attribution back through the front door, and a
    Coach cost sentinel reading low because the calls are not there.

    Detected at the consumer: the usage callback runs sync-in-a-thread inside
    the agent loop and must not grow IO. Wiring is covered by review, not by a
    test - the seam would need a whole tick to exercise three lines.
    """
    from trdrbot.tick import _usage_went_dark

    assert _usage_went_dark([], llm_turns=3) is True
    assert _usage_went_dark(["claude-fable-5"], llm_turns=3) is False
    # Quiet when the count is not evidence: a detector that cries wolf gets
    # ignored, which costs more than the miss.
    assert _usage_went_dark([], llm_turns=0) is False


def test_the_learning_heartbeat_fires_even_when_there_is_nothing_to_learn(tmp_path):
    """It was guarded by "only if something filled or resolved", which writes
    the row exactly when the probe least needs it: a quiet week and a dead
    learning path then produce the same silence. That collapse is what every
    heartbeat in this module exists to prevent."""
    import asyncio
    from types import SimpleNamespace

    from trdrbot import reconcile
    from trdrbot.analytics import Snapshot

    journal = Journal(tmp_path / "journal.jsonl")
    store = SimpleNamespace(open_positions=lambda: [])
    # The REAL Snapshot, not a stand-in with just the two attributes reconcile
    # happened to read when this was written. A hand-rolled fake silently stops
    # covering the seam the moment the real one grows a field - which is exactly
    # what it did, and the reason conftest builds every other input from its
    # real producer.
    snap = Snapshot(broker_readable=True)

    asyncio.run(reconcile.reconcile(store, snap, journal, None, None))

    row = journal_rows(journal, "learn_run")[-1]
    assert (row["fills"], row["resolutions"], row["errors"]) == (0, 0, 0)
    # And health reads that as idle, not as broken.
    findings = _check(tmp_path, list(journal.read()) * 3)
    learning = [f for f in findings if f[1] == "learning"]
    assert learning and learning[0][0] == health.OK, learning


# --- coach staleness must count CHANCES, not clock ticks -------------------


def _coach_row(*, trials_scored, muse_runs_since_pulse, experiments_open=1):
    return {"kind": "coach_run", "trials_scored": trials_scored,
            "experiments_open": experiments_open,
            "muse_runs_since_pulse": muse_runs_since_pulse}


def test_a_closed_weekend_of_housekeeping_pulses_does_not_read_as_a_stalled_coach(tmp_path):
    """Found live: 20 housekeeping cycles over a Saturday, with an experiment
    left open from Friday, read as "ran 24x, produced 4 - but nothing in the
    last 20 runs" - a health FAIL for a market that never opened.

    `record_trial` has exactly one call site, inside `muse.run` (grep it) - a
    trial can exist only where a muse run does. `experiments_open` stays 1
    through every one of these pulses regardless, which is why it was the
    wrong thing for `work` to measure: it says a lever is ACTIVE, not that a
    pulse had any CHANCE to see a trial."""
    one_success = [_coach_row(trials_scored=1, muse_runs_since_pulse=1)]
    weekend = [_coach_row(trials_scored=0, muse_runs_since_pulse=0) for _ in range(30)]

    findings = _check(tmp_path, one_success + weekend)

    coach = [f for f in findings if f[1] == "coach"][0]
    assert coach[0] == health.OK, coach


def test_a_muse_run_that_never_reaches_record_trial_still_reads_as_stalled(tmp_path):
    """The bug this probe exists to catch must still be caught: the muse IS
    running - real chances existed - and none of them produced a trial."""
    one_success = [_coach_row(trials_scored=1, muse_runs_since_pulse=1)]
    broken = [_coach_row(trials_scored=0, muse_runs_since_pulse=1) for _ in range(25)]

    findings = _check(tmp_path, one_success + broken)

    coach = [f for f in findings if f[1] == "coach"][0]
    assert coach[0] == health.BAD, coach


def test_housekeeping_noise_between_two_muse_runs_does_not_mask_a_real_break(tmp_path):
    """A closed evening's worth of no-op pulses sits between two real muse
    chances, one of which failed to score. The failure must still surface -
    diluting it below detection would be worse than the false positive this
    fix removes."""
    rows = ([_coach_row(trials_scored=1, muse_runs_since_pulse=1)]
            + [_coach_row(trials_scored=0, muse_runs_since_pulse=0) for _ in range(15)]
            + [_coach_row(trials_scored=0, muse_runs_since_pulse=1)]  # the real miss
            + [_coach_row(trials_scored=0, muse_runs_since_pulse=0) for _ in range(15)])

    findings = _check(tmp_path, rows)

    coach = [f for f in findings if f[1] == "coach"][0]
    assert coach[0] == health.BAD, coach


# ==================================================================== PILLAR-4
# Phase 4 shipped two journal kinds and no way to notice them failing
# (I-47, WU-6.2). "Health detects, the ledger remembers" is this project's own
# division of labour; these are the detectors for the rows it added to itself.
# Governed by docs/principles_testing.md - the four pillars.

def _sized(journal, n=1, result="sized"):
    for _ in range(n):
        journal.append("sizing", result=result, contracts=1 if result == "sized" else 0)


def test_a_window_of_nothing_but_refusals_is_flagged(tmp_path):
    """I-47: refusals are deliberate and useful; refusals CLUSTERING is the
    shape of a seam that has stopped identifying which structure it is sizing
    (the I-40 class). The gauge charts it - a chart needs someone to look."""
    journal = Journal(tmp_path / "journal.jsonl")
    _sized(journal, 9, result="refused")

    found = {name: (lvl, detail) for lvl, name, detail in
             health.check(tmp_path / "journal.jsonl", [])}

    assert found["sizing"][0] == health.BAD
    assert "REFUSED" in found["sizing"][1]


def test_a_healthy_mix_of_sizes_and_refusals_stays_quiet(tmp_path):
    """The crying-wolf half of the contract (D-070). A refusal among real
    verdicts is the system working, not the system stuck."""
    journal = Journal(tmp_path / "journal.jsonl")
    _sized(journal, 6, result="sized")
    _sized(journal, 3, result="refused")

    found = {name: (lvl, detail) for lvl, name, detail in
             health.check(tmp_path / "journal.jsonl", [])}

    assert found["sizing"][0] == health.OK


def test_orders_placed_without_consulting_sizing_are_flagged(tmp_path):
    """The Kelly gate and the book caps can be routed around simply by not
    calling the tool - and from every other signal that looks exactly like
    normal trading."""
    journal = Journal(tmp_path / "journal.jsonl")
    _sized(journal, 1)  # arms the check: sizing has been seen at least once
    for _ in range(health.ORDERS_WITHOUT_SIZING):
        journal.append("execution", order_calls=[{"symbol": "SPY..."}])

    found = {name: (lvl, detail) for lvl, name, detail in
             health.check(tmp_path / "journal.jsonl", [])}

    assert found["sizing.bypassed"][0] == health.BAD
    assert "routed around" in found["sizing.bypassed"][1]


def test_the_bypass_check_is_inert_before_sizing_has_ever_been_seen(tmp_path):
    """Self-arming: the journal predates these row kinds by the project's whole
    history, and "this shipped yesterday" is the cheapest false alarm to
    avoid."""
    journal = Journal(tmp_path / "journal.jsonl")
    for _ in range(10):
        journal.append("execution", order_calls=[{"symbol": "SPY..."}])

    names = {name for _lvl, name, _detail in health.check(tmp_path / "journal.jsonl", [])}

    assert "sizing.bypassed" not in names


def test_a_dead_book_risk_feed_is_flagged_only_while_positions_are_open(tmp_path):
    """Correlated exposure going invisible matters when there is a book to be
    exposed; with no open position it is silence about nothing."""
    from types import SimpleNamespace

    journal = Journal(tmp_path / "journal.jsonl")
    journal.append("book_risk", delta_dollars=1.0, vega_dollars=-1.0)
    for _ in range(health.STALE_AFTER_RUNS):
        journal.append("decision", batch="b")
    open_pos = [SimpleNamespace(status="open", position_id="p1", max_loss_usd=100.0,
                                exit_rules=[], thesis="t", thesis_band_low=1.0)]

    flat = {n for _l, n, _d in health.check(tmp_path / "journal.jsonl", [])}
    held = {n for _l, n, _d in health.check(tmp_path / "journal.jsonl", open_pos)}

    assert "book_risk.stale" not in flat
    assert "book_risk.stale" in held


def test_health_says_so_when_the_live_process_is_older_than_the_code(tmp_path):
    """D-108. A long-lived `trdrbot run` holds every module and the config in
    memory from the moment it started. On 2026-09-02 the live loop turned out
    to be 40 hours and SEVEN decisions old - the discovery corpse, the deadlocked
    Coach, the single-name watchlist and a deadline two days from force-closing
    the whole book were all still executing while the repo said they were fixed.
    Nothing noticed. Now the loop writes its pid and sha at startup and health
    compares that sha to HEAD.

    Three cases, because a wrong probe here would cry wolf on every run.sh
    deployment (one process per tick, never writes the file)."""
    import json
    import os
    import subprocess

    from trdrbot import health

    root = tmp_path / "repo"
    (root / "data" / "state").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "one"], cwd=root, check=True)
    old_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                             capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "two"], cwd=root, check=True)
    run_json = root / "data" / "state" / "run.json"

    # 1. alive pid (this test's own), on the OLD sha -> the finding, counting commits
    run_json.write_text(json.dumps({"pid": os.getpid(), "git_sha": old_sha,
                                    "started": "2026-08-31T15:53:35"}))
    found = health._stale_process(run_json)
    assert len(found) == 1 and found[0][0] == health.BAD
    assert "1 commit(s) later" in found[0][2] and "Restart" in found[0][2]

    # 2. alive pid on HEAD -> silence
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                          capture_output=True, text=True).stdout.strip()
    run_json.write_text(json.dumps({"pid": os.getpid(), "git_sha": head}))
    assert health._stale_process(run_json) == []

    # 3. dead pid -> silence: the loop was stopped, or run.sh is driving it
    run_json.write_text(json.dumps({"pid": 999_999_999, "git_sha": old_sha}))
    assert health._stale_process(run_json) == []
    # and no file at all (run.sh mode) -> silence
    run_json.unlink()
    assert health._stale_process(run_json) == []


def test_health_names_a_closed_position_that_can_never_be_attributed(tmp_path, make_position):
    """D-109. `attribution.pending` needs a claim and a parseable horizon, so a
    closed position without them never becomes pending, the probe's `work`
    reads 0, and the subsystem reports "idle, not stalled". A permanently empty
    queue and a permanently stuck item were the same observation. Live:
    pos_20260826_SPY_bull_put_spread closed +8.2% with no thesis and will never
    be attributed at any future date."""
    from trdrbot import health

    journal = tmp_path / "journal.jsonl"
    journal.write_text("")
    stuck = make_position(status="closed", thesis_claim="", thesis_horizon="", attribution="")
    bad_date = make_position(position_id="pos_h", status="closed", thesis_claim="c",
                             thesis_horizon="not-a-date", attribution="")
    fine = make_position(position_id="pos_ok", status="closed", thesis_claim="c",
                         thesis_horizon="2026-09-10", attribution="")
    done = make_position(position_id="pos_done", status="closed", thesis_claim="",
                         thesis_horizon="", attribution="thesis_right_expression_right")
    found = {f[1]: (f[0], f[2]) for f in health.check(journal, [stuck, bad_date, fine, done])
             if f[1].startswith("position:")}
    assert found[f"position:{stuck.position_id[:28]}"][0] == health.BAD
    assert "NEVER be attributed" in found[f"position:{stuck.position_id[:28]}"][1]
    assert "unparseable horizon" in found["position:pos_h"][1]
    assert "position:pos_ok" not in found, "a closed position with a future horizon is fine"
    assert "position:pos_done" not in found, "an attributed position is done"

