"""The playbook - structure choice as a Coach lever, measured before trusted (notes/026).

The maths under this system prices any single-expiry leg set, the sizer
treats a condor and a vertical fairly, and nothing in exit rules or positions
assumes a leg count - yet only one- and two-leg structures were ever traded,
because nothing told the decide agent which structure family fits which
thesis shape. The obvious fix, a mapping paragraph in the system prompt, is a
human-asserted rule nothing scores. This module makes the mapping DATA the
Coach can move, scored by the stack's own arithmetic, promoted on evidence.

The lever is a CATALOGUE (YAML) of structure families, each declaring which
thesis shapes it applies to and where its strikes sit relative to the thesis
band, in units of the expected move. For every admitted opportunity the
incumbent catalogue is instantiated on the live chain and each instance meets
fixed gates:

    every leg quoted | loss bounded | pays after entry costs IF the band holds
    | wins materially more often when the band holds than when it fails

That last pair is `experiments.attribute` mirrored pre-trade: if the view is
right, does the expression pay, and does it stop paying when the view is
wrong. Survivors reach the decide agent as a priced menu beside the claim; a
shadow challenger is scored on the same chain memo and writes nothing; the
reward is the fraction of instances that survive. Every instance is journalled
with its legs and resolved at expiry against the close - exact arithmetic, the
slow evidence that audits the fast reward.

Rule 2 of the Coach (data, never code) holds by construction: the gates, their
constants, the validator and the sentinels live here; the catalogue cannot
reach them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from . import optmath
from .optmath import Leg

# --- shapes and anchors -----------------------------------------------------

SHAPES: tuple[str, ...] = ("range", "bull_target", "bear_target", "bull_floor", "bear_ceiling")
ANCHORS: tuple[str, ...] = ("spot", "band_low", "band_high", "band_mid")

#: The catalogue's bounds. Twelve families is more than a desk keeps; three is
#: the least that can cover a range and both directions.
MIN_FAMILIES, MAX_FAMILIES = 3, 12
MIN_LEGS, MAX_LEGS = 2, 4
#: A strike may sit this far from its anchor, in expected moves. This is what
#: makes a deep-in-the-money "spread" unrepresentable - the reward would score
#: an 80/120 vertical at spot 100 as faithful to any bullish claim, because it
#: is stock wearing a costume.
MAX_ANCHOR_SIGMA = 2.5

#: A structure must win at least this much more often when the thesis holds
#: than when it fails, or it is not expressing the thesis. From notes/026
#: section 5, where 0.25 separates the desk's answer from the rest on a
#: fair-value zoo. Audited by `playbook_outcome` rows - do rejected-as-
#: indifferent candidates keep winning? - never re-tuned from taste (the same
#: rule as exit_rules.CORROBORATION_FRACTION, I-65).
MIN_BAND_EDGE = 0.25
#: Entry friction is HALF the round-trip spread per leg: a proposal is scored
#: as held to expiry, and `friction-is-the-size-of-the-edge` records that a
#: round trip charged on a hold-to-expiry structure is an exit never paid.
ENTRY_CROSSINGS = 0.5
#: Which distribution conditioned the reward. Recorded on every row so a later
#: switch to the calibrated bootstrap (D-089) is auditable, not silent.
DIST = "lognormal"

#: The synthetic board the validator instantiates every family on: enough to
#: prove bounded loss and distinct strikes by the same arithmetic that scores
#: production, with no chain in sight.
SYNTHETIC_SPOT, SYNTHETIC_SIGMA = 100.0, 4.0
SYNTHETIC_BANDS: dict[str, tuple[float | None, float | None]] = {
    "range": (96.0, 104.0), "bull_target": (104.0, 110.0), "bear_target": (90.0, 96.0),
    "bull_floor": (97.0, None), "bear_ceiling": (None, 103.0),
}


class CatalogueError(ValueError):
    """A catalogue that cannot be run. The message names the defect and is what
    the mutator's retry suffix hands back."""


def shape_of(band_low: float | None, band_high: float | None, spot: float) -> str | None:
    """Which kind of claim this band makes. Derived from the band, never from
    the model's `direction` label - the band is what resolves; the label is
    prose, and the two disagree often enough to journal it."""
    if band_low is None and band_high is None:
        return None
    if band_low is None:
        return "bear_ceiling"
    if band_high is None:
        return "bull_floor"
    if band_low <= spot <= band_high:
        return "range"
    return "bull_target" if band_low > spot else "bear_target"


