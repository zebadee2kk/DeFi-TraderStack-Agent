# Roadmap

> Status lines below are as of **2026-09-04**, against the integrated MVP
> (`src/traderstack/`). See `docs/MVP-BACKLOG.md` for the epic-level checklist
> these summarise, and its "Remaining before live capital" section for the
> single consolidated gap list.

## Phase 0 — Architecture and research

Deliverables:
- project charter
- high-level design
- component decision log
- threat model
- initial risk policy
- data-source inventory and API/cost matrix
- venue shortlist
- strategy research plan

Exit gate: architecture review complete; no unresolved blocker affecting safe paper deployment.

**Status (2026-09-04): Done.** Every listed deliverable exists as a doc in
this directory. The remaining Epic 0 backlog items (`docs/MVP-BACKLOG.md`) are
human sign-off checkboxes, not artefacts to build.

## Phase 1 — Reproducible research environment

Build:
- containerised development environment
- PostgreSQL/time-series/Redis services
- research dataset format
- Freqtrade integration
- benchmark strategies
- backtest reporting
- look-ahead/leakage checks
- experiment metadata/versioning

Exit gate: baseline results reproduce from a clean environment.

**Status (2026-09-04): Mostly done, on a different research harness than
planned.** Docker/Postgres/Redis, benchmark strategies, backtest reporting
(`research/baselines.py`, `research/costs.py`), look-ahead/leakage checks
(`research/leakage.py`), walk-forward (`walkforward.py`) and experiment
attribution (`research/attribution.py`, `research/tuning.py`) are all
implemented, exposed via `traderstack-research` and
`traderstack-download-candles`. **Freqtrade integration was not built** — a
purpose-built research harness was implemented instead; revisit only if
Freqtrade's own connector/strategy ecosystem becomes worth the integration
cost.

## Phase 2 — Market-data and feature platform

Build:
- direct exchange feed adapter(s)
- CoinGecko/CMC adapters
- Dune ingestion
- CryptoPanic/news adapter
- LunarCrush/social adapter
- altFINS adapter
- freshness/quality monitoring
- normalised schemas
- feature engine
- regime classifier v1

Exit gate: deterministic feature replay produces the same features for the same historical input.

**Status (2026-09-04): Done.** Kraken WS v2 (with reconnect/backoff/stale
detection) plus an alternative Robinhood Chain on-chain swap feed, CoinGecko/
CMC reference adapters, Dune/LunarCrush/CryptoPanic/Perplexity/altFINS
intelligence adapters (each behind `traderstack.market.registry.ProviderRegistry`
for timeout/circuit-breaker/quota/caching), freshness and pairwise-divergence
checks, the canonical `AssetFeatureVector` schema, and `RegimeClassifier` v1
are all implemented and wired into the live loop.

## Phase 3 — Strategy framework

Implement independently testable strategies:
- momentum/trend
- breakout
- mean reversion baseline
- on-chain flow
- narrative/social momentum
- event/news
- optional funding/basis

Add:
- TradeCandidate schema
- per-strategy performance attribution
- strategy versioning
- candidate confidence calibration

Exit gate: candidate generation works without execution privileges.

**Status (2026-09-04): Core done; breakout/funding-basis strategies and
formal confidence calibration not built.** `strategies.py` implements
momentum, trend and mean-reversion, backtested and walk-forward-validated by
the pre-trade gate; `agents/specialists.py` adds deterministic technical/
on-chain/narrative specialist readers consumed as meta-agent evidence.
`TradeProposal` is the candidate schema; per-strategy attribution
(`research/attribution.py`) and versioning (`signal_registry.py`) exist.
Breakout, dedicated event/news, and funding/basis strategies were not built —
news is instead a deterministic gate, not a scored candidate source. Candidate
confidence is a plain `[0,1]` field with no separate calibration step.

## Phase 4 — Agent intelligence

Build:
- Claude tool/MCP gateway
- evidence retrieval
- structured LLM schemas
- specialist analysis agents
- meta-agent/challenger design
- model routing/cost controls
- prompt/version audit trail

Research A/B tests:
- deterministic weighting vs Claude meta-agent
- market-only vs market + news
- market-only vs market + on-chain
- market-only vs market + social

Exit gate: LLM components demonstrate measurable incremental value or are demoted to explanatory/research roles.

