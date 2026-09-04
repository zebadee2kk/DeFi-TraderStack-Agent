"""Deterministic execution planner (docs/EXECUTION-ARCHITECTURE.md -> Execution Planner).

Converts an approved ``PaperOrderIntent`` plus an execution price into a single
venue child order. Pure and side-effect free: no I/O, no clock, no randomness,
so the same decision always produces the same client order id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from pydantic import BaseModel, Field

from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent

# Namespace constant so the idempotency key is stable across processes and
# restarts but cannot collide with identifiers minted by another system.
_CLIENT_ORDER_ID_NAMESPACE = b"traderstack.execution.client_order_id.v1"
_CORRELATION_ID_NAMESPACE = b"traderstack.execution.correlation_id.v1"


class ExecutionPlanRejected(ValueError):
    """Raised when an approved intent cannot be turned into a safe child order.

    Rejection is always terminal for that decision: the planner never rounds a
    trade up, never widens a slippage bound and never retries.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ExecutionPlan(BaseModel):
    """A single venue child order, fully constrained and identified."""

    decision_id: str
    client_order_id: str
    correlation_id: str
    asset: str
    side: Side
    venue: str
    trading_pair: str
    quantity: float = Field(gt=0)
    execution_price_usd: float = Field(gt=0)
    reference_price_usd: float = Field(gt=0)
    notional_usd: float = Field(gt=0)
    requested_notional_usd: float = Field(gt=0)
    slippage_bps: float = Field(ge=0)


def client_order_id_for(decision_id: str, *, prefix: str = "ts") -> str:
    """Deterministic idempotency key derived from the decision id.

    Short enough (<= 24 chars) for venues that cap client order ids at 32/36
    characters, and stable so a replayed or restarted submission of the same
    decision produces the same key.
    """

    digest = hashlib.blake2s(
        decision_id.encode("utf-8"), digest_size=10, person=_CLIENT_ORDER_ID_NAMESPACE[:8]
    ).hexdigest()
    return f"{prefix}-{digest}"


def correlation_id_for(decision_id: str) -> str:
    """Deterministic correlation id tying decision -> order -> fill in the audit trail."""

    digest = hashlib.blake2s(
        decision_id.encode("utf-8"), digest_size=16, person=_CORRELATION_ID_NAMESPACE[:8]
    ).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


@dataclass(frozen=True)
class ExecutionPlanner:
    """Applies size, slippage and identity policy to an approved intent.

    ``lot_step``      venue quantity increment; quantities round *down* so a
                      rounded order can never exceed the approved notional.
    ``min_notional_usd``
                      reject rather than submit dust the venue would bounce.
    ``max_slippage_bps``
                      reject when the execution price deviates from the
                      pipeline's validated tick by more than this, in either
                      direction — a large favourable deviation is as much a
                      data-integrity signal as an adverse one.
    """

    lot_step: float = 1e-8
    min_notional_usd: float = 10.0
    max_slippage_bps: float = 50.0
    quote_currency: str = "USD"
    client_order_id_prefix: str = "ts"

    def __post_init__(self) -> None:
        if self.lot_step <= 0:
            raise ValueError("lot_step must be positive")
        if self.min_notional_usd <= 0:
            raise ValueError("min_notional_usd must be positive")
        if self.max_slippage_bps < 0:
            raise ValueError("max_slippage_bps must not be negative")

    def plan(
        self,
        intent: PaperOrderIntent,
        *,
        execution_price_usd: float,
        reference_price_usd: float,
    ) -> ExecutionPlan:
        if execution_price_usd <= 0:
            raise ExecutionPlanRejected("execution price must be positive")
        if reference_price_usd <= 0:
            raise ExecutionPlanRejected("reference price must be positive")

        slippage_bps = abs(execution_price_usd - reference_price_usd) / reference_price_usd * 10_000
        if slippage_bps > self.max_slippage_bps:
            raise ExecutionPlanRejected(
                f"execution price deviates {slippage_bps:.2f} bps from the validated tick, "
                f"limit {self.max_slippage_bps:.2f} bps"
            )

        quantity = self._round_to_lot(intent.notional_usd / execution_price_usd)
        if quantity <= 0:
            raise ExecutionPlanRejected(f"quantity rounds to zero at lot step {self.lot_step}")

        notional = quantity * execution_price_usd
        if notional < self.min_notional_usd:
            raise ExecutionPlanRejected(
                f"order notional {notional:.2f} USD below minimum {self.min_notional_usd:.2f} USD"
            )

        return ExecutionPlan(
            decision_id=intent.decision_id,
            client_order_id=client_order_id_for(
                intent.decision_id, prefix=self.client_order_id_prefix
            ),
            correlation_id=correlation_id_for(intent.decision_id),
            asset=intent.asset.upper(),
            side=intent.side,
            venue=intent.venue,
            trading_pair=f"{intent.asset.upper()}-{self.quote_currency}",
            quantity=quantity,
            execution_price_usd=execution_price_usd,
            reference_price_usd=reference_price_usd,
            notional_usd=notional,
            requested_notional_usd=intent.notional_usd,
            slippage_bps=slippage_bps,
        )

    def _round_to_lot(self, quantity: float) -> float:
        try:
            step = Decimal(str(self.lot_step))
            rounded = (Decimal(str(quantity)) / step).to_integral_value(rounding=ROUND_DOWN) * step
        except (InvalidOperation, ValueError) as exc:  # pragma: no cover - guarded by __post_init__
            raise ExecutionPlanRejected(f"cannot round quantity to lot step: {exc}") from exc
        return float(rounded)
