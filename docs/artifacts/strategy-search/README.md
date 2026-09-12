# Strategy search artifacts

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
