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

## Container hardening

The `app` image (`Dockerfile`) is a two-stage build — a `builder` stage resolves
dependencies into an isolated venv, and the `runtime` stage carries only that venv
plus the app, on a digest-pinned `python:3.12-slim` base, running as the existing
non-root `traderstack` user with `PIP_NO_CACHE_DIR=1`. It ships a `HEALTHCHECK`
against its own Prometheus endpoint (`/metrics` on port 9108, via `urllib` since
the slim image has no `curl`), and a `.dockerignore` keeps build context to source
+ `pyproject.toml`.

`docker-compose.yml`'s `app` service runs with `read_only: true` (a `tmpfs` mount
covers `/tmp`; the `app_state` volume remains the one writable path, at
`/app/var`), `security_opt: [no-new-privileges:true]`, a matching `healthcheck:`,
and CPU/memory limits (`deploy.resources.limits`). See `docs/RUNBOOK.md` for
day-to-day operation and `docs/SECURITY-THREAT-MODEL.md` for the controls this
implements.

## Deployment Principle

Infrastructure must be disposable; state must be recoverable. No irreplaceable configuration should exist only inside a running container or UI.
