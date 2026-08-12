import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from prometheus_client import start_http_server

from traderstack.agents.claude import AnthropicMetaAgentClient
from traderstack.agents.meta import ConstrainedMetaAgent
from traderstack.audit import JsonlAuditSink
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.config import Settings
from traderstack.eventing import FanoutResultSink, PostgresRuntimeEventStore, RedisRuntimePublisher
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.intelligence_orchestrator import (
    IntelligenceOrchestrator,
    NewsFetcher,
    SocialFetcher,
)
from traderstack.market.adapters import (
    CoinGeckoPriceProvider,
    CoinMarketCapPriceProvider,
    KrakenTickerProvider,
)
from traderstack.market.candle_feed import CandleFeed
from traderstack.market.intelligence_providers import (
    CryptoPanicNewsProvider,
    LunarCrushSocialProvider,
)
from traderstack.market.kraken_candles import KrakenCandleProvider
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime, RuntimeResult, SignalPaperRuntime, TradingRuntime
from traderstack.service import ContinuousPaperService
from traderstack.signal_pipeline import SignalPipeline

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]
PipelineMode = Literal["signal", "demo"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the guarded continuous paper trading service")
    parser.add_argument("--submit", action="store_true", help="submit approved paper orders")
    parser.add_argument("--audit-path", default="var/audit/runtime.jsonl")
    parser.add_argument("--checkpoint-path", default="var/state/portfolio.json")
    parser.add_argument("--cycle-seconds", type=float, default=5.0)
    parser.add_argument("--metrics-port", type=int, default=9108)
    parser.add_argument(
        "--pipeline",
        choices=("signal", "demo"),
        default="signal",
        help="signal: candle-driven strategy ensemble; demo: hardcoded vertical-slice proposal",
    )
    parser.add_argument(
        "--meta-agent",
        action="store_true",
        help="review consensus signals with the constrained Claude meta-agent (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--persistent-events",
        action="store_true",
        help="also persist runtime events to PostgreSQL and publish them to Redis",
    )
    return parser


def build_executor(settings: Settings, *, submit: bool) -> HummingbotPaperExecutor | None:
    if not submit:
        return None
    if settings.hummingbot_api_username is None or settings.hummingbot_api_password is None:
        raise RuntimeError("paper submission requires Hummingbot API credentials")
    return HummingbotPaperExecutor(
        base_url=settings.hummingbot_api_url,
        username=settings.hummingbot_api_username,
        password=settings.hummingbot_api_password.get_secret_value(),
        account_name=settings.hummingbot_account_name,
        connector_name=settings.hummingbot_connector_name,
    )


def build_intelligence(settings: Settings) -> IntelligenceOrchestrator | None:
    news: tuple[NewsFetcher, ...] = ()
    social: SocialFetcher | None = None
    if settings.cryptopanic_api_key is not None:
        provider = CryptoPanicNewsProvider(
            auth_token=settings.cryptopanic_api_key.get_secret_value()
        )
        news = (provider.fetch,)
    if settings.lunarcrush_api_key is not None:
        social = LunarCrushSocialProvider(
            api_key=settings.lunarcrush_api_key.get_secret_value()
        ).fetch
    if not news and social is None:
        return None
    return IntelligenceOrchestrator(social=social, news=news)


def build_meta_agent(settings: Settings) -> ConstrainedMetaAgent:
    if settings.anthropic_api_key is None:
        raise RuntimeError("meta-agent review requires ANTHROPIC_API_KEY")
    client = AnthropicMetaAgentClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.anthropic_model,
    )
    return ConstrainedMetaAgent(client=client)


def build_runtime(
    settings: Settings,
    *,
    pipeline_mode: PipelineMode,
    submit: bool,
    use_meta_agent: bool,
) -> TradingRuntime:
    executor = build_executor(settings, submit=submit)
    if pipeline_mode == "demo":
        return PaperRuntime(
            venue=KrakenTickerProvider(),
            references=(CoinGeckoPriceProvider(), CoinMarketCapPriceProvider()),
            pipeline=VerticalSlicePipeline(
                risk_engine=RiskEngine(settings),
                max_tick_age_seconds=settings.max_market_data_age_seconds,
                max_reference_divergence_bps=settings.max_reference_divergence_bps,
            ),
            executor=executor,
        )

    pipeline = SignalPipeline(
        risk_engine=RiskEngine(settings),
        intelligence=build_intelligence(settings),
        meta_agent=build_meta_agent(settings) if use_meta_agent else None,
        max_tick_age_seconds=settings.max_market_data_age_seconds,
        max_reference_divergence_bps=settings.max_reference_divergence_bps,
        base_notional_pct=settings.base_notional_pct,
        min_confidence=settings.min_consensus_confidence,
        min_order_notional_usd=settings.min_order_notional_usd,
        venue=settings.hummingbot_connector_name,
    )
    return SignalPaperRuntime(
        venue=KrakenTickerProvider(),
        references=(CoinGeckoPriceProvider(), CoinMarketCapPriceProvider()),
        candles=CandleFeed(
            fetcher=KrakenCandleProvider(),
            interval=settings.candle_interval,
            count=settings.candle_count,
            refresh_seconds=settings.candle_refresh_seconds,
        ),
        pipeline=pipeline,
        executor=executor,
    )


def build_service(
    settings: Settings,
    *,
    pipeline_mode: PipelineMode = "signal",
    submit: bool,
    use_meta_agent: bool = False,
    cycle_seconds: float,
    portfolio: InMemoryPortfolioBook,
    on_result: ResultHandler,
    checkpoint_store: JsonPortfolioCheckpointStore,
) -> ContinuousPaperService:
    if settings.trading_mode != "paper":
        raise RuntimeError("continuous paper service requires TRADING_MODE=paper")

    runtime = build_runtime(
        settings,
        pipeline_mode=pipeline_mode,
        submit=submit,
        use_meta_agent=use_meta_agent,
    )
    symbols = tuple(f"{asset}/USD" for asset in settings.assets)
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
        pipeline_mode=args.pipeline,
        submit=args.submit,
        use_meta_agent=args.meta_agent,
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
