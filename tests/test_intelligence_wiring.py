from collections.abc import AsyncIterator

import pytest

from traderstack.cli import build_intelligence, parse_dune_query_ids
from traderstack.config import Settings
from traderstack.intelligence import NewsSnapshot, OnChainSnapshot, SocialSnapshot
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN, symbol="BTC/USD", bid=999.5, ask=1000.5, last=1000
    )


def references() -> list[ReferencePrice]:
    return [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1000)]


def pipeline(**overrides: object) -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False)), **overrides)  # type: ignore[arg-type]


def bundle(*, adverse: bool = False) -> ExternalIntelligence:
    return ExternalIntelligence(
        asset="BTC",
        onchain=OnChainSnapshot(
            asset="BTC", exchange_netflow_z=-1.1, large_wallet_accumulation=0.6, source_id="dune:q1"
        ),
        social=SocialSnapshot(
            asset="BTC", sentiment=0.3, mention_velocity_z=1.2, source_id="lunarcrush:test"
        ),
        news=NewsSnapshot(
            asset="BTC",
            event_score=0.7,
            adverse_event=adverse,
            item_count=4,
            source_id="cryptopanic:test",
        ),
    )


# --- orchestrator.gather -------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_returns_bundle_and_isolates_failures() -> None:
    async def onchain(asset: str) -> OnChainSnapshot:
        raise RuntimeError("dune down")

    async def social(asset: str) -> SocialSnapshot:
        return SocialSnapshot(asset=asset, sentiment=0.2, source_id="lunar:test")

    result = await IntelligenceOrchestrator(onchain=onchain, social=social).gather("btc")
    assert result.asset == "BTC"
    assert result.onchain is None
    assert result.social is not None and result.social.sentiment == pytest.approx(0.2)
    assert result.source_ids == ["lunar:test"]
    assert not result.is_empty


@pytest.mark.asyncio
async def test_gather_raises_when_required_and_everything_fails() -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="all external intelligence providers unavailable"):
        await IntelligenceOrchestrator(news=(broken,), require_any_external=True).gather("BTC")


# --- pipeline ------------------------------------------------------------------


def test_pipeline_merges_intelligence_into_feature_vector() -> None:
    result = pipeline().process(tick(), references(), portfolio(), intelligence=bundle())
    assert result.feature_vector is not None
    vector = result.feature_vector
    assert vector.onchain.large_wallet_accumulation == pytest.approx(0.6)
    assert vector.narrative.sentiment == pytest.approx(0.3)
    assert vector.news.event_score == pytest.approx(0.7)
    assert vector.source_ids == [
        "kraken",
        "coingecko",
        "dune:q1",
        "lunarcrush:test",
        "cryptopanic:test",
    ]
    assert result.paper_order is not None


def test_pipeline_blocks_new_risk_on_adverse_news() -> None:
    result = pipeline().process(
        tick(), references(), portfolio(), intelligence=bundle(adverse=True)
    )
    assert result.accepted_market_data is True
    assert result.rejection_reasons == ["adverse_news_event"]
    assert result.proposal is None and result.paper_order is None
    assert result.feature_vector is not None and result.feature_vector.news.adverse_event is True


def test_pipeline_adverse_news_block_can_be_disabled_by_config() -> None:
    result = pipeline(block_on_adverse_news=False).process(
        tick(), references(), portfolio(), intelligence=bundle(adverse=True)
    )
    assert result.paper_order is not None


def test_pipeline_can_require_external_intelligence() -> None:
    strict = pipeline(require_external_intelligence=True)
    assert strict.process(tick(), references(), portfolio()).rejection_reasons == [
        "no_external_intelligence"
    ]
    empty = ExternalIntelligence(asset="BTC")
    assert strict.process(
        tick(), references(), portfolio(), intelligence=empty
    ).rejection_reasons == ["no_external_intelligence"]
    assert (
        strict.process(tick(), references(), portfolio(), intelligence=bundle()).paper_order
        is not None
    )


def test_pipeline_ignores_intelligence_for_a_different_asset() -> None:
    wrong = ExternalIntelligence(
        asset="ETH",
        news=NewsSnapshot(
            asset="ETH", event_score=0.9, adverse_event=True, item_count=1, source_id="x"
        ),
    )
    result = pipeline().process(tick(), references(), portfolio(), intelligence=wrong)
    assert result.paper_order is not None
    assert result.feature_vector is not None and result.feature_vector.news.adverse_event is False


# --- runtime -------------------------------------------------------------------


class FakeVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN, symbol=symbols[0], bid=99.95, ask=100.05, last=100
        )


class GoodReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100)]


@pytest.mark.asyncio
async def test_runtime_gathers_intelligence_each_cycle() -> None:
    async def news(asset: str) -> NewsSnapshot:
        return NewsSnapshot(
            asset=asset, event_score=0.5, adverse_event=False, item_count=2, source_id="news:test"
        )

    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=pipeline(),
        intelligence=IntelligenceOrchestrator(news=(news,)),
    )
    result = await runtime.run_once("BTC/USD", portfolio())
    assert result.intelligence_sources == ["news:test"]
    assert result.intelligence_error is None
    assert result.pipeline.feature_vector is not None
    assert result.pipeline.feature_vector.news.event_score == pytest.approx(0.5)
    assert result.pipeline.paper_order is not None


@pytest.mark.asyncio
async def test_runtime_records_intelligence_failure_and_fails_closed_when_required() -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("down")

    runtime = PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=pipeline(require_external_intelligence=True),
        intelligence=IntelligenceOrchestrator(news=(broken,), require_any_external=True),
    )
    result = await runtime.run_once("BTC/USD", portfolio())
    assert result.intelligence_error is not None and "unavailable" in result.intelligence_error
    assert result.pipeline.rejection_reasons == ["no_external_intelligence"]
    assert result.pipeline.paper_order is None


# --- settings → providers -----------------------------------------------------


def test_parse_dune_query_ids() -> None:
    assert parse_dune_query_ids("btc:123, ETH:456") == {"BTC": 123, "ETH": 456}
    assert parse_dune_query_ids("") == {}
    with pytest.raises(RuntimeError, match="malformed"):
        parse_dune_query_ids("BTC:abc")


def test_build_intelligence_returns_none_without_credentials() -> None:
    assert build_intelligence(Settings()) is None


def test_build_intelligence_assembles_configured_providers() -> None:
    orchestrator = build_intelligence(
        Settings(
            dune_api_key="d",
            dune_query_ids="BTC:1",
            lunarcrush_api_key="l",
            cryptopanic_api_key="c",
            perplexity_api_key="p",
            intelligence_cache_seconds=42,
            intelligence_required=True,
        )
    )
    assert orchestrator is not None
    assert orchestrator.onchain is not None
    assert orchestrator.social is not None
    assert len(orchestrator.news) == 2
    assert orchestrator.cache.max_age_seconds == 42
    assert orchestrator.require_any_external is True


def test_build_intelligence_skips_dune_without_query_ids() -> None:
    orchestrator = build_intelligence(Settings(dune_api_key="d", cryptopanic_api_key="c"))
    assert orchestrator is not None
    assert orchestrator.onchain is None
    assert len(orchestrator.news) == 1
