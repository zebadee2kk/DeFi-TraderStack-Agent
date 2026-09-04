import pytest

from traderstack.execution.ledger import (
    TERMINAL_ORDER_STATES,
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    IllegalStateTransition,
    OrderLifecycleState,
    is_legal_transition,
)
from traderstack.models import Side


def ledger_with_order(
    state: OrderLifecycleState = OrderLifecycleState.SUBMITTED,
    *,
    quantity: float = 1.0,
) -> ExecutionLedger:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=quantity,
            state=state,
        )
    )
    return ledger


def test_documented_lifecycle_states_exist() -> None:
    """docs/EXECUTION-ARCHITECTURE.md order lifecycle."""

    for name in (
        "PLANNED",
        "SUBMITTED",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "EXPIRED",
    ):
        assert hasattr(OrderLifecycleState, name)
    assert TERMINAL_ORDER_STATES == {
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.EXPIRED,
    }


@pytest.mark.parametrize("terminal", sorted(TERMINAL_ORDER_STATES))
@pytest.mark.parametrize(
    "target",
    [
        OrderLifecycleState.SUBMITTED,
        OrderLifecycleState.ACKNOWLEDGED,
        OrderLifecycleState.OPEN,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.SUBMISSION_UNCERTAIN,
    ],
)
def test_terminal_states_never_reopen(
    terminal: OrderLifecycleState, target: OrderLifecycleState
) -> None:
    ledger = ledger_with_order(terminal)
    with pytest.raises(IllegalStateTransition):
        ledger.update_order_state("o1", target)
    assert ledger.orders["o1"].state is terminal


def test_terminal_state_may_be_reasserted_by_reconciliation() -> None:
    """Every reconciliation pass re-applies the venue status; that must be a no-op."""

    ledger = ledger_with_order(OrderLifecycleState.FILLED)
    ledger.update_order_state("o1", OrderLifecycleState.FILLED)
    assert ledger.orders["o1"].state is OrderLifecycleState.FILLED


@pytest.mark.parametrize(
    "target",
    [
        OrderLifecycleState.SUBMITTED,
        OrderLifecycleState.ACKNOWLEDGED,
        OrderLifecycleState.OPEN,
        OrderLifecycleState.PLANNED,
    ],
)
def test_partially_filled_cannot_go_backwards(target: OrderLifecycleState) -> None:
    ledger = ledger_with_order(OrderLifecycleState.PARTIALLY_FILLED)
    with pytest.raises(IllegalStateTransition, match="illegal transition"):
        ledger.update_order_state("o1", target)


def test_acknowledged_order_can_never_become_uncertain_again() -> None:
    ledger = ledger_with_order(OrderLifecycleState.ACKNOWLEDGED)
    with pytest.raises(IllegalStateTransition):
        ledger.update_order_state("o1", OrderLifecycleState.SUBMISSION_UNCERTAIN)


def test_forward_lifecycle_is_legal() -> None:
    ledger = ledger_with_order(OrderLifecycleState.PLANNED)
    for state in (
        OrderLifecycleState.SUBMITTED,
        OrderLifecycleState.ACKNOWLEDGED,
        OrderLifecycleState.OPEN,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.FILLED,
    ):
        ledger.update_order_state("o1", state)
        assert ledger.orders["o1"].state is state


def test_uncertain_submission_may_resolve_to_any_venue_truth() -> None:
    for state in (
        OrderLifecycleState.SUBMITTED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.EXPIRED,
    ):
        assert is_legal_transition(OrderLifecycleState.SUBMISSION_UNCERTAIN, state)


def test_expired_is_reachable_from_a_working_order() -> None:
    ledger = ledger_with_order(OrderLifecycleState.OPEN)
    ledger.update_order_state("o1", OrderLifecycleState.EXPIRED)
    assert ledger.orders["o1"].state is OrderLifecycleState.EXPIRED


def test_fill_on_a_terminal_order_is_refused_without_mutating_quantities() -> None:
    ledger = ledger_with_order(OrderLifecycleState.CANCELLED, quantity=1.0)
    with pytest.raises(IllegalStateTransition):
        ledger.record_fill(
            ExecutionFill(
                fill_id="late",
                order_id="o1",
                asset="BTC",
                side=Side.BUY,
                quantity=0.5,
                price_usd=20_000,
            )
        )
    order = ledger.orders["o1"]
    assert order.filled_quantity == 0
    assert order.state is OrderLifecycleState.CANCELLED
    assert "late" not in ledger.processed_fill_ids


def test_unknown_order_still_raises_key_error() -> None:
    ledger = ExecutionLedger()
    with pytest.raises(KeyError):
        ledger.update_order_state("nope", OrderLifecycleState.FILLED)


def test_orders_are_resolvable_by_venue_and_client_order_id() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-abc",
            decision_id="d9",
            asset="ETH",
            side=Side.BUY,
            requested_quantity=1.0,
            client_order_id="ts-abc",
            venue_order_id="venue-77",
        )
    )
    assert ledger.find_order("ts-abc") is ledger.orders["ts-abc"]
    assert ledger.find_order("venue-77") is ledger.orders["ts-abc"]
    assert ledger.find_order("unknown") is None
    assert ledger.has_order_for_decision("d9")
    assert not ledger.has_order_for_decision("d8")

    # A venue fill keyed by the venue's own id still lands on our order.
    assert ledger.record_fill(
        ExecutionFill(
            fill_id="f1",
            order_id="venue-77",
            asset="ETH",
            side=Side.BUY,
            quantity=1.0,
            price_usd=1_000,
        )
    )
    assert ledger.orders["ts-abc"].state is OrderLifecycleState.FILLED
