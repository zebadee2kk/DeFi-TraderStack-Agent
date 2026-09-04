from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.candles import periods_per_year as candle_periods_per_year
from traderstack.models import Side
from traderstack.research.costs import CostModel, FlatCostModel
from traderstack.strategies import Regime, StrategyEnsemble

# A position "decision" function used by `simulate_positions`: given the candle window
# available so far (point-in-time only), return the desired position weight (in
# [-1, 1], where 1 is fully long and -1 fully short), the prevailing market regime, and
# the ids of the strategies/signals contributing to that decision.
PositionDecision = Callable[[tuple[Candle, ...]], tuple[float, Regime, list[str]]]


class BacktestTrade(BaseModel):
    """One completed round trip: an entry fill followed by an exit fill."""

    entry_time: datetime
    exit_time: datetime
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    side: Side
    return_pct: float
    regime: Regime
    strategy_ids: list[str] = Field(default_factory=list)
    notional_usd: float = Field(ge=0)
    fees_paid: float = Field(ge=0)


class BacktestMetrics(BaseModel):
    starting_equity: float = Field(gt=0)
    ending_equity: float = Field(gt=0)
    total_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float = Field(ge=0)
    sharpe: float
    trades: int = Field(ge=0)
    sortino: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    annualized_volatility: float = Field(default=0.0, ge=0)
    turnover: float = Field(default=0.0, ge=0)
    total_fees: float = Field(default=0.0, ge=0)
    trade_log: list[BacktestTrade] = Field(default_factory=list)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance) if variance > 0 else 0.0


