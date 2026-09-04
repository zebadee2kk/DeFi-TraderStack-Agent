"""Simple baseline strategies every proposed strategy must beat (Evaluation
Framework "Baselines" section): buy-and-hold, time-series momentum, a
moving-average trend follower, mean reversion, and a volatility-targeted
benchmark. Each shares `simulate_positions` -- the same trade bookkeeping, fee
model, and metrics as `BaselineBacktester` -- so comparisons are apples to apples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, cast

from pydantic import BaseModel

from traderstack.backtest import BacktestMetrics, simulate_positions
from traderstack.candles import Candle, periods_per_year
from traderstack.indicators import momentum as momentum_indicator
from traderstack.indicators import moving_average, realized_volatility, zscore
from traderstack.research.costs import CostModel
from traderstack.strategies import Regime, RegimeClassifier

DEFAULT_WARMUP = 31


def _safe_regime(classifier: RegimeClassifier, window: tuple[Candle, ...]) -> Regime:
    try:
        return classifier.classify(window)
    except ValueError:
        return Regime.RANGE


class Baseline(Protocol):
    name: str

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        cost_model: CostModel | None = None,
        starting_equity: float = 10_000.0,
        warmup: int = DEFAULT_WARMUP,
    ) -> BacktestMetrics: ...


@dataclass(frozen=True)
class BuyAndHoldBaseline:
    """Always fully long. The simplest possible benchmark."""

    name: str = "buy_and_hold"
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        cost_model: CostModel | None = None,
        starting_equity: float = 10_000.0,
        warmup: int = DEFAULT_WARMUP,
    ) -> BacktestMetrics:
        def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
            return 1.0, _safe_regime(self.classifier, window), [self.name]

        return simulate_positions(
            candles, decide, starting_equity=starting_equity, warmup=warmup, cost_model=cost_model
        )


@dataclass(frozen=True)
class TimeSeriesMomentumBaseline:
    """Long when trailing momentum is positive, short when negative, else flat."""

    name: str = "time_series_momentum"
    lookback: int = 20
    threshold: float = 0.0
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        cost_model: CostModel | None = None,
        starting_equity: float = 10_000.0,
        warmup: int = DEFAULT_WARMUP,
    ) -> BacktestMetrics:
        def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
            regime = _safe_regime(self.classifier, window)
            if len(window) <= self.lookback:
                return 0.0, regime, []
            value = momentum_indicator(window, self.lookback)
            if value > self.threshold:
                return 1.0, regime, [self.name]
            if value < -self.threshold:
                return -1.0, regime, [self.name]
            return 0.0, regime, []

        return simulate_positions(
            candles, decide, starting_equity=starting_equity, warmup=warmup, cost_model=cost_model
        )


@dataclass(frozen=True)
class MovingAverageTrendBaseline:
    """Long when the short moving average is above the long one, short otherwise."""

    name: str = "ma_trend"
    short_window: int = 10
    long_window: int = 30
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        cost_model: CostModel | None = None,
        starting_equity: float = 10_000.0,
        warmup: int = DEFAULT_WARMUP,
    ) -> BacktestMetrics:
        def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
            regime = _safe_regime(self.classifier, window)
            if len(window) < self.long_window:
                return 0.0, regime, []
            short = moving_average(window, self.short_window)
            long = moving_average(window, self.long_window)
            weight = 1.0 if short >= long else -1.0
            return weight, regime, [self.name]

        return simulate_positions(
            candles, decide, starting_equity=starting_equity, warmup=warmup, cost_model=cost_model
        )


@dataclass(frozen=True)
class MeanReversionBaseline:
    """Buy dips, sell rips, based on a rolling price z-score."""

    name: str = "mean_reversion"
    lookback: int = 20
    entry_z: float = 1.0
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        cost_model: CostModel | None = None,
        starting_equity: float = 10_000.0,
        warmup: int = DEFAULT_WARMUP,
    ) -> BacktestMetrics:
        def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
            regime = _safe_regime(self.classifier, window)
            if len(window) < self.lookback:
                return 0.0, regime, []
            closes = [candle.close for candle in window[-self.lookback :]]
            current_z = zscore(closes[-1], closes)
            if current_z <= -self.entry_z:
                return 1.0, regime, [self.name]
            if current_z >= self.entry_z:
                return -1.0, regime, [self.name]
            return 0.0, regime, []

        return simulate_positions(
            candles, decide, starting_equity=starting_equity, warmup=warmup, cost_model=cost_model
        )


@dataclass(frozen=True)
class VolatilityTargetBaseline:
    """Long-only, sized so realized volatility tracks `target_annual_vol`.

    Weight = min(target_vol_per_bar / realized_vol_per_bar, max_leverage), long only.
    Deleverages automatically in high-volatility regimes -- the "volatility-targeted
    benchmark" the Evaluation Framework calls for.
    """

    name: str = "volatility_target"
    target_annual_vol: float = 0.6
    vol_lookback: int = 20
    max_leverage: float = 1.0
    classifier: RegimeClassifier = field(default_factory=RegimeClassifier)

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        cost_model: CostModel | None = None,
        starting_equity: float = 10_000.0,
        warmup: int = DEFAULT_WARMUP,
    ) -> BacktestMetrics:
        periods = periods_per_year(candles[0].interval) if candles else 365.0
        target_per_bar = self.target_annual_vol / max(periods, 1.0) ** 0.5

        def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
            regime = _safe_regime(self.classifier, window)
            if len(window) <= self.vol_lookback:
                return 0.0, regime, []
            realized = realized_volatility(window, self.vol_lookback)
            if realized <= 0:
                weight = self.max_leverage
            else:
                weight = min(target_per_bar / realized, self.max_leverage)
            return max(weight, 0.0), regime, [self.name]

        return simulate_positions(
            candles,
            decide,
            starting_equity=starting_equity,
            warmup=warmup,
            cost_model=cost_model,
            rebalance_threshold=0.05,
        )


def default_baselines() -> tuple[Baseline, ...]:
    return cast(
        "tuple[Baseline, ...]",
        (
            BuyAndHoldBaseline(),
            TimeSeriesMomentumBaseline(),
            MovingAverageTrendBaseline(),
            MeanReversionBaseline(),
            VolatilityTargetBaseline(),
        ),
    )


def run_baselines(
    candles: tuple[Candle, ...],
    baselines: tuple[Baseline, ...] | None = None,
    *,
    cost_model: CostModel | None = None,
    starting_equity: float = 10_000.0,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, BacktestMetrics]:
    """Run every baseline over the same candles and cost model."""
    selected = baselines if baselines is not None else default_baselines()
    return {
        baseline.name: baseline.run(
            candles, cost_model=cost_model, starting_equity=starting_equity, warmup=warmup
        )
        for baseline in selected
    }


class ExcessMetrics(BaseModel):
    """A strategy's performance relative to one baseline."""

    baseline: str
    strategy_total_return: float
    baseline_total_return: float
    excess_total_return: float
    excess_sharpe: float
    excess_sortino: float
    excess_calmar: float
    excess_max_drawdown: float
    excess_profit_factor: float
    excess_expectancy: float


def compare(
    strategy_metrics: BacktestMetrics, baselines: dict[str, BacktestMetrics]
) -> dict[str, ExcessMetrics]:
    """Excess performance of `strategy_metrics` over each named baseline's metrics."""
    return {
        name: ExcessMetrics(
            baseline=name,
            strategy_total_return=strategy_metrics.total_return,
            baseline_total_return=metrics.total_return,
            excess_total_return=strategy_metrics.total_return - metrics.total_return,
            excess_sharpe=strategy_metrics.sharpe - metrics.sharpe,
            excess_sortino=strategy_metrics.sortino - metrics.sortino,
            excess_calmar=strategy_metrics.calmar - metrics.calmar,
            excess_max_drawdown=strategy_metrics.max_drawdown - metrics.max_drawdown,
            excess_profit_factor=strategy_metrics.profit_factor - metrics.profit_factor,
            excess_expectancy=strategy_metrics.expectancy - metrics.expectancy,
        )
        for name, metrics in baselines.items()
    }
