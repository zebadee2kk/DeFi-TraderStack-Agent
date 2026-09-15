# Operator Runbook

This is the operational guide for running DeFi TraderStack Agent as a paper-trading
service: zero-to-running, day-to-day operation, the kill switch, key rotation, how to
read what it produced, and how to respond to the incidents that matter most in the MVP.

The default, production-supported path is **`TRADING_MODE=paper`**.
`TRADING_MODE=shadow` is the Phase 7 record-only path (same decisions, no venue
orders). `TRADING_MODE=live` is rejected at startup. Live capital is explicitly
out of MVP scope (see `docs/MVP-BACKLOG.md`); nothing in this document
authorizes live trading.

## Console scripts

Every entry point below is a `[project.scripts]` console script (`pyproject.toml`),
runnable as `traderstack-<name>` once installed, or `.venv/bin/traderstack-<name>`
without activating the venv.

| Script | What it does |
|---|---|
| `traderstack-paper` | Runs the continuous service (`ContinuousPaperService`). In `TRADING_MODE=paper`, `PAPER_SIMULATE_FILLS=true` (default) books each risk-allowed `paper_order` into the local portfolio at mid ± `PAPER_SLIPPAGE_BPS` with `PAPER_FEE_BPS` — no Hummingbot and no `--submit` required. `--submit` is the optional Hummingbot paper-venue path (see below). In `TRADING_MODE=shadow`, `--submit` is ignored and would-have-been orders are written to `--shadow-ledger-path`. See "Zero to paper trading" and "Shadow-live" below. |
| `traderstack-check-config` | Loads `Settings` exactly as the runtime does and prints what's enabled — venue feed, meta-agent mode, every provider, execution/reconciliation settings, provider quotas, kill-switch channels, risk limits, position-exit rules — warning (and exiting non-zero) on unsafe combinations. Never prints secret values. Run this before every start and after every `.env` change. |
| `traderstack-kill` | Engages the kill switch by writing the sentinel file (`--file`, default `$KILL_SWITCH_FILE` or `var/state/KILL`). Needs no access to the running process. See "Engaging / releasing the kill switch". |
| `traderstack-resume` | Removes the sentinel file. Does **not** clear the `KILL_SWITCH` setting, the Redis key, or a latched `SIGUSR1` — those are separate channels and print as a reminder. |
| `traderstack-trace` | Read-only: prints the full ordered runtime-event trace for one `decision_id` from Postgres (requires `--persistent-events` to have been running). `traderstack-trace <decision_id> [--limit N]`. |
| `traderstack-research` | Runs the research harness end-to-end over a candle history (JSON file via `--candles`, or live from Kraken via `--symbol`): backtest with realistic costs, walk-forward, required baselines, and a performance attribution report. `--json` for machine-readable output. |
| `traderstack-strategy-search` | Offline catalog search: scores the expanded pre-registered catalog (MA / momentum / mean-reversion + vol-regime filters; optional funding / OI / liquidation series) on Kraken charts-spot (~180d 1h) or public Spot OHLC (720-bar cap) with `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` costs, walk-forward + holdout, and a pre-registered top-1 / Bonferroni-honest ranking. Promotion additionally requires WF **total** return > 0. Writes `var/ops/strategy_search_report.{json,md}`. Never flips `PAPER_PROMOTE_SEARCHED_STRATEGIES`. |
| `traderstack-miles-search` | Miles-inspired catalog search: EMA 9/21 and 12/26 (optional ADX gate) × optional GARCH vol-targeted sizing, scored on Kraken Spot OHLC (daily and 1h, 720-bar public cap) with `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` costs, walk-forward + holdout. Writes `docs/artifacts/strategy-search/miles-inspired-report.md`. Never flips `PAPER_GARCH_SIZE` or `PAPER_PROMOTE_EMA_9_21`. Daily promotion is not a 1h-runtime claim — the paper promote flag forces `1d` / 1440m. |
| `traderstack-daily-robustness` | Daily robustness / balanced-holdout pass: EMA 9/21, 12/26, 20/50, 50/200 (ADX variants), dual-mom grid, buy-the-dip, MA risk-off, optional GARCH size on the longest Kraken public daily OHLC (720-bar ≈ 2y cap). Optional Yahoo Finance BTC-USD/ETH-USD daily is a non-Kraken A/B only. Promotes only if **BTC and ETH** both have WF total > 0 **and** both have holdout excess > 0 (ETH cannot carry a losing BTC holdout). Writes `docs/artifacts/strategy-search/balanced-holdout-report.md`. Never flips `PAPER_PROMOTE_*`. |
| `traderstack-harder-gates` | Harder honesty gates on the Kraken daily 720-bar window: **A** magnitude (BTC and ETH holdout excess > 0 and min/max ratio ≥ 0.25), **B** three contiguous 240-bar windows (BTC and ETH WF total > 0 in ≥ 2 of 3), **C** 2× fees (20+10 bps) still clearing #96 balanced signs. Default catalog is the frozen expanded post-#97 grid. Ranking key (frozen before scoring): mean holdout excess among combined-passers. Yahoo is A/B only. Writes `docs/artifacts/strategy-search/expanded-harder-gates-report.md`. Never flips `PAPER_PROMOTE_*`. An empty promotee is success. |
| `traderstack-honesty-pack` | Focused honesty reprint for one combined-passer (default `ema_9_21_adx15`): Kraken A/B/C row, Yahoo `period1`/`period2` A/B for **that** id only (cannot promote), WF maxDD vs paper DD ceiling 0.30, and the gate-B multi-window table. Writes `docs/artifacts/strategy-search/ema-9-21-adx15-honesty.md`. Never flips `PAPER_PROMOTE_*`. Empty or negative Yahoo is success. |
| `traderstack-second-print` | Second independent print for `ema_9_21_adx15` (and the other #99/#100 combined-passers). Kraken public OHLC cannot unlock a second 720; scores the holdout-blind prefix (same venue; not independent) and a pre-registered older Binance Spot daily 720 (BTCUSDT+ETHUSDT) ending before the primary Kraken first bar. Labeled non-Kraken / report-only; cannot enter the promotion average. Writes `docs/artifacts/strategy-search/ema-9-21-adx15-second-print.md`. Never flips `PAPER_PROMOTE_*`. An honest FAIL is success. |
| `traderstack-dual-print-search` | Expanded daily catalog (frozen K before pull) scored under the **pre-registered dual-print bar**: Kraken primary 720 must clear #96+A+B+C **and** the #102 Binance.US older-720 must also clear those combined gates. Ranking key: Kraken mean holdout excess among dual-print passers. Venues are not averaged. Writes `docs/artifacts/strategy-search/dual-print-search.md`. Never flips `PAPER_PROMOTE_*`. An empty dual-print set is success. |
| `traderstack-liq-regime-search` | Paper-only next slice after the empty #104 EMA dual-print: scores a frozen catalog **conditioned on** liquidation-z / funding-z / OI-z / cross-venue series when an aligned historical series exists, plus candle-only vol-regime wrappers. Public USDT-M liquidation REST is typically unusable and is skipped, not zero-filled. Dual-print only if historical liq exists on BTC+ETH **and** a second venue print is supplied; otherwise **single-print** and **cannot promote**. Writes `docs/artifacts/strategy-search/liq-regime-search.md`. Never flips `PAPER_PROMOTE_*`. Empty search is success. |
| `traderstack-intraday-dual-print` | Paper-only 4h (default) or 1h hunt after empty daily EMA (#104), empty liq (#105), and empty Polymarket PIT (#106). Frozen **non-EMA** catalog (MA / momentum / mean-reversion / vol-regime; funding/OI only if aligned series exist). Same #96+A+B+C combined gates on Kraken public Spot **and** the #102-style Binance.US older-720 of the same interval. Ranking is Kraken mean holdout among dual-print passers. Writes `docs/artifacts/strategy-search/intraday-dual-print.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. |
| `traderstack-funding-carry` | Paper-only funding-z threshold + hedged cash-and-carry catalog on BTC+ETH. Aligns Kraken public Spot (default 4h) to public funding-rate history (OKX + Hyperliquid + HTX when reachable; BitMEX is a sunset venue — official closure 23 September 2026 04:00 UTC — and is not selected; Binance/Bybit probed and skipped if geo-blocked). Dual-print only if two **independent funding venues** cover BTC and ETH; one venue is **single-print** and **cannot promote**. Hard gates (#96+A+B+C) stay UNAVAILABLE unless 720 aligned daily bars exist on **each** venue. Writes `docs/artifacts/strategy-search/funding-carry.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. |
| `traderstack-relative-value` | Paper-only BTC−ETH relative-value residual: fade/follow daily `r_BTC − r_ETH` at frozen \|z\| ≥ 1.0 / 1.5 / 2.0 (lookback 20). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/btc-eth-relative-value.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA reprint. |
| `traderstack-xs-momentum` | Paper-only BTC+ETH+SOL cross-sectional momentum: long top-1 / optional short bottom-1 by trailing N-day return (N in {21, 63, 126}; optional vol-scaled ranking; `ls` dollar-neutral or `lo` long-only). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs as before; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH/SOL. Writes `docs/artifacts/strategy-search/cross-sectional-momentum.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA or residual reprint. |
| `traderstack-donchian-breakout` | Paper-only Donchian / channel breakout: long-only or long/short on the prior N-day high/low (N in {20, 55, 100}; optional ATR(14) buffer on `lo` 20/55). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs as before; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/donchian-breakout.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA, residual, or XS reprint. |
| `traderstack-tsmom` | Paper-only time-series momentum: long-only or long/short on each asset's own trailing N-day close-to-close return (N in {21, 63, 126, 252}). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs as before; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/tsmom.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA, residual, XS, or Donchian reprint. |
| `traderstack-bollinger-fade` | Paper-only Bollinger band-fade / mean-reversion: fade-to-inside, long-only fade, and a squeeze-breakout contrast on own-asset SMA ± k × sample stdev (period×k in {20x2, 20x2.5, 40x2}). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs as before; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/bollinger-fade.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA, residual, XS, Donchian, TSMOM, or `mean_reversion_*` reprint. |
| `traderstack-calendar-seasonality` | Paper-only UTC calendar seasonality: day-of-week long-only (Mon / Fri / Mon+Fri), skip-weekend (long Mon–Fri, flat Sat/Sun), month-of-year (Q4 / Jan / Nov+Dec), and turn-of-month last 3 / first 3 UTC calendar days. Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs as before; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/calendar-seasonality.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA, residual, XS, Donchian, TSMOM, or Bollinger reprint. |
| `traderstack-lead-lag` | Paper-only BTC→ETH lead-lag: ETH follows or fades lagged BTC L-day return (L in {1,2,3,5} follow-lo; {1,2,3} follow-ls / fade-lo; BTC-follows-ETH mirror lo {1,2}). Not same-bar residual z-score (#116). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): both BTC and ETH legs; other leg is **flat**. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/lead-lag.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA, residual, XS, Donchian, TSMOM, Bollinger, or calendar reprint. |
| `traderstack-volume-breakout` | Paper-only volume-confirmed breakout: long-only or long/short on the prior N-day high/low **and** a volume gate (N×mult in {20x1.5, 55x1.5, 20x2}; V=20 SMA through t−1), plus a small volume-surge set. Not a Donchian N retune (#118). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs as before; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Paper-executable on Kraken spot BTC/ETH. Writes `docs/artifacts/strategy-search/volume-breakout.md`. Never flips `PAPER_PROMOTE_*`. Empty dual-print set is success. Not an EMA, residual, XS, Donchian, TSMOM, Bollinger, calendar, or lead-lag reprint. |
| `traderstack-download-candles` | Pages Kraken's public OHLC REST endpoint into the JSON candle format `traderstack-research --candles`, `traderstack-strategy-search --candles`, `traderstack-miles-search --candles`, `traderstack-harder-gates --candles`, `traderstack-honesty-pack --candles`, `traderstack-second-print --candles`, `traderstack-dual-print-search --candles`, `traderstack-liq-regime-search --candles`, `traderstack-intraday-dual-print --candles`, `traderstack-funding-carry --candles`, `traderstack-relative-value --candles`, `traderstack-xs-momentum --candles`, `traderstack-donchian-breakout --candles`, `traderstack-tsmom --candles`, `traderstack-bollinger-fade --candles`, `traderstack-calendar-seasonality --candles`, `traderstack-lead-lag --candles`, `traderstack-volume-breakout --candles`, `traderstack-ensemble-trend --candles`, and `traderstack-paper-report --candles` expect. Network only, no credentials required (public endpoint). `--venue` selects a longer history than Kraken's 720-bar REST cap: `coinbase` (Coinbase Exchange public candles), `binance_vision` (checksum-verified monthly spot zips) or `kraken_archive` (a local OHLCVT drop, no network). See "Multi-year candle archives". |
| `traderstack-soak` | Drives the real service wiring against a seeded synthetic market (no network/database/credentials) for an acceptance soak window and always writes a pass/fail JSON report (`<workdir>/report.json`). `--preset ci` is the short CI/smoke path; `--preset full` is the 86400s window. See "24/7 acceptance soak" below. |
| `traderstack-opportunity-funnel` | Zero-trade diagnosis (#131). Rebuilds the per-cycle opportunity funnel (`cycles → valid market data → signal candidate → pre-trade eligible → risk allowed → meta-agent retained → planner accepted → fill`) from a finished run's `audit/runtime.jsonl` (+ optional execution ledger) and names the dominant blocking gate with exact reason counts. Offline, read-only. The same funnel is written live to `--funnel-path` by `traderstack-paper` and into `traderstack-soak`'s `report.json`. See "Zero-trade diagnosis" below. |
| `traderstack-paper-report` | Reconstructs the paper equity curve from a completed run's audit trail and ledger, and compares it against the buy-and-hold / momentum / trend / mean-reversion / volatility-targeted baselines. See "Paper performance versus baselines" below. |
| `traderstack-polymarket-weather-paper` | **Opt-in, paper-only** Polymarket weather research. Compares Open-Meteo (or NOAA) highs to public CLOB mids and writes *would-trade* intents to a dedicated JSONL ledger. Never signs, never posts CLOB orders, never touches the crypto paper loop. Requires `TRADING_MODE=paper`. See "Polymarket weather paper research" below. |
| `traderstack-polymarket-weather-eval` | Fee-aware evaluation of that weather rule against `always_hold` and `fade_the_mid`. Dual independent prints (non-overlapping dates or disjoint resolution sources) are required before anyone may talk about promotion. Writes `docs/artifacts/strategy-search/polymarket-weather-eval.md`. Never flips `PAPER_PROMOTE_*`. Empty / negative is success. No CLOB orders. |
| `traderstack-ensemble-trend` | Paper-only ensemble trend (#137): long-only multi-lookback Donchian-on-close (N in {5, 10, 20, 30, 60, 90, 150, 250, 360}; bar t never sets its own level) with a trailing stop at max(prior stop, prior close-channel midpoint), equal-weight across open lookbacks, 25% annualised vol target on 90-day realised vol, capped at 1.0 (no leverage), on a frozen `CANDIDATE_UNIVERSE` of Kraken USD pairs with a monthly point-in-time top-20 snapshot (≥ 365 prior bars or 720-cap, median 30-day close×volume ≥ $2M; non-members forced flat). Not a Donchian N retune (#118). Same #96+A+B+C dual-print bar as #104 (Kraken public Spot daily 720 **and** the #102 Binance.US older-720). Multi-asset rule (frozen): BTC and ETH signs; SOL reported, not a gate. Ranking is Kraken mean holdout excess among dual-print passers. Fees from the frozen Kraken Pro tier table (`--kraken-tier`, default tier 1 = 80 bps taker per side) unless `--fee-bps` is explicit. Reports gross attribution by asset and by lookback. `era_prints_available=false` / `dsr_pbo_available=false` until #133 / #135 land (not invented). Accepts `traderstack-download-candles` JSON via `--candles`. Writes `docs/artifacts/strategy-search/ensemble-trend.md`. Never flips `PAPER_PROMOTE_*`; adds no Settings field. Empty dual-print set is success. |
| `traderstack-download-basis` | Second-venue point-in-time basis (#134). Downloads daily **mark close − index close, over index** from OKX (`history-mark-price-candles` − `history-index-candles`, `bar=1Dutc`, `confirm==1` rows only, serial pagination with backoff on 403/429) and Binance Vision (`markPriceKlines` − `indexPriceKlines` monthly + trailing-month daily zips, sha256 `.CHECKSUM` verified per zip, fail closed on mismatch) into `var/research/basis/<venue>/<SYMBOL>_basis_1d.json` (the `[{opened_at, value}]` shape `traderstack-funding-carry --basis-dir` reads) and writes the probe table `docs/artifacts/strategy-search/pit-basis-second-venue.md` (first/last/days/gaps per series; OKX×Vision aligned days). Funding premium, last-trade candles and funding-implied basis are refused in code. A missing day is a skip, never a zero; an unreachable venue is a recorded skip and the command still exits 0. Quote is USDT on both venues. Network only, no credentials. Never flips `PAPER_PROMOTE_*`. |
| `traderstack-polymarket-crypto-collect` | **Opt-in, paper-only** point-in-time tape (#142): per open Polymarket BTC/ETH "above $K on &lt;date&gt;" market, the CLOB mid against a Deribit option-implied `P(S_T > K)`, with both venue timestamps. GET-only Gamma / CLOB / Deribit public endpoints; no Deribit private endpoints, no signing, no CLOB orders, no size and no side. Crucix high-tier alerts are recorded as a withhold-only stand-aside. Requires `TRADING_MODE=paper`. Never flips `PAPER_PROMOTE_*`; an empty tape is success. See "Crypto-threshold wedge tape (#142)" below. |

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
   you *did* turn on requires it (e.g. `VENUE_FEED=robinhood_chain`, or
   `VENUE_FEED=kraken_rest` which is paper-only).
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
7. **Paper PnL (default, no Hummingbot):** Compose `app.command` and
   `make run-paper` do **not** pass `--submit`. That used to leave every
   RiskEngine `allow` as a `paper_order` intent with `execution_status=null`,
   no ledger row, and `traderstack_portfolio_nav_usd` stuck at the starting
   10000. With `PAPER_SIMULATE_FILLS=true` (documented paper default) an
   ALLOW that still has a `paper_order` after the meta-agent review is
   filled in-process at the primary mid ± `PAPER_SLIPPAGE_BPS` (adverse),
   charged `PAPER_FEE_BPS` (`fee_source=modelled`), written to the
   execution ledger, and applied to cash/positions/NAV. Restart is
   idempotent (same `paper-fill:<client_order_id>`). The kill switch, a
   meta-agent veto, reconciliation-blocked, or a torn ledger still
   withhold. Confirm with:
   ```bash
   curl -s http://localhost:9108/metrics | grep traderstack_portfolio_nav_usd
   curl -s http://localhost:9108/metrics | grep traderstack_paper_fills_total
   jq -r '.execution_status' var/audit/runtime.jsonl | sort | uniq -c
   ```
8. **Optional alternate: `--submit` + Hummingbot paper profile** — only
   after you've set `HUMMINGBOT_API_USERNAME`/`HUMMINGBOT_API_PASSWORD` and,
   if you want the `hummingbot-api` service defined in `docker-compose.yml`
   itself (rather than an externally-run one), started it:
   ```bash
   docker compose --profile execution up -d
   ```
   Then run the app with `--submit` (edit the `app` service `command:` or run
   `traderstack-paper --submit ...` directly). That path still only *submits*;
   venue fills land later via `HummingbotExecutionReconciler`. When
   `PAPER_SIMULATE_FILLS=true` the local book is already filled on ALLOW, so
   Hummingbot NAV reconcile is not wired (it would drift and freeze new
   risk). Set `PAPER_SIMULATE_FILLS=false` if you want venue trades to be
   the only fill source. Hummingbot is **not** required for basic paper PnL.

At every step, the pre-trade backtest gate and the deterministic risk engine are
active by default (`PRETRADE_BACKTEST_ENABLED=true`, `KILL_SWITCH=true`). With the
kill switch on, every proposal is deterministically rejected with
`kill_switch_enabled` — that's expected. See "Engaging/releasing the kill switch"
before disengaging it. Paper dry-runs on Kraken Spot OHLC with intel keys left
blank use `PAPER_RESEARCH_MODE=true` (documented paper default) so the
strategy ensemble can form a candle-only consensus on every allowlisted
asset and reach that risk decision; see "Paper research mode and strategy
consensus". Live/shadow never get that voter rule.

## Shadow-live

`TRADING_MODE=shadow` (Roadmap Phase 7) consumes the same live feeds and runs the
same decision, risk, pre-trade and meta-agent pipeline as paper. The difference
is at the execution boundary:

- approved intents are planned with the same lot / min-notional / slippage
  constraints;
- each would-have-been order is appended to `--shadow-ledger-path` (default
  `var/audit/shadow_intents.jsonl`) and stamped on the runtime audit line as
  `trading_mode: "shadow"` / `execution_status: "shadow_recorded"` (or
  `shadow_plan_rejected` / `shadow_duplicate`);
- Hummingbot is never constructed, even if `--submit` is passed;
- Robinhood Chain execution is not called; nothing is signed or broadcast;
- the paper portfolio is **not** filled from a shadow intent.

This is how you tell the two modes apart:

| Surface | Paper (`--submit`) | Shadow |
|---|---|---|
| `RuntimeResult.trading_mode` | `paper` | `shadow` |
| `execution_status` | `submitted` / planner or venue refusal | `shadow_recorded` / `shadow_plan_rejected` / `shadow_duplicate` |
| Prometheus | `traderstack_paper_orders_submitted_total` | `traderstack_shadow_intents_recorded_total` and `traderstack_trading_mode_info{mode="shadow"}=1` |
| Durable record | `var/state/execution_ledger.json` | `var/audit/shadow_intents.jsonl` |
| Venue HTTP | Hummingbot `POST /trading/orders` | none |

```bash
# .env: TRADING_MODE=shadow  (and KILL_SWITCH=false only if you actually want
# recorded intents; the default kill switch still rejects every proposal)
make check-config
make run-shadow
# or:
.venv/bin/traderstack-paper \
  --persistent-events \
  --shadow-ledger-path var/audit/shadow_intents.jsonl
```

`traderstack-check-config` reports shadow as "record only" and does **not** treat
it as an unsafe combination. `TRADING_MODE=live` is still flagged unsafe and
rejected by `cli.build_service`. Shadow does not authorise live capital; it is
the validation step *before* any live-capital phase.

Do not loosen kill switch, risk limits or pre-trade gates "to make shadow trade
more". A shadow run full of `kill_switch_enabled` is the system working.

## Filling in `.env` safely

- Start from `.env.example` — never commit a filled-in `.env` (it's gitignored).
- Leave any provider key blank to leave that feature off; nothing in this repo
  requires all providers to be configured. Run `traderstack-check-config` after
  editing to see exactly what turned on.
- Leave `PAPER_GARCH_SIZE=false` unless `traderstack-miles-search` shows
  walk-forward total return > 0 and holdout excess return > 0 after fees.
  The overlay does not relax `RiskEngine`; it can only reduce size. No
  GARCH-sized candidate cleared that bar on the committed daily window.
- Leave `PAPER_PROMOTE_EMA_9_21=false` unless you intend to register
  **only** the pre-registered daily winner `ema_9_21` as the paper
  pre-trade voter **and** run that voter on daily candles. Paper-only;
  ignored on live/shadow. Does not enable live. Does not flip
  `PAPER_GARCH_SIZE`. Takes precedence over
  `PAPER_PROMOTE_SEARCHED_STRATEGIES`. When the flag is on, paper
  ingestion / feature bars / the pre-trade backtest are forced to
  `1d` (Kraken interval 1440) even if `PRETRADE_CANDLE_INTERVAL=1h`.
- Leave `PAPER_PROMOTE_EMA_9_21_ADX15=false` unless you intend to
  register **only** the expanded harder-gates combined-passer top-1
  `ema_9_21_adx15` (EMA 9/21, ADX>15) on daily candles. Same paper-only
  / daily-force rules. `PAPER_PROMOTE_EMA_9_21` wins if both are true.
  See `docs/artifacts/strategy-search/expanded-harder-gates-report.md`.
  **Do not claim the daily Miles edge on a 1h runtime** — that is a
  different strategy, and the same EMA lost money on the 1h window.
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
- Leave `PAPER_PROMOTE_SEARCHED_STRATEGIES=false` unless a
  `traderstack-strategy-search` report shows a gate-clearing winner (WF **total**
  return > 0 after fees, holdout excess > 0, min trades) and pin
  `PAPER_PROMOTE_SEARCHED_STRATEGY_ID` to that exact id. The flag does not relax
  `RiskEngine`; flipping it on with no winner or the wrong id fails closed.
- `ROBINHOOD_CHAIN_*` values (RPC URL, chain id, router/token allowlists) must come
  from Robinhood's own official chain docs, never guessed — see the warnings
  already in `.env.example` and `docs/DATA-SOURCES.md`.
- **`VENUE_FEED=kraken_rest`**: paper-only public Spot REST ticker
  (`GET https://api.kraken.com/0/public/Ticker`). Use it when Kraken WS v2
  hangs, is firewalled, or `KrakenFeedExhausted` keeps ending the cycle. It
  is rejected at startup unless `TRADING_MODE=paper`. Poll interval is
  `KRAKEN_REST_POLL_SECONDS` (default 1s) — keep it under
  `MAX_MARKET_DATA_AGE_SECONDS`. No order-book snapshots on this feed.
  See "Kraken REST ticker fallback" below.
- **`CRUCIX_*`**: optional local intel. The adapter is registered only when
  `CRUCIX_ENABLED=true` or `CRUCIX_BASE_URL` / `CRUCIX_API_KEY` is set. A
  copied blank `.env.example` does **not** register it. High-tier alerts
  become `NewsFeatures.adverse_event` (an extra rejection source only;
  never a way to size up or authorise). Default URL when registered
  without an override is `http://host.docker.internal:8787`. When Crucix
  **is** opted in, a provider timeout, HTTP error, or unexpected payload
  fails closed: new risk is rejected with
  `intelligence_provider_unavailable`. Existing positions and
  deterministic exits are untouched. Optional news providers
  (CryptoPanic, Perplexity) still isolate failures. The same
  `build_intelligence` / `PaperRuntime` path is used for paper, shadow,
  and live — live does **not** ignore Crucix. This is safety plumbing,
  not a trading edge; it does not flip `PAPER_PROMOTE_*`.

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

Every run writes a machine-readable JSON report to `--report`, defaulting to
`<workdir>/report.json`, so a pass/fail artefact is always archived. The report
includes `schema_version`, `passed`, `failures[]`, `full_24h_window_executed`
(true only when a ≥86400s request actually ran for ~24 hours), health, the risk
audit-chain verification, and a Prometheus snapshot. **A short CI soak is not
the 24-hour window.** `full_24h_window_executed` stays `false` unless you
really ran it.

```bash
# CI / local smoke (same wiring, 8 cycles). Also: make soak-ci
.venv/bin/traderstack-soak --preset ci --workdir var/soak-ci

# 24-hour window, one cycle every 5 seconds. Also: make soak-24h
.venv/bin/traderstack-soak --preset full --cycle-seconds 5 --workdir var/soak
```

Equivalent long-form commands:

```bash
.venv/bin/traderstack-soak \
  --seconds 86400 \
  --cycle-seconds 5 \
  --workdir var/soak \
  --report var/soak/report.json
```

Useful variations:

```bash
# A longer smoke run before committing to 24 hours
.venv/bin/traderstack-soak --cycles 200 --workdir var/soak

# The shipped scenarios: CI, clean baseline, provider outages, kill-switch drill
.venv/bin/traderstack-soak --scenario ops/soak/scenarios/ci.json
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

Keep `<workdir>/report.json` alongside the audit trail. For a 24-hour run that
is `var/soak/report.json`; confirm `full_24h_window_executed: true` before
treating it as the Epic 10 exit-criterion artefact. The CI job
(`traderstack-soak --preset ci`) archives a short report so the runner and
report schema stay green — it does **not** satisfy the 24-hour gate.
`traderstack-paper-report` (below) turns the same files into the performance
comparison.

## Zero-trade diagnosis (opportunity funnel)

A 24-hour paper window that ends with zero fills is not, by itself, evidence of
anything: it can mean no valid ticks, a reference provider down, stale candles,
an ensemble that never agreed, a pre-trade bar that never cleared, a risk
rejection, a meta-agent veto, a planner refusal, or fills simply not being
enabled. Loosening a threshold before knowing which of those it was is how a
safety rejection gets mistaken for a strategy failure. The opportunity funnel
(`src/traderstack/opportunity_funnel.py`, #131) answers that question first.

Every cycle is reduced to the furthest **stage** it reached and, if it did not
fill, the single nearest **gate** that stopped it plus the literal reason
strings that gate emitted (the same strings as "What each rejection reason
means" below and the execution-status table):

```text
cycle -> valid_market_data -> signal_candidate -> pretrade_eligible
      -> risk_allowed -> meta_agent_retained -> planner_accepted -> filled
gates: market_data | candle_history | universe | intelligence | signal
       | pretrade | risk | meta_agent | planner | fill
```

Each gate rolls up into one of three headline categories, which is the first
thing to read in a zero-fill report:

| Category | Gates | Meaning |
|---|---|---|
| `no_opportunity` | `market_data`, `candle_history`, `universe`, `signal` | Nothing tradeable was ever formed — bad/missing data, stale candles, no strategy consensus, or a symbol outside the promote universe. **Not** a safety rejection; also not a reason to relax a threshold. |
| `opportunity_rejected` | `intelligence`, `pretrade`, `risk`, `meta_agent`, `planner` | A candidate existed and a control withheld it. Read that gate's reason counts (`reasons_by_gate`) before touching anything. |
| `fill_unavailable` | `fill` | Risk approved an order and nothing could book it: `PAPER_SIMULATE_FILLS=false` with no `--submit` (`execution_not_attempted`), kill switch / reconciliation block / torn ledger (`paper_fill_withheld`), diagnostic mode (`diagnostic_withheld`), venue uncertainty, or a venue order still pending (`venue_fill_pending`). |

The report also carries per-symbol and per-strategy stage counts (strategy is
only known once a `TradeProposal` exists, so those start at
`pretrade_eligible`), bounded reason maps (at most 64 distinct keys per gate,
overflow under `(other)`), first/last observation timestamps, tick-age and
candle-age statistics, the last/minimum candle count, whether paper fills and
venue submission were enabled, and a one-line `diagnosis.verdict` naming the
dominant gate and its top reason.

Where to find it:

- **`traderstack-paper`** rewrites a JSON snapshot to `--funnel-path`
  (default `var/ops/opportunity_funnel.json`) after every cycle. A write
  failure is logged and never fails the cycle.
- **`traderstack-soak`** persists it as `opportunity_funnel` in `report.json`
  and renders it in the text report, with venue fills joined from the ledger
  at the end of the window.
- **`traderstack-opportunity-funnel`** rebuilds it offline from any run's
  `audit/runtime.jsonl` (+ `state/execution_ledger.json` when present):

  ```bash
  .venv/bin/traderstack-opportunity-funnel \
    --audit-path var/audit/runtime.jsonl \
    --ledger-path var/state/execution_ledger.json \
    --output var/ops/opportunity_funnel.json
  ```

  Wall-clock tick age is not in the audit trail, so the offline rebuild leaves
  `tick_age_seconds` empty; `stale_primary_tick` counts still appear under
  `market_data`.

**Diagnostic-only mode.** `OPPORTUNITY_DIAGNOSTIC_MODE=true` runs the full
cycle — kill switch, market-data validation, pre-trade gate, risk engine,
meta-agent, planner — exactly as normal and audits every decision, but never
books a paper fill and never submits to a venue: `submission_enabled` and
`paper_fill_enabled` are both forced false, and an approved order is stamped
`execution_status=diagnostic_withheld`. Each cycle also logs an
`opportunity_diagnosis` line with its nearest blocking gate. The flag is not
a risk-limit input: it is absent from `risk_limits` / `policy_version`, it
cannot lift a reconciliation or durable-state block, and the kill switch
remains the first explanation when engaged (`tests/security/
test_diagnostic_mode_cannot_relax_controls.py`). Use it to characterise a
zero-trade window without creating positions; set it back to `false` to
resume paper PnL.

Read the funnel **before** changing any `PRETRADE_*` / `PAPER_PRETRADE_*`
threshold or promoting a new strategy: a window whose dominant gate is
`signal` (`no_strategy_consensus`) is a research result, not a tuning
problem, and a window whose dominant gate is `risk` or `meta_agent` is the
system doing its job.

## Paper performance versus baselines

## Miles-inspired EMA / ADX / GARCH search

Public methods only (not claimed YouTube PnL): EMA 9/21 and 12/26 direction,
optional ADX chop gate, GARCH(1,1) walk-forward vol as a **size** overlay
(`target_vol / forecast_vol`, clip [0.25, 2.0]). GARCH never chooses a side.

```bash
# Live Kraken Spot OHLC — daily (~2y) and 1h (~30d). 720 committed bars each.
.venv/bin/traderstack-miles-search --live-kraken

# Offline fixtures
.venv/bin/traderstack-miles-search \
  --candles var/research/btc_1d.json \
  --output-md docs/artifacts/strategy-search/miles-inspired-report.md
```

Kraken's public OHLC endpoint cannot retrieve bars older than the most recent
720, regardless of `since`. Daily is the long window; 1h is the recent window.

Promotion (research only): walk-forward **mean total return > 0 after fees**
**and** holdout **mean excess return > 0 after fees**, plus min trades.
`PAPER_GARCH_SIZE` stays **false**. No GARCH-sized candidate cleared the
bar (vol-targeted size increased turnover and fee drag). When on,
`RiskEngine` may only *reduce* approved notional.

`PAPER_PROMOTE_EMA_9_21` (default **false**) is the documented paper-only
switch to register **only** `ema_9_21` as a pre-trade voter (`extra_voters`,
`suppress_defaults=True`, `min_agreeing=1`) **on the same daily series the
search promoted**. It does not enable live trading. Live/shadow ignore the
flag. It does not flip `PAPER_GARCH_SIZE`. If both this and
`PAPER_PROMOTE_SEARCHED_STRATEGIES` are true, `ema_9_21` wins and
`traderstack-check-config` warns.

`PAPER_PROMOTE_EMA_9_21_ADX15` (default **false**) is the paper-only
pin for the expanded harder-gates combined-passer top-1
(`ema_9_21` + ADX>15). Same daily-candle force, same paper-only
rule, same "does not enable live", and the same
`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` ceiling. If both EMA
promote flags are true, `PAPER_PROMOTE_EMA_9_21` wins.

**Alignment (do not skip this).** `ema_9_21` cleared the daily Kraken Spot
OHLC window in #93. Paper historically fetched `PRETRADE_CANDLE_INTERVAL=1h`.
Running that daily-validated EMA on 1h bars is **not** the same strategy
(and 1h lost money). When the flag is on (`TRADING_MODE=paper` only):

- `PaperRuntime.candle_interval` is forced to `1d` (Kraken `interval=1440`)
- feature bars and the pre-trade backtest use that same daily series
- the gate rejects `candle_interval_mismatch` if any bar is not `1d`
- `PRETRADE_MAX_CANDLE_AGE_SECONDS` is raised to at least 48h so last
  committed daily bars are not stale after mid-morning UTC
- `PRETRADE_CANDLE_INTERVAL=1h` is ignored for ingestion and the gate
- the pre-trade drawdown ceiling is `PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`
  (default **0.30**), not `PRETRADE_MAX_DRAWDOWN_PCT=0.15`. That ceiling
  is applied to **research walk-forward maxDD** (train=180 / test=60 /
  step=60, warmup=train — the #95–#100 definition), not to
  full-history backtest DD. Daily `ema_9_21` realized WF maxDD ~23.35%
  on Kraken BTC+ETH (ETH per-asset ~28.77%). After #98 the 0.30 bar
  was still compared to the full-history book (ETH ~43% on 400 daily
  bars), so ETH rejected every cycle with
  `backtest_drawdown_above_maximum` while BTC's ~20% cleared. Do **not**
  raise the ceiling past 0.30 to cover that longer series;
  `traderstack-check-config` warns. Live/shadow keep 0.15 on the
  full-history book. Setting the paper ceiling to 0 fails Settings
  load. Do not set 1.0 to disable the gate
- candle lookback is forced to **720** (Kraken public OHLC cap / the
  #95–#100 window). `PRETRADE_CANDLE_COUNT=400` is the 1h MA lookback
  and would drop the older research folds, including ETH's 28.77% WF
  maxDD fold. Live/shadow keep 400
- the promote-path **trading universe** is `PAPER_PROMOTE_UNIVERSE`
  (default **BTC/USD,ETH/USD**), not the full `MVP_ASSETS` list. The
  #100 honesty pack showed SOL WF maxDD ~50% vs the 0.30 paper
  ceiling; leaving SOL in the cycle would reject it forever
  (`backtest_drawdown_above_maximum`) or trade a name outside the
  BTC+ETH research envelope. Extra names in `PAPER_PROMOTE_UNIVERSE`
  cannot expand past BTC/USD + ETH/USD. A leftover SOL position can
  still exit; new SOL risk is skipped with `promote_universe_excluded`.
  Live/shadow ignore the pins and keep full `MVP_ASSETS`. This is
  universe alignment, not a claim of edge
- `EXIT_TIME_STOP_BARS` is still a *bar* count: 24 × 1d = 24 days. Set
  `EXIT_TIME_STOP_BARS=1` if you want a one-day time-stop on daily bars.

`traderstack-check-config` prints the forced interval, the forced 720-bar
lookback, the promote-path drawdown ceiling (and that it applies to
research WF maxDD, not full-history backtest DD), and the promote
universe. It warns if that ceiling is tighter than the documented
~23.35% research envelope **or** raised past 0.30 to cover the longer
full-history series. Do not narrate a
daily holdout as evidence for an hourly paper run.

## Daily robustness (balanced-holdout bar)

`#93` promoted `ema_9_21` on a three-asset daily mean; `#95` required
BTC **and** ETH walk-forward total > 0 but still allowed an ETH holdout
tail to carry the mean. The default `traderstack-daily-robustness` bar
additionally requires **BTC holdout excess > 0 and ETH holdout excess
> 0** (plus mean holdout excess > 0 and min trades). SOL is reported
and is not a promotion gate. Yahoo never enters the promotion average.

The catalog is pre-registered before the window is scored (slower EMAs,
dual-mom lookback grid, dip z grid, SMA200 risk-off, two GARCH size
overlays). `--catalog legacy` re-scores the frozen #95 K=8 list.
`--no-balanced-holdout` restores the #95 mean-holdout gate only.

```bash
.venv/bin/traderstack-daily-robustness --live-kraken
# skip the Yahoo Finance (non-Kraken) A/B
.venv/bin/traderstack-daily-robustness --live-kraken --no-yahoo
# frozen #95 catalog, still using the balanced-holdout bar
.venv/bin/traderstack-daily-robustness --live-kraken --catalog legacy
```

Kraken public OHLC cannot retrieve more than 720 committed daily bars
(~2 years) regardless of `since`. Yahoo `BTC-USD` / `ETH-USD` daily is
labeled non-Kraken and cannot promote. Leave `PAPER_PROMOTE_*` false
unless `docs/artifacts/strategy-search/balanced-holdout-report.md` names
an id that still clears this bar. Do not flip
`PAPER_PROMOTE_EMA_9_21` or `PAPER_GARCH_SIZE` from their defaults
because a report exists. Finding no promotee is a successful research
outcome.

## Harder honesty gates (magnitude / multi-window / fee stress)

`#96` still lets a tiny BTC holdout and a huge ETH holdout both count
as a PASS. `traderstack-harder-gates` pre-registers three additional
bars **before** the window is scored:

- **A magnitude:** both holdout excesses > 0 **and**
  `min(BTC,ETH)/max(BTC,ETH) ≥ 0.25`.
- **B multi-window:** most recent 720 Kraken daily bars split into
  three contiguous 240-bar slices. Each slice uses the #96 walk-forward
  (train=180, test=60, step=60) with no in-window holdout. BTC **and**
  ETH WF total must be > 0 in at least 2 of 3 windows.
- **C fee stress:** re-score at 2× fee and slippage (defaults 20+10
  bps). Must still clear the #96 balanced signs.

Yahoo / non-Kraken prints stay A/B only and are never averaged in.
The default catalog is the frozen expanded post-#97 grid (`--catalog
expanded`); `#96` balanced and `#95` legacy remain available. Ranking
key (frozen before scoring): **mean holdout excess among
combined-passers**. Combined = #96 **and** A **and** B **and** C. A
non-passer is never promoted; walk-forward rank cannot block a passer.
If a combined-passer top-1 exists, the report names
`PAPER_PROMOTE_<ID>` (default **false**) — this command does not flip
it, nor `PAPER_PROMOTE_EMA_9_21`. The committed expanded-catalog window
named `PAPER_PROMOTE_EMA_9_21_ADX15` for `ema_9_21_adx15`; leave that
flag **false** unless you intend the paper-only daily voter. An empty
promotee is also a successful research outcome.

```bash
.venv/bin/traderstack-harder-gates --live-kraken
.venv/bin/traderstack-harder-gates --live-kraken --no-yahoo
```

See `docs/artifacts/strategy-search/expanded-harder-gates-report.md`
(this expansion) and
`docs/artifacts/strategy-search/magnitude-multiwindow-report.md` (#97).

## Honesty pack (`ema_9_21_adx15`)

`#99` documented `ema_9_21_adx15` as the expanded-catalog
combined-passer top-1 and pinned
`PAPER_PROMOTE_EMA_9_21_ADX15` (default **false**).
`traderstack-honesty-pack` reprints **that id only**:

- Kraken combined A/B/C + ranking (still top-1?)
- Yahoo Finance daily A/B for this candidate (`period1`/`period2`;
  labeled non-Kraken; cannot promote)
- WF maxDD on BTC/ETH/SOL vs the paper DD ceiling 0.30
- Gate B multi-window table for this id

Empty or negative Yahoo is a successful research outcome. This
command never flips the pin and never enables live.

```bash
.venv/bin/traderstack-honesty-pack --live-kraken
.venv/bin/traderstack-honesty-pack --live-kraken --no-yahoo
```

See `docs/artifacts/strategy-search/ema-9-21-adx15-honesty.md`.

## Second print (`ema_9_21_adx15`)

The #100 honesty pack still had only one Kraken 720-bar window.
`traderstack-second-print` pre-registers the slice rules **before**
scoring:

- Kraken public OHLC cannot retrieve a second 720-bar era (`since`
  pages forward only). That path is documented as UNAVAILABLE.
- Kraken-compatible path that exists: **holdout-blind prefix** (drop
  the last 20% holdout tail). Same venue; overlapping walk-forward;
  not an independent era. Gate B still needs 3×240 bars and fails
  closed if the prefix is short.
- Binance Spot daily BTCUSDT+ETHUSDT: 720 committed bars ending
  strictly before the primary Kraken first bar. This environment's
  `api.binance.com` is HTTP 451; `api.binance.us` is the reachable
  public Spot host and is labeled Binance.US, not Binance.com.
  Report-only. **Cannot enter the promotion average** (a multi-venue
  bar is not pre-registered).

Same strategy definition and #96 + A + B + C gates. Fees are the
paper-research defaults (10+5; gate C 20+10). An honest FAIL is
success. This command never flips
`PAPER_PROMOTE_EMA_9_21_ADX15`.

```bash
.venv/bin/traderstack-second-print --live
.venv/bin/traderstack-second-print --live --no-binance
```

See `docs/artifacts/strategy-search/ema-9-21-adx15-second-print.md`.

## Dual-print daily search

`#102` showed that `ema_9_21_adx15` (and the other three #99
combined-passers) fail the Binance.US older-720. That print was
report-only because a multi-venue bar had **not** been pre-registered.
`traderstack-dual-print-search` freezes the dual-print bar **before**
scoring:

- Catalog is a frozen superset of the #99 expanded grid (more EMA/ADX,
  SMA risk-off, dual-mom, dip+vol, candle-only vol-regime wrappers).
  K is committed before the live pull. Liquidation / funding / OI
  voters stay skipped unless an aligned series is supplied.
- Combined on each print is still #96 + A + B + C.
- Dual-print passer = combined PASS on the Kraken primary 720 **and**
  combined PASS on the #102 Binance.US older-720 (720 committed daily
  bars ending before the primary Kraken first bar).
- Ranking key: Kraken mean holdout excess among dual-print passers.
  Binance holdout is a gate; venues are not averaged.
- A Kraken-only combined-passer cannot promote.
- Empty dual-print set is success. This command never flips
  `PAPER_PROMOTE_*` and does not add a new pin unless a committed
  report names a passer (default false if added).

```bash
.venv/bin/traderstack-dual-print-search --live
.venv/bin/traderstack-dual-print-search --live --no-binance
```

See `docs/artifacts/strategy-search/dual-print-search.md`.

## Liquidation / regime-conditioned search

#104's dual-print EMA catalog had **zero** passers. Live paper cycles
already attach Binance USDT-M liquidation z and optional bookTicker
cross-venue mid as `ResearchEdgeFeatures` (research context only;
`RiskEngine` does not read them). Public historical liquidation REST
is typically unusable (`allForceOrders` recent-only / HTTP 451; Vision
`um/liquidationSnapshot` removed). `traderstack-liq-regime-search`
pre-registers a small catalog **conditioned on** those families when a
series exists, plus candle-only vol-regime wrappers:

- Dual-print only if a usable historical liquidation series exists on
  BTC and ETH **and** a second venue candle print is supplied.
- Otherwise the run is labeled **single-print** (Kraken public Spot
  daily 720) and **cannot promote**.
- Funding / OI public history may score when aligned; they are skipped,
  not zero-filled, when REST cannot build a series.
- Crucix already maps high-tier alerts to `adverse_event` and the
  pipeline already rejects with `adverse_news_event`. That path is
  unchanged. This command does not enable Crucix or live.

```bash
.venv/bin/traderstack-liq-regime-search --live-kraken
.venv/bin/traderstack-liq-regime-search \
  --candles tests/fixtures/strategy_search/btc_1h.json \
  --candles tests/fixtures/strategy_search/eth_1h.json
```

See `docs/artifacts/strategy-search/liq-regime-search.md`.

Daily EMA dual-print (#104), historical liquidation (#105), and
Polymarket PIT tape (#106) were all empty. `traderstack-intraday-dual-print`
is a **different family**: fee-aware #96+A+B+C on Kraken public Spot
**4h** (default; `1h` is the alternate) BTC+ETH, plus the #102-style
Binance.US older-720 of the same interval. The catalog is frozen
non-EMA (MA / momentum / mean-reversion / vol-regime). Funding/OI
variants instantiate only when an aligned series is fetched.

```bash
.venv/bin/traderstack-intraday-dual-print --live
.venv/bin/traderstack-intraday-dual-print --live --interval 1h
.venv/bin/traderstack-intraday-dual-print --live --no-binance
```

See `docs/artifacts/strategy-search/intraday-dual-print.md`. An empty
dual-print set is success. Do not add a new `PAPER_PROMOTE_*` pin
unless a committed report names a passer (default false if added).

## Funding / carry search

#104 daily EMA dual-print, #105 historical liquidation, #106
Polymarket PIT tape, and #108 4h non-EMA dual-print were all empty.
`traderstack-funding-carry` is a **different family**: fee-aware
funding-z thresholds, funding-agree spot overlays, and a modeled
hedged cash-and-carry on BTC+ETH.

- Dual-print only if two independent **funding** venues (e.g.
  Hyperliquid and HTX) each cover BTC and ETH. A second candle
  venue without a second funding tape is not dual-print. Same-venue
  prefix/suffix is not independent. Binance (HTTP 451) and Bybit
  (HTTP 403) are probed and recorded as skips when geo-blocked.
  BitMEX is a **sunset** venue (official closure 23 September 2026
  04:00 UTC; risk limits from 26 August 2026 04:00 UTC) and is not
  selected for dual-print or paper hedge.
- Otherwise the run is labeled **single-print** and **cannot promote**.
- OKX public funding-rate-history is typically ~90d of 8h prints.
  Hyperliquid `fundingHistory` is hourly and typically reachable
  (daily runs request ~800d so a Kraken 720-bar daily window can be
  covered on that one tape). HTX `swap_historical_funding_rate` is a
  public 8h `funding_rate` tape from 2020-10-21 (BTC+ETH), long
  enough for ≥720 UTC daily sums. BitMEX `GET /api/v1/funding` remains
  fetchable as dead-end documentation only. Hard gates (#96+A+B+C)
  need 720 aligned **daily** bars on **each** participating venue and
  stay UNAVAILABLE on a short overlap — they are not faked.
  `--interval 1d` resamples funding to UTC daily sums (empty days
  omitted, never zero-filled).
- Hedged carry PnL is received |funding| minus two-leg fees. Perp-spot
  basis is skipped unless a PIT mark−index / perp-mid−spot-mid series
  is supplied on **both** dual-print venues for the scored window.
  `--live` probes Hyperliquid, HTX, and BitMEX (sunset notes) and
  records UNAVAILABLE when the pair is incomplete (`fundingHistory.premium`
  and BitMEX `.XBTUSDPI` are not basis). A paper hedge+funding soak
  path exists (`PAPER_PERP_HEDGE`, default false): the cycle fetches
  an explicit Hyperliquid `midPx` (HTX bid/ask mid fallback; BitMEX
  not required) and applies same-venue public funding settlements.
  Snapshot mids are not historical PIT basis and are not scored as one.
  `PAPER_CARRY_PATH_READY` is true for that soak; `can_promote` stays
  false while PIT basis is UNAVAILABLE. A Settings pin requires
  dual-print + hard gates + PIT basis + a paper-executable path.
- This command never flips `PAPER_PROMOTE_*` and does not add a new
  pin unless those four are all true (default false if a pin is ever
  added). Empty / cannot-promote is success.

```bash
.venv/bin/traderstack-funding-carry --live
.venv/bin/traderstack-funding-carry --live --interval 1d
.venv/bin/traderstack-funding-carry \
  --candles tests/fixtures/strategy_search/btc_1h.json \
  --candles tests/fixtures/strategy_search/eth_1h.json \
  --interval 1h
```

See `docs/artifacts/strategy-search/funding-carry.md` (4h dual-print),
`docs/artifacts/strategy-search/funding-carry-daily.md` (daily
resample / hard-gate print),
`docs/artifacts/strategy-search/funding-carry-basis.md` (PIT basis
probe: UNAVAILABLE),
`docs/artifacts/strategy-search/pit-basis-archives.md` (public
archive probe: still UNAVAILABLE), and the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## BTC−ETH relative-value residual

#115 left PIT basis archives **UNAVAILABLE**, so carry cannot
promote. `traderstack-relative-value` is the next **non-carry**
family: fade/follow daily BTC minus ETH excess return at
**pre-registered** |z| thresholds. This is not another EMA
dual-print (#104 / #108).

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Residual is built from venue-local BTC and ETH closes. A day
  missing either close is skipped, not zero-filled.
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-relative-value --live
.venv/bin/traderstack-relative-value --live --no-binance
```

See `docs/artifacts/strategy-search/btc-eth-relative-value.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## BTC+ETH+SOL cross-sectional momentum

#116 left the BTC−ETH residual dual-print empty (every Kraken RV
holdout negative). `traderstack-xs-momentum` is the next
**non-carry / non-EMA / non-residual** family: long the top-1
(and optionally short the bottom-1) among {BTC, ETH, SOL} by a
**pre-registered** trailing N-day return. Not another residual
retune.

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): BTC and ETH WF/holdout
  signs as before; SOL is reported and is **not** a gate.
  Equal-weight portfolio metrics are not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- A ranking day needs all three venue-local closes. A missing
  asset day is skipped, not ranked on a two-asset subset.
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD` +
  `SOL/USD`).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-xs-momentum --live
.venv/bin/traderstack-xs-momentum --live --no-binance
```

See `docs/artifacts/strategy-search/cross-sectional-momentum.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## Donchian / channel breakout

#117 left the BTC+ETH+SOL cross-sectional dual-print empty
(informational `xs_mom_lo_vol_63` was ETH-carried / #96 FAIL).
`traderstack-donchian-breakout` is the next **non-carry / non-EMA /
non-residual / non-XS** family: long-only or long/short on a
**pre-registered** prior N-day Donchian channel. Not another
lookback retune.

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): BTC and ETH WF/holdout
  signs as before; SOL is reported and is **not** a gate.
  Equal-weight portfolio metrics are not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Decision at bar t uses the prior channel (bars `[t-N, t)`). Fill
  at t+1 open. Exit is `opposite_band_same_n`.
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`; SOL
  optional).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-donchian-breakout --live
.venv/bin/traderstack-donchian-breakout --live --no-binance
```

See `docs/artifacts/strategy-search/donchian-breakout.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## Time-series momentum

#118 left the Donchian / channel-breakout dual-print empty
(informational positive Kraken mean HO still failed #96 on BTC
walk-forward). `traderstack-tsmom` is the next **non-carry /
non-EMA / non-residual / non-XS / non-Donchian** family: long-only
or long/short on each asset's **own** pre-registered trailing
N-day close-to-close return. Not a cross-section rank and not a
channel.

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): BTC and ETH WF/holdout
  signs as before; SOL is reported and is **not** a gate.
  Equal-weight portfolio metrics are not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Decision at bar t uses closes through t (`close[t] / close[t−N]
  − 1`). Fill at t+1 open. Vol-scaled sign variants omitted
  (`sign(return/vol)` equals `sign(return)` when vol > 0).
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`; SOL
  optional).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-tsmom --live
.venv/bin/traderstack-tsmom --live --no-binance
```

See `docs/artifacts/strategy-search/tsmom.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## Bollinger band-fade / mean-reversion

#119 left the time-series momentum dual-print empty
(informational ETH-carried #96 FAIL and BTC walk-forward fails).
`traderstack-bollinger-fade` is the next **non-carry / non-EMA /
non-residual / non-XS / non-Donchian / non-TSMOM** family:
mean-reversion against own-asset Bollinger bands. Distinct from
existing `mean_reversion_*` catalog ids (#93 / #108 used different
bars).

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): BTC and ETH WF/holdout
  signs as before; SOL is reported and is **not** a gate.
  Equal-weight portfolio metrics are not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Bands from SMA(period) ± k × sample stdev through t. Fade exits
  `flat_when_inside_bands` (not exit-at-mid). Fill at t+1 open.
  Squeeze-breakout CONTRAST is long only on an upside expansion
  from the frozen p20 of the prior 120 bandwidths.
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`; SOL
  optional).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-bollinger-fade --live
.venv/bin/traderstack-bollinger-fade --live --no-binance
```

See `docs/artifacts/strategy-search/bollinger-fade.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## Calendar seasonality

#120 left the Bollinger band-fade dual-print empty
(informational `bb_squeeze_break_40` cleared Kraken #96+A+B
but failed gate C). `traderstack-calendar-seasonality` is the
next **non-carry / non-EMA / non-residual / non-XS /
non-Donchian / non-TSMOM / non-Bollinger** family: positions
from the **UTC civil calendar** of bar t only. Not a
price-indicator retune.

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): BTC and ETH WF/holdout
  signs as before; SOL is reported and is **not** a gate.
  Equal-weight portfolio metrics are not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Timezone is UTC. Decision uses the UTC date of bar t. Fill at
  t+1 open. Frozen sets: Mon / Fri / Mon+Fri; skip-weekend
  (long Mon–Fri); Q4 / Jan / Nov+Dec; turn-of-month last 3 /
  first 3 UTC calendar days (`calendar.monthrange`; no look-ahead).
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`; SOL
  optional).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-calendar-seasonality --live
.venv/bin/traderstack-calendar-seasonality --live --no-binance
```

