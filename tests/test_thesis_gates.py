"""The gates a candidate thesis must pass, fed the inputs they actually get.

Both gates here read model output or a third-party envelope, so malformed is
normal. The existing suite fed them clean candidates and well-shaped chains.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from conftest import tools_for

from trdrbot import muse, opportunity


def _soon(days: int = 3) -> str:
    """A horizon inside the muse's own 1-10 day window, derived from today -
    a literal date would drift out of the window as the calendar moves and
    the test would start failing for a reason that is not the code's."""
    return (date.today() + timedelta(days=days)).isoformat()


# --------------------------------------------------------- the options gate


async def test_an_error_payload_is_not_a_tradeable_chain():
    """The gate counted the SUBSTRING "symbol" in `str(response)`, so an error
    payload mentioning the word scored 1 and returned tradeable - the gate
    answering yes on the evidence that it had failed."""
    tools = tools_for(get_option_chain=lambda **k: {"error": "no chain for symbol XYZ"})

    gate = await opportunity.options_gate(tools, "XYZ", "2026-09-04")

    assert gate["tradeable"] is False


async def test_a_real_chain_counts_its_contracts():
    tools = tools_for(get_option_chain=lambda **k: {"snapshots": {
        "SPY260904C00770000": {}, "SPY260904P00770000": {}, "not-an-occ": {},
    }})

    gate = await opportunity.options_gate(tools, "SPY", "2026-09-04")

    assert gate["tradeable"] is True
    assert gate["contracts_seen"] == 2, "counted a key that is not a contract"
    assert gate["via"] == "snapshots"


async def test_an_unrecognised_shape_degrades_but_says_which_path_answered():
    """A schema change must not block every candidate - but a silent fallback
    is how the substring count survived unnoticed, so the path is reported."""
    tools = tools_for(get_option_chain=lambda **k: "SPY260904C00770000 symbol")

    gate = await opportunity.options_gate(tools, "SPY", "2026-09-04")

    assert gate["via"] == "substring_fallback"


async def test_a_raising_chain_call_is_not_tradeable():
    def boom(**_: Any) -> Any:
        raise RuntimeError("mcp down")

    gate = await opportunity.options_gate(tools_for(get_option_chain=boom),
                                         "SPY", "2026-09-04")

    assert gate["tradeable"] is False and "error" in gate


# ------------------------------------------------- one candidate, one cost


def test_a_null_probability_defaults_rather_than_raising():
    """`float(cand.get("probability", 0.5))` raised TypeError on an explicit
    null - the KEY is present, so the default never fired."""
    assert muse._prob(None) == 0.5
    assert muse._prob("not a number") == 0.5
    assert muse._prob(0.27) == 0.27
    assert muse._prob("0.4") == 0.4


async def test_one_malformed_candidate_costs_one_candidate_not_the_run(paths, monkeypatch):
    """`_evaluate` had no per-candidate guard, so a single bad field aborted
    the whole run AND both arms of an open trial - a model hiccup could void a
    paired trial that had nothing wrong with either variant."""
    from types import SimpleNamespace

    from trdrbot.ledger import Ledger

    closes = [100.0 + (i % 7) * 0.5 for i in range(120)]
    monkeypatch.setattr(muse.market_stats, "load_closes", lambda *a, **k: closes)
    monkeypatch.setattr(muse, "_plausible_band", lambda *a, **k: True)

    async def gate(*a: Any, **k: Any) -> dict[str, Any]:
        return {"tradeable": True}

    monkeypatch.setattr(muse, "options_gate", gate)

    # The poison: `chain` is a string where the gate cascade expects a list,
    # so `" -> ".join(...)` raises partway through - the shape of a real
    # malformed reply rather than an invented exception.
    good = {"underlying": "SPY", "claim": "c", "chain": ["a"], "probability": 0.4,
            "band_low_pct": -3.0, "band_high_pct": 3.0, "horizon": _soon()}
    bad = dict(good, underlying="QQQ", chain=[object()])

    cfg = SimpleNamespace(paths=paths, deadline=_soon(20))
    evaluated = await muse._evaluate(
        [bad, good], {}, cfg, Ledger(paths.state / "ledger.jsonl"),
        latest=_soon(10), variant="v0", cache={},
    )

    by_name = {v["underlying"]: v for v in evaluated}
    assert by_name["SPY"]["fate"] == "candidate", "the good candidate was lost"
    assert "QQQ" in by_name, "the bad candidate vanished instead of being recorded"


async def test_a_candidate_that_raises_is_recorded_as_a_rejection(paths, monkeypatch):
    """A bad candidate must leave a verdict, not a hole: the muse's own gauge
    divides survivors by candidates, so a silently dropped one skews the
    Coach's reward."""
    from types import SimpleNamespace

    from trdrbot.ledger import Ledger

    monkeypatch.setattr(muse.market_stats, "load_closes",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    cfg = SimpleNamespace(paths=paths, deadline=_soon(20))
    evaluated = await muse._evaluate(
        [{"underlying": "SPY", "claim": "c", "chain": ["a"], "probability": 0.4,
          "band_low_pct": -3.0, "band_high_pct": 3.0, "horizon": _soon()}],
        {}, cfg, Ledger(paths.state / "ledger.jsonl"),
        latest=_soon(10), variant="v0", cache={},
    )

    assert len(evaluated) == 1
    assert evaluated[0]["fate"].startswith("error:")


async def test_a_malformed_reply_element_is_counted_not_silently_dropped(paths):
    """I-49: this file's own invariant is that EVERY candidate is registered,
    because an LLM's discards are exactly the selection bias the
    multiple-testing correction exists to catch - and a bare `continue` on a
    malformed element made it the one candidate that escaped the count.

    The consequence that matters is on the Coach: a prompt variant producing
    garbage must LOSE its A/B trials on that garbage rather than be invisible
    to its own reward. It still does not reach `ledger.register` - a row with
    no underlying and no band is exactly what register refuses.
    """
    from types import SimpleNamespace

    from trdrbot import coach
    from trdrbot.ledger import Ledger

    good = {"underlying": "SPY", "claim": "c", "chain": ["a"], "probability": 0.4,
            "band_low_pct": -3.0, "band_high_pct": 3.0, "horizon": _soon()}
    cfg = SimpleNamespace(paths=paths, deadline=_soon(20))

    evaluated = await muse._evaluate(
        ["not a dict at all", {"claim": "no underlying anywhere"}, good],
        {}, cfg, Ledger(paths.state / "ledger.jsonl"),
        latest=_soon(10), variant="v0", cache={},
    )

    assert len(evaluated) == 3, "malformed elements vanished from the accounting"
    fates = [v["fate"] for v in evaluated]
    assert fates.count("malformed reply element") == 2
    # And the Coach scores them as failures, which is the whole point.
    assert sum(1 for f in fates if coach.survived(f)) <= 1
    # Every verdict carries the keys the journal row and the verbose print read
    # directly - a KeyError here would take down the whole muse run.
    for v in evaluated:
        assert "underlying" in v and "stated" in v and "fate" in v
