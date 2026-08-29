"""The one gate that admits an item onto the inbox seam.

Three sources wrote this seam under three different rule sets. Research - the
source whose output the agent reads every morning - had none of the four gates
the other two earned through shipped bugs, so the D-035 defect those gates
exist for was still open on that path. The muse hand-built a payload that
would have failed the shared field check it never called.
"""

from __future__ import annotations

import pytest

from trdrbot.opportunity import Admission, Opportunity, admit


def _o(**overrides) -> Opportunity:
    base = {"underlying": "SPY", "claim": "SPY rolls over",
            "horizon": "2026-09-02", "band_high": 770.0}
    base.update(overrides)
    return Opportunity(**base)


# --------------------------------------------------------- the field checks


@pytest.mark.parametrize(
    ("overrides", "defect"),
    [
        ({"underlying": ""}, "missing_underlying"),
        ({"claim": ""}, "missing_claim"),
        ({"horizon": ""}, "missing_horizon"),
        ({"band_low": None, "band_high": None}, "missing_band"),
        ({"horizon": "2 Sept"}, "bad_horizon_format"),
    ],
)
def test_a_defect_names_the_specific_field(overrides, defect):
    """Returns the SPECIFIC missing field rather than a bare bool (D-071). A
    fully-reasoned thesis dropped for one absent `horizon` was indistinguishable
    in the log from genuine garbage - a repeating defect is a fixable prompt
    problem, an opaque one is just attrition."""
    assert admit(_o(**overrides)).defect == defect


def test_one_band_is_enough_to_be_scoreable():
    assert admit(_o(band_low=None, band_high=770.0)).ok
    assert admit(_o(band_low=760.0, band_high=None)).ok


# --------------------------------------------------------- the three gates


def test_a_band_that_is_a_percentage_move_is_refused():
    """THE D-035 defect, still open on the research path until now: the model
    emitted percentage moves ([-6.0, 8.0] on an $87 stock) where prices were
    asked for, which makes `holds_at` always-False and scores every thesis as
    failed - silently corrupting the learning loop."""
    assert admit(_o(band_high=8.0), spot=766.0).defect == "band_not_a_price"
    assert admit(_o(band_high=770.0), spot=766.0).ok


def test_a_horizon_past_the_last_useful_day_is_refused():
    assert admit(_o(horizon="2026-09-30"), latest_useful="2026-09-02").defect == \
        "horizon_too_late"


def test_an_untradeable_underlying_is_refused():
    assert admit(_o(), options_tradeable=False).defect == "failed_options_gate"
    assert admit(_o(), options_tradeable=True).ok


# ------------------------------------------- absence is reported, not passed


def test_a_gate_with_no_input_is_reported_unchecked_rather_than_skipped():
    """The half that matters as much as the defect. Discovery's band check
    VANISHED whenever the close fetch had failed - exactly when the data is
    worst - and research had no options gate at all with nothing recording its
    absence. An admitted item now says what its admission rested on (D-038)."""
    verdict = admit(_o())

    assert verdict.ok
    assert set(verdict.unchecked) == {"horizon_window", "band_plausibility", "options_gate"}


def test_a_fully_evidenced_admission_reports_nothing_unchecked():
    """The distinction has to cut both ways or `unchecked` becomes noise."""
    verdict = admit(_o(), spot=766.0, latest_useful="2026-09-02", options_tradeable=True)

    assert verdict == Admission(defect=None, unchecked=())


def test_a_zero_spot_is_no_anchor_rather_than_a_failing_one():
    """`_plausible_band`'s original rule: with no anchor, do not invent a
    judgement. It just says so now instead of passing quietly."""
    assert "band_plausibility" in admit(_o(band_high=8.0), spot=0.0).unchecked


# ---------------------------------------------------------- the payload seam


def test_the_payload_round_trips():
    o = _o(band_low=760.0, direction="bearish", drift_pct=-1.5,
           why="because", suggested_structures=("bear_put_spread",))

    assert Opportunity.from_payload(o.to_payload()) == o


def test_the_payload_keys_are_the_wire_format_the_sources_already_wrote():
    """These keys are rendered into the decide prompt and three of them are
    hashed by `ids.opportunity_id`, so renaming one would silently change
    every opportunity's identity and break Phase 1's dedup."""
    assert set(_o().to_payload()) == {
        "underlying", "claim", "direction", "drift_pct",
        "band_low", "band_high", "horizon", "why", "suggested_structures",
    }


