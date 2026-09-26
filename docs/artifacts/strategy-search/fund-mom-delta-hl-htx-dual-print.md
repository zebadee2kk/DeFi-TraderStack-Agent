# Funding-momentum (rate-change) HL x HTX dual-print

Generated: 2026-09-26T08:51:51.370068+00:00
Recipe freeze commit: `18e3abc` (pre-score).
Print kind: **dual_print**. dual_mode=`concurrent_venues`; funding=`hyperliquid` x `htx`; can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`0`; paper_path_ready=`true`

## Rules

Pre-registered same-asset funding-momentum / rate-change dual-print (frozen before score). Concurrent HL x HTX. Fees 5+5 bps x 2 legs. Distinct from fund_z_harvest_sign_hold, fund_spread_btc_eth #180, fund_xs_rank #179. PAPER_PROMOTE_* stays false. Empty set success.

Executability: paper-perp funding-momentum (rate-change); conceptually via PAPER_PERP_HEDGE; this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot

Fees: 5+5 bps x 2 legs.

## Coverage (frozen before PnL)

```
{'hl_btc_days': 801, 'hl_eth_days': 801, 'htx_btc_days': 801, 'htx_eth_days': 801, 'min_bars_preferred': 720}
```

## History notes

- `hyperliquid_funding:BTC/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d)
- `hl_funding_daily:BTC/USD` **ok**: resampled 19199 -> 801 UTC daily sums
- `hyperliquid_funding:ETH/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d)
- `hl_funding_daily:ETH/USD` **ok**: resampled 19199 -> 801 UTC daily sums
- `htx_funding:BTC/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d)
- `htx_funding_daily:BTC/USD` **ok**: resampled 2401 -> 801 UTC daily sums
- `htx_funding:ETH/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d)
- `htx_funding_daily:ETH/USD` **ok**: resampled 2401 -> 801 UTC daily sums
- `coverage_freeze` **ok**: hl_ok=True days=801/801; htx_ok=True days=801/801; concurrent required
- `dual_print_cells` **ok**: frozen concurrent hyperliquid x htx before PnL

## Primary (`hyperliquid`)

| id | WF total | holdout excess | flips | eligible | control |
| --- | ---: | ---: | ---: | :---: | :---: |
| `fund_mom_delta_sign` | -6.45% | -15.60% | 919 | no | no |
| `fund_mom_delta_z_1_0` | -4.12% | -12.90% | 606 | no | no |
| `fund_mom_delta_z_1_5` | -2.58% | -7.42% | 347 | no | no |
| `fund_mom_delta_z_2_0` | -1.50% | -4.07% | 194 | no | no |
| `fund_mom_confirm_sign` | -6.00% | -14.96% | 924 | no | no |
| `fund_mom_flat` | 0.00% | 0.00% | 0 | no | yes |

## Second (`htx`)

| id | WF total | holdout excess | flips | eligible | control |
| --- | ---: | ---: | ---: | :---: | :---: |
| `fund_mom_delta_sign` | -5.45% | -17.07% | 844 | no | no |
| `fund_mom_delta_z_1_0` | -4.44% | -11.14% | 608 | no | no |
| `fund_mom_delta_z_1_5` | -3.08% | -5.67% | 373 | no | no |
| `fund_mom_delta_z_2_0` | -1.88% | -2.17% | 189 | no | no |
| `fund_mom_confirm_sign` | -5.06% | -17.90% | 851 | no | no |
| `fund_mom_flat` | 0.00% | 0.00% | 0 | no | yes |

## Dual-print passers

**0** dual-print passers.

## Promotion decision

**No candidate is auto-enabled.** can_promote=false; keep_flag_false=true. Recommended pin name (defaults false if added later): `n/a`. No live path. PAPER_PROMOTE_* untouched.
