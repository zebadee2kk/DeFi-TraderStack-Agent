from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.candles import Candle
from traderstack.market.candle_feed import CandleFeed, interval_to_seconds


def make_candles(count: int, *, include_forming: bool = False) -> tuple[Candle, ...]:
    now = datetime.now(UTC)
    first_open = now - timedelta(hours=count)
    candles = []
    for index in range(count):
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=first_open + timedelta(hours=index),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
            )
        )
    if include_forming:
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=now - timedelta(minutes=10),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
            )
        )
    return tuple(candles)


@dataclass
class StubFetcher:
    candles: tuple[Candle, ...]
    fail: bool = False
    calls: int = field(default=0)

    async def fetch(
        self,
        symbol: str,
        resolution: str = "1h",
        *,
        count: int = 250,
    ) -> tuple[Candle, ...]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return self.candles


def test_interval_to_seconds() -> None:
    assert interval_to_seconds("1m") == 60
    assert interval_to_seconds("4h") == 14_400
    assert interval_to_seconds("1d") == 86_400
    with pytest.raises(ValueError):
        interval_to_seconds("fast")
    with pytest.raises(ValueError):
        interval_to_seconds("0h")


async def test_feed_caches_within_ttl() -> None:
    fetcher = StubFetcher(make_candles(10))
    feed = CandleFeed(fetcher=fetcher, refresh_seconds=300)
    first = await feed.get("BTC/USD")
    second = await feed.get("BTC/USD")
    assert fetcher.calls == 1
    assert first == second


async def test_feed_drops_forming_candle() -> None:
    fetcher = StubFetcher(make_candles(10, include_forming=True))
    feed = CandleFeed(fetcher=fetcher)
    candles = await feed.get("BTC/USD")
    assert len(candles) == 10
    span = timedelta(seconds=interval_to_seconds("1h"))
    assert candles[-1].opened_at + span <= datetime.now(UTC)


async def test_feed_serves_cache_on_fetch_failure() -> None:
    fetcher = StubFetcher(make_candles(10))
    feed = CandleFeed(fetcher=fetcher, refresh_seconds=0.0)
    first = await feed.get("BTC/USD")
    fetcher.fail = True
    fallback = await feed.get("BTC/USD")
    assert fallback == first
    assert fetcher.calls == 2


async def test_feed_raises_without_usable_cache() -> None:
    fetcher = StubFetcher(make_candles(10), fail=True)
    feed = CandleFeed(fetcher=fetcher)
    with pytest.raises(RuntimeError):
        await feed.get("BTC/USD")
