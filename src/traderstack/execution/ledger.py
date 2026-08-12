from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from traderstack.models import Side

# Fill quantities compare a requested amount (notional / price) against
# exchange-rounded decimals; use a relative tolerance so large quantities
# are not tripped up by float ULPs.
_QUANTITY_REL_TOL = 1e-9
_QUANTITY_ABS_TOL = 1e-12


class OrderLifecycleState(StrEnum):
    SUBMITTED = "submitted"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ExecutionFill(BaseModel):
    fill_id: str
    order_id: str
    asset: str
    side: Side
    quantity: float = Field(gt=0, lt=1e15, allow_inf_nan=False)
    price_usd: float = Field(gt=0, lt=1e12, allow_inf_nan=False)
    fee_usd: float = Field(default=0.0, ge=0, lt=1e12, allow_inf_nan=False)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionOrder(BaseModel):
    order_id: str
    decision_id: str
    asset: str
    side: Side
    requested_quantity: float = Field(gt=0, lt=1e15, allow_inf_nan=False)
    state: OrderLifecycleState = OrderLifecycleState.SUBMITTED
    filled_quantity: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    average_fill_price_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LedgerState(BaseModel):
    orders: dict[str, ExecutionOrder] = Field(default_factory=dict)
    processed_fill_ids: list[str] = Field(default_factory=list)


@dataclass
class ExecutionLedger:
    orders: dict[str, ExecutionOrder] = field(default_factory=dict)
    processed_fill_ids: set[str] = field(default_factory=set)

    @classmethod
    def from_state(cls, state: LedgerState) -> ExecutionLedger:
        return cls(
            orders={order_id: order.model_copy() for order_id, order in state.orders.items()},
            processed_fill_ids=set(state.processed_fill_ids),
        )

    def state(self) -> LedgerState:
        return LedgerState(
            orders={order_id: order.model_copy() for order_id, order in self.orders.items()},
            processed_fill_ids=sorted(self.processed_fill_ids),
        )

    def register_order(self, order: ExecutionOrder) -> None:
        existing = self.orders.get(order.order_id)
        if existing is not None and existing != order:
            raise ValueError(f"conflicting duplicate order id {order.order_id}")
        self.orders[order.order_id] = order

    def update_order_state(self, order_id: str, state: OrderLifecycleState) -> None:
        order = self.orders.get(order_id)
        if order is None:
            raise KeyError(f"unknown order id {order_id}")
        order.state = state
        order.last_updated_at = datetime.now(UTC)

    def validate_fill(self, fill: ExecutionFill) -> bool:
        """Check a fill without consuming its idempotency id.

        Returns False for an already-processed fill, raises for a fill that
        contradicts its order, and returns True when the fill can be applied.
        Callers must apply side effects (portfolio update) BEFORE commit_fill
        so a failed application never burns the fill id.
        """
        if fill.fill_id in self.processed_fill_ids:
            return False
        order = self.orders.get(fill.order_id)
        if order is None:
            raise KeyError(f"orphan fill {fill.fill_id} references unknown order {fill.order_id}")
        if fill.asset.upper() != order.asset.upper() or fill.side is not order.side:
            raise ValueError(f"fill {fill.fill_id} does not match order {fill.order_id}")
        new_filled_quantity = order.filled_quantity + fill.quantity
        overfill_limit = order.requested_quantity * (1 + _QUANTITY_REL_TOL) + _QUANTITY_ABS_TOL
        if new_filled_quantity > overfill_limit:
            raise ValueError(f"fill {fill.fill_id} overfills order {fill.order_id}")
        return True

    def commit_fill(self, fill: ExecutionFill) -> None:
        order = self.orders[fill.order_id]
        new_filled_quantity = order.filled_quantity + fill.quantity
        previous_notional = (order.average_fill_price_usd or 0.0) * order.filled_quantity
        new_notional = previous_notional + fill.price_usd * fill.quantity
        order.filled_quantity = new_filled_quantity
        order.average_fill_price_usd = new_notional / new_filled_quantity
        order.state = (
            OrderLifecycleState.FILLED
            if math.isclose(
                new_filled_quantity,
                order.requested_quantity,
                rel_tol=_QUANTITY_REL_TOL,
                abs_tol=_QUANTITY_ABS_TOL,
            )
            or new_filled_quantity > order.requested_quantity
            else OrderLifecycleState.PARTIALLY_FILLED
        )
        order.last_updated_at = datetime.now(UTC)
        self.processed_fill_ids.add(fill.fill_id)

    def record_fill(self, fill: ExecutionFill) -> bool:
        if not self.validate_fill(fill):
            return False
        self.commit_fill(fill)
        return True
