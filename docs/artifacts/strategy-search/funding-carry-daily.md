# Funding / carry strategy search

**BitMEX sunset replacement print.** Official closure 23 September
2026 04:00 UTC (https://www.bitmex.com/blog/bitmex-closure). BitMEX
was fetched as dead-end documentation and **not selected**. Second
venue is **HTX**. PIT basis stays skipped (HTX mark−index is one
venue; HL archive ends 2026-06-01). `#112` HL+BitMEX numbers are
superseded for dual-print pairing, not as a promote unlock.

Generated: 2026-09-12T22:20:58.387139+00:00
Print kind: **dual_print**. interval=`1d`; primary_venue=`hyperliquid`; second_venue=`htx`; hard_gates_available=`true`; can_promote=`false`; basis_status=`skipped`; paper_path_ready=`true`; `keep_flag_false=true`.
Core K=13; scored ids=13; ranking_key=`informational_wf_excess_single_print_cannot_promote` (informational).
Costs: fee=10 bps + slippage=5 bps (spot overlays); hedged carry pays 2 legs × (fee+slip) on each flip. Basis is skipped, not invented.
Walk-forward: train=180 test=60 step=60 warmup=31.
Hard gates: available.
Funding resample: UTC `1d` sums; empty days omitted.
Aligned bars: primary=720, second=720.

## What this does / does not claim

This is a paper-research catalog of funding-z thresholds, funding-agree spot overlays, and a modeled hedged cash-and-carry. It is **not** a live-capital claim, not a fabricated PnL, and not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`. Hedged carry is **not** executable on the Kraken paper-spot path.

## Basis (skip-not-invent)

Status: **skipped**.
Perp-spot basis skipped, not invented. No PIT mark−index (or perp mid − spot mid) series was supplied on both dual-print venues for the scored window. Live probes: Hyperliquid public REST is current markPx/oraclePx/midPx only; asiletto81/hyperliquid asset_ctxs is ≥720d but ends 2026-06-01 (~617d on the current Kraken 720). HTX daily mark−index exists on one venue and is not applied alone. BitMEX is a sunset venue (closure 23 September 2026 04:00 UTC) and still has no free ≥720d mark−index. Hyperliquid fundingHistory.premium and BitMEX .XBTUSDPI/.ETHUSDPI are funding-formula inputs and are not used. Last-trade and funding-implied basis are circular / look-ahead. Carry PnL stays received |funding| minus two-leg fees. Cannot promote on a basis-unaware model.

## Paper-executable path

Ready: **true**. A Settings pin is not added unless this is true **and** dual-print **and** hard gates **and** PIT basis all clear.

A paper hedge+funding soak path exists when PAPER_PERP_HEDGE=true: the cycle fetches an explicit current perp mid from Hyperliquid midPx (HTX bid/ask mid fallback; BitMEX opt-in only, not required) and applies caller-supplied settlements from the same venue's public funding tape (execution/paper_perp.py + paper_perp_feed.py). TRADING_MODE=paper only; kill switch withholds new hedges and funding; live is refused. PAPER_CARRY_PATH_READY is true for that forward soak. Current snapshot mids are not a historical PIT mark−index / perp-mid−spot-mid series and are not written into research scoring. can_promote stays false while PIT basis is UNAVAILABLE on both dual-print venues. Do not add a Settings pin.

## Honesty / pre-registered rules

Pre-registered funding/carry search (frozen before any Kraken or funding-REST pull). Funding-z threshold voters and spot overlays instantiate only when an aligned funding series is supplied — never zero-filled. Hedged carry is a research model of cash-and-carry: received |funding| minus two-leg (spot+perp) fees on each flip; perp-spot basis is not invented and is not in the PnL. Dual-print requires two independent funding venues (e.g. Hyperliquid and HTX) each covering BTC and ETH. BitMEX is a sunset venue and is not selected. A second candle venue without a second funding tape is not dual-print. Same-venue prefix/suffix is not independent. Hard gates (#96+A+B+C) need 720 aligned daily bars on each funding venue; a ~90d OKX tape cannot unlock them (including after UTC-day resample). Daily evaluation sums settlements per UTC day and omits empty days — never zero-filled. Perp-spot basis is skipped unless a PIT mark−index / perp-mid−spot-mid series is supplied; funding premium and last-trade are not basis. A paper hedge+funding soak path is cycle-wired (PAPER_CARRY_PATH_READY=true when PAPER_PERP_HEDGE fetches an explicit HL midPx or HTX bid/ask mid and applies same-venue funding; BitMEX is not required; Kraken spot mid is not used). Current snapshot mids are not a historical PIT basis series and are not scored here. can_promote stays false while PIT basis is UNAVAILABLE. Absent two venues this run is SINGLE-PRINT and cannot promote. A pin requires dual-print + hard gates + PIT basis + a paper-executable path. PAPER_PROMOTE_* stays default false. No live. Empty search is success. Funding tapes were resampled to UTC 1d sums (empty days omitted, not zero-filled). Primary carry hard gates: carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8737397404820223) B=true (3/3) C=true combined=true. w1: BTC=0.015155537638074312 ETH=0.01379697913744904 pass=true; w2: BTC=0.01312875992260909 ETH=0.015352042577623903 pass=true; w3: BTC=0.013725533075015006 ETH=0.014641196489654451 pass=true. Second carry hard gates: carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8050542781802776) B=true (3/3) C=true combined=true. w1: BTC=0.011140932518064472 ETH=0.010938196117621146 pass=true; w2: BTC=0.015256899439940463 ETH=0.013650204397158916 pass=true; w3: BTC=0.012331398197611643 ETH=0.008100364966832752 pass=true. Basis skipped (no PIT series). Paper hedge+funding soak path is cycle-wired (PAPER_CARRY_PATH_READY=true; explicit HL/HTX mid + same-venue funding; BitMEX not required; Kraken spot mid is not used). Snapshot mids are not historical PIT basis. can_promote still requires PIT basis on both dual-print venues. Do not add a Settings pin. Dual-print eligible names (carry_hedged_sign) are informational only; leave every PAPER_PROMOTE_* false. can_promote stays false unless dual-print AND hard gates AND PIT basis AND a paper-executable path all clear.

## Print policy (frozen before scoring)

Pre-registered funding/carry search (frozen before any Kraken or funding-REST pull). Funding-z threshold voters and spot overlays instantiate only when an aligned funding series is supplied — never zero-filled. Hedged carry is a research model of cash-and-carry: received |funding| minus two-leg (spot+perp) fees on each flip; perp-spot basis is not invented and is not in the PnL. Dual-print requires two independent funding venues (e.g. Hyperliquid and HTX) each covering BTC and ETH. BitMEX is a sunset venue and is not selected. A second candle venue without a second funding tape is not dual-print. Same-venue prefix/suffix is not independent. Hard gates (#96+A+B+C) need 720 aligned daily bars on each funding venue; a ~90d OKX tape cannot unlock them (including after UTC-day resample). Daily evaluation sums settlements per UTC day and omits empty days — never zero-filled. Perp-spot basis is skipped unless a PIT mark−index / perp-mid−spot-mid series is supplied; funding premium and last-trade are not basis. A paper hedge+funding soak path is cycle-wired (PAPER_CARRY_PATH_READY=true when PAPER_PERP_HEDGE fetches an explicit HL midPx or HTX bid/ask mid and applies same-venue funding; BitMEX is not required; Kraken spot mid is not used). Current snapshot mids are not a historical PIT basis series and are not scored here. can_promote stays false while PIT basis is UNAVAILABLE. Absent two venues this run is SINGLE-PRINT and cannot promote. A pin requires dual-print + hard gates + PIT basis + a paper-executable path. PAPER_PROMOTE_* stays default false. No live. Empty search is success.

| print | when | can promote? |
| --- | --- | --- |
| single-print | only one usable funding venue on BTC+ETH (typical leftover: OKX only; Binance 451 / Bybit 403) | **no** |
| dual-print | two independent funding venues each covering BTC and ETH | still **no** Settings flip; a passer would only justify a documented default-false pin |

## Pre-registered catalog

Frozen catalog (K=13 when funding is present): funding-z fade/follow at |z|>=1.0 / 1.5 / 2.0 (spot signal); ema_9_21 and momentum_12 funding-agree overlays; hedged carry always-on plus |rate|>=1bp / 3bp and |z|>=1.5; informational control ma_cross_10_30 on the same funding-overlap window. Do not grow this list after seeing PnL. Hedged carry is not paper-spot executable and is not basis-aware unless a PIT basis series is supplied.

Frozen ids: `funding_z_fade_1_0`, `funding_z_fade_1_5`, `funding_z_fade_2_0`, `funding_z_follow_1_0`, `funding_z_follow_1_5`, `funding_z_follow_2_0`, `ema_9_21_funding_agree`, `momentum_12_funding_agree`, `carry_hedged_sign`, `carry_hedged_abs_1bp`, `carry_hedged_abs_3bp`, `carry_hedged_z_1_5`, `ma_cross_10_30`.

Unconditioned control (cannot promote): `ma_cross_10_30`.

## Data

- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)

## Funding series

- `binance_funding:BTC/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_funding:ETH/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `bybit_funding:BTC/USD` **skipped**: HTTP 403 (CloudFront / country block — unavailable in this environment) (source=bybit, points=0)
- `bybit_funding:ETH/USD` **skipped**: HTTP 403 (CloudFront / country block — unavailable in this environment) (source=bybit, points=0)
- `okx_funding:BTC/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=290)
- `okx_funding:ETH/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=290)
- `hyperliquid_funding:BTC/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d) (source=hyperliquid:/info fundingHistory, points=19199)
- `hyperliquid_funding:ETH/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d) (source=hyperliquid:/info fundingHistory, points=19199)
- `htx_funding:BTC/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d) (source=htx:/linear-swap-api/v1/swap_historical_funding_rate, points=2401)
- `htx_funding:ETH/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d) (source=htx:/linear-swap-api/v1/swap_historical_funding_rate, points=2401)
- `bitmex_funding:BTC/USD` **ok**: BitMEX public funding settlements (paginated; fundingRate only, not fundingRateDaily; lookback 800d; sunset venue — BitMEX official closure 23 September 2026 04:00 UTC (risk limits from 26 August 2026 04:00 UTC; new registrations already stopped). https://www.bitmex.com/blog/bitmex-closure. Not a long-term dual-print, funding, basis, or paper-hedge venue.) (source=bitmex:/api/v1/funding, points=2400)
- `bitmex_funding:ETH/USD` **ok**: BitMEX public funding settlements (paginated; fundingRate only, not fundingRateDaily; lookback 800d; sunset venue — BitMEX official closure 23 September 2026 04:00 UTC (risk limits from 26 August 2026 04:00 UTC; new registrations already stopped). https://www.bitmex.com/blog/bitmex-closure. Not a long-term dual-print, funding, basis, or paper-hedge venue.) (source=bitmex:/api/v1/funding, points=2400)
- `hyperliquid_basis:BTC/USD` **skipped**: UNAVAILABLE: Hyperliquid public REST has current markPx/oraclePx/midPx only (metaAndAssetCtxs). fundingHistory.premium is the funding-formula input, not a PIT perp−spot mid, and is not used. candleSnapshot is last-trade, not mid. HuggingFace asiletto81/hyperliquid asset_ctxs is a public ≥720d mark_px/oracle_px tape (883 contiguous days 2024-01-01 → 2026-06-01) but the current Kraken 720 (2024-09-22 → 2026-09-11) aligns only ~617 days. Official S3 is requester-pays 403. Skip-not-invent; do not retune the window after seeing the archive end date. Current markPx/oraclePx observed; snapshot only. (source=hyperliquid:/info metaAndAssetCtxs, points=0)
- `hyperliquid_basis:ETH/USD` **skipped**: UNAVAILABLE: Hyperliquid public REST has current markPx/oraclePx/midPx only (metaAndAssetCtxs). fundingHistory.premium is the funding-formula input, not a PIT perp−spot mid, and is not used. candleSnapshot is last-trade, not mid. HuggingFace asiletto81/hyperliquid asset_ctxs is a public ≥720d mark_px/oracle_px tape (883 contiguous days 2024-01-01 → 2026-06-01) but the current Kraken 720 (2024-09-22 → 2026-09-11) aligns only ~617 days. Official S3 is requester-pays 403. Skip-not-invent; do not retune the window after seeing the archive end date. Current markPx/oraclePx observed; snapshot only. (source=hyperliquid:/info metaAndAssetCtxs, points=0)
- `htx_basis:BTC/USD` **ok**: HTX public daily mark_price_kline close minus index close over index (not last-trade; not premium_index). Single-venue tape; dual-print basis still needs Hyperliquid on the same window. (source=htx:/index/market/history mark_price_kline−index, points=2000)
- `htx_basis:ETH/USD` **ok**: HTX public daily mark_price_kline close minus index close over index (not last-trade; not premium_index). Single-venue tape; dual-print basis still needs Hyperliquid on the same window. (source=htx:/index/market/history mark_price_kline−index, points=2000)
- `bitmex_basis:BTC/USD` **skipped**: UNAVAILABLE: BitMEX is sunsetting (official closure 23 September 2026 04:00 UTC; https://www.bitmex.com/blog/bitmex-closure) and is not a long-term basis venue. Public REST still has current markPrice / indicativeSettlePrice / midPrice only. Historical .XBTUSDPI / .ETHUSDPI is the funding-formula premium index (same class as Hyperliquid premium — not used). quote/bucketed + .BXBT/.BETH can form perp-mid−index, which is not mark−index and not perp-mid−spot-mid. Skip-not-invent. Current markPrice/indicativeSettlePrice observed; snapshot only. .XBTUSDPI historical premium index exists and is not used (funding-formula input, not mark−index). (source=bitmex:/api/v1/instrument, points=0)
- `bitmex_basis:ETH/USD` **skipped**: UNAVAILABLE: BitMEX is sunsetting (official closure 23 September 2026 04:00 UTC; https://www.bitmex.com/blog/bitmex-closure) and is not a long-term basis venue. Public REST still has current markPrice / indicativeSettlePrice / midPrice only. Historical .XBTUSDPI / .ETHUSDPI is the funding-formula premium index (same class as Hyperliquid premium — not used). quote/bucketed + .BXBT/.BETH can form perp-mid−index, which is not mark−index and not perp-mid−spot-mid. Skip-not-invent. Current markPrice/indicativeSettlePrice observed; snapshot only. .ETHUSDPI historical premium index exists and is not used (funding-formula input, not mark−index). (source=bitmex:/api/v1/instrument, points=0)
- `funding:BTC/USD` **ok**: resampled 19199 prints → 801 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=801)
- `funding:ETH/USD` **ok**: resampled 19199 prints → 801 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=801)
- `second_funding:BTC/USD` **ok**: resampled 2401 prints → 800 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=800)
- `second_funding:ETH/USD` **ok**: resampled 2401 prints → 800 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=800)
- `perp_spot_basis` **skipped**: Perp-spot basis skipped, not invented. No PIT mark−index (or perp mid − spot mid) series was supplied on both dual-print venues for the scored window. Live probes: Hyperliquid public REST is current markPx/oraclePx/midPx only; asiletto81/hyperliquid asset_ctxs is ≥720d but ends 2026-06-01 (~617d on the current Kraken 720). HTX daily mark−index exists on one venue and is not applied alone. BitMEX is a sunset venue (closure 23 September 2026 04:00 UTC) and still has no free ≥720d mark−index. Hyperliquid fundingHistory.premium and BitMEX .XBTUSDPI/.ETHUSDPI are funding-formula inputs and are not used. Last-trade and funding-implied basis are circular / look-ahead. Carry PnL stays received |funding| minus two-leg fees. Cannot promote on a basis-unaware model. (source=funding_carry.basis, points=0)

