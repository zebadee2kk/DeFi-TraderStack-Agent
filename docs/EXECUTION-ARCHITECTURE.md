# Execution Architecture

## Decision

Use Hummingbot as the preferred execution abstraction for the MVP, with direct exchange/DEX integration retained as an escape hatch where connector capability or reliability requires it.

## Execution Path

```text
Validated market data (tick + independent references + candle history)
   -> Pre-trade backtest gate (strategy confirmation, backtest, walk-forward)
   -> Trade Proposal
   -> Portfolio Allocator
   -> Deterministic Risk Engine
   -> Execution Planner
   -> Hummingbot API / Gateway
   -> Venue
   -> Fill/Reconciliation
```

### Pre-trade backtest gate

`traderstack.pretrade.PreTradeBacktestGate` runs before a proposal is even
constructed. Given the asset's recent candle history it:

1. rejects if history is missing, shorter than `PRETRADE_MIN_CANDLES`, or older
   than `PRETRADE_MAX_CANDLE_AGE_SECONDS`;
2. re-evaluates the deterministic strategy ensemble on those candles and
   rejects unless there is a consensus side (and, if a side was proposed,
   unless it matches);
3. backtests the ensemble over the same history net of
   `PRETRADE_FEE_BPS` + `PRETRADE_SLIPPAGE_BPS` and rejects on excess return
   vs. buy-and-hold, max drawdown, Sharpe or trade-count thresholds;
4. runs rolling walk-forward folds and rejects on out-of-sample excess return
   or worst-fold drawdown (or on too little history, when
   `PRETRADE_REQUIRE_WALKFORWARD=true`).

The gate can only add rejections. It never relaxes the risk engine, and its
thresholds live in version-controlled configuration, not in any agent's
runtime state. The full `PreTradeCheck` (metrics, folds, reasons) is attached
to every `PipelineResult` so each decision is auditable.

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

## Robinhood Chain Scaffolding

`traderstack.execution.robinhood_chain` scaffolds the DEX Execution requirements
above for Robinhood Chain (EVM-compatible) specifically:

- `ChainConfig` / `Settings.robinhood_chain_*` — chain id and RPC URL are always
  operator-supplied from Robinhood's own official chain documentation; nothing
  is hardcoded, and the module fails closed (`ExecutionSafetyError`) if they are
  unset.
- `RobinhoodChainExecutionPolicy` — deterministic token and router allowlists,
  a maximum on-chain notional, and gas-limit/gas-price ceilings.
- `RobinhoodChainExecutor.prepare_swap` — verifies venue/mode, enforces the
  allowlists and notional cap, independently re-checks the connected RPC's
  chain id against configuration, checks wallet balance and nonce, bounds the
  estimated gas and gas price, and simulates the call (`eth_call`) before
  returning an `UnsignedSwapTransaction`.

This executor never signs or broadcasts a transaction and never holds a
private key — it stops at producing a fully policy-checked unsigned
transaction for an isolated signing/custody service to consume. `live` trading
mode is rejected outright: per ADR-0001, DEX/on-chain execution is Phase 2
work, and the isolated signer/smart-account controls in Roadmap Phase 8 do not
exist yet.

## GOAT / Community MCP Position

GOAT SDK MCP and community execution-capable MCPs are research/integration references, not the primary production execution authority. They may be tested in isolated test-wallet environments only until explicitly promoted by an architecture decision record.
