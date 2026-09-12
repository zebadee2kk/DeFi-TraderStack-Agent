"""Crucix outage fail-closed cannot be relaxed into new risk.

When Crucix is opted in, a provider timeout/error blocks new risk with
``intelligence_provider_unavailable``. Edge features, a disabled adverse-news
gate, and the meta-agent must not authorise a paper order after that reject.
This is safety plumbing, not a trading edge.
"""

from collections.abc import AsyncIterator

import pytest

from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.agents.review import MetaAgentMode, MetaAgentReviewer
from traderstack.config import Settings
from traderstack.features import ResearchEdgeFeatures
from traderstack.intelligence import NewsSnapshot
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime


def _engine() -> RiskEngine:
    return RiskEngine(
        Settings(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            redis_url="redis://localhost:6379/0",
            kill_switch=False,
        )
    )


def _pipeline(**overrides: object) -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=_engine(), **overrides)  # type: ignore[arg-type]


def _tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN, symbol="BTC/USD", bid=999.5, ask=1000.5, last=1000
    )


def _refs() -> list[ReferencePrice]:
    return [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1000)]


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def test_crucix_outage_blocks_new_risk_and_leaves_notional_unset() -> None:
    result = _pipeline().process(
        _tick(),
        _refs(),
        _portfolio(),
        intelligence=ExternalIntelligence(asset="BTC", provider_unavailable=True),
    )
    assert result.rejection_reasons == ["intelligence_provider_unavailable"]
    assert result.proposal is None
    assert result.paper_order is None
    assert result.risk_result is None


def test_edge_features_cannot_clear_crucix_outage_reject() -> None:
    result = _pipeline().process(
        _tick(),
        _refs(),
        _portfolio(),
        intelligence=ExternalIntelligence(asset="BTC", provider_unavailable=True),
        edge=ResearchEdgeFeatures(
            liq_notional_long_z=5.0,
            liq_notional_short_z=-5.0,
            liq_count_long=1.0,
            liq_count_short=1.0,
        ),
        edge_source_ids=("liq:hostile",),
    )
    assert result.rejection_reasons == ["intelligence_provider_unavailable"]
    assert result.paper_order is None


def test_disabling_adverse_news_block_cannot_open_crucix_outage() -> None:
    result = _pipeline(block_on_adverse_news=False).process(
        _tick(),
        _refs(),
        _portfolio(),
        intelligence=ExternalIntelligence(asset="BTC", provider_unavailable=True),
    )
    assert result.rejection_reasons == ["intelligence_provider_unavailable"]
    assert result.paper_order is None


class _Venue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN, symbol=symbols[0], bid=99.95, ask=100.05, last=100
        )


class _Reference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100)]


@pytest.mark.asyncio
async def test_meta_agent_approval_cannot_authorise_after_crucix_outage() -> None:
    async def broken(_asset: str) -> NewsSnapshot:
        raise TimeoutError("crucix down")

    async def approve(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(
            approve=True, confidence_delta=0.15, rationale="authorise anyway", risk_flags=[]
        )

    runtime = PaperRuntime(
        venue=_Venue(),
        references=(_Reference(),),
        pipeline=_pipeline(),
        intelligence=IntelligenceOrchestrator(fail_closed_news=(broken,)),
        meta_reviewer=MetaAgentReviewer(client=approve, mode=MetaAgentMode.VETO),
    )
    result = await runtime.run_once("BTC/USD", _portfolio())
    assert result.pipeline.rejection_reasons == ["intelligence_provider_unavailable"]
    assert result.pipeline.paper_order is None
    assert result.pipeline.proposal is None
    assert result.execution_receipt is None
    if result.meta_review is not None:
        assert result.meta_review.called is False
