# Execution Architecture

## Decision

Use Hummingbot as the preferred execution abstraction for the MVP, with direct exchange/DEX integration retained as an escape hatch where connector capability or reliability requires it.

## Execution Path

```text
Validated market data (tick + independent references + candle history)
   + External intelligence (Dune on-chain, LunarCrush social, CryptoPanic/Perplexity news, altFINS technical signal)
   -> Feature vector merge + deterministic news rule (adverse event => no new risk)
   -> Pre-trade backtest gate (strategy confirmation, backtest, walk-forward)
   -> Trade Proposal
   -> Deterministic Risk Engine
   -> Constrained meta-agent review (withhold-only; off/advisory/veto)
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
`PERPLEXITY_API_KEY`, `ALTFINS_API_KEY`). Retrieved text never reaches the
pipeline: each adapter reduces its source to bounded numeric features, which
is the prompt-injection boundary from the threat model.

### Two spread limits, deliberately (not a duplicate to consolidate)

`VerticalSlicePipeline.max_spread_bps` (`Settings.max_spread_bps`,
`MAX_SPREAD_BPS`) and `RiskEngine`'s `RISK_MAX_SPREAD_BPS` look like the same
check twice. They are not:

- The pipeline's check (`spread_limit_exceeded`) runs on the raw venue tick
  **before any feature vector or proposal exists** -- it is a market-data
  quality gate, the same tier as `stale_primary_tick` and
  `reference_price_divergence`. It can reject before there is anything for
  the risk engine to evaluate at all.
- The risk engine's check (`spread_too_wide`) runs on the *feature vector's*
  spread reading as tier 4 of the documented control hierarchy
  (`docs/RISK-PRINCIPLES.md`) -- Zone C, version-controlled, never bypassable
  by an LLM, and stamped into `RiskEngine.policy_version` /
  `RISK_LIMIT_FIELDS`. `max_spread_bps` is not a risk-policy field and does
  not move the policy version (the same is true of `max_reference_divergence_bps`
  and `max_market_data_age_seconds`, its siblings in the same market-data tier).

A third, unrelated spread threshold lives in
`agents.specialists.SpecialistCommittee` (`max_spread_bps: float = 25.0`,
hardcoded, no `Settings` field). It never gates anything -- it only shapes one
specialist's advisory signal that the meta-agent reviewer sees as evidence, so
it carries no risk consequence and needs no operator control. Do not confuse
it with either gate above.

Both real gates exist because they answer different questions: "is this tick
usable at all" (pipeline) vs. "is this proposal's execution-quality risk
acceptable" (risk engine, part of the auditable policy). Keep both; do not
fold one into the other.

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

## Cycle order of operations

This is the actual, traced order of `ContinuousPaperService.run` ->
`_run_symbol_safely` -> `PaperRuntime.run_once` for the integrated MVP
(`src/traderstack/service.py`, `src/traderstack/runtime.py`). It exists so a
change to any of the shared files below can be checked against it rather than
against memory.

```text
ContinuousPaperService.run()  (loops until stopped or unhealthy)
 1. _maybe_reconcile()                          -- once per RECONCILE_INTERVAL_SECONDS,
    -> execution + portfolio reconcilers          for the whole cycle, BEFORE any symbol
    -> sets/clears RuntimeHealth.reconciliation_blocked runs. A failed pass or NAV drift
                                                    past MAX_NAV_DRIFT_BPS blocks *new
                                                    submissions* for every symbol this cycle
                                                    (decisions/audit keep running).
 2. for each symbol:
    _run_symbol_safely(symbol):
    2a. _refresh_kill_switch()                  -- re-probes file/Redis/signal channels
                                                    BEFORE the pipeline runs. An unreachable
                                                    Redis channel is treated as engaged.
    2b. submission_enabled = submit AND NOT reconciliation_blocked
                                                    -- the reconciliation gate is evaluated
                                                    and applied HERE, before run_once is even
                                                    called with submit=True/False. Submission
                                                    is gated before it is attempted, not
                                                    cleaned up after.
    2c. PaperRuntime.run_once(symbol, portfolio.snapshot(), submit=submission_enabled):
        i.   fetch venue tick (primary market data)
        ii.  fetch reference prices (CoinGecko/CoinMarketCap, concurrent, isolated failures)
        iii. fetch candle history (if the pre-trade gate is enabled)
        iv.  best-effort candle persistence (--persistent-events; failure never fails the cycle)
        v.   fetch external intelligence (Dune/LunarCrush/CryptoPanic/Perplexity/altFINS,
             concurrent, isolated failures, cached)
        vi.  fetch order-book snapshot (Kraken only, opt-in, informational -- not consumed
             by the pipeline or risk engine today)
        vii. VerticalSlicePipeline.process(...):
             - market-data validation (stale tick, spread, reference divergence)
             - intelligence merge + adverse-news gate (deterministic, before any proposal)
             - pre-trade backtest gate (strategy re-confirmation, backtest, walk-forward)
             - TradeProposal construction
             - RiskEngine.evaluate(...)          -- Zone C. Kill switch is check #1 here,
                                                     checked on *every* evaluated proposal,
                                                     submission or not. This is the layer that
                                                     can never be relaxed by an LLM.
             - PaperOrderIntent, if ALLOW/REDUCE with approved_notional_usd > 0
        viii. MetaAgentReviewer.run(symbol, pipeline_result)   -- Epic 6. Runs strictly AFTER
             risk sizing is fixed, strictly BEFORE submission. It can only *withhold* an
             already-approved order (null paper_order, append a rejection reason -- veto mode)
             or nudge confidence within a bounded delta (advisory mode changes nothing at all).
             It never re-sizes, re-sides or authorises anything risk did not already approve.
        ix.  record_pipeline_result(...)          -- metrics recorded against the RESULT OF
             STEP viii (post meta-agent), so a vetoed cycle counts its veto reason, not the
             pre-veto risk decision alone.
        x.   if submit and paper_order is not None: submit via IdempotentSubmitter (ledger
             write PLANNED before the venue call; planner checks lot/notional/slippage;
             timeout/5xx -> SUBMISSION_UNCERTAIN, no retry until reconciliation resolves it)
        xi.  return RuntimeResult(tick, pipeline_result, meta_review, execution_receipt,
             execution_status, execution_reason, ...)
    2d. mark the portfolio at the tick's last price; compute + publish the NAV/cash gauges
    2e. register the execution receipt in the ledger (bare-executor path only -- the
        submitter already registered it under the client order id before the venue call)
    2f. _record_risk_decision(result)             -- append to the hash-chained risk audit
        trail. The record carries `result` (the risk engine's own decision) AND
        `meta_review`/`execution_status`/`execution_reason` from the SAME cycle, so an ALLOW
        that was subsequently vetoed is legible on one line, not only inferable by
        cross-referencing the runtime audit log separately.
    2g. checkpoint the portfolio (on_portfolio)    -- BEFORE the event fan-out (Epic 10).
        This is the durable local state a restart resumes from; on_result fans out to
        remote sinks (Postgres/Redis) that can be down far longer than a local write. Saving
        the checkpoint first means a downstream sink outage can never leave the checkpoint
        ahead of -- or silently behind -- the execution ledger, which the submitter persists
        regardless of the sinks' health.
    2h. fan out RuntimeResult to on_result sinks   -- JsonlAuditSink always; Postgres +
        Redis additionally under --persistent-events. A sink failure is counted
        (record_event_sink_failure) and re-raised, which trips health.record_error below.
    2i. health.record_success(symbol)
    -- on any exception in 2a-2i: health.record_error(symbol, exc); back off
       error_backoff_seconds. 5 consecutive errors on one symbol stops the whole service
       (ContinuousPaperService.run), not only that symbol.
 3. sleep cycle_interval_seconds (or until stopped), then repeat from 1.
```

**Invariants this order encodes, and that any change to `service.py`,
`runtime.py`, `pipeline.py`, `health.py` or `risk_audit.py` must preserve:**

1. The kill switch and the reconciliation gate are both evaluated **before**
   any submission is attempted this cycle -- the kill switch inside
   `RiskEngine.evaluate` (step vii, Zone C, unconditionally on every
   proposal), and reconciliation via `submission_enabled` (step 2b, computed
   before `run_once` is even called with `submit=`). Neither is a
   post-submission cleanup step.
2. The meta-agent (step viii) runs strictly after risk sizing is fixed and
   strictly before submission (step x), so it can only ever remove risk the
   deterministic engine already approved, never add or resize it.
3. Every metric and audit record that reflects "what happened this cycle"
   (`record_pipeline_result`, the risk audit trail) is built from the
   **post-review** result, not the pre-review one -- a veto is never silently
   dropped between the risk engine's decision and what gets recorded.
4. The portfolio checkpoint is written before the event fan-out, so the
   locally-resumable state never depends on a remote sink's availability.

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
