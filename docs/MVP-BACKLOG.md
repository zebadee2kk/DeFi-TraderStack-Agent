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
- [x] selection-bias evidence in search reports (#135): pre-registered era
      prints (2016-2019 / 2020-2022 / 2022-2024 / 2024-2026), Deflated Sharpe
      (Bailey & Lopez de Prado), probability of backtest overfitting via CSCV,
      and percentile-bootstrap CIs on Sharpe and expectancy replacing the fixed
      trade-count floor. Vendored in pure Python (`research/overfitting.py`) —
      no new dependency. Wired through the shared `run_harder_gates` path, so
      the eleven dual-print families carry it, as do `-second-print` and
      `-honesty-pack` (both score through `run_harder_gates`; second-print had
      been computing the block and discarding it). `traderstack-strategy-search`,
      `-miles-search`, `-daily-robustness`, `-liq-regime-search` and
      `-funding-carry` do **not** carry it and are **not** wiring: they never
      call `run_harder_gates`, so each needs a decision about what its trial
      set is, and a wrong trial count silently weakens the DSR rather than
      failing loudly. Additional withholding gate: it can only remove a
      promotion, never grant one.
- [x] multi-year candle fetchers (#133): `traderstack-download-candles --venue
      coinbase|binance_vision|kraken_archive`, past Kraken's 720-bar REST cap,
      with gap detection, checksum-verified Binance Vision months and a
      cross-venue daily-close divergence flag. **Parse path tested offline
      only** — all three hosts are egress-blocked from the build environment,
      so no live multi-year pull has been performed.

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
- [x] externally anchored chain head (#68): `{sequence, head_hash,
      policy_version, anchored_at}` published every `AUDIT_ANCHOR_EVERY`
      records and on shutdown to sinks outside the audit file, so a
      regenerate-from-genesis rewrite — which passes `verify_chain` perfectly —
      is caught by `traderstack-verify-audit`, and a divergent anchor halts the
      service at startup through the #67 durable-state gate. Publishing never
      blocks a cycle (failures counted on
      `traderstack_audit_anchor_failures_total`); verification fails closed.
      **Detection, not prevention**: a WORM/append-only sink is still the
      unticked half, and anchors are not yet signed with an operator-held key,
      so compromising both the trail and an anchor store still yields a
      consistent pair.
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

The reducing-only quantity clamp that stops a protective exit overselling
after adverse slippage (#130) is now enforced on **both** execution paths:
`PaperFillSimulator` reads the cap from the in-memory paper book, and
`IdempotentSubmitter` takes it from `PaperRuntime`, which passes the held
quantity from the same `PortfolioSnapshot` the risk engine and the exit rules
used for that cycle. A resumed `SUBMISSION_UNCERTAIN` order contributes its
already-planned quantity as a second ceiling, so a replan at a moved price can
only hold or shrink a reducing order. When no position view is supplied the
order is left unclamped rather than refused — refusing a protective exit for
want of a position view would reproduce #130's actual harm, a stop-loss that
does not reduce risk. Covered by `tests/security/test_submitter_reduce_only.py`.

## Epic 9 — Observability
- [x] OpenTelemetry traces
- [x] Prometheus metrics
- [x] Grafana dashboard
- [x] Loki logs
- [x] provider/API-cost dashboard
- [x] decision-to-fill trace view

## Epic 10 — Paper-Trading Acceptance
- [ ] 24/7 soak test — **the runner exists, a short CI soak archives a machine-readable report, and the 24-hour window itself has not been run.** `traderstack-soak --preset ci` (also `make soak-ci`, and a `soak-ci` GitHub Actions job) is the CI-friendly path. `traderstack-soak --preset full --cycle-seconds 5 --workdir var/soak` (also `make soak-24h`) is the 86400s window. Every run writes `<workdir>/report.json` with `passed` / `failures[]` / `full_24h_window_executed`. See docs/RUNBOOK.md, "24/7 acceptance soak".
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

1. **The 24/7 soak window itself** (Epic 10; Roadmap Phase 6). The runner,
   drills, CI-length soak and report archival are implemented; the sustained
   24-hour run has not yet been executed and archived as evidence
   (`full_24h_window_executed` will stay false until it is).
2. **Shadow-live validation** (Roadmap Phase 7) — **runtime implemented;
   statistical exit gate not.** `TRADING_MODE=shadow` now runs the full
   decision/risk/meta-agent pipeline, records would-have-been orders, and
   never submits to Hummingbot or broadcasts on-chain. The Phase 7 exit gate
   (adequate sample vs paper/reality) still needs an operator campaign.
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
   SEC-2026-09-14); a few remaining fail-closed items that need a host
   Docker-socket redesign or signer work (SEC-2026-09-11, -15, -16).
   SEC-2026-09-18 (policy_version coverage of surrounding gates) and the
   narrower fail-closed-by-accident items SEC-2026-09-17, -19 and -20 are
   fixed in this pass.
5. **Tiny-capital live pilot and controlled scale-up** (Roadmap Phases 9-10) —
   blocked on 2 and 3 above by design; not started.

None of these block continued paper trading. They are exactly what stands
between the current MVP and the live-capital phases.
