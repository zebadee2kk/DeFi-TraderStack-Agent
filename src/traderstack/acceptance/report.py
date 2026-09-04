"""``traderstack-paper-report``: paper performance versus baselines (Epic 10).

Reads what a paper run actually produced -- the runtime audit JSONL written by
``JsonlAuditSink`` and the execution ledger JSON written by
``JsonExecutionLedgerStore`` -- reconstructs the paper equity curve and trade
list, scores it with the same ``BacktestMetrics`` the research harness uses, and
compares it against ``research.baselines`` over the same period's candles.

Two deliberate constraints:

* The metrics are computed with the *same* statistics as ``backtest.py``
  (``_sharpe`` / ``_sortino`` / ``_std``), not a re-implementation, so a paper
  number and a backtest number mean the same thing and are safe to subtract.
* Nothing is inferred that the audit trail does not record. Fees are not in the
  paper receipts, so they default to zero and can only be *estimated* with an
  explicit ``--fee-bps``; the report says which it used.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt
from pathlib import Path
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

# Reusing the private statistics helpers is intentional: the paper metrics must
# be computed identically to the backtest metrics they are compared against.
from traderstack.backtest import BacktestMetrics, BacktestTrade, _mean, _sharpe, _sortino, _std
from traderstack.candles import Candle
from traderstack.execution.ledger import ExecutionLedgerState, OrderLifecycleState
from traderstack.models import Side
from traderstack.research.attribution import (
    AttributionReport,
    build_attribution_report,
    render_attribution_table,
)
from traderstack.research.baselines import ExcessMetrics, compare, run_baselines
from traderstack.strategies import Regime

SECONDS_PER_YEAR = 365.0 * 86_400.0


# --- inputs -----------------------------------------------------------------


class MarkPoint(BaseModel):
    """One mark-to-market observation taken from a runtime audit line."""

    observed_at: datetime
    asset: str
    price_usd: float = Field(gt=0)
    decision_id: str | None = None
    strategy_ids: list[str] = Field(default_factory=list)


class PaperFill(BaseModel):
    """One executed paper order, reconstructed from the execution ledger."""

    observed_at: datetime
    order_id: str
    decision_id: str
    asset: str
    side: Side
    quantity: float = Field(gt=0)
    price_usd: float = Field(gt=0)

    @property
    def notional_usd(self) -> float:
        return self.quantity * self.price_usd


def load_runtime_events(path: Path) -> list[dict[str, Any]]:
    """Parse the runtime audit JSONL, skipping blank and unreadable lines."""

    events: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # A truncated tail (killed mid-write) must not lose the whole run.
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def marks_from_events(events: list[dict[str, Any]], *, asset: str | None = None) -> list[MarkPoint]:
    """Every validated tick in the audit trail, as a mark-to-market series."""

    marks: list[MarkPoint] = []
    for event in events:
        tick = event.get("tick")
        if not isinstance(tick, dict):
            continue
        symbol = str(tick.get("symbol", ""))
        base = symbol.split("/", 1)[0].upper()
        if asset is not None and base != asset.upper():
            continue
        pipeline = event.get("pipeline") or {}
        proposal = pipeline.get("proposal") or {}
        marks.append(
            MarkPoint(
                observed_at=tick["observed_at"],
                asset=base,
                price_usd=float(tick["last"]),
                decision_id=proposal.get("decision_id"),
                strategy_ids=list(proposal.get("signal_ids") or []),
            )
        )
    marks.sort(key=lambda mark: mark.observed_at)
    return marks


def strategy_ids_by_decision(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Decision id -> the signal ids that produced it, for attribution."""

    mapping: dict[str, list[str]] = {}
    for event in events:
        proposal = (event.get("pipeline") or {}).get("proposal")
        if not isinstance(proposal, dict):
            continue
        decision_id = proposal.get("decision_id")
        if isinstance(decision_id, str):
            mapping[decision_id] = list(proposal.get("signal_ids") or [proposal.get("strategy_id")])
    return mapping


def fills_from_ledger(path: Path, *, asset: str | None = None) -> list[PaperFill]:
    """Executed quantity per ledger order, oldest first.

    Only orders the venue actually filled carry a quantity and an average price;
    submitted-but-unfilled orders are deliberately excluded rather than assumed
    to have traded.
    """

    state = ExecutionLedgerState.model_validate_json(Path(path).read_text(encoding="utf-8"))
    fills: list[PaperFill] = []
    for order in state.orders.values():
        if order.filled_quantity <= 0 or order.average_fill_price_usd is None:
            continue
        if order.state in {OrderLifecycleState.REJECTED, OrderLifecycleState.EXPIRED}:
            continue
        if asset is not None and order.asset.upper() != asset.upper():
            continue
        fills.append(
            PaperFill(
                observed_at=order.last_updated_at,
                order_id=order.order_id,
                decision_id=order.decision_id,
                asset=order.asset.upper(),
                side=order.side,
                quantity=order.filled_quantity,
                price_usd=order.average_fill_price_usd,
            )
        )
    fills.sort(key=lambda fill: fill.observed_at)
    return fills


