# Edge-hunt status — 2026-09-12

Paper / research only. This memo summarizes the strategy-search dead
ends through #108 and the next falsifiable slice (funding / carry).
It is **not** a profitability claim. No number here is invented.

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
`traderstack-paper`. The cycle still passes `perp_mid_usd=None`, so
production hedges skip. `PAPER_CARRY_PATH_READY` stays **false**.
`can_promote` stays **false**. No new Settings pin.

### Still blocked

`can_promote` requires dual-print ∧ hard gates ∧ PIT basis ∧ paper
path. After this session: dual-print **true**, hard gates **true**,
basis **UNAVAILABLE**, paper path **stub / not ready**.

## Next falsifiable experiments

Do not rerun #104 / #105 / #106 / #108 / the 4h #110 funding print
on the same windows. Do not rerun the #111 daily print with only
OKX as the second tape. Do not re-score carry on HL `premium` or
BitMEX `.XBTUSDPI`.

1. **Second independent funding tape.** Done in #110: Hyperliquid +
   OKX dual-print. Spot-signal passers: **0**. Modeled
   `carry_hedged_sign` cleared fee-aware signs on both 4h-aligned
   tapes and still cannot promote.
2. **Daily resample / #96+A+B+C honesty.** Done in #111. See above
   and `funding-carry-daily.md`.
3. **Second long settlement tape.** Done in #112: BitMEX. Daily
   dual-print + hard gates are available. Modeled
   `carry_hedged_sign` clears both prints and the #96+A+B+C analog
   and still cannot promote (basis skipped; paper path not ready).
4. **Basis-aware carry.** This session: probed and **UNAVAILABLE**
   on Hyperliquid and BitMEX for mark−index / perp-mid−spot-mid.
   Next only if a public historical mark/index or perp-mid−spot-mid
   tape appears on **both** venues. Do not invent from last-trade
   or from funding.
5. **Paper-executable path (still `TRADING_MODE=paper`).** Stub
   exists; not cycle-wired with a perp mid. Next: a PIT perp mid
   (not Kraken spot) plus funding settlements in the paper cycle,
   still paper-only, kill switch respected. Do not add a Settings
   pin until A+B both work and gates still clear.
6. **Not** another daily-EMA catalog expansion on the same Kraken 720
   + Binance.US older-720 pair.
7. **Not** liquidation-conditioned promotion until a public historical
   liquidation aggregate exists (it does not today).
8. **Not** Polymarket weather promotion until a PIT CLOB mid +
   official station-high tape exists (it does not today).

## Pins

| flag | default | status |
| --- | --- | --- |
| `PAPER_PROMOTE_SEARCHED_STRATEGIES` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21_ADX15` | false | stay false |
| `PAPER_GARCH_SIZE` | false | stay false |
| new funding/carry pin | *(not added)* | `carry_hedged_sign` is a modeled daily dual-print + hard-gate analog passer on Hyperliquid+BitMEX; PIT basis UNAVAILABLE and paper perp stub not promote-ready — do not add a pin |
| `PAPER_PERP_HEDGE` | false | scaffold only; cycle skips without a PIT perp mid |

`TRADING_MODE=paper`. No live.
