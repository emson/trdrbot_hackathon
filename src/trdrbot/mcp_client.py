"""Alpaca MCP connection.

The server runs as a local stdio subprocess spawned by the MCP client. Alpaca
does publish hosted MCP endpoints, but they authenticate through interactive
browser OAuth, which a headless service cannot use - Alpaca's own docs point
this case at the open-source server with API-key auth.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from .config import Config

# Tool names that move money or change risk. Not used to block anything -
# D-009 removed guardrails - but the executor needs to know which calls are
# consequential so it can journal them as executions rather than reads.
ORDER_TOOLS = {
    "place_stock_order",
    "place_option_order",
    "place_crypto_order",
    "replace_order_by_id",
    "cancel_order_by_id",
    "cancel_all_orders",
    "close_position",
    "close_all_positions",
    "exercise_options_position",
}


def build_client(config: Config) -> MultiServerMCPClient:
    return MultiServerMCPClient({"alpaca": config.alpaca_mcp_server()})


async def get_tools(config: Config) -> list[Any]:
    """Tools that open a NEW session - and therefore a new `uvx` subprocess -
    per call. Fine for a one-shot CLI command; never use it inside a tick.
    See `session_tools`."""
    client = build_client(config)
    return await client.get_tools()


@asynccontextmanager
async def session_tools(config: Config) -> AsyncIterator[list[Any]]:
    """Tools bound to ONE session, so the whole tick shares one subprocess.

    `MultiServerMCPClient.get_tools()` returns tools that start a fresh session
    on every call - the adapter's own documented default - and for a stdio
    server that means spawning `uvx alpaca-mcp-server` again, ~1.6s of process
    start, for each individual tool call. A quiet housekeeping tick was doing
    six of them; one long run's log carries 515 server banners.

    Measured on the six calls a housekeeping tick makes: 12.33s across seven
    subprocesses, against 2.75s in one - a 78% saving, and far more on a decide
    cycle, which calls chains, snapshots and quotes many times over. It also
    buys back headroom against `tick.watchdog_seconds`, which a slow cycle was
    spending on process startup rather than on thinking.
    """
    client = build_client(config)
    async with client.session("alpaca") as session:
        yield await load_mcp_tools(session)


def unwrap(result: Any) -> Any:
    """Pull the payload out of the MCP server's response envelope.

    Alpaca's server wraps every result as
    ``{"_alpaca_mcp_security": {...}, "data": {...}}`` and tags it
    ``untrusted_tool_output`` - its own prompt-injection boundary. We only read
    the ``data`` half, and never treat anything inside it as instructions.
    """
    if isinstance(result, list) and result and isinstance(result[0], dict):
        text = result[0].get("text")
        if text:
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                return text
    if isinstance(result, dict):
        data = result.get("data", result)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data
    return result


async def call(tools: dict[str, Any], name: str, **kwargs: Any) -> Any:
    """Invoke a tool by name and unwrap the envelope."""
    return unwrap(await tools[name].ainvoke(kwargs))
