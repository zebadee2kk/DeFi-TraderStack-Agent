"""`traderstack-research`: run the research harness end to end.

Loads a candle history (point-in-time-safe JSON file, or live from
`KrakenCandleProvider`), then runs Stage 1 (backtest with realistic costs),
Stage 3 (walk-forward), the required baselines, and a performance attribution
report -- and prints the result as a readable table or, with `--json`, as
machine-readable JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from traderstack.backtest import BacktestMetrics, BaselineBacktester
from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.fee_tiers import FeeTierStamp, add_fee_tier_argument, resolve_research_costs
from traderstack.market.kraken_candles import KrakenCandleProvider
from traderstack.research.attribution import (
    AttributionReport,
    build_attribution_report,
    render_attribution_table,
)
from traderstack.research.baselines import ExcessMetrics, compare, run_baselines
from traderstack.walkforward import WalkForwardEvaluator, WalkForwardReport


def load_candles_from_json(path: Path) -> tuple[Candle, ...]:
    """Load candles from a JSON array of candle objects (one Candle per row)."""
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise TypeError(f"{path}: expected a JSON array of candle objects")
    return tuple(Candle.model_validate(row) for row in payload)


async def _load_from_kraken(symbol: str, resolution: str, count: int) -> tuple[Candle, ...]:
    provider = KrakenCandleProvider()
    return await provider.fetch(symbol, resolution, count=count)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run backtest + walk-forward + baselines + attribution over a candle history"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candles", type=Path, help="JSON file of candle objects (no network)")
    source.add_argument("--symbol", help="fetch candles live from Kraken, e.g. BTC/USD (network)")
    parser.add_argument(
        "--resolution", default="1h", help="candle interval when fetching from Kraken"
    )
    parser.add_argument(
        "--count", type=int, default=500, help="candle count when fetching from Kraken"
    )
    parser.add_argument("--starting-equity", type=float, default=10_000.0)
    # --- fee realism (#138) --- default None = PAPER_FEE_TIER taker (Tier 1 = 80 bps)
    parser.add_argument("--fee-bps", type=float, default=None)
    add_fee_tier_argument(parser)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--warmup", type=int, default=31)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--asset", default=None, help="asset label for the attribution report")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead of a table"
    )
    return parser


def _load_candles(args: argparse.Namespace) -> tuple[Candle, ...]:
    if args.candles is not None:
        return load_candles_from_json(args.candles)
    return asyncio.run(_load_from_kraken(args.symbol, args.resolution, args.count))


class ResearchReport:
    """The full result of one research-harness run."""

    def __init__(
        self,
        *,
        asset: str,
        candle_count: int,
        metrics: BacktestMetrics,
        walkforward: WalkForwardReport | None,
        baselines: dict[str, BacktestMetrics],
        excess: dict[str, ExcessMetrics],
        attribution: AttributionReport,
        # --- fee realism (#138) ---
        fee_tier: FeeTierStamp | None = None,
        fee_bps: float | None = None,
        slippage_bps: float | None = None,
    ) -> None:
        self.asset = asset
        self.candle_count = candle_count
        self.metrics = metrics
        self.walkforward = walkforward
        self.baselines = baselines
        self.excess = excess
        self.attribution = attribution
        # --- fee realism (#138) ---
        self.fee_tier = fee_tier
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def to_json(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "candles": self.candle_count,
            "metrics": self.metrics.model_dump(mode="json"),
            "walkforward": self.walkforward.model_dump(mode="json") if self.walkforward else None,
            "baselines": {name: m.model_dump(mode="json") for name, m in self.baselines.items()},
            "excess": {name: e.model_dump(mode="json") for name, e in self.excess.items()},
            "attribution": self.attribution.model_dump(mode="json"),
            # --- fee realism (#138) ---
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "fee_tier": self.fee_tier.model_dump(mode="json") if self.fee_tier else None,
        }

    def render(self) -> str:
        lines: list[str] = []
        metrics = self.metrics
        lines.append(f"Asset: {self.asset}  ({self.candle_count} candles)")
        # --- fee realism (#138) ---
        if self.fee_bps is not None and self.slippage_bps is not None:
            lines.append(f"Costs: fee={self.fee_bps:g} bps + slippage={self.slippage_bps:g} bps")
        if self.fee_tier is not None:
            lines.append(self.fee_tier.render_line())
        lines.append("-" * 60)
        lines.append(f"Total return:      {metrics.total_return:.2%}")
        lines.append(f"Benchmark return:  {metrics.benchmark_return:.2%}")
        lines.append(f"Excess return:     {metrics.excess_return:.2%}")
        lines.append(f"Sharpe:            {metrics.sharpe:.3f}")
        lines.append(f"Sortino:           {metrics.sortino:.3f}")
        lines.append(f"Calmar:            {metrics.calmar:.3f}")
        lines.append(f"Max drawdown:      {metrics.max_drawdown:.2%}")
        lines.append(f"Profit factor:     {metrics.profit_factor:.3f}")
        lines.append(f"Expectancy/trade:  {metrics.expectancy:.2%}")
        lines.append(f"Annualized vol:    {metrics.annualized_volatility:.2%}")
        lines.append(f"Turnover:          {metrics.turnover:.2f}x")
        lines.append(f"Total fees:        ${metrics.total_fees:,.2f}")
        lines.append(f"Trades:            {metrics.trades}")

        if self.walkforward is not None:
            lines.append("\nWalk-forward")
            lines.append("-" * 60)
            lines.append(f"Folds:              {len(self.walkforward.folds)}")
            lines.append(f"Mean total return:  {self.walkforward.mean_total_return:.2%}")
            lines.append(f"Mean excess return: {self.walkforward.mean_excess_return:.2%}")
            lines.append(f"Mean sharpe:        {self.walkforward.mean_sharpe:.3f}")
            lines.append(f"Worst drawdown:     {self.walkforward.worst_drawdown:.2%}")
        else:
            lines.append("\nWalk-forward: insufficient candles for one fold")

        lines.append("\nBaselines (excess over each)")
        lines.append("-" * 60)
        for name, excess_metrics in self.excess.items():
            lines.append(
                f"{name:<20} strategy={excess_metrics.strategy_total_return:+.2%}  "
                f"baseline={excess_metrics.baseline_total_return:+.2%}  "
                f"excess={excess_metrics.excess_total_return:+.2%}  "
                f"excess_sharpe={excess_metrics.excess_sharpe:+.3f}"
            )

        lines.append("")
        lines.append(render_attribution_table(self.attribution))
        return "\n".join(lines)


def run(args: argparse.Namespace, settings: Settings | None = None) -> ResearchReport:
    candles = _load_candles(args)
    if not candles:
        raise ValueError("no candles loaded")
    asset = args.asset or candles[0].symbol

    # --- fee realism (#138) ---
    # Precedence: --fee-bps (stamped "explicit") > --fee-tier > PAPER_FEE_TIER;
    # the tier fee is max(PRETRADE_FEE_BPS, tier taker). Taker leg only.
    costs = resolve_research_costs(
        fee_bps=args.fee_bps,
        fee_tier=args.fee_tier,
        settings=settings or Settings(),
        slippage_bps=args.slippage_bps,
    )
    backtester = BaselineBacktester(
        starting_equity=args.starting_equity,
        fee_bps=costs.fee_bps,
        slippage_bps=costs.slippage_bps,
        warmup=args.warmup,
    )
    metrics = backtester.run(candles)

    walkforward_report: WalkForwardReport | None
    try:
        evaluator = WalkForwardEvaluator(
            backtester=backtester,
            train_size=args.train_size,
            test_size=args.test_size,
            step_size=args.step_size,
        )
        walkforward_report = evaluator.evaluate(candles)
    except ValueError:
        walkforward_report = None

    baseline_metrics = run_baselines(
        candles, starting_equity=args.starting_equity, warmup=args.warmup
    )
    excess = compare(metrics, baseline_metrics)
    attribution = build_attribution_report(metrics.trade_log, asset=asset)

    return ResearchReport(
        asset=asset,
        candle_count=len(candles),
        metrics=metrics,
        walkforward=walkforward_report,
        baselines=baseline_metrics,
        excess=excess,
        attribution=attribution,
        # --- fee realism (#138) ---
        fee_tier=costs.stamp,
        fee_bps=costs.fee_bps,
        slippage_bps=costs.slippage_bps,
    )


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = run(args)
    if args.json:
        print(json.dumps(report.to_json(), indent=2, default=str))
    else:
        print(report.render())


if __name__ == "__main__":
    main()
