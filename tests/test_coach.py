"""The Coach: promotion math, trial fairness, and the shadow-arm contract (D-088).

The load-bearing test in this file is
`test_the_shadow_arm_writes_nothing_at_all` - everything else guards a
threshold, but that one guards the property that makes autonomous
experimentation safe to run against a live system at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from trdrbot import coach, muse
from trdrbot.journal import Journal
from trdrbot.ledger import Ledger

#: The muse lever's own declaration - what the generic machinery reads too,
#: rather than a constant that could drift from it (D-093).
_MUSE_LEVER = coach.lever("muse.prompt")

# --- fixtures --------------------------------------------------------------


def _cfg(tmp_path: Path, **coach_opts) -> SimpleNamespace:
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        paths=SimpleNamespace(state=tmp_path / "state", data=tmp_path,
                              journal=tmp_path / "journal.jsonl"),
        coach={"enabled": True, **coach_opts},
        pricing={},
        deadline="2026-09-04",
    )


def _floors_cfg(**coach_opts) -> SimpleNamespace:
    """Config for the PURE verdict tests, which read only `cfg.coach`.

    They used to build a config rooted at a hardcoded /tmp, which really did
    create a `/tmp/state` directory
    on the developer's machine - a shared mutable directory, against the
    fresh-fixtures non-negotiable, for paths none of them ever read.
    """
    return SimpleNamespace(coach={"enabled": True, **coach_opts})


def _journal(tmp_path: Path) -> Journal:
    p = tmp_path / "journal.jsonl"
    p.touch()
    return Journal(p)


# --- promotion math (pure) -------------------------------------------------


def test_p_challenger_better_is_exactly_half_when_the_evidence_is_identical():
    # Two arms with the same record cannot prefer either. Anything else here
    # means the integration is skewed and every close call would inherit it.
    assert coach.p_challenger_better(5, 5, 5, 5) == pytest.approx(0.5, abs=1e-6)
    assert coach.p_challenger_better(0, 0, 0, 0) == pytest.approx(0.5, abs=1e-6)
    assert coach.p_challenger_better(30, 12, 30, 12) == pytest.approx(0.5, abs=1e-6)


def test_p_challenger_better_is_symmetric_under_swapping_the_arms():
    a = coach.p_challenger_better(18, 6, 9, 15)
    b = coach.p_challenger_better(9, 15, 18, 6)
    assert a + b == pytest.approx(1.0, abs=1e-6)


def test_a_challenger_that_is_merely_luckier_early_is_not_promoted():
    """4-1 up after 5 runs is a streak, not evidence.

    The floors exist for exactly this shape: the posterior alone would already
    favour the challenger, and promoting on it would install noise as policy.
    """
    t = coach.Tally("e", "muse.prompt", "v0", "v1", runs=5, s_c=4, f_c=1, s_i=1, f_i=4)
    assert t.posterior > 0.9  # the evidence really does point that way
    outcome, _ = coach.verdict(t, coach.floors(_floors_cfg()))
    assert outcome == "", "promoted on 5 runs - the run floor is not binding"


def test_a_fair_coin_challenger_is_never_promoted_over_the_full_run_cap():
    """Two identical arms, run to the cap, must end in `timeout` - never a
    promotion. This is the Coach's zero-EV property: with no real difference
    there is no verdict, the same shape as Kelly being exactly zero on a
    fairly priced structure (D-079)."""
    cfg = _floors_cfg()
    for runs in range(1, coach.CAP_RUNS + 1):
        t = coach.Tally("e", "muse.prompt", "v0", "v1", runs=runs,
                        s_c=2 * runs, f_c=3 * runs, s_i=2 * runs, f_i=3 * runs)
        outcome, _ = coach.verdict(t, coach.floors(cfg))
        assert outcome != "promoted", f"promoted an identical arm at {runs} runs"
    assert outcome == "timeout"


def test_promotion_needs_the_posterior_and_both_floors_together():
    cfg = _floors_cfg()
    fl = coach.floors(cfg)
    strong = dict(s_c=40, f_c=10, s_i=10, f_i=40)

    ok = coach.Tally("e", "l", "v0", "v1", runs=10, **strong)
    assert coach.verdict(ok, fl)[0] == "promoted"

    # enough candidates, not enough runs
    few_runs = coach.Tally("e", "l", "v0", "v1", runs=3, **strong)
    assert coach.verdict(few_runs, fl)[0] == ""

    # enough runs, not enough candidates: 10 runs of 2 candidates each is 20
    # Bernoulli trials wearing 10 runs' clothing.
    few_cands = coach.Tally("e", "l", "v0", "v1", runs=10,
                            s_c=10, f_c=0, s_i=0, f_i=10)
    assert min(few_cands.n_i, few_cands.n_c) < fl["min_candidates"]
    assert coach.verdict(few_cands, fl)[0] == ""


def test_a_hopeless_challenger_is_refuted_early_rather_than_run_to_the_cap():
    t = coach.Tally("e", "l", "v0", "v1", runs=7, s_c=1, f_c=40, s_i=30, f_i=11)
    outcome, reason = coach.verdict(t, coach.floors(_floors_cfg()))
    assert outcome == "refuted" and "futile" in reason


def test_the_incumbent_keeps_its_place_on_timeout():
    t = coach.Tally("e", "l", "v0", "v1", runs=coach.CAP_RUNS,
                    s_c=30, f_c=30, s_i=28, f_i=32)
    outcome, _ = coach.verdict(t, coach.floors(_floors_cfg()))
    assert outcome == "timeout"


# --- the shadow arm: the contract that makes this safe --------------------


def test_the_shadow_ledger_still_refuses_a_candidate_with_no_band():
    """`register` returning None IS a gate in production ("unfalsifiable").

    A shadow arm that skipped the ledger entirely would skip that gate too, and
    the challenger would be scored against an easier gauntlet than the
    incumbent - an unfair trial that would read as a genuine improvement.
    """
    sl = muse.ShadowLedger()
    assert sl.register(band_low=None, band_high=None) is None
    assert sl.register(band_low=100.0, band_high=None) is not None
    assert sl.register(band_low=None, band_high=200.0) is not None
    assert sl.registered == 2


def test_the_shadow_ledger_is_shaped_like_the_real_one():
    """Both arms call the SAME gate cascade, so the stand-in must accept every
    call the real ledger accepts. A missing method would only surface on the
    live run that first reached that gate."""
    for name in ("register", "mark_rejected", "mark_stated"):
        assert hasattr(muse.ShadowLedger(), name)
    sl = muse.ShadowLedger()
    e = sl.register(kind="muse", underlying="SPY", claim="c", probability=0.4,
                    probability_stated=False, horizon="2026-09-02",
                    band_low=1.0, band_high=2.0, variant="v1", notes="n")
    assert e is not None and sl.mark_stated(e.id) and sl.mark_rejected(e.id, "why")


@pytest.mark.asyncio
async def test_the_shadow_arm_writes_nothing_at_all(tmp_path, monkeypatch):
    """THE contract. A paired run must leave the ledger, the inbox and the
    thesis journal rows byte-identical to an unpaired one.

    A challenger arm that registered its candidates would inflate D-052's trial
    count with experiment artefacts and feed rejected material into
    calibration - D-080's exact defect, rebuilt by the machinery meant to
    improve things.
    """
    from trdrbot.inbox import Inbox

    cand = {"underlying": "SPY", "claim": "c", "chain": ["a"], "direction": "bullish",
            "probability": 0.4, "band_low_pct": -3.0, "band_high_pct": 3.0,
            "horizon": "2026-09-02", "suggested_structures": []}

    paths = SimpleNamespace(state=tmp_path / "state", data=tmp_path,
                            journal=tmp_path / "journal.jsonl",
                            wiki=tmp_path / "wiki",
                            inbox_pending=tmp_path / "inbox" / "pending",
                            inbox_processed=tmp_path / "inbox" / "processed",
                            inbox_failed=tmp_path / "inbox" / "failed")
    for p in (paths.state, paths.wiki, paths.inbox_pending, paths.inbox_processed,
              paths.inbox_failed):
        Path(p).mkdir(parents=True, exist_ok=True)
    cfg = SimpleNamespace(paths=paths, coach={"enabled": True}, pricing={},
                          deadline="2026-09-04", polymarket_queries=[],
                          max_retries=3)

    closes = [100.0 + (i % 7) * 0.5 for i in range(120)]
    monkeypatch.setattr(muse.market_stats, "load_closes", lambda *a, **k: closes)
    monkeypatch.setattr(muse, "_options_gate",
                        lambda *a, **k: _async({"tradeable": True}))
    monkeypatch.setattr(muse, "_plausible_band", lambda *a, **k: True)
    monkeypatch.setattr(muse, "_sample_concepts", lambda *a, **k: [("c/a", "text")])

    async def fake_generate(prompt_text, fields, config, journal, *, variant, verbose):
        # The two arms produce DIFFERENT candidates, as two prompt variants
        # really would. That matters since D-091: opportunities dedup on their
        # claim, so if both arms proposed the identical band, a challenger that
        # wrongly emitted would collapse into the incumbent's item and this
        # test would pass while the contract it guards was broken.
        c = dict(cand)
        if variant != "v0":
            c["band_low_pct"], c["band_high_pct"] = -9.0, 9.0
        return [c]

    monkeypatch.setattr(muse, "_generate", fake_generate)

    # Patched at `evidence.gather`, the seam the muse actually calls now -
    # rather than at mcp_client, which was reaching two layers down into how
    # the news happened to be fetched.
    async def _no_evidence(*a, **k):
        return "(none)", "(none)"

    monkeypatch.setattr(muse.evidence, "gather", _no_evidence)

    inbox = Inbox(paths, max_retries=3)
    journal = Journal(paths.journal)
    journal.path.touch()
    book = Ledger(paths.state / "ledger.jsonl")

    from trdrbot.wiki import Wiki

    # 1. unpaired baseline
    monkeypatch.setattr(coach, "arms", lambda *a, **k: coach.Arms(
        incumbent=coach.Variant("v0", muse.MUSE_PROMPT)))
    await muse.run({}, cfg, inbox, Wiki(paths.wiki), journal, book, verbose=False)
    base_ledger = len(book.all())
    base_inbox = len(list(Path(paths.inbox_pending).glob("*")))
    base_muse_rows = sum(1 for r in journal.read() if r.get("kind") == "muse")

    # 2. the same run, with a challenger being trialled.
    #
    # Pending is cleared first so the two runs are INDEPENDENT, which the delta
    # arithmetic below assumes. Opportunities dedup on their claim now (D-091),
    # and both runs emit the identical candidate - so leaving the baseline
    # item in place would make the paired run's emission a no-op and the test
    # would "pass" by measuring dedup instead of the shadow-arm contract.
    for stale in Path(paths.inbox_pending).glob("*"):
        stale.unlink()

    monkeypatch.setattr(coach, "arms", lambda *a, **k: coach.Arms(
        incumbent=coach.Variant("v0", muse.MUSE_PROMPT),
        challenger=coach.Variant("v1", muse.MUSE_PROMPT + "\nvariant"),
        exp_id="exp_test"))
    book2 = Ledger(paths.state / "ledger.jsonl")
    await muse.run({}, cfg, inbox, Wiki(paths.wiki), journal, book2, verbose=False)

    added_ledger = len(book2.all()) - base_ledger
    # Pending was emptied above, so whatever is there now is what the PAIRED
    # run emitted - and it must match what the unpaired baseline emitted.
    added_inbox = len(list(Path(paths.inbox_pending).glob("*")))
    added_muse_rows = sum(1 for r in journal.read() if r.get("kind") == "muse") - base_muse_rows

    assert added_ledger == base_ledger, (
        f"the paired run wrote {added_ledger} ledger rows against a baseline of "
        f"{base_ledger} - the challenger arm is writing theses")
    assert added_inbox == base_inbox, "the challenger arm emitted to the inbox"
    assert added_muse_rows == 1, "the challenger arm wrote its own muse journal row"

    trials = [r for r in coach.events(cfg) if r.get("kind") == "trial_result"]
    assert len(trials) == 1, "the paired run recorded no trial result"
    assert trials[0]["challenger"]["candidates"] == 1


def _async(value):
    async def _inner(*a, **k):
        return value
    return _inner()


# --- state, promotion, crash safety ---------------------------------------


def test_a_promotion_swaps_the_incumbent_and_survives_a_reload(tmp_path):
    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    st = coach.load_state(cfg, "muse.prompt", "SEED TEXT " * 30)
    ch = coach.Variant("v1", "CHALLENGER TEXT " * 30, origin="mutation")
    coach._open(cfg, st, ch, journal)
    t = coach.Tally("e", "muse.prompt", "v0", "v1", runs=10,
                    s_c=40, f_c=10, s_i=10, f_i=40)
    coach._promote(cfg, st, t, "because", journal)

    fresh = coach.load_state(cfg, "muse.prompt", "SEED TEXT " * 30)
    assert fresh.incumbent.id == "v1"
    assert fresh.previous is not None and fresh.previous.id == "v0"
    assert fresh.challenger is None and fresh.exp_id is None
    assert fresh.incumbent.text.startswith("CHALLENGER")


def test_a_promotion_logged_but_never_applied_is_reconciled_on_restart(tmp_path):
    """The close is appended BEFORE the state swap, so a crash between them
    leaves a promoted experiment whose lever state still shows the old
    incumbent. The event log is truth; the state file is a cache of it."""
    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    seed = "SEED TEXT " * 30
    st = coach.load_state(cfg, "muse.prompt", seed)
    coach._open(cfg, st, coach.Variant("v1", "NEW TEXT " * 30, origin="mutation"), journal)
    # simulate the crash: append the close, never swap
    coach._append(coach.events_path(cfg), {
        "kind": "experiment_closed", "exp_id": st.exp_id, "lever": "muse.prompt",
        "outcome": "promoted", "reason": "r", "runs": 10, "final_posterior": 0.95,
        "challenger": "v1", "challenger_text": "NEW TEXT " * 30})
    assert coach.load_state(cfg, "muse.prompt", seed).incumbent.id == "v0"

    applied = coach.reconcile(cfg, seed_override={"muse.prompt": seed})
    assert applied and "v0 -> v1" in applied[0]
    assert coach.load_state(cfg, "muse.prompt", seed).incumbent.id == "v1"
    # and it is idempotent - a second pass must not re-promote
    assert coach.reconcile(cfg, seed_override={"muse.prompt": seed}) == []


def test_corrupt_lever_state_degrades_to_the_seed_and_keeps_the_broken_file(tmp_path):
    cfg = _cfg(tmp_path)
    path = coach._state_path(cfg, "muse.prompt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json")

    st = coach.load_state(cfg, "muse.prompt", "SEED")
    assert st.incumbent.id == "v0" and st.incumbent.text == "SEED"
    # the unreadable file is NOT silently overwritten - a human may need it
    assert path.read_text() == "{ this is not json"


def test_a_hand_edited_incumbent_gets_a_recomputed_fingerprint(tmp_path):
    """Editing the state file is a supported steering move. A stale
    fingerprint beside edited text would mislabel every trial that variant
    runs in."""
    cfg = _cfg(tmp_path)
    st = coach.load_state(cfg, "muse.prompt", "SEED")
    coach.save_state(cfg, st)
    raw = json.loads(coach._state_path(cfg, "muse.prompt").read_text())
    raw["incumbent"]["text"] = "EDITED BY A HUMAN"
    raw["incumbent"]["fingerprint"] = "staleval"
    coach._state_path(cfg, "muse.prompt").write_text(json.dumps(raw))

    reloaded = coach.load_state(cfg, "muse.prompt", "SEED")
    assert reloaded.incumbent.text == "EDITED BY A HUMAN"
    assert reloaded.incumbent.fingerprint == coach.fingerprint("EDITED BY A HUMAN")


def test_arms_returns_no_challenger_once_the_experiment_is_closed(tmp_path):
    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    st = coach.load_state(cfg, "muse.prompt", "SEED")
    coach._open(cfg, st, coach.Variant("v1", "NEW"), journal)
    assert coach.arms(cfg, "muse.prompt", seed_text="SEED").paired

    st2 = coach.load_state(cfg, "muse.prompt", "SEED")
    coach._close(cfg, st2, "refuted", "worse", journal)
    assert not coach.arms(cfg, "muse.prompt", seed_text="SEED").paired


def test_a_disabled_coach_runs_the_seed_and_opens_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.coach = {"enabled": False}
    a = coach.arms(cfg, "muse.prompt", seed_text="SEED")
    assert a.incumbent.text == "SEED" and not a.paired


# --- mutation validation ---------------------------------------------------


def test_a_mutated_prompt_missing_a_placeholder_is_rejected():
    inc = muse.MUSE_PROMPT
    broken = inc.replace("{concepts}", "the concepts")
    why = coach.validate_prompt(broken, inc, _MUSE_LEVER.placeholders)
    assert why == "", "a MISSING placeholder is only a problem if code needs it"
    # ...but an UNKNOWN one is a live KeyError on the next muse run
    unknown = inc.replace("{news}", "{nonexistent_field}")
    assert "not a safe format template" in coach.validate_prompt(
        unknown, inc, _MUSE_LEVER.placeholders)


def test_a_mutated_prompt_with_unescaped_json_braces_is_rejected():
    """The prompt is a `.format()` template, so a JSON example written with
    single braces raises at format time - on a live muse run, not here, unless
    this check catches it first."""
    inc = muse.MUSE_PROMPT
    bad = inc.replace('[{{"underlying"', '[{"underlying"')
    assert "not a safe format template" in coach.validate_prompt(
        bad, inc, _MUSE_LEVER.placeholders)


def test_a_mutation_identical_to_the_incumbent_is_rejected():
    inc = muse.MUSE_PROMPT
    assert "identical" in coach.validate_prompt(inc, inc, _MUSE_LEVER.placeholders)


def test_a_mutation_that_drops_the_schema_contract_is_rejected():
    inc = muse.MUSE_PROMPT
    bad = inc.replace("band_low_pct", "band_bottom")
    why = coach.validate_prompt(bad, inc, _MUSE_LEVER.placeholders,
                                must_contain=("band_low_pct", "JSON array"))
    assert "band_low_pct" in why


def test_a_bloated_mutation_is_rejected():
    inc = muse.MUSE_PROMPT
    assert "bloat" in coach.validate_prompt(inc * 3, inc, _MUSE_LEVER.placeholders)


def test_the_real_muse_prompt_passes_its_own_validator():
    """The incumbent must satisfy the rules its challengers are held to, or
    the validator is measuring something the system does not actually do."""
    other = muse.MUSE_PROMPT + "\n\nOne extra instruction line for difference."
    assert coach.validate_prompt(other, muse.MUSE_PROMPT, _MUSE_LEVER.placeholders,
                                 must_contain=("band_low_pct", "band_high_pct",
                                               "JSON array")) == ""


# --- rule 3: the ruler may not be moved by what it measures ---------------


def test_a_lever_cannot_experiment_while_its_own_scorer_is_being_tested(tmp_path, monkeypatch):
    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    gates = coach.Lever("muse.gates", "muse", ("muse.gates",), "policy")
    monkeypatch.setattr(coach, "LEVERS", (coach.LEVERS[0], gates))

    st = coach.load_state(cfg, "muse.prompt", "SEED")
    coach._open(cfg, st, coach.Variant("v1", "NEW"), journal)

    clash = coach._disjoint(cfg, gates)
    assert "muse.gates" in clash and "muse.prompt" in clash
    # and the reverse holds once the roles swap
    assert coach._disjoint(cfg, coach.LEVERS[0]) == ""


# --- the heartbeat ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_heartbeat_keys_match_exactly_what_the_health_probe_reads(tmp_path):
    """A probe reading a key nobody writes reports a confident zero forever.
    That is how `_market_pulse` stayed dead with a passing test (D-074)."""
    from trdrbot import health

    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    await coach.pulse(cfg, journal, seed_override={})
    rows = [r for r in journal.read() if r.get("kind") == "coach_run"]
    assert rows, "pulse wrote no heartbeat"

    probe = next(p for p in health.PROBES if p.name == "coach")
    assert probe.ran_kinds == ("coach_run",)
    # both callables must find their keys on a real heartbeat row
    assert probe.produced(rows) == 0
    assert probe.work is not None and probe.work(rows) == 0
    assert "trials_scored" in rows[0] and "experiments_open" in rows[0]

    # And the field the probe SUMS must be a per-heartbeat delta, not a running
    # total - health adds it across every row, so a cumulative field would be
    # counted once per pulse. Measured before this was fixed: three pulses over
    # seven real trials reported "produced 5".
    import inspect
    src = inspect.getsource(coach.pulse)
    assert '"trials_scored"] = sum' in src.replace("state[", '"').replace("'", '"') or \
        'state["trials_scored"]' in src
    assert "> last_beat" in src, (
        "trials_scored must count only events since the previous heartbeat")


@pytest.mark.asyncio
async def test_the_heartbeat_is_written_even_when_the_coach_is_disabled(tmp_path):
    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    cfg.coach = {"enabled": False}
    await coach.pulse(cfg, journal, seed_override={})
    assert [r for r in journal.read() if r.get("kind") == "coach_run"]


@pytest.mark.asyncio
async def test_an_operator_pause_closes_the_open_experiment_without_promoting(tmp_path):
    cfg, journal = _cfg(tmp_path), _journal(tmp_path)
    seed = "SEED " * 60
    st = coach.load_state(cfg, "muse.prompt", seed)
    coach._open(cfg, st, coach.Variant("v1", "NEW " * 60), journal)
    st = coach.load_state(cfg, "muse.prompt", seed)
    st.paused = True
    coach.save_state(cfg, st)

    await coach.pulse(cfg, journal, seed_override={"muse.prompt": seed})
    after = coach.load_state(cfg, "muse.prompt", seed)
    assert after.incumbent.id == "v0", "a paused lever was promoted"
    assert after.exp_id is None
    closes = [r for r in coach.events(cfg) if r.get("kind") == "experiment_closed"]
    assert closes and closes[-1]["outcome"] == "operator_override"


# --- gauges ----------------------------------------------------------------


def test_a_gauge_with_no_data_is_omitted_rather_than_written_as_zero(tmp_path):
    """A zero meaning "no data" is indistinguishable on a chart from a real
    collapse to zero - the absence-as-zero class (notes/012)."""
    cfg = _cfg(tmp_path)
    g = coach.snapshot_gauges(cfg, [])
    assert "muse.survival_rate" not in g
    assert "muse.candidates_per_run" not in g
    assert g["coach.open_experiments"] == 0  # genuinely measured, genuinely zero


def test_the_survival_gauge_counts_every_fate_that_survived_the_gauntlet(tmp_path):
    cfg = _cfg(tmp_path)
    rows = [{"kind": "muse", "candidates": 4, "fates": [
        {"fate": "EMITTED"}, {"fate": "candidate, not emitted (rank)"},
        {"fate": "rejected: base probability 3% - a lottery ticket"},
        {"fate": "rejected: no usable price history"}]}]
    assert coach.snapshot_gauges(cfg, rows)["muse.survival_rate"] == pytest.approx(0.5)


def test_seed_entropy_counts_distinct_collision_pairs(tmp_path):
    cfg = _cfg(tmp_path)
    rows = [{"kind": "muse", "candidates": 1, "concepts": ["a", "b"], "fates": []},
            {"kind": "muse", "candidates": 1, "concepts": ["a", "b"], "fates": []},
            {"kind": "muse", "candidates": 1, "concepts": ["a", "c"], "fates": []}]
    assert coach.snapshot_gauges(cfg, rows)["muse.seed_entropy"] == 2


def test_the_other_two_thesis_sources_and_the_ladder_are_measured_too(tmp_path):
    """The module map names a metric per module; the muse had three and the
    rest had none, so the report could not say whether research had stopped
    producing or discovery's gauntlet had tightened."""
    rows = [
        {"kind": "research", "opportunities": 3},
        {"kind": "research", "opportunities": 1},
        {"kind": "discovery", "nominees": ["A", "B", "C", "D"], "opportunities": 1},
        {"kind": "attribution", "verdict": "thesis_right_expression_right"},
        {"kind": "attribution", "verdict": "thesis_wrong_expression_faithful"},
        {"kind": "attribution", "verdict": "thesis_wrong_profited_anyway"},
        {"kind": "attribution", "verdict": "unscoreable"},
        # The subsystem heartbeat shares the kind and carries no verdict; it is
        # a run record, not an outcome, and must not dilute the rate.
        {"kind": "attribution", "pending": 0, "attributed": 4, "skipped_no_price": 0},
    ]
    g = coach.snapshot_gauges(_cfg(tmp_path), rows)
    assert g["research.opportunities_per_run"] == pytest.approx(2.0)
    assert g["discovery.gauntlet_survival"] == pytest.approx(0.25)
    # Same definition as `competence.attributable_rate`: a lucky win and an
    # unscoreable outcome both teach nothing and neither counts.
    assert g["attribution.attributable_rate"] == pytest.approx(0.5)


