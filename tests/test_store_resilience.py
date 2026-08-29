"""What the persistent stores do when a file on disk is not what they expect.

Every store here is append-or-rewrite plain text on a laptop that gets closed,
so a partial line is a real operating condition rather than a hypothetical.
The suite had no coverage of it at all, and two of the readers - the two most
critical ones - raised on the first bad byte.
"""

from __future__ import annotations

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
