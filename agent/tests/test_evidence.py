"""What the three thesis sources look at, and how a failure to look reads.

The three copies this replaces had already drifted where it mattered: a failed
odds call rendered as "(none)" in two of them, telling the model there are no
prediction markets when in fact the API failed. Those are different claims
about the world and an empty block cannot distinguish them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from conftest import tools_for

from trdrbot import evidence


def _cfg(paths, queries: list[str] | None = None) -> Any:
    return SimpleNamespace(paths=paths, polymarket_queries=queries or [])


async def test_a_failed_news_call_says_so_rather_than_reading_as_quiet(paths, monkeypatch):
    def boom(**_: Any) -> Any:
        raise RuntimeError("upstream 503")

    news, _ = await evidence.gather(tools_for(get_news=boom), _cfg(paths))

    assert "news unavailable" in news
    assert "RuntimeError" in news


async def test_a_failed_odds_query_says_so_rather_than_reading_as_quiet(paths, monkeypatch):
    """research rendered this truthfully; discovery and the muse swallowed it
    with a bare `pass` and showed "(none)"."""
    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("polymarket down")

    monkeypatch.setattr("trdrbot.polymarket.search", boom)

    _, odds = await evidence.gather(tools_for(get_news=lambda **k: {"news": []}),
                                    _cfg(paths, ["fed cuts"]))

    assert "odds unavailable" in odds and "fed cuts" in odds


async def test_one_failing_odds_query_does_not_lose_the_others(paths, monkeypatch):
    """The copies wrapped the whole loop in ONE try, so the first query to
    fail discarded every later query's results too - and then rendered the lot
    as if the markets had simply been quiet."""
    async def flaky(query: str, limit: int = 2) -> Any:
        if query == "bad":
            raise RuntimeError("nope")
        return [{"probability": 0.42, "question": f"will {query}?"}]

    monkeypatch.setattr("trdrbot.polymarket.search", flaky)

    _, odds = await evidence.gather(tools_for(get_news=lambda **k: {"news": []}),
                                    _cfg(paths, ["bad", "good"]))

    assert "odds unavailable for 'bad'" in odds
    assert "42% will good?" in odds, "the healthy query's result was discarded"


async def test_no_queries_configured_is_quiet_not_broken(paths):
    _, odds = await evidence.gather(tools_for(get_news=lambda **k: {"news": []}),
                                    _cfg(paths))

    assert odds == "(none)"


async def test_symbol_scoping_reaches_the_broker_call(paths, monkeypatch):
    """research scopes news to its universe; discovery and the muse want the
    broad tape, which is the point of them."""
    monkeypatch.setattr("trdrbot.news_extract.enrich",
                        lambda items, config: _resolved([]))
    tools = tools_for(get_news=lambda **k: {"news": []})

    await evidence.gather(tools, _cfg(paths), symbols=["SPY", "QQQ"], news_limit=25)
    scoped = tools["get_news"].calls[-1]
    assert scoped["symbols"] == "SPY,QQQ" and scoped["limit"] == 25

    await evidence.gather(tools, _cfg(paths), news_limit=40)
    broad = tools["get_news"].calls[-1]
    assert "symbols" not in broad and broad["limit"] == 40


def _resolved(value: Any) -> Any:
    async def _f() -> Any:
        return value
    return _f()
