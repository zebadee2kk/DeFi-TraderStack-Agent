from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.paper_perp_feed import PaperPerpVenueFeed
from traderstack.research.edge_series import (
    bitmex_current_mid_usd,
    htx_current_mid_usd,
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


def test_htx_mid_uses_bid_ask_not_mark_or_last() -> None:
    payload = {
        "status": "ok",
        "tick": {
            "bid": [77234.0, 1130],
            "ask": [77234.1, 7018],
            "close": 77000.0,
        },
    }
    assert htx_current_mid_usd(payload) == pytest.approx(77234.05)
    mark_only = {"status": "ok", "tick": {"close": 77000.0}}
    assert htx_current_mid_usd(mark_only) is None
    crossed = {"status": "ok", "tick": {"bid": [10.0, 1], "ask": [9.0, 1]}}
    assert htx_current_mid_usd(crossed) is None


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
async def test_feed_falls_back_to_htx_when_hyperliquid_mid_missing() -> None:
    async def hl_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_hl_payload(mid=None))

    async def htx_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "ok", "tick": {"bid": [77234.0, 1], "ask": [77234.1, 1]}},
        )

    hl_transport = httpx.MockTransport(hl_handler)
    htx_transport = httpx.MockTransport(htx_handler)
    async with (
        httpx.AsyncClient(base_url="https://api.hyperliquid.xyz", transport=hl_transport) as hl,
        httpx.AsyncClient(base_url="https://api.hbdm.com", transport=htx_transport) as htx,
    ):
        feed = PaperPerpVenueFeed(hyperliquid_client=hl, htx_client=htx, mid_cache_seconds=0)
        quote = await feed.fetch_mid("BTC/USD")
    assert quote is not None
    assert quote.venue == "htx"
    assert quote.mid_usd == pytest.approx(77234.05)
    assert "bid/ask" in quote.source
    assert "bitmex" not in quote.source


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
            base_url="https://api.hbdm.com",
            transport=httpx.MockTransport(bm_handler),
        ) as htx,
    ):
        feed = PaperPerpVenueFeed(hyperliquid_client=hl, htx_client=htx)
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


def test_feed_rejects_non_positive_timeouts() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PaperPerpVenueFeed(timeout_seconds=0)
    with pytest.raises(ValueError, match="funding_lookback"):
        PaperPerpVenueFeed(funding_lookback_hours=0)


@pytest.mark.asyncio
async def test_feed_respects_venue_preference_and_cache() -> None:
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json=[{"symbol": "XBTUSD", "midPrice": 77137.4, "markPrice": 77156.96}],
        )

    async with httpx.AsyncClient(
        base_url="https://www.bitmex.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        feed = PaperPerpVenueFeed(
            venue_preference="bitmex",
            bitmex_client=client,
            mid_cache_seconds=60,
        )
        first = await feed.fetch_mid("BTC/USD")
        second = await feed.fetch_mid("BTC/USD")
    assert first is not None and second is not None
    assert first.venue == "bitmex"
    assert first.mid_usd == second.mid_usd
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_feed_methods_refuse_if_mode_is_mutated() -> None:
    feed = PaperPerpVenueFeed()
    feed.trading_mode = "live"
    with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
        await feed.fetch_mid("BTC/USD")
    with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
        await feed.fetch_funding_since(
            "BTC/USD",
            venue="hyperliquid",
            since=datetime(2026, 9, 12, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_bitmex_funding_tape_uses_funding_rate_only() -> None:
    since = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "timestamp": "2026-09-12T08:00:00.000Z",
                    "fundingRate": 0.0001,
                    "fundingRateDaily": 0.0003,
                }
            ],
        )

    async with httpx.AsyncClient(
        base_url="https://www.bitmex.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        feed = PaperPerpVenueFeed(bitmex_client=client)
        tape = await feed.fetch_funding_since("BTC/USD", venue="bitmex", since=since)
    assert tape.venue == "bitmex"
    assert len(tape.settlements) == 1
    assert tape.settlements[0][1] == pytest.approx(0.0001)
    assert 0.0003 not in {rate for _ts, rate in tape.settlements}


@pytest.mark.asyncio
async def test_htx_funding_tape_uses_funding_rate_only() -> None:
    # The HTX fetcher keeps only rows inside its own ``now - lookback_days``
    # window, so the fixture must be dated relative to now: an absolute
    # timestamp here silently ages out of the window and the test fails on
    # the calendar, not on the code.
    now = datetime.now(UTC)
    since = now - timedelta(days=1)
    funding_time_ms = int((now - timedelta(hours=8)).timestamp() * 1000)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "data": {
                    "data": [
                        {
                            "funding_time": str(funding_time_ms),
                            "funding_rate": "0.0001",
                            "realized_rate": None,
                            "avg_premium_index": "0.01",
                        }
                    ]
                },
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.hbdm.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        feed = PaperPerpVenueFeed(htx_client=client)
        tape = await feed.fetch_funding_since("BTC/USD", venue="htx", since=since)
    assert tape.venue == "htx"
    assert len(tape.settlements) == 1
    assert tape.settlements[0][1] == pytest.approx(0.0001)
    assert 0.01 not in {rate for _ts, rate in tape.settlements}


@pytest.mark.asyncio
async def test_mid_http_error_is_a_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        transport=httpx.MockTransport(handler),
    ) as client:
        feed = PaperPerpVenueFeed(
            venue_preference="hyperliquid",
            hyperliquid_client=client,
        )
        assert await feed.fetch_mid("BTC/USD") is None
