# Strategy search artifacts

Committed output of `traderstack-strategy-search` on **Kraken Spot OHLC**
(`GET https://api.kraken.com/0/public/OHLC`) for BTC/USD, ETH/USD, SOL/USD,
1h bars, 2026-08-13 13:00 UTC → 2026-09-12 12:00 UTC (720 committed candles
each). Costs: `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)=10` + `PRETRADE_SLIPPAGE_BPS=5`.

This is **not** a profitability claim.

## Result on this window

No catalog member cleared the promotion gate. Pre-registered top-1 by
walk-forward mean excess return was `momentum_6` (WF excess +1.06%) but
holdout excess was **−2.96%**. Every rankable candidate had **negative**
walk-forward *total* return after fees. The always-on MA (`ma_always_on_10_30`)
posted WF total return −1.02%.

**Leave `PAPER_PROMOTE_SEARCHED_STRATEGIES=false`.**

Offline unit tests use the smaller synthetic files in
`tests/fixtures/strategy_search/` (not this live window). Runtime default
writes the same JSON/MD pair to `var/ops/` (gitignored).
