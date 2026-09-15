from datetime import date

import httpx
import pytest

from traderstack.market.registry import ProviderRegistry
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


# --- polymarket weather PIT tape (#141) ---


@pytest.mark.asyncio
async def test_book_top_reduces_unsorted_arrays_with_a_get() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/book"
        assert request.url.params["token_id"] == "tok"
        return httpx.Response(
            200,
            json={
                "bids": [
                    {"price": "0.30", "size": "10"},
                    {"price": "0.34", "size": "10"},
                    {"price": "0.28", "size": "10"},
                ],
                "asks": [
                    {"price": "0.44", "size": "10"},
                    {"price": "0.38", "size": "10"},
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url="https://clob.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        top = await ClobPublicClient(client=client).book_top("tok")

    assert top.best_bid == 0.34
    assert top.best_ask == 0.38
    assert top.mid == pytest.approx(0.36)
    assert top.half_spread == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_one_sided_book_raises_rather_than_inventing_a_mid() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bids": [], "asks": [{"price": "0.03", "size": "5"}]})

    async with httpx.AsyncClient(
        base_url="https://clob.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="one-sided"):
            await ClobPublicClient(client=client).book_top("tok")


@pytest.mark.asyncio
async def test_gamma_keyset_paging_propagates_the_cursor() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/events/keyset"
        seen.append(request.url.params.get("cursor", ""))
        if not request.url.params.get("cursor"):
            return httpx.Response(200, json={"events": [{"id": "e1"}], "next_cursor": "abc"})
        return httpx.Response(200, json={"events": [{"id": "e2"}], "next_cursor": None})

    async with httpx.AsyncClient(
        base_url="https://gamma-api.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        gamma = GammaClient(client=client)
        first, cursor = await gamma.list_weather_events_keyset(tag_slug="weather", limit=1)
        assert cursor == "abc"
        second, cursor = await gamma.list_weather_events_keyset(
            tag_slug="weather", limit=1, cursor=cursor
        )

    assert [row["id"] for row in first + second] == ["e1", "e2"]
    assert cursor is None
    assert seen == ["", "abc"]


@pytest.mark.asyncio
async def test_gamma_offset_paging_sends_order_and_offset() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/events"
        assert request.url.params["offset"] == "100"
        assert request.url.params["order"] == "id"
        assert request.url.params["ascending"] == "false"
        return httpx.Response(200, json=[{"id": "e3"}])

    async with httpx.AsyncClient(
        base_url="https://gamma-api.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        page = await GammaClient(client=client).list_weather_events_page(
            tag_slug="weather", limit=100, offset=100
        )
    assert [row["id"] for row in page] == ["e3"]


@pytest.mark.asyncio
async def test_open_meteo_model_parameter_is_sent_and_recorded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["models"] == "gfs_seamless"
        return httpx.Response(
            200,
            json={"daily": {"time": ["2026-09-14"], "temperature_2m_max": [88.2]}},
        )

    async with httpx.AsyncClient(
        base_url="https://api.open-meteo.com", transport=httpx.MockTransport(handler)
    ) as client:
        point = await OpenMeteoClient(client=client).daily_high(
            CITY_CATALOG["miami"], date(2026, 9, 14), sigma_f=2.5, model="gfs_seamless"
        )
    assert point.high_f == 88.2
    assert point.model == "gfs_seamless"


@pytest.mark.asyncio
async def test_open_meteo_best_match_sends_no_models_parameter() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "models" not in request.url.params
        return httpx.Response(
            200,
            json={"daily": {"time": ["2026-09-14"], "temperature_2m_max": [88.2]}},
        )

    async with httpx.AsyncClient(
        base_url="https://api.open-meteo.com", transport=httpx.MockTransport(handler)
    ) as client:
        point = await OpenMeteoClient(client=client).daily_high(
            CITY_CATALOG["miami"], date(2026, 9, 14), sigma_f=2.5
        )
    assert point.model == "best_match"


@pytest.mark.asyncio
async def test_one_sided_books_do_not_trip_the_provider_breaker() -> None:
    """A legitimately one-sided book is data, not a provider failure.

    Three out-of-the-money buckets in a row would otherwise open the
    circuit and silently skip the rest of a collection cycle (#141).
    """

    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["token_id"])
        if request.url.params["token_id"].startswith("dry"):
            return httpx.Response(200, json={"bids": [], "asks": [{"price": "0.03", "size": "1"}]})
        return httpx.Response(
            200,
            json={
                "bids": [{"price": "0.30", "size": "1"}],
                "asks": [{"price": "0.32", "size": "1"}],
            },
        )

    registry = ProviderRegistry(name="polymarket_clob", failure_threshold=3)
    async with httpx.AsyncClient(
        base_url="https://clob.polymarket.com", transport=httpx.MockTransport(handler)
    ) as client:
        clob = ClobPublicClient(client=client, registry=registry)
        for index in range(4):
            with pytest.raises(ValueError, match="one-sided"):
                await clob.book_top(f"dry-{index}")
        top = await clob.book_top("liquid")

    assert top.mid == pytest.approx(0.31)
    assert len(calls) == 5