# --- the catalogue ----------------------------------------------------------


@dataclass(frozen=True)
class LegSpec:
    right: str    # C | P
    side: str     # long | short
    qty: int      # 1 | 2
    anchor: str   # one of ANCHORS
    sigma: float  # offset from the anchor, in expected moves


@dataclass(frozen=True)
class Family:
    name: str
    shapes: tuple[str, ...]
    legs: tuple[LegSpec, ...]


@dataclass(frozen=True)
class Catalogue:
    version: int
    families: tuple[Family, ...]

    def applicable(self, shape: str) -> list[Family]:
        return [f for f in self.families if shape in f.shapes]


SEED_CATALOGUE = """version: 1
families:
  - name: bull_call_debit
    shapes: [bull_target, bull_floor]
    legs:
      - {right: C, side: long,  at: {anchor: spot, sigma: 0.0}}
      - {right: C, side: short, at: {anchor: spot, sigma: 1.0}}
  - name: bull_call_debit_on_band
    shapes: [bull_target]
    legs:
      - {right: C, side: long,  at: {anchor: band_low,  sigma: -0.25}}
      - {right: C, side: short, at: {anchor: band_high, sigma: 0.0}}
  - name: bull_put_credit
    shapes: [bull_floor]
    legs:
      - {right: P, side: short, at: {anchor: band_low, sigma: 0.0}}
      - {right: P, side: long,  at: {anchor: band_low, sigma: -1.0}}
  - name: bear_put_debit
    shapes: [bear_target, bear_ceiling]
    legs:
      - {right: P, side: long,  at: {anchor: spot, sigma: 0.0}}
      - {right: P, side: short, at: {anchor: spot, sigma: -1.0}}
  - name: bear_put_debit_on_band
    shapes: [bear_target]
    legs:
      - {right: P, side: long,  at: {anchor: band_high, sigma: 0.25}}
      - {right: P, side: short, at: {anchor: band_low,  sigma: 0.0}}
  - name: bear_call_credit
    shapes: [bear_ceiling]
    legs:
      - {right: C, side: short, at: {anchor: band_high, sigma: 0.0}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 1.0}}
  - name: iron_condor
    shapes: [range]
    legs:
      - {right: P, side: short, at: {anchor: band_low,  sigma: 0.0}}
      - {right: P, side: long,  at: {anchor: band_low,  sigma: -1.0}}
      - {right: C, side: short, at: {anchor: band_high, sigma: 0.0}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 1.0}}
  - name: iron_butterfly
    shapes: [range]
    legs:
      - {right: P, side: short, at: {anchor: band_mid,  sigma: 0.0}}
      - {right: C, side: short, at: {anchor: band_mid,  sigma: 0.0}}
      - {right: P, side: long,  at: {anchor: band_low,  sigma: -0.5}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 0.5}}
  - name: call_butterfly
    shapes: [range]
    legs:
      - {right: C, side: long,  at: {anchor: band_low,  sigma: 0.0}}
      - {right: C, side: short, qty: 2, at: {anchor: band_mid, sigma: 0.0}}
      - {right: C, side: long,  at: {anchor: band_high, sigma: 0.0}}
"""


def _leg_spec(raw: Any, where: str) -> LegSpec:
    if not isinstance(raw, dict):
        raise CatalogueError(f"{where}: a leg must be a mapping, got {type(raw).__name__}")
    right = str(raw.get("right", "")).upper()
    if right not in ("C", "P"):
        raise CatalogueError(f"{where}: right must be C or P, got {raw.get('right')!r}")
    side = str(raw.get("side", "")).lower()
    if side not in ("long", "short"):
        raise CatalogueError(f"{where}: side must be long or short, got {raw.get('side')!r}")
    qty = raw.get("qty", 1)
    if qty not in (1, 2):
        raise CatalogueError(f"{where}: qty must be 1 or 2, got {qty!r}")
    at = raw.get("at")
    if not isinstance(at, dict):
        raise CatalogueError(f"{where}: needs at: {{anchor, sigma}}")
    anchor = str(at.get("anchor", ""))
    if anchor not in ANCHORS:
        raise CatalogueError(f"{where}: anchor must be one of {list(ANCHORS)}, got {anchor!r}")
    try:
        sigma = float(at.get("sigma", 0.0))
    except (TypeError, ValueError) as exc:
        raise CatalogueError(f"{where}: sigma must be a number") from exc
    if not -MAX_ANCHOR_SIGMA <= sigma <= MAX_ANCHOR_SIGMA:
        raise CatalogueError(
            f"{where}: sigma {sigma:g} outside +/-{MAX_ANCHOR_SIGMA:g} expected moves")
    return LegSpec(right=right, side=side, qty=int(qty), anchor=anchor, sigma=sigma)


