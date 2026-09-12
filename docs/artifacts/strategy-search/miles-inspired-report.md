# Miles-inspired strategy search report

Generated: 2026-09-12T13:20:14.133711+00:00
Symbols: BTC/USD, ETH/USD, SOL/USD
Intervals: 1d, 1h (promotion uses 1d only)
Costs: fee=10 bps + slippage=5 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both.)
Walk-forward: train=180 test=60 step=60 (train is warmup; only the test window trades); holdout_fraction=20%
Promotion floor: WF mean total_return > 0 **and** holdout mean excess_return > 0 after fees, min trades=3
GARCH: min_train=120 refit_every=21 target_vol_ann=0.5 size clip [0.25, 2.0]
Selection: pre_registered_top1 (K=12)

## Inspiration and honesty

Methods only — not claimed YouTube PnL. Direction is EMA crossover (9/21, 12/26) with an optional ADX chop gate. GARCH(1,1) is a walk-forward vol forecast used *only* to scale size (`target_vol / forecast_vol`). No candidate is rewritten to look profitable. Walk-forward ranking never sees the holdout tail. Selection is pre-registered top-1 of 12 Miles-inspired catalog members (Bonferroni analogue: one promotion decision, not K independent promotions). A selected candidate is promoted only if fee-aware walk-forward mean total return is strictly greater than 0, min trades are met, and holdout mean excess return is strictly greater than 0. Positive excess with a negative total return is not an edge. 1h and daily percent returns are never averaged together; when daily bars are present they are the promotion window (Miles: use the daily chart) and 1h is a robustness table only.

## Multiple testing

K catalog members are scored on the same research window. We do not treat every excess>0 as a discovered edge. At most the single pre-registered top-1 (by walk-forward mean total return, min-trades filter) may be promoted, and only if holdout excess return is also strictly positive. A classical Bonferroni p-cut would be 0.05/12 ≈ 0.0042; this search has no per-fold t-test, so holdout confirmation is the out-of-sample control.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval. `since` pages forward only; older history is not available from this endpoint. Daily ≈ 2 years; 1h ≈ 30 days.
- BTC/USD@1d: 720 committed bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00
- BTC/USD@1h: 720 committed bars 2026-08-13T13:00:00+00:00 → 2026-09-12T12:00:00+00:00
- ETH/USD@1d: 720 committed bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00
- ETH/USD@1h: 720 committed bars 2026-08-13T13:00:00+00:00 → 2026-09-12T12:00:00+00:00
- SOL/USD@1d: 720 committed bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00
- SOL/USD@1h: 720 committed bars 2026-08-13T13:00:00+00:00 → 2026-09-12T12:00:00+00:00

## Ranked candidates (walk-forward mean total return after fees)

| rank | id | family | WF total | WF excess | WF trades | holdout excess | eligible | promoted |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `ema_9_21` | ema_cross | +7.92% | +6.34% | 61 | +22.20% | yes | yes |
| 2 | `ema_12_26` | ema_cross | +6.92% | +5.34% | 46 | +13.61% | yes | no |
| 3 | `ema_12_26_adx25` | ema_cross | +3.79% | +2.21% | 37 | +4.69% | yes | no |
| 4 | `ema_12_26_adx20` | ema_cross | +2.73% | +1.15% | 47 | -1.57% | no | no |
| 5 | `ema_9_21_adx25` | ema_cross | +1.91% | +0.34% | 43 | +2.63% | yes | no |
| 6 | `ema_9_21_adx20` | ema_cross | +1.87% | +0.29% | 57 | +8.85% | yes | no |
| 7 | `ema_9_21_garch` | ema_cross_garch | -0.09% | -1.66% | 327 | +1.14% | no | no |
| 8 | `ema_12_26_adx25_garch` | ema_cross_garch | -0.49% | -2.06% | 206 | -4.62% | no | no |
| 9 | `ema_12_26_garch` | ema_cross_garch | -1.40% | -2.97% | 311 | -5.75% | no | no |
| 10 | `ema_9_21_adx25_garch` | ema_cross_garch | -1.50% | -3.08% | 212 | -6.57% | no | no |
| 11 | `ema_12_26_adx20_garch` | ema_cross_garch | -2.08% | -3.66% | 254 | -12.07% | no | no |
| 12 | `ema_9_21_adx20_garch` | ema_cross_garch | -2.17% | -3.75% | 263 | -3.53% | no | no |

