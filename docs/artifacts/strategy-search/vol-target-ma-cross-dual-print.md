# Vol-target overlay on ma_cross_10_30 SPOT dual-print (Kraken x Coinbase)

**Repo tip at score:** `8b616bc`.

Generated: 2026-09-18T14:40:51.960457+00:00
Print kind: **dual_print**. primary_candle=`kraken`; second_candle=`coinbase`; paper_path_ready=`true`; can_promote=`false`; `keep_flag_false=true`.
Core ids=4; dual_print_passers=`0`.
Costs: fee=80 bps + slippage=5 bps (pilot spot). Reduce-only vol scalar; no leverage.
Aligned bars: primary=720, second=724.

## What this does / does not claim

Paper-research vol-target size overlay on frozen `ma_cross_10_30`. **Not** a live-capital claim, **not** a reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success. Control alone cannot promote.

## Honesty / pre-registered rules

Pre-registered vol-target size overlay on frozen ma_cross_10_30 (frozen before any score). Direction: always-on SMA short=10 / long=30. Overlays size with min(target_ann / ann_realised_vol_20, 1.0) where ann_realised_vol is std of the last 20 simple close-to-close returns through the decision bar times sqrt(periods_per_year). Insufficient history -> flat (skip-not-invent, never zero-filled). Max leverage 1.0 (reduce-only). Catalog: control ma_cross_10_30 (unit +/-1, cannot promote) + ma_cross_10_30_vt15/vt25/vt50. Dual-print = Kraken x Coinbase spot BTC/ETH; venues never averaged. Pilot fee 80+5 bps. PAPER_PROMOTE_* stays default false. Empty dual-print set is success. Not a Miles EMA+GARCH reprint, not session-gap, not funding-div.

## Pre-registered catalog

Frozen ids: `ma_cross_10_30`, `ma_cross_10_30_vt15`, `ma_cross_10_30_vt25`, `ma_cross_10_30_vt50`.

Overlays: `ma_cross_10_30_vt15`, `ma_cross_10_30_vt25`, `ma_cross_10_30_vt50`.

Control (cannot promote): `ma_cross_10_30`.

## Candle notes

- `kraken:BTC/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `kraken:ETH/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:BTC/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:ETH/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00

## Primary candle print (`kraken`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -3.96% | -2.70% | -7.32% | no | yes |
| 2 | `ma_cross_10_30_vt15` | ma_cross_vol_target | -17.12% | -15.86% | -33.39% | no | no |
| 3 | `ma_cross_10_30_vt50` | ma_cross_vol_target | -17.26% | -16.00% | -20.12% | no | no |
| 4 | `ma_cross_10_30_vt25` | ma_cross_vol_target | -19.94% | -18.68% | -36.74% | no | no |

## Second candle print (`coinbase`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -4.72% | -1.33% | -7.33% | no | yes |
| 2 | `ma_cross_10_30_vt50` | ma_cross_vol_target | -18.45% | -15.06% | -20.11% | no | no |
| 3 | `ma_cross_10_30_vt15` | ma_cross_vol_target | -19.04% | -15.64% | -33.36% | no | no |
| 4 | `ma_cross_10_30_vt25` | ma_cross_vol_target | -21.09% | -17.70% | -36.69% | no | no |

## Dual-print passers

**dual_print_passers=0.** Empty dual-print set is the successful outcome. Leave every `PAPER_PROMOTE_*=false`.

## Promote

**No candidate is promoted.** print_kind=`dual_print`; can_promote=`false`; keep_flag_false=`true`.

