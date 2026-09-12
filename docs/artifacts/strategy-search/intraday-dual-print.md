# Intraday (4h) dual-print strategy search

Generated: 2026-09-12T17:04:39.546346+00:00
Interval: **4h** (allowed: 4h primary, 1h alternate). Catalog K scored=36 (frozen core=32; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2026-05-15T16:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-12T12:00:00+00:00; bars=720).
`multi_venue_bar_preregistered=true`; `can_average_venues=false`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered 4h/1h dual-print bar (frozen before any Kraken or Binance.US score). Combined on each print is #96 balanced-holdout and A magnitude and B multi-window and C 2× fees. A dual-print passer must combined-PASS the Kraken primary 720-bar window at the frozen interval AND the #102-style Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed bars of the same interval ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Funding/OI variants score only when an aligned series is fetched; they are skipped, not invented. Pre-registered 4h/1h dual-print catalog (frozen before any Kraken or Binance.US pull). Not a daily-EMA hunt. Core K=32: MA / momentum / mean-reversion plus candle-only vol-regime wrappers and a small 4h-appropriate lookback grid. `ema_9_21` and `ema_12_26` are informational controls only. Funding-z / OI-z instantiate only when an aligned historical series is fetched (OKX public history when reachable); liquidation-z and cross-venue stay skipped (no aligned Spot series; #105). Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. Interval=4h. This run scored K=36 (core ids frozen at 32; optional feature ids present: ['funding_z_fade', 'funding_z_follow', 'oi_z_fade', 'oi_z_follow']). Kraken combined-passers: 0. Binance combined-passers: 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered 4h/1h dual-print bar (frozen before any Kraken or Binance.US score). Combined on each print is #96 balanced-holdout and A magnitude and B multi-window and C 2× fees. A dual-print passer must combined-PASS the Kraken primary 720-bar window at the frozen interval AND the #102-style Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed bars of the same interval ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Funding/OI variants score only when an aligned series is fetched; they are skipped, not invented.

Same #96+A+B+C bar as the daily harder gates, applied to the frozen 4h/1h interval (bar counts unchanged). A — magnitude: BTC and ETH holdout excess > 0 and min/max ratio >= 0.25. B — three contiguous 240-bar slices of this interval; each uses train=180 / test=60 / step=60 with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3. C — 2× fees (20+10 bps) must still clear #96 balanced signs. Combined requires #96 and A and B and C on **each** print.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 4h | public Spot, 720-bar cap; #96+A+B+C; rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 4h | same #102 definition: 720 committed 4h bars ending before the primary Kraken first bar; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking | informational | no |

## Pre-registered catalog

