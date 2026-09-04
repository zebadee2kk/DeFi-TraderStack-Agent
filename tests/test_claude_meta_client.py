import json

import httpx
import pytest
from pydantic import ValidationError

from traderstack.agents.claude import (
    DEFAULT_META_AGENT_MODEL,
    META_AGENT_SCHEMA,
    AnthropicMetaAgentClient,
)
from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.agents.prompts import meta_agent_prompt
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


@pytest.mark.asyncio
async def test_claude_client_sends_the_registered_prompt_and_reports_usage() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        assert request.headers["x-api-key"] == "test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "model": "claude-haiku-4-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1200, "output_tokens": 90},
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "approve": False,
                                "confidence_delta": -0.05,
                                "rationale": "stale on-chain slice",
                                "risk_flags": ["stale_evidence"],
                            }
                        ),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com"
    ) as client:
        call = await AnthropicMetaAgentClient(api_key="test", client=client).review(_packet())

    assert seen["model"] == DEFAULT_META_AGENT_MODEL == "claude-haiku-4-5"
    assert seen["system"] == meta_agent_prompt().text
    assert seen["output_config"] == {
        "format": {"type": "json_schema", "schema": META_AGENT_SCHEMA}
    }
    assert call.decision.approve is False
    assert call.model == "claude-haiku-4-5"
    assert call.input_tokens == 1200
    assert call.output_tokens == 90
    assert call.total_tokens == 1290


@pytest.mark.asyncio
async def test_claude_client_fails_closed_on_truncated_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{"}]},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com"
    ) as client:
        with pytest.raises(RuntimeError, match="failed closed"):
            await AnthropicMetaAgentClient(api_key="test", client=client)(_packet())


@pytest.mark.asyncio
async def test_claude_client_fails_closed_on_an_out_of_range_confidence_delta() -> None:
    """The JSON schema cannot express numeric bounds, so the model can exceed them."""

    async def handler(request: httpx.Request) -> httpx.Response:
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
                                "confidence_delta": 0.75,
                                "rationale": "very confident",
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
        with pytest.raises(ValidationError):
            await AnthropicMetaAgentClient(api_key="test", client=client)(_packet())


@pytest.mark.asyncio
async def test_claude_client_fails_closed_on_unexpected_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
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
                                "rationale": "ok",
                                "risk_flags": [],
                                "override_notional_usd": 1_000_000,
                            }
                        ),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com"
    ) as client:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            await AnthropicMetaAgentClient(api_key="test", client=client)(_packet())


@pytest.mark.asyncio
async def test_claude_client_fails_closed_on_a_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "overloaded"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com"
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await AnthropicMetaAgentClient(api_key="test", client=client)(_packet())


def test_decision_schema_rejects_out_of_range_deltas_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MetaAgentDecision(approve=True, confidence_delta=0.16, rationale="too generous")
    with pytest.raises(ValidationError):
        MetaAgentDecision(approve=True, confidence_delta=-0.16, rationale="too harsh")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MetaAgentDecision.model_validate(
            {
                "approve": True,
                "confidence_delta": 0.0,
                "rationale": "ok",
                "side": "sell",
            }
        )