## Per-series detail

### `ema_9_21` — EMA 9/21

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | +4.57% | +5.48% | +5.55% | +7.35% |
| BTC/USD 1h | 720 | -0.50% | -1.82% | -4.24% | -7.50% |
| ETH/USD 1d | 720 | +14.61% | +8.60% | +58.37% | +67.06% |
| ETH/USD 1h | 720 | -0.48% | -1.30% | -3.74% | -2.37% |
| SOL/USD 1d | 720 | +4.57% | +4.94% | +2.66% | +22.73% |
| SOL/USD 1h | 720 | +0.35% | -2.18% | -3.71% | -8.19% |

### `ema_12_26` — EMA 12/26

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | +3.03% | +3.94% | +0.58% | +2.38% |
| BTC/USD 1h | 720 | -0.27% | -1.59% | -3.69% | -6.95% |
| ETH/USD 1d | 720 | +13.73% | +7.72% | +49.59% | +58.27% |
| ETH/USD 1h | 720 | -0.56% | -1.38% | -4.51% | -3.14% |
| SOL/USD 1d | 720 | +4.00% | +4.38% | -9.34% | +10.73% |
| SOL/USD 1h | 720 | -1.30% | -3.83% | -3.60% | -8.08% |

### `ema_12_26_adx25` — EMA 12/26 × ADX>25

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | +3.30% | +4.20% | +4.57% | +6.36% |
| BTC/USD 1h | 720 | -1.47% | -2.80% | -2.80% | -6.05% |
| ETH/USD 1d | 720 | +9.18% | +3.17% | +8.68% | +17.36% |
| ETH/USD 1h | 720 | -1.50% | -2.32% | -7.96% | -6.59% |
| SOL/USD 1d | 720 | -1.11% | -0.73% | +0.84% | +20.91% |
| SOL/USD 1h | 720 | -0.95% | -3.48% | -5.01% | -9.48% |

### `ema_12_26_adx20` — EMA 12/26 × ADX>20

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | +2.25% | +3.15% | +4.53% | +6.33% |
| BTC/USD 1h | 720 | -2.13% | -3.46% | -2.80% | -6.05% |
| ETH/USD 1d | 720 | +9.10% | +3.09% | +15.20% | +23.88% |
| ETH/USD 1h | 720 | -1.76% | -2.58% | -7.25% | -5.88% |
| SOL/USD 1d | 720 | -3.16% | -2.79% | -24.43% | -4.36% |
| SOL/USD 1h | 720 | -0.98% | -3.51% | -5.94% | -10.41% |

### `ema_9_21_adx25` — EMA 9/21 × ADX>25

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | +4.41% | +5.31% | +3.23% | +5.03% |
| BTC/USD 1h | 720 | -2.30% | -3.62% | -3.64% | -6.90% |
| ETH/USD 1d | 720 | +5.88% | -0.13% | +3.82% | +12.50% |
| ETH/USD 1h | 720 | -1.59% | -2.41% | -7.96% | -6.59% |
| SOL/USD 1d | 720 | -4.55% | -4.18% | +0.84% | +20.91% |
| SOL/USD 1h | 720 | -0.25% | -2.77% | -3.95% | -8.42% |

### `ema_9_21_adx20` — EMA 9/21 × ADX>20

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | +2.13% | +3.03% | +10.04% | +11.83% |
| BTC/USD 1h | 720 | -2.82% | -4.14% | -3.36% | -6.62% |
| ETH/USD 1d | 720 | +7.08% | +1.07% | +22.82% | +31.50% |
| ETH/USD 1h | 720 | -1.52% | -2.34% | -7.05% | -5.69% |
| SOL/USD 1d | 720 | -3.60% | -3.22% | -6.31% | +13.76% |
| SOL/USD 1h | 720 | +0.37% | -2.16% | -4.89% | -9.36% |

