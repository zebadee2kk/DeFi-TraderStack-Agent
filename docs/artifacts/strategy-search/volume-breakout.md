# Volume-confirmed breakout dual-print (BTC+ETH; SOL optional)

**Not yet run.** Catalog and dual-print bar are frozen in this
commit **before** any live Kraken or Binance.US OHLC pull. Do not
grow K or retune N / V / vol_mult after seeing PnL.

Frozen ranking key: `mean_holdout_excess_among_dual_print_passers`.
`CAN_AVERAGE_VENUES=false`. `PAPER_PATH_READY=true`.
`keep_flag_false=true`. Empty dual-print set is success.

## Pre-registered catalog (frozen)

| family | ids |
| --- | --- |
| Long-only volume-confirmed breakout | `volbrk_lo_20x1_5`, `volbrk_lo_55x1_5`, `volbrk_lo_20x2` |
| Long/short symmetric with the same volume gate | `volbrk_ls_20x1_5`, `volbrk_ls_55x1_5` |
| Volume surge only | `volsurge_lo_20x2`, `volsurge_lo_20x2_5` |
| Control (cannot promote) | `ma_cross_10_30` |

- Prior channel uses bars `[t-N, t)` — no look-ahead into t's high.
- Volume SMA through t−1 (`volume_sma_through_t_minus_1`); V=20.
- Long-only exit: close < prior N-day low (`opposite_band_same_n`).
- Fill at t+1 open.
- Missing volume skips that bar/name (never invented). Quote volume
  is not a substitute. A venue without usable base volume fails
  closed for volume names.
- Not a Donchian N retune (#118): every promote-eligible name
  requires a volume gate.
- `PAPER_PROMOTE_*` stays default false. No live.

Frozen core ids: `volbrk_lo_20x1_5`, `volbrk_lo_55x1_5`,
`volbrk_lo_20x2`, `volbrk_ls_20x1_5`, `volbrk_ls_55x1_5`,
`volsurge_lo_20x2`, `volsurge_lo_20x2_5`, `ma_cross_10_30`.
