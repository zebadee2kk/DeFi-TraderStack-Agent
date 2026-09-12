# Magnitude / multi-window / fee-stress report

Generated: 2026-09-12T14:58:08.771576+00:00
Symbols: BTC-USD, BTC/USD, ETH-USD, ETH/USD, SOL/USD
Intervals: 1d (promotion uses Kraken 1d BTC+ETH only)
Baseline costs: fee=10 bps + slippage=5 bps. Gate C costs: fee=20 bps + slippage=10 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both. Gate C re-scores at 2× both legs.)
Walk-forward: train=180 test=60 step=60; holdout_fraction=20% on the full series (gate C / #96). Gate B windows use the same train/test/step and no holdout.
Selection: pre_registered_top1 (catalog=balanced)

## Pre-registered gates (frozen before scoring)

Pre-registered harder gates (frozen before the Kraken window is scored). A — magnitude: both BTC and ETH holdout excess > 0 and min/max holdout ratio >= 0.25 (reject ETH-only magnitude). B — multi-window: three contiguous 240-bar Kraken daily slices; each uses #96 walk-forward (train=180, test=60, step=60) with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3 windows. C — fee stress: 2× fee and slippage (defaults 10+5 → 20+10 bps) must still clear #96 balanced signs. Combined promote requires #96 balanced-holdout and A and B and C and pre-registered top-1. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 stays false.

| gate | rule |
| --- | --- |
| A Magnitude | BTC and ETH holdout excess > 0 **and** min/max ratio ≥ 0.25 |
| B Multi-window | 3 contiguous 240-bar Kraken daily slices; BTC **and** ETH WF total > 0 in ≥ 2 of 3 |
| C Fee stress | 2× fees (20+10 bps) still clear #96 balanced signs |
| Combined | #96 balanced-holdout **and** A **and** B **and** C **and** pre-registered top-1. #2 cannot skip a failing #1. |

## Honesty

No candidate is rewritten to look profitable. Walk-forward ranking never sees the holdout tail. Selection is pre-registered top-1 of 20 catalog members by baseline Kraken BTC+ETH walk-forward mean total return. Yahoo Finance daily is a longer non-Kraken A/B and cannot enter ranking, magnitude, multi-window, or fee-stress averages. Pre-registered harder gates (frozen before the Kraken window is scored). A — magnitude: both BTC and ETH holdout excess > 0 and min/max holdout ratio >= 0.25 (reject ETH-only magnitude). B — multi-window: three contiguous 240-bar Kraken daily slices; each uses #96 walk-forward (train=180, test=60, step=60) with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3 windows. C — fee stress: 2× fee and slippage (defaults 10+5 → 20+10 bps) must still clear #96 balanced signs. Combined promote requires #96 balanced-holdout and A and B and C and pre-registered top-1. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 stays false. An honest FAIL on A, B, or C is a successful research outcome — it is not rewritten as a soft PASS. This run does not flip PAPER_PROMOTE_EMA_9_21 (default false) and does not enable live. ema_9_21 #96 balanced-holdout: PASS. Gate A magnitude: FAIL. Gate B multi-window: FAIL. Gate C fee stress: PASS. Combined: FAIL. No candidate cleared the combined harder-gates bar; paper promotion must stay off.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Pre-registered catalog

Pre-registered balanced-holdout grid (frozen before the Kraken window is scored): #95 EMA 9/21 and 12/26 ± ADX 20/25; slower EMA 20/50 and 50/200 (± ADX 20 on 20/50); dual-mom lookbacks 12/60, 21/63, 21/126, 63/126; buy-the-dip z=1.5 and z=2.0 with the same vol filter; asset-local SMA200 risk-off on ema_9_21 and ema_20_50; BTC SMA200 overlay on ema_9_21 when a Kraken BTC/USD daily series is bound; GARCH size overlays on ema_9_21 and ema_20_50 only. SOL is reported, not a promotion gate. Yahoo never enters the promotion average. PAPER_GARCH_SIZE stays false unless a GARCH-sized name clears.

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

## Ranked candidates (baseline Kraken BTC+ETH WF total; A/B/C overlay)

| rank | id | WF total | BTC HO | ETH HO | ratio | A | B | C | #96 | combined | promoted |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| 1 | `ema_9_21` | +9.59% | +5.55% | +58.37% | 0.095 | FAIL | FAIL | PASS | PASS | FAIL | no |
| 2 | `ema_12_26` | +8.38% | +0.58% | +49.59% | 0.012 | FAIL | PASS | FAIL | PASS | FAIL | no |
| 3 | `ema_12_26_adx25` | +6.24% | +4.57% | +8.68% | 0.526 | PASS | FAIL | PASS | PASS | FAIL | no |
| 4 | `ema_12_26_adx20` | +5.67% | +4.53% | +15.20% | 0.298 | PASS | PASS | PASS | PASS | PASS | no |
| 5 | `ema_9_21_adx25` | +5.14% | +3.23% | +3.82% | 0.846 | PASS | FAIL | PASS | PASS | FAIL | no |
| 6 | `ema_20_50_adx20` | +5.08% | +2.34% | -0.46% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 7 | `ema_9_21_btc_ma200_riskoff` | +4.90% | +9.33% | +2.75% | 0.295 | PASS | PASS | FAIL | FAIL | FAIL | no |
| 8 | `ema_9_21_ma200_riskoff` | +4.67% | +9.33% | +2.75% | 0.295 | PASS | FAIL | PASS | PASS | FAIL | no |
| 9 | `ema_9_21_adx20` | +4.60% | +10.04% | +22.82% | 0.440 | PASS | FAIL | PASS | PASS | FAIL | no |
| 10 | `ema_20_50_ma200_riskoff` | +4.55% | -2.30% | +2.75% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 11 | `dual_mom_21_63` | +4.47% | +1.85% | +12.78% | 0.145 | FAIL | PASS | FAIL | FAIL | FAIL | no |
| 12 | `dual_mom_21_126` | +4.18% | +4.12% | -16.83% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 13 | `dual_mom_63_126` | +3.40% | -9.92% | +2.53% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 14 | `dip_mr_20_2_0_vol` | +2.59% | -11.99% | -20.44% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 15 | `ema_20_50` | +2.00% | -0.01% | +20.14% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 16 | `ema_9_21_garch` | +0.08% | -16.31% | +28.48% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 17 | `dip_mr_20_1_5_vol` | +0.03% | -8.96% | -20.09% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 18 | `dual_mom_12_60` | -0.65% | +1.73% | +2.22% | 0.777 | PASS | PASS | FAIL | FAIL | FAIL | no |
| 19 | `ema_20_50_garch` | -6.35% | -23.59% | +0.79% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |
| 20 | `ema_50_200` | -8.63% | -3.22% | -17.20% | n/a | FAIL | FAIL | FAIL | FAIL | FAIL | no |

## #96 eligible non-promoted re-check (ADX / SMA variants)

These names cleared #96 balanced-holdout on the committed 2026-09-12 window (or are the pre-registered ADX/SMA set) but were not top-1. They are re-scored under A–C. They **cannot** be promoted unless they are the pre-registered top-1 *and* clear the new gates. A better magnitude ratio on #2 does not unlock promotion when `ema_9_21` remains top-1.

| id | #96 | A | B | C | combined | note |
| --- | --- | --- | --- | --- | --- | --- |
| `ema_12_26` | PASS | FAIL | PASS | FAIL | FAIL | not top-1; cannot skip |
| `ema_12_26_adx25` | PASS | PASS | FAIL | PASS | FAIL | not top-1; cannot skip |
| `ema_12_26_adx20` | PASS | PASS | PASS | PASS | PASS | not top-1; cannot skip |
| `ema_9_21_adx25` | PASS | PASS | FAIL | PASS | FAIL | not top-1; cannot skip |
| `ema_9_21_ma200_riskoff` | PASS | PASS | FAIL | PASS | FAIL | not top-1; cannot skip |
| `ema_9_21_adx20` | PASS | PASS | FAIL | PASS | FAIL | not top-1; cannot skip |

## Yahoo Finance A/B (non-Kraken, not promotion)

Yahoo rows are a longer non-Kraken A/B. They are never averaged into ranking, magnitude, multi-window, or fee stress. A negative Yahoo BTC holdout cannot be washed out by a large ETH print, and a positive Yahoo ETH print cannot promote.

- BTC-USD 4378 bars: WF total +12.83%, holdout excess -9.28% (non-Kraken A/B; not promotion)
- ETH-USD 3229 bars: WF total +11.00%, holdout excess +202.27% (non-Kraken A/B; not promotion)

## Promotion decision

`ema_9_21` #96 balanced-holdout: **PASS**. Gate A: **FAIL**. Gate B: **FAIL**. Gate C: **PASS**. Combined: **FAIL**.
**No candidate cleared the combined harder-gates bar.** An honest FAIL is the successful outcome. Leave `PAPER_PROMOTE_EMA_9_21=false` and `PAPER_PROMOTE_SEARCHED_STRATEGIES=false`.
Pre-registered top-1 by baseline BTC+ETH WF total was `ema_9_21` (WF total=+9.59%, holdout ratio=0.095; blocked by: A magnitude (holdout_magnitude_ratio_below_minimum); B multi-window (multiwindow_fewer_than_min_passes)).
`ema_9_21` does **not** clear the combined harder-gates bar on this window.

Yahoo rows above are a longer non-Kraken A/B. Do not average them with Kraken prints. Do not copy YouTube or Yahoo-backtest return figures. Do not flip `PAPER_PROMOTE_EMA_9_21`.
