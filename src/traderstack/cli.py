import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from prometheus_client import start_http_server
from pydantic import SecretStr

from traderstack.audit import JsonlAuditSink
from traderstack.backtest import BaselineBacktester
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.config import Settings
from traderstack.eventing import FanoutResultSink, PostgresRuntimeEventStore, RedisRuntimePublisher
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.intelligence_orchestrator import (
    IntelligenceCache,
    IntelligenceOrchestrator,
    NewsFetcher,
)
from traderstack.market.adapters import (
    CoinGeckoPriceProvider,
    CoinMarketCapPriceProvider,
    KrakenBookProvider,
    KrakenTickerProvider,
)
from traderstack.market.altfins import AltFinsSignalProvider
from traderstack.market.intelligence_providers import (
    CryptoPanicNewsProvider,
    DuneOnChainProvider,
    LunarCrushSocialProvider,
)
from traderstack.market.kraken_candles import KrakenCandleProvider
from traderstack.market.perplexity import PerplexityNewsProvider
from traderstack.market.providers import BookSnapshotProvider, VenueMarketDataProvider
from traderstack.market.registry import (
    ProviderRegistry,
    RegisteredCandleHistoryProvider,
    RegisteredReferencePriceProvider,
    registered_fetcher,
)
from traderstack.market.robinhood_chain_feed import swap_feed_from_settings
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime, RuntimeResult
from traderstack.service import ContinuousPaperService

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]


def build_pretrade_gate(settings: Settings) -> PreTradeBacktestGate:
    backtester = BaselineBacktester(
        starting_equity=settings.paper_starting_nav_usd,
        fee_bps=settings.pretrade_fee_bps,
        slippage_bps=settings.pretrade_slippage_bps,
    )
    return PreTradeBacktestGate(
        backtester=backtester,
        min_candles=settings.pretrade_min_candles,
        max_candle_age_seconds=settings.pretrade_max_candle_age_seconds,
        min_excess_return=settings.pretrade_min_excess_return,
        max_drawdown=settings.pretrade_max_drawdown_pct,
        min_sharpe=settings.pretrade_min_sharpe,
        min_trades=settings.pretrade_min_trades,
        require_walkforward=settings.pretrade_require_walkforward,
    )


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


# --- providers (Epic 2/3): provider health, quota and caching wrapper ----------


def build_provider_registry(
    settings: Settings,
    name: str,
    *,
    calls_per_minute: int | None = None,
    calls_per_day: int | None = None,
    cache_ttl_seconds: float = 0.0,
) -> ProviderRegistry:
    """One `ProviderRegistry` per named provider, using the shared timeout/
    breaker defaults from settings plus that provider's own quota/cache.
    """
    return ProviderRegistry(
        name=name,
        timeout_seconds=settings.provider_timeout_seconds,
        failure_threshold=settings.provider_failure_threshold,
        cooldown_seconds=settings.provider_breaker_cooldown_seconds,
        calls_per_minute=calls_per_minute,
        calls_per_day=calls_per_day,
        cache_ttl_seconds=cache_ttl_seconds,
    )


def parse_dune_query_ids(raw: str) -> dict[str, int]:
    query_ids: dict[str, int] = {}
    for spec in raw.split(","):
        spec = spec.strip()
        if not spec:
            continue
        asset, _, query_id = spec.partition(":")
        if not asset.strip() or not query_id.strip().isdigit():
            raise RuntimeError(f"malformed DUNE_QUERY_IDS entry: {spec!r}")
        query_ids[asset.strip().upper()] = int(query_id.strip())
    return query_ids