def load_candles_json(path: Path) -> tuple[Candle, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError(f"{path}: expected a JSON array of candle objects")
    return tuple(Candle.model_validate(row) for row in payload)


def candles_in_period(
    candles: tuple[Candle, ...], start: datetime, end: datetime
) -> tuple[Candle, ...]:
    """The candles covering the paper run, so baselines see the same market."""

    return tuple(candle for candle in candles if start <= candle.opened_at <= end)


# --- reconstruction ---------------------------------------------------------


@dataclass
class PaperRun:
    """The paper run as an equity curve plus a round-trip trade list."""

    starting_equity: float
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    fills: int = 0
    total_fees: float = 0.0
    turnover_usd: float = 0.0
    open_quantity: float = 0.0

    @property
    def ending_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.starting_equity


def reconstruct(
    marks: list[MarkPoint],
    fills: list[PaperFill],
    *,
    starting_equity: float,
    fee_bps: float = 0.0,
    strategy_ids: dict[str, list[str]] | None = None,
) -> PaperRun:
    """Replay marks and fills into an equity curve and FIFO round trips.

    Cash and inventory move only on fills; equity is marked at every tick the
    audit trail recorded. Unclosed inventory at the end is closed at the final
    mark so it appears in the trade list rather than silently vanishing.
    """

    if starting_equity <= 0:
        raise ValueError("starting_equity must be positive")
    run = PaperRun(starting_equity=starting_equity)
    strategy_ids = strategy_ids or {}
    cash = starting_equity
    quantity = 0.0
    # FIFO lots: (quantity, price, time, decision_id)
    lots: deque[tuple[float, float, datetime, str]] = deque()
    last_price = marks[0].price_usd if marks else 0.0

    events: list[tuple[datetime, int, MarkPoint | PaperFill]] = [
        # Fills sort before marks at the same instant, so the tick that recorded
        # a submission also marks the position it created.
        *((fill.observed_at, 0, fill) for fill in fills),
        *((mark.observed_at, 1, mark) for mark in marks),
    ]
    events.sort(key=lambda item: (item[0], item[1]))

    for moment, _order, event in events:
        if isinstance(event, PaperFill):
            fee = event.notional_usd * fee_bps / 10_000
            run.fills += 1
            run.total_fees += fee
            run.turnover_usd += event.notional_usd
            cash -= fee
            last_price = event.price_usd
            if event.side is Side.BUY:
                cash -= event.notional_usd
                quantity += event.quantity
                lots.append((event.quantity, event.price_usd, moment, event.decision_id))
            else:
                cash += event.notional_usd
                quantity -= event.quantity
                _close_lots(run, lots, event, strategy_ids)
            continue

        last_price = event.price_usd
        run.equity_curve.append((moment, cash + quantity * last_price))

    if lots and last_price > 0:
        closing_time = run.equity_curve[-1][0] if run.equity_curve else lots[-1][2]
        synthetic = PaperFill(
            observed_at=closing_time,
            order_id="mark-to-market",
            decision_id=lots[0][3],
            asset=fills[0].asset if fills else "",
            side=Side.SELL,
            quantity=sum(lot[0] for lot in lots),
            price_usd=last_price,
        )
        _close_lots(run, lots, synthetic, strategy_ids)
    run.open_quantity = max(quantity, 0.0)
    return run


def _close_lots(
    run: PaperRun,
    lots: deque[tuple[float, float, datetime, str]],
    fill: PaperFill,
    strategy_ids: dict[str, list[str]],
) -> None:
    """Match a sell against open buy lots, FIFO, recording one trade per lot."""

    remaining = fill.quantity
    while remaining > 1e-12 and lots:
        lot_quantity, lot_price, lot_time, decision_id = lots[0]
        matched = min(lot_quantity, remaining)
        notional = matched * lot_price
        run.trades.append(
            BacktestTrade(
                entry_time=lot_time,
                exit_time=fill.observed_at,
                entry_price=lot_price,
                exit_price=fill.price_usd,
                side=Side.BUY,
                return_pct=(fill.price_usd / lot_price) - 1.0,
                regime=Regime.RANGE,
                strategy_ids=strategy_ids.get(decision_id, ["paper"]),
                notional_usd=notional,
                fees_paid=0.0,
            )
        )
        remaining -= matched
        if matched >= lot_quantity - 1e-12:
            lots.popleft()
        else:
            lots[0] = (lot_quantity - matched, lot_price, lot_time, decision_id)


def periods_per_year(curve: list[tuple[datetime, float]]) -> float:
    """Bars per year implied by the observed spacing of the equity curve."""

    if len(curve) < 2:
        return 365.0
    gaps = [
        (curve[index][0] - curve[index - 1][0]).total_seconds() for index in range(1, len(curve))
    ]
    spacing = median([gap for gap in gaps if gap > 0] or [86_400.0])
    return SECONDS_PER_YEAR / spacing


def metrics_from_run(run: PaperRun) -> BacktestMetrics:
    """Score the reconstructed run with the research harness's own statistics."""

    curve = run.equity_curve
    equity = run.ending_equity
    returns = [
        curve[index][1] / curve[index - 1][1] - 1.0
        for index in range(1, len(curve))
        if curve[index - 1][1] > 0
    ]
    periods = periods_per_year(curve)

    peak = run.starting_equity
    max_drawdown = 0.0
    for _, value in curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, 1.0 - value / peak)

    total_return = equity / run.starting_equity - 1.0
    benchmark_return = 0.0
    bars = max(len(curve) - 1, 1)
    annualized_return = (
        (equity / run.starting_equity) ** (periods / bars) - 1.0 if equity > 0 else -1.0
    )
    calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0.0

    gains = [trade.return_pct for trade in run.trades if trade.return_pct > 0]
    losses = [trade.return_pct for trade in run.trades if trade.return_pct < 0]
    gross_loss = abs(sum(losses))
    profit_factor = (
        sum(gains) / gross_loss if gross_loss > 1e-12 else (sum(gains) if gains else 0.0)
    )

    return BacktestMetrics(
        starting_equity=run.starting_equity,
        ending_equity=max(equity, 1e-9),
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        max_drawdown=max_drawdown,
        sharpe=_sharpe(returns, periods),
        trades=len(run.trades),
        sortino=_sortino(returns, periods),
        calmar=calmar,
        profit_factor=profit_factor,
        expectancy=_mean([trade.return_pct for trade in run.trades]),
        annualized_volatility=_std(returns) * sqrt(periods),
        turnover=run.turnover_usd / run.starting_equity,
        total_fees=run.total_fees,
        trade_log=list(run.trades),
    )


