import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from prometheus_client import start_http_server

from traderstack.audit import JsonlAuditSink
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.config import Settings
from traderstack.eventing import FanoutResultSink, PostgresRuntimeEventStore, RedisRuntimePublisher
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.market.adapters import (
    CoinGeckoPriceProvider,
    CoinMarketCapPriceProvider,
    KrakenTickerProvider,
)
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime, RuntimeResult
from traderstack.service import ContinuousPaperService

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]


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

    pipeline = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        max_tick_age_seconds=settings.max_market_data_age_seconds,
        max_reference_divergence_bps=settings.max_reference_divergence_bps,
    )
    runtime = PaperRuntime(
        venue=KrakenTickerProvider(),
        references=(CoinGeckoPriceProvider(), CoinMarketCapPriceProvider()),
        pipeline=pipeline,
        executor=executor,
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
