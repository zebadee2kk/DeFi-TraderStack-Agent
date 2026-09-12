# BTC−ETH relative-value residual dual-print

Generated: 2026-09-12T19:20:11.951141+00:00
Catalog K scored=7 (frozen core=7; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars=720).
Residual pair-days: 719 (2024-09-23T00:00:00+00:00 → 2026-09-11T00:00:00+00:00).
`multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered BTC−ETH relative-value residual dual-print bar (frozen before any Kraken or Binance.US score). Treatment: fade or follow daily close-to-close excess r_BTC − r_ETH at |z| ≥ 1.0 / 1.5 / 2.0 with lookback 20. ETH is bound to the negated residual (skip-not-invent: a day missing either close is omitted, never zero-filled). Combined on each print is #96 balanced-holdout and A magnitude and B multi-window and C 2× fees. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint and not a carry/basis family. Frozen catalog (K=7): rv_fade / rv_follow at |z|>=1.0 / 1.5 / 2.0 on the BTC−ETH residual (lookback 20), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Residual is built from the venue-local BTC and ETH daily closes; a missing pair day is skipped. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=7 (core ids frozen at 7). Residual pair-days: 719. Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered BTC−ETH relative-value residual dual-print bar (frozen before any Kraken or Binance.US score). Treatment: fade or follow daily close-to-close excess r_BTC − r_ETH at |z| ≥ 1.0 / 1.5 / 2.0 with lookback 20. ETH is bound to the negated residual (skip-not-invent: a day missing either close is omitted, never zero-filled). Combined on each print is #96 balanced-holdout and A magnitude and B multi-window and C 2× fees. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C; rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily bars ending before the primary Kraken first bar; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Treatment (frozen)

Daily BTC minus ETH close-to-close excess return, z-scored over 20 aligned pair-days. Fade: sell the outperformer / buy the underperformer at |z| ≥ threshold. Follow: the opposite. Decision uses residual through bar t; the shared backtest fills at bar t+1 open. A missing pair day is skipped, not zero-filled.

## Pre-registered catalog

Frozen catalog (K=7): rv_fade / rv_follow at |z|>=1.0 / 1.5 / 2.0 on the BTC−ETH residual (lookback 20), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Residual is built from the venue-local BTC and ETH daily closes; a missing pair day is skipped. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `rv_fade_1_0`, `rv_fade_1_5`, `rv_fade_2_0`, `rv_follow_1_0`, `rv_follow_1_5`, `rv_follow_2_0`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. Signals are candle-only long/short on BTC/USD and ETH/USD; paper_simulate_fills already books Side.BUY / Side.SELL. No perp, no funding, no hedge book, no invented basis. A Settings pin is still added only if a committed dual-print passer exists, and then default false.

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
- BTCUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- BTC−ETH residual: 719 aligned pair-days 2024-09-23T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (skipped days omitted).
- Binance.US residual: 719 aligned pair-days (same skip-not-invent rule).

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

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only RV names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These RV names cleared #96+A+B+C on the Kraken primary window. They are **not** promotees unless they also appear in the dual-print table. Control omitted.

| rank | id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These RV names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken. Control omitted.

| id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: |
| `rv_follow_2_0` | relative_value | FAIL | FAIL | no | -7.11% | +6.12% |
| `rv_follow_1_0` | relative_value | FAIL | FAIL | no | -13.79% | -3.05% |
| `rv_follow_1_5` | relative_value | FAIL | FAIL | no | -5.49% | +2.81% |
| `rv_fade_2_0` | relative_value | FAIL | FAIL | no | -6.50% | -1.02% |
| `rv_fade_1_5` | relative_value | FAIL | FAIL | no | -11.68% | -3.31% |
| `rv_fade_1_0` | relative_value | FAIL | FAIL | no | -15.64% | -5.29% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -2.08% | -37.11% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Residual points (Kraken-aligned pair days after the first return): 719. Missing pair days were skipped.
- Paper path: ready on Kraken spot BTC/ETH (PAPER_PATH_READY=true).
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not re-run #104 or #108 EMA dual-prints. Do not invent PIT basis for carry.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not re-run dead EMA dual-prints (#104 / #108). Do not invent carry basis.
