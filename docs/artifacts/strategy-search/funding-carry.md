# Funding / carry strategy search

Generated: 2026-09-12T17:43:30.368714+00:00
Print kind: **dual_print**. interval=`4h`; primary_venue=`hyperliquid`; second_venue=`okx`; hard_gates_available=`false`; can_promote=`false`; `keep_flag_false=true`.
Core K=13; scored ids=13; ranking_key=`informational_wf_excess_single_print_cannot_promote` (informational).
Costs: fee=10 bps + slippage=5 bps (spot overlays); hedged carry pays 2 legs × (fee+slip) on each flip. Basis is not modeled.
Walk-forward: train=180 test=60 step=60 warmup=31.
Hard gates: UNAVAILABLE: need interval=1d and >=720 aligned bars; got interval=4h, aligned_bars=720.

## What this does / does not claim

This is a paper-research catalog of funding-z thresholds, funding-agree spot overlays, and a modeled hedged cash-and-carry. It is **not** a live-capital claim, not a fabricated PnL, and not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`. Hedged carry is **not** executable on the Kraken paper-spot path.

## Honesty / pre-registered rules

Pre-registered funding/carry search (frozen before any Kraken or funding-REST pull). Funding-z threshold voters and spot overlays instantiate only when an aligned funding series is supplied — never zero-filled. Hedged carry is a research model of cash-and-carry: received |funding| minus two-leg (spot+perp) fees on each flip; perp-spot basis is not invented and is not in the PnL. Dual-print requires two independent funding venues (e.g. OKX and Hyperliquid) each covering BTC and ETH. A second candle venue without a second funding tape is not dual-print. Same-venue prefix/suffix is not independent. Hard gates (#96+A+B+C) need 720 aligned daily bars; a ~90d OKX tape cannot unlock them. Absent two venues this run is SINGLE-PRINT and cannot promote. PAPER_PROMOTE_* stays default false. No live. Empty search is success. Hard gates (#96+A+B+C) are UNAVAILABLE on this overlap (interval=4h, aligned_bars=720; need 1d and >=720). Dual-print eligible names (carry_hedged_sign) are informational only; leave every PAPER_PROMOTE_* false.

## Print policy (frozen before scoring)

Pre-registered funding/carry search (frozen before any Kraken or funding-REST pull). Funding-z threshold voters and spot overlays instantiate only when an aligned funding series is supplied — never zero-filled. Hedged carry is a research model of cash-and-carry: received |funding| minus two-leg (spot+perp) fees on each flip; perp-spot basis is not invented and is not in the PnL. Dual-print requires two independent funding venues (e.g. OKX and Hyperliquid) each covering BTC and ETH. A second candle venue without a second funding tape is not dual-print. Same-venue prefix/suffix is not independent. Hard gates (#96+A+B+C) need 720 aligned daily bars; a ~90d OKX tape cannot unlock them. Absent two venues this run is SINGLE-PRINT and cannot promote. PAPER_PROMOTE_* stays default false. No live. Empty search is success.

| print | when | can promote? |
| --- | --- | --- |
| single-print | only one usable funding venue on BTC+ETH (typical leftover: OKX only; Binance 451 / Bybit 403) | **no** |
| dual-print | two independent funding venues each covering BTC and ETH | still **no** Settings flip; a passer would only justify a documented default-false pin |

## Pre-registered catalog

Frozen catalog (K=13 when funding is present): funding-z fade/follow at |z|>=1.0 / 1.5 / 2.0 (spot signal); ema_9_21 and momentum_12 funding-agree overlays; hedged carry always-on plus |rate|>=1bp / 3bp and |z|>=1.5; informational control ma_cross_10_30 on the same funding-overlap window. Do not grow this list after seeing PnL. Hedged carry is not paper-spot executable.

Frozen ids: `funding_z_fade_1_0`, `funding_z_fade_1_5`, `funding_z_fade_2_0`, `funding_z_follow_1_0`, `funding_z_follow_1_5`, `funding_z_follow_2_0`, `ema_9_21_funding_agree`, `momentum_12_funding_agree`, `carry_hedged_sign`, `carry_hedged_abs_1bp`, `carry_hedged_abs_3bp`, `carry_hedged_z_1_5`, `ma_cross_10_30`.

Unconditioned control (cannot promote): `ma_cross_10_30`.

## Data

- BTC/USD@4h: 720 committed Kraken bars 2026-05-15T16:00:00+00:00 → 2026-09-12T12:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@4h: 720 committed Kraken bars 2026-05-15T16:00:00+00:00 → 2026-09-12T12:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)

## Funding series

- `binance_funding:BTC/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_funding:ETH/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `bybit_funding:BTC/USD` **skipped**: HTTP 403 (CloudFront / country block — unavailable in this environment) (source=bybit, points=0)
- `bybit_funding:ETH/USD` **skipped**: HTTP 403 (CloudFront / country block — unavailable in this environment) (source=bybit, points=0)
- `okx_funding:BTC/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=290)
- `okx_funding:ETH/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=290)
- `hyperliquid_funding:BTC/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 180d) (source=hyperliquid:/info fundingHistory, points=4320)
- `hyperliquid_funding:ETH/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 180d) (source=hyperliquid:/info fundingHistory, points=4320)

