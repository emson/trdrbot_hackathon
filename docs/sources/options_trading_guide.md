# Options Trading Guide for Alpaca Hackathon

## Options Basics

Options are contracts that give you the right (but not obligation) to buy or sell a stock at a specific price on or before a specific date.

### Key Terms

- **Call Option:** Right to BUY stock at strike price
- **Put Option:** Right to SELL stock at strike price
- **Strike Price:** The fixed price at which you can buy/sell
- **Expiration Date:** Date when option expires and becomes worthless (usually Friday)
- **Premium:** Price you pay for the option (per share × 100 = contract price)
- **In the Money (ITM):** Option has intrinsic value
- **Out of the Money (OTM):** Option has no intrinsic value
- **At the Money (ATM):** Stock price equals strike price

### Greeks (Risk Measures)

- **Delta:** How much option price changes with 1% stock move (0-1 for calls)
- **Gamma:** How much delta changes with 1% stock move (curvature)
- **Theta:** Daily time decay (negative, options lose value daily)
- **Vega:** Sensitivity to implied volatility (higher IV = higher premium)
- **Rho:** Sensitivity to interest rate changes

## Options Strategies

### 1. Long Call (Bullish)

**Best For:** Bullish outlook with defined risk

```
Buy 1 Call
Strike: $150
Expiration: Sept 18
Premium: $5

Max Profit: Unlimited
Max Loss: $500 (premium paid)
Breakeven: $155
```

**Use Case:** You think AAPL will rise above $155 before Sept 18

**How to Execute:**
```python
api.submit_order(
    symbol="AAPL",
    qty=1,
    side="buy",
    type="option",
    option_symbol="AAPL_180921C150",  # Call, Sept 18, $150 strike
)
```

### 2. Long Put (Bearish)

**Best For:** Bearish outlook with defined risk

```
Buy 1 Put
Strike: $150
Expiration: Sept 18
Premium: $5

Max Profit: $14,500 (strike - premium)
Max Loss: $500 (premium paid)
Breakeven: $145
```

**Use Case:** You think AAPL will fall below $145 before Sept 18

### 3. Bull Call Spread (Bullish, Limited Risk/Reward)

**Best For:** Bullish but want to limit cost and risk

```
Buy Call @ $150
Sell Call @ $155
Both expiring Sept 18
Net Cost: $2 per contract ($200 total)

Max Profit: $500
Max Loss: $200
Breakeven: $152
```

**Pros:**
- Lower cost than buying call outright
- Limited risk
- Good for moderate bullish outlook

**Cons:**
- Limited profit potential
- Need to monitor two positions

**Execution:**
```python
# Multi-leg order
api.submit_order(
    symbol="AAPL",
    qty=10,  # 10 spreads
    side="buy",
    type="option",
    strategy="spread",
    legs=[
        {"contract": "AAPL_180921C150", "qty": 10, "side": "buy"},
        {"contract": "AAPL_180921C155", "qty": 10, "side": "sell"}
    ]
)
```

### 4. Bear Put Spread (Bearish/Neutral, Income)

**Best For:** Generate income in sideways/up market

```
Sell Put @ $145
Buy Put @ $140
Both expiring Sept 18
Net Credit: $2 per contract ($200 total)

Max Profit: $200 (premium collected)
Max Loss: $300 (width - credit)
Breakeven: $143
```

**Pros:**
- Generate immediate income
- Protected on downside below $140
- Good for neutral-to-bullish outlook

**Cons:**
- Need margin
- Max loss if stock drops significantly
- Requires active monitoring

### 5. Straddle (High Volatility Play)

**Best For:** Expecting big move in either direction

```
Buy Call @ $150
Buy Put @ $150
Both expiring Sept 18
Total Cost: $10 ($1000)

Max Profit: Unlimited up, Significant down
Max Loss: $1000
Breakeven: $140 or $160
```

**Use Case:** Before earnings announcement expecting volatility

### 6. Strangle (Low Cost High Volatility Play)

**Best For:** Expecting move, want lower cost than straddle

```
Buy Call @ $155
Buy Put @ $145
Both expiring Sept 18
Total Cost: $5 ($500)

Max Profit: Unlimited (but need bigger move)
Max Loss: $500
Breakeven: $140 or $160
```

**Same as straddle but cheaper** - good if you expect large move

### 7. Iron Condor (High Probability, Limited Risk)

**Best For:** Selling premium in sideways market

```
Sell Put @ $145
Buy Put @ $140
Sell Call @ $160
Buy Call @ $165
All expiring Sept 18
Net Credit: $2 ($200)

Max Profit: $200
Max Loss: $300
Profit Range: $140-$160
```

**Pros:**
- High probability (win if stock stays in range)
- Good premium collection
- Protected on both sides

**Cons:**
- Complex (4 legs)
- Requires monitoring
- Margin requirement

### 8. Covered Call (Income on Stock)

**Best For:** Own stock and want income

```
Own 100 AAPL shares @ $150
Sell 1 Call @ $155
Premium: $2 ($200)

Income: $200 (premium)
Risk: Stock called away if rises above $155
```

**Use Case:** You own stock and want to generate income

### 9. Protective Put (Downside Protection)

**Best For:** Own stock, want insurance

```
Own 100 AAPL shares @ $150
Buy 1 Put @ $145
Premium: $2 ($200)

Cost: $200 (insurance)
Protected below: $145
Profit above: Unlimited
```

