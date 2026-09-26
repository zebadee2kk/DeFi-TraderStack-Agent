# BTC-ETH relative funding / funding-spread HL x HTX dual-print

**Recipe tip (pre-score):** `505ce29` (`docs/artifacts/strategy-search/fund-spread-btc-eth-hl-htx-dual-print-recipe.md`).


Generated: 2026-09-26T02:23:59.340642+00:00
Print kind: **dual_print**. dual_mode=`concurrent_venues`; funding=`hyperliquid` x `htx`; can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`0`; paper_path_ready=`true`

## Rules

Pre-registered BTC-ETH relative funding / funding-spread dual-print (frozen before score). Concurrent HL x HTX preferred. Fees 5+5 bps x 2 legs. Distinct from fund_z_harvest / fund_div / fund_xs_rank / price RV. PAPER_PROMOTE_* stays false. Empty set success.

Executability: paper-perp BTC-ETH funding-spread; conceptually via PAPER_PERP_HEDGE; this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot

Fees: 5+5 bps x 2 legs.

## Coverage (frozen before PnL)

```
{'hl_btc_days': 801, 'hl_eth_days': 801, 'hl_aligned_days': 801, 'htx_btc_days': 801, 'htx_eth_days': 801, 'htx_aligned_days': 801, 'hl_span': ['2024-07-18T00:00:00+00:00', '2026-09-26T00:00:00+00:00'], 'htx_span': ['2024-07-18T00:00:00+00:00', '2026-09-26T00:00:00+00:00'], 'min_bars_preferred': 720, 'short_train': 80, 'short_test': 40, 'short_step': 40}
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
- `coverage_freeze` **ok**: hl_aligned=801 ok=True; htx_aligned=801 ok=True; prefer concurrent=True
- `dual_print_cells` **ok**: frozen concurrent hyperliquid x htx before PnL

## Primary (`hyperliquid`)

| id | WF total | holdout excess | flips | eligible | control |
| --- | ---: | ---: | ---: | :---: | :---: |
| `fund_spread_btc_eth_sign_hold` | -3.65% | -8.70% | 265 | no | no |
| `fund_spread_btc_eth_z_1_0` | -4.13% | -10.17% | 284 | no | no |
| `fund_spread_btc_eth_z_1_5` | -2.21% | -6.96% | 164 | no | no |
| `fund_spread_btc_eth_z_2_0` | -1.17% | -3.03% | 88 | no | no |
| `fund_spread_btc_eth_demean_sign` | -2.99% | -6.54% | 232 | no | no |
| `fund_spread_btc_eth_flat` | 0.00% | 0.00% | 0 | no | yes |

## Second (`htx`)

| id | WF total | holdout excess | flips | eligible | control |
| --- | ---: | ---: | ---: | :---: | :---: |
| `fund_spread_btc_eth_sign_hold` | -4.43% | -6.07% | 292 | no | no |
| `fund_spread_btc_eth_z_1_0` | -3.74% | -10.04% | 276 | no | no |
| `fund_spread_btc_eth_z_1_5` | -2.61% | -4.92% | 179 | no | no |
| `fund_spread_btc_eth_z_2_0` | -1.29% | -2.99% | 83 | no | no |
| `fund_spread_btc_eth_demean_sign` | -3.57% | -8.29% | 249 | no | no |
| `fund_spread_btc_eth_flat` | 0.00% | 0.00% | 0 | no | yes |

## Dual-print passers

**0** dual-print passers.

## Promotion decision

**No candidate is auto-enabled.** can_promote=false; keep_flag_false=true. Recommended pin name (defaults false if added later): `n/a`. No live path. PAPER_PROMOTE_* untouched.
