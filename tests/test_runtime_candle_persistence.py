from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
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
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100)]


class FakeCandleProvider:
    def __init__(self, candles: tuple[Candle, ...]) -> None:
        self.candles = candles

    async def fetch(
        self, symbol: str, resolution: str = "1h", *, count: int = 250
    ) -> tuple[Candle, ...]:
        return self.candles


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def some_candles() -> tuple[Candle, ...]:
    return (
        Candle(
            symbol="BTC/USD",
            interval="1h",
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=10,
        ),
    )


@pytest.mark.asyncio
async def test_run_once_forwards_fetched_candles_to_candle_sink() -> None:
    received: list[tuple[Candle, ...]] = []

    async def sink(candles: tuple[Candle, ...]) -> None:
        received.append(candles)

    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False))),
        candles=FakeCandleProvider(some_candles()),
        candle_sink=sink,
    )

    result = await runtime.run_once("BTC/USD", portfolio())

    assert result.candle_error is None
    assert len(received) == 1
    assert received[0] == some_candles()


@pytest.mark.asyncio
async def test_run_once_tolerates_a_failing_candle_sink() -> None:
    async def broken_sink(candles: tuple[Candle, ...]) -> None:
        raise RuntimeError("db unavailable")

    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False))),
        candles=FakeCandleProvider(some_candles()),
        candle_sink=broken_sink,
    )

    result = await runtime.run_once("BTC/USD", portfolio())

    # A failing persistence sink must not fail the trading cycle.
    assert result.pipeline.accepted_market_data is True


@pytest.mark.asyncio
async def test_run_once_does_not_call_candle_sink_without_candle_provider() -> None:
    calls = 0

    async def sink(candles: tuple[Candle, ...]) -> None:
        nonlocal calls
        calls += 1

    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False))),
        candle_sink=sink,
    )

    await runtime.run_once("BTC/USD", portfolio())

    assert calls == 0
