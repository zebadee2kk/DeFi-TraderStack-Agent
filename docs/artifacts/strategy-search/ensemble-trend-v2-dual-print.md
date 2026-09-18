# Ensemble-trend v2 consensus dual-print (Kraken x Coinbase; BTC+ETH gate; SOL reported)

Generated: 2026-09-18T11:18:08.875377+00:00
Catalog K scored=4 (frozen core=4; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Costs: fee=80 bps per side (Kraken Pro tier 1 taker; source=`kraken_pro_tier_taker`) + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-28T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-17T00:00:00+00:00; bars BTC=720 / ETH=720 / SOL=720).
`era_prints_available=false` (#133 pending); `dsr_pbo_available=false` (#135 pending); `multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.
Universe: 38 frozen candidates, 43 pulled, 0 skipped; membership top-20 by median 30-bar close×volume ≥ $2,000,000 with ≥ 365 prior bars; last snapshot 8 members.

## Honesty / pre-registered rules

Pre-registered ensemble-trend dual-print bar (#137; frozen before any Kraken or Binance.US score). Treatment: for each lookback N in {5, 10, 20, 30, 60, 90, 150, 250, 360}, entry rule `close_above_prior_n_max_close`: that lookback opens long when close[t] > max close of bars [t-N, t) (bar t never sets its own level). Stop rule `max_prior_stop_close_channel_midpoint`: on entry the stop is the midpoint of the prior N-bar close channel; every later bar the stop is max(prior stop, current prior-window midpoint) and never ratchets down; exit to flat when close[t] < stop; re-entry needs a fresh breakout on a later bar. Ensemble weight = (open lookbacks / total lookbacks) × min(0.25 / annualised 90-bar realised vol through close[t], 1.0), long-only, capped at 1 (paper spot has no leverage). Decision at close[t]; fill at t+1 open. Universe: frozen CANDIDATE_UNIVERSE Kraken USD spot pairs with a monthly point-in-time snapshot (bars strictly before the month start only): listed ≥ 365 prior daily bars (a 720-cap series is inferred to predate the window) and median 30-bar close×volume ≥ $2,000,000 (Kraken-local volume, stricter than the paper's aggregate); top-20 by that median are members; a non-member bar is forced flat. Kraken REST serves only currently-listed pairs, so this window is survivorship-biased (unlike the paper). Fees: Kraken Pro tier table (taker leg per side; default tier 1 = 80 bps) unless --fee-bps is explicit; gate C doubles. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Era prints (#133) and DSR / PBO (#135) are era_prints_available=false / dsr_pbo_available=false until they land; they are not invented. The shared harness charges fees on full equity at every rebalance regardless of fractional weight (cost-overstated, conservative). The precomputed series restarts stop state from the series start, like the #118 lookup voter. Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not a #118 Donchian N retune, not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, and not a carry/basis family. Frozen ensemble-trend v2 consensus catalog (K=4): `ens_trend_v2_maj_mid_vt15` (lookbacks {30,60,90,150}, min_open=2, 15% vol), `ens_trend_v2_maj_long_vt15` (lookbacks {60,90,150,250}, min_open=2, 15% vol), `ens_trend_v2_strict_mid_vt15` (lookbacks {20,30,60,90,150}, min_open=3, 15% vol), plus informational control `ma_cross_10_30` (cannot promote). Distinct from the #137 ENSEMBLE_CATALOG — do not retune either list after seeing PnL. PAPER_PROMOTE_* stays false. catalog_name=v2; second_print_mode=concurrent_venue_harder_gates. This run scored K=4 (core ids frozen at 4). Fees: 80 bps (kraken_pro_tier_taker, Kraken Pro tier 1) + slippage 5 bps. Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Universe snapshot policy (frozen before scoring)

Universe snapshot policy (frozen): on the first bar of each UTC month, using only bars strictly before that month, a name is a member when it has ≥ 365 prior daily bars (or its Kraken series hits the 720-bar public cap, which implies the listing predates the window) and its median 30-bar close×volume is ≥ $2,000,000; the top-20 by that median are members for the whole month. Fewer than 20 qualifiers means a smaller book, never a relaxed bar. A non-member bar is forced flat. Membership never looks at bars inside or after the month it governs.

Survivorship: Kraken public REST returns OHLC only for pairs that are listed today, and at most 720 daily bars each. The frozen CANDIDATE_UNIVERSE therefore omits every delisted name and cannot reproduce the paper's survivorship-bias-free 2015–2025 universe. The monthly point-in-time snapshot removes look-ahead in membership only; it does not remove delisting bias. Treat any pass on this window as an upper bound until the #133 archives supply delisted histories.

Frozen candidate universe: `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, `DOGE/USD`, `ADA/USD`, `SUI/USD`, `LINK/USD`, `XMR/USD`, `NEAR/USD`, `UNI/USD`, `LTC/USD`, `ENA/USD`, `PEPE/USD`, `CRV/USD`, `XLM/USD`, `AAVE/USD`, `AVAX/USD`, `ONDO/USD`, `TRX/USD`, `BCH/USD`, `INJ/USD`, `ICP/USD`, `FET/USD`, `POL/USD`, `ARB/USD`, `DOT/USD`, `JUP/USD`, `ALGO/USD`, `APT/USD`, `ZEC/USD`, `TAO/USD`, `DASH/USD`, `TON/USD`, `HBAR/USD`, `BNB/USD`, `TRUMP/USD`, `HYPE/USD`

Pulled: `AAVE/USD`, `ADA/USD`, `ALGO/USD`, `APT/USD`, `ARB/USD`, `ATOM/USD`, `AVAX/USD`, `BCH/USD`, `BLUR/USD`, `BTC/USD`, `COMP/USD`, `CRV/USD`, `DOGE/USD`, `DOT/USD`, `ENS/USD`, `ETC/USD`, `ETH/USD`, `FET/USD`, `FIL/USD`, `GRT/USD`, `HBAR/USD`, `ICP/USD`, `IMX/USD`, `INJ/USD`, `LDO/USD`, `LINK/USD`, `LTC/USD`, `MANA/USD`, `NEAR/USD`, `OP/USD`, `PEPE/USD`, `RENDER/USD`, `SAND/USD`, `SEI/USD`, `SHIB/USD`, `SNX/USD`, `SOL/USD`, `SUI/USD`, `SUSHI/USD`, `TIA/USD`, `UNI/USD`, `XLM/USD`, `XRP/USD`. Skipped (not invented): none.

| month | members |
| --- | ---: |
| 2024-09-01 | 0 |
| 2024-10-01 | 0 |
| 2024-11-01 | 8 |
| 2024-12-01 | 20 |
| 2025-01-01 | 20 |
| 2025-02-01 | 16 |
| 2025-03-01 | 11 |
| 2025-04-01 | 10 |
| 2025-05-01 | 10 |
| 2025-06-01 | 12 |
| 2025-07-01 | 10 |
| 2025-08-01 | 14 |
| 2025-09-01 | 13 |
| 2025-10-01 | 12 |
| 2025-11-01 | 11 |
| 2025-12-01 | 13 |
| 2026-01-01 | 9 |
| 2026-02-01 | 9 |
| 2026-03-01 | 10 |
| 2026-04-01 | 7 |
| 2026-05-01 | 7 |
| 2026-06-01 | 11 |
| 2026-07-01 | 12 |
| 2026-08-01 | 9 |
| 2026-09-01 | 8 |

Last snapshot members: `ADA/USD`, `BTC/USD`, `DOGE/USD`, `ETH/USD`, `LINK/USD`, `SOL/USD`, `SUI/USD`, `XRP/USD`.

## Fee tier (frozen)

| Kraken Pro tier | maker bps | taker bps |
| ---: | ---: | ---: |
| 1 (default) | 40 | 80 |
| 2 | 30 | 60 |
| 3 | 22 | 38 |
| 8 | 8 | 20 |
| 12 | 0 | 10 |

The taker leg is charged per side by the shared harness on full equity at every rebalance (fractional weights are cost-overstated; conservative). Gate C doubles fee and slippage. Post-only maker realism is #138.

## Dual-print bar (frozen before scoring)

Pre-registered ensemble-trend dual-print bar (#137; frozen before any Kraken or Binance.US score). Treatment: for each lookback N in {5, 10, 20, 30, 60, 90, 150, 250, 360}, entry rule `close_above_prior_n_max_close`: that lookback opens long when close[t] > max close of bars [t-N, t) (bar t never sets its own level). Stop rule `max_prior_stop_close_channel_midpoint`: on entry the stop is the midpoint of the prior N-bar close channel; every later bar the stop is max(prior stop, current prior-window midpoint) and never ratchets down; exit to flat when close[t] < stop; re-entry needs a fresh breakout on a later bar. Ensemble weight = (open lookbacks / total lookbacks) × min(0.25 / annualised 90-bar realised vol through close[t], 1.0), long-only, capped at 1 (paper spot has no leverage). Decision at close[t]; fill at t+1 open. Universe: frozen CANDIDATE_UNIVERSE Kraken USD spot pairs with a monthly point-in-time snapshot (bars strictly before the month start only): listed ≥ 365 prior daily bars (a 720-cap series is inferred to predate the window) and median 30-bar close×volume ≥ $2,000,000 (Kraken-local volume, stricter than the paper's aggregate); top-20 by that median are members; a non-member bar is forced flat. Kraken REST serves only currently-listed pairs, so this window is survivorship-biased (unlike the paper). Fees: Kraken Pro tier table (taker leg per side; default tier 1 = 80 bps) unless --fee-bps is explicit; gate C doubles. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Era prints (#133) and DSR / PBO (#135) are era_prints_available=false / dsr_pbo_available=false until they land; they are not invented. The shared harness charges fees on full equity at every rebalance regardless of fractional weight (cost-overstated, conservative). The precomputed series restarts stop state from the series start, like the #118 lookup voter. Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not a #118 Donchian N retune, not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |
| Era prints 2016-19 / 2020-22 / 2022-24 / 2024-26 (#133) + DSR / PBO (#135) | **unavailable in this run** — not scored, not invented | n/a |

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: require BTC and ETH walk-forward total > 0 and holdout excess > 0, plus A/B/C, exactly as #96+#104. SOL walk-forward and holdout are printed in the tables when the series exists and **do not** gate. Equal-weight portfolio metrics were considered and **rejected** before scoring. The 20-name book is a research construct: the paper path still cycles only `Settings.effective_cycle_symbols` under `RISK_MAX_OPEN_POSITIONS`.

## Treatment (frozen)

For each lookback N the position opens long when close[t] > max close of bars `[t-N, t)`; the stop starts at the prior close-channel midpoint and ratchets to max(prior stop, current midpoint); exit when close[t] < stop; re-entry needs a fresh breakout. Weight = open fraction × min(0.25 / 90-bar annualised realised vol, 1). Long-only, capped at 1.0 (no leverage). Decision at close[t]; fill at t+1 open. A missing series is skipped, never zero-filled.

Warmup on the 720-bar cap: the nine-lookback book needs 361 bars before its first assignment (~359 decision bars remain), so early walk-forward folds are all-flat and min_trades may fail. That is reported as skipped / warmup-limited, never invented, and is why `ens_trend_6lb_vt25` is in the same frozen catalog.

## Pre-registered catalog

Frozen ensemble-trend v2 consensus catalog (K=4): `ens_trend_v2_maj_mid_vt15` (lookbacks {30,60,90,150}, min_open=2, 15% vol), `ens_trend_v2_maj_long_vt15` (lookbacks {60,90,150,250}, min_open=2, 15% vol), `ens_trend_v2_strict_mid_vt15` (lookbacks {20,30,60,90,150}, min_open=3, 15% vol), plus informational control `ma_cross_10_30` (cannot promote). Distinct from the #137 ENSEMBLE_CATALOG — do not retune either list after seeing PnL. PAPER_PROMOTE_* stays false.

Frozen core ids: `ens_trend_9lb_vt25`, `ens_trend_6lb_vt25`, `ens_trend_9lb_unit`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. `EnsembleTrendVoter` is a candle-only voter: BUY with score in (0, 1] when the ensemble weight is positive, side=None otherwise, never SELL. When no precomputed series is registered for a symbol it recomputes `ensemble_trend_series` on the decision-time candles it is given, so the existing pre-trade gate can re-confirm it. The weight travels only as StrategySignal.score / confidence; RiskEngine sizes from Settings and can only reduce. The strategy's trailing stop is a research construct — runtime exits remain the EXIT_* rules. No perp, no leverage, no hedge book. A Settings pin is still added only if a committed dual-print passer exists, and then default false; none is added by #137.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- kraken:loaded 720 1d bars for AAVE/USD from var/research/candles/kraken/AAVE_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ADA/USD from var/research/candles/kraken/ADA_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ALGO/USD from var/research/candles/kraken/ALGO_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for APT/USD from var/research/candles/kraken/APT_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ARB/USD from var/research/candles/kraken/ARB_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ATOM/USD from var/research/candles/kraken/ATOM_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for AVAX/USD from var/research/candles/kraken/AVAX_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for BCH/USD from var/research/candles/kraken/BCH_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for BLUR/USD from var/research/candles/kraken/BLUR_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for BTC/USD from var/research/candles/kraken/BTC_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for COMP/USD from var/research/candles/kraken/COMP_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for CRV/USD from var/research/candles/kraken/CRV_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for DOGE/USD from var/research/candles/kraken/DOGE_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for DOT/USD from var/research/candles/kraken/DOT_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ENS/USD from var/research/candles/kraken/ENS_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ETC/USD from var/research/candles/kraken/ETC_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ETH/USD from var/research/candles/kraken/ETH_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for FET/USD from var/research/candles/kraken/FET_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for FIL/USD from var/research/candles/kraken/FIL_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for GRT/USD from var/research/candles/kraken/GRT_USD_1d.json (candles_dir)
- kraken:loaded 435 1d bars for HBAR/USD from var/research/candles/kraken/HBAR_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for ICP/USD from var/research/candles/kraken/ICP_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for IMX/USD from var/research/candles/kraken/IMX_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for INJ/USD from var/research/candles/kraken/INJ_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for LDO/USD from var/research/candles/kraken/LDO_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for LINK/USD from var/research/candles/kraken/LINK_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for LTC/USD from var/research/candles/kraken/LTC_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for MANA/USD from var/research/candles/kraken/MANA_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for NEAR/USD from var/research/candles/kraken/NEAR_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for OP/USD from var/research/candles/kraken/OP_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for PEPE/USD from var/research/candles/kraken/PEPE_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for RENDER/USD from var/research/candles/kraken/RENDER_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SAND/USD from var/research/candles/kraken/SAND_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SEI/USD from var/research/candles/kraken/SEI_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SHIB/USD from var/research/candles/kraken/SHIB_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SNX/USD from var/research/candles/kraken/SNX_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SOL/USD from var/research/candles/kraken/SOL_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SUI/USD from var/research/candles/kraken/SUI_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for SUSHI/USD from var/research/candles/kraken/SUSHI_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for TIA/USD from var/research/candles/kraken/TIA_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for UNI/USD from var/research/candles/kraken/UNI_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for XLM/USD from var/research/candles/kraken/XLM_USD_1d.json (candles_dir)
- kraken:loaded 720 1d bars for XRP/USD from var/research/candles/kraken/XRP_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for AAVE/USD from var/research/candles/coinbase/AAVE_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ADA/USD from var/research/candles/coinbase/ADA_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ALGO/USD from var/research/candles/coinbase/ALGO_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for APT/USD from var/research/candles/coinbase/APT_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ARB/USD from var/research/candles/coinbase/ARB_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ATOM/USD from var/research/candles/coinbase/ATOM_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for AVAX/USD from var/research/candles/coinbase/AVAX_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for BCH/USD from var/research/candles/coinbase/BCH_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for BLUR/USD from var/research/candles/coinbase/BLUR_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for BTC/USD from var/research/candles/coinbase/BTC_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for COMP/USD from var/research/candles/coinbase/COMP_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for CRV/USD from var/research/candles/coinbase/CRV_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for DOGE/USD from var/research/candles/coinbase/DOGE_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for DOT/USD from var/research/candles/coinbase/DOT_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ENS/USD from var/research/candles/coinbase/ENS_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ETC/USD from var/research/candles/coinbase/ETC_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ETH/USD from var/research/candles/coinbase/ETH_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for FET/USD from var/research/candles/coinbase/FET_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for FIL/USD from var/research/candles/coinbase/FIL_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for GRT/USD from var/research/candles/coinbase/GRT_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for HBAR/USD from var/research/candles/coinbase/HBAR_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for ICP/USD from var/research/candles/coinbase/ICP_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for IMX/USD from var/research/candles/coinbase/IMX_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for INJ/USD from var/research/candles/coinbase/INJ_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for LDO/USD from var/research/candles/coinbase/LDO_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for LINK/USD from var/research/candles/coinbase/LINK_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for LTC/USD from var/research/candles/coinbase/LTC_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for MANA/USD from var/research/candles/coinbase/MANA_USD_1d.json (candles_dir)
- coinbase:loaded 386 1d bars for MATIC/USD from var/research/candles/coinbase/MATIC_USD_1d.json (candles_dir)
- coinbase:loaded 476 1d bars for MKR/USD from var/research/candles/coinbase/MKR_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for NEAR/USD from var/research/candles/coinbase/NEAR_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for OP/USD from var/research/candles/coinbase/OP_USD_1d.json (candles_dir)
- coinbase:loaded 674 1d bars for PEPE/USD from var/research/candles/coinbase/PEPE_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for RENDER/USD from var/research/candles/coinbase/RENDER_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SAND/USD from var/research/candles/coinbase/SAND_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SEI/USD from var/research/candles/coinbase/SEI_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SHIB/USD from var/research/candles/coinbase/SHIB_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SNX/USD from var/research/candles/coinbase/SNX_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SOL/USD from var/research/candles/coinbase/SOL_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SUI/USD from var/research/candles/coinbase/SUI_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for SUSHI/USD from var/research/candles/coinbase/SUSHI_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for TIA/USD from var/research/candles/coinbase/TIA_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for UNI/USD from var/research/candles/coinbase/UNI_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for XLM/USD from var/research/candles/coinbase/XLM_USD_1d.json (candles_dir)
- coinbase:loaded 724 1d bars for XRP/USD from var/research/candles/coinbase/XRP_USD_1d.json (candles_dir)
- candles-dir kraken: 43 series; venues=['coinbase', 'kraken'] in 0s
- primary first bar 2024-09-28T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- gate symbols=BTC/USD,ETH/USD (SOL/USD reported); remaining universe names feed point-in-time membership only (skip-not-invent)
- catalog=v2
- SOL/USD present (720 bars); reported, not a gate.

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the same research costs as the Kraken print: `max(PRETRADE_FEE_BPS, PAPER_FEE_TIER taker)` + `PRETRADE_SLIPPAGE_BPS` (exact numbers in the report's fee tier line; gate C doubles both) so costs stay comparable. Binance.US's own taker is not substituted and no maker rebate is assumed. Not a VIP study. Quote is USDT, not USD.

- Rule: `concurrent_venue_harder_gates`
- Venue label: `coinbase`
- Status: **available**
- Bars: BTC 724 / ETH 724 / SOL 724
- Span: 2024-09-24T00:00:00+00:00 → 2026-09-17T00:00:00+00:00
- Overlaps primary window: yes
- Fail-closed reason: —

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping BTC/ETH series fails closed. Empty Binance means zero dual-print passers (success). Missing SOL on Binance is report-only (not a gate).

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only ensemble names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only in a separate PR, default false.

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Kraken combined-passers (informational)

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## All rows (both prints)

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | `ens_trend_v2_maj_mid_vt15` | -6.54% | -6.28% | -6.80% | -23.23% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| — | `ens_trend_v2_maj_long_vt15` | -4.69% | -3.75% | -5.63% | -20.83% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| — | `ens_trend_v2_strict_mid_vt15` | -5.74% | -6.49% | -4.99% | -21.20% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| — | `ma_cross_10_30` | -7.32% | -1.99% | -12.65% | -1.55% | n/a | FAIL | FAIL | FAIL | FAIL | no |

Binance side:

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| `ens_trend_v2_maj_mid_vt15` | -6.46% | -6.16% | -6.76% | -23.23% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| `ens_trend_v2_maj_long_vt15` | -4.65% | -3.71% | -5.59% | -20.83% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| `ens_trend_v2_strict_mid_vt15` | -5.67% | -6.39% | -4.95% | -21.20% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| `ma_cross_10_30` | -7.33% | -1.99% | -12.66% | -1.62% | n/a | FAIL | FAIL | FAIL | FAIL | no |

## Attribution (gross close-to-close; informational, not a gate)

Per bar the ensemble contributes weight[t] × (close[t+1]/close[t] − 1); each lookback's share is its open fraction of that weight. No fees or slippage. The lookback columns sum to the asset total for each book.

| book | asset | gross contribution |
| --- | --- | ---: |
| `ens_trend_v2_maj_mid_vt15` | BTC/USD | -3.79% |
| `ens_trend_v2_maj_mid_vt15` | ETH/USD | +6.78% |
| `ens_trend_v2_maj_mid_vt15` | SOL/USD | -3.22% |
| `ens_trend_v2_maj_long_vt15` | BTC/USD | -3.06% |
| `ens_trend_v2_maj_long_vt15` | ETH/USD | +4.44% |
| `ens_trend_v2_maj_long_vt15` | SOL/USD | -2.79% |
| `ens_trend_v2_strict_mid_vt15` | BTC/USD | -1.97% |
| `ens_trend_v2_strict_mid_vt15` | ETH/USD | +3.99% |
| `ens_trend_v2_strict_mid_vt15` | SOL/USD | -0.65% |

| book | lookback | gross contribution |
| --- | ---: | ---: |
| `ens_trend_v2_maj_mid_vt15` | 30 | +1.38% |
| `ens_trend_v2_maj_mid_vt15` | 60 | -0.78% |
| `ens_trend_v2_maj_mid_vt15` | 90 | -0.73% |
| `ens_trend_v2_maj_mid_vt15` | 150 | -0.11% |
| `ens_trend_v2_maj_long_vt15` | 60 | -1.12% |
| `ens_trend_v2_maj_long_vt15` | 90 | -0.18% |
| `ens_trend_v2_maj_long_vt15` | 150 | +0.84% |
| `ens_trend_v2_maj_long_vt15` | 250 | -0.95% |
| `ens_trend_v2_strict_mid_vt15` | 20 | +1.08% |
| `ens_trend_v2_strict_mid_vt15` | 30 | +1.75% |
| `ens_trend_v2_strict_mid_vt15` | 60 | +0.58% |
| `ens_trend_v2_strict_mid_vt15` | 90 | -0.99% |
| `ens_trend_v2_strict_mid_vt15` | 150 | -1.05% |

## Recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (coinbase; 724 BTC / 724 ETH / 724 SOL; 2024-09-24T00:00:00+00:00 → 2026-09-17T00:00:00+00:00).
- Multi-asset gate: `btc_eth_signs_as_96_abc_sol_reported_not_required` (SOL reported, not required).
- Era prints: era_prints_available=false (#133 pending); DSR / PBO: dsr_pbo_available=false (#135 pending). Re-run and re-commit when they land; nothing here is invented.
- Paper path: ready on Kraken spot BTC/ETH (SOL optional; PAPER_PATH_READY=true); long-only, score in [0, 1], RiskEngine can only reduce.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not widen RISK_MAX_OPEN_POSITIONS, MVP_ASSETS or PAPER_PROMOTE_UNIVERSE for a 20-name book (see docs/EXECUTION-ARCHITECTURE.md).

## Gates

Pre-registered harder gates (frozen before the Kraken window is scored). A — magnitude: both BTC and ETH holdout excess > 0 and min/max holdout ratio >= 0.25 (reject ETH-only magnitude). B — multi-window: three contiguous 240-bar Kraken daily slices; each uses #96 walk-forward (train=180, test=60, step=60) with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3 windows. C — fee stress: 2× fee and slippage (defaults 10+5 → 20+10 bps) must still clear #96 balanced signs. Combined requires #96 balanced-holdout and A and B and C. Ranking key (frozen before scoring): mean_holdout_excess_among_combined_passers — Kraken BTC+ETH mean holdout excess among combined-passers; full-catalog walk-forward rank is informational. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 stays false.
