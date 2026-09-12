# Evaluation Framework

## Core Principle

The system is not considered successful because it makes money in one backtest. It must demonstrate reproducible risk-adjusted performance against simple baselines after realistic costs.

## Required Stages

### Stage 1 — Historical Backtest
- point-in-time data only
- explicit fees
- slippage model
- realistic latency assumptions
- delistings and missing-data treatment documented

### Stage 2 — Bias Controls
- look-ahead bias checks
- survivorship-bias review
- train/validation/holdout separation
- prompt/model version frozen per experiment

### Stage 3 — Walk-Forward Testing
Repeated out-of-sample windows with no parameter access to future periods.

### Stage 4 — Paper Trading
Run against live market data with simulated execution for a meaningful observation period.

Every paper (and later live) decision additionally passes the **pre-trade backtest gate** (`traderstack.pretrade`): Stages 1 and 3 are re-run on the asset's most recent candle history at decision time, and the proposal is rejected unless the strategy confirms the side and still shows bounded-drawdown, cost-adjusted, out-of-sample edge. This is a continuous self-check, not a substitute for the offline research stages above.

### Stage 5 — Shadow Live
Generate the exact orders the production system would submit, but do not transmit them. Compare theoretical against market outcomes.

### Stage 6 — Tiny-Capital Pilot
Strictly capped capital and risk budget, with immediate rollback capability.

## Baselines

Every strategy must be compared against relevant simple baselines:
- BTC buy-and-hold
- ETH buy-and-hold
- BTC/ETH weighted portfolio
- simple time-series momentum
- simple moving-average trend strategy
- simple mean-reversion strategy
- volatility-targeted benchmark

## Metrics

Primary:
- CAGR / total return
- annualized volatility
- Sharpe ratio
- Sortino ratio
- maximum drawdown
- Calmar ratio
- profit factor
- expectancy per trade

Operational:
- turnover
- fees
- modeled and realized slippage
- fill rate
- rejected-order rate
- stale-data incidents
- provider failures
- LLM cost per decision / per unit PnL

## Attribution

Performance must be decomposed by:
- strategy
- asset
- market regime
- signal source
- model/prompt version
- long/short direction where applicable
- gross return versus fees/slippage

## Promotion Gate

No strategy advances to live capital solely on aggregate returns. Promotion requires acceptable out-of-sample behavior, bounded drawdown, stable attribution, operational reliability and no evidence of data leakage.

## Implemented

The research harness (Epic 5) and the signal registry (Epic 4) are implemented in `src/traderstack/research/` and `src/traderstack/signal_registry.py`.

**Stage 1 — Historical Backtest.** `traderstack.backtest.BaselineBacktester` (unchanged public signature) runs point-in-time only — at each bar it evaluates the strategy ensemble on `candles[:i+1]` and fills on the *next* bar's open, never the bar it decided on. It now also returns, on `BacktestMetrics.trade_log`, an ordered list of `BacktestTrade` records (entry/exit time and price, side, return net of costs, regime at entry, and the contributing strategy ids). Fees and slippage are pluggable via `research.costs.CostModel`: `FlatCostModel` reproduces the original fixed-bps behaviour (the default, so nothing changes unless configured) and `VolumeAwareSlippageModel` grows slippage with order notional relative to the bar's traded volume, capped. Missing-data/delisting handling is inherited from `CandleHistory`/`Candle` validation (strictly increasing timestamps, valid OHLC); this MVP does not yet backtest across delistings.

**Annualisation.** `candles.periods_per_year(interval)` (new, additive) infers bars-per-year from the candle interval label (`1m` … `1w`) instead of assuming daily bars; Sharpe, Sortino, and annualized volatility all use it. `BacktestMetrics` gained Sortino, Calmar, profit factor, expectancy per trade, annualized volatility, turnover, and total fees (all additive fields with defaults, so existing callers are unaffected).

**Stage 2 — Bias Controls.** `research.leakage.assert_no_lookahead` / `assert_no_lookahead_under_shuffled_future` prove `StrategyEnsemble.evaluate` and `CandleMarketFeatureBuilder.build` are pure, point-in-time functions of the window they are given — see `tests/test_research_leakage.py`, which also demonstrates the helper actually catches a deliberately-leaky (stateful) signal function. `research.tuning.grid_search_momentum_lookback` composes with the same helper to prove walk-forward parameter fitting never sees test-window data (`tests/test_walkforward_fit.py`). Train/validation/holdout separation is enforced structurally by `WalkForwardEvaluator`'s fold slicing.

**Stage 3 — Walk-Forward Testing.** `traderstack.walkforward.WalkForwardEvaluator` now accepts an optional `fit` hook (additive field, default `None` = unchanged behaviour): given only the train-window candles, it returns a (possibly parameter-tuned) `BaselineBacktester` to evaluate on the held-out test window. `research.tuning.grid_search_momentum_lookback` is one such hook, grid-searching the momentum lookback on train data only.

