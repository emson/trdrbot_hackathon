"""The wiki as a store: what it refuses, what it survives, and how it ages.

Concept ids are built from MODEL OUTPUT (`f"research/{ticker}"`), reads are on
the decide path, pages carry non-ASCII, and the freshness policy only ever ran
at sweep time - so a page could be too stale to keep and still be injected
into the prompt or handed to the muse as collision material.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from trdrbot import ids
from trdrbot.wiki import Concept, Wiki


def _dossier(wiki: Wiki, cid: str = "research/SPY", **fm) -> Concept:
    c = Concept(concept_id=cid, frontmatter={"type": "CompanyDossier", **fm},
                body="# What it is\nA broad market ETF.\n\n# Bull case\nx\n\n"
                     "# Bear case\nx\n\n# People\nx\n\n# Environment\nx\n")
    wiki.write_concept(c)
    return c


# ------------------------------------------------------- the path boundary


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "research/../../x", "", ".."])
def test_a_concept_id_that_escapes_the_root_is_refused(tmp_path, bad):
    """Concept ids come from model output - `f"research/{ticker}"` where the
    ticker came back from an LLM - so this is a boundary, and validating at a
    boundary is the fail-fast rule rather than defensive code. Without it a key
    containing `..` writes outside the wiki entirely."""
    with pytest.raises(ValueError, match="unsafe concept id"):
        Wiki(tmp_path).path_for(bad)


def test_ordinary_ids_still_work(tmp_path):
    w = Wiki(tmp_path)
    for good in ("lessons", "research/SPY", "context/regime", "technique/a-roll-is-a-new-trade"):
        assert w.path_for(good).suffix == ".md"


# ------------------------------------------------------------ reads degrade


def test_unterminated_frontmatter_degrades_instead_of_raising(tmp_path, capsys):
    """`text.split("---", 2)` unpacking three values raised ValueError, and
    `read()` is on the hot path - the decide prompt's regime block, every
    dossier lookup - with no guard. One truncated write and the tick died
    reading its own wiki."""
    w = Wiki(tmp_path)
    (tmp_path / "broken.md").write_text("---\ntype: Lesson\nbody with no closer\n",
                                        encoding="utf-8")

    c = w.read("broken")

    assert c is not None and "body with no closer" in c.body
    assert "unreadable frontmatter" in capsys.readouterr().out


def test_non_ascii_round_trips(tmp_path):
    """Live dossiers carry non-ASCII - a real one has a U+2011 non-breaking
    hyphen - and not one read or write in src/ named an encoding."""
    w = Wiki(tmp_path)
    text = "Non‑breaking hyphen, em rules — and € euros."
    w.write_concept(Concept(concept_id="lessons",
                            frontmatter={"type": "Lesson"}, body=f"# L\n{text}\n"))

    assert text in w.read("lessons").body


# ---------------------------------------------------------------- ageing


def test_a_page_with_no_stale_after_ages_off_its_generated_date(tmp_path):
    """I-20: the 24 dossiers written before lifecycle stamping landed have no
    `stale_after`, so `is_stale` was False forever - permanently unsweepable
    and permanently eligible as muse collision material. Fail-safe when it
    shipped, but the safety never expired."""
    old = ids.utc_now() - timedelta(hours=48)
    c = Concept(concept_id="research/OLD",
                frontmatter={"type": "CompanyDossier",
                             "generated": {"at": old.isoformat()}},
                body="# What it is\nx\n")

    assert c.is_stale() is True

    fresh = Concept(concept_id="research/NEW",
                    frontmatter={"type": "CompanyDossier",
                                 "generated": {"at": ids.utc_now().isoformat()}},
                    body="# What it is\nx\n")
    assert fresh.is_stale() is False


def test_a_timeless_type_never_ages(tmp_path):
    """A technique is timeless by policy; the fallback must not invent an
    expiry for a type that declares none."""
    c = Concept(concept_id="technique/x",
                frontmatter={"type": "Technique",
                             "generated": {"at": "2020-01-01T00:00:00+00:00"}},
                body="# R\nx\n")

    assert c.is_stale() is False


def test_a_legacy_dossier_now_reaches_the_sweep(tmp_path):
    """The consequence of the fallback: `sweep` can finally tombstone them."""
    w = Wiki(tmp_path)
    old = (ids.utc_now() - timedelta(hours=48)).isoformat()
    path = w.path_for("research/OLD")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: CompanyDossier\ngenerated:\n  at: '{old}'\n---\n\n"
                    f"# What it is\nx\n", encoding="utf-8")

    assert w.sweep()["deprecated"] == ["research/OLD"]


def test_a_protected_page_survives_however_old(tmp_path):
    """Tombstoning the only page explaining why we are in a trade would be the
    worst possible moment to do it."""
    w = Wiki(tmp_path)
    old = (ids.utc_now() - timedelta(hours=48)).isoformat()
    path = w.path_for("research/HELD")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: CompanyDossier\ngenerated:\n  at: '{old}'\n---\n\n"
                    f"# What it is\nx\n", encoding="utf-8")

    out = w.sweep(protected={"research/HELD"})

    assert out["deprecated"] == [] and out["protected"] == ["research/HELD"]


# ------------------------------------------------- staleness reaches readers


def test_the_muse_is_not_fed_tombstoned_pages(tmp_path):
    """A dossier housekeeping deprecated is one the sweep judged too stale to
    trust. Feeding it back as collision material undoes that judgement - and
    the raw rglob the sampler used could not see the status at all."""
    import random

    from trdrbot.muse import _sample_concepts

    w = Wiki(tmp_path)
    _dossier(w, "research/GOOD")
    dead = _dossier(w, "research/DEAD")
    dead.frontmatter["status"] = "deprecated"
    w.write_concept(dead, touch_generated=False)

    picked = dict(_sample_concepts(w, random.Random(0), 3))

    assert "research/GOOD" in picked
    assert "research/DEAD" not in picked



def test_an_overwritten_page_keeps_its_prior_body_in_a_history_the_muse_cannot_sample(tmp_path):
    """D-110. Nothing in the wiki is ever deleted - but the regime page is
    OVERWRITTEN every morning, and its previous assessment survived only in
    git, only when a human committed data/, which the loop never does. The one
    surface "how regimes change" could be learned from was destroying its own
    past daily.

    Three properties: the prior body is kept under a dated heading, newest
    first; an unchanged rewrite keeps nothing; and the history is NOT a concept
    - the muse's collision sampler must never draw yesterday's regime as an
    idea."""
    from trdrbot.wiki import Concept, Wiki

    w = Wiki(tmp_path)
    c = Concept(concept_id="context/regime", frontmatter={"type": "MarketContext"},
                body="# Assessment\nRisk-on.\n")
    w.write_concept(c, type_="MarketContext")

    assert w.archive_prior(w.read("context/regime"))
    hist = (tmp_path / "context" / "regime.history.md").read_text()
    assert hist.startswith("## ") and "Risk-on." in hist

    later = w.read("context/regime")
    later.body = "# Assessment\nRisk-off.\n"
    w.write_concept(later, type_="MarketContext")
    assert w.archive_prior(w.read("context/regime"))
    hist = (tmp_path / "context" / "regime.history.md").read_text()
    assert hist.index("Risk-off.") < hist.index("Risk-on."), "newest first, like log.md"

    assert not w.archive_prior(Concept(concept_id="context/empty", body="")), \
        "an empty page has nothing to keep"
    ids_ = {x.concept_id for x in w.all_concepts()}
    assert "context/regime" in ids_
    assert not any("history" in i for i in ids_), "a history is not a concept"