def test_the_new_gauges_are_omitted_rather_than_zeroed_when_there_is_no_data(tmp_path):
    """Each of the three obeys the module's own rule. A research yield of 0.0
    means "the cycle ran and found nothing", which is a real and alarming
    reading - it must not be what "the cycle has not run" looks like."""
    g = coach.snapshot_gauges(_cfg(tmp_path), [])
    for name in ("research.opportunities_per_run", "discovery.gauntlet_survival",
                 "attribution.attributable_rate"):
        assert name not in g
    # A run that genuinely produced nothing DOES read zero.
    g2 = coach.snapshot_gauges(_cfg(tmp_path), [{"kind": "research", "opportunities": 0}])
    assert g2["research.opportunities_per_run"] == 0.0


def test_the_attributable_gauge_agrees_with_the_ladder_it_mirrors(tmp_path):
    """It gates real position size in `competence.assess`. Two copies of one
    definition drifting apart is this project's most familiar bug, so the
    journal-derived gauge is checked against the store-derived original."""
    from types import SimpleNamespace

    from trdrbot import competence

    verdicts = ["thesis_right_expression_right", "thesis_right_expression_wrong",
                "thesis_wrong_expression_faithful", "thesis_wrong_profited_anyway",
                "unscoreable"]
    ladder, _ = competence.attributable_rate(
        [SimpleNamespace(attribution=v) for v in verdicts])
    gauge = coach.snapshot_gauges(
        _cfg(tmp_path), [{"kind": "attribution", "verdict": v} for v in verdicts],
    )["attribution.attributable_rate"]
    assert gauge == pytest.approx(ladder)


