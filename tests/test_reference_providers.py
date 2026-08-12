import httpx
import pytest

import traderstack.market.adapters
from traderstack.market.adapters import CoinGeckoPriceProvider, CoinMarketCapPriceProvider
from traderstack.market.models import MarketSource


async def test_coingecko_reuses_one_client_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"bitcoin": {"usd": 50_000.0}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CoinGeckoPriceProvider(client=client)
        # Any AsyncClient construction after injection means the provider is
        # not reusing the injected client.
        monkeypatch.setattr(
            traderstack.market.adapters.httpx,
            "AsyncClient",
            _forbid_client_construction,
        )
        first = await provider.get_prices(("BTC",))
        second = await provider.get_prices(("BTC",))
        await provider.aclose()

    assert requests == 2
    assert [price.price for price in first + second] == [50_000.0, 50_000.0]
    assert first[0].source is MarketSource.COINGECKO


async def test_coinmarketcap_owned_client_is_created_once_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={"data": {"BTC": {"quote": {"USD": {"price": 50_000.0}}}}},
        )

    created: list[httpx.AsyncClient] = []
    real_client = httpx.AsyncClient

    def tracking_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        client = real_client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    monkeypatch.setattr(traderstack.market.adapters.httpx, "AsyncClient", tracking_client)
    provider = CoinMarketCapPriceProvider()
    first = await provider.get_prices(("BTC",))
    second = await provider.get_prices(("BTC",))
    await provider.aclose()

    assert requests == 2
    assert len(created) == 1
    assert created[0].is_closed
    assert [price.price for price in first + second] == [50_000.0, 50_000.0]


def _forbid_client_construction(*args: object, **kwargs: object) -> httpx.AsyncClient:
    raise AssertionError("provider constructed a new httpx.AsyncClient instead of reusing one")
