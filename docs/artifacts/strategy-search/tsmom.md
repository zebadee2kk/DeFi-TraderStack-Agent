# Time-series momentum dual-print (BTC+ETH; SOL optional)

Generated: 2026-09-12T20:15:35.357735+00:00
Catalog K scored=9 (frozen core=9; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars BTC=720 / ETH=720 / SOL=720).
`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered time-series momentum dual-print bar (frozen before any Kraken or Binance.US score). Treatment: each asset uses its own trailing N-day close-to-close return (decision `closes_through_t`: close[t] / close[t-N] − 1). Long-only is long when that return is > 0 and flat otherwise. Long/short is long when the return is > 0 and short when it is < 0 (flat on an exact zero). N in {21, 63, 126, 252}. Vol-scaled sign variants omitted (sign(return/vol) equals sign(return) whenever vol > 0; a return/vol size overlay is GARCH-class sizing and is out of scope). This is not cross-sectional top-1 (#117) and not Donchian / channel breakout (#118). Decision at bar t; fill `next_bar_open` (t+1 open — no look-ahead into the fill bar). Each asset uses its own closes; a missing/short series is skipped, never zero-filled. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, and not a carry/basis family. Frozen catalog (K=9): long-only time-series momentum (`tsmom_lo_{21,63,126,252}`), long/short symmetric (`tsmom_ls_{21,63,126,252}`), plus informational control ma_cross_10_30 (cannot promote). Vol-scaled sign variants omitted (sign(return/vol) equals sign(return) whenever vol > 0; a return/vol size overlay is GARCH-class sizing and is out of scope). Do not grow this list after seeing PnL. Trailing return is built from venue-local closes; a missing series is skipped, never zero-filled. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=9 (core ids frozen at 9). Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. Informational #96 FAIL (ETH-carried mean HO): `tsmom_lo_63`, `tsmom_ls_63`. Informational BTC walk-forward fail (positive mean HO and BTC HO): `tsmom_lo_21`, `tsmom_ls_21`. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered time-series momentum dual-print bar (frozen before any Kraken or Binance.US score). Treatment: each asset uses its own trailing N-day close-to-close return (decision `closes_through_t`: close[t] / close[t-N] − 1). Long-only is long when that return is > 0 and flat otherwise. Long/short is long when the return is > 0 and short when it is < 0 (flat on an exact zero). N in {21, 63, 126, 252}. Vol-scaled sign variants omitted (sign(return/vol) equals sign(return) whenever vol > 0; a return/vol size overlay is GARCH-class sizing and is out of scope). This is not cross-sectional top-1 (#117) and not Donchian / channel breakout (#118). Decision at bar t; fill `next_bar_open` (t+1 open — no look-ahead into the fill bar). Each asset uses its own closes; a missing/short series is skipped, never zero-filled. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: require BTC and ETH walk-forward total > 0 and holdout excess > 0, plus A/B/C, exactly as #96+#104. SOL walk-forward and holdout are printed in the tables when the series exists and **do not** gate. Equal-weight portfolio metrics were considered and **rejected** before scoring — that would be a different bar and is not used here.

## Treatment (frozen)

On each asset at bar t, the signal is that asset's trailing N-day close-to-close return (`closes_through_t`: close[t] / close[t−N] − 1). Long-only is long when the return is > 0 and flat otherwise. Long/short is long when the return is > 0 and short when it is < 0. The shared backtest fills at `next_bar_open` (bar t+1 open), so the decision never looks ahead into the fill bar. A missing series is skipped, never zero-filled. Vol-scaled sign variants omitted (sign(return/vol) equals sign(return) whenever vol > 0; a return/vol size overlay is GARCH-class sizing and is out of scope). Not cross-sectional top-1 (#117) and not Donchian (#118).

## Pre-registered catalog

Frozen catalog (K=9): long-only time-series momentum (`tsmom_lo_{21,63,126,252}`), long/short symmetric (`tsmom_ls_{21,63,126,252}`), plus informational control ma_cross_10_30 (cannot promote). Vol-scaled sign variants omitted (sign(return/vol) equals sign(return) whenever vol > 0; a return/vol size overlay is GARCH-class sizing and is out of scope). Do not grow this list after seeing PnL. Trailing return is built from venue-local closes; a missing series is skipped, never zero-filled. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `tsmom_lo_21`, `tsmom_lo_63`, `tsmom_lo_126`, `tsmom_lo_252`, `tsmom_ls_21`, `tsmom_ls_63`, `tsmom_ls_126`, `tsmom_ls_252`, `ma_cross_10_30`.

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

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only TSMOM names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | Kraken SOL HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These TSMOM names cleared #96+A+B+C on the Kraken primary window (BTC+ETH gates). They are **not** promotees unless they also appear in the dual-print table. Control omitted. SOL holdout is reported.

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These TSMOM names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken. Control omitted. SOL holdout is reported.

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## #96 FAIL informational names (ETH-carried)

These names have a **positive** Kraken mean holdout excess while BTC holdout excess is ≤ 0. That is the same honesty as `xs_mom_lo_vol_63` in #117: the mean is ETH-carried. **#96 FAIL**, not a combined-passer.

| id | Kraken mean HO | BTC HO | ETH HO |
| --- | ---: | ---: | ---: |
| `tsmom_lo_63` | +2.61% | -7.12% | +12.35% |
| `tsmom_ls_63` | +6.29% | -13.74% | +26.32% |

## Informational BTC walk-forward fails

These names have a **positive** Kraken mean holdout and **positive** BTC holdout, but BTC walk-forward total is ≤ 0. Same honesty as #118 Donchian (`donchian_ls_20` / `donchian_lo_20` / `donchian_lo_atr_55`). Still not an edge.

| id | Kraken mean HO | BTC HO | BTC WF |
| --- | ---: | ---: | ---: |
| `tsmom_lo_21` | +7.32% | +9.15% | -1.71% |
| `tsmom_ls_21` | +6.64% | +16.79% | -3.75% |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| `tsmom_ls_21` | tsmom | FAIL | FAIL | no | +6.64% | -31.17% | +16.79% | -3.52% |
| `tsmom_lo_21` | tsmom | FAIL | FAIL | no | +7.32% | -14.64% | +9.15% | +5.48% |
| `tsmom_lo_63` | tsmom | FAIL | FAIL | no | +2.61% | -9.99% | -7.12% | +12.35% |
| `tsmom_ls_63` | tsmom | FAIL | FAIL | no | +6.29% | -25.10% | -13.74% | +26.32% |
| `tsmom_lo_126` | tsmom | FAIL | FAIL | no | -5.92% | +7.77% | -2.87% | -8.97% |
| `tsmom_ls_126` | tsmom | FAIL | FAIL | no | -15.24% | +11.09% | -13.18% | -17.31% |
| `tsmom_lo_252` | tsmom | FAIL | FAIL | no | -5.24% | -3.74% | -1.80% | -8.68% |
| `tsmom_ls_252` | tsmom | FAIL | FAIL | no | -10.14% | -9.43% | -3.22% | -17.06% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -2.08% | -37.11% | +2.75% | -6.92% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH / 720 SOL; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Multi-asset gate: `btc_eth_signs_as_96_abc_sol_reported_not_required` (SOL reported, not required).
- Paper path: ready on Kraken spot BTC/ETH (SOL optional; PAPER_PATH_READY=true).
- #96 FAIL (ETH-carried informational mean HO; BTC holdout ≤ 0): `tsmom_lo_63`, `tsmom_ls_63`. A positive mean with a losing BTC holdout is not an edge.
- Informational positive mean HO and BTC HO with BTC walk-forward ≤ 0: `tsmom_lo_21`, `tsmom_ls_21`. Same honesty as #118 Donchian — still not an edge.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not re-run #104 or #108 EMA dual-prints. Do not re-run the #116 residual, #117 cross-sectional, or #118 Donchian catalogs on the same windows. Do not invent PIT basis for carry.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not re-run dead EMA dual-prints (#104 / #108), the #116 residual catalog, the #117 cross-sectional catalog, or the #118 Donchian catalog on the same windows. Do not invent carry basis.
