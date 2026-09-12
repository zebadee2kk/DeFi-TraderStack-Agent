# Daily robustness report

Generated: 2026-09-12T14:42:05.062544+00:00
Symbols: BTC-USD, BTC/USD, ETH-USD, ETH/USD, SOL/USD
Intervals: 1d (promotion uses Kraken 1d BTC+ETH only)
Costs: fee=10 bps + slippage=5 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both.)
Walk-forward: train=180 test=60 step=60 (train is warmup; only the test window trades); holdout_fraction=20%
Promotion floor: **BTC and ETH** Kraken daily WF mean total_return > 0, **BTC holdout excess > 0 and ETH holdout excess > 0** (balanced holdout — ETH cannot carry a losing BTC tail), holdout mean excess_return > 0 after fees, min trades=3. SOL is supporting (not required). Yahoo is non-Kraken A/B and never enters the promotion average.
Selection: pre_registered_top1 (K=20, catalog=balanced)

## Honesty

No candidate is rewritten to look profitable. Walk-forward ranking never sees the holdout tail. Selection is pre-registered top-1 of 20 daily-robustness catalog members. Promotion uses Kraken daily BTC/USD and ETH/USD only. The #95 bar required both walk-forward totals > 0 and a positive **mean** holdout excess — an ETH tail could still carry that mean. The balanced-holdout bar additionally requires BTC holdout excess > 0 **and** ETH holdout excess > 0 so one asset cannot hide a losing holdout. SOL/USD is supporting and is not required to promote. Yahoo Finance daily is a longer non-Kraken A/B and cannot promote. Positive excess with a negative total return is not an edge. A large ETH holdout on a two-year window is one tail, not a live-capital claim. This run's promotion decision uses the balanced-holdout bar (BTC and ETH WF total > 0 **and** BTC and ETH holdout excess > 0, plus mean holdout excess > 0 and min trades). ema_9_21 #95 multi-asset bar: PASS. ema_9_21 balanced-holdout bar: PASS. ema_9_21 cleared this run's promotion bar. That does not flip PAPER_PROMOTE_EMA_9_21 (default false) and does not enable live.

## Multiple testing

K catalog members are scored on the same Kraken BTC/ETH daily research window. At most the single pre-registered top-1 (by walk-forward mean total return on BTC+ETH, min-trades filter) may be promoted, and only if BTC and ETH both have WF total > 0, BTC holdout excess > 0, ETH holdout excess > 0, and holdout mean excess > 0. A classical Bonferroni p-cut would be 0.05/20 ≈ 0.0025; this search has no per-fold t-test, so per-asset holdout confirmation is the out-of-sample control.

## Pre-registered catalog

Pre-registered balanced-holdout grid (frozen before the Kraken window is scored): #95 EMA 9/21 and 12/26 ± ADX 20/25; slower EMA 20/50 and 50/200 (± ADX 20 on 20/50); dual-mom lookbacks 12/60, 21/63, 21/126, 63/126; buy-the-dip z=1.5 and z=2.0 with the same vol filter; asset-local SMA200 risk-off on ema_9_21 and ema_20_50; BTC SMA200 overlay on ema_9_21 when a Kraken BTC/USD daily series is bound; GARCH size overlays on ema_9_21 and ema_20_50 only. SOL is reported, not a promotion gate. Yahoo never enters the promotion average. PAPER_GARCH_SIZE stays false unless a GARCH-sized name clears.

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

