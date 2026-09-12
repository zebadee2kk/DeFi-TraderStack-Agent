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

## Next falsifiable experiments

Do not rerun #104 / #105 / #106 / #108 on the same windows.

1. **Second independent funding tape.** Binance USDT-M
   `/fapi/v1/fundingRate` when not HTTP 451, or an operator-supplied
   point-in-time tape that does not overlap the OKX ~90d window.
   Same catalog, dual-print bar already frozen. Without this, funding /
   carry stays single-print.
2. **Basis-aware carry, only if a PIT perp−spot series exists.** Do
   not invent basis from last-trade or from funding itself. Skip if
   the series is missing.
3. **Longer funding overlap that can actually run #96+A+B+C.** That
   means 720 aligned **daily** bars of funding on BTC and ETH, on two
   venues. Not a 4h 90d reprint labeled as daily.
4. **Not** another daily-EMA catalog expansion on the same Kraken 720
   + Binance.US older-720 pair.
5. **Not** liquidation-conditioned promotion until a public historical
   liquidation aggregate exists (it does not today).
6. **Not** Polymarket weather promotion until a PIT CLOB mid +
   official station-high tape exists (it does not today).

## Pins

| flag | default | status |
| --- | --- | --- |
| `PAPER_PROMOTE_SEARCHED_STRATEGIES` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21` | false | stay false |
| `PAPER_PROMOTE_EMA_9_21_ADX15` | false | stay false |
| `PAPER_GARCH_SIZE` | false | stay false |
| new funding/carry pin | *(not added)* | do not add unless a dual-print passer exists |

`TRADING_MODE=paper`. No live.
