# Project Charter

## Mission

Design and build a secure, testable, autonomous crypto/DeFi trading research and execution platform that operates continuously while separating AI reasoning from deterministic portfolio, risk, and execution controls.

## Primary objective

Determine whether combining quantitative market features, on-chain intelligence, social/news signals, and LLM reasoning can generate persistent risk-adjusted alpha after fees, slippage, latency, and realistic execution constraints.

## Scope

### In scope
- crypto spot and selected DeFi markets
- event-driven data ingestion and signal generation
- Claude-led research/meta-reasoning
- multiple specialist strategy agents
- deterministic portfolio construction
- deterministic risk policy and circuit breakers
- Hummingbot-based execution
- research/backtesting using Freqtrade and custom tooling
- paper, shadow-live, and controlled live deployment
- full decision provenance, observability, and replay

### Out of scope for initial phases
- managing third-party funds
- investment advice or client-facing recommendations
- unrestricted autonomous wallet authority
- high-frequency/latency-arbitrage strategies
- self-modifying live strategies
- leverage until separately risk-approved

## Core hypotheses

1. Multi-source structured features outperform raw LLM interpretation of unstructured feeds.
2. Specialist strategy agents plus a meta-agent are more robust than a monolithic trading agent.
3. LLMs add the most value in context, event interpretation, narrative synthesis, and regime-aware strategy selection rather than tick-level execution.
4. Deterministic risk controls materially reduce catastrophic failure modes without removing useful AI discretion.
5. Any proposed AI advantage must remain after comparison to simple non-AI baselines.

## Success criteria

A strategy may progress toward live capital only when it demonstrates:
- no detected look-ahead/data leakage defects;
- positive out-of-sample expectancy after realistic costs;
- acceptable drawdown and tail-risk behaviour;
- stable performance across multiple market regimes;
- successful paper and shadow-live operation;
- complete auditable decision/execution records;
- tested failure recovery and emergency shutdown.

## Design principles

1. **Risk engine outranks every agent.**
2. **Execution uses least privilege.**
3. **Market data used for execution comes from the execution venue where possible.**
4. **MCPs are intelligence adapters, not trusted control planes.**
5. **Every signal has provenance and freshness metadata.**
6. **Every strategy is independently measurable.**
7. **LLM output is structured, validated, and bounded.**
8. **No strategy promotion without out-of-sample evidence.**
9. **Failures should default to no new risk.**
10. **Human operators retain a global kill switch.**
