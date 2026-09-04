import json

import httpx
import pytest

from traderstack.features import MarketFeatures
from traderstack.intelligence import AltFinsSignalSnapshot, merge_external_intelligence
from traderstack.market.altfins import AltFinsSignalProvider


def market() -> MarketFeatures:
    return MarketFeatures(
        trend_4h=0.1, trend_1d=0.1, volatility_z=0.0, relative_volume=1.0, spread_bps=2.0
    )


@pytest.mark.asyncio
async def test_altfins_provider_maps_bullish_bearish_ratio_to_bounded_score() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/public/signals-feed/search-requests"
        assert request.headers["X-API-KEY"] == "secret"
        body = json.loads(request.content)
        assert body["symbols"] == ["BTC"]
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "symbol": "BTC",
                        "signalKey": "SIGNALS_SUMMARY_SMA_50_200",
                        "signalName": "x",
                        "direction": "BULLISH",
                        "timestamp": "2026-09-04T00:00:00Z",
                    },
                    {
                        "symbol": "BTC",
                        "signalKey": "SIGNALS_SUMMARY_CHANNEL_UP",
                        "signalName": "y",
                        "direction": "BULLISH",
                        "timestamp": "2026-09-04T00:00:00Z",
                    },
                    {
                        "symbol": "BTC",
                        "signalKey": "SIGNALS_SUMMARY_RSI",
                        "signalName": "z",
                        "direction": "BEARISH",
                        "timestamp": "2026-09-04T00:00:00Z",
                    },
                ],
                "totalElements": 3,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://altfins.com"
    ) as client:
        snapshot = await AltFinsSignalProvider(api_key="secret", client=client).fetch("btc")

    assert snapshot.asset == "BTC"
    assert snapshot.score == pytest.approx(1 / 3)
    assert snapshot.source_id == "altfins:signals-feed"


@pytest.mark.asyncio
async def test_altfins_provider_returns_none_score_when_no_signals() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [], "totalElements": 0})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://altfins.com"
    ) as client:
        snapshot = await AltFinsSignalProvider(api_key="secret", client=client).fetch("eth")

    assert snapshot.score is None


def test_merge_external_intelligence_maps_altfins_onto_market_features() -> None:
    altfins = AltFinsSignalSnapshot(asset="BTC", score=0.5, source_id="altfins:signals-feed")
    vector = merge_external_intelligence("BTC", market(), altfins=altfins)

    assert vector.market.external_signal_score == pytest.approx(0.5)
    assert vector.market.external_signal_source == "altfins:signals-feed"
    assert "altfins:signals-feed" in vector.source_ids
    # Original MarketFeatures fields are untouched by the merge.
    assert vector.market.trend_4h == pytest.approx(0.1)


def test_merge_external_intelligence_without_altfins_leaves_new_fields_none() -> None:
    vector = merge_external_intelligence("BTC", market())
    assert vector.market.external_signal_score is None
    assert vector.market.external_signal_source is None
