# Volume-confirmed breakout dual-print (BTC+ETH; SOL optional)

Generated: 2026-09-12T21:42:43.865228+00:00
Catalog K scored=8 (frozen core=8; ranking_key=`mean_holdout_excess_among_dual_print_passers`).
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars BTC=720 / ETH=720 / SOL=720).
`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered volume-confirmed breakout dual-print bar (frozen before any Kraken or Binance.US score). Treatment: this is not a Donchian N retune (#118) — every promote-eligible name requires a volume gate. Breakout names compare close[t] to the prior N-day channel (max high / min low of bars [t-N, t); bar t's high/low never set the breakout level) **and** require volume[t] > V-day volume SMA × mult (V frozen at 20; decision `volume_sma_through_t_minus_1`: SMA on bars [t-V, t), bar t excluded). Exit rule `opposite_band_same_n`: long-only exits to flat when close[t] < prior N-day low (exit does not require volume); long/short flips short only when that band breaks **and** the same volume gate fires (unconfirmed opposite-band holds). Between the bands the previous side is held (start flat). Volume-surge names have no channel: long when volume[t] > SMA(V)×mult and close[t] > close[t−1]; flat otherwise. Missing or non-positive volume skips that bar (never invented). base volume only; quote volume is never substituted and a venue without usable base volume fails closed for volume names. Decision at bar t; fill `next_bar_open` (t+1 open — no look-ahead into the fill bar). Each asset uses its own OHLC; a missing/short series is skipped, never zero-filled. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, not TSMOM, not Bollinger fade, not calendar seasonality, not lead-lag, and not a carry/basis family. Frozen catalog (K=8): long-only volume-confirmed breakout (`volbrk_lo_{20x1_5,55x1_5,20x2}`), long/short symmetric (`volbrk_ls_{20x1_5,55x1_5}`), volume-surge long-only (`volsurge_lo_{20x2,20x2_5}`), plus informational control ma_cross_10_30 (cannot promote). V frozen at 20; volume SMA `volume_sma_through_t_minus_1`. Do not grow this list or retune N / V / mult after seeing PnL. Channel and volume SMA are built from venue-local OHLC; a missing series or missing volume is skipped, never zero-filled or invented. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it. This run scored K=8 (core ids frozen at 8). Kraken combined-passers (ex-control): 0. Binance combined-passers (ex-control): 0. Dual-print passers: 0. Informational BTC walk-forward fail (positive mean HO and BTC HO): `volbrk_lo_20x1_5`, `volbrk_lo_20x2`, `volsurge_lo_20x2`, `volsurge_lo_20x2_5`. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Dual-print bar (frozen before scoring)

Pre-registered volume-confirmed breakout dual-print bar (frozen before any Kraken or Binance.US score). Treatment: this is not a Donchian N retune (#118) — every promote-eligible name requires a volume gate. Breakout names compare close[t] to the prior N-day channel (max high / min low of bars [t-N, t); bar t's high/low never set the breakout level) **and** require volume[t] > V-day volume SMA × mult (V frozen at 20; decision `volume_sma_through_t_minus_1`: SMA on bars [t-V, t), bar t excluded). Exit rule `opposite_band_same_n`: long-only exits to flat when close[t] < prior N-day low (exit does not require volume); long/short flips short only when that band breaks **and** the same volume gate fires (unconfirmed opposite-band holds). Between the bands the previous side is held (start flat). Volume-surge names have no channel: long when volume[t] > SMA(V)×mult and close[t] > close[t−1]; flat otherwise. Missing or non-positive volume skips that bar (never invented). base volume only; quote volume is never substituted and a venue without usable base volume fails closed for volume names. Decision at bar t; fill `next_bar_open` (t+1 open — no look-ahead into the fill bar). Each asset uses its own OHLC; a missing/short series is skipped, never zero-filled. Multi-asset combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` — #96 balanced-holdout and A magnitude and B multi-window and C 2× fees on BTC and ETH; SOL is reported when present and is not a gate. Equal-weight portfolio metrics are not used. A dual-print passer must combined-PASS the Kraken primary 720-bar daily window AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed daily BTC+ETH bars ending strictly before the primary Kraken first bar). Ranking key: mean_holdout_excess_among_dual_print_passers — Kraken BTC+ETH mean holdout excess among dual-print passers (tie-break: candidate_id). Binance holdout is a gate only; CAN_AVERAGE_VENUES=false. MULTI_VENUE_BAR_PREREGISTERED=true. A Kraken-only combined-passer is not a dual-print passer and cannot promote. The informational control ma_cross_10_30 cannot enter the passer set. Missing, short, or overlapping Binance fails closed (zero dual-print passers). Fees are paper-research 10+5 (gate C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) (PAPER_PATH_READY=true). PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not an EMA reprint, not a BTC−ETH residual reprint, not cross-sectional momentum, not Donchian / channel breakout, not TSMOM, not Bollinger fade, not calendar seasonality, not lead-lag, and not a carry/basis family.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: require BTC and ETH walk-forward total > 0 and holdout excess > 0, plus A/B/C, exactly as #96+#104. SOL walk-forward and holdout are printed in the tables when the series exists and **do not** gate. Equal-weight portfolio metrics were considered and **rejected** before scoring — that would be a different bar and is not used here.

