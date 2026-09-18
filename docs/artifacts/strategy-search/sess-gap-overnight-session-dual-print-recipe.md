# Overnight vs session open-close gap dual-print recipe (pre-registration)

**Repo tip at score:** `cc5f90a`.

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · tip at authoring: re-pin commit SHA in the run report.
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Prior paper dual-prints (#160–#167) returned empty / unavailable / zero-fill
soaks. This note freezes a **fresh** candle-only family that splits the daily
OHLC return into overnight vs session components without needing an intraday
archive:

- overnight_gap[t] = open[t] / close[t-1] − 1
- session_ret[t] = close[t] / open[t] − 1

A missing or non-positive prior close/open is **skipped**, never zero-filled.

## Frozen catalog (new ids; freeze before any score)

Prefix: `sess_gap_`

| id | feature | rule |
| --- | --- | --- |
| `sess_gap_on_fade_{1_0,1_5,2_0}` | overnight gap | fade FeatureZ \|z\|≥ threshold |
| `sess_gap_on_follow_{1_0,1_5,2_0}` | overnight gap | follow FeatureZ \|z\|≥ threshold |
| `sess_gap_sess_fade_{1_0,1_5,2_0}` | session return | fade FeatureZ \|z\|≥ threshold |
| `sess_gap_sess_follow_{1_0,1_5,2_0}` | session return | follow FeatureZ \|z\|≥ threshold |
| `ma_cross_10_30` | control | informational; cannot promote |

Lookback = 20. Do **not** grow or retune this list after seeing PnL.

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage.

## Dual-print cells

1. Kraken: `var/research/candles/kraken/` (BTC/ETH gate).
2. Coinbase: `var/research/candles/coinbase/` (BTC/ETH gate).

Each venue builds features from **its own** OHLC (venues never averaged).

## Exact command

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

traderstack-sess-gap \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --fee-bps 80 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/sess-gap-overnight-session-dual-print.md \
  --output-json var/ops/sess_gap_overnight_session_dual_print.json
```

## Success criteria

- Recipe committed **before** the score artifact.
- Score writes an honest report; `dual_print_passers=0` is success.
- `PAPER_PROMOTE_*` defaults remain false.
