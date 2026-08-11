from collections.abc import AsyncIterator
from typing import Protocol

from traderstack.market.models import MarketTick, ReferencePrice


class VenueMarketDataProvider(Protocol):
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]: ...


class ReferencePriceProvider(Protocol):
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]: ...


class ProviderHealth(Protocol):
    async def healthy(self) -> bool: ...
