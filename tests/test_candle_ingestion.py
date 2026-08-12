from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.market.kraken_candles import KrakenCandleProvider, kraken_pair
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.walkforward import WalkForwardEvaluator


def make_candles(count: int, start_price: float = 100.0) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index in range(count):
        price = start_price * (1.0 + index * 0.002)
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price * 1.001,
                volume=100.0 + index,
            )
        )
    return tuple(candles)


def test_kraken_pair_mapping() -> None:
    assert kraken_pair("BTC/USD") == "XBTUSD"
    assert kraken_pair("eth/usd") == "ETHUSD"
    assert kraken_pair("SOL/USD") == "SOLUSD"
    with pytest.raises(ValueError):
        kraken_pair("BTCUSD")


# Row shape mirrors a real /0/public/OHLC response: second-resolution epochs,
# string OHLC values, canonical result key (XXBTZUSD) differing from the pair.
OHLC_RESPONSE = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            [1783933200, "101", "103", "100", "102", "101.5", "12", 906],
            [1783929600, "100", "102", "99", "101", "100.5", "10", 1490],
        ],
        "last": 1783933200,
    },
}


@pytest.mark.asyncio
async def test_kraken_candle_provider_normalizes_and_orders() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/0/public/OHLC"
        assert request.url.params["pair"] == "XBTUSD"
        assert request.url.params["interval"] == "60"
        return httpx.Response(200, json=OHLC_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        provider = KrakenCandleProvider(client=client)
        candles = await provider.fetch("BTC/USD", "1h", count=2)

    assert [c.open for c in candles] == [100.0, 101.0]
    assert candles[0].symbol == "BTC/USD"
    assert candles[0].opened_at == datetime.fromtimestamp(1783929600, tz=UTC)
    assert candles[0].volume == 10.0


@pytest.mark.asyncio
async def test_kraken_candle_provider_rejects_api_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        provider = KrakenCandleProvider(client=client)
        with pytest.raises(RuntimeError, match="Unknown asset pair"):
            await provider.fetch("BTC/USD")


@pytest.mark.asyncio
async def test_kraken_candle_provider_rejects_millisecond_timestamps() -> None:
    payload = {
        "error": [],
        "result": {"XXBTZUSD": [[1783933200000, "101", "103", "100", "102", "101.5", "12", 906]]},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        provider = KrakenCandleProvider(client=client)
        with pytest.raises(ValueError, match="implausible"):
            await provider.fetch("BTC/USD")


def test_market_feature_builder_uses_candle_history() -> None:
    features = CandleMarketFeatureBuilder().build(make_candles(30), spread_bps=4.0)
    assert features.trend_4h > 0
    assert features.trend_1d > 0
    assert features.relative_volume > 1
    assert features.spread_bps == 4.0


def test_walkforward_builds_multiple_holdout_folds() -> None:
    evaluator = WalkForwardEvaluator(train_size=80, test_size=40, step_size=40)
    report = evaluator.evaluate(make_candles(200))
    assert len(report.folds) == 3
    assert report.folds[0].train_end == report.folds[0].test_start
    assert report.worst_drawdown >= 0
