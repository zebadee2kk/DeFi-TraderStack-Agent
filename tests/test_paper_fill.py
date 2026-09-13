"""Paper-native fills: ALLOW books cash/positions/NAV without Hummingbot."""

from __future__ import annotations

import pytest

from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.ledger import (
    ExecutionLedger,
    ExecutionOrder,
    FeeSource,
    OrderLifecycleState,
)
from traderstack.execution.paper_fill import (
    PaperFillRejectReason,
    PaperFillSimulator,
    PaperFillStatus,
    adverse_fill_price_usd,
    paper_fill_id,
)
from traderstack.execution.planner import ExecutionPlanner
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook


def _intent(
    *,
    decision_id: str = "decision-1",
    side: Side = Side.BUY,
    notional_usd: float = 1_000.0,
) -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id=decision_id,
        asset="BTC",
        side=side,
        notional_usd=notional_usd,
    )


def _book(nav: float = 10_000.0) -> InMemoryPortfolioBook:
    return InMemoryPortfolioBook(starting_nav_usd=nav)


def test_adverse_fill_price_is_worse_than_mid() -> None:
    mid = 20_000.0
    assert adverse_fill_price_usd(Side.BUY, mid, 10.0) == pytest.approx(20_020.0)
    assert adverse_fill_price_usd(Side.SELL, mid, 10.0) == pytest.approx(19_980.0)


def test_paper_allow_changes_nav_cash_and_position() -> None:
    ledger = ExecutionLedger()
    book = _book()
    starting = book.nav_usd
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)

    outcome = simulator.apply(_intent(), mid_usd=20_000.0, ledger=ledger, portfolio=book)

    assert outcome.status is PaperFillStatus.FILLED
    assert outcome.applied
    # Fee leaves cash and never returns as inventory, so NAV moves even if
    # the book is still marked at the fill price.
    assert book.nav_usd != pytest.approx(starting)
    assert book.nav_usd == pytest.approx(starting - outcome.fee_usd)
    assert book.cash_usd is not None and book.cash_usd < starting
    assert book.positions["BTC"].quantity > 0
    order = next(iter(ledger.orders.values()))
    assert order.state is OrderLifecycleState.FILLED
    assert order.fee_source is FeeSource.MODELLED
    assert paper_fill_id(order.client_order_id or order.order_id) in ledger.processed_fill_ids


def test_paper_fee_reduces_nav_versus_a_zero_fee_fill() -> None:
    mid = 20_000.0
    free_book, fee_book = _book(), _book()
    free = PaperFillSimulator(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    charged = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=0.0)

    free.apply(
        _intent(decision_id="free"), mid_usd=mid, ledger=ExecutionLedger(), portfolio=free_book
    )
    charged_out = charged.apply(
        _intent(decision_id="fee"), mid_usd=mid, ledger=ExecutionLedger(), portfolio=fee_book
    )

    assert charged_out.fee_usd > 0
    # Same mid, no slippage: inventory is marked at the fill, so the only NAV
    # gap is the modelled fee leaving cash.
    assert fee_book.nav_usd == pytest.approx(free_book.nav_usd - charged_out.fee_usd)
    assert fee_book.nav_usd < 10_000


def test_restart_does_not_double_fill() -> None:
    ledger = ExecutionLedger()
    book = _book()
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)
    first = simulator.apply(_intent(), mid_usd=20_000.0, ledger=ledger, portfolio=book)
    nav_after = book.nav_usd
    cash_after = book.cash_usd

    second = simulator.apply(_intent(), mid_usd=20_000.0, ledger=ledger, portfolio=book)

    assert first.status is PaperFillStatus.FILLED
    assert second.status is PaperFillStatus.DUPLICATE
    assert book.nav_usd == pytest.approx(nav_after)
    assert book.cash_usd == pytest.approx(cash_after)
    assert len(ledger.processed_fill_ids) == 1


def test_existing_submitter_order_is_filled_at_its_planned_quantity() -> None:
    planner = ExecutionPlanner()
    plan = planner.plan(_intent(), execution_price_usd=20_010.0, reference_price_usd=20_000.0)
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id=plan.client_order_id,
            decision_id=plan.decision_id,
            asset=plan.asset,
            side=plan.side,
            requested_quantity=plan.quantity,
            state=OrderLifecycleState.SUBMITTED,
            client_order_id=plan.client_order_id,
            correlation_id=plan.correlation_id,
        )
    )
    book = _book()
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)

    outcome = simulator.apply(_intent(), mid_usd=20_000.0, ledger=ledger, portfolio=book)

    assert outcome.status is PaperFillStatus.FILLED
    order = ledger.orders[plan.client_order_id]
    assert order.filled_quantity == pytest.approx(plan.quantity)
    assert order.state is OrderLifecycleState.FILLED


def test_sell_without_position_is_rejected_and_does_not_touch_the_book() -> None:
    ledger = ExecutionLedger()
    book = _book()
    simulator = PaperFillSimulator()

    outcome = simulator.apply(
        _intent(side=Side.SELL), mid_usd=20_000.0, ledger=ledger, portfolio=book
    )

    assert outcome.status is PaperFillStatus.REJECTED
    assert "cannot sell" in (outcome.reason or "")
    assert book.nav_usd == pytest.approx(10_000)
    assert book.positions.get("BTC") is None or book.positions["BTC"].quantity == 0
    assert ledger.processed_fill_ids == set()


def test_non_paper_mode_is_refused() -> None:
    simulator = PaperFillSimulator(trading_mode="shadow")
    with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
        simulator.apply(_intent(), mid_usd=20_000.0, ledger=ExecutionLedger(), portfolio=_book())


