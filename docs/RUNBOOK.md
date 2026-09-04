# Operator Runbook

This is the operational guide for running DeFi TraderStack Agent as a paper-trading
service: zero-to-running, day-to-day operation, the kill switch, key rotation, how to
read what it produced, and how to respond to the incidents that matter most in the MVP.

Everything here assumes **`TRADING_MODE=paper`**. Live capital is explicitly out of
MVP scope (see `docs/MVP-BACKLOG.md`); nothing in this document authorizes live
trading.

## Zero to paper trading

1. **Prerequisites**: Docker Engine + Compose plugin, and Python 3.12 if you want to
   run outside Docker too.
2. **Configure**:
   ```bash
   cp .env.example .env
   ```
   Fill in `.env` — see "Filling in `.env` safely" below. You can run with every
   provider key left blank; the runtime treats a missing key as "that feature is
   off" (see `traderstack-check-config`), never as an error, except where a setting
   you *did* turn on requires it (e.g. `VENUE_FEED=robinhood_chain`).
3. **Verify configuration before starting anything**:
   ```bash
   make setup            # creates .venv, installs the package + dev tools
   make check-config     # traderstack-check-config: prints what's enabled, warns/exits non-zero on unsafe combos
   ```
   Fix anything it flags before proceeding. This is safe to run repeatedly — it
   never prints secret values, only whether they're present.
4. **Start the datastores** (Postgres/Timescale + Redis) and the app:
   ```bash
   docker compose up -d postgres redis
   docker compose --profile app up -d --build
   ```
   Or, without Docker, once `postgres`/`redis` are reachable per `DATABASE_URL`/
   `REDIS_URL`:
   ```bash
   make run-paper
   ```
5. **Confirm it's healthy**:
   ```bash
   docker compose ps                          # app should show "healthy" after ~20-50s
   curl -s http://localhost:9108/metrics | grep traderstack_runtime_healthy
   tail -f var/audit/runtime.jsonl            # one JSON line per symbol cycle
   ```
6. **Optional: observability** (Grafana/Prometheus dashboards — owned by the
   observability profile, not this document):
   ```bash
   make run-observability
   ```
7. **Optional: real order submission through Hummingbot** — only after you've set
   `HUMMINGBOT_API_USERNAME`/`HUMMINGBOT_API_PASSWORD` and, if you want the
   `hummingbot-api` service defined in `docker-compose.yml` itself (rather than an
   externally-run one), started it:
   ```bash
   docker compose --profile execution up -d
   ```
   Then run the app with `--submit` (edit the `app` service `command:` or run
   `traderstack-paper --submit ...` directly). Until then, the runtime computes and
   risk-checks proposals but places no orders — useful for a first dry run.

At every step, the pre-trade backtest gate and the deterministic risk engine are
active by default (`PRETRADE_BACKTEST_ENABLED=true`, `KILL_SWITCH=true`). With the
kill switch on, every proposal is deterministically rejected with
`kill_switch_enabled` — that's expected. See "Engaging/releasing the kill switch"
before disengaging it.

## Filling in `.env` safely

