# Cross-sectional momentum dual-print (BTC+ETH+SOL)

Generated: 2026-09-12T19:38:54.717281+00:00
Catalog K scored=13 (frozen core=13; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars BTC=720 / ETH=720 / SOL=720).
Aligned triple-days: 720 (2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00).
`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered BTC+ETH+SOL cross-sectional momentum dual-print bar (frozen before any Kraken or Binance.US score). Treatment: long top-1 by trailing N-day return among {BTC, ETH, SOL}; dollar-neutral `ls` also shorts bottom-1. N in {21, 63, 126}. Optional `vol` ranks by trailing return / trailing sample vol over the same N (ranking transform, not a size overlay). Long-only variants are labeled `lo`. A ranking day requires all three venue-local closes; a missing asset day is skipped, not ranked on a two-asset subset and not zero-filled. Tie-break: higher score, then alphabetical canonical symbol. Signal is valid only on the same opened_at (no stale hold). Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). SOL must exist on a venue to instantiate the XS catalog there (skip-not-invent). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD+SOL/USD (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, and not a carry/basis family. Frozen catalog (K=13): dollar-neutral long-top-1 / short-bottom-1 (`xs_mom_ls_{N}`) and long-only top-1 (`xs_mom_lo_{N}`) at N in {21, 63, 126}, plus the same books with vol-scaled ranking (`_vol_`), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Ranking is built from venue-local BTC, ETH, and SOL daily closes; a day missing any of the three is skipped. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=13 (core ids frozen at 13). Aligned triple-days: 720. Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered BTC+ETH+SOL cross-sectional momentum dual-print bar (frozen before any Kraken or Binance.US score). Treatment: long top-1 by trailing N-day return among {BTC, ETH, SOL}; dollar-neutral `ls` also shorts bottom-1. N in {21, 63, 126}. Optional `vol` ranks by trailing return / trailing sample vol over the same N (ranking transform, not a size overlay). Long-only variants are labeled `lo`. A ranking day requires all three venue-local closes; a missing asset day is skipped, not ranked on a two-asset subset and not zero-filled. Tie-break: higher score, then alphabetical canonical symbol. Signal is valid only on the same opened_at (no stale hold). Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). SOL must exist on a venue to instantiate the XS catalog there (skip-not-invent). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD+SOL/USD (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL required to instantiate the catalog; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: require BTC and ETH walk-forward total > 0 and holdout excess > 0, plus A/B/C, exactly as #96+#104. SOL walk-forward and holdout are printed in the tables and **do not** gate. Equal-weight three-asset portfolio metrics were considered and **rejected** before scoring — that would be a different bar and is not used here.

## Treatment (frozen)

On each aligned BTC+ETH+SOL day t, compute trailing N-day close-to-close return (and, for `vol` names, divide by the sample stdev of the N daily returns). Long the top-1 name; `ls` also shorts the bottom-1 (dollar-neutral book: one long leg and one short leg; the middle name is flat). `lo` is long-only top-1. Decision uses closes through bar t; the shared backtest fills at bar t+1 open. A day missing any of the three closes is skipped. A signal is applied only when the candle `opened_at` matches an assignment (no stale hold).

## Pre-registered catalog

Frozen catalog (K=13): dollar-neutral long-top-1 / short-bottom-1 (`xs_mom_ls_{N}`) and long-only top-1 (`xs_mom_lo_{N}`) at N in {21, 63, 126}, plus the same books with vol-scaled ranking (`_vol_`), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Ranking is built from venue-local BTC, ETH, and SOL daily closes; a day missing any of the three is skipped. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `xs_mom_ls_21`, `xs_mom_ls_63`, `xs_mom_ls_126`, `xs_mom_lo_21`, `xs_mom_lo_63`, `xs_mom_lo_126`, `xs_mom_ls_vol_21`, `xs_mom_ls_vol_63`, `xs_mom_ls_vol_126`, `xs_mom_lo_vol_21`, `xs_mom_lo_vol_63`, `xs_mom_lo_vol_126`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. Signals are candle-only long/short/flat on BTC/USD, ETH/USD, and SOL/USD; paper_simulate_fills already books Side.BUY / Side.SELL. No perp, no funding, no hedge book, no invented basis. A Settings pin is still added only if a committed dual-print passer exists, and then default false.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2024-09-22T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- universe=BTC/USD,ETH/USD,SOL/USD (skip-not-invent: need all three)
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
- BTC+ETH+SOL aligned triple-days: 720 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (skipped days omitted).
- Binance.US aligned triple-days: 720 (same skip-not-invent rule).

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720 / SOL 720
- Span: 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00
- Overlaps primary window: no
- Fail-closed reason: —

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping BTC/ETH series fails closed. Empty Binance means zero dual-print passers (success). Missing SOL on Binance skips XS names on that venue (not a two-asset fallback).

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only XS names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | Kraken SOL HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These XS names cleared #96+A+B+C on the Kraken primary window (BTC+ETH gates). They are **not** promotees unless they also appear in the dual-print table. Control omitted. SOL holdout is reported.

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These XS names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken. Control omitted. SOL holdout is reported.

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO | Kraken SOL HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: |
| `xs_mom_lo_126` | xs_momentum | FAIL | FAIL | no | -12.12% | -7.06% | +8.28% |
| `xs_mom_lo_63` | xs_momentum | FAIL | FAIL | no | -1.54% | +1.65% | -11.55% |
| `xs_mom_lo_21` | xs_momentum | FAIL | FAIL | no | -6.61% | -4.71% | -16.14% |
| `xs_mom_ls_126` | xs_momentum | FAIL | FAIL | no | -29.70% | -25.75% | +25.92% |
| `xs_mom_lo_vol_21` | xs_momentum | FAIL | FAIL | no | -8.85% | -9.00% | -8.79% |
| `xs_mom_ls_21` | xs_momentum | FAIL | FAIL | no | -18.79% | -10.32% | -11.14% |
| `xs_mom_lo_vol_63` | xs_momentum | FAIL | FAIL | no | +7.13% | +9.55% | -20.37% |
| `xs_mom_lo_vol_126` | xs_momentum | FAIL | FAIL | no | -12.15% | +1.12% | +11.02% |
| `xs_mom_ls_63` | xs_momentum | FAIL | FAIL | no | -11.89% | -6.11% | -1.12% |
| `xs_mom_ls_vol_21` | xs_momentum | FAIL | FAIL | no | -14.08% | -23.38% | -10.69% |
| `xs_mom_ls_vol_126` | xs_momentum | FAIL | FAIL | no | -26.32% | -14.23% | +25.98% |
| `xs_mom_ls_vol_63` | xs_momentum | FAIL | FAIL | no | -0.10% | -1.74% | -8.71% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -2.08% | -37.11% | +6.11% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH / 720 SOL; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Aligned BTC+ETH+SOL triple-days (Kraken): 720. Missing-asset days were skipped.
- Multi-asset gate: `btc_eth_signs_as_96_abc_sol_reported_not_required` (SOL reported, not required).
- Paper path: ready on Kraken spot BTC/ETH/SOL (PAPER_PATH_READY=true).
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not re-run #104 or #108 EMA dual-prints. Do not re-run the #116 residual catalog on the same windows. Do not invent PIT basis for carry.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not re-run dead EMA dual-prints (#104 / #108) or the #116 residual catalog on the same windows. Do not invent carry basis.
