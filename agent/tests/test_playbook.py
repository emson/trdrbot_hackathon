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
