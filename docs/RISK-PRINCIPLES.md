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

## Implemented controls

Every control below is deterministic code in the Zone C control plane. Each is
configured only from version-controlled settings (`Settings` / `.env`), and each
emits a fixed reason string that appears verbatim in `RiskResult.reasons` and in
the risk audit trail. No runtime message can change a limit, and no reason
string can be argued away.

| Layer | Control | Setting | Reason string | Implementation |
| --- | --- | --- | --- | --- |
| 1 Global halt | Operator kill switch (settings flag) | `KILL_SWITCH` | `kill_switch_enabled` | `killswitch.py` |
| 1 Global halt | Operator kill switch (sentinel file) | `KILL_SWITCH_FILE` | `kill_switch_enabled` | `killswitch.py`, `traderstack-kill` / `traderstack-resume` |
| 1 Global halt | Operator kill switch (Redis key) | `KILL_SWITCH_REDIS_KEY`, `KILL_SWITCH_REDIS_ENABLED` | `kill_switch_enabled` | `killswitch.py` |
| 1 Global halt | Operator kill switch (SIGUSR1) | — (signal) | `kill_switch_enabled` | `killswitch.py` |
| 2 Account/portfolio | Stale-state shutdown | `MAX_PORTFOLIO_STATE_AGE_SECONDS` | `stale_portfolio_state` | `risk.py` |
| 2 Account/portfolio | Maximum daily loss | `MAX_DAILY_LOSS_PCT` | `daily_loss_limit_reached` | `risk.py`, anchored by `portfolio.py` |
| 2 Account/portfolio | Maximum rolling drawdown | `MAX_ACCOUNT_DRAWDOWN_PCT` | `account_drawdown_limit_reached` | `risk.py` |
| 2 Account/portfolio | Maximum gross exposure | `MAX_GROSS_EXPOSURE_PCT` | `gross_exposure_limit` | `risk.py` |
| 2 Account/portfolio | Minimum cash reserve | `MIN_CASH_RESERVE_PCT` | `cash_reserve_breached` | `risk.py` |
| 2 Account/portfolio | Maximum simultaneous positions | `MAX_OPEN_POSITIONS` | `max_positions_reached` | `risk.py` |
| 3 Strategy | Maximum consecutive losses | `STRATEGY_MAX_CONSECUTIVE_LOSSES` | `strategy_circuit_breaker` | `circuit_breaker.py` |
| 3 Strategy | Rolling drawdown over the last N closed trades | `STRATEGY_DRAWDOWN_WINDOW`, `STRATEGY_MAX_ROLLING_DRAWDOWN_PCT` | `strategy_circuit_breaker` | `circuit_breaker.py` |
| 3 Strategy | Suspension cool-down | `STRATEGY_BREAKER_COOLDOWN_SECONDS` | `strategy_circuit_breaker` | `circuit_breaker.py` |
| 4 Asset/venue | Symbol allowlist | `MVP_ASSETS` | `asset_not_allowlisted` | `risk.py` |
| 4 Asset/venue | Maximum spread | `RISK_MAX_SPREAD_BPS` | `spread_too_wide` | `risk.py` |
| 5 Trade | Maximum position notional | `MAX_POSITION_PCT` | `position_limit_reached`, `position_size_reduced` | `risk.py` |
| 5 Trade | Cap a reducing SELL to held exposure | (existing exposure; not a new Settings field) | `sell_capped_to_position` | `risk.py` |
| 5 Trade | Volatility-targeted sizing | `VOLATILITY_SIZING_ENABLED`, `TARGET_VOLATILITY` | `volatility_scaled` | `risk.py` |
| 5 Trade | Stop-loss vs average cost | `EXIT_STOP_LOSS_PCT` | `exit_stop_loss` | `exits.py` |
| 5 Trade | Trailing stop vs high-water | `EXIT_TRAILING_STOP_PCT` | `exit_trailing_stop` | `exits.py` |
| 5 Trade | Take-profit vs average cost | `EXIT_TAKE_PROFIT_PCT` | `exit_take_profit` | `exits.py` |
| 5 Trade | Maximum holding period | `EXIT_TIME_STOP_BARS` | `exit_time_stop` | `exits.py` |
| 5 Trade | Thesis invalidated | `EXIT_ON_THESIS_INVALIDATION` | `exit_thesis_invalidated` | `exits.py` |
| Evidence | Immutable risk-decision audit trail | `RISK_AUDIT_PATH` | — | `risk_audit.py` |
| Evidence | Policy versioning | `RISK_POLICY_LABEL` + digest of all limits | — | `risk.py` |

