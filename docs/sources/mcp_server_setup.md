# Alpaca MCP Server Setup & Usage

## What is MCP (Model Context Protocol)?

MCP enables AI assistants (like Claude) to have access to structured tools and data sources. The Alpaca MCP Server provides Claude/Cursor with direct access to trading capabilities through 65 tools.

## Architecture

```
You (in Claude/Cursor)
    ↓
Claude's Brain (thinks about trading)
    ↓
Alpaca MCP Server (65 tools)
    ↓
Alpaca Trading API
    ↓
Your Paper Trading Account
```

## Alpaca MCP Server Tools (65 Total)

### Account Tools (8)
- Get account information
- Get account configurations
- Get account trading configurations
- Check buying power
- Monitor account equity
- View account history
- Update account settings
- Get portfolio metrics

### Order Management Tools (12)
- Submit orders (market, limit, stop, bracket, etc.)
- Get order status
- List all orders
- Cancel orders
- Modify orders
- Get filled orders
- Monitor order fills
- Get order history

### Position Management Tools (6)
- Get all open positions
- Get specific position
- Close position
- Get position P&L
- Monitor position changes
- Get historical positions

### Market Data Tools (15)
- Get latest stock quotes
- Get historical price bars (OHLCV)
- Get market status
- Get trading hours
- Get latest trades
- Get bid/ask data
- Stream real-time quotes
- Get market calendars
- Get corporate actions
- Get earnings dates
- Get economic calendars
- Search securities
- Get company information

### Options Trading Tools (12)
- Get options chains
- Get options contracts
- Place options orders
- Get options positions
- Close options positions
- Get options Greeks
- Get implied volatility
- Calculate options pricing
- Get options history
- Monitor options trades
- Get options strategies
- Get options analytics

### Documentation Tools (6)
- Search API documentation
- Get tool descriptions
- List available operations
- Get implementation details
- Find examples
- Access reference guides

### Crypto Tools (Optional, if enabled)
- Get crypto quotes
- Place crypto orders
- Get crypto positions
- Get crypto bars
- Monitor crypto trades

## Installation

### Option 1: Using npm

```bash
npm install -g @alpaca/mcp-server
# or
npm install @alpaca/mcp-server
```

### Option 2: Using pip

```bash
pip install alpaca-mcp-server
```

### Option 3: Build from Source

```bash
git clone https://github.com/alpacahq/alpaca-mcp-server.git
cd alpaca-mcp-server
npm install
npm run build
npm run start
```

## Configuration

### Environment Variables

Set these before running the MCP server:

```bash
# Required
export APCA_API_KEY_ID="your_api_key_id"
export APCA_API_SECRET_KEY="your_api_secret_key"

# Optional (defaults to paper trading)
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"

# Optional - logging level
export LOG_LEVEL="info"
```

### .env File Approach

Create `.env` file:
```
APCA_API_KEY_ID=your_key_here
APCA_API_SECRET_KEY=your_secret_here
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

Load environment:
```bash
source .env
# On Windows: set /p < .env
```

## Running the Server

### Basic Start

```bash
# If installed globally
alpaca-mcp-server

# If installed locally
npx alpaca-mcp-server

# Or via Python
python -m alpaca_mcp_server
```

### With Custom Configuration

```bash
alpaca-mcp-server --port 3000 --loglevel debug
```

### As a Service (systemd)

```ini
[Unit]
Description=Alpaca MCP Server
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/alpaca
Environment="APCA_API_KEY_ID=your_key"
Environment="APCA_API_SECRET_KEY=your_secret"
ExecStart=/usr/local/bin/alpaca-mcp-server
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Connecting Claude/Cursor to MCP Server

### Claude Desktop App

1. Install Alpaca MCP Server
2. Configure in `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "alpaca-mcp-server",
      "env": {
        "APCA_API_KEY_ID": "your_key_id",
        "APCA_API_SECRET_KEY": "your_secret_key",
        "APCA_API_BASE_URL": "https://paper-api.alpaca.markets"
      }
    }
  }
}
```

3. Restart Claude
4. Start using Alpaca tools

### Claude Web (claude.ai)

1. Start MCP Server locally
2. In Claude's settings, configure MCP server connection
3. Connect to `http://localhost:3000` (or your configured port)
4. Start using tools

### Cursor IDE

1. Install Alpaca MCP Server
2. In Cursor settings → MCP Servers
3. Add server configuration with credentials
4. Restart Cursor
5. Access tools in chat with `@alpaca`

## Using Tools with Claude

### Simple Query

```
You: "What's the current price of Apple stock?"

Claude uses: GET /v1/stocks/{symbol}/quotes
Result: Shows you AAPL price in real-time
```

### Placing a Trade

```
You: "Buy 10 shares of AAPL at market price in my paper account"

Claude:
1. Calls: Get account → checks buying power
2. Calls: Submit order → AAPL, 10 shares, buy, market
3. Result: Shows order confirmation and details
```

### Options Trading Strategy

```
You: "I want to sell a bull call spread on AAPL. 
      Buy the 230 call and sell the 235 call, both expiring Sept 18.
      Execute 5 spreads."

Claude:
1. Calls: Get options chains → finds Sept 18 expiration
2. Calls: Get options contracts → finds both strikes
3. Calls: Submit multi-leg order → places spread
4. Result: Confirmation of spread execution
```

### Market Analysis

