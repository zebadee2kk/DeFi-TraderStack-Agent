# DeFi TraderStack Agent

An experimental autonomous crypto/DeFi trading research and execution platform
combining quantitative signals, on-chain intelligence, market/news/social
data, LLM reasoning, deterministic risk controls, and broker/DEX execution.

> **Status:** MVP paper-trading platform. `TRADING_MODE=paper` is the default
> and the only mode that can place venue (paper) orders. `TRADING_MODE=shadow`
> runs the same decision/risk/meta-agent pipeline and records would-have-been
> orders without submitting them. Live capital is explicitly out of scope
> until the remaining gates in `docs/MVP-BACKLOG.md` ("Remaining before live
> capital") and `docs/ROADMAP.md` Phases 8-9 close. Nothing in this
> repository or its defaults authorizes live trading.

## Safety principle

**No LLM may modify, disable or bypass runtime risk policy.** Claude may
propose a trade or withhold one that risk already approved; deterministic
software alone decides whether a proposal is permitted and at what size. This
holds at every layer:

- The **deterministic risk engine** (`src/traderstack/risk.py`) evaluates
  every proposal against version-controlled limits — kill switch, exposure,
  drawdown, daily loss, circuit breakers, spread — and no agent, LLM message,
  tool result or runtime API can change those limits from inside the process.
- The **kill switch** (`src/traderstack/killswitch.py`) has four independent
  channels (a setting, a sentinel file, a Redis key, `SIGUSR1`); engaging any
  one halts new risk, and an unreachable Redis channel is treated as engaged,
  never as clear.
- The **constrained meta-agent review** (`src/traderstack/agents/review.py`)
  runs strictly *after* the risk engine has already fixed side, asset and
  approved notional. It can only withhold an already-approved order or nudge
  confidence within a small bound — never size, side, or approve new risk.
- Every risk decision is written to a hash-chained, append-only audit trail
  (`src/traderstack/risk_audit.py`) that also records the meta-agent's review
  and the execution outcome, so a risk-approved proposal that was later
  vetoed is legible on one line, not only inferable by cross-referencing logs.

`docs/SECURITY-REVIEW-2026-09.md` attacked this boundary directly — prompt
injection into the meta-agent, halt-channel bypass attempts, mutable-settings
tampering — and found no path that relaxes risk.

## Quickstart (paper trading)

```bash
cp .env.example .env          # fill in what you need; everything else can stay blank
make setup                    # creates .venv, installs the package + dev tools
make check-config             # traderstack-check-config: shows what's enabled, fails on unsafe combos
docker compose up -d postgres redis
docker compose --profile app up -d --build
docker compose ps             # app should report "healthy" within ~50s
tail -f var/audit/runtime.jsonl
```

`KILL_SWITCH=true` and `TRADING_MODE=paper` are the defaults — the
deterministic risk engine rejects every proposal until you deliberately
change that. Full zero-to-running steps, every console script, filling in
`.env` safely, the kill switch, meta-agent budgets, provider quotas, key
rotation, reading the audit log/metrics, upgrading, and incident response all
live in **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)**.

## Architecture overview

```text
Validated market data (venue tick + independent references + candle history)
   + External intelligence (Dune on-chain, LunarCrush social, CryptoPanic/Perplexity/altFINS)
   -> Feature vector merge + deterministic news rule (adverse event => no new risk)
   -> Pre-trade backtest gate (strategy confirmation, backtest, walk-forward)
   -> Trade Proposal
   -> Deterministic Risk Engine (kill switch checked first, then account/strategy/asset/trade limits)
   -> Constrained meta-agent review (can only withhold or nudge confidence — advisory/veto/off)
  -> Execution Planner
       paper  -> Idempotent Submitter -> Hummingbot API -> Venue -> Fill / Reconciliation
       shadow -> ShadowRecorder (would-have-been order; no venue call, no fill)
  Paper reconciliation gates new submissions, never decisions or auditing.
```

