# BTC→ETH lead-lag dual-print

**Not yet run.** Catalog and dual-print bar are frozen here
**before** any live Kraken or Binance.US OHLC pull. Do not grow
this list or retune L after seeing PnL.

## Honesty / pre-registered rules

Pre-registered BTC→ETH lead-lag dual-print bar (frozen before any
Kraken or Binance.US score). Treatment: the traded asset follows
or fades the lead asset's trailing L-day close-to-close return
(decision `lead_closes_through_t`: lead_close[t] / lead_close[t−L]
− 1 on aligned pair-days). L ≥ 1, so when trading ETH the gate
does not use same-bar ETH. This is **not** same-bar residual
z-score on `r_BTC − r_ETH` (#116). Fill `next_bar_open` on the
traded asset (t+1 open — no look-ahead into the fill bar).
Unpaired BTC/ETH days are skipped, never zero-filled.

Other-leg book `flat_on_aligned_pair_days`: ETH-traded names keep
BTC **flat**; BTC-traded mirror names keep ETH **flat**. Combined
#96+A+B+C still requires both legs (standing #96). The other
leg is not `ma_cross_10_30` and not own-asset TSMOM.

Multi-asset combined bar: `btc_eth_both_legs_96_abc_other_leg_flat`.
Equal-weight portfolio metrics are not used.

A dual-print passer must combined-PASS the Kraken primary 720-bar
daily window **and** the #102 Binance.US older-720
(`older_720_ending_before_primary_first_bar`: 720 committed daily
BTC+ETH bars ending strictly before the primary Kraken first bar).
Ranking key: `mean_holdout_excess_among_dual_print_passers`.
`CAN_AVERAGE_VENUES=false`. `MULTI_VENUE_BAR_PREREGISTERED=true`.
A Kraken-only combined-passer cannot promote. The informational
control `ma_cross_10_30` cannot enter the passer set. Missing,
short, or overlapping Binance fails closed (zero dual-print
passers). Fees are paper-research 10+5 (gate C 20+10).
`PAPER_PATH_READY=true` on Kraken spot BTC/USD+ETH/USD.
`PAPER_PROMOTE_*` stays default false. No live. An empty
dual-print set is success.

## Dual-print bar (frozen before scoring)

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | public Spot daily, 720-bar cap; #96+A+B+C on BTC+ETH (other leg flat); rank among dual-print passers by Kraken mean HO | **Kraken mean HO only** |
| Binance.US older 720 | same #102 definition: 720 committed daily BTC+ETH bars ending before the primary Kraken first bar; must combined-PASS | **no** (gate only; not averaged) |

`api.binance.com` is HTTP 451 from this environment;
`api.binance.us` is labeled **Binance.US**, not Binance.com.

## Pre-registered catalog

Frozen catalog (K=13):

| family | ids |
| --- | --- |
| Follow: long ETH when BTC trailing L-day return > 0 (else flat) | `leadlag_eth_follow_lo_{1,2,3,5}` |
| Follow long/short ETH on sign of BTC L-day return | `leadlag_eth_follow_ls_{1,2,3}` |
| Fade: long ETH when BTC L-day return < 0 | `leadlag_eth_fade_lo_{1,2,3}` |
| Mirror: BTC follows lagged ETH (small set) | `leadlag_btc_follow_lo_{1,2}` |
| Control (cannot promote) | `ma_cross_10_30` |

Frozen core ids: `leadlag_eth_follow_lo_1`, `leadlag_eth_follow_lo_2`,
`leadlag_eth_follow_lo_3`, `leadlag_eth_follow_lo_5`,
`leadlag_eth_follow_ls_1`, `leadlag_eth_follow_ls_2`,
`leadlag_eth_follow_ls_3`, `leadlag_eth_fade_lo_1`,
`leadlag_eth_fade_lo_2`, `leadlag_eth_fade_lo_3`,
`leadlag_btc_follow_lo_1`, `leadlag_btc_follow_lo_2`,
`ma_cross_10_30`.

Do not grow this list or retune L after seeing PnL.

## Dual-print passers (promotion ranking)

Not yet run. Empty table until the frozen catalog is live-scored
once.

| dual rank | id | Kraken mean HO | Binance mean HO | selected | can flip flag |
| ---: | --- | ---: | ---: | :---: | :---: |
| — | — | n/a | n/a | no | no |

Keep every `PAPER_PROMOTE_*=false`. Do not add a new promote
flag until this table is non-empty, and then default **false**.
