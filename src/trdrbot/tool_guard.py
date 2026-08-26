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
