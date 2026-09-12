"""Shared reconnect/backoff loop for long-lived public market-data websockets.

Streaming venue and paper-research feeds (Kraken ticker/book, Binance USDT-M
liquidations, optional Binance/Bybit bookTicker) are deliberately *not* wrapped
by ``ProviderRegistry``: a request timeout and circuit breaker do not fit a
long-lived subscription. They share this reconnect loop instead — the same
pattern documented for Kraken in ``docs/PROVIDER-CAPABILITY-MATRIX.md``.

A collector that exhausts reconnects raises ``FeedExhausted``. For
paper-research feeds that is informational: the trading cycle continues with
missing edge features rather than halting. Kraken remains the primary tick
source and keeps its own fail-closed posture.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import websockets
from prometheus_client import Counter, Gauge

DEFAULT_MAX_RECONNECT_ATTEMPTS = 10
DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_MAX_SECONDS = 30.0
DEFAULT_STALE_AFTER_SECONDS = 30.0

ConnectFactory = Callable[..., Any]
SleepFn = Callable[[float], Awaitable[None]]

stream_messages_total = Counter(
    "traderstack_stream_messages_total",
    "Streaming feed items yielded by the reconnect loop, by feed",
    ("feed", "outcome"),
)
stream_reconnects_total = Counter(
    "traderstack_stream_reconnects_total",
    "Streaming feed reconnect attempts, by feed",
    ("feed",),
)
stream_last_message_unixtime = Gauge(
    "traderstack_stream_last_message_unixtime",
    "Unix timestamp of the last item yielded by a streaming feed",
    ("feed",),
)


class FeedError(RuntimeError):
    """Raised when one connection attempt cannot be trusted (stalled, disconnected).

    Caught and retried by the reconnect loop.
    """


class FeedExhausted(FeedError):
    """Raised when reconnect attempts are exhausted; the stream truly ends."""


def compute_backoff(attempt: int, base_seconds: float, max_seconds: float, jitter: float) -> float:
    """Capped exponential backoff with full jitter: ``jitter`` in [0, 1] scales
    the delay into [0.5x, 1x] of the nominal value so many reconnecting clients
    don't all retry in lockstep.
    """
    nominal = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
    return nominal * (0.5 + max(0.0, min(1.0, jitter)) * 0.5)


def record_stream_message(feed_name: str, *, outcome: str = "yielded") -> None:
    stream_messages_total.labels(feed=feed_name, outcome=outcome).inc()
    if outcome == "yielded":
        stream_last_message_unixtime.labels(feed=feed_name).set(time.time())


async def stream_with_reconnect[T](
    open_once: Callable[[], AsyncIterator[T]],
    *,
    feed_name: str,
    max_reconnect_attempts: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
    sleep: SleepFn,
    random_jitter: Callable[[], float],
) -> AsyncIterator[T]:
    """Run ``open_once()`` (a fresh connection + subscribe + read loop each call)
    and reconnect with backoff on failure, yielding items continuously across
    reconnects. ``open_once`` should raise ``FeedError`` on a stale/dead
    connection; transport errors (``OSError``, timeouts, websockets exceptions)
    are caught here too.
    """
    attempt = 0
    while True:
        try:
            async for item in open_once():
                attempt = 0  # any successful message resets the backoff counter
                record_stream_message(feed_name, outcome="yielded")
                yield item
            # A generator that returns instead of raising is still a lost
            # connection (server closed cleanly) - treat it as one.
            raise FeedError(f"{feed_name} stream ended unexpectedly")
        except (
            FeedError,
            OSError,
            TimeoutError,
            websockets.exceptions.WebSocketException,
        ) as exc:
            attempt += 1
            stream_reconnects_total.labels(feed=feed_name).inc()
            if attempt > max_reconnect_attempts:
                raise FeedExhausted(
                    f"{feed_name} failed after {attempt - 1} reconnect attempt(s)"
                ) from exc
            delay = compute_backoff(
                attempt, backoff_base_seconds, backoff_max_seconds, random_jitter()
            )
            await sleep(delay)


async def recv_or_stale(
    ws: Any,
    *,
    stale_after_seconds: float,
    feed_name: str,
) -> Any:
    """Read one websocket message, optionally treating silence as a dead feed.

    ``stale_after_seconds <= 0`` disables the application-level timeout and
    relies on the websocket ping/pong for liveness — required for sparse
    streams such as liquidations, which can be quiet for minutes in calm
    markets without the connection being dead.
    """
    if stale_after_seconds <= 0:
        return await ws.recv()
    try:
        return await asyncio.wait_for(ws.recv(), timeout=stale_after_seconds)
    except TimeoutError as exc:
        raise FeedError(f"no {feed_name} message within {stale_after_seconds}s") from exc
