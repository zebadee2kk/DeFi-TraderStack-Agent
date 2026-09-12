from collections.abc import AsyncIterator
from typing import Protocol

from traderstack.candles import Candle
from traderstack.market.models import (
    BookSnapshot,
    BookTicker,
    LiquidationWindowSnapshot,
    MarketTick,
    ReferencePrice,
)


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


# --- paper-research edge data plane -------------------------------------------
#
# Snapshot readers for background streaming collectors. ``snapshot`` / ``latest``
# are in-process (no network): the WS reconnect loop lives on the collector.
# Same split as Kraken ticker/book vs ProviderRegistry-wrapped REST.


class LiquidationSnapshotProvider(Protocol):
    def snapshot(self, asset: str) -> LiquidationWindowSnapshot | None: ...


class BookTickerSnapshotProvider(Protocol):
    def latest(self, asset: str) -> BookTicker | None: ...


class EdgeFeedCollector(Protocol):
    """Background streaming collector started by ContinuousPaperService.run."""

    feed_name: str

    async def collect(self) -> None: ...
