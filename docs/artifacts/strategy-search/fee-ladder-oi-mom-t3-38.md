# HL/Bybit open-interest momentum SPOT overlay dual-print

Generated: 2026-09-18T16:15:14.067152+00:00
Print kind: **dual_print**. interval=`1d`; primary_candle=`kraken`; second_candle=`coinbase`; feature_oi=`bybit`; gate_oi=`hyperliquid_asilletto`; dual_oi_available=`true`; paper_path_ready=`true`; can_promote=`false`; `keep_flag_false=true`.
Core ids=7; dual_print_passers=`0`.
Costs: fee=38 bps + slippage=5 bps (pilot spot). OI is a filter only - no perp leg.
Aligned bars: primary=720, second=724.

## What this does / does not claim

Paper-research catalog of OI-momentum FeatureZ voters on spot BTC/ETH. **Not** a live-capital claim. **Not** a reason to flip `PAPER_PROMOTE_*`. Empty dual-print set is success.

## Probe notes

- Hyperliquid asiletto81/hyperliquid asset_ctxs: AVAILABLE >=720d BTC+ETH.
- Bybit linear daily open interest: AVAILABLE >=720d BTC+ETH.
- HTX / Binance / OKX daily OI history: UNAVAILABLE at >=720d.
- Live candle feature tape: Bybit. HL archive ends 2026-06-01; live Kraken720 overlap is below 720 so HL is gate-only for this score.

## Honesty / pre-registered rules

Pre-registered HL/Bybit open-interest momentum SPOT overlay frozen before any pull/score. Feature = UTC-daily oi_ret[t]=OI[t]/OI[t-N]-1 for N in {7,14,30}; FeatureZVoter lookback=20; fade/follow at |z|>=2.0 only. Dual OI gate = HL asiletto81 asset_ctxs AND Bybit linear daily OI each >=720 UTC days BTC+ETH. Dual-print = Kraken x Coinbase spot with Bybit OI as the live feature tape. HL archive ends 2026-06-01; live Kraken720 overlap below 720 so skip-not-invent. PAPER_PROMOTE_* stays default false. Empty dual-print set is success.

## Pre-registered catalog

Frozen ids: `oi_mom_fade_7`, `oi_mom_fade_14`, `oi_mom_fade_30`, `oi_mom_follow_7`, `oi_mom_follow_14`, `oi_mom_follow_30`; control `ma_cross_10_30`.

## Edge / OI gate notes

- `oi_gate:hyperliquid_asilletto:BTC/USD` **ok**: points=760 min=720 span=2024-01-01->2026-06-01
- `oi_gate:hyperliquid_asilletto:ETH/USD` **ok**: points=760 min=720 span=2024-01-01->2026-06-01
- `oi_gate:bybit:BTC/USD` **ok**: points=2236 min=720 span=2020-08-05->2026-09-18
- `oi_gate:bybit:ETH/USD` **ok**: points=2158 min=720 span=2020-10-22->2026-09-18
- `oi_gate:dual` **ok**: both HL asiletto and Bybit >=720d BTC+ETH
- `oi_source` **ok**: offline files var/ops/oi_cache/asilletto81_oi.json + var/ops/oi_cache/bybit_oi.json

## Candle notes

- `kraken:BTC/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `kraken:ETH/USD`: 720 daily bars 2024-09-28T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:BTC/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00
- `coinbase:ETH/USD`: 724 daily bars 2024-09-24T00:00:00+00:00 -> 2026-09-17T00:00:00+00:00

## Primary candle print (`kraken`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -0.11% | 4.86% | -5.21% | no | yes |
| 2 | `oi_mom_follow_30` | funding_z | -4.88% | 0.09% | -14.93% | no | no |
| 3 | `oi_mom_fade_14` | funding_z | -5.49% | -0.52% | -11.97% | no | no |
| 4 | `oi_mom_fade_7` | funding_z | -6.08% | -1.11% | -13.75% | no | no |
| 5 | `oi_mom_follow_7` | funding_z | -6.19% | -1.22% | -17.86% | no | no |
| 6 | `oi_mom_follow_14` | funding_z | -7.11% | -2.14% | -19.49% | no | no |
| 7 | `oi_mom_fade_30` | funding_z | -7.31% | -2.34% | -20.03% | no | no |

## Second candle print (`coinbase`)

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -6.66% | 6.82% | -5.24% | no | yes |
| 2 | `oi_mom_follow_30` | funding_z | -13.65% | -0.17% | -14.90% | no | no |
| 3 | `oi_mom_fade_14` | funding_z | -13.88% | -0.40% | -12.01% | no | no |
| 4 | `oi_mom_follow_7` | funding_z | -14.14% | -0.65% | -17.86% | no | no |
| 5 | `oi_mom_fade_7` | funding_z | -14.56% | -1.08% | -13.79% | no | no |
| 6 | `oi_mom_follow_14` | funding_z | -15.76% | -2.27% | -19.49% | no | no |
| 7 | `oi_mom_fade_30` | funding_z | -15.85% | -2.37% | -20.10% | no | no |

## Dual-print passers

**dual_print_passers=0.** Empty set is success. Leave every `PAPER_PROMOTE_*` false.

## Promotion decision

**No candidate is promoted.** print_kind=`dual_print`; dual_oi_available=`true`; can_promote=`false`; recommended_promote_flag=`none`; `keep_flag_false=true`. Do not add a Settings pin. Do not enable live.
