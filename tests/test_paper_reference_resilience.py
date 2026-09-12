"""Paper-only last-good reference reuse and CoinGecko 429 backoff.

Live/shadow must keep fail-closed (no last-good). A 429 retry is
good-client behaviour in every mode and does not authorise a trade.
"""

from pathlib import Path

import httpx
import pytest

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_provider_registry, build_service
from traderstack.config import Settings
from traderstack.market.adapters import CoinGeckoPriceProvider, retry_after_seconds
from traderstack.market.models import MarketSource
from traderstack.market.registry import RegisteredReferencePriceProvider
from traderstack.portfolio import InMemoryPortfolioBook


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
        "pretrade_backtest_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


async def _noop(_: object) -> None:
    return None


def test_retry_after_seconds_caps_and_falls_back() -> None:
    response = httpx.Response(429, headers={"Retry-After": "8"})
    assert retry_after_seconds(response, 2.0) == 2.0
    response = httpx.Response(429, headers={"Retry-After": "1.5"})
    assert retry_after_seconds(response, 2.0) == 1.5
    response = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert retry_after_seconds(response, 2.0) == 1.0
    response = httpx.Response(429)
    assert retry_after_seconds(response, 2.0) == 1.0


@pytest.mark.asyncio
async def test_coingecko_retries_once_on_429_then_succeeds() -> None:
    attempts = 0
    slept: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"bitcoin": {"usd": 20_000.0}})

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.coingecko.com"
    )
    provider = CoinGeckoPriceProvider(client=client, sleep=fake_sleep)
    prices = await provider.get_prices(("BTC",))
    await client.aclose()

    assert attempts == 2
    assert slept == [1.0]
    assert len(prices) == 1
    assert prices[0].source is MarketSource.COINGECKO
    assert prices[0].asset == "BTC"
    assert prices[0].price == 20_000.0


@pytest.mark.asyncio
async def test_coingecko_exhausted_429_still_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    async def fake_sleep(delay: float) -> None:
        return None

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.coingecko.com"
    )
    provider = CoinGeckoPriceProvider(client=client, sleep=fake_sleep)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_prices(("BTC",))
    await client.aclose()


def test_paper_settings_activate_reference_resilience() -> None:
    paper = _settings()
    assert paper.trading_mode == "paper"
    assert paper.paper_reference_resilience_active is True
    assert paper.effective_reference_cache_seconds == paper.paper_reference_cache_seconds
    assert paper.effective_reference_last_good_seconds == paper.paper_reference_last_good_seconds
    assert paper.paper_reference_last_good_seconds > 0


def test_live_and_shadow_disable_last_good() -> None:
    for mode in ("live", "shadow"):
        settings = _settings(trading_mode=mode, paper_reference_last_good_seconds=300)
        assert settings.paper_reference_resilience_active is False
        assert settings.effective_reference_last_good_seconds == 0.0
        assert settings.effective_reference_cache_seconds == settings.reference_price_cache_seconds


def test_build_service_wires_last_good_on_paper(tmp_path: Path) -> None:
    paper = build_service(
        _settings(),
        submit=False,
        cycle_seconds=5.0,
        portfolio=InMemoryPortfolioBook(10_000),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "paper.json"),
    )
    for reference in paper.runtime.references:
        assert isinstance(reference, RegisteredReferencePriceProvider)
        assert reference.registry.last_good_ttl_seconds == 300.0
        assert reference.registry.cache_ttl_seconds == 120.0


def test_build_service_refuses_non_paper_so_last_good_cannot_be_wired() -> None:
    with pytest.raises(RuntimeError, match="TRADING_MODE=live is rejected"):
        build_service(
            _settings(trading_mode="live"),
            submit=False,
            cycle_seconds=5.0,
            portfolio=InMemoryPortfolioBook(10_000),
            on_result=_noop,
            checkpoint_store=JsonPortfolioCheckpointStore(Path("unused.json")),
        )


def test_build_provider_registry_forwards_last_good() -> None:
    registry = build_provider_registry(
        _settings(), "coingecko", cache_ttl_seconds=120, last_good_ttl_seconds=300
    )
    assert registry.last_good_ttl_seconds == 300
    assert registry.cache_ttl_seconds == 120
