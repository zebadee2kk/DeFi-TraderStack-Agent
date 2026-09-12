import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from traderstack.agents.review import MetaAgentReview, MetaAgentReviewer
from traderstack.candles import Candle
from traderstack.execution.hummingbot import HummingbotOrderReceipt, HummingbotPaperExecutor
from traderstack.execution.shadow import ShadowIntent, ShadowRecorder
from traderstack.execution.submitter import IdempotentSubmitter
from traderstack.features import ResearchEdgeFeatures
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.book_ticker import (
    cross_venue_divergence_bps,
    record_cross_venue_divergence,
)
from traderstack.market.models import BookSnapshot, MarketTick, ReferencePrice
from traderstack.market.providers import (
    BookSnapshotProvider,
    BookTickerSnapshotProvider,
    CandleHistoryProvider,
    LiquidationSnapshotProvider,
    ReferencePriceProvider,
    VenueMarketDataProvider,
)
from traderstack.metrics import (  # --- observability (Epic 9) ---
    record_candles_loaded,
    record_event_sink_failure,
    record_paper_order_submitted,
    record_pipeline_result,
    record_shadow_intent,
    timed_provider_call,
)
from traderstack.models import PortfolioSnapshot, Side
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
    # --- execution hardening (Epic 8) ---
    # Why a submission did or did not happen, so refusals (duplicate decision,
    # planner rejection, uncertain venue state) land in the audit trail too.
    execution_status: str | None = None
    execution_reason: str | None = None
    # --- providers (Epic 2): order-book snapshot handling -----------------------
    book_snapshot: BookSnapshot | None = None
    book_error: str | None = None
    # --- paper-research edge data plane ---
    # Snapshot read failures are informational; they never fail the cycle.
    edge_error: str | None = None
    # --- shadow-live (Roadmap Phase 7) ------------------------------------------
    # Stamped on every cycle so paper and shadow audit lines are distinguishable
    # without inferring from the absence of a Hummingbot receipt.
    trading_mode: str = "paper"
    shadow_intent: ShadowIntent | None = None


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
    # --- execution hardening (Epic 8) ---
    # When wired, the submitter owns planning, idempotency and retry gating and
    # replaces the bare executor call below.
    submitter: IdempotentSubmitter | None = None
    # --- providers (Epic 2): order-book snapshot handling -----------------------
    # Optional; informational only today (not consumed by the risk plane yet).
    book: BookSnapshotProvider | None = None
    # --- paper-research edge data plane ---
    # In-process snapshot readers fed by background WS collectors. Research
    # context only — never an execution venue, never a risk-limit input.
    liquidations: LiquidationSnapshotProvider | None = None
    book_ticker: BookTickerSnapshotProvider | None = None
    # --- shadow-live (Roadmap Phase 7) ------------------------------------------
    # `shadow` records would-have-been orders through `shadow_recorder` and
    # never calls a venue. `paper` is the only mode that may submit.
    trading_mode: str = "paper"
    shadow_recorder: ShadowRecorder | None = None

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
                    # --- crucix fail-closed ---
                    # gather() itself should return provider_unavailable rather
                    # than raise for Crucix, but any unexpected raise still
                    # fails closed when fail-closed news is opted in.
                    if self.intelligence.fail_closed_news:
                        external = ExternalIntelligence(asset=asset, provider_unavailable=True)
                if (
                    external is not None
                    and external.provider_unavailable
                    and intelligence_error is None
                ):
                    intelligence_error = "intelligence_provider_unavailable"

            # --- providers (Epic 2): order-book snapshot handling -------------------
            book_snapshot: BookSnapshot | None = None
            book_error: str | None = None
            if self.book is not None:
                try:
                    book_snapshot = await self._next_book(symbol)
                except Exception as exc:  # noqa: BLE001 - book depth is informational; never blocks the cycle.
                    book_error = f"{type(exc).__name__}: {exc}"

            # --- paper-research edge data plane ---
            edge: ResearchEdgeFeatures | None = None
            edge_source_ids: tuple[str, ...] = ()
            edge_error: str | None = None
            if self.liquidations is not None or self.book_ticker is not None:
                try:
                    edge, edge_source_ids = self._edge_features(asset, tick)
                except Exception as exc:  # noqa: BLE001 - research context; never blocks the cycle.
                    edge_error = f"{type(exc).__name__}: {exc}"

            pipeline_result = self.pipeline.process(
                tick,
                prices,
                portfolio,
                candles=history,
                intelligence=external,
                edge=edge,
                edge_source_ids=edge_source_ids,
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
            # --- execution hardening (Epic 8) ---
            execution_status: str | None = None
            execution_reason: str | None = None
            shadow_intent: ShadowIntent | None = None
            if self.trading_mode == "shadow" and pipeline_result.paper_order is not None:
                # Shadow records the planned order and stops. submit=True is
                # ignored: there is no venue path in this mode.
                if self.shadow_recorder is None:
                    raise RuntimeError("shadow mode requires a shadow recorder")
                intent = pipeline_result.paper_order
                shadow_intent = await self.shadow_recorder.record(
                    intent,
                    execution_price_usd=tick.ask if intent.side is Side.BUY else tick.bid,
                    reference_price_usd=tick.last,
                )
                execution_status = shadow_intent.status
                execution_reason = shadow_intent.reason
                record_shadow_intent(symbol, intent.side.value, shadow_intent.status)
            elif submit and pipeline_result.paper_order is not None:
                if self.trading_mode != "paper":
                    raise RuntimeError("venue submission is only allowed in paper mode")
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
                if receipt is not None:
                    # observability (Epic 9): count the paper order as submitted once
                    # the venue accepted it.
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
                execution_status=execution_status,
                execution_reason=execution_reason,
                book_snapshot=book_snapshot,
                book_error=book_error,
                edge_error=edge_error,
                trading_mode=self.trading_mode,
                shadow_intent=shadow_intent,
            )

    async def _next_tick(self, symbol: str) -> MarketTick:
        # SEC-2026-09-17: do not derive the traded asset from a venue-authored
        # symbol. A tick for a different pair than we subscribed is rejected
        # here rather than trusted and later failing closed by accident.
        async for tick in self.venue.stream_ticks((symbol,)):
            if tick.symbol != symbol:
                raise RuntimeError(
                    f"venue tick symbol {tick.symbol!r} does not match requested {symbol!r}"
                )
            return tick
        raise RuntimeError("venue stream ended before producing a tick")

    def _edge_features(
        self, asset: str, tick: MarketTick
    ) -> tuple[ResearchEdgeFeatures | None, tuple[str, ...]]:
        """Read local liquidation / bookTicker snapshots. No network."""
        features = ResearchEdgeFeatures()
        source_ids: list[str] = []
        if self.liquidations is not None:
            snap = self.liquidations.snapshot(asset)
            if snap is not None:
                features = features.model_copy(
                    update={
                        "liq_notional_long_z": snap.liq_notional_long_z,
                        "liq_notional_short_z": snap.liq_notional_short_z,
                        "liq_count_long": snap.liq_count_long,
                        "liq_count_short": snap.liq_count_short,
                    }
                )
                source_ids.append(snap.source_id)
        if self.book_ticker is not None:
            ticker = self.book_ticker.latest(asset)
            if ticker is not None:
                divergence = cross_venue_divergence_bps(tick.mid, ticker.mid)
                features = features.model_copy(
                    update={
                        "cross_venue_mid_divergence_bps": divergence,
                        "cross_venue_mid_source": ticker.source.value,
                    }
                )
                record_cross_venue_divergence(asset, ticker.source.value, divergence)
                source_ids.append(f"book_ticker:{ticker.source.value}")
        if not source_ids:
            return (None, ())
        return (features, tuple(source_ids))

    async def _next_book(self, symbol: str) -> BookSnapshot:
        assert self.book is not None
        async for snapshot in self.book.stream_books((symbol,)):
            return snapshot
        raise RuntimeError("book stream ended before producing a snapshot")
