# Calendar seasonality dual-print (BTC+ETH; SOL optional)

**Not yet run.** Catalog and dual-print bar frozen before any Kraken
or Binance.US OHLC pull. Do not retune weekday / month / N,M sets
after seeing PnL.

Timezone: **UTC**. Decision uses the UTC civil date of bar t
(`utc_calendar_date_of_bar_t`). Fill at t+1 open. Positions ignore
OHLC — this is not a price-indicator retune of #116–#120.

`multi_asset_gate_rule=btc_eth_signs_as_96_abc_sol_reported_not_required`;
`multi_venue_bar_preregistered=true`; `can_average_venues=false`;
`paper_path_ready=true`; `keep_flag_false=true`.

## Dual-print bar (frozen before scoring)

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (SOL reported); rank among dual-print passers by `mean_holdout_excess_among_dual_print_passers` | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; SOL optional report-only; must combined-PASS | **no** (gate only; not averaged) |
| Kraken-only combined ranking | informational | no |

Missing, short, or overlapping Binance fails closed (zero dual-print
passers — success). `api.binance.com` is labeled Binance.US when the
fallback `api.binance.us` is used. Never zero-fill. Costs 10+5 bps;
gate C 20+10.

## Pre-registered catalog

Frozen catalog (K=9). Do not grow this list after seeing PnL.

| family | ids | frozen set |
| --- | --- | --- |
| Day-of-week long-only | `cal_dow_lo_mon` | Monday UTC (weekday=0) |
| Day-of-week long-only | `cal_dow_lo_fri` | Friday UTC (weekday=4) |
| Day-of-week long-only | `cal_dow_lo_mon_fri` | Monday+Friday UTC |
| Skip-weekend | `cal_dow_skip_weekend` | long Mon–Fri UTC; flat Sat/Sun UTC |
| Month-of-year long-only | `cal_moy_lo_q4` | October–December UTC |
| Month-of-year long-only | `cal_moy_lo_jan` | January UTC |
| Month-of-year long-only | `cal_moy_lo_nov_dec` | November–December UTC |
| Turn-of-month | `cal_tom_lo_3_3` | last 3 / first 3 UTC calendar days of the month (`calendar.monthrange`; no look-ahead) |
| Control (cannot promote) | `ma_cross_10_30` | informational MA 10/30 |

Frozen core ids: `cal_dow_lo_mon`, `cal_dow_lo_fri`,
`cal_dow_lo_mon_fri`, `cal_dow_skip_weekend`, `cal_moy_lo_q4`,
`cal_moy_lo_jan`, `cal_moy_lo_nov_dec`, `cal_tom_lo_3_3`,
`ma_cross_10_30`.

Turn-of-month uses the civil calendar (known in advance), not “last
3 bars present in the series”. A missing bar is skipped, never
zero-filled, and does not reassign last-N onto earlier dates.

## Honesty

`PAPER_PROMOTE_*` stays default **false**. No new Settings pin unless
a committed dual-print passer exists, and then default false. Empty
dual-print table is success. Do not enable live. Do not fabricate
PnL. Do not re-run #104 / #108 / #116 / #117 / #118 / #119 / #120
on the same windows. Do not invent PIT basis.

## Dual-print passers

Not yet run.
