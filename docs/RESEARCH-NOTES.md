# Research Notes and Component Decisions

## Current conclusion

The concept is technically viable, but the engineering goal is not merely to make an LLM capable of placing trades. The project must test whether an agentic + quantitative architecture produces persistent, risk-adjusted value after realistic costs and against simple baselines.

## Original ten-tool set

| Tool | Intended role | Current disposition |
|---|---|---|
| TradingView MCP | charts, indicators, alerts, Pine workflows | Keep as secondary/non-critical intelligence path |
| Dune MCP | on-chain analytics and wallet/protocol flows | Keep |
| Perplexity MCP | live web and financial/event research | Keep |
| GOAT SDK MCP | wallet/on-chain execution | Legacy/experimental only; do not make a production dependency |
| altFINS MCP | technical indicators, screeners and signals | Keep |
| CoinGecko MCP/API | crypto market and on-chain reference data | Keep |
| DeFi Trading & Portfolio MCP | portfolio reads/DEX actions | Experimental; not primary execution control plane |
| CryptoPanic MCP | crypto news | Keep |
| CoinMarketCap MCP/API | market/reference data and cross-validation | Keep |
| LunarCrush MCP | social/narrative intelligence | Keep |

## Important additions

### Hummingbot
Preferred execution spine for the design because its ecosystem provides exchange/DEX connectors, market data abstractions, order lifecycle support, Gateway, APIs and MCP integration. This lets the project concentrate effort on signal quality, portfolio intelligence and risk rather than reimplementing exchange connectivity.

### Freqtrade
Recommended as an independent research/backtest tool for directional strategy experiments, dry-run validation and specific testing for look-ahead bias. It should not be treated as a second production execution engine unless later evidence justifies that complexity.

### Venue-native market feeds
Execution-critical market state should come directly from the venue (or the execution abstraction backed by that venue), not from slow/aggregated MCP research services.

### Durable workflows
A 24/7 trading system needs crash-resilient event/workflow semantics. Orchestration must be able to reconstruct state after process/network failures.

### Smart-account / signing controls
On-chain execution requires a narrow signing boundary, transaction simulation, contract/token allowlists, spending limits and explicit permissions. LLM-facing services should never hold unrestricted signing keys.

## Research implications for the design

1. LLM trading research is promising but often suffers from data leakage, weak cost modelling and poor reproducibility.
2. Multi-agent architectures are worth testing, but claims of superior performance must be measured against simple strategies and passive crypto exposure.
3. Structured quantitative/on-chain features should be the primary input. News/social/LLM reasoning are complementary contextual signals rather than replacements for market structure.
4. Strategy performance must be evaluated by market regime, not only as one aggregate return curve.
5. Production architecture should separate signal generation, portfolio construction, risk control and execution.

## Required benchmark suite

At minimum:
- BTC buy-and-hold
- ETH buy-and-hold
- static BTC/ETH portfolio
- simple momentum
- simple trend-following
- simple mean reversion
- volatility-targeted/risk-balanced baseline

## Research questions still open

- Which exchange(s) and chain(s) should be the first supported live venues? (Robinhood Chain, chain id 4663, is now scaffolded as the first on-chain venue; see `DATA-SOURCES.md` and `execution/robinhood_chain.py`.)
- Which data sources have usable free/API tiers for continuous operation?
- What signal frequency maximises usefulness of Claude without excessive cost/latency?
- Does social/narrative information add value after controlling for price momentum?
- Does Dune/on-chain information provide incremental predictive value over market data alone?
- Is a Claude meta-agent better than deterministic signal weighting?
- Which market-regime classifier is stable enough for production use?
- What is the minimum realistic paper-trading period before a tiny-capital live pilot?
- Does an NWP-vs-Polymarket-temperature divergence survive fees, station
  mismatch and a pre-registered A/B (see `docs/EVALUATION-FRAMEWORK.md`)?
  Social claims of high win rates are treated as unproven. The paper weather
  CLI records intents only. `traderstack-polymarket-weather-eval` now
  scores gates 1/4/5 when resolved rows exist; this repo has no PIT mid +
  official station-high tape, so the committed live print is empty and
  cannot promote. Gates 2 and 3 (WF parameter fit; a full season of live
  paper A/B) are still open. That is not evidence of alpha.
- Does a fee-aware funding-z threshold or hedged cash-and-carry clear
  dual independent prints on BTC+ETH? `traderstack-funding-carry`
  scores a frozen catalog against OKX, Hyperliquid, and BitMEX when
  reachable (Binance/Bybit probed and skipped if geo-blocked). A
  single-venue tape cannot promote; hard gates stay UNAVAILABLE until
  720 aligned daily bars exist on two venues. BitMEX public
  settlements can fill that bar; OKX public history is still ~90d
  after a UTC-day resample.   PIT basis is UNAVAILABLE on Hyperliquid
  and BitMEX (current mark/index only; premium is not basis). Public
  archives were probed and stay UNAVAILABLE for dual-print
  (official HL `asset_ctxs` is requester-pays 403; a public HF
  mirror `asiletto81/hyperliquid` now supplies ≥720d HL
  `mark_px`/`oracle_px`; BitMEX dumps still have no mark tape;
  Tardis first-of-month samples are not a daily tape) — see
  `docs/artifacts/strategy-search/pit-basis-archives.md`. A
  paper hedge+funding soak path is cycle-wired
  (`PAPER_CARRY_PATH_READY=true` when `PAPER_PERP_HEDGE` fetches an
  explicit HL/BitMEX mid + same-venue funding). Snapshot mids are not
  historical PIT basis, so a pin stays off. Empty / cannot-promote is
  success. See
  `docs/artifacts/strategy-search/edge-status-2026-09-12.md`.
