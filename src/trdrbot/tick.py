"""One tick, split by cost (D-017).

    EVERY TICK (cheap, deterministic, no LLM)
        C21 analytics  ->  C13 reconcile  ->  C24 exit rules
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        That order is the D-019 fix (INV-25): reconciling first means a
        position the broker already resolved is terminal before exit rules
        run, so it is excluded by construction rather than by a later check.

    EVERY N TICKS (expensive)
        resume-check -> assemble context (incl. elfmem frames) -> decide
        -> act -> journal

    MARKET CLOSED
        housekeeping instead of decide: interim scoring (INV-24), the only
        place elfmem's dream() is allowed to run (INV-10/23).

Fast monitoring with slow deciding shortens the exposure window while cutting
LLM spend - the exit evaluator needs no model to notice a breached stop.

elfmem's session() auto-consolidates on exit (verified against the running
library, see elfmem_adapter.py) - so a tick begins/ends its own session
manually and never calls dream() itself.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langgraph.prebuilt import ToolNode, create_react_agent

from . import (
    analytics,
    blog,
    compact,
    competence,
    exit_rules,
    failures,
    health,
    housekeeping,
    idle,
    ids,
    learn,
    local_tools,
    mcp_client,
    news_extract,
    optmath,
    prompts,
    reconcile,
    sensors,
    sizing,
    tool_guard,
    usage,
)
from . import (
    ledger as ledger_mod,
)
from . import (
    store as store_mod,
)
from .calibration import CalibrationStore
from .config import Config
from .elfmem_adapter import ElfmemAdapter
from .inbox import Inbox, Item
from .journal import Journal
from .llm import SYSTEM_PROMPT, build_model
from .positions import ACTIVE, PositionStore
from .wiki import Wiki


def _tick_count(config: Config) -> int:
    p = config.paths.state / "tick_count"
    n = int(p.read_text(encoding="utf-8").strip() or 0) + 1 if p.exists() else 1
    store_mod.write_atomic(p, str(n))
    return n


def _text_of(message: Any) -> str:
    """Readable text from a message whose content may be a block list.

    Extended-thinking responses return a list of blocks - a `thinking` block
    carrying an opaque signature blob, then the actual `text`. Stringifying
    the whole list dumped that blob into the journal and the console, burying
    the agent's reasoning in base64 and wasting the 2000-char summary budget.
    """
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return str(content)


#: Beta-weighted book delta above this share of equity per 1% market move is
#: called out as a directional bet. Reported, never gated (D-009): it bounds
#: variance, not ruin, and defined-risk legs already bound the worst case.
BETA_DELTA_FLAG_PCT = 1.5

#: Share of the tier's book cap consumed before the book is called full. THIS
#: is the number that is actually a limit, and it is the one the flag belongs
#: on. The delta flag above says "these positions are one bet", which is a
#: diversification observation; this one says "there is no budget left", which
#: is a constraint. They had been collapsed into a single CONCENTRATED stamp
#: attached to the delta, and the agent read the diversification observation as
#: the constraint - declining in 41 of 89 cycles against an unbounded linear
#: number while 86% of the actual risk budget sat unused.
BOOK_RISK_FLAG_SHARE = 0.75

#: Underlyings named in the ATTENTION query. Enough to cover a decision's real
#: subject matter; small enough that one market-wrap article tagging eight
#: tickers cannot drown out the name actually being traded.
ATTENTION_MAX_NAMES = 6

def decide_tool_node(agent_tools: list[Any]) -> ToolNode:
    """Tools bound so a RUNTIME tool error becomes a ToolMessage, not a crash.

    langgraph's pre-1.0 default was `handle_tool_errors=True`: every tool
    exception came back to the model as an error message it could react to.
    The >=1.0 default returns a message only for pydantic argument-validation
    errors and RE-RAISES everything else - and this project pins
    `langgraph>=0.2`, so the behaviour the whole decide path assumes changed
    underneath it. Verified against the installed 1.2.11: with the default, a
    tool raising RuntimeError propagates straight out of `agent.ainvoke`.

    That costs far more than a lost turn. The escape lands in the handler at
    the end of this module, which classifies TRANSIENT and calls
    `inbox.record_failure` on EVERY pending item - so three MCP blips
    dead-letter every opportunity, for something none of them caused. Worse,
    a raise from `record_position` AFTER an order filled means the `execution`
    row is never journalled and the "order placed but record_position was not
    called" warning never runs: a live position with no exit rules, and
    nothing saying so.

    The design already assumes this contract - every `tool_guard` refusal is a
    STRING and the compactor fails open, both results rather than exceptions.
    """
    return ToolNode(agent_tools, handle_tool_errors=True)


def _attention_query(items: list[Item], open_pos: list[Any], config: Config) -> str:
    """What to ask MEMORY about, given what this cycle is actually deciding.

    Was `" ".join(config.watchlist) + " options setup"` - a constant. With
    watchlist ["SPY"], every ATTENTION recall asked about SPY no matter what
    the agent was looking at, so the NVDA position was decided with SPY
    memories in context and then, at attribution, CREDITED them: 2 of its 3
    creditable blocks were about the wrong underlying (D-072). Retrieval was
    answering a question nobody asked, and the learning loop was scoring the
    answer.

    Ordered by how directly a name bears on the decision - open positions
    (money at risk now), then proposed opportunities (what we may act on),
    then news symbols - and capped, because relevance is the point and a
    longer query is a vaguer one. The watchlist stays as the floor so an empty
    cycle still recalls something rather than querying the empty string.

    News symbols are filtered to names we could actually trade, which the
    first live run showed is not optional: one broad-market article tagged
    twelve ETFs, and the unfiltered version asked memory about "AGG BND GLD"
    - bond and gold noise - pushing SPY, the only name in the book, to fourth.
    That was WORSE than the constant it replaced. An article's ticker list is
    what it mentions, not what we are deciding about.
    """
    tradeable = {s.upper() for s in config.watchlist} | {
        s.upper() for s in config.research_universe}
    names: list[str] = []

    def add(raw: Any) -> None:
        s = str(raw or "").upper().strip()
        if s and s.isalnum() and s not in names:
            names.append(s)

    for p in open_pos:
        add(p.underlying)
    for i in items:
        # An opportunity names its own candidate, which discovery may well
        # have nominated from outside the universe - that is the point of it,
        # so it is never filtered.
        if i.type == "opportunity":
            add(i.payload.get("underlying"))
    for i in items:
        if i.type == "news":
            for s in (i.payload.get("symbols") or []):
                if str(s).upper() in tradeable:
                    add(s)
    for s in config.watchlist:
        add(s)
    return " ".join(names[:ATTENTION_MAX_NAMES]) + " options setup"


def render_competence(posture: Any, can_open: bool = True, why: str = "") -> str:
    """The size budget as the agent reads it. Public so it can be tested.

    `posture.reason` states EARNED and APPLIED Kelly when an appetite is in
    play, and it sits here directly beside `next_tier_needs()`, which promises
    more size for more resolved theses. Reporting only the applied figure would
    tell the agent it had EARNED a posture the operator chose, while the ladder
    went on advertising a reward the appetite had already halved (D-099).

    The appetite clause is stated only when there is something to state, and it
    names the BOUNDARY rather than editorialising. `size_position` is consulted
    in 2 of 89 decide cycles (I-68) - the other 87 decide in prose - so this is
    where a risk posture actually reaches behaviour, and an agent that read
    "less risk" as "trade less often" would be moving a lever nobody set.
    Selectivity is the EV gate's business, and the gate is upstream of every
    multiplication the appetite performs.
    """
    return (
        f"## Competence tier: {posture.tier.upper()}\n"
        f"{posture.reason}. Book cap {posture.book_cap:.0%} of equity in defined "
        f"max-loss, {posture.position_cap:.1%} on any one position; size_position "
        f"enforces both - do not argue with the number it returns.\n"
        f"To earn more size: {posture.next_tier_needs()}. Size is earned by resolved, "
        f"ATTRIBUTABLE theses - a profit on a wrong view is luck and counts for nothing."
        + (f"\nThese caps carry an operator risk appetite of "
           f"{posture.appetite:.2f}x. It scales SIZE, not selectivity - what is "
           f"worth trading is unchanged." if posture.appetite != 1.0 else "")
        + (f"\nHARD STOP: {why}" if not can_open else "")
    )


def _render_book_risk(positions: list[Any], bg: dict[str, Any] | None,
                      equity: float, posture: Any) -> list[str]:
    """The book's risk, in the unit the whole system measures risk in, first.

    D-037 settled that risk here means DOLLARS OF DEFINED MAX LOSS AGAINST
    EQUITY: it is what the three sizing caps count, what the ladder's book cap
    is denominated in, and what a defined-risk book can actually lose. Every
    surface honoured that except this one, which led with beta-weighted delta.

    Delta is a LOCAL SLOPE through a payoff that is flat beyond its far strike,
    so on a defined-risk book it is unbounded above the thing it purports to
    describe. Measured on the live 13-lot 766/758 put spread: the prompt read
    `-3.48% of equity per 1% SPY move` against a position whose entire max loss
    was 2.14% of equity - the headline risk number was 1.63x the worst case
    that exists, and at a 5% move it overstated the real mark loss by 6x. The
    agent then declined trade after trade against it while 86% of the book's
    risk budget sat unused.

    So: defined risk leads and carries the flag, because it is the constraint.
    Delta follows, labelled as the diversification lens it actually is.
    """
    lines: list[str] = []
    at_risk = sum(p.max_loss_usd or 0.0 for p in positions)
    unpriced = sum(1 for p in positions if p.max_loss_usd is None)
    cap = getattr(posture, "book_cap", None)
    if equity > 0 and cap:
        budget, used = cap * equity, at_risk / (cap * equity)
        flag = ("  <- BOOK FULL: this is the binding limit, not the delta below"
                if used >= BOOK_RISK_FLAG_SHARE else "")
        lines.append(
            f"Defined risk: ${at_risk:,.0f} of max loss = {at_risk / equity:.1%} of "
            f"equity, against the {getattr(posture, 'tier', '').upper()} book cap of "
            f"{cap:.0%} (${budget:,.0f}). {used:.0%} used, ${budget - at_risk:,.0f} "
            f"of headroom." + (f" ({unpriced} position(s) carry no recorded max "
                               f"loss and count as zero here.)" if unpriced else "")
            + flag
        )
        # A cap CUT below what the book already carries is neither a bug nor an
        # emergency. Sizing gates NEW risk and never liquidates - a preference
        # dial that submits market orders is not a preference dial - so the book
        # runs over its target until positions expire. Said out loud, because an
        # operator who lowered the appetite and then read an over-cap book would
        # reasonably read it as a failure (D-099).
        if at_risk > budget:
            lines.append(
                f"  ^ OVER CAP by ${at_risk - budget:,.0f}. Nothing is being "
                f"force-closed: sizing gates NEW risk only, so the cap is a target on "
                f"the way down, not an invariant. New positions are refused until this "
                f"unwinds."
            )
    if not bg:
        return lines
    skip = f" ({bg['positions_skipped']} unpriced)" if bg["positions_skipped"] else ""
    lines.append(
        f"Book greeks (est., entry IV): delta ${bg['delta_dollars']:+,.0f}"
        f" | theta ${bg['theta_dollars']:+,.0f}/day"
        f" | vega ${bg['vega_dollars']:+,.0f}/IVpt{skip}."
    )
    if "beta_weighted_delta" not in bg:
        return lines
    pct = bg.get("pct_equity_per_1pct_spy")
    assumed = bg.get("betas_assumed") or []
    note = (f" ({len(assumed)} beta assumed - poor fit or no history: "
            f"{', '.join(assumed)})" if assumed else "")
    # The flag is a DIVERSIFICATION observation, so it needs something to
    # diversify (D-102). On a one-name book "these positions are one market
    # bet, whatever the names suggest" is a tautology - there is one name - and
    # the agent read it as a reason not to add the second position that would
    # have fixed it. It was the stated rationale in 5 of the last 6 declines.
    names = {p.underlying for p in positions if p.underlying}
    flag = ""
    if pct is not None and abs(pct) >= BETA_DELTA_FLAG_PCT and len(names) > 1:
        flag = ("  <- DIRECTIONAL: these positions are one market bet, "
                "whatever the names suggest")
    elif pct is not None and abs(pct) >= BETA_DELTA_FLAG_PCT:
        flag = ("  <- one name, so this IS the position, not a concentration "
                "finding. A second name would lower it, not raise it")
    lines.append(
        f"Beta-weighted to SPY: ${bg['beta_weighted_delta']:+,.0f} delta"
        + (f", i.e. {pct:+.2f}% of equity per 1% SPY move" if pct is not None else "")
        + f". Betas {bg['betas']}{note}.{flag}"
    )
    lines.append(
        "That percentage is a LOCAL SLOPE, not a loss: these are defined-risk "
        "structures, so however far SPY moves the book's entire downside is the "
        "defined risk above. Use the delta to ask whether a new position is a NEW "
        "bet or more of this one; judge whether you can AFFORD it against the "
        "headroom, which is the number that actually binds."
    )
    return lines


def _render_positions(positions: list[Any], bg: dict[str, Any] | None = None,
                      equity: float = 0.0, posture: Any = None) -> str:
    """Two-tier context (D-019): detail for what needs attention, one line for the rest.

    Takes what it renders. It used to take the store, the snapshot, a state
    directory and an equity figure - four parameters, three of them present
    only so that a RENDERER could compute book greeks internally, where nothing
    else could see the result. The caller computes them now and journals them
    on the way past (WU-4.10), which is how they became a gauge at all.
    """
    if not positions:
        return "## Our positions\n\n(none)"

    lines = ["## Our positions", ""]
    # Book shape first: what the book has at risk, then correlated exposure in
    # its native units. Three bullish put spreads on three tickers LOOK
    # diversified and ARE one +delta/-vega/+theta position - this is where that
    # becomes visible before a fourth one gets added (D-040).
    risk_lines = _render_book_risk(positions, bg, equity, posture)
    if risk_lines:
        lines += [*risk_lines, ""]
    for p in positions:
        rules = ", ".join(
            # `level` for underlying stops, `threshold` for mark-based ones.
            # Reading only `threshold` printed "underlying_stop=None" on a
            # position whose thesis stop WAS set - a rendering bug that told
            # the agent its most important guard was missing.
            f"{r['type']}="
            f"{r.get('threshold', r.get('level', r.get('days_before_expiry')))}"
            for r in p.exit_rules
        ) or "NO EXIT RULES"
        lines.append(f"- **{p.position_id}** [{p.status}] {p.strategy} on {p.underlying} "
                      f"(trust: {p.trust_tier()})")
        lines.append(f"  legs: {', '.join(p.symbols) or '(none)'} | exits: {rules}")
        lines.append(f"  thesis: {p.thesis[:200]}")
    return "\n".join(lines)


# `_market_pulse` lived here: it decided whether a material move or too long a
# silence warranted a fresh look. It was defined, unit-tested, and NEVER CALLED
# - `idle.decide` absorbed the whole rung when D-043 landed and nothing removed
# the original. Deleted rather than wired up, because it was not merely dead: it
# carried its own copies of the two thresholds (PULSE_MOVE / MATERIAL_MOVE and
# PULSE_MAX_SILENCE_MIN / MAX_SILENCE_MIN), so anyone tuning the pulse would
# have changed the system's behaviour by exactly nothing while its test kept
# passing. Duplicated constants behind a dead function are worse than no
# function. `idle.MATERIAL_MOVE` and `idle.MAX_SILENCE_MIN` are now the only
# copies, and `test_material_move_wakes_the_agent_through_the_idle_ladder`
# tests the path that actually runs.


async def run_tick(
    config: Config, *, verbose: bool = True, force_decide: bool = False
) -> dict[str, Any]:
    """One tick, on ONE MCP session.

    The session wraps the whole tick because the adapter's default tools start
    a fresh stdio subprocess per tool CALL - measured at 12.3s for the six
    calls a quiet housekeeping tick makes, against 2.75s sharing one
    (mcp_client.session_tools).
    """
    async with mcp_client.session_tools(config) as tools_list:
        return await _run_tick(config, tools_list, verbose=verbose,
                               force_decide=force_decide)


def _usage_went_dark(model_served: list[str], llm_turns: int) -> bool:
    """A cycle that certainly called an LLM but whose ledger recorded nothing.

    `model_served` is read back FROM the usage ledger, so a failed ledger write
    yields an empty list on the execution row - which is D-070's
    mis-attribution returning through the back door, plus a Coach cost sentinel
    reading low because the calls it prices are not there.

    Detected at the consumer rather than at the write: the usage callback runs
    sync-in-a-thread inside the agent loop and must not grow IO.

    Deliberately quiet when `llm_turns` is 0. That means the message shapes
    changed and the count is no longer evidence of anything - and a detector
    that cries wolf gets ignored, which costs more than the miss.
    """
    return llm_turns > 0 and not model_served


def _order_legs(call: dict[str, Any]) -> list[dict[str, Any]]:
    return [leg for leg in ((call.get("args") or {}).get("legs") or [])
            if isinstance(leg, dict)]


def _opens_a_position(call: dict[str, Any]) -> bool:
    """Does this order OPEN exposure, rather than close it?

    `position_intent` lives on the LEGS in Alpaca's multi-leg payload, and this
    was reading it off the top level - where it is never present - so the test
    was `"close" not in ""`, permanently True. Every `place_option_order` read
    as opening, including the closes the agent submits through the same tool
    (live: `theo-close-spy-bps-20260901-0957`, three sell_to_close legs), so
    the "no exit rules were recorded" warning cried wolf on every exit.
    """
    if not str(call.get("name", "")).startswith("place_"):
        return False
    args = call.get("args") or {}
    intents = " ".join([*(str(leg.get("position_intent", "")) for leg in _order_legs(call)),
                        str(args.get("position_intent", ""))]).lower()
    if "to_open" in intents:
        return True
    # Stated and every leg closes -> a close. Nothing stated at all -> assume
    # opening, which is the side that WARNS: a missed warning on an exit is
    # noise, a missed warning on an entry is a position with no stops.
    return "close" not in intents


def _placed_contracts(call: dict[str, Any]) -> list[int]:
    """Contracts this order actually sends per leg: `qty` x each `ratio_qty`."""
    args = call.get("args") or {}
    try:
        qty = int(float(args.get("qty") or args.get("quantity") or 0))
    except (TypeError, ValueError):
        return []
    if qty <= 0:
        return []
    out: set[int] = set()
    for leg in _order_legs(call):
        try:
            ratio = int(float(leg.get("ratio_qty") or 1))
        except (TypeError, ValueError):
            ratio = 1
        if ratio > 0:
            out.add(qty * ratio)
    return sorted(out) or [qty]


def _order_underlying(call: dict[str, Any]) -> str:
    for leg in _order_legs(call):
        parsed = optmath.parse_occ(str(leg.get("symbol", "")))
        if parsed:
            return str(parsed["underlying"]).upper()
    return ""


def _guarded_mcp_tools(tools_list: list[Any], config: Config, batch: str,
                       store: PositionStore, journal: Any = None) -> list[Any]:
    """The MCP tools the decide agent may call, wrapped in the four guards.

    One coherent step, and the only part of the tool assembly that is one -
    the local tools are built alongside the competence assessment they depend
    on, so hoisting those too would give this function a name it does not
    earn.

    Order matters and composes deliberately (D-065): bind only the allowlisted
    tools (schemas for 72 cost ~21k tokens per call and the agent has ever
    used 17), compact heavy results at the boundary so a 61k-char option chain
    enters context as a ~4k table instead of being re-sent every turn, then
    the two guards. `enforce_order_ids` is what makes INV-18 hold at all: the
    model authors every tool argument, so without it the client_order_id is
    whatever it invents.
    """
    allow = set(config.decide_tools)
    tools = [t for t in tools_list if not allow or t.name in allow]
    tools = compact.wrap_heavy_tools(tools, config, journal)
    tools = tool_guard.enforce_order_ids(tools, batch)
    # Every status carrying real broker exposure, not just `open` (I-58). An
    # `opening` position has an order working and a `closing` one is mid-
    # liquidation - `close_all_positions` would touch both, so both must count
    # toward the >1 refusal. `closing` is no longer transient either: it now
    # persists across ticks until the retry completes (I-57). `proposed` alone
    # is excluded - nothing has been sent to the broker yet.
    return tool_guard.redirect_whole_book_close(
        tools, lambda: len([p for p in store.open_positions()
                            if p.status in ACTIVE - {"proposed"}])
    )


async def _build_decide_prompt(
    *, snap: analytics.Snapshot, store: PositionStore, wiki: Wiki, config: Config,
    posture: Any, cal_now: Any, ctx: Any, items: list[Item], prior: Any, n: int,
    journal: Any = None,
) -> str:
    """Everything the decide agent reads, assembled in priority order.

    Extracted from `_run_tick` verbatim - ~90 lines of `prompt_parts.append`
    that made the tick's actual ORDERING (the D-019 guarantees the module
    docstring is at pains to explain) impossible to see. Only the assembly
    moved; the fast path, the idle ladder and the post-invoke bookkeeping stay
    inline, because scattering those would lose the plot this module exists to
    keep straight.
    """
    open_now = store.open_positions()
    book_greeks = analytics.book_greeks(
        open_now, snap.underlying_prices,
        state_dir=config.paths.state, equity=snap.equity or 0.0)
    if book_greeks and journal is not None:
        # The book's risk SHAPE, on the record once per decide cycle. Computed
        # here already for the prompt; journalling it costs nothing and is what
        # turns "the book drifted into one big directional bet" from something
        # a reader might notice into a trajectory (WU-4.10). A vega CAP has to
        # earn its existence from this series - measure first, gate later.
        journal.append(
            "book_risk", positions=len(open_now),
            delta_dollars=round(book_greeks["delta_dollars"], 2),
            vega_dollars=round(book_greeks["vega_dollars"], 2),
            theta_dollars=round(book_greeks["theta_dollars"], 2),
            beta_weighted_delta=book_greeks.get("beta_weighted_delta"),
            pct_equity_per_1pct_spy=book_greeks.get("pct_equity_per_1pct_spy"),
            skipped=book_greeks.get("positions_skipped", 0))
    prompt_parts = [snap.render(),
                    _render_positions(open_now, book_greeks, snap.equity or 0.0, posture)]
    _ok, _why = competence.can_open(config.deadline, None)
    prompt_parts.append(render_competence(posture, _ok, _why))
    if config.events:
        from datetime import date as _date
        ev_lines = []
        for ev in config.events:
            try:
                days = (_date.fromisoformat(str(ev["date"])) - ids.market_today()).days
            except (KeyError, ValueError):
                continue
            if 0 <= days <= 14:
                ev_lines.append(f"- {ev['date']} ({days}d away): {ev.get('name','')}")
        if ev_lines:
            prompt_parts.append(
                "## Known macro events (binary risk - check every holding window)\n"
                + "\n".join(ev_lines)
            )
    regime = wiki.read("context/regime")
    if regime and regime.body.strip():
        # Labelled when expired rather than dropped. The regime page is a
        # singleton that rewrites itself, so an old one is the only market
        # context there is - but presenting it undated as "the regime"
        # is what makes a stale read indistinguishable from a fresh one.
        # It IS stale on disk right now, and nothing said so.
        stale = " - STALE, read as history" if regime.is_stale() else ""
        generated = (regime.frontmatter.get("generated") or {}).get("at", "")
        prompt_parts.append(
            f"## Market regime (research desk, {generated[:10]}{stale})\n\n"
            + regime.body[:1800]
        )
    if ctx.text:
        prompt_parts.append(f"## What you remember\n\n{ctx.text}")
    # News gets enriched HERE, at the decide seam, not at ingestion (D-070).
    # Sensors are deliberately deterministic and LLM-free (D-015), and the
    # decide path is the one that both pays for news and acts on it. Doing
    # it here also means the freshest article - the one that just arrived
    # and matters most - is enriched at the moment of the decision rather
    # than whenever research/discovery/muse next happens to run.
    #
    # Measured on two live articles: raw JSON payloads rendered 1,322 chars;
    # enriched rendered 824 - 38% SMALLER while adding sentiment, event
    # type, regime, claim horizon and entities. Extraction cost ~$0.0002.
    # Cheaper and more informative, which is the only kind of trade worth
    # making here.
    news_items = [i for i in items if i.type == "news"]
    other_items = [i for i in items if i.type != "news"]
    obs_lines = []
    if news_items:
        try:
            payloads = [dict(i.payload, id=i.payload.get("id") or i.id) for i in news_items]
            extracts = await news_extract.enrich(payloads, config, journal)
            obs_lines.append(news_extract.render_block(extracts))
        except Exception as exc:  # noqa: BLE001 - fail open to the raw payloads
            print(f"[tick {n}] news enrichment failed, using raw payloads: {exc!r}")
            obs_lines += [f"- [news | trust={i.trust}] {json.dumps(i.payload)}"
                          for i in news_items]
    obs_lines += [f"- [{i.type} | trust={i.trust}] {json.dumps(i.payload)}" for i in other_items]
    prompt_parts.append("## Observations this cycle\n\n" + "\n".join(obs_lines))
    # THE LOOP'S OTHER HALF (D-113). `learn._write_lesson` has appended one
    # entry per resolved position to `lessons.md` since D-022, and nothing has
    # ever read it back into a decision: the system learned and then decided
    # without consulting what it learned. Its own trading history was on disk
    # and out of context, while the prompt carried an aggregate calibration
    # number that cannot say WHICH trades produced it.
    #
    # Placed immediately before that number for exactly that reason - the
    # base rate, then the trades it is made of.
    lessons = learn.recent_lessons(wiki)
    if lessons:
        prompt_parts.append(
            "## What happened when you traded\n\n"
            "Your last resolved positions, most recent last. These are the "
            "outcomes behind the calibration figure below.\n\n" + lessons
        )
    # Same `cal_now` the ladder and the sizing tool read - one number, one
    # meaning. The prompt used to show a position-only figure while size
    # was gated on a ledger-inclusive one.
    if cal_now.n:
        prompt_parts.append(
            f"## Your calibration so far\n\n{cal_now.verdict()}\n\n"
            f"Base rate: {cal_now.base_rate:.0%} of your resolved forecasts and closed "
            f"positions came in. Use this to set `confidence` honestly - it is scored, "
            f"and it is the same number size_position shrinks your claim against.\n"
            f"Sample: {cal_now.sample_note()}."
        )
    _win = competence.forecast_window(config.deadline)
    prompt_parts.append(
        "## Constraints\n"
        + (f"- Hard stop: {config.deadline} - everything is force-closed then, so "
           f"prefer expiries well inside it.\n" if config.deadline else
           "- No hard stop: the run continues indefinitely, so a position is closed "
           "by its own exit rules and nothing else.\n")
        + f"- Useful horizons: {_win[0]} to {_win[2]}, aim around {_win[1]}. Short "
        f"horizons resolve while the reasoning is still checkable.\n"
        # NOT "Watchlist: SPY" (D-102). One word under a heading called
        # Constraints, describing the NEWS scope, read for the whole run as a
        # restriction on what could be traded - while nothing in tool_guard,
        # sizing or the order path filters by symbol at all, and the book had
        # already traded NVDA. 62 opportunities reached the inbox across 40+
        # names and the agent formed theses on 2 of them. Say what is true.
        + f"- Tradeable: ANY liquid, optionable US name. Quoted for you below: "
        f"{', '.join(sorted(set(config.watchlist) | set(config.research_universe)))}.\n"
        f"- Candidates in this cycle's observations may name others. They are "
        f"not second-class: price them and judge them on the same terms."
    )
    if prior:
        prompt_parts.append(
            "## Resuming\nA previous decision for this batch did not complete. "
            "Its order id is idempotent, so re-attempting the same action is safe - "
            "a duplicate will be rejected."
        )
    return "\n\n".join(prompt_parts)


async def _run_tick(
    config: Config, tools_list: list[Any], *, verbose: bool = True,
    force_decide: bool = False,
) -> dict[str, Any]:
    journal = Journal(config.paths.journal)
    inbox = Inbox(config.paths, max_retries=config.max_retries)
    store = PositionStore(config.paths.wiki)
    wiki = Wiki(config.paths.wiki)
    calib = CalibrationStore(config.paths.state / "forecasts.jsonl")

    n = _tick_count(config)
    tools = {t.name: t for t in tools_list}

    mem = await ElfmemAdapter.build(config.paths.state / "elfmem.db")
    await mem.begin(task_type="trade_decision")  # active-hours clock; no auto-dream (see module docstring)

    try:
        # ---------- fast path: every tick, no LLM ----------
        sensed = await sensors.collect(tools, config, inbox, n, verbose=verbose)
        # Price what the agent may DECIDE about, not only what it already
        # holds (D-102). A candidate used to arrive with bands and no mark, so
        # evaluating it cost two tool calls the agent demonstrably did not
        # spend - measured: on both cycles where non-SPY candidates were
        # presented, it made ZERO tool calls and its summary named neither.
        # An option it cannot see the price of is not an option.
        snap = await analytics.snapshot(
            tools,
            underlyings=sorted(
                {p.underlying for p in store.open_positions() if p.underlying}
                | {s.upper() for s in config.research_universe}
                | {str(i.payload.get("underlying") or "").upper()
                   for i in inbox.pending() if i.type == "opportunity"}
                - {""}
            ),
            # So an unreadable broker leaves a `degraded` row health reads back,
            # rather than a print in an unattended run (I-55).
            journal=journal,
        )
        recon = await reconcile.reconcile(store, snap, journal, mem, wiki, calib,
                                          blog_dir=config.paths.blog)
        triggered = await exit_rules.run(
            store, snap, tools, journal, config.deadline, mem, wiki,
            calibration=calib, blog_dir=config.paths.blog, verbose=verbose
        )

        if verbose:
            print(f"[tick {n}] market_open={snap.market_open} equity=${snap.equity:,.0f} "
                  f"holdings={len(snap.broker_positions)}")
            # Sensors were the ONE fast-path subsystem whose output the tick
            # discarded entirely - `sensed` was assigned and never read, so a
            # collector emitting nothing looked identical to one emitting
            # twenty. That is the shape `health` exists to catch, and there is
            # no sensor heartbeat probe to catch it instead.
            print(f"[tick {n}] sensors: "
                  + (", ".join(f"{k}={v}" for k, v in sorted(sensed.items()) if v)
                     or "nothing new"))
            print(f"[tick {n}] reconcile: {reconcile.summarise(recon)}")
            if triggered:
                print(f"[tick {n}] exit rules closed: {triggered}")

        # ---------- market closed: housekeeping, not decide ----------
        # force_decide exercises the full reasoning chain outside market hours.
        # Orders queue rather than fill, so this tests the DECISION, not the
        # execution - useful for development and for demoing the agent's
        # reasoning without waiting for the bell.
        if not snap.market_open and not force_decide:
            hk = await housekeeping.run(store, snap, mem, wiki, journal, config,
                                        tools=tools, verbose=verbose)
            return {"status": "housekeeping", "tick": n, "market_open": snap.market_open,
                    "sensed": sensed, "exits": triggered, **hk}

        # ---------- slow path: every N ticks ----------
        if n % config.decide_every_n_ticks != 0:
            if verbose:
                print(f"[tick {n}] fast path only (decide runs every "
                      f"{config.decide_every_n_ticks} ticks)")
            return {"status": "fast_only", "tick": n, "market_open": snap.market_open,
                    "sensed": sensed, "exits": triggered}

        items = inbox.pending()

        # Stale candidates are worse than none: they were priced against
        # quotes that no longer exist, and the agent has correctly declined
        # them on exactly that basis. Expire before they reach the prompt.
        if items:
            fresh = inbox.expire_stale(idle.OPPORTUNITY_STALE_MIN, journal)
            if fresh:
                items = inbox.pending()
                if verbose:
                    print(f"[tick {n}] expired {fresh} stale opportunity item(s)")

        if not items:
            # An empty inbox is several states, not one (D-043). The ladder
            # picks the cheapest rung that the situation actually justifies.
            import zoneinfo
            from datetime import datetime
            et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
            action = idle.decide(
                market_open=snap.market_open,
                positions=store.open_positions(),
                underlying_prices=snap.underlying_prices,
                last_decision_at=journal.last_decision_at(),
                last_hunt_at=journal.last_hunt_at(),
                open_risk_usd=sum(p.max_loss_usd or 0.0 for p in store.open_positions()),
                equity=snap.equity or 100000.0,
                risk_cap_fraction=sizing.PORTFOLIO_MAX_AT_RISK,
                minutes_to_close_=idle.minutes_to_close(et),
            )
            if verbose:
                print(f"[tick {n}] idle -> {action.level}: {action.reason}")

            if action.level == "hunt" and tools:
                # Intraday opportunity generation, priced at LIVE quotes. Every
                # candidate the agent had seen until now was researched while
                # the market was CLOSED, and it kept declining them for exactly
                # that reason ("any spread I priced now would be simulated on
                # prices that no longer exist").
                try:
                    from . import discovery
                    r = await discovery.run(tools, config, inbox, wiki, journal,
                                            verbose=verbose)
                    journal.append("hunt", opportunities=r["opportunities"],
                                   reason=action.reason)
                    items = inbox.pending()
                except Exception as exc:  # noqa: BLE001 - hunting is advisory
                    # LOUD (D-102). Hunting being advisory means a failure must
                    # not stop the tick; it does not mean a failure may be
                    # invisible. A shadowed name killed six consecutive hunts
                    # over two days behind this `print`, and because discovery
                    # is the ONLY source that nominates outside the fixed
                    # research universe, the book quietly became single-name.
                    # `degraded` rows escalate in `trdrbot health` on repeat.
                    print(f"[tick {n}] hunt failed, continuing: {exc!r}")
                    journal.append("hunt", opportunities=0, error=repr(exc))
                    health.degraded(journal, "discovery", type(exc).__name__,
                                    detail=repr(exc)[:200])

                # The muse rides the same rung (D-088). It was CLI-only, so its
                # A/B trials had no runs to feed on - a lever nothing exercises
                # improves nothing. The daily cap lives in `muse.run` now, so
                # every caller inherits it (D-092).
                try:
                    from . import coach, muse
                    book = ledger_mod.Ledger(config.paths.state / "ledger.jsonl")
                    r_muse = await muse.run(tools, config, inbox, wiki, journal, book,
                                            verbose=verbose)
                    if not r_muse.get("skipped"):
                        items = inbox.pending()
                        # Pulse immediately: the trial result just landed, and
                        # housekeeping (the other pulse site) only runs while
                        # the market is CLOSED - so waiting for it would defer
                        # every promotion to the following night.
                        await coach.pulse(config, journal,
                                                                                    verbose=verbose)
                except Exception as exc:  # noqa: BLE001 - the muse is advisory
                    print(f"[tick {n}] muse failed, continuing: {exc!r}")
            elif action.level == "review":
                inbox.write("position_review", {
                    "reason": action.reason, **action.detail,
                }, source="idle", trust="primary")
                items = inbox.pending()

        if not items:
            if verbose:
                print(f"[tick {n}] inbox empty - no decide cycle")
            return {"status": "idle", "tick": n, "market_open": snap.market_open,
                    "sensed": sensed, "exits": triggered}

        batch = ids.batch_id([i.id for i in items])
        prior = journal.unresolved_decision(batch)
        if prior and verbose:
            print(f"[tick {n}] resuming unresolved decision {prior['id']} (not re-deciding)")

        # The model authors every tool argument, so without this it invents its
        # own client_order_id and INV-18's idempotency guarantee silently evaporates.
        # Context diet (D-065), applied BEFORE the guards so everything
        # composes: (1) bind only the allowlisted tools - schemas for 72 cost
        # ~21k tokens per call and the agent has ever used 17; (2) compact
        # heavy results at the boundary so a 61k-char option chain enters
        # context as a ~4k table instead of being re-sent in full every turn.
        guarded = _guarded_mcp_tools(tools_list, config, batch, store, journal)

        open_pos = store.open_positions()
        query = _attention_query(items, open_pos, config)
        ctx = await mem.assemble_context(query)

        decision_id = journal.append(  # write-ahead (INV-18)
            "decision",
            batch=batch,
            model=config.model,
            tick=n,
            # Which prompts actually produced this decision. Cannot be
            # reconstructed later, so it is recorded now even though no
            # second variant exists yet (D-045).
            prompts=prompts.fingerprints(config=config),
            item_ids=[i.id for i in items],
            resumed_from=prior["id"] if prior else None,
            elfmem_blocks=ctx.blocks,
        )

        shared = local_tools.SharedContext()
        book = ledger_mod.Ledger(config.paths.state / "ledger.jsonl")
        sim_tool = local_tools.build_simulate_experiments(shared, config.paths.state, book)
        forecast_tool = local_tools.build_record_forecast(book, config.paths.state)
        open_risk = sum(p.max_loss_usd or 0.0 for p in open_pos)
        by_underlying: dict[str, float] = {}
        for op in open_pos:
            if op.underlying:
                by_underlying[op.underlying.upper()] = (
                    by_underlying.get(op.underlying.upper(), 0.0) + (op.max_loss_usd or 0.0)
                )
        equity_now = snap.equity or 100000.0
        hw = competence.update_high_water(config.paths.state, equity_now, journal)
        # Calibration draws on declined-thesis forecasts too (D-052). Computed
        # ONCE and passed everywhere it is needed: the ladder, the sizing tool
        # and the prompt all used to derive their own, and the sizing tool's
        # omitted the ledger entirely.
        declined = ledger_mod.as_forecasts(book.resolved())
        cal_now = calib.score(declined)
        posture = competence.assess(
            resolved=cal_now.n, reliability=cal_now.reliability,
            positions=store.all(), equity=equity_now, high_water=hw,
            # Reported on the ladder, never gated on (D-009). 29 forecasts
            # across a handful of names came to 11.8 independent, and a reader
            # told only "15 resolved (have 29)" would think the next rung was
            # already earned.
            effective=cal_now.n_eff,
            # The operator's size preference (D-099). The ONE thing on this
            # posture the agent did not earn, and the one it may not set.
            appetite=config.risk_appetite,
        )
        if verbose:
            print(f"[tick {n}] competence: {posture.reason}")
        journal.append("competence", tier=posture.tier, resolved=posture.resolved,
                       reliability=posture.reliability,
                       # None here now MEANS unmeasured rather than 0%, so the
                       # gauge series can tell a young pipeline from a lucky
                       # book. `verdicts` is what says which (WU-8.2).
                       attributable_rate=posture.attributable_rate,
                       verdicts=posture.verdicts, effective=posture.effective,
                       drawdown=posture.drawdown, book_cap=posture.book_cap,
                       position_cap=posture.position_cap,
                       kelly_multiplier=posture.kelly_multiplier,
                       seed_fraction=posture.seed_fraction,
                       # THREE numbers, because they can differ and each
                       # difference means something (D-099): what the operator
                       # asked for, what survived the clamp, and what survived
                       # the ruin bound. A row where all three agree is the
                       # normal case; one where they do not is a knob that was
                       # partly or wholly absorbed, and `trdrbot health` says
                       # so. Rows before D-099 carry no appetite key at all -
                       # absent means pre-lever, and the journal is append-only.
                       appetite=posture.appetite,
                       appetite_config=config.risk_appetite,
                       realised_appetite=round(posture.realised_appetite, 4),
                       equity=equity_now, high_water=hw)
        size_tool = local_tools.build_size_position(
            calib, equity_now,
            open_risk_usd=open_risk, open_risk_by_underlying=by_underlying,
            shared=shared, posture=posture, extra_forecasts=declined,
            # Every sizing outcome on the record, refusals included (WU-4.2).
            # A rising refusal share is the only production-visible sign that
            # the structure-matching seam is losing the conditional payoff.
            journal=journal,
        )
        record_tool = local_tools.build_record_position(
            store, decision_id, elfmem_blocks=ctx.blocks,
            # The CHAIN, not its head. `config.model` is the configured intent,
            # and the fallback demonstrably fires: on 2026-08-28 the decide
            # role was served by claude-opus-5 (97 calls), gpt-5 (19) and
            # gpt-5.6-sol (6) per usage.jsonl, while every position page
            # recorded a single name. D-070 fixed exactly this for the journal
            # (`model_served`) and left the position pages saying something
            # confidently wrong. Which model answered each call is in
            # usage.jsonl, keyed by time; what the page can honestly claim at
            # write time is the chain that was eligible to answer.
            generated_by=" | ".join(config.model_chain("decide")),
            calibration=calib,
            sources=[{"id": i.id, "resource": f"inbox/{i.id}", "author": i.source}
                     for i in items],
            shared=shared, ledger=book, journal=journal,
        )
        agent_tools = guarded + [sim_tool, size_tool, record_tool, forecast_tool]
        agent = create_react_agent(build_model(config, role="decide"),
                                   decide_tool_node(agent_tools), prompt=SYSTEM_PROMPT)

        prompt = await _build_decide_prompt(
            snap=snap, store=store, wiki=wiki, config=config, posture=posture,
            cal_now=cal_now, ctx=ctx, items=items, prior=prior, n=n,
            journal=journal,
        )

        # Marks the start of THIS cycle's LLM calls, so the served model can be
        # read back from the usage ledger afterwards (D-070). Taken before the
        # call, not after, or a slow cycle would pick up the next one's calls.
        decide_started_at = ids.utc_now().isoformat()

        # PROMPT CACHING, and this is the one lever that matters for spend.
        # 81% of this system's bill is INPUT tokens, and a react agent re-sends
        # its whole accumulated context on every turn - measured at 7 calls
        # averaging 22-33k input tokens each for ONE decide cycle, of which the
        # tool schemas, the system prompt and this opening message are byte
        # identical every time. A cache breakpoint at the end of the opening
        # message covers all three (Anthropic caches the prefix up to and
        # including the marked block, and tool definitions sit ahead of the
        # messages), so turns 2..n read it back at a tenth of the rate.
        #
        # Safe across the fallback chain: verified that gpt-5-mini and
        # gpt-4o-mini both accept a content block carrying `cache_control` and
        # simply ignore the key, so an Anthropic outage still falls through.
        cached_prompt = [{"type": "text", "text": prompt,
                          "cache_control": {"type": "ephemeral"}}]
        try:
            # The one call in a tick that can hang for minutes on end: a react
            # agent looping over a provider that has stopped answering. Five
            # retries per model times three models in the chain, with no bound
            # of its own - and `tick_lock` does not help, because it makes
            # LATER ticks skip rather than killing the holder (FM-26).
            # TimeoutError classifies TRANSIENT, so the handler below journals
            # it and retries the batch next cycle, which is the right policy.
            result = await asyncio.wait_for(
                agent.ainvoke({"messages": [("user", cached_prompt)]}),
                timeout=config.watchdog_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            cause = failures.classify(exc)
            journal.append("error", batch=batch, decision_ref=decision_id,
                           cause=cause.value, error=repr(exc))
            for it in items:
                inbox.record_failure(it, reason=f"agent error: {exc!r}", cause=cause)
            if verbose:
                print(f"\n[tick {n}] FAILED ({cause.value}): {type(exc).__name__}: {exc}")
                print(f"\n  {failures.advice(cause, exc)}\n")
            raise

        messages = result["messages"]
        final = messages[-1]
        summary_text = _text_of(final)
        calls = [tc for m in messages for tc in (getattr(m, "tool_calls", None) or [])]
        orders = [tc for tc in calls if tc.get("name") in mcp_client.ORDER_TOOLS]
        recorded = [tc for tc in calls if tc.get("name") == "record_position"]
        # READ WHAT THE BROKER SAID (D-112). The order tool RETURNS
        # `{"error": ...}` with isError=False, so a rejected order and a
        # filled one both count as "an order call was made": the execution row
        # was written and the order probe read healthy on a book of rejections.
        # Pair each order call with its ToolMessage and read the payload.
        results = {getattr(m, "tool_call_id", None): getattr(m, "content", "")
                   for m in messages if getattr(m, "type", "") == "tool"}
        rejected: list[dict[str, Any]] = []
        for tc in orders:
            raw = results.get(tc.get("id"))
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                payload = raw
            why = mcp_client.in_band_error(mcp_client.unwrap(payload))
            if why:
                rejected.append({"name": tc.get("name"), "error": why})
        if rejected:
            health.degraded(journal, "orders", "broker rejected an order the agent placed",
                            rejected=rejected)

        # I-60 AT THE RIGHT SEAM (D-113). The mismatch check lived only inside
        # `record_position`, where it compares sizing's contract count against
        # the legs the agent WROTE DOWN. Those two agreeing says nothing about
        # what went to the broker: sizing computes 3, the order sends 10, the
        # page records 3, and `max_loss_usd` - what every book cap sums - is
        # denominated in a size that was never traded, with no row anywhere.
        # Reported, never refused (D-009): this holds the agent's own two tool
        # calls against each other rather than gating either.
        sized = shared.sizing
        for call in orders:
            if sized is None or not _opens_a_position(call):
                continue
            placed = _placed_contracts(call)
            u = _order_underlying(call)
            if sized.underlying not in ("", u) or not placed:
                continue
            if placed != [sized.contracts]:
                journal.append("sizing_mismatch", seam="placed", underlying=u,
                               sized_contracts=sized.contracts, placed_qtys=placed,
                               decision_ref=decision_id)
                print(f"\n[tick {n}] WARNING: size_position computed "
                      f"{sized.contracts} contract(s) for {u}; the order placed "
                      f"{placed}. The book caps are sized against "
                      f"{sized.contracts}.")

        # `model` is the configured INTENT (chain head); `served` is what
        # actually answered. They differ whenever the fallback fires, and
        # recording only the former made the journal confidently wrong about
        # who made 19 decisions (D-070).
        served = usage.UsageLedger(
            config.paths.state / "usage.jsonl").served_since("decide", decide_started_at)
        llm_turns = sum(1 for m in messages if getattr(m, "type", "") == "ai")

        journal.append(
            "execution" if orders else "no_op",
            batch=batch,
            decision_ref=decision_id,
            model=config.model,
            model_served=served,
            tick=n,
            client_order_id=ids.client_order_id(batch) if orders else None,
            tool_calls=[tc.get("name") for tc in calls],
            order_calls=[
                {"name": tc.get("name"),
                 "args_as_model_supplied": tc.get("args"),
                 "client_order_id_enforced": ids.client_order_id(batch)}
                for tc in orders
            ],
            positions_recorded=len(recorded),
            orders_rejected=rejected,
            summary=summary_text[:2000],
        )
        if _usage_went_dark(served, llm_turns):
            health.degraded(journal, "usage", "no calls recorded for this cycle",
                            llm_turns=llm_turns, since=decide_started_at,
                            decision_ref=decision_id)

        # One trade-blog entry per position record_position wrote this cycle
        # (D-097) - everything it needs was already computed by simulate/size/
        # record, so this is formatting, not a second decision. Advisory: a
        # publishing failure must never be able to take the tick down with it.
        for trade in shared.recorded_trades:
            blog.write_entry(
                trade, summary_text=summary_text, decision_ref=decision_id, batch=batch,
                model=config.model, served=served,
                blog_dir=config.paths.blog, journal=journal,
            )

        inbox.archive(items)

        # An order that OPENS a position without a recorded position has no
        # exit rules and nothing can act on it. Only opening orders qualify:
        # this fired on `replace_order_by_id` when the agent repriced its own
        # exit, demanding a record_position for a position it was closing. A
        # warning that cries wolf teaches everyone to ignore warnings - the
        # same class as the underlying_stop=None rendering bug (D-056). It
        # cried wolf anyway until D-113: the intent it read lives on the LEGS,
        # so the filter was `"close" not in ""` and every close qualified.
        opening_orders = [o for o in orders if _opens_a_position(o)]
        if opening_orders and not recorded:
            print("\n[tick] WARNING: order placed but record_position was not called - "
                  "this position has no exit rules and the evaluator cannot see it.")

        if verbose:
            print(f"\n[tick {n}] tools: {[tc.get('name') for tc in calls] or 'none'}")
            print(f"[tick {n}] orders={len(orders)} positions_recorded={len(recorded)}")
            print(f'\n--- agent ---\n{summary_text}\n')

        return {"status": "done", "tick": n, "market_open": snap.market_open, "batch": batch,
                "orders": len(orders), "recorded": len(recorded),
                "sensed": sensed, "exits": triggered}
    finally:
        await mem.end()  # no dream() here - see module docstring
        await mem.close()
