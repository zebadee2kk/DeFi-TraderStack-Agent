import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import websockets

from traderstack.market.models import (
    BookLevel,
    BookSnapshot,
    MarketSource,
    MarketTick,
    ReferencePrice,
)

COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


# --- providers (Epic 2): Kraken WS resilience ----------------------------------
#
# A public Kraken WS v2 connection can drop at any time (idle proxy timeouts,
# Kraken-side restarts, network blips). `stream_ticks`/`stream_books` used to
# open one connection and let any error kill the generator, silently ending
# the venue feed. They now reconnect with capped exponential backoff and full
# jitter, detect a stalled connection (no message within `stale_after_seconds`)
# and reconnect it too, and give up only after `max_reconnect_attempts`.

DEFAULT_MAX_RECONNECT_ATTEMPTS = 10
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_MAX_SECONDS = 30.0
DEFAULT_STALE_AFTER_SECONDS = 30.0

ConnectFactory = Callable[..., Any]
SleepFn = Callable[[float], Awaitable[None]]


class KrakenFeedError(RuntimeError):
    """Raised when one connection attempt to a Kraken feed cannot be trusted
    (stalled, disconnected). Caught and retried by the reconnect loop.
    """


class KrakenFeedExhausted(KrakenFeedError):
    """Raised when reconnect attempts are exhausted; the stream truly ends."""


def _compute_backoff(attempt: int, base_seconds: float, max_seconds: float, jitter: float) -> float:
    """Capped exponential backoff with full jitter: `jitter` in [0, 1] scales
    the delay into [0.5x, 1x] of the nominal value so many reconnecting clients
    don't all retry in lockstep.
    """
    nominal = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
    return nominal * (0.5 + max(0.0, min(1.0, jitter)) * 0.5)


async def _stream_with_reconnect[T](
    open_once: Callable[[], AsyncIterator[T]],
    *,
    feed_name: str,
    max_reconnect_attempts: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
    sleep: SleepFn,
    random_jitter: Callable[[], float],
) -> AsyncIterator[T]:
    """Run `open_once()` (a fresh connection + subscribe + read loop each call)
    and reconnect with backoff on failure, yielding items continuously across
    reconnects. `open_once` should raise `KrakenFeedError` on a stale/dead
    connection; transport errors (`OSError`, timeouts, websockets exceptions)
    are caught here too.
    """
    attempt = 0
    while True:
        try:
            async for item in open_once():
                attempt = 0  # any successful message resets the backoff counter
                yield item
            # A generator that returns instead of raising is still a lost
            # connection (server closed cleanly) - treat it as one.
            raise KrakenFeedError(f"{feed_name} stream ended unexpectedly")
        except (KrakenFeedError, OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
            attempt += 1
            if attempt > max_reconnect_attempts:
                raise KrakenFeedExhausted(
                    f"{feed_name} failed after {attempt - 1} reconnect attempt(s)"
                ) from exc
            delay = _compute_backoff(attempt, backoff_base_seconds, backoff_max_seconds, random_jitter())
            await sleep(delay)


@dataclass
class KrakenTickerProvider:
    url: str = "wss://ws.kraken.com/v2"
    connect: ConnectFactory = field(default=websockets.connect)
    max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS
    sleep: SleepFn = field(default=asyncio.sleep)
    random_jitter: Callable[[], float] = field(default=random.random)

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        async for tick in _stream_with_reconnect(
            lambda: self._stream_once(symbols),
            feed_name="kraken ticker",
            max_reconnect_attempts=self.max_reconnect_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_max_seconds=self.backoff_max_seconds,
            sleep=self.sleep,
            random_jitter=self.random_jitter,
        ):
            yield tick

    async def _stream_once(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        async with self.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "params": {"channel": "ticker", "symbol": list(symbols), "snapshot": True},
                    }
                )
            )
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.stale_after_seconds)
                except TimeoutError as exc:
                    raise KrakenFeedError(
                        f"no ticker message within {self.stale_after_seconds}s"
                    ) from exc
                message = json.loads(raw)
                tick = parse_kraken_ticker(message)
                if tick is not None:
                    yield tick


def parse_kraken_ticker(message: dict[str, object]) -> MarketTick | None:
    if message.get("channel") != "ticker":
        return None
    data = message.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    row = data[0]
    symbol = row.get("symbol")
    bid = row.get("bid")
    ask = row.get("ask")
    last = row.get("last")
    if not isinstance(symbol, str):
        return None
    if not isinstance(bid, (int, float)):
        return None
    if not isinstance(ask, (int, float)):
        return None
    if not isinstance(last, (int, float)):
        return None
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        observed_at=datetime.now(UTC),
        bid=float(bid),
        ask=float(ask),
        last=float(last),
    )


# --- providers (Epic 2): order-book snapshot handling --------------------------
#
# Kraken WS v2's `book` channel sends one full `snapshot` on subscribe and then
# incremental `update` messages (changed levels only; qty 0 means "remove this
# price"). A `BookSnapshot` needs the merged, still-current top-N, so each
# symbol's book is kept locally and re-derived on every message. Verified
# against https://docs.kraken.com/api/docs/websocket-v2/book (message shapes
# and the depth values 10/25/100/500/1000) on 2026-09-04.


