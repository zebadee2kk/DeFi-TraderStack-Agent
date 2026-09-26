# Weekly / low-turnover trend dual-print

Generated: 2026-09-26T01:12:02.168479+00:00
Recipe commit: `dd527d1`. Print kind: **dual_print**. venues=`kraken` x `coinbase`; resample=`friday_utc_close`; second_rule=`concurrent_venue_harder_gates`; fees=80+5 bps (Kraken Pro tier 1); can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`0`; paper_path_ready=`true`

## Rules

Pre-registered weekly / low-turnover trend dual-print (Hypothesis C, frozen before score). Resample: Friday UTC close week (`friday_utc_close`) from existing 1d archives to `1w`. Catalog: long-only weekly SMA cross (4/12, 10/40), weekly Donchian breakout+midpoint exit (20, 40), weekly TSMOM sign (12, 26). WF train=40/test=10/step=10/holdout=0.2/min_trades=2. Gate B: 3x34 weekly windows, in-window train=24/test=10, min_passes=2. Gate A ratio 0.25; Gate C 2x fees. Dual-print: `concurrent_venue_harder_gates` Kraken x Coinbase. Fees pilot 80+5 bps. Not a retune of ens_trend_v2 / daily TSMOM / Donchian / xs-topk / sess-gap / vol-target / oi_mom. PAPER_PROMOTE_* stays false. Empty dual-print set is success. Spot-executable on Kraken.

Frozen catalog (K=6): `wk_trend_ma_4_12`, `wk_trend_ma_10_40`, `wk_trend_donch_20`, `wk_trend_donch_40`, `wk_trend_tsmom_12`, `wk_trend_tsmom_26`. Do not grow after seeing PnL.

## History / resample notes

- kraken: loaded 720 1d bars for BTC/USD from var/research/candles/kraken/BTC_USD_1d.json
- kraken: loaded 720 1d bars for ETH/USD from var/research/candles/kraken/ETH_USD_1d.json
- kraken: loaded 720 1d bars for SOL/USD from var/research/candles/kraken/SOL_USD_1d.json
- coinbase: loaded 724 1d bars for BTC/USD from var/research/candles/coinbase/BTC_USD_1d.json
- coinbase: loaded 724 1d bars for ETH/USD from var/research/candles/coinbase/ETH_USD_1d.json
- coinbase: loaded 724 1d bars for SOL/USD from var/research/candles/coinbase/SOL_USD_1d.json
- era: loaded 731 1d bars for BTC/USD from var/research/candles/coinbase_era_2022_2024/BTC_USD_1d.json
- era: loaded 731 1d bars for ETH/USD from var/research/candles/coinbase_era_2022_2024/ETH_USD_1d.json
- kraken: BTC/USD@1d: 720 daily -> 102 weekly (2024-10-04 -> 2026-09-11)
- kraken: ETH/USD@1d: 720 daily -> 102 weekly (2024-10-04 -> 2026-09-11)
- kraken: SOL/USD@1d: 720 daily -> 102 weekly (2024-10-04 -> 2026-09-11)
- coinbase: BTC/USD@1d: 724 daily -> 103 weekly (2024-09-27 -> 2026-09-11)
- coinbase: ETH/USD@1d: 724 daily -> 103 weekly (2024-09-27 -> 2026-09-11)
- coinbase: SOL/USD@1d: 724 daily -> 103 weekly (2024-09-27 -> 2026-09-11)

Primary weekly bars: `{'BTC/USD': 102, 'ETH/USD': 102, 'SOL/USD': 102}`
Second weekly bars: `{'BTC/USD': 103, 'ETH/USD': 103, 'SOL/USD': 103}`

## Primary print (kraken)

| id | WF | holdout | #96 | A | B | C | combined |
| --- | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| `wk_trend_ma_4_12` | 2.54% | -7.82% | no | no | no | no | no |
| `wk_trend_ma_10_40` | -6.19% | -2.17% | no | no | no | no | no |
| `wk_trend_donch_20` | 1.74% | -1.95% | no | no | no | no | no |
| `wk_trend_donch_40` | -5.85% | -2.17% | no | no | no | no | no |
| `wk_trend_tsmom_12` | 4.59% | -27.77% | no | no | no | no | no |
| `wk_trend_tsmom_26` | -3.97% | -3.13% | no | no | no | no | no |

## Second print (coinbase)

| id | WF | holdout | #96 | A | B | C | combined |
| --- | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| `wk_trend_ma_4_12` | 2.52% | -7.80% | no | no | no | no | no |
| `wk_trend_ma_10_40` | -3.95% | -2.14% | no | no | no | no | no |
| `wk_trend_donch_20` | 0.17% | -1.93% | no | no | no | no | no |
| `wk_trend_donch_40` | -6.78% | -2.14% | no | no | no | no | no |
| `wk_trend_tsmom_12` | 5.78% | -27.75% | no | no | no | no | no |
| `wk_trend_tsmom_26` | -3.22% | -3.11% | no | no | no | no | no |

## Dual-print passers

**0** dual-print passers.

## Promotion decision

**No candidate is promoted.** can_promote=false; keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. No live path. Spot-executable only if a future pin PR names a dual-print passer (default false).
