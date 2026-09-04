from collections.abc import AsyncIterator
from typing import Protocol

from traderstack.candles import Candle
from traderstack.market.models import BookSnapshot, MarketTick, ReferencePrice


class VenueMarketDataProvider(Protocol):
    def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]: ...


class ReferencePriceProvider(Protocol):
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]: ...


class CandleHistoryProvider(Protocol):
    async def fetch(
        self, symbol: str, resolution: str = ..., *, count: int = ...
    ) -> tuple[Candle, ...]: ...


class ProviderHealth(Protocol):
    async def healthy(self) -> bool: ...


# --- providers (Epic 2): order-book snapshot handling --------------------------


class BookSnapshotProvider(Protocol):
    def stream_books(self, symbols: tuple[str, ...]) -> AsyncIterator[BookSnapshot]: ...
