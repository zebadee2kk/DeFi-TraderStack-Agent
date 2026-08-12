from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from traderstack.backtest import BacktestMetrics, BaselineBacktester
from traderstack.candles import Candle


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
