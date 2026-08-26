# Getting Started Guide

## Quick Start Checklist

- [x] Team registered on lablab.ai (Team: trdrbot)
- [x] Alpaca paper trading account created
- [ ] API keys generated and stored securely
- [ ] Development environment set up
- [ ] Alpaca MCP Server configured
- [ ] First trade executed (test)
- [ ] Trading strategy development begins
- [ ] Options trading implemented
- [ ] Project documentation prepared
- [ ] Final submission before September 4 15:00 UTC

## Step 1: Secure Your API Keys

### Generate API Keys from Alpaca

1. Log in to https://app.alpaca.markets/account/login
2. Navigate to API Keys section
3. Select "Paper Trading" account
4. Copy your:
   - **API Key ID**
   - **API Secret Key**

### Store Securely

Never commit API keys to Git. Use environment variables:

```bash
# .env file (add to .gitignore!)
APCA_API_KEY_ID=your_key_here
APCA_API_SECRET_KEY=your_secret_here
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

Or set directly in terminal:
```bash
export APCA_API_KEY_ID="your_key_here"
export APCA_API_SECRET_KEY="your_secret_here"
```

## Step 2: Set Up Development Environment

### Option A: Python (Recommended for quick start)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install alpaca-trade-api requests pandas numpy

# Verify connection
python -c "from alpaca_trade_api import REST; api = REST(); print(api.get_account())"
```

### Option B: Node.js

```bash
# Initialize project
npm init -y

# Install dependencies
npm install alpaca-trade-api dotenv

# Create .env file with your credentials
# Verify connection in a test script
```

### Option C: Use Claude/Cursor with MCP Server

This is the **recommended approach** for the hackathon since it leverages AI:

1. Set up Alpaca MCP Server (see below)
2. Configure Claude or Cursor to use MCP Server
3. Let AI make trading decisions through structured tools

## Step 3: Configure Alpaca MCP Server

### For Claude/Cursor Integration

1. **Install MCP Server:**
   ```bash
   npm install -g @alpaca/mcp-server
   # or
   pip install alpaca-mcp-server
   ```

2. **Configure Environment:**
   ```bash
   export APCA_API_KEY_ID="your_key"
   export APCA_API_SECRET_KEY="your_secret"
   ```

3. **Start MCP Server:**
   ```bash
   alpaca-mcp-server
   ```

4. **In Claude/Cursor:**
   - Configure MCP server connection
   - Test connection with a simple query
   - Access 65 trading and market data tools

**Documentation:** https://docs.alpaca.markets/us/docs/alpaca-mcp-server

## Step 4: Test Basic Trading

### First Trade (Paper Trading)

```python
from alpaca_trade_api import REST

api = REST()

# Get account info
account = api.get_account()
print(f"Account: {account.account_number}")
print(f"Buying Power: {account.buying_power}")
print(f"Cash: {account.cash}")

# Place a test market order (for testing, use $1-5 worth)
order = api.submit_order(
    symbol="AAPL",
    qty=1,
    side="buy",
    type="market",
    time_in_force="day"
)
print(f"Order placed: {order.id}")
```

### Using Claude/Cursor with MCP

Prompt Claude:
> "Using the Alpaca trading tools, buy 1 share of AAPL at market price in my paper trading account"

Claude will use the MCP tools to execute the trade.

## Step 5: Develop Your Strategy

### Strategy Framework

1. **Data Collection**
   - Fetch market data via Alpaca API
   - Analyze price, volume, technical indicators
   - Consider economic calendar events

2. **Trading Logic**
   - Entry conditions (when to buy/sell)
   - Exit conditions (when to close positions)
   - Risk management (stop losses, position sizing)

3. **Options Implementation** (REQUIRED)
   - Choose options strategy:
     - Bull call spread (bullish)
     - Bear put spread (bearish)
     - Iron condor (range-bound)
     - Straddle (high volatility)
     - Collar (downside protection)
   - Define entry/exit rules
   - Calculate Greeks (delta, gamma, theta, vega)

4. **Execution**
   - Use Alpaca API to place orders
   - Track open positions
   - Monitor P&L

