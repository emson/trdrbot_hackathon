"""Force deterministic order ids onto MCP order tools.

The LLM calls the Alpaca MCP tools directly, which means it authors every
argument - including `client_order_id`. Left alone it invents one per call
(observed: "trdrbot-skeleton-20260826-spy260918c765"), which quietly defeats
INV-18: a crash-retry would re-invoke the model, get a *different* invented id,
and Alpaca would happily accept a second, different position. The journal would
also be recording an id that was never actually sent.

So we wrap the order-placing tools and overwrite `client_order_id` with the
batch-derived value before the call leaves the process.

This is NOT a guardrail (D-009). It blocks nothing and vetoes no decision - it
normalises one argument so the idempotency guarantee actually holds. Same
category as reconciliation: correctness plumbing, not policy.
"""

from __future__ import annotations

from typing import Any, Sequence

from . import ids

#: Only tools that *create* an order take a client_order_id. Cancels and closes
#: are addressed by order/position id instead.
_ID_BEARING = {"place_stock_order", "place_option_order", "place_crypto_order"}

#: `close_all_positions` liquidates the ENTIRE book. Observed live (D-046): the
#: agent reached for it intending to close ONE spread, and followed it with a
#: separate sell order on a leg the sweep had already closed - which only
#: failed to leave a naked short because of fill sequencing, not design. With
#: one position open it is equivalent to a legitimate close; with several it
#: destroys unrelated theses mid-flight and wrecks the learning record.
_WHOLE_BOOK = "close_all_positions"


def redirect_whole_book_close(tools: Sequence[Any], count_open: "callable") -> list[Any]:
    """Refuse a whole-book liquidation while more than one position is open.

    NOT a judgment gate (D-009): it vetoes no view and blocks no strategy. It
    refuses one instrument whose blast radius exceeds any single-position
    intent, and names the correct one (`close_position` per symbol, which
    INV-19 already requires for all legs). The agent may still close every
    position - one at a time, deliberately.
    """
    out: list[Any] = []
    for tool in tools:
        if tool.name != _WHOLE_BOOK:
            out.append(tool)
            continue
        original = tool.coroutine

        async def _guarded(*args: Any, __orig=original, **kwargs: Any) -> Any:
            n = count_open()
            if n > 1:
                msg = (
                    f"REFUSED: close_all_positions would liquidate all {n} open "
                    f"positions, not the one you mean. Close per position with "
                    f"close_position(symbol_or_asset_id=...) for every leg "
                    f"(INV-19). If you genuinely intend to flatten the whole "
                    f"book, do it one position at a time."
                )
                print(f"[tool_guard] {msg}")
                return msg
            return await __orig(*args, **kwargs)

        tool.coroutine = _guarded
        out.append(tool)
    return out


def _accepts_client_order_id(tool: Any) -> bool:
    """True if the tool takes a client_order_id argument.

    langchain-mcp-adapters exposes args_schema as a raw JSON-Schema dict rather
    than a pydantic model, so handle both shapes.
    """
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return False
    if isinstance(schema, dict):
        return "client_order_id" in schema.get("properties", {})
    fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", {})
    return "client_order_id" in fields


def enforce_order_ids(tools: Sequence[Any], batch: str) -> list[Any]:
    """Return tools with deterministic client_order_id injection applied."""
    out: list[Any] = []
    for tool in tools:
        if tool.name in _ID_BEARING and _accepts_client_order_id(tool):
            out.append(_wrap(tool, batch))
        else:
            out.append(tool)
    return out


def _wrap(tool: Any, batch: str) -> Any:
    original = tool.coroutine
    forced_id = ids.client_order_id(batch)

    async def _forced(*args: Any, **kwargs: Any) -> Any:
        supplied = kwargs.get("client_order_id")
        if supplied and supplied != forced_id:
            print(
                f"[tool_guard] {tool.name}: replacing model-supplied "
                f"client_order_id {supplied!r} with batch-derived {forced_id!r}"
            )
        kwargs["client_order_id"] = forced_id
        return await original(*args, **kwargs)

    tool.coroutine = _forced
    return tool
