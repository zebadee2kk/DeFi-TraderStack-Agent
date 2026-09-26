# Hedged-carry + dual-basis fee-aware multi-day historical REPLAY

Generated: 2026-09-26T19:48:56.569476+00:00
Recipe commit: `513f8e9`. Print kind: **dual_basis**. strategy=`carry_hedged_sign_basis_dual`; notional=$100×2; can_promote=`false`; keep_flag_false=`true`; mtm_omitted=`true`; dual_basis_fee_survival_passers=`2`

## Rules

Pre-registered hedged-carry + dual-basis fee-aware multi-day REPLAY (frozen before score). Always-on sign-hold; open once per N-day window; income = HL daily_sum_abs funding + basis Δ (prev−curr); fee_aware = funding + basis − fees (MTM omitted). Dual print OKX x Binance Vision. HTX hourly skip-not-invent. PAPER_PROMOTE_* stays false. can_promote=false.

Honesty: PAPER_RESEARCH_ONLY_NOT_LIVE_PNL_NOT_PROMOTE. fee_aware = funding_usd + basis_usd - fees_usd (MTM omitted). can_promote stays false; PAPER_PROMOTE_* Field defaults stay false.

## History notes

- `asilletto_daily_sum_abs_compact` **ok**: loaded daily_sum_abs_btc_eth.json; days=760
- `basis_file:okx:BTC` **ok**: loaded 2460 daily rows from BTCUSD_basis_1d.json
- `basis_file:okx:ETH` **ok**: loaded 2460 daily rows from ETHUSD_basis_1d.json
- `basis_panel:okx` **ok**: days_with_btc_eth=2460
- `basis_file:binance_vision:BTC` **ok**: loaded 2441 daily rows from BTCUSD_basis_1d.json
- `basis_file:binance_vision:ETH` **ok**: loaded 2455 daily rows from ETHUSD_basis_1d.json
- `basis_panel:binance_vision` **ok**: days_with_btc_eth=2441
- `htx_hourly_funding` **skipped**: no HTX hourly funding tape on disk; dual-print uses OKX x Vision basis

## Print `hl_okx` (basis=`okx`; funding_days=760; basis_days=883)

### Tumbling windows (primary)

| N | ladder | n | fees_usd | mean_funding | mean_basis | mean_fee_aware | median_fee_aware | frac_fee_pos | survival_pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 3 | `paper_fees_usd_10bps_x2` | 253 | 0.2000 | 0.2214 | -0.0002 | 0.0212 | -0.0266 | 34.0% | no |
| 3 | `paper_fee_plus_slip_15bps_x2` | 253 | 0.3000 | 0.2214 | -0.0002 | -0.0788 | -0.1266 | 15.4% | no |
| 3 | `research_5plus5_x2` | 253 | 0.2000 | 0.2214 | -0.0002 | 0.0212 | -0.0266 | 34.0% | no |
| 5 | `paper_fees_usd_10bps_x2` | 152 | 0.2000 | 0.3689 | -0.0003 | 0.1687 | 0.0881 | 89.5% | yes |
| 5 | `paper_fee_plus_slip_15bps_x2` | 152 | 0.3000 | 0.3689 | -0.0003 | 0.0687 | -0.0119 | 44.7% | no |
| 5 | `research_5plus5_x2` | 152 | 0.2000 | 0.3689 | -0.0003 | 0.1687 | 0.0881 | 89.5% | yes |
| 7 | `paper_fees_usd_10bps_x2` | 108 | 0.2000 | 0.5176 | -0.0008 | 0.3167 | 0.1922 | 100.0% | yes |
| 7 | `paper_fee_plus_slip_15bps_x2` | 108 | 0.3000 | 0.5176 | -0.0008 | 0.2167 | 0.0922 | 85.2% | yes |
| 7 | `research_5plus5_x2` | 108 | 0.2000 | 0.5176 | -0.0008 | 0.3167 | 0.1922 | 100.0% | yes |

### Sliding windows (primary ladder only)

| N | n | mean_fee_aware | median_fee_aware | frac_fee_pos |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 758 | 0.0205 | -0.0280 | 34.2% |
| 5 | 756 | 0.1661 | 0.0844 | 88.9% |
| 7 | 754 | 0.3114 | 0.2038 | 99.9% |

## Print `hl_vision` (basis=`binance_vision`; funding_days=760; basis_days=883)

### Tumbling windows (primary)

| N | ladder | n | fees_usd | mean_funding | mean_basis | mean_fee_aware | median_fee_aware | frac_fee_pos | survival_pass |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 3 | `paper_fees_usd_10bps_x2` | 253 | 0.2000 | 0.2214 | 0.0026 | 0.0241 | -0.0273 | 34.0% | no |
| 3 | `paper_fee_plus_slip_15bps_x2` | 253 | 0.3000 | 0.2214 | 0.0026 | -0.0759 | -0.1273 | 17.0% | no |
| 3 | `research_5plus5_x2` | 253 | 0.2000 | 0.2214 | 0.0026 | 0.0241 | -0.0273 | 34.0% | no |
| 5 | `paper_fees_usd_10bps_x2` | 152 | 0.2000 | 0.3689 | 0.0034 | 0.1724 | 0.0934 | 88.2% | yes |
| 5 | `paper_fee_plus_slip_15bps_x2` | 152 | 0.3000 | 0.3689 | 0.0034 | 0.0724 | -0.0066 | 48.7% | no |
| 5 | `research_5plus5_x2` | 152 | 0.2000 | 0.3689 | 0.0034 | 0.1724 | 0.0934 | 88.2% | yes |
| 7 | `paper_fees_usd_10bps_x2` | 108 | 0.2000 | 0.5176 | -0.0013 | 0.3163 | 0.1894 | 100.0% | yes |
| 7 | `paper_fee_plus_slip_15bps_x2` | 108 | 0.3000 | 0.5176 | -0.0013 | 0.2163 | 0.0894 | 84.3% | yes |
| 7 | `research_5plus5_x2` | 108 | 0.2000 | 0.5176 | -0.0013 | 0.3163 | 0.1894 | 100.0% | yes |

### Sliding windows (primary ladder only)

| N | n | mean_fee_aware | median_fee_aware | frac_fee_pos |
| ---: | ---: | ---: | ---: | ---: |
| 3 | 758 | 0.0208 | -0.0276 | 34.3% |
| 5 | 756 | 0.1663 | 0.0882 | 89.3% |
| 7 | 754 | 0.3115 | 0.2035 | 99.7% |

## Dual-basis fee-survival passers (informational)

`N=5/paper_fees_usd_10bps_x2`, `N=7/paper_fees_usd_10bps_x2`

## Promotion decision

**No promote.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. Historical fee-survival replay is not a Settings pin flip and not live PnL. No live path.