Notes on the implemented semantics:

- **Daily means daily.** `PortfolioState` persists a `day_start_nav_usd` /
  `day_start_date` anchor that rolls at UTC midnight, so `MAX_DAILY_LOSS_PCT`
  measures the current day rather than PnL since inception.
- **Volatility targeting only reduces.** Approved notional is scaled by
  `TARGET_VOLATILITY / observed volatility`, capped at 1.0 and then at the
  position limit. Scaling *up* would have the risk engine inventing risk nobody
  proposed, which the control hierarchy does not permit.
- **The kill switch is live, not static.** The risk engine consults the
  `KillSwitch` object, which is re-probed at the start of every service cycle. A
  sentinel file created by an operator therefore takes effect on the next cycle
  with no restart, no API call and no cooperation from the agent runtime. An
  unreachable Redis halt channel is treated as engaged.
- **Policy version is derived.** `RiskEngine.policy_version` is
  `RISK_POLICY_LABEL` plus a SHA-256 digest of every risk limit in force
  (`RISK_LIMIT_FIELDS`), including the pre-trade, market-data, execution-planner
  and Robinhood Chain policy settings enforced *around* the engine
  (SEC-2026-09-18), so any of those changing is visible in every audit record
  without anyone remembering to bump a string.
- **Every decision is evidence.** Each `evaluate` result recorded by the service
  is appended to a hash-chained JSONL file carrying the proposal, the full
  result, the policy version and the limits in force (inline and hashed).
  `risk_audit.verify_chain` detects any edited, removed or reordered line.
- **Adversarial coverage.** `tests/test_risk_adversarial.py` asserts that absurd
  notionals, non-allowlisted assets and proposals arriving while the kill switch
  file exists are rejected regardless of confidence, signal ids or thesis text,
  including thesis text that instructs the system to raise its own limits.
  Thesis or signal ids claiming "this is a reduce" cannot reclassify an
  uncovered SELL as risk-reducing; classification is derived from
  `PortfolioSnapshot` only.
- **Risk-reducing exits.** A SELL is risk-reducing only when the observed
  book already has positive exposure in that asset. Additive limits
  (`gross_exposure_limit`, `cash_reserve_breached`, `max_positions_reached`,
  `position_limit_reached`) and volatility scaling do not block or resize
  those exits; daily-loss and drawdown are recorded as informational
  reasons. The kill switch, stale-state shutdown, strategy breaker
  (discretionary strategies only), allowlist and spread gates still
  reject. Approved notional is never larger than the exposure held.
  Deterministic `exit-*` proposals skip the entry-strategy circuit
  breaker so a run of stop-losses cannot freeze the flatten path; the
  kill switch is unchanged.
- **Position-management exits.** `exits.py` evaluates stop-loss,
  take-profit, optional trailing stop, time-stop (`EXIT_TIME_STOP_BARS`
  × the candle interval) and optional thesis invalidation against
  checkpointed `opened_at` / average cost / high-water. Paper and
  shadow run the rules (paper-conservative defaults); live ignores
  them. Each fired rule becomes a reducing SELL through
  `RiskEngine.evaluate`. The meta-agent cannot veto an exit. The exit
  settings are in `RISK_LIMIT_FIELDS`, so `policy_version` moves when
  they change.

## Failure behaviour

The default response to uncertainty, inconsistent state, expired market data, failed reconciliation, unavailable risk service, or signing-service anomalies is **no new risk**.

A strategy-driven SELL against observed long exposure is the implemented
deterministic reduce path: it may pass additive limits so the book can
de-risk, and is separately tested (`tests/test_risk.py`,
`tests/test_risk_reducing_exits.py`, `tests/security/`). Stop-loss,
take-profit and time-stop position management (`exits.py`) emit the
same reducing path and are separately tested (`tests/test_exits.py`,
`tests/acceptance/test_position_exits.py`, `tests/security/`). Operator
flatten remains separate work.

## Key custody

- CEX API credentials should exclude withdrawal permissions.
- Private keys must not be exposed to LLM context or ordinary MCP/tool processes.
- On-chain signing should be isolated behind a narrow policy-controlled service or smart-account mechanism.
- Development and paper environments must use dedicated credentials/wallets.

## Promotion gates

Risk limits may become less conservative only through explicit version-controlled configuration changes after review. Agents cannot autonomously increase their own limits because recent performance was strong.