**Baselines.** `research.baselines` implements buy-and-hold, simple time-series momentum, a moving-average trend follower, mean reversion, and a volatility-targeted benchmark, all sharing the same simulation engine, cost model, and metrics as the strategy under test (`simulate_positions` in `backtest.py`) — so comparisons are apples to apples. `research.baselines.compare(strategy_metrics, baselines)` returns per-baseline excess metrics.

**Attribution.** `research.attribution.build_attribution_report` decomposes a backtest's trades by contributing strategy, asset, regime, side, and gross return versus fees/slippage, as `AttributionReport`; `render_attribution_table` renders it as plain text. Attribution by model/prompt version is available via `signal_version` (below) once upstream agents populate it on `TradeProposal`; that wiring belongs to Epic 6/7 and is out of this harness's scope.

**Signal registry and versioning (Epic 4).** `signal_registry.version_of(obj)` derives a version string from an object's class name plus a stable hash of its (recursively normalized) constructor parameters, by reflection over frozen dataclasses — no cooperation required from the strategy/ensemble/feature-builder classes themselves. `SignalRegistry` records `name -> version` mappings. `StrategySignal` and `TradeProposal` both gained an optional `signal_version` field (additive, default `None`); `StrategyEnsemble.consensus` populates it on the combined signal it produces.

**Research CLI.** `traderstack-research` (`research/cli.py`) loads candles from a JSON file or live from `KrakenCandleProvider`, runs backtest + walk-forward + baselines + attribution, and prints a table or (`--json`) machine-readable output. Paper-trading candle history (`market/kraken_candles.py`) and `traderstack-download-candles` (`research/download_candles.py`) share Kraken's public Spot OHLC REST endpoint (`GET https://api.kraken.com/0/public/OHLC`, **verified** against `docs.kraken.com/api/docs/rest-api/get-ohlc-data`). The downloader pages forward via `since`/`last`, respecting the documented 720-candles-per-call cap; both paths always drop the trailing not-yet-committed bar.

## Acceptance drills

Stage 4 (Paper Trading) is not "we ran it and nothing crashed". Before a paper run
counts as evidence, the system has to be shown failing *correctly*: the documented
fail-closed behaviour in docs/RISK-PRINCIPLES.md ("Failure behaviour") and
docs/SECURITY-THREAT-MODEL.md ("Failure Policy") has to be observable on demand,
not merely asserted in prose.

Epic 10 turns each of those failure modes into an automated drill. Every drill
drives a real `ContinuousPaperService` — real pipeline, real deterministic risk
engine, real pre-trade gate, real planner/submitter/ledger, real reconcilers, real
hash-chained audit trail — for a bounded number of cycles. The only fakes are the
network edges:

- `src/traderstack/acceptance/market.py` — a seeded synthetic random-walk market
  (candles + ticks). One seed reproduces a run exactly.
- `src/traderstack/acceptance/faults.py` — a fault-injection wrapper for every
  external dependency. Each fault is an object with `arm()`/`disarm()` and a
  counter of how many times it *actually fired*, so a drill asserts the failure
  happened rather than assuming the wiring reached it.

| Drill | File | What it proves |
|---|---|---|
| Forced provider outages | `tests/acceptance/test_provider_outages.py` | One reference down still trades on the other; all references down rejects with `no_independent_reference_price`; candle history down (error or empty) rejects with `missing_candle_history`; intelligence down only degrades the cycle (`intelligence_error` recorded, `no_external_intelligence` when `INTELLIGENCE_REQUIRED`); a hang is a failure, not an answer; the provider circuit breaker opens after `PROVIDER_FAILURE_THRESHOLD` and stops calling the provider; the meta-agent unavailable suppresses the order in veto mode and changes nothing in advisory mode. |
| Forced database restart | `tests/acceptance/test_database_restart.py` | An event-sink outage is counted (`traderstack_event_sink_failures_total`), never swallowed; it resubmits nothing; the portfolio checkpoint keeps advancing; persistence resumes unattended; a permanent outage stops the service. |
| Stale data | `tests/acceptance/test_stale_data.py` | `stale_primary_tick`, `stale_candle_history` and `stale_portfolio_state` each block new risk on their own, and the refusals reach the risk audit trail. |
| Duplicate orders | `tests/acceptance/test_duplicate_order.py` | One decision, at most one venue order — offered twice in-process and again after a restart that reloads the ledger from disk. Also names the one way the guard can be lost: deleting the ledger file. |
| Risk-service failure | `tests/acceptance/test_risk_service_failure.py` | A raising risk engine produces no order, records an error cycle, increments the health counter, writes nothing to the audit trail, and stops the service after `max_consecutive_errors`. |
| Kill-switch drill | `tests/acceptance/test_kill_switch_drill.py` | A sentinel file created mid-run halts the very next cycle with `kill_switch_enabled`, the `traderstack_kill_switch_engaged` gauge flips, `traderstack-resume` releases it and trading resumes; halted cycles are still audited; SIGUSR1 halts and deliberately cannot be cleared in-process. |
| Reconciliation drift | `tests/acceptance/test_reconciliation_drift.py` | NAV drift and order-state conflicts block *submission only* — decisions, sizing and auditing continue — and the block clears only after a fully clean pass. |
| Audit integrity | `tests/acceptance/test_audit_integrity.py` | After a run the hash chain verifies, every submitted order maps to both a risk-audit record and a runtime event, the chain survives a restart, and an edited or removed line fails verification. |

