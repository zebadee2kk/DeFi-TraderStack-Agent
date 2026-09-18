# Vol-target overlay on frozen ma_cross_10_30 dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · tip at authoring: re-pin commit SHA in the run report.
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Prior paper dual-prints (#160–#168) returned empty / unavailable / zero-fill
soaks. Edge-status 2026-09-18 ranks next: a **vol-target size overlay** on a
**frozen** simple signal (`ma_cross_10_30`). The unit-weight control alone
cannot promote; each overlay id needs its own dual-print passer.

This is **not** a Miles EMA+GARCH catalog reprint and **not** a retune of
session-gap / funding-div / xs-topk.

## Frozen catalog (new ids; freeze before any score)

Prefix / control:

| id | sizing | note |
| --- | --- | --- |
| `ma_cross_10_30` | unit ±1 | control; informational; **cannot promote** |
| `ma_cross_10_30_vt15` | min(0.15 / ann. realised vol, 1.0) | overlay |
| `ma_cross_10_30_vt25` | min(0.25 / ann. realised vol, 1.0) | overlay |
| `ma_cross_10_30_vt50` | min(0.50 / ann. realised vol, 1.0) | overlay |

Direction (frozen): always-on SMA cross short=10 / long=30 (same voter as
the search-catalog `ma_cross_10_30` always-on baseline).

Vol scalar (frozen): annualised std of the last **20** simple close-to-close
returns through the decision bar × √periods_per_year; missing/insufficient
history → **flat** (skip-not-invent, never zero-filled). Max leverage **1.0**
(reduce-only; no leverage).

Do **not** grow this list, move a target, or change the lookback after seeing PnL.

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage.

## Dual-print cells

1. Kraken: `var/research/candles/kraken/` (BTC/ETH gate).
2. Coinbase: `var/research/candles/coinbase/` (BTC/ETH gate).

Each venue scores its **own** OHLC (venues never averaged).

## Passer rule (frozen)

A name is a dual-print passer only if it is eligible on **both** venue prints
under the miles-style paper bar (mean WF total > 0, mean holdout excess > 0,
min trades) **and** it is **not** the control. Control is scored and reported
but excluded from `dual_print_passers`. Empty set is success.

## Exact command

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate
traderstack-vol-target \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --fee-bps 80 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/vol-target-ma-cross-dual-print.md
```

## Promote

**Keep every `PAPER_PROMOTE_*=false`.** This CLI never adds or flips a promote
pin. `TRADING_MODE` stays paper. No live path.