# --- scoring an arm --------------------------------------------------------


def test_a_reply_that_parses_to_nothing_scores_as_failures_not_as_silence():
    """GLM-5.2 burned an entire 8,000-token budget and returned zero characters
    (D-084) - a "successful" call nothing else penalises. If an empty reply
    scored nothing, a variant that always produced nothing would be
    unfalsifiable by its own reward."""
    r = muse._score_arm([], muse.CANDIDATES)
    assert r["survived"] == 0 and r["failed"] == muse.CANDIDATES


def test_scoring_counts_emitted_and_ranked_out_candidates_as_survivors():
    """Emission rank is not a gate - a candidate that cleared every gate and
    then lost a rank cut still proves the prompt produced a good thesis."""
    ev = [{"fate": "EMITTED"}, {"fate": "candidate, not emitted (rank)"},
          {"fate": "candidate"}, {"fate": "rejected: no usable price history"}]
    r = muse._score_arm(ev, muse.CANDIDATES)
    assert r["survived"] == 3 and r["failed"] == 1


# --- the report ------------------------------------------------------------


def test_the_report_renders_from_completely_empty_stores(tmp_path):
    from trdrbot import report

    cfg = _cfg(tmp_path)
    html = report.build(cfg)
    assert "<title>" in html and "The Coach" in html
    assert "http://" not in html and "https://" not in html, (
        "the report must be self-contained - it is read exactly when something "
        "has gone wrong, which is the worst time to need the network")


