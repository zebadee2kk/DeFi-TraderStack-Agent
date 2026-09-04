# Execution Architecture

## Decision

Use Hummingbot as the preferred execution abstraction for the MVP, with direct exchange/DEX integration retained as an escape hatch where connector capability or reliability requires it.

## Execution Path

```text
Validated market data (tick + independent references + candle history)
   + External intelligence (Dune on-chain, LunarCrush social, CryptoPanic/Perplexity news)
   -> Feature vector merge + deterministic news rule (adverse event => no new risk)
   -> Pre-trade backtest gate (strategy confirmation, backtest, walk-forward)
   -> Trade Proposal
   -> Portfolio Allocator
   -> Deterministic Risk Engine
   -> Execution Planner
   -> Hummingbot API / Gateway
   -> Venue
   -> Fill/Reconciliation
```

### External intelligence in the loop

`PaperRuntime` gathers on-chain, social and news snapshots for the asset each
cycle through `IntelligenceOrchestrator.gather` (concurrent, cached for
`INTELLIGENCE_CACHE_SECONDS`, each provider failure isolated). The pipeline
merges them into the `AssetFeatureVector` alongside market features, then
applies two deterministic rules before any proposal exists:

- `INTELLIGENCE_BLOCK_ON_ADVERSE_NEWS=true` (default): an `adverse_event` from
  the news providers rejects the cycle with `adverse_news_event`.
- `INTELLIGENCE_REQUIRED=true`: a cycle with no external intelligence at all
  is rejected with `no_external_intelligence` rather than trading on market
  data alone.

Providers are assembled from whichever credentials are present
(`DUNE_API_KEY` + `DUNE_QUERY_IDS`, `LUNARCRUSH_API_KEY`, `CRYPTOPANIC_API_KEY`,
`PERPLEXITY_API_KEY`). Retrieved text never reaches the pipeline: each adapter
reduces its source to bounded numeric features, which is the prompt-injection
boundary from the threat model.

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

### Implemented

The lifecycle above is enforced in code by `traderstack.execution`.

**Planner** (`execution/planner.py`) — pure and side-effect free.
`ExecutionPlanner.plan` converts an approved `PaperOrderIntent` plus an
execution price into one venue child order:

- quantity is floored to `EXECUTION_LOT_STEP` (never rounded up, so a plan can
  never exceed the approved notional) and rejected if it rounds to zero;
- the resulting notional must reach `EXECUTION_MIN_NOTIONAL_USD`;
- the execution price must be within `EXECUTION_MAX_SLIPPAGE_BPS` of the
  pipeline's validated tick, in *either* direction — a suspiciously favourable
  price is a data-integrity signal, not a gift;
- a deterministic `client_order_id` (the idempotency key) and `correlation_id`
  are derived from `decision_id` alone, so two processes, or the same process
  after a restart, mint identical identifiers for the same decision.

Every rejection is terminal for that decision: the planner never resizes,
relaxes a bound or retries.

**Ledger and state machine** (`execution/ledger.py`, `execution/ledger_store.py`).
`OrderLifecycleState` carries the full documented lifecycle —
`PLANNED`, `SUBMITTED`, `ACKNOWLEDGED`, `OPEN`, `PARTIALLY_FILLED`, `FILLED`,
`CANCELLED`, `REJECTED`, `EXPIRED` — plus `SUBMISSION_UNCERTAIN` for the
timeout case below. `ExecutionLedger.update_order_state` and `record_fill`
enforce a transition table: the four terminal states never reopen, nothing
moves backwards (a `PARTIALLY_FILLED` order can never return to `SUBMITTED`),
an `ACKNOWLEDGED` order can never become uncertain again, and re-asserting the
current state is a no-op so repeated reconciliation passes are safe. Illegal
transitions raise `IllegalStateTransition` and are refused before any quantity
is mutated. `JsonExecutionLedgerStore` persists the ledger alongside the
portfolio checkpoint (`--ledger-path`, default `var/state/execution_ledger.json`)
with the same atomic-write discipline, and is written after every mutation.

**Idempotent submission** (`execution/submitter.py`). `IdempotentSubmitter`
writes the `PLANNED` order to the ledger *before* calling the venue, so a crash
mid-submission still leaves evidence the decision was acted on. A decision that
already has a ledger order in any state is refused outright — including after a
process restart, because the ledger is loaded at startup. The client order id is
sent to Hummingbot, but idempotency does not depend on the venue honouring it;
the persistent ledger is the authoritative duplicate guard.

**Retry and timeout.** Submission is wrapped in
`EXECUTION_SUBMIT_TIMEOUT_SECONDS`. A timeout, transport failure or 5xx marks
the decision `SUBMISSION_UNCERTAIN` and stops there. No retry is permitted until
a reconciliation pass has confirmed the venue does not know the client order id;
if reconciliation itself is unavailable the order simply stays uncertain. Once
absence is confirmed, retries are bounded by `EXECUTION_MAX_RETRIES` with
exponential backoff, and exhausting them marks the order `REJECTED` with the
reason recorded. A 4xx is a permanent rejection with no retry, and safety
violations (non-paper mode, non-`_paper_trade` connector) are refused before
anything is written or sent.

**Reconciliation in the service loop.** `ContinuousPaperService` runs
`HummingbotExecutionReconciler` (orders and fills into the ledger and portfolio)
and `HummingbotPortfolioReconciler` (NAV drift against `MAX_NAV_DRIFT_BPS`)
every `RECONCILE_INTERVAL_SECONDS`. A failed pass, an order-state divergence or
NAV drift sets `RuntimeHealth.reconciliation_blocked`, exported as the
`traderstack_reconciliation_blocked` gauge. That flag blocks **new risk only**:
market data, agent decisions, risk evaluation and the audit trail all keep
running and existing positions are untouched. The next clean pass clears it.

A venue snapshot that merely lags local state (still "open" while a partial fill
is already booked) is tolerated; a venue that contradicts a *terminal* local
state is reported as a conflict and blocks.

**Hummingbot API caveat.** `hummingbot-api`'s `TradeRequest` (verified against
`models/trading.py`, September 2026) has no client-order-id field at all — it
accepts `account_name`, `connector_name`, `trading_pair`, `trade_type`,
`amount`, `order_type`, `price`, `position_action` and mints its own `order_id`.
The key is still sent as `client_order_id` (an assumed name, inert on today's
API) for any connector or future version that honours it. Because of this,
`venue_knows_order` also treats an order the ledger cannot account for that
matches the planned pair/side/quantity as "the venue knows it" — the fail-closed
reading, since concluding "not found" would license a resubmission.

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
