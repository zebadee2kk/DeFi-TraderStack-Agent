from dataclasses import dataclass, field
from math import sqrt

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.models import Side
from traderstack.strategies import StrategyEnsemble


class BacktestMetrics(BaseModel):
    starting_equity: float = Field(gt=0)
    ending_equity: float = Field(gt=0)
    total_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float = Field(ge=0)
    sharpe: float
    trades: int = Field(ge=0)


@dataclass(frozen=True)
class BaselineBacktester:
    ensemble: StrategyEnsemble = field(default_factory=StrategyEnsemble)
    starting_equity: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    warmup: int = 31

    def run(self, candles: tuple[Candle, ...]) -> BacktestMetrics:
        if len(candles) <= self.warmup:
            raise ValueError("insufficient candles for backtest")
        equity = self.starting_equity
        peak = equity
        max_drawdown = 0.0
        position = 0
        entry_price = 0.0
        returns: list[float] = []
        trades = 0
        friction = (self.fee_bps + self.slippage_bps) / 10_000

        for index in range(self.warmup, len(candles) - 1):
            window = candles[: index + 1]
            _, signals = self.ensemble.evaluate(window)
            consensus = self.ensemble.consensus(signals)
            next_price = candles[index + 1].open
            previous_equity = equity

            desired_position = position
            if consensus is not None:
                desired_position = 1 if consensus.side is Side.BUY else -1

            if desired_position != position:
                if position != 0:
                    pnl = position * (next_price / entry_price - 1.0)
                    equity *= 1.0 + pnl - friction
                    trades += 1
                position = desired_position
                entry_price = next_price
                if position != 0:
                    equity *= 1.0 - friction

            returns.append(equity / previous_equity - 1.0)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1.0 - equity / peak)

        if position != 0:
            final_price = candles[-1].close
            equity *= 1.0 + position * (final_price / entry_price - 1.0) - friction
            trades += 1
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1.0 - equity / peak)

        total_return = equity / self.starting_equity - 1.0
        benchmark_return = candles[-1].close / candles[self.warmup].open - 1.0
        sharpe = self._sharpe(returns)
        return BacktestMetrics(
            starting_equity=self.starting_equity,
            ending_equity=equity,
            total_return=total_return,
            benchmark_return=benchmark_return,
            excess_return=total_return - benchmark_return,
            max_drawdown=max_drawdown,
            sharpe=sharpe,
            trades=trades,
        )

    @staticmethod
    def _sharpe(returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        avg = sum(returns) / len(returns)
        variance = sum((value - avg) ** 2 for value in returns) / (len(returns) - 1)
        if variance <= 0:
            return 0.0
        return avg / sqrt(variance) * sqrt(365.0)