def parse_catalogue(text: str) -> Catalogue:
    """YAML -> Catalogue. Raises CatalogueError naming the first defect.

    Structure only - what the schema says. Whether each family is RUNNABLE
    (bounded, non-degenerate on every shape it declares) is `validate_catalogue`,
    which needs the pricing arithmetic and reports rather than raises.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogueError(f"not valid YAML: {str(exc).splitlines()[0]}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("families"), list):
        raise CatalogueError("the catalogue must be a mapping with a `families:` list")
    fams_raw = raw["families"]
    if not MIN_FAMILIES <= len(fams_raw) <= MAX_FAMILIES:
        raise CatalogueError(
            f"{len(fams_raw)} families - between {MIN_FAMILIES} and {MAX_FAMILIES} allowed")
    families: list[Family] = []
    seen: set[str] = set()
    for i, f in enumerate(fams_raw):
        where = f"families[{i}]"
        if not isinstance(f, dict):
            raise CatalogueError(f"{where}: must be a mapping")
        name = str(f.get("name", "")).strip()
        if not name or not all(c.isalnum() or c == "_" for c in name) or not name.islower():
            raise CatalogueError(f"{where}: name must be a lowercase slug, got {name!r}")
        if name in seen:
            raise CatalogueError(f"{where}: duplicate family name {name!r}")
        seen.add(name)
        shapes = f.get("shapes")
        if not isinstance(shapes, list) or not shapes:
            raise CatalogueError(f"{name}: shapes must be a non-empty list")
        for sh in shapes:
            if sh not in SHAPES:
                raise CatalogueError(f"{name}: unknown shape {sh!r}, expected one of {list(SHAPES)}")
        legs = f.get("legs")
        if not isinstance(legs, list) or not MIN_LEGS <= len(legs) <= MAX_LEGS:
            raise CatalogueError(f"{name}: between {MIN_LEGS} and {MAX_LEGS} legs, got "
                                 f"{len(legs) if isinstance(legs, list) else 'none'}")
        families.append(Family(
            name=name, shapes=tuple(str(s) for s in shapes),
            legs=tuple(_leg_spec(l, f"{name}.legs[{j}]") for j, l in enumerate(legs))))
    return Catalogue(version=int(raw.get("version") or 1), families=tuple(families))


def _anchor_value(anchor: str, spot: float, band_low: float | None,
                  band_high: float | None) -> float | None:
    if anchor == "spot":
        return spot
    if anchor == "band_low":
        return band_low
    if anchor == "band_high":
        return band_high
    if band_low is None or band_high is None:
        return None
    return (band_low + band_high) / 2.0


def _target_strikes(family: Family, *, spot: float, sigma: float, band_low: float | None,
                    band_high: float | None) -> list[float] | str:
    """Where each leg WANTS to be, before snapping to a chain. A string when an
    anchor does not exist for this band (band_mid on a one-sided claim)."""
    out: list[float] = []
    for spec in family.legs:
        base = _anchor_value(spec.anchor, spot, band_low, band_high)
        if base is None:
            return f"anchor {spec.anchor} does not exist for this band"
        out.append(base + spec.sigma * sigma)
    return out


def validate_catalogue(text: str) -> str:
    """"" when the catalogue is safe to run, else the defect.

    The lever's `validator_ref`. Deterministic, names the exact problem, and
    instantiates every family on a synthetic board for every shape it declares
    so that "bounded loss" and "distinct strikes" are proven by the arithmetic
    that will score it - a naked short cannot be smuggled in by a mutation,
    because `max_profit_loss` refuses it here first.
    """
    try:
        cat = parse_catalogue(text)
    except CatalogueError as exc:
        return str(exc)
    for shape in SHAPES:
        if not cat.applicable(shape):
            return f"no family covers the shape {shape!r} - a catalogue must answer every claim"
    for fam in cat.families:
        # NO NAKED SHORT, as a property of the legs. `max_profit_loss` below
        # refuses an uncovered short CALL (its loss is unbounded) but a short
        # PUT's loss is bounded at its strike - a $9,499 worst case on a $96
        # strike, which the sizer would size and a catalogue must not offer.
        # Per right, the shorts must be covered by at least as many longs.
        for right in ("C", "P"):
            longs = sum(l.qty for l in fam.legs if l.right == right and l.side == "long")
            shorts = sum(l.qty for l in fam.legs if l.right == right and l.side == "short")
            if shorts > longs:
                return (f"{fam.name}: {shorts} short {right} against {longs} long - a naked "
                        f"short cannot be sized")
        for shape in fam.shapes:
            lo, hi = SYNTHETIC_BANDS[shape]
            targets = _target_strikes(fam, spot=SYNTHETIC_SPOT, sigma=SYNTHETIC_SIGMA,
                                      band_low=lo, band_high=hi)
            if isinstance(targets, str):
                return f"{fam.name} on {shape}: {targets}"
            legs = [Leg(right=s.right, strike=round(k, 2), side=s.side, qty=s.qty, price=0.0)
                    for s, k in zip(fam.legs, targets)]
            by_right: dict[tuple[str, float], int] = {}
            for l in legs:
                by_right[(l.right, l.strike)] = by_right.get((l.right, l.strike), 0) + 1
            if any(n > 1 for n in by_right.values()):
                return (f"{fam.name} on {shape}: two legs of one right resolve to the same "
                        f"strike - degenerate by construction")
            _, max_loss = optmath.max_profit_loss(legs)
            if max_loss is None:
                return f"{fam.name} on {shape}: unbounded loss - a naked short cannot be sized"
    return ""


# --- the chain, normalised --------------------------------------------------


@dataclass(frozen=True)
class Quote:
    occ: str
    right: str
    strike: float
    expiry: str
    bid: float | None
    ask: float | None
    iv: float | None  # fraction

    @property
    def quoted(self) -> bool:
        return (isinstance(self.bid, int | float) and isinstance(self.ask, int | float)
                and self.ask >= self.bid > 0)

    @property
    def mid(self) -> float | None:
        if not self.quoted or self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class Chain:
    """An option chain as this module reads it: quotes keyed by expiry."""

    quotes: tuple[Quote, ...]

    def expiries(self) -> list[str]:
        return sorted({q.expiry for q in self.quotes})

    def at(self, expiry: str, right: str | None = None) -> list[Quote]:
        return [q for q in self.quotes if q.expiry == expiry and (right is None or q.right == right)]

    def nearest(self, expiry: str, right: str, strike: float) -> Quote | None:
        """The listed strike closest to `strike`, quoted or not - a snap that
        lands on an unquoted contract is the catalogue's failure to report,
        not one to route around."""
        cands = self.at(expiry, right)
        return min(cands, key=lambda q: abs(q.strike - strike)) if cands else None

    def atm_iv(self, expiry: str, spot: float) -> float | None:
        """Mean IV of the call and put nearest spot, or None if the chain
        carries no IV at that expiry."""
        ivs = []
        for right in ("C", "P"):
            q = self.nearest(expiry, right, spot)
            if q is not None and q.iv is not None and q.iv > 0:
                ivs.append(q.iv)
        return sum(ivs) / len(ivs) if ivs else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def chain_from_snapshots(snaps: Any) -> Chain:
    """The Alpaca snapshot dict (as `options_gate` returns it) -> Chain.

    Reads the same `latestQuote.bp/ap` keys `compact.py` reads, plus the
    per-contract IV under either casing the feed has used. A contract with no
    parseable OCC key is dropped - it is not an option this module can price.
    """
    quotes: list[Quote] = []
    if not isinstance(snaps, dict):
        return Chain(quotes=())
    for occ, snap in snaps.items():
        meta = optmath.parse_occ(str(occ))
        if meta is None or not isinstance(snap, dict):
            continue
        q = snap.get("latestQuote") or {}
        iv = _num(snap.get("impliedVolatility", snap.get("implied_volatility")))
        quotes.append(Quote(
            occ=str(occ).upper(), right=meta["right"], strike=meta["strike"],
            expiry=meta["expiry"], bid=_num(q.get("bp")), ask=_num(q.get("ap")),
            iv=iv if iv and iv > 0 else None))
    return Chain(quotes=tuple(quotes))


# --- instantiation and the gates --------------------------------------------


@dataclass(frozen=True)
class Instance:
    """One family placed on one chain: real strikes, real mids, real spreads."""

    family: str
    legs: tuple[Leg, ...]
    occs: tuple[str, ...]
    #: A full bid/ask crossing per leg, round trip, dollars for the legs' qty.
    friction_rt: float


def resolve_legs(family: Family, shape: str, *, spot: float, sigma: float,
                 band_low: float | None, band_high: float | None, chain: Chain,
                 expiry: str) -> Instance | str:
    """Place a family on the chain. A fate string on gates 1-2 - every leg must
    be quoted, and no two legs of one right may collapse onto one strike."""
    targets = _target_strikes(family, spot=spot, sigma=sigma, band_low=band_low,
                              band_high=band_high)
    if isinstance(targets, str):
        return f"rejected: {targets}"
    legs: list[Leg] = []
    occs: list[str] = []
    friction = 0.0
    for spec, target in zip(family.legs, targets):
        q = chain.nearest(expiry, spec.right, target)
        if q is None:
            return f"rejected: unquoted leg {spec.right}{target:.0f} (no strike listed)"
        mid = q.mid
        if mid is None or q.bid is None or q.ask is None:
            return f"rejected: unquoted leg {q.occ}"
        legs.append(Leg(right=spec.right, strike=q.strike, side=spec.side, qty=spec.qty,
                        price=mid, expiry=expiry, iv=q.iv))
        occs.append(q.occ)
        friction += (q.ask - q.bid) * spec.qty * optmath.CONTRACT_MULTIPLIER
    seen: dict[tuple[str, float], int] = {}
    for l in legs:
        seen[(l.right, l.strike)] = seen.get((l.right, l.strike), 0) + 1
    if any(n > 1 for n in seen.values()):
        return "rejected: degenerate - legs collapsed to one strike"
    return Instance(family=family.name, legs=tuple(legs), occs=tuple(occs), friction_rt=friction)


def evaluate(legs: list[Leg] | tuple[Leg, ...], *, spot: float, iv: float, days: float,
             band_low: float | None, band_high: float | None,
             friction_rt: float) -> dict[str, Any]:
    """Gates 3-5 and the numbers behind them. One fate per instance.

    `iv` is the conditioning distribution's vol (the expiry's ATM IV) and
    `days` runs to EXPIRY, not to the horizon - the strikes live on the
    expiry's distribution and that is where the payoff is settled.
    """
    legs = list(legs)
    cost = optmath.entry_cost(legs)
    max_profit, max_loss = optmath.max_profit_loss(legs)
    entry_friction = friction_rt * ENTRY_CROSSINGS
    out: dict[str, Any] = {
        "net": round(cost, 2), "max_profit": max_profit, "max_loss": max_loss,
        "entry_friction": round(entry_friction, 2), "dist": DIST, "fate": "",
    }
    if max_loss is None:
        out["fate"] = "rejected: unbounded loss"
        return out
    bc = optmath.band_conditional(legs, spot, iv, days, band_low, band_high)
    if bc is None:
        out["fate"] = "rejected: band unreachable on the grid"
        return out
    e_hold = bc.e_pnl_hold - entry_friction
    out.update({
        "p_band": round(bc.p_band, 4), "e_hold": round(e_hold, 2),
        "p_hold": round(bc.p_profit_hold, 4), "p_fail": round(bc.p_profit_fail, 4),
        "edge": round(bc.edge, 4),
    })
    if e_hold <= 0:
        out["fate"] = f"rejected: pays ${e_hold:+,.0f} when the thesis holds"
    elif bc.edge < MIN_BAND_EDGE:
        out["fate"] = f"rejected: indifferent to the thesis (edge {bc.edge:+.2f})"
    else:
        out["fate"] = "candidate"
    return out


def score_arm(verdicts: list[dict[str, Any]], asked: int) -> dict[str, Any]:
    """One arm's paired-trial reward, in the muse's exact shape.

    A catalogue with NO family for a shape answers `asked` failures: it could
    not express the thesis, and that is the variant's own doing - unlike a
    missing chain, which voids the trial for both arms.
    """
    from .coach import survived

    hits = sum(1 for v in verdicts if survived(v.get("fate")))
    total = len(verdicts) or asked
    return {"candidates": len(verdicts), "survived": hits,
            "failed": max(0, total - hits),
            "fates": [str(v.get("fate", ""))[:80] for v in verdicts]}


# --- naming a structure from its legs ---------------------------------------


def classify(legs: list[Leg] | tuple[Leg, ...]) -> str:
    """The family a leg set belongs to, from its geometry alone.

    Derived, never declared (D-037): the model's `strategy` string is prose,
    and "which families have been right, wrong or lucky" has to be answerable
    from the legs that actually traded.
    """
    legs = sorted(legs, key=lambda l: (l.right, l.strike))
    n = len(legs)
    if n == 1:
        l = legs[0]
        return f"{l.side}_{'call' if l.right == 'C' else 'put'}"
    rights = {l.right for l in legs}
    if n == 2:
        a, b = legs
        if len(rights) == 1:
            if a.side == b.side:
                return "other"
            if a.qty != b.qty:
                return "ratio_spread"
            word = "call" if a.right == "C" else "put"
            debit = optmath.entry_cost(legs) > 0
            # calls: long the lower strike is bullish; puts: long the higher is bearish
            bullish = (a.side == "long") if a.right == "C" else (b.side == "short")
            return f"{'bull' if bullish else 'bear'}_{word}_{'debit' if debit else 'credit'}"
        if a.side != b.side:
            return "other"
        same = abs(a.strike - b.strike) < 1e-9
        return f"{a.side}_{'straddle' if same else 'strangle'}"
    if n == 3 and len(rights) == 1:
        lo, mid, hi = legs
        word = "call" if lo.right == "C" else "put"
        wings_long = lo.side == "long" and hi.side == "long" and mid.side == "short"
        wings_short = lo.side == "short" and hi.side == "short" and mid.side == "long"
        if mid.qty == 2 and lo.qty == hi.qty == 1 and (wings_long or wings_short):
            return f"{word}_butterfly" if wings_long else f"short_{word}_butterfly"
        return "other"
    if n == 4 and rights == {"C", "P"}:
        puts = [l for l in legs if l.right == "P"]
        calls = [l for l in legs if l.right == "C"]
        if len(puts) == 2 and len(calls) == 2:
            p_lo, p_hi = puts
            c_lo, c_hi = calls
            inner_short = p_hi.side == "short" and p_lo.side == "long" \
                and c_lo.side == "short" and c_hi.side == "long"
            inner_long = p_hi.side == "long" and p_lo.side == "short" \
                and c_lo.side == "long" and c_hi.side == "short"
            if inner_short:
                return "iron_butterfly" if abs(p_hi.strike - c_lo.strike) < 1e-9 else "iron_condor"
            if inner_long:
                return "reverse_iron_condor"
    return "other"


def leg_payload(leg: Leg, occ: str = "") -> dict[str, Any]:
    """One leg as a journal row carries it - enough to resolve at expiry."""
    d = {"right": leg.right, "strike": leg.strike, "side": leg.side, "qty": leg.qty,
         "price": leg.price, "expiry": leg.expiry}
    if occ:
        d["symbol"] = occ
    if leg.iv is not None:
        d["iv_pct"] = round(leg.iv * 100.0, 2)
    return d


def legs_from_payload(rows: list[dict[str, Any]]) -> list[Leg]:
    """The inverse of `leg_payload`, for the resolver. `Leg.parse` is the
    strict boundary parser and this is a recorded row, so the vocabulary is
    already this module's own."""
    return [Leg(right=str(r["right"]), strike=float(r["strike"]), side=str(r["side"]),
                qty=int(r.get("qty", 1)), price=float(r.get("price", 0.0)),
                expiry=str(r.get("expiry", "")),
                iv=(float(r["iv_pct"]) / 100.0) if r.get("iv_pct") is not None else None)
            for r in rows]


__all__ = [
    "ANCHORS", "SHAPES", "SEED_CATALOGUE", "MIN_BAND_EDGE", "ENTRY_CROSSINGS",
    "Catalogue", "CatalogueError", "Chain", "Family", "Instance", "LegSpec", "Quote",
    "chain_from_snapshots", "classify", "evaluate", "leg_payload", "legs_from_payload",
    "parse_catalogue", "resolve_legs", "score_arm", "shape_of", "validate_catalogue",
]
