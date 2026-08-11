# High-Level Design

## System context

```text
External intelligence                       Trading venues
─────────────────────                       ──────────────
TradingView MCP                             CEX REST/WebSocket
Dune MCP                                    DEX / AMMs
Perplexity MCP                              Hummingbot connectors
altFINS MCP                                 Hummingbot Gateway
CoinGecko MCP/API                                 │
CryptoPanic MCP                                   │
CoinMarketCap MCP/API                             │
LunarCrush MCP                                    │
       │                                           │
       ▼                                           ▼
┌─────────────────┐                       ┌──────────────────┐
│ Ingestion layer │                       │ Execution layer  │
└────────┬────────┘                       └────────┬─────────┘
         ▼                                         ▲
┌─────────────────┐                                │
│ Normalisation & │                                │
│ feature engine  │                                │
└────────┬────────┘                                │
         ▼                                         │
┌─────────────────┐       ┌─────────────────┐      │
│ Strategy agents │──────▶│ Portfolio/meta  │      │
│ + quant signals │       │ intelligence    │      │
└─────────────────┘       └────────┬────────┘      │
                                  ▼               │
                         ┌─────────────────┐        │
                         │ Deterministic   │────────┘
                         │ risk engine     │
                         └─────────────────┘
```

## Major subsystems

### 1. Data ingestion
Responsibilities:
- venue-native market feeds;
- intelligence/MCP/API polling;
- timestamps and freshness;
- source identity and quality metadata;
- idempotent event ingestion.

### 2. Normalisation and feature engine
Converts heterogeneous raw inputs into versioned structured features. LLM agents should consume bounded features and selected evidence rather than raw firehoses by default.

Feature families:
- price/trend/momentum;
- volatility and liquidity;
- order-book/microstructure;
- derivatives/funding/open interest where available;
- on-chain flows;
- social/narrative acceleration;
- news/event risk;
- cross-asset relationships;
- market regime.

### 3. Strategy layer
Initial independent strategies:
- momentum/trend;
- breakout;
- mean-reversion research baseline;
- on-chain flow;
- narrative/social momentum;
- event/news reaction;
- funding/basis research strategy.

Each strategy produces a structured `TradeCandidate`, never a direct order.

### 4. Claude/meta-agent layer
Primary responsibilities:
- cross-source synthesis;
- event interpretation;
- resolving conflicting evidence;
- regime-aware strategy selection/challenge;
- producing bounded candidate rationale and confidence;
- post-trade qualitative attribution.

It does not control hard risk policy or signing keys.

### 5. Portfolio allocator
Consumes approved candidates and current portfolio state. Responsible for:
- volatility-aware sizing;
- correlation/concentration constraints;
- strategy risk budgets;
- portfolio-level exposure;
- capital allocation across strategies.

### 6. Deterministic risk engine
Final mandatory pre-trade authority. Possible decisions:
- `ALLOW`
- `REDUCE_SIZE`
- `REJECT`
- `HALT_STRATEGY`
- `HALT_SYSTEM`

No model tool is granted permission to change production risk rules.

### 7. Execution
Preferred spine: Hummingbot API/MCP/Gateway plus venue-native data.

Responsibilities:
- order lifecycle;
- execution venue selection;
- quote freshness;
- slippage control;
- retries and reconciliation;
- fills and fees;
- position reconciliation;
- on-chain transaction construction/simulation where applicable.

### 8. Workflow and event processing
24/7 operation is event-driven. Examples:
- price breakout;
- volatility spike;
- social/narrative spike;
- whale/on-chain flow;
- material news;
- stale/failed data source;
- risk threshold;
- fill/update;
- scheduled portfolio review.

Durable workflow semantics are required so process or host failures cannot silently lose execution state.

### 9. Persistence
Proposed logical stores:
- PostgreSQL: portfolio, orders, decisions, policy/config metadata;
- time-series store/TimescaleDB: bars, features, signals, execution telemetry;
- Redis: ephemeral cache/locks/state acceleration;
- Parquet/object storage: research datasets and reproducible backtests.

### 10. Observability and audit
All decisions need a traceable chain:
`raw evidence → features → strategy candidate → AI assessment → allocation → risk decision → order → fill → outcome`.

Use OpenTelemetry-compatible traces/metrics/logs with dashboards and alerts.

## Trust boundaries

1. Internet/MCP responses are untrusted data.
2. Claude/LLM output is untrusted until schema-validated.
3. Strategy output cannot reach execution without deterministic controls.
4. Signing credentials live in an isolated execution/signing boundary.
5. API keys should have the minimum required exchange permissions; withdrawal permissions are prohibited for CEX trading keys.
6. Failure to establish fresh/consistent state defaults to no new risk.

## Deployment model

Initial deployment should be containerised and reproducible. Separate logical/runtime domains for:
- research and backtesting;
- market-data ingestion;
- agents;
- deterministic risk;
- execution/signing;
- observability.

Production live execution is intentionally deferred until validation gates are satisfied.
