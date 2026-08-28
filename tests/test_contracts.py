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


@pytest.mark.asyncio
async def test_outcome_rejects_a_non_positive_weight(cfg, tmp_path):
    """Phase-2 credit weighting depends on this: elfmem raises on weight <= 0,
    which is why `credit_weight` has a floor. If elfmem ever starts ACCEPTING
    0, the floor becomes a choice rather than a hard requirement - still
    correct, but the reason changes and this test should say so (D-073)."""
    from trdrbot.elfmem_adapter import ElfmemAdapter

    mem = await ElfmemAdapter.build(tmp_path / "e.db")
    try:
        await mem.begin()
        r = await mem.mem.remember("weight probe", tags=["contract"], category="knowledge",
                                   source="t", cue="when probing")
        await mem.mem.consolidate()
        with pytest.raises(ValueError, match="weight"):
            await mem.mem.outcome([r.block_id], 0.9, weight=0.0, source="t")
        await mem.end()
    finally:
        await mem.close()


@pytest.mark.asyncio
async def test_frame_similarity_is_bounded_but_its_spread_is_not_guaranteed(cfg):
    """What credit weighting may and may not assume about `similarity`.

    D-073 measured elfmem min-max normalising across each recall - worst match
    exactly 0.0, best exactly 1.0 - and built `credit_weight` on it, reporting a
    4x differential between the best and worst block in a decision.

    **That is no longer what a recall returns, and this test caught it.**
    Observed against the live database once the block pool grew: the returned
    set is a filtered top SLICE, not the whole scored population, so
    similarities cluster near the top (0.926-1.000 on a real query) and the
    worst returned match is nowhere near 0.0. The practical effect is that the
    credit differential has collapsed from the documented 4x to about 1.05x.

    That is not a regression to fix by manufacturing spread. A block returned at
    0.93 genuinely IS relevant, and forcing a 4x split across near-identical
    scores would invent discrimination the data does not contain. The
    irrelevant-block case D-073 was built for - a SPY mind model scoring 0.0
    against an NVDA query - now simply does not come back at all.

    So the beliefs that remain load-bearing, and are asserted here: similarity
    is BOUNDED in [0, 1], and it can arrive anywhere in that range. The floor in
    `credit_weight` is still mandatory, because elfmem rejects weight <= 0 (the
    test below) and nothing guarantees a returned similarity is above zero."""
    from trdrbot.elfmem_adapter import ElfmemAdapter
    from trdrbot.positions import CREDIT_WEIGHT_FLOOR, credit_weight

    mem = await ElfmemAdapter.build(cfg.paths.state / "elfmem.db")
    try:
        await mem.begin()
        fr = await mem.mem.frame("attention", "selling premium after an event")
        sims = [b.similarity for b in fr.blocks]
        assert len(sims) >= 2, "need several blocks for this to mean anything"
        for s in sims:
            assert 0.0 <= s <= 1.0, f"similarity outside [0,1]: {s} - semantics changed"
        # Whatever comes back must map to a weight elfmem will accept.
        for s in sims:
            assert CREDIT_WEIGHT_FLOOR <= credit_weight(s) <= 1.0
        await mem.end()
    finally:
        await mem.close()


async def test_anthropic_serves_a_marked_prefix_from_the_prompt_cache():
    """The belief the decide path's cost now rests on: a content block carrying
    `cache_control` is cached, and the SECOND call reads it back rather than
    paying full rate. 81% of this system's bill is input tokens and a react
    agent re-sends its prefix on every turn, so if this stops being true the
    decide cycle silently costs ~3x more."""
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage
    from trdrbot.usage import _cache_split

    big = "You are a trading agent. " + "Standing rule to consider. " * 250
    sys = SystemMessage(content=[{"type": "text", "text": big,
                                  "cache_control": {"type": "ephemeral"}}])
    m = init_chat_model("anthropic:claude-opus-5", max_tokens=64)

    first = await m.ainvoke([sys, HumanMessage(content="Reply with the number 1.")])
    second = await m.ainvoke([sys, HumanMessage(content="Reply with the number 2.")])

    r1, w1 = _cache_split((first.usage_metadata or {}).get("input_token_details") or {})
    r2, w2 = _cache_split((second.usage_metadata or {}).get("input_token_details") or {})

    # Deliberately NOT "the first call writes and the second reads". This test
    # runs against a shared 5-minute cache, so a re-run inside that window finds
    # the prefix already warm and the first call READS - which failed the run
    # after the one that wrote it. The belief that actually matters is that a
    # marked prefix is served from cache at all; which call paid to put it there
    # is not something the decide path depends on.
    assert r1 + w1 > 100, f"the marked prefix was neither written nor read: {r1}/{w1}"
    assert r2 > 100, f"the second call must read the prefix back, saw {r2}"
    # And the total already includes them, so pricing must adjust not add.
    assert (second.usage_metadata or {})["input_tokens"] >= r2


