from datetime import UTC

import httpx
import pytest

from traderstack.research.kraken_charts import (
    chart_market_for,
    describe_ohlc_cap,
    download_kraken_charts,
)


def test_chart_market_maps_spot_symbols() -> None:
    assert chart_market_for("BTC/USD") == "PI_XBTUSD"
    assert chart_market_for("eth/usd") == "PI_ETHUSD"
    assert chart_market_for("SOL/USD") == "PI_SOLUSD"
    with pytest.raises(ValueError):
        chart_market_for("DOGE/USD")


def test_describe_ohlc_cap_mentions_720() -> None:
    note = describe_ohlc_cap(interval="1h", requested=4320, received=720)
    assert "720" in note
    assert "since" in note


@pytest.mark.asyncio
async def test_download_kraken_charts_drops_last_bar_and_parses_ms() -> None:
    rows = [
        {
            "time": 1_700_000_000_000 + index * 3_600_000,
            "open": str(100 + index),
            "high": str(100 + index + 1),
            "low": str(100 + index - 1),
            "close": str(100 + index),
            "volume": "0",
        }
        for index in range(5)
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/charts/v1/spot/PI_XBTUSD/1h" in str(request.url)
        assert request.url.params["count"] == "4"  # count+1
        return httpx.Response(200, json={"candles": rows})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://futures.kraken.com", transport=transport
    ) as client:
        candles = await download_kraken_charts("BTC/USD", "1h", count=3, client=client)

    assert len(candles) == 3
    assert candles[0].close == 101.0
    assert candles[-1].close == 103.0
    assert candles[0].symbol == "BTC/USD"
    assert candles[0].opened_at.tzinfo == UTC
