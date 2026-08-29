"""What the three thesis sources look at before they think.

Research, discovery and the muse each gathered the same two inputs - recent
news and prediction-market odds - from three near-identical copies differing
only in a limit and a symbol filter. The copies had already drifted where it
mattered most: a failed odds call rendered as `(none)` in two of them, which
tells the model there are no prediction markets when in fact the API failed.
Those are different claims about the world, and the model cannot tell them
apart from an empty block.

One convention, stated once: **a failure renders itself.** An empty block
means the world is quiet; "(unavailable: X)" means we could not look.
"""

from __future__ import annotations

from typing import Any

from . import mcp_client, news_extract
from .config import Config

#: Odds results per query. Two is enough to show the crowd's view without one
#: broad query crowding the block.
ODDS_PER_QUERY = 2


async def gather(
    tools: dict[str, Any], config: Config, *,
    symbols: list[str] | None = None, news_limit: int = 30, journal: Any = None,
) -> tuple[str, str]:
    """(news_block, odds_block), ready for a prompt.

    `symbols` scopes the news to a watchlist (research does; discovery and the
    muse want the broad tape, which is the point of them).
    """
    return (
        await _news_block(tools, config, symbols=symbols, limit=news_limit,
                          journal=journal),
        await _odds_block(config),
    )


async def _news_block(tools: dict[str, Any], config: Config, *,
                      symbols: list[str] | None, limit: int,
                      journal: Any = None) -> str:
    kwargs: dict[str, Any] = {"limit": limit, "exclude_contentless": True, "sort": "desc"}
    if symbols:
        kwargs["symbols"] = ",".join(symbols)
    try:
        r = await mcp_client.call(tools, "get_news", **kwargs)
        items = (r.get("news") or []) if isinstance(r, dict) else []
        return news_extract.render_block(
            await news_extract.enrich(items, config, journal))
    except Exception as exc:  # noqa: BLE001 - advisory input, never fatal (INV-8)
        # A thesis source that reasons with NO news reads identically to one
        # reasoning with news that happened to be quiet, so the substitution
        # is recorded rather than only substituted.
        from .health import degraded
        degraded(journal, "evidence", f"news unavailable ({type(exc).__name__})",
                 error=repr(exc)[:200])
        return f"(news unavailable: {type(exc).__name__})"


async def _odds_block(config: Config) -> str:
    """Prediction-market odds, one line per market.

    Isolated PER QUERY: the copies this replaces wrapped the whole loop in one
    try, so the first query to fail discarded every later query's results too -
    and then rendered the lot as if the markets had simply been quiet.
    """
    from . import polymarket

    lines: list[str] = []
    for q in config.polymarket_queries:
        try:
            for m in await polymarket.search(q, limit=ODDS_PER_QUERY):
                lines.append(f"- {m['probability']:.0%} {m['question']}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"(odds unavailable for {q!r}: {type(exc).__name__})")
    return "\n".join(lines) or "(none)"