### Sample Options Trading Pattern

```python
# Using Python and Alpaca API
import alpaca_trade_api as tradeapi

api = tradeapi.REST()

# Buy a call option
buy_call = {
    "symbol": "AAPL",
    "right": "C",  # Call
    "expiration_date": "2026-09-18",
    "strike": "230",
    "qty": 5,
    "side": "buy"
}

# Sell a call option (to create a spread)
sell_call = {
    "symbol": "AAPL", 
    "right": "C",
    "expiration_date": "2026-09-18",
    "strike": "235",
    "qty": 5,
    "side": "sell"
}

# Execute as multi-leg order
```

## Step 6: Build with AI (Recommended)

### Claude + Alpaca MCP Approach

1. **Define Trading Goals**
   ```
   "I want to build a trading agent that:
   - Analyzes market sentiment
   - Executes bull call spreads when bullish
   - Executes bear put spreads when bearish
   - Manages risk with position sizing"
   ```

2. **Let Claude Help**
   - Use Claude to generate trading logic
   - Have Claude execute trades via MCP
   - Let Claude analyze results
   - Iterate and improve

3. **Example Workflow**
   ```
   You: "Analyze AAPL sentiment and suggest an options trade"
   Claude: [Analyzes data via MCP tools, suggests strategy]
   You: "Execute your suggestion"
   Claude: [Places orders, confirms execution]
   ```

## Step 7: Monitor & Iterate

### Daily Development Tasks

- [ ] Check paper account P&L
- [ ] Review trade execution quality
- [ ] Adjust strategy based on results
- [ ] Test new options strategies
- [ ] Improve risk management
- [ ] Document changes

### Week of September 2-4

- [ ] Finalize strategy
- [ ] Prepare documentation
- [ ] Create demo/screenshots
- [ ] Test submission process
- [ ] Submit by Sept 4, 15:00 UTC

## Key Resources

### Official Documentation
- [Alpaca Trading API Docs](https://docs.alpaca.markets/)
- [MCP Server Documentation](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- [Options Trading Guide](https://alpaca.markets/learn/how-to-trade-options-with-alpaca)
- [Paper Trading Guide](https://alpaca.markets/learn/start-paper-trading)

### SDKs & Libraries
- [Alpaca-py (Python SDK)](https://github.com/alpacahq/alpaca-py)
- [alpaca-trade-api (Node.js)](https://github.com/alpacahq/alpaca-trade-api-js)
- [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server)

### Community
- [lablab.ai Discord](https://lablab.ai/)
- [Alpaca Community Slack](https://alpaca.markets/)
- [GitHub Discussions](https://github.com/alpacahq)

## Tips for Success

1. **Start Simple**
   - Master basic buy/sell before complex strategies
   - Test one options strategy at a time
   - Build confidence with paper trading

2. **Use AI Effectively**
   - Leverage Claude/Cursor to generate code
   - Have AI help analyze market data
   - Let AI suggest strategy improvements

3. **Risk Management**
   - Never risk more than 2-5% per trade
   - Use stop losses religiously
   - Test extensively in paper trading

4. **Documentation**
   - Document your strategy clearly
   - Explain why you chose options strategies
   - Show trading results and performance

5. **Collaboration**
   - Divide work among team members
   - Use version control (Git)
   - Regular sync-ups on progress

6. **Time Management**
   - Start immediately (don't wait)
   - Dedicate focused development time
   - Leave buffer time for troubleshooting

## Troubleshooting

### API Connection Issues
- Verify API keys are correct
- Ensure paper trading account is selected
- Check internet connection
- Review Alpaca status page

### Trading Errors
- Verify you have sufficient buying power
- Check symbol spelling
- Ensure order type is valid for options
- Review order restrictions (market hours, etc.)

### MCP Server Issues
- Ensure environment variables are set
- Restart server after changes
- Check server logs for errors
- Verify Claude/Cursor configuration

---

**Last Updated:** August 26, 2026

**Get Help:** Check lablab.ai Discord community or Alpaca support channels
