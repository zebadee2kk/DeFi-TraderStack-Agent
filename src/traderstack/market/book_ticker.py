"""Optional second-venue bookTicker for paper-research cross-venue mid features.

Binance USDT-M (``btcusdt@bookTicker`` on ``fstream.binance.com``) or Bybit
v5 linear public tickers (``tickers.BTCUSDT``). This is **not** an execution
venue: the mid is compared to the primary tick (typically Kraken USD) to
produce ``ResearchEdgeFeatures.cross_venue_mid_divergence_bps`` only.

Reconnect/backoff follow ``traderstack.market.streaming``, same as Kraken.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import websockets
from prometheus_client import Gauge

from traderstack.market.models import BookTicker, MarketSource
from traderstack.market.streaming import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    DEFAULT_STALE_AFTER_SECONDS,
    ConnectFactory,
    SleepFn,
    recv_or_stale,
    stream_with_reconnect,
)
from traderstack.market.symbols import asset_from_futures_symbol, futures_symbol

BINANCE_BOOK_TICKER_URL = "wss://fstream.binance.com/stream?streams={streams}"
BYBIT_LINEAR_URL = "wss://stream.bybit.com/v5/public/linear"

BookTickerVenue = Literal["binance", "bybit"]

cross_venue_mid_usd = Gauge(
    "traderstack_cross_venue_mid_usd",
    "Latest second-venue bookTicker mid (quote units), research only",
    ("asset", "venue"),
)
cross_venue_mid_divergence_bps = Gauge(
    "traderstack_cross_venue_mid_divergence_bps",
    "Primary vs second-venue mid divergence in bps, research only",
    ("asset", "venue"),
)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _ms_to_datetime(value: object, *, fallback: datetime) -> datetime:
    millis = _as_float(value)
    if millis is None:
        return fallback
    return datetime.fromtimestamp(millis / 1000.0, tz=UTC)


def parse_binance_book_ticker(
    message: object,
    *,
    assets: tuple[str, ...] | None = None,
    quote: str = "USDT",
    now: datetime | None = None,
) -> BookTicker | None:
    """Pure: reduce one recorded Binance bookTicker payload to a typed ticker."""
    if not isinstance(message, dict):
        return None
    row: dict[str, Any]
    if "s" in message and ("b" in message or "a" in message):
        row = message
    else:
        data = message.get("data")
        if not isinstance(data, dict):
            return None
        row = data
    symbol = row.get("s")
    if not isinstance(symbol, str):
        return None
    asset = asset_from_futures_symbol(symbol, quote)
    if asset is None:
        return None
    if assets is not None and asset not in {a.upper() for a in assets}:
        return None
    bid = _as_float(row.get("b"))
    ask = _as_float(row.get("a"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    observed = now or datetime.now(UTC)
    return BookTicker(
        source=MarketSource.BINANCE,
        symbol=symbol.upper(),
        asset=asset,
        observed_at=_ms_to_datetime(row.get("E") or row.get("T"), fallback=observed),
        bid=bid,
        ask=ask,
    )


def parse_bybit_ticker(
    message: object,
    *,
    assets: tuple[str, ...] | None = None,
    quote: str = "USDT",
    now: datetime | None = None,
) -> BookTicker | None:
    """Pure: reduce one recorded Bybit v5 ``tickers.*`` payload to a typed ticker."""
    if not isinstance(message, dict):
        return None
    topic = message.get("topic")
    if not isinstance(topic, str) or not topic.startswith("tickers."):
        return None
    data = message.get("data")
    if not isinstance(data, dict):
        return None
    symbol = data.get("symbol")
    if not isinstance(symbol, str):
        symbol = topic.split(".", 1)[1] if "." in topic else ""
    if not symbol:
        return None
    asset = asset_from_futures_symbol(symbol, quote)
    if asset is None:
        return None
    if assets is not None and asset not in {a.upper() for a in assets}:
        return None
    bid = _as_float(data.get("bid1Price"))
    ask = _as_float(data.get("ask1Price"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    observed = now or datetime.now(UTC)
    return BookTicker(
        source=MarketSource.BYBIT,
        symbol=symbol.upper(),
        asset=asset,
        observed_at=_ms_to_datetime(message.get("ts"), fallback=observed),
        bid=bid,
        ask=ask,
    )


def parse_book_ticker(
    message: object,
    *,
    venue: BookTickerVenue,
    assets: tuple[str, ...] | None = None,
    quote: str = "USDT",
    now: datetime | None = None,
) -> BookTicker | None:
    if venue == "bybit":
        return parse_bybit_ticker(message, assets=assets, quote=quote, now=now)
    return parse_binance_book_ticker(message, assets=assets, quote=quote, now=now)


def cross_venue_divergence_bps(primary_mid: float, secondary_mid: float) -> float:
    if primary_mid <= 0:
        return 0.0
    return abs(secondary_mid - primary_mid) / primary_mid * 10_000


def binance_combined_url(
    assets: tuple[str, ...],
    quote: str = "USDT",
    *,
    template: str = BINANCE_BOOK_TICKER_URL,
) -> str:
    streams = "/".join(f"{futures_symbol(asset, quote).lower()}@bookTicker" for asset in assets)
    return template.format(streams=streams)


@dataclass
class BookTickerProvider:
    """Streaming collector + latest-mid cache for one second venue."""

    venue: BookTickerVenue = "binance"
    url: str = ""
    assets: tuple[str, ...] = ()
    quote: str = "USDT"
    max_age_seconds: float = 5.0
    connect: ConnectFactory = field(default=websockets.connect)
    max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS
    sleep: SleepFn = field(default=asyncio.sleep)
    random_jitter: Callable[[], float] = field(default=random.random)
    feed_name: str = field(init=False, default="")
    _latest: dict[str, BookTicker] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.feed_name = f"{self.venue}_book_ticker"
        if not self.url:
            if self.venue == "bybit":
                self.url = BYBIT_LINEAR_URL
            else:
                self.url = binance_combined_url(self.assets, self.quote)

    async def stream_tickers(self) -> AsyncIterator[BookTicker]:
        async for ticker in stream_with_reconnect(
            self._stream_once,
            feed_name=self.feed_name,
            max_reconnect_attempts=self.max_reconnect_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_max_seconds=self.backoff_max_seconds,
            sleep=self.sleep,
            random_jitter=self.random_jitter,
        ):
            yield ticker

    async def _stream_once(self) -> AsyncIterator[BookTicker]:
        async with self.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            if self.venue == "bybit":
                args = [f"tickers.{futures_symbol(asset, self.quote)}" for asset in self.assets]
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
            while True:
                raw = await recv_or_stale(
                    ws,
                    stale_after_seconds=self.stale_after_seconds,
                    feed_name=self.feed_name,
                )
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ticker = parse_book_ticker(
                    payload, venue=self.venue, assets=self.assets, quote=self.quote
                )
                if ticker is not None:
                    yield ticker

    async def collect(self) -> None:
        async for ticker in self.stream_tickers():
            self._latest[ticker.asset] = ticker
            cross_venue_mid_usd.labels(asset=ticker.asset, venue=self.venue).set(ticker.mid)

    def latest(self, asset: str, *, now: datetime | None = None) -> BookTicker | None:
        ticker = self._latest.get(asset.upper())
        if ticker is None:
            return None
        moment = now or datetime.now(UTC)
        if self.max_age_seconds > 0:
            age = (moment - ticker.observed_at).total_seconds()
            if age > self.max_age_seconds:
                return None
        return ticker


def record_cross_venue_divergence(asset: str, venue: str, divergence_bps: float) -> None:
    cross_venue_mid_divergence_bps.labels(asset=asset, venue=venue).set(divergence_bps)
