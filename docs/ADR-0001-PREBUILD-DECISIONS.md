# ADR-0001 — Pre-build Architecture Decisions

Status: Accepted for MVP design

## Decisions

1. **Runtime language:** Python 3.12 for orchestration, data, signals, risk and adapters.
2. **Execution spine:** Hummingbot API/Gateway. Claude and other LLMs never talk directly to exchange credentials.
3. **Research harness:** Freqtrade for reproducible directional-strategy research, lookahead checks and dry-run comparison.
4. **Primary storage:** PostgreSQL with TimescaleDB extension for canonical time-series/decision data; Parquet object files for research datasets; Redis only for ephemeral cache/coordination.
5. **Workflow model:** event-driven services. Temporal is the preferred durable workflow engine after MVP baseline; MVP may begin with an internal async event bus while preserving interfaces for Temporal adoption.
6. **LLM boundary:** Claude is a reasoning/meta-agent. All proposals must be schema-valid and pass a deterministic risk service that cannot be bypassed by prompts or tool calls.
7. **MVP venue:** centralized-exchange paper trading through Hummingbot first. DEX/on-chain execution is Phase 2 after risk and signing controls are proven.
8. **MVP universe:** BTC, ETH and SOL quoted against a stable quote asset, subject to venue support. Universe expansion is configuration-driven, not agent-controlled.
9. **MVP strategies:** simple momentum/trend, on-chain-informed directional, and narrative/news-informed directional candidates. Each must beat or add value versus simple baselines in leakage-controlled evaluation before live promotion.
10. **Capital:** zero real capital for MVP. Paper NAV starts at a configurable synthetic balance. Tiny-capital live trading requires a separate promotion decision and hard cap.
11. **Secrets:** never committed. Exchange credentials use least privilege and no withdrawal permission. Signing services are isolated from LLM/runtime containers.
12. **Observability:** OpenTelemetry-compatible structured traces, Prometheus metrics and immutable decision IDs from signal to fill.

## Rejected for critical path

- TradingView Desktop MCP as a production execution dependency.
- Archived GOAT SDK as a production executor.
- Direct LLM-issued wallet or exchange transactions.
- Single-agent `while true: ask model what to buy` architecture.
- Self-modifying live trading rules without offline evaluation and promotion gates.

## Consequences

The system is intentionally slower and more constrained than an unrestricted agent, but decisions become reproducible, testable and recoverable. Intelligence providers may fail without compromising execution safety. Risk and reconciliation remain functional even if Claude is unavailable.