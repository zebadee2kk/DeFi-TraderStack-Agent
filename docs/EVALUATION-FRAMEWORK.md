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

**Strategy search and paper-voter promotion.** `traderstack-strategy-search` (`research/search_cli.py`) is the batch loop that *discovers* which standalone catalog members have fee-aware walk-forward **total** return — it does not assume the baseline MA ensemble has edge, and beating buy-and-hold while still losing money is not an edge. Catalog (pre-registered): MA-cross / momentum / mean-reversion plus vol-regime-agree wrappers; optional funding-z / OI-z / liquidation-z / cross-venue voters only when an aligned series is supplied (those features are not on the Kraken Spot OHLC paper path and are skipped, not zero-filled, when public REST cannot build a historical series). History: public Spot OHLC is capped at 720 bars (`since` pages forward only); the charts-spot `PI_*` path is used for ~90–180d 1h. Costs are `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` plus `PRETRADE_SLIPPAGE_BPS`. Ranking uses walk-forward folds on the research prefix only; the holdout tail is scored after ranking. Multiple-testing policy is pre-registered top-1 (Bonferroni analogue: one promotion decision over K looks, documented in the report; no invented p-values). A candidate may register as a paper voter only when `PAPER_PROMOTE_SEARCHED_STRATEGIES=true` **and** `PAPER_PROMOTE_SEARCHED_STRATEGY_ID` matches that id **and** the report still shows WF mean total return > 0 after fees, min trades, and (default) holdout excess > 0. Default of the flag is false. If nothing clears, the report says so and promotion stays off — this is not rewritten as an edge. `docs/artifacts/strategy-search/` holds the committed report.

