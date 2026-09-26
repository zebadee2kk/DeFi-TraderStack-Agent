# fund_z flip-cost / >=N-day hold-gate dual-print

Generated: 2026-09-26T09:40:09.377951+00:00
Recipe commit: `eb60bcd`. Print kind: **dual_print**. funding=`hyperliquid` x `htx`; basis=`okx` x `binance_vision`; dual_basis_available=`true`; N_research=3; N_paper=5; can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`1`; structurally_fee_survivable_ge_3d=`false`; paper_path_ready=`true`

## Rules

Pre-registered fund_z flip-cost / >=N-day hold-gate dual-print (frozen before score). N in {3,5} from #183 BE table. Enter when N*|rate| >= open_cost; sticky ids keep min_hold=N. Dual HL x HTX + required dual_basis OKX x Binance Vision. Fee 5+5 bps x 2 legs. NEW ids distinct from fund_z_harvest_*. Honesty: unfiltered sign_hold_ref passer is not a new edge. PAPER_PROMOTE_* stays false. Empty set success.

Executability: paper-perp flip-cost hold-gate; conceptually via PAPER_PERP_HEDGE; this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot

Fees: 5+5 bps x 2 legs.

## Honesty

If only fund_z_flipcost_sign_hold_ref passes, that is the known sign_hold shape under a NEW id — not a new edge. Magnitude/sticky gates are filters on the same harvest family.

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

| id | WF total | holdout excess | mean hold | basis_modeled | eligible |
| --- | ---: | ---: | ---: | :---: | :---: |
| `fund_z_flipcost_be3d` | -0.35% | 0.00% | 2.8d | yes | no |
| `fund_z_flipcost_be5d` | -0.63% | -0.78% | 3.1d | yes | no |
| `fund_z_flipcost_be3d_sticky` | -0.11% | 0.00% | 4.7d | yes | no |
| `fund_z_flipcost_be5d_sticky` | -0.31% | -0.37% | 6.5d | yes | no |
| `fund_z_flipcost_sign_hold_ref` | 1.68% | 3.43% | 800.0d | yes | yes |
| `fund_z_flipcost_flat` | 0.00% | 0.00% | 0.0d | no | no |

Hard gates (sign_hold_ref): fund_z_flipcost_sign_hold_ref daily hard gates: #96=true A=true (ratio=0.9159797119820569) B=true (3/3) C=true combined=true. w1: BTC=0.020731068305472444 ETH=0.017499832514675795 pass=true; w2: BTC=0.013125121869729472 ETH=0.014631065586249381 pass=true; w3: BTC=0.014195384729895677 ETH=0.014763671289759417 pass=true

## Second print (HTX funding x Binance Vision basis)

| id | WF total | holdout excess | mean hold | basis_modeled | eligible |
| --- | ---: | ---: | ---: | :---: | :---: |
| `fund_z_flipcost_be3d` | -0.26% | -0.67% | 1.8d | yes | no |
| `fund_z_flipcost_be5d` | -0.44% | -1.86% | 2.5d | yes | no |
| `fund_z_flipcost_be3d_sticky` | -0.17% | -0.64% | 4.0d | yes | no |
| `fund_z_flipcost_be5d_sticky` | -0.28% | -1.09% | 6.2d | yes | no |
| `fund_z_flipcost_sign_hold_ref` | 1.47% | 3.13% | 800.0d | yes | yes |
| `fund_z_flipcost_flat` | 0.00% | 0.00% | 0.0d | no | no |

Hard gates (sign_hold_ref): fund_z_flipcost_sign_hold_ref daily hard gates: #96=true A=true (ratio=0.8530456226061498) B=true (3/3) C=true combined=true. w1: BTC=0.010600717521078717 ETH=0.012189358501890402 pass=true; w2: BTC=0.01652104178546865 ETH=0.014603160754143696 pass=true; w3: BTC=0.01171924223834453 ETH=0.009329906927094012 pass=true

## Dual-print passers

`fund_z_flipcost_sign_hold_ref`

## Fee-survivability (>=3d structural hold)

structurally_fee_survivable_ge_3d=**false** (magnitude/sticky passer with mean_hold_days >= 3 on both prints).

## Promotion decision

**No candidate is auto-enabled.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. No live path.