def _sharpe(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    deviation = _std(returns)
    if deviation <= 0:
        return 0.0
    return _mean(returns) / deviation * sqrt(periods_per_year)


def _sortino(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    downside = [value for value in returns if value < 0]
    if not downside:
        return 0.0
    downside_deviation = sqrt(sum(value**2 for value in downside) / len(returns))
    if downside_deviation <= 0:
        return 0.0
    return _mean(returns) / downside_deviation * sqrt(periods_per_year)


def simulate_positions(
    candles: tuple[Candle, ...],
    decide: PositionDecision,
    *,
    starting_equity: float = 10_000.0,
    warmup: int = 31,
    cost_model: CostModel | None = None,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    rebalance_threshold: float = 1e-9,
) -> BacktestMetrics:
    """Run a point-in-time backtest driven by a position-decision function.

    `decide` is called with only the candles available up to (and including) each
    decision index -- it must never see future candles. This is the shared engine
    behind `BaselineBacktester.run` and every strategy in `research.baselines`, so
    they all share identical cost accounting, trade bookkeeping, and metrics.
    """
    if len(candles) <= warmup:
        raise ValueError("insufficient candles for backtest")
    model = cost_model or FlatCostModel(fee_bps=fee_bps, slippage_bps=slippage_bps)
    periods = candle_periods_per_year(candles[0].interval)

    equity = starting_equity
    peak = equity
    max_drawdown = 0.0
    position = 0.0
    entry_price = 0.0
    entry_time = candles[warmup].opened_at
    entry_regime: Regime = Regime.RANGE
    entry_strategy_ids: list[str] = []
    entry_notional = 0.0
    entry_fees = 0.0
    returns: list[float] = []
    trade_log: list[BacktestTrade] = []
    total_fees = 0.0
    total_turnover = 0.0

    def close_position(exit_candle: Candle, exit_price: float) -> None:
        nonlocal equity, total_fees, total_turnover
        notional = equity
        exit_friction = model.cost_bps(exit_candle, notional) / 10_000
        pnl = position * (exit_price / entry_price - 1.0)
        # A leveraged/unbounded short can, in principle, lose more than 100% of the
        # position notional in one mark; floor the multiplier so equity can approach
        # but never reach or cross zero (a real account cannot owe negative equity
        # on a single spot position).
        equity *= max(1.0 + pnl - exit_friction, 1e-9)
        fees = notional * exit_friction
        total_fees += fees
        total_turnover += notional
        return_pct = equity / entry_notional - 1.0 if entry_notional > 0 else 0.0
        trade_log.append(
            BacktestTrade(
                entry_time=entry_time,
                exit_time=exit_candle.opened_at,
                entry_price=entry_price,
                exit_price=exit_price,
                side=Side.BUY if position > 0 else Side.SELL,
                return_pct=return_pct,
                regime=entry_regime,
                strategy_ids=list(entry_strategy_ids),
                notional_usd=entry_notional,
                fees_paid=entry_fees + fees,
            )
        )

    def open_position(
        entry_candle: Candle, price: float, weight: float, regime: Regime, ids: list[str]
    ) -> None:
        nonlocal equity, position, entry_price, entry_time, entry_regime
        nonlocal entry_strategy_ids, entry_notional, entry_fees, total_fees, total_turnover
        notional = equity
        friction = model.cost_bps(entry_candle, notional) / 10_000
        equity *= 1.0 - friction
        fees = notional * friction
        total_fees += fees
        total_turnover += notional
        position = weight
        entry_price = price
        entry_time = entry_candle.opened_at
        entry_regime = regime
        entry_strategy_ids = list(ids)
        entry_notional = notional
        entry_fees = fees

    for index in range(warmup, len(candles) - 1):
        window = candles[: index + 1]
        weight, regime, ids = decide(window)
        next_candle = candles[index + 1]
        next_price = next_candle.open
        previous_equity = equity

        if abs(weight - position) > rebalance_threshold:
            if position != 0.0:
                close_position(next_candle, next_price)
            if weight != 0.0:
                open_position(next_candle, next_price, weight, regime, ids)
            else:
                position = 0.0

        returns.append(equity / previous_equity - 1.0)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1.0 - equity / peak)

    if position != 0.0:
        close_position(candles[-1], candles[-1].close)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1.0 - equity / peak)

    total_return = equity / starting_equity - 1.0
    benchmark_return = candles[-1].close / candles[warmup].open - 1.0
    sharpe = _sharpe(returns, periods)
    sortino = _sortino(returns, periods)

    bars = max(len(candles) - warmup, 1)
    if equity > 0:
        annualized_return = (equity / starting_equity) ** (periods / bars) - 1.0
    else:
        annualized_return = -1.0
    calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0.0

    gains = [trade.return_pct for trade in trade_log if trade.return_pct > 0]
    losses = [trade.return_pct for trade in trade_log if trade.return_pct < 0]
    gross_loss = abs(sum(losses))
    if gross_loss > 1e-12:
        profit_factor = sum(gains) / gross_loss
    else:
        profit_factor = sum(gains) if gains else 0.0
    expectancy = _mean([trade.return_pct for trade in trade_log])
    annualized_volatility = _std(returns) * sqrt(periods)
    turnover = total_turnover / starting_equity

    return BacktestMetrics(
        starting_equity=starting_equity,
        ending_equity=equity,
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        trades=len(trade_log),
        sortino=sortino,
        calmar=calmar,
        profit_factor=profit_factor,
        expectancy=expectancy,
        annualized_volatility=annualized_volatility,
        turnover=turnover,
        total_fees=total_fees,
        trade_log=trade_log,
    )


@dataclass(frozen=True)
class BaselineBacktester:
    ensemble: StrategyEnsemble = field(default_factory=StrategyEnsemble)
    starting_equity: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    warmup: int = 31
    cost_model: CostModel | None = None

    def run(self, candles: tuple[Candle, ...]) -> BacktestMetrics:
        def decide(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
            regime, signals = self.ensemble.evaluate(window)
            consensus = self.ensemble.consensus(signals)
            if consensus is None or consensus.side is None:
                return 0.0, regime, []
            weight = 1.0 if consensus.side is Side.BUY else -1.0
            contributing = [signal.strategy_id for signal in signals if signal.side is consensus.side]
            return weight, regime, contributing

        return simulate_positions(
            candles,
            decide,
            starting_equity=self.starting_equity,
            warmup=self.warmup,
            cost_model=self.cost_model,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
        )

    @staticmethod
    def _sharpe(returns: list[float]) -> float:
        # Retained for backward compatibility; assumes daily bars (365/yr).
        return _sharpe(returns, 365.0)
