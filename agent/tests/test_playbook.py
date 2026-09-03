"""The playbook: structure choice as a Coach lever (notes/026).

Offline throughout. The chain is synthetic and priced at fair value on the
same lognormal grid the stack scores with, so a fair structure is fair BY
CONSTRUCTION and any preference the reward shows is the reward's own.
"""

from __future__ import annotations

import pytest

from trdrbot import optmath, playbook
from trdrbot.optmath import Leg, _lognormal_grid

SPOT, DAYS, IV = 100.0, 7.0, 0.25
EXPIRY = "2026-09-11"


def _fair(right: str, strike: float) -> float:
    grid = _lognormal_grid(SPOT, IV, DAYS)
    if right == "C":
        return sum(w * max(0.0, s - strike) for s, w in grid)
    return sum(w * max(0.0, strike - s) for s, w in grid)


def _chain(strikes: list[float] | None = None, *, spread: float = 0.10,
           unquoted: set[float] | None = None, iv: float | None = IV) -> playbook.Chain:
    """A synthetic chain: every strike, both rights, quoted around fair value."""
    strikes = strikes or [float(k) for k in range(80, 121)]
    quotes = []
    for k in strikes:
        for right in ("C", "P"):
            fair = _fair(right, k)
            # a real chain bids a cent for the far wings; a zero bid is a gate
            bid, ask = max(0.01, fair - spread / 2), fair + spread / 2
            if unquoted and k in unquoted:
                bid, ask = 0.0, 0.0
            occ = f"XYZ260911{right}{int(round(k * 1000)):08d}"
            quotes.append(playbook.Quote(occ=occ, right=right, strike=k, expiry=EXPIRY,
                                         bid=bid, ask=ask, iv=iv))
    return playbook.Chain(quotes=tuple(quotes))


def _leg(right: str, strike: float, side: str, qty: int = 1) -> Leg:
    return Leg(right=right, strike=strike, side=side, qty=qty, price=_fair(right, strike))


def _menu(band_low: float | None, band_high: float | None, catalogue: str = "") -> dict[str, dict]:
    """Instantiate the seed (or a given catalogue) for one thesis and evaluate
    every applicable family. {family: verdict}."""
    cat = playbook.parse_catalogue(catalogue or playbook.SEED_CATALOGUE)
    shape = playbook.shape_of(band_low, band_high, SPOT)
    assert shape is not None
    sigma = optmath.expected_move(SPOT, IV, DAYS)
    assert sigma is not None
    out: dict[str, dict] = {}
    for fam in cat.applicable(shape):
        inst = playbook.resolve_legs(fam, shape, spot=SPOT, sigma=sigma, band_low=band_low,
                                     band_high=band_high, chain=_chain(), expiry=EXPIRY)
        if isinstance(inst, str):
            out[fam.name] = {"fate": inst}
            continue
        out[fam.name] = playbook.evaluate(inst.legs, spot=SPOT, iv=IV, days=DAYS,
                                          band_low=band_low, band_high=band_high,
                                          friction_rt=inst.friction_rt)
    return out


# --- shapes -----------------------------------------------------------------


@pytest.mark.parametrize(("lo", "hi", "want"), [
    (98.0, 102.0, "range"), (100.0, 100.0, "range"),
    (103.0, 108.0, "bull_target"), (90.0, 96.0, "bear_target"),
    (98.0, None, "bull_floor"), (None, 102.0, "bear_ceiling"),
    (None, None, None),
])
def test_shape_of_derives_five_shapes_from_band_and_spot(lo, hi, want):
    assert playbook.shape_of(lo, hi, SPOT) == want


# --- the catalogue and its validator ---------------------------------------


def test_seed_catalogue_validates_and_every_family_is_bounded_on_every_declared_shape():
    assert playbook.validate_catalogue(playbook.SEED_CATALOGUE) == ""
    cat = playbook.parse_catalogue(playbook.SEED_CATALOGUE)
    for shape in playbook.SHAPES:
        assert cat.applicable(shape), f"the seed answers no {shape} claim"
    # ...and the same text, mutated the way the muse's challengers are, still
    # clears the generic validator with the playbook's own as its schema check
    from trdrbot import coach

    lever = coach.lever("playbook.catalogue")
    if lever is not None:  # registered from commit 3 onward
        assert coach.validate_prompt(
            playbook.SEED_CATALOGUE.replace("sigma: 1.0}}", "sigma: 1.25}}"),
            playbook.SEED_CATALOGUE, (), must_contain=lever.must_contain,
            kind="policy", validator=playbook.validate_catalogue) == ""


