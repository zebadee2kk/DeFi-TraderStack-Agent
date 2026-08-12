from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.market.kraken_candles import KrakenCandleProvider
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


@pytest.mark.asyncio
async def test_kraken_candle_provider_normalizes_and_orders() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/charts/v1/spot/BTCUSD/1h"
        return httpx.Response(
            200,
            json={
                "candles": [
                    {"time": 2, "open": "101", "high": "103", "low": "100", "close": "102", "volume": "12"},
                    {"time": 1, "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10"},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://futures.kraken.com", transport=transport) as client:
        provider = KrakenCandleProvider(client=client)
        candles = await provider.fetch("BTC/USD", "1h", count=2)

    assert [c.open for c in candles] == [100.0, 101.0]
    assert candles[0].symbol == "BTC/USD"


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
