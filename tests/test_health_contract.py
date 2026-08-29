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
