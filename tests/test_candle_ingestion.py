from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.market.kraken_candles import (
    KRAKEN_OHLC_PATH,
    KRAKEN_REST_BASE_URL,
    KrakenCandleProvider,
    parse_ohlc_payload,
    parse_ohlc_row,
)
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


def _ohlc_row(time: int, price: float) -> list[object]:
    return [time, f"{price}", f"{price + 1}", f"{price - 1}", f"{price}", f"{price}", "10.0", 5]


def test_parse_ohlc_row_reads_kraken_spot_columns() -> None:
    candle = parse_ohlc_row(_ohlc_row(1_700_000_000, 100.0), symbol="btc/usd", resolution="1h")
    assert candle.symbol == "BTC/USD"
    assert candle.interval == "1h"
    assert candle.opened_at == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert candle.open == 100.0
    assert candle.high == 101.0
    assert candle.low == 99.0
    assert candle.close == 100.0
    assert candle.volume == 10.0


def test_parse_ohlc_payload_rejects_kraken_error_array() -> None:
    with pytest.raises(RuntimeError, match="Unknown asset pair"):
        parse_ohlc_payload({"error": ["EQuery:Unknown asset pair"], "result": {}})


def test_parse_ohlc_payload_rejects_unexpected_shape() -> None:
    with pytest.raises(TypeError):
        parse_ohlc_payload(["not", "a", "dict"])
    with pytest.raises(TypeError):
        parse_ohlc_payload({"error": [], "result": {"last": 1}})


@pytest.mark.asyncio
async def test_kraken_candle_provider_uses_public_spot_ohlc() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.kraken.com"
        assert request.url.path == KRAKEN_OHLC_PATH
        assert request.url.params["pair"] == "BTCUSD"
        assert request.url.params["interval"] == "60"
        return httpx.Response(
            200,
            json={
                "error": [],
                "result": {
                    "XXBTZUSD": [
                        _ohlc_row(2, 101.0),
                        _ohlc_row(1, 100.0),
                        _ohlc_row(3, 102.0),
                    ],
                    "last": 3,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=KRAKEN_REST_BASE_URL, transport=transport) as client:
        provider = KrakenCandleProvider(client=client)
        candles = await provider.fetch("BTC/USD", "1h", count=10)

    # Sorted, trailing uncommitted bar dropped.
    assert [c.open for c in candles] == [100.0, 101.0]
    assert candles[0].symbol == "BTC/USD"
    assert candles[0].opened_at < candles[-1].opened_at


@pytest.mark.asyncio
async def test_kraken_candle_provider_caps_at_requested_count() -> None:
    rows = [_ohlc_row(index + 1, 100.0 + index) for index in range(6)]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": [], "result": {"BTCUSD": rows, "last": 6}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=KRAKEN_REST_BASE_URL, transport=transport) as client:
        candles = await KrakenCandleProvider(client=client).fetch("BTC/USD", "1h", count=2)

    # 6 rows minus the uncommitted last bar, then the newest `count`.
    assert [c.open for c in candles] == [103.0, 104.0]


@pytest.mark.asyncio
async def test_kraken_candle_provider_raises_on_kraken_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=KRAKEN_REST_BASE_URL, transport=transport) as client:
        with pytest.raises(RuntimeError, match="Kraken OHLC error"):
            await KrakenCandleProvider(client=client).fetch("BTC/USD", "1h", count=2)


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