```
You: "Give me the last 30 days of daily bars for AAPL and suggest 
      trading strategies based on the chart"

Claude:
1. Calls: Get bars → retrieves 30 days of OHLCV data
2. Analyzes data locally
3. Suggests strategies (momentum, mean reversion, etc.)
4. Proposes entry/exit points
```

## Example Workflows

### Workflow 1: Simple Buy and Hold

```
User: "Execute a simple buy 5 shares of MSFT at market"

Claude Process:
├─ Check account balance
├─ Place buy order (5 MSFT, market)
├─ Confirm order filled
└─ Show position details
```

### Workflow 2: Options Spread Strategy

```
User: "Create a bear put spread on QQQ. Sell 405 put, buy 400 put, 
       both Oct 17, 10 contracts"

Claude Process:
├─ Get options chains (QQQ)
├─ Verify Oct 17 expiration exists
├─ Calculate margin requirement
├─ Execute multi-leg order
├─ Monitor position
└─ Calculate Greeks and potential profit/loss
```

### Workflow 3: Daily Trading Algorithm

```
User: "Let's build a simple moving average crossover strategy.
       When 20-day MA crosses above 50-day MA, buy.
       When it crosses below, sell."

Claude:
├─ Gets historical bars
├─ Calculates moving averages
├─ Identifies crossover signals
├─ Executes entry/exit orders
├─ Monitors P&L
└─ Logs all trades
```

## Tool Categories & Typical Use Cases

### Account Management
**Use for:** Checking funds, monitoring balance, verifying account status
```
Claude: "Tell me my current buying power and portfolio value"
Tools: get_account, get_account_configuration
```

### Order Execution
**Use for:** Placing, modifying, canceling orders
```
Claude: "Buy 100 shares of SPY at $450"
Tools: submit_order, get_order, cancel_order
```

### Position Management
**Use for:** Monitoring open positions, closing trades
```
Claude: "Close my AAPL position and show me P&L"
Tools: get_positions, close_position
```

### Market Data
**Use for:** Analyzing price trends, finding entry/exit points
```
Claude: "What's the 3-month trend for AAPL?"
Tools: get_bars, get_quotes, search_securities
```

### Options Analytics
**Use for:** Options strategy analysis, Greeks calculation
```
Claude: "What are the Greeks for a 250 call on AAPL expiring Sept 18?"
Tools: get_options_chains, get_options_Greeks, get_implied_volatility
```

## Error Handling & Troubleshooting

### Connection Issues

**Problem:** "Cannot connect to Alpaca API"
**Solution:**
```bash
# Verify credentials
echo $APCA_API_KEY_ID
echo $APCA_API_SECRET_KEY

# Test connection manually
curl -H "Authorization: Bearer $APCA_API_KEY_ID" \
  https://paper-api.alpaca.markets/v2/account
```

### Authentication Errors

**Problem:** "Unauthorized - Invalid API Key"
**Solution:**
- Regenerate API keys in Alpaca dashboard
- Clear old environment variables
- Restart MCP server
- Verify key has correct permissions

### Order Placement Failures

**Problem:** "Insufficient buying power"
**Solution:**
```
Claude: "What's my available buying power?"
Claude uses: GET /v2/account
Result: Shows exact amount available
Action: Adjust order size accordingly
```

### Slow Performance

**Problem:** "Tools are slow to respond"
**Solution:**
```bash
# Check server logs
# Restart MCP server
# Verify internet connection
# Check Alpaca API status
```

## Best Practices

1. **Start Simple:**
   - Test basic account queries first
   - Place small test orders
   - Verify order execution

2. **Use Proper Position Sizing:**
   - Never use 100% of buying power
   - Keep 20-30% reserved
   - Scale up gradually

3. **Risk Management:**
   - Always set stop losses
   - Use bracket orders for protection
   - Monitor positions actively

4. **Data Analysis:**
   - Get multiple days of bars for better analysis
   - Consider different timeframes
   - Verify data before trading

5. **Logging & Auditing:**
   - Keep logs of Claude interactions
   - Record all orders executed
   - Monitor P&L regularly

## Advanced Features

### Real-time Streaming

Claude can request real-time data streams:
```
User: "Stream live price updates for AAPL"
Claude: Sets up WebSocket connection
Result: Real-time price updates in chat
```

### Multi-leg Options Orders

Claude can handle complex options strategies:
```
User: "Create an iron condor: 
       Sell 400 put, Buy 395 put,
       Sell 415 call, Buy 420 call"
Claude: Executes as single multi-leg order
```

### Algorithmic Trading

Claude can implement algorithms:
```
User: "Implement a simple momentum strategy"
Claude:
├─ Gets historical data
├─ Calculates momentum indicator
├─ Places orders based on signals
└─ Monitors and adjusts automatically
```

## Monitoring & Maintenance

### Health Checks

```bash
# Check server status
curl http://localhost:3000/health

# View server logs
journalctl -u alpaca-mcp-server -f

# Monitor resources
top | grep alpaca-mcp-server
```

### Performance Monitoring

```bash
# Monitor API response times
# Check rate limit usage
# Track order execution times
# Monitor streaming connections
```

## Documentation & Support

- **Official Docs:** https://docs.alpaca.markets/us/docs/alpaca-mcp-server
- **GitHub:** https://github.com/alpacahq/alpaca-mcp-server
- **Blog Post:** https://alpaca.markets/blog/alpacas-mcp-server-for-trading-api-adds-documentation-access/
- **Community:** Alpaca Discord & Forums

---

**Last Updated:** August 26, 2026

**Pro Tip:** Start with Claude asking questions about your account, then progress to simple orders, then complex strategies.
