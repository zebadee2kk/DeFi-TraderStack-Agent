# Expanded catalog harder-gates report

Generated: 2026-09-12T15:12:16.032192+00:00
Symbols: BTC-USD, BTC/USD, ETH-USD, ETH/USD, SOL/USD
Intervals: 1d (promotion uses Kraken 1d BTC+ETH only)
Baseline costs: fee=10 bps + slippage=5 bps. Gate C costs: fee=20 bps + slippage=10 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both. Gate C re-scores at 2× both legs.)
Walk-forward: train=180 test=60 step=60; holdout_fraction=20% on the full series (gate C / #96). Gate B windows use the same train/test/step and no holdout.
Selection: pre_registered_top1_mean_holdout_excess_among_combined_passers (ranking_key=mean_holdout_excess_among_combined_passers; catalog=expanded)

## Pre-registered gates (frozen before scoring)

Pre-registered harder gates (frozen before the Kraken window is scored). A — magnitude: both BTC and ETH holdout excess > 0 and min/max holdout ratio >= 0.25 (reject ETH-only magnitude). B — multi-window: three contiguous 240-bar Kraken daily slices; each uses #96 walk-forward (train=180, test=60, step=60) with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3 windows. C — fee stress: 2× fee and slippage (defaults 10+5 → 20+10 bps) must still clear #96 balanced signs. Combined requires #96 balanced-holdout and A and B and C. Ranking key (frozen before scoring): mean_holdout_excess_among_combined_passers — Kraken BTC+ETH mean holdout excess among combined-passers; full-catalog walk-forward rank is informational. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 stays false.

| gate | rule |
| --- | --- |
| A Magnitude | BTC and ETH holdout excess > 0 **and** min/max ratio ≥ 0.25 |
| B Multi-window | 3 contiguous 240-bar Kraken daily slices; BTC **and** ETH WF total > 0 in ≥ 2 of 3 |
| C Fee stress | 2× fees (20+10 bps) still clear #96 balanced signs |
| Combined | #96 balanced-holdout **and** A **and** B **and** C. Top-1 among those passers by `mean_holdout_excess_among_combined_passers`. A non-passer is never promoted. |

## Honesty

No candidate is rewritten to look profitable. Walk-forward folds never see the holdout tail. Combined-passers are names that clear #96 balanced-holdout and A and B and C. Ranking key (frozen before scoring): mean_holdout_excess_among_combined_passers — top-1 of 48 catalog members that also combined-pass, by Kraken BTC+ETH mean holdout excess (tie-break: candidate_id). Full-catalog walk-forward rank is informational and cannot promote a non-passer or block a passer. Yahoo Finance daily is a longer non-Kraken A/B and cannot enter ranking, magnitude, multi-window, or fee-stress averages. Pre-registered harder gates (frozen before the Kraken window is scored). A — magnitude: both BTC and ETH holdout excess > 0 and min/max holdout ratio >= 0.25 (reject ETH-only magnitude). B — multi-window: three contiguous 240-bar Kraken daily slices; each uses #96 walk-forward (train=180, test=60, step=60) with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3 windows. C — fee stress: 2× fee and slippage (defaults 10+5 → 20+10 bps) must still clear #96 balanced signs. Combined requires #96 balanced-holdout and A and B and C. Ranking key (frozen before scoring): mean_holdout_excess_among_combined_passers — Kraken BTC+ETH mean holdout excess among combined-passers; full-catalog walk-forward rank is informational. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 stays false. An honest FAIL / empty promotee is a successful research outcome — it is not rewritten as a soft PASS. This run does not flip PAPER_PROMOTE_EMA_9_21 (default false) and does not enable live. ema_9_21 #96 balanced-holdout: PASS. Gate A magnitude: FAIL. Gate B multi-window: FAIL. Gate C fee stress: PASS. Combined: FAIL. Combined-passer top-1 was ema_9_21_adx15 (PAPER_PROMOTE_EMA_9_21_ADX15 default false). Document the paper-only id; do not enable live.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Pre-registered catalog

Pre-registered expanded harder-gates catalog (frozen before the Kraken window is scored). Includes the #96/#97 balanced grid plus ADX 15/18/22/30 on EMA 9/21 and 12/26; faster EMA 5/13 and 8/21; slower EMA 13/34 and 21/55; ADX20 on 8/21 and 13/34; asset-local SMA200 risk-off on 12/26, 8/21, 13/34, and 12/26+ADX20; dual-mom lookbacks 10/50, 15/90, 21/90, 42/126; dip+vol lookbacks 10/15 and z=1.0 plus a 2× vol-filter variant. BTC SMA200 overlays on ema_9_21 / ema_12_26 / ema_20_50 when a Kraken BTC/USD daily series is bound. SOL is reported, not a gate. Yahoo never enters ranking or A/B/C averages. Do not grow this list after seeing PnL. PAPER_GARCH_SIZE and PAPER_PROMOTE_EMA_9_21 stay false unless a committed report names a paper-only pin and an operator flips it.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- BTC-USD@1d: 4378 Yahoo Finance (yfinance-compatible, non-Kraken) daily bars 2014-09-17T00:00:00+00:00 → 2026-09-11T00:00:00+00:00
- ETH-USD@1d: 3229 Yahoo Finance (yfinance-compatible, non-Kraken) daily bars 2017-11-09T00:00:00+00:00 → 2026-09-11T00:00:00+00:00

## `ema_9_21` PASS / FAIL

| gate | verdict | evidence |
| --- | --- | --- |
| A Magnitude | **FAIL** | BTC holdout +5.55%, ETH holdout +58.37%, ratio 0.095 (min 0.25); blocked by: holdout_magnitude_ratio_below_minimum |
| B Multi-window | **FAIL** | 1/3 windows passed — W1 oldest BTC +16.13% / ETH +53.49%; W2 middle BTC +10.44% / ETH -16.88%; W3 newest BTC -8.99% / ETH +32.74%; blocked by: multiwindow_fewer_than_min_passes |
| C Fee stress | **PASS** | 2× fees BTC WF +3.41% / ETH WF +13.59%; BTC holdout +3.33% / ETH holdout +56.99% |
| Combined | **FAIL** | #96 balanced-holdout PASS; A FAIL; B FAIL; C PASS |

### `ema_9_21` multi-window detail

| window | bars | first → last | BTC WF | ETH WF | passed |
| --- | ---: | --- | ---: | ---: | --- |
| W1 oldest | 240 | 2024-09-22T00:00:00+00:00 → 2025-05-19T00:00:00+00:00 | +16.13% | +53.49% | yes |
| W2 middle | 240 | 2025-05-20T00:00:00+00:00 → 2026-01-14T00:00:00+00:00 | +10.44% | -16.88% | no |
| W3 newest | 240 | 2026-01-15T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 | -8.99% | +32.74% | no |

## Combined-passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_combined_passers`. Only names that already clear #96 + A + B + C appear here. Empty table = no promotee (success).

| combined rank | id | mean HO excess | BTC HO | ETH HO | ratio | WF total | WF rank | promoted |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `ema_9_21_adx15` | +26.07% | +21.68% | +30.45% | 0.712 | +7.31% | 4 | yes |
| 2 | `ema_9_21_adx18` | +24.41% | +22.90% | +25.93% | 0.883 | +6.01% | 8 | no |
| 3 | `ema_12_26_adx18` | +18.11% | +17.37% | +18.85% | 0.921 | +6.90% | 5 | no |
| 4 | `ema_12_26_adx20` | +9.87% | +4.53% | +15.20% | 0.298 | +5.67% | 10 | no |

## Full catalog (informational WF rank; A/B/C overlay)

| WF rank | id | WF total | mean HO | BTC HO | ETH HO | ratio | A | B | C | #96 | combined | promoted |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| 1 | `ema_8_21` | +9.98% | +30.69% | +6.01% | +55.38% | 0.109 | FAIL | FAIL | PASS | PASS | FAIL | no |
| 2 | `ema_9_21` | +9.59% | +31.96% | +5.55% | +58.37% | 0.095 | FAIL | FAIL | PASS | PASS | FAIL | no |
| 3 | `ema_12_26` | +8.38% | +25.09% | +0.58% | +49.59% | 0.012 | FAIL | PASS | FAIL | PASS | FAIL | no |
| 4 | `ema_9_21_adx15` | +7.31% | +26.07% | +21.68% | +30.45% | 0.712 | PASS | PASS | PASS | PASS | PASS | yes |
| 5 | `ema_12_26_adx18` | +6.90% | +18.11% | +17.37% | +18.85% | 0.921 | PASS | PASS | PASS | PASS | PASS | no |
| 6 | `ema_12_26_adx15` | +6.55% | +19.55% | +15.97% | +23.14% | 0.690 | PASS | PASS | FAIL | PASS | FAIL | no |
| 7 | `ema_12_26_adx25` | +6.24% | +6.62% | +4.57% | +8.68% | 0.526 | PASS | FAIL | PASS | PASS | FAIL | no |
| 8 | `ema_9_21_adx18` | +6.01% | +24.41% | +22.90% | +25.93% | 0.883 | PASS | PASS | PASS | PASS | PASS | no |
| 9 | `ema_13_34` | +5.96% | +12.50% | -6.30% | +31.30% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 10 | `ema_12_26_adx20` | +5.67% | +9.87% | +4.53% | +15.20% | 0.298 | PASS | PASS | PASS | PASS | PASS | no |
| 11 | `dual_mom_21_90` | +5.61% | -16.78% | -12.62% | -20.94% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 12 | `ema_9_21_adx25` | +5.14% | +3.53% | +3.23% | +3.82% | 0.846 | PASS | FAIL | PASS | PASS | FAIL | no |
| 13 | `ema_20_50_adx20` | +5.08% | +0.94% | +2.34% | -0.46% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 14 | `ema_9_21_btc_ma200_riskoff` | +4.90% | +6.04% | +9.33% | +2.75% | 0.295 | PASS | PASS | FAIL | FAIL | FAIL | no |
| 15 | `ema_13_34_ma200_riskoff` | +4.86% | +6.04% | +9.33% | +2.75% | 0.295 | PASS | FAIL | PASS | PASS | FAIL | no |
| 16 | `ema_9_21_ma200_riskoff` | +4.67% | +6.04% | +9.33% | +2.75% | 0.295 | PASS | FAIL | PASS | PASS | FAIL | no |
| 17 | `ema_9_21_adx20` | +4.60% | +16.43% | +10.04% | +22.82% | 0.440 | PASS | FAIL | PASS | PASS | FAIL | no |
| 18 | `dual_mom_42_126` | +4.58% | +2.57% | +1.94% | +3.20% | 0.607 | PASS | FAIL | FAIL | PASS | FAIL | no |
| 19 | `ema_20_50_ma200_riskoff` | +4.55% | +0.22% | -2.30% | +2.75% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 20 | `ema_8_21_ma200_riskoff` | +4.54% | +6.04% | +9.33% | +2.75% | 0.295 | PASS | FAIL | PASS | PASS | FAIL | no |
| 21 | `dual_mom_21_63` | +4.47% | +7.32% | +1.85% | +12.78% | 0.145 | FAIL | PASS | FAIL | FAIL | FAIL | no |
| 22 | `ema_13_34_adx20` | +4.44% | +3.74% | +3.05% | +4.43% | 0.689 | PASS | FAIL | PASS | PASS | FAIL | no |
| 23 | `ema_8_21_adx20` | +4.42% | +15.30% | +10.59% | +20.02% | 0.529 | PASS | FAIL | PASS | PASS | FAIL | no |
| 24 | `ema_12_26_ma200_riskoff` | +4.28% | +6.04% | +9.33% | +2.75% | 0.295 | PASS | FAIL | PASS | PASS | FAIL | no |
| 25 | `dual_mom_21_126` | +4.18% | -6.35% | +4.12% | -16.83% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 26 | `ema_12_26_adx22` | +3.79% | +5.59% | +8.10% | +3.08% | 0.380 | PASS | FAIL | PASS | PASS | FAIL | no |
| 27 | `ema_9_21_adx22` | +3.53% | +5.79% | +7.27% | +4.30% | 0.591 | PASS | FAIL | PASS | PASS | FAIL | no |
| 28 | `dual_mom_63_126` | +3.40% | -3.69% | -9.92% | +2.53% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 29 | `ema_12_26_btc_ma200_riskoff` | +3.33% | +6.04% | +9.33% | +2.75% | 0.295 | PASS | PASS | FAIL | FAIL | FAIL | no |
| 30 | `ema_21_55` | +2.85% | +9.66% | -6.21% | +25.53% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 31 | `dip_mr_20_2_0_vol` | +2.59% | -16.21% | -11.99% | -20.44% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 32 | `ema_9_21_adx30` | +2.49% | +3.35% | -5.42% | +12.12% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 33 | `ema_12_26_adx30` | +2.30% | +3.35% | -5.42% | +12.12% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 34 | `ema_12_26_adx20_ma200_riskoff` | +2.09% | -2.18% | -3.52% | -0.84% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 35 | `ema_20_50` | +2.00% | +10.06% | -0.01% | +20.14% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 36 | `dip_mr_10_1_5_vol` | +1.48% | -20.45% | -14.93% | -25.97% | n/a | FAIL | PASS | FAIL | FAIL | FAIL | no |
| 37 | `ema_5_13` | +1.44% | +35.04% | +36.86% | +33.21% | 0.901 | PASS | PASS | FAIL | FAIL | FAIL | no |
| 38 | `ema_20_50_btc_ma200_riskoff` | +0.29% | +0.22% | -2.30% | +2.75% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 39 | `dip_mr_15_1_5_vol` | +0.22% | -17.81% | -13.49% | -22.12% | n/a | FAIL | PASS | FAIL | FAIL | FAIL | no |
| 40 | `ema_9_21_garch` | +0.08% | +6.08% | -16.31% | +28.48% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 41 | `dip_mr_20_1_5_vol` | +0.03% | -14.53% | -8.96% | -20.09% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 42 | `dip_mr_20_1_5_vol2` | +0.01% | -14.53% | -8.96% | -20.09% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 43 | `dual_mom_15_90` | -0.18% | -11.42% | -8.62% | -14.23% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 44 | `dip_mr_20_1_0_vol` | -0.45% | -22.11% | -15.35% | -28.86% | n/a | FAIL | PASS | FAIL | FAIL | FAIL | no |
| 45 | `dual_mom_12_60` | -0.65% | +1.97% | +1.73% | +2.22% | 0.777 | PASS | PASS | FAIL | FAIL | FAIL | no |
| 46 | `dual_mom_10_50` | -1.31% | -2.50% | -9.55% | +4.56% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 47 | `ema_20_50_garch` | -6.35% | -11.40% | -23.59% | +0.79% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 48 | `ema_50_200` | -8.63% | -10.21% | -3.22% | -17.20% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |

## #96 eligible re-check (ADX / SMA variants)

These names cleared #96 balanced-holdout on the committed 2026-09-12 window (or are the pre-registered ADX/SMA set). They are re-scored under A–C. Under the expanded ranking key a combined-passer **can** be selected even if it is not walk-forward #1. A non-passer is still never promoted.

| id | #96 | A | B | C | combined | combined rank | note |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| `ema_12_26` | PASS | FAIL | PASS | FAIL | FAIL | — | combined FAIL |
| `ema_12_26_adx25` | PASS | PASS | FAIL | PASS | FAIL | — | combined FAIL |
| `ema_12_26_adx20` | PASS | PASS | PASS | PASS | PASS | 4 | combined PASS but not top-1 among passers |
| `ema_9_21_adx25` | PASS | PASS | FAIL | PASS | FAIL | — | combined FAIL |
| `ema_9_21_ma200_riskoff` | PASS | PASS | FAIL | PASS | FAIL | — | combined FAIL |
| `ema_9_21_adx20` | PASS | PASS | FAIL | PASS | FAIL | — | combined FAIL |

## Yahoo Finance A/B (non-Kraken, not promotion)

Yahoo rows are a longer non-Kraken A/B. They are never averaged into ranking, magnitude, multi-window, or fee stress. A negative Yahoo BTC holdout cannot be washed out by a large ETH print, and a positive Yahoo ETH print cannot promote.

- BTC-USD 4378 bars: WF total +12.83%, holdout excess -9.28% (non-Kraken A/B; not promotion)
- ETH-USD 3229 bars: WF total +11.00%, holdout excess +202.27% (non-Kraken A/B; not promotion)

## Promotion decision

`ema_9_21` #96 balanced-holdout: **PASS**. Gate A: **FAIL**. Gate B: **FAIL**. Gate C: **PASS**. Combined: **FAIL**.
Cleared the combined harder-gates bar on Kraken daily BTC+ETH and ranked top-1 among combined-passers by `mean_holdout_excess_among_combined_passers` (research only): `ema_9_21_adx15` (mean holdout excess=+26.07%, WF rank=4).
Documented paper-only switch: `PAPER_PROMOTE_EMA_9_21_ADX15=true` (default **false**; `TRADING_MODE=paper` only). This report does not flip that flag, does not flip `PAPER_PROMOTE_EMA_9_21`, and does not enable live.

Yahoo rows above are a longer non-Kraken A/B. Do not average them with Kraken prints. Do not copy YouTube or Yahoo-backtest return figures. Do not flip `PAPER_PROMOTE_EMA_9_21`.
