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