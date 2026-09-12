from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.research.candidates import FeatureZVoter
from traderstack.research.edge_series import (
    fetch_binance_funding,
    fetch_binance_liquidations,
    fetch_bitmex_funding,
    fetch_bybit_funding,
    fetch_hyperliquid_funding,
    fetch_okx_funding,
)
from traderstack.strategies import Regime


@pytest.mark.asyncio
async def test_binance_funding_records_http_451_as_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(451, text="unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=transport
    ) as client:
        result = await fetch_binance_funding("BTC/USD", client=client)
    assert result.status == "skipped"
    assert "451" in result.reason


@pytest.mark.asyncio
async def test_binance_liquidations_skip_short_span() -> None:
    now = int(datetime(2026, 9, 12, tzinfo=UTC).timestamp() * 1000)

    async def handler(_request: httpx.Request) -> httpx.Response:
        rows = [
            {"time": now, "origQty": "1.0", "side": "SELL"},
            {"time": now + 3_600_000, "origQty": "2.0", "side": "BUY"},
        ]
        return httpx.Response(200, json=rows)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=transport
    ) as client:
        result = await fetch_binance_liquidations("BTC/USD", client=client)
    assert result.status == "skipped"
    assert "not a historical" in result.reason


@pytest.mark.asyncio
async def test_bybit_funding_records_http_403_as_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=(
                "The Amazon CloudFront distribution is configured to block access from your country"
            ),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.bybit.com", transport=transport) as client:
        result = await fetch_bybit_funding("BTC/USD", client=client)
    assert result.status == "skipped"
    assert "403" in result.reason
    assert "country" in result.reason.lower() or "CloudFront" in result.reason


@pytest.mark.asyncio
async def test_bybit_funding_parses_pages_when_reachable() -> None:
    pages = [
        {
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0003",
                        "fundingRateTimestamp": "2000000",
                    },
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0001",
                        "fundingRateTimestamp": "1000000",
                    },
                ]
            },
        },
        {"retCode": 0, "result": {"list": []}},
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.bybit.com", transport=transport) as client:
        result = await fetch_bybit_funding("BTC/USD", client=client, limit_pages=3)
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == 0.0001
    assert result.points[1][1] == 0.0003


@pytest.mark.asyncio
async def test_hyperliquid_funding_retries_http_429() -> None:
    pages = [
        httpx.Response(429, text="too many requests"),
        httpx.Response(
            200,
            json=[{"coin": "BTC", "fundingRate": "0.0004", "time": 1_000_000}],
        ),
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return pages[idx]

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", transport=transport
    ) as client:
        result = await fetch_hyperliquid_funding(
            "BTC/USD", client=client, start_ms=1, limit_pages=2
        )
    assert result.status == "ok"
    assert len(result.points) == 1
    assert result.points[0][1] == 0.0004
    assert calls["n"] >= 2


@pytest.mark.asyncio
async def test_hyperliquid_funding_parses_pages() -> None:
    pages = [
        [
            {"coin": "ETH", "fundingRate": "0.0001", "premium": "0.0", "time": 1_000_000},
            {"coin": "ETH", "fundingRate": "-0.0002", "premium": "0.0", "time": 2_000_000},
        ],
        [],
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", transport=transport
    ) as client:
        result = await fetch_hyperliquid_funding(
            "ETH/USD", client=client, start_ms=1, limit_pages=3
        )
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == 0.0001
    assert result.points[1][1] == -0.0002
    assert "fundingHistory" in result.source


@pytest.mark.asyncio
async def test_okx_funding_parses_pages() -> None:
    pages = [
        {
            "code": "0",
            "data": [
                {"fundingTime": "1789200000000", "fundingRate": "0.0001"},
                {"fundingTime": "1789171200000", "fundingRate": "-0.0002"},
            ],
        },
        {"code": "0", "data": []},
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.okx.com", transport=transport) as client:
        result = await fetch_okx_funding("ETH/USD", client=client)
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == -0.0002


@pytest.mark.asyncio
async def test_bitmex_funding_uses_settlement_not_daily_restatement() -> None:
    pages = [
        [
            {
                "timestamp": "2024-09-22T04:00:00.000Z",
                "symbol": "XBTUSD",
                "fundingInterval": "2000-01-01T08:00:00.000Z",
                "fundingRate": 0.0001,
                "fundingRateDaily": 0.0003,
            },
            {
                "timestamp": "2024-09-22T12:00:00.000Z",
                "symbol": "XBTUSD",
                "fundingInterval": "2000-01-01T08:00:00.000Z",
                "fundingRate": -0.0002,
                "fundingRateDaily": -0.0006,
            },
        ],
        [],
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.bitmex.com", transport=transport) as client:
        result = await fetch_bitmex_funding(
            "BTC/USD",
            client=client,
            start_iso="2024-09-22T00:00:00.000Z",
        )
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == 0.0001
    assert result.points[1][1] == -0.0002
    assert 0.0003 not in {point[1] for point in result.points}
    assert "fundingRateDaily" in result.reason
    assert "/api/v1/funding" in result.source


@pytest.mark.asyncio
async def test_bitmex_funding_records_http_error_as_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.bitmex.com", transport=transport) as client:
        result = await fetch_bitmex_funding("ETH/USD", client=client)
    assert result.status == "skipped"
    assert "403" in result.reason


def test_feature_z_voter_uses_per_symbol_series() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1h",
            opened_at=start + timedelta(hours=index),
            open=200.0 - 0.25 * index,
            high=201.0 - 0.25 * index,
            low=199.0 - 0.25 * index,
            close=200.0 - 0.25 * index,
            volume=1_000 + index,
        )
        for index in range(40)
    )
    btc = tuple((c.opened_at, 0.0 if index < 39 else 8.0) for index, c in enumerate(candles))
    eth = tuple((c.opened_at, 0.0 if index < 39 else -8.0) for index, c in enumerate(candles))
    voter = FeatureZVoter(
        strategy_id="funding_z_fade",
        feature_name="funding_z",
        values_by_symbol=(("BTC/USD", btc), ("ETH/USD", eth)),
        lookback=20,
        entry_z=1.5,
        fade=True,
    )
    btc_signal = voter.evaluate(candles, Regime.RANGE)
    eth_candles = tuple(c.model_copy(update={"symbol": "ETH/USD"}) for c in candles)
    eth_signal = voter.evaluate(eth_candles, Regime.RANGE)
    assert btc_signal.side is not None
    assert eth_signal.side is not None
    assert btc_signal.side != eth_signal.side
