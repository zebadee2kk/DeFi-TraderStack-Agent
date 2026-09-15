# Ensemble trend dual-print (#137; BTC+ETH gate; SOL reported; top-20 PIT universe)

Generated: 2026-09-14T09:33:18.380908+00:00
Catalog K scored=4 (frozen core=4; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Costs: fee=80 bps per side (Kraken Pro tier 1 taker; source=`kraken_pro_tier_taker`) + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-24T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-13T00:00:00+00:00; bars BTC=720 / ETH=720 / SOL=720).
`era_prints_available=false` (#133 pending); `dsr_pbo_available=false` (#135 pending); `multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.
Universe: 38 frozen candidates, 38 pulled, 0 skipped; membership top-20 by median 30-bar close×volume ≥ $2,000,000 with ≥ 365 prior bars; last snapshot 11 members.

## Honesty / pre-registered rules

Pre-registered ensemble-trend dual-print bar (#137; frozen before any Kraken or Binance.US score). Treatment: for each lookback N in {5, 10, 20, 30, 60, 90, 150, 250, 360}, entry rule `close_above_prior_n_max_close`: that lookback opens long when close[t] > max close of bars [t-N, t) (bar t never sets its own level). Stop rule `max_prior_stop_close_channel_midpoint`: on entry the stop is the midpoint of the prior N-bar close channel; every later bar the stop is max(prior stop, current prior-window midpoint) and never ratchets down; exit to flat when close[t] < stop; re-entry needs a fresh breakout on a later bar. Ensemble weight = (open lookbacks / total lookbacks) × min(0.25 / annualised 90-bar realised vol through close[t], 1.0), long-only, capped at 1 (paper spot has no leverage). Decision at close[t]; fill at t+1 open. Universe: frozen CANDIDATE_UNIVERSE Kraken USD spot pairs with a monthly point-in-time snapshot (bars strictly before the month start only): listed ≥ 365 prior daily bars (a 720-cap series is inferred to predate the window) and median 30-bar close×volume ≥ $2,000,000 (Kraken-local volume, stricter than the paper's aggregate); top-20 by that median are members; a non-member bar is forced flat. Kraken REST serves only currently-listed pairs, so this window is survivorship-biased (unlike the paper). Fees: Kraken Pro tier table (taker leg per side; default tier 1 = 80 bps) unless --fee-bps is explicit; gate C doubles. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Era prints (#133) and DSR / PBO (#135) are era_prints_available=false / dsr_pbo_available=false until they land; they are not invented. The shared harness charges fees on full equity at every rebalance regardless of fractional weight (cost-overstated, conservative). The precomputed series restarts stop state from the series start, like the #118 lookup voter. Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not a #118 Donchian N retune, not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, and not a carry/basis family. Frozen catalog (K=4): `ens_trend_9lb_vt25` (all nine lookbacks, 25% vol target), `ens_trend_6lb_vt25` (lookbacks {5, 10, 20, 30, 60, 90}, 25% vol target; pre-registered because the 720-bar Kraken cap leaves the nine-lookback book warmup-limited to ~359 decision bars — this is not a post-hoc retune), `ens_trend_9lb_unit` (all nine lookbacks, open-fraction weight without the vol scalar; informational contrast), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Channels, stops and vol are built from venue-local closes; a missing or short series is skipped, never zero-filled. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=4 (core ids frozen at 4). Fees: 80 bps (kraken_pro_tier_taker, Kraken Pro tier 1) + slippage 5 bps. Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Universe snapshot policy (frozen before scoring)

Universe snapshot policy (frozen): on the first bar of each UTC month, using only bars strictly before that month, a name is a member when it has ≥ 365 prior daily bars (or its Kraken series hits the 720-bar public cap, which implies the listing predates the window) and its median 30-bar close×volume is ≥ $2,000,000; the top-20 by that median are members for the whole month. Fewer than 20 qualifiers means a smaller book, never a relaxed bar. A non-member bar is forced flat. Membership never looks at bars inside or after the month it governs.

Survivorship: Kraken public REST returns OHLC only for pairs that are listed today, and at most 720 daily bars each. The frozen CANDIDATE_UNIVERSE therefore omits every delisted name and cannot reproduce the paper's survivorship-bias-free 2015–2025 universe. The monthly point-in-time snapshot removes look-ahead in membership only; it does not remove delisting bias. Treat any pass on this window as an upper bound until the #133 archives supply delisted histories.

Frozen candidate universe: `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, `DOGE/USD`, `ADA/USD`, `SUI/USD`, `LINK/USD`, `XMR/USD`, `NEAR/USD`, `UNI/USD`, `LTC/USD`, `ENA/USD`, `PEPE/USD`, `CRV/USD`, `XLM/USD`, `AAVE/USD`, `AVAX/USD`, `ONDO/USD`, `TRX/USD`, `BCH/USD`, `INJ/USD`, `ICP/USD`, `FET/USD`, `POL/USD`, `ARB/USD`, `DOT/USD`, `JUP/USD`, `ALGO/USD`, `APT/USD`, `ZEC/USD`, `TAO/USD`, `DASH/USD`, `TON/USD`, `HBAR/USD`, `BNB/USD`, `TRUMP/USD`, `HYPE/USD`

Pulled: `AAVE/USD`, `ADA/USD`, `ALGO/USD`, `APT/USD`, `ARB/USD`, `AVAX/USD`, `BCH/USD`, `BNB/USD`, `BTC/USD`, `CRV/USD`, `DASH/USD`, `DOGE/USD`, `DOT/USD`, `ENA/USD`, `ETH/USD`, `FET/USD`, `HBAR/USD`, `HYPE/USD`, `ICP/USD`, `INJ/USD`, `JUP/USD`, `LINK/USD`, `LTC/USD`, `NEAR/USD`, `ONDO/USD`, `PEPE/USD`, `POL/USD`, `SOL/USD`, `SUI/USD`, `TAO/USD`, `TON/USD`, `TRUMP/USD`, `TRX/USD`, `UNI/USD`, `XLM/USD`, `XMR/USD`, `XRP/USD`, `ZEC/USD`. Skipped (not invented): none.

| month | members |
| --- | ---: |
| 2024-09-01 | 0 |
| 2024-10-01 | 0 |
| 2024-11-01 | 8 |
| 2024-12-01 | 18 |
| 2025-01-01 | 20 |
| 2025-02-01 | 19 |
| 2025-03-01 | 13 |
| 2025-04-01 | 12 |
| 2025-05-01 | 11 |
| 2025-06-01 | 15 |
| 2025-07-01 | 11 |
| 2025-08-01 | 16 |
| 2025-09-01 | 16 |
| 2025-10-01 | 15 |
| 2025-11-01 | 15 |
| 2025-12-01 | 17 |
| 2026-01-01 | 12 |
| 2026-02-01 | 13 |
| 2026-03-01 | 12 |
| 2026-04-01 | 10 |
| 2026-05-01 | 10 |
| 2026-06-01 | 15 |
| 2026-07-01 | 15 |
| 2026-08-01 | 12 |
| 2026-09-01 | 11 |

Last snapshot members: `ADA/USD`, `BTC/USD`, `DOGE/USD`, `ETH/USD`, `LINK/USD`, `SOL/USD`, `SUI/USD`, `TAO/USD`, `XMR/USD`, `XRP/USD`, `ZEC/USD`.

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

Frozen catalog (K=4): `ens_trend_9lb_vt25` (all nine lookbacks, 25% vol target), `ens_trend_6lb_vt25` (lookbacks {5, 10, 20, 30, 60, 90}, 25% vol target; pre-registered because the 720-bar Kraken cap leaves the nine-lookback book warmup-limited to ~359 decision bars — this is not a post-hoc retune), `ens_trend_9lb_unit` (all nine lookbacks, open-fraction weight without the vol scalar; informational contrast), plus informational control ma_cross_10_30 (cannot promote). Do not grow this list after seeing PnL. Channels, stops and vol are built from venue-local closes; a missing or short series is skipped, never zero-filled. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `ens_trend_9lb_vt25`, `ens_trend_6lb_vt25`, `ens_trend_9lb_unit`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. `EnsembleTrendVoter` is a candle-only voter: BUY with score in (0, 1] when the ensemble weight is positive, side=None otherwise, never SELL. When no precomputed series is registered for a symbol it recomputes `ensemble_trend_series` on the decision-time candles it is given, so the existing pre-trade gate can re-confirm it. The weight travels only as StrategySignal.score / confidence; RiskEngine sizes from Settings and can only reduce. The strategy's trailing stop is a research construct — runtime exits remain the EXIT_* rules. No perp, no leverage, no hedge book. A Settings pin is still added only if a committed dual-print passer exists, and then default false; none is added by #137.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- XRP/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- DOGE/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ADA/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- SUI/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- LINK/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- XMR/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- NEAR/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- UNI/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- LTC/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ENA/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- PEPE/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- CRV/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- XLM/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- AAVE/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- AVAX/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ONDO/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- TRX/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- BCH/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- INJ/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ICP/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- FET/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- POL/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ARB/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- DOT/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- JUP/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ALGO/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- APT/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- ZEC/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- TAO/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- DASH/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap)
- TON/USD@1d: 703 committed Kraken bars 2024-10-11T00:00:00+00:00 → 2026-09-13T00:00:00+00:00
- HBAR/USD@1d: 431 committed Kraken bars 2025-07-10T00:00:00+00:00 → 2026-09-13T00:00:00+00:00
- BNB/USD@1d: 510 committed Kraken bars 2025-04-22T00:00:00+00:00 → 2026-09-13T00:00:00+00:00
- TRUMP/USD@1d: 604 committed Kraken bars 2025-01-18T00:00:00+00:00 → 2026-09-13T00:00:00+00:00
- HYPE/USD@1d: 229 committed Kraken bars 2026-01-28T00:00:00+00:00 → 2026-09-13T00:00:00+00:00
- universe pull: 38 of 38 symbols in 48s; skipped=0
- primary first bar 2024-09-24T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- gate symbols=BTC/USD,ETH/USD (SOL/USD reported); remaining universe names feed point-in-time membership only (skip-not-invent)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 (non-Kraken; report-only)
- SOLUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- SOLUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- SOLUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 (non-Kraken; report-only)
- SOL/USD present (720 bars); reported, not a gate.

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720 / SOL 720
- Span: 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00
- Overlaps primary window: no
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
| — | `ens_trend_9lb_vt25` | -38.39% | -35.97% | -40.81% | -41.37% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| — | `ens_trend_6lb_vt25` | -42.00% | -39.58% | -44.42% | -47.42% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| — | `ens_trend_9lb_unit` | -40.93% | -37.51% | -44.34% | -46.62% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| — | `ma_cross_10_30` | -8.66% | -3.68% | -13.65% | -3.35% | n/a | FAIL | FAIL | FAIL | FAIL | no |

Binance side:

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| `ens_trend_9lb_vt25` | -4.58% | -20.51% | +11.36% | -5.28% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| `ens_trend_6lb_vt25` | -10.28% | -31.91% | +11.36% | -5.28% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| `ens_trend_9lb_unit` | -11.60% | -34.56% | +11.36% | -5.28% | n/a | FAIL | FAIL | FAIL | FAIL | no |
| `ma_cross_10_30` | -40.55% | -57.03% | -24.08% | -27.01% | n/a | FAIL | FAIL | FAIL | FAIL | no |

## Attribution (gross close-to-close; informational, not a gate)

Per bar the ensemble contributes weight[t] × (close[t+1]/close[t] − 1); each lookback's share is its open fraction of that weight. No fees or slippage. The lookback columns sum to the asset total for each book.

| book | asset | gross contribution |
| --- | --- | ---: |
| `ens_trend_9lb_vt25` | BTC/USD | -6.87% |
| `ens_trend_9lb_vt25` | ETH/USD | -5.64% |
| `ens_trend_9lb_vt25` | SOL/USD | -3.35% |
| `ens_trend_6lb_vt25` | BTC/USD | -2.80% |
| `ens_trend_6lb_vt25` | ETH/USD | +8.37% |
| `ens_trend_6lb_vt25` | SOL/USD | -1.23% |
| `ens_trend_9lb_unit` | BTC/USD | -8.26% |
| `ens_trend_9lb_unit` | ETH/USD | -17.53% |
| `ens_trend_9lb_unit` | SOL/USD | -13.90% |

| book | lookback | gross contribution |
| --- | ---: | ---: |
| `ens_trend_9lb_vt25` | 5 | +0.92% |
| `ens_trend_9lb_vt25` | 10 | -0.96% |
| `ens_trend_9lb_vt25` | 20 | -2.52% |
| `ens_trend_9lb_vt25` | 30 | -1.58% |
| `ens_trend_9lb_vt25` | 60 | -3.12% |
| `ens_trend_9lb_vt25` | 90 | -2.24% |
| `ens_trend_9lb_vt25` | 150 | -2.22% |
| `ens_trend_9lb_vt25` | 250 | -2.39% |
| `ens_trend_9lb_vt25` | 360 | -1.75% |
| `ens_trend_6lb_vt25` | 5 | +0.39% |
| `ens_trend_6lb_vt25` | 10 | +1.85% |
| `ens_trend_6lb_vt25` | 20 | +4.16% |
| `ens_trend_6lb_vt25` | 30 | +2.57% |
| `ens_trend_6lb_vt25` | 60 | -3.41% |
| `ens_trend_6lb_vt25` | 90 | -1.23% |
| `ens_trend_9lb_unit` | 5 | -1.05% |
| `ens_trend_9lb_unit` | 10 | -4.04% |
| `ens_trend_9lb_unit` | 20 | -6.94% |
| `ens_trend_9lb_unit` | 30 | -3.45% |
| `ens_trend_9lb_unit` | 60 | -6.88% |
| `ens_trend_9lb_unit` | 90 | -4.32% |
| `ens_trend_9lb_unit` | 150 | -5.68% |
| `ens_trend_9lb_unit` | 250 | -5.06% |
| `ens_trend_9lb_unit` | 360 | -2.27% |

## Recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH / 720 SOL; 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00).
- Multi-asset gate: `btc_eth_signs_as_96_abc_sol_reported_not_required` (SOL reported, not required).
- Era prints: era_prints_available=false (#133 pending); DSR / PBO: dsr_pbo_available=false (#135 pending). Re-run and re-commit when they land; nothing here is invented.
- Paper path: ready on Kraken spot BTC/ETH (SOL optional; PAPER_PATH_READY=true); long-only, score in [0, 1], RiskEngine can only reduce.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not widen RISK_MAX_OPEN_POSITIONS, MVP_ASSETS or PAPER_PROMOTE_UNIVERSE for a 20-name book (see docs/EXECUTION-ARCHITECTURE.md).

## Gates

Pre-registered harder gates (frozen before the Kraken window is scored). A — magnitude: both BTC and ETH holdout excess > 0 and min/max holdout ratio >= 0.25 (reject ETH-only magnitude). B — multi-window: three contiguous 240-bar Kraken daily slices; each uses #96 walk-forward (train=180, test=60, step=60) with no in-window holdout; BTC and ETH WF total > 0 in at least 2 of 3 windows. C — fee stress: 2× fee and slippage (defaults 10+5 → 20+10 bps) must still clear #96 balanced signs. Combined requires #96 balanced-holdout and A and B and C. Ranking key (frozen before scoring): mean_holdout_excess_among_combined_passers — Kraken BTC+ETH mean holdout excess among combined-passers; full-catalog walk-forward rank is informational. Yahoo is A/B only. PAPER_PROMOTE_EMA_9_21 stays false.