| rank | id | family | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout maxDD | BTC WF | ETH WF | BTC holdout | ETH holdout | eligible | promoted |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `ema_9_21` | ema_cross | +9.59% | +7.04% | 42 | +23.35% | +31.96% | +9.69% | +4.57% | +14.61% | +5.55% | +58.37% | yes | yes |
| 2 | `ema_12_26` | ema_cross | +8.38% | +5.83% | 30 | +25.37% | +25.09% | +11.42% | +3.03% | +13.73% | +0.58% | +49.59% | yes | no |
| 3 | `ema_12_26_adx25` | ema_cross | +6.24% | +3.69% | 23 | +12.12% | +6.62% | +3.08% | +3.30% | +9.18% | +4.57% | +8.68% | yes | no |
| 4 | `ema_12_26_adx20` | ema_cross | +5.67% | +3.12% | 29 | +17.49% | +9.87% | +5.35% | +2.25% | +9.10% | +4.53% | +15.20% | yes | no |
| 5 | `ema_9_21_adx25` | ema_cross | +5.14% | +2.59% | 27 | +13.27% | +3.53% | +4.29% | +4.41% | +5.88% | +3.23% | +3.82% | yes | no |
| 6 | `ema_20_50_adx20` | ema_cross | +5.08% | +2.53% | 29 | +13.03% | +0.94% | +4.46% | -0.23% | +10.39% | +2.34% | -0.46% | no | no |
| 7 | `ema_9_21_btc_ma200_riskoff` | ema_cross_riskoff | +4.90% | +2.35% | 33 | +23.42% | +6.04% | +0.15% | -1.06% | +10.86% | +9.33% | +2.75% | no | no |
| 8 | `ema_9_21_ma200_riskoff` | ema_cross_riskoff | +4.67% | +2.12% | 25 | +13.33% | +6.04% | +0.15% | +2.91% | +6.44% | +9.33% | +2.75% | yes | no |
| 9 | `ema_9_21_adx20` | ema_cross | +4.60% | +2.05% | 38 | +20.60% | +16.43% | +2.43% | +2.13% | +7.08% | +10.04% | +22.82% | yes | no |
| 10 | `ema_20_50_ma200_riskoff` | ema_cross_riskoff | +4.55% | +2.00% | 19 | +15.21% | +0.22% | +2.97% | -0.37% | +9.48% | -2.30% | +2.75% | no | no |
| 11 | `dual_mom_21_63` | dual_momentum | +4.47% | +1.92% | 64 | +18.20% | +7.32% | +10.33% | -2.45% | +11.39% | +1.85% | +12.78% | no | no |
| 12 | `dual_mom_21_126` | dual_momentum | +4.18% | +1.63% | 57 | +14.24% | -6.35% | +18.84% | -1.40% | +9.76% | +4.12% | -16.83% | no | no |
| 13 | `dual_mom_63_126` | dual_momentum | +3.40% | +0.84% | 30 | +16.83% | -3.69% | +6.36% | +0.44% | +6.35% | -9.92% | +2.53% | no | no |
| 14 | `dip_mr_20_2_0_vol` | buy_the_dip | +2.59% | +0.04% | 21 | +4.45% | -16.21% | +11.70% | +1.82% | +3.36% | -11.99% | -20.44% | no | no |
| 15 | `ema_20_50` | ema_cross | +2.00% | -0.55% | 23 | +28.85% | +10.06% | +6.53% | -2.69% | +6.70% | -0.01% | +20.14% | no | no |
| 16 | `ema_9_21_garch` | ema_cross_garch | +0.08% | -2.47% | 248 | +29.55% | +6.08% | +22.86% | -3.54% | +3.69% | -16.31% | +28.48% | no | no |
| 17 | `dip_mr_20_1_5_vol` | buy_the_dip | +0.03% | -2.52% | 35 | +21.64% | -14.53% | +12.41% | -0.64% | +0.70% | -8.96% | -20.09% | no | no |
| 18 | `dual_mom_12_60` | dual_momentum | -0.65% | -3.20% | 69 | +23.68% | +1.97% | +9.20% | -0.36% | -0.93% | +1.73% | +2.22% | no | no |
| 19 | `ema_20_50_garch` | ema_cross_garch | -6.35% | -8.90% | 233 | +37.63% | -11.40% | +24.09% | -12.48% | -0.22% | -23.59% | +0.79% | no | no |
| 20 | `ema_50_200` | ema_cross | -8.63% | -11.19% | 15 | +37.72% | -10.21% | +4.97% | -3.06% | -14.21% | -3.22% | -17.20% | no | no |

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

### `ema_20_50_adx20` — EMA 20/50 × ADX>20

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -0.23% | +0.67% | 16 | +13.34% | +2.34% | +4.14% | 4 | +3.70% |
| ETH/USD 1d | kraken | 720 | +10.39% | +4.39% | 13 | +12.71% | -0.46% | +8.23% | 5 | +5.22% |
| SOL/USD 1d | kraken | 720 | +6.81% | +7.19% | 12 | +24.66% | -18.25% | +1.82% | 4 | +8.68% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +13.50% | -2.74% | 118 | +55.98% | -53.89% | -33.02% | 30 | +52.14% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +8.64% | -3.36% | 94 | +61.98% | +107.61% | +73.92% | 14 | +22.11% |

Blocked by: btc_walkforward_total_return_not_positive, eth_holdout_excess_not_positive