## Spot-signal / overlay (walk-forward mean excess after fees)

Informational. Eligible under a fee-aware sign check does not mean promoted. Control cannot promote. Scored only on the funding-overlap window (skip-not-invent extra unfunded history).

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `momentum_12_funding_agree` | funding_z | -0.74% | -0.05% | -1.69% | no | no |
| 2 | `funding_z_fade_2_0` | funding_z | -0.87% | -0.19% | -3.77% | no | no |
| 3 | `funding_z_follow_1_5` | funding_z | -0.95% | -0.27% | -0.85% | no | no |
| 4 | `funding_z_follow_2_0` | funding_z | -1.24% | -0.56% | -1.50% | no | no |
| 5 | `ema_9_21_funding_agree` | funding_z | -1.38% | -0.69% | -2.76% | no | no |
| 6 | `funding_z_fade_1_5` | funding_z | -1.61% | -0.93% | -4.69% | no | no |
| 7 | `ma_cross_10_30` | ma_cross | -1.78% | -1.10% | -12.57% | no | yes |
| 8 | `funding_z_follow_1_0` | funding_z | -1.94% | -1.25% | -1.87% | no | no |
| 9 | `funding_z_fade_1_0` | funding_z | -2.04% | -1.36% | -5.43% | no | no |

## Hedged carry (modeled; basis not invented)

PnL = received |funding| while harvesting, minus two-leg (fee+slippage) on each flip. Decision at print *i* uses only prints before *i*. Excess is versus cash (0), not versus spot buy-and-hold. Not paper-spot executable.

| id | WF total | holdout total | full-sample | eligible |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +0.06% | +0.95% | +3.89% | yes |
| `carry_hedged_abs_1bp` | +0.00% | +0.00% | +0.00% | no |
| `carry_hedged_abs_3bp` | +0.00% | +0.00% | +0.00% | no |
| `carry_hedged_z_1_5` | -2.66% | -24.03% | -84.47% | no |

## Second funding print (`okx`)

Independent tape. Not averaged with the primary. A name must clear the fee-aware bar on **both** prints to be a dual-print passer.

| rank | id | family | WF excess | WF total | holdout excess | eligible |
| ---: | --- | --- | ---: | ---: | ---: | :---: |
| 1 | `funding_z_follow_2_0` | funding_z | -0.46% | -0.10% | -2.59% | no |
| 2 | `funding_z_fade_2_0` | funding_z | -0.49% | -0.13% | -1.37% | no |
| 3 | `funding_z_follow_1_5` | funding_z | -0.50% | -0.14% | -2.36% | no |
| 4 | `momentum_12_funding_agree` | funding_z | -0.73% | -0.36% | -3.88% | no |
| 5 | `funding_z_follow_1_0` | funding_z | -0.91% | -0.55% | -3.79% | no |
| 6 | `funding_z_fade_1_5` | funding_z | -1.42% | -1.06% | -3.13% | no |
| 7 | `ema_9_21_funding_agree` | funding_z | -1.45% | -1.09% | -4.16% | no |
| 8 | `funding_z_fade_1_0` | funding_z | -2.13% | -1.77% | -5.23% | no |
| 9 | `ma_cross_10_30` | ma_cross | -3.50% | -3.14% | -11.24% | no |

| id | WF total | holdout total | full-sample | eligible |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +0.16% | +0.33% | +1.03% | yes |
| `carry_hedged_abs_1bp` | -0.68% | -2.61% | -7.31% | no |
| `carry_hedged_abs_3bp` | +0.00% | +0.00% | +0.00% | no |
| `carry_hedged_z_1_5` | -3.22% | -3.49% | -18.28% | no |

## Dual-print passers

Names that cleared the fee-aware bar on both funding venues (informational; no Settings pin): `carry_hedged_sign`.

## Promotion decision

**No candidate is promoted.** print_kind=`dual_print`; hard_gates_available=`false`; can_promote=`false`; recommended_promote_flag=`none`. Leave every `PAPER_PROMOTE_*` false. Do not add a new pin. Do not enable live.
Informational spot-signal top-1 by WF excess was `momentum_12_funding_agree` (WF excess=-0.74%, WF total=-0.05%, holdout excess=-1.69%; eligible=False).
