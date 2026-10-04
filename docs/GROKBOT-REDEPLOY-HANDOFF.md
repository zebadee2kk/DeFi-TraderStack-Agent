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

## 4. Run safe bootstrap preflight and resource audit

```bash
.venv/bin/traderstack-redeploy-preflight --host-published-services
.venv/bin/traderstack-resource-audit --probe-public
```

The bootstrap preflight is the rebuild gate: paper mode, kill switch, promotion/diagnostic flags, public Polymarket reachability, and the warehouse must be safe/available.

Then record the stricter resource-completeness result:

```bash
.venv/bin/traderstack-redeploy-preflight --strict-resources --host-published-services
```

A strict-resource failure caused only by missing optional/keyed intelligence credentials is an **activation/readiness blocker**, not a reason to keep running an obsolete app image. The app may still be rebuilt with `KILL_SWITCH=true` so public/available collectors and health evidence can run. Do not declare the deployment resource-complete and do not disengage the kill switch until the strict gate passes.

Before treating missing credentials as a manual file-edit task, run the WSL helper:

```bash
make configure-api-credentials
```

or directly:

```bash
python3 ops/configure-api-credentials.py
```

The helper:
- prompts only for missing managed credentials by default;
- hides secret input from the terminal;
- never accepts secret values on the command line;
- preserves unrelated `.env` settings;
- sets `.env` mode to `0600`;
- manages required `DUNE_API_KEY`, `DUNE_QUERY_IDS`, `LUNARCRUSH_API_KEY`, `CRYPTOPANIC_API_KEY`, `PERPLEXITY_API_KEY`, and `ALTFINS_API_KEY`;
- can optionally manage `COINGECKO_API_KEY` and `COINMARKETCAP_API_KEY` for quota/headroom;
- does not modify Crucix or trading/risk settings.

Use `python3 ops/configure-api-credentials.py --status` to show only SET/MISSING/OPTIONAL state without printing values.
Use `python3 ops/configure-api-credentials.py --guide` for acquisition guidance without prompting for secrets.
Use `--include-optional` only when you want CoinGecko/CoinMarketCap keys, and `--all` only when intentionally rotating existing values.

The strict configuration gate requires explicit operator decisions/configuration for:

- Dune (API key + query IDs);
- LunarCrush;
- CryptoPanic;
- Perplexity;
- altFINS;
- Crucix.

CoinGecko and CoinMarketCap keys are optional because TraderStack supports their public/no-key reference-price paths. Their **post-start health** still matters and remains part of the active-resource gate.

Polymarket Data API v2 is public/no-key and must be reachable.

If a paid/keyed resource is unavailable, report the exact variable/resource name and keep it as an activation blocker. Do not generate a key, commit a secret, silently substitute another provider, weaken the strict preflight, or disengage the kill switch. Continue safe rebuild/collection steps that do not require that credential.

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
.venv/bin/traderstack-redeploy-preflight --require-active-resources --host-published-services
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
