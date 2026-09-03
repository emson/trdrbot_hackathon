"""The trade blog (D-097): one markdown story per position, entry and outcome.

Built from the real producers throughout - `make_position` for the position
shape, `local_tools.SharedContext`/`RecordedTrade`/`SimStructure` for what a
decide cycle actually has in scope - never a hand-rolled literal, for the same
reason the rest of this suite insists on it (D-063).
"""

from __future__ import annotations

from trdrbot import blog
from trdrbot.local_tools import RecordedTrade, SimStructure


def _structure(name, **kw):
    defaults = dict(key=(name,), qty=1, entry_cost=100.0, max_profit=300.0,
                    max_loss=-100.0, payoff_ratio=3.0, rr=3.0)
    defaults.update(kw)
    return SimStructure(name=name, **defaults)


def test_write_entry_produces_frontmatter_the_html_pass_can_key_off(tmp_path, make_position):
    """Metadata as YAML frontmatter, not buried in prose - the stated
    requirement (a later pass transforms these to HTML without re-parsing)."""
    pos = make_position()
    trade = RecordedTrade(position=pos, matched=None, alternatives=[], confidence=0.42)

    path = blog.write_entry(
        trade, summary_text="Because the tape confirmed it.", decision_ref="dec_1",
        batch="bat_1", model="anthropic:claude-opus-5", served=["anthropic:claude-opus-5"],
        blog_dir=tmp_path)

    assert path == blog.path_for(tmp_path, pos.position_id)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front, _, body = text[4:].partition("\n---\n")
    assert f"position_id: {pos.position_id}" in front
    assert "underlying: SPY" in front
    assert "confidence: 0.42" in front
    assert "date: 2026-08-28" in front and 'time: "17:34:00.843832+00:00"' in front


def test_write_entry_includes_the_agents_own_reasoning_verbatim(tmp_path, make_position):
    """The one thing this whole feature exists for: the model's own words,
    unparaphrased, in the published file."""
    pos = make_position()
    trade = RecordedTrade(position=pos, matched=None, alternatives=[], confidence=0.42)
    reasoning = "The driver is causal and dated, not chart shape. Honest confidence 0.42."

    path = blog.write_entry(trade, summary_text=reasoning, decision_ref="d", batch="b",
                            model="m", served=["m"], blog_dir=tmp_path)

    assert reasoning in path.read_text(encoding="utf-8")