def _seed_with(**edits: str) -> str:
    text = playbook.SEED_CATALOGUE
    for old, new in edits.items():
        assert old in text, old
        text = text.replace(old, new)
    return text


@pytest.mark.parametrize(("text", "defect"), [
    # a naked short: drop the long wing of the put credit spread
    (_seed_with(**{"      - {right: P, side: long,  at: {anchor: band_low, sigma: -1.0}}\n": ""}),
     "between 2 and 4 legs"),
    # a naked short PUT: its loss is bounded at the strike, so the arithmetic
    # alone would pass it - the coverage rule is what refuses it
    (_seed_with(**{"- {right: P, side: long,  at: {anchor: band_low, sigma: -1.0}}":
                   "- {right: C, side: long,  at: {anchor: band_low, sigma: -1.0}}"}),
     "naked short"),
    (_seed_with(**{"shapes: [range]\n    legs:\n      - {right: P, side: short, at: {anchor: band_low,  sigma: 0.0}}":
                   "shapes: [sideways]\n    legs:\n      - {right: P, side: short, at: {anchor: band_low,  sigma: 0.0}}"}),
     "unknown shape"),
    (_seed_with(**{"sigma: 1.0}}": "sigma: 3.0}}"}), "outside +/-2.5"),
    (_seed_with(**{"shapes: [bull_target, bull_floor]": "shapes: [bull_target]",
                   "shapes: [bull_floor]": "shapes: [bull_target]"}),
     "no family covers the shape 'bull_floor'"),
    ("version: 1\nfamilies: []\n", "0 families"),
    (playbook.SEED_CATALOGUE.replace("name: bull_put_credit", "name: bull_call_debit"),
     "duplicate family name"),
    # band_mid on a one-sided claim has no value
    (_seed_with(**{"name: iron_butterfly\n    shapes: [range]": "name: iron_butterfly\n    shapes: [range, bull_floor]"}),
     "anchor band_mid does not exist"),
    # two legs of one right on one strike
    (_seed_with(**{"- {right: C, side: short, at: {anchor: spot, sigma: 1.0}}":
                   "- {right: C, side: short, at: {anchor: spot, sigma: 0.0}}"}),
     "degenerate"),
    ("families: [", "not valid YAML"),
])
def test_validate_catalogue_names_the_defect(text, defect):
    why = playbook.validate_catalogue(text)
    assert defect in why, why


def test_thirteen_families_is_too_many():
    cat = playbook.parse_catalogue(playbook.SEED_CATALOGUE)
    extra = "".join(
        f"  - name: extra_{i}\n    shapes: [range]\n    legs:\n"
        f"      - {{right: C, side: long,  at: {{anchor: spot, sigma: 0.0}}}}\n"
        f"      - {{right: C, side: short, at: {{anchor: spot, sigma: 1.0}}}}\n"
        for i in range(13 - len(cat.families)))
    assert "families - between 3 and 12" in playbook.validate_catalogue(
        playbook.SEED_CATALOGUE + extra)


# --- the reward --------------------------------------------------------------


def test_band_conditional_matches_an_independent_grid_computation():
    legs = [_leg("P", 96, "short"), _leg("P", 92, "long"),
            _leg("C", 104, "short"), _leg("C", 108, "long")]
    lo, hi = 98.0, 102.0
    grid = _lognormal_grid(SPOT, IV, DAYS)
    inside = [(s, w) for s, w in grid if lo <= s <= hi]
    outside = [(s, w) for s, w in grid if not lo <= s <= hi]
    w_in, w_out = sum(w for _, w in inside), sum(w for _, w in outside)
    want_e = sum(w * optmath.pnl_at(legs, s) for s, w in inside) / w_in
    want_ph = sum(w for s, w in inside if optmath.pnl_at(legs, s) > 0) / w_in
    want_pf = sum(w for s, w in outside if optmath.pnl_at(legs, s) > 0) / w_out

    bc = optmath.band_conditional(legs, SPOT, IV, DAYS, lo, hi)

    assert bc is not None
    assert bc.p_band == pytest.approx(w_in)
    assert bc.e_pnl_hold == pytest.approx(want_e)
    assert bc.p_profit_hold == pytest.approx(want_ph)
    assert bc.p_profit_fail == pytest.approx(want_pf)
    assert bc.edge == pytest.approx(want_ph - want_pf)
    assert optmath.band_conditional(legs, SPOT, IV, DAYS, None, None) is None