### `ema_9_21_btc_ma200_riskoff` — EMA 9/21 × BTC/USD SMA200 risk-off (flat when BTC below MA)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -1.06% | -0.16% | 18 | +17.93% | +9.33% | +11.12% | 1 | +0.15% |
| ETH/USD 1d | kraken | 720 | +10.86% | +4.85% | 15 | +28.91% | +2.75% | +11.43% | 1 | +0.15% |
| SOL/USD 1d | kraken | 720 | -3.81% | -3.44% | 16 | +50.01% | -0.37% | +19.70% | 1 | +0.15% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +0.00% | -16.25% | 0 | +0.00% | -17.00% | +3.86% | 16 | +25.12% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +0.00% | -12.00% | 0 | +0.00% | +128.15% | +94.46% | 13 | +29.45% |

Blocked by: btc_walkforward_total_return_not_positive

### `ema_9_21_ma200_riskoff` — EMA 9/21 × asset SMA200 risk-off (flat below MA)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +2.91% | +3.82% | 13 | +8.11% | +9.33% | +11.12% | 1 | +0.15% |
| ETH/USD 1d | kraken | 720 | +6.44% | +0.43% | 12 | +18.54% | +2.75% | +11.43% | 1 | +0.15% |
| SOL/USD 1d | kraken | 720 | +3.61% | +3.98% | 6 | +19.18% | -0.37% | +19.70% | 1 | +0.15% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +11.00% | -5.24% | 77 | +36.86% | -15.76% | +5.11% | 37 | +32.80% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +5.18% | -6.82% | 62 | +45.28% | +52.05% | +18.36% | 17 | +31.31% |

### `ema_9_21_adx20` — EMA 9/21 × ADX>20

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +2.13% | +3.03% | 21 | +15.21% | +10.04% | +11.83% | 5 | +2.48% |
| ETH/USD 1d | kraken | 720 | +7.08% | +1.07% | 17 | +26.00% | +22.82% | +31.50% | 5 | +2.38% |
| SOL/USD 1d | kraken | 720 | -3.60% | -3.22% | 19 | +41.20% | -6.31% | +13.76% | 4 | +8.68% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +9.90% | -6.35% | 151 | +50.65% | -26.01% | -5.14% | 38 | +40.92% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +10.05% | -1.95% | 121 | +49.53% | +79.61% | +45.93% | 21 | +44.29% |

### `ema_20_50_ma200_riskoff` — EMA 20/50 × asset SMA200 risk-off (flat below MA)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -0.37% | +0.53% | 10 | +15.08% | -2.30% | -0.51% | 2 | +5.80% |
| ETH/USD 1d | kraken | 720 | +9.48% | +3.47% | 9 | +15.33% | +2.75% | +11.43% | 1 | +0.15% |
| SOL/USD 1d | kraken | 720 | +4.23% | +4.61% | 5 | +20.89% | -0.37% | +19.70% | 1 | +0.15% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +12.03% | -4.22% | 60 | +20.47% | -29.49% | -8.62% | 26 | +40.71% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +7.21% | -4.79% | 46 | +38.18% | +109.43% | +75.75% | 10 | +22.11% |

Blocked by: btc_walkforward_total_return_not_positive, btc_holdout_excess_not_positive

### `dual_mom_21_63` — dual-momentum 21/63 (agree or cash)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -2.45% | -1.55% | 35 | +13.45% | +1.85% | +3.65% | 11 | +10.42% |
| ETH/USD 1d | kraken | 720 | +11.39% | +5.38% | 29 | +22.95% | +12.78% | +21.46% | 12 | +10.24% |
| SOL/USD 1d | kraken | 720 | -3.60% | -3.23% | 35 | +34.28% | +5.39% | +25.46% | 14 | +16.74% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +11.33% | -4.91% | 231 | +33.34% | -55.57% | -34.71% | 71 | +44.48% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +5.41% | -6.59% | 178 | +30.98% | +155.46% | +121.77% | 44 | +32.29% |

Blocked by: btc_walkforward_total_return_not_positive

### `dual_mom_21_126` — dual-momentum 21/126 (agree or cash)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -1.40% | -0.49% | 33 | +13.31% | +4.12% | +5.91% | 11 | +9.48% |
| ETH/USD 1d | kraken | 720 | +9.76% | +3.75% | 24 | +15.16% | -16.83% | -8.15% | 10 | +28.19% |
| SOL/USD 1d | kraken | 720 | +3.16% | +3.54% | 25 | +21.65% | -7.70% | +12.36% | 12 | +8.92% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +12.53% | -3.71% | 211 | +49.79% | -30.53% | -9.66% | 56 | +27.89% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +6.80% | -5.20% | 158 | +41.17% | +58.58% | +24.90% | 39 | +28.21% |

