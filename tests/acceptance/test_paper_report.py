"""Epic 10: the paper performance report, on synthetic fixtures.

The fixtures are written with the *production* models -- a ``RuntimeResult``
dumped exactly as ``JsonlAuditSink`` writes it, and an ``ExecutionLedgerState``
exactly as ``JsonExecutionLedgerStore`` writes it -- so the report is tested
against the file formats it will actually be pointed at.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.acceptance.market import SyntheticMarket
from traderstack.acceptance.report import (
    build_parser,
    build_report,
    fills_from_ledger,
    load_runtime_events,
    main,
    marks_from_events,
    metrics_from_run,
    reconstruct,
    strategy_ids_by_decision,
)
from traderstack.audit import JsonlAuditSink
from traderstack.candles import Candle
from traderstack.execution.ledger import (
    ExecutionLedgerState,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.runtime import RuntimeResult

START = datetime(2026, 8, 1, tzinfo=UTC)
STEP = timedelta(hours=1)
TICKS = 240
# TradeProposal.decision_id is a UUID; fixed values keep the fixture stable.
BUY_DECISION = "11111111-1111-4111-8111-111111111111"
SELL_DECISION = "22222222-2222-4222-8222-222222222222"


def _prices() -> list[float]:
    """A deterministic up-then-down path so drawdown and Sharpe are non-trivial."""

    return [
        20_000.0 * (1.0 + 0.004 * min(index, 160) - 0.002 * max(index - 160, 0))
        for index in range(TICKS)
    ]


async def write_audit(path: Path, *, decision_at: dict[int, str]) -> None:
    sink = JsonlAuditSink(path)
    for index, price in enumerate(_prices()):
        tick = MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=START + STEP * index,
            bid=price * 0.9998,
            ask=price * 1.0002,
            last=price,
        )
        pipeline = PipelineResult(accepted_market_data=True)
        decision_id = decision_at.get(index)
        if decision_id is not None:
            proposal = TradeProposal(
                decision_id=decision_id,
                strategy_id="vertical-slice-v1",
                asset="BTC",
                side=Side.BUY,
                confidence=0.5,
                requested_notional_usd=1_000,
                thesis="fixture",
                signal_ids=["pretrade-backtest-gate-v1"],
                source_freshness_seconds=1.0,
            )
            pipeline = PipelineResult(
                accepted_market_data=True,
                proposal=proposal,
                risk_result=RiskResult(
                    decision_id=proposal.decision_id,
                    decision=RiskDecision.ALLOW,
                    approved_notional_usd=1_000,
                    policy_version="mvp-v1+fixture",
                ),
                paper_order=PaperOrderIntent(
                    decision_id=decision_id, asset="BTC", side=Side.BUY, notional_usd=1_000
                ),
            )
        await sink(RuntimeResult(tick=tick, references=[], pipeline=pipeline))


def write_ledger(path: Path, orders: list[ExecutionOrder]) -> None:
    state = ExecutionLedgerState(orders={order.order_id: order for order in orders})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def filled_order(
    order_id: str, decision_id: str, side: Side, quantity: float, price: float, index: int
) -> ExecutionOrder:
    return ExecutionOrder(
        order_id=order_id,
        decision_id=decision_id,
        asset="BTC",
        side=side,
        requested_quantity=quantity,
        state=OrderLifecycleState.FILLED,
        filled_quantity=quantity,
        average_fill_price_usd=price,
        last_updated_at=START + STEP * index,
    )


def write_candles(path: Path) -> None:
    market = SyntheticMarket(
        symbols=("BTC/USD",),
        seed=5,
        history=TICKS,
        anchor=START + STEP * (TICKS - 1),
    )
    candles: list[Candle] = list(market.candles("BTC/USD"))
    path.write_text(
        json.dumps([candle.model_dump(mode="json") for candle in candles]), encoding="utf-8"
    )


@pytest.fixture
async def paper_run(tmp_path: Path) -> dict[str, Path]:
    audit = tmp_path / "runtime.jsonl"
    ledger = tmp_path / "execution_ledger.json"
    candles = tmp_path / "candles.json"
    prices = _prices()
    await write_audit(audit, decision_at={40: BUY_DECISION, 180: SELL_DECISION})
    write_ledger(
        ledger,
        [
            filled_order("ts-buy", BUY_DECISION, Side.BUY, 0.05, prices[40], 40),
            filled_order("ts-sell", SELL_DECISION, Side.SELL, 0.05, prices[180], 180),
        ],
    )
    write_candles(candles)
    return {"audit": audit, "ledger": ledger, "candles": candles}


# --- parsing ----------------------------------------------------------------


async def test_marks_and_fills_are_read_back_from_the_real_file_formats(paper_run) -> None:
    events = load_runtime_events(paper_run["audit"])
    marks = marks_from_events(events, asset="BTC")
    fills = fills_from_ledger(paper_run["ledger"], asset="BTC")

    assert len(events) == TICKS
    assert len(marks) == TICKS
    assert marks[0].observed_at == START
    assert marks[40].decision_id == BUY_DECISION
    assert [fill.side for fill in fills] == [Side.BUY, Side.SELL]
    assert fills[0].quantity == pytest.approx(0.05)


async def test_a_truncated_audit_tail_does_not_lose_the_run(paper_run) -> None:
    with paper_run["audit"].open("a", encoding="utf-8") as handle:
        handle.write('{"tick": {"symbol": "BTC/US')

    assert len(load_runtime_events(paper_run["audit"])) == TICKS


def test_unfilled_orders_are_not_treated_as_trades(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    write_ledger(
        ledger,
        [
            ExecutionOrder(
                order_id="ts-open",
                decision_id="d1",
                asset="BTC",
                side=Side.BUY,
                requested_quantity=0.05,
                state=OrderLifecycleState.SUBMITTED,
            )
        ],
    )

    assert fills_from_ledger(ledger) == []


# --- reconstruction ---------------------------------------------------------


async def test_the_equity_curve_and_round_trip_match_the_fills(paper_run) -> None:
    events = load_runtime_events(paper_run["audit"])
    run = reconstruct(
        marks_from_events(events),
        fills_from_ledger(paper_run["ledger"]),
        starting_equity=10_000.0,
        strategy_ids=strategy_ids_by_decision(events),
    )

    prices = _prices()
    assert len(run.equity_curve) == TICKS
    assert run.equity_curve[0][1] == pytest.approx(10_000.0)
    assert run.fills == 2
    assert len(run.trades) == 1

    trade = run.trades[0]
    assert trade.entry_price == pytest.approx(prices[40])
    assert trade.exit_price == pytest.approx(prices[180])
    assert trade.return_pct == pytest.approx(prices[180] / prices[40] - 1.0)
    assert trade.strategy_ids == ["pretrade-backtest-gate-v1"]

    expected_equity = 10_000.0 + 0.05 * (prices[180] - prices[40])
    assert run.ending_equity == pytest.approx(expected_equity)
    assert run.open_quantity == pytest.approx(0.0)


async def test_open_inventory_is_closed_at_the_final_mark(paper_run) -> None:
    events = load_runtime_events(paper_run["audit"])
    fills = [fill for fill in fills_from_ledger(paper_run["ledger"]) if fill.side is Side.BUY]
    run = reconstruct(marks_from_events(events), fills, starting_equity=10_000.0)

    assert len(run.trades) == 1
    assert run.trades[0].exit_price == pytest.approx(_prices()[-1])
    assert run.open_quantity == pytest.approx(0.05)


async def test_fees_are_only_modelled_when_asked_for(paper_run) -> None:
    events = load_runtime_events(paper_run["audit"])
    marks = marks_from_events(events)
    fills = fills_from_ledger(paper_run["ledger"])

    free = reconstruct(marks, fills, starting_equity=10_000.0)
    charged = reconstruct(marks, fills, starting_equity=10_000.0, fee_bps=10.0)

    assert free.total_fees == 0.0
    assert charged.total_fees > 0
    assert charged.ending_equity < free.ending_equity


async def test_metrics_use_the_backtest_statistics(paper_run) -> None:
    events = load_runtime_events(paper_run["audit"])
    run = reconstruct(
        marks_from_events(events), fills_from_ledger(paper_run["ledger"]), starting_equity=10_000.0
    )
    metrics = metrics_from_run(run)

    assert metrics.starting_equity == pytest.approx(10_000.0)
    assert metrics.total_return > 0
    assert metrics.trades == 1
    assert metrics.max_drawdown >= 0
    assert metrics.sharpe != 0.0
    assert metrics.annualized_volatility > 0
    assert metrics.turnover > 0


# --- report -----------------------------------------------------------------


async def test_the_report_compares_paper_against_every_baseline(paper_run) -> None:
    report = build_report(
        audit_path=paper_run["audit"],
        ledger_path=paper_run["ledger"],
        candles=tuple(
            Candle.model_validate(row)
            for row in json.loads(paper_run["candles"].read_text(encoding="utf-8"))
        ),
        starting_equity=10_000.0,
    )

    assert report.asset == "BTC"
    assert report.period_start == START
    assert report.cycles == TICKS
    assert report.fills == 2
    assert report.baseline_candles > 32
    assert set(report.baselines) == {
        "buy_and_hold",
        "time_series_momentum",
        "ma_trend",
        "mean_reversion",
        "volatility_target",
    }
    assert set(report.excess) == set(report.baselines)
    for name, excess in report.excess.items():
        assert excess.baseline == name
        assert excess.strategy_total_return == pytest.approx(report.metrics.total_return)
        assert excess.excess_total_return == pytest.approx(
            report.metrics.total_return - report.baselines[name].total_return
        )

    assert report.attribution.total_trades == 1
    assert [bucket.key for bucket in report.attribution.by_strategy] == [
        "pretrade-backtest-gate-v1"
    ]

    rendered = report.render()
    assert "Paper performance -- BTC" in rendered
    assert "buy_and_hold" in rendered
    assert "Performance Attribution" in rendered


async def test_the_report_says_when_fees_are_not_modelled(paper_run) -> None:
    report = build_report(
        audit_path=paper_run["audit"], ledger_path=paper_run["ledger"], starting_equity=10_000.0
    )

    assert any("fees and slippage are NOT modelled" in note for note in report.notes)
    assert report.excess == {}
    assert "baselines not computed" in report.render()


async def test_a_run_with_no_fills_is_reported_as_flat_not_as_an_error(tmp_path: Path) -> None:
    audit = tmp_path / "runtime.jsonl"
    ledger = tmp_path / "ledger.json"
    await write_audit(audit, decision_at={})
    write_ledger(ledger, [])

    report = build_report(audit_path=audit, ledger_path=ledger, starting_equity=10_000.0)

    assert report.fills == 0
    assert report.metrics.total_return == pytest.approx(0.0)
    assert report.metrics.trades == 0
    assert any("records no fills" in note for note in report.notes)


async def test_too_few_candles_skips_the_baselines_with_a_note(paper_run) -> None:
    candles = tuple(
        Candle.model_validate(row)
        for row in json.loads(paper_run["candles"].read_text(encoding="utf-8"))
    )[:5]

    report = build_report(
        audit_path=paper_run["audit"],
        ledger_path=paper_run["ledger"],
        candles=candles,
        starting_equity=10_000.0,
    )

    assert report.baselines == {}
    assert any("baselines need more than warmup" in note for note in report.notes)


async def test_an_audit_trail_with_no_ticks_is_refused(tmp_path: Path) -> None:
    audit = tmp_path / "empty.jsonl"
    audit.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no runtime ticks"):
        build_report(audit_path=audit, ledger_path=tmp_path / "missing.json")


# --- CLI --------------------------------------------------------------------


async def test_main_prints_json(paper_run, capsys) -> None:
    code = main(
        [
            "--audit-path",
            str(paper_run["audit"]),
            "--ledger-path",
            str(paper_run["ledger"]),
            "--candles",
            str(paper_run["candles"]),
            "--fee-bps",
            "10",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["asset"] == "BTC"
    assert payload["fee_bps"] == 10.0
    assert payload["metrics"]["trades"] == 1
    assert payload["excess"]["buy_and_hold"]["baseline"] == "buy_and_hold"


async def test_main_prints_a_table(paper_run, capsys) -> None:
    code = main(
        [
            "--audit-path",
            str(paper_run["audit"]),
            "--ledger-path",
            str(paper_run["ledger"]),
            "--asset",
            "BTC",
        ]
    )

    assert code == 0
    assert "Paper performance -- BTC" in capsys.readouterr().out


def test_the_parser_defaults_point_at_the_documented_paths() -> None:
    args = build_parser().parse_args([])

    assert args.audit_path == Path("var/audit/runtime.jsonl")
    assert args.ledger_path == Path("var/state/execution_ledger.json")
    assert args.fee_bps == 0.0
