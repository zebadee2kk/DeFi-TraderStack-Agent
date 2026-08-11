# Execution Architecture

## Decision

Use Hummingbot as the preferred execution abstraction for the MVP, with direct exchange/DEX integration retained as an escape hatch where connector capability or reliability requires it.

## Execution Path

```text
Trade Proposal
   -> Portfolio Allocator
   -> Deterministic Risk Engine
   -> Execution Planner
   -> Hummingbot API / Gateway
   -> Venue
   -> Fill/Reconciliation
```

## Responsibilities

### Execution Planner
- converts approved portfolio intent into venue-specific child orders
- chooses passive/aggressive order style according to policy
- applies size, slippage and liquidity constraints
- assigns idempotency/correlation identifiers

### Hummingbot
- standardized venue connector layer
- order placement/cancellation
- market/position access
- CEX and supported DEX execution

### Reconciliation Service
Venue state is authoritative for execution. The service continually compares local orders/positions against venue state and blocks new risk if state diverges.

## Order Lifecycle

1. APPROVED
2. PLANNED
3. SUBMITTED
4. ACKNOWLEDGED
5. PARTIALLY_FILLED
6. FILLED / CANCELLED / REJECTED / EXPIRED
7. RECONCILED

No assumption may be made that an API timeout means an order failed. Reconciliation is required before retrying.

## Paper and Live Separation

Paper, shadow and live environments require different credentials and database namespaces. Live keys must never be accepted by development configuration.

## Venue Credentials

For CEX operation:
- trading permission only
- withdrawals disabled
- dedicated bot subaccount where available
- IP allowlisting where supported
- strict API-key rotation procedure

## DEX Execution

DEX production path requires:
- approved routers/contracts only
- quote expiry
- maximum price impact
- gas ceiling
- transaction simulation
- nonce management
- smart-account spending limits
- post-transaction receipt reconciliation

## GOAT / Community MCP Position

GOAT SDK MCP and community execution-capable MCPs are research/integration references, not the primary production execution authority. They may be tested in isolated test-wallet environments only until explicitly promoted by an architecture decision record.
