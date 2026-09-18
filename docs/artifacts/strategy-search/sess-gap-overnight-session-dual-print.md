# Overnight vs session gap SPOT dual-print (Kraken x Coinbase)

**Repo tip at score:** `cc5f90a`.

Generated: 2026-09-18T14:08:35.949863+00:00
Print kind: **dual_print**. interval=`1d`; primary_candle=`kraken`; second_candle=`coinbase`; paper_path_ready=`true`; can_promote=`false`; `keep_flag_false=true`.
Core ids=13; dual_print_passers=`0`.
Costs: fee=80 bps + slippage=5 bps (pilot spot). No hedged-carry legs.
Aligned bars: primary=720, second=724.

## What this does / does not claim

Paper-research catalog of overnight-gap and session-return FeatureZ voters on spot BTC/ETH from daily OHLC. **Not** a live-capital claim, **not** a reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success.

## Honesty / pre-registered rules

Pre-registered overnight vs session open-close gap SPOT overlay (frozen before any score). Features from daily OHLC only: (1) overnight_gap[t] = open[t]/close[t-1]-1; (2) session_ret[t] = close[t]/open[t]-1. A missing/non-positive prior close or open is skipped, never zero-filled. FeatureZVoter lookback=20; fade/follow at |z|>=1.0/1.5/2.0 for each feature. Dual-print = Kraken x Coinbase spot BTC/ETH; each venue uses its OWN OHLC-derived features (venues never averaged). Pilot fee 80+5 bps. BitMEX not used. PAPER_PROMOTE_* stays default false. Empty dual-print set is success. Not a calendar reprint, not funding-div, not xs-topk.

## Pre-registered catalog

Frozen ids: `sess_gap_on_fade_1_0`, `sess_gap_on_fade_1_5`, `sess_gap_on_fade_2_0`, `sess_gap_on_follow_1_0`, `sess_gap_on_follow_1_5`, `sess_gap_on_follow_2_0`, `sess_gap_sess_fade_1_0`, `sess_gap_sess_fade_1_5`, `sess_gap_sess_fade_2_0`, `sess_gap_sess_follow_1_0`, `sess_gap_sess_follow_1_5`, `sess_gap_sess_follow_2_0`; control `ma_cross_10_30`.

## Edge / feature notes

- `sess_gap_overnight:BTC/USD` **ok**: 719 overnight gaps 2024-09-29 -> 2026-09-17
- `sess_gap_session:BTC/USD` **ok**: 720 session returns 2024-09-28 -> 2026-09-17
- `sess_gap_overnight:ETH/USD` **ok**: 719 overnight gaps 2024-09-29 -> 2026-09-17
- `sess_gap_session:ETH/USD` **ok**: 720 session returns 2024-09-28 -> 2026-09-17
- `sess_gap_overnight:BTC/USD` **ok**: 723 overnight gaps 2024-09-25 -> 2026-09-17
- `sess_gap_session:BTC/USD` **ok**: 724 session returns 2024-09-24 -> 2026-09-17
- `sess_gap_overnight:ETH/USD` **ok**: 723 overnight gaps 2024-09-25 -> 2026-09-17
- `sess_gap_session:ETH/USD` **ok**: 724 session returns 2024-09-24 -> 2026-09-17

## Candle notes

- `kraken:BTC/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `kraken:ETH/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:BTC/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:ETH/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00

## Primary candle print (`kraken`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -1.70% | 3.27% | -8.65% | no | yes |
| 2 | `sess_gap_sess_follow_2_0` | funding_z | -5.88% | -0.91% | -9.62% | no | no |
| 3 | `sess_gap_on_follow_2_0` | funding_z | -7.36% | -2.39% | -30.16% | no | no |
| 4 | `sess_gap_sess_fade_2_0` | funding_z | -7.71% | -2.74% | -32.78% | no | no |
| 5 | `sess_gap_sess_follow_1_5` | funding_z | -8.12% | -3.15% | -15.47% | no | no |
| 6 | `sess_gap_on_follow_1_5` | funding_z | -9.05% | -4.08% | -38.75% | no | no |
| 7 | `sess_gap_sess_fade_1_5` | funding_z | -10.12% | -5.15% | -40.96% | no | no |
| 8 | `sess_gap_on_fade_2_0` | funding_z | -10.38% | -5.41% | -20.54% | no | no |
| 9 | `sess_gap_on_fade_1_5` | funding_z | -11.60% | -6.63% | -24.38% | no | no |
| 10 | `sess_gap_on_follow_1_0` | funding_z | -11.86% | -6.89% | -48.05% | no | no |
| 11 | `sess_gap_sess_follow_1_0` | funding_z | -11.89% | -6.92% | -36.78% | no | no |
| 12 | `sess_gap_on_fade_1_0` | funding_z | -12.80% | -7.83% | -32.12% | no | no |
| 13 | `sess_gap_sess_fade_1_0` | funding_z | -16.70% | -11.73% | -51.33% | no | no |

## Second candle print (`coinbase`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -8.22% | 5.26% | -8.68% | no | yes |
| 2 | `sess_gap_sess_follow_2_0` | funding_z | -14.55% | -1.06% | -9.67% | no | no |
| 3 | `sess_gap_on_fade_2_0` | funding_z | -15.73% | -2.24% | -18.16% | no | no |
| 4 | `sess_gap_sess_fade_2_0` | funding_z | -16.63% | -3.14% | -32.77% | no | no |
| 5 | `sess_gap_sess_follow_1_5` | funding_z | -17.07% | -3.59% | -16.56% | no | no |
| 6 | `sess_gap_on_follow_2_0` | funding_z | -17.40% | -3.92% | -33.56% | no | no |
| 7 | `sess_gap_on_follow_1_5` | funding_z | -17.64% | -4.16% | -35.76% | no | no |
| 8 | `sess_gap_sess_fade_1_5` | funding_z | -18.18% | -4.69% | -41.42% | no | no |
| 9 | `sess_gap_on_fade_1_5` | funding_z | -18.75% | -5.26% | -21.39% | no | no |
| 10 | `sess_gap_on_follow_1_0` | funding_z | -19.65% | -6.16% | -38.50% | no | no |
| 11 | `sess_gap_sess_follow_1_0` | funding_z | -20.05% | -6.56% | -38.69% | no | no |
| 12 | `sess_gap_on_fade_1_0` | funding_z | -20.53% | -7.04% | -34.53% | no | no |
| 13 | `sess_gap_sess_fade_1_0` | funding_z | -23.19% | -9.70% | -50.95% | no | no |

## Dual-print passers

**dual_print_passers=0.** Empty set is success. Leave every `PAPER_PROMOTE_*` false.

## Operator recommendation

**No candidate is promoted.** print_kind=`dual_print`; can_promote=`false`; recommended_promote_flag=`none`; `keep_flag_false=true`. Do not add a Settings pin. Do not enable live.
