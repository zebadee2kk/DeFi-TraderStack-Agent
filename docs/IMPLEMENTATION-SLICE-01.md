# Implementation Slice 01 — Live Market Data to Paper Proposal

## Goal
Build the first end-to-end vertical slice without enabling live capital:

1. stream Kraken spot ticker data for BTC/USD, ETH/USD and SOL/USD;
2. normalise it into `MarketTick`;
3. fetch independent CoinGecko and CoinMarketCap USD reference prices;
4. reject stale or materially divergent inputs;
5. construct a canonical feature vector;
6. generate a deterministic demonstration signal;
7. convert it into a typed `TradeProposal`;
8. pass it through the existing deterministic risk engine;
9. produce a paper-order intent only when risk allows it.

## Trust boundary
External market and intelligence providers are untrusted inputs. No provider response can submit an order directly. The pipeline must traverse validation and the deterministic risk engine.

## MVP venue
Kraken spot remains the primary venue. Public market data uses Kraken Spot WebSocket v2. Hummingbot remains the eventual execution adapter; this slice stops at a typed paper-order intent so exchange credentials are not required.

## Reference providers
CoinGecko and CoinMarketCap are used as independent reference-price sources. Their adapters are deliberately isolated behind the `ReferencePriceProvider` protocol so either can be replaced without changing strategy or risk code.

## Failure behaviour
Fail closed when:
- the Kraken tick is stale;
- no independent reference prices are available;
- reference-price divergence exceeds policy;
- spread exceeds policy;
- portfolio/risk policy rejects the proposal;
- a provider response is malformed.

A single unavailable reference provider may be tolerated only when at least one other independent reference remains healthy and consistent.
