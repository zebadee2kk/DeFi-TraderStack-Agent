# MVP Backlog

## Epic 0 — Architecture Freeze
- [ ] Approve HLD and trust boundaries
- [ ] Decide initial exchange/venue
- [ ] Decide initial asset universe
- [ ] Decide initial paper-trading capital model
- [ ] Record ADRs for Hummingbot, Freqtrade, database and workflow engine

## Epic 1 — Repository/Foundation
- [x] Python project scaffolding
- [x] Docker Compose baseline
- [x] typed configuration model
- [x] structured logging
- [x] CI lint/test/security checks
- [x] secrets example files with no credentials

## Epic 2 — Market Data
- [x] direct venue WebSocket ingestion (Kraken WS v2, now with reconnect/backoff/stale-detection - `traderstack.market.adapters.KrakenTickerProvider`)
- [ ] candle aggregation
- [x] order-book snapshot handling (`KrakenBookProvider`, `BookSnapshot`, `depth_within_bps` - opt-in via `KRAKEN_BOOK_ENABLED`; not yet consumed by the risk plane)
- [x] CoinGecko reference adapter
- [x] CoinMarketCap reference adapter
- [x] data freshness/divergence checks (now includes reference-vs-reference `pairwise_divergences`, not only primary-vs-reference)
- [x] persistent time-series storage

## Epic 3 — Intelligence Adapters
- [x] Dune adapter/MCP integration
- [x] LunarCrush adapter/MCP integration
- [x] CryptoPanic adapter/MCP integration
- [x] Perplexity research adapter (migrated to the Agent API; Sonar Chat Completions is deprecated)
- [x] altFINS adapter (`traderstack.market.altfins`; signal-ratio score is a documented assumption, see PROVIDER-CAPABILITY-MATRIX.md)
- [ ] TradingView secondary integration
- [x] provider health and quota tracking (`traderstack.market.registry.ProviderRegistry`: timeout, circuit breaker, quota budgets, TTL cache, Prometheus metrics, `health()`)

## Epic 4 — Feature and Signal Plane
- [ ] canonical feature schema
- [ ] technical feature pipeline
- [ ] on-chain feature pipeline
- [ ] social/narrative feature pipeline
- [ ] news/event classifier
- [ ] regime classifier v1
- [x] signal registry and versioning

## Epic 5 — Research Harness
- [ ] Freqtrade research integration
- [x] baseline strategies
- [x] fee/slippage models
- [x] lookahead-bias test
- [x] walk-forward evaluator
- [x] performance attribution report

## Epic 6 — Agent Runtime
- [x] Claude model abstraction
- [ ] tool/MCP allowlist
- [x] technical strategy agent
- [x] on-chain strategy agent
- [x] narrative strategy agent
- [x] meta/investment-committee agent
- [x] JSON schema validation for proposals
- [x] prompt/version registry

## Epic 7 — Portfolio and Risk
- [x] NAV/position service (`portfolio.py`; daily PnL now anchored at UTC midnight)
- [x] volatility-based sizing
- [x] exposure limits (gross, per-position, max simultaneous positions, cash reserve)
- [x] liquidity/spread constraints
- [x] max daily loss
- [x] max account drawdown
- [x] strategy circuit breaker (`circuit_breaker.py`)
- [x] kill-switch API (`killswitch.py`; sentinel file, Redis key, SIGUSR1, setting)
- [x] immutable risk-decision audit trail (`risk_audit.py`; SHA-256 chained JSONL)
- [x] stale-state shutdown
- [x] policy versioning derived from the risk limits in force

See the "Implemented controls" table in docs/RISK-PRINCIPLES.md for the setting
and reason string behind each control.

## Epic 8 — Execution
- [ ] Hummingbot API integration
- [ ] paper account setup
- [x] execution planner
- [x] idempotent order submission
- [x] order/fill state machine
- [x] venue reconciliation
- [x] retry/timeout handling

## Epic 9 — Observability
- [x] OpenTelemetry traces
- [x] Prometheus metrics
- [x] Grafana dashboard
- [x] Loki logs
- [x] provider/API-cost dashboard
- [x] decision-to-fill trace view

## Epic 10 — Paper-Trading Acceptance
- [ ] 24/7 soak test — **the runner exists and is tested; the 24-hour window itself has not been run.** `traderstack-soak --seconds 86400 --workdir var/soak --report var/soak/report.json` drives the real `cli.build_service` wiring against a seeded synthetic market with optional scheduled fault injection, and emits a machine-readable acceptance report. See docs/RUNBOOK.md, "24/7 acceptance soak", for the procedure and the pass criteria.
- [x] forced provider outages (`tests/acceptance/test_provider_outages.py`)
- [x] forced database restart (`tests/acceptance/test_database_restart.py`)
- [x] stale-data test (`tests/acceptance/test_stale_data.py`)
- [x] duplicate-order test (`tests/acceptance/test_duplicate_order.py`)
- [x] risk-service failure test (`tests/acceptance/test_risk_service_failure.py`)
- [x] kill-switch drill (`tests/acceptance/test_kill_switch_drill.py`)
- [x] reconciliation-drift drill (`tests/acceptance/test_reconciliation_drift.py`)
- [x] audit-integrity drill (`tests/acceptance/test_audit_integrity.py`)
- [x] paper performance report versus baselines (`traderstack-paper-report`, `src/traderstack/acceptance/report.py`)

The drills share the fault-injection harness in `src/traderstack/acceptance/faults.py`
(each fault is an object with `arm()`/`disarm()` and a fired counter) and the seeded
synthetic market in `src/traderstack/acceptance/market.py`. Every drill drives a real
`ContinuousPaperService`; only the network edges are faked. See docs/EVALUATION-FRAMEWORK.md,
"Acceptance drills", for what each drill asserts.

## MVP Exit Criteria

The MVP is complete when it can autonomously ingest live data, produce versioned signals and Claude trade proposals, deterministically reject unsafe proposals, submit approved paper orders through Hummingbot, reconcile outcomes, and provide a complete auditable decision trail for at least one continuous 24/7 test window.

Live capital is explicitly outside MVP exit criteria.
