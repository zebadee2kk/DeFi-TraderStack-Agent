from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from traderstack.models import Side


class OrderLifecycleState(StrEnum):
    """Order lifecycle per docs/EXECUTION-ARCHITECTURE.md.

    ``PLANNED`` is written before the venue call so a crash mid-submission still
    leaves evidence that the decision was acted on. ``SUBMISSION_UNCERTAIN`` is
    the fail-closed state used when a submission timed out or returned 5xx: the
    venue may or may not know the order, so no retry is permitted until
    reconciliation proves the venue does not know the client order id.
    """

    PLANNED = "planned"
    SUBMITTED = "submitted"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    ACKNOWLEDGED = "acknowledged"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


TERMINAL_ORDER_STATES: frozenset[OrderLifecycleState] = frozenset(
    {
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.EXPIRED,
    }
)

_CLOSING_STATES: frozenset[OrderLifecycleState] = frozenset(
    {
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.EXPIRED,
    }
)

# Legal forward transitions. A transition to the current state is always legal
# (reconciliation re-applies the same venue status on every pass); every other
# transition out of a terminal state is illegal. Nothing may move backwards:
# PARTIALLY_FILLED can never return to SUBMITTED/OPEN.
_ALLOWED_TRANSITIONS: dict[OrderLifecycleState, frozenset[OrderLifecycleState]] = {
    # Pre-submission: the venue truth is entirely unknown, so any discovered
    # state is legal once reconciliation reports one.
    OrderLifecycleState.PLANNED: frozenset(
        {
            OrderLifecycleState.SUBMITTED,
            OrderLifecycleState.SUBMISSION_UNCERTAIN,
            OrderLifecycleState.ACKNOWLEDGED,
            OrderLifecycleState.OPEN,
        }
        | _CLOSING_STATES
    ),
    OrderLifecycleState.SUBMITTED: frozenset(
        {
            OrderLifecycleState.SUBMISSION_UNCERTAIN,
            OrderLifecycleState.ACKNOWLEDGED,
            OrderLifecycleState.OPEN,
        }
        | _CLOSING_STATES
    ),
    OrderLifecycleState.SUBMISSION_UNCERTAIN: frozenset(
        {
            OrderLifecycleState.SUBMITTED,
            OrderLifecycleState.ACKNOWLEDGED,
            OrderLifecycleState.OPEN,
        }
        | _CLOSING_STATES
    ),
    # Once the venue has acknowledged the order, submission is no longer
    # uncertain and can never become uncertain again.
    OrderLifecycleState.ACKNOWLEDGED: frozenset({OrderLifecycleState.OPEN} | _CLOSING_STATES),
    OrderLifecycleState.OPEN: frozenset(_CLOSING_STATES),
    OrderLifecycleState.PARTIALLY_FILLED: frozenset(
        {
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.EXPIRED,
        }
    ),
    OrderLifecycleState.FILLED: frozenset(),
    OrderLifecycleState.CANCELLED: frozenset(),
    OrderLifecycleState.REJECTED: frozenset(),
    OrderLifecycleState.EXPIRED: frozenset(),
}


class IllegalStateTransition(ValueError):
    """Raised when an order is moved through an illegal lifecycle transition."""

    def __init__(
        self,
        order_id: str,
        current: OrderLifecycleState,
        requested: OrderLifecycleState,
    ) -> None:
        super().__init__(f"illegal transition {current} -> {requested} for order {order_id}")
        self.order_id = order_id
        self.current = current
        self.requested = requested


def is_legal_transition(current: OrderLifecycleState, requested: OrderLifecycleState) -> bool:
    if current is requested:
        return True
    return requested in _ALLOWED_TRANSITIONS[current]


class ExecutionFill(BaseModel):
    fill_id: str
    order_id: str
    asset: str
    side: Side
    quantity: float = Field(gt=0)
    price_usd: float = Field(gt=0)
    fee_usd: float = Field(default=0.0, ge=0)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionOrder(BaseModel):
    order_id: str
    decision_id: str
    asset: str
    side: Side
    requested_quantity: float = Field(gt=0)
    state: OrderLifecycleState = OrderLifecycleState.SUBMITTED
    filled_quantity: float = Field(default=0.0, ge=0)
    average_fill_price_usd: float | None = Field(default=None, gt=0)
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # --- execution hardening (Epic 8) ---
    # ``order_id`` is the ledger primary key. When the submitter plans an order it
    # is the deterministic client order id (the idempotency key) and the venue's
    # own id lands in ``venue_order_id`` once the submission returns.
    client_order_id: str | None = None
    venue_order_id: str | None = None
    correlation_id: str | None = None
    submission_attempts: int = 0
    reason: str | None = None