**Miles-inspired catalog (`traderstack-miles-search`).** EMA 9/21 and 12/26 direction (optional ADX>threshold chop gate) composed with a walk-forward GARCH(1,1) size overlay (`target_vol / forecast_vol` clipped to [0.25, 2.0]). GARCH never chooses a side. Costs are `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` plus `PRETRADE_SLIPPAGE_BPS`. Ranking uses the research prefix only. Promotion requires fee-aware walk-forward **mean total return > 0** and holdout **mean excess return > 0** (same honesty bar as the #89 paper search: beating a falling buy-and-hold while still losing money is not an edge). Default `PAPER_GARCH_SIZE=false`. When that flag is on, `RiskEngine` may only *reduce* notional from the GARCH forecast. The documented paper-voter switch is `PAPER_PROMOTE_EMA_9_21` (default false): when `TRADING_MODE=paper` it registers **only** the pre-registered daily winner `ema_9_21`, suppresses the unpromoted defaults, and forces paper candle ingestion / feature bars / the pre-trade backtest to daily (`1d` / Kraken 1440) so the runtime cannot silently evaluate that voter on 1h bars. The pre-trade drawdown ceiling on that path is `PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` (default 0.30) applied to research walk-forward maxDD (train=180 / test=60 / step=60, warmup=train), not to full-history backtest DD (ETH ~43% on 400 daily bars vs WF 28.77%). Lookback is forced to 720. The 1h `PRETRADE_MAX_DRAWDOWN_PCT=0.15` bar still compares the full-history book. It does not enable live. Do not claim the daily edge on a 1h runtime. Report: `docs/artifacts/strategy-search/miles-inspired-report.md`.

**Daily robustness (`traderstack-daily-robustness`).** Re-scores a pre-registered daily catalog on the longest Kraken public Spot **daily** window (`GET /0/public/OHLC`, **720-bar cap ≈ 2y**; `since` pages forward only). Default catalog (`--catalog balanced`): `ema_9_21` / `ema_12_26` / slower `ema_20_50` / `ema_50_200`, ADX gates, a frozen dual-mom lookback grid, buy-the-dip z grid, asset-local and BTC-overlay SMA200 risk-off, and two GARCH size overlays. `--catalog legacy` is the frozen #95 K=8 list. Optional Yahoo Finance `BTC-USD` / `ETH-USD` daily is a longer **non-Kraken** A/B and is never averaged into the promotion decision. Ranking uses Kraken BTC+ETH only. SOL is reported and is not required to promote. The #95 bar required BTC **and** ETH walk-forward mean total return > 0 after fees, min trades, and holdout **mean** excess > 0. The default **balanced-holdout** bar keeps that **and** requires BTC holdout excess > 0 **and** ETH holdout excess > 0 so an ETH tail cannot carry a losing BTC holdout. Reports both PASS/FAIL lines for `ema_9_21`. Does not flip `PAPER_PROMOTE_*` or `PAPER_GARCH_SIZE`. Report: `docs/artifacts/strategy-search/balanced-holdout-report.md` (the #95 window remains in `daily-robustness-report.md`).

**Harder honesty gates (`traderstack-harder-gates`).** Same Kraken daily 720-bar cap, with three gates pre-registered before scoring: **A** magnitude (`min/max` BTC vs ETH holdout excess ≥ 0.25, both signs > 0); **B** three contiguous 240-bar windows requiring BTC **and** ETH WF total > 0 in at least 2 of 3 (each window uses train=180/test=60 and no in-window holdout); **C** 2× fees (20+10 bps) must still clear #96 balanced signs. Default catalog is the frozen **expanded** post-#97 grid (more ADX, faster/slower EMAs, SMA200 variants, dual-mom, dip+vol); `--catalog balanced` / `legacy` remain. Yahoo remains A/B only. Ranking key (frozen before scoring): **mean holdout excess among combined-passers** (Kraken BTC+ETH). Combined = #96 **and** A **and** B **and** C; top-1 of that passer set may be documented as a paper-only pin. A non-passer is never promoted. Walk-forward rank of the full catalog is informational and cannot block a passer. Does not flip `PAPER_PROMOTE_EMA_9_21`. An empty promotee is success. On the committed 2026-09-12 Kraken window the expanded catalog's combined-passer top-1 was `ema_9_21_adx15`; the documented paper-only pin is `PAPER_PROMOTE_EMA_9_21_ADX15` (default false). Reports: `docs/artifacts/strategy-search/magnitude-multiwindow-report.md` (#97) and `docs/artifacts/strategy-search/expanded-harder-gates-report.md`.

**Honesty pack (`traderstack-honesty-pack`).** Focused reprint for one combined-passer (default `ema_9_21_adx15`): confirm the Kraken combined row is still top-1, score Yahoo Finance daily A/B for **that** id only (`period1`/`period2`; labeled non-Kraken; cannot promote), compare WF maxDD on BTC/ETH/SOL to the paper DD ceiling 0.30, and reprint the gate-B multi-window table. Empty or negative Yahoo is success. Never flips `PAPER_PROMOTE_EMA_9_21_ADX15`. The paper promote path aligns the **trading universe** to `PAPER_PROMOTE_UNIVERSE` (default `BTC/USD,ETH/USD`) so SOL is not cycled under that envelope (`promote_universe_excluded`). That is universe alignment, not a claim of edge. Report: `docs/artifacts/strategy-search/ema-9-21-adx15-honesty.md`.

**Second print (`traderstack-second-print`).** Closes the #100 gap of a single Kraken 720-bar window. Slice rules are frozen before scoring: Kraken public OHLC cannot unlock a second 720 (`since` pages forward only); the Kraken-compatible path is the holdout-blind prefix (same venue, not independent; gate B fails closed if shorter than 720). The independent print is Binance Spot daily BTCUSDT+ETHUSDT, 720 committed bars ending strictly before the primary Kraken first bar. `api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled Binance.US, not Binance.com. Same strategy definition and #96+A+B+C gates; fees are paper-research 10+5 (gate C 20+10). Labeled non-Kraken / report-only; a multi-venue bar is **not** pre-registered, so a Binance combined-pass cannot enter the promotion average and cannot flip `PAPER_PROMOTE_EMA_9_21_ADX15`. An honest FAIL is success. Report: `docs/artifacts/strategy-search/ema-9-21-adx15-second-print.md`.

**Dual-print search (`traderstack-dual-print-search`).** Continues after #102: the dual-print bar is **pre-registered** before scoring. Catalog is a frozen superset of the #99 expanded grid (more EMA/ADX, SMA risk-off, dual-mom, dip+vol, candle-only vol-regime wrappers; liquidation/funding/OI skipped when no aligned series). A name must combined-PASS #96+A+B+C on the Kraken primary 720 **and** on the same #102 Binance.US older-720. Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Binance holdout is a gate; venues are not averaged. A Kraken-only combined-passer cannot promote. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/dual-print-search.md`.

**Liquidation / regime-conditioned search (`traderstack-liq-regime-search`).** Pivot after the empty #104 dual-print EMA catalog. Frozen core: six vol-regime-agree price voters plus three unconditioned controls. Optional liquidation-z / funding-z / OI-z / cross-venue families instantiate only when an aligned historical series is supplied (not zero-filled). Public USDT-M liquidation REST is typically unusable; live WS `!forceOrder@arr` and bookTicker are paper-cycle research context, not a backtest input. Dual-print requires historical liquidation series on BTC and ETH **and** a second venue candle print. Otherwise the run is labeled **single-print** and **cannot promote**. Ranking is informational. Never flips `PAPER_PROMOTE_*`. Empty search is success. Crucix → `adverse_event` was already wired as a news veto and is unchanged. Report: `docs/artifacts/strategy-search/liq-regime-search.md`.

**Intraday dual-print search (`traderstack-intraday-dual-print`).** Continues after empty daily EMA (#104), empty liq (#105), and empty Polymarket PIT (#106). Frozen **non-EMA** catalog (MA / momentum / mean-reversion / vol-regime; two EMA names as informational controls). Funding-z / OI-z instantiate only when an aligned historical series is fetched; liquidation-z and cross-venue stay skipped. Same #96+A+B+C combined gates on Kraken public Spot **4h** (default; `1h` alternate; 720-bar cap) **and** the #102-style Binance.US older-720 of the same interval. Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/intraday-dual-print.md`.

**Funding / carry search (`traderstack-funding-carry`).** Continues after empty #104/#105/#106/#108. Frozen catalog: funding-z fade/follow at |z|≥1.0 / 1.5 / 2.0, `ema_9_21` / `momentum_12` funding-agree overlays, hedged cash-and-carry (always-on, |rate|≥1bp / 3bp, |z|≥1.5), plus informational `ma_cross_10_30`. Dual-print requires two independent **funding** venues on BTC+ETH (e.g. Hyperliquid and HTX). BitMEX is a sunset venue (official closure 23 September 2026 04:00 UTC) and is not selected. Binance (often HTTP 451) and Bybit (often HTTP 403) are probed and skipped, not invented. One venue is **single-print** and **cannot promote**. `--interval 1d` resamples funding to UTC daily sums (empty days omitted) so #96+A+B+C can be evaluated or recorded UNAVAILABLE; a ~90d OKX tape cannot unlock them. HTX public settlements (`funding_rate` only, never `avg_premium_index`) can fill ≥720 UTC daily sums. Hard gates need 720 aligned daily bars on **each** participating venue. Hedged carry PnL is received |funding| minus two-leg fees; perp-spot basis is skipped unless a PIT mark−index / perp-mid−spot-mid series is supplied on **both** dual-print venues for the scored window (Hyperliquid funding premium and BitMEX `.XBTUSDPI` are not basis). A paper hedge+funding soak path is cycle-wired (`execution/paper_perp.py` + `execution/paper_perp_feed.py`; `PAPER_PERP_HEDGE` default false). The cycle fetches an explicit Hyperliquid `midPx` (HTX bid/ask mid fallback; BitMEX not required) and applies same-venue public funding settlements. Kraken spot mid is never a substitute. Current snapshot mids are not a historical PIT series and are not written into research scoring. `PAPER_CARRY_PATH_READY` is true for that soak; `can_promote` stays false while PIT basis is UNAVAILABLE. Public historical archives: HuggingFace `asiletto81/hyperliquid` `asset_ctxs` is a ≥720d HL mark−index tape ending 2026-06-01 (~617d on the current Kraken 720); official HL S3 stays requester-pays 403; BitMEX dumps still have no mark tape and the venue is closing — see `docs/artifacts/strategy-search/pit-basis-archives.md`. A Settings pin requires dual-print + hard gates + PIT basis + a paper-executable path. Ranking is informational. Never flips `PAPER_PROMOTE_*`. Empty / cannot-promote is success. Reports: `docs/artifacts/strategy-search/funding-carry.md`, `docs/artifacts/strategy-search/funding-carry-daily.md`, `docs/artifacts/strategy-search/funding-carry-basis.md`, `docs/artifacts/strategy-search/pit-basis-archives.md`, `docs/artifacts/strategy-search/edge-status-2026-09-12.md`.

**BTC−ETH relative-value residual (`traderstack-relative-value`).** Continues after #115: PIT basis archives stay UNAVAILABLE, so carry cannot promote. This is a **different family** — not another EMA dual-print and not a carry reprint. Frozen catalog: fade/follow daily close-to-close excess `r_BTC − r_ETH` at |z|≥1.0 / 1.5 / 2.0 (lookback 20), plus informational `ma_cross_10_30` (cannot enter the passer set). ETH is bound to the negated residual. A missing pair day is skipped, not zero-filled. Same pre-registered #96+A+B+C dual-print bar as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/btc-eth-relative-value.md`.

**Cross-sectional momentum (`traderstack-xs-momentum`).** Continues after #116: the BTC−ETH residual dual-print was empty (every Kraken RV holdout negative). This is a **different family** — not another EMA dual-print, not a residual retune, and not invented basis. Frozen catalog: long top-1 / optional short bottom-1 among {BTC, ETH, SOL} by trailing N-day return (N in {21, 63, 126}), dollar-neutral (`ls`) or long-only (`lo`), optional vol-scaled ranking (return / sample vol, not a size overlay), plus informational `ma_cross_10_30` (cannot enter the passer set). A ranking day requires all three venue-local closes; a missing asset day is skipped, not ranked on a two-asset subset. Multi-asset combined bar (frozen before scoring): same #96+A+B+C on **BTC and ETH**; SOL is reported and is not a gate. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD+SOL/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/cross-sectional-momentum.md`.

**Donchian / channel breakout (`traderstack-donchian-breakout`).** Continues after #117: the BTC+ETH+SOL cross-sectional dual-print was empty (informational `xs_mom_lo_vol_63` was ETH-carried / #96 FAIL). This is a **different family** — not another EMA dual-print, not a residual or XS lookback retune, and not invented basis. Frozen catalog: long-only (`donchian_lo_{20,55,100}`) and long/short (`donchian_ls_{20,55,100}`) on the prior N-day high/low, ATR-buffered long-only (`donchian_lo_atr_{20,55}`; Wilder ATR 14 × 1.0 through t−1), plus informational `ma_cross_10_30` (cannot enter the passer set). Decision at bar t uses the prior channel (bars `[t-N, t)`; bar t's high/low never set the breakout level). Exit is `opposite_band_same_n`. Fill at t+1 open. A missing/short series is skipped, not zero-filled. Multi-asset combined bar (frozen before scoring): same #96+A+B+C on **BTC and ETH**; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/donchian-breakout.md`.

**Time-series momentum (`traderstack-tsmom`).** Continues after #118: the Donchian / channel-breakout dual-print was empty (informational positive Kraken mean HO still failed #96 on BTC walk-forward). This is a **different family** — not another EMA dual-print, not a residual / XS / Donchian retune, and not invented basis. Frozen catalog: long-only (`tsmom_lo_{21,63,126,252}`) and long/short (`tsmom_ls_{21,63,126,252}`) on each asset's own trailing N-day close-to-close return, plus informational `ma_cross_10_30` (cannot enter the passer set). Vol-scaled sign variants omitted (`sign(return/vol)` equals `sign(return)` when vol > 0; a size overlay is out of scope). Decision at bar t uses closes through t (`close[t] / close[t−N] − 1`). Fill at t+1 open. A missing/short series is skipped, not zero-filled. Multi-asset combined bar (frozen before scoring): same #96+A+B+C on **BTC and ETH**; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/tsmom.md`.

**Bollinger band-fade / mean-reversion (`traderstack-bollinger-fade`).** Continues after #119: the TSMOM dual-print was empty (informational ETH-carried #96 FAIL and BTC walk-forward fails). This is a **different family** — not another EMA dual-print, not a residual / XS / Donchian / TSMOM retune, and not invented basis. Distinct from existing `mean_reversion_*` catalog ids (#93 charts-spot / #108 4h). Frozen catalog: fade-to-inside (`bb_fade_{20x2,20x2_5,40x2}`), long-only fade (`bb_lo_fade_{20x2,40x2}`), squeeze-breakout CONTRAST (`bb_squeeze_break_{20,40}`; expand from p20 of the prior 120 bandwidths, long above mid), plus informational `ma_cross_10_30` (cannot enter the passer set). Bands are SMA(period) ± k × sample stdev (ddof=1) using closes through t. Exit is `flat_when_inside_bands` (not exit-at-mid). Fill at t+1 open. A missing/short series is skipped, not zero-filled. Multi-asset combined bar (frozen before scoring): same #96+A+B+C on **BTC and ETH**; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/bollinger-fade.md`.

**Calendar seasonality (`traderstack-calendar-seasonality`).** Continues after #120: the Bollinger band-fade dual-print was empty (informational `bb_squeeze_break_40` cleared Kraken #96+A+B but failed gate C). This is a **different family** — not another EMA dual-print, not a residual / XS / Donchian / TSMOM / Bollinger retune, and not invented basis. Frozen catalog: UTC day-of-week long-only (`cal_dow_lo_{mon,fri,mon_fri}`), skip-weekend (`cal_dow_skip_weekend`; long Mon–Fri UTC), month-of-year long-only (`cal_moy_lo_{q4,jan,nov_dec}`), turn-of-month (`cal_tom_lo_3_3`; last 3 / first 3 UTC calendar days via `calendar.monthrange`), plus informational `ma_cross_10_30` (cannot enter the passer set). Timezone is UTC. Decision uses the UTC civil date of bar t only (prices ignored). Fill at t+1 open. A missing/short series is skipped, not zero-filled. Multi-asset combined bar (frozen before scoring): same #96+A+B+C on **BTC and ETH**; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/calendar-seasonality.md`.

**BTC→ETH lead-lag (`traderstack-lead-lag`).** Continues after #121: the calendar seasonality dual-print was empty (every Kraken mean HO negative). This is a **different family** — not another EMA dual-print, not a residual / XS / Donchian / TSMOM / Bollinger / calendar retune, and not invented basis. Not same-bar residual z-score on `r_BTC − r_ETH` (#116). Frozen catalog: ETH follows lagged BTC long-only (`leadlag_eth_follow_lo_{1,2,3,5}`), ETH follows lagged BTC long/short (`leadlag_eth_follow_ls_{1,2,3}`), ETH fades lagged BTC long-only (`leadlag_eth_fade_lo_{1,2,3}`), BTC follows lagged ETH long-only mirror (`leadlag_btc_follow_lo_{1,2}`), plus informational `ma_cross_10_30` (cannot enter the passer set). Decision at bar t uses the lead asset's L-day close-to-close return through t (`lead_close[t] / lead_close[t−L] − 1`; L ≥ 1). When trading ETH, same-bar ETH does not enter the gate. Fill at t+1 open of the traded asset. Unpaired BTC/ETH days are skipped, not zero-filled. Multi-asset combined bar (frozen before scoring): every name produces both BTC and ETH books; the other leg is **flat**; combined #96+A+B+C still requires both legs. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/lead-lag.md`.

**Volume-confirmed breakout (`traderstack-volume-breakout`).** Continues after #122: the BTC→ETH lead-lag dual-print was empty (informational `leadlag_eth_follow_lo_5` was ETH-carried / #96 FAIL). This is a **different family** — not another EMA dual-print, not a residual / XS / Donchian / TSMOM / Bollinger / calendar / lead-lag retune, and not invented basis. Not a Donchian N retune (#118): every promote-eligible name requires a volume gate. Frozen catalog: long-only volume-confirmed breakout (`volbrk_lo_{20x1_5,55x1_5,20x2}`), long/short symmetric (`volbrk_ls_{20x1_5,55x1_5}`), volume-surge long-only (`volsurge_lo_{20x2,20x2_5}`), plus informational `ma_cross_10_30` (cannot enter the passer set). Prior channel uses bars `[t-N, t)` (bar t's high/low never set the breakout level). Volume SMA through t−1 (V frozen at 20). Missing volume skips that bar (never invented); quote volume is not a substitute. A venue without usable base volume fails closed for volume names. Exit is `opposite_band_same_n` (long-only exit does not require volume). Fill at t+1 open. A missing/short series is skipped, not zero-filled. Multi-asset combined bar (frozen before scoring): same #96+A+B+C on **BTC and ETH**; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. Same pre-registered dual-print prints as #104: Kraken public Spot daily 720 **and** the #102 Binance.US older-720 (non-overlapping). Ranking key (frozen): Kraken BTC+ETH mean holdout excess among dual-print passers. Venues are not averaged. A Kraken-only combined-passer cannot promote. Paper-executable on Kraken spot BTC/USD+ETH/USD. Empty dual-print set is success. Never flips `PAPER_PROMOTE_*`. A new paper pin is added only if a committed report names a passer, and then default false. Report: `docs/artifacts/strategy-search/volume-breakout.md`.

**Ensemble trend (`traderstack-ensemble-trend`, #137).** Pre-registers the Zarattini / Pagani / Barbon multi-lookback Donchian-on-close rules as a dual-print family on a frozen top-20 point-in-time Kraken universe: nine close-only lookbacks {5..360} each with a trailing stop at max(prior stop, prior close-channel midpoint), equal-weight across open lookbacks, 25% annualised vol target on 90-day realised vol, long-only, capped at 1.0 (no leverage). Not a #118 Donchian N retune. Universe membership is a monthly point-in-time snapshot (≥ 365 prior bars or 720-cap; median 30-day close×volume ≥ $2M; top-20); non-members are forced flat; the Kraken window is survivorship-biased and the report header says so. Fees from the frozen Kraken Pro tier table (default tier 1 = 80 bps taker per side; gate C doubles). Same #96+A+B+C bar on Kraken public daily 720 **and** the #102 Binance.US older-720; BTC and ETH gate, SOL reported; ranking is Kraken mean holdout excess among dual-print passers. Attribution by asset and by lookback is gross and informational. `era_prints_available=false` and `dsr_pbo_available=false` until #133 / #135 land — never invented. The harness gained one opt-in field, `SearchCandidate.weight_from_score` (default false, |weight| ≤ 1), so every prior catalog still trades at ±1. Paper path: `EnsembleTrendVoter` emits BUY with score in (0, 1] or none, never SELL; RiskEngine can only reduce. Never flips `PAPER_PROMOTE_*`; adds no Settings field. Empty dual-print set is success. Report: `docs/artifacts/strategy-search/ensemble-trend.md`.

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
| Forced provider outages | `tests/acceptance/test_provider_outages.py` | One reference down still trades on the other; all references down rejects with `no_independent_reference_price`; candle history down (error or empty) rejects with `missing_candle_history`; optional intelligence down only degrades the cycle (`intelligence_error` recorded, `no_external_intelligence` when `INTELLIGENCE_REQUIRED`); Crucix opted-in outage is fail-closed (`intelligence_provider_unavailable`, covered in unit/security tests); a hang is a failure, not an answer; the provider circuit breaker opens after `PROVIDER_FAILURE_THRESHOLD` and stops calling the provider; the meta-agent unavailable suppresses the order in veto mode and changes nothing in advisory mode. |
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
record — fees come from the execution ledger (venue-reported or `PAPER_FEE_BPS`-modelled
when the venue reports none) and `--fee-bps` is only a fallback for fills that still
carry no fee, and the report says which it used — and orders that were submitted but
never reconciled to a fill are excluded rather than assumed to have traded.

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

`traderstack-polymarket-weather-eval` is the report-only calculator for
gates **1, 4 and 5**. It scores a pre-registered city allowlist (the #44
warm/stable set) plus an optional crypto overlay
(`polymarket_weather_vs_btc_daily`) that is skipped unless an aligned BTC
daily close series is supplied. Primary PnL is conservative (mid ±
half-spread − documented taker-fee haircut). Mid-fill is reported and
cannot promote. Dual independent prints are pre-registered
(`MULTI_PRINT_BAR_PREREGISTERED=true`): non-overlapping `event_date`
sets, or overlapping dates with disjoint resolution sources. A single
print cannot promote even if treatment excess is positive. This CLI
never writes a `PAPER_PROMOTE_*` pin.

This repository has **no** public point-in-time CLOB mid + official
station-high tape. `--empty-live` (empty print, cannot promote) is the
honest live outcome. Fixture packs in `tests/fixtures/polymarket/` prove
the calculator; they are not a live season and cannot promote.

**Still not claimed:** gate 2 (walk-forward fit of `MIN_EDGE` / `SIGMA_F`
/ haircut on train folds) and gate 3 (a full season of live paper A/B
per city). Until those are green on two independent prints, the only
allowed statement remains: "the paper ledger contains would-trade
intents; the eval CLI can score resolved rows when they exist." Do not
add a live CLOB path as a side effect of a later change.

## Selection-bias evidence: era prints, DSR, PBO (#135)

The search harness ranked top-1 across a catalog of `K` trials, wrote a
Bonferroni note, and required **two venue prints** before calling a name
a passer. Both halves of that were weaker than they looked.

Two venues over the **same two years** are not two independent
observations. Kraken and Coinbase BTC-USD are near-identical tapes; the
second venue mostly re-prices the same bars. And a Bonferroni note that
ignores the *variance* of the trial Sharpes cannot say either how much a
winner was inflated by the search, or how strong a real winner is.

The binding constraint turns out to be the **window, not the catalog**.
The standard error of an annualised Sharpe is

```
SE(SR) ~= sqrt((1 + SR^2 / 2) / T_years)          # Lo (2002)
```

so at `T = 2` years:

| annual SR | SE  | t-stat | years needed for t = 2 |
| --------: | --: | -----: | ---------------------: |
| 0.50 | 0.750 | 0.67 | 18.0 |
| 0.75 | 0.800 | 0.94 |  9.1 |
| 1.00 | 0.866 | 1.15 |  6.0 |
| 1.50 | 1.031 | 1.46 |  3.8 |
| 2.00 | 1.225 | 1.63 |  3.0 |

No plausible crypto Sharpe clears `t = 2` on a two-year window. That is
why every strategy family reads as zero — enlarging the catalog cannot
fix it, and neither can a second venue over the same bars. Every search
report now carries this table, computed at that run's own window length
(`research.overfitting.power_table`).

### Pre-registered print policy

`src/traderstack/research/era_prints.py`. A second independent print is
either

* a second **venue** over the same window (unchanged, still valid), or
* a second **era** — a non-overlapping calendar window on the *same*
  venue. Pre-registered eras, frozen before any score, half-open UTC:
  `2016-2019`, `2020-2022`, `2022-2024`, `2024-2026`. An era counts as
  covered only with at least 240 committed bars in it (one #96
  train+test block).

Every report now **names which kind of print it used**: `venue`, `era`,
`venue+era`, or `single`. A `single` print cannot claim an independent
confirmation and withholds the evidence gate for every candidate in the
run. Moving, re-cutting or adding an era after seeing a score is
retuning: change the tuple in version control, with a note, first.

### Deflated Sharpe Ratio

`src/traderstack/research/overfitting.py`, vendored in pure Python (no
numpy/scipy/pandas, no new dependency — the normal CDF is `math.erf` and
its inverse is Acklam's rational approximation plus one Halley step,
unit-tested against published quantiles).

* **PSR** — Bailey & López de Prado, *The Sharpe Ratio Efficient
  Frontier*, Journal of Risk 15(2), 2012, eq. (3).
* **Expected maximum Sharpe over N trials** and **DSR** — Bailey &
  López de Prado, *The Deflated Sharpe Ratio*, JPM 40(5), 2014
  (SSRN 2460551), eq. (5). `DSR = PSR(E[max SR_n])`, with
  `E[max SR_n] ~= sqrt(V[SR_n]) * ((1 - gamma) * Phi^-1(1 - 1/N) + gamma
  * Phi^-1(1 - 1/(N e)))`.

DSR takes the trial count, the **variance of the trial Sharpes**, the
skew and raw kurtosis of the return sample, and the sample length. It is
reported alongside the raw Sharpe, never instead of it. A strategy can
pass raw Sharpe and fail DSR — that is the point, and
`tests/test_selection_evidence.py::test_a_candidate_can_pass_raw_sharpe_and_fail_the_dsr_gate`
pins exactly that case.

### Probability of backtest overfitting

CSCV — Bailey, Borwein, López de Prado & Zhu, *The Probability of
Backtest Overfitting*, JCF 20(4), 2016. The fold-return matrix (rows =
time slices, columns = trials) is cut into `S` equal, disjoint,
contiguous blocks; over all `C(S, S/2)` in-sample/out-of-sample splits,
PBO is the share whose in-sample winner lands below the out-of-sample
median. It is exhaustive, so it has no seed and reproduces exactly.

PBO is reported **per catalog**, so "0 passers" and "1 passer with PBO
0.6" are now distinguishable outcomes rather than the same line in a
report.

### Trade-count floor by bootstrap

The fixed `min_trades` floor is replaced by the count a percentile
bootstrap CI on expectancy needs in order to exclude zero at the stated
confidence (default 95%), found by a doubling bracket and a bisection,
each size evaluated from its own `random.Random(seed)`. An analytic
cross-check `n > (z s / |mu|)^2` is reported next to it.

The bootstrap **can only raise** the floor:
`effective_min_trades = max(configured_min_trades, required_trades)`.
No configured threshold is ever lowered by it.

### Observation unit — stated plainly

Search reports strip per-bar and per-trade logs, so the finest return
sample that survives into a report is the **walk-forward fold**: one net
total return per fold per promotion asset, stacked BTC → ETH → SOL.
Every statistic above runs on that sample and every report names the
unit (`observation_unit: walk_forward_fold`). The trade-count floor is
found in fold units and scaled to trades by the observed trades-per-fold,
with both numbers reported so the conversion is visible rather than
implied. A series that is missing, skipped, or produced no walk-forward
is left out of the sample entirely — **never zero-filled**.

### Reporting order

Every `traderstack-*-search` report renders the evidence block in this
order, and the JSON carries the same fields under `selection_evidence`:

1. **print kind** (`venue` / `era` / `venue+era` / `single`) and why
2. **trial count** `K`, and how many trials had a usable return sample
3. **observation unit**
4. **PBO** for the catalog, with the split count and combination count
5. **bootstrap** seed, iteration count and confidence level
6. **evidence passers** (an empty set is a successful result)
7. per-candidate table: observations, trades, annualised Sharpe, **DSR**,
   **bootstrap CI on Sharpe**, **bootstrap CI on expectancy**, effective
   trade floor, and the gate verdict
8. **era coverage** of the primary venue's series
9. the **power table** at this run's window length

### Where the gate sits

DSR, PBO, the bootstrap CIs and the trade floor are **additional** gates
layered on top of #96 + A + B + C. They are computed in the shared
scoring path (`research.harder_gates.run_harder_gates`) and can only
**withhold**: a combined-passer that cannot show them is not promoted,
and nothing is promoted in its place. They never lower a threshold,
never flip a `PAPER_PROMOTE_*` default, and never turn a name that
failed #96/A/B/C into a passer. A statistic that cannot be computed is
reported as skipped **with a reason** and withholds the gate — absent
evidence is never read as a pass.

Thresholds (`research.selection_evidence`, frozen in version control and
deliberately **not** `Settings` fields, because a bar an operator can
move after seeing PnL is not a pre-registered test): `DSR_MIN = 0.95`,
`PBO_MAX = 0.50`, bootstrap seed 135, 2000 iterations, 95% percentile
CIs.

### Determinism

Every bootstrap draws from an explicit `random.Random(seed)` created
inside the call; the global RNG is never touched (pinned by
`tests/test_overfitting.py` and `tests/test_selection_evidence.py`). CSCV
is exhaustive over combinations and has no RNG at all. A fixed seed
reproduces every bootstrap number bit-for-bit, and the whole
`SelectionEvidence` block round-trips identically across runs.

### Coverage

Wired through `run_harder_gates`, so it reaches `traderstack-harder-gates`,
`traderstack-second-print`, `traderstack-intraday-dual-print`, and every
family that scores through `dual_print_search._score`:
`traderstack-dual-print-search`, `traderstack-relative-value`,
`traderstack-xs-momentum`, `traderstack-donchian-breakout`,
`traderstack-tsmom`, `traderstack-bollinger-fade`,
`traderstack-calendar-seasonality`, `traderstack-lead-lag`,
`traderstack-volume-breakout`.

`traderstack-honesty-pack` also carries it: it scores through
`run_harder_gates` and now surfaces that report's block.

`traderstack-second-print` was listed here as covered before it was: the
scorer computed the evidence and `_score_histories` discarded the report,
returning rows only. It now returns both, and
`test_second_print_surfaces_the_selection_evidence_block` pins that, as
`test_honesty_pack_surfaces_the_selection_evidence_block` does for the pack.

`traderstack-miles-search` carries it as of #135's follow-up. It could not
before for a structural reason worth recording: `selection_evidence` imported
`CandidateSearchResult` from `miles_search` and `series_for_asset` from
`daily_robustness` (which itself imports `miles_search`), so any search module
wanting an evidence block closed an import cycle. Both imports are now
deferred — the first to `TYPE_CHECKING` (annotation-only under
`from __future__ import annotations`), the second to call time — and
`kraken_daily_candles` moved down from `harder_gates` to sit with
`series_for_asset`, so the one implementation is reused rather than copied.
K is the frozen catalog length the report already publishes as
`multiple_testing["n_candidates"]`, so the deflation term is not a guess.

`traderstack-strategy-search` carries it too, behind an opt-in.
`search.AssetCandidateMetrics` now records the `interval` that `_score_asset`
already held, which makes it field-for-field identical to
`miles_search.SeriesCandidateMetrics`, and `CandidateSearchResult` exposes a
`per_series` alias. The builder reads only `candidate_id` and `per_series`, so
the call site casts and
`test_strategy_search_rows_stay_shape_compatible_with_the_evidence_builder`
fails if either model grows a field the other lacks — the cast cannot go stale
silently. K is again the published `n_candidates`.

The opt-in (`include_selection_evidence`, default off) exists because
`run_search` is called in a loop by `funding_carry` and `liq_regime_search`,
neither of which carries a block; only `traderstack-strategy-search` passes it.

**Not carrying the block:** `traderstack-daily-robustness`,
`traderstack-liq-regime-search` and `traderstack-funding-carry`.

`liq-regime-search` and `funding-carry` remain genuinely undecided rather than
merely unwired: each calls `run_search` several times per run, so "one trial"
spans multiple scored sets and K is not simply a catalog length. Choosing K
wrongly there understates the deflation term, which makes the DSR look better
rather than failing loudly.

`traderstack-daily-robustness` is deliberately excluded rather than blocked:
`run_daily_robustness` is called twice inside `run_harder_gates` (baseline and
fee-stressed) and again by `honesty_pack`, each of which already computes or
inherits its own block, so computing it there would trip the bootstrap three
times per harder-gates run for one reported result. These build
their reports on `research.search` / `research.miles_search` /
`research.daily_robustness` and never call `run_harder_gates`, so — contrary
to what this section previously claimed — extending the block to them is
**not** wiring. Each needs a decision about what its trial set is, and the
trial count is the deflation term: a wrong K silently *weakens* the DSR
rather than failing loudly, which is worse than reporting no DSR at all. So
they stay uncovered until that is designed per CLI, not guessed. This is the
first slice of #48 and does not close it.

### Polymarket weather — point-in-time tape now exists (#141)

The statement above that this repository has **no** public point-in-time
CLOB-mid + official-station-high tape is superseded in one respect: the
repository now *builds* one. `traderstack-polymarket-weather-collect` records
decision-time book and as-issued forecast while markets are open, and
`traderstack-polymarket-weather-resolve` pairs those rows with the official
station high and emits per-month print packs the evaluator consumes.

What has **not** changed:

* The tape starts empty. It can only be filled by running the collector from
  an operator host over weeks; nothing is back-filled from settlement prices.
  `docs/artifacts/strategy-search/polymarket-weather-tape.md` reports
  `rows = 0`, which is the honest status, not a failure.
* The evaluator still scores nothing until the resolver emits a print, still
  requires two independent prints, and still cannot promote.
* Gate 2 (walk-forward parameter fit) and gate 3 (a full season of live paper
  A/B) are not claimed.
* Only Fahrenheit-resolved cities are in scope until a unit-aware bucket
  model lands; Celsius cities are catalogued and skipped.
* `PAPER_PROMOTE_POLYMARKET_WEATHER` remains absent from `Settings`.
