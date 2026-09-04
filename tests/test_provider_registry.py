import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.market.registry import (
    BreakerState,
    ProviderCircuitOpenError,
    ProviderQuotaExceededError,
    ProviderRegistry,
    registered_fetcher,
)


class _Clock:
    """A controllable clock for deterministic breaker/quota tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 4, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


# --- circuit breaker -------------------------------------------------------


@pytest.mark.asyncio
async def test_breaker_opens_after_failure_threshold_and_refuses_further_calls() -> None:
    clock = _Clock()
    registry = ProviderRegistry(name="flaky", failure_threshold=2, cooldown_seconds=30, clock=clock)
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await registry.call(flaky)
    assert registry.health().state is BreakerState.CLOSED

    with pytest.raises(RuntimeError):
        await registry.call(flaky)
    assert registry.health().state is BreakerState.OPEN
    assert calls == 2

    # Circuit is open: the wrapped function is not even invoked again.
    with pytest.raises(ProviderCircuitOpenError):
        await registry.call(flaky)
    assert calls == 2


@pytest.mark.asyncio
async def test_breaker_half_opens_after_cooldown_and_closes_on_success() -> None:
    clock = _Clock()
    registry = ProviderRegistry(name="recovering", failure_threshold=1, cooldown_seconds=10, clock=clock)

    async def failing() -> str:
        raise RuntimeError("down")

    async def healthy() -> str:
        return "ok"

    with pytest.raises(RuntimeError):
        await registry.call(failing)
    assert registry.health().state is BreakerState.OPEN

    # Still within cooldown: refused outright.
    clock.advance(5)
    with pytest.raises(ProviderCircuitOpenError):
        await registry.call(failing)

    # Cooldown elapsed: a trial call is let through (half-open) and succeeds.
    clock.advance(10)
    result = await registry.call(healthy)
    assert result == "ok"
    assert registry.health().state is BreakerState.CLOSED


@pytest.mark.asyncio
async def test_breaker_half_open_failure_reopens_immediately() -> None:
    clock = _Clock()
    registry = ProviderRegistry(name="unstable", failure_threshold=5, cooldown_seconds=10, clock=clock)

    async def failing() -> str:
        raise RuntimeError("down")

    # A single failure below the normal threshold would not normally open the
    # breaker, but a half-open trial call failing must reopen it immediately.
    for _ in range(5):
        with pytest.raises(RuntimeError):
            await registry.call(failing)
    assert registry.health().state is BreakerState.OPEN

    clock.advance(10)
    with pytest.raises(RuntimeError):
        await registry.call(failing)  # the half-open trial call
    assert registry.health().state is BreakerState.OPEN


@pytest.mark.asyncio
async def test_timeout_counts_as_a_failure() -> None:
    registry = ProviderRegistry(name="slow", timeout_seconds=0.01, failure_threshold=1)

    async def slow() -> str:
        await asyncio.sleep(0.2)
        return "too late"

    with pytest.raises(TimeoutError):
        await registry.call(slow)
    assert registry.health().state is BreakerState.OPEN
    assert registry.health().consecutive_failures == 1


# --- quota -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_per_minute_refuses_calls_beyond_budget() -> None:
    clock = _Clock()
    registry = ProviderRegistry(name="quota-limited", calls_per_minute=2, clock=clock)
    calls = 0

    async def ping() -> str:
        nonlocal calls
        calls += 1
        return "pong"

    assert await registry.call(ping) == "pong"
    assert await registry.call(ping) == "pong"
    with pytest.raises(ProviderQuotaExceededError):
        await registry.call(ping)
    assert calls == 2  # the third call never reached the function

    # A minute later the window has rolled forward and calls are allowed again.
    clock.advance(61)
    assert await registry.call(ping) == "pong"
    assert calls == 3


@pytest.mark.asyncio
async def test_quota_per_day_resets_on_the_next_day() -> None:
    clock = _Clock()
    registry = ProviderRegistry(name="daily-limited", calls_per_day=1, clock=clock)

    async def ping() -> str:
        return "pong"

    assert await registry.call(ping) == "pong"
    with pytest.raises(ProviderQuotaExceededError):
        await registry.call(ping)

    clock.advance(24 * 60 * 60 + 1)
    assert await registry.call(ping) == "pong"


# --- TTL cache -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_avoids_upstream_call_and_preserves_original_payload() -> None:
    clock = _Clock()
    registry = ProviderRegistry(name="cached", cache_ttl_seconds=30, clock=clock)
    calls = 0

    async def fetch_price() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"price": 100.0, "fetched_at": clock.now}

    first = await registry.call(fetch_price, cache_key="btc")
    clock.advance(5)
    second = await registry.call(fetch_price, cache_key="btc")

    assert calls == 1
    assert second is first
    # The pipeline's freshness check must still see the *original* fetch time,
    # not a refreshed one, even though five seconds of wall-clock passed.
    assert second["fetched_at"] == first["fetched_at"]

    clock.advance(30)
    await registry.call(fetch_price, cache_key="btc")
    assert calls == 2


@pytest.mark.asyncio
async def test_cache_disabled_by_default_calls_upstream_every_time() -> None:
    registry = ProviderRegistry(name="uncached")
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await registry.call(fetch, cache_key="x") == 1
    assert await registry.call(fetch, cache_key="x") == 2


# --- registered_fetcher wrapper -------------------------------------------------


@pytest.mark.asyncio
async def test_registered_fetcher_delegates_through_the_registry() -> None:
    registry = ProviderRegistry(name="news", failure_threshold=1)

    async def underlying(asset: str) -> str:
        return f"snapshot:{asset}"

    wrapped = registered_fetcher(underlying, registry)
    assert await wrapped("BTC") == "snapshot:BTC"
    assert registry.health().state is BreakerState.CLOSED


@pytest.mark.asyncio
async def test_health_report_reflects_calls_and_latency() -> None:
    registry = ProviderRegistry(name="reported")

    async def ok() -> None:
        return None

    await registry.call(ok)
    report = registry.health()
    assert report.name == "reported"
    assert report.state is BreakerState.CLOSED
    assert report.last_latency_seconds is not None
    assert report.last_success_at is not None
    assert report.calls_last_minute == 1
