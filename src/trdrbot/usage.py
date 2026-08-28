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

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from . import ids


@dataclass
class Call:
    ts: str
    role: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None  # None = model not in the pricing table


def price(pricing: dict[str, Any], model: str,
          input_tokens: int, output_tokens: int) -> float | None:
    """Cost in USD, or None when the model is not priced.

    `pricing` maps a model id to {input, output} in dollars per MILLION tokens.
    Matching is exact first, then by suffix - providers return dated ids like
    `gpt-4o-mini-2024-07-18` for a model configured as `openai:gpt-4o-mini`,
    and a table keyed on the configured name should still match.
    """
    entry = pricing.get(model)
    if entry is None:
        for key, val in pricing.items():
            bare = key.split(":", 1)[-1]
            if model.startswith(bare) or bare.startswith(model):
                entry = val
                break
    if not isinstance(entry, dict):
        return None
    try:
        return (input_tokens * float(entry["input"])
                + output_tokens * float(entry["output"])) / 1_000_000.0
    except (KeyError, TypeError, ValueError):
        return None


class UsageLedger:
    """Append-only JSONL. One line per LLM call."""

    def __init__(self, path: Path, pricing: dict[str, Any] | None = None) -> None:
        self.path = path
        self.pricing = pricing or {}

    def record(self, role: str, model: str, inp: int, out: int) -> Call:
        call = Call(ts=ids.utc_now().isoformat(), role=role, model=model,
                    input_tokens=inp, output_tokens=out,
                    cost_usd=price(self.pricing, model, inp, out))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps(call.__dict__) + "\n")
        except OSError as exc:  # noqa: BLE001 - never break a trade over bookkeeping
            print(f"[usage] could not write ledger: {exc!r}")
        return call

    def calls(self) -> list[Call]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Call(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

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
                        self.ledger.record(self.role, str(model), inp, out)
        except Exception as exc:  # noqa: BLE001 - accounting never breaks a trade
            print(f"[usage] callback error, ignored: {exc!r}")


def render(summary: dict[str, Any]) -> str:
    lines = ["", "=== LLM usage and cost ===", ""]
    lines.append(f"  {summary['calls']} calls, ${summary['total_cost_usd']:.4f} priced")
    if summary["unpriced_calls"]:
        lines.append(f"  WARNING: {summary['unpriced_calls']} call(s) UNPRICED "
                     f"(not counted in the total): {', '.join(summary['unpriced_models'])}")
        lines.append(f"  -> add these to llm.pricing in config.yaml for a true total")
    lines.append("")
    if summary["by_model"]:
        lines.append(f"  {'model':<44}{'calls':>6}{'in':>10}{'out':>9}{'cost':>10}")
        for m, d in sorted(summary["by_model"].items(), key=lambda kv: -kv[1]["cost"]):
            cost = f"${d['cost']:.4f}" if not d["unpriced"] else f"${d['cost']:.4f}*"
            lines.append(f"  {m[:43]:<44}{d['calls']:>6}{d['in']:>10,}{d['out']:>9,}{cost:>10}")
    if summary["by_role"]:
        lines.append("")
        lines.append("  by role: " + ", ".join(
            f"{r} ${c:.4f}" for r, c in sorted(summary["by_role"].items(), key=lambda kv: -kv[1])))
    lines.append("")
    return "\n".join(lines)
