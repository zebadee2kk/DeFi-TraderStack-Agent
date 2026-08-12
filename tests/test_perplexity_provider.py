import json

import httpx
import pytest

from traderstack.market.perplexity import PerplexityNewsProvider


@pytest.mark.asyncio
async def test_perplexity_news_provider_normalizes_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sonar"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "event_score": 0.72,
                                    "adverse_event": True,
                                    "item_count": 4,
                                }
                            ),
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.perplexity.ai"
    ) as client:
        snapshot = await PerplexityNewsProvider(
            api_key="test-key", client=client
        ).fetch("btc")

    assert snapshot.asset == "BTC"
    assert snapshot.event_score == pytest.approx(0.72)
    assert snapshot.adverse_event is True
    assert snapshot.item_count == 4
    assert snapshot.source_id == "perplexity:sonar"
