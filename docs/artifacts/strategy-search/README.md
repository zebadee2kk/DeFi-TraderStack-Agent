# Strategy search artifacts

This directory holds committed offline search reports. Two catalogs share it.

## Catalog search (`traderstack-strategy-search`)

Committed output of `traderstack-strategy-search` on **Kraken charts-spot
`PI_*`** (research-only; not the 720-bar public Spot OHLC). BTC/USD, ETH/USD,
SOL/USD. Costs: `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)=10` +
`PRETRADE_SLIPPAGE_BPS=5`.

This is **not** a profitability claim.

## Windows

| file | interval | source | bars / asset | span |
| --- | --- | --- | ---: | --- |
| `report.md` / `report.json` | 1h | `kraken_charts_spot` | 4320 | 2026-03-16 13:00 → 2026-09-12 12:00 UTC (180.0d) |
| `report-4h.md` / `report-4h.json` | 4h | `kraken_charts_spot` | 1080 | 2026-03-16 12:00 → 2026-09-12 08:00 UTC (179.8d) |

Public `GET /0/public/OHLC` cannot reach this history: a `since` of 180 days
ago still returns the same most-recent **720** 1h bars. Charts-spot closes can
differ a few bps from that print; volume is zero on this path.

## Result

**No catalog member cleared the promotion gate on either window.**

Promotion requires WF mean **total** return > 0 after fees, min trades, and
holdout mean excess > 0. Ranking is pre-registered top-1 by WF excess (K=23;
Bonferroni analogue 0.05/23 ≈ 0.0022). Top-1 failing holdout does **not**
unlock #2.

### 1h (primary, paper-aligned timeframe)

Every rankable candidate had **negative** walk-forward total return *and*
negative excess after fees.

