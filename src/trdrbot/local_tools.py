"""Local LangGraph tools (D-016 - local capability is a tool, not an MCP server).

`record_position` is the bridge from the model's prose to machine-readable
state. Without it the agent states a stop-loss in a sentence and nothing can
act on it; with it, the exit-rule evaluator has something deterministic to
check every 60 seconds.

This is why the agent is *required* to call it after opening a position: an
exit rule that exists only in prose is not an exit rule.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from pathlib import Path

from . import experiments, ids, market_stats, optmath, sizing
from .calibration import CalibrationStore
from .ledger import STANDALONE
from .positions import Position, PositionStore


def build_simulate_experiments(shared: dict[str, Any], state_dir: "Path | None" = None,
                               ledger: "Any" = None) -> StructuredTool:
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
        if state_dir is not None:
            closes = market_stats.load_closes(state_dir, underlying)
            if closes:
                factors = market_stats.bootstrap_factors(
                    closes, days_to_expiry, seed=underlying, drift=drift_pct / 100.0
                ) or None
        results = [
            (e, experiments.simulate(e, thesis, spot, iv_pct / 100.0, days_to_expiry,
                                     terminal_factors=factors, friction_usd=fr))
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
                    probability=0.5, horizon=horizon,
                    band_low=band_low, band_high=band_high,
                    notes=f"{len(built)} structures simulated",
                )
            except Exception as exc:  # noqa: BLE001 - never block a decision
                print(f"[ledger] register failed: {exc!r}")
        shared["thesis"] = thesis
        # Market params of this simulation - record_position derives the
        # entry greeks from these, same derive-not-declare pattern as sizing.
        shared["market"] = {"spot": spot, "iv": iv_pct / 100.0, "days": days_to_expiry}
        shared["ranked"] = [(e.name, m) for e, m in ranked]
        return experiments.render_comparison(thesis, ranked)

    return StructuredTool.from_function(
        func=simulate_experiments,
        name="simulate_experiments",
        description=simulate_experiments.__doc__,
    )


def build_record_position(
    store: PositionStore,
    decision_ref: str,
    *,
    elfmem_blocks: dict[str, list[str]] | None = None,
    generated_by: str = "",
    calibration: "CalibrationStore | None" = None,
    sources: list[dict[str, Any]] | None = None,
    shared: dict[str, Any] | None = None,
    ledger: Any = None,
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
            stop_loss_pct: close at this loss, as a negative percent (-50 = -50%)
            profit_target_pct: close at this gain, as a percent (50 = +50%)
            time_stop_days_before_expiry: close this many days before expiry
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
        # Risk is DERIVED, not declared: prefer what size_position actually
        # computed this cycle, falling back to the model's own figure only if
        # sizing was skipped. Keeps the book caps honest without depending on
        # the model remembering a field.
        sized = (shared or {}).get("sizing") or {}
        if sized.get("max_loss_usd") is not None and (
            not sized.get("underlying") or sized["underlying"] == underlying.upper()
        ):
            pos.max_loss_usd = float(sized["max_loss_usd"])
        elif max_loss_usd is not None:
            pos.max_loss_usd = float(max_loss_usd)

        # Entry greeks, derived not declared (D-040): parse the executed OCC
        # legs, price them with the market params simulate_experiments stashed.
        # The judged story ("net delta X, theta Y - chosen because...") comes
        # from here, and so does the book-greeks context on later ticks.
        mkt = (shared or {}).get("market") or {}
        if mkt:
            occ_legs = []
            for l in legs:
                o = optmath.parse_occ(str(l.get("symbol", "")))
                if o is None:
                    occ_legs = []
                    break
                occ_legs.append(optmath.Leg(
                    right=o["right"], strike=o["strike"],
                    side="long" if str(l.get("side", "")).lower() in ("long", "buy") else "short",
                    qty=int(l.get("qty", 1) or 1), price=0.0,
                ))
            g = optmath.net_greeks(occ_legs, mkt["spot"], mkt["iv"], mkt["days"]) if occ_legs else None
            if g:
                pos.greeks_at_entry = {k: round(v, 2) for k, v in g.items()}
                pos.entry_iv = mkt["iv"]
                pos.entry_spot = mkt["spot"]

        # Carry the thesis onto the position so resolution can attribute the
        # outcome to the VIEW or the STRUCTURE rather than just to P&L. Found
        # live: the very first position ever opened went straight from
        # get_option_chain to place_option_order to record_position with
        # simulate_experiments never called in between, so `shared["thesis"]`
        # was never set and this position can NEVER be attributed - silently,
        # since nothing before this line noticed (D-038).
        th = (shared or {}).get("thesis")
        thesis_missing = th is None
        if th is not None:
            pos.thesis_claim = th.claim
            pos.thesis_horizon = th.horizon
            pos.thesis_band_low = th.band_low
            pos.thesis_band_high = th.band_high
            pos.thesis_drift = th.drift
        # Close the loop: mark the pre-registered thesis as traded, so the
        # ledger distinguishes ideas acted on from ideas declined.
        if ledger is not None and pos.thesis_horizon:
            try:
                ledger.mark_traded(pos.underlying, pos.thesis_horizon, pos.position_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[ledger] mark_traded failed: {exc!r}")
        path = store.save(pos)
        if calibration is not None:
            calibration.record(pos.position_id, confidence)
        # Say exactly which signals are enforced. The failure this guards
        # against is a stated invalidation level that no rule actually
        # watches - visible here rather than discovered at a loss (D-037).
        from .exit_rules import watched_signals
        watching = watched_signals(pos)
        note = ""
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
            f"Recorded {pos.position_id} with {len(rules)} exit rule(s) at {path.name}, "
            f"confidence {confidence:.0%} (scored for calibration at close),{risk}. "
            f"Watching: {', '.join(watching) or 'no signals'}. "
            f"Exit rules are evaluated automatically every tick.{note}"
        )

    return StructuredTool.from_function(
        func=record_position,
        name="record_position",
        description=record_position.__doc__,
    )


def build_size_position(
    calibration: "CalibrationStore", equity: float, open_count: int,
    open_risk_usd: float = 0.0,
    open_risk_by_underlying: dict[str, float] | None = None,
    shared: dict[str, Any] | None = None,
    posture: Any = None,
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
        """
        d = sizing.size_position(
            equity=equity,
            underlying=underlying,
            open_risk_usd=open_risk_usd,
            open_risk_by_underlying=open_risk_by_underlying,
            stated_confidence=stated_confidence,
            max_profit=max_profit,
            max_loss=max_loss,
            calibration=calibration.score(),
            posture=posture,
        )
        # The system now KNOWS this position's true worst case. Stashing it
        # here means record_position can fill max_loss_usd itself instead of
        # asking the model to re-declare a number it was just given - a
        # forgotten field would have silently counted the position as zero
        # risk and quietly loosened the book caps (D-037).
        if shared is not None and d.contracts > 0:
            shared["sizing"] = {
                "underlying": underlying.upper(),
                "contracts": d.contracts,
                "max_loss_usd": abs(max_loss) * d.contracts,
            }
        return d.explain()

    return StructuredTool.from_function(
        func=size_position, name="size_position", description=size_position.__doc__
    )


def build_record_forecast(ledger: Any) -> StructuredTool:
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
            horizon: YYYY-MM-DD when this is judged
            band_low: holds only if price >= this at the horizon
            band_high: holds only if price <= this at the horizon.
                Give at least one, or it cannot be scored and will be refused.
            why: brief reasoning, for the record
        """
        e = ledger.register(
            kind=STANDALONE, underlying=underlying, claim=claim,
            probability=probability, horizon=horizon,
            band_low=band_low, band_high=band_high, notes=why,
        )
        if e is None:
            return ("REFUSED: no band given, so this could never be scored. "
                    "Give band_low and/or band_high.")
        return (f"Recorded forecast {e.id} on {e.underlying}: {e.probability:.0%} that "
                f"[{e.band_low}, {e.band_high}] holds on {e.horizon}. "
                f"It will be scored automatically and counts toward your calibration.")

    return StructuredTool.from_function(
        func=record_forecast, name="record_forecast",
        description=record_forecast.__doc__,
    )
