# Dual-print daily strategy search

Generated: 2026-09-12T16:13:58.885071+00:00
Catalog K scored=70 (frozen core=65; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars=720).
`multi_venue_bar_preregistered=true`; `can_average_venues=false`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered dual-print bar (frozen before any Kraken or Binance.US score). Combined on each print is #96 balanced-holdout and A magnitude and B multi-window and C 2× fees. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Pre-registered dual-print catalog (frozen before any Kraken or Binance.US pull). Superset of the #99 expanded harder-gates grid (K=45 core) plus more EMA pairs (6/19, 10/30, 15/45, 21/63), ADX 12/16 on 9/21 and 12/26, ADX15 on 8/21 and 20/50, asset-local SMA100 risk-off on 9/21 and 12/26, SMA200 risk-off on 9/21+ADX15, dual-mom 8/40 12/90 21/252, dip+vol lookback 30 and z=1.25, and candle-only vol-regime wrappers on ema_9_21 / ema_12_26. BTC SMA200 overlays on 9/21, 12/26, 20/50, 8/21, and 13/34 when a venue-local BTC daily series is bound. Liquidation / funding / OI feature voters are not in this K: no aligned historical series is available on public Spot OHLC, and they are skipped rather than zero-filled. SOL is reported, not a gate. Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=70 (core ids frozen at 65; overlays 5 when BTC is bound). Kraken combined-passers: 5. Binance combined-passers: 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered dual-print bar (frozen before any Kraken or Binance.US score). Combined on each print is #96 balanced-holdout and A magnitude and B multi-window and C 2× fees. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C; rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily bars ending before the primary Kraken first bar; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Pre-registered catalog

Pre-registered dual-print catalog (frozen before any Kraken or Binance.US pull). Superset of the #99 expanded harder-gates grid (K=45 core) plus more EMA pairs (6/19, 10/30, 15/45, 21/63), ADX 12/16 on 9/21 and 12/26, ADX15 on 8/21 and 20/50, asset-local SMA100 risk-off on 9/21 and 12/26, SMA200 risk-off on 9/21+ADX15, dual-mom 8/40 12/90 21/252, dip+vol lookback 30 and z=1.25, and candle-only vol-regime wrappers on ema_9_21 / ema_12_26. BTC SMA200 overlays on 9/21, 12/26, 20/50, 8/21, and 13/34 when a venue-local BTC daily series is bound. Liquidation / funding / OI feature voters are not in this K: no aligned historical series is available on public Spot OHLC, and they are skipped rather than zero-filled. SOL is reported, not a gate. Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `ema_9_21`, `ema_12_26`, `ema_9_21_adx20`, `ema_12_26_adx20`, `ema_9_21_adx25`, `ema_12_26_adx25`, `ema_20_50`, `ema_50_200`, `ema_20_50_adx20`, `ema_9_21_garch`, `ema_20_50_garch`, `dual_mom_12_60`, `dual_mom_21_63`, `dual_mom_21_126`, `dual_mom_63_126`, `dip_mr_20_1_5_vol`, `dip_mr_20_2_0_vol`, `ema_9_21_ma200_riskoff`, `ema_20_50_ma200_riskoff`, `ema_9_21_adx15`, `ema_12_26_adx15`, `ema_9_21_adx18`, `ema_12_26_adx18`, `ema_9_21_adx22`, `ema_12_26_adx22`, `ema_9_21_adx30`, `ema_12_26_adx30`, `ema_5_13`, `ema_8_21`, `ema_13_34`, `ema_21_55`, `ema_8_21_adx20`, `ema_13_34_adx20`, `ema_12_26_ma200_riskoff`, `ema_8_21_ma200_riskoff`, `ema_13_34_ma200_riskoff`, `ema_12_26_adx20_ma200_riskoff`, `dual_mom_10_50`, `dual_mom_15_90`, `dual_mom_21_90`, `dual_mom_42_126`, `dip_mr_10_1_5_vol`, `dip_mr_15_1_5_vol`, `dip_mr_20_1_0_vol`, `dip_mr_20_1_5_vol2`, `ema_6_19`, `ema_10_30`, `ema_15_45`, `ema_21_63`, `ema_9_21_adx12`, `ema_12_26_adx12`, `ema_9_21_adx16`, `ema_12_26_adx16`, `ema_8_21_adx15`, `ema_20_50_adx15`, `ema_9_21_ma100_riskoff`, `ema_12_26_ma100_riskoff`, `ema_9_21_adx15_ma200_riskoff`, `dual_mom_8_40`, `dual_mom_12_90`, `dual_mom_21_252`, `dip_mr_30_1_5_vol`, `dip_mr_20_1_25_vol`, `ema_9_21_vol_regime`, `ema_12_26_vol_regime`.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2024-09-22T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@1d: 720 committed binance_us_spot daily bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot daily bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720
- Span: 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00
- Overlaps primary window: no
- Fail-closed reason: —

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping series fails closed. Empty Binance means zero dual-print passers (success).

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only names that already clear combined on **both** prints appear here. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These names cleared #96+A+B+C on the Kraken primary window. They are **not** promotees unless they also appear in the dual-print table.