def test_reward_prefers_premium_on_ranges_and_verticals_on_directional_claims():
    """PILLAR-4 (learning integrity): the lever's reward must not carry a
    structural preference nobody chose. Pins RELATIONSHIPS from notes/026
    section 5, never levels: a spot-centred condor survives a range claim and
    is refused as indifferent on a target claim; a bull call debit survives
    the target claim and is refused as unfaithful on the range.

    Mutation-verified: with gates 4 and 5 disabled (`MIN_BAND_EDGE = -1` and
    the pays-when-it-holds check skipped) both refusals become `candidate` and
    this test fails - the revert was performed and observed before the test
    shipped (notes/026 commit 2).

    Note what is NOT asserted: the seed's condor placed by its own anchors on
    a [103,108] target band puts its shorts AT 103 and 108 - a condor whose
    profit zone IS the claim - and the reward rightly passes it. Faithfulness
    is a property of where the strikes sit, not of the family's name.
    """
    def verdict(legs: list[Leg], lo: float | None, hi: float | None) -> str:
        v = playbook.evaluate(legs, spot=SPOT, iv=IV, days=DAYS, band_low=lo, band_high=hi,
                              friction_rt=sum(0.10 * l.qty * 100 for l in legs))
        return str(v["fate"])

    condor = [_leg("P", 96, "short"), _leg("P", 92, "long"),
              _leg("C", 104, "short"), _leg("C", 108, "long")]
    debit = [_leg("C", 100, "long"), _leg("C", 105, "short")]
    narrow_range, target = (98.0, 102.0), (103.0, 108.0)

    assert verdict(condor, *narrow_range) == "candidate"
    assert verdict(condor, *target).startswith("rejected:"), verdict(condor, *target)
    assert verdict(debit, *target) == "candidate"
    assert verdict(debit, *narrow_range).startswith("rejected: pays $"), verdict(debit, *narrow_range)

    # ...and the seed, placed by its own anchors, answers every shape with at
    # least one survivor on a fair-value chain.
    for lo, hi in ((98.0, 102.0), (103.0, 108.0), (90.0, 96.0), (98.0, None), (None, 102.0)):
        menu = _menu(lo, hi)
        assert any(v["fate"] == "candidate" for v in menu.values()), (lo, hi, menu)


def test_tight_fly_narrower_than_the_band_is_rejected_for_paying_negative_when_it_holds():
    """The reward cannot be gamed by ever-tighter flies: a 99/100/101 fly
    under a [98, 102] claim loses money across most of the band it is meant
    to express, and gate 4 says so by name."""
    fly = [_leg("C", 99, "long"), _leg("C", 100, "short", 2), _leg("C", 101, "long")]
    v = playbook.evaluate(fly, spot=SPOT, iv=IV, days=DAYS, band_low=98.0, band_high=102.0,
                          friction_rt=sum(0.10 * l.qty * 100 for l in fly))
    assert v["fate"].startswith("rejected: pays $"), v
    assert v["e_hold"] < 0


def test_an_unbounded_loss_is_refused_before_any_conditional_is_computed():
    """Gate 3 is the sizer's own rule: an unbounded worst case cannot be
    sized. A naked short put is BOUNDED by that arithmetic (its strike), which
    is why the validator's coverage rule exists at the catalogue level."""
    v = playbook.evaluate([_leg("C", 104, "short")], spot=SPOT, iv=IV, days=DAYS,
                          band_low=98.0, band_high=None, friction_rt=10.0)
    assert v["fate"] == "rejected: unbounded loss" and "edge" not in v


def test_score_arm_scores_an_uncovered_shape_as_failures():
    """A catalogue with no family for a shape could not express the thesis -
    that is the variant's own doing, so it scores as `asked` failures rather
    than as an empty result nothing penalises (the muse's empty-reply rule)."""
    r = playbook.score_arm([], asked=3)
    assert r == {"candidates": 0, "survived": 0, "failed": 3, "fates": []}
    r = playbook.score_arm([{"fate": "candidate"}, {"fate": "rejected: unbounded loss"}], asked=2)
    assert r["survived"] == 1 and r["failed"] == 1


# --- instantiation on a chain -----------------------------------------------


def test_resolve_legs_snaps_to_listed_strikes_and_refuses_an_unquoted_one():
    cat = playbook.parse_catalogue(playbook.SEED_CATALOGUE)
    condor = next(f for f in cat.families if f.name == "iron_condor")
    sigma = optmath.expected_move(SPOT, IV, DAYS)
    coarse = _chain([80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0])
    inst = playbook.resolve_legs(condor, "range", spot=SPOT, sigma=sigma, band_low=97.7,
                                 band_high=102.3, chain=coarse, expiry=EXPIRY)
    assert not isinstance(inst, str), inst
    assert [(l.right, l.strike, l.side) for l in inst.legs] == [
        ("P", 100.0, "short"), ("P", 95.0, "long"), ("C", 100.0, "short"), ("C", 105.0, "long")]
    assert all(occ.startswith("XYZ260911") for occ in inst.occs)
    # four legs, each crossing one $0.10 spread, round trip
    assert inst.friction_rt == pytest.approx(4 * 0.10 * 100)

    # on the $1 grid the long put wing lands on 94 (97.7 - 1 sigma = 94.24)
    dead = playbook.resolve_legs(condor, "range", spot=SPOT, sigma=sigma, band_low=97.7,
                                 band_high=102.3, chain=_chain(unquoted={94.0}), expiry=EXPIRY)
    assert dead == "rejected: unquoted leg XYZ260911P00094000"


