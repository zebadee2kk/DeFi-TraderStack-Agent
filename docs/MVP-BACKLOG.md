# MVP Backlog

## Epic 0 — Architecture Freeze
- [ ] Approve HLD and trust boundaries
- [ ] Decide initial exchange/venue
- [ ] Decide initial asset universe
- [ ] Decide initial paper-trading capital model
- [ ] Record ADRs for Hummingbot, Freqtrade, database and workflow engine

## Epic 1 — Repository/Foundation
- [ ] Python project scaffolding
- [ ] Docker Compose baseline
- [ ] typed configuration model
- [ ] structured logging
- [ ] CI lint/test/security checks
- [ ] secrets example files with no credentials

## Epic 2 — Market Data
- [ ] direct venue WebSocket ingestion
- [ ] candle aggregation
- [ ] order-book snapshot handling
- [ ] CoinGecko reference adapter
- [ ] CoinMarketCap reference adapter
- [ ] data freshness/divergence checks
- [x] persistent time-series storage

## Epic 3 — Intelligence Adapters
- [ ] Dune adapter/MCP integration
- [ ] LunarCrush adapter/MCP integration
- [ ] CryptoPanic adapter/MCP integration
- [ ] Perplexity research adapter
- [ ] altFINS adapter
- [ ] TradingView secondary integration
- [ ] provider health and quota tracking

## Epic 4 — Feature and Signal Plane
- [ ] canonical feature schema
- [ ] technical feature pipeline
- [ ] on-chain feature pipeline
- [ ] social/narrative feature pipeline
- [ ] news/event classifier
- [ ] regime classifier v1
- [ ] signal registry and versioning

## Epic 5 — Research Harness
- [ ] Freqtrade research integration
- [ ] baseline strategies
- [ ] fee/slippage models
- [ ] lookahead-bias test
- [ ] walk-forward evaluator
- [ ] performance attribution report

## Epic 6 — Agent Runtime
- [ ] Claude model abstraction
- [ ] tool/MCP allowlist
- [ ] technical strategy agent
- [ ] on-chain strategy agent
- [ ] narrative strategy agent
- [ ] meta/investment-committee agent
- [ ] JSON schema validation for proposals
- [ ] prompt/version registry

## Epic 7 — Portfolio and Risk
- [ ] NAV/position service
- [ ] volatility-based sizing
- [ ] exposure limits
- [ ] liquidity/spread constraints
- [ ] max daily loss
- [ ] max account drawdown
- [ ] strategy circuit breaker
- [ ] kill-switch API
- [ ] immutable risk-decision audit trail

## Epic 8 — Execution
- [ ] Hummingbot API integration
- [ ] paper account setup
- [ ] execution planner
- [ ] idempotent order submission
- [ ] order/fill state machine
- [ ] venue reconciliation
- [ ] retry/timeout handling

## Epic 9 — Observability
- [x] OpenTelemetry traces
- [x] Prometheus metrics
- [x] Grafana dashboard
- [x] Loki logs
- [x] provider/API-cost dashboard
- [x] decision-to-fill trace view

## Epic 10 — Paper-Trading Acceptance
- [ ] 24/7 soak test
- [ ] forced provider outages
- [ ] forced database restart
- [ ] stale-data test
- [ ] duplicate-order test
- [ ] risk-service failure test
- [ ] kill-switch drill
- [ ] paper performance report versus baselines

## MVP Exit Criteria

The MVP is complete when it can autonomously ingest live data, produce versioned signals and Claude trade proposals, deterministically reject unsafe proposals, submit approved paper orders through Hummingbot, reconcile outcomes, and provide a complete auditable decision trail for at least one continuous 24/7 test window.

Live capital is explicitly outside MVP exit criteria.
