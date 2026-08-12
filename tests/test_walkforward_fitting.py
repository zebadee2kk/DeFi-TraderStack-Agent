from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    StrategyEnsemble,
    TrendStrategy,
)
from traderstack.walkforward import (
    EnsembleCandidate,
    FittedWalkForwardEvaluator,
    default_candidates,
)


def make_candles(prices: list[float], symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        high = max(previous, price) * 1.001
        low = min(previous, price) * 0.999
        candles.append(
            Candle(
                symbol=symbol,
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=high,
                low=low,
                close=price,
                volume=100 + index,
            )
        )
    return tuple(candles)


def make_trend_prices(count: int) -> list[float]:
    return [100.0 + index * 1.0 for index in range(count)]


def inert_ensemble() -> StrategyEnsemble:
    return StrategyEnsemble(
        momentum_strategy=MomentumStrategy(minimum_momentum=10.0),
        trend_strategy=TrendStrategy(minimum_separation=10.0),
        mean_reversion_strategy=MeanReversionStrategy(entry_z=50.0),
    )


def test_fitting_selects_candidate_per_fold_with_expected_fold_count() -> None:
    evaluator = FittedWalkForwardEvaluator(train_size=80, test_size=40, step_size=40)
    report = evaluator.evaluate(make_candles(make_trend_prices(200)))

    names = {candidate.name for candidate in default_candidates()}
    assert len(report.folds) == 3
    for fold in report.folds:
        assert fold.train_end == fold.test_start
        assert fold.selected_candidate in names
    assert report.worst_drawdown >= 0


def test_selection_uses_only_train_window() -> None:
    candidates = (
        EnsembleCandidate(name="inert", ensemble=inert_ensemble()),
        EnsembleCandidate(name="active", ensemble=StrategyEnsemble()),
    )
    evaluator = FittedWalkForwardEvaluator(
        candidates=candidates, train_size=80, test_size=40, step_size=40
    )
    prices = make_trend_prices(80) + [179.0 + (0.5 if index % 2 else -0.5) for index in range(40)]
    candles = make_candles(prices)
    report = evaluator.evaluate(candles)

    fold = report.folds[0]
    train_slice = candles[fold.train_start : fold.train_end]
    train_scores = {
        candidate.name: replace(evaluator.backtester, ensemble=candidate.ensemble).run(train_slice)
        for candidate in candidates
    }
    expected = max(
        candidates,
        key=lambda candidate: (
            train_scores[candidate.name].sharpe,
            train_scores[candidate.name].total_return,
        ),
    )
    assert fold.selected_candidate in {"inert", "active"}
    assert fold.selected_candidate == expected.name
    assert fold.train_metrics == train_scores[expected.name]
    assert fold.train_metrics != fold.metrics


def test_evaluate_rejects_too_few_candles() -> None:
    evaluator = FittedWalkForwardEvaluator(train_size=80, test_size=40, step_size=40)
    with pytest.raises(ValueError, match="insufficient candles"):
        evaluator.evaluate(make_candles(make_trend_prices(100)))


def test_evaluate_rejects_empty_candidates() -> None:
    evaluator = FittedWalkForwardEvaluator(candidates=())
    with pytest.raises(ValueError, match="at least one candidate"):
        evaluator.evaluate(make_candles(make_trend_prices(300)))


def test_evaluate_rejects_windows_within_warmup() -> None:
    backtester = BaselineBacktester()
    evaluator = FittedWalkForwardEvaluator(backtester=backtester, train_size=backtester.warmup)
    with pytest.raises(ValueError, match="train_size must exceed"):
        evaluator.evaluate(make_candles(make_trend_prices(300)))
