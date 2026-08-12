from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from traderstack.candles import Candle
from traderstack.market.candle_feed import interval_to_seconds

KRAKEN_BASE_ALIASES = {"BTC": "XBT"}
# Sanity bounds for second-resolution epochs (2000-01-01 .. 2100-01-01); the
# previous implementation silently mis-parsed millisecond timestamps.
_MIN_EPOCH_SECONDS = 946_684_800
_MAX_EPOCH_SECONDS = 4_102_444_800


def kraken_pair(symbol: str) -> str:
    base, _, quote = symbol.upper().partition("/")
    if not base or not quote:
        raise ValueError(f"symbol must be BASE/QUOTE, got {symbol!r}")
    return f"{KRAKEN_BASE_ALIASES.get(base, base)}{quote}"


@dataclass
class KrakenCandleProvider:
    """Fetches OHLC candles from the Kraken spot REST API (/0/public/OHLC)."""

    base_url: str = "https://api.kraken.com"
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
        interval_minutes = interval_to_seconds(resolution) // 60
        if interval_minutes < 1:
            raise ValueError(f"resolution {resolution!r} is below Kraken's 1m minimum")
        params: dict[str, str | int] = {"pair": kraken_pair(symbol), "interval": interval_minutes}
        if self.client is not None:
            response = await self.client.get("/0/public/OHLC", params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=15,
            ) as client:
                response = await client.get("/0/public/OHLC", params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("unexpected Kraken OHLC response")
        errors = payload.get("error")
        if errors:
            raise RuntimeError(f"Kraken OHLC API error: {errors}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TypeError("Kraken OHLC response missing result")
        # The result key is Kraken's canonical pair name (e.g. XXBTZUSD for
        # XBTUSD), so take the single non-"last" entry instead of matching it.
        rows = next((value for key, value in result.items() if key != "last"), None)
        if not isinstance(rows, list):
            raise TypeError("Kraken OHLC response missing candle rows")

        candles = [self._parse_row(row, symbol, resolution) for row in rows]
        candles.sort(key=lambda candle: candle.opened_at)
        return tuple(candles[-count:])

    @staticmethod
    def _parse_row(row: object, symbol: str, resolution: str) -> Candle:
        if not isinstance(row, list) or len(row) < 7:
            raise TypeError("unexpected Kraken OHLC row shape")
        timestamp = row[0]
        if not isinstance(timestamp, int | float):
            raise TypeError("Kraken OHLC row missing timestamp")
        if not _MIN_EPOCH_SECONDS <= float(timestamp) <= _MAX_EPOCH_SECONDS:
            raise ValueError(f"implausible Kraken candle timestamp {timestamp!r}")
        try:
            open_, high, low, close = (float(row[index]) for index in range(1, 5))
            volume = float(row[6])
        except (TypeError, ValueError) as exc:
            raise TypeError("Kraken OHLC row contains non-numeric fields") from exc
        return Candle(
            symbol=symbol.upper(),
            interval=resolution,
            opened_at=datetime.fromtimestamp(float(timestamp), tz=UTC),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
