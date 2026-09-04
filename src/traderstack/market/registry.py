"""Provider health, quota and caching wrapper (Epic 2/3 resilience).

Per the "Selection policy" in docs/PROVIDER-CAPABILITY-MATRIX.md: "A provider
must have a documented adapter contract, health state, timeout, quota/budget,
freshness threshold and fallback behavior before it can be enabled." This
module gives every request/response-style provider call (reference prices,
candle history, intelligence fetchers) that in one wrapper:

- a per-call timeout
- latency measurement
- consecutive-failure counting and a circuit breaker (closed -> open after
  ``failure_threshold`` consecutive failures -> half-open after
  ``cooldown_seconds`` -> closed again on the next success, or straight back
  to open on the next failure)
- per-provider quota budgets (calls per minute / per day); a call beyond
  budget is refused before it reaches the network
- an optional short-TTL cache keyed by the caller's own ``cache_key``, so a
  fast poll loop (e.g. the 5-second paper-trading cycle) doesn't burn a slow
  free-tier quota (CoinGecko ~30 req/min, CoinMarketCap Basic's small daily
  allowance) - a cache hit returns the exact prior value (including its
  original ``observed_at``), so downstream freshness checks still see real
  data age, not a refreshed timestamp
- a ``health()`` report and Prometheus counters/gauges, following the pattern
  in ``traderstack.health``

Streaming venue feeds (Kraken ticker/book) are NOT wrapped here - they have
their own reconnect/backoff/staleness handling in ``market.adapters`` because
a circuit breaker and a request timeout don't apply to a long-lived
subscription the same way.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

from prometheus_client import Counter, Gauge

from traderstack.candles import Candle
from traderstack.market.models import ReferencePrice
from traderstack.market.providers import CandleHistoryProvider, ReferencePriceProvider

provider_calls_total = Counter(
    "traderstack_provider_calls_total",
    "Provider registry calls by outcome",
    ("provider", "outcome"),
)
provider_last_latency_seconds = Gauge(
    "traderstack_provider_last_latency_seconds",
    "Latency of the most recent successful provider call",
    ("provider",),
)
provider_breaker_state = Gauge(
    "traderstack_provider_breaker_state",
    "Circuit breaker state: 0=closed, 1=half_open, 2=open",
    ("provider",),
)
provider_quota_rejections_total = Counter(
    "traderstack_provider_quota_rejections_total",
    "Calls refused for exceeding a quota budget",
    ("provider", "window"),
)
provider_cache_hits_total = Counter(
    "traderstack_provider_cache_hits_total",
    "TTL cache hits that avoided an upstream call",
    ("provider",),
)


class BreakerState(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


_STATE_VALUE = {BreakerState.CLOSED: 0, BreakerState.HALF_OPEN: 1, BreakerState.OPEN: 2}


class ProviderCircuitOpenError(RuntimeError):
    """Raised when a call is refused because the provider's circuit is open."""


class ProviderQuotaExceededError(RuntimeError):
    """Raised when a call is refused because it would exceed the configured quota."""


@dataclass(frozen=True)
class ProviderHealthReport:
    name: str
    state: BreakerState
    consecutive_failures: int
    last_latency_seconds: float | None
    last_success_at: datetime | None
    last_error: str | None
    calls_last_minute: int
    calls_today: int


@dataclass
class _CacheEntry:
    value: Any
    expires_at: datetime


_MISS = object()


