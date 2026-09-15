"""Protective exits never oversell after adverse paper slippage (#130).

Regression cover for the two layers of the fix:

* ``exits.evaluate_position_exits`` sizes the exit notional at the worst-case
  execution price, so the planner's ``notional / execution_price`` conversion
  lands at or below the held quantity;
* ``ExecutionPlanner.plan`` clamps a reducing-only order down to the held
  quantity whatever price produced it, and the clamp can only ever *reduce*.

Before the fix a full stop-loss at the default ``PAPER_SLIPPAGE_BPS=5`` was
refused as a short sale: a risk-reducing order failed closed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from traderstack.config import Settings
from traderstack.execution.ledger import (
    ExecutionLedger,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.execution.paper_fill import (
    PaperFillSimulator,
    PaperFillStatus,
    adverse_fill_price_usd,
)
from traderstack.execution.planner import (
    ExecutionPlanner,
    ExecutionPlanRejected,
    ExitSizingRejected,
)
from traderstack.exits import ExitReason, evaluate_position_exits
from traderstack.metrics import record_paper_fill
from traderstack.models import HeldPosition, Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook, Position

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
QUANTITY = 1.0
ENTRY = 100.0
SLIPPAGE_BPS = 5.0


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "kill_switch": False,
        "trading_mode": "paper",
        "exit_stop_loss_pct": 0.02,
        "exit_take_profit_pct": 0.04,
        "exit_trailing_stop_pct": 0.0,
        "exit_time_stop_bars": 24,
        "paper_slippage_bps": SLIPPAGE_BPS,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _held(
    *,
    quantity: float = QUANTITY,
    high_water_price_usd: float = ENTRY,
    opened_at: datetime | None = NOW,
) -> HeldPosition:
    return HeldPosition(
        quantity=quantity,
        average_cost_usd=ENTRY,
        exposure_usd=quantity * ENTRY,
        opened_at=opened_at,
        high_water_price_usd=high_water_price_usd,
        entry_strategy_id="momentum_v1",
    )


def _book(*, quantity: float = QUANTITY) -> InMemoryPortfolioBook:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000.0)
    if quantity > 0:
        book.positions["BTC"] = Position(quantity=quantity, average_cost_usd=ENTRY)
        book.marks_usd["BTC"] = ENTRY
    return book


def _simulator(**overrides: float) -> PaperFillSimulator:
    planner = ExecutionPlanner(
        min_notional_usd=float(overrides.pop("min_notional_usd", 10.0)),
        lot_step=float(overrides.pop("lot_step", 1e-8)),
    )
    return PaperFillSimulator(
        planner=planner,
        paper_fee_bps=float(overrides.pop("paper_fee_bps", 10.0)),
        paper_slippage_bps=float(overrides.pop("paper_slippage_bps", SLIPPAGE_BPS)),
    )


def _intent(
    notional: float, *, reduce_only: bool = True, decision_id: str = "d1"
) -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id=decision_id,
        asset="BTC",
        side=Side.SELL,
        notional_usd=notional,
        reduce_only=reduce_only,
    )


# --- the four protective rules, end to end through the paper fill ---------------

_RULES = (
    # reason, mark, settings overrides, position overrides
    (ExitReason.STOP_LOSS, 97.0, {}, {}),
    (
        ExitReason.TRAILING_STOP,
        108.0,
        {"exit_stop_loss_pct": 0.0, "exit_take_profit_pct": 0.0, "exit_trailing_stop_pct": 0.05},
        {"high_water_price_usd": 120.0},
    ),
    (ExitReason.TAKE_PROFIT, 105.0, {}, {}),
    (
        ExitReason.TIME_STOP,
        100.5,
        {},
        {"opened_at": NOW - timedelta(hours=48)},
    ),
)


@pytest.mark.parametrize(
    ("reason", "mark", "overrides", "position"), _RULES, ids=lambda v: str(v)[:24]
)
def test_every_protective_rule_fills_the_whole_position_under_adverse_slippage(
    reason: ExitReason,
    mark: float,
    overrides: dict[str, object],
    position: dict[str, object],
) -> None:
    settings = _settings(**overrides)
    signal = evaluate_position_exits(
        settings=settings,
        asset="BTC",
        position=_held(**position),  # type: ignore[arg-type]
        mark_price_usd=mark,
        now=NOW,
        bar_seconds=3_600.0,
    )
    assert signal is not None
    assert signal.reason is reason
    assert signal.side is Side.SELL

    book = _book()
    simulator = _simulator()
    outcome = simulator.apply(
        _intent(signal.requested_notional_usd, decision_id=reason.value),
        mid_usd=mark,
        ledger=ExecutionLedger(),
        portfolio=book,
    )

    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.fill is not None and outcome.plan is not None
    # The whole position leaves the book and nothing is invented on top of it.
    assert outcome.fill.quantity <= QUANTITY
    assert outcome.fill.quantity == pytest.approx(QUANTITY)
    assert book.positions["BTC"].quantity == pytest.approx(0.0)
    assert book.positions["BTC"].quantity >= 0.0
    # Fee and notional stay consistent with the quantity that actually filled.
    fill_price = adverse_fill_price_usd(Side.SELL, mark, SLIPPAGE_BPS)
    assert outcome.fill.price_usd == pytest.approx(fill_price)
    assert outcome.fee_usd == pytest.approx(outcome.fill.quantity * fill_price * 10.0 / 10_000.0)
    assert outcome.fill.fee_usd == pytest.approx(outcome.fee_usd)


def test_reproduces_issue_130_full_stop_loss_no_longer_fails_closed() -> None:
    # The exact reproduction from the issue: 1.0 unit long at a $100 mark.
    settings = _settings()
    signal = evaluate_position_exits(
        settings=settings,
        asset="BTC",
        position=_held(),
        mark_price_usd=98.0,
        now=NOW,
        bar_seconds=3_600.0,
    )
    assert signal is not None
    fill_price = adverse_fill_price_usd(Side.SELL, 98.0, SLIPPAGE_BPS)
    # The old sizing (quantity * mark) asked for more units than were held.
    assert QUANTITY * 98.0 / fill_price > QUANTITY
    assert signal.requested_notional_usd / fill_price == pytest.approx(QUANTITY)


# --- the clamp is an invariant, not a sizing helper -----------------------------


def test_clamp_holds_even_when_the_notional_was_sized_at_the_mark() -> None:
    # Simulates a future slippage source that sizes at the mark again: the
    # planner still cannot plan more than the held quantity.
    book = _book()
    outcome = _simulator().apply(
        _intent(QUANTITY * ENTRY),
        mid_usd=ENTRY,
        ledger=ExecutionLedger(),
        portfolio=book,
    )
    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.plan is not None
    assert outcome.plan.quantity == pytest.approx(QUANTITY)
    assert outcome.fill is not None and outcome.fill.quantity <= QUANTITY
    assert book.positions["BTC"].quantity == pytest.approx(0.0)


def test_clamp_never_raises_a_smaller_exit_up_to_the_held_quantity() -> None:
    book = _book()
    half = QUANTITY * ENTRY / 2
    outcome = _simulator().apply(
        _intent(half), mid_usd=ENTRY, ledger=ExecutionLedger(), portfolio=book
    )
    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.fill is not None
    assert outcome.fill.quantity < QUANTITY
    assert book.positions["BTC"].quantity > 0


def test_clamp_is_not_available_to_an_entry_order() -> None:
    # A non-reducing SELL above the held quantity is still refused outright:
    # the clamp must never become a way to silently resize an entry.
    book = _book()
    outcome = _simulator().apply(
        _intent(QUANTITY * ENTRY * 5, reduce_only=False),
        mid_usd=ENTRY,
        ledger=ExecutionLedger(),
        portfolio=book,
    )
    assert outcome.status is PaperFillStatus.REJECTED
    assert outcome.reason is not None and "cannot sell" in outcome.reason
    assert book.positions["BTC"].quantity == pytest.approx(QUANTITY)


def test_planner_clamp_only_ever_reduces_quantity() -> None:
    planner = ExecutionPlanner(min_notional_usd=1.0)
    unclamped = planner.plan(_intent(50.0), execution_price_usd=100.0, reference_price_usd=100.0)
    generous = planner.plan(
        _intent(50.0),
        execution_price_usd=100.0,
        reference_price_usd=100.0,
        max_quantity=10.0,
    )
    assert generous.quantity == pytest.approx(unclamped.quantity)
    assert generous.notional_usd == pytest.approx(unclamped.notional_usd)


# --- a clamp to nothing is a clean, labelled rejection --------------------------


def test_reducing_order_with_no_position_is_labelled_not_a_validation_error() -> None:
    outcome = _simulator().apply(
        _intent(500.0), mid_usd=ENTRY, ledger=ExecutionLedger(), portfolio=_book(quantity=0.0)
    )
    assert outcome.status is PaperFillStatus.INVALID_EXIT_SIZE
    assert outcome.reason is not None and "no held quantity" in outcome.reason
    assert outcome.plan is None


def test_cap_below_the_lot_step_is_labelled_invalid_exit_sizing() -> None:
    simulator = _simulator(lot_step=0.1, min_notional_usd=1.0)
    outcome = simulator.apply(
        _intent(500.0), mid_usd=ENTRY, ledger=ExecutionLedger(), portfolio=_book(quantity=0.05)
    )
    assert outcome.status is PaperFillStatus.INVALID_EXIT_SIZE
    assert outcome.reason is not None and "rounds to zero" in outcome.reason


def test_clamped_exit_below_min_notional_is_labelled_apart_from_a_venue_rejection() -> None:
    clamped = _simulator(min_notional_usd=10.0).apply(
        _intent(500.0), mid_usd=ENTRY, ledger=ExecutionLedger(), portfolio=_book(quantity=0.05)
    )
    assert clamped.status is PaperFillStatus.INVALID_EXIT_SIZE
    assert clamped.reason is not None and "below minimum" in clamped.reason

    # An order the clamp never touched keeps the venue/data vocabulary.
    unclamped = _simulator(min_notional_usd=10.0).apply(
        _intent(4.0, decision_id="d2"),
        mid_usd=ENTRY,
        ledger=ExecutionLedger(),
        portfolio=_book(),
    )
    assert unclamped.status is PaperFillStatus.PLAN_REJECTED
    assert unclamped.status is not PaperFillStatus.INVALID_EXIT_SIZE


def test_exit_sizing_rejection_is_a_plan_rejection_for_existing_handlers() -> None:
    assert issubclass(ExitSizingRejected, ExecutionPlanRejected)
    with pytest.raises(ExecutionPlanRejected):
        ExecutionPlanner().plan(
            _intent(500.0),
            execution_price_usd=100.0,
            reference_price_usd=100.0,
            max_quantity=0.0,
        )


# --- idempotency: a replan can never grow the order -----------------------------


def test_replanned_exit_is_never_larger_than_the_held_quantity() -> None:
    # The submitter planned this decision at the ask, before the position was
    # partly reduced elsewhere. The paper fill must not honour the stale,
    # larger size against a smaller book.
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-stale",
            decision_id="d1",
            asset="BTC",
            side=Side.SELL,
            requested_quantity=QUANTITY,
            state=OrderLifecycleState.PLANNED,
            client_order_id="ts-stale",
        )
    )
    book = _book(quantity=0.4)
    outcome = _simulator().apply(
        _intent(QUANTITY * ENTRY), mid_usd=ENTRY, ledger=ledger, portfolio=book
    )
    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.fill is not None
    assert outcome.fill.quantity <= 0.4
    assert book.positions["BTC"].quantity == pytest.approx(0.0)
    assert book.positions["BTC"].quantity >= 0.0


def test_replan_does_not_increase_an_already_smaller_planned_quantity() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-small",
            decision_id="d1",
            asset="BTC",
            side=Side.SELL,
            requested_quantity=0.25,
            state=OrderLifecycleState.PLANNED,
            client_order_id="ts-small",
        )
    )
    book = _book()
    outcome = _simulator().apply(
        _intent(QUANTITY * ENTRY), mid_usd=ENTRY, ledger=ledger, portfolio=book
    )
    assert outcome.status is PaperFillStatus.FILLED, outcome.reason
    assert outcome.fill is not None
    assert outcome.fill.quantity == pytest.approx(0.25)
    assert book.positions["BTC"].quantity == pytest.approx(0.75)


# --- the operator-visible label -------------------------------------------------


def _counter(status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "traderstack_paper_fills_total",
            {"symbol": "BTC/USD", "side": "sell", "status": status},
        )
        or 0.0
    )


def test_invalid_exit_sizing_is_counted_apart_from_venue_and_data_rejections() -> None:
    invalid = PaperFillStatus.INVALID_EXIT_SIZE.value
    before_invalid = _counter(invalid)
    before_plan = _counter(PaperFillStatus.PLAN_REJECTED.value)
    before_rejected = _counter(PaperFillStatus.REJECTED.value)

    record_paper_fill("BTC/USD", "sell", invalid)

    assert _counter(invalid) == before_invalid + 1
    assert _counter(PaperFillStatus.PLAN_REJECTED.value) == before_plan
    assert _counter(PaperFillStatus.REJECTED.value) == before_rejected
    assert invalid not in {
        PaperFillStatus.PLAN_REJECTED.value,
        PaperFillStatus.REJECTED.value,
        PaperFillStatus.WITHHELD.value,
    }