class ExecutionLedgerState(BaseModel):
    """Serialisable ledger snapshot, persisted alongside the portfolio checkpoint."""

    orders: dict[str, ExecutionOrder] = Field(default_factory=dict)
    processed_fill_ids: list[str] = Field(default_factory=list)


@dataclass
class ExecutionLedger:
    orders: dict[str, ExecutionOrder] = field(default_factory=dict)
    processed_fill_ids: set[str] = field(default_factory=set)

    @classmethod
    def from_state(cls, state: ExecutionLedgerState) -> ExecutionLedger:
        return cls(
            orders={key: order.model_copy(deep=True) for key, order in state.orders.items()},
            processed_fill_ids=set(state.processed_fill_ids),
        )

    def state(self) -> ExecutionLedgerState:
        return ExecutionLedgerState(
            orders={key: order.model_copy(deep=True) for key, order in self.orders.items()},
            processed_fill_ids=sorted(self.processed_fill_ids),
        )

    def register_order(self, order: ExecutionOrder) -> None:
        existing = self.orders.get(order.order_id)
        if existing is not None and existing != order:
            raise ValueError(f"conflicting duplicate order id {order.order_id}")
        self.orders[order.order_id] = order

    def find_order(self, identifier: str) -> ExecutionOrder | None:
        """Resolve an order by ledger key, venue order id or client order id."""

        order = self.orders.get(identifier)
        if order is not None:
            return order
        for candidate in self.orders.values():
            if identifier in (candidate.venue_order_id, candidate.client_order_id):
                return candidate
        return None

    def orders_for_decision(self, decision_id: str) -> list[ExecutionOrder]:
        return [order for order in self.orders.values() if order.decision_id == decision_id]

    def has_order_for_decision(self, decision_id: str) -> bool:
        return any(order.decision_id == decision_id for order in self.orders.values())

    def update_order_state(self, order_id: str, state: OrderLifecycleState) -> None:
        order = self.find_order(order_id)
        if order is None:
            raise KeyError(f"unknown order id {order_id}")
        self._transition(order, state)

    def record_fill(self, fill: ExecutionFill) -> bool:
        if fill.fill_id in self.processed_fill_ids:
            return False
        order = self.find_order(fill.order_id)
        if order is None:
            raise KeyError(f"orphan fill {fill.fill_id} references unknown order {fill.order_id}")
        if fill.asset.upper() != order.asset.upper() or fill.side is not order.side:
            raise ValueError(f"fill {fill.fill_id} does not match order {fill.order_id}")
        new_filled_quantity = order.filled_quantity + fill.quantity
        if new_filled_quantity > order.requested_quantity + 1e-12:
            raise ValueError(f"fill {fill.fill_id} overfills order {fill.order_id}")

        next_state = (
            OrderLifecycleState.FILLED
            if abs(new_filled_quantity - order.requested_quantity) <= 1e-12
            else OrderLifecycleState.PARTIALLY_FILLED
        )
        # Reject the fill before mutating quantities if the order is terminal.
        self._transition(order, next_state)

        previous_notional = (order.average_fill_price_usd or 0.0) * order.filled_quantity
        new_notional = previous_notional + fill.price_usd * fill.quantity
        order.filled_quantity = new_filled_quantity
        order.average_fill_price_usd = new_notional / new_filled_quantity
        order.last_updated_at = datetime.now(UTC)
        self.processed_fill_ids.add(fill.fill_id)
        return True

    @staticmethod
    def _transition(order: ExecutionOrder, state: OrderLifecycleState) -> None:
        if not is_legal_transition(order.state, state):
            raise IllegalStateTransition(order.order_id, order.state, state)
        order.state = state
        order.last_updated_at = datetime.now(UTC)
