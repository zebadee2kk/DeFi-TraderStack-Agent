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
  free minute-bar archive. **Wired** as `traderstack-download-candles --venue
  binance_vision` (#133) — see "Multi-year candle fetchers" below.
- **Kraken quarterly OHLCVT CSV** for our actual execution venue, topped up with a
  Kraken REST `Trades` walk (`since` in ns, 1000/call) to cover the gap since the
  last quarterly drop. **Wired** as `--venue kraken_archive` (local file loader).
- **Coinbase public candles** — **300** per call, paginate by start/end. (An
  earlier note in this file said 350; 300 is the documented cap and is what the
  adapter uses.) **Wired** as `--venue coinbase`.
- **Tardis.dev** only if order-book replay becomes necessary (trial first; paid).

#### Multi-year candle fetchers (#133) [V, shape from vendor docs — see the reachability caveat]

Before #133 every strategy catalog was scored on Kraken's 720-bar public REST
cap (~2 years daily) plus one older Binance.US 720 — one regime, and less
history than the #96+A+B+C gates ask for. These three adapters are the backtest
stack named above, finally implemented. All are research-only: they never run
on the trading cycle, the `RiskEngine` never reads them, and they flip no
`PAPER_PROMOTE_*` flag. Operator usage is in `RUNBOOK.md`, "Multi-year candle
archives (#133)".

| Source | Module | Shape | Limits |
|---|---|---|---|
| Coinbase Exchange public candles | `research/candles_coinbase.py` | `GET /products/{id}/candles?granularity=&start=&end=`; rows are `[time, low, high, open, close, volume]` (**not** OHLC order), descending, `time` in unix seconds | 300 candles/request; granularities `{60,300,900,3600,21600,86400}` only — **no native 4h**, so 4h is rolled up from complete 1h buckets; public limit 10 req/s/IP (bursts 15) |
| Binance Vision monthly spot klines | `research/candles_binance_vision.py` | `/data/spot/monthly/klines/{SYM}/{iv}/{SYM}-{iv}-{YYYY}-{MM}.zip` plus a `.CHECKSUM` sibling holding `sha256  filename` | spot from 2017-08; quote is **USDT**, not USD; newer files carry a CSV header row and microsecond timestamps (both handled per-row); delisted symbols are *sometimes* retained (LUNAUSDT 2022-04 was present at issue time) — verify per symbol, never assume |
| Kraken official OHLCVT archive | `research/candles_kraken_archive.py` | headerless `{PAIR}_{minutes}.csv`, columns `timestamp,open,high,low,close,volume,trades`; Kraken asset codes (**XBT**, not BTC) | quarterly Google Drive zips (support article 360047124832) = **manual download**, so this is a local-file loader and makes no network call; 8 timeframes |

Safety properties these adapters hold, tested in `tests/test_candle_archives.py`:

- `status` is `ok` or `skipped`, matching the funding adapters. A skip carries
  **no candles** — a partial series is never returned.
- Missing bars are **gaps**, counted in the report header, never interpolated,
  forward-filled or zero-filled. Timestamps must sit exactly on the UTC
  interval grid.
- An HTTP **429 from Coinbase is a skip, not a retry** — no backoff loop, no
  retry storm against a public endpoint.
- Binance Vision checksums are verified **before** parsing and **fail closed**:
  a mismatch (or data present with no published `.CHECKSUM`) discards the whole
  series, including months that already verified.
- The Kraken archive loader **refuses a partial or unparsable file outright**,
  reporting the offending line rather than the rows that happened to parse.
- Cross-venue sanity: `--cross-check` flags any shared daily bar whose closes
  disagree by more than `MAX_REFERENCE_DIVERGENCE_BPS` (the existing
  version-controlled `Settings` limit, read only). Flagged bars are listed in
  the report and never silently used; venues are never averaged.

**Survivorship-bias caveat (Kraken OHLCVT archive).** The quarterly drop ships
**active pairs only** — pairs Kraken has delisted are absent. A universe or
catalog built from that archive alone sees only survivors and will read better
than the venue actually traded. Treat it as one venue's long tape, not a
bias-free universe. The loader attaches this caveat as a note on every series
it returns.

**Reachability caveat (honest).** The session that implemented #133 could not
reach any of these hosts: the agent egress proxy answered `403` to `CONNECT`
for `api.exchange.coinbase.com`, `data.binance.vision` **and**
`api.kraken.com` (organisation egress policy, not a vendor block). The row
shapes and limits above come from the vendor documentation and the live
probes recorded in issue #133 on 2026-09-13; the adapters have **not** been
run against a live response from that environment. Re-verify the live shapes
from an environment with egress before trusting a first real pull, and treat
the first pull's report header (bar counts, first/last bar, gaps) as the
verification record.
- Freqtrade's `download-data` already handles Kraken's 720-candle REST cap.
- **Funding-rate history (research only):** OKX
  `GET /api/v5/public/funding-rate-history` is typically ~90d of 8h
  prints. Hyperliquid `POST /info` `fundingHistory` is public hourly
  and typically reachable here (independent tape). HTX
  `GET /linear-swap-api/v1/swap_historical_funding_rate` is a public
  8h `funding_rate` tape from 2020-10-21 (BTC-USDT and ETH-USDT). An
  800d lookback yields ≥720 UTC daily sums. Use `funding_rate` only —
  `avg_premium_index` is the funding-formula premium; `realized_rate`
  is null on every historical page probed here. BitMEX
  `GET /api/v1/funding` remains a public settlement tape but the
  venue is **sunsetting** (official closure 23 September 2026 04:00
  UTC; https://www.bitmex.com/blog/bitmex-closure) and is not
  selected for dual-print or paper hedge. Binance USDT-M
  `GET /fapi/v1/fundingRate` is paginable when reachable (often HTTP
  451). `data.binance.vision` monthly `fundingRate` +
  `markPriceKlines` + `indexPriceKlines` zips respond 200 from
  2020-01 even when fapi is 451 — a full dump candidate, not stitched
  this session (HTX REST already fills the 720-day bar). Bybit
  `GET /v5/market/funding/history` is often HTTP 403 (CloudFront
  country block) from this environment. These are skip-not-invent
  inputs for `traderstack-funding-carry`. One venue / one history
  length is single-print and cannot promote. Daily evaluation sums
  settlements per UTC day and omits empty days. Perp-spot basis is
  not invented from last-trade or from `fundingHistory.premium`.
  Dual-print PIT basis on the current Kraken 720 is still
  UNAVAILABLE: HL REST is current-only; HuggingFace
  `asiletto81/hyperliquid` `asset_ctxs` is ≥720d but ends 2026-06-01
  (~617d aligned); HTX daily mark−index exists on one venue; BitMEX
  still has no free ≥720d tape and is closing. Deribit restates 8h
  interest every hour — not wired (would invent 8× carry). Gate
  `from` is capped at 180d; Bitget public history is ~90d; MEXC
  funding is 539d.
- **BTC−ETH relative-value residual (research only):** built from the
  same public Spot daily closes already used by
  `traderstack-dual-print-search` — Kraken `GET /0/public/OHLC`
  (720-bar cap) and Binance.US older-720 (`api.binance.us` when
  `api.binance.com` is HTTP 451). Residual is `r_BTC − r_ETH` on
  aligned `opened_at`; a missing pair day is skipped, not
  zero-filled. No exogenous series. Input to
  `traderstack-relative-value`.
- **BTC+ETH+SOL cross-sectional momentum (research only):** built
  from the same public Spot daily closes — Kraken
  `GET /0/public/OHLC` (720-bar cap) and Binance.US older-720
  (`api.binance.us` when `api.binance.com` is HTTP 451), now
  including `SOL/USD` / `SOLUSDT`. Ranking uses venue-local
  trailing N-day returns; a day missing any of the three closes
  is skipped, not zero-filled and not ranked on a two-asset
  subset. No exogenous series. Input to
  `traderstack-xs-momentum`.
- **Donchian / channel breakout (research only):** built from the
  same public Spot daily OHLC — Kraken `GET /0/public/OHLC`
  (720-bar cap) and Binance.US older-720 (`api.binance.us` when
  `api.binance.com` is HTTP 451). Channel uses prior N-day high/low
  (bars `[t-N, t)`); ATR buffer uses Wilder ATR(14) through t−1.
  A missing/short series is skipped, not zero-filled. No exogenous
  series. Input to `traderstack-donchian-breakout`.
- **Time-series momentum (research only):** built from the same
  public Spot daily closes — Kraken `GET /0/public/OHLC`
  (720-bar cap) and Binance.US older-720 (`api.binance.us` when
  `api.binance.com` is HTTP 451). Each asset uses its own
  trailing N-day close-to-close return (closes through t; fill
  at t+1 open). A missing/short series is skipped, not
  zero-filled. No exogenous series. Input to `traderstack-tsmom`.
- **Bollinger band-fade (research only):** built from the same
  public Spot daily closes — Kraken `GET /0/public/OHLC`
  (720-bar cap) and Binance.US older-720 (`api.binance.us` when
  `api.binance.com` is HTTP 451). Bands are SMA(period) ± k ×
  sample stdev using closes through t; fill at t+1 open. A
  missing/short series is skipped, not zero-filled. No
  exogenous series. Input to `traderstack-bollinger-fade`.
- **Calendar seasonality (research only):** built from the same
  public Spot daily bar timestamps — Kraken `GET /0/public/OHLC`
  (720-bar cap) and Binance.US older-720 (`api.binance.us` when
  `api.binance.com` is HTTP 451). Positions use the UTC civil
  date of bar t only (fill at t+1 open). A missing/short series
  is skipped, not zero-filled. No exogenous series. Input to
  `traderstack-calendar-seasonality`.
- **BTC→ETH lead-lag (research only):** built from the same
  public Spot daily closes — Kraken `GET /0/public/OHLC`
  (720-bar cap) and Binance.US older-720 (`api.binance.us` when
  `api.binance.com` is HTTP 451). The traded asset follows or
  fades the lead asset's L-day close-to-close return (lead
  closes through t; fill at t+1 open of the traded asset).
  Unpaired BTC/ETH days are skipped, not zero-filled. No
  exogenous series. Input to `traderstack-lead-lag`.
- **Volume-confirmed breakout (research only):** built from the
  same public Spot daily OHLC **and** base volume — Kraken
  `GET /0/public/OHLC` (720-bar cap) and Binance.US older-720
  (`api.binance.us` when `api.binance.com` is HTTP 451). Prior
  channel uses bars `[t-N, t)`; volume SMA through t−1 (V=20).
  Missing volume skips that bar (never invented). Quote volume
  is not substituted. A venue without usable base volume fails
  closed for volume names. Fill at t+1 open. No exogenous
  series. Input to `traderstack-volume-breakout`.
- **Wide-universe top-k cross-sectional momentum (research only,
  #140):** universe from Kraken public `GET /0/public/AssetPairs`
  (no auth; a *current* listing, so delisted names are absent —
  survivorship stated in the report header; frozen exclusion list
  for stablecoins / fiat / commodities / wrapped duplicates), then
  one Kraken `GET /0/public/OHLC` `interval=1440` pull per pair
  (720-bar cap, ~1 request/s with a 1 s sleep between pairs; HTTP
  429 or an error is a per-pair skip). Dollar volume for the
  monthly liquidity filter is `close × base volume` from that OHLC
  print only (the charts-spot `PI_*` path reports zero volume and
  is never used). Second-venue prints enter as JSON through
  `traderstack-xs-topk --candles-dir` from the #133 fetchers
  (Coinbase Exchange `/products/{id}/candles?granularity=86400`,
  300 candles/request, reachable; `data.binance.vision` daily spot
  klines, reachable via S3 while `api.binance.com` is HTTP 451 and
  Bybit REST is HTTP 403 — neither REST host is called). A missing
  or short series is a skip, never a zero. Input to
  `traderstack-xs-topk`.

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

### Implemented: real-time swap feed

`traderstack.market.robinhood_chain_feed.RobinhoodChainSwapFeed` implements step
2 of the plan below as a `VenueMarketDataProvider`. It opens a websocket
JSON-RPC session (`ROBINHOOD_CHAIN_WS_URL`), verifies `eth_chainId` against
`ROBINHOOD_CHAIN_ID` before doing anything else, then `eth_subscribe`s to
`logs` for the operator-listed pools (`ROBINHOOD_CHAIN_POOLS`): Uniswap v3
pool addresses directly, and v4 pool ids filtered on the PoolManager
singleton. Each `Swap` is decoded into a `SwapEvent` (amounts, side, post-swap
price from `sqrtPriceX96`, liquidity, tick) and surfaced as a `MarketTick`
whose bid/ask straddle the price by the pool's fee tier, since an AMM's
marginal spread at small size is its fee. Event topics are derived from the
human-readable signatures via an in-module keccak-256 (verified against known
answers in tests) rather than pasted constants. Select it with
`VENUE_FEED=robinhood_chain`; the existing staleness, spread and
independent-reference checks then apply unchanged, and the pre-trade gate
still backtests on the base asset's Kraken USD candles.

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
| Binance USDT-M `!forceOrder@arr` [V] | all-market liquidations | — | 24 h connection life; public, no auth | **Implemented** as paper-research only (`BinanceForceOrderProvider`; not an execution venue) |
| Binance USDT-M `bookTicker` [V] | best bid/ask | — | combined stream; 24 h connection life | **Implemented** as optional second-venue mid (`BookTickerProvider`, `BOOK_TICKER_VENUE=binance`) |
| Binance Spot WS [V] | bookTicker, depth, aggTrade, kline | Binance Vision bulk | 1024 streams/conn; 24 h connection life; geo-restricted | python-binance, ccxt |
| Bybit v5 WS [V] | orderbook, publicTrade, tickers, kline | REST kline | ≤500 conns / 5 min | pybit, ccxt; **tickers.*** wired as optional paper-research bookTicker (`BOOK_TICKER_VENUE=bybit`) |
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

## Polymarket weather (paper research only)

Read-only public APIs used by `traderstack-polymarket-weather-paper`. No
credentials. Not on the crypto execution path.
`traderstack-polymarket-weather-eval` does **not** invent a historical
CLOB tape from these endpoints: closed Gamma events without a stored
decision-time mid and an official station high are not scored.

| Source | Role | Auth | Write |
|---|---|---|---|
| Gamma `https://gamma-api.polymarket.com/events` [S] | Discover open weather-tagged events/markets | None | None |
| CLOB `https://clob.polymarket.com/midpoint` [S] | Probability-like mid for a token id | None | **None — client refuses order/auth paths** |
| Open-Meteo `https://api.open-meteo.com/v1/forecast` [V] | Daily `temperature_2m_max` in °F | None | None |
| NOAA `https://api.weather.gov` [V] | Optional forecast; User-Agent required | None | None |

Re-verify Gamma/CLOB query parameters against Polymarket's current public
docs before relying on a live (still paper) cycle. Tag slugs and weather
question phrasing change. The adapters fail closed on unparseable payloads.

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