def test_echoed_delimiters_are_stripped_from_a_generated_prompt():
    """Measured on the first live mutation: the model copied the harness's own
    delimiter lines into the challenger text. Nothing downstream would have
    caught it - the result still formats and still validates - so a prompt
    carrying two lines of this module's scaffolding would have gone live."""
    assert coach.clean_prompt("<<<PROMPT\nreal content here\nPROMPT") == "real content here"
    assert coach.clean_prompt("```\nreal content here\n```") == "real content here"
    assert coach.clean_prompt("- - - - - - - - - -\nbody\n- - - - - - - - - -") == "body"
    # content that merely CONTAINS a fence-like line is untouched in the middle
    assert coach.clean_prompt("a\n---\nb") == "a\n---\nb"


def test_a_rejection_reason_is_fed_back_into_the_retry():
    """The validator's message names the exact defect, so handing it back is
    strictly better than spending the next mutation cooldown rediscovering it.
    Measured live: a first attempt fails a meaningful fraction of the time,
    always the same way - literal braces written in prose - and an attempt told
    exactly that fixes it."""
    filled = coach.RETRY_SUFFIX.format(reason="not a safe format template (KeyError: ' and ')")
    assert "REJECTED" in filled and "KeyError" in filled
    assert coach.MUTATE_ATTEMPTS >= 2, "a single-shot mutation wastes a whole cooldown"


