# Documentation

Reference material for **trdrbot**, an options-trading agent built for the Alpaca AI Trading
Agents Hackathon. Start at the [repository README](../README.md) for what the project is and how
it fits together; this directory is the long-form material behind it.

## What's in here

**Engineering principles** — the rules the code is held to, portable to any Python project.

| | |
|---|---|
| [`principles_README.md`](principles_README.md) | Index of the three documents below |
| [`principles_coding.md`](principles_coding.md) | How to write and modify production code |
| [`principles_testing.md`](principles_testing.md) | When a test earns its place, and what it must prove |
| [`principles_agent_api.md`](principles_agent_api.md) | How to design tools an LLM agent consumes |

**The build, as it happened**

| | |
|---|---|
| [`dev_journals/`](dev_journals) | Nine dated entries: what was built, what broke, why a fix won |
| [`plan_risk_appetite.md`](plan_risk_appetite.md), [`plan_defect_remediation.md`](plan_defect_remediation.md) | Two completed plans, kept as the record of their reasoning |
| [`website_build_transcript.md`](website_build_transcript.md) | How trdrbot.com was built and deployed |

**Presentation and design**

| | |
|---|---|
| [`deck.html`](deck.html) / [`deck.pdf`](deck.pdf) | The slide deck ([hosted](https://trdrbot.com/deck.html)) |
| [`design_system.md`](design_system.md) / [`design_system.html`](design_system.html) | The two type-and-shape registers the site and deck share |
| [`architecture_explorer.html`](architecture_explorer.html), [`risk_appetite_explorer.html`](risk_appetite_explorer.html) | Interactive explainers, published under trdrbot.com/resources |

**Research and domain notes**

| | |
|---|---|
| [`research_risk_appetite.md`](research_risk_appetite.md) | The measured basis for the risk-appetite lever |
| [`market_selection.md`](market_selection.md) | Why this watchlist |
| [`sources/`](sources) | Deep dives: Alpaca API, the MCP server, options strategies, Greeks, OKF, Polymarket |

**Hackathon reference** — verified against the live event page; the requirements themselves are in
[`submission_and_judging.md`](submission_and_judging.md).

| | |
|---|---|
| [`submission_and_judging.md`](submission_and_judging.md) | Deliverables, judging criteria, deadline, MIT requirement |
| [`submission_assets_checklist.md`](submission_assets_checklist.md) | What still has to exist before submitting |
| [`hackathon_overview.md`](hackathon_overview.md), [`quick_reference.md`](quick_reference.md) | Event context and fast answers |
| [`technical_setup.md`](technical_setup.md), [`getting_started.md`](getting_started.md) | Account, keys and environment setup |
| [`resources.md`](resources.md), [`social_media_playbook.md`](social_media_playbook.md) | Official links; build-in-public plan |

---

# The original pre-build guide

*Everything below was written on 2026-08-26, before the agent existed, to orient the team at the
start of the hackathon. It is kept as written - a record of what was known going in. Where it
describes work still to be done, that work is now done; the sections above are the current map,
and `agent/` commands run from `agent/`, not the repository root.*

## Quick Navigation

### Getting Started (Start Here!)

1. **[quick_reference.md](quick_reference.md)**
   - Key dates, deadlines, and checklists
   - Account setup checklist
   - Essential environment variables
   - Success metrics and daily routine
   - Read this first for quick answers

2. **[hackathon_overview.md](hackathon_overview.md)**
   - Event summary and key concepts
   - Timeline and accessibility
   - Team structure and competition environment
   - What you need to build

3. **[getting_started.md](getting_started.md)**
   - Step-by-step setup guide
   - Environment configuration
   - First test trade walkthrough
   - Strategy development framework
   - Troubleshooting guide

### Technical Documentation

4. **[technical_setup.md](technical_setup.md)**
   - Alpaca account setup details
   - Options trading capabilities
   - API integration options (MCP Server recommended)
   - Build stack recommendations
   - Environment configuration

5. **[submission_and_judging.md](submission_and_judging.md)**
   - Submission timeline and requirements
   - Mandatory deliverables checklist
   - Judging process explanation
   - Prize distribution
   - Best practices for submission

### Reference & Resources

6. **[resources.md](resources.md)**
   - All official documentation links
   - GitHub repositories
   - MCP ecosystem resources
   - Learning materials
   - Related technologies

### Deep Dives (Sources Directory)

7. **[sources/alpaca_api_summary.md](sources/alpaca_api_summary.md)**
   - Comprehensive Alpaca Trading API reference
   - Core endpoints and features
   - Python and Node.js SDK examples
   - Error handling and best practices
   - Authentication and rate limits

8. **[sources/mcp_server_setup.md](sources/mcp_server_setup.md)**
   - Detailed MCP Server installation
   - All 65 tools explained by category
   - Integration with Claude/Cursor
   - Example workflows and use cases
   - Configuration and troubleshooting
   - Key to leveraging AI for trading

9. **[sources/options_trading_guide.md](sources/options_trading_guide.md)**
   - Options basics and terminology
   - 10 options strategies explained (with examples)
   - Greeks (Delta, Gamma, Theta, Vega) explained
   - Alpaca options API reference
   - Strategy selection guide for hackathon
   - Tips for success

10. **[sources/urls_and_links.md](sources/urls_and_links.md)**
    - All official URLs and links
    - Documentation pages
    - GitHub repositories
    - Learning resources
    - Market data providers
    - Organized by category for easy reference

## Directory Structure

```
docs/
├── README.md (you are here)
├── principles_*.md            the engineering rules the code is held to
├── dev_journals/              nine dated build entries
├── plan_*.md                  two completed plans, kept for their reasoning
├── deck.html / deck.pdf       the slide deck
├── design_system.*            the shared type-and-shape registers
├── *_explorer.html            interactive explainers, published to the site
├── research_risk_appetite.*   the measured basis for the risk lever
├── hackathon_*.md,            event context, setup and submission reference
│   submission_*.md,
│   technical_setup.md,
│   getting_started.md,
│   quick_reference.md,
│   resources.md
├── assets/                    images used by the deck and the site
└── sources/                   Alpaca API, MCP server, options, Greeks, OKF, Polymarket
```

## Key Information at a Glance

### Event Details
- **Hackathon:** Alpaca AI Trading Agents
- **Platform:** lablab.ai
- **Start Date:** August 28, 2026
- **Deadline:** September 4, 2026 at 15:00 UTC
- **Prize Pool:** $6,000 USD
- **Team Name:** trdrbot

### Critical Requirements
1. ✅ **Paper Trading Account** - Must be NEW, dedicated account
2. ✅ **Functional Trading Agent** - Using Alpaca API/MCP/CLI
3. ✅ **Options Trading** - REQUIRED component
4. ✅ **Submission** - Before Sept 4, 15:00 UTC

### Recommended Approach
- Use **Claude/Cursor** + **Alpaca MCP Server**
- Let AI analyze markets and suggest strategies
- AI executes trades through structured tools
- You monitor, document, and optimize

### Quick Start (3 Steps)
1. **Setup:** Generate API keys, configure environment
2. **Develop:** Build trading strategy with options
3. **Submit:** Document and submit before deadline

## How to Use This Documentation

### If You're in a Hurry
1. Read [quick_reference.md](quick_reference.md) (5 min)
2. Check [hackathon_overview.md](hackathon_overview.md) (5 min)
3. Start with [getting_started.md](getting_started.md) (10 min)
4. Jump to implementation!

### If You're Learning
1. Start with [hackathon_overview.md](hackathon_overview.md)
2. Follow [getting_started.md](getting_started.md) step-by-step
3. Reference [technical_setup.md](technical_setup.md) for details
4. Use [sources/options_trading_guide.md](sources/options_trading_guide.md) for strategy ideas
5. Check [sources/mcp_server_setup.md](sources/mcp_server_setup.md) for AI integration

### If You're Implementing
1. Consult [technical_setup.md](technical_setup.md) for setup
2. Reference [sources/alpaca_api_summary.md](sources/alpaca_api_summary.md) for API details
3. Use [sources/mcp_server_setup.md](sources/mcp_server_setup.md) for Claude integration
4. Follow [sources/options_trading_guide.md](sources/options_trading_guide.md) for strategy patterns
5. Check [submission_and_judging.md](submission_and_judging.md) before submitting

### If You Have Questions
1. Check [quick_reference.md](quick_reference.md) troubleshooting section
2. Search relevant sections (technical_setup.md, getting_started.md)
3. Review [sources/URLs_AND_LINKS.md](sources/urls_and_links.md) for official help
4. Check specific deep-dive guides in `sources/` directory

## Key Resources

### Documentation Versions
All links and information current as of **August 26, 2026**

### Most Important Pages
1. 🔥 [sources/mcp_server_setup.md](sources/mcp_server_setup.md) - How to leverage Claude for trading
2. 🎯 [sources/options_trading_guide.md](sources/options_trading_guide.md) - Required options strategies
3. ⚙️ [technical_setup.md](technical_setup.md) - Getting everything working
4. ✅ [submission_and_judging.md](submission_and_judging.md) - Don't miss the deadline!

### Official Links
- **Hackathon Page:** https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon
- **Alpaca Docs:** https://docs.alpaca.markets/
- **MCP Server:** https://alpaca.markets/mcp-server
- **Paper Trading:** https://alpaca.markets/learn/start-paper-trading
- **Options Guide:** https://alpaca.markets/learn/how-to-trade-options-with-alpaca

### All Links
See [sources/urls_and_links.md](sources/urls_and_links.md) for complete reference

## Timeline

### Week 1: Setup & Learning (Aug 28 - Sept 1)
- [ ] Set up Alpaca paper trading account ✅ DONE
- [ ] Generate and store API keys securely
- [ ] Configure development environment
- [ ] First test orders and market data access
- [ ] Study options trading strategies
- [ ] Configure Claude/Cursor with MCP Server

### Week 2: Development & Testing (Sept 1 - 4)
- [ ] Implement trading strategy
- [ ] Add options trading component
- [ ] Test extensively in paper trading
- [ ] Prepare documentation
- [ ] Create demo/screenshots
- [ ] Final testing and verification
- [ ] Submit before Sept 4, 15:00 UTC

## Success Checklist

Before submission, verify:
- [ ] Paper trading account is NEW and dedicated
- [ ] Options trading implemented and tested
- [ ] Strategy is documented clearly
- [ ] Code is clean and organized
- [ ] All links in submission work
- [ ] Screenshots/demo prepared
- [ ] README explains the approach
- [ ] Submitted before deadline
- [ ] Backup copy saved locally

## Pro Tips

1. **Leverage AI:** Use Claude with MCP Server for intelligent trading decisions
2. **Test Thoroughly:** Paper trading is for testing - do it extensively
3. **Document Well:** Clear documentation scores points
4. **Start Simple:** Master basics before complex strategies
5. **Track Everything:** Log trades, P&L, and strategy changes
6. **Use Options:** Make options trading the highlight of your submission
7. **Start Now:** Don't wait - 9 days goes fast!

## Common Questions

**Q: Can I use an existing Alpaca account?**  
A: No, you must create a NEW paper trading account specifically for this hackathon.

**Q: Do I need real money?**  
A: No! Paper trading uses $100,000 in virtual funds. Zero real money risk.

**Q: What if I'm new to trading?**  
A: Perfect! Read the [options_trading_guide.md](sources/options_trading_guide.md) to learn, then use Claude to help implement strategies.

**Q: How do I integrate Claude for trading?**  
A: See [mcp_server_setup.md](sources/mcp_server_setup.md) - it explains how Claude can execute trades through Alpaca's MCP Server.

**Q: What's the best strategy to win?**  
A: Combine: (1) Smart AI analysis, (2) Creative options use, (3) Clear documentation, (4) Good performance metrics

## Next Steps

1. **Read [quick_reference.md](quick_reference.md)** (5 minutes)
2. **Follow [getting_started.md](getting_started.md)** (setup your environment)
3. **Study [options_trading_guide.md](sources/options_trading_guide.md)** (learn strategies)
4. **Setup [mcp_server_setup.md](sources/mcp_server_setup.md)** (integrate Claude)
5. **Start Building!**

## Questions or Issues?

- **Hackathon Help:** Check lablab.ai Discord community
- **Alpaca Support:** https://alpaca.markets/
- **Documentation:** Review relevant .md file in this directory
- **Broken Links:** See [urls_and_links.md](sources/urls_and_links.md)

---

## Document Summary

| Document | Purpose | Read Time |
|----------|---------|-----------|
| quick_reference.md | Fast answers, checklists | 5 min |
| hackathon_overview.md | Event context and requirements | 10 min |
| technical_setup.md | API and environment setup | 15 min |
| getting_started.md | Step-by-step implementation guide | 30 min |
| submission_and_judging.md | Submission requirements and process | 10 min |
| resources.md | All links and external resources | 5 min |
| sources/alpaca_api_summary.md | API reference and examples | 20 min |
| sources/mcp_server_setup.md | Claude integration guide | 25 min |
| sources/options_trading_guide.md | Strategy types and examples | 20 min |
| sources/urls_and_links.md | Complete URL reference | As needed |

**Total Recommended Reading:** ~2 hours for solid understanding

---

**Last Updated:** August 26, 2026

**Team:** trdrbot  
**Hackathon:** Alpaca AI Trading Agents on lablab.ai  
**Deadline:** September 4, 2026 at 15:00 UTC

**Let's build an amazing AI trading agent! 🚀**