async def test_openai_tolerates_a_cache_control_block():
    """The decide prompt carries `cache_control` for Anthropic. The fallback
    chain sends the SAME message to OpenAI, so an OpenAI that rejected the key
    would turn a provider outage into a total outage."""
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage

    block = [{"type": "text", "text": "Reply with OK.",
              "cache_control": {"type": "ephemeral"}}]
    r = await init_chat_model("openai:gpt-4o-mini", max_tokens=16).ainvoke(
        [HumanMessage(content=block)])
    assert r is not None


async def test_one_mcp_session_serves_many_tool_calls(cfg):
    """`MultiServerMCPClient.get_tools()` returns tools that start a NEW stdio
    session per call, which for this server means respawning
    `uvx alpaca-mcp-server` every time - 12.3s across seven subprocesses for the
    six calls a housekeeping tick makes, against 2.75s in one."""
    from trdrbot import mcp_client

    async with mcp_client.session_tools(cfg) as tools_list:
        tools = {t.name: t for t in tools_list}
        assert "get_clock" in tools and "get_option_chain" in tools
        for _ in range(3):
            clock = await mcp_client.call(tools, "get_clock")
            assert isinstance(clock, dict) and "is_open" in clock


@pytest.mark.asyncio
async def test_glm_5_2_via_opencode_zen_actually_calls_a_bound_tool(cfg):
    """The one belief this whole migration rests on, and the one thing no
    amount of reading Zen's or Zhipu's docs can establish: does GLM-5.2,
    served over Zen's OpenAI-compatible endpoint, drive a LangGraph
    create_react_agent tool call reliably? Every role in this system - decide
    above all - is built on `bind_tools`/`create_react_agent`, and a model
    that answers fine in plain chat but silently ignores or mishandles tool
    schemas would make `decide` look healthy while never calling
    simulate_experiments or record_position. Skips (not fails) with no
    ZEN_API_KEY set, exactly like the project's own doctor probe."""
    import os

    if not os.environ.get("ZEN_API_KEY"):
        pytest.skip("ZEN_API_KEY not set - see .env.example")

    from langchain.chat_models import init_chat_model
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent

    @tool
    def get_ticker_price(ticker: str) -> str:
        """Return the current price for a ticker symbol."""
        return f"{ticker.upper()} is trading at $123.45"

    real_spec, conn_kwargs = cfg.resolve_model_spec("opencode_zen:glm-5.2")
    m = init_chat_model(real_spec, max_tokens=500, max_retries=1, **conn_kwargs)
    agent = create_react_agent(
        m, [get_ticker_price],
        prompt="Use the tool to answer. Always call get_ticker_price before answering.")
    result = await agent.ainvoke(
        {"messages": [("user", "What is SPY trading at right now?")]})

    calls = [tc for msg in result["messages"]
             for tc in (getattr(msg, "tool_calls", None) or [])]
    assert calls, "GLM-5.2 answered without calling the bound tool - decide would too"
    assert calls[0]["name"] == "get_ticker_price"
    assert str(calls[0]["args"].get("ticker", "")).upper() == "SPY"
    final = str(result["messages"][-1].content)
    assert "123.45" in final, "the tool RESULT must reach the final answer, not just the call"


