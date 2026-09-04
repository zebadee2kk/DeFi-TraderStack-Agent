# Operator Runbook

This is the operational guide for running DeFi TraderStack Agent as a paper-trading
service: zero-to-running, day-to-day operation, the kill switch, key rotation, how to
read what it produced, and how to respond to the incidents that matter most in the MVP.

Everything here assumes **`TRADING_MODE=paper`**. Live capital is explicitly out of
MVP scope (see `docs/MVP-BACKLOG.md`); nothing in this document authorizes live
trading.

## Console scripts

Every entry point below is a `[project.scripts]` console script (`pyproject.toml`),
runnable as `traderstack-<name>` once installed, or `.venv/bin/traderstack-<name>`
without activating the venv.

| Script | What it does |
|---|---|
| `traderstack-paper` | Runs the continuous paper-trading service (`ContinuousPaperService`). `--submit` enables real (paper-venue) order submission; without it, proposals are computed and risk-checked but nothing is sent to Hummingbot. See "Zero to paper trading" below. |
| `traderstack-check-config` | Loads `Settings` exactly as the runtime does and prints what's enabled — venue feed, meta-agent mode, every provider, execution/reconciliation settings, provider quotas, kill-switch channels, risk limits — warning (and exiting non-zero) on unsafe combinations. Never prints secret values. Run this before every start and after every `.env` change. |
| `traderstack-kill` | Engages the kill switch by writing the sentinel file (`--file`, default `$KILL_SWITCH_FILE` or `var/state/KILL`). Needs no access to the running process. See "Engaging / releasing the kill switch". |
| `traderstack-resume` | Removes the sentinel file. Does **not** clear the `KILL_SWITCH` setting, the Redis key, or a latched `SIGUSR1` — those are separate channels and print as a reminder. |
| `traderstack-trace` | Read-only: prints the full ordered runtime-event trace for one `decision_id` from Postgres (requires `--persistent-events` to have been running). `traderstack-trace <decision_id> [--limit N]`. |
| `traderstack-research` | Runs the research harness end-to-end over a candle history (JSON file via `--candles`, or live from Kraken via `--symbol`): backtest with realistic costs, walk-forward, required baselines, and a performance attribution report. `--json` for machine-readable output. |
| `traderstack-download-candles` | Pages Kraken's public OHLC REST endpoint into the JSON candle format `traderstack-research --candles` and `traderstack-paper-report --candles` expect. Network only, no credentials required (public endpoint). |
| `traderstack-soak` | Drives the real service wiring against a seeded synthetic market (no network/database/credentials) for an acceptance soak window and emits a pass/fail JSON report. See "24/7 acceptance soak" below. |
| `traderstack-paper-report` | Reconstructs the paper equity curve from a completed run's audit trail and ledger, and compares it against the buy-and-hold / momentum / trend / mean-reversion / volatility-targeted baselines. See "Paper performance versus baselines" below. |

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
6. **Optional: observability** (Grafana/Prometheus dashboards):
   ```bash
   make run-observability
   ```
   **Grafana anonymous access is enabled by default** (`GF_AUTH_ANONYMOUS_ENABLED=true`,
   Viewer role) for local single-operator convenience — anyone who can reach
   port `3000` sees the dashboards with no login. This is fine on a laptop;
   before running the `observability` profile anywhere network-reachable by
   others, put Grafana behind real ingress/auth (`docs/INFRASTRUCTURE.md`,
   and `docs/SECURITY-REVIEW-2026-09.md` SEC-2026-09-09) or disable anonymous
   access in `ops/grafana/`. The same "don't expose it as shipped" caution
   applies to Prometheus, Loki and Postgres, none of which have their own
   auth in the default compose file.
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
- **`PERPLEXITY_API_KEY`**: `market/perplexity.py` targets Perplexity's **Agent
  API** (`POST /v1/agent`), not the older Sonar Chat Completions endpoint
  (`POST /v1/sonar`) — Perplexity's own docs mark Sonar deprecated in favour of
  the Agent API and scheduled to stop working 27 Sep 2026. No `.env` change is
  needed for this (same API key, this repo already targets the new endpoint);
  it's noted here so an operator debugging a Perplexity failure checks the
  right endpoint's status, not the deprecated one. See
  `docs/PROVIDER-CAPABILITY-MATRIX.md`, "Perplexity news adapter", for the
  verified source links and date.
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
engine (`RiskEngine._halted`, checked **first**, before any other limit), outside
the LLM runtime, and its only failure mode is closed (rejecting trades), never
open. Implementation: `src/traderstack/killswitch.py`.

