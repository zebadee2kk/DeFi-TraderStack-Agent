# DeFi TraderStack Agent

An experimental autonomous crypto/DeFi trading research and execution platform combining quantitative signals, on-chain intelligence, market/news/social data, LLM reasoning, deterministic risk controls, and broker/DEX execution.

> **Status:** Architecture and research phase. No production capital should be connected until the full backtest, forward-test, paper-trading, security, and risk-control gates are complete.

## Quickstart (paper trading)

```bash
cp .env.example .env          # fill in what you need; everything else can stay blank
make setup                    # creates .venv, installs the package + dev tools
make check-config             # traderstack-check-config: shows what's enabled, fails on unsafe combos
docker compose up -d postgres redis
docker compose --profile app up -d --build
docker compose ps             # app should report "healthy" within ~50s
tail -f var/audit/runtime.jsonl
```

`KILL_SWITCH=true` and `TRADING_MODE=paper` are the defaults — the deterministic
risk engine rejects every proposal until you deliberately change that. Full
zero-to-running steps, filling in `.env` safely, the kill switch, key rotation,
reading the audit log/metrics, upgrading, and incident response all live in
**[`docs/RUNBOOK.md`](docs/RUNBOOK.md)**.

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

## External intelligence in the live loop

Every cycle the runtime gathers Dune (on-chain), LunarCrush (social) and
CryptoPanic/Perplexity (news) snapshots for the asset, cached and failure-isolated,
and merges them into the feature vector. An adverse news event deterministically
blocks new risk for that cycle. Providers activate when their API key is set; see
the `INTELLIGENCE_*` settings in `.env.example`. Adapters emit bounded numbers only,
so retrieved text never reaches the decision path.

## Pre-trade self-check (backtest gate)

Before any proposal reaches the risk engine, `src/traderstack/pretrade.py` re-runs
the strategy ensemble over the asset's recent candle history (fetched each cycle
from Kraken), backtests it net of fees and slippage against buy-and-hold, and
walk-forward tests it out-of-sample. A missing, stale or unconvincing history
rejects the trade. Thresholds are `PRETRADE_*` settings in `.env.example`; the gate
is on by default and can only add rejections, never relax risk policy.

## Robinhood Chain real-time swap feed

`src/traderstack/market/robinhood_chain_feed.py` streams Uniswap v3/v4 `Swap`
events from operator-listed pools over websocket JSON-RPC (`eth_subscribe`), after
verifying the endpoint's chain id, and emits them as `MarketTick`s so the normal
staleness/spread/reference-divergence validation applies. Set
`VENUE_FEED=robinhood_chain` plus `ROBINHOOD_CHAIN_WS_URL` and
`ROBINHOOD_CHAIN_POOLS` to use it as the primary tick source. Read-only: it never
discovers tokens or trades on its own.

## Robinhood Chain (EVM) execution scaffolding

`src/traderstack/execution/robinhood_chain.py` prepares policy-checked, simulated,
**unsigned** swap transactions against Robinhood Chain, an EVM-compatible network.
Chain id, RPC URL and token/router allowlists are always operator-supplied via
`Settings` (see `.env.example`) — sourced from Robinhood's own official chain
documentation, never hardcoded or guessed. The executor independently verifies the
connected RPC's chain id, enforces allowlists and a notional/gas policy, and
simulates the transaction, but never signs or broadcasts it and never holds a
private key; `live` trading mode is rejected until an isolated signing/custody
service exists (see `docs/EXECUTION-ARCHITECTURE.md` and `docs/ROADMAP.md` Phase 8).

## Repository roadmap

See `docs/PROJECT-CHARTER.md`, `docs/HLD.md`, `docs/RESEARCH-NOTES.md`, `docs/RISK-PRINCIPLES.md`, and `docs/ROADMAP.md` as they are developed.

`docs/DATA-SOURCES.md` is the researched inventory of live, reference, on-chain and
backtest data sources (with verification status), including a Robinhood Chain
section covering the documented chain ids, RPC/explorer endpoints, live DEX router
addresses, oracles and which indexers/vendors support chain 4663.

## Disclaimer

This repository is for research and proprietary experimentation, not financial advice. Initial scope is private/proprietary trading only; no third-party client funds or investment service functionality is in scope.
