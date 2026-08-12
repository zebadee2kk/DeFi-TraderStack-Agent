import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from traderstack.market.models import MarketSource, MarketTick
from traderstack.market.ticker_feed import PersistentTickerFeed


def tick(symbol: str, last: float) -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        observed_at=datetime.now(UTC),
        bid=last - 0.05,
        ask=last + 0.05,
        last=last,
    )


class StreamingVenue:
    """Yields the configured ticks, then holds the connection open silently."""

    def __init__(self, ticks: tuple[MarketTick, ...]) -> None:
        self.ticks = ticks
        self.calls = 0
        self.drained = asyncio.Event()

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        self.calls += 1
        for item in self.ticks:
            yield item
        self.drained.set()
        await asyncio.Event().wait()


class FlakyVenue:
    """Fails the first connection, then streams one tick and stays open."""

    def __init__(self, item: MarketTick) -> None:
        self.item = item
        self.calls = 0

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("handshake failed")
        yield self.item
        await asyncio.Event().wait()


class SilentVenue:
    """Connects but never produces a tick."""

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        await asyncio.Event().wait()
        yield tick("BTC/USD", 1.0)  # pragma: no cover - unreachable


async def test_latest_serves_newest_tick_per_symbol_over_single_subscription() -> None:
    venue = StreamingVenue(
        (tick("BTC/USD", 100.0), tick("ETH/USD", 50.0), tick("BTC/USD", 101.0))
    )
    feed = PersistentTickerFeed(venue=venue, symbols=("BTC/USD", "ETH/USD"))
    try:
        eth = await feed.latest("ETH/USD")
        await asyncio.wait_for(venue.drained.wait(), timeout=1)
        btc = await feed.latest("BTC/USD")
        btc_again = await feed.latest("BTC/USD")
    finally:
        await feed.aclose()
    assert eth.last == 50.0
    assert btc.last == 101.0
    assert btc_again.last == 101.0
    # One shared subscription serves every latest() call.
    assert venue.calls == 1


async def test_feed_reconnects_after_stream_failure() -> None:
    venue = FlakyVenue(tick("BTC/USD", 100.0))
    feed = PersistentTickerFeed(
        venue=venue,
        symbols=("BTC/USD",),
        reconnect_backoff_seconds=0.01,
    )
    try:
        result = await feed.latest("BTC/USD")
    finally:
        await feed.aclose()
    assert result.last == 100.0
    assert venue.calls == 2


async def test_latest_raises_when_no_tick_arrives_in_time() -> None:
    feed = PersistentTickerFeed(
        venue=SilentVenue(),
        symbols=("BTC/USD",),
        max_tick_wait_seconds=0.05,
    )
    try:
        with pytest.raises(RuntimeError, match="no tick for BTC/USD"):
            await feed.latest("BTC/USD")
    finally:
        await feed.aclose()


async def test_aclose_cancels_consumer_task() -> None:
    feed = PersistentTickerFeed(
        venue=SilentVenue(),
        symbols=("BTC/USD",),
        max_tick_wait_seconds=0.05,
    )
    with pytest.raises(RuntimeError, match="no tick"):
        await feed.latest("BTC/USD")
    task = feed._task
    assert task is not None
    assert not task.done()

    await feed.aclose()

    assert task.cancelled()
    with pytest.raises(RuntimeError, match="closed"):
        await feed.latest("BTC/USD")
