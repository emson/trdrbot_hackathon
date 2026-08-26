# Quick Reference Guide

## Key Dates & Deadlines

| Item | Date | Time |
|------|------|------|
| **Hackathon Start** | August 28, 2026 | 00:00 UTC |
| **Submission Deadline** | September 4, 2026 | 15:00 UTC |
| **Judging Begins** | September 4, 2026 | 15:00 UTC |
| **Winner Announcement** | TBD | TBD |

⏱️ **Time Remaining:** ~9 days of development time

## Team Info

- **Team Name:** trdrbot
- **Platform:** lablab.ai
- **Hackathon:** Alpaca AI Trading Agents
- **Prize Pool:** $6,000 USD

## Account Setup Checklist

- [x] Team registered on lablab.ai
- [x] Alpaca paper trading account created
- [ ] API keys generated (from https://app.alpaca.markets/account/login)
- [ ] API keys stored securely (environment variables)
- [ ] Development environment configured
- [ ] First test trade executed
- [ ] Options trading enabled (automatic for paper accounts)

## Required for Submission

1. ✅ **New Alpaca Paper Trading Account** (Created)
2. ✅ **Functional Trading Agent** (Development in progress)
3. ✅ **Options Trading Implementation** (REQUIRED)
4. ✅ **Submission via lablab.ai** (Before Sept 4, 15:00 UTC)

## Environment Variables

```bash
export APCA_API_KEY_ID="your_api_key_id"
export APCA_API_SECRET_KEY="your_api_secret_key"
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
```

## API Integration Options

### 1. MCP Server (Recommended) ⭐
- Best for: Using Claude/Cursor for trading decisions
- Tools: 65 tools for trading and market data
- Setup: `alpaca-mcp-server` or `@alpaca/mcp-server`
- Cost: Zero (included)
- Docs: https://docs.alpaca.markets/us/docs/alpaca-mcp-server

### 2. REST API
- Best for: Direct programmatic access
- SDKs: Python (alpaca-py), Node.js (alpaca-trade-api-js)
- Setup: Install SDK, authenticate with keys
- Docs: https://docs.alpaca.markets/

### 3. CLI
- Best for: Scripted automation
- Setup: `alpaca-cli` package
- Use: Command-line trading automation

## Quick Commands

### Get Account Info (Python)
```python
from alpaca_trade_api import REST
api = REST()
account = api.get_account()
print(f"Buying Power: ${account.buying_power}")
```

### Place Stock Order (Python)
```python
order = api.submit_order(
    symbol="AAPL",
    qty=10,
    side="buy",
    type="market"
)
```

### Get Market Data (Python)
```python
bars = api.get_bars("AAPL", "day", start="2026-08-01")
quote = api.get_latest_quote("AAPL")
```

### Place Options Order (Python)
```python
order = api.submit_order(
    symbol="AAPL",
    qty=5,
    side="buy",
    type="option",
    option_symbol="AAPL_180921C150"
)
```

## Documentation Hub

| Topic | Location |
|-------|----------|
| **Hackathon Overview** | `docs/hackathon_overview.md` |
| **Getting Started** | `docs/getting_started.md` |
| **Technical Setup** | `docs/technical_setup.md` |
| **Submission Guide** | `docs/submission_and_judging.md` |
| **Resource Links** | `docs/resources.md` |
| **Alpaca API** | `docs/sources/alpaca_api_summary.md` |
| **MCP Server** | `docs/sources/mcp_server_setup.md` |
| **Options Trading** | `docs/sources/options_trading_guide.md` |

## Important URLs

### Hackathon
- Main Page: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
- Live Submissions: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon/live
- lablab.ai: https://lablab.ai/

### Alpaca
- Login: https://app.alpaca.markets/account/login
- API Docs: https://docs.alpaca.markets/
- MCP Server: https://alpaca.markets/mcp-server
- Blog: https://alpaca.markets/blog/
- Learning: https://alpaca.markets/learn/

### Code Repositories
- Alpaca GitHub: https://github.com/alpacahq
- Alpaca MCP Server: https://github.com/alpacahq/alpaca-mcp-server
- Alpaca-py SDK: https://github.com/alpacahq/alpaca-py

## Paper Trading Account Features

| Feature | Status |
|---------|--------|
| Starting Capital | $100,000 (simulated) |
| Real Market Data | ✅ Yes |
| Options Trading | ✅ Yes (Level 3) |
| Single-leg Options | ✅ Yes |
| Multi-leg Options | ✅ Yes |
| Market Hours | Matches real market |
| Slippage Simulation | No (ideal execution) |
| Real Money Risk | ✅ None |
| Reset Funds | ✅ Can reset anytime |

## Trading Strategy Checklist

### Before Development
- [ ] Read options trading guide
- [ ] Understand Greeks (Delta, Gamma, Theta, Vega)
- [ ] Decide on strategy type (spreads, straddles, etc.)
- [ ] Test in paper trading environment

### During Development
- [ ] Implement data collection
- [ ] Build trading logic
- [ ] Implement options trading
- [ ] Add risk management (stop losses, position sizing)
- [ ] Test extensively
- [ ] Monitor P&L
- [ ] Document everything

### Before Submission
- [ ] Finalize strategy
- [ ] Prepare project documentation
- [ ] Create demo/screenshots
- [ ] Verify all links work
- [ ] Test submission process
- [ ] Submit 1-2 hours early

## Recommended Strategy Types

### Simple (Start Here)
- Bull Call Spread
- Bear Put Spread
- Long Call/Put

### Intermediate
- Iron Condor
- Straddle/Strangle
- Covered Call

### Advanced
- Calendar Spreads
- Diagonal Spreads
- Algorithm-based multi-leg

## Common Issues & Solutions

| Problem | Solution |
|---------|----------|
| API Connection Failed | Check API keys, verify paper trading selected |
| Order Won't Fill | Verify buying power, check market hours, confirm order type |
| Options Not Trading | Options auto-enabled in paper, verify contract symbol |
| Slow Performance | Restart MCP server, check internet connection |
| Can't Find Documentation | See resources.md for all links |

## Success Metrics

Track these to judge your project:

- **Return on Investment (ROI):** % return on $100k
- **Sharpe Ratio:** Risk-adjusted returns
- **Max Drawdown:** Largest peak-to-trough loss
- **Win Rate:** % of trades that profit
- **Average Trade:** Average profit per trade
- **Options Usage:** % of trades using options
- **Consistency:** Regular profits vs. lucky trades
- **Code Quality:** Clean, well-documented code
- **Strategy Logic:** Clear, sound trading rationale

## Pro Tips

1. **Start with Claude + MCP** - Leverage AI for intelligence
2. **Test in Paper First** - Always test before submitting
3. **Use Multiple Strategies** - Show options expertise
4. **Document Everything** - Clear docs = higher scores
5. **Monitor Greeks** - Show understanding of options risk
6. **Automate Everything** - Let AI do the work
7. **Track Metrics** - Keep detailed performance logs
8. **Submit Early** - Don't risk deadline issues

## Troubleshooting Links

- **Alpaca Issues:** https://alpaca.markets/
- **lablab.ai Support:** https://lablab.ai/
- **MCP Server Docs:** https://docs.alpaca.markets/us/docs/alpaca-mcp-server
- **Trading Guide:** https://alpaca.markets/learn/

## Daily Routine

**Week 1 (Aug 28 - Sept 1)**
- [ ] Setup complete, first trades executed
- [ ] Strategy defined and documented
- [ ] Options trading implemented
- [ ] Automation in place

**Week 2 (Sept 1 - 4)**
- [ ] Strategy refined based on testing
- [ ] Performance optimized
- [ ] Documentation finalized
- [ ] Submit before Sept 4, 15:00 UTC

## Contacts & Support

- **lablab.ai:** https://lablab.ai/ (Discord community)
- **Alpaca:** https://alpaca.markets/ (Support portal)
- **Email Support:** Check official websites
- **GitHub Issues:** Report bugs at repository pages

---

**Last Updated:** August 26, 2026

**Good Luck! 🚀**

Remember: This is paper trading. The goal is to demonstrate your ability to build an AI trading agent, not to make the most money!
