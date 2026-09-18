# Vol-target overlay on ma_cross_10_30 SPOT dual-print (Kraken x Coinbase)

**Repo tip at score:** `a6a9165`.


## Operator cell note (second-era)

This run is **Coinbase era×era**, not Kraken×Coinbase venue dual-print.
Renderer title/rules text still mentions the concurrent-venue wording from
the shared `VOL_TARGET_RULES` string; the candle notes and
`primary_candle` / `second_candle` labels above are authoritative.
Recipe: `vol-target-ma-cross-second-era-dual-print-recipe.md`.
Tip at recipe freeze: `a6a9165`. Tip at score: re-pin on merge.

Generated: 2026-09-18T15:09:33.963363+00:00
Print kind: **dual_print**. primary_candle=`coinbase_era_2024_2026`; second_candle=`coinbase_era_2022_2024`; paper_path_ready=`true`; can_promote=`false`; `keep_flag_false=true`.
Core ids=4; dual_print_passers=`0`.
Costs: fee=80 bps + slippage=5 bps (pilot spot). Reduce-only vol scalar; no leverage.
Aligned bars: primary=724, second=731.

## What this does / does not claim

Paper-research vol-target size overlay on frozen `ma_cross_10_30`. **Not** a live-capital claim, **not** a reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success. Control alone cannot promote.

## Honesty / pre-registered rules

Pre-registered vol-target size overlay on frozen ma_cross_10_30 (frozen before any score). Direction: always-on SMA short=10 / long=30. Overlays size with min(target_ann / ann_realised_vol_20, 1.0) where ann_realised_vol is std of the last 20 simple close-to-close returns through the decision bar times sqrt(periods_per_year). Insufficient history -> flat (skip-not-invent, never zero-filled). Max leverage 1.0 (reduce-only). Catalog: control ma_cross_10_30 (unit +/-1, cannot promote) + ma_cross_10_30_vt15/vt25/vt50. Dual-print = Kraken x Coinbase spot BTC/ETH; venues never averaged. Pilot fee 80+5 bps. PAPER_PROMOTE_* stays default false. Empty dual-print set is success. Not a Miles EMA+GARCH reprint, not session-gap, not funding-div.

## Pre-registered catalog

Frozen ids: `ma_cross_10_30`, `ma_cross_10_30_vt15`, `ma_cross_10_30_vt25`, `ma_cross_10_30_vt50`.

Overlays: `ma_cross_10_30_vt15`, `ma_cross_10_30_vt25`, `ma_cross_10_30_vt50`.

Control (cannot promote): `ma_cross_10_30`.

## Candle notes

- `coinbase_era_2024_2026:BTC/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase_era_2024_2026:ETH/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase_era_2022_2024:BTC/USD`: 731 daily bars 2022-09-24T00:00:00+00:00 -> 2024-09-23T00:00:00+00:00
- `coinbase_era_2022_2024:ETH/USD`: 731 daily bars 2022-09-24T00:00:00+00:00 -> 2024-09-23T00:00:00+00:00

## Primary candle print (`coinbase_era_2024_2026`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -4.72% | -1.33% | -7.33% | no | yes |
| 2 | `ma_cross_10_30_vt50` | ma_cross_vol_target | -18.45% | -15.06% | -20.11% | no | no |
| 3 | `ma_cross_10_30_vt15` | ma_cross_vol_target | -19.04% | -15.64% | -33.36% | no | no |
| 4 | `ma_cross_10_30_vt25` | ma_cross_vol_target | -21.09% | -17.70% | -36.69% | no | no |

## Second candle print (`coinbase_era_2022_2024`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -10.05% | 5.61% | -43.47% | no | yes |
| 2 | `ma_cross_10_30_vt50` | ma_cross_vol_target | -14.02% | 1.65% | -54.60% | no | no |
| 3 | `ma_cross_10_30_vt15` | ma_cross_vol_target | -26.77% | -11.11% | -30.08% | no | no |
| 4 | `ma_cross_10_30_vt25` | ma_cross_vol_target | -28.10% | -12.44% | -45.67% | no | no |

## Dual-print passers

**dual_print_passers=0.** Empty dual-print set is the successful outcome. Leave every `PAPER_PROMOTE_*=false`.

## Promote

**No candidate is promoted.** print_kind=`dual_print`; can_promote=`false`; keep_flag_false=`true`.

