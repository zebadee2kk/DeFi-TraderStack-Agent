from dataclasses import dataclass, field, replace

from pydantic import BaseModel, Field

from traderstack.backtest import BacktestMetrics, BaselineBacktester
from traderstack.candles import Candle
from traderstack.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    StrategyEnsemble,
    TrendStrategy,
)


class WalkForwardFold(BaseModel):
    train_start: int = Field(ge=0)
    train_end: int = Field(gt=0)
    test_start: int = Field(ge=0)
    test_end: int = Field(gt=0)
    metrics: BacktestMetrics


class WalkForwardReport(BaseModel):
    folds: list[WalkForwardFold]
    mean_total_return: float
    mean_excess_return: float
    mean_sharpe: float
    worst_drawdown: float = Field(ge=0)


@dataclass(frozen=True)
class WalkForwardEvaluator:
    backtester: BaselineBacktester = field(default_factory=BaselineBacktester)
    train_size: int = 180
    test_size: int = 60
    step_size: int = 60

    def evaluate(self, candles: tuple[Candle, ...]) -> WalkForwardReport:
        if self.train_size <= self.backtester.warmup:
            raise ValueError("train_size must exceed backtester warmup")
        if self.test_size <= self.backtester.warmup:
            raise ValueError("test_size must exceed backtester warmup")
        if self.step_size <= 0:
            raise ValueError("step_size must be positive")

        folds: list[WalkForwardFold] = []
        train_start = 0
        while True:
            train_end = train_start + self.train_size
            test_start = train_end
            test_end = test_start + self.test_size
            if test_end > len(candles):
                break
            test_slice = candles[test_start:test_end]
            metrics = self.backtester.run(test_slice)
            folds.append(
                WalkForwardFold(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    metrics=metrics,
                )
            )
            train_start += self.step_size

        if not folds:
            raise ValueError("insufficient candles for one walk-forward fold")
        count = len(folds)
        return WalkForwardReport(
            folds=folds,
            mean_total_return=sum(f.metrics.total_return for f in folds) / count,
            mean_excess_return=sum(f.metrics.excess_return for f in folds) / count,
            mean_sharpe=sum(f.metrics.sharpe for f in folds) / count,
            worst_drawdown=max(f.metrics.max_drawdown for f in folds),
        )


@dataclass(frozen=True)
class EnsembleCandidate:
    name: str
    ensemble: StrategyEnsemble


def default_candidates() -> tuple[EnsembleCandidate, ...]:
    return (
        EnsembleCandidate(name="baseline", ensemble=StrategyEnsemble()),
        EnsembleCandidate(
            name="fast_momentum",
            ensemble=StrategyEnsemble(
                momentum_strategy=MomentumStrategy(lookback=6, minimum_momentum=0.01)
            ),
        ),
        EnsembleCandidate(
            name="slow_momentum",
            ensemble=StrategyEnsemble(
                momentum_strategy=MomentumStrategy(lookback=24, minimum_momentum=0.03)
            ),
        ),
        EnsembleCandidate(
            name="fast_trend",
            ensemble=StrategyEnsemble(
                trend_strategy=TrendStrategy(short_window=5, long_window=20)
            ),
        ),
        EnsembleCandidate(
            name="slow_trend",
            ensemble=StrategyEnsemble(
                trend_strategy=TrendStrategy(short_window=15, long_window=30)
            ),
        ),
        EnsembleCandidate(
            name="tight_reversion",
            ensemble=StrategyEnsemble(
                mean_reversion_strategy=MeanReversionStrategy(entry_z=1.0)
            ),
        ),
        EnsembleCandidate(
            name="wide_reversion",
            ensemble=StrategyEnsemble(
                mean_reversion_strategy=MeanReversionStrategy(entry_z=2.5)
            ),
        ),
    )


class FittedWalkForwardFold(BaseModel):
    train_start: int = Field(ge=0)
    train_end: int = Field(gt=0)
    test_start: int = Field(ge=0)
    test_end: int = Field(gt=0)
    selected_candidate: str
    train_metrics: BacktestMetrics
    metrics: BacktestMetrics


class FittedWalkForwardReport(BaseModel):
    folds: list[FittedWalkForwardFold]
    mean_total_return: float
    mean_excess_return: float
    mean_sharpe: float
    worst_drawdown: float = Field(ge=0)


@dataclass(frozen=True)
class FittedWalkForwardEvaluator:
    backtester: BaselineBacktester = field(default_factory=BaselineBacktester)
    candidates: tuple[EnsembleCandidate, ...] = field(default_factory=default_candidates)
    train_size: int = 180
    test_size: int = 60
    step_size: int = 60

    def evaluate(self, candles: tuple[Candle, ...]) -> FittedWalkForwardReport:
        if not self.candidates:
            raise ValueError("at least one candidate is required")
        if self.train_size <= self.backtester.warmup:
            raise ValueError("train_size must exceed backtester warmup")
        if self.test_size <= self.backtester.warmup:
            raise ValueError("test_size must exceed backtester warmup")
        if self.step_size <= 0:
            raise ValueError("step_size must be positive")

        folds: list[FittedWalkForwardFold] = []
        train_start = 0
        while True:
            train_end = train_start + self.train_size
            test_start = train_end
            test_end = test_start + self.test_size
            if test_end > len(candles):
                break
            train_slice = candles[train_start:train_end]
            selected, train_metrics = self._fit(train_slice)
            test_metrics = replace(self.backtester, ensemble=selected.ensemble).run(
                candles[test_start:test_end]
            )
            folds.append(
                FittedWalkForwardFold(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    selected_candidate=selected.name,
                    train_metrics=train_metrics,
                    metrics=test_metrics,
                )
            )
            train_start += self.step_size

        if not folds:
            raise ValueError("insufficient candles for one walk-forward fold")
        count = len(folds)
        return FittedWalkForwardReport(
            folds=folds,
            mean_total_return=sum(f.metrics.total_return for f in folds) / count,
            mean_excess_return=sum(f.metrics.excess_return for f in folds) / count,
            mean_sharpe=sum(f.metrics.sharpe for f in folds) / count,
            worst_drawdown=max(f.metrics.max_drawdown for f in folds),
        )

    def _fit(
        self, train_slice: tuple[Candle, ...]
    ) -> tuple[EnsembleCandidate, BacktestMetrics]:
        best: tuple[EnsembleCandidate, BacktestMetrics] | None = None
        for candidate in self.candidates:
            metrics = replace(self.backtester, ensemble=candidate.ensemble).run(train_slice)
            if best is None or (metrics.sharpe, metrics.total_return) > (
                best[1].sharpe,
                best[1].total_return,
            ):
                best = (candidate, metrics)
        assert best is not None
        return best