def test_live_mode_is_refused() -> None:
    simulator = PaperFillSimulator(trading_mode="live")
    with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
        simulator.apply(_intent(), mid_usd=20_000.0, ledger=ExecutionLedger(), portfolio=_book())


# --- protective exit sizing (#130) ---


def _long_book(quantity: float = 1.0, price: float = 100.0) -> InMemoryPortfolioBook:
    book = _book()
    book.apply_fill("BTC", Side.BUY, quantity, price)
    book.mark("BTC", price)
    return book


def test_issue_130_reproduction_exit_fills_the_whole_position_at_5_bps() -> None:
    """1.0 BTC at a $100 mark, exit intent $100, 5 bps adverse slippage.

    The planner converts $100 back to 1.00050025 units at $99.95; the intent's
    ``max_quantity`` caps that to the held 1.0 so the stop-loss fills.
    """

    book = _long_book()
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)
    exit_intent = PaperOrderIntent(
        decision_id="exit-1", asset="BTC", side=Side.SELL, notional_usd=100.0, max_quantity=1.0
    )

    outcome = simulator.apply(exit_intent, mid_usd=100.0, ledger=ledger, portfolio=book)

    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.reason_code is None
    assert outcome.fill is not None
    assert outcome.fill.quantity == pytest.approx(1.0)
    assert outcome.fill.price_usd == pytest.approx(99.95)
    assert book.positions["BTC"].quantity == 0
    fee = 1.0 * 99.95 * 10.0 / 10_000.0
    assert outcome.fee_usd == pytest.approx(fee)
    assert book.cash_usd == pytest.approx(10_000.0 - 100.0 + 99.95 - fee)
    assert outcome.plan is not None
    assert outcome.plan.quantity_capped_to_position is True


def test_same_oversized_sell_without_max_quantity_is_still_a_short_sale_rejection() -> None:
    """Documents the pre-fix behaviour for a non-exit SELL larger than the book."""

    book = _long_book()
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)

    outcome = simulator.apply(
        _intent(side=Side.SELL, notional_usd=100.0), mid_usd=100.0, ledger=ledger, portfolio=book
    )

    assert outcome.status is PaperFillStatus.REJECTED
    assert outcome.reason_code is PaperFillRejectReason.SHORT_SALE
    assert (outcome.reason or "").startswith("short_sale: cannot sell")
    assert book.positions["BTC"].quantity == pytest.approx(1.0)
    assert ledger.processed_fill_ids == set()


def test_reason_codes_for_invalid_mid_and_planner_rejection() -> None:
    simulator = PaperFillSimulator()
    invalid = simulator.apply(_intent(), mid_usd=0.0, ledger=ExecutionLedger(), portfolio=_book())
    assert invalid.status is PaperFillStatus.REJECTED
    assert invalid.reason_code is PaperFillRejectReason.INVALID_MID
    assert (invalid.reason or "").startswith("invalid_mid:")

    dust = PaperFillSimulator(planner=ExecutionPlanner(min_notional_usd=5_000.0))
    rejected = dust.apply(_intent(), mid_usd=20_000.0, ledger=ExecutionLedger(), portfolio=_book())
    assert rejected.status is PaperFillStatus.PLAN_REJECTED
    assert rejected.reason_code is PaperFillRejectReason.PLAN_REJECTED
    assert (rejected.reason or "").startswith("plan_rejected:")


def test_reason_code_for_a_terminal_decision() -> None:
    planner = ExecutionPlanner()
    plan = planner.plan(_intent(), execution_price_usd=20_000.0, reference_price_usd=20_000.0)
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id=plan.client_order_id,
            decision_id=plan.decision_id,
            asset=plan.asset,
            side=plan.side,
            requested_quantity=plan.quantity,
            state=OrderLifecycleState.REJECTED,
            client_order_id=plan.client_order_id,
            correlation_id=plan.correlation_id,
        )
    )
    outcome = PaperFillSimulator().apply(
        _intent(), mid_usd=20_000.0, ledger=ledger, portfolio=_book()
    )
    assert outcome.status is PaperFillStatus.REJECTED
    assert outcome.reason_code is PaperFillRejectReason.DECISION_TERMINAL


def test_exit_intent_exceeding_the_book_is_flagged_as_exit_sizing_invalid() -> None:
    """A carried max_quantity larger than the book is a sizing bug, not venue noise."""

    book = _long_book(quantity=0.5)
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)
    hostile = PaperOrderIntent(
        decision_id="exit-2", asset="BTC", side=Side.SELL, notional_usd=100.0, max_quantity=1.0
    )

    outcome = simulator.apply(hostile, mid_usd=100.0, ledger=ledger, portfolio=book)

    assert outcome.status is PaperFillStatus.REJECTED
    assert outcome.reason_code is PaperFillRejectReason.EXIT_SIZING_INVALID
    assert (outcome.reason or "").startswith("exit_sizing_invalid: cannot sell")
    assert book.positions["BTC"].quantity == pytest.approx(0.5)
    assert ledger.processed_fill_ids == set()


def test_capped_exit_replay_is_a_duplicate_and_leaves_the_book_unchanged() -> None:
    book = _long_book()
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)
    exit_intent = PaperOrderIntent(
        decision_id="exit-3", asset="BTC", side=Side.SELL, notional_usd=100.0, max_quantity=1.0
    )
    first = simulator.apply(exit_intent, mid_usd=100.0, ledger=ledger, portfolio=book)
    cash_after = book.cash_usd

    second = simulator.apply(exit_intent, mid_usd=100.0, ledger=ledger, portfolio=book)

    assert first.status is PaperFillStatus.FILLED
    assert second.status is PaperFillStatus.DUPLICATE
    assert second.reason_code is None
    assert book.cash_usd == pytest.approx(cash_after)
    assert book.positions["BTC"].quantity == 0
    assert len(ledger.processed_fill_ids) == 1
