# Provider Capability Matrix

This matrix defines intended roles rather than marketing claims. Pricing, rate limits, authentication and exact tool availability are volatile and MUST be re-verified against vendor documentation during implementation before a paid plan is selected.

| Provider/tool | Primary role | Critical path? | Write capability | MVP use | Notes |
|---|---|---:|---:|---:|---|
| TradingView MCP | chart/indicator/alert secondary validation | No | potentially via desktop workflows | Later | community integration; never executor |
| Dune MCP/API | on-chain analytics, wallet/protocol flows | No | No for our use | Yes | asynchronous/derived intelligence; cache results |
| Perplexity MCP/API | web/event research | No | No | Yes | event enrichment only; not a price oracle |
| GOAT SDK MCP | on-chain actions | No | Yes | No | archived upstream; excluded from production path |
| altFINS MCP/API | technical signals/screening | No | No for our use | Yes | useful pre-computed feature source; cross-check internally |
| CoinGecko MCP/API | broad market/reference data | Secondary | No | Yes | reference/divergence source, not execution price |
| DeFi Trading & Portfolio MCP | DeFi reads/quotes/actions | No | Yes | Research only | isolate; no funded wallet in MVP |
| CryptoPanic MCP/API | crypto news/event feed | No | No | Yes | event trigger/enrichment; timestamps and dedupe required |
| CoinMarketCap MCP/API | market/reference data | Secondary | No | Yes | independent validation/redundancy |
| LunarCrush MCP/API | social/narrative intelligence | No | No | Yes | narrative features only; manipulation-aware controls needed |
| Hummingbot | exchange/DEX execution abstraction | **Yes** | Yes | **Yes** | sole MVP order-routing spine |
| Robinhood Chain (EVM) | on-chain swap execution venue | No for MVP | Unsigned-tx preparation only | Research only | `traderstack.execution.robinhood_chain` prepares policy-checked, simulated, **unsigned** transactions; chain id/RPC are operator-configured, never hardcoded; no signing/broadcast in this repo until a Phase 8 signing service exists |
| Robinhood Chain swap feed | venue-native real-time DEX price/flow (Uniswap v3/v4 `Swap` logs via `eth_subscribe`) | Yes when `VENUE_FEED=robinhood_chain` | No (read-only) | Research / paper | `traderstack.market.robinhood_chain_feed`; verifies chain id before subscribing; watches only operator-listed pools; bid/ask synthesised from pool fee tier |
| Freqtrade | research/backtest/dry-run harness | No | Can trade but disabled in architecture | **Yes** | independent research harness, not production executor |
| Direct venue WS/REST | venue-native market data and reconciliation | **Yes** | execution delegated to Hummingbot | **Yes** | authoritative venue state for execution checks |
| Claude API | reasoning, proposal synthesis, meta-agent | No for safety | No direct execution | **Yes** | failure must degrade to no-new-risk state |

## Selection policy

A provider must have a documented adapter contract, health state, timeout, quota/budget, freshness threshold and fallback behavior before it can be enabled. Intelligence-provider failure cannot relax risk. Conflicting price/reference sources create a divergence event and can block new entries.

## Cost-control fields to capture during implementation

For every commercial API, record: free-tier allowance; monthly base fee; per-call/token/credit cost; websocket limits; historical-data limits; commercial-use restrictions; overage behavior; and expected monthly cost at low/medium/high event volumes. Do not hard-code current prices in architecture documents because vendor plans change.

## Implemented adapters and health controls

Research/implementation snapshot: **4 September 2026**. This section records what actually satisfies the selection policy above today, versus what is still just a documented intent in the table.

### Provider health, quota and caching (`traderstack.market.registry.ProviderRegistry`)

Every reference-price provider (CoinGecko, CoinMarketCap), the Kraken candle provider, and every intelligence fetcher (Dune, LunarCrush, CryptoPanic, Perplexity, altFINS) are wrapped in `cli.build_service` / `cli.build_intelligence` through a `ProviderRegistry`, one instance per provider (`build_provider_registry`). Each wrapped call gets:

- a timeout (`PROVIDER_TIMEOUT_SECONDS`)
- a circuit breaker: closed &rarr; **open** after `PROVIDER_FAILURE_THRESHOLD` consecutive failures &rarr; **half-open** after `PROVIDER_BREAKER_COOLDOWN_SECONDS` &rarr; closed again on the half-open trial call's success, or straight back to open on its failure
- a quota budget (calls/minute and/or calls/day; `COINGECKO_CALLS_PER_MINUTE`, `COINMARKETCAP_CALLS_PER_MINUTE`/`_DAY`, `CANDLE_PROVIDER_CALLS_PER_MINUTE`, `INTELLIGENCE_PROVIDER_CALLS_PER_MINUTE`) — a call beyond budget is refused before it reaches the network
- an optional short-TTL cache (`REFERENCE_PRICE_CACHE_SECONDS` for the reference-price providers) so the 5-second paper-trading cycle doesn't burn a slow free-tier quota; a cache hit returns the original cached value including its original `observed_at`, so the pipeline's freshness check still sees real data age, never a refreshed timestamp
- Prometheus counters/gauges (`traderstack_provider_calls_total`, `traderstack_provider_last_latency_seconds`, `traderstack_provider_breaker_state`, `traderstack_provider_quota_rejections_total`, `traderstack_provider_cache_hits_total`), following the pattern in `traderstack.health`
- a `health()` report (state, consecutive failures, last latency/error, calls in the current minute/day) satisfying the `ProviderHealth` protocol in `traderstack.market.providers`