- Start from `.env.example` — never commit a filled-in `.env` (it's gitignored).
- Leave any provider key blank to leave that feature off; nothing in this repo
  requires all providers to be configured. Run `traderstack-check-config` after
  editing to see exactly what turned on.
- Prefer a secret manager or your platform's env-injection mechanism over a
  plaintext `.env` file for anything beyond a local paper-trading sandbox
  (`docs/INFRASTRUCTURE.md`, "Secrets"). If you must use a file, restrict its
  permissions (`chmod 600 .env`) and keep it off shared filesystems.
  - Docker Compose passes it in via `env_file:`; the container consumes the
    environment, not the file, so this is compatible with either.
- Exchange/API keys should have no withdrawal permission and should be scoped to a
  dedicated subaccount, per `docs/SECURITY-THREAT-MODEL.md` ("Mandatory Controls").
  This applies to `HUMMINGBOT_API_*` credentials for whatever venue account they
  front.
- Never lower `KILL_SWITCH`, `MAX_POSITION_PCT`, `MAX_DAILY_LOSS_PCT`,
  `MAX_ACCOUNT_DRAWDOWN_PCT` or disable `PRETRADE_BACKTEST_ENABLED` "to see if it
  trades more" — these are the deterministic controls the LLM cannot bypass by
  design. Loosen them only with the same deliberation you'd give a risk-policy
  change, and confirm the result with `traderstack-check-config`.
- `ROBINHOOD_CHAIN_*` values (RPC URL, chain id, router/token allowlists) must come
  from Robinhood's own official chain docs, never guessed — see the warnings
  already in `.env.example` and `docs/DATA-SOURCES.md`.

## Starting and stopping

```bash
# Start core infra + app
docker compose up -d postgres redis
docker compose --profile app up -d --build

# Stop the app but keep data
docker compose --profile app stop app

# Stop everything, keep volumes (portfolio checkpoint, audit log, DB data)
docker compose --profile app --profile observability --profile execution down

# Stop everything AND delete volumes (irreversible — loses checkpoint/audit/DB state)
docker compose down -v
```

Outside Docker: `Ctrl-C` (SIGINT) on `traderstack-paper` stops the service after
its current in-flight symbol cycle; the portfolio checkpoint is written on every
cycle (`--checkpoint-path`, default `var/state/portfolio.json`), so a restart
resumes from the last saved NAV/positions rather than the configured starting NAV.

## Engaging / releasing the kill switch

The kill switch is the emergency stop described in
`docs/SECURITY-THREAT-MODEL.md` ("Mandatory Controls") and
`docs/INFRASTRUCTURE.md` ("Availability"): it sits in the deterministic risk
engine, outside the LLM runtime, and its only failure mode is closed (rejecting
trades), never open.

Today the risk engine reads it from a single setting:

- **`KILL_SWITCH=true`** (the default) — the risk engine rejects every proposal
  with reason `kill_switch_enabled` before any sizing or limit check runs. This is
  the safe, "everything stops" state.
- **`KILL_SWITCH=false`** — the risk engine evaluates proposals normally, subject
  to its other limits (allowlist, drawdown, daily loss, position size).

To engage it right now on a running deployment: set `KILL_SWITCH=true` in `.env`
and restart the `app` service (`docker compose --profile app up -d --force-recreate
app`), or edit the running host's environment and restart the process. Because the
check happens first in `RiskEngine.evaluate`, an already-in-flight cycle finishes
its current step but no new order is ever placed once the flag takes effect.

A separate operator is adding a file-based kill switch — a `var/state/KILL`
sentinel file plus `traderstack-kill` / `traderstack-resume` CLI scripts — so the
switch can be thrown without editing `.env` and restarting the container (e.g. from
a monitoring alert or a one-line SSH command). Once available:

- `traderstack-kill` creates `var/state/KILL` and the running service should treat
  its presence the same as `KILL_SWITCH=true`.
- `traderstack-resume` removes it.
- Because `var/state` is the same path as `--checkpoint-path`'s directory and is
  volume-mounted (`app_state`) into the container, the file works whether you run
  `traderstack-kill` on the host or inside the container.

Until those scripts land, `KILL_SWITCH=true` + restart is the documented procedure
above; `traderstack-check-config` will flag `KILL_SWITCH=false` outside
`APP_ENV=development` as an unsafe combination precisely so this is never left
disengaged by accident.

**Drill**: periodically verify the switch actually stops trading — set
`KILL_SWITCH=true`, restart, and confirm every subsequent audit line shows
`"rejection_reasons":["kill_switch_enabled"]` before you rely on it in an incident.

## Key rotation

1. Generate the new credential at the provider (exchange/venue subaccount API key,
   Anthropic key, on-chain RPC provider key, etc.) **before** revoking the old one.
2. Update `.env` (or your secret manager) with the new value. Never edit the value
   in place inside a running container — secrets are injected at process start via
   `pydantic-settings`' env loading (`Settings`), so a change requires a restart to
   take effect.
3. Restart just the `app` service so it picks up the new value:
   ```bash
   docker compose --profile app up -d --force-recreate app
   ```
4. Confirm the new credential works: `traderstack-check-config` shows the provider
   as present (never the value), and `var/audit/runtime.jsonl`'s
   `intelligence_error`/`candle_error` fields should stop mentioning that provider
   if they previously did.
5. Revoke the old credential at the provider once you've confirmed the new one is
   live for at least one full cycle.
6. For exchange/venue keys specifically: confirm the new key still has no
   withdrawal permission and is still scoped to the dedicated subaccount before
   revoking the old one (`docs/SECURITY-THREAT-MODEL.md`).
7. Never commit a rotated (or any) key to git, including in a throwaway branch or
   commit that gets amended away — treat it as compromised if it ever touches the
   working tree outside `.env`.

## Reading the audit log

Every symbol cycle appends one JSON line to `--audit-path` (default
`var/audit/runtime.jsonl`), via `JsonlAuditSink`. It's the full, replayable
decision trail: tick, references, pipeline result (including the pre-trade
backtest/walk-forward check), risk result, and execution receipt if an order was
submitted.

```bash
tail -f var/audit/runtime.jsonl | jq .
jq 'select(.pipeline.accepted_market_data == false)' var/audit/runtime.jsonl   # rejected cycles
jq '.pipeline.risk_result.decision' var/audit/runtime.jsonl | sort | uniq -c   # allow/reduce/reject counts
```

### What each rejection reason means

A cycle can be rejected at three points, each adding to
`pipeline.rejection_reasons` (or, for the risk engine, `pipeline.risk_result.reasons`
with `decision: "reject"`). Every value below is the literal string that appears in
the audit log (`src/traderstack/pipeline.py`, `src/traderstack/pretrade.py`,
`src/traderstack/risk.py`).

**Market data validation** (`VerticalSlicePipeline.process`, before any feature
vector exists):

| Reason | Meaning |
|---|---|
| `stale_primary_tick` | The venue tick is older than `max_tick_age_seconds` — the runtime uses `MAX_MARKET_DATA_AGE_SECONDS`. |
| `spread_limit_exceeded` | Bid/ask spread on the primary tick exceeds the pipeline's spread limit. |
| `no_independent_reference_price` | No CoinGecko/CoinMarketCap reference price was available for this asset to cross-check the primary tick. |
| `reference_price_divergence` | The primary tick diverges from the independent reference(s) by more than `MAX_REFERENCE_DIVERGENCE_BPS`. |

**External intelligence gating** (after market data is accepted, before a
proposal):

| Reason | Meaning |
|---|---|
| `no_external_intelligence` | `INTELLIGENCE_REQUIRED=true` but no configured provider (Dune/LunarCrush/CryptoPanic/Perplexity) returned anything this cycle. |
| `adverse_news_event` | `INTELLIGENCE_BLOCK_ON_ADVERSE_NEWS=true` (default) and a news provider flagged an adverse event for this asset — new risk is blocked for the cycle; existing positions are untouched. |

**Pre-trade backtest gate** (`PreTradeBacktestGate.evaluate`, only when
`PRETRADE_BACKTEST_ENABLED=true`):

| Reason | Meaning |
|---|---|
| `missing_candle_history` | The gate is enabled but no candle history was fetched for this cycle at all. |
| `insufficient_candle_history` | Fewer candles than `PRETRADE_MIN_CANDLES`. |
| `stale_candle_history` | The most recent candle is older than `PRETRADE_MAX_CANDLE_AGE_SECONDS`. |
| `no_strategy_consensus` | The deterministic strategy ensemble, re-run on current candles, produced no consensus side. |
| `strategy_does_not_confirm_side` | The ensemble's consensus side doesn't match the side a caller explicitly requested confirmation for. |
| `backtest_excess_return_below_minimum` | Backtested return net of fees/slippage, vs. buy-and-hold, is below `PRETRADE_MIN_EXCESS_RETURN`. |
| `backtest_drawdown_above_maximum` | Backtested max drawdown exceeds `PRETRADE_MAX_DRAWDOWN_PCT`. |
| `backtest_sharpe_below_minimum` | Backtested Sharpe ratio is below `PRETRADE_MIN_SHARPE`. |
| `backtest_trade_count_below_minimum` | Fewer backtested trades than `PRETRADE_MIN_TRADES` (too little evidence). |
| `walkforward_insufficient_history` | Not enough history for a walk-forward evaluation, and `PRETRADE_REQUIRE_WALKFORWARD=true`. |
| `walkforward_excess_return_below_minimum` | Mean out-of-sample excess return across walk-forward folds is below minimum. |
| `walkforward_drawdown_above_maximum` | Worst walk-forward fold's drawdown exceeds `PRETRADE_MAX_DRAWDOWN_PCT`. |

**Deterministic risk engine** (`RiskEngine.evaluate`, always active, cannot be
bypassed by the LLM):

| Reason | Meaning |
|---|---|
| `kill_switch_enabled` | `KILL_SWITCH=true`. Every other check is skipped — this is the emergency-stop path. See "Engaging/releasing the kill switch". |
| `asset_not_allowlisted` | The proposal's asset isn't in `MVP_ASSETS`. |
| `daily_loss_limit_reached` | Today's realized PnL has hit `MAX_DAILY_LOSS_PCT` of NAV. |
| `account_drawdown_limit_reached` | Drawdown from peak NAV has hit `MAX_ACCOUNT_DRAWDOWN_PCT`. |
| `position_limit_reached` | Existing exposure to the asset already consumes all of `MAX_POSITION_PCT` of NAV, so remaining room is zero. |
| `position_size_reduced` | *Not a rejection* — the decision is `reduce`, not `reject`. The requested notional was cut down to fit remaining `MAX_POSITION_PCT` headroom, and the (smaller) order still proceeds. |

A cycle with `pipeline.risk_result.decision == "reject"` and one of the risk-engine
reasons above still counted as `accepted_market_data: true` — market data,
intelligence and the backtest gate all passed; only the risk engine said no.

## Reading Prometheus metrics

The app exposes Prometheus metrics on `--metrics-port` (default `9108`,
`http://localhost:9108/metrics`), defined in `src/traderstack/health.py`:

| Metric | Type | Meaning |
|---|---|---|
| `traderstack_cycles_total{symbol,outcome}` | counter | Completed symbol cycles, labeled `outcome="success"` or `"error"`. Watch the `error` rate per symbol. |
| `traderstack_last_success_unixtime{symbol}` | gauge | Unix timestamp of that symbol's last successful cycle — `time() - traderstack_last_success_unixtime` is your per-symbol staleness. |
| `traderstack_runtime_healthy` | gauge | `1` if healthy, `0` once `consecutive_errors` reaches `max_consecutive_errors` (default 5) — the service stops itself when this flips to `0` (`ContinuousPaperService.run`). |

`ops/prometheus.yml` already scrapes `app:9108` under the `observability` profile
(owned separately from this document — see `docker-compose.yml`).

Minimal alerting rules worth having from day one:
- `traderstack_runtime_healthy == 0` for any duration → page immediately (the
  service has stopped itself).
- `time() - traderstack_last_success_unixtime > 300` per symbol → the symbol has
  gone quiet without the process dying (e.g. wedged on one asset).
- Sudden drop in `rate(traderstack_cycles_total{outcome="success"}[5m])` to zero
  across all symbols → provider/network outage.

## Upgrading

1. Read the diff, especially anything touching `src/traderstack/config.py` (new/
   renamed settings), `src/traderstack/risk.py`, or `src/traderstack/pretrade.py`
   (risk-policy behavior).
2. `git pull`, then `make check` (lint + typecheck + test) before deploying.
3. Compare `.env.example` against your `.env` for new variables:
   ```bash
   diff <(grep -oE '^[A-Z_]+' .env.example | sort) <(grep -oE '^[A-Z_]+' .env | sort)
   ```
4. Run `make check-config` against your updated `.env` before restarting the live
   process.
5. Rebuild and restart:
   ```bash
   docker compose --profile app build app
   docker compose --profile app up -d
   ```
6. Watch `traderstack_runtime_healthy` and the audit log's first few cycles after
   an upgrade before walking away.
7. The portfolio checkpoint (`var/state/portfolio.json`) and audit log
   (`var/audit/runtime.jsonl`) are forward-compatible by construction (plain
   JSON/JSONL); no migration step is expected for an MVP-stage upgrade, but back up
   `app_state` (`docker run --rm -v <project>_app_state:/data -v $(pwd):/backup
   alpine tar czf /backup/app_state-$(date +%F).tgz -C /data .`) before anything
   that changes portfolio/audit schemas.

## Incident response

In every case: engage the kill switch first if there's any doubt about capital
safety, *then* investigate. `TRADING_MODE=paper` means no real capital is ever at
risk from these scenarios today, but treat every incident as a live-trading
rehearsal — the deterministic controls should behave identically the day this
graduates past paper.

### Provider outage (market data, reference price, or intelligence provider)

Symptoms: `traderstack_cycles_total{outcome="error"}` rising, or audit lines
showing `candle_error`/`intelligence_error`, or repeated `stale_primary_tick` /
`no_independent_reference_price` rejections for one symbol.

1. Check `var/audit/runtime.jsonl` for the specific `candle_error` /
   `intelligence_error` message — it names the exception and provider.
2. Confirm it's the provider, not your credentials or network:
   `traderstack-check-config` still shows the key as present; check the
   provider's own status page.
3. The system already fails closed here by design — a stale/missing tick or
   provider outage produces rejections, not bad trades (`docs/SECURITY-THREAT-MODEL.md`,
   "Failure Policy"). No emergency action is required beyond monitoring.
4. If venue market data itself is out (not just a secondary reference/
   intelligence provider), `traderstack_runtime_healthy` will flip to `0` after 5
   consecutive errors and the service stops itself — this is expected, not a bug.
5. Restart once the provider recovers: `docker compose --profile app up -d
   --force-recreate app`.

### Database (Postgres) outage

Symptoms: `app` container failing to start (`depends_on: postgres:
condition: service_healthy` blocks it), or, with `--persistent-events`, errors from
`PostgresRuntimeEventStore`.

1. `docker compose ps postgres` / `docker compose logs postgres` to see why it's
   unhealthy.
2. The portfolio checkpoint (`var/state/portfolio.json`) and the JSONL audit log
   are independent of Postgres — they keep working even with
   `--persistent-events` failing, so trading state and the audit trail are not at
   risk from a Postgres outage alone.
3. Once Postgres is healthy again (`pg_isready -U traderstack -d traderstack`
   inside the container, or the compose healthcheck going green), restart `app`.
4. If data on the `postgres_data` volume is suspected corrupted, restore from your
   most recent backup (`docs/INFRASTRUCTURE.md`, "Availability" calls for daily
   backups) rather than deleting the volume.

### Drift detected (reconciliation mismatch against the venue)

Symptoms: `HummingbotPortfolioReconciler.reconcile` returns `matched: false`, or
`ReconciliationResult.nav_difference_bps` exceeds `max_nav_difference_bps`
(default 25 bps).

1. Treat this as the reconciliation-failure case in
   `docs/SECURITY-THREAT-MODEL.md` ("Failure Policy"): position state that cannot
   be reconciled should block new risk. Engage the kill switch
   (`KILL_SWITCH=true` + restart, see above) while you investigate — the runtime
   does not yet auto-halt on drift, so this step is on the operator today.
2. Compare `ReconciliationResult.internal_nav_usd` vs. `external_nav_usd` and the
   `reasons` list to see whether it's a stale local checkpoint, a missed fill, or
   a genuine venue-side discrepancy.
3. Cross-check against the venue's own UI/API for the paper account
   (`HUMMINGBOT_ACCOUNT_NAME`) directly, independent of this codebase.
4. If the local checkpoint is simply behind (e.g. after an ungraceful restart),
   the safest fix is usually to let reconciliation's authoritative venue state win
   — do not hand-edit `var/state/portfolio.json` to "fix" NAV without
   understanding why it drifted first.
5. Release the kill switch only once you can explain the divergence and the next
   reconciliation cycle reports `matched: true`.
