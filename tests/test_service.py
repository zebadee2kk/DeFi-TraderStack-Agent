from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from traderstack.execution.hummingbot import HummingbotOrderReceipt
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def run_once(self, symbol, portfolio, *, submit=False):
        self.calls.append((symbol, submit))
        return self.result


@pytest.mark.asyncio
async def test_service_applies_execution_receipt_to_portfolio() -> None:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )
    order = PaperOrderIntent(
        decision_id="decision-1",
        asset="BTC",
        side=Side.BUY,
        notional_usd=1_000,
    )
    pipeline = PipelineResult(
        accepted_market_data=True,
        paper_order=order,
    )
    receipt = HummingbotOrderReceipt(
        order_id="paper-1",
        account_name="paper_account",
        connector_name="kraken_paper_trade",
        trading_pair="BTC-USD",
        trade_type="BUY",
        amount=0.05,
        order_type="MARKET",
        price=20_000,
        status="created",
    )
    result = RuntimeResult(
        tick=tick,
        references=[],
        pipeline=pipeline,
        execution_receipt=receipt,
    )
    runtime = FakeRuntime(result)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=True,
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    snapshot = book.snapshot()
    assert runtime.calls == [("BTC/USD", True)]
    assert snapshot.cash_usd == pytest.approx(9_000)
    assert snapshot.asset_exposure_usd["BTC"] == pytest.approx(1_000)


@pytest.mark.asyncio
async def test_service_marks_without_execution() -> None:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="ETH/USD",
        observed_at=datetime.now(UTC),
        bid=999,
        ask=1_001,
        last=1_000,
    )
    result = RuntimeResult(
        tick=tick,
        references=[],
        pipeline=PipelineResult(accepted_market_data=False),
    )
    runtime = FakeRuntime(result)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("ETH/USD",),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("ETH/USD")

    assert book.marks_usd["ETH"] == pytest.approx(1_000)
