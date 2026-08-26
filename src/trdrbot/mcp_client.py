"""Alpaca MCP connection.

The server runs as a local stdio subprocess spawned by the MCP client. Alpaca
does publish hosted MCP endpoints, but they authenticate through interactive
browser OAuth, which a headless service cannot use - Alpaca's own docs point
this case at the open-source server with API-key auth.
"""

from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

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
    client = build_client(config)
    return await client.get_tools()
