# Donchian / channel-breakout dual-print (BTC+ETH; SOL optional)

Catalog and print policy **frozen before any live OHLC pull**. This
file will be overwritten by `traderstack-donchian-breakout --live`
after that freeze is committed. No scores yet. No fabricated PnL.

`keep_flag_false=true`. Every `PAPER_PROMOTE_*` stays default **false**.
`TRADING_MODE` stays `paper`. Do not add a Settings pin unless the
live dual-print passer table is non-empty (and then default false).

## Pre-registered catalog (frozen; do not grow after seeing PnL)

| family | ids |
| --- | --- |
| Long-only breakout (enter long when close > prior N-day high; exit to flat when close < prior N-day low) | `donchian_lo_{20,55,100}` |
| Long/short symmetric (long above prior high, short below prior low) | `donchian_ls_{20,55,100}` |
| ATR-buffered long-only (same N; Wilder ATR 14 × 1.0 through t−1) | `donchian_lo_atr_{20,55}` |
| Control (cannot promote) | `ma_cross_10_30` |

Frozen core ids: `donchian_lo_20`, `donchian_lo_55`, `donchian_lo_100`,
`donchian_ls_20`, `donchian_ls_55`, `donchian_ls_100`,
`donchian_lo_atr_20`, `donchian_lo_atr_55`, `ma_cross_10_30`.

K=9. Exit rule frozen as `opposite_band_same_n` (not a mid-channel
exit, not a shorter Turtle exit window). Decision at bar t using the
**prior** channel (bars `[t-N, t)`; bar t's high/low never set the
breakout level). Fill at t+1 open. Missing/short series skipped, never
zero-filled.

## Dual-print bar (frozen)

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional; must combined-PASS | **no** (gate only) |

`CAN_AVERAGE_VENUES=false`. `MULTI_VENUE_BAR_PREREGISTERED=true`.
A Kraken-only combined-passer cannot promote. Control cannot enter the
passer set. Empty dual-print table is success.

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`. Equal-weight
portfolio metrics are not used.

## Live scores

**Not yet run.** This freeze commit exists so the catalog cannot be
retuned after seeing PnL.

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** Do not add a new promote flag
until a committed live report names a dual-print passer (default false
if added). Do not re-run #104 / #108 / #116 / #117 on the same windows.
Do not invent PIT basis for carry.