See `docs/artifacts/strategy-search/calendar-seasonality.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## BTC→ETH lead-lag

#121 left the calendar seasonality dual-print empty (every
Kraken mean HO negative). `traderstack-lead-lag` is the next
**non-carry / non-EMA / non-residual / non-XS / non-Donchian /
non-TSMOM / non-Bollinger / non-calendar** family: ETH
follows or fades **lagged BTC** L-day return. Not same-bar
residual z-score on `r_BTC − r_ETH` (#116).

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): every name produces
  both BTC and ETH books. ETH-traded names run the lead-lag rule
  on ETH and keep BTC **flat**; BTC-traded mirror names run the
  lead-lag rule on BTC and keep ETH **flat**. Combined still
  requires **both** legs. Equal-weight portfolio metrics are
  not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Decision uses lead closes through t (`lead_close[t] /
  lead_close[t−L] − 1`; L ≥ 1). When trading ETH, same-bar ETH
  does not enter the gate. Fill at t+1 open of the traded asset.
  Unpaired BTC/ETH days are skipped, never zero-filled.
- Frozen L: follow-lo {1,2,3,5}; follow-ls / fade-lo {1,2,3};
  BTC-follows-ETH mirror lo {1,2}.
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-lead-lag --live
.venv/bin/traderstack-lead-lag --live --no-binance
```

