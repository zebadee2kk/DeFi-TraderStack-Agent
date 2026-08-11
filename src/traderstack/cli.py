import argparse
import asyncio
from pathlib import Path

from traderstack.audit import JsonlAuditSink
from traderstack.config import Settings
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.market.adapters import (
    CoinGeckoPriceProvider,
    CoinMarketCapPriceProvider,
    KrakenTickerProvider,
)
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime
from traderstack.service import ContinuousPaperService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the guarded continuous paper trading service")
    parser.add_argument("--submit", action="store_true", help="submit approved paper orders")
    parser.add_argument("--audit-path", default="var/audit/runtime.jsonl")
    parser.add_argument("--cycle-seconds", type=float, default=5.0)
    return parser


def build_service(
    settings: Settings,
    *,
    submit: bool,
    audit_path: Path,
    cycle_seconds: float,
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
        references=(
            CoinGeckoPriceProvider(),
            CoinMarketCapPriceProvider(),
        ),
        pipeline=pipeline,
        executor=executor,
    )
    symbols = tuple(f"{asset}/USD" for asset in settings.assets)
    return ContinuousPaperService(
        runtime=runtime,
        portfolio=InMemoryPortfolioBook(settings.paper_starting_nav_usd),
        symbols=symbols,
        submit=submit,
        cycle_interval_seconds=cycle_seconds,
        on_result=JsonlAuditSink(audit_path),
    )


async def _main_async(args: argparse.Namespace) -> None:
    settings = Settings()
    service = build_service(
        settings,
        submit=args.submit,
        audit_path=Path(args.audit_path),
        cycle_seconds=args.cycle_seconds,
    )
    await service.run()


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