- Does a fee-aware fade/follow of daily BTC minus ETH excess return
  at frozen |z| thresholds clear the same #96+A+B+C dual-print bar
  (Kraken 720 + Binance.US older-720)? `traderstack-relative-value`
  scores that residual family. It is paper-executable on Kraken
  spot. Empty dual-print is success. Not an EMA reprint. See
  `docs/artifacts/strategy-search/btc-eth-relative-value.md`.
- Does a fee-aware long-top-1 / short-bottom-1 among {BTC, ETH, SOL}
  by frozen trailing N-day return (21/63/126; optional vol-scaled)
  clear the same #96+A+B+C dual-print bar (Kraken 720 + Binance.US
  older-720)? `traderstack-xs-momentum` scores that family. BTC and
  ETH signs remain the gate; SOL is reported, not required.
  Paper-executable on Kraken spot. Empty dual-print is success.
  Not an EMA or residual reprint. See
  `docs/artifacts/strategy-search/cross-sectional-momentum.md`.
- Does a fee-aware Donchian / channel breakout (prior N-day
  high/low; N in {20, 55, 100}; optional ATR-14 buffer) clear the
  same #96+A+B+C dual-print bar (Kraken 720 + Binance.US
  older-720)? `traderstack-donchian-breakout` scores that family.
  BTC and ETH signs remain the gate; SOL is reported, not required.
  Paper-executable on Kraken spot. Empty dual-print is success.
  Not an EMA, residual, or XS reprint. See
  `docs/artifacts/strategy-search/donchian-breakout.md`.
- Does a fee-aware own-asset time-series momentum (trailing
  N-day close-to-close return; N in {21, 63, 126, 252};
  long-only or long/short) clear the same #96+A+B+C
  dual-print bar (Kraken 720 + Binance.US older-720)?
  `traderstack-tsmom` scores that family. BTC and ETH signs
  remain the gate; SOL is reported, not required.
  Paper-executable on Kraken spot. Empty dual-print is
  success. Not an EMA, residual, XS, or Donchian reprint.
  See `docs/artifacts/strategy-search/tsmom.md`.
- Does a fee-aware own-asset Bollinger band-fade (SMA ± k ×
  sample stdev; fade-to-inside / long-only fade / squeeze
  contrast; period×k in {20x2, 20x2.5, 40x2}) clear the same
  #96+A+B+C dual-print bar (Kraken 720 + Binance.US
  older-720)? `traderstack-bollinger-fade` scores that
  family. BTC and ETH signs remain the gate; SOL is
  reported, not required. Paper-executable on Kraken spot.
  Empty dual-print is success. Distinct from existing
  `mean_reversion_*` ids (#93 / #108 used different bars).
  Not an EMA, residual, XS, Donchian, or TSMOM reprint.
  See `docs/artifacts/strategy-search/bollinger-fade.md`.
- Does a fee-aware UTC calendar seasonality book (day-of-week
  Mon / Fri / Mon+Fri; skip-weekend; month-of-year Q4 / Jan /
  Nov+Dec; turn-of-month last 3 / first 3 civil days) clear
  the same #96+A+B+C dual-print bar (Kraken 720 + Binance.US
  older-720)? `traderstack-calendar-seasonality` scores that
  family. Timezone is UTC. Positions ignore OHLC. BTC and
  ETH signs remain the gate; SOL is reported, not required.
  Paper-executable on Kraken spot. Empty dual-print is
  success. Not an EMA, residual, XS, Donchian, TSMOM, or
  Bollinger reprint. See
  `docs/artifacts/strategy-search/calendar-seasonality.md`.
- Does a fee-aware BTC→ETH lead-lag book (ETH follows or
  fades lagged BTC L-day return; L in {1,2,3,5} follow-lo;
  {1,2,3} follow-ls / fade-lo; BTC-follows-ETH mirror lo
  {1,2}) clear the same #96+A+B+C dual-print bar (Kraken 720
  + Binance.US older-720)? `traderstack-lead-lag` scores that
  family. Not same-bar residual z-score (#116). Other leg is
  frozen flat; both BTC and ETH legs remain the gate.
  Paper-executable on Kraken spot. Empty dual-print is
  success. Not an EMA, residual, XS, Donchian, TSMOM,
  Bollinger, or calendar reprint. See
  `docs/artifacts/strategy-search/lead-lag.md`.
- Does a fee-aware volume-confirmed breakout book (price
  breakout **and** volume > V-day SMA × mult; V=20 through
  t−1; N×mult in {20x1.5, 55x1.5, 20x2} plus a small
  volume-surge set) clear the same #96+A+B+C dual-print bar
  (Kraken 720 + Binance.US older-720)?
  `traderstack-volume-breakout` scores that family. Not a
  Donchian N retune (#118). Missing volume is skipped, never
  invented. BTC and ETH signs remain the gate; SOL is
  reported, not required. Paper-executable on Kraken spot.
  Empty dual-print is success. Not an EMA, residual, XS,
  Donchian, TSMOM, Bollinger, calendar, or lead-lag reprint.
  See `docs/artifacts/strategy-search/volume-breakout.md`.
