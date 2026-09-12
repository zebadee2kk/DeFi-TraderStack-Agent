from datetime import date

import httpx
import pytest

from traderstack.polymarket.cities import CITY_CATALOG
from traderstack.polymarket.clob import ClobPublicClient, assert_public_clob_path
from traderstack.polymarket.forecast import NoaaClient, OpenMeteoClient
from traderstack.polymarket.gamma import GammaClient


@pytest.mark.asyncio
async def test_gamma_lists_only_dict_events() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/events"
        assert request.url.params["tag_slug"] == "weather"
        assert request.url.params["closed"] == "false"
        return httpx.Response(200, json=[{"id": "e1", "markets": []}, "skip-me"])

    async with httpx.AsyncClient(
        base_url="https://gamma-api.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        events = await GammaClient(client=client).list_weather_events(tag_slug="weather", limit=10)

    assert events == ({"id": "e1", "markets": []},)


@pytest.mark.asyncio
async def test_clob_midpoint_is_get_only() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        assert request.url.path == "/midpoint"
        assert request.url.params["token_id"] == "tok"
        return httpx.Response(200, json={"mid": "0.42"})

    async with httpx.AsyncClient(
        base_url="https://clob.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        mid = await ClobPublicClient(client=client).midpoint("tok")

    assert mid == 0.42
    assert seen == ["GET"]


def test_clob_refuses_order_and_unknown_paths() -> None:
    with pytest.raises(RuntimeError, match="never signs"):
        assert_public_clob_path("/order")
    with pytest.raises(RuntimeError, match="refuses path"):
        assert_public_clob_path("/spread")


@pytest.mark.asyncio
async def test_open_meteo_reduces_daily_high() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["temperature_unit"] == "fahrenheit"
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-09-11", "2026-09-12"],
                    "temperature_2m_max": [88.0, 92.4],
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.open-meteo.com", transport=httpx.MockTransport(handler)
    ) as client:
        point = await OpenMeteoClient(client=client).daily_high(
            CITY_CATALOG["miami"], date(2026, 9, 12), sigma_f=2.5
        )

    assert point.high_f == 92.4
    assert point.source == "open_meteo"
    assert point.city_slug == "miami"


@pytest.mark.asyncio
async def test_noaa_follows_forecast_url_on_same_host() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "User-Agent" in request.headers
        if request.url.path.startswith("/points/"):
            return httpx.Response(
                200,
                json={
                    "properties": {
                        "forecast": "https://api.weather.gov/gridpoints/MFL/1,2/forecast"
                    }
                },
            )
        assert request.url.path == "/gridpoints/MFL/1,2/forecast"
        return httpx.Response(
            200,
            json={
                "properties": {
                    "periods": [
                        {
                            "startTime": "2026-09-12T06:00:00-04:00",
                            "isDaytime": True,
                            "temperature": 91,
                            "temperatureUnit": "F",
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.weather.gov", transport=httpx.MockTransport(handler)
    ) as client:
        point = await NoaaClient(client=client).daily_high(
            CITY_CATALOG["miami"], date(2026, 9, 12), sigma_f=2.5
        )

    assert point.high_f == 91.0
    assert point.source == "noaa"
