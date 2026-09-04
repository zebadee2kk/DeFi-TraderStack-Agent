import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from traderstack.agents.review import MetaAgentReview, MetaAgentReviewer
from traderstack.candles import Candle
from traderstack.execution.hummingbot import HummingbotOrderReceipt, HummingbotPaperExecutor
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.models import MarketTick, ReferencePrice
from traderstack.market.providers import (
    CandleHistoryProvider,
    ReferencePriceProvider,
    VenueMarketDataProvider,
)
from traderstack.metrics import (  # --- observability (Epic 9) ---
    record_candles_loaded,
    record_event_sink_failure,
    record_paper_order_submitted,
    record_pipeline_result,
    timed_provider_call,
)
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import PipelineResult, VerticalSlicePipeline
from traderstack.tracing import traced_call, traced_span  # observability (Epic 9)


class RuntimeResult(BaseModel):
    tick: MarketTick
    references: list[ReferencePrice]
    pipeline: PipelineResult
    candles_loaded: int = 0
    candle_error: str | None = None
    intelligence_sources: list[str] = []
    intelligence_error: str | None = None
    # --- meta-agent (Epic 6) ---
    meta_review: MetaAgentReview | None = None
    # --- end meta-agent (Epic 6) ---
    execution_receipt: HummingbotOrderReceipt | None = None


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
    # --- meta-agent (Epic 6) ---
    # Bounded LLM review between the deterministic pipeline and execution. It can
    # only withhold risk or adjust confidence; it never sizes or sides a trade.
    meta_reviewer: MetaAgentReviewer | None = None
    # --- end meta-agent (Epic 6) ---
    # --- persistence (Epic 2): optional hook, called with each freshly fetched
    # candle batch (e.g. PostgresCandleStore.append_many) when --persistent-events
    # is set. None disables candle persistence entirely (default).
    candle_sink: Callable[[tuple[Candle, ...]], Awaitable[None]] | None = None

    async def run_once(
        self,
        symbol: str,
        portfolio: PortfolioSnapshot,
        *,
        submit: bool = False,
    ) -> RuntimeResult:
        # --- observability (Epic 9): one trace span per cycle, symbol + decision_id ---
        with traced_span("paper_runtime.run_once", symbol=symbol) as _span:
            # --- end observability (Epic 9) ---
            tick = await self._next_tick(symbol)
            asset = symbol.split("/", 1)[0].upper()
            reference_batches = await asyncio.gather(
                *(
                    # --- observability (Epic 9): time + trace each reference fetch ---
                    timed_provider_call(
                        type(provider).__name__,
                        "reference_price",
                        traced_call(
                            "provider_fetch",
                            {
                                "provider": type(provider).__name__,
                                "kind": "reference_price",
                                "symbol": symbol,
                            },
                            provider.get_prices((asset,)),
                        ),
                    )
                    # --- end observability (Epic 9) ---
                    for provider in self.references
                ),
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
                    history = await timed_provider_call(  # observability (Epic 9)
                        type(self.candles).__name__,
                        "candle_history",
                        traced_call(
                            "provider_fetch",
                            {
                                "provider": type(self.candles).__name__,
                                "kind": "candle_history",
                                "symbol": symbol,
                            },
                            self.candles.fetch(
                                f"{asset}/{self.candle_quote}",
                                self.candle_interval,
                                count=self.candle_count,
                            ),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - a failed history fetch fails closed downstream.
                    candle_error = f"{type(exc).__name__}: {exc}"
            record_candles_loaded(symbol, len(history) if history else 0)  # observability (Epic 9)
            if history and self.candle_sink is not None:
                # --- persistence (Epic 2): best-effort candle persistence; a sink
                # failure must not fail the trading cycle itself.
                try:
                    await self.candle_sink(history)
                except Exception:  # noqa: BLE001 - persistence failure is non-fatal for the cycle.
                    record_event_sink_failure("candle_store")
                # --- end persistence (Epic 2) ---

            external: ExternalIntelligence | None = None
            intelligence_error: str | None = None
            if self.intelligence is not None:
                try:
                    external = await timed_provider_call(  # observability (Epic 9)
                        type(self.intelligence).__name__,
                        "intelligence",
                        traced_call(
                            "provider_fetch",
                            {
                                "provider": type(self.intelligence).__name__,
                                "kind": "intelligence",
                                "symbol": symbol,
                            },
                            self.intelligence.gather(asset),
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - intelligence failure degrades to no-new-risk downstream.
                    intelligence_error = f"{type(exc).__name__}: {exc}"

            pipeline_result = self.pipeline.process(
                tick, prices, portfolio, candles=history, intelligence=external
            )

            # --- meta-agent (Epic 6) ---
            meta_review: MetaAgentReview | None = None
            if self.meta_reviewer is not None:
                pipeline_result, meta_review = await self.meta_reviewer.run(
                    tick.symbol, pipeline_result
                )
            # --- end meta-agent (Epic 6) ---

            record_pipeline_result(symbol, pipeline_result)  # observability (Epic 9)
            if _span is not None and pipeline_result.proposal is not None:  # observability (Epic 9)
                _span.set_attribute("decision_id", str(pipeline_result.proposal.decision_id))
            receipt = None
            if submit and pipeline_result.paper_order is not None:
                if self.executor is None:
                    raise RuntimeError("paper execution requested without an executor")
                receipt = await self.executor.submit(
                    pipeline_result.paper_order,
                    execution_price_usd=tick.last,
                    trading_mode="paper",
                )
                # observability (Epic 9): count the paper order as submitted once the
                # executor call above succeeds without raising.
                record_paper_order_submitted(symbol, pipeline_result.paper_order.side.value)

            return RuntimeResult(
                tick=tick,
                references=prices,
                pipeline=pipeline_result,
                candles_loaded=len(history) if history else 0,
                candle_error=candle_error,
                intelligence_sources=external.source_ids if external is not None else [],
                intelligence_error=intelligence_error,
                meta_review=meta_review,
                execution_receipt=receipt,
            )

    async def _next_tick(self, symbol: str) -> MarketTick:
        async for tick in self.venue.stream_ticks((symbol,)):
            return tick
        raise RuntimeError("venue stream ended before producing a tick")
