# HL-HTX funding-divergence SPOT overlay dual-print

Generated: 2026-09-18T10:37:43.794372+00:00
Print kind: **dual_print**. interval=`1d`; primary_candle=`kraken`; second_candle=`coinbase`; funding=`hyperliquid`-minus-`htx`; paper_path_ready=`true`; can_promote=`false`; `keep_flag_false=true`.
Core ids=7; dual_print_passers=`0`.
Costs: fee=80 bps + slippage=5 bps (pilot spot). No hedged-carry legs.
Aligned bars: primary=720, second=724.

## What this does / does not claim

Paper-research catalog of HL-HTX funding-divergence FeatureZ voters on spot BTC/ETH. **Not** a live-capital claim, **not** hedged carry, **not** a reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success.

## Honesty / pre-registered rules

Pre-registered HL-HTX funding-divergence SPOT overlay (frozen before any pull/score). Feature = UTC-daily HL funding sum minus HTX funding sum on the intersection of days per symbol; empty days omitted, never zero-filled. FeatureZVoter lookback=20; fade/follow at |z|>=1.0/1.5/2.0. Dual-print = Kraken x Coinbase spot BTC/ETH with the SAME divergence feature (both funding venues required). Hedged carry is excluded. Pilot fee 80+5 bps. BitMEX not used. PAPER_PROMOTE_* stays default false. Empty dual-print set is success.

## Pre-registered catalog

Frozen ids: `fund_div_hl_htx_fade_1_0`, `fund_div_hl_htx_fade_1_5`, `fund_div_hl_htx_fade_2_0`, `fund_div_hl_htx_follow_1_0`, `fund_div_hl_htx_follow_1_5`, `fund_div_hl_htx_follow_2_0`; control `ma_cross_10_30`.

## Edge / divergence notes

- `funding_div_resample:BTC/USD:hl` **ok**: resampled 19199 -> 801 UTC daily sums
- `funding_div_resample:BTC/USD:htx` **ok**: resampled 2401 -> 801 UTC daily sums
- `funding_div:BTC/USD` **ok**: HL-minus-HTX on 801 intersecting UTC days (2024-07-10 -> 2026-09-18)
- `funding_div_resample:ETH/USD:hl` **ok**: resampled 19199 -> 801 UTC daily sums
- `funding_div_resample:ETH/USD:htx` **ok**: resampled 2401 -> 801 UTC daily sums
- `funding_div:ETH/USD` **ok**: HL-minus-HTX on 801 intersecting UTC days (2024-07-10 -> 2026-09-18)
- `hyperliquid_funding:BTC/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d)
- `hyperliquid_funding:ETH/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d)
- `htx_funding:BTC/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d)
- `htx_funding:ETH/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d)

## Candle notes

- `kraken:BTC/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `kraken:ETH/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:BTC/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:ETH/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00

## Primary candle print (`kraken`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -1.70% | 3.27% | -8.65% | no | yes |
| 2 | `fund_div_hl_htx_follow_1_5` | funding_z | -6.29% | -1.32% | -27.86% | no | no |
| 3 | `fund_div_hl_htx_fade_2_0` | funding_z | -7.27% | -2.30% | -24.26% | no | no |
| 4 | `fund_div_hl_htx_follow_2_0` | funding_z | -7.75% | -2.78% | -19.35% | no | no |
| 5 | `fund_div_hl_htx_fade_1_5` | funding_z | -12.44% | -7.47% | -34.75% | no | no |
| 6 | `fund_div_hl_htx_follow_1_0` | funding_z | -12.62% | -7.65% | -48.96% | no | no |
| 7 | `fund_div_hl_htx_fade_1_0` | funding_z | -14.41% | -9.44% | -37.72% | no | no |

## Second candle print (`coinbase`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -8.22% | 5.26% | -8.68% | no | yes |
| 2 | `fund_div_hl_htx_follow_1_5` | funding_z | -15.39% | -1.90% | -27.88% | no | no |
| 3 | `fund_div_hl_htx_fade_2_0` | funding_z | -16.28% | -2.80% | -24.27% | no | no |
| 4 | `fund_div_hl_htx_follow_2_0` | funding_z | -16.34% | -2.85% | -19.39% | no | no |
| 5 | `fund_div_hl_htx_follow_1_0` | funding_z | -21.53% | -8.04% | -48.97% | no | no |
| 6 | `fund_div_hl_htx_fade_1_5` | funding_z | -21.77% | -8.29% | -34.77% | no | no |
| 7 | `fund_div_hl_htx_fade_1_0` | funding_z | -23.94% | -10.45% | -37.78% | no | no |

## Dual-print passers

**dual_print_passers=0.** Empty set is success. Leave every `PAPER_PROMOTE_*` false.

## Promotion decision

**No candidate is promoted.** print_kind=`dual_print`; can_promote=`false`; recommended_promote_flag=`none`; `keep_flag_false=true`. Do not add a Settings pin. Do not enable live.