Blocked by: holdout_excess_return_not_positive, btc_walkforward_total_return_not_positive, eth_holdout_excess_not_positive

### `dual_mom_63_126` — dual-momentum 63/126 (agree or cash)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +0.44% | +1.35% | 19 | +14.38% | -9.92% | -8.13% | 5 | +12.43% |
| ETH/USD 1d | kraken | 720 | +6.35% | +0.34% | 11 | +19.29% | +2.53% | +11.22% | 4 | +0.29% |
| SOL/USD 1d | kraken | 720 | +0.10% | +0.47% | 19 | +34.14% | -8.58% | +11.48% | 8 | +10.78% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +14.02% | -2.22% | 141 | +50.09% | -48.28% | -27.42% | 42 | +38.35% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +12.04% | +0.04% | 105 | +75.45% | +55.84% | +22.16% | 16 | +28.90% |

Blocked by: holdout_excess_return_not_positive, btc_holdout_excess_not_positive

### `dip_mr_20_2_0_vol` — buy-the-dip 20-bar |z|>=2 (skip if 20d vol > 1.5× 60d vol)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | +1.82% | +2.73% | 13 | +3.96% | -11.99% | -10.19% | 3 | +11.65% |
| ETH/USD 1d | kraken | 720 | +3.36% | -2.65% | 8 | +4.94% | -20.44% | -11.76% | 2 | +11.76% |
| SOL/USD 1d | kraken | 720 | +7.01% | +7.38% | 13 | +2.61% | -30.71% | -10.64% | 1 | +10.64% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | -0.86% | -17.11% | 59 | +23.69% | -35.61% | -14.74% | 22 | +19.35% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +0.52% | -11.48% | 57 | +35.98% | +40.37% | +6.68% | 17 | +11.97% |

Blocked by: holdout_excess_return_not_positive, btc_holdout_excess_not_positive, eth_holdout_excess_not_positive

### `ema_20_50` — EMA 20/50

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -2.69% | -1.79% | 14 | +24.15% | -0.01% | +1.79% | 3 | +4.08% |
| ETH/USD 1d | kraken | 720 | +6.70% | +0.69% | 9 | +33.54% | +20.14% | +28.82% | 3 | +8.97% |
| SOL/USD 1d | kraken | 720 | +5.06% | +5.43% | 10 | +25.60% | -54.12% | -34.05% | 10 | +44.98% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +14.25% | -1.99% | 97 | +55.98% | -52.62% | -31.76% | 19 | +55.40% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +9.11% | -2.89% | 79 | +64.24% | +164.27% | +130.58% | 9 | +22.11% |

Blocked by: btc_walkforward_total_return_not_positive, btc_holdout_excess_not_positive

### `ema_9_21_garch` — EMA 9/21 × GARCH size [0.25, 2.0]

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -3.54% | -2.63% | 155 | +30.86% | -16.31% | -14.52% | 69 | +35.94% |
| ETH/USD 1d | kraken | 720 | +3.69% | -2.32% | 93 | +28.25% | +28.48% | +37.16% | 20 | +9.78% |
| SOL/USD 1d | kraken | 720 | -0.42% | -0.05% | 79 | +36.15% | -8.74% | +11.32% | 23 | +15.79% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +6.42% | -9.82% | 1187 | +38.05% | -79.96% | -59.10% | 299 | +64.92% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +1.83% | -10.17% | 547 | +38.93% | +103.61% | +69.92% | 121 | +38.47% |

Blocked by: btc_walkforward_total_return_not_positive, btc_holdout_excess_not_positive

### `dip_mr_20_1_5_vol` — buy-the-dip 20-bar |z|>=1.5 (skip if 20d vol > 1.5× 60d vol)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -0.64% | +0.27% | 18 | +16.95% | -8.96% | -7.17% | 8 | +12.57% |
| ETH/USD 1d | kraken | 720 | +0.70% | -5.31% | 17 | +26.33% | -20.09% | -11.41% | 6 | +12.24% |
| SOL/USD 1d | kraken | 720 | +4.15% | +4.53% | 21 | +28.62% | -29.01% | -8.95% | 4 | +10.31% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | -0.20% | -16.45% | 113 | +41.68% | -21.20% | -0.34% | 40 | +28.48% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | -0.40% | -12.40% | 104 | +39.86% | +23.39% | -10.30% | 31 | +27.91% |

Blocked by: holdout_excess_return_not_positive, btc_walkforward_total_return_not_positive, btc_holdout_excess_not_positive, eth_holdout_excess_not_positive