## Spot-signal / overlay (walk-forward mean excess after fees)

Informational. Eligible under a fee-aware sign check does not mean promoted. Control cannot promote. Scored only on the funding-overlap window (skip-not-invent extra unfunded history).

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -4.41% | +7.80% | +4.94% | no | yes |
| 2 | `funding_z_follow_1_5` | funding_z | -7.71% | +4.50% | -20.64% | no | no |
| 3 | `funding_z_follow_1_0` | funding_z | -8.33% | +3.88% | -24.04% | no | no |
| 4 | `funding_z_follow_2_0` | funding_z | -8.81% | +3.41% | -19.98% | no | no |
| 5 | `ema_9_21_funding_agree` | funding_z | -10.79% | +1.43% | -3.56% | no | no |
| 6 | `momentum_12_funding_agree` | funding_z | -11.18% | +1.03% | -8.63% | no | no |
| 7 | `funding_z_fade_2_0` | funding_z | -16.23% | -4.02% | -1.74% | no | no |
| 8 | `funding_z_fade_1_5` | funding_z | -17.54% | -5.33% | -4.32% | no | no |
| 9 | `funding_z_fade_1_0` | funding_z | -18.29% | -6.07% | -5.22% | no | no |

## Hedged carry (modeled; basis not invented)

PnL = received |funding| while harvesting, minus two-leg (fee+slippage) on each flip. Decision at print *i* uses only prints before *i*. Excess is versus cash (0), not versus spot buy-and-hold. Not paper-spot executable. Basis is included only when a PIT series was supplied.

