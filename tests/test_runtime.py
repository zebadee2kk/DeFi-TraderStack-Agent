from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from traderstack.config import Settings
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime


class FakeVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN,
            symbol=symbols[0],
            observed_at=datetime.now(UTC),
            bid=99.95,
            ask=100.05,
            last=100,
        )


class GoodReference:
    def __init__(self, source: MarketSource, price: float = 100) -> None:
        self.source = source
        self.price = price

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=self.source, asset=assets[0], price=self.price)]


class BrokenReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        raise RuntimeError("provider unavailable")


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=10_000,
        daily_pnl_usd=0,
        peak_nav_usd=10_000,
    )


def pipeline() -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False)))


@pytest.mark.asyncio
async def test_runtime_tolerates_one_failed_reference_provider() -> None:
    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(MarketSource.COINGECKO), BrokenReference()),
        pipeline=pipeline(),
    )
    result = await runtime.run_once("BTC/USD", portfolio())
    assert result.pipeline.accepted_market_data is True
    assert result.pipeline.paper_order is not None
    assert result.execution_receipt is None
    assert len(result.references) == 1


@pytest.mark.asyncio
async def test_runtime_fails_closed_when_all_references_fail() -> None:
    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(BrokenReference(),),
        pipeline=pipeline(),
    )
    result = await runtime.run_once("BTC/USD", portfolio())
    assert result.pipeline.accepted_market_data is False
    assert "no_independent_reference_price" in result.pipeline.rejection_reasons
    assert result.execution_receipt is None


@pytest.mark.asyncio
async def test_runtime_only_submits_when_explicitly_requested() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201,
            json={
                "order_id": "paper-1",
                "account_name": "paper_account",
                "connector_name": "kraken_paper_trade",
                "trading_pair": "BTC-USD",
                "trade_type": "BUY",
                "amount": 1.0,
                "order_type": "MARKET",
                "price": None,
                "status": "submitted",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        executor = HummingbotPaperExecutor("http://hummingbot", "user", "pass", client=client)
        runtime = PaperRuntime(
            venue=FakeVenue(),
            references=(GoodReference(MarketSource.COINGECKO),),
            pipeline=pipeline(),
            executor=executor,
        )
        preview = await runtime.run_once("BTC/USD", portfolio(), submit=False)
        submitted = await runtime.run_once("BTC/USD", portfolio(), submit=True)

    assert preview.execution_receipt is None
    assert submitted.execution_receipt is not None
    assert calls == 1