### `dual_mom_12_60` — dual-momentum 12/60 (agree or cash)

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -0.36% | +0.54% | 32 | +14.60% | +1.73% | +3.52% | 13 | +8.68% |
| ETH/USD 1d | kraken | 720 | -0.93% | -6.94% | 37 | +32.76% | +2.22% | +10.90% | 18 | +9.72% |
| SOL/USD 1d | kraken | 720 | -7.90% | -7.52% | 41 | +44.89% | -3.64% | +16.43% | 15 | +19.16% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +11.32% | -4.92% | 291 | +33.58% | -35.96% | -15.10% | 79 | +38.31% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +9.63% | -2.37% | 216 | +28.49% | +46.04% | +12.35% | 60 | +40.57% |

Blocked by: walkforward_total_return_not_positive, btc_walkforward_total_return_not_positive, eth_walkforward_total_return_not_positive

### `ema_20_50_garch` — EMA 20/50 × GARCH size [0.25, 2.0]

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -12.48% | -11.57% | 149 | +40.28% | -23.59% | -21.79% | 67 | +31.69% |
| ETH/USD 1d | kraken | 720 | -0.22% | -6.23% | 84 | +34.97% | +0.79% | +9.47% | 19 | +16.49% |
| SOL/USD 1d | kraken | 720 | +0.23% | +0.60% | 71 | +19.35% | -54.23% | -34.16% | 24 | +42.26% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +6.65% | -9.60% | 1145 | +38.71% | -95.74% | -74.88% | 275 | +75.53% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +1.67% | -10.33% | 525 | +47.76% | +43.28% | +9.60% | 113 | +37.26% |

Blocked by: walkforward_total_return_not_positive, holdout_excess_return_not_positive, btc_walkforward_total_return_not_positive, eth_walkforward_total_return_not_positive, btc_holdout_excess_not_positive

### `ema_50_200` — EMA 50/200

| series | source | bars | WF total | WF excess | WF trades | WF maxDD | holdout excess | holdout total | holdout trades | holdout maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC/USD 1d | kraken | 720 | -3.06% | -2.15% | 8 | +23.69% | -3.22% | -1.43% | 1 | +1.43% |
| ETH/USD 1d | kraken | 720 | -14.21% | -20.22% | 7 | +51.74% | -17.20% | -8.52% | 2 | +8.52% |
| SOL/USD 1d | kraken | 720 | -13.82% | -13.45% | 7 | +40.43% | -39.31% | -19.24% | 1 | +19.24% |
| BTC-USD 1d | yahoo (non-Kraken) | 4378 | +4.95% | -11.29% | 66 | +64.05% | +42.91% | +63.78% | 2 | +0.15% |
| ETH-USD 1d | yahoo (non-Kraken) | 3229 | +2.33% | -9.67% | 51 | +73.80% | +1.51% | -32.18% | 5 | +40.77% |

Blocked by: walkforward_total_return_not_positive, holdout_excess_return_not_positive, btc_walkforward_total_return_not_positive, eth_walkforward_total_return_not_positive, btc_holdout_excess_not_positive, eth_holdout_excess_not_positive

## Holdout concentration (honesty)

`ema_9_21` Kraken holdout excess: BTC +5.55% vs ETH +58.37%. #95 multi-asset bar (WF both > 0, mean holdout > 0): **PASS**. Balanced-holdout bar (also BTC holdout > 0 **and** ETH holdout > 0): **PASS**. Magnitude skew is reported, not gated — both signs must be positive, but ETH can still be much larger. A +50% ETH tail on one ~144-day window is not a live-capital claim.

## Yahoo Finance A/B (non-Kraken, not promotion)

Yahoo `range=max` downsamples crypto to monthly; this A/B uses `period1`/`period2` so the series stays daily. High/low are expanded to contain open/close when Yahoo's print is inconsistent. Closes are not Kraken Spot. This block cannot promote.

- `BTC-USD` 4378 bars: WF total +12.83%, holdout excess -9.28%
- `ETH-USD` 3229 bars: WF total +11.00%, holdout excess +202.27%

## Promotion decision

`ema_9_21` #95 multi-asset bar: **PASS**. `ema_9_21` balanced-holdout bar: **PASS**.
Cleared the balanced-holdout bar on Kraken daily BTC+ETH (research only): `ema_9_21`.
Documented paper-only switch: `PAPER_PROMOTE_EMA_9_21=true` (default false; `TRADING_MODE=paper` only). This report does not flip that flag and does not enable live.

Yahoo rows above are a longer non-Kraken A/B. Do not average them with Kraken prints. Do not copy YouTube or Yahoo-backtest return figures.
