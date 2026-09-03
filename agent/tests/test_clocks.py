"""Which clock answers which question.

Four clocks used to decide four different things - `date.today()` (local),
`ids.utc_now()`, an ET zone conversion, and a UTC weekday - and the mismatches
were real: horizons written in UTC were read in local time, cache staleness
compared a UTC stamp against a local date, and the Saturday research gate
fired from Friday 20:00 ET.

There are now two, and each is named for the question it answers.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from trdrbot import ids


def test_the_two_clocks_are_the_dates_they_claim_to_be():
    assert ids.today() == datetime.now(ZoneInfo("UTC")).date()
    assert ids.market_today() == datetime.now(ZoneInfo("America/New_York")).date()


def test_maturity_is_judged_against_the_clock_the_horizon_was_written_with():
    """`Entry.matured` defaulted to the LOCAL date while horizons are derived
    from `ids.utc_now()`. West of UTC the local date is a day behind for part
    of every day, so a horizon that had arrived read as still pending - and
    attribution simply never ran for it that day."""
    from trdrbot.ledger import Entry

    yesterday = Entry(id="e", kind="muse", created="", underlying="SPY", claim="c",
                      probability=0.5,
                      horizon=(ids.market_today() - timedelta(days=1)).isoformat(),
                      band_low=1.0, band_high=2.0)

    assert yesterday.matured() is True

    # TODAY is not matured until today's SESSION has closed (I-79). The old
    # assertion here was `horizon == today -> True`, which is true from 00:00
    # ET - so the first overnight housekeeping tick scored the day's forecasts
    # against the previous session's last print, sixteen hours early.
    due_today = Entry(id="e1", kind="muse", created="", underlying="SPY", claim="c",
                      probability=0.5, horizon=ids.market_today().isoformat(),
                      band_low=1.0, band_high=2.0)
    assert due_today.matured() is ids.session_closed_on(ids.market_today())

    tomorrow = Entry(id="e2", kind="muse", created="", underlying="SPY", claim="c",
                     probability=0.5,
                     horizon=(ids.market_today() + timedelta(days=1)).isoformat(),
                     band_low=1.0, band_high=2.0)
    assert tomorrow.matured() is False


def test_attribution_uses_the_same_clock_as_the_horizon(paths, make_position):
    """The other half of the same seam: `_horizon_passed` compared a UTC-written
    horizon against the local date."""
    from trdrbot import attribution
    from trdrbot.positions import PositionStore

    store = PositionStore(paths.wiki)
    # YESTERDAY's session, which has unambiguously closed. A horizon of TODAY is
    # due only after 16:00 ET now (I-79), and that boundary is pinned by the
    # ledger's own maturity test rather than smuggled in here.
    due = make_position(status="closed", last_pnl_pct=0.1,
                        thesis_horizon=(ids.market_today() - timedelta(days=1)).isoformat())
    store.save(due)

    assert [p.position_id for p in attribution.pending(store)] == [due.position_id]


def test_days_to_expiry_uses_the_market_calendar():
    """DTE is a claim about trading days. A UTC date is already tomorrow from
    20:00 ET, so a UTC-based DTE is off by one every evening - exactly when a
    short-dated option's gamma makes the number matter most."""
    from trdrbot import exit_rules

    expiry = ids.market_today() + timedelta(days=3)

    assert exit_rules._days_to(expiry.isoformat()) == 3


def test_an_unparseable_date_is_unobservable_rather_than_zero():
    """A rule reading an unobservable signal must HOLD. Returning 0 would make
    a `days_to_expiry <= 0` rule fire on a typo."""
    from trdrbot import exit_rules

    assert exit_rules._days_to("not-a-date") is None
    assert exit_rules._days_to(None) is None


# The "no module reaches for the local date" rule is enforced MECHANICALLY,
# by ruff's DTZ011, rather than by a test that reads source text. A banned
# construct is a lint rule; asserting on the text of the code would have been
# the same mistake the source-inspection tests make elsewhere in this suite.


def test_the_saturday_research_gate_keys_on_the_market_week():
    """Keyed on the UTC weekday, the gate suppressed research from Friday
    20:00 ET - the run that reads a fresh Friday close and is the most useful
    one of the week."""
    friday_evening_et = datetime(2026, 8, 28, 20, 30, tzinfo=ZoneInfo("America/New_York"))

    assert friday_evening_et.astimezone(ZoneInfo("UTC")).weekday() == 5, \
        "this instant really is Saturday in UTC"
    assert friday_evening_et.date().weekday() == 4, "and Friday in the market's week"
    assert friday_evening_et.date() == date(2026, 8, 28)
