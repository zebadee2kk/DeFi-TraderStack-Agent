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


# --- search evidence (#135) ---
def test_period_returns_are_captured_per_bar_and_compound_to_equity() -> None:
    from math import prod

    from traderstack.backtest import simulate_positions
    from traderstack.strategies import Regime

    candles = make_trend(90)
    warmup = 31
    # Flat on the last decision so the forced end-of-series close is a no-op
    # and the per-bar returns compound exactly to the equity ratio.
    last_decision = len(candles) - 2

    def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
        if len(window) - 1 >= last_decision:
            return 0.0, Regime.TRENDING_UP, []
        return 1.0, Regime.TRENDING_UP, ["t"]

    metrics = simulate_positions(candles, decide, warmup=warmup)
    assert len(metrics.period_returns) == len(candles) - warmup - 1
    compounded = prod(1.0 + value for value in metrics.period_returns)
    assert abs(compounded - metrics.ending_equity / metrics.starting_equity) < 1e-9
    assert metrics.trades == 1
