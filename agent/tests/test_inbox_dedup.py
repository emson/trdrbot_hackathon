"""The inbox seam: what makes two items the same item.

Item ids were uuid4-unique by construction, deliberately - a news sensor
emitting a batch once produced N identical filenames and silently overwrote
its own output. But opportunities are generated repeatedly from overlapping
evidence, so uniqueness-by-construction meant an identical claim could never
dedup. Measured on the live pending directory: 22 opportunities, XLE six times
and MU five, three byte-identical band pairs from three separate muse runs -
all entering ONE decide batch, where they read as five independent signals
rather than one claim made five times.
"""

from __future__ import annotations

from trdrbot.inbox import Inbox


def _claim(**overrides):
    payload = {"underlying": "XLE", "horizon": "2026-08-31",
               "band_low": 62.89, "band_high": 64.64, "claim": "energy rolls over"}
    payload.update(overrides)
    return payload


def test_the_same_claim_twice_in_one_day_is_one_pending_item(paths):
    inbox = Inbox(paths)

    first = inbox.write("opportunity", _claim(), source="muse")
    second = inbox.write("opportunity", _claim(), source="muse")

    assert first.id == second.id
    assert len(list(paths.inbox_pending.glob("*.json"))) == 1
    assert len(inbox.pending()) == 1


def test_a_different_band_is_a_different_claim(paths):
    inbox = Inbox(paths)

    inbox.write("opportunity", _claim(), source="muse")
    inbox.write("opportunity", _claim(band_high=70.0), source="muse")

    assert len(inbox.pending()) == 2


def test_a_different_horizon_is_a_different_claim(paths):
    inbox = Inbox(paths)

    inbox.write("opportunity", _claim(), source="muse")
    inbox.write("opportunity", _claim(horizon="2026-09-02"), source="muse")

    assert len(inbox.pending()) == 2


def test_two_sources_reaching_the_same_claim_are_kept_apart(paths):
    """Corroboration is signal, not noise: discovery and the muse landing on
    the same trade independently is worth MORE than either alone, and the
    decide cycle can only see that if both items survive."""
    inbox = Inbox(paths)

    inbox.write("opportunity", _claim(), source="muse")
    inbox.write("opportunity", _claim(), source="discovery")

    assert len(inbox.pending()) == 2


def test_the_first_write_wins_and_keeps_its_timestamp(paths):
    """The dedup returns the EXISTING item rather than overwriting it, so
    `expire_stale` still ages the claim from when it was first made - a claim
    re-emitted every run must not refresh its own staleness clock forever."""
    inbox = Inbox(paths)

    first = inbox.write("opportunity", _claim(), source="muse")
    again = inbox.write("opportunity", _claim(claim="reworded but same bands"),
                        source="muse")

    assert again.ts == first.ts
    assert again.payload["claim"] == "energy rolls over", "the original was overwritten"


def test_news_items_never_dedup(paths):
    """The uuid4 in item_id was bought by a real incident - a sensor reported
    "20 new" and left 2 files on disk. Two news items with identical payloads
    are two observations and must both survive."""
    inbox = Inbox(paths)

    a = inbox.write("news", {"headline": "same wire story"}, source="alpaca_news")
    b = inbox.write("news", {"headline": "same wire story"}, source="alpaca_news")

    assert a.id != b.id
    assert len(inbox.pending()) == 2


def test_a_claim_with_no_bands_still_gets_a_stable_id(paths):
    """A missing band must not make the id unstable, or the item would never
    dedup AND would collide with any other bandless claim on the same name."""
    inbox = Inbox(paths)

    first = inbox.write("opportunity", _claim(band_low=None, band_high=None),
                        source="research")
    second = inbox.write("opportunity", _claim(band_low=None, band_high=None),
                         source="research")

    assert first.id == second.id
    assert len(inbox.pending()) == 1
