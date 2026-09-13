"""Protective exits fill the held quantity end to end under adverse slippage (#130).

Each rule goes book -> snapshot -> ``VerticalSlicePipeline.process`` ->
``RiskEngine`` -> ``PaperFillSimulator`` with non-zero ``PAPER_SLIPPAGE_BPS``.
Before #130 the planner converted the exit notional back to quantity at the
lower sell price and asked for more units than the book held, so the
protective fill was rejected as a short sale. Now the intent carries the held
quantity and the planner caps to it: the position goes flat, the sell still
lands at the adverse price and ``PAPER_FEE_BPS`` is charged on the capped
quantity.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.paper_fill import PaperFillSimulator, PaperFillStatus
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import RiskDecision, Side
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
ENTRY = 100.0
HELD = 1.0
FEE_BPS = 10.0
# 40 bps is the largest case that stays inside the planner's default 50 bps
# EXECUTION_MAX_SLIPPAGE_BPS gate for every mark (50 bps sits on the boundary).
SLIPPAGE_CASES = (0.0, 5.0, 25.0, 40.0)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "kill_switch": False,
        "exit_stop_loss_pct": 0.02,
        "exit_take_profit_pct": 0.04,
        "exit_trailing_stop_pct": 0.0,
        "exit_time_stop_bars": 24,
        "exit_on_thesis_invalidation": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _tick(last: float) -> MarketTick:
    # Two-bps spread around ``last`` so the pipeline's spread gate passes and
    # ``tick.mid`` equals the mark the exit was sized at.
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=NOW,
        bid=last * (1 - 0.0001),
        ask=last * (1 + 0.0001),
        last=last,
    )


def _seed_book(
    *, mark: float, opened_at: datetime = NOW, high_water: float | None = None
) -> InMemoryPortfolioBook:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000.0)
    book.apply_fill("BTC", Side.BUY, HELD, ENTRY, now=opened_at, strategy_id="momentum_v1")
    if high_water is not None:
        book.mark("BTC", high_water)
    book.mark("BTC", mark)
    return book


def _run_exit(
    book: InMemoryPortfolioBook, *, mark: float, slippage_bps: float, **overrides: object
):
    settings = _settings(**overrides)
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    tick = _tick(mark)
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=mark)]
    result = pipe.process(tick, refs, book.snapshot(now=NOW), now=NOW)
    assert result.paper_order is not None, result.rejection_reasons
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=FEE_BPS, paper_slippage_bps=slippage_bps)
    outcome = simulator.apply(result.paper_order, mid_usd=tick.mid, ledger=ledger, portfolio=book)
    return result, outcome, ledger, tick


def _assert_flat_at_adverse_price(
    result,
    outcome,
    ledger: ExecutionLedger,
    book: InMemoryPortfolioBook,
    tick: MarketTick,
    *,
    slippage_bps: float,
    expected_quantity: float = HELD,
) -> None:
    assert result.paper_order.max_quantity == pytest.approx(HELD)
    assert result.risk_result is not None
    assert result.risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.reason_code is None
    assert outcome.fill is not None and outcome.plan is not None

    fill_price = tick.mid * (1.0 - slippage_bps / 10_000.0)
    assert outcome.fill.price_usd == pytest.approx(fill_price)
    assert outcome.fill.quantity == pytest.approx(expected_quantity)
    assert outcome.fill.quantity <= HELD + 1e-12
    assert outcome.plan.quantity <= HELD + 1e-12
    assert outcome.plan.notional_usd <= result.paper_order.notional_usd + 1e-9

    expected_fee = expected_quantity * fill_price * FEE_BPS / 10_000.0
    assert outcome.fee_usd == pytest.approx(expected_fee)
    assert book.positions["BTC"].quantity == pytest.approx(HELD - expected_quantity)
    assert book.positions["BTC"].fees_paid_usd == pytest.approx(expected_fee)

    # Cash: NAV - entry cost + proceeds at the adverse price - fee.
    expected_cash = 10_000.0 - HELD * ENTRY + expected_quantity * fill_price - expected_fee
    assert book.cash_usd == pytest.approx(expected_cash)
    # Realized PnL reflects slippage: below what a mid fill would have made.
    expected_pnl = expected_quantity * (fill_price - ENTRY) - expected_fee
    assert book.realized_pnl_usd == pytest.approx(expected_pnl)
    if slippage_bps > 0:
        assert book.realized_pnl_usd < expected_quantity * (tick.mid - ENTRY) - expected_fee

    order = ledger.orders_for_decision(result.paper_order.decision_id)[0]
    assert order.state is OrderLifecycleState.FILLED
    assert order.requested_quantity == pytest.approx(expected_quantity)
    assert order.requested_quantity <= HELD + 1e-12


@pytest.mark.parametrize("slippage_bps", SLIPPAGE_CASES)
def test_stop_loss_fills_the_full_position_under_adverse_slippage(slippage_bps: float) -> None:
    book = _seed_book(mark=97.0)
    result, outcome, ledger, tick = _run_exit(book, mark=97.0, slippage_bps=slippage_bps)
    assert result.exit_reason == "exit_stop_loss"
    _assert_flat_at_adverse_price(result, outcome, ledger, book, tick, slippage_bps=slippage_bps)
    assert outcome.plan is not None
    # The overshoot only exists when the sell price is below the mark.
    assert outcome.plan.quantity_capped_to_position is (slippage_bps > 0)


@pytest.mark.parametrize("slippage_bps", SLIPPAGE_CASES)
def test_trailing_stop_fills_the_full_position_under_adverse_slippage(
    slippage_bps: float,
) -> None:
    book = _seed_book(mark=108.0, high_water=110.0)
    result, outcome, ledger, tick = _run_exit(
        book,
        mark=108.0,
        slippage_bps=slippage_bps,
        exit_trailing_stop_pct=0.015,
        exit_take_profit_pct=0.10,
    )
    assert result.exit_reason == "exit_trailing_stop"
    _assert_flat_at_adverse_price(result, outcome, ledger, book, tick, slippage_bps=slippage_bps)


@pytest.mark.parametrize("slippage_bps", SLIPPAGE_CASES)
def test_take_profit_fills_the_full_position_under_adverse_slippage(slippage_bps: float) -> None:
    book = _seed_book(mark=105.0)
    result, outcome, ledger, tick = _run_exit(book, mark=105.0, slippage_bps=slippage_bps)
    assert result.exit_reason == "exit_take_profit"
    _assert_flat_at_adverse_price(result, outcome, ledger, book, tick, slippage_bps=slippage_bps)


@pytest.mark.parametrize("slippage_bps", SLIPPAGE_CASES)
def test_time_stop_fills_the_full_position_under_adverse_slippage(slippage_bps: float) -> None:
    book = _seed_book(mark=100.0, opened_at=NOW - timedelta(hours=25))
    result, outcome, ledger, tick = _run_exit(
        book, mark=100.0, slippage_bps=slippage_bps, exit_time_stop_bars=24
    )
    assert result.exit_reason == "exit_time_stop"
    _assert_flat_at_adverse_price(result, outcome, ledger, book, tick, slippage_bps=slippage_bps)


def test_reduced_exit_from_a_stale_mark_still_fills_at_most_the_held_quantity() -> None:
    """RiskEngine caps a SELL to the snapshot's exposure (stale, lower mark).

    The approved notional is then below the live exposure, so the planner's
    quantity is below the held quantity; the cap must not raise it back up.
    """

    book = _seed_book(mark=95.0)  # book still marked at 95
    result, outcome, ledger, tick = _run_exit(book, mark=97.0, slippage_bps=5.0)
    assert result.exit_reason == "exit_stop_loss"
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.REDUCE
    assert "sell_capped_to_position" in result.risk_result.reasons
    assert result.paper_order is not None
    assert result.paper_order.notional_usd == pytest.approx(HELD * 95.0)
    assert result.paper_order.max_quantity == pytest.approx(HELD)

    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.plan is not None
    fill_price = tick.mid * (1.0 - 5.0 / 10_000.0)
    expected_quantity = 95.0 / fill_price
    assert expected_quantity < HELD
    assert outcome.plan.quantity == pytest.approx(expected_quantity, rel=1e-6)
    assert outcome.plan.quantity <= HELD
    assert outcome.plan.quantity_capped_to_position is False
    assert book.positions["BTC"].quantity == pytest.approx(HELD - outcome.plan.quantity)
    assert book.positions["BTC"].quantity >= 0
    order = ledger.orders_for_decision(result.paper_order.decision_id)[0]
    assert order.requested_quantity <= HELD


def test_capped_exit_replay_after_restart_is_a_duplicate() -> None:
    book = _seed_book(mark=97.0)
    settings = _settings()
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    tick = _tick(97.0)
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=97.0)]
    result = pipe.process(tick, refs, book.snapshot(now=NOW), now=NOW)
    assert result.paper_order is not None
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=FEE_BPS, paper_slippage_bps=5.0)

    first = simulator.apply(result.paper_order, mid_usd=tick.mid, ledger=ledger, portfolio=book)
    cash_after = book.cash_usd
    second = simulator.apply(result.paper_order, mid_usd=tick.mid, ledger=ledger, portfolio=book)

    assert first.status is PaperFillStatus.FILLED
    assert second.status is PaperFillStatus.DUPLICATE
    assert book.cash_usd == pytest.approx(cash_after)
    assert book.positions["BTC"].quantity == 0
    assert len(ledger.processed_fill_ids) == 1
