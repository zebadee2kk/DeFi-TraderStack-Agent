# Time-series momentum dual-print (catalog freeze)

Catalog and print policy are **frozen in this commit before any live
Kraken or Binance.US OHLC pull**. Do not grow the list after seeing
PnL. Live scoring happens in a later commit.

Generated: catalog freeze (pre-score).
Catalog K scored=n/a (frozen core=9;
ranking_key=`mean_holdout_excess_among_dual_print_passers`).
`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`;
`multi_venue_bar_preregistered=true`; `can_average_venues=false`;
`paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Pre-registered time-series momentum dual-print bar (frozen before any
Kraken or Binance.US score). Treatment: each asset uses **its own**
trailing N-day close-to-close return (decision `closes_through_t`:
close[t] / close[t−N] − 1). Long-only is long when that return is > 0
and flat otherwise. Long/short is long when the return is > 0 and
short when it is < 0 (flat on an exact zero). N in {21, 63, 126, 252}.
Vol-scaled sign variants omitted (`sign(return/vol)` equals
`sign(return)` whenever vol > 0; a `return/vol` size overlay is
GARCH-class sizing and is out of scope). This is **not**
cross-sectional top-1 (#117) and **not** Donchian / channel breakout
(#118). Decision at bar t; fill `next_bar_open` (t+1 open — no
look-ahead into the fill bar). Each asset uses its own closes; a
missing/short series is skipped, never zero-filled. Multi-asset
combined bar: `btc_eth_signs_as_96_abc_sol_reported_not_required` —
#96 balanced-holdout and A magnitude and B multi-window and C 2× fees
on BTC and ETH; SOL is reported when present and is not a gate.
Equal-weight portfolio metrics are not used. A dual-print passer must
combined-PASS the Kraken primary 720-bar daily window AND the #102
Binance.US older-720 (`older_720_ending_before_primary_first_bar`:
720 committed daily BTC+ETH bars ending strictly before the primary
Kraken first bar). Ranking key:
`mean_holdout_excess_among_dual_print_passers` — Kraken BTC+ETH mean
holdout excess among dual-print passers (tie-break: candidate_id).
Binance holdout is a gate only; `CAN_AVERAGE_VENUES=false`.
`MULTI_VENUE_BAR_PREREGISTERED=true`. A Kraken-only combined-passer
cannot promote. The informational control `ma_cross_10_30` cannot
enter the passer set. Missing, short, or overlapping Binance fails
closed (zero dual-print passers). Fees are paper-research 10+5 (gate
C 20+10). Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL
optional) (`PAPER_PATH_READY=true`). `PAPER_PROMOTE_*` stays default
false. No live. An empty dual-print set is success.

## Dual-print bar (frozen before scoring)

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking (`mean_holdout_excess_among_combined_passers`) | informational | no |

## Multi-asset gate (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: require BTC and
ETH walk-forward total > 0 and holdout excess > 0, plus A/B/C,
exactly as #96+#104. SOL walk-forward and holdout are printed when
the series exists and **do not** gate. Equal-weight portfolio
metrics were considered and **rejected** before scoring.

## Treatment (frozen)

On each asset at bar t, the signal is that asset's trailing N-day
close-to-close return (`closes_through_t`: close[t] / close[t−N] − 1).
Long-only is long when the return is > 0 and flat otherwise.
Long/short is long when the return is > 0 and short when it is < 0.
The shared backtest fills at `next_bar_open` (bar t+1 open), so the
decision never looks ahead into the fill bar. A missing series is
skipped, never zero-filled.

## Pre-registered catalog

Frozen catalog (K=9): long-only time-series momentum
(`tsmom_lo_{21,63,126,252}`), long/short symmetric
(`tsmom_ls_{21,63,126,252}`), plus informational control
`ma_cross_10_30` (cannot promote). Vol-scaled sign variants omitted
(`sign(return/vol)` equals `sign(return)` whenever vol > 0; a
`return/vol` size overlay is GARCH-class sizing and is out of scope).
Do not grow this list after seeing PnL.

Frozen core ids: `tsmom_lo_21`, `tsmom_lo_63`, `tsmom_lo_126`,
`tsmom_lo_252`, `tsmom_ls_21`, `tsmom_ls_63`, `tsmom_ls_126`,
`tsmom_ls_252`, `ma_cross_10_30`.

## Paper path

This family is paper-executable on Kraken spot. Signals are
candle-only long/short/flat on BTC/USD and ETH/USD (SOL/USD when
present); `paper_simulate_fills` already books Side.BUY / Side.SELL.
No perp, no funding, no hedge book, no invented basis. A Settings pin
is still added only if a committed dual-print passer exists, and then
default false.

## Live print

**Not yet run.** This freeze commit exists so the catalog and bar
cannot change after seeing PnL. The later `--live` commit overwrites
this file with scored tables. Empty dual-print is success.
`PAPER_PROMOTE_*` stays false. Do not add a new promote flag unless
the dual-print passer table is non-empty (and then default **false**).

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** Do not enable live. Do not
fabricate PnL. Do not re-run #104 / #108 EMA dual-prints, the #116
residual catalog, the #117 cross-sectional catalog, or the #118
Donchian catalog on the same windows. Do not invent PIT basis.

`keep_flag_false=true`.