See `docs/artifacts/strategy-search/lead-lag.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

## Volume-confirmed breakout

#122 left the BTC→ETH lead-lag dual-print empty (informational
`leadlag_eth_follow_lo_5` was ETH-carried / #96 FAIL).
`traderstack-volume-breakout` is the next **non-carry / non-EMA /
non-residual / non-XS / non-Donchian / non-TSMOM / non-Bollinger /
non-calendar / non-lead-lag** family: price breakout **and** a
volume gate. Not a Donchian N retune (#118).

- Same #96+A+B+C combined bar on Kraken public Spot **daily** 720
  **and** the #102 Binance.US older-720 (non-overlapping).
- Multi-asset rule (frozen before scoring): BTC and ETH signs as
  #96+A+B+C; SOL reported, not a gate. Equal-weight portfolio
  metrics are not used.
- Ranking key (frozen): Kraken BTC+ETH mean holdout excess among
  dual-print passers. Venues are not averaged. The informational
  control `ma_cross_10_30` cannot enter the passer set.
- Prior channel uses bars `[t-N, t)` (no look-ahead into t's
  high). Volume SMA through t−1 (V=20). Missing volume skips
  that bar (never invented). Quote volume is not a substitute.
  A venue without usable base volume fails closed for volume
  names. Fill at t+1 open.
- Frozen ids: `volbrk_lo_{20x1_5,55x1_5,20x2}`,
  `volbrk_ls_{20x1_5,55x1_5}`, `volsurge_lo_{20x2,20x2_5}`.
- Paper-executable on Kraken spot (`BTC/USD` + `ETH/USD`; SOL
  optional).
- This command never flips `PAPER_PROMOTE_*` and does not add a
  new pin unless a committed report names a dual-print passer
  (default false if added). Empty dual-print set is success.

```bash
.venv/bin/traderstack-volume-breakout --live
.venv/bin/traderstack-volume-breakout --live --no-binance
```

See `docs/artifacts/strategy-search/volume-breakout.md` and
the 2026-09-12 status memo
`docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

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
the attribution table (including **By exit reason** — `exit_stop_loss`,
`exit_take_profit`, `exit_time_stop`, … versus `discretionary`). `--json` emits
the same thing machine-readably.