Each cycle, per symbol: the kill switch and reconciliation gate are
re-evaluated *before* anything is submitted; the pipeline runs; the risk
engine decides; the meta-agent (if enabled) can only remove risk the engine
already approved; the portfolio checkpoint is written *before* the event
fan-out to remote sinks, so a downstream outage never leaves local state
behind the execution ledger. The full, traced order of operations —
`ContinuousPaperService.run` → `PaperRuntime.run_once` — with the invariants
each step preserves, is documented in
**[`docs/EXECUTION-ARCHITECTURE.md`](docs/EXECUTION-ARCHITECTURE.md)**,
"Cycle order of operations".

`docs/AGENT-ARCHITECTURE.md` documents the agent topology and the
deterministic/LLM boundary in more depth; `docs/RISK-PRINCIPLES.md` documents
the risk control hierarchy and every setting/reason-string pair.

## Features

**External intelligence in the live loop.** Every cycle the runtime gathers
Dune (on-chain), LunarCrush (social), CryptoPanic/Perplexity (news) and
altFINS (technical signal) snapshots for the asset — concurrent, cached, each
provider failure isolated — and merges them into the feature vector. An
adverse news event deterministically blocks new risk for that cycle. Each
adapter reduces its source to bounded numeric features; retrieved text never
reaches the decision path. Providers activate when their API key is set (see
`INTELLIGENCE_*` / provider settings in `.env.example`); each is wrapped in a
per-provider timeout/circuit-breaker/quota wrapper
(`traderstack.market.registry.ProviderRegistry`).

**Pre-trade self-check (backtest gate).** Before any proposal reaches the risk
engine, `src/traderstack/pretrade.py` re-runs the strategy ensemble over the
asset's recent candle history, backtests it net of fees and slippage against
buy-and-hold, and walk-forward tests it out-of-sample. A missing, stale or
unconvincing history rejects the trade. On by default (`PRETRADE_*` settings);
can only add rejections, never relax risk policy.

**Constrained meta-agent review.** `src/traderstack/agents/review.py` inserts
one bounded LLM review between the deterministic pipeline and execution — see
"Safety principle" above for the boundary, and `docs/RUNBOOK.md`, "Meta-agent
modes and budgets", for `META_AGENT_MODE` (`off`/`advisory`/`veto`), cost
controls and budgets. The technical, on-chain and narrative strategy agents in
`agents/specialists.py` are deterministic feature readers feeding it evidence,
not further model calls.

**Execution hardening.** `src/traderstack/execution/` implements idempotent
submission (one decision → at most one venue order, across restarts), a
documented order-lifecycle state machine including the fail-closed
`SUBMISSION_UNCERTAIN` state for timeouts/5xx, and venue reconciliation that
blocks new submissions (never decisions or auditing) on divergence or NAV
drift. See `docs/EXECUTION-ARCHITECTURE.md` and `docs/RUNBOOK.md`, "Execution
status and the order lifecycle".

**Robinhood Chain.** Two independent, separately-configured surfaces (see
`docs/RUNBOOK.md`, "Robinhood Chain configuration prerequisites"):
`src/traderstack/market/robinhood_chain_feed.py` streams Uniswap v3/v4 `Swap`
events from operator-listed pools over websocket JSON-RPC as an alternative
primary tick source (`VENUE_FEED=robinhood_chain`), read-only; and
`src/traderstack/execution/robinhood_chain.py` prepares policy-checked,
simulated, **unsigned** swap transactions against the same chain — it never
signs or broadcasts, and `live` mode is rejected outright until an isolated
signing/custody service exists (`docs/ROADMAP.md` Phase 8). Both require
chain id, RPC URL and (for execution) allowlists sourced from Robinhood's own
official chain documentation, never guessed.

**Observability.** OpenTelemetry traces (opt-in), Prometheus metrics, a
provisioned Grafana dashboard, and Loki log aggregation are all wired
(`docker compose --profile observability`). Grafana ships with anonymous
Viewer access enabled for local convenience — see `docs/RUNBOOK.md` before
running that profile anywhere network-reachable by others.