# --- report -----------------------------------------------------------------


class PaperPerformanceReport(BaseModel):
    """Paper performance, its baselines, the excess, and the attribution."""

    asset: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    cycles: int = 0
    marks: int = 0
    fills: int = 0
    open_quantity: float = 0.0
    fee_bps: float = 0.0
    metrics: BacktestMetrics
    baselines: dict[str, BacktestMetrics] = Field(default_factory=dict)
    excess: dict[str, ExcessMetrics] = Field(default_factory=dict)
    attribution: AttributionReport
    baseline_candles: int = 0
    notes: list[str] = Field(default_factory=list)

    def render(self) -> str:
        metrics = self.metrics
        lines = [
            f"Paper performance -- {self.asset}",
            "=" * 72,
            f"Period:            {self.period_start} .. {self.period_end}",
            f"Runtime cycles:    {self.cycles}   marks: {self.marks}   fills: {self.fills}",
            f"Fee model:         {self.fee_bps:.2f} bps (estimated; paper receipts carry no fees)",
            "",
            f"Total return:      {metrics.total_return:.2%}",
            f"Sharpe:            {metrics.sharpe:.3f}",
            f"Sortino:           {metrics.sortino:.3f}",
            f"Calmar:            {metrics.calmar:.3f}",
            f"Max drawdown:      {metrics.max_drawdown:.2%}",
            f"Profit factor:     {metrics.profit_factor:.3f}",
            f"Expectancy/trade:  {metrics.expectancy:.2%}",
            f"Annualized vol:    {metrics.annualized_volatility:.2%}",
            f"Turnover:          {metrics.turnover:.2f}x",
            f"Total fees:        ${metrics.total_fees:,.2f}",
            f"Round trips:       {metrics.trades}",
        ]
        lines.append("")
        lines.append(f"Baselines over the same {self.baseline_candles} candles")
        lines.append("-" * 72)
        if not self.excess:
            lines.append("  (no candle history supplied -- baselines not computed)")
        for name, excess in sorted(self.excess.items()):
            lines.append(
                f"{name:<20} paper={excess.strategy_total_return:+.2%}  "
                f"baseline={excess.baseline_total_return:+.2%}  "
                f"excess={excess.excess_total_return:+.2%}  "
                f"excess_sharpe={excess.excess_sharpe:+.3f}"
            )
        lines.append("")
        lines.append(render_attribution_table(self.attribution))
        if self.notes:
            lines.append("\nNotes")
            lines.append("-" * 72)
            lines.extend(f"  - {note}" for note in self.notes)
        return "\n".join(lines)