@pytest.mark.asyncio
async def test_grok_4_6_via_opencode_zen_actually_calls_a_bound_tool(cfg):
    """The Grok mirror of the GLM belief above, and the more consequential one
    right now: Grok-4.6 is the CONFIGURED PRIMARY for decide. Deliberately
    does NOT skip on a live provider error - only on a missing key, the same
    as doctor's own probe. As of this migration Zen's grok-4.6 endpoint
    returns a reproducible HTTP 500 (verified three times, independent of
    this test), so this test is EXPECTED TO FAIL until that clears - which is
    the correct, honest behaviour for a contract test: it names the belief
    that is currently false rather than hiding it behind a skip."""
    import os

    if not os.environ.get("ZEN_API_KEY"):
        pytest.skip("ZEN_API_KEY not set - see .env.example")

    from langchain.chat_models import init_chat_model
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent

    @tool
    def get_ticker_price(ticker: str) -> str:
        """Return the current price for a ticker symbol."""
        return f"{ticker.upper()} is trading at $123.45"

    real_spec, conn_kwargs = cfg.resolve_model_spec("opencode_zen:grok-4.6")
    m = init_chat_model(real_spec, max_tokens=500, max_retries=1, **conn_kwargs)
    agent = create_react_agent(
        m, [get_ticker_price],
        prompt="Use the tool to answer. Always call get_ticker_price before answering.")
    result = await agent.ainvoke(
        {"messages": [("user", "What is SPY trading at right now?")]})

    calls = [tc for msg in result["messages"]
             for tc in (getattr(msg, "tool_calls", None) or [])]
    assert calls, "Grok-4.6 answered without calling the bound tool - decide would too"
    assert calls[0]["name"] == "get_ticker_price"
    final = str(result["messages"][-1].content)
    assert "123.45" in final, "the tool RESULT must reach the final answer, not just the call"


@pytest.mark.asyncio
async def test_the_decide_chain_survives_grok_being_down(cfg):
    """D-008 verified once, live, that a real Anthropic 400 falls through the
    chain. Grok-4.6 being confirmed live-down as of this migration makes this
    the same test for free, against a REAL failure rather than an injected
    one: does build_model's whole chain - not just resolve_model_spec's pure
    logic - still answer with the primary erroring? If Zen ever starts
    returning success-with-empty-content instead of a real HTTP error (the
    GLM-5.2 failure mode), this test would keep passing while decide quietly
    stopped reasoning - the gap D-076's `[assumptions]` principle exists to
    keep in view, not one this single test can close."""
    import os

    if not os.environ.get("ZEN_API_KEY"):
        pytest.skip("ZEN_API_KEY not set - see .env.example")

    from trdrbot.llm import build_model

    m = build_model(cfg, role="decide")
    r = await m.ainvoke("Reply with exactly the word: ok")
    served = (r.response_metadata or {}).get("model_name", "")
    assert r.content, "the chain must produce SOME answer despite the primary"
    assert served != "grok-4.6", (
        "if this starts passing WITH grok-4.6 as the served model, Zen's "
        "outage has cleared - update the config comment and I-25, don't "
        "just let the assertion go stale")


@pytest.mark.asyncio
async def test_gpt_5_6_sol_calls_a_bound_tool_through_the_real_build_model_path(cfg):
    """Not a scratch repro - this goes through `llm.build_model()` exactly as
    `tick.py` does, so it proves the ACTUAL production path (config resolution
    + use_responses_api + constructor-callback usage tracking, all at once)
    rather than a hand-assembled approximation of it.

    Grounds the fix a live 400 named: gpt-5.6-sol refuses function tools on
    the classic Chat Completions endpoint while reasoning is active. Every
    role in this system needs bind_tools, so an unfixed model_options entry
    would 400 on the very first tool call, every single decide cycle."""
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent
    from trdrbot.llm import build_model
    from trdrbot.usage import UsageLedger

    @tool
    def get_ticker_price(ticker: str) -> str:
        """Return the current price for a ticker symbol."""
        return f"{ticker.upper()} is trading at $123.45"

    m = build_model(cfg, role="decide")
    agent = create_react_agent(
        m, [get_ticker_price],
        prompt="Use the tool to answer. Always call get_ticker_price before answering.")
    result = await agent.ainvoke(
        {"messages": [("user", "What is SPY trading at right now?")]})

    calls = [tc for msg in result["messages"]
             for tc in (getattr(msg, "tool_calls", None) or [])]
    assert calls, "gpt-5.6-sol answered without calling the bound tool - decide would too"
    assert calls[0]["name"] == "get_ticker_price"
    final = str(result["messages"][-1].content)
    assert "123.45" in final, "the tool RESULT must reach the final answer, not just the call"
