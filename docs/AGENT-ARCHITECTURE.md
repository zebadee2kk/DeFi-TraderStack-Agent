# Agent Architecture

## Objective

Define an agent topology that combines LLM reasoning with deterministic quantitative controls. No agent may directly bypass portfolio or risk policy.

## Topology

### 1. Market Regime Agent
Classifies current market state using quantitative features plus contextual interpretation.

Outputs:
- regime label
- confidence
- supporting features
- active strategy set

### 2. Technical Strategy Agent
Consumes normalized market features and altFINS/TradingView-derived technical signals.

Outputs structured trade candidates only.

### 3. On-Chain Strategy Agent
Consumes Dune, CoinGecko on-chain data and wallet/protocol flow signals.

### 4. Narrative/Sentiment Agent
Consumes LunarCrush, CryptoPanic and Perplexity research.

### 5. Market Data Validation Agent
Cross-checks CoinGecko, CoinMarketCap and direct venue data for stale or divergent feeds.

### 6. Meta/Investment Committee Agent
Receives structured outputs from strategy agents and produces a ranked set of trade proposals with explicit reasons, confidence and invalidation conditions.

### 7. Post-Trade Review Agent
Performs qualitative attribution after a position closes. It may recommend research changes but may not alter live strategy logic automatically.

## Deterministic Boundaries

The following are never delegated to an LLM:
- account NAV calculation
- current positions
- hard exposure limits
- order sizing caps
- slippage limits
- stop-loss enforcement
- drawdown circuit breakers
- signing policy
- kill switch
- order state reconciliation

## Agent Contract

All agent outputs must be JSON-compatible, versioned and auditable. A canonical trade proposal should include:

```json
{
  "proposal_id": "uuid",
  "asset": "SOL-USDT",
  "direction": "long",
  "strategy": "narrative_momentum",
  "confidence": 0.74,
  "entry": {"type": "limit", "price": 150.0},
  "invalidation": {"price": 143.5},
  "target": {"price": 164.0},
  "max_risk_pct_nav": 0.5,
  "evidence": [],
  "source_timestamps": {}
}
```

## Design Principle

LLMs generate hypotheses and interpret context. Deterministic services calculate, validate, constrain and execute.
