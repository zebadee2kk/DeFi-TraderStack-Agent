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

Live print: `traderstack-funding-carry --live --interval 1d` (see
`funding-carry-daily.md`). Numbers are filled from that run — not
invented here.

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

*(filled after `--live --interval 1d`; do not invent)*

## Next falsifiable experiments

Do not rerun #104 / #105 / #106 / #108 / the 4h #110 funding print
on the same windows.

1. **Second independent funding tape.** Done in #110: Hyperliquid +
   OKX dual-print. Spot-signal passers: **0**. Modeled
   `carry_hedged_sign` cleared fee-aware signs on both 4h-aligned
   tapes and still cannot promote.
2. **Daily resample / #96+A+B+C honesty.** This session. See above
   and `funding-carry-daily.md`.
3. **Basis-aware carry, only if a PIT perp−spot series exists on
   both venues.** Do not invent basis from last-trade or from
   funding itself. Skip if the series is missing.
4. **Paper-executable path (still `TRADING_MODE=paper`).** A paper
   perp simulator that applies venue funding at each settlement,
   and/or a two-leg paper hedge book, plus PIT basis mark-to-market.
   Do not add a Settings pin that implies this path exists.
5. **Not** another daily-EMA catalog expansion on the same Kraken 720
   + Binance.US older-720 pair.
6. **Not** liquidation-conditioned promotion until a public historical
   liquidation aggregate exists (it does not today).
7. **Not** Polymarket weather promotion until a PIT CLOB mid +
   official station-high tape exists (it does not today).

## Pins

| flag | default | status |
| --- | --- | --- |
| `PAPER_PROMOTE_SEARCHED_STRATEGIES` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21_ADX15` | false | stay false |
| `PAPER_GARCH_SIZE` | false | stay false |
| new funding/carry pin | *(not added)* | `carry_hedged_sign` is a modeled 4h dual-print passer only; daily hard gates / PIT basis / paper path are not all clear — do not add a pin |

`TRADING_MODE=paper`. No live.
