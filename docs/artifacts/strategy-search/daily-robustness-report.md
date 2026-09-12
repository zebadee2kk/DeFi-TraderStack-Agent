# Daily robustness report

Generated: 2026-09-12T14:26:05.998659+00:00
Symbols: BTC-USD, BTC/USD, ETH-USD, ETH/USD, SOL/USD
Intervals: 1d (promotion uses Kraken 1d BTC+ETH only)
Costs: fee=10 bps + slippage=5 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both.)
Walk-forward: train=180 test=60 step=60 (train is warmup; only the test window trades); holdout_fraction=20%
Promotion floor: **BTC and ETH** Kraken daily WF mean total_return > 0 **and** holdout mean excess_return > 0 after fees, min trades=3. SOL is supporting. Yahoo is non-Kraken A/B.
Selection: pre_registered_top1 (K=8)

## Honesty

No candidate is rewritten to look profitable. Walk-forward ranking never sees the holdout tail. Selection is pre-registered top-1 of 8 daily-robustness catalog members. Promotion uses Kraken daily BTC/USD and ETH/USD only: both must have fee-aware walk-forward mean total return > 0 (this is the multi-asset bar that #93's three-asset mean did not require), min trades must be met, and holdout mean excess return on those two assets must be > 0 after fees. SOL/USD is supporting. Yahoo Finance daily is a longer non-Kraken A/B and cannot promote. Positive excess with a negative total return is not an edge. A large ETH holdout on a two-year window is one tail, not a live-capital claim. ema_9_21 still clears the stricter BTC-and-ETH walk-forward bar on this window. That does not flip the default flag.

## Multiple testing

K catalog members are scored on the same Kraken BTC/ETH daily research window. At most the single pre-registered top-1 (by walk-forward mean total return on BTC+ETH, min-trades filter) may be promoted, and only if BTC and ETH both have WF total > 0 and holdout mean excess > 0. A classical Bonferroni p-cut would be 0.05/8 ≈ 0.0063; this search has no per-fold t-test, so holdout confirmation is the out-of-sample control.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- BTC-USD@1d: 4378 Yahoo Finance (yfinance-compatible, non-Kraken) daily bars 2014-09-17T00:00:00+00:00 → 2026-09-11T00:00:00+00:00
- ETH-USD@1d: 3229 Yahoo Finance (yfinance-compatible, non-Kraken) daily bars 2017-11-09T00:00:00+00:00 → 2026-09-11T00:00:00+00:00

## Ranked candidates (Kraken BTC+ETH daily, walk-forward mean total after fees)

| rank | id | family | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout maxDD | BTC WF | ETH WF | eligible | promoted |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `ema_9_21` | ema_cross | +9.59% | +7.04% | 42 | +23.35% | +31.96% | +9.69% | +4.57% | +14.61% | yes | yes |
| 2 | `ema_12_26` | ema_cross | +8.38% | +5.83% | 30 | +25.37% | +25.09% | +11.42% | +3.03% | +13.73% | yes | no |
| 3 | `ema_12_26_adx25` | ema_cross | +6.24% | +3.69% | 23 | +12.12% | +6.62% | +3.08% | +3.30% | +9.18% | yes | no |
| 4 | `ema_12_26_adx20` | ema_cross | +5.67% | +3.12% | 29 | +17.49% | +9.87% | +5.35% | +2.25% | +9.10% | yes | no |
| 5 | `ema_9_21_adx25` | ema_cross | +5.14% | +2.59% | 27 | +13.27% | +3.53% | +4.29% | +4.41% | +5.88% | yes | no |
| 6 | `ema_9_21_adx20` | ema_cross | +4.60% | +2.05% | 38 | +20.60% | +16.43% | +2.43% | +2.13% | +7.08% | yes | no |
| 7 | `dual_mom_21_126` | dual_momentum | +4.18% | +1.63% | 57 | +14.24% | -6.35% | +18.84% | -1.40% | +9.76% | no | no |
| 8 | `dip_mr_20_1_5_vol` | buy_the_dip | +0.03% | -2.52% | 35 | +21.64% | -14.53% | +12.41% | -0.64% | +0.70% | no | no |

## Per-series detail

### `ema_9_21` — EMA 9/21

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +4.57% | +5.48% | 23 | +17.93% | +5.55% | +7.35% | 7 | +17.01% |
| ETH/USD 1d | kraken | 720 | +14.61% | +8.60% | 19 | +28.77% | +58.37% | +67.06% | 3 | +2.38% |
| SOL/USD 1d | kraken | 720 | +4.57% | +4.94% | 19 | +50.01% | +2.66% | +22.73% | 7 | +16.52% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +12.83% | -3.41% | 167 | +50.65% | -9.28% | +11.59% | 44 | +33.16% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +11.00% | -1.00% | 127 | +60.65% | +202.27% | +168.59% | 21 | +36.23% |

### `ema_12_26` — EMA 12/26

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +3.03% | +3.94% | 16 | +21.06% | +0.58% | +2.38% | 7 | +17.92% |
| ETH/USD 1d | kraken | 720 | +13.73% | +7.72% | 14 | +29.68% | +49.59% | +58.27% | 3 | +4.91% |
| SOL/USD 1d | kraken | 720 | +4.00% | +4.38% | 16 | +44.10% | -9.34% | +10.73% | 7 | +18.23% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +13.64% | -2.60% | 138 | +59.74% | -21.92% | -1.06% | 34 | +30.10% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +8.73% | -3.27% | 105 | +62.02% | +144.37% | +110.69% | 17 | +35.12% |

### `ema_12_26_adx25` — EMA 12/26 × ADX>25

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +3.30% | +4.20% | 13 | +12.73% | +4.57% | +6.36% | 4 | +5.88% |
| ETH/USD 1d | kraken | 720 | +9.18% | +3.17% | 10 | +11.51% | +8.68% | +17.36% | 2 | +0.29% |
| SOL/USD 1d | kraken | 720 | -1.11% | -0.73% | 14 | +30.17% | +0.84% | +20.91% | 2 | +0.15% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +11.51% | -4.73% | 105 | +43.42% | +8.03% | +28.90% | 21 | +16.86% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +5.86% | -6.14% | 88 | +48.10% | +107.39% | +73.70% | 13 | +27.95% |

### `ema_12_26_adx20` — EMA 12/26 × ADX>20

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +2.25% | +3.15% | 15 | +10.00% | +4.53% | +6.33% | 5 | +5.78% |
| ETH/USD 1d | kraken | 720 | +9.10% | +3.09% | 14 | +24.97% | +15.20% | +23.88% | 4 | +4.91% |
| SOL/USD 1d | kraken | 720 | -3.16% | -2.79% | 18 | +34.25% | -24.43% | -4.36% | 4 | +12.29% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +12.09% | -4.15% | 131 | +59.74% | -37.74% | -16.87% | 32 | +38.39% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +8.42% | -3.58% | 108 | +50.73% | +66.46% | +32.77% | 18 | +35.12% |

### `ema_9_21_adx25` — EMA 9/21 × ADX>25

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +4.41% | +5.31% | 15 | +7.61% | +3.23% | +5.03% | 5 | +5.88% |
| ETH/USD 1d | kraken | 720 | +5.88% | -0.13% | 12 | +18.93% | +3.82% | +12.50% | 3 | +2.70% |
| SOL/USD 1d | kraken | 720 | -4.55% | -4.18% | 16 | +38.31% | +0.84% | +20.91% | 2 | +0.15% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +7.75% | -8.49% | 121 | +48.52% | +12.82% | +33.69% | 24 | +19.83% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +6.39% | -5.61% | 98 | +48.56% | +75.67% | +41.99% | 17 | +25.18% |

### `ema_9_21_adx20` — EMA 9/21 × ADX>20

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +2.13% | +3.03% | 21 | +15.21% | +10.04% | +11.83% | 5 | +2.48% |
| ETH/USD 1d | kraken | 720 | +7.08% | +1.07% | 17 | +26.00% | +22.82% | +31.50% | 5 | +2.38% |
| SOL/USD 1d | kraken | 720 | -3.60% | -3.22% | 19 | +41.20% | -6.31% | +13.76% | 4 | +8.68% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +9.90% | -6.35% | 151 | +50.65% | -26.01% | -5.14% | 38 | +40.92% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +10.05% | -1.95% | 121 | +49.53% | +79.61% | +45.93% | 21 | +44.29% |

### `dual_mom_21_126` — dual-momentum 21/126 (agree or cash)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -1.40% | -0.49% | 33 | +13.31% | +4.12% | +5.91% | 11 | +9.48% |
| ETH/USD 1d | kraken | 720 | +9.76% | +3.75% | 24 | +15.16% | -16.83% | -8.15% | 10 | +28.19% |
| SOL/USD 1d | kraken | 720 | +3.16% | +3.54% | 25 | +21.65% | -7.70% | +12.36% | 12 | +8.92% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +12.53% | -3.71% | 211 | +49.79% | -30.53% | -9.66% | 56 | +27.89% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +6.80% | -5.20% | 158 | +41.17% | +58.58% | +24.90% | 39 | +28.21% |

Blocked by: holdout_excess_return_not_positive, btc_walkforward_total_return_not_positive

### `dip_mr_20_1_5_vol` — buy-the-dip 20-bar |z|>=1.5 (skip if 20d vol > 1.5× 60d vol)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -0.64% | +0.27% | 18 | +16.95% | -8.96% | -7.17% | 8 | +12.57% |
| ETH/USD 1d | kraken | 720 | +0.70% | -5.31% | 17 | +26.33% | -20.09% | -11.41% | 6 | +12.24% |
| SOL/USD 1d | kraken | 720 | +4.15% | +4.53% | 21 | +28.62% | -29.01% | -8.95% | 4 | +10.31% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | -0.20% | -16.45% | 113 | +41.68% | -21.20% | -0.34% | 40 | +28.48% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | -0.40% | -12.40% | 104 | +39.86% | +23.39% | -10.30% | 31 | +27.91% |

Blocked by: holdout_excess_return_not_positive, btc_walkforward_total_return_not_positive

## Holdout concentration (honesty)

`ema_9_21` Kraken holdout excess is still ETH-heavy: BTC +5.55% vs ETH +58.37%. The multi-asset bar only requires both **walk-forward** totals > 0; it does not require a balanced holdout. A +50% ETH tail on one ~144-day window is not a live-capital claim.

## Yahoo Finance A/B (non-Kraken, not promotion)

Yahoo `range=max` downsamples crypto to monthly; this A/B uses `period1`/`period2` so the series stays daily. High/low are expanded to contain open/close when Yahoo's print is inconsistent. Closes are not Kraken Spot. This block cannot promote.

- `BTC-USD` 4378 bars: WF total +12.83%, holdout excess -9.28%
- `ETH-USD` 3229 bars: WF total +11.00%, holdout excess +202.27%

## Promotion decision

Cleared the stricter multi-asset bar on Kraken daily BTC+ETH (research only): `ema_9_21`.
Documented paper-only switch: `PAPER_PROMOTE_EMA_9_21=true` (default false; `TRADING_MODE=paper` only). This report does not flip that flag and does not enable live.

Yahoo rows above are a longer non-Kraken A/B. Do not average them with Kraken prints. Do not copy YouTube or Yahoo-backtest return figures.
