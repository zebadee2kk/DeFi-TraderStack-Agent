"""Kraken public Spot OHLC candle history.

Paper-trading and research share this adapter so a cycle never hits the
futures.kraken.com charts path (that endpoint returns 400 for spot pairs).

**Verified** against Kraken's public API documentation
(https://docs.kraken.com/api/docs/rest-api/get-ohlc-data):

- Endpoint: ``GET https://api.kraken.com/0/public/OHLC``
- Query params: ``pair`` (e.g. ``BTCUSD``), ``interval`` (minutes: 1, 5, 15, 30,
  60, 240, 1440, 10080, 21600), and optional ``since`` (unix seconds).
- Response: ``{"error": [...], "result": {"<pair>": [[time, open, high, low,
  close, vwap, volume, count], ...], "last": <unix seconds>}}``.
- Cap: up to 720 of the most recent entries per call.
- The final row of every response is the current, not-yet-committed timeframe
  and must be dropped before a backtest or pre-trade gate sees it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from traderstack.candles import Candle

KRAKEN_REST_BASE_URL = "https://api.kraken.com"
KRAKEN_OHLC_PATH = "/0/public/OHLC"

# Kraken's `interval` query parameter is in minutes and only accepts this fixed set.
INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


def kraken_pair(symbol: str) -> str:
    base, _, quote = symbol.upper().partition("/")
    if not quote:
        raise ValueError(f"symbol must be formatted BASE/QUOTE, got {symbol!r}")
    return f"{base}{quote}"


def parse_ohlc_row(row: object, *, symbol: str, resolution: str) -> Candle:
    if not isinstance(row, list) or len(row) < 7:
        raise TypeError("unexpected Kraken OHLC row")
    timestamp = int(row[0])
    return Candle(
        symbol=symbol.upper(),
        interval=resolution,
        opened_at=datetime.fromtimestamp(timestamp, tz=UTC),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[6]),
    )


def parse_ohlc_payload(payload: object) -> tuple[list[list[Any]], int]:
    """Split a Kraken OHLC JSON body into (rows, last-cursor)."""
    if not isinstance(payload, dict):
        raise TypeError("unexpected Kraken candle response")
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken OHLC error: {errors}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("unexpected Kraken OHLC result shape")
    result = dict(result)
    if "last" not in result:
        raise TypeError("unexpected Kraken OHLC result shape")
    last = int(result.pop("last"))
    if len(result) != 1:
        raise TypeError(f"unexpected Kraken OHLC result shape: {sorted(result)}")
    (rows,) = result.values()
    if not isinstance(rows, list):
        raise TypeError("unexpected Kraken OHLC row payload")
    return rows, last


async def fetch_ohlc_page(
    client: httpx.AsyncClient,
    *,
    pair: str,
    interval_minutes: int,
    since: int | None,
) -> tuple[list[list[Any]], int]:
    """One call to Kraken's public OHLC endpoint; returns (rows, last-cursor)."""
    params: dict[str, str | int] = {"pair": pair, "interval": interval_minutes}
    if since is not None:
        params["since"] = since
    response = await client.get(KRAKEN_OHLC_PATH, params=params)
    response.raise_for_status()
    return parse_ohlc_payload(response.json())


def candles_from_ohlc_rows(
    rows: list[list[Any]],
    *,
    symbol: str,
    resolution: str,
    drop_uncommitted: bool = True,
) -> list[Candle]:
    candles = [parse_ohlc_row(row, symbol=symbol, resolution=resolution) for row in rows]
    candles.sort(key=lambda candle: candle.opened_at)
    if drop_uncommitted and candles:
        # The last bar of every page is "not yet committed" per Kraken's docs.
        candles = candles[:-1]
    return candles


@dataclass
class KrakenCandleProvider:
    base_url: str = KRAKEN_REST_BASE_URL
    client: httpx.AsyncClient | None = None

    async def fetch(
        self,
        symbol: str,
        resolution: str = "1h",
        *,
        count: int = 250,
    ) -> tuple[Candle, ...]:
        if count <= 0:
            raise ValueError("count must be positive")
        if resolution not in INTERVAL_MINUTES:
            raise ValueError(
                f"unsupported resolution {resolution!r}; use one of {sorted(INTERVAL_MINUTES)}"
            )
        pair = kraken_pair(symbol)
        interval_minutes = INTERVAL_MINUTES[resolution]

        if self.client is not None:
            rows, _last = await fetch_ohlc_page(
                self.client, pair=pair, interval_minutes=interval_minutes, since=None
            )
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=15,
            ) as client:
                rows, _last = await fetch_ohlc_page(
                    client, pair=pair, interval_minutes=interval_minutes, since=None
                )

        candles = candles_from_ohlc_rows(rows, symbol=symbol, resolution=resolution)
        return tuple(candles[-count:])
