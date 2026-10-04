# Grokbot redeploy handoff — data/intelligence course correction

**Target:** redeploy the current repository into a safe paper/research state after #191–#193 course-correction work.

## Non-negotiable safety state

The first boot must use:

- `TRADING_MODE=paper`;
- `KILL_SWITCH=true`;
- every `PAPER_PROMOTE_*` boolean false;
- `PAPER_GARCH_SIZE=false`;
- `PAPER_PERP_HEDGE=false`;
- `PAPER_CARRY_HEDGE_DIAGNOSTIC=false`;
- `OPPORTUNITY_DIAGNOSTIC_MODE=false`;
- no live-capital path and no new `--submit` argument.

Do not invent credentials, disable a failing gate, or set a provider to healthy without a successful call.

## 1. Reconcile the checkout

```bash
git status --short --branch
git fetch origin main
git checkout main
git pull --ff-only origin main
git status --short --branch
git log -1 --oneline
```

The worktree must be clean before deployment.

## 2. Install and verify repository code

```bash
make setup
make check
make check-config
```

Any failure is a deployment blocker.

## 3. Start durable dependencies only

```bash
docker compose up -d postgres redis
docker compose ps
```

Wait for PostgreSQL to be healthy.

## 4. Run strict resource/deployment preflight

```bash
.venv/bin/traderstack-redeploy-preflight --strict-resources
.venv/bin/traderstack-resource-audit --probe-public
```

The strict preflight deliberately blocks when any intended resource is missing.

The current programme expects explicit operator decisions/configuration for:

- Dune;
- LunarCrush;
- CryptoPanic;
- Perplexity;
- altFINS;
- Crucix;
- CoinGecko;
- CoinMarketCap.

Polymarket Data API v2 is public/no-key and must be reachable.

If a paid/keyed resource is unavailable, **stop and report the exact variable/resource name**. Do not generate a key, commit a secret, silently substitute another provider, or weaken the strict preflight.

## 5. Initialize/verify the intelligence warehouse

The preflight creates/checks the PostgreSQL warehouse tables. Then run:

```bash
.venv/bin/traderstack-signal-health-import
.venv/bin/traderstack-signal-coverage
```

Expected logical stores now include:

- `feature_snapshots`;
- `provider_observations`;
- `collector_health`;
- `wallet_observations`;
- existing runtime-event/candle/audit stores.

The append-only provider-health journal remains first-write operational evidence and is not replaced by PostgreSQL.

## 6. Prove Polymarket wallet collection manually

```bash
bash ops/polymarket-intelligence-collect.sh
.venv/bin/traderstack-polymarket-wallet-cohorts --time-period MONTH --top 25
```

This uses current Polymarket Data API v2 for leaderboard/trades/positions and records exact point-in-time cohort identity.

A zero/short cohort is evidence, not permission to change ranking rules.

## 7. Start the app with the kill switch still engaged

```bash
docker compose --profile app up -d --build
docker compose ps
curl -fsS http://127.0.0.1:9108/metrics >/dev/null
docker compose logs --tail=300 app
```

Confirm:

- app healthy;
- PostgreSQL/Redis reachable;
- no restart loop;
- no secret value in logs;
- no `PAPER_PROMOTE_*` pin became true;
- no live/Hummingbot execution profile was started.

After enough runtime cycles for provider health to be recorded, require **actual successful calls**, not just configured keys:

```bash
.venv/bin/traderstack-redeploy-preflight --require-active-resources
```

If this fails, leave the kill switch engaged and resolve the named provider/network/auth failure. Do not downgrade the check to configured-only.

## 8. Schedule intelligence accumulation

Run `ops/polymarket-intelligence-collect.sh` every **30–60 minutes**.

Run `ops/polymarket-wallet-signal-eval.sh` **daily** after snapshots begin accumulating.

Use the host's existing scheduler (systemd timer/cron/orchestrator). Do not put credentials in timer unit files or command lines.

The collector job writes the latest cohort report to:

`var/research/polymarket-wallet-cohorts-latest.json`

The evaluator writes:

`var/research/polymarket-wallet-signal-eval-latest.json`

The evaluator is research-only. It tests the frozen wallet hypotheses at 60/300/900-second copy delays and 25/50/100 bps per-side cost sensitivity. It never creates an order.

## 9. Human gate before disengaging the kill switch

Grokbot may complete all deployment, collection and smoke testing with `KILL_SWITCH=true`.

Do **not** change `KILL_SWITCH=false` automatically.

Return to the operator with:

- deployed commit SHA;
- `docker compose ps`;
- strict preflight output;
- resource-audit output;
- missing/blocked credentials, if any;
- signal coverage output;
- wallet snapshot summary;
- latest cohort report;
- latest wallet-signal evaluation summary if enough history exists;
- confirmation that all promotion flags remain false.

Only after that explicit human gate may the normal paper runtime be allowed to take paper risk.

## Definition of redeploy-ready

Repository side is ready when:

- main is clean and all intended PRs are merged;
- CI is green;
- `make check` is green;
- strict redeploy preflight exists and runs;
- Polymarket uses Data API v2, not retiring v1 leaderboard;
- PostgreSQL warehouse initializes;
- resource health is restart-persistent;
- wallet snapshots have exact cohort IDs;
- delayed wallet follow/fade evaluator is research-only and fail-closed on coarse/missing history;
- collection/evaluation jobs are documented and runnable;
- no live capital or promotion flag is enabled.

Local deployment is complete only when the operator-host preflight proves the resources actually available there.
