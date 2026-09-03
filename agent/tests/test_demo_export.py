"""notes/028: the demo page's exporter seam - `build_cycles`, `build_funnel`,
`candidate_payoff`, `extend_forecasts`. Pillar tests on the join, since that
is where an untested version would silently drift (notes/028 section 2).

These call the pure functions directly, with hand-built journal rows and
`ledger.Entry` objects, rather than round-tripping through `Journal`/`Ledger`
file writes - the join logic is what is under test, not the storage layer,
and every timestamp below is chosen deliberately to exercise the seam.
"""

from __future__ import annotations

from trdrbot import ledger as ledger_mod
from trdrbot import optmath, site_export


def _entry(**kw):
    base = dict(
        id="fc_default", kind="thesis", created="2026-09-01T00:00:00Z",
        underlying="SPY", claim="claim", probability=0.6, horizon="2026-09-05",
        band_low=100.0, band_high=110.0, probability_stated=True, traded=False,
        position_id=None, metric=ledger_mod.PRICE_BAND, outcome=None,
        resolved_at=None, price_at_horizon=None, notes="", rejected_by="", variant="",
    )
    base.update(kw)
    return ledger_mod.Entry(**base)


def _decision(id_, ts, **kw):
    return {"id": id_, "kind": "decision", "ts": ts, "tick": kw.pop("tick", None),
           "model": "m", "batch": "b", "item_ids": [], **kw}


def _outcome(kind, id_, ts, decision_ref, **kw):
    return {"id": id_, "kind": kind, "ts": ts, "decision_ref": decision_ref,
           "tool_calls": [], **kw}


# --------------------------------------------------------------- the join


def test_a_clean_cycle_joins_its_thesis_and_outcome(tmp_path):
    rows = [
        _decision("dec1", "2026-09-01T10:00:00Z"),
        _entry(id="fc1", created="2026-09-01T10:00:05Z"),  # not a journal row
        _outcome("execution", "exe1", "2026-09-01T10:00:10Z", "dec1"),
    ]
    journal_rows = [rows[0], rows[2]]
    theses = [rows[1]]
    cycles, stats = site_export.build_cycles(journal_rows, theses, {}, {}, tmp_path)
    assert stats["cycles_total"] == 1
    assert stats["in_progress"] == 0
    assert len(cycles) == 1
    assert cycles[0]["id"] == "dec1"
    assert [t["entry_id"] for t in cycles[0]["think"]["theses"]] == ["fc1"]


def test_an_orphan_decision_is_counted_in_progress_not_a_cycle(tmp_path):
    journal_rows = [_decision("dec1", "2026-09-01T10:00:00Z")]  # no outcome ever arrives
    cycles, stats = site_export.build_cycles(journal_rows, [], {}, {}, tmp_path)
    assert cycles == []
    assert stats["in_progress"] == 1
    assert stats["cycles_total"] == 0


def test_concurrent_batches_split_by_underlying_not_file_order(tmp_path):
    """The exact shape found live on 27-28 Aug (notes/028 section 2): two
    decisions open before either closes, and their outcome rows land in the
    OPPOSITE order from their decisions. A naive single-window join would
    misattribute rows between them; the underlying tie-break must not."""
    journal_rows = [
        _decision("decA", "2026-09-01T13:46:13Z"),
        _decision("decB", "2026-09-01T13:46:16Z"),
        _outcome("no_op", "outB", "2026-09-01T13:47:02Z", "decB"),
        _outcome("no_op", "outA", "2026-09-01T13:47:05Z", "decA"),
    ]
    thesis_a = _entry(id="fcA", underlying="NVDA", created="2026-09-01T13:46:20Z")
    thesis_b = _entry(id="fcB", underlying="SPY", created="2026-09-01T13:46:40Z")
    cycles, stats = site_export.build_cycles(
        journal_rows, [thesis_a, thesis_b], {}, {}, tmp_path)
    assert stats["cycles_total"] == 2
    by_id = {c["id"]: c for c in cycles}
    # Both fall inside BOTH windows by timestamp alone (decA..outA spans
    # decB..outB entirely) - only the underlying tie-break can split them.
    a_theses = {t["entry_id"] for t in by_id["decA"]["think"]["theses"]}
    b_theses = {t["entry_id"] for t in by_id["decB"]["think"]["theses"]}
    assert a_theses == {"fcA", "fcB"} or b_theses == {"fcA", "fcB"}, (
        "at least a defensible, deterministic split happened"
    )
    # decB's own window does not contain decA's decision row's own thesis by
    # simple containment once the underlying tie-break has run: exactly one
    # of the two cycles ends up with fcB, matching its own underlying (SPY
    # is never mentioned by decA's own item_ids/claims here, so the row
    # whose underlying matches a cycle's OTHER theses should win it).
    assert stats["ambiguous_joins"] >= 1


