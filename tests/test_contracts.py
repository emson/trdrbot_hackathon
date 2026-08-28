"""Contract tests: what we BELIEVE about the outside world, checked against it.

Run explicitly - they use real network and real keys:

    uv run pytest -m contract

Why this file exists, from evidence rather than doctrine. Every serious bug in
this project was found by *measuring* or *running*, never by a unit test
catching a logic error - because the bugs were not logic errors. They were
wrong beliefs about a seam:

  - `get_stock_snapshot` takes `symbols`, not `symbol_or_symbols`; the free
    tier 403s on the default SIP feed          -> attribution silently dead for days
  - `get_stock_bars` ascending + `limit` truncates from the START of the range
                                               -> six-week-stale data, logs healthy
  - `get_stock_latest_trade` nests under `trades`, not the symbol
                                               -> every underlying_stop inert in production
  - `outcome()` on an unconsolidated block returns updated=0, silently
                                               -> memory credit never assigned
  - `.with_config(callbacks=)` records ZERO of a LangGraph agent's LLM calls
                                               -> the priciest path unmetered
  - an exhausted Anthropic key raises `AnthropicInvalidRequestError` (a 400,
    NOT a rate-limit class)                    -> a fallback keyed on the wrong
                                                  exception would never fire

None of those are discoverable offline, and all of them are one API change
away from returning. Each test below is one such belief, written so its
failure names the belief that broke rather than just "assertion failed".

The rule for this file: assert the SHAPE and the DISCRIMINATING property, never
live values. "SPY costs 767.61" is not a contract; "the price is a positive
float found under `trades.<symbol>.p`" is.
"""

from __future__ import annotations

import pytest

# Sockets are disabled for the default suite (a unit test reaching the network
# is both slow and a lie about what it proves). Contract tests are the one place
# real network is the POINT, so they re-enable it explicitly - opting in per
# file, never by weakening the global default.
pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.enable_socket]


@pytest.fixture(scope="module")
def cfg():
    from trdrbot import config as config_mod
    return config_mod.load(quiet=True)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _tools(cfg):
    from trdrbot import mcp_client
    return {t.name: t for t in await mcp_client.get_tools(cfg)}


# ---------------------------------------------------------------- Alpaca

@pytest.mark.asyncio
async def test_latest_trade_nests_the_price_under_trades(cfg):
    """The shape that made every underlying_stop inert: the payload is
    {"trades": {"SPY": {"p": ...}}}, NOT {"SPY": {...}}."""
    from trdrbot import mcp_client
    tools = await _tools(cfg)
    r = await mcp_client.call(tools, "get_stock_latest_trade", symbols="SPY", feed="iex")

    assert isinstance(r, dict), f"expected a dict, got {type(r).__name__}"
    assert "trades" in r, f"price is no longer nested under 'trades' - keys: {list(r)}"
    node = r["trades"].get("SPY")
    assert node is not None, "symbol key missing inside 'trades'"
    assert isinstance(node.get("p"), (int, float)) and node["p"] > 0, \
        f"no positive price under trades.SPY.p - got {node!r}"


@pytest.mark.asyncio
async def test_snapshot_uses_symbols_and_the_iex_feed_is_permitted(cfg):
    """`symbol_or_symbols` 400s and the default SIP feed 403s on our tier."""
    from trdrbot import mcp_client
    tools = await _tools(cfg)
    params = list(tools["get_stock_snapshot"].args_schema.get("properties", {}))
    assert "symbols" in params, f"parameter renamed - now: {params}"

    ok = await mcp_client.call(tools, "get_stock_snapshot", symbols="SPY", feed="iex")
    assert isinstance(ok, dict) and ok, "iex feed no longer returns a snapshot"


@pytest.mark.asyncio
async def test_daily_bars_descending_are_anchored_to_today(cfg):
    """Ascending + limit truncates from the START of the range, which served
    six-week-stale data while every log line read healthy. `sort=desc` anchors
    the window to now by construction."""
    from datetime import date, timedelta
    from trdrbot import market_stats
    tools = await _tools(cfg)

    closes = await market_stats.fetch_daily_closes(tools, "SPY", days=60)
    assert len(closes) >= 40, f"only {len(closes)} bars - history request shape changed"
    assert all(c > 0 for c in closes), "non-positive close in the series"

    # The discriminating check: the LAST bar must be recent. A silent revert to
    # ascending+limit shows up here and nowhere else.
    raw = await mcp_client_call_bars(tools)
    newest = max(raw)
    assert (date.today() - newest) < timedelta(days=6), \
        f"newest bar is {newest} - bars are stale, sort/limit semantics changed"


async def mcp_client_call_bars(tools):
    """Bar dates only, so the staleness check above reads clearly."""
    from datetime import date, timedelta
    from trdrbot import mcp_client
    start = (date.today() - timedelta(days=40)).isoformat()
    r = await mcp_client.call(tools, "get_stock_bars", symbols="SPY", timeframe="1Day",
                              start=start, feed="iex", limit=30, sort="desc")
    bars = r.get("bars") if isinstance(r, dict) else r
    if isinstance(bars, dict):
        bars = bars.get("SPY") or []
    return [date.fromisoformat(str(b["t"])[:10]) for b in bars if b.get("t")]


