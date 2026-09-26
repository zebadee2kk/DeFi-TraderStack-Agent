# Basis residual / cash-and-carry residual dual-print

Generated: 2026-09-26T00:27:34.097230+00:00
Print kind: **dual_print**. primary=`okx`; second=`binance_vision`; dual_basis_available=`true`; can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`0`; paper_path_ready=`false`

## Rules

Pre-registered basis residual dual-print (frozen before score). Feature = PIT mark-index basis z (lookback=20); fade/follow at |z|>=1.0/1.5/2.0. Residual PnL: short-basis earns prev-current; long-basis earns current-prev; missing days skipped. Two-leg fees 5+5 bps. Dual-print = OKX x Binance Vision. Research-only residual; not Kraken-spot. PAPER_PROMOTE_* stays false. Empty set is success.

Executability: research-only residual PnL on PIT basis change; paper-perp related via PAPER_PERP_HEDGE for hedged carry but this catalog does not enable it; not Kraken-spot executable

Fees: 5+5 bps x 2 legs.

## History notes

- `okx_basis:BTC/USD` **ok**: loaded 2460 daily mark−index rows from var/research/basis/okx/BTCUSD_basis_1d.json (2020-01-01 → 2026-09-25; clamped to the scored window; missing days stay missing)
- `okx_basis:ETH/USD` **ok**: loaded 2460 daily mark−index rows from var/research/basis/okx/ETHUSD_basis_1d.json (2020-01-01 → 2026-09-25; clamped to the scored window; missing days stay missing)
- `binance_vision_basis:BTC/USD` **ok**: loaded 2441 daily mark−index rows from var/research/basis/binance_vision/BTCUSD_basis_1d.json (2020-01-01 → 2026-09-24; clamped to the scored window; missing days stay missing)
- `binance_vision_basis:ETH/USD` **ok**: loaded 2455 daily mark−index rows from var/research/basis/binance_vision/ETHUSD_basis_1d.json (2020-01-01 → 2026-09-24; clamped to the scored window; missing days stay missing)
- `okx_basis:BTC/USD` **ok**: 2460 daily points (need >=720)
- `okx_basis:ETH/USD` **ok**: 2460 daily points (need >=720)
- `binance_vision_basis:BTC/USD` **ok**: 2441 daily points (need >=720)
- `binance_vision_basis:ETH/USD` **ok**: 2455 daily points (need >=720)

## Primary print (OKX)

| id | WF total | holdout excess | eligible |
| --- | ---: | ---: | :---: |
| `basis_resid_mr_fade_1_0` | -4.68% | -33.54% | no |
| `basis_resid_mr_fade_1_5` | -2.44% | -19.07% | no |
| `basis_resid_mr_fade_2_0` | -0.89% | -8.96% | no |
| `basis_resid_mom_follow_1_0` | -5.95% | -35.48% | no |
| `basis_resid_mom_follow_1_5` | -3.17% | -20.45% | no |
| `basis_resid_mom_follow_2_0` | -1.25% | -9.71% | no |

## Second print (Binance Vision)

| id | WF total | holdout excess | eligible |
| --- | ---: | ---: | :---: |
| `basis_resid_mr_fade_1_0` | -4.26% | -33.21% | no |
| `basis_resid_mr_fade_1_5` | -2.50% | -19.55% | no |
| `basis_resid_mr_fade_2_0` | -1.14% | -7.82% | no |
| `basis_resid_mom_follow_1_0` | -4.95% | -35.77% | no |
| `basis_resid_mom_follow_1_5` | -2.92% | -21.57% | no |
| `basis_resid_mom_follow_2_0` | -1.35% | -9.04% | no |

## Dual-print passers

**0** dual-print passers.

## Promotion decision

**No candidate is promoted.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. No live path.
