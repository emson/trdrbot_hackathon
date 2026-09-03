"""Token and cost accounting across every provider (D-062).

One append-only ledger of every LLM call the system makes: which role asked,
which model actually answered, how many tokens, and what it cost. Written from
a LangChain callback, so it covers all five call sites (decide, research,
discovery, muse, doctor) without any of them knowing it exists.

Two deliberate properties:

**An unpriced model is reported, never counted as free.** If a model is absent
from the pricing table, its cost is `None` and the report says how many calls
are unpriced - it does not quietly add 0.00 to the total. That is the
absence-as-zero failure class this project keeps finding (D-038), and a
cost report that silently understates spend is exactly its most expensive
form.

**Accounting can never break a trade.** Every callback path is wrapped: a
malformed usage payload, an unwritable ledger, a disk full - none of it may
propagate into a decide cycle. Bookkeeping that can halt trading is worse
than no bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from . import ids, store

#: Anthropic's published cache multipliers against the base input rate: a
#: cache WRITE costs 1.25x, a READ 0.1x. OpenAI's automatic caching discounts
#: reads too and reports them the same way through LangChain, so the same
#: arithmetic covers both. Wrong in the third decimal for some providers;
#: catastrophically wrong if omitted, because a cached token billed at full
#: rate makes caching look like it saved nothing.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


@dataclass
class Call:
    ts: str
    role: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None  # None = model not in the pricing table
    #: Of `input_tokens`, how many were served from / written to the prompt
    #: cache. LangChain's `usage_metadata.input_tokens` is the TOTAL and
    #: already includes both, so they are priced by adjusting, never by adding.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def price(pricing: dict[str, Any], model: str,
          input_tokens: int, output_tokens: int,
          cache_read: int = 0, cache_write: int = 0) -> float | None:
    """Cost in USD, or None when the model is not priced.

    `pricing` maps a model id to {input, output} in dollars per MILLION tokens.
    Matching is exact first, then by suffix - providers return dated ids like
    `gpt-4o-mini-2024-07-18` for a model configured as `openai:gpt-4o-mini`,
    and a table keyed on the configured name should still match.

    Cached input is billed at its own rate. `input_tokens` is the total, so the
    cached share is removed from the full-price bucket and re-added at its
    multiplier rather than counted twice.
    """
    entry = pricing.get(model)
    if entry is None:
        # LONGEST match, not first (D-112): "gpt-5-mini-2025-08-07" starts
        # with "gpt-5", and dict order put "openai:gpt-5" first, so every
        # mini call was priced at the gpt-5 rate - 5x, on 27 recorded calls,
        # in every cost report and the cost sentinel's numerator.
        best = ""
        for key, val in pricing.items():
            bare = key.split(":", 1)[-1]
            if (model.startswith(bare) or bare.startswith(model)) and len(bare) > len(best):
                best, entry = bare, val
    if not isinstance(entry, dict):
        return None
    try:
        rate_in = float(entry["input"])
        full = max(0, input_tokens - cache_read - cache_write)
        return (full * rate_in
                + cache_read * rate_in * CACHE_READ_MULTIPLIER
                + cache_write * rate_in * CACHE_WRITE_MULTIPLIER
                + output_tokens * float(entry["output"])) / 1_000_000.0
    except (KeyError, TypeError, ValueError):
        return None


class UsageLedger:
    """Append-only JSONL. One line per LLM call."""

    def __init__(self, path: Path, pricing: dict[str, Any] | None = None) -> None:
        self.path = path
        self.pricing = pricing or {}

    def record(self, role: str, model: str, inp: int, out: int,
               cache_read: int = 0, cache_write: int = 0) -> Call:
        call = Call(ts=ids.utc_now().isoformat(), role=role, model=model,
                    input_tokens=inp, output_tokens=out,
                    cost_usd=price(self.pricing, model, inp, out,
                                   cache_read, cache_write),
                    cache_read_tokens=cache_read, cache_write_tokens=cache_write)
        store.append_jsonl(self.path, dict(call.__dict__), advisory=True)
        return call

    def calls(self) -> list[Call]:
        if not self.path.exists():
            return []
        out = []
        for row in store.read_jsonl(self.path)[0]:
            try:
                # Ignore keys Call has not heard of - `v` is one, and a field
                # added later must not make every older row unreadable.
                out.append(Call(**{k: v for k, v in row.items()
                                   if k in Call.__dataclass_fields__}))
            except TypeError:
                continue
        return out

    def served_since(self, role: str, since_ts: str) -> list[str]:
        """Models that ACTUALLY answered `role` since `since_ts`, first-seen order.

        The journal used to record `config.model` - the configured FIRST
        CHOICE - as "the model that made this decision". When the fallback
        chain fires, that is simply false: 19 decide cycles were journalled as
        `anthropic:claude-opus-5` while this ledger shows `gpt-5` served every
        one of them (D-070). Fallback firing is not an error and leaves no
        error record, so nothing else in the system would ever have contradicted
        the wrong attribution. This is the only place that knows the truth,
        because it is written from the provider's own response metadata.

        A list, not a single value: one decide cycle is several LLM calls, and
        a chain that fails over mid-cycle genuinely was served by two models.
        Flattening that to one name would trade a known lie for a subtler one.
        """
        seen: list[str] = []
        for c in self.calls():
            if c.role == role and c.ts >= since_ts and c.model not in seen:
                seen.append(c.model)
        return seen

    def summary(self) -> dict[str, Any]:
        calls = self.calls()
        priced = [c for c in calls if c.cost_usd is not None]
        unpriced = [c for c in calls if c.cost_usd is None]
        by_model: dict[str, dict[str, Any]] = {}
        by_role: dict[str, float] = {}
        for c in calls:
            m = by_model.setdefault(c.model, {"calls": 0, "in": 0, "out": 0,
                                              "cost": 0.0, "unpriced": 0})
            m["calls"] += 1
            m["in"] += c.input_tokens
            m["out"] += c.output_tokens
            m["cached"] = m.get("cached", 0) + c.cache_read_tokens
            if c.cost_usd is None:
                m["unpriced"] += 1
            else:
                m["cost"] += c.cost_usd
                by_role[c.role] = by_role.get(c.role, 0.0) + c.cost_usd
        return {
            "calls": len(calls),
            "total_cost_usd": sum(c.cost_usd or 0.0 for c in priced),
            "unpriced_calls": len(unpriced),
            "unpriced_models": sorted({c.model for c in unpriced}),
            "by_model": by_model,
            "by_role": by_role,
        }


def _cache_split(details: dict[str, Any]) -> tuple[int, int]:
    """(cache_read, cache_write) out of LangChain's input_token_details.

    Two shapes are live at once and both must be read. The reading call reports
    `cache_read`; the WRITING call reports 0 there and puts the same tokens
    under `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` (verified
    against a real Anthropic response: write leg 2611 ephemeral_5m with
    cache_creation 0, read leg 2611 cache_read). Taking only `cache_creation`
    would price every cache WRITE as ordinary input - which is nearly right,
    since a write is 1.25x, but it would also make the ledger silent about
    whether caching engaged at all.
    """
    try:
        read = int(details.get("cache_read") or 0)
        write = int(details.get("cache_creation") or 0)
        if not write:
            write = sum(int(v or 0) for k, v in details.items()
                        if str(k).startswith("ephemeral_") and k.endswith("_input_tokens"))
        return max(0, read), max(0, write)
    except (TypeError, ValueError):
        return 0, 0


class UsageCallback(BaseCallbackHandler):
    """Records every LLM response. Attached once, at model construction."""

    def __init__(self, ledger: UsageLedger, role: str) -> None:
        self.ledger = ledger
        self.role = role

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            for gen_list in getattr(response, "generations", []) or []:
                for gen in gen_list or []:
                    msg = getattr(gen, "message", None)
                    if msg is None:
                        continue
                    usage = getattr(msg, "usage_metadata", None) or {}
                    meta = getattr(msg, "response_metadata", None) or {}
                    # The model that ACTUALLY answered - which is the point
                    # under fallback: the configured primary may not be the
                    # one that served, and billing follows the server.
                    model = (meta.get("model_name") or meta.get("model")
                             or "unknown")
                    inp = int(usage.get("input_tokens") or 0)
                    out = int(usage.get("output_tokens") or 0)
                    if inp or out:
                        r, w = _cache_split(usage.get("input_token_details") or {})
                        self.ledger.record(self.role, str(model), inp, out, r, w)
        except Exception as exc:  # noqa: BLE001 - accounting never breaks a trade
            print(f"[usage] callback error, ignored: {exc!r}")


def render(summary: dict[str, Any]) -> str:
    lines = ["", "=== LLM usage and cost ===", ""]
    lines.append(f"  {summary['calls']} calls, ${summary['total_cost_usd']:.4f} priced")
    if summary["unpriced_calls"]:
        lines.append(f"  WARNING: {summary['unpriced_calls']} call(s) UNPRICED "
                     f"(not counted in the total): {', '.join(summary['unpriced_models'])}")
        lines.append("  -> add these to llm.pricing in config.yaml for a true total")
    lines.append("")
    if summary["by_model"]:
        # `cached` is the share of `in` served from the prompt cache at a tenth
        # of the rate. Input is ~80% of this system's bill and most of it is a
        # prefix re-sent on every agent turn, so this column is where the money
        # is - a zero next to a large `in` means caching is not engaging.
        lines.append(f"  {'model':<40}{'calls':>6}{'in':>10}{'cached':>9}{'out':>9}{'cost':>10}")
        for m, d in sorted(summary["by_model"].items(), key=lambda kv: -kv[1]["cost"]):
            cost = f"${d['cost']:.4f}" if not d["unpriced"] else f"${d['cost']:.4f}*"
            cached = d.get("cached", 0)
            share = f"{cached / d['in']:.0%}" if d["in"] and cached else "-"
            lines.append(f"  {m[:39]:<40}{d['calls']:>6}{d['in']:>10,}{share:>9}"
                         f"{d['out']:>9,}{cost:>10}")
    if summary["by_role"]:
        lines.append("")
        lines.append("  by role: " + ", ".join(
            f"{r} ${c:.4f}" for r, c in sorted(summary["by_role"].items(), key=lambda kv: -kv[1])))
    lines.append("")
    return "\n".join(lines)
