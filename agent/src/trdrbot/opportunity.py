"""The inbox seam's one shape, and the one gate that admits it.

Three sources write opportunities - research (top-down), discovery
(news-nominated) and the muse (creative collision) - and the decide cycle
treats every item identically. They were admitted by three DIFFERENT rule
sets, which is only visible when laid side by side:

    gate                      research  discovery  muse
    field defects (D-071)     yes       yes        never called
    horizon inside the window no        yes        yes
    bands are prices          no        yes        yes (+computed from pct)
    options chain exists      yes       yes        yes   (research: D-113)

So research - the source whose output the agent reads every morning - had
none of the four gates the other two earned through shipped bugs, and the
D-035 defect those gates exist for (the model emitting percentage moves as
dollar bands, making `holds_at` always-False and scoring every thesis as
failed) was still open on that path. The muse, meanwhile, hand-built a payload
that would have failed the shared field check it never called.

What is shared here is ONLY "may this become an inbox item". Each source keeps
its own prompts, its own evidence gathering, and its own extra gates - the
muse's bootstrap base rate and ledger pre-registration, discovery's nomination
gauntlet - because those are what make them different sources rather than one
source with three prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import mcp_client, optmath

#: A real band lives within this multiple of the computed spot. Outside it the
#: number is not a price at all - it is a percentage move, or a level recalled
#: from training data (D-035, D-081).
BAND_SPOT_LOW, BAND_SPOT_HIGH = 0.3, 3.0


@dataclass(frozen=True)
class Opportunity:
    """One candidate thesis, on its way to the inbox."""

    underlying: str
    claim: str
    horizon: str  # YYYY-MM-DD
    direction: str = "neutral"
    drift_pct: float = 0.0
    band_low: float | None = None
    band_high: float | None = None
    why: str = ""
    suggested_structures: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, raw: Any) -> Opportunity | None:
        """A model-supplied dict -> an Opportunity, or None if it is not one.

        Deliberately permissive about TYPES and strict about STRUCTURE: a
        model writing a number where a string belongs is normal and coercible,
        a model returning something that is not an object at all is not.
        """
        if not isinstance(raw, dict):
            return None
        def _f(key: str) -> float | None:
            v = raw.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        structures = raw.get("suggested_structures") or []
        return cls(
            underlying=str(raw.get("underlying") or "").upper(),
            claim=str(raw.get("claim") or ""),
            horizon=str(raw.get("horizon") or ""),
            direction=str(raw.get("direction") or "neutral"),
            drift_pct=_f("drift_pct") or 0.0,
            band_low=_f("band_low"),
            band_high=_f("band_high"),
            why=str(raw.get("why") or ""),
            suggested_structures=tuple(str(s) for s in structures
                                       if isinstance(structures, list)),
        )

    def to_payload(self) -> dict[str, Any]:
        """The inbox payload, key-for-key as the three sources wrote it.

        These keys are a WIRE FORMAT: the decide prompt renders them and
        `ids.opportunity_id` hashes three of them, so renaming one would
        silently change every opportunity's identity and break dedup.
        """
        return {
            "underlying": self.underlying,
            "claim": self.claim,
            "direction": self.direction,
            "drift_pct": self.drift_pct,
            "band_low": self.band_low,
            "band_high": self.band_high,
            "horizon": self.horizon,
            "why": self.why,
            "suggested_structures": list(self.suggested_structures),
        }


@dataclass(frozen=True)
class Admission:
    """Whether an opportunity may enter the inbox, and what could not be asked.

    `unchecked` is the part that matters as much as `defect`. A gate whose
    input is unavailable used to be skipped SILENTLY - discovery's band check
    vanished whenever the close fetch had failed, which is exactly when the
    data is worst, and research simply had no options gate at all with nothing
    recording its absence. Naming the gates that could not run turns "admitted"
    into "admitted on this much evidence" (D-038).
    """

    defect: str | None = None
    unchecked: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.defect is None


def field_defect(o: Opportunity) -> str | None:
    """Why this opportunity could never be scored, or None if it can.

    Returns the SPECIFIC missing field rather than a bare bool (D-071).
    "unscoreable_opportunity" was journalled for every rejection, so a
    fully-reasoned CRM thesis - correct bands, correct drift, the date stated
    in its own claim text - was indistinguishable in the log from genuine
    garbage. It was dropped for one absent `horizon` field and the rejection
    could not say so. A repeating defect is a fixable prompt problem; an opaque
    one is just attrition.
    """
    for name, value in (("underlying", o.underlying), ("claim", o.claim),
                        ("horizon", o.horizon)):
        if not value:
            return f"missing_{name}"
    if o.band_low is None and o.band_high is None:
        return "missing_band"
    if len(o.horizon) != 10 or o.horizon[4] != "-" or o.horizon[7] != "-":
        return "bad_horizon_format"
    return None


def admit(
    o: Opportunity,
    *,
    spot: float | None = None,
    latest_useful: str | None = None,
    options_tradeable: bool | None = None,
    earliest_useful: str | None = None,
) -> Admission:
    """May this enter the inbox? One answer, for all three sources.

    Every gate whose input is None lands in `unchecked` instead of passing
    quietly, so the emission row records what the admission actually rested on.
    """
    defect = field_defect(o)
    if defect:
        return Admission(defect=defect)

    unchecked: list[str] = []

    if latest_useful:
        if o.horizon > latest_useful:
            return Admission(defect="horizon_too_late")
        # The window has TWO sides (D-112). The muse's own cascade refused
        # `days <= 0`; this shared gate only checked the far end, so research
        # and discovery could admit a thesis dated today - which resolves in
        # zero days and teaches nothing.
        if earliest_useful and o.horizon < earliest_useful:
            return Admission(defect="horizon_too_early")
    else:
        unchecked.append("horizon_window")

    if spot and spot > 0:
        for band in (o.band_low, o.band_high):
            if band is not None and not (BAND_SPOT_LOW * spot <= band <= BAND_SPOT_HIGH * spot):
                return Admission(defect="band_not_a_price")
    else:
        unchecked.append("band_plausibility")

    if options_tradeable is None:
        unchecked.append("options_gate")
    elif not options_tradeable:
        return Admission(defect="failed_options_gate")

    return Admission(unchecked=tuple(unchecked))


async def options_gate(tools: dict[str, Any], ticker: str, latest: str) -> dict[str, Any]:
    """Does a chain exist with an expiry on/before `latest`?

    `latest` is the forecast window's own upper bound, not the deadline
    (D-101). The question the gate asks is "can a thesis on this name resolve
    while it is still worth acting on", and that has an answer whether or not a
    competition is running - the hard stop merely tightens it when one exists.
    Passing the raw deadline meant this gate had no bound at all without one.

    Counts real contracts, by parsing the OCC keys the chain is actually keyed
    by. It used to count the SUBSTRING "symbol" in `str(response)`, which made
    an error payload like `{"error": "no chain for symbol XYZ"}` score 1 and
    return tradeable - the gate answering yes on the evidence that it failed.
    The same heuristic would have broken the other way the moment chain
    compaction ran first: a compacted table contains neither "symbol" nor the
    ticker, so every candidate would have been rejected as untradeable,
    permanently and silently.

    Lives HERE, beside `admit`, because it answers one of `admit`'s own
    parameters and all three sources need it. It sat in `discovery` while the
    muse reached across for it and `research` - the source whose output the
    agent reads every morning - never called it at all, because
    `discovery` already imports `research` and the import would not have gone
    the other way (D-113). A shared gate living inside one of its callers is
    how a table like the one above gets a "no" in it.
    """
    try:
        r = await mcp_client.call(
            tools, "get_option_chain", underlying_symbol=ticker,
            expiration_date_lte=latest,
        )
        snaps = r.get("snapshots") if isinstance(r, dict) else None
        if isinstance(snaps, dict):
            n = sum(1 for occ in snaps if optmath.parse_occ(str(occ)))
            return {"tradeable": n > 0, "contracts_seen": n, "via": "snapshots"}
        if isinstance(r, dict) and r.get("error"):
            # An error is an answer, and the answer is no. Under the old
            # substring count this was the WORST case: the message itself
            # usually contains the word "symbol", so a failure scored 1 and
            # the gate returned tradeable.
            return {"tradeable": False, "contracts_seen": 0,
                    "error": str(r["error"])[:120], "via": "error_payload"}
        # Unrecognised shape. Keep the old heuristic so a schema change
        # degrades rather than blocking every candidate - but SAY which path
        # answered, because a silent fallback is how the substring count
        # survived unnoticed in the first place (D-038).
        text = str(r)
        n = text.count("symbol") or text.count(ticker)
        return {"tradeable": n > 0, "contracts_seen": n, "via": "substring_fallback"}
    except Exception as exc:  # noqa: BLE001
        return {"tradeable": False, "error": type(exc).__name__}