def test_resolve_legs_refuses_legs_that_collapse_onto_one_strike():
    cat = playbook.parse_catalogue(playbook.SEED_CATALOGUE)
    fly = next(f for f in cat.families if f.name == "call_butterfly")
    sigma = optmath.expected_move(SPOT, IV, DAYS)
    # a $10 strike grid under a $4-wide band: all three legs land on 100
    coarse = _chain([80.0, 90.0, 100.0, 110.0, 120.0])
    out = playbook.resolve_legs(fly, "range", spot=SPOT, sigma=sigma, band_low=98.0,
                                band_high=102.0, chain=coarse, expiry=EXPIRY)
    assert out == "rejected: degenerate - legs collapsed to one strike"


def test_chain_from_snapshots_reads_the_feeds_keys_and_drops_what_it_cannot_parse():
    snaps = {
        "SPY260911C00760000": {"latestQuote": {"bp": 1.2, "ap": 1.3}, "impliedVolatility": 0.18},
        "SPY260911P00755000": {"latestQuote": {"bp": 0.9, "ap": 1.0}, "implied_volatility": 0.21},
        "SPY260911P00750000": {"latestQuote": {"bp": 0.0, "ap": 0.0}},
        "not-an-occ": {"latestQuote": {"bp": 1, "ap": 2}},
    }
    chain = playbook.chain_from_snapshots(snaps)
    assert chain.expiries() == ["2026-09-11"]
    assert {q.occ for q in chain.quotes} == {"SPY260911C00760000", "SPY260911P00755000",
                                             "SPY260911P00750000"}
    assert chain.atm_iv("2026-09-11", 757.0) == pytest.approx((0.18 + 0.21) / 2)
    assert chain.nearest("2026-09-11", "P", 751.0).quoted is False
    assert playbook.chain_from_snapshots({"error": "no chain"}).quotes == ()


# --- naming ------------------------------------------------------------------


@pytest.mark.parametrize(("legs", "want"), [
    ([_leg("C", 100, "long"), _leg("C", 105, "short")], "bull_call_debit"),
    ([_leg("P", 100, "short"), _leg("P", 95, "long")], "bull_put_credit"),
    ([_leg("C", 100, "short"), _leg("C", 105, "long")], "bear_call_credit"),
    ([_leg("P", 100, "long"), _leg("P", 95, "short")], "bear_put_debit"),
    ([_leg("P", 95, "short"), _leg("P", 90, "long"), _leg("C", 105, "short"),
      _leg("C", 110, "long")], "iron_condor"),
    ([_leg("P", 100, "short"), _leg("C", 100, "short"), _leg("P", 95, "long"),
      _leg("C", 105, "long")], "iron_butterfly"),
    ([_leg("P", 95, "long"), _leg("P", 90, "short"), _leg("C", 105, "long"),
      _leg("C", 110, "short")], "reverse_iron_condor"),
    ([_leg("C", 95, "long"), _leg("C", 100, "short", 2), _leg("C", 105, "long")], "call_butterfly"),
    ([_leg("C", 100, "long"), _leg("P", 100, "long")], "long_straddle"),
    ([_leg("P", 95, "short"), _leg("C", 105, "short")], "short_strangle"),
    ([_leg("C", 100, "long")], "long_call"),
    ([_leg("C", 100, "long"), _leg("C", 105, "short", 2)], "ratio_spread"),
    ([_leg("C", 100, "long"), _leg("C", 105, "long")], "other"),
])
def test_classify_names_the_zoo(legs, want):
    assert playbook.classify(legs) == want


def test_leg_payload_round_trips_through_the_journal_shape():
    leg = Leg(right="C", strike=225.0, side="short", qty=2, price=1.35, expiry=EXPIRY, iv=0.38)
    row = playbook.leg_payload(leg, "NVDA260911C00225000")
    assert row["symbol"] == "NVDA260911C00225000" and row["iv_pct"] == 38.0
    back = playbook.legs_from_payload([row])[0]
    assert back == leg


# --- the hot path: attach, one board, two arms, one row -------------------

