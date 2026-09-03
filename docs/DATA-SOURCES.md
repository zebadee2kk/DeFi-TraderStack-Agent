# Data Sources

Research snapshot: **September 2026**. Vendor limits, pricing and chain support
change often; re-verify against the linked primary pages before enabling any
source in production (see the selection policy in
`PROVIDER-CAPABILITY-MATRIX.md`).

Verification legend: **[V]** confirmed on an official/primary page at research
time; **[S]** from search snippets or third-party pages only; **[?]** could not
be verified. Anything marked [S] or [?] must be confirmed by an operator before
it is relied upon.

## Recommended stack

### Live, execution-quality (hot path)

| Tier | Source | Why |
|---|---|---|
| Primary | **Kraken WS v2** ticker + `book` (depth 10) | Already integrated; public channels unauthenticated; ≤200 symbols/connection. |
| Second venue | **Coinbase Advanced Trade WS** `level2` + `market_trades` | No auth for public channels; only outbound messages are rate-limited (8 msg/s/IP). |
| Cross-venue sanity | **ccxt (pro)** watchers for Binance / Bybit / OKX top-of-book | Cross-venue mid and stale-feed detection only. Do not route hot-path decisions through the normalisation layer. |

### Reference / divergence (slow path)

| Source | Role | Free budget |
|---|---|---|
| **Pyth Hermes** SSE stream | Off-chain oracle reference | Free; 10 req / 10 s / IP. One SSE connection is well inside that. |
| **DefiLlama** `coins.llama.fi` | Slow reference price, TVL, DEX volumes | Free, no key (~500 req / 5 min [S]). |
| **CoinGecko Demo** | Slow reference (existing adapter) | 10k credits/month → budget ~1 call per asset per 5 min. |
| **CoinMarketCap Basic** | Listings/metadata only | Free tier has **no** historical OHLCV. |
| CryptoCompare / CoinDesk Data | **Retire.** Free tier was withdrawn 21 May 2026 [V]. | — |

### On-chain (general EVM)

- **web3.py v7/v8 `WebSocketProvider` + `eth_subscribe`** on **Alchemy** free tier
  (30M CU/month, 25 rps, WSS included) as primary RPC; **Chainstack Developer** or
  **dRPC** free tiers as failover.
- **Codex** (free 10k req/month) or **GeckoTerminal** (free, 30 rpm) for aggregated
  pool stats and discovery.

### Backtest data

- **Binance Vision** monthly 1m klines + aggTrades: free, bulk, since 2017. Best
  free minute-bar archive.
- **Kraken quarterly OHLCVT CSV** for our actual execution venue, topped up with a
  Kraken REST `Trades` walk (`since` in ns, 1000/call) to cover the gap since the
  last quarterly drop.
- **Coinbase public candles** (350/call, paginate by start/end).
- **Tardis.dev** only if order-book replay becomes necessary (trial first; paid).
- Freqtrade's `download-data` already handles Kraken's 720-candle REST cap.

## Robinhood Chain

### Network facts [V — docs.robinhood.com]

