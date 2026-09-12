# BTC→ETH lead-lag dual-print

Generated: 2026-09-12T21:16:34.422292+00:00
Catalog K scored=13 (frozen core=13; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars BTC=720 / ETH=720).
Aligned pair-days: 720 (2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00).
`multi_asset_gate_rule=btc_eth_both_legs_96_abc_other_leg_flat`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered BTC→ETH lead-lag dual-print bar (frozen before any Kraken or Binance.US score). Treatment: the traded asset follows or fades the lead asset's trailing L-day close-to-close return (decision `lead_closes_through_t`: lead_close[t] / lead_close[t-L] − 1 on aligned pair-days). L ≥ 1, so when trading ETH the gate does not use same-bar ETH. not same-bar residual z-score on r_BTC − r_ETH (#116); the gate uses only the lead asset's L-day return (L≥1). Follow long-only is long the traded asset when the lead return is > 0 and flat otherwise. Follow long/short is the sign of the lead return (flat on exact zero). Fade long-only is long the traded asset when the lead return is < 0 and flat otherwise (mean-revert the lead). Mirror names trade BTC following lagged ETH (small frozen set). Other-leg book `flat_on_aligned_pair_days`: ETH-traded names keep BTC flat; BTC-traded names keep ETH flat. Combined #96+A+B+C still requires both legs (standing #96). The other leg is not ma_cross_10_30 and not own-asset TSMOM. Decision at bar t; fill `next_bar_open` on the traded asset (t+1 open — no look-ahead into the fill bar). Unpaired BTC/ETH days are skipped, never zero-filled. Multi-asset combined bar: `btc_eth_both_legs_96_abc_other_leg_flat` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH (both legs). Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, not TSMOM, not Bollinger fade, not calendar seasonality, and not a carry/basis family. Frozen catalog (K=13): ETH follows lagged BTC long-only (`leadlag_eth_follow_lo_{1,2,3,5}`), ETH follows lagged BTC long/short (`leadlag_eth_follow_ls_{1,2,3}`), ETH fades lagged BTC long-only (`leadlag_eth_fade_lo_{1,2,3}`), BTC follows lagged ETH long-only mirror (`leadlag_btc_follow_lo_{1,2}`), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list or retune L after seeing PnL. Lead return uses `lead_closes_through_t` on aligned pair-days; unpaired days are skipped, never zero-filled. Other-leg book is `flat_on_aligned_pair_days`. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=13 (core ids frozen at 13). Aligned pair-days: 720. Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. Informational #96 FAIL (ETH-carried mean HO): `leadlag_eth_follow_lo_5`. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered BTC→ETH lead-lag dual-print bar (frozen before any Kraken or Binance.US score). Treatment: the traded asset follows or fades the lead asset's trailing L-day close-to-close return (decision `lead_closes_through_t`: lead_close[t] / lead_close[t-L] − 1 on aligned pair-days). L ≥ 1, so when trading ETH the gate does not use same-bar ETH. not same-bar residual z-score on r_BTC − r_ETH (#116); the gate uses only the lead asset's L-day return (L≥1). Follow long-only is long the traded asset when the lead return is > 0 and flat otherwise. Follow long/short is the sign of the lead return (flat on exact zero). Fade long-only is long the traded asset when the lead return is < 0 and flat otherwise (mean-revert the lead). Mirror names trade BTC following lagged ETH (small frozen set). Other-leg book `flat_on_aligned_pair_days`: ETH-traded names keep BTC flat; BTC-traded names keep ETH flat. Combined #96+A+B+C still requires both legs (standing #96). The other leg is not ma_cross_10_30 and not own-asset TSMOM. Decision at bar t; fill `next_bar_open` on the traded asset (t+1 open — no look-ahead into the fill bar). Unpaired BTC/ETH days are skipped, never zero-filled. Multi-asset combined bar: `btc_eth_both_legs_96_abc_other_leg_flat` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH (both legs). Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, not TSMOM, not Bollinger fade, not calendar seasonality, and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (other leg `flat_on_aligned_pair_days`); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Multi-asset gate (frozen)

`btc_eth_both_legs_96_abc_other_leg_flat`: every catalog id produces a BTC book and an ETH book. ETH-traded names run the lead-lag rule on ETH and keep BTC **flat**. BTC-traded mirror names run the lead-lag rule on BTC and keep ETH **flat**. Combined #96+A+B+C still requires **both** legs (standing #96 — ETH-only strength cannot promote). The other leg is not `ma_cross_10_30` and not own-asset TSMOM. Equal-weight portfolio metrics were considered and **rejected** before scoring.

## Treatment (frozen)

At aligned pair-day t the lead return is the lead asset's trailing L-day close-to-close (`lead_closes_through_t`: lead_close[t] / lead_close[t−L] − 1). L ≥ 1. The gate uses the lead close at t and **never** the traded asset's same-bar close — when trading ETH, same-bar ETH does not enter the signal. This is not #116 residual z-score on `r_BTC − r_ETH`. Follow long-only: long the traded asset when the lead return is > 0, else flat. Follow long/short: sign of the lead return. Fade long-only: long the traded asset when the lead return is < 0, else flat. The shared backtest fills at `next_bar_open` on the traded asset (bar t+1 open), so the decision never looks ahead into the fill bar. Unpaired BTC/ETH days are skipped, never zero-filled.

## Pre-registered catalog

