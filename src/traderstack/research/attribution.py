"""Performance attribution (Evaluation Framework "Attribution" section):
decompose a backtest's trades by strategy, asset, regime, side, and gross return
versus fees/slippage.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from pydantic import BaseModel, Field

from traderstack.backtest import BacktestTrade


class AttributionBucket(BaseModel):
    """Aggregate stats for one slice of trades (one strategy, asset, regime, or side)."""

    key: str
    trade_count: int = Field(ge=0)
    gross_return: float
    net_return: float
    fees_and_slippage_return: float
    total_fees_usd: float = Field(ge=0)
    win_rate: float = Field(ge=0, le=1)
    average_return: float


class AttributionReport(BaseModel):
    """Full decomposition of a set of trades."""

    asset: str
    total_trades: int = Field(ge=0)
    by_strategy: list[AttributionBucket] = Field(default_factory=list)
    by_asset: list[AttributionBucket] = Field(default_factory=list)
    by_regime: list[AttributionBucket] = Field(default_factory=list)
    by_side: list[AttributionBucket] = Field(default_factory=list)
    gross_vs_costs: AttributionBucket


def _bucket(key: str, trades: list[BacktestTrade]) -> AttributionBucket:
    count = len(trades)
    gross_returns = [
        trade.return_pct + trade.fees_paid / trade.notional_usd
        if trade.notional_usd > 0
        else trade.return_pct
        for trade in trades
    ]
    net_returns = [trade.return_pct for trade in trades]
    gross_total = sum(gross_returns)
    net_total = sum(net_returns)
    wins = sum(1 for trade in trades if trade.return_pct > 0)
    return AttributionBucket(
        key=key,
        trade_count=count,
        gross_return=gross_total,
        net_return=net_total,
        fees_and_slippage_return=gross_total - net_total,
        total_fees_usd=sum(trade.fees_paid for trade in trades),
        win_rate=(wins / count) if count else 0.0,
        average_return=(net_total / count) if count else 0.0,
    )


def _group_by(
    trades: list[BacktestTrade], key_fn: Callable[[BacktestTrade], str]
) -> list[AttributionBucket]:
    groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in trades:
        groups[key_fn(trade)].append(trade)
    return [_bucket(key, group) for key, group in sorted(groups.items())]


def build_attribution_report(
    trades: list[BacktestTrade] | tuple[BacktestTrade, ...],
    *,
    asset: str,
) -> AttributionReport:
    """Decompose `trades` by contributing strategy, asset, regime, side, and cost."""
    trade_list = list(trades)

    def strategy_keys(trade: BacktestTrade) -> list[str]:
        return trade.strategy_ids or ["unattributed"]

    strategy_groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in trade_list:
        for strategy_id in strategy_keys(trade):
            strategy_groups[strategy_id].append(trade)
    by_strategy = [_bucket(key, group) for key, group in sorted(strategy_groups.items())]

    by_asset = _group_by(trade_list, lambda _t: asset)
    by_regime = _group_by(trade_list, lambda t: t.regime.value)
    by_side = _group_by(trade_list, lambda t: t.side.value)

    return AttributionReport(
        asset=asset,
        total_trades=len(trade_list),
        by_strategy=by_strategy,
        by_asset=by_asset,
        by_regime=by_regime,
        by_side=by_side,
        gross_vs_costs=_bucket("all_trades", trade_list),
    )


def render_attribution_table(report: AttributionReport) -> str:
    """A plain-text table rendering of an `AttributionReport`."""
    lines: list[str] = []
    lines.append(f"Performance Attribution -- {report.asset} ({report.total_trades} trades)")
    lines.append("=" * 72)

    def render_section(title: str, buckets: list[AttributionBucket]) -> None:
        lines.append(f"\n{title}")
        lines.append("-" * len(title))
        if not buckets:
            lines.append("  (no trades)")
            return
        header = f"{'key':<22}{'n':>5}{'net %':>10}{'gross %':>10}{'fees %':>10}{'win %':>8}"
        lines.append(header)
        for bucket in buckets:
            lines.append(
                f"{bucket.key:<22}{bucket.trade_count:>5}"
                f"{bucket.net_return * 100:>10.2f}"
                f"{bucket.gross_return * 100:>10.2f}"
                f"{bucket.fees_and_slippage_return * 100:>10.2f}"
                f"{bucket.win_rate * 100:>8.1f}"
            )

    render_section("By strategy", report.by_strategy)
    render_section("By asset", report.by_asset)
    render_section("By regime", report.by_regime)
    render_section("By side", report.by_side)

    gross = report.gross_vs_costs
    lines.append("\nGross vs. costs")
    lines.append("-" * 15)
    lines.append(f"  gross return:  {gross.gross_return * 100:.2f}%")
    lines.append(f"  fees/slippage: {gross.fees_and_slippage_return * 100:.2f}%")
    lines.append(f"  net return:    {gross.net_return * 100:.2f}%")
    lines.append(f"  total fees:    ${gross.total_fees_usd:,.2f}")
    return "\n".join(lines)
