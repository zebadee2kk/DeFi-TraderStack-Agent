# Roadmap

## Phase 0 — Architecture and research

Deliverables:
- project charter
- high-level design
- component decision log
- threat model
- initial risk policy
- data-source inventory and API/cost matrix
- venue shortlist
- strategy research plan

Exit gate: architecture review complete; no unresolved blocker affecting safe paper deployment.

## Phase 1 — Reproducible research environment

Build:
- containerised development environment
- PostgreSQL/time-series/Redis services
- research dataset format
- Freqtrade integration
- benchmark strategies
- backtest reporting
- look-ahead/leakage checks
- experiment metadata/versioning

Exit gate: baseline results reproduce from a clean environment.

## Phase 2 — Market-data and feature platform

Build:
- direct exchange feed adapter(s)
- CoinGecko/CMC adapters
- Dune ingestion
- CryptoPanic/news adapter
- LunarCrush/social adapter
- altFINS adapter
- freshness/quality monitoring
- normalised schemas
- feature engine
- regime classifier v1

Exit gate: deterministic feature replay produces the same features for the same historical input.

## Phase 3 — Strategy framework

Implement independently testable strategies:
- momentum/trend
- breakout
- mean reversion baseline
- on-chain flow
- narrative/social momentum
- event/news
- optional funding/basis

Add:
- TradeCandidate schema
- per-strategy performance attribution
- strategy versioning
- candidate confidence calibration

Exit gate: candidate generation works without execution privileges.

## Phase 4 — Agent intelligence

Build:
- Claude tool/MCP gateway
- evidence retrieval
- structured LLM schemas
- specialist analysis agents
- meta-agent/challenger design
- model routing/cost controls
- prompt/version audit trail

Research A/B tests:
- deterministic weighting vs Claude meta-agent
- market-only vs market + news
- market-only vs market + on-chain
- market-only vs market + social

Exit gate: LLM components demonstrate measurable incremental value or are demoted to explanatory/research roles.

## Phase 5 — Portfolio and deterministic risk plane

Build:
- portfolio state service
- allocation/risk budgets
- concentration/correlation controls
- hard trade rules
- drawdown guards
- circuit breakers
- stale-state protections
- global kill switch
- policy versioning

Exit gate: adversarial tests demonstrate that agents cannot bypass controls.

## Phase 6 — Hummingbot paper execution

Build:
- Hummingbot API/MCP/Gateway integration
- order lifecycle state machine
- reconciliation
- realistic costs/slippage
- paper exchange/venue setup
- monitoring and alerts

Exit gate: sustained unattended paper operation without unreconciled state or risk-control failures.

## Phase 7 — Shadow-live validation

Consume live feeds and make live-time decisions without placing real orders. Compare hypothetical fills against market reality and paper execution.

Exit gate: statistically adequate sample with acceptable execution assumptions and stable operations across market conditions.

## Phase 8 — On-chain security path

Only if DeFi execution remains justified:
- isolated signer
- test wallet
- transaction simulation
- smart-account/guard policy
- token/contract/chain allowlists
- spending caps
- failure/recovery exercises

Exit gate: security review and adversarial transaction tests pass.

## Phase 9 — Tiny-capital live pilot

Use a deliberately small risk budget and conservative limits. No leverage initially.

Requirements:
- human-visible kill switch
- alerting
- daily reconciliation
- strategy-specific limits
- automatic drawdown halt
- immutable production risk policy during each deployment

Exit gate: live behaviour matches paper/shadow assumptions closely enough to justify any scale increase.

## Phase 10 — Controlled scale and continuous research

Scale only through explicit reviewed configuration changes. New strategies repeat the full research/paper/shadow pipeline. Production agents cannot promote themselves or increase their own capital allocation.