| id | WF total | holdout total | full-sample | eligible |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.72% | +3.32% | +27.71% | yes |
| `carry_hedged_abs_1bp` | -1.36% | -8.17% | -18.98% | no |
| `carry_hedged_abs_3bp` | -2.42% | -4.82% | -21.50% | no |
| `carry_hedged_z_1_5` | -2.88% | -8.72% | -32.95% | no |

## Second funding print (`htx`)

Independent tape. Not averaged with the primary. A name must clear the fee-aware bar on **both** prints to be a dual-print passer.

| rank | id | family | WF excess | WF total | holdout excess | eligible |
| ---: | --- | --- | ---: | ---: | ---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -4.41% | +7.80% | +4.94% | no |
| 2 | `funding_z_fade_1_5` | funding_z | -10.40% | +1.81% | -4.93% | no |
| 3 | `ema_9_21_funding_agree` | funding_z | -10.54% | +1.67% | -4.52% | no |
| 4 | `momentum_12_funding_agree` | funding_z | -10.77% | +1.44% | -6.35% | no |
| 5 | `funding_z_fade_2_0` | funding_z | -11.95% | +0.26% | +1.00% | no |
| 6 | `funding_z_follow_1_0` | funding_z | -13.27% | -1.05% | -16.89% | no |
| 7 | `funding_z_follow_2_0` | funding_z | -13.67% | -1.46% | -21.03% | no |
| 8 | `funding_z_fade_1_0` | funding_z | -14.37% | -2.15% | -10.47% | no |
| 9 | `funding_z_follow_1_5` | funding_z | -15.59% | -3.38% | -18.44% | no |