### Soak runs

`traderstack-soak` runs the same wiring for `--cycles N` or `--seconds T`, optionally
following a JSON scenario that arms and disarms faults at chosen cycles
(`ops/soak/scenarios/{ci,baseline,provider_outage,kill_switch_drill}.json`), and always
writes a machine-readable acceptance report to `<workdir>/report.json`: schema version,
cycles, outcomes by rejection reason, risk decisions, orders/receipts/ledger states,
reconciliations, faults fired, provider breaker states, health, audit-chain verification,
a Prometheus snapshot, and `full_24h_window_executed` (true only when a ≥86400s request
actually ran that long). `--preset ci` is the short CI/smoke path; `--preset full` is
the 24-hour window. Operator procedure and pass criteria: docs/RUNBOOK.md, "24/7
acceptance soak". The 24-hour window itself has not been executed in this repository.

### Paper performance versus baselines

`traderstack-paper-report` (`src/traderstack/acceptance/report.py`) closes the loop
between a paper run and the Baselines section above. It reads the runtime audit JSONL
and the execution ledger, reconstructs the paper equity curve and FIFO round trips,
scores them with the *same* `BacktestMetrics` statistics the research harness uses (so
the numbers are safe to subtract), runs `research.baselines` over the same period's
candles, and prints the excess per baseline plus the `research.attribution` report.

Two honesty constraints are built in: nothing is inferred that the audit trail does not
record — paper receipts carry no fees, so fees are zero unless `--fee-bps` explicitly
estimates them, and the report says so — and orders that were submitted but never
reconciled to a fill are excluded rather than assumed to have traded.

**Not yet implemented:** Freqtrade research integration, survivorship-bias review,
and the tiny-capital-pilot stage (6). Shadow-live (stage 5) now has a runtime
(`TRADING_MODE=shadow`) that records would-have-been orders; the statistical
comparison campaign against paper/reality is still an operator activity.

## Polymarket weather — validation A/B

`traderstack-polymarket-weather-paper` records *hypotheses* (model probability
vs CLOB mid). It does not demonstrate a durable edge. Treat any external claim
of a high weather-market win rate (often quoted without fees, without a
resolution-station match, and without a holdout) as marketing until the gates
below pass on *this* ledger.

### Why skepticism is the default

- Polymarket weather markets are short-dated binary/bucket contracts. A few
  lucky days dominate a small sample.
- NWP highs are not the same random variable as the market's official
  observation station / rounding / timezone / "as of" cutoff.
- CLOB mid is not a fill. Spread + taker fees + depth routinely erase a
  5–10¢ "edge".
- `POLYMARKET_WEATHER_SIGMA_F` (default 2.5°F) is an operator prior, not a
  calibrated CRPS/skill score for that city and lead time.
- Selection: only parsed, allowlisted, liquid-looking markets enter the
  ledger. That is not a random sample of weather contracts.

### Required A/B before anyone talks about promotion

Run these as a research notebook / offline job against the paper ledger plus
an independent resolution series. This module does **not** implement them
yet — that is intentional. Shipping a calculator is not shipping a validated
strategy.

| Gate | Treatment (A) | Control (B) | Pass rule (pre-registered) |
|---|---|---|---|
| 1. Historical point-in-time | Intents that would have fired using only forecasts + mids available *before* market close | Always-pass / fade-the-mid / random side at the same notional | A excess vs B after fees+spread, p-value / CI pre-declared, n large enough for the horizon |
| 2. Walk-forward | Fit `MIN_EDGE`, `SIGMA_F`, haircut on train folds only | Frozen defaults from fold 0 | Mean OOS excess > 0 after costs; no fold may peek at later resolutions |
| 3. Paper A/B (live data, no orders) | Current edge rule → `would_trade` rows | Same markets, shuffled side or "always hold" | Compare *resolved* PnL of A vs B over ≥ one full season per city, not one heat wave |
| 4. Station match | Same | Same | Drop any market whose resolution metadata (ASOS id, midnight-to-midnight local, °F rounding) cannot be paired to the NWP series used at decision time |
| 5. Cost honesty | Mid ± half-spread − documented Polymarket taker fee | Fill at mid (forbidden as a primary metric) | Report both; promotion uses the conservative one |

Until gates 1–5 are green, the only allowed statement is: "the paper ledger
contains would-trade intents." Do not add a live CLOB path as a side effect
of a later change.
