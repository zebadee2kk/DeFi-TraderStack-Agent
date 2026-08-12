import json

import httpx
import pytest

from traderstack.agents.claude import AnthropicMetaAgentClient
from traderstack.agents.meta import EvidencePacket
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.models import Side
from traderstack.strategies import Regime, StrategySignal


def _packet() -> EvidencePacket:
    return EvidencePacket(
        asset="BTC",
        feature_vector=AssetFeatureVector(
            asset="BTC",
            market=MarketFeatures(
                trend_4h=0.4,
                trend_1d=0.6,
                volatility_z=0.2,
                relative_volume=1.4,
                spread_bps=4.0,
            ),
        ),
        strategy_signal=StrategySignal(
            strategy_id="baseline_ensemble_v1",
            symbol="BTC/USD",
            side=Side.BUY,
            score=0.7,
            confidence=0.65,
            regime=Regime.TRENDING_UP,
            rationale="baseline consensus",
        ),
        requested_notional_usd=500,
    )


@pytest.mark.asyncio
async def test_claude_client_parses_structured_decision() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/messages"
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "approve": True,
                                "confidence_delta": 0.05,
                                "rationale": "corroborated evidence",
                                "risk_flags": [],
                            }
                        ),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com"
    ) as client:
        decision = await AnthropicMetaAgentClient(api_key="test", client=client)(_packet())

    assert decision.approve is True
    assert decision.confidence_delta == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_claude_client_fails_closed_on_refusal() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"stop_reason": "refusal", "content": [{"type": "text", "text": "refused"}]},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com"
    ) as client:
        meta = AnthropicMetaAgentClient(api_key="test", client=client)
        with pytest.raises(RuntimeError, match="failed closed"):
            await meta(_packet())
