import asyncio
from dataclasses import dataclass

from pydantic import BaseModel

from traderstack.execution.hummingbot import HummingbotOrderReceipt, HummingbotPaperExecutor
from traderstack.market.models import MarketTick, ReferencePrice
from traderstack.market.providers import ReferencePriceProvider, VenueMarketDataProvider
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import PipelineResult, VerticalSlicePipeline


class RuntimeResult(BaseModel):
    tick: MarketTick
    references: list[ReferencePrice]
    pipeline: PipelineResult
    execution_receipt: HummingbotOrderReceipt | None = None


@dataclass
class PaperRuntime:
    venue: VenueMarketDataProvider
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
        tick = await self._next_tick(symbol)
        asset = symbol.split("/", 1)[0].upper()
        reference_batches = await asyncio.gather(
            *(provider.get_prices((asset,)) for provider in self.references),
            return_exceptions=True,
        )
        prices: list[ReferencePrice] = []
        for batch in reference_batches:
            if isinstance(batch, BaseException):
                continue
            prices.extend(batch)

        pipeline_result = self.pipeline.process(tick, prices, portfolio)
        receipt = None
        if submit and pipeline_result.paper_order is not None:
            if self.executor is None:
                raise RuntimeError("paper execution requested without an executor")
            receipt = await self.executor.submit(
                pipeline_result.paper_order,
                execution_price_usd=tick.last,
                trading_mode="paper",
            )

        return RuntimeResult(
            tick=tick,
            references=prices,
            pipeline=pipeline_result,
            execution_receipt=receipt,
        )

    async def _next_tick(self, symbol: str) -> MarketTick:
        async for tick in self.venue.stream_ticks((symbol,)):
            return tick
        raise RuntimeError("venue stream ended before producing a tick")
