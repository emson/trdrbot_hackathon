"""F4 - housekeeping. Runs when the market is closed, not on every tick.

Two jobs relevant to stage 3: interim scoring (INV-24 - the actual fix for
"nothing resolves inside the competition window") and elfmem consolidation
(the only place dream() is allowed to run, per INV-10/23).
"""

from __future__ import annotations

from typing import Any

from . import attribution
from .analytics import Snapshot, position_pnl_fraction
from .config import Config
from .elfmem_adapter import ElfmemAdapter
from .journal import Journal
from .positions import PositionStore
from .wiki import Wiki

#: Interim scoring fires only when |unrealised P&L| first crosses one of
#: these. Below the first band a mark is indistinguishable from bid/ask
#: noise on a freshly opened spread, which is exactly what was being
#: learned from before.
#:
#: **FRACTIONS, not percents, because that is what `position_pnl_fraction` returns.**
#: These read 25.0 and 50.0 - i.e. +2500% and +5000% - so no position could
#: ever reach band 1 and interim scoring has been dead since the day the bands
#: were added. The journal proves it: eight `interim_outcome` rows, all from
#: 2026-08-26, none since, while `trdrbot health` kept reporting
#: "interim_scoring ran 8x, produced 8" off that historical total. The unit
#: test agreed with the constants (it passed -3, -12, -27 as PERCENTS) and the
#: production caller passed fractions, so both sides were internally consistent
#: and jointly wrong - which is why 156 green tests said nothing about it.
INTERIM_BANDS = (0.25, 0.50)


def _materiality_band(pnl_fraction: float) -> int:
    """0 = not material yet; 1 and 2 = successively larger real moves.

    The argument is a FRACTION of net entry cost (0.25 = a 25% move), the same
    unit `analytics.position_pnl_fraction` returns - and the name now says so.
    It read `pnl_pct` while the constants beside it were percentages, which is
    exactly the collision that shipped interim scoring dead on arrival: the
    bands read 25.0/50.0 against a fraction input, so no position could ever
    reach band 1 (D-074).
    """
    mag = abs(pnl_fraction)
    band = 0
    for i, threshold in enumerate(INTERIM_BANDS, start=1):
        if mag >= threshold:
            band = i
    return band