## Initial intelligence/tool set

1. TradingView MCP — charts, alerts, indicators and Pine workflows (secondary/non-critical path)
2. Dune MCP — on-chain analytics, wallet flows and protocol data
3. Perplexity MCP — live web and financial research
4. GOAT SDK MCP — legacy/experimental only; upstream repository is archived
5. altFINS MCP — technical indicators, screeners and signals
6. CoinGecko MCP/API — broad crypto market and on-chain data
7. DeFi Trading & Portfolio MCP — experimental portfolio/DEX integration
8. CryptoPanic MCP — real-time crypto news/events
9. CoinMarketCap MCP/API — market data and independent verification
10. LunarCrush MCP — social/narrative intelligence

**Polymarket weather (opt-in paper research).**
`traderstack-polymarket-weather-paper` compares public NWP highs to
Polymarket CLOB mids and writes would-trade intents to
`var/audit/polymarket_weather_paper.jsonl`. It is a separate process from
`traderstack-paper`, requires `TRADING_MODE=paper`, respects the kill
switch, and has no private-key or CLOB-order surface. Claimed weather-market
win rates are unproven; see `docs/EVALUATION-FRAMEWORK.md` and
`docs/RUNBOOK.md` ("Polymarket weather paper research").

## Validation path

Historical backtest → leakage/look-ahead checks → walk-forward validation →
holdout evaluation → paper trading → shadow-live trading → tiny-capital live
pilot → controlled scale-up. Benchmarks include BTC/ETH buy-and-hold and
simple non-AI momentum/trend/mean-reversion strategies (`traderstack-research`,
`traderstack-strategy-search`, `traderstack-miles-search`,
`traderstack-daily-robustness`, `traderstack-paper-report`) so any claimed AI
alpha is measured against appropriate baselines, not narrated after the fact.
`traderstack-strategy-search` is the paper-research promotion loop: it will
not register a voter unless fee-aware walk-forward **total** return is
strictly positive *and* holdout excess is strictly positive. The default
`PAPER_PROMOTE_SEARCHED_STRATEGIES=false` stays off until a report shows a
winner, and promotion is pinned to that catalog id
(`PAPER_PROMOTE_SEARCHED_STRATEGY_ID`). `traderstack-miles-search` scores
EMA 9/21 and 12/26 (optional ADX gate) with a GARCH(1,1) vol-targeted size
overlay under fees. Promotion requires walk-forward **total return > 0**
and holdout **excess return > 0**. Default `PAPER_GARCH_SIZE=false` stays
off (no GARCH-sized candidate cleared). `PAPER_PROMOTE_EMA_9_21=false` is
the documented paper-only switch to register `ema_9_21` as the sole paper
voter on daily candles (`1d` / Kraken 1440); it does not enable live and
must not be read as a 1h-runtime edge.
`traderstack-daily-robustness` stress-tests that daily winner (plus a
pre-registered slower-EMA / dual-mom / risk-off / optional-GARCH grid)
on the 720-bar Kraken daily cap and only documents a `PAPER_PROMOTE_*`
id if **BTC and ETH** both have walk-forward total > 0 **and** both have
holdout excess > 0 after fees.

## Roadmap

`docs/ROADMAP.md` carries a dated implementation status per phase.
`docs/MVP-BACKLOG.md` is the epic-level checklist, ending with a "Remaining
before live capital" list. See also `docs/PROJECT-CHARTER.md`, `docs/HLD.md`,
`docs/RESEARCH-NOTES.md` and `docs/DATA-SOURCES.md` (the researched inventory
of live, reference, on-chain and backtest data sources, including Robinhood
Chain's documented chain ids, RPC/explorer endpoints and router addresses).

## Disclaimer

This repository is for research and proprietary experimentation, not
financial advice. Initial scope is private/proprietary trading only; no
third-party client funds or investment service functionality is in scope.
