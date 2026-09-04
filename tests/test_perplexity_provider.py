import json

import httpx
import pytest

from traderstack.market.perplexity import PerplexityNewsProvider


@pytest.mark.asyncio
async def test_perplexity_news_provider_normalizes_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/agent"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "perplexity/sonar"
        assert len(body["input"]) == 1
        assert body["input"][0]["type"] == "message"
        assert body["input"][0]["role"] == "user"
        assert "BTC" in body["input"][0]["content"]
        assert "instructions" in body
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"]["required"] == [
            "event_score",
            "adverse_event",
            "item_count",
        ]
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "status": "completed",
                "model": "perplexity/sonar",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "event_score": 0.72,
                                        "adverse_event": True,
                                        "item_count": 4,
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.perplexity.ai"
    ) as client:
        snapshot = await PerplexityNewsProvider(api_key="test-key", client=client).fetch("btc")

    assert snapshot.asset == "BTC"
    assert snapshot.event_score == pytest.approx(0.72)
    assert snapshot.adverse_event is True
    assert snapshot.item_count == 4
    assert snapshot.source_id == "perplexity:perplexity/sonar"


@pytest.mark.asyncio
async def test_perplexity_news_provider_rejects_response_without_output_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": [{"type": "search_results", "results": []}]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.perplexity.ai"
    ) as client:
        with pytest.raises(TypeError, match="missing output text"):
            await PerplexityNewsProvider(api_key="test-key", client=client).fetch("eth")
