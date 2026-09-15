# Funding / carry strategy search

Generated: 2026-09-13T23:32:17.504249+00:00
Print kind: **dual_print**. interval=`1d`; primary_venue=`hyperliquid`; second_venue=`htx`; hard_gates_available=`true`; can_promote=`true`; basis_status=`ok`; basis_print_kind=`dual_basis`; basis_venue=`okx`; second_basis_venue=`binance_vision`; paper_path_ready=`true`; `keep_flag_false=true`.
Core K=13; scored ids=13; ranking_key=`informational_wf_excess_single_print_cannot_promote` (informational).
Costs: fee=10 bps + slippage=5 bps (spot overlays); hedged carry pays 2 legs × (fee+slip) on each flip. PIT basis is modeled (skip missing days).
Walk-forward: train=180 test=60 step=60 warmup=31.
Hard gates: available.
Funding resample: UTC `1d` sums; empty days omitted.
Aligned bars: primary=720, second=720.

## What this does / does not claim

This is a paper-research catalog of funding-z thresholds, funding-agree spot overlays, and a modeled hedged cash-and-carry. It is **not** a live-capital claim, not a fabricated PnL, and not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`. Hedged carry is **not** executable on the Kraken paper-spot path.

## Basis (skip-not-invent)

Status: **ok** (print kind `dual_basis`).
PIT mark−index basis applied per symbol on dual_basis: primary funding print (hyperliquid) × basis (okx); second funding print (htx) × basis (binance_vision). Basis PnL enters only on days where both the current and previous print have a value (missing days skipped, never zero-filled); the harvest decision never sees basis. Window frozen at/before BASIS_AWARE_WINDOW_END_UTC when using asiletto81+HTX; OKX / Binance Vision cover the live Kraken 720 without moving it.

Pairing: Pairing rule (frozen before any pull): primary funding print × --basis-venue; second funding print × --second-basis-venue. The funding tape and the basis tape need not be the same venue — the cross-venue pairing is stated here, not hidden. In dual-print a lone basis series is not applied; basis is looked up per symbol and never broadcast from one asset to the other; a day missing on either side is skipped, never zero-filled.

| print | funding venue | basis venue | symbol | first | last | days | aligned with funding | status |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| primary | hyperliquid | okx | BTC/USD | 2024-09-23 | 2026-09-12 | 720 | 720 | applied |
| primary | hyperliquid | okx | ETH/USD | 2024-09-23 | 2026-09-12 | 720 | 720 | applied |
| second | htx | binance_vision | BTC/USD | 2024-09-23 | 2026-09-12 | 719 | 719 | applied |
| second | htx | binance_vision | ETH/USD | 2024-09-23 | 2026-09-12 | 719 | 719 | applied |

## Paper-executable path

Ready: **true**. A Settings pin is not added unless this is true **and** dual-print **and** hard gates **and** PIT basis all clear.

A paper hedge+funding soak path exists when PAPER_PERP_HEDGE=true: the cycle fetches an explicit current perp mid from Hyperliquid midPx (HTX bid/ask mid fallback; BitMEX opt-in only, not required) and applies caller-supplied settlements from the same venue's public funding tape (execution/paper_perp.py + paper_perp_feed.py). TRADING_MODE=paper only; kill switch withholds new hedges and funding; live is refused. PAPER_CARRY_PATH_READY is true for that forward soak. Current snapshot mids are not a historical PIT mark−index / perp-mid−spot-mid series and are not written into research scoring. can_promote stays false while PIT basis is UNAVAILABLE on both dual-print venues. Do not add a Settings pin.

## Honesty / pre-registered rules

Pre-registered funding/carry search (frozen before any Kraken or funding-REST pull). Funding-z threshold voters and spot overlays instantiate only when an aligned funding series is supplied — never zero-filled. Hedged carry is a research model of cash-and-carry: received |funding| minus two-leg (spot+perp) fees on each flip; perp-spot basis is not invented and is not in the PnL. Dual-print requires two independent funding venues (e.g. Hyperliquid and HTX) each covering BTC and ETH. BitMEX is a sunset venue and is not selected. A second candle venue without a second funding tape is not dual-print. Same-venue prefix/suffix is not independent. Hard gates (#96+A+B+C) need 720 aligned daily bars on each funding venue; a ~90d OKX tape cannot unlock them (including after UTC-day resample). Daily evaluation sums settlements per UTC day and omits empty days — never zero-filled. Perp-spot basis is skipped unless a PIT mark−index / perp-mid−spot-mid series is supplied; funding premium and last-trade are not basis. Second-venue PIT basis is OKX + Binance Vision daily mark−index (paired primary×OKX, second×Binance Vision, frozen before the pull; a lone series is not applied in dual-print; basis is per symbol, never broadcast). A paper hedge+funding soak path is cycle-wired (PAPER_CARRY_PATH_READY=true when PAPER_PERP_HEDGE fetches an explicit HL midPx or HTX bid/ask mid and applies same-venue funding; BitMEX is not required; Kraken spot mid is not used). Current snapshot mids are not a historical PIT basis series and are not scored here. can_promote stays false while PIT basis is UNAVAILABLE. Absent two venues this run is SINGLE-PRINT and cannot promote. A pin requires dual-print + hard gates + PIT basis + a paper-executable path. PAPER_PROMOTE_* stays default false. No live. Empty search is success. Funding tapes were resampled to UTC 1d sums (empty days omitted, not zero-filled). Primary carry hard gates: carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8739374550921887) B=true (3/3) C=true combined=true. w1: BTC=0.015712199792257575 ETH=0.014795969588255131 pass=true; w2: BTC=0.01317380190272277 ETH=0.015423233595002195 pass=true; w3: BTC=0.013412472825653055 ETH=0.01460535858725942 pass=true. Second carry hard gates: carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8043228847941867) B=true (3/3) C=true combined=true. w1: BTC=0.011019696801414014 ETH=0.011026021861587632 pass=true; w2: BTC=0.015296725109407605 ETH=0.013854616579876966 pass=true; w3: BTC=0.012406443432842362 ETH=0.008209551618621136 pass=true. Basis applied (dual_basis): primary×okx, second×binance_vision; USDT-quoted mark−index, per symbol, missing days skipped. Paper hedge+funding soak path is cycle-wired (PAPER_CARRY_PATH_READY=true; explicit HL/HTX mid + same-venue funding; BitMEX not required; Kraken spot mid is not used). Snapshot mids are not historical PIT basis. can_promote still requires PIT basis on both dual-print venues. Do not add a Settings pin. Dual-print eligible names (carry_hedged_sign) are informational only; leave every PAPER_PROMOTE_* false.

## Print policy (frozen before scoring)

Pre-registered funding/carry search (frozen before any Kraken or funding-REST pull). Funding-z threshold voters and spot overlays instantiate only when an aligned funding series is supplied — never zero-filled. Hedged carry is a research model of cash-and-carry: received |funding| minus two-leg (spot+perp) fees on each flip; perp-spot basis is not invented and is not in the PnL. Dual-print requires two independent funding venues (e.g. Hyperliquid and HTX) each covering BTC and ETH. BitMEX is a sunset venue and is not selected. A second candle venue without a second funding tape is not dual-print. Same-venue prefix/suffix is not independent. Hard gates (#96+A+B+C) need 720 aligned daily bars on each funding venue; a ~90d OKX tape cannot unlock them (including after UTC-day resample). Daily evaluation sums settlements per UTC day and omits empty days — never zero-filled. Perp-spot basis is skipped unless a PIT mark−index / perp-mid−spot-mid series is supplied; funding premium and last-trade are not basis. Second-venue PIT basis is OKX + Binance Vision daily mark−index (paired primary×OKX, second×Binance Vision, frozen before the pull; a lone series is not applied in dual-print; basis is per symbol, never broadcast). A paper hedge+funding soak path is cycle-wired (PAPER_CARRY_PATH_READY=true when PAPER_PERP_HEDGE fetches an explicit HL midPx or HTX bid/ask mid and applies same-venue funding; BitMEX is not required; Kraken spot mid is not used). Current snapshot mids are not a historical PIT basis series and are not scored here. can_promote stays false while PIT basis is UNAVAILABLE. Absent two venues this run is SINGLE-PRINT and cannot promote. A pin requires dual-print + hard gates + PIT basis + a paper-executable path. PAPER_PROMOTE_* stays default false. No live. Empty search is success.

| print | when | can promote? |
| --- | --- | --- |
| single-print | only one usable funding venue on BTC+ETH (typical leftover: OKX only; Binance 451 / Bybit 403) | **no** |
| dual-print | two independent funding venues each covering BTC and ETH | still **no** Settings flip; a passer would only justify a documented default-false pin |

## Pre-registered catalog

Frozen catalog (K=13 when funding is present): funding-z fade/follow at |z|>=1.0 / 1.5 / 2.0 (spot signal); ema_9_21 and momentum_12 funding-agree overlays; hedged carry always-on plus |rate|>=1bp / 3bp and |z|>=1.5; informational control ma_cross_10_30 on the same funding-overlap window. Do not grow this list after seeing PnL. Hedged carry is not paper-spot executable and is not basis-aware unless a PIT basis series is supplied.

Frozen ids: `funding_z_fade_1_0`, `funding_z_fade_1_5`, `funding_z_fade_2_0`, `funding_z_follow_1_0`, `funding_z_follow_1_5`, `funding_z_follow_2_0`, `ema_9_21_funding_agree`, `momentum_12_funding_agree`, `carry_hedged_sign`, `carry_hedged_abs_1bp`, `carry_hedged_abs_3bp`, `carry_hedged_z_1_5`, `ma_cross_10_30`.

Unconditioned control (cannot promote): `ma_cross_10_30`.

## Data

- BTC/USD@1d: 720 committed Kraken bars 2024-09-23T00:00:00+00:00 → 2026-09-12T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-23T00:00:00+00:00 → 2026-09-12T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)

## Funding series

- `binance_funding:BTC/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `binance_funding:ETH/USD` **skipped**: HTTP 451 (geo-blocked / unavailable in this environment) (source=binance, points=0)
- `bybit_funding:BTC/USD` **skipped**: HTTP 403 (CloudFront / country block — unavailable in this environment) (source=bybit, points=0)
- `bybit_funding:ETH/USD` **skipped**: HTTP 403 (CloudFront / country block — unavailable in this environment) (source=bybit, points=0)
- `okx_funding:BTC/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=293)
- `okx_funding:ETH/USD` **ok**: OKX swap funding-rate-history (public; ~90d of 8h prints) (source=okx:/api/v5/public/funding-rate-history, points=293)
- `hyperliquid_funding:BTC/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d) (source=hyperliquid:/info fundingHistory, points=19199)
- `hyperliquid_funding:ETH/USD` **ok**: Hyperliquid public fundingHistory (hourly; paginated; lookback 800d) (source=hyperliquid:/info fundingHistory, points=19199)
- `htx_funding:BTC/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d) (source=htx:/linear-swap-api/v1/swap_historical_funding_rate, points=2401)
- `htx_funding:ETH/USD` **ok**: HTX linear-swap public funding_rate (paginated 8h; not avg_premium_index; realized_rate unused/null; lookback 800d) (source=htx:/linear-swap-api/v1/swap_historical_funding_rate, points=2401)
- `bitmex_funding:BTC/USD` **ok**: BitMEX public funding settlements (paginated; fundingRate only, not fundingRateDaily; lookback 800d; sunset venue — BitMEX official closure 23 September 2026 04:00 UTC (risk limits from 26 August 2026 04:00 UTC; new registrations already stopped). https://www.bitmex.com/blog/bitmex-closure. Not a long-term dual-print, funding, basis, or paper-hedge venue.) (source=bitmex:/api/v1/funding, points=2400)
- `bitmex_funding:ETH/USD` **ok**: BitMEX public funding settlements (paginated; fundingRate only, not fundingRateDaily; lookback 800d; sunset venue — BitMEX official closure 23 September 2026 04:00 UTC (risk limits from 26 August 2026 04:00 UTC; new registrations already stopped). https://www.bitmex.com/blog/bitmex-closure. Not a long-term dual-print, funding, basis, or paper-hedge venue.) (source=bitmex:/api/v1/funding, points=2400)
- `okx_basis:BTC/USD` **ok**: loaded 720 daily mark−index rows from var/research/basis/okx/BTCUSD_basis_1d.json (2024-09-23 → 2026-09-12; clamped to the scored window; missing days stay missing) (source=okx:file, points=720)
- `okx_basis:ETH/USD` **ok**: loaded 720 daily mark−index rows from var/research/basis/okx/ETHUSD_basis_1d.json (2024-09-23 → 2026-09-12; clamped to the scored window; missing days stay missing) (source=okx:file, points=720)
- `binance_vision_basis:BTC/USD` **ok**: loaded 719 daily mark−index rows from var/research/basis/binance_vision/BTCUSD_basis_1d.json (2024-09-23 → 2026-09-12; clamped to the scored window; missing days stay missing) (source=binance_vision:file, points=719)
- `binance_vision_basis:ETH/USD` **ok**: loaded 719 daily mark−index rows from var/research/basis/binance_vision/ETHUSD_basis_1d.json (2024-09-23 → 2026-09-12; clamped to the scored window; missing days stay missing) (source=binance_vision:file, points=719)
- `funding:BTC/USD` **ok**: resampled 19199 prints → 800 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=800)
- `funding:ETH/USD` **ok**: resampled 19199 prints → 800 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=800)
- `second_funding:BTC/USD` **ok**: resampled 2401 prints → 800 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=800)
- `second_funding:ETH/USD` **ok**: resampled 2401 prints → 800 UTC daily sums (empty days omitted, not zero-filled) (source=funding_carry.resample_daily, points=800)

## Spot-signal / overlay (walk-forward mean excess after fees)

Informational. Eligible under a fee-aware sign check does not mean promoted. Control cannot promote. Scored only on the funding-overlap window (skip-not-invent extra unfunded history).

| rank | id | family | WF excess | WF total | holdout excess | eligible | control |
| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -7.63% | +7.82% | +3.39% | no | yes |
| 2 | `funding_z_follow_1_0` | funding_z | -11.05% | +4.39% | -27.81% | no | no |
| 3 | `funding_z_follow_1_5` | funding_z | -11.23% | +4.21% | -24.24% | no | no |
| 4 | `funding_z_follow_2_0` | funding_z | -12.35% | +3.09% | -23.59% | no | no |
| 5 | `ema_9_21_funding_agree` | funding_z | -14.55% | +0.89% | -7.27% | no | no |
| 6 | `momentum_12_funding_agree` | funding_z | -14.95% | +0.50% | -12.23% | no | no |
| 7 | `funding_z_fade_2_0` | funding_z | -19.25% | -3.81% | -5.34% | no | no |
| 8 | `funding_z_fade_1_5` | funding_z | -20.55% | -5.11% | -7.91% | no | no |
| 9 | `funding_z_fade_1_0` | funding_z | -22.06% | -6.62% | -8.93% | no | no |

## Hedged carry (modeled; basis not invented)

PnL = received |funding| while harvesting, minus two-leg (fee+slippage) on each flip. Decision at print *i* uses only prints before *i*. Excess is versus cash (0), not versus spot buy-and-hold. Not paper-spot executable. Basis is included only when a PIT series was supplied.

| id | WF total | holdout total | full-sample | eligible |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.71% | +3.33% | +27.76% | yes |
| `carry_hedged_abs_1bp` | -1.43% | -8.15% | -18.57% | no |
| `carry_hedged_abs_3bp` | -2.43% | -4.68% | -21.46% | no |
| `carry_hedged_z_1_5` | -2.87% | -8.83% | -32.92% | no |

## Second funding print (`htx`)

Independent tape. Not averaged with the primary. A name must clear the fee-aware bar on **both** prints to be a dual-print passer.

| rank | id | family | WF excess | WF total | holdout excess | eligible |
| ---: | --- | --- | ---: | ---: | ---: | :---: |
| 1 | `ma_cross_10_30` | ma_cross | -7.63% | +7.82% | +3.39% | no |
| 2 | `funding_z_fade_1_5` | funding_z | -14.22% | +1.22% | -8.50% | no |
| 3 | `ema_9_21_funding_agree` | funding_z | -14.27% | +1.17% | -7.12% | no |
| 4 | `momentum_12_funding_agree` | funding_z | -14.50% | +0.95% | -8.99% | no |
| 5 | `funding_z_fade_2_0` | funding_z | -15.18% | +0.26% | -2.60% | no |
| 6 | `funding_z_follow_1_0` | funding_z | -15.85% | -0.41% | -21.41% | no |
| 7 | `funding_z_follow_2_0` | funding_z | -16.91% | -1.46% | -24.63% | no |
| 8 | `funding_z_fade_1_0` | funding_z | -18.25% | -2.81% | -13.10% | no |
| 9 | `funding_z_follow_1_5` | funding_z | -18.30% | -2.85% | -22.37% | no |

| id | WF total | holdout total | full-sample | eligible |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.49% | +3.30% | +21.26% | yes |
| `carry_hedged_abs_1bp` | -1.71% | -11.99% | -32.24% | no |
| `carry_hedged_abs_3bp` | -3.66% | -9.94% | -35.77% | no |
| `carry_hedged_z_1_5` | -3.00% | -9.76% | -34.21% | no |

## Carry hard gates (#96+A+B+C analog on daily funding)

Evaluated only on a UTC-daily resampled tape. UNAVAILABLE when a venue has fewer than 720 daily prints. Combined requires #96 (BTC and ETH WF total > 0 and holdout > 0), A (holdout magnitude ratio >= 0.25), B (2 of 3 recent 240-day windows with BTC and ETH WF total > 0), and C (2× fees still clear #96). This is informational and cannot unlock a Settings pin without PIT basis and a paper-executable path.

- Primary (`hyperliquid`): available=`true`; carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8739374550921887) B=true (3/3) C=true combined=true. w1: BTC=0.015712199792257575 ETH=0.014795969588255131 pass=true; w2: BTC=0.01317380190272277 ETH=0.015423233595002195 pass=true; w3: BTC=0.013412472825653055 ETH=0.01460535858725942 pass=true
- Second (`htx`): available=`true`; carry_hedged_sign daily hard gates: #96=true A=true (ratio=0.8043228847941867) B=true (3/3) C=true combined=true. w1: BTC=0.011019696801414014 ETH=0.011026021861587632 pass=true; w2: BTC=0.015296725109407605 ETH=0.013854616579876966 pass=true; w3: BTC=0.012406443432842362 ETH=0.008209551618621136 pass=true

## Dual-print passers

Names that cleared the fee-aware bar on both funding venues (informational; no Settings pin): `carry_hedged_sign`.

## Promotion decision

**No candidate is promoted.** print_kind=`dual_print`; hard_gates_available=`true`; can_promote=`true`; recommended_promote_flag=`none`. The pre-registered bar (dual-print + hard gates + PIT basis on both prints + paper path + a dual-print passer) was reached in this report. That is a report field, not a Settings change: this command writes no pin, every `PAPER_PROMOTE_*` default stays false, and hedged carry is still not paper-spot executable. A pin, if ever proposed, is a separate documented default-false flag reviewed by a human — never flipped by a research run. Do not enable live.
Informational spot-signal top-1 by WF excess was `ma_cross_10_30` (WF excess=-7.63%, WF total=+7.82%, holdout excess=+3.39%; eligible=False).
