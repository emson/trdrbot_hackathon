# Technical Setup & Requirements

## Alpaca Trading Platform

### Account Setup

**Status:** ✅ Paper trading account created and registered

#### Account Creation Steps
1. Create or sign in at https://app.alpaca.markets/account/login
2. Select "Paper Trading" account from top left dashboard
3. Generate API Keys from dashboard API Keys panel
4. Copy and securely store your Key and Secret

#### Paper Trading Account Benefits
- $100,000 in virtual starting capital
- Real market data
- Full access to all trading features
- No card required
- No real money at risk
- Virtual funds can be reset at any time

### Options Trading

**Requirement:** All submissions must incorporate options trading

#### Paper Trading Options Access
- **Options Level:** Level 3 strategies enabled by default for paper accounts
- **No Setup Needed:** Options trading is automatically available in paper environments
- **Order Types Supported:**
  - Single-leg options orders
  - Multi-leg options orders (spreads, straddles, etc.)
  - Market, limit, stop, stop-limit orders
  - Bracket orders
  - Trailing stop orders

#### Options Documentation
See: https://docs.alpaca.markets/us/docs/options-trading

## Alpaca API Integration

### Three Ways to Integrate

#### 1. Trading MCP Server (Recommended for AI Agents)

**Overview:** Alpaca's MCP (Model Context Protocol) Server exposes 65 tools from the Trading and Market Data APIs. Designed to work seamlessly with AI assistants like Claude and Cursor.

**Key Features:**
- 65 tools across Trading and Market Data APIs
- Built from Alpaca's published OpenAPI specifications
- Stays aligned with API updates
- Works directly with AI assistants
- Documentation access tools included
- Read-only tools for inspecting API operations

**Setup:**
1. Create Alpaca account and generate API keys
2. Store keys securely (as environment variables)
3. Configure AI assistant with MCP Server connection
4. Use AI assistant to execute trades through structured tools

**Resources:**
- [Alpaca MCP Server Documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [Alpaca MCP Server GitHub](https://github.com/alpacahq/alpaca-mcp-server)
- [MCP Server Setup Guide](https://alpaca.markets/mcp-server)

#### 2. Trading API (Direct REST/WebSocket)

**Overview:** Direct access to Alpaca's trading endpoints via REST API and WebSocket connections

**Key Features:**
- Direct account management
- Order placement and management
- Real-time market data
- Portfolio tracking
- Webhook support

**Resources:**
- [Trading API Documentation](https://docs.alpaca.markets/us/docs/)
- [Alpaca GitHub Organization](https://github.com/alpacahq)

#### 3. Trading CLI (Command Line Interface)

**Overview:** Terminal-based tool for scripted, logged, or automated tasks

**Use Cases:**
- Scripted automation pipelines
- Logging and audit trails
- Integration with deployment systems
- Development and testing

**Resources:**
- [Trading CLI Documentation](https://docs.alpaca.markets/us/docs/)

## Build Stack Recommendations

### For Claude/Cursor + MCP Server Approach

```
AI Assistant (Claude/Cursor)
    ↓
Alpaca MCP Server (65 trading tools)
    ↓
Alpaca Trading API
    ↓
Paper Trading Account
```

### Tech Stack Examples

**Option A: Python-based**
- Python 3.8+
- Alpaca-py SDK or requests library
- FastAPI or Flask (for webhook endpoints if needed)
- Pandas/NumPy (for data analysis)

**Option B: Node.js-based**
- Node.js 18+
- alpaca-trade-api or fetch API
- Express.js (for webhook endpoints if needed)

**Option C: AI-Native (Recommended)**
- Claude or Cursor as the AI engine
- Alpaca MCP Server for trading interface
- Your chosen backend language (Python, Node.js, Go, etc.)
- LangChain or similar for prompt engineering

## Environment Variables

Store these securely (never commit to git):

```bash
APCA_API_KEY_ID=your_api_key_here
APCA_API_SECRET_KEY=your_secret_key_here
APCA_API_BASE_URL=https://paper-api.alpaca.markets  # For paper trading
```

## Market Data Access

**Included with Account:**
- Real-time quote data
- LULD (Limit Up/Limit Down) data
- News data
- Options data

**Data Formats:**
- REST API
- WebSocket streaming
- HTTP POST webhooks

## Key Limitations & Considerations

### Paper Trading Environment
- Virtual funds only ($100,000 starting)
- Real market data and conditions
- Same order execution as live trading (simulated)
- Order latency may differ from live trading

### Requirements
- Must use Alpaca's Trading API, MCP Server, or CLI
- Must incorporate options trading
- All orders execute in paper trading environment
- Team needs separate dedicated Alpaca paper trading account

## Documentation & Resources

**Official Resources:**
- [Building AI Trading Applications with Alpaca](https://alpaca.markets/blog/building-ai-trading-applications-with-alpaca/)
- [Alpaca Trading Docs](https://docs.alpaca.markets/)
- [How to Start Paper Trading](https://alpaca.markets/learn/start-paper-trading)
- [How to Trade Options](https://alpaca.markets/learn/how-to-trade-options-with-alpaca)
- [Register on Alpaca](https://alpaca.markets/learn/register-on-alpaca)

**MCP Server Resources:**
- [Alpaca MCP Server Documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [GitHub: Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server)
- [Awesome MCP Servers - Alpaca](https://mcpservers.org/servers/laukikk/alpaca-mcp)

---

**Last Updated:** August 26, 2026
