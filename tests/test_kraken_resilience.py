import asyncio
import json
from typing import Any, Self

import pytest

from traderstack.market.adapters import (
    KrakenBookProvider,
    KrakenFeedExhausted,
    KrakenTickerProvider,
    parse_kraken_book_message,
)
from traderstack.market.models import MarketSource


def ticker_message(
    symbol: str = "BTC/USD", *, bid: float = 999.0, ask: float = 1001.0, last: float = 1000.0
) -> str:
    return json.dumps(
        {
            "channel": "ticker",
            "type": "update",
            "data": [{"symbol": symbol, "bid": bid, "ask": ask, "last": last}],
        }
    )


class FakeTickerSocket:
    """Mimics a `websockets` connection: sends recorded messages, then acts
    as though the peer disconnected once exhausted.
    """

    def __init__(self, messages: list[str]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = list(messages)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self._messages:
            raise ConnectionResetError("peer closed the connection")
        return self._messages.pop(0)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class HangingSocket:
    """Never responds - used to exercise stale-connection detection."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        await asyncio.sleep(10)
        raise AssertionError("unreachable: recv should have timed out first")

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _connect_sequence(items: list[Any]) -> Any:
    """Returns a connect factory that hands out `items` in order across
    successive calls (an `Exception` instance is raised instead of returned).
    """
    calls = {"n": 0}

    def connect(url: str, **kwargs: object) -> Any:
        item = items[calls["n"]]
        calls["n"] += 1
        if isinstance(item, BaseException):
            raise item
        return item

    connect.calls = calls  # type: ignore[attr-defined]
    return connect


def _instant_sleep(_: float) -> Any:
    return asyncio.sleep(0)


# --- ticker: reconnect ----------------------------------------------------------


@pytest.mark.asyncio
async def test_ticker_reconnects_after_first_connection_failure_and_keeps_streaming() -> None:
    connect = _connect_sequence(
        [
            OSError("connection refused"),
            FakeTickerSocket([ticker_message(last=1000.0), ticker_message(last=1001.0)]),
        ]
    )
    provider = KrakenTickerProvider(
        connect=connect, sleep=_instant_sleep, random_jitter=lambda: 0.0
    )

    ticks = []
    async for tick in provider.stream_ticks(("BTC/USD",)):
        ticks.append(tick)
        if len(ticks) == 2:
            break

    assert [t.last for t in ticks] == [1000.0, 1001.0]
    assert connect.calls["n"] == 2  # first attempt failed, second succeeded


@pytest.mark.asyncio
async def test_ticker_reconnects_across_a_clean_disconnect() -> None:
    first_socket = FakeTickerSocket([ticker_message(last=100.0)])
    second_socket = FakeTickerSocket([ticker_message(last=200.0)])
    connect = _connect_sequence([first_socket, second_socket])
    provider = KrakenTickerProvider(
        connect=connect, sleep=_instant_sleep, random_jitter=lambda: 0.0
    )

    ticks = []
    async for tick in provider.stream_ticks(("BTC/USD",)):
        ticks.append(tick)
        if len(ticks) == 2:
            break

    # The first socket's message list is exhausted after one tick, so recv()
    # raises and the provider must reconnect to keep streaming from the second.
    assert [t.last for t in ticks] == [100.0, 200.0]


@pytest.mark.asyncio
async def test_ticker_gives_up_after_max_reconnect_attempts() -> None:
    connect = _connect_sequence([OSError("down")] * 10)
    provider = KrakenTickerProvider(
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        max_reconnect_attempts=3,
    )

    with pytest.raises(KrakenFeedExhausted):
        async for _tick in provider.stream_ticks(("BTC/USD",)):
            pass

    assert connect.calls["n"] == 4  # the initial attempt plus 3 reconnects


@pytest.mark.asyncio
async def test_ticker_reconnects_on_stale_connection() -> None:
    connect = _connect_sequence([HangingSocket(), FakeTickerSocket([ticker_message(last=42.0)])])
    provider = KrakenTickerProvider(
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        stale_after_seconds=0.02,
    )

    ticks = []
    async for tick in provider.stream_ticks(("BTC/USD",)):
        ticks.append(tick)
        break

    assert ticks[0].last == 42.0
    assert connect.calls["n"] == 2


# --- book: pure parsing -----------------------------------------------------------


def test_parse_kraken_book_message_builds_sorted_top_of_book() -> None:
    books: dict[str, Any] = {}
    snapshot_message = {
        "channel": "book",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "bids": [{"price": 100.0, "qty": 1.0}, {"price": 99.5, "qty": 2.0}],
                "asks": [{"price": 100.5, "qty": 1.5}, {"price": 101.0, "qty": 3.0}],
                "checksum": 123,
                "timestamp": "2026-09-04T00:00:00.000000Z",
            }
        ],
    }
    snapshot = parse_kraken_book_message(snapshot_message, books, depth=10)
    assert snapshot is not None
    assert snapshot.symbol == "BTC/USD"
    assert [level.price for level in snapshot.bids] == [100.0, 99.5]
    assert [level.price for level in snapshot.asks] == [100.5, 101.0]
    assert snapshot.best_bid == 100.0
    assert snapshot.best_ask == 100.5
    assert snapshot.source is MarketSource.KRAKEN

    update_message = {
        "channel": "book",
        "type": "update",
        "data": [
            {
                "symbol": "BTC/USD",
                "bids": [{"price": 100.0, "qty": 0.0}, {"price": 100.25, "qty": 0.75}],
                "asks": [],
                "checksum": 456,
                "timestamp": "2026-09-04T00:00:01.000000Z",
            }
        ],
    }
    updated = parse_kraken_book_message(update_message, books, depth=10)
    assert updated is not None
    # 100.0 was removed (qty 0), 100.25 was added; the untouched 99.5 remains.
    assert [level.price for level in updated.bids] == [100.25, 99.5]
    assert [level.price for level in updated.asks] == [100.5, 101.0]


def test_parse_kraken_book_message_ignores_non_book_messages() -> None:
    assert (
        parse_kraken_book_message({"channel": "ticker", "type": "update", "data": []}, {}) is None
    )
    assert parse_kraken_book_message({"channel": "book", "type": "heartbeat"}, {}) is None


def test_book_snapshot_depth_within_bps() -> None:
    books: dict[str, Any] = {}
    message = {
        "channel": "book",
        "type": "snapshot",
        "data": [
            {
                "symbol": "BTC/USD",
                "bids": [{"price": 100.0, "qty": 1.0}, {"price": 90.0, "qty": 5.0}],
                "asks": [{"price": 101.0, "qty": 2.0}, {"price": 120.0, "qty": 5.0}],
                "timestamp": "2026-09-04T00:00:00Z",
            }
        ],
    }
    snapshot = parse_kraken_book_message(message, books, depth=10)
    assert snapshot is not None
    # mid = (100 + 101) / 2 = 100.5; 200bps band = [98.49, 102.51] -> only the
    # near levels (100.0 bid, 101.0 ask) are within it.
    bid_depth, ask_depth = snapshot.depth_within_bps(200)
    assert bid_depth == pytest.approx(100.0 * 1.0)
    assert ask_depth == pytest.approx(101.0 * 2.0)


# --- book: streaming with reconnect ----------------------------------------------


@pytest.mark.asyncio
async def test_book_provider_streams_snapshot_then_update_across_reconnect() -> None:
    snapshot_message = json.dumps(
        {
            "channel": "book",
            "type": "snapshot",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "bids": [{"price": 100.0, "qty": 1.0}],
                    "asks": [{"price": 101.0, "qty": 1.0}],
                    "timestamp": "2026-09-04T00:00:00Z",
                }
            ],
        }
    )
    first_socket = FakeTickerSocket([snapshot_message])
    reconnect_snapshot = json.dumps(
        {
            "channel": "book",
            "type": "snapshot",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "bids": [{"price": 102.0, "qty": 1.0}],
                    "asks": [{"price": 103.0, "qty": 1.0}],
                    "timestamp": "2026-09-04T00:00:05Z",
                }
            ],
        }
    )
    second_socket = FakeTickerSocket([reconnect_snapshot])
    connect = _connect_sequence([first_socket, second_socket])
    provider = KrakenBookProvider(connect=connect, sleep=_instant_sleep, random_jitter=lambda: 0.0)

    snapshots = []
    async for snapshot in provider.stream_books(("BTC/USD",)):
        snapshots.append(snapshot)
        if len(snapshots) == 2:
            break

    assert snapshots[0].best_bid == 100.0
    assert snapshots[1].best_bid == 102.0
