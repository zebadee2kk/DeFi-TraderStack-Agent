# ADR-005 — MVP Exchange and Market-Data Venue

Status: Accepted for MVP paper trading
Date: 2026-08-11

## Decision
Use Kraken spot as the initial direct venue for the MVP market-data and paper-execution path, while keeping all venue access behind interfaces so another exchange can be added without changing strategy or risk logic.

Initial paper universe:
- BTC/USD
- ETH/USD
- SOL/USD

## Why Kraken
- Hummingbot currently exposes a maintained Kraken spot connector with WebSocket connectivity, spot candle feed, and a dedicated paper-trade mode.
- Hummingbot standardises exchange-specific market-data and order semantics, reducing bespoke exchange code.
- Kraken publishes first-party REST and WebSocket APIs suitable for direct validation and later fallback work.

## Constraints
- Spot only for MVP. No perpetuals or leverage.
- No live credentials in the MVP acceptance phase.
- Direct venue WebSocket data is authoritative for execution-adjacent price checks.
- CoinGecko/CoinMarketCap are reference and divergence sources, not the execution price source.
- Hummingbot MCP is not granted unrestricted execution authority. Our deterministic risk service remains the mandatory control point.

## References checked 2026-08-11
- https://hummingbot.org/exchanges/kraken/
- https://hummingbot.org/connectors/
- https://hummingbot.org/mcp/
- https://docs.kraken.com/

## Revisit triggers
Re-evaluate this ADR before live capital, before derivatives, or if connector health/support materially changes.