def test_a_payload_that_is_not_an_object_is_refused_rather_than_coerced():
    for junk in (None, "a string", 42, ["a", "list"]):
        assert Opportunity.from_payload(junk) is None


def test_types_are_coerced_but_structure_is_not_invented():
    """Permissive about TYPES, strict about STRUCTURE: a model writing a
    number where a string belongs is normal and coercible; a model omitting
    the claim entirely is a defect the gate must catch, not paper over."""
    o = Opportunity.from_payload({"underlying": "spy", "claim": 123,
                                  "horizon": "2026-09-02", "band_high": "770.5"})

    assert o is not None
    assert o.underlying == "SPY" and o.claim == "123" and o.band_high == 770.5

    bad = Opportunity.from_payload({"underlying": "SPY", "horizon": "2026-09-02",
                                    "band_high": 770.0})
    assert bad is not None and admit(bad).defect == "missing_claim"


def test_an_unparseable_band_reads_as_absent_not_as_zero():
    """Absence-as-zero: a band of 0.0 would make `holds_at` a different claim
    entirely, and 0.0 is inside no sane spot window so it would be refused as
    "not a price" - a confusing defect for what is really a missing value."""
    o = Opportunity.from_payload({"underlying": "SPY", "claim": "c",
                                  "horizon": "2026-09-02", "band_high": "not a number"})

    assert o is not None and o.band_high is None
    assert admit(o).defect == "missing_band"


# ------------------------------------------- the sources now share one door


async def test_research_now_rejects_the_percentage_band_it_used_to_admit(
    paths, monkeypatch, capsys
):
    """The seam test for the whole work unit. Research emitted straight from
    `opportunity_defect` - no band check, no horizon window, no options gate -
    so a percentage-move band reached the decide prompt and would have scored
    its thesis as failed at attribution. Run through the real emission loop.
    """
    from types import SimpleNamespace

    from conftest import tools_for

    from trdrbot import research
    from trdrbot.inbox import Inbox
    from trdrbot.journal import Journal
    from trdrbot.wiki import Wiki

    # The model returns one plausible-priced opportunity and one whose band is
    # a percentage move - the exact D-035 shape, on an underlying whose real
    # close the deterministic layer computed itself.
    reply = (
        "REGIME_MARKDOWN:\n# Assessment\nquiet\n# Drivers\nx\n# Calendar\nx\n# Watch\nx\n"
        "DOSSIERS_JSON:\n{}\n"
        'OPPORTUNITIES_JSON:\n[{"underlying":"SPY","claim":"holds","horizon":"2026-09-02",'
        '"band_low":760.0,"band_high":775.0,"drift_pct":0.5,"why":"w"},'
        '{"underlying":"SPY","claim":"pct band","horizon":"2026-09-02",'
        '"band_low":-6.0,"band_high":8.0,"drift_pct":0.5,"why":"w"}]'
    )
    monkeypatch.setattr(research, "ask", lambda *a, **k: _async(reply))
    monkeypatch.setattr(research.market_stats, "fetch_daily_series",
                        lambda *a, **k: _async((["2026-08-28"] * 120,
                                                [766.0 + i % 3 for i in range(120)])))
    monkeypatch.setattr(research.evidence, "gather",
                        lambda *a, **k: _async(("(none)", "(none)")))

    cfg = SimpleNamespace(paths=paths, deadline="2026-09-04",
                          research_universe=["SPY"], watchlist=["SPY"],
                          polymarket_queries=[])
    journal = Journal(paths.journal)

    out = await research.run(tools_for(), cfg, Inbox(paths), Wiki(paths.wiki),
                             journal, verbose=False, force=True)

    assert out["opportunities"] == 1, "the percentage-move band was admitted"
    rejected = [r for r in journal.read() if r.get("kind") == "research_rejected"]
    assert [r["reason"] for r in rejected] == ["unscoreable:band_not_a_price"]
    assert rejected[0]["source"] == "research", "rejections must name their producer"


def _async(value):
    async def _f(*a, **k):
        return value
    return _f()
