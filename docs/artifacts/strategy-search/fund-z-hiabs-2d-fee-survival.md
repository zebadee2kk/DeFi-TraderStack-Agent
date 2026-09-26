# fund_z high-|funding| selective ≤2d fee-survival historical REPLAY

Generated: 2026-09-26T20:36:25.399117+00:00
Recipe commit: `7bb12d4`. Print kind: **dual_era**. strategy=`fund_z_hiabs_trail1_hold`; family=`fund_z_hiabs_fee_aware_replay`; notional=$100×2; can_promote=`false`; le2d_path_exists=`true`.

## Rules

Pre-registered high-|funding| selective historical REPLAY. Enter when the trailing completed present day's combined funding_usd is >= the ladder's open_cost_usd / 2; hold the next N present days starting at i+1. fee_aware = funding - open fees; MTM omitted. Always-on tumbling windows are reference-only. PAPER_PROMOTE_* stays false; can_promote=false.

Honesty: PAPER_RESEARCH_ONLY_NOT_LIVE_PNL_NOT_PROMOTE. Selective fee survival is informational; can_promote stays false and PAPER_PROMOTE_* stays false.

## History notes

- `asilletto_daily_sum_abs_compact` **ok**: loaded daily_sum_abs_btc_eth.json; days=760

## Era `era_a` (20240101 → 20250401; days=334)

### Selective event windows (primary)

| N | ladder | threshold | n | fees | mean funding | mean fee-aware | frac fee-positive | pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | `paper_fees_usd_10bps_x2` | 0.1000 | 83 | 0.2000 | 0.1742 | -0.0258 | 28.9% | no |
| 1 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 46 | 0.3000 | 0.2088 | -0.0912 | 21.7% | no |
| 1 | `research_5plus5_x2` | 0.1000 | 83 | 0.2000 | 0.1742 | -0.0258 | 28.9% | no |
| 2 | `paper_fees_usd_10bps_x2` | 0.1000 | 83 | 0.2000 | 0.3319 | 0.1319 | 73.5% | yes |
| 2 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 46 | 0.3000 | 0.3913 | 0.0913 | 63.0% | yes |
| 2 | `research_5plus5_x2` | 0.1000 | 83 | 0.2000 | 0.3319 | 0.1319 | 73.5% | yes |
| 3 | `paper_fees_usd_10bps_x2` | 0.1000 | 83 | 0.2000 | 0.4853 | 0.2853 | 96.4% | yes |
| 3 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 46 | 0.3000 | 0.5538 | 0.2538 | 89.1% | yes |
| 3 | `research_5plus5_x2` | 0.1000 | 83 | 0.2000 | 0.4853 | 0.2853 | 96.4% | yes |

### Always-on tumbling reference

| N | ladder | threshold | n | fees | mean funding | mean fee-aware | frac fee-positive | pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | `paper_fees_usd_10bps_x2` | 0.1000 | 334 | 0.2000 | 0.0936 | -0.1064 | 7.8% | no |
| 1 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 334 | 0.3000 | 0.0936 | -0.2064 | 3.3% | no |
| 1 | `research_5plus5_x2` | 0.1000 | 334 | 0.2000 | 0.0936 | -0.1064 | 7.8% | no |
| 2 | `paper_fees_usd_10bps_x2` | 0.1000 | 167 | 0.2000 | 0.1871 | -0.0129 | 25.7% | no |
| 2 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 167 | 0.3000 | 0.1871 | -0.1129 | 13.8% | no |
| 2 | `research_5plus5_x2` | 0.1000 | 167 | 0.2000 | 0.1871 | -0.0129 | 25.7% | no |
| 3 | `paper_fees_usd_10bps_x2` | 0.1000 | 111 | 0.2000 | 0.2810 | 0.0810 | 49.5% | no |
| 3 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 111 | 0.3000 | 0.2810 | -0.0190 | 26.1% | no |
| 3 | `research_5plus5_x2` | 0.1000 | 111 | 0.2000 | 0.2810 | 0.0810 | 49.5% | no |


## Era `era_b` (20250402 → 20260601; days=426)

### Selective event windows (primary)

| N | ladder | threshold | n | fees | mean funding | mean fee-aware | frac fee-positive | pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | `paper_fees_usd_10bps_x2` | 0.1000 | 30 | 0.2000 | 0.1271 | -0.0729 | 13.3% | no |
| 1 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 18 | 0.3000 | 0.1423 | -0.1577 | 0.0% | no |
| 1 | `research_5plus5_x2` | 0.1000 | 30 | 0.2000 | 0.1271 | -0.0729 | 13.3% | no |
| 2 | `paper_fees_usd_10bps_x2` | 0.1000 | 30 | 0.2000 | 0.2368 | 0.0368 | 63.3% | yes |
| 2 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 18 | 0.3000 | 0.2534 | -0.0466 | 27.8% | no |
| 2 | `research_5plus5_x2` | 0.1000 | 30 | 0.2000 | 0.2368 | 0.0368 | 63.3% | yes |
| 3 | `paper_fees_usd_10bps_x2` | 0.1000 | 30 | 0.2000 | 0.3456 | 0.1456 | 80.0% | yes |
| 3 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 18 | 0.3000 | 0.3672 | 0.0672 | 72.2% | yes |
| 3 | `research_5plus5_x2` | 0.1000 | 30 | 0.2000 | 0.3456 | 0.1456 | 80.0% | yes |

### Always-on tumbling reference

| N | ladder | threshold | n | fees | mean funding | mean fee-aware | frac fee-positive | pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | `paper_fees_usd_10bps_x2` | 0.1000 | 426 | 0.2000 | 0.0583 | -0.1417 | 1.2% | no |
| 1 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 426 | 0.3000 | 0.0583 | -0.2417 | 0.0% | no |
| 1 | `research_5plus5_x2` | 0.1000 | 426 | 0.2000 | 0.0583 | -0.1417 | 1.2% | no |
| 2 | `paper_fees_usd_10bps_x2` | 0.1000 | 213 | 0.2000 | 0.1166 | -0.0834 | 8.5% | no |
| 2 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 213 | 0.3000 | 0.1166 | -0.1834 | 2.8% | no |
| 2 | `research_5plus5_x2` | 0.1000 | 213 | 0.2000 | 0.1166 | -0.0834 | 8.5% | no |
| 3 | `paper_fees_usd_10bps_x2` | 0.1000 | 142 | 0.2000 | 0.1749 | -0.0251 | 14.8% | no |
| 3 | `paper_fee_plus_slip_15bps_x2` | 0.1500 | 142 | 0.3000 | 0.1749 | -0.1251 | 7.7% | no |
| 3 | `research_5plus5_x2` | 0.1000 | 142 | 0.2000 | 0.1749 | -0.0251 | 14.8% | no |

## Dual-era event-mode fee-survival passers

`N=2/paper_fees_usd_10bps_x2`, `N=3/paper_fees_usd_10bps_x2`

## Promotion decision

**No promote.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. This historical replay is not live PnL.