def test_write_entry_names_the_chosen_structure_among_its_alternatives(tmp_path, make_position):
    """Chosen and discarded, in one table - the literal ask this feature
    exists to satisfy."""
    pos = make_position()
    chosen = _structure("766/758 put debit", max_loss=-2171.0, payoff_ratio=2.85)
    rejected = _structure("775/780 call credit spread", max_loss=-283.0, payoff_ratio=0.34)
    trade = RecordedTrade(position=pos, matched=chosen, alternatives=[rejected], confidence=0.42)

    path = blog.write_entry(trade, summary_text="reasoning", decision_ref="d", batch="b",
                            model="m", served=["m"], blog_dir=tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "766/758 put debit" in text and "**chosen**" in text
    assert "775/780 call credit spread" in text
    # The chosen row itself carries the mark, not just co-presence of the text.
    chosen_line = next(l for l in text.splitlines() if "766/758 put debit" in l)
    rejected_line = next(l for l in text.splitlines() if "775/780 call credit spread" in l)
    assert "**chosen**" in chosen_line
    assert "**chosen**" not in rejected_line


def test_write_entry_names_a_position_with_no_recorded_thesis_honestly(tmp_path, make_position):
    """Trade A on the real book has no thesis_claim at all (README's own
    stated limitation). The blog must say so, not print an empty section that
    reads as if nothing was missing."""
    pos = make_position(thesis="", thesis_claim="", thesis_horizon="",
                        thesis_band_low=None, thesis_band_high=None)
    trade = RecordedTrade(position=pos, matched=None, alternatives=[], confidence=0.5)

    path = blog.write_entry(trade, summary_text="opened it", decision_ref="d", batch="b",
                            model="m", served=["m"], blog_dir=tmp_path)

    assert "No thesis was recorded" in path.read_text(encoding="utf-8")


def test_write_outcome_appends_to_the_same_file_the_entry_wrote(tmp_path, make_position):
    """One file per trade, whole story - not a second file a reader has to
    go find."""
    pos = make_position()
    trade = RecordedTrade(position=pos, matched=None, alternatives=[], confidence=0.42)
    blog.write_entry(trade, summary_text="entry reasoning here", decision_ref="d",
                     batch="b", model="m", served=["m"], blog_dir=tmp_path)

    ok = blog.write_outcome(pos, close_reason="stop_loss",
                            why="position_mark -68% below -65%", pnl_fraction=-0.68,
                            blog_dir=tmp_path)

    assert ok is True
    text = blog.path_for(tmp_path, pos.position_id).read_text(encoding="utf-8")
    assert "entry reasoning here" in text, "the entry story was overwritten, not appended to"
    assert text.count("## Outcome") == 1, "two Outcome sections - the placeholder wasn't replaced"
    assert "stop_loss" in text and "-68.0%" in text


def test_write_outcome_with_no_entry_on_record_still_publishes_something(tmp_path, make_position):
    """A position that predates this mechanism (or whose entry write failed)
    still resolves - the outcome must not be silently dropped for want of a
    file to append to."""
    pos = make_position(position_id="pos_legacy_no_entry")

    ok = blog.write_outcome(pos, close_reason="external", why="in our records, absent at broker",
                            pnl_fraction=None, blog_dir=tmp_path)

    assert ok is True
    text = blog.path_for(tmp_path, pos.position_id).read_text(encoding="utf-8")
    assert "No entry story is on record" in text
    assert "external" in text


def test_write_entry_never_raises_on_a_bad_blog_dir_and_journals_the_failure(
    tmp_path, make_position
):
    """Publishing a story must never be able to interrupt the tick it is part
    of - a failure degrades, it does not propagate."""
    from trdrbot.journal import Journal

    pos = make_position()
    trade = RecordedTrade(position=pos, matched=None, alternatives=[], confidence=0.5)
    journal = Journal(tmp_path / "j.jsonl")
    unwritable = tmp_path / "not_a_directory.txt"
    unwritable.write_text("occupied")  # blog_dir/<file> under a FILE, not a dir

    path = blog.write_entry(trade, summary_text="x", decision_ref="d", batch="b",
                            model="m", served=["m"], blog_dir=unwritable, journal=journal)

    assert path is None
    rows = [r for r in journal.read() if r.get("kind") == "degraded"]
    assert rows and rows[0]["subsystem"] == "blog.write_entry"


def test_record_position_stashes_the_chosen_and_rejected_structures(tmp_path, make_position):
    """The seam this whole feature depends on: record_position must actually
    populate shared.recorded_trades with what it already computed, or blog.py
    has nothing real to format."""
    from trdrbot import local_tools
    from trdrbot.calibration import CalibrationStore
    from trdrbot.positions import PositionStore

    legs = [{"symbol": "SPY260903P00766000", "side": "buy", "qty": 13},
            {"symbol": "SPY260903P00758000", "side": "sell", "qty": 13}]
    # Matching is by LEG SHAPE (D-037's "derive, don't declare"), never by
    # name - so the "chosen" fixture's key is derived the same way
    # record_position derives it, from the real legs, not asserted by fiat.
    traded = [local_tools.optmath.Leg.from_position_leg(leg) for leg in legs]
    traded_key = local_tools._legs_key([(t.right, t.strike, t.side) for t in traded])

    store = PositionStore(tmp_path)
    shared = local_tools.SharedContext()
    shared.structures = [
        _structure("bear_put_spread", key=traded_key, qty=13, max_loss=-2171.0),
        _structure("call_credit_spread", qty=13, max_loss=-283.0),
    ]
    calib = CalibrationStore(tmp_path / "c.json")
    rec = local_tools.build_record_position(store, "dec_1", shared=shared, calibration=calib)

    rec.func(underlying="SPY", strategy="bear_put_spread", legs=legs,
            thesis="SPY rolls over", confidence=0.42, expiry="2026-09-03")

    assert len(shared.recorded_trades) == 1
    trade = shared.recorded_trades[0]
    assert trade.confidence == 0.42
    assert trade.position.underlying == "SPY"
    # Matching is by leg shape (D-037), not name - confirmed structurally: the
    # OTHER structure (call_credit_spread) ends up as the sole alternative.
    assert [st.name for st in trade.alternatives] == ["call_credit_spread"]
