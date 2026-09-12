from datetime import UTC, datetime

import httpx
import pytest

from traderstack.market.adapters import (
    CoinMarketCapPriceProvider,
    parse_coinmarketcap_quotes,
)
from traderstack.market.models import MarketSource


def test_parse_cmc_v3_list_data_and_list_quote() -> None:
    prices = parse_coinmarketcap_quotes(
        {
            "data": [
                {
                    "id": 1,
                    "symbol": "BTC",
                    "quote": [
                        {"symbol": "USD", "price": 63120.95},
                        {"symbol": "EUR", "price": 1.0},
                    ],
                },
                {
                    "id": 1027,
                    "symbol": "ETH",
                    "quote": [{"symbol": "USD", "price": 2400.0}],
                },
            ]
        },
        observed_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    by_asset = {item.asset: item.price for item in prices}
    assert by_asset == {"BTC": 63120.95, "ETH": 2400.0}
    assert all(item.source is MarketSource.COINMARKETCAP for item in prices)


def test_parse_cmc_legacy_dict_data_and_dict_quote() -> None:
    prices = parse_coinmarketcap_quotes(
        {
            "data": {
                "BTC": {"symbol": "BTC", "quote": {"USD": {"price": 100.0}}},
                "ETH": {"quote": {"USD": {"price": 50.0}}},
            }
        }
    )
    by_asset = {item.asset: item.price for item in prices}
    assert by_asset == {"BTC": 100.0, "ETH": 50.0}


def test_parse_cmc_dict_of_listing_lists() -> None:
    prices = parse_coinmarketcap_quotes(
        {
            "data": {
                "BTC": [
                    {"symbol": "BTC", "quote": [{"symbol": "USD", "price": 111.0}]},
                    {"symbol": "BTC", "quote": [{"symbol": "USD", "price": 999.0}]},
                ]
            }
        }
    )
    assert len(prices) == 1
    assert prices[0].asset == "BTC"
    assert prices[0].price == 111.0


def test_parse_cmc_skips_malformed_rows() -> None:
    prices = parse_coinmarketcap_quotes(
        {
            "data": [
                "not-a-row",
                {"symbol": "BTC", "quote": []},
                {"symbol": "ETH", "quote": {"USD": {"price": -1}}},
                {"symbol": "SOL", "quote": {"USD": {"price": 20}}},
            ]
        }
    )
    assert [item.asset for item in prices] == ["SOL"]


def test_parse_cmc_non_dict_payload_is_empty() -> None:
    assert parse_coinmarketcap_quotes(["nope"]) == []


@pytest.mark.asyncio
async def test_cmc_provider_parses_public_list_payload_without_a_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "X-CMC_PRO_API_KEY" not in request.headers
        assert request.url.path == "/public-api/v3/cryptocurrency/quotes/latest"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"symbol": "BTC", "quote": [{"symbol": "USD", "price": 42.0}]},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://pro-api.coinmarketcap.com", transport=transport
    ) as client:
        provider = CoinMarketCapPriceProvider(api_key=None, client=client)
        prices = await provider.get_prices(("BTC", "ETH"))

    assert len(prices) == 1
    assert prices[0].price == 42.0
