import pytest

from traderstack.agents.meta import ConstrainedMetaAgent, EvidencePacket, MetaAgentDecision
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.models import Side
from traderstack.strategies import Regime, StrategySignal


def packet(side: Side | None = Side.BUY, confidence: float = 0.7) -> EvidencePacket:
    vector = AssetFeatureVector(
        asset="BTC",
        market=MarketFeatures(
            trend_4h=0.4,
            trend_1d=0.3,
            volatility_z=0.05,
            relative_volume=1.4,
            spread_bps=3.0,
        ),
    )
    signal = StrategySignal(
        strategy_id="baseline_ensemble_v1",
        symbol="BTC/USD",
        side=side,
        score=0.6,
        confidence=confidence,
        regime=Regime.TRENDING_UP,
        rationale="baseline consensus",
    )
    return EvidencePacket(
        asset="BTC",
        feature_vector=vector,
        strategy_signal=signal,
        requested_notional_usd=500.0,
    )


@pytest.mark.asyncio
async def test_meta_agent_can_veto_without_trade_proposal() -> None:
    async def client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(
            approve=False,
            confidence_delta=-0.1,
            rationale="adverse news conflict",
            risk_flags=["news_conflict"],
        )

    result = await ConstrainedMetaAgent(client=client).propose(packet())
    assert result is None


@pytest.mark.asyncio
async def test_meta_agent_cannot_change_side_or_notional() -> None:
    async def client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(
            approve=True,
            confidence_delta=0.1,
            rationale="structured evidence supports baseline",
        )

    result = await ConstrainedMetaAgent(client=client).propose(packet(Side.SELL, 0.6))
    assert result is not None
    assert result.side is Side.SELL
    assert result.requested_notional_usd == 500.0
    assert result.confidence == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_meta_agent_does_nothing_without_baseline_signal() -> None:
    called = False

    async def client(_: EvidencePacket) -> MetaAgentDecision:
        nonlocal called
        called = True
        return MetaAgentDecision(approve=True, confidence_delta=0, rationale="unused")

    result = await ConstrainedMetaAgent(client=client).propose(packet(None))
    assert result is None
    assert called is False


async def test_confidence_nudge_scales_notional_down_never_up() -> None:
    async def nudging_client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(approve=True, confidence_delta=-0.1, rationale="weaker")

    evidence = packet()
    evidence = evidence.model_copy(update={"source_freshness_seconds": 3.5})
    result = await ConstrainedMetaAgent(client=nudging_client).propose(evidence)
    assert result is not None
    base = evidence.strategy_signal.confidence
    expected = evidence.requested_notional_usd * ((base - 0.1) / base)
    assert result.requested_notional_usd == pytest.approx(expected)
    assert result.source_freshness_seconds == pytest.approx(3.5)

    async def inflating_client(_: EvidencePacket) -> MetaAgentDecision:
        return MetaAgentDecision(approve=True, confidence_delta=0.15, rationale="stronger")

    inflated = await ConstrainedMetaAgent(client=inflating_client).propose(packet())
    assert inflated is not None
    assert inflated.requested_notional_usd <= packet().requested_notional_usd
