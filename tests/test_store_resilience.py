"""What the persistent stores do when a file on disk is not what they expect.

Every store here is append-or-rewrite plain text on a laptop that gets closed,
so a partial line is a real operating condition rather than a hypothetical.
The suite had no coverage of it at all, and two of the readers - the two most
critical ones - raised on the first bad byte.
"""

from __future__ import annotations

import contextlib
import json

from trdrbot.calibration import CalibrationStore
from trdrbot.journal import Journal


def test_one_truncated_journal_line_does_not_blind_every_reader(tmp_path, capsys):
    """The journal is the ground-truth store and was the LEAST fault-tolerant
    reader in the system - a bare json.loads per line, where ledger and health
    already skipped bad ones. Appends are buffered and rows carry a 2000-char
    summary, so a crash mid-flush really does leave a partial line; one of
    those made last_decision_at, unresolved_decision, the muse nonce, the muse
    daily cap and coach.pulse all raise at once.
    """
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append("decision", batch="b1")
    with journal.path.open("a") as fh:
        fh.write('{"kind": "execution", "ts": "2026-08-29T10:00:00+00:00", "batch"\n')
    journal.append("no_op", batch="b2")

    rows = list(journal.read())

    assert [r["kind"] for r in rows] == ["decision", "no_op"]
    assert journal.last_decision_at() is not None
    assert "skipped 1 unparseable" in capsys.readouterr().out


def test_the_journal_still_resolves_an_unresolved_decision_past_a_bad_line(tmp_path):
    """INV-27's resume check reads the whole journal, so a corrupt line used to
    mean re-deciding a batch that already had a write-ahead record."""
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append("decision", batch="bat_x")
    with journal.path.open("a") as fh:
        fh.write("not json at all\n")

    assert journal.unresolved_decision("bat_x") is not None


def test_a_truncated_forecast_line_does_not_kill_every_tick(tmp_path, capsys):
    """CalibrationStore is constructed at the TOP of every tick, before
    anything else runs, and parsed with no error handling at all - so one bad
    line in forecasts.jsonl killed every tick, permanently, until someone
    edited the file by hand."""
    path = tmp_path / "forecasts.jsonl"
    store = CalibrationStore(path)
    store.record("pos_1", probability=0.6, subject="SPY")
    with path.open("a") as fh:
        fh.write('{"position_id": "pos_2", "probab\n')

    reloaded = CalibrationStore(path)

    assert [f.position_id for f in reloaded._items] == ["pos_1"]
    assert "skipped 1 unreadable" in capsys.readouterr().out


def test_a_forecast_with_an_unknown_field_survives_rather_than_being_deleted(tmp_path):
    """`Forecast(**d)` raised TypeError on any key the dataclass had not heard
    of - and because `_flush` rewrites the WHOLE file, a row skipped on load is
    a row deleted on the next write. Adding one field would have silently
    destroyed the calibration record it was meant to enrich.
    """
    path = tmp_path / "forecasts.jsonl"
    path.write_text(json.dumps({
        "position_id": "pos_old", "probability": 0.7, "outcome": True,
        "resolved_at": "2026-08-01", "subject": "SPY",
        "future_field_from_a_later_version": 42,
    }) + "\n")

    store = CalibrationStore(path)
    assert [f.position_id for f in store._items] == ["pos_old"]

    store.record("pos_new", probability=0.5, subject="QQQ")  # forces a full rewrite
    survivors = [json.loads(x)["position_id"] for x in path.read_text().splitlines() if x]
    assert survivors == ["pos_old", "pos_new"], "the drifted row was deleted by the rewrite"


def test_an_empty_forecast_file_is_not_an_error(tmp_path):
    path = tmp_path / "forecasts.jsonl"
    path.write_text("\n\n")
    assert CalibrationStore(path).resolved() == []


# ------------------------------------------------------------ atomic writes


def test_write_atomic_leaves_the_original_intact_when_the_swap_fails(tmp_path, monkeypatch):
    """The failure this prevents: a truncate-then-write that dies in the middle
    leaves neither the old contents nor the new. `write_atomic` writes a
    sibling and swaps, so the reader sees one or the other."""
    from trdrbot import store

    path = tmp_path / "ledger.jsonl"
    path.write_text("original\n")

    def boom(src, dst):
        raise OSError("crash during swap")

    monkeypatch.setattr(store.os, "replace", boom)
    with contextlib.suppress(OSError):
        store.write_atomic(path, "replacement\n")

    assert path.read_text() == "original\n", "the original was destroyed"


def test_the_ledger_rewrite_is_atomic(tmp_path, monkeypatch):
    """`_rewrite` fires once per candidate per gate during a muse run, over the
    whole file. `data/state/ledger.jsonl.bak-before-repair` on disk is what
    this class of failure looks like when it lands."""
    from trdrbot import store
    from trdrbot.ledger import Ledger

    path = tmp_path / "ledger.jsonl"
    book = Ledger(path)
    e = book.register(kind="muse", underlying="SPY", claim="c", probability=0.4,
                      horizon="2026-09-02", band_low=1.0, band_high=2.0)
    before = path.read_text()

    monkeypatch.setattr(store.os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError("crash")))
    with contextlib.suppress(OSError):
        book.mark_rejected(e.id, "some gate")

    assert path.read_text() == before, "a crashed rewrite truncated the ledger"