| id | WF total | holdout total | full-sample | eligible |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.50% | +3.31% | +21.26% | yes |
| `carry_hedged_abs_1bp` | -1.66% | -12.15% | -32.13% | no |
| `carry_hedged_abs_3bp` | -3.65% | -9.95% | -35.76% | no |
| `carry_hedged_z_1_5` | -2.99% | -9.64% | -34.12% | no |

## Carry hard gates (#96+A+B+C analog on daily funding)

Evaluated only on a UTC-daily resampled tape. UNAVAILABLE when a venue has fewer than 720 daily prints. Combined requires #96 (BTC and ETH WF total > 0 and holdout > 0), A (holdout magnitude ratio >= 0.25), B (2 of 3 recent 240-day windows with BTC and ETH WF total > 0), and C (2× fees still clear #96). This is informational and cannot unlock a Settings pin without PIT basis and a paper-executable path.

- Primary (`hyperliquid`): available=`true`; carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8737397404820223) B=true (3/3) C=true combined=true. w1: BTC=0.015155537638074312 ETH=0.01379697913744904 pass=true; w2: BTC=0.01312875992260909 ETH=0.015352042577623903 pass=true; w3: BTC=0.013725533075015006 ETH=0.014641196489654451 pass=true
- Second (`htx`): available=`true`; carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8050542781802776) B=true (3/3) C=true combined=true. w1: BTC=0.011140932518064472 ETH=0.010938196117621146 pass=true; w2: BTC=0.015256899439940463 ETH=0.013650204397158916 pass=true; w3: BTC=0.012331398197611643 ETH=0.008100364966832752 pass=true

## Dual-print passers

Names that cleared the fee-aware bar on both funding venues (informational; no Settings pin): `carry_hedged_sign`.

## Promotion decision

**No candidate is promoted.** print_kind=`dual_print`; hard_gates_available=`true`; can_promote=`false`; recommended_promote_flag=`none`. Leave every `PAPER_PROMOTE_*` false. Do not add a new pin. Do not enable live.
Informational spot-signal top-1 by WF excess was `ma_cross_10_30` (WF excess=-4.41%, WF total=+7.80%, holdout excess=+4.94%; eligible=False).
