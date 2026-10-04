from __future__ import annotations

from typing import Any

import httpx
import pytest

from traderstack.polymarket.data_api import PolymarketDataClient, wallet_from_leaderboard_row


def test_wallet_from_leaderboard_row_accepts_current_field_spellings() -> None:
    wallet = "0x" + "ab" * 20
    assert wallet_from_leaderboard_row({"proxyWallet": wallet}) == wallet
    assert wallet_from_leaderboard_row({"proxy_wallet": wallet.upper().replace("0X", "0x")}) == wallet


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
