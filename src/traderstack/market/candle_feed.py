from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from traderstack.candles import Candle

_INTERVAL_UNITS = {"m": 60, "h": 3_600, "d": 86_400, "w": 604_800}


def interval_to_seconds(interval: str) -> int:
    unit = interval[-1:].lower()
    magnitude = interval[:-1]
    if unit not in _INTERVAL_UNITS or not magnitude.isdigit() or int(magnitude) <= 0:
        raise ValueError(f"unsupported candle interval {interval!r}")
    return int(magnitude) * _INTERVAL_UNITS[unit]


class CandleFetcher(Protocol):
    async def fetch(
        self,
        symbol: str,
        resolution: str = "1h",
        *,
        count: int = 250,
    ) -> tuple[Candle, ...]: ...


@dataclass
class CandleFeed:
    """TTL-cached candle history per symbol with forming-candle exclusion.

    The most recent candle returned by chart endpoints is usually still forming;
    including it would let signals react to an unfinished bar, so it is dropped.
    On fetch failure the last good history is served until it exceeds
    max_staleness_seconds, at which point the failure propagates.
    """

    fetcher: CandleFetcher
    interval: str = "1h"
    count: int = 250
    refresh_seconds: float = 300.0
    max_staleness_seconds: float = 1_800.0
    drop_forming: bool = True
    _cache: dict[str, tuple[datetime, tuple[Candle, ...]]] = field(default_factory=dict)

    async def get(self, symbol: str) -> tuple[Candle, ...]:
        key = symbol.upper()
        now = datetime.now(UTC)
        cached = self._cache.get(key)
        if cached is not None and (now - cached[0]).total_seconds() <= self.refresh_seconds:
            return cached[1]
        try:
            candles = await self.fetcher.fetch(symbol, self.interval, count=self.count)
        except Exception:
            if cached is not None and (now - cached[0]).total_seconds() <= self.max_staleness_seconds:
                return cached[1]
            raise
        if self.drop_forming:
            candles = self._without_forming(candles, now)
        self._cache[key] = (now, candles)
        return candles

    def _without_forming(self, candles: tuple[Candle, ...], now: datetime) -> tuple[Candle, ...]:
        if not candles:
            return candles
        span = timedelta(seconds=interval_to_seconds(self.interval))
        if candles[-1].opened_at + span > now:
            return candles[:-1]
        return candles
