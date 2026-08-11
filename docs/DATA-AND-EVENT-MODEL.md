# Data and Event Model

## Purpose

Create a canonical data plane that prevents individual agents from consuming inconsistent raw provider responses.

## Data Layers

1. **Raw ingestion** — immutable provider payloads, timestamped at receipt.
2. **Normalized market data** — common schema for prices, candles, order books, funding and volume.
3. **Feature store** — calculated technical, on-chain, social and event features.
4. **Signal store** — versioned strategy signals.
5. **Decision store** — agent proposals and risk decisions.
6. **Execution ledger** — orders, fills, fees, slippage and reconciled positions.

## Canonical Feature Record

```json
{
  "asset": "BTC-USDT",
  "venue": "kraken",
  "ts": "2026-08-11T19:00:00Z",
  "market": {
    "last": 0,
    "spread_bps": 0,
    "relative_volume": 0,
    "volatility_z": 0,
    "trend_1h": 0,
    "trend_4h": 0,
    "trend_1d": 0
  },
  "onchain": {
    "exchange_netflow_z": 0,
    "large_wallet_flow_z": 0
  },
  "social": {
    "mention_velocity_z": 0,
    "sentiment": 0
  },
  "news": {
    "event_score": 0,
    "adverse_event": false
  }
}
```

## Core Events

- MARKET_TICK
- CANDLE_CLOSED
- PRICE_BREAKOUT
- VOLUME_SPIKE
- VOLATILITY_SPIKE
- FUNDING_EXTREME
- SOCIAL_SPIKE
- NEWS_EVENT
- WHALE_FLOW
- REGIME_CHANGED
- SIGNAL_CREATED
- TRADE_PROPOSED
- RISK_REJECTED
- ORDER_SUBMITTED
- ORDER_FILLED
- ORDER_CANCELLED
- POSITION_OPENED
- POSITION_CLOSED
- DRAWDOWN_LIMIT
- DATA_STALE
- PROVIDER_FAILURE
- EXECUTION_FAILURE
- KILL_SWITCH

## Event Envelope

Every event must include:

```json
{
  "event_id": "uuid",
  "event_type": "PRICE_BREAKOUT",
  "occurred_at": "ISO-8601",
  "received_at": "ISO-8601",
  "asset": "BTC-USDT",
  "source": "market-scanner",
  "schema_version": "1.0",
  "correlation_id": "uuid",
  "payload": {}
}
```

## Freshness

Every provider datum must retain source timestamp, retrieval timestamp and TTL. Stale data must fail closed for execution-sensitive decisions.

## Storage Recommendation

- PostgreSQL: decisions, strategy metadata, orders, positions, configuration.
- TimescaleDB/PostgreSQL hypertables: candles, features and time-series metrics.
- Redis: ephemeral cache, locks and short-lived event state.
- Parquet/object storage: historical immutable datasets and backtest snapshots.