from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from conftest import days_out, journal_rows, tools_for  # noqa: E402

from trdrbot import coach  # noqa: E402
from trdrbot.journal import Journal  # noqa: E402
from trdrbot.opportunity import Opportunity, render_for_decide  # noqa: E402


def _cfg(tmp_path: Path) -> SimpleNamespace:
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        paths=SimpleNamespace(state=tmp_path / "state", data=tmp_path,
                              journal=tmp_path / "journal.jsonl"),
        coach={"enabled": True}, pricing={}, deadline=None)


def _snapshots(expiry: str, **chain_kw) -> dict:
    """The synthetic chain as the feed would hand it to `options_gate`."""
    ymd = expiry[2:4] + expiry[5:7] + expiry[8:10]
    snaps = {}
    for q in _chain(**chain_kw).quotes:
        occ = q.occ.replace("260911", ymd)
        snaps[occ] = {"latestQuote": {"bp": q.bid, "ap": q.ask}, "impliedVolatility": q.iv}
    return snaps


def _opp(lo: float | None, hi: float | None, horizon: str) -> Opportunity:
    return Opportunity(underlying="XYZ", claim="XYZ does a thing", horizon=horizon,
                       direction="neutral", band_low=lo, band_high=hi, why="because")


def _pair(cfg: SimpleNamespace, journal: Journal) -> None:
    """Open a paired experiment on the playbook lever, as the Coach would."""
    st = coach.load_state(cfg, "playbook.catalogue", playbook.SEED_CATALOGUE)
    challenger = playbook.SEED_CATALOGUE.replace("sigma: 1.0}}", "sigma: 1.25}}")
    assert playbook.validate_catalogue(challenger) == ""
    coach._open(cfg, st, coach.Variant("v1", challenger), journal)


@pytest.mark.asyncio
async def test_attach_shadow_arm_writes_nothing(tmp_path):
    """D-088's shadow rule, for the second lever: the challenger reaches
    `record_trial` and nothing else. One `playbook` row, one heartbeat, one
    trial with both arms - and the opportunity carries only the incumbent's
    menu."""
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    _pair(cfg, journal)
    expiry, horizon = days_out(8), days_out(5)
    tools = tools_for(get_option_chain=lambda **_: {"snapshots": _snapshots(expiry)})

    out = await playbook.attach(tools, cfg, journal, _opp(98.0, 102.0, horizon), source="muse",
                                spot=SPOT, chain=_snapshots(expiry))

    assert out.playbook is not None and out.playbook["shape"] == "range"
    assert out.playbook["variant"] == "v0"
    survivors = [c for c in out.playbook["candidates"] if c["fate"] == "candidate"]
    assert survivors and all(c["legs"] for c in survivors)
    rows = journal_rows(journal, "playbook")
    assert len(rows) == 1 and rows[0]["variant"] == "v0" and rows[0]["candidates"]
    beats = journal_rows(journal, "playbook_run")
    assert len(beats) == 1 and beats[0]["proposed"] == len(rows[0]["candidates"])
    trials = [r for r in coach.events(cfg) if r.get("kind") == "trial_result"]
    assert len(trials) == 1
    assert trials[0]["incumbent"]["candidates"] > 0 and trials[0]["challenger"]["candidates"] > 0
    assert not tools["get_option_chain"].calls, "the chain was handed in - no fetch"
    # the payload round-trips and its identity ignores the menu
    payload = out.to_payload()
    assert Opportunity.from_payload(payload) == out
    from trdrbot import ids

    bare = _opp(98.0, 102.0, horizon).to_payload()
    assert ids.opportunity_id("muse", payload) == ids.opportunity_id("muse", bare)


@pytest.mark.asyncio
async def test_attach_shares_one_chain_fetch_across_both_arms(tmp_path):
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    _pair(cfg, journal)
    expiry = days_out(8)
    tools = tools_for(get_option_chain=lambda **_: {"snapshots": _snapshots(expiry)})

    out = await playbook.attach(tools, cfg, journal, _opp(103.0, 108.0, days_out(5)),
                                source="research", spot=SPOT)

    assert len(tools["get_option_chain"].calls) == 1
    assert out.playbook is not None and out.playbook["shape"] == "bull_target"
    assert len([r for r in coach.events(cfg) if r.get("kind") == "trial_result"]) == 1


