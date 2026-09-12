from datetime import UTC, datetime

import pytest

from traderstack.features import MarketFeatures
from traderstack.intelligence import NewsSnapshot, OnChainSnapshot, SocialSnapshot
from traderstack.intelligence_orchestrator import (
    PROVIDER_UNAVAILABLE_REASON,
    IntelligenceCache,
    IntelligenceOrchestrator,
)


@pytest.fixture
def market() -> MarketFeatures:
    return MarketFeatures(
        trend_4h=0.3,
        trend_1d=0.4,
        volatility_z=0.1,
        relative_volume=1.2,
        spread_bps=3.0,
    )


@pytest.mark.asyncio
async def test_orchestrator_merges_and_caches_external_features(market: MarketFeatures) -> None:
    calls = {"onchain": 0, "social": 0, "news": 0}

    async def onchain(asset: str) -> OnChainSnapshot:
        calls["onchain"] += 1
        return OnChainSnapshot(
            asset=asset,
            exchange_netflow_z=-1.2,
            large_wallet_accumulation=0.7,
            source_id="dune:test",
        )

    async def social(asset: str) -> SocialSnapshot:
        calls["social"] += 1
        return SocialSnapshot(
            asset=asset,
            sentiment=0.4,
            mention_velocity_z=1.8,
            source_id="lunar:test",
        )

    async def news(asset: str) -> NewsSnapshot:
        calls["news"] += 1
        return NewsSnapshot(
            asset=asset,
            event_score=0.6,
            adverse_event=False,
            item_count=2,
            source_id="news:test",
        )

    orchestrator = IntelligenceOrchestrator(
        onchain=onchain,
        social=social,
        news=(news,),
        cache=IntelligenceCache(max_age_seconds=300),
    )
    first = await orchestrator.build("btc", market)
    second = await orchestrator.build("BTC", market)

    assert first.onchain.large_wallet_accumulation == pytest.approx(0.7)
    assert first.narrative.mention_velocity_z == pytest.approx(1.8)
    assert first.news.event_score == pytest.approx(0.6)
    assert first.source_ids == ["dune:test", "lunar:test", "news:test"]
    assert second.source_ids == first.source_ids
    assert calls == {"onchain": 1, "social": 1, "news": 1}


@pytest.mark.asyncio
async def test_orchestrator_combines_news_and_isolates_provider_failure(
    market: MarketFeatures,
) -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("provider unavailable")

    async def adverse(asset: str) -> NewsSnapshot:
        return NewsSnapshot(
            asset=asset,
            observed_at=datetime.now(UTC),
            event_score=0.8,
            adverse_event=True,
            item_count=3,
            source_id="perplexity:test",
        )

    vector = await IntelligenceOrchestrator(news=(broken, adverse)).build("ETH", market)

    assert vector.news.event_score == pytest.approx(0.8)
    assert vector.news.adverse_event is True
    assert vector.source_ids == ["perplexity:test"]


@pytest.mark.asyncio
async def test_orchestrator_can_require_external_evidence(market: MarketFeatures) -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("provider unavailable")

    orchestrator = IntelligenceOrchestrator(news=(broken,), require_any_external=True)
    with pytest.raises(RuntimeError, match="all external intelligence providers unavailable"):
        await orchestrator.build("SOL", market)


@pytest.mark.asyncio
async def test_fail_closed_news_outage_marks_provider_unavailable(
    market: MarketFeatures,
) -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise TimeoutError("crucix timed out")

    orchestrator = IntelligenceOrchestrator(fail_closed_news=(broken,))
    bundle = await orchestrator.gather("BTC")
    assert bundle.provider_unavailable is True
    assert bundle.news is None
    assert bundle.is_empty
    vector = await orchestrator.build("BTC", market)
    assert vector.news.adverse_event is False
    assert PROVIDER_UNAVAILABLE_REASON == "intelligence_provider_unavailable"


@pytest.mark.asyncio
async def test_fail_closed_news_outage_still_merges_optional_news(
    market: MarketFeatures,
) -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("crucix down")

    async def optional(asset: str) -> NewsSnapshot:
        return NewsSnapshot(
            asset=asset,
            event_score=0.4,
            adverse_event=False,
            item_count=1,
            source_id="cryptopanic:test",
        )

    bundle = await IntelligenceOrchestrator(
        news=(optional,), fail_closed_news=(broken,)
    ).gather("ETH")
    assert bundle.provider_unavailable is True
    assert bundle.news is not None
    assert bundle.news.source_id == "cryptopanic:test"
    assert bundle.news.adverse_event is False


@pytest.mark.asyncio
async def test_optional_news_outage_does_not_mark_fail_closed() -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("cryptopanic down")

    async def crucix(asset: str) -> NewsSnapshot:
        return NewsSnapshot(
            asset=asset,
            event_score=0.1,
            adverse_event=False,
            item_count=0,
            source_id="crucix:alerts",
        )

    bundle = await IntelligenceOrchestrator(
        news=(broken,), fail_closed_news=(crucix,)
    ).gather("BTC")
    assert bundle.provider_unavailable is False
    assert bundle.news is not None
    assert bundle.news.source_id == "crucix:alerts"


@pytest.mark.asyncio
async def test_fail_closed_outage_is_not_cached() -> None:
    calls = {"n": 0}

    async def flaky(asset: str) -> NewsSnapshot:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("down")
        return NewsSnapshot(
            asset=asset,
            event_score=0.2,
            adverse_event=False,
            item_count=1,
            source_id="crucix:alerts",
        )

    orchestrator = IntelligenceOrchestrator(
        fail_closed_news=(flaky,), cache=IntelligenceCache(max_age_seconds=300)
    )
    first = await orchestrator.gather("BTC")
    assert first.provider_unavailable is True
    second = await orchestrator.gather("BTC")
    assert second.provider_unavailable is False
    assert second.news is not None
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_require_any_external_returns_unavailable_instead_of_raising() -> None:
    async def broken(asset: str) -> NewsSnapshot:
        raise RuntimeError("down")

    bundle = await IntelligenceOrchestrator(
        fail_closed_news=(broken,), require_any_external=True
    ).gather("SOL")
    assert bundle.provider_unavailable is True
    assert bundle.is_empty