| rank | id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `ema_9_21_adx15` | +26.07% | +21.68% | +30.45% | 0.712 | PASS | PASS | PASS | PASS | no |
| 2 | `ema_8_21_adx15` | +25.08% | +22.21% | +27.95% | 0.794 | PASS | PASS | PASS | PASS | no |
| 3 | `ema_9_21_adx18` | +24.41% | +22.90% | +25.93% | 0.883 | PASS | PASS | PASS | PASS | no |
| 4 | `ema_12_26_adx18` | +18.11% | +17.37% | +18.85% | 0.921 | PASS | PASS | PASS | PASS | no |
| 5 | `ema_12_26_adx20` | +9.87% | +4.53% | +15.20% | 0.298 | PASS | PASS | PASS | PASS | no |

## Binance.US combined-passers (informational)

These names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken.

| id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Full catalog (informational)

| id | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO |
| --- | :---: | :---: | :---: | ---: | ---: |
| `ema_8_21` | FAIL | FAIL | no | +30.69% | -15.66% |
| `ema_9_21` | FAIL | FAIL | no | +31.96% | -15.80% |
| `ema_9_21_adx12` | FAIL | FAIL | no | +33.24% | -15.80% |
| `ema_10_30` | FAIL | FAIL | no | +23.71% | -23.73% |
| `ema_12_26` | FAIL | FAIL | no | +25.09% | -23.73% |
| `ema_12_26_adx12` | FAIL | FAIL | no | +26.30% | -23.73% |
| `ema_8_21_adx15` | PASS | FAIL | no | +25.08% | -15.66% |
| `ema_9_21_adx15` | PASS | FAIL | no | +26.07% | -15.80% |
| `ema_12_26_adx16` | FAIL | FAIL | no | +19.81% | -23.73% |
| `ema_12_26_adx18` | PASS | FAIL | no | +18.11% | -14.58% |
| `ema_12_26_adx15` | FAIL | FAIL | no | +19.55% | -23.73% |
| `ema_12_26_adx25` | FAIL | FAIL | no | +6.62% | -15.46% |
| `ema_9_21_adx18` | PASS | FAIL | no | +24.41% | -7.67% |
| `ema_9_21_adx16` | FAIL | FAIL | no | +26.21% | -15.80% |
| `ema_13_34` | FAIL | FAIL | no | +12.50% | -33.11% |
| `ema_6_19` | FAIL | FAIL | no | +33.08% | +6.53% |
| `ema_12_26_adx20` | PASS | FAIL | no | +9.87% | -14.78% |
| `dual_mom_21_90` | FAIL | FAIL | no | -16.78% | -9.70% |
| `ema_8_21_btc_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -15.15% |
| `ema_9_21_adx25` | FAIL | FAIL | no | +3.53% | -14.00% |
| `ema_20_50_adx20` | FAIL | FAIL | no | +0.94% | -10.73% |
| `ema_21_63` | FAIL | FAIL | no | +7.80% | -29.54% |
| `ema_9_21_btc_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -13.73% |
| `ema_13_34_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -31.28% |
| `ema_9_21_vol_regime` | FAIL | FAIL | no | +19.66% | -25.89% |
| `ema_9_21_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -19.79% |
| `ema_9_21_adx20` | FAIL | FAIL | no | +16.43% | -9.72% |
| `dual_mom_42_126` | FAIL | FAIL | no | +2.57% | -5.36% |
| `ema_20_50_ma200_riskoff` | FAIL | FAIL | no | +0.22% | -22.02% |
| `ema_8_21_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -21.02% |
| `dual_mom_21_63` | FAIL | FAIL | no | +7.32% | -28.06% |
| `ema_13_34_adx20` | FAIL | FAIL | no | +3.74% | -18.88% |
| `ema_8_21_adx20` | FAIL | FAIL | no | +15.30% | -11.43% |
| `ema_12_26_vol_regime` | FAIL | FAIL | no | +17.92% | -30.57% |
| `ema_12_26_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -22.64% |
| `dual_mom_21_126` | FAIL | FAIL | no | -6.35% | -11.48% |
| `ema_12_26_adx22` | FAIL | FAIL | no | +5.59% | -20.87% |
| `ema_9_21_adx22` | FAIL | FAIL | no | +5.79% | -18.96% |
| `dual_mom_63_126` | FAIL | FAIL | no | -3.69% | -6.87% |
| `ema_12_26_btc_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -16.93% |
| `ema_21_55` | FAIL | FAIL | no | +9.66% | -25.24% |
| `ema_9_21_adx15_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -19.79% |
| `dip_mr_20_2_0_vol` | FAIL | FAIL | no | -16.21% | +3.00% |
| `ema_9_21_ma100_riskoff` | FAIL | FAIL | no | +21.77% | +4.49% |
| `ema_9_21_adx30` | FAIL | FAIL | no | +3.35% | -17.80% |
| `ema_15_45` | FAIL | FAIL | no | +21.40% | -30.65% |
| `ema_12_26_adx30` | FAIL | FAIL | no | +3.35% | -13.26% |
| `ema_13_34_btc_ma200_riskoff` | FAIL | FAIL | no | +6.04% | -26.32% |
| `ema_12_26_adx20_ma200_riskoff` | FAIL | FAIL | no | -2.18% | -16.12% |
| `ema_20_50` | FAIL | FAIL | no | +10.06% | -28.05% |
| `ema_12_26_ma100_riskoff` | FAIL | FAIL | no | +16.61% | +0.15% |
| `dip_mr_10_1_5_vol` | FAIL | FAIL | no | -20.45% | -13.16% |
| `ema_5_13` | FAIL | FAIL | no | +35.04% | +9.00% |
| `dual_mom_8_40` | FAIL | FAIL | no | +9.12% | -20.26% |
| `dip_mr_20_1_25_vol` | FAIL | FAIL | no | -17.35% | +3.30% |
| `dual_mom_12_90` | FAIL | FAIL | no | -21.93% | +14.67% |
| `ema_20_50_btc_ma200_riskoff` | FAIL | FAIL | no | +0.22% | -17.99% |
| `dip_mr_15_1_5_vol` | FAIL | FAIL | no | -17.81% | +3.50% |
| `ema_20_50_adx15` | FAIL | FAIL | no | +2.22% | -28.05% |
| `ema_9_21_garch` | FAIL | FAIL | no | +6.08% | -37.91% |
| `dip_mr_20_1_5_vol` | FAIL | FAIL | no | -14.53% | +1.51% |
| `dip_mr_20_1_5_vol2` | FAIL | FAIL | no | -14.53% | +1.51% |
| `dual_mom_15_90` | FAIL | FAIL | no | -11.42% | +4.40% |
| `dip_mr_20_1_0_vol` | FAIL | FAIL | no | -22.11% | -0.15% |
| `dual_mom_12_60` | FAIL | FAIL | no | +1.97% | -8.63% |
| `dual_mom_10_50` | FAIL | FAIL | no | -2.50% | -5.26% |
| `dip_mr_30_1_5_vol` | FAIL | FAIL | no | -19.54% | +11.47% |
| `ema_20_50_garch` | FAIL | FAIL | no | -11.40% | -44.04% |
| `ema_50_200` | FAIL | FAIL | no | -10.21% | +5.17% |
| `dual_mom_21_252` | FAIL | FAIL | no | -5.74% | -19.98% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational): 5 (`ema_9_21_adx15`, `ema_8_21_adx15`, `ema_9_21_adx18`, `ema_12_26_adx18`, `ema_12_26_adx20`). A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Dual-print top-1: **none**. Do not add a new promote flag. Leave `PAPER_PROMOTE_EMA_9_21` and `PAPER_PROMOTE_EMA_9_21_ADX15` false.
- Do not enable live. Do not fabricate PnL.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window.
