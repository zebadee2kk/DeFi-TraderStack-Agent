# Research Notes and Component Decisions

## Current conclusion

The concept is technically viable, but the engineering goal is not merely to make an LLM capable of placing trades. The project must test whether an agentic + quantitative architecture produces persistent, risk-adjusted value after realistic costs and against simple baselines.

## Original ten-tool set

| Tool | Intended role | Current disposition |
|---|---|---|
| TradingView MCP | charts, indicators, alerts, Pine workflows | Keep as secondary/non-critical intelligence path |
| Dune MCP | on-chain analytics and wallet/protocol flows | Keep |
| Perplexity MCP | live web and financial/event research | Keep |
| GOAT SDK MCP | wallet/on-chain execution | Legacy/experimental only; do not make a production dependency |
| altFINS MCP | technical indicators, screeners and signals | Keep |
| CoinGecko MCP/API | crypto market and on-chain reference data | Keep |
| DeFi Trading & Portfolio MCP | portfolio reads/DEX actions | Experimental; not primary execution control plane |
| CryptoPanic MCP | crypto news | Keep |
| CoinMarketCap MCP/API | market/reference data and cross-validation | Keep |
| LunarCrush MCP | social/narrative intelligence | Keep |

## Important additions

### Hummingbot
Preferred execution spine for the design because its ecosystem provides exchange/DEX connectors, market data abstractions, order lifecycle support, Gateway, APIs and MCP integration. This lets the project concentrate effort on signal quality, portfolio intelligence and risk rather than reimplementing exchange connectivity.

### Freqtrade
Recommended as an independent research/backtest tool for directional strategy experiments, dry-run validation and specific testing for look-ahead bias. It should not be treated as a second production execution engine unless later evidence justifies that complexity.

### Venue-native market feeds
Execution-critical market state should come directly from the venue (or the execution abstraction backed by that venue), not from slow/aggregated MCP research services.

### Durable workflows
A 24/7 trading system needs crash-resilient event/workflow semantics. Orchestration must be able to reconstruct state after process/network failures.

### Smart-account / signing controls
On-chain execution requires a narrow signing boundary, transaction simulation, contract/token allowlists, spending limits and explicit permissions. LLM-facing services should never hold unrestricted signing keys.

## Research implications for the design

1. LLM trading research is promising but often suffers from data leakage, weak cost modelling and poor reproducibility.
2. Multi-agent architectures are worth testing, but claims of superior performance must be measured against simple strategies and passive crypto exposure.
3. Structured quantitative/on-chain features should be the primary input. News/social/LLM reasoning are complementary contextual signals rather than replacements for market structure.
4. Strategy performance must be evaluated by market regime, not only as one aggregate return curve.
5. Production architecture should separate signal generation, portfolio construction, risk control and execution.

## Required benchmark suite

At minimum:
- BTC buy-and-hold
- ETH buy-and-hold
- static BTC/ETH portfolio
- simple momentum
- simple trend-following
- simple mean reversion
- volatility-targeted/risk-balanced baseline

## Research questions still open

- Which exchange(s) and chain(s) should be the first supported live venues?
- Which data sources have usable free/API tiers for continuous operation?
- What signal frequency maximises usefulness of Claude without excessive cost/latency?
- Does social/narrative information add value after controlling for price momentum?
- Does Dune/on-chain information provide incremental predictive value over market data alone?
- Is a Claude meta-agent better than deterministic signal weighting?
- Which market-regime classifier is stable enough for production use?
- What is the minimum realistic paper-trading period before a tiny-capital live pilot?