@dataclass
class ProviderRegistry:
    """Wraps a fallible async provider call with a timeout, a circuit breaker,
    quota budgets and an optional TTL cache. One instance per provider.
    """

    name: str
    timeout_seconds: float = 10.0
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    calls_per_minute: int | None = None
    calls_per_day: int | None = None
    # 0 (default) disables caching.
    cache_ttl_seconds: float = 0.0
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    _state: BreakerState = field(init=False, default=BreakerState.CLOSED)
    _consecutive_failures: int = field(init=False, default=0)
    _opened_at: datetime | None = field(init=False, default=None)
    _last_latency_seconds: float | None = field(init=False, default=None)
    _last_success_at: datetime | None = field(init=False, default=None)
    _last_error: str | None = field(init=False, default=None)
    _minute_calls: deque[datetime] = field(init=False, default_factory=deque)
    _day: date | None = field(init=False, default=None)
    _day_count: int = field(init=False, default=0)
    _cache: dict[Hashable, _CacheEntry] = field(init=False, default_factory=dict)

    def _now(self) -> datetime:
        return self.clock()

    async def call[T](
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        cache_key: Hashable | None = None,
        **kwargs: Any,
    ) -> T:
        now = self._now()
        if cache_key is not None and self.cache_ttl_seconds > 0:
            cached = self._cache_get(cache_key, now)
            if cached is not _MISS:
                provider_cache_hits_total.labels(provider=self.name).inc()
                return cached  # type: ignore[no-any-return]

        self._check_breaker(now)
        self._reserve_quota(now)

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.timeout_seconds)
        except Exception as exc:  # recorded then re-raised for the caller to handle
            self._record_failure(exc)
            raise
        latency = time.monotonic() - start
        self._record_success(latency)
        if cache_key is not None and self.cache_ttl_seconds > 0:
            self._cache_put(cache_key, result, now)
        return result

    def _check_breaker(self, now: datetime) -> None:
        if self._state is BreakerState.OPEN:
            if self._opened_at is not None and (now - self._opened_at).total_seconds() >= self.cooldown_seconds:
                self._state = BreakerState.HALF_OPEN
                provider_breaker_state.labels(provider=self.name).set(_STATE_VALUE[self._state])
            else:
                raise ProviderCircuitOpenError(f"provider {self.name!r} circuit is open")

    def _reserve_quota(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=60)
        while self._minute_calls and self._minute_calls[0] < cutoff:
            self._minute_calls.popleft()
        today = now.date()
        if self._day != today:
            self._day = today
            self._day_count = 0

        if self.calls_per_minute is not None and len(self._minute_calls) >= self.calls_per_minute:
            provider_quota_rejections_total.labels(provider=self.name, window="minute").inc()
            raise ProviderQuotaExceededError(
                f"provider {self.name!r} exceeded {self.calls_per_minute} calls/minute budget"
            )
        if self.calls_per_day is not None and self._day_count >= self.calls_per_day:
            provider_quota_rejections_total.labels(provider=self.name, window="day").inc()
            raise ProviderQuotaExceededError(
                f"provider {self.name!r} exceeded {self.calls_per_day} calls/day budget"
            )

        self._minute_calls.append(now)
        self._day_count += 1

    def _record_failure(self, exc: BaseException) -> None:
        self._consecutive_failures += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        provider_calls_total.labels(provider=self.name, outcome="error").inc()
        if self._state is BreakerState.HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
            self._state = BreakerState.OPEN
            self._opened_at = self._now()
        provider_breaker_state.labels(provider=self.name).set(_STATE_VALUE[self._state])

    def _record_success(self, latency_seconds: float) -> None:
        self._consecutive_failures = 0
        self._last_latency_seconds = latency_seconds
        self._last_success_at = self._now()
        self._state = BreakerState.CLOSED
        self._opened_at = None
        provider_calls_total.labels(provider=self.name, outcome="success").inc()
        provider_last_latency_seconds.labels(provider=self.name).set(latency_seconds)
        provider_breaker_state.labels(provider=self.name).set(_STATE_VALUE[self._state])

    def _cache_get(self, key: Hashable, now: datetime) -> Any:
        entry = self._cache.get(key)
        if entry is None:
            return _MISS
        if now >= entry.expires_at:
            del self._cache[key]
            return _MISS
        return entry.value

    def _cache_put(self, key: Hashable, value: Any, now: datetime) -> None:
        self._cache[key] = _CacheEntry(value=value, expires_at=now + timedelta(seconds=self.cache_ttl_seconds))

    def health(self) -> ProviderHealthReport:
        now = self._now()
        cutoff = now - timedelta(seconds=60)
        calls_last_minute = sum(1 for ts in self._minute_calls if ts >= cutoff)
        return ProviderHealthReport(
            name=self.name,
            state=self._state,
            consecutive_failures=self._consecutive_failures,
            last_latency_seconds=self._last_latency_seconds,
            last_success_at=self._last_success_at,
            last_error=self._last_error,
            calls_last_minute=calls_last_minute,
            calls_today=self._day_count if self._day == now.date() else 0,
        )

    async def healthy(self) -> bool:
        """Satisfies the `ProviderHealth` protocol in `market.providers`."""
        return self._state is not BreakerState.OPEN


# --- convenience wrappers: drop-in replacements for the Protocols in market.providers


class RegisteredReferencePriceProvider:
    """Wraps a `ReferencePriceProvider` with timeout/breaker/quota/TTL-cache."""

    def __init__(self, provider: ReferencePriceProvider, registry: ProviderRegistry) -> None:
        self._provider = provider
        self.registry = registry

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return await self.registry.call(
            self._provider.get_prices, assets, cache_key=("get_prices", assets)
        )


class RegisteredCandleHistoryProvider:
    """Wraps a `CandleHistoryProvider` with timeout/breaker/quota/TTL-cache."""

    def __init__(self, provider: CandleHistoryProvider, registry: ProviderRegistry) -> None:
        self._provider = provider
        self.registry = registry

    async def fetch(
        self, symbol: str, resolution: str = "1h", *, count: int = 250
    ) -> tuple[Candle, ...]:
        return await self.registry.call(
            self._provider.fetch,
            symbol,
            resolution,
            count=count,
            cache_key=("fetch", symbol, resolution, count),
        )


def registered_fetcher[T](
    fetcher: Callable[[str], Awaitable[T]], registry: ProviderRegistry
) -> Callable[[str], Awaitable[T]]:
    """Wraps a single-argument `Callable[[str], Awaitable[T]]` intelligence
    fetcher (the shape `IntelligenceOrchestrator` expects) the same way.
    """

    async def wrapped(asset: str) -> T:
        return await registry.call(fetcher, asset, cache_key=("fetch", asset))

    return wrapped
