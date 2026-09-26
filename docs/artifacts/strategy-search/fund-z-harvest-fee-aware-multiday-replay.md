# fund_z_harvest_sign_hold fee-aware multi-day historical REPLAY

Generated: 2026-09-26T19:37:25.174607+00:00
Recipe commit: `3b02735`. Print kind: **dual_era**. strategy=`fund_z_harvest_sign_hold`; notional=$100×2; can_promote=`false`; keep_flag_false=`true`; mtm_omitted=`true`; dual_era_fee_survival_passers=`2`

## Rules

Pre-registered fund_z_harvest_sign_hold fee-aware multi-day historical REPLAY (frozen before score). Always-on sign-hold; open once per N-day window; funding = notional * daily_sum_abs(|hourly|); fee_aware = funding - fees (MTM omitted). Dual era on HL asilletto when HTX hourly absent. PAPER_PROMOTE_* stays false. can_promote=false.

Honesty: PAPER_RESEARCH_ONLY_NOT_LIVE_PNL_NOT_PROMOTE. fee_aware_paper_pnl_usd = funding_usd - fees_usd (MTM omitted). can_promote stays false; PAPER_PROMOTE_* Field defaults stay false.

## History notes

- `asilletto_daily_sum_abs_compact` **ok**: loaded daily_sum_abs_btc_eth.json; days=760

## Era `era_a` (20240101 → 20250401; days_with_funding=334)

### Tumbling windows (primary)

| N | ladder | n | fees_usd | mean_funding | mean_fee_aware | median_fee_aware | p10 | p90 | frac_fee_pos | survival_pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 3 | `paper_fees_usd_10bps_x2` | 111 | 0.2000 | 0.2810 | 0.0810 | -0.0000 | -0.0559 | 0.3679 | 49.5% | no |
| 3 | `paper_fee_plus_slip_15bps_x2` | 111 | 0.3000 | 0.2810 | -0.0190 | -0.1000 | -0.1559 | 0.2679 | 26.1% | no |
| 3 | `research_5plus5_x2` | 111 | 0.2000 | 0.2810 | 0.0810 | -0.0000 | -0.0559 | 0.3679 | 49.5% | no |
| 5 | `paper_fees_usd_10bps_x2` | 66 | 0.2000 | 0.4710 | 0.2710 | 0.1290 | 0.0472 | 0.6783 | 100.0% | yes |
| 5 | `paper_fee_plus_slip_15bps_x2` | 66 | 0.3000 | 0.4710 | 0.1710 | 0.0290 | -0.0528 | 0.5783 | 66.7% | yes |
| 5 | `research_5plus5_x2` | 66 | 0.2000 | 0.4710 | 0.2710 | 0.1290 | 0.0472 | 0.6783 | 100.0% | yes |
| 7 | `paper_fees_usd_10bps_x2` | 47 | 0.2000 | 0.6604 | 0.4604 | 0.2678 | 0.1482 | 1.1785 | 100.0% | yes |
| 7 | `paper_fee_plus_slip_15bps_x2` | 47 | 0.3000 | 0.6604 | 0.3604 | 0.1678 | 0.0482 | 1.0785 | 100.0% | yes |
| 7 | `research_5plus5_x2` | 47 | 0.2000 | 0.6604 | 0.4604 | 0.2678 | 0.1482 | 1.1785 | 100.0% | yes |

### Sliding windows (step=1; denser distribution)

| N | ladder | n | fees_usd | mean_fee_aware | median_fee_aware | frac_fee_pos |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 3 | `paper_fees_usd_10bps_x2` | 332 | 0.2000 | 0.0783 | 0.0009 | 50.6% |
| 5 | `paper_fees_usd_10bps_x2` | 330 | 0.2000 | 0.2609 | 0.1376 | 99.7% |
| 7 | `paper_fees_usd_10bps_x2` | 328 | 0.2000 | 0.4435 | 0.2710 | 100.0% |

## Era `era_b` (20250402 → 20260601; days_with_funding=426)

### Tumbling windows (primary)

| N | ladder | n | fees_usd | mean_funding | mean_fee_aware | median_fee_aware | p10 | p90 | frac_fee_pos | survival_pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 3 | `paper_fees_usd_10bps_x2` | 142 | 0.2000 | 0.1749 | -0.0251 | -0.0478 | -0.0889 | 0.0563 | 14.8% | no |
| 3 | `paper_fee_plus_slip_15bps_x2` | 142 | 0.3000 | 0.1749 | -0.1251 | -0.1478 | -0.1889 | -0.0437 | 7.7% | no |
| 3 | `research_5plus5_x2` | 142 | 0.2000 | 0.1749 | -0.0251 | -0.0478 | -0.0889 | 0.0563 | 14.8% | no |
| 5 | `paper_fees_usd_10bps_x2` | 85 | 0.2000 | 0.2914 | 0.0914 | 0.0570 | -0.0072 | 0.2308 | 83.5% | yes |
| 5 | `paper_fee_plus_slip_15bps_x2` | 85 | 0.3000 | 0.2914 | -0.0086 | -0.0430 | -0.1072 | 0.1308 | 28.2% | no |
| 5 | `research_5plus5_x2` | 85 | 0.2000 | 0.2914 | 0.0914 | 0.0570 | -0.0072 | 0.2308 | 83.5% | yes |
| 7 | `paper_fees_usd_10bps_x2` | 60 | 0.2000 | 0.4096 | 0.2096 | 0.1616 | 0.0755 | 0.3818 | 100.0% | yes |
| 7 | `paper_fee_plus_slip_15bps_x2` | 60 | 0.3000 | 0.4096 | 0.1096 | 0.0616 | -0.0245 | 0.2818 | 80.0% | yes |
| 7 | `research_5plus5_x2` | 60 | 0.2000 | 0.4096 | 0.2096 | 0.1616 | 0.0755 | 0.3818 | 100.0% | yes |

### Sliding windows (step=1; denser distribution)

| N | ladder | n | fees_usd | mean_fee_aware | median_fee_aware | frac_fee_pos |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 3 | `paper_fees_usd_10bps_x2` | 424 | 0.2000 | -0.0250 | -0.0458 | 16.5% |
| 5 | `paper_fees_usd_10bps_x2` | 422 | 0.2000 | 0.0920 | 0.0567 | 85.1% |
| 7 | `paper_fees_usd_10bps_x2` | 420 | 0.2000 | 0.2092 | 0.1576 | 100.0% |

## Dual-era fee-survival passers (informational)

`N=5/paper_fees_usd_10bps_x2`, `N=7/paper_fees_usd_10bps_x2`


## Days-to-breakeven (all-tape empiric; open $0.20)

Computed on the same compact HL daily_sum_abs tape (n=760 days), open_cost=$0.20, cap=14d contiguous from each start:

| Metric | Value |
|---|---:|
| mean days-to-BE | 3.89 |
| median days-to-BE | 4.00 |
| starts that BE within 14d | 756/760 |

Consistent with #183 amortization (~2.7d mean / ~3.4d median at tape mean income). Not a promote.

## Promotion decision

**No promote.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false (including `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD`). Historical fee-survival replay is not a Settings pin flip and not live PnL. No live path.

