# Bollinger band-fade / mean-reversion dual-print (BTC+ETH; SOL optional)

Generated: 2026-09-12T20:39:47.032881+00:00
Catalog K scored=8 (frozen core=8; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars BTC=720 / ETH=720 / SOL=720).
`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered Bollinger band-fade / mean-reversion dual-print bar (frozen before any Kraken or Binance.US score). Treatment: each asset uses its own SMA(period) ± k × sample stdev (`sample_stdev_ddof_1`) over the same window through t (decision `closes_through_t`). Fade-to-mid (`bb_fade_{{20x2,20x2_5,40x2}}`) is short when close > upper, long when close < lower, and `flat_when_inside_bands` (close on or between the bands). Long-only fade (`bb_lo_fade_{{20x2,40x2}}`) is long below the lower band and flat otherwise. Squeeze-breakout CONTRAST (`bb_squeeze_break_{20,40}`; k=2; `expand_from_p20_of_prior_120_bandwidth_long_above_mid`): long when prior bandwidth ≤ 20th percentile of the previous 120 bandwidths and current bandwidth expands and close > mid; flat otherwise. Distinct from existing `mean_reversion_*` catalog ids (`mean_reversion_20_1_5`, `mean_reversion_20_2_0`, `mean_reversion_10_1_5`, `mean_reversion_40_2_0`, and the #108 4h extras). Those are z-score voters (optionally RANGE-regime gated) on charts-spot / 4h bars. This family uses explicit SMA ± k × sample stdev bands, `flat_when_inside_bands` (not exit-at-mid), long-only fade, and a squeeze-breakout contrast; no RANGE gate; daily Kraken 720 + Binance.US older-720. Band math for `bb_fade_20x2` matches `mean_reversion_20_2_0` without the regime filter — still a different id and a different print, not a #108 reprint. This is not trend, not cross-section (#117), not Donchian (#118), and not TSMOM sign-of-return (#119). Decision at bar t; fill `next_bar_open` (t+1 open — no look-ahead into the fill bar). Each asset uses its own closes; a missing/short series is skipped, never zero-filled. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, not TSMOM, and not a carry/basis family. Frozen catalog (K=8): fade-to-mid (`bb_fade_{20x2,20x2_5,40x2}`), long-only fade (`bb_lo_fade_{20x2,40x2}`), squeeze-breakout CONTRAST (`bb_squeeze_break_{20,40}`; `expand_from_p20_of_prior_120_bandwidth_long_above_mid`), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Bands are built from venue-local closes; a missing series is skipped, never zero-filled. Distinct from existing `mean_reversion_*` catalog ids (`mean_reversion_20_1_5`, `mean_reversion_20_2_0`, `mean_reversion_10_1_5`, `mean_reversion_40_2_0`, and the #108 4h extras). Those are z-score voters (optionally RANGE-regime gated) on charts-spot / 4h bars. This family uses explicit SMA ± k × sample stdev bands, `flat_when_inside_bands` (not exit-at-mid), long-only fade, and a squeeze-breakout contrast; no RANGE gate; daily Kraken 720 + Binance.US older-720. Band math for `bb_fade_20x2` matches `mean_reversion_20_2_0` without the regime filter — still a different id and a different print, not a #108 reprint. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=8 (core ids frozen at 8). Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered Bollinger band-fade / mean-reversion dual-print bar (frozen before any Kraken or Binance.US score). Treatment: each asset uses its own SMA(period) ± k × sample stdev (`sample_stdev_ddof_1`) over the same window through t (decision `closes_through_t`). Fade-to-mid (`bb_fade_{{20x2,20x2_5,40x2}}`) is short when close > upper, long when close < lower, and `flat_when_inside_bands` (close on or between the bands). Long-only fade (`bb_lo_fade_{{20x2,40x2}}`) is long below the lower band and flat otherwise. Squeeze-breakout CONTRAST (`bb_squeeze_break_{20,40}`; k=2; `expand_from_p20_of_prior_120_bandwidth_long_above_mid`): long when prior bandwidth ≤ 20th percentile of the previous 120 bandwidths and current bandwidth expands and close > mid; flat otherwise. Distinct from existing `mean_reversion_*` catalog ids (`mean_reversion_20_1_5`, `mean_reversion_20_2_0`, `mean_reversion_10_1_5`, `mean_reversion_40_2_0`, and the #108 4h extras). Those are z-score voters (optionally RANGE-regime gated) on charts-spot / 4h bars. This family uses explicit SMA ± k × sample stdev bands, `flat_when_inside_bands` (not exit-at-mid), long-only fade, and a squeeze-breakout contrast; no RANGE gate; daily Kraken 720 + Binance.US older-720. Band math for `bb_fade_20x2` matches `mean_reversion_20_2_0` without the regime filter — still a different id and a different print, not a #108 reprint. This is not trend, not cross-section (#117), not Donchian (#118), and not TSMOM sign-of-return (#119). Decision at bar t; fill `next_bar_open` (t+1 open — no look-ahead into the fill bar). Each asset uses its own closes; a missing/short series is skipped, never zero-filled. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, not TSMOM, and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: require BTC and ETH walk-forward total > 0 and holdout excess > 0, plus A/B/C, exactly as #96+#104. SOL walk-forward and holdout are printed in the tables when the series exists and **do not** gate. Equal-weight portfolio metrics were considered and **rejected** before scoring — that would be a different bar and is not used here.

## Treatment (frozen)

On each asset at bar t, bands are SMA(period) ± k × sample stdev (`sample_stdev_ddof_1`) using closes through t (`closes_through_t`). Fade-to-mid shorts above the upper band, longs below the lower band, and goes `flat_when_inside_bands` (not exit-at-mid). Long-only fade is long below the lower band and flat otherwise. Squeeze-breakout CONTRAST (`expand_from_p20_of_prior_120_bandwidth_long_above_mid`) is long only on an upside expansion from the frozen p20 bandwidth; otherwise flat. The shared backtest fills at `next_bar_open` (bar t+1 open), so the decision never looks ahead into the fill bar. A missing series is skipped, never zero-filled. Distinct from existing `mean_reversion_*` catalog ids (`mean_reversion_20_1_5`, `mean_reversion_20_2_0`, `mean_reversion_10_1_5`, `mean_reversion_40_2_0`, and the #108 4h extras). Those are z-score voters (optionally RANGE-regime gated) on charts-spot / 4h bars. This family uses explicit SMA ± k × sample stdev bands, `flat_when_inside_bands` (not exit-at-mid), long-only fade, and a squeeze-breakout contrast; no RANGE gate; daily Kraken 720 + Binance.US older-720. Band math for `bb_fade_20x2` matches `mean_reversion_20_2_0` without the regime filter — still a different id and a different print, not a #108 reprint. Not trend, not cross-sectional (#117), not Donchian (#118), not TSMOM (#119).

## Pre-registered catalog

Frozen catalog (K=8): fade-to-mid (`bb_fade_{20x2,20x2_5,40x2}`), long-only fade (`bb_lo_fade_{20x2,40x2}`), squeeze-breakout CONTRAST (`bb_squeeze_break_{20,40}`; `expand_from_p20_of_prior_120_bandwidth_long_above_mid`), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Bands are built from venue-local closes; a missing series is skipped, never zero-filled. Distinct from existing `mean_reversion_*` catalog ids (`mean_reversion_20_1_5`, `mean_reversion_20_2_0`, `mean_reversion_10_1_5`, `mean_reversion_40_2_0`, and the #108 4h extras). Those are z-score voters (optionally RANGE-regime gated) on charts-spot / 4h bars. This family uses explicit SMA ± k × sample stdev bands, `flat_when_inside_bands` (not exit-at-mid), long-only fade, and a squeeze-breakout contrast; no RANGE gate; daily Kraken 720 + Binance.US older-720. Band math for `bb_fade_20x2` matches `mean_reversion_20_2_0` without the regime filter — still a different id and a different print, not a #108 reprint. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `bb_fade_20x2`, `bb_fade_20x2_5`, `bb_fade_40x2`, `bb_lo_fade_20x2`, `bb_lo_fade_40x2`, `bb_squeeze_break_20`, `bb_squeeze_break_40`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. Signals are candle-only long/short/flat on BTC/USD and ETH/USD (SOL/USD when present); paper_simulate_fills already books Side.BUY / Side.SELL. No perp, no funding, no hedge book, no invented basis. A Settings pin is still added only if a committed dual-print passer exists, and then default false.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2024-09-22T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- universe=BTC/USD,ETH/USD,SOL/USD (SOL optional report-only; skip-not-invent)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- SOLUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- SOLUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- SOLUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- SOL/USD present (720 bars); reported, not a gate.

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720 / SOL 720
- Span: 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00
- Overlaps primary window: no
- Fail-closed reason: —

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping BTC/ETH series fails closed. Empty Binance means zero dual-print passers (success). Missing SOL on Binance is report-only (not a two-asset fallback and not a gate).

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only Bollinger names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | Kraken SOL HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These Bollinger names cleared #96+A+B+C on the Kraken primary window (BTC+ETH gates). They are **not** promotees unless they also appear in the dual-print table. Control omitted. SOL holdout is reported.

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These Bollinger names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken. Control omitted. SOL holdout is reported.

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| `bb_lo_fade_20x2` | bb_fade | FAIL | FAIL | no | -16.21% | +3.00% | -11.99% | -20.44% |
| `bb_squeeze_break_40` | bb_squeeze | FAIL | FAIL | no | +3.72% | +1.44% | +4.69% | +2.74% |
| `bb_lo_fade_40x2` | bb_fade | FAIL | FAIL | no | -16.60% | +6.17% | -14.18% | -19.02% |
| `bb_fade_20x2` | bb_fade | FAIL | FAIL | no | -26.43% | +0.83% | -23.89% | -28.97% |
| `bb_fade_20x2_5` | bb_fade | FAIL | FAIL | no | -18.85% | -1.56% | -17.39% | -20.31% |
| `bb_squeeze_break_20` | bb_squeeze | FAIL | FAIL | no | +1.33% | +6.39% | +1.25% | +1.41% |
| `bb_fade_40x2` | bb_fade | FAIL | FAIL | no | -25.76% | +5.23% | -25.56% | -25.97% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -2.08% | -37.11% | +2.75% | -6.92% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH / 720 SOL; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Multi-asset gate: `btc_eth_signs_as_96_abc_sol_reported_not_required` (SOL reported, not required).
- Paper path: ready on Kraken spot BTC/ETH (SOL optional; PAPER_PATH_READY=true).
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not re-run #104 or #108 EMA / 4h dual-prints. Do not re-run the #116 residual, #117 cross-sectional, #118 Donchian, or #119 TSMOM catalogs on the same windows. Do not invent PIT basis for carry. Do not reprint `mean_reversion_*` ids.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not re-run dead EMA dual-prints (#104 / #108), the #116 residual catalog, the #117 cross-sectional catalog, the #118 Donchian catalog, or the #119 TSMOM catalog on the same windows. Do not invent carry basis. Do not reprint `mean_reversion_*` ids.
