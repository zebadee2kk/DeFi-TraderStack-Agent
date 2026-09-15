"""Coinbase Exchange public candles: multi-year daily / 1h history (#133).

Endpoint (public, unauthenticated)::

    GET https://api.exchange.coinbase.com/products/{product_id}/candles
        ?granularity={seconds}&start={ISO8601}&end={ISO8601}

Response is a JSON array of arrays in **descending** time order, and the field
order is *not* OHLC — it is::

    [ time, low, high, open, close, volume ]

``time`` is the bucket start in unix **seconds**, UTC.

Shape and limits, as documented by Coinbase:

* ``granularity`` accepts only ``{60, 300, 900, 3600, 21600, 86400}`` seconds.
  There is **no 14400 (4h) bucket** — a 4h series is rolled up from complete
  1h buckets here (see ``COINBASE_DERIVED_INTERVALS``); a 4h bucket missing any
  of its four hourly bars is dropped, never completed with an invented bar.
* At most **300 candles per request**. This module paginates by walking
  ``start``/``end`` forward in 300-bucket windows.
* Public rate limit: **10 requests per second per IP, with bursts up to 15**
  (``COINBASE_PUBLIC_RATE_LIMIT_PER_SECOND``). The default pace used here is
  deliberately well inside that (``COINBASE_DEFAULT_REQUESTS_PER_SECOND``),
  and it is an explicit, caller-visible parameter rather than an implicit
  sleep.
* **HTTP 429 is a skip, not a retry storm.** A rate-limited response ends the
  walk immediately and the series is reported ``status="skipped"`` with the
  reason; this module never backs off and hammers the endpoint again.

Verification note (honest): the target hosts for this issue were **not
reachable from the session that wrote this module** — the agent egress proxy
answered ``403`` to ``CONNECT api.exchange.coinbase.com:443`` (organisation
policy), as it did for ``data.binance.vision`` and even ``api.kraken.com``.
The parser therefore follows Coinbase's documented response shape and the
row samples recorded in issue #133; it has not been run against a live
response from here. The committed tests are entirely offline
(``httpx.MockTransport``), as required. Re-verify the live shape from an
environment with egress before trusting a first real pull.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import httpx

from traderstack.candles import Candle
from traderstack.research.candle_archives import (
    ArchiveParseError,
    CandleSeriesFetch,
    aggregate,
    drop_uncommitted,
    finish_series,
    interval_step,
    require_aligned,
    skipped_series,
)

COINBASE_EXCHANGE_BASE_URL = "https://api.exchange.coinbase.com"
COINBASE_CANDLES_PATH = "/products/{product_id}/candles"
COINBASE_VENUE = "coinbase_exchange"

#: Documented cap: the endpoint returns at most 300 candles per request.
COINBASE_MAX_CANDLES_PER_REQUEST = 300
#: Documented public limit: 10 requests/second/IP, bursting to 15.
COINBASE_PUBLIC_RATE_LIMIT_PER_SECOND = 10.0
#: What this module actually paces itself at — well inside the public limit.
COINBASE_DEFAULT_REQUESTS_PER_SECOND = 3.0
#: Safety stop so a misbehaving cursor cannot loop forever.
COINBASE_DEFAULT_MAX_REQUESTS = 400

#: Granularities Coinbase publishes natively, in seconds.
COINBASE_GRANULARITY_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3_600,
    "6h": 21_600,
    "1d": 86_400,
}
#: Intervals this module serves by rolling up a native granularity.
COINBASE_DERIVED_INTERVALS: dict[str, str] = {"4h": "1h"}

SUPPORTED_INTERVALS: tuple[str, ...] = (
    "1m",
    "5m",
    "15m",
    "1h",
    "4h",
    "6h",
    "1d",
)

# Coinbase BTC-USD daily history starts in 2015; ETH-USD in 2016. Requests for
# earlier windows simply come back empty (a skip), never zero-filled.
COINBASE_EARLIEST_DAILY = datetime(2015, 1, 1, tzinfo=UTC)


class CoinbaseRateLimited(RuntimeError):
    """HTTP 429 from the public candles endpoint. Always a skip."""


def coinbase_product_id(symbol: str) -> str:
    """``BTC/USD`` → ``BTC-USD``. Rejects anything that is not BASE/QUOTE."""
    base, _, quote = symbol.upper().partition("/")
    if not base or not quote or "/" in quote:
        raise ValueError(f"symbol must be formatted BASE/QUOTE, got {symbol!r}")
    return f"{base}-{quote}"


def parse_coinbase_candle(row: object, *, symbol: str, interval: str) -> Candle:
    """Reduce one ``[time, low, high, open, close, volume]`` row to a Candle.

    Everything the venue sent is untrusted: the row must be a 6-field array of
    numbers, the timestamp must land exactly on the UTC interval grid, and the
    prices must be positive. ``Candle`` then enforces high/low containment.
    """
    if not isinstance(row, list | tuple) or len(row) < 6:
        raise ArchiveParseError("Coinbase candle row must be an array of at least 6 fields")
    try:
        opened_seconds = int(row[0])
        low = float(row[1])
        high = float(row[2])
        open_price = float(row[3])
        close = float(row[4])
        volume = float(row[5])
    except (TypeError, ValueError) as exc:
        raise ArchiveParseError(f"Coinbase candle row is not numeric: {exc}") from exc
    if min(low, high, open_price, close) <= 0:
        raise ArchiveParseError("Coinbase candle prices must be positive")
    if volume < 0:
        raise ArchiveParseError("Coinbase candle volume must not be negative")
    opened_at = require_aligned(datetime.fromtimestamp(opened_seconds, tz=UTC), interval)
    return Candle(
        symbol=symbol.upper(),
        interval=interval,
        opened_at=opened_at,
        open=open_price,
        # The venue's own low/high must contain open and close; clamp rather
        # than reject so one sloppy row does not discard a whole window, but
        # never move a price we were given.
        high=max(high, open_price, close),
        low=min(low, open_price, close),
        close=close,
        volume=volume,
    )


def parse_coinbase_candles(payload: object, *, symbol: str, interval: str) -> list[Candle]:
    """Parse a full candles response body (descending order in, list out)."""
    if isinstance(payload, dict):
        message = payload.get("message") or str(payload)
        raise ArchiveParseError(f"Coinbase candles error: {message}")
    if not isinstance(payload, list):
        raise ArchiveParseError("Coinbase candles payload must be an array")
    return [parse_coinbase_candle(row, symbol=symbol, interval=interval) for row in payload]


class _Pacer:
    """Explicit request pacing. ``requests_per_second <= 0`` disables it."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_gap = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last = 0.0

    async def wait(self) -> None:
        if self._min_gap <= 0:
            return
        now = time.monotonic()
        remaining = self._last + self._min_gap - now
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._last = time.monotonic()