def test_a_ledger_row_with_an_unknown_field_survives_the_next_rewrite(tmp_path):
    """`Entry(**json.loads(line))` raised TypeError on any key the dataclass had
    not heard of, and the row was skipped on load - then DELETED by the next
    `_rewrite`. Adding one field to Entry was therefore a silent way to destroy
    the pre-registration history that the multiple-testing correction (D-052)
    depends on."""
    from trdrbot.ledger import Ledger

    path = tmp_path / "ledger.jsonl"
    book = Ledger(path)
    kept = book.register(kind="muse", underlying="SPY", claim="c", probability=0.4,
                         horizon="2026-09-02", band_low=1.0, band_high=2.0)
    row = json.loads(path.read_text().splitlines()[0])
    with path.open("a") as fh:
        fh.write(json.dumps({**row, "id": "fc_from_the_future",
                             "underlying": "QQQ",
                             "a_field_added_in_a_later_version": 42}) + "\n")

    reloaded = Ledger(path)
    assert {e.id for e in reloaded.all()} == {kept.id, "fc_from_the_future"}

    reloaded.mark_rejected(kept.id, "a gate")  # forces the full rewrite
    survivors = {json.loads(x)["id"] for x in path.read_text().splitlines() if x}
    assert survivors == {kept.id, "fc_from_the_future"}, "the drifted row was deleted"


def test_a_corrupt_high_water_file_is_loud_rather_than_silently_unguarding(tmp_path):
    """A corrupt high_water.json reset the peak to 0.0, at which point
    `equity > hw` was trivially true and the peak became today's equity - so
    drawdown computed to exactly 0 and DEMOTION SILENTLY STOPPED WORKING until
    a new peak formed naturally. Fail-open on a capital-protection input, with
    nothing anywhere saying so."""
    from trdrbot import competence
    from trdrbot.journal import Journal

    state = tmp_path / "state"
    state.mkdir()
    (state / "high_water.json").write_text("{not json")
    journal = Journal(tmp_path / "journal.jsonl")

    hw = competence.update_high_water(state, 100_000.0, journal)

    assert hw == 100_000.0  # the degrade itself is unchanged - the peak is gone
    rows = [r for r in journal.read() if r.get("kind") == "state_corrupt"]
    assert len(rows) == 1
    assert rows[0]["consequence"] == "drawdown_unguarded"


def test_a_readable_high_water_file_journals_nothing(tmp_path):
    """The corruption row must mean something when it appears."""
    import json as _json

    from trdrbot import competence
    from trdrbot.journal import Journal

    state = tmp_path / "state"
    state.mkdir()
    (state / "high_water.json").write_text(_json.dumps({"high_water": 120_000.0}))
    journal = Journal(tmp_path / "journal.jsonl")

    hw = competence.update_high_water(state, 100_000.0, journal)

    assert hw == 120_000.0, "the real peak must survive a lower equity reading"
    assert [r for r in journal.read() if r.get("kind") == "state_corrupt"] == []


# ------------------------------------------------------- the JSONL primitives


def test_an_appended_row_carries_a_schema_version(tmp_path):
    """`v` is what makes the NEXT schema change auditable. Measured before it
    existed: `decision` rows carry four distinct key shapes across the
    journal's history, every consumer absorbing the drift with `.get()`, and
    no way to tell which population a historical aggregate is mixing."""
    from trdrbot import store

    path = tmp_path / "rows.jsonl"
    store.append_jsonl(path, {"kind": "thing", "n": 1})

    rows, skipped = store.read_jsonl(path)
    assert rows == [{"v": store.SCHEMA_VERSION, "kind": "thing", "n": 1}]
    assert skipped == 0


def test_rows_written_before_versioning_still_read(tmp_path):
    """Nothing rewrites history, so a mixed file is the normal state."""
    from trdrbot import store

    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({"kind": "old", "n": 0}) + "\n")
    store.append_jsonl(path, {"kind": "new", "n": 1})

    rows, _ = store.read_jsonl(path)
    assert [r["kind"] for r in rows] == ["old", "new"]
    assert "v" not in rows[0] and rows[1]["v"] == store.SCHEMA_VERSION


def test_a_ground_truth_write_failure_is_loud_and_a_bookkeeping_one_is_not(tmp_path):
    """The failure POLICY is the argument, because the three appenders this
    replaced each chose a different one silently. The journal must not lose a
    write quietly; a gauge row must never break a trade."""
    import pytest

    from trdrbot import store

    unwritable = tmp_path / "nope"
    unwritable.write_text("i am a file, not a directory")
    target = unwritable / "rows.jsonl"

    with pytest.raises(OSError):
        store.append_jsonl(target, {"kind": "ground_truth"})

    assert store.append_jsonl(target, {"kind": "bookkeeping"}, advisory=True) is False


def test_the_journal_still_reports_what_it_skipped(tmp_path, capsys):
    """Behaviour preserved through the move to the shared reader."""
    from trdrbot.journal import Journal

    journal = Journal(tmp_path / "journal.jsonl")
    journal.append("decision", batch="b1")
    with journal.path.open("a") as fh:
        fh.write("{ truncated\n")

    assert [r["kind"] for r in journal.read()] == ["decision"]
    assert "skipped 1 unparseable" in capsys.readouterr().out


def test_the_usage_ledger_ignores_keys_Call_has_not_heard_of(tmp_path):
    """`v` is one such key, and so is any field added later - a row must not
    become unreadable because the dataclass grew."""
    from trdrbot.usage import UsageLedger

    path = tmp_path / "usage.jsonl"
    led = UsageLedger(path)
    led.record("decide", "some-model", 100, 50)

    reread = UsageLedger(path).calls()
    assert len(reread) == 1
    assert reread[0].role == "decide" and reread[0].input_tokens == 100
