# Strategy search report

Generated: 2026-09-12T13:02:30.871472+00:00
Symbols: BTC/USD, ETH/USD, SOL/USD
Costs: fee=10 bps + slippage=5 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both.)
Walk-forward: train=180 test=60 step=60 warmup=31; holdout_fraction=20%
Promotion floor: WF excess > 0, min trades=3, holdout confirmation=on
Selection: pre_registered_top1 (K=13)

## Honesty

No candidate is rewritten to look profitable. Walk-forward ranking never sees the holdout tail. Selection is pre-registered top-1 of 13 catalog members (Bonferroni analogue: one promotion decision, not K independent promotions). A selected candidate is promoted only if fee-aware walk-forward mean excess return is strictly above the floor and min trades are met, and holdout mean excess return is also strictly above the floor. No candidate cleared the bar on this data; paper promotion must stay off.

## Multiple testing

K catalog members are scored on the same research window. We do not treat every excess>0 as a discovered edge. At most the single pre-registered top-1 (by walk-forward mean excess return, min-trades filter) may be promoted, and only if it also clears the configured floors. A classical Bonferroni p-cut would be 0.05/13 ≈ 0.0038; this search has no per-fold t-test, so holdout confirmation is the out-of-sample control instead of a p-value.

## Ranked candidates (walk-forward mean excess after fees)

| rank | id | family | WF excess | WF total | WF trades | holdout excess | eligible | promoted |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `momentum_6` | momentum | +1.06% | -0.19% | 17 | -2.96% | no | no |
| 2 | `mean_reversion_20_2_0` | mean_reversion | +0.99% | -0.26% | 18 | -1.04% | no | no |
| 3 | `momentum_12_strict` | momentum | +0.99% | -0.26% | 8 | -0.97% | no | no |
| 4 | `mean_reversion_20_1_5` | mean_reversion | +0.87% | -0.38% | 28 | -2.06% | no | no |
| 5 | `ma_cross_10_30_wide` | ma_cross | +0.81% | -0.44% | 19 | +0.06% | yes | no |
| 6 | `mean_reversion_10_1_5` | mean_reversion | +0.76% | -0.49% | 29 | -3.29% | no | no |
| 7 | `momentum_12` | momentum | +0.46% | -0.79% | 35 | -2.15% | no | no |
| 8 | `ma_cross_5_20` | ma_cross | +0.39% | -0.86% | 27 | -3.06% | no | no |
| 9 | `ma_cross_10_30` | ma_cross | +0.27% | -0.98% | 28 | -3.58% | no | no |
| 10 | `ma_always_on_10_30` | ma_cross | +0.23% | -1.02% | 35 | -3.35% | no | no |
| 11 | `momentum_24` | momentum | -0.07% | -1.32% | 38 | -2.38% | no | no |
| — | `ma_cross_20_50` | ma_cross | n/a | n/a | 0 | n/a | no | no |
| — | `mean_reversion_40_2_0` | mean_reversion | n/a | n/a | 0 | n/a | no | no |

## Skipped optional families

- `liquidation_z_fade` (liquidation_z): fade liquidation z-score |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.
- `cross_venue_fade` (cross_venue): fade cross-venue divergence z |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.

## Promotion decision

**No candidate cleared the bar.** Leave `PAPER_PROMOTE_SEARCHED_STRATEGIES=false`. This is not an edge.
Pre-registered top-1 by WF excess was `momentum_6` (WF excess=+1.06%, holdout excess=-2.96%; blocked by: holdout_excess_return_not_positive).