**Use Case:** You own stock but worried about downside

### 10. Collar (Protected Buy)

**Best For:** Own stock, hedge risk but reduce cost

```
Own 100 AAPL shares @ $150
Buy Put @ $145 ($2 cost)
Sell Call @ $160 ($2 credit)
Net Cost: $0

Protected: Can't lose below $145
Max profit: Limited to $160
```

**Best for hacky: Free protection**

## Paper Trading Options in Alpaca

### Automatic Level 3 Access

✅ **Paper trading accounts automatically get:**
- Single leg options (calls & puts)
- Multi-leg options (spreads, straddles, etc.)
- Level 3 strategy approval
- No margin requirements for spreads
- Simulated greeks and pricing
- Real market data for options

### Supported Option Types in Paper Trading

| Strategy | Supported | Notes |
|----------|-----------|-------|
| Long Call | ✅ Yes | Full support |
| Long Put | ✅ Yes | Full support |
| Short Call | ✅ Yes | With margin |
| Short Put | ✅ Yes | With margin |
| Call Spread | ✅ Yes | Multi-leg |
| Put Spread | ✅ Yes | Multi-leg |
| Iron Condor | ✅ Yes | 4-leg order |
| Straddle | ✅ Yes | Multi-leg |
| Strangle | ✅ Yes | Multi-leg |
| Collar | ✅ Yes | Multi-leg |
| Calendar Spreads | ✅ Yes | Different expirations |
| Diagonals | ✅ Yes | Different strikes & dates |

## Alpaca Options API

### Getting Options Data

```python
from alpaca_trade_api import REST

api = REST()

# Get options chains (all strikes and expirations)
chains = api.get_options_chains("AAPL")

# Get specific options contracts
contracts = api.get_options_contracts(
    symbol="AAPL",
    expiration="2026-09-18"
)

# Get options bars (historical data)
bars = api.get_options_bars(
    contract="AAPL_180921C150",
    start="2026-08-01"
)
```

### Placing Options Orders

```python
# Single leg - Buy a call
call_order = api.submit_order(
    symbol="AAPL",
    qty=5,  # 5 contracts
    side="buy",
    type="option",
    option_symbol="AAPL_180921C150"
)

# Multi-leg - Bull call spread
spread_order = api.submit_order(
    symbol="AAPL",
    qty=10,  # 10 spreads
    side="buy",
    type="option",
    strategy="spread",
    legs=[
        {"side": "buy", "qty": 10, "strike": 150, "type": "call"},
        {"side": "sell", "qty": 10, "strike": 155, "type": "call"}
    ],
    expiration="2026-09-18"
)
```

### Getting Options Greeks

```python
# Get greeks for a contract
contract = api.get_options_contract("AAPL_180921C150")
print(f"Delta: {contract.greeks.delta}")
print(f"Gamma: {contract.greeks.gamma}")
print(f"Theta: {contract.greeks.theta}")
print(f"Vega: {contract.greeks.vega}")

# Calculate implied volatility
iv = api.get_implied_volatility("AAPL")
print(f"AAPL IV: {iv}%")
```

## Strategy Selection for Hackathon

### For Beginners
1. **Long Call** - Simple bullish play
2. **Long Put** - Simple bearish play
3. **Bull Call Spread** - Limited risk bullish

### For Intermediate
1. **Bear Put Spread** - Income generation
2. **Straddle** - Volatility play (great for earnings)
3. **Covered Call** - If you buy stock

### For Advanced
1. **Iron Condor** - Complex but high probability
2. **Calendar Spreads** - Time decay plays
3. **Diagonal Spreads** - Combine directional + time decay

## Tips for Hackathon Success

### Strategy Design
1. **Pick Simple First:** Start with bull/bear spreads
2. **Use Paper Trading:** Test extensively
3. **Track Results:** Log all trades and P&L
4. **Calculate Greeks:** Show understanding of risk
5. **Optimize Expiration:** Use nearest dates initially

### Implementation Tips
1. **Use Claude/MCP:** Let Claude analyze and suggest strategies
2. **Automate Analysis:** Have Claude pull greeks and IV
3. **Set Alerts:** Monitor positions actively
4. **Rebalance:** Adjust trades if price moves significantly
5. **Document Logic:** Explain why you chose each strategy

### Winning Approach
- Use **AI to analyze** market conditions
- AI **suggests options strategies** based on analysis
- AI **executes trades** through MCP
- You **monitor and adjust**
- Show **detailed P&L and Greeks** analysis
- Document **strategy logic** clearly

## Common Mistakes to Avoid

1. ❌ Not understanding Greeks
2. ❌ Using too much capital on single trade
3. ❌ Not setting stop losses
4. ❌ Ignoring time decay (especially near expiration)
5. ❌ Over-complicating strategies
6. ❌ Not testing in paper trading first
7. ❌ Forgetting about liquidity (tight spreads)
8. ❌ Not considering assignment risk

## Resources

- **Alpaca Options Guide:** https://alpaca.markets/learn/how-to-trade-options-with-alpaca
- **Options Basics:** https://www.investopedia.com/terms/o/option.asp
- **Greeks Calculator:** Various online tools
- **Paper Trading Practice:** Use Alpaca paper account extensively

---

**Last Updated:** August 26, 2026

**Remember:** Options are leveraged instruments. Always understand your risk before trading!
