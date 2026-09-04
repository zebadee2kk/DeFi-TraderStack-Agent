from datetime import UTC, datetime, timedelta

from traderstack.backtest import BacktestMetrics
from traderstack.candles import Candle
from traderstack.research.baselines import (
    BuyAndHoldBaseline,
    MeanReversionBaseline,
    MovingAverageTrendBaseline,
    TimeSeriesMomentumBaseline,
    VolatilityTargetBaseline,
    compare,
    default_baselines,
    run_baselines,
)


def make_uptrend(count: int = 300) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        previous = price
        price = price + 0.5
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def test_buy_and_hold_tracks_the_benchmark() -> None:
    candles = make_uptrend()
    metrics = BuyAndHoldBaseline().run(candles)
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.trades == 1
    assert metrics.total_return > 0
    assert metrics.total_return == metrics.excess_return + metrics.benchmark_return


def test_momentum_ma_and_mean_reversion_baselines_run() -> None:
    candles = make_uptrend()
    for baseline in (
        TimeSeriesMomentumBaseline(),
        MovingAverageTrendBaseline(),
        MeanReversionBaseline(),
        VolatilityTargetBaseline(),
    ):
        metrics = baseline.run(candles)
        assert isinstance(metrics, BacktestMetrics)
        assert metrics.starting_equity == 10_000.0


def test_run_baselines_covers_the_default_set() -> None:
    candles = make_uptrend()
    results = run_baselines(candles)
    names = {baseline.name for baseline in default_baselines()}
    assert set(results) == names
    for metrics in results.values():
        assert isinstance(metrics, BacktestMetrics)


def test_compare_reports_excess_over_each_baseline() -> None:
    candles = make_uptrend()
    strategy_metrics = BuyAndHoldBaseline(name="strategy_under_test").run(candles)
    baselines = run_baselines(candles)
    excess = compare(strategy_metrics, baselines)
    assert set(excess) == set(baselines)
    for name, result in excess.items():
        assert result.baseline == name
        assert result.excess_total_return == (
            strategy_metrics.total_return - baselines[name].total_return
        )


def test_higher_notional_orders_reduce_returns_under_volume_aware_costs() -> None:
    """Baselines all share the backtester's cost model; a larger starting equity
    (bigger orders relative to bar volume) should do worse under a volume-aware
    slippage model than a smaller one, all else equal."""
    from traderstack.research.costs import VolumeAwareSlippageModel

    candles = make_uptrend()
    model = VolumeAwareSlippageModel(
        fee_bps=5.0,
        base_slippage_bps=2.0,
        participation_sensitivity_bps=500.0,
        max_slippage_bps=500.0,
    )
    small = BuyAndHoldBaseline().run(candles, cost_model=model, starting_equity=1_000.0)
    large = BuyAndHoldBaseline().run(candles, cost_model=model, starting_equity=1_000_000.0)
    assert small.total_fees < large.total_fees
    assert small.total_return >= large.total_return
