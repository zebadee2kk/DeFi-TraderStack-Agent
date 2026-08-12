# Implementation Slice 02 — Signal-Driven Paper Loop

## Goal
Replace the hardcoded vertical-slice demonstration proposal with a real, candle-driven
signal path so the continuous paper service exercises the actual strategy machinery:

1. maintain per-symbol candle history via a TTL-cached feed (`CandleFeed` over
   `KrakenCandleProvider`), excluding the still-forming bar;
2. build real `MarketFeatures` from candles (`CandleMarketFeatureBuilder`);
3. classify the regime and evaluate the baseline strategy ensemble
   (momentum, trend, mean reversion) on every cycle;
4. trade only on multi-strategy consensus, with confidence-scaled sizing
   (`nav × base_notional_pct × confidence`);
5. optionally enrich the feature vector with external intelligence
   (CryptoPanic news, LunarCrush social) and veto buys on adverse news events;
6. optionally route the consensus candidate through the constrained Claude
   meta-agent (`--meta-agent`), which can only veto or nudge confidence within
   schema bounds and fails closed on any error;
7. pass every proposal through the deterministic risk engine before any
   paper-order intent is produced.

## Pipeline order of gates
market-data quality → candle features → ensemble consensus → confidence floor →
adverse-news veto → notional floor → meta-agent review (optional, fail-closed) →
deterministic risk engine.

The demo pipeline remains available behind `--pipeline demo` for integration
smoke tests; `--pipeline signal` is the default.

## Risk-policy changes (policy_version mvp-v2)
- **Daily loss limit now anchors to the UTC day.** The portfolio book tracks a
  daily NAV anchor that rolls over at midnight UTC and persists through
  checkpoints, so `daily_pnl_usd` means "today's PnL", not lifetime PnL.
- **Sell semantics.** Sells only reduce paper exposure (no shorts): they are
  capped to the existing position, rejected when there is no position, and are
  not blocked by the daily-loss or drawdown breakers (reducing risk is always
  permitted). The kill switch and asset allowlist still gate everything.
- **Minimum order notional** (`MIN_ORDER_NOTIONAL_USD`, default $10) rejects
  dust orders on both sides, including after a REDUCE.

## Failure behaviour
Fail closed when:
- candle history is unavailable or insufficient (cycle downgrades to a
  market-data rejection, never a crash);
- the meta-agent errors, refuses, or returns malformed output;
- any existing slice-01 market-data gate trips.

Fail open (advisory only) when:
- external intelligence providers are unavailable — the pipeline falls back to
  a market-only feature vector, because intelligence can only veto, never
  originate trades.

## Execution reconciliation loop
When `--submit` is active the service owns an `ExecutionLedger` and a
`HummingbotExecutionReconciler`. Every `RECONCILE_INTERVAL_SECONDS` it pulls
order states and trades from the Hummingbot API, applies previously unseen
fills to the portfolio book (idempotent by fill id), and checkpoints the book
whenever fills were applied. Reconciliation failures never crash a cycle, but
`max_consecutive_reconcile_failures` (default 5) consecutive failures halt the
service — sustained unreconciled state is treated as unsafe to trade through.

## On-chain enrichment
When `DUNE_API_KEY` and `DUNE_QUERY_IDS` (`BTC:1234567,ETH:2345678`) are both
set, the intelligence orchestrator fetches per-asset on-chain snapshots from
Dune and merges them into the feature vector. Like all external intelligence
this is advisory: it informs the meta-agent's evidence packet but cannot
originate trades.

## Walk-forward parameter fitting
`FittedWalkForwardEvaluator` (see `walkforward.py`) fits ensemble parameters on
each training window — selecting among `EnsembleCandidate` configurations by
train-window Sharpe (tie-broken by total return) — and scores only the selected
candidate on the out-of-sample test window. The test slice never influences
selection.

## New configuration
| Variable | Default | Meaning |
| --- | --- | --- |
| `BASE_NOTIONAL_PCT` | 0.02 | NAV fraction requested at confidence 1.0 |
| `MIN_CONSENSUS_CONFIDENCE` | 0.35 | consensus confidence floor |
| `MIN_ORDER_NOTIONAL_USD` | 10 | dust-order rejection floor |
| `CANDLE_INTERVAL` | 1h | strategy candle interval |
| `CANDLE_COUNT` | 250 | candles fetched per refresh |
| `CANDLE_REFRESH_SECONDS` | 300 | candle cache TTL |
| `ANTHROPIC_MODEL` | claude-haiku-4-5-20251001 | meta-agent review model |
| `RECONCILE_INTERVAL_SECONDS` | 30 | execution reconciliation cadence |
| `DUNE_QUERY_IDS` | (empty) | per-asset Dune query IDs for on-chain features |

## Explicitly out of scope for this slice
- shorting, leverage, or any non-paper execution;
- automatic promotion of fitted parameters into the live loop (fitting remains
  a research harness until the evaluation gates in the roadmap are met).