Streaming venue feeds (Kraken ticker/book) are deliberately **not** wrapped by `ProviderRegistry` — a request timeout and circuit breaker don't fit a long-lived subscription. They get their own resilience instead (next section).

### Kraken WS v2 resilience (`traderstack.market.adapters`)

`KrakenTickerProvider.stream_ticks` and the new `KrakenBookProvider.stream_books` share a reconnect loop (`_stream_with_reconnect`) that:

- reconnects on any transport error or a stalled connection (no message within `KRAKEN_STALE_AFTER_SECONDS`, default 30s) with capped exponential backoff plus full jitter (`KRAKEN_BACKOFF_BASE_SECONDS`/`KRAKEN_BACKOFF_MAX_SECONDS`)
- gives up only after `KRAKEN_MAX_RECONNECT_ATTEMPTS` consecutive reconnect failures, raising `KrakenFeedExhausted`
- yields ticks/book snapshots continuously across reconnects (the caller sees one uninterrupted stream)
- takes an injectable `connect` factory (matching `RobinhoodChainSwapFeed.connect`) plus injectable `sleep`/`random_jitter`, so reconnect/backoff/stale-detection are unit-tested without a real socket or real wall-clock delay (`tests/test_kraken_resilience.py`)

### Order-book snapshots (`KrakenBookProvider`, Epic 2)

Subscribes to Kraken WS v2's `book` channel (depth 10 by default, `KRAKEN_BOOK_DEPTH`; verified against https://docs.kraken.com/api/docs/websocket-v2/book on 2026-09-04: one full `snapshot` on subscribe, then `update` messages carrying only changed price levels, qty `0` meaning "remove this level"). A local order book per symbol is merged on every message and re-derived into a `BookSnapshot` (best-N levels each side, `observed_at`) — pure, tested against recorded-shape fixtures in `tests/test_kraken_resilience.py`. `BookSnapshot.depth_within_bps(bps)` returns notional (quote-currency) depth within `bps` of the mid on each side. Opt-in via `KRAKEN_BOOK_ENABLED` (Kraken venue only); surfaced on `RuntimeResult.book_snapshot` — informational today, not yet consumed by the risk plane (that wiring is left for a future risk-plane change, per the coordination rules for this change).

### Provider divergence event (Epic 2)

`traderstack.market.validation.pairwise_divergences` compares every pair of independent-source prices (the primary tick plus every non-Kraken reference), not only each reference against the primary. Any pair disagreeing by more than `MAX_REFERENCE_DIVERGENCE_BPS` produces a `PriceDivergence`. `VerticalSlicePipeline.process` always computes this (even when the cycle is otherwise rejected) and returns it as `PipelineResult.divergences`, so a reference-vs-reference disagreement — e.g. CoinGecko and CoinMarketCap disagreeing with each other while each individually stays within tolerance of the Kraken primary — lands in the audit trail even though it would not trigger `reference_price_divergence` on its own.

### Perplexity news adapter (`traderstack.market.perplexity`)

Rewritten to target Perplexity's **Agent API** (`POST /v1/agent`) instead of the old Sonar Chat Completions endpoint (`POST /v1/sonar`), which Perplexity's own docs mark deprecated in favour of the Agent API and scheduled to stop working 27 Sep 2026 — https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview, https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/how-to, https://docs.perplexity.ai/api-reference/agent-post, verified 2026-09-04. Uses `response_format: {type: "json_schema", ...}` to force a schema-constrained JSON reply (event_score/adverse_event/item_count) instead of hoping free-form prose happens to parse as JSON. `NewsSnapshot` output contract is unchanged.

### altFINS technical-signals adapter (`traderstack.market.altfins`)

New adapter against altFINS' public REST API — base URL `https://altfins.com`, `X-API-KEY` header auth, `POST /api/v2/public/signals-feed/search-requests` (a page of discrete BULLISH/BEARISH signal rows per symbol/time-window). Endpoint paths, auth, and the request/response field names (`symbols`, `direction`, `PaginatedResponse.content`, `SignalDataItem{symbol, signalKey, signalName, direction, timestamp}`) are **verified** against altFINS' own published TypeScript client and type definitions at https://github.com/altfins-com/altfins-api-examples (cloned and read directly) on 2026-09-04, cross-checked against https://altfins.com/crypto-market-and-analytical-data-api/documentation/api/public-api/. altFINS does **not** publish a single normalised numeric "signal score" — mapping a page of signals to `AssetFeatureVector.market.external_signal_score` (net bullish/bearish share of signals fired in a configurable lookback window, clipped to [-1, 1]) is this implementation's **own documented design assumption**, flagged in the adapter's docstring, not a field altFINS returns directly. Wired through `IntelligenceOrchestrator.altfins` / `ExternalIntelligence.altfins` and merged additively via `merge_external_intelligence(..., altfins=...)`.

### Settings introduced

`ALTFINS_API_KEY` (SecretStr; was already in `.env.example`, now backed by a `Settings` field), plus the `PROVIDER_*`, `*_CALLS_PER_MINUTE`/`_DAY`, `REFERENCE_PRICE_CACHE_SECONDS`, `KRAKEN_*` settings documented in `.env.example`.