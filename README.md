# DeFi TraderStack Agent

An experimental autonomous crypto/DeFi trading research and execution platform combining quantitative signals, on-chain intelligence, market/news/social data, LLM reasoning, deterministic risk controls, and broker/DEX execution.

> **Status:** Architecture and research phase. No production capital should be connected until the full backtest, forward-test, paper-trading, security, and risk-control gates are complete.

## Project goal

Build a 24/7/365 event-driven trading platform in which:

- deterministic services ingest and normalise market/on-chain data;
- specialised strategy agents generate structured trade candidates;
- Claude acts as the primary research/meta-reasoning layer;
- portfolio construction and risk controls are deterministic and cannot be bypassed by an LLM;
- Hummingbot is the preferred execution spine for CEX/DEX connectivity;
- all decisions are auditable and replayable;
- strategies must demonstrate out-of-sample value after fees and slippage before receiving live capital.

## Initial intelligence/tool set

1. TradingView MCP — charts, alerts, indicators and Pine workflows (secondary/non-critical path)
2. Dune MCP — on-chain analytics, wallet flows and protocol data
3. Perplexity MCP — live web and financial research
4. GOAT SDK MCP — legacy/experimental only; upstream repository is archived
5. altFINS MCP — technical indicators, screeners and signals
6. CoinGecko MCP/API — broad crypto market and on-chain data
7. DeFi Trading & Portfolio MCP — experimental portfolio/DEX integration
8. CryptoPanic MCP — real-time crypto news/events
9. CoinMarketCap MCP/API — market data and independent verification
10. LunarCrush MCP — social/narrative intelligence

## Additional core components

- Hummingbot API/MCP/Gateway — preferred execution layer
- Freqtrade — research, backtesting, look-ahead analysis and dry-run validation
- Direct exchange WebSockets — execution-quality market data
- Feature and signal engine — normalisation and structured features
- Market regime engine — strategy eligibility by regime
- Portfolio allocator — independent capital allocation and risk budgeting
- Deterministic risk engine — hard limits, circuit breakers and kill switch
- Safe Smart Account / transaction policy controls for DeFi execution
- Transaction simulation prior to signed on-chain actions
- Durable event-driven workflows
- PostgreSQL + time-series storage + Redis/cache
- OpenTelemetry + Prometheus/Grafana/Loki-style observability
- Secrets management and isolated signing service

## Safety principle

No LLM may modify, disable or bypass runtime risk policy. Claude may propose trades; deterministic software decides whether the proposal is permitted and at what size.

## Validation path

Historical backtest → leakage/look-ahead checks → walk-forward validation → holdout evaluation → paper trading → shadow-live trading → tiny-capital live pilot → controlled scale-up.

Benchmarks will include BTC/ETH buy-and-hold and simple non-AI momentum/trend/mean-reversion strategies so that any claimed AI alpha is measured against appropriate baselines.

## Repository roadmap

See `docs/PROJECT-CHARTER.md`, `docs/HLD.md`, `docs/RESEARCH-NOTES.md`, `docs/RISK-PRINCIPLES.md`, and `docs/ROADMAP.md` as they are developed.

## Disclaimer

This repository is for research and proprietary experimentation, not financial advice. Initial scope is private/proprietary trading only; no third-party client funds or investment service functionality is in scope.
