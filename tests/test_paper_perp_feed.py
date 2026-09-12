from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.paper_perp_feed import PaperPerpVenueFeed
from traderstack.research.edge_series import (
    bitmex_current_mid_usd,
    hyperliquid_current_mid_usd,
)


def _hl_payload(*, mid: str | None = "77129.5", premium: str = "-0.0005") -> list[object]:
    ctx: dict[str, object] = {
        "markPx": "77130.0",
        "oraclePx": "77172.1",
        "premium": premium,
    }
    if mid is not None:
        ctx["midPx"] = mid
    return [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
        [ctx, {"markPx": "2524.3", "oraclePx": "2525.43", "premium": "-0.0004"}],
    ]


def test_hyperliquid_mid_uses_mid_px_not_mark_or_premium() -> None:
    mid = hyperliquid_current_mid_usd(_hl_payload(), "BTC")
    assert mid == pytest.approx(77129.5)
    missing = hyperliquid_current_mid_usd(_hl_payload(mid=None), "BTC")
    assert missing is None
    zero = hyperliquid_current_mid_usd(_hl_payload(mid="0"), "BTC")
    assert zero is None


def test_bitmex_mid_uses_mid_price_not_mark() -> None:
    rows = [
        {
            "symbol": "XBTUSD",
            "markPrice": 77156.96,
            "lastPrice": 77000.0,
            "midPrice": 77137.4,
        }
    ]
    assert bitmex_current_mid_usd(rows) == pytest.approx(77137.4)
    no_mid = [{"symbol": "XBTUSD", "markPrice": 77156.96, "lastPrice": 77000.0}]
    assert bitmex_current_mid_usd(no_mid) is None
    assert bitmex_current_mid_usd([]) is None


def test_feed_refuses_live_and_shadow() -> None:
    for mode in ("live", "shadow"):
        with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
            PaperPerpVenueFeed(trading_mode=mode)


@pytest.mark.asyncio
async def test_feed_prefers_hyperliquid_mid_and_skips_invented_fallback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/info"):
            return httpx.Response(200, json=_hl_payload())
        return httpx.Response(500, text="should not fall back")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", transport=transport
    ) as client:
        feed = PaperPerpVenueFeed(hyperliquid_client=client, bitmex_client=client)
        quote = await feed.fetch_mid("BTC/USD")
    assert quote is not None
    assert quote.venue == "hyperliquid"
    assert quote.mid_usd == pytest.approx(77129.5)
    assert quote.source.endswith("midPx")
    assert "premium" not in quote.source


@pytest.mark.asyncio
async def test_feed_falls_back_to_bitmex_when_hyperliquid_mid_missing() -> None:
    async def hl_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_hl_payload(mid=None))

    async def bm_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"symbol": "XBTUSD", "markPrice": 77156.96, "midPrice": 77137.4}],
        )

    hl_transport = httpx.MockTransport(hl_handler)
    bm_transport = httpx.MockTransport(bm_handler)
    async with (
        httpx.AsyncClient(base_url="https://api.hyperliquid.xyz", transport=hl_transport) as hl,
        httpx.AsyncClient(base_url="https://www.bitmex.com", transport=bm_transport) as bm,
    ):
        feed = PaperPerpVenueFeed(hyperliquid_client=hl, bitmex_client=bm, mid_cache_seconds=0)
        quote = await feed.fetch_mid("BTC/USD")
    assert quote is not None
    assert quote.venue == "bitmex"
    assert quote.mid_usd == pytest.approx(77137.4)
    assert quote.source.endswith("midPrice")


@pytest.mark.asyncio
async def test_feed_skips_when_both_venues_lack_a_mid() -> None:
    async def hl_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_hl_payload(mid=None))

    async def bm_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"symbol": "XBTUSD", "markPrice": 1.0}])

    async with (
        httpx.AsyncClient(
            base_url="https://api.hyperliquid.xyz",
            transport=httpx.MockTransport(hl_handler),
        ) as hl,
        httpx.AsyncClient(
            base_url="https://www.bitmex.com",
            transport=httpx.MockTransport(bm_handler),
        ) as bm,
    ):
        feed = PaperPerpVenueFeed(hyperliquid_client=hl, bitmex_client=bm)
        assert await feed.fetch_mid("BTC/USD") is None


@pytest.mark.asyncio
async def test_funding_tape_is_same_venue_and_filters_before_since() -> None:
    now = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
    older = now - timedelta(hours=3)
    newer = now + timedelta(hours=1)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"time": int(older.timestamp() * 1000), "fundingRate": "0.0001"},
                {"time": int(newer.timestamp() * 1000), "fundingRate": "0.0002"},
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        transport=httpx.MockTransport(handler),
    ) as client:
        feed = PaperPerpVenueFeed(hyperliquid_client=client)
        tape = await feed.fetch_funding_since("BTC/USD", venue="hyperliquid", since=now)
    assert tape.venue == "hyperliquid"
    assert len(tape.settlements) == 1
    assert tape.settlements[0][1] == pytest.approx(0.0002)
    assert tape.source.startswith("hyperliquid")