### `ema_9_21_garch` — EMA 9/21 × GARCH size [0.25, 2.0]

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | -3.54% | -2.63% | -16.31% | -14.52% |
| BTC/USD 1h | 720 | -8.21% | -9.54% | -23.38% | -26.64% |
| ETH/USD 1d | 720 | +3.69% | -2.32% | +28.48% | +37.16% |
| ETH/USD 1h | 720 | -5.82% | -6.64% | -22.53% | -21.16% |
| SOL/USD 1d | 720 | -0.42% | -0.05% | -8.74% | +11.32% |
| SOL/USD 1h | 720 | -6.29% | -8.82% | -13.99% | -18.47% |

### `ema_12_26_adx25_garch` — EMA 12/26 × ADX>25 × GARCH size [0.25, 2.0]

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | -1.38% | -0.47% | -4.49% | -2.70% |
| BTC/USD 1h | 720 | -5.61% | -6.94% | -16.23% | -19.48% |
| ETH/USD 1d | 720 | +2.16% | -3.84% | +0.47% | +9.16% |
| ETH/USD 1h | 720 | -3.93% | -4.75% | -9.70% | -8.33% |
| SOL/USD 1d | 720 | -2.24% | -1.87% | -9.83% | +10.24% |
| SOL/USD 1h | 720 | -4.14% | -6.67% | -8.40% | -12.88% |

### `ema_12_26_garch` — EMA 12/26 × GARCH size [0.25, 2.0]

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | -6.20% | -5.30% | -22.58% | -20.78% |
| BTC/USD 1h | 720 | -8.27% | -9.59% | -22.73% | -25.98% |
| ETH/USD 1d | 720 | +3.18% | -2.83% | +22.49% | +31.17% |
| ETH/USD 1h | 720 | -6.09% | -6.91% | -24.01% | -22.65% |
| SOL/USD 1d | 720 | -1.16% | -0.79% | -17.17% | +2.90% |
| SOL/USD 1h | 720 | -7.45% | -9.98% | -14.49% | -18.97% |

### `ema_9_21_adx25_garch` — EMA 9/21 × ADX>25 × GARCH size [0.25, 2.0]

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | -0.04% | +0.86% | -6.19% | -4.40% |
| BTC/USD 1h | 720 | -6.29% | -7.61% | -16.93% | -20.19% |
| ETH/USD 1d | 720 | -0.06% | -6.06% | -3.69% | +4.99% |
| ETH/USD 1h | 720 | -3.94% | -4.76% | -9.70% | -8.33% |
| SOL/USD 1d | 720 | -4.40% | -4.03% | -9.83% | +10.24% |
| SOL/USD 1h | 720 | -3.62% | -6.14% | -7.36% | -11.83% |

### `ema_12_26_adx20_garch` — EMA 12/26 × ADX>20 × GARCH size [0.25, 2.0]

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | -2.90% | -1.99% | -7.99% | -6.19% |
| BTC/USD 1h | 720 | -8.62% | -9.95% | -19.87% | -23.12% |
| ETH/USD 1d | 720 | +0.86% | -5.14% | +1.10% | +9.78% |
| ETH/USD 1h | 720 | -5.31% | -6.13% | -13.86% | -12.50% |
| SOL/USD 1d | 720 | -4.22% | -3.85% | -29.34% | -9.27% |
| SOL/USD 1h | 720 | -5.26% | -7.78% | -10.78% | -15.26% |

### `ema_9_21_adx20_garch` — EMA 9/21 × ADX>20 × GARCH size [0.25, 2.0]

| series | bars | WF total | WF excess | holdout excess | holdout total |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | 720 | -2.63% | -1.73% | -0.82% | +0.97% |
| BTC/USD 1h | 720 | -9.14% | -10.46% | -20.55% | -23.80% |
| ETH/USD 1d | 720 | -0.09% | -6.10% | +6.15% | +14.83% |
| ETH/USD 1h | 720 | -4.92% | -5.74% | -13.20% | -11.83% |
| SOL/USD 1d | 720 | -3.80% | -3.42% | -15.92% | +4.15% |
| SOL/USD 1h | 720 | -4.32% | -6.85% | -9.75% | -14.23% |

## Promotion decision

Promoted on the 1d window (research only): ema_9_21.
**`PAPER_GARCH_SIZE` stays false.** No GARCH-sized candidate cleared the bar (vol-targeted size increased turnover and fee drag).
1h robustness (not in the promotion average) is in the per-series tables. A large daily holdout on one asset is one tail, not a live-capital claim. Do not copy YouTube return figures.
