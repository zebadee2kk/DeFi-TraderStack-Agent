# Edge-hunt status — 2026-09-12

Paper / research only. This memo summarizes the strategy-search dead
ends through #123 (volume-confirmed breakout: **0** dual-print
passers) plus the #124 PIT-basis archive re-hunt and the
BitMEX-sunset replacement hunt. It is **not** a profitability
claim. No number
here is invented.

All `PAPER_PROMOTE_*` defaults stay **false**. `TRADING_MODE` stays
`paper`. No live path.

## What cannot promote (standing rules)

A name cannot enter a paper pin, and must not be talked about as an
edge, unless **all** of the following are true:

1. Dual independent prints (two venues **or** two non-overlapping
   eras that are not the same tape split in half).
2. Fee-aware walk-forward **total** return > 0 and holdout excess > 0
   on **both** BTC and ETH (the #96 balanced bar), plus the harder
   A/B/C gates where the window is long enough.
3. The catalog and the print policy were frozen **before** the pull.
4. An operator-facing `PAPER_PROMOTE_*` flag is added only after a
   committed report names a passer, and that flag still defaults
   **false**.

A Kraken-only combined-passer is not enough. Beating a falling
buy-and-hold while still losing money is not an edge. Skip-not-invent:
a missing series is a skip, not a zero-filled z.

## Dead ends (do not re-litigate without new data)

| id | family | result | why it cannot promote |
| --- | --- | --- | --- |
| #104 | Daily EMA dual-print (`traderstack-dual-print-search`) | **0** dual-print passers | Kraken combined-passers existed (`ema_9_21_adx15` mean HO +26.07% and four others). Binance.US older-720 combined-passers: **0** (mean HO −7.67% to −15.80%). Positive Kraken holdout with a losing second print is not an edge. |
| #105 | Liquidation / regime (`traderstack-liq-regime-search`) | no historical liq | Binance `allForceOrders` HTTP 451 / recent-only; Vision `um/liquidationSnapshot` removed; OKX liquidation-orders span hours. Labeled **single-print**. OKX funding (~90d) and 1h OI scored; no #89-eligible row. Live `!forceOrder@arr` is not a backtest input. |
| #106 | Polymarket weather PIT (`traderstack-polymarket-weather-eval`) | no PIT tape | No public point-in-time CLOB mid + official station high. Using settlement as the decision mid is look-ahead. Committed run was `--empty-live`: 0 eligible rows. |
| #107 | Crucix fail-closed | safety only | Opted-in Crucix outage now rejects new risk with `intelligence_provider_unavailable`. Not a trading edge. Crucix stays off by default. |
| #108 | 4h non-EMA dual-print (`traderstack-intraday-dual-print`) | **0** passers | Kraken 4h combined-passers: **0** (every Kraken mean HO negative). Binance.US 4h combined-passers: **0**. OKX funding/OI were aligned and still did not produce a dual-print passer. |
| #116 | BTC−ETH residual (`traderstack-relative-value`) | **0** dual-print passers | Fade/follow daily `r_BTC − r_ETH` at frozen \|z\| ≥ 1.0 / 1.5 / 2.0. Kraken combined-passers: **0** (every RV mean HO negative, −5.49% to −15.64%). Binance.US combined-passers: **0**. Paper path ready; still cannot promote. |
| #117 | Cross-sectional momentum (`traderstack-xs-momentum`) | **0** dual-print passers | Long top-1 / optional short bottom-1 among {BTC,ETH,SOL} at frozen N in {21,63,126} (`ls`/`lo`, optional vol-scaled ranking). Kraken combined-passers: **0**. Binance.US combined-passers: **0**. Informational `xs_mom_lo_vol_63` mean HO +7.13% / +9.55% still fails #96 (BTC HO −16.52%). Paper path ready; still cannot promote. |
| #118 | Donchian / channel breakout (`traderstack-donchian-breakout`) | **0** dual-print passers | Frozen `donchian_lo/ls_{20,55,100}` + `donchian_lo_atr_{20,55}`. Kraken combined-passers: **0**. Binance.US combined-passers: **0**. Informational positive Kraken mean HO (`donchian_ls_20` +31.04%, `donchian_lo_20` +15.10%, `donchian_lo_atr_55` +6.04%) still fails #96 on BTC walk-forward (not ETH-carried holdout). Paper path ready; still cannot promote. |
| #119 | Time-series momentum (`traderstack-tsmom`) | **0** dual-print passers | Frozen `tsmom_lo/ls_{21,63,126,252}`. Kraken combined-passers: **0**. Binance.US combined-passers: **0**. Informational #96 FAIL ETH-carried: `tsmom_lo_63` / `tsmom_ls_63`. Informational BTC WF-fail (positive mean HO and BTC HO): `tsmom_lo_21` / `tsmom_ls_21`. Paper path ready; still cannot promote. |
| #120 | Bollinger band-fade (`traderstack-bollinger-fade`) | **0** dual-print passers | Frozen `bb_fade_{20x2,20x2_5,40x2}` / `bb_lo_fade_{20x2,40x2}` / `bb_squeeze_break_{20,40}`. Kraken combined-passers: **0**. Binance.US combined-passers: **0**. #96 FAIL ETH-carried: **none**. BTC WF-fail: **none**. Informational `bb_squeeze_break_40` clears Kraken #96+A+B (mean HO +3.72%) but fails gate C; Binance #96 FAIL (BTC HO −4.69%). Paper path ready; still cannot promote. |
| #121 | Calendar seasonality (`traderstack-calendar-seasonality`) | **0** dual-print passers | Frozen `cal_dow_lo_{mon,fri,mon_fri}` / `cal_dow_skip_weekend` / `cal_moy_lo_{q4,jan,nov_dec}` / `cal_tom_lo_3_3`. Kraken combined-passers: **0**. Binance.US combined-passers: **0**. #96 FAIL ETH-carried: **none**. BTC WF-fail: **none**. Every Kraken mean HO negative (−5.24% to −26.42%). Paper path ready; still cannot promote. |
| #122 | BTC→ETH lead-lag (`traderstack-lead-lag`) | **0** dual-print passers | Frozen `leadlag_eth_follow_lo_{1,2,3,5}` / `leadlag_eth_follow_ls_{1,2,3}` / `leadlag_eth_fade_lo_{1,2,3}` / `leadlag_btc_follow_lo_{1,2}`. Kraken combined-passers: **0**. Binance.US combined-passers: **0**. Informational #96 FAIL ETH-carried: `leadlag_eth_follow_lo_5` (mean HO +6.67%; BTC HO −1.80%). BTC WF-fail: **none**. Other leg frozen flat. Paper path ready; still cannot promote. |
| this PR | Volume-confirmed breakout (`traderstack-volume-breakout`) | **0** dual-print passers | Frozen `volbrk_lo_{20x1_5,55x1_5,20x2}` / `volbrk_ls_{20x1_5,55x1_5}` / `volsurge_lo_{20x2,20x2_5}`. Not a Donchian N retune. Kraken combined-passers: **0**. Binance.US combined-passers: **0**. #96 FAIL ETH-carried: **none**. Informational BTC WF-fail: `volbrk_lo_20x1_5`, `volbrk_lo_20x2`, `volsurge_lo_20x2`, `volsurge_lo_20x2_5`. Paper path ready; still cannot promote. |

Earlier daily work (#93–#103) documented `ema_9_21` / `ema_9_21_adx15`
as paper-only pins. Those flags remain default **false**. The #102
second print and the #104 dual-print bar are why they stay off: the
independent print does not confirm.

## This session — funding / carry

`traderstack-funding-carry` is the next falsifiable family, not a
reprint of #104 or #108.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Funding-z threshold (spot signal) | `funding_z_fade_1_0`, `funding_z_fade_1_5`, `funding_z_fade_2_0`, `funding_z_follow_1_0`, `funding_z_follow_1_5`, `funding_z_follow_2_0` |
| Spot overlay | `ema_9_21_funding_agree`, `momentum_12_funding_agree` |
| Hedged carry (research model) | `carry_hedged_sign`, `carry_hedged_abs_1bp`, `carry_hedged_abs_3bp`, `carry_hedged_z_1_5` |
| Control (cannot promote) | `ma_cross_10_30` |

Hedged carry PnL is received |funding| minus two-leg (spot+perp) fees
on each flip. Perp-spot **basis is not invented** and is not in the
PnL. That family is **not** paper-spot executable.

### Print policy (frozen)

| print | when | can promote? |
| --- | --- | --- |
| single-print | only one usable funding venue on BTC+ETH | **no** |
| dual-print | two independent funding venues (e.g. Binance **and** OKX) | still no Settings flip |

A second candle venue without a second funding tape is not
dual-print. Splitting one OKX tape is the same venue.

Hard gates (#96+A+B+C) need 720 aligned **daily** bars. A ~90d OKX
funding overlap cannot unlock them; they are recorded UNAVAILABLE, not
faked.

### Live print (2026-09-12)

`traderstack-funding-carry --live` (Kraken public Spot 4h BTC+ETH,
720-bar cap 2026-05-15 16:00 → 2026-09-12 12:00 UTC; costs 10+5 bps).

| series | status |
| --- | --- |
| Binance USDT-M funding | **skipped** — HTTP 451 |
| OKX funding-rate-history | **ok** — 290 prints, 2026-06-08 08:00 → 2026-09-12 16:00 UTC (~90d of 8h) per BTC and ETH |
| Aligned 4h overlap | 578 bars (funding window; extra Kraken bars skipped, not invented) |
| Print kind | **single_print** (one venue / one history length) |
| Hard gates (#96+A+B+C) | **UNAVAILABLE** (need 1d and ≥720 aligned bars) |

Spot-signal / overlay (informational; every name **ineligible**):

| rank | id | WF excess | WF total | holdout excess |
| ---: | --- | ---: | ---: | ---: |
| 1 | `funding_z_follow_2_0` | −0.46% | −0.10% | −2.59% |
| 2 | `funding_z_fade_2_0` | −0.49% | −0.13% | −1.37% |
| 9 | `ma_cross_10_30` (control) | −3.50% | −3.14% | −11.24% |

Hedged carry (modeled; basis not invented; **not** paper-spot executable):

| id | WF total | holdout total | full-sample | eligible? |
| --- | ---: | ---: | ---: | :---: |
| `carry_hedged_sign` | +0.16% | +0.33% | +1.03% | yes* |
| `carry_hedged_abs_1bp` | −0.68% | −2.61% | −7.31% | no |
| `carry_hedged_abs_3bp` | +0.00% | +0.00% | +0.00% | no (never in) |
| `carry_hedged_z_1_5` | −3.22% | −3.49% | −18.28% | no |

\*Fee-aware signs > 0 on this one ~90d OKX tape. That is **not** dual-print,
not a hard-gate pass, not a basis-aware result, and **cannot promote**.

**No new `PAPER_PROMOTE_*` pin.** Single-print / cannot-promote is success.

See `funding-carry.md`.

## This session — second independent funding tape

Highest-leverage next experiment from the list below: find a **second
funding venue** that works from this environment, wire it
skip-not-invent, and re-run the frozen funding-carry dual-print bar.
Do not invent a series. Empty dual-print is success. No new
`PAPER_PROMOTE_*` pin unless a dual-print passer exists.

### Venue probe (this environment, 2026-09-12)

| venue | public path | result |
| --- | --- | --- |
| Binance USDT-M | `GET /fapi/v1/fundingRate` | **UNAVAILABLE** — HTTP 451 |
| Bybit linear | `GET /v5/market/funding/history` | **UNAVAILABLE** — HTTP 403 CloudFront country block |
| OKX swap | `GET /api/v5/public/funding-rate-history` | **ok** — ~90d of 8h prints (already wired) |
| Hyperliquid | `POST /info` `fundingHistory` | **ok** — hourly, paginable from 2023-05-12; BTC+ETH live |
| Deribit | `public/get_funding_rate_history` | reachable, **not wired** — `interest_8h` restated every hour; treating each row as a settlement would invent 8× carry |
| Gate USDT | `GET /futures/usdt/funding_rate` | reachable, **not wired** — default ~90 prints; `from` capped at 180d |
| Bitget USDT-M | `GET /api/v2/mix/market/history-fund-rate` | reachable, **not wired** — ~270 8h prints (~90d) |
| MEXC | `GET /contract/funding_rate/history` | reachable, **not wired** — ~1618 8h prints from 2025-03-22 |
| dYdX v4 indexer | `GET /v4/historicalFunding/{ticker}` | reachable, **not wired** — hourly; not needed once Hyperliquid covers dual-print |

Wired second tape: **Hyperliquid**. Bybit is probed and recorded as a
skip. Binance stays a skip. Other reachable CEX/DEX tapes are
documented, not blended.

### Live dual-print (2026-09-12)

`traderstack-funding-carry --live` after the Hyperliquid adapter.
Kraken public Spot 4h BTC+ETH, 720-bar cap (2026-05-15 16:00 →
2026-09-12 12:00 UTC). Costs 10+5 bps.

| series | status |
| --- | --- |
| Binance USDT-M funding | **skipped** — HTTP 451 |
| Bybit linear funding | **skipped** — HTTP 403 CloudFront |
| OKX funding | **ok** — 290 prints (~90d of 8h) per BTC and ETH |
| Hyperliquid funding | **ok** — 4320 hourly prints (180d lookback) per BTC and ETH |
| Print kind | **dual_print** (Hyperliquid primary, OKX second) |
| Hard gates | **UNAVAILABLE** (interval=4h; need 1d and ≥720 on two venues) |
| Spot-signal dual-print passers | **0** (every overlay lost after fees on both tapes) |
| Modeled dual-print passer | `carry_hedged_sign` only |

Spot-signal / overlay (Hyperliquid primary; every name **ineligible**):

| rank | id | WF excess | WF total | holdout excess |
| ---: | --- | ---: | ---: | ---: |
| 1 | `momentum_12_funding_agree` | −0.74% | −0.05% | −1.69% |
| 7 | `ma_cross_10_30` (control) | −1.78% | −1.10% | −12.57% |

OKX second print matches the earlier single-print tape (top-1
`funding_z_follow_2_0` WF excess −0.46%). No spot-signal name cleared
both.

Modeled hedged carry (basis not invented; **not** paper-spot executable):

| id | HL WF / HO / full | OKX WF / HO / full | both? |
| --- | ---: | ---: | :---: |
| `carry_hedged_sign` | +0.06% / +0.95% / +3.89% | +0.16% / +0.33% / +1.03% | yes* |
| `carry_hedged_abs_1bp` | +0.00% (never in; hourly abs(rate) typically <1bp) | −0.68% / −2.61% / −7.31% | no |
| `carry_hedged_abs_3bp` | +0.00% (never in) | +0.00% (never in) | no |
| `carry_hedged_z_1_5` | −2.66% / −24.03% / −84.47% | −3.22% / −3.49% / −18.28% | no |

\*Fee-aware signs > 0 on **both** independent tapes. That is still
not a hard-gate pass, not basis-aware, and **not paper-spot
executable**. Cadences differ (hourly vs 8h); the two full-sample
numbers are not the same bet. **Cannot promote. No new Settings pin**
— a pin would imply a paper path that does not exist.

See `funding-carry.md`.

## This session — daily resample / hard-gate honesty

Highest-leverage next step after #110: evaluate `carry_hedged_sign`
on a **daily** aligned series (UTC-day sums of settlements; empty
days omitted, never zero-filled) long enough for #96+A+B+C, or
document why the gates stay UNAVAILABLE. Explicitly skip basis
unless a PIT perp−spot series exists. Document the missing
paper-executable path. Still no Settings pin.

### Standing constraints (do not wish away)

- Hard gates need 720 aligned **daily** bars on **each** venue in a
  dual-print. Hyperliquid can cover a Kraken 720-bar daily window
  if enough `fundingHistory` pages are fetched (~800d lookback).
  OKX public history is still ~90d of 8h prints → ~90 daily sums.
- Hyperliquid `fundingHistory.premium` is the funding-formula input,
  **not** a PIT perp−spot mid. Last-trade is not basis. Skip.
- Paper fills are Kraken spot only (`paper_simulate_fills`). There
  is no paper perp simulator and no hedged spot+perp book.

### Live daily print (2026-09-12)

`traderstack-funding-carry --live --interval 1d` (Kraken public Spot
1d BTC+ETH, 720-bar cap 2024-09-22 → 2026-09-11 UTC; costs 10+5 bps).
Hyperliquid lookback 800d with 429 backoff. First attempt: BTC 19199
hourly ok, ETH HTTP 429 → venue dropped (skip-not-invent; not dual).
Retry with page/symbol pause: both coins 19199 hourly.

| series | status |
| --- | --- |
| Binance USDT-M funding | **skipped** — HTTP 451 |
| Bybit linear funding | **skipped** — HTTP 403 CloudFront |
| OKX funding | **ok** — 290 8h prints → **97** UTC daily sums per BTC and ETH |
| Hyperliquid funding | **ok** — 19199 hourly prints → **801** UTC daily sums per BTC and ETH |
| Print kind | **dual_print** (Hyperliquid primary, OKX second) |
| Aligned daily bars | primary **720** (Kraken ∩ HL); second **96** (Kraken ∩ OKX) |
| Hard gates (#96+A+B+C) | **UNAVAILABLE** (second venue 96 < 720) |
| Basis | **skipped** (no PIT perp−spot series) |
| Paper path | **false** (Kraken spot fills only) |
| Spot-signal dual-print passers | **0** |
| Modeled dual-print passers | **0** |

Spot-signal / overlay (Hyperliquid primary, 720 daily; every name
**ineligible**). Informational top-1 is the control:

| rank | id | WF excess | WF total | holdout excess |
| ---: | --- | ---: | ---: | ---: |
| 1 | `ma_cross_10_30` (control) | −4.41% | +7.80% | +4.94% |
| 2 | `funding_z_follow_1_5` | −7.71% | +4.50% | −20.64% |

OKX second-print spot overlays: all **n/a** (96 daily bars cannot
form a walk-forward fold). Skip, not a shorter bar.

Modeled hedged carry (basis skipped; **not** paper-spot executable):

| id | HL WF / HO / full | OKX WF / HO / full | both? |
| --- | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.72% / +3.32% / +27.70% | n/a / +0.31% / +0.94% | no |
| `carry_hedged_abs_1bp` | −1.36% / −8.17% / −18.98% | n/a / −0.93% / −5.82% | no |
| `carry_hedged_abs_3bp` | −2.42% / −4.82% / −21.50% | n/a / −0.57% / −1.38% | no |
| `carry_hedged_z_1_5` | −2.88% / −8.72% / −32.95% | n/a / −0.87% / −5.62% | no |

OKX daily WF is **n/a** (`walkforward_insufficient_prints`): 97
daily sums with a 20% holdout leave ~77 research prints, below the
frozen 80+40 short bar. Do not shorten the bar after seeing that.

Carry hard-gate analog (daily funding, not a Settings unlock):

| venue | available | #96 | A | B | C | combined |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| Hyperliquid (801 daily) | yes | true | true (ratio 0.87) | true (3/3) | true | **true** |
| OKX (97 daily) | **no** | — | — | — | — | UNAVAILABLE |

The long Hyperliquid tape can run #96+A+B+C and `carry_hedged_sign`
clears that analog **on one venue**. That is not dual-print, not
basis-aware, and not paper-executable. The 4h #110 dual-print
passer **does not survive** daily resample: OKX cannot form WF
folds. Empty dual-print set is success.

**Cannot promote. No new Settings pin.**

See `funding-carry-daily.md`.

## This session — second long settlement tape (BitMEX)

Highest-leverage next step after #111: find **one** additional public
funding history that can yield ≥720 UTC daily sums for BTC+ETH
without inventing cadence, wire it skip-not-invent, and re-run
`traderstack-funding-carry --live --interval 1d` with the two longest
usable venues. Empty dual-print is success. No `PAPER_PROMOTE_*`
flip unless hard gates + dual-print + PIT basis + paper path all
clear.

### Venue probe (this environment, 2026-09-12, after #111)

| venue | public path | result |
| --- | --- | --- |
| Binance USDT-M REST | `GET /fapi/v1/fundingRate` | **UNAVAILABLE** — HTTP 451 (already skipped) |
| Binance Vision | `data.binance.vision` monthly `fundingRate` zips | reachable (2020-01 and 2026-08 HTTP 200) — **not wired**; BitMEX already fills the 720-day bar without zip stitching |
| Bybit linear | `GET /v5/market/funding/history` | **UNAVAILABLE** — HTTP 403 CloudFront |
| OKX swap | `GET /api/v5/public/funding-rate-history` | **ok** — ~90d of 8h → ~97 daily (already wired; too short for hard gates) |
| Hyperliquid | `POST /info` `fundingHistory` | **ok** — hourly → 801 daily (already wired) |
| BitMEX | `GET /api/v1/funding` | **ok — wired** — XBTUSD from 2016-05-14, ETHUSD from 2018-08-02; 800d window = 2402 8h prints / **801 UTC days**, no day gaps. Uses `fundingRate` only |
| Deribit | `public/get_funding_rate_history` | reachable, **not wired** — `interest_8h` restated every hour (would invent 8×) |
| Gate USDT | `GET /futures/usdt/funding_rate` | reachable, **not wired** — `from` capped at 180d |
| HTX linear | `swap_historical_funding_rate` | reachable (~2150d) — **not wired**; one long tape is enough |
| KuCoin futures | `/contract/funding-rates` | reachable, short default page (~34d) — **not wired** |
| MEXC | `/contract/funding_rate/history` | reachable, shorter than 720 UTC days in #110 — **not wired** |
| dYdX v4 | `/v4/historicalFunding` | reachable hourly — **not wired** |
| Kraken Futures | `/derivatives/api/v3/historicalfundingrates` | **UNAVAILABLE** — HTTP 404 from this environment |
| Coinbase International | `/api/v1/instruments/{id}/funding` | reachable hourly snapshots — **not wired** (cadence not a settlement tape) |

Wired long second tape: **BitMEX**. `_pick_venues` still prefers the
two longest usable tapes by mean print count (Hyperliquid hourly
then BitMEX 8h). OKX stays a documented short tape, not blended.

### Live daily print (2026-09-12, after BitMEX)

`traderstack-funding-carry --live --interval 1d` (Kraken public Spot
1d BTC+ETH, 720-bar cap 2024-09-22 → 2026-09-11 UTC; costs 10+5 bps).

| series | status |
| --- | --- |
| Binance USDT-M funding | **skipped** — HTTP 451 |
| Bybit linear funding | **skipped** — HTTP 403 CloudFront |
| OKX funding | **ok** — 290 8h → 97 UTC daily (not selected; shorter than BitMEX) |
| Hyperliquid funding | **ok** — 19199 hourly → **801** UTC daily sums |
| BitMEX funding | **ok** — 2400 8h settlements → **801** UTC daily sums |
| Print kind | **dual_print** (Hyperliquid primary, BitMEX second) |
| Aligned daily bars | primary **720** / second **720** |
| Hard gates (#96+A+B+C) | **available** (both venues ≥720) |
| Basis | **skipped** (no PIT perp−spot series) |
| Paper path | **false** (Kraken spot fills only) |
| Spot-signal dual-print passers | **0** |
| Modeled dual-print passers | `carry_hedged_sign` only |

Spot-signal / overlay (every name **ineligible** on both tapes).
Informational top-1 is the control on both:

| venue | top-1 | WF excess | WF total | holdout excess |
| --- | --- | ---: | ---: | ---: |
| Hyperliquid | `ma_cross_10_30` (control) | −4.41% | +7.80% | +4.94% |
| BitMEX | `ma_cross_10_30` (control) | −4.41% | +7.80% | +4.94% |

Modeled hedged carry (basis skipped; **not** paper-spot executable):

| id | HL WF / HO / full | BitMEX WF / HO / full | both? |
| --- | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.72% / +3.32% / +27.70% | +2.55% / +5.32% / +46.46% | yes* |
| `carry_hedged_abs_1bp` | −1.36% / −8.17% / −18.98% | +0.20% / −3.80% / +16.24% | no |
| `carry_hedged_abs_3bp` | −2.42% / −4.82% / −21.50% | −0.25% / −3.45% / +13.62% | no |
| `carry_hedged_z_1_5` | −2.88% / −8.72% / −32.95% | −2.91% / −7.43% / −29.75% | no |

\*Fee-aware signs > 0 on **both** independent daily tapes. The 4h #110
passer **survives** daily resample once the second tape is long enough
for walk-forward folds.

Carry hard-gate analog (daily funding, not a Settings unlock):

| venue | available | #96 | A | B | C | combined |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| Hyperliquid (801 daily) | yes | true | true (ratio 0.87) | true (3/3) | true | **true** |
| BitMEX (801 daily) | yes | true | true (ratio 0.46) | true (3/3) | true | **true** |

Dual-print **and** hard gates are now honest. That is still **not**
basis-aware and **not** paper-executable. `can_promote` stays false.
**Cannot promote. No new Settings pin.**

See `funding-carry-daily.md`.

## This session — PIT basis probe + paper perp stub

Highest-leverage next step after #112: close the two remaining
honesty gaps. Do not invent basis. Do not flip `PAPER_PROMOTE_*`.
If carry would have to be re-scored on an invented series, skip.

### A — PIT basis (UNAVAILABLE on both venues)

Probed 2026-09-12 from this environment. Requested construction:
**mark−index** or **perp-mid−spot-mid**, timestamps that do not look
ahead. Hyperliquid `premium` remains forbidden.

| venue | what exists | why it is not PIT basis |
| --- | --- | --- |
| Hyperliquid `POST /info` `metaAndAssetCtxs` | **current** `markPx` / `oraclePx` / `midPx` (BTC mark 77130 / oracle 77172.1 at probe) | snapshot only; no historical REST |
| Hyperliquid `fundingHistory` | hourly `fundingRate` + `premium` | `premium` is the funding-formula input, not a PIT perp−spot mid |
| Hyperliquid `candleSnapshot` | last-trade OHLC | last-trade is not mid |
| BitMEX `GET /instrument` | **current** `markPrice` / `indicativeSettlePrice` / `midPrice` | snapshot only |
| BitMEX `.XBTUSDPI` / `.ETHUSDPI` `trade/bucketed` | historical premium index (minute prints; 1d close −0.000299 on 2026-09-12) | funding-formula premium, same class as HL `premium` — not wired |
| BitMEX `quote/bucketed` XBTUSD + `.BXBT` / `.BETH` | perp quote mid and composite index | perp-mid−**index**, not mark−index and not perp-mid−**spot-mid**; HL cannot pair it |

Wired: `fetch_hyperliquid_basis` and `fetch_bitmex_basis`. Both
return **skipped** with the probe reason. `--live` appends those
notes. `basis_status` stays `skipped`. `carry_hedged_sign` is **not
re-scored** with a fabricated series. The #112 daily numbers
(HL WF +1.72% / BitMEX +2.55%) are still the basis-unaware model.

**Cannot unlock `basis_status=ok`. Cannot promote.**

See `funding-carry-basis.md`.

### B — paper perp / hedge stub (not promote-ready)

`src/traderstack/execution/paper_perp.py` is a paper-only book:

- refuses `live` / `shadow`;
- kill switch withholds new hedges and funding;
- hedges a spot paper fill only when an **explicit perp mid** is
  supplied (Kraken spot mid is not a substitute);
- applies funding credit/debit only from caller-supplied settlement
  prints (positive rate: longs pay shorts);
- writes the client order id before the simulated hedge fill;
- does **not** book perp PnL into the spot portfolio.

`PAPER_PERP_HEDGE` (default **false**) opts the stub into
`traderstack-paper`. After #113 the cycle still passed
`perp_mid_usd=None`, so production hedges skipped.
`PAPER_CARRY_PATH_READY` stayed **false**. `can_promote` stayed
**false**. No new Settings pin.

### Still blocked (after #113)

`can_promote` requires dual-print ∧ hard gates ∧ PIT basis ∧ paper
path. After #113: dual-print **true**, hard gates **true**, basis
**UNAVAILABLE**, paper path **stub / not ready**.

## This session — paper hedge+funding soak path

Highest-leverage next step after #113: close the paper-path honesty
gap without inventing historical PIT basis.

### What was wired

When `PAPER_PERP_HEDGE=true` and `TRADING_MODE=paper`:

1. The cycle fetches an **explicit current** perp mid from
   Hyperliquid `metaAndAssetCtxs.midPx` and/or BitMEX
   `/instrument.midPrice` for BTC/ETH.
2. That mid is passed into `PaperPerpBook.maybe_hedge_spot_fill`.
   The Kraken spot mid is **never** substituted. `markPx` /
   last-trade / funding premium are not mids and are not fallbacks.
3. Funding credit/debit is applied only from the **same venue's**
   public funding tape (HL `fundingHistory` or BitMEX `/funding`
   `fundingRate`), and only prints strictly after the hedge.
   Missing tape → skip, not invent.

`PAPER_PERP_HEDGE` still defaults **false**. No live. No
`PAPER_PROMOTE_*` flip.

### What was not wired

Current snapshot mids are **not** a historical mark−index or
perp-mid−spot-mid series. Writing them into
`traderstack-funding-carry` would invent PIT basis the venues do
not publish. Research `basis_status` stays **skipped**. Carry was
**not** re-scored. The #112 daily numbers stay the basis-unaware
model.

### Readiness

| flag | value | meaning |
| --- | --- | --- |
| `PAPER_CARRY_PATH_READY` | **true** | hedge+funding paper path is cycle-wired and exercised with real mid+funding inputs |
| `can_promote` | **false** | dual-print ∧ hard gates are true; PIT basis is still UNAVAILABLE |
| `PAPER_PERP_HEDGE` | **false** (default) | operator opt-in for forward paper soaks |
| `PAPER_PROMOTE_*` | **false** | no pin |

Promote remains blocked on basis.

See `funding-carry-basis.md`.

## This session — public PIT basis archives

Highest-leverage next step after #114: find a **public historical
archive** (not another live REST snapshot) that supplies mark−index
or perp-mid−spot-mid for Hyperliquid and/or BitMEX over ≥720 days,
without paid credentials. If found, wire skip-not-invent and
re-score `carry_hedged_sign`. If not, document UNAVAILABLE.

### Archive probe (this environment, 2026-09-12)

| source | result |
| --- | --- |
| `s3://hyperliquid-archive/asset_ctxs` | **UNAVAILABLE** — requester-pays; anonymous HTTP 403; `AWS_ACCESS_KEY_ID` unset. Docs claim daily files from 2023-05-20; columns not confirmed here. Do not invent AWS keys. |
| `s3://hl-mainnet-node-data` / Hydromancer Reservoir | **UNAVAILABLE** — same 403 requester-pays |
| `public.bitmex.com` `data/` | trade + quote + porl only. `data/instrument/` **404**. Quote ≠ mark−index. |
| BitMEX `XBTUSDT` mid − `XBT_USDT` mid | calendar >720d from 2022-05-17, **not used**: spot 1d spread 150–603 bps (ETH 3473–3725 bps) |
| Tardis | unauthorized except first-of-month samples; HL since 2024-10-29 (~318d < 720) |
| Coin Metrics community | HTTP 403 |
| HuggingFace `GregM/hyperliquid-perp-open-data` | schema only; no rows |
| CryptoDataDownload `/data/bitmex/` | HTTP 404 |

**No fetcher wired. Carry not re-scored.** See
`pit-basis-archives.md`.

`can_promote` still requires dual-print ∧ hard gates ∧ PIT basis ∧
paper path. After this session: dual-print **true**, hard gates
**true**, paper soak **true**, basis **UNAVAILABLE**.

## Next falsifiable experiments

Do not rerun #104 / #105 / #106 / #108 / the 4h #110 funding print
on the same windows. Do not rerun the #111 daily print with only
OKX as the second tape. Do not re-score carry on HL `premium` or
BitMEX `.XBTUSDPI`. Do not rerun this BTC−ETH residual catalog or the
BTC+ETH+SOL cross-sectional momentum catalog or the Donchian /
channel-breakout catalog or the time-series momentum catalog or
the Bollinger band-fade catalog or the calendar seasonality
catalog or the BTC→ETH lead-lag catalog on the same Kraken
720 + Binance.US older-720 windows.
Do not reprint `mean_reversion_*` ids. Do not invent a
same-bar residual z-score reprint of #116. Do not retune
Donchian N after seeing #118.

1. **Second independent funding tape.** Done in #110: Hyperliquid +
   OKX dual-print. Spot-signal passers: **0**. Modeled
   `carry_hedged_sign` cleared fee-aware signs on both 4h-aligned
   tapes and still cannot promote.
2. **Daily resample / #96+A+B+C honesty.** Done in #111. See above
   and `funding-carry-daily.md`.
3. **Second long settlement tape.** Done in #112 with BitMEX (now a
   **sunset** venue — official closure 23 September 2026 04:00 UTC).
   Replacement hunt: **HTX** is the wired long tape. Daily
   dual-print without BitMEX is Hyperliquid + HTX. Modeled
   `carry_hedged_sign` on the #112 HL+BitMEX print still cannot
   promote (basis skipped).
4. **Basis-aware carry.** REST probe (#113) and first archive
   probe (#115) were **UNAVAILABLE**. Re-hunt after #123 (#124):
   Hyperliquid now has a public ≥720d mark−index tape
   (`asiletto81/hyperliquid` `asset_ctxs`, 883 contiguous days,
   `mark_px`/`oracle_px` confirmed) that ends 2026-06-01 (~617d on
   the current Kraken 720). HTX daily mark−index is wired (single
   venue). BitMEX is closing and still has no free ≥720d tape
   (spot book still 150–600 / ~3500 bps; not a mid). Dual-print
   basis stays **UNAVAILABLE** on this window. Next only when HL
   mark−index covers the scored 720 days without invented
   AWS/Tardis/Dune keys and without retuning the window. Do not
   invent from last-trade or from funding. Do not stitch Tardis
   first-of-month samples.
5. **Paper-executable path (still `TRADING_MODE=paper`).** Done in
   #114. `PAPER_CARRY_PATH_READY` is true for the soak. Promote
   still blocked on historical PIT basis. Do not add a Settings pin.
6. **BTC−ETH relative-value residual.** Done in #116. See
   `btc-eth-relative-value.md`. Dual-print passers: **0**.
7. **BTC+ETH+SOL cross-sectional momentum.** Done this session. See
   below and `cross-sectional-momentum.md`. Dual-print passers: **0**.
8. **Not** another daily-EMA catalog expansion on the same Kraken 720
   + Binance.US older-720 pair.
9. **Not** a residual lookback / |z| retune on the same windows
   after seeing the #116 print.
10. **Not** an N / vol-lookback retune of this cross-section on the
    same windows after seeing this print.
11. **Donchian / channel breakout.** Done this session. See below
    and `donchian-breakout.md`. Dual-print passers: **0**.
12. **Not** a Donchian N / ATR-period retune on the same windows
    after seeing that print.
13. **Time-series momentum (own-asset trailing return).** Done this
    session. See below and `tsmom.md`. Dual-print passers: **0**.
14. **Not** a TSMOM N retune on the same windows after seeing that
    print.
15. **Not** liquidation-conditioned promotion until a public historical
    liquidation aggregate exists (it does not today).
16. **Not** Polymarket weather promotion until a PIT CLOB mid +
    official station-high tape exists (it does not today).
17. **Bollinger band-fade / mean-reversion.** Done this session.
    See below and `bollinger-fade.md`. Dual-print passers: **0**.
18. **Not** a Bollinger period / k / squeeze-percentile retune on
    the same windows after seeing this print.
19. **Calendar seasonality (UTC DOW / MOY / turn-of-month).**
    Done this session. See below and
    `calendar-seasonality.md`. Dual-print passers: **0**.
20. **Not** a calendar weekday / month / N,M retune on the same
    windows after seeing that print.
21. **BTC→ETH lead-lag (ETH follows lagged BTC).** Done this
    session. See below and `lead-lag.md`. Dual-print
    passers: **0**. Not a residual z-score reprint of #116.
22. **Not** an L / book retune of this lead-lag catalog on the
    same windows after seeing that print.
23. **Volume-confirmed breakout (price + volume gate).** Done
    this session. See below and `volume-breakout.md`. Dual-print
    passers: **0**. Not a Donchian N retune of #118.
24. **Not** an N / V / vol_mult retune of this volume-breakout
    catalog on the same windows after seeing that print.
25. **PIT basis archive re-hunt (after #123 / #124).** Done.
    See below and `pit-basis-archives.md`. Dual-print basis still
    **UNAVAILABLE** (HL tape found; BitMEX missing). Carry not
    re-scored. No fetcher for a paired basis score. No pin.
26. **BitMEX sunset replacement.** HTX is the wired funding
    replacement. Official closure 23 September 2026 04:00 UTC.
    Dual-print basis still **UNAVAILABLE** on the current Kraken
    720. Carry not re-scored with invented basis. No pin.
27. **Not** a BitMEX-dependent paper soak, promote path, or new
    fetcher.

## This session — BTC→ETH lead-lag (catalog frozen)

Highest-leverage next experiment from #121: a **non-EMA /
non-residual / non-XS / non-Donchian / non-TSMOM /
non-Bollinger / non-calendar** family that is
paper-executable on Kraken spot. ETH position follows
**lagged BTC** return — not same-bar residual z-score on
`r_BTC − r_ETH` (#116). Catalog and dual-print bar are
frozen **before** any live OHLC pull. Do not retune L after
seeing PnL. Do not re-run #104 / #108 / #116 / #117 / #118
/ #119 / #120 / #121 on the same windows. Do not invent
PIT basis.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Follow long-only ETH on BTC L-day return > 0 | `leadlag_eth_follow_lo_{1,2,3,5}` |
| Follow long/short ETH on sign of BTC L-day return | `leadlag_eth_follow_ls_{1,2,3}` |
| Fade long-only ETH when BTC L-day return < 0 | `leadlag_eth_fade_lo_{1,2,3}` |
| Mirror: BTC follows lagged ETH long-only | `leadlag_btc_follow_lo_{1,2}` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: at aligned pair-day t the lead return is
`lead_close[t] / lead_close[t−L] − 1` (`lead_closes_through_t`).
L ≥ 1, so when trading ETH the gate does **not** use
same-bar ETH. Fill at t+1 open of the **traded** asset.
Unpaired BTC/ETH days skipped, not zero-filled.

### Multi-asset bar (frozen)

`btc_eth_both_legs_96_abc_other_leg_flat`: every catalog id
produces a BTC book and an ETH book. ETH-traded names run
the lead-lag rule on ETH and keep BTC **flat**. BTC-traded
mirror names run the lead-lag rule on BTC and keep ETH
**flat**. Combined #96+A+B+C still requires **both** legs
(standing #96). The other leg is not `ma_cross_10_30` and
not own-asset TSMOM. Equal-weight portfolio metrics were
considered and **rejected** before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-lead-lag --live` (Kraken public Spot 1d BTC+ETH,
720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US older-720
2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps). Catalog
frozen in a prior commit before this pull. Aligned pair-days:
720 / 720.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD daily | **ok** — 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT older-720 | **ok** — 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |
| #96 FAIL ETH-carried informational names | `leadlag_eth_follow_lo_5` |
| Informational BTC walk-forward fails | **none** |

Informational (every name **ineligible**; rank is Kraken
walk-forward among lead-lag names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `leadlag_eth_follow_ls_3` | −11.50% | +21.06% |
| 5 | `leadlag_eth_follow_lo_5` | +6.67% | +8.28% |
| 13 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

`leadlag_eth_follow_lo_5` is the only lead-lag name with a
**positive** Kraken mean HO (+6.67%; Binance +8.28%). BTC
holdout −1.80% / ETH +15.14% — the mean is ETH-carried.
ETH-traded names keep BTC **flat**, so the BTC holdout is
flat-vs-buy-and-hold (same −1.80% on every ETH-traded
name). That is **#96 FAIL**, not a combined-passer. A
positive mean with a losing BTC holdout is not an edge.

A positive Binance holdout with a losing Kraken holdout
(most follow-ls / follow-lo names except `_5`) is also
not an edge. Empty dual-print set is success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `lead-lag.md`.

## This session — volume-confirmed breakout (catalog frozen)

Highest-leverage next experiment from #122: a **non-EMA /
non-residual / non-XS / non-Donchian / non-TSMOM /
non-Bollinger / non-calendar / non-lead-lag** family that
is paper-executable on Kraken spot. Price breakout **and**
a volume gate. **Not** a Donchian N retune (#118). Catalog
and dual-print bar are frozen **before** any live OHLC
pull. Do not retune N / V / vol_mult after seeing PnL. Do
not re-run #104 / #108 / #116 / #117 / #118 / #119 / #120
/ #121 / #122 on the same windows. Do not invent PIT
basis. Missing volume is skipped, never invented.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Long-only: close > prior N-day high **and** volume > V-day SMA × mult; exit close < prior N-day low | `volbrk_lo_{20x1_5,55x1_5,20x2}` |
| Long/short symmetric with the same volume gate | `volbrk_ls_{20x1_5,55x1_5}` |
| Volume surge only (long when vol > SMA×mult and close > prior close) | `volsurge_lo_{20x2,20x2_5}` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: prior channel uses bars `[t-N, t)` (no look-ahead
into t's high). Volume SMA through t−1
(`volume_sma_through_t_minus_1`; V frozen at 20). Fill at
t+1 open. Missing / non-positive volume skips that bar.
Quote volume is not substituted. A venue without usable
base volume fails closed for volume names.

### Multi-asset bar (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: #96+A+B+C on
BTC and ETH. SOL is reported when present and is **not** a gate.
Equal-weight portfolio metrics were considered and **rejected**
before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-volume-breakout --live` (Kraken public Spot 1d
BTC+ETH+SOL, 720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US
older-720 2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps).
Catalog frozen in a prior commit before this pull. Base volume
usable on both venues (720/720 per asset). Quote volume was not
substituted.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD + SOL/USD daily | **ok** — 720 / 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT + SOLUSDT older-720 | **ok** — 720 / 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH; SOL optional) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |
| #96 FAIL ETH-carried informational names | **none** |
| Informational BTC walk-forward fails | `volbrk_lo_20x1_5`, `volbrk_lo_20x2`, `volsurge_lo_20x2`, `volsurge_lo_20x2_5` |

Informational (every name **ineligible**; rank is Kraken
walk-forward among volume-confirmed names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `volbrk_lo_55x1_5` | −1.16% | −0.40% |
| 3 | `volbrk_lo_20x2` | +5.22% | −6.49% |
| 4 | `volsurge_lo_20x2_5` | +3.87% | +4.57% |
| 5 | `volsurge_lo_20x2` | +3.87% | +3.75% |
| 7 | `volbrk_lo_20x1_5` | +1.52% | −2.05% |
| 2 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

Four names have a **positive** Kraken mean HO and **positive**
BTC holdout (`volbrk_lo_20x2` +5.22% / BTC HO +7.69%;
`volsurge_lo_{20x2,20x2_5}` +3.87% / BTC HO +9.14%;
`volbrk_lo_20x1_5` +1.52% / BTC HO +7.69%) but BTC
walk-forward is negative. Same honesty as #118 Donchian /
#119 TSMOM. `volsurge_lo_*` ETH holdout is also negative
(−1.41%). That is **#96 FAIL** on BTC walk-forward (and ETH
holdout for the surge names), not a combined-passer. A
positive holdout with a losing walk-forward is not an edge.
Empty dual-print set is success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `volume-breakout.md`.

## This session — PIT basis archive re-hunt (after #123)

Highest-leverage next step after the empty #123 volume print:
re-hunt public PIT basis archives that could unlock
basis-aware scoring of modeled `carry_hedged_sign`. #123
volume-confirmed breakout dual-print passers: **0**. Do not
re-run that catalog or #104 / #108 / #116–#122 on the same
windows. Do not flip `PAPER_PROMOTE_*`. Empty / still
UNAVAILABLE is success.

### What changed vs #115

HuggingFace `asiletto81/hyperliquid` now publishes official-shape
daily `asset_ctxs/YYYYMMDD.csv.lz4` that this environment can
GET without AWS keys. Probe (2026-09-12): **883 contiguous
days** 2024-01-01 → 2026-06-01, 0 gaps. Decompressed header
includes `mark_px` and `oracle_px` (not last-trade). BTC and
ETH minute rows confirmed on the first and last files. That
is a real ≥720d Hyperliquid mark−index tape.

BitMEX still has no matching free tape. Public dump prefixes
`data/instrument/`, `data/mark/`, `data/funding/` list **200**
but are empty. Spot 1d spreads remain **150–603 bps**
(`XBT_USDT`) and **~3500 bps** (`ETH_USDT`). Tardis
`derivative_ticker` first-of-month CSVs have `mark_price` and
`index_price` on **both** venues and are not a ≥720d daily
tape; full history needs a key that is not invented. Coin
Metrics / Dune / AlgoTick / requester-pays S3 stay closed.

Chainticks/perp-data is now populated (was schema-only in
#115) with true mark/index columns, but only **345**
contiguous days (2023-05-20 → 2024-04-28). Below the 720-day
bar.

### Decision

**No fetcher wired. Carry not re-scored.** Dual-print basis
requires the requested construction on **both** venues.
`basis_status` stays `skipped`. `can_promote` stays **false**.
No `PAPER_PROMOTE_*` flip. No live.

Operator recommendation from #124: still blocked on dual-print
basis (HL tape found; BitMEX missing). **Superseded for
funding:** BitMEX is closing 23 September 2026 04:00 UTC; HTX
is the wired replacement long tape. Next basis gate is an HL
mark−index that covers the scored 720 days (the archive ends
2026-06-01 / ~617d aligned) so it can pair with HTX. Do not
retune the window. Until then leave every pin **false**.

See `pit-basis-archives.md`.

## This session — BTC−ETH relative-value residual

Highest-leverage next experiment from #115: a **non-carry** family
that is paper-executable on Kraken spot. Catalog and dual-print bar
were frozen **before** the live pull. Not an EMA reprint. PIT basis
was not invented.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Residual fade | `rv_fade_1_0`, `rv_fade_1_5`, `rv_fade_2_0` |
| Residual follow | `rv_follow_1_0`, `rv_follow_1_5`, `rv_follow_2_0` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: daily close-to-close excess `r_BTC − r_ETH`, z-scored
over lookback 20. ETH sees the negated residual. Unpaired days
skipped, not zero-filled. Decision at bar t; fill at t+1 open.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-relative-value --live` (Kraken public Spot 1d BTC+ETH,
720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US older-720
2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps). Residual
719 aligned pair-days on each venue.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD daily | **ok** — 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT older-720 | **ok** — 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |

Informational (every name **ineligible**; Kraken mean HO all
negative; rank is Kraken walk-forward among RV names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `rv_follow_2_0` | −7.11% | +6.12% |
| 2 | `rv_follow_1_5` | −5.49% | +2.81% |
| 3 | `rv_fade_2_0` | −6.50% | −1.02% |
| 7 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

A positive Binance holdout with a losing Kraken holdout is not an
edge. A Kraken-only combined-passer did not appear either.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.** Empty dual-print
set is success.

See `btc-eth-relative-value.md`.

## This session — BTC+ETH+SOL cross-sectional momentum

Highest-leverage next experiment from #116: a **non-carry /
non-residual** family that is paper-executable on Kraken spot.
Catalog and dual-print bar were frozen **before** the live pull.
Not an EMA reprint. Not a residual lookback retune.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Dollar-neutral long top-1 / short bottom-1 | `xs_mom_ls_21`, `xs_mom_ls_63`, `xs_mom_ls_126` |
| Long-only top-1 | `xs_mom_lo_21`, `xs_mom_lo_63`, `xs_mom_lo_126` |
| Vol-scaled ranking (same books) | `xs_mom_ls_vol_*`, `xs_mom_lo_vol_*` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: trailing N-day close-to-close return among {BTC, ETH,
SOL}. `vol` names rank by return / sample vol over the same N
(ranking transform, not a size overlay). A ranking day needs all
three venue-local closes. Missing-asset days skipped, not ranked
on a two-asset subset. Decision at bar t; fill at t+1 open.

### Multi-asset bar (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: #96+A+B+C on
BTC and ETH. SOL is reported and is **not** a gate. Equal-weight
portfolio metrics were considered and **rejected** before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-xs-momentum --live` (Kraken public Spot 1d BTC+ETH+SOL,
720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US older-720
2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps). Aligned
triple-days: 720 / 720.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD + SOL/USD daily | **ok** — 720 / 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT + SOLUSDT older-720 | **ok** — 720 / 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH/SOL) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |

Informational (every name **ineligible**; rank is Kraken
walk-forward among XS names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `xs_mom_lo_126` | −12.12% | −7.06% |
| 7 | `xs_mom_lo_vol_63` | +7.13% | +9.55% |
| 13 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

`xs_mom_lo_vol_63` is the only XS name with a positive Kraken
mean HO (+7.13%; Binance +9.55%). BTC holdout −16.52% / ETH
+30.78% — the mean is ETH-carried. That is **#96 FAIL**, not a
combined-passer. A positive mean with a losing BTC holdout is
not an edge. Empty dual-print set is success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `cross-sectional-momentum.md`.

## This session — Donchian / channel breakout (catalog frozen)

Highest-leverage next experiment from #117: a **non-EMA / non-residual
/ non-XS** family that is paper-executable on Kraken spot. Catalog
and dual-print bar are frozen **before** any live OHLC pull. Do not
retune N or ATR after seeing PnL. Do not re-run #104 / #108 / #116 /
#117 on the same windows. Do not invent PIT basis.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Long-only breakout | `donchian_lo_{20,55,100}` |
| Long/short symmetric | `donchian_ls_{20,55,100}` |
| ATR-buffered long-only (ATR 14 × 1.0) | `donchian_lo_atr_{20,55}` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: close[t] vs prior N-day high/low (bars `[t-N, t)`; no
look-ahead into t's high/low). Exit `opposite_band_same_n`. Fill at
t+1 open. ATR uses Wilder ATR(14) through t−1.

### Multi-asset bar (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: #96+A+B+C on
BTC and ETH. SOL is reported when present and is **not** a gate.
Equal-weight portfolio metrics were considered and **rejected**
before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-donchian-breakout --live` (Kraken public Spot 1d
BTC+ETH+SOL, 720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US
older-720 2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps).
Catalog frozen in a prior commit before this pull.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD + SOL/USD daily | **ok** — 720 / 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT + SOLUSDT older-720 | **ok** — 720 / 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH; SOL optional) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |
| #96 FAIL ETH-carried informational names | **none** |

Informational (every name **ineligible**; rank is Kraken
walk-forward among Donchian names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `donchian_lo_55` | −12.58% | −0.40% |
| 4 | `donchian_lo_atr_55` | +6.04% | −6.40% |
| 7 | `donchian_lo_20` | +15.10% | −9.35% |
| 9 | `donchian_ls_20` | +31.04% | −23.75% |
| 3 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

Three names have a **positive** Kraken mean HO
(`donchian_ls_20` +31.04%, `donchian_lo_20` +15.10%,
`donchian_lo_atr_55` +6.04%) and **positive BTC holdout**. That is
**not** the ETH-carried #96 FAIL pattern from `xs_mom_lo_vol_63`
in #117. They still fail #96 because BTC walk-forward total is
negative (and Binance holdout is negative). A positive holdout
with a losing walk-forward is not an edge. Empty dual-print set
is success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `donchian-breakout.md`.

## This session — time-series momentum (catalog frozen)

Highest-leverage next experiment from #118: a **non-EMA /
non-residual / non-XS / non-Donchian** family that is
paper-executable on Kraken spot. Catalog and dual-print bar were
frozen **before** the live OHLC pull. Do not retune N after
seeing PnL. Do not re-run #104 / #108 / #116 / #117 / #118 on
the same windows. Do not invent PIT basis.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Long-only (return > 0 else flat) | `tsmom_lo_{21,63,126,252}` |
| Long/short (sign of return) | `tsmom_ls_{21,63,126,252}` |
| Control (cannot promote) | `ma_cross_10_30` |

Vol-scaled sign variants (`tsmom_*_vol_*`) are **omitted**:
`sign(return/vol)` equals `sign(return)` whenever vol > 0, so
those ids would be duplicates. A `return/vol` size overlay would
be GARCH-class sizing and is out of scope. Do not add either
after seeing PnL.

Treatment: each asset uses **its own** trailing N-day
close-to-close return (`closes_through_t`: close[t] / close[t−N]
− 1). Fill at t+1 open. Missing series skipped, not zero-filled.

### Multi-asset bar (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: #96+A+B+C on
BTC and ETH. SOL is reported when present and is **not** a gate.
Equal-weight portfolio metrics were considered and **rejected**
before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-tsmom --live` (Kraken public Spot 1d BTC+ETH+SOL,
720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US older-720
2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps). Catalog
frozen in a prior commit before this pull.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD + SOL/USD daily | **ok** — 720 / 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT + SOLUSDT older-720 | **ok** — 720 / 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH; SOL optional) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |
| #96 FAIL ETH-carried informational names | `tsmom_lo_63`, `tsmom_ls_63` |
| Informational BTC walk-forward fails | `tsmom_lo_21`, `tsmom_ls_21` |

Informational (every name **ineligible**; rank is Kraken
walk-forward among TSMOM names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `tsmom_ls_21` | +6.64% | −31.17% |
| 2 | `tsmom_lo_21` | +7.32% | −14.64% |
| 3 | `tsmom_lo_63` | +2.61% | −9.99% |
| 4 | `tsmom_ls_63` | +6.29% | −25.10% |
| 9 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

`tsmom_lo_63` / `tsmom_ls_63` have a **positive** Kraken mean HO
(+2.61% / +6.29%) with BTC holdout −7.12% / −13.74% — the mean
is ETH-carried. That is **#96 FAIL**, not a combined-passer.

`tsmom_lo_21` / `tsmom_ls_21` have a **positive** Kraken mean HO
(+7.32% / +6.64%) and **positive BTC holdout** (+9.15% /
+16.79%) but BTC walk-forward −1.71% / −3.75%. Same honesty as
#118 Donchian. A positive holdout with a losing walk-forward is
not an edge. `tsmom_ls_21` ETH holdout is also negative
(−3.52%). Empty dual-print set is success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `tsmom.md`.

## This session — Bollinger band-fade (catalog frozen)

Highest-leverage next experiment from #119: a **non-EMA /
non-residual / non-XS / non-Donchian / non-TSMOM** family that
is paper-executable on Kraken spot. Catalog and dual-print bar
are frozen **before** any live OHLC pull. Do not retune period,
k, exit rule, or squeeze percentile after seeing PnL. Do not
re-run #104 / #108 / #116 / #117 / #118 / #119 on the same
windows. Do not invent PIT basis. Distinct from existing
`mean_reversion_*` catalog ids (#93 / #108 used different bars).

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Fade to mid | `bb_fade_{20x2,20x2_5,40x2}` |
| Long-only fade | `bb_lo_fade_{20x2,40x2}` |
| Squeeze-breakout CONTRAST | `bb_squeeze_break_{20,40}` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: SMA(period) ± k × sample stdev (ddof=1) using closes
through t. Exit `flat_when_inside_bands` (not exit-at-mid).
Squeeze: long when bandwidth expands from the frozen p20 of the
prior 120 bandwidths and close > mid. Fill at t+1 open. Missing
series skipped, not zero-filled.

### Multi-asset bar (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: #96+A+B+C on
BTC and ETH. SOL is reported when present and is **not** a gate.
Equal-weight portfolio metrics were considered and **rejected**
before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-bollinger-fade --live` (Kraken public Spot 1d
BTC+ETH+SOL, 720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US
older-720 2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps).
Catalog frozen in a prior commit before this pull.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD + SOL/USD daily | **ok** — 720 / 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT + SOLUSDT older-720 | **ok** — 720 / 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH; SOL optional) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |
| #96 FAIL ETH-carried informational names | **none** |
| Informational BTC walk-forward fails | **none** |

Informational (every name **ineligible**; rank is Kraken
walk-forward among Bollinger names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `bb_lo_fade_20x2` | −16.21% | +3.00% |
| 3 | `bb_squeeze_break_40` | +3.72% | +1.44% |
| 7 | `bb_squeeze_break_20` | +1.33% | +6.39% |
| 2 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

`bb_squeeze_break_40` has a **positive** Kraken mean HO (+3.72%)
and **positive** BTC and ETH holdout (+4.69% / +2.74%) and
**positive** BTC and ETH walk-forward (+2.79% / +0.08%) — that
clears **#96+A+B** on Kraken. It still **fails gate C** (2× fees).
Binance holdout is mixed (mean +1.44%; BTC HO −4.69%) so Binance
#96 also fails. A Kraken #96 pass that dies at 2× fees, with a
losing BTC second print, is not an edge.

`bb_squeeze_break_20` has a **positive** Kraken mean HO (+1.33%)
and **positive** BTC/ETH holdout (+1.25% / +1.41%) but ETH
walk-forward −1.87%. That is **#96 FAIL** on ETH walk-forward,
not the ETH-carried holdout pattern from #117 / #119. Binance
BTC HO −5.43%. Still not an edge. Empty dual-print set is
success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `bollinger-fade.md`.

## This session — calendar seasonality (catalog frozen)

Highest-leverage next experiment from #120: a **non-EMA /
non-residual / non-XS / non-Donchian / non-TSMOM /
non-Bollinger** family that is paper-executable on Kraken
spot. Positions are driven by the **UTC civil calendar** of
bar t only. Catalog and dual-print bar are frozen **before**
any live OHLC pull. Do not data-mine weekday or month sets
after seeing PnL. Do not re-run #104 / #108 / #116 / #117 /
#118 / #119 / #120 on the same windows. Do not invent PIT
basis.

### Catalog (frozen before the live pull)

| family | ids |
| --- | --- |
| Day-of-week long-only | `cal_dow_lo_mon`, `cal_dow_lo_fri`, `cal_dow_lo_mon_fri` |
| Skip-weekend (long Mon–Fri UTC; flat Sat/Sun) | `cal_dow_skip_weekend` |
| Month-of-year long-only | `cal_moy_lo_q4`, `cal_moy_lo_jan`, `cal_moy_lo_nov_dec` |
| Turn-of-month (last 3 / first 3 UTC calendar days) | `cal_tom_lo_3_3` |
| Control (cannot promote) | `ma_cross_10_30` |

Treatment: timezone **UTC**. Decision uses
`opened_at.astimezone(UTC).date()` (naive timestamps treated
as UTC). Fill at t+1 open. Turn-of-month uses
`calendar.monthrange` (civil last-N / first-M; no look-ahead
into future bars). A missing bar is skipped, never
zero-filled, and does not reassign last-N onto earlier dates.
Prices never enter the calendar decision.

### Multi-asset bar (frozen)

`btc_eth_signs_as_96_abc_sol_reported_not_required`: #96+A+B+C on
BTC and ETH. SOL is reported when present and is **not** a gate.
Equal-weight portfolio metrics were considered and **rejected**
before scoring.

### Print policy (frozen)

| print | rule | can promote? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C on BTC+ETH; rank dual-print passers by Kraken mean HO | only if also Binance combined-PASS |
| Binance.US older-720 | same #102 slice; must combined-PASS | no (gate only) |

### Live print (2026-09-12)

`traderstack-calendar-seasonality --live` (Kraken public Spot 1d
BTC+ETH+SOL, 720-bar cap 2024-09-22 → 2026-09-11 UTC; Binance.US
older-720 2022-10-03 → 2024-09-21, no overlap; costs 10+5 bps).
Catalog frozen in a prior commit before this pull.

| series | status |
| --- | --- |
| Kraken BTC/USD + ETH/USD + SOL/USD daily | **ok** — 720 / 720 / 720 |
| Binance.US BTCUSDT + ETHUSDT + SOLUSDT older-720 | **ok** — 720 / 720 / 720 (`api.binance.com` HTTP 451; labeled Binance.US) |
| Print kind | **dual_print** (two non-overlapping venue/era tapes) |
| Hard gates (#96+A+B+C) | **available** on both prints |
| Paper path | **true** (Kraken spot BTC/ETH; SOL optional) |
| Dual-print passers | **0** |
| Kraken combined-passers (ex-control) | **0** |
| Binance.US combined-passers (ex-control) | **0** |
| #96 FAIL ETH-carried informational names | **none** |
| Informational BTC walk-forward fails | **none** |

Informational (every name **ineligible**; rank is Kraken
walk-forward among calendar names):

| rank | id | Kraken mean HO | Binance mean HO |
| ---: | --- | ---: | ---: |
| 1 | `cal_dow_lo_mon` | −25.43% | −12.21% |
| 2 | `cal_dow_skip_weekend` | −19.71% | −4.90% |
| 3 | `cal_tom_lo_3_3` | −7.49% | −13.38% |
| 5 | `cal_dow_lo_fri` | −6.48% | +8.07% |
| 4 | `cal_moy_lo_jan` | −5.24% | +4.42% |
| 9 | `ma_cross_10_30` (control) | −2.08% | −37.11% |

Every calendar Kraken mean HO is **negative**. A positive
Binance holdout (`cal_dow_lo_fri` +8.07%; the three MOY names
+4.42%) with a losing Kraken holdout is not an edge.

`cal_moy_lo_jan` / `cal_moy_lo_q4` / `cal_moy_lo_nov_dec`
share the same Kraken holdout (−5.24% / BTC −1.80% / ETH
−8.68%). The 20% holdout on this window is ≈ Apr–Sep 2026,
which contains none of January / Q4 / Nov–Dec, so those
three names were flat for the whole holdout. That is a
window artifact, not a reason to grow the month set. Do
not retune. Empty dual-print set is success.

**Cannot promote. No new `PAPER_PROMOTE_*` pin.**

See `calendar-seasonality.md`.

## This session — BitMEX sunset + replacement hunt (after #123)

Operator directive: BitMEX is shutting down
(https://www.bitmex.com/blog/bitmex-closure). Closure Time
**23 September 2026 04:00 UTC**. Risk limits from **26 August
2026 04:00 UTC**. New registrations already stopped. Historical
BitMEX tapes stay dead-end documentation. Do not build new
promote paths, paper soaks, or fetcher dependencies on BitMEX
continuing to exist.

#124 PIT re-hunt facts (now on `main`) are included: HuggingFace
`asiletto81/hyperliquid` `asset_ctxs` is a public ≥720d HL
`mark_px`/`oracle_px` tape (883 contiguous days, 2024-01-01 →
2026-06-01). The current Kraken 720 aligns only ~617 of those days.
Do not retune the window after seeing the archive end date.

### Replacement probe (this environment, 2026-09-12)

Success for a candidate = public funding usable for daily dual-print
with HL **and** public mark−index or liquid perp-mid−spot-mid ≥720d.

| venue | funding ≥720 UTC days? | mark−index / liquid mid ≥720d? | full candidate? |
| --- | --- | --- | --- |
| Hyperliquid | **yes** (already wired; 801 daily) | **archive yes / window no** — HF 883d ends 2026-06-01 (~617d aligned); REST current-only | pair venue |
| HTX | **yes** — 6457 8h / 2152d from 2020-10-21; **wired** | **yes** — 2000 daily mark+index from 2021-03-23; **wired**, not applied alone | **yes (single venue)** |
| Binance Vision | **yes** — monthly zips 2020-01 → 2026-08 GET 200 | **yes** — `markPriceKlines` + `indexPriceKlines` 1d zips 200 | **yes (dump)** — not stitched; fapi REST **451** |
| OKX | **no** — ~96d / 290 8h | **yes** — 2448 daily mark+index | no |
| dYdX v4 | **yes** — 1052d hourly | **no** — last-trade candles; oracle 404 | no |
| MEXC | **no** — 539d | **yes** — 2000d fair+index | no |
| Gate | **no** — 180d `from` cap | **no** — mark candles need KEY | no |
| Bitget | **no** — ~90d | **no** — ~90d | no |
| Binance REST / Bybit | **skip** 451 / 403 | skip | skip |
| BitMEX | historical yes | **no** free ≥720d; **sunset** | dead-end |

### What was wired

- `fetch_htx_funding` — `funding_rate` only (`avg_premium_index`
  unused; `realized_rate` null on every historical page).
- `fetch_htx_basis` — daily (mark close − index close) / index.
  Recorded in `--live` notes. **Not** applied as a single-venue
  basis series (dual-print basis still needs HL on the same window).
- `_pick_venues` excludes `bitmex` (`SUNSET_FUNDING_VENUES`).
- `PAPER_PERP_HEDGE` auto path is Hyperliquid then HTX. BitMEX
  remains opt-in (`venue_preference="bitmex"`) only.

### Live daily print (2026-09-12, after HTX)

`traderstack-funding-carry --live --interval 1d` (Kraken public Spot
1d BTC+ETH, 720-bar cap 2024-09-22 → 2026-09-11 UTC; costs 10+5 bps).

| series | status |
| --- | --- |
| Binance USDT-M funding | **skipped** — HTTP 451 |
| Bybit linear funding | **skipped** — HTTP 403 CloudFront |
| OKX funding | **ok** — 290 8h → 97 UTC daily (not selected; shorter than HTX) |
| Hyperliquid funding | **ok** — 19199 hourly → **801** UTC daily sums |
| HTX funding | **ok** — 2401 8h → **800** UTC daily sums |
| BitMEX funding | **ok** — 2400 8h (sunset; **not selected**) |
| Print kind | **dual_print** (Hyperliquid primary, HTX second) |
| Aligned daily bars | primary **720** / second **720** |
| Hard gates (#96+A+B+C) | **available** (both venues ≥720) |
| Basis | **skipped** (HL window ~617d; HTX 2000d not applied alone) |
| Paper path | **true** (HL/HTX soak; BitMEX not required) |
| Spot-signal dual-print passers | **0** |
| Modeled dual-print passers | `carry_hedged_sign` only |

Modeled hedged carry (basis skipped; **not** paper-spot executable):

| id | HL WF / HO / full | HTX WF / HO / full | both? |
| --- | ---: | ---: | :---: |
| `carry_hedged_sign` | +1.72% / +3.32% / +27.71% | +1.50% / +3.31% / +21.26% | yes* |
| `carry_hedged_abs_1bp` | −1.36% / −8.17% / −18.98% | −1.66% / −12.15% / −32.13% | no |
| `carry_hedged_abs_3bp` | −2.42% / −4.82% / −21.50% | −3.65% / −9.95% / −35.76% | no |
| `carry_hedged_z_1_5` | −2.88% / −8.72% / −32.95% | −2.99% / −9.64% / −34.12% | no |

\*Fee-aware signs > 0 on **both** independent daily tapes. Hard-gate
analog combined **true** on both (HL ratio 0.87; HTX ratio 0.81).
That is still **not** basis-aware. `can_promote` stays false.

### What was not done (on purpose)

- No Binance Vision zip stitch (HTX REST already fills funding).
- No HL `asset_ctxs` fetcher into scoring (617d < 720 on this
  window; do not retune).
- No `PAPER_PROMOTE_*` flip. Defaults stay **false**.
- Did not reconstruct mark from index × (1 + funding basis).
- Did not re-run candle catalogs #104/#108/#116–#123.

**Cannot promote.** Funding dual-print without BitMEX is now
HL+HTX. Basis-aware carry is still UNAVAILABLE.

See `funding-carry-daily.md` and `pit-basis-archives.md`.

## Pins

| flag | default | status |
| --- | --- | --- |
| `PAPER_PROMOTE_SEARCHED_STRATEGIES` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21_ADX15` | false | stay false |
| `PAPER_GARCH_SIZE` | false | stay false |
| new funding/carry pin | *(not added)* | `carry_hedged_sign` is a modeled daily dual-print + hard-gate analog passer on Hyperliquid+HTX (HL WF +1.72% / HTX +1.50%); paper soak path ready (HL/HTX); HL PIT mark−index now readable (`asiletto81/hyperliquid`, 883d) but BitMEX still UNAVAILABLE and the scored 720 aligns only ~617d — do not add a pin |
| new relative-value pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; do not add a pin |
| new cross-sectional momentum pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; informational `xs_mom_lo_vol_63` mean HO is ETH-carried (#96 FAIL); do not add a pin |
| new Donchian pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; informational positive Kraken mean HO still fails #96 on BTC walk-forward; do not add a pin |
| new TSMOM pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; informational `tsmom_lo_63` / `tsmom_ls_63` mean HO is ETH-carried (#96 FAIL); `tsmom_lo_21` / `tsmom_ls_21` fail BTC walk-forward; do not add a pin |
| new Bollinger fade pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; informational `bb_squeeze_break_40` clears Kraken #96+A+B but fails gate C; no ETH-carried / BTC-WF-fail names; do not add a pin |
| new calendar seasonality pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; every Kraken mean HO negative; no ETH-carried / BTC-WF-fail names; do not add a pin |
| new lead-lag pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; informational `leadlag_eth_follow_lo_5` mean HO is ETH-carried (#96 FAIL); do not add a pin |
| new volume-breakout pin | *(not added)* | dual-print passers 0 on Kraken 720 + Binance.US older-720; no ETH-carried names; informational BTC WF-fail: `volbrk_lo_20x1_5` / `volbrk_lo_20x2` / `volsurge_lo_20x2` / `volsurge_lo_20x2_5`; do not add a pin |
| `PAPER_PERP_HEDGE` | false | opt-in forward soak; fetches HL midPx / HTX bid/ask mid + same-venue funding; BitMEX not required; not a promote path |

`TRADING_MODE=paper`. No live.

## Addendum 2026-09-13 — odds brief and tracking issue

The bottleneck is statistical power, not the catalog: every family above
sits on one ~2-year window. See `docs/artifacts/research/odds-brief-2026-09-13.md`
and tracking issue #132 (sub-issues #133–#143) for the verified free
multi-year data (Coinbase, Binance Vision, OKX mark/index, Kraken archive),
the dual-print PIT basis that is now reachable, the DSR/PBO harness gates,
fee realism, and the Polymarket tape collector. Nothing in that program
relaxes a gate or flips a `PAPER_PROMOTE_*` default.

## Addendum 2026-09-14 — on-chain regime overlay (#139)

`traderstack-onchain-regime` scored the frozen TSMOM catalog ungated and
gated by three pre-registered Coin Metrics community overlays (`mvrvz_p90`,
`mvrvz_p80`, `nupl_075`; BTC series, rows strictly before the decision bar)
on the same two prints. **Overlay passers: 0.** `mvrvz_p90` and the two
`*_63__mvrvz_p80` names are `mixed_fail` (a print/metric helped, another
hurt); the other `mvrvz_p80` names `hurts`; `nupl_075` never bound (NUPL
never exceeded 0.75 on either print → `neutral`). No new pin. The runtime
gate (`ONCHAIN_REGIME_GATE_ENABLED`) stays off by default and can only
withhold new longs. See `onchain-regime.md`.
