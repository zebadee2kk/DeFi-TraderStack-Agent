from datetime import UTC, datetime, timedelta

import pytest

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


def make_series(
    changes: list[float],
    interval: str = "1d",
    start_price: float = 100.0,
) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    step = timedelta(days=1) if interval == "1d" else timedelta(hours=1)
    candles = []
    previous = start_price
    price = start_price
    for index, change in enumerate(changes):
        price = price * (1 + change)
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval=interval,
                opened_at=start + step * index,
                open=previous,
                high=max(previous, price) * 1.001,
                low=min(previous, price) * 0.999,
                close=price,
                volume=1_000,
            )
        )
        previous = price
    return tuple(candles)


def test_drawdown_sees_open_position_losses() -> None:
    # Ride a ramp into a crash: the old realized-only accounting reported
    # ~0.15% drawdown here because equity never marked while holding.
    changes = [0.02] * 50 + [-0.08] * 10 + [0.0] * 5
    metrics = BaselineBacktester().run(make_series(changes))
    assert metrics.max_drawdown > 0.3


def test_sharpe_annualization_scales_with_interval() -> None:
    changes = ([0.02] * 20 + [-0.01] * 5) * 3
    daily = BaselineBacktester().run(make_series(changes, interval="1d"))
    hourly = BaselineBacktester().run(make_series(changes, interval="1h"))
    assert daily.sharpe != 0
    assert hourly.sharpe / daily.sharpe == pytest.approx((24) ** 0.5, rel=1e-6)


def test_long_only_maps_sell_to_flat_while_short_mode_profits() -> None:
    changes = [-0.01] * 90
    long_only = BaselineBacktester().run(make_series(changes))
    assert long_only.trades == 0
    assert long_only.total_return == pytest.approx(0.0)

    short_enabled = BaselineBacktester(long_only=False).run(make_series(changes))
    assert short_enabled.trades >= 1
    assert short_enabled.total_return > 0
