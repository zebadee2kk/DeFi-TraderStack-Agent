import asyncio
from dataclasses import dataclass

from pydantic import BaseModel

from traderstack.candles import Candle
from traderstack.execution.hummingbot import HummingbotOrderReceipt, HummingbotPaperExecutor
from traderstack.execution.submitter import IdempotentSubmitter
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.models import MarketTick, ReferencePrice
from traderstack.market.providers import (
    CandleHistoryProvider,
    ReferencePriceProvider,
    VenueMarketDataProvider,
)
from traderstack.models import PortfolioSnapshot, Side
from traderstack.pipeline import PipelineResult, VerticalSlicePipeline


class RuntimeResult(BaseModel):
    tick: MarketTick
    references: list[ReferencePrice]
    pipeline: PipelineResult
    candles_loaded: int = 0
    candle_error: str | None = None
    intelligence_sources: list[str] = []
    intelligence_error: str | None = None
    execution_receipt: HummingbotOrderReceipt | None = None
    # --- execution hardening (Epic 8) ---
    # Why a submission did or did not happen, so refusals (duplicate decision,
    # planner rejection, uncertain venue state) land in the audit trail too.
    execution_status: str | None = None
    execution_reason: str | None = None


@dataclass
class PaperRuntime:
    venue: VenueMarketDataProvider
    references: tuple[ReferencePriceProvider, ...]
    pipeline: VerticalSlicePipeline
    executor: HummingbotPaperExecutor | None = None
    candles: CandleHistoryProvider | None = None
    candle_interval: str = "1h"
    candle_count: int = 400
    # Candle history is keyed by base asset against this quote so the pre-trade
    # gate can backtest on deep CEX history even when the live tick comes from an
    # on-chain pool quoted in a stablecoin (e.g. ETH/USDG).
    candle_quote: str = "USD"
    intelligence: IntelligenceOrchestrator | None = None
    # --- execution hardening (Epic 8) ---
    # When wired, the submitter owns planning, idempotency and retry gating and
    # replaces the bare executor call below.
    submitter: IdempotentSubmitter | None = None

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

        history: tuple[Candle, ...] | None = None
        candle_error: str | None = None
        if self.candles is not None:
            try:
                history = await self.candles.fetch(
                    f"{asset}/{self.candle_quote}", self.candle_interval, count=self.candle_count
                )
            except Exception as exc:  # noqa: BLE001 - a failed history fetch fails closed downstream.
                candle_error = f"{type(exc).__name__}: {exc}"

        external: ExternalIntelligence | None = None
        intelligence_error: str | None = None
        if self.intelligence is not None:
            try:
                external = await self.intelligence.gather(asset)
            except Exception as exc:  # noqa: BLE001 - intelligence failure degrades to no-new-risk downstream.
                intelligence_error = f"{type(exc).__name__}: {exc}"

        pipeline_result = self.pipeline.process(
            tick, prices, portfolio, candles=history, intelligence=external
        )
        receipt = None
        # --- execution hardening (Epic 8) ---
        execution_status: str | None = None
        execution_reason: str | None = None
        if submit and pipeline_result.paper_order is not None:
            if self.submitter is not None:
                intent = pipeline_result.paper_order
                outcome = await self.submitter.submit(
                    intent,
                    # Cross the spread: the price actually payable is checked
                    # against the pipeline's validated last trade by the planner.
                    execution_price_usd=tick.ask if intent.side is Side.BUY else tick.bid,
                    reference_price_usd=tick.last,
                )
                receipt = outcome.receipt
                execution_status = outcome.status.value
                execution_reason = outcome.reason
            elif self.executor is None:
                raise RuntimeError("paper execution requested without an executor")
            else:
                receipt = await self.executor.submit(
                    pipeline_result.paper_order,
                    execution_price_usd=tick.last,
                    trading_mode="paper",
                )

        return RuntimeResult(
            tick=tick,
            references=prices,
            pipeline=pipeline_result,
            candles_loaded=len(history) if history else 0,
            candle_error=candle_error,
            intelligence_sources=external.source_ids if external is not None else [],
            intelligence_error=intelligence_error,
            execution_receipt=receipt,
            execution_status=execution_status,
            execution_reason=execution_reason,
        )

    async def _next_tick(self, symbol: str) -> MarketTick:
        async for tick in self.venue.stream_ticks((symbol,)):
            return tick
        raise RuntimeError("venue stream ended before producing a tick")