Frozen catalog (K=13): ETH follows lagged BTC long-only (`leadlag_eth_follow_lo_{1,2,3,5}`), ETH follows lagged BTC long/short (`leadlag_eth_follow_ls_{1,2,3}`), ETH fades lagged BTC long-only (`leadlag_eth_fade_lo_{1,2,3}`), BTC follows lagged ETH long-only mirror (`leadlag_btc_follow_lo_{1,2}`), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list or retune L after seeing PnL. Lead return uses `lead_closes_through_t` on aligned pair-days; unpaired days are skipped, never zero-filled. Other-leg book is `flat_on_aligned_pair_days`. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `leadlag_eth_follow_lo_1`, `leadlag_eth_follow_lo_2`, `leadlag_eth_follow_lo_3`, `leadlag_eth_follow_lo_5`, `leadlag_eth_follow_ls_1`, `leadlag_eth_follow_ls_2`, `leadlag_eth_follow_ls_3`, `leadlag_eth_fade_lo_1`, `leadlag_eth_fade_lo_2`, `leadlag_eth_fade_lo_3`, `leadlag_btc_follow_lo_1`, `leadlag_btc_follow_lo_2`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. Signals are candle-only long/short/flat on BTC/USD and ETH/USD; paper_simulate_fills already books Side.BUY / Side.SELL. No perp, no funding, no hedge book, no invented basis. A Settings pin is still added only if a committed dual-print passer exists, and then default false.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2024-09-22T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- universe=BTC/USD,ETH/USD (BTC+ETH pair; unpaired days skipped)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- BTC+ETH aligned pair-days: 720 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (unpaired days omitted).
- Binance.US aligned pair-days: 720 (same skip-not-invent rule).

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720
- Span: 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00
- Overlaps primary window: no
- Fail-closed reason: —

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping BTC/ETH series fails closed. Empty Binance means zero dual-print passers (success).

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only lead-lag names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These lead-lag names cleared #96+A+B+C on the Kraken primary window (both BTC and ETH legs). They are **not** promotees unless they also appear in the dual-print table. Control omitted.

| rank | id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These lead-lag names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken. Control omitted.

| id | mean HO | BTC HO | ETH HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | — | — | — | — | no |

## #96 FAIL informational names (ETH-carried)

These names have a **positive** Kraken mean holdout excess while BTC holdout excess is ≤ 0. That is the same honesty as `xs_mom_lo_vol_63` in #117 and `tsmom_lo_63` / `tsmom_ls_63` in #119: the mean is ETH-carried. **#96 FAIL**, not a combined-passer. ETH-traded names keep BTC flat, so a losing BTC holdout vs buy-and-hold is expected and is not an edge.

| id | Kraken mean HO | BTC HO | ETH HO |
| --- | ---: | ---: | ---: |
| `leadlag_eth_follow_lo_5` | +6.67% | -1.80% | +15.14% |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| `leadlag_eth_follow_ls_3` | lead_lag | FAIL | FAIL | no | -11.50% | +21.06% | -1.80% | -21.20% |
| `leadlag_eth_follow_lo_3` | lead_lag | FAIL | FAIL | no | -5.53% | +9.96% | -1.80% | -9.25% |
| `leadlag_eth_follow_lo_1` | lead_lag | FAIL | FAIL | no | -0.08% | -7.80% | -1.80% | +1.63% |
| `leadlag_eth_follow_ls_1` | lead_lag | FAIL | FAIL | no | -1.50% | -16.96% | -1.80% | -1.19% |
| `leadlag_eth_follow_lo_5` | lead_lag | FAIL | FAIL | no | +6.67% | +8.28% | -1.80% | +15.14% |
| `leadlag_eth_follow_lo_2` | lead_lag | FAIL | FAIL | no | -6.54% | +11.80% | -1.80% | -11.29% |
| `leadlag_eth_follow_ls_2` | lead_lag | FAIL | FAIL | no | -13.49% | +18.33% | -1.80% | -25.18% |
| `leadlag_btc_follow_lo_2` | lead_lag | FAIL | FAIL | no | -8.36% | +0.82% | -8.05% | -8.68% |
| `leadlag_btc_follow_lo_1` | lead_lag | FAIL | FAIL | no | -5.65% | +2.68% | -2.63% | -8.68% |
| `leadlag_eth_fade_lo_2` | lead_lag | FAIL | FAIL | no | -7.48% | -12.46% | -1.80% | -13.17% |
| `leadlag_eth_fade_lo_3` | lead_lag | FAIL | FAIL | no | -7.32% | -10.52% | -1.80% | -12.85% |
| `leadlag_eth_fade_lo_1` | lead_lag | FAIL | FAIL | no | -15.53% | +0.68% | -1.80% | -29.27% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -2.08% | -37.11% | +2.75% | -6.92% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Multi-asset gate: `btc_eth_both_legs_96_abc_other_leg_flat` (other leg `flat_on_aligned_pair_days`; both BTC and ETH must clear #96+A+B+C).
- Aligned pair-days (Kraken): 720. Unpaired days were skipped, not zero-filled.
- Paper path: ready on Kraken spot BTC/ETH (PAPER_PATH_READY=true).
- #96 FAIL (ETH-carried informational mean HO; BTC holdout ≤ 0): `leadlag_eth_follow_lo_5`. A positive mean with a losing BTC holdout is not an edge. ETH-traded names keep BTC flat, so a losing BTC holdout vs buy-and-hold is the expected #96 fail-closed posture.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not re-run #104 or #108 EMA dual-prints. Do not re-run the #116 residual, #117 cross-sectional, #118 Donchian, #119 TSMOM, #120 Bollinger, or #121 calendar catalogs on the same windows. Do not invent PIT basis for carry.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not re-run dead EMA dual-prints (#104 / #108), the #116 residual catalog, the #117 cross-sectional catalog, the #118 Donchian catalog, the #119 TSMOM catalog, the #120 Bollinger catalog, or the #121 calendar catalog on the same windows. Do not invent carry basis.
