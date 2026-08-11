# Risk Principles

## Non-negotiable rule

**No LLM may modify, disable, bypass, or directly authorise exceptions to production risk policy during runtime.**

Claude and other agents may propose trades and explain their reasoning. Deterministic services decide whether the trade is allowed and at what size.

## Control hierarchy

1. Global system halt / operator kill switch
2. Account and portfolio limits
3. Strategy limits
4. Asset/protocol limits
5. Trade-level validation
6. Execution safeguards

Higher layers always override lower layers.

## Initial controls to design

### Global
- maximum daily loss
- maximum rolling drawdown
- maximum gross/net exposure
- minimum reserve/cash allocation
- maximum number of simultaneous positions
- stale-state shutdown
- operator kill switch

### Strategy
- capital/risk budget
- maximum consecutive losses
- maximum rolling drawdown
- degradation threshold
- minimum live sample size before scale-up
- automatic suspension on abnormal behaviour

### Asset / venue / protocol
- allowlists
- maximum portfolio concentration
- minimum liquidity
- maximum spread
- maximum volatility threshold
- venue health and data freshness
- smart-contract/protocol allowlists

### Trade
- maximum notional
- maximum slippage
- minimum expected reward/risk
- quote divergence checks
- order-book depth/liquidity checks
- stale-price rejection
- duplicate/idempotency protection
- pre-trade reconciliation

### On-chain
- transaction simulation
- destination/token allowlists
- spending limits
- permitted methods/contracts
- gas bounds
- chain ID verification
- independent balance and nonce checks

## Failure behaviour

The default response to uncertainty, inconsistent state, expired market data, failed reconciliation, unavailable risk service, or signing-service anomalies is **no new risk**.

Existing positions may still require predefined emergency close/reduce logic; this must be deterministic and separately tested.

## Key custody

- CEX API credentials should exclude withdrawal permissions.
- Private keys must not be exposed to LLM context or ordinary MCP/tool processes.
- On-chain signing should be isolated behind a narrow policy-controlled service or smart-account mechanism.
- Development and paper environments must use dedicated credentials/wallets.

## Promotion gates

Risk limits may become less conservative only through explicit version-controlled configuration changes after review. Agents cannot autonomously increase their own limits because recent performance was strong.