async def run(
    store: PositionStore, snap: Snapshot, mem: ElfmemAdapter, wiki: Wiki, journal: Journal,
    config: Config, *, tools: dict[str, Any] | None = None, verbose: bool = True,
) -> dict[str, int]:
    """Closed-market work. `config` is PASSED, not re-loaded.

    This used to call `config.load(quiet=True)` three times per run, and each
    call re-runs `load_dotenv(override=True)` and re-mkdirs every path. Worse
    than the cost: the run loop captures its config once at startup, so an
    edit to config.yaml mid-run left housekeeping reading the new file while
    everything else ran on the old one - two live configurations, with nothing
    saying so.
    """
    interim_scored = 0
    interim_eligible = 0

    for pos in store.open_positions():
        if pos.status != "open" or not pos.all_elfmem_block_ids:
            continue
        pnl = position_pnl_fraction(pos.symbols, snap)
        if pnl is None:
            continue
        interim_eligible += 1
        # Score only on FIRST entry into a materiality band, never once per
        # cycle. The per-event weight was always low (0.1); repetition was the
        # hole. Found live: one unresolved position accumulated EIGHT interim
        # scores - 0.8 of cumulative evidence, approaching the 1.0 of a real
        # resolution - all scored hit=False from a -$45 mark that was bid/ask
        # noise on a fresh spread whose thesis was intact and whose underlying
        # sat 1.5% clear of the short strike. The loop was busy learning that
        # a good position was bad, from spread noise, eight times over.
        #
        # Bands are monotonic and one-way: a position contributes at most two
        # interim signals, each earned by a move large enough not to be
        # noise, and a mark oscillating around a threshold cannot re-fire.
        band = _materiality_band(pnl)
        if band <= pos.interim_band:
            continue
        pos.interim_band = band
        store.save(pos)

        # Low weight (D-018 #1/INV-24): a signal on an UNREALISED, still-
        # fluctuating position, not a true resolution. Exists so the learning
        # loop turns at all inside an 8-day window where most positions won't
        # fully resolve - not to substitute for resolution. Narrower signal
        # (0.7/0.3, not resolution's 0.9/0.1) reflects that lower certainty.
        #
        # This is now the ONLY place a money-derived signal reaches a block,
        # and it stays deliberately (D-091 removed the one at close). The
        # distinction is what evidence exists yet: an OPEN position has no
        # verdict available and never will until its horizon, so a low-weight
        # mark is the only signal there is. A CLOSED one is different -
        # attribution IS coming, so crediting on the money first would just
        # pre-empt the verdict with the number the verdict exists to overrule.
        signal = 0.7 if pnl > 0 else 0.3
        await mem.resolve(pos, hit=pnl > 0, signal=signal, weight=0.1, interim=True)
        journal.append(
            "interim_outcome", position_id=pos.position_id, pnl_pct=pnl,
            weight=0.1, band=band,
        )
        interim_scored += 1

    # Heartbeat, same shape as `attribution_run` and for the same reason: the
    # interim probe used to read the `interim_outcome` rows themselves, so
    # "ran" and "produced" were the SAME rows and the check was a tautology -
    # it could only ever say "never ran" or "ran Nx, produced N". Interim
    # scoring died the day the materiality bands were added and health went on
    # reporting "ran 8x, produced 8" off eight rows written before that, for
    # two days and ~250 ticks. A subsystem that worked once and then stopped
    # must not read as healthy forever.
    journal.append("interim_run", eligible=interim_eligible, scored=interim_scored)

    # Daily research cycle (D-032): regime + dossiers + opportunities. Once
    # per calendar day - it costs an LLM call and regime does not move hourly.
    if tools:
        from . import research
        # The cadence (once a day, never Saturday) lives in `research.run`
        # now, so `trdrbot research` inherits it too - it used to bypass both
        # the marker and the weekday gate (D-092).
        try:
            from .inbox import Inbox as _Inbox
            inbox = _Inbox(config.paths, max_retries=config.max_retries)
            r = await research.run(tools, config, inbox, wiki, journal, verbose=verbose)
            if verbose and not r.get("skipped"):
                print(f"[housekeeping] research: {r['opportunities']} opportunities")
        except Exception as exc:  # noqa: BLE001 - research is advisory (INV-8)
            print(f"[housekeeping] research failed, continuing: {exc!r}")

    # Resolve matured forecasts against the tape (D-052). This is where the
    # cheap evidence lands: theses we DECLINED get scored exactly like traded
    # ones, and they are the only realistic route to a calibration sample large
    # enough to mean anything.
    forecasts_resolved = 0
    if tools:
        from . import ids as _i
        from . import ledger as _ledger
        from .attribution import _spot
        book = _ledger.Ledger(config.paths.state / "ledger.jsonl")
        due = book.matured_unresolved()
        for e in due:
            spot = await _spot(tools, e.underlying)
            if spot is None:
                continue  # never guess the price; try again next cycle
            done = book.resolve(e.id, spot, _i.utc_now().isoformat())
            if done:
                forecasts_resolved += 1
                journal.append(
                    "forecast_resolved", entry_id=e.id, underlying=e.underlying,
                    traded=e.traded, stated=e.probability, held=done.outcome,
                    price_at_horizon=spot,
                )
        if due:
            journal.append("forecast_run", due=len(due), resolved=forecasts_resolved,
                           skipped_no_price=len(due) - forecasts_resolved)

    # Attribute any thesis whose horizon has now arrived (view vs structure).
    attributed = 0
    if tools:
        attributed = (await attribution.run(store, tools, mem, wiki, journal,
                                            verbose=verbose))["attributed"]

    # Wiki lifecycle sweep. Tombstones expired dossiers in place - never
    # deletes, never moves - and never touches a ticker we are actually holding,
    # because a position outlives the research cadence and the page explaining
    # why we are in a trade is the worst possible thing to retire mid-trade.
    swept: dict[str, list[str]] = {"deprecated": [], "protected": []}
    try:
        held = {f"research/{p.underlying.upper()}"
                for p in store.open_positions() if p.underlying}
        swept = wiki.sweep(protected=held)
        if swept["deprecated"]:
            journal.append("wiki_sweep", deprecated=swept["deprecated"],
                           protected=swept["protected"])
    except Exception as exc:  # noqa: BLE001 - housekeeping is advisory (INV-8)
        print(f"[housekeeping] wiki sweep failed, continuing: {exc!r}")

    # The Coach's overnight pulse (D-088): snapshot gauges, check sentinels,
    # settle any experiment whose evidence is in, and open the next one. It is
    # also pulsed straight after every muse run, because housekeeping only runs
    # while the market is CLOSED and the muse only runs while it is OPEN - so
    # this call alone would defer every promotion to the following night.
    coached: dict[str, Any] = {}
    try:
        from . import coach
        coach.reconcile(config)
        coached = await coach.pulse(config, journal,
                                                                        verbose=verbose)
    except Exception as exc:  # noqa: BLE001 - the Coach is advisory (INV-8)
        print(f"[housekeeping] coach pulse failed, continuing: {exc!r}")

    dreamed = await mem.housekeeping_dream()

    wiki.append_log(
        f"housekeeping: {interim_scored} interim score(s), "
        f"consolidation {'ok' if dreamed else 'skipped (see log)'}, "
        f"{attributed} attribution(s), "
        f"{len(swept['deprecated'])} concept(s) tombstoned"
    )
    if verbose:
        print(f"[housekeeping] interim_scored={interim_scored} dream_ok={dreamed}")

    return {"interim_scored": interim_scored, "dream_ok": dreamed, "attributed": attributed,
            "forecasts_resolved": forecasts_resolved,
            "wiki_deprecated": len(swept["deprecated"]),
            "coach_experiments_open": int(coached.get("experiments_open") or 0)}