def build_report(
    *,
    audit_path: Path,
    ledger_path: Path,
    candles: tuple[Candle, ...] = (),
    asset: str | None = None,
    starting_equity: float = 10_000.0,
    fee_bps: float = 0.0,
    warmup: int = 31,
) -> PaperPerformanceReport:
    events = load_runtime_events(audit_path)
    marks = marks_from_events(events, asset=asset)
    if not marks:
        raise ValueError(f"{audit_path}: no runtime ticks to build an equity curve from")
    resolved_asset = asset.upper() if asset else marks[0].asset
    fills = (
        fills_from_ledger(ledger_path, asset=resolved_asset) if Path(ledger_path).exists() else []
    )

    run = reconstruct(
        marks,
        fills,
        starting_equity=starting_equity,
        fee_bps=fee_bps,
        strategy_ids=strategy_ids_by_decision(events),
    )
    metrics = metrics_from_run(run)

    notes: list[str] = []
    if not fills:
        notes.append(
            "The execution ledger records no fills, so the paper equity curve is flat: "
            "orders were submitted but never reconciled to a fill."
        )
    if run.open_quantity > 0:
        notes.append(
            "Open inventory at the end of the period was closed at the final mark "
            "so it appears in the trade list."
        )
    if fee_bps == 0:
        notes.append("--fee-bps was 0, so fees and slippage are NOT modelled in these numbers.")

    period_start = marks[0].observed_at
    period_end = marks[-1].observed_at
    window = candles_in_period(candles, period_start, period_end) if candles else ()
    baselines: dict[str, BacktestMetrics] = {}
    if len(window) > warmup + 1:
        baselines = run_baselines(window, starting_equity=starting_equity, warmup=warmup)
    elif candles:
        notes.append(
            f"Only {len(window)} candle(s) fall inside the paper period; "
            f"baselines need more than warmup ({warmup}) bars, so they were skipped."
        )

    return PaperPerformanceReport(
        asset=resolved_asset,
        period_start=period_start,
        period_end=period_end,
        cycles=len(events),
        marks=len(marks),
        fills=run.fills,
        open_quantity=run.open_quantity,
        fee_bps=fee_bps,
        metrics=metrics,
        baselines=baselines,
        excess=compare(metrics, baselines) if baselines else {},
        attribution=build_attribution_report(run.trades, asset=resolved_asset),
        baseline_candles=len(window),
        notes=notes,
    )


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct the paper equity curve from the runtime audit trail and the "
            "execution ledger, and compare it against the research baselines."
        )
    )
    parser.add_argument("--audit-path", type=Path, default=Path("var/audit/runtime.jsonl"))
    parser.add_argument("--ledger-path", type=Path, default=Path("var/state/execution_ledger.json"))
    parser.add_argument(
        "--candles",
        type=Path,
        default=None,
        help="JSON array of candles for the baselines (no network)",
    )
    parser.add_argument(
        "--candle-store",
        action="store_true",
        help="load the baseline candles from the Postgres candle store instead of a file",
    )
    parser.add_argument("--candle-interval", default="1h")
    parser.add_argument("--asset", default=None, help="restrict the report to one base asset")
    parser.add_argument("--starting-equity", type=float, default=10_000.0)
    parser.add_argument(
        "--fee-bps",
        type=float,
        default=0.0,
        help="estimated round-trip fee/slippage in bps; paper receipts carry no fees",
    )
    parser.add_argument("--warmup", type=int, default=31)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    return parser


def _load_candles(args: argparse.Namespace) -> tuple[Candle, ...]:
    if args.candles is not None:
        return load_candles_json(args.candles)
    if args.candle_store:
        # Imported lazily: the store pulls in SQLAlchemy/asyncpg and needs a
        # reachable database, neither of which a file-based report requires.
        import asyncio

        from traderstack.candle_store import PostgresCandleStore
        from traderstack.config import Settings

        settings = Settings()
        symbol = f"{(args.asset or 'BTC').upper()}/USD"

        async def load() -> tuple[Candle, ...]:
            store = PostgresCandleStore(settings.database_url)
            try:
                return await store.load(symbol, args.candle_interval)
            finally:
                await store.close()

        return asyncio.run(load())
    return ()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        audit_path=args.audit_path,
        ledger_path=args.ledger_path,
        candles=_load_candles(args),
        asset=args.asset,
        starting_equity=args.starting_equity,
        fee_bps=args.fee_bps,
        warmup=args.warmup,
    )
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
    else:
        print(report.render())
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
