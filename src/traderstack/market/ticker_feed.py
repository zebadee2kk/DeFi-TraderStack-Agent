import asyncio
import contextlib
from dataclasses import dataclass, field

from traderstack.market.models import MarketTick
from traderstack.market.providers import VenueMarketDataProvider


@dataclass
class PersistentTickerFeed:
    """Single long-lived venue subscription serving the latest tick per symbol.

    One background task consumes ``venue.stream_ticks`` for every configured
    symbol and keeps the newest tick per symbol, reconnecting after a backoff
    whenever the stream ends or fails. Callers read via :meth:`latest` instead
    of opening a fresh connection per symbol per cycle.
    """

    venue: VenueMarketDataProvider
    symbols: tuple[str, ...]
    max_tick_wait_seconds: float = 15.0
    reconnect_backoff_seconds: float = 2.0
    _latest: dict[str, MarketTick] = field(default_factory=dict, init=False)
    _tick_arrived: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    async def latest(self, symbol: str) -> MarketTick:
        """Return the newest tick for ``symbol``, waiting for the first to arrive.

        The tick is returned exactly as received: under a continuous
        subscription its observed_at is the true receive time, so on a quiet
        pair the last tick ages naturally and the downstream staleness gate can
        reject it. (The old connect-per-cycle pattern re-received the
        subscription snapshot each cycle, stamping an old price with a fresh
        observed_at and hiding its staleness.)
        """
        self._ensure_consumer()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_tick_wait_seconds
        while True:
            tick = self._latest.get(symbol)
            if tick is not None:
                return tick
            # Grab the event before re-checking so an update between the check
            # and the wait cannot be missed (the consumer replaces the event
            # after setting it).
            arrived = self._tick_arrived
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RuntimeError(
                    f"no tick for {symbol} within {self.max_tick_wait_seconds}s"
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(arrived.wait(), timeout=remaining)

    async def aclose(self) -> None:
        """Cancel the consumer task; the feed cannot be used afterwards."""
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _ensure_consumer(self) -> None:
        if self._closed:
            raise RuntimeError("ticker feed is closed")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        while not self._closed:
            try:
                async for tick in self.venue.stream_ticks(self.symbols):
                    self._latest[tick.symbol] = tick
                    # Wake current waiters, then arm a fresh event for the
                    # next update.
                    self._tick_arrived.set()
                    self._tick_arrived = asyncio.Event()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001, S110 - transport failures mean reconnect, not crash.
                pass
            await asyncio.sleep(self.reconnect_backoff_seconds)
