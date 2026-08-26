# Alpaca Trading API Summary

## API Overview

The Alpaca Trading API is a REST-based API that allows developers to build trading applications. It provides access to:

- **Account Management:** Account information, buying power, cash balance
- **Order Management:** Place, cancel, modify, and track orders
- **Position Management:** Track open positions and P&L
- **Market Data:** Real-time and historical price data
- **Options Trading:** Place and manage options orders
- **Webhooks:** Real-time event notifications

## Authentication

### Required Credentials
- **API Key ID:** Unique identifier for your application
- **API Secret Key:** Secret for signing requests
- **Base URL (Paper Trading):** https://paper-api.alpaca.markets
- **Base URL (Live Trading):** https://api.alpaca.markets

### Storing Credentials Securely

**NEVER commit credentials to Git!**

Use environment variables:
```bash
export APCA_API_KEY_ID="your_key_id"
export APCA_API_SECRET_KEY="your_secret_key"
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
```

## Core API Endpoints

### Account Endpoints
- `GET /v2/account` - Get account information
- `GET /v2/account/portfolio_history` - Get account history
- `GET /v2/account/configurations` - Get account settings

### Order Endpoints
- `POST /v2/orders` - Submit new order
- `GET /v2/orders` - Get list of orders
- `GET /v2/orders/{order_id}` - Get specific order
- `PATCH /v2/orders/{order_id}` - Modify order
- `DELETE /v2/orders/{order_id}` - Cancel order
- `DELETE /v2/orders` - Cancel all orders

### Position Endpoints
- `GET /v2/positions` - Get all positions
- `GET /v2/positions/{symbol}` - Get specific position
- `DELETE /v2/positions/{symbol}` - Close position

### Market Data Endpoints
- `GET /v1/last/stocks/{symbols}` - Get latest stock price
- `GET /v1/last_quote/stocks/{symbols}` - Get latest quote
- `GET /v1/bars/stocks/{symbols}` - Get bars (OHLCV data)

### Options Endpoints
- `GET /v2/options/chains` - Get options chains
- `GET /v2/options/contracts` - Get options contracts
- `POST /v2/orders` - Place options orders
- `GET /v2/positions` - Get options positions

## Order Types

### Simple Orders
- **Market:** Execute at current market price immediately
- **Limit:** Execute at specified price or better
- **Stop:** Execute when price reaches stop level
- **Stop-Limit:** Combines stop and limit logic

### Advanced Orders
- **Bracket Order:** Buy + profit target + stop loss
- **Trailing Stop:** Dynamic stop that follows price
- **OCO (One-Cancels-Other):** Two orders, one cancels the other if filled

### Options Orders
- **Single Leg:** Call or put on one contract
- **Multi-Leg:** Spreads, straddles, strangles, condors
- **Covered Call:** Stock + short call
- **Collar:** Stock + call + put protection

## Time in Force Options
- **DAY:** Order expires at end of trading day
- **GTC:** Good-til-canceled (stays until filled or manually canceled)
- **OPG:** Opening order (fills at market open)
- **CLS:** Closing order (fills at market close)

## Paper Trading Features

### Available in Paper Trading
- ✅ All order types
- ✅ Options trading (Level 3 by default)
- ✅ Market data (real-time)
- ✅ Multi-leg options orders
- ✅ Account management
- ✅ Position tracking
- ✅ $100,000 starting capital
- ✅ Order history and analytics

### Differences from Live Trading
- Virtual funds only
- No slippage simulation (orders fill instantly)
- No market impact consideration
- Can reset funds anytime
- No regulatory margin requirements

## Python SDK Usage Examples

### Installation
```bash
pip install alpaca-trade-api
```

### Get Account Information
```python
from alpaca_trade_api import REST

api = REST()

account = api.get_account()
print(f"Account Number: {account.account_number}")
print(f"Buying Power: ${account.buying_power}")
print(f"Cash: ${account.cash}")
print(f"Portfolio Value: ${account.portfolio_value}")
```

### Place a Stock Order
```python
# Market order
order = api.submit_order(
    symbol="AAPL",
    qty=10,
    side="buy",
    type="market",
    time_in_force="day"
)

# Limit order
order = api.submit_order(
    symbol="AAPL",
    qty=10,
    side="buy",
    type="limit",
    limit_price=150.00,
    time_in_force="gtc"
)
```

### Get Market Data
```python
from alpaca_trade_api.rest import TimeFrame

# Get latest quote
quote = api.get_latest_quote("AAPL")
print(f"AAPL Price: ${quote.last_quote.ask_price}")

# Get bars (OHLCV data)
bars = api.get_bars(
    "AAPL",
    TimeFrame.Day,
    start="2026-01-01",
    end="2026-08-26"
)
for bar in bars:
    print(f"{bar.t} - Close: ${bar.c}")
```

### Stream Real-time Data
```python
from alpaca_trade_api import Stream

stream = Stream()

async def on_bars(data):
    print(f"Bar received: {data}")

stream.subscribe_bars(on_bars, "AAPL")
```

## Node.js SDK Usage Examples

### Installation
```bash
npm install alpaca-trade-api
```

### Get Account Information
```javascript
const Alpaca = require("@alpacahq/alpaca-trade-api");

const alpaca = new Alpaca();

async function getAccount() {
  const account = await alpaca.getAccount();
  console.log(account);
}

getAccount();
```

### Place Order
```javascript
async function placeOrder() {
  const order = await alpaca.createOrder({
    symbol: "AAPL",
    qty: 10,
    side: "buy",
    type: "market",
    time_in_force: "day"
  });
  console.log(order);
}
```

## API Rate Limits

- **REST API:** 200 requests per minute
- **WebSocket:** Per-connection limits apply
- **Data Requests:** Depends on subscription level

## Common Response Codes

- **200 OK:** Request successful
- **201 Created:** Resource created
- **400 Bad Request:** Invalid request format
- **401 Unauthorized:** Authentication failed
- **403 Forbidden:** Permission denied
- **404 Not Found:** Resource not found
- **422 Unprocessable Entity:** Validation error
- **429 Too Many Requests:** Rate limit exceeded

## Error Handling

Always include error handling in production code:

```python
try:
    order = api.submit_order(
        symbol="AAPL",
        qty=10,
        side="buy",
        type="market"
    )
except Exception as e:
    print(f"Order failed: {e}")
```

## Webhook Integration

Set up webhooks to receive real-time event notifications:

```python
# Available events
# - order_fill
# - account_update
# - trade_update
# - etc.

# Configure in Alpaca Dashboard
# Webhook URL receives POST requests with event data
```

## Best Practices

1. **Use Paper Trading First:**
   - Test all strategies in paper trading
   - Verify API integration works
   - Monitor for edge cases

2. **Error Handling:**
   - Implement proper try/catch blocks
   - Log all errors
   - Implement retry logic for transient failures

3. **Performance:**
   - Cache market data where appropriate
   - Use efficient data structures
   - Batch requests when possible

4. **Security:**
   - Never log API keys
   - Use environment variables
   - Implement request signing
   - Monitor account for unusual activity

5. **Order Management:**
   - Always set stop losses
   - Use position sizing
   - Monitor open orders
   - Implement order cancel logic

## Documentation Links

- **Full API Reference:** https://docs.alpaca.markets/
- **Python SDK:** https://github.com/alpacahq/alpaca-py
- **Node.js SDK:** https://github.com/alpacahq/alpaca-trade-api-js
- **Trading Guide:** https://alpaca.markets/learn/

---

**Last Updated:** August 26, 2026
