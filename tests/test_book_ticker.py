"""Second-venue bookTicker adapter — recorded fixtures, no network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Self

import pytest

from traderstack.market.book_ticker import (
    BookTickerProvider,
    binance_combined_url,
    cross_venue_divergence_bps,
    parse_binance_book_ticker,
    parse_bybit_ticker,
)
from traderstack.market.models import MarketSource
from traderstack.market.streaming import FeedExhausted

BINANCE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edge" / "binance_book_ticker.json"
BYBIT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edge" / "bybit_ticker.json"


def _binance() -> dict[str, Any]:
    return json.loads(BINANCE_FIXTURES.read_text(encoding="utf-8"))


def _bybit() -> dict[str, Any]:
    return json.loads(BYBIT_FIXTURES.read_text(encoding="utf-8"))


def test_parse_binance_raw_and_combined_book_ticker() -> None:
    raw = parse_binance_book_ticker(_binance()["raw"], assets=("BTC", "ETH"))
    assert raw is not None
    assert raw.source is MarketSource.BINANCE
    assert raw.asset == "BTC"
    assert raw.bid == pytest.approx(25000.10)
    assert raw.ask == pytest.approx(25000.50)
    assert raw.mid == pytest.approx((25000.10 + 25000.50) / 2)

    combined = parse_binance_book_ticker(_binance()["combined"], assets=("ETH",))
    assert combined is not None
    assert combined.asset == "ETH"


def test_parse_binance_drops_malformed_and_other_assets() -> None:
    assert parse_binance_book_ticker(_binance()["malformed"], assets=("BTC",)) is None
    assert parse_binance_book_ticker(_binance()["raw"], assets=("ETH",)) is None


def test_parse_bybit_ticker_uses_bid1_ask1() -> None:
    ticker = parse_bybit_ticker(_bybit()["snapshot"], assets=("BTC",))
    assert ticker is not None
    assert ticker.source is MarketSource.BYBIT
    assert ticker.asset == "BTC"
    assert ticker.bid == pytest.approx(17215.50)
    assert ticker.ask == pytest.approx(17216.00)


def test_parse_bybit_requires_both_sides() -> None:
    assert parse_bybit_ticker(_bybit()["delta_missing_bid"], assets=("ETH",)) is None


def test_cross_venue_divergence_bps() -> None:
    assert cross_venue_divergence_bps(100.0, 100.5) == pytest.approx(50.0)
    assert cross_venue_divergence_bps(0.0, 100.0) == 0.0


def test_binance_combined_url_lists_allowlisted_assets() -> None:
    url = binance_combined_url(("BTC", "ETH"))
    assert "btcusdt@bookTicker" in url
    assert "ethusdt@bookTicker" in url
    assert url.startswith("wss://fstream.binance.com/stream?streams=")


class FakeSocket:
    def __init__(self, messages: list[str]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = list(messages)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self._messages:
            raise ConnectionResetError("peer closed")
        return self._messages.pop(0)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _connect_sequence(items: list[Any]) -> Any:
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


@pytest.mark.asyncio
async def test_binance_book_ticker_reconnects_from_fixtures() -> None:
    first = FakeSocket([json.dumps(_binance()["raw"])])
    second = FakeSocket([json.dumps(_binance()["combined"])])
    connect = _connect_sequence([OSError("refused"), first, second])
    provider = BookTickerProvider(
        venue="binance",
        assets=("BTC", "ETH"),
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        max_age_seconds=10_000,
    )

    ticks = []
    async for ticker in provider.stream_tickers():
        ticks.append(ticker)
        if len(ticks) == 2:
            break

    assert [t.asset for t in ticks] == ["BTC", "ETH"]
    assert connect.calls["n"] == 3


@pytest.mark.asyncio
async def test_bybit_book_ticker_subscribes_and_caches_latest() -> None:
    socket = FakeSocket([json.dumps(_bybit()["snapshot"])])
    connect = _connect_sequence([socket])
    provider = BookTickerProvider(
        venue="bybit",
        assets=("BTC",),
        connect=connect,
        sleep=_instant_sleep,
        random_jitter=lambda: 0.0,
        max_reconnect_attempts=0,
        max_age_seconds=10_000,
    )

    with pytest.raises(FeedExhausted):
        await provider.collect()

    assert socket.sent[0]["op"] == "subscribe"
    assert socket.sent[0]["args"] == ["tickers.BTCUSDT"]
    latest = provider.latest("BTC")
    assert latest is not None
    assert latest.source is MarketSource.BYBIT
    assert latest.mid == pytest.approx((17215.50 + 17216.00) / 2)