**Status (2026-09-04): Core review loop done; MCP gateway and formal A/B
studies not built.** `agents/review.py`'s `MetaAgentReviewer` calls Claude
through `agents/claude.py` directly (no MCP tool-calling layer), runs strictly
after risk sizing is fixed, and can only veto or nudge confidence within a
bounded delta (`off`/`advisory`/`veto` via `META_AGENT_MODE`) — never size,
side or approve new risk. Prompt/version audit trail
(`agents/prompts.py`), evidence-hash caching and daily call/token budgets are
implemented. No dedicated Claude tool/MCP gateway exists, and the "deterministic
vs. meta-agent" / "market-only vs. +news/on-chain/social" comparisons remain
manual (`traderstack-paper-report`) rather than an automated A/B framework.

## Phase 5 — Portfolio and deterministic risk plane

Build:
- portfolio state service
- allocation/risk budgets
- concentration/correlation controls
- hard trade rules
- drawdown guards
- circuit breakers
- stale-state protections
- global kill switch
- policy versioning

Exit gate: adversarial tests demonstrate that agents cannot bypass controls.

**Status (2026-09-04): Done, and adversarially tested.** Portfolio state,
volatility sizing, every exposure/drawdown/loss/spread limit, the strategy
circuit breaker, the four-channel kill switch (settings/file/Redis/SIGUSR1,
an unreachable Redis channel counted as engaged), the hash-chained risk audit
trail, stale-state shutdown and policy versioning are all implemented
(`portfolio.py`, `risk.py`, `circuit_breaker.py`, `killswitch.py`,
`risk_audit.py`). `docs/SECURITY-REVIEW-2026-09.md` attacked these controls
directly (prompt injection into the meta-agent, halt-channel bypass attempts,
mutable-settings tampering) and found no path that relaxes risk.

## Phase 6 — Hummingbot paper execution

Build:
- Hummingbot API/MCP/Gateway integration
- order lifecycle state machine
- reconciliation
- realistic costs/slippage
- paper exchange/venue setup
- monitoring and alerts

Exit gate: sustained unattended paper operation without unreconciled state or risk-control failures.

**Status (2026-09-04): Implemented; the sustained 24/7 window is the one
remaining exit-gate step.** Hummingbot API integration, the order lifecycle
state machine (`OrderLifecycleState`, including `SUBMISSION_UNCERTAIN`),
idempotent submission, reconciliation (order/fill and NAV-drift) and retry/
timeout handling are all implemented and covered by
`tests/acceptance/`. The `traderstack-soak` runner exists and is tested, but
the 24-hour window itself has not yet been run and archived — see
`docs/MVP-BACKLOG.md` Epic 10 and `docs/RUNBOOK.md`, "24/7 acceptance soak".

## Phase 7 — Shadow-live validation

Consume live feeds and make live-time decisions without placing real orders. Compare hypothetical fills against market reality and paper execution.

Exit gate: statistically adequate sample with acceptable execution assumptions and stable operations across market conditions.

**Status (2026-09-04): Not started.** `Settings.trading_mode` accepts
`"shadow"` as a literal, but `cli.build_service` only ever builds the paper
loop and raises if `trading_mode != "paper"` — there is no distinct
shadow-mode behaviour (live-time decisions without paper fills, compared
against paper/reality) yet.

## Phase 8 — On-chain security path

Only if DeFi execution remains justified:
- isolated signer
- test wallet
- transaction simulation
- smart-account/guard policy
- token/contract/chain allowlists
- spending caps
- failure/recovery exercises

Exit gate: security review and adversarial transaction tests pass.

**Status (2026-09-04): Scaffolding only — deliberately stops short of
signing.** `execution/robinhood_chain.py` verifies the connected RPC's chain
id, enforces token/router allowlists and a notional/gas policy, checks wallet
balance, and simulates the transaction (`eth_call`) before returning an
**unsigned** transaction; `live` trading mode is rejected outright. No
isolated signer, smart-account/guard policy, or spending-cap enforcement
service exists yet — this phase is not exited until one does.
`docs/SECURITY-REVIEW-2026-09.md` (SEC-2026-09-15, SEC-2026-09-16) records the
specific gaps a signer must close before this scaffolding is trusted with a key.

## Phase 9 — Tiny-capital live pilot

Use a deliberately small risk budget and conservative limits. No leverage initially.

Requirements:
- human-visible kill switch
- alerting
- daily reconciliation
- strategy-specific limits
- automatic drawdown halt
- immutable production risk policy during each deployment

Exit gate: live behaviour matches paper/shadow assumptions closely enough to justify any scale increase.

**Status (2026-09-04): Not started.** Blocked on Phases 7 and 8.

## Phase 10 — Controlled scale and continuous research

Scale only through explicit reviewed configuration changes. New strategies repeat the full research/paper/shadow pipeline. Production agents cannot promote themselves or increase their own capital allocation.

**Status (2026-09-04): Not started.** Blocked on Phase 9.