Pre-registered 4h/1h dual-print catalog (frozen before any Kraken or Binance.US pull). Not a daily-EMA hunt. Core K=32: MA / momentum / mean-reversion plus candle-only vol-regime wrappers and a small 4h-appropriate lookback grid. `ema_9_21` and `ema_12_26` are informational controls only. Funding-z / OI-z instantiate only when an aligned historical series is fetched (OKX public history when reachable); liquidation-z and cross-venue stay skipped (no aligned Spot series; #105). Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `ma_cross_5_20`, `ma_cross_10_30`, `ma_cross_20_50`, `ma_cross_10_30_wide`, `ma_always_on_10_30`, `momentum_6`, `momentum_12`, `momentum_24`, `momentum_12_strict`, `mean_reversion_20_1_5`, `mean_reversion_20_2_0`, `mean_reversion_10_1_5`, `mean_reversion_40_2_0`, `ma_cross_10_30_vol`, `ma_always_on_10_30_vol`, `momentum_6_vol`, `momentum_12_vol`, `mean_reversion_20_1_5_vol`, `mean_reversion_20_2_0_vol`, `ma_cross_8_21`, `ma_cross_12_36`, `ma_cross_15_45`, `momentum_18`, `momentum_36`, `momentum_48`, `mean_reversion_30_1_5`, `mean_reversion_24_2_0`, `ma_cross_8_21_vol`, `momentum_18_vol`, `mean_reversion_30_1_5_vol`, `ema_9_21`, `ema_12_26`.

Optional feature ids (only when aligned series present): `funding_z_fade`, `funding_z_follow`, `oi_z_fade`, `oi_z_follow`. Present this run: ['funding_z_fade', 'funding_z_follow', 'oi_z_fade', 'oi_z_follow'].

## Skipped optional families

- liquidation_z: skipped — no aligned historical Spot series (#105). Not invented.
- cross_venue: skipped — no aligned two-venue historical series. Not invented.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval. `since` pages forward only. 4h ≈ 120 calendar days; 1h ≈ 30 days. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. This is not the daily EMA promotion window.

## Data

- BTC/USD@4h: 720 committed Kraken bars 2026-05-15T16:00:00+00:00 → 2026-09-12T12:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@4h: 720 committed Kraken bars 2026-05-15T16:00:00+00:00 → 2026-09-12T12:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2026-05-15T16:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@4h: 720 committed binance_us_spot 4h bars 2026-01-15T16:00:00+00:00 → 2026-05-15T12:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@4h: 720 committed binance_us_spot 4h bars 2026-01-15T16:00:00+00:00 → 2026-05-15T12:00:00+00:00 (non-Kraken; report-only)
- binance_funding:BTC/USD: skipped — HTTP 451 (geo-blocked / unavailable in this environment)
- binance_oi:BTC/USD: skipped — HTTP 451 (geo-blocked / unavailable in this environment)
- binance_liquidation:BTC/USD: skipped — HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed.
- binance_funding:ETH/USD: skipped — HTTP 451 (geo-blocked / unavailable in this environment)
- binance_oi:ETH/USD: skipped — HTTP 451 (geo-blocked / unavailable in this environment)
- binance_liquidation:ETH/USD: skipped — HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed.
- okx_funding:BTC/USD: ok — OKX swap funding-rate-history (public; ~90d of 8h prints)
- okx_oi:BTC/USD: ok — OKX rubik 1h open-interest-history (public, paginated)
- okx_liquidation:BTC/USD: skipped — OKX liquidation-orders span 22.9h across 100 fills — not a historical aggregate. Skip rather than invent a z.
- okx_funding:ETH/USD: ok — OKX swap funding-rate-history (public; ~90d of 8h prints)
- okx_oi:ETH/USD: ok — OKX rubik 1h open-interest-history (public, paginated)
- okx_liquidation:ETH/USD: skipped — OKX liquidation-orders span 8.0h across 100 fills — not a historical aggregate. Skip rather than invent a z.

## Binance.US second print (required 4h gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720
- Span: 2026-01-15T16:00:00+00:00 → 2026-05-15T12:00:00+00:00
- Overlaps primary window: no
- Fail-closed reason: —

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping series fails closed. Empty Binance means zero dual-print passers (success).

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only names that already clear combined on **both** prints appear here. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | family | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | selected | can flip flag |
| ---: | --- | --- | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | — | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These names cleared #96+A+B+C on the Kraken primary window. They are **not** promotees unless they also appear in the dual-print table.

| rank | id | family | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken.

| id | family | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| --- | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: |
| `mean_reversion_30_1_5` | mean_reversion | FAIL | FAIL | no | -16.63% | +3.09% |
| `mean_reversion_30_1_5_vol` | mean_reversion | FAIL | FAIL | no | -16.63% | +3.09% |
| `mean_reversion_40_2_0` | mean_reversion | FAIL | FAIL | no | -16.44% | +1.04% |
| `mean_reversion_20_1_5` | mean_reversion | FAIL | FAIL | no | -17.13% | +1.42% |
| `mean_reversion_20_1_5_vol` | mean_reversion | FAIL | FAIL | no | -17.13% | +1.42% |
| `mean_reversion_20_2_0` | mean_reversion | FAIL | FAIL | no | -16.47% | +1.16% |
| `mean_reversion_20_2_0_vol` | mean_reversion | FAIL | FAIL | no | -16.47% | +1.16% |
| `mean_reversion_24_2_0` | mean_reversion | FAIL | FAIL | no | -16.39% | +2.22% |
| `mean_reversion_10_1_5` | mean_reversion | FAIL | FAIL | no | -17.01% | +1.19% |
| `momentum_6_vol` | momentum | FAIL | FAIL | no | -10.55% | -7.20% |
| `ma_cross_20_50` | ma_cross | FAIL | FAIL | no | -10.70% | -6.91% |
| `oi_z_follow` | open_interest_z | FAIL | FAIL | no | -33.48% | -0.31% |
| `ma_cross_8_21` | ma_cross | FAIL | FAIL | no | -20.05% | -4.72% |
| `ma_cross_8_21_vol` | ma_cross | FAIL | FAIL | no | -20.05% | -4.72% |
| `funding_z_follow` | funding_z | FAIL | FAIL | no | -17.38% | -0.31% |
| `momentum_6` | momentum | FAIL | FAIL | no | -11.09% | -9.92% |
| `ma_cross_15_45` | ma_cross | FAIL | FAIL | no | -11.15% | -4.76% |
| `funding_z_fade` | funding_z | FAIL | FAIL | no | -20.68% | -0.31% |
| `momentum_12_strict` | momentum | FAIL | FAIL | no | -9.11% | -1.12% |
| `ma_cross_10_30_wide` | ma_cross | FAIL | FAIL | no | -7.80% | -6.75% |
| `momentum_48` | momentum | FAIL | FAIL | no | -10.88% | -13.61% |
| `ma_cross_5_20` | ma_cross | FAIL | FAIL | no | -18.51% | -5.27% |
| `oi_z_fade` | open_interest_z | FAIL | FAIL | no | -15.60% | -0.31% |
| `momentum_12_vol` | momentum | FAIL | FAIL | no | -17.22% | -12.39% |
| `ema_12_26` | ema_cross | FAIL | FAIL | no | -21.54% | -12.36% |
| `ma_cross_12_36` | ma_cross | FAIL | FAIL | no | -11.66% | -7.58% |
| `ma_cross_10_30` | ma_cross | FAIL | FAIL | no | -14.69% | -10.25% |
| `ma_cross_10_30_vol` | ma_cross | FAIL | FAIL | no | -14.69% | -10.25% |
| `ma_always_on_10_30_vol` | ma_cross | FAIL | FAIL | no | -14.69% | -10.25% |
| `momentum_36` | momentum | FAIL | FAIL | no | -14.16% | -10.34% |
| `ma_always_on_10_30` | ma_cross | FAIL | FAIL | no | -10.04% | -13.75% |
| `momentum_12` | momentum | FAIL | FAIL | no | -18.91% | -16.41% |
| `momentum_18_vol` | momentum | FAIL | FAIL | no | -9.50% | -9.67% |
| `momentum_24` | momentum | FAIL | FAIL | no | -13.87% | -15.55% |
| `momentum_18` | momentum | FAIL | FAIL | no | -10.46% | -14.34% |
| `ema_9_21` | ema_cross | FAIL | FAIL | no | -20.48% | -8.71% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken 4h combined-passers (informational): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar` 4h: scored (binance_us_spot; 720 BTC / 720 ETH; 2026-01-15T16:00:00+00:00 → 2026-05-15T12:00:00+00:00).
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not claim a 4h/1h print as the daily EMA edge.
