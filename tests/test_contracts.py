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
async def test_an_option_positions_cost_basis_is_a_signed_dollar_total(cfg):
    """The belief every book cap now rests on (I-59).

    `reconcile` reprices a position's max loss from the fill, and derives BOTH
    the side and the per-share premium from `cost_basis` alone - specifically to
    avoid a second, untested belief about whether `avg_entry_price` is quoted
    per share or per contract. If cost_basis were ever per-share rather than a
    dollar total, every recomputed max loss would be wrong by the 100x contract
    multiplier, in the direction that says "plenty of room left in the caps".

    The discriminating property, not a value: cost_basis must reconcile with
    qty x avg_entry_price x 100 to within rounding. That single relationship
    pins the units of all three fields at once.
    """
    from trdrbot import mcp_client, optmath
    tools = await _tools(cfg)
    rows = await mcp_client.call(tools, "get_all_positions")

    assert isinstance(rows, list), f"expected a list, got {type(rows).__name__}"
    options = [r for r in rows if isinstance(r, dict)
               and optmath.parse_occ(str(r.get("symbol", "")))]
    if not options:
        pytest.skip("no option position open right now - nothing to check the units against")

    for row in options:
        cost = float(row["cost_basis"])
        qty, entry = abs(float(row["qty"])), float(row["avg_entry_price"])
        expected = qty * entry * optmath.CONTRACT_MULTIPLIER
        assert abs(abs(cost) - expected) <= max(1.0, 0.01 * expected), (
            f"{row['symbol']}: cost_basis {cost} does not equal qty x avg_entry_price "
            f"x {optmath.CONTRACT_MULTIPLIER} ({expected}). One of these three fields "
            f"has changed units, and filled_legs() derives risk from the first."
        )
        assert (cost > 0) == (float(row["qty"]) > 0), (
            f"{row['symbol']}: the sign of cost_basis no longer agrees with the sign "
            f"of qty - filled_legs() reads long/short from it."
        )


@pytest.mark.asyncio
@pytest.mark.skip(reason="places a real order - run manually, supervised, never in the "
                         "competition window; see docstring")
async def test_a_naked_short_option_is_refused_by_the_broker_or_by_our_level(cfg):
    """Is the broker a SECOND backstop against unbounded loss, or is sizing the
    only one?

    `size_position` refuses a structure whose max loss is unbounded, but the
    agent can reach `place_option_order` without calling it - so what the broker
    does with a naked short is the difference between one guard and none. We
    have never checked; the answer is currently an assumption.

    Deliberately unmarketable (a far-OTM short call priced far above any bid) so
    it cannot fill even briefly, cancelled in `finally`, and asserted on the
    SUBMISSION's shape only - never on a fill. Run it with the account open in
    front of you.
    """
    from trdrbot import mcp_client
    tools = await _tools(cfg)
    order_id = None
    try:
        r = await mcp_client.call(
            tools, "place_option_order", legs=[{
                "symbol": "SPY271217C01200000", "side": "sell", "ratio_qty": 1}],
            quantity=1, order_type="limit", limit_price=95.0, time_in_force="day")
        assert isinstance(r, (dict, str)), f"unexpected response type {type(r).__name__}"
        order_id = r.get("id") if isinstance(r, dict) else None
        # Either outcome is informative and BOTH are recorded by this assertion
        # failing loudly if the shape stops being readable at all.
        assert order_id or "reject" in str(r).lower() or "level" in str(r).lower(), (
            f"a naked short was neither accepted with an id nor refused with a "
            f"reason - the response says: {str(r)[:300]}"
        )
    finally:
        if order_id:
            await mcp_client.call(tools, "cancel_order_by_id", order_id=order_id)


@pytest.mark.asyncio
@pytest.mark.skip(reason="must run while the market is SHUT, against a symbol we do not "
                         "hold; see docstring")
