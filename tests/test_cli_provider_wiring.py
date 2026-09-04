from pathlib import Path

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_intelligence, build_provider_registry, build_service
from traderstack.config import Settings
from traderstack.market.adapters import KrakenBookProvider, KrakenTickerProvider
from traderstack.market.registry import (
    RegisteredCandleHistoryProvider,
    RegisteredReferencePriceProvider,
)
from traderstack.portfolio import InMemoryPortfolioBook


async def _noop(_: object) -> None:
    return None


def base_settings(**overrides: object) -> Settings:
    overrides.setdefault("kill_switch", False)
    overrides.setdefault("pretrade_backtest_enabled", False)
    return Settings(**overrides)  # type: ignore[arg-type]


def test_build_provider_registry_uses_settings_defaults() -> None:
    settings = base_settings(
        provider_timeout_seconds=7.5,
        provider_failure_threshold=4,
        provider_breaker_cooldown_seconds=12,
    )
    registry = build_provider_registry(
        settings, "example", calls_per_minute=5, cache_ttl_seconds=15
    )
    assert registry.name == "example"
    assert registry.timeout_seconds == 7.5
    assert registry.failure_threshold == 4
    assert registry.cooldown_seconds == 12
    assert registry.calls_per_minute == 5
    assert registry.cache_ttl_seconds == 15


def test_build_intelligence_includes_altfins_alone() -> None:
    orchestrator = build_intelligence(base_settings(altfins_api_key="secret"))
    assert orchestrator is not None
    assert orchestrator.altfins is not None
    assert orchestrator.onchain is None
    assert orchestrator.social is None
    assert orchestrator.news == ()


def test_build_service_carries_pipeline_max_spread_bps_from_settings(tmp_path: Path) -> None:
    """MAX_SPREAD_BPS must reach VerticalSlicePipeline, not stay at its dataclass
    default -- it was previously constructed without this argument at all.
    """

    settings = base_settings(max_spread_bps=17.5)
    checkpoint_store = JsonPortfolioCheckpointStore(tmp_path / "portfolio.json")
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=5.0,
        portfolio=InMemoryPortfolioBook(settings.paper_starting_nav_usd),
        on_result=_noop,
        checkpoint_store=checkpoint_store,
    )
    assert service.runtime.pipeline.max_spread_bps == 17.5


def test_build_service_wraps_reference_and_candle_providers_through_the_registry(
    tmp_path: Path,
) -> None:
    settings = base_settings(pretrade_backtest_enabled=True)
    checkpoint_store = JsonPortfolioCheckpointStore(tmp_path / "portfolio.json")
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=5.0,
        portfolio=InMemoryPortfolioBook(settings.paper_starting_nav_usd),
        on_result=_noop,
        checkpoint_store=checkpoint_store,
    )
    for reference in service.runtime.references:
        assert isinstance(reference, RegisteredReferencePriceProvider)
    assert isinstance(service.runtime.candles, RegisteredCandleHistoryProvider)
    assert isinstance(service.runtime.venue, KrakenTickerProvider)
    assert service.runtime.book is None


def test_build_service_carries_kraken_reconnect_settings_and_optional_book(tmp_path: Path) -> None:
    settings = base_settings(
        kraken_max_reconnect_attempts=4,
        kraken_stale_after_seconds=12,
        kraken_book_enabled=True,
        kraken_book_depth=25,
    )
    checkpoint_store = JsonPortfolioCheckpointStore(tmp_path / "portfolio.json")
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=5.0,
        portfolio=InMemoryPortfolioBook(settings.paper_starting_nav_usd),
        on_result=_noop,
        checkpoint_store=checkpoint_store,
    )
    venue = service.runtime.venue
    assert isinstance(venue, KrakenTickerProvider)
    assert venue.max_reconnect_attempts == 4
    assert venue.stale_after_seconds == 12

    book = service.runtime.book
    assert isinstance(book, KrakenBookProvider)
    assert book.depth == 25