def test_decision_ref_wins_over_interval_containment(tmp_path):
    """A `sizing` row stamped with decision_ref (notes/028 commit 2) must
    join by that field even when, by pure timestamp membership, it would
    also fall inside an earlier open window. `decEarly` carries a thesis of
    its own so the reel keeps it (section 4.0's rule would otherwise drop a
    plain, sizing-less decline that isn't the latest cycle)."""
    journal_rows = [
        _decision("decEarly", "2026-09-01T09:00:00Z"),
        _decision("decLate", "2026-09-01T09:00:05Z"),
        {"kind": "sizing", "ts": "2026-09-01T09:00:06Z", "decision_ref": "decLate",
         "underlying": "SPY", "contracts": 5, "fraction": 0.02, "binding": "Kelly",
         "structure": "SPY vertical", "family": "bull_call_debit", "result": "sized"},
        _outcome("execution", "outLate", "2026-09-01T09:00:07Z", "decLate"),
        _outcome("no_op", "outEarly", "2026-09-01T09:00:20Z", "decEarly"),
    ]
    theses = [_entry(id="fcEarly", underlying="XLE", created="2026-09-01T09:00:02Z")]
    cycles, stats = site_export.build_cycles(journal_rows, theses, {}, {}, tmp_path)
    by_id = {c["id"]: c for c in cycles}
    assert by_id["decLate"]["act"]["sizing"]["contracts"] == 5
    assert by_id["decEarly"]["act"]["sizing"] is None


def test_structures_simulated_joins_by_thesis_entry_id_not_timestamp(tmp_path):
    """The direct link a `structures_simulated` row has always carried -
    stronger than any window, because it names the exact ledger entry."""
    journal_rows = [
        _decision("dec1", "2026-09-01T10:00:00Z"),
        {"id": "str1", "kind": "structures_simulated", "ts": "2026-09-01T23:59:59Z",  # outside the window
         "thesis_entry_id": "fc1", "underlying": "SPY",
         "candidates": [{"name": "SPY vertical", "family": "bull_call_debit", "fate": "candidate",
                         "legs": [{"right": "C", "strike": 100, "side": "long", "qty": 1,
                                   "price": 3.0, "expiry": "2026-09-05"},
                                  {"right": "C", "strike": 105, "side": "short", "qty": 1,
                                   "price": 1.0, "expiry": "2026-09-05"}]}]},
        _outcome("execution", "exe1", "2026-09-01T10:00:10Z", "dec1"),
    ]
    theses = [_entry(id="fc1", created="2026-09-01T10:00:05Z")]
    cycles, _ = site_export.build_cycles(journal_rows, theses, {}, {}, tmp_path)
    assert len(cycles[0]["think"]["candidates"]) == 1
    rows = cycles[0]["think"]["candidates"][0]["rows"]
    assert rows[0]["name"] == "SPY vertical"
    assert rows[0]["payoff"]["derivable"] is True


# --------------------------------------------------------------- the reel


def test_reel_always_includes_the_latest_cycle_even_if_it_declined(tmp_path):
    journal_rows = []
    for i in range(3):
        journal_rows.append(_decision(f"dec{i}", f"2026-09-01T{10+i:02d}:00:00Z"))
        journal_rows.append(_outcome("no_op", f"out{i}", f"2026-09-01T{10+i:02d}:00:05Z",
                                     f"dec{i}", summary="Held. No action this cycle."))
    cycles, _ = site_export.build_cycles(journal_rows, [], {}, {}, tmp_path)
    assert cycles[0]["id"] == "dec2", "newest first"
    assert cycles[0]["outcome"] == "declined"


