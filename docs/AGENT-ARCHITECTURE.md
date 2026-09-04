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

## Implemented (Epic 6)

The agent runtime exists in code; not every agent in the topology above is built
yet, and the ones that are do less than the sketch implies. What ships today:

| Component | Module | LLM? |
| --- | --- | --- |
| Technical strategy agent | `agents/specialists.py` — `TechnicalSpecialist` | no |
| On-chain strategy agent | `agents/specialists.py` — `OnChainSpecialist` | no |
| Narrative/sentiment agent | `agents/specialists.py` — `NarrativeSpecialist` | no |
| Specialist committee | `agents/specialists.py` — `SpecialistCommittee` | no |
| Meta/investment-committee agent | `agents/meta.py`, `agents/review.py` | yes |
| Claude model abstraction | `agents/claude.py` — `AnthropicMetaAgentClient` | — |
| Prompt/version registry | `agents/prompts.py` — `PromptRegistry` | — |

### Specialist agents are deterministic

Each specialist reads one slice of the `AssetFeatureVector` (market / on-chain /
narrative + news) and emits a `StrategySignal`. They call no model, so they are
reproducible, effectively free, and degrade to "no signal" — never to an invented
one — when a provider is missing. Every threshold is a constructor parameter.
`SpecialistCommittee.consensus` delegates to `StrategyEnsemble.consensus`, so the
committee agrees with the baseline quant ensemble by construction rather than by
convention.

### The meta-agent is a review stage, not a decision stage

`PaperRuntime.run_once` runs pipeline → **meta-agent review** → execution. By the
time the model is asked anything, the side, the asset, the requested notional and
the risk-approved notional are already fixed. The reviewer receives an
`EvidencePacket` of bounded numeric features and structured fields — market /
on-chain / narrative features, the pre-trade backtest and walk-forward summary,
each specialist's signal, and the risk engine's own decision and reasons — and
may only:

* veto the cycle, or
* approve it and shift confidence within the `MetaAgentDecision` bound (±0.15).

It cannot choose a side, an asset, a venue or a size, and it never edits
`risk_result` or `approved_notional_usd`. Because sizing is settled before the
call, even an approval carrying a positive delta cannot increase notional.

`META_AGENT_MODE` selects the effect:

| Mode | Behaviour |
| --- | --- |
| `off` | never called |
| `advisory` (default) | called and recorded on `RuntimeResult.meta_review`; execution unaffected |
| `veto` | a veto suppresses the paper order with `meta_agent_veto`; a failure suppresses it with `meta_agent_unavailable`; an approval applies the bounded delta |

### Fail-closed and cost control

In veto mode a timeout, an exception, an HTTP error, a refusal or `max_tokens`
stop reason, a schema-invalid reply, a missing client, or an exhausted daily
budget all produce `meta_agent_unavailable` — no new risk. There is no path on
which an unavailable model results in a silent approval.

Spend is bounded three ways: a short-lived cache keyed by a hash of the evidence
packet (identical evidence is not re-asked), daily call and token budgets checked
before the request, and Prometheus counters for reviews, tokens, estimated cost
and suppressed orders (`agents/metrics.py`).

### Prompt provenance

The system prompt lives in `PromptRegistry` with a version string and a SHA-256
content hash; editing the text changes the hash. Every review records
`prompt_version` and `prompt_hash` alongside the model id, latency, token usage
and estimated cost, so any past decision can be traced to the exact instructions
that produced it.

### Evidence is data

The prompt states the boundary explicitly and the packet enforces it: only
bounded numerics and structured enums cross into the model context. Retrieved
text never does.

### Not yet built

The market regime agent and market-data validation agent are covered by
deterministic modules (`strategies.RegimeClassifier`, `market/validation.py`)
rather than by agents. The post-trade review agent and the tool/MCP allowlist are
outstanding; the meta-agent is currently given no tools at all.
