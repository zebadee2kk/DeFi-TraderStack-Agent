"""Longer Kraken *charts* history than public Spot OHLC allows.

Kraken's documented public Spot OHLC (``GET /0/public/OHLC``) returns at most
720 committed bars and ``since`` only pages *forward*. Empirically (2026-09-12)
a ``since`` of 180 days ago still returns the same most-recent 720 1h bars.

The futures charts spot path (the same family as ``KrakenCandleProvider``, but
with the ``PI_*`` contract id) does accept a larger ``count``:

* ``count=4320`` 1h → ~180 calendar days for BTC/ETH/SOL
* ``count=2000`` 1h → ~83 days
* public OHLC 4h → 720 bars ≈ 120 days as a fallback mix

Closes on this path are a few bps away from ``/0/public/OHLC`` (index / mark
style, not the exact spot print) and volume is often zero. Research-only:
this module is not wired into the paper ``KrakenCandleProvider`` (which still
requests ``BTCUSD`` and falls back to the 720-bar public OHLC).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from traderstack.candles import Candle, interval_to_seconds

KRAKEN_CHARTS_BASE_URL = "https://futures.kraken.com"
KRAKEN_CHARTS_SPOT_PATH = "/api/charts/v1/spot/{market}/{resolution}"
CHARTS_HARD_CAP = 7000

# Public OHLC pair names do not work on this path (HTTP 400 for BTCUSD).
_CHART_MARKETS: dict[str, str] = {
    "BTC/USD": "PI_XBTUSD",
    "XBT/USD": "PI_XBTUSD",
    "ETH/USD": "PI_ETHUSD",
    "SOL/USD": "PI_SOLUSD",
}


def chart_market_for(symbol: str) -> str:
    key = symbol.upper()
    if key in _CHART_MARKETS:
        return _CHART_MARKETS[key]
    raise ValueError(
        f"no Kraken charts PI_* mapping for {symbol!r}; known: {sorted(_CHART_MARKETS)}"
    )


def _opened_at(raw: float) -> datetime:
    timestamp = float(raw)
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return datetime.fromtimestamp(timestamp, tz=UTC)


async def download_kraken_charts(
    symbol: str,
    resolution: str,
    *,
    count: int = 4320,
    base_url: str = KRAKEN_CHARTS_BASE_URL,
    client: httpx.AsyncClient | None = None,
) -> tuple[Candle, ...]:
    """Fetch up to ``count`` committed charts-spot bars, dropping the last row.

    The last bar of a live page is treated as uncommitted (same posture as
    public OHLC). Request ``count + 1`` so a caller asking for 4320 committed
    1h bars can actually get ~180 days.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    interval_to_seconds(resolution)
    market = chart_market_for(symbol)
    path = KRAKEN_CHARTS_SPOT_PATH.format(market=market, resolution=resolution)
    fetch_count = min(count + 1, CHARTS_HARD_CAP)
    params = {"count": fetch_count}

    async def _get(active: httpx.AsyncClient) -> object:
        response = await active.get(path, params=params)
        response.raise_for_status()
        return response.json()

    if client is not None:
        payload = await _get(client)
    else:
        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30) as owned:
            payload = await _get(owned)

    rows = payload.get("candles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TypeError("unexpected Kraken charts response")

    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("unexpected Kraken charts candle")
        timestamp = row.get("time")
        if not isinstance(timestamp, int | float):
            raise TypeError("Kraken charts candle missing timestamp")
        candles.append(
            Candle(
                symbol=symbol.upper(),
                interval=resolution,
                opened_at=_opened_at(timestamp),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
            )
        )
    candles.sort(key=lambda candle: candle.opened_at)
    if candles:
        candles = candles[:-1]
    if len(candles) > count:
        candles = candles[-count:]
    return tuple(candles)


def describe_ohlc_cap(*, interval: str, requested: int, received: int) -> str:
    """Operator-facing note when public OHLC cannot honour a long request."""
    return (
        f"Kraken public Spot OHLC ({interval}) returned {received} bars "
        f"(requested {requested}). The documented cap is 720 most-recent "
        "entries; `since` pages forward only and does not unlock older "
        "history. Use the charts-spot PI_* path for 90–180d 1h."
    )