def test_the_mutate_prompt_warns_about_braces_outside_the_json_example():
    """The first live mutation failure wrote `{X and Y}` in ORDINARY PROSE, not
    in the JSON block - the original warning only mentioned the JSON example,
    so it was true and insufficient."""
    assert "not only inside the JSON" in coach.MUTATE_PROMPT
    assert "ordinary prose" in coach.MUTATE_PROMPT


# --- crash safety: the log is the truth, state is a cache of it ------------


def test_a_duplicate_run_nonce_is_counted_once(tmp_path):
    """`muse.run` derives its nonce from today's `muse` journal rows but calls
    `record_trial` BEFORE appending its own row - so a crash in that window
    makes the next run compute the SAME nonce and write a second trial_result
    for one run. Both counted toward runs, successes, failures and therefore
    the posterior, inflating the evidence for whichever arm was duplicated.
    The field existed from the start with nothing reading it."""
    cfg = _cfg(tmp_path)
    arm = {"survived": 3, "failed": 2, "candidates": 5}
    coach._append(coach.events_path(cfg), {
        "kind": "experiment_opened", "exp_id": "exp_1", "lever": "muse.prompt",
        "incumbent": "v0", "challenger": "v1"})
    for _ in range(2):  # the same run, recorded twice
        coach._append(coach.events_path(cfg), {
            "kind": "trial_result", "exp_id": "exp_1", "run_nonce": 0,
            "incumbent": arm, "challenger": arm})

    t = coach.tally(cfg, "exp_1")

    assert t.runs == 1, f"the duplicate was counted as a second run: {t.runs}"
    assert (t.s_i, t.f_i) == (3, 2)
    assert t.voided == 1, "the duplicate should be visible, not silently dropped"


