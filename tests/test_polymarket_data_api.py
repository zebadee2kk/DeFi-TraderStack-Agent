from __future__ import annotations

import httpx
import pytest

from traderstack.polymarket.data_api import PolymarketDataClient, wallet_from_leaderboard_row


def test_wallet_from_leaderboard_row_accepts_current_field_spellings() -> None:
    wallet = "0x" + "ab" * 20
    assert wallet_from_leaderboard_row({"proxyWallet": wallet}) == wallet
    assert (
        wallet_from_leaderboard_row({"proxy_wallet": wallet.upper().replace("0X", "0x")}) == wallet
    )


@pytest.mark.asyncio
async def test_leaderboard_uses_v2_without_retired_offset() -> None:
    wallet = "0x" + "56" * 20
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"rank": 1, "proxy_wallet": wallet, "pnl": 42}],
                "pagination": {"next_cursor": None, "has_more": False},
            },
        )

    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        rows = await PolymarketDataClient(client=http).leaderboard(
            category="CRYPTO",
            time_period="MONTH",
            limit=10,
        )

    assert rows[0]["proxy_wallet"] == wallet
    assert seen[0].url.path == "/v2/leaderboard"
    assert seen[0].url.params["category"] == "CRYPTO"
    assert seen[0].url.params["timePeriod"] == "MONTH"
    assert "offset" not in seen[0].url.params


@pytest.mark.asyncio
async def test_positions_follow_cursor_with_wallet_anchor() -> None:
    wallet = "0x" + "12" * 20
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"condition_id": "one"}],
                    "pagination": {"next_cursor": "cursor-1", "has_more": True},
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [{"condition_id": "two"}],
                "pagination": {"next_cursor": None, "has_more": False},
            },
        )

    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = PolymarketDataClient(client=http)
        rows = await client.positions(wallet, status="CLOSED", max_pages=3, page_size=10)

    assert [row["condition_id"] for row in rows] == ["one", "two"]
    assert requests[0].url.params["user"] == wallet
    assert requests[0].url.params["status"] == "CLOSED"
    assert requests[1].url.params["user"] == wallet
    assert requests[1].url.params["cursor"] == "cursor-1"
    assert "offset" not in requests[1].url.params


@pytest.mark.asyncio
async def test_data_api_retries_retry_after_for_503(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": "0"}, json={"error": "busy"})
        return httpx.Response(200, json={"data": {"proxy_wallet": "0x" + "34" * 20, "value": 1}})

    async def fake_sleep(value: float) -> None:
        sleeps.append(value)

    monkeypatch.setattr("traderstack.polymarket.data_api.asyncio.sleep", fake_sleep)
    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = PolymarketDataClient(client=http)
        value = await client.value("0x" + "34" * 20)

    assert value["value"] == 1
    assert calls == 2
    assert sleeps == [0.0]


@pytest.mark.asyncio
async def test_price_as_of_preserves_resolution_and_refuses_future_point() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"timestamp": 100, "price": 0.4, "resolution_seconds": 60},
                    {"timestamp": 110, "price": 0.5, "resolution_seconds": 60},
                    {"timestamp": 121, "price": 0.9, "resolution_seconds": 60},
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = PolymarketDataClient(client=http)
        point = await client.price_as_of("token-1", 120)

    assert point is not None
    assert point.timestamp == 110
    assert point.price == 0.5
    assert point.resolution_seconds == 60
    assert seen[0].url.path == "/v2/prices-history"
    assert seen[0].url.params["token_id"] == "token-1"
    assert seen[0].url.params["as_of"] == "120"


def test_wallet_from_leaderboard_row_accepts_v2_user_id() -> None:
    wallet = "0x" + "ab" * 20
    assert wallet_from_leaderboard_row({"user_id": wallet}) == wallet
