# Security and Threat Model

## Security Goal

Assume any external data source, MCP server, LLM response or community package can be wrong, compromised or malicious. Protect funds even when the intelligence layer fails.

## Trust Zones

### Zone A — Public/Untrusted Intelligence
TradingView MCP, Dune, Perplexity, altFINS, CoinGecko, CryptoPanic, CoinMarketCap, LunarCrush and community MCPs.

### Zone B — Agent Runtime
Claude and supporting models. No direct unrestricted signing authority.

### Zone C — Deterministic Control Plane
Portfolio state, risk policy, order validation and execution policy. This is higher trust and has no LLM-controlled configuration mutation.

### Zone D — Signing/Custody
Exchange API credentials and on-chain signing. Isolated from the agent runtime.

## Principal Threats

- prompt injection in news, social posts, websites or MCP responses
- malicious/compromised MCP server
- dependency/supply-chain compromise
- hallucinated or stale market data
- price-feed manipulation
- credential exfiltration
- unrestricted wallet signing
- exchange API abuse
- compromised agent attempting policy changes
- race conditions/double execution
- replayed events
- poisoned backtest data
- leakage/look-ahead bias mistaken for alpha
- runaway API/token cost

## Mandatory Controls

- MCP/tool allowlist and pinned versions/commits where practical
- isolated containers and minimal network egress
- secrets injected at runtime, never stored in prompts/repository
- exchange API keys without withdrawal permissions
- dedicated subaccount for the bot
- explicit symbol/venue allowlists
- deterministic transaction/order policy checks
- idempotency keys for execution
- reconciliation against venue state
- transaction simulation before on-chain execution
- hardware/isolated signing where feasible
- rate/spend limits at wallet or smart-account layer
- immutable audit logs
- emergency kill switch outside the LLM runtime

## Prompt Injection Boundary

All retrieved text is data, never authority. External content cannot grant permissions, alter policy, request credentials, change tool configuration or instruct execution. The orchestrator must preserve this separation in system/tool policy.

## Failure Policy

Execution fails closed when:
- market data is stale or divergent
- risk service is unavailable
- position state cannot be reconciled
- signing service health is unknown
- required provider quorum is not met
- duplicate/correlation state is ambiguous

## On-Chain Custody

Production on-chain execution should use a constrained smart account/multisig architecture with spending caps and allowlisted contracts rather than an unrestricted EOA private key exposed to an agent process.
