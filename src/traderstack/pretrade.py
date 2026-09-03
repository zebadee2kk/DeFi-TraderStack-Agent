"""Pre-trade self-check: backtest the strategy on recent history before every proposal.

Before a trade candidate reaches the risk engine, the gate re-runs the same
deterministic strategy ensemble that produced it over the asset's recent candle
history, and asks three questions:

1. Does the strategy, evaluated on real candles right now, actually confirm the
   proposed side?
2. Would that strategy have made money, net of fees and slippage and against a
   buy-and-hold benchmark, over the recent lookback?
3. Does it hold up out-of-sample across rolling walk-forward folds?

Any "no" (or any missing / stale input) is a rejection. The gate never relaxes
the risk engine; it can only add rejections ahead of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.backtest import BacktestMetrics, BaselineBacktester
from traderstack.candles import Candle
from traderstack.models import Side
from traderstack.strategies import Regime
from traderstack.walkforward import WalkForwardEvaluator, WalkForwardReport


class PreTradeCheck(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    confirmed_side: Side | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    regime: Regime | None = None
    rationale: str | None = None
    candles_evaluated: int = Field(default=0, ge=0)
    metrics: BacktestMetrics | None = None
    walkforward: WalkForwardReport | None = None


@dataclass(frozen=True)
class PreTradeBacktestGate:
    backtester: BaselineBacktester = field(default_factory=BaselineBacktester)
    walkforward: WalkForwardEvaluator | None = None
    min_candles: int = 250
    max_candle_age_seconds: float | None = 7_200.0
    min_excess_return: float = 0.0
    max_drawdown: float = 0.15
    min_sharpe: float = 0.0
    min_trades: int = 3
    require_walkforward: bool = True
    min_walkforward_excess_return: float = 0.0

    def evaluate(
        self,
        candles: tuple[Candle, ...],
        side: Side | None = None,
        *,
        now: datetime | None = None,
    ) -> PreTradeCheck:
        reasons: list[str] = []
        count = len(candles)

        if count < self.min_candles:
            return PreTradeCheck(
                passed=False,
                reasons=["insufficient_candle_history"],
                candles_evaluated=count,
            )

        if self.max_candle_age_seconds is not None:
            reference_time = now or datetime.now(UTC)
            age = (reference_time - candles[-1].opened_at).total_seconds()
            if age > self.max_candle_age_seconds:
                return PreTradeCheck(
                    passed=False,
                    reasons=["stale_candle_history"],
                    candles_evaluated=count,
                )

        regime, signals = self.backtester.ensemble.evaluate(candles)
        consensus = self.backtester.ensemble.consensus(signals)
        if consensus is None or consensus.side is None:
            return PreTradeCheck(
                passed=False,
                reasons=["no_strategy_consensus"],
                regime=regime,
                candles_evaluated=count,
            )
        if side is not None and consensus.side is not side:
            return PreTradeCheck(
                passed=False,
                reasons=["strategy_does_not_confirm_side"],
                confirmed_side=consensus.side,
                confidence=consensus.confidence,
                regime=regime,
                rationale=consensus.rationale,
                candles_evaluated=count,
            )

        metrics = self.backtester.run(candles)
        if metrics.excess_return < self.min_excess_return:
            reasons.append("backtest_excess_return_below_minimum")
        if metrics.max_drawdown > self.max_drawdown:
            reasons.append("backtest_drawdown_above_maximum")
        if metrics.sharpe < self.min_sharpe:
            reasons.append("backtest_sharpe_below_minimum")
        if metrics.trades < self.min_trades:
            reasons.append("backtest_trade_count_below_minimum")

        report: WalkForwardReport | None = None
        evaluator = self.walkforward or WalkForwardEvaluator(backtester=self.backtester)
        try:
            report = evaluator.evaluate(candles)
        except ValueError:
            if self.require_walkforward:
                reasons.append("walkforward_insufficient_history")
        if report is not None:
            if report.mean_excess_return < self.min_walkforward_excess_return:
                reasons.append("walkforward_excess_return_below_minimum")
            if report.worst_drawdown > self.max_drawdown:
                reasons.append("walkforward_drawdown_above_maximum")

        return PreTradeCheck(
            passed=not reasons,
            reasons=reasons,
            confirmed_side=consensus.side,
            confidence=consensus.confidence,
            regime=regime,
            rationale=consensus.rationale,
            candles_evaluated=count,
            metrics=metrics,
            walkforward=report,
        )
