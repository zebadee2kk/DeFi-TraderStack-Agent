from datetime import UTC, datetime, timedelta

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.research.leakage import assert_no_lookahead
from traderstack.research.tuning import grid_search_momentum_lookback
from traderstack.walkforward import WalkForwardEvaluator


def make_candles(count: int = 400) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        previous = price
        # A mild cyclical wiggle on top of an uptrend so different momentum
        # lookbacks genuinely score differently.
        price = price + 0.4 + 0.6 * ((index % 9) - 4) / 4
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


def test_default_walkforward_ignores_the_train_slice() -> None:
    candles = make_candles()
    evaluator = WalkForwardEvaluator(train_size=120, test_size=60, step_size=60)
    report = evaluator.evaluate(candles)
    assert len(report.folds) >= 1


def test_fit_hook_only_ever_sees_the_train_window() -> None:
    """The fit hook must never be handed anything past its own train window --
    reuse the lookahead helper to prove it."""
    candles = make_candles()
    seen_train_windows: list[tuple[Candle, ...]] = []
    base_backtester = BaselineBacktester(warmup=31)

    def spying_fit(train_candles: tuple[Candle, ...]) -> BaselineBacktester:
        seen_train_windows.append(train_candles)
        return base_backtester

    evaluator = WalkForwardEvaluator(
        backtester=base_backtester, train_size=120, test_size=60, step_size=60, fit=spying_fit
    )
    report = evaluator.evaluate(candles)
    assert len(report.folds) >= 1
    assert len(seen_train_windows) == len(report.folds)

    for fold, train_window in zip(report.folds, seen_train_windows, strict=True):
        assert len(train_window) == fold.train_end - fold.train_start
        assert train_window == candles[fold.train_start : fold.train_end]
        # Nothing at or after the test window leaked into what fit() received.
        assert train_window[-1].opened_at < candles[fold.test_start].opened_at


def test_grid_search_momentum_lookback_only_uses_train_data() -> None:
    candles = make_candles()
    base_backtester = BaselineBacktester(warmup=31)
    seen_train_windows: list[tuple[Candle, ...]] = []

    fit = grid_search_momentum_lookback(base_backtester, candidates=(6, 12, 24))

    def spying_fit(train_candles: tuple[Candle, ...]) -> BaselineBacktester:
        seen_train_windows.append(train_candles)
        return fit(train_candles)

    evaluator = WalkForwardEvaluator(
        backtester=base_backtester, train_size=150, test_size=60, step_size=60, fit=spying_fit
    )
    report = evaluator.evaluate(candles)
    assert len(report.folds) >= 1

    for fold, train_window in zip(report.folds, seen_train_windows, strict=True):
        assert train_window == candles[fold.train_start : fold.train_end]


def test_grid_search_fit_hook_itself_has_no_lookahead() -> None:
    """The fit hook is a signal-like function of its (train-only) argument --
    prove it never depends on data past what it was given."""
    candles = make_candles()
    base_backtester = BaselineBacktester(warmup=31)
    fit = grid_search_momentum_lookback(base_backtester, candidates=(6, 12))

    def fn(window: tuple[Candle, ...]) -> int:
        tuned = fit(window)
        return tuned.ensemble.momentum_strategy.lookback

    assert_no_lookahead(fn, candles, min_index=150, step=50)