def test_distinct_nonces_still_accumulate(tmp_path):
    """The dedup must not collapse genuinely separate runs."""
    cfg = _cfg(tmp_path)
    arm = {"survived": 3, "failed": 2, "candidates": 5}
    coach._append(coach.events_path(cfg), {
        "kind": "experiment_opened", "exp_id": "exp_1", "lever": "muse.prompt",
        "incumbent": "v0", "challenger": "v1"})
    for nonce in (0, 1, 2):
        coach._append(coach.events_path(cfg), {
            "kind": "trial_result", "exp_id": "exp_1", "run_nonce": nonce,
            "incumbent": arm, "challenger": arm})

    assert coach.tally(cfg, "exp_1").runs == 3


def test_an_experiment_with_no_opened_event_is_cleared_rather_than_stuck(tmp_path):
    """`_open` used to save state BEFORE appending its event - the opposite of
    `_close` and `_promote`. A crash between them left state naming an exp_id
    with no opened row: tally() None forever, is_closed() False forever, so the
    muse kept running a paired trial whose results could never be scored, and
    nothing repaired it."""
    cfg = _cfg(tmp_path)
    st = coach.LeverState(lever="muse.prompt", incumbent=coach.Variant("v0", "seed"))
    st.challenger = coach.Variant("v1", "challenger text")
    st.exp_id = "exp_orphaned"
    coach.save_state(cfg, st)

    applied = coach.reconcile(cfg, seed_override={"muse.prompt": "seed"})

    assert any("exp_orphaned" in a for a in applied)
    healed = coach.load_state(cfg, "muse.prompt", "seed")
    assert healed.exp_id is None and healed.challenger is None
    assert coach.arms(cfg, "muse.prompt", seed_text="seed").paired is False


def test_open_appends_the_event_before_it_swaps_state(tmp_path):
    """Ordering IS the crash-safety property, so it is asserted on the
    artifacts rather than trusted: after _open, the event log must already
    carry the experiment that lever state names."""
    cfg = _cfg(tmp_path)
    journal = _journal(tmp_path)
    st = coach.LeverState(lever="muse.prompt", incumbent=coach.Variant("v0", "seed"))

    coach._open(cfg, st, coach.Variant("v1", "challenger text"), journal)

    opened = [r for r in coach.events(cfg) if r.get("kind") == "experiment_opened"]
    assert [r["exp_id"] for r in opened] == [st.exp_id]
    assert coach.reconcile(cfg, seed_override={"muse.prompt": "seed"}) == [], \
        "a freshly opened experiment must not look orphaned"


def test_a_broken_gauge_is_reported_rather_than_silently_omitted(tmp_path, monkeypatch):
    """This module's own rule is that a gauge with no data must be OMITTED, not
    written as zero - on a chart those are indistinguishable. But an exception
    omitted it identically and silently, so "the calibration store is broken"
    and "there is no calibration data yet" produced the same empty slot. That
    is D-038's absence-as-zero defect reappearing inside the module that
    preaches against it."""
    cfg = _cfg(tmp_path)
    (tmp_path / "state" / "ledger.jsonl").write_text("{ this will not parse\n")

    def explode(*a, **k):
        raise RuntimeError("ledger unreadable")

    # Patched at the source module, not on coach: `snapshot_gauges` imports
    # ledger locally, so there is no coach attribute to patch - and the real
    # module is the honest boundary anyway.
    monkeypatch.setattr("trdrbot.ledger.Ledger", explode)
    g = coach.snapshot_gauges(cfg, rows=[])

    assert "calibration.n" not in g, "a broken gauge must not be written as a value"
    assert "calibration" in g.get("gauges_failed", []), "the failure is invisible"