def build_intelligence(settings: Settings) -> IntelligenceOrchestrator | None:
    """Assemble every intelligence provider that has credentials; None if there are none.

    Every fetcher is wrapped through a per-provider `ProviderRegistry`
    (timeout, circuit breaker, quota) - see build_provider_registry above.
    """
    quota = settings.intelligence_provider_calls_per_minute

    onchain = None
    if settings.dune_api_key is not None:
        query_ids = parse_dune_query_ids(settings.dune_query_ids)
        if query_ids:
            onchain = registered_fetcher(
                DuneOnChainProvider(
                    api_key=settings.dune_api_key.get_secret_value(), query_ids=query_ids
                ).fetch,
                build_provider_registry(settings, "dune", calls_per_minute=quota),
            )

    social = None
    if settings.lunarcrush_api_key is not None:
        social = registered_fetcher(
            LunarCrushSocialProvider(api_key=settings.lunarcrush_api_key.get_secret_value()).fetch,
            build_provider_registry(settings, "lunarcrush", calls_per_minute=quota),
        )

    news: list[NewsFetcher] = []
    if settings.cryptopanic_api_key is not None:
        news.append(
            registered_fetcher(
                CryptoPanicNewsProvider(
                    auth_token=settings.cryptopanic_api_key.get_secret_value(),
                    api_plan=settings.cryptopanic_api_plan,
                ).fetch,
                build_provider_registry(settings, "cryptopanic", calls_per_minute=quota),
            )
        )
    if settings.perplexity_api_key is not None:
        news.append(
            registered_fetcher(
                PerplexityNewsProvider(api_key=settings.perplexity_api_key.get_secret_value()).fetch,
                build_provider_registry(settings, "perplexity", calls_per_minute=quota),
            )
        )

    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    altfins = None
    if settings.altfins_api_key is not None:
        altfins = registered_fetcher(
            AltFinsSignalProvider(api_key=settings.altfins_api_key.get_secret_value()).fetch,
            build_provider_registry(settings, "altfins", calls_per_minute=quota),
        )

    if onchain is None and social is None and not news and altfins is None:
        return None
    return IntelligenceOrchestrator(
        onchain=onchain,
        social=social,
        news=tuple(news),
        cache=IntelligenceCache(max_age_seconds=settings.intelligence_cache_seconds),
        require_any_external=settings.intelligence_required,
        altfins=altfins,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the guarded continuous paper trading service")
    parser.add_argument("--submit", action="store_true", help="submit approved paper orders")
    parser.add_argument("--audit-path", default="var/audit/runtime.jsonl")
    parser.add_argument("--checkpoint-path", default="var/state/portfolio.json")
    parser.add_argument("--cycle-seconds", type=float, default=5.0)
    parser.add_argument("--metrics-port", type=int, default=9108)
    parser.add_argument(
        "--persistent-events",
        action="store_true",
        help="also persist runtime events to PostgreSQL and publish them to Redis",
    )
    return parser


def build_service(
    settings: Settings,
    *,
    submit: bool,
    cycle_seconds: float,
    portfolio: InMemoryPortfolioBook,
    on_result: ResultHandler,
    checkpoint_store: JsonPortfolioCheckpointStore,
) -> ContinuousPaperService:
    if settings.trading_mode != "paper":
        raise RuntimeError("continuous paper service requires TRADING_MODE=paper")

    executor = None
    if submit:
        if settings.hummingbot_api_username is None or settings.hummingbot_api_password is None:
            raise RuntimeError("paper submission requires Hummingbot API credentials")
        executor = HummingbotPaperExecutor(
            base_url=settings.hummingbot_api_url,
            username=settings.hummingbot_api_username,
            password=settings.hummingbot_api_password.get_secret_value(),
            account_name=settings.hummingbot_account_name,
            connector_name=settings.hummingbot_connector_name,
        )

    pretrade_gate = None
    candle_provider = None
    if settings.pretrade_backtest_enabled:
        pretrade_gate = build_pretrade_gate(settings)
        # --- providers (Epic 2/3): provider health, quota and caching wrapper --
        candle_provider = RegisteredCandleHistoryProvider(
            KrakenCandleProvider(),
            build_provider_registry(
                settings, "kraken_candles", calls_per_minute=settings.candle_provider_calls_per_minute
            ),
        )

    intelligence = build_intelligence(settings)
    if settings.intelligence_required and intelligence is None:
        raise RuntimeError("INTELLIGENCE_REQUIRED=true but no intelligence provider has credentials")

    pipeline = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        max_tick_age_seconds=settings.max_market_data_age_seconds,
        max_reference_divergence_bps=settings.max_reference_divergence_bps,
        pretrade_gate=pretrade_gate,
        feature_builder=CandleMarketFeatureBuilder() if pretrade_gate else None,
        block_on_adverse_news=settings.intelligence_block_on_adverse_news,
        require_external_intelligence=settings.intelligence_required,
    )
    venue: VenueMarketDataProvider
    book: BookSnapshotProvider | None = None
    if settings.venue_feed == "robinhood_chain":
        swap_feed = swap_feed_from_settings(settings)
        venue = swap_feed
        symbols = tuple(
            pool.symbol
            for pool in swap_feed.pools
            if pool.symbol.split("/", 1)[0].upper() in settings.assets
        )
        if not symbols:
            raise RuntimeError("no ROBINHOOD_CHAIN_POOLS match MVP_ASSETS")
    else:
        venue = KrakenTickerProvider(
            max_reconnect_attempts=settings.kraken_max_reconnect_attempts,
            backoff_base_seconds=settings.kraken_backoff_base_seconds,
            backoff_max_seconds=settings.kraken_backoff_max_seconds,
            stale_after_seconds=settings.kraken_stale_after_seconds,
        )
        symbols = tuple(f"{asset}/USD" for asset in settings.assets)
        # --- providers (Epic 2): order-book snapshot handling -------------------
        if settings.kraken_book_enabled:
            book = KrakenBookProvider(
                depth=settings.kraken_book_depth,
                max_reconnect_attempts=settings.kraken_max_reconnect_attempts,
                backoff_base_seconds=settings.kraken_backoff_base_seconds,
                backoff_max_seconds=settings.kraken_backoff_max_seconds,
                stale_after_seconds=settings.kraken_stale_after_seconds,
            )

    # --- providers (Epic 2/3): provider health, quota and caching wrapper ------
    reference_registry_kwargs = {"cache_ttl_seconds": settings.reference_price_cache_seconds}
    runtime = PaperRuntime(
        venue=venue,
        references=(
            RegisteredReferencePriceProvider(
                CoinGeckoPriceProvider(api_key=_secret(settings.coingecko_api_key)),
                build_provider_registry(
                    settings,
                    "coingecko",
                    calls_per_minute=settings.coingecko_calls_per_minute,
                    calls_per_day=settings.coingecko_calls_per_day,
                    **reference_registry_kwargs,
                ),
            ),
            RegisteredReferencePriceProvider(
                CoinMarketCapPriceProvider(api_key=_secret(settings.coinmarketcap_api_key)),
                build_provider_registry(
                    settings,
                    "coinmarketcap",
                    calls_per_minute=settings.coinmarketcap_calls_per_minute,
                    calls_per_day=settings.coinmarketcap_calls_per_day,
                    **reference_registry_kwargs,
                ),
            ),
        ),
        pipeline=pipeline,
        executor=executor,
        candles=candle_provider,
        candle_interval=settings.pretrade_candle_interval,
        candle_count=settings.pretrade_candle_count,
        intelligence=intelligence,
        book=book,
    )
    return ContinuousPaperService(
        runtime=runtime,
        portfolio=portfolio,
        symbols=symbols,
        submit=submit,
        cycle_interval_seconds=cycle_seconds,
        on_result=on_result,
        on_portfolio=checkpoint_store.save,
    )


async def _main_async(args: argparse.Namespace) -> None:
    settings = Settings()
    checkpoint_store = JsonPortfolioCheckpointStore(Path(args.checkpoint_path))
    portfolio = await checkpoint_store.load()
    if portfolio is None:
        portfolio = InMemoryPortfolioBook(settings.paper_starting_nav_usd)

    sinks: list[ResultHandler] = [JsonlAuditSink(Path(args.audit_path))]
    postgres: PostgresRuntimeEventStore | None = None
    redis: RedisRuntimePublisher | None = None
    if args.persistent_events:
        postgres = PostgresRuntimeEventStore(settings.database_url)
        await postgres.initialize()
        redis = RedisRuntimePublisher(settings.redis_url)
        sinks.extend((postgres, redis))

    start_http_server(args.metrics_port)
    service = build_service(
        settings,
        submit=args.submit,
        cycle_seconds=args.cycle_seconds,
        portfolio=portfolio,
        on_result=FanoutResultSink(tuple(sinks)),
        checkpoint_store=checkpoint_store,
    )
    try:
        await service.run()
    finally:
        if postgres is not None:
            await postgres.close()
        if redis is not None:
            await redis.close()


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
