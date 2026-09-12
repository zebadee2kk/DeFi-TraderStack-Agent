# Liquidation / regime-conditioned strategy search

Generated: 2026-09-12T16:30:36.729250+00:00
Print kind: **single_print**. `historical_liquidation=false`; `second_venue=false`; `can_promote=false`; `keep_flag_false=true`.
Core K=9; scored ids=13; ranking_key=`informational_wf_excess_single_print_cannot_promote` (informational).
Costs: fee=10 bps + slippage=5 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both.)
Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.

## What this does / does not claim

This is a paper-research catalog search conditioned on liquidation-z / funding-z / OI-z / cross-venue series when those series exist, plus candle-only vol-regime wrappers that always score. It is **not** a live-capital claim, not a PnL forecast, and not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`.

Crucix already maps high-tier alerts to `NewsSnapshot.adverse_event` and the pipeline already rejects with `adverse_news_event` when `INTELLIGENCE_BLOCK_ON_ADVERSE_NEWS=true`. That path was not changed here. Live liquidation / bookTicker features stay research context on the paper cycle; they do not size or side.

## Honesty / pre-registered rules

Pre-registered liquidation/regime-conditioned search (frozen before any Kraken or edge-series pull). Candle-only vol-regime wrappers are always scored. Unconditioned MA / momentum / mean-reversion controls are informational and cannot promote. Liquidation-z, funding-z, OI-z, and cross-venue families instantiate only when an aligned historical series is supplied — never zero-filled. Public USDT-M liquidation REST is typically unusable (allForceOrders recent-only / geo-blocked; Vision um/liquidationSnapshot removed; live WS is !forceOrder@arr). Dual-print requires a usable historical liquidation series on BTC and ETH AND a second venue candle print. Absent that, this run is SINGLE-PRINT (Kraken public Spot daily 720-bar cap) and cannot promote. PAPER_PROMOTE_* stays default false. No live. Empty search is success. This run is labeled SINGLE-PRINT and cannot promote, even if a vol-regime or funding/OI row would clear the #89 fee-aware bar. No usable historical liquidation series — liquidation-z voters were skipped, not zero-filled.

## Print policy (frozen before scoring)

Pre-registered liquidation/regime-conditioned search (frozen before any Kraken or edge-series pull). Candle-only vol-regime wrappers are always scored. Unconditioned MA / momentum / mean-reversion controls are informational and cannot promote. Liquidation-z, funding-z, OI-z, and cross-venue families instantiate only when an aligned historical series is supplied — never zero-filled. Public USDT-M liquidation REST is typically unusable (allForceOrders recent-only / geo-blocked; Vision um/liquidationSnapshot removed; live WS is !forceOrder@arr). Dual-print requires a usable historical liquidation series on BTC and ETH AND a second venue candle print. Absent that, this run is SINGLE-PRINT (Kraken public Spot daily 720-bar cap) and cannot promote. PAPER_PROMOTE_* stays default false. No live. Empty search is success.

| print | when | can promote? |
| --- | --- | --- |
| single-print | no usable historical liquidation series on BTC+ETH, or no second venue candle print | **no** |
| dual-print | historical liquidation series on BTC and ETH **and** a second venue print | still **no** Settings flip; a passer would only justify a documented default-false pin |

## Pre-registered catalog

Frozen core (K=9): six vol-regime-agree price voters plus three unconditioned controls (ma_cross_10_30, momentum_12, mean_reversion_20_1_5). Optional families when a series is present: liquidation_z fade/follow + liq-agree wrappers on those three inners and on ema_9_21 / ema_9_21_adx15 / ema_12_26; funding_z fade/follow; oi_z fade/follow; cross_venue_fade. Do not grow this list after seeing PnL. Live paper liquidation / bookTicker snapshots are not a historical series and are not backfilled.

Frozen core ids: `ma_cross_10_30_vol`, `ma_always_on_10_30_vol`, `momentum_6_vol`, `momentum_12_vol`, `mean_reversion_20_1_5_vol`, `mean_reversion_20_2_0_vol`, `ma_cross_10_30`, `momentum_12`, `mean_reversion_20_1_5`.

Unconditioned controls (cannot promote): `ma_cross_10_30`, `mean_reversion_20_1_5`, `momentum_12`.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- No usable historical liquidation series — Binance dual-print not fetched. Labeled single-print; cannot promote.

## Edge series

- `binance_funding:BTC/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_oi:BTC/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_liquidation:BTC/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed. (source=binance, points=0)
- `binance_funding:ETH/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_oi:ETH/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_liquidation:ETH/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed. (source=binance, points=0)
- `okx_funding:BTC/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=290)
- `okx_oi:BTC/USD` **ok**: OKX rubik 1h open-interest-history (public, paginated) (source=okx:/api/v5/rubik/stat/contracts/open-interest-history, points=1440)
- `okx_liquidation:BTC/USD` **skipped**: OKX liquidation-orders span 20.8h across 100 fills — not a historical aggregate. Skip rather than invent a z. (source=okx, points=0)
- `okx_funding:ETH/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=290)
- `okx_oi:ETH/USD` **ok**: OKX rubik 1h open-interest-history (public, paginated) (source=okx:/api/v5/rubik/stat/contracts/open-interest-history, points=1440)
- `okx_liquidation:ETH/USD` **skipped**: OKX liquidation-orders span 7.7h across 100 fills — not a historical aggregate. Skip rather than invent a z. (source=okx, points=0)

## Skipped optional families

- `liquidation_z_fade` (liquidation_z): fade liquidation z-score |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.
- `liquidation_z_follow` (liquidation_z): follow liquidation z-score |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.
- `cross_venue_fade` (cross_venue): fade cross-venue divergence z |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.
- `ema_9_21_liq_agree` (liquidation_z): EMA 9/21 (liquidation-z must agree): skipped — no aligned historical liquidation series. Live WS !forceOrder@arr is not a backtest input.
- `ema_9_21_adx15_liq_agree` (liquidation_z): EMA 9/21 ADX>15 (liquidation-z must agree): skipped — no aligned historical liquidation series. Live WS !forceOrder@arr is not a backtest input.
- `ema_12_26_liq_agree` (liquidation_z): EMA 12/26 (liquidation-z must agree): skipped — no aligned historical liquidation series. Live WS !forceOrder@arr is not a backtest input.

## Ranked candidates (walk-forward mean excess after fees)

Informational. Eligible under the #89 fee-aware bar does not mean promoted.
Controls cannot promote.

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_always_on_10_30_vol` | ma_cross | -4.40% | +7.82% | +11.29% | no | no |
| 2 | `ma_cross_10_30_vol` | ma_cross | -4.41% | +7.80% | +4.94% | no | no |
| 3 | `ma_cross_10_30` | ma_cross | -4.41% | +7.80% | +4.94% | no | yes |
| 4 | `momentum_12_vol` | momentum | -10.25% | +1.96% | -1.60% | no | no |
| 5 | `momentum_12` | momentum | -10.62% | +1.59% | -1.37% | no | yes |
| 6 | `mean_reversion_20_1_5_vol` | mean_reversion | -12.17% | +0.05% | -10.56% | no | no |
| 7 | `mean_reversion_20_1_5` | mean_reversion | -12.17% | +0.05% | -10.56% | no | yes |
| 8 | `mean_reversion_20_2_0_vol` | mean_reversion | -12.66% | -0.45% | -11.62% | no | no |
| 9 | `momentum_6_vol` | momentum | -13.03% | -0.82% | +5.69% | no | no |
| — | `funding_z_fade` | funding_z | -12.21% | +0.00% | +2.55% | no | no |
| — | `funding_z_follow` | funding_z | -12.21% | +0.00% | -27.54% | no | no |
| — | `oi_z_fade` | open_interest_z | -12.21% | +0.00% | -7.70% | no | no |
| — | `oi_z_follow` | open_interest_z | -12.21% | +0.00% | -16.75% | no | no |

## Dual-print passers

Not a dual-print run. A Kraken-only (or funding/OI-only) row cannot promote.

## Promotion decision

**No candidate is promoted.** print_kind=`single_print`; can_promote=`false`; recommended_promote_flag=`none`. Leave every `PAPER_PROMOTE_*` false. Do not add a new pin. Do not enable live.
Informational top-1 by WF excess was `ma_always_on_10_30_vol` (WF excess=-4.40%, WF total=+7.82%, holdout excess=+11.29%; eligible=False).