| Item | Value |
|---|---|
| Mainnet chain ID | **4663** |
| Testnet chain ID | **46630** |
| Public mainnet RPC | `https://rpc.mainnet.chain.robinhood.com` — documented as rate-limited, no archive data, **not recommended for production** |
| Public testnet RPC | `https://rpc.testnet.chain.robinhood.com` |
| Public WSS JSON-RPC | **None documented.** Robinhood's docs point to Alchemy: `wss://robinhood-mainnet.g.alchemy.com/v2/{KEY}` |
| Sequencer feed (Nitro feed, not JSON-RPC) | `wss://feed.mainnet.chain.robinhood.com` / `wss://feed.testnet.chain.robinhood.com` |
| Explorer | https://robinhoodchain.blockscout.com (Blockscout is official; Etherscan does not support the chain). Testnet: https://explorer.testnet.chain.robinhood.com |
| Gas token | ETH |
| Stack | Arbitrum Orbit / Nitro, blob DA to Ethereum |
| Block time / finality | ~100 ms blocks; sub-second sequencer soft-confirm; minutes to L1 posting; ~13 min Ethereum finality; 7-day withdrawal challenge window |
| Launch | Testnet 10 Feb 2026, mainnet 1 Jul 2026 — **on-chain history is only ~2 months deep** |
| Canonical tokens | WETH `0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73`; USDG `0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168`; stock-token list generated from an on-chain registry (https://docs.robinhood.com/chain/contracts) |

Sources: https://docs.robinhood.com/chain/connecting ,
https://docs.robinhood.com/chain/run-a-full-node ,
https://docs.robinhood.com/chain/transaction-finality

Numeric public-RPC rate limits are **[?]** — a "100 rps/IP, 1 WS per IP" figure
circulates but is not on any page we could fetch.

### Robinhood Stock Token off-chain API [V]

`https://api.robinhood.com/rhj/` — `/assets` (metadata, deployment addresses,
corporate-action multiplier; 15 s cache), `/prices/{symbol}` (token-denominated
USD bid/ask, volume, halt status; 15 s cache), `/corporate-actions` (1 h cache).
Stated limit 60 req/s. No websocket. https://docs.robinhood.com/chain/stock-token-apis/

### DEXs and routers

| Venue | Status | Key addresses |
|---|---|---|
| **Uniswap v3** [V] | Live since day one | Factory `0x1f7d7550b1b028f7571e69a784071f0205fd2efa`; QuoterV2 `0x33e885ed0ec9bf04ecfb19341582aadcb4c8a9e7`; SwapRouter02 `0xcaf681a66d020601342297493863e78c959e5cb2`; UniversalRouter `0x8876789976decbfcbbbe364623c63652db8c0904`; Permit2 `0x000000000022D473030F116dDEE9F6B43aC78BA3` — https://developers.uniswap.org/docs/protocols/v3/deployments/v3-robinhood-chain-deployments |
| **Uniswap v4** [V] | Live | PoolManager `0x8366a39cc670b4001a1121b8f6a443a643e40951`; StateView `0xf3334192d15450cdd385c8b70e03f9a6bd9e673b`; V4Quoter `0x8dc178efb8111bb0973dd9d722ebeff267c98f94`; UniversalRouter as above — https://developers.uniswap.org/docs/protocols/v4/deployments |
| **1inch** [V] | Swap (Classic + Fusion), Spot Price, Orderbook, Token, Balance APIs on chain 4663 via the 1inch Developer Portal (free tier; paid from $20/mo) | https://business.1inch.com/chains/robinhood |
| **Arcus** (dYdX Labs + Robinhood Crypto) | Spot trading of ~95 stock tokens; RWA perps waitlisted. AMM vs. CLOB design and public API **[?]** | https://arcus.xyz/ |
| Rialto, Pleiades, launchpads (hood.fun etc.) [S] | Rialto: spot + lending; Pleiades: proprietary AMM (not public liquidity); launchpads graduate into Uniswap pools | — |

For the executor in `traderstack.execution.robinhood_chain`, the router
allowlist should start with UniversalRouter and/or SwapRouter02 only, after an
operator re-verifies the addresses against the Uniswap deployments page.

### Oracles on Robinhood Chain [V]

- **Chainlink Data Feeds**: crypto plus ~95 [S] tokenized-equity feeds, and an L2
  Sequencer Uptime Feed. Equity feeds are 24/5 and may hold the last price over
  weekends — **always check `updatedAt`**, `oraclePaused()` (corporate actions)
  and `uiMultiplier()`. Address list:
  https://docs.chain.link/data-feeds/tokenized-equity-feeds/robinhood
- **Chainlink Data Streams**: Robinhood docs give a mainnet Verifier Proxy
  (`0xcE73c8ad08CBDEaCa6078BF0627C8fe0a9a536E7`) but Chainlink's own
  supported-networks page omits the chain **[?]**. SDKs are Go/TS/Rust only.
- **Pyth is not deployed on Robinhood Chain** [V]. Use Hermes off-chain as a
  reference only.

### Indexers and data vendors supporting chain 4663

| Vendor | Support | Notes |
|---|---|---|
| The Graph | Yes [V] — slug `robinhood`, `eip155:4663` | 100k free queries/mo, then $2/100k. No public Uniswap subgraph found yet [?] — deploy our own. |
| Goldsky | Yes [V] — subgraphs, Mirror/Turbo pipelines, Edge RPC | $100 starter credit; pay-as-you-go. |
| Envio HyperSync | Yes [V] — `https://robinhood.hypersync.xyz`, Python client | Free dev tier; token required. Best for rebuilding swap history from logs. |
| Dune | Yes [V] | Minutes latency; analytics, not real-time. |
| DefiLlama | Yes [V] — `chainId: 4663` in `/v2/chains` | Free. |
| GeckoTerminal / CoinGecko onchain | Yes [V] — network id `robinhood` | GT free 30 rpm; OHLCV per pool. |
| DexScreener | Yes [V] — `chainId: "robinhood"` | Free, no key; no candles, no websocket. |
| Bitquery | Yes [V] — `EVM(network: robinhood)`; decodes Uniswap v4 + launchpads; WS + Kafka | Pro $79/mo for websocket. |
| Codex (Defined.fi) | Yes [V] — websocket subscriptions | Free 10k req/mo. |
| Alchemy | Yes [V] — HTTPS + WSS, Prices/Token/Transfers APIs, webhooks | No Debug/Trace API on this chain. |
| QuickNode, dRPC, Chainstack | Yes [V/S] | Recommended providers per Robinhood docs. |
| Blockscout multichain API | Yes [V] — `https://api.blockscout.com/4663/api/v2` | 100k credits/day @ 5 rps free; use for ABIs/decoded txs, not latency. |
| Moralis | **No** [V] | — |
| Birdeye, Ponder, Nansen, Infura | **[?]** | Birdeye is Solana-centric; assume unsupported. |

### Robinhood Chain wiring plan

1. **RPC**: Alchemy HTTPS + WSS (free tier) as primary; Chainstack or dRPC as
   failover. Never point the bot at the public RPC (no WSS, no archive,
   rate-limited).
2. **Real-time swaps / liquidity**: `eth_subscribe("logs")` on the Uniswap v4
   PoolManager singleton (one subscription covers every v4 pool) and on
   individual v3 pools resolved via the factory. Read v4 state via StateView,
   quote via V4Quoter / QuoterV2. Optionally consume the sequencer feed for
   pre-confirmation ordering.
3. **Aggregates / discovery**: GeckoTerminal and DexScreener (free) for pool
   discovery and liquidity screening; Codex or Bitquery if a vendor-side
   real-time trade stream is required.
4. **Stock-token reference**: Chainlink tokenized-equity feeds on-chain with
   staleness checks, cross-checked against `api.robinhood.com/rhj/prices/{symbol}`.
   Crypto pairs: Chainlink on-chain + Pyth Hermes off-chain.
5. **Backfill**: Envio HyperSync or Goldsky to rebuild swap history from logs;
   Dune/DefiLlama for chain-level metrics.

## CEX websocket streams (public, unauthenticated)

| Source | Channels | Historical | Limits | Python |
|---|---|---|---|---|
| Kraken WS v2 `wss://ws.kraken.com/v2` [V] | ticker, book (10–1000), trade, ohlc | REST OHLC 720/call; Trades 1000/call with ns `since` (full history walkable) | ≤200 symbols/conn; rate counter 200/s (500/s Pro) [S] | ccxt, python-kraken-sdk |
| Coinbase Advanced Trade WS [V] | ticker, ticker_batch, level2, market_trades, candles | Public candles 350/call | 8 msg/s/IP outbound; must subscribe within 5 s | coinbase-advanced-py, ccxt |
| Binance Spot WS [V] | bookTicker, depth, aggTrade, kline | Binance Vision bulk | 1024 streams/conn; 24 h connection life; geo-restricted | python-binance, ccxt |
| Bybit v5 WS [V] | orderbook, publicTrade, tickers, kline | REST kline | ≤500 conns / 5 min | pybit, ccxt |
| OKX WS [V] | tickers, books, bbo-tbt, trades, candles | REST candles | 3 conn req/s/IP; 30 conns/channel | python-okx, ccxt |

## Historical OHLCV

| Source | Depth | Free? | Notes |
|---|---|---|---|
| Binance Vision [V] | 1m since 2017, monthly/daily zips with checksums | Yes, no key | https://github.com/binance/binance-public-data |
| Kraken OHLCVT CSV [V] | 1m full history, refreshed quarterly | Yes | https://support.kraken.com/articles/360047124832 |
| Coinbase public candles [V] | 1m–1d, 350/call | Yes | Paginate by start/end |
| CryptoDataDownload [V] | Daily/hourly/1m CSV mirrors since 2017 | Yes | Kraken page currently unavailable; verify gaps |
| CoinGecko [V] | Demo: daily, 1–2 y; paid: hourly 10 y; Enterprise: 5-min | Partial | Coin-level, not exchange-level |
| CoinMarketCap [V] | Historical OHLCV only from Builder $29/mo | No | — |
| CoinDesk Data (ex-CryptoCompare) [V] | Deep | **No** (free tier retired May 2026) | Migrate away |
| Tardis.dev [V] | Tick trades + L2 books, 2019+, Kraken included | Trial only | Order-book replay gold standard; paid |
| Kaiko, Amberdata [S] | Deep | No | Enterprise/sales only |
| Tiingo [V] | Multi-year | No (crypto from $30/mo) | — |
| On-chain (Robinhood) | Since pool creation (Jul 2026+) | GT free | GeckoTerminal/Codex bars, or rebuild from Swap logs |

## On-chain analytics and oracles

| Source | What | Free? | Notes |
|---|---|---|---|
| Chainlink Data Feeds | On-chain aggregator reads via RPC | Yes | `AggregatorV3Interface` via web3.py; staleness checks mandatory |
| Pyth Hermes [V] | `/v2/updates/price/latest`, SSE stream | Yes, 10 req / 10 s / IP | Not on Robinhood Chain; reference only |
| DefiLlama [V/S] | TVL, volumes, prices, chain data | Yes | Pro $300/mo for higher limits |
| Dune | SQL over decoded tables | Free credits [?] | Minutes latency |
| Nansen [S] | Smart-money labels | 100 credits + 10/day | Robinhood coverage [?] |
| Glassnode [S] | BTC/ETH metrics | No free API | — |
| Santiment [S] | On-chain/social/dev metrics | 1000 calls/mo | `sanpy` |
| Token Terminal [V] | Fundamentals | API is custom tier only | — |

## Python libraries (status at research time)

| Library | Status |
|---|---|
| ccxt (Pro merged) | Active, PyPI 4.5.77 [V] |
| web3.py | v7 stable; **v8.0.0 released 31 Aug 2026** [V] with `batch_requests()` |
| ape | Active [S]; ApeWorX now also stewards web3.py |
| cryptofeed | **GitHub archived 7 Jul 2026 [S]**, PyPI 2.5.0 Aug 2026 [V] — maintenance mode; do not add as a new dependency |
| TA-Lib python | Active, 0.7.1 Jul 2026 [S] |
| pandas-ta | Original at archival risk [S]; use `pandas-ta-classic` fork if needed |
| vectorbt | 1.1.0 Jul 2026 [V] (community-maintained; PRO is paid) |
| backtesting.py | 0.6.6 Jul 2026 [V] |
| freqtrade | 2026.8, 31 Aug 2026 [V] |
| hummingbot | 2.16.0, 29 Jul 2026 [V]; Gateway covers Uniswap |

## Explicitly unverified

- Numeric public-RPC rate limits for Robinhood Chain.
- Any official public WSS JSON-RPC endpoint from Robinhood (only Alchemy WSS and the sequencer feed are documented).
- Exact number of Chainlink equity feeds (~95 reported by press).
- General availability of Chainlink Data Streams on Robinhood Chain.
- Arcus internals and public API; Lighter's on-chain footprint on Robinhood.
- Birdeye, Ponder, Nansen and Infura coverage of Robinhood Chain.
- Kraken WS v2 rate-counter figures (docs page returned 404).
- DexScreener 300 rpm limit for pairs endpoints.
- Dune free-plan credits; Tardis.dev list prices; Codex tier details; CoinGecko Demo access to onchain endpoints.
- Existence of a public Uniswap v3/v4 subgraph already deployed for Robinhood Chain.