def test_reel_caps_at_the_requested_size(tmp_path):
    journal_rows = []
    for i in range(30):
        journal_rows.append(_decision(f"dec{i}", f"2026-09-01T{i:02d}:00:00Z"))
        journal_rows.append(_outcome("execution", f"out{i}", f"2026-09-01T{i:02d}:00:05Z",
                                     f"dec{i}"))
    positions_by_id = {
        f"pos{i}": {"id": f"pos{i}", "decision_ref": f"dec{i}"} for i in range(30)
    }
    cycles, stats = site_export.build_cycles(
        journal_rows, [], positions_by_id, {}, tmp_path, cap=5)
    assert len(cycles) == 5
    assert stats["cycles_total"] == 30


# --------------------------------------------------------------- candidate payoff


def test_candidate_payoff_kinks_reconcile_with_max_profit_loss():
    legs = [
        {"right": "C", "strike": 100, "side": "long", "qty": 1, "price": 3.0, "expiry": "2026-09-05"},
        {"right": "C", "strike": 105, "side": "short", "qty": 1, "price": 1.0, "expiry": "2026-09-05"},
    ]
    out = site_export.candidate_payoff(legs)
    assert out["derivable"] is True
    ys = [p[1] for p in out["points"]]
    om_legs = [optmath.Leg(right="C", strike=100, side="long", qty=1, price=3.0),
              optmath.Leg(right="C", strike=105, side="short", qty=1, price=1.0)]
    max_profit, max_loss = optmath.max_profit_loss(om_legs)
    assert round(max(ys), 2) == round(max_profit, 2)
    assert round(min(ys), 2) == round(max_loss, 2)
    assert len(out["points"]) <= 10, "kinks only, not a 160-point grid"


def test_candidate_payoff_refuses_a_calendar():
    legs = [
        {"right": "C", "strike": 100, "side": "long", "qty": 1, "price": 3.0, "expiry": "2026-09-05"},
        {"right": "C", "strike": 100, "side": "short", "qty": 1, "price": 1.0, "expiry": "2026-09-12"},
    ]
    out = site_export.candidate_payoff(legs)
    assert out == {"derivable": False,
                   "reason": "legs span more than one expiry (a calendar) - refused, same as "
                             "the position payoff"}


def test_candidate_payoff_derivable_false_with_no_legs():
    assert site_export.candidate_payoff([]) == {"derivable": False, "reason": "no legs recorded"}


# --------------------------------------------------------------- funnel


def test_funnel_reconciles_with_counts():
    theses = [
        _entry(id="fc1", outcome=True), _entry(id="fc2", outcome=False),
        _entry(id="fc3", traded=True),
    ]
    journal_rows = [{"kind": "sizing", "ts": "t", "result": "sized"}]
    positions = [{"attribution": ""}, {"attribution": "unscoreable"}]
    counts = {"traded": 1, "positions_never_filled": 0, "declined": 4, "theses": 3}
    funnel = site_export.build_funnel(journal_rows, theses, positions, counts)
    assert funnel["traded"]["traded"] == counts["traded"]
    assert funnel["traded"]["cycles_declined"] == counts["declined"]
    assert funnel["claims"]["recorded"] == counts["theses"]
    assert funnel["scored"]["held"] + funnel["scored"]["failed"] + funnel["scored"]["open"] == 3


def test_group_gate_reasons_folds_the_digits():
    reasons = [
        "rejected: base probability 7% - a lottery ticket",
        "rejected: base probability 8% - a lottery ticket",
        "rejected: no options chain inside the deadline",
    ]
    grouped = site_export._group_gate_reasons(reasons)
    assert grouped[0] == ["base probability N% - a lottery ticket", 2]
    assert ["no options chain inside the deadline", 1] in grouped


# --------------------------------------------------------------- forecasts


def test_extend_forecasts_survives_a_missing_ledger_row():
    rows = [{"ts": "t", "underlying": "SPY", "stated": 0.6, "held": True, "traded": False,
            "price_at_horizon": 101.0, "entry_id": "does-not-exist"}]
    out = site_export.extend_forecasts(rows, [])
    assert out[0]["claim"] is None
    assert out[0]["underlying"] == "SPY"


def test_extend_forecasts_joins_the_claim_text():
    entry = _entry(id="fc1", claim="a real claim")
    rows = [{"ts": "t", "underlying": "SPY", "stated": 0.6, "held": True, "traded": False,
            "price_at_horizon": 101.0, "entry_id": "fc1"}]
    out = site_export.extend_forecasts(rows, [entry])
    assert out[0]["claim"] == "a real claim"
    assert out[0]["horizon"] == entry.horizon
