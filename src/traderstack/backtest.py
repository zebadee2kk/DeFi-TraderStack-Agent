from dataclasses import dataclass, field
from math import sqrt

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.market.candle_feed import interval_to_seconds
from traderstack.models import Side
from traderstack.strategies import StrategyEnsemble

_SECONDS_PER_YEAR = 365.0 * 86_400.0
_WIPEOUT_EQUITY = 1e-9


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
    """Bar-by-bar backtester with mark-to-market equity accounting.

    Equity is revalued on every bar, so drawdown and Sharpe reflect open
    positions, not just realized trades. long_only=True (the default) maps
    SELL consensus to flat, matching the live risk engine's reduce-only
    sell semantics; shorts are an explicit research opt-in.
    """

    ensemble: StrategyEnsemble = field(default_factory=StrategyEnsemble)
    starting_equity: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    warmup: int = 31
    long_only: bool = True

    def run(self, candles: tuple[Candle, ...]) -> BacktestMetrics:
        if len(candles) <= self.warmup + 1:
            raise ValueError("insufficient candles for backtest")
        equity = self.starting_equity
        peak = equity
        max_drawdown = 0.0
        position = 0
        returns: list[float] = []
        trades = 0
        friction = (self.fee_bps + self.slippage_bps) / 10_000
        reference_price = candles[self.warmup].open
        wiped_out = False

        for index in range(self.warmup, len(candles) - 1):
            window = candles[: index + 1]
            _, signals = self.ensemble.evaluate(window)
            consensus = self.ensemble.consensus(signals)
            execution_price = candles[index + 1].open
            bar_close = candles[index + 1].close
            previous_equity = equity

            desired_position = position
            if consensus is not None:
                if consensus.side is Side.BUY:
                    desired_position = 1
                else:
                    desired_position = 0 if self.long_only else -1

            # Mark the carried position from the last reference to this
            # bar's execution price, then trade, then mark to the close.
            equity *= 1.0 + position * (execution_price / reference_price - 1.0)
            if desired_position != position:
                legs = abs(desired_position - position)
                equity *= (1.0 - friction) ** legs
                trades += legs
                position = desired_position
            equity *= 1.0 + position * (bar_close / execution_price - 1.0)
            reference_price = bar_close

            returns.append(equity / previous_equity - 1.0 if previous_equity > 0 else -1.0)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1.0 - equity / peak if peak > 0 else 1.0)
            if equity <= 0:
                wiped_out = True
                break

        if position != 0 and not wiped_out:
            equity *= 1.0 - friction
            trades += 1
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1.0 - equity / peak)

        if equity <= 0:
            equity = _WIPEOUT_EQUITY
            max_drawdown = 1.0

        total_return = equity / self.starting_equity - 1.0
        benchmark_return = candles[-1].close / candles[self.warmup].open - 1.0
        sharpe = self._sharpe(returns, candles[0].interval)
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
    def _sharpe(returns: list[float], interval: str) -> float:
        if len(returns) < 2:
            return 0.0
        avg = sum(returns) / len(returns)
        variance = sum((value - avg) ** 2 for value in returns) / (len(returns) - 1)
        if variance <= 0:
            return 0.0
        periods_per_year = _SECONDS_PER_YEAR / interval_to_seconds(interval)
        return avg / sqrt(variance) * sqrt(periods_per_year)
