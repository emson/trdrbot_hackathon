"""Local LangGraph tools (D-016 - local capability is a tool, not an MCP server).

`record_position` is the bridge from the model's prose to machine-readable
state. Without it the agent states a stop-loss in a sentence and nothing can
act on it; with it, the exit-rule evaluator has something deterministic to
check every 60 seconds.

This is why the agent is *required* to call it after opening a position: an
exit rule that exists only in prose is not an exit rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from . import experiments, ids, market_stats, optmath, sizing
from .analytics import MIN_NET_COST_SHARE
from .calibration import CalibrationStore
from .ledger import PRICE_BAND, REALIZED_VOL_PCT, STANDALONE
from .positions import Position, PositionStore


@dataclass(frozen=True)
class MarketParams:
    """The market this cycle simulated against. `record_position` re-prices the
    executed legs from exactly these, so entry greeks are DERIVED rather than
    re-declared by the model (D-037/D-040)."""

    spot: float
    iv: float          # FRACTION (0.165 = 16.5%)
    days: int


@dataclass(frozen=True)
class SimStructure:
    """One priced candidate, keyed by its legs so the traded one can be found
    again without the model re-declaring anything."""

    key: tuple
    name: str
    qty: int
    entry_cost: float | None
    max_profit: float | None
    max_loss: float | None
    payoff_ratio: float | None
    rr: float | None
    #: Gross premium traded across all legs. Carried because the mark-based
    #: P&L base is refused below `MIN_NET_COST_SHARE` of it, which makes every
    #: stop and target on such a structure permanently unobservable (I-45).
    gross_premium: float | None = None
    #: {(right, strike, side): iv_fraction} for legs that quoted their own IV.
    #: The skew the agent OBSERVED, kept so `record_position` can put it on the
    #: recorded legs rather than asking the model to re-declare it (D-037).
    #: None when the board was flat.
    leg_ivs: dict | None = None


@dataclass(frozen=True)
class SizingStash:
    """What `size_position` computed, so `record_position` can fill
    `max_loss_usd` itself. A forgotten field would silently count the position
    as zero risk and quietly loosen the book caps (D-037)."""

    underlying: str
    contracts: int
    max_loss_usd: float


@dataclass
class SharedContext:
    """What one decide cycle's tools know about each other.

    This was a bare `dict[str, Any]` - the system's real domain model, and
    invisible: `simulate_experiments` wrote four keys, `size_position` read one
    and wrote another, `record_position` read four, and the schema existed only
    as `.get()` chains spread across four closures. Every "derive, don't
    declare" fix in the codebase (D-037, D-040) was implemented by adding a key
    to it, and nothing could check that the reader and the writer agreed.
    """

    thesis: experiments.Thesis | None = None
    market: MarketParams | None = None
    ranked: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    structures: list[SimStructure] = field(default_factory=list)
    sizing: SizingStash | None = None
    #: One entry per successful record_position call this cycle - the trade
    #: blog's whole input, captured here rather than re-derived, because
    #: `record_position` already computed the matched structure and still has
    #: every rejected one in scope (D-097).
    recorded_trades: list[RecordedTrade] = field(default_factory=list)


@dataclass(frozen=True)
class RecordedTrade:
    """A position `record_position` just wrote, with the sibling structures it
    was chosen over. `matched` is None when nothing in `structures` matched
    the recorded legs (sizing was skipped, or the model recorded something it
    never simulated) - the blog still gets written, honestly missing that part."""

    position: Position
    matched: SimStructure | None
    alternatives: list[SimStructure]
    confidence: float



def _legs_key(legs: list[tuple[str, float, str]]) -> tuple:
    """Identity of a structure, independent of quantity. (right, strike, side)."""
    return tuple(sorted((str(r).upper()[:1], round(float(k), 4), str(s).lower())
                        for r, k, s in legs))


def _unreachable_rules(
    stop_loss_pct: float | None, profit_target_pct: float | None,
    net_cost: float, max_profit: float | None, max_loss: float | None,
) -> list[str]:
    """Mark-based rules that can never fire, given this structure's own payoff.

    A percentage stop is a percentage OF THE NET ENTRY COST (see
    `analytics.position_pnl_fraction`), so its trigger is a dollar amount that the
    position's bounded payoff may simply never reach. Both live positions had
    this and nobody could see it:

        NVDA 230/240 debit spread, stop -60%   needs -$2,287 against a $2,253
                                               max loss - it could never fire
        SPY  755/750 credit spread, target +50% needs +$1,057 against a $535
                                               max profit - never

    The agent believed it had a stop. It had a sentence. This is the same
    failure `watched_signals` was written for - a stated invalidation level no
    rule watches - one level deeper: a rule that IS watched and cannot trigger.
    Reported, never blocked (D-009).
    """
    out: list[str] = []
    base = abs(net_cost)
    if base <= 0:
        return out
    if stop_loss_pct is not None and max_loss is not None:
        need = abs(stop_loss_pct) / 100.0 * base
        if need > abs(max_loss) + 1e-9:
            out.append(
                f"stop_loss {stop_loss_pct:g}% needs a ${need:,.0f} loss but this "
                f"structure can only lose ${abs(max_loss):,.0f} - it can NEVER fire. "
                f"The whole max loss is {abs(max_loss) / base:.0%} of what you paid; "
                f"a stop must be tighter than that"
            )
    if profit_target_pct is not None and max_profit is not None:
        need = abs(profit_target_pct) / 100.0 * base
        if need > max_profit + 1e-9:
            out.append(
                f"profit_target {profit_target_pct:g}% needs a ${need:,.0f} gain but "
                f"max profit is ${max_profit:,.0f} - it can NEVER fire. Max profit is "
                f"{max_profit / base:.0%} of what you paid; a target must be under that"
            )
    return out


def build_simulate_experiments(shared: SharedContext, state_dir: Path | None = None,
                               ledger: Any = None) -> StructuredTool:
    """Tool: score several expressions of one thesis before risking anything.

    Takes ALL candidates in a single call rather than one per call - that is
    deliberate. A per-candidate tool lets the agent simulate one structure and
    stop, which is just a slower way of deciding first and justifying after.
    Requiring the list up front forces the comparison to actually happen.
    """

    def simulate_experiments(
        thesis_claim: str,
        underlying: str,
        horizon: str,
        drift_pct: float,
        spot: float,
        iv_pct: float,
        days_to_expiry: int,
        candidates: list[dict[str, Any]],
        band_low: float | None = None,
        band_high: float | None = None,
        vol_view_pct: float | None = None,
    ) -> str:
        """Simulate several candidate structures expressing ONE thesis, and rank them.

        Call this BEFORE placing any order. Give at least two genuinely
        different structures - if every candidate is the same shape with
        different strikes, you are not exploring, you are decorating a choice
        you already made.

        Args:
            thesis_claim: your falsifiable view in one sentence
            underlying: e.g. "SPY"
            horizon: YYYY-MM-DD by which the thesis is decided
            drift_pct: expected TOTAL return over the horizon (2.0 = +2%).
                This is your view. If it is 0 you are claiming no directional
                edge, and the thesis edge column will show that honestly.
            spot: current underlying price
            iv_pct: implied vol as a percent (20.0 = 20%)
            days_to_expiry: calendar days to the options' expiry
            band_low: thesis holds only if price >= this at horizon
            band_high: thesis holds only if price <= this at horizon.
                Give at least one band - without one the thesis cannot be
                scored later and you lose the ability to learn whether your
                VIEW or your STRUCTURE was wrong.
            vol_view_pct: your forecast for the ANNUALIZED REALIZED VOL over
                this horizon, in percent (8.5 = 8.5%). **State it whenever the
                trade is about volatility** - premium you think is rich,
                premium you think is cheap, any range structure. It is the vol
                half of your decision measure: P(profit), expected value and
                the payoff ratio that sizes the trade are all computed under
                it, so a vol edge you can defend becomes size you have earned.
                Omit it and those columns price under the market's own IV,
                where by construction you have no vol edge at all - the honest
                answer for a purely directional thesis, and the wrong one for a
                condor. It is the number you already state in prose every cycle
                ("I forecast 8.5%; the condors need sub-7.5%"), so put it on
                the record with record_forecast(metric='realized_vol') too -
                that is what turns a claim into a scored input.
            candidates: list of {name, rationale, legs}, where legs is a list
                of {right: "C"|"P", strike, side: "long"|"short", qty, price,
                bid?, ask?, iv_pct?}. Include bid and ask when you have real
                quotes: friction is then computed from the ACTUAL spreads
                instead of a flat 10% of premium, and price should be the
                mid. Include iv_pct per leg when the surface is skewed - net
                vega/greeks then honour the skew you observed instead of a
                flat surface.
        """
        thesis = experiments.Thesis(
            claim=thesis_claim, underlying=underlying, horizon=horizon,
            drift=drift_pct / 100.0, band_low=band_low, band_high=band_high,
            # Percent at the boundary, fraction inside - the same convention as
            # iv_pct and drift_pct, and the conversion happens here, once.
            vol_view=(vol_view_pct / 100.0) if vol_view_pct is not None else None,
        )
        built: list[experiments.Experiment] = []
        frictions: list[float | None] = []
        for c in candidates:
            raw_legs = list(c.get("legs") or [])
            # Real friction from real quotes: a round trip crosses ~one full
            # bid/ask spread per leg. Only used when EVERY leg has a sane
            # quote pair - a partial set silently mixes models.
            friction: float | None = None
            quoted = [
                (float(l["ask"]) - float(l["bid"]), float(l.get("qty", 1)))
                for l in raw_legs
                if l.get("bid") is not None and l.get("ask") is not None
                and float(l["ask"]) >= float(l["bid"]) >= 0
            ]
            if len(quoted) == len(raw_legs) and quoted:
                friction = sum(sp * q * optmath.CONTRACT_MULTIPLIER for sp, q in quoted)
            frictions.append(friction)
            try:
                legs = [
                    optmath.Leg.parse({k: v for k, v in l.items() if k not in ("bid", "ask")})
                    for l in raw_legs
                ]
            except ValueError as e:
                return f"Invalid legs in candidate {c.get('name')!r}: {e}"
            if not legs:
                return f"Candidate {c.get('name')!r} has no legs."
            built.append(experiments.Experiment(
                name=str(c.get("name") or f"candidate {len(built)+1}"),
                legs=legs, rationale=str(c.get("rationale") or ""),
            ))
        if len(built) < 2:
            return (
                "Give at least two genuinely different structures. One candidate is not "
                "an experiment, it is a decision already made."
            )

        # Historical bootstrap, if the research cycle has refreshed this
        # underlying's closes recently. Demeaned + thesis drift applied, so
        # the HISTORY row is comparable with the thesis view, and the tail
        # gap is attributable to distribution shape.
        factors = None
        realized_vol_pct = None
        if state_dir is not None:
            closes = market_stats.load_closes(state_dir, underlying)
            if closes:
                # The CALIBRATED bootstrap, the same one the muse's gates read
                # (D-089). The raw one was measured overconfident by 15-23pp
                # exactly where credit spreads live (I-29), and this call feeds
                # the EV, POP and payoff_ratio columns the agent chooses a
                # structure from - and then sizing's Kelly gate. An optimistic
                # tail here is an optimistic bet size downstream. The inflation
                # is fitted offline with a holdout veto and is 1.0 whenever no
                # fit exists, so this is byte-identical until one does.
                factors = market_stats.bootstrap_factors(
                    closes, days_to_expiry, seed=underlying, drift=drift_pct / 100.0,
                    inflate=market_stats.band_inflation(state_dir, days_to_expiry),
                ) or None
                # Same closes, already loaded: what the tape has actually been
                # delivering, to sit beside what the market is charging.
                realized_vol_pct = market_stats.compute_stats(underlying, closes).realized_vol
        results = [
            (e, experiments.simulate(e, thesis, spot, iv_pct / 100.0, days_to_expiry,
                                     terminal_factors=factors, friction_usd=fr,
                                     realized_vol_pct=realized_vol_pct))
            for e, fr in zip(built, frictions)
        ]
        ranked = experiments.rank(results)
        # Pre-registration is AUTOMATIC (D-052). Every thesis simulated is
        # recorded here, traded or not - the agent cannot forget it, cannot
        # skip it under pressure, and pays no extra prompt burden. An LLM
        # generates far more theses than it trades, and the discarded ones are
        # exactly what a multiple-testing correction needs to count.
        if ledger is not None:
            try:
                ledger.register(
                    kind="thesis", underlying=underlying, claim=thesis_claim,
                    # Placeholder: this records the TRIAL, not a forecast.
                    # probability_stated=False keeps it out of calibration.
                    probability=0.5, probability_stated=False, horizon=horizon,
                    band_low=band_low, band_high=band_high,
                    notes=f"{len(built)} structures simulated",
                )
            except Exception as exc:  # noqa: BLE001 - never block a decision
                print(f"[ledger] register failed: {exc!r}")
        shared.thesis = thesis
        # Market params of this simulation - record_position derives the
        # entry greeks from these, same derive-not-declare pattern as sizing.
        shared.market = MarketParams(spot=spot, iv=iv_pct / 100.0, days=days_to_expiry)
        shared.ranked = [(e.name, m) for e, m in ranked]
        # Every simulated structure, keyed by its LEGS, so record_position can
        # find the one actually traded without the model re-declaring anything
        # (D-037's derive-not-declare). Used to tell the agent when an exit
        # rule it just wrote can never fire.
        shared.structures = [
            SimStructure(
                key=_legs_key([(l.right, l.strike, l.side) for l in e.legs]),
                name=e.name,
                qty=sum(l.qty for l in e.legs),
                entry_cost=m.get("entry_cost"),
                max_profit=m.get("max_profit"),
                max_loss=m.get("max_loss"),
                # Kelly's real `b` for this structure, carried so size_position
                # can use it without the model re-declaring a number it was
                # just shown (D-037's derive-don't-declare).
                payoff_ratio=m.get("payoff_ratio"),
                rr=(abs(m["max_profit"] / m["max_loss"])
                    if m.get("max_profit") is not None and m.get("max_loss") else None),
                gross_premium=sum(l.price * l.qty * optmath.CONTRACT_MULTIPLIER
                                  for l in e.legs),
                leg_ivs={_legs_key([(l.right, l.strike, l.side)]): l.iv
                         for l in e.legs if l.iv is not None} or None,
            )
            for e, m in results if m.get("usable")
        ]
        return experiments.render_comparison(thesis, ranked)

    return StructuredTool.from_function(
        func=simulate_experiments,
        name="simulate_experiments",
        description=simulate_experiments.__doc__,
    )


def _leg_qty(leg: dict[str, Any]) -> int:
    """A recorded leg's contract count, 0 when it is unreadable.

    Model-authored, so a string, a null or a float are all live possibilities;
    an unreadable quantity must not raise inside `record_position` (that would
    lose a position that is already open at the broker) and must not be
    silently counted as a real number either.
    """
    try:
        return abs(int(float(leg.get("qty", 0) or 0)))
    except (TypeError, ValueError):
        return 0


#: How much of max loss may already be locked in at a thesis stop's own level
#: before that stop stops being protection. At 0.99 the payoff is flat: the
#: level can only ever confirm a loss that is already fully taken.
STOP_TOO_LATE_SHARE = 0.99


def _late_underlying_stops(legs: list[dict[str, Any]], below: float | None,
                           above: float | None) -> list[str]:
    """Thesis stops that fire only after the payoff has already bottomed out.

    `_unreachable_rules` catches a mark rule that can never fire. This is its
    sibling one step out: a rule that fires reliably, on the right signal, at a
    price where there is nothing left to save. A vertical's payoff is FLAT
    beyond its far strike, so a stop placed out there is outside the range
    where price still moves P&L at all.

    Found by the harmony scaffold on the live book: a 766/758 bear put spread
    carrying `underlying_stop above 776`. Max loss is fully realised at 766, so
    the stop sat 10 points past the point of no further damage - and satisfied
    `health`'s "has an underlying stop" check the whole time, which is what
    made it invisible. The position read as protected because it was watched.

    Reported, never blocked (D-009). A stop out there is not senseless - it
    still closes a position whose view has clearly failed, which frees capital
    and ends the theta bleed. It is just not PROTECTION, and the difference is
    the agent's to weigh once it is stated.
    """
    parsed = [optmath.Leg.from_position_leg(leg) for leg in legs]
    if not parsed or not all(parsed):
        return []
    out: list[str] = []
    for level, direction in ((below, "below"), (above, "above")):
        if level is None:
            continue
        try:
            locked = optmath.loss_locked_at(parsed, float(level))
        except optmath.MultiExpiryError:
            return []  # a calendar: payoff-at-expiry says nothing useful here
        if locked is not None and locked >= STOP_TOO_LATE_SHARE:
            out.append(
                f"underlying_stop {direction} {float(level):g} sits where "
                f"{locked:.0%} of max loss is ALREADY taken - the payoff is flat "
                f"there, so this level can only confirm a loss, never limit one. "
                f"For protection the level has to sit inside the strikes, where "
                f"price still moves P&L"
            )
    return out


def _horizon_outlives_expiry(horizon: str, expiry: str) -> str | None:
    """A view that resolves after the trade is gone cannot be tested by it.

    The position is force-closed at expiry (or at the deadline, INV-26), the
    claim is still unresolved, and attribution scores that as the VIEW being
    wrong - when the real error was choosing an expiry too short to hold it.
    That is a corrupted learning signal, not just a bad trade: it teaches the
    agent to distrust a view that may have been right.
    """
    try:
        h, e = date.fromisoformat(str(horizon)), date.fromisoformat(str(expiry))
    except (ValueError, TypeError):
        return None
    if h <= e:
        return None
    return (f"thesis_horizon {horizon} is AFTER expiry {expiry} - the position is "
            f"closed {(h - e).days} day(s) before its own claim can resolve, and "
            f"attribution will score the unresolved view as wrong. Either shorten "
            f"the horizon or buy the expiry that outlives it")


def build_record_position(
    store: PositionStore,
    decision_ref: str,
    *,
    elfmem_blocks: dict[str, list[str] | dict[str, float]] | None = None,
    generated_by: str = "",
    calibration: CalibrationStore | None = None,
    sources: list[dict[str, Any]] | None = None,
    shared: SharedContext | None = None,
    ledger: Any = None,
    journal: Any = None,
) -> StructuredTool:
    def record_position(
        underlying: str,
        strategy: str,
        legs: list[dict[str, Any]],
        thesis: str,
        confidence: float,
        expiry: str = "",
        stop_loss_pct: float | None = None,
        profit_target_pct: float | None = None,
        time_stop_days_before_expiry: int | None = None,
        underlying_stop_below: float | None = None,
        underlying_stop_above: float | None = None,
        max_loss_usd: float | None = None,
    ) -> str:
        """Record a position you have just opened, with its exit conditions.

        Call this immediately after a successful order placement. The exit
        rules you give here are evaluated automatically every tick and will
        close the position without asking you, so state them deliberately.

        Args:
            underlying: e.g. "SPY"
            strategy: e.g. "long_call", "bull_put_spread"
            legs: one dict per leg, each with "symbol" (OCC), "side", "qty"
            thesis: one or two sentences - why, and what invalidates it
            confidence: your honest probability (0.0-1.0) that this position
                closes profitable. This is scored: over time your stated
                confidence is compared against how often you were actually
                right (Brier/Murphy calibration). Saying 0.9 on everything
                will be detected as overconfidence, and a well-calibrated
                0.55 is worth more than an inflated 0.9. Be honest, not
                optimistic.
            expiry: option expiry as YYYY-MM-DD
            stop_loss_pct: close at this loss, as a negative percent. **Percent
                OF THE NET DEBIT PAID OR CREDIT RECEIVED**, the way a broker
                quotes position P&L - not of the notional. On a debit spread
                -100% is the whole premium, so any tighter stop is a fraction
                of it; on a credit spread -100% means giving back the entire
                credit, and the classic stop is -200% (twice the credit).
                A stop that needs a bigger loss than the structure can produce
                will never fire, and this tool says so if you write one.
            profit_target_pct: close at this gain, same base. On a credit
                spread +50% is the standard "buy it back for half the credit";
                note that a credit spread's max profit IS the credit, so a
                target above +100% can never fire.
            time_stop_days_before_expiry: close this many days before expiry.
                Defaults are not neutral here: if you write NO time stop, an
                implicit one closes the position 1 day before expiry - the
                gamma wall, where delta flips on a small move and short-dated
                premium stops behaving like the position you opened. Write
                your own to override it, and write 0 if you genuinely mean to
                hold to expiry.
            underlying_stop_below: close if the UNDERLYING trades below this
                price - your thesis-invalidation level. Prefer this to
                stop_loss_pct for spreads: the underlying prints cleanly,
                the option mark is bid/ask noise.
            underlying_stop_above: same, for bearish theses.
            max_loss_usd: the position's TOTAL defined max loss in dollars
                (contracts x per-contract max loss, from simulate/size).
                Feeds the portfolio risk cap.
        """
        rules: list[dict[str, Any]] = []
        if stop_loss_pct is not None:
            rules.append({"type": "stop_loss", "basis": "position_mark", "threshold": f"{stop_loss_pct}%"})
        if profit_target_pct is not None:
            rules.append({"type": "profit_target", "basis": "position_mark", "threshold": f"{profit_target_pct}%"})
        if time_stop_days_before_expiry is not None:
            rules.append({"type": "time_stop", "days_before_expiry": time_stop_days_before_expiry})
        if underlying_stop_below is not None:
            rules.append({"type": "underlying_stop", "direction": "below", "level": underlying_stop_below})
        if underlying_stop_above is not None:
            rules.append({"type": "underlying_stop", "direction": "above", "level": underlying_stop_above})

        # SHARED LEGS (D-111). The broker aggregates holdings BY SYMBOL, and
        # `analytics.by_symbol` keys on symbol, so two position pages sharing an
        # OCC leg both read ONE aggregated broker row: the mark-based stop on
        # each divides by a net cost that includes the other's contracts, and
        # when the aggregate's short credit approaches the long debit the base
        # is refused as unreadable and BOTH stops go permanently unobservable.
        # Reachable now at six concurrent positions. Reported, never refused:
        # the order has already filled, and an unrecorded fill is an orphan.
        # `_render_positions` lists every held leg in the prompt, so the agent
        # can avoid this; `trdrbot health` names both pages when it does not.
        _held = {sym: p.position_id for p in store.open_positions() for sym in p.symbols}
        _shared = sorted({l.get("symbol", "") for l in legs} & set(_held))
        if _shared:
            journal_note = (f"WARNING: leg(s) {', '.join(_shared)} are already held by "
                            f"{', '.join(sorted({_held[x] for x in _shared}))}. The broker "
                            f"aggregates by symbol, so the mark-based stops on BOTH "
                            f"positions now read a shared, fabricated cost base. Prefer "
                            f"different strikes or expiries on a name you already hold.")
            if journal is not None:
                try:
                    journal.append("leg_overlap", legs=_shared,
                                   with_positions=sorted({_held[x] for x in _shared}))
                except Exception as exc:  # noqa: BLE001 - observability never breaks a trade
                    print(f"[record_position] journal append failed: {exc!r}")
        else:
            journal_note = ""
        pos = Position(
            position_id=ids.position_id(underlying, strategy),
            # `opening`, not `open`: the order is submitted, not confirmed
            # filled. Reconciliation promotes it once the broker shows the
            # legs. Claiming `open` here would make an unfilled limit order
            # look like real exposure, and exit rules would evaluate against a
            # position that does not exist.
            status="opening",
            strategy=strategy,
            underlying=underlying.upper(),
            opened=ids.utc_now().isoformat(),
            expiry=expiry,
            legs=legs,
            exit_rules=rules,
            thesis=thesis,
            decision_ref=decision_ref,
            # elfmem blocks recalled for THIS decision (INV-22, per-frame) -
            # the credit-assignment targets at resolution (D-011).
            elfmem_blocks=dict(elfmem_blocks or {}),
            generated_by=generated_by,
            # OKF sources (D-022): what the agent actually read this cycle,
            # so a resolved position can credit or discredit its inputs.
            sources=list(sources or []),
        )
        note = ""
        # Risk is DERIVED, not declared: prefer what size_position actually
        # computed this cycle, falling back to the model's own figure only if
        # sizing was skipped. Keeps the book caps honest without depending on
        # the model remembering a field.
        sized = shared.sizing if shared else None
        if sized is not None and sized.underlying in ("", underlying.upper()):
            pos.max_loss_usd = float(sized.max_loss_usd)
            # ...and say so when the two disagree. `max_loss_usd` above is
            # sizing's contract count times sizing's per-contract risk, so
            # recording a DIFFERENT quantity silently denominates the book caps
            # in a size that was never traded. Reported, never refused (D-009):
            # the agent may deliberately take a different size, and this is its
            # own two tool calls being held against each other, not a policy
            # imposed on either. Reconcile reprices from the fill regardless
            # (I-59), so the caps are protected either way - this exists to
            # make the INTENT gap visible while it is still explicable.
            recorded_qtys = sorted({q for q in (_leg_qty(l) for l in legs) if q > 0})
            if recorded_qtys and recorded_qtys != [sized.contracts]:
                if journal is not None:
                    journal.append("sizing_mismatch", position_id=pos.position_id,
                                   underlying=sized.underlying,
                                   sized_contracts=sized.contracts,
                                   recorded_qtys=recorded_qtys)
                note += (
                    f" NOTE: size_position computed {sized.contracts} contract(s) for this "
                    f"trade; the legs recorded here carry {recorded_qtys}. Recorded as given "
                    f"- but the book caps were sized against {sized.contracts}, so if the "
                    f"quantity was deliberate, re-run size_position to re-derive the risk."
                )
        elif max_loss_usd is not None:
            pos.max_loss_usd = float(max_loss_usd)

        # WHICH simulated structure was actually traded, matched on legs so
        # nothing is re-declared (D-037). Computed once, here, because two
        # separate things need it: the per-leg IVs below, and the exit-rule
        # reachability warnings further down.
        traded = [optmath.Leg.from_position_leg(leg) for leg in legs]
        traded_key = (_legs_key([(t.right, t.strike, t.side) for t in traded if t])
                      if legs and all(traded) else ())
        matched = next((st for st in (shared.structures if shared else [])
                        if st.key == traded_key and st.qty), None)

        # The skew the agent OBSERVED, carried onto the recorded legs. Without
        # it every greek computed after entry - these, and the book-greeks line
        # read every cycle afterwards - falls back to one flat vol even for a
        # position deliberately built from a skewed board, while the pre-trade
        # EV/POP layer has been skew-aware since WU-4.8. `net_greeks` honours
        # per-leg IV; this is what finally gives it one (I-50).
        if matched and matched.leg_ivs:
            for leg, t in zip(legs, traded):
                if t is None:
                    continue
                iv = matched.leg_ivs.get(_legs_key([(t.right, t.strike, t.side)]))
                if iv is not None:
                    leg["iv_pct"] = round(iv * 100.0, 4)

        # Entry greeks, derived not declared (D-040): parse the executed OCC
        # legs, price them with the market params simulate_experiments stashed.
        # The judged story ("net delta X, theta Y - chosen because...") comes
        # from here, and so does the book-greeks context on later ticks.
        mkt = shared.market if shared else None
        if mkt is not None:
            occ_legs = []
            for leg in legs:
                parsed = optmath.Leg.from_position_leg(leg)
                if parsed is None:
                    occ_legs = []
                    break
                occ_legs.append(parsed)
            g = optmath.net_greeks(occ_legs, mkt.spot, mkt.iv, mkt.days) if occ_legs else None
            if g:
                pos.greeks_at_entry = {k: round(v, 2) for k, v in g.items()}
                pos.entry_iv = mkt.iv
                pos.entry_spot = mkt.spot

        # Carry the thesis onto the position so resolution can attribute the
        # outcome to the VIEW or the STRUCTURE rather than just to P&L. Found
        # live: the very first position ever opened went straight from
        # get_option_chain to place_option_order to record_position with
        # simulate_experiments never called in between, so `shared.thesis`
        # was never set and this position can NEVER be attributed - silently,
        # since nothing before this line noticed (D-038).
        th = shared.thesis if shared else None
        thesis_missing = th is None
        if th is not None:
            pos.thesis_claim = th.claim
            pos.thesis_horizon = th.horizon
            pos.thesis_band_low = th.band_low
            pos.thesis_band_high = th.band_high
            pos.thesis_drift = th.drift
            pos.thesis_vol_view = th.vol_view
        # Close the loop: mark the pre-registered thesis as traded, AND state
        # its probability - the agent's `confidence` is the same number
        # `size_position` sized against, and a thesis with money behind it is
        # the last one that should sit outside the calibration record (D-105).
        if ledger is not None and pos.thesis_horizon:
            try:
                ledger.mark_traded(pos.underlying, pos.thesis_horizon, pos.position_id,
                                   probability=confidence)
            except Exception as exc:  # noqa: BLE001
                print(f"[ledger] mark_traded failed: {exc!r}")
        path = store.save(pos)
        if shared is not None:
            shared.recorded_trades.append(RecordedTrade(
                position=pos, matched=matched, confidence=confidence,
                alternatives=[st for st in shared.structures if st is not matched],
            ))
        if calibration is not None:
            calibration.record(pos.position_id, confidence, pos.underlying)
        # Say exactly which signals are enforced. The failure this guards
        # against is a stated invalidation level that no rule actually
        # watches - visible here rather than discovered at a loss (D-037).
        from .exit_rules import watched_signals
        watching = watched_signals(pos)

        # Can the mark-based rules the agent just wrote actually fire? Matched
        # by LEGS against what simulate_experiments priced, so nothing is
        # re-declared and a mismatch simply skips the check.
        if matched is not None:
            st = matched
            scale = sum(int(l.get("qty", 1) or 1) for l in legs) / st.qty
            bad = _unreachable_rules(
                stop_loss_pct, profit_target_pct,
                (st.entry_cost or 0.0) * scale,
                (st.max_profit * scale) if st.max_profit is not None else None,
                (st.max_loss * scale) if st.max_loss is not None else None,
            )
            if bad:
                note += " WARNING - exit rule(s) that cannot trigger: " + "; ".join(bad) + "."
            # ...and the case one layer deeper: rules that parse, are watched,
            # and can never PRINT. Below MIN_NET_COST_SHARE of gross premium the
            # mark-based P&L base is refused as division by noise (correctly -
            # a spread whose legs nearly cancel has almost no net cost), so
            # every stop and target on the position holds forever. Nothing else
            # says so: `invalid_rules()` reads 0 because they parse, and
            # `watched_signals()` lists position_mark because they ARE watched
            # - they simply never observe anything (I-45).
            mark_rules = stop_loss_pct is not None or profit_target_pct is not None
            gross = (st.gross_premium or 0.0) * scale
            if mark_rules and gross > 0 and abs((st.entry_cost or 0.0) * scale) < (
                    MIN_NET_COST_SHARE * gross):
                note += (
                    f" WARNING - this structure's net cost is under "
                    f"{MIN_NET_COST_SHARE:.0%} of the ${gross:,.0f} gross premium traded, "
                    f"so position-mark P&L is refused as division by noise and your "
                    f"stop_loss/profit_target can NEVER fire, however far the position "
                    f"moves. Watch the underlying or the clock instead: add "
                    f"underlying_stop_below/_above at your invalidation level, or a "
                    f"time_stop."
                )
        # A stop that fires reliably, on the right signal, where nothing is left
        # to save. Needs no matched structure - it is payoff GEOMETRY, derived
        # from the OCC strikes on the legs just recorded, so it still speaks
        # when simulate_experiments was skipped.
        for late in _late_underlying_stops(legs, underlying_stop_below, underlying_stop_above):
            note += f" WARNING - {late}."

        stale_view = _horizon_outlives_expiry(pos.thesis_horizon, expiry)
        if stale_view:
            note += f" WARNING - {stale_view}."

        if thesis_missing:
            note += (
                " NOTE: no thesis on file - simulate_experiments was not called "
                "(or not before this), so this position can NEVER be scored for "
                "view-vs-structure learning. Call simulate_experiments before "
                "record_position next time."
            )
        if "underlying" not in watching:
            note += (
                " NOTE: no underlying_stop - your exit rules watch only "
                f"{', '.join(watching) or 'nothing'}, so a thesis break in the "
                "underlying will not close this position. Add "
                "underlying_stop_below/_above at your invalidation level if you "
                "stated one."
            )
        risk = f" risk ${pos.max_loss_usd:,.0f}" if pos.max_loss_usd else ""
        if pos.greeks_at_entry:
            ge = pos.greeks_at_entry
            risk += (f"; entry greeks delta ${ge['delta_dollars']:+,.0f}, "
                     f"theta ${ge['theta_dollars']:+,.0f}/day, vega ${ge['vega_dollars']:+,.0f}/IVpt")
        return (
            (journal_note + "\n" if journal_note else "")
            + f"Recorded {pos.position_id} with {len(rules)} exit rule(s) at {path.name}, "
            f"confidence {confidence:.0%} (scored for calibration at close),{risk}. "
            f"Watching: {', '.join(watching) or 'no signals'}. "
            f"Exit rules are evaluated automatically every tick.{note}"
        )

    return StructuredTool.from_function(
        func=record_position,
        name="record_position",
        description=record_position.__doc__,
    )


#: How close two risk/reward ratios must be to be the same structure. Loose
#: enough for the model's rounding of the figures it read off the comparison,
#: tight enough that two genuinely different candidates on one board do not
#: collide - a condor at 0.59 and a put spread at 0.19 are nowhere near this.
RR_MATCH_TOLERANCE = 0.02


def _match_structure(shared: SharedContext | None, max_profit: float | None,
                     max_loss: float, name: str = "") -> SimStructure | str:
    """The simulated structure being sized - or the REFUSAL that replaces it.

    **A str is a refusal**, the convention `_vacuity_check` and every tool guard
    here already use. That is the whole change (I-40): this used to return the
    payoff ratio or None, and None meant four different things -

        nothing was simulated                    | no conditional payoff exists
        no unique match                          | we do not know WHICH payoff
        the match's own payoff_ratio was None    | friction ate the expected win
        a direct caller supplied nothing         | not this tool's case at all

    - which `sizing.size_position` then treated identically, falling back to
    max/max **with no friction at all**. D-079 had just made the gate open
    exactly where EV-after-costs turns positive; this seam dropped the cost view
    one layer later, and the structures friction punishes most are the ones the
    fallback flatters most. Measured on a fair-priced 99/100-101/102 condor at a
    claimed 70%: refused under the friction-charged conditional ratio (b 0.26,
    gate needs 79%), sized **224 contracts - 4.99% of equity, the per-position
    cap** - under the fallback (b 3.49, gate needs 22%).

    Matching is by NAME first - the names are echoed to the model in
    `render_comparison`, so it can give one, and that is exact. R:R is the
    fallback because it is SCALE-INVARIANT: the model quotes per-contract
    figures while `simulate` priced whatever quantity the legs carried, so
    matching on dollars would fail on every multi-lot candidate. Ambiguity
    refuses rather than guessing; a wrong `b` is worse than no trade.
    """
    structures = shared.structures if shared else []
    if not structures:
        return (
            "REFUSED: nothing usable has been simulated this cycle, so this "
            "structure has no conditional payoff and no friction estimate to be "
            "sized against. Call simulate_experiments first. (Sizing on max "
            "profit over max loss pairs a tail ratio with a whole-region "
            "probability and charges no costs - that combination is how a "
            "structure priced as unaffordable gets sized at the position cap.)"
        )

    match: SimStructure | None = None
    if name:
        named = [s for s in structures if s.name == name]
        if len(named) == 1:
            match = named[0]
    if match is None and max_profit is not None and max_loss:
        want = abs(max_profit / max_loss)
        hits = [s for s in structures if s.rr is not None
                and abs(s.rr - want) <= RR_MATCH_TOLERANCE]
        if len(hits) == 1:
            match = hits[0]
    if match is None:
        known = ", ".join(sorted(s.name for s in structures))
        return (
            f"REFUSED: this does not match anything simulated this cycle. Pass "
            f"structure_name exactly as it appeared in the comparison - one of: "
            f"{known}. Inferring the match from the risk/reward ratio cannot tell "
            f"two candidates apart when they share one, and a structure with an "
            f"unbounded max profit has no ratio to infer from at all."
        )
    if match.payoff_ratio is None:
        return (
            f"REFUSED: '{match.name}' has no usable conditional payoff. Its entire "
            f"expected win is eaten by the round-trip friction, or it wins (or "
            f"loses) so one-sidedly that there is no side to condition on - see "
            f"its row in the comparison. There is no payoff left to bet on, so "
            f"not trading it is the answer, not sizing it smaller."
        )
    return match


def _journal_sizing(journal: Any, **fields: Any) -> None:
    """Record what sizing actually did. Never blocks a decision (same guard as
    the ledger calls). Feeds `sizing.refused_rate` - a rising refusal share is
    the I-40 class resurfacing in production, where nothing else would show it.
    """
    if journal is None:
        return
    try:
        journal.append("sizing", **fields)
    except Exception as exc:  # noqa: BLE001 - observability never breaks a trade
        print(f"[sizing] journal append failed: {exc!r}")


def build_size_position(
    calibration: CalibrationStore, equity: float | None,
    open_risk_usd: float = 0.0,
    open_risk_by_underlying: dict[str, float] | None = None,
    shared: SharedContext | None = None,
    posture: Any = None,
    extra_forecasts: list[Any] | None = None,
    journal: Any = None,
) -> StructuredTool:
    """Tool: how many contracts, given edge, bankroll, and earned trust.

    Sizing used to be the model's free choice, which made every other piece of
    machinery decorative - a perfectly reasoned trade at a reckless size is a
    reckless trade. This puts size on Kelly, scaled by how well the agent's
    stated probabilities have actually held up.
    """

    def size_position(
        stated_confidence: float,
        max_profit: float,
        max_loss: float,
        underlying: str = "",
        structure_name: str = "",
    ) -> str:
        """Compute the defensible position size. Call this BEFORE placing an order.

        Size is derived from your edge and your TRACK RECORD, not chosen. Your
        stated confidence is shrunk toward the base rate according to how well
        calibrated you have actually been - so overconfidence costs you size,
        and a demonstrated record earns it back. A result of 0 contracts means
        there is no defensible position here; that is a real answer.

        Args:
            stated_confidence: your honest probability (0-1) this closes profitable
            max_profit: from simulate_experiments (use a positive number)
            max_loss: from simulate_experiments (use a NEGATIVE number)
            underlying: the ticker, so per-name concentration is checked
            structure_name: the candidate's name from simulate_experiments,
                exactly as it appeared in the comparison table. GIVE IT: it
                matches this size to the structure that was actually priced.
                Without it the match is inferred from the risk/reward ratio,
                which cannot tell two candidates apart when they share one -
                and an ambiguous match is refused rather than guessed.

        Sizing needs a structure this cycle's simulate_experiments actually
        priced, because the conditional payoff and the friction estimate exist
        only there. If you have not simulated it, or the name does not match, or
        its expected win is entirely eaten by costs, this REFUSES - and that
        refusal is a real answer about the trade, not an error to route around.
        """
        # NO BANKROLL, NO SIZE (I-75). Every cap in this system - Kelly, the
        # book cap, the per-name cap, the exploration floor - is a FRACTION of
        # equity, so an unreadable account leaves nothing to take a fraction
        # of. The caller used to substitute a $100,000 constant, which sized 47
        # contracts against the 12 the real equity permitted. This is the sizer
        # declining to answer a question it has no input for, not a policy gate.
        if equity is None:
            _journal_sizing(journal, underlying=underlying.upper(), result="refused",
                            contracts=0, structure=structure_name,
                            reason="account unreadable - no bankroll to size against")
            return (
                "REFUSED: the account could not be read this tick, so there is no "
                "bankroll to size against and every cap here is a fraction of one. "
                "Do not open a position on this cycle; the account is re-read every "
                "tick and sizing will answer again as soon as it is readable."
            )
        match = _match_structure(shared, max_profit, max_loss, structure_name)
        if isinstance(match, str):
            _journal_sizing(journal, underlying=underlying.upper(), result="refused",
                            contracts=0, structure=structure_name, reason=match[:160])
            return match

        d = sizing.size_position(
            equity=equity,
            underlying=underlying,
            # ALWAYS the conditional ratio of the structure that was actually
            # priced, friction included. `_match_structure` refused above if it
            # could not identify one, so the max/max fallback inside
            # `sizing.size_position` is now unreachable from production (I-40).
            payoff_ratio=match.payoff_ratio,
            open_risk_usd=open_risk_usd,
            open_risk_by_underlying=open_risk_by_underlying,
            stated_confidence=stated_confidence,
            max_profit=max_profit,
            max_loss=max_loss,
            # The SAME calibration the competence ladder was assessed on.
            # `calibration.score()` with no argument counts only closed
            # positions, so sizing was shrinking confidence against one sample
            # while the tier that supplies its Kelly multiplier and book cap
            # had been computed on another - the ledger-inclusive one that
            # D-052 built precisely because position closes will never reach a
            # meaningful n. Two numbers called "your calibration", disagreeing,
            # inside one decision.
            calibration=calibration.score(extra_forecasts),
            posture=posture,
        )
        # The system now KNOWS this position's true worst case. Stashing it
        # here means record_position can fill max_loss_usd itself instead of
        # asking the model to re-declare a number it was just given - a
        # forgotten field would have silently counted the position as zero
        # risk and quietly loosened the book caps (D-037).
        if shared is not None and d.contracts > 0:
            shared.sizing = SizingStash(
                underlying=underlying.upper(), contracts=d.contracts,
                max_loss_usd=abs(max_loss) * d.contracts,
            )
        _journal_sizing(journal, underlying=underlying.upper(),
                        result="sized" if d.contracts > 0 else "no_position",
                        contracts=d.contracts, structure=structure_name,
                        fraction=round(d.fraction_of_equity, 5),
                        # WHICH limit set the number, not just what the number
                        # was (D-099). Without it a risk lever that moved an
                        # inert constraint looked identical to one that worked.
                        binding=d.binding,
                        payoff_ratio=match.payoff_ratio)
        return d.explain()

    return StructuredTool.from_function(
        func=size_position, name="size_position", description=size_position.__doc__
    )


#: A forecast whose band history almost always holds is uninformative - UNLESS
#: the model disagrees with history, which is exactly what makes it a claim.
#: Same threshold and same reasoning as the muse's adversarial gate, which
#: learned this the hard way: a naive ceiling rejected a stated 27% against a
#: 99% base, i.e. the single most interesting call it generated (D-060).
VACUITY_BASE = 0.90
VACUITY_AGREE = 0.25


def _vacuity_check(state_dir: Path | None, underlying: str, probability: float,
                   horizon: str, band_low: float | None, band_high: float | None) -> str | None:
    """Refuse a forecast that history says is a near-certainty and the model agrees with.

    Calibration gates SIZE (competence.min_n), so every recorded forecast is a
    claim on real risk budget. Without this, "SPY between 0 and 10000 next
    Tuesday" is a scoreable forecast that resolves true, counts toward
    `resolved`, and walks the agent up the size ladder on evidence of nothing.
    That is not a hypothetical: the ladder's only n-gate is a COUNT, so
    inflating the count is the cheapest possible way to earn size dishonestly,
    and nothing else in the system would have noticed (D-070).

    Fails OPEN, deliberately: no persisted history means no anchor, and an
    invented judgement is worse than an unguarded one - the same rule
    `_plausible_band` follows when it has no spot to judge against.
    """
    if state_dir is None or (band_low is None and band_high is None):
        return None
    try:
        closes = market_stats.load_closes(state_dir, underlying)
        if not closes or len(closes) < 60:
            return None
        days = (date.fromisoformat(horizon) - ids.market_today()).days
        if days <= 0 or days > 30:
            return None  # horizon sanity is scored elsewhere; not this gate's job
        factors = market_stats.bootstrap_factors(closes, days, seed=f"forecast|{underlying}")
        if not factors:
            return None
        spot = closes[-1]
        held = sum(1 for f in factors
                   if (band_low is None or spot * f >= band_low)
                   and (band_high is None or spot * f <= band_high))
        base = held / len(factors)
    except Exception:  # noqa: BLE001 - a guard that crashes is worse than no guard
        return None

    if base >= VACUITY_BASE and abs(probability - base) < VACUITY_AGREE:
        return (
            f"REFUSED: uninformative. History says that band holds {base:.0%} of the time "
            f"over {days}d and you said {probability:.0%} - you are agreeing with the base "
            f"rate, so this scores as 'right' without testing any judgement, while still "
            f"counting toward the calibration that earns size. Tighten the band until it "
            f"is genuinely uncertain, or state a probability that actually disagrees with "
            f"history and say why."
        )
    return None


#: The model-facing metric names, mapped to the ledger's wire values. Two
#: vocabularies on purpose: the tool argument is what an agent would naturally
#: write, the stored value says its units out loud so a reader of the ledger
#: file cannot mistake a vol band for a price.
_METRICS = {"price": PRICE_BAND, "realized_vol": REALIZED_VOL_PCT}


def build_record_forecast(ledger: Any, state_dir: Path | None = None) -> StructuredTool:
    """Tool: put a view on the record without trading it.

    The cheapest evidence available to this agent. Size is gated on measured
    calibration, and calibration needs roughly 50 resolved forecasts to mean
    anything - a number trade-level observations will never reach at 1-5
    concurrent positions. A forecast on a setup you DECLINE costs nothing and
    scores exactly the same judgement.
    """

    def record_forecast(
        underlying: str,
        claim: str,
        probability: float,
        horizon: str,
        band_low: float | None = None,
        band_high: float | None = None,
        why: str = "",
        metric: str = "price",
    ) -> str:
        """Record a falsifiable prediction you are NOT trading.

        Use this every time you form a view and decline to act on it - a setup
        whose edge did not survive costs, a name you looked at and passed, a
        call on where something lands. It is scored exactly like a traded
        thesis and it moves your calibration record, which is what earns size.

        Args:
            underlying: ticker the prediction is about
            claim: the prediction in one sentence
            probability: your honest P(0-1) that the band holds at the horizon.
                Do not round to 0.5/0.75 - granularity matters, and rounding
                measurably degrades forecast accuracy.
            horizon: YYYY-MM-DD when this is judged. PREFER 1-3 DAYS OUT.
                A forecast only teaches you anything once it RESOLVES, and
                nothing you record can move your size until it has. Week-long
                horizons on a short operating window resolve after the point
                they could have changed a decision - one slow forecast is
                worth less than three fast ones, even though it feels more
                serious. Short horizons are also harder, which is the point:
                they test judgement rather than drift.
            band_low: holds only if the metric is >= this at the horizon
            band_high: holds only if the metric is <= this at the horizon.
                Give at least one, or it cannot be scored and will be refused.
                Make the band genuinely uncertain - one history almost always
                holds is refused as uninformative, because scoring 'right' on
                a near-certainty earns size without testing judgement.
            why: brief reasoning, for the record
            metric: what the band is about.
                'price' (default): band_low/band_high are prices at the horizon.
                'realized_vol': band_low/band_high bound the ANNUALIZED realized
                vol IN PERCENT over now -> horizon (e.g. 7.0/9.5 = "realized
                lands between 7% and 9.5%"). This is the claim your
                breakeven-vol comparison already makes in prose every cycle -
                recorded here, it is scored against the tape automatically and
                moves your calibration like any other forecast.
        """
        wanted = _METRICS.get(metric)
        if wanted is None:
            return (f"REFUSED: unknown metric {metric!r}. "
                    f"Use one of: {', '.join(sorted(_METRICS))}.")

        # The vacuity anchor is a bootstrap over the PRICE distribution, so it
        # can only judge a price band. A vol analogue is future work; until it
        # exists, a vol claim is unguarded rather than judged by the wrong
        # ruler - the same fail-open rule this check already follows when it
        # has no history at all.
        if wanted == PRICE_BAND:
            vacuous = _vacuity_check(state_dir, underlying, probability,
                                     horizon, band_low, band_high)
            if vacuous:
                return vacuous

        e = ledger.register(
            kind=STANDALONE, underlying=underlying, claim=claim,
            probability=probability, horizon=horizon,
            band_low=band_low, band_high=band_high, notes=why, metric=wanted,
        )
        if e is None:
            return ("REFUSED: no band given, so this could never be scored. "
                    "Give band_low and/or band_high.")
        units = "%" if e.metric == REALIZED_VOL_PCT else ""
        what = "realized vol" if e.metric == REALIZED_VOL_PCT else "price"
        return (f"Recorded forecast {e.id} on {e.underlying}: {e.probability:.0%} that "
                f"{what} lands in [{e.band_low}{units}, {e.band_high}{units}] "
                f"on {e.horizon}. "
                f"It will be scored automatically and counts toward your calibration.")

    return StructuredTool.from_function(
        func=record_forecast, name="record_forecast",
        description=record_forecast.__doc__,
    )
