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

**Research CLI.** `traderstack-research` (`research/cli.py`) loads candles from a JSON file or live from `KrakenCandleProvider`, runs backtest + walk-forward + baselines + attribution, and prints a table or (`--json`) machine-readable output. `traderstack-download-candles` (`research/download_candles.py`) pages Kraken's public Spot OHLC REST endpoint (`GET https://api.kraken.com/0/public/OHLC`, **verified** against `docs.kraken.com/api/docs/rest-api/get-ohlc-data`) forward via `since`/`last`, respecting the documented 720-candles-per-call cap, and always drops the trailing not-yet-committed bar.

**Not yet implemented:** Freqtrade research integration, on-chain/social/narrative feature pipelines, news/event classifier, regime classifier v1 (the existing `RegimeClassifier` is a simple MVP version, not the Epic 4 deliverable), survivorship-bias review, and shadow-live/tiny-capital-pilot stages (5–6).