async def fetch_coinbase_page(
    client: httpx.AsyncClient,
    *,
    product_id: str,
    granularity_seconds: int,
    start: datetime,
    end: datetime,
) -> object:
    """One request. Raises :class:`CoinbaseRateLimited` on HTTP 429."""
    response = await client.get(
        COINBASE_CANDLES_PATH.format(product_id=product_id),
        params={
            "granularity": granularity_seconds,
            "start": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "end": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        },
    )
    if response.status_code == 429:
        raise CoinbaseRateLimited("HTTP 429 Too Many Requests from Coinbase public candles")
    response.raise_for_status()
    return response.json()


async def fetch_coinbase_candles(
    symbol: str,
    interval: str,
    *,
    start: datetime,
    end: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    base_url: str = COINBASE_EXCHANGE_BASE_URL,
    requests_per_second: float = COINBASE_DEFAULT_REQUESTS_PER_SECOND,
    max_requests: int = COINBASE_DEFAULT_MAX_REQUESTS,
    now: datetime | None = None,
) -> CandleSeriesFetch:
    """Page Coinbase Exchange candles from ``start`` to ``end`` (default: now).

    Walks forward in windows of at most 300 buckets. Returns a
    :class:`CandleSeriesFetch`: ``status="ok"`` with candles, gaps and the
    report header, or ``status="skipped"`` with the reason (bad interval,
    HTTP 429, transport error, empty window). Never partially succeeds into an
    ``ok`` that hides a transport failure.
    """
    name = f"coinbase_candles:{symbol}@{interval}"
    fetched_at = datetime.now(UTC)

    if interval not in SUPPORTED_INTERVALS:
        return skipped_series(
            name=name,
            venue=COINBASE_VENUE,
            symbol=symbol,
            interval=interval,
            reason=(
                f"unsupported interval {interval!r}; "
                f"Coinbase serves {sorted(COINBASE_GRANULARITY_SECONDS)} "
                f"(plus {sorted(COINBASE_DERIVED_INTERVALS)} rolled up from 1h)"
            ),
            fetched_at=fetched_at,
        )
    try:
        product_id = coinbase_product_id(symbol)
    except ValueError as exc:
        return skipped_series(
            name=name,
            venue=COINBASE_VENUE,
            symbol=symbol,
            interval=interval,
            reason=str(exc),
            fetched_at=fetched_at,
        )

    native_interval = COINBASE_DERIVED_INTERVALS.get(interval, interval)
    granularity = COINBASE_GRANULARITY_SECONDS[native_interval]
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    window_end = (end or moment).astimezone(UTC)
    cursor = start.astimezone(UTC)
    if cursor > window_end:
        return skipped_series(
            name=name,
            venue=COINBASE_VENUE,
            symbol=symbol,
            interval=interval,
            reason=f"empty window: start {cursor.isoformat()} > end {window_end.isoformat()}",
            fetched_at=fetched_at,
        )

    notes = [
        f"granularity={granularity}s",
        f"page_size<={COINBASE_MAX_CANDLES_PER_REQUEST}",
        (
            f"pace={requests_per_second:g}rps of a documented "
            f"{COINBASE_PUBLIC_RATE_LIMIT_PER_SECOND:g}rps public limit"
        ),
    ]
    if interval in COINBASE_DERIVED_INTERVALS:
        notes.append(
            f"{interval} rolled up from complete {native_interval} buckets "
            "(Coinbase publishes no native 4h granularity)"
        )

    # Coinbase treats `end` as inclusive, so a 300-bucket page spans 299 steps
    # past `start` and the next page resumes one step later.
    windows = coinbase_page_windows(
        start=cursor,
        end=window_end,
        interval=native_interval,
        page_size=COINBASE_MAX_CANDLES_PER_REQUEST,
    )
    truncated_at = windows[max_requests][0] if len(windows) > max_requests else None
    windows = windows[:max_requests]

    pacer = _Pacer(requests_per_second)
    collected: list[Candle] = []
    owned = client is None
    active = client or httpx.AsyncClient(base_url=base_url, timeout=30)
    requests_made = 0
    try:
        for page_start, page_end in windows:
            await pacer.wait()
            requests_made += 1
            try:
                payload = await fetch_coinbase_page(
                    active,
                    product_id=product_id,
                    granularity_seconds=granularity,
                    start=page_start,
                    end=page_end,
                )
                page = parse_coinbase_candles(payload, symbol=symbol, interval=native_interval)
            except CoinbaseRateLimited as exc:
                # Skip, not a retry storm.
                return skipped_series(
                    name=name,
                    venue=COINBASE_VENUE,
                    symbol=symbol,
                    interval=interval,
                    reason=f"{exc} after {requests_made} request(s); no retry",
                    notes=tuple(notes),
                    fetched_at=fetched_at,
                )
            except (httpx.HTTPError, ArchiveParseError) as exc:
                return skipped_series(
                    name=name,
                    venue=COINBASE_VENUE,
                    symbol=symbol,
                    interval=interval,
                    reason=f"{type(exc).__name__}: {exc}",
                    notes=tuple(notes),
                    fetched_at=fetched_at,
                )
            collected.extend(page)
        if truncated_at is not None:
            notes.append(
                f"stopped at max_requests={max_requests}; "
                f"window truncated at {truncated_at.isoformat()}"
            )
    finally:
        if owned:
            await active.aclose()

    committed = drop_uncommitted(
        tuple(sorted(collected, key=lambda candle: candle.opened_at)),
        interval=native_interval,
        now=moment,
    )
    if interval in COINBASE_DERIVED_INTERVALS:
        committed = aggregate(committed, source_interval=native_interval, target_interval=interval)
    return finish_series(
        name=name,
        venue=COINBASE_VENUE,
        symbol=symbol,
        interval=interval,
        candles=list(committed),
        ok_reason=f"{requests_made} request(s) over {COINBASE_VENUE}",
        empty_reason="Coinbase returned no committed bars in the requested window",
        notes=tuple(notes),
        fetched_at=fetched_at,
    )


def coinbase_page_windows(
    *, start: datetime, end: datetime, interval: str, page_size: int
) -> list[tuple[datetime, datetime]]:
    """The (start, end) windows :func:`fetch_coinbase_candles` would request.

    Exposed so the pagination boundaries are directly testable without any
    transport at all.
    """
    if page_size < 1:
        raise ValueError("page_size must be positive")
    step: timedelta = interval_step(interval)
    windows: list[tuple[datetime, datetime]] = []
    cursor = start.astimezone(UTC)
    # `end` is inclusive on this endpoint: a window whose start equals `end`
    # still asks for one bar, so the walk runs while cursor <= stop.
    stop = end.astimezone(UTC)
    while cursor <= stop:
        page_end = min(cursor + step * (page_size - 1), stop)
        windows.append((cursor, page_end))
        cursor = page_end + step
    return windows
