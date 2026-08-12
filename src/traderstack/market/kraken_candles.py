from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from traderstack.candles import Candle


@dataclass
class KrakenCandleProvider:
    base_url: str = "https://futures.kraken.com"
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
        market_symbol = symbol.replace("/", "").upper()
        path = f"/api/charts/v1/spot/{market_symbol}/{resolution}"
        params = {"count": count}
        if self.client is not None:
            response = await self.client.get(path, params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=15,
            ) as client:
                response = await client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("candles") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise TypeError("unexpected Kraken candle response")

        candles: list[Candle] = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("unexpected Kraken candle item")
            timestamp = row.get("time")
            if not isinstance(timestamp, int | float):
                raise TypeError("Kraken candle missing timestamp")
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    interval=resolution,
                    opened_at=datetime.fromtimestamp(float(timestamp), tz=UTC),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0.0)),
                )
            )
        candles.sort(key=lambda candle: candle.opened_at)
        return tuple(candles)