async def test_close_position_off_hours_refuses_rather_than_silently_accepting(cfg):
    """WU-7.1 defers every close to an open session, on the belief that a close
    submitted into a shut market is not reliably actioned. This checks the half
    of that belief which is safe to check: a close must never come back looking
    like a success it did not achieve.

    Against a symbol we do not hold, so it exercises the transport and the error
    shape without touching the book. That is a real limit: it does NOT answer
    what the broker does with a close of a position we DO hold, off-hours, which
    needs either Alpaca's own documentation or a disposable single-contract
    position opened for the purpose - well clear of anything live.
    """
    from trdrbot import mcp_client
    tools = await _tools(cfg)
    clock = await mcp_client.call(tools, "get_clock")
    if clock.get("is_open"):
        pytest.skip("market is open - this test is about the shut-session path")

    try:
        r = await mcp_client.call(
            tools, "close_position", symbol_or_asset_id="ZZZNOTAREALSYMBOL999")
    except Exception as exc:  # noqa: BLE001 - an exception IS a valid outcome here
        assert str(exc), "the transport raised without saying why"
        return
    assert "error" in str(r).lower() or "not" in str(r).lower(), (
        f"closing a position we do not hold returned something that reads like "
        f"success: {str(r)[:300]}. `exit_rules` treats a non-raising close as "
        f"submitted, so a false success there strands a live position."
    )


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


@pytest.mark.asyncio
async def test_the_mutation_role_never_returns_an_unsafe_prompt(cfg, tmp_path):
    """Whatever the Coach accepts as a challenger must be safe to run. (D-088)

    The belief under test is about an external model, so it is checked against
    the real endpoint - the discipline that caught GLM-5.2 returning nothing
    (D-084) and gpt-5.6-sol refusing bound tools (D-085).

    It asserts the INVARIANT, not a success rate. Generation is stochastic:
    measured live, a first attempt fails validation a meaningful fraction of
    the time, always the same way - literal braces written in prose, which
    `.format()` reads as a placeholder - which is why `mutate` retries with the
    rejection reason fed back. Returning None after exhausting its attempts is
    a legitimate outcome the pulse handles. Returning something INVALID is not,
    and would crash the next live muse run rather than this test.

    Asserting "always produces a valid prompt" would be a flaky test of a
    probabilistic property. Asserting "never produces an invalid one" is the
    property the system's safety actually rests on.
    """
    from types import SimpleNamespace

    from trdrbot import coach, muse
    from trdrbot.journal import Journal

    journal_path = tmp_path / "journal.jsonl"
    journal_path.touch()
    journal = Journal(journal_path)
    state = SimpleNamespace(
        lever="muse.prompt", next_variant_n=1,
        incumbent=coach.Variant("v0", muse.MUSE_PROMPT))

    v = await coach.mutate(cfg, state, [], journal)

    rows = [r for r in journal.read()
            if r["kind"] in ("coach_mutation", "coach_mutation_rejected")]
    assert rows, "the mutation role was never reached - no attempt was journalled"

    if v is None:
        # Acceptable, but it must have SAID why, on every attempt - a silent
        # refusal is undiagnosable, and the reasons are how the retry works.
        rejected = [r for r in rows if r["kind"] == "coach_mutation_rejected"]
        assert len(rejected) == coach.MUTATE_ATTEMPTS
        assert all(r.get("reason") for r in rejected)
        pytest.skip(f"mutation exhausted {coach.MUTATE_ATTEMPTS} attempts: "
                    f"{[r['reason'][:60] for r in rejected]}")

    why = coach.validate_prompt(
        v.text, muse.MUSE_PROMPT, coach.lever("muse.prompt").placeholders,
        must_contain=("band_low_pct", "band_high_pct", "JSON array"))
    assert why == "", f"mutate() returned a challenger that fails validation: {why}"

    # The real proof: it survives the exact format() call muse.run makes.
    rendered = v.text.format(
        today="2026-08-29", n=3, k=5, concepts="C", news="N", odds="O",
        earliest="2026-08-31", preferred="2026-09-01", latest="2026-09-03")
    assert len(rendered) > 500
    # ...and carries none of the harness's own framing into production.
    assert not rendered.lstrip().startswith(("<<<", "```", "- - -"))

# Three OpenCode Zen contract tests stood here - GLM-5.2 tool-calling,
# Grok-4.6 tool-calling, and "the decide chain survives grok being down".
# D-084/D-085 removed both models from every chain (GLM-5.2 spent an entire
# 8,000-token budget on invisible reasoning; grok-4.6 returned HTTP 500 three
# times running), and one of the three carried "EXPECTED TO FAIL" in its own
# docstring.
#
# A 19-test tier carrying three permanently-red entries trains the reader to
# ignore red in the ONE tier whose whole value is that red means something.
# The belief they were protecting - that neither model is in any live chain -
# is pinned offline and for free by
# `test_gpt_5_6_sol_is_the_configured_primary_not_grok_or_glm`.
