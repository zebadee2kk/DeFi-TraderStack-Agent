# Strategy search report

Generated: 2026-09-12T13:21:53.050557+00:00
Symbols: BTC/USD:4h, ETH/USD:4h, SOL/USD:4h
Costs: fee=10 bps + slippage=5 bps (fee_bps is max(PRETRADE_FEE_BPS, PAPER_FEE_BPS); slippage_bps is PRETRADE_SLIPPAGE_BPS. Every fill pays both.)
Walk-forward: train=180 test=60 step=60 warmup=31; holdout_fraction=20%
Promotion floor: WF total > 0 (require_wf_total=True), WF excess > 0, min trades=3, holdout confirmation=on
Selection: pre_registered_top1 (K=23)

## Honesty

No candidate is rewritten to look profitable. Walk-forward ranking never sees the holdout tail. Selection is pre-registered top-1 of 23 catalog members (Bonferroni analogue: one promotion decision, not K independent promotions). A selected candidate is promoted only if fee-aware walk-forward mean total return is strictly above the floor (and excess is recorded), min trades are met, and holdout mean excess return is also strictly above the floor. No candidate cleared the bar on this data; paper promotion must stay off.

## Multiple testing

K catalog members are scored on the same research window. We do not treat every excess>0 as a discovered edge. At most the single pre-registered top-1 (by walk-forward mean excess return, min-trades filter) may be promoted, and only if it also clears the configured floors. A classical Bonferroni p-cut would be 0.05/23 ≈ 0.0022; this search has no per-fold t-test, so holdout confirmation is the out-of-sample control instead of a p-value.

## Ranked candidates (walk-forward mean excess after fees)

| rank | id | family | WF excess | WF total | WF trades | holdout excess | eligible | promoted |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `momentum_12_strict` | momentum | +0.44% | +0.45% | 19 | -13.06% | no | no |
| 2 | `momentum_6_vol` | momentum | +0.19% | +0.19% | 24 | -13.89% | no | no |
| 3 | `ma_cross_5_20` | ma_cross | +0.06% | +0.06% | 38 | -13.96% | no | no |
| 4 | `mean_reversion_20_1_5` | mean_reversion | -0.03% | -0.03% | 31 | -18.80% | no | no |
| 5 | `mean_reversion_20_1_5_vol` | mean_reversion | -0.03% | -0.03% | 31 | -18.80% | no | no |
| 6 | `mean_reversion_10_1_5` | mean_reversion | -0.04% | -0.04% | 38 | -18.82% | no | no |
| 7 | `mean_reversion_20_2_0` | mean_reversion | -0.15% | -0.15% | 23 | -18.91% | no | no |
| 8 | `mean_reversion_20_2_0_vol` | mean_reversion | -0.15% | -0.15% | 23 | -18.91% | no | no |
| 9 | `momentum_12_vol` | momentum | -0.17% | -0.17% | 41 | -18.74% | no | no |
| 10 | `ma_cross_10_30_wide` | ma_cross | -0.20% | -0.20% | 32 | -10.24% | no | no |
| 11 | `funding_z_follow` | funding_z | -0.22% | -0.22% | 31 | -21.64% | no | no |
| 12 | `oi_z_follow` | open_interest_z | -0.24% | -0.24% | 29 | -31.67% | no | no |
| 13 | `momentum_6` | momentum | -0.26% | -0.26% | 42 | -15.10% | no | no |
| 14 | `oi_z_fade` | open_interest_z | -0.28% | -0.28% | 29 | -26.30% | no | no |
| 15 | `funding_z_fade` | funding_z | -0.34% | -0.34% | 31 | -22.13% | no | no |
| 16 | `ma_always_on_10_30` | ma_cross | -0.45% | -0.45% | 64 | -8.88% | no | no |
| 17 | `ma_cross_10_30` | ma_cross | -0.53% | -0.52% | 46 | -10.83% | no | no |
| 18 | `ma_cross_10_30_vol` | ma_cross | -0.53% | -0.52% | 46 | -10.83% | no | no |
| 19 | `ma_always_on_10_30_vol` | ma_cross | -0.53% | -0.52% | 46 | -10.83% | no | no |
| 20 | `momentum_24` | momentum | -0.76% | -0.75% | 69 | -11.93% | no | no |
| 21 | `momentum_12` | momentum | -0.92% | -0.92% | 67 | -20.23% | no | no |
| — | `ma_cross_20_50` | ma_cross | n/a | n/a | 0 | n/a | no | no |
| — | `mean_reversion_40_2_0` | mean_reversion | n/a | n/a | 0 | n/a | no | no |

## History sources

- `BTC/USD` 4h source=kraken_charts_spot n=1080 — Kraken futures charts spot PI_* (research-only). Closes can differ a few bps from /0/public/OHLC. volume is zero on this path
- `ETH/USD` 4h source=kraken_charts_spot n=1080 — Kraken futures charts spot PI_* (research-only). Closes can differ a few bps from /0/public/OHLC. volume is zero on this path
- `SOL/USD` 4h source=kraken_charts_spot n=1080 — Kraken futures charts spot PI_* (research-only). Closes can differ a few bps from /0/public/OHLC. volume is zero on this path

## Edge series

- `binance_funding:BTC/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_oi:BTC/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_liquidation:BTC/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed. (source=binance, points=0)
- `binance_funding:ETH/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_oi:ETH/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_liquidation:ETH/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed. (source=binance, points=0)
- `binance_funding:SOL/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_oi:SOL/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_liquidation:SOL/USD` skipped: HTTP 451 (geo-blocked / unavailable in this environment). No public USDT-M historical liquidation REST; live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed. (source=binance, points=0)
- `okx_funding:BTC/USD` ok: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=289)
- `okx_oi:BTC/USD` ok: OKX rubik 1h open-interest-history (public, paginated) (source=okx:/api/v5/rubik/stat/contracts/open-interest-history, points=1440)
- `okx_liquidation:BTC/USD` skipped: OKX liquidation-orders span 19.0h across 100 fills — not a historical aggregate. Skip rather than invent a z. (source=okx, points=0)
- `okx_funding:ETH/USD` ok: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=289)
- `okx_oi:ETH/USD` ok: OKX rubik 1h open-interest-history (public, paginated) (source=okx:/api/v5/rubik/stat/contracts/open-interest-history, points=1440)
- `okx_liquidation:ETH/USD` skipped: OKX liquidation-orders span 4.5h across 100 fills — not a historical aggregate. Skip rather than invent a z. (source=okx, points=0)
- `okx_funding:SOL/USD` ok: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=289)
- `okx_oi:SOL/USD` ok: OKX rubik 1h open-interest-history (public, paginated) (source=okx:/api/v5/rubik/stat/contracts/open-interest-history, points=1440)
- `okx_liquidation:SOL/USD` skipped: OKX liquidation-orders span 18.4h across 100 fills — not a historical aggregate. Skip rather than invent a z. (source=okx, points=0)

## Skipped optional families

- `liquidation_z_fade` (liquidation_z): fade liquidation z-score |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.
- `liquidation_z_follow` (liquidation_z): follow liquidation z-score |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.
- `cross_venue_fade` (cross_venue): fade cross-venue divergence z |z|>=1.5: skipped — no aligned series supplied. This feature is not present on the Kraken Spot OHLC paper path.

## Promotion decision

**No candidate cleared the bar.** Leave `PAPER_PROMOTE_SEARCHED_STRATEGIES=false`. This is not an edge.
Pre-registered top-1 by WF excess was `momentum_12_strict` (WF excess=+0.44%, holdout excess=-13.06%; blocked by: holdout_excess_return_not_positive).