## Treatment (frozen)

This is **not** a Donchian N retune (#118): every promote-eligible name requires a volume gate. On each asset at bar t, the channel is the max high and min low of the prior N bars `[t-N, t)`. Bar t's high/low never enter that level. Volume SMA uses `volume_sma_through_t_minus_1` (V=20 bars `[t-V, t)`; bar t excluded). A missing or non-positive volume skips that bar and is never invented; quote volume is not a substitute. Exit rule `opposite_band_same_n`: long-only is flat after close[t] < prior low (no volume required to exit); long/short flips short only on that band **with** the same volume gate. Between the bands the previous side is held (start flat). Volume-surge names have no channel: long when volume[t] > SMA×mult and close[t] > close[t−1]; flat otherwise. Decision uses close[t]; the shared backtest fills at `next_bar_open` (bar t+1 open). A missing series is skipped, never zero-filled. A venue without usable base volume fails closed for volume names.

## Pre-registered catalog

Frozen catalog (K=8): long-only volume-confirmed breakout (`volbrk_lo_{20x1_5,55x1_5,20x2}`), long/short symmetric (`volbrk_ls_{20x1_5,55x1_5}`), volume-surge long-only (`volsurge_lo_{20x2,20x2_5}`), plus informational control ma_cross_10_30 (cannot promote). V frozen at 20; volume SMA `volume_sma_through_t_minus_1`. Do not grow this list or retune N / V / mult after seeing PnL. Channel and volume SMA are built from venue-local OHLC; a missing series or missing volume is skipped, never zero-filled or invented. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it.

Frozen core ids: `volbrk_lo_20x1_5`, `volbrk_lo_55x1_5`, `volbrk_lo_20x2`, `volbrk_ls_20x1_5`, `volbrk_ls_55x1_5`, `volsurge_lo_20x2`, `volsurge_lo_20x2_5`, `ma_cross_10_30`.

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
- Kraken BTC/USD: 720/720 bars with base volume > 0 (quote volume is not substituted).
- Kraken ETH/USD: 720/720 bars with base volume > 0 (quote volume is not substituted).
- Kraken SOL/USD: 720/720 bars with base volume > 0 (quote volume is not substituted).
- Binance.US BTC/USD: 720/720 bars with base volume > 0 (quote volume is not substituted).
- Binance.US ETH/USD: 720/720 bars with base volume > 0 (quote volume is not substituted).
- Binance.US SOL/USD: 720/720 bars with base volume > 0 (quote volume is not substituted).
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

`api.binance.com` is HTTP 451 from this environment; `api.binance.us` is labeled **Binance.US**, not Binance.com. A short or overlapping BTC/ETH series fails closed. Empty Binance means zero dual-print passers (success). Missing SOL on Binance is report-only (not a two-asset fallback and not a gate). Missing base volume fails closed for volume names; quote volume is not substituted.

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`. Only volume-confirmed names that already clear combined on **both** prints appear here. `ma_cross_10_30` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO | Kraken SOL HO | selected | can flip flag |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | no | no |

## Kraken combined-passers (informational)

These volume-confirmed names cleared #96+A+B+C on the Kraken primary window (BTC+ETH gates). They are **not** promotees unless they also appear in the dual-print table. Control omitted. SOL holdout is reported.

| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Binance.US combined-passers (informational)

These volume-confirmed names cleared #96+A+B+C on the Binance.US older-720. They cannot promote unless they also cleared Kraken. Control omitted. SOL holdout is reported.

| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |
| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |

## Informational BTC walk-forward fails

These names have a **positive** Kraken mean holdout and **positive** BTC holdout, but BTC walk-forward total is ≤ 0. Same honesty as #118 Donchian and #119 TSMOM. Still not an edge.

| id | Kraken mean HO | BTC HO | BTC WF |
| --- | ---: | ---: | ---: |
| `volbrk_lo_20x1_5` | +1.52% | +7.69% | -6.85% |
| `volbrk_lo_20x2` | +5.22% | +7.69% | -4.68% |
| `volsurge_lo_20x2` | +3.87% | +9.14% | -3.09% |
| `volsurge_lo_20x2_5` | +3.87% | +9.14% | -1.74% |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| `volbrk_lo_55x1_5` | volume_breakout | FAIL | FAIL | no | -1.16% | -0.40% | -5.08% | +2.75% |
| `volbrk_ls_55x1_5` | volume_breakout | FAIL | FAIL | no | -1.55% | -3.55% | -9.15% | +6.06% |
| `volbrk_lo_20x2` | volume_breakout | FAIL | FAIL | no | +5.22% | -6.49% | +7.69% | +2.75% |
| `volsurge_lo_20x2_5` | volume_surge | FAIL | FAIL | no | +3.87% | +4.57% | +9.14% | -1.41% |
| `volsurge_lo_20x2` | volume_surge | FAIL | FAIL | no | +3.87% | +3.75% | +9.14% | -1.41% |
| `volbrk_ls_20x1_5` | volume_breakout | FAIL | FAIL | no | -14.22% | -26.00% | +10.69% | -39.12% |
| `volbrk_lo_20x1_5` | volume_breakout | FAIL | FAIL | no | +1.52% | -2.05% | +7.69% | -4.65% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -2.08% | -37.11% | +2.75% | -6.92% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Kraken combined-passers (informational; control excluded from ranking): 0. A Kraken-only passer cannot promote.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH / 720 SOL; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- Multi-asset gate: `btc_eth_signs_as_96_abc_sol_reported_not_required` (SOL reported, not required).
- Volume SMA: `volume_sma_through_t_minus_1` (V=20; missing volume skipped, never invented).
- Paper path: ready on Kraken spot BTC/ETH (SOL optional; PAPER_PATH_READY=true).
- Informational positive mean HO and BTC HO with BTC walk-forward ≤ 0: `volbrk_lo_20x1_5`, `volbrk_lo_20x2`, `volsurge_lo_20x2`, `volsurge_lo_20x2_5`. Same honesty as #118 Donchian / #119 TSMOM — still not an edge.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not re-run #104 or #108 EMA dual-prints. Do not re-run the #116 residual, #117 cross-sectional, #118 Donchian, #119 TSMOM, #120 Bollinger, #121 calendar, or #122 lead-lag catalogs on the same windows. Do not invent PIT basis for carry.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not re-run dead EMA dual-prints (#104 / #108), the #116 residual catalog, the #117 cross-sectional catalog, the #118 Donchian catalog, the #119 TSMOM catalog, the #120 Bollinger catalog, the #121 calendar catalog, or the #122 lead-lag catalog on the same windows. Do not invent carry basis.
