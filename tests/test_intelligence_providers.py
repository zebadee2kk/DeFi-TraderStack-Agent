import httpx
import pytest

from traderstack.features import MarketFeatures
from traderstack.intelligence import merge_external_intelligence
from traderstack.market.intelligence_providers import (
    CryptoPanicNewsProvider,
    DuneOnChainProvider,
    LunarCrushSocialProvider,
)


@pytest.mark.asyncio
async def test_dune_provider_maps_configured_query_fields() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Dune-Api-Key"] == "secret"
        return httpx.Response(
            200,
            json={"result": {"rows": [{"exchange_netflow_z": -1.2, "large_wallet_accumulation": 0.7}]}},
        )

    async with httpx.AsyncClient(base_url="https://api.dune.com", transport=httpx.MockTransport(handler)) as client:
        provider = DuneOnChainProvider(api_key="secret", query_ids={"BTC": 123}, client=client)
        result = await provider.fetch("BTC")

    assert result.exchange_netflow_z == -1.2
    assert result.large_wallet_accumulation == 0.7
    assert result.source_id == "dune:query:123"


@pytest.mark.asyncio
async def test_lunarcrush_provider_normalizes_sentiment() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer lunar"
        return httpx.Response(200, json={"data": [{"symbol": "BTC", "sentiment": 75}]})

    async with httpx.AsyncClient(base_url="https://lunarcrush.com", transport=httpx.MockTransport(handler)) as client:
        provider = LunarCrushSocialProvider(api_key="lunar", client=client)
        result = await provider.fetch("BTC")

    assert result.sentiment == pytest.approx(0.5)
    assert result.mention_velocity_z is None


@pytest.mark.asyncio
async def test_cryptopanic_provider_derives_adverse_event() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["currencies"] == "BTC"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"votes": {"negative": 7, "positive": 3, "important": 4}},
                    {"votes": {"negative": 2, "positive": 1, "important": 1}},
                ]
            },
        )

    async with httpx.AsyncClient(base_url="https://cryptopanic.com", transport=httpx.MockTransport(handler)) as client:
        provider = CryptoPanicNewsProvider(auth_token="panic", client=client)
        result = await provider.fetch("BTC")

    assert result.adverse_event is True
    assert result.event_score == pytest.approx(0.4)
    assert result.item_count == 2


def test_external_intelligence_merges_into_feature_vector() -> None:
    market = MarketFeatures(
        trend_4h=0.2,
        trend_1d=0.3,
        volatility_z=0.05,
        relative_volume=1.2,
        spread_bps=3.0,
    )
    vector = merge_external_intelligence("BTC", market)
    assert vector.asset == "BTC"
    assert vector.market.relative_volume == 1.2
    assert vector.source_ids == []


async def test_cryptopanic_error_never_leaks_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthorized"})

    async with httpx.AsyncClient(
        base_url="https://cryptopanic.com", transport=httpx.MockTransport(handler)
    ) as client:
        provider = CryptoPanicNewsProvider(auth_token="SECRET-TOKEN-123", client=client)
        with pytest.raises(RuntimeError) as excinfo:
            await provider.fetch("BTC")

    assert "SECRET-TOKEN-123" not in str(excinfo.value)
    assert "auth_token" not in str(excinfo.value)
    assert "401" in str(excinfo.value)
