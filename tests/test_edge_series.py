from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.research.candidates import FeatureZVoter
from traderstack.research.edge_series import (
    fetch_binance_funding,
    fetch_binance_liquidations,
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
