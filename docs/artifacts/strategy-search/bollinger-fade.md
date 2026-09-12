# Bollinger band-fade / mean-reversion dual-print (BTC+ETH; SOL optional)

Generated: **Not yet run** (catalog and print policy frozen before any
live Kraken or Binance.US OHLC pull).

Catalog K scored=n/a (frozen core=8;
ranking_key=`mean_holdout_excess_among_dual_print_passers`).
`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`;
`multi_venue_bar_preregistered=true`; `can_average_venues=false`;
`paper_path_ready=true`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Catalog and dual-print bar are frozen **before** any live pull. Do not
retune period, k, exit rule, or squeeze percentile after seeing PnL.
Empty dual-print set is success. `PAPER_PROMOTE_*` stays default false.
No live. `TRADING_MODE=paper` only.

## Dual-print bar (frozen before scoring)

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar (`older_720_ending_before_primary_first_bar`); SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking | informational | no |

`CAN_AVERAGE_VENUES=false`. Missing, short, or overlapping Binance
fails closed (zero dual-print passers). Fees: research 10+5 bps;
gate C 20+10. Fill at t+1 open.

## Treatment (frozen)

Bands: SMA(period) ± k × sample stdev (ddof=1) over the same window
**through t** (`closes_through_t`). Decision at bar t; fill
`next_bar_open`. Exit `flat_when_inside_bands` (not exit-at-mid).

- Fade-to-mid: short when close > upper, long when close < lower,
  flat when close is on or between the bands.
- Long-only fade: long when close < lower, flat otherwise.
- Squeeze-breakout CONTRAST: long when prior bandwidth ≤ 20th
  percentile of the previous 120 bandwidths **and** current
  bandwidth expands **and** close > mid; flat otherwise
  (`expand_from_p20_of_prior_120_bandwidth_long_above_mid`).

Distinct from existing `mean_reversion_*` catalog ids
(`mean_reversion_20_1_5`, `mean_reversion_20_2_0`,
`mean_reversion_10_1_5`, `mean_reversion_40_2_0`, and the #108 4h
extras). Those are z-score voters (optionally RANGE-gated) on
charts-spot / 4h bars. This family uses explicit bands, no RANGE
gate, daily Kraken 720 + Binance.US older-720, plus long-only fade
and the squeeze contrast. Not a #108 reprint.

Not trend, not cross-section (#117), not Donchian (#118), not TSMOM
(#119).

## Pre-registered catalog

Frozen catalog (K=8). Do not grow this list after seeing PnL.

Frozen core ids: `bb_fade_20x2`, `bb_fade_20x2_5`, `bb_fade_40x2`,
`bb_lo_fade_20x2`, `bb_lo_fade_40x2`, `bb_squeeze_break_20`,
`bb_squeeze_break_40`, `ma_cross_10_30`.

| family | ids |
| --- | --- |
| Fade to mid | `bb_fade_20x2`, `bb_fade_20x2_5`, `bb_fade_40x2` |
| Long-only fade | `bb_lo_fade_20x2`, `bb_lo_fade_40x2` |
| Squeeze-breakout CONTRAST | `bb_squeeze_break_20`, `bb_squeeze_break_40` |
| Control (cannot promote) | `ma_cross_10_30` |

`PAPER_PROMOTE_*` stays false unless a committed dual-print report
names a paper-only pin and an operator flips it.

## Dual-print passers (promotion ranking)

Live print: **Not yet run**. Empty table until `--live` is committed.

| dual rank | id | Kraken mean HO | Binance mean HO | selected | can flip flag |
| ---: | --- | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | no | no |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** Do not add a new promote
flag until a committed live report names a dual-print passer
(default still false). Do not re-run #104 / #108 / #116 / #117 /
#118 / #119 on the same windows. Do not invent PIT basis.
`keep_flag_false=true`.
