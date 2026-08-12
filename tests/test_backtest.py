from datetime import UTC, datetime, timedelta

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle


def make_trend(count: int = 90) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 1.0
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=previous,
                high=max(previous, close) * 1.001,
                low=min(previous, close) * 0.999,
                close=close,
                volume=1_000 + index,
            )
        )
        previous = close
    return tuple(candles)


def test_backtest_returns_metrics_and_counts_trades() -> None:
    metrics = BaselineBacktester().run(make_trend())
    assert metrics.ending_equity > 0
    assert metrics.trades >= 1
    assert metrics.max_drawdown >= 0
    assert metrics.benchmark_return > 0
