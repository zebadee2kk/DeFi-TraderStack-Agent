# Infrastructure and Deployment

## Goal

Provide a reproducible, isolated and observable runtime for 24/7 research, paper trading and eventually controlled live execution.

## Recommended MVP Runtime

Docker Compose on a dedicated Linux host/VPS is sufficient for the first paper-trading release. Keep the design Kubernetes-compatible, but do not add cluster complexity until scaling or HA requirements justify it.

## Services

```text
reverse-proxy
api-gateway
orchestrator
market-ingestion
feature-engine
signal-engine
regime-engine
agent-runtime
portfolio-service
risk-engine
execution-planner
hummingbot
reconciliation-service
postgres
redis
object-store
otel-collector
prometheus
grafana
loki
```

## Network Segmentation

- `public_ingress`: dashboard/API only.
- `intelligence_net`: agents and external research connectors.
- `control_net`: portfolio/risk/execution services.
- `data_net`: databases and telemetry.
- `signing_net`: signing component only; no general agent access.

Default-deny east/west connectivity where practical.

## Availability

Paper MVP target:
- restart-safe services
- persistent database volumes
- health checks
- automatic container restart
- daily backups

Before material live capital:
- independent kill switch
- host monitoring
- off-host backups
- tested restore runbook
- redundant provider connectivity where justified
- deployment rollback procedure

## Configuration

Environment-specific configuration:

```text
config/
  base/
  paper/
  shadow/
  live/
```

Never allow live credentials in paper/dev environments.

## Secrets

Prefer a dedicated secret manager for production. Vaultwarden may be used for human credential custody, but runtime services should retrieve narrowly scoped machine secrets through an automated secret-management mechanism rather than clipboard/manual injection.

## Observability

OpenTelemetry is the common instrumentation layer. Capture traces across event -> agent -> risk -> order -> fill using the same correlation ID.

Implemented today (Epic 9):

- **Metrics** — `traderstack.metrics` (Prometheus): pipeline outcomes and rejection reasons by symbol, proposals and risk decisions, paper orders submitted, provider fetch latency/failures by provider, candle history size, intelligence source presence, portfolio NAV/cash/drawdown gauges, and event-sink failures. Exposed by `traderstack-paper` on `--metrics-port` (default 9108, see `ops/prometheus.yml`).
- **Structured logs** — `traderstack.logging_config.configure_logging()` (structlog): JSON in every environment except `development` (console renderer there), one line per runtime cycle with `symbol`/`decision_id`/`cycle` bound, and a redaction processor that masks any field whose key contains `key`, `token`, `password` or `secret` before it is ever rendered.
- **Traces** — `traderstack.tracing` (OpenTelemetry, optional `opentelemetry` extra): a span per `PaperRuntime.run_once` cycle and per provider fetch, carrying `symbol` and (once known) `decision_id`. A complete no-op — no import, no overhead — unless both the extra is installed and `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- **Decision-to-fill trace view** — `PostgresRuntimeEventStore.recent(symbol, limit)` and `.decision_trace(decision_id)` query helpers (requires `--persistent-events`), and the `traderstack-trace <decision_id>` console script that prints the ordered events for one decision.

### Running the observability stack

The `observability` Compose profile brings up Prometheus, Grafana (pre-provisioned with both dashboards and datasources), and Loki/Promtail for log aggregation, alongside the `app` profile's paper-trading service:

```sh
docker compose --profile app --profile observability up -d
```

This starts:

- **Prometheus** (`:9090`) — scrapes `app:9108` per `ops/prometheus.yml`.
- **Grafana** (`:3000`) — auto-provisioned from `ops/grafana/provisioning/` (Prometheus + Loki datasources) and `ops/grafana/dashboards/traderstack.json` (a "TraderStack Overview" dashboard: cycle rate/outcomes, rejection reasons, risk decisions, provider latency/failures and an API-cost proxy panel driven by the same provider counters, portfolio NAV/drawdown, runtime health, and an application-logs panel). Anonymous viewer access is enabled for local use; put Grafana behind the real ingress/auth layer before anything beyond a single operator's laptop.
- **Loki** (`:3100`) + **Promtail** — Promtail tails the `app` container's stdout via Docker service discovery (`ops/promtail.yml`) and ships it to Loki; this is optional and can be omitted by not starting the `observability` profile, in which case only Prometheus metrics and local structured logs remain.
- **OpenTelemetry traces** are opt-in and not part of the Compose stack by default: install the `opentelemetry` extra (`pip install -e '.[opentelemetry]'`) and set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP/HTTP collector to enable them; nothing else changes.

## Deployment Principle

Infrastructure must be disposable; state must be recoverable. No irreplaceable configuration should exist only inside a running container or UI.