@pytest.mark.asyncio
async def test_option_chain_is_large_enough_to_matter_for_context_cost(cfg):
    """Not a correctness contract - a COST one. One chain measured 15,343
    tokens and is re-sent every agent turn, which is 84% of decide spend. If
    this ever shrinks by an order of magnitude the context budget changed;
    if it grows, cost did (D-063)."""
    import json
    from trdrbot import mcp_client
    tools = await _tools(cfg)
    r = await mcp_client.call(tools, "get_option_chain", underlying_symbol="SPY")
    size = len(r if isinstance(r, str) else json.dumps(r))
    assert size > 1_000, "chain suspiciously small - filtering changed upstream?"
    print(f"\n  option chain payload: {size:,} chars ~= {size // 4:,} tokens")


# ---------------------------------------------------------------- elfmem

@pytest.mark.asyncio
async def test_outcome_on_an_unconsolidated_block_applies_nothing(tmp_path, cfg):
    """The silent zero that meant memory credit was never assigned. If elfmem
    ever fixes this, our consolidate-and-retry in resolve() becomes redundant -
    this test failing is GOOD NEWS and a prompt to simplify."""
    from trdrbot.elfmem_adapter import ElfmemAdapter
    mem = await ElfmemAdapter.build(tmp_path / "e.db")
    try:
        await mem.begin()
        r = await mem.mem.remember("contract probe", tags=["contract"],
                                   category="knowledge", source="t", cue="when probing")
        before = await mem.mem.outcome([r.block_id], 0.9, weight=1.0, source="t")
        await mem.mem.consolidate()
        after = await mem.mem.outcome([r.block_id], 0.9, weight=1.0, source="t")

        assert before.blocks_updated == 0, \
            "elfmem now applies outcomes to inbox blocks - resolve()'s retry can be simplified"
        assert after.blocks_updated == 1, "outcome no longer applies post-consolidation"
        await mem.end()
    finally:
        await mem.close()


@pytest.mark.asyncio
async def test_self_frame_still_says_you_are_and_renders_the_constitution(tmp_path, cfg):
    """Our rename patch keys on 'You are <name>'. If upstream rewords the
    preamble the patch no-ops safely - but we want to KNOW."""
    from trdrbot.elfmem_adapter import ElfmemAdapter
    mem = await ElfmemAdapter.build(cfg.paths.state / "elfmem.db")
    try:
        await mem.begin()
        fr = await mem.self_frame()
        assert fr.text, "SELF frame renders nothing"
        assert "You are Theo" in fr.text, \
            f"rename patch no longer applies - heading is {fr.text.splitlines()[0]!r}"
        await mem.end()
    finally:
        await mem.close()


# ---------------------------------------------------------------- providers

@pytest.mark.asyncio
async def test_at_least_one_configured_model_answers(cfg):
    """The chain as a whole must work. Individual providers may be down or
    out of credit - that is what the chain is for - but zero reachable models
    means the system cannot make a decision at all."""
    from trdrbot.llm import build_model
    model = build_model(cfg, role="decide")
    r = await model.ainvoke("Reply with the single word: ok")
    assert "ok" in str(r.content).lower()
    served = (r.response_metadata or {}).get("model_name")
    assert served, "no model_name in response_metadata - usage attribution would break"
    print(f"\n  decide chain served by: {served}")


@pytest.mark.asyncio
async def test_usage_metadata_carries_token_counts(cfg):
    """Cost accounting reads usage_metadata. No counts, no cost visibility."""
    from trdrbot.llm import build_model
    r = await build_model(cfg, role="doctor").ainvoke("Reply with the single word: ok")
    usage = getattr(r, "usage_metadata", None)
    assert usage, "usage_metadata absent - all cost reporting would silently read zero"
    assert usage.get("input_tokens", 0) > 0 and usage.get("output_tokens", 0) > 0


@pytest.mark.asyncio
async def test_langgraph_agent_records_usage_only_via_constructor_callbacks(cfg, tmp_path):
    """`.with_config(callbacks=)` recorded ZERO of an agent's calls while
    constructor callbacks recorded all of them. If LangChain ever fixes this,
    the constructor route still works - but the asymmetry is worth watching,
    because it silently under-metered our most expensive path."""
    from langchain.chat_models import init_chat_model
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent
    from trdrbot.usage import UsageCallback, UsageLedger

    @tool
    def ping(x: str) -> str:
        """Return pong."""
        return "pong"

    spec = cfg.model_chain("doctor")[0]
    led = UsageLedger(tmp_path / "u.jsonl", {})
    m = init_chat_model(spec, max_tokens=200, callbacks=[UsageCallback(led, "decide")])
    agent = create_react_agent(m, [ping], prompt="Call ping once, then reply done.")
    await agent.ainvoke({"messages": [("user", "call ping with x=hi")]})

    assert led.calls(), "constructor callbacks no longer capture agent LLM calls"
