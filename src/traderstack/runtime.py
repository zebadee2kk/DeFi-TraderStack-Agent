import asyncio
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from traderstack.execution.hummingbot import HummingbotOrderReceipt, HummingbotPaperExecutor
from traderstack.market.candle_feed import CandleFeed
from traderstack.market.models import MarketTick, ReferencePrice
from traderstack.market.providers import ReferencePriceProvider
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import PipelineResult, VerticalSlicePipeline
from traderstack.signal_pipeline import SignalPipeline


class RuntimeResult(BaseModel):
    tick: MarketTick
    references: list[ReferencePrice]
    pipeline: PipelineResult
    execution_receipt: HummingbotOrderReceipt | None = None


class TradingRuntime(Protocol):
    async def run_once(
        self,
        symbol: str,
        portfolio: PortfolioSnapshot,
        *,
        submit: bool = False,
    ) -> RuntimeResult: ...


class TickSource(Protocol):
    """Serves the most recent market tick for a symbol (e.g. PersistentTickerFeed)."""

    async def latest(self, symbol: str) -> MarketTick: ...


async def _gather_references(
    providers: tuple[ReferencePriceProvider, ...],
    asset: str,
) -> list[ReferencePrice]:
    batches = await asyncio.gather(
        *(provider.get_prices((asset,)) for provider in providers),
        return_exceptions=True,
    )
    prices: list[ReferencePrice] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue
        prices.extend(batch)
    return prices


async def _submit_if_approved(
    executor: HummingbotPaperExecutor | None,
    pipeline_result: PipelineResult,
    execution_price_usd: float,
    submit: bool,
) -> HummingbotOrderReceipt | None:
    if not submit or pipeline_result.paper_order is None:
        return None
    if executor is None:
        raise RuntimeError("paper execution requested without an executor")
    return await executor.submit(
        pipeline_result.paper_order,
        execution_price_usd=execution_price_usd,
        trading_mode="paper",
    )


@dataclass
class PaperRuntime:
    """Demo runtime driving the hardcoded vertical-slice pipeline."""

    ticks: TickSource
    references: tuple[ReferencePriceProvider, ...]
    pipeline: VerticalSlicePipeline
    executor: HummingbotPaperExecutor | None = None

    async def run_once(
        self,
        symbol: str,
        portfolio: PortfolioSnapshot,
        *,
        submit: bool = False,
    ) -> RuntimeResult:
        tick = await self.ticks.latest(symbol)
        asset = symbol.split("/", 1)[0].upper()
        prices = await _gather_references(self.references, asset)

        pipeline_result = self.pipeline.process(tick, prices, portfolio)
        receipt = await _submit_if_approved(self.executor, pipeline_result, tick.last, submit)

        return RuntimeResult(
            tick=tick,
            references=prices,
            pipeline=pipeline_result,
            execution_receipt=receipt,
        )


@dataclass
class SignalPaperRuntime:
    """Signal-driven runtime: candle history feeds the strategy ensemble."""

    ticks: TickSource
    references: tuple[ReferencePriceProvider, ...]
    candles: CandleFeed
    pipeline: SignalPipeline
    executor: HummingbotPaperExecutor | None = None

    async def run_once(
        self,
        symbol: str,
        portfolio: PortfolioSnapshot,
        *,
        submit: bool = False,
    ) -> RuntimeResult:
        tick = await self.ticks.latest(symbol)
        asset = symbol.split("/", 1)[0].upper()
        # CandleFeed already absorbs transient outages by serving its cache; if
        # it still raises, the history is truly unavailable and the error must
        # surface so RuntimeHealth records it instead of silently never trading.
        prices, candles = await asyncio.gather(
            _gather_references(self.references, asset),
            self.candles.get(symbol),
        )

        pipeline_result = await self.pipeline.process(tick, candles, prices, portfolio)
        receipt = await _submit_if_approved(self.executor, pipeline_result, tick.last, submit)

        return RuntimeResult(
            tick=tick,
            references=prices,
            pipeline=pipeline_result,
            execution_receipt=receipt,
        )