| top-1 / notable | WF excess | WF total | holdout excess | promoted |
| --- | ---: | ---: | ---: | --- |
| `funding_z_follow` (top-1) | **−0.11%** | **−0.09%** | **−20.12%** | no |
| `oi_z_follow` | −0.43% | −0.41% | −28.92% | no |
| `ma_always_on_10_30` | −0.86% | −0.84% | −16.03% | no |
| `momentum_6` (PR #89 30d top-1) | −1.11% | −1.09% | −18.56% | no |

### 4h (supporting mix)

Three names posted positive WF total after fees. All three **failed holdout**.

| top-1 / notable | WF excess | WF total | holdout excess | promoted |
| --- | ---: | ---: | ---: | --- |
| `momentum_12_strict` (top-1) | +0.44% | **+0.45%** | **−13.06%** | no (holdout failed) |
| `momentum_6_vol` | +0.19% | +0.19% | −13.89% | no (not top-1; holdout failed) |
| `ma_cross_5_20` | +0.06% | +0.06% | −13.96% | no (not top-1; holdout failed) |

## Edge series

| series | status |
| --- | --- |
| Binance USDT-M funding / OI / `allForceOrders` | **skipped** — HTTP 451 from this environment |
| Binance historical liquidations | **skipped** — no public USDT-M historical REST; live WS is `!forceOrder@arr`; Vision `um/liquidationSnapshot` removed |
| OKX funding-rate-history | **ok** — 289 prints (~90d of 8h) per BTC/ETH/SOL |
| OKX 1h open-interest-history | **ok** — 1440 points (~60d) per symbol |
| OKX liquidation-orders | **skipped** — ~5–19h of recent fills, not a historical aggregate |
| Cross-venue divergence | **skipped** — no aligned two-venue series supplied |

**Leave `PAPER_PROMOTE_SEARCHED_STRATEGIES=false`.**
`PAPER_PROMOTE_SEARCHED_STRATEGY_ID` stays empty — there is no id to pin.

Offline unit tests use the smaller synthetic files in
`tests/fixtures/strategy_search/` (not this live window). Runtime default
writes the same JSON/MD pair to `var/ops/` (gitignored).

## Miles-inspired catalog (`traderstack-miles-search`)

Committed output of `traderstack-miles-search --live-kraken` on Kraken public
Spot OHLC (`GET https://api.kraken.com/0/public/OHLC`) for BTC/USD, ETH/USD,
SOL/USD.

Kraken returns at most 720 of the most recent committed bars per pair and
interval. Daily (2024-09-22 → 2026-09-11) is the promotion window. 1h
(2026-08-13 → 2026-09-12) is robustness only — 1h percent returns are not
averaged with daily.

Costs: `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)=10` + `PRETRADE_SLIPPAGE_BPS=5`.

### Result on this window

`ema_9_21` cleared the daily bar (WF mean total return +7.92%, holdout mean
excess +22.20% after fees). That holdout is one ~144-day tail and is ETH-heavy.
Every GARCH-sized candidate lost money after fees (more turnover). 1h lost
money for the same EMA.

**Leave `PAPER_GARCH_SIZE=false`.** This is not a live-capital claim and not
a YouTube PnL copy. Register `ema_9_21` as a paper voter only via the
documented `PAPER_PROMOTE_EMA_9_21` flag (default false). That flag forces
paper candles to daily (`1d` / 1440m) and uses
`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` (default 0.30) so the ~23%
daily WF maxDD is not rejected by the 1h 15% bar. Do not claim this
daily edge on a 1h runtime.

See `miles-inspired-report.md`.

## Daily robustness (`traderstack-daily-robustness`)

Stress-test of the #93 daily winner plus dual-momentum and buy-the-dip
mean-reversion on the longest **Kraken public Spot daily** window the API
allows (720 committed bars, ~2 years). `since` cannot unlock older Kraken
prints. Optional Yahoo Finance `BTC-USD` / `ETH-USD` daily is a longer
**non-Kraken** A/B and never enters the promotion average.

Promotion is stricter than #93: **BTC and ETH** must both have fee-aware
walk-forward mean total return > 0, plus holdout mean excess > 0. The
three-asset mean that let ETH dominate #93's holdout is not enough.

On the 2026-09-12 Kraken window, `ema_9_21` still cleared BTC WF +4.57%
and ETH WF +14.61% (holdout remains ETH-heavy: +5.55% vs +58.37%). Dual-
momentum and buy-the-dip did not. Documented pin is
`PAPER_PROMOTE_EMA_9_21` (default false). Yahoo daily is supporting only.

See `daily-robustness-report.md`.

## Balanced holdout (`traderstack-daily-robustness`, default bar)

The #95 bar still lets an ETH holdout tail carry a **mean** that is
positive while BTC holdout is not. The default promotion bar now also
requires **BTC holdout excess > 0 and ETH holdout excess > 0**. SOL is
reported and is not a gate. Yahoo remains A/B only.

The catalog is pre-registered (frozen before the window is scored): the
#95 EMA/ADX names, slower EMA 20/50 and 50/200, a dual-mom lookback
grid, a dip z grid, asset-local and BTC-overlay SMA200 risk-off, and
two GARCH size overlays. `PAPER_GARCH_SIZE` and
`PAPER_PROMOTE_EMA_9_21` stay false unless a committed report names a
paper-only pin and an operator flips the flag.

On the 2026-09-12 Kraken 720-bar daily window (2024-09-22 → 2026-09-11),
`ema_9_21` **PASS**ed both bars: BTC WF +4.57% / ETH WF +14.61%, BTC
holdout excess +5.55% / ETH +58.37%. The ETH tail is still large; the
new bar only requires both **signs** > 0. Slower EMAs, dual-mom, dip,
and both GARCH overlays failed. Yahoo BTC-USD holdout excess stayed
negative and did not enter the average. Leave
`PAPER_PROMOTE_EMA_9_21=false` (documented paper-only pin only).

See `balanced-holdout-report.md`.

