import asyncio
import json
import random
from collections.abc import AsyncIterator, Callable
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
from traderstack.market.streaming import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    DEFAULT_STALE_AFTER_SECONDS,
    ConnectFactory,
    FeedError,
    FeedExhausted,
    SleepFn,
    compute_backoff,
    recv_or_stale,
    stream_with_reconnect,
)

COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}

# CoinGecko Demo / public free tiers return HTTP 429 under even modest
# multi-asset polling. One bounded retry that honours Retry-After (capped)
# is good-client behaviour for every trading mode; it does not loosen
# fail-closed. Paper last-good reuse lives in ProviderRegistry, not here.
DEFAULT_COINGECKO_RETRY_429_ATTEMPTS = 1
DEFAULT_COINGECKO_MAX_RETRY_AFTER_SECONDS = 2.0


def retry_after_seconds(response: httpx.Response, cap_seconds: float) -> float:
    """Parse Retry-After as a delay in seconds, capped. Non-numeric values
    (HTTP-date) fall back to 1s rather than blocking a cycle on a long wait.
    """
    cap = max(0.0, cap_seconds)
    raw = response.headers.get("Retry-After")
    if raw is None:
        return min(1.0, cap)
    try:
        return min(max(0.0, float(raw)), cap)
    except ValueError:
        return min(1.0, cap)


# --- providers (Epic 2): Kraken WS resilience ----------------------------------
#
# A public Kraken WS v2 connection can drop at any time (idle proxy timeouts,
# Kraken-side restarts, network blips). `stream_ticks`/`stream_books` used to
# open one connection and let any error kill the generator, silently ending
# the venue feed. They now reconnect with capped exponential backoff and full
# jitter, detect a stalled connection (no message within `stale_after_seconds`)
# and reconnect it too, and give up only after `max_reconnect_attempts`.
# The reconnect loop is shared with the paper-research edge feeds
# (`traderstack.market.streaming`).

# Backwards-compatible names: existing tests and docs refer to these.
KrakenFeedError = FeedError
KrakenFeedExhausted = FeedExhausted
_compute_backoff = compute_backoff
_stream_with_reconnect = stream_with_reconnect


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
                raw = await recv_or_stale(
                    ws,
                    stale_after_seconds=self.stale_after_seconds,
                    feed_name="kraken ticker",
                )
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
                raw = await recv_or_stale(
                    ws,
                    stale_after_seconds=self.stale_after_seconds,
                    feed_name="kraken book",
                )
                message = json.loads(raw)
                snapshot = parse_kraken_book_message(message, self._books, depth=self.depth)
                if snapshot is not None and snapshot.symbol in symbols:
                    yield snapshot


class CoinGeckoPriceProvider:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.coingecko.com/api/v3",
        client: httpx.AsyncClient | None = None,
        retry_429_attempts: int = DEFAULT_COINGECKO_RETRY_429_ATTEMPTS,
        max_retry_after_seconds: float = DEFAULT_COINGECKO_MAX_RETRY_AFTER_SECONDS,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.retry_429_attempts = max(0, retry_429_attempts)
        self.max_retry_after_seconds = max(0.0, max_retry_after_seconds)
        self.sleep = sleep

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        ids = [COINGECKO_IDS[a] for a in assets if a in COINGECKO_IDS]
        if not ids:
            return []
        headers = {"x-cg-demo-api-key": self.api_key} if self.api_key else {}
        payload = await self._fetch_payload(ids, headers)
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

    async def _fetch_payload(self, ids: list[str], headers: dict[str, str]) -> dict[str, Any]:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=10)
        try:
            for attempt in range(self.retry_429_attempts + 1):
                response = await client.get(
                    f"{self.base_url}/simple/price",
                    params={"ids": ",".join(ids), "vs_currencies": "usd"},
                    headers=headers,
                )
                if response.status_code == 429 and attempt < self.retry_429_attempts:
                    await self.sleep(retry_after_seconds(response, self.max_retry_after_seconds))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("unexpected CoinGecko payload")
                return payload
            raise RuntimeError("CoinGecko 429 retries exhausted")
        finally:
            if owns_client:
                await client.aclose()


def _cmc_usd_price(quote: object) -> float | None:
    """Extract a USD last price from CMC ``quote`` as a dict *or* a list.

    v1/v2 keyed ``quote`` as ``{"USD": {"price": ...}}``. v3 (and the public
    no-key path) returns ``quote`` as a list of ``{"symbol": "USD", "price": ...}``
    objects. Either shape is reduced to a finite float or ``None``.
    """
    if isinstance(quote, dict):
        usd = quote.get("USD") if "USD" in quote else quote.get("usd")
        if isinstance(usd, dict):
            price = usd.get("price")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                return float(price)
        # A single quote object (already USD) may carry ``price`` at the top.
        price = quote.get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            symbol = quote.get("symbol") or quote.get("name")
            if symbol is None or str(symbol).upper() == "USD":
                return float(price)
        return None
    if isinstance(quote, list):
        for item in quote:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol") or item.get("name")
            if symbol is not None and str(symbol).upper() != "USD":
                continue
            price = item.get("price")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                return float(price)
    return None


def _cmc_asset_rows(data: object) -> list[tuple[str, dict[str, Any]]]:
    """Flatten CMC ``data`` whether it is a symbol-keyed dict or a list.

    A dict value may itself be a list (multiple listings for one symbol);
    we take the first dict row that yields a USD price later.
    """
    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            if isinstance(symbol, str) and symbol.strip():
                rows.append((symbol.upper(), item))
        return rows
    if not isinstance(data, dict):
        return rows
    for key, value in data.items():
        listings: list[Any]
        if isinstance(value, list):
            listings = value
        elif isinstance(value, dict):
            listings = [value]
        else:
            continue
        for item in listings:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                symbol = str(key)
            rows.append((str(symbol).upper(), item))
    return rows


def parse_coinmarketcap_quotes(
    payload: object,
    *,
    observed_at: datetime | None = None,
) -> list[ReferencePrice]:
    """Parse a CMC quotes/latest body; skip unrecognised shapes instead of 500ing."""
    if not isinstance(payload, dict):
        return []
    now = observed_at or datetime.now(UTC)
    prices: list[ReferencePrice] = []
    seen: set[str] = set()
    for asset, row in _cmc_asset_rows(payload.get("data")):
        if asset in seen:
            continue
        quote = row.get("quote")
        if quote is None:
            quote = row.get("quotes")
        price = _cmc_usd_price(quote)
        if price is None or price <= 0:
            continue
        seen.add(asset)
        prices.append(
            ReferencePrice(
                source=MarketSource.COINMARKETCAP,
                asset=asset,
                observed_at=now,
                price=price,
            )
        )
    return prices


class CoinMarketCapPriceProvider:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://pro-api.coinmarketcap.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        path = (
            "/v3/cryptocurrency/quotes/latest"
            if self.api_key
            else "/public-api/v3/cryptocurrency/quotes/latest"
        )
        headers = {"X-CMC_PRO_API_KEY": self.api_key} if self.api_key else {}
        wanted = {asset.upper() for asset in assets}
        params = {"symbol": ",".join(assets), "convert": "USD"}
        if self.client is not None:
            response = await self.client.get(path, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}{path}", params=params, headers=headers
                )
        response.raise_for_status()
        return [
            price for price in parse_coinmarketcap_quotes(response.json()) if price.asset in wanted
        ]