@dataclass
class _LocalOrderBook:
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)

    def apply(self, message_type: str, bid_levels: list[Any], ask_levels: list[Any]) -> None:
        if message_type == "snapshot":
            self.bids = {}
            self.asks = {}
        _merge_levels(self.bids, bid_levels)
        _merge_levels(self.asks, ask_levels)

    def top(self, depth: int) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        best_bids = sorted(self.bids.items(), key=lambda kv: kv[0], reverse=True)[:depth]
        best_asks = sorted(self.asks.items(), key=lambda kv: kv[0])[:depth]
        return (
            tuple(BookLevel(price=price, qty=qty) for price, qty in best_bids),
            tuple(BookLevel(price=price, qty=qty) for price, qty in best_asks),
        )


def _merge_levels(side: dict[float, float], levels: list[Any]) -> None:
    for level in levels:
        if not isinstance(level, dict):
            continue
        price, qty = level.get("price"), level.get("qty")
        if not isinstance(price, (int, float)) or not isinstance(qty, (int, float)):
            continue
        if qty <= 0:
            side.pop(float(price), None)
        else:
            side[float(price)] = float(qty)


def _parse_kraken_timestamp(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


def parse_kraken_book_message(
    message: dict[str, object],
    books: dict[str, _LocalOrderBook],
    *,
    depth: int = 10,
) -> BookSnapshot | None:
    """Pure: merge one `book` channel message into `books` (mutated in place,
    keyed by symbol) and return the resulting top-`depth` snapshot, or None if
    `message` isn't a book snapshot/update.
    """
    if message.get("channel") != "book":
        return None
    message_type = message.get("type")
    if message_type not in ("snapshot", "update"):
        return None
    data = message.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    row = data[0]
    symbol = row.get("symbol")
    bids, asks = row.get("bids"), row.get("asks")
    if not isinstance(symbol, str) or not isinstance(bids, list) or not isinstance(asks, list):
        return None

    book = books.setdefault(symbol, _LocalOrderBook())
    book.apply(str(message_type), bids, asks)
    top_bids, top_asks = book.top(depth)
    return BookSnapshot(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        observed_at=_parse_kraken_timestamp(row.get("timestamp")),
        bids=top_bids,
        asks=top_asks,
    )


@dataclass
class KrakenBookProvider:
    url: str = "wss://ws.kraken.com/v2"
    depth: int = 10
    connect: ConnectFactory = field(default=websockets.connect)
    max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS
    sleep: SleepFn = field(default=asyncio.sleep)
    random_jitter: Callable[[], float] = field(default=random.random)
    _books: dict[str, _LocalOrderBook] = field(init=False, default_factory=dict)

    async def stream_books(self, symbols: tuple[str, ...]) -> AsyncIterator[BookSnapshot]:
        async for snapshot in _stream_with_reconnect(
            lambda: self._stream_once(symbols),
            feed_name="kraken book",
            max_reconnect_attempts=self.max_reconnect_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_max_seconds=self.backoff_max_seconds,
            sleep=self.sleep,
            random_jitter=self.random_jitter,
        ):
            yield snapshot

    async def _stream_once(self, symbols: tuple[str, ...]) -> AsyncIterator[BookSnapshot]:
        async with self.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "params": {"channel": "book", "symbol": list(symbols), "depth": self.depth},
                    }
                )
            )
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.stale_after_seconds)
                except TimeoutError as exc:
                    raise KrakenFeedError(
                        f"no book message within {self.stale_after_seconds}s"
                    ) from exc
                message = json.loads(raw)
                snapshot = parse_kraken_book_message(message, self._books, depth=self.depth)
                if snapshot is not None and snapshot.symbol in symbols:
                    yield snapshot


class CoinGeckoPriceProvider:
    def __init__(
        self, api_key: str | None = None, base_url: str = "https://api.coingecko.com/api/v3"
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        ids = [COINGECKO_IDS[a] for a in assets if a in COINGECKO_IDS]
        if not ids:
            return []
        headers = {"x-cg-demo-api-key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/simple/price",
                params={"ids": ",".join(ids), "vs_currencies": "usd"},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        now = datetime.now(UTC)
        reverse = {v: k for k, v in COINGECKO_IDS.items()}
        prices: list[ReferencePrice] = []
        for coin_id, row in payload.items():
            if (
                coin_id in reverse
                and isinstance(row, dict)
                and isinstance(row.get("usd"), (int, float))
            ):
                prices.append(
                    ReferencePrice(
                        source=MarketSource.COINGECKO,
                        asset=reverse[coin_id],
                        observed_at=now,
                        price=float(row["usd"]),
                    )
                )
        return prices


class CoinMarketCapPriceProvider:
    def __init__(
        self, api_key: str | None = None, base_url: str = "https://pro-api.coinmarketcap.com"
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        path = (
            "/v3/cryptocurrency/quotes/latest"
            if self.api_key
            else "/public-api/v3/cryptocurrency/quotes/latest"
        )
        headers = {"X-CMC_PRO_API_KEY": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                params={"symbol": ",".join(assets), "convert": "USD"},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", {})
        now = datetime.now(UTC)
        prices: list[ReferencePrice] = []
        if isinstance(data, dict):
            for asset, row in data.items():
                if not isinstance(row, dict):
                    continue
                quote = row.get("quote")
                usd = quote.get("USD") if isinstance(quote, dict) else None
                price = usd.get("price") if isinstance(usd, dict) else None
                if isinstance(price, (int, float)):
                    prices.append(
                        ReferencePrice(
                            source=MarketSource.COINMARKETCAP,
                            asset=str(asset).upper(),
                            observed_at=now,
                            price=float(price),
                        )
                    )
        return prices
