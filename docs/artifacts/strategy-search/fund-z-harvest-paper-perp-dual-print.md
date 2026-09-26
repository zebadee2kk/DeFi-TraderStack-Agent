# Paper-perp funding-z threshold harvest dual-print

Generated: 2026-09-26T00:29:17.308299+00:00
Print kind: **dual_print**. funding=`hyperliquid` x `htx`; basis=`okx` x `binance_vision`; dual_basis_available=`true`; can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`1`; paper_path_ready=`true`

## Rules

Pre-registered paper-perp funding-z harvest (frozen before score). Distinct ids from carry_hedged_*. Dual-print HL x HTX funding with required dual_basis OKX x Binance Vision. Fee 5+5 bps x 2 legs. Skip if basis missing. PAPER_PROMOTE_* stays false. Empty set success.

Executability: paper-perp executable via PAPER_PERP_HEDGE path conceptually; this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot

Fees: 5+5 bps x 2 legs.

## History notes

- `hyperliquid_funding:BTC/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d)
- `hl_funding_daily:BTC/USD` **ok**: resampled 19199 -> 801 UTC daily sums
- `hyperliquid_funding:ETH/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d)
- `hl_funding_daily:ETH/USD` **ok**: resampled 19199 -> 801 UTC daily sums
- `htx_funding:BTC/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d)
- `htx_funding_daily:BTC/USD` **ok**: resampled 2401 -> 801 UTC daily sums
- `htx_funding:ETH/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d)
- `htx_funding_daily:ETH/USD` **ok**: resampled 2401 -> 801 UTC daily sums
- `okx_basis:BTC/USD` **ok**: loaded 2460 daily mark−index rows from var/research/basis/okx/BTCUSD_basis_1d.json (2020-01-01 → 2026-09-25; clamped to the scored window; missing days stay missing)
- `okx_basis:ETH/USD` **ok**: loaded 2460 daily mark−index rows from var/research/basis/okx/ETHUSD_basis_1d.json (2020-01-01 → 2026-09-25; clamped to the scored window; missing days stay missing)
- `binance_vision_basis:BTC/USD` **ok**: loaded 2441 daily mark−index rows from var/research/basis/binance_vision/BTCUSD_basis_1d.json (2020-01-01 → 2026-09-24; clamped to the scored window; missing days stay missing)
- `binance_vision_basis:ETH/USD` **ok**: loaded 2455 daily mark−index rows from var/research/basis/binance_vision/ETHUSD_basis_1d.json (2020-01-01 → 2026-09-24; clamped to the scored window; missing days stay missing)

## Primary print (HL funding x OKX basis)

| id | WF total | holdout excess | basis_modeled | eligible |
| --- | ---: | ---: | :---: | :---: |
| `fund_z_harvest_z_1_0` | -2.91% | -8.68% | yes | no |
| `fund_z_harvest_z_1_5` | -1.88% | -6.22% | yes | no |
| `fund_z_harvest_z_2_0` | -1.12% | -3.70% | yes | no |
| `fund_z_harvest_abs_2bp` | -1.85% | -5.25% | yes | no |
| `fund_z_harvest_sign_hold` | 1.68% | 3.42% | yes | yes |

Hard gates (sign_hold): fund_z_harvest_sign_hold daily hard gates: #96=true A=true (ratio=0.916712366988035) B=true (3/3) C=true combined=true. w1: BTC=0.020731068305472444 ETH=0.017499832514675795 pass=true; w2: BTC=0.013125121869729472 ETH=0.014631065586249381 pass=true; w3: BTC=0.014116275933117484 ETH=0.014649524645069745 pass=true

## Second print (HTX funding x Binance Vision basis)

| id | WF total | holdout excess | basis_modeled | eligible |
| --- | ---: | ---: | :---: | :---: |
| `fund_z_harvest_z_1_0` | -2.91% | -9.21% | yes | no |
| `fund_z_harvest_z_1_5` | -1.99% | -5.09% | yes | no |
| `fund_z_harvest_z_2_0` | -1.50% | -2.07% | yes | no |
| `fund_z_harvest_abs_2bp` | -1.71% | -9.40% | yes | no |
| `fund_z_harvest_sign_hold` | 1.47% | 3.12% | yes | yes |

Hard gates (sign_hold): fund_z_harvest_sign_hold daily hard gates: #96=true A=true (ratio=0.8506872688288076) B=true (3/3) C=true combined=true. w1: BTC=0.010600717521078717 ETH=0.012189358501890402 pass=true; w2: BTC=0.01652104178546865 ETH=0.014603160754143696 pass=true; w3: BTC=0.01169243468919623 ETH=0.009228987752250895 pass=true

## Dual-print passers

`fund_z_harvest_sign_hold`

## Promotion decision

**No candidate is promoted.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. No live path.