Two things it will not do, by design:

- It never invents fees that the ledger does not record. Venue-reported fees and
  `PAPER_FEE_BPS`-modelled fees (applied when the venue reports none, default 10 bps,
  matching `PRETRADE_FEE_BPS`) are read from the execution ledger and reported as
  fee drag, labelled `venue` / `modelled`. `--fee-bps` is only a *fallback* for
  fills that still carry no ledger fee — and the report states which it used.
- It never assumes an unfilled order traded. Paper-simulated fills
  (`execution_status=paper_filled`, ledger `FILLED`, `fee_source=modelled`)
  are real ledger rows and are included. Orders that were only submitted
  to Hummingbot and never filled (or never paper-simulated) are excluded,
  so a report showing "no fills" means neither `PAPER_SIMULATE_FILLS` nor
  venue reconciliation booked one — check the ledger states, not the report.

Candles come from a JSON file (`--candles`, produced by `traderstack-download-candles`)
or, with `--candle-store`, from the Postgres candle store populated by
`--persistent-events`.

## Multi-year candle archives (#133)

Every catalog since #104 was scored on Kraken's public Spot OHLC cap —
720 bars, about two years daily — plus one older Binance.US 720. That is
one regime. `traderstack-download-candles --venue` reaches further back,
into the same JSON candle format every `--candles` consumer already reads
(`symbol`, `interval`, `opened_at`, `open`, `high`, `low`, `close`,
`volume`; one object per bar, ascending).

| `--venue` | Source | Reach | Network |
|---|---|---|---|
| `kraken` (default) | `api.kraken.com` public OHLC | most recent 720 bars | yes |
| `coinbase` | `api.exchange.coinbase.com` public candles | BTC-USD from 2015, ETH-USD from 2016 | yes |
| `binance_vision` | `data.binance.vision` monthly spot kline zips | spot from 2017-08 | yes |
| `kraken_archive` | a manually downloaded Kraken OHLCVT drop | full venue history | **no** |

```bash
# Coinbase daily back to 2016 (300 bars per request, paced inside the public limit)
.venv/bin/traderstack-download-candles BTC/USD \
  --venue coinbase --resolution 1d --start 2016-01-01 \
  --out var/research/btc_1d_coinbase.json

# Binance Vision monthly zips, each sha256-verified against its .CHECKSUM
.venv/bin/traderstack-download-candles BTC/USD \
  --venue binance_vision --resolution 1d --start 2017-08-01 \
  --out var/research/btc_1d_binance_vision.json

# A local Kraken OHLCVT drop, cross-checked against the Coinbase pull
.venv/bin/traderstack-download-candles BTC/USD \
  --venue kraken_archive --resolution 1d \
  --archive-path var/research/kraken_ohlcvt/ \
  --out var/research/btc_1d_kraken_archive.json \
  --cross-check var/research/btc_1d_coinbase.json
```

**Report header.** Every archive venue writes a sidecar JSON next to
`--out` (default `<out>.report.json`, override with `--report`) recording
`venue`, `status`, `reason`, `bars`, `first`, `last`, `gaps`,
`missing_bars` and `fetched_at`. Read it before using a series: it is the
only place the gaps are enumerated.

**Status vocabulary.** Same `ok` / `skipped` as the funding adapters. A
skip carries **no candles at all** — an unreachable host, an HTTP 429, a
missing month, a checksum mismatch or an unparsable file never produces a
partial series. When the status is `skipped`, no candle file is written
and the report explains why.

**Gaps are never filled.** A bar the venue did not publish stays absent
and is counted in `gaps`. Nothing here interpolates, forward-fills or
zero-fills, and every timestamp must land exactly on the UTC interval
grid — a misaligned row is a parse failure, not something to round.

**Rate limiting (Coinbase).** The documented public limit is **10
requests per second per IP, bursting to 15**. This client paces itself at
3 req/s by default (`--requests-per-second`), and an **HTTP 429 is a skip,
not a retry**: the walk stops immediately and the series is reported
`skipped` with the request count. It never backs off and retries, so a
rate-limited pull can never turn into a retry storm against a public
endpoint. Coinbase publishes no native 4h bucket — `--resolution 4h` is
rolled up from complete 1h buckets, and a 4h bucket missing any of its
four hours is dropped rather than completed.

**Checksum verification (Binance Vision) fails closed.** For each month
the zip is fetched, then its published `.CHECKSUM`, and the zip's sha256
must equal the published digest before a single row is parsed. A
mismatch, an unparsable digest, or data present with **no** published
`.CHECKSUM` aborts the *whole* series — months that already verified are
discarded too. A month that simply 404s (before listing, or a delisted
symbol the bucket no longer retains) is a recorded per-month skip and is
noted in the report. Quote asset is **USDT**, not USD.

**Kraken OHLCVT archive.** Quarterly zips from Kraken support article
360047124832, hosted on Google Drive, so this is a *loader for a local
file*, not a fetcher — it makes no network call. Point `--archive-path`
(or `RESEARCH_KRAKEN_ARCHIVE_PATH`) at the unpacked `{PAIR}_{minutes}.csv`
or the directory holding it; `BTC/USD` at `1d` resolves to
`XBTUSD_1440.csv`. It **refuses a partial or unparsable file outright**:
one bad row, one off-grid timestamp or one truncated final line makes the
whole load a skip with the offending line number, never the rows that
happened to parse. The drop contains **active pairs only**, so any
universe built from it alone is survivorship-biased — that caveat is
attached as a note to every loaded series.

**Cross-venue sanity.** `--cross-check <candle json>` compares daily
closes bar-for-bar against another venue's export. Any shared bar whose
closes disagree by more than `--max-divergence-bps` (default:
`MAX_REFERENCE_DIVERGENCE_BPS` from `Settings`, read and never written) is
listed in the report's `cross_venue_divergence` block and printed as a
`WARNING`. Bars only one venue published are not compared and the two
venues are never averaged together.

These commands are **research-only**: they never run on the trading
cycle, the `RiskEngine` never reads their output, and they flip no
`PAPER_PROMOTE_*` flag. Re-scoring a catalog on the longer history is
issue #136, not this tool.

## Strategy search and paper-voter promotion

The paper loop's default 2-of-3 ensemble (momentum + MA trend + mean reversion) is
**not** evidence of edge. `traderstack-strategy-search` scores those families — plus
always-on MA, a few window variants, and optional liquidation-z / cross-venue series —
as *standalone* voters under `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` +
`PRETRADE_SLIPPAGE_BPS`, with a walk-forward research window and a held-out tail.

```bash
# Offline / fixture (no network)
.venv/bin/traderstack-strategy-search \
  --candles tests/fixtures/strategy_search/btc_1h.json \
  --candles tests/fixtures/strategy_search/eth_1h.json \
  --candles tests/fixtures/strategy_search/sol_1h.json \
  --output-json var/ops/strategy_search_report.json \
  --output-md var/ops/strategy_search_report.md

# Live Kraken charts-spot ~180d 1h (public OHLC cannot page older than 720 bars)
.venv/bin/traderstack-strategy-search \
  --symbol BTC/USD --symbol ETH/USD --symbol SOL/USD \
  --resolution 1h --also-resolution 4h --count 4320 --source auto
```

