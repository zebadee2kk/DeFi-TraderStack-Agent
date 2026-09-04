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
- [x] canonical feature schema (`features.py`: `AssetFeatureVector` — market/on-chain/narrative/news, plus the altFINS external-signal slot)
- [x] technical feature pipeline (`market_features.CandleMarketFeatureBuilder`, trend/volatility/relative-volume/spread from candle history)
- [x] on-chain feature pipeline (`market.intelligence_providers.DuneOnChainProvider` → `OnChainFeatures`)
- [x] social/narrative feature pipeline (`market.intelligence_providers.LunarCrushSocialProvider` → `NarrativeFeatures`)
- [x] news/event classifier (`market.intelligence_providers.CryptoPanicNewsProvider`, `market.perplexity.PerplexityNewsProvider` → `NewsFeatures.adverse_event`, deterministically gates new risk)
- [x] regime classifier v1 (`strategies.RegimeClassifier` → `Regime`, consumed by the pre-trade gate and the specialist committee)
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
- [x] Hummingbot API integration (`execution/hummingbot.py` `HummingbotPaperExecutor`, `execution/reconcile.py` `HummingbotExecutionReconciler`, `reconciliation.py` `HummingbotPortfolioReconciler`; wired end-to-end in `cli.build_service` behind `--submit`)
- [x] paper account setup (`HUMMINGBOT_ACCOUNT_NAME`/`HUMMINGBOT_CONNECTOR_NAME` in `.env.example`; `docker-compose.yml` `execution` profile brings up `hummingbot-api` + its own Postgres)
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

## Remaining before live capital

Everything below is unticked above (or open in `docs/SECURITY-REVIEW-2026-09.md`)
for a reason worth restating here in one place. See `docs/ROADMAP.md` for the
phase each belongs to, with a dated status line per phase.

1. **The 24/7 soak window itself** (Epic 10; Roadmap Phase 6). The runner and
   every drill are implemented and tested; the sustained 24-hour run has not
   yet been executed and archived as evidence.
2. **Shadow-live validation** (Roadmap Phase 7) — not started.
   `TRADING_MODE=shadow` is an accepted `Settings` value with no distinct
   runtime behaviour behind it yet.
3. **On-chain execution signing** (Roadmap Phase 8). `execution/robinhood_chain.py`
   stops at an unsigned, simulated transaction by design; no isolated signer,
   smart-account/guard policy or spending-cap service exists. Two specific
   scaffolding gaps a signer must close first: the chain-id check and the
   later RPC calls are not bound to the same connection
   (SEC-2026-09-15), and `prepare_swap` does not yet allowlist method
   selectors or bound `value_wei` by policy (SEC-2026-09-16).
4. **Open security-review items** (`docs/SECURITY-REVIEW-2026-09.md`, "Open"
   status): the Promtail Docker-socket mount grants root-equivalent host
   access (SEC-2026-09-11); `pip-audit` is red in CI on its own resolved `pip`
   advisories, not this project's dependencies (SEC-2026-09-12); dev tooling
   and every non-app container image are unpinned (SEC-2026-09-13,
   SEC-2026-09-14); `RiskEngine.policy_version` does not cover every limit
   enforced around it — pretrade/execution/reference-divergence/market-data-age
   settings can change without moving the version (SEC-2026-09-18); a few
   narrower fail-closed-by-accident items (SEC-2026-09-17, -19, -20).
5. **Tiny-capital live pilot and controlled scale-up** (Roadmap Phases 9-10) —
   blocked on 2 and 3 above by design; not started.

None of these block continued paper trading. They are exactly what stands
between the current MVP and the live-capital phases.