**Four independent channels, and engaging *any one* of them halts new risk.**
There is no priority order between them — `KillSwitch.engaged` is `True` if any
is:

| Channel | How to engage it | How to release it | Notes |
|---|---|---|---|
| `KILL_SWITCH` setting | Set `KILL_SWITCH=true` in `.env`, restart the process. | Set `KILL_SWITCH=false`, restart. | Version-controlled; the only channel that requires a restart to change. Default is `true` — every proposal is rejected with `kill_switch_enabled` until an operator deliberately turns it off. |
| Sentinel file (`KILL_SWITCH_FILE`, default `var/state/KILL`) | `traderstack-kill` (or `touch` the file directly). No process cooperation or API call needed — any operator with filesystem access can do this even if the app is unresponsive. | `traderstack-resume` (or delete the file). | Re-probed by the risk engine live, every cycle — **no restart required** for either direction. `var/state` is the same volume as `--checkpoint-path` (`app_state` in Docker), so this works identically from the host or inside the container. |
| Redis key (`KILL_SWITCH_REDIS_KEY`, default `traderstack:kill_switch`) | `SET traderstack:kill_switch 1` (any truthy value: not `""`/`"0"`/`"false"`/`"no"`/`"off"`) against `REDIS_URL`. Requires `KILL_SWITCH_REDIS_ENABLED=true`. | `DEL traderstack:kill_switch` or set it to a falsy value. | Lets a remote operator or an external monitor halt the fleet without touching the host at all. **An unreachable Redis (timeout, connection refused, auth failure) is treated as engaged, not clear** — `KillSwitch.refresh()` catches the probe exception and sets `redis_engaged = True` rather than assuming "no signal means safe". If Redis being briefly unreachable ever halts trading unexpectedly, check `KillSwitch.redis_error` / the `traderstack_kill_switch_source_engaged{source="redis"}` gauge before assuming a deliberate halt. |
| `SIGUSR1` | `kill -SIGUSR1 <pid>` (or `docker compose exec app kill -SIGUSR1 1`). | **Cannot be released from inside the process** — restart it. | A process-wide latch: once received, it stays engaged for the life of the process by design (`install_signal_handler`/`_signal_engaged`). Unavailable on platforms without `SIGUSR1` or when called off the main thread; the other three channels are unaffected. |

Re-probing happens at the start of **every** service cycle
(`ContinuousPaperService._refresh_kill_switch`, before the pipeline runs for
each symbol) — see `docs/EXECUTION-ARCHITECTURE.md`, "Cycle order of
operations". Because the check happens first in `RiskEngine.evaluate`, an
already-in-flight cycle finishes its current step but no new order is ever
placed once any channel engages.

Check which channel(s) are currently engaged with the Prometheus gauges
`traderstack_kill_switch_engaged` (overall) and
`traderstack_kill_switch_source_engaged{source="settings"|"file"|"redis"|"signal"}`
(per channel), or by reading `KillSwitch.engaged_sources` if you're inspecting
the process directly.

`traderstack-check-config` flags `KILL_SWITCH=false` outside
`APP_ENV=development` as an unsafe combination precisely so the settings
channel is never left disengaged by accident; it also reports the sentinel
path and whether the Redis channel is enabled (never its value).

**Drill**: periodically verify the switch actually stops trading —
`traderstack-kill`, and confirm every subsequent audit line shows
`"rejection_reasons":["kill_switch_enabled"]` before you rely on it in an
incident, then `traderstack-resume` and confirm trading resumes. This exact
drill runs automatically in `tests/acceptance/test_kill_switch_drill.py` and as
a soak scenario (`traderstack-soak --scenario
ops/soak/scenarios/kill_switch_drill.json`) — see "24/7 acceptance soak" below.
Running those is not a substitute for throwing the switch on the real
deployment you depend on, but a failure in either means the switch is broken
before you get there.

## 24/7 acceptance soak

The MVP exit criteria require "at least one continuous 24/7 test window". The
`traderstack-soak` entry point is how you produce the evidence for it. It runs the
**real** service wiring — the same `cli.build_service` a live paper run uses, so the
same pipeline, deterministic risk engine, pre-trade gate, execution planner, idempotent
submitter, execution ledger, reconcilers, kill switch and hash-chained audit trails —
against a seeded synthetic market instead of live providers. It needs no network, no
database and no vendor credentials, so it can be left running anywhere.

