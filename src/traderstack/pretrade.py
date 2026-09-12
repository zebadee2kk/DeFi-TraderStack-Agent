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
    # Paper-only positive-evidence floor (total return, not excess vs B&H).
    # None (live/shadow default) skips the check so PRETRADE_MIN_* stay the bar.
    min_total_return: float | None = None
    # --- miles-inspired ema_9_21 paper voter ---
    # When set (promote path), reject before scoring if any bar is not this
    # interval. A daily-validated EMA on 1h history is a different strategy.
    required_candle_interval: str | None = None
    # --- paper daily promote DD series ---
    # When False (daily paper promote), max_drawdown is applied only to
    # walk-forward worst_drawdown — the #95–#100 research definition.
    # Full-history backtest DD is a longer series (ETH ~43% on 400 daily
    # bars) and is not that ceiling. Live/shadow keep True (0.15 bar).
    compare_full_history_drawdown: bool = True

    def evaluate(
        self,
        candles: tuple[Candle, ...],
        side: Side | None = None,
        *,
        now: datetime | None = None,
    ) -> PreTradeCheck:
        reasons: list[str] = []
        count = len(candles)

        # --- miles-inspired ema_9_21 paper voter ---
        # Interval mismatch is checked before any scoring so the promote path
        # cannot silently evaluate a daily-validated voter on 1h bars.
        if self.required_candle_interval is not None and (
            count == 0
            or any(candle.interval != self.required_candle_interval for candle in candles)
        ):
            return PreTradeCheck(
                passed=False,
                reasons=["candle_interval_mismatch"],
                candles_evaluated=count,
            )

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
        if self.min_total_return is not None and metrics.total_return < self.min_total_return:
            reasons.append("backtest_total_return_below_minimum")
        if metrics.excess_return < self.min_excess_return:
            reasons.append("backtest_excess_return_below_minimum")
        # --- paper daily promote DD series ---
        # Full-history max_drawdown spans the whole lookback. The paper
        # daily ceiling is calibrated to research WF fold maxDD (ETH
        # 28.77% on 720d vs ~43% full-history on 400d). Comparing the
        # longer series to that ceiling is why ETH never cleared after
        # #98. Live/shadow still compare the full-history book.
        if self.compare_full_history_drawdown and metrics.max_drawdown > self.max_drawdown:
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
