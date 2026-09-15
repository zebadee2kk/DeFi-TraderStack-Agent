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
- immutable audit logs, with the chain head anchored outside the file (below)
- emergency kill switch outside the LLM runtime

### Audit-trail root of trust (#68)

The risk-decision trail is SHA-256 hash-chained, which makes any edited,
removed or reordered *line* detectable. It does not make a whole-file rewrite
detectable, because the chain's only root of trust is the file itself: an
attacker — or a well-meaning operator — with write access to `var/audit/` can
regenerate the chain from genesis with different content and it verifies
perfectly. Since this threat model assumes the host may be compromised, that
gap sat directly under the system's central claim of "a complete auditable
decision trail".

The boundary is now the anchor: `{sequence, head_hash, policy_version,
anchored_at}` is published periodically, and on shutdown, to sinks outside the
audit file. `traderstack-verify-audit` verifies the chain **and** cross-checks
every anchor against it, reporting the sequence number of divergence. To forge
a trail an attacker must now also forge every anchor in every channel.

Where the anchor lives determines how much it is worth:

| Sink | Root of trust |
|---|---|
| local JSONL (`JsonlAuditAnchorStore`) | same host, same process — two files to forge instead of one. Fine for tests and local runs; not a real boundary |
| Redis / Postgres with an insert-only grant for the app role | off-process. The trading process can append an anchor but cannot rewrite one |
| operator-held remote receiver | off-host. The strongest of the three, and the only one that survives full host compromise |

Two postures apply, deliberately opposite. **Publishing** is evidence, so a
sink being down is counted on `traderstack_audit_anchor_failures_total` and
never blocks a trading cycle. **Verification** fails closed: a divergent
anchor, an unreadable trail, or no anchors at all is a failure, because an
intact chain with nothing to check it against proves only internal
consistency.

Not yet closed: anchors are not themselves signed with a key the runtime does
not hold, so an attacker who compromises both the trail and an anchor store
can still produce a consistent pair. Signing to an operator-held key is the
remaining step (#68, item 4).

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