```bash
# 24-hour window, one cycle every 5 seconds, JSON report written at the end
.venv/bin/traderstack-soak \
  --seconds 86400 \
  --cycle-seconds 5 \
  --workdir var/soak \
  --report var/soak/report.json
```

Useful variations:

```bash
# A quick smoke run before committing to 24 hours
.venv/bin/traderstack-soak --cycles 200 --workdir var/soak

# The shipped scenarios: clean baseline, provider outages, kill-switch drill
.venv/bin/traderstack-soak --scenario ops/soak/scenarios/baseline.json --seconds 86400
.venv/bin/traderstack-soak --scenario ops/soak/scenarios/provider_outage.json --cycles 60
.venv/bin/traderstack-soak --scenario ops/soak/scenarios/kill_switch_drill.json --cycles 30

# Multi-symbol, different market path
.venv/bin/traderstack-soak --seconds 86400 --symbols BTC/USD,ETH/USD --seed 99
```

A scenario file pins the market (`seed`, `drift`, `volatility`, `history`), the duration,
any `Settings` overrides, and a fault schedule — each entry names a fault, the cycle it
arms at, and either the cycle it disarms at or how many activations it gets. `--cycles`,
`--seconds`, `--seed` and `--symbols` on the command line override the file.

The run writes into `--workdir` (default `var/soak`) exactly what a real paper run
writes: `audit/runtime.jsonl`, `audit/risk_decisions.jsonl`, `state/execution_ledger.json`
and `state/portfolio.json`.

**What "pass" means.** The runner exits `0` only when every criterion below holds, and
prints any that failed under `Result` (also in `failures[]` in the JSON report):

- cycles actually ran;
- the risk-decision hash chain verifies end to end (`risk_audit.verify_chain`);
- every risk decision made reached the audit trail;
- no decision produced more than one venue order, and there are never more receipts
  than venue submissions — i.e. the idempotency guard held for the whole window;
- runtime events were persisted (unless a sink-failure fault was deliberately armed).

Rejections are **not** failures. A window full of `no_independent_reference_price`,
`stale_primary_tick` or `kill_switch_enabled` is the system doing its job; read the
`rejection_reasons` and `risk_reasons` maps in the report to see which control fired
and how often. What you are looking for in a 24-hour report is:

- `health.healthy: true` and `health.consecutive_errors: 0` at the end;
- `outcomes.error_cycles` at or near zero (an error cycle is an *exception*, not a
  rejection);
- `reconciliations.blocked: 0`, or blocks that cleared;
- `provider_breakers` all `closed` at the end;
- `ledger_orders == orders_submitted`, and every order in a terminal or open state you
  can explain.

Keep `var/soak/report.json` alongside the audit trail: together they are the artefact
that satisfies the exit criterion, and `traderstack-paper-report` (below) turns the same
files into the performance comparison.

## Paper performance versus baselines

After a paper run (or a soak), reconstruct what it actually achieved and compare it with
the simple baselines from `docs/EVALUATION-FRAMEWORK.md`:

```bash
.venv/bin/traderstack-paper-report \
  --audit-path var/audit/runtime.jsonl \
  --ledger-path var/state/execution_ledger.json \
  --candles var/research/btc_1h.json \
  --fee-bps 15
```

It rebuilds the paper equity curve from the audit trail's ticks and the ledger's fills,
matches buys and sells FIFO into round trips, scores them with the same metrics the
research harness uses, and prints the excess over buy-and-hold, time-series momentum,
moving-average trend, mean reversion and the volatility-targeted benchmark, followed by
the attribution table. `--json` emits the same thing machine-readably.

Two things it will not do, by design:

- It never invents fees. Paper receipts carry no fee data, so fees are `0` unless you
  pass `--fee-bps` to *estimate* them — and the report states which it used. Compare
  net-of-cost numbers only when you supplied a cost.
- It never assumes an unfilled order traded. Orders that were submitted but never
  reconciled to a fill are excluded, so a report showing "no fills" means reconciliation
  never confirmed one — check the ledger states, not the report.

Candles come from a JSON file (`--candles`, produced by `traderstack-download-candles`)
or, with `--candle-store`, from the Postgres candle store populated by
`--persistent-events`.

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

There are **two** audit files, deliberately separate — one is the full event
log, the other is the tamper-evident compliance record of risk decisions
specifically:

| File | Written by | Contents | Tamper-evident? |
|---|---|---|---|
| `--audit-path` (default `var/audit/runtime.jsonl`) | `JsonlAuditSink` | One line per symbol cycle: the full `RuntimeResult` — tick, references, pipeline result (including the pre-trade backtest/walk-forward check), risk result, meta-agent review, execution receipt/status. The complete, replayable decision trail. | No — plain JSONL, easy to `jq`, not hash-chained. |
| `--risk-audit-path` (default `var/audit/risk_decisions.jsonl`) | `JsonlRiskAuditTrail` | One line per risk decision *that actually reached the risk engine* (no line at all for cycles rejected upstream by market-data/intelligence/pre-trade gates): the full `TradeProposal`, the full `RiskResult`, the risk limits in force (inline and hashed), the meta-agent review and execution outcome from the *same* cycle, plus a SHA-256 hash chained to the previous record. | **Yes** — this is the record built specifically to survive an "did the agent secretly relax risk" audit. |

```bash
tail -f var/audit/runtime.jsonl | jq .
jq 'select(.pipeline.accepted_market_data == false)' var/audit/runtime.jsonl   # rejected cycles
jq '.pipeline.risk_result.decision' var/audit/runtime.jsonl | sort | uniq -c   # allow/reduce/reject counts
```

### Verifying the risk audit chain

```bash
.venv/bin/python -c "
from traderstack.risk_audit import verify_chain
result = verify_chain('var/audit/risk_decisions.jsonl')
print(result)
assert result.valid, result.error
"
```

`verify_chain` re-derives every record's hash from its own content and checks
it chains to the previous record's hash (`previous_hash`) and carries the
`sequence` it should. It reports the **first** sequence number where the chain
breaks (`first_invalid_sequence`) — an edited field, a removed line, or lines
out of order all produce a specific, located failure rather than a bare "invalid".
`traderstack-soak`'s pass criteria include this check running clean over the
whole window (see "24/7 acceptance soak" above); run it by hand any time you
need to hand someone evidence the trail hasn't been altered.

To see whether a decision the risk engine allowed was actually executed, read
one record's `result` (the risk engine's own decision) alongside its
`meta_review` and `execution_status`/`execution_reason` fields — added
specifically so this doesn't require cross-referencing `runtime.jsonl`
separately:

```bash
jq 'select(.result.decision == "allow" and .meta_review.suppressed_order == true)' \
  var/audit/risk_decisions.jsonl   # risk-approved cycles the meta-agent then vetoed
```

### What each rejection reason means

A cycle can be rejected at four points, each adding to
`pipeline.rejection_reasons` (or, for the risk engine, `pipeline.risk_result.reasons`
with `decision: "reject"`). Every value below is the literal string that appears in
the audit log (`src/traderstack/pipeline.py`, `src/traderstack/pretrade.py`,
`src/traderstack/risk.py`, `src/traderstack/agents/review.py`).

**Market data validation** (`VerticalSlicePipeline.process`, before any feature
vector exists — a data-quality gate, not risk policy):

| Reason | Meaning | Operator action |
|---|---|---|
| `stale_primary_tick` | The venue tick is older than `MAX_MARKET_DATA_AGE_SECONDS`. | Usually transient (network/venue latency). Persistent → check the venue feed (Kraken WS reconnects, or the Robinhood Chain websocket) is actually delivering. |
| `spread_limit_exceeded` | Bid/ask spread on the primary tick exceeds `MAX_SPREAD_BPS`. | Expected in thin/volatile conditions. Persistent on a liquid pair → check venue/pool liquidity, not a bug. |
| `no_independent_reference_price` | Neither CoinGecko nor CoinMarketCap returned a price for this asset. | Check `traderstack-check-config` shows both configured (or their unauthenticated fallback isn't rate-limited) and their provider circuit breakers aren't open — see "Provider circuit breakers and quotas". |
| `reference_price_divergence` | The primary tick diverges from the independent reference(s) by more than `MAX_REFERENCE_DIVERGENCE_BPS`. | Investigate before loosening the threshold — this is the control that catches a wrong/manipulated venue price. |

**External intelligence gating** (after market data is accepted, before a
proposal):

| Reason | Meaning | Operator action |
|---|---|---|
| `no_external_intelligence` | `INTELLIGENCE_REQUIRED=true` but no configured provider (Dune/LunarCrush/CryptoPanic/Perplexity/altFINS) returned anything this cycle. | Check provider keys/circuit breakers, or set `INTELLIGENCE_REQUIRED=false` if trading on market data alone is acceptable. |
| `adverse_news_event` | `INTELLIGENCE_BLOCK_ON_ADVERSE_NEWS=true` (default) and a news provider flagged an adverse event for this asset — new risk is blocked for the cycle; existing positions are untouched. | Expected behaviour during a real news event. Read the `news` feature fields in the audit line for which provider/asset triggered it. |

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

None of these need operator action beyond monitoring — a rejecting gate here is
working as intended (no history yet, or the ensemble genuinely doesn't clear its
own bar). Persistent `missing_candle_history`/`insufficient_candle_history` on
every cycle for one asset is the one worth investigating (candle provider outage
or a newly-added asset with too little history).

**Deterministic risk engine** (`RiskEngine.evaluate`, checked in this order,
tier by tier per `docs/RISK-PRINCIPLES.md`; always active, cannot be bypassed
by the LLM):

| Reason | Meaning | Operator action |
|---|---|---|
| `kill_switch_enabled` | Any kill-switch channel is engaged (see "Engaging/releasing the kill switch"). Every other check is skipped — this is the emergency-stop path. | Confirm it's intentional (`traderstack_kill_switch_source_engaged`), then `traderstack-resume` / clear the engaging channel when ready. |
| `stale_portfolio_state` | The local portfolio snapshot is older than `MAX_PORTFOLIO_STATE_AGE_SECONDS`. | Should not happen in the normal loop (the snapshot is built fresh each cycle) — investigate a wedged/slow cycle if seen. |
| `daily_loss_limit_reached` | Today's realized PnL has hit `MAX_DAILY_LOSS_PCT` of NAV (anchored at UTC midnight). | Expected control firing. Clears automatically at the next UTC day; do not raise the limit mid-incident to "let it keep trading". |
| `account_drawdown_limit_reached` | Drawdown from peak NAV has hit `MAX_ACCOUNT_DRAWDOWN_PCT`. | Same as above — a deliberate stop, not a bug. Investigate the drawdown's cause before ever considering a limit change. |
| `gross_exposure_limit` | Total exposure across all assets has reached `MAX_GROSS_EXPOSURE_PCT` of NAV, leaving no room for more. | Expected once the book is close to fully allocated. |
| `cash_reserve_breached` | Cash would fall below `MIN_CASH_RESERVE_PCT` of NAV if this proposal were approved. | Expected near full allocation; investigate only if it fires with substantial idle cash reported elsewhere. |
| `max_positions_reached` | The proposal's asset has no existing position and the book already holds `MAX_OPEN_POSITIONS` others. | Expected diversification control; not an error. |
| `strategy_circuit_breaker` | `StrategyCircuitBreaker` has tripped this `strategy_id` on realized underperformance (`STRATEGY_MAX_CONSECUTIVE_LOSSES` / rolling drawdown). | Investigate the strategy's recent trades before the cooldown (`STRATEGY_BREAKER_COOLDOWN_SECONDS`) expires; do not manually clear it without understanding why it tripped. |
| `asset_not_allowlisted` | The proposal's asset isn't in `MVP_ASSETS`. | Add it to `MVP_ASSETS` only after the same review any other risk-policy change gets. |
| `spread_too_wide` | The feature vector's spread reading exceeds `RISK_MAX_SPREAD_BPS` — the risk-policy spread gate, distinct from the pipeline's own `spread_limit_exceeded` (see `docs/EXECUTION-ARCHITECTURE.md`, "Two spread limits, deliberately"). | Same as `spread_limit_exceeded` — investigate venue/pool liquidity if persistent on a liquid pair. |
| `position_limit_reached` | Existing exposure to the asset already consumes all of `MAX_POSITION_PCT` of NAV, so remaining room is zero. | Expected once a position is fully sized. |
| `position_size_reduced` | *Not a rejection* — the decision is `reduce`, not `reject`. The requested notional was cut down to fit remaining `MAX_POSITION_PCT`/exposure/cash headroom, and the (smaller) order still proceeds. | Informational only. |
| `volatility_scaled` | *Not a rejection* — accompanies `ALLOW` or `REDUCE`. `VOLATILITY_SIZING_ENABLED=true` scaled the notional down by `TARGET_VOLATILITY` / observed volatility (never scaled up). | Informational only. |

A cycle with `pipeline.risk_result.decision == "reject"` and one of the risk-engine
reasons above still counted as `accepted_market_data: true` — market data,
intelligence and the backtest gate all passed; only the risk engine said no.

**Meta-agent review** (`agents/review.py`, only when `META_AGENT_MODE=veto`;
appended to `pipeline.rejection_reasons` *after* the risk engine already
approved the proposal — see `docs/EXECUTION-ARCHITECTURE.md`, "Cycle order of
operations"):

| Reason | Meaning | Operator action |
|---|---|---|
| `meta_agent_veto` | The reviewer explicitly declined this cycle (`approved: false` in its structured reply). The risk-approved order was withheld; nothing was submitted. | Read `meta_review.rationale` and `meta_review.risk_flags` in the audit line for why. Not an error — this is the reviewer doing its job. |
| `meta_agent_unavailable` | The review didn't produce a usable decision at all — timeout, transport error, invalid/unparseable reply, or an exhausted daily call/token budget. Fails closed: no reviewer available means no new risk in veto mode. | Check `meta_review.error` in the audit line. A budget exhaustion clears at the next UTC day; a timeout/error pattern warrants checking Anthropic API status and `ANTHROPIC_API_KEY`. |

A record showing `risk_result.decision == "allow"` next to either meta-agent
reason above is not a contradiction — it is the whole point of recording both.
See "Verifying the risk audit chain" above.

## Execution status and the order lifecycle

Once a proposal clears the risk engine (and, in veto mode, the meta-agent),
`IdempotentSubmitter.submit` (`execution/submitter.py`) returns a
`SubmissionStatus`, recorded on `RuntimeResult.execution_status` /
`execution_reason` and in the risk audit trail (see below):

| Status | Meaning | Operator action |
|---|---|---|
| `submitted` | Sent to the venue and acknowledged. | None. |
| `duplicate` | This `decision_id` already has a ledger order — nothing was sent (the idempotency guard held). | None; confirms the guard is working. Persistent duplicates for the same decision across restarts are expected (that's the point of the ledger). |
| `adopted` | An earlier `SUBMISSION_UNCERTAIN` submission turned out to exist at the venue after all — reconciliation found it and adopted it rather than resubmitting. | None; the correct outcome of the uncertain-timeout path below. |
| `plan_rejected` | `ExecutionPlanner` refused the order — quantity rounds to zero at `EXECUTION_LOT_STEP`, below `EXECUTION_MIN_NOTIONAL_USD`, or the execution price is outside `EXECUTION_MAX_SLIPPAGE_BPS` of the pipeline's validated tick (in *either* direction — a suspiciously favourable price is treated as a data-integrity signal, not a gift). | Usually a sizing/liquidity artefact, not a bug. Persistent slippage rejections on a liquid pair warrant checking the venue's actual spread. |
| `rejected` | Permanent failure — a 4xx from the venue, or retries exhausted after confirmed absence (see `SUBMISSION_UNCERTAIN` below). Terminal in the ledger; never retried automatically. | Read `execution_reason` for the venue's message. Investigate before manually intervening. |
| `uncertain` | The venue's truth for this order is unknown right now (see next section). No retry is permitted until reconciliation resolves it. | See "Resolving `SUBMISSION_UNCERTAIN`" below. |

**`OrderLifecycleState`** (`execution/ledger.py`) tracks the order itself once
submitted: `PLANNED` → `SUBMITTED` → (`SUBMISSION_UNCERTAIN` if uncertain) →
`ACKNOWLEDGED` → `OPEN` → `PARTIALLY_FILLED` → one of the terminal states
`FILLED`/`CANCELLED`/`REJECTED`/`EXPIRED`. Nothing moves backwards, and the
four terminal states never reopen — `IllegalStateTransition` is raised (and
refused before any quantity is mutated) if code ever tries.

### Resolving `SUBMISSION_UNCERTAIN`

**What it means:** the submission timed out or the venue returned a
transport error/5xx. This is explicitly **not** "the order failed" — the
venue may or may not have received it. No retry is permitted until a
reconciliation pass has positively confirmed the venue does not know the
client order id (`docs/EXECUTION-ARCHITECTURE.md`, "Retry and timeout").

**Manual procedure, if a decision appears stuck in this state:**

1. Confirm reconciliation is actually running: `RECONCILE_INTERVAL_SECONDS`
   has elapsed at least once since the timeout, and
   `traderstack_reconciliation_blocked` isn't itself stuck at `1` for an
   unrelated reason (transport error to Hummingbot, NAV drift) — fix that
   first, since reconciliation being blocked also blocks resolving this order.
2. Once reconciliation is healthy, check `var/state/execution_ledger.json`
   (or the ledger passed to `reconcile_now()`) for the order's current state:
   - resolved to `submitted`/`acknowledged`/`open`/a fill → done, no action
     (this is the `adopted` path above).
   - resolved to `rejected` after exhausting `EXECUTION_MAX_RETRIES` → done,
     terminal, investigate the recorded reason if unexpected.
   - still `submission_uncertain` after several reconciliation passes →
     escalate: check Hummingbot API connectivity/health directly
     (`docker compose logs hummingbot-api`) and the venue account's own
     order history for the `client_order_id` (deterministic, derived from
     `decision_id` alone — see `execution/planner.py`).
3. **Never hand-edit the ledger or portfolio checkpoint to force a state.**
   Let reconciliation's authoritative venue read resolve it, exactly as in
   the reconciliation-drift incident procedure below — the two situations
   share the same underlying discipline (venue state wins).
4. If the venue is confirmed genuinely unreachable for an extended period,
   engage the kill switch while you investigate; new proposals keep being
   evaluated and audited, but no new submission is attempted regardless.

## Meta-agent modes and budgets

`META_AGENT_MODE` (`.env.example`) controls `agents.review.MetaAgentReviewer`,
the one bounded LLM step between the deterministic pipeline and execution:

- **`off`** — never called. No cost, no effect, nothing recorded beyond `mode: "off"`.
- **`advisory`** (default) — called and recorded (rationale, risk flags, an
  implied confidence delta) on every eligible cycle, but **never changes
  execution**: the proposal, risk result and paper order are all untouched.
  Safe to run in production to build a track record before trusting `veto`.
- **`veto`** — a decline (`approved: false`) or *any* failure (timeout, error,
  invalid reply, exhausted budget) suppresses the paper order for that cycle
  (`meta_agent_veto` / `meta_agent_unavailable` above). An approval may still
  adjust `TradeProposal.confidence` within the bounded `±0.15` delta in
  `MetaAgentDecision` — it can never re-side, re-size, or increase the
  risk-approved notional. **Requires `ANTHROPIC_API_KEY`**; the process raises
  at startup rather than running a veto gate with no reviewer behind it
  (`traderstack-check-config` flags this combination).

By the time the reviewer sees anything, side, asset and risk-approved notional
are already fixed by the deterministic layers upstream — it can only remove
risk that was already approved, never add any. The technical/on-chain/
narrative specialists in `agents/specialists.py` that feed it evidence are
themselves deterministic feature readers, not further model calls.

**Cost controls**, all in `.env.example` under `META_AGENT_*`:

- `META_AGENT_CACHE_SECONDS` — identical evidence (a SHA-256 digest of the
  decision-relevant packet, excluding wall-clock timestamps) within this
  window reuses the previous decision without a new call.
- `META_AGENT_MAX_CALLS_PER_DAY` / `META_AGENT_MAX_TOKENS_PER_DAY` — UTC-day
  budgets; `0` disables that dimension. Exceeding either makes the reviewer
  unavailable for the rest of the day, which fails closed in veto mode.
- `META_AGENT_INPUT_COST_PER_MTOK` / `META_AGENT_OUTPUT_COST_PER_MTOK` —
  operator-supplied USD/million-token rates for the cost telemetry
  (`meta_agent_cost_usd_total`) only; **not authoritative pricing** — verify
  against Anthropic's current published rates before trusting the number for
  billing reconciliation.
- `META_AGENT_TIMEOUT_SECONDS` — a slow reply counts as `meta_agent_unavailable`,
  not a hang.

`traderstack-check-config` reports the current mode, model, budgets and
whether `ANTHROPIC_API_KEY` is present (never its value).

## Provider circuit breakers and quotas

Every external provider — reference prices (CoinGecko, CoinMarketCap), candle
history (Kraken), and every intelligence adapter (Dune, LunarCrush,
CryptoPanic, Perplexity, altFINS) — is wrapped in a per-provider
`traderstack.market.registry.ProviderRegistry` (`build_provider_registry` in
`cli.py`), giving each one, independently:

- **Timeout** (`PROVIDER_TIMEOUT_SECONDS`, shared default) — a call that
  doesn't return in time is treated as a failure for that provider only.
- **Circuit breaker** (`PROVIDER_FAILURE_THRESHOLD` consecutive failures opens
  it; `PROVIDER_BREAKER_COOLDOWN_SECONDS` before the next attempt) — an open
  breaker fails fast without hitting the provider, so one flaky vendor cannot
  slow down every cycle. Distinct from `StrategyCircuitBreaker`
  (`strategy_circuit_breaker` above), which trips on a *strategy's* realized
  trading performance, not a *provider's* transport health — same pattern,
  different layer, do not confuse the two.
- **Quota** (`*_CALLS_PER_MINUTE`/`*_CALLS_PER_DAY`, per provider in
  `.env.example`; `None`/blank = unlimited) — a soft budget enforced
  client-side so the app self-limits before the vendor does.
- **Caching** (`REFERENCE_PRICE_CACHE_SECONDS` for reference prices;
  `INTELLIGENCE_CACHE_SECONDS` for intelligence providers, at the
  orchestrator level) — reduces call volume; keep both well under
  `MAX_MARKET_DATA_AGE_SECONDS` so a cached price is never stale enough to be
  the effective cause of a `stale_primary_tick`-adjacent problem.

Inspect current state via `health()` on each `ProviderRegistry` (surfaced
through structured logs and the `traderstack_provider_*` Prometheus metrics —
`ops/grafana/dashboards/traderstack.json`'s "provider latency/failures" panel)
or `traderstack-check-config`'s per-provider quota lines. A provider showing
as configured (`traderstack-check-config`) but whose feature keeps rejecting
with `no_independent_reference_price`/`no_external_intelligence` is very
likely sitting behind an open breaker — check its `last_error`.

## Robinhood Chain configuration prerequisites

Two independent, separately-configured surfaces use Robinhood Chain; neither
depends on the other, and either can be used without the other:

**1. Primary market-data feed** (`VENUE_FEED=robinhood_chain`) — replaces
Kraken as the primary tick source with a read-only Uniswap v3/v4 swap feed.
Requires, all fail-closed if missing:
- `ROBINHOOD_CHAIN_RPC_URL`, `ROBINHOOD_CHAIN_ID` — sourced from Robinhood's
  own official chain docs (https://docs.robinhood.com/chain/connecting),
  never guessed. The feed independently verifies the connected endpoint's
  `eth_chainId` against this value before trusting anything it sends.
- `ROBINHOOD_CHAIN_WS_URL` — a **websocket** JSON-RPC endpoint for
  `eth_subscribe`; the public Robinhood RPC has none, so this must be a
  provider endpoint (Alchemy/Chainstack/dRPC — see `docs/DATA-SOURCES.md`).
- `ROBINHOOD_CHAIN_POOLS` — at least one pool matching an asset in
  `MVP_ASSETS`, or `build_service` refuses to start
  ("no ROBINHOOD_CHAIN_POOLS match MVP_ASSETS").
- `ROBINHOOD_CHAIN_V4_POOL_MANAGER` — only if any configured pool is v4.

**2. On-chain execution scaffolding** (`execution/robinhood_chain.py`) —
independent of which venue feed is active. Requires
`ROBINHOOD_CHAIN_ALLOWED_TOKENS` and `ROBINHOOD_CHAIN_ALLOWED_ROUTERS`
(deterministic allowlists — nothing outside them can be swapped/routed
through) plus the RPC/chain-id settings above. It only ever produces an
**unsigned, simulated** transaction — see `docs/EXECUTION-ARCHITECTURE.md`,
"Robinhood Chain Scaffolding" — never signs or broadcasts, and `live` mode is
rejected outright regardless of configuration.

`traderstack-check-config` reports both surfaces separately: "robinhood chain
feed configured" (surface 1, only checked when `VENUE_FEED=robinhood_chain`)
and "Robinhood Chain execution configured" (surface 2, always checked) plus
its max notional — a configured-but-`ROBINHOOD_CHAIN_MAX_NOTIONAL_USD<=0`
combination is flagged as a warning even though it fails closed by design
(every transaction blocked), so an operator notices before assuming it's live.

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
   be reconciled blocks new risk. The runtime already does this itself — a failed
   pass sets `RuntimeHealth.reconciliation_blocked` (gauge
   `traderstack_reconciliation_blocked`), which stops *submission* while decisions,
   sizing and auditing keep running, and clears on the next clean pass
   (`tests/acceptance/test_reconciliation_drift.py`). Engage the kill switch anyway
   if you want decisions to stop as well while you investigate.
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
