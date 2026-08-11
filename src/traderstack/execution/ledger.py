from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from traderstack.models import Side


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


@dataclass
class ExecutionLedger:
    orders: dict[str, ExecutionOrder] = field(default_factory=dict)
    processed_fill_ids: set[str] = field(default_factory=set)

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

    def record_fill(self, fill: ExecutionFill) -> bool:
        if fill.fill_id in self.processed_fill_ids:
            return False
        order = self.orders.get(fill.order_id)
        if order is None:
            raise KeyError(f"orphan fill {fill.fill_id} references unknown order {fill.order_id}")
        if fill.asset.upper() != order.asset.upper() or fill.side is not order.side:
            raise ValueError(f"fill {fill.fill_id} does not match order {fill.order_id}")
        new_filled_quantity = order.filled_quantity + fill.quantity
        if new_filled_quantity > order.requested_quantity + 1e-12:
            raise ValueError(f"fill {fill.fill_id} overfills order {fill.order_id}")

        previous_notional = (order.average_fill_price_usd or 0.0) * order.filled_quantity
        new_notional = previous_notional + fill.price_usd * fill.quantity
        order.filled_quantity = new_filled_quantity
        order.average_fill_price_usd = new_notional / new_filled_quantity
        order.state = (
            OrderLifecycleState.FILLED
            if abs(new_filled_quantity - order.requested_quantity) <= 1e-12
            else OrderLifecycleState.PARTIALLY_FILLED
        )
        order.last_updated_at = datetime.now(UTC)
        self.processed_fill_ids.add(fill.fill_id)
        return True