def test_gauges_that_simply_have_no_data_yet_report_no_failure(tmp_path):
    """The distinction has to cut both ways, or `gauges_failed` becomes noise
    and stops meaning anything."""
    g = coach.snapshot_gauges(_cfg(tmp_path), rows=[])

    assert "gauges_failed" not in g


# --- a lever is a declaration, not a code change ---------------------------


def _synthetic_lever() -> coach.Lever:
    """A second lever, declared exactly as a real one would be."""
    return coach.Lever(
        "widget.prompt", "widget", ("widget.gates",), "prompt",
        seed_ref=("fixtures_lever", "SEED"),
        placeholders=("today", "n", "k"),
        must_contain=("widget_low_pct", "JSON array"),
        evidence_kind="widget",
    )


def test_a_seed_resolves_by_import_and_a_bad_ref_degrades(capsys):
    """`seed_ref` is (module, attribute) resolved on demand - data, not a
    callable, because a callable in a module-level registry would have to be
    imported at module scope and that is how the coach package's import cycle
    would come straight back."""
    from fixtures_lever import SEED

    # `seed_text` is the internal resolver; `coach.seeds()` is what callers
    # use, and `arms(seed_text=...)` is where the resolved text lands.
    from trdrbot.coach_pkg.state import seed_text

    assert seed_text(_synthetic_lever()) == SEED

    broken = coach.Lever("x", "x", (), "prompt", seed_ref=("no.such.module", "X"))
    assert seed_text(broken) == ""
    assert "cannot resolve seed" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_a_lever_is_registered_by_declaration_alone(tmp_path, monkeypatch):
    """THE proof of the work unit: a second lever runs the FULL experiment
    cycle with no muse anywhere in it and no Coach internals edited.

    Everything the generic machinery needs - the seed, the placeholders, the
    validator's anchors, the evidence stream - now comes off the declaration.
    It used to come off literals inside `mutate` and a
    `{"muse.prompt": MUSE_PROMPT}` dict copy-pasted at three call sites.
    """
    lv = _synthetic_lever()
    monkeypatch.setattr(coach, "LEVERS", (lv,))
    monkeypatch.setattr("trdrbot.coach_pkg.state.LEVERS", (lv,))
    cfg = _cfg(tmp_path)
    journal = _journal(tmp_path)

    # 1. the registry supplies its seed, with no caller passing one
    assert set(coach.seeds()) == {"widget.prompt"}
    st = coach.load_state(cfg, lv.name, coach.seeds()[lv.name])
    assert st.incumbent.text.startswith("You are a test subsystem")

    # 2. arms() hands the subsystem an incumbent - unpaired until one opens
    assert coach.arms(cfg, lv.name, seed_text=coach.seeds()[lv.name]).paired is False

    # 3. a challenger opens
    challenger = coach.Variant("v1", st.incumbent.text.replace("Consider", "Weigh"))
    coach._open(cfg, st, challenger, journal)
    arms = coach.arms(cfg, lv.name, seed_text=coach.seeds()[lv.name])
    assert arms.paired and arms.challenger.id == "v1"

    # 4. paired trials accumulate, scored by the generic tally
    strong = ({"survived": 1, "failed": 4, "candidates": 5},
              {"survived": 5, "failed": 0, "candidates": 5})
    for nonce in range(coach.MIN_RUNS):
        coach.record_trial(cfg, arms.exp_id, run_nonce=nonce,
                           incumbent=strong[0], challenger=strong[1])
    t = coach.tally(cfg, arms.exp_id)
    assert t.runs == coach.MIN_RUNS and t.posterior > coach.PROMOTE_AT

    # 5. the generic verdict promotes it, and the state file shows the swap
    outcome, reason = coach.verdict(t, coach.floors(cfg))
    assert outcome == "promoted", reason
    coach._promote(cfg, coach.load_state(cfg, lv.name, ""), t, reason, journal)

    assert coach.load_state(cfg, lv.name, "").incumbent.id == "v1"


def test_the_mutation_validates_against_the_levers_own_anchors():
    """`mutate` passed the MUSE's anchors as literals, so a second lever would
    have had its challengers validated against a contract belonging to another
    subsystem."""
    lv = _synthetic_lever()
    from fixtures_lever import SEED

    dropped = SEED.replace("widget_low_pct", "something_else")
    assert "widget_low_pct" in coach.validate_prompt(
        dropped, SEED, lv.placeholders, must_contain=lv.must_contain)

    # ...and the muse's own anchors are irrelevant to it
    assert coach.validate_prompt(
        dropped, SEED, lv.placeholders,
        must_contain=("band_low_pct",)) != ""


def test_a_lever_with_no_evidence_stream_still_mutates():
    """An evidence kind is optional - a new lever has no rejection history and
    must not be blocked from ever generating a challenger by its absence."""
    assert "no rejection evidence" in coach._rejection_digest([], "")
    assert coach._rejection_digest([{"kind": "widget", "fates": [
        {"fate": "rejected: too wide"}]}], "widget").startswith("- rejected: too wide")