Multiple-testing policy is **pre-registered top-1** (one promotion decision over the
catalog, not K independent "we found a winner" claims). A Bonferroni note is written
into the report; we do not invent per-fold p-values. Promotion additionally requires
walk-forward mean **total** return **> 0 after fees**, holdout excess > 0,
`PAPER_SEARCH_MIN_TRADES`, and `PAPER_PROMOTE_SEARCHED_STRATEGY_ID` equal to that
id. Beating buy-and-hold while still losing money is not an edge.

`PAPER_PROMOTE_SEARCHED_STRATEGIES` stays **false** until a report shows a winner.
Turning it on without a gate-clearing report fails closed at
`traderstack-check-config` and at `build_pretrade_gate` — the process does not
quietly fall back to the unpromoted MA ensemble under the promotion flag.

`BINANCE_LIQ_ENABLED` / `BOOK_TICKER_ENABLED` are live paper-research *streams*
(not an execution venue). They do not provide a 90–180d historical liquidation
series: Binance USDT-M historical REST is missing (live WS `!forceOrder@arr`
only; Vision `um/liquidationSnapshot` removed). Search therefore probes public
REST and records a skip rather than inventing a z from the live socket.

Funding and open-interest series are fetched from public REST when `--symbol` is
used (`--fetch-edge-series`, default on): Binance USDT-M first, OKX if Binance
returns 451/403. Pass `--liquidation-z` / `--funding-z` / `--oi-z` /
`--cross-venue-z` JSON to score a local series; otherwise those families are
skipped, not zero-filled.

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
| `POLYMARKET_WEATHER_LEDGER_PATH` (default `var/audit/polymarket_weather_paper.jsonl`) | `PolymarketWeatherPaperLedger` | One line per weather-market observation or would-trade intent from `traderstack-polymarket-weather-paper`. Always `venue_submitted=false`. Isolated from the crypto audit files so a weather run cannot rewrite crypto risk history. | No — plain JSONL research ledger. |
| `POLYMARKET_CRYPTO_TAPE_PATH` (default `var/audit/polymarket_crypto_wedge_tape.jsonl`) | `CryptoWedgeTape` (#142) | One line per observed Polymarket BTC/ETH threshold market per cycle: mid, best bid/ask, option-implied probability, model version, both venue timestamps, Crucix stand-aside status, row status. Always `venue_submitted=false` / `execution=paper_tape_only`; no size, side or notional field exists. Isolated from the crypto audit files. | No — plain JSONL research tape. |

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

#### What `verify_chain` alone does *not* prove (#68)

A hash chain is only as good as its root of trust, and here the root is the
file itself. Anyone who can write to `var/audit/` can regenerate the chain from
genesis with different content, and the rewritten file **passes `verify_chain`
perfectly** — every hash is self-consistent because every hash was recomputed.
The same applies to a file restored from an older backup, or truncated.

`traderstack-verify-audit` closes that by cross-checking the trail against
chain heads published *outside* it:

```bash
.venv/bin/traderstack-verify-audit \
  --audit-path var/audit/risk_decisions.jsonl \
  --anchor-path var/audit/anchors.jsonl
```

Exit codes are meant for cron: `0` chain intact **and** every anchor matches,
`1` verification failed, `2` no trail at that path. A rewrite is reported as
the sequence number where the file and an anchor disagree:

```
chain:   intact (412 record(s))
anchors: 3 checked
result:  FAILED
error:   record 199 hashes to 8f21c0a4b7de but the published anchor commits to
         1c9d4ee20b13: the trail was rewritten
diverged at sequence: 199
```

**No anchors is a failure, not a pass.** An attacker who can rewrite the trail
can usually delete a local anchor log too, so an intact chain with nothing to
check it against proves only internal consistency. `--allow-unanchored`
downgrades that to a pass; use it only when you know anchoring was never
enabled for the run in question.

A local anchor log on the same host is the weakest form of this: it raises the
bar (two files to forge instead of one) without moving the root of trust off
the box. Prefer the Redis or Postgres sinks with an insert-only grant for the
app role, so the trading process can add an anchor but never rewrite one.
`AUDIT_ANCHOR` sinks are wired through `FanoutAuditAnchorSink`, which counts
failures on `traderstack_audit_anchor_failures_total{sink=...}` and never
blocks a trading cycle — so alert on "no successful anchor in N minutes"
rather than expecting a loud failure at the time.

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
| `stale_primary_tick` | The venue tick is older than `MAX_MARKET_DATA_AGE_SECONDS`. | Usually transient (network/venue latency). Persistent → check the venue feed (Kraken WS reconnects, `VENUE_FEED=kraken_rest` as a paper-only fallback, or the Robinhood Chain websocket) is actually delivering. |
| `spread_limit_exceeded` | Bid/ask spread on the primary tick exceeds `MAX_SPREAD_BPS`. | Expected in thin/volatile conditions. Persistent on a liquid pair → check venue/pool liquidity, not a bug. |
| `no_independent_reference_price` | Neither CoinGecko nor CoinMarketCap returned a price for this asset (and, on paper, no last-good mid was still inside `PAPER_REFERENCE_LAST_GOOD_SECONDS`). | On paper, a burst of CoinGecko HTTP 429s should be absorbed by last-good / the longer paper cache — see "Paper reference-price resilience". Persistent rejects after that window, or any reject on live/shadow, mean both providers failed cold (or last-good expired): check keys, circuit breakers, and "Provider circuit breakers and quotas". |
| `reference_price_divergence` | The primary tick diverges from the independent reference(s) by more than `MAX_REFERENCE_DIVERGENCE_BPS`. | Investigate before loosening the threshold — this is the control that catches a wrong/manipulated venue price. |

**External intelligence gating** (after market data is accepted, before a
proposal):

| Reason | Meaning | Operator action |
|---|---|---|
| `no_external_intelligence` | `INTELLIGENCE_REQUIRED=true` but no configured provider (Dune/LunarCrush/CryptoPanic/Perplexity/altFINS/Crucix) returned anything this cycle. | Check provider keys/circuit breakers, or set `INTELLIGENCE_REQUIRED=false` if trading on market data alone is acceptable. |
| `adverse_news_event` | `INTELLIGENCE_BLOCK_ON_ADVERSE_NEWS=true` (default) and a news provider flagged an adverse event for this asset — new risk is blocked for the cycle; existing positions are untouched. | Expected behaviour during a real news event. Read the `news` feature fields in the audit line for which provider/asset triggered it. |
| `intelligence_provider_unavailable` | Crucix is opted in (`CRUCIX_ENABLED=true` or `CRUCIX_BASE_URL` / `CRUCIX_API_KEY` set) and that provider timed out, raised, or returned a non-snapshot this cycle. New risk is blocked; existing positions/exits are untouched. Other optional intel failures are still isolated. Same reject on paper, shadow, and live. | Check Crucix reachability (`host.docker.internal:8787` by default), the `crucix` circuit breaker, and `PROVIDER_TIMEOUT_SECONDS`. This is **not** a news event — distinguish it from `adverse_news_event`. Do not set `CRUCIX_ENABLED=false` to "fix" an outage unless you intend to stop using Crucix as a safety source. |

**Pre-trade backtest gate** (`PreTradeBacktestGate.evaluate`, only when
`PRETRADE_BACKTEST_ENABLED=true`):

| Reason | Meaning |
|---|---|
| `missing_candle_history` | The gate is enabled but no candle history was fetched for this cycle at all. |
| `insufficient_candle_history` | Fewer candles than `PRETRADE_MIN_CANDLES`. |
| `stale_candle_history` | The most recent candle is older than `PRETRADE_MAX_CANDLE_AGE_SECONDS`. |
| `no_strategy_consensus` | The deterministic strategy ensemble, re-run on current candles, produced no consensus side. See "Paper research mode and strategy consensus" below for when this is expected vs. a paper-config gap. |
| `strategy_does_not_confirm_side` | The ensemble's consensus side doesn't match the side a caller explicitly requested confirmation for. |
| `backtest_total_return_below_minimum` | Paper-only. Backtested total return (not vs. buy-and-hold) is below `PAPER_PRETRADE_MIN_TOTAL_RETURN`. Live/shadow never emit this. |
| `backtest_excess_return_below_minimum` | Backtested return net of fees/slippage, vs. buy-and-hold, is below the active floor (`PAPER_PRETRADE_MIN_EXCESS_RETURN` on paper, `PRETRADE_MIN_EXCESS_RETURN` on live/shadow). |
| `backtest_drawdown_above_maximum` | Full-history backtested max drawdown exceeds `PRETRADE_MAX_DRAWDOWN_PCT`. Live/shadow and the 1h non-promote paper path emit this. The daily paper promote path does **not** — that ceiling is calibrated to research walk-forward maxDD, a shorter series (ETH full-history ~43% on 400d vs WF 28.77%). |
| `backtest_sharpe_below_minimum` | Backtested Sharpe ratio is below the active floor (`PAPER_PRETRADE_MIN_SHARPE` on paper, `PRETRADE_MIN_SHARPE` on live/shadow). |
| `backtest_trade_count_below_minimum` | Fewer backtested trades than the active floor (`PAPER_PRETRADE_MIN_TRADES` on paper, `PRETRADE_MIN_TRADES` on live/shadow). |
| `walkforward_insufficient_history` | Not enough history for a walk-forward evaluation, and `PRETRADE_REQUIRE_WALKFORWARD=true`. |
| `walkforward_excess_return_below_minimum` | Mean out-of-sample excess return across walk-forward folds is below the active floor (`PAPER_PRETRADE_MIN_WALKFORWARD_EXCESS_RETURN` on paper, `0.0` on live/shadow). |
| `walkforward_drawdown_above_maximum` | Worst walk-forward fold's drawdown exceeds the active ceiling. On the daily paper promote path this is research-style WF (train=180 / test=60 / step=60, warmup=train) vs `PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`. Live/shadow compare isolated test-slice folds to `PRETRADE_MAX_DRAWDOWN_PCT`. |
| `candle_interval_mismatch` | Paper promote path only. History is missing or any bar is not the forced daily interval (`1d`). Scored before any backtest. |
| `promote_universe_excluded` | Paper daily promote path only (`PAPER_PROMOTE_EMA_9_21` or `PAPER_PROMOTE_EMA_9_21_ADX15` and `TRADING_MODE=paper`). The tick's symbol is outside `PAPER_PROMOTE_UNIVERSE` / the hard #100 envelope (`BTC/USD`, `ETH/USD`). SOL stays in `MVP_ASSETS` but is not traded under the BTC+ETH research envelope (honesty pack: SOL WF maxDD ~50% vs the 0.30 paper ceiling). Existing positions can still exit. Live/shadow never emit this. |

None of these need operator action beyond monitoring — a rejecting gate here is
working as intended (no history yet, or the ensemble genuinely doesn't clear its
own bar). Persistent `missing_candle_history`/`insufficient_candle_history` on
every cycle for one asset is the one worth investigating (candle provider outage
or a newly-added asset with too little history). Persistent
`no_strategy_consensus` on every cycle, with healthy Kraken candles and no
other rejection, is the paper-research-mode case described next.

## Paper research mode and strategy consensus

`no_strategy_consensus` is raised in `PreTradeBacktestGate.evaluate` after
`StrategyEnsemble.consensus` / `combine_signals` finds no majority side. It is
**not** a risk-engine rejection: market-data validation already passed, and
RiskEngine is never called for that cycle.

### Why a typical paper dry-run used to fail-closed here

The default candle ensemble has three voters (momentum, trend, mean-reversion)
and requires **two agreeing actionable signals**. Those three are
regime-exclusive:

| Regime | Who can vote | Typical Kraken 1h Spot OHLC |
|---|---|---|
| `trending_up` / `trending_down` | Trend (0.5% MA gap) **and** momentum (2% over 12 bars). Mean-reversion is silent. | Mild drift often clears the trend bar but not 2% / 12 hours → **one voter**. |
| `range` | Mean-reversion only (`|z| ≥ 1.5`). Momentum *can* fire but usually opposes it. | Flat-to-choppy books → **zero or one voter**, or a 1–1 split. |
| `high_volatility` | Momentum only (trend requires a trending regime). | Crash/spike hours → **one voter**. |

A split vote (equal buy and sell counts) is also no consensus — fail closed,
not a silent BUY.

Optional intelligence does **not** vote in this ensemble. Empty intel, a
missing Crucix (or any other unset edge provider), and absent edge fields
(`onchain.*`, `narrative.*`, `market.external_signal_score`) only starve the
deterministic specialists that feed the meta-agent as *evidence*. They cannot
create a candle-side consensus, and their absence is expected on a paper
laptop that left those keys blank.

So: candles and the tick can be healthy, RiskEngine would have allowed a
proposal, and the stack still emits no intentional paper trade because the
vote structurally cannot reach two agreeing sides.

### What paper research mode changes (and what it does not)

`PAPER_RESEARCH_MODE=true` is the **documented paper default**. It applies
**only** when `TRADING_MODE=paper` (`Settings.paper_research_active`).
`traderstack-paper` / `build_service` already refuse non-paper modes; the
ensemble helper also ignores the flag on live/shadow so a mis-set env cannot
loosen those gates.

When active:

1. A fourth, candle-only voter (`paper_research_baseline_v1`) joins the
   ensemble for **every allowlisted asset** (BTC, ETH, SOL, …). It is
   symbol-agnostic. Primary tilt is short-vs-long moving average on the
   same Kraken OHLC. When those two averages have compressed (typical ETH
   1h RANGE: a few bps) it falls back to last close vs the long MA so it
   does not go silent on one asset. No intel, no Crucix, no edge fields.
   Perfectly flat or non-positive prices stay flat.
2. If **no** optional intel provider has usable credentials, consensus may
   form from **one** agreeing healthy signal (`min_agreeing=1`). If any of
   Dune / LunarCrush / CryptoPanic / Perplexity / altFINS *is* configured,
   the two-voter bar is kept.
3. The pre-trade **backtest and walk-forward** still run. When the baseline
   is wired they measure that isolated MA path — not the full
   regime-exclusive ensemble, which flattens on 1–1 splits and bleeds fees
   on a lookback the MA itself would survive. On paper they use
   `PAPER_PRETRADE_MIN_*` (see the next section); they are not disabled. A
   consensus side that cannot show non-catastrophic total return, or that
   breaches drawdown / the paper excess and Sharpe floors / trade-count /
   walk-forward, is still rejected.
4. Every proposal that leaves the gate still goes through **RiskEngine**
   (kill switch first), then the meta-agent withhold-only review. Paper
   research mode cannot auto-approve, disable the kill switch, change a
   side/size after risk, or raise notionals.

`PAPER_RESEARCH_MODE=false` restores the strict two-voter candle ensemble
(no baseline voter). Use that when you want paper to fail-closed the same
way live/shadow do.

### When consensus is expected vs fail-closed

| Situation | Expected outcome |
|---|---|
| Healthy Kraken 1h history, `TRADING_MODE=paper`, `PAPER_RESEARCH_MODE=true` (default), intel keys blank, book has a measurable MA tilt, a price-vs-long-MA tilt, or a single regime-valid signal | Consensus **can** form on every allowlisted asset, including ETH-like RANGE books where short-vs-long has compressed. If the paper pretrade floors also clear (non-catastrophic total return, see below), the cycle should reach RiskEngine. Kill switch / limits / a catastrophic lookback may still reject. |
| Perfectly flat or no-signal book (zero momentum, zero MA gap, no z-score) | `no_strategy_consensus` — fail-closed. Features are not directional. |
| Split vote (equal buy and sell counts) | `no_strategy_consensus` — fail-closed, except on paper with intel off (`min_agreeing=1`): if the baseline voted, its side wins and an opposing minority cannot cancel it. |
| `PAPER_RESEARCH_MODE=false`, or `TRADING_MODE` is shadow/live | Two agreeing candle strategies required. Typical mild Kraken drift **will** fail-closed; that is intentional. |
| Optional intel configured on paper | Baseline voter is still present; `min_agreeing` stays 2. |
| Missing/stale/short candle history | `missing_candle_history` / `insufficient_candle_history` / `stale_candle_history` — not a consensus question. |

`traderstack-check-config` reports whether paper research mode is `active`,
`off`, or `ignored` (flag set but `TRADING_MODE` is not paper), and the
same for paper reference resilience and paper pretrade thresholds. On the
daily promote path it also prints `PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`
and `PAPER_PROMOTE_UNIVERSE` (BTC/USD + ETH/USD; #100 honesty pack), and
warns if that ceiling is tighter than the documented ~23.35% research
envelope.

## Paper pre-trade thresholds on Spot OHLC

The live/shadow floors (`PRETRADE_MIN_EXCESS_RETURN=0.0`,
`PRETRADE_MIN_SHARPE=0.0`, `PRETRADE_MIN_TRADES=3`) are a **promotion
bar**: beat costless buy-and-hold, print a non-negative Sharpe, and show
enough completed trades. They are not a bug.

On ~400-bar Kraken 1h Spot (~16.7 days) a candle-only MA voter
(`paper_research_baseline_v1`) is structurally behind that bar:

- An always-long BUY on an uptrend pays entry/exit fees that buy-and-hold
  does not, so `excess_return` is slightly negative even when the strategy
  made money. `PRETRADE_MIN_EXCESS_RETURN=0.0` is then unreachable.
- Typical Spot chop produces a handful of MA flips. Fees plus whipsaw push
  excess vs buy-and-hold below 0. Independently, the shared backtester
  records period returns only when the position is rebalanced, so a
  one-trade hold prints a large negative Sharpe even when the strategy
  made money.
- A clean uptrend that stays in one position has **one** completed
  round-trip, so `PRETRADE_MIN_TRADES=3` would reject the healthiest book.
- The *current* 16-day Spot lookback is often a mild pullback, not a
  clean uptrend. WSL retest on PR #82 (`PAPER_RESEARCH_MODE=true`, Spot
  OHLC restored): BTC/SOL reached consensus then rejected
  `backtest_total_return_below_minimum` (and excess) on an isolated MA
  path of about −7% vs buy-and-hold from the warmup bar of about −3 to
  −4%. That is a losing lookback, not a blow-up. Requiring
  `total_return >= 0` therefore blocked every BTC/SOL cycle (0 paper
  intents; Risk never reached) even though market data was healthy and
  drawdown stayed inside `PRETRADE_MAX_DRAWDOWN_PCT`. ETH failed earlier
  with `no_strategy_consensus` because short-vs-long MA compressed to
  ~4 bps (below the 10 bp bar) while price vs the long MA was still
  measurable — the baseline now uses that fallback so it participates
  for every allowlisted asset.
- Measuring the full regime-exclusive ensemble as the lookback made this
  worse: opposing minority votes flatten the position (1–1 split) and
  the book re-enters, so BTC ensemble total return was about −11% /
  −7% excess vs about −7% / −4% for the isolated MA path. Paper
  backtest/walk-forward therefore follow the wired baseline.

`TRADING_MODE=paper` therefore applies documented paper floors
(`build_pretrade_gate` reads `Settings.effective_pretrade_*`). The gate
stays on. Live/shadow keep the strict `PRETRADE_MIN_*` even if the paper
env vars are set.

| Paper setting | Default | What it still requires |
|---|---|---|
| `PAPER_PRETRADE_MIN_TOTAL_RETURN` | `-0.15` | Non-catastrophic evidence on the isolated MA path, aligned with `PRETRADE_MAX_DRAWDOWN_PCT`. A 16-day Spot pullback of a few percent can pass. A collapse still fail-closes (`backtest_total_return_below_minimum`). This is **not** "the strategy made money"; that claim was false for current BTC/SOL Spot. |
| `PAPER_PRETRADE_MIN_EXCESS_RETURN` | `-0.10` | Room for fee drag / MA flips vs costless buy-and-hold on a short window. Not a free pass for a large underperformance. |
| `PAPER_PRETRADE_MIN_SHARPE` | `-10.0` | The shared backtester records period returns only on a rebalance, so a one-trade MA hold prints a large negative Sharpe (~-5 on a clean 400-bar 1h uptrend) even when `total_return` is +28%. This floor is set so that artifact does not block a non-catastrophic lookback. Tighten toward `0` to rehearse the live bar. |
| `PAPER_PRETRADE_MIN_TRADES` | `1` | At least one completed round-trip. Flat/no-trade books still fail. |
| `PAPER_PRETRADE_MIN_WALKFORWARD_EXCESS_RETURN` | `-0.10` | Out-of-sample excess uses the same paper room. `PRETRADE_REQUIRE_WALKFORWARD` stays on. |
| `PRETRADE_MAX_DRAWDOWN_PCT` | `0.15` (shared) | 1h MA / live / shadow catastrophic bar. **Not** the daily `ema_9_21` promote ceiling. |
| `PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` | `0.30` (paper promote only) | Used when `TRADING_MODE=paper` and a daily promote pin is on (`PAPER_PROMOTE_EMA_9_21` or `PAPER_PROMOTE_EMA_9_21_ADX15`). Applied to **research walk-forward maxDD** (train=180 / test=60 / step=60, warmup=train), matching #95–#100. ETH full-history backtest DD on the same Kraken daily window is ~43% (400d) / ~36% (720d) — a different series; do not raise this past 0.30 to cover it. The 0.15 1h bar rejected every post-#94 daily soak cycle. 0 fails closed at load. Do not set `1.0` to disable the gate. |
| `PAPER_PROMOTE_UNIVERSE` | `BTC/USD,ETH/USD` (paper promote only) | Used when `TRADING_MODE=paper` and a daily promote pin is on. Restricts the **cycle list** and new-risk path to the #100 Kraken Spot BTC+ETH envelope. `MVP_ASSETS` still lists SOL for the flag-off paper path and for RiskEngine's allowlist; SOL is skipped with `promote_universe_excluded` rather than scored as if it were inside the envelope. Extra names cannot expand past BTC/USD + ETH/USD. Live/shadow ignore this. Universe alignment, not a claim of edge. See `docs/artifacts/strategy-search/ema-9-21-adx15-honesty.md`. |

Do **not** set `PRETRADE_BACKTEST_ENABLED=false` to "see if it trades".
That removes the gate; these floors exist so paper can reach Risk without
doing that. Tighten the paper floors toward the live values when you want
a promotion rehearsal.

## Paper reference-price resilience

Independent reference prices are CoinGecko and CoinMarketCap (already
wired, including CMC's unauthenticated public path). Kraken is
deliberately **not** accepted as an independent reference
(`market.validation` drops `MarketSource.KRAKEN`) — a same-venue
secondary pair would not catch a wrong venue tick.

CoinGecko Demo / public free tiers 429 under multi-asset paper polling
(WSL retest: ~14/22 cycles `no_independent_reference_price` from HTTP
429). Live/shadow stay fail-closed: no last-good, short cache.

On `TRADING_MODE=paper` only:

1. `PAPER_REFERENCE_CACHE_SECONDS` (default 120) replaces
   `REFERENCE_PRICE_CACHE_SECONDS` (20) for the reference-provider
   registries. Cached payloads keep their original `observed_at`.
2. `PAPER_REFERENCE_LAST_GOOD_SECONDS` (default 300) stores the last
   successful payload. A later 429, timeout, open breaker, or quota
   refusal serves that last-good mid instead of an empty list. After the
   window expires with no new success, the cycle fail-closes again
   (`no_independent_reference_price`).
3. CoinGecko retries **one** HTTP 429 honouring `Retry-After`, capped at
   2 seconds, in **every** trading mode. That is good-client behaviour so
   we do not hammer the vendor; it does not authorise a trade.

A last-good mid that has moved relative to the venue tick still trips
`reference_price_divergence` (`MAX_REFERENCE_DIVERGENCE_BPS`). Last-good
never changes RiskEngine limits, side, size, or the kill switch.

Cold start (no successful fetch yet) still fail-closes — there is nothing
to reuse. Set `PAPER_REFERENCE_LAST_GOOD_SECONDS=0` to restore
fail-closed-on-any-error on paper (acceptance soaks do this so fault
injection still observes `no_independent_reference_price`).

`traderstack-check-config` reports paper reference resilience as `active`
or `ignored`.

**Deterministic risk engine** (`RiskEngine.evaluate`, checked in this order,
tier by tier per `docs/RISK-PRINCIPLES.md`; always active, cannot be bypassed
by the LLM):

| Reason | Meaning | Operator action |
|---|---|---|
| `kill_switch_enabled` | Any kill-switch channel is engaged (see "Engaging/releasing the kill switch"). Every other check is skipped — this is the emergency-stop path. | Confirm it's intentional (`traderstack_kill_switch_source_engaged`), then `traderstack-resume` / clear the engaging channel when ready. |
| `stale_portfolio_state` | The local portfolio snapshot is older than `MAX_PORTFOLIO_STATE_AGE_SECONDS`. | Should not happen in the normal loop (the snapshot is built fresh each cycle) — investigate a wedged/slow cycle if seen. |
| `daily_loss_limit_reached` | Today's realized PnL has hit `MAX_DAILY_LOSS_PCT` of NAV (anchored at UTC midnight). Blocks risk-adding proposals. On a risk-reducing SELL (held long exposure) this is informational only — the exit can still proceed. | Expected control firing. Clears automatically at the next UTC day; do not raise the limit mid-incident to "let it keep adding risk". |
| `account_drawdown_limit_reached` | Drawdown from peak NAV has hit `MAX_ACCOUNT_DRAWDOWN_PCT`. Blocks risk-adding proposals; informational on a risk-reducing SELL. | Same as above — a deliberate stop on new risk, not a bug. Investigate the drawdown's cause before ever considering a limit change. |
| `gross_exposure_limit` | Total exposure across all assets has reached `MAX_GROSS_EXPOSURE_PCT` of NAV, leaving no room for more. Applies to risk-adding proposals only (including an uncovered SELL). | Expected once the book is close to fully allocated. A held-position SELL is not blocked by this reason. |
| `cash_reserve_breached` | Cash would fall below `MIN_CASH_RESERVE_PCT` of NAV if this proposal were approved. Applies to risk-adding proposals only. | Expected near full allocation; investigate only if it fires with substantial idle cash reported elsewhere. |
| `max_positions_reached` | The proposal's asset has no existing position and the book already holds `MAX_OPEN_POSITIONS` others. Applies to risk-adding proposals only. | Expected diversification control; not an error. |
| `strategy_circuit_breaker` | `StrategyCircuitBreaker` has tripped this `strategy_id` on realized underperformance (`STRATEGY_MAX_CONSECUTIVE_LOSSES` / rolling drawdown). | Investigate the strategy's recent trades before the cooldown (`STRATEGY_BREAKER_COOLDOWN_SECONDS`) expires; do not manually clear it without understanding why it tripped. |
| `asset_not_allowlisted` | The proposal's asset isn't in `MVP_ASSETS`. | Add it to `MVP_ASSETS` only after the same review any other risk-policy change gets. |
| `spread_too_wide` | The feature vector's spread reading exceeds `RISK_MAX_SPREAD_BPS` — the risk-policy spread gate, distinct from the pipeline's own `spread_limit_exceeded` (see `docs/EXECUTION-ARCHITECTURE.md`, "Two spread limits, deliberately"). | Same as `spread_limit_exceeded` — investigate venue/pool liquidity if persistent on a liquid pair. |
| `position_limit_reached` | Existing exposure to the asset already consumes all of `MAX_POSITION_PCT` of NAV, so remaining room is zero. Applies to risk-adding proposals only — a SELL of that held position is not blocked by this reason. | Expected once a position is fully sized. |
| `position_size_reduced` | *Not a rejection* — the decision is `reduce`, not `reject`. The requested notional was cut down to fit remaining `MAX_POSITION_PCT`/exposure/cash headroom, and the (smaller) order still proceeds. | Informational only. |
| `sell_capped_to_position` | *Not a rejection* — accompanies `REDUCE` on a risk-reducing SELL. Requested notional was larger than the exposure the engine observed for that asset, so approved size was clamped to the held position. Never scaled up. | Informational only. Persistent caps mean the strategy asked to sell more than the book holds. |
| `volatility_scaled` | *Not a rejection* — accompanies `ALLOW` or `REDUCE` on risk-adding proposals. `VOLATILITY_SIZING_ENABLED=true` scaled the notional down by `TARGET_VOLATILITY` / observed volatility (never scaled up). Risk-reducing exits skip this. | Informational only. |

**Deterministic position exits** (`exits.py`, paper and shadow only; live
ignores `EXIT_*` until documented). These are *not* rejection reasons —
they are why a reducing SELL was proposed. They appear on
`pipeline.exit_reason`, `proposal.strategy_id` (`exit-stop_loss`, …) and
`proposal.signal_ids`. The proposal still goes through `RiskEngine.evaluate`
(kill switch withholds). The meta-agent cannot veto them.

| Reason | Setting | Meaning |
|---|---|---|
| `exit_stop_loss` | `EXIT_STOP_LOSS_PCT` (paper default 2%) | Mark ≤ average cost × (1 − pct). |
| `exit_trailing_stop` | `EXIT_TRAILING_STOP_PCT` (default 0, off) | Mark ≤ high-water × (1 − pct) after the position has made progress. |
| `exit_take_profit` | `EXIT_TAKE_PROFIT_PCT` (paper default 4%) | Mark ≥ average cost × (1 + pct). |
| `exit_time_stop` | `EXIT_TIME_STOP_BARS` (paper default 24) | Held at least N bars (`effective_pretrade_candle_interval`; 24 × 1h = 1 day). With `PAPER_PROMOTE_EMA_9_21` the paper path uses daily bars, so 24 × 1d = 24 days unless you set the bar count down. Legacy checkpoints without `opened_at` do not fire this rule. |
| `exit_thesis_invalidated` | `EXIT_ON_THESIS_INVALIDATION` (default false) | Ensemble confirms the opposite side of the held long, or regime is `trending_down` after a momentum entry. |

Set a rule to `0` / `false` to disable it. `traderstack-check-config` prints
the block. `traderstack-paper-report` attributes closed round-trips by exit
reason. A halt still rejects the exit (`kill_switch_enabled`) — the switch
is an unconditional stop, including flatten.

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
| `invalid_exit_size` | The venue-submission twin of `paper_fill_invalid_exit_size`: a *reducing-only* order (a deterministic exit) could not be sized at or below the held quantity that `PaperRuntime` passed from this cycle's portfolio snapshot. Distinct from `plan_rejected` so invalid exit sizing stays countable apart from a venue or data refusal. Nothing was sent and no ledger order was created. | Read `execution_reason`. Residual dust under `EXECUTION_MIN_NOTIONAL_USD` is the common, benign cause. Anything else means the snapshot the exit was sized against disagrees with the venue book — reconcile before expecting the exit to fill. |
| `paper_filled` | In-process paper fill booked at mid ± `PAPER_SLIPPAGE_BPS` with `PAPER_FEE_BPS`. Ledger `FILLED`, cash/positions/NAV updated. Does not require Hummingbot. | None. This is the default paper PnL path (`PAPER_SIMULATE_FILLS=true`). |
| `paper_fill_duplicate` | This `decision_id` already has a paper fill (restart / replay). Book unchanged. | None; confirms the ledger guard. |
| `paper_fill_rejected` | Planner or book refused the fill (lot/notional/slippage, or a *non-reducing* SELL larger than the held position — a reducing-only exit is clamped to the position instead, see the next row). | Read `execution_reason`. Persistent slippage rejects: check `PAPER_SLIPPAGE_BPS` ≤ `EXECUTION_MAX_SLIPPAGE_BPS`. |
| `paper_fill_invalid_exit_size` | A *reducing-only* order (a deterministic exit) could not be sized at or below the held quantity: nothing left to reduce, the held quantity rounds to zero at `EXECUTION_LOT_STEP`, or clamping it to the held quantity leaves it under `EXECUTION_MIN_NOTIONAL_USD`. Distinct from `plan_rejected` / `paper_fill_rejected` so invalid exit sizing is countable apart from a venue or data refusal (`traderstack_paper_fills_total{status="paper_fill_invalid_exit_size"}`). | Read `execution_reason`. A residual dust position under the venue minimum is the common cause and is benign; anything else means the position the exit was sized against disagrees with the paper book — check the ledger and the checkpoint before expecting the exit to fill. |
| `paper_fill_withheld` | Kill switch engaged, reconciliation blocked, or torn durable state. Intent was not filled. | Same as a withheld submission — fix the halt/reconcile/ledger before expecting NAV to move. |
| `diagnostic_withheld` | `OPPORTUNITY_DIAGNOSTIC_MODE=true`: every upstream control allowed this order (or the kill switch was engaged — `execution_reason` says which) and diagnostic mode withheld the paper fill / venue submission by design. NAV never moves in this mode. | None. Read the opportunity funnel (`--funnel-path` snapshot or `traderstack-opportunity-funnel`) for where the *other* cycles stopped; set the flag back to `false` to resume paper fills. |

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
   share the same underlying discipline (venue state wins). See also
   "Corrupt or torn checkpoint / ledger" below if the file itself will not
   parse.
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

## Paper-research edge feeds (Binance liquidations, optional bookTicker)

Opt-in **paper-research** streams. They are **not** execution venues: enabling them does not add Binance or Bybit order routing, and `RiskEngine` does not read their features to size, side, or authorize a trade. They exist so the feature vector (and therefore the meta-agent's withhold-only context) can include liquidation-cascade intensity and a second-venue mid divergence.

Both feeds use the same reconnect/backoff loop as Kraken ticker/book (`traderstack.market.streaming`). They are **not** wrapped by `ProviderRegistry` — a request timeout and circuit breaker do not fit a long-lived subscription. A collector that dies after reconnect exhaustion logs `edge_collector_stopped` and the cycle continues with missing `edge` fields; it does **not** halt trading.

**Enable in paper mode** (after `cp .env.example .env` and `traderstack-check-config`):

```bash
# Binance USDT-M all-market liquidations → AssetFeatureVector.edge.liq_*
BINANCE_LIQ_ENABLED=true
# Optional. Default is the public forceOrder stream; leave as-is unless you have a reason.
# BINANCE_LIQ_URL=wss://fstream.binance.com/ws/!forceOrder@arr
# Rolling window (seconds) for the current notional/count, and the longer baseline
# used for z-scores. Counts are bounded to [0, 1] via BINANCE_LIQ_COUNT_CAP.
# BINANCE_LIQ_WINDOW_SECONDS=60
# BINANCE_LIQ_BASELINE_SECONDS=900
# BINANCE_LIQ_COUNT_CAP=20

# Optional second-venue bookTicker → edge.cross_venue_mid_divergence_bps
# Venue is binance (USDT-M combined bookTicker) or bybit (v5 linear tickers).
BOOK_TICKER_ENABLED=true
BOOK_TICKER_VENUE=binance
# BOOK_TICKER_VENUE=bybit
```

`traderstack-check-config` reports both flags. `TRADING_MODE` stays `paper`. Do not point Hummingbot or `VENUE_FEED` at Binance/Bybit as a side effect of turning these on — the primary tick remains Kraken or `robinhood_chain`.

**How to read the features.** On an accepted cycle the audit line's `feature_vector.edge` carries:

| Field | Meaning |
|---|---|
| `liq_notional_long_z` / `liq_notional_short_z` | Current-window long/short liquidation notional vs. the baseline window totals, clipped to [-5, 5]. `null` until at least two baseline windows exist. A Binance `SELL` force order is a **long** liquidation; `BUY` is a **short** liquidation. |
| `liq_count_long` / `liq_count_short` | Event count in the current window, bounded to [0, 1] as `min(n, CAP) / CAP`. |
| `cross_venue_mid_divergence_bps` | `abs(second_venue_mid - primary_mid) / primary_mid * 10_000`. Kraken is typically USD and the second venue is USDT, so a small basis is expected. |
| `cross_venue_mid_source` | `binance` or `bybit`. |

Prometheus: `traderstack_stream_messages_total`, `traderstack_stream_reconnects_total`, `traderstack_stream_last_message_unixtime`, `traderstack_liq_window_notional_usd`, `traderstack_liq_window_zscore`, `traderstack_cross_venue_mid_divergence_bps`.

## Provider circuit breakers and quotas

Every external provider — reference prices (CoinGecko, CoinMarketCap), candle
history (Kraken), and every intelligence adapter (Dune, LunarCrush,
CryptoPanic, Perplexity, altFINS, Crucix) — is wrapped in a per-provider
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
- **Caching** (`REFERENCE_PRICE_CACHE_SECONDS` for reference prices on
  live/shadow; `PAPER_REFERENCE_CACHE_SECONDS` plus
  `PAPER_REFERENCE_LAST_GOOD_SECONDS` on paper — see "Paper
  reference-price resilience"; `INTELLIGENCE_CACHE_SECONDS` for
  intelligence providers, at the orchestrator level) — reduces call
  volume. The short live/shadow TTL stays well under
  `MAX_MARKET_DATA_AGE_SECONDS`. Paper last-good is a failure fallback,
  not a freshness refresh: it keeps the original `observed_at`.

Inspect current state via `health()` on each `ProviderRegistry` (surfaced
through structured logs and the `traderstack_provider_*` Prometheus metrics —
`ops/grafana/dashboards/traderstack.json`'s "provider latency/failures" panel)
or `traderstack-check-config`'s per-provider quota lines. A provider showing
as configured (`traderstack-check-config`) but whose feature keeps rejecting
with `no_independent_reference_price`/`no_external_intelligence` is very
likely sitting behind an open breaker — check its `last_error`.

## Kraken REST ticker fallback

Kraken WS v2 (`VENUE_FEED=kraken`, the default) reconnects with backoff and
gives up after `KRAKEN_MAX_RECONNECT_ATTEMPTS`. If that stream is hung from
the operator's network — idle proxy, outbound WS blocked, `KrakenFeedExhausted`
in the audit log — switch the **paper** process to the public Spot REST
ticker instead of guessing ticks:

```bash
# .env
TRADING_MODE=paper
VENUE_FEED=kraken_rest
KRAKEN_REST_POLL_SECONDS=1
```

`traderstack-paper` then polls `GET https://api.kraken.com/0/public/Ticker`
(`a`/`b`/`c` → ask/bid/last) once per `stream_ticks` wait. No credentials,
no private endpoints, no signing. `VENUE_FEED=kraken_rest` with
`TRADING_MODE` other than `paper` is a startup error
(`require_paper_kraken_rest`) and a `traderstack-check-config` warning.

This feed has no order-book channel (`KRAKEN_BOOK_ENABLED` is ignored).
Candle history is unchanged (public Spot OHLC). Independent reference
prices (CoinGecko / CoinMarketCap) still run; CMC's public quotes path
accepts both list- and dict-shaped `data`/`quote` so a missing paid key
can still yield a USD price when the public payload is well-formed.

Switch back to `VENUE_FEED=kraken` once WS is healthy — REST is a
fallback, not the preferred execution-quality stream.

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

### Corrupt or torn checkpoint / ledger

Symptoms: startup logs `corrupt_execution_ledger` or `corrupt_portfolio_checkpoint`;
`traderstack_runtime_healthy` is `0`; `traderstack_reconciliation_blocked` is `1`;
`RuntimeHealth.durable_state_error` is set; the service refuses to submit (and
does not enter the cycle loop). This is the fail-closed reading of a host crash
or power loss that truncated `var/state/execution_ledger.json` or
`var/state/portfolio.json` — the same failure mode as deleting the ledger file,
reached without anyone deleting anything.

The writers (`JsonExecutionLedgerStore`, `JsonPortfolioCheckpointStore`, the
JSONL audit sinks) `fsync` the file after each critical write and `fsync` the
parent directory after an atomic rename. That is durable on local POSIX
filesystems (ext4, XFS, typically also APFS). On some NFS / overlayfs mounts
directory `fsync` is not supported (`EINVAL`); the *file* fsync still happens.
Put `--ledger-path` and `--checkpoint-path` on local POSIX storage, not a
network mount, if you care about surviving a host crash. `os.fsync` behaviour
is OS- and filesystem-dependent; the tests monkeypatch `os.fsync` rather than
pulling the plug.

**Recovery:**

1. Engage the kill switch. Do not start the process with `--submit` against a
   torn ledger.
2. Look next to the target file for a leftover `.tmp` (`execution_ledger.json.tmp`,
   `portfolio.json.tmp`). If the `.tmp` is a complete, parsable JSON document and
   the target is empty or truncated, copy the `.tmp` over the target *only after*
   you have verified it parses (`python -c "import json; json.load(open('...'))"`)
   and you have a copy of both files. Then reconcile against the venue before
   any new submission — the recovered ledger may pre-date the venue call that
   was in flight when the host died.
3. If neither file parses, restore the most recent backup of `var/state/` and
   treat every in-flight `decision_id` as `SUBMISSION_UNCERTAIN`: query the
   venue (Hummingbot / paper account) for those client order ids before
   allowing `--submit` again. Starting with an empty ledger is the one way the
   idempotency guard can be lost (`tests/acceptance/test_duplicate_order.py`).
4. The JSONL audit trails (`var/audit/runtime.jsonl`,
   `var/audit/risk_decisions.jsonl`) append and fsync each record. A truncated
   tail line is skipped by `traderstack-paper-report`; a torn risk-audit line
   fails `verify_chain` at that sequence. Do not edit them to "fix" the chain.
5. Restart only once the ledger and checkpoint parse and a reconciliation pass
   is clean. Release the kill switch after that.

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

## Polymarket weather paper research

Opt-in research profile. It does **not** run inside `traderstack-paper` and does
**not** call `RiskEngine` on crypto assets. Invoking the dedicated CLI is the
only way it executes. `POLYMARKET_WEATHER_ENABLED` is a documentation / 
`traderstack-check-config` flag; leaving it `false` (the default) keeps the
crypto loop unchanged.

### What it does

1. GET public Polymarket Gamma events tagged `POLYMARKET_WEATHER_TAG_SLUG`
   (default `weather`).
2. Parse temperature contracts (threshold "N°F or higher", or "low–high°F"
   buckets) only when the city is on `POLYMARKET_WEATHER_CITIES`.
3. GET public CLOB `/midpoint` for the Yes token (no signing, no `/order`).
4. GET Open-Meteo daily `temperature_2m_max` (or NOAA `/points` → `/forecast`)
   for that city/date.
5. Compare a Normal(`forecast_high`, `POLYMARKET_WEATHER_SIGMA_F`) model
   probability to the CLOB mid. If `|model − mid| − POLYMARKET_WEATHER_FEE_HAIRCUT`
   ≥ `POLYMARKET_WEATHER_MIN_EDGE` (the namespaced MIN_EDGE), record a
   **would-trade** paper intent.
6. Append the intent to `POLYMARKET_WEATHER_LEDGER_PATH`.
   `venue_submitted` is always `false`.

### Hard constraints

- `TRADING_MODE` must be `paper`. `live` and `shadow` raise at startup.
- The four-channel operator kill switch is consulted. If engaged (including
  the default `KILL_SWITCH=true`), qualifying edges are recorded as
  `kill_switch` withheld intents with `paper_notional_usd=0`.
- There is no Polymarket private-key / L2 / signing setting. Do not add one.
- Unknown city slugs fail closed. The catalog default prefers warm/stable
  climates (`honolulu`, `san_diego`, `miami`, `phoenix`, `singapore`,
  `lisbon`). High-variance cities (`new_york`, `chicago`) exist in the catalog
  but are not defaults.

### Offline / first run

```bash
# kill switch off only in APP_ENV=development — otherwise check-config warns
KILL_SWITCH=false TRADING_MODE=paper \
  .venv/bin/traderstack-polymarket-weather-paper \
    --fixtures-dir tests/fixtures/polymarket \
    --ledger-path var/audit/polymarket_weather_paper.jsonl
```

`--fixtures-dir` needs no network. A live cycle (public GETs only) omits that
flag. `traderstack-check-config` prints the weather block, including
"paper intents only (no CLOB orders)" and the report-only eval CLI.

### Fee-aware evaluation (report-only)

`traderstack-polymarket-weather-eval` scores resolved rows (or writes the
honest empty historical-tape report). It does **not** run inside
`traderstack-paper`.

```bash
# Honest empty live tape (no PIT mid + official station-high series here)
KILL_SWITCH=false TRADING_MODE=paper \
  .venv/bin/traderstack-polymarket-weather-eval --empty-live

# Offline calculator on fixture packs (still cannot promote; n is tiny)
KILL_SWITCH=false TRADING_MODE=paper \
  .venv/bin/traderstack-polymarket-weather-eval \
    --resolved tests/fixtures/polymarket/resolved_print_a.json \
    --resolved tests/fixtures/polymarket/resolved_print_b.json
```

`--empty-live` is the successful outcome when there is no public
point-in-time CLOB mid + official ASOS/NCEI high tape. Do not invent
historical mids from settlement prices (look-ahead). A single print
cannot promote. Two independent prints that clear the calculator floor
still do not flip a `PAPER_PROMOTE_*` flag — this CLI cannot write a
pin. The pre-registered crypto overlay
(`polymarket_weather_vs_btc_daily`) is skipped unless you pass
`--btc-daily`; missing series is not invented.

### Do not trust claimed win rates

Blog / social claims that "NWP vs Polymarket temperature" is a high-win-rate
edge are **unvalidated** for this repo. A `WOULD_TRADE` row is a hypothesis,
not alpha. The eval CLI implements the calculator for gates 1 / 4 / 5 in
`docs/EVALUATION-FRAMEWORK.md` ("Polymarket weather — validation A/B").
Gates 2 (walk-forward parameter fit) and 3 (a full season of live paper
A/B) are still not claimed. Do not promote this module toward live CLOB
trading from paper intents or a single fixture pack.

## Ensemble trend (multi-lookback Donchian, trailing stop, vol target)

#137 pre-registers the Zarattini / Pagani / Barbon "Catching Crypto
Trends" rules (SSRN 5209907) as a dual-print family. It is **not** a
#118 Donchian N retune: #118 scored single high/low channels on two
assets; this family votes nine close-only lookbacks, trails a stop,
targets volatility and forces non-members of a monthly point-in-time
universe flat.

- Treatment (frozen): for each lookback N in {5, 10, 20, 30, 60, 90,
  150, 250, 360}, that lookback opens long when `close[t] > max close
  of bars [t-N, t)` (bar t never sets its own level). On entry the stop
  is the midpoint of that prior N-bar close channel; on every later bar
  the stop is `max(prior stop, current midpoint)` and never ratchets
  down; exit to flat when `close[t] < stop`; re-entry needs a fresh
  breakout on a later bar.
- Ensemble weight = (open lookbacks / total) × min(0.25 / annualised
  90-day realised vol through close[t], 1.0), long-only, capped at 1.0
  (paper spot has no leverage). Decision at close[t]; fill at t+1 open.
- Universe snapshot policy (frozen): on the first bar of each UTC month,
  using only bars strictly before that month, a `CANDIDATE_UNIVERSE`
  name is a member when it has ≥ 365 prior daily bars (or its Kraken
  series hits the 720-bar public cap, which implies the listing
  predates the window) and its median 30-day close×volume is ≥ $2M
  (Kraken-local volume — stricter than the paper's aggregate); the
  top-20 by that median are members for the whole month. Fewer than 20
  qualifiers is a smaller book, never a relaxed bar.
- Survivorship caveat: Kraken REST serves only currently-listed pairs
  and at most 720 daily bars, so this window is survivorship-biased
  (unlike the paper). The point-in-time snapshot removes look-ahead in
  membership only. Every report header states this.
- Warmup: the nine-lookback book needs 361 bars before its first
  assignment (~359 decision bars on the 720 cap), so early folds are
  all-flat and `min_trades` may fail — reported as warmup-limited, never
  invented. `ens_trend_6lb_vt25` ({5..90}) is in the same frozen catalog
  for that reason; it is not a post-hoc retune.
- Fee tier (frozen Kraken Pro schedule, bps maker/taker): tier 1 =
  40/80 (default; the pilot's tier), 2 = 30/60, 3 = 22/38, 8 = 8/20,
  12 = 0/10. The taker leg is charged per side; gate C doubles. The
  shared harness charges fees on full equity at every rebalance, so
  fractional weights are cost-overstated (conservative). `--fee-bps`
  overrides the tier when explicit. Post-only maker realism is #138.
- Frozen ids: `ens_trend_9lb_vt25`, `ens_trend_6lb_vt25`,
  `ens_trend_9lb_unit` (informational contrast), plus the control
  `ma_cross_10_30` (cannot enter the passer set).
- Scoring: same #96+A+B+C combined bar on Kraken public Spot daily 720
  **and** the #102 Binance.US older-720. BTC and ETH gate; SOL reported.
  Ranking key: Kraken BTC+ETH mean holdout excess among dual-print
  passers. Era prints (#133) and DSR / PBO (#135) are reported as
  `era_prints_available=false` / `dsr_pbo_available=false` until they
  land; re-run and re-commit the report then.
- Attribution by asset and by lookback is gross close-to-close
  (informational; the lookback columns sum to the asset total).
- Paper path: `EnsembleTrendVoter` (`strategy_id=ens_trend_9lb_vt25`)
  emits BUY with `score` in (0, 1] or `side=None`, never SELL, and
  recomputes on decision-time candles when no precomputed series is
  registered, so the existing pre-trade gate can re-confirm it.
  RiskEngine is untouched and sizes from Settings, so it can only
  reduce. The 20-name research book does **not** widen
  `RISK_MAX_OPEN_POSITIONS`, `MVP_ASSETS` or `PAPER_PROMOTE_UNIVERSE`
  — see `docs/EXECUTION-ARCHITECTURE.md`, "Ensemble-trend layering".
- This command never flips `PAPER_PROMOTE_*`, adds no Settings field,
  and does not add a new pin. A committed dual-print passer would get
  its own flag PR, default false. Empty dual-print set is success.

```bash
.venv/bin/traderstack-ensemble-trend --live
.venv/bin/traderstack-ensemble-trend --live --no-binance
.venv/bin/traderstack-ensemble-trend --live --kraken-tier 3
```

`--live` pulls every `CANDIDATE_UNIVERSE` pair sequentially from Kraken
public OHLC (about one request per second; an unknown pair or HTTP error
is a per-symbol skip note, never an abort) and then Binance Spot daily
BTC/ETH/SOL (`api.binance.us` when `api.binance.com` is HTTP 451; 403 /
451 is a skip and the second print fails closed). See
`docs/artifacts/strategy-search/ensemble-trend.md`.
## Second-venue PIT basis (OKX + Binance Vision) and the basis-aware carry re-score

`carry_hedged_sign` was the only name to finish positive after fees on
both independent funding tapes (Hyperliquid + HTX) and was blocked only
on point-in-time basis. #134 wires two independent daily **mark−index**
tapes that reach 2020 on BTC and ETH, so the live Kraken 720 can be
scored basis-aware **without moving the window**:

| venue | construction | path | notes |
| --- | --- | --- | --- |
| OKX | `history-mark-price-candles` close − `history-index-candles` close, over index | `GET /api/v5/market/history-mark-price-candles?instId=BTC-USDT-SWAP&bar=1Dutc` and `…/history-index-candles?instId=BTC-USDT&bar=1Dutc` (index instId has **no** `-SWAP`) | `bar=1D` is the UTC+8 day (opens 16:00 UTC) — only `1Dutc` lines up with the funding tape's UTC-day sums; rows off a UTC midnight are skipped and counted. 100 rows/page, `after=<ts_ms>` pages older. Rapid pagination has produced HTTP 403 from the WAF: pages are walked serially with a 0.25 s pause and 2/4/8/16/32 s backoff; after five retries the series is recorded truncated/skipped, never filled. The newest row is the uncommitted day (`confirm=="0"`) and is dropped. |
| Binance Vision | `markPriceKlines` close − `indexPriceKlines` close, over index | `https://data.binance.vision/data/futures/um/{monthly,daily}/{markPriceKlines,indexPriceKlines}/{SYMBOL}/1d/…zip` (+ `.CHECKSUM`) | Reachable via S3 while `fapi.binance.com` REST is HTTP 451 here. Every zip's sha256 is verified before parsing; a mismatch or missing `.CHECKSUM` **fails closed** (that month/day is skipped, not filled from elsewhere). Monthly zips for complete months; a 404 month (not yet published) and the trailing partial month use daily zips up to yesterday UTC; today's bar is never used. Cache under `var/research/binance_vision/` is re-verified on every read. |

Refused in code (`research/basis.py::refuse_forbidden_basis_source`):
`premium` / `premiumIndexKlines` / `.XBTUSDPI` (funding-formula premium),
`klines` / `market/candles` / `candleSnapshot` (last-trade), `fundingRate`
/ `funding-rate-history` (funding-implied), `trade` / `aggTrades` /
`bookTicker` / `quote` (trade or book tapes). Every emitted value is a
finite float with `|basis| ≤ 0.10` on a UTC day open; anything else is
skipped and counted (`tests/security/test_basis_tape_cannot_relax_controls.py`).

Pairing rule, frozen in code before any pull
(`funding_carry.BASIS_PAIRING_RULE`): **primary funding print ×
`--basis-venue` (default `okx`); second funding print ×
`--second-basis-venue` (default `binance_vision`)**. The funding tape
and the basis tape are different venues — the report states the
cross-venue pairing (`hyperliquid × okx`, `htx × binance_vision`) rather
than hiding it. Basis is looked up **per symbol** and never broadcast
from one asset to the other. A lone basis series (one print only) is
**not applied alone**: both prints score basis-aware or neither does,
and `basis_status` stays `skipped`. A per-symbol basis supplied against
a single (non-per-symbol) funding series is *unpaired* and not applied.
Basis for day D is the day-D close and enters only the day-D hedged PnL
(close D−1 → close D); it never touches the harvest decision. A day
missing on either side is skipped, never zero-filled. Basis-aware
scoring is daily only (`--interval 1d`). Choosing `--basis-venue
hyperliquid --second-basis-venue htx` selects the #126 coverage-driven
freeze (window ending 2026-06-01) instead.

```bash
# 1. pull both venues from 2020 (≈10 min; OKX walks serially, Vision verifies every zip)
.venv/bin/traderstack-download-basis --venue okx --venue binance_vision --since 2020-01-01
# 2. re-score the frozen carry catalog on the live Kraken 720 with dual basis (default costs 10+5 bps)
.venv/bin/traderstack-funding-carry --live --interval 1d --basis-dir var/research/basis
# 3. the pilot-tier print: Kraken Pro Tier-1 taker = 80 bps per side (#138 fee realism)
.venv/bin/traderstack-funding-carry --live --interval 1d --basis-dir var/research/basis \
  --fee-bps 80 --output-md docs/artifacts/strategy-search/funding-carry-daily-tier1-taker.md \
  --output-json var/ops/funding_carry_daily_tier1_taker.json
```

`--fetch-basis` (default on for `--live --interval 1d`) fetches any
series missing from `--basis-dir` and writes it there; `--no-fetch-basis`
reads files only. The report header shows `basis_status`,
`basis_print_kind` (`none` / `single_basis` / `dual_basis`),
`basis_venue`, `second_basis_venue`, and the basis section carries the
probe table (print, funding venue, basis venue, symbol, first, last,
days, aligned-with-funding days, applied / not_applied_alone /
not_applied_unpaired).

`can_promote` keeps its existing conjunction (dual-print **and** hard
gates **and** `basis_status=ok` **and** paper path **and** a dual-print
passer). It is a report field only — nothing outside `research/` reads
it, no `PAPER_PROMOTE_*` default changes, and no new pin is added by
this command. See
`docs/artifacts/strategy-search/pit-basis-second-venue.md` (probe
table), `funding-carry-daily.md` (dual-basis print at 10+5 bps),
`funding-carry-daily-tier1-taker.md` (80 bps print),
`funding-carry-basis.md` and `pit-basis-archives.md` (decision).
## Fee realism (Kraken Pro tier) (#138)

Research used to score every candidate at `PRETRADE_FEE_BPS=10` +
`PRETRADE_SLIPPAGE_BPS=5` per leg (gate C at 20+10), and paper fills
charged `PAPER_FEE_BPS=10`. Kraken's published Pro spot schedule
(kraken.com/features/fee-schedule, read 2026-09-13, frozen in
`src/traderstack/fee_tiers.py`) starts far above that:

| `PAPER_FEE_TIER` | 30-day volume | maker bps | taker bps | round trip taker |
| --- | --- | ---: | ---: | ---: |
| `kraken_pro_spot_t1` (default, pilot) | $0+ | 40 | 80 | 160 |
| `kraken_pro_spot_t2` | $2.5K+ | 30 | 60 | 120 |
| `kraken_pro_spot_t3` | $10K+ | 22 | 38 | 76 |
| `kraken_pro_spot_t8` | ~$500K+ | 8 | 20 | 40 |
| `kraken_pro_spot_t12` | $10M+ | 0 | 10 | 20 |
| `modelled` | n/a | `PAPER_FEE_BPS` | `PAPER_FEE_BPS` | 2× `PAPER_FEE_BPS` |

What the tier changes:

- **Paper fills** (`execution_status=paper_filled`), the no-venue-fee
  fallback in `HummingbotExecutionReconciler`, and the paper pre-trade
  backtest gate all charge the tier's **taker** leg
  (`Settings.effective_paper_fee_bps`). Default Tier 1 = 80 bps per leg.
  Wherever an earlier section of this runbook says "`PAPER_FEE_BPS`"
  for a paper fill or a `fee_source=modelled` ledger fee, read
  "`PAPER_FEE_TIER` taker (`PAPER_FEE_BPS` only when
  `PAPER_FEE_TIER=modelled`)". `PAPER_FEE_BPS` still applies to the
  paper perp stub (`PAPER_PERP_HEDGE`): a Kraken spot tier would be an
  invented perp fee.
- **Every research CLI** (`traderstack-research`,
  `traderstack-strategy-search`, `traderstack-miles-search`,
  `traderstack-daily-robustness`, `traderstack-harder-gates`,
  `traderstack-honesty-pack`, `traderstack-second-print`,
  `traderstack-dual-print-search`, `traderstack-liq-regime-search`,
  `traderstack-intraday-dual-print`, `traderstack-relative-value`,
  `traderstack-xs-momentum`, `traderstack-donchian-breakout`,
  `traderstack-tsmom`, `traderstack-bollinger-fade`,
  `traderstack-calendar-seasonality`, `traderstack-lead-lag`,
  `traderstack-volume-breakout`) takes `--fee-tier <id>` and scores at
  `max(PRETRADE_FEE_BPS, tier taker)` + `PRETRADE_SLIPPAGE_BPS`.
  Precedence: explicit `--fee-bps N` (report stamped `explicit`) >
  `--fee-tier` > `PAPER_FEE_TIER`. Wherever an earlier section says
  `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)`, read
  `max(PRETRADE_FEE_BPS, PAPER_FEE_TIER taker)`. Gate C stays 2× the
  tier (160+10 bps per leg at Tier 1).
  `traderstack-funding-carry` is the one research CLI without
  `--fee-tier` yet: `research/funding_carry_cli.py` is owned by #134
  (basis-aware carry) in this wave, so it still scores at
  `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` and prints no `fee_tier`
  block; it gains the flag once #134 lands.
- **Every report and `report.json` names the tier**: a `fee_tier` block
  (`tier_id`, `maker_bps`, `taker_bps`, `role=taker`, `fee_bps_used`,
  `source`, `read_on`) and a markdown line directly under the costs
  line, e.g. `Fee tier: Tier 1 ($0+ 30d) maker 40 / taker 80 bps
  (kraken_pro_spot_t1); scored at taker 80 bps. Maker bps shown for
  information only, not assumed: no paper post-only fill-rate evidence
  exists yet.` Reports generated before #138 have no `fee_tier` block
  and were scored at 10+5; they still load.
- **Maker fees are never assumed.** There is no `--fee-role`, no
  `PAPER_MAKER_FEE_BPS`, and `FeeTierStamp.role` can only be `taker`.
  Post-only limit orders are #73's planner design; one month of paper
  fill-rate data must exist before any report may score at maker bps.
- `traderstack-check-config` prints a `Paper fee tier` line and warns
  when `PAPER_FEE_TIER=modelled` (four to eight times optimistic versus
  Tier 1). `modelled` is the documented way back to pre-#138 numbers,
  not a recommendation.

What the tier does **not** change: it is not a risk limit
(`RiskEngine` never reads it; it is not in `RISK_LIMIT_FIELDS` and does
not move `policy_version`), it cannot size a trade upward or pick a
side, and it never flips a `PAPER_PROMOTE_*` flag. A higher fee only
debits NAV, which the daily-loss and drawdown breakers already read, so
it can only withhold. Expect the #131 funnel to show `pretrade` as the
dominant blocking gate at Tier 1 and near-zero paper fills — that is
honest. An empty catalog at Tier 1 is a successful research result; the
committed pre-#138 catalogs are re-scored on the new default by #136,
not regenerated here.

```bash
.venv/bin/traderstack-tsmom --live                                   # Tier 1 taker (default)
.venv/bin/traderstack-tsmom --live --fee-tier kraken_pro_spot_t3     # $10K+ 30d account
.venv/bin/traderstack-tsmom --live --fee-bps 10                      # stamped "explicit"
PAPER_FEE_TIER=modelled .venv/bin/traderstack-check-config           # warns
```

## Crypto-threshold wedge tape (#142)

`traderstack-polymarket-crypto-collect` is a second, separate opt-in research
process (like the weather collector above): it never enters
`ContinuousPaperService`, never reaches `RiskEngine`, and emits no intent, size
or side. It only *observes*.

One invocation does exactly this:

1. Build the deterministic daily event slugs for `POLYMARKET_CRYPTO_ASSETS`
   over today plus `POLYMARKET_CRYPTO_LOOKAHEAD_DAYS`
   (`bitcoin-above-on-september-16-2026`, `ethereum-above-on-…`).
2. `GET /events?slug=…` on Gamma. A slug that does not exist yet returns `[]`
   and is counted as `events_missing` — a skip, never an invented row. A Gamma
   that does not *answer* is counted separately as `events_error`, so an outage
   never reads as "there was nothing listed".
3. Parse each market: only `Will the price of <Bitcoin|Ethereum> be above $K on
   <Month D>?` with an `endDate`, two CLOB token ids, an open book and a
   description naming the Binance 1-minute candle is accepted. Anything else
   (weekly ranges, "dip to", "reach", closed markets, a different settlement
   source) is counted as `unparsed` and dropped.
4. `GET /book?token_id=<yes token>` for the best bid/ask, the mid and the venue
   `timestamp`.
5. One `public/get_instruments` + one `public/get_book_summary_by_currency` per
   currency on Deribit, reduced to typed rows, then the frozen model
   `bs_n_d2_markiv_interp_v1`: mark IV interpolated in strike inside each
   bracketing expiry, total variance interpolated in time to the Polymarket
   resolution instant, `P = N(d2)` with the forward from `underlying_price` and
   `r = 0`.
6. Apply the freshness bound `POLYMARKET_CRYPTO_MAX_STALENESS_SECONDS`
   *independently* to the CLOB book timestamp and to the oldest Deribit quote
   used, then append one row per market to `POLYMARKET_CRYPTO_TAPE_PATH`.

Hard constraints (all covered by
`tests/security/test_polymarket_crypto_wedge_boundary.py`):

- `TRADING_MODE` must be `paper`; the CLI refuses to start otherwise.
- Deribit is read-only: two allowlisted public paths, and any path containing
  `private`, `auth`, `buy`, `sell`, `edit`, `cancel` or `withdraw` is refused
  before a request is built. There is no POST anywhere in this path.
- No signing, no private key, no CLOB order placement.
- Rows carry no size, side, notional or limit field. Nothing in the tape can be
  read as an instruction.
- The Crucix status is withhold-only: only a positively known `clear` leaves a
  row eligible for a future trade mask; `adverse`, `unavailable` and
  `not_configured` all stand aside.
- The kill switch is refreshed and printed, but collection is *not* skipped when
  it is engaged: an engaged switch has nothing to withhold here, and skipping
  would silently punch a hole in the tape.

Operator cron (every 15 minutes, from the operator host):

```bash
*/15 * * * * KILL_SWITCH=false TRADING_MODE=paper .venv/bin/traderstack-polymarket-crypto-collect --once
```

Offline, no network, from the committed fixture pack:

```bash
TRADING_MODE=paper .venv/bin/traderstack-polymarket-crypto-collect \
  --fixtures-dir tests/fixtures/polymarket_crypto \
  --tape-path var/audit/polymarket_crypto_wedge_tape.jsonl --json
.venv/bin/traderstack-polymarket-crypto-collect --print-rules   # frozen pre-registration
```

Row statuses:

| `status` | Meaning |
|---|---|
| `ok` | Both venues answered inside the freshness bound; `wedge = poly_mid − deribit_prob` is recorded. |
| `stale_polymarket` | The CLOB book timestamp is missing or older than `POLYMARKET_CRYPTO_MAX_STALENESS_SECONDS`. Recorded, never scored. |
| `stale_deribit` | The oldest Deribit quote used is older than the same bound. Recorded, never scored. |
| `no_two_sided_book` | The book was one-sided, unreadable or unavailable, so there is no mid. Never a zero. |
| `no_option_probability` | The chain could not price this strike: no bracketing expiry inside `POLYMARKET_CRYPTO_MAX_EXPIRY_GAP_HOURS`, a sparse chain (all listed strikes on one side of K), a resolution already past, or an unreachable Deribit. The named reason is in `reasons`. |

Markets that do not parse are counted in the cycle report (`unparsed`) rather
than taped: without a typed asset and strike there is nothing honest to record.

### What this does not claim

- No PnL. No promotion. There is no `PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE`
  setting and this slice ships no path to one.
- The evaluator and the settlement resolver are the next slice; until they
  exist the tape is evidence only.
- Sign convention: `wedge = poly_mid − deribit_prob`. Positive means Polymarket
  is pricing the threshold higher than the option chain implies.
- A Polymarket daily resolves at 16:00 UTC on the Binance 1-minute close while
  Deribit dailies expire 08:00 UTC on the Deribit index. Every row records
  `expiry_gap_hours` and the forward used: this is a *comparable* probability,
  not an identical payoff, and no arbitrage is implied.
- A quota refusal or open circuit breaker shows up as `no_two_sided_book` /
  `no_option_probability` counts and a chain-error line, not as a crash and not
  as a zero.