@pytest.mark.asyncio
async def test_attach_voids_the_trial_when_no_expiry_lies_inside_the_window(tmp_path):
    """Data absence is not evidence about either catalogue: the trial is
    VOID for both arms, the opportunity goes out without a menu, and the
    heartbeat says so."""
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    _pair(cfg, journal)
    expiry, late_horizon = days_out(8), days_out(12)
    tools = tools_for(get_option_chain=lambda **_: {"snapshots": _snapshots(expiry)})

    out = await playbook.attach(tools, cfg, journal, _opp(98.0, 102.0, late_horizon),
                                source="muse", spot=SPOT)

    assert out.playbook is None
    assert journal_rows(journal, "playbook")[0]["voided"] == playbook.VOID_NO_EXPIRY
    assert journal_rows(journal, "playbook_run")[0]["voided"] == 1
    trial = [r for r in coach.events(cfg) if r.get("kind") == "trial_result"][0]
    assert trial["challenger"] == {"voided": playbook.VOID_NO_EXPIRY}
    assert coach.tally(cfg, trial["exp_id"]).runs == 0, "a void is not a run"


@pytest.mark.asyncio
async def test_attach_never_raises_and_degrades_when_the_incumbent_arm_fails(tmp_path):
    """An operator can hand-edit the incumbent into something that does not
    parse. The emission still happens, without a menu, and a `degraded` row
    says why - a silent pass-through is the failure class D-074 names."""
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    st = coach.load_state(cfg, "playbook.catalogue", playbook.SEED_CATALOGUE)
    st.incumbent = coach.Variant("v0", "families: [")
    coach.save_state(cfg, st)
    expiry = days_out(8)

    out = await playbook.attach({}, cfg, journal, _opp(98.0, 102.0, days_out(5)), source="muse",
                                spot=SPOT, chain=_snapshots(expiry))

    assert out.playbook is None
    degraded = journal_rows(journal, "degraded")
    assert degraded and degraded[0]["subsystem"] == "playbook"
    assert journal_rows(journal, "playbook_run")[0]["proposed"] == 0

    # ...and a tool that raises is the same story: no exception escapes
    def boom(**_):
        raise RuntimeError("feed down")

    out = await playbook.attach(tools_for(get_option_chain=boom), cfg, journal,
                                _opp(98.0, 102.0, days_out(5)), source="muse", spot=SPOT)
    assert out.playbook is None


@pytest.mark.asyncio
async def test_attach_falls_back_to_realized_vol_when_the_chain_carries_no_iv(tmp_path):
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    expiry = days_out(8)
    import math
    import random

    rng = random.Random(1)
    closes = [100.0]
    for _ in range(120):
        closes.append(round(closes[-1] * math.exp(rng.gauss(0, 0.012)), 2))

    out = await playbook.attach({}, cfg, journal, _opp(98.0, 102.0, days_out(5)), source="muse",
                                chain=_snapshots(expiry, iv=None), closes=closes)

    assert out.playbook is not None and out.playbook["iv_source"] == "realized"
    assert out.playbook["spot"] == closes[-1]


def test_render_for_decide_lists_survivors_then_rejections_and_reads_as_legs():
    payload = {
        "underlying": "NVDA", "claim": "NVDA holds 222-232", "direction": "bullish",
        "drift_pct": 0.0, "band_low": 222.0, "band_high": 232.0, "horizon": "2026-09-04",
        "why": "MUSE domino chain: a -> b", "suggested_structures": ["bull call spread"],
        "playbook": {
            "shape": "bull_target", "priced_at": "2026-09-03T13:02:11+00:00",
            "expiry": "2026-09-04", "spot": 224.44, "sigma": 5.1, "iv_pct": 38.0,
            "iv_source": "chain",
            "candidates": [
                {"family": "bull_call_debit_on_band", "fate": "candidate",
                 "legs": [{"right": "C", "strike": 222.0, "side": "long", "qty": 1},
                          {"right": "C", "strike": 232.0, "side": "short", "qty": 1}],
                 "net": 410.0, "max_profit": 590.0, "max_loss": -410.0,
                 "e_hold": 402.0, "p_hold": 0.91, "p_fail": 0.12, "edge": 0.79},
                {"family": "iron_condor", "fate": "rejected: indifferent to the thesis (edge +0.08)"},
                {"family": "call_butterfly", "fate": "rejected: pays $-31 when the thesis holds"},
            ]}}
    text = render_for_decide(payload, source="muse", trust="primary")
    lines = text.splitlines()
    assert lines[0].startswith('- [opportunity | muse | trust=primary] NVDA - "NVDA holds 222-232"')
    assert "holds if 222 <= price <= 232 on 2026-09-04" in lines[0]
    assert any(l.strip().startswith("PLAYBOOK (bull_target;") for l in lines)
    assert "  bull_call_debit_on_band  +C222 -C232  debit $410 | maxP $590 / maxL $-410" in text
    assert "holds: P(win) 91% E[pnl] +$402 | fails: P(win) 12%" in text
    assert "rejected: iron_condor - indifferent to the thesis (edge +0.08); call_butterfly - pays" in text
    assert "re-simulate at live quotes" in text
    assert len(lines) <= 8
    # a menu-less opportunity renders the same header and nothing more
    bare = render_for_decide({k: v for k, v in payload.items() if k != "playbook"}, source="muse")
    assert "PLAYBOOK" not in bare and bare.startswith("- [opportunity | muse] NVDA")


def test_the_playbook_lever_is_a_declaration_the_registry_can_run():
    lever = coach.lever("playbook.catalogue")
    assert lever is not None and lever.kind == "policy"
    assert coach.seeds()["playbook.catalogue"] == playbook.SEED_CATALOGUE
    validator = coach.validator_of(lever)
    assert validator is not None and validator(playbook.SEED_CATALOGUE) == ""
    assert "naked" in validator(playbook.SEED_CATALOGUE.replace(
        "- {right: P, side: long,  at: {anchor: band_low, sigma: -1.0}}",
        "- {right: C, side: long,  at: {anchor: band_low, sigma: -1.0}}"))
    rendered = coach.render_mutate_prompt(lever, playbook.SEED_CATALOGUE, rejections="-",
                                          graveyard="-")
    assert "band holds" in rendered and "data, not a template" in rendered


# --- resolution at expiry -----------------------------------------------------

from datetime import timedelta  # noqa: E402

from trdrbot import ids, market_stats  # noqa: E402


def _iso(days_ago: int) -> str:
    """`days_ago` before the MARKET date - derived, never literal (D-032), and
    from the clock `scripts/suite_at.py` shifts, not the wall clock."""
    return (ids.market_today() - timedelta(days=days_ago)).isoformat()


def _proposal_row(journal: Journal, expiry: str, *, kind: str = "playbook",
                  entry_friction: float = 10.0, family: str = "bull_call_debit") -> str:
    legs = [playbook.leg_payload(Leg("C", 100.0, "long", 1, 3.0, expiry)),
            playbook.leg_payload(Leg("C", 105.0, "short", 1, 1.0, expiry))]
    return journal.append(kind, underlying="XYZ", source="muse", variant="v0",
                          band_low=103.0, band_high=108.0, expiry=expiry,
                          candidates=[{"family": family, "fate": "candidate", "legs": legs,
                                       "entry_friction": entry_friction, "e_hold": 50.0,
                                       "edge": 0.6}])


@pytest.mark.asyncio
async def test_resolve_scores_a_candidate_at_the_expiry_close_exactly(tmp_path):
    """Exact arithmetic at the close, less the entry friction the proposal was
    scored with - computed independently here."""
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    expiry = _iso(3)
    dates = [_iso(9 - i) for i in range(10)]
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
    market_stats.save_closes(cfg.paths.state, "XYZ", closes, dates=dates)
    rid = _proposal_row(journal, expiry)
    close = closes[dates.index(expiry)]

    r = await playbook.resolve(cfg, {}, journal)

    out = journal_rows(journal, "playbook_outcome")
    assert r["resolved"] == 1 and len(out) == 1
    legs = [Leg("C", 100.0, "long", 1, 3.0), Leg("C", 105.0, "short", 1, 1.0)]
    assert out[0]["pnl"] == pytest.approx(optmath.pnl_at(legs, close) - 10.0)
    assert out[0]["won"] is (out[0]["pnl"] > 0)
    assert out[0]["proposal_id"] == rid and out[0]["family"] == "bull_call_debit"
    assert out[0]["band_held_at_expiry"] is (103.0 <= close <= 108.0)
    beat = journal_rows(journal, "playbook_resolve_run")[-1]
    assert beat["due"] == 1 and beat["resolved"] == 1
    # idempotent: a second pass finds nothing due
    r2 = await playbook.resolve(cfg, {}, journal)
    assert r2["due"] == 0 and len(journal_rows(journal, "playbook_outcome")) == 1


@pytest.mark.asyncio
async def test_resolve_waits_for_the_expiry_session_to_close(tmp_path):
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    _proposal_row(journal, days_out(2))
    r = await playbook.resolve(cfg, {}, journal)
    assert r["due"] == 0 and not journal_rows(journal, "playbook_outcome")


@pytest.mark.asyncio
async def test_resolve_gives_up_after_ten_days_without_a_price_and_says_so(tmp_path):
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    _proposal_row(journal, _iso(12))
    r = await playbook.resolve(cfg, {}, journal)
    out = journal_rows(journal, "playbook_outcome")
    assert r["given_up"] == 1 and out[0]["unresolved"] == "no_price" and out[0]["won"] is None
    # ...and a recent one with no price is retried, not given up
    _proposal_row(journal, _iso(3), family="bear_put_debit")
    r = await playbook.resolve(cfg, {}, journal)
    assert r["no_price"] == 1 and r["given_up"] == 0
    assert len(journal_rows(journal, "playbook_outcome")) == 1


@pytest.mark.asyncio
async def test_resolve_fetches_a_missing_close_once_per_name_and_saves_it(tmp_path):
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    expiry = _iso(3)
    _proposal_row(journal, expiry)
    _proposal_row(journal, expiry, family="bull_put_credit")
    bars = [{"t": _iso(9 - i) + "T20:00:00Z", "c": 100.0 + i} for i in range(10)]
    tools = tools_for(get_stock_bars=lambda **_: {"bars": {"XYZ": bars}})

    r = await playbook.resolve(cfg, tools, journal)

    assert r["resolved"] == 2
    assert len(tools["get_stock_bars"].calls) == 1, "one fetch per name per pass"
    assert market_stats.returns_path(cfg.paths.state, "XYZ").exists(), "the series is kept"


def test_structures_simulated_row_is_written_for_the_agents_own_candidates_and_never_scored(tmp_path):
    """I-16, delivered: every structure the agent prices - traded or not - is
    journalled with its legs so the resolver scores it at expiry. A different
    kind from `playbook` on purpose: not a trial, and not read by the lever's
    rejection digest or its gauges."""
    from trdrbot import local_tools

    journal = Journal(tmp_path / "journal.jsonl")
    shared = local_tools.SharedContext()
    sim = local_tools.build_simulate_experiments(shared, None, None, journal=journal)
    sim.func(
        thesis_claim="up", underlying="SPY", horizon=days_out(5), drift_pct=0.5,
        spot=771.0, iv_pct=11.0, days_to_expiry=7, band_low=775.0, band_high=782.0,
        candidates=[
            {"name": "debit", "legs": [
                {"right": "C", "strike": 773, "side": "long", "qty": 1, "price": 3.10},
                {"right": "C", "strike": 778, "side": "short", "qty": 1, "price": 1.35}]},
            {"name": "credit", "legs": [
                {"right": "P", "strike": 765, "side": "short", "qty": 1, "price": 1.90},
                {"right": "P", "strike": 760, "side": "long", "qty": 1, "price": 1.10}]},
        ])
    rows = journal_rows(journal, "structures_simulated")
    assert len(rows) == 1 and rows[0]["source"] == "agent"
    fams = {c["name"]: c["family"] for c in rows[0]["candidates"]}
    assert fams == {"debit": "bull_call_debit", "credit": "bull_put_credit"}
    for c in rows[0]["candidates"]:
        assert c["legs"] and all(l["expiry"] == rows[0]["expiry"] for l in c["legs"])
        assert "e_hold" in c and "edge" in c, "the band-conditional read rides along"
        assert c["entry_friction"] > 0
    assert not journal_rows(journal, "playbook"), "not a playbook row: never a trial"
    assert {s.family for s in shared.structures} == {"bull_call_debit", "bull_put_credit"}
    # the lever's own gauges do not read it
    assert "playbook.survival_rate" not in coach.snapshot_gauges(
        SimpleNamespace(paths=SimpleNamespace(state=tmp_path, data=tmp_path), coach={}),
        list(journal.read()))


@pytest.mark.asyncio
async def test_attach_refetches_when_the_gates_page_lacks_strikes_around_spot(tmp_path):
    """Measured live on MRK: the gate's page matched the horizon's expiry and
    carried one put, at 135 against a 150 spot - every bearish family snapped
    onto it and was refused as unquoted, and no fetch happened because the
    expiry test passed. Coverage is the second half of "usable"."""
    cfg, journal = _cfg(tmp_path), Journal(tmp_path / "journal.jsonl")
    expiry = days_out(8)
    full = _snapshots(expiry)
    calls_only = {occ: s for occ, s in full.items() if "C" in occ[9:10] or occ.endswith("P00085000")}
    tools = tools_for(get_option_chain=lambda **_: {"snapshots": full})

    out = await playbook.attach(tools, cfg, journal, _opp(90.0, 96.0, days_out(5)),
                                source="muse", spot=SPOT, chain=calls_only)

    assert len(tools["get_option_chain"].calls) == 1, "a thin page triggers the targeted fetch"
    kw = tools["get_option_chain"].calls[0]
    assert kw["expiration_date_gte"] == days_out(5) and kw["strike_price_gte"] < SPOT < kw["strike_price_lte"]
    assert out.playbook is not None
    assert any(c["fate"] == "candidate" for c in out.playbook["candidates"]), out.playbook
